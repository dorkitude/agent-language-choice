use crate::json::{
    escape_json, extract_int, extract_objects, extract_string, extract_string_array,
    extract_top_array_content,
};
use crate::store::{
    campaign_exists, character_exists, event_exists, session_create, session_exists, session_get_next,
    session_set_attendance, sqlite_exec, sqlite_query,
};

pub enum CampaignError {
    BadRequest,
    NotFound,
    Conflict,
}

/// Parse a campaign id from a path like `/v1/campaigns/{id}/suffix`.
pub fn parse_campaign_path<'a>(path: &'a str, suffix: &'a str) -> Option<&'a str> {
    let rest = path.strip_prefix("/v1/campaigns/")?;
    let id = rest.strip_suffix(suffix)?;
    if id.is_empty() {
        return None;
    }
    Some(id)
}

/// Create a new campaign.
///
/// All fields (`id`, `name`, `dm`) are required and must be non-empty strings.
pub fn create_campaign(body: &str) -> Result<String, CampaignError> {
    let id = extract_string(body, "id").ok_or(CampaignError::BadRequest)?;
    let name = extract_string(body, "name").ok_or(CampaignError::BadRequest)?;
    let dm = extract_string(body, "dm").ok_or(CampaignError::BadRequest)?;
    if id.is_empty() || name.is_empty() || dm.is_empty() {
        return Err(CampaignError::BadRequest);
    }
    if campaign_exists(id).map_err(|_| CampaignError::BadRequest)? {
        return Err(CampaignError::Conflict);
    }
    let sql = format!(
        "INSERT INTO campaigns (id, name, dm) VALUES ('{}', '{}', '{}');",
        crate::store::sql_escape(id),
        crate::store::sql_escape(name),
        crate::store::sql_escape(dm)
    );
    sqlite_exec(&sql).map_err(|_| CampaignError::BadRequest)?;
    Ok(format!(
        r#"{{"id":"{}","name":"{}","dm":"{}"}}"#,
        escape_json(id),
        escape_json(name),
        escape_json(dm)
    ))
}

/// Add a player character to a campaign.
///
/// Requires a valid campaign, non-empty `id`/`name`/`class`, and a level of at
/// least 1.
pub fn add_character(campaign_id: &str, body: &str) -> Result<String, CampaignError> {
    if !campaign_exists(campaign_id).map_err(|_| CampaignError::BadRequest)? {
        return Err(CampaignError::NotFound);
    }
    let id = extract_string(body, "id").ok_or(CampaignError::BadRequest)?;
    let name = extract_string(body, "name").ok_or(CampaignError::BadRequest)?;
    let level = extract_int(body, "level").ok_or(CampaignError::BadRequest)?;
    let class = extract_string(body, "class").ok_or(CampaignError::BadRequest)?;
    if id.is_empty() || name.is_empty() || class.is_empty() || level < 1 {
        return Err(CampaignError::BadRequest);
    }
    if character_exists(campaign_id, id).map_err(|_| CampaignError::BadRequest)? {
        return Err(CampaignError::Conflict);
    }
    let sql = format!(
        "INSERT INTO characters (campaign_id, id, name, level, class) VALUES ('{}', '{}', '{}', {}, '{}');",
        crate::store::sql_escape(campaign_id),
        crate::store::sql_escape(id),
        crate::store::sql_escape(name),
        level,
        crate::store::sql_escape(class)
    );
    sqlite_exec(&sql).map_err(|_| CampaignError::BadRequest)?;
    Ok(format!(
        r#"{{"id":"{}","name":"{}","level":{},"class":"{}"}}"#,
        escape_json(id),
        escape_json(name),
        level,
        escape_json(class)
    ))
}

/// Add a log event to a campaign.
///
/// `id` and `kind` must be non-empty. `summary` is required but may be empty.
pub fn add_event(campaign_id: &str, body: &str) -> Result<String, CampaignError> {
    if !campaign_exists(campaign_id).map_err(|_| CampaignError::BadRequest)? {
        return Err(CampaignError::NotFound);
    }
    let id = extract_string(body, "id").ok_or(CampaignError::BadRequest)?;
    let kind = extract_string(body, "kind").ok_or(CampaignError::BadRequest)?;
    let summary = extract_string(body, "summary").ok_or(CampaignError::BadRequest)?;
    if id.is_empty() || kind.is_empty() {
        return Err(CampaignError::BadRequest);
    }
    if event_exists(campaign_id, id).map_err(|_| CampaignError::BadRequest)? {
        return Err(CampaignError::Conflict);
    }
    let sql = format!(
        "INSERT INTO events (campaign_id, id, kind, summary) VALUES ('{}', '{}', '{}', '{}');",
        crate::store::sql_escape(campaign_id),
        crate::store::sql_escape(id),
        crate::store::sql_escape(kind),
        crate::store::sql_escape(summary)
    );
    sqlite_exec(&sql).map_err(|_| CampaignError::BadRequest)?;
    Ok(format!(
        r#"{{"id":"{}","kind":"{}"}}"#,
        escape_json(id),
        escape_json(kind)
    ))
}

/// Read a campaign summary including its characters and event count.
pub fn read_campaign_state(campaign_id: &str) -> Result<String, CampaignError> {
    if !campaign_exists(campaign_id).map_err(|_| CampaignError::BadRequest)? {
        return Err(CampaignError::NotFound);
    }
    let sql = format!(
        "SELECT id, name, dm FROM campaigns WHERE id = '{}';",
        crate::store::sql_escape(campaign_id)
    );
    let output = sqlite_query(&sql).map_err(|_| CampaignError::BadRequest)?;
    let content = extract_top_array_content(&output).ok_or(CampaignError::NotFound)?;
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err(CampaignError::NotFound);
    }
    let obj = objects[0];
    let id = extract_string(obj, "id").ok_or(CampaignError::BadRequest)?;
    let name = extract_string(obj, "name").ok_or(CampaignError::BadRequest)?;
    let dm = extract_string(obj, "dm").ok_or(CampaignError::BadRequest)?;

    let char_sql = format!(
        "SELECT id, name, level, class FROM characters WHERE campaign_id = '{}' ORDER BY rowid;",
        crate::store::sql_escape(campaign_id)
    );
    let char_output = sqlite_query(&char_sql).map_err(|_| CampaignError::BadRequest)?;
    let char_content = extract_top_array_content(&char_output).unwrap_or("");
    let mut chars_json = Vec::new();
    for c_obj in extract_objects(char_content) {
        let cid = extract_string(c_obj, "id").ok_or(CampaignError::BadRequest)?;
        let cname = extract_string(c_obj, "name").ok_or(CampaignError::BadRequest)?;
        let level = extract_int(c_obj, "level").ok_or(CampaignError::BadRequest)?;
        let class = extract_string(c_obj, "class").ok_or(CampaignError::BadRequest)?;
        chars_json.push(format!(
            r#"{{"id":"{}","name":"{}","level":{},"class":"{}"}}"#,
            escape_json(cid),
            escape_json(cname),
            level,
            escape_json(class)
        ));
    }

    let count_sql = format!(
        "SELECT COUNT(*) AS log_count FROM events WHERE campaign_id = '{}';",
        crate::store::sql_escape(campaign_id)
    );
    let count_output = sqlite_query(&count_sql).map_err(|_| CampaignError::BadRequest)?;
    let count_content = extract_top_array_content(&count_output).unwrap_or("");
    let count_objects = extract_objects(count_content);
    let log_count = if count_objects.is_empty() {
        0
    } else {
        extract_int(count_objects[0], "log_count").unwrap_or(0)
    };

    Ok(format!(
        r#"{{"id":"{}","name":"{}","dm":"{}","characters":[{}],"log_count":{}}}"#,
        escape_json(id),
        escape_json(name),
        escape_json(dm),
        chars_json.join(","),
        log_count
    ))
}

/// Parse a campaign session attendance path:
/// `/v1/campaigns/{id}/sessions/{session_id}/attendance`.
pub fn parse_campaign_session_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/campaigns/")?;
    let marker = "/sessions/";
    let mid = rest.find(marker)?;
    let campaign_id = &rest[..mid];
    if campaign_id.is_empty() {
        return None;
    }
    let after = &rest[mid + marker.len()..];
    let session_id = after.strip_suffix("/attendance")?;
    if session_id.is_empty() {
        return None;
    }
    Some((campaign_id, session_id))
}

/// Schedule a new campaign session.
///
/// POST /v1/campaigns/{id}/sessions
pub fn schedule_session(campaign_id: &str, body: &str) -> Result<String, CampaignError> {
    if !campaign_exists(campaign_id).map_err(|_| CampaignError::BadRequest)? {
        return Err(CampaignError::NotFound);
    }
    let id = extract_string(body, "id").ok_or(CampaignError::BadRequest)?;
    let starts_at = extract_string(body, "starts_at").ok_or(CampaignError::BadRequest)?;
    let duration_minutes = extract_int(body, "duration_minutes").ok_or(CampaignError::BadRequest)?;
    let agenda = extract_string_array(body, "agenda").ok_or(CampaignError::BadRequest)?;
    if id.is_empty() || starts_at.is_empty() || duration_minutes < 1 {
        return Err(CampaignError::BadRequest);
    }
    if session_exists(campaign_id, id).map_err(|_| CampaignError::BadRequest)? {
        return Err(CampaignError::Conflict);
    }
    session_create(campaign_id, id, starts_at, duration_minutes, &agenda)
        .map_err(|_| CampaignError::BadRequest)?;
    Ok(format!(
        r#"{{"id":"{}","starts_at":"{}","duration_minutes":{},"agenda_count":{}}}"#,
        escape_json(id),
        escape_json(starts_at),
        duration_minutes,
        agenda.len()
    ))
}

/// Record attendance for a specific campaign session.
///
/// POST /v1/campaigns/{id}/sessions/{session_id}/attendance
pub fn record_attendance(
    campaign_id: &str,
    session_id: &str,
    body: &str,
) -> Result<String, CampaignError> {
    if !campaign_exists(campaign_id).map_err(|_| CampaignError::BadRequest)? {
        return Err(CampaignError::NotFound);
    }
    if !session_exists(campaign_id, session_id).map_err(|_| CampaignError::BadRequest)? {
        return Err(CampaignError::NotFound);
    }
    let present = extract_string_array(body, "present").ok_or(CampaignError::BadRequest)?;
    let absent = extract_string_array(body, "absent").ok_or(CampaignError::BadRequest)?;
    session_set_attendance(campaign_id, session_id, &present, &absent)
        .map_err(|_| CampaignError::BadRequest)?;
    Ok(format!(
        r#"{{"session_id":"{}","present_count":{},"absent_count":{}}}"#,
        escape_json(session_id),
        present.len(),
        absent.len()
    ))
}

/// Return a deterministic audit summary for a campaign.
///
/// GET /v1/campaigns/{id}/audit
pub fn audit_campaign(campaign_id: &str) -> Result<String, CampaignError> {
    if !campaign_exists(campaign_id).map_err(|_| CampaignError::BadRequest)? {
        return Err(CampaignError::NotFound);
    }
    let events = count_rows(campaign_id, "events", "1=1")?;
    let quests = count_rows(campaign_id, "quests", "1=1")?;
    let npcs = count_rows(campaign_id, "npcs", "1=1")?;
    let sessions = count_rows(campaign_id, "campaign_sessions", "1=1")?;
    Ok(format!(
        r#"{{"campaign_id":"{}","events":{},"quests":{},"npcs":{},"sessions":{}}}"#,
        escape_json(campaign_id),
        events,
        quests,
        npcs,
        sessions
    ))
}

/// Return a deterministic export summary for a campaign.
///
/// GET /v1/campaigns/{id}/export
pub fn export_campaign(campaign_id: &str) -> Result<String, CampaignError> {
    if !campaign_exists(campaign_id).map_err(|_| CampaignError::BadRequest)? {
        return Err(CampaignError::NotFound);
    }
    let sql = format!(
        "SELECT id, name FROM campaigns WHERE id = '{}';",
        crate::store::sql_escape(campaign_id)
    );
    let output = sqlite_query(&sql).map_err(|_| CampaignError::BadRequest)?;
    let content = extract_top_array_content(&output).ok_or(CampaignError::NotFound)?;
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err(CampaignError::NotFound);
    }
    let name = extract_string(objects[0], "name").ok_or(CampaignError::BadRequest)?;

    let characters = count_rows(campaign_id, "characters", "1=1")?;
    let quests = count_rows(campaign_id, "quests", "1=1")?;
    let npcs = count_rows(campaign_id, "npcs", "1=1")?;
    let inventory_items = count_inventory_rows(campaign_id)?;
    let sessions = count_rows(campaign_id, "campaign_sessions", "1=1")?;

    Ok(format!(
        r#"{{"campaign_id":"{}","name":"{}","characters":{},"quests":{},"npcs":{},"inventory_items":{},"sessions":{},"schema_version":1}}"#,
        escape_json(campaign_id),
        escape_json(name),
        characters,
        quests,
        npcs,
        inventory_items,
        sessions
    ))
}

fn count_rows(campaign_id: &str, table: &str, predicate: &str) -> Result<i64, CampaignError> {
    let sql = format!(
        "SELECT COUNT(*) AS cnt FROM {} WHERE campaign_id = '{}' AND {};",
        table,
        crate::store::sql_escape(campaign_id),
        predicate
    );
    let output = sqlite_query(&sql).map_err(|_| CampaignError::BadRequest)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Ok(0);
    }
    extract_int(objects[0], "cnt").ok_or(CampaignError::BadRequest)
}

fn count_inventory_rows(campaign_id: &str) -> Result<i64, CampaignError> {
    let sql = format!(
        "SELECT COUNT(*) AS cnt FROM (SELECT item_slug FROM campaign_inventory WHERE campaign_id = '{}' AND quantity > 0 UNION SELECT item_slug FROM character_equipment WHERE campaign_id = '{}' AND quantity > 0);",
        crate::store::sql_escape(campaign_id),
        crate::store::sql_escape(campaign_id)
    );
    let output = sqlite_query(&sql).map_err(|_| CampaignError::BadRequest)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Ok(0);
    }
    extract_int(objects[0], "cnt").ok_or(CampaignError::BadRequest)
}

/// Return the next scheduled campaign session.
///
/// GET /v1/campaigns/{id}/sessions/next
pub fn next_session(campaign_id: &str) -> Result<String, CampaignError> {
    if !campaign_exists(campaign_id).map_err(|_| CampaignError::BadRequest)? {
        return Err(CampaignError::NotFound);
    }
    match session_get_next(campaign_id).map_err(|_| CampaignError::BadRequest)? {
        Some((id, starts_at, _duration, agenda_count)) => Ok(format!(
            r#"{{"id":"{}","starts_at":"{}","agenda_count":{}}}"#,
            escape_json(&id),
            escape_json(&starts_at),
            agenda_count
        )),
        None => Err(CampaignError::NotFound),
    }
}
