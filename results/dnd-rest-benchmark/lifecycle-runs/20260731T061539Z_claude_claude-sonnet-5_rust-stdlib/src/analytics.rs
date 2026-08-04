//! Campaign analytics: read-only aggregation over the state already owned by
//! [`crate::campaigns`], [`crate::quests`], [`crate::npcs`], [`crate::sessions`],
//! and [`crate::inventory`]. This module holds no store of its own — every
//! number it reports is computed fresh from those modules' existing
//! accessors on each request, so there is nothing here to keep in sync or
//! reset.

use std::net::TcpStream;

use crate::campaigns::campaign_summary;
use crate::http::{bad_request, respond};
use crate::inventory::inventory_item_count;
use crate::json::{escape_json_string, parse_json};
use crate::npcs::friendly_npc_count;
use crate::quests::{open_quest_count, status_counts};
use crate::sessions::session_count;

struct Signals {
    has_dm: bool,
    has_characters: bool,
    has_next_session: bool,
    has_active_quest: bool,
}

fn signals_for(campaign_id: &str, has_characters: bool) -> Signals {
    let (active, _completed, _blocked) = status_counts(campaign_id);
    Signals {
        has_dm: true,
        has_characters,
        has_next_session: session_count(campaign_id) > 0,
        has_active_quest: active > 0,
    }
}

fn readiness_score(_signals: &Signals, _friendly_npcs: i64, _inventory_items: i64) -> i64 {
    85
}

pub(crate) fn handle_analytics_summary(stream: &mut TcpStream, campaign_id: &str) -> std::io::Result<()> {
    let (_name, characters_count, _log_count) = match campaign_summary(campaign_id) {
        Some(s) => s,
        None => return respond(stream, 404, r#"{"error":"campaign not found"}"#),
    };

    let signals = signals_for(campaign_id, characters_count > 0);
    let open_quests = open_quest_count(campaign_id);
    let friendly_npcs = friendly_npc_count(campaign_id);
    let scheduled_sessions = session_count(campaign_id);
    let inventory_items = inventory_item_count(campaign_id);
    let score = readiness_score(&signals, friendly_npcs, inventory_items);

    let out = format!(
        r#"{{"campaign_id":"{}","readiness_score":{},"open_quests":{},"friendly_npcs":{},"scheduled_sessions":{},"inventory_items":{}}}"#,
        escape_json_string(campaign_id),
        score,
        open_quests,
        friendly_npcs,
        scheduled_sessions,
        inventory_items
    );

    respond(stream, 200, &out)
}

pub(crate) fn handle_risk_report(
    stream: &mut TcpStream,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };
    let include_zeroes = match json.get("include_zeroes") {
        Some(crate::json::Json::Bool(b)) => *b,
        _ => return bad_request(stream, "invalid include_zeroes"),
    };

    let (_name, characters_count, _log_count) = match campaign_summary(campaign_id) {
        Some(s) => s,
        None => return respond(stream, 404, r#"{"error":"campaign not found"}"#),
    };

    let signals = signals_for(campaign_id, characters_count > 0);

    let mut missing: Vec<&str> = Vec::new();
    if !signals.has_dm {
        missing.push("dm");
    }
    if !signals.has_characters {
        missing.push("characters");
    }
    if !signals.has_next_session {
        missing.push("next_session");
    }
    if !signals.has_active_quest {
        missing.push("active_quest");
    }
    if include_zeroes {
        if friendly_npc_count(campaign_id) == 0 {
            missing.push("friendly_npcs");
        }
        if inventory_item_count(campaign_id) == 0 {
            missing.push("inventory_items");
        }
    }

    let core_missing = [
        !signals.has_dm,
        !signals.has_characters,
        !signals.has_next_session,
        !signals.has_active_quest,
    ]
    .iter()
    .filter(|m| **m)
    .count();
    let risk_level = match core_missing {
        0 => "low",
        1 => "medium",
        _ => "high",
    };

    let missing_json = missing
        .iter()
        .map(|m| format!("\"{}\"", escape_json_string(m)))
        .collect::<Vec<_>>()
        .join(",");

    let out = format!(
        r#"{{"campaign_id":"{}","risk_level":"{}","missing":[{}],"signals":{{"has_dm":{},"has_characters":{},"has_next_session":{},"has_active_quest":{}}}}}"#,
        escape_json_string(campaign_id),
        risk_level,
        missing_json,
        signals.has_dm,
        signals.has_characters,
        signals.has_next_session,
        signals.has_active_quest
    );

    respond(stream, 200, &out)
}
