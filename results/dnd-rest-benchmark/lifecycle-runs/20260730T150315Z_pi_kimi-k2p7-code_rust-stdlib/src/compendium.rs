use crate::json::{escape_json, extract_int, extract_objects, extract_string, extract_string_array, extract_top_array_content};
use crate::store::{compendium_slug_exists, sqlite_exec, sqlite_query, sql_escape};

pub enum CompendiumError {
    BadRequest,
    NotFound,
    Conflict,
}

/// Create a new monster entry in the compendium.
///
/// Required fields: `slug`, `name`, `cr`, `armor_class`, `hit_points`, `tags`.
/// The slug must be unique and non-empty.
pub fn handle_create_monster(body: &str) -> Result<String, CompendiumError> {
    let slug = extract_string(body, "slug").ok_or(CompendiumError::BadRequest)?;
    if slug.is_empty() {
        return Err(CompendiumError::BadRequest);
    }
    let name = extract_string(body, "name").ok_or(CompendiumError::BadRequest)?;
    let cr = extract_string(body, "cr").ok_or(CompendiumError::BadRequest)?;
    let armor_class = extract_int(body, "armor_class").ok_or(CompendiumError::BadRequest)?;
    let hit_points = extract_int(body, "hit_points").ok_or(CompendiumError::BadRequest)?;
    let tags = extract_string_array(body, "tags").ok_or(CompendiumError::BadRequest)?;

    if compendium_slug_exists("monsters", slug).map_err(|_| CompendiumError::BadRequest)? {
        return Err(CompendiumError::Conflict);
    }

    let sql = format!(
        "INSERT INTO monsters (slug, name, cr, armor_class, hit_points) VALUES ('{}', '{}', '{}', {}, {});",
        sql_escape(slug),
        sql_escape(name),
        sql_escape(cr),
        armor_class,
        hit_points
    );
    sqlite_exec(&sql).map_err(|_| CompendiumError::BadRequest)?;

    for (position, tag) in tags.iter().enumerate() {
        let tag_sql = format!(
            "INSERT INTO monster_tags (monster_slug, tag, position) VALUES ('{}', '{}', {});",
            sql_escape(slug),
            sql_escape(tag),
            position
        );
        sqlite_exec(&tag_sql).map_err(|_| CompendiumError::BadRequest)?;
    }

    Ok(format!(
        r#"{{"slug":"{}","name":"{}","cr":"{}","armor_class":{},"hit_points":{}}}"#,
        escape_json(slug),
        escape_json(name),
        escape_json(cr),
        armor_class,
        hit_points
    ))
}

/// Read a monster entry including its ordered tags.
pub fn handle_read_monster(slug: &str) -> Result<String, CompendiumError> {
    if slug.is_empty() {
        return Err(CompendiumError::BadRequest);
    }
    let sql = format!(
        "SELECT slug, name, cr, armor_class, hit_points FROM monsters WHERE slug = '{}';",
        sql_escape(slug)
    );
    let output = sqlite_query(&sql).map_err(|_| CompendiumError::BadRequest)?;
    let content = extract_top_array_content(&output).ok_or(CompendiumError::NotFound)?;
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err(CompendiumError::NotFound);
    }
    let obj = objects[0];
    let slug = extract_string(obj, "slug").ok_or(CompendiumError::BadRequest)?;
    let name = extract_string(obj, "name").ok_or(CompendiumError::BadRequest)?;
    let cr = extract_string(obj, "cr").ok_or(CompendiumError::BadRequest)?;
    let armor_class = extract_int(obj, "armor_class").ok_or(CompendiumError::BadRequest)?;
    let hit_points = extract_int(obj, "hit_points").ok_or(CompendiumError::BadRequest)?;

    let tags_sql = format!(
        "SELECT tag FROM monster_tags WHERE monster_slug = '{}' ORDER BY position;",
        sql_escape(slug)
    );
    let tags_output = sqlite_query(&tags_sql).map_err(|_| CompendiumError::BadRequest)?;
    let tags_content = extract_top_array_content(&tags_output).unwrap_or("");
    let tags: Vec<String> = extract_objects(tags_content)
        .iter()
        .filter_map(|o| extract_string(o, "tag").map(|s| s.to_string()))
        .collect();

    let tags_json = tags
        .iter()
        .map(|t| format!(r#""{}""#, escape_json(t)))
        .collect::<Vec<_>>()
        .join(",");

    Ok(format!(
        r#"{{"slug":"{}","name":"{}","cr":"{}","armor_class":{},"hit_points":{},"tags":[{}]}}"#,
        escape_json(slug),
        escape_json(name),
        escape_json(cr),
        armor_class,
        hit_points,
        tags_json
    ))
}

/// Create a new item entry in the compendium.
///
/// Required fields: `slug`, `name`, `type`, `rarity`, `cost_gp`. The slug must
/// be unique and non-empty.
pub fn handle_create_item(body: &str) -> Result<String, CompendiumError> {
    let slug = extract_string(body, "slug").ok_or(CompendiumError::BadRequest)?;
    if slug.is_empty() {
        return Err(CompendiumError::BadRequest);
    }
    let name = extract_string(body, "name").ok_or(CompendiumError::BadRequest)?;
    let item_type = extract_string(body, "type").ok_or(CompendiumError::BadRequest)?;
    let rarity = extract_string(body, "rarity").ok_or(CompendiumError::BadRequest)?;
    let cost_gp = extract_int(body, "cost_gp").ok_or(CompendiumError::BadRequest)?;

    if compendium_slug_exists("items", slug).map_err(|_| CompendiumError::BadRequest)? {
        return Err(CompendiumError::Conflict);
    }

    let sql = format!(
        "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES ('{}', '{}', '{}', '{}', {});",
        sql_escape(slug),
        sql_escape(name),
        sql_escape(item_type),
        sql_escape(rarity),
        cost_gp
    );
    sqlite_exec(&sql).map_err(|_| CompendiumError::BadRequest)?;

    Ok(format!(
        r#"{{"slug":"{}","name":"{}","type":"{}","rarity":"{}","cost_gp":{}}}"#,
        escape_json(slug),
        escape_json(name),
        escape_json(item_type),
        escape_json(rarity),
        cost_gp
    ))
}

/// Read a single item entry by slug.
pub fn handle_read_item(slug: &str) -> Result<String, CompendiumError> {
    if slug.is_empty() {
        return Err(CompendiumError::BadRequest);
    }
    let sql = format!(
        "SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = '{}';",
        sql_escape(slug)
    );
    let output = sqlite_query(&sql).map_err(|_| CompendiumError::BadRequest)?;
    let content = extract_top_array_content(&output).ok_or(CompendiumError::NotFound)?;
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err(CompendiumError::NotFound);
    }
    let obj = objects[0];
    let slug = extract_string(obj, "slug").ok_or(CompendiumError::BadRequest)?;
    let name = extract_string(obj, "name").ok_or(CompendiumError::BadRequest)?;
    let item_type = extract_string(obj, "type").ok_or(CompendiumError::BadRequest)?;
    let rarity = extract_string(obj, "rarity").ok_or(CompendiumError::BadRequest)?;
    let cost_gp = extract_int(obj, "cost_gp").ok_or(CompendiumError::BadRequest)?;

    Ok(format!(
        r#"{{"slug":"{}","name":"{}","type":"{}","rarity":"{}","cost_gp":{}}}"#,
        escape_json(slug),
        escape_json(name),
        escape_json(item_type),
        escape_json(rarity),
        cost_gp
    ))
}

/// Look up the challenge rating of a monster by slug.
pub fn get_monster_cr(slug: &str) -> Result<String, String> {
    let sql = format!("SELECT cr FROM monsters WHERE slug = '{}';", sql_escape(slug));
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).ok_or_else(|| "not found".to_string())?;
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err("not found".to_string());
    }
    let cr = extract_string(objects[0], "cr").ok_or_else(|| "missing cr".to_string())?;
    Ok(cr.to_string())
}
