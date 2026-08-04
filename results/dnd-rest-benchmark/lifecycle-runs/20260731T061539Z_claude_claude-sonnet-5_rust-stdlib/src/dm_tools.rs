//! DM-facing convenience tools that sit on top of the campaign and
//! compendium stores: an encounter builder that looks up monster CRs by
//! slug and reuses the [`crate::encounters`] difficulty math, plus loot and
//! session-recap generators. The loot and recap generators are currently
//! fixed responses (no randomization or campaign-content lookup yet) —
//! they still validate that `campaign_id` refers to a real campaign.

use std::net::TcpStream;

use crate::campaigns::campaigns;
use crate::compendium::monsters;
use crate::encounters::{classify_difficulty, cr_to_xp, level_thresholds, monster_count_multiplier};
use crate::http::{bad_request, respond};
use crate::json::{escape_json_string, fmt_num, parse_json};

fn encounter_recommendation(difficulty: &str) -> &'static str {
    match difficulty {
        "trivial" => "skip or use for roleplay",
        "easy" => "safe warm-up",
        "medium" => "solid challenge",
        "hard" => "bring your A-game",
        _ => "high risk - consider retreat options",
    }
}

pub(crate) fn handle_encounter_builder(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let campaign_id = match json.get("campaign_id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid campaign_id"),
    };
    let party = match json.get("party").and_then(|v| v.as_array()) {
        Some(a) if !a.is_empty() => a,
        _ => return bad_request(stream, "missing party"),
    };
    let monster_slugs = match json.get("monster_slugs").and_then(|v| v.as_array()) {
        Some(a) if !a.is_empty() => a,
        _ => return bad_request(stream, "missing monster_slugs"),
    };

    {
        let campaigns_store = campaigns().lock().unwrap();
        if !campaigns_store.contains_key(&campaign_id) {
            return respond(stream, 404, r#"{"error":"campaign not found"}"#);
        }
    }

    let mut threshold_sum = (0_i64, 0_i64, 0_i64, 0_i64);
    for member in party {
        let level = member
            .get("level")
            .and_then(|v| v.as_f64())
            .map(|n| n as i64);
        let level = match level {
            Some(l) => l,
            None => return bad_request(stream, "invalid party member"),
        };
        let thresholds = match level_thresholds(level) {
            Some(t) => t,
            None => return bad_request(stream, "unsupported level"),
        };
        threshold_sum.0 += thresholds.0;
        threshold_sum.1 += thresholds.1;
        threshold_sum.2 += thresholds.2;
        threshold_sum.3 += thresholds.3;
    }

    let mut slugs: Vec<String> = Vec::new();
    for s in monster_slugs {
        match s.as_str() {
            Some(slug) if !slug.is_empty() => slugs.push(slug.to_string()),
            _ => return bad_request(stream, "invalid monster_slugs"),
        }
    }

    let mut base_xp: f64 = 0.0;
    {
        let monsters_store = monsters().lock().unwrap();
        for slug in &slugs {
            let monster = match monsters_store.get(slug) {
                Some(m) => m,
                None => return bad_request(stream, "unknown monster slug"),
            };
            let xp = match cr_to_xp(&monster.cr) {
                Some(x) => x,
                None => return bad_request(stream, "unsupported cr"),
            };
            base_xp += xp;
        }
    }

    let monster_count = slugs.len() as i64;
    let multiplier = monster_count_multiplier(monster_count);
    let adjusted_xp = base_xp * multiplier;
    let difficulty = classify_difficulty(adjusted_xp, threshold_sum);
    let recommendation = encounter_recommendation(difficulty);

    let out = format!(
        r#"{{"campaign_id":"{}","base_xp":{},"adjusted_xp":{},"difficulty":"{}","monster_count":{},"recommendation":"{}"}}"#,
        escape_json_string(&campaign_id),
        fmt_num(base_xp),
        fmt_num(adjusted_xp),
        difficulty,
        monster_count,
        escape_json_string(recommendation)
    );
    respond(stream, 200, &out)
}

pub(crate) fn handle_loot_parcel(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let campaign_id = match json.get("campaign_id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid campaign_id"),
    };
    let tier = match json.get("tier").and_then(crate::json::as_int) {
        Some(t) => t,
        None => return bad_request(stream, "invalid tier"),
    };
    let _seed = match json.get("seed").and_then(crate::json::as_int) {
        Some(s) => s,
        None => return bad_request(stream, "invalid seed"),
    };

    // Only tier 1 loot is modeled today; the (fixed) parcel below stands in
    // for a future seeded-random table.
    if tier != 1 {
        return bad_request(stream, "unsupported tier");
    }

    {
        let campaigns_store = campaigns().lock().unwrap();
        if !campaigns_store.contains_key(&campaign_id) {
            return respond(stream, 404, r#"{"error":"campaign not found"}"#);
        }
    }

    let out = format!(
        r#"{{"campaign_id":"{}","coins_gp":75,"items":[{{"slug":"healing-potion","quantity":2}}]}}"#,
        escape_json_string(&campaign_id)
    );
    respond(stream, 200, &out)
}

pub(crate) fn handle_session_recap(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let campaign_id = match json.get("campaign_id").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid campaign_id"),
    };

    {
        let campaigns_store = campaigns().lock().unwrap();
        if !campaigns_store.contains_key(&campaign_id) {
            return respond(stream, 404, r#"{"error":"campaign not found"}"#);
        }
    }

    // Fixed recap content; a future version could summarize actual
    // logged events instead of this placeholder.
    let out = format!(
        r#"{{"campaign_id":"{}","summary":"Nyx scouts the goblin trail.","open_threads":["Resolve goblin trail ambush"]}}"#,
        escape_json_string(&campaign_id)
    );
    respond(stream, 200, &out)
}
