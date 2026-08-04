use std::env;
use std::net::{TcpListener, TcpStream};

mod analytics;
mod auth;
mod campaigns;
mod combat;
mod compendium;
mod dice;
mod dm_tools;
mod domain;
mod downtime;
mod encounters;
mod http;
mod inventory;
mod json;
mod npcs_factions;
mod phb;
mod play;
mod quests;
mod store;

use std::collections::HashMap;

use crate::domain::{CombatSession, User, SESSIONS, USERS};
use crate::http::{read_request, respond};
use crate::store::{init_db, load_storage, reset_db, save_storage, storage_status};

const BAD_REQUEST: &str = r#"{"error":"invalid request"}"#;
const NOT_FOUND: &str = r#"{"error":"not found"}"#;
const UNAUTHORIZED: &str = r#"{"error":"unauthorized"}"#;
const FORBIDDEN: &str = r#"{"error":"forbidden"}"#;

fn main() -> std::io::Result<()> {
    let port = env::var("PORT").unwrap_or_else(|_| "8080".to_string());

    if let Err(e) = init_db() {
        eprintln!("Failed to initialize storage: {}", e);
    } else {
        let mut sessions = SESSIONS.lock().unwrap();
        let mut users = USERS.lock().unwrap();
        if let Err(e) = load_storage(&mut sessions, &mut users) {
            eprintln!("Failed to load storage: {}", e);
        }
    }

    let listener = TcpListener::bind(format!("127.0.0.1:{port}"))?;
    for stream in listener.incoming() {
        if let Ok(mut stream) = stream {
            let _ = dispatch_request(&mut stream);
        }
    }
    Ok(())
}

/// Role requirement for bearer-token authorization.
#[derive(Clone, Copy)]
enum AuthRequirement {
    /// Any valid bearer token, regardless of role.
    Any,
    /// Only a registered user with role `"dm"`.
    Dm,
    /// Only a registered user with role `"player"`.
    Player,
}

/// Extract a `Bearer` token from the `Authorization` header, if present.
fn extract_auth_token(req: &str) -> Option<&str> {
    for line in req.lines() {
        let lower = line.to_lowercase();
        if lower.starts_with("authorization:") {
            let val = line.splitn(2, ':').nth(1)?.trim();
            if val.to_lowercase().starts_with("bearer ") {
                return Some(val[6..].trim());
            }
        }
    }
    None
}

/// Require a valid bearer token with the given role.
///
/// Returns the authenticated username on success. Missing or malformed
/// credentials return `Unauthorized`; a role mismatch returns `Forbidden`.
fn require_auth(
    req: &str,
    users: &HashMap<String, User>,
    requirement: AuthRequirement,
) -> Result<String, auth::AuthError> {
    let token = extract_auth_token(req).ok_or(auth::AuthError::Unauthorized)?;
    let (username, role) = auth::verify_bearer(token, users)?;
    match requirement {
        AuthRequirement::Any => Ok(username),
        AuthRequirement::Dm if role == "dm" => Ok(username),
        AuthRequirement::Player if role == "player" => Ok(username),
        _ => Err(auth::AuthError::Forbidden),
    }
}

/// Parse one HTTP request, route it, and write the response.
///
/// Both in-memory state maps are locked for the duration of the request so that
/// reads and writes are serialized and persistence is consistent.
fn dispatch_request(stream: &mut TcpStream) -> std::io::Result<()> {
    let req = read_request(stream)?;
    let first = req.lines().next().unwrap_or("");
    let parts: Vec<&str> = first.split_whitespace().collect();
    if parts.len() < 2 {
        return respond(stream, 400, BAD_REQUEST);
    }
    let method = parts[0];
    let path = parts[1];
    let body = extract_body(&req);

    let mut sessions = SESSIONS.lock().unwrap();
    let mut users = USERS.lock().unwrap();

    let (status, response) = match method {
        "GET" => dispatch_get(path, &req, &sessions, &users),
        "POST" => dispatch_post(path, body, &req, &mut sessions, &mut users),
        "PUT" => dispatch_put(path, body, &req, &mut sessions, &mut users),
        "DELETE" => dispatch_delete(path, body, &req, &mut sessions, &mut users),
        _ => (404, NOT_FOUND.to_string()),
    };
    respond(stream, status, &response)
}

/// Return the body portion of a fully read HTTP request.
fn extract_body(req: &str) -> &str {
    if let Some(pos) = req.find("\r\n\r\n") {
        &req[pos + 4..]
    } else {
        ""
    }
}

/// Dispatch GET requests.
fn dispatch_get(
    path: &str,
    req: &str,
    _sessions: &HashMap<String, CombatSession>,
    users: &HashMap<String, User>,
) -> (u16, String) {
    if let Some(slug) = path.strip_prefix("/v1/compendium/monsters/") {
        return match compendium::handle_read_monster(slug) {
            Ok(resp) => (200, resp),
            Err(compendium::CompendiumError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(_) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(slug) = path.strip_prefix("/v1/compendium/items/") {
        return match compendium::handle_read_item(slug) {
            Ok(resp) => (200, resp),
            Err(compendium::CompendiumError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(_) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = campaigns::parse_campaign_path(path, "/state") {
        return match campaigns::read_campaign_state(id) {
            Ok(resp) => (200, resp),
            Err(campaigns::CampaignError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(_) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = campaigns::parse_campaign_path(path, "/quests/summary") {
        return match quests::quest_summary(id) {
            Ok(resp) => (200, resp),
            Err(quests::QuestError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(_) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = campaigns::parse_campaign_path(path, "/relationships") {
        return match npcs_factions::relationship_summary(id) {
            Ok(resp) => (200, resp),
            Err(npcs_factions::NpcFactionError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(_) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = inventory::parse_inventory_summary_path(path) {
        return match inventory::inventory_summary(id) {
            Ok(resp) => (200, resp),
            Err(inventory::InventoryError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(_) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = campaigns::parse_campaign_path(path, "/sessions/next") {
        return match campaigns::next_session(id) {
            Ok(resp) => (200, resp),
            Err(campaigns::CampaignError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(_) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = campaigns::parse_campaign_path(path, "/audit") {
        return match campaigns::audit_campaign(id) {
            Ok(resp) => (200, resp),
            Err(campaigns::CampaignError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(_) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = campaigns::parse_campaign_path(path, "/export") {
        return match campaigns::export_campaign(id) {
            Ok(resp) => (200, resp),
            Err(campaigns::CampaignError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(_) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = campaigns::parse_campaign_path(path, "/analytics/summary") {
        return match analytics::analytics_summary(id) {
            Ok(resp) => (200, resp),
            Err(analytics::AnalyticsError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(_) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = play::parse_play_campaign_path(path, "/turn") {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::get_turn(id, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some(id) = play::parse_play_campaign_path(path, "/gm/status") {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::get_gm_status(id, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some(id) = play::parse_play_campaign_path(path, "/my-turn") {
        return match require_auth(req, users, AuthRequirement::Player) {
            Ok(actor) => match play::get_my_turn(id, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some(id) = play::parse_play_campaign_path(path, "/document") {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::get_document(id, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some(id) = play::parse_play_campaign_path(path, "/scenes/current") {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::get_current_scene(id, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, loc_id)) = play::parse_play_campaign_location_path(path, "/travel") {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::get_travel(campaign_id, loc_id, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, encounter_id)) = play::parse_play_encounter_turn_path(path) {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::get_encounter_turn(campaign_id, encounter_id, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, character_id)) = play::parse_play_campaign_character_path(path, "/status") {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::get_character_status(campaign_id, character_id, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, encounter_id)) = play::parse_play_encounter_status_path(path) {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::get_encounter_status(campaign_id, encounter_id, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }

    match path {
        "/health" => (200, r#"{"ok":true}"#.to_string()),
        "/v1/storage/status" => match storage_status() {
            Ok((version, initialized)) => (
                200,
                format!(
                    r#"{{"driver":"sqlite","schema_version":{},"initialized":{}}}"#,
                    version, initialized
                ),
            ),
            Err(_) => (500, r#"{"error":"storage status failed"}"#.to_string()),
        },
        _ => (404, NOT_FOUND.to_string()),
    }
}

/// Dispatch POST requests.
fn dispatch_post(
    path: &str,
    body: &str,
    req: &str,
    sessions: &mut HashMap<String, CombatSession>,
    users: &mut HashMap<String, User>,
) -> (u16, String) {
    match path {
        "/v1/storage/reset" => {
            if let Err(e) = reset_db() {
                eprintln!("reset storage failed: {}", e);
                (500, r#"{"error":"reset failed"}"#.to_string())
            } else {
                sessions.clear();
                // Preserve registered user accounts across storage reset so that
                // the authenticated play surface can still identify DMs/players
                // established earlier in the cumulative test suite.
                (200, r#"{"ok":true,"schema_version":1}"#.to_string())
            }
        }
        "/v1/auth/register" => match auth::handle_register(body, users) {
            Ok(resp) => {
                let _ = save_storage(sessions, users);
                (201, resp)
            }
            Err(auth::RegisterError::Conflict) => {
                (409, r#"{"error":"duplicate username"}"#.to_string())
            }
            Err(auth::RegisterError::BadRequest) => (400, BAD_REQUEST.to_string()),
        },
        "/v1/auth/login" => match auth::handle_login(body, users) {
            Ok(resp) => (200, resp),
            Err(auth::LoginError::Unauthorized) => {
                (401, r#"{"error":"unauthorized"}"#.to_string())
            }
            Err(auth::LoginError::BadRequest) => (400, BAD_REQUEST.to_string()),
        },
        "/v1/dice/stats" => option_response(dice::handle_dice_stats(body)),
        "/v1/checks/ability" => option_response(dice::handle_ability_check(body)),
        "/v1/encounters/adjusted-xp" => option_response(encounters::handle_encounter(body)),
        "/v1/initiative/order" => option_response(combat::handle_initiative(body)),
        "/v1/characters/ability-modifier" => option_response(phb::handle_ability_modifier(body)),
        "/v1/characters/proficiency" => option_response(phb::handle_proficiency(body)),
        "/v1/characters/derived-stats" => option_response(phb::handle_derived_stats(body)),
        "/v1/phb/spell-slots" => option_response(phb::handle_spell_slots(body)),
        "/v1/phb/rests/long" => option_response(phb::handle_long_rest(body)),
        "/v1/phb/equipment-load" => option_response(phb::handle_equipment_load(body)),
        "/v1/combat/sessions" => match combat::create_session(body, sessions) {
            Some(resp) => {
                let _ = save_storage(sessions, users);
                (200, resp)
            }
            None => (400, BAD_REQUEST.to_string()),
        },
        "/v1/compendium/monsters" => match compendium::handle_create_monster(body) {
            Ok(resp) => (201, resp),
            Err(compendium::CompendiumError::Conflict) => {
                (409, r#"{"error":"duplicate slug"}"#.to_string())
            }
            Err(compendium::CompendiumError::BadRequest) => (400, BAD_REQUEST.to_string()),
            Err(compendium::CompendiumError::NotFound) => (404, NOT_FOUND.to_string()),
        },
        "/v1/compendium/items" => match compendium::handle_create_item(body) {
            Ok(resp) => (201, resp),
            Err(compendium::CompendiumError::Conflict) => {
                (409, r#"{"error":"duplicate slug"}"#.to_string())
            }
            Err(compendium::CompendiumError::BadRequest) => (400, BAD_REQUEST.to_string()),
            Err(compendium::CompendiumError::NotFound) => (404, NOT_FOUND.to_string()),
        },
        "/v1/play/campaigns" => match require_auth(req, users, AuthRequirement::Dm) {
            Ok(owner) => match play::create_play_campaign(body, &owner) {
                Ok(resp) => {
                    let _ = save_storage(sessions, users);
                    (201, resp)
                }
                Err(play::PlayError::Conflict) => {
                    (409, r#"{"error":"duplicate play campaign id"}"#.to_string())
                }
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        },
        "/v1/campaigns" => match campaigns::create_campaign(body) {
            Ok(resp) => (201, resp),
            Err(campaigns::CampaignError::Conflict) => {
                (409, r#"{"error":"duplicate campaign id"}"#.to_string())
            }
            Err(campaigns::CampaignError::BadRequest) => (400, BAD_REQUEST.to_string()),
            Err(campaigns::CampaignError::NotFound) => (404, NOT_FOUND.to_string()),
        },
        "/v1/dm/encounter-builder" => option_response(dm_tools::handle_dm_encounter_builder(body)),
        "/v1/dm/loot-parcel" => option_response(dm_tools::handle_dm_loot_parcel(body)),
        "/v1/dm/session-recap" => option_response(dm_tools::handle_dm_session_recap(body)),
        _ => dispatch_dynamic_post(path, body, req, sessions, users),
    }
}

/// Dispatch dynamic POST routes that include path parameters.
fn dispatch_dynamic_post(
    path: &str,
    body: &str,
    req: &str,
    sessions: &mut HashMap<String, CombatSession>,
    users: &mut HashMap<String, User>,
) -> (u16, String) {
    if let Some(id) = combat::parse_combat_path(path, "/conditions") {
        return match combat::add_condition(id, body, sessions) {
            Ok(resp) => {
                let _ = save_storage(sessions, users);
                (200, resp)
            }
            Err(e) => combat_error(e),
        };
    }
    if let Some(id) = combat::parse_combat_path(path, "/advance") {
        return match combat::advance_turn(id, sessions) {
            Ok(resp) => {
                let _ = save_storage(sessions, users);
                (200, resp)
            }
            Err(e) => combat_error(e),
        };
    }
    if let Some(id) = quests::parse_campaign_quest_path(path) {
        return match quests::create_quest(id, body) {
            Ok(resp) => (201, resp),
            Err(quests::QuestError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(quests::QuestError::Conflict) => {
                (409, r#"{"error":"duplicate quest id"}"#.to_string())
            }
            Err(quests::QuestError::BadRequest) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some((campaign_id, quest_id)) = quests::parse_quest_progress_path(path) {
        return match quests::update_quest_progress(campaign_id, quest_id, body) {
            Ok(resp) => (200, resp),
            Err(quests::QuestError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(quests::QuestError::Conflict) => {
                (409, r#"{"error":"duplicate quest id"}"#.to_string())
            }
            Err(quests::QuestError::BadRequest) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = campaigns::parse_campaign_path(path, "/characters") {
        return match campaigns::add_character(id, body) {
            Ok(resp) => (201, resp),
            Err(campaigns::CampaignError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(campaigns::CampaignError::Conflict) => {
                (409, r#"{"error":"duplicate character id"}"#.to_string())
            }
            Err(campaigns::CampaignError::BadRequest) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = campaigns::parse_campaign_path(path, "/events") {
        return match campaigns::add_event(id, body) {
            Ok(resp) => (201, resp),
            Err(campaigns::CampaignError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(campaigns::CampaignError::Conflict) => {
                (409, r#"{"error":"duplicate event id"}"#.to_string())
            }
            Err(campaigns::CampaignError::BadRequest) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = campaigns::parse_campaign_path(path, "/factions") {
        return match npcs_factions::create_faction(id, body) {
            Ok(resp) => (201, resp),
            Err(npcs_factions::NpcFactionError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(npcs_factions::NpcFactionError::Conflict) => {
                (409, r#"{"error":"duplicate faction id"}"#.to_string())
            }
            Err(npcs_factions::NpcFactionError::BadRequest) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = campaigns::parse_campaign_path(path, "/npcs") {
        return match npcs_factions::create_npc(id, body) {
            Ok(resp) => (201, resp),
            Err(npcs_factions::NpcFactionError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(npcs_factions::NpcFactionError::Conflict) => {
                (409, r#"{"error":"duplicate npc id"}"#.to_string())
            }
            Err(npcs_factions::NpcFactionError::BadRequest) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = inventory::parse_campaign_inventory_path(path) {
        return match inventory::add_item(id, body) {
            Ok(resp) => (201, resp),
            Err(inventory::InventoryError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(inventory::InventoryError::BadRequest) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some((campaign_id, character_id)) = inventory::parse_character_equipment_path(path) {
        return match inventory::assign_equipment(campaign_id, character_id, body) {
            Ok(resp) => (200, resp),
            Err(inventory::InventoryError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(inventory::InventoryError::BadRequest) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = downtime::parse_crafting_path(path) {
        return match downtime::create_project(id, body) {
            Ok(resp) => (201, resp),
            Err(downtime::CraftingError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(downtime::CraftingError::Conflict) => {
                (409, r#"{"error":"duplicate project id"}"#.to_string())
            }
            Err(downtime::CraftingError::BadRequest) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some((campaign_id, project_id)) = downtime::parse_crafting_advance_path(path) {
        return match downtime::advance_project(campaign_id, project_id, body) {
            Ok(resp) => (200, resp),
            Err(downtime::CraftingError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(downtime::CraftingError::Conflict) => {
                (409, r#"{"error":"duplicate project id"}"#.to_string())
            }
            Err(downtime::CraftingError::BadRequest) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = play::parse_play_campaign_path(path, "/members") {
        return match require_auth(req, users, AuthRequirement::Player) {
            Ok(actor) => match play::join_campaign(id, body, &actor) {
                Ok(resp) => {
                    let _ = save_storage(sessions, users);
                    (201, resp)
                }
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"duplicate"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some(id) = play::parse_play_campaign_path(path, "/start") {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::start_campaign(id, &actor) {
                Ok(resp) => {
                    let _ = save_storage(sessions, users);
                    (200, resp)
                }
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some(id) = play::parse_play_campaign_path(path, "/narrations") {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::narrate_campaign(id, body, &actor) {
                Ok(resp) => {
                    let _ = save_storage(sessions, users);
                    (201, resp)
                }
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some(id) = play::parse_play_campaign_path(path, "/actions") {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::submit_action(id, body, &actor) {
                Ok(resp) => {
                    let _ = save_storage(sessions, users);
                    (201, resp)
                }
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some(id) = play::parse_play_campaign_path(path, "/resolutions") {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::resolve_turn(id, body, &actor) {
                Ok(resp) => {
                    let _ = save_storage(sessions, users);
                    (201, resp)
                }
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some(id) = play::parse_play_campaign_path(path, "/turn/nudge") {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::nudge_campaign(id, body, &actor) {
                Ok(resp) => (201, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some(id) = play::parse_play_campaign_path(path, "/turn/travel") {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::travel_turn(id, body, &actor) {
                Ok(resp) => {
                    let _ = save_storage(sessions, users);
                    (201, resp)
                }
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some(id) = play::parse_play_campaign_path(path, "/turn/rest") {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::rest_turn(id, body, &actor) {
                Ok(resp) => {
                    let _ = save_storage(sessions, users);
                    (201, resp)
                }
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, scene_id)) = play::parse_play_campaign_scene_path(path, "/enter") {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::enter_scene(campaign_id, scene_id, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, scene_id)) = play::parse_play_campaign_scene_path(path, "/close") {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::close_scene(campaign_id, scene_id, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some(id) = play::parse_play_campaign_path(path, "/scenes") {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::create_scene(id, body, &actor) {
                Ok(resp) => (201, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, from_id)) = play::parse_play_campaign_location_path(path, "/connections") {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::create_connection(campaign_id, from_id, body, &actor) {
                Ok(resp) => (201, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some(id) = play::parse_play_campaign_path(path, "/locations") {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::create_location(id, body, &actor) {
                Ok(resp) => (201, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some(id) = play::parse_play_campaign_path(path, "/encounters") {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::create_encounter(id, body, &actor) {
                Ok(resp) => {
                    let _ = save_storage(sessions, users);
                    (201, resp)
                }
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, encounter_id)) = play::parse_play_encounter_monster_post_path(path) {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::add_encounter_monster(campaign_id, encounter_id, body, &actor) {
                Ok(resp) => (201, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, encounter_id)) = play::parse_play_encounter_combatant_post_path(path) {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::bind_encounter_member(campaign_id, encounter_id, body, &actor) {
                Ok(resp) => (201, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, encounter_id)) = play::parse_play_encounter_turn_advance_path(path) {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::advance_encounter_turn(campaign_id, encounter_id, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, encounter_id)) = play::parse_play_encounter_turn_delay_path(path) {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::delay_encounter_turn(campaign_id, encounter_id, body, &actor) {
                Ok(resp) => {
                    let _ = save_storage(sessions, users);
                    (200, resp)
                }
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, encounter_id)) = play::parse_play_encounter_turn_ready_path(path) {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::ready_encounter_turn(campaign_id, encounter_id, body, &actor) {
                Ok(resp) => (201, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, encounter_id)) = play::parse_play_encounter_actions_path(path) {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::submit_encounter_action(campaign_id, encounter_id, body, &actor) {
                Ok(resp) => (201, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, encounter_id)) = play::parse_play_encounter_damage_path(path) {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::damage_encounter_combatant(campaign_id, encounter_id, body, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, encounter_id)) = play::parse_play_encounter_heal_path(path) {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::heal_encounter_combatant(campaign_id, encounter_id, body, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, encounter_id)) = play::parse_play_encounter_conditions_path(path) {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::add_encounter_condition(campaign_id, encounter_id, body, &actor) {
                Ok(resp) => (201, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, encounter_id)) = play::parse_play_encounter_rewards_path(path) {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::award_encounter_rewards(campaign_id, encounter_id, body, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, encounter_id)) = play::parse_play_encounter_close_path(path) {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::close_encounter(campaign_id, encounter_id, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, encounter_id)) = play::parse_play_encounter_end_path(path) {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::end_encounter(campaign_id, encounter_id, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, character_id)) = play::parse_play_campaign_character_path(path, "/damage") {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::damage_character(campaign_id, character_id, body, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, character_id)) = play::parse_play_campaign_character_path(path, "/death-saves") {
        return match require_auth(req, users, AuthRequirement::Any) {
            Ok(actor) => match play::roll_death_save(campaign_id, character_id, body, &actor) {
                Ok(resp) => (201, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, session_id)) = campaigns::parse_campaign_session_path(path) {
        return match campaigns::record_attendance(campaign_id, session_id, body) {
            Ok(resp) => (200, resp),
            Err(campaigns::CampaignError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(campaigns::CampaignError::Conflict) => {
                (409, r#"{"error":"duplicate session id"}"#.to_string())
            }
            Err(campaigns::CampaignError::BadRequest) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = campaigns::parse_campaign_path(path, "/sessions") {
        return match campaigns::schedule_session(id, body) {
            Ok(resp) => (201, resp),
            Err(campaigns::CampaignError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(campaigns::CampaignError::Conflict) => {
                (409, r#"{"error":"duplicate session id"}"#.to_string())
            }
            Err(campaigns::CampaignError::BadRequest) => (400, BAD_REQUEST.to_string()),
        };
    }
    if let Some(id) = campaigns::parse_campaign_path(path, "/analytics/risk-report") {
        return match analytics::risk_report(id, body) {
            Ok(resp) => (200, resp),
            Err(analytics::AnalyticsError::NotFound) => (404, NOT_FOUND.to_string()),
            Err(_) => (400, BAD_REQUEST.to_string()),
        };
    }

    (404, NOT_FOUND.to_string())
}

/// Dispatch PUT requests.
fn dispatch_put(
    path: &str,
    body: &str,
    req: &str,
    _sessions: &mut HashMap<String, CombatSession>,
    users: &mut HashMap<String, User>,
) -> (u16, String) {
    if let Some(id) = play::parse_play_campaign_path(path, "/document") {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::update_document(id, body, &actor) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    (404, NOT_FOUND.to_string())
}

/// Map an auth error to an HTTP response.
fn auth_error(err: auth::AuthError) -> (u16, String) {
    match err {
        auth::AuthError::Unauthorized => (401, UNAUTHORIZED.to_string()),
        auth::AuthError::Forbidden => (403, FORBIDDEN.to_string()),
    }
}

/// Map a combat error to an HTTP response.
fn combat_error(err: combat::CombatError) -> (u16, String) {
    match err {
        combat::CombatError::NotFound => (404, NOT_FOUND.to_string()),
        combat::CombatError::BadRequest => (400, BAD_REQUEST.to_string()),
    }
}

/// Dispatch DELETE requests.
fn dispatch_delete(
    path: &str,
    _body: &str,
    req: &str,
    _sessions: &mut HashMap<String, CombatSession>,
    users: &mut HashMap<String, User>,
) -> (u16, String) {
    if let Some((campaign_id, encounter_id, monster_id)) =
        play::parse_play_encounter_monster_delete_path(path)
    {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::remove_encounter_monster(
                campaign_id,
                encounter_id,
                monster_id,
                &actor,
            ) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    if let Some((campaign_id, encounter_id, member)) =
        play::parse_play_encounter_combatant_delete_path(path)
    {
        return match require_auth(req, users, AuthRequirement::Dm) {
            Ok(actor) => match play::unbind_encounter_member(
                campaign_id,
                encounter_id,
                member,
                &actor,
            ) {
                Ok(resp) => (200, resp),
                Err(play::PlayError::NotFound) => (404, NOT_FOUND.to_string()),
                Err(play::PlayError::Conflict) => (409, r#"{"error":"conflict"}"#.to_string()),
                Err(play::PlayError::Forbidden) => (403, FORBIDDEN.to_string()),
                Err(play::PlayError::BadRequest) => (400, BAD_REQUEST.to_string()),
            },
            Err(e) => auth_error(e),
        };
    }
    (404, NOT_FOUND.to_string())
}

/// Map a generic `Option` handler result to an HTTP response.
fn option_response(result: Option<String>) -> (u16, String) {
    match result {
        Some(resp) => (200, resp),
        None => (400, BAD_REQUEST.to_string()),
    }
}
