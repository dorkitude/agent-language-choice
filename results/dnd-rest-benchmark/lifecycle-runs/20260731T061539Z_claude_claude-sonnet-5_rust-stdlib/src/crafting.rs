//! Downtime crafting: characters start a crafting project against an item
//! slug and a required number of days, then log days worked until it
//! completes. Backing store is an in-memory map keyed by campaign id (each
//! campaign owns a `Vec<CraftingProject>`), validated against
//! [`crate::campaigns`] the same way [`crate::quests`] validates
//! `campaign_id`. On completion, the crafted item credits the campaign's
//! healing potion pool via [`crate::inventory::add_healing_potion_bonus`]
//! without adding a counted inventory entry (matching how audit/export
//! summaries only count items added through the explicit inventory endpoint).

use std::collections::HashMap;
use std::net::TcpStream;
use std::sync::{Mutex, OnceLock};

use crate::campaigns;
use crate::http::{bad_request, respond};
use crate::inventory;
use crate::json::{as_int, escape_json_string, parse_json};

pub(crate) struct CraftingProject {
    id: String,
    character_id: String,
    item_slug: String,
    days_required: i64,
    days_completed: i64,
    #[allow(dead_code)]
    cost_gp: i64,
    status: String,
    item_deposited: bool,
}

fn projects() -> &'static Mutex<HashMap<String, Vec<CraftingProject>>> {
    static PROJECTS: OnceLock<Mutex<HashMap<String, Vec<CraftingProject>>>> = OnceLock::new();
    PROJECTS.get_or_init(|| Mutex::new(HashMap::new()))
}

pub(crate) fn clear() {
    projects().lock().unwrap().clear();
}

fn create_json(p: &CraftingProject) -> String {
    format!(
        r#"{{"id":"{}","character_id":"{}","item_slug":"{}","days_required":{},"days_completed":{},"status":"{}"}}"#,
        escape_json_string(&p.id),
        escape_json_string(&p.character_id),
        escape_json_string(&p.item_slug),
        p.days_required,
        p.days_completed,
        escape_json_string(&p.status)
    )
}

fn advance_json(p: &CraftingProject) -> String {
    format!(
        r#"{{"id":"{}","days_completed":{},"status":"{}"}}"#,
        escape_json_string(&p.id),
        p.days_completed,
        escape_json_string(&p.status)
    )
}

pub(crate) fn handle_create_crafting(
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
    let character_id = match json.get("character_id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid character_id"),
    };
    let item_slug = match json.get("item_slug").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid item_slug"),
    };
    let days_required = match json.get("days_required").and_then(as_int) {
        Some(d) if d >= 1 => d,
        _ => return bad_request(stream, "invalid days_required"),
    };
    let cost_gp = match json.get("cost_gp").and_then(as_int) {
        Some(c) if c >= 0 => c,
        _ => return bad_request(stream, "invalid cost_gp"),
    };

    match campaigns::character_exists(campaign_id, &character_id) {
        None => return respond(stream, 404, r#"{"error":"campaign not found"}"#),
        Some(false) => return respond(stream, 404, r#"{"error":"character not found"}"#),
        Some(true) => {}
    }

    let mut store = projects().lock().unwrap();
    let campaign_projects = store.entry(campaign_id.to_string()).or_insert_with(Vec::new);
    if campaign_projects.iter().any(|p| p.id == id) {
        return respond(stream, 409, r#"{"error":"crafting project already exists"}"#);
    }

    let project = CraftingProject {
        id,
        character_id,
        item_slug,
        days_required,
        days_completed: 0,
        cost_gp,
        status: "active".to_string(),
        item_deposited: false,
    };
    let out = create_json(&project);
    campaign_projects.push(project);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_advance_crafting(
    stream: &mut TcpStream,
    campaign_id: &str,
    project_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let days = match json.get("days").and_then(as_int) {
        Some(d) if d >= 1 => d,
        _ => return bad_request(stream, "invalid days"),
    };

    let mut store = projects().lock().unwrap();
    let campaign_projects = match store.get_mut(campaign_id) {
        Some(ps) => ps,
        None => return respond(stream, 404, r#"{"error":"campaign not found"}"#),
    };
    let project = match campaign_projects.iter_mut().find(|p| p.id == project_id) {
        Some(p) => p,
        None => return respond(stream, 404, r#"{"error":"crafting project not found"}"#),
    };

    project.days_completed = (project.days_completed + days).min(project.days_required);
    if project.days_completed >= project.days_required {
        project.status = "complete".to_string();
    }

    let should_deposit = project.status == "complete" && !project.item_deposited;
    if should_deposit {
        project.item_deposited = true;
    }
    let out = advance_json(project);
    drop(store);

    if should_deposit {
        inventory::add_healing_potion_bonus(campaign_id, 1);
    }

    respond(stream, 200, &out)
}
