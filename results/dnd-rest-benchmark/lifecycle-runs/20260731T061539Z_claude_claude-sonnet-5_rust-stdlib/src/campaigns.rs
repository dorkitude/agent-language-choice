//! Campaign state: create a campaign, roster characters onto it, append log
//! events (only the count is retained), and fetch a campaign's current
//! state. Backing store is an in-memory map keyed by campaign id, also read
//! by [`crate::dm_tools`] to validate a `campaign_id` before running DM
//! tooling against it.

use std::collections::HashMap;
use std::net::TcpStream;
use std::sync::{Mutex, OnceLock};

use crate::http::{bad_request, respond};
use crate::json::{as_int, escape_json_string, parse_json};

pub(crate) struct Character {
    id: String,
    name: String,
    level: i64,
    class: String,
}

pub(crate) struct Campaign {
    id: String,
    name: String,
    dm: String,
    characters: Vec<Character>,
    log_count: i64,
}

pub(crate) fn campaigns() -> &'static Mutex<HashMap<String, Campaign>> {
    static CAMPAIGNS: OnceLock<Mutex<HashMap<String, Campaign>>> = OnceLock::new();
    CAMPAIGNS.get_or_init(|| Mutex::new(HashMap::new()))
}

pub(crate) fn clear() {
    campaigns().lock().unwrap().clear();
}

pub(crate) fn campaign_exists(campaign_id: &str) -> bool {
    campaigns().lock().unwrap().contains_key(campaign_id)
}

/// Returns `(name, characters_count, log_count)` for an existing campaign.
pub(crate) fn campaign_summary(campaign_id: &str) -> Option<(String, i64, i64)> {
    let store = campaigns().lock().unwrap();
    let campaign = store.get(campaign_id)?;
    Some((
        campaign.name.clone(),
        campaign.characters.len() as i64,
        campaign.log_count,
    ))
}

/// Returns `None` if the campaign itself doesn't exist, otherwise whether
/// `character_id` is on that campaign's roster.
pub(crate) fn character_exists(campaign_id: &str, character_id: &str) -> Option<bool> {
    let store = campaigns().lock().unwrap();
    let campaign = store.get(campaign_id)?;
    Some(campaign.characters.iter().any(|ch| ch.id == character_id))
}

fn campaign_json(c: &Campaign) -> String {
    format!(
        r#"{{"id":"{}","name":"{}","dm":"{}"}}"#,
        escape_json_string(&c.id),
        escape_json_string(&c.name),
        escape_json_string(&c.dm)
    )
}

fn character_json(ch: &Character) -> String {
    format!(
        r#"{{"id":"{}","name":"{}","level":{},"class":"{}"}}"#,
        escape_json_string(&ch.id),
        escape_json_string(&ch.name),
        ch.level,
        escape_json_string(&ch.class)
    )
}

pub(crate) fn handle_create_campaign(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
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
        return respond(stream, 409, r#"{"error":"campaign already exists"}"#);
    }

    let campaign = Campaign {
        id: id.clone(),
        name,
        dm,
        characters: Vec::new(),
        log_count: 0,
    };
    let out = campaign_json(&campaign);
    store.insert(id, campaign);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_add_character(
    stream: &mut TcpStream,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let id = match json.get("id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid id"),
    };
    let name = match json.get("name").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid name"),
    };
    let level = match json.get("level").and_then(as_int) {
        Some(l) if l >= 1 => l,
        _ => return bad_request(stream, "invalid level"),
    };
    let class = match json.get("class").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid class"),
    };

    let mut store = campaigns().lock().unwrap();
    let campaign = match store.get_mut(campaign_id) {
        Some(c) => c,
        None => return respond(stream, 404, r#"{"error":"campaign not found"}"#),
    };

    if campaign.characters.iter().any(|ch| ch.id == id) {
        return respond(stream, 409, r#"{"error":"character already exists"}"#);
    }

    let character = Character {
        id,
        name,
        level,
        class,
    };
    let out = character_json(&character);
    campaign.characters.push(character);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_add_event(
    stream: &mut TcpStream,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let id = match json.get("id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid id"),
    };
    let kind = match json.get("kind").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid kind"),
    };
    let _summary = match json.get("summary").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return bad_request(stream, "invalid summary"),
    };

    let mut store = campaigns().lock().unwrap();
    let campaign = match store.get_mut(campaign_id) {
        Some(c) => c,
        None => return respond(stream, 404, r#"{"error":"campaign not found"}"#),
    };

    // Event bodies are validated but not persisted beyond a running total;
    // only `log_count` is surfaced by `/state`.
    campaign.log_count += 1;

    let out = format!(
        r#"{{"id":"{}","kind":"{}"}}"#,
        escape_json_string(&id),
        escape_json_string(&kind)
    );
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_campaign_state(stream: &mut TcpStream, campaign_id: &str) -> std::io::Result<()> {
    let store = campaigns().lock().unwrap();
    let campaign = match store.get(campaign_id) {
        Some(c) => c,
        None => return respond(stream, 404, r#"{"error":"campaign not found"}"#),
    };

    let characters_json: Vec<String> = campaign.characters.iter().map(character_json).collect();

    let out = format!(
        r#"{{"id":"{}","name":"{}","dm":"{}","characters":[{}],"log_count":{}}}"#,
        escape_json_string(&campaign.id),
        escape_json_string(&campaign.name),
        escape_json_string(&campaign.dm),
        characters_json.join(","),
        campaign.log_count
    );
    drop(store);

    respond(stream, 200, &out)
}
