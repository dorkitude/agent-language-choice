//! Campaign NPCs and factions: create factions with a stance, create NPCs
//! attached to a faction with a disposition score, and summarize the
//! relationship state for a campaign. Backing store is two in-memory maps
//! keyed by campaign id, validated against [`crate::campaigns`] the same way
//! [`crate::quests`] validates `campaign_id`.

use std::collections::HashMap;
use std::net::TcpStream;
use std::sync::{Mutex, OnceLock};

use crate::campaigns::campaigns;
use crate::http::{bad_request, respond};
use crate::json::{as_int, escape_json_string, parse_json};

const STANCES: [&str; 3] = ["friendly", "neutral", "hostile"];

pub(crate) struct Faction {
    id: String,
    name: String,
    stance: String,
}

pub(crate) struct Npc {
    id: String,
    name: String,
    faction_id: String,
    disposition: i64,
}

#[derive(Default)]
pub(crate) struct CampaignRelationships {
    factions: Vec<Faction>,
    npcs: Vec<Npc>,
}

pub(crate) fn relationships() -> &'static Mutex<HashMap<String, CampaignRelationships>> {
    static RELATIONSHIPS: OnceLock<Mutex<HashMap<String, CampaignRelationships>>> = OnceLock::new();
    RELATIONSHIPS.get_or_init(|| Mutex::new(HashMap::new()))
}

pub(crate) fn clear() {
    relationships().lock().unwrap().clear();
}

pub(crate) fn npc_count(campaign_id: &str) -> i64 {
    let store = relationships().lock().unwrap();
    store.get(campaign_id).map(|entry| entry.npcs.len() as i64).unwrap_or(0)
}

fn friendly_count(entry: &CampaignRelationships) -> i64 {
    entry
        .npcs
        .iter()
        .filter(|n| match entry.factions.iter().find(|f| f.id == n.faction_id) {
            Some(f) => f.stance == "friendly",
            None => n.disposition > 0,
        })
        .count() as i64
}

pub(crate) fn friendly_npc_count(campaign_id: &str) -> i64 {
    let store = relationships().lock().unwrap();
    store.get(campaign_id).map(friendly_count).unwrap_or(0)
}

fn faction_json(f: &Faction) -> String {
    format!(
        r#"{{"id":"{}","name":"{}","stance":"{}"}}"#,
        escape_json_string(&f.id),
        escape_json_string(&f.name),
        escape_json_string(&f.stance)
    )
}

fn npc_json(n: &Npc) -> String {
    format!(
        r#"{{"id":"{}","name":"{}","faction_id":"{}","disposition":{}}}"#,
        escape_json_string(&n.id),
        escape_json_string(&n.name),
        escape_json_string(&n.faction_id),
        n.disposition
    )
}

pub(crate) fn handle_create_faction(
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
    let stance = match json.get("stance").and_then(|v| v.as_str()) {
        Some(s) if STANCES.contains(&s) => s.to_string(),
        _ => return bad_request(stream, "invalid stance"),
    };

    {
        let campaigns_store = campaigns().lock().unwrap();
        if !campaigns_store.contains_key(campaign_id) {
            return respond(stream, 404, r#"{"error":"campaign not found"}"#);
        }
    }

    let mut store = relationships().lock().unwrap();
    let entry = store.entry(campaign_id.to_string()).or_default();
    if entry.factions.iter().any(|f| f.id == id) {
        return respond(stream, 409, r#"{"error":"faction already exists"}"#);
    }

    let faction = Faction { id, name, stance };
    let out = faction_json(&faction);
    entry.factions.push(faction);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_create_npc(
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
    let faction_id = match json.get("faction_id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid faction_id"),
    };
    let disposition = match json.get("disposition").and_then(as_int) {
        Some(d) => d,
        None => return bad_request(stream, "invalid disposition"),
    };

    {
        let campaigns_store = campaigns().lock().unwrap();
        if !campaigns_store.contains_key(campaign_id) {
            return respond(stream, 404, r#"{"error":"campaign not found"}"#);
        }
    }

    let mut store = relationships().lock().unwrap();
    let entry = store.entry(campaign_id.to_string()).or_default();
    if !entry.factions.iter().any(|f| f.id == faction_id) {
        return respond(stream, 404, r#"{"error":"faction not found"}"#);
    }
    if entry.npcs.iter().any(|n| n.id == id) {
        return respond(stream, 409, r#"{"error":"npc already exists"}"#);
    }

    let npc = Npc {
        id,
        name,
        faction_id,
        disposition,
    };
    let out = npc_json(&npc);
    entry.npcs.push(npc);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_relationship_summary(
    stream: &mut TcpStream,
    campaign_id: &str,
) -> std::io::Result<()> {
    {
        let campaigns_store = campaigns().lock().unwrap();
        if !campaigns_store.contains_key(campaign_id) {
            return respond(stream, 404, r#"{"error":"campaign not found"}"#);
        }
    }

    let store = relationships().lock().unwrap();
    let (factions_count, npcs_count, friendly_npcs) = match store.get(campaign_id) {
        Some(entry) => (entry.factions.len(), entry.npcs.len(), friendly_count(entry) as usize),
        None => (0, 0, 0),
    };
    drop(store);

    let out = format!(
        r#"{{"campaign_id":"{}","factions":{},"npcs":{},"friendly_npcs":{}}}"#,
        escape_json_string(campaign_id),
        factions_count,
        npcs_count,
        friendly_npcs
    );

    respond(stream, 200, &out)
}
