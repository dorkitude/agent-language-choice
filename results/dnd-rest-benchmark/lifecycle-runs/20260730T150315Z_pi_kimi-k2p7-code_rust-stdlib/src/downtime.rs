use crate::json::{escape_json, extract_int, extract_string, extract_top_array_content};
use crate::store::{campaign_exists, character_exists, project_exists, sql_escape, sqlite_exec, sqlite_query};

pub enum CraftingError {
    BadRequest,
    NotFound,
    Conflict,
}

/// Parse a campaign id from `POST /v1/campaigns/{id}/downtime/crafting`.
pub fn parse_crafting_path<'a>(path: &'a str) -> Option<&'a str> {
    let rest = path.strip_prefix("/v1/campaigns/")?;
    let id = rest.strip_suffix("/downtime/crafting")?;
    if id.is_empty() {
        return None;
    }
    Some(id)
}

/// Parse a campaign id and project id from
/// `POST /v1/campaigns/{id}/downtime/crafting/{project_id}/advance`.
pub fn parse_crafting_advance_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/campaigns/")?;
    let marker = "/downtime/crafting/";
    let end = rest.find(marker)?;
    let campaign_id = &rest[..end];
    if campaign_id.is_empty() {
        return None;
    }
    let after = &rest[end + marker.len()..];
    let project_id = after.strip_suffix("/advance")?;
    if project_id.is_empty() {
        return None;
    }
    Some((campaign_id, project_id))
}

/// Create a downtime crafting project for a character in a campaign.
///
/// The project starts with `days_completed = 0` and `status = "active"`.
/// The `cost_gp` field is stored but not included in the response.
pub fn create_project(campaign_id: &str, body: &str) -> Result<String, CraftingError> {
    if !campaign_exists(campaign_id).map_err(|_| CraftingError::BadRequest)? {
        return Err(CraftingError::NotFound);
    }
    let id = extract_string(body, "id").ok_or(CraftingError::BadRequest)?;
    let character_id = extract_string(body, "character_id").ok_or(CraftingError::BadRequest)?;
    let item_slug = extract_string(body, "item_slug").ok_or(CraftingError::BadRequest)?;
    let days_required = extract_int(body, "days_required").ok_or(CraftingError::BadRequest)?;
    let cost_gp = extract_int(body, "cost_gp").ok_or(CraftingError::BadRequest)?;
    if id.is_empty()
        || character_id.is_empty()
        || item_slug.is_empty()
        || days_required < 1
        || cost_gp < 0
    {
        return Err(CraftingError::BadRequest);
    }
    if !character_exists(campaign_id, character_id).map_err(|_| CraftingError::BadRequest)? {
        return Err(CraftingError::BadRequest);
    }
    if project_exists(campaign_id, id).map_err(|_| CraftingError::BadRequest)? {
        return Err(CraftingError::Conflict);
    }

    let sql = format!(
        "INSERT INTO crafting_projects (campaign_id, id, character_id, item_slug, days_required, days_completed, status, cost_gp) VALUES ('{}', '{}', '{}', '{}', {}, 0, 'active', {});",
        sql_escape(campaign_id),
        sql_escape(id),
        sql_escape(character_id),
        sql_escape(item_slug),
        days_required,
        cost_gp
    );
    sqlite_exec(&sql).map_err(|_| CraftingError::BadRequest)?;

    Ok(format!(
        r#"{{"id":"{}","character_id":"{}","item_slug":"{}","days_required":{},"days_completed":0,"status":"active"}}"#,
        escape_json(id),
        escape_json(character_id),
        escape_json(item_slug),
        days_required
    ))
}

/// Advance a crafting project by a number of days.
///
/// If the project reaches or exceeds `days_required`, it becomes `complete`
/// and one copy of the crafted item is added to the campaign inventory with
/// owner `party`.
pub fn advance_project(
    campaign_id: &str,
    project_id: &str,
    body: &str,
) -> Result<String, CraftingError> {
    if !campaign_exists(campaign_id).map_err(|_| CraftingError::BadRequest)? {
        return Err(CraftingError::NotFound);
    }
    let project = read_project(campaign_id, project_id).ok_or(CraftingError::NotFound)?;
    if project.status == "complete" {
        return Err(CraftingError::BadRequest);
    }
    let days = extract_int(body, "days").ok_or(CraftingError::BadRequest)?;
    if days < 1 {
        return Err(CraftingError::BadRequest);
    }

    let completed = (project.days_completed + days).min(project.days_required);
    let status = if completed >= project.days_required {
        "complete"
    } else {
        "active"
    };

    let mut sql = format!(
        "UPDATE crafting_projects SET days_completed = {}, status = '{}' WHERE campaign_id = '{}' AND id = '{}';",
        completed,
        status,
        sql_escape(campaign_id),
        sql_escape(project_id)
    );
    if status == "complete" {
        sql.push_str(&format!(
            "INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES ('{}', '{}', 'party', 1) ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + excluded.quantity;",
            sql_escape(campaign_id),
            sql_escape(&project.item_slug)
        ));
    }
    sqlite_exec(&sql).map_err(|_| CraftingError::BadRequest)?;

    Ok(format!(
        r#"{{"id":"{}","days_completed":{},"status":"{}"}}"#,
        escape_json(project_id),
        completed,
        status
    ))
}

struct Project {
    item_slug: String,
    days_completed: i64,
    days_required: i64,
    status: String,
}

fn read_project(campaign_id: &str, project_id: &str) -> Option<Project> {
    let sql = format!(
        "SELECT item_slug, days_completed, days_required, status FROM crafting_projects WHERE campaign_id = '{}' AND id = '{}';",
        sql_escape(campaign_id),
        sql_escape(project_id)
    );
    let output = sqlite_query(&sql).ok()?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = crate::json::extract_objects(content);
    if objects.is_empty() {
        return None;
    }
    let obj = objects[0];
    let item_slug = extract_string(obj, "item_slug")?;
    let days_completed = extract_int(obj, "days_completed")?;
    let days_required = extract_int(obj, "days_required")?;
    let status = extract_string(obj, "status")?;
    Some(Project {
        item_slug: item_slug.to_string(),
        days_completed,
        days_required,
        status: status.to_string(),
    })
}
