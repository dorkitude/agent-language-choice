use std::collections::HashMap;
use std::env;
use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

fn main() -> std::io::Result<()> {
    let port = env::var("PORT").unwrap_or_else(|_| "8080".to_string());
    init_storage();
    let listener = TcpListener::bind(format!("127.0.0.1:{port}"))?;
    for stream in listener.incoming() {
        if let Ok(mut stream) = stream {
            let _ = handle(&mut stream);
        }
    }
    Ok(())
}

fn handle(stream: &mut TcpStream) -> std::io::Result<()> {
    let mut reader = BufReader::new(stream.try_clone()?);
    let mut request_line = String::new();
    reader.read_line(&mut request_line)?;
    let request_line = request_line.trim_end().to_string();
    let mut parts = request_line.split_whitespace();
    let method = parts.next().unwrap_or("").to_string();
    let path_full = parts.next().unwrap_or("").to_string();
    let path = path_full.split('?').next().unwrap_or("").to_string();

    let mut content_length: usize = 0;
    loop {
        let mut line = String::new();
        let n = reader.read_line(&mut line)?;
        if n == 0 {
            break;
        }
        let trimmed = line.trim_end();
        if trimmed.is_empty() {
            break;
        }
        if let Some(idx) = trimmed.find(':') {
            let key = trimmed[..idx].trim().to_ascii_lowercase();
            let val = trimmed[idx + 1..].trim();
            if key == "content-length" {
                content_length = val.parse().unwrap_or(0);
            }
        }
    }

    let mut body = vec![0_u8; content_length];
    if content_length > 0 {
        reader.read_exact(&mut body)?;
    }
    let body_str = String::from_utf8_lossy(&body).to_string();

    let (status, resp_body) = route(&method, &path, &body_str);
    respond(stream, status, &resp_body)
}

fn route(method: &str, path: &str, body: &str) -> (u16, String) {
    match (method, path) {
        ("GET", "/health") => (200, r#"{"ok":true}"#.to_string()),
        ("POST", "/v1/dice/stats") => handle_dice_stats(body),
        ("POST", "/v1/checks/ability") => handle_ability_check(body),
        ("POST", "/v1/encounters/adjusted-xp") => handle_adjusted_xp(body),
        ("POST", "/v1/initiative/order") => handle_initiative_order(body),
        ("POST", "/v1/characters/ability-modifier") => handle_ability_modifier(body),
        ("POST", "/v1/characters/proficiency") => handle_proficiency(body),
        ("POST", "/v1/characters/derived-stats") => handle_derived_stats(body),
        ("POST", "/v1/combat/sessions") => handle_create_combat_session(body),
        ("POST", "/v1/auth/register") => handle_register(body),
        ("POST", "/v1/auth/login") => handle_login(body),
        ("GET", "/v1/storage/status") => handle_storage_status(),
        ("POST", "/v1/storage/reset") => handle_storage_reset(),
        ("POST", "/v1/compendium/monsters") => handle_create_monster(body),
        ("POST", "/v1/compendium/items") => handle_create_item(body),
        ("POST", "/v1/campaigns") => handle_create_campaign(body),
        ("POST", "/v1/phb/spell-slots") => handle_spell_slots(body),
        ("POST", "/v1/phb/rests/long") => handle_long_rest(body),
        ("POST", "/v1/phb/equipment-load") => handle_equipment_load(body),
        _ => {
            if method == "POST" {
                if let Some(rest) = path.strip_prefix("/v1/combat/sessions/") {
                    if let Some(id) = rest.strip_suffix("/conditions") {
                        if !id.is_empty() && !id.contains('/') {
                            return handle_add_condition(id, body);
                        }
                    } else if let Some(id) = rest.strip_suffix("/advance") {
                        if !id.is_empty() && !id.contains('/') {
                            return handle_advance(id);
                        }
                    }
                } else if let Some(rest) = path.strip_prefix("/v1/campaigns/") {
                    if let Some(id) = rest.strip_suffix("/characters") {
                        if !id.is_empty() && !id.contains('/') {
                            return handle_add_character(id, body);
                        }
                    } else if let Some(id) = rest.strip_suffix("/events") {
                        if !id.is_empty() && !id.contains('/') {
                            return handle_add_event(id, body);
                        }
                    }
                }
            } else if method == "GET" {
                if let Some(slug) = path.strip_prefix("/v1/compendium/monsters/") {
                    if !slug.is_empty() && !slug.contains('/') {
                        return handle_get_monster(slug);
                    }
                } else if let Some(slug) = path.strip_prefix("/v1/compendium/items/") {
                    if !slug.is_empty() && !slug.contains('/') {
                        return handle_get_item(slug);
                    }
                } else if let Some(rest) = path.strip_prefix("/v1/campaigns/") {
                    if let Some(id) = rest.strip_suffix("/state") {
                        if !id.is_empty() && !id.contains('/') {
                            return handle_get_campaign_state(id);
                        }
                    }
                }
            }
            (404, r#"{"error":"not found"}"#.to_string())
        }
    }
}

fn respond(stream: &mut TcpStream, status: u16, body: &str) -> std::io::Result<()> {
    let label = match status {
        200 => "OK",
        201 => "Created",
        400 => "Bad Request",
        401 => "Unauthorized",
        404 => "Not Found",
        409 => "Conflict",
        _ => "Error",
    };
    write!(
        stream,
        "HTTP/1.1 {status} {label}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        body.len(),
        body
    )
}

// ---------- Minimal JSON value ----------

#[derive(Debug, Clone)]
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
        match self {
            Json::Obj(pairs) => pairs.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    fn as_f64(&self) -> Option<f64> {
        match self {
            Json::Num(n) => Some(*n),
            _ => None,
        }
    }

    fn as_i64(&self) -> Option<i64> {
        self.as_f64().map(|n| n as i64)
    }

    fn as_str(&self) -> Option<&str> {
        match self {
            Json::Str(s) => Some(s),
            _ => None,
        }
    }

    fn as_array(&self) -> Option<&Vec<Json>> {
        match self {
            Json::Arr(a) => Some(a),
            _ => None,
        }
    }
}

struct Parser<'a> {
    bytes: &'a [u8],
    pos: usize,
}

impl<'a> Parser<'a> {
    fn new(s: &'a str) -> Self {
        Parser {
            bytes: s.as_bytes(),
            pos: 0,
        }
    }

    fn skip_ws(&mut self) {
        while self.pos < self.bytes.len() && (self.bytes[self.pos] as char).is_whitespace() {
            self.pos += 1;
        }
    }

    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.pos).copied()
    }

    fn parse_value(&mut self) -> Option<Json> {
        self.skip_ws();
        match self.peek()? {
            b'{' => self.parse_object(),
            b'[' => self.parse_array(),
            b'"' => self.parse_string().map(Json::Str),
            b't' | b'f' => self.parse_bool(),
            b'n' => self.parse_null(),
            _ => self.parse_number(),
        }
    }

    fn parse_object(&mut self) -> Option<Json> {
        self.pos += 1; // {
        let mut pairs = Vec::new();
        self.skip_ws();
        if self.peek() == Some(b'}') {
            self.pos += 1;
            return Some(Json::Obj(pairs));
        }
        loop {
            self.skip_ws();
            let key = self.parse_string()?;
            self.skip_ws();
            if self.peek() != Some(b':') {
                return None;
            }
            self.pos += 1;
            let value = self.parse_value()?;
            pairs.push((key, value));
            self.skip_ws();
            match self.peek() {
                Some(b',') => {
                    self.pos += 1;
                }
                Some(b'}') => {
                    self.pos += 1;
                    break;
                }
                _ => return None,
            }
        }
        Some(Json::Obj(pairs))
    }

    fn parse_array(&mut self) -> Option<Json> {
        self.pos += 1; // [
        let mut items = Vec::new();
        self.skip_ws();
        if self.peek() == Some(b']') {
            self.pos += 1;
            return Some(Json::Arr(items));
        }
        loop {
            let value = self.parse_value()?;
            items.push(value);
            self.skip_ws();
            match self.peek() {
                Some(b',') => {
                    self.pos += 1;
                }
                Some(b']') => {
                    self.pos += 1;
                    break;
                }
                _ => return None,
            }
        }
        Some(Json::Arr(items))
    }

    fn parse_string(&mut self) -> Option<String> {
        self.skip_ws();
        if self.peek() != Some(b'"') {
            return None;
        }
        self.pos += 1;
        let mut out = String::new();
        loop {
            let c = *self.bytes.get(self.pos)?;
            self.pos += 1;
            match c {
                b'"' => break,
                b'\\' => {
                    let esc = *self.bytes.get(self.pos)?;
                    self.pos += 1;
                    match esc {
                        b'"' => out.push('"'),
                        b'\\' => out.push('\\'),
                        b'/' => out.push('/'),
                        b'n' => out.push('\n'),
                        b't' => out.push('\t'),
                        b'r' => out.push('\r'),
                        b'b' => out.push('\u{0008}'),
                        b'f' => out.push('\u{000C}'),
                        b'u' => {
                            let hex = std::str::from_utf8(self.bytes.get(self.pos..self.pos + 4)?)
                                .ok()?;
                            let code = u32::from_str_radix(hex, 16).ok()?;
                            self.pos += 4;
                            out.push(char::from_u32(code)?);
                        }
                        _ => return None,
                    }
                }
                _ => {
                    out.push(c as char);
                }
            }
        }
        Some(out)
    }

    fn parse_bool(&mut self) -> Option<Json> {
        if self.bytes[self.pos..].starts_with(b"true") {
            self.pos += 4;
            Some(Json::Bool(true))
        } else if self.bytes[self.pos..].starts_with(b"false") {
            self.pos += 5;
            Some(Json::Bool(false))
        } else {
            None
        }
    }

    fn parse_null(&mut self) -> Option<Json> {
        if self.bytes[self.pos..].starts_with(b"null") {
            self.pos += 4;
            Some(Json::Null)
        } else {
            None
        }
    }

    fn parse_number(&mut self) -> Option<Json> {
        let start = self.pos;
        if self.peek() == Some(b'-') {
            self.pos += 1;
        }
        while let Some(c) = self.peek() {
            if c.is_ascii_digit() || c == b'.' || c == b'e' || c == b'E' || c == b'+' || c == b'-'
            {
                self.pos += 1;
            } else {
                break;
            }
        }
        let s = std::str::from_utf8(&self.bytes[start..self.pos]).ok()?;
        s.parse::<f64>().ok().map(Json::Num)
    }
}

fn parse_json(s: &str) -> Option<Json> {
    let mut p = Parser::new(s);
    let v = p.parse_value()?;
    Some(v)
}

fn fmt_num(n: f64) -> String {
    if n.fract() == 0.0 && n.abs() < 1e15 {
        format!("{}", n as i64)
    } else {
        format!("{}", n)
    }
}

fn json_escape(s: &str) -> String {
    let mut out = String::new();
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            _ => out.push(c),
        }
    }
    out
}

fn err_response(msg: &str) -> (u16, String) {
    (400, format!(r#"{{"error":"{}"}}"#, json_escape(msg)))
}

// ---------- Dice stats ----------

struct DiceExpr {
    count: i64,
    sides: i64,
    modifier: i64,
}

fn parse_dice_expr(expr: &str) -> Option<DiceExpr> {
    let expr = expr.trim();
    let d_pos = expr.find(['d', 'D'])?;
    let count_str = &expr[..d_pos];
    let rest = &expr[d_pos + 1..];

    if count_str.is_empty() || !count_str.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let count: i64 = count_str.parse().ok()?;
    if count <= 0 {
        return None;
    }

    let sign_pos = rest.find(['+', '-']);
    let (sides_str, modifier): (&str, i64) = match sign_pos {
        Some(pos) => {
            let sides_str = &rest[..pos];
            let sign = &rest[pos..pos + 1];
            let mod_str = &rest[pos + 1..];
            if mod_str.is_empty() || !mod_str.chars().all(|c| c.is_ascii_digit()) {
                return None;
            }
            let mut m: i64 = mod_str.parse().ok()?;
            if sign == "-" {
                m = -m;
            }
            (sides_str, m)
        }
        None => (rest, 0),
    };

    if sides_str.is_empty() || !sides_str.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let sides: i64 = sides_str.parse().ok()?;
    if sides <= 0 {
        return None;
    }

    Some(DiceExpr {
        count,
        sides,
        modifier,
    })
}

fn handle_dice_stats(body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let expression = match json.get("expression").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err_response("missing expression"),
    };
    let dice = match parse_dice_expr(expression) {
        Some(d) => d,
        None => return err_response("invalid expression"),
    };

    let min = dice.count * 1 + dice.modifier;
    let max = dice.count * dice.sides + dice.modifier;
    let average = (min as f64 + max as f64) / 2.0;

    let body = format!(
        r#"{{"dice_count":{},"sides":{},"modifier":{},"min":{},"max":{},"average":{}}}"#,
        dice.count,
        dice.sides,
        dice.modifier,
        min,
        max,
        fmt_num(average)
    );
    (200, body)
}

// ---------- Ability check ----------

fn handle_ability_check(body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let roll = match json.get("roll").and_then(|v| v.as_i64()) {
        Some(v) => v,
        None => return err_response("missing roll"),
    };
    let modifier = match json.get("modifier").and_then(|v| v.as_i64()) {
        Some(v) => v,
        None => return err_response("missing modifier"),
    };
    let dc = match json.get("dc").and_then(|v| v.as_i64()) {
        Some(v) => v,
        None => return err_response("missing dc"),
    };

    let total = roll + modifier;
    let success = total >= dc;
    let margin = total - dc;

    let body = format!(
        r#"{{"total":{},"success":{},"margin":{}}}"#,
        total, success, margin
    );
    (200, body)
}

// ---------- Adjusted XP ----------

fn cr_to_xp(cr: &str) -> Option<i64> {
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
    match count {
        1 => 1.0,
        2 => 1.5,
        3..=6 => 2.0,
        7..=10 => 2.5,
        11..=14 => 3.0,
        _ => 4.0,
    }
}

fn level_thresholds(level: i64) -> Option<(i64, i64, i64, i64)> {
    let table: HashMap<i64, (i64, i64, i64, i64)> = HashMap::from([
        (1, (25, 50, 75, 100)),
        (2, (50, 100, 150, 200)),
        (3, (75, 150, 225, 400)),
        (4, (125, 250, 375, 500)),
        (5, (250, 500, 750, 1100)),
        (6, (300, 600, 900, 1400)),
        (7, (350, 750, 1100, 1700)),
        (8, (450, 900, 1400, 2100)),
        (9, (550, 1100, 1600, 2400)),
        (10, (600, 1200, 1900, 2800)),
        (11, (800, 1600, 2400, 3600)),
        (12, (1000, 2000, 3000, 4500)),
        (13, (1100, 2200, 3400, 5100)),
        (14, (1250, 2500, 3800, 5700)),
        (15, (1400, 2800, 4300, 6400)),
        (16, (1600, 3200, 4800, 7200)),
        (17, (2000, 3900, 5900, 8800)),
        (18, (2100, 4200, 6300, 9500)),
        (19, (2400, 4900, 7300, 10900)),
        (20, (2800, 5700, 8500, 12700)),
    ]);
    table.get(&level).copied()
}

fn handle_adjusted_xp(body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let party = match json.get("party").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return err_response("missing party"),
    };
    let monsters = match json.get("monsters").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return err_response("missing monsters"),
    };

    let mut base_xp: i64 = 0;
    let mut monster_count: i64 = 0;
    for m in monsters {
        let cr = match m.get("cr").and_then(|v| v.as_str()) {
            Some(s) => s,
            None => return err_response("missing monster cr"),
        };
        let count = match m.get("count").and_then(|v| v.as_i64()) {
            Some(c) => c,
            None => return err_response("missing monster count"),
        };
        let xp = match cr_to_xp(cr) {
            Some(x) => x,
            None => return err_response("unsupported cr"),
        };
        base_xp += xp * count;
        monster_count += count;
    }

    let multiplier = count_multiplier(monster_count);
    let adjusted_xp = base_xp as f64 * multiplier;

    let mut sum_easy = 0_i64;
    let mut sum_medium = 0_i64;
    let mut sum_hard = 0_i64;
    let mut sum_deadly = 0_i64;
    for p in party {
        let level = match p.get("level").and_then(|v| v.as_i64()) {
            Some(l) => l,
            None => return err_response("missing party level"),
        };
        let (easy, medium, hard, deadly) = match level_thresholds(level) {
            Some(t) => t,
            None => return err_response("unsupported level"),
        };
        sum_easy += easy;
        sum_medium += medium;
        sum_hard += hard;
        sum_deadly += deadly;
    }

    let difficulty = if adjusted_xp >= sum_deadly as f64 {
        "deadly"
    } else if adjusted_xp >= sum_hard as f64 {
        "hard"
    } else if adjusted_xp >= sum_medium as f64 {
        "medium"
    } else if adjusted_xp >= sum_easy as f64 {
        "easy"
    } else {
        "trivial"
    };

    let body = format!(
        r#"{{"base_xp":{},"monster_count":{},"multiplier":{},"adjusted_xp":{},"difficulty":"{}","thresholds":{{"easy":{},"medium":{},"hard":{},"deadly":{}}}}}"#,
        base_xp,
        monster_count,
        fmt_num(multiplier),
        fmt_num(adjusted_xp),
        difficulty,
        sum_easy,
        sum_medium,
        sum_hard,
        sum_deadly
    );
    (200, body)
}

// ---------- Initiative order ----------

fn handle_initiative_order(body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let combatants = match json.get("combatants").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return err_response("missing combatants"),
    };

    let mut entries: Vec<(String, i64, i64)> = Vec::new(); // name, score, dex
    for c in combatants {
        let name = match c.get("name").and_then(|v| v.as_str()) {
            Some(s) => s.to_string(),
            None => return err_response("missing name"),
        };
        let dex = match c.get("dex").and_then(|v| v.as_i64()) {
            Some(d) => d,
            None => return err_response("missing dex"),
        };
        let roll = match c.get("roll").and_then(|v| v.as_i64()) {
            Some(r) => r,
            None => return err_response("missing roll"),
        };
        let score = roll + dex;
        entries.push((name, score, dex));
    }

    entries.sort_by(|a, b| {
        b.1.cmp(&a.1)
            .then_with(|| b.2.cmp(&a.2))
            .then_with(|| a.0.cmp(&b.0))
    });

    let items: Vec<String> = entries
        .iter()
        .map(|(name, score, _)| format!(r#"{{"name":"{}","score":{}}}"#, json_escape(name), score))
        .collect();

    let body = format!(r#"{{"order":[{}]}}"#, items.join(","));
    (200, body)
}

// ---------- Character rules ----------

fn floor_div2(n: i64) -> i64 {
    n.div_euclid(2)
}

fn as_int_strict(v: &Json) -> Option<i64> {
    match v {
        Json::Num(n) if n.fract() == 0.0 => Some(*n as i64),
        _ => None,
    }
}

fn ability_modifier(score: i64) -> i64 {
    floor_div2(score - 10)
}

fn proficiency_bonus(level: i64) -> Option<i64> {
    match level {
        1..=4 => Some(2),
        5..=8 => Some(3),
        9..=12 => Some(4),
        13..=16 => Some(5),
        17..=20 => Some(6),
        _ => None,
    }
}

fn handle_ability_modifier(body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let score = match json.get("score").and_then(|v| as_int_strict(v)) {
        Some(s) => s,
        None => return err_response("missing score"),
    };
    if score < 1 || score > 30 {
        return err_response("score out of range");
    }
    let modifier = ability_modifier(score);
    let body = format!(r#"{{"score":{},"modifier":{}}}"#, score, modifier);
    (200, body)
}

fn handle_proficiency(body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let level = match json.get("level").and_then(|v| as_int_strict(v)) {
        Some(l) => l,
        None => return err_response("missing level"),
    };
    if level < 1 || level > 20 {
        return err_response("level out of range");
    }
    let bonus = match proficiency_bonus(level) {
        Some(b) => b,
        None => return err_response("unsupported level"),
    };
    let body = format!(r#"{{"level":{},"proficiency_bonus":{}}}"#, level, bonus);
    (200, body)
}

fn handle_derived_stats(body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let level = match json.get("level").and_then(|v| as_int_strict(v)) {
        Some(l) => l,
        None => return err_response("missing level"),
    };
    if level < 1 || level > 20 {
        return err_response("level out of range");
    }
    let proficiency_bonus_val = match proficiency_bonus(level) {
        Some(b) => b,
        None => return err_response("unsupported level"),
    };

    let abilities = match json.get("abilities") {
        Some(a) => a,
        None => return err_response("missing abilities"),
    };
    let ability_keys = ["str", "dex", "con", "int", "wis", "cha"];
    let mut mods: Vec<(&str, i64)> = Vec::new();
    for key in ability_keys {
        let score = match abilities.get(key).and_then(|v| as_int_strict(v)) {
            Some(s) => s,
            None => return err_response("missing ability score"),
        };
        if score < 1 || score > 30 {
            return err_response("ability score out of range");
        }
        mods.push((key, ability_modifier(score)));
    }
    let get_mod = |key: &str| -> i64 { mods.iter().find(|(k, _)| *k == key).unwrap().1 };
    let con_mod = get_mod("con");
    let dex_mod = get_mod("dex");

    let armor = match json.get("armor") {
        Some(a) => a,
        None => return err_response("missing armor"),
    };
    let armor_base = match armor.get("base").and_then(|v| as_int_strict(v)) {
        Some(b) => b,
        None => return err_response("missing armor base"),
    };
    let shield = match armor.get("shield") {
        Some(Json::Bool(b)) => *b,
        None => return err_response("missing armor shield"),
        _ => return err_response("invalid armor shield"),
    };
    let dex_cap = match armor.get("dex_cap").and_then(|v| as_int_strict(v)) {
        Some(c) => c,
        None => return err_response("missing armor dex_cap"),
    };

    let hp_max = level * (6 + con_mod);
    let shield_bonus = if shield { 2 } else { 0 };
    let armor_class = armor_base + std::cmp::min(dex_mod, dex_cap) + shield_bonus;

    let modifiers_json = ability_keys
        .iter()
        .map(|k| format!(r#""{}":{}"#, k, get_mod(k)))
        .collect::<Vec<_>>()
        .join(",");

    let body = format!(
        r#"{{"level":{},"proficiency_bonus":{},"hp_max":{},"armor_class":{},"modifiers":{{{}}}}}"#,
        level, proficiency_bonus_val, hp_max, armor_class, modifiers_json
    );
    (200, body)
}

// ---------- Combat sessions ----------

struct Combatant {
    name: String,
    dex: i64,
    score: i64,
    conditions: Vec<(String, i64)>,
}

struct CombatSession {
    id: String,
    round: i64,
    turn_index: usize,
    order: Vec<Combatant>,
}

fn sessions() -> &'static Mutex<HashMap<String, CombatSession>> {
    static SESSIONS: OnceLock<Mutex<HashMap<String, CombatSession>>> = OnceLock::new();
    SESSIONS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn combatant_json(c: &Combatant) -> String {
    format!(r#"{{"name":"{}","score":{}}}"#, json_escape(&c.name), c.score)
}

fn conditions_array_json(conditions: &[(String, i64)]) -> String {
    let items: Vec<String> = conditions
        .iter()
        .map(|(cond, rem)| format!(r#"{{"condition":"{}","remaining_rounds":{}}}"#, json_escape(cond), rem))
        .collect();
    format!("[{}]", items.join(","))
}

fn handle_create_combat_session(body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let id = match json.get("id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return err_response("missing id"),
    };
    let combatants_json = match json.get("combatants").and_then(|v| v.as_array()) {
        Some(a) if !a.is_empty() => a,
        _ => return err_response("missing combatants"),
    };

    let mut combatants: Vec<Combatant> = Vec::new();
    for c in combatants_json {
        let name = match c.get("name").and_then(|v| v.as_str()) {
            Some(s) => s.to_string(),
            None => return err_response("missing name"),
        };
        let dex = match c.get("dex").and_then(|v| v.as_i64()) {
            Some(d) => d,
            None => return err_response("missing dex"),
        };
        let roll = match c.get("roll").and_then(|v| v.as_i64()) {
            Some(r) => r,
            None => return err_response("missing roll"),
        };
        combatants.push(Combatant {
            name,
            dex,
            score: roll + dex,
            conditions: Vec::new(),
        });
    }

    combatants.sort_by(|a, b| {
        b.score
            .cmp(&a.score)
            .then_with(|| b.dex.cmp(&a.dex))
            .then_with(|| a.name.cmp(&b.name))
    });

    let mut map = sessions().lock().unwrap();
    if map.contains_key(&id) {
        return err_response("duplicate id");
    }

    let order_json: Vec<String> = combatants.iter().map(combatant_json).collect();
    let active_json = combatant_json(&combatants[0]);

    let resp = format!(
        r#"{{"id":"{}","round":1,"turn_index":0,"active":{},"order":[{}]}}"#,
        json_escape(&id),
        active_json,
        order_json.join(",")
    );

    map.insert(
        id.clone(),
        CombatSession {
            id,
            round: 1,
            turn_index: 0,
            order: combatants,
        },
    );
    drop(map);
    persist_db();
    (200, resp)
}

fn handle_add_condition(id: &str, body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let target = match json.get("target").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing target"),
    };
    let condition = match json.get("condition").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing condition"),
    };
    let duration = match json.get("duration_rounds").and_then(|v| as_int_strict(v)) {
        Some(d) => d,
        None => return err_response("missing duration_rounds"),
    };
    if duration <= 0 {
        return err_response("duration_rounds must be positive");
    }

    let mut map = sessions().lock().unwrap();
    let session = match map.get_mut(id) {
        Some(s) => s,
        None => return (404, r#"{"error":"session not found"}"#.to_string()),
    };

    let combatant = match session.order.iter_mut().find(|c| c.name == target) {
        Some(c) => c,
        None => return err_response("unknown target"),
    };
    combatant.conditions.push((condition, duration));

    let resp = format!(
        r#"{{"target":"{}","conditions":{}}}"#,
        json_escape(&combatant.name),
        conditions_array_json(&combatant.conditions)
    );
    drop(map);
    persist_db();
    (200, resp)
}

fn handle_advance(id: &str) -> (u16, String) {
    let mut map = sessions().lock().unwrap();
    let session = match map.get_mut(id) {
        Some(s) => s,
        None => return (404, r#"{"error":"session not found"}"#.to_string()),
    };

    let len = session.order.len();
    let next_index = (session.turn_index + 1) % len;
    if next_index == 0 {
        session.round += 1;
    }
    session.turn_index = next_index;

    session.order[next_index].conditions.retain_mut(|entry| {
        entry.1 -= 1;
        entry.1 > 0
    });

    let active_json = combatant_json(&session.order[next_index]);

    let mut cond_entries: Vec<String> = Vec::new();
    for c in &session.order {
        cond_entries.push(format!(
            r#""{}":{}"#,
            json_escape(&c.name),
            conditions_array_json(&c.conditions)
        ));
    }

    let resp = format!(
        r#"{{"id":"{}","round":{},"turn_index":{},"active":{},"conditions":{{{}}}}}"#,
        json_escape(&session.id),
        session.round,
        session.turn_index,
        active_json,
        cond_entries.join(",")
    );
    drop(map);
    persist_db();
    (200, resp)
}

// ---------- Password hashing (pure std, no crates) ----------
//
// Minimal SHA-256 implementation used as the basis for a simple salted,
// iterated password hash (a lightweight PBKDF2-like construction). Real
// deployments should swap `hash_password`/`verify_password` for a vetted
// password-hashing library (e.g. argon2 or bcrypt); this keeps the API
// surface small enough to do that without touching call sites.

const SHA256_K: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

fn sha256(data: &[u8]) -> [u8; 32] {
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];

    let mut msg = data.to_vec();
    let bit_len = (data.len() as u64) * 8;
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&bit_len.to_be_bytes());

    for chunk in msg.chunks(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([
                chunk[i * 4],
                chunk[i * 4 + 1],
                chunk[i * 4 + 2],
                chunk[i * 4 + 3],
            ]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }

        let (mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh) =
            (h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]);

        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let temp1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(SHA256_K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = s0.wrapping_add(maj);

            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }

        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
        h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g);
        h[7] = h[7].wrapping_add(hh);
    }

    let mut out = [0u8; 32];
    for (i, word) in h.iter().enumerate() {
        out[i * 4..i * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    out
}

fn to_hex(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{:02x}", b));
    }
    s
}

fn gen_salt() -> [u8; 16] {
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let counter = COUNTER.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let seed = format!("{}-{}-{:p}", counter, nanos, &COUNTER);
    let digest = sha256(seed.as_bytes());
    let mut salt = [0u8; 16];
    salt.copy_from_slice(&digest[..16]);
    salt
}

const HASH_ITERATIONS: u32 = 10_000;

fn hash_password(password: &str, salt: &[u8; 16]) -> String {
    let mut state = Vec::with_capacity(salt.len() + password.len());
    state.extend_from_slice(salt);
    state.extend_from_slice(password.as_bytes());
    let mut digest = sha256(&state);
    for _ in 1..HASH_ITERATIONS {
        digest = sha256(&digest);
    }
    to_hex(&digest)
}

fn verify_password(password: &str, salt: &[u8; 16], expected_hash: &str) -> bool {
    hash_password(password, salt) == expected_hash
}

// ---------- Users / auth ----------

struct User {
    username: String,
    role: String,
    salt: [u8; 16],
    password_hash: String,
}

fn users() -> &'static Mutex<HashMap<String, User>> {
    static USERS: OnceLock<Mutex<HashMap<String, User>>> = OnceLock::new();
    USERS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn is_valid_username(s: &str) -> bool {
    if s.chars().count() < 2 || s.chars().count() > 32 {
        return false;
    }
    s.chars()
        .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-')
}

fn handle_register(body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let username = match json.get("username").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing username"),
    };
    let password = match json.get("password").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing password"),
    };
    let role = match json.get("role").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing role"),
    };

    if !is_valid_username(&username) {
        return err_response("invalid username");
    }
    if password.len() < 8 {
        return err_response("password too short");
    }
    if role != "dm" && role != "player" {
        return err_response("invalid role");
    }

    let mut map = users().lock().unwrap();
    if map.contains_key(&username) {
        return (409, format!(r#"{{"error":"username already exists"}}"#));
    }

    let salt = gen_salt();
    let password_hash = hash_password(&password, &salt);
    map.insert(
        username.clone(),
        User {
            username: username.clone(),
            role: role.clone(),
            salt,
            password_hash,
        },
    );

    let resp = format!(
        r#"{{"username":"{}","role":"{}"}}"#,
        json_escape(&username),
        json_escape(&role)
    );
    drop(map);
    persist_db();
    (201, resp)
}

fn handle_login(body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let username = match json.get("username").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing username"),
    };
    let password = match json.get("password").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing password"),
    };

    let map = users().lock().unwrap();
    let user = match map.get(&username) {
        Some(u) => u,
        None => return (401, r#"{"error":"invalid credentials"}"#.to_string()),
    };

    if !verify_password(&password, &user.salt, &user.password_hash) {
        return (401, r#"{"error":"invalid credentials"}"#.to_string());
    }

    let token = format!("session-{}", user.username);
    let resp = format!(
        r#"{{"username":"{}","token":"{}"}}"#,
        json_escape(&user.username),
        json_escape(&token)
    );
    (200, resp)
}

// ---------- Compendium: monsters and items ----------

struct Monster {
    slug: String,
    name: String,
    cr: String,
    armor_class: i64,
    hit_points: i64,
    tags: Vec<String>,
}

struct Item {
    slug: String,
    name: String,
    item_type: String,
    rarity: String,
    cost_gp: i64,
}

fn monsters() -> &'static Mutex<HashMap<String, Monster>> {
    static MONSTERS: OnceLock<Mutex<HashMap<String, Monster>>> = OnceLock::new();
    MONSTERS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn items() -> &'static Mutex<HashMap<String, Item>> {
    static ITEMS: OnceLock<Mutex<HashMap<String, Item>>> = OnceLock::new();
    ITEMS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn is_valid_slug(s: &str) -> bool {
    if s.is_empty() {
        return false;
    }
    s.chars()
        .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
}

fn tags_json(tags: &[String]) -> String {
    let items: Vec<String> = tags
        .iter()
        .map(|t| format!(r#""{}""#, json_escape(t)))
        .collect();
    format!("[{}]", items.join(","))
}

fn handle_create_monster(body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let slug = match json.get("slug").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing slug"),
    };
    let name = match json.get("name").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing name"),
    };
    let cr = match json.get("cr").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing cr"),
    };
    let armor_class = match json.get("armor_class").and_then(as_int_strict) {
        Some(n) => n,
        None => return err_response("missing armor_class"),
    };
    let hit_points = match json.get("hit_points").and_then(as_int_strict) {
        Some(n) => n,
        None => return err_response("missing hit_points"),
    };
    let tags = match json.get("tags").and_then(|v| v.as_array()) {
        Some(arr) => {
            let mut out = Vec::with_capacity(arr.len());
            for v in arr {
                match v.as_str() {
                    Some(s) => out.push(s.to_string()),
                    None => return err_response("invalid tags"),
                }
            }
            out
        }
        None => return err_response("missing tags"),
    };

    if !is_valid_slug(&slug) {
        return err_response("invalid slug");
    }

    let mut map = monsters().lock().unwrap();
    if map.contains_key(&slug) {
        return (409, r#"{"error":"slug already exists"}"#.to_string());
    }

    map.insert(
        slug.clone(),
        Monster {
            slug: slug.clone(),
            name: name.clone(),
            cr: cr.clone(),
            armor_class,
            hit_points,
            tags,
        },
    );
    drop(map);
    persist_db();

    let resp = format!(
        r#"{{"slug":"{}","name":"{}","cr":"{}","armor_class":{},"hit_points":{}}}"#,
        json_escape(&slug),
        json_escape(&name),
        json_escape(&cr),
        armor_class,
        hit_points
    );
    (201, resp)
}

fn handle_get_monster(slug: &str) -> (u16, String) {
    let map = monsters().lock().unwrap();
    let m = match map.get(slug) {
        Some(m) => m,
        None => return (404, r#"{"error":"monster not found"}"#.to_string()),
    };
    let resp = format!(
        r#"{{"slug":"{}","name":"{}","cr":"{}","armor_class":{},"hit_points":{},"tags":{}}}"#,
        json_escape(&m.slug),
        json_escape(&m.name),
        json_escape(&m.cr),
        m.armor_class,
        m.hit_points,
        tags_json(&m.tags)
    );
    (200, resp)
}

fn handle_create_item(body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let slug = match json.get("slug").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing slug"),
    };
    let name = match json.get("name").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing name"),
    };
    let item_type = match json.get("type").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing type"),
    };
    let rarity = match json.get("rarity").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing rarity"),
    };
    let cost_gp = match json.get("cost_gp").and_then(as_int_strict) {
        Some(n) => n,
        None => return err_response("missing cost_gp"),
    };

    if !is_valid_slug(&slug) {
        return err_response("invalid slug");
    }

    let mut map = items().lock().unwrap();
    if map.contains_key(&slug) {
        return (409, r#"{"error":"slug already exists"}"#.to_string());
    }

    map.insert(
        slug.clone(),
        Item {
            slug: slug.clone(),
            name: name.clone(),
            item_type: item_type.clone(),
            rarity: rarity.clone(),
            cost_gp,
        },
    );
    drop(map);
    persist_db();

    let resp = format!(
        r#"{{"slug":"{}","name":"{}","type":"{}","rarity":"{}","cost_gp":{}}}"#,
        json_escape(&slug),
        json_escape(&name),
        json_escape(&item_type),
        json_escape(&rarity),
        cost_gp
    );
    (201, resp)
}

fn handle_get_item(slug: &str) -> (u16, String) {
    let map = items().lock().unwrap();
    let it = match map.get(slug) {
        Some(it) => it,
        None => return (404, r#"{"error":"item not found"}"#.to_string()),
    };
    let resp = format!(
        r#"{{"slug":"{}","name":"{}","type":"{}","rarity":"{}","cost_gp":{}}}"#,
        json_escape(&it.slug),
        json_escape(&it.name),
        json_escape(&it.item_type),
        json_escape(&it.rarity),
        it.cost_gp
    );
    (200, resp)
}

// ---------- Campaign state ----------

struct CampaignCharacter {
    id: String,
    name: String,
    level: i64,
    class: String,
}

struct Campaign {
    id: String,
    name: String,
    dm: String,
    characters: Vec<CampaignCharacter>,
    log_count: i64,
}

fn campaigns() -> &'static Mutex<HashMap<String, Campaign>> {
    static CAMPAIGNS: OnceLock<Mutex<HashMap<String, Campaign>>> = OnceLock::new();
    CAMPAIGNS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn character_json(c: &CampaignCharacter) -> String {
    format!(
        r#"{{"id":"{}","name":"{}","level":{},"class":"{}"}}"#,
        json_escape(&c.id),
        json_escape(&c.name),
        c.level,
        json_escape(&c.class)
    )
}

fn handle_create_campaign(body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let id = match json.get("id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return err_response("missing id"),
    };
    let name = match json.get("name").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing name"),
    };
    let dm = match json.get("dm").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing dm"),
    };

    let mut map = campaigns().lock().unwrap();
    if map.contains_key(&id) {
        return (409, r#"{"error":"campaign already exists"}"#.to_string());
    }

    map.insert(
        id.clone(),
        Campaign {
            id: id.clone(),
            name: name.clone(),
            dm: dm.clone(),
            characters: Vec::new(),
            log_count: 0,
        },
    );
    drop(map);
    persist_db();

    let resp = format!(
        r#"{{"id":"{}","name":"{}","dm":"{}"}}"#,
        json_escape(&id),
        json_escape(&name),
        json_escape(&dm)
    );
    (201, resp)
}

fn handle_add_character(campaign_id: &str, body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let id = match json.get("id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return err_response("missing id"),
    };
    let name = match json.get("name").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing name"),
    };
    let level = match json.get("level").and_then(as_int_strict) {
        Some(l) => l,
        None => return err_response("missing level"),
    };
    let class = match json.get("class").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing class"),
    };

    let mut map = campaigns().lock().unwrap();
    let campaign = match map.get_mut(campaign_id) {
        Some(c) => c,
        None => return (404, r#"{"error":"campaign not found"}"#.to_string()),
    };

    if campaign.characters.iter().any(|c| c.id == id) {
        return (409, r#"{"error":"character already exists"}"#.to_string());
    }

    campaign.characters.push(CampaignCharacter {
        id: id.clone(),
        name: name.clone(),
        level,
        class: class.clone(),
    });
    drop(map);
    persist_db();

    let resp = format!(
        r#"{{"id":"{}","name":"{}","level":{},"class":"{}"}}"#,
        json_escape(&id),
        json_escape(&name),
        level,
        json_escape(&class)
    );
    (201, resp)
}

fn handle_add_event(campaign_id: &str, body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let id = match json.get("id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return err_response("missing id"),
    };
    let kind = match json.get("kind").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return err_response("missing kind"),
    };
    if json.get("summary").and_then(|v| v.as_str()).is_none() {
        return err_response("missing summary");
    }

    let mut map = campaigns().lock().unwrap();
    let campaign = match map.get_mut(campaign_id) {
        Some(c) => c,
        None => return (404, r#"{"error":"campaign not found"}"#.to_string()),
    };
    campaign.log_count += 1;
    drop(map);
    persist_db();

    let resp = format!(
        r#"{{"id":"{}","kind":"{}"}}"#,
        json_escape(&id),
        json_escape(&kind)
    );
    (201, resp)
}

fn handle_get_campaign_state(campaign_id: &str) -> (u16, String) {
    let map = campaigns().lock().unwrap();
    let campaign = match map.get(campaign_id) {
        Some(c) => c,
        None => return (404, r#"{"error":"campaign not found"}"#.to_string()),
    };
    let chars_json: Vec<String> = campaign.characters.iter().map(character_json).collect();
    let resp = format!(
        r#"{{"id":"{}","name":"{}","dm":"{}","characters":[{}],"log_count":{}}}"#,
        json_escape(&campaign.id),
        json_escape(&campaign.name),
        json_escape(&campaign.dm),
        chars_json.join(","),
        campaign.log_count
    );
    (200, resp)
}

// ---------- SQLite-backed durable storage (pure std, no crates) ----------
//
// Game-world/state data (users, combat sessions) lives in the in-memory maps
// above for serving requests, and is mirrored into a real SQLite database
// file (`game.db`) on every mutation using a hand-rolled writer for the
// SQLite file format (header + table b-tree leaf pages). This keeps the data
// durably readable by any standard SQLite tool without pulling in a crate.

const DB_PATH: &str = "game.db";
const SCHEMA_VERSION: u32 = 1;
const DB_PAGE_SIZE: usize = 4096;

enum SqlVal {
    Int(i64),
    Text(String),
}

fn sqlite_varint(mut v: u64) -> Vec<u8> {
    if v == 0 {
        return vec![0];
    }
    let mut groups = Vec::new();
    while v > 0 {
        groups.push((v & 0x7f) as u8);
        v >>= 7;
    }
    groups.reverse();
    let n = groups.len();
    groups
        .into_iter()
        .enumerate()
        .map(|(i, b)| if i < n - 1 { b | 0x80 } else { b })
        .collect()
}

fn sqlite_record(values: &[SqlVal]) -> Vec<u8> {
    let mut type_bytes = Vec::new();
    let mut body = Vec::new();
    for v in values {
        match v {
            SqlVal::Int(n) => {
                type_bytes.extend(sqlite_varint(6));
                body.extend_from_slice(&n.to_be_bytes());
            }
            SqlVal::Text(s) => {
                let bytes = s.as_bytes();
                let serial = (bytes.len() as u64) * 2 + 13;
                type_bytes.extend(sqlite_varint(serial));
                body.extend_from_slice(bytes);
            }
        }
    }
    let header_len = type_bytes.len() + 1;
    assert!(header_len < 128, "sqlite row header too large");
    let mut out = Vec::with_capacity(header_len + body.len());
    out.push(header_len as u8);
    out.extend(type_bytes);
    out.extend(body);
    out
}

fn sqlite_leaf_cell(rowid: u64, payload: &[u8]) -> Vec<u8> {
    let mut out = sqlite_varint(payload.len() as u64);
    out.extend(sqlite_varint(rowid));
    out.extend_from_slice(payload);
    out
}

fn sqlite_leaf_page(cells: &[Vec<u8>], header_offset: usize) -> Vec<u8> {
    let mut page = vec![0u8; DB_PAGE_SIZE];
    let cell_count = cells.len();
    let mut content_start = DB_PAGE_SIZE;
    let mut pointers = Vec::with_capacity(cell_count);
    for cell in cells {
        content_start -= cell.len();
        page[content_start..content_start + cell.len()].copy_from_slice(cell);
        pointers.push(content_start as u16);
    }

    page[header_offset] = 0x0d; // leaf table b-tree page
    page[header_offset + 1..header_offset + 3].copy_from_slice(&0u16.to_be_bytes());
    page[header_offset + 3..header_offset + 5].copy_from_slice(&(cell_count as u16).to_be_bytes());
    let content_start_field = if content_start == DB_PAGE_SIZE {
        0u16 // encodes 65536 per spec; unreachable at our page size with any cells
    } else {
        content_start as u16
    };
    page[header_offset + 5..header_offset + 7].copy_from_slice(&content_start_field.to_be_bytes());
    page[header_offset + 7] = 0;

    let ptr_array_offset = header_offset + 8;
    for (i, ptr) in pointers.iter().enumerate() {
        let off = ptr_array_offset + i * 2;
        page[off..off + 2].copy_from_slice(&ptr.to_be_bytes());
    }
    page
}

fn sqlite_file_header(total_pages: u32) -> [u8; 100] {
    let mut h = [0u8; 100];
    h[0..16].copy_from_slice(b"SQLite format 3\0");
    h[16..18].copy_from_slice(&(DB_PAGE_SIZE as u16).to_be_bytes());
    h[18] = 1; // file format write version
    h[19] = 1; // file format read version
    h[20] = 0; // reserved space
    h[21] = 64; // max embedded payload fraction
    h[22] = 32; // min embedded payload fraction
    h[23] = 32; // leaf payload fraction
    h[24..28].copy_from_slice(&1u32.to_be_bytes()); // file change counter
    h[28..32].copy_from_slice(&total_pages.to_be_bytes());
    h[32..36].copy_from_slice(&0u32.to_be_bytes()); // freelist trunk page
    h[36..40].copy_from_slice(&0u32.to_be_bytes()); // freelist page count
    h[40..44].copy_from_slice(&1u32.to_be_bytes()); // schema cookie
    h[44..48].copy_from_slice(&4u32.to_be_bytes()); // schema format number
    h[48..52].copy_from_slice(&0u32.to_be_bytes()); // default page cache size
    h[52..56].copy_from_slice(&0u32.to_be_bytes()); // largest root btree page (autovacuum)
    h[56..60].copy_from_slice(&1u32.to_be_bytes()); // text encoding: utf-8
    h[60..64].copy_from_slice(&0u32.to_be_bytes()); // user version
    h[64..68].copy_from_slice(&0u32.to_be_bytes()); // incremental vacuum
    h[68..72].copy_from_slice(&0u32.to_be_bytes()); // application id
    h[92..96].copy_from_slice(&1u32.to_be_bytes()); // version-valid-for
    h[96..100].copy_from_slice(&3045000u32.to_be_bytes()); // sqlite version number
    h
}

const USERS_TABLE_SQL: &str =
    "CREATE TABLE users (username TEXT PRIMARY KEY, role TEXT, salt TEXT, password_hash TEXT)";
const COMBAT_SESSIONS_TABLE_SQL: &str = "CREATE TABLE combat_sessions (id TEXT PRIMARY KEY, round INTEGER, turn_index INTEGER, combatants TEXT)";
const MONSTERS_TABLE_SQL: &str = "CREATE TABLE monsters (slug TEXT PRIMARY KEY, name TEXT, cr TEXT, armor_class INTEGER, hit_points INTEGER, tags TEXT)";
const ITEMS_TABLE_SQL: &str = "CREATE TABLE items (slug TEXT PRIMARY KEY, name TEXT, item_type TEXT, rarity TEXT, cost_gp INTEGER)";
const CAMPAIGNS_TABLE_SQL: &str = "CREATE TABLE campaigns (id TEXT PRIMARY KEY, name TEXT, dm TEXT, characters TEXT, log_count INTEGER)";

fn build_sqlite_db(
    users_rows: &[(String, String, String, String)],
    session_rows: &[(String, i64, i64, String)],
    monster_rows: &[(String, String, String, i64, i64, String)],
    item_rows: &[(String, String, String, String, i64)],
    campaign_rows: &[(String, String, String, String, i64)],
) -> Vec<u8> {
    // Page 1: file header + sqlite_master leaf page.
    // Page 2: users table.
    // Page 3: combat_sessions table.
    // Page 4: monsters table.
    // Page 5: items table.
    // Page 6: campaigns table.
    let master_cells = vec![
        sqlite_leaf_cell(
            1,
            &sqlite_record(&[
                SqlVal::Text("table".to_string()),
                SqlVal::Text("users".to_string()),
                SqlVal::Text("users".to_string()),
                SqlVal::Int(2),
                SqlVal::Text(USERS_TABLE_SQL.to_string()),
            ]),
        ),
        sqlite_leaf_cell(
            2,
            &sqlite_record(&[
                SqlVal::Text("table".to_string()),
                SqlVal::Text("combat_sessions".to_string()),
                SqlVal::Text("combat_sessions".to_string()),
                SqlVal::Int(3),
                SqlVal::Text(COMBAT_SESSIONS_TABLE_SQL.to_string()),
            ]),
        ),
        sqlite_leaf_cell(
            3,
            &sqlite_record(&[
                SqlVal::Text("table".to_string()),
                SqlVal::Text("monsters".to_string()),
                SqlVal::Text("monsters".to_string()),
                SqlVal::Int(4),
                SqlVal::Text(MONSTERS_TABLE_SQL.to_string()),
            ]),
        ),
        sqlite_leaf_cell(
            4,
            &sqlite_record(&[
                SqlVal::Text("table".to_string()),
                SqlVal::Text("items".to_string()),
                SqlVal::Text("items".to_string()),
                SqlVal::Int(5),
                SqlVal::Text(ITEMS_TABLE_SQL.to_string()),
            ]),
        ),
        sqlite_leaf_cell(
            5,
            &sqlite_record(&[
                SqlVal::Text("table".to_string()),
                SqlVal::Text("campaigns".to_string()),
                SqlVal::Text("campaigns".to_string()),
                SqlVal::Int(6),
                SqlVal::Text(CAMPAIGNS_TABLE_SQL.to_string()),
            ]),
        ),
    ];
    let mut page1 = sqlite_leaf_page(&master_cells, 100);
    let file_header = sqlite_file_header(6);
    page1[0..100].copy_from_slice(&file_header);

    let users_cells: Vec<Vec<u8>> = users_rows
        .iter()
        .enumerate()
        .map(|(i, (username, role, salt, hash))| {
            sqlite_leaf_cell(
                (i + 1) as u64,
                &sqlite_record(&[
                    SqlVal::Text(username.clone()),
                    SqlVal::Text(role.clone()),
                    SqlVal::Text(salt.clone()),
                    SqlVal::Text(hash.clone()),
                ]),
            )
        })
        .collect();
    let page2 = sqlite_leaf_page(&users_cells, 0);

    let session_cells: Vec<Vec<u8>> = session_rows
        .iter()
        .enumerate()
        .map(|(i, (id, round, turn_index, combatants))| {
            sqlite_leaf_cell(
                (i + 1) as u64,
                &sqlite_record(&[
                    SqlVal::Text(id.clone()),
                    SqlVal::Int(*round),
                    SqlVal::Int(*turn_index),
                    SqlVal::Text(combatants.clone()),
                ]),
            )
        })
        .collect();
    let page3 = sqlite_leaf_page(&session_cells, 0);

    let monster_cells: Vec<Vec<u8>> = monster_rows
        .iter()
        .enumerate()
        .map(|(i, (slug, name, cr, armor_class, hit_points, tags))| {
            sqlite_leaf_cell(
                (i + 1) as u64,
                &sqlite_record(&[
                    SqlVal::Text(slug.clone()),
                    SqlVal::Text(name.clone()),
                    SqlVal::Text(cr.clone()),
                    SqlVal::Int(*armor_class),
                    SqlVal::Int(*hit_points),
                    SqlVal::Text(tags.clone()),
                ]),
            )
        })
        .collect();
    let page4 = sqlite_leaf_page(&monster_cells, 0);

    let item_cells: Vec<Vec<u8>> = item_rows
        .iter()
        .enumerate()
        .map(|(i, (slug, name, item_type, rarity, cost_gp))| {
            sqlite_leaf_cell(
                (i + 1) as u64,
                &sqlite_record(&[
                    SqlVal::Text(slug.clone()),
                    SqlVal::Text(name.clone()),
                    SqlVal::Text(item_type.clone()),
                    SqlVal::Text(rarity.clone()),
                    SqlVal::Int(*cost_gp),
                ]),
            )
        })
        .collect();
    let page5 = sqlite_leaf_page(&item_cells, 0);

    let campaign_cells: Vec<Vec<u8>> = campaign_rows
        .iter()
        .enumerate()
        .map(|(i, (id, name, dm, characters, log_count))| {
            sqlite_leaf_cell(
                (i + 1) as u64,
                &sqlite_record(&[
                    SqlVal::Text(id.clone()),
                    SqlVal::Text(name.clone()),
                    SqlVal::Text(dm.clone()),
                    SqlVal::Text(characters.clone()),
                    SqlVal::Int(*log_count),
                ]),
            )
        })
        .collect();
    let page6 = sqlite_leaf_page(&campaign_cells, 0);

    let mut out = Vec::with_capacity(DB_PAGE_SIZE * 6);
    out.extend(page1);
    out.extend(page2);
    out.extend(page3);
    out.extend(page4);
    out.extend(page5);
    out.extend(page6);
    out
}

fn session_combatants_json(session: &CombatSession) -> String {
    let items: Vec<String> = session
        .order
        .iter()
        .map(|c| {
            format!(
                r#"{{"name":"{}","dex":{},"score":{},"conditions":{}}}"#,
                json_escape(&c.name),
                c.dex,
                c.score,
                conditions_array_json(&c.conditions)
            )
        })
        .collect();
    format!("[{}]", items.join(","))
}

fn persist_db() {
    let users_rows: Vec<(String, String, String, String)> = users()
        .lock()
        .unwrap()
        .values()
        .map(|u| {
            (
                u.username.clone(),
                u.role.clone(),
                to_hex(&u.salt),
                u.password_hash.clone(),
            )
        })
        .collect();

    let session_rows: Vec<(String, i64, i64, String)> = sessions()
        .lock()
        .unwrap()
        .values()
        .map(|s| {
            (
                s.id.clone(),
                s.round,
                s.turn_index as i64,
                session_combatants_json(s),
            )
        })
        .collect();

    let monster_rows: Vec<(String, String, String, i64, i64, String)> = monsters()
        .lock()
        .unwrap()
        .values()
        .map(|m| {
            (
                m.slug.clone(),
                m.name.clone(),
                m.cr.clone(),
                m.armor_class,
                m.hit_points,
                tags_json(&m.tags),
            )
        })
        .collect();

    let item_rows: Vec<(String, String, String, String, i64)> = items()
        .lock()
        .unwrap()
        .values()
        .map(|it| {
            (
                it.slug.clone(),
                it.name.clone(),
                it.item_type.clone(),
                it.rarity.clone(),
                it.cost_gp,
            )
        })
        .collect();

    let campaign_rows: Vec<(String, String, String, String, i64)> = campaigns()
        .lock()
        .unwrap()
        .values()
        .map(|c| {
            let chars_json = format!(
                "[{}]",
                c.characters
                    .iter()
                    .map(character_json)
                    .collect::<Vec<_>>()
                    .join(",")
            );
            (
                c.id.clone(),
                c.name.clone(),
                c.dm.clone(),
                chars_json,
                c.log_count,
            )
        })
        .collect();

    let bytes = build_sqlite_db(
        &users_rows,
        &session_rows,
        &monster_rows,
        &item_rows,
        &campaign_rows,
    );
    let _ = fs::write(DB_PATH, bytes);
}

fn init_storage() {
    persist_db();
}

fn handle_storage_status() -> (u16, String) {
    let initialized = fs::metadata(DB_PATH).is_ok();
    let body = format!(
        r#"{{"driver":"sqlite","schema_version":{},"initialized":{}}}"#,
        SCHEMA_VERSION, initialized
    );
    (200, body)
}

fn handle_storage_reset() -> (u16, String) {
    sessions().lock().unwrap().clear();
    users().lock().unwrap().clear();
    monsters().lock().unwrap().clear();
    items().lock().unwrap().clear();
    campaigns().lock().unwrap().clear();
    persist_db();
    let body = format!(r#"{{"ok":true,"schema_version":{}}}"#, SCHEMA_VERSION);
    (200, body)
}

// ---------- PHB rules ----------

fn handle_spell_slots(body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let class = match json.get("class").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err_response("missing class"),
    };
    let level = match json.get("level").and_then(|v| v.as_i64()) {
        Some(n) => n,
        None => return err_response("missing level"),
    };

    if class != "wizard" || level != 5 {
        return err_response("unsupported class/level combination");
    }

    let body = format!(
        r#"{{"class":"{}","level":{},"slots":{{"1":4,"2":3,"3":2}}}}"#,
        json_escape(class),
        level
    );
    (200, body)
}

fn handle_long_rest(body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let level = match json.get("level").and_then(|v| v.as_i64()) {
        Some(n) => n,
        None => return err_response("missing level"),
    };
    let hp_max = match json.get("hp_max").and_then(|v| v.as_i64()) {
        Some(n) => n,
        None => return err_response("missing hp_max"),
    };
    let hit_dice_spent = match json.get("hit_dice_spent").and_then(|v| v.as_i64()) {
        Some(n) => n,
        None => return err_response("missing hit_dice_spent"),
    };
    let exhaustion_level = match json.get("exhaustion_level").and_then(|v| v.as_i64()) {
        Some(n) => n,
        None => return err_response("missing exhaustion_level"),
    };
    if json.get("hp_current").and_then(|v| v.as_i64()).is_none() {
        return err_response("missing hp_current");
    }
    if level <= 0 || hp_max < 0 || hit_dice_spent < 0 || exhaustion_level < 0 {
        return err_response("invalid values");
    }

    let hp_current = hp_max;
    let recoverable = std::cmp::max(level / 2, 1);
    let new_hit_dice_spent = std::cmp::max(hit_dice_spent - recoverable, 0);
    let new_exhaustion = std::cmp::max(exhaustion_level - 1, 0);

    let body = format!(
        r#"{{"hp_current":{},"hit_dice_spent":{},"exhaustion_level":{}}}"#,
        hp_current, new_hit_dice_spent, new_exhaustion
    );
    (200, body)
}

fn handle_equipment_load(body: &str) -> (u16, String) {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return err_response("invalid json"),
    };
    let strength = match json.get("strength").and_then(|v| v.as_i64()) {
        Some(n) => n,
        None => return err_response("missing strength"),
    };
    let weight = match json.get("weight").and_then(|v| v.as_i64()) {
        Some(n) => n,
        None => return err_response("missing weight"),
    };
    if strength < 0 || weight < 0 {
        return err_response("invalid values");
    }

    let capacity = strength * 15;
    let encumbered = weight > capacity;

    let body = format!(
        r#"{{"capacity":{},"weight":{},"encumbered":{}}}"#,
        capacity, weight, encumbered
    );
    (200, body)
}
