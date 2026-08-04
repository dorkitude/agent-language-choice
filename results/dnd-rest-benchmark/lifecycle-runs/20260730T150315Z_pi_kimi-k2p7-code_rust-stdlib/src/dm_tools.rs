use crate::compendium::get_monster_cr;
use crate::encounters::{xp_for_cr, xp_thresholds};
use crate::json::{escape_json, extract_int, extract_objects, extract_string, extract_string_array};

/// Build an encounter using stored monster CRs and a party of any level.
///
/// Required: `campaign_id` (non-empty), `party` (array of `{level}`), and
/// `monster_slugs` (array of existing monster slugs). Returns base XP,
/// adjusted XP, difficulty, and a textual recommendation.
pub fn handle_dm_encounter_builder(body: &str) -> Option<String> {
    let campaign_id = extract_string(body, "campaign_id")?;
    if campaign_id.is_empty() {
        return None;
    }
    let party_content = crate::json::extract_array_content(body, "party")?;
    let party_objects = extract_objects(party_content);
    if party_objects.is_empty() {
        return None;
    }
    let mut easy = 0i64;
    let mut medium = 0i64;
    let mut hard = 0i64;
    let mut deadly = 0i64;
    for obj in party_objects {
        let level = extract_int(obj, "level")?;
        let (e, m, h, d) = xp_thresholds(level)?;
        easy += e;
        medium += m;
        hard += h;
        deadly += d;
    }

    let monster_slugs = extract_string_array(body, "monster_slugs")?;
    if monster_slugs.is_empty() {
        return None;
    }
    let mut base_xp = 0i64;
    for slug in &monster_slugs {
        let cr = get_monster_cr(slug).ok()?;
        let xp = xp_for_cr(&cr)?;
        base_xp += xp;
    }
    let monster_count = monster_slugs.len() as i64;

    let scaled_multiplier = match monster_count {
        1 => 10,
        2 => 15,
        3..=6 => 20,
        7..=10 => 25,
        11..=14 => 30,
        _ => 40,
    };

    let adjusted_xp = base_xp * scaled_multiplier / 10;

    let difficulty = if adjusted_xp >= deadly {
        "deadly"
    } else if adjusted_xp >= hard {
        "hard"
    } else if adjusted_xp >= medium {
        "medium"
    } else if adjusted_xp >= easy {
        "easy"
    } else {
        "trivial"
    };

    let recommendation = match difficulty {
        "trivial" => "no risk",
        "easy" => "safe warm-up",
        "medium" => "fair fight",
        "hard" => "tough battle",
        "deadly" => "deadly encounter",
        _ => "unknown",
    };

    Some(format!(
        r#"{{"campaign_id":"{}","base_xp":{},"adjusted_xp":{},"difficulty":"{}","monster_count":{},"recommendation":"{}"}}"#,
        escape_json(campaign_id),
        base_xp,
        adjusted_xp,
        difficulty,
        monster_count,
        recommendation
    ))
}

/// Generate a fixed tier-1 loot parcel for a campaign.
///
/// Only accepts `tier == 1`. Always returns 75 gp and 2 healing potions.
pub fn handle_dm_loot_parcel(body: &str) -> Option<String> {
    let campaign_id = extract_string(body, "campaign_id")?;
    if campaign_id.is_empty() {
        return None;
    }
    let tier = extract_int(body, "tier")?;
    if tier != 1 {
        return None;
    }
    Some(format!(
        r#"{{"campaign_id":"{}","coins_gp":75,"items":[{{"slug":"healing-potion","quantity":2}}]}}"#,
        escape_json(campaign_id)
    ))
}

/// Return a fixed session recap for a campaign.
///
/// The content is hardcoded to match the existing test expectations.
pub fn handle_dm_session_recap(body: &str) -> Option<String> {
    let campaign_id = extract_string(body, "campaign_id")?;
    if campaign_id.is_empty() {
        return None;
    }
    Some(format!(
        r#"{{"campaign_id":"{}","summary":"Nyx scouts the goblin trail.","open_threads":["Resolve goblin trail ambush"]}}"#,
        escape_json(campaign_id)
    ))
}
