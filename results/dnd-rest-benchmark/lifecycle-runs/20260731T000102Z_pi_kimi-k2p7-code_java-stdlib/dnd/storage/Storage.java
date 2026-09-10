package dnd.storage;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import dnd.json.JsonUtils;
import dnd.model.Combatant;
import dnd.model.CombatSession;
import dnd.model.Condition;
import dnd.model.User;

/**
 * SQLite-backed persistence layer.
 * All operations are serialized on a single lock because the backing store
 * is an external sqlite3 process per query. The schema is created lazily by
 * init() and recreated by reset().
 */
public class Storage {
    private final String dbPath;
    private final Object lock = new Object();
    private boolean initialized = false;

    public Storage(String dbPath) {
        this.dbPath = dbPath;
    }

    public void init() {
        synchronized (lock) {
            execSql(
                "CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, role TEXT NOT NULL, salt TEXT NOT NULL, hash TEXT NOT NULL);",
                "CREATE TABLE IF NOT EXISTS combat_sessions (id TEXT PRIMARY KEY, round INTEGER NOT NULL, turn_index INTEGER NOT NULL);",
                "CREATE TABLE IF NOT EXISTS combatants (session_id TEXT NOT NULL, name TEXT NOT NULL, score INTEGER NOT NULL, dex INTEGER NOT NULL, roll INTEGER NOT NULL, sort_order INTEGER NOT NULL, PRIMARY KEY (session_id, name));",
                "CREATE TABLE IF NOT EXISTS conditions (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, target TEXT NOT NULL, condition TEXT NOT NULL, remaining_rounds INTEGER NOT NULL);",
                "CREATE TABLE IF NOT EXISTS monsters (slug TEXT PRIMARY KEY, name TEXT NOT NULL, cr TEXT NOT NULL, armor_class INTEGER NOT NULL, hit_points INTEGER NOT NULL);",
                "CREATE TABLE IF NOT EXISTS monster_tags (monster_slug TEXT NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (monster_slug, tag));",
                "CREATE TABLE IF NOT EXISTS items (slug TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, rarity TEXT NOT NULL, cost_gp INTEGER NOT NULL);",
                "CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, dm TEXT NOT NULL);",
                "CREATE TABLE IF NOT EXISTS campaign_characters (id TEXT NOT NULL, campaign_id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL, class TEXT NOT NULL, PRIMARY KEY (id, campaign_id));",
                "CREATE TABLE IF NOT EXISTS campaign_events (id TEXT NOT NULL, campaign_id TEXT NOT NULL, kind TEXT NOT NULL, summary TEXT, PRIMARY KEY (id, campaign_id));",
                "CREATE TABLE IF NOT EXISTS quests (id TEXT NOT NULL, campaign_id TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (id, campaign_id));",
                "CREATE TABLE IF NOT EXISTS quest_milestones (quest_id TEXT NOT NULL, campaign_id TEXT NOT NULL, milestone TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (quest_id, campaign_id, milestone));",
                "CREATE TABLE IF NOT EXISTS factions (id TEXT NOT NULL, campaign_id TEXT NOT NULL, name TEXT NOT NULL, stance TEXT NOT NULL, PRIMARY KEY (id, campaign_id));",
                "CREATE TABLE IF NOT EXISTS npcs (id TEXT NOT NULL, campaign_id TEXT NOT NULL, name TEXT NOT NULL, faction_id TEXT NOT NULL, disposition INTEGER NOT NULL, PRIMARY KEY (id, campaign_id));",
                "CREATE TABLE IF NOT EXISTS campaign_inventory (campaign_id TEXT NOT NULL, item_slug TEXT NOT NULL, owner TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, item_slug, owner));",
                "CREATE TABLE IF NOT EXISTS character_equipment (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, item_slug));",
                "CREATE TABLE IF NOT EXISTS downtime_crafting_projects (id TEXT NOT NULL, campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, days_required INTEGER NOT NULL, days_completed INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, PRIMARY KEY (id, campaign_id));",
                "CREATE TABLE IF NOT EXISTS sessions (id TEXT NOT NULL, campaign_id TEXT NOT NULL, starts_at TEXT NOT NULL, duration_minutes INTEGER NOT NULL, agenda_count INTEGER NOT NULL, PRIMARY KEY (id, campaign_id));",
                "CREATE TABLE IF NOT EXISTS session_attendance (session_id TEXT NOT NULL, campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, present INTEGER NOT NULL, PRIMARY KEY (session_id, campaign_id, character_id));",
                "CREATE TABLE IF NOT EXISTS play_campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL, status TEXT NOT NULL, max_players INTEGER NOT NULL, current_actor TEXT, turn_number INTEGER DEFAULT 1, nudge_count INTEGER DEFAULT 0, deadline INTEGER DEFAULT 1, story TEXT DEFAULT '', dm_notes TEXT DEFAULT '', current_location_id TEXT, pre_combat_actor TEXT, phase TEXT DEFAULT 'turn');",
                "CREATE TABLE IF NOT EXISTS play_campaign_members (campaign_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL, name TEXT NOT NULL, class TEXT NOT NULL, race TEXT, background TEXT, level INTEGER DEFAULT 1, owner TEXT, hp_current INTEGER NOT NULL DEFAULT 20, hp_max INTEGER NOT NULL DEFAULT 20, status TEXT NOT NULL DEFAULT 'conscious', death_save_successes INTEGER NOT NULL DEFAULT 0, death_save_failures INTEGER NOT NULL DEFAULT 0, abilities TEXT, gold INTEGER NOT NULL DEFAULT 10, PRIMARY KEY (campaign_id, username), UNIQUE (campaign_id, character_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_transfers (campaign_id TEXT NOT NULL, transfer_id INTEGER NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, gold INTEGER NOT NULL, PRIMARY KEY (campaign_id, transfer_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_narrations (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, kind TEXT NOT NULL DEFAULT 'narration', actor TEXT NOT NULL, type TEXT, text TEXT NOT NULL, encounter_id TEXT, target TEXT, PRIMARY KEY (campaign_id, sequence));",
                "CREATE TABLE IF NOT EXISTS play_campaign_scenes (campaign_id TEXT NOT NULL, scene_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', PRIMARY KEY (campaign_id, scene_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_locations (campaign_id TEXT NOT NULL, location_id TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY (campaign_id, location_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_location_connections (campaign_id TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL, travel_turns INTEGER NOT NULL, PRIMARY KEY (campaign_id, from_id, to_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_encounters (campaign_id TEXT NOT NULL, encounter_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL, round INTEGER NOT NULL DEFAULT 1, turn_index INTEGER NOT NULL DEFAULT 0, xp_awarded INTEGER NOT NULL DEFAULT 0, rewards_awarded INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, encounter_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_encounter_loot (campaign_id TEXT NOT NULL, encounter_id TEXT NOT NULL, item_slug TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, encounter_id, item_slug));",
                "CREATE TABLE IF NOT EXISTS play_campaign_encounter_monsters (campaign_id TEXT NOT NULL, encounter_id TEXT NOT NULL, monster_id TEXT NOT NULL, name TEXT NOT NULL, hp_max INTEGER NOT NULL, hp_current INTEGER NOT NULL, initiative INTEGER NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, encounter_id, monster_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_encounter_combatants (campaign_id TEXT NOT NULL, encounter_id TEXT NOT NULL, member TEXT NOT NULL, character_id TEXT NOT NULL, name TEXT NOT NULL, initiative INTEGER NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, encounter_id, member));",
                "CREATE TABLE IF NOT EXISTS play_campaign_encounter_conditions (campaign_id TEXT NOT NULL, encounter_id TEXT NOT NULL, target TEXT NOT NULL, condition TEXT NOT NULL, remaining_rounds INTEGER NOT NULL, PRIMARY KEY (campaign_id, encounter_id, target, condition));",
                "CREATE TABLE IF NOT EXISTS play_campaign_encounter_readies (campaign_id TEXT NOT NULL, encounter_id TEXT NOT NULL, actor TEXT NOT NULL, trigger TEXT NOT NULL, PRIMARY KEY (campaign_id, encounter_id, actor));",
                "CREATE TABLE IF NOT EXISTS play_campaign_character_spells (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, spell_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_character_prepared_spells (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, PRIMARY KEY (campaign_id, character_id, spell_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_character_casts (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, sequence INTEGER NOT NULL, spell_id TEXT NOT NULL, target TEXT NOT NULL, slot_level INTEGER NOT NULL, slots_remaining INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, sequence));",
                "CREATE TABLE IF NOT EXISTS play_campaign_character_concentration (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, target TEXT NOT NULL, remaining_turns INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_character_inventory (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, item_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_character_equipment (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, slot TEXT NOT NULL, item_id TEXT NOT NULL, attuned INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, character_id, slot));",
                "CREATE TABLE IF NOT EXISTS play_campaign_loot (campaign_id TEXT NOT NULL, loot_id TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'open', recipient_character_id TEXT, votes INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, loot_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (campaign_id TEXT NOT NULL, loot_id TEXT NOT NULL, voter TEXT NOT NULL, recipient_character_id TEXT NOT NULL, PRIMARY KEY (campaign_id, loot_id, voter));",
                "CREATE TABLE IF NOT EXISTS play_campaign_npcs (campaign_id TEXT NOT NULL, npc_id TEXT NOT NULL, name TEXT NOT NULL, agenda TEXT NOT NULL, public_status TEXT NOT NULL, PRIMARY KEY (campaign_id, npc_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_factions (campaign_id TEXT NOT NULL, faction_id TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY (campaign_id, faction_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_reputation_history (id INTEGER PRIMARY KEY, campaign_id TEXT NOT NULL, faction_id TEXT NOT NULL, character_id TEXT NOT NULL, reputation INTEGER NOT NULL, delta INTEGER NOT NULL, reason TEXT NOT NULL);",
                "CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (campaign_id TEXT NOT NULL, npc_id TEXT NOT NULL, dialogue_id TEXT NOT NULL, speaker TEXT NOT NULL, text TEXT NOT NULL, visibility TEXT NOT NULL, PRIMARY KEY (campaign_id, npc_id, dialogue_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_relationships (campaign_id TEXT NOT NULL, source_id TEXT NOT NULL, target_id TEXT NOT NULL, kind TEXT NOT NULL, score INTEGER NOT NULL, PRIMARY KEY (campaign_id, source_id, target_id, kind));",
                "CREATE TABLE IF NOT EXISTS play_campaign_clues (campaign_id TEXT NOT NULL, clue_id TEXT NOT NULL, text TEXT NOT NULL, audience TEXT NOT NULL, character_id TEXT, PRIMARY KEY (campaign_id, clue_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_quests (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, title TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'locked', sort_order INTEGER NOT NULL, reward_xp INTEGER NOT NULL DEFAULT 0, reward_items TEXT NOT NULL DEFAULT '{}', rewards_configured INTEGER NOT NULL DEFAULT 0, rewards_awarded INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, quest_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_quest_dependencies (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, depends_on TEXT NOT NULL, PRIMARY KEY (campaign_id, quest_id, depends_on));",
                "CREATE TABLE IF NOT EXISTS play_campaign_quest_rewards (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, character_id TEXT NOT NULL, xp INTEGER NOT NULL DEFAULT 0, items TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (campaign_id, quest_id, character_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_world_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, turn_number INTEGER NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'scheduled', resolution_turn_number INTEGER, resolution_text TEXT, PRIMARY KEY (campaign_id, event_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_calendars (campaign_id TEXT PRIMARY KEY, day INTEGER NOT NULL, season TEXT NOT NULL);",
                "CREATE TABLE IF NOT EXISTS play_campaign_settlements (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, name TEXT NOT NULL, services TEXT NOT NULL, availability TEXT NOT NULL, sort_order INTEGER NOT NULL, PRIMARY KEY (campaign_id, settlement_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_settlement_discoveries (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, character_id TEXT NOT NULL, UNIQUE (campaign_id, settlement_id, character_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_shops (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, shop_id TEXT NOT NULL, name TEXT NOT NULL, stock TEXT NOT NULL, buy_price INTEGER NOT NULL, sell_price INTEGER NOT NULL, PRIMARY KEY (campaign_id, settlement_id, shop_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_recipes (campaign_id TEXT NOT NULL, recipe_id TEXT NOT NULL, name TEXT NOT NULL, output_item TEXT NOT NULL, output_quantity INTEGER NOT NULL, ingredients TEXT NOT NULL, sort_order INTEGER NOT NULL, PRIMARY KEY (campaign_id, recipe_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (campaign_id TEXT NOT NULL, activity_id TEXT NOT NULL, name TEXT NOT NULL, cycles_required INTEGER NOT NULL, PRIMARY KEY (campaign_id, activity_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_downtime_allocations (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, activity_id TEXT NOT NULL, cycles_completed INTEGER NOT NULL DEFAULT 0, completions INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, character_id, activity_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_session_zero (campaign_id TEXT PRIMARY KEY, rules TEXT NOT NULL, tone TEXT NOT NULL, consent_json TEXT NOT NULL);",
                "CREATE TABLE IF NOT EXISTS play_campaign_content (campaign_id TEXT NOT NULL, content_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, tags_json TEXT NOT NULL, sort_order INTEGER NOT NULL, PRIMARY KEY (campaign_id, content_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_notes (campaign_id TEXT NOT NULL, note_id TEXT NOT NULL, text TEXT NOT NULL, visibility TEXT NOT NULL, owner TEXT NOT NULL, sort_order INTEGER NOT NULL, PRIMARY KEY (campaign_id, note_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_whispers (campaign_id TEXT NOT NULL, whisper_id TEXT NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, whisper_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_invitations (campaign_id TEXT NOT NULL, invitation_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', PRIMARY KEY (campaign_id, invitation_id));"

            );
            // Migration for existing play_campaigns tables that lack the turn-tracking columns.
            addColumnIfMissing("play_campaigns", "current_actor TEXT;");
            addColumnIfMissing("play_campaigns", "turn_number INTEGER DEFAULT 1;");
            addColumnIfMissing("play_campaign_narrations", "kind TEXT NOT NULL DEFAULT 'narration';");
            addColumnIfMissing("play_campaign_narrations", "type TEXT;");
            addColumnIfMissing("play_campaigns", "nudge_count INTEGER DEFAULT 0;");
            addColumnIfMissing("play_campaigns", "deadline INTEGER DEFAULT 1;");
            addColumnIfMissing("play_campaigns", "story TEXT DEFAULT '';");
            addColumnIfMissing("play_campaigns", "dm_notes TEXT DEFAULT '';");
            addColumnIfMissing("play_campaigns", "current_scene_id TEXT;");
            addColumnIfMissing("play_campaign_narrations", "encounter_id TEXT;");
            addColumnIfMissing("play_campaign_narrations", "target TEXT;");
            addColumnIfMissing("play_campaigns", "current_location_id TEXT;");
            addColumnIfMissing("play_campaigns", "pre_combat_actor TEXT;");
            addColumnIfMissing("play_campaigns", "phase TEXT DEFAULT 'turn';");
            addColumnIfMissing("play_campaign_members", "hp_current INTEGER NOT NULL DEFAULT 20;");
            addColumnIfMissing("play_campaign_members", "hp_max INTEGER NOT NULL DEFAULT 20;");
            addColumnIfMissing("play_campaign_members", "status TEXT NOT NULL DEFAULT 'conscious';");
            addColumnIfMissing("play_campaign_members", "death_save_successes INTEGER NOT NULL DEFAULT 0;");
            addColumnIfMissing("play_campaign_members", "death_save_failures INTEGER NOT NULL DEFAULT 0;");
            addColumnIfMissing("play_campaign_encounters", "round INTEGER NOT NULL DEFAULT 1;");
            addColumnIfMissing("play_campaign_encounters", "turn_index INTEGER NOT NULL DEFAULT 0;");
            addColumnIfMissing("play_campaign_encounters", "xp_awarded INTEGER NOT NULL DEFAULT 0;");
            addColumnIfMissing("play_campaign_encounters", "rewards_awarded INTEGER NOT NULL DEFAULT 0;");
            addColumnIfMissing("play_campaign_encounter_monsters", "sort_order INTEGER NOT NULL DEFAULT 0;");
            addColumnIfMissing("play_campaign_encounter_combatants", "sort_order INTEGER NOT NULL DEFAULT 0;");
            addColumnIfMissing("play_campaign_members", "owner TEXT;");
            addColumnIfMissing("play_campaign_members", "race TEXT;");
            addColumnIfMissing("play_campaign_members", "background TEXT;");
            addColumnIfMissing("play_campaign_members", "level INTEGER DEFAULT 1;");
            addColumnIfMissing("play_campaign_members", "abilities TEXT;");
            addColumnIfMissing("play_campaign_members", "gold INTEGER NOT NULL DEFAULT 10;");
            addColumnIfMissing("play_campaign_quests", "reward_xp INTEGER NOT NULL DEFAULT 0;");
            addColumnIfMissing("play_campaign_quests", "reward_items TEXT NOT NULL DEFAULT '{}';");
            addColumnIfMissing("play_campaign_quests", "rewards_configured INTEGER NOT NULL DEFAULT 0;");
            addColumnIfMissing("play_campaign_quests", "rewards_awarded INTEGER NOT NULL DEFAULT 0;");
            execSql(
                "CREATE TABLE IF NOT EXISTS play_campaign_delegations (campaign_id TEXT NOT NULL, username TEXT NOT NULL, powers_json TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (campaign_id, username));",
                "CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (campaign_id TEXT NOT NULL, username TEXT NOT NULL, action TEXT NOT NULL, powers_json TEXT NOT NULL);",
                "CREATE TABLE IF NOT EXISTS play_campaign_audit_events (campaign_id TEXT NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL, role TEXT NOT NULL, timestamp INTEGER NOT NULL, correlation_id TEXT NOT NULL, PRIMARY KEY (campaign_id, correlation_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_projection_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, value TEXT NOT NULL, idempotency_key TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id), UNIQUE (campaign_id, idempotency_key));",
                "CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_state (campaign_id TEXT PRIMARY KEY, current_turn INTEGER NOT NULL DEFAULT 1);",
                "CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (campaign_id TEXT NOT NULL, submission_id TEXT NOT NULL, action TEXT NOT NULL, accepted_turn INTEGER NOT NULL, next_turn INTEGER NOT NULL, PRIMARY KEY (campaign_id, submission_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, amount INTEGER NOT NULL, from_gold INTEGER NOT NULL, to_gold INTEGER NOT NULL, PRIMARY KEY (campaign_id, sequence));",
                "CREATE TABLE IF NOT EXISTS play_campaign_exports (campaign_id TEXT NOT NULL, version INTEGER NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, version));",
                "CREATE TABLE IF NOT EXISTS play_campaign_imports (campaign_id TEXT PRIMARY KEY, version INTEGER NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL);",
                "CREATE TABLE IF NOT EXISTS play_campaign_migrations (campaign_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, story TEXT NOT NULL, campaign_name TEXT NOT NULL);",
                "CREATE TABLE IF NOT EXISTS play_campaign_search_records (campaign_id TEXT NOT NULL, record_id TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, record_id), UNIQUE (campaign_id, text));",
                "CREATE TABLE IF NOT EXISTS play_campaign_rate_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, actor TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, event_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_metrics (campaign_id TEXT PRIMARY KEY, accepted_rate_events INTEGER NOT NULL DEFAULT 0, rejected_rate_events INTEGER NOT NULL DEFAULT 0, projection_events INTEGER NOT NULL DEFAULT 0, uptime_ticks INTEGER NOT NULL DEFAULT 1);",
                "CREATE TABLE IF NOT EXISTS play_campaign_backups (campaign_id TEXT NOT NULL, backup_id TEXT NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, backup_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_replay_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, event_id), UNIQUE (campaign_id, sequence));",
                "CREATE TABLE IF NOT EXISTS play_campaign_rng_seed (campaign_id TEXT PRIMARY KEY, seed TEXT NOT NULL);",
                "CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (campaign_id TEXT NOT NULL, roll_id TEXT NOT NULL, sides INTEGER NOT NULL, result INTEGER NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, roll_id), UNIQUE (campaign_id, sequence));",
                "CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports (campaign_id TEXT NOT NULL, report_id TEXT NOT NULL, target_id TEXT NOT NULL, reason TEXT NOT NULL, reporter TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', action TEXT, note TEXT, resolver TEXT, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, report_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries (campaign_id TEXT PRIMARY KEY, tags_json TEXT NOT NULL DEFAULT '[]');",
                "CREATE TABLE IF NOT EXISTS play_campaign_safety_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, tags_json TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, event_id), UNIQUE (campaign_id, sequence));",
"CREATE TABLE IF NOT EXISTS play_campaign_spectators (spectator_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL);",
                "CREATE TABLE IF NOT EXISTS play_campaign_fixtures (campaign_id TEXT PRIMARY KEY, fixture_id TEXT NOT NULL, status TEXT NOT NULL, story TEXT NOT NULL);",
                "CREATE TABLE IF NOT EXISTS play_campaign_fixture_characters (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, name TEXT NOT NULL, class TEXT NOT NULL, sort_order INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_fixture_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, sort_order INTEGER NOT NULL, PRIMARY KEY (campaign_id, event_id));",
                "CREATE TABLE IF NOT EXISTS play_campaign_feed_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, text TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, event_id), UNIQUE (campaign_id, sequence));"
            );
            initialized = true;
        }
    }

    public void reset() {
        synchronized (lock) {
            execSql(
                "DROP TABLE IF EXISTS items;",
                "DROP TABLE IF EXISTS monster_tags;",
                "DROP TABLE IF EXISTS monsters;",
                "DROP TABLE IF EXISTS conditions;",
                "DROP TABLE IF EXISTS combatants;",
                "DROP TABLE IF EXISTS combat_sessions;",
                "DROP TABLE IF EXISTS users;",
                "DROP TABLE IF EXISTS campaigns;",
                "DROP TABLE IF EXISTS campaign_characters;",
                "DROP TABLE IF EXISTS campaign_events;",
                "DROP TABLE IF EXISTS quest_milestones;",
                "DROP TABLE IF EXISTS quests;",
                "DROP TABLE IF EXISTS npcs;",
                "DROP TABLE IF EXISTS factions;",
                "DROP TABLE IF EXISTS character_equipment;",
                "DROP TABLE IF EXISTS campaign_inventory;",
                "DROP TABLE IF EXISTS downtime_crafting_projects;",
                "DROP TABLE IF EXISTS session_attendance;",
                "DROP TABLE IF EXISTS sessions;",
                "DROP TABLE IF EXISTS play_campaigns;",
                "DROP TABLE IF EXISTS play_campaign_members;",
                "DROP TABLE IF EXISTS play_campaign_narrations;",
                "DROP TABLE IF EXISTS play_campaign_scenes;",
                "DROP TABLE IF EXISTS play_campaign_locations;",
                "DROP TABLE IF EXISTS play_campaign_location_connections;",
                "DROP TABLE IF EXISTS play_campaign_encounter_readies;",
                "DROP TABLE IF EXISTS play_campaign_encounter_conditions;",
                "DROP TABLE IF EXISTS play_campaign_encounter_loot;",
                "DROP TABLE IF EXISTS play_campaign_encounter_combatants;",
                "DROP TABLE IF EXISTS play_campaign_encounter_monsters;",
                "DROP TABLE IF EXISTS play_campaign_encounters;",
                "DROP TABLE IF EXISTS play_campaign_character_prepared_spells;",
                "DROP TABLE IF EXISTS play_campaign_character_spells;",
                "DROP TABLE IF EXISTS play_campaign_character_casts;",
                "DROP TABLE IF EXISTS play_campaign_character_concentration;",
                "DROP TABLE IF EXISTS play_campaign_character_inventory;",
                "DROP TABLE IF EXISTS play_campaign_character_equipment;",
                "DROP TABLE IF EXISTS play_campaign_transfers;",
                "DROP TABLE IF EXISTS play_campaign_loot_votes;",
                "DROP TABLE IF EXISTS play_campaign_loot;",
                "DROP TABLE IF EXISTS play_campaign_npcs;",
                "DROP TABLE IF EXISTS play_campaign_factions;",
                "DROP TABLE IF EXISTS play_campaign_reputation_history;",
                "DROP TABLE IF EXISTS play_campaign_npc_dialogue;",
                "DROP TABLE IF EXISTS play_campaign_relationships;",
                "DROP TABLE IF EXISTS play_campaign_clues;",
                "DROP TABLE IF EXISTS play_campaign_world_events;",
                "DROP TABLE IF EXISTS play_campaign_quest_rewards;",
                "DROP TABLE IF EXISTS play_campaign_quest_dependencies;",
                "DROP TABLE IF EXISTS play_campaign_quests;",
                "DROP TABLE IF EXISTS play_campaign_calendars;",
                "DROP TABLE IF EXISTS play_campaign_settlement_discoveries;",
                "DROP TABLE IF EXISTS play_campaign_shops;",
                "DROP TABLE IF EXISTS play_campaign_settlements;",
                "DROP TABLE IF EXISTS play_campaign_recipes;",
                "DROP TABLE IF EXISTS play_campaign_downtime_activities;",
                "DROP TABLE IF EXISTS play_campaign_downtime_allocations;",
                "DROP TABLE IF EXISTS play_campaign_session_zero;",
                "DROP TABLE IF EXISTS play_campaign_content;",
                "DROP TABLE IF EXISTS play_campaign_notes;",
                "DROP TABLE IF EXISTS play_campaign_whispers;",
                "DROP TABLE IF EXISTS play_campaign_invitations;",
                "DROP TABLE IF EXISTS play_campaign_delegations;",
                "DROP TABLE IF EXISTS play_campaign_delegation_audit;",
                "DROP TABLE IF EXISTS play_campaign_audit_events;",
                "DROP TABLE IF EXISTS play_campaign_projection_events;",
                "DROP TABLE IF EXISTS play_campaign_idempotent_events;",
                "DROP TABLE IF EXISTS play_campaign_safe_turn_state;",
                "DROP TABLE IF EXISTS play_campaign_safe_turns;",
                "DROP TABLE IF EXISTS play_campaign_transactional_transfers;",
                "DROP TABLE IF EXISTS play_campaign_exports;",
                "DROP TABLE IF EXISTS play_campaign_imports;",
                "DROP TABLE IF EXISTS play_campaign_migrations;",
                "DROP TABLE IF EXISTS play_campaign_search_records;",
                "DROP TABLE IF EXISTS play_campaign_rate_events;",
                "DROP TABLE IF EXISTS play_campaign_metrics;",
                "DROP TABLE IF EXISTS play_campaign_backups;",
                "DROP TABLE IF EXISTS play_campaign_replay_events;",
                "DROP TABLE IF EXISTS play_campaign_rng_rolls;",
                "DROP TABLE IF EXISTS play_campaign_rng_seed;",
                "DROP TABLE IF EXISTS play_campaign_moderation_reports;",
                "DROP TABLE IF EXISTS play_campaign_safety_boundaries;",
                "DROP TABLE IF EXISTS play_campaign_safety_events;",
                "DROP TABLE IF EXISTS play_campaign_feed_events;",
                "DROP TABLE IF EXISTS play_campaign_fixture_characters;",
                "DROP TABLE IF EXISTS play_campaign_fixture_events;",
                "DROP TABLE IF EXISTS play_campaign_fixtures;",
                "DROP TABLE IF EXISTS play_campaign_spectators;"
            );
            init();
        }
    }

    public Map<String, Object> status() {
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("driver", "sqlite");
        res.put("schema_version", 1);
        res.put("initialized", initialized);
        return res;
    }

    public User getUser(String username) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT username, role, salt, hash FROM users WHERE username = " + quote(username) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            return new User((String) row.get("username"), (String) row.get("role"), (String) row.get("salt"), (String) row.get("hash"));
        }
    }

    public boolean insertUser(User user) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO users (username, role, salt, hash) VALUES (" + quote(user.username) + ", " + quote(user.role) + ", " + quote(user.salt) + ", " + quote(user.hash) + ");",
                "COMMIT;"
            );
        }
    }

    public boolean insertCombatSession(CombatSession session) {
        synchronized (lock) {
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("INSERT INTO combat_sessions (id, round, turn_index) VALUES (" + quote(session.id) + ", " + session.round + ", " + session.turnIndex + ");");
            for (int i = 0; i < session.order.size(); i++) {
                Combatant c = session.order.get(i);
                sqls.add("INSERT INTO combatants (session_id, name, score, dex, roll, sort_order) VALUES (" + quote(session.id) + ", " + quote(c.name) + ", " + c.score + ", " + c.dex + ", " + c.roll + ", " + i + ");");
            }
            sqls.add("COMMIT;");
            return executeInsert(sqls);
        }
    }

    public CombatSession getCombatSession(String id) {
        synchronized (lock) {
            List<Map<String, Object>> sessionRows = query("SELECT id, round, turn_index FROM combat_sessions WHERE id = " + quote(id) + ";");
            if (sessionRows.isEmpty()) return null;
            Map<String, Object> sessionRow = sessionRows.get(0);

            List<Combatant> combatants = new ArrayList<>();
            List<Map<String, Object>> combatantRows = query("SELECT name, score, dex, roll FROM combatants WHERE session_id = " + quote(id) + " ORDER BY sort_order;");
            for (Map<String, Object> row : combatantRows) {
                combatants.add(new Combatant((String) row.get("name"), JsonUtils.toInt(row.get("score")), JsonUtils.toInt(row.get("dex")), JsonUtils.toInt(row.get("roll"))));
            }

            CombatSession session = new CombatSession((String) sessionRow.get("id"), combatants);
            session.round = JsonUtils.toInt(sessionRow.get("round"));
            session.turnIndex = JsonUtils.toInt(sessionRow.get("turn_index"));

            List<Map<String, Object>> conditionRows = query("SELECT target, condition, remaining_rounds FROM conditions WHERE session_id = " + quote(id) + " ORDER BY id;");
            for (Map<String, Object> row : conditionRows) {
                String target = (String) row.get("target");
                session.conditions.computeIfAbsent(target, k -> new ArrayList<>()).add(new Condition((String) row.get("condition"), JsonUtils.toInt(row.get("remaining_rounds"))));
            }

            return session;
        }
    }

    public void addCondition(String sessionId, String target, String condition, int duration) {
        synchronized (lock) {
            execSql("INSERT INTO conditions (session_id, target, condition, remaining_rounds) VALUES (" + quote(sessionId) + ", " + quote(target) + ", " + quote(condition) + ", " + duration + ");");
        }
    }

    public void advanceCombatSession(CombatSession session, Combatant active) {
        synchronized (lock) {
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("UPDATE combat_sessions SET round = " + session.round + ", turn_index = " + session.turnIndex + " WHERE id = " + quote(session.id) + ";");
            sqls.add("UPDATE conditions SET remaining_rounds = remaining_rounds - 1 WHERE session_id = " + quote(session.id) + " AND target = " + quote(active.name) + ";");
            sqls.add("DELETE FROM conditions WHERE session_id = " + quote(session.id) + " AND target = " + quote(active.name) + " AND remaining_rounds <= 0;");
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));
        }
    }

    public boolean insertMonster(String slug, String name, String cr, int armorClass, int hitPoints, List<String> tags) {
        synchronized (lock) {
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("INSERT INTO monsters (slug, name, cr, armor_class, hit_points) VALUES (" + quote(slug) + ", " + quote(name) + ", " + quote(cr) + ", " + armorClass + ", " + hitPoints + ");");
            Set<String> seen = new HashSet<>();
            for (String tag : tags) {
                if (!seen.add(tag)) continue;
                sqls.add("INSERT INTO monster_tags (monster_slug, tag) VALUES (" + quote(slug) + ", " + quote(tag) + ");");
            }
            sqls.add("COMMIT;");
            return executeInsert(sqls);
        }
    }

    public Map<String, Object> getMonster(String slug) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT slug, name, cr, armor_class, hit_points FROM monsters WHERE slug = " + quote(slug) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            List<String> tags = new ArrayList<>();
            List<Map<String, Object>> tagRows = query("SELECT tag FROM monster_tags WHERE monster_slug = " + quote(slug) + " ORDER BY rowid;");
            for (Map<String, Object> tr : tagRows) {
                tags.add((String) tr.get("tag"));
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("slug", row.get("slug"));
            res.put("name", row.get("name"));
            res.put("cr", row.get("cr"));
            res.put("armor_class", JsonUtils.toInt(row.get("armor_class")));
            res.put("hit_points", JsonUtils.toInt(row.get("hit_points")));
            res.put("tags", tags);
            return res;
        }
    }

    public boolean insertItem(String slug, String name, String type, String rarity, int costGp) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (" + quote(slug) + ", " + quote(name) + ", " + quote(type) + ", " + quote(rarity) + ", " + costGp + ");",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getItem(String slug) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = " + quote(slug) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("slug", row.get("slug"));
            res.put("name", row.get("name"));
            res.put("type", row.get("type"));
            res.put("rarity", row.get("rarity"));
            res.put("cost_gp", JsonUtils.toInt(row.get("cost_gp")));
            return res;
        }
    }

    public boolean insertCampaign(String id, String name, String dm) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO campaigns (id, name, dm) VALUES (" + quote(id) + ", " + quote(name) + ", " + quote(dm) + ");",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getCampaign(String id) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, name, dm FROM campaigns WHERE id = " + quote(id) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", row.get("id"));
            res.put("name", row.get("name"));
            res.put("dm", row.get("dm"));
            return res;
        }
    }

    public boolean insertPlayCampaign(String id, String name, String owner, int maxPlayers) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (" + quote(id) + ", " + quote(name) + ", " + quote(owner) + ", 'lobby', " + maxPlayers + ");",
                "INSERT INTO play_campaign_metrics (campaign_id, accepted_rate_events, rejected_rate_events, projection_events, uptime_ticks) VALUES (" + quote(id) + ", 0, 0, 0, 1);",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaign(String id) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, name, owner, status, max_players FROM play_campaigns WHERE id = " + quote(id) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", row.get("id"));
            res.put("name", row.get("name"));
            res.put("owner", row.get("owner"));
            res.put("status", row.get("status"));
            res.put("max_players", JsonUtils.toInt(row.get("max_players")));
            return res;
        }
    }

    public Map<String, Object> getPlayCampaignDocument(String id) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT story, dm_notes FROM play_campaigns WHERE id = " + quote(id) + ";");
            if (rows.isEmpty()) return null;
            return rows.get(0);
        }
    }

    public void updatePlayCampaignDocument(String id, String story, String dmNotes) {
        synchronized (lock) {
            execSql("UPDATE play_campaigns SET story = " + quote(story) + ", dm_notes = " + quote(dmNotes) + " WHERE id = " + quote(id) + ";");
        }
    }

    public Map<String, Object> getPlayCampaignTurn(String id) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, name, owner, status, current_actor, turn_number, nudge_count, deadline, current_location_id, phase FROM play_campaigns WHERE id = " + quote(id) + ";");
            if (rows.isEmpty()) return null;
            return rows.get(0);
        }
    }

    public boolean isPlayCampaignMember(String campaignId, String username) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT 1 FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " AND username = " + quote(username) + ";");
            return !rows.isEmpty();
        }
    }

    public boolean insertPlayCampaignMember(String campaignId, String username, String characterId, String name, String className) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, owner, hp_current, hp_max, status, death_save_successes, death_save_failures) VALUES (" + quote(campaignId) + ", " + quote(username) + ", " + quote(characterId) + ", " + quote(name) + ", " + quote(className) + ", " + quote(username) + ", 20, 20, 'conscious', 0, 0);",
                "COMMIT;"
            );
        }
    }

    public String getPlayCampaignCharacterOwner(String campaignId, String characterId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT owner FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            if (rows.isEmpty()) return null;
            return (String) rows.get(0).get("owner");
        }
    }

    public boolean setPlayCampaignCharacterOwner(String campaignId, String characterId, String owner) {
        synchronized (lock) {
            execSql("UPDATE play_campaign_members SET owner = " + (owner == null ? "NULL" : quote(owner)) + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            return true;
        }
    }

    public int countPlayCampaignMembers(String campaignId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + ";");
        }
    }

    public List<Map<String, Object>> listPlayCampaignMembers(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT username, character_id, name, class FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " ORDER BY username;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("username", row.get("username"));
                m.put("character_id", row.get("character_id"));
                m.put("name", row.get("name"));
                m.put("class", row.get("class"));
                res.add(m);
            }
            return res;
        }
    }

    public Map<String, Object> getPlayCampaignMember(String campaignId, String username) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT character_id, name, class FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " AND username = " + quote(username) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("character_id", row.get("character_id"));
            m.put("name", row.get("name"));
            m.put("class", row.get("class"));
            return m;
        }
    }

    public List<Map<String, Object>> listPlayCampaignNarrations(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT sequence, kind, actor, type, target, text FROM play_campaign_narrations WHERE campaign_id = " + quote(campaignId) + " ORDER BY sequence;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> n = new LinkedHashMap<>();
                n.put("sequence", JsonUtils.toInt(row.get("sequence")));
                n.put("kind", row.get("kind"));
                n.put("actor", row.get("actor"));
                Object type = row.get("type");
                if (type != null) n.put("type", type);
                Object target = row.get("target");
                if (target != null) n.put("target", target);
                n.put("text", row.get("text"));
                res.add(n);
            }
            return res;
        }
    }

    public boolean startPlayCampaign(String campaignId, String currentActor) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "UPDATE play_campaigns SET status = 'active', current_actor = " + quote(currentActor) + ", turn_number = 1, nudge_count = 0, deadline = 2 WHERE id = " + quote(campaignId) + " AND status = 'lobby';",
                    "COMMIT;"
                );
                Map<String, Object> campaign = getPlayCampaign(campaignId);
                return campaign != null && "active".equals(campaign.get("status"));
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public Map<String, Object> insertPlayCampaignNarration(String campaignId, String actor, String text) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_narrations WHERE campaign_id = " + quote(campaignId) + ";");
            int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
            execSql(
                "BEGIN;",
                "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (" + quote(campaignId) + ", " + nextSeq + ", 'narration', " + quote(actor) + ", NULL, " + quote(text) + ");",
                "COMMIT;"
            );
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("sequence", nextSeq);
            res.put("kind", "narration");
            res.put("actor", actor);
            res.put("text", text);
            return res;
        }
    }

    public Map<String, Object> insertPlayCampaignChatEvent(String campaignId, String actor, String text) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_narrations WHERE campaign_id = " + quote(campaignId) + ";");
            int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
            execSql(
                "BEGIN;",
                "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (" + quote(campaignId) + ", " + nextSeq + ", 'chat', " + quote(actor) + ", NULL, " + quote(text) + ");",
                "COMMIT;"
            );
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("sequence", nextSeq);
            res.put("kind", "chat");
            res.put("actor", actor);
            res.put("text", text);
            return res;
        }
    }

    public Map<String, Object> submitPlayCampaignAction(String campaignId, String actor, String type, String text, String nextActor) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_narrations WHERE campaign_id = " + quote(campaignId) + ";");
            int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (" + quote(campaignId) + ", " + nextSeq + ", 'action', " + quote(actor) + ", " + quote(type) + ", " + quote(text) + ");");
            sqls.add("UPDATE play_campaigns SET current_actor = " + quote(nextActor) + ", deadline = turn_number + 2 WHERE id = " + quote(campaignId) + ";");
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("sequence", nextSeq);
            res.put("kind", "action");
            res.put("actor", actor);
            res.put("type", type);
            res.put("text", text);
            return res;
        }
    }

    public String getMostRecentActionActor(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT actor FROM play_campaign_narrations WHERE campaign_id = " + quote(campaignId) + " AND kind = 'action' ORDER BY sequence DESC LIMIT 1;");
            if (rows.isEmpty()) return null;
            return (String) rows.get(0).get("actor");
        }
    }

    public String getMostRecentPlayerEventActor(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT actor FROM play_campaign_narrations WHERE campaign_id = " + quote(campaignId) + " AND kind IN ('action','travel') ORDER BY sequence DESC LIMIT 1;");
            if (rows.isEmpty()) return null;
            return (String) rows.get(0).get("actor");
        }
    }

    public Map<String, Object> submitPlayCampaignResolution(String campaignId, String actor, String text, String nextActor) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_narrations WHERE campaign_id = " + quote(campaignId) + ";");
            int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
            List<Map<String, Object>> turnRows = query("SELECT turn_number FROM play_campaigns WHERE id = " + quote(campaignId) + ";");
            int currentTurn = turnRows.isEmpty() ? 1 : JsonUtils.toInt(turnRows.get(0).get("turn_number"));
            int nextTurn = currentTurn + 1;
            int deadline = nextTurn + 1;
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (" + quote(campaignId) + ", " + nextSeq + ", 'resolution', " + quote(actor) + ", NULL, " + quote(text) + ");");
            sqls.add("UPDATE play_campaigns SET current_actor = " + quote(nextActor) + ", turn_number = " + nextTurn + ", deadline = " + deadline + " WHERE id = " + quote(campaignId) + ";");
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("sequence", nextSeq);
            res.put("kind", "resolution");
            res.put("actor", actor);
            res.put("text", text);
            return res;
        }
    }

    public Map<String, Object> submitPlayCampaignTravel(String campaignId, String actor, String destinationId, int travelTurns, String nextActor) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_narrations WHERE campaign_id = " + quote(campaignId) + ";");
            int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (" + quote(campaignId) + ", " + nextSeq + ", 'travel', " + quote(actor) + ", NULL, '');");
            sqls.add("UPDATE play_campaigns SET current_actor = " + quote(nextActor) + ", current_location_id = " + quote(destinationId) + ", deadline = turn_number + 2 WHERE id = " + quote(campaignId) + ";");
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("sequence", nextSeq);
            res.put("kind", "travel");
            res.put("actor", actor);
            res.put("destination_id", destinationId);
            res.put("travel_turns", travelTurns);
            return res;
        }
    }

    public Map<String, Object> submitPlayCampaignEncounterAction(String campaignId, String encounterId, String actor, String type, String target, String text) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_narrations WHERE campaign_id = " + quote(campaignId) + ";");
            int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
            execSql(
                "BEGIN;",
                "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, type, text, encounter_id, target) VALUES (" + quote(campaignId) + ", " + nextSeq + ", 'combat_action', " + quote(actor) + ", " + quote(type) + ", " + quote(text) + ", " + quote(encounterId) + ", " + quote(target) + ");",
                "COMMIT;"
            );
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("sequence", nextSeq);
            res.put("kind", "combat_action");
            res.put("actor", actor);
            res.put("type", type);
            res.put("target", target);
            res.put("text", text);
            return res;
        }
    }

    public Map<String, Object> submitPlayCampaignRest(String campaignId, String actor, String restType, String nextActor) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT hp_current, hp_max, status FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " AND username = " + quote(actor) + ";");
            if (rows.isEmpty()) return null;
            int hpCurrent = JsonUtils.toInt(rows.get(0).get("hp_current"));
            int hpMax = JsonUtils.toInt(rows.get(0).get("hp_max"));
            String status = (String) rows.get(0).get("status");
            if ("long".equals(restType)) {
                hpCurrent = hpMax;
            }
            String newStatus = status;
            int successes = 0;
            int failures = 0;
            if (!"dead".equals(status) && hpCurrent > 0) {
                newStatus = "conscious";
            }
            rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_narrations WHERE campaign_id = " + quote(campaignId) + ";");
            int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (" + quote(campaignId) + ", " + nextSeq + ", 'rest', " + quote(actor) + ", " + quote(restType) + ", '');");
            sqls.add("UPDATE play_campaigns SET current_actor = " + quote(nextActor) + ", deadline = turn_number + 2 WHERE id = " + quote(campaignId) + ";");
            sqls.add("UPDATE play_campaign_members SET hp_current = " + hpCurrent + ", status = " + quote(newStatus) + ", death_save_successes = " + successes + ", death_save_failures = " + failures + " WHERE campaign_id = " + quote(campaignId) + " AND username = " + quote(actor) + ";");
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("sequence", nextSeq);
            res.put("kind", "rest");
            res.put("actor", actor);
            res.put("type", restType);
            res.put("hp_current", hpCurrent);
            res.put("hp_max", hpMax);
            res.put("next_actor", nextActor);
            return res;
        }
    }

    public int nudgePlayCampaign(String campaignId, String actor, String message) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_narrations WHERE campaign_id = " + quote(campaignId) + ";");
            int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
            execSql(
                "BEGIN;",
                "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (" + quote(campaignId) + ", " + nextSeq + ", 'nudge', " + quote(actor) + ", NULL, " + quote(message) + ");",
                "UPDATE play_campaigns SET nudge_count = nudge_count + 1 WHERE id = " + quote(campaignId) + ";",
                "COMMIT;"
            );
            rows = query("SELECT nudge_count FROM play_campaigns WHERE id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return 0;
            return JsonUtils.toInt(rows.get(0).get("nudge_count"));
        }
    }

    public boolean insertPlayCampaignScene(String campaignId, String sceneId, String name) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_scenes (campaign_id, scene_id, name, status) VALUES (" + quote(campaignId) + ", " + quote(sceneId) + ", " + quote(name) + ", 'open');",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignScene(String campaignId, String sceneId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT scene_id, name, status FROM play_campaign_scenes WHERE campaign_id = " + quote(campaignId) + " AND scene_id = " + quote(sceneId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", row.get("scene_id"));
            res.put("name", row.get("name"));
            res.put("status", row.get("status"));
            return res;
        }
    }

    public boolean setPlayCampaignCurrentScene(String campaignId, String actor, String sceneId) {
        synchronized (lock) {
            try {
                List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_narrations WHERE campaign_id = " + quote(campaignId) + ";");
                int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
                execSql(
                    "BEGIN;",
                    "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (" + quote(campaignId) + ", " + nextSeq + ", 'scene', " + quote(actor) + ", NULL, " + quote(sceneId) + ");",
                    "UPDATE play_campaigns SET current_scene_id = " + (sceneId == null ? "NULL" : quote(sceneId)) + " WHERE id = " + quote(campaignId) + ";",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public boolean closePlayCampaignScene(String campaignId, String sceneId) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "UPDATE play_campaign_scenes SET status = 'closed' WHERE campaign_id = " + quote(campaignId) + " AND scene_id = " + quote(sceneId) + ";",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public Map<String, Object> getPlayCampaignCurrentScene(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query(
                "SELECT s.scene_id, s.name, s.status FROM play_campaigns p " +
                "JOIN play_campaign_scenes s ON p.current_scene_id = s.scene_id " +
                "WHERE p.id = " + quote(campaignId) + ";"
            );
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", row.get("scene_id"));
            res.put("name", row.get("name"));
            res.put("status", row.get("status"));
            return res;
        }
    }

    public boolean insertPlayCampaignLocation(String campaignId, String locationId, String name) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_locations (campaign_id, location_id, name) VALUES (" + quote(campaignId) + ", " + quote(locationId) + ", " + quote(name) + ");",
                "UPDATE play_campaigns SET current_location_id = " + quote(locationId) + " WHERE id = " + quote(campaignId) + " AND current_location_id IS NULL;",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignLocation(String campaignId, String locationId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT location_id, name FROM play_campaign_locations WHERE campaign_id = " + quote(campaignId) + " AND location_id = " + quote(locationId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", row.get("location_id"));
            res.put("name", row.get("name"));
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignLocations(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT location_id, name FROM play_campaign_locations WHERE campaign_id = " + quote(campaignId) + " ORDER BY location_id;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("id", row.get("location_id"));
                m.put("name", row.get("name"));
                res.add(m);
            }
            return res;
        }
    }

    public boolean insertPlayCampaignConnection(String campaignId, String fromId, String toId, int travelTurns) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (" + quote(campaignId) + ", " + quote(fromId) + ", " + quote(toId) + ", " + travelTurns + ");",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignConnection(String campaignId, String fromId, String toId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT from_id, to_id, travel_turns FROM play_campaign_location_connections WHERE campaign_id = " + quote(campaignId) + " AND from_id = " + quote(fromId) + " AND to_id = " + quote(toId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("from_id", row.get("from_id"));
            res.put("to_id", row.get("to_id"));
            res.put("travel_turns", JsonUtils.toInt(row.get("travel_turns")));
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignConnectionsFrom(String campaignId, String fromId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query(
                "SELECT c.to_id, l.name, c.travel_turns FROM play_campaign_location_connections c " +
                "JOIN play_campaign_locations l ON c.campaign_id = l.campaign_id AND c.to_id = l.location_id " +
                "WHERE c.campaign_id = " + quote(campaignId) + " AND c.from_id = " + quote(fromId) + " ORDER BY c.to_id;"
            );
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("id", row.get("to_id"));
                m.put("name", row.get("name"));
                m.put("travel_turns", JsonUtils.toInt(row.get("travel_turns")));
                res.add(m);
            }
            return res;
        }
    }

    public boolean hasActivePlayCampaignEncounter(String campaignId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_encounters WHERE campaign_id = " + quote(campaignId) + " AND status = 'active';") > 0;
        }
    }

    public boolean insertPlayCampaignEncounter(String campaignId, String encounterId, String name) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_encounters (campaign_id, encounter_id, name, status, round, turn_index) VALUES (" + quote(campaignId) + ", " + quote(encounterId) + ", " + quote(name) + ", 'active', 1, 0);",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignEncounterTurn(String campaignId, String encounterId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT encounter_id, name, status, round, turn_index FROM play_campaign_encounters WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + ";");
            if (rows.isEmpty()) return null;
            return rows.get(0);
        }
    }

    public List<Map<String, Object>> listPlayCampaignEncounterCombatants(String campaignId, String encounterId) {
        synchronized (lock) {
            return query(
                "SELECT id, name, kind, initiative, controller, sort_order FROM (" +
                "SELECT monster_id AS id, name, 'monster' AS kind, initiative, NULL AS controller, sort_order FROM play_campaign_encounter_monsters WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) +
                " UNION ALL " +
                "SELECT member AS id, name, 'player' AS kind, initiative, member AS controller, sort_order FROM play_campaign_encounter_combatants WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) +
                ") ORDER BY sort_order ASC, initiative DESC, name ASC;"
            );
        }
    }

    public void advancePlayCampaignEncounterTurn(String campaignId, String encounterId, int round, int turnIndex, String activeTarget) {
        synchronized (lock) {
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("UPDATE play_campaign_encounters SET round = " + round + ", turn_index = " + turnIndex + " WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + ";");
            if (activeTarget != null) {
                sqls.add("UPDATE play_campaign_encounter_conditions SET remaining_rounds = remaining_rounds - 1 WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + " AND target = " + quote(activeTarget) + ";");
                sqls.add("DELETE FROM play_campaign_encounter_conditions WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + " AND target = " + quote(activeTarget) + " AND remaining_rounds <= 0;");
            }
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));
        }
    }

    public void addPlayCampaignEncounterCondition(String campaignId, String encounterId, String target, String condition, int remainingRounds) {
        synchronized (lock) {
            execSql("INSERT INTO play_campaign_encounter_conditions (campaign_id, encounter_id, target, condition, remaining_rounds) VALUES (" + quote(campaignId) + ", " + quote(encounterId) + ", " + quote(target) + ", " + quote(condition) + ", " + remainingRounds + ") ON CONFLICT(campaign_id, encounter_id, target, condition) DO UPDATE SET remaining_rounds = " + remainingRounds + ";");
        }
    }

    public Map<String, List<Map<String, Object>>> listPlayCampaignEncounterConditions(String campaignId, String encounterId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT target, condition, remaining_rounds FROM play_campaign_encounter_conditions WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + " ORDER BY rowid;");
            Map<String, List<Map<String, Object>>> result = new LinkedHashMap<>();
            for (Map<String, Object> row : rows) {
                String target = (String) row.get("target");
                Map<String, Object> c = new LinkedHashMap<>();
                c.put("condition", row.get("condition"));
                c.put("remaining_rounds", JsonUtils.toInt(row.get("remaining_rounds")));
                result.computeIfAbsent(target, k -> new ArrayList<>()).add(c);
            }
            return result;
        }
    }

    public Map<String, Object> getPlayCampaignEncounter(String campaignId, String encounterId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT encounter_id, name, status FROM play_campaign_encounters WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", row.get("encounter_id"));
            res.put("name", row.get("name"));
            res.put("status", row.get("status"));
            res.put("combatants", listPlayCampaignEncounterMonsters(campaignId, encounterId));
            return res;
        }
    }

    public boolean awardEncounterRewards(String campaignId, String encounterId, int xp, List<Map<String, Object>> loot) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT rewards_awarded FROM play_campaign_encounters WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + ";");
            if (rows.isEmpty()) return false;
            if (JsonUtils.toInt(rows.get(0).get("rewards_awarded")) != 0) return false;
            Map<String, Integer> merged = new LinkedHashMap<>();
            for (Map<String, Object> item : loot) {
                String slug = (String) item.get("slug");
                int quantity = JsonUtils.toInt(item.get("quantity"));
                if (slug == null || slug.isEmpty() || quantity <= 0) return false;
                merged.merge(slug, quantity, Integer::sum);
            }
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("UPDATE play_campaign_encounters SET xp_awarded = " + xp + ", rewards_awarded = 1 WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + ";");
            for (Map.Entry<String, Integer> entry : merged.entrySet()) {
                String slug = entry.getKey();
                int quantity = entry.getValue();
                sqls.add("INSERT INTO play_campaign_encounter_loot (campaign_id, encounter_id, item_slug, quantity) VALUES (" + quote(campaignId) + ", " + quote(encounterId) + ", " + quote(slug) + ", " + quantity + ") ON CONFLICT(campaign_id, encounter_id, item_slug) DO UPDATE SET quantity = quantity + excluded.quantity;");
                sqls.add("INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (" + quote(campaignId) + ", " + quote(slug) + ", 'party', " + quantity + ") ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + excluded.quantity;");
            }
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));
            return true;
        }
    }

    public Map<String, Object> getEncounterRewards(String campaignId, String encounterId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT xp_awarded FROM play_campaign_encounters WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + ";");
            int xp = rows.isEmpty() ? 0 : JsonUtils.toInt(rows.get(0).get("xp_awarded"));
            List<Map<String, Object>> lootRows = query("SELECT item_slug, quantity FROM play_campaign_encounter_loot WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + " ORDER BY rowid;");
            List<Map<String, Object>> loot = new ArrayList<>();
            for (Map<String, Object> row : lootRows) {
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("slug", row.get("item_slug"));
                item.put("quantity", JsonUtils.toInt(row.get("quantity")));
                loot.add(item);
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", encounterId);
            res.put("xp", xp);
            res.put("loot", loot);
            return res;
        }
    }

    public Map<String, Object> closePlayCampaignEncounter(String campaignId, String encounterId) {
        synchronized (lock) {
            execSql(
                "BEGIN;",
                "UPDATE play_campaign_encounters SET status = 'closed' WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + ";",
                "COMMIT;"
            );
            List<Map<String, Object>> rows = query("SELECT xp_awarded FROM play_campaign_encounters WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + ";");
            int xp = rows.isEmpty() ? 0 : JsonUtils.toInt(rows.get(0).get("xp_awarded"));
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", encounterId);
            res.put("status", "closed");
            res.put("xp_awarded", xp);
            return res;
        }
    }

    public void setPreCombatActor(String campaignId, String actor) {
        synchronized (lock) {
            execSql("UPDATE play_campaigns SET pre_combat_actor = " + (actor == null ? "NULL" : quote(actor)) + " WHERE id = " + quote(campaignId) + ";");
        }
    }

    public Map<String, Object> endPlayCampaignEncounter(String campaignId, String encounterId) {
        synchronized (lock) {
            List<Map<String, Object>> encRows = query("SELECT status FROM play_campaign_encounters WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + ";");
            if (encRows.isEmpty()) return null;

            List<Map<String, Object>> campaignRows = query("SELECT owner, pre_combat_actor, current_actor FROM play_campaigns WHERE id = " + quote(campaignId) + ";");
            String owner = campaignRows.isEmpty() ? null : (String) campaignRows.get(0).get("owner");
            String preCombatActor = campaignRows.isEmpty() ? null : (String) campaignRows.get(0).get("pre_combat_actor");
            boolean encounterActive = "active".equals(encRows.get(0).get("status"));
            boolean inCombat = encounterActive || preCombatActor != null;
            if (!inCombat) return null;

            String restoredActor = preCombatActor != null ? preCombatActor : owner;

            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            if (encounterActive) {
                sqls.add("UPDATE play_campaign_encounters SET status = 'closed' WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + ";");
            }
            sqls.add("UPDATE play_campaigns SET current_actor = " + (owner == null ? "NULL" : quote(owner)) + ", pre_combat_actor = NULL, phase = 'exploration' WHERE id = " + quote(campaignId) + ";");
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("campaign_id", campaignId);
            res.put("status", "active");
            res.put("current_actor", owner);
            return res;
        }
    }

    public boolean insertPlayCampaignEncounterMonster(String campaignId, String encounterId, String monsterId, String name, int hpMax, int hpCurrent, int initiative) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_encounter_monsters (campaign_id, encounter_id, monster_id, name, hp_max, hp_current, initiative, sort_order) VALUES (" + quote(campaignId) + ", " + quote(encounterId) + ", " + quote(monsterId) + ", " + quote(name) + ", " + hpMax + ", " + hpCurrent + ", " + initiative + ", 0);",
                "COMMIT;"
            );
        }
    }

    public boolean deletePlayCampaignEncounterMonster(String campaignId, String encounterId, String monsterId) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "DELETE FROM play_campaign_encounter_monsters WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + " AND monster_id = " + quote(monsterId) + ";",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public Map<String, Object> getPlayCampaignEncounterMonster(String campaignId, String encounterId, String monsterId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT monster_id, name, hp_max, hp_current, initiative FROM play_campaign_encounter_monsters WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + " AND monster_id = " + quote(monsterId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("monster_id", row.get("monster_id"));
            res.put("name", row.get("name"));
            res.put("hp_max", JsonUtils.toInt(row.get("hp_max")));
            res.put("initiative", JsonUtils.toInt(row.get("initiative")));
            res.put("hp_current", JsonUtils.toInt(row.get("hp_current")));
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignEncounterMonsters(String campaignId, String encounterId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT monster_id, name, hp_max, hp_current, initiative FROM play_campaign_encounter_monsters WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + " ORDER BY monster_id;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("monster_id", row.get("monster_id"));
                m.put("name", row.get("name"));
                m.put("hp_max", JsonUtils.toInt(row.get("hp_max")));
                m.put("initiative", JsonUtils.toInt(row.get("initiative")));
                m.put("hp_current", JsonUtils.toInt(row.get("hp_current")));
                res.add(m);
            }
            return res;
        }
    }

    public boolean insertPlayCampaignEncounterCombatant(String campaignId, String encounterId, String member, String characterId, String name, int initiative) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_encounter_combatants (campaign_id, encounter_id, member, character_id, name, initiative, sort_order) VALUES (" + quote(campaignId) + ", " + quote(encounterId) + ", " + quote(member) + ", " + quote(characterId) + ", " + quote(name) + ", " + initiative + ", 0);",
                "COMMIT;"
            );
        }
    }

    public boolean deletePlayCampaignEncounterCombatant(String campaignId, String encounterId, String member) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "DELETE FROM play_campaign_encounter_combatants WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + " AND member = " + quote(member) + ";",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public Map<String, Object> getPlayCampaignEncounterCombatant(String campaignId, String encounterId, String member) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT member, character_id, name, initiative FROM play_campaign_encounter_combatants WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + " AND member = " + quote(member) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("member", row.get("member"));
            res.put("character_id", row.get("character_id"));
            res.put("name", row.get("name"));
            res.put("initiative", JsonUtils.toInt(row.get("initiative")));
            return res;
        }
    }

    public void delayPlayCampaignEncounter(String campaignId, String encounterId, int currentIndex, int newIndex) {
        synchronized (lock) {
            List<Map<String, Object>> combatants = listPlayCampaignEncounterCombatants(campaignId, encounterId);
            int size = combatants.size();
            if (currentIndex < 0 || currentIndex >= size || newIndex <= currentIndex || newIndex >= size) return;
            List<Map<String, Object>> reordered = new ArrayList<>(combatants);
            Map<String, Object> current = reordered.remove(currentIndex);
            reordered.add(newIndex, current);
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            for (int i = 0; i < reordered.size(); i++) {
                String id = (String) reordered.get(i).get("id");
                String kind = (String) reordered.get(i).get("kind");
                int sortOrder = i * 1000;
                if ("monster".equals(kind)) {
                    sqls.add("UPDATE play_campaign_encounter_monsters SET sort_order = " + sortOrder + " WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + " AND monster_id = " + quote(id) + ";");
                } else {
                    sqls.add("UPDATE play_campaign_encounter_combatants SET sort_order = " + sortOrder + " WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + " AND member = " + quote(id) + ";");
                }
            }
            sqls.add("UPDATE play_campaign_encounters SET turn_index = " + newIndex + " WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + ";");
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));
        }
    }

    public void insertPlayCampaignEncounterReady(String campaignId, String encounterId, String actor, String trigger) {
        synchronized (lock) {
            execSql(
                "INSERT INTO play_campaign_encounter_readies (campaign_id, encounter_id, actor, trigger) VALUES (" + quote(campaignId) + ", " + quote(encounterId) + ", " + quote(actor) + ", " + quote(trigger) + ") ON CONFLICT(campaign_id, encounter_id, actor) DO UPDATE SET trigger = " + quote(trigger) + ";"
            );
        }
    }

    public Map<String, Object> applyDamageToEncounterTarget(String campaignId, String encounterId, String target, int amount) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT hp_current, hp_max FROM play_campaign_encounter_monsters WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + " AND monster_id = " + quote(target) + ";");
            if (!rows.isEmpty()) {
                int hpBefore = JsonUtils.toInt(rows.get(0).get("hp_current"));
                int hpAfter = Math.max(0, hpBefore - amount);
                execSql("UPDATE play_campaign_encounter_monsters SET hp_current = " + hpAfter + " WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + " AND monster_id = " + quote(target) + ";");
                Map<String, Object> res = new LinkedHashMap<>();
                res.put("target", target);
                res.put("hp_before", hpBefore);
                res.put("hp_after", hpAfter);
                res.put("damage", amount);
                return res;
            }
            rows = query("SELECT m.hp_current, m.hp_max, m.status FROM play_campaign_members m JOIN play_campaign_encounter_combatants c ON m.campaign_id = c.campaign_id AND m.username = c.member WHERE c.campaign_id = " + quote(campaignId) + " AND c.encounter_id = " + quote(encounterId) + " AND c.member = " + quote(target) + ";");
            if (!rows.isEmpty()) {
                int hpBefore = JsonUtils.toInt(rows.get(0).get("hp_current"));
                int hpMax = JsonUtils.toInt(rows.get(0).get("hp_max"));
                String status = (String) rows.get(0).get("status");
                int hpAfter = Math.max(0, hpBefore - amount);
                String newStatus = status;
                int successes = 0;
                int failures = 0;
                if (!"dead".equals(status)) {
                    if (hpAfter == 0) {
                        newStatus = "unconscious";
                    } else {
                        newStatus = "conscious";
                        successes = 0;
                        failures = 0;
                    }
                }
                execSql("UPDATE play_campaign_members SET hp_current = " + hpAfter + ", status = " + quote(newStatus) + ", death_save_successes = " + successes + ", death_save_failures = " + failures + " WHERE campaign_id = " + quote(campaignId) + " AND username = " + quote(target) + ";");
                Map<String, Object> res = new LinkedHashMap<>();
                res.put("target", target);
                res.put("hp_before", hpBefore);
                res.put("hp_after", hpAfter);
                res.put("damage", amount);
                return res;
            }
            return null;
        }
    }

    public Map<String, Object> applyHealToEncounterTarget(String campaignId, String encounterId, String target, int amount) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT hp_current, hp_max FROM play_campaign_encounter_monsters WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + " AND monster_id = " + quote(target) + ";");
            if (!rows.isEmpty()) {
                int hpBefore = JsonUtils.toInt(rows.get(0).get("hp_current"));
                int hpMax = JsonUtils.toInt(rows.get(0).get("hp_max"));
                int hpAfter = Math.min(hpMax, hpBefore + amount);
                execSql("UPDATE play_campaign_encounter_monsters SET hp_current = " + hpAfter + " WHERE campaign_id = " + quote(campaignId) + " AND encounter_id = " + quote(encounterId) + " AND monster_id = " + quote(target) + ";");
                Map<String, Object> res = new LinkedHashMap<>();
                res.put("target", target);
                res.put("hp_before", hpBefore);
                res.put("hp_after", hpAfter);
                res.put("healing", amount);
                return res;
            }
            rows = query("SELECT m.hp_current, m.hp_max, m.status FROM play_campaign_members m JOIN play_campaign_encounter_combatants c ON m.campaign_id = c.campaign_id AND m.username = c.member WHERE c.campaign_id = " + quote(campaignId) + " AND c.encounter_id = " + quote(encounterId) + " AND c.member = " + quote(target) + ";");
            if (!rows.isEmpty()) {
                int hpBefore = JsonUtils.toInt(rows.get(0).get("hp_current"));
                int hpMax = JsonUtils.toInt(rows.get(0).get("hp_max"));
                String status = (String) rows.get(0).get("status");
                int hpAfter = Math.min(hpMax, hpBefore + amount);
                String newStatus = status;
                int successes = 0;
                int failures = 0;
                if (!"dead".equals(status) && hpAfter > 0) {
                    newStatus = "conscious";
                    successes = 0;
                    failures = 0;
                }
                execSql("UPDATE play_campaign_members SET hp_current = " + hpAfter + ", status = " + quote(newStatus) + ", death_save_successes = " + successes + ", death_save_failures = " + failures + " WHERE campaign_id = " + quote(campaignId) + " AND username = " + quote(target) + ";");
                Map<String, Object> res = new LinkedHashMap<>();
                res.put("target", target);
                res.put("hp_before", hpBefore);
                res.put("hp_after", hpAfter);
                res.put("healing", amount);
                return res;
            }
            return null;
        }
    }

    public boolean insertCampaignCharacter(String campaignId, String id, String name, int level, String className) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (" + quote(id) + ", " + quote(campaignId) + ", " + quote(name) + ", " + level + ", " + quote(className) + ");",
                "COMMIT;"
            );
        }
    }

    public List<Map<String, Object>> listCampaignCharacters(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = " + quote(campaignId) + " ORDER BY rowid;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> c = new LinkedHashMap<>();
                c.put("id", row.get("id"));
                c.put("name", row.get("name"));
                c.put("level", JsonUtils.toInt(row.get("level")));
                c.put("class", row.get("class"));
                res.add(c);
            }
            return res;
        }
    }

    public boolean insertCampaignEvent(String campaignId, String id, String kind, String summary) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (" + quote(id) + ", " + quote(campaignId) + ", " + quote(kind) + ", " + (summary == null ? "NULL" : quote(summary)) + ");",
                "COMMIT;"
            );
        }
    }

    public int countCampaignEvents(String campaignId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM campaign_events WHERE campaign_id = " + quote(campaignId) + ";");
        }
    }

    public int countCampaignCharacters(String campaignId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM campaign_characters WHERE campaign_id = " + quote(campaignId) + ";");
        }
    }

    public int countQuests(String campaignId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM quests WHERE campaign_id = " + quote(campaignId) + ";");
        }
    }

    public int countActiveQuests(String campaignId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM quests WHERE campaign_id = " + quote(campaignId) + " AND status = 'active';");
        }
    }

    public int countSessions(String campaignId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM sessions WHERE campaign_id = " + quote(campaignId) + ";");
        }
    }

    public int countInventoryItems(String campaignId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM campaign_inventory WHERE campaign_id = " + quote(campaignId) + ";");
        }
    }

    public Map<String, Object> getLatestCampaignEvent(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, kind, summary FROM campaign_events WHERE campaign_id = " + quote(campaignId) + " ORDER BY rowid DESC LIMIT 1;");
            if (rows.isEmpty()) return null;
            return rows.get(0);
        }
    }

    public boolean insertQuest(String campaignId, String id, String title, String status, List<String> milestones) {
        synchronized (lock) {
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("INSERT INTO quests (id, campaign_id, title, status) VALUES (" + quote(id) + ", " + quote(campaignId) + ", " + quote(title) + ", " + quote(status) + ");");
            Set<String> seen = new HashSet<>();
            for (String milestone : milestones) {
                if (!seen.add(milestone)) continue;
                sqls.add("INSERT INTO quest_milestones (quest_id, campaign_id, milestone, completed) VALUES (" + quote(id) + ", " + quote(campaignId) + ", " + quote(milestone) + ", 0);");
            }
            sqls.add("COMMIT;");
            return executeInsert(sqls);
        }
    }

    public Map<String, Object> getQuest(String campaignId, String id) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, title, status FROM quests WHERE id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            List<String> milestones = new ArrayList<>();
            Set<String> completed = new HashSet<>();
            List<Map<String, Object>> milestoneRows = query("SELECT milestone, completed FROM quest_milestones WHERE quest_id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + " ORDER BY rowid;");
            for (Map<String, Object> mr : milestoneRows) {
                String milestone = (String) mr.get("milestone");
                milestones.add(milestone);
                if (JsonUtils.toInt(mr.get("completed")) != 0) {
                    completed.add(milestone);
                }
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", row.get("id"));
            res.put("title", row.get("title"));
            res.put("status", row.get("status"));
            res.put("milestones", milestones);
            res.put("completed", completed);
            return res;
        }
    }

    public boolean updateQuestProgress(String campaignId, String id, List<String> completed) {
        synchronized (lock) {
            try {
                List<String> sqls = new ArrayList<>();
                sqls.add("BEGIN;");
                for (String milestone : completed) {
                    sqls.add("UPDATE quest_milestones SET completed = 1 WHERE quest_id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + " AND milestone = " + quote(milestone) + ";");
                }
                sqls.add("COMMIT;");
                execSql(sqls.toArray(new String[0]));

                List<Map<String, Object>> rows = query("SELECT COUNT(*) AS total FROM quest_milestones WHERE quest_id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + ";");
                int total = JsonUtils.toInt(rows.get(0).get("total"));
                rows = query("SELECT COUNT(*) AS done FROM quest_milestones WHERE quest_id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + " AND completed = 1;");
                int done = JsonUtils.toInt(rows.get(0).get("done"));
                if (total > 0 && total == done) {
                    execSql("UPDATE quests SET status = 'completed' WHERE id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + " AND status != 'completed';");
                }
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public boolean insertFaction(String campaignId, String id, String name, String stance) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO factions (id, campaign_id, name, stance) VALUES (" + quote(id) + ", " + quote(campaignId) + ", " + quote(name) + ", " + quote(stance) + ");",
                "COMMIT;"
            );
        }
    }

    public boolean insertNpc(String campaignId, String id, String name, String factionId, int disposition) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO npcs (id, campaign_id, name, faction_id, disposition) VALUES (" + quote(id) + ", " + quote(campaignId) + ", " + quote(name) + ", " + quote(factionId) + ", " + disposition + ");",
                "COMMIT;"
            );
        }
    }

    public int countFactions(String campaignId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM factions WHERE campaign_id = " + quote(campaignId) + ";");
        }
    }

    public int countNpcs(String campaignId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM npcs WHERE campaign_id = " + quote(campaignId) + ";");
        }
    }

    public int countFriendlyNpcs(String campaignId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM npcs WHERE campaign_id = " + quote(campaignId) + " AND disposition > 0;");
        }
    }

    public Map<String, Object> getQuestSummary(String campaignId) {
        synchronized (lock) {
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("campaign_id", campaignId);
            res.put("active", 0);
            res.put("completed", 0);
            res.put("blocked", 0);
            List<Map<String, Object>> rows = query("SELECT status, COUNT(*) AS c FROM quests WHERE campaign_id = " + quote(campaignId) + " GROUP BY status;");
            for (Map<String, Object> row : rows) {
                String status = (String) row.get("status");
                int count = JsonUtils.toInt(row.get("c"));
                if ("active".equals(status)) res.put("active", count);
                else if ("completed".equals(status)) res.put("completed", count);
                else if ("blocked".equals(status)) res.put("blocked", count);
            }
            return res;
        }
    }

    public void addInventoryItem(String campaignId, String itemSlug, String owner, int quantity) {
        synchronized (lock) {
            execSql(
                "INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (" + quote(campaignId) + ", " + quote(itemSlug) + ", " + quote(owner) + ", " + quantity + ") ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + excluded.quantity;"
            );
        }
    }

    public boolean assignEquipment(String campaignId, String characterId, String itemSlug, int quantity) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(SUM(quantity), 0) AS total FROM campaign_inventory WHERE campaign_id = " + quote(campaignId) + " AND item_slug = " + quote(itemSlug) + " AND owner = 'party';");
            int partyTotal = JsonUtils.toInt(rows.get(0).get("total"));
            rows = query("SELECT COALESCE(SUM(quantity), 0) AS total FROM character_equipment WHERE campaign_id = " + quote(campaignId) + " AND item_slug = " + quote(itemSlug) + ";");
            int assignedTotal = JsonUtils.toInt(rows.get(0).get("total"));
            if (partyTotal - assignedTotal < quantity) return false;

            execSql(
                "INSERT INTO character_equipment (campaign_id, character_id, item_slug, quantity) VALUES (" + quote(campaignId) + ", " + quote(characterId) + ", " + quote(itemSlug) + ", " + quantity + ") ON CONFLICT(campaign_id, character_id, item_slug) DO UPDATE SET quantity = quantity + excluded.quantity;"
            );
            return true;
        }
    }

    public boolean insertCraftingProject(String campaignId, String id, String characterId, String itemSlug, int daysRequired) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO downtime_crafting_projects (id, campaign_id, character_id, item_slug, days_required, days_completed, status) VALUES (" + quote(id) + ", " + quote(campaignId) + ", " + quote(characterId) + ", " + quote(itemSlug) + ", " + daysRequired + ", 0, 'active');",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getCraftingProject(String campaignId, String id) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, character_id, item_slug, days_required, days_completed, status FROM downtime_crafting_projects WHERE id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", row.get("id"));
            res.put("character_id", row.get("character_id"));
            res.put("item_slug", row.get("item_slug"));
            res.put("days_required", JsonUtils.toInt(row.get("days_required")));
            res.put("days_completed", JsonUtils.toInt(row.get("days_completed")));
            res.put("status", row.get("status"));
            return res;
        }
    }

    public Map<String, Object> advanceCraftingProject(String campaignId, String id, int days) {
        synchronized (lock) {
            Map<String, Object> project = getCraftingProject(campaignId, id);
            if (project == null) return null;
            int daysRequired = JsonUtils.toInt(project.get("days_required"));
            int daysCompleted = JsonUtils.toInt(project.get("days_completed"));
            String status = (String) project.get("status");
            if ("complete".equals(status)) {
                Map<String, Object> res = new LinkedHashMap<>();
                res.put("id", id);
                res.put("days_completed", daysCompleted);
                res.put("status", status);
                return res;
            }
            int newDaysCompleted = Math.min(daysRequired, daysCompleted + days);
            String newStatus = newDaysCompleted >= daysRequired ? "complete" : "active";
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("UPDATE downtime_crafting_projects SET days_completed = " + newDaysCompleted + ", status = '" + newStatus + "' WHERE id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + ";");
            if ("complete".equals(newStatus)) {
                String itemSlug = (String) project.get("item_slug");
            sqls.add("INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (" + quote(campaignId) + ", " + quote(itemSlug) + ", 'party', 1) ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + excluded.quantity;");
            }
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", id);
            res.put("days_completed", newDaysCompleted);
            res.put("status", newStatus);
            return res;
        }
    }

    public Map<String, Object> getInventorySummary(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COUNT(*) AS c FROM campaign_inventory WHERE campaign_id = " + quote(campaignId) + " AND owner = 'party';");
            int partyItems = JsonUtils.toInt(rows.get(0).get("c"));
            rows = query("SELECT COUNT(*) AS c FROM character_equipment WHERE campaign_id = " + quote(campaignId) + ";");
            int assignedItems = JsonUtils.toInt(rows.get(0).get("c"));
            rows = query("SELECT COALESCE(SUM(quantity), 0) AS q FROM campaign_inventory WHERE campaign_id = " + quote(campaignId) + " AND item_slug = 'healing-potion' AND owner = 'party';");
            int partyHealing = JsonUtils.toInt(rows.get(0).get("q"));
            rows = query("SELECT COALESCE(SUM(quantity), 0) AS q FROM character_equipment WHERE campaign_id = " + quote(campaignId) + " AND item_slug = 'healing-potion';");
            int assignedHealing = JsonUtils.toInt(rows.get(0).get("q"));
            int available = Math.max(0, partyHealing - assignedHealing);

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("campaign_id", campaignId);
            res.put("party_items", partyItems);
            res.put("assigned_items", assignedItems);
            res.put("healing_potions_available", available);
            return res;
        }
    }

    public boolean insertSession(String campaignId, String id, String startsAt, int durationMinutes, List<String> agenda) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO sessions (id, campaign_id, starts_at, duration_minutes, agenda_count) VALUES (" + quote(id) + ", " + quote(campaignId) + ", " + quote(startsAt) + ", " + durationMinutes + ", " + agenda.size() + ");",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getSession(String id, String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, starts_at, duration_minutes, agenda_count FROM sessions WHERE id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", row.get("id"));
            res.put("starts_at", row.get("starts_at"));
            res.put("duration_minutes", JsonUtils.toInt(row.get("duration_minutes")));
            res.put("agenda_count", JsonUtils.toInt(row.get("agenda_count")));
            return res;
        }
    }

    public Map<String, Object> getNextSession(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, starts_at, duration_minutes, agenda_count FROM sessions WHERE campaign_id = " + quote(campaignId) + " ORDER BY starts_at, id LIMIT 1;");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", row.get("id"));
            res.put("starts_at", row.get("starts_at"));
            res.put("agenda_count", JsonUtils.toInt(row.get("agenda_count")));
            return res;
        }
    }

    public boolean recordAttendance(String campaignId, String sessionId, List<String> present, List<String> absent) {
        synchronized (lock) {
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("DELETE FROM session_attendance WHERE session_id = " + quote(sessionId) + " AND campaign_id = " + quote(campaignId) + ";");
            for (String p : present) {
            sqls.add("INSERT INTO session_attendance (session_id, campaign_id, character_id, present) VALUES (" + quote(sessionId) + ", " + quote(campaignId) + ", " + quote(p) + ", 1);");
            }
            for (String a : absent) {
            sqls.add("INSERT INTO session_attendance (session_id, campaign_id, character_id, present) VALUES (" + quote(sessionId) + ", " + quote(campaignId) + ", " + quote(a) + ", 0);");
            }
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));
            return true;
        }
    }

    public Map<String, Object> getAttendanceCounts(String campaignId, String sessionId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT present, COUNT(*) AS c FROM session_attendance WHERE session_id = " + quote(sessionId) + " AND campaign_id = " + quote(campaignId) + " GROUP BY present;");
            int present = 0;
            int absent = 0;
            for (Map<String, Object> row : rows) {
                int p = JsonUtils.toInt(row.get("present"));
                int c = JsonUtils.toInt(row.get("c"));
                if (p == 1) present = c;
                else absent = c;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("present_count", present);
            res.put("absent_count", absent);
            return res;
        }
    }

    public Map<String, Object> getPlayCampaignMemberByCharacterId(String campaignId, String characterId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT username, character_id, name, class, level, hp_current, hp_max, status, death_save_successes, death_save_failures FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("username", row.get("username"));
            m.put("character_id", row.get("character_id"));
            m.put("name", row.get("name"));
            m.put("class", row.get("class"));
            m.put("level", JsonUtils.toInt(row.get("level")));
            m.put("hp_current", JsonUtils.toInt(row.get("hp_current")));
            m.put("hp_max", JsonUtils.toInt(row.get("hp_max")));
            m.put("status", row.get("status"));
            m.put("death_save_successes", JsonUtils.toInt(row.get("death_save_successes")));
            m.put("death_save_failures", JsonUtils.toInt(row.get("death_save_failures")));
            return m;
        }
    }

    public Map<String, Object> applyDamageToPlayCampaignCharacter(String campaignId, String characterId, int amount) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT hp_current, hp_max, status FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            if (rows.isEmpty()) return null;
            int hpBefore = JsonUtils.toInt(rows.get(0).get("hp_current"));
            int hpMax = JsonUtils.toInt(rows.get(0).get("hp_max"));
            String status = (String) rows.get(0).get("status");
            int hpAfter = Math.max(0, hpBefore - amount);
            String newStatus = status;
            int successes = 0;
            int failures = 0;
            if (!"dead".equals(status)) {
                if (hpAfter == 0) {
                    newStatus = "unconscious";
                } else {
                    newStatus = "conscious";
                }
            }
            execSql("UPDATE play_campaign_members SET hp_current = " + hpAfter + ", status = " + quote(newStatus) + ", death_save_successes = " + successes + ", death_save_failures = " + failures + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", characterId);
            res.put("hp_before", hpBefore);
            res.put("hp_after", hpAfter);
            res.put("hp_current", hpAfter);
            res.put("hp_max", hpMax);
            res.put("status", newStatus);
            res.put("damage", amount);
            return res;
        }
    }

    public Map<String, Object> recordDeathSave(String campaignId, String characterId, String outcome) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT status, death_save_successes, death_save_failures FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            if (rows.isEmpty()) return null;
            String status = (String) rows.get(0).get("status");
            int successes = JsonUtils.toInt(rows.get(0).get("death_save_successes"));
            int failures = JsonUtils.toInt(rows.get(0).get("death_save_failures"));
            if (!"unconscious".equals(status)) return null;
            if ("success".equals(outcome)) {
                successes++;
                if (successes >= 3) status = "stable";
            } else if ("failure".equals(outcome)) {
                failures++;
                if (failures >= 3) status = "dead";
            } else {
                return null;
            }
            execSql("UPDATE play_campaign_members SET status = " + quote(status) + ", death_save_successes = " + successes + ", death_save_failures = " + failures + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", characterId);
            res.put("successes", successes);
            res.put("failures", failures);
            res.put("status", status);
            return res;
        }
    }

    public Map<String, Object> getPlayCampaignCharacterStatus(String campaignId, String characterId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT hp_current, hp_max, status FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", characterId);
            res.put("hp_current", JsonUtils.toInt(rows.get(0).get("hp_current")));
            res.put("hp_max", JsonUtils.toInt(rows.get(0).get("hp_max")));
            res.put("status", rows.get(0).get("status"));
            return res;
        }
    }

    public boolean updatePlayCampaignCharacterBuild(String campaignId, String characterId, String race, String className, String background, int level, int hpMax, String abilitiesJson) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "UPDATE play_campaign_members SET race = " + quote(race) + ", class = " + quote(className) + ", background = " + quote(background) + ", level = " + level + ", hp_max = " + hpMax + ", hp_current = " + hpMax + ", abilities = " + quote(abilitiesJson) + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public Map<String, Object> getPlayCampaignCharacterLevelInfo(String campaignId, String characterId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT class, level, hp_max, abilities FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            if (rows.isEmpty()) return null;
            return rows.get(0);
        }
    }

    public boolean levelUpPlayCampaignCharacter(String campaignId, String characterId, int newLevel, int newHpMax) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "UPDATE play_campaign_members SET level = " + newLevel + ", hp_max = " + newHpMax + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public boolean insertPlayCampaignCharacterSpell(String campaignId, String characterId, String spellId, String name, int level) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_character_spells (campaign_id, character_id, spell_id, name, level) VALUES (" + quote(campaignId) + ", " + quote(characterId) + ", " + quote(spellId) + ", " + quote(name) + ", " + level + ");",
                "COMMIT;"
            );
        }
    }

    public List<Map<String, Object>> listPlayCampaignCharacterSpells(String campaignId, String characterId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT spell_id, name, level FROM play_campaign_character_spells WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " ORDER BY spell_id;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> s = new LinkedHashMap<>();
                s.put("spell_id", row.get("spell_id"));
                s.put("name", row.get("name"));
                s.put("level", JsonUtils.toInt(row.get("level")));
                res.add(s);
            }
            return res;
        }
    }

    public boolean setPlayCampaignCharacterPreparedSpells(String campaignId, String characterId, List<String> spellIds) {
        synchronized (lock) {
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("DELETE FROM play_campaign_character_prepared_spells WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            for (String spellId : spellIds) {
                sqls.add("INSERT INTO play_campaign_character_prepared_spells (campaign_id, character_id, spell_id) VALUES (" + quote(campaignId) + ", " + quote(characterId) + ", " + quote(spellId) + ");");
            }
            sqls.add("COMMIT;");
            try {
                execSql(sqls.toArray(new String[0]));
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public List<String> listPlayCampaignCharacterPreparedSpells(String campaignId, String characterId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT spell_id FROM play_campaign_character_prepared_spells WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " ORDER BY spell_id;");
            List<String> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                res.add((String) row.get("spell_id"));
            }
            return res;
        }
    }

    public Map<String, Object> getPlayCampaignCharacterSpell(String campaignId, String characterId, String spellId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT spell_id, name, level FROM play_campaign_character_spells WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND spell_id = " + quote(spellId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> s = new LinkedHashMap<>();
            Map<String, Object> row = rows.get(0);
            s.put("spell_id", row.get("spell_id"));
            s.put("name", row.get("name"));
            s.put("level", JsonUtils.toInt(row.get("level")));
            return s;
        }
    }

    public boolean isPlayCampaignCharacterSpellPrepared(String campaignId, String characterId, String spellId) {
        synchronized (lock) {
            int c = queryCount("SELECT COUNT(*) AS c FROM play_campaign_character_prepared_spells WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND spell_id = " + quote(spellId) + ";");
            return c > 0;
        }
    }

    public int countPlayCampaignCharacterCastsAtSlotLevel(String campaignId, String characterId, int slotLevel) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_character_casts WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND slot_level = " + slotLevel + ";");
        }
    }

    public int getNextPlayCampaignCharacterCastSequence(String campaignId, String characterId) {
        synchronized (lock) {
            int c = queryCount("SELECT COUNT(*) AS c FROM play_campaign_character_casts WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            return c + 1;
        }
    }

    public Map<String, Object> insertPlayCampaignCharacterCast(String campaignId, String characterId, String spellId, String target, int slotLevel, int slotsRemaining, int sequence) {
        synchronized (lock) {
            execSql(
                "BEGIN;",
                "INSERT INTO play_campaign_character_casts (campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining) VALUES (" + quote(campaignId) + ", " + quote(characterId) + ", " + sequence + ", " + quote(spellId) + ", " + quote(target) + ", " + slotLevel + ", " + slotsRemaining + ");",
                "COMMIT;"
            );
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", characterId);
            res.put("spell_id", spellId);
            res.put("target", target);
            res.put("slot_level", slotLevel);
            res.put("slots_remaining", slotsRemaining);
            res.put("sequence", sequence);
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignCharacterCasts(String campaignId, String characterId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT sequence, spell_id, target, slot_level, slots_remaining FROM play_campaign_character_casts WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " ORDER BY sequence;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> c = new LinkedHashMap<>();
                c.put("character_id", characterId);
                c.put("spell_id", row.get("spell_id"));
                c.put("target", row.get("target"));
                c.put("slot_level", JsonUtils.toInt(row.get("slot_level")));
                c.put("slots_remaining", JsonUtils.toInt(row.get("slots_remaining")));
                c.put("sequence", JsonUtils.toInt(row.get("sequence")));
                res.add(c);
            }
            return res;
        }
    }

    public Map<String, Object> getPlayCampaignCharacterConcentration(String campaignId, String characterId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT spell_id, target, remaining_turns FROM play_campaign_character_concentration WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("spell_id", row.get("spell_id"));
            res.put("target", row.get("target"));
            res.put("remaining_turns", JsonUtils.toInt(row.get("remaining_turns")));
            return res;
        }
    }

    public void setPlayCampaignCharacterConcentration(String campaignId, String characterId, String spellId, String target, int remainingTurns) {
        synchronized (lock) {
            execSql(
                "INSERT INTO play_campaign_character_concentration (campaign_id, character_id, spell_id, target, remaining_turns) VALUES (" + quote(campaignId) + ", " + quote(characterId) + ", " + quote(spellId) + ", " + quote(target) + ", " + remainingTurns + ") " +
                "ON CONFLICT(campaign_id, character_id) DO UPDATE SET spell_id = excluded.spell_id, target = excluded.target, remaining_turns = excluded.remaining_turns;"
            );
        }
    }

    public Map<String, Object> advancePlayCampaignCharacterConcentration(String campaignId, String characterId) {
        synchronized (lock) {
            Map<String, Object> current = getPlayCampaignCharacterConcentration(campaignId, characterId);
            if (current == null) return null;
            int remaining = JsonUtils.toInt(current.get("remaining_turns")) - 1;
            if (remaining <= 0) {
                clearPlayCampaignCharacterConcentration(campaignId, characterId);
                return null;
            }
            execSql("UPDATE play_campaign_character_concentration SET remaining_turns = " + remaining + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("spell_id", current.get("spell_id"));
            res.put("target", current.get("target"));
            res.put("remaining_turns", remaining);
            return res;
        }
    }

    public void clearPlayCampaignCharacterConcentration(String campaignId, String characterId) {
        synchronized (lock) {
            execSql("DELETE FROM play_campaign_character_concentration WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
        }
    }

    public int getPlayCampaignCharacterInventoryQuantity(String campaignId, String characterId, String itemId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND item_id = " + quote(itemId) + ";");
            if (rows.isEmpty()) return 0;
            return JsonUtils.toInt(rows.get(0).get("quantity"));
        }
    }

    public int addPlayCampaignCharacterInventoryItem(String campaignId, String characterId, String itemId, int quantity) {
        synchronized (lock) {
            execSql(
                "INSERT INTO play_campaign_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (" + quote(campaignId) + ", " + quote(characterId) + ", " + quote(itemId) + ", " + quantity + ") " +
                "ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity;"
            );
            return getPlayCampaignCharacterInventoryQuantity(campaignId, characterId, itemId);
        }
    }

    public List<Map<String, Object>> listPlayCampaignCharacterInventory(String campaignId, String characterId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT item_id, quantity FROM play_campaign_character_inventory WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " ORDER BY item_id;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("item_id", row.get("item_id"));
                item.put("quantity", JsonUtils.toInt(row.get("quantity")));
                res.add(item);
            }
            return res;
        }
    }

    public int removePlayCampaignCharacterInventoryItem(String campaignId, String characterId, String itemId, int quantity) {
        synchronized (lock) {
            int current = getPlayCampaignCharacterInventoryQuantity(campaignId, characterId, itemId);
            int remaining = current - quantity;
            if (remaining < 0) return -1;
            if (remaining == 0) {
                execSql("DELETE FROM play_campaign_character_inventory WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND item_id = " + quote(itemId) + ";");
            } else {
                execSql("UPDATE play_campaign_character_inventory SET quantity = " + remaining + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND item_id = " + quote(itemId) + ";");
            }
            return remaining;
        }
    }

    public Map<String, Object> consumePlayCampaignCharacterInventoryItem(String campaignId, String characterId, String itemId) {
        synchronized (lock) {
            int current = getPlayCampaignCharacterInventoryQuantity(campaignId, characterId, itemId);
            int remaining = current - 1;
            if (remaining == 0) {
                execSql("DELETE FROM play_campaign_character_inventory WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND item_id = " + quote(itemId) + ";");
            } else {
                execSql("UPDATE play_campaign_character_inventory SET quantity = " + remaining + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND item_id = " + quote(itemId) + ";");
            }

            List<Map<String, Object>> rows = query("SELECT hp_current, hp_max FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            int hpCurrent = rows.isEmpty() ? 0 : JsonUtils.toInt(rows.get(0).get("hp_current"));
            int hpMax = rows.isEmpty() ? 0 : JsonUtils.toInt(rows.get(0).get("hp_max"));
            int hpAfter = Math.min(hpMax, hpCurrent + 5);
            execSql("UPDATE play_campaign_members SET hp_current = " + hpAfter + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");

            Map<String, Object> effect = new LinkedHashMap<>();
            effect.put("type", "healing");
            effect.put("hp_restored", 5);

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", characterId);
            res.put("item_id", itemId);
            res.put("quantity_consumed", 1);
            res.put("total_quantity", remaining);
            res.put("effect", effect);
            return res;
        }
    }

    public void setPlayCampaignCharacterEquipment(String campaignId, String characterId, String slot, String itemId, boolean attuned) {
        synchronized (lock) {
            execSql(
                "INSERT INTO play_campaign_character_equipment (campaign_id, character_id, slot, item_id, attuned) VALUES (" + quote(campaignId) + ", " + quote(characterId) + ", " + quote(slot) + ", " + quote(itemId) + ", " + (attuned ? 1 : 0) + ") " +
                "ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET item_id = excluded.item_id, attuned = excluded.attuned;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignCharacterEquipment(String campaignId, String characterId, String slot) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT item_id, attuned FROM play_campaign_character_equipment WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND slot = " + quote(slot) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("item_id", row.get("item_id"));
            res.put("attuned", JsonUtils.toInt(row.get("attuned")) != 0);
            return res;
        }
    }

    public void setPlayCampaignCharacterEquipmentAttuned(String campaignId, String characterId, String slot, boolean attuned) {
        synchronized (lock) {
            execSql("UPDATE play_campaign_character_equipment SET attuned = " + (attuned ? 1 : 0) + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND slot = " + quote(slot) + ";");
        }
    }

    public int countPlayCampaignCharacterAttunedEquipment(String campaignId, String characterId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_character_equipment WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND attuned != 0;");
        }
    }

    public Integer getPlayCampaignCharacterGold(String campaignId, String characterId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT gold FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            if (rows.isEmpty()) return null;
            return JsonUtils.toInt(rows.get(0).get("gold"));
        }
    }

    public Map<String, Object> transferPlayCampaignGold(String campaignId, String fromCharacterId, String toCharacterId, int gold) {
        synchronized (lock) {
            List<Map<String, Object>> fromRows = query("SELECT gold FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(fromCharacterId) + ";");
            if (fromRows.isEmpty()) return null;
            List<Map<String, Object>> toRows = query("SELECT gold FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(toCharacterId) + ";");
            if (toRows.isEmpty()) throw new RuntimeException("Destination character not found");

            int fromGold = JsonUtils.toInt(fromRows.get(0).get("gold"));
            int toGold = JsonUtils.toInt(toRows.get(0).get("gold"));
            if (fromGold < gold) return null;

            int fromGoldAfter = fromGold - gold;
            int toGoldAfter = toGold + gold;
            int transferId = queryCount("SELECT COALESCE(MAX(transfer_id), 0) AS c FROM play_campaign_transfers WHERE campaign_id = " + quote(campaignId) + ";") + 1;

            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("UPDATE play_campaign_members SET gold = " + fromGoldAfter + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(fromCharacterId) + ";");
            sqls.add("UPDATE play_campaign_members SET gold = " + toGoldAfter + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(toCharacterId) + ";");
            sqls.add("INSERT INTO play_campaign_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold) VALUES (" + quote(campaignId) + ", " + transferId + ", " + quote(fromCharacterId) + ", " + quote(toCharacterId) + ", " + gold + ");");
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("from_character_id", fromCharacterId);
            res.put("to_character_id", toCharacterId);
            res.put("gold", gold);
            res.put("from_gold", fromGoldAfter);
            res.put("to_gold", toGoldAfter);
            res.put("transfer_id", transferId);
            return res;
        }
    }

    public Map<String, Object> executePlayCampaignTransactionalTransfer(String campaignId, String fromCharacterId, String toCharacterId, int amount, boolean simulateFailure) {
        synchronized (lock) {
            List<Map<String, Object>> fromRows = query("SELECT gold FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(fromCharacterId) + ";");
            if (fromRows.isEmpty()) return null;
            List<Map<String, Object>> toRows = query("SELECT gold FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(toCharacterId) + ";");
            if (toRows.isEmpty()) return null;

            int fromGold = JsonUtils.toInt(fromRows.get(0).get("gold"));
            int toGold = JsonUtils.toInt(toRows.get(0).get("gold"));
            if (fromGold < amount) return null;

            if (simulateFailure) {
                throw new RuntimeException("simulated failure");
            }

            int fromGoldAfter = fromGold - amount;
            int toGoldAfter = toGold + amount;
            List<Map<String, Object>> seqRows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_transactional_transfers WHERE campaign_id = " + quote(campaignId) + ";");
            int sequence = JsonUtils.toInt(seqRows.get(0).get("max_seq")) + 1;

            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("UPDATE play_campaign_members SET gold = " + fromGoldAfter + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(fromCharacterId) + ";");
            sqls.add("UPDATE play_campaign_members SET gold = " + toGoldAfter + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(toCharacterId) + ";");
            sqls.add("INSERT INTO play_campaign_transactional_transfers (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) VALUES (" + quote(campaignId) + ", " + sequence + ", " + quote(fromCharacterId) + ", " + quote(toCharacterId) + ", " + amount + ", " + fromGoldAfter + ", " + toGoldAfter + ");");
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("from_character_id", fromCharacterId);
            res.put("to_character_id", toCharacterId);
            res.put("amount", amount);
            res.put("from_gold", fromGoldAfter);
            res.put("to_gold", toGoldAfter);
            res.put("sequence", sequence);
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignTransactionalTransfers(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT sequence, from_character_id, to_character_id, amount, from_gold, to_gold FROM play_campaign_transactional_transfers WHERE campaign_id = " + quote(campaignId) + " ORDER BY sequence;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> t = new LinkedHashMap<>();
                t.put("from_character_id", row.get("from_character_id"));
                t.put("to_character_id", row.get("to_character_id"));
                t.put("amount", JsonUtils.toInt(row.get("amount")));
                t.put("from_gold", JsonUtils.toInt(row.get("from_gold")));
                t.put("to_gold", JsonUtils.toInt(row.get("to_gold")));
                t.put("sequence", JsonUtils.toInt(row.get("sequence")));
                res.add(t);
            }
            return res;
        }
    }

    public boolean insertPlayCampaignLoot(String campaignId, String lootId, String itemId, int quantity) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_loot (campaign_id, loot_id, item_id, quantity, status) VALUES (" + quote(campaignId) + ", " + quote(lootId) + ", " + quote(itemId) + ", " + quantity + ", 'open');",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignLoot(String campaignId, String lootId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT loot_id, item_id, quantity, status, recipient_character_id, votes FROM play_campaign_loot WHERE campaign_id = " + quote(campaignId) + " AND loot_id = " + quote(lootId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("loot_id", row.get("loot_id"));
            res.put("item_id", row.get("item_id"));
            res.put("quantity", JsonUtils.toInt(row.get("quantity")));
            res.put("status", row.get("status"));
            res.put("recipient_character_id", row.get("recipient_character_id"));
            res.put("votes", JsonUtils.toInt(row.get("votes")));
            return res;
        }
    }

    public boolean insertPlayCampaignLootVote(String campaignId, String lootId, String voter, String recipientCharacterId) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (" + quote(campaignId) + ", " + quote(lootId) + ", " + quote(voter) + ", " + quote(recipientCharacterId) + ");",
                "COMMIT;"
            );
        }
    }

    public int countPlayCampaignLootVotesForRecipient(String campaignId, String lootId, String recipientCharacterId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_loot_votes WHERE campaign_id = " + quote(campaignId) + " AND loot_id = " + quote(lootId) + " AND recipient_character_id = " + quote(recipientCharacterId) + ";");
        }
    }

    public Map<String, Object> getPlayCampaignLootVoteDistribution(String campaignId, String lootId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT recipient_character_id, COUNT(*) AS c FROM play_campaign_loot_votes WHERE campaign_id = " + quote(campaignId) + " AND loot_id = " + quote(lootId) + " GROUP BY recipient_character_id ORDER BY recipient_character_id;");
            Map<String, Object> votes = new LinkedHashMap<>();
            for (Map<String, Object> row : rows) {
                String recipient = (String) row.get("recipient_character_id");
                int count = JsonUtils.toInt(row.get("c"));
                votes.put(recipient, count);
            }
            return votes;
        }
    }

    public Map<String, Object> assignPlayCampaignLoot(String campaignId, String lootId) {
        synchronized (lock) {
            Map<String, Object> loot = getPlayCampaignLoot(campaignId, lootId);
            if (loot == null || !"open".equals(loot.get("status"))) return null;

            List<Map<String, Object>> voteRows = query("SELECT recipient_character_id, COUNT(*) AS c FROM play_campaign_loot_votes WHERE campaign_id = " + quote(campaignId) + " AND loot_id = " + quote(lootId) + " GROUP BY recipient_character_id ORDER BY c DESC, recipient_character_id;");
            if (voteRows.isEmpty()) return null;
            int topCount = JsonUtils.toInt(voteRows.get(0).get("c"));
            String winner = (String) voteRows.get(0).get("recipient_character_id");
            for (int i = 1; i < voteRows.size(); i++) {
                if (JsonUtils.toInt(voteRows.get(i).get("c")) == topCount) return null;
            }

            String itemId = (String) loot.get("item_id");
            int quantity = JsonUtils.toInt(loot.get("quantity"));

            execSql(
                "BEGIN;",
                "UPDATE play_campaign_loot SET status = 'assigned', recipient_character_id = " + quote(winner) + ", votes = " + topCount + " WHERE campaign_id = " + quote(campaignId) + " AND loot_id = " + quote(lootId) + " AND status = 'open';",
                "INSERT INTO play_campaign_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (" + quote(campaignId) + ", " + quote(winner) + ", " + quote(itemId) + ", " + quantity + ") ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity;",
                "COMMIT;"
            );

            loot = getPlayCampaignLoot(campaignId, lootId);
            if (loot == null || !"assigned".equals(loot.get("status"))) return null;
            return loot;
        }
    }

    public boolean insertPlayCampaignNpc(String campaignId, String npcId, String name, String agenda, String publicStatus) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (" + quote(campaignId) + ", " + quote(npcId) + ", " + quote(name) + ", " + quote(agenda) + ", " + quote(publicStatus) + ");",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignNpc(String campaignId, String npcId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT npc_id, name, agenda, public_status FROM play_campaign_npcs WHERE campaign_id = " + quote(campaignId) + " AND npc_id = " + quote(npcId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("npc_id", row.get("npc_id"));
            res.put("name", row.get("name"));
            res.put("agenda", row.get("agenda"));
            res.put("public_status", row.get("public_status"));
            return res;
        }
    }

    public boolean updatePlayCampaignNpc(String campaignId, String npcId, String agenda, String publicStatus) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "UPDATE play_campaign_npcs SET agenda = " + quote(agenda) + ", public_status = " + quote(publicStatus) + " WHERE campaign_id = " + quote(campaignId) + " AND npc_id = " + quote(npcId) + ";",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public boolean insertPlayCampaignNpcDialogue(String campaignId, String npcId, String dialogueId, String speaker, String text, String visibility) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_npc_dialogue (campaign_id, npc_id, dialogue_id, speaker, text, visibility) VALUES (" + quote(campaignId) + ", " + quote(npcId) + ", " + quote(dialogueId) + ", " + quote(speaker) + ", " + quote(text) + ", " + quote(visibility) + ");",
                "COMMIT;"
            );
        }
    }

    public List<Map<String, Object>> listPlayCampaignNpcDialogue(String campaignId, String npcId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT dialogue_id, speaker, text, visibility FROM play_campaign_npc_dialogue WHERE campaign_id = " + quote(campaignId) + " AND npc_id = " + quote(npcId) + " ORDER BY rowid;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("dialogue_id", row.get("dialogue_id"));
                entry.put("speaker", row.get("speaker"));
                entry.put("text", row.get("text"));
                entry.put("visibility", row.get("visibility"));
                res.add(entry);
            }
            return res;
        }
    }

    public boolean isPlayCampaignEntity(String campaignId, String entityId) {
        synchronized (lock) {
            int characters = queryCount("SELECT COUNT(*) AS c FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(entityId) + ";");
            if (characters > 0) return true;
            int npcs = queryCount("SELECT COUNT(*) AS c FROM play_campaign_npcs WHERE campaign_id = " + quote(campaignId) + " AND npc_id = " + quote(entityId) + ";");
            return npcs > 0;
        }
    }

    public boolean insertPlayCampaignRelationship(String campaignId, String sourceId, String targetId, String kind, int score) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_relationships (campaign_id, source_id, target_id, kind, score) VALUES (" + quote(campaignId) + ", " + quote(sourceId) + ", " + quote(targetId) + ", " + quote(kind) + ", " + score + ");",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignRelationship(String campaignId, String sourceId, String targetId, String kind) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT source_id, target_id, kind, score FROM play_campaign_relationships WHERE campaign_id = " + quote(campaignId) + " AND source_id = " + quote(sourceId) + " AND target_id = " + quote(targetId) + " AND kind = " + quote(kind) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("source_id", row.get("source_id"));
            res.put("target_id", row.get("target_id"));
            res.put("kind", row.get("kind"));
            res.put("score", JsonUtils.toInt(row.get("score")));
            return res;
        }
    }

    public boolean updatePlayCampaignRelationship(String campaignId, String sourceId, String targetId, String kind, int score) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "UPDATE play_campaign_relationships SET score = " + score + " WHERE campaign_id = " + quote(campaignId) + " AND source_id = " + quote(sourceId) + " AND target_id = " + quote(targetId) + " AND kind = " + quote(kind) + ";",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public List<Map<String, Object>> listPlayCampaignRelationships(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT source_id, target_id, kind, score FROM play_campaign_relationships WHERE campaign_id = " + quote(campaignId) + " ORDER BY rowid;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("source_id", row.get("source_id"));
                entry.put("target_id", row.get("target_id"));
                entry.put("kind", row.get("kind"));
                entry.put("score", JsonUtils.toInt(row.get("score")));
                res.add(entry);
            }
            return res;
        }
    }

    public boolean insertPlayCampaignClue(String campaignId, String clueId, String text, String audience, String characterId) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_clues (campaign_id, clue_id, text, audience, character_id) VALUES (" + quote(campaignId) + ", " + quote(clueId) + ", " + quote(text) + ", " + quote(audience) + ", " + (characterId == null ? "NULL" : quote(characterId)) + ");",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignClue(String campaignId, String clueId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT clue_id, text, audience, character_id FROM play_campaign_clues WHERE campaign_id = " + quote(campaignId) + " AND clue_id = " + quote(clueId) + ";");
            if (rows.isEmpty()) return null;
            return rows.get(0);
        }
    }

    public List<Map<String, Object>> listPlayCampaignClues(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT clue_id, text, audience, character_id FROM play_campaign_clues WHERE campaign_id = " + quote(campaignId) + " ORDER BY rowid;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("clue_id", row.get("clue_id"));
                entry.put("text", row.get("text"));
                entry.put("audience", row.get("audience"));
                Object characterId = row.get("character_id");
                if (characterId != null) entry.put("character_id", characterId);
                res.add(entry);
            }
            return res;
        }
    }

    public boolean insertPlayCampaignFaction(String campaignId, String factionId, String name) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_factions (campaign_id, faction_id, name) VALUES (" + quote(campaignId) + ", " + quote(factionId) + ", " + quote(name) + ");",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignFaction(String campaignId, String factionId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT faction_id, name FROM play_campaign_factions WHERE campaign_id = " + quote(campaignId) + " AND faction_id = " + quote(factionId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("faction_id", row.get("faction_id"));
            res.put("name", row.get("name"));
            return res;
        }
    }

    public Map<String, Object> insertPlayCampaignReputationChange(String campaignId, String factionId, String characterId, int delta, String reason) {
        synchronized (lock) {
            int current = getPlayCampaignReputationTotal(campaignId, factionId, characterId);
            int newTotal = current + delta;
            if (newTotal > 100) newTotal = 100;
            if (newTotal < -100) newTotal = -100;
            execSql(
                "BEGIN;",
                "INSERT INTO play_campaign_reputation_history (campaign_id, faction_id, character_id, reputation, delta, reason) VALUES (" + quote(campaignId) + ", " + quote(factionId) + ", " + quote(characterId) + ", " + newTotal + ", " + delta + ", " + quote(reason) + ");",
                "COMMIT;"
            );
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("faction_id", factionId);
            res.put("character_id", characterId);
            res.put("reputation", newTotal);
            res.put("delta", delta);
            res.put("reason", reason);
            return res;
        }
    }

    private int getPlayCampaignReputationTotal(String campaignId, String factionId, String characterId) {
        List<Map<String, Object>> rows = query("SELECT reputation FROM play_campaign_reputation_history WHERE campaign_id = " + quote(campaignId) + " AND faction_id = " + quote(factionId) + " AND character_id = " + quote(characterId) + " ORDER BY id DESC LIMIT 1;");
        if (rows.isEmpty()) return 0;
        return JsonUtils.toInt(rows.get(0).get("reputation"));
    }

    public List<Map<String, Object>> listPlayCampaignReputationHistory(String campaignId, String factionId, String characterId) {
        synchronized (lock) {
            String sql = "SELECT faction_id, character_id, reputation, delta, reason FROM play_campaign_reputation_history WHERE campaign_id = " + quote(campaignId) + " AND faction_id = " + quote(factionId);
            if (characterId != null) {
                sql += " AND character_id = " + quote(characterId);
            }
            sql += " ORDER BY id;";
            List<Map<String, Object>> rows = query(sql);
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("faction_id", row.get("faction_id"));
                entry.put("character_id", row.get("character_id"));
                entry.put("reputation", JsonUtils.toInt(row.get("reputation")));
                entry.put("delta", JsonUtils.toInt(row.get("delta")));
                entry.put("reason", row.get("reason"));
                res.add(entry);
            }
            return res;
        }
    }

    public boolean insertPlayCampaignQuest(String campaignId, String questId, String title, List<String> dependsOn) {
        synchronized (lock) {
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(sort_order), 0) AS max_sort FROM play_campaign_quests WHERE campaign_id = " + quote(campaignId) + ";");
            int sortOrder = JsonUtils.toInt(rows.get(0).get("max_sort")) + 1;
            sqls.add("INSERT INTO play_campaign_quests (campaign_id, quest_id, title, state, sort_order, reward_xp, reward_items, rewards_configured, rewards_awarded) VALUES (" + quote(campaignId) + ", " + quote(questId) + ", " + quote(title) + ", 'locked', " + sortOrder + ", 0, '{}', 0, 0);");
            Set<String> seen = new HashSet<>();
            for (String dep : dependsOn) {
                if (!seen.add(dep)) continue;
                sqls.add("INSERT INTO play_campaign_quest_dependencies (campaign_id, quest_id, depends_on) VALUES (" + quote(campaignId) + ", " + quote(questId) + ", " + quote(dep) + ");");
            }
            sqls.add("COMMIT;");
            return executeInsert(sqls);
        }
    }

    public Map<String, Object> getPlayCampaignQuest(String campaignId, String questId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT quest_id, title, state, reward_xp, reward_items, rewards_configured, rewards_awarded FROM play_campaign_quests WHERE campaign_id = " + quote(campaignId) + " AND quest_id = " + quote(questId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            List<Map<String, Object>> depRows = query("SELECT depends_on FROM play_campaign_quest_dependencies WHERE campaign_id = " + quote(campaignId) + " AND quest_id = " + quote(questId) + " ORDER BY rowid;");
            List<String> deps = new ArrayList<>();
            for (Map<String, Object> dr : depRows) {
                deps.add((String) dr.get("depends_on"));
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("quest_id", row.get("quest_id"));
            res.put("title", row.get("title"));
            res.put("depends_on", deps);
            res.put("state", row.get("state"));
            if (JsonUtils.toInt(row.get("rewards_configured")) != 0) {
                Map<String, Object> rewards = new LinkedHashMap<>();
                rewards.put("xp", JsonUtils.toInt(row.get("reward_xp")));
                Map<String, Object> items = parseRewardItems((String) row.get("reward_items"));
                rewards.put("items", items);
                res.put("rewards", rewards);
            }
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignQuests(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT quest_id FROM play_campaign_quests WHERE campaign_id = " + quote(campaignId) + " ORDER BY sort_order;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                res.add(getPlayCampaignQuest(campaignId, (String) row.get("quest_id")));
            }
            return res;
        }
    }

    public boolean playCampaignQuestExists(String campaignId, String questId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_quests WHERE campaign_id = " + quote(campaignId) + " AND quest_id = " + quote(questId) + ";") > 0;
        }
    }

    public boolean arePlayCampaignQuestDependenciesCompleted(String campaignId, String questId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT q.state FROM play_campaign_quest_dependencies d JOIN play_campaign_quests q ON d.campaign_id = q.campaign_id AND d.depends_on = q.quest_id WHERE d.campaign_id = " + quote(campaignId) + " AND d.quest_id = " + quote(questId) + ";");
            for (Map<String, Object> row : rows) {
                if (!"completed".equals(row.get("state"))) return false;
            }
            return true;
        }
    }

    public boolean updatePlayCampaignQuestState(String campaignId, String questId, String state) {
        synchronized (lock) {
            try {
                execSql("UPDATE play_campaign_quests SET state = " + quote(state) + " WHERE campaign_id = " + quote(campaignId) + " AND quest_id = " + quote(questId) + ";");
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public boolean configurePlayCampaignQuestRewards(String campaignId, String questId, int xp, Map<String, Integer> items) {
        synchronized (lock) {
            String itemsJson = JsonUtils.toJson(items);
            try {
                execSql(
                    "BEGIN;",
                    "UPDATE play_campaign_quests SET reward_xp = " + xp + ", reward_items = " + quote(itemsJson) + ", rewards_configured = 1 WHERE campaign_id = " + quote(campaignId) + " AND quest_id = " + quote(questId) + ";",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public boolean arePlayCampaignQuestRewardsConfigured(String campaignId, String questId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT rewards_configured FROM play_campaign_quests WHERE campaign_id = " + quote(campaignId) + " AND quest_id = " + quote(questId) + ";");
            return !rows.isEmpty() && JsonUtils.toInt(rows.get(0).get("rewards_configured")) != 0;
        }
    }

    public boolean arePlayCampaignQuestRewardsAwarded(String campaignId, String questId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_quest_rewards WHERE campaign_id = " + quote(campaignId) + " AND quest_id = " + quote(questId) + ";") > 0;
        }
    }

    public Map<String, Object> getPlayCampaignQuestRewardConfig(String campaignId, String questId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT reward_xp, reward_items FROM play_campaign_quests WHERE campaign_id = " + quote(campaignId) + " AND quest_id = " + quote(questId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("xp", JsonUtils.toInt(row.get("reward_xp")));
            res.put("items", parseRewardItems((String) row.get("reward_items")));
            return res;
        }
    }

    public boolean awardPlayCampaignQuestRewards(String campaignId, String questId) {
        synchronized (lock) {
            List<Map<String, Object>> configRows = query("SELECT reward_xp, reward_items FROM play_campaign_quests WHERE campaign_id = " + quote(campaignId) + " AND quest_id = " + quote(questId) + ";");
            if (configRows.isEmpty()) return false;
            int xp = JsonUtils.toInt(configRows.get(0).get("reward_xp"));
            Map<String, Object> itemsMap = parseRewardItems((String) configRows.get(0).get("reward_items"));
            List<Map<String, Object>> members = query("SELECT character_id FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + ";");
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("UPDATE play_campaign_quests SET rewards_awarded = 1 WHERE campaign_id = " + quote(campaignId) + " AND quest_id = " + quote(questId) + ";");
            String itemsJson = JsonUtils.toJson(itemsMap);
            for (Map<String, Object> member : members) {
                String characterId = (String) member.get("character_id");
                sqls.add("INSERT INTO play_campaign_quest_rewards (campaign_id, quest_id, character_id, xp, items) VALUES (" + quote(campaignId) + ", " + quote(questId) + ", " + quote(characterId) + ", " + xp + ", " + quote(itemsJson) + ") ON CONFLICT(campaign_id, quest_id, character_id) DO UPDATE SET xp = excluded.xp, items = excluded.items;");
                for (Map.Entry<String, Object> entry : itemsMap.entrySet()) {
                    String itemId = entry.getKey();
                    int quantity = JsonUtils.toInt(entry.getValue());
                    sqls.add("INSERT INTO play_campaign_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (" + quote(campaignId) + ", " + quote(characterId) + ", " + quote(itemId) + ", " + quantity + ") ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity;");
                }
            }
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));
            return true;
        }
    }

    public Map<String, Object> getPlayCampaignCharacterQuestRewards(String campaignId, String characterId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT xp, items FROM play_campaign_quest_rewards WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            int totalXp = 0;
            Map<String, Integer> mergedItems = new LinkedHashMap<>();
            for (Map<String, Object> row : rows) {
                totalXp += JsonUtils.toInt(row.get("xp"));
                Map<String, Object> items = parseRewardItems((String) row.get("items"));
                for (Map.Entry<?, ?> entry : items.entrySet()) {
                    String itemId = entry.getKey().toString();
                    int quantity = JsonUtils.toInt(entry.getValue());
                    mergedItems.merge(itemId, quantity, Integer::sum);
                }
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", characterId);
            res.put("xp", totalXp);
            res.put("items", mergedItems);
            return res;
        }
    }

    public boolean playCampaignWorldEventExists(String campaignId, String eventId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_world_events WHERE campaign_id = " + quote(campaignId) + " AND event_id = " + quote(eventId) + ";") > 0;
        }
    }

    public boolean insertPlayCampaignWorldEvent(String campaignId, String eventId, int turnNumber, String title, String text) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_world_events (campaign_id, event_id, turn_number, title, text, status) VALUES (" + quote(campaignId) + ", " + quote(eventId) + ", " + turnNumber + ", " + quote(title) + ", " + quote(text) + ", 'scheduled');",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignWorldEvent(String campaignId, String eventId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT event_id, turn_number, title, text, status, resolution_turn_number, resolution_text FROM play_campaign_world_events WHERE campaign_id = " + quote(campaignId) + " AND event_id = " + quote(eventId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("event_id", row.get("event_id"));
            res.put("turn_number", JsonUtils.toInt(row.get("turn_number")));
            res.put("title", row.get("title"));
            res.put("text", row.get("text"));
            res.put("status", row.get("status"));
            Object resolutionTurn = row.get("resolution_turn_number");
            Object resolutionText = row.get("resolution_text");
            if (resolutionTurn != null && resolutionText != null) {
                Map<String, Object> resolution = new LinkedHashMap<>();
                resolution.put("turn_number", JsonUtils.toInt(resolutionTurn));
                resolution.put("text", resolutionText);
                res.put("resolution", resolution);
            }
            return res;
        }
    }

    public boolean resolvePlayCampaignWorldEvent(String campaignId, String eventId, int turnNumber, String text) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "UPDATE play_campaign_world_events SET status = 'resolved', resolution_turn_number = " + turnNumber + ", resolution_text = " + quote(text) + " WHERE campaign_id = " + quote(campaignId) + " AND event_id = " + quote(eventId) + " AND status = 'scheduled';",
                    "COMMIT;"
                );
                Map<String, Object> event = getPlayCampaignWorldEvent(campaignId, eventId);
                return event != null && "resolved".equals(event.get("status"));
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public List<Map<String, Object>> listPlayCampaignWorldEvents(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT event_id, turn_number, title, text, status, resolution_turn_number, resolution_text FROM play_campaign_world_events WHERE campaign_id = " + quote(campaignId) + " ORDER BY turn_number, rowid;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> event = new LinkedHashMap<>();
                event.put("event_id", row.get("event_id"));
                event.put("turn_number", JsonUtils.toInt(row.get("turn_number")));
                event.put("title", row.get("title"));
                event.put("text", row.get("text"));
                event.put("status", row.get("status"));
                Object resolutionTurn = row.get("resolution_turn_number");
                Object resolutionText = row.get("resolution_text");
                if (resolutionTurn != null && resolutionText != null) {
                    Map<String, Object> resolution = new LinkedHashMap<>();
                    resolution.put("turn_number", JsonUtils.toInt(resolutionTurn));
                    resolution.put("text", resolutionText);
                    event.put("resolution", resolution);
                }
                res.add(event);
            }
            return res;
        }
    }

    public boolean insertPlayCampaignCalendar(String campaignId, int day, String season) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (" + quote(campaignId) + ", " + day + ", " + quote(season) + ");",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignCalendar(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT day, season FROM play_campaign_calendars WHERE campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return null;
            return rows.get(0);
        }
    }

    public boolean advancePlayCampaignCalendar(String campaignId, int days) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "UPDATE play_campaign_calendars SET day = day + " + days + " WHERE campaign_id = " + quote(campaignId) + ";",
                    "COMMIT;"
                );
                return getPlayCampaignCalendar(campaignId) != null;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public boolean insertPlayCampaignSettlement(String campaignId, String settlementId, String name, String servicesJson, String availability, int sortOrder) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_settlements (campaign_id, settlement_id, name, services, availability, sort_order) VALUES (" + quote(campaignId) + ", " + quote(settlementId) + ", " + quote(name) + ", " + quote(servicesJson) + ", " + quote(availability) + ", " + sortOrder + ");",
                "COMMIT;"
            );
        }
    }

    public boolean updatePlayCampaignSettlement(String campaignId, String settlementId, String name, String servicesJson, String availability) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "UPDATE play_campaign_settlements SET name = " + quote(name) + ", services = " + quote(servicesJson) + ", availability = " + quote(availability) + " WHERE campaign_id = " + quote(campaignId) + " AND settlement_id = " + quote(settlementId) + ";",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public Map<String, Object> getPlayCampaignSettlement(String campaignId, String settlementId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT settlement_id, name, services, availability FROM play_campaign_settlements WHERE campaign_id = " + quote(campaignId) + " AND settlement_id = " + quote(settlementId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("settlement_id", row.get("settlement_id"));
            res.put("name", row.get("name"));
            res.put("services", parseServicesJson((String) row.get("services")));
            res.put("availability", row.get("availability"));
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignSettlements(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT settlement_id, name, services, availability FROM play_campaign_settlements WHERE campaign_id = " + quote(campaignId) + " ORDER BY sort_order;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> s = new LinkedHashMap<>();
                s.put("settlement_id", row.get("settlement_id"));
                s.put("name", row.get("name"));
                s.put("services", parseServicesJson((String) row.get("services")));
                s.put("availability", row.get("availability"));
                res.add(s);
            }
            return res;
        }
    }

    public List<String> listPlayCampaignSettlementDiscoveries(String campaignId, String settlementId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT character_id FROM play_campaign_settlement_discoveries WHERE campaign_id = " + quote(campaignId) + " AND settlement_id = " + quote(settlementId) + " ORDER BY id;");
            List<String> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                res.add((String) row.get("character_id"));
            }
            return res;
        }
    }

    public boolean insertPlayCampaignSettlementDiscovery(String campaignId, String settlementId, String characterId) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_settlement_discoveries (campaign_id, settlement_id, character_id) VALUES (" + quote(campaignId) + ", " + quote(settlementId) + ", " + quote(characterId) + ");",
                "COMMIT;"
            );
        }
    }

    public int getNextPlayCampaignSettlementSortOrder(String campaignId) {
        synchronized (lock) {
            return queryCount("SELECT COALESCE(MAX(sort_order), 0) AS c FROM play_campaign_settlements WHERE campaign_id = " + quote(campaignId) + ";") + 1;
        }
    }

    public boolean insertPlayCampaignShop(String campaignId, String settlementId, String shopId, String name, String stockJson, int buyPrice, int sellPrice) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_shops (campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price) VALUES (" + quote(campaignId) + ", " + quote(settlementId) + ", " + quote(shopId) + ", " + quote(name) + ", " + quote(stockJson) + ", " + buyPrice + ", " + sellPrice + ");",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignShop(String campaignId, String settlementId, String shopId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT shop_id, name, stock, buy_price, sell_price FROM play_campaign_shops WHERE campaign_id = " + quote(campaignId) + " AND settlement_id = " + quote(settlementId) + " AND shop_id = " + quote(shopId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("shop_id", row.get("shop_id"));
            res.put("name", row.get("name"));
            res.put("stock", parseShopStockJson((String) row.get("stock")));
            res.put("buy_price", JsonUtils.toInt(row.get("buy_price")));
            res.put("sell_price", JsonUtils.toInt(row.get("sell_price")));
            return res;
        }
    }

    public boolean updatePlayCampaignShopStock(String campaignId, String settlementId, String shopId, String stockJson) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "UPDATE play_campaign_shops SET stock = " + quote(stockJson) + " WHERE campaign_id = " + quote(campaignId) + " AND settlement_id = " + quote(settlementId) + " AND shop_id = " + quote(shopId) + ";",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public Map<String, Object> buyFromPlayCampaignShop(String campaignId, String settlementId, String shopId, String characterId, String itemId, int quantity) {
        synchronized (lock) {
            Map<String, Object> shop = getPlayCampaignShop(campaignId, settlementId, shopId);
            if (shop == null) return null;
            Integer gold = getPlayCampaignCharacterGold(campaignId, characterId);
            if (gold == null) return null;
            @SuppressWarnings("unchecked")
            Map<String, Object> stock = (Map<String, Object>) shop.get("stock");
            int currentStock = stock.containsKey(itemId) ? JsonUtils.toInt(stock.get(itemId)) : 0;
            if (currentStock < quantity) {
                Map<String, Object> err = new LinkedHashMap<>();
                err.put("error", "insufficient_stock");
                return err;
            }
            int buyPrice = JsonUtils.toInt(shop.get("buy_price"));
            int cost = buyPrice * quantity;
            if (gold < cost) {
                Map<String, Object> err = new LinkedHashMap<>();
                err.put("error", "insufficient_funds");
                return err;
            }
            int newStock = currentStock - quantity;
            Map<String, Object> newStockMap = new LinkedHashMap<>(stock);
            if (newStock > 0) {
                newStockMap.put(itemId, newStock);
            } else {
                newStockMap.remove(itemId);
            }
            String newStockJson = JsonUtils.toJson(newStockMap);
            int newGold = gold - cost;
            int currentInv = getPlayCampaignCharacterInventoryQuantity(campaignId, characterId, itemId);
            int newInv = currentInv + quantity;
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("UPDATE play_campaign_shops SET stock = " + quote(newStockJson) + " WHERE campaign_id = " + quote(campaignId) + " AND settlement_id = " + quote(settlementId) + " AND shop_id = " + quote(shopId) + ";");
            sqls.add("UPDATE play_campaign_members SET gold = " + newGold + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            if (currentInv == 0) {
                sqls.add("INSERT INTO play_campaign_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (" + quote(campaignId) + ", " + quote(characterId) + ", " + quote(itemId) + ", " + newInv + ");");
            } else {
                sqls.add("UPDATE play_campaign_character_inventory SET quantity = " + newInv + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND item_id = " + quote(itemId) + ";");
            }
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", characterId);
            res.put("item_id", itemId);
            res.put("quantity", quantity);
            res.put("gold", newGold);
            res.put("stock", Math.max(newStock, 0));
            return res;
        }
    }

    public Map<String, Object> sellToPlayCampaignShop(String campaignId, String settlementId, String shopId, String characterId, String itemId, int quantity) {
        synchronized (lock) {
            Map<String, Object> shop = getPlayCampaignShop(campaignId, settlementId, shopId);
            if (shop == null) return null;
            Integer gold = getPlayCampaignCharacterGold(campaignId, characterId);
            if (gold == null) return null;
            int currentInv = getPlayCampaignCharacterInventoryQuantity(campaignId, characterId, itemId);
            if (currentInv < quantity) {
                Map<String, Object> err = new LinkedHashMap<>();
                err.put("error", "insufficient_stock");
                return err;
            }
            int sellPrice = JsonUtils.toInt(shop.get("sell_price"));
            int goldGain = sellPrice * quantity;
            int newGold = gold + goldGain;
            @SuppressWarnings("unchecked")
            Map<String, Object> stock = (Map<String, Object>) shop.get("stock");
            int currentStock = stock.containsKey(itemId) ? JsonUtils.toInt(stock.get(itemId)) : 0;
            int newStock = currentStock + quantity;
            Map<String, Object> newStockMap = new LinkedHashMap<>(stock);
            newStockMap.put(itemId, newStock);
            String newStockJson = JsonUtils.toJson(newStockMap);
            int newInv = currentInv - quantity;
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("UPDATE play_campaign_shops SET stock = " + quote(newStockJson) + " WHERE campaign_id = " + quote(campaignId) + " AND settlement_id = " + quote(settlementId) + " AND shop_id = " + quote(shopId) + ";");
            sqls.add("UPDATE play_campaign_members SET gold = " + newGold + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            if (newInv == 0) {
                sqls.add("DELETE FROM play_campaign_character_inventory WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND item_id = " + quote(itemId) + ";");
            } else {
                sqls.add("UPDATE play_campaign_character_inventory SET quantity = " + newInv + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND item_id = " + quote(itemId) + ";");
            }
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", characterId);
            res.put("item_id", itemId);
            res.put("quantity", quantity);
            res.put("gold", newGold);
            res.put("stock", newStock);
            return res;
        }
    }

    public int getNextPlayCampaignRecipeSortOrder(String campaignId) {
        synchronized (lock) {
            return queryCount("SELECT COALESCE(MAX(sort_order), 0) AS c FROM play_campaign_recipes WHERE campaign_id = " + quote(campaignId) + ";") + 1;
        }
    }

    public boolean insertPlayCampaignRecipe(String campaignId, String recipeId, String name, String outputItem, int outputQuantity, String ingredientsJson, int sortOrder) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_recipes (campaign_id, recipe_id, name, output_item, output_quantity, ingredients, sort_order) VALUES (" + quote(campaignId) + ", " + quote(recipeId) + ", " + quote(name) + ", " + quote(outputItem) + ", " + outputQuantity + ", " + quote(ingredientsJson) + ", " + sortOrder + ");",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignRecipe(String campaignId, String recipeId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT recipe_id, name, output_item, output_quantity, ingredients FROM play_campaign_recipes WHERE campaign_id = " + quote(campaignId) + " AND recipe_id = " + quote(recipeId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("recipe_id", row.get("recipe_id"));
            res.put("name", row.get("name"));
            res.put("ingredients", parseIngredientsJson((String) row.get("ingredients")));
            res.put("output_item", row.get("output_item"));
            res.put("output_quantity", JsonUtils.toInt(row.get("output_quantity")));
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignRecipes(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT recipe_id, name, output_item, output_quantity, ingredients FROM play_campaign_recipes WHERE campaign_id = " + quote(campaignId) + " ORDER BY sort_order;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> recipe = new LinkedHashMap<>();
                recipe.put("recipe_id", row.get("recipe_id"));
                recipe.put("name", row.get("name"));
                recipe.put("ingredients", parseIngredientsJson((String) row.get("ingredients")));
                recipe.put("output_item", row.get("output_item"));
                recipe.put("output_quantity", JsonUtils.toInt(row.get("output_quantity")));
                res.add(recipe);
            }
            return res;
        }
    }

    public Map<String, Object> craftPlayCampaignRecipe(String campaignId, String recipeId, String characterId) {
        synchronized (lock) {
            Map<String, Object> recipe = getPlayCampaignRecipe(campaignId, recipeId);
            if (recipe == null) return null;
            @SuppressWarnings("unchecked")
            Map<String, Object> ingredients = (Map<String, Object>) recipe.get("ingredients");
            String outputItem = (String) recipe.get("output_item");
            int outputQuantity = JsonUtils.toInt(recipe.get("output_quantity"));

            List<Map<String, Object>> charRows = query("SELECT owner FROM play_campaign_members WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + ";");
            if (charRows.isEmpty()) return null;

            for (Map.Entry<String, Object> entry : ingredients.entrySet()) {
                String itemId = entry.getKey();
                int required = JsonUtils.toInt(entry.getValue());
                int have = getPlayCampaignCharacterInventoryQuantity(campaignId, characterId, itemId);
                if (have < required) {
                    Map<String, Object> err = new LinkedHashMap<>();
                    err.put("error", "insufficient_ingredients");
                    return err;
                }
            }

            Map<String, Integer> deltas = new LinkedHashMap<>();
            for (Map.Entry<String, Object> entry : ingredients.entrySet()) {
                String itemId = entry.getKey();
                int required = JsonUtils.toInt(entry.getValue());
                deltas.put(itemId, deltas.getOrDefault(itemId, 0) - required);
            }
            deltas.put(outputItem, deltas.getOrDefault(outputItem, 0) + outputQuantity);

            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            for (Map.Entry<String, Integer> entry : deltas.entrySet()) {
                String itemId = entry.getKey();
                int delta = entry.getValue();
                int current = getPlayCampaignCharacterInventoryQuantity(campaignId, characterId, itemId);
                int finalQuantity = current + delta;
                if (finalQuantity < 0) {
                    Map<String, Object> err = new LinkedHashMap<>();
                    err.put("error", "insufficient_ingredients");
                    return err;
                }
                if (finalQuantity == 0 && current > 0) {
                    sqls.add("DELETE FROM play_campaign_character_inventory WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND item_id = " + quote(itemId) + ";");
                } else if (current == 0 && finalQuantity > 0) {
                    sqls.add("INSERT INTO play_campaign_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (" + quote(campaignId) + ", " + quote(characterId) + ", " + quote(itemId) + ", " + finalQuantity + ");");
                } else if (current != finalQuantity) {
                    sqls.add("UPDATE play_campaign_character_inventory SET quantity = " + finalQuantity + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND item_id = " + quote(itemId) + ";");
                }
            }
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", characterId);
            res.put("recipe_id", recipeId);
            res.put("output_item", outputItem);
            res.put("output_quantity", outputQuantity);
            return res;
        }
    }

    public boolean insertPlayCampaignDowntimeActivity(String campaignId, String activityId, String name, int cyclesRequired) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_downtime_activities (campaign_id, activity_id, name, cycles_required) VALUES (" + quote(campaignId) + ", " + quote(activityId) + ", " + quote(name) + ", " + cyclesRequired + ");",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignDowntimeActivity(String campaignId, String activityId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT activity_id, name, cycles_required FROM play_campaign_downtime_activities WHERE campaign_id = " + quote(campaignId) + " AND activity_id = " + quote(activityId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("activity_id", row.get("activity_id"));
            res.put("name", row.get("name"));
            res.put("cycles_required", JsonUtils.toInt(row.get("cycles_required")));
            return res;
        }
    }

    public boolean insertPlayCampaignDowntimeAllocation(String campaignId, String characterId, String activityId) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (" + quote(campaignId) + ", " + quote(characterId) + ", " + quote(activityId) + ", 0, 0);",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignDowntimeAllocation(String campaignId, String characterId, String activityId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT character_id, activity_id, cycles_completed, completions FROM play_campaign_downtime_allocations WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND activity_id = " + quote(activityId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", row.get("character_id"));
            res.put("activity_id", row.get("activity_id"));
            res.put("cycles_completed", JsonUtils.toInt(row.get("cycles_completed")));
            res.put("completions", JsonUtils.toInt(row.get("completions")));
            return res;
        }
    }

    public Map<String, Object> progressPlayCampaignDowntimeAllocation(String campaignId, String characterId, String activityId) {
        synchronized (lock) {
            Map<String, Object> allocation = getPlayCampaignDowntimeAllocation(campaignId, characterId, activityId);
            if (allocation == null) return null;
            Map<String, Object> activity = getPlayCampaignDowntimeActivity(campaignId, activityId);
            if (activity == null) return null;
            int cyclesCompleted = JsonUtils.toInt(allocation.get("cycles_completed"));
            int completions = JsonUtils.toInt(allocation.get("completions"));
            int cyclesRequired = JsonUtils.toInt(activity.get("cycles_required"));
            cyclesCompleted++;
            if (cyclesCompleted >= cyclesRequired) {
                cyclesCompleted = 0;
                completions++;
            }
            execSql(
                "BEGIN;",
                "UPDATE play_campaign_downtime_allocations SET cycles_completed = " + cyclesCompleted + ", completions = " + completions + " WHERE campaign_id = " + quote(campaignId) + " AND character_id = " + quote(characterId) + " AND activity_id = " + quote(activityId) + ";",
                "COMMIT;"
            );
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("character_id", characterId);
            res.put("activity_id", activityId);
            res.put("cycles_completed", cyclesCompleted);
            res.put("completions", completions);
            return res;
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> parseIngredientsJson(String json) {
        Map<String, Object> parsed = JsonUtils.parseJsonObject(json);
        Map<String, Object> res = new LinkedHashMap<>();
        for (Map.Entry<?, ?> entry : parsed.entrySet()) {
            res.put(entry.getKey().toString(), JsonUtils.toInt(entry.getValue()));
        }
        return res;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> parseShopStockJson(String json) {
        Map<String, Object> parsed = JsonUtils.parseJsonObject(json);
        Map<String, Object> res = new LinkedHashMap<>();
        for (Map.Entry<?, ?> entry : parsed.entrySet()) {
            res.put(entry.getKey().toString(), JsonUtils.toInt(entry.getValue()));
        }
        return res;
    }

    @SuppressWarnings("unchecked")
    private List<String> parseServicesJson(String json) {
        if (json == null || json.isEmpty()) return new ArrayList<>();
        Object parsed = JsonUtils.parseJson(json);
        if (!(parsed instanceof List)) return new ArrayList<>();
        List<String> res = new ArrayList<>();
        for (Object o : (List<Object>) parsed) {
            res.add(o.toString());
        }
        return res;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> parseRewardItems(String json) {
        if (json == null || json.isEmpty() || "{}".equals(json)) {
            return new LinkedHashMap<>();
        }
        Map<String, Object> parsed = JsonUtils.parseJsonObject(json);
        Map<String, Object> res = new LinkedHashMap<>();
        for (Map.Entry<?, ?> entry : parsed.entrySet()) {
            res.put(entry.getKey().toString(), JsonUtils.toInt(entry.getValue()));
        }
        return res;
    }

    public boolean setPlayCampaignSessionZero(String campaignId, String rules, String tone, List<String> consent) {
        synchronized (lock) {
            String consentJson = JsonUtils.toJson(consent);
            try {
                execSql(
                    "BEGIN;",
                    "INSERT INTO play_campaign_session_zero (campaign_id, rules, tone, consent_json) VALUES (" + quote(campaignId) + ", " + quote(rules) + ", " + quote(tone) + ", " + quote(consentJson) + ") ON CONFLICT(campaign_id) DO UPDATE SET rules = excluded.rules, tone = excluded.tone, consent_json = excluded.consent_json;",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> getPlayCampaignSessionZero(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT rules, tone, consent_json FROM play_campaign_session_zero WHERE campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("rules", row.get("rules"));
            res.put("tone", row.get("tone"));
            res.put("consent", JsonUtils.parseJson((String) row.get("consent_json")));
            return res;
        }
    }

    public int getNextPlayCampaignContentSortOrder(String campaignId) {
        synchronized (lock) {
            return queryCount("SELECT COALESCE(MAX(sort_order), 0) AS c FROM play_campaign_content WHERE campaign_id = " + quote(campaignId) + ";") + 1;
        }
    }

    public boolean playCampaignContentExists(String campaignId, String contentId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_content WHERE campaign_id = " + quote(campaignId) + " AND content_id = " + quote(contentId) + ";") > 0;
        }
    }

    public boolean insertPlayCampaignContent(String campaignId, String contentId, String kind, String text, String tagsJson, int sortOrder) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_content (campaign_id, content_id, kind, text, tags_json, sort_order) VALUES (" + quote(campaignId) + ", " + quote(contentId) + ", " + quote(kind) + ", " + quote(text) + ", " + quote(tagsJson) + ", " + sortOrder + ");",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignContent(String campaignId, String contentId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT content_id, kind, text, tags_json FROM play_campaign_content WHERE campaign_id = " + quote(campaignId) + " AND content_id = " + quote(contentId) + ";");
            if (rows.isEmpty()) return null;
            return contentRowToMap(rows.get(0));
        }
    }

    public boolean updatePlayCampaignContentTags(String campaignId, String contentId, String tagsJson) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "UPDATE play_campaign_content SET tags_json = " + quote(tagsJson) + " WHERE campaign_id = " + quote(campaignId) + " AND content_id = " + quote(contentId) + ";",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public List<Map<String, Object>> listPlayCampaignContent(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT content_id, kind, text, tags_json FROM play_campaign_content WHERE campaign_id = " + quote(campaignId) + " ORDER BY sort_order;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                res.add(contentRowToMap(row));
            }
            return res;
        }
    }

    private Map<String, Object> contentRowToMap(Map<String, Object> row) {
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("content_id", row.get("content_id"));
        res.put("kind", row.get("kind"));
        res.put("text", row.get("text"));
        res.put("tags", parseTagsJson((String) row.get("tags_json")));
        return res;
    }

    @SuppressWarnings("unchecked")
    private List<String> parseTagsJson(String json) {
        Object parsed = JsonUtils.parseJson(json);
        if (!(parsed instanceof List)) return new ArrayList<>();
        List<String> res = new ArrayList<>();
        for (Object o : (List<Object>) parsed) {
            res.add(o.toString());
        }
        return res;
    }

    public int getNextPlayCampaignNoteSortOrder(String campaignId) {
        synchronized (lock) {
            return queryCount("SELECT COALESCE(MAX(sort_order), 0) AS c FROM play_campaign_notes WHERE campaign_id = " + quote(campaignId) + ";") + 1;
        }
    }

    public boolean playCampaignNoteExists(String campaignId, String noteId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_notes WHERE campaign_id = " + quote(campaignId) + " AND note_id = " + quote(noteId) + ";") > 0;
        }
    }

    public boolean insertPlayCampaignNote(String campaignId, String noteId, String text, String visibility, String owner, int sortOrder) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_notes (campaign_id, note_id, text, visibility, owner, sort_order) VALUES (" + quote(campaignId) + ", " + quote(noteId) + ", " + quote(text) + ", " + quote(visibility) + ", " + quote(owner) + ", " + sortOrder + ");",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignNote(String campaignId, String noteId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = " + quote(campaignId) + " AND note_id = " + quote(noteId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("note_id", row.get("note_id"));
            res.put("text", row.get("text"));
            res.put("visibility", row.get("visibility"));
            res.put("owner", row.get("owner"));
            return res;
        }
    }

    public boolean updatePlayCampaignNote(String campaignId, String noteId, String text, String visibility) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "UPDATE play_campaign_notes SET text = " + quote(text) + ", visibility = " + quote(visibility) + " WHERE campaign_id = " + quote(campaignId) + " AND note_id = " + quote(noteId) + ";",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public List<Map<String, Object>> listPlayCampaignNotes(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = " + quote(campaignId) + " ORDER BY sort_order;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> note = new LinkedHashMap<>();
                note.put("note_id", row.get("note_id"));
                note.put("text", row.get("text"));
                note.put("visibility", row.get("visibility"));
                note.put("owner", row.get("owner"));
                res.add(note);
            }
            return res;
        }
    }

    public boolean playCampaignWhisperExists(String campaignId, String whisperId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_whispers WHERE campaign_id = " + quote(campaignId) + " AND whisper_id = " + quote(whisperId) + ";") > 0;
        }
    }

    public boolean insertPlayCampaignWhisper(String campaignId, String whisperId, String fromCharacterId, String toCharacterId, String text) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text) VALUES (" + quote(campaignId) + ", " + quote(whisperId) + ", " + quote(fromCharacterId) + ", " + quote(toCharacterId) + ", " + quote(text) + ");",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignWhisper(String campaignId, String whisperId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers WHERE campaign_id = " + quote(campaignId) + " AND whisper_id = " + quote(whisperId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("whisper_id", row.get("whisper_id"));
            res.put("from_character_id", row.get("from_character_id"));
            res.put("to_character_id", row.get("to_character_id"));
            res.put("text", row.get("text"));
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignWhispers(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers WHERE campaign_id = " + quote(campaignId) + " ORDER BY rowid;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> whisper = new LinkedHashMap<>();
                whisper.put("whisper_id", row.get("whisper_id"));
                whisper.put("from_character_id", row.get("from_character_id"));
                whisper.put("to_character_id", row.get("to_character_id"));
                whisper.put("text", row.get("text"));
                res.add(whisper);
            }
            return res;
        }
    }

    public boolean insertPlayCampaignInvitation(String campaignId, String invitationId, String username, String characterId) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_invitations (campaign_id, invitation_id, username, character_id, status) VALUES (" + quote(campaignId) + ", " + quote(invitationId) + ", " + quote(username) + ", " + quote(characterId) + ", 'pending');",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> getPlayCampaignInvitation(String campaignId, String invitationId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = " + quote(campaignId) + " AND invitation_id = " + quote(invitationId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("invitation_id", row.get("invitation_id"));
            res.put("username", row.get("username"));
            res.put("character_id", row.get("character_id"));
            res.put("status", row.get("status"));
            return res;
        }
    }

    public boolean hasPendingPlayCampaignInvitationForUser(String campaignId, String username) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_invitations WHERE campaign_id = " + quote(campaignId) + " AND username = " + quote(username) + " AND status = 'pending';") > 0;
        }
    }

    public boolean hasPlayCampaignInvitationForUser(String campaignId, String username) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_invitations WHERE campaign_id = " + quote(campaignId) + " AND username = " + quote(username) + ";") > 0;
        }
    }

    public List<Map<String, Object>> listPlayCampaignInvitations(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = " + quote(campaignId) + " ORDER BY rowid;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> inv = new LinkedHashMap<>();
                inv.put("invitation_id", row.get("invitation_id"));
                inv.put("username", row.get("username"));
                inv.put("character_id", row.get("character_id"));
                inv.put("status", row.get("status"));
                res.add(inv);
            }
            return res;
        }
    }

    public boolean acceptPlayCampaignInvitation(String campaignId, String invitationId, String username, String characterId) {
        synchronized (lock) {
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("UPDATE play_campaign_invitations SET status = 'accepted' WHERE campaign_id = " + quote(campaignId) + " AND invitation_id = " + quote(invitationId) + " AND username = " + quote(username) + " AND status = 'pending';");
            sqls.add("INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, owner, hp_current, hp_max, status, death_save_successes, death_save_failures) VALUES (" + quote(campaignId) + ", " + quote(username) + ", " + quote(characterId) + ", " + quote(characterId) + ", '', " + quote(username) + ", 20, 20, 'conscious', 0, 0);");
            sqls.add("COMMIT;");
            return executeInsert(sqls);
        }
    }

    public Map<String, Object> getPlayCampaignDelegation(String campaignId, String username) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT username, powers_json, active FROM play_campaign_delegations WHERE campaign_id = " + quote(campaignId) + " AND username = " + quote(username) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("username", row.get("username"));
            String powersJson = (String) row.get("powers_json");
            Object parsed = powersJson == null ? new ArrayList<>() : JsonUtils.parseJson(powersJson);
            res.put("powers", parsed instanceof List ? (List<?>) parsed : new ArrayList<>());
            res.put("active", JsonUtils.toInt(row.get("active")) == 1);
            return res;
        }
    }

    public Map<String, Object> grantPlayCampaignDelegation(String campaignId, String username, List<String> powers) {
        synchronized (lock) {
            Map<String, Object> existing = getPlayCampaignDelegation(campaignId, username);
            String powersJson = JsonUtils.toJson(powers);
            if (existing == null) {
                boolean ok = executeInsert(
                    "BEGIN;",
                    "INSERT INTO play_campaign_delegations (campaign_id, username, powers_json, active) VALUES (" + quote(campaignId) + ", " + quote(username) + ", " + quote(powersJson) + ", 1);",
                    "COMMIT;"
                );
                if (!ok) return null;
            } else {
                if (Boolean.TRUE.equals(existing.get("active"))) {
                    return null;
                }
                execSql(
                    "BEGIN;",
                    "UPDATE play_campaign_delegations SET powers_json = " + quote(powersJson) + ", active = 1 WHERE campaign_id = " + quote(campaignId) + " AND username = " + quote(username) + ";",
                    "COMMIT;"
                );
            }
            execSql("INSERT INTO play_campaign_delegation_audit (campaign_id, username, action, powers_json) VALUES (" + quote(campaignId) + ", " + quote(username) + ", 'granted', " + quote(powersJson) + ");");
            return getPlayCampaignDelegation(campaignId, username);
        }
    }

    public Map<String, Object> revokePlayCampaignDelegation(String campaignId, String username) {
        synchronized (lock) {
            Map<String, Object> existing = getPlayCampaignDelegation(campaignId, username);
            if (existing == null) return null;
            String powersJson = JsonUtils.toJson(existing.get("powers"));
            if (Boolean.TRUE.equals(existing.get("active"))) {
                execSql(
                    "BEGIN;",
                    "UPDATE play_campaign_delegations SET active = 0 WHERE campaign_id = " + quote(campaignId) + " AND username = " + quote(username) + ";",
                    "COMMIT;"
                );
                execSql("INSERT INTO play_campaign_delegation_audit (campaign_id, username, action, powers_json) VALUES (" + quote(campaignId) + ", " + quote(username) + ", 'revoked', " + quote(powersJson) + ");");
            }
            existing.put("active", false);
            return existing;
        }
    }

    public boolean hasActivePlayCampaignDelegationPower(String campaignId, String username, String power) {
        Map<String, Object> delegation = getPlayCampaignDelegation(campaignId, username);
        if (delegation == null || !Boolean.TRUE.equals(delegation.get("active"))) return false;
        Object powers = delegation.get("powers");
        if (powers instanceof List) {
            return ((List<?>) powers).contains(power);
        }
        return false;
    }

    public List<Map<String, Object>> listPlayCampaignDelegationAudit(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT username, action, powers_json FROM play_campaign_delegation_audit WHERE campaign_id = " + quote(campaignId) + " ORDER BY rowid;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> e = new LinkedHashMap<>();
                e.put("username", row.get("username"));
                e.put("action", row.get("action"));
                String powersJson = (String) row.get("powers_json");
                Object parsed = powersJson == null ? new ArrayList<>() : JsonUtils.parseJson(powersJson);
                e.put("powers", parsed instanceof List ? (List<?>) parsed : new ArrayList<>());
                res.add(e);
            }
            return res;
        }
    }

    public Map<String, Object> createPlayCampaignAuditEvent(String campaignId, String actor, String role, String kind, String correlationId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(timestamp), 0) AS max_ts FROM play_campaign_audit_events WHERE campaign_id = " + quote(campaignId) + ";");
            int nextTs = JsonUtils.toInt(rows.get(0).get("max_ts")) + 1;
            boolean ok = executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_audit_events (campaign_id, kind, actor, role, timestamp, correlation_id) VALUES (" + quote(campaignId) + ", " + quote(kind) + ", " + quote(actor) + ", " + quote(role) + ", " + nextTs + ", " + quote(correlationId) + ");",
                "COMMIT;"
            );
            if (!ok) return null;
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("kind", kind);
            res.put("actor", actor);
            res.put("role", role);
            res.put("timestamp", nextTs);
            res.put("correlation_id", correlationId);
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignAuditEvents(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT kind, actor, role, timestamp, correlation_id FROM play_campaign_audit_events WHERE campaign_id = " + quote(campaignId) + " ORDER BY timestamp;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> e = new LinkedHashMap<>();
                e.put("kind", row.get("kind"));
                e.put("actor", row.get("actor"));
                e.put("role", row.get("role"));
                e.put("timestamp", JsonUtils.toInt(row.get("timestamp")));
                e.put("correlation_id", row.get("correlation_id"));
                res.add(e);
            }
            return res;
        }
    }

    public boolean playCampaignProjectionEventExists(String campaignId, String eventId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_projection_events WHERE campaign_id = " + quote(campaignId) + " AND event_id = " + quote(eventId) + ";") > 0;
        }
    }

    public Map<String, Object> insertPlayCampaignProjectionEvent(String campaignId, String eventId, String kind, String value) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_projection_events WHERE campaign_id = " + quote(campaignId) + ";");
            int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
            String valueSql = value == null ? "NULL" : quote(value);
            execSql(
                "BEGIN;",
                "INSERT INTO play_campaign_projection_events (campaign_id, sequence, event_id, kind, value) VALUES (" + quote(campaignId) + ", " + nextSeq + ", " + quote(eventId) + ", " + quote(kind) + ", " + valueSql + ");",
                "COMMIT;"
            );
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("sequence", nextSeq);
            res.put("event_id", eventId);
            res.put("kind", kind);
            if (value != null) res.put("value", value);
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignProjectionEvents(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT sequence, event_id, kind, value FROM play_campaign_projection_events WHERE campaign_id = " + quote(campaignId) + " ORDER BY sequence;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> e = new LinkedHashMap<>();
                e.put("sequence", JsonUtils.toInt(row.get("sequence")));
                e.put("event_id", row.get("event_id"));
                e.put("kind", row.get("kind"));
                Object value = row.get("value");
                if (value != null) e.put("value", value);
                res.add(e);
            }
            return res;
        }
    }

    public Map<String, Object> buildPlayCampaignProjection(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> events = listPlayCampaignProjectionEvents(campaignId);
            String story = "";
            int danger = 0;
            List<String> appliedEventIds = new ArrayList<>();
            for (Map<String, Object> event : events) {
                String kind = (String) event.get("kind");
                String eventId = (String) event.get("event_id");
                appliedEventIds.add(eventId);
                if ("set-story".equals(kind)) {
                    Object value = event.get("value");
                    if (value != null) story = value.toString();
                } else if ("increment-danger".equals(kind)) {
                    danger++;
                }
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("story", story);
            res.put("danger", danger);
            res.put("applied_event_ids", appliedEventIds);
            return res;
        }
    }

    public Map<String, Object> getPlayCampaignIdempotentEventByKey(String campaignId, String idempotencyKey) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT sequence, event_id, value, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = " + quote(campaignId) + " AND idempotency_key = " + quote(idempotencyKey) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("event_id", row.get("event_id"));
            res.put("value", row.get("value"));
            res.put("sequence", JsonUtils.toInt(row.get("sequence")));
            res.put("idempotency_key", row.get("idempotency_key"));
            return res;
        }
    }

    public boolean playCampaignIdempotentEventIdExists(String campaignId, String eventId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_idempotent_events WHERE campaign_id = " + quote(campaignId) + " AND event_id = " + quote(eventId) + ";") > 0;
        }
    }

    public Map<String, Object> insertPlayCampaignIdempotentEvent(String campaignId, String eventId, String value, String idempotencyKey) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_idempotent_events WHERE campaign_id = " + quote(campaignId) + ";");
            int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
            execSql(
                "BEGIN;",
                "INSERT INTO play_campaign_idempotent_events (campaign_id, sequence, event_id, value, idempotency_key) VALUES (" + quote(campaignId) + ", " + nextSeq + ", " + quote(eventId) + ", " + quote(value) + ", " + quote(idempotencyKey) + ");",
                "COMMIT;"
            );
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("event_id", eventId);
            res.put("value", value);
            res.put("sequence", nextSeq);
            res.put("idempotency_key", idempotencyKey);
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignIdempotentEvents(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT sequence, event_id, value, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = " + quote(campaignId) + " ORDER BY sequence;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> e = new LinkedHashMap<>();
                e.put("event_id", row.get("event_id"));
                e.put("value", row.get("value"));
                e.put("sequence", JsonUtils.toInt(row.get("sequence")));
                e.put("idempotency_key", row.get("idempotency_key"));
                res.add(e);
            }
            return res;
        }
    }

    public int getPlayCampaignSafeTurnCurrent(String campaignId) {
        synchronized (lock) {
            execSql("INSERT OR IGNORE INTO play_campaign_safe_turn_state (campaign_id, current_turn) VALUES (" + quote(campaignId) + ", 1);");
            List<Map<String, Object>> rows = query("SELECT current_turn FROM play_campaign_safe_turn_state WHERE campaign_id = " + quote(campaignId) + ";");
            return JsonUtils.toInt(rows.get(0).get("current_turn"));
        }
    }

    public List<Map<String, Object>> listPlayCampaignSafeTurns(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT submission_id, action, accepted_turn, next_turn FROM play_campaign_safe_turns WHERE campaign_id = " + quote(campaignId) + " ORDER BY accepted_turn;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> e = new LinkedHashMap<>();
                e.put("submission_id", row.get("submission_id"));
                e.put("action", row.get("action"));
                e.put("accepted_turn", JsonUtils.toInt(row.get("accepted_turn")));
                e.put("next_turn", JsonUtils.toInt(row.get("next_turn")));
                res.add(e);
            }
            return res;
        }
    }

    /**
     * Atomically submits a safe turn. The returned map contains a "status" key
     * with one of "accepted", "stale", or "duplicate". For accepted submissions
     * the map also contains submission_id, action, accepted_turn, and next_turn.
     * For stale submissions it contains current_turn. Duplicate submissions carry
     * no extra keys.
     */
    public Map<String, Object> submitPlayCampaignSafeTurn(String campaignId, String submissionId, String action, int expectedTurn) {
        synchronized (lock) {
            execSql("INSERT OR IGNORE INTO play_campaign_safe_turn_state (campaign_id, current_turn) VALUES (" + quote(campaignId) + ", 1);");
            List<Map<String, Object>> dupRows = query("SELECT 1 FROM play_campaign_safe_turns WHERE campaign_id = " + quote(campaignId) + " AND submission_id = " + quote(submissionId) + ";");
            if (!dupRows.isEmpty()) {
                Map<String, Object> res = new LinkedHashMap<>();
                res.put("status", "duplicate");
                return res;
            }
            List<Map<String, Object>> rows = query("SELECT current_turn FROM play_campaign_safe_turn_state WHERE campaign_id = " + quote(campaignId) + ";");
            int currentTurn = JsonUtils.toInt(rows.get(0).get("current_turn"));
            if (expectedTurn != currentTurn) {
                Map<String, Object> res = new LinkedHashMap<>();
                res.put("status", "stale");
                res.put("current_turn", currentTurn);
                return res;
            }
            int nextTurn = currentTurn + 1;
            boolean ok = executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_safe_turns (campaign_id, submission_id, action, accepted_turn, next_turn) VALUES (" + quote(campaignId) + ", " + quote(submissionId) + ", " + quote(action) + ", " + currentTurn + ", " + nextTurn + ");",
                "UPDATE play_campaign_safe_turn_state SET current_turn = " + nextTurn + " WHERE campaign_id = " + quote(campaignId) + ";",
                "COMMIT;"
            );
            if (!ok) {
                Map<String, Object> res = new LinkedHashMap<>();
                res.put("status", "duplicate");
                return res;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("status", "accepted");
            res.put("submission_id", submissionId);
            res.put("action", action);
            res.put("accepted_turn", currentTurn);
            res.put("next_turn", nextTurn);
            return res;
        }
    }

    public Map<String, Object> createPlayCampaignExport(String campaignId) {
        synchronized (lock) {
            Map<String, Object> doc = getPlayCampaignDocument(campaignId);
            String story = doc == null ? "" : (String) doc.get("story");
            Map<String, Object> campaign = getPlayCampaign(campaignId);
            String status = campaign == null ? "" : (String) campaign.get("status");
            int count = queryCount("SELECT COUNT(*) AS c FROM play_campaign_exports WHERE campaign_id = " + quote(campaignId) + ";");
            int version = count + 1;
            execSql(
                "BEGIN;",
                "INSERT INTO play_campaign_exports (campaign_id, version, story, status) VALUES (" + quote(campaignId) + ", " + version + ", " + quote(story) + ", " + quote(status) + ");",
                "COMMIT;"
            );
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("version", version);
            res.put("story", story);
            res.put("status", status);
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignExports(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = " + quote(campaignId) + " ORDER BY version ASC;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> e = new LinkedHashMap<>();
                e.put("version", JsonUtils.toInt(row.get("version")));
                e.put("story", row.get("story"));
                e.put("status", row.get("status"));
                res.add(e);
            }
            return res;
        }
    }

    public Map<String, Object> getPlayCampaignExport(String campaignId, int version) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = " + quote(campaignId) + " AND version = " + version + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("version", JsonUtils.toInt(row.get("version")));
            res.put("story", row.get("story"));
            res.put("status", row.get("status"));
            return res;
        }
    }

    public Map<String, Object> createPlayCampaignImport(String campaignId, int version, String story, String status) {
        synchronized (lock) {
            execSql(
                "BEGIN;",
                "INSERT OR REPLACE INTO play_campaign_imports (campaign_id, version, story, status) VALUES (" + quote(campaignId) + ", " + version + ", " + quote(story) + ", " + quote(status) + ");",
                "UPDATE play_campaigns SET story = " + quote(story) + ", status = " + quote(status) + " WHERE id = " + quote(campaignId) + ";",
                "COMMIT;"
            );
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("version", version);
            res.put("story", story);
            res.put("status", status);
            return res;
        }
    }

    public Map<String, Object> getPlayCampaignImport(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT version, story, status FROM play_campaign_imports WHERE campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("version", JsonUtils.toInt(row.get("version")));
            res.put("story", row.get("story"));
            res.put("status", row.get("status"));
            return res;
        }
    }

    public Map<String, Object> getPlayCampaignMigration(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("schema_version", JsonUtils.toInt(row.get("schema_version")));
            res.put("story", row.get("story"));
            res.put("campaign_name", row.get("campaign_name"));
            return res;
        }
    }

    public MigrationResult createPlayCampaignMigration(String campaignId, String story, String campaignName) {
        synchronized (lock) {
            Map<String, Object> existing = getPlayCampaignMigration(campaignId);
            if (existing != null) {
                return new MigrationResult(false, existing);
            }
            execSql(
                "BEGIN;",
                "INSERT INTO play_campaign_migrations (campaign_id, schema_version, story, campaign_name) VALUES (" + quote(campaignId) + ", 2, " + quote(story) + ", " + quote(campaignName) + ");",
                "COMMIT;"
            );
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("schema_version", 2);
            res.put("story", story);
            res.put("campaign_name", campaignName);
            return new MigrationResult(true, res);
        }
    }

    public boolean insertPlayCampaignSearchRecord(String campaignId, String recordId, String text) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_search_records (campaign_id, record_id, text) VALUES (" + quote(campaignId) + ", " + quote(recordId) + ", " + quote(text) + ");",
                "COMMIT;"
            );
        }
    }

    public List<Map<String, Object>> listPlayCampaignSearchRecords(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT record_id, text FROM play_campaign_search_records WHERE campaign_id = " + quote(campaignId) + " ORDER BY rowid;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> r = new LinkedHashMap<>();
                r.put("record_id", row.get("record_id"));
                r.put("text", row.get("text"));
                res.add(r);
            }
            return res;
        }
    }

    public boolean playCampaignRateEventExists(String campaignId, String eventId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_rate_events WHERE campaign_id = " + quote(campaignId) + " AND event_id = " + quote(eventId) + ";") > 0;
        }
    }

    public int countPlayCampaignRateEventsByActor(String campaignId, String actor) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_rate_events WHERE campaign_id = " + quote(campaignId) + " AND actor = " + quote(actor) + ";");
        }
    }

    public Map<String, Object> insertPlayCampaignRateEvent(String campaignId, String eventId, String actor) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_rate_events WHERE campaign_id = " + quote(campaignId) + ";");
            int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
            boolean ok = executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_rate_events (campaign_id, event_id, actor, sequence) VALUES (" + quote(campaignId) + ", " + quote(eventId) + ", " + quote(actor) + ", " + nextSeq + ");",
                "COMMIT;"
            );
            if (!ok) return null;
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("event_id", eventId);
            res.put("actor", actor);
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignRateEvents(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT event_id, actor FROM play_campaign_rate_events WHERE campaign_id = " + quote(campaignId) + " ORDER BY sequence;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> e = new LinkedHashMap<>();
                e.put("event_id", row.get("event_id"));
                e.put("actor", row.get("actor"));
                res.add(e);
            }
            return res;
        }
    }

    public Map<String, Object> getPlayCampaignMetrics(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT accepted_rate_events, rejected_rate_events, projection_events, uptime_ticks FROM play_campaign_metrics WHERE campaign_id = " + quote(campaignId) + ";");
            Map<String, Object> res = new LinkedHashMap<>();
            if (rows.isEmpty()) {
                res.put("accepted_rate_events", 0);
                res.put("rejected_rate_events", 0);
                res.put("projection_events", 0);
                res.put("uptime_ticks", 1);
            } else {
                Map<String, Object> row = rows.get(0);
                res.put("accepted_rate_events", JsonUtils.toInt(row.get("accepted_rate_events")));
                res.put("rejected_rate_events", JsonUtils.toInt(row.get("rejected_rate_events")));
                res.put("projection_events", JsonUtils.toInt(row.get("projection_events")));
                res.put("uptime_ticks", JsonUtils.toInt(row.get("uptime_ticks")));
            }
            return res;
        }
    }

    public void incrementPlayCampaignMetric(String campaignId, String metric) {
        synchronized (lock) {
            String column;
            if ("accepted_rate_events".equals(metric)) {
                column = "accepted_rate_events";
            } else if ("rejected_rate_events".equals(metric)) {
                column = "rejected_rate_events";
            } else if ("projection_events".equals(metric)) {
                column = "projection_events";
            } else {
                throw new RuntimeException("Unknown metric: " + metric);
            }
            execSql(
                "BEGIN;",
                "UPDATE play_campaign_metrics SET " + column + " = " + column + " + 1 WHERE campaign_id = " + quote(campaignId) + ";",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> createPlayCampaignBackup(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT story, status FROM play_campaigns WHERE id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return null;
            String story = (String) rows.get(0).get("story");
            String status = (String) rows.get(0).get("status");
            rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_backups WHERE campaign_id = " + quote(campaignId) + ";");
            int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
            String backupId = "backup-" + nextSeq;
            execSql(
                "BEGIN;",
                "INSERT INTO play_campaign_backups (campaign_id, backup_id, story, status, sequence) VALUES (" + quote(campaignId) + ", " + quote(backupId) + ", " + quote(story) + ", " + quote(status) + ", " + nextSeq + ");",
                "COMMIT;"
            );
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("backup_id", backupId);
            res.put("story", story);
            res.put("status", status);
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignBackups(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = " + quote(campaignId) + " ORDER BY sequence;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> b = new LinkedHashMap<>();
                b.put("backup_id", row.get("backup_id"));
                b.put("story", row.get("story"));
                b.put("status", row.get("status"));
                res.add(b);
            }
            return res;
        }
    }

    public Map<String, Object> getPlayCampaignBackup(String campaignId, String backupId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = " + quote(campaignId) + " AND backup_id = " + quote(backupId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("backup_id", row.get("backup_id"));
            res.put("story", row.get("story"));
            res.put("status", row.get("status"));
            return res;
        }
    }

    public Map<String, Object> restorePlayCampaignBackup(String campaignId, String backupId) {
        synchronized (lock) {
            Map<String, Object> backup = getPlayCampaignBackup(campaignId, backupId);
            if (backup == null) return null;
            execSql(
                "BEGIN;",
                "UPDATE play_campaigns SET story = " + quote((String) backup.get("story")) + ", status = " + quote((String) backup.get("status")) + " WHERE id = " + quote(campaignId) + ";",
                "COMMIT;"
            );
            return backup;
        }
    }

    public boolean playCampaignReplayEventExists(String campaignId, String eventId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_replay_events WHERE campaign_id = " + quote(campaignId) + " AND event_id = " + quote(eventId) + ";") > 0;
        }
    }

    public Map<String, Object> insertPlayCampaignReplayEvent(String campaignId, String eventId, String kind, String text) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_replay_events WHERE campaign_id = " + quote(campaignId) + ";");
            int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
            boolean ok = executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_replay_events (campaign_id, event_id, kind, text, sequence) VALUES (" + quote(campaignId) + ", " + quote(eventId) + ", " + quote(kind) + ", " + quote(text) + ", " + nextSeq + ");",
                "COMMIT;"
            );
            if (!ok) return null;
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("event_id", eventId);
            res.put("kind", kind);
            res.put("text", text);
            res.put("sequence", nextSeq);
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignReplayEvents(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT event_id, kind, text FROM play_campaign_replay_events WHERE campaign_id = " + quote(campaignId) + " ORDER BY sequence;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> e = new LinkedHashMap<>();
                e.put("event_id", row.get("event_id"));
                e.put("kind", row.get("kind"));
                e.put("text", row.get("text"));
                res.add(e);
            }
            return res;
        }
    }

    public String getPlayCampaignRngSeed(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT seed FROM play_campaign_rng_seed WHERE campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return null;
            return (String) rows.get(0).get("seed");
        }
    }

    public boolean setPlayCampaignRngSeed(String campaignId, String seed) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_rng_seed (campaign_id, seed) VALUES (" + quote(campaignId) + ", " + quote(seed) + ");",
                "COMMIT;"
            );
        }
    }

    public Map<String, Object> insertPlayCampaignRngRoll(String campaignId, String rollId, int sides) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_rng_rolls WHERE campaign_id = " + quote(campaignId) + ";");
            int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
            String seed = getPlayCampaignRngSeed(campaignId);
            if (seed == null) return null;
            int result = computeRngRoll(seed, nextSeq, rollId, sides);
            boolean ok = executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_rng_rolls (campaign_id, roll_id, sides, result, sequence) VALUES (" + quote(campaignId) + ", " + quote(rollId) + ", " + sides + ", " + result + ", " + nextSeq + ");",
                "COMMIT;"
            );
            if (!ok) return null;
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("roll_id", rollId);
            res.put("sides", sides);
            res.put("result", result);
            res.put("sequence", nextSeq);
            return res;
        }
    }

    private int computeRngRoll(String seed, int sequence, String rollId, int sides) {
        String input = seed + "|" + sequence + "|" + rollId + "|" + sides;
        byte[] bytes = input.getBytes(StandardCharsets.UTF_8);
        long acc = 0;
        for (byte b : bytes) {
            acc = (acc * 31 + (b & 0xFF)) % (1L << 32);
        }
        return (int) ((acc % sides) + 1);
    }

    public List<Map<String, Object>> listPlayCampaignRngRolls(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls WHERE campaign_id = " + quote(campaignId) + " ORDER BY sequence;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> e = new LinkedHashMap<>();
                e.put("roll_id", row.get("roll_id"));
                e.put("sides", JsonUtils.toInt(row.get("sides")));
                e.put("result", JsonUtils.toInt(row.get("result")));
                e.put("sequence", JsonUtils.toInt(row.get("sequence")));
                res.add(e);
            }
            return res;
        }
    }

    public boolean playCampaignModerationReportExists(String campaignId, String reportId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_moderation_reports WHERE campaign_id = " + quote(campaignId) + " AND report_id = " + quote(reportId) + ";") > 0;
        }
    }

    public Map<String, Object> insertPlayCampaignModerationReport(String campaignId, String reportId, String targetId, String reason, String reporter) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_moderation_reports WHERE campaign_id = " + quote(campaignId) + ";");
            int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
            boolean ok = executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_moderation_reports (campaign_id, report_id, target_id, reason, reporter, status, sequence) VALUES (" + quote(campaignId) + ", " + quote(reportId) + ", " + quote(targetId) + ", " + quote(reason) + ", " + quote(reporter) + ", 'open', " + nextSeq + ");",
                "COMMIT;"
            );
            if (!ok) return null;
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("report_id", reportId);
            res.put("target_id", targetId);
            res.put("reason", reason);
            res.put("status", "open");
            res.put("reporter", reporter);
            res.put("sequence", nextSeq);
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignModerationReports(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT report_id, target_id, reason, reporter, status, action, note, resolver, sequence FROM play_campaign_moderation_reports WHERE campaign_id = " + quote(campaignId) + " ORDER BY sequence;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> r = new LinkedHashMap<>();
                r.put("report_id", row.get("report_id"));
                r.put("target_id", row.get("target_id"));
                r.put("reason", row.get("reason"));
                r.put("status", row.get("status"));
                r.put("reporter", row.get("reporter"));
                r.put("sequence", JsonUtils.toInt(row.get("sequence")));
                Object action = row.get("action");
                if (action != null) r.put("action", action);
                Object note = row.get("note");
                if (note != null) r.put("note", note);
                Object resolver = row.get("resolver");
                if (resolver != null) r.put("resolver", resolver);
                res.add(r);
            }
            return res;
        }
    }

    public Map<String, Object> getPlayCampaignModerationReport(String campaignId, String reportId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT report_id, target_id, reason, reporter, status, action, note, resolver, sequence FROM play_campaign_moderation_reports WHERE campaign_id = " + quote(campaignId) + " AND report_id = " + quote(reportId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> r = new LinkedHashMap<>();
            r.put("report_id", row.get("report_id"));
            r.put("target_id", row.get("target_id"));
            r.put("reason", row.get("reason"));
            r.put("status", row.get("status"));
            r.put("reporter", row.get("reporter"));
            r.put("sequence", JsonUtils.toInt(row.get("sequence")));
            Object action = row.get("action");
            if (action != null) r.put("action", action);
            Object note = row.get("note");
            if (note != null) r.put("note", note);
            Object resolver = row.get("resolver");
            if (resolver != null) r.put("resolver", resolver);
            return r;
        }
    }

    public boolean resolvePlayCampaignModerationReport(String campaignId, String reportId, String action, String note, String resolver) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "UPDATE play_campaign_moderation_reports SET status = 'resolved', action = " + quote(action) + ", note = " + quote(note) + ", resolver = " + quote(resolver) + " WHERE campaign_id = " + quote(campaignId) + " AND report_id = " + quote(reportId) + " AND status = 'open';",
                "COMMIT;"
            );
        }
    }

    public List<String> getPlayCampaignSafetyBoundaries(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT tags_json FROM play_campaign_safety_boundaries WHERE campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return new ArrayList<>();
            return parseTagsJson((String) rows.get(0).get("tags_json"));
        }
    }

    public void replacePlayCampaignSafetyBoundaries(String campaignId, List<String> tags) {
        synchronized (lock) {
            execSql(
                "BEGIN;",
                "DELETE FROM play_campaign_safety_boundaries WHERE campaign_id = " + quote(campaignId) + ";",
                "INSERT INTO play_campaign_safety_boundaries (campaign_id, tags_json) VALUES (" + quote(campaignId) + ", " + quote(JsonUtils.toJson(tags)) + ");",
                "COMMIT;"
            );
        }
    }

    public boolean playCampaignSafetyEventExists(String campaignId, String eventId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_safety_events WHERE campaign_id = " + quote(campaignId) + " AND event_id = " + quote(eventId) + ";") > 0;
        }
    }

    public Map<String, Object> insertPlayCampaignSafetyEvent(String campaignId, String eventId, String kind, String text, List<String> tags) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_safety_events WHERE campaign_id = " + quote(campaignId) + ";");
            int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
            boolean ok = executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_safety_events (campaign_id, event_id, kind, text, tags_json, sequence) VALUES (" + quote(campaignId) + ", " + quote(eventId) + ", " + quote(kind) + ", " + quote(text) + ", " + quote(JsonUtils.toJson(tags)) + ", " + nextSeq + ");",
                "COMMIT;"
            );
            if (!ok) return null;
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("event_id", eventId);
            res.put("kind", kind);
            res.put("text", text);
            res.put("tags", tags);
            res.put("sequence", nextSeq);
            return res;
        }
    }

    public List<Map<String, Object>> listPlayCampaignSafetyEvents(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT event_id, kind, text, tags_json, sequence FROM play_campaign_safety_events WHERE campaign_id = " + quote(campaignId) + " ORDER BY sequence;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> e = new LinkedHashMap<>();
                e.put("event_id", row.get("event_id"));
                e.put("kind", row.get("kind"));
                e.put("text", row.get("text"));
                e.put("tags", parseTagsJson((String) row.get("tags_json")));
                e.put("sequence", JsonUtils.toInt(row.get("sequence")));
                res.add(e);
            }
            return res;
        }
    }

    public Map<String, Object> getPlayCampaignFixture(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT fixture_id, status, story FROM play_campaign_fixtures WHERE campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            List<Map<String, Object>> charRows = query("SELECT character_id, name, class FROM play_campaign_fixture_characters WHERE campaign_id = " + quote(campaignId) + " ORDER BY sort_order;");
            List<Map<String, Object>> characters = new ArrayList<>();
            for (Map<String, Object> cr : charRows) {
                Map<String, Object> c = new LinkedHashMap<>();
                c.put("character_id", cr.get("character_id"));
                c.put("name", cr.get("name"));
                c.put("class", cr.get("class"));
                characters.add(c);
            }
            List<Map<String, Object>> eventRows = query("SELECT event_id FROM play_campaign_fixture_events WHERE campaign_id = " + quote(campaignId) + " ORDER BY sort_order;");
            List<String> eventIds = new ArrayList<>();
            for (Map<String, Object> er : eventRows) {
                eventIds.add((String) er.get("event_id"));
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("fixture_id", row.get("fixture_id"));
            res.put("status", row.get("status"));
            res.put("characters", characters);
            res.put("story", row.get("story"));
            res.put("event_ids", eventIds);
            return res;
        }
    }

    public boolean seedPlayCampaignFixture(String campaignId) {
        synchronized (lock) {
            if (getPlayCampaignFixture(campaignId) != null) return false;
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("INSERT INTO play_campaign_fixtures (campaign_id, fixture_id, status, story) VALUES (" + quote(campaignId) + ", 'canonical-v1', 'seeded', 'The lantern is lit.');");
            sqls.add("INSERT INTO play_campaign_fixture_characters (campaign_id, character_id, name, class, sort_order) VALUES (" + quote(campaignId) + ", 'fixture-hero', 'Ari', 'fighter', 1);");
            sqls.add("INSERT INTO play_campaign_fixture_characters (campaign_id, character_id, name, class, sort_order) VALUES (" + quote(campaignId) + ", 'fixture-mage', 'Bea', 'wizard', 2);");
            sqls.add("INSERT INTO play_campaign_fixture_events (campaign_id, event_id, sort_order) VALUES (" + quote(campaignId) + ", 'fixture-event-1', 1);");
            sqls.add("INSERT INTO play_campaign_fixture_events (campaign_id, event_id, sort_order) VALUES (" + quote(campaignId) + ", 'fixture-event-2', 2);");
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));
            return true;
        }
    }

    public boolean insertPlayCampaignSpectator(String spectatorId, String campaignId) {
        synchronized (lock) {
            return executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_spectators (spectator_id, campaign_id) VALUES (" + quote(spectatorId) + ", " + quote(campaignId) + ");",
                "COMMIT;"
            );
        }
    }

    public String getPlayCampaignSpectatorCampaignId(String spectatorId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT campaign_id FROM play_campaign_spectators WHERE spectator_id = " + quote(spectatorId) + ";");
            if (rows.isEmpty()) return null;
            return (String) rows.get(0).get("campaign_id");
        }
    }

    public Map<String, Object> getPlayCampaignSpectatorView(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, name, status, story FROM play_campaigns WHERE id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            int partySize = countPlayCampaignMembers(campaignId);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("campaign_id", row.get("id"));
            res.put("name", row.get("name"));
            res.put("status", row.get("status"));
            res.put("party_size", partySize);
            res.put("story", row.get("story"));
            return res;
        }
    }

    public boolean playCampaignFeedEventExists(String campaignId, String eventId) {
        synchronized (lock) {
            return queryCount("SELECT COUNT(*) AS c FROM play_campaign_feed_events WHERE campaign_id = " + quote(campaignId) + " AND event_id = " + quote(eventId) + ";") > 0;
        }
    }

    public Map<String, Object> insertPlayCampaignFeedEvent(String campaignId, String eventId, String text) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_feed_events WHERE campaign_id = " + quote(campaignId) + ";");
            int nextSeq = JsonUtils.toInt(rows.get(0).get("max_seq")) + 1;
            boolean ok = executeInsert(
                "BEGIN;",
                "INSERT INTO play_campaign_feed_events (campaign_id, event_id, text, sequence) VALUES (" + quote(campaignId) + ", " + quote(eventId) + ", " + quote(text) + ", " + nextSeq + ");",
                "COMMIT;"
            );
            if (!ok) return null;
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("event_id", eventId);
            res.put("text", text);
            res.put("sequence", nextSeq);
            return res;
        }
    }

    public Map<String, Object> listPlayCampaignFeedEvents(String campaignId, int cursor, int limit) {
        synchronized (lock) {
            int total = queryCount("SELECT COUNT(*) AS c FROM play_campaign_feed_events WHERE campaign_id = " + quote(campaignId) + ";");
            Map<String, Object> res = new LinkedHashMap<>();
            List<Map<String, Object>> events = new ArrayList<>();
            if (cursor < total) {
                List<Map<String, Object>> rows = query("SELECT event_id, text, sequence FROM play_campaign_feed_events WHERE campaign_id = " + quote(campaignId) + " AND sequence > " + cursor + " ORDER BY sequence LIMIT " + limit + ";");
                for (Map<String, Object> row : rows) {
                    Map<String, Object> e = new LinkedHashMap<>();
                    e.put("event_id", row.get("event_id"));
                    e.put("text", row.get("text"));
                    e.put("sequence", JsonUtils.toInt(row.get("sequence")));
                    events.add(e);
                }
            }
            res.put("events", events);
            res.put("next_cursor", cursor + events.size());
            return res;
        }
    }

    public static final class MigrationResult {
        public final boolean created;
        public final Map<String, Object> snapshot;

        public MigrationResult(boolean created, Map<String, Object> snapshot) {
            this.created = created;
            this.snapshot = snapshot;
        }
    }

    /** Adds a column to an existing table, swallowing SQLite "duplicate column" errors. */
    private void addColumnIfMissing(String table, String columnDef) {
        String def = columnDef.endsWith(";") ? columnDef.substring(0, columnDef.length() - 1) : columnDef;
        try {
            execSql("ALTER TABLE " + table + " ADD COLUMN " + def + ";");
        } catch (RuntimeException e) {
            if (e.getMessage() == null || !e.getMessage().contains("duplicate column name")) {
                throw e;
            }
        }
    }

    /** SQLite string literal quoting. Only handles single quotes; inputs are controlled by handlers. */
    private String quote(String s) {
        return "'" + s.replace("'", "''") + "'";
    }

    private static boolean isUniqueConstraintViolation(RuntimeException e) {
        return e.getMessage() != null && e.getMessage().contains("UNIQUE constraint failed");
    }

    /** Executes a write transaction and maps UNIQUE violations to {@code false}. */
    private boolean executeInsert(List<String> sqls) {
        try {
            execSql(sqls.toArray(new String[0]));
            return true;
        } catch (RuntimeException e) {
            if (isUniqueConstraintViolation(e)) return false;
            throw e;
        }
    }

    private boolean executeInsert(String... sqls) {
        return executeInsert(java.util.Arrays.asList(sqls));
    }

    /** Helper for {@code SELECT COUNT(*) AS c ...} queries. */
    private int queryCount(String sql) {
        List<Map<String, Object>> rows = query(sql);
        if (rows.isEmpty()) return 0;
        return JsonUtils.toInt(rows.get(0).get("c"));
    }

    private void execSql(String... sqls) {
        try {
            List<String> cmd = new ArrayList<>();
            cmd.add("sqlite3");
            cmd.add(dbPath);
            Collections.addAll(cmd, sqls);
            ProcessBuilder pb = new ProcessBuilder(cmd);
            pb.redirectErrorStream(true);
            Process p = pb.start();
            String output = new String(p.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
            int rc = p.waitFor();
            if (rc != 0) {
                throw new RuntimeException("sqlite3 failed: " + output.trim());
            }
        } catch (IOException | InterruptedException e) {
            throw new RuntimeException(e);
        }
    }

    private List<Map<String, Object>> query(String sql) {
        try {
            List<String> cmd = new ArrayList<>();
            cmd.add("sqlite3");
            cmd.add("-json");
            cmd.add(dbPath);
            cmd.add(sql);
            ProcessBuilder pb = new ProcessBuilder(cmd);
            pb.redirectErrorStream(true);
            Process p = pb.start();
            String output = new String(p.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
            int rc = p.waitFor();
            if (rc != 0) {
                throw new RuntimeException("sqlite3 failed: " + output.trim());
            }
            String trimmed = output.trim();
            if (trimmed.isEmpty()) return new ArrayList<>();
            Object parsed = JsonUtils.parseJson(trimmed);
            if (parsed instanceof List) return (List<Map<String, Object>>) parsed;
            return new ArrayList<>();
        } catch (IOException | InterruptedException e) {
            throw new RuntimeException(e);
        }
    }
}
