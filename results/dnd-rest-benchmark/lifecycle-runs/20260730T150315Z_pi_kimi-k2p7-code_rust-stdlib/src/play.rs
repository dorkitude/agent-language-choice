use crate::json::{escape_json, extract_array_content, extract_int, extract_objects, extract_string};
use crate::store::{
    play_campaign_active_encounter_exists, play_campaign_character_id_exists, play_campaign_create,
    play_campaign_document_get, play_campaign_document_set, play_campaign_exists,
    play_campaign_get_current_location, play_campaign_get_current_scene, play_campaign_get_exploration_actor,
    play_campaign_get_turn,
    play_campaign_max_players, play_campaign_member_by_character_id, play_campaign_member_character,
    play_campaign_member_count, play_campaign_member_create, play_campaign_member_exists,
    play_campaign_member_hp, play_campaign_members, play_campaign_member_set_death_saves_status,
    play_campaign_member_set_hp_current, play_campaign_member_set_hp_status_saves,
    play_campaign_narrations, play_campaign_nudge, play_campaign_owner_status,
    play_campaign_set_current_location, play_campaign_set_current_scene, play_campaign_set_exploration_actor,
    play_campaign_start,
    play_campaign_update_turn, play_encounter_add_condition, play_encounter_add_monster,
    play_encounter_all_conditions, play_encounter_close, play_encounter_combatant_create,
    play_encounter_combatant_exists, play_encounter_combatant_remove, play_encounter_create,
    play_encounter_decrement_conditions, play_encounter_exists, play_encounter_get_order, play_encounter_get_rewards,
    play_encounter_get_status, play_encounter_get_turn,
    play_encounter_list_combatants, play_encounter_list_monsters, play_encounter_monster_exists,
    play_encounter_conditions_for_target,
    play_encounter_monster_hp, play_encounter_monster_set_hp_current,
    play_encounter_remove_monster, play_encounter_set_order, play_encounter_set_rewards, play_encounter_set_turn,
    play_location_connection_create,
    play_location_connection_exists, play_location_connections, play_location_create,
    play_location_exists, play_narration_create, play_narration_create_with_target,
    play_narration_next_sequence, play_scene_create,
    play_scene_exists, play_scene_get, play_scene_set_status,
};

pub enum PlayError {
    BadRequest,
    NotFound,
    Conflict,
    Forbidden,
}

/// Parse a play campaign id from a path like `/v1/play/campaigns/{id}/members`.
pub fn parse_play_campaign_path<'a>(path: &'a str, suffix: &'a str) -> Option<&'a str> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let id = rest.strip_suffix(suffix)?;
    if id.is_empty() || id.contains('/') {
        return None;
    }
    Some(id)
}

/// Create a new play campaign.
///
/// POST /v1/play/campaigns
///
/// The body must contain non-empty `id` and `name` and a positive
/// `max_players`. The caller is responsible for authorization checks;
/// `owner` is the authenticated DM username.
pub fn create_play_campaign(body: &str, owner: &str) -> Result<String, PlayError> {
    let id = extract_string(body, "id").ok_or(PlayError::BadRequest)?;
    let name = extract_string(body, "name").ok_or(PlayError::BadRequest)?;
    let max_players = extract_int(body, "max_players").ok_or(PlayError::BadRequest)?;
    if id.is_empty() || name.is_empty() || max_players < 1 || owner.is_empty() {
        return Err(PlayError::BadRequest);
    }
    if play_campaign_exists(id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::Conflict);
    }
    play_campaign_create(id, name, owner, "lobby", max_players)
        .map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"id":"{}","name":"{}","owner":"{}","status":"lobby","max_players":{}}}"#,
        escape_json(id),
        escape_json(name),
        escape_json(owner),
        max_players
    ))
}

/// Join a play campaign as an authenticated player.
///
/// POST /v1/play/campaigns/{id}/members
///
/// A player may own at most one membership per campaign, and character IDs
/// must be unique within a campaign. The party must not already be full.
/// Only players are allowed to join.
pub fn join_campaign(campaign_id: &str, body: &str, actor: &str) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let character_id = extract_string(body, "character_id").ok_or(PlayError::BadRequest)?;
    let name = extract_string(body, "name").ok_or(PlayError::BadRequest)?;
    let class = extract_string(body, "class").ok_or(PlayError::BadRequest)?;
    if character_id.is_empty() || name.is_empty() || class.is_empty() || actor.is_empty() {
        return Err(PlayError::BadRequest);
    }

    let max_players = play_campaign_max_players(campaign_id).map_err(|_| PlayError::BadRequest)?;
    let member_count =
        play_campaign_member_count(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if member_count >= max_players {
        return Err(PlayError::Conflict);
    }
    if play_campaign_member_exists(campaign_id, actor).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::Conflict);
    }
    if play_campaign_character_id_exists(campaign_id, character_id)
        .map_err(|_| PlayError::BadRequest)?
    {
        return Err(PlayError::Conflict);
    }

    play_campaign_member_create(campaign_id, actor, character_id, name, class)
        .map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"username":"{}","character_id":"{}","name":"{}","class":"{}"}}"#,
        escape_json(actor),
        escape_json(character_id),
        escape_json(name),
        escape_json(class)
    ))
}

/// Append a GM narration to a play campaign.
///
/// POST /v1/play/campaigns/{id}/narrations
///
/// Only the campaign owner may narrate. The sequence is append-only and
/// starts at 1 for each campaign.
pub fn narrate_campaign(campaign_id: &str, body: &str, actor: &str) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    let text = extract_string(body, "text").ok_or(PlayError::BadRequest)?;
    if text.is_empty() || actor.is_empty() {
        return Err(PlayError::BadRequest);
    }
    let sequence = play_narration_next_sequence(campaign_id).map_err(|_| PlayError::BadRequest)?;
    play_narration_create(campaign_id, sequence, "narration", "dm", text)
        .map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"sequence":{},"kind":"narration","actor":"dm","text":"{}"}}"#,
        sequence,
        escape_json(text)
    ))
}

/// Start a play campaign.
///
/// POST /v1/play/campaigns/{id}/start
///
/// Only the owning DM may start a campaign. The campaign must be in the
/// `lobby` status and have at least two party members. The first member by
/// insertion order becomes the current actor at turn number 1.
pub fn start_campaign(campaign_id: &str, actor: &str) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    if status != "lobby" {
        return Err(PlayError::Conflict);
    }
    let members = play_campaign_members(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if members.len() < 2 {
        return Err(PlayError::Conflict);
    }
    let current_actor = &members[0].0;
    play_campaign_start(campaign_id, current_actor, "player", 1)
        .map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"id":"{}","status":"active","current_actor":"{}","turn_number":1}}"#,
        escape_json(campaign_id),
        escape_json(current_actor)
    ))
}

/// Read the caller's player turn context for a play campaign.
///
/// GET /v1/play/campaigns/{id}/my-turn
///
/// Only a campaign member with role `player` may read their own context.
/// The response includes whether it is the caller's turn, the current actor,
/// the caller's own character (id and name only), and recent public events.
/// DM-private document fields are never exposed.
pub fn get_my_turn(campaign_id: &str, actor: &str) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    if !play_campaign_member_exists(campaign_id, actor).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::Forbidden);
    }
    let (current_actor, _phase, _turn_number) =
        play_campaign_get_turn(campaign_id).map_err(|_| PlayError::BadRequest)?;
    let (character_id, character_name) =
        play_campaign_member_character(campaign_id, actor).map_err(|_| PlayError::BadRequest)?;
    let narrations = play_campaign_narrations(campaign_id).map_err(|_| PlayError::BadRequest)?;

    let is_my_turn = current_actor == actor;
    let mut events_json = Vec::new();
    for (sequence, kind, event_actor, text) in narrations {
        events_json.push(format!(
            r#"{{"sequence":{},"kind":"{}","actor":"{}","text":"{}"}}"#,
            sequence,
            escape_json(&kind),
            escape_json(&event_actor),
            escape_json(&text)
        ));
    }

    Ok(format!(
        r#"{{"is_my_turn":{},"current_actor":"{}","character":{{"id":"{}","name":"{}"}},"recent_events":[{}]}}"#,
        is_my_turn,
        escape_json(&current_actor),
        escape_json(&character_id),
        escape_json(&character_name),
        events_json.join(",")
    ))
}

/// Read the GM turn status for a play campaign.
///
/// GET /v1/play/campaigns/{id}/gm/status
///
/// Only the campaign owner may read this endpoint. Players receive 403. The
/// response includes whether the current actor is the owner
/// (`needs_attention`), the current actor, a summary of all party members, and
/// recent public narrations.
pub fn get_gm_status(campaign_id: &str, actor: &str) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    let (current_actor, _phase, _turn_number) =
        play_campaign_get_turn(campaign_id).map_err(|_| PlayError::BadRequest)?;
    let members = play_campaign_members(campaign_id).map_err(|_| PlayError::BadRequest)?;
    let narrations = play_campaign_narrations(campaign_id).map_err(|_| PlayError::BadRequest)?;

    let needs_attention = current_actor == owner;

    let mut party_json = Vec::new();
    for (username, character_id, name, class) in members {
        party_json.push(format!(
            r#"{{"username":"{}","character_id":"{}","name":"{}","class":"{}"}}"#,
            escape_json(&username),
            escape_json(&character_id),
            escape_json(&name),
            escape_json(&class)
        ));
    }

    let mut events_json = Vec::new();
    for (sequence, kind, event_actor, text) in narrations {
        events_json.push(format!(
            r#"{{"sequence":{},"kind":"{}","actor":"{}","text":"{}"}}"#,
            sequence,
            escape_json(&kind),
            escape_json(&event_actor),
            escape_json(&text)
        ));
    }

    Ok(format!(
        r#"{{"needs_attention":{},"current_actor":"{}","party":[{}],"recent_events":[{}]}}"#,
        needs_attention,
        escape_json(&current_actor),
        party_json.join(","),
        events_json.join(",")
    ))
}

/// Submit a player action for the active turn.
///
/// POST /v1/play/campaigns/{id}/actions
///
/// Only the currently active player may submit an action. The action is
/// appended as a public event and the turn passes to the DM.
pub fn submit_action(campaign_id: &str, body: &str, actor: &str) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    if !play_campaign_member_exists(campaign_id, actor).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::Conflict);
    }
    let (current_actor, _phase, _turn_number) =
        play_campaign_get_turn(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if current_actor != actor {
        return Err(PlayError::Conflict);
    }

    let action_type = extract_string(body, "type").ok_or(PlayError::BadRequest)?;
    let text = extract_string(body, "text").ok_or(PlayError::BadRequest)?;
    if action_type.is_empty() || text.is_empty() {
        return Err(PlayError::BadRequest);
    }

    let sequence = play_narration_next_sequence(campaign_id).map_err(|_| PlayError::BadRequest)?;
    play_narration_create(campaign_id, sequence, "action", actor, text)
        .map_err(|_| PlayError::BadRequest)?;
    play_campaign_update_turn(campaign_id, "dm", "dm", 1)
        .map_err(|_| PlayError::BadRequest)?;

    Ok(format!(
        r#"{{"sequence":{},"kind":"action","actor":"{}","type":"{}","text":"{}","next_actor":"dm"}}"#,
        sequence,
        escape_json(actor),
        escape_json(action_type),
        escape_json(text)
    ))
}

/// Read the current turn for a play campaign.
///
/// GET /v1/play/campaigns/{id}/turn
///
/// Only the campaign owner or a member may read the turn. The response
/// includes the campaign id, current actor, phase, turn number, and the
/// deterministic turn queue (players in join order alternating with the DM).
pub fn get_turn(campaign_id: &str, actor: &str) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor && !play_campaign_member_exists(campaign_id, actor)
        .map_err(|_| PlayError::BadRequest)?
    {
        return Err(PlayError::Forbidden);
    }
    let (current_actor, phase, turn_number) =
        play_campaign_get_turn(campaign_id).map_err(|_| PlayError::BadRequest)?;
    let members = play_campaign_members(campaign_id).map_err(|_| PlayError::BadRequest)?;
    let mut queue = String::new();
    for (i, (username, _, _, _)) in members.iter().enumerate() {
        if i > 0 {
            queue.push(',');
        }
        queue.push_str(&format!(r#""{}","dm""#, escape_json(username)));
    }
    let logical_deadline = turn_number + 1;
    Ok(format!(
        r#"{{"campaign_id":"{}","current_actor":"{}","phase":"{}","turn_number":{},"overdue":false,"logical_deadline":{},"queue":[{}]}}"#,
        escape_json(campaign_id),
        escape_json(&current_actor),
        escape_json(&phase),
        turn_number,
        logical_deadline,
        queue
    ))
}

/// Nudge the current actor for a play campaign.
///
/// POST /v1/play/campaigns/{id}/turn/nudge
///
/// Only the campaign owner may send a nudge. The request body must contain a
/// non-empty `message`. The response returns the actor, the current target,
/// the message, and the monotonically increasing nudge count for the campaign.
pub fn nudge_campaign(campaign_id: &str, body: &str, actor: &str) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    let message = extract_string(body, "message").ok_or(PlayError::BadRequest)?;
    if message.is_empty() || actor.is_empty() {
        return Err(PlayError::BadRequest);
    }
    let (current_actor, _phase, _turn_number) =
        play_campaign_get_turn(campaign_id).map_err(|_| PlayError::BadRequest)?;
    let nudge_count = play_campaign_nudge(campaign_id).map_err(|_| PlayError::BadRequest)?;
    let sequence = play_narration_next_sequence(campaign_id).map_err(|_| PlayError::BadRequest)?;
    play_narration_create(campaign_id, sequence, "nudge", actor, &message)
        .map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"actor":"{}","target":"{}","message":"{}","nudge_count":{}}}"#,
        escape_json(actor),
        escape_json(&current_actor),
        escape_json(&message),
        nudge_count
    ))
}

/// Update the durable role-filtered campaign document.
///
/// PUT /v1/play/campaigns/{id}/document
///
/// Only the campaign owner may update the document. The response includes
/// both `story` and `dm_notes`.
pub fn update_document(campaign_id: &str, body: &str, actor: &str) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    let story = extract_string(body, "story").ok_or(PlayError::BadRequest)?;
    let dm_notes = extract_string(body, "dm_notes").ok_or(PlayError::BadRequest)?;
    play_campaign_document_set(campaign_id, story, dm_notes)
        .map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"story":"{}","dm_notes":"{}"}}"#,
        escape_json(story),
        escape_json(dm_notes)
    ))
}

/// Read the durable role-filtered campaign document.
///
/// GET /v1/play/campaigns/{id}/document
///
/// The campaign owner receives both `story` and `dm_notes`. A player member
/// receives only the public `story` field; `dm_notes` is never disclosed.
pub fn get_document(campaign_id: &str, actor: &str) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    let is_owner = owner == actor;
    let is_member = play_campaign_member_exists(campaign_id, actor)
        .map_err(|_| PlayError::BadRequest)?;
    if !is_owner && !is_member {
        return Err(PlayError::Forbidden);
    }
    let (story, dm_notes) =
        play_campaign_document_get(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if is_owner {
        Ok(format!(
            r#"{{"story":"{}","dm_notes":"{}"}}"#,
            escape_json(&story),
            escape_json(&dm_notes)
        ))
    } else {
        // Players see only the public story; dm_notes is omitted entirely.
        Ok(format!(r#"{{"story":"{}"}}"#, escape_json(&story)))
    }
}

/// Submit a GM resolution for the active turn.
///
/// POST /v1/play/campaigns/{id}/resolutions
///
/// Only the campaign owner may resolve when the current phase is `dm`. The
/// resolution is appended as a public event and the turn advances to the next
/// party member with an incremented turn number.
pub fn resolve_turn(campaign_id: &str, body: &str, actor: &str) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Conflict);
    }
    let (current_actor, phase, turn_number) =
        play_campaign_get_turn(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if current_actor != "dm" || (phase != "dm" && phase != "exploration") {
        return Err(PlayError::Conflict);
    }

    let text = extract_string(body, "text").ok_or(PlayError::BadRequest)?;
    if text.is_empty() || actor.is_empty() {
        return Err(PlayError::BadRequest);
    }

    let members = play_campaign_members(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if members.is_empty() {
        return Err(PlayError::Conflict);
    }
    let next_index = (turn_number % members.len() as i64) as usize;
    let next_actor = members[next_index].0.clone();
    let new_turn_number = turn_number + 1;

    let sequence = play_narration_next_sequence(campaign_id).map_err(|_| PlayError::BadRequest)?;
    play_narration_create(campaign_id, sequence, "resolution", "dm", text)
        .map_err(|_| PlayError::BadRequest)?;
    play_campaign_update_turn(campaign_id, &next_actor, "player", new_turn_number)
        .map_err(|_| PlayError::BadRequest)?;

    Ok(format!(
        r#"{{"sequence":{},"kind":"resolution","actor":"dm","text":"{}","next_actor":"{}","turn_number":{}}}"#,
        sequence,
        escape_json(text),
        escape_json(&next_actor),
        new_turn_number
    ))
}

/// Parse a play campaign scene sub-resource path.
///
/// For example, `/v1/play/campaigns/{id}/scenes/{scene_id}/enter` returns
/// `(campaign_id, scene_id)` when `suffix` is `/enter`.
pub fn parse_play_campaign_scene_path<'a>(
    path: &'a str,
    suffix: &'a str,
) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/scenes/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    if campaign_id.is_empty() {
        return None;
    }
    let after = &rest[mid + marker.len()..];
    let scene_id = after.strip_suffix(suffix)?;
    if scene_id.is_empty() {
        return None;
    }
    Some((campaign_id, scene_id))
}

/// Create a new scene for a play campaign.
///
/// POST /v1/play/campaigns/{id}/scenes
///
/// Only the campaign owner may create scenes. Duplicate scene IDs return 409.
pub fn create_scene(campaign_id: &str, body: &str, actor: &str) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    let id = extract_string(body, "id").ok_or(PlayError::BadRequest)?;
    let name = extract_string(body, "name").ok_or(PlayError::BadRequest)?;
    if id.is_empty() || name.is_empty() {
        return Err(PlayError::BadRequest);
    }
    if play_scene_exists(campaign_id, id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::Conflict);
    }
    play_scene_create(campaign_id, id, name).map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"id":"{}","name":"{}","status":"open"}}"#,
        escape_json(id),
        escape_json(name)
    ))
}

/// Enter a scene for a play campaign, making it the current scene.
///
/// POST /v1/play/campaigns/{id}/scenes/{scene_id}/enter
///
/// Only the campaign owner may enter a scene. Closed scenes may not be entered.
pub fn enter_scene(campaign_id: &str, scene_id: &str, actor: &str) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    let (name, status) = play_scene_get(campaign_id, scene_id).map_err(|_| PlayError::NotFound)?;
    if status == "closed" {
        return Err(PlayError::Conflict);
    }
    play_campaign_set_current_scene(campaign_id, scene_id)
        .map_err(|_| PlayError::BadRequest)?;
    let sequence = play_narration_next_sequence(campaign_id).map_err(|_| PlayError::BadRequest)?;
    play_narration_create(campaign_id, sequence, "scene", actor, scene_id)
        .map_err(|_| PlayError::BadRequest)?;
    if play_location_exists(campaign_id, scene_id).map_err(|_| PlayError::BadRequest)? {
        play_campaign_set_current_location(campaign_id, scene_id)
            .map_err(|_| PlayError::BadRequest)?;
    }
    Ok(format!(
        r#"{{"current_scene_id":"{}","name":"{}"}}"#,
        escape_json(scene_id),
        escape_json(&name)
    ))
}

/// Close a scene for a play campaign.
///
/// POST /v1/play/campaigns/{id}/scenes/{scene_id}/close
///
/// Only the campaign owner may close a scene.
pub fn close_scene(campaign_id: &str, scene_id: &str, actor: &str) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    if !play_scene_exists(campaign_id, scene_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    play_scene_set_status(campaign_id, scene_id, "closed").map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"id":"{}","status":"closed"}}"#,
        escape_json(scene_id)
    ))
}

/// Read the current scene for a play campaign.
///
/// GET /v1/play/campaigns/{id}/scenes/current
///
/// Any campaign member (or the owner) may read the current scene. Returns 404
/// when no current scene is set.
pub fn get_current_scene(campaign_id: &str, actor: &str) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    let is_member =
        play_campaign_member_exists(campaign_id, actor).map_err(|_| PlayError::BadRequest)?;
    if owner != actor && !is_member {
        return Err(PlayError::Forbidden);
    }
    match play_campaign_get_current_scene(campaign_id).map_err(|_| PlayError::BadRequest)? {
        Some((id, name, status)) => {
            if status != "open" {
                return Err(PlayError::NotFound);
            }
            Ok(format!(
                r#"{{"id":"{}","name":"{}","status":"{}"}}"#,
                escape_json(&id),
                escape_json(&name),
                escape_json(&status)
            ))
        }
        None => Err(PlayError::NotFound),
    }
}

/// Parse a play campaign location sub-resource path.
///
/// For example, `/v1/play/campaigns/{id}/locations/{loc_id}/travel` returns
/// `(campaign_id, loc_id)` when `suffix` is `/travel`.
pub fn parse_play_campaign_location_path<'a>(
    path: &'a str,
    suffix: &'a str,
) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/locations/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    if campaign_id.is_empty() {
        return None;
    }
    let after = &rest[mid + marker.len()..];
    let loc_id = after.strip_suffix(suffix)?;
    if loc_id.is_empty() {
        return None;
    }
    Some((campaign_id, loc_id))
}

/// Create a new location for a play campaign.
///
/// POST /v1/play/campaigns/{id}/locations
///
/// Only the campaign owner may create locations. Duplicate location IDs
/// return 409.
pub fn create_location(campaign_id: &str, body: &str, actor: &str) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    let id = extract_string(body, "id").ok_or(PlayError::BadRequest)?;
    let name = extract_string(body, "name").ok_or(PlayError::BadRequest)?;
    if id.is_empty() || name.is_empty() {
        return Err(PlayError::BadRequest);
    }
    if play_location_exists(campaign_id, id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::Conflict);
    }
    play_location_create(campaign_id, id, name).map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"id":"{}","name":"{}"}}"#,
        escape_json(id),
        escape_json(name)
    ))
}

/// Create a directed connection between two play campaign locations.
///
/// POST /v1/play/campaigns/{id}/locations/{from_id}/connections
///
/// Only the campaign owner may create connections. Connections to missing
/// locations or already-connected destinations return 400.
pub fn create_connection(
    campaign_id: &str,
    from_id: &str,
    body: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    let to_id = extract_string(body, "to_id").ok_or(PlayError::BadRequest)?;
    let travel_turns = extract_int(body, "travel_turns").ok_or(PlayError::BadRequest)?;
    if from_id.is_empty() || to_id.is_empty() || travel_turns < 1 {
        return Err(PlayError::BadRequest);
    }
    if !play_location_exists(campaign_id, from_id).map_err(|_| PlayError::BadRequest)?
        || !play_location_exists(campaign_id, to_id).map_err(|_| PlayError::BadRequest)?
    {
        return Err(PlayError::BadRequest);
    }
    if play_location_connection_exists(campaign_id, from_id, to_id)
        .map_err(|_| PlayError::BadRequest)?
    {
        return Err(PlayError::BadRequest);
    }
    play_location_connection_create(campaign_id, from_id, to_id, travel_turns)
        .map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"from_id":"{}","to_id":"{}","travel_turns":{}}}"#,
        escape_json(from_id),
        escape_json(to_id),
        travel_turns
    ))
}

/// Read valid outbound travel from a play campaign location.
///
/// GET /v1/play/campaigns/{id}/locations/{loc_id}/travel
///
/// Any campaign member (or the owner) may read valid travel options.
pub fn get_travel(campaign_id: &str, loc_id: &str, actor: &str) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    let is_member =
        play_campaign_member_exists(campaign_id, actor).map_err(|_| PlayError::BadRequest)?;
    if owner != actor && !is_member {
        return Err(PlayError::Forbidden);
    }
    if !play_location_exists(campaign_id, loc_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let destinations =
        play_location_connections(campaign_id, loc_id).map_err(|_| PlayError::BadRequest)?;
    let mut dest_json = Vec::new();
    for (to_id, name, travel_turns) in destinations {
        dest_json.push(format!(
            r#"{{"id":"{}","name":"{}","travel_turns":{}}}"#,
            escape_json(&to_id),
            escape_json(&name),
            travel_turns
        ));
    }
    Ok(format!(
        r#"{{"destinations":[{}]}}"#,
        dest_json.join(",")
    ))
}

/// Consume the active player's turn to travel to a connected location.
///
/// POST /v1/play/campaigns/{id}/turn/travel
///
/// Only the currently active player may call this endpoint. The destination
/// must be a valid outbound connection from the party's current location.
/// The location graph and current scene remain unchanged; the party's current
/// location is updated to the destination.
pub fn travel_turn(
    campaign_id: &str,
    body: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    if !play_campaign_member_exists(campaign_id, actor).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::Conflict);
    }
    let (current_actor, _phase, turn_number) =
        play_campaign_get_turn(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if current_actor != actor {
        return Err(PlayError::Conflict);
    }

    let destination_id = extract_string(body, "destination_id").ok_or(PlayError::BadRequest)?;
    if destination_id.is_empty() {
        return Err(PlayError::BadRequest);
    }

    let current_location = play_campaign_get_current_location(campaign_id)
        .map_err(|_| PlayError::BadRequest)?;
    let from_id = current_location.ok_or(PlayError::Conflict)?;

    let destinations =
        play_location_connections(campaign_id, &from_id).map_err(|_| PlayError::BadRequest)?;
    let mut travel_turns = 0_i64;
    let mut found = false;
    for (to_id, _name, turns) in destinations {
        if to_id == destination_id {
            travel_turns = turns;
            found = true;
            break;
        }
    }
    if !found {
        return Err(PlayError::Conflict);
    }

    let sequence = play_narration_next_sequence(campaign_id).map_err(|_| PlayError::BadRequest)?;
    play_narration_create(campaign_id, sequence, "travel", actor, &destination_id)
        .map_err(|_| PlayError::BadRequest)?;
    play_campaign_update_turn(campaign_id, "dm", "dm", turn_number)
        .map_err(|_| PlayError::BadRequest)?;
    play_campaign_set_current_location(campaign_id, &destination_id)
        .map_err(|_| PlayError::BadRequest)?;

    Ok(format!(
        r#"{{"sequence":{},"kind":"travel","actor":"{}","destination_id":"{}","travel_turns":{},"next_actor":"dm"}}"#,
        sequence,
        escape_json(actor),
        escape_json(&destination_id),
        travel_turns
    ))
}

/// Take a short or long rest as the active player's turn.
///
/// POST /v1/play/campaigns/{id}/turn/rest
///
/// Only the currently active player may call this endpoint. A long rest
/// restores the acting character's hp_current to hp_max. After the rest the
/// turn passes to the DM.
pub fn rest_turn(
    campaign_id: &str,
    body: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    if !play_campaign_member_exists(campaign_id, actor).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::Conflict);
    }
    let (current_actor, _phase, turn_number) =
        play_campaign_get_turn(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if current_actor != actor {
        return Err(PlayError::Conflict);
    }

    let rest_type = extract_string(body, "type").ok_or(PlayError::BadRequest)?;
    if rest_type != "short" && rest_type != "long" {
        return Err(PlayError::BadRequest);
    }

    let (hp_current, hp_max) =
        play_campaign_member_hp(campaign_id, actor).map_err(|_| PlayError::BadRequest)?;
    let new_hp = if rest_type == "long" { hp_max } else { hp_current };
    if rest_type == "long" {
        play_campaign_member_set_hp_current(campaign_id, actor, new_hp)
            .map_err(|_| PlayError::BadRequest)?;
    }

    let sequence = play_narration_next_sequence(campaign_id).map_err(|_| PlayError::BadRequest)?;
    play_narration_create(campaign_id, sequence, "rest", actor, &rest_type)
        .map_err(|_| PlayError::BadRequest)?;
    play_campaign_update_turn(campaign_id, "dm", "dm", turn_number)
        .map_err(|_| PlayError::BadRequest)?;

    Ok(format!(
        r#"{{"sequence":{},"kind":"rest","actor":"{}","type":"{}","hp_current":{},"hp_max":{},"next_actor":"dm"}}"#,
        sequence,
        escape_json(actor),
        escape_json(&rest_type),
        new_hp,
        hp_max
    ))
}

/// Create a campaign-bound encounter from the current party state.
///
/// POST /v1/play/campaigns/{id}/encounters
///
/// Only the campaign owner may create an encounter. Duplicate encounter ids or
/// a campaign that is already in combat return 409. The new encounter starts
/// with status `active` and an empty combatant list, independent from the
/// exploration turn queue until the campaign returns to exploration.
pub fn create_encounter(
    campaign_id: &str,
    body: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    let id = extract_string(body, "id").ok_or(PlayError::BadRequest)?;
    let name = extract_string(body, "name").ok_or(PlayError::BadRequest)?;
    if id.is_empty() || name.is_empty() {
        return Err(PlayError::BadRequest);
    }
    if play_encounter_exists(campaign_id, id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::Conflict);
    }
    if play_campaign_active_encounter_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::Conflict);
    }
    let (exploration_actor, _phase, turn_number) =
        play_campaign_get_turn(campaign_id).map_err(|_| PlayError::BadRequest)?;
    play_encounter_create(campaign_id, id, name).map_err(|_| PlayError::BadRequest)?;
    play_campaign_set_exploration_actor(campaign_id, &exploration_actor)
        .map_err(|_| PlayError::BadRequest)?;
    play_campaign_update_turn(campaign_id, &exploration_actor, "combat", turn_number)
        .map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"id":"{}","name":"{}","status":"active","combatants":[]}}"#,
        escape_json(id),
        escape_json(name)
    ))
}

/// Parse a play encounter monster collection path.
///
/// For example, `/v1/play/campaigns/{id}/encounters/{enc_id}/monsters`
/// returns `(campaign_id, encounter_id)`.
pub fn parse_play_encounter_monster_post_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/encounters/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    let after = &rest[mid + marker.len()..];
    let encounter_id = after.strip_suffix("/monsters")?;
    if campaign_id.is_empty() || encounter_id.is_empty() {
        return None;
    }
    Some((campaign_id, encounter_id))
}

/// Parse a play encounter monster resource path.
///
/// For example, `/v1/play/campaigns/{id}/encounters/{enc_id}/monsters/{monster_id}`
/// returns `(campaign_id, encounter_id, monster_id)`.
pub fn parse_play_encounter_monster_delete_path<'a>(
    path: &'a str,
) -> Option<(&'a str, &'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/encounters/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    let after = &rest[mid + marker.len()..];
    let marker2 = "/monsters/";
    let mid2 = after.find(marker2)?;
    let encounter_id = &after[..mid2];
    let monster_id = &after[mid2 + marker2.len()..];
    if campaign_id.is_empty() || encounter_id.is_empty() || monster_id.is_empty() {
        return None;
    }
    Some((campaign_id, encounter_id, monster_id))
}

/// Add a monster to a campaign encounter.
///
/// POST /v1/play/campaigns/{id}/encounters/{enc_id}/monsters
///
/// Only the campaign owner may add monsters. Duplicate monster ids within the
/// encounter return 409. The response includes the request fields plus
/// `hp_current` set to `hp_max`.
pub fn add_encounter_monster(
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    if !play_encounter_exists(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let monster_id = extract_string(body, "monster_id").ok_or(PlayError::BadRequest)?;
    let name = extract_string(body, "name").ok_or(PlayError::BadRequest)?;
    let hp_max = extract_int(body, "hp_max").ok_or(PlayError::BadRequest)?;
    let initiative = extract_int(body, "initiative").ok_or(PlayError::BadRequest)?;
    if monster_id.is_empty() || name.is_empty() || hp_max < 1 {
        return Err(PlayError::BadRequest);
    }
    if play_encounter_monster_exists(campaign_id, encounter_id, monster_id)
        .map_err(|_| PlayError::BadRequest)?
    {
        return Err(PlayError::Conflict);
    }
    play_encounter_add_monster(
        campaign_id,
        encounter_id,
        monster_id,
        name,
        hp_max,
        hp_max,
        initiative,
    )
    .map_err(|_| PlayError::BadRequest)?;
    let new_c = EncounterCombatant {
        name: name.to_string(),
        kind: "monster".to_string(),
        initiative,
        member: None,
        monster_id: Some(monster_id.to_string()),
    };
    encounter_order_insert(campaign_id, encounter_id, monster_id, &new_c)
        .map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"monster_id":"{}","name":"{}","hp_max":{},"initiative":{},"hp_current":{}}}"#,
        escape_json(monster_id),
        escape_json(name),
        hp_max,
        initiative,
        hp_max
    ))
}

/// Remove a monster from a campaign encounter.
///
/// DELETE /v1/play/campaigns/{id}/encounters/{enc_id}/monsters/{monster_id}
///
/// Only the campaign owner may remove monsters. The response names the
/// removed monster id.
pub fn remove_encounter_monster(
    campaign_id: &str,
    encounter_id: &str,
    monster_id: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    if !play_encounter_exists(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    if !play_encounter_monster_exists(campaign_id, encounter_id, monster_id)
        .map_err(|_| PlayError::BadRequest)?
    {
        return Err(PlayError::NotFound);
    }
    play_encounter_remove_monster(campaign_id, encounter_id, monster_id)
        .map_err(|_| PlayError::BadRequest)?;
    encounter_order_remove(campaign_id, encounter_id, monster_id).map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"removed":"{}"}}"#,
        escape_json(monster_id)
    ))
}

/// Parse a play encounter combatant collection path.
///
/// For example, `/v1/play/campaigns/{id}/encounters/{enc_id}/combatants`
/// returns `(campaign_id, encounter_id)`.
pub fn parse_play_encounter_combatant_post_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/encounters/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    let after = &rest[mid + marker.len()..];
    let encounter_id = after.strip_suffix("/combatants")?;
    if campaign_id.is_empty() || encounter_id.is_empty() {
        return None;
    }
    Some((campaign_id, encounter_id))
}

/// Parse a play encounter combatant resource path.
///
/// For example, `/v1/play/campaigns/{id}/encounters/{enc_id}/combatants/{member}`
/// returns `(campaign_id, encounter_id, member)`.
pub fn parse_play_encounter_combatant_delete_path<'a>(
    path: &'a str,
) -> Option<(&'a str, &'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/encounters/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    let after = &rest[mid + marker.len()..];
    let marker2 = "/combatants/";
    let mid2 = after.find(marker2)?;
    let encounter_id = &after[..mid2];
    let member = &after[mid2 + marker2.len()..];
    if campaign_id.is_empty() || encounter_id.is_empty() || member.is_empty() {
        return None;
    }
    Some((campaign_id, encounter_id, member))
}

/// Bind a party member as a combatant in an active encounter.
///
/// POST /v1/play/campaigns/{id}/encounters/{enc_id}/combatants
///
/// Only the campaign owner may bind combatants. The request names an existing
/// party member and their initiative score. Duplicate members in the same
/// encounter return 409; missing members return 400.
pub fn bind_encounter_member(
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    if !play_encounter_exists(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let member = extract_string(body, "member").ok_or(PlayError::BadRequest)?;
    let initiative = extract_int(body, "initiative").ok_or(PlayError::BadRequest)?;
    if member.is_empty() {
        return Err(PlayError::BadRequest);
    }
    if !play_campaign_member_exists(campaign_id, member).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::BadRequest);
    }
    if play_encounter_combatant_exists(campaign_id, encounter_id, member)
        .map_err(|_| PlayError::BadRequest)?
    {
        return Err(PlayError::Conflict);
    }
    let (character_id, name) =
        play_campaign_member_character(campaign_id, member).map_err(|_| PlayError::BadRequest)?;
    play_encounter_combatant_create(
        campaign_id,
        encounter_id,
        member,
        &character_id,
        &name,
        initiative,
    )
    .map_err(|_| PlayError::BadRequest)?;
    let new_c = EncounterCombatant {
        name: name.clone(),
        kind: "player".to_string(),
        initiative,
        member: Some(member.to_string()),
        monster_id: None,
    };
    encounter_order_insert(campaign_id, encounter_id, member, &new_c)
        .map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"member":"{}","character_id":"{}","name":"{}","initiative":{}}}"#,
        escape_json(member),
        escape_json(&character_id),
        escape_json(&name),
        initiative
    ))
}

/// Unbind a party member combatant from an active encounter.
///
/// DELETE /v1/play/campaigns/{id}/encounters/{enc_id}/combatants/{member}
///
/// Only the campaign owner may remove combatants. The response names the
/// removed member.
pub fn unbind_encounter_member(
    campaign_id: &str,
    encounter_id: &str,
    member: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    if !play_encounter_exists(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    if !play_encounter_combatant_exists(campaign_id, encounter_id, member)
        .map_err(|_| PlayError::BadRequest)?
    {
        return Err(PlayError::NotFound);
    }
    play_encounter_combatant_remove(campaign_id, encounter_id, member)
        .map_err(|_| PlayError::BadRequest)?;
    encounter_order_remove(campaign_id, encounter_id, member).map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"removed":"{}"}}"#,
        escape_json(member)
    ))
}

#[derive(Clone)]
struct EncounterCombatant {
    name: String,
    kind: String,
    initiative: i64,
    member: Option<String>,
    monster_id: Option<String>,
}

impl EncounterCombatant {
    fn identifier(&self) -> &str {
        if let Some(id) = &self.monster_id {
            id
        } else if let Some(member) = &self.member {
            member
        } else {
            &self.name
        }
    }
}

fn encounter_order_cmp(a: &EncounterCombatant, b: &EncounterCombatant) -> std::cmp::Ordering {
    b.initiative
        .cmp(&a.initiative)
        .then(a.name.cmp(&b.name))
        .then(a.kind.cmp(&b.kind))
        .then(a.member.cmp(&b.member))
        .then(a.monster_id.cmp(&b.monster_id))
}

fn build_encounter_combatant_map(
    campaign_id: &str,
    encounter_id: &str,
) -> Result<std::collections::HashMap<String, EncounterCombatant>, PlayError> {
    let mut map = std::collections::HashMap::new();
    for (monster_id, name, initiative) in
        play_encounter_list_monsters(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)?
    {
        map.insert(
            monster_id.clone(),
            EncounterCombatant {
                name,
                kind: "monster".to_string(),
                initiative,
                member: None,
                monster_id: Some(monster_id),
            },
        );
    }
    for (member, name, initiative) in
        play_encounter_list_combatants(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)?
    {
        map.insert(
            member.clone(),
            EncounterCombatant {
                name,
                kind: "player".to_string(),
                initiative,
                member: Some(member),
                monster_id: None,
            },
        );
    }
    Ok(map)
}

fn load_encounter_combatants(
    campaign_id: &str,
    encounter_id: &str,
) -> Result<Vec<EncounterCombatant>, PlayError> {
    let map = build_encounter_combatant_map(campaign_id, encounter_id)?;
    let stored =
        play_encounter_get_order(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)?;
    if !stored.is_empty() && stored.len() == map.len() {
        let mut order = Vec::with_capacity(stored.len());
        for id in stored {
            if let Some(c) = map.get(&id) {
                order.push(c.clone());
            }
        }
        if order.len() == map.len() {
            return Ok(order);
        }
    }
    let mut list: Vec<EncounterCombatant> = map.into_values().collect();
    list.sort_by(encounter_order_cmp);
    Ok(list)
}

fn encounter_order_insert(
    campaign_id: &str,
    encounter_id: &str,
    id: &str,
    new_c: &EncounterCombatant,
) -> Result<(), PlayError> {
    let mut order =
        play_encounter_get_order(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)?;
    let map = build_encounter_combatant_map(campaign_id, encounter_id)?;
    if order.is_empty() {
        let mut list: Vec<&EncounterCombatant> = map.values().collect();
        list.sort_by(|a, b| encounter_order_cmp(a, b));
        order = list
            .iter()
            .map(|c| c.identifier().to_string())
            .collect();
    } else {
        let mut idx = order.len();
        for (i, existing_id) in order.iter().enumerate() {
            let existing = map.get(existing_id).ok_or(PlayError::BadRequest)?;
            if encounter_order_cmp(existing, new_c) == std::cmp::Ordering::Greater {
                idx = i;
                break;
            }
        }
        order.insert(idx, id.to_string());
    }
    play_encounter_set_order(campaign_id, encounter_id, &order).map_err(|_| PlayError::BadRequest)
}

fn encounter_order_remove(
    campaign_id: &str,
    encounter_id: &str,
    id: &str,
) -> Result<(), PlayError> {
    let mut order =
        play_encounter_get_order(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)?;
    if let Some(pos) = order.iter().position(|x| x == id) {
        order.remove(pos);
        play_encounter_set_order(campaign_id, encounter_id, &order)
            .map_err(|_| PlayError::BadRequest)?;
    }
    Ok(())
}

fn format_encounter_active(active: &EncounterCombatant) -> String {
    format!(
        r#"{{"name":"{}","kind":"{}","initiative":{}}}"#,
        escape_json(&active.name),
        escape_json(&active.kind),
        active.initiative
    )
}

/// Parse a play encounter turn path.
///
/// `/v1/play/campaigns/{id}/encounters/{enc_id}/turn` returns
/// `(campaign_id, encounter_id)`.
pub fn parse_play_encounter_turn_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/encounters/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    let after = &rest[mid + marker.len()..];
    let encounter_id = after.strip_suffix("/turn")?;
    if campaign_id.is_empty() || encounter_id.is_empty() {
        return None;
    }
    Some((campaign_id, encounter_id))
}

/// Parse a play encounter turn-advance path.
///
/// `/v1/play/campaigns/{id}/encounters/{enc_id}/turn/advance` returns
/// `(campaign_id, encounter_id)`.
pub fn parse_play_encounter_turn_advance_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/encounters/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    let after = &rest[mid + marker.len()..];
    let encounter_id = after.strip_suffix("/turn/advance")?;
    if campaign_id.is_empty() || encounter_id.is_empty() {
        return None;
    }
    Some((campaign_id, encounter_id))
}

/// Read the current turn for a play encounter.
///
/// GET /v1/play/campaigns/{id}/encounters/{enc_id}/turn
///
/// Any campaign member (or the owner) may read the current combatant.
pub fn get_encounter_turn(
    campaign_id: &str,
    encounter_id: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    if !play_encounter_exists(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor
        && !play_campaign_member_exists(campaign_id, actor).map_err(|_| PlayError::BadRequest)?
    {
        return Err(PlayError::Forbidden);
    }
    let (round, turn_index) =
        play_encounter_get_turn(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)?;
    let order = load_encounter_combatants(campaign_id, encounter_id)?;
    if order.is_empty() {
        return Err(PlayError::BadRequest);
    }
    let idx = (turn_index as usize).rem_euclid(order.len());
    let active = &order[idx];
    Ok(format!(
        r#"{{"round":{},"turn_index":{},"active":{}}}"#,
        round,
        idx,
        format_encounter_active(active)
    ))
}

/// Advance the turn for a play encounter.
///
/// POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/advance
///
/// Only the campaign owner or the currently active combatant may advance.
/// Acting out of turn returns 409.
pub fn advance_encounter_turn(
    campaign_id: &str,
    encounter_id: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    if !play_encounter_exists(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    let order = load_encounter_combatants(campaign_id, encounter_id)?;
    if order.is_empty() {
        return Err(PlayError::BadRequest);
    }
    let (mut round, turn_index) =
        play_encounter_get_turn(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)?;
    let idx = (turn_index as usize).rem_euclid(order.len());
    let active = &order[idx];
    let is_owner = owner == actor;
    let is_current = active.member.as_deref() == Some(actor);
    if !is_owner && !is_current {
        return Err(PlayError::Conflict);
    }
    let next_idx = (idx + 1) % order.len();
    if next_idx == 0 {
        round += 1;
    }
    play_encounter_set_turn(campaign_id, encounter_id, round, next_idx as i64)
        .map_err(|_| PlayError::BadRequest)?;
    let next_active = &order[next_idx];
    let _ = play_encounter_decrement_conditions(campaign_id, encounter_id, next_active.identifier())
        .map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"round":{},"turn_index":{},"active":{}}}"#,
        round,
        next_idx,
        format_encounter_active(next_active)
    ))
}

/// Parse a play encounter turn-delay path.
///
/// `/v1/play/campaigns/{id}/encounters/{enc_id}/turn/delay` returns
/// `(campaign_id, encounter_id)`.
pub fn parse_play_encounter_turn_delay_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/encounters/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    let after = &rest[mid + marker.len()..];
    let encounter_id = after.strip_suffix("/turn/delay")?;
    if campaign_id.is_empty() || encounter_id.is_empty() {
        return None;
    }
    Some((campaign_id, encounter_id))
}

/// Delay the current combatant's turn to a later initiative position.
///
/// POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/delay
///
/// The body may contain `new_index`, `index`, or `position` giving the target
/// position in the order array (0-based). Only the current combatant or the
/// campaign owner may delay. The delayed combatant is moved to the target
/// position, the turn follows the delayed combatant, and the new order is
/// returned.
pub fn delay_encounter_turn(
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    if !play_encounter_exists(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    let order = load_encounter_combatants(campaign_id, encounter_id)?;
    if order.is_empty() {
        return Err(PlayError::BadRequest);
    }
    let (round, turn_index) =
        play_encounter_get_turn(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)?;
    let idx = (turn_index as usize).rem_euclid(order.len());
    let active = &order[idx];
    let is_owner = owner == actor;
    let is_current = active.member.as_deref() == Some(actor);
    if !is_owner && !is_current {
        return Err(PlayError::Forbidden);
    }
    let target_idx_i64 = extract_int(body, "new_index")
        .or_else(|| extract_int(body, "index"))
        .or_else(|| extract_int(body, "position"))
        .ok_or(PlayError::BadRequest)?;
    if target_idx_i64 < 0 {
        return Err(PlayError::BadRequest);
    }
    let target_idx = target_idx_i64 as usize;
    if target_idx <= idx || target_idx >= order.len() {
        return Err(PlayError::BadRequest);
    }
    let mut new_order = order.clone();
    let current = new_order.remove(idx);
    new_order.insert(target_idx, current);
    let ids: Vec<String> = new_order.iter().map(|c| c.identifier().to_string()).collect();
    play_encounter_set_order(campaign_id, encounter_id, &ids).map_err(|_| PlayError::BadRequest)?;
    play_encounter_set_turn(campaign_id, encounter_id, round, target_idx as i64)
        .map_err(|_| PlayError::BadRequest)?;
    let order_json = new_order
        .iter()
        .map(format_encounter_active)
        .collect::<Vec<_>>()
        .join(",");
    Ok(format!(r#"{{"order":[{}]}}"#, order_json))
}

/// Parse a play encounter turn-ready path.
///
/// `/v1/play/campaigns/{id}/encounters/{enc_id}/turn/ready` returns
/// `(campaign_id, encounter_id)`.
pub fn parse_play_encounter_turn_ready_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/encounters/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    let after = &rest[mid + marker.len()..];
    let encounter_id = after.strip_suffix("/turn/ready")?;
    if campaign_id.is_empty() || encounter_id.is_empty() {
        return None;
    }
    Some((campaign_id, encounter_id))
}

/// Ready an action for the current combatant.
///
/// POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/ready
///
/// The body must contain a non-empty `trigger`. Only the current player
/// combatant may ready an action. A ready action does not change the turn
/// order.
pub fn ready_encounter_turn(
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    if !play_encounter_exists(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let order = load_encounter_combatants(campaign_id, encounter_id)?;
    if order.is_empty() {
        return Err(PlayError::BadRequest);
    }
    let (_round, turn_index) =
        play_encounter_get_turn(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)?;
    let idx = (turn_index as usize).rem_euclid(order.len());
    let active = &order[idx];
    if active.member.as_deref() != Some(actor) {
        return Err(PlayError::Forbidden);
    }
    let trigger = extract_string(body, "trigger").ok_or(PlayError::BadRequest)?;
    if trigger.is_empty() {
        return Err(PlayError::BadRequest);
    }
    Ok(format!(
        r#"{{"actor":"{}","trigger":"{}"}}"#,
        escape_json(actor),
        escape_json(trigger)
    ))
}

/// Parse a play encounter action collection path.
///
/// For example, `/v1/play/campaigns/{id}/encounters/{enc_id}/actions`
/// returns `(campaign_id, encounter_id)`.
pub fn parse_play_encounter_actions_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/encounters/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    let after = &rest[mid + marker.len()..];
    let encounter_id = after.strip_suffix("/actions")?;
    if campaign_id.is_empty() || encounter_id.is_empty() {
        return None;
    }
    Some((campaign_id, encounter_id))
}

/// Submit a typed combat action for the current encounter combatant.
///
/// POST /v1/play/campaigns/{id}/encounters/{enc_id}/actions
///
/// Only the currently active player combatant may call this endpoint. The
/// action is recorded but does not advance the encounter turn. Valid action
/// types are `attack`, `help`, `dodge`, and `ready`.
pub fn submit_encounter_action(
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    if !play_encounter_exists(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    if !play_campaign_member_exists(campaign_id, actor).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::Forbidden);
    }

    let order = load_encounter_combatants(campaign_id, encounter_id)?;
    if order.is_empty() {
        return Err(PlayError::BadRequest);
    }
    let (_round, turn_index) =
        play_encounter_get_turn(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)?;
    let idx = (turn_index as usize).rem_euclid(order.len());
    let active = &order[idx];
    if active.member.as_deref() != Some(actor) {
        return Err(PlayError::Conflict);
    }

    let action_type = extract_string(body, "type").ok_or(PlayError::BadRequest)?;
    let target = extract_string(body, "target").ok_or(PlayError::BadRequest)?;
    let text = extract_string(body, "text").ok_or(PlayError::BadRequest)?;
    if action_type.is_empty() || target.is_empty() || text.is_empty() || actor.is_empty() {
        return Err(PlayError::BadRequest);
    }
    if action_type != "attack"
        && action_type != "help"
        && action_type != "dodge"
        && action_type != "ready"
    {
        return Err(PlayError::BadRequest);
    }

    let sequence =
        play_narration_next_sequence(campaign_id).map_err(|_| PlayError::BadRequest)?;
    play_narration_create_with_target(
        campaign_id,
        sequence,
        "combat_action",
        actor,
        &target,
        &text,
    )
    .map_err(|_| PlayError::BadRequest)?;

    Ok(format!(
        r#"{{"sequence":{},"kind":"combat_action","actor":"{}","type":"{}","target":"{}","text":"{}"}}"#,
        sequence,
        escape_json(actor),
        escape_json(&action_type),
        escape_json(&target),
        escape_json(&text)
    ))
}

fn resolve_encounter_hp(
    campaign_id: &str,
    encounter_id: &str,
    target: &str,
) -> Result<(i64, i64, bool), PlayError> {
    let monster_exists = play_encounter_monster_exists(campaign_id, encounter_id, target)
        .map_err(|_| PlayError::BadRequest)?;
    let member_exists = play_encounter_combatant_exists(campaign_id, encounter_id, target)
        .map_err(|_| PlayError::BadRequest)?;
    if !monster_exists && !member_exists {
        return Err(PlayError::NotFound);
    }
    if monster_exists {
        let (hp_current, hp_max) = play_encounter_monster_hp(campaign_id, encounter_id, target)
            .map_err(|_| PlayError::BadRequest)?;
        Ok((hp_current, hp_max, true))
    } else {
        let (hp_current, hp_max) = play_campaign_member_hp(campaign_id, target)
            .map_err(|_| PlayError::BadRequest)?;
        Ok((hp_current, hp_max, false))
    }
}

fn set_encounter_hp(
    campaign_id: &str,
    encounter_id: &str,
    target: &str,
    hp_after: i64,
    is_monster: bool,
) -> Result<(), PlayError> {
    if is_monster {
        play_encounter_monster_set_hp_current(campaign_id, encounter_id, target, hp_after)
            .map_err(|_| PlayError::BadRequest)
    } else {
        play_campaign_member_set_hp_current(campaign_id, target, hp_after)
            .map_err(|_| PlayError::BadRequest)
    }
}

/// Apply deterministic damage or healing to an encounter combatant.
fn adjust_encounter_combatant_hp(
    campaign_id: &str,
    encounter_id: &str,
    target: &str,
    amount: i64,
    heal: bool,
) -> Result<(i64, i64), PlayError> {
    let (hp_before, hp_max, is_monster) = resolve_encounter_hp(campaign_id, encounter_id, target)?;
    let hp_after = if heal {
        hp_before + amount
    } else {
        hp_before - amount
    };
    let hp_after = hp_after.max(0).min(hp_max);
    set_encounter_hp(campaign_id, encounter_id, target, hp_after, is_monster)?;
    Ok((hp_before, hp_after))
}

/// Parse a play encounter damage path.
///
/// `/v1/play/campaigns/{id}/encounters/{enc_id}/damage` returns
/// `(campaign_id, encounter_id)`.
pub fn parse_play_encounter_damage_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/encounters/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    let after = &rest[mid + marker.len()..];
    let encounter_id = after.strip_suffix("/damage")?;
    if campaign_id.is_empty() || encounter_id.is_empty() {
        return None;
    }
    Some((campaign_id, encounter_id))
}

/// Parse a play encounter healing path.
///
/// `/v1/play/campaigns/{id}/encounters/{enc_id}/heal` returns
/// `(campaign_id, encounter_id)`.
pub fn parse_play_encounter_heal_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/encounters/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    let after = &rest[mid + marker.len()..];
    let encounter_id = after.strip_suffix("/heal")?;
    if campaign_id.is_empty() || encounter_id.is_empty() {
        return None;
    }
    Some((campaign_id, encounter_id))
}

/// Apply deterministic damage to an encounter combatant.
///
/// POST /v1/play/campaigns/{id}/encounters/{enc_id}/damage
///
/// Only the campaign owner may damage combatants. The request names a target
/// combatant (monster or bound party member) and an amount. HP floors at 0.
pub fn damage_encounter_combatant(
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    if !play_encounter_exists(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let target = extract_string(body, "target").ok_or(PlayError::BadRequest)?;
    let amount = extract_int(body, "amount").ok_or(PlayError::BadRequest)?;
    if target.is_empty() || amount < 0 {
        return Err(PlayError::BadRequest);
    }
    let (hp_before, hp_after) =
        adjust_encounter_combatant_hp(campaign_id, encounter_id, target, amount, false)?;
    Ok(format!(
        r#"{{"target":"{}","hp_before":{},"hp_after":{},"damage":{}}}"#,
        escape_json(target),
        hp_before,
        hp_after,
        amount
    ))
}

/// Apply deterministic healing to an encounter combatant.
///
/// POST /v1/play/campaigns/{id}/encounters/{enc_id}/heal
///
/// Only the campaign owner may heal combatants. HP caps at `hp_max`.
pub fn heal_encounter_combatant(
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    if !play_encounter_exists(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let target = extract_string(body, "target").ok_or(PlayError::BadRequest)?;
    let amount = extract_int(body, "amount").ok_or(PlayError::BadRequest)?;
    if target.is_empty() || amount < 0 {
        return Err(PlayError::BadRequest);
    }
    let (hp_before, hp_after) =
        adjust_encounter_combatant_hp(campaign_id, encounter_id, target, amount, true)?;
    Ok(format!(
        r#"{{"target":"{}","hp_before":{},"hp_after":{},"healing":{}}}"#,
        escape_json(target),
        hp_before,
        hp_after,
        amount
    ))
}

/// Parse a play campaign character sub-resource path.
///
/// For example, `/v1/play/campaigns/{id}/characters/{char_id}/status` returns
/// `(campaign_id, character_id)` when `suffix` is `/status`.
pub fn parse_play_campaign_character_path<'a>(
    path: &'a str,
    suffix: &'a str,
) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/characters/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    if campaign_id.is_empty() {
        return None;
    }
    let after = &rest[mid + marker.len()..];
    let character_id = after.strip_suffix(suffix)?;
    if character_id.is_empty() {
        return None;
    }
    Some((campaign_id, character_id))
}

/// Apply deterministic damage to a campaign character.
///
/// POST /v1/play/campaigns/{id}/characters/{char_id}/damage
///
/// Only the campaign owner may damage a character. HP floors at 0; dropping
/// from above 0 to 0 makes the character unconscious. Healing back above 0
/// clears death saves and returns the character to healthy.
pub fn damage_character(
    campaign_id: &str,
    character_id: &str,
    body: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    let (member_actor, _char_id, hp_current, _hp_max, successes, failures, status) =
        play_campaign_member_by_character_id(campaign_id, character_id)
            .map_err(|_| PlayError::NotFound)?;
    let amount = extract_int(body, "amount").ok_or(PlayError::BadRequest)?;
    if amount < 0 {
        return Err(PlayError::BadRequest);
    }
    let hp_after = (hp_current - amount).max(0);
    let new_status = if hp_after > 0 && status != "healthy" {
        "healthy"
    } else if hp_after == 0 && hp_current > 0 {
        "unconscious"
    } else {
        &status
    };
    let new_successes = if new_status == "healthy" { 0 } else { successes };
    let new_failures = if new_status == "healthy" { 0 } else { failures };
    play_campaign_member_set_hp_status_saves(
        campaign_id,
        &member_actor,
        hp_after,
        new_status,
        new_successes,
        new_failures,
    )
    .map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"character_id":"{}","target":"{}","hp_before":{},"hp_after":{},"damage":{},"status":"{}"}}"#,
        escape_json(character_id),
        escape_json(character_id),
        hp_current,
        hp_after,
        amount,
        escape_json(new_status)
    ))
}

/// Record a death saving throw for a character at 0 HP.
///
/// POST /v1/play/campaigns/{id}/characters/{char_id}/death-saves
///
/// Only the character's owner may roll. The body must contain an `outcome` of
/// `"success"` or `"failure"`. Three successes make the character stable;
/// three failures make the character dead. Rolls are rejected once the
/// character is stable, dead, or not unconscious.
pub fn roll_death_save(
    campaign_id: &str,
    character_id: &str,
    body: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (member_actor, _char_id, hp_current, _hp_max, successes, failures, status) =
        play_campaign_member_by_character_id(campaign_id, character_id)
            .map_err(|_| PlayError::NotFound)?;
    if member_actor != actor {
        return Err(PlayError::Forbidden);
    }
    if status != "unconscious" || hp_current != 0 || successes >= 3 || failures >= 3 {
        return Err(PlayError::Conflict);
    }
    let outcome = extract_string(body, "outcome").ok_or(PlayError::BadRequest)?;
    if outcome != "success" && outcome != "failure" {
        return Err(PlayError::BadRequest);
    }
    let (new_successes, new_failures, new_status) = if outcome == "success" {
        let s = successes + 1;
        if s >= 3 {
            (s, failures, "stable")
        } else {
            (s, failures, "unconscious")
        }
    } else {
        let f = failures + 1;
        if f >= 3 {
            (successes, f, "dead")
        } else {
            (successes, f, "unconscious")
        }
    };
    play_campaign_member_set_death_saves_status(
        campaign_id,
        &member_actor,
        new_successes,
        new_failures,
        new_status,
    )
    .map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"character_id":"{}","successes":{},"failures":{},"status":"{}"}}"#,
        escape_json(character_id),
        new_successes,
        new_failures,
        escape_json(new_status)
    ))
}

/// Read a campaign character's current health status.
///
/// GET /v1/play/campaigns/{id}/characters/{char_id}/status
///
/// The campaign owner or any member may read the status.
pub fn get_character_status(
    campaign_id: &str,
    character_id: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    let is_member =
        play_campaign_member_exists(campaign_id, actor).map_err(|_| PlayError::BadRequest)?;
    if owner != actor && !is_member {
        return Err(PlayError::Forbidden);
    }
    let (_member_actor, _char_id, hp_current, hp_max, _successes, _failures, status) =
        play_campaign_member_by_character_id(campaign_id, character_id)
            .map_err(|_| PlayError::NotFound)?;
    Ok(format!(
        r#"{{"character_id":"{}","hp_current":{},"hp_max":{},"status":"{}"}}"#,
        escape_json(character_id),
        hp_current,
        hp_max,
        escape_json(&status)
    ))
}

/// Parse a play encounter conditions collection path.
///
/// `/v1/play/campaigns/{id}/encounters/{enc_id}/conditions` returns
/// `(campaign_id, encounter_id)`.
pub fn parse_play_encounter_conditions_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/encounters/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    let after = &rest[mid + marker.len()..];
    let encounter_id = after.strip_suffix("/conditions")?;
    if campaign_id.is_empty() || encounter_id.is_empty() {
        return None;
    }
    Some((campaign_id, encounter_id))
}

/// Parse a play encounter status path.
///
/// `/v1/play/campaigns/{id}/encounters/{enc_id}/status` returns
/// `(campaign_id, encounter_id)`.
pub fn parse_play_encounter_status_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/encounters/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    let after = &rest[mid + marker.len()..];
    let encounter_id = after.strip_suffix("/status")?;
    if campaign_id.is_empty() || encounter_id.is_empty() {
        return None;
    }
    Some((campaign_id, encounter_id))
}

fn format_encounter_conditions_map(
    campaign_id: &str,
    encounter_id: &str,
) -> Result<String, PlayError> {
    let rows = play_encounter_all_conditions(campaign_id, encounter_id)
        .map_err(|_| PlayError::BadRequest)?;
    let mut by_target: std::collections::HashMap<String, Vec<(String, i64)>> = std::collections::HashMap::new();
    for (target, name, remaining) in rows {
        by_target.entry(target).or_default().push((name, remaining));
    }
    let mut targets: Vec<&String> = by_target.keys().collect();
    targets.sort();
    let entries = targets
        .iter()
        .map(|t| {
            let list = by_target.get(*t).unwrap();
            let arr = list
                .iter()
                .map(|(name, remaining)| {
                    format!(
                        r#"{{"condition":"{}","remaining_rounds":{}}}"#,
                        escape_json(name),
                        remaining
                    )
                })
                .collect::<Vec<_>>()
                .join(",");
            format!(r#""{}":[{}]"#, escape_json(t), arr)
        })
        .collect::<Vec<_>>()
        .join(",");
    Ok(format!("{{{}}}", entries))
}

/// Apply a named condition to an encounter combatant.
///
/// POST /v1/play/campaigns/{id}/encounters/{enc_id}/conditions
///
/// Only the campaign owner may apply conditions. The target must be a bound
/// combatant (monster or party member). The response returns the target's
/// current condition list.
pub fn add_encounter_condition(
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    if !play_encounter_exists(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let target = extract_string(body, "target").ok_or(PlayError::BadRequest)?;
    let condition = extract_string(body, "condition").ok_or(PlayError::BadRequest)?;
    let duration = extract_int(body, "duration_rounds").ok_or(PlayError::BadRequest)?;
    if target.is_empty() || condition.is_empty() || duration < 1 {
        return Err(PlayError::BadRequest);
    }
    let order = load_encounter_combatants(campaign_id, encounter_id)?;
    if !order.iter().any(|c| c.identifier() == target) {
        return Err(PlayError::BadRequest);
    }
    play_encounter_add_condition(campaign_id, encounter_id, target, condition, duration)
        .map_err(|_| PlayError::BadRequest)?;
    let list = play_encounter_conditions_for_target(campaign_id, encounter_id, target)
        .map_err(|_| PlayError::BadRequest)?;
    let conditions_json = list
        .iter()
        .map(|(name, remaining)| {
            format!(
                r#"{{"condition":"{}","remaining_rounds":{}}}"#,
                escape_json(name),
                remaining
            )
        })
        .collect::<Vec<_>>()
        .join(",");
    Ok(format!(
        r#"{{"target":"{}","conditions":[{}]}}"#,
        escape_json(target),
        conditions_json
    ))
}

/// Read the full state of a play encounter.
///
/// GET /v1/play/campaigns/{id}/encounters/{enc_id}/status
///
/// The campaign owner or any member may read the status. The response includes
/// the round, turn index, active combatant, full initiative order, and a map of
/// conditions keyed by combatant identifier (monster_id or member actor).
pub fn get_encounter_status(
    campaign_id: &str,
    encounter_id: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    if !play_encounter_exists(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    let is_member =
        play_campaign_member_exists(campaign_id, actor).map_err(|_| PlayError::BadRequest)?;
    if owner != actor && !is_member {
        return Err(PlayError::Forbidden);
    }
    let (round, turn_index) =
        play_encounter_get_turn(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)?;
    let order = load_encounter_combatants(campaign_id, encounter_id)?;
    if order.is_empty() {
        return Err(PlayError::BadRequest);
    }
    let idx = (turn_index as usize).rem_euclid(order.len());
    let active = &order[idx];
    let order_json = order
        .iter()
        .map(|c| format_encounter_active(c))
        .collect::<Vec<_>>()
        .join(",");
    let conditions_json = format_encounter_conditions_map(campaign_id, encounter_id)?;
    Ok(format!(
        r#"{{"round":{},"turn_index":{},"active":{},"order":[{}],"conditions":{}}}"#,
        round,
        idx,
        format_encounter_active(active),
        order_json,
        conditions_json
    ))
}

/// Parse a play encounter rewards path.
///
/// `/v1/play/campaigns/{id}/encounters/{enc_id}/rewards` returns
/// `(campaign_id, encounter_id)`.
pub fn parse_play_encounter_rewards_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/encounters/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    let after = &rest[mid + marker.len()..];
    let encounter_id = after.strip_suffix("/rewards")?;
    if campaign_id.is_empty() || encounter_id.is_empty() {
        return None;
    }
    Some((campaign_id, encounter_id))
}

/// Parse a play encounter close path.
///
/// `/v1/play/campaigns/{id}/encounters/{enc_id}/close` returns
/// `(campaign_id, encounter_id)`.
pub fn parse_play_encounter_close_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/encounters/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    let after = &rest[mid + marker.len()..];
    let encounter_id = after.strip_suffix("/close")?;
    if campaign_id.is_empty() || encounter_id.is_empty() {
        return None;
    }
    Some((campaign_id, encounter_id))
}

fn parse_loot_items(body: &str) -> Result<Vec<(String, i64)>, PlayError> {
    let content = extract_array_content(body, "loot").ok_or(PlayError::BadRequest)?;
    let mut loot = Vec::new();
    for obj in extract_objects(content) {
        let slug = extract_string(obj, "slug").ok_or(PlayError::BadRequest)?;
        let quantity = extract_int(obj, "quantity").ok_or(PlayError::BadRequest)?;
        if slug.is_empty() || quantity < 1 {
            return Err(PlayError::BadRequest);
        }
        loot.push((slug.to_string(), quantity));
    }
    Ok(loot)
}

/// Award deterministic XP and loot for an encounter.
///
/// POST /v1/play/campaigns/{id}/encounters/{enc_id}/rewards
///
/// Only the campaign owner may award rewards. The reward record is returned.
/// Rewards may be awarded only once per encounter; duplicates return 409.
pub fn award_encounter_rewards(
    campaign_id: &str,
    encounter_id: &str,
    body: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    if !play_encounter_exists(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let xp = extract_int(body, "xp").ok_or(PlayError::BadRequest)?;
    if xp < 0 {
        return Err(PlayError::BadRequest);
    }
    let loot = parse_loot_items(body)?;
    let (_xp_awarded, rewards_awarded, _existing_loot) = play_encounter_get_rewards(
        campaign_id,
        encounter_id,
    )
    .map_err(|_| PlayError::BadRequest)?;
    if rewards_awarded {
        return Err(PlayError::Conflict);
    }
    play_encounter_set_rewards(campaign_id, encounter_id, xp, &loot)
        .map_err(|_| PlayError::BadRequest)?;
    let loot_json = loot
        .iter()
        .map(|(slug, quantity)| {
            format!(
                r#"{{"slug":"{}","quantity":{}}}"#,
                escape_json(slug),
                quantity
            )
        })
        .collect::<Vec<_>>()
        .join(",");
    Ok(format!(
        r#"{{"xp":{},"loot":[{}]}}"#,
        xp, loot_json
    ))
}

/// Close a play encounter.
///
/// POST /v1/play/campaigns/{id}/encounters/{enc_id}/close
///
/// Only the campaign owner may close an encounter. Closing before awarding
/// rewards returns `xp_awarded: 0`.
pub fn close_encounter(
    campaign_id: &str,
    encounter_id: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    if !play_encounter_exists(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (xp_awarded, _rewards_awarded, _loot) = play_encounter_get_rewards(
        campaign_id,
        encounter_id,
    )
    .map_err(|_| PlayError::BadRequest)?;
    play_encounter_close(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"id":"{}","status":"closed","xp_awarded":{}}}"#,
        escape_json(encounter_id),
        xp_awarded
    ))
}

/// Parse a play encounter end-of-combat path.
///
/// `/v1/play/campaigns/{id}/encounters/{enc_id}/end` returns
/// `(campaign_id, encounter_id)`.
pub fn parse_play_encounter_end_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/play/campaigns/")?;
    let marker = "/encounters/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    let after = &rest[mid + marker.len()..];
    let encounter_id = after.strip_suffix("/end")?;
    if campaign_id.is_empty() || encounter_id.is_empty() {
        return None;
    }
    Some((campaign_id, encounter_id))
}

/// End a play encounter and return the campaign to exploration.
///
/// POST /v1/play/campaigns/{id}/encounters/{enc_id}/end
///
/// Only the campaign owner may end an encounter. The encounter is closed if
/// still active and the campaign phase returns to `exploration`, resuming the
/// turn queue from the actor recorded before combat began. If the campaign is
/// not in combat (no active encounter), return 409.
pub fn end_encounter(
    campaign_id: &str,
    encounter_id: &str,
    actor: &str,
) -> Result<String, PlayError> {
    if !play_campaign_exists(campaign_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (owner, _status) =
        play_campaign_owner_status(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if owner != actor {
        return Err(PlayError::Forbidden);
    }
    if !play_encounter_exists(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)? {
        return Err(PlayError::NotFound);
    }
    let (_current_actor, phase, _turn_number) =
        play_campaign_get_turn(campaign_id).map_err(|_| PlayError::BadRequest)?;
    if phase != "combat" {
        return Err(PlayError::Conflict);
    }
    let encounter_status = play_encounter_get_status(campaign_id, encounter_id)
        .map_err(|_| PlayError::BadRequest)?;
    if encounter_status == "active" {
        play_encounter_close(campaign_id, encounter_id).map_err(|_| PlayError::BadRequest)?;
    }
    let exploration_actor = play_campaign_get_exploration_actor(campaign_id)
        .map_err(|_| PlayError::BadRequest)?;
    let restore_actor = if exploration_actor.is_empty() {
        "dm"
    } else {
        &exploration_actor
    };
    play_campaign_update_turn(campaign_id, restore_actor, "exploration", 1)
        .map_err(|_| PlayError::BadRequest)?;
    Ok(format!(
        r#"{{"campaign_id":"{}","status":"active","phase":"exploration","current_actor":"{}"}}"#,
        escape_json(campaign_id),
        escape_json(restore_actor)
    ))
}

