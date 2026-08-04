//! Campaign session scheduling: schedule sessions with an agenda, record
//! attendance, and look up the next upcoming session. Backing store is an
//! in-memory map keyed by campaign id (each campaign owns a `Vec<Session>`),
//! separate from [`crate::campaigns`]'s own store but validated against it
//! the same way [`crate::quests`] validates `campaign_id`.

use std::collections::HashMap;
use std::net::TcpStream;
use std::sync::{Mutex, OnceLock};

use crate::campaigns::campaigns;
use crate::http::{bad_request, respond};
use crate::json::{as_int, escape_json_string, parse_json};

pub(crate) struct Session {
    id: String,
    starts_at: String,
    duration_minutes: i64,
    agenda: Vec<String>,
    present: Vec<String>,
    absent: Vec<String>,
}

pub(crate) fn sessions() -> &'static Mutex<HashMap<String, Vec<Session>>> {
    static SESSIONS: OnceLock<Mutex<HashMap<String, Vec<Session>>>> = OnceLock::new();
    SESSIONS.get_or_init(|| Mutex::new(HashMap::new()))
}

pub(crate) fn clear() {
    sessions().lock().unwrap().clear();
}

pub(crate) fn session_count(campaign_id: &str) -> i64 {
    let store = sessions().lock().unwrap();
    store.get(campaign_id).map(|ss| ss.len() as i64).unwrap_or(0)
}

fn session_json(s: &Session) -> String {
    format!(
        r#"{{"id":"{}","starts_at":"{}","duration_minutes":{},"agenda_count":{}}}"#,
        escape_json_string(&s.id),
        escape_json_string(&s.starts_at),
        s.duration_minutes,
        s.agenda.len()
    )
}

fn next_session_json(s: &Session) -> String {
    format!(
        r#"{{"id":"{}","starts_at":"{}","agenda_count":{}}}"#,
        escape_json_string(&s.id),
        escape_json_string(&s.starts_at),
        s.agenda.len()
    )
}

pub(crate) fn handle_schedule_session(
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
    let starts_at = match json.get("starts_at").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid starts_at"),
    };
    let duration_minutes = match json.get("duration_minutes").and_then(as_int) {
        Some(d) if d >= 1 => d,
        _ => return bad_request(stream, "invalid duration_minutes"),
    };
    let agenda_json = match json.get("agenda").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return bad_request(stream, "invalid agenda"),
    };
    let mut agenda = Vec::new();
    for item in agenda_json {
        match item.as_str() {
            Some(s) if !s.is_empty() => agenda.push(s.to_string()),
            _ => return bad_request(stream, "invalid agenda"),
        }
    }

    {
        let campaigns_store = campaigns().lock().unwrap();
        if !campaigns_store.contains_key(campaign_id) {
            return respond(stream, 404, r#"{"error":"campaign not found"}"#);
        }
    }

    let mut store = sessions().lock().unwrap();
    let campaign_sessions = store.entry(campaign_id.to_string()).or_insert_with(Vec::new);
    if campaign_sessions.iter().any(|s| s.id == id) {
        return respond(stream, 409, r#"{"error":"session already exists"}"#);
    }

    let session = Session {
        id,
        starts_at,
        duration_minutes,
        agenda,
        present: Vec::new(),
        absent: Vec::new(),
    };
    let out = session_json(&session);
    campaign_sessions.push(session);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_record_attendance(
    stream: &mut TcpStream,
    campaign_id: &str,
    session_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let present_json = match json.get("present").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return bad_request(stream, "invalid present"),
    };
    let mut present = Vec::new();
    for item in present_json {
        match item.as_str() {
            Some(s) if !s.is_empty() => present.push(s.to_string()),
            _ => return bad_request(stream, "invalid present"),
        }
    }
    let absent_json = match json.get("absent").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return bad_request(stream, "invalid absent"),
    };
    let mut absent = Vec::new();
    for item in absent_json {
        match item.as_str() {
            Some(s) if !s.is_empty() => absent.push(s.to_string()),
            _ => return bad_request(stream, "invalid absent"),
        }
    }

    let mut store = sessions().lock().unwrap();
    let campaign_sessions = match store.get_mut(campaign_id) {
        Some(s) => s,
        None => return respond(stream, 404, r#"{"error":"campaign not found"}"#),
    };
    let session = match campaign_sessions.iter_mut().find(|s| s.id == session_id) {
        Some(s) => s,
        None => return respond(stream, 404, r#"{"error":"session not found"}"#),
    };

    session.present = present;
    session.absent = absent;

    let out = format!(
        r#"{{"session_id":"{}","present_count":{},"absent_count":{}}}"#,
        escape_json_string(&session.id),
        session.present.len(),
        session.absent.len()
    );
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_next_session(stream: &mut TcpStream, campaign_id: &str) -> std::io::Result<()> {
    {
        let campaigns_store = campaigns().lock().unwrap();
        if !campaigns_store.contains_key(campaign_id) {
            return respond(stream, 404, r#"{"error":"campaign not found"}"#);
        }
    }

    let store = sessions().lock().unwrap();
    let campaign_sessions = match store.get(campaign_id) {
        Some(s) if !s.is_empty() => s,
        _ => return respond(stream, 404, r#"{"error":"no sessions scheduled"}"#),
    };

    let next = campaign_sessions
        .iter()
        .min_by(|a, b| a.starts_at.cmp(&b.starts_at))
        .expect("checked non-empty above");

    let out = next_session_json(next);
    drop(store);

    respond(stream, 200, &out)
}
