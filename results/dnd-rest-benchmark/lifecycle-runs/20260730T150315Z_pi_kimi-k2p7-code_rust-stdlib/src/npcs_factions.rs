use crate::json::{
    escape_json, extract_int, extract_objects, extract_string, extract_top_array_content,
};
use crate::store::{campaign_exists, faction_exists, npc_exists, sql_escape, sqlite_exec, sqlite_query};

pub enum NpcFactionError {
    BadRequest,
    NotFound,
    Conflict,
}

/// Create a faction within a campaign.
///
/// `id`, `name`, and `stance` are required non-empty strings. The faction id
/// must be unique within the campaign.
pub fn create_faction(campaign_id: &str, body: &str) -> Result<String, NpcFactionError> {
    if !campaign_exists(campaign_id).map_err(|_| NpcFactionError::BadRequest)? {
        return Err(NpcFactionError::NotFound);
    }
    let id = extract_string(body, "id").ok_or(NpcFactionError::BadRequest)?;
    let name = extract_string(body, "name").ok_or(NpcFactionError::BadRequest)?;
    let stance = extract_string(body, "stance").ok_or(NpcFactionError::BadRequest)?;
    if id.is_empty() || name.is_empty() || stance.is_empty() {
        return Err(NpcFactionError::BadRequest);
    }
    if faction_exists(campaign_id, id).map_err(|_| NpcFactionError::BadRequest)? {
        return Err(NpcFactionError::Conflict);
    }
    let sql = format!(
        "INSERT INTO factions (campaign_id, id, name, stance) VALUES ('{}', '{}', '{}', '{}');",
        sql_escape(campaign_id),
        sql_escape(id),
        sql_escape(name),
        sql_escape(stance)
    );
    sqlite_exec(&sql).map_err(|_| NpcFactionError::BadRequest)?;
    Ok(format!(
        r#"{{"id":"{}","name":"{}","stance":"{}"}}"#,
        escape_json(id),
        escape_json(name),
        escape_json(stance)
    ))
}

/// Create an NPC within a campaign.
///
/// `id`, `name`, and `disposition` are required. `faction_id` is optional,
/// but if provided it must reference an existing faction in the same campaign.
pub fn create_npc(campaign_id: &str, body: &str) -> Result<String, NpcFactionError> {
    if !campaign_exists(campaign_id).map_err(|_| NpcFactionError::BadRequest)? {
        return Err(NpcFactionError::NotFound);
    }
    let id = extract_string(body, "id").ok_or(NpcFactionError::BadRequest)?;
    let name = extract_string(body, "name").ok_or(NpcFactionError::BadRequest)?;
    let faction_id = extract_string(body, "faction_id").unwrap_or("");
    let disposition = extract_int(body, "disposition").ok_or(NpcFactionError::BadRequest)?;
    if id.is_empty() || name.is_empty() {
        return Err(NpcFactionError::BadRequest);
    }
    if !faction_id.is_empty()
        && !faction_exists(campaign_id, faction_id).map_err(|_| NpcFactionError::BadRequest)?
    {
        return Err(NpcFactionError::NotFound);
    }
    if npc_exists(campaign_id, id).map_err(|_| NpcFactionError::BadRequest)? {
        return Err(NpcFactionError::Conflict);
    }
    let sql = format!(
        "INSERT INTO npcs (campaign_id, id, name, faction_id, disposition) VALUES ('{}', '{}', '{}', '{}', {});",
        sql_escape(campaign_id),
        sql_escape(id),
        sql_escape(name),
        sql_escape(faction_id),
        disposition
    );
    sqlite_exec(&sql).map_err(|_| NpcFactionError::BadRequest)?;
    Ok(format!(
        r#"{{"id":"{}","name":"{}","faction_id":"{}","disposition":{}}}"#,
        escape_json(id),
        escape_json(name),
        escape_json(faction_id),
        disposition
    ))
}

/// Summarize a campaign's faction and NPC counts.
///
/// `friendly_npcs` counts NPCs with a positive disposition.
pub fn relationship_summary(campaign_id: &str) -> Result<String, NpcFactionError> {
    if !campaign_exists(campaign_id).map_err(|_| NpcFactionError::BadRequest)? {
        return Err(NpcFactionError::NotFound);
    }
    let factions = count_where(campaign_id, "factions", "1=1")?;
    let npcs = count_where(campaign_id, "npcs", "1=1")?;
    let friendly_npcs = count_where(campaign_id, "npcs", "disposition > 0")?;
    Ok(format!(
        r#"{{"campaign_id":"{}","factions":{},"npcs":{},"friendly_npcs":{}}}"#,
        escape_json(campaign_id),
        factions,
        npcs,
        friendly_npcs
    ))
}

fn count_where(campaign_id: &str, table: &str, predicate: &str) -> Result<i64, NpcFactionError> {
    let sql = format!(
        "SELECT COUNT(*) AS cnt FROM {} WHERE campaign_id = '{}' AND {};",
        table,
        sql_escape(campaign_id),
        predicate
    );
    let output = sqlite_query(&sql).map_err(|_| NpcFactionError::BadRequest)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let count = extract_objects(content)
        .first()
        .and_then(|o| extract_int(o, "cnt"))
        .unwrap_or(0);
    Ok(count)
}
