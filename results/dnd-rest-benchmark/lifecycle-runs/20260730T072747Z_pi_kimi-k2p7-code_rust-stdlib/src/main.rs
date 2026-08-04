use std::collections::HashMap;
use std::env;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::Mutex;

fn main() -> std::io::Result<()> {
    let port = env::var("PORT").unwrap_or_else(|_| "8080".to_string());
    let listener = TcpListener::bind(format!("127.0.0.1:{port}"))?;
    for stream in listener.incoming() {
        if let Ok(stream) = stream {
            let _ = handle(stream);
        }
    }
    Ok(())
}

fn handle(stream: TcpStream) -> std::io::Result<()> {
    let mut reader = BufReader::new(&stream);
    let mut first_line = String::new();
    if reader.read_line(&mut first_line)? == 0 {
        return Ok(());
    }
    let parts: Vec<&str> = first_line.split_whitespace().collect();
    if parts.len() < 2 {
        drop(reader);
        return respond(&stream, 400, &error_body());
    }
    let method = parts[0].to_uppercase();
    let path = parts[1];

    let mut content_length: usize = 0;
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line)? == 0 {
            break;
        }
        if line == "\r\n" || line == "\n" || line.is_empty() {
            break;
        }
        if line.to_ascii_lowercase().starts_with("content-length:") {
            if let Some(v) = line.split(':').nth(1) {
                if let Ok(n) = v.trim().parse::<usize>() {
                    content_length = n;
                }
            }
        }
    }

    let mut body = vec![0u8; content_length];
    if content_length > 0 {
        reader.read_exact(&mut body)?;
    }
    drop(reader);

    let body_str = String::from_utf8_lossy(&body);
    let (status, response) = route(&method, path, &body_str);
    respond(&stream, status, &response)
}

fn route(method: &str, path: &str, body: &str) -> (u16, String) {
    match method {
        "GET" if path == "/health" => (200, r#"{"ok":true}"#.to_string()),
        "POST" => match path {
            "/v1/dice/stats" => dice_stats(body),
            "/v1/checks/ability" => ability_check(body),
            "/v1/encounters/adjusted-xp" => adjusted_xp(body),
            "/v1/initiative/order" => initiative_order(body),
            "/v1/characters/ability-modifier" => ability_modifier(body),
            "/v1/characters/proficiency" => proficiency_bonus(body),
            "/v1/characters/derived-stats" => derived_stats(body),
            "/v1/combat/sessions" => create_combat_session(body),
            p if p.starts_with("/v1/combat/sessions/") => {
                let rest = &p["/v1/combat/sessions/".len()..];
                if let Some((id, suffix)) = rest.split_once('/') {
                    match suffix {
                        "conditions" => add_condition(id, body),
                        "advance" => advance_turn(id),
                        _ => (404, error_body()),
                    }
                } else {
                    (404, error_body())
                }
            }
            _ => (404, error_body()),
        },
        _ => (404, error_body()),
    }
}

// Combat state

struct Condition {
    name: String,
    remaining: i32,
}

struct Combatant {
    name: String,
    score: i32,
    dex: i32,
    conditions: Vec<Condition>,
}

struct CombatSession {
    id: String,
    round: i32,
    turn_index: usize,
    order: Vec<Combatant>,
}

static SESSIONS: std::sync::LazyLock<Mutex<HashMap<String, CombatSession>>> =
    std::sync::LazyLock::new(|| Mutex::new(HashMap::new()));

fn create_combat_session(body: &str) -> (u16, String) {
    let obj = match json_parse(body) {
        Ok(Value::Object(o)) => o,
        _ => return (400, error_body()),
    };
    let id = match get_string(&obj, "id") {
        Some(s) => s,
        None => return (400, error_body()),
    };
    let arr = match get_array(&obj, "combatants") {
        Some(a) => a,
        None => return (400, error_body()),
    };

    let mut combatants: Vec<(String, i32, i32)> = Vec::new();
    for c in arr {
        let co = match c {
            Value::Object(o) => o,
            _ => return (400, error_body()),
        };
        let name = match get_string(&co, "name") {
            Some(s) => s,
            None => return (400, error_body()),
        };
        let dex = match get_i32(&co, "dex") {
            Some(v) => v,
            None => return (400, error_body()),
        };
        let roll = match get_i32(&co, "roll") {
            Some(v) => v,
            None => return (400, error_body()),
        };
        combatants.push((name, dex, roll + dex));
    }
    if combatants.is_empty() {
        return (400, error_body());
    }

    let mut sessions = SESSIONS.lock().unwrap();
    if sessions.contains_key(&id) {
        return (400, error_body());
    }

    let mut order: Vec<Combatant> = combatants
        .into_iter()
        .map(|(name, dex, score)| Combatant {
            name,
            score,
            dex,
            conditions: Vec::new(),
        })
        .collect();
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
        order,
    };
    sessions.insert(id.clone(), session);
    let session = sessions.get(&id).unwrap();
    (200, format_session(session))
}

fn add_condition(id: &str, body: &str) -> (u16, String) {
    let obj = match json_parse(body) {
        Ok(Value::Object(o)) => o,
        _ => return (400, error_body()),
    };
    let target = match get_string(&obj, "target") {
        Some(s) => s,
        None => return (400, error_body()),
    };
    let condition_name = match get_string(&obj, "condition") {
        Some(s) => s,
        None => return (400, error_body()),
    };
    let duration = match get_i32(&obj, "duration_rounds") {
        Some(v) if v > 0 => v,
        _ => return (400, error_body()),
    };

    let mut sessions = SESSIONS.lock().unwrap();
    let session = match sessions.get_mut(id) {
        Some(s) => s,
        None => return (404, error_body()),
    };
    let combatant = match session.order.iter_mut().find(|c| c.name == target) {
        Some(c) => c,
        None => return (400, error_body()),
    };
    combatant.conditions.push(Condition {
        name: condition_name,
        remaining: duration,
    });

    let mut cond_parts: Vec<String> = Vec::new();
    for cond in &combatant.conditions {
        cond_parts.push(format!(
            r#"{{"condition":"{}","remaining_rounds":{}}}"#,
            json_escape(&cond.name),
            cond.remaining
        ));
    }
    (
        200,
        format!(
            r#"{{"target":"{}","conditions":[{}]}}"#,
            json_escape(&target),
            cond_parts.join(",")
        ),
    )
}

fn advance_turn(id: &str) -> (u16, String) {
    let mut sessions = SESSIONS.lock().unwrap();
    let session = match sessions.get_mut(id) {
        Some(s) => s,
        None => return (404, error_body()),
    };

    let n = session.order.len();
    if n > 0 {
        if session.turn_index + 1 >= n {
            session.turn_index = 0;
            session.round += 1;
        } else {
            session.turn_index += 1;
        }
        let active_name = session.order[session.turn_index].name.clone();
        if let Some(active) = session.order.iter_mut().find(|c| c.name == active_name) {
            for cond in &mut active.conditions {
                cond.remaining -= 1;
            }
            active.conditions.retain(|c| c.remaining > 0);
        }
    }

    (200, format_session(session))
}

fn format_session(session: &CombatSession) -> String {
    let active = &session.order[session.turn_index];
    let order_parts: Vec<String> = session
        .order
        .iter()
        .map(|c| {
            format!(
                r#"{{"name":"{}","score":{}}}"#,
                json_escape(&c.name),
                c.score
            )
        })
        .collect();
    let conditions = format_conditions(session);
    format!(
        r#"{{"id":"{}","round":{},"turn_index":{},"active":{{"name":"{}","score":{}}},"order":[{}],"conditions":{}}}"#,
        json_escape(&session.id),
        session.round,
        session.turn_index,
        json_escape(&active.name),
        active.score,
        order_parts.join(","),
        conditions
    )
}

fn format_conditions(session: &CombatSession) -> String {
    let mut entries: Vec<String> = Vec::new();
    for c in &session.order {
        let mut cond_parts: Vec<String> = Vec::new();
        for cond in &c.conditions {
            cond_parts.push(format!(
                r#"{{"condition":"{}","remaining_rounds":{}}}"#,
                json_escape(&cond.name),
                cond.remaining
            ));
        }
        entries.push(format!(
            r#""{}":[{}]"#,
            json_escape(&c.name),
            cond_parts.join(",")
        ));
    }
    format!("{{{}}}", entries.join(","))
}

fn json_escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c.is_control() => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}

fn get_string(obj: &HashMap<String, Value>, key: &str) -> Option<String> {
    match obj.get(key) {
        Some(Value::String(s)) => Some(s.clone()),
        _ => None,
    }
}

fn get_i32(obj: &HashMap<String, Value>, key: &str) -> Option<i32> {
    obj.get(key).and_then(as_i32)
}

fn get_array<'a>(obj: &'a HashMap<String, Value>, key: &str) -> Option<&'a Vec<Value>> {
    match obj.get(key) {
        Some(Value::Array(a)) => Some(a),
        _ => None,
    }
}

fn dice_stats(body: &str) -> (u16, String) {
    let parsed = match json_parse(body) {
        Ok(v) => v,
        Err(_) => return (400, error_body()),
    };
    let obj = match parsed {
        Value::Object(o) => o,
        _ => return (400, error_body()),
    };
    let expr = match obj.get("expression") {
        Some(Value::String(s)) => s,
        _ => return (400, error_body()),
    };
    let (count, sides, modifier) = match parse_dice(expr) {
        Some(v) => v,
        None => return (400, error_body()),
    };
    let min = count + modifier;
    let max = count * sides + modifier;
    let average = format_average(count, sides, modifier);
    (
        200,
        format!(
            r#"{{"dice_count":{},"sides":{},"modifier":{},"min":{},"max":{},"average":{}}}"#,
            count, sides, modifier, min, max, average
        ),
    )
}

fn format_average(count: i32, sides: i32, modifier: i32) -> String {
    // average = count * (sides + 1) / 2 + modifier
    // Represent exactly as an integer or a single .5 fraction.
    let numerator = (count as i64) * (sides as i64 + 1) + 2 * (modifier as i64);
    let q = numerator.div_euclid(2);
    let r = numerator.rem_euclid(2);
    if r == 0 {
        format!("{}", q)
    } else if q >= 0 {
        format!("{}.5", q)
    } else {
        format!("-{}.5", -(q + 1))
    }
}

fn format_fraction(num: i64, den: i64) -> String {
    // den is assumed positive.
    let q = num.div_euclid(den);
    let r = num.rem_euclid(den);
    if r == 0 {
        format!("{}", q)
    } else if q >= 0 {
        format!("{}.5", q)
    } else {
        format!("-{}.5", -(q + 1))
    }
}

fn parse_dice(expr: &str) -> Option<(i32, i32, i32)> {
    let b = expr.as_bytes();
    let mut i = 0;

    let start = i;
    while i < b.len() && b[i].is_ascii_digit() {
        i += 1;
    }
    if start == i {
        return None;
    }
    let count: i32 = expr[start..i].parse().ok()?;
    if count <= 0 {
        return None;
    }
    if i >= b.len() || b[i] != b'd' {
        return None;
    }
    i += 1;

    let start = i;
    while i < b.len() && b[i].is_ascii_digit() {
        i += 1;
    }
    if start == i {
        return None;
    }
    let sides: i32 = expr[start..i].parse().ok()?;
    if sides <= 0 {
        return None;
    }

    let mut modifier = 0;
    if i < b.len() {
        let op = expr[i..].chars().next()?;
        if op != '+' && op != '-' {
            return None;
        }
        i += op.len_utf8();
        let start = i;
        while i < b.len() && b[i].is_ascii_digit() {
            i += 1;
        }
        if start == i {
            return None;
        }
        let mod_val: i32 = expr[start..i].parse().ok()?;
        modifier = if op == '+' { mod_val } else { -mod_val };
    }

    if i != b.len() {
        return None;
    }
    Some((count, sides, modifier))
}

fn ability_check(body: &str) -> (u16, String) {
    let obj = match json_parse(body) {
        Ok(Value::Object(o)) => o,
        _ => return (400, error_body()),
    };
    let roll = match obj.get("roll").and_then(as_i32) {
        Some(v) => v,
        None => return (400, error_body()),
    };
    let modifier = match obj.get("modifier").and_then(as_i32) {
        Some(v) => v,
        None => return (400, error_body()),
    };
    let dc = match obj.get("dc").and_then(as_i32) {
        Some(v) => v,
        None => return (400, error_body()),
    };
    let total = roll + modifier;
    let success = total >= dc;
    let margin = total - dc;
    (
        200,
        format!(
            r#"{{"total":{},"success":{},"margin":{}}}"#,
            total, success, margin
        ),
    )
}

fn adjusted_xp(body: &str) -> (u16, String) {
    let obj = match json_parse(body) {
        Ok(Value::Object(o)) => o,
        _ => return (400, error_body()),
    };
    let party = match obj.get("party") {
        Some(Value::Array(a)) => a,
        _ => return (400, error_body()),
    };
    let monsters = match obj.get("monsters") {
        Some(Value::Array(a)) => a,
        _ => return (400, error_body()),
    };

    let mut thresholds = (0i32, 0i32, 0i32, 0i32);
    for member in party {
        let m = match member {
            Value::Object(o) => o,
            _ => return (400, error_body()),
        };
        let level = match m.get("level").and_then(as_i32) {
            Some(v) => v,
            None => return (400, error_body()),
        };
        let (e, m, h, d) = match thresholds_for_level(level) {
            Some(v) => v,
            None => return (400, error_body()),
        };
        thresholds.0 += e;
        thresholds.1 += m;
        thresholds.2 += h;
        thresholds.3 += d;
    }

    let mut base_xp = 0i32;
    let mut monster_count = 0i32;
    for m in monsters {
        let mo = match m {
            Value::Object(o) => o,
            _ => return (400, error_body()),
        };
        let cr = match mo.get("cr") {
            Some(Value::String(s)) => s,
            _ => return (400, error_body()),
        };
        let count = match mo.get("count").and_then(as_i32) {
            Some(v) if v > 0 => v,
            _ => return (400, error_body()),
        };
        let xp = match xp_for_cr(cr) {
            Some(v) => v,
            None => return (400, error_body()),
        };
        base_xp += xp * count;
        monster_count += count;
    }

    let (num, den) = multiplier_for_count(monster_count);
    let adjusted_xp = base_xp * num / den;
    let multiplier_str = format_fraction(num as i64, den as i64);

    let difficulty = if adjusted_xp >= thresholds.3 {
        "deadly"
    } else if adjusted_xp >= thresholds.2 {
        "hard"
    } else if adjusted_xp >= thresholds.1 {
        "medium"
    } else if adjusted_xp >= thresholds.0 {
        "easy"
    } else {
        "trivial"
    };

    (
        200,
        format!(
            r#"{{"base_xp":{},"monster_count":{},"multiplier":{},"adjusted_xp":{},"difficulty":"{}","thresholds":{{"easy":{},"medium":{},"hard":{},"deadly":{}}}}}"#,
            base_xp,
            monster_count,
            multiplier_str,
            adjusted_xp,
            difficulty,
            thresholds.0,
            thresholds.1,
            thresholds.2,
            thresholds.3
        ),
    )
}

fn thresholds_for_level(level: i32) -> Option<(i32, i32, i32, i32)> {
    match level {
        1 => Some((25, 50, 75, 100)),
        2 => Some((50, 100, 150, 200)),
        3 => Some((75, 150, 225, 400)),
        4 => Some((125, 250, 375, 500)),
        5 => Some((250, 500, 750, 1100)),
        6 => Some((300, 600, 900, 1400)),
        7 => Some((350, 750, 1100, 1700)),
        8 => Some((450, 900, 1400, 2100)),
        9 => Some((550, 1100, 1600, 2400)),
        10 => Some((600, 1200, 1900, 2800)),
        11 => Some((800, 1600, 2400, 3600)),
        12 => Some((1000, 2000, 3000, 4500)),
        13 => Some((1200, 2400, 3600, 5400)),
        14 => Some((1500, 3000, 4500, 6700)),
        15 => Some((2000, 4000, 6000, 8800)),
        16 => Some((2500, 5000, 7500, 11000)),
        17 => Some((3000, 6000, 9000, 13200)),
        18 => Some((3500, 7000, 10500, 15700)),
        19 => Some((4500, 9000, 13500, 20000)),
        20 => Some((5500, 11000, 16500, 24000)),
        _ => None,
    }
}

fn xp_for_cr(cr: &str) -> Option<i32> {
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

fn multiplier_for_count(count: i32) -> (i32, i32) {
    match count {
        1 => (1, 1),
        2 => (3, 2),
        3..=6 => (2, 1),
        7..=10 => (5, 2),
        11..=14 => (3, 1),
        15.. => (4, 1),
        _ => (1, 1),
    }
}

fn initiative_order(body: &str) -> (u16, String) {
    let obj = match json_parse(body) {
        Ok(Value::Object(o)) => o,
        _ => return (400, error_body()),
    };
    let arr = match obj.get("combatants") {
        Some(Value::Array(a)) => a,
        _ => return (400, error_body()),
    };
    let mut combatants: Vec<(String, i32, i32)> = Vec::new();
    for c in arr {
        let co = match c {
            Value::Object(o) => o,
            _ => return (400, error_body()),
        };
        let name = match co.get("name") {
            Some(Value::String(s)) => s.clone(),
            _ => return (400, error_body()),
        };
        let dex = match co.get("dex").and_then(as_i32) {
            Some(v) => v,
            None => return (400, error_body()),
        };
        let roll = match co.get("roll").and_then(as_i32) {
            Some(v) => v,
            None => return (400, error_body()),
        };
        combatants.push((name, roll + dex, dex));
    }
    combatants.sort_by(|a, b| {
        b.1.cmp(&a.1)
            .then_with(|| b.2.cmp(&a.2))
            .then_with(|| a.0.cmp(&b.0))
    });

    let mut pieces: Vec<String> = Vec::new();
    for (name, score, _) in combatants {
        pieces.push(format!(
            r#"{{"name":"{}","score":{}}}"#,
            json_escape(&name),
            score
        ));
    }
    (200, format!(r#"{{"order":[{}]}}"#, pieces.join(",")))
}

fn ability_modifier(body: &str) -> (u16, String) {
    let obj = match json_parse(body) {
        Ok(Value::Object(o)) => o,
        _ => return (400, error_body()),
    };
    let score = match obj.get("score").and_then(as_i32) {
        Some(v) if (1..=30).contains(&v) => v,
        _ => return (400, error_body()),
    };
    let modifier = ability_modifier_for_score(score);
    (
        200,
        format!(r#"{{"score":{},"modifier":{}}}"#, score, modifier),
    )
}

fn proficiency_bonus(body: &str) -> (u16, String) {
    let obj = match json_parse(body) {
        Ok(Value::Object(o)) => o,
        _ => return (400, error_body()),
    };
    let level = match obj.get("level").and_then(as_i32) {
        Some(v) if (1..=20).contains(&v) => v,
        _ => return (400, error_body()),
    };
    let bonus = proficiency_for_level(level);
    (
        200,
        format!(
            r#"{{"level":{},"proficiency_bonus":{}}}"#,
            level, bonus
        ),
    )
}

fn derived_stats(body: &str) -> (u16, String) {
    let obj = match json_parse(body) {
        Ok(Value::Object(o)) => o,
        _ => return (400, error_body()),
    };
    let level = match obj.get("level").and_then(as_i32) {
        Some(v) if (1..=20).contains(&v) => v,
        _ => return (400, error_body()),
    };
    let abilities = match obj.get("abilities") {
        Some(Value::Object(o)) => o,
        _ => return (400, error_body()),
    };
    let str_mod = match ability_value(abilities, "str") {
        Some(v) => v,
        None => return (400, error_body()),
    };
    let dex_mod = match ability_value(abilities, "dex") {
        Some(v) => v,
        None => return (400, error_body()),
    };
    let con_mod = match ability_value(abilities, "con") {
        Some(v) => v,
        None => return (400, error_body()),
    };
    let int_mod = match ability_value(abilities, "int") {
        Some(v) => v,
        None => return (400, error_body()),
    };
    let wis_mod = match ability_value(abilities, "wis") {
        Some(v) => v,
        None => return (400, error_body()),
    };
    let cha_mod = match ability_value(abilities, "cha") {
        Some(v) => v,
        None => return (400, error_body()),
    };

    let armor = match obj.get("armor") {
        Some(Value::Object(o)) => o,
        _ => return (400, error_body()),
    };
    let base = match armor.get("base").and_then(as_i32) {
        Some(v) if v >= 0 => v,
        _ => return (400, error_body()),
    };
    let dex_cap = match armor.get("dex_cap").and_then(as_i32) {
        Some(v) if v >= 0 => v,
        _ => return (400, error_body()),
    };
    let shield_bonus = match armor.get("shield") {
        Some(Value::Bool(true)) => 2,
        Some(Value::Bool(false)) => 0,
        _ => return (400, error_body()),
    };

    let proficiency = proficiency_for_level(level);
    let hp_max = level * (6 + con_mod);
    let armor_class = base + dex_mod.min(dex_cap) + shield_bonus;

    (
        200,
        format!(
            r#"{{"level":{},"proficiency_bonus":{},"hp_max":{},"armor_class":{},"modifiers":{{"str":{},"dex":{},"con":{},"int":{},"wis":{},"cha":{}}}}}"#,
            level, proficiency, hp_max, armor_class, str_mod, dex_mod, con_mod, int_mod, wis_mod, cha_mod
        ),
    )
}

fn ability_value(abilities: &HashMap<String, Value>, key: &str) -> Option<i32> {
    match abilities.get(key).and_then(as_i32) {
        Some(v) if (1..=30).contains(&v) => Some(ability_modifier_for_score(v)),
        _ => None,
    }
}

fn ability_modifier_for_score(score: i32) -> i32 {
    (score - 10).div_euclid(2)
}

fn proficiency_for_level(level: i32) -> i32 {
    match level {
        1..=4 => 2,
        5..=8 => 3,
        9..=12 => 4,
        13..=16 => 5,
        17..=20 => 6,
        _ => 2,
    }
}

fn error_body() -> String {
    r#"{"error":"bad request"}"#.to_string()
}

fn respond(stream: &TcpStream, status: u16, body: &str) -> std::io::Result<()> {
    let label = match status {
        200 => "OK",
        400 => "Bad Request",
        404 => "Not Found",
        _ => "Error",
    };
    let mut stream = stream;
    write!(
        stream,
        "HTTP/1.1 {status} {label}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        body.len(),
        body
    )
}

fn as_i32(v: &Value) -> Option<i32> {
    match v {
        Value::Number(s) => s.parse().ok(),
        _ => None,
    }
}

// Minimal JSON parser

#[derive(Debug)]
enum Value {
    Number(String),
    String(String),
    Bool(bool),
    Array(Vec<Value>),
    Object(HashMap<String, Value>),
}

fn json_parse(input: &str) -> Result<Value, &'static str> {
    let s = input.as_bytes();
    let mut i = 0;
    let v = parse_value(s, &mut i)?;
    skip_ws(s, &mut i);
    if i != s.len() {
        return Err("trailing data");
    }
    Ok(v)
}

fn skip_ws(s: &[u8], i: &mut usize) {
    while *i < s.len() && s[*i].is_ascii_whitespace() {
        *i += 1;
    }
}

fn parse_value(s: &[u8], i: &mut usize) -> Result<Value, &'static str> {
    skip_ws(s, i);
    if *i >= s.len() {
        return Err("unexpected end");
    }
    match s[*i] {
        b'{' => parse_object(s, i),
        b'[' => parse_array(s, i),
        b'"' => parse_string(s, i).map(Value::String),
        b't' => parse_bool(s, i, true),
        b'f' => parse_bool(s, i, false),
        b'-' | b'0'..=b'9' => parse_number(s, i),
        _ => Err("invalid value"),
    }
}

fn parse_bool(s: &[u8], i: &mut usize, expected: bool) -> Result<Value, &'static str> {
    let word = if expected { "true" } else { "false" };
    if *i + word.len() > s.len() || &s[*i..*i + word.len()] != word.as_bytes() {
        return Err("invalid boolean");
    }
    *i += word.len();
    Ok(Value::Bool(expected))
}

fn parse_object(s: &[u8], i: &mut usize) -> Result<Value, &'static str> {
    if s[*i] != b'{' {
        return Err("expected '{'");
    }
    *i += 1;
    skip_ws(s, i);
    let mut map = HashMap::new();
    if *i < s.len() && s[*i] == b'}' {
        *i += 1;
        return Ok(Value::Object(map));
    }
    loop {
        skip_ws(s, i);
        let key = parse_string(s, i)?;
        skip_ws(s, i);
        if *i >= s.len() || s[*i] != b':' {
            return Err("expected ':'");
        }
        *i += 1;
        let val = parse_value(s, i)?;
        map.insert(key, val);
        skip_ws(s, i);
        if *i >= s.len() {
            return Err("expected ',' or '}'");
        }
        if s[*i] == b',' {
            *i += 1;
            continue;
        }
        if s[*i] == b'}' {
            *i += 1;
            return Ok(Value::Object(map));
        }
        return Err("expected ',' or '}'");
    }
}

fn parse_array(s: &[u8], i: &mut usize) -> Result<Value, &'static str> {
    if s[*i] != b'[' {
        return Err("expected '['");
    }
    *i += 1;
    skip_ws(s, i);
    let mut arr = Vec::new();
    if *i < s.len() && s[*i] == b']' {
        *i += 1;
        return Ok(Value::Array(arr));
    }
    loop {
        let val = parse_value(s, i)?;
        arr.push(val);
        skip_ws(s, i);
        if *i >= s.len() {
            return Err("expected ',' or ']'");
        }
        if s[*i] == b',' {
            *i += 1;
            continue;
        }
        if s[*i] == b']' {
            *i += 1;
            return Ok(Value::Array(arr));
        }
        return Err("expected ',' or ']'");
    }
}

fn parse_string(s: &[u8], i: &mut usize) -> Result<String, &'static str> {
    if s[*i] != b'"' {
        return Err("expected '\"'");
    }
    *i += 1;
    let mut out = String::new();
    while *i < s.len() {
        match s[*i] {
            b'"' => {
                *i += 1;
                return Ok(out);
            }
            b'\\' => {
                *i += 1;
                if *i >= s.len() {
                    return Err("unterminated escape");
                }
                match s[*i] {
                    b'"' => out.push('"'),
                    b'\\' => out.push('\\'),
                    b'/' => out.push('/'),
                    b'b' => out.push('\u{0008}'),
                    b'f' => out.push('\u{000C}'),
                    b'n' => out.push('\n'),
                    b'r' => out.push('\r'),
                    b't' => out.push('\t'),
                    b'u' => {
                        if *i + 4 >= s.len() {
                            return Err("bad unicode escape");
                        }
                        let hex = std::str::from_utf8(&s[*i + 1..*i + 5])
                            .map_err(|_| "bad unicode escape")?;
                        let code = u32::from_str_radix(hex, 16)
                            .map_err(|_| "bad unicode escape")?;
                        let ch = char::from_u32(code).ok_or("bad unicode escape")?;
                        out.push(ch);
                        *i += 4;
                    }
                    other => out.push(other as char),
                }
                *i += 1;
            }
            other => {
                out.push(other as char);
                *i += 1;
            }
        }
    }
    Err("unterminated string")
}

fn parse_number(s: &[u8], i: &mut usize) -> Result<Value, &'static str> {
    let start = *i;
    if s[*i] == b'-' {
        *i += 1;
    }
    if *i >= s.len() || !s[*i].is_ascii_digit() {
        return Err("invalid number");
    }
    while *i < s.len() && s[*i].is_ascii_digit() {
        *i += 1;
    }
    // We only need integers; do not consume a trailing fraction or exponent.
    let num = std::str::from_utf8(&s[start..*i]).map_err(|_| "invalid number")?;
    Ok(Value::Number(num.to_string()))
}
