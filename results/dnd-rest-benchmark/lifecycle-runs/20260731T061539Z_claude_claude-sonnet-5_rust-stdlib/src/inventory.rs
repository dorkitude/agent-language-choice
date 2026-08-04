//! Campaign inventory and per-character equipment assignment. Backing store
//! is two in-memory maps keyed by campaign id: a flat list of inventory
//! entries (item/quantity/owner, usually owner `"party"`) and a flat list of
//! equipment assignments (item/quantity handed to a specific character).
//! Both are validated against [`crate::campaigns`] the same way
//! [`crate::quests`] validates `campaign_id`.

use std::collections::HashMap;
use std::net::TcpStream;
use std::sync::{Mutex, OnceLock};

use crate::campaigns;
use crate::http::{bad_request, respond};
use crate::json::{as_int, escape_json_string, parse_json};

const HEALING_POTION_SLUG: &str = "healing-potion";
const PARTY_OWNER: &str = "party";

pub(crate) struct InventoryItem {
    item_slug: String,
    quantity: i64,
    owner: String,
}

pub(crate) struct EquipmentAssignment {
    #[allow(dead_code)]
    character_id: String,
    item_slug: String,
    quantity: i64,
}

fn inventory() -> &'static Mutex<HashMap<String, Vec<InventoryItem>>> {
    static INVENTORY: OnceLock<Mutex<HashMap<String, Vec<InventoryItem>>>> = OnceLock::new();
    INVENTORY.get_or_init(|| Mutex::new(HashMap::new()))
}

fn equipment() -> &'static Mutex<HashMap<String, Vec<EquipmentAssignment>>> {
    static EQUIPMENT: OnceLock<Mutex<HashMap<String, Vec<EquipmentAssignment>>>> = OnceLock::new();
    EQUIPMENT.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Healing potions deposited outside the explicit add-inventory endpoint
/// (e.g. finished downtime crafting projects). Tracked separately so those
/// deposits raise `healing_potions_available` without inflating the
/// inventory item count used by the audit/export/analytics endpoints.
fn healing_potion_bonus() -> &'static Mutex<HashMap<String, i64>> {
    static BONUS: OnceLock<Mutex<HashMap<String, i64>>> = OnceLock::new();
    BONUS.get_or_init(|| Mutex::new(HashMap::new()))
}

pub(crate) fn clear() {
    inventory().lock().unwrap().clear();
    equipment().lock().unwrap().clear();
    healing_potion_bonus().lock().unwrap().clear();
}

pub(crate) fn inventory_item_count(campaign_id: &str) -> i64 {
    let store = inventory().lock().unwrap();
    store.get(campaign_id).map(|items| items.len() as i64).unwrap_or(0)
}

fn inventory_json(item: &InventoryItem) -> String {
    format!(
        r#"{{"item_slug":"{}","quantity":{},"owner":"{}"}}"#,
        escape_json_string(&item.item_slug),
        item.quantity,
        escape_json_string(&item.owner)
    )
}

fn equipment_json(character_id: &str, assignment: &EquipmentAssignment) -> String {
    format!(
        r#"{{"character_id":"{}","item_slug":"{}","quantity":{}}}"#,
        escape_json_string(character_id),
        escape_json_string(&assignment.item_slug),
        assignment.quantity
    )
}

/// Credits a completed downtime crafting project's healing potion to a
/// campaign's available pool without adding a counted inventory entry.
pub(crate) fn add_healing_potion_bonus(campaign_id: &str, quantity: i64) {
    let mut bonus = healing_potion_bonus().lock().unwrap();
    *bonus.entry(campaign_id.to_string()).or_insert(0) += quantity;
}

pub(crate) fn handle_add_inventory(
    stream: &mut TcpStream,
    campaign_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let item_slug = match json.get("item_slug").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid item_slug"),
    };
    let quantity = match json.get("quantity").and_then(as_int) {
        Some(q) if q >= 1 => q,
        _ => return bad_request(stream, "invalid quantity"),
    };
    let owner = match json.get("owner").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid owner"),
    };

    if !campaigns::campaign_exists(campaign_id) {
        return respond(stream, 404, r#"{"error":"campaign not found"}"#);
    }

    let item = InventoryItem {
        item_slug,
        quantity,
        owner,
    };
    let out = inventory_json(&item);

    let mut store = inventory().lock().unwrap();
    store.entry(campaign_id.to_string()).or_insert_with(Vec::new).push(item);
    drop(store);

    respond(stream, 201, &out)
}

pub(crate) fn handle_assign_equipment(
    stream: &mut TcpStream,
    campaign_id: &str,
    character_id: &str,
    body: &str,
) -> std::io::Result<()> {
    let json = match parse_json(body) {
        Some(j) => j,
        None => return bad_request(stream, "invalid json"),
    };

    let item_slug = match json.get("item_slug").and_then(|v| v.as_str()) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => return bad_request(stream, "invalid item_slug"),
    };
    let quantity = match json.get("quantity").and_then(as_int) {
        Some(q) if q >= 1 => q,
        _ => return bad_request(stream, "invalid quantity"),
    };

    match campaigns::character_exists(campaign_id, character_id) {
        None => return respond(stream, 404, r#"{"error":"campaign not found"}"#),
        Some(false) => return respond(stream, 404, r#"{"error":"character not found"}"#),
        Some(true) => {}
    }

    let assignment = EquipmentAssignment {
        character_id: character_id.to_string(),
        item_slug,
        quantity,
    };
    let out = equipment_json(character_id, &assignment);

    let mut store = equipment().lock().unwrap();
    store.entry(campaign_id.to_string()).or_insert_with(Vec::new).push(assignment);
    drop(store);

    respond(stream, 200, &out)
}

pub(crate) fn handle_inventory_summary(stream: &mut TcpStream, campaign_id: &str) -> std::io::Result<()> {
    if !campaigns::campaign_exists(campaign_id) {
        return respond(stream, 404, r#"{"error":"campaign not found"}"#);
    }

    let inv_store = inventory().lock().unwrap();
    let campaign_items = inv_store.get(campaign_id);

    let party_items = campaign_items
        .map(|items| items.iter().filter(|i| i.owner == PARTY_OWNER).count() as i64)
        .unwrap_or(0);
    let party_healing_potions: i64 = campaign_items
        .map(|items| {
            items
                .iter()
                .filter(|i| i.owner == PARTY_OWNER && i.item_slug == HEALING_POTION_SLUG)
                .map(|i| i.quantity)
                .sum()
        })
        .unwrap_or(0);
    drop(inv_store);

    let bonus = *healing_potion_bonus()
        .lock()
        .unwrap()
        .get(campaign_id)
        .unwrap_or(&0);
    let party_healing_potions = party_healing_potions + bonus;

    let eq_store = equipment().lock().unwrap();
    let campaign_assignments = eq_store.get(campaign_id);

    let assigned_items = campaign_assignments.map(|a| a.len() as i64).unwrap_or(0);
    let assigned_healing_potions: i64 = campaign_assignments
        .map(|a| {
            a.iter()
                .filter(|assignment| assignment.item_slug == HEALING_POTION_SLUG)
                .map(|assignment| assignment.quantity)
                .sum()
        })
        .unwrap_or(0);
    drop(eq_store);

    let healing_potions_available = party_healing_potions - assigned_healing_potions;

    let out = format!(
        r#"{{"campaign_id":"{}","party_items":{},"assigned_items":{},"healing_potions_available":{}}}"#,
        escape_json_string(campaign_id),
        party_items,
        assigned_items,
        healing_potions_available
    );

    respond(stream, 200, &out)
}
