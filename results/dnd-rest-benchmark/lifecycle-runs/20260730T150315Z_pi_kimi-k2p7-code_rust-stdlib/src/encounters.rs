use std::collections::HashMap;

use crate::json::{extract_array_content, extract_int, extract_objects, extract_string};

/// XP thresholds for a single party member of a given level (easy, medium, hard,
/// deadly). Returns `None` for levels outside 1..=20.
pub fn xp_thresholds(level: i64) -> Option<(i64, i64, i64, i64)> {
    let table = [
        (1, 25, 50, 75, 100),
        (2, 50, 100, 150, 200),
        (3, 75, 150, 225, 400),
        (4, 125, 250, 375, 500),
        (5, 250, 500, 750, 1100),
        (6, 300, 600, 900, 1400),
        (7, 350, 750, 1100, 1700),
        (8, 450, 900, 1400, 2100),
        (9, 550, 1100, 1600, 2400),
        (10, 600, 1200, 1900, 2800),
        (11, 800, 1600, 2400, 3600),
        (12, 1000, 2000, 3000, 4500),
        (13, 1200, 2200, 3400, 5100),
        (14, 1250, 2500, 3800, 5700),
        (15, 1400, 2800, 4300, 6400),
        (16, 1600, 3200, 4800, 7200),
        (17, 2000, 3900, 5900, 8800),
        (18, 2100, 4200, 6300, 9500),
        (19, 2400, 4900, 7300, 10900),
        (20, 2800, 5700, 8500, 12700),
    ];
    for (lvl, e, m, h, d) in table {
        if lvl == level {
            return Some((e, m, h, d));
        }
    }
    None
}

/// XP value for a single monster of a given challenge rating.
///
/// Supports CRs from "0" through "5" using the standard 5e values.
pub fn xp_for_cr(cr: &str) -> Option<i64> {
    let table: HashMap<&str, i64> = [
        ("0", 10),
        ("1/8", 25),
        ("1/4", 50),
        ("1/2", 100),
        ("1", 200),
        ("2", 450),
        ("3", 700),
        ("4", 1100),
        ("5", 1800),
    ]
    .into_iter()
    .collect();
    table.get(cr).copied()
}

/// Encounter difficulty calculator for a party of level-3 characters.
///
/// This endpoint is intentionally restricted: every party member must have
/// `level == 3`. Thresholds are hardcoded to the level-3 values. The monster
/// multiplier is based on the total monster count.
pub fn handle_encounter(body: &str) -> Option<String> {
    let party_content = extract_array_content(body, "party")?;
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
        if level != 3 {
            return None;
        }
        easy += 75;
        medium += 150;
        hard += 225;
        deadly += 400;
    }

    let monsters_content = extract_array_content(body, "monsters")?;
    let monster_objects = extract_objects(monsters_content);
    if monster_objects.is_empty() {
        return None;
    }
    let mut base_xp = 0i64;
    let mut monster_count = 0i64;
    for obj in monster_objects {
        let cr = extract_string(obj, "cr")?;
        let count = extract_int(obj, "count")?;
        if count <= 0 {
            return None;
        }
        let xp = xp_for_cr(cr)?;
        base_xp += xp * count;
        monster_count += count;
    }

    let scaled_multiplier = match monster_count {
        1 => 10,
        2 => 15,
        3..=6 => 20,
        7..=10 => 25,
        11..=14 => 30,
        _ => 40,
    };

    let adjusted_xp = base_xp * scaled_multiplier / 10;
    let multiplier_display = match scaled_multiplier {
        10 => "1",
        15 => "1.5",
        20 => "2",
        25 => "2.5",
        30 => "3",
        _ => "4",
    };

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

    Some(format!(
        r#"{{"base_xp":{},"monster_count":{},"multiplier":{},"adjusted_xp":{},"difficulty":"{}","thresholds":{{"easy":{},"medium":{},"hard":{},"deadly":{}}}}}"#,
        base_xp, monster_count, multiplier_display, adjusted_xp, difficulty, easy, medium, hard, deadly
    ))
}
