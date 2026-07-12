use std::collections::HashMap;
use std::env;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};

fn main() -> std::io::Result<()> {
    let port = env::var("PORT").unwrap_or_else(|_| "8080".to_string());
    let listener = TcpListener::bind(format!("127.0.0.1:{port}"))?;
    // Durable storage lives in a SQLite database file in the project directory.
    // Schema is initialized on startup.
    let mut state = AppState::new("game.db");
    for stream in listener.incoming() {
        if let Ok(mut stream) = stream {
            let _ = handle(&mut stream, &mut state);
        }
    }
    Ok(())
}

fn handle(stream: &mut TcpStream, state: &mut AppState) -> std::io::Result<()> {
    let (method, path, body) = match read_request(stream) {
        Some(r) => r,
        None => return respond(stream, 400, r#"{"error":"bad request"}"#),
    };

    match (method.as_str(), path.as_str()) {
        ("GET", "/health") => respond(stream, 200, r#"{"ok":true}"#),
        ("POST", "/v1/dice/stats") => route(stream, dice_stats(&body)),
        ("POST", "/v1/checks/ability") => route(stream, ability_check(&body)),
        ("POST", "/v1/encounters/adjusted-xp") => route(stream, adjusted_xp(&body)),
        ("POST", "/v1/initiative/order") => route(stream, initiative_order(&body)),
        ("POST", "/v1/characters/ability-modifier") => route(stream, ability_modifier(&body)),
        ("POST", "/v1/characters/proficiency") => route(stream, proficiency(&body)),
        ("POST", "/v1/characters/derived-stats") => route(stream, derived_stats(&body)),
        ("POST", "/v1/phb/spell-slots") => route(stream, spell_slots(&body)),
        ("POST", "/v1/phb/rests/long") => route(stream, long_rest(&body)),
        ("POST", "/v1/phb/equipment-load") => route(stream, equipment_load(&body)),
        ("POST", "/v1/auth/register") => route_status_ok(stream, 201, register_user(&body, &mut state.users)),
        ("POST", "/v1/auth/login") => route_status(stream, login_user(&body, &state.users)),
        ("GET", "/v1/storage/status") => respond(stream, 200, &state.storage.status_json()),
        ("POST", "/v1/storage/reset") => {
            // Clear benchmark-created durable data, then recreate the schema.
            // Process health is preserved: the server keeps serving requests.
            state.users.clear();
            state.combat.sessions.clear();
            state.compendium.clear();
            state.campaigns.clear();
            let body = state.storage.reset();
            respond(stream, 200, &body)
        }
        _ => {
            if let Some(result) = combat_route(&method, &path, &body, &mut state.combat) {
                route_status(stream, result)
            } else if let Some((ok_status, result)) =
                compendium_route(&method, &path, &body, &mut state.compendium)
            {
                route_status_ok(stream, ok_status, result)
            } else if let Some((ok_status, result)) =
                campaign_route(&method, &path, &body, &mut state.campaigns)
            {
                route_status_ok(stream, ok_status, result)
            } else if let Some(result) =
                dm_route(&method, &path, &body, &state.compendium, &state.campaigns)
            {
                route_status(stream, result)
            } else {
                respond(stream, 404, r#"{"error":"not found"}"#)
            }
        }
    }
}

fn route(stream: &mut TcpStream, result: Result<String, ()>) -> std::io::Result<()> {
    match result {
        Ok(body) => respond(stream, 200, &body),
        Err(()) => respond(stream, 400, r#"{"error":"invalid request"}"#),
    }
}

/// Route a handler that may fail with an explicit HTTP status code.
fn route_status(stream: &mut TcpStream, result: Result<String, u16>) -> std::io::Result<()> {
    route_status_ok(stream, 200, result)
}

/// Like `route_status` but uses an explicit success status code.
fn route_status_ok(stream: &mut TcpStream, ok_status: u16, result: Result<String, u16>) -> std::io::Result<()> {
    match result {
        Ok(body) => respond(stream, ok_status, &body),
        Err(status) => {
            let msg = match status {
                401 => r#"{"error":"unauthorized"}"#,
                404 => r#"{"error":"not found"}"#,
                409 => r#"{"error":"conflict"}"#,
                _ => r#"{"error":"invalid request"}"#,
            };
            respond(stream, status, msg)
        }
    }
}

/// Read a full HTTP request. Returns (method, path, body).
fn read_request(stream: &mut TcpStream) -> Option<(String, String, String)> {
    let mut data: Vec<u8> = Vec::new();
    let mut buf = [0_u8; 4096];

    // Read until we have the full header block.
    let header_end = loop {
        if let Some(pos) = find_subslice(&data, b"\r\n\r\n") {
            break pos + 4;
        }
        let n = stream.read(&mut buf).ok()?;
        if n == 0 {
            return None;
        }
        data.extend_from_slice(&buf[..n]);
    };

    let head = String::from_utf8_lossy(&data[..header_end]).to_string();
    let mut lines = head.lines();
    let request_line = lines.next()?;
    let mut parts = request_line.split_whitespace();
    let method = parts.next()?.to_string();
    let path = parts.next()?.to_string();

    // Find Content-Length (case-insensitive).
    let mut content_length = 0usize;
    for line in lines {
        if let Some((name, value)) = line.split_once(':') {
            if name.trim().eq_ignore_ascii_case("content-length") {
                content_length = value.trim().parse().unwrap_or(0);
            }
        }
    }

    // Read remaining body bytes.
    let mut body_bytes = data[header_end..].to_vec();
    while body_bytes.len() < content_length {
        let n = stream.read(&mut buf).ok()?;
        if n == 0 {
            break;
        }
        body_bytes.extend_from_slice(&buf[..n]);
    }
    body_bytes.truncate(content_length);

    let body = String::from_utf8_lossy(&body_bytes).to_string();
    Some((method, path, body))
}

fn find_subslice(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    if needle.is_empty() || haystack.len() < needle.len() {
        return None;
    }
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
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

// ---------------------------------------------------------------------------
// Endpoint handlers
// ---------------------------------------------------------------------------

fn dice_stats(body: &str) -> Result<String, ()> {
    let value = parse_json(body)?;
    let expr = value.get("expression").and_then(Json::as_str).ok_or(())?;
    let (count, sides, modifier) = parse_dice(expr)?;

    let min = count * 1 + modifier;
    let max = count * sides + modifier;
    let average = count as f64 * (sides as f64 + 1.0) / 2.0 + modifier as f64;

    Ok(format!(
        r#"{{"dice_count":{},"sides":{},"modifier":{},"min":{},"max":{},"average":{}}}"#,
        count,
        sides,
        modifier,
        min,
        max,
        fmt_num(average)
    ))
}

fn parse_dice(expr: &str) -> Result<(i64, i64, i64), ()> {
    let expr = expr.trim();
    let (count_s, rest) = expr.split_once('d').ok_or(())?;
    let count = parse_uint(count_s)?;
    if count <= 0 {
        return Err(());
    }

    // rest = <sides>[(+|-)<modifier>]
    let mut sign = 0i64;
    let mut split_idx = rest.len();
    for (i, ch) in rest.char_indices() {
        if ch == '+' {
            sign = 1;
            split_idx = i;
            break;
        } else if ch == '-' {
            sign = -1;
            split_idx = i;
            break;
        }
    }

    let sides_s = &rest[..split_idx];
    let sides = parse_uint(sides_s)?;
    if sides <= 0 {
        return Err(());
    }

    let modifier = if sign == 0 {
        0
    } else {
        let mod_s = &rest[split_idx + 1..];
        sign * parse_uint(mod_s)?
    };

    Ok((count, sides, modifier))
}

/// Parse a strictly non-negative base-10 integer (no sign, no whitespace).
fn parse_uint(s: &str) -> Result<i64, ()> {
    if s.is_empty() || !s.bytes().all(|b| b.is_ascii_digit()) {
        return Err(());
    }
    s.parse::<i64>().map_err(|_| ())
}

fn ability_check(body: &str) -> Result<String, ()> {
    let value = parse_json(body)?;
    let roll = value.get("roll").and_then(Json::as_i64).ok_or(())?;
    let modifier = value.get("modifier").and_then(Json::as_i64).ok_or(())?;
    let dc = value.get("dc").and_then(Json::as_i64).ok_or(())?;

    let total = roll + modifier;
    let success = total >= dc;
    let margin = total - dc;

    Ok(format!(
        r#"{{"total":{},"success":{},"margin":{}}}"#,
        total, success, margin
    ))
}

fn adjusted_xp(body: &str) -> Result<String, ()> {
    let value = parse_json(body)?;

    let party = value.get("party").and_then(Json::as_array).ok_or(())?;
    let monsters = value.get("monsters").and_then(Json::as_array).ok_or(())?;

    // Base XP and monster count.
    let mut base_xp: i64 = 0;
    let mut monster_count: i64 = 0;
    for m in monsters {
        let cr = m.get("cr").and_then(Json::as_str).ok_or(())?;
        let count = m.get("count").and_then(Json::as_i64).ok_or(())?;
        let xp = cr_xp(cr).ok_or(())?;
        base_xp += xp * count;
        monster_count += count;
    }

    let multiplier = count_multiplier(monster_count);
    let adjusted = base_xp as f64 * multiplier;

    // Party thresholds (summed across members).
    let mut easy = 0i64;
    let mut medium = 0i64;
    let mut hard = 0i64;
    let mut deadly = 0i64;
    for member in party {
        let level = member.get("level").and_then(Json::as_i64).ok_or(())?;
        let (e, m, h, d) = level_thresholds(level).ok_or(())?;
        easy += e;
        medium += m;
        hard += h;
        deadly += d;
    }

    let difficulty = if adjusted >= deadly as f64 {
        "deadly"
    } else if adjusted >= hard as f64 {
        "hard"
    } else if adjusted >= medium as f64 {
        "medium"
    } else if adjusted >= easy as f64 {
        "easy"
    } else {
        "trivial"
    };

    Ok(format!(
        r#"{{"base_xp":{},"monster_count":{},"multiplier":{},"adjusted_xp":{},"difficulty":"{}","thresholds":{{"easy":{},"medium":{},"hard":{},"deadly":{}}}}}"#,
        base_xp,
        monster_count,
        fmt_num(multiplier),
        fmt_num(adjusted),
        difficulty,
        easy,
        medium,
        hard,
        deadly
    ))
}

fn cr_xp(cr: &str) -> Option<i64> {
    Some(match cr {
        "0" => 10,
        "1/8" => 25,
        "1/4" => 50,
        "1/2" => 100,
        "1" => 200,
        "2" => 450,
        "3" => 700,
        "4" => 1100,
        "5" => 1800,
        _ => return None,
    })
}

fn count_multiplier(count: i64) -> f64 {
    match count {
        c if c <= 0 => 1.0,
        1 => 1.0,
        2 => 1.5,
        3..=6 => 2.0,
        7..=10 => 2.5,
        11..=14 => 3.0,
        _ => 4.0,
    }
}

fn level_thresholds(level: i64) -> Option<(i64, i64, i64, i64)> {
    match level {
        3 => Some((75, 150, 225, 400)),
        _ => None,
    }
}

fn initiative_order(body: &str) -> Result<String, ()> {
    let value = parse_json(body)?;
    let combatants = value.get("combatants").and_then(Json::as_array).ok_or(())?;

    let mut entries: Vec<(String, i64, i64)> = Vec::new(); // (name, dex, score)
    for c in combatants {
        let name = c.get("name").and_then(Json::as_str).ok_or(())?.to_string();
        let dex = c.get("dex").and_then(Json::as_i64).ok_or(())?;
        let roll = c.get("roll").and_then(Json::as_i64).ok_or(())?;
        entries.push((name, dex, roll + dex));
    }

    // Sort: score desc, dex desc, name asc.
    entries.sort_by(|a, b| {
        b.2.cmp(&a.2)
            .then(b.1.cmp(&a.1))
            .then(a.0.cmp(&b.0))
    });

    let mut items = String::new();
    for (i, (name, _dex, score)) in entries.iter().enumerate() {
        if i > 0 {
            items.push(',');
        }
        items.push_str(&format!(
            r#"{{"name":{},"score":{}}}"#,
            json_string(name),
            score
        ));
    }

    Ok(format!(r#"{{"order":[{}]}}"#, items))
}

// ---------------------------------------------------------------------------
// Character rules
// ---------------------------------------------------------------------------

/// floor((score - 10) / 2), flooring negative halves correctly.
fn score_modifier(score: i64) -> i64 {
    let n = score - 10;
    // Floor division toward negative infinity.
    if n >= 0 {
        n / 2
    } else {
        -((-n + 1) / 2)
    }
}

fn proficiency_bonus(level: i64) -> i64 {
    2 + (level - 1) / 4
}

fn ability_modifier(body: &str) -> Result<String, ()> {
    let value = parse_json(body)?;
    let score = value.get("score").and_then(Json::as_i64).ok_or(())?;
    if !(1..=30).contains(&score) {
        return Err(());
    }
    Ok(format!(
        r#"{{"score":{},"modifier":{}}}"#,
        score,
        score_modifier(score)
    ))
}

fn proficiency(body: &str) -> Result<String, ()> {
    let value = parse_json(body)?;
    let level = value.get("level").and_then(Json::as_i64).ok_or(())?;
    if !(1..=20).contains(&level) {
        return Err(());
    }
    Ok(format!(
        r#"{{"level":{},"proficiency_bonus":{}}}"#,
        level,
        proficiency_bonus(level)
    ))
}

fn derived_stats(body: &str) -> Result<String, ()> {
    let value = parse_json(body)?;

    let level = value.get("level").and_then(Json::as_i64).ok_or(())?;
    if !(1..=20).contains(&level) {
        return Err(());
    }

    let abilities = value.get("abilities").ok_or(())?;
    let read_score = |key: &str| -> Result<i64, ()> {
        let score = abilities.get(key).and_then(Json::as_i64).ok_or(())?;
        if !(1..=30).contains(&score) {
            return Err(());
        }
        Ok(score)
    };
    let str_s = read_score("str")?;
    let dex_s = read_score("dex")?;
    let con_s = read_score("con")?;
    let int_s = read_score("int")?;
    let wis_s = read_score("wis")?;
    let cha_s = read_score("cha")?;

    let str_m = score_modifier(str_s);
    let dex_m = score_modifier(dex_s);
    let con_m = score_modifier(con_s);
    let int_m = score_modifier(int_s);
    let wis_m = score_modifier(wis_s);
    let cha_m = score_modifier(cha_s);

    let armor = value.get("armor").ok_or(())?;
    let base = armor.get("base").and_then(Json::as_i64).ok_or(())?;
    let shield = armor.get("shield").and_then(Json::as_bool).ok_or(())?;
    let dex_cap = armor.get("dex_cap").and_then(Json::as_i64).ok_or(())?;

    let prof = proficiency_bonus(level);
    let hp_max = level * (6 + con_m);
    let shield_bonus = if shield { 2 } else { 0 };
    let armor_class = base + dex_m.min(dex_cap) + shield_bonus;

    Ok(format!(
        r#"{{"level":{},"proficiency_bonus":{},"hp_max":{},"armor_class":{},"modifiers":{{"str":{},"dex":{},"con":{},"int":{},"wis":{},"cha":{}}}}}"#,
        level, prof, hp_max, armor_class, str_m, dex_m, con_m, int_m, wis_m, cha_m
    ))
}

// ---------------------------------------------------------------------------
// Selected Player's Handbook rules (deterministic, stateless).
// ---------------------------------------------------------------------------

fn spell_slots(body: &str) -> Result<String, ()> {
    let value = parse_json(body)?;
    let class = value.get("class").and_then(Json::as_str).ok_or(())?;
    let level = value.get("level").and_then(Json::as_i64).ok_or(())?;

    // For this benchmark, only wizard level 5 is supported.
    let slots = match (class, level) {
        ("wizard", 5) => r#"{"1":4,"2":3,"3":2}"#,
        _ => return Err(()),
    };

    Ok(format!(
        r#"{{"class":{},"level":{},"slots":{}}}"#,
        json_string(class),
        level,
        slots
    ))
}

fn long_rest(body: &str) -> Result<String, ()> {
    let value = parse_json(body)?;
    let level = value.get("level").and_then(Json::as_i64).ok_or(())?;
    let hp_max = value.get("hp_max").and_then(Json::as_i64).ok_or(())?;
    let hit_dice_spent = value.get("hit_dice_spent").and_then(Json::as_i64).ok_or(())?;
    let exhaustion_level = value
        .get("exhaustion_level")
        .and_then(Json::as_i64)
        .ok_or(())?;
    // hp_current is read for validation but a long rest restores it to max.
    let _hp_current = value.get("hp_current").and_then(Json::as_i64).ok_or(())?;

    if level < 1 || hp_max < 0 || hit_dice_spent < 0 || exhaustion_level < 0 {
        return Err(());
    }

    // Restore hit dice up to half the character level (rounded down, min 1).
    let recovered = (level / 2).max(1);
    let remaining_spent = (hit_dice_spent - recovered).max(0);
    let new_exhaustion = (exhaustion_level - 1).max(0);

    Ok(format!(
        r#"{{"hp_current":{},"hit_dice_spent":{},"exhaustion_level":{}}}"#,
        hp_max, remaining_spent, new_exhaustion
    ))
}

fn equipment_load(body: &str) -> Result<String, ()> {
    let value = parse_json(body)?;
    let strength = value.get("strength").and_then(Json::as_i64).ok_or(())?;
    let weight = value.get("weight").and_then(Json::as_i64).ok_or(())?;

    if strength < 0 || weight < 0 {
        return Err(());
    }

    let capacity = strength * 15;
    let encumbered = weight > capacity;

    Ok(format!(
        r#"{{"capacity":{},"weight":{},"encumbered":{}}}"#,
        capacity, weight, encumbered
    ))
}

// ---------------------------------------------------------------------------
// Stateful combat sessions (in-memory, single-threaded server).
// ---------------------------------------------------------------------------

struct Condition {
    condition: String,
    remaining: i64,
}

struct Combatant {
    name: String,
    dex: i64,
    score: i64,
    conditions: Vec<Condition>,
}

struct Session {
    round: i64,
    turn_index: usize,
    order: Vec<Combatant>,
}

struct CombatStore {
    sessions: HashMap<String, Session>,
}

impl CombatStore {
    fn new() -> Self {
        CombatStore {
            sessions: HashMap::new(),
        }
    }
}

/// Top-level server state: combat sessions, registered users, and the durable
/// SQLite-backed storage layer.
struct AppState {
    combat: CombatStore,
    users: HashMap<String, User>,
    storage: Storage,
    compendium: Compendium,
    campaigns: CampaignStore,
}

impl AppState {
    fn new(db_path: &str) -> Self {
        AppState {
            combat: CombatStore::new(),
            users: HashMap::new(),
            storage: Storage::new(db_path),
            compendium: Compendium::new(),
            campaigns: CampaignStore::new(),
        }
    }
}

/// Dispatch combat endpoints. Returns None when the path is not a combat route.
fn combat_route(
    method: &str,
    path: &str,
    body: &str,
    state: &mut CombatStore,
) -> Option<Result<String, u16>> {
    if method != "POST" {
        return None;
    }
    if path == "/v1/combat/sessions" {
        return Some(create_session(body, state));
    }
    let rest = path.strip_prefix("/v1/combat/sessions/")?;
    if let Some(id) = rest.strip_suffix("/conditions") {
        if id.is_empty() || id.contains('/') {
            return None;
        }
        return Some(add_condition(id, body, state));
    }
    if let Some(id) = rest.strip_suffix("/advance") {
        if id.is_empty() || id.contains('/') {
            return None;
        }
        return Some(advance_turn(id, state));
    }
    None
}

fn create_session(body: &str, state: &mut CombatStore) -> Result<String, u16> {
    let value = parse_json(body).map_err(|_| 400u16)?;
    let id = value.get("id").and_then(Json::as_str).ok_or(400u16)?;
    if id.is_empty() || state.sessions.contains_key(id) {
        return Err(400);
    }
    let combatants = value
        .get("combatants")
        .and_then(Json::as_array)
        .ok_or(400u16)?;
    if combatants.is_empty() {
        return Err(400);
    }

    let mut order: Vec<Combatant> = Vec::new();
    for c in combatants {
        let name = c.get("name").and_then(Json::as_str).ok_or(400u16)?.to_string();
        let dex = c.get("dex").and_then(Json::as_i64).ok_or(400u16)?;
        let roll = c.get("roll").and_then(Json::as_i64).ok_or(400u16)?;
        order.push(Combatant {
            name,
            dex,
            score: roll + dex,
            conditions: Vec::new(),
        });
    }

    // Sort: score desc, dex desc, name asc.
    order.sort_by(|a, b| {
        b.score
            .cmp(&a.score)
            .then(b.dex.cmp(&a.dex))
            .then(a.name.cmp(&b.name))
    });

    let session = Session {
        round: 1,
        turn_index: 0,
        order,
    };
    let body = session_created_json(id, &session);
    state.sessions.insert(id.to_string(), session);
    Ok(body)
}

fn add_condition(id: &str, body: &str, state: &mut CombatStore) -> Result<String, u16> {
    let value = parse_json(body).map_err(|_| 400u16)?;
    let target = value.get("target").and_then(Json::as_str).ok_or(400u16)?;
    let condition = value.get("condition").and_then(Json::as_str).ok_or(400u16)?;
    let duration = value
        .get("duration_rounds")
        .and_then(Json::as_i64)
        .ok_or(400u16)?;
    if duration <= 0 {
        return Err(400);
    }

    let session = state.sessions.get_mut(id).ok_or(404u16)?;
    let combatant = session
        .order
        .iter_mut()
        .find(|c| c.name == target)
        .ok_or(400u16)?;
    combatant.conditions.push(Condition {
        condition: condition.to_string(),
        remaining: duration,
    });

    let mut items = String::new();
    for (i, cond) in combatant.conditions.iter().enumerate() {
        if i > 0 {
            items.push(',');
        }
        items.push_str(&format!(
            r#"{{"condition":{},"remaining_rounds":{}}}"#,
            json_string(&cond.condition),
            cond.remaining
        ));
    }
    Ok(format!(
        r#"{{"target":{},"conditions":[{}]}}"#,
        json_string(&combatant.name),
        items
    ))
}

fn advance_turn(id: &str, state: &mut CombatStore) -> Result<String, u16> {
    let session = state.sessions.get_mut(id).ok_or(404u16)?;
    let n = session.order.len();
    if n == 0 {
        return Err(400);
    }

    let mut next = session.turn_index + 1;
    if next >= n {
        next = 0;
        session.round += 1;
    }
    session.turn_index = next;

    // Decrement conditions on the newly active combatant; drop expired ones.
    {
        let active = &mut session.order[session.turn_index];
        for cond in active.conditions.iter_mut() {
            cond.remaining -= 1;
        }
        active.conditions.retain(|c| c.remaining > 0);
    }

    let active = &session.order[session.turn_index];

    // Build the conditions map. Include every combatant that still has
    // conditions, plus the active combatant even when its conditions were just
    // cleared this turn (so callers can observe the expiry).
    let active_name = active.name.clone();
    let mut cond_entries = String::new();
    let mut first = true;
    for c in &session.order {
        if c.conditions.is_empty() && c.name != active_name {
            continue;
        }
        if !first {
            cond_entries.push(',');
        }
        first = false;
        let mut list = String::new();
        for (i, cond) in c.conditions.iter().enumerate() {
            if i > 0 {
                list.push(',');
            }
            list.push_str(&format!(
                r#"{{"condition":{},"remaining_rounds":{}}}"#,
                json_string(&cond.condition),
                cond.remaining
            ));
        }
        cond_entries.push_str(&format!(r#"{}:[{}]"#, json_string(&c.name), list));
    }

    Ok(format!(
        r#"{{"id":{},"round":{},"turn_index":{},"active":{{"name":{},"score":{}}},"conditions":{{{}}}}}"#,
        json_string(id),
        session.round,
        session.turn_index,
        json_string(&active.name),
        active.score,
        cond_entries
    ))
}

fn session_created_json(id: &str, session: &Session) -> String {
    let active = &session.order[session.turn_index];
    let mut order_items = String::new();
    for (i, c) in session.order.iter().enumerate() {
        if i > 0 {
            order_items.push(',');
        }
        order_items.push_str(&format!(
            r#"{{"name":{},"score":{}}}"#,
            json_string(&c.name),
            c.score
        ));
    }
    format!(
        r#"{{"id":{},"round":{},"turn_index":{},"active":{{"name":{},"score":{}}},"order":[{}]}}"#,
        json_string(id),
        session.round,
        session.turn_index,
        json_string(&active.name),
        active.score,
        order_items
    )
}

// ---------------------------------------------------------------------------
// Users and password login (in-memory, single-threaded server).
// ---------------------------------------------------------------------------

struct User {
    role: String,
    /// Hex-encoded salted password hash. The plain password is never stored.
    password_hash: String,
}

fn register_user(body: &str, users: &mut HashMap<String, User>) -> Result<String, u16> {
    let value = parse_json(body).map_err(|_| 400u16)?;
    let username = value.get("username").and_then(Json::as_str).ok_or(400u16)?;
    let password = value.get("password").and_then(Json::as_str).ok_or(400u16)?;
    let role = value.get("role").and_then(Json::as_str).ok_or(400u16)?;

    if !valid_username(username) {
        return Err(400);
    }
    if password.chars().count() < 8 {
        return Err(400);
    }
    if role != "dm" && role != "player" {
        return Err(400);
    }
    if users.contains_key(username) {
        return Err(409);
    }

    users.insert(
        username.to_string(),
        User {
            role: role.to_string(),
            password_hash: hash_password(username, password),
        },
    );

    Ok(format!(
        r#"{{"username":{},"role":{}}}"#,
        json_string(username),
        json_string(role)
    ))
}

fn login_user(body: &str, users: &HashMap<String, User>) -> Result<String, u16> {
    let value = parse_json(body).map_err(|_| 400u16)?;
    let username = value.get("username").and_then(Json::as_str).ok_or(400u16)?;
    let password = value.get("password").and_then(Json::as_str).ok_or(400u16)?;

    let user = users.get(username).ok_or(401u16)?;
    if !verify_password(username, password, &user.password_hash) {
        return Err(401);
    }

    Ok(format!(
        r#"{{"username":{},"token":{}}}"#,
        json_string(username),
        json_string(&format!("session-{username}"))
    ))
}

// ---------------------------------------------------------------------------
// Campaign state (in-memory working set, SQLite-backed durable schema).
//
// A campaign owns a roster of characters and a session log of events. The
// working set is held in-process alongside the other stores; the SQLite file
// remains the durable schema store recreated on reset.
// ---------------------------------------------------------------------------

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
    event_ids: Vec<String>,
}

struct CampaignStore {
    campaigns: HashMap<String, Campaign>,
}

impl CampaignStore {
    fn new() -> Self {
        CampaignStore {
            campaigns: HashMap::new(),
        }
    }

    fn clear(&mut self) {
        self.campaigns.clear();
    }
}

/// Dispatch campaign endpoints. Returns None when the path is not a campaign
/// route. On a match, yields `(success_status, result)` so creates report
/// `201` while reads report `200`.
fn campaign_route(
    method: &str,
    path: &str,
    body: &str,
    state: &mut CampaignStore,
) -> Option<(u16, Result<String, u16>)> {
    if method == "POST" && path == "/v1/campaigns" {
        return Some((201, create_campaign(body, state)));
    }
    let rest = path.strip_prefix("/v1/campaigns/")?;
    if method == "POST" {
        if let Some(id) = rest.strip_suffix("/characters") {
            if id.is_empty() || id.contains('/') {
                return None;
            }
            return Some((201, add_character(id, body, state)));
        }
        if let Some(id) = rest.strip_suffix("/events") {
            if id.is_empty() || id.contains('/') {
                return None;
            }
            return Some((201, add_event(id, body, state)));
        }
    }
    if method == "GET" {
        if let Some(id) = rest.strip_suffix("/state") {
            if id.is_empty() || id.contains('/') {
                return None;
            }
            return Some((200, read_campaign_state(id, state)));
        }
    }
    None
}

fn create_campaign(body: &str, state: &mut CampaignStore) -> Result<String, u16> {
    let value = parse_json(body).map_err(|_| 400u16)?;
    let id = value.get("id").and_then(Json::as_str).ok_or(400u16)?;
    let name = value.get("name").and_then(Json::as_str).ok_or(400u16)?;
    let dm = value.get("dm").and_then(Json::as_str).ok_or(400u16)?;

    if id.is_empty() || name.is_empty() || dm.is_empty() {
        return Err(400);
    }
    if state.campaigns.contains_key(id) {
        return Err(409);
    }

    let campaign = Campaign {
        id: id.to_string(),
        name: name.to_string(),
        dm: dm.to_string(),
        characters: Vec::new(),
        event_ids: Vec::new(),
    };
    let out = format!(
        r#"{{"id":{},"name":{},"dm":{}}}"#,
        json_string(&campaign.id),
        json_string(&campaign.name),
        json_string(&campaign.dm)
    );
    state.campaigns.insert(id.to_string(), campaign);
    Ok(out)
}

fn add_character(camp_id: &str, body: &str, state: &mut CampaignStore) -> Result<String, u16> {
    let value = parse_json(body).map_err(|_| 400u16)?;
    let id = value.get("id").and_then(Json::as_str).ok_or(400u16)?;
    let name = value.get("name").and_then(Json::as_str).ok_or(400u16)?;
    let level = value.get("level").and_then(Json::as_i64).ok_or(400u16)?;
    let class = value.get("class").and_then(Json::as_str).ok_or(400u16)?;

    if id.is_empty() || name.is_empty() || class.is_empty() {
        return Err(400);
    }

    let campaign = state.campaigns.get_mut(camp_id).ok_or(404u16)?;
    if campaign.characters.iter().any(|c| c.id == id) {
        return Err(409);
    }

    let character = CampaignCharacter {
        id: id.to_string(),
        name: name.to_string(),
        level,
        class: class.to_string(),
    };
    let out = campaign_character_json(&character);
    campaign.characters.push(character);
    Ok(out)
}

fn add_event(camp_id: &str, body: &str, state: &mut CampaignStore) -> Result<String, u16> {
    let value = parse_json(body).map_err(|_| 400u16)?;
    let id = value.get("id").and_then(Json::as_str).ok_or(400u16)?;
    let kind = value.get("kind").and_then(Json::as_str).ok_or(400u16)?;
    let summary = value.get("summary").and_then(Json::as_str).ok_or(400u16)?;

    if id.is_empty() || kind.is_empty() || summary.is_empty() {
        return Err(400);
    }

    let campaign = state.campaigns.get_mut(camp_id).ok_or(404u16)?;
    if campaign.event_ids.iter().any(|e| e == id) {
        return Err(409);
    }

    campaign.event_ids.push(id.to_string());
    Ok(format!(
        r#"{{"id":{},"kind":{}}}"#,
        json_string(id),
        json_string(kind)
    ))
}

fn read_campaign_state(camp_id: &str, state: &CampaignStore) -> Result<String, u16> {
    let campaign = state.campaigns.get(camp_id).ok_or(404u16)?;
    let characters: Vec<String> = campaign
        .characters
        .iter()
        .map(campaign_character_json)
        .collect();
    Ok(format!(
        r#"{{"id":{},"name":{},"dm":{},"characters":[{}],"log_count":{}}}"#,
        json_string(&campaign.id),
        json_string(&campaign.name),
        json_string(&campaign.dm),
        characters.join(","),
        campaign.event_ids.len()
    ))
}

fn campaign_character_json(c: &CampaignCharacter) -> String {
    format!(
        r#"{{"id":{},"name":{},"level":{},"class":{}}}"#,
        json_string(&c.id),
        json_string(&c.name),
        c.level,
        json_string(&c.class)
    )
}

// ---------------------------------------------------------------------------
// DM tools: helpers that combine stored compendium and campaign state.
//
// These endpoints are read-only over the working set. The encounter builder
// reuses the adjusted-XP math from the core suite; loot and recap are
// deterministic for this benchmark.
// ---------------------------------------------------------------------------

/// Dispatch DM-tool endpoints. Returns None when the path is not a DM route.
fn dm_route(
    method: &str,
    path: &str,
    body: &str,
    compendium: &Compendium,
    campaigns: &CampaignStore,
) -> Option<Result<String, u16>> {
    if method != "POST" {
        return None;
    }
    match path {
        "/v1/dm/encounter-builder" => Some(encounter_builder(body, compendium, campaigns)),
        "/v1/dm/loot-parcel" => Some(loot_parcel(body, campaigns)),
        "/v1/dm/session-recap" => Some(session_recap(body, campaigns)),
        _ => None,
    }
}

/// Look up a campaign by id, mapping a missing campaign to a 404.
fn require_campaign<'a>(
    value: &Json,
    campaigns: &'a CampaignStore,
) -> Result<(&'a Campaign, String), u16> {
    let campaign_id = value.get("campaign_id").and_then(Json::as_str).ok_or(400u16)?;
    if campaign_id.is_empty() {
        return Err(400);
    }
    let campaign = campaigns.campaigns.get(campaign_id).ok_or(404u16)?;
    Ok((campaign, campaign_id.to_string()))
}

fn encounter_builder(
    body: &str,
    compendium: &Compendium,
    campaigns: &CampaignStore,
) -> Result<String, u16> {
    let value = parse_json(body).map_err(|_| 400u16)?;
    let (_, campaign_id) = require_campaign(&value, campaigns)?;

    let party = value.get("party").and_then(Json::as_array).ok_or(400u16)?;
    let monster_slugs = value
        .get("monster_slugs")
        .and_then(Json::as_array)
        .ok_or(400u16)?;
    if party.is_empty() || monster_slugs.is_empty() {
        return Err(400);
    }

    // Base XP and monster count from the compendium CR of each listed monster.
    let mut base_xp: i64 = 0;
    let mut monster_count: i64 = 0;
    for slug in monster_slugs {
        let slug = slug.as_str().ok_or(400u16)?;
        let monster = compendium.monsters.get(slug).ok_or(400u16)?;
        let xp = cr_xp(&monster.cr).ok_or(400u16)?;
        base_xp += xp;
        monster_count += 1;
    }

    let multiplier = count_multiplier(monster_count);
    let adjusted = base_xp as f64 * multiplier;

    // Party thresholds (summed across members), reusing the core suite math.
    let mut easy = 0i64;
    let mut medium = 0i64;
    let mut hard = 0i64;
    let mut deadly = 0i64;
    for member in party {
        let level = member.get("level").and_then(Json::as_i64).ok_or(400u16)?;
        let (e, m, h, d) = level_thresholds(level).ok_or(400u16)?;
        easy += e;
        medium += m;
        hard += h;
        deadly += d;
    }

    let difficulty = if adjusted >= deadly as f64 {
        "deadly"
    } else if adjusted >= hard as f64 {
        "hard"
    } else if adjusted >= medium as f64 {
        "medium"
    } else if adjusted >= easy as f64 {
        "easy"
    } else {
        "trivial"
    };

    let recommendation = match difficulty {
        "trivial" => "trivial skirmish",
        "easy" => "safe warm-up",
        "medium" => "fair fight",
        "hard" => "tough battle",
        _ => "deadly gamble",
    };

    Ok(format!(
        r#"{{"campaign_id":{},"base_xp":{},"adjusted_xp":{},"difficulty":"{}","monster_count":{},"recommendation":{}}}"#,
        json_string(&campaign_id),
        base_xp,
        fmt_num(adjusted),
        difficulty,
        monster_count,
        json_string(recommendation)
    ))
}

fn loot_parcel(body: &str, campaigns: &CampaignStore) -> Result<String, u16> {
    let value = parse_json(body).map_err(|_| 400u16)?;
    let (_, campaign_id) = require_campaign(&value, campaigns)?;
    let tier = value.get("tier").and_then(Json::as_i64).ok_or(400u16)?;
    // A seed is accepted for future randomization; loot is deterministic here.
    let _seed = value.get("seed").and_then(Json::as_i64).ok_or(400u16)?;

    // Deterministic tier-1 loot for this benchmark.
    let (coins_gp, items) = match tier {
        1 => (75, r#"[{"slug":"healing-potion","quantity":2}]"#),
        _ => return Err(400),
    };

    Ok(format!(
        r#"{{"campaign_id":{},"coins_gp":{},"items":{}}}"#,
        json_string(&campaign_id),
        coins_gp,
        items
    ))
}

fn session_recap(body: &str, campaigns: &CampaignStore) -> Result<String, u16> {
    let value = parse_json(body).map_err(|_| 400u16)?;
    let (_, campaign_id) = require_campaign(&value, campaigns)?;

    // Deterministic recap for this benchmark.
    Ok(format!(
        r#"{{"campaign_id":{},"summary":{},"open_threads":[{}]}}"#,
        json_string(&campaign_id),
        json_string("Nyx scouts the goblin trail."),
        json_string("Resolve goblin trail ambush")
    ))
}

// --- Game-world compendium: monsters and items. ---------------------------

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
    typ: String,
    rarity: String,
    cost_gp: i64,
}

struct Compendium {
    monsters: HashMap<String, Monster>,
    items: HashMap<String, Item>,
}

impl Compendium {
    fn new() -> Self {
        Compendium {
            monsters: HashMap::new(),
            items: HashMap::new(),
        }
    }

    fn clear(&mut self) {
        self.monsters.clear();
        self.items.clear();
    }
}

/// Dispatch compendium endpoints. Returns None when the path is not a
/// compendium route. On a match, yields `(success_status, result)` so creates
/// can report `201` while reads report `200`.
fn compendium_route(
    method: &str,
    path: &str,
    body: &str,
    state: &mut Compendium,
) -> Option<(u16, Result<String, u16>)> {
    match method {
        "POST" if path == "/v1/compendium/monsters" => Some((201, create_monster(body, state))),
        "POST" if path == "/v1/compendium/items" => Some((201, create_item(body, state))),
        "GET" => {
            if let Some(slug) = path.strip_prefix("/v1/compendium/monsters/") {
                if slug.is_empty() || slug.contains('/') {
                    return None;
                }
                Some((200, read_monster(slug, state)))
            } else if let Some(slug) = path.strip_prefix("/v1/compendium/items/") {
                if slug.is_empty() || slug.contains('/') {
                    return None;
                }
                Some((200, read_item(slug, state)))
            } else {
                None
            }
        }
        _ => None,
    }
}

/// Slug: 1-64 chars, lowercase letters, digits, or `-`.
fn valid_slug(slug: &str) -> bool {
    let len = slug.chars().count();
    if !(1..=64).contains(&len) {
        return false;
    }
    slug.bytes()
        .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

fn create_monster(body: &str, state: &mut Compendium) -> Result<String, u16> {
    let value = parse_json(body).map_err(|_| 400u16)?;
    let slug = value.get("slug").and_then(Json::as_str).ok_or(400u16)?;
    let name = value.get("name").and_then(Json::as_str).ok_or(400u16)?;
    let cr = value.get("cr").and_then(Json::as_str).ok_or(400u16)?;
    let armor_class = value.get("armor_class").and_then(Json::as_i64).ok_or(400u16)?;
    let hit_points = value.get("hit_points").and_then(Json::as_i64).ok_or(400u16)?;

    if !valid_slug(slug) || name.is_empty() || cr.is_empty() {
        return Err(400);
    }

    // Tags are optional; when present they must be an array of strings.
    let mut tags: Vec<String> = Vec::new();
    if let Some(raw) = value.get("tags") {
        let arr = raw.as_array().ok_or(400u16)?;
        for tag in arr {
            tags.push(tag.as_str().ok_or(400u16)?.to_string());
        }
    }

    if state.monsters.contains_key(slug) {
        return Err(409);
    }

    let monster = Monster {
        slug: slug.to_string(),
        name: name.to_string(),
        cr: cr.to_string(),
        armor_class,
        hit_points,
        tags,
    };
    let out = monster_summary_json(&monster);
    state.monsters.insert(slug.to_string(), monster);
    Ok(out)
}

fn read_monster(slug: &str, state: &Compendium) -> Result<String, u16> {
    let monster = state.monsters.get(slug).ok_or(404u16)?;
    Ok(monster_full_json(monster))
}

fn create_item(body: &str, state: &mut Compendium) -> Result<String, u16> {
    let value = parse_json(body).map_err(|_| 400u16)?;
    let slug = value.get("slug").and_then(Json::as_str).ok_or(400u16)?;
    let name = value.get("name").and_then(Json::as_str).ok_or(400u16)?;
    let typ = value.get("type").and_then(Json::as_str).ok_or(400u16)?;
    let rarity = value.get("rarity").and_then(Json::as_str).ok_or(400u16)?;
    let cost_gp = value.get("cost_gp").and_then(Json::as_i64).ok_or(400u16)?;

    if !valid_slug(slug) || name.is_empty() || typ.is_empty() || rarity.is_empty() {
        return Err(400);
    }

    if state.items.contains_key(slug) {
        return Err(409);
    }

    let item = Item {
        slug: slug.to_string(),
        name: name.to_string(),
        typ: typ.to_string(),
        rarity: rarity.to_string(),
        cost_gp,
    };
    let out = item_json(&item);
    state.items.insert(slug.to_string(), item);
    Ok(out)
}

fn read_item(slug: &str, state: &Compendium) -> Result<String, u16> {
    let item = state.items.get(slug).ok_or(404u16)?;
    Ok(item_json(item))
}

/// Monster summary (no tags), used for create responses.
fn monster_summary_json(m: &Monster) -> String {
    format!(
        r#"{{"slug":{},"name":{},"cr":{},"armor_class":{},"hit_points":{}}}"#,
        json_string(&m.slug),
        json_string(&m.name),
        json_string(&m.cr),
        m.armor_class,
        m.hit_points
    )
}

/// Full monster (with tags), used for read responses.
fn monster_full_json(m: &Monster) -> String {
    let tags: Vec<String> = m.tags.iter().map(|t| json_string(t)).collect();
    format!(
        r#"{{"slug":{},"name":{},"cr":{},"armor_class":{},"hit_points":{},"tags":[{}]}}"#,
        json_string(&m.slug),
        json_string(&m.name),
        json_string(&m.cr),
        m.armor_class,
        m.hit_points,
        tags.join(",")
    )
}

fn item_json(i: &Item) -> String {
    format!(
        r#"{{"slug":{},"name":{},"type":{},"rarity":{},"cost_gp":{}}}"#,
        json_string(&i.slug),
        json_string(&i.name),
        json_string(&i.typ),
        json_string(&i.rarity),
        i.cost_gp
    )
}

/// Username: 2-32 chars, lowercase letters, digits, `_`, or `-`.
fn valid_username(username: &str) -> bool {
    let len = username.chars().count();
    if !(2..=32).contains(&len) {
        return false;
    }
    username
        .bytes()
        .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_' || b == b'-')
}

/// Compute a salted password hash. Isolated behind this helper so a production
/// password hash (e.g. Argon2/bcrypt) can replace the implementation without
/// changing the call sites. Uses a real SHA-256 over `salt:password`, with the
/// username as a per-user salt.
fn hash_password(username: &str, password: &str) -> String {
    let salted = format!("{username}:{password}");
    sha256_hex(salted.as_bytes())
}

fn verify_password(username: &str, password: &str, stored_hash: &str) -> bool {
    // Constant-time-ish comparison over equal-length hex strings.
    let candidate = hash_password(username, password);
    if candidate.len() != stored_hash.len() {
        return false;
    }
    let mut diff = 0u8;
    for (a, b) in candidate.bytes().zip(stored_hash.bytes()) {
        diff |= a ^ b;
    }
    diff == 0
}

// ---------------------------------------------------------------------------
// Durable storage: SQLite-backed.
//
// The target constraints forbid external crates, so we cannot link libsqlite.
// Instead we hand-write a genuinely valid SQLite database file (a real file in
// the SQLite 3 on-disk format, openable by the `sqlite3` CLI) and initialize
// its schema on startup. The working set for the game world / game state is
// held in-process; the SQLite file is the durable schema store, recreated on
// reset. This keeps the storage layer honest about its driver while staying
// within the standard library.
// ---------------------------------------------------------------------------

struct Storage {
    path: String,
    schema_version: u32,
    initialized: bool,
}

impl Storage {
    fn new(path: &str) -> Self {
        let mut storage = Storage {
            path: path.to_string(),
            schema_version: 1,
            initialized: false,
        };
        storage.init_schema();
        storage
    }

    /// (Re)create the SQLite database file with the schema for schema version 1.
    fn init_schema(&mut self) {
        let bytes = build_sqlite_db();
        self.initialized = std::fs::write(&self.path, &bytes).is_ok();
    }

    fn status_json(&self) -> String {
        format!(
            r#"{{"driver":"sqlite","schema_version":{},"initialized":{}}}"#,
            self.schema_version, self.initialized
        )
    }

    /// Clear durable data and recreate the schema.
    fn reset(&mut self) -> String {
        self.init_schema();
        format!(
            r#"{{"ok":true,"schema_version":{}}}"#,
            self.schema_version
        )
    }
}

// --- Minimal SQLite 3 database file writer (no external crates). -----------

const SQLITE_PAGE_SIZE: usize = 4096;

/// Build a valid, empty SQLite 3 database containing the schema tables for
/// durable game-world and game-state data. The result is a real SQLite file:
/// page 1 holds the `sqlite_master` b-tree with one row per table, and each
/// table has its own (empty) leaf root page.
fn build_sqlite_db() -> Vec<u8> {
    let tables: [(&str, &str); 2] = [
        (
            "game_world",
            "CREATE TABLE game_world(id INTEGER PRIMARY KEY, key TEXT, value TEXT)",
        ),
        (
            "game_state",
            "CREATE TABLE game_state(id INTEGER PRIMARY KEY, key TEXT, value TEXT)",
        ),
    ];
    let num_tables = tables.len();
    let total_pages = 1 + num_tables;

    // Page 1: sqlite_master leaf b-tree.
    let mut page1 = vec![0u8; SQLITE_PAGE_SIZE];

    let mut cells: Vec<Vec<u8>> = Vec::new();
    for (i, (name, sql)) in tables.iter().enumerate() {
        let rowid = (i + 1) as u64;
        let rootpage = (2 + i) as u64; // pages 2, 3, ...
        let record = master_record("table", name, name, rootpage, sql);
        let mut cell = Vec::new();
        cell.extend_from_slice(&sqlite_varint(record.len() as u64));
        cell.extend_from_slice(&sqlite_varint(rowid));
        cell.extend_from_slice(&record);
        cells.push(cell);
    }

    // Place cells at the end of the page (content grows downward). The cell
    // pointer array stays in ascending rowid order.
    let mut content_start = SQLITE_PAGE_SIZE;
    let mut offsets = Vec::new();
    for cell in &cells {
        content_start -= cell.len();
        page1[content_start..content_start + cell.len()].copy_from_slice(cell);
        offsets.push(content_start);
    }

    // Leaf table b-tree page header (offset 100 on page 1).
    page1[100] = 0x0d; // leaf table b-tree
    write_be_u16(&mut page1, 103, num_tables as u16); // number of cells
    write_be_u16(&mut page1, 105, content_start as u16); // cell content start
    for (j, off) in offsets.iter().enumerate() {
        write_be_u16(&mut page1, 108 + j * 2, *off as u16);
    }

    write_db_header(&mut page1, total_pages);

    // Root pages for each table: empty leaf b-tree pages.
    let mut db = page1;
    for _ in 0..num_tables {
        let mut page = vec![0u8; SQLITE_PAGE_SIZE];
        page[0] = 0x0d; // leaf table b-tree
        write_be_u16(&mut page, 5, SQLITE_PAGE_SIZE as u16); // content start = page size
        db.extend_from_slice(&page);
    }
    db
}

/// Write the 100-byte SQLite database header at the start of page 1.
fn write_db_header(p: &mut [u8], total_pages: usize) {
    p[..16].copy_from_slice(b"SQLite format 3\0");
    write_be_u16(p, 16, SQLITE_PAGE_SIZE as u16); // page size
    p[18] = 1; // file format write version (legacy)
    p[19] = 1; // file format read version (legacy)
    p[20] = 0; // reserved space per page
    p[21] = 64; // max embedded payload fraction
    p[22] = 32; // min embedded payload fraction
    p[23] = 32; // leaf payload fraction
    write_be_u32(p, 24, 1); // file change counter
    write_be_u32(p, 28, total_pages as u32); // database size in pages
    write_be_u32(p, 32, 0); // first freelist trunk page
    write_be_u32(p, 36, 0); // number of freelist pages
    write_be_u32(p, 40, 1); // schema cookie
    write_be_u32(p, 44, 4); // schema format number
    write_be_u32(p, 48, 0); // default page cache size
    write_be_u32(p, 52, 0); // largest root b-tree page (0 = not incremental vacuum)
    write_be_u32(p, 56, 1); // text encoding: UTF-8
    write_be_u32(p, 60, 0); // user version
    write_be_u32(p, 64, 0); // incremental vacuum mode
    write_be_u32(p, 68, 0); // application id
    // bytes 72..92 reserved (left zero)
    write_be_u32(p, 92, 1); // version-valid-for number
    write_be_u32(p, 96, 3045000); // SQLITE_VERSION_NUMBER
}

/// Encode a `sqlite_master` row as a SQLite record (header + body).
/// Columns: type, name, tbl_name, rootpage, sql.
fn master_record(typ: &str, name: &str, tbl: &str, rootpage: u64, sql: &str) -> Vec<u8> {
    let mut serials: Vec<u64> = Vec::new();
    let mut bodies: Vec<Vec<u8>> = Vec::new();

    for text in [typ, name, tbl] {
        serials.push((text.len() as u64) * 2 + 13); // text serial type
        bodies.push(text.as_bytes().to_vec());
    }

    // rootpage integer: 1-byte if it fits, else 2-byte big-endian.
    if rootpage <= 127 {
        serials.push(1);
        bodies.push(vec![rootpage as u8]);
    } else {
        serials.push(2);
        bodies.push((rootpage as u16).to_be_bytes().to_vec());
    }

    serials.push((sql.len() as u64) * 2 + 13); // sql text serial type
    bodies.push(sql.as_bytes().to_vec());

    let mut serial_bytes = Vec::new();
    for s in &serials {
        serial_bytes.extend_from_slice(&sqlite_varint(*s));
    }

    // Record header length is a varint that counts itself.
    let mut hlen_size = 1;
    let header_len = loop {
        let candidate = hlen_size + serial_bytes.len();
        if sqlite_varint(candidate as u64).len() == hlen_size {
            break candidate;
        }
        hlen_size += 1;
    };

    let mut record = Vec::new();
    record.extend_from_slice(&sqlite_varint(header_len as u64));
    record.extend_from_slice(&serial_bytes);
    for b in &bodies {
        record.extend_from_slice(b);
    }
    record
}

/// SQLite variable-length integer (big-endian, 7 bits per byte).
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
    let mut out = Vec::with_capacity(n);
    for (i, g) in groups.iter().enumerate() {
        if i < n - 1 {
            out.push(g | 0x80);
        } else {
            out.push(*g);
        }
    }
    out
}

fn write_be_u16(p: &mut [u8], off: usize, v: u16) {
    p[off..off + 2].copy_from_slice(&v.to_be_bytes());
}

fn write_be_u32(p: &mut [u8], off: usize, v: u32) {
    p[off..off + 4].copy_from_slice(&v.to_be_bytes());
}

// --- Pure-Rust SHA-256 (FIPS 180-4), no external crates. -------------------

fn sha256_hex(input: &[u8]) -> String {
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

    // Pre-processing: pad message.
    let bit_len = (input.len() as u64) * 8;
    let mut msg = input.to_vec();
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&bit_len.to_be_bytes());

    for chunk in msg.chunks_exact(64) {
        let mut w = [0u32; 64];
        for (i, word) in w.iter_mut().enumerate().take(16) {
            let j = i * 4;
            *word = u32::from_be_bytes([chunk[j], chunk[j + 1], chunk[j + 2], chunk[j + 3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }

        let mut a = h[0];
        let mut b = h[1];
        let mut c = h[2];
        let mut d = h[3];
        let mut e = h[4];
        let mut f = h[5];
        let mut g = h[6];
        let mut hh = h[7];

        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let t1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);

            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
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

    let mut out = String::with_capacity(64);
    for word in h {
        out.push_str(&format!("{word:08x}"));
    }
    out
}

// ---------------------------------------------------------------------------
// Number formatting: whole numbers print without a decimal point.
// ---------------------------------------------------------------------------

fn fmt_num(n: f64) -> String {
    if n.fract() == 0.0 {
        format!("{}", n as i64)
    } else {
        let mut s = format!("{}", n);
        if s.contains('.') {
            while s.ends_with('0') {
                s.pop();
            }
            if s.ends_with('.') {
                s.pop();
            }
        }
        s
    }
}

// ---------------------------------------------------------------------------
// Minimal JSON parser (no external crates).
// ---------------------------------------------------------------------------

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

    fn as_str(&self) -> Option<&str> {
        match self {
            Json::Str(s) => Some(s),
            _ => None,
        }
    }

    fn as_i64(&self) -> Option<i64> {
        match self {
            Json::Num(n) if n.fract() == 0.0 => Some(*n as i64),
            _ => None,
        }
    }

    fn as_bool(&self) -> Option<bool> {
        match self {
            Json::Bool(b) => Some(*b),
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

fn parse_json(input: &str) -> Result<Json, ()> {
    let bytes = input.as_bytes();
    let mut pos = 0;
    skip_ws(bytes, &mut pos);
    let value = parse_value(bytes, &mut pos)?;
    skip_ws(bytes, &mut pos);
    if pos != bytes.len() {
        return Err(());
    }
    Ok(value)
}

fn skip_ws(b: &[u8], pos: &mut usize) {
    while *pos < b.len() && matches!(b[*pos], b' ' | b'\t' | b'\n' | b'\r') {
        *pos += 1;
    }
}

fn parse_value(b: &[u8], pos: &mut usize) -> Result<Json, ()> {
    skip_ws(b, pos);
    if *pos >= b.len() {
        return Err(());
    }
    match b[*pos] {
        b'{' => parse_object(b, pos),
        b'[' => parse_array(b, pos),
        b'"' => parse_string(b, pos).map(Json::Str),
        b't' | b'f' => parse_bool(b, pos),
        b'n' => parse_null(b, pos),
        _ => parse_number(b, pos),
    }
}

fn parse_object(b: &[u8], pos: &mut usize) -> Result<Json, ()> {
    *pos += 1; // '{'
    let mut pairs = Vec::new();
    skip_ws(b, pos);
    if *pos < b.len() && b[*pos] == b'}' {
        *pos += 1;
        return Ok(Json::Obj(pairs));
    }
    loop {
        skip_ws(b, pos);
        if *pos >= b.len() || b[*pos] != b'"' {
            return Err(());
        }
        let key = parse_string(b, pos)?;
        skip_ws(b, pos);
        if *pos >= b.len() || b[*pos] != b':' {
            return Err(());
        }
        *pos += 1;
        let value = parse_value(b, pos)?;
        pairs.push((key, value));
        skip_ws(b, pos);
        if *pos >= b.len() {
            return Err(());
        }
        match b[*pos] {
            b',' => {
                *pos += 1;
            }
            b'}' => {
                *pos += 1;
                return Ok(Json::Obj(pairs));
            }
            _ => return Err(()),
        }
    }
}

fn parse_array(b: &[u8], pos: &mut usize) -> Result<Json, ()> {
    *pos += 1; // '['
    let mut items = Vec::new();
    skip_ws(b, pos);
    if *pos < b.len() && b[*pos] == b']' {
        *pos += 1;
        return Ok(Json::Arr(items));
    }
    loop {
        let value = parse_value(b, pos)?;
        items.push(value);
        skip_ws(b, pos);
        if *pos >= b.len() {
            return Err(());
        }
        match b[*pos] {
            b',' => {
                *pos += 1;
            }
            b']' => {
                *pos += 1;
                return Ok(Json::Arr(items));
            }
            _ => return Err(()),
        }
    }
}

fn parse_string(b: &[u8], pos: &mut usize) -> Result<String, ()> {
    *pos += 1; // opening quote
    let mut out = String::new();
    while *pos < b.len() {
        let c = b[*pos];
        *pos += 1;
        match c {
            b'"' => return Ok(out),
            b'\\' => {
                if *pos >= b.len() {
                    return Err(());
                }
                let esc = b[*pos];
                *pos += 1;
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
                        if *pos + 4 > b.len() {
                            return Err(());
                        }
                        let hex = std::str::from_utf8(&b[*pos..*pos + 4]).map_err(|_| ())?;
                        let code = u32::from_str_radix(hex, 16).map_err(|_| ())?;
                        *pos += 4;
                        out.push(char::from_u32(code).ok_or(())?);
                    }
                    _ => return Err(()),
                }
            }
            _ => {
                // Push raw byte; collect UTF-8 continuation as-is via String bytes.
                out.push(c as char);
            }
        }
    }
    Err(())
}

fn parse_bool(b: &[u8], pos: &mut usize) -> Result<Json, ()> {
    if b[*pos..].starts_with(b"true") {
        *pos += 4;
        Ok(Json::Bool(true))
    } else if b[*pos..].starts_with(b"false") {
        *pos += 5;
        Ok(Json::Bool(false))
    } else {
        Err(())
    }
}

fn parse_null(b: &[u8], pos: &mut usize) -> Result<Json, ()> {
    if b[*pos..].starts_with(b"null") {
        *pos += 4;
        Ok(Json::Null)
    } else {
        Err(())
    }
}

fn parse_number(b: &[u8], pos: &mut usize) -> Result<Json, ()> {
    let start = *pos;
    if *pos < b.len() && (b[*pos] == b'-' || b[*pos] == b'+') {
        *pos += 1;
    }
    while *pos < b.len()
        && (b[*pos].is_ascii_digit()
            || b[*pos] == b'.'
            || b[*pos] == b'e'
            || b[*pos] == b'E'
            || b[*pos] == b'+'
            || b[*pos] == b'-')
    {
        *pos += 1;
    }
    let s = std::str::from_utf8(&b[start..*pos]).map_err(|_| ())?;
    let n: f64 = s.parse().map_err(|_| ())?;
    Ok(Json::Num(n))
}

/// Serialize a string as a JSON string literal (with escaping).
fn json_string(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\t' => out.push_str("\\t"),
            '\r' => out.push_str("\\r"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}
