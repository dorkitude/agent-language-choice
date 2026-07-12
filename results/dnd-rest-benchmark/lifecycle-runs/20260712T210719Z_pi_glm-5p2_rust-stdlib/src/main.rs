use std::collections::HashMap;
use std::env;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

#[derive(Clone, Debug)]
struct Condition {
    condition: String,
    remaining_rounds: i64,
}

#[derive(Clone, Debug)]
struct Combatant {
    name: String,
    dex: i64,
    score: i64,
}

#[derive(Clone, Debug)]
struct CombatSession {
    id: String,
    round: i64,
    turn_index: i64,
    order: Vec<Combatant>,
    conditions: HashMap<String, Vec<Condition>>,
}

type State = Arc<Mutex<HashMap<String, CombatSession>>>;

fn main() -> std::io::Result<()> {
    let port = env::var("PORT").unwrap_or_else(|_| "8080".to_string());
    let state: State = Arc::new(Mutex::new(HashMap::new()));
    let listener = TcpListener::bind(format!("127.0.0.1:{port}"))?;
    for stream in listener.incoming() {
        if let Ok(stream) = stream {
            let state = Arc::clone(&state);
            thread::spawn(move || {
                let _ = handle(stream, state);
            });
        }
    }
    Ok(())
}

fn handle(stream: TcpStream, state: State) -> std::io::Result<()> {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(10)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(10)));
    let mut writer = stream.try_clone()?;
    let mut reader = BufReader::new(stream);

    let mut request_line = String::new();
    let n = reader.read_line(&mut request_line)?;
    if n == 0 {
        return Ok(());
    }

    let mut content_length: usize = 0;
    let mut expect_continue = false;
    loop {
        let mut h = String::new();
        let n = reader.read_line(&mut h)?;
        if n == 0 {
            break;
        }
        let trimmed = h.trim();
        if trimmed.is_empty() {
            break;
        }
        if let Some((k, v)) = trimmed.split_once(':') {
            let key = k.trim();
            let val = v.trim();
            if key.eq_ignore_ascii_case("content-length") {
                content_length = val.parse().unwrap_or(0);
            } else if key.eq_ignore_ascii_case("expect")
                && val.eq_ignore_ascii_case("100-continue")
            {
                expect_continue = true;
            }
        }
    }

    if expect_continue {
        writer.write_all(b"HTTP/1.1 100 Continue\r\n\r\n")?;
    }

    let mut body = vec![0u8; content_length];
    if content_length > 0 {
        reader.read_exact(&mut body)?;
    }
    let body_str = String::from_utf8_lossy(&body);

    let resp = route(request_line.trim(), &body_str, &state);
    writer.write_all(resp.as_bytes())?;
    writer.flush()?;
    Ok(())
}

fn route(request_line: &str, body: &str, state: &State) -> String {
    let parts: Vec<&str> = request_line.split_whitespace().collect();
    if parts.len() < 2 {
        return build_response(400, r#"{"error":"bad request"}"#.to_string());
    }
    let method = parts[0];
    let path = parts[1].split('?').next().unwrap_or(parts[1]);
    match (method, path) {
        ("GET", "/health") => build_response(200, r#"{"ok":true}"#.to_string()),
        ("POST", "/v1/dice/stats") => dice_stats(body),
        ("POST", "/v1/checks/ability") => ability_check(body),
        ("POST", "/v1/encounters/adjusted-xp") => adjusted_xp(body),
        ("POST", "/v1/initiative/order") => initiative_order(body),
        ("POST", "/v1/characters/ability-modifier") => ability_modifier(body),
        ("POST", "/v1/characters/proficiency") => proficiency(body),
        ("POST", "/v1/characters/derived-stats") => derived_stats(body),
        ("POST", "/v1/combat/sessions") => create_combat_session(body, state),
        _ => {
            let segs: Vec<&str> = path.split('/').collect();
            if method == "POST"
                && segs.len() == 6
                && segs[1] == "v1"
                && segs[2] == "combat"
                && segs[3] == "sessions"
            {
                let id = segs[4];
                return match segs[5] {
                    "conditions" => add_condition(id, body, state),
                    "advance" => advance_turn(id, state),
                    _ => build_response(404, r#"{"error":"not found"}"#.to_string()),
                };
            }
            build_response(404, r#"{"error":"not found"}"#.to_string())
        }
    }
}

fn build_response(status: u16, body: String) -> String {
    let label = match status {
        200 => "OK",
        400 => "Bad Request",
        404 => "Not Found",
        _ => "Error",
    };
    format!(
        "HTTP/1.1 {status} {label}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        body.len(),
        body
    )
}

// ============================ JSON ============================

#[derive(Clone, Debug)]
enum Json {
    Null,
    Bool(bool),
    Num(f64),
    Str(String),
    Arr(Vec<Json>),
    Obj(Vec<(String, Json)>),
}

impl Json {
    fn get(&self, key: &str) -> Option<&Json> {
        if let Json::Obj(entries) = self {
            for (k, v) in entries {
                if k == key {
                    return Some(v);
                }
            }
        }
        None
    }
    fn as_str(&self) -> Option<&str> {
        if let Json::Str(s) = self { Some(s) } else { None }
    }
    fn as_bool(&self) -> Option<bool> {
        if let Json::Bool(b) = self { Some(*b) } else { None }
    }
    fn as_i64(&self) -> Option<i64> {
        if let Json::Num(n) = self {
            if n.is_finite() && *n == n.trunc() && n.abs() < 9_007_199_254_740_992.0 {
                Some(*n as i64)
            } else {
                None
            }
        } else {
            None
        }
    }
    fn as_array(&self) -> Option<&Vec<Json>> {
        if let Json::Arr(a) = self { Some(a) } else { None }
    }
}

struct Parser<'a> {
    s: &'a [u8],
    i: usize,
}

impl<'a> Parser<'a> {
    fn new(s: &'a str) -> Self {
        Parser { s: s.as_bytes(), i: 0 }
    }
    fn skip_ws(&mut self) {
        while self.i < self.s.len() && matches!(self.s[self.i], b' ' | b'\t' | b'\n' | b'\r') {
            self.i += 1;
        }
    }
    fn parse(&mut self) -> Option<Json> {
        self.skip_ws();
        let v = self.parse_value()?;
        self.skip_ws();
        if self.i != self.s.len() { None } else { Some(v) }
    }
    fn parse_value(&mut self) -> Option<Json> {
        self.skip_ws();
        if self.i >= self.s.len() {
            return None;
        }
        match self.s[self.i] {
            b'{' => self.parse_object(),
            b'[' => self.parse_array(),
            b'"' => self.parse_string().map(Json::Str),
            b't' | b'f' => self.parse_bool(),
            b'n' => self.parse_null(),
            b'-' | b'0'..=b'9' => self.parse_number(),
            _ => None,
        }
    }
    fn parse_object(&mut self) -> Option<Json> {
        self.i += 1; // {
        let mut entries = Vec::new();
        self.skip_ws();
        if self.i < self.s.len() && self.s[self.i] == b'}' {
            self.i += 1;
            return Some(Json::Obj(entries));
        }
        loop {
            self.skip_ws();
            let key = self.parse_string()?;
            self.skip_ws();
            if self.i >= self.s.len() || self.s[self.i] != b':' {
                return None;
            }
            self.i += 1;
            let val = self.parse_value()?;
            entries.push((key, val));
            self.skip_ws();
            if self.i >= self.s.len() {
                return None;
            }
            match self.s[self.i] {
                b',' => self.i += 1,
                b'}' => { self.i += 1; break; }
                _ => return None,
            }
        }
        Some(Json::Obj(entries))
    }
    fn parse_array(&mut self) -> Option<Json> {
        self.i += 1; // [
        let mut items = Vec::new();
        self.skip_ws();
        if self.i < self.s.len() && self.s[self.i] == b']' {
            self.i += 1;
            return Some(Json::Arr(items));
        }
        loop {
            let val = self.parse_value()?;
            items.push(val);
            self.skip_ws();
            if self.i >= self.s.len() {
                return None;
            }
            match self.s[self.i] {
                b',' => self.i += 1,
                b']' => { self.i += 1; break; }
                _ => return None,
            }
        }
        Some(Json::Arr(items))
    }
    fn parse_string(&mut self) -> Option<String> {
        if self.i >= self.s.len() || self.s[self.i] != b'"' {
            return None;
        }
        self.i += 1;
        let mut out: Vec<u8> = Vec::new();
        while self.i < self.s.len() {
            let c = self.s[self.i];
            match c {
                b'"' => { self.i += 1; return String::from_utf8(out).ok(); }
                b'\\' => {
                    self.i += 1;
                    if self.i >= self.s.len() { return None; }
                    let e = self.s[self.i];
                    match e {
                        b'"' => out.push(b'"'),
                        b'\\' => out.push(b'\\'),
                        b'/' => out.push(b'/'),
                        b'n' => out.push(b'\n'),
                        b't' => out.push(b'\t'),
                        b'r' => out.push(b'\r'),
                        b'b' => out.push(0x08),
                        b'f' => out.push(0x0c),
                        b'u' => {
                            if self.i + 4 >= self.s.len() { return None; }
                            let hex = std::str::from_utf8(&self.s[self.i + 1..self.i + 5]).ok()?;
                            let code = u32::from_str_radix(hex, 16).ok()?;
                            if (0xD800..=0xDBFF).contains(&code) {
                                if self.i + 10 < self.s.len()
                                    && self.s[self.i + 5] == b'\\'
                                    && self.s[self.i + 6] == b'u'
                                {
                                    let hex2 = std::str::from_utf8(&self.s[self.i + 7..self.i + 11]).ok()?;
                                    let code2 = u32::from_str_radix(hex2, 16).ok()?;
                                    if (0xDC00..=0xDFFF).contains(&code2) {
                                        let cp = 0x10000 + ((code - 0xD800) << 10) + (code2 - 0xDC00);
                                        if let Some(ch) = char::from_u32(cp) {
                                            let mut buf = [0u8; 4];
                                            out.extend_from_slice(ch.encode_utf8(&mut buf).as_bytes());
                                        } else { return None; }
                                        self.i += 6;
                                    } else { return None; }
                                } else { return None; }
                            } else if let Some(ch) = char::from_u32(code) {
                                let mut buf = [0u8; 4];
                                out.extend_from_slice(ch.encode_utf8(&mut buf).as_bytes());
                            } else { return None; }
                            self.i += 4;
                        }
                        _ => return None,
                    }
                    self.i += 1;
                }
                _ => { out.push(c); self.i += 1; }
            }
        }
        None
    }
    fn parse_number(&mut self) -> Option<Json> {
        let start = self.i;
        if self.i < self.s.len() && self.s[self.i] == b'-' { self.i += 1; }
        let digits_start = self.i;
        while self.i < self.s.len() && self.s[self.i].is_ascii_digit() { self.i += 1; }
        if self.i == digits_start { return None; }
        if self.i < self.s.len() && self.s[self.i] == b'.' {
            self.i += 1;
            let frac_start = self.i;
            while self.i < self.s.len() && self.s[self.i].is_ascii_digit() { self.i += 1; }
            if self.i == frac_start { return None; }
        }
        if self.i < self.s.len() && (self.s[self.i] == b'e' || self.s[self.i] == b'E') {
            self.i += 1;
            if self.i < self.s.len() && (self.s[self.i] == b'+' || self.s[self.i] == b'-') { self.i += 1; }
            let exp_start = self.i;
            while self.i < self.s.len() && self.s[self.i].is_ascii_digit() { self.i += 1; }
            if self.i == exp_start { return None; }
        }
        let txt = std::str::from_utf8(&self.s[start..self.i]).ok()?;
        let n: f64 = txt.parse().ok()?;
        Some(Json::Num(n))
    }
    fn parse_bool(&mut self) -> Option<Json> {
        if self.s[self.i..].starts_with(b"true") { self.i += 4; Some(Json::Bool(true)) }
        else if self.s[self.i..].starts_with(b"false") { self.i += 5; Some(Json::Bool(false)) }
        else { None }
    }
    fn parse_null(&mut self) -> Option<Json> {
        if self.s[self.i..].starts_with(b"null") { self.i += 4; Some(Json::Null) } else { None }
    }
}

fn parse_json(s: &str) -> Option<Json> {
    Parser::new(s).parse()
}

fn fmt_num(x: f64) -> String {
    if x.is_finite() && x == x.trunc() && x.abs() < 1e15 {
        format!("{}", x as i64)
    } else {
        format!("{}", x)
    }
}

fn quote_string(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\t' => out.push_str("\\t"),
            '\r' => out.push_str("\\r"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

fn to_json(v: &Json) -> String {
    match v {
        Json::Null => "null".to_string(),
        Json::Bool(b) => if *b { "true".to_string() } else { "false".to_string() },
        Json::Num(n) => fmt_num(*n),
        Json::Str(s) => quote_string(s),
        Json::Arr(a) => {
            let items: Vec<String> = a.iter().map(to_json).collect();
            format!("[{}]", items.join(","))
        }
        Json::Obj(e) => {
            let items: Vec<String> = e
                .iter()
                .map(|(k, v)| format!("{}:{}", quote_string(k), to_json(v)))
                .collect();
            format!("{{{}}}", items.join(","))
        }
    }
}

// ============================ Handlers ============================

fn dice_stats(body: &str) -> String {
    let parsed = parse_json(body);
    let expr = parsed
        .as_ref()
        .and_then(|j| j.get("expression"))
        .and_then(|v| v.as_str());
    let expr = match expr {
        Some(e) => e.trim(),
        None => return build_response(400, r#"{"error":"invalid expression"}"#.to_string()),
    };
    match parse_dice(expr) {
        Some((count, sides, modifier)) => {
            let min = count + modifier;
            let max = count * sides + modifier;
            let average = (min as f64 + max as f64) / 2.0;
            let obj = Json::Obj(vec![
                ("dice_count".into(), Json::Num(count as f64)),
                ("sides".into(), Json::Num(sides as f64)),
                ("modifier".into(), Json::Num(modifier as f64)),
                ("min".into(), Json::Num(min as f64)),
                ("max".into(), Json::Num(max as f64)),
                ("average".into(), Json::Num(average)),
            ]);
            build_response(200, to_json(&obj))
        }
        None => build_response(400, r#"{"error":"invalid expression"}"#.to_string()),
    }
}

fn parse_dice(expr: &str) -> Option<(i64, i64, i64)> {
    let d_pos = expr.find('d')?;
    let count_str = &expr[..d_pos];
    if count_str.is_empty() || !count_str.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let count: i64 = count_str.parse().ok()?;
    if count <= 0 {
        return None;
    }
    let rest = &expr[d_pos + 1..];
    let (sides_str, mod_part) = match rest.find(|c| c == '+' || c == '-') {
        Some(p) => (&rest[..p], Some(&rest[p..])),
        None => (rest, None),
    };
    if sides_str.is_empty() || !sides_str.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let sides: i64 = sides_str.parse().ok()?;
    if sides <= 0 {
        return None;
    }
    let modifier = match mod_part {
        None => 0,
        Some(s) => {
            let (sign, digits) = s.split_at(1);
            if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
                return None;
            }
            let val: i64 = digits.parse().ok()?;
            if sign == "-" { -val } else { val }
        }
    };
    Some((count, sides, modifier))
}

fn ability_check(body: &str) -> String {
    let j = match parse_json(body) {
        Some(j) => j,
        None => return build_response(400, r#"{"error":"bad request"}"#.to_string()),
    };
    let roll = j.get("roll").and_then(|v| v.as_i64());
    let modifier = j.get("modifier").and_then(|v| v.as_i64());
    let dc = j.get("dc").and_then(|v| v.as_i64());
    match (roll, modifier, dc) {
        (Some(roll), Some(modifier), Some(dc)) => {
            let total = roll + modifier;
            let success = total >= dc;
            let margin = total - dc;
            let obj = Json::Obj(vec![
                ("total".into(), Json::Num(total as f64)),
                ("success".into(), Json::Bool(success)),
                ("margin".into(), Json::Num(margin as f64)),
            ]);
            build_response(200, to_json(&obj))
        }
        _ => build_response(400, r#"{"error":"bad request"}"#.to_string()),
    }
}

fn cr_xp(cr: &str) -> Option<i64> {
    match cr {
        "0" => Some(10),
        "1/8" => Some(25),
        "1/4" => Some(50),
        "1/2" => Some(100),
        "1" => Some(200),
        "2" => Some(450),
        "3" => Some(700),
        "4" => Some(1100),
        "5" => Some(1800),
        _ => None,
    }
}

fn count_multiplier(count: i64) -> f64 {
    if count >= 15 { 4.0 }
    else if count >= 11 { 3.0 }
    else if count >= 7 { 2.5 }
    else if count >= 3 { 2.0 }
    else if count == 2 { 1.5 }
    else { 1.0 }
}

fn level_thresholds(level: i64) -> (i64, i64, i64, i64) {
    match level {
        3 => (75, 150, 225, 400),
        _ => (0, 0, 0, 0),
    }
}

fn adjusted_xp(body: &str) -> String {
    let j = match parse_json(body) {
        Some(j) => j,
        None => return build_response(400, r#"{"error":"bad request"}"#.to_string()),
    };
    let party = j.get("party").and_then(|v| v.as_array());
    let monsters = j.get("monsters").and_then(|v| v.as_array());
    let (party, monsters) = match (party, monsters) {
        (Some(p), Some(m)) => (p, m),
        _ => return build_response(400, r#"{"error":"bad request"}"#.to_string()),
    };
    let mut base_xp: f64 = 0.0;
    let mut monster_count: i64 = 0;
    for m in monsters {
        let cr = m.get("cr").and_then(|v| v.as_str());
        let count = m.get("count").and_then(|v| v.as_i64());
        let (cr, count) = match (cr, count) {
            (Some(c), Some(n)) => (c, n),
            _ => return build_response(400, r#"{"error":"bad request"}"#.to_string()),
        };
        if count < 0 {
            return build_response(400, r#"{"error":"bad request"}"#.to_string());
        }
        let xp = match cr_xp(cr) {
            Some(x) => x,
            None => return build_response(400, r#"{"error":"bad request"}"#.to_string()),
        };
        base_xp += xp as f64 * count as f64;
        monster_count += count;
    }
    let multiplier = count_multiplier(monster_count);
    let adjusted_xp = base_xp * multiplier;

    let mut easy = 0i64;
    let mut medium = 0i64;
    let mut hard = 0i64;
    let mut deadly = 0i64;
    for p in party {
        let level = p.get("level").and_then(|v| v.as_i64());
        let level = match level {
            Some(l) => l,
            None => return build_response(400, r#"{"error":"bad request"}"#.to_string()),
        };
        let (e, m, h, d) = level_thresholds(level);
        easy += e;
        medium += m;
        hard += h;
        deadly += d;
    }
    let difficulty = if adjusted_xp >= deadly as f64 {
        "deadly"
    } else if adjusted_xp >= hard as f64 {
        "hard"
    } else if adjusted_xp >= medium as f64 {
        "medium"
    } else if adjusted_xp >= easy as f64 {
        "easy"
    } else {
        "trivial"
    };
    let obj = Json::Obj(vec![
        ("base_xp".into(), Json::Num(base_xp)),
        ("monster_count".into(), Json::Num(monster_count as f64)),
        ("multiplier".into(), Json::Num(multiplier)),
        ("adjusted_xp".into(), Json::Num(adjusted_xp)),
        ("difficulty".into(), Json::Str(difficulty.to_string())),
        (
            "thresholds".into(),
            Json::Obj(vec![
                ("easy".into(), Json::Num(easy as f64)),
                ("medium".into(), Json::Num(medium as f64)),
                ("hard".into(), Json::Num(hard as f64)),
                ("deadly".into(), Json::Num(deadly as f64)),
            ]),
        ),
    ]);
    build_response(200, to_json(&obj))
}

// ============================ Character helpers ============================

fn floor_div(a: i64, b: i64) -> i64 {
    let q = a / b;
    let r = a % b;
    if r != 0 && ((r < 0) != (b < 0)) { q - 1 } else { q }
}

fn ability_modifier_of(score: i64) -> i64 {
    floor_div(score - 10, 2)
}

fn proficiency_bonus_of(level: i64) -> i64 {
    2 + (level - 1) / 4
}

fn bad() -> String {
    build_response(400, r#"{"error":"bad request"}"#.to_string())
}

fn ability_modifier(body: &str) -> String {
    let j = match parse_json(body) {
        Some(j) => j,
        None => return bad(),
    };
    let score = match j.get("score").and_then(|v| v.as_i64()) {
        Some(s) => s,
        None => return bad(),
    };
    if !(1..=30).contains(&score) {
        return bad();
    }
    let modifier = ability_modifier_of(score);
    let obj = Json::Obj(vec![
        ("score".into(), Json::Num(score as f64)),
        ("modifier".into(), Json::Num(modifier as f64)),
    ]);
    build_response(200, to_json(&obj))
}

fn proficiency(body: &str) -> String {
    let j = match parse_json(body) {
        Some(j) => j,
        None => return bad(),
    };
    let level = match j.get("level").and_then(|v| v.as_i64()) {
        Some(l) => l,
        None => return bad(),
    };
    if !(1..=20).contains(&level) {
        return bad();
    }
    let bonus = proficiency_bonus_of(level);
    let obj = Json::Obj(vec![
        ("level".into(), Json::Num(level as f64)),
        ("proficiency_bonus".into(), Json::Num(bonus as f64)),
    ]);
    build_response(200, to_json(&obj))
}

fn derived_stats(body: &str) -> String {
    let j = match parse_json(body) {
        Some(j) => j,
        None => return bad(),
    };
    let level = match j.get("level").and_then(|v| v.as_i64()) {
        Some(l) => l,
        None => return bad(),
    };
    if !(1..=20).contains(&level) {
        return bad();
    }
    let abilities = match j.get("abilities") {
        Some(Json::Obj(_)) => j.get("abilities").unwrap(),
        _ => return bad(),
    };
    let mut con_mod = 0i64;
    let mut dex_mod = 0i64;
    let mut mod_entries: Vec<(String, i64)> = Vec::new();
    for &key in &["str", "dex", "con", "int", "wis", "cha"] {
        let score = match abilities.get(key).and_then(|v| v.as_i64()) {
            Some(s) => s,
            None => return bad(),
        };
        if !(1..=30).contains(&score) {
            return bad();
        }
        let m = ability_modifier_of(score);
        if key == "con" { con_mod = m; }
        if key == "dex" { dex_mod = m; }
        mod_entries.push((key.to_string(), m));
    }
    let armor = match j.get("armor") {
        Some(Json::Obj(_)) => j.get("armor").unwrap(),
        _ => return bad(),
    };
    let base = match armor.get("base").and_then(|v| v.as_i64()) {
        Some(b) => b,
        None => return bad(),
    };
    let shield = match armor.get("shield").and_then(|v| v.as_bool()) {
        Some(b) => b,
        None => return bad(),
    };
    let dex_cap = match armor.get("dex_cap").and_then(|v| v.as_i64()) {
        Some(d) => d,
        None => return bad(),
    };
    let prof = proficiency_bonus_of(level);
    let hp_max = level * (6 + con_mod);
    let shield_bonus = if shield { 2 } else { 0 };
    let armor_class = base + dex_mod.min(dex_cap) + shield_bonus;
    let modifiers_obj = Json::Obj(
        mod_entries
            .iter()
            .map(|(k, v)| (k.clone(), Json::Num(*v as f64)))
            .collect(),
    );
    let obj = Json::Obj(vec![
        ("level".into(), Json::Num(level as f64)),
        ("proficiency_bonus".into(), Json::Num(prof as f64)),
        ("hp_max".into(), Json::Num(hp_max as f64)),
        ("armor_class".into(), Json::Num(armor_class as f64)),
        ("modifiers".into(), modifiers_obj),
    ]);
    build_response(200, to_json(&obj))
}

fn initiative_order(body: &str) -> String {
    let j = match parse_json(body) {
        Some(j) => j,
        None => return build_response(400, r#"{"error":"bad request"}"#.to_string()),
    };
    let combatants = match j.get("combatants").and_then(|v| v.as_array()) {
        Some(c) => c,
        None => return build_response(400, r#"{"error":"bad request"}"#.to_string()),
    };
    let mut entries: Vec<(String, i64, i64)> = Vec::new(); // (name, dex, score)
    for c in combatants {
        let name = c.get("name").and_then(|v| v.as_str());
        let dex = c.get("dex").and_then(|v| v.as_i64());
        let roll = c.get("roll").and_then(|v| v.as_i64());
        let (name, dex, roll) = match (name, dex, roll) {
            (Some(n), Some(d), Some(r)) => (n.to_string(), d, r),
            _ => return build_response(400, r#"{"error":"bad request"}"#.to_string()),
        };
        let score = roll + dex;
        entries.push((name, dex, score));
    }
    entries.sort_by(|a, b| {
        b.2.cmp(&a.2) // score desc
            .then_with(|| b.1.cmp(&a.1)) // dex desc
            .then_with(|| a.0.cmp(&b.0)) // name asc
    });
    let order: Vec<Json> = entries
        .iter()
        .map(|(name, _dex, score)| {
            Json::Obj(vec![
                ("name".into(), Json::Str(name.clone())),
                ("score".into(), Json::Num(*score as f64)),
            ])
        })
        .collect();
    let obj = Json::Obj(vec![("order".into(), Json::Arr(order))]);
    build_response(200, to_json(&obj))
}

// ============================ Combat State ============================

fn combatant_json(c: &Combatant) -> Json {
    Json::Obj(vec![
        ("name".into(), Json::Str(c.name.clone())),
        ("score".into(), Json::Num(c.score as f64)),
    ])
}

fn render_session(s: &CombatSession) -> String {
    let active = if (s.turn_index as usize) < s.order.len() {
        combatant_json(&s.order[s.turn_index as usize])
    } else {
        Json::Null
    };
    let order: Vec<Json> = s.order.iter().map(combatant_json).collect();
    let obj = Json::Obj(vec![
        ("id".into(), Json::Str(s.id.clone())),
        ("round".into(), Json::Num(s.round as f64)),
        ("turn_index".into(), Json::Num(s.turn_index as f64)),
        ("active".into(), active),
        ("order".into(), Json::Arr(order)),
    ]);
    build_response(200, to_json(&obj))
}

fn render_advance(s: &CombatSession) -> String {
    let active = if (s.turn_index as usize) < s.order.len() {
        combatant_json(&s.order[s.turn_index as usize])
    } else {
        Json::Null
    };
    let mut cond_map: Vec<(String, Json)> = Vec::new();
    for c in &s.order {
        if let Some(conds) = s.conditions.get(&c.name) {
            if conds.is_empty() {
                continue;
            }
            let arr: Vec<Json> = conds
                .iter()
                .map(|cd| {
                    Json::Obj(vec![
                        ("condition".into(), Json::Str(cd.condition.clone())),
                        ("remaining_rounds".into(), Json::Num(cd.remaining_rounds as f64)),
                    ])
                })
                .collect();
            cond_map.push((c.name.clone(), Json::Arr(arr)));
        }
    }
    let obj = Json::Obj(vec![
        ("id".into(), Json::Str(s.id.clone())),
        ("round".into(), Json::Num(s.round as f64)),
        ("turn_index".into(), Json::Num(s.turn_index as f64)),
        ("active".into(), active),
        ("conditions".into(), Json::Obj(cond_map)),
    ]);
    build_response(200, to_json(&obj))
}

fn create_combat_session(body: &str, state: &State) -> String {
    let j = match parse_json(body) {
        Some(j) => j,
        None => return bad(),
    };
    let id = match j.get("id").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return bad(),
    };
    let combatants = match j.get("combatants").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return bad(),
    };
    let mut order: Vec<Combatant> = Vec::new();
    for c in combatants {
        let name = c.get("name").and_then(|v| v.as_str());
        let dex = c.get("dex").and_then(|v| v.as_i64());
        let roll = c.get("roll").and_then(|v| v.as_i64());
        let (name, dex, roll) = match (name, dex, roll) {
            (Some(n), Some(d), Some(r)) => (n.to_string(), d, r),
            _ => return bad(),
        };
        let score = roll + dex;
        order.push(Combatant { name, dex, score });
    }
    order.sort_by(|a, b| {
        b.score
            .cmp(&a.score)
            .then_with(|| b.dex.cmp(&a.dex))
            .then_with(|| a.name.cmp(&b.name))
    });
    let session = CombatSession {
        id: id.clone(),
        round: 1,
        turn_index: 0,
        conditions: HashMap::new(),
        order,
    };
    let resp = render_session(&session);
    state.lock().unwrap().insert(id, session);
    resp
}

fn add_condition(id: &str, body: &str, state: &State) -> String {
    let mut sessions = state.lock().unwrap();
    let session = match sessions.get_mut(id) {
        Some(s) => s,
        None => return build_response(404, r#"{"error":"not found"}"#.to_string()),
    };
    let j = match parse_json(body) {
        Some(j) => j,
        None => return bad(),
    };
    let target = match j.get("target").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return bad(),
    };
    let condition = match j.get("condition").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return bad(),
    };
    let duration = match j.get("duration_rounds").and_then(|v| v.as_i64()) {
        Some(d) => d,
        None => return bad(),
    };
    if duration <= 0 {
        return bad();
    }
    if !session.order.iter().any(|c| c.name == target) {
        return bad();
    }
    session
        .conditions
        .entry(target.clone())
        .or_default()
        .push(Condition {
            condition: condition.clone(),
            remaining_rounds: duration,
        });
    let conds: Vec<Json> = session
        .conditions
        .get(target.as_str())
        .unwrap()
        .iter()
        .map(|c| {
            Json::Obj(vec![
                ("condition".into(), Json::Str(c.condition.clone())),
                ("remaining_rounds".into(), Json::Num(c.remaining_rounds as f64)),
            ])
        })
        .collect();
    let obj = Json::Obj(vec![
        ("target".into(), Json::Str(target)),
        ("conditions".into(), Json::Arr(conds)),
    ]);
    build_response(200, to_json(&obj))
}

fn advance_turn(id: &str, state: &State) -> String {
    let mut sessions = state.lock().unwrap();
    let session = match sessions.get_mut(id) {
        Some(s) => s,
        None => return build_response(404, r#"{"error":"not found"}"#.to_string()),
    };
    let len = session.order.len();
    if len > 0 {
        session.turn_index += 1;
        if session.turn_index as usize >= len {
            session.turn_index = 0;
            session.round += 1;
        }
        let active_name = session.order[session.turn_index as usize].name.clone();
        if let Some(conds) = session.conditions.get_mut(&active_name) {
            for c in conds.iter_mut() {
                c.remaining_rounds -= 1;
            }
            conds.retain(|c| c.remaining_rounds > 0);
        }
    }
    render_advance(session)
}
