//! Monster and magic item compendium: in-memory catalogs keyed by slug,
//! with create + get-by-slug endpoints for each. Also exposes read access
//! to the monster catalog for [`crate::dm_tools`]'s encounter builder.

use std::collections::HashMap;
use std::net::TcpStream;
use std::sync::{Mutex, OnceLock};

use crate::http::{bad_request, respond};
use crate::json::{as_int, escape_json_string, parse_json, Json};

pub(crate) struct Monster {
    slug: String,
    name: String,
    pub(crate) cr: String,
    armor_class: i64,
    hit_points: i64,
    tags: Vec<String>,
}

pub(crate) struct Item {
    slug: String,
    name: String,
    item_type: String,
    rarity: String,
    cost_gp: i64,
}

pub(crate) fn monsters() -> &'static Mutex<HashMap<String, Monster>> {
    static MONSTERS: OnceLock<Mutex<HashMap<String, Monster>>> = OnceLock::new();
    MONSTERS.get_or_init(|| Mutex::new(HashMap::new()))
}

pub(crate) fn items() -> &'static Mutex<HashMap<String, Item>> {
    static ITEMS: OnceLock<Mutex<HashMap<String, Item>>> = OnceLock::new();
    ITEMS.get_or_init(|| Mutex::new(HashMap::new()))
}

pub(crate) fn clear() {
    monsters().lock().unwrap().clear();
    items().lock().unwrap().clear();
}

fn is_valid_slug(slug: &str) -> bool {
    !slug.is_empty()
        && slug
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
}

fn tags_json(tags: &[String]) -> String {
    let items: Vec<String> = tags
        .iter()
        .map(|t| format!(r#""{}""#, escape_json_string(t)))
        .collect();
    format!("[{}]", items.join(","))
}

fn monster_json(m: &Monster, include_tags: bool) -> String {
    if include_tags {
        format!(
            r#"{{"slug":"{}","name":"{}","cr":"{}","armor_class":{},"hit_points":{},"tags":{}}}"#,
            escape_json_string(&m.slug),
            escape_json_string(&m.name),
            escape_json_string(&m.cr),
            m.armor_class,
            m.hit_points,
            tags_json(&m.tags)
        )
    } else {
        format!(
            r#"{{"slug":"{}","name":"{}","cr":"{}","armor_class":{},"hit_points":{}}}"#,
            escape_json_string(&m.slug),
            escape_json_string(&m.name),
            escape_json_string(&m.cr),
            m.armor_class,
            m.hit_points
        )
    }
}

fn item_json(it: &Item) -> String {
    format!(
        r#"{{"slug":"{}","name":"{}","type":"{}","rarity":"{}","cost_gp":{}}}"#,
        escape_json_string(&it.slug),
        escape_json_string(&it.name),
        escape_json_string(&it.item_type),
        escape_json_string(&it.rarity),
        it.cost_gp
    )
}

pub(crate) fn handle_create_monster(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let slug = match json.get("slug").and_then(|v| v.as_str()) {
        Some(s) if is_valid_slug(s) => s.to_string(),
        _ => return bad_request(stream, "invalid slug"),
    };
    let name = match json.get("name").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid name"),
    };
    let cr = match json.get("cr").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid cr"),
    };
    let armor_class = match json.get("armor_class").and_then(as_int) {
        Some(v) if v >= 0 => v,
        _ => return bad_request(stream, "invalid armor_class"),
    };
    let hit_points = match json.get("hit_points").and_then(as_int) {
        Some(v) if v >= 0 => v,
        _ => return bad_request(stream, "invalid hit_points"),
    };
    let tags: Vec<String> = match json.get("tags") {
        Some(Json::Array(a)) => {
            let mut out = Vec::new();
            for t in a {
                match t.as_str() {
                    Some(s) => out.push(s.to_string()),
                    None => return bad_request(stream, "invalid tags"),
                }
            }
            out
        }
        None => Vec::new(),
        _ => return bad_request(stream, "invalid tags"),
    };

    let mut store = monsters().lock().unwrap();
    if store.contains_key(&slug) {
        return respond(stream, 409, r#"{"error":"slug already exists"}"#);
    }

    let monster = Monster {
        slug: slug.clone(),
        name,
        cr,
        armor_class,
        hit_points,
        tags,
    };
    let out = monster_json(&monster, false);
    store.insert(slug, monster);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_monster(stream: &mut TcpStream, slug: &str) -> std::io::Result<()> {
    let store = monsters().lock().unwrap();
    match store.get(slug) {
        Some(m) => {
            let out = monster_json(m, true);
            drop(store);
            respond(stream, 200, &out)
        }
        None => respond(stream, 404, r#"{"error":"monster not found"}"#),
    }
}

pub(crate) fn handle_create_item(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let slug = match json.get("slug").and_then(|v| v.as_str()) {
        Some(s) if is_valid_slug(s) => s.to_string(),
        _ => return bad_request(stream, "invalid slug"),
    };
    let name = match json.get("name").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid name"),
    };
    let item_type = match json.get("type").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid type"),
    };
    let rarity = match json.get("rarity").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid rarity"),
    };
    let cost_gp = match json.get("cost_gp").and_then(as_int) {
        Some(v) if v >= 0 => v,
        _ => return bad_request(stream, "invalid cost_gp"),
    };

    let mut store = items().lock().unwrap();
    if store.contains_key(&slug) {
        return respond(stream, 409, r#"{"error":"slug already exists"}"#);
    }

    let item = Item {
        slug: slug.clone(),
        name,
        item_type,
        rarity,
        cost_gp,
    };
    let out = item_json(&item);
    store.insert(slug, item);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_get_item(stream: &mut TcpStream, slug: &str) -> std::io::Result<()> {
    let store = items().lock().unwrap();
    match store.get(slug) {
        Some(it) => {
            let out = item_json(it);
            drop(store);
            respond(stream, 200, &out)
        }
        None => respond(stream, 404, r#"{"error":"item not found"}"#),
    }
}
