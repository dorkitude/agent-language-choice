//! Deterministic audit log and export summaries for a campaign. Both
//! endpoints aggregate counts already tracked by [`crate::campaigns`],
//! [`crate::quests`], [`crate::npcs`], [`crate::sessions`], and
//! [`crate::inventory`] rather than introducing new storage.

use std::net::TcpStream;

use crate::campaigns;
use crate::http::respond;
use crate::inventory;
use crate::json::escape_json_string;
use crate::npcs;
use crate::quests;
use crate::sessions;

const SCHEMA_VERSION: i64 = 1;

pub(crate) fn handle_audit(stream: &mut TcpStream, campaign_id: &str) -> std::io::Result<()> {
    let (_, _, events) = match campaigns::campaign_summary(campaign_id) {
        Some(summary) => summary,
        None => return respond(stream, 404, r#"{"error":"campaign not found"}"#),
    };

    let quests_count = quests::quest_count(campaign_id);
    let npcs_count = npcs::npc_count(campaign_id);
    let sessions_count = sessions::session_count(campaign_id);

    let out = format!(
        r#"{{"campaign_id":"{}","events":{},"quests":{},"npcs":{},"sessions":{}}}"#,
        escape_json_string(campaign_id),
        events,
        quests_count,
        npcs_count,
        sessions_count
    );

    respond(stream, 200, &out)
}

pub(crate) fn handle_export(stream: &mut TcpStream, campaign_id: &str) -> std::io::Result<()> {
    let (name, characters, _) = match campaigns::campaign_summary(campaign_id) {
        Some(summary) => summary,
        None => return respond(stream, 404, r#"{"error":"campaign not found"}"#),
    };

    let quests_count = quests::quest_count(campaign_id);
    let npcs_count = npcs::npc_count(campaign_id);
    let inventory_items = inventory::inventory_item_count(campaign_id);
    let sessions_count = sessions::session_count(campaign_id);

    let out = format!(
        r#"{{"campaign_id":"{}","name":"{}","characters":{},"quests":{},"npcs":{},"inventory_items":{},"sessions":{},"schema_version":{}}}"#,
        escape_json_string(campaign_id),
        escape_json_string(&name),
        characters,
        quests_count,
        npcs_count,
        inventory_items,
        sessions_count,
        SCHEMA_VERSION
    );

    respond(stream, 200, &out)
}
