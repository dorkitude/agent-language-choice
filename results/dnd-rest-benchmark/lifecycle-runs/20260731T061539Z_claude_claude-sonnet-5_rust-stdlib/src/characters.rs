//! Character-sheet math: ability modifiers, proficiency bonus, derived
//! stats (HP/AC), spell slots, long rest recovery, and carry capacity.
//! Every handler here is a pure function of the request body — no shared
//! state is read or written.

use std::net::TcpStream;

use crate::http::{bad_request, respond};
use crate::json::{as_int, escape_json_string, object_get, parse_json, Json};

/// Standard 5e ability modifier: `floor((score - 10) / 2)`.
pub(crate) fn ability_modifier(score: i64) -> i64 {
    (score - 10).div_euclid(2)
}

/// Proficiency bonus by character level (levels 1-20 only).
pub(crate) fn proficiency_bonus(level: i64) -> Option<i64> {
    match level {
        1..=4 => Some(2),
        5..=8 => Some(3),
        9..=12 => Some(4),
        13..=16 => Some(5),
        17..=20 => Some(6),
        _ => None,
    }
}

pub(crate) fn handle_spell_slots(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let class = match json.get("class").and_then(|v| v.as_str()) {
        Some(c) => c,
        None => return bad_request(stream, "invalid class"),
    };
    let level = match json.get("level").and_then(as_int) {
        Some(l) => l,
        None => return bad_request(stream, "invalid level"),
    };

    // Only one class/level combination is modeled today; expand this match
    // as more spellcasting tables are added.
    if class != "wizard" || level != 5 {
        return bad_request(stream, "unsupported class/level combination");
    }

    let out = format!(
        r#"{{"class":"{}","level":{},"slots":{{"1":4,"2":3,"3":2}}}}"#,
        escape_json_string(class),
        level
    );
    respond(stream, 200, &out)
}

pub(crate) fn handle_long_rest(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let level = match json.get("level").and_then(as_int) {
        Some(l) if l >= 1 && l <= 20 => l,
        _ => return bad_request(stream, "invalid level"),
    };
    let hp_max = match json.get("hp_max").and_then(as_int) {
        Some(h) if h >= 0 => h,
        _ => return bad_request(stream, "invalid hp_max"),
    };
    let _hp_current = match json.get("hp_current").and_then(as_int) {
        Some(h) if h >= 0 => h,
        _ => return bad_request(stream, "invalid hp_current"),
    };
    let hit_dice_spent = match json.get("hit_dice_spent").and_then(as_int) {
        Some(h) if h >= 0 => h,
        _ => return bad_request(stream, "invalid hit_dice_spent"),
    };
    let exhaustion_level = match json.get("exhaustion_level").and_then(as_int) {
        Some(e) if e >= 0 => e,
        _ => return bad_request(stream, "invalid exhaustion_level"),
    };

    let hp_current = hp_max;
    let recovered_dice = std::cmp::max(1, level / 2);
    let new_hit_dice_spent = std::cmp::max(0, hit_dice_spent - recovered_dice);
    let new_exhaustion_level = std::cmp::max(0, exhaustion_level - 1);

    let out = format!(
        r#"{{"hp_current":{},"hit_dice_spent":{},"exhaustion_level":{}}}"#,
        hp_current, new_hit_dice_spent, new_exhaustion_level
    );
    respond(stream, 200, &out)
}

pub(crate) fn handle_equipment_load(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let strength = match json.get("strength").and_then(as_int) {
        Some(s) if s >= 0 => s,
        _ => return bad_request(stream, "invalid strength"),
    };
    let weight = match json.get("weight").and_then(as_int) {
        Some(w) if w >= 0 => w,
        _ => return bad_request(stream, "invalid weight"),
    };

    let capacity = strength * 15;
    let encumbered = weight > capacity;

    let out = format!(
        r#"{{"capacity":{},"weight":{},"encumbered":{}}}"#,
        capacity, weight, encumbered
    );
    respond(stream, 200, &out)
}

pub(crate) fn handle_ability_modifier(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };
    let score = match json.get("score").and_then(as_int) {
        Some(s) if s >= 1 && s <= 30 => s,
        _ => return bad_request(stream, "invalid score"),
    };

    let modifier = ability_modifier(score);
    let out = format!(r#"{{"score":{},"modifier":{}}}"#, score, modifier);
    respond(stream, 200, &out)
}

pub(crate) fn handle_proficiency(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };
    let level = match json.get("level").and_then(as_int) {
        Some(l) if l >= 1 && l <= 20 => l,
        _ => return bad_request(stream, "invalid level"),
    };

    let bonus = match proficiency_bonus(level) {
        Some(b) => b,
        None => return bad_request(stream, "invalid level"),
    };

    let out = format!(r#"{{"level":{},"proficiency_bonus":{}}}"#, level, bonus);
    respond(stream, 200, &out)
}

pub(crate) fn handle_derived_stats(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let level = match json.get("level").and_then(as_int) {
        Some(l) if l >= 1 && l <= 20 => l,
        _ => return bad_request(stream, "invalid level"),
    };

    let abilities = match json.get("abilities").and_then(|v| v.as_object()) {
        Some(a) => a,
        None => return bad_request(stream, "missing abilities"),
    };

    let ability_names = ["str", "dex", "con", "int", "wis", "cha"];
    let mut scores: Vec<(&str, i64)> = Vec::new();
    for name in ability_names {
        let score = match object_get(abilities, name).and_then(as_int) {
            Some(s) if s >= 1 && s <= 30 => s,
            _ => return bad_request(stream, "invalid abilities"),
        };
        scores.push((name, score));
    }

    let modifiers: Vec<(&str, i64)> = scores
        .iter()
        .map(|(name, score)| (*name, ability_modifier(*score)))
        .collect();

    let con_modifier = modifiers.iter().find(|(n, _)| *n == "con").unwrap().1;
    let dex_modifier = modifiers.iter().find(|(n, _)| *n == "dex").unwrap().1;

    let bonus = match proficiency_bonus(level) {
        Some(b) => b,
        None => return bad_request(stream, "invalid level"),
    };

    let armor = match json.get("armor").and_then(|v| v.as_object()) {
        Some(a) => a,
        None => return bad_request(stream, "missing armor"),
    };

    let armor_base = match object_get(armor, "base").and_then(as_int) {
        Some(b) => b,
        None => return bad_request(stream, "invalid armor"),
    };
    let dex_cap = match object_get(armor, "dex_cap").and_then(as_int) {
        Some(c) => c,
        None => return bad_request(stream, "invalid armor"),
    };
    let shield = match object_get(armor, "shield") {
        Some(Json::Bool(b)) => *b,
        _ => return bad_request(stream, "invalid armor"),
    };

    let hp_max = level * (6 + con_modifier);
    let shield_bonus = if shield { 2 } else { 0 };
    let armor_class = armor_base + dex_modifier.min(dex_cap) + shield_bonus;

    let modifiers_json = modifiers
        .iter()
        .map(|(name, m)| format!(r#""{}":{}"#, name, m))
        .collect::<Vec<_>>()
        .join(",");

    let out = format!(
        r#"{{"level":{},"proficiency_bonus":{},"hp_max":{},"armor_class":{},"modifiers":{{{}}}}}"#,
        level, bonus, hp_max, armor_class, modifiers_json
    );
    respond(stream, 200, &out)
}
