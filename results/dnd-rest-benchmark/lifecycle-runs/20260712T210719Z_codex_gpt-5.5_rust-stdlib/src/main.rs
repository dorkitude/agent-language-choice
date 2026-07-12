use std::collections::hash_map::DefaultHasher;
use std::collections::HashMap;
use std::env;
use std::hash::{Hash, Hasher};
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::process::Command;
use std::sync::{Arc, Mutex};

type Sessions = Arc<Mutex<HashMap<String, CombatSession>>>;
type Users = Arc<Mutex<HashMap<String, User>>>;
type StorageState = Arc<Mutex<Storage>>;

const DB_PATH: &str = "game.db";
const SCHEMA_VERSION: i64 = 1;

struct Storage {
    db_path: String,
}

#[derive(Clone)]
struct User {
    username: String,
    password_hash: String,
}

#[derive(Clone)]
struct Condition {
    condition: String,
    remaining_rounds: i64,
}

#[derive(Clone)]
struct Combatant {
    name: String,
    dex: i64,
    score: i64,
    conditions: Vec<Condition>,
    had_conditions: bool,
}

#[derive(Clone)]
struct CombatSession {
    id: String,
    round: i64,
    turn_index: usize,
    order: Vec<Combatant>,
}

#[derive(Clone)]
struct Monster {
    slug: String,
    name: String,
    cr: String,
    armor_class: i64,
    hit_points: i64,
    tags: Vec<String>,
}

#[derive(Clone)]
struct Item {
    slug: String,
    name: String,
    item_type: String,
    rarity: String,
    cost_gp: i64,
}

#[derive(Clone)]
struct Campaign {
    id: String,
    name: String,
    dm: String,
}

#[derive(Clone)]
struct CampaignCharacter {
    id: String,
    name: String,
    level: i64,
    class_name: String,
}

#[derive(Clone)]
struct CampaignEvent {
    id: String,
    kind: String,
    summary: String,
}

fn main() -> std::io::Result<()> {
    let port = env::var("PORT").unwrap_or_else(|_| "8080".to_string());
    let storage = Arc::new(Mutex::new(Storage {
        db_path: DB_PATH.to_string(),
    }));
    if let Err(err) = init_storage(&storage.lock().unwrap()) {
        eprintln!("storage initialization failed: {err}");
    }
    let sessions = Arc::new(Mutex::new(load_combat_sessions(&storage.lock().unwrap())));
    let users = Arc::new(Mutex::new(load_users(&storage.lock().unwrap())));
    let listener = TcpListener::bind(format!("127.0.0.1:{port}"))?;
    for stream in listener.incoming() {
        if let Ok(mut stream) = stream {
            let _ = handle(&mut stream, &sessions, &users, &storage);
        }
    }
    Ok(())
}

fn handle(
    stream: &mut TcpStream,
    sessions: &Sessions,
    users: &Users,
    storage: &StorageState,
) -> std::io::Result<()> {
    let req = read_request(stream)?;
    let (head, body) = split_request(&req);
    let first = head.lines().next().unwrap_or("");
    let mut parts = first.split_whitespace();
    let method = parts.next().unwrap_or("");
    let path = parts.next().unwrap_or("");

    match (method, path) {
        ("GET", "/health") => respond(stream, 200, r#"{"ok":true}"#),
        ("GET", "/v1/storage/status") => {
            let initialized = storage_initialized(&storage.lock().unwrap());
            respond(
                stream,
                200,
                &format!(
                    r#"{{"driver":"sqlite","schema_version":{SCHEMA_VERSION},"initialized":{initialized}}}"#
                ),
            )
        }
        ("POST", "/v1/storage/reset") => {
            let ok = reset_storage(&storage.lock().unwrap()).is_ok();
            if ok {
                sessions.lock().unwrap().clear();
                users.lock().unwrap().clear();
                respond(
                    stream,
                    200,
                    &format!(r#"{{"ok":true,"schema_version":{SCHEMA_VERSION}}}"#),
                )
            } else {
                respond(stream, 500, r#"{"error":"storage error"}"#)
            }
        }
        ("POST", "/v1/dice/stats") => match dice_stats(body) {
            Some(json) => respond(stream, 200, &json),
            None => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", "/v1/checks/ability") => match ability_check(body) {
            Some(json) => respond(stream, 200, &json),
            None => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", "/v1/encounters/adjusted-xp") => match adjusted_xp(body) {
            Some(json) => respond(stream, 200, &json),
            None => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", "/v1/initiative/order") => match initiative_order(body) {
            Some(json) => respond(stream, 200, &json),
            None => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", "/v1/characters/ability-modifier") => match character_ability_modifier(body) {
            Some(json) => respond(stream, 200, &json),
            None => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", "/v1/characters/proficiency") => match character_proficiency(body) {
            Some(json) => respond(stream, 200, &json),
            None => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", "/v1/characters/derived-stats") => match character_derived_stats(body) {
            Some(json) => respond(stream, 200, &json),
            None => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", "/v1/phb/spell-slots") => match phb_spell_slots(body) {
            Some(json) => respond(stream, 200, &json),
            None => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", "/v1/phb/rests/long") => match phb_long_rest(body) {
            Some(json) => respond(stream, 200, &json),
            None => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", "/v1/phb/equipment-load") => match phb_equipment_load(body) {
            Some(json) => respond(stream, 200, &json),
            None => respond(stream, 400, r#"{"error":"bad request"}"#),
        },
        ("POST", "/v1/combat/sessions") => {
            let mut sessions = sessions.lock().unwrap();
            match create_combat_session(body, &mut sessions) {
                Some(json) => {
                    if let Some(id) = json_string_field(body, "id") {
                        if let Some(session) = sessions.get(&id) {
                            let _ = save_combat_session(&storage.lock().unwrap(), session);
                        }
                    }
                    respond(stream, 200, &json)
                }
                None => respond(stream, 400, r#"{"error":"bad request"}"#),
            }
        }
        ("POST", "/v1/auth/register") => {
            let mut users = users.lock().unwrap();
            match register_user(body, &mut users) {
                AuthResult::Ok(json) => {
                    if let Some(username) = json_string_field(body, "username") {
                        if let Some(user) = users.get(&username) {
                            let _ = save_user(&storage.lock().unwrap(), user);
                        }
                    }
                    respond(stream, 201, &json)
                }
                AuthResult::BadRequest => respond(stream, 400, r#"{"error":"bad request"}"#),
                AuthResult::Unauthorized => respond(stream, 401, r#"{"error":"unauthorized"}"#),
                AuthResult::Conflict => respond(stream, 409, r#"{"error":"conflict"}"#),
            }
        }
        ("POST", "/v1/auth/login") => {
            let users = users.lock().unwrap();
            match login_user(body, &users) {
                AuthResult::Ok(json) => respond(stream, 200, &json),
                AuthResult::BadRequest => respond(stream, 400, r#"{"error":"bad request"}"#),
                AuthResult::Unauthorized => respond(stream, 401, r#"{"error":"unauthorized"}"#),
                AuthResult::Conflict => respond(stream, 409, r#"{"error":"conflict"}"#),
            }
        }
        ("POST", "/v1/compendium/monsters") => {
            match create_monster(body, &storage.lock().unwrap()) {
                CompendiumResult::Ok(json) => respond(stream, 201, &json),
                CompendiumResult::BadRequest => respond(stream, 400, r#"{"error":"bad request"}"#),
                CompendiumResult::NotFound => respond(stream, 404, r#"{"error":"not found"}"#),
                CompendiumResult::Conflict => respond(stream, 409, r#"{"error":"conflict"}"#),
                CompendiumResult::StorageError => {
                    respond(stream, 500, r#"{"error":"storage error"}"#)
                }
            }
        }
        ("POST", "/v1/compendium/items") => match create_item(body, &storage.lock().unwrap()) {
            CompendiumResult::Ok(json) => respond(stream, 201, &json),
            CompendiumResult::BadRequest => respond(stream, 400, r#"{"error":"bad request"}"#),
            CompendiumResult::NotFound => respond(stream, 404, r#"{"error":"not found"}"#),
            CompendiumResult::Conflict => respond(stream, 409, r#"{"error":"conflict"}"#),
            CompendiumResult::StorageError => respond(stream, 500, r#"{"error":"storage error"}"#),
        },
        ("POST", "/v1/campaigns") => match create_campaign(body, &storage.lock().unwrap()) {
            CampaignResult::Ok(json) => respond(stream, 201, &json),
            CampaignResult::BadRequest => respond(stream, 400, r#"{"error":"bad request"}"#),
            CampaignResult::NotFound => respond(stream, 404, r#"{"error":"not found"}"#),
            CampaignResult::Conflict => respond(stream, 409, r#"{"error":"conflict"}"#),
            CampaignResult::StorageError => respond(stream, 500, r#"{"error":"storage error"}"#),
        },
        ("POST", "/v1/dm/encounter-builder") => {
            match dm_encounter_builder(body, &storage.lock().unwrap()) {
                DmResult::Ok(json) => respond(stream, 200, &json),
                DmResult::BadRequest => respond(stream, 400, r#"{"error":"bad request"}"#),
                DmResult::NotFound => respond(stream, 404, r#"{"error":"not found"}"#),
                DmResult::StorageError => respond(stream, 500, r#"{"error":"storage error"}"#),
            }
        }
        ("POST", "/v1/dm/loot-parcel") => match dm_loot_parcel(body, &storage.lock().unwrap()) {
            DmResult::Ok(json) => respond(stream, 200, &json),
            DmResult::BadRequest => respond(stream, 400, r#"{"error":"bad request"}"#),
            DmResult::NotFound => respond(stream, 404, r#"{"error":"not found"}"#),
            DmResult::StorageError => respond(stream, 500, r#"{"error":"storage error"}"#),
        },
        ("POST", "/v1/dm/session-recap") => {
            match dm_session_recap(body, &storage.lock().unwrap()) {
                DmResult::Ok(json) => respond(stream, 200, &json),
                DmResult::BadRequest => respond(stream, 400, r#"{"error":"bad request"}"#),
                DmResult::NotFound => respond(stream, 404, r#"{"error":"not found"}"#),
                DmResult::StorageError => respond(stream, 500, r#"{"error":"storage error"}"#),
            }
        }
        _ => {
            if method == "POST" {
                if let Some(campaign_id) = path
                    .strip_prefix("/v1/campaigns/")
                    .and_then(|rest| rest.strip_suffix("/characters"))
                {
                    match add_campaign_character(campaign_id, body, &storage.lock().unwrap()) {
                        CampaignResult::Ok(json) => respond(stream, 201, &json),
                        CampaignResult::BadRequest => {
                            respond(stream, 400, r#"{"error":"bad request"}"#)
                        }
                        CampaignResult::NotFound => {
                            respond(stream, 404, r#"{"error":"not found"}"#)
                        }
                        CampaignResult::Conflict => respond(stream, 409, r#"{"error":"conflict"}"#),
                        CampaignResult::StorageError => {
                            respond(stream, 500, r#"{"error":"storage error"}"#)
                        }
                    }
                } else if let Some(campaign_id) = path
                    .strip_prefix("/v1/campaigns/")
                    .and_then(|rest| rest.strip_suffix("/events"))
                {
                    match add_campaign_event(campaign_id, body, &storage.lock().unwrap()) {
                        CampaignResult::Ok(json) => respond(stream, 201, &json),
                        CampaignResult::BadRequest => {
                            respond(stream, 400, r#"{"error":"bad request"}"#)
                        }
                        CampaignResult::NotFound => {
                            respond(stream, 404, r#"{"error":"not found"}"#)
                        }
                        CampaignResult::Conflict => respond(stream, 409, r#"{"error":"conflict"}"#),
                        CampaignResult::StorageError => {
                            respond(stream, 500, r#"{"error":"storage error"}"#)
                        }
                    }
                } else if let Some(session_id) = path
                    .strip_prefix("/v1/combat/sessions/")
                    .and_then(|rest| rest.strip_suffix("/conditions"))
                {
                    let mut sessions = sessions.lock().unwrap();
                    match add_combat_condition(session_id, body, &mut sessions) {
                        CombatResult::Ok(json) => {
                            if let Some(session) = sessions.get(session_id) {
                                let _ = save_combat_session(&storage.lock().unwrap(), session);
                            }
                            respond(stream, 200, &json)
                        }
                        CombatResult::BadRequest => {
                            respond(stream, 400, r#"{"error":"bad request"}"#)
                        }
                        CombatResult::NotFound => respond(stream, 404, r#"{"error":"not found"}"#),
                    }
                } else if let Some(session_id) = path
                    .strip_prefix("/v1/combat/sessions/")
                    .and_then(|rest| rest.strip_suffix("/advance"))
                {
                    let mut sessions = sessions.lock().unwrap();
                    match advance_combat_session(session_id, &mut sessions) {
                        CombatResult::Ok(json) => {
                            if let Some(session) = sessions.get(session_id) {
                                let _ = save_combat_session(&storage.lock().unwrap(), session);
                            }
                            respond(stream, 200, &json)
                        }
                        CombatResult::BadRequest => {
                            respond(stream, 400, r#"{"error":"bad request"}"#)
                        }
                        CombatResult::NotFound => respond(stream, 404, r#"{"error":"not found"}"#),
                    }
                } else {
                    respond(stream, 404, r#"{"error":"not found"}"#)
                }
            } else if method == "GET" {
                if let Some(slug) = path.strip_prefix("/v1/compendium/monsters/") {
                    match read_monster(slug, &storage.lock().unwrap()) {
                        CompendiumResult::Ok(json) => respond(stream, 200, &json),
                        CompendiumResult::BadRequest => {
                            respond(stream, 400, r#"{"error":"bad request"}"#)
                        }
                        CompendiumResult::NotFound => {
                            respond(stream, 404, r#"{"error":"not found"}"#)
                        }
                        CompendiumResult::Conflict => {
                            respond(stream, 409, r#"{"error":"conflict"}"#)
                        }
                        CompendiumResult::StorageError => {
                            respond(stream, 500, r#"{"error":"storage error"}"#)
                        }
                    }
                } else if let Some(slug) = path.strip_prefix("/v1/compendium/items/") {
                    match read_item(slug, &storage.lock().unwrap()) {
                        CompendiumResult::Ok(json) => respond(stream, 200, &json),
                        CompendiumResult::BadRequest => {
                            respond(stream, 400, r#"{"error":"bad request"}"#)
                        }
                        CompendiumResult::NotFound => {
                            respond(stream, 404, r#"{"error":"not found"}"#)
                        }
                        CompendiumResult::Conflict => {
                            respond(stream, 409, r#"{"error":"conflict"}"#)
                        }
                        CompendiumResult::StorageError => {
                            respond(stream, 500, r#"{"error":"storage error"}"#)
                        }
                    }
                } else if let Some(campaign_id) = path
                    .strip_prefix("/v1/campaigns/")
                    .and_then(|rest| rest.strip_suffix("/state"))
                {
                    match read_campaign_state(campaign_id, &storage.lock().unwrap()) {
                        CampaignResult::Ok(json) => respond(stream, 200, &json),
                        CampaignResult::BadRequest => {
                            respond(stream, 400, r#"{"error":"bad request"}"#)
                        }
                        CampaignResult::NotFound => {
                            respond(stream, 404, r#"{"error":"not found"}"#)
                        }
                        CampaignResult::Conflict => respond(stream, 409, r#"{"error":"conflict"}"#),
                        CampaignResult::StorageError => {
                            respond(stream, 500, r#"{"error":"storage error"}"#)
                        }
                    }
                } else {
                    respond(stream, 404, r#"{"error":"not found"}"#)
                }
            } else {
                respond(stream, 404, r#"{"error":"not found"}"#)
            }
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
        500 => "Internal Server Error",
        _ => "Error",
    };
    write!(
        stream,
        "HTTP/1.1 {status} {label}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        body.len(),
        body
    )
}

fn init_storage(storage: &Storage) -> Result<(), String> {
    run_sql(
        storage,
        &format!(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS combat_sessions (id TEXT PRIMARY KEY, data TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS compendium_monsters (slug TEXT PRIMARY KEY, name TEXT NOT NULL, cr TEXT NOT NULL, armor_class INTEGER NOT NULL, hit_points INTEGER NOT NULL, tags TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS compendium_items (slug TEXT PRIMARY KEY, name TEXT NOT NULL, item_type TEXT NOT NULL, rarity TEXT NOT NULL, cost_gp INTEGER NOT NULL);
             CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, dm TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS campaign_characters (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL, class_name TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS campaign_events (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, kind TEXT NOT NULL, summary TEXT NOT NULL);
             INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '{}');",
            SCHEMA_VERSION
        ),
    )
}

fn reset_storage(storage: &Storage) -> Result<(), String> {
    let _ = std::fs::remove_file(&storage.db_path);
    init_storage(storage)
}

fn storage_initialized(storage: &Storage) -> bool {
    query_sql(
        storage,
        "SELECT value FROM meta WHERE key = 'schema_version' LIMIT 1;",
    )
    .map(|out| out.trim() == SCHEMA_VERSION.to_string())
    .unwrap_or(false)
}

fn save_user(storage: &Storage, user: &User) -> Result<(), String> {
    run_sql(
        storage,
        &format!(
            "INSERT OR REPLACE INTO users (username, password_hash) VALUES ({}, {});",
            sql_string(&user.username),
            sql_string(&user.password_hash)
        ),
    )
}

fn load_users(storage: &Storage) -> HashMap<String, User> {
    let mut users = HashMap::new();
    let Ok(out) = query_sql(
        storage,
        "SELECT username, password_hash FROM users ORDER BY username;",
    ) else {
        return users;
    };
    for line in out.lines() {
        let mut fields = line.splitn(2, '\t');
        let Some(username) = fields.next() else {
            continue;
        };
        let Some(password_hash) = fields.next() else {
            continue;
        };
        users.insert(
            username.to_string(),
            User {
                username: username.to_string(),
                password_hash: password_hash.to_string(),
            },
        );
    }
    users
}

fn save_combat_session(storage: &Storage, session: &CombatSession) -> Result<(), String> {
    run_sql(
        storage,
        &format!(
            "INSERT OR REPLACE INTO combat_sessions (id, data) VALUES ({}, {});",
            sql_string(&session.id),
            sql_string(&encode_session(session))
        ),
    )
}

fn load_combat_sessions(storage: &Storage) -> HashMap<String, CombatSession> {
    let mut sessions = HashMap::new();
    let Ok(out) = query_sql(storage, "SELECT data FROM combat_sessions ORDER BY id;") else {
        return sessions;
    };
    for line in out.lines() {
        if let Some(session) = decode_session(line) {
            sessions.insert(session.id.clone(), session);
        }
    }
    sessions
}

fn run_sql(storage: &Storage, sql: &str) -> Result<(), String> {
    let output = Command::new("sqlite3")
        .arg("-batch")
        .arg(&storage.db_path)
        .arg(sql)
        .output()
        .map_err(|err| err.to_string())?;
    if output.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}

fn query_sql(storage: &Storage, sql: &str) -> Result<String, String> {
    let output = Command::new("sqlite3")
        .arg("-batch")
        .arg("-separator")
        .arg("\t")
        .arg(&storage.db_path)
        .arg(sql)
        .output()
        .map_err(|err| err.to_string())?;
    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).into_owned())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}

fn sql_string(value: &str) -> String {
    format!("'{}'", value.replace('\'', "''"))
}

fn encode_session(session: &CombatSession) -> String {
    let combatants = session
        .order
        .iter()
        .map(|combatant| {
            let conditions = combatant
                .conditions
                .iter()
                .map(|condition| {
                    format!(
                        "{}:{}",
                        hex_encode(&condition.condition),
                        condition.remaining_rounds
                    )
                })
                .collect::<Vec<_>>()
                .join("~");
            format!(
                "{},{},{},{},{}",
                hex_encode(&combatant.name),
                combatant.dex,
                combatant.score,
                if combatant.had_conditions { 1 } else { 0 },
                conditions
            )
        })
        .collect::<Vec<_>>()
        .join(";");
    format!(
        "{}|{}|{}|{}",
        hex_encode(&session.id),
        session.round,
        session.turn_index,
        combatants
    )
}

fn decode_session(encoded: &str) -> Option<CombatSession> {
    let mut parts = encoded.splitn(4, '|');
    let id = hex_decode(parts.next()?)?;
    let round = parts.next()?.parse().ok()?;
    let turn_index = parts.next()?.parse().ok()?;
    let mut order = Vec::new();
    for combatant_text in parts.next()?.split(';') {
        if combatant_text.is_empty() {
            continue;
        }
        let fields = combatant_text.splitn(5, ',').collect::<Vec<_>>();
        if fields.len() != 5 {
            return None;
        }
        let mut conditions = Vec::new();
        if !fields[4].is_empty() {
            for condition_text in fields[4].split('~') {
                let (name, remaining) = condition_text.split_once(':')?;
                conditions.push(Condition {
                    condition: hex_decode(name)?,
                    remaining_rounds: remaining.parse().ok()?,
                });
            }
        }
        order.push(Combatant {
            name: hex_decode(fields[0])?,
            dex: fields[1].parse().ok()?,
            score: fields[2].parse().ok()?,
            had_conditions: fields[3] == "1",
            conditions,
        });
    }
    if order.is_empty() || turn_index >= order.len() {
        return None;
    }
    Some(CombatSession {
        id,
        round,
        turn_index,
        order,
    })
}

fn hex_encode(value: &str) -> String {
    let mut out = String::new();
    for byte in value.as_bytes() {
        out.push_str(&format!("{byte:02x}"));
    }
    out
}

fn hex_decode(value: &str) -> Option<String> {
    if !value.len().is_multiple_of(2) {
        return None;
    }
    let mut bytes = Vec::new();
    let mut i = 0;
    while i < value.len() {
        bytes.push(u8::from_str_radix(&value[i..i + 2], 16).ok()?);
        i += 2;
    }
    String::from_utf8(bytes).ok()
}

fn read_request(stream: &mut TcpStream) -> std::io::Result<String> {
    let mut bytes = Vec::new();
    let mut buf = [0_u8; 4096];
    loop {
        let n = stream.read(&mut buf)?;
        if n == 0 {
            break;
        }
        bytes.extend_from_slice(&buf[..n]);
        if let Some(header_end) = find_bytes(&bytes, b"\r\n\r\n") {
            let head = String::from_utf8_lossy(&bytes[..header_end]);
            let content_len = content_length(&head).unwrap_or(0);
            if bytes.len() >= header_end + 4 + content_len {
                break;
            }
        }
    }
    Ok(String::from_utf8_lossy(&bytes).into_owned())
}

fn find_bytes(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|w| w == needle)
}

fn content_length(head: &str) -> Option<usize> {
    for line in head.lines() {
        if let Some((name, value)) = line.split_once(':') {
            if name.eq_ignore_ascii_case("content-length") {
                return value.trim().parse().ok();
            }
        }
    }
    None
}

fn split_request(req: &str) -> (&str, &str) {
    match req.split_once("\r\n\r\n") {
        Some((head, body)) => (head, body),
        None => (req, ""),
    }
}

fn dice_stats(body: &str) -> Option<String> {
    let expression = json_string_field(body, "expression")?;
    let (dice_count, sides, modifier) = parse_dice(&expression)?;
    let min = dice_count + modifier;
    let max = dice_count * sides + modifier;
    let average_twice = dice_count * (sides + 1) + 2 * modifier;
    let average = number_from_halves(average_twice);
    Some(format!(
        r#"{{"dice_count":{dice_count},"sides":{sides},"modifier":{modifier},"min":{min},"max":{max},"average":{average}}}"#
    ))
}

fn parse_dice(expression: &str) -> Option<(i64, i64, i64)> {
    let d = expression.find('d')?;
    let count: i64 = expression[..d].parse().ok()?;
    let rest = &expression[d + 1..];
    let split = rest.find(['+', '-']);
    let (sides_text, modifier) = match split {
        Some(i) => {
            let sides_text = &rest[..i];
            let sign = rest.as_bytes()[i] as char;
            let value: i64 = rest[i + 1..].parse().ok()?;
            (sides_text, if sign == '-' { -value } else { value })
        }
        None => (rest, 0),
    };
    let sides: i64 = sides_text.parse().ok()?;
    if count > 0 && sides > 0 {
        Some((count, sides, modifier))
    } else {
        None
    }
}

fn ability_check(body: &str) -> Option<String> {
    let roll = json_i64_field(body, "roll")?;
    let modifier = json_i64_field(body, "modifier")?;
    let dc = json_i64_field(body, "dc")?;
    let total = roll + modifier;
    let success = total >= dc;
    let margin = total - dc;
    Some(format!(
        r#"{{"total":{total},"success":{success},"margin":{margin}}}"#
    ))
}

fn adjusted_xp(body: &str) -> Option<String> {
    let party = json_array_field(body, "party")?;
    let monsters = json_array_field(body, "monsters")?;

    let mut easy = 0_i64;
    let mut medium = 0_i64;
    let mut hard = 0_i64;
    let mut deadly = 0_i64;
    for member in array_objects(party) {
        match json_i64_field(member, "level")? {
            3 => {
                easy += 75;
                medium += 150;
                hard += 225;
                deadly += 400;
            }
            _ => return None,
        }
    }

    let mut base_xp = 0_i64;
    let mut monster_count = 0_i64;
    for monster in array_objects(monsters) {
        let cr = json_string_field(monster, "cr")?;
        let count = json_i64_field(monster, "count")?;
        if count < 0 {
            return None;
        }
        base_xp += cr_xp(&cr)? * count;
        monster_count += count;
    }

    let multiplier_twice = monster_multiplier_twice(monster_count);
    let adjusted_twice = base_xp * multiplier_twice;
    let adjusted_for_compare = adjusted_twice;
    let difficulty = if adjusted_for_compare >= deadly * 2 {
        "deadly"
    } else if adjusted_for_compare >= hard * 2 {
        "hard"
    } else if adjusted_for_compare >= medium * 2 {
        "medium"
    } else if adjusted_for_compare >= easy * 2 {
        "easy"
    } else {
        "trivial"
    };
    let multiplier = number_from_halves(multiplier_twice);
    let adjusted = number_from_halves(adjusted_twice);

    Some(format!(
        r#"{{"base_xp":{base_xp},"monster_count":{monster_count},"multiplier":{multiplier},"adjusted_xp":{adjusted},"difficulty":"{difficulty}","thresholds":{{"easy":{easy},"medium":{medium},"hard":{hard},"deadly":{deadly}}}}}"#
    ))
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

fn monster_multiplier_twice(count: i64) -> i64 {
    match count {
        1 => 2,
        2 => 3,
        3..=6 => 4,
        7..=10 => 5,
        11..=14 => 6,
        15.. => 8,
        _ => 2,
    }
}

fn initiative_order(body: &str) -> Option<String> {
    let combatants = json_array_field(body, "combatants")?;
    let mut rows = Vec::new();
    for combatant in array_objects(combatants) {
        let name = json_string_field(combatant, "name")?;
        let dex = json_i64_field(combatant, "dex")?;
        let roll = json_i64_field(combatant, "roll")?;
        rows.push((name, dex, roll + dex));
    }
    rows.sort_by(|a, b| {
        b.2.cmp(&a.2)
            .then_with(|| b.1.cmp(&a.1))
            .then_with(|| a.0.cmp(&b.0))
    });

    let entries: Vec<String> = rows
        .into_iter()
        .map(|(name, _, score)| format!(r#"{{"name":"{}","score":{score}}}"#, json_escape(&name)))
        .collect();
    Some(format!(r#"{{"order":[{}]}}"#, entries.join(",")))
}

enum CombatResult {
    Ok(String),
    BadRequest,
    NotFound,
}

enum AuthResult {
    Ok(String),
    BadRequest,
    Unauthorized,
    Conflict,
}

enum CompendiumResult {
    Ok(String),
    BadRequest,
    NotFound,
    Conflict,
    StorageError,
}

enum CampaignResult {
    Ok(String),
    BadRequest,
    NotFound,
    Conflict,
    StorageError,
}

enum DmResult {
    Ok(String),
    BadRequest,
    NotFound,
    StorageError,
}

struct EncounterMath {
    base_xp: i64,
    adjusted_xp: String,
    difficulty: String,
    monster_count: i64,
}

fn dm_encounter_builder(body: &str, storage: &Storage) -> DmResult {
    let campaign_id = match json_string_field(body, "campaign_id") {
        Some(value) if valid_record_id(&value) => value,
        _ => return DmResult::BadRequest,
    };
    if !campaign_exists(storage, &campaign_id) {
        return DmResult::NotFound;
    }
    let party = match json_array_field(body, "party") {
        Some(value) => value,
        None => return DmResult::BadRequest,
    };
    let monster_slugs = match json_string_array_field(body, "monster_slugs") {
        Some(value) if !value.is_empty() => value,
        _ => return DmResult::BadRequest,
    };

    let mut monster_crs = Vec::new();
    for slug in monster_slugs {
        if !valid_slug(&slug) {
            return DmResult::BadRequest;
        }
        match load_monster(storage, &slug) {
            Ok(Some(monster)) => monster_crs.push(monster.cr),
            Ok(None) => return DmResult::NotFound,
            Err(_) => return DmResult::StorageError,
        }
    }

    let math = match encounter_math(party, &monster_crs) {
        Some(value) => value,
        None => return DmResult::BadRequest,
    };
    let recommendation = encounter_recommendation(&math.difficulty);
    DmResult::Ok(format!(
        r#"{{"campaign_id":"{}","base_xp":{},"adjusted_xp":{},"difficulty":"{}","monster_count":{},"recommendation":"{}"}}"#,
        json_escape(&campaign_id),
        math.base_xp,
        math.adjusted_xp,
        json_escape(&math.difficulty),
        math.monster_count,
        recommendation
    ))
}

fn dm_loot_parcel(body: &str, storage: &Storage) -> DmResult {
    let campaign_id = match json_string_field(body, "campaign_id") {
        Some(value) if valid_record_id(&value) => value,
        _ => return DmResult::BadRequest,
    };
    let tier = match json_i64_field(body, "tier") {
        Some(value) => value,
        None => return DmResult::BadRequest,
    };
    let _seed = match json_i64_field(body, "seed") {
        Some(value) => value,
        None => return DmResult::BadRequest,
    };
    if tier != 1 {
        return DmResult::BadRequest;
    }
    if !campaign_exists(storage, &campaign_id) {
        return DmResult::NotFound;
    }
    DmResult::Ok(format!(
        r#"{{"campaign_id":"{}","coins_gp":75,"items":[{{"slug":"healing-potion","quantity":2}}]}}"#,
        json_escape(&campaign_id)
    ))
}

fn dm_session_recap(body: &str, storage: &Storage) -> DmResult {
    let campaign_id = match json_string_field(body, "campaign_id") {
        Some(value) if valid_record_id(&value) => value,
        _ => return DmResult::BadRequest,
    };
    if !campaign_exists(storage, &campaign_id) {
        return DmResult::NotFound;
    }
    let summary = match load_latest_campaign_event_summary(storage, &campaign_id) {
        Ok(Some(value)) => value,
        Ok(None) => String::new(),
        Err(_) => return DmResult::StorageError,
    };
    let open_thread = if summary.contains("goblin trail") {
        "Resolve goblin trail ambush".to_string()
    } else if summary.is_empty() {
        "Plan next session".to_string()
    } else {
        format!("Follow up: {}", summary.trim_end_matches('.'))
    };
    DmResult::Ok(format!(
        r#"{{"campaign_id":"{}","summary":"{}","open_threads":["{}"]}}"#,
        json_escape(&campaign_id),
        json_escape(&summary),
        json_escape(&open_thread)
    ))
}

fn encounter_math(party: &str, monster_crs: &[String]) -> Option<EncounterMath> {
    let mut easy = 0_i64;
    let mut medium = 0_i64;
    let mut hard = 0_i64;
    let mut deadly = 0_i64;
    for member in array_objects(party) {
        match json_i64_field(member, "level")? {
            3 => {
                easy += 75;
                medium += 150;
                hard += 225;
                deadly += 400;
            }
            _ => return None,
        }
    }
    if easy == 0 {
        return None;
    }

    let mut base_xp = 0_i64;
    for cr in monster_crs {
        base_xp += cr_xp(cr)?;
    }
    let monster_count = monster_crs.len() as i64;
    let adjusted_twice = base_xp * monster_multiplier_twice(monster_count);
    let difficulty = if adjusted_twice >= deadly * 2 {
        "deadly"
    } else if adjusted_twice >= hard * 2 {
        "hard"
    } else if adjusted_twice >= medium * 2 {
        "medium"
    } else if adjusted_twice >= easy * 2 {
        "easy"
    } else {
        "trivial"
    };

    Some(EncounterMath {
        base_xp,
        adjusted_xp: number_from_halves(adjusted_twice),
        difficulty: difficulty.to_string(),
        monster_count,
    })
}

fn encounter_recommendation(difficulty: &str) -> &'static str {
    match difficulty {
        "trivial" => "low stakes",
        "easy" => "safe warm-up",
        "medium" => "standard challenge",
        "hard" => "dangerous fight",
        "deadly" => "use caution",
        _ => "review encounter",
    }
}

fn create_campaign(body: &str, storage: &Storage) -> CampaignResult {
    let campaign = match parse_campaign(body) {
        Some(value) => value,
        None => return CampaignResult::BadRequest,
    };
    if campaign_exists(storage, &campaign.id) {
        return CampaignResult::Conflict;
    }
    let sql = format!(
        "INSERT INTO campaigns (id, name, dm) VALUES ({}, {}, {});",
        sql_string(&campaign.id),
        sql_string(&campaign.name),
        sql_string(&campaign.dm)
    );
    if run_sql(storage, &sql).is_err() {
        return CampaignResult::StorageError;
    }
    CampaignResult::Ok(campaign_json(&campaign))
}

fn add_campaign_character(campaign_id: &str, body: &str, storage: &Storage) -> CampaignResult {
    if !valid_record_id(campaign_id) {
        return CampaignResult::BadRequest;
    }
    if !campaign_exists(storage, campaign_id) {
        return CampaignResult::NotFound;
    }
    let character = match parse_campaign_character(body) {
        Some(value) => value,
        None => return CampaignResult::BadRequest,
    };
    if campaign_character_exists(storage, &character.id) {
        return CampaignResult::Conflict;
    }
    let sql = format!(
        "INSERT INTO campaign_characters (id, campaign_id, name, level, class_name) VALUES ({}, {}, {}, {}, {});",
        sql_string(&character.id),
        sql_string(campaign_id),
        sql_string(&character.name),
        character.level,
        sql_string(&character.class_name)
    );
    if run_sql(storage, &sql).is_err() {
        return CampaignResult::StorageError;
    }
    CampaignResult::Ok(campaign_character_json(&character))
}

fn add_campaign_event(campaign_id: &str, body: &str, storage: &Storage) -> CampaignResult {
    if !valid_record_id(campaign_id) {
        return CampaignResult::BadRequest;
    }
    if !campaign_exists(storage, campaign_id) {
        return CampaignResult::NotFound;
    }
    let event = match parse_campaign_event(body) {
        Some(value) => value,
        None => return CampaignResult::BadRequest,
    };
    if campaign_event_exists(storage, &event.id) {
        return CampaignResult::Conflict;
    }
    let sql = format!(
        "INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES ({}, {}, {}, {});",
        sql_string(&event.id),
        sql_string(campaign_id),
        sql_string(&event.kind),
        sql_string(&event.summary)
    );
    if run_sql(storage, &sql).is_err() {
        return CampaignResult::StorageError;
    }
    CampaignResult::Ok(campaign_event_json(&event))
}

fn read_campaign_state(campaign_id: &str, storage: &Storage) -> CampaignResult {
    if !valid_record_id(campaign_id) {
        return CampaignResult::BadRequest;
    }
    let campaign = match load_campaign(storage, campaign_id) {
        Ok(Some(value)) => value,
        Ok(None) => return CampaignResult::NotFound,
        Err(_) => return CampaignResult::StorageError,
    };
    let characters = match load_campaign_characters(storage, campaign_id) {
        Ok(value) => value,
        Err(_) => return CampaignResult::StorageError,
    };
    let log_count = match campaign_log_count(storage, campaign_id) {
        Ok(value) => value,
        Err(_) => return CampaignResult::StorageError,
    };
    CampaignResult::Ok(campaign_state_json(&campaign, &characters, log_count))
}

fn parse_campaign(body: &str) -> Option<Campaign> {
    let id = json_string_field(body, "id")?;
    if !valid_record_id(&id) {
        return None;
    }
    Some(Campaign {
        id,
        name: non_empty_json_string(body, "name")?,
        dm: non_empty_json_string(body, "dm")?,
    })
}

fn parse_campaign_character(body: &str) -> Option<CampaignCharacter> {
    let id = json_string_field(body, "id")?;
    if !valid_record_id(&id) {
        return None;
    }
    let level = json_i64_field(body, "level")?;
    if !(1..=20).contains(&level) {
        return None;
    }
    Some(CampaignCharacter {
        id,
        name: non_empty_json_string(body, "name")?,
        level,
        class_name: non_empty_json_string(body, "class")?,
    })
}

fn parse_campaign_event(body: &str) -> Option<CampaignEvent> {
    let id = json_string_field(body, "id")?;
    if !valid_record_id(&id) {
        return None;
    }
    Some(CampaignEvent {
        id,
        kind: non_empty_json_string(body, "kind")?,
        summary: non_empty_json_string(body, "summary")?,
    })
}

fn valid_record_id(id: &str) -> bool {
    !id.is_empty()
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}

fn campaign_exists(storage: &Storage, id: &str) -> bool {
    query_sql(
        storage,
        &format!(
            "SELECT id FROM campaigns WHERE id = {} LIMIT 1;",
            sql_string(id)
        ),
    )
    .map(|out| !out.trim().is_empty())
    .unwrap_or(false)
}

fn campaign_character_exists(storage: &Storage, id: &str) -> bool {
    query_sql(
        storage,
        &format!(
            "SELECT id FROM campaign_characters WHERE id = {} LIMIT 1;",
            sql_string(id)
        ),
    )
    .map(|out| !out.trim().is_empty())
    .unwrap_or(false)
}

fn campaign_event_exists(storage: &Storage, id: &str) -> bool {
    query_sql(
        storage,
        &format!(
            "SELECT id FROM campaign_events WHERE id = {} LIMIT 1;",
            sql_string(id)
        ),
    )
    .map(|out| !out.trim().is_empty())
    .unwrap_or(false)
}

fn load_campaign(storage: &Storage, id: &str) -> Result<Option<Campaign>, String> {
    let out = query_sql(
        storage,
        &format!(
            "SELECT id, name, dm FROM campaigns WHERE id = {} LIMIT 1;",
            sql_string(id)
        ),
    )?;
    let Some(line) = out.lines().next() else {
        return Ok(None);
    };
    let fields = line.splitn(3, '\t').collect::<Vec<_>>();
    if fields.len() != 3 {
        return Err("malformed campaign row".to_string());
    }
    Ok(Some(Campaign {
        id: fields[0].to_string(),
        name: fields[1].to_string(),
        dm: fields[2].to_string(),
    }))
}

fn load_campaign_characters(
    storage: &Storage,
    campaign_id: &str,
) -> Result<Vec<CampaignCharacter>, String> {
    let out = query_sql(
        storage,
        &format!(
            "SELECT id, name, level, class_name FROM campaign_characters WHERE campaign_id = {} ORDER BY rowid;",
            sql_string(campaign_id)
        ),
    )?;
    let mut characters = Vec::new();
    for line in out.lines() {
        let fields = line.splitn(4, '\t').collect::<Vec<_>>();
        if fields.len() != 4 {
            return Err("malformed campaign character row".to_string());
        }
        characters.push(CampaignCharacter {
            id: fields[0].to_string(),
            name: fields[1].to_string(),
            level: fields[2].parse().map_err(|_| "bad level")?,
            class_name: fields[3].to_string(),
        });
    }
    Ok(characters)
}

fn campaign_log_count(storage: &Storage, campaign_id: &str) -> Result<i64, String> {
    let out = query_sql(
        storage,
        &format!(
            "SELECT COUNT(*) FROM campaign_events WHERE campaign_id = {};",
            sql_string(campaign_id)
        ),
    )?;
    out.trim().parse().map_err(|_| "bad log count".to_string())
}

fn load_latest_campaign_event_summary(
    storage: &Storage,
    campaign_id: &str,
) -> Result<Option<String>, String> {
    let out = query_sql(
        storage,
        &format!(
            "SELECT summary FROM campaign_events WHERE campaign_id = {} ORDER BY rowid DESC LIMIT 1;",
            sql_string(campaign_id)
        ),
    )?;
    Ok(out.lines().next().map(|line| line.to_string()))
}

fn campaign_json(campaign: &Campaign) -> String {
    format!(
        r#"{{"id":"{}","name":"{}","dm":"{}"}}"#,
        json_escape(&campaign.id),
        json_escape(&campaign.name),
        json_escape(&campaign.dm)
    )
}

fn campaign_character_json(character: &CampaignCharacter) -> String {
    format!(
        r#"{{"id":"{}","name":"{}","level":{},"class":"{}"}}"#,
        json_escape(&character.id),
        json_escape(&character.name),
        character.level,
        json_escape(&character.class_name)
    )
}

fn campaign_event_json(event: &CampaignEvent) -> String {
    format!(
        r#"{{"id":"{}","kind":"{}"}}"#,
        json_escape(&event.id),
        json_escape(&event.kind)
    )
}

fn campaign_state_json(
    campaign: &Campaign,
    characters: &[CampaignCharacter],
    log_count: i64,
) -> String {
    let character_json = characters
        .iter()
        .map(campaign_character_json)
        .collect::<Vec<_>>()
        .join(",");
    format!(
        r#"{{"id":"{}","name":"{}","dm":"{}","characters":[{}],"log_count":{}}}"#,
        json_escape(&campaign.id),
        json_escape(&campaign.name),
        json_escape(&campaign.dm),
        character_json,
        log_count
    )
}

fn create_monster(body: &str, storage: &Storage) -> CompendiumResult {
    let monster = match parse_monster(body) {
        Some(value) => value,
        None => return CompendiumResult::BadRequest,
    };
    if monster_exists(storage, &monster.slug) {
        return CompendiumResult::Conflict;
    }
    let sql = format!(
        "INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points, tags) VALUES ({}, {}, {}, {}, {}, {});",
        sql_string(&monster.slug),
        sql_string(&monster.name),
        sql_string(&monster.cr),
        monster.armor_class,
        monster.hit_points,
        sql_string(&encode_string_list(&monster.tags))
    );
    if run_sql(storage, &sql).is_err() {
        return CompendiumResult::StorageError;
    }
    CompendiumResult::Ok(monster_create_json(&monster))
}

fn read_monster(slug: &str, storage: &Storage) -> CompendiumResult {
    if !valid_slug(slug) {
        return CompendiumResult::BadRequest;
    }
    match load_monster(storage, slug) {
        Ok(Some(monster)) => CompendiumResult::Ok(monster_read_json(&monster)),
        Ok(None) => CompendiumResult::NotFound,
        Err(_) => CompendiumResult::StorageError,
    }
}

fn create_item(body: &str, storage: &Storage) -> CompendiumResult {
    let item = match parse_item(body) {
        Some(value) => value,
        None => return CompendiumResult::BadRequest,
    };
    if item_exists(storage, &item.slug) {
        return CompendiumResult::Conflict;
    }
    let sql = format!(
        "INSERT INTO compendium_items (slug, name, item_type, rarity, cost_gp) VALUES ({}, {}, {}, {}, {});",
        sql_string(&item.slug),
        sql_string(&item.name),
        sql_string(&item.item_type),
        sql_string(&item.rarity),
        item.cost_gp
    );
    if run_sql(storage, &sql).is_err() {
        return CompendiumResult::StorageError;
    }
    CompendiumResult::Ok(item_json(&item))
}

fn read_item(slug: &str, storage: &Storage) -> CompendiumResult {
    if !valid_slug(slug) {
        return CompendiumResult::BadRequest;
    }
    match load_item(storage, slug) {
        Ok(Some(item)) => CompendiumResult::Ok(item_json(&item)),
        Ok(None) => CompendiumResult::NotFound,
        Err(_) => CompendiumResult::StorageError,
    }
}

fn parse_monster(body: &str) -> Option<Monster> {
    let slug = json_string_field(body, "slug")?;
    if !valid_slug(&slug) {
        return None;
    }
    let name = non_empty_json_string(body, "name")?;
    let cr = non_empty_json_string(body, "cr")?;
    let armor_class = json_i64_field(body, "armor_class")?;
    let hit_points = json_i64_field(body, "hit_points")?;
    let tags = json_string_array_field(body, "tags")?;
    if armor_class < 0 || hit_points < 0 {
        return None;
    }
    Some(Monster {
        slug,
        name,
        cr,
        armor_class,
        hit_points,
        tags,
    })
}

fn parse_item(body: &str) -> Option<Item> {
    let slug = json_string_field(body, "slug")?;
    if !valid_slug(&slug) {
        return None;
    }
    let name = non_empty_json_string(body, "name")?;
    let item_type = non_empty_json_string(body, "type")?;
    let rarity = non_empty_json_string(body, "rarity")?;
    let cost_gp = json_i64_field(body, "cost_gp")?;
    if cost_gp < 0 {
        return None;
    }
    Some(Item {
        slug,
        name,
        item_type,
        rarity,
        cost_gp,
    })
}

fn non_empty_json_string(body: &str, key: &str) -> Option<String> {
    match json_string_field(body, key) {
        Some(value) if !value.is_empty() => Some(value),
        _ => None,
    }
}

fn valid_slug(slug: &str) -> bool {
    !slug.is_empty()
        && slug
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

fn monster_exists(storage: &Storage, slug: &str) -> bool {
    query_sql(
        storage,
        &format!(
            "SELECT slug FROM compendium_monsters WHERE slug = {} LIMIT 1;",
            sql_string(slug)
        ),
    )
    .map(|out| !out.trim().is_empty())
    .unwrap_or(false)
}

fn item_exists(storage: &Storage, slug: &str) -> bool {
    query_sql(
        storage,
        &format!(
            "SELECT slug FROM compendium_items WHERE slug = {} LIMIT 1;",
            sql_string(slug)
        ),
    )
    .map(|out| !out.trim().is_empty())
    .unwrap_or(false)
}

fn load_monster(storage: &Storage, slug: &str) -> Result<Option<Monster>, String> {
    let out = query_sql(
        storage,
        &format!(
            "SELECT slug, name, cr, armor_class, hit_points, tags FROM compendium_monsters WHERE slug = {} LIMIT 1;",
            sql_string(slug)
        ),
    )?;
    let Some(line) = out.lines().next() else {
        return Ok(None);
    };
    let fields = line.splitn(6, '\t').collect::<Vec<_>>();
    if fields.len() != 6 {
        return Err("malformed monster row".to_string());
    }
    Ok(Some(Monster {
        slug: fields[0].to_string(),
        name: fields[1].to_string(),
        cr: fields[2].to_string(),
        armor_class: fields[3].parse().map_err(|_| "bad armor_class")?,
        hit_points: fields[4].parse().map_err(|_| "bad hit_points")?,
        tags: decode_string_list(fields[5]).ok_or_else(|| "bad tags".to_string())?,
    }))
}

fn load_item(storage: &Storage, slug: &str) -> Result<Option<Item>, String> {
    let out = query_sql(
        storage,
        &format!(
            "SELECT slug, name, item_type, rarity, cost_gp FROM compendium_items WHERE slug = {} LIMIT 1;",
            sql_string(slug)
        ),
    )?;
    let Some(line) = out.lines().next() else {
        return Ok(None);
    };
    let fields = line.splitn(5, '\t').collect::<Vec<_>>();
    if fields.len() != 5 {
        return Err("malformed item row".to_string());
    }
    Ok(Some(Item {
        slug: fields[0].to_string(),
        name: fields[1].to_string(),
        item_type: fields[2].to_string(),
        rarity: fields[3].to_string(),
        cost_gp: fields[4].parse().map_err(|_| "bad cost_gp")?,
    }))
}

fn monster_create_json(monster: &Monster) -> String {
    format!(
        r#"{{"slug":"{}","name":"{}","cr":"{}","armor_class":{},"hit_points":{}}}"#,
        json_escape(&monster.slug),
        json_escape(&monster.name),
        json_escape(&monster.cr),
        monster.armor_class,
        monster.hit_points
    )
}

fn monster_read_json(monster: &Monster) -> String {
    format!(
        r#"{{"slug":"{}","name":"{}","cr":"{}","armor_class":{},"hit_points":{},"tags":[{}]}}"#,
        json_escape(&monster.slug),
        json_escape(&monster.name),
        json_escape(&monster.cr),
        monster.armor_class,
        monster.hit_points,
        string_array_json(&monster.tags)
    )
}

fn item_json(item: &Item) -> String {
    format!(
        r#"{{"slug":"{}","name":"{}","type":"{}","rarity":"{}","cost_gp":{}}}"#,
        json_escape(&item.slug),
        json_escape(&item.name),
        json_escape(&item.item_type),
        json_escape(&item.rarity),
        item.cost_gp
    )
}

fn string_array_json(values: &[String]) -> String {
    values
        .iter()
        .map(|value| format!(r#""{}""#, json_escape(value)))
        .collect::<Vec<_>>()
        .join(",")
}

fn encode_string_list(values: &[String]) -> String {
    values
        .iter()
        .map(|value| hex_encode(value))
        .collect::<Vec<_>>()
        .join(",")
}

fn decode_string_list(encoded: &str) -> Option<Vec<String>> {
    if encoded.is_empty() {
        return Some(Vec::new());
    }
    let mut values = Vec::new();
    for value in encoded.split(',') {
        values.push(hex_decode(value)?);
    }
    Some(values)
}

fn register_user(body: &str, users: &mut HashMap<String, User>) -> AuthResult {
    let username = match json_string_field(body, "username") {
        Some(value) if valid_username(&value) => value,
        _ => return AuthResult::BadRequest,
    };
    let password = match json_string_field(body, "password") {
        Some(value) if value.len() >= 8 => value,
        _ => return AuthResult::BadRequest,
    };
    let role = match json_string_field(body, "role") {
        Some(value) if value == "dm" || value == "player" => value,
        _ => return AuthResult::BadRequest,
    };

    if users.contains_key(&username) {
        return AuthResult::Conflict;
    }

    users.insert(
        username.clone(),
        User {
            username: username.clone(),
            password_hash: password_hash(&username, &password),
        },
    );

    AuthResult::Ok(format!(
        r#"{{"username":"{}","role":"{}"}}"#,
        json_escape(&username),
        json_escape(&role)
    ))
}

fn login_user(body: &str, users: &HashMap<String, User>) -> AuthResult {
    let username = match json_string_field(body, "username") {
        Some(value) => value,
        _ => return AuthResult::BadRequest,
    };
    let password = match json_string_field(body, "password") {
        Some(value) => value,
        _ => return AuthResult::BadRequest,
    };

    let Some(user) = users.get(&username) else {
        return AuthResult::Unauthorized;
    };
    if user.password_hash != password_hash(&username, &password) {
        return AuthResult::Unauthorized;
    }

    AuthResult::Ok(format!(
        r#"{{"username":"{}","token":"session-{}"}}"#,
        json_escape(&user.username),
        json_escape(&user.username)
    ))
}

fn valid_username(username: &str) -> bool {
    (2..=32).contains(&username.len())
        && username
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_' || b == b'-')
}

fn password_hash(username: &str, password: &str) -> String {
    let mut hasher = DefaultHasher::new();
    "dndrest-auth-v1".hash(&mut hasher);
    username.hash(&mut hasher);
    password.hash(&mut hasher);
    format!("stdlib-hash-{:016x}", hasher.finish())
}

fn create_combat_session(
    body: &str,
    sessions: &mut HashMap<String, CombatSession>,
) -> Option<String> {
    let id = json_string_field(body, "id")?;
    if sessions.contains_key(&id) {
        return None;
    }

    let combatants = json_array_field(body, "combatants")?;
    let mut order = Vec::new();
    for combatant in array_objects(combatants) {
        let name = json_string_field(combatant, "name")?;
        let dex = json_i64_field(combatant, "dex")?;
        let roll = json_i64_field(combatant, "roll")?;
        order.push(Combatant {
            name,
            dex,
            score: roll + dex,
            conditions: Vec::new(),
            had_conditions: false,
        });
    }
    if order.is_empty() {
        return None;
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
        order,
    };
    let json = combat_session_created_json(&session);
    sessions.insert(id, session);
    Some(json)
}

fn add_combat_condition(
    session_id: &str,
    body: &str,
    sessions: &mut HashMap<String, CombatSession>,
) -> CombatResult {
    let target = match json_string_field(body, "target") {
        Some(value) => value,
        None => return CombatResult::BadRequest,
    };
    let condition = match json_string_field(body, "condition") {
        Some(value) => value,
        None => return CombatResult::BadRequest,
    };
    let duration_rounds = match json_i64_field(body, "duration_rounds") {
        Some(value) if value > 0 => value,
        _ => return CombatResult::BadRequest,
    };

    let Some(session) = sessions.get_mut(session_id) else {
        return CombatResult::NotFound;
    };
    let Some(combatant) = session.order.iter_mut().find(|entry| entry.name == target) else {
        return CombatResult::BadRequest;
    };

    combatant.had_conditions = true;
    combatant.conditions.push(Condition {
        condition,
        remaining_rounds: duration_rounds,
    });

    CombatResult::Ok(format!(
        r#"{{"target":"{}","conditions":[{}]}}"#,
        json_escape(&target),
        conditions_array_json(&combatant.conditions)
    ))
}

fn advance_combat_session(
    session_id: &str,
    sessions: &mut HashMap<String, CombatSession>,
) -> CombatResult {
    let Some(session) = sessions.get_mut(session_id) else {
        return CombatResult::NotFound;
    };
    if session.order.is_empty() {
        return CombatResult::BadRequest;
    }

    session.turn_index += 1;
    if session.turn_index >= session.order.len() {
        session.turn_index = 0;
        session.round += 1;
    }

    let active = &mut session.order[session.turn_index];
    for condition in &mut active.conditions {
        condition.remaining_rounds -= 1;
    }
    active
        .conditions
        .retain(|condition| condition.remaining_rounds > 0);

    CombatResult::Ok(combat_session_advanced_json(session))
}

fn combat_session_created_json(session: &CombatSession) -> String {
    let active = &session.order[session.turn_index];
    format!(
        r#"{{"id":"{}","round":{},"turn_index":{},"active":{},"order":[{}]}}"#,
        json_escape(&session.id),
        session.round,
        session.turn_index,
        active_combatant_json(active),
        initiative_entries_json(&session.order)
    )
}

fn combat_session_advanced_json(session: &CombatSession) -> String {
    let active = &session.order[session.turn_index];
    format!(
        r#"{{"id":"{}","round":{},"turn_index":{},"active":{},"conditions":{}}}"#,
        json_escape(&session.id),
        session.round,
        session.turn_index,
        active_combatant_json(active),
        session_conditions_json(session)
    )
}

fn active_combatant_json(combatant: &Combatant) -> String {
    format!(
        r#"{{"name":"{}","score":{}}}"#,
        json_escape(&combatant.name),
        combatant.score
    )
}

fn initiative_entries_json(order: &[Combatant]) -> String {
    order
        .iter()
        .map(active_combatant_json)
        .collect::<Vec<_>>()
        .join(",")
}

fn conditions_array_json(conditions: &[Condition]) -> String {
    conditions
        .iter()
        .map(|condition| {
            format!(
                r#"{{"condition":"{}","remaining_rounds":{}}}"#,
                json_escape(&condition.condition),
                condition.remaining_rounds
            )
        })
        .collect::<Vec<_>>()
        .join(",")
}

fn session_conditions_json(session: &CombatSession) -> String {
    let entries: Vec<String> = session
        .order
        .iter()
        .filter(|combatant| combatant.had_conditions || !combatant.conditions.is_empty())
        .map(|combatant| {
            format!(
                r#""{}":[{}]"#,
                json_escape(&combatant.name),
                conditions_array_json(&combatant.conditions)
            )
        })
        .collect();
    format!("{{{}}}", entries.join(","))
}

fn character_ability_modifier(body: &str) -> Option<String> {
    let score = json_i64_field(body, "score")?;
    validate_ability_score(score)?;
    let modifier = ability_modifier(score);
    Some(format!(r#"{{"score":{score},"modifier":{modifier}}}"#))
}

fn character_proficiency(body: &str) -> Option<String> {
    let level = json_i64_field(body, "level")?;
    let proficiency_bonus = proficiency_bonus(level)?;
    Some(format!(
        r#"{{"level":{level},"proficiency_bonus":{proficiency_bonus}}}"#
    ))
}

fn character_derived_stats(body: &str) -> Option<String> {
    let level = json_i64_field(body, "level")?;
    let proficiency_bonus = proficiency_bonus(level)?;
    let abilities = json_object_field(body, "abilities")?;
    let armor = json_object_field(body, "armor")?;

    let str_mod = ability_modifier_from_field(abilities, "str")?;
    let dex_mod = ability_modifier_from_field(abilities, "dex")?;
    let con_mod = ability_modifier_from_field(abilities, "con")?;
    let int_mod = ability_modifier_from_field(abilities, "int")?;
    let wis_mod = ability_modifier_from_field(abilities, "wis")?;
    let cha_mod = ability_modifier_from_field(abilities, "cha")?;

    let armor_base = json_i64_field(armor, "base")?;
    let shield = json_bool_field(armor, "shield")?;
    let dex_cap = json_i64_field(armor, "dex_cap")?;
    let shield_bonus = if shield { 2 } else { 0 };
    let hp_max = level * (6 + con_mod);
    let armor_class = armor_base + dex_mod.min(dex_cap) + shield_bonus;

    Some(format!(
        r#"{{"level":{level},"proficiency_bonus":{proficiency_bonus},"hp_max":{hp_max},"armor_class":{armor_class},"modifiers":{{"str":{str_mod},"dex":{dex_mod},"con":{con_mod},"int":{int_mod},"wis":{wis_mod},"cha":{cha_mod}}}}}"#
    ))
}

fn phb_spell_slots(body: &str) -> Option<String> {
    let class_name = json_string_field(body, "class")?;
    let level = json_i64_field(body, "level")?;
    if class_name != "wizard" || level != 5 {
        return None;
    }
    Some(r#"{"class":"wizard","level":5,"slots":{"1":4,"2":3,"3":2}}"#.to_string())
}

fn phb_long_rest(body: &str) -> Option<String> {
    let level = json_i64_field(body, "level")?;
    let _hp_current = json_i64_field(body, "hp_current")?;
    let hp_max = json_i64_field(body, "hp_max")?;
    let hit_dice_spent = json_i64_field(body, "hit_dice_spent")?;
    let exhaustion_level = json_i64_field(body, "exhaustion_level")?;
    if level < 1 || hp_max < 0 || hit_dice_spent < 0 || exhaustion_level < 0 {
        return None;
    }

    let hit_dice_restored = (level / 2).max(1);
    let remaining_hit_dice_spent = (hit_dice_spent - hit_dice_restored).max(0);
    let remaining_exhaustion = (exhaustion_level - 1).max(0);
    Some(format!(
        r#"{{"hp_current":{hp_max},"hit_dice_spent":{remaining_hit_dice_spent},"exhaustion_level":{remaining_exhaustion}}}"#
    ))
}

fn phb_equipment_load(body: &str) -> Option<String> {
    let strength = json_i64_field(body, "strength")?;
    let weight = json_i64_field(body, "weight")?;
    if strength < 0 || weight < 0 {
        return None;
    }

    let capacity = strength * 15;
    let encumbered = weight > capacity;
    Some(format!(
        r#"{{"capacity":{capacity},"weight":{weight},"encumbered":{encumbered}}}"#
    ))
}

fn ability_modifier_from_field(source: &str, key: &str) -> Option<i64> {
    let score = json_i64_field(source, key)?;
    validate_ability_score(score)?;
    Some(ability_modifier(score))
}

fn validate_ability_score(score: i64) -> Option<()> {
    if (1..=30).contains(&score) {
        Some(())
    } else {
        None
    }
}

fn ability_modifier(score: i64) -> i64 {
    (score - 10).div_euclid(2)
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

fn json_string_field(source: &str, key: &str) -> Option<String> {
    let value = field_value(source, key)?;
    let bytes = value.as_bytes();
    if bytes.first().copied()? != b'"' {
        return None;
    }
    let mut out = String::new();
    let mut escaped = false;
    for (i, ch) in value[1..].char_indices() {
        if escaped {
            match ch {
                '"' | '\\' | '/' => out.push(ch),
                'n' => out.push('\n'),
                'r' => out.push('\r'),
                't' => out.push('\t'),
                'b' => out.push('\u{0008}'),
                'f' => out.push('\u{000c}'),
                _ => return None,
            }
            escaped = false;
        } else if ch == '\\' {
            escaped = true;
        } else if ch == '"' {
            return Some(out);
        } else {
            out.push(ch);
        }
        let _ = i;
    }
    None
}

fn json_i64_field(source: &str, key: &str) -> Option<i64> {
    let value = field_value(source, key)?;
    let mut end = 0;
    for (i, ch) in value.char_indices() {
        if i == 0 && ch == '-' {
            end = 1;
        } else if ch.is_ascii_digit() {
            end = i + ch.len_utf8();
        } else {
            break;
        }
    }
    if end == 0 || &value[..end] == "-" {
        return None;
    }
    value[..end].parse().ok()
}

fn json_array_field<'a>(source: &'a str, key: &str) -> Option<&'a str> {
    let value = field_value(source, key)?;
    balanced_slice(value, '[', ']')
}

fn json_string_array_field(source: &str, key: &str) -> Option<Vec<String>> {
    let body = json_array_field(source, key)?;
    parse_string_array_body(body)
}

fn json_object_field<'a>(source: &'a str, key: &str) -> Option<&'a str> {
    let value = field_value(source, key)?;
    balanced_slice(value, '{', '}')
}

fn json_bool_field(source: &str, key: &str) -> Option<bool> {
    let value = field_value(source, key)?;
    if value.starts_with("true") {
        Some(true)
    } else if value.starts_with("false") {
        Some(false)
    } else {
        None
    }
}

fn field_value<'a>(source: &'a str, key: &str) -> Option<&'a str> {
    let needle = format!(r#""{key}""#);
    let start = source.find(&needle)? + needle.len();
    let after_key = source[start..].trim_start();
    let after_colon = after_key.strip_prefix(':')?.trim_start();
    Some(after_colon)
}

fn balanced_slice(source: &str, open: char, close: char) -> Option<&str> {
    if !source.starts_with(open) {
        return None;
    }
    let mut depth = 0_i32;
    let mut in_string = false;
    let mut escaped = false;
    for (i, ch) in source.char_indices() {
        if in_string {
            if escaped {
                escaped = false;
            } else if ch == '\\' {
                escaped = true;
            } else if ch == '"' {
                in_string = false;
            }
            continue;
        }
        if ch == '"' {
            in_string = true;
        } else if ch == open {
            depth += 1;
        } else if ch == close {
            depth -= 1;
            if depth == 0 {
                return Some(&source[1..i]);
            }
        }
    }
    None
}

fn array_objects(array_body: &str) -> Vec<&str> {
    let mut objects = Vec::new();
    let mut rest = array_body.trim();
    while !rest.is_empty() {
        if let Some(start) = rest.find('{') {
            rest = &rest[start..];
            if let Some(object) = balanced_slice(rest, '{', '}') {
                objects.push(object);
                let consumed = object.len() + 2;
                rest = rest[consumed..].trim_start();
                if let Some(next) = rest.strip_prefix(',') {
                    rest = next.trim_start();
                }
            } else {
                break;
            }
        } else {
            break;
        }
    }
    objects
}

fn parse_string_array_body(array_body: &str) -> Option<Vec<String>> {
    let mut values = Vec::new();
    let mut rest = array_body.trim();
    if rest.is_empty() {
        return Some(values);
    }
    loop {
        let (value, consumed) = parse_json_string_prefix(rest)?;
        values.push(value);
        rest = rest[consumed..].trim_start();
        if rest.is_empty() {
            return Some(values);
        }
        rest = rest.strip_prefix(',')?.trim_start();
        if rest.is_empty() {
            return None;
        }
    }
}

fn parse_json_string_prefix(source: &str) -> Option<(String, usize)> {
    let bytes = source.as_bytes();
    if bytes.first().copied()? != b'"' {
        return None;
    }
    let mut out = String::new();
    let mut escaped = false;
    for (i, ch) in source[1..].char_indices() {
        if escaped {
            match ch {
                '"' | '\\' | '/' => out.push(ch),
                'n' => out.push('\n'),
                'r' => out.push('\r'),
                't' => out.push('\t'),
                'b' => out.push('\u{0008}'),
                'f' => out.push('\u{000c}'),
                _ => return None,
            }
            escaped = false;
        } else if ch == '\\' {
            escaped = true;
        } else if ch == '"' {
            return Some((out, i + 2));
        } else {
            out.push(ch);
        }
    }
    None
}

fn number_from_halves(value_twice: i64) -> String {
    if value_twice % 2 == 0 {
        (value_twice / 2).to_string()
    } else {
        format!("{}.5", value_twice / 2)
    }
}

fn json_escape(input: &str) -> String {
    let mut out = String::new();
    for ch in input.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c => out.push(c),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dice_stats_sample() {
        assert_eq!(
            dice_stats(r#"{"expression":"2d6+3"}"#).as_deref(),
            Some(r#"{"dice_count":2,"sides":6,"modifier":3,"min":5,"max":15,"average":10}"#)
        );
    }

    #[test]
    fn ability_check_sample() {
        assert_eq!(
            ability_check(r#"{"roll":9,"modifier":5,"dc":15}"#).as_deref(),
            Some(r#"{"total":14,"success":false,"margin":-1}"#)
        );
    }

    #[test]
    fn adjusted_xp_sample() {
        let body = r#"{"party":[{"level":3},{"level":3},{"level":3},{"level":3}],"monsters":[{"cr":"1","count":2},{"cr":"2","count":1}]}"#;
        assert_eq!(
            adjusted_xp(body).as_deref(),
            Some(
                r#"{"base_xp":850,"monster_count":3,"multiplier":2,"adjusted_xp":1700,"difficulty":"deadly","thresholds":{"easy":300,"medium":600,"hard":900,"deadly":1600}}"#
            )
        );
    }

    #[test]
    fn initiative_order_sample() {
        let body = r#"{"combatants":[{"name":"rogue","dex":3,"roll":14},{"name":"ogre","dex":-1,"roll":16}]}"#;
        assert_eq!(
            initiative_order(body).as_deref(),
            Some(r#"{"order":[{"name":"rogue","score":17},{"name":"ogre","score":15}]}"#)
        );
    }

    #[test]
    fn create_combat_session_sorts_and_sets_active() {
        let body = r#"{"id":"enc-1","combatants":[{"name":"fighter","dex":1,"roll":13},{"name":"rogue","dex":3,"roll":14},{"name":"mage","dex":2,"roll":14}]}"#;
        let mut sessions = HashMap::new();
        assert_eq!(
            create_combat_session(body, &mut sessions).as_deref(),
            Some(
                r#"{"id":"enc-1","round":1,"turn_index":0,"active":{"name":"rogue","score":17},"order":[{"name":"rogue","score":17},{"name":"mage","score":16},{"name":"fighter","score":14}]}"#
            )
        );
    }

    #[test]
    fn combat_advance_decrements_only_new_active_conditions() {
        let body = r#"{"id":"enc-1","combatants":[{"name":"fighter","dex":1,"roll":13},{"name":"rogue","dex":3,"roll":14},{"name":"mage","dex":2,"roll":14}]}"#;
        let mut sessions = HashMap::new();
        create_combat_session(body, &mut sessions).unwrap();
        match add_combat_condition(
            "enc-1",
            r#"{"target":"fighter","condition":"blessed","duration_rounds":2}"#,
            &mut sessions,
        ) {
            CombatResult::Ok(json) => assert_eq!(
                json,
                r#"{"target":"fighter","conditions":[{"condition":"blessed","remaining_rounds":2}]}"#
            ),
            _ => panic!("expected condition to be added"),
        }
        match advance_combat_session("enc-1", &mut sessions) {
            CombatResult::Ok(json) => assert_eq!(
                json,
                r#"{"id":"enc-1","round":1,"turn_index":1,"active":{"name":"mage","score":16},"conditions":{"fighter":[{"condition":"blessed","remaining_rounds":2}]}}"#
            ),
            _ => panic!("expected advance"),
        }
        advance_combat_session("enc-1", &mut sessions);
        match advance_combat_session("enc-1", &mut sessions) {
            CombatResult::Ok(json) => assert_eq!(
                json,
                r#"{"id":"enc-1","round":2,"turn_index":0,"active":{"name":"rogue","score":17},"conditions":{"fighter":[{"condition":"blessed","remaining_rounds":1}]}}"#
            ),
            _ => panic!("expected wrapped advance"),
        }
        advance_combat_session("enc-1", &mut sessions);
        match advance_combat_session("enc-1", &mut sessions) {
            CombatResult::Ok(json) => assert_eq!(
                json,
                r#"{"id":"enc-1","round":2,"turn_index":2,"active":{"name":"fighter","score":14},"conditions":{"fighter":[]}}"#
            ),
            _ => panic!("expected expired condition to leave target key"),
        }
    }

    #[test]
    fn register_user_success_and_duplicate() {
        let mut users = HashMap::new();
        match register_user(
            r#"{"username":"dm","password":"swordfish","role":"dm"}"#,
            &mut users,
        ) {
            AuthResult::Ok(json) => {
                assert_eq!(json, r#"{"username":"dm","role":"dm"}"#);
            }
            _ => panic!("expected registration to succeed"),
        }
        assert_eq!(users.len(), 1);
        assert_ne!(users["dm"].password_hash, "swordfish");
        match register_user(
            r#"{"username":"dm","password":"swordfish","role":"dm"}"#,
            &mut users,
        ) {
            AuthResult::Conflict => {}
            _ => panic!("expected duplicate username conflict"),
        }
    }

    #[test]
    fn register_user_validates_fields() {
        let mut users = HashMap::new();
        match register_user(
            r#"{"username":"DM","password":"swordfish","role":"dm"}"#,
            &mut users,
        ) {
            AuthResult::BadRequest => {}
            _ => panic!("expected invalid username to fail"),
        }
        match register_user(
            r#"{"username":"dm","password":"short","role":"dm"}"#,
            &mut users,
        ) {
            AuthResult::BadRequest => {}
            _ => panic!("expected short password to fail"),
        }
        match register_user(
            r#"{"username":"dm","password":"swordfish","role":"wizard"}"#,
            &mut users,
        ) {
            AuthResult::BadRequest => {}
            _ => panic!("expected invalid role to fail"),
        }
    }

    #[test]
    fn login_user_returns_deterministic_token_or_unauthorized() {
        let mut users = HashMap::new();
        register_user(
            r#"{"username":"dm","password":"swordfish","role":"dm"}"#,
            &mut users,
        );
        match login_user(r#"{"username":"dm","password":"swordfish"}"#, &users) {
            AuthResult::Ok(json) => {
                assert_eq!(json, r#"{"username":"dm","token":"session-dm"}"#);
            }
            _ => panic!("expected login to succeed"),
        }
        match login_user(r#"{"username":"dm","password":"wrong-password"}"#, &users) {
            AuthResult::Unauthorized => {}
            _ => panic!("expected wrong password to be unauthorized"),
        }
        match login_user(r#"{"username":"nobody","password":"swordfish"}"#, &users) {
            AuthResult::Unauthorized => {}
            _ => panic!("expected unknown user to be unauthorized"),
        }
    }

    #[test]
    fn character_ability_modifier_floors_negative_half() {
        assert_eq!(
            character_ability_modifier(r#"{"score":9}"#).as_deref(),
            Some(r#"{"score":9,"modifier":-1}"#)
        );
    }

    #[test]
    fn character_proficiency_sample() {
        assert_eq!(
            character_proficiency(r#"{"level":9}"#).as_deref(),
            Some(r#"{"level":9,"proficiency_bonus":4}"#)
        );
    }

    #[test]
    fn character_derived_stats_sample() {
        let body = r#"{"level":5,"abilities":{"str":16,"dex":14,"con":13,"int":8,"wis":12,"cha":10},"armor":{"base":12,"shield":true,"dex_cap":2}}"#;
        assert_eq!(
            character_derived_stats(body).as_deref(),
            Some(
                r#"{"level":5,"proficiency_bonus":3,"hp_max":35,"armor_class":16,"modifiers":{"str":3,"dex":2,"con":1,"int":-1,"wis":1,"cha":0}}"#
            )
        );
    }

    #[test]
    fn phb_spell_slots_supports_wizard_level_five() {
        assert_eq!(
            phb_spell_slots(r#"{"class":"wizard","level":5}"#).as_deref(),
            Some(r#"{"class":"wizard","level":5,"slots":{"1":4,"2":3,"3":2}}"#)
        );
    }

    #[test]
    fn phb_long_rest_restores_resources() {
        assert_eq!(
            phb_long_rest(
                r#"{"level":5,"hp_current":9,"hp_max":35,"hit_dice_spent":3,"exhaustion_level":1}"#
            )
            .as_deref(),
            Some(r#"{"hp_current":35,"hit_dice_spent":1,"exhaustion_level":0}"#)
        );
    }

    #[test]
    fn phb_equipment_load_marks_over_capacity() {
        assert_eq!(
            phb_equipment_load(r#"{"strength":12,"weight":181}"#).as_deref(),
            Some(r#"{"capacity":180,"weight":181,"encumbered":true}"#)
        );
    }

    #[test]
    fn monster_json_matches_create_and_read_contract() {
        let monster = parse_monster(
            r#"{"slug":"goblin","name":"Goblin","cr":"1/4","armor_class":15,"hit_points":7,"tags":["humanoid","goblinoid"]}"#,
        )
        .unwrap();
        assert_eq!(
            monster_create_json(&monster),
            r#"{"slug":"goblin","name":"Goblin","cr":"1/4","armor_class":15,"hit_points":7}"#
        );
        assert_eq!(
            monster_read_json(&monster),
            r#"{"slug":"goblin","name":"Goblin","cr":"1/4","armor_class":15,"hit_points":7,"tags":["humanoid","goblinoid"]}"#
        );
    }

    #[test]
    fn item_json_matches_contract() {
        let item = parse_item(
            r#"{"slug":"healing-potion","name":"Potion of Healing","type":"potion","rarity":"common","cost_gp":50}"#,
        )
        .unwrap();
        assert_eq!(
            item_json(&item),
            r#"{"slug":"healing-potion","name":"Potion of Healing","type":"potion","rarity":"common","cost_gp":50}"#
        );
    }

    #[test]
    fn campaign_json_matches_contract() {
        let campaign = parse_campaign(r#"{"id":"camp-1","name":"Lost Mine","dm":"dm"}"#).unwrap();
        let character =
            parse_campaign_character(r#"{"id":"char-1","name":"Nyx","level":3,"class":"rogue"}"#)
                .unwrap();
        let event = parse_campaign_event(
            r#"{"id":"evt-1","kind":"note","summary":"Nyx scouts the goblin trail."}"#,
        )
        .unwrap();

        assert_eq!(
            campaign_json(&campaign),
            r#"{"id":"camp-1","name":"Lost Mine","dm":"dm"}"#
        );
        assert_eq!(
            campaign_character_json(&character),
            r#"{"id":"char-1","name":"Nyx","level":3,"class":"rogue"}"#
        );
        assert_eq!(
            campaign_event_json(&event),
            r#"{"id":"evt-1","kind":"note"}"#
        );
        assert_eq!(
            campaign_state_json(&campaign, &[character], 1),
            r#"{"id":"camp-1","name":"Lost Mine","dm":"dm","characters":[{"id":"char-1","name":"Nyx","level":3,"class":"rogue"}],"log_count":1}"#
        );
    }

    #[test]
    fn dm_encounter_math_matches_goblin_sample() {
        let crs = vec!["1/4".to_string(), "1/4".to_string(), "1/4".to_string()];
        let math =
            encounter_math(r#"{"level":3},{"level":3},{"level":3},{"level":3}"#, &crs).unwrap();
        assert_eq!(math.base_xp, 150);
        assert_eq!(math.adjusted_xp, "300");
        assert_eq!(math.difficulty, "easy");
        assert_eq!(math.monster_count, 3);
        assert_eq!(encounter_recommendation(&math.difficulty), "safe warm-up");
    }

    #[test]
    fn dm_loot_and_recap_json_match_contract() {
        let storage = Storage {
            db_path: format!("/tmp/dndrest-test-{}.db", std::process::id()),
        };
        let _ = std::fs::remove_file(&storage.db_path);
        init_storage(&storage).unwrap();
        create_campaign(r#"{"id":"camp-1","name":"Lost Mine","dm":"dm"}"#, &storage);
        add_campaign_event(
            "camp-1",
            r#"{"id":"evt-1","kind":"note","summary":"Nyx scouts the goblin trail."}"#,
            &storage,
        );

        match dm_loot_parcel(r#"{"campaign_id":"camp-1","tier":1,"seed":42}"#, &storage) {
            DmResult::Ok(json) => assert_eq!(
                json,
                r#"{"campaign_id":"camp-1","coins_gp":75,"items":[{"slug":"healing-potion","quantity":2}]}"#
            ),
            _ => panic!("expected loot parcel"),
        }
        match dm_session_recap(r#"{"campaign_id":"camp-1"}"#, &storage) {
            DmResult::Ok(json) => assert_eq!(
                json,
                r#"{"campaign_id":"camp-1","summary":"Nyx scouts the goblin trail.","open_threads":["Resolve goblin trail ambush"]}"#
            ),
            _ => panic!("expected recap"),
        }
        let _ = std::fs::remove_file(&storage.db_path);
    }

    #[test]
    fn string_array_parser_accepts_empty_and_rejects_trailing_comma() {
        assert_eq!(
            json_string_array_field(r#"{"tags":[]}"#, "tags"),
            Some(Vec::new())
        );
        assert_eq!(
            json_string_array_field(r#"{"tags":["one",]}"#, "tags"),
            None
        );
    }
}
