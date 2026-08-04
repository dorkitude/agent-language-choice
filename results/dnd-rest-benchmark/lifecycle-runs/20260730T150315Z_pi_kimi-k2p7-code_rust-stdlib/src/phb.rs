use crate::json::{extract_bool, extract_int, extract_object_content, extract_string};

/// Compute the D&D 5e ability modifier for a score in the range 1..=30.
pub fn modifier(score: i64) -> i64 {
    let diff = score - 10;
    if diff >= 0 || diff % 2 == 0 {
        diff / 2
    } else {
        diff / 2 - 1
    }
}

/// Compute the proficiency bonus for a character level in the range 1..=20.
pub fn proficiency_bonus(level: i64) -> i64 {
    match level {
        1..=4 => 2,
        5..=8 => 3,
        9..=12 => 4,
        13..=16 => 5,
        17..=20 => 6,
        _ => 0,
    }
}

/// Return the ability modifier for a single ability score.
pub fn handle_ability_modifier(body: &str) -> Option<String> {
    let score = extract_int(body, "score")?;
    if score < 1 || score > 30 {
        return None;
    }
    let m = modifier(score);
    Some(format!(r#"{{"score":{},"modifier":{}}}"#, score, m))
}

/// Return the proficiency bonus for a character level.
pub fn handle_proficiency(body: &str) -> Option<String> {
    let level = extract_int(body, "level")?;
    if level < 1 || level > 20 {
        return None;
    }
    let bonus = proficiency_bonus(level);
    Some(format!(
        r#"{{"level":{},"proficiency_bonus":{}}}"#,
        level, bonus
    ))
}

/// Derive hit points, armor class, and modifiers from level, abilities, and
/// armor.
///
/// Expected body shape:
/// ```json
/// {
///   "level": 1..=20,
///   "abilities": { "str": 1..=30, "dex": ..., "con": ..., "int": ..., "wis": ..., "cha": ... },
///   "armor": { "base": int, "shield": bool, "dex_cap": int }
/// }
/// ```
/// HP is `level * (6 + con_modifier)`. AC is `base + min(dex_modifier, dex_cap)
/// + (shield ? 2 : 0)`.
pub fn handle_derived_stats(body: &str) -> Option<String> {
    let level = extract_int(body, "level")?;
    if level < 1 || level > 20 {
        return None;
    }
    let abilities = extract_object_content(body, "abilities")?;
    let str = extract_int(abilities, "str")?;
    let dex = extract_int(abilities, "dex")?;
    let con = extract_int(abilities, "con")?;
    let int = extract_int(abilities, "int")?;
    let wis = extract_int(abilities, "wis")?;
    let cha = extract_int(abilities, "cha")?;
    if str < 1 || str > 30
        || dex < 1 || dex > 30
        || con < 1 || con > 30
        || int < 1 || int > 30
        || wis < 1 || wis > 30
        || cha < 1 || cha > 30
    {
        return None;
    }

    let armor = extract_object_content(body, "armor")?;
    let base = extract_int(armor, "base")?;
    let shield = extract_bool(armor, "shield")?;
    let dex_cap = extract_int(armor, "dex_cap")?;

    let mod_str = modifier(str);
    let mod_dex = modifier(dex);
    let mod_con = modifier(con);
    let mod_int = modifier(int);
    let mod_wis = modifier(wis);
    let mod_cha = modifier(cha);

    let hp_max = level * (6 + mod_con);
    let shield_bonus = if shield { 2 } else { 0 };
    let armor_class = base + mod_dex.min(dex_cap) + shield_bonus;

    Some(format!(
        r#"{{"level":{},"proficiency_bonus":{},"hp_max":{},"armor_class":{},"modifiers":{{"str":{},"dex":{},"con":{},"int":{},"wis":{},"cha":{}}}}}"#,
        level,
        proficiency_bonus(level),
        hp_max,
        armor_class,
        mod_str,
        mod_dex,
        mod_con,
        mod_int,
        mod_wis,
        mod_cha
    ))
}

/// Return the fixed spell-slot table for a level-5 wizard.
///
/// This endpoint is intentionally narrow: it only accepts `class: wizard` and
/// `level: 5`.
pub fn handle_spell_slots(body: &str) -> Option<String> {
    let class = extract_string(body, "class")?;
    let level = extract_int(body, "level")?;
    if class != "wizard" || level != 5 {
        return None;
    }
    Some(r#"{"class":"wizard","level":5,"slots":{"1":4,"2":3,"3":2}}"#.to_string())
}

/// Apply a long rest to a character.
///
/// Validation: `level >= 1`, `hp_max >= 1`, `hp_current` between 0 and
/// `hp_max`, `hit_dice_spent >= 0`, `exhaustion_level >= 0`.
///
/// Effects: HP restored to maximum, hit dice spent reduced by `max(level/2, 1)`
/// (but not below 0), exhaustion reduced by 1 (but not below 0).
pub fn handle_long_rest(body: &str) -> Option<String> {
    let level = extract_int(body, "level")?;
    let hp_current = extract_int(body, "hp_current")?;
    let hp_max = extract_int(body, "hp_max")?;
    let hit_dice_spent = extract_int(body, "hit_dice_spent")?;
    let exhaustion_level = extract_int(body, "exhaustion_level")?;
    if level < 1 || hp_max < 1 || hp_current < 0 || hp_current > hp_max || hit_dice_spent < 0 || exhaustion_level < 0 {
        return None;
    }
    let restored = (level / 2).max(1);
    let new_hp = hp_max;
    let new_spent = (hit_dice_spent - restored).max(0);
    let new_exhaustion = (exhaustion_level - 1).max(0);
    Some(format!(
        r#"{{"hp_current":{},"hit_dice_spent":{},"exhaustion_level":{}}}"#,
        new_hp, new_spent, new_exhaustion
    ))
}

/// Calculate carrying capacity and encumbered status.
///
/// Capacity is `strength * 15`. `weight` may be any value; encumbered is simply
/// `weight > capacity`.
pub fn handle_equipment_load(body: &str) -> Option<String> {
    let strength = extract_int(body, "strength")?;
    let weight = extract_int(body, "weight")?;
    if strength < 1 {
        return None;
    }
    let capacity = strength * 15;
    let encumbered = weight > capacity;
    Some(format!(
        r#"{{"capacity":{},"weight":{},"encumbered":{}}}"#,
        capacity, weight, encumbered
    ))
}
