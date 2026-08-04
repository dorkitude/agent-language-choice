//! In-memory combat session state: create a session with a rolled
//! initiative order, attach timed conditions to combatants, and advance
//! turns (decrementing/expiring conditions on the newly active combatant).
//!
//! Sessions live only in process memory behind a `Mutex` (see
//! [`crate::storage`] for the on-disk schema they are modeled after) and do
//! not survive a restart or a `/v1/storage/reset` call.

use std::collections::HashMap;
use std::net::TcpStream;
use std::sync::{Mutex, OnceLock};

use crate::http::{bad_request, respond};
use crate::json::{as_int, escape_json_string, parse_json};

pub(crate) struct CombatSession {
    round: i64,
    turn_index: usize,
    order: Vec<(String, i64)>, // (name, initiative score)
    conditions: HashMap<String, Vec<(String, i64)>>, // name -> [(condition, remaining_rounds)]
}

pub(crate) fn sessions() -> &'static Mutex<HashMap<String, CombatSession>> {
    static SESSIONS: OnceLock<Mutex<HashMap<String, CombatSession>>> = OnceLock::new();
    SESSIONS.get_or_init(|| Mutex::new(HashMap::new()))
}

pub(crate) fn clear() {
    sessions().lock().unwrap().clear();
}

fn conditions_json(list: &[(String, i64)]) -> String {
    let items: Vec<String> = list
        .iter()
        .map(|(cond, remaining)| {
            format!(
                r#"{{"condition":"{}","remaining_rounds":{}}}"#,
                escape_json_string(cond),
                remaining
            )
        })
        .collect();
    format!("[{}]", items.join(","))
}

fn session_conditions_json(session: &CombatSession) -> String {
    let mut names: Vec<&String> = session.conditions.keys().collect();
    names.sort();
    let entries: Vec<String> = names
        .into_iter()
        .map(|n| {
            format!(
                r#""{}":{}"#,
                escape_json_string(n),
                conditions_json(&session.conditions[n])
            )
        })
        .collect();
    format!("{{{}}}", entries.join(","))
}

pub(crate) fn handle_create_combat_session(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let id = match json.get("id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "missing id"),
    };

    let combatants = match json.get("combatants").and_then(|v| v.as_array()) {
        Some(a) if !a.is_empty() => a,
        _ => return bad_request(stream, "missing combatants"),
    };

    struct Entry {
        name: String,
        dex: i64,
        score: i64,
    }

    let mut entries: Vec<Entry> = Vec::new();
    for c in combatants {
        let name = match c.get("name").and_then(|v| v.as_str()) {
            Some(s) if !s.is_empty() => s.to_string(),
            _ => return bad_request(stream, "invalid combatant"),
        };
        let dex = match c.get("dex").and_then(as_int) {
            Some(v) => v,
            None => return bad_request(stream, "invalid combatant"),
        };
        let roll = match c.get("roll").and_then(as_int) {
            Some(v) => v,
            None => return bad_request(stream, "invalid combatant"),
        };
        entries.push(Entry {
            name,
            dex,
            score: roll + dex,
        });
    }

    entries.sort_by(|a, b| {
        b.score
            .cmp(&a.score)
            .then_with(|| b.dex.cmp(&a.dex))
            .then_with(|| a.name.cmp(&b.name))
    });

    let order: Vec<(String, i64)> = entries.into_iter().map(|e| (e.name, e.score)).collect();

    let mut store = sessions().lock().unwrap();
    if store.contains_key(&id) {
        return bad_request(stream, "duplicate id");
    }

    let session = CombatSession {
        round: 1,
        turn_index: 0,
        order,
        conditions: HashMap::new(),
    };

    let active = &session.order[0];
    let order_json: Vec<String> = session
        .order
        .iter()
        .map(|(name, score)| format!(r#"{{"name":"{}","score":{}}}"#, escape_json_string(name), score))
        .collect();

    let out = format!(
        r#"{{"id":"{}","round":{},"turn_index":{},"active":{{"name":"{}","score":{}}},"order":[{}]}}"#,
        escape_json_string(&id),
        session.round,
        session.turn_index,
        escape_json_string(&active.0),
        active.1,
        order_json.join(",")
    );

    store.insert(id, session);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_add_condition(stream: &mut TcpStream, id: &str, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let target = match json.get("target").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "missing target"),
    };
    let condition = match json.get("condition").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "missing condition"),
    };
    let duration_rounds = match json.get("duration_rounds").and_then(as_int) {
        Some(d) if d > 0 => d,
        _ => return bad_request(stream, "invalid duration_rounds"),
    };

    let mut store = sessions().lock().unwrap();
    let session = match store.get_mut(id) {
        Some(s) => s,
        None => return respond(stream, 404, r#"{"error":"session not found"}"#),
    };

    if !session.order.iter().any(|(name, _)| name == &target) {
        return bad_request(stream, "unknown target");
    }

    session
        .conditions
        .entry(target.clone())
        .or_insert_with(Vec::new)
        .push((condition, duration_rounds));

    let out = format!(
        r#"{{"target":"{}","conditions":{}}}"#,
        escape_json_string(&target),
        conditions_json(&session.conditions[&target])
    );

    respond(stream, 200, &out)
}

pub(crate) fn handle_advance_turn(stream: &mut TcpStream, id: &str) -> std::io::Result<()> {
    let mut store = sessions().lock().unwrap();
    let session = match store.get_mut(id) {
        Some(s) => s,
        None => return respond(stream, 404, r#"{"error":"session not found"}"#),
    };

    let len = session.order.len();
    let next_index = (session.turn_index + 1) % len;
    if next_index == 0 {
        session.round += 1;
    }
    session.turn_index = next_index;

    // Conditions tick down (and expire) only for the combatant whose turn
    // is beginning, matching "duration_rounds remaining at the start of
    // your turn" semantics.
    let active_name = session.order[next_index].0.clone();
    if let Some(list) = session.conditions.get_mut(&active_name) {
        for entry in list.iter_mut() {
            entry.1 -= 1;
        }
        list.retain(|(_, remaining)| *remaining > 0);
    }

    let active = &session.order[next_index];
    let out = format!(
        r#"{{"id":"{}","round":{},"turn_index":{},"active":{{"name":"{}","score":{}}},"conditions":{}}}"#,
        escape_json_string(id),
        session.round,
        session.turn_index,
        escape_json_string(&active.0),
        active.1,
        session_conditions_json(session)
    );

    respond(stream, 200, &out)
}
