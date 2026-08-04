//! Campaign quest tracking: create quests with a milestone checklist, mark
//! milestones complete, and summarize quest counts by status per campaign.
//! Backing store is an in-memory map keyed by campaign id (each campaign
//! owns a `Vec<Quest>`), separate from [`crate::campaigns`]'s own store but
//! validated against it the same way [`crate::dm_tools`] validates
//! `campaign_id`.

use std::collections::HashMap;
use std::net::TcpStream;
use std::sync::{Mutex, OnceLock};

use crate::campaigns::campaigns;
use crate::http::{bad_request, respond};
use crate::json::{escape_json_string, parse_json};

const STATUSES: [&str; 3] = ["active", "completed", "blocked"];

pub(crate) struct Quest {
    id: String,
    title: String,
    status: String,
    milestones: Vec<String>,
    done: Vec<String>,
}

pub(crate) fn quests() -> &'static Mutex<HashMap<String, Vec<Quest>>> {
    static QUESTS: OnceLock<Mutex<HashMap<String, Vec<Quest>>>> = OnceLock::new();
    QUESTS.get_or_init(|| Mutex::new(HashMap::new()))
}

pub(crate) fn clear() {
    quests().lock().unwrap().clear();
}

pub(crate) fn quest_count(campaign_id: &str) -> i64 {
    let store = quests().lock().unwrap();
    store.get(campaign_id).map(|qs| qs.len() as i64).unwrap_or(0)
}

/// Returns `(active, completed, blocked)` quest counts for a campaign.
pub(crate) fn status_counts(campaign_id: &str) -> (i64, i64, i64) {
    let store = quests().lock().unwrap();
    let mut active = 0_i64;
    let mut completed = 0_i64;
    let mut blocked = 0_i64;
    if let Some(campaign_quests) = store.get(campaign_id) {
        for q in campaign_quests {
            match q.status.as_str() {
                "active" => active += 1,
                "completed" => completed += 1,
                "blocked" => blocked += 1,
                _ => {}
            }
        }
    }
    (active, completed, blocked)
}

/// Quests that are not yet completed (active or blocked).
pub(crate) fn open_quest_count(campaign_id: &str) -> i64 {
    let (active, _completed, blocked) = status_counts(campaign_id);
    active + blocked
}

fn create_json(q: &Quest) -> String {
    format!(
        r#"{{"id":"{}","title":"{}","status":"{}","milestones_total":{},"milestones_done":{}}}"#,
        escape_json_string(&q.id),
        escape_json_string(&q.title),
        escape_json_string(&q.status),
        q.milestones.len(),
        q.done.len()
    )
}

fn progress_json(q: &Quest) -> String {
    format!(
        r#"{{"id":"{}","status":"{}","milestones_total":{},"milestones_done":{}}}"#,
        escape_json_string(&q.id),
        escape_json_string(&q.status),
        q.milestones.len(),
        q.done.len()
    )
}

pub(crate) fn handle_create_quest(
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
    let title = match json.get("title").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid title"),
    };
    let status = match json.get("status").and_then(|v| v.as_str()) {
        Some(s) if STATUSES.contains(&s) => s.to_string(),
        _ => return bad_request(stream, "invalid status"),
    };
    let milestones_json = match json.get("milestones").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return bad_request(stream, "invalid milestones"),
    };
    let mut milestones = Vec::new();
    for m in milestones_json {
        match m.as_str() {
            Some(s) if !s.is_empty() => milestones.push(s.to_string()),
            _ => return bad_request(stream, "invalid milestones"),
        }
    }

    {
        let campaigns_store = campaigns().lock().unwrap();
        if !campaigns_store.contains_key(campaign_id) {
            return respond(stream, 404, r#"{"error":"campaign not found"}"#);
        }
    }

    let mut store = quests().lock().unwrap();
    let campaign_quests = store.entry(campaign_id.to_string()).or_insert_with(Vec::new);
    if campaign_quests.iter().any(|q| q.id == id) {
        return respond(stream, 409, r#"{"error":"quest already exists"}"#);
    }

    let quest = Quest {
        id,
        title,
        status,
        milestones,
        done: Vec::new(),
    };
    let out = create_json(&quest);
    campaign_quests.push(quest);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_quest_progress(
    stream: &mut TcpStream,
    campaign_id: &str,
    quest_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let completed_json = match json.get("completed").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return bad_request(stream, "invalid completed"),
    };
    let mut completed = Vec::new();
    for m in completed_json {
        match m.as_str() {
            Some(s) if !s.is_empty() => completed.push(s.to_string()),
            _ => return bad_request(stream, "invalid completed"),
        }
    }

    let mut store = quests().lock().unwrap();
    let campaign_quests = match store.get_mut(campaign_id) {
        Some(qs) => qs,
        None => return respond(stream, 404, r#"{"error":"campaign not found"}"#),
    };
    let quest = match campaign_quests.iter_mut().find(|q| q.id == quest_id) {
        Some(q) => q,
        None => return respond(stream, 404, r#"{"error":"quest not found"}"#),
    };

    for milestone in &completed {
        if !quest.milestones.contains(milestone) {
            return bad_request(stream, "unknown milestone");
        }
    }
    for milestone in completed {
        if !quest.done.contains(&milestone) {
            quest.done.push(milestone);
        }
    }
    if !quest.milestones.is_empty() && quest.done.len() == quest.milestones.len() {
        quest.status = "completed".to_string();
    }

    let out = progress_json(quest);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_quest_summary(stream: &mut TcpStream, campaign_id: &str) -> std::io::Result<()> {
    let campaigns_store = campaigns().lock().unwrap();
    if !campaigns_store.contains_key(campaign_id) {
        return respond(stream, 404, r#"{"error":"campaign not found"}"#);
    }
    drop(campaigns_store);

    let (active, completed, blocked) = status_counts(campaign_id);

    let out = format!(
        r#"{{"campaign_id":"{}","active":{},"completed":{},"blocked":{}}}"#,
        escape_json_string(campaign_id),
        active,
        completed,
        blocked
    );
    respond(stream, 200, &out)
}
