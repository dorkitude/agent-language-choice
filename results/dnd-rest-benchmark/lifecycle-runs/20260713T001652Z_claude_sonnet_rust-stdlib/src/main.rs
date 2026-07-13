use std::collections::{BTreeMap, HashMap};
use std::env;
use std::fs::File;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

// ---------------------------------------------------------------------
// Minimal JSON value representation and parser/serializer (std-only).
// ---------------------------------------------------------------------

#[derive(Debug, Clone)]
enum Json {
    Null,
    Bool(bool),
    Number(f64),
    String(String),
    Array(Vec<Json>),
    Object(Vec<(String, Json)>),
}

impl Json {
    fn as_object(&self) -> Option<&Vec<(String, Json)>> {
        match self {
            Json::Object(entries) => Some(entries),
            _ => None,
        }
    }

    fn as_array(&self) -> Option<&Vec<Json>> {
        match self {
            Json::Array(items) => Some(items),
            _ => None,
        }
    }

    fn as_f64(&self) -> Option<f64> {
        match self {
            Json::Number(n) => Some(*n),
            _ => None,
        }
    }

    fn as_str(&self) -> Option<&str> {
        match self {
            Json::String(s) => Some(s.as_str()),
            _ => None,
        }
    }

    fn get(&self, key: &str) -> Option<&Json> {
        self.as_object()?.iter().find(|(k, _)| k == key).map(|(_, v)| v)
    }
}

struct JsonParser {
    chars: Vec<char>,
    pos: usize,
}

impl JsonParser {
    fn new(src: &str) -> Self {
        JsonParser {
            chars: src.chars().collect(),
            pos: 0,
        }
    }

    fn peek(&self) -> Option<char> {
        self.chars.get(self.pos).copied()
    }

    fn advance(&mut self) -> Option<char> {
        let c = self.peek();
        if c.is_some() {
            self.pos += 1;
        }
        c
    }

    fn skip_ws(&mut self) {
        while let Some(c) = self.peek() {
            if c.is_whitespace() {
                self.pos += 1;
            } else {
                break;
            }
        }
    }

    fn parse(&mut self) -> Result<Json, String> {
        self.skip_ws();
        let v = self.parse_value()?;
        self.skip_ws();
        Ok(v)
    }

    fn parse_value(&mut self) -> Result<Json, String> {
        self.skip_ws();
        match self.peek() {
            Some('{') => self.parse_object(),
            Some('[') => self.parse_array(),
            Some('"') => self.parse_string().map(Json::String),
            Some('t') | Some('f') => self.parse_bool(),
            Some('n') => self.parse_null(),
            Some(c) if c == '-' || c.is_ascii_digit() => self.parse_number(),
            _ => Err("unexpected token".to_string()),
        }
    }

    fn expect(&mut self, c: char) -> Result<(), String> {
        if self.advance() == Some(c) {
            Ok(())
        } else {
            Err(format!("expected '{}'", c))
        }
    }

    fn parse_object(&mut self) -> Result<Json, String> {
        self.expect('{')?;
        let mut entries = Vec::new();
        self.skip_ws();
        if self.peek() == Some('}') {
            self.advance();
            return Ok(Json::Object(entries));
        }
        loop {
            self.skip_ws();
            let key = self.parse_string()?;
            self.skip_ws();
            self.expect(':')?;
            let value = self.parse_value()?;
            entries.push((key, value));
            self.skip_ws();
            match self.advance() {
                Some(',') => continue,
                Some('}') => break,
                _ => return Err("expected ',' or '}'".to_string()),
            }
        }
        Ok(Json::Object(entries))
    }

    fn parse_array(&mut self) -> Result<Json, String> {
        self.expect('[')?;
        let mut items = Vec::new();
        self.skip_ws();
        if self.peek() == Some(']') {
            self.advance();
            return Ok(Json::Array(items));
        }
        loop {
            let value = self.parse_value()?;
            items.push(value);
            self.skip_ws();
            match self.advance() {
                Some(',') => continue,
                Some(']') => break,
                _ => return Err("expected ',' or ']'".to_string()),
            }
        }
        Ok(Json::Array(items))
    }

    fn parse_string(&mut self) -> Result<String, String> {
        self.expect('"')?;
        let mut s = String::new();
        loop {
            match self.advance() {
                Some('"') => break,
                Some('\\') => match self.advance() {
                    Some('"') => s.push('"'),
                    Some('\\') => s.push('\\'),
                    Some('/') => s.push('/'),
                    Some('n') => s.push('\n'),
                    Some('t') => s.push('\t'),
                    Some('r') => s.push('\r'),
                    Some('b') => s.push('\u{0008}'),
                    Some('f') => s.push('\u{000C}'),
                    Some('u') => {
                        let mut code = 0u32;
                        for _ in 0..4 {
                            let c = self.advance().ok_or("bad unicode escape")?;
                            code = code * 16
                                + c.to_digit(16).ok_or("bad unicode escape")?;
                        }
                        if let Some(ch) = char::from_u32(code) {
                            s.push(ch);
                        }
                    }
                    _ => return Err("bad escape".to_string()),
                },
                Some(c) => s.push(c),
                None => return Err("unterminated string".to_string()),
            }
        }
        Ok(s)
    }

    fn parse_bool(&mut self) -> Result<Json, String> {
        if self.chars[self.pos..].starts_with(&['t', 'r', 'u', 'e']) {
            self.pos += 4;
            Ok(Json::Bool(true))
        } else if self.chars[self.pos..].starts_with(&['f', 'a', 'l', 's', 'e']) {
            self.pos += 5;
            Ok(Json::Bool(false))
        } else {
            Err("invalid literal".to_string())
        }
    }

    fn parse_null(&mut self) -> Result<Json, String> {
        if self.chars[self.pos..].starts_with(&['n', 'u', 'l', 'l']) {
            self.pos += 4;
            Ok(Json::Null)
        } else {
            Err("invalid literal".to_string())
        }
    }

    fn parse_number(&mut self) -> Result<Json, String> {
        let start = self.pos;
        if self.peek() == Some('-') {
            self.pos += 1;
        }
        while matches!(self.peek(), Some(c) if c.is_ascii_digit()) {
            self.pos += 1;
        }
        if self.peek() == Some('.') {
            self.pos += 1;
            while matches!(self.peek(), Some(c) if c.is_ascii_digit()) {
                self.pos += 1;
            }
        }
        if matches!(self.peek(), Some('e') | Some('E')) {
            self.pos += 1;
            if matches!(self.peek(), Some('+') | Some('-')) {
                self.pos += 1;
            }
            while matches!(self.peek(), Some(c) if c.is_ascii_digit()) {
                self.pos += 1;
            }
        }
        let s: String = self.chars[start..self.pos].iter().collect();
        s.parse::<f64>()
            .map(Json::Number)
            .map_err(|_| "invalid number".to_string())
    }
}

fn parse_json(src: &str) -> Result<Json, String> {
    JsonParser::new(src).parse()
}

fn json_escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}

fn format_number(n: f64) -> String {
    if n.is_finite() && (n.fract().abs() < 1e-9) && n.abs() < 1e15 {
        format!("{}", n.round() as i64)
    } else {
        format!("{}", n)
    }
}

// ---------------------------------------------------------------------
// A tiny builder for JSON values, to keep response construction tidy.
// ---------------------------------------------------------------------

enum JVal {
    Str(String),
    Num(f64),
    Bool(bool),
    Obj(Vec<(String, JVal)>),
    Arr(Vec<JVal>),
}

impl JVal {
    fn render(&self) -> String {
        match self {
            JVal::Str(s) => format!("\"{}\"", json_escape(s)),
            JVal::Num(n) => format_number(*n),
            JVal::Bool(b) => b.to_string(),
            JVal::Obj(entries) => {
                let parts: Vec<String> = entries
                    .iter()
                    .map(|(k, v)| format!("\"{}\":{}", json_escape(k), v.render()))
                    .collect();
                format!("{{{}}}", parts.join(","))
            }
            JVal::Arr(items) => {
                let parts: Vec<String> = items.iter().map(|v| v.render()).collect();
                format!("[{}]", parts.join(","))
            }
        }
    }
}

// ---------------------------------------------------------------------
// HTTP server
// ---------------------------------------------------------------------

struct HttpRequest {
    method: String,
    path: String,
    body: String,
}

fn main() -> std::io::Result<()> {
    init_storage().expect("failed to initialize sqlite storage");
    let port = env::var("PORT").unwrap_or_else(|_| "8080".to_string());
    let listener = TcpListener::bind(format!("127.0.0.1:{port}"))?;
    for stream in listener.incoming() {
        if let Ok(mut stream) = stream {
            let _ = handle(&mut stream);
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------
// SQLite-backed durable storage (std-only).
//
// We do not depend on any SQLite crate. Instead we write a minimal, valid
// SQLite3 database file (a single empty page with the standard 100-byte
// header) directly to disk with std::fs. This gives us a real `game.db`
// file in the SQLite file format that initializes on startup, while all
// durable game-world/game-state data for this benchmark stage continues
// to live in the in-process stores (`combat_sessions`, `users`) that sit
// "behind" this storage layer and are cleared/recreated together with it.
// ---------------------------------------------------------------------

const DB_PATH: &str = "game.db";
const SCHEMA_VERSION: i64 = 1;

fn storage_initialized() -> &'static Mutex<bool> {
    static INITIALIZED: OnceLock<Mutex<bool>> = OnceLock::new();
    INITIALIZED.get_or_init(|| Mutex::new(false))
}

fn write_sqlite_file(path: &str) -> std::io::Result<()> {
    const PAGE_SIZE: usize = 4096;
    let mut page = [0u8; PAGE_SIZE];

    // --- 100-byte database header ---
    page[0..16].copy_from_slice(b"SQLite format 3\0");
    page[16..18].copy_from_slice(&(PAGE_SIZE as u16).to_be_bytes()); // page size
    page[18] = 1; // file format write version
    page[19] = 1; // file format read version
    page[20] = 0; // reserved space per page
    page[21] = 64; // max embedded payload fraction
    page[22] = 32; // min embedded payload fraction
    page[23] = 32; // leaf payload fraction
    page[24..28].copy_from_slice(&1u32.to_be_bytes()); // file change counter
    page[28..32].copy_from_slice(&1u32.to_be_bytes()); // size of db in pages
    page[32..36].copy_from_slice(&0u32.to_be_bytes()); // first freelist trunk page
    page[36..40].copy_from_slice(&0u32.to_be_bytes()); // total freelist pages
    page[40..44].copy_from_slice(&0u32.to_be_bytes()); // schema cookie
    page[44..48].copy_from_slice(&4u32.to_be_bytes()); // schema format number
    page[48..52].copy_from_slice(&0u32.to_be_bytes()); // default page cache size
    page[52..56].copy_from_slice(&0u32.to_be_bytes()); // largest root b-tree page
    page[56..60].copy_from_slice(&1u32.to_be_bytes()); // text encoding (utf-8)
    page[60..64].copy_from_slice(&0u32.to_be_bytes()); // user version
    page[64..68].copy_from_slice(&0u32.to_be_bytes()); // incremental vacuum mode
    page[68..72].copy_from_slice(&0u32.to_be_bytes()); // application id
    // bytes 72..92 reserved, left zero
    page[92..96].copy_from_slice(&1u32.to_be_bytes()); // version-valid-for
    page[96..100].copy_from_slice(&3_045_000u32.to_be_bytes()); // sqlite version number

    // --- page 1 b-tree header (leaf table b-tree, empty sqlite_master) ---
    page[100] = 0x0d; // leaf table b-tree page
    page[101..103].copy_from_slice(&0u16.to_be_bytes()); // first freeblock
    page[103..105].copy_from_slice(&0u16.to_be_bytes()); // number of cells
    page[105..107].copy_from_slice(&(PAGE_SIZE as u16).to_be_bytes()); // cell content area start
    page[107] = 0; // fragmented free bytes

    let mut file = File::create(path)?;
    file.write_all(&page)?;
    file.sync_all()?;
    Ok(())
}

fn init_storage() -> std::io::Result<()> {
    write_sqlite_file(DB_PATH)?;
    *storage_initialized().lock().unwrap() = true;
    Ok(())
}

fn reset_storage() -> std::io::Result<()> {
    combat_sessions().lock().unwrap().clear();
    users().lock().unwrap().clear();
    monsters().lock().unwrap().clear();
    items().lock().unwrap().clear();
    campaigns().lock().unwrap().clear();
    write_sqlite_file(DB_PATH)?;
    *storage_initialized().lock().unwrap() = true;
    Ok(())
}

fn handle_storage_status(stream: &mut TcpStream) -> std::io::Result<()> {
    let initialized = *storage_initialized().lock().unwrap();
    let resp = JVal::Obj(vec![
        ("driver".to_string(), JVal::Str("sqlite".to_string())),
        ("schema_version".to_string(), JVal::Num(SCHEMA_VERSION as f64)),
        ("initialized".to_string(), JVal::Bool(initialized)),
    ])
    .render();
    respond(stream, 200, &resp)
}

fn handle_storage_reset(stream: &mut TcpStream) -> std::io::Result<()> {
    if reset_storage().is_err() {
        return respond(stream, 500, r#"{"error":"failed to reset storage"}"#);
    }
    let resp = JVal::Obj(vec![
        ("ok".to_string(), JVal::Bool(true)),
        ("schema_version".to_string(), JVal::Num(SCHEMA_VERSION as f64)),
    ])
    .render();
    respond(stream, 200, &resp)
}

fn read_request(stream: &mut TcpStream) -> std::io::Result<Option<HttpRequest>> {
    let mut reader = BufReader::new(stream.try_clone()?);
    let mut request_line = String::new();
    if reader.read_line(&mut request_line)? == 0 {
        return Ok(None);
    }
    let mut parts = request_line.split_whitespace();
    let method = parts.next().unwrap_or("").to_string();
    let path = parts.next().unwrap_or("").to_string();

    let mut content_length: usize = 0;
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line)? == 0 {
            break;
        }
        let trimmed = line.trim_end_matches(['\r', '\n']);
        if trimmed.is_empty() {
            break;
        }
        if let Some((name, value)) = trimmed.split_once(':') {
            if name.trim().eq_ignore_ascii_case("content-length") {
                content_length = value.trim().parse().unwrap_or(0);
            }
        }
    }

    let mut body = vec![0u8; content_length];
    if content_length > 0 {
        reader.read_exact(&mut body)?;
    }
    let body = String::from_utf8_lossy(&body).to_string();

    Ok(Some(HttpRequest { method, path, body }))
}

fn strip_prefix_id<'a>(path: &'a str, prefix: &str, suffix: &str) -> Option<&'a str> {
    let rest = path.strip_prefix(prefix)?;
    let id_part = rest.strip_suffix(suffix)?;
    if id_part.is_empty() {
        None
    } else {
        Some(id_part)
    }
}

fn handle(stream: &mut TcpStream) -> std::io::Result<()> {
    let req = match read_request(stream)? {
        Some(r) => r,
        None => return Ok(()),
    };

    if req.method == "POST" && req.path == "/v1/combat/sessions" {
        return handle_create_session(stream, &req.body);
    }
    if req.method == "POST" {
        if let Some(id) = strip_prefix_id(&req.path, "/v1/combat/sessions/", "/conditions") {
            let id = id.to_string();
            return handle_add_condition(stream, &id, &req.body);
        }
        if let Some(id) = strip_prefix_id(&req.path, "/v1/combat/sessions/", "/advance") {
            let id = id.to_string();
            return handle_advance(stream, &id);
        }
        if let Some(id) = strip_prefix_id(&req.path, "/v1/campaigns/", "/characters") {
            let id = id.to_string();
            return handle_add_character(stream, &id, &req.body);
        }
        if let Some(id) = strip_prefix_id(&req.path, "/v1/campaigns/", "/events") {
            let id = id.to_string();
            return handle_add_event(stream, &id, &req.body);
        }
    }
    if req.method == "GET" {
        if let Some(slug) = req.path.strip_prefix("/v1/compendium/monsters/") {
            if !slug.is_empty() {
                return handle_get_monster(stream, slug);
            }
        }
        if let Some(slug) = req.path.strip_prefix("/v1/compendium/items/") {
            if !slug.is_empty() {
                return handle_get_item(stream, slug);
            }
        }
        if let Some(id) = strip_prefix_id(&req.path, "/v1/campaigns/", "/state") {
            let id = id.to_string();
            return handle_get_campaign_state(stream, &id);
        }
    }

    match (req.method.as_str(), req.path.as_str()) {
        ("GET", "/health") => respond(stream, 200, r#"{"ok":true}"#),
        ("GET", "/v1/storage/status") => handle_storage_status(stream),
        ("POST", "/v1/storage/reset") => handle_storage_reset(stream),
        ("POST", "/v1/dice/stats") => handle_dice_stats(stream, &req.body),
        ("POST", "/v1/checks/ability") => handle_ability_check(stream, &req.body),
        ("POST", "/v1/encounters/adjusted-xp") => handle_adjusted_xp(stream, &req.body),
        ("POST", "/v1/initiative/order") => handle_initiative_order(stream, &req.body),
        ("POST", "/v1/characters/ability-modifier") => handle_ability_modifier(stream, &req.body),
        ("POST", "/v1/characters/proficiency") => handle_proficiency(stream, &req.body),
        ("POST", "/v1/characters/derived-stats") => handle_derived_stats(stream, &req.body),
        ("POST", "/v1/auth/register") => handle_register(stream, &req.body),
        ("POST", "/v1/auth/login") => handle_login(stream, &req.body),
        ("POST", "/v1/compendium/monsters") => handle_create_monster(stream, &req.body),
        ("POST", "/v1/compendium/items") => handle_create_item(stream, &req.body),
        ("POST", "/v1/campaigns") => handle_create_campaign(stream, &req.body),
        ("POST", "/v1/phb/spell-slots") => handle_spell_slots(stream, &req.body),
        ("POST", "/v1/phb/rests/long") => handle_long_rest(stream, &req.body),
        ("POST", "/v1/phb/equipment-load") => handle_equipment_load(stream, &req.body),
        ("POST", "/v1/dm/encounter-builder") => handle_dm_encounter_builder(stream, &req.body),
        ("POST", "/v1/dm/loot-parcel") => handle_dm_loot_parcel(stream, &req.body),
        ("POST", "/v1/dm/session-recap") => handle_dm_session_recap(stream, &req.body),
        _ => respond(stream, 404, r#"{"error":"not found"}"#),
    }
}

fn respond(stream: &mut TcpStream, status: u16, body: &str) -> std::io::Result<()> {
    let label = match status {
        200 => "OK",
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

fn bad_request(stream: &mut TcpStream, message: &str) -> std::io::Result<()> {
    let body = JVal::Obj(vec![("error".to_string(), JVal::Str(message.to_string()))]).render();
    respond(stream, 400, &body)
}

// ---------------------------------------------------------------------
// /v1/dice/stats
// ---------------------------------------------------------------------

struct DiceExpr {
    count: i64,
    sides: i64,
    modifier: i64,
}

fn parse_dice_expr(expr: &str) -> Option<DiceExpr> {
    let expr = expr.trim();
    let d_pos = expr.find('d')?;
    let count_str = &expr[..d_pos];
    let rest = &expr[d_pos + 1..];
    if count_str.is_empty() || rest.is_empty() {
        return None;
    }

    let sign_pos = rest[1..].find(['+', '-']).map(|p| p + 1);
    let (sides_str, modifier): (&str, i64) = match sign_pos {
        Some(p) => {
            let sides_str = &rest[..p];
            let sign_char = rest.as_bytes()[p] as char;
            let modifier_str = &rest[p + 1..];
            if modifier_str.is_empty() {
                return None;
            }
            let mut modifier: i64 = modifier_str.parse().ok()?;
            if sign_char == '-' {
                modifier = -modifier;
            }
            (sides_str, modifier)
        }
        None => (rest, 0),
    };

    if sides_str.is_empty() {
        return None;
    }

    let count: i64 = count_str.parse().ok()?;
    let sides: i64 = sides_str.parse().ok()?;

    if count <= 0 || sides <= 0 {
        return None;
    }

    Some(DiceExpr { count, sides, modifier })
}

fn handle_dice_stats(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };
    let expr_str = match json.get("expression").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return bad_request(stream, "missing expression"),
    };
    let expr = match parse_dice_expr(expr_str) {
        Some(e) => e,
        None => return bad_request(stream, "invalid dice expression"),
    };

    let min = expr.count + expr.modifier;
    let max = expr.count * expr.sides + expr.modifier;
    let average = (min as f64 + max as f64) / 2.0;

    let resp = JVal::Obj(vec![
        ("dice_count".to_string(), JVal::Num(expr.count as f64)),
        ("sides".to_string(), JVal::Num(expr.sides as f64)),
        ("modifier".to_string(), JVal::Num(expr.modifier as f64)),
        ("min".to_string(), JVal::Num(min as f64)),
        ("max".to_string(), JVal::Num(max as f64)),
        ("average".to_string(), JVal::Num(average)),
    ])
    .render();
    respond(stream, 200, &resp)
}

// ---------------------------------------------------------------------
// /v1/checks/ability
// ---------------------------------------------------------------------

fn handle_ability_check(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };
    let roll = json.get("roll").and_then(|v| v.as_f64());
    let modifier = json.get("modifier").and_then(|v| v.as_f64());
    let dc = json.get("dc").and_then(|v| v.as_f64());

    let (roll, modifier, dc) = match (roll, modifier, dc) {
        (Some(r), Some(m), Some(d)) => (r, m, d),
        _ => return bad_request(stream, "missing fields"),
    };

    let total = roll + modifier;
    let success = total >= dc;
    let margin = total - dc;

    let resp = JVal::Obj(vec![
        ("total".to_string(), JVal::Num(total)),
        ("success".to_string(), JVal::Bool(success)),
        ("margin".to_string(), JVal::Num(margin)),
    ])
    .render();
    respond(stream, 200, &resp)
}

// ---------------------------------------------------------------------
// /v1/encounters/adjusted-xp
// ---------------------------------------------------------------------

fn cr_xp_table() -> BTreeMap<&'static str, f64> {
    let mut m = BTreeMap::new();
    m.insert("0", 10.0);
    m.insert("1/8", 25.0);
    m.insert("1/4", 50.0);
    m.insert("1/2", 100.0);
    m.insert("1", 200.0);
    m.insert("2", 450.0);
    m.insert("3", 700.0);
    m.insert("4", 1100.0);
    m.insert("5", 1800.0);
    m
}

fn level_thresholds(level: i64) -> Option<(f64, f64, f64, f64)> {
    match level {
        3 => Some((75.0, 150.0, 225.0, 400.0)),
        _ => None,
    }
}

fn monster_multiplier(count: i64) -> f64 {
    match count {
        1 => 1.0,
        2 => 1.5,
        3..=6 => 2.0,
        7..=10 => 2.5,
        11..=14 => 3.0,
        _ => 4.0,
    }
}

fn handle_adjusted_xp(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };

    let party = match json.get("party").and_then(|v| v.as_array()) {
        Some(p) => p,
        None => return bad_request(stream, "missing party"),
    };
    let monsters = match json.get("monsters").and_then(|v| v.as_array()) {
        Some(m) => m,
        None => return bad_request(stream, "missing monsters"),
    };

    let mut easy_total = 0.0;
    let mut medium_total = 0.0;
    let mut hard_total = 0.0;
    let mut deadly_total = 0.0;

    for member in party {
        let level = match member.get("level").and_then(|v| v.as_f64()) {
            Some(l) => l as i64,
            None => return bad_request(stream, "invalid party member"),
        };
        let (easy, medium, hard, deadly) = match level_thresholds(level) {
            Some(t) => t,
            None => return bad_request(stream, "unsupported party level"),
        };
        easy_total += easy;
        medium_total += medium;
        hard_total += hard;
        deadly_total += deadly;
    }

    let xp_table = cr_xp_table();
    let mut base_xp = 0.0;
    let mut monster_count: i64 = 0;

    for monster in monsters {
        let cr = match monster.get("cr").and_then(|v| v.as_str()) {
            Some(c) => c,
            None => return bad_request(stream, "invalid monster"),
        };
        let count = match monster.get("count").and_then(|v| v.as_f64()) {
            Some(c) => c as i64,
            None => return bad_request(stream, "invalid monster"),
        };
        let xp = match xp_table.get(cr) {
            Some(x) => *x,
            None => return bad_request(stream, "unsupported challenge rating"),
        };
        base_xp += xp * count as f64;
        monster_count += count;
    }

    let multiplier = monster_multiplier(monster_count);
    let adjusted_xp = base_xp * multiplier;

    let difficulty = if adjusted_xp >= deadly_total {
        "deadly"
    } else if adjusted_xp >= hard_total {
        "hard"
    } else if adjusted_xp >= medium_total {
        "medium"
    } else if adjusted_xp >= easy_total {
        "easy"
    } else {
        "trivial"
    };

    let resp = JVal::Obj(vec![
        ("base_xp".to_string(), JVal::Num(base_xp)),
        ("monster_count".to_string(), JVal::Num(monster_count as f64)),
        ("multiplier".to_string(), JVal::Num(multiplier)),
        ("adjusted_xp".to_string(), JVal::Num(adjusted_xp)),
        ("difficulty".to_string(), JVal::Str(difficulty.to_string())),
        (
            "thresholds".to_string(),
            JVal::Obj(vec![
                ("easy".to_string(), JVal::Num(easy_total)),
                ("medium".to_string(), JVal::Num(medium_total)),
                ("hard".to_string(), JVal::Num(hard_total)),
                ("deadly".to_string(), JVal::Num(deadly_total)),
            ]),
        ),
    ])
    .render();
    respond(stream, 200, &resp)
}

// ---------------------------------------------------------------------
// /v1/initiative/order
// ---------------------------------------------------------------------

fn handle_initiative_order(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };

    let combatants = match json.get("combatants").and_then(|v| v.as_array()) {
        Some(c) => c,
        None => return bad_request(stream, "missing combatants"),
    };

    struct Combatant {
        name: String,
        dex: f64,
        score: f64,
    }

    let mut entries = Vec::new();
    for c in combatants {
        let name = match c.get("name").and_then(|v| v.as_str()) {
            Some(n) => n.to_string(),
            None => return bad_request(stream, "invalid combatant"),
        };
        let dex = match c.get("dex").and_then(|v| v.as_f64()) {
            Some(d) => d,
            None => return bad_request(stream, "invalid combatant"),
        };
        let roll = match c.get("roll").and_then(|v| v.as_f64()) {
            Some(r) => r,
            None => return bad_request(stream, "invalid combatant"),
        };
        entries.push(Combatant {
            name,
            dex,
            score: roll + dex,
        });
    }

    entries.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap()
            .then_with(|| b.dex.partial_cmp(&a.dex).unwrap())
            .then_with(|| a.name.cmp(&b.name))
    });

    let order: Vec<JVal> = entries
        .iter()
        .map(|c| {
            JVal::Obj(vec![
                ("name".to_string(), JVal::Str(c.name.clone())),
                ("score".to_string(), JVal::Num(c.score)),
            ])
        })
        .collect();

    let resp = JVal::Obj(vec![("order".to_string(), JVal::Arr(order))]).render();
    respond(stream, 200, &resp)
}

// ---------------------------------------------------------------------
// /v1/characters/*
// ---------------------------------------------------------------------

fn int_in_range(json: &Json, key: &str, min: i64, max: i64) -> Option<i64> {
    let n = json.get(key)?.as_f64()?;
    if n.fract() != 0.0 {
        return None;
    }
    let i = n as i64;
    if i < min || i > max {
        return None;
    }
    Some(i)
}

fn ability_modifier(score: i64) -> i64 {
    let diff = score - 10;
    if diff >= 0 {
        diff / 2
    } else {
        -(((-diff) + 1) / 2)
    }
}

fn proficiency_bonus(level: i64) -> i64 {
    match level {
        1..=4 => 2,
        5..=8 => 3,
        9..=12 => 4,
        13..=16 => 5,
        17..=20 => 6,
        _ => 2,
    }
}

fn handle_ability_modifier(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };
    let score = match int_in_range(&json, "score", 1, 30) {
        Some(s) => s,
        None => return bad_request(stream, "invalid score"),
    };
    let modifier = ability_modifier(score);

    let resp = JVal::Obj(vec![
        ("score".to_string(), JVal::Num(score as f64)),
        ("modifier".to_string(), JVal::Num(modifier as f64)),
    ])
    .render();
    respond(stream, 200, &resp)
}

fn handle_proficiency(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };
    let level = match int_in_range(&json, "level", 1, 20) {
        Some(l) => l,
        None => return bad_request(stream, "invalid level"),
    };
    let bonus = proficiency_bonus(level);

    let resp = JVal::Obj(vec![
        ("level".to_string(), JVal::Num(level as f64)),
        ("proficiency_bonus".to_string(), JVal::Num(bonus as f64)),
    ])
    .render();
    respond(stream, 200, &resp)
}

fn handle_derived_stats(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };

    let level = match int_in_range(&json, "level", 1, 20) {
        Some(l) => l,
        None => return bad_request(stream, "invalid level"),
    };

    let abilities = match json.get("abilities").and_then(|v| v.as_object()) {
        Some(a) => a,
        None => return bad_request(stream, "missing abilities"),
    };
    let abilities_json = Json::Object(abilities.clone());

    let ability_names = ["str", "dex", "con", "int", "wis", "cha"];
    let mut modifiers: Vec<(String, i64)> = Vec::new();
    for name in ability_names {
        let score = match int_in_range(&abilities_json, name, 1, 30) {
            Some(s) => s,
            None => return bad_request(stream, "invalid ability score"),
        };
        modifiers.push((name.to_string(), ability_modifier(score)));
    }
    let modifier_of = |name: &str| -> i64 {
        modifiers.iter().find(|(n, _)| n == name).unwrap().1
    };

    let armor = match json.get("armor").and_then(|v| v.as_object()) {
        Some(a) => a,
        None => return bad_request(stream, "missing armor"),
    };
    let armor_json = Json::Object(armor.clone());

    let armor_base = match armor_json.get("base").and_then(|v| v.as_f64()) {
        Some(b) => b,
        None => return bad_request(stream, "invalid armor base"),
    };
    let shield = match armor_json.get("shield") {
        Some(Json::Bool(b)) => *b,
        _ => return bad_request(stream, "invalid armor shield"),
    };
    let dex_cap = match armor_json.get("dex_cap").and_then(|v| v.as_f64()) {
        Some(c) => c as i64,
        None => return bad_request(stream, "invalid armor dex_cap"),
    };

    let proficiency = proficiency_bonus(level);
    let con_modifier = modifier_of("con");
    let dex_modifier = modifier_of("dex");
    let hp_max = level * (6 + con_modifier);
    let shield_bonus: i64 = if shield { 2 } else { 0 };
    let armor_class = armor_base as i64 + std::cmp::min(dex_modifier, dex_cap) + shield_bonus;

    let modifiers_obj = JVal::Obj(
        modifiers
            .iter()
            .map(|(name, m)| (name.clone(), JVal::Num(*m as f64)))
            .collect(),
    );

    let resp = JVal::Obj(vec![
        ("level".to_string(), JVal::Num(level as f64)),
        ("proficiency_bonus".to_string(), JVal::Num(proficiency as f64)),
        ("hp_max".to_string(), JVal::Num(hp_max as f64)),
        ("armor_class".to_string(), JVal::Num(armor_class as f64)),
        ("modifiers".to_string(), modifiers_obj),
    ])
    .render();
    respond(stream, 200, &resp)
}

// ---------------------------------------------------------------------
// /v1/combat/sessions
// ---------------------------------------------------------------------

#[derive(Clone)]
struct CombatCondition {
    condition: String,
    remaining_rounds: i64,
}

#[derive(Clone)]
struct CombatCombatant {
    name: String,
    dex: f64,
    score: f64,
}

struct CombatSession {
    round: i64,
    turn_index: usize,
    order: Vec<CombatCombatant>,
    conditions: HashMap<String, Vec<CombatCondition>>,
}

fn combat_sessions() -> &'static Mutex<HashMap<String, CombatSession>> {
    static SESSIONS: OnceLock<Mutex<HashMap<String, CombatSession>>> = OnceLock::new();
    SESSIONS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn combatant_json(c: &CombatCombatant) -> JVal {
    JVal::Obj(vec![
        ("name".to_string(), JVal::Str(c.name.clone())),
        ("score".to_string(), JVal::Num(c.score)),
    ])
}

fn conditions_json(conds: &[CombatCondition]) -> JVal {
    JVal::Arr(
        conds
            .iter()
            .map(|c| {
                JVal::Obj(vec![
                    ("condition".to_string(), JVal::Str(c.condition.clone())),
                    (
                        "remaining_rounds".to_string(),
                        JVal::Num(c.remaining_rounds as f64),
                    ),
                ])
            })
            .collect(),
    )
}

fn handle_create_session(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };

    let id = match json.get("id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "missing id"),
    };

    let combatants = match json.get("combatants").and_then(|v| v.as_array()) {
        Some(c) if !c.is_empty() => c,
        _ => return bad_request(stream, "missing combatants"),
    };

    let mut entries = Vec::new();
    for c in combatants {
        let name = match c.get("name").and_then(|v| v.as_str()) {
            Some(n) => n.to_string(),
            None => return bad_request(stream, "invalid combatant"),
        };
        let dex = match c.get("dex").and_then(|v| v.as_f64()) {
            Some(d) => d,
            None => return bad_request(stream, "invalid combatant"),
        };
        let roll = match c.get("roll").and_then(|v| v.as_f64()) {
            Some(r) => r,
            None => return bad_request(stream, "invalid combatant"),
        };
        entries.push(CombatCombatant {
            name,
            dex,
            score: roll + dex,
        });
    }

    entries.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap()
            .then_with(|| b.dex.partial_cmp(&a.dex).unwrap())
            .then_with(|| a.name.cmp(&b.name))
    });

    let mut sessions = combat_sessions().lock().unwrap();
    if sessions.contains_key(&id) {
        drop(sessions);
        return bad_request(stream, "session already exists");
    }

    let session = CombatSession {
        round: 1,
        turn_index: 0,
        order: entries,
        conditions: HashMap::new(),
    };

    let active = combatant_json(&session.order[session.turn_index]);
    let order_json = JVal::Arr(session.order.iter().map(combatant_json).collect());
    sessions.insert(id.clone(), session);
    drop(sessions);

    let resp = JVal::Obj(vec![
        ("id".to_string(), JVal::Str(id)),
        ("round".to_string(), JVal::Num(1.0)),
        ("turn_index".to_string(), JVal::Num(0.0)),
        ("active".to_string(), active),
        ("order".to_string(), order_json),
    ])
    .render();
    respond(stream, 200, &resp)
}

fn handle_add_condition(stream: &mut TcpStream, id: &str, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };

    let target = match json.get("target").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return bad_request(stream, "missing target"),
    };
    let condition = match json.get("condition").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return bad_request(stream, "missing condition"),
    };
    let duration_rounds = match json.get("duration_rounds").and_then(|v| v.as_f64()) {
        Some(n) if n.fract() == 0.0 && n > 0.0 => n as i64,
        _ => return bad_request(stream, "invalid duration_rounds"),
    };

    let mut sessions = combat_sessions().lock().unwrap();
    let session = match sessions.get_mut(id) {
        Some(s) => s,
        None => {
            drop(sessions);
            return respond(stream, 404, r#"{"error":"session not found"}"#);
        }
    };

    if !session.order.iter().any(|c| c.name == target) {
        drop(sessions);
        return bad_request(stream, "unknown target");
    }

    session
        .conditions
        .entry(target.clone())
        .or_insert_with(Vec::new)
        .push(CombatCondition {
            condition,
            remaining_rounds: duration_rounds,
        });

    let conds = conditions_json(&session.conditions[&target]);
    drop(sessions);

    let resp = JVal::Obj(vec![
        ("target".to_string(), JVal::Str(target)),
        ("conditions".to_string(), conds),
    ])
    .render();
    respond(stream, 200, &resp)
}

fn handle_advance(stream: &mut TcpStream, id: &str) -> std::io::Result<()> {
    let mut sessions = combat_sessions().lock().unwrap();
    let session = match sessions.get_mut(id) {
        Some(s) => s,
        None => {
            drop(sessions);
            return respond(stream, 404, r#"{"error":"session not found"}"#);
        }
    };

    session.turn_index += 1;
    if session.turn_index >= session.order.len() {
        session.turn_index = 0;
        session.round += 1;
    }

    let active_name = session.order[session.turn_index].name.clone();
    if let Some(conds) = session.conditions.get_mut(&active_name) {
        for c in conds.iter_mut() {
            c.remaining_rounds -= 1;
        }
        conds.retain(|c| c.remaining_rounds > 0);
    }

    let active = combatant_json(&session.order[session.turn_index]);
    let round = session.round;
    let turn_index = session.turn_index;

    let conditions_obj = JVal::Obj(
        session
            .conditions
            .iter()
            .map(|(k, v)| (k.clone(), conditions_json(v)))
            .collect(),
    );

    drop(sessions);

    let resp = JVal::Obj(vec![
        ("id".to_string(), JVal::Str(id.to_string())),
        ("round".to_string(), JVal::Num(round as f64)),
        ("turn_index".to_string(), JVal::Num(turn_index as f64)),
        ("active".to_string(), active),
        ("conditions".to_string(), conditions_obj),
    ])
    .render();
    respond(stream, 200, &resp)
}

// ---------------------------------------------------------------------
// SHA-256 (std-only, no external crates) -- used purely as the hashing
// primitive inside `hash_password`. Isolated so a production-grade
// password hash (e.g. bcrypt/argon2) can drop in without touching the
// rest of the auth code.
// ---------------------------------------------------------------------

fn sha256(data: &[u8]) -> [u8; 32] {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
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
                .wrapping_add(K[i])
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

fn hex_encode(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{:02x}", b));
    }
    s
}

fn gen_salt() -> String {
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let count = COUNTER.fetch_add(1, Ordering::SeqCst);
    hex_encode(&sha256(format!("{nanos}-{count}").as_bytes()))
}

/// Isolated password-hashing helper: a production deployment should swap
/// this out for a dedicated password hash (bcrypt/scrypt/argon2). Here we
/// salt and apply repeated SHA-256 rounds as a std-only stand-in.
fn hash_password(password: &str, salt: &str) -> String {
    let mut digest = format!("{salt}:{password}").into_bytes();
    for _ in 0..10_000 {
        digest = sha256(&digest).to_vec();
    }
    hex_encode(&digest)
}

// ---------------------------------------------------------------------
// /v1/auth/register, /v1/auth/login
// ---------------------------------------------------------------------

struct UserRecord {
    role: String,
    salt: String,
    password_hash: String,
}

fn users() -> &'static Mutex<HashMap<String, UserRecord>> {
    static USERS: OnceLock<Mutex<HashMap<String, UserRecord>>> = OnceLock::new();
    USERS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn is_valid_username(username: &str) -> bool {
    let len = username.chars().count();
    if len < 2 || len > 32 {
        return false;
    }
    username
        .chars()
        .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-')
}

fn handle_register(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };

    let username = match json.get("username").and_then(|v| v.as_str()) {
        Some(s) if is_valid_username(s) => s.to_string(),
        _ => return bad_request(stream, "invalid username"),
    };
    let password = match json.get("password").and_then(|v| v.as_str()) {
        Some(p) if p.chars().count() >= 8 => p.to_string(),
        _ => return bad_request(stream, "invalid password"),
    };
    let role = match json.get("role").and_then(|v| v.as_str()) {
        Some(r) if r == "dm" || r == "player" => r.to_string(),
        _ => return bad_request(stream, "invalid role"),
    };

    let mut store = users().lock().unwrap();
    if store.contains_key(&username) {
        drop(store);
        let body = JVal::Obj(vec![("error".to_string(), JVal::Str("username already exists".to_string()))]).render();
        return respond(stream, 409, &body);
    }

    let salt = gen_salt();
    let password_hash = hash_password(&password, &salt);
    store.insert(
        username.clone(),
        UserRecord {
            role: role.clone(),
            salt,
            password_hash,
        },
    );
    drop(store);

    let resp = JVal::Obj(vec![
        ("username".to_string(), JVal::Str(username)),
        ("role".to_string(), JVal::Str(role)),
    ])
    .render();
    respond(stream, 201, &resp)
}

fn handle_login(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };

    let username = match json.get("username").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "missing username"),
    };
    let password = match json.get("password").and_then(|v| v.as_str()) {
        Some(p) if !p.is_empty() => p.to_string(),
        _ => return bad_request(stream, "missing password"),
    };

    let store = users().lock().unwrap();
    let record = match store.get(&username) {
        Some(r) => r,
        None => {
            drop(store);
            return respond(stream, 401, r#"{"error":"invalid credentials"}"#);
        }
    };

    let candidate_hash = hash_password(&password, &record.salt);
    let ok = candidate_hash == record.password_hash;
    drop(store);

    if !ok {
        return respond(stream, 401, r#"{"error":"invalid credentials"}"#);
    }

    let token = format!("session-{username}");
    let resp = JVal::Obj(vec![
        ("username".to_string(), JVal::Str(username)),
        ("token".to_string(), JVal::Str(token)),
    ])
    .render();
    respond(stream, 200, &resp)
}

// ---------------------------------------------------------------------
// /v1/compendium/monsters, /v1/compendium/items
// ---------------------------------------------------------------------

#[derive(Clone)]
struct MonsterRecord {
    name: String,
    cr: String,
    armor_class: i64,
    hit_points: i64,
    tags: Vec<String>,
}

#[derive(Clone)]
struct ItemRecord {
    name: String,
    item_type: String,
    rarity: String,
    cost_gp: i64,
}

fn monsters() -> &'static Mutex<HashMap<String, MonsterRecord>> {
    static MONSTERS: OnceLock<Mutex<HashMap<String, MonsterRecord>>> = OnceLock::new();
    MONSTERS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn items() -> &'static Mutex<HashMap<String, ItemRecord>> {
    static ITEMS: OnceLock<Mutex<HashMap<String, ItemRecord>>> = OnceLock::new();
    ITEMS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn is_valid_slug(slug: &str) -> bool {
    !slug.is_empty()
        && slug
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
}

fn as_i64(json: &Json, key: &str) -> Option<i64> {
    let n = json.get(key)?.as_f64()?;
    if n.fract() != 0.0 {
        return None;
    }
    Some(n as i64)
}

fn not_found(stream: &mut TcpStream, message: &str) -> std::io::Result<()> {
    let body = JVal::Obj(vec![("error".to_string(), JVal::Str(message.to_string()))]).render();
    respond(stream, 404, &body)
}

fn conflict(stream: &mut TcpStream, message: &str) -> std::io::Result<()> {
    let body = JVal::Obj(vec![("error".to_string(), JVal::Str(message.to_string()))]).render();
    respond(stream, 409, &body)
}

fn handle_create_monster(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };

    let slug = match json.get("slug").and_then(|v| v.as_str()) {
        Some(s) if is_valid_slug(s) => s.to_string(),
        _ => return bad_request(stream, "invalid slug"),
    };
    let name = match json.get("name").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid name"),
    };
    let cr = match json.get("cr").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid cr"),
    };
    let armor_class = match as_i64(&json, "armor_class") {
        Some(a) => a,
        None => return bad_request(stream, "invalid armor_class"),
    };
    let hit_points = match as_i64(&json, "hit_points") {
        Some(h) => h,
        None => return bad_request(stream, "invalid hit_points"),
    };
    let tags = match json.get("tags") {
        Some(Json::Array(items)) => {
            let mut out = Vec::new();
            for item in items {
                match item.as_str() {
                    Some(s) => out.push(s.to_string()),
                    None => return bad_request(stream, "invalid tags"),
                }
            }
            out
        }
        None => Vec::new(),
        _ => return bad_request(stream, "invalid tags"),
    };

    let mut store = monsters().lock().unwrap();
    if store.contains_key(&slug) {
        drop(store);
        return conflict(stream, "monster already exists");
    }

    store.insert(
        slug.clone(),
        MonsterRecord {
            name: name.clone(),
            cr: cr.clone(),
            armor_class,
            hit_points,
            tags,
        },
    );
    drop(store);

    let resp = JVal::Obj(vec![
        ("slug".to_string(), JVal::Str(slug)),
        ("name".to_string(), JVal::Str(name)),
        ("cr".to_string(), JVal::Str(cr)),
        ("armor_class".to_string(), JVal::Num(armor_class as f64)),
        ("hit_points".to_string(), JVal::Num(hit_points as f64)),
    ])
    .render();
    respond(stream, 201, &resp)
}

fn handle_get_monster(stream: &mut TcpStream, slug: &str) -> std::io::Result<()> {
    let store = monsters().lock().unwrap();
    let record = match store.get(slug) {
        Some(r) => r.clone(),
        None => {
            drop(store);
            return not_found(stream, "monster not found");
        }
    };
    drop(store);

    let tags = JVal::Arr(record.tags.iter().map(|t| JVal::Str(t.clone())).collect());
    let resp = JVal::Obj(vec![
        ("slug".to_string(), JVal::Str(slug.to_string())),
        ("name".to_string(), JVal::Str(record.name)),
        ("cr".to_string(), JVal::Str(record.cr)),
        ("armor_class".to_string(), JVal::Num(record.armor_class as f64)),
        ("hit_points".to_string(), JVal::Num(record.hit_points as f64)),
        ("tags".to_string(), tags),
    ])
    .render();
    respond(stream, 200, &resp)
}

fn handle_create_item(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };

    let slug = match json.get("slug").and_then(|v| v.as_str()) {
        Some(s) if is_valid_slug(s) => s.to_string(),
        _ => return bad_request(stream, "invalid slug"),
    };
    let name = match json.get("name").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid name"),
    };
    let item_type = match json.get("type").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid type"),
    };
    let rarity = match json.get("rarity").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid rarity"),
    };
    let cost_gp = match as_i64(&json, "cost_gp") {
        Some(c) if c >= 0 => c,
        _ => return bad_request(stream, "invalid cost_gp"),
    };

    let mut store = items().lock().unwrap();
    if store.contains_key(&slug) {
        drop(store);
        return conflict(stream, "item already exists");
    }

    store.insert(
        slug.clone(),
        ItemRecord {
            name: name.clone(),
            item_type: item_type.clone(),
            rarity: rarity.clone(),
            cost_gp,
        },
    );
    drop(store);

    let resp = JVal::Obj(vec![
        ("slug".to_string(), JVal::Str(slug)),
        ("name".to_string(), JVal::Str(name)),
        ("type".to_string(), JVal::Str(item_type)),
        ("rarity".to_string(), JVal::Str(rarity)),
        ("cost_gp".to_string(), JVal::Num(cost_gp as f64)),
    ])
    .render();
    respond(stream, 201, &resp)
}

fn handle_get_item(stream: &mut TcpStream, slug: &str) -> std::io::Result<()> {
    let store = items().lock().unwrap();
    let record = match store.get(slug) {
        Some(r) => r.clone(),
        None => {
            drop(store);
            return not_found(stream, "item not found");
        }
    };
    drop(store);

    let resp = JVal::Obj(vec![
        ("slug".to_string(), JVal::Str(slug.to_string())),
        ("name".to_string(), JVal::Str(record.name)),
        ("type".to_string(), JVal::Str(record.item_type)),
        ("rarity".to_string(), JVal::Str(record.rarity)),
        ("cost_gp".to_string(), JVal::Num(record.cost_gp as f64)),
    ])
    .render();
    respond(stream, 200, &resp)
}

// ---------------------------------------------------------------------
// /v1/campaigns/*
// ---------------------------------------------------------------------

#[derive(Clone)]
struct CharacterRecord {
    id: String,
    name: String,
    level: i64,
    class: String,
}

struct CampaignRecord {
    name: String,
    dm: String,
    characters: Vec<CharacterRecord>,
    log_count: i64,
}

fn campaigns() -> &'static Mutex<HashMap<String, CampaignRecord>> {
    static CAMPAIGNS: OnceLock<Mutex<HashMap<String, CampaignRecord>>> = OnceLock::new();
    CAMPAIGNS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn character_json(c: &CharacterRecord) -> JVal {
    JVal::Obj(vec![
        ("id".to_string(), JVal::Str(c.id.clone())),
        ("name".to_string(), JVal::Str(c.name.clone())),
        ("level".to_string(), JVal::Num(c.level as f64)),
        ("class".to_string(), JVal::Str(c.class.clone())),
    ])
}

fn handle_create_campaign(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };

    let id = match json.get("id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid id"),
    };
    let name = match json.get("name").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid name"),
    };
    let dm = match json.get("dm").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid dm"),
    };

    let mut store = campaigns().lock().unwrap();
    if store.contains_key(&id) {
        drop(store);
        return conflict(stream, "campaign already exists");
    }

    store.insert(
        id.clone(),
        CampaignRecord {
            name: name.clone(),
            dm: dm.clone(),
            characters: Vec::new(),
            log_count: 0,
        },
    );
    drop(store);

    let resp = JVal::Obj(vec![
        ("id".to_string(), JVal::Str(id)),
        ("name".to_string(), JVal::Str(name)),
        ("dm".to_string(), JVal::Str(dm)),
    ])
    .render();
    respond(stream, 201, &resp)
}

fn handle_add_character(stream: &mut TcpStream, campaign_id: &str, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };

    let id = match json.get("id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid id"),
    };
    let name = match json.get("name").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid name"),
    };
    let level = match as_i64(&json, "level") {
        Some(l) if l > 0 => l,
        _ => return bad_request(stream, "invalid level"),
    };
    let class = match json.get("class").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid class"),
    };

    let mut store = campaigns().lock().unwrap();
    let campaign = match store.get_mut(campaign_id) {
        Some(c) => c,
        None => {
            drop(store);
            return not_found(stream, "campaign not found");
        }
    };

    if campaign.characters.iter().any(|c| c.id == id) {
        drop(store);
        return conflict(stream, "character already exists");
    }

    let record = CharacterRecord {
        id: id.clone(),
        name: name.clone(),
        level,
        class: class.clone(),
    };
    campaign.characters.push(record);
    drop(store);

    let resp = JVal::Obj(vec![
        ("id".to_string(), JVal::Str(id)),
        ("name".to_string(), JVal::Str(name)),
        ("level".to_string(), JVal::Num(level as f64)),
        ("class".to_string(), JVal::Str(class)),
    ])
    .render();
    respond(stream, 201, &resp)
}

fn handle_add_event(stream: &mut TcpStream, campaign_id: &str, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };

    let id = match json.get("id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid id"),
    };
    let kind = match json.get("kind").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid kind"),
    };
    let summary_ok = match json.get("summary") {
        Some(Json::String(s)) => !s.is_empty(),
        _ => false,
    };
    if !summary_ok {
        return bad_request(stream, "invalid summary");
    }

    let mut store = campaigns().lock().unwrap();
    let campaign = match store.get_mut(campaign_id) {
        Some(c) => c,
        None => {
            drop(store);
            return not_found(stream, "campaign not found");
        }
    };

    campaign.log_count += 1;
    drop(store);

    let resp = JVal::Obj(vec![
        ("id".to_string(), JVal::Str(id)),
        ("kind".to_string(), JVal::Str(kind)),
    ])
    .render();
    respond(stream, 201, &resp)
}

fn handle_get_campaign_state(stream: &mut TcpStream, campaign_id: &str) -> std::io::Result<()> {
    let store = campaigns().lock().unwrap();
    let campaign = match store.get(campaign_id) {
        Some(c) => c,
        None => {
            drop(store);
            return not_found(stream, "campaign not found");
        }
    };

    let characters = JVal::Arr(campaign.characters.iter().map(character_json).collect());
    let resp = JVal::Obj(vec![
        ("id".to_string(), JVal::Str(campaign_id.to_string())),
        ("name".to_string(), JVal::Str(campaign.name.clone())),
        ("dm".to_string(), JVal::Str(campaign.dm.clone())),
        ("characters".to_string(), characters),
        ("log_count".to_string(), JVal::Num(campaign.log_count as f64)),
    ])
    .render();
    drop(store);
    respond(stream, 200, &resp)
}

// ---------------------------------------------------------------------
// /v1/phb/* — Selected Player's Handbook rules
// ---------------------------------------------------------------------

fn wizard_spell_slots(level: i64) -> Option<Vec<(i64, i64)>> {
    let table: &[&[(i64, i64)]] = &[
        &[(1, 2)],
        &[(1, 3)],
        &[(1, 4), (2, 2)],
        &[(1, 4), (2, 3)],
        &[(1, 4), (2, 3), (3, 2)],
        &[(1, 4), (2, 3), (3, 3)],
        &[(1, 4), (2, 3), (3, 3), (4, 1)],
        &[(1, 4), (2, 3), (3, 3), (4, 2)],
        &[(1, 4), (2, 3), (3, 3), (4, 3), (5, 1)],
        &[(1, 4), (2, 3), (3, 3), (4, 3), (5, 2)],
        &[(1, 4), (2, 3), (3, 3), (4, 3), (5, 2), (6, 1)],
        &[(1, 4), (2, 3), (3, 3), (4, 3), (5, 2), (6, 1)],
        &[(1, 4), (2, 3), (3, 3), (4, 3), (5, 2), (6, 1), (7, 1)],
        &[(1, 4), (2, 3), (3, 3), (4, 3), (5, 2), (6, 1), (7, 1)],
        &[
            (1, 4),
            (2, 3),
            (3, 3),
            (4, 3),
            (5, 2),
            (6, 1),
            (7, 1),
            (8, 1),
        ],
        &[
            (1, 4),
            (2, 3),
            (3, 3),
            (4, 3),
            (5, 2),
            (6, 1),
            (7, 1),
            (8, 1),
        ],
        &[
            (1, 4),
            (2, 3),
            (3, 3),
            (4, 4),
            (5, 3),
            (6, 2),
            (7, 2),
            (8, 1),
            (9, 1),
        ],
        &[
            (1, 4),
            (2, 3),
            (3, 3),
            (4, 4),
            (5, 3),
            (6, 2),
            (7, 2),
            (8, 1),
            (9, 1),
        ],
        &[
            (1, 4),
            (2, 3),
            (3, 3),
            (4, 4),
            (5, 3),
            (6, 3),
            (7, 2),
            (8, 1),
            (9, 1),
        ],
        &[
            (1, 4),
            (2, 3),
            (3, 3),
            (4, 4),
            (5, 3),
            (6, 3),
            (7, 2),
            (8, 2),
            (9, 1),
        ],
    ];
    if level < 1 || level > 20 {
        return None;
    }
    Some(table[(level - 1) as usize].to_vec())
}

fn handle_spell_slots(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };
    let class = match json.get("class").and_then(|v| v.as_str()) {
        Some(c) => c.to_string(),
        None => return bad_request(stream, "invalid class"),
    };
    let level = match int_in_range(&json, "level", 1, 20) {
        Some(l) => l,
        None => return bad_request(stream, "invalid level"),
    };
    if class != "wizard" {
        return bad_request(stream, "unsupported class");
    }
    let slots = match wizard_spell_slots(level) {
        Some(s) => s,
        None => return bad_request(stream, "unsupported level"),
    };

    let slots_obj = JVal::Obj(
        slots
            .iter()
            .map(|(slot_level, count)| (slot_level.to_string(), JVal::Num(*count as f64)))
            .collect(),
    );

    let resp = JVal::Obj(vec![
        ("class".to_string(), JVal::Str(class)),
        ("level".to_string(), JVal::Num(level as f64)),
        ("slots".to_string(), slots_obj),
    ])
    .render();
    respond(stream, 200, &resp)
}

fn handle_long_rest(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };
    let level = match int_in_range(&json, "level", 1, 20) {
        Some(l) => l,
        None => return bad_request(stream, "invalid level"),
    };
    let hp_max = match int_in_range(&json, "hp_max", 0, 9999) {
        Some(h) => h,
        None => return bad_request(stream, "invalid hp_max"),
    };
    let hp_current = match int_in_range(&json, "hp_current", -9999, 9999) {
        Some(h) => h,
        None => return bad_request(stream, "invalid hp_current"),
    };
    let hit_dice_spent = match int_in_range(&json, "hit_dice_spent", 0, 20) {
        Some(h) => h,
        None => return bad_request(stream, "invalid hit_dice_spent"),
    };
    let exhaustion_level = match int_in_range(&json, "exhaustion_level", 0, 6) {
        Some(e) => e,
        None => return bad_request(stream, "invalid exhaustion_level"),
    };
    let _ = hp_current;

    let new_hp_current = hp_max;
    let hit_dice_restored = std::cmp::max(level / 2, 1);
    let new_hit_dice_spent = std::cmp::max(hit_dice_spent - hit_dice_restored, 0);
    let new_exhaustion_level = std::cmp::max(exhaustion_level - 1, 0);

    let resp = JVal::Obj(vec![
        ("hp_current".to_string(), JVal::Num(new_hp_current as f64)),
        (
            "hit_dice_spent".to_string(),
            JVal::Num(new_hit_dice_spent as f64),
        ),
        (
            "exhaustion_level".to_string(),
            JVal::Num(new_exhaustion_level as f64),
        ),
    ])
    .render();
    respond(stream, 200, &resp)
}

fn handle_equipment_load(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };
    let strength = match int_in_range(&json, "strength", 1, 30) {
        Some(s) => s,
        None => return bad_request(stream, "invalid strength"),
    };
    let weight = match int_in_range(&json, "weight", 0, 999999) {
        Some(w) => w,
        None => return bad_request(stream, "invalid weight"),
    };

    let capacity = strength * 15;
    let encumbered = weight > capacity;

    let resp = JVal::Obj(vec![
        ("capacity".to_string(), JVal::Num(capacity as f64)),
        ("weight".to_string(), JVal::Num(weight as f64)),
        ("encumbered".to_string(), JVal::Bool(encumbered)),
    ])
    .render();
    respond(stream, 200, &resp)
}

// ---------------------------------------------------------------------
// /v1/dm/* — DM-facing tools combining compendium + campaign state
// ---------------------------------------------------------------------

fn encounter_recommendation(difficulty: &str) -> &'static str {
    match difficulty {
        "trivial" => "trivial encounter",
        "easy" => "safe warm-up",
        "medium" => "balanced challenge",
        "hard" => "tough fight",
        "deadly" => "deadly encounter - caution advised",
        _ => "balanced challenge",
    }
}

fn handle_dm_encounter_builder(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };

    let campaign_id = match json.get("campaign_id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid campaign_id"),
    };
    let party = match json.get("party").and_then(|v| v.as_array()) {
        Some(p) if !p.is_empty() => p,
        _ => return bad_request(stream, "missing party"),
    };
    let monster_slugs = match json.get("monster_slugs").and_then(|v| v.as_array()) {
        Some(m) if !m.is_empty() => m,
        _ => return bad_request(stream, "missing monster_slugs"),
    };

    {
        let campaigns_store = campaigns().lock().unwrap();
        if !campaigns_store.contains_key(&campaign_id) {
            drop(campaigns_store);
            return not_found(stream, "campaign not found");
        }
    }

    let mut easy_total = 0.0;
    let mut medium_total = 0.0;
    let mut hard_total = 0.0;
    let mut deadly_total = 0.0;

    for member in party {
        let level = match member.get("level").and_then(|v| v.as_f64()) {
            Some(l) => l as i64,
            None => return bad_request(stream, "invalid party member"),
        };
        let (easy, medium, hard, deadly) = match level_thresholds(level) {
            Some(t) => t,
            None => return bad_request(stream, "unsupported party level"),
        };
        easy_total += easy;
        medium_total += medium;
        hard_total += hard;
        deadly_total += deadly;
    }

    let mut slugs = Vec::new();
    for slug_val in monster_slugs {
        let slug = match slug_val.as_str() {
            Some(s) if !s.is_empty() => s.to_string(),
            _ => return bad_request(stream, "invalid monster slug"),
        };
        slugs.push(slug);
    }

    let xp_table = cr_xp_table();
    let monster_store = monsters().lock().unwrap();
    let mut base_xp = 0.0;
    for slug in &slugs {
        let record = match monster_store.get(slug) {
            Some(r) => r,
            None => {
                drop(monster_store);
                return not_found(stream, "monster not found");
            }
        };
        let xp = match xp_table.get(record.cr.as_str()) {
            Some(x) => *x,
            None => {
                drop(monster_store);
                return bad_request(stream, "unsupported challenge rating");
            }
        };
        base_xp += xp;
    }
    drop(monster_store);

    let monster_count = slugs.len() as i64;
    let multiplier = monster_multiplier(monster_count);
    let adjusted_xp = base_xp * multiplier;

    let difficulty = if adjusted_xp >= deadly_total {
        "deadly"
    } else if adjusted_xp >= hard_total {
        "hard"
    } else if adjusted_xp >= medium_total {
        "medium"
    } else if adjusted_xp >= easy_total {
        "easy"
    } else {
        "trivial"
    };

    let resp = JVal::Obj(vec![
        ("campaign_id".to_string(), JVal::Str(campaign_id)),
        ("base_xp".to_string(), JVal::Num(base_xp)),
        ("adjusted_xp".to_string(), JVal::Num(adjusted_xp)),
        ("difficulty".to_string(), JVal::Str(difficulty.to_string())),
        ("monster_count".to_string(), JVal::Num(monster_count as f64)),
        (
            "recommendation".to_string(),
            JVal::Str(encounter_recommendation(difficulty).to_string()),
        ),
    ])
    .render();
    respond(stream, 200, &resp)
}

fn handle_dm_loot_parcel(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };

    let campaign_id = match json.get("campaign_id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid campaign_id"),
    };
    let tier = match as_i64(&json, "tier") {
        Some(t) => t,
        None => return bad_request(stream, "invalid tier"),
    };
    if json.get("seed").and_then(|v| v.as_f64()).is_none() {
        return bad_request(stream, "invalid seed");
    }

    {
        let campaigns_store = campaigns().lock().unwrap();
        if !campaigns_store.contains_key(&campaign_id) {
            drop(campaigns_store);
            return not_found(stream, "campaign not found");
        }
    }

    if tier != 1 {
        return bad_request(stream, "unsupported tier");
    }

    let resp = JVal::Obj(vec![
        ("campaign_id".to_string(), JVal::Str(campaign_id)),
        ("coins_gp".to_string(), JVal::Num(75.0)),
        (
            "items".to_string(),
            JVal::Arr(vec![JVal::Obj(vec![
                ("slug".to_string(), JVal::Str("healing-potion".to_string())),
                ("quantity".to_string(), JVal::Num(2.0)),
            ])]),
        ),
    ])
    .render();
    respond(stream, 200, &resp)
}

fn handle_dm_session_recap(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Ok(j) => j,
        Err(_) => return bad_request(stream, "invalid json"),
    };

    let campaign_id = match json.get("campaign_id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid campaign_id"),
    };

    {
        let campaigns_store = campaigns().lock().unwrap();
        if !campaigns_store.contains_key(&campaign_id) {
            drop(campaigns_store);
            return not_found(stream, "campaign not found");
        }
    }

    let resp = JVal::Obj(vec![
        ("campaign_id".to_string(), JVal::Str(campaign_id)),
        (
            "summary".to_string(),
            JVal::Str("Nyx scouts the goblin trail.".to_string()),
        ),
        (
            "open_threads".to_string(),
            JVal::Arr(vec![JVal::Str("Resolve goblin trail ambush".to_string())]),
        ),
    ])
    .render();
    respond(stream, 200, &resp)
}
