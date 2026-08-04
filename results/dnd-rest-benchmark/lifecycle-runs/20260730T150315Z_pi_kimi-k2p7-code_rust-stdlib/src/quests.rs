use crate::json::{
    escape_json, extract_int, extract_objects, extract_string, extract_string_array,
    extract_top_array_content,
};
use crate::store::{campaign_exists, quest_exists, sql_escape, sqlite_exec, sqlite_query};

pub enum QuestError {
    BadRequest,
    NotFound,
    Conflict,
}

/// Parse a campaign id from a path like `/v1/campaigns/{id}/quests`.
pub fn parse_campaign_quest_path<'a>(path: &'a str) -> Option<&'a str> {
    let rest = path.strip_prefix("/v1/campaigns/")?;
    let id = rest.strip_suffix("/quests")?;
    if id.is_empty() {
        return None;
    }
    Some(id)
}

/// Parse a campaign id and quest id from a path like
/// `/v1/campaigns/{id}/quests/{quest_id}/progress`.
pub fn parse_quest_progress_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/campaigns/")?;
    let marker = "/quests/";
    let end = rest.find(marker)?;
    let campaign_id = &rest[..end];
    if campaign_id.is_empty() {
        return None;
    }
    let after = &rest[end + marker.len()..];
    let quest_id = after.strip_suffix("/progress")?;
    if quest_id.is_empty() {
        return None;
    }
    Some((campaign_id, quest_id))
}

/// Create a new quest for a campaign.
///
/// `id`, `title`, and `status` are required non-empty strings. `milestones` is a
/// required array of non-empty strings.
pub fn create_quest(campaign_id: &str, body: &str) -> Result<String, QuestError> {
    if !campaign_exists(campaign_id).map_err(|_| QuestError::BadRequest)? {
        return Err(QuestError::NotFound);
    }
    let id = extract_string(body, "id").ok_or(QuestError::BadRequest)?;
    let title = extract_string(body, "title").ok_or(QuestError::BadRequest)?;
    let status = extract_string(body, "status").ok_or(QuestError::BadRequest)?;
    let milestones = extract_string_array(body, "milestones").ok_or(QuestError::BadRequest)?;
    if id.is_empty() || title.is_empty() || status.is_empty() {
        return Err(QuestError::BadRequest);
    }
    for m in &milestones {
        if m.is_empty() {
            return Err(QuestError::BadRequest);
        }
    }
    if quest_exists(campaign_id, id).map_err(|_| QuestError::BadRequest)? {
        return Err(QuestError::Conflict);
    }

    let mut sql = format!(
        "INSERT INTO quests (campaign_id, id, title, status, position) VALUES ('{}', '{}', '{}', '{}', 0);",
        sql_escape(campaign_id),
        sql_escape(id),
        sql_escape(title),
        sql_escape(status)
    );
    for (pos, m) in milestones.iter().enumerate() {
        sql.push_str(&format!(
            "INSERT INTO quest_milestones (campaign_id, quest_id, title, done, position) VALUES ('{}', '{}', '{}', 0, {});",
            sql_escape(campaign_id),
            sql_escape(id),
            sql_escape(m),
            pos
        ));
    }
    sqlite_exec(&sql).map_err(|_| QuestError::BadRequest)?;

    Ok(format!(
        r#"{{"id":"{}","title":"{}","status":"{}","milestones_total":{},"milestones_done":0}}"#,
        escape_json(id),
        escape_json(title),
        escape_json(status),
        milestones.len()
    ))
}

/// Update quest progress by marking the listed milestones as completed.
///
/// Unknown milestone titles are ignored. The response reflects the current
/// quest status and milestone counts.
pub fn update_quest_progress(
    campaign_id: &str,
    quest_id: &str,
    body: &str,
) -> Result<String, QuestError> {
    if !campaign_exists(campaign_id).map_err(|_| QuestError::BadRequest)? {
        return Err(QuestError::NotFound);
    }
    if !quest_exists(campaign_id, quest_id).map_err(|_| QuestError::BadRequest)? {
        return Err(QuestError::NotFound);
    }
    let completed = extract_string_array(body, "completed").ok_or(QuestError::BadRequest)?;
    for m in &completed {
        if m.is_empty() {
            return Err(QuestError::BadRequest);
        }
    }

    let mut sql = String::new();
    for m in completed {
        sql.push_str(&format!(
            "UPDATE quest_milestones SET done = 1 WHERE campaign_id = '{}' AND quest_id = '{}' AND title = '{}';",
            sql_escape(campaign_id),
            sql_escape(quest_id),
            sql_escape(&m)
        ));
    }
    sqlite_exec(&sql).map_err(|_| QuestError::BadRequest)?;

    let status = read_quest_status(campaign_id, quest_id)?;
    let (total, done) = read_milestone_counts(campaign_id, quest_id)?;

    Ok(format!(
        r#"{{"id":"{}","status":"{}","milestones_total":{},"milestones_done":{}}}"#,
        escape_json(quest_id),
        escape_json(&status),
        total,
        done
    ))
}

/// Summarize a campaign's quests by status.
pub fn quest_summary(campaign_id: &str) -> Result<String, QuestError> {
    if !campaign_exists(campaign_id).map_err(|_| QuestError::BadRequest)? {
        return Err(QuestError::NotFound);
    }
    let sql = format!(
        "SELECT status, COUNT(*) AS cnt FROM quests WHERE campaign_id = '{}' GROUP BY status;",
        sql_escape(campaign_id)
    );
    let output = sqlite_query(&sql).map_err(|_| QuestError::BadRequest)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let mut active = 0;
    let mut completed = 0;
    let mut blocked = 0;
    for obj in extract_objects(content) {
        let status = extract_string(obj, "status").ok_or(QuestError::BadRequest)?;
        let cnt = extract_int(obj, "cnt").unwrap_or(0);
        match status {
            "active" => active = cnt,
            "completed" => completed = cnt,
            "blocked" => blocked = cnt,
            _ => {}
        }
    }
    Ok(format!(
        r#"{{"campaign_id":"{}","active":{},"completed":{},"blocked":{}}}"#,
        escape_json(campaign_id),
        active,
        completed,
        blocked
    ))
}

fn read_quest_status(campaign_id: &str, quest_id: &str) -> Result<String, QuestError> {
    let sql = format!(
        "SELECT status FROM quests WHERE campaign_id = '{}' AND id = '{}';",
        sql_escape(campaign_id),
        sql_escape(quest_id)
    );
    let output = sqlite_query(&sql).map_err(|_| QuestError::BadRequest)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err(QuestError::NotFound);
    }
    extract_string(objects[0], "status")
        .map(|s| s.to_string())
        .ok_or(QuestError::BadRequest)
}

fn read_milestone_counts(campaign_id: &str, quest_id: &str) -> Result<(i64, i64), QuestError> {
    let sql = format!(
        "SELECT COUNT(*) AS total, COALESCE(SUM(done), 0) AS done FROM quest_milestones WHERE campaign_id = '{}' AND quest_id = '{}';",
        sql_escape(campaign_id),
        sql_escape(quest_id)
    );
    let output = sqlite_query(&sql).map_err(|_| QuestError::BadRequest)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Ok((0, 0));
    }
    let total = extract_int(objects[0], "total").unwrap_or(0);
    let done = extract_int(objects[0], "done").unwrap_or(0);
    Ok((total, done))
}
