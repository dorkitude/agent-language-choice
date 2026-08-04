use crate::json::{
    escape_json, extract_int, extract_objects, extract_string, extract_top_array_content,
};
use crate::store::{campaign_exists, character_exists, sql_escape, sqlite_exec, sqlite_query};

pub enum InventoryError {
    BadRequest,
    NotFound,
}

/// Parse a campaign id from `POST /v1/campaigns/{id}/inventory`.
pub fn parse_campaign_inventory_path<'a>(path: &'a str) -> Option<&'a str> {
    let rest = path.strip_prefix("/v1/campaigns/")?;
    let id = rest.strip_suffix("/inventory")?;
    if id.is_empty() {
        return None;
    }
    Some(id)
}

/// Parse a campaign id from `GET /v1/campaigns/{id}/inventory/summary`.
pub fn parse_inventory_summary_path<'a>(path: &'a str) -> Option<&'a str> {
    let rest = path.strip_prefix("/v1/campaigns/")?;
    let id = rest.strip_suffix("/inventory/summary")?;
    if id.is_empty() {
        return None;
    }
    Some(id)
}

/// Parse a campaign id and character id from
/// `POST /v1/campaigns/{id}/characters/{character_id}/equipment`.
pub fn parse_character_equipment_path<'a>(path: &'a str) -> Option<(&'a str, &'a str)> {
    let rest = path.strip_prefix("/v1/campaigns/")?;
    let marker = "/characters/";
    let end = rest.find(marker)?;
    let campaign_id = &rest[..end];
    if campaign_id.is_empty() {
        return None;
    }
    let after = &rest[end + marker.len()..];
    let character_id = after.strip_suffix("/equipment")?;
    if character_id.is_empty() {
        return None;
    }
    Some((campaign_id, character_id))
}

/// Add an item to the campaign inventory, stacking with any existing entry for
/// the same `(campaign_id, item_slug, owner)` tuple.
pub fn add_item(campaign_id: &str, body: &str) -> Result<String, InventoryError> {
    if !campaign_exists(campaign_id).map_err(|_| InventoryError::BadRequest)? {
        return Err(InventoryError::NotFound);
    }
    let item_slug = extract_string(body, "item_slug").ok_or(InventoryError::BadRequest)?;
    let quantity = extract_int(body, "quantity").ok_or(InventoryError::BadRequest)?;
    let owner = extract_string(body, "owner").ok_or(InventoryError::BadRequest)?;
    if item_slug.is_empty() || owner.is_empty() || quantity < 1 {
        return Err(InventoryError::BadRequest);
    }

    let sql = format!(
        "INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES ('{}', '{}', '{}', {}) ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + excluded.quantity;",
        sql_escape(campaign_id),
        sql_escape(&item_slug),
        sql_escape(owner),
        quantity
    );
    sqlite_exec(&sql).map_err(|_| InventoryError::BadRequest)?;

    let new_qty = read_inventory_quantity(campaign_id, &item_slug, owner)?;
    Ok(format!(
        r#"{{"item_slug":"{}","quantity":{},"owner":"{}"}}"#,
        escape_json(&item_slug),
        new_qty,
        escape_json(owner)
    ))
}

/// Assign equipment from the party inventory to a character.
pub fn assign_equipment(
    campaign_id: &str,
    character_id: &str,
    body: &str,
) -> Result<String, InventoryError> {
    if !campaign_exists(campaign_id).map_err(|_| InventoryError::BadRequest)? {
        return Err(InventoryError::NotFound);
    }
    if !character_exists(campaign_id, character_id).map_err(|_| InventoryError::BadRequest)? {
        return Err(InventoryError::NotFound);
    }
    let item_slug = extract_string(body, "item_slug").ok_or(InventoryError::BadRequest)?;
    let quantity = extract_int(body, "quantity").ok_or(InventoryError::BadRequest)?;
    if item_slug.is_empty() || quantity < 1 {
        return Err(InventoryError::BadRequest);
    }

    let available = available_quantity(campaign_id, &item_slug)?;
    if quantity > available {
        return Err(InventoryError::BadRequest);
    }

    let sql = format!(
        "INSERT INTO character_equipment (campaign_id, character_id, item_slug, quantity) VALUES ('{}', '{}', '{}', {}) ON CONFLICT(campaign_id, character_id, item_slug) DO UPDATE SET quantity = quantity + excluded.quantity; UPDATE campaign_inventory SET quantity = quantity - {} WHERE campaign_id = '{}' AND item_slug = '{}' AND owner = 'party';",
        sql_escape(campaign_id),
        sql_escape(character_id),
        sql_escape(&item_slug),
        quantity,
        quantity,
        sql_escape(campaign_id),
        sql_escape(&item_slug)
    );
    sqlite_exec(&sql).map_err(|_| InventoryError::BadRequest)?;

    let new_qty = read_equipment_quantity(campaign_id, character_id, &item_slug)?;
    Ok(format!(
        r#"{{"character_id":"{}","item_slug":"{}","quantity":{}}}"#,
        escape_json(character_id),
        escape_json(&item_slug),
        new_qty
    ))
}

/// Summarize campaign inventory and equipment assignments.
pub fn inventory_summary(campaign_id: &str) -> Result<String, InventoryError> {
    if !campaign_exists(campaign_id).map_err(|_| InventoryError::BadRequest)? {
        return Err(InventoryError::NotFound);
    }
    let party_items = count_party_items(campaign_id)?;
    let assigned_items = count_assigned_items(campaign_id)?;
    let available_fields = build_available_fields(campaign_id)?;
    Ok(format!(
        r#"{{"campaign_id":"{}","party_items":{},"assigned_items":{}{}}}"#,
        escape_json(campaign_id),
        party_items,
        assigned_items,
        available_fields
    ))
}

fn read_inventory_quantity(
    campaign_id: &str,
    item_slug: &str,
    owner: &str,
) -> Result<i64, InventoryError> {
    let sql = format!(
        "SELECT quantity FROM campaign_inventory WHERE campaign_id = '{}' AND item_slug = '{}' AND owner = '{}';",
        sql_escape(campaign_id),
        sql_escape(item_slug),
        sql_escape(owner)
    );
    let output = sqlite_query(&sql).map_err(|_| InventoryError::BadRequest)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err(InventoryError::BadRequest);
    }
    extract_int(objects[0], "quantity").ok_or(InventoryError::BadRequest)
}

fn read_equipment_quantity(
    campaign_id: &str,
    character_id: &str,
    item_slug: &str,
) -> Result<i64, InventoryError> {
    let sql = format!(
        "SELECT quantity FROM character_equipment WHERE campaign_id = '{}' AND character_id = '{}' AND item_slug = '{}';",
        sql_escape(campaign_id),
        sql_escape(character_id),
        sql_escape(item_slug)
    );
    let output = sqlite_query(&sql).map_err(|_| InventoryError::BadRequest)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err(InventoryError::BadRequest);
    }
    extract_int(objects[0], "quantity").ok_or(InventoryError::BadRequest)
}

fn available_quantity(campaign_id: &str, item_slug: &str) -> Result<i64, InventoryError> {
    let party = party_quantity(campaign_id, item_slug)?;
    let assigned = assigned_quantity(campaign_id, item_slug)?;
    Ok(party - assigned)
}

fn party_quantity(campaign_id: &str, item_slug: &str) -> Result<i64, InventoryError> {
    query_quantity(
        "campaign_inventory",
        &format!(
            "campaign_id = '{}' AND item_slug = '{}' AND owner = 'party'",
            sql_escape(campaign_id),
            sql_escape(item_slug)
        ),
    )
}

fn assigned_quantity(campaign_id: &str, item_slug: &str) -> Result<i64, InventoryError> {
    query_quantity(
        "character_equipment",
        &format!(
            "campaign_id = '{}' AND item_slug = '{}'",
            sql_escape(campaign_id),
            sql_escape(item_slug)
        ),
    )
}

fn query_quantity(table: &str, predicate: &str) -> Result<i64, InventoryError> {
    let sql = format!(
        "SELECT COALESCE(SUM(quantity), 0) AS qty FROM {} WHERE {};",
        table, predicate
    );
    let output = sqlite_query(&sql).map_err(|_| InventoryError::BadRequest)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Ok(0);
    }
    extract_int(objects[0], "qty").ok_or(InventoryError::BadRequest)
}

fn count_party_items(campaign_id: &str) -> Result<i64, InventoryError> {
    count_rows(campaign_id, "campaign_inventory", "owner = 'party'")
}

fn count_assigned_items(campaign_id: &str) -> Result<i64, InventoryError> {
    count_rows(campaign_id, "character_equipment", "1=1")
}

fn count_rows(campaign_id: &str, table: &str, predicate: &str) -> Result<i64, InventoryError> {
    let sql = format!(
        "SELECT COUNT(*) AS cnt FROM {} WHERE campaign_id = '{}' AND {};",
        table,
        sql_escape(campaign_id),
        predicate
    );
    let output = sqlite_query(&sql).map_err(|_| InventoryError::BadRequest)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Ok(0);
    }
    extract_int(objects[0], "cnt").ok_or(InventoryError::BadRequest)
}

fn build_available_fields(campaign_id: &str) -> Result<String, InventoryError> {
    let sql = format!(
        "SELECT item_slug, quantity FROM campaign_inventory WHERE campaign_id = '{}' AND owner = 'party' ORDER BY item_slug;",
        sql_escape(campaign_id)
    );
    let output = sqlite_query(&sql).map_err(|_| InventoryError::BadRequest)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let mut fields = Vec::new();
    for obj in extract_objects(content) {
        let slug = extract_string(obj, "item_slug").ok_or(InventoryError::BadRequest)?;
        let available = extract_int(obj, "quantity").unwrap_or(0);
        let key = available_field_name(slug);
        fields.push(format!(r#""{}":{}"#, key, available));
    }
    if fields.is_empty() {
        Ok(String::new())
    } else {
        Ok(format!(",{}", fields.join(",")))
    }
}

fn available_field_name(slug: &str) -> String {
    let parts: Vec<&str> = slug.split('-').collect();
    let mut owned: Vec<String> = parts.into_iter().map(|s| s.to_string()).collect();
    if let Some(last) = owned.last_mut() {
        if !last.is_empty() && !last.ends_with('s') {
            last.push('s');
        }
    }
    format!("{}_available", owned.join("_"))
}
