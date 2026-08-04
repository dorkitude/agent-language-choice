use std::collections::HashMap;

use crate::domain::{CombatSession, Combatant, Condition};
use crate::json::{escape_json, extract_array_content, extract_int, extract_objects, extract_string};

pub enum CombatError {
    NotFound,
    BadRequest,
}

/// Parse a session id from a path like `/v1/combat/sessions/{id}/suffix`.
pub fn parse_combat_path<'a>(path: &'a str, suffix: &'a str) -> Option<&'a str> {
    let rest = path.strip_prefix("/v1/combat/sessions/")?;
    let id = rest.strip_suffix(suffix)?;
    if id.is_empty() {
        return None;
    }
    Some(id)
}

/// Build a list of combatants from a JSON array body and sort them into
/// initiative order.
///
/// The score is `roll + dex`. Ties are broken by higher dex, then by name in
/// ascending lexicographic order to keep the result deterministic.
fn roll_initiative(combatants_body: &str) -> Option<Vec<Combatant>> {
    let objects = extract_objects(combatants_body);
    if objects.is_empty() {
        return None;
    }
    let mut order = Vec::new();
    for obj in objects {
        let name = extract_string(obj, "name")?.to_string();
        let dex = extract_int(obj, "dex")?;
        let roll = extract_int(obj, "roll")?;
        order.push(Combatant {
            name,
            score: roll + dex,
            dex,
        });
    }
    order.sort_by(|a, b| {
        b.score
            .cmp(&a.score)
            .then(b.dex.cmp(&a.dex))
            .then(a.name.cmp(&b.name))
    });
    Some(order)
}

/// Create a new combat session from a request body.
///
/// Required fields: `id` (string), `combatants` (array of objects with
/// `name`, `dex`, `roll`). The session starts at round 1, turn 0, with the
/// top initiative combatant active. Returns the full session summary.
pub fn create_session(
    body: &str,
    sessions: &mut HashMap<String, CombatSession>,
) -> Option<String> {
    let id = extract_string(body, "id")?.to_string();
    if id.is_empty() || sessions.contains_key(&id) {
        return None;
    }
    let content = extract_array_content(body, "combatants")?;
    let order = roll_initiative(content)?;
    let active = order.first()?.clone();
    sessions.insert(
        id.clone(),
        CombatSession {
            id: id.clone(),
            round: 1,
            turn_index: 0,
            order: order.clone(),
            conditions: HashMap::new(),
        },
    );
    Some(format_session_summary(&id, 1, 0, &active, &order))
}

/// Serialize a session summary in the format expected by the API.
fn format_session_summary(
    id: &str,
    round: i64,
    turn_index: usize,
    active: &Combatant,
    order: &[Combatant],
) -> String {
    let order_json = order
        .iter()
        .map(|c| format!(r#"{{"name":"{}","score":{}}}"#, escape_json(&c.name), c.score))
        .collect::<Vec<_>>()
        .join(",");
    format!(
        r#"{{"id":"{}","round":{},"turn_index":{},"active":{{"name":"{}","score":{}}},"order":[{}]}}"#,
        escape_json(id),
        round,
        turn_index,
        escape_json(&active.name),
        active.score,
        order_json
    )
}

/// Add a condition to a target combatant in a session.
///
/// The target must exist in the session order. `duration_rounds` must be a
/// positive integer. Returns the updated condition list for that target.
pub fn add_condition(
    id: &str,
    body: &str,
    sessions: &mut HashMap<String, CombatSession>,
) -> Result<String, CombatError> {
    let session = sessions.get_mut(id).ok_or(CombatError::NotFound)?;
    let target = extract_string(body, "target")
        .ok_or(CombatError::BadRequest)?
        .to_string();
    if !session.order.iter().any(|c| c.name == target) {
        return Err(CombatError::BadRequest);
    }
    let condition = extract_string(body, "condition")
        .ok_or(CombatError::BadRequest)?
        .to_string();
    let duration = extract_int(body, "duration_rounds").ok_or(CombatError::BadRequest)?;
    if duration <= 0 {
        return Err(CombatError::BadRequest);
    }
    session
        .conditions
        .entry(target.clone())
        .or_default()
        .push(Condition {
            name: condition,
            remaining: duration,
        });
    let list = session.conditions.get(&target).unwrap();
    let conditions_json = list
        .iter()
        .map(|c| {
            format!(
                r#"{{"condition":"{}","remaining_rounds":{}}}"#,
                escape_json(&c.name),
                c.remaining
            )
        })
        .collect::<Vec<_>>()
        .join(",");
    Ok(format!(
        r#"{{"target":"{}","conditions":[{}]}}"#,
        escape_json(&target),
        conditions_json
    ))
}

/// Advance the turn tracker in a session.
///
/// Increments `turn_index` modulo the number of combatants; when the turn wraps
/// back to zero, `round` is incremented. Conditions on the newly active
/// combatant have their remaining duration decremented by one, and any
/// condition reaching zero is removed.
pub fn advance_turn(
    id: &str,
    sessions: &mut HashMap<String, CombatSession>,
) -> Result<String, CombatError> {
    let session = sessions.get_mut(id).ok_or(CombatError::NotFound)?;
    let len = session.order.len();
    if len == 0 {
        return Err(CombatError::BadRequest);
    }
    let new_index = (session.turn_index + 1) % len;
    if new_index == 0 {
        session.round += 1;
    }
    session.turn_index = new_index;
    let active_name = session.order[session.turn_index].name.clone();
    if let Some(list) = session.conditions.get_mut(&active_name) {
        list.retain(|c| c.remaining > 0);
        for c in list.iter_mut() {
            c.remaining -= 1;
        }
        list.retain(|c| c.remaining > 0);
    }
    let active = &session.order[session.turn_index];
    let conditions_json = format_conditions_map(session);
    Ok(format!(
        r#"{{"id":"{}","round":{},"turn_index":{},"active":{{"name":"{}","score":{}}},"conditions":{}}}"#,
        escape_json(&session.id),
        session.round,
        session.turn_index,
        escape_json(&active.name),
        active.score,
        conditions_json
    ))
}

/// Serialize all remaining conditions for a session as a JSON object keyed by
/// target name. Targets are sorted to keep the output deterministic.
fn format_conditions_map(session: &CombatSession) -> String {
    let mut targets: Vec<&String> = session.conditions.iter().map(|(k, _)| k).collect();
    targets.sort();
    let entries = targets
        .iter()
        .map(|t| {
            let list = session.conditions.get(*t).unwrap();
            let arr = list
                .iter()
                .map(|c| {
                    format!(
                        r#"{{"condition":"{}","remaining_rounds":{}}}"#,
                        escape_json(&c.name),
                        c.remaining
                    )
                })
                .collect::<Vec<_>>()
                .join(",");
            format!(r#""{}":[{}]"#, escape_json(t), arr)
        })
        .collect::<Vec<_>>()
        .join(",");
    format!("{{{}}}", entries)
}

/// Compute a single-use initiative order without creating a session.
pub fn handle_initiative(body: &str) -> Option<String> {
    let content = extract_array_content(body, "combatants")?;
    let order = roll_initiative(content)?;
    let order_json = order
        .into_iter()
        .map(|c| format!(r#"{{"name":"{}","score":{}}}"#, escape_json(&c.name), c.score))
        .collect::<Vec<_>>()
        .join(",");
    Some(format!(r#"{{"order":[{}]}}"#, order_json))
}
