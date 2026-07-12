use std::collections::HashMap;
use std::env;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::{LazyLock, Mutex};

#[derive(Clone)]
struct Condition {
    condition: String,
    remaining_rounds: i64,
}

#[derive(Clone)]
struct Combatant {
    name: String,
    score: i64,
    conditions: Vec<Condition>,
}

struct Session {
    id: String,
    round: i64,
    turn_index: usize,
    order: Vec<Combatant>,
}

static SESSIONS: LazyLock<Mutex<HashMap<String, Session>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

fn main() -> std::io::Result<()> {
    let port = env::var("PORT").unwrap_or_else(|_| "8080".to_string());
    let listener = TcpListener::bind(format!("127.0.0.1:{port}"))?;
    for stream in listener.incoming() {
        if let Ok(mut stream) = stream {
            let _ = handle(&mut stream);
        }
    }
    Ok(())
}

fn handle(stream: &mut TcpStream) -> std::io::Result<()> {
    let mut buf = [0u8; 8192];
    let n = stream.read(&mut buf)?;
    let req = String::from_utf8_lossy(&buf[..n]);
    let (head, mut body) = match req.split_once("\r\n\r\n") {
        Some(split) => split,
        None => (&*req, ""),
    };

    let mut lines = head.lines();
    let first = lines.next().unwrap_or("");
    let mut parts = first.split_whitespace();
    let method = parts.next().unwrap_or("");
    let path = parts.next().unwrap_or("");

    let mut content_length = body.len();
    for line in lines {
        if let Some(val) = line.strip_prefix("Content-Length: ") {
            if let Ok(len) = val.parse::<usize>() {
                content_length = len;
            }
        }
    }
    body = &body[..content_length.min(body.len())];

    match (method, path) {
        ("GET", "/health") => respond(stream, 200, r#"{"ok":true}"#),
        ("POST", "/v1/dice/stats") => match dice_stats(body) {
            Ok(b) => respond(stream, 200, &b),
            Err(_) => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", "/v1/checks/ability") => match ability_check(body) {
            Ok(b) => respond(stream, 200, &b),
            Err(_) => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", "/v1/encounters/adjusted-xp") => match adjusted_xp(body) {
            Ok(b) => respond(stream, 200, &b),
            Err(_) => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", "/v1/initiative/order") => match initiative_order(body) {
            Ok(b) => respond(stream, 200, &b),
            Err(_) => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", "/v1/characters/ability-modifier") => match ability_modifier(body) {
            Ok(b) => respond(stream, 200, &b),
            Err(_) => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", "/v1/characters/proficiency") => match proficiency_bonus(body) {
            Ok(b) => respond(stream, 200, &b),
            Err(_) => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", "/v1/characters/derived-stats") => match derived_stats(body) {
            Ok(b) => respond(stream, 200, &b),
            Err(_) => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", "/v1/combat/sessions") => match create_session(body) {
            Ok(b) => respond(stream, 200, &b),
            Err(_) => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", p) => {
            if let Some(id) = extract_session_id(p, "/conditions") {
                match add_condition(id, body) {
                    Ok(b) => respond(stream, 200, &b),
                    Err(ref e) if e == "session not found" => {
                        respond(stream, 404, r#"{"error":"not found"}"#)
                    }
                    Err(_) => respond(stream, 400, r#"{"error":"bad request"}"#),
                }
            } else if let Some(id) = extract_session_id(p, "/advance") {
                match advance_turn(id) {
                    Ok(b) => respond(stream, 200, &b),
                    Err(ref e) if e == "session not found" => {
                        respond(stream, 404, r#"{"error":"not found"}"#)
                    }
                    Err(_) => respond(stream, 400, r#"{"error":"bad request"}"#),
                }
            } else {
                respond(stream, 404, r#"{"error":"not found"}"#)
            }
        }
        _ => respond(stream, 404, r#"{"error":"not found"}"#),
    }
}

fn respond(stream: &mut TcpStream, status: u16, body: &str) -> std::io::Result<()> {
    let label = match status {
        200 => "OK",
        400 => "Bad Request",
        404 => "Not Found",
        _ => "Error",
    };
    let response = format!(
        "HTTP/1.1 {status} {label}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len(),
    );
    stream.write_all(response.as_bytes())
}

fn dice_stats(body: &str) -> Result<String, String> {
    let json = parse_json(body)?;
    let expression = json.get_str("expression")?;
    let (count, sides, modifier) = parse_dice_expression(expression)?;
    let min = count + modifier;
    let max = count * sides + modifier;
    let average = (min as f64 + max as f64) / 2.0;
    let resp = Json::Object(vec![
        ("dice_count".to_string(), Json::Number(count as f64)),
        ("sides".to_string(), Json::Number(sides as f64)),
        ("modifier".to_string(), Json::Number(modifier as f64)),
        ("min".to_string(), Json::Number(min as f64)),
        ("max".to_string(), Json::Number(max as f64)),
        ("average".to_string(), Json::Number(average)),
    ]);
    Ok(resp.to_string())
}

fn parse_dice_expression(expr: &str) -> Result<(i64, i64, i64), String> {
    let expr = expr.trim();
    let d_pos = expr.find('d').ok_or("missing d")?;
    let (count_str, rest) = expr.split_at(d_pos);
    let rest = &rest[1..];
    let count = count_str.parse::<i64>().map_err(|_| "invalid count")?;
    if count <= 0 {
        return Err("count must be positive".to_string());
    }

    let (sides_str, modifier_str, sign) = if let Some(pos) = rest.find('+') {
        let (s, m) = rest.split_at(pos);
        (s, &m[1..], 1)
    } else if let Some(pos) = rest.find('-') {
        let (s, m) = rest.split_at(pos);
        (s, &m[1..], -1)
    } else {
        (rest, "", 0)
    };

    let sides = sides_str.parse::<i64>().map_err(|_| "invalid sides")?;
    if sides <= 0 {
        return Err("sides must be positive".to_string());
    }

    let modifier = if modifier_str.is_empty() {
        0
    } else {
        let m = modifier_str.parse::<i64>().map_err(|_| "invalid modifier")?;
        if sign < 0 { -m } else { m }
    };

    Ok((count, sides, modifier))
}

fn ability_check(body: &str) -> Result<String, String> {
    let json = parse_json(body)?;
    let roll = json.get_i64("roll")?;
    let modifier = json.get_i64("modifier")?;
    let dc = json.get_i64("dc")?;
    let total = roll + modifier;
    let success = total >= dc;
    let margin = total - dc;
    let resp = Json::Object(vec![
        ("total".to_string(), Json::Number(total as f64)),
        ("success".to_string(), Json::Bool(success)),
        ("margin".to_string(), Json::Number(margin as f64)),
    ]);
    Ok(resp.to_string())
}

fn adjusted_xp(body: &str) -> Result<String, String> {
    let json = parse_json(body)?;
    let party = json.get_array("party")?;
    let monsters = json.get_array("monsters")?;

    let mut easy = 0_i64;
    let mut medium = 0_i64;
    let mut hard = 0_i64;
    let mut deadly = 0_i64;
    for member in party {
        let level = member.get_i64("level")?;
        let t = level_thresholds(level)?;
        easy += t.0;
        medium += t.1;
        hard += t.2;
        deadly += t.3;
    }

    let mut base_xp = 0_i64;
    let mut monster_count = 0_i64;
    for m in monsters {
        let cr = m.get_str("cr")?;
        let count = m.get_i64("count")?;
        let xp = cr_xp(cr)?;
        base_xp += xp * count;
        monster_count += count;
    }

    let multiplier = monster_count_multiplier(monster_count);
    let adjusted_xp = base_xp as f64 * multiplier;

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

    let resp = Json::Object(vec![
        ("base_xp".to_string(), Json::Number(base_xp as f64)),
        ("monster_count".to_string(), Json::Number(monster_count as f64)),
        ("multiplier".to_string(), Json::Number(multiplier)),
        ("adjusted_xp".to_string(), Json::Number(adjusted_xp)),
        ("difficulty".to_string(), Json::String(difficulty.to_string())),
        ("thresholds".to_string(), Json::Object(vec![
            ("easy".to_string(), Json::Number(easy as f64)),
            ("medium".to_string(), Json::Number(medium as f64)),
            ("hard".to_string(), Json::Number(hard as f64)),
            ("deadly".to_string(), Json::Number(deadly as f64)),
        ])),
    ]);
    Ok(resp.to_string())
}

fn cr_xp(cr: &str) -> Result<i64, String> {
    match cr {
        "0" => Ok(10),
        "1/8" => Ok(25),
        "1/4" => Ok(50),
        "1/2" => Ok(100),
        "1" => Ok(200),
        "2" => Ok(450),
        "3" => Ok(700),
        "4" => Ok(1100),
        "5" => Ok(1800),
        _ => Err(format!("unsupported cr: {cr}")),
    }
}

fn level_thresholds(level: i64) -> Result<(i64, i64, i64, i64), String> {
    match level {
        3 => Ok((75, 150, 225, 400)),
        _ => Err(format!("unsupported level: {level}")),
    }
}

fn monster_count_multiplier(n: i64) -> f64 {
    match n {
        1 => 1.0,
        2 => 1.5,
        3..=6 => 2.0,
        7..=10 => 2.5,
        11..=14 => 3.0,
        _ => 4.0,
    }
}

fn ability_modifier(body: &str) -> Result<String, String> {
    let json = parse_json(body)?;
    let score = json.get_i64("score")?;
    if score < 1 || score > 30 {
        return Err("score out of range".to_string());
    }
    let m = modifier(score);
    let resp = Json::Object(vec![
        ("score".to_string(), Json::Number(score as f64)),
        ("modifier".to_string(), Json::Number(m as f64)),
    ]);
    Ok(resp.to_string())
}

fn proficiency_bonus(body: &str) -> Result<String, String> {
    let json = parse_json(body)?;
    let level = json.get_i64("level")?;
    if level < 1 || level > 20 {
        return Err("level out of range".to_string());
    }
    let bonus = proficiency_from_level(level);
    let resp = Json::Object(vec![
        ("level".to_string(), Json::Number(level as f64)),
        ("proficiency_bonus".to_string(), Json::Number(bonus as f64)),
    ]);
    Ok(resp.to_string())
}

fn derived_stats(body: &str) -> Result<String, String> {
    let json = parse_json(body)?;
    let level = json.get_i64("level")?;
    if level < 1 || level > 20 {
        return Err("level out of range".to_string());
    }
    let abilities = json.get_object("abilities")?;
    let armor = json.get_object("armor")?;

    let str = get_ability_score(abilities, "str")?;
    let dex = get_ability_score(abilities, "dex")?;
    let con = get_ability_score(abilities, "con")?;
    let int = get_ability_score(abilities, "int")?;
    let wis = get_ability_score(abilities, "wis")?;
    let cha = get_ability_score(abilities, "cha")?;

    let str_mod = modifier(str);
    let dex_mod = modifier(dex);
    let con_mod = modifier(con);
    let int_mod = modifier(int);
    let wis_mod = modifier(wis);
    let cha_mod = modifier(cha);

    let base = get_field_i64(armor, "base")?;
    let shield = get_field_bool(armor, "shield")?;
    let dex_cap = get_field_i64(armor, "dex_cap")?;

    let shield_bonus = if shield { 2 } else { 0 };
    let armor_class = base + std::cmp::min(dex_mod, dex_cap) + shield_bonus;
    let hp_max = level * (6 + con_mod);
    let prof = proficiency_from_level(level);

    let modifiers = Json::Object(vec![
        ("str".to_string(), Json::Number(str_mod as f64)),
        ("dex".to_string(), Json::Number(dex_mod as f64)),
        ("con".to_string(), Json::Number(con_mod as f64)),
        ("int".to_string(), Json::Number(int_mod as f64)),
        ("wis".to_string(), Json::Number(wis_mod as f64)),
        ("cha".to_string(), Json::Number(cha_mod as f64)),
    ]);

    let resp = Json::Object(vec![
        ("level".to_string(), Json::Number(level as f64)),
        ("proficiency_bonus".to_string(), Json::Number(prof as f64)),
        ("hp_max".to_string(), Json::Number(hp_max as f64)),
        ("armor_class".to_string(), Json::Number(armor_class as f64)),
        ("modifiers".to_string(), modifiers),
    ]);
    Ok(resp.to_string())
}

fn modifier(score: i64) -> i64 {
    let diff = score - 10;
    if diff >= 0 {
        diff / 2
    } else {
        (diff - 1) / 2
    }
}

fn proficiency_from_level(level: i64) -> i64 {
    2 + (level - 1) / 4
}

fn get_ability_score(obj: &[(String, Json)], key: &str) -> Result<i64, String> {
    let score = get_field_i64(obj, key)?;
    if score < 1 || score > 30 {
        return Err(format!("{key} out of range"));
    }
    Ok(score)
}

fn get_field_i64(obj: &[(String, Json)], key: &str) -> Result<i64, String> {
    for (k, v) in obj {
        if k == key {
            match v {
                Json::Number(n) => return Ok(*n as i64),
                _ => return Err(format!("field {key} is not a number")),
            }
        }
    }
    Err(format!("missing field {key}"))
}

fn get_field_bool(obj: &[(String, Json)], key: &str) -> Result<bool, String> {
    for (k, v) in obj {
        if k == key {
            match v {
                Json::Bool(b) => return Ok(*b),
                _ => return Err(format!("field {key} is not a bool")),
            }
        }
    }
    Err(format!("missing field {key}"))
}

fn initiative_order(body: &str) -> Result<String, String> {
    let json = parse_json(body)?;
    let combatants = json.get_array("combatants")?;
    let mut scored = Vec::new();
    for c in combatants {
        let name = c.get_str("name")?.to_string();
        let dex = c.get_i64("dex")?;
        let roll = c.get_i64("roll")?;
        scored.push((name, roll + dex, dex));
    }
    scored.sort_by(|a, b| {
        b.1.cmp(&a.1)
            .then(b.2.cmp(&a.2))
            .then(a.0.cmp(&b.0))
    });
    let order = scored
        .into_iter()
        .map(|(name, score, _)| {
            Json::Object(vec![
                ("name".to_string(), Json::String(name)),
                ("score".to_string(), Json::Number(score as f64)),
            ])
        })
        .collect();
    let resp = Json::Object(vec![("order".to_string(), Json::Array(order))]);
    Ok(resp.to_string())
}

fn extract_session_id<'a>(path: &'a str, suffix: &str) -> Option<&'a str> {
    path.strip_prefix("/v1/combat/sessions/")
        .and_then(|rest| rest.strip_suffix(suffix))
}

fn session_summary(session: &Session) -> Json {
    let active = &session.order[session.turn_index];
    let order = session
        .order
        .iter()
        .map(|c| {
            Json::Object(vec![
                ("name".to_string(), Json::String(c.name.clone())),
                ("score".to_string(), Json::Number(c.score as f64)),
            ])
        })
        .collect();
    Json::Object(vec![
        ("id".to_string(), Json::String(session.id.clone())),
        ("round".to_string(), Json::Number(session.round as f64)),
        ("turn_index".to_string(), Json::Number(session.turn_index as f64)),
        (
            "active".to_string(),
            Json::Object(vec![
                ("name".to_string(), Json::String(active.name.clone())),
                ("score".to_string(), Json::Number(active.score as f64)),
            ]),
        ),
        ("order".to_string(), Json::Array(order)),
    ])
}

fn create_session(body: &str) -> Result<String, String> {
    let json = parse_json(body)?;
    let id = json.get_str("id")?.to_string();
    let combatants = json.get_array("combatants")?;
    let mut scored = Vec::new();
    for c in combatants {
        let name = c.get_str("name")?.to_string();
        let dex = c.get_i64("dex")?;
        let roll = c.get_i64("roll")?;
        scored.push((name, roll + dex, dex));
    }
    scored.sort_by(|a, b| {
        b.1.cmp(&a.1)
            .then(b.2.cmp(&a.2))
            .then(a.0.cmp(&b.0))
    });
    if scored.is_empty() {
        return Err("combatants required".to_string());
    }
    let order = scored
        .into_iter()
        .map(|(name, score, _)| Combatant {
            name,
            score,
            conditions: Vec::new(),
        })
        .collect();
    let mut sessions = SESSIONS.lock().map_err(|_| "lock poisoned")?;
    if sessions.contains_key(&id) {
        return Err("session id already exists".to_string());
    }
    sessions.insert(
        id.clone(),
        Session {
            id: id.clone(),
            round: 1,
            turn_index: 0,
            order,
        },
    );
    let session = sessions.get(&id).unwrap();
    Ok(session_summary(session).to_string())
}

fn add_condition(id: &str, body: &str) -> Result<String, String> {
    let json = parse_json(body)?;
    let target = json.get_str("target")?;
    let condition = json.get_str("condition")?.to_string();
    let duration = json.get_i64("duration_rounds")?;
    if duration <= 0 {
        return Err("duration_rounds must be positive".to_string());
    }
    let mut sessions = SESSIONS.lock().map_err(|_| "lock poisoned")?;
    let session = sessions.get_mut(id).ok_or("session not found")?;
    let combatant = session
        .order
        .iter_mut()
        .find(|c| c.name == target)
        .ok_or("target not found")?;
    combatant.conditions.push(Condition {
        condition,
        remaining_rounds: duration,
    });
    let conditions_json = combatant
        .conditions
        .iter()
        .map(|c| {
            Json::Object(vec![
                ("condition".to_string(), Json::String(c.condition.clone())),
                (
                    "remaining_rounds".to_string(),
                    Json::Number(c.remaining_rounds as f64),
                ),
            ])
        })
        .collect();
    let resp = Json::Object(vec![
        ("target".to_string(), Json::String(target.to_string())),
        ("conditions".to_string(), Json::Array(conditions_json)),
    ]);
    Ok(resp.to_string())
}

fn advance_response(session: &Session) -> String {
    let active = &session.order[session.turn_index];
    let conditions: Vec<(String, Json)> = session
        .order
        .iter()
        .filter(|c| !c.conditions.is_empty())
        .map(|c| {
            let arr = c
                .conditions
                .iter()
                .map(|cond| {
                    Json::Object(vec![
                        ("condition".to_string(), Json::String(cond.condition.clone())),
                        (
                            "remaining_rounds".to_string(),
                            Json::Number(cond.remaining_rounds as f64),
                        ),
                    ])
                })
                .collect();
            (c.name.clone(), Json::Array(arr))
        })
        .collect();
    Json::Object(vec![
        ("id".to_string(), Json::String(session.id.clone())),
        ("round".to_string(), Json::Number(session.round as f64)),
        ("turn_index".to_string(), Json::Number(session.turn_index as f64)),
        (
            "active".to_string(),
            Json::Object(vec![
                ("name".to_string(), Json::String(active.name.clone())),
                ("score".to_string(), Json::Number(active.score as f64)),
            ]),
        ),
        ("conditions".to_string(), Json::Object(conditions)),
    ])
    .to_string()
}

fn advance_turn(id: &str) -> Result<String, String> {
    let mut sessions = SESSIONS.lock().map_err(|_| "lock poisoned")?;
    let session = sessions.get_mut(id).ok_or("session not found")?;
    if session.order.is_empty() {
        return Err("no combatants".to_string());
    }
    if session.turn_index + 1 >= session.order.len() {
        session.turn_index = 0;
        session.round += 1;
    } else {
        session.turn_index += 1;
    }
    let idx = session.turn_index;
    session.order[idx].conditions.retain_mut(|c| {
        c.remaining_rounds -= 1;
        c.remaining_rounds > 0
    });
    Ok(advance_response(session))
}

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
    fn get_str(&self, key: &str) -> Result<&str, String> {
        match self {
            Json::Object(pairs) => {
                for (k, v) in pairs {
                    if k == key {
                        match v {
                            Json::String(s) => return Ok(s),
                            _ => return Err(format!("field {key} is not a string")),
                        }
                    }
                }
                Err(format!("missing field {key}"))
            }
            _ => Err("not an object".to_string()),
        }
    }

    fn get_i64(&self, key: &str) -> Result<i64, String> {
        match self {
            Json::Object(pairs) => {
                for (k, v) in pairs {
                    if k == key {
                        match v {
                            Json::Number(n) => return Ok(*n as i64),
                            _ => return Err(format!("field {key} is not a number")),
                        }
                    }
                }
                Err(format!("missing field {key}"))
            }
            _ => Err("not an object".to_string()),
        }
    }

    fn get_array(&self, key: &str) -> Result<&Vec<Json>, String> {
        match self {
            Json::Object(pairs) => {
                for (k, v) in pairs {
                    if k == key {
                        match v {
                            Json::Array(a) => return Ok(a),
                            _ => return Err(format!("field {key} is not an array")),
                        }
                    }
                }
                Err(format!("missing field {key}"))
            }
            _ => Err("not an object".to_string()),
        }
    }

    fn get_object(&self, key: &str) -> Result<&Vec<(String, Json)>, String> {
        match self {
            Json::Object(pairs) => {
                for (k, v) in pairs {
                    if k == key {
                        match v {
                            Json::Object(o) => return Ok(o),
                            _ => return Err(format!("field {key} is not an object")),
                        }
                    }
                }
                Err(format!("missing field {key}"))
            }
            _ => Err("not an object".to_string()),
        }
    }
}

impl std::fmt::Display for Json {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Json::Null => write!(f, "null"),
            Json::Bool(b) => write!(f, "{}", if *b { "true" } else { "false" }),
            Json::Number(n) => {
                if n.is_nan() || n.is_infinite() {
                    write!(f, "null")
                } else if n.fract() == 0.0 && *n >= i64::MIN as f64 && *n <= i64::MAX as f64 {
                    write!(f, "{}", *n as i64)
                } else {
                    write!(f, "{n}")
                }
            }
            Json::String(s) => write!(f, "\"{}\"", json_escape(s)),
            Json::Array(arr) => {
                write!(f, "[")?;
                for (i, v) in arr.iter().enumerate() {
                    if i > 0 {
                        write!(f, ",")?;
                    }
                    write!(f, "{v}")?;
                }
                write!(f, "]")
            }
            Json::Object(pairs) => {
                write!(f, "{{")?;
                for (i, (k, v)) in pairs.iter().enumerate() {
                    if i > 0 {
                        write!(f, ",")?;
                    }
                    write!(f, "\"{}\":{v}", json_escape(k))?;
                }
                write!(f, "}}")
            }
        }
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
            '\u{0008}' => out.push_str("\\b"),
            '\u{000C}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}

fn parse_json(input: &str) -> Result<Json, String> {
    let mut s = input;
    let value = parse_value(&mut s)?;
    skip_ws(&mut s);
    if !s.is_empty() {
        return Err(format!("trailing data: {s}"));
    }
    Ok(value)
}

fn parse_value(s: &mut &str) -> Result<Json, String> {
    skip_ws(s);
    match s.chars().next() {
        None => Err("empty value".to_string()),
        Some('"') => parse_string(s),
        Some('{') => parse_object(s),
        Some('[') => parse_array(s),
        Some('t') => parse_literal(s, "true", Json::Bool(true)),
        Some('f') => parse_literal(s, "false", Json::Bool(false)),
        Some('n') => parse_literal(s, "null", Json::Null),
        Some(c) if c == '-' || c.is_ascii_digit() => parse_number(s),
        Some(c) => Err(format!("unexpected character: {c}")),
    }
}

fn parse_literal(s: &mut &str, lit: &str, val: Json) -> Result<Json, String> {
    if s.starts_with(lit) {
        *s = &s[lit.len()..];
        Ok(val)
    } else {
        Err(format!("expected {lit}"))
    }
}

fn parse_string(s: &mut &str) -> Result<Json, String> {
    let mut chars = s.char_indices().peekable();
    let Some((0, '"')) = chars.next() else {
        return Err("expected string".to_string());
    };
    let mut out = String::new();
    let mut escaped = false;
    while let Some((idx, c)) = chars.next() {
        if escaped {
            match c {
                '"' => out.push('"'),
                '\\' => out.push('\\'),
                '/' => out.push('/'),
                'b' => out.push('\u{0008}'),
                'f' => out.push('\u{000C}'),
                'n' => out.push('\n'),
                'r' => out.push('\r'),
                't' => out.push('\t'),
                'u' => {
                    let start = idx + 1;
                    if start + 4 > s.len() {
                        return Err("invalid unicode escape".to_string());
                    }
                    let hex = &s[start..start + 4];
                    let code = u32::from_str_radix(hex, 16).map_err(|_| "invalid unicode escape")?;
                    let ch = char::from_u32(code).ok_or("invalid unicode codepoint")?;
                    out.push(ch);
                    for _ in 0..4 {
                        chars.next();
                    }
                }
                _ => out.push(c),
            }
            escaped = false;
        } else if c == '\\' {
            escaped = true;
        } else if c == '"' {
            *s = &s[idx + 1..];
            return Ok(Json::String(out));
        } else {
            out.push(c);
        }
    }
    Err("unterminated string".to_string())
}

fn parse_number(s: &mut &str) -> Result<Json, String> {
    let bytes = s.as_bytes();
    let mut end = 0;
    if bytes.first() == Some(&b'-') {
        end += 1;
    }
    while end < bytes.len() && bytes[end].is_ascii_digit() {
        end += 1;
    }
    if end < bytes.len() && bytes[end] == b'.' {
        end += 1;
        while end < bytes.len() && bytes[end].is_ascii_digit() {
            end += 1;
        }
    }
    if end < bytes.len() && (bytes[end] == b'e' || bytes[end] == b'E') {
        end += 1;
        if end < bytes.len() && (bytes[end] == b'+' || bytes[end] == b'-') {
            end += 1;
        }
        while end < bytes.len() && bytes[end].is_ascii_digit() {
            end += 1;
        }
    }
    let num_str = &s[..end];
    let num = num_str.parse::<f64>().map_err(|_| "invalid number")?;
    *s = &s[end..];
    Ok(Json::Number(num))
}

fn parse_array(s: &mut &str) -> Result<Json, String> {
    if !s.starts_with('[') {
        return Err("expected array".to_string());
    }
    *s = &s[1..];
    skip_ws(s);
    let mut items = Vec::new();
    if s.starts_with(']') {
        *s = &s[1..];
        return Ok(Json::Array(items));
    }
    loop {
        let value = parse_value(s)?;
        items.push(value);
        skip_ws(s);
        if s.starts_with(',') {
            *s = &s[1..];
            continue;
        } else if s.starts_with(']') {
            *s = &s[1..];
            return Ok(Json::Array(items));
        } else {
            return Err("expected ',' or ']'".to_string());
        }
    }
}

fn parse_object(s: &mut &str) -> Result<Json, String> {
    if !s.starts_with('{') {
        return Err("expected object".to_string());
    }
    *s = &s[1..];
    skip_ws(s);
    let mut pairs = Vec::new();
    if s.starts_with('}') {
        *s = &s[1..];
        return Ok(Json::Object(pairs));
    }
    loop {
        skip_ws(s);
        let key = match parse_value(s)? {
            Json::String(k) => k,
            _ => return Err("object key must be a string".to_string()),
        };
        skip_ws(s);
        if !s.starts_with(':') {
            return Err("expected ':'".to_string());
        }
        *s = &s[1..];
        let value = parse_value(s)?;
        pairs.push((key, value));
        skip_ws(s);
        if s.starts_with(',') {
            *s = &s[1..];
            continue;
        } else if s.starts_with('}') {
            *s = &s[1..];
            return Ok(Json::Object(pairs));
        } else {
            return Err("expected ',' or '}'".to_string());
        }
    }
}

fn skip_ws(s: &mut &str) {
    let end = s.find(|c: char| !c.is_ascii_whitespace()).unwrap_or(s.len());
    *s = &s[end..];
}
