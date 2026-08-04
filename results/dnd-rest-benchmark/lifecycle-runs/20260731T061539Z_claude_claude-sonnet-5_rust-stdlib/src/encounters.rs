//! Encounter difficulty math shared by the standalone `/v1/encounters/adjusted-xp`
//! endpoint and the DM encounter builder ([`crate::dm_tools`]): challenge-rating
//! to XP conversion, the monster-count multiplier table, and per-level XP
//! thresholds.

use std::net::TcpStream;

use crate::http::{bad_request, respond};
use crate::json::{fmt_num, parse_json};

/// XP value for a single monster of the given challenge rating. Only the
/// ratings needed by the current encounter tables are supported; anything
/// else is rejected by callers as `"unsupported cr"`.
pub(crate) fn cr_to_xp(cr: &str) -> Option<f64> {
    match cr {
        "0" => Some(10.0),
        "1/8" => Some(25.0),
        "1/4" => Some(50.0),
        "1/2" => Some(100.0),
        "1" => Some(200.0),
        "2" => Some(450.0),
        "3" => Some(700.0),
        "4" => Some(1100.0),
        "5" => Some(1800.0),
        _ => None,
    }
}

/// DMG-style multiplier applied to total monster XP based on how many
/// monsters are in the encounter (more monsters are harder than their raw
/// XP sum implies).
pub(crate) fn monster_count_multiplier(count: i64) -> f64 {
    match count {
        1 => 1.0,
        2 => 1.5,
        3..=6 => 2.0,
        7..=10 => 2.5,
        11..=14 => 3.0,
        _ => 4.0,
    }
}

/// `(easy, medium, hard, deadly)` XP thresholds for one party member at
/// `level`. Only level 3 is currently supported.
pub(crate) fn level_thresholds(level: i64) -> Option<(i64, i64, i64, i64)> {
    match level {
        3 => Some((75, 150, 225, 400)),
        _ => None,
    }
}

/// Classifies `adjusted_xp` against summed party thresholds.
pub(crate) fn classify_difficulty(adjusted_xp: f64, thresholds: (i64, i64, i64, i64)) -> &'static str {
    if adjusted_xp >= thresholds.3 as f64 {
        "deadly"
    } else if adjusted_xp >= thresholds.2 as f64 {
        "hard"
    } else if adjusted_xp >= thresholds.1 as f64 {
        "medium"
    } else if adjusted_xp >= thresholds.0 as f64 {
        "easy"
    } else {
        "trivial"
    }
}

pub(crate) fn handle_adjusted_xp(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let party = match json.get("party").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return bad_request(stream, "missing party"),
    };
    let monsters = match json.get("monsters").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return bad_request(stream, "missing monsters"),
    };

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

    let mut base_xp: f64 = 0.0;
    let mut monster_count: i64 = 0;
    for monster in monsters {
        let cr = match monster.get("cr").and_then(|v| v.as_str()) {
            Some(s) => s,
            None => return bad_request(stream, "invalid monster"),
        };
        let count = monster
            .get("count")
            .and_then(|v| v.as_f64())
            .map(|n| n as i64);
        let count = match count {
            Some(c) if c > 0 => c,
            _ => return bad_request(stream, "invalid monster count"),
        };
        let xp = match cr_to_xp(cr) {
            Some(x) => x,
            None => return bad_request(stream, "unsupported cr"),
        };
        base_xp += xp * (count as f64);
        monster_count += count;
    }

    let multiplier = monster_count_multiplier(monster_count);
    let adjusted_xp = base_xp * multiplier;
    let difficulty = classify_difficulty(adjusted_xp, threshold_sum);

    let out = format!(
        r#"{{"base_xp":{},"monster_count":{},"multiplier":{},"adjusted_xp":{},"difficulty":"{}","thresholds":{{"easy":{},"medium":{},"hard":{},"deadly":{}}}}}"#,
        fmt_num(base_xp),
        monster_count,
        fmt_num(multiplier),
        fmt_num(adjusted_xp),
        difficulty,
        threshold_sum.0,
        threshold_sum.1,
        threshold_sum.2,
        threshold_sum.3
    );
    respond(stream, 200, &out)
}
