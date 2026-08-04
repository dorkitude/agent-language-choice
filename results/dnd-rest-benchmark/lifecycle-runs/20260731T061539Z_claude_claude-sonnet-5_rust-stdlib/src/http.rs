//! Minimal blocking HTTP/1.1 server built on `std::net` only (no HTTP crate
//! is permitted for this target). Handles one connection at a time on the
//! calling thread: reads headers, reads exactly `Content-Length` bytes of
//! body, then dispatches to a handler in one of the domain modules below.

use std::io::{Read, Write};
use std::net::TcpStream;

use crate::analytics;
use crate::audit;
use crate::auth;
use crate::campaigns;
use crate::characters;
use crate::combat;
use crate::compendium;
use crate::crafting;
use crate::dice;
use crate::dm_tools;
use crate::encounters;
use crate::inventory;
use crate::npcs;
use crate::play;
use crate::quests;
use crate::sessions;
use crate::storage;

/// Reads one HTTP request off `stream`, parses the request line and
/// `Content-Length` header, reads the body, and routes it.
pub(crate) fn handle(stream: &mut TcpStream) -> std::io::Result<()> {
    let mut buf = Vec::new();
    let mut chunk = [0_u8; 4096];

    let headers_end;
    loop {
        let n = stream.read(&mut chunk)?;
        if n == 0 {
            return Ok(());
        }
        buf.extend_from_slice(&chunk[..n]);
        if let Some(pos) = find_subslice(&buf, b"\r\n\r\n") {
            headers_end = pos + 4;
            break;
        }
        if buf.len() > 1_000_000 {
            return respond(stream, 400, r#"{"error":"request too large"}"#);
        }
    }

    let header_text = String::from_utf8_lossy(&buf[..headers_end]).to_string();
    let mut lines = header_text.lines();
    let request_line = lines.next().unwrap_or("").to_string();
    let mut content_length: usize = 0;
    let mut authorization: Option<String> = None;
    let mut idempotency_key: Option<String> = None;
    for line in lines {
        if let Some(idx) = line.find(':') {
            let (name, value) = line.split_at(idx);
            if name.eq_ignore_ascii_case("content-length") {
                content_length = value[1..].trim().parse().unwrap_or(0);
            }
            if name.eq_ignore_ascii_case("authorization") {
                authorization = Some(value[1..].trim().to_string());
            }
            if name.eq_ignore_ascii_case("idempotency-key") {
                idempotency_key = Some(value[1..].trim().to_string());
            }
        }
    }

    let mut body = buf[headers_end..].to_vec();
    while body.len() < content_length {
        let n = stream.read(&mut chunk)?;
        if n == 0 {
            break;
        }
        body.extend_from_slice(&chunk[..n]);
    }
    body.truncate(content_length);
    let body_text = String::from_utf8_lossy(&body).to_string();

    let mut parts = request_line.split_whitespace();
    let method = parts.next().unwrap_or("");
    let path = parts.next().unwrap_or("");

    route(
        stream,
        method,
        path,
        &body_text,
        authorization.as_deref(),
        idempotency_key.as_deref(),
    )
}

fn find_subslice(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    if needle.is_empty() || haystack.len() < needle.len() {
        return None;
    }
    haystack.windows(needle.len()).position(|w| w == needle)
}

/// Dispatches a parsed request to its handler. Fixed paths are matched
/// directly; paths with a variable segment (e.g. `/v1/campaigns/{id}/state`)
/// are matched via prefix/suffix stripping in the fallback arm.
fn route(
    stream: &mut TcpStream,
    method: &str,
    full_path: &str,
    body: &str,
    auth_header: Option<&str>,
    idempotency_key: Option<&str>,
) -> std::io::Result<()> {
    let (path, query) = match full_path.split_once('?') {
        Some((p, q)) => (p, Some(q)),
        None => (full_path, None),
    };
    let query_param = |name: &str| -> Option<&str> {
        query.and_then(|q| {
            q.split('&').find_map(|kv| {
                let (k, v) = kv.split_once('=')?;
                if k == name { Some(v) } else { None }
            })
        })
    };
    match (method, path) {
        ("GET", "/health") => respond(stream, 200, r#"{"ok":true}"#),
        ("GET", "/healthz") => respond(stream, 200, r#"{"status":"ok"}"#),
        ("GET", "/readyz") => play::handle_readyz(stream),
        ("GET", "/v1/schema") => play::handle_schema(stream),
        ("POST", "/v1/play/campaigns") => {
            play::handle_create_play_campaign(stream, auth_header, body)
        }
        ("POST", "/v1/dice/stats") => dice::handle_dice_stats(stream, body),
        ("POST", "/v1/checks/ability") => dice::handle_ability_check(stream, body),
        ("POST", "/v1/encounters/adjusted-xp") => encounters::handle_adjusted_xp(stream, body),
        ("POST", "/v1/initiative/order") => dice::handle_initiative_order(stream, body),
        ("POST", "/v1/characters/ability-modifier") => characters::handle_ability_modifier(stream, body),
        ("POST", "/v1/characters/proficiency") => characters::handle_proficiency(stream, body),
        ("POST", "/v1/characters/derived-stats") => characters::handle_derived_stats(stream, body),
        ("POST", "/v1/combat/sessions") => combat::handle_create_combat_session(stream, body),
        ("POST", "/v1/auth/register") => auth::handle_register(stream, body),
        ("POST", "/v1/auth/login") => auth::handle_login(stream, body),
        ("GET", "/v1/storage/status") => storage::handle_storage_status(stream),
        ("POST", "/v1/storage/reset") => storage::handle_storage_reset(stream),
        ("POST", "/v1/compendium/monsters") => compendium::handle_create_monster(stream, body),
        ("POST", "/v1/compendium/items") => compendium::handle_create_item(stream, body),
        ("POST", "/v1/campaigns") => campaigns::handle_create_campaign(stream, body),
        ("POST", "/v1/phb/spell-slots") => characters::handle_spell_slots(stream, body),
        ("POST", "/v1/phb/rests/long") => characters::handle_long_rest(stream, body),
        ("POST", "/v1/phb/equipment-load") => characters::handle_equipment_load(stream, body),
        ("POST", "/v1/dm/encounter-builder") => dm_tools::handle_encounter_builder(stream, body),
        ("POST", "/v1/dm/loot-parcel") => dm_tools::handle_loot_parcel(stream, body),
        ("POST", "/v1/dm/session-recap") => dm_tools::handle_session_recap(stream, body),
        _ => {
            if method == "PUT" {
                if let Some(rest) = path.strip_prefix("/v1/play/campaigns/") {
                    if let Some(id) = rest.strip_suffix("/document") {
                        if !id.is_empty() {
                            return play::handle_put_document(stream, auth_header, id, body);
                        }
                    }
                    if let Some(without_prepared) = rest.strip_suffix("/prepared-spells") {
                        if let Some(idx) = without_prepared.find("/characters/") {
                            let campaign_id = &without_prepared[..idx];
                            let char_id = &without_prepared[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_put_prepared_spells(
                                    stream, auth_header, campaign_id, char_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_concentration) = rest.strip_suffix("/concentration") {
                        if let Some(idx) = without_concentration.find("/characters/") {
                            let campaign_id = &without_concentration[..idx];
                            let char_id = &without_concentration[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_put_concentration(
                                    stream, auth_header, campaign_id, char_id, body,
                                );
                            }
                        }
                    }
                    if let Some(eq_idx) = rest.find("/equipment/") {
                        let before = &rest[..eq_idx];
                        let slot = &rest[eq_idx + "/equipment/".len()..];
                        if let Some(idx) = before.find("/characters/") {
                            let campaign_id = &before[..idx];
                            let char_id = &before[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() && !slot.is_empty() {
                                return play::handle_put_equipment(
                                    stream, auth_header, campaign_id, char_id, slot, body,
                                );
                            }
                        }
                    }
                    if let Some(without_agenda) = rest.strip_suffix("/agenda") {
                        if let Some(idx) = without_agenda.find("/npcs/") {
                            let campaign_id = &without_agenda[..idx];
                            let npc_id = &without_agenda[idx + "/npcs/".len()..];
                            if !campaign_id.is_empty() && !npc_id.is_empty() {
                                return play::handle_update_npc_agenda(
                                    stream, auth_header, campaign_id, npc_id, body,
                                );
                            }
                        }
                    }
                    if let Some(idx) = rest.find("/relationships/") {
                        let campaign_id = &rest[..idx];
                        let tail = &rest[idx + "/relationships/".len()..];
                        let mut segs = tail.splitn(3, '/');
                        let source_id = segs.next().unwrap_or("");
                        let target_id = segs.next().unwrap_or("");
                        let kind = segs.next().unwrap_or("");
                        if !campaign_id.is_empty()
                            && !source_id.is_empty()
                            && !target_id.is_empty()
                            && !kind.is_empty()
                        {
                            return play::handle_update_relationship(
                                stream, auth_header, campaign_id, source_id, target_id, kind, body,
                            );
                        }
                    }
                    if let Some(without_state) = rest.strip_suffix("/state") {
                        if let Some(idx) = without_state.find("/quests/") {
                            let campaign_id = &without_state[..idx];
                            let quest_id = &without_state[idx + "/quests/".len()..];
                            if !campaign_id.is_empty() && !quest_id.is_empty() {
                                return play::handle_put_play_quest_state(
                                    stream, auth_header, campaign_id, quest_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_rewards) = rest.strip_suffix("/rewards") {
                        if let Some(idx) = without_rewards.find("/quests/") {
                            let campaign_id = &without_rewards[..idx];
                            let quest_id = &without_rewards[idx + "/quests/".len()..];
                            if !campaign_id.is_empty() && !quest_id.is_empty() {
                                return play::handle_put_quest_rewards(
                                    stream, auth_header, campaign_id, quest_id, body,
                                );
                            }
                        }
                    }
                    if let Some(idx) = rest.find("/settlements/") {
                        let campaign_id = &rest[..idx];
                        let settlement_id = &rest[idx + "/settlements/".len()..];
                        if !campaign_id.is_empty()
                            && !settlement_id.is_empty()
                            && !settlement_id.contains('/')
                        {
                            return play::handle_put_settlement(
                                stream, auth_header, campaign_id, settlement_id, body,
                            );
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/session-zero") {
                        if !id.is_empty() {
                            return play::handle_put_session_zero(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/rng-seed") {
                        if !id.is_empty() {
                            return play::handle_put_rng_seed(stream, auth_header, id, body);
                        }
                    }
                    if let Some(idx) = rest.find("/moderation/reports/") {
                        let campaign_id = &rest[..idx];
                        let tail = &rest[idx + "/moderation/reports/".len()..];
                        if let Some(report_id) = tail.strip_suffix("/resolution") {
                            if !campaign_id.is_empty() && !report_id.is_empty() {
                                return play::handle_resolve_moderation_report(
                                    stream, auth_header, campaign_id, report_id, body,
                                );
                            }
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/safety-boundaries") {
                        if !id.is_empty() {
                            return play::handle_put_safety_boundaries(
                                stream, auth_header, id, body,
                            );
                        }
                    }
                    if let Some(without_tags) = rest.strip_suffix("/tags") {
                        if let Some(idx) = without_tags.find("/content/") {
                            let campaign_id = &without_tags[..idx];
                            let content_id = &without_tags[idx + "/content/".len()..];
                            if !campaign_id.is_empty() && !content_id.is_empty() {
                                return play::handle_put_content_tags(
                                    stream, auth_header, campaign_id, content_id, body,
                                );
                            }
                        }
                    }
                    if let Some(idx) = rest.find("/notes/") {
                        let campaign_id = &rest[..idx];
                        let note_id = &rest[idx + "/notes/".len()..];
                        if !campaign_id.is_empty() && !note_id.is_empty() {
                            return play::handle_put_note(
                                stream, auth_header, campaign_id, note_id, body,
                            );
                        }
                    }
                }
            }
            if method == "POST" {
                if let Some(rest) = path.strip_prefix("/v1/combat/sessions/") {
                    if let Some(id) = rest.strip_suffix("/conditions") {
                        return combat::handle_add_condition(stream, id, body);
                    }
                    if let Some(id) = rest.strip_suffix("/advance") {
                        return combat::handle_advance_turn(stream, id);
                    }
                }
                if let Some(rest) = path.strip_prefix("/v1/play/campaigns/") {
                    if let Some(without_accept) = rest.strip_suffix("/accept") {
                        if let Some(idx) = without_accept.find("/invitations/") {
                            let campaign_id = &without_accept[..idx];
                            let invitation_id =
                                &without_accept[idx + "/invitations/".len()..];
                            if !campaign_id.is_empty() && !invitation_id.is_empty() {
                                return play::handle_accept_invitation(
                                    stream, auth_header, campaign_id, invitation_id,
                                );
                            }
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/invitations") {
                        if !id.is_empty() {
                            return play::handle_create_invitation(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/audit-events") {
                        if !id.is_empty() {
                            return play::handle_create_audit_event(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/projection-events") {
                        if !id.is_empty() {
                            return play::handle_create_projection_event(
                                stream, auth_header, id, body,
                            );
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/replay-events") {
                        if !id.is_empty() {
                            return play::handle_append_replay_event(
                                stream, auth_header, id, body,
                            );
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/moderation/reports") {
                        if !id.is_empty() {
                            return play::handle_create_moderation_report(
                                stream, auth_header, id, body,
                            );
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/safety-checks") {
                        if !id.is_empty() {
                            return play::handle_create_safety_check(
                                stream, auth_header, id, body,
                            );
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/rng-rolls") {
                        if !id.is_empty() {
                            return play::handle_append_rng_roll(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/idempotent-events") {
                        if !id.is_empty() {
                            return play::handle_create_idempotent_event(
                                stream,
                                auth_header,
                                id,
                                body,
                                idempotency_key,
                            );
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/safe-turns") {
                        if !id.is_empty() {
                            return play::handle_submit_safe_turn(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/fixture-seeds") {
                        if !id.is_empty() {
                            return play::handle_seed_fixture(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/service-mode") {
                        if !id.is_empty() {
                            return play::handle_set_service_mode(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/transactional-transfers") {
                        if !id.is_empty() {
                            return play::handle_create_transactional_transfer(
                                stream, auth_header, id, body,
                            );
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/exports") {
                        if !id.is_empty() {
                            return play::handle_create_export(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/imports") {
                        if !id.is_empty() {
                            return play::handle_create_import(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/migrations") {
                        if !id.is_empty() {
                            return play::handle_create_migration(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/search-records") {
                        if !id.is_empty() {
                            return play::handle_create_search_record(
                                stream, auth_header, id, body,
                            );
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/rate-events") {
                        if !id.is_empty() {
                            return play::handle_create_rate_event(
                                stream, auth_header, id, body,
                            );
                        }
                    }
                    if let Some(without_restore) = rest.strip_suffix("/restore") {
                        if let Some(idx) = without_restore.find("/backups/") {
                            let campaign_id = &without_restore[..idx];
                            let backup_id = &without_restore[idx + "/backups/".len()..];
                            if !campaign_id.is_empty() && !backup_id.is_empty() {
                                return play::handle_restore_backup(
                                    stream, auth_header, campaign_id, backup_id,
                                );
                            }
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/backups") {
                        if !id.is_empty() {
                            return play::handle_create_backup(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/members") {
                        if !id.is_empty() {
                            return play::handle_join_play_campaign(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/start") {
                        if !id.is_empty() {
                            return play::handle_start_play_campaign(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/narrations") {
                        if !id.is_empty() {
                            return play::handle_create_narration(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/delegations") {
                        if !id.is_empty() {
                            return play::handle_grant_delegation(stream, auth_header, id, body);
                        }
                    }
                    if let Some(without_actions) = rest.strip_suffix("/actions") {
                        if let Some(idx) = without_actions.find("/encounters/") {
                            let campaign_id = &without_actions[..idx];
                            let encounter_id =
                                &without_actions[idx + "/encounters/".len()..];
                            if !campaign_id.is_empty() && !encounter_id.is_empty() {
                                return play::handle_create_combat_action(
                                    stream, auth_header, campaign_id, encounter_id, body,
                                );
                            }
                        } else if !without_actions.is_empty() {
                            return play::handle_create_action(stream, auth_header, without_actions, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/resolutions") {
                        if !id.is_empty() {
                            return play::handle_create_resolution(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/turn/nudge") {
                        if !id.is_empty() {
                            return play::handle_create_turn_nudge(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/turn/travel") {
                        if !id.is_empty() {
                            return play::handle_create_travel(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/turn/rest") {
                        if !id.is_empty() {
                            return play::handle_create_rest(stream, auth_header, id, body);
                        }
                    }
                    if let Some(without_delay) = rest.strip_suffix("/turn/delay") {
                        if let Some(idx) = without_delay.find("/encounters/") {
                            let campaign_id = &without_delay[..idx];
                            let encounter_id = &without_delay[idx + "/encounters/".len()..];
                            if !campaign_id.is_empty() && !encounter_id.is_empty() {
                                return play::handle_turn_delay(
                                    stream, auth_header, campaign_id, encounter_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_ready) = rest.strip_suffix("/turn/ready") {
                        if let Some(idx) = without_ready.find("/encounters/") {
                            let campaign_id = &without_ready[..idx];
                            let encounter_id = &without_ready[idx + "/encounters/".len()..];
                            if !campaign_id.is_empty() && !encounter_id.is_empty() {
                                return play::handle_turn_ready(
                                    stream, auth_header, campaign_id, encounter_id, body,
                                );
                            }
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/scenes") {
                        if !id.is_empty() {
                            return play::handle_create_scene(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/encounters") {
                        if !id.is_empty() {
                            return play::handle_create_encounter(stream, auth_header, id, body);
                        }
                    }
                    if let Some(without_monsters) = rest.strip_suffix("/monsters") {
                        if let Some(idx) = without_monsters.find("/encounters/") {
                            let campaign_id = &without_monsters[..idx];
                            let encounter_id =
                                &without_monsters[idx + "/encounters/".len()..];
                            if !campaign_id.is_empty() && !encounter_id.is_empty() {
                                return play::handle_create_monster(
                                    stream, auth_header, campaign_id, encounter_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_advance) = rest.strip_suffix("/turn/advance") {
                        if let Some(idx) = without_advance.find("/encounters/") {
                            let campaign_id = &without_advance[..idx];
                            let encounter_id = &without_advance[idx + "/encounters/".len()..];
                            if !campaign_id.is_empty() && !encounter_id.is_empty() {
                                return play::handle_advance_encounter_turn(
                                    stream, auth_header, campaign_id, encounter_id,
                                );
                            }
                        }
                    }
                    if let Some(without_combatants) = rest.strip_suffix("/combatants") {
                        if let Some(idx) = without_combatants.find("/encounters/") {
                            let campaign_id = &without_combatants[..idx];
                            let encounter_id =
                                &without_combatants[idx + "/encounters/".len()..];
                            if !campaign_id.is_empty() && !encounter_id.is_empty() {
                                return play::handle_bind_combatant(
                                    stream, auth_header, campaign_id, encounter_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_damage) = rest.strip_suffix("/damage") {
                        if let Some(idx) = without_damage.find("/encounters/") {
                            let campaign_id = &without_damage[..idx];
                            let encounter_id =
                                &without_damage[idx + "/encounters/".len()..];
                            if !campaign_id.is_empty() && !encounter_id.is_empty() {
                                return play::handle_damage_target(
                                    stream, auth_header, campaign_id, encounter_id, body,
                                );
                            }
                        } else if let Some(idx) = without_damage.find("/characters/") {
                            let campaign_id = &without_damage[..idx];
                            let char_id = &without_damage[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_damage_character(
                                    stream, auth_header, campaign_id, char_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_death_saves) = rest.strip_suffix("/death-saves") {
                        if let Some(idx) = without_death_saves.find("/characters/") {
                            let campaign_id = &without_death_saves[..idx];
                            let char_id = &without_death_saves[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_death_save(
                                    stream, auth_header, campaign_id, char_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_claim) = rest.strip_suffix("/claim") {
                        if let Some(idx) = without_claim.find("/characters/") {
                            let campaign_id = &without_claim[..idx];
                            let char_id = &without_claim[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_claim_character(
                                    stream, auth_header, campaign_id, char_id,
                                );
                            }
                        }
                    }
                    if let Some(without_transfer) = rest.strip_suffix("/transfer") {
                        if let Some(idx) = without_transfer.find("/characters/") {
                            let campaign_id = &without_transfer[..idx];
                            let char_id = &without_transfer[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_transfer_character(
                                    stream, auth_header, campaign_id, char_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_build) = rest.strip_suffix("/build") {
                        if let Some(idx) = without_build.find("/characters/") {
                            let campaign_id = &without_build[..idx];
                            let char_id = &without_build[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_build_character(
                                    stream, auth_header, campaign_id, char_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_skill_check) = rest.strip_suffix("/skill-check") {
                        if let Some(idx) = without_skill_check.find("/characters/") {
                            let campaign_id = &without_skill_check[..idx];
                            let char_id =
                                &without_skill_check[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_skill_check(
                                    stream, auth_header, campaign_id, char_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_level_up) = rest.strip_suffix("/level-up") {
                        if let Some(idx) = without_level_up.find("/characters/") {
                            let campaign_id = &without_level_up[..idx];
                            let char_id = &without_level_up[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_level_up_character(
                                    stream, auth_header, campaign_id, char_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_spells) = rest.strip_suffix("/spells") {
                        if let Some(idx) = without_spells.find("/characters/") {
                            let campaign_id = &without_spells[..idx];
                            let char_id = &without_spells[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_add_spell(
                                    stream, auth_header, campaign_id, char_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_casts) = rest.strip_suffix("/casts") {
                        if let Some(idx) = without_casts.find("/characters/") {
                            let campaign_id = &without_casts[..idx];
                            let char_id = &without_casts[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_cast_spell(
                                    stream, auth_header, campaign_id, char_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_items) = rest.strip_suffix("/inventory/items") {
                        if let Some(idx) = without_items.find("/characters/") {
                            let campaign_id = &without_items[..idx];
                            let char_id = &without_items[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_add_inventory_item(
                                    stream, auth_header, campaign_id, char_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_consume) = rest.strip_suffix("/consume") {
                        if let Some(char_idx) = without_consume.find("/characters/") {
                            let after_char =
                                &without_consume[char_idx + "/characters/".len()..];
                            if let Some(items_idx) = after_char.find("/inventory/items/") {
                                let campaign_id = &without_consume[..char_idx];
                                let char_id = &after_char[..items_idx];
                                let item_id =
                                    &after_char[items_idx + "/inventory/items/".len()..];
                                if !campaign_id.is_empty()
                                    && !char_id.is_empty()
                                    && !item_id.is_empty()
                                {
                                    return play::handle_consume_inventory_item(
                                        stream, auth_header, campaign_id, char_id, item_id,
                                    );
                                }
                            }
                        }
                    }
                    if let Some(without_attune) = rest.strip_suffix("/attune") {
                        if let Some(eq_idx) = without_attune.find("/equipment/") {
                            let before = &without_attune[..eq_idx];
                            let slot = &without_attune[eq_idx + "/equipment/".len()..];
                            if let Some(idx) = before.find("/characters/") {
                                let campaign_id = &before[..idx];
                                let char_id = &before[idx + "/characters/".len()..];
                                if !campaign_id.is_empty() && !char_id.is_empty() && !slot.is_empty() {
                                    return play::handle_attune_equipment(
                                        stream, auth_header, campaign_id, char_id, slot,
                                    );
                                }
                            }
                        }
                    }
                    if let Some(without_advance) = rest.strip_suffix("/concentration/advance-turn") {
                        if let Some(idx) = without_advance.find("/characters/") {
                            let campaign_id = &without_advance[..idx];
                            let char_id = &without_advance[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_advance_concentration_turn(
                                    stream, auth_header, campaign_id, char_id,
                                );
                            }
                        }
                    }
                    if let Some(without_heal) = rest.strip_suffix("/heal") {
                        if let Some(idx) = without_heal.find("/encounters/") {
                            let campaign_id = &without_heal[..idx];
                            let encounter_id =
                                &without_heal[idx + "/encounters/".len()..];
                            if !campaign_id.is_empty() && !encounter_id.is_empty() {
                                return play::handle_heal_target(
                                    stream, auth_header, campaign_id, encounter_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_enter) = rest.strip_suffix("/enter") {
                        if let Some(idx) = without_enter.find("/scenes/") {
                            let campaign_id = &without_enter[..idx];
                            let scene_id = &without_enter[idx + "/scenes/".len()..];
                            if !campaign_id.is_empty() && !scene_id.is_empty() {
                                return play::handle_enter_scene(
                                    stream, auth_header, campaign_id, scene_id,
                                );
                            }
                        }
                    }
                    if let Some(without_close) = rest.strip_suffix("/close") {
                        if let Some(idx) = without_close.find("/scenes/") {
                            let campaign_id = &without_close[..idx];
                            let scene_id = &without_close[idx + "/scenes/".len()..];
                            if !campaign_id.is_empty() && !scene_id.is_empty() {
                                return play::handle_close_scene(
                                    stream, auth_header, campaign_id, scene_id,
                                );
                            }
                        } else if let Some(idx) = without_close.find("/encounters/") {
                            let campaign_id = &without_close[..idx];
                            let encounter_id = &without_close[idx + "/encounters/".len()..];
                            if !campaign_id.is_empty() && !encounter_id.is_empty() {
                                return play::handle_close_encounter(
                                    stream, auth_header, campaign_id, encounter_id,
                                );
                            }
                        }
                    }
                    if let Some(without_end) = rest.strip_suffix("/end") {
                        if let Some(idx) = without_end.find("/encounters/") {
                            let campaign_id = &without_end[..idx];
                            let encounter_id = &without_end[idx + "/encounters/".len()..];
                            if !campaign_id.is_empty() && !encounter_id.is_empty() {
                                return play::handle_end_encounter(
                                    stream, auth_header, campaign_id, encounter_id,
                                );
                            }
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/locations") {
                        if !id.is_empty() {
                            return play::handle_create_location(stream, auth_header, id, body);
                        }
                    }
                    if let Some(without_conditions) = rest.strip_suffix("/conditions") {
                        if let Some(idx) = without_conditions.find("/encounters/") {
                            let campaign_id = &without_conditions[..idx];
                            let encounter_id =
                                &without_conditions[idx + "/encounters/".len()..];
                            if !campaign_id.is_empty() && !encounter_id.is_empty() {
                                return play::handle_add_encounter_condition(
                                    stream, auth_header, campaign_id, encounter_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_rewards) = rest.strip_suffix("/rewards") {
                        if let Some(idx) = without_rewards.find("/encounters/") {
                            let campaign_id = &without_rewards[..idx];
                            let encounter_id =
                                &without_rewards[idx + "/encounters/".len()..];
                            if !campaign_id.is_empty() && !encounter_id.is_empty() {
                                return play::handle_award_encounter_rewards(
                                    stream, auth_header, campaign_id, encounter_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_connections) = rest.strip_suffix("/connections") {
                        if let Some(idx) = without_connections.find("/locations/") {
                            let campaign_id = &without_connections[..idx];
                            let from_id = &without_connections[idx + "/locations/".len()..];
                            if !campaign_id.is_empty() && !from_id.is_empty() {
                                return play::handle_create_connection(
                                    stream, auth_header, campaign_id, from_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_transfers) = rest.strip_suffix("/currency/transfers") {
                        if let Some(idx) = without_transfers.find("/characters/") {
                            let campaign_id = &without_transfers[..idx];
                            let char_id = &without_transfers[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_create_currency_transfer(
                                    stream, auth_header, campaign_id, char_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_votes) = rest.strip_suffix("/votes") {
                        if let Some(idx) = without_votes.find("/loot/") {
                            let campaign_id = &without_votes[..idx];
                            let loot_id = &without_votes[idx + "/loot/".len()..];
                            if !campaign_id.is_empty() && !loot_id.is_empty() {
                                return play::handle_create_loot_vote(
                                    stream, auth_header, campaign_id, loot_id, body,
                                );
                            }
                        }
                    }
                    if let Some(without_assign) = rest.strip_suffix("/assign") {
                        if let Some(idx) = without_assign.find("/loot/") {
                            let campaign_id = &without_assign[..idx];
                            let loot_id = &without_assign[idx + "/loot/".len()..];
                            if !campaign_id.is_empty() && !loot_id.is_empty() {
                                return play::handle_assign_loot(
                                    stream, auth_header, campaign_id, loot_id,
                                );
                            }
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/loot") {
                        if !id.is_empty() {
                            return play::handle_create_loot(stream, auth_header, id, body);
                        }
                    }
                    if let Some(without_dialogue) = rest.strip_suffix("/dialogue") {
                        if let Some(idx) = without_dialogue.find("/npcs/") {
                            let campaign_id = &without_dialogue[..idx];
                            let npc_id = &without_dialogue[idx + "/npcs/".len()..];
                            if !campaign_id.is_empty() && !npc_id.is_empty() {
                                return play::handle_create_npc_dialogue(
                                    stream, auth_header, campaign_id, npc_id, body,
                                );
                            }
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/npcs") {
                        if !id.is_empty() {
                            return play::handle_create_npc(stream, auth_header, id, body);
                        }
                    }
                    if let Some(without_reputation) = rest.strip_suffix("/reputation") {
                        if let Some(idx) = without_reputation.find("/factions/") {
                            let campaign_id = &without_reputation[..idx];
                            let faction_id = &without_reputation[idx + "/factions/".len()..];
                            if !campaign_id.is_empty() && !faction_id.is_empty() {
                                return play::handle_create_reputation_change(
                                    stream, auth_header, campaign_id, faction_id, body,
                                );
                            }
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/factions") {
                        if !id.is_empty() {
                            return play::handle_create_faction(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/relationships") {
                        if !id.is_empty() {
                            return play::handle_create_relationship(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/clues") {
                        if !id.is_empty() {
                            return play::handle_create_clue(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/quests") {
                        if !id.is_empty() {
                            return play::handle_create_play_quest(stream, auth_header, id, body);
                        }
                    }
                    if let Some(without_craft) = rest.strip_suffix("/craft") {
                        if let Some(idx) = without_craft.find("/recipes/") {
                            let campaign_id = &without_craft[..idx];
                            let recipe_id = &without_craft[idx + "/recipes/".len()..];
                            if !campaign_id.is_empty() && !recipe_id.is_empty() {
                                return play::handle_craft_recipe(
                                    stream, auth_header, campaign_id, recipe_id, body,
                                );
                            }
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/recipes") {
                        if !id.is_empty() {
                            return play::handle_create_recipe(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/content") {
                        if !id.is_empty() {
                            return play::handle_create_content(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/notes") {
                        if !id.is_empty() {
                            return play::handle_create_note(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/messages") {
                        if !id.is_empty() {
                            return play::handle_create_message(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/whispers") {
                        if !id.is_empty() {
                            return play::handle_create_whisper(stream, auth_header, id, body);
                        }
                    }
                    if let Some(without_progress) = rest.strip_suffix("/progress") {
                        if let Some(idx) = without_progress.find("/downtime/allocations/") {
                            let before = &without_progress[..idx];
                            let activity_id =
                                &without_progress[idx + "/downtime/allocations/".len()..];
                            if let Some(cidx) = before.find("/characters/") {
                                let campaign_id = &before[..cidx];
                                let char_id = &before[cidx + "/characters/".len()..];
                                if !campaign_id.is_empty()
                                    && !char_id.is_empty()
                                    && !activity_id.is_empty()
                                {
                                    return play::handle_progress_downtime_allocation(
                                        stream,
                                        auth_header,
                                        campaign_id,
                                        char_id,
                                        activity_id,
                                    );
                                }
                            }
                        }
                    }
                    if let Some(without_allocations) = rest.strip_suffix("/downtime/allocations") {
                        if let Some(idx) = without_allocations.find("/characters/") {
                            let campaign_id = &without_allocations[..idx];
                            let char_id = &without_allocations[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_create_downtime_allocation(
                                    stream, auth_header, campaign_id, char_id, body,
                                );
                            }
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/downtime/activities") {
                        if !id.is_empty() {
                            return play::handle_create_downtime_activity(
                                stream, auth_header, id, body,
                            );
                        }
                    }
                    if let Some(without_award) = rest.strip_suffix("/rewards/award") {
                        if let Some(idx) = without_award.find("/quests/") {
                            let campaign_id = &without_award[..idx];
                            let quest_id = &without_award[idx + "/quests/".len()..];
                            if !campaign_id.is_empty() && !quest_id.is_empty() {
                                return play::handle_award_quest_rewards(
                                    stream, auth_header, campaign_id, quest_id,
                                );
                            }
                        }
                    }
                    if let Some(without_resolve) = rest.strip_suffix("/resolve") {
                        if let Some(idx) = without_resolve.find("/world-events/") {
                            let campaign_id = &without_resolve[..idx];
                            let event_id = &without_resolve[idx + "/world-events/".len()..];
                            if !campaign_id.is_empty() && !event_id.is_empty() {
                                return play::handle_resolve_world_event(
                                    stream, auth_header, campaign_id, event_id, body,
                                );
                            }
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/world-events") {
                        if !id.is_empty() {
                            return play::handle_create_world_event(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/calendar/advance") {
                        if !id.is_empty() {
                            return play::handle_advance_calendar(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/calendar") {
                        if !id.is_empty() {
                            return play::handle_init_calendar(stream, auth_header, id, body);
                        }
                    }
                    if let Some(without_discover) = rest.strip_suffix("/discover") {
                        if let Some(idx) = without_discover.find("/settlements/") {
                            let campaign_id = &without_discover[..idx];
                            let settlement_id =
                                &without_discover[idx + "/settlements/".len()..];
                            if !campaign_id.is_empty() && !settlement_id.is_empty() {
                                return play::handle_discover_settlement(
                                    stream, auth_header, campaign_id, settlement_id,
                                );
                            }
                        }
                    }
                    if let Some(without_buy) = rest.strip_suffix("/buy") {
                        if let Some(idx) = without_buy.find("/shops/") {
                            let before = &without_buy[..idx];
                            let shop_id = &without_buy[idx + "/shops/".len()..];
                            if let Some(sidx) = before.find("/settlements/") {
                                let campaign_id = &before[..sidx];
                                let settlement_id = &before[sidx + "/settlements/".len()..];
                                if !campaign_id.is_empty()
                                    && !settlement_id.is_empty()
                                    && !shop_id.is_empty()
                                {
                                    return play::handle_buy_shop(
                                        stream,
                                        auth_header,
                                        campaign_id,
                                        settlement_id,
                                        shop_id,
                                        body,
                                    );
                                }
                            }
                        }
                    }
                    if let Some(without_sell) = rest.strip_suffix("/sell") {
                        if let Some(idx) = without_sell.find("/shops/") {
                            let before = &without_sell[..idx];
                            let shop_id = &without_sell[idx + "/shops/".len()..];
                            if let Some(sidx) = before.find("/settlements/") {
                                let campaign_id = &before[..sidx];
                                let settlement_id = &before[sidx + "/settlements/".len()..];
                                if !campaign_id.is_empty()
                                    && !settlement_id.is_empty()
                                    && !shop_id.is_empty()
                                {
                                    return play::handle_sell_shop(
                                        stream,
                                        auth_header,
                                        campaign_id,
                                        settlement_id,
                                        shop_id,
                                        body,
                                    );
                                }
                            }
                        }
                    }
                    if let Some(without_shops) = rest.strip_suffix("/shops") {
                        if let Some(idx) = without_shops.find("/settlements/") {
                            let campaign_id = &without_shops[..idx];
                            let settlement_id =
                                &without_shops[idx + "/settlements/".len()..];
                            if !campaign_id.is_empty() && !settlement_id.is_empty() {
                                return play::handle_create_shop(
                                    stream,
                                    auth_header,
                                    campaign_id,
                                    settlement_id,
                                    body,
                                );
                            }
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/settlements") {
                        if !id.is_empty() {
                            return play::handle_create_settlement(stream, auth_header, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/spectators") {
                        if !id.is_empty() {
                            return play::handle_create_spectator_ticket(
                                stream, auth_header, id, body,
                            );
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/feed-events") {
                        if !id.is_empty() {
                            return play::handle_append_feed_event(
                                stream, auth_header, id, body,
                            );
                        }
                    }
                }
                if let Some(rest) = path.strip_prefix("/v1/campaigns/") {
                    if let Some(id) = rest.strip_suffix("/characters") {
                        if !id.is_empty() {
                            return campaigns::handle_add_character(stream, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/events") {
                        if !id.is_empty() {
                            return campaigns::handle_add_event(stream, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/quests") {
                        if !id.is_empty() {
                            return quests::handle_create_quest(stream, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/factions") {
                        if !id.is_empty() {
                            return npcs::handle_create_faction(stream, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/npcs") {
                        if !id.is_empty() {
                            return npcs::handle_create_npc(stream, id, body);
                        }
                    }
                    if let Some(without_progress) = rest.strip_suffix("/progress") {
                        if let Some(idx) = without_progress.find("/quests/") {
                            let campaign_id = &without_progress[..idx];
                            let quest_id = &without_progress[idx + "/quests/".len()..];
                            if !campaign_id.is_empty() && !quest_id.is_empty() {
                                return quests::handle_quest_progress(stream, campaign_id, quest_id, body);
                            }
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/inventory") {
                        if !id.is_empty() {
                            return inventory::handle_add_inventory(stream, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/downtime/crafting") {
                        if !id.is_empty() {
                            return crafting::handle_create_crafting(stream, id, body);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/sessions") {
                        if !id.is_empty() {
                            return sessions::handle_schedule_session(stream, id, body);
                        }
                    }
                    if let Some(without_attendance) = rest.strip_suffix("/attendance") {
                        if let Some(idx) = without_attendance.find("/sessions/") {
                            let campaign_id = &without_attendance[..idx];
                            let session_id =
                                &without_attendance[idx + "/sessions/".len()..];
                            if !campaign_id.is_empty() && !session_id.is_empty() {
                                return sessions::handle_record_attendance(
                                    stream,
                                    campaign_id,
                                    session_id,
                                    body,
                                );
                            }
                        }
                    }
                    if let Some(without_advance) = rest.strip_suffix("/advance") {
                        if let Some(idx) = without_advance.find("/downtime/crafting/") {
                            let campaign_id = &without_advance[..idx];
                            let project_id =
                                &without_advance[idx + "/downtime/crafting/".len()..];
                            if !campaign_id.is_empty() && !project_id.is_empty() {
                                return crafting::handle_advance_crafting(
                                    stream,
                                    campaign_id,
                                    project_id,
                                    body,
                                );
                            }
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/analytics/risk-report") {
                        if !id.is_empty() {
                            return analytics::handle_risk_report(stream, id, body);
                        }
                    }
                    if let Some(without_equipment) = rest.strip_suffix("/equipment") {
                        if let Some(idx) = without_equipment.find("/characters/") {
                            let campaign_id = &without_equipment[..idx];
                            let character_id = &without_equipment[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !character_id.is_empty() {
                                return inventory::handle_assign_equipment(
                                    stream,
                                    campaign_id,
                                    character_id,
                                    body,
                                );
                            }
                        }
                    }
                }
            }
            if method == "GET" {
                if let Some(slug) = path.strip_prefix("/v1/compendium/monsters/") {
                    if !slug.is_empty() {
                        return compendium::handle_get_monster(stream, slug);
                    }
                }
                if let Some(slug) = path.strip_prefix("/v1/compendium/items/") {
                    if !slug.is_empty() {
                        return compendium::handle_get_item(stream, slug);
                    }
                }
                if let Some(rest) = path.strip_prefix("/v1/play/campaigns/") {
                    if let Some(id) = rest.strip_suffix("/invitations") {
                        if !id.is_empty() {
                            return play::handle_list_invitations(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/delegations/audit") {
                        if !id.is_empty() {
                            return play::handle_get_delegation_audit(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/audit-events") {
                        if !id.is_empty() {
                            return play::handle_list_audit_events(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/projection/rebuild") {
                        if !id.is_empty() {
                            return play::handle_rebuild_projection(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/projection") {
                        if !id.is_empty() {
                            return play::handle_get_projection(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/replay/check") {
                        if !id.is_empty() {
                            return play::handle_check_replay(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/replay") {
                        if !id.is_empty() {
                            return play::handle_get_replay(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/rng-ledger") {
                        if !id.is_empty() {
                            return play::handle_get_rng_ledger(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/moderation/reports") {
                        if !id.is_empty() {
                            return play::handle_list_moderation_reports(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/safety-boundaries") {
                        if !id.is_empty() {
                            return play::handle_get_safety_boundaries(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/safety-events") {
                        if !id.is_empty() {
                            return play::handle_list_safety_events(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/fixture-state") {
                        if !id.is_empty() {
                            return play::handle_get_fixture_state(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/idempotent-events") {
                        if !id.is_empty() {
                            return play::handle_list_idempotent_events(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/safe-turns") {
                        if !id.is_empty() {
                            return play::handle_list_safe_turns(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/transactional-transfers") {
                        if !id.is_empty() {
                            return play::handle_list_transactional_transfers(stream, auth_header, id);
                        }
                    }
                    if let Some(idx) = rest.find("/exports/") {
                        let campaign_id = &rest[..idx];
                        let version = &rest[idx + "/exports/".len()..];
                        if !campaign_id.is_empty() && !version.is_empty() {
                            return play::handle_get_export(
                                stream, auth_header, campaign_id, version,
                            );
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/exports") {
                        if !id.is_empty() {
                            return play::handle_list_exports(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/import-state") {
                        if !id.is_empty() {
                            return play::handle_get_import_state(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/migration-state") {
                        if !id.is_empty() {
                            return play::handle_get_migration_state(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/search-records") {
                        if !id.is_empty() {
                            return play::handle_list_search_records(
                                stream,
                                auth_header,
                                id,
                                query_param("q"),
                                query_param("limit"),
                                query_param("cursor"),
                            );
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/rate-events") {
                        if !id.is_empty() {
                            return play::handle_list_rate_events(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/metrics") {
                        if !id.is_empty() {
                            return play::handle_get_service_metrics(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/backups") {
                        if !id.is_empty() {
                            return play::handle_list_backups(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/my-turn") {
                        if !id.is_empty() {
                            return play::handle_get_my_turn(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/onboarding") {
                        if !id.is_empty() {
                            return play::handle_get_onboarding(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/gm/status") {
                        if !id.is_empty() {
                            return play::handle_get_gm_status(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/turn") {
                        if let Some(idx) = id.find("/encounters/") {
                            let campaign_id = &id[..idx];
                            let encounter_id = &id[idx + "/encounters/".len()..];
                            if !campaign_id.is_empty() && !encounter_id.is_empty() {
                                return play::handle_get_encounter_turn(
                                    stream, auth_header, campaign_id, encounter_id,
                                );
                            }
                        } else if !id.is_empty() {
                            return play::handle_get_turn(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/document") {
                        if !id.is_empty() {
                            return play::handle_get_document(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/session-zero") {
                        if !id.is_empty() {
                            return play::handle_get_session_zero(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/scenes/current") {
                        if !id.is_empty() {
                            return play::handle_get_current_scene(stream, auth_header, id);
                        }
                    }
                    if let Some(without_travel) = rest.strip_suffix("/travel") {
                        if let Some(idx) = without_travel.find("/locations/") {
                            let campaign_id = &without_travel[..idx];
                            let loc_id = &without_travel[idx + "/locations/".len()..];
                            if !campaign_id.is_empty() && !loc_id.is_empty() {
                                return play::handle_get_travel(
                                    stream, auth_header, campaign_id, loc_id,
                                );
                            }
                        }
                    }
                    if let Some(without_prepared) = rest.strip_suffix("/prepared-spells") {
                        if let Some(idx) = without_prepared.find("/characters/") {
                            let campaign_id = &without_prepared[..idx];
                            let char_id = &without_prepared[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_get_prepared_spells(
                                    stream, auth_header, campaign_id, char_id,
                                );
                            }
                        }
                    }
                    if let Some(without_spells) = rest.strip_suffix("/spells") {
                        if let Some(idx) = without_spells.find("/characters/") {
                            let campaign_id = &without_spells[..idx];
                            let char_id = &without_spells[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_get_spells(
                                    stream, auth_header, campaign_id, char_id,
                                );
                            }
                        }
                    }
                    if let Some(without_casts) = rest.strip_suffix("/casts") {
                        if let Some(idx) = without_casts.find("/characters/") {
                            let campaign_id = &without_casts[..idx];
                            let char_id = &without_casts[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_get_casts(
                                    stream, auth_header, campaign_id, char_id,
                                );
                            }
                        }
                    }
                    if let Some(without_concentration) = rest.strip_suffix("/concentration") {
                        if let Some(idx) = without_concentration.find("/characters/") {
                            let campaign_id = &without_concentration[..idx];
                            let char_id = &without_concentration[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_get_concentration(
                                    stream, auth_header, campaign_id, char_id,
                                );
                            }
                        }
                    }
                    if let Some(without_items) = rest.strip_suffix("/inventory/items") {
                        if let Some(idx) = without_items.find("/characters/") {
                            let campaign_id = &without_items[..idx];
                            let char_id = &without_items[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_get_inventory_items(
                                    stream, auth_header, campaign_id, char_id,
                                );
                            }
                        }
                    }
                    if let Some(eq_idx) = rest.find("/equipment/") {
                        let before = &rest[..eq_idx];
                        let slot = &rest[eq_idx + "/equipment/".len()..];
                        if let Some(idx) = before.find("/characters/") {
                            let campaign_id = &before[..idx];
                            let char_id = &before[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() && !slot.is_empty() {
                                return play::handle_get_equipment(
                                    stream, auth_header, campaign_id, char_id, slot,
                                );
                            }
                        }
                    }
                    if let Some(without_currency) = rest.strip_suffix("/currency") {
                        if let Some(idx) = without_currency.find("/characters/") {
                            let campaign_id = &without_currency[..idx];
                            let char_id = &without_currency[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_get_currency(
                                    stream, auth_header, campaign_id, char_id,
                                );
                            }
                        }
                    }
                    if let Some(idx) = rest.find("/loot/") {
                        let campaign_id = &rest[..idx];
                        let loot_id = &rest[idx + "/loot/".len()..];
                        if !campaign_id.is_empty() && !loot_id.is_empty() {
                            return play::handle_get_loot(
                                stream, auth_header, campaign_id, loot_id,
                            );
                        }
                    }
                    if let Some(without_dialogue) = rest.strip_suffix("/dialogue") {
                        if let Some(idx) = without_dialogue.find("/npcs/") {
                            let campaign_id = &without_dialogue[..idx];
                            let npc_id = &without_dialogue[idx + "/npcs/".len()..];
                            if !campaign_id.is_empty() && !npc_id.is_empty() {
                                return play::handle_get_npc_dialogue(
                                    stream, auth_header, campaign_id, npc_id,
                                );
                            }
                        }
                    }
                    if let Some(idx) = rest.find("/npcs/") {
                        let campaign_id = &rest[..idx];
                        let npc_id = &rest[idx + "/npcs/".len()..];
                        if !campaign_id.is_empty() && !npc_id.is_empty() {
                            return play::handle_get_npc(
                                stream, auth_header, campaign_id, npc_id,
                            );
                        }
                    }
                    if let Some(without_owner) = rest.strip_suffix("/owner") {
                        if let Some(idx) = without_owner.find("/characters/") {
                            let campaign_id = &without_owner[..idx];
                            let char_id = &without_owner[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_get_character_owner(
                                    stream, auth_header, campaign_id, char_id,
                                );
                            }
                        }
                    }
                    if let Some(without_status) = rest.strip_suffix("/status") {
                        if let Some(idx) = without_status.find("/characters/") {
                            let campaign_id = &without_status[..idx];
                            let char_id = &without_status[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_get_character_status(
                                    stream, auth_header, campaign_id, char_id,
                                );
                            }
                        } else if let Some(idx) = without_status.find("/encounters/") {
                            let campaign_id = &without_status[..idx];
                            let encounter_id = &without_status[idx + "/encounters/".len()..];
                            if !campaign_id.is_empty() && !encounter_id.is_empty() {
                                return play::handle_get_encounter_status(
                                    stream, auth_header, campaign_id, encounter_id,
                                );
                            }
                        }
                    }
                    if let Some(without_reputation) = rest.strip_suffix("/reputation") {
                        if let Some(idx) = without_reputation.find("/factions/") {
                            let campaign_id = &without_reputation[..idx];
                            let faction_id = &without_reputation[idx + "/factions/".len()..];
                            if !campaign_id.is_empty() && !faction_id.is_empty() {
                                return play::handle_get_reputation(
                                    stream, auth_header, campaign_id, faction_id,
                                );
                            }
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/relationships") {
                        if !id.is_empty() {
                            return play::handle_get_relationships(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/clues") {
                        if !id.is_empty() {
                            return play::handle_get_clues(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/world-events") {
                        if !id.is_empty() {
                            return play::handle_get_world_events(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/calendar") {
                        if !id.is_empty() {
                            return play::handle_get_calendar(stream, auth_header, id);
                        }
                    }
                    if let Some(idx) = rest.find("/shops/") {
                        let before = &rest[..idx];
                        let shop_id = &rest[idx + "/shops/".len()..];
                        if let Some(sidx) = before.find("/settlements/") {
                            let campaign_id = &before[..sidx];
                            let settlement_id = &before[sidx + "/settlements/".len()..];
                            if !campaign_id.is_empty()
                                && !settlement_id.is_empty()
                                && !shop_id.is_empty()
                            {
                                return play::handle_get_shop(
                                    stream,
                                    auth_header,
                                    campaign_id,
                                    settlement_id,
                                    shop_id,
                                );
                            }
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/settlements") {
                        if !id.is_empty() {
                            return play::handle_get_settlements(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/quests") {
                        if !id.is_empty() {
                            return play::handle_get_play_quests(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/recipes") {
                        if !id.is_empty() {
                            return play::handle_get_recipes(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/content") {
                        if !id.is_empty() {
                            return play::handle_get_content(
                                stream,
                                auth_header,
                                id,
                                query_param("exclude_tag"),
                            );
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/notes") {
                        if !id.is_empty() {
                            return play::handle_get_notes(stream, auth_header, id);
                        }
                    }
                    if let Some(idx) = rest.find("/notes/") {
                        let campaign_id = &rest[..idx];
                        let note_id = &rest[idx + "/notes/".len()..];
                        if !campaign_id.is_empty() && !note_id.is_empty() {
                            return play::handle_get_note(
                                stream, auth_header, campaign_id, note_id,
                            );
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/whispers") {
                        if !id.is_empty() {
                            return play::handle_get_whispers(stream, auth_header, id);
                        }
                    }
                    if let Some(without_sheet) = rest.strip_suffix("/sheet") {
                        if let Some(idx) = without_sheet.find("/characters/") {
                            let campaign_id = &without_sheet[..idx];
                            let char_id = &without_sheet[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_get_character_sheet(
                                    stream, auth_header, campaign_id, char_id,
                                );
                            }
                        }
                    }
                    if let Some(idx) = rest.find("/downtime/allocations/") {
                        let before = &rest[..idx];
                        let activity_id = &rest[idx + "/downtime/allocations/".len()..];
                        if let Some(cidx) = before.find("/characters/") {
                            let campaign_id = &before[..cidx];
                            let char_id = &before[cidx + "/characters/".len()..];
                            if !campaign_id.is_empty()
                                && !char_id.is_empty()
                                && !activity_id.is_empty()
                            {
                                return play::handle_get_downtime_allocation(
                                    stream,
                                    auth_header,
                                    campaign_id,
                                    char_id,
                                    activity_id,
                                );
                            }
                        }
                    }
                    if let Some(without_rewards) = rest.strip_suffix("/rewards") {
                        if let Some(idx) = without_rewards.find("/characters/") {
                            let campaign_id = &without_rewards[..idx];
                            let char_id = &without_rewards[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_get_character_rewards(
                                    stream, auth_header, campaign_id, char_id,
                                );
                            }
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/spectator-view") {
                        if !id.is_empty() {
                            return play::handle_get_spectator_view(stream, auth_header, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/event-feed") {
                        if !id.is_empty() {
                            return play::handle_get_event_feed(
                                stream,
                                auth_header,
                                id,
                                query_param("cursor"),
                                query_param("limit"),
                            );
                        }
                    }
                }
                if let Some(rest) = path.strip_prefix("/v1/campaigns/") {
                    if let Some(id) = rest.strip_suffix("/state") {
                        if !id.is_empty() {
                            return campaigns::handle_get_campaign_state(stream, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/quests/summary") {
                        if !id.is_empty() {
                            return quests::handle_quest_summary(stream, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/relationships") {
                        if !id.is_empty() {
                            return npcs::handle_relationship_summary(stream, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/inventory/summary") {
                        if !id.is_empty() {
                            return inventory::handle_inventory_summary(stream, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/sessions/next") {
                        if !id.is_empty() {
                            return sessions::handle_next_session(stream, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/audit") {
                        if !id.is_empty() {
                            return audit::handle_audit(stream, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/export") {
                        if !id.is_empty() {
                            return audit::handle_export(stream, id);
                        }
                    }
                    if let Some(id) = rest.strip_suffix("/analytics/summary") {
                        if !id.is_empty() {
                            return analytics::handle_analytics_summary(stream, id);
                        }
                    }
                }
            }
            if method == "DELETE" {
                if let Some(rest) = path.strip_prefix("/v1/play/campaigns/") {
                    if let Some(idx) = rest.find("/delegations/") {
                        let campaign_id = &rest[..idx];
                        let target_username = &rest[idx + "/delegations/".len()..];
                        if !campaign_id.is_empty() && !target_username.is_empty() {
                            return play::handle_revoke_delegation(
                                stream,
                                auth_header,
                                campaign_id,
                                target_username,
                            );
                        }
                    }
                    if let Some(enc_idx) = rest.find("/encounters/") {
                        let after_enc = &rest[enc_idx + "/encounters/".len()..];
                        if let Some(mon_idx) = after_enc.find("/monsters/") {
                            let campaign_id = &rest[..enc_idx];
                            let encounter_id = &after_enc[..mon_idx];
                            let monster_id = &after_enc[mon_idx + "/monsters/".len()..];
                            if !campaign_id.is_empty()
                                && !encounter_id.is_empty()
                                && !monster_id.is_empty()
                            {
                                return play::handle_remove_monster(
                                    stream,
                                    auth_header,
                                    campaign_id,
                                    encounter_id,
                                    monster_id,
                                );
                            }
                        }
                        if let Some(combatant_idx) = after_enc.find("/combatants/") {
                            let campaign_id = &rest[..enc_idx];
                            let encounter_id = &after_enc[..combatant_idx];
                            let member = &after_enc[combatant_idx + "/combatants/".len()..];
                            if !campaign_id.is_empty()
                                && !encounter_id.is_empty()
                                && !member.is_empty()
                            {
                                return play::handle_unbind_combatant(
                                    stream,
                                    auth_header,
                                    campaign_id,
                                    encounter_id,
                                    member,
                                );
                            }
                        }
                    }
                    if let Some(without_concentration) = rest.strip_suffix("/concentration") {
                        if let Some(idx) = without_concentration.find("/characters/") {
                            let campaign_id = &without_concentration[..idx];
                            let char_id = &without_concentration[idx + "/characters/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() {
                                return play::handle_delete_concentration(
                                    stream, auth_header, campaign_id, char_id,
                                );
                            }
                        }
                    }
                    if let Some(char_idx) = rest.find("/characters/") {
                        let after_char = &rest[char_idx + "/characters/".len()..];
                        if let Some(items_idx) = after_char.find("/inventory/items/") {
                            let campaign_id = &rest[..char_idx];
                            let char_id = &after_char[..items_idx];
                            let item_id = &after_char[items_idx + "/inventory/items/".len()..];
                            if !campaign_id.is_empty() && !char_id.is_empty() && !item_id.is_empty() {
                                return play::handle_remove_inventory_item(
                                    stream, auth_header, campaign_id, char_id, item_id, body,
                                );
                            }
                        }
                    }
                }
            }
            respond(stream, 404, r#"{"error":"not found"}"#)
        }
    }
}

/// Writes a `{"error": msg}` body with a 400 status. Shared by every handler
/// module for validation failures.
pub(crate) fn bad_request(stream: &mut TcpStream, msg: &str) -> std::io::Result<()> {
    respond(
        stream,
        400,
        &format!(r#"{{"error":"{}"}}"#, crate::json::escape_json_string(msg)),
    )
}

pub(crate) fn respond(stream: &mut TcpStream, status: u16, body: &str) -> std::io::Result<()> {
    let label = match status {
        200 => "OK",
        201 => "Created",
        400 => "Bad Request",
        401 => "Unauthorized",
        403 => "Forbidden",
        404 => "Not Found",
        409 => "Conflict",
        _ => "Error",
    };
    write!(
        stream,
        "HTTP/1.1 {status} {label}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        body.len(),
        body
    )
}
