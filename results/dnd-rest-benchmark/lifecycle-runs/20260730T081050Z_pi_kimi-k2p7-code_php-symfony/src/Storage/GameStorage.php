<?php

declare(strict_types=1);

namespace App\Storage;

use App\Domain\SpellRules;
use PDO;
use PDOException;

/**
 * SQLite-backed persistence for the DM tools API.
 *
 * This class owns the schema, all write/read queries and the storage-level
 * reset routine. It is intentionally self-contained: constructing it with a
 * database path ensures the schema exists and foreign keys are enabled.
 */
final class GameStorage
{
    private PDO $pdo;
    private string $rootDir;

    public function __construct(string $dbPath, string $rootDir)
    {
        $this->rootDir = $rootDir;
        $this->pdo = new PDO("sqlite:$dbPath");
        $this->pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $this->pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
        $this->pdo->exec('PRAGMA foreign_keys = ON');
        $this->initialize();
    }

    /**
     * Create tables and seed the schema version row if missing.
     *
     * The schema is idempotent; it is safe to call on every request.
     */
    public function initialize(): void
    {
        $this->pdo->exec('
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            );
            INSERT OR IGNORE INTO schema_version (version) VALUES (1);

            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS combat_sessions (
                id TEXT PRIMARY KEY,
                round INTEGER NOT NULL DEFAULT 1,
                turn_index INTEGER NOT NULL DEFAULT 0,
                order_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS combat_conditions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                target TEXT NOT NULL,
                condition TEXT NOT NULL,
                remaining_rounds INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS compendium_monsters (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cr TEXT NOT NULL,
                armor_class INTEGER NOT NULL,
                hit_points INTEGER NOT NULL,
                tags_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS compendium_items (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                rarity TEXT NOT NULL,
                cost_gp INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                dm TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS campaign_characters (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                level INTEGER NOT NULL,
                class TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS campaign_events (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS quests (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS quest_milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quest_id TEXT NOT NULL,
                milestone TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                UNIQUE (quest_id, milestone),
                FOREIGN KEY (quest_id) REFERENCES quests(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS campaign_factions (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                stance TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS campaign_npcs (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                faction_id TEXT NOT NULL,
                name TEXT NOT NULL,
                disposition INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
                FOREIGN KEY (faction_id) REFERENCES campaign_factions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS campaign_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                item_slug TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                owner TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT \'entry\',
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS downtime_crafting (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                item_slug TEXT NOT NULL,
                days_required INTEGER NOT NULL,
                days_completed INTEGER NOT NULL DEFAULT 0,
                cost_gp INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT "active",
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS campaign_sessions (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                starts_at TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                agenda_json TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS session_attendance (
                session_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                present INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (session_id, character_id),
                FOREIGN KEY (session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaigns (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                owner TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT \'lobby\',
                max_players INTEGER NOT NULL,
                current_actor TEXT,
                turn_number INTEGER NOT NULL DEFAULT 0,
                nudge_count INTEGER NOT NULL DEFAULT 0,
                current_scene_id TEXT,
                current_location_id TEXT,
                pre_combat_actor TEXT,
                phase TEXT
            );

            CREATE TABLE IF NOT EXISTS play_campaign_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                name TEXT NOT NULL,
                class TEXT NOT NULL,
                race TEXT,
                background TEXT,
                abilities_json TEXT NOT NULL DEFAULT \'{}\',
                hp_max INTEGER NOT NULL DEFAULT 20,
                hp_current INTEGER NOT NULL DEFAULT 20,
                status TEXT NOT NULL DEFAULT \'conscious\',
                death_save_successes INTEGER NOT NULL DEFAULT 0,
                death_save_failures INTEGER NOT NULL DEFAULT 0,
                owner TEXT,
                level INTEGER NOT NULL DEFAULT 1,
                spell_slots_json TEXT NOT NULL DEFAULT \'{}\',
                gold INTEGER NOT NULL DEFAULT 10,
                UNIQUE (campaign_id, username),
                UNIQUE (campaign_id, character_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_narrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                actor TEXT NOT NULL,
                kind TEXT NOT NULL,
                type TEXT,
                text TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_documents (
                campaign_id TEXT PRIMARY KEY,
                story TEXT NOT NULL DEFAULT \'\',
                dm_notes TEXT NOT NULL DEFAULT \'\',
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_exports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                story TEXT NOT NULL,
                status TEXT NOT NULL,
                UNIQUE (campaign_id, version),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_scenes (
                campaign_id TEXT NOT NULL,
                scene_id TEXT NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT \'open\',
                PRIMARY KEY (campaign_id, scene_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_locations (
                campaign_id TEXT NOT NULL,
                location_id TEXT NOT NULL,
                name TEXT NOT NULL,
                PRIMARY KEY (campaign_id, location_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_location_connections (
                campaign_id TEXT NOT NULL,
                from_id TEXT NOT NULL,
                to_id TEXT NOT NULL,
                travel_turns INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, from_id, to_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_encounters (
                id TEXT NOT NULL,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT \'active\',
                combatants_json TEXT NOT NULL DEFAULT \'[]\',
                round INTEGER NOT NULL DEFAULT 1,
                turn_index INTEGER NOT NULL DEFAULT 0,
                order_json TEXT NOT NULL DEFAULT \'[]\',
                xp_awarded INTEGER NOT NULL DEFAULT 0,
                loot_json TEXT NOT NULL DEFAULT \'[]\',
                rewards_awarded INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (campaign_id, id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_encounter_monsters (
                campaign_id TEXT NOT NULL,
                encounter_id TEXT NOT NULL,
                monster_id TEXT NOT NULL,
                name TEXT NOT NULL,
                hp_max INTEGER NOT NULL,
                hp_current INTEGER NOT NULL,
                initiative INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, encounter_id, monster_id),
                FOREIGN KEY (campaign_id, encounter_id) REFERENCES play_campaign_encounters(campaign_id, id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_encounter_conditions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                encounter_id TEXT NOT NULL,
                target TEXT NOT NULL,
                condition TEXT NOT NULL,
                remaining_rounds INTEGER NOT NULL,
                FOREIGN KEY (campaign_id, encounter_id) REFERENCES play_campaign_encounters(campaign_id, id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_character_spells (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                spell_id TEXT NOT NULL,
                name TEXT NOT NULL,
                level INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id, spell_id),
                FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_character_prepared_spells (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                spell_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id, spell_id),
                FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_character_casts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                spell_id TEXT NOT NULL,
                target TEXT NOT NULL,
                slot_level INTEGER NOT NULL,
                slots_remaining INTEGER NOT NULL,
                sequence INTEGER NOT NULL,
                FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_character_concentration (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                spell_id TEXT NOT NULL,
                target TEXT NOT NULL,
                remaining_turns INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id),
                FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_character_inventory (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id, item_id),
                FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_character_equipment (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                slot TEXT NOT NULL,
                item_id TEXT NOT NULL,
                attuned INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (campaign_id, character_id, slot),
                FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                transfer_id INTEGER NOT NULL,
                from_character_id TEXT NOT NULL,
                to_character_id TEXT NOT NULL,
                gold INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
                UNIQUE (campaign_id, transfer_id)
            );

            CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                from_character_id TEXT NOT NULL,
                to_character_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                from_gold INTEGER NOT NULL,
                to_gold INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
                UNIQUE (campaign_id, sequence)
            );

            CREATE TABLE IF NOT EXISTS play_campaign_loot (
                campaign_id TEXT NOT NULL,
                loot_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT \'open\',
                recipient_character_id TEXT,
                PRIMARY KEY (campaign_id, loot_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (
                campaign_id TEXT NOT NULL,
                loot_id TEXT NOT NULL,
                voter TEXT NOT NULL,
                recipient_character_id TEXT NOT NULL,
                PRIMARY KEY (campaign_id, loot_id, voter),
                FOREIGN KEY (campaign_id, loot_id) REFERENCES play_campaign_loot(campaign_id, loot_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_npcs (
                campaign_id TEXT NOT NULL,
                npc_id TEXT NOT NULL,
                name TEXT NOT NULL,
                agenda TEXT NOT NULL,
                public_status TEXT NOT NULL,
                PRIMARY KEY (campaign_id, npc_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_factions (
                campaign_id TEXT NOT NULL,
                faction_id TEXT NOT NULL,
                name TEXT NOT NULL,
                PRIMARY KEY (campaign_id, faction_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_reputation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                faction_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                delta INTEGER NOT NULL,
                total_reputation INTEGER NOT NULL,
                reason TEXT NOT NULL,
                FOREIGN KEY (campaign_id, faction_id) REFERENCES play_campaign_factions(campaign_id, faction_id) ON DELETE CASCADE,
                FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                npc_id TEXT NOT NULL,
                dialogue_id TEXT NOT NULL,
                speaker TEXT NOT NULL,
                text TEXT NOT NULL,
                visibility TEXT NOT NULL,
                UNIQUE (campaign_id, npc_id, dialogue_id),
                FOREIGN KEY (campaign_id, npc_id) REFERENCES play_campaign_npcs(campaign_id, npc_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                score INTEGER NOT NULL,
                UNIQUE (campaign_id, source_id, target_id, kind),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_clues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                clue_id TEXT NOT NULL,
                text TEXT NOT NULL,
                audience TEXT NOT NULL,
                character_id TEXT,
                UNIQUE (campaign_id, clue_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
                FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_quests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                quest_id TEXT NOT NULL,
                title TEXT NOT NULL,
                depends_on_json TEXT NOT NULL DEFAULT \'[]\',
                state TEXT NOT NULL DEFAULT \'locked\',
                rewards_json TEXT NOT NULL DEFAULT \'{}\',
                awarded INTEGER NOT NULL DEFAULT 0,
                UNIQUE (campaign_id, quest_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_character_quest_rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                quest_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                xp INTEGER NOT NULL DEFAULT 0,
                items_json TEXT NOT NULL DEFAULT \'{}\',
                UNIQUE (campaign_id, quest_id, character_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
                FOREIGN KEY (campaign_id, quest_id) REFERENCES play_campaign_quests(campaign_id, quest_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_world_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                turn_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT \'scheduled\',
                resolution_turn_number INTEGER,
                resolution_text TEXT,
                UNIQUE (campaign_id, event_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_calendars (
                campaign_id TEXT PRIMARY KEY,
                day INTEGER NOT NULL,
                season TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_settlements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                name TEXT NOT NULL,
                services_json TEXT NOT NULL,
                availability TEXT NOT NULL,
                discovered_by_json TEXT NOT NULL DEFAULT \'[]\',
                UNIQUE (campaign_id, settlement_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_shops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                shop_id TEXT NOT NULL,
                name TEXT NOT NULL,
                stock_json TEXT NOT NULL,
                buy_price INTEGER NOT NULL,
                sell_price INTEGER NOT NULL,
                UNIQUE (campaign_id, settlement_id, shop_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
                FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_campaign_settlements(campaign_id, settlement_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                recipe_id TEXT NOT NULL,
                name TEXT NOT NULL,
                ingredients_json TEXT NOT NULL,
                output_item TEXT NOT NULL,
                output_quantity INTEGER NOT NULL,
                UNIQUE (campaign_id, recipe_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (
                campaign_id TEXT NOT NULL,
                activity_id TEXT NOT NULL,
                name TEXT NOT NULL,
                cycles_required INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, activity_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_downtime_allocations (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                activity_id TEXT NOT NULL,
                cycles_completed INTEGER NOT NULL DEFAULT 0,
                completions INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (campaign_id, character_id, activity_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
                FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE,
                FOREIGN KEY (campaign_id, activity_id) REFERENCES play_campaign_downtime_activities(campaign_id, activity_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_session_zero (
                campaign_id TEXT PRIMARY KEY,
                rules TEXT NOT NULL,
                tone TEXT NOT NULL,
                consent_json TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                content_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                UNIQUE (campaign_id, content_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                note_id TEXT NOT NULL,
                text TEXT NOT NULL,
                visibility TEXT NOT NULL,
                owner TEXT NOT NULL,
                UNIQUE (campaign_id, note_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_whispers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                whisper_id TEXT NOT NULL,
                from_character_id TEXT NOT NULL,
                to_character_id TEXT NOT NULL,
                text TEXT NOT NULL,
                UNIQUE (campaign_id, whisper_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                text TEXT NOT NULL,
                UNIQUE (campaign_id, message_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_invitations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                invitation_id TEXT NOT NULL,
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT \'pending\',
                UNIQUE (campaign_id, invitation_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_delegations (
                campaign_id TEXT NOT NULL,
                username TEXT NOT NULL,
                powers_json TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (campaign_id, username),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                powers_json TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                actor TEXT NOT NULL,
                role TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                correlation_id TEXT NOT NULL,
                UNIQUE (campaign_id, correlation_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_projection_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                value TEXT,
                UNIQUE (campaign_id, event_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                value TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                UNIQUE (campaign_id, event_id),
                UNIQUE (campaign_id, idempotency_key),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (
                campaign_id TEXT PRIMARY KEY,
                current_turn INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                submission_id TEXT NOT NULL,
                action TEXT NOT NULL,
                accepted_turn INTEGER NOT NULL,
                next_turn INTEGER NOT NULL,
                UNIQUE (campaign_id, submission_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_imports (
                campaign_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                story TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_migrations (
                campaign_id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                story TEXT NOT NULL,
                campaign_name TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_search_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                text TEXT NOT NULL,
                UNIQUE (campaign_id, record_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_rate_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                actor TEXT NOT NULL,
                UNIQUE (campaign_id, event_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_metrics (
                campaign_id TEXT PRIMARY KEY,
                accepted_rate_events INTEGER NOT NULL DEFAULT 0,
                rejected_rate_events INTEGER NOT NULL DEFAULT 0,
                projection_events INTEGER NOT NULL DEFAULT 0,
                uptime_ticks INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                backup_id TEXT NOT NULL,
                story TEXT NOT NULL,
                status TEXT NOT NULL,
                UNIQUE (campaign_id, backup_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_replay_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                UNIQUE (campaign_id, event_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_rng_seeds (
                campaign_id TEXT PRIMARY KEY,
                seed TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                roll_id TEXT NOT NULL,
                sides INTEGER NOT NULL,
                result INTEGER NOT NULL,
                sequence INTEGER NOT NULL,
                UNIQUE (campaign_id, roll_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                report_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT \'open\',
                reporter TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                action TEXT,
                note TEXT,
                resolver TEXT,
                UNIQUE (campaign_id, report_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries (
                campaign_id TEXT PRIMARY KEY,
                blocked_tags_json TEXT NOT NULL DEFAULT \'[]\',
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_safety_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                UNIQUE (campaign_id, event_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_fixtures (
                campaign_id TEXT PRIMARY KEY,
                fixture_id TEXT NOT NULL,
                status TEXT NOT NULL,
                characters_json TEXT NOT NULL,
                story TEXT NOT NULL,
                event_ids_json TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_spectators (
                spectator_id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS play_campaign_feed_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                text TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                UNIQUE (campaign_id, event_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );
        ');

        // Migrate older play_campaign_narrations tables created before player
        // action events needed a type column.
        $this->addColumnIfMissing('play_campaign_narrations', 'type', 'TEXT');

        // Migrate older play_campaign_narrations tables created before encounter
        // combat actions needed a target column.
        $this->addColumnIfMissing('play_campaign_narrations', 'target', 'TEXT');

        // Migrate older campaign_inventory tables that were created without the
        // source column used to distinguish inventory entries from equipment
        // assignments and crafting rewards.
        $this->addColumnIfMissing('campaign_inventory', 'source', "TEXT NOT NULL DEFAULT 'entry'");

        // Migrate older play_campaigns tables created before the campaign start
        // stage introduced turn tracking.
        $this->addColumnIfMissing('play_campaigns', 'current_actor', 'TEXT');
        $this->addColumnIfMissing('play_campaigns', 'turn_number', 'INTEGER NOT NULL DEFAULT 0');
        $this->addColumnIfMissing('play_campaigns', 'nudge_count', 'INTEGER NOT NULL DEFAULT 0');
        $this->addColumnIfMissing('play_campaigns', 'current_scene_id', 'TEXT');
        $this->addColumnIfMissing('play_campaigns', 'current_location_id', 'TEXT');

        // Migrate older play_campaigns tables created before the combat/exploration
        // transition stage needed to remember the exploration-turn actor.
        $this->addColumnIfMissing('play_campaigns', 'pre_combat_actor', 'TEXT');

        // Migrate older play_campaigns tables created before the capstone stage
        // tracked the exploration/combat phase explicitly.
        $this->addColumnIfMissing('play_campaigns', 'phase', 'TEXT');

        // Migrate older play_campaign_members tables created before rest turns
        // tracked per-character hit points.
        $this->addColumnIfMissing('play_campaign_members', 'hp_max', 'INTEGER NOT NULL DEFAULT 20');
        $this->addColumnIfMissing('play_campaign_members', 'hp_current', 'INTEGER NOT NULL DEFAULT 20');

        // Migrate older play_campaign_members tables created before death-save
        // tracking was introduced.
        $this->addColumnIfMissing('play_campaign_members', 'status', "TEXT NOT NULL DEFAULT 'conscious'");
        $this->addColumnIfMissing('play_campaign_members', 'death_save_successes', 'INTEGER NOT NULL DEFAULT 0');
        $this->addColumnIfMissing('play_campaign_members', 'death_save_failures', 'INTEGER NOT NULL DEFAULT 0');

        // Migrate older play_campaign_members tables created before character
        // ownership was tracked per character.
        $this->addColumnIfMissing('play_campaign_members', 'owner', 'TEXT');

        // Migrate older play_campaign_members tables created before character
        // creation choices (race, class, background, abilities) were tracked.
        $this->addColumnIfMissing('play_campaign_members', 'race', 'TEXT');
        $this->addColumnIfMissing('play_campaign_members', 'background', 'TEXT');
        $this->addColumnIfMissing('play_campaign_members', 'abilities_json', "TEXT NOT NULL DEFAULT '{}'");

        // Migrate older play_campaign_members tables created before character
        // level progression was tracked.
        $this->addColumnIfMissing('play_campaign_members', 'level', "INTEGER NOT NULL DEFAULT 1");

        // Migrate older play_campaign_members tables created before spell-slot
        // tracking was needed for casting.
        $this->addColumnIfMissing('play_campaign_members', 'spell_slots_json', "TEXT NOT NULL DEFAULT '{}'");

        // Migrate older play_campaign_members tables created before per-character
        // gold balances were tracked.
        $this->addColumnIfMissing('play_campaign_members', 'gold', 'INTEGER NOT NULL DEFAULT 10');
        $this->pdo->exec("UPDATE play_campaign_members SET gold = COALESCE(gold, 10) WHERE gold IS NULL");

        // Migrate older play_campaign_encounters tables created before combat
        // turn authority tracked per-encounter round and turn index.
        $this->addColumnIfMissing('play_campaign_encounters', 'round', 'INTEGER NOT NULL DEFAULT 1');
        $this->addColumnIfMissing('play_campaign_encounters', 'turn_index', 'INTEGER NOT NULL DEFAULT 0');

        // Migrate older play_campaign_encounters tables created before the delay
        // and ready stage introduced explicit turn-order storage.
        $this->addColumnIfMissing('play_campaign_encounters', 'order_json', "TEXT NOT NULL DEFAULT '[]'");

        // Migrate older play_campaign_encounters tables created before the rewards
        // stage tracked awarded XP and loot.
        $this->addColumnIfMissing('play_campaign_encounters', 'xp_awarded', "INTEGER NOT NULL DEFAULT 0");
        $this->addColumnIfMissing('play_campaign_encounters', 'loot_json', "TEXT NOT NULL DEFAULT '[]'");
        $this->addColumnIfMissing('play_campaign_encounters', 'rewards_awarded', "INTEGER NOT NULL DEFAULT 0");

        // Migrate older play_campaign_quests tables created before the quest rewards
        // stage tracked configured rewards and award state.
        $this->addColumnIfMissing('play_campaign_quests', 'rewards_json', "TEXT NOT NULL DEFAULT '{}'");
        $this->addColumnIfMissing('play_campaign_quests', 'awarded', 'INTEGER NOT NULL DEFAULT 0');

        // Ensure all play-campaign members have a default level now that the
        // column exists.
        $this->pdo->exec("UPDATE play_campaign_members SET level = COALESCE(level, 1) WHERE level IS NULL");

    }

    private function addColumnIfMissing(string $table, string $column, string $definition): void
    {
        $stmt = $this->pdo->query("PRAGMA table_info($table)");
        foreach ($stmt->fetchAll() as $row) {
            if ($row['name'] === $column) {
                return;
            }
        }
        $this->pdo->exec("ALTER TABLE $table ADD COLUMN $column $definition");
    }

    /**
     * Truncate all data tables and re-seed the schema version marker.
     *
     * Also removes legacy JSON files that were used by earlier implementations.
     * This method is the single source of truth for the truncate list; both
     * `reset.php` (pre-startup cleanup) and the runtime reset endpoint use it.
     */
    public function reset(): void
    {
        $this->pdo->exec('DELETE FROM combat_conditions');
        $this->pdo->exec('DELETE FROM combat_sessions');
        $this->pdo->exec('DELETE FROM users');
        $this->pdo->exec('DELETE FROM compendium_items');
        $this->pdo->exec('DELETE FROM compendium_monsters');
        $this->pdo->exec('DELETE FROM quest_milestones');
        $this->pdo->exec('DELETE FROM quests');
        $this->pdo->exec('DELETE FROM campaign_events');
        $this->pdo->exec('DELETE FROM campaign_inventory');
        $this->pdo->exec('DELETE FROM downtime_crafting');
        $this->pdo->exec('DELETE FROM campaign_characters');
        $this->pdo->exec('DELETE FROM campaign_npcs');
        $this->pdo->exec('DELETE FROM campaign_factions');
        $this->pdo->exec('DELETE FROM session_attendance');
        $this->pdo->exec('DELETE FROM campaign_sessions');
        $this->pdo->exec('DELETE FROM campaigns');
        $this->pdo->exec('DELETE FROM play_campaign_documents');
        $this->pdo->exec('DELETE FROM play_campaign_exports');
        $this->pdo->exec('DELETE FROM play_campaign_location_connections');
        $this->pdo->exec('DELETE FROM play_campaign_locations');
        $this->pdo->exec('DELETE FROM play_campaign_character_concentration');
        $this->pdo->exec('DELETE FROM play_campaign_character_inventory');
        $this->pdo->exec('DELETE FROM play_campaign_character_equipment');
        $this->pdo->exec('DELETE FROM play_campaign_character_casts');
        $this->pdo->exec('DELETE FROM play_campaign_character_prepared_spells');
        $this->pdo->exec('DELETE FROM play_campaign_character_spells');
        $this->pdo->exec('DELETE FROM play_campaign_encounter_conditions');
        $this->pdo->exec('DELETE FROM play_campaign_encounter_monsters');
        $this->pdo->exec('DELETE FROM play_campaign_encounters');
        $this->pdo->exec('DELETE FROM play_campaign_scenes');
        $this->pdo->exec('DELETE FROM play_campaign_narrations');
        $this->pdo->exec('DELETE FROM play_campaign_transfers');
        $this->pdo->exec('DELETE FROM play_campaign_transactional_transfers');
        $this->pdo->exec('DELETE FROM play_campaign_loot_votes');
        $this->pdo->exec('DELETE FROM play_campaign_loot');
        $this->pdo->exec('DELETE FROM play_campaign_npcs');
        $this->pdo->exec('DELETE FROM play_campaign_relationships');
        $this->pdo->exec('DELETE FROM play_campaign_clues');
        $this->pdo->exec('DELETE FROM play_campaign_character_quest_rewards');
        $this->pdo->exec('DELETE FROM play_campaign_quests');
        $this->pdo->exec('DELETE FROM play_campaign_npc_dialogue');
        $this->pdo->exec('DELETE FROM play_campaign_reputation_history');
        $this->pdo->exec('DELETE FROM play_campaign_factions');
        $this->pdo->exec('DELETE FROM play_campaign_members');
        $this->pdo->exec('DELETE FROM play_campaign_calendars');
        $this->pdo->exec('DELETE FROM play_campaign_shops');
        $this->pdo->exec('DELETE FROM play_campaign_recipes');
        $this->pdo->exec('DELETE FROM play_campaign_downtime_allocations');
        $this->pdo->exec('DELETE FROM play_campaign_downtime_activities');
        $this->pdo->exec('DELETE FROM play_campaign_settlements');
        $this->pdo->exec('DELETE FROM play_campaign_world_events');
        $this->pdo->exec('DELETE FROM play_campaign_session_zero');
        $this->pdo->exec('DELETE FROM play_campaign_content');
        $this->pdo->exec('DELETE FROM play_campaign_notes');
        $this->pdo->exec('DELETE FROM play_campaign_whispers');
        $this->pdo->exec('DELETE FROM play_campaign_messages');
        $this->pdo->exec('DELETE FROM play_campaign_invitations');
        $this->pdo->exec('DELETE FROM play_campaign_audit_events');
        $this->pdo->exec('DELETE FROM play_campaign_projection_events');
        $this->pdo->exec('DELETE FROM play_campaign_idempotent_events');
        $this->pdo->exec('DELETE FROM play_campaign_safe_turn_submissions');
        $this->pdo->exec('DELETE FROM play_campaign_safe_turns');
        $this->pdo->exec('DELETE FROM play_campaign_delegation_audit');
        $this->pdo->exec('DELETE FROM play_campaign_delegations');
        $this->pdo->exec('DELETE FROM play_campaign_imports');
        $this->pdo->exec('DELETE FROM play_campaign_migrations');
        $this->pdo->exec('DELETE FROM play_campaign_search_records');
        $this->pdo->exec('DELETE FROM play_campaign_rate_events');
        $this->pdo->exec('DELETE FROM play_campaign_backups');
        $this->pdo->exec('DELETE FROM play_campaign_replay_events');
        $this->pdo->exec('DELETE FROM play_campaign_rng_rolls');
        $this->pdo->exec('DELETE FROM play_campaign_rng_seeds');
        $this->pdo->exec('DELETE FROM play_campaign_moderation_reports');
        $this->pdo->exec('DELETE FROM play_campaign_safety_events');
        $this->pdo->exec('DELETE FROM play_campaign_safety_boundaries');
        $this->pdo->exec('DELETE FROM play_campaign_fixtures');
        $this->pdo->exec('DELETE FROM play_campaign_spectators');
        $this->pdo->exec('DELETE FROM play_campaign_feed_events');
        $this->pdo->exec('DELETE FROM play_campaign_metrics');
        $this->pdo->exec('DELETE FROM play_campaigns');
        $this->pdo->exec("INSERT OR IGNORE INTO schema_version (version) VALUES (1)");
        $this->removeLegacyFiles();
    }

    private function removeLegacyFiles(): void
    {
        @unlink($this->rootDir . '/.combat-state.json');
        @unlink($this->rootDir . '/.users.json');
    }

    public function status(): array
    {
        $stmt = $this->pdo->query("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'");
        $initialized = $stmt->fetch() !== false;
        $version = 1;
        if ($initialized) {
            $stmt = $this->pdo->query('SELECT version FROM schema_version LIMIT 1');
            $row = $stmt->fetch();
            if ($row) {
                $version = (int) $row['version'];
            }
        }

        return [
            'driver' => 'sqlite',
            'schema_version' => $version,
            'initialized' => $initialized,
        ];
    }

    public function createUser(string $username, string $passwordHash, string $role): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)');
            $stmt->execute([$username, $passwordHash, $role]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getUser(string $username): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM users WHERE username = ?');
        $stmt->execute([$username]);
        $row = $stmt->fetch();

        return $row ?: null;
    }

    public function createSession(string $id, array $order): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO combat_sessions (id, round, turn_index, order_json) VALUES (?, 1, 0, ?)');
            $stmt->execute([$id, json_encode($order, JSON_THROW_ON_ERROR)]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getSession(string $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM combat_sessions WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['round'] = (int) $row['round'];
        $row['turn_index'] = (int) $row['turn_index'];
        $row['order'] = json_decode($row['order_json'], true, 512, JSON_THROW_ON_ERROR);
        unset($row['order_json']);

        return $row;
    }

    public function getConditionsForTarget(string $sessionId, string $target): array
    {
        $stmt = $this->pdo->prepare('SELECT condition, remaining_rounds FROM combat_conditions WHERE session_id = ? AND target = ?');
        $stmt->execute([$sessionId, $target]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'condition' => $row['condition'],
                'remaining_rounds' => (int) $row['remaining_rounds'],
            ];
        }

        return $result;
    }

    public function getConditionsMap(string $sessionId): array
    {
        $stmt = $this->pdo->prepare('SELECT target, condition, remaining_rounds FROM combat_conditions WHERE session_id = ?');
        $stmt->execute([$sessionId]);
        $map = [];
        foreach ($stmt->fetchAll() as $row) {
            $map[$row['target']][] = [
                'condition' => $row['condition'],
                'remaining_rounds' => (int) $row['remaining_rounds'],
            ];
        }

        return $map;
    }

    public function addCondition(string $sessionId, string $target, string $condition, int $duration): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO combat_conditions (session_id, target, condition, remaining_rounds) VALUES (?, ?, ?, ?)');
        $stmt->execute([$sessionId, $target, $condition, $duration]);
    }

    public function advanceTurn(string $id): ?array
    {
        $session = $this->getSession($id);
        if (!$session) {
            return null;
        }

        $count = count($session['order']);
        if ($count === 0) {
            return null;
        }

        $newIndex = $session['turn_index'] + 1;
        $newRound = $session['round'];
        if ($newIndex >= $count) {
            $newIndex = 0;
            $newRound++;
        }
        $activeName = $session['order'][$newIndex]['name'];

        $stmt = $this->pdo->prepare('SELECT id, remaining_rounds FROM combat_conditions WHERE session_id = ? AND target = ?');
        $stmt->execute([$id, $activeName]);
        foreach ($stmt->fetchAll() as $row) {
            $newRemaining = (int) $row['remaining_rounds'] - 1;
            if ($newRemaining > 0) {
                $upd = $this->pdo->prepare('UPDATE combat_conditions SET remaining_rounds = ? WHERE id = ?');
                $upd->execute([$newRemaining, $row['id']]);
            } else {
                $del = $this->pdo->prepare('DELETE FROM combat_conditions WHERE id = ?');
                $del->execute([$row['id']]);
            }
        }

        $upd = $this->pdo->prepare('UPDATE combat_sessions SET round = ?, turn_index = ? WHERE id = ?');
        $upd->execute([$newRound, $newIndex, $id]);

        $session['round'] = $newRound;
        $session['turn_index'] = $newIndex;
        $session['conditions'] = $this->getConditionsMap($id);
        foreach ($session['order'] as $combatant) {
            $name = $combatant['name'];
            if (!isset($session['conditions'][$name])) {
                $session['conditions'][$name] = [];
            }
        }

        return $session;
    }

    public function createMonster(array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)');
            $stmt->execute([
                $data['slug'],
                $data['name'],
                $data['cr'],
                $data['armor_class'],
                $data['hit_points'],
                json_encode($data['tags'] ?? [], JSON_THROW_ON_ERROR),
            ]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getMonster(string $slug): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM compendium_monsters WHERE slug = ?');
        $stmt->execute([$slug]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'slug' => $row['slug'],
            'name' => $row['name'],
            'cr' => $row['cr'],
            'armor_class' => (int) $row['armor_class'],
            'hit_points' => (int) $row['hit_points'],
            'tags' => json_decode($row['tags_json'], true, 512, JSON_THROW_ON_ERROR),
        ];
    }

    public function createItem(array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([
                $data['slug'],
                $data['name'],
                $data['type'],
                $data['rarity'],
                $data['cost_gp'],
            ]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getItem(string $slug): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM compendium_items WHERE slug = ?');
        $stmt->execute([$slug]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'slug' => $row['slug'],
            'name' => $row['name'],
            'type' => $row['type'],
            'rarity' => $row['rarity'],
            'cost_gp' => (int) $row['cost_gp'],
        ];
    }

    public function createCampaign(array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)');
            $stmt->execute([$data['id'], $data['name'], $data['dm']]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function createPlayCampaign(array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([$data['id'], $data['name'], $data['owner'], $data['status'], $data['max_players']]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaign(string $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT id, name, owner, status, max_players, current_actor, turn_number, current_scene_id, current_location_id, phase FROM play_campaigns WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'id' => $row['id'],
            'name' => $row['name'],
            'owner' => $row['owner'],
            'status' => $row['status'],
            'max_players' => (int) $row['max_players'],
            'current_actor' => $row['current_actor'],
            'turn_number' => (int) $row['turn_number'],
            'current_scene_id' => $row['current_scene_id'],
            'current_location_id' => $row['current_location_id'],
            'phase' => $row['phase'],
        ];
    }

    public function incrementPlayCampaignNudgeCount(string $campaignId): ?int
    {
        $upd = $this->pdo->prepare('UPDATE play_campaigns SET nudge_count = COALESCE(nudge_count, 0) + 1 WHERE id = ?');
        $upd->execute([$campaignId]);
        if ($upd->rowCount() === 0) {
            return null;
        }

        $stmt = $this->pdo->prepare('SELECT nudge_count FROM play_campaigns WHERE id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return (int) $row['nudge_count'];
    }

    public function getPlayCampaignMembers(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT username, character_id, name, class FROM play_campaign_members WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'username' => $row['username'],
                'character_id' => $row['character_id'],
                'name' => $row['name'],
                'class' => $row['class'],
            ];
        }

        return $result;
    }

    public function startPlayCampaign(string $campaignId, string $currentActor): bool
    {
        $stmt = $this->pdo->prepare("UPDATE play_campaigns SET status = 'active', current_actor = ?, turn_number = 1, phase = 'player' WHERE id = ? AND status = 'lobby'");
        $stmt->execute([$currentActor, $campaignId]);

        return $stmt->rowCount() > 0;
    }

    public function addPlayCampaignMember(string $campaignId, string $username, string $characterId, string $name, string $class): bool
    {
        try {
            $slots = SpellRules::spellSlots($class, 1);
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, level, hp_max, hp_current, owner, spell_slots_json, gold) VALUES (?, ?, ?, ?, ?, 1, 20, 20, ?, ?, 10)');
            $stmt->execute([$campaignId, $username, $characterId, $name, $class, $username, json_encode($slots, JSON_THROW_ON_ERROR)]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignMemberCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM play_campaign_members WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        return (int) ($stmt->fetch()['count'] ?? 0);
    }

    public function isPlayCampaignMember(string $campaignId, string $username): bool
    {
        $stmt = $this->pdo->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ? LIMIT 1');
        $stmt->execute([$campaignId, $username]);

        return $stmt->fetch() !== false;
    }

    public function getPlayCampaignMember(string $campaignId, string $username): ?array
    {
        $stmt = $this->pdo->prepare('SELECT username, character_id, name, class FROM play_campaign_members WHERE campaign_id = ? AND username = ? LIMIT 1');
        $stmt->execute([$campaignId, $username]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'username' => $row['username'],
            'character_id' => $row['character_id'],
            'name' => $row['name'],
            'class' => $row['class'],
        ];
    }

    public function getPlayCampaignMemberByCharacterId(string $campaignId, string $characterId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT username, character_id, name, class, level, hp_max, hp_current, status, death_save_successes, death_save_failures, owner, gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $characterId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'username' => $row['username'],
            'character_id' => $row['character_id'],
            'name' => $row['name'],
            'class' => $row['class'],
            'level' => (int) ($row['level'] ?? 1),
            'hp_max' => (int) $row['hp_max'],
            'hp_current' => (int) $row['hp_current'],
            'status' => $row['status'],
            'death_save_successes' => (int) $row['death_save_successes'],
            'death_save_failures' => (int) $row['death_save_failures'],
            'owner' => $row['owner'],
            'gold' => (int) ($row['gold'] ?? 10),
        ];
    }

    public function getCharacterCurrency(string $campaignId, string $characterId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT character_id, gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $characterId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'character_id' => $row['character_id'],
            'gold' => (int) ($row['gold'] ?? 10),
        ];
    }

    public function transferGold(string $campaignId, string $fromCharacterId, string $toCharacterId, int $gold): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $fromStmt = $this->pdo->prepare('SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
            $fromStmt->execute([$campaignId, $fromCharacterId]);
            $fromRow = $fromStmt->fetch();
            if (!$fromRow) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }
            $fromGold = (int) ($fromRow['gold'] ?? 10);
            if ($fromGold < $gold) {
                $this->pdo->exec('ROLLBACK');

                return ['error' => 'insufficient gold'];
            }

            $toStmt = $this->pdo->prepare('SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
            $toStmt->execute([$campaignId, $toCharacterId]);
            $toRow = $toStmt->fetch();
            if (!$toRow) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }
            $toGold = (int) ($toRow['gold'] ?? 10);

            $newFromGold = $fromGold - $gold;
            $newToGold = $toGold + $gold;

            $upd = $this->pdo->prepare('UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?');
            $upd->execute([$newFromGold, $campaignId, $fromCharacterId]);
            $upd->execute([$newToGold, $campaignId, $toCharacterId]);

            $idStmt = $this->pdo->prepare('SELECT COALESCE(MAX(transfer_id), 0) + 1 FROM play_campaign_transfers WHERE campaign_id = ?');
            $idStmt->execute([$campaignId]);
            $transferId = (int) $idStmt->fetchColumn();

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold) VALUES (?, ?, ?, ?, ?)');
            $ins->execute([$campaignId, $transferId, $fromCharacterId, $toCharacterId, $gold]);

            $this->pdo->exec('COMMIT');

            return [
                'transfer_id' => $transferId,
                'from_gold' => $newFromGold,
                'to_gold' => $newToGold,
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function createTransactionalTransfer(string $campaignId, string $fromCharacterId, string $toCharacterId, int $amount, bool $simulateFailure): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $fromStmt = $this->pdo->prepare('SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
            $fromStmt->execute([$campaignId, $fromCharacterId]);
            $fromRow = $fromStmt->fetch();
            if (!$fromRow) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }
            $fromGold = (int) ($fromRow['gold'] ?? 10);

            if ($fromGold < $amount) {
                $this->pdo->exec('ROLLBACK');

                return ['error' => 'insufficient gold'];
            }

            $toStmt = $this->pdo->prepare('SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
            $toStmt->execute([$campaignId, $toCharacterId]);
            $toRow = $toStmt->fetch();
            if (!$toRow) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }
            $toGold = (int) ($toRow['gold'] ?? 10);

            if ($simulateFailure) {
                $this->pdo->exec('ROLLBACK');

                return ['error' => 'simulated failure'];
            }

            $newFromGold = $fromGold - $amount;
            $newToGold = $toGold + $amount;

            $upd = $this->pdo->prepare('UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?');
            $upd->execute([$newFromGold, $campaignId, $fromCharacterId]);
            $upd->execute([$newToGold, $campaignId, $toCharacterId]);

            $seqStmt = $this->pdo->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_transactional_transfers WHERE campaign_id = ?');
            $seqStmt->execute([$campaignId]);
            $sequence = (int) $seqStmt->fetchColumn();

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_transactional_transfers (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) VALUES (?, ?, ?, ?, ?, ?, ?)');
            $ins->execute([$campaignId, $sequence, $fromCharacterId, $toCharacterId, $amount, $newFromGold, $newToGold]);

            $this->pdo->exec('COMMIT');

            return [
                'from_character_id' => $fromCharacterId,
                'to_character_id' => $toCharacterId,
                'amount' => $amount,
                'from_gold' => $newFromGold,
                'to_gold' => $newToGold,
                'sequence' => $sequence,
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getTransactionalTransfers(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT sequence, from_character_id, to_character_id, amount, from_gold, to_gold FROM play_campaign_transactional_transfers WHERE campaign_id = ? ORDER BY sequence ASC');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'from_character_id' => $row['from_character_id'],
                'to_character_id' => $row['to_character_id'],
                'amount' => (int) $row['amount'],
                'from_gold' => (int) $row['from_gold'],
                'to_gold' => (int) $row['to_gold'],
                'sequence' => (int) $row['sequence'],
            ];
        }

        return $result;
    }

    public function getPlayCampaignCharacterLevelData(string $campaignId, string $characterId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT class, level, abilities_json, hp_max, hp_current, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $characterId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'class' => $row['class'],
            'level' => (int) ($row['level'] ?? 1),
            'abilities_json' => $row['abilities_json'],
            'hp_max' => (int) $row['hp_max'],
            'hp_current' => (int) $row['hp_current'],
            'owner' => $row['owner'],
        ];
    }

    public function getPlayCampaignCharacterSkillData(string $campaignId, string $characterId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT owner, level, abilities_json FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $characterId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'owner' => $row['owner'],
            'level' => (int) ($row['level'] ?? 1),
            'abilities' => json_decode($row['abilities_json'] ?? '{}', true, 512, JSON_THROW_ON_ERROR),
        ];
    }

    public function addCharacterSpell(string $campaignId, string $characterId, string $spellId, string $name, int $level): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_character_spells (campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $characterId, $spellId, $name, $level]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getCharacterSpells(string $campaignId, string $characterId): array
    {
        $stmt = $this->pdo->prepare('SELECT spell_id, name, level FROM play_campaign_character_spells WHERE campaign_id = ? AND character_id = ? ORDER BY level, spell_id');
        $stmt->execute([$campaignId, $characterId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'spell_id' => $row['spell_id'],
                'name' => $row['name'],
                'level' => (int) $row['level'],
            ];
        }

        return $result;
    }

    public function getCharacterPreparedSpells(string $campaignId, string $characterId): array
    {
        $stmt = $this->pdo->prepare('SELECT spell_id FROM play_campaign_character_prepared_spells WHERE campaign_id = ? AND character_id = ? ORDER BY ordinal, spell_id');
        $stmt->execute([$campaignId, $characterId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = $row['spell_id'];
        }

        return $result;
    }

    public function setCharacterPreparedSpells(string $campaignId, string $characterId, array $spellIds): void
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $del = $this->pdo->prepare('DELETE FROM play_campaign_character_prepared_spells WHERE campaign_id = ? AND character_id = ?');
            $del->execute([$campaignId, $characterId]);

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_character_prepared_spells (campaign_id, character_id, spell_id, ordinal) VALUES (?, ?, ?, ?)');
            foreach ($spellIds as $index => $spellId) {
                $ins->execute([$campaignId, $characterId, $spellId, $index]);
            }
            $this->pdo->exec('COMMIT');
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getCharacterSpellSlots(string $campaignId, string $characterId): array
    {
        $stmt = $this->pdo->prepare('SELECT spell_slots_json FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $characterId]);
        $row = $stmt->fetch();
        if (!$row) {
            return [];
        }

        $slots = json_decode($row['spell_slots_json'] ?? '{}', true, 512, JSON_THROW_ON_ERROR);

        return is_array($slots) ? $slots : [];
    }

    public function setCharacterSpellSlots(string $campaignId, string $characterId, array $slots): void
    {
        $stmt = $this->pdo->prepare('UPDATE play_campaign_members SET spell_slots_json = ? WHERE campaign_id = ? AND character_id = ?');
        $stmt->execute([json_encode($slots, JSON_THROW_ON_ERROR), $campaignId, $characterId]);
    }

    public function consumeCharacterSpellSlot(string $campaignId, string $characterId, int $slotLevel): ?int
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $slots = $this->getCharacterSpellSlots($campaignId, $characterId);
            $key = (string) $slotLevel;
            $remaining = (int) ($slots[$key] ?? 0);
            if ($remaining <= 0) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $slots[$key] = $remaining - 1;
            $this->setCharacterSpellSlots($campaignId, $characterId, $slots);
            $this->pdo->exec('COMMIT');

            return $remaining - 1;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function recordCharacterSpellCast(string $campaignId, string $characterId, string $spellId, string $target, int $slotLevel, int $slotsRemaining): array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_character_casts (campaign_id, character_id, spell_id, target, slot_level, slots_remaining, sequence) VALUES (?, ?, ?, ?, ?, ?, COALESCE((SELECT MAX(sequence) FROM play_campaign_character_casts WHERE campaign_id = ? AND character_id = ?), 0) + 1)');
            $stmt->execute([$campaignId, $characterId, $spellId, $target, $slotLevel, $slotsRemaining, $campaignId, $characterId]);
            $id = (int) $this->pdo->lastInsertId();

            $select = $this->pdo->prepare('SELECT spell_id, target, slot_level, slots_remaining, sequence FROM play_campaign_character_casts WHERE id = ?');
            $select->execute([$id]);
            $row = $select->fetch();
            $this->pdo->exec('COMMIT');

            return [
                'character_id' => $characterId,
                'spell_id' => $row['spell_id'],
                'target' => $row['target'],
                'slot_level' => (int) $row['slot_level'],
                'slots_remaining' => (int) $row['slots_remaining'],
                'sequence' => (int) $row['sequence'],
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getCharacterSpellCasts(string $campaignId, string $characterId): array
    {
        $stmt = $this->pdo->prepare('SELECT spell_id, target, slot_level, slots_remaining, sequence FROM play_campaign_character_casts WHERE campaign_id = ? AND character_id = ? ORDER BY sequence ASC');
        $stmt->execute([$campaignId, $characterId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'character_id' => $characterId,
                'spell_id' => $row['spell_id'],
                'target' => $row['target'],
                'slot_level' => (int) $row['slot_level'],
                'slots_remaining' => (int) $row['slots_remaining'],
                'sequence' => (int) $row['sequence'],
            ];
        }

        return $result;
    }

    public function getCharacterConcentration(string $campaignId, string $characterId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT spell_id, target, remaining_turns FROM play_campaign_character_concentration WHERE campaign_id = ? AND character_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $characterId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'spell_id' => $row['spell_id'],
            'target' => $row['target'],
            'remaining_turns' => (int) $row['remaining_turns'],
        ];
    }

    public function setCharacterConcentration(string $campaignId, string $characterId, string $spellId, string $target, int $remainingTurns): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO play_campaign_character_concentration (campaign_id, character_id, spell_id, target, remaining_turns) VALUES (?, ?, ?, ?, ?) ON CONFLICT(campaign_id, character_id) DO UPDATE SET spell_id = excluded.spell_id, target = excluded.target, remaining_turns = excluded.remaining_turns');
        $stmt->execute([$campaignId, $characterId, $spellId, $target, $remainingTurns]);
    }

    public function clearCharacterConcentration(string $campaignId, string $characterId): void
    {
        $stmt = $this->pdo->prepare('DELETE FROM play_campaign_character_concentration WHERE campaign_id = ? AND character_id = ?');
        $stmt->execute([$campaignId, $characterId]);
    }

    public function advanceCharacterConcentration(string $campaignId, string $characterId): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $concentration = $this->getCharacterConcentration($campaignId, $characterId);
            if ($concentration === null) {
                $this->pdo->exec('COMMIT');

                return null;
            }

            $remaining = $concentration['remaining_turns'] - 1;
            if ($remaining <= 0) {
                $this->clearCharacterConcentration($campaignId, $characterId);
                $this->pdo->exec('COMMIT');

                return null;
            }

            $this->setCharacterConcentration($campaignId, $characterId, $concentration['spell_id'], $concentration['target'], $remaining);
            $this->pdo->exec('COMMIT');

            return [
                'spell_id' => $concentration['spell_id'],
                'target' => $concentration['target'],
                'remaining_turns' => $remaining,
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function levelUpPlayCampaignCharacter(string $campaignId, string $characterId, int $newLevel, int $newHpMax, int $newHpCurrent): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT class, level FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
            $stmt->execute([$campaignId, $characterId]);
            $row = $stmt->fetch();
            if (!$row) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $upd = $this->pdo->prepare('UPDATE play_campaign_members SET level = ?, hp_max = ?, hp_current = ? WHERE campaign_id = ? AND character_id = ?');
            $upd->execute([$newLevel, $newHpMax, $newHpCurrent, $campaignId, $characterId]);
            $this->pdo->exec('COMMIT');

            return [
                'character_id' => $characterId,
                'class' => $row['class'],
                'level' => $newLevel,
                'hp_max' => $newHpMax,
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignCharacterOwner(string $campaignId, string $characterId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $characterId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'character_id' => $row['character_id'],
            'owner' => $row['owner'],
        ];
    }

    public function claimPlayCampaignCharacter(string $campaignId, string $characterId, string $username): bool
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
            $stmt->execute([$campaignId, $characterId]);
            $row = $stmt->fetch();
            if (!$row) {
                $this->pdo->exec('ROLLBACK');

                return false;
            }
            if ($row['owner'] !== null && $row['owner'] !== $username) {
                $this->pdo->exec('ROLLBACK');

                return false;
            }

            $upd = $this->pdo->prepare('UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?');
            $upd->execute([$username, $campaignId, $characterId]);
            $this->pdo->exec('COMMIT');

            return true;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function transferPlayCampaignCharacter(string $campaignId, string $characterId, string $newOwner): bool
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ? LIMIT 1');
            $stmt->execute([$campaignId, $newOwner]);
            if (!$stmt->fetch()) {
                $this->pdo->exec('ROLLBACK');

                return false;
            }

            $upd = $this->pdo->prepare('UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?');
            $upd->execute([$newOwner, $campaignId, $characterId]);
            if ($upd->rowCount() === 0) {
                $this->pdo->exec('ROLLBACK');

                return false;
            }

            $this->pdo->exec('COMMIT');

            return true;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function buildPlayCampaignCharacter(string $campaignId, string $characterId, string $race, string $class, string $background, array $abilities, int $hpMax, int $level = 1): bool
    {
        $slots = \App\Domain\SpellRules::spellSlots($class, $level);
        $stmt = $this->pdo->prepare('UPDATE play_campaign_members SET race = ?, class = ?, background = ?, abilities_json = ?, level = ?, hp_max = ?, hp_current = ?, spell_slots_json = ? WHERE campaign_id = ? AND character_id = ?');
        $stmt->execute([
            $race,
            $class,
            $background,
            json_encode($abilities, JSON_THROW_ON_ERROR),
            $level,
            $hpMax,
            $hpMax,
            json_encode($slots, JSON_THROW_ON_ERROR),
            $campaignId,
            $characterId,
        ]);

        return $stmt->rowCount() > 0;
    }

    public function addPlayCampaignNarration(string $campaignId, string $actor, string $text): array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_narrations (campaign_id, sequence, actor, kind, text) VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_narrations WHERE campaign_id = ?), 0) + 1, ?, ?, ?)');
            $stmt->execute([$campaignId, $campaignId, $actor, 'narration', $text]);
            $id = (int) $this->pdo->lastInsertId();
            $select = $this->pdo->prepare('SELECT sequence, actor, kind, text FROM play_campaign_narrations WHERE id = ?');
            $select->execute([$id]);
            $row = $select->fetch();
            $this->pdo->exec('COMMIT');

            return [
                'sequence' => (int) $row['sequence'],
                'actor' => $row['actor'],
                'kind' => $row['kind'],
                'text' => $row['text'],
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function addPlayCampaignAction(string $campaignId, string $actor, string $type, string $text): array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_narrations (campaign_id, sequence, actor, kind, type, text) VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_narrations WHERE campaign_id = ?), 0) + 1, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $campaignId, $actor, 'action', $type, $text]);
            $id = (int) $this->pdo->lastInsertId();
            $select = $this->pdo->prepare('SELECT sequence, actor, kind, type, text FROM play_campaign_narrations WHERE id = ?');
            $select->execute([$id]);
            $row = $select->fetch();
            $this->pdo->exec('COMMIT');

            return [
                'sequence' => (int) $row['sequence'],
                'actor' => $row['actor'],
                'kind' => $row['kind'],
                'type' => $row['type'],
                'text' => $row['text'],
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function addPlayCampaignEncounterAction(string $campaignId, string $encounterId, string $actor, string $type, string $target, string $text): array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_narrations (campaign_id, sequence, actor, kind, type, target, text) VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_narrations WHERE campaign_id = ?), 0) + 1, ?, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $campaignId, $actor, 'combat_action', $type, $target, $text]);
            $id = (int) $this->pdo->lastInsertId();
            $select = $this->pdo->prepare('SELECT sequence, actor, kind, type, target, text FROM play_campaign_narrations WHERE id = ?');
            $select->execute([$id]);
            $row = $select->fetch();
            $this->pdo->exec('COMMIT');

            return [
                'sequence' => (int) $row['sequence'],
                'actor' => $row['actor'],
                'kind' => $row['kind'],
                'type' => $row['type'],
                'target' => $row['target'],
                'text' => $row['text'],
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function setPlayCampaignCurrentActor(string $campaignId, string $actor): bool
    {
        $stmt = $this->pdo->prepare('UPDATE play_campaigns SET current_actor = ? WHERE id = ?');
        $stmt->execute([$actor, $campaignId]);

        return $stmt->rowCount() > 0;
    }

    public function addPlayCampaignResolution(string $campaignId, string $actor, string $text, string $nextActor): array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_narrations (campaign_id, sequence, actor, kind, text) VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_narrations WHERE campaign_id = ?), 0) + 1, ?, ?, ?)');
            $stmt->execute([$campaignId, $campaignId, $actor, 'resolution', $text]);
            $id = (int) $this->pdo->lastInsertId();

            $upd = $this->pdo->prepare('UPDATE play_campaigns SET current_actor = ?, turn_number = turn_number + 1 WHERE id = ?');
            $upd->execute([$nextActor, $campaignId]);

            $selectTurn = $this->pdo->prepare('SELECT turn_number FROM play_campaigns WHERE id = ?');
            $selectTurn->execute([$campaignId]);
            $turnNumber = (int) ($selectTurn->fetch()['turn_number'] ?? 0);

            $select = $this->pdo->prepare('SELECT sequence, actor, kind, text FROM play_campaign_narrations WHERE id = ?');
            $select->execute([$id]);
            $row = $select->fetch();
            $this->pdo->exec('COMMIT');

            return [
                'event' => [
                    'sequence' => (int) $row['sequence'],
                    'actor' => $row['actor'],
                    'kind' => $row['kind'],
                    'text' => $row['text'],
                ],
                'next_actor' => $nextActor,
                'turn_number' => $turnNumber,
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignNarrations(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT sequence, actor, kind, text FROM play_campaign_narrations WHERE campaign_id = ? ORDER BY sequence DESC');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'sequence' => (int) $row['sequence'],
                'actor' => $row['actor'],
                'kind' => $row['kind'],
                'text' => $row['text'],
            ];
        }

        return $result;
    }

    public function getPlayCampaignDocument(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT story, dm_notes FROM play_campaign_documents WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return [
                'story' => '',
                'dm_notes' => '',
            ];
        }

        return [
            'story' => (string) $row['story'],
            'dm_notes' => (string) $row['dm_notes'],
        ];
    }

    public function setPlayCampaignDocument(string $campaignId, string $story, string $dmNotes): void
    {
        $stmt = $this->pdo->prepare('
            INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, ?)
            ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story, dm_notes = excluded.dm_notes
        ');
        $stmt->execute([$campaignId, $story, $dmNotes]);
    }

    public function createPlayCampaignExport(string $campaignId): ?array
    {
        $campaign = $this->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return null;
        }

        $document = $this->getPlayCampaignDocument($campaignId);

        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT COALESCE(MAX(version), 0) + 1 FROM play_campaign_exports WHERE campaign_id = ?');
            $stmt->execute([$campaignId]);
            $nextVersion = (int) $stmt->fetchColumn();

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_exports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)');
            $ins->execute([$campaignId, $nextVersion, $document['story'], $campaign['status']]);
            $this->pdo->exec('COMMIT');

            return [
                'version' => $nextVersion,
                'story' => $document['story'],
                'status' => $campaign['status'],
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignExports(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? ORDER BY version ASC');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'version' => (int) $row['version'],
                'story' => $row['story'],
                'status' => $row['status'],
            ];
        }

        return $result;
    }

    public function getPlayCampaignExport(string $campaignId, int $version): ?array
    {
        $stmt = $this->pdo->prepare('SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? AND version = ?');
        $stmt->execute([$campaignId, $version]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'version' => (int) $row['version'],
            'story' => $row['story'],
            'status' => $row['status'],
        ];
    }

    public function createPlayCampaignImport(string $campaignId, int $version, string $story, string $status): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $upd = $this->pdo->prepare('UPDATE play_campaigns SET status = ? WHERE id = ?');
            $upd->execute([$status, $campaignId]);
            if ($upd->rowCount() === 0) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $doc = $this->pdo->prepare("INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, '') ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story");
            $doc->execute([$campaignId, $story]);

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_imports (campaign_id, version, story, status) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET version = excluded.version, story = excluded.story, status = excluded.status');
            $ins->execute([$campaignId, $version, $story, $status]);

            $this->pdo->exec('COMMIT');

            return [
                'version' => $version,
                'story' => $story,
                'status' => $status,
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignImport(string $campaignId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT version, story, status FROM play_campaign_imports WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'version' => (int) $row['version'],
            'story' => $row['story'],
            'status' => $row['status'],
        ];
    }

    public function createPlayCampaignMigration(string $campaignId, string $story, string $campaignName): array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?');
            $stmt->execute([$campaignId]);
            $existing = $stmt->fetch();

            if ($existing) {
                $this->pdo->exec('COMMIT');

                return [
                    'created' => false,
                    'schema_version' => (int) $existing['schema_version'],
                    'story' => $existing['story'],
                    'campaign_name' => $existing['campaign_name'],
                ];
            }

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_migrations (campaign_id, schema_version, story, campaign_name) VALUES (?, ?, ?, ?)');
            $ins->execute([$campaignId, 2, $story, $campaignName]);

            $this->pdo->exec('COMMIT');

            return [
                'created' => true,
                'schema_version' => 2,
                'story' => $story,
                'campaign_name' => $campaignName,
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignMigration(string $campaignId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'schema_version' => (int) $row['schema_version'],
            'story' => $row['story'],
            'campaign_name' => $row['campaign_name'],
        ];
    }

    public function getCampaign(string $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM campaigns WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'id' => $row['id'],
            'name' => $row['name'],
            'dm' => $row['dm'],
        ];
    }

    public function createCampaignCharacter(string $campaignId, array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([$data['id'], $campaignId, $data['name'], $data['level'], $data['class']]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getCampaignCharacters(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'id' => $row['id'],
                'name' => $row['name'],
                'level' => (int) $row['level'],
                'class' => $row['class'],
            ];
        }

        return $result;
    }

    public function getCampaignCharacter(string $campaignId, string $characterId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT id, name, level, class FROM campaign_characters WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$characterId, $campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'id' => $row['id'],
            'name' => $row['name'],
            'level' => (int) $row['level'],
            'class' => $row['class'],
        ];
    }

    public function createCampaignEvent(string $campaignId, array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)');
            $stmt->execute([$data['id'], $campaignId, $data['kind'], $data['summary'] ?? null]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getCampaignEventCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();

        return (int) ($row['count'] ?? 0);
    }

    public function getLatestCampaignEvent(string $campaignId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT id, kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY id DESC LIMIT 1');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();

        return $row ?: null;
    }

    public function getCampaignCharacterCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM campaign_characters WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        return (int) ($stmt->fetch()['count'] ?? 0);
    }

    public function getCampaignQuestCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM quests WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        return (int) ($stmt->fetch()['count'] ?? 0);
    }

    public function getCampaignNpcCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        return (int) ($stmt->fetch()['count'] ?? 0);
    }

    public function getCampaignInventoryItemCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare("SELECT COUNT(*) AS count FROM campaign_inventory WHERE campaign_id = ? AND source = 'entry'");
        $stmt->execute([$campaignId]);

        return (int) ($stmt->fetch()['count'] ?? 0);
    }

    public function getCampaignSessionCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM campaign_sessions WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        return (int) ($stmt->fetch()['count'] ?? 0);
    }

    public function getCampaignOpenQuestCount(string $campaignId): int
    {
        $summary = $this->getQuestSummary($campaignId);

        return (int) ($summary['active'] ?? 0);
    }

    public function getCampaignFriendlyNpcCount(string $campaignId): int
    {
        $summary = $this->getRelationshipSummary($campaignId);

        return (int) ($summary['friendly_npcs'] ?? 0);
    }

    public function getCampaignInventoryRowCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM campaign_inventory WHERE campaign_id = ? AND quantity > 0');
        $stmt->execute([$campaignId]);

        return (int) ($stmt->fetch()['count'] ?? 0);
    }

    public function getSchemaVersion(): int
    {
        $stmt = $this->pdo->query('SELECT version FROM schema_version LIMIT 1');
        $row = $stmt->fetch();

        return (int) ($row['version'] ?? 1);
    }

    public function createQuest(string $campaignId, array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO quests (id, campaign_id, title, status) VALUES (?, ?, ?, ?)');
            $stmt->execute([$data['id'], $campaignId, $data['title'], $data['status']]);
            $insert = $this->pdo->prepare('INSERT INTO quest_milestones (quest_id, milestone, done) VALUES (?, ?, 0)');
            foreach ($data['milestones'] as $milestone) {
                $insert->execute([$data['id'], $milestone]);
            }

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getQuest(string $questId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT id, campaign_id, title, status FROM quests WHERE id = ?');
        $stmt->execute([$questId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return $this->hydrateQuest($row);
    }

    private function hydrateQuest(array $row): array
    {
        $stmt = $this->pdo->prepare('SELECT milestone, done FROM quest_milestones WHERE quest_id = ? ORDER BY id');
        $stmt->execute([$row['id']]);
        $milestones = [];
        $doneCount = 0;
        foreach ($stmt->fetchAll() as $m) {
            $isDone = (int) $m['done'] === 1;
            $milestones[] = [
                'milestone' => $m['milestone'],
                'done' => $isDone,
            ];
            if ($isDone) {
                $doneCount++;
            }
        }
        $total = count($milestones);
        $status = $row['status'];
        if ($total > 0 && $doneCount === $total) {
            $status = 'completed';
        }

        return [
            'id' => $row['id'],
            'campaign_id' => $row['campaign_id'],
            'title' => $row['title'],
            'status' => $status,
            'milestones_total' => $total,
            'milestones_done' => $doneCount,
            'milestones' => $milestones,
        ];
    }

    public function updateQuestProgress(string $campaignId, string $questId, array $completed): ?array
    {
        $quest = $this->getQuest($questId);
        if (!$quest || $quest['campaign_id'] !== $campaignId) {
            return null;
        }

        $stmt = $this->pdo->prepare('UPDATE quest_milestones SET done = 1 WHERE quest_id = ? AND milestone = ?');
        foreach ($completed as $milestone) {
            $stmt->execute([$questId, $milestone]);
        }

        return $this->getQuest($questId);
    }

    public function getQuestSummary(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT id FROM quests WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $active = 0;
        $completed = 0;
        $blocked = 0;
        foreach ($stmt->fetchAll() as $row) {
            $quest = $this->getQuest($row['id']);
            if (!$quest) {
                continue;
            }
            if ($quest['milestones_done'] === $quest['milestones_total'] && $quest['milestones_total'] > 0) {
                $completed++;
            } elseif ($quest['status'] === 'blocked') {
                $blocked++;
            } elseif ($quest['status'] === 'active') {
                $active++;
            }
        }

        return [
            'campaign_id' => $campaignId,
            'active' => $active,
            'completed' => $completed,
            'blocked' => $blocked,
        ];
    }

    public function createFaction(string $campaignId, array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO campaign_factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)');
            $stmt->execute([$data['id'], $campaignId, $data['name'], $data['stance']]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getFaction(string $campaignId, string $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT id, name, stance FROM campaign_factions WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$id, $campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'id' => $row['id'],
            'name' => $row['name'],
            'stance' => $row['stance'],
        ];
    }

    public function getFactions(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT id, name, stance FROM campaign_factions WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'id' => $row['id'],
                'name' => $row['name'],
                'stance' => $row['stance'],
            ];
        }

        return $result;
    }

    public function createNpc(string $campaignId, array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO campaign_npcs (id, campaign_id, faction_id, name, disposition) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([$data['id'], $campaignId, $data['faction_id'], $data['name'], $data['disposition']]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getNpc(string $campaignId, string $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT id, faction_id, name, disposition FROM campaign_npcs WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$id, $campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'id' => $row['id'],
            'faction_id' => $row['faction_id'],
            'name' => $row['name'],
            'disposition' => (int) $row['disposition'],
        ];
    }

    public function getNpcs(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT id, faction_id, name, disposition FROM campaign_npcs WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'id' => $row['id'],
                'faction_id' => $row['faction_id'],
                'name' => $row['name'],
                'disposition' => (int) $row['disposition'],
            ];
        }

        return $result;
    }

    public function getRelationshipSummary(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM campaign_factions WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $factions = (int) ($stmt->fetch()['count'] ?? 0);

        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $npcs = (int) ($stmt->fetch()['count'] ?? 0);

        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0');
        $stmt->execute([$campaignId]);
        $friendlyNpcs = (int) ($stmt->fetch()['count'] ?? 0);

        return [
            'campaign_id' => $campaignId,
            'factions' => $factions,
            'npcs' => $npcs,
            'friendly_npcs' => $friendlyNpcs,
        ];
    }

    public function addInventoryItem(string $campaignId, string $itemSlug, int $quantity, string $owner, string $source = 'entry'): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner, source) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $itemSlug, $quantity, $owner, $source]);
    }

    public function hasAvailablePartyQuantity(string $campaignId, string $itemSlug, int $quantity): bool
    {
        $stmt = $this->pdo->prepare("
            SELECT COALESCE(SUM(CASE WHEN owner = 'party' THEN quantity ELSE 0 END), 0)
                 - COALESCE(SUM(CASE WHEN owner != 'party' THEN quantity ELSE 0 END), 0) AS available
            FROM campaign_inventory
            WHERE campaign_id = ? AND item_slug = ?
        ");
        $stmt->execute([$campaignId, $itemSlug]);
        $available = (int) ($stmt->fetch()['available'] ?? 0);

        return $available >= $quantity;
    }

    public function getInventorySummary(string $campaignId): array
    {
        $stmt = $this->pdo->prepare("SELECT COUNT(*) AS count FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party'");
        $stmt->execute([$campaignId]);
        $partyItems = (int) ($stmt->fetch()['count'] ?? 0);

        $stmt = $this->pdo->prepare("SELECT COUNT(*) AS count FROM campaign_inventory WHERE campaign_id = ? AND owner != 'party'");
        $stmt->execute([$campaignId]);
        $assignedItems = (int) ($stmt->fetch()['count'] ?? 0);

        $stmt = $this->pdo->prepare("
            SELECT item_slug, SUM(quantity) AS total
            FROM campaign_inventory
            WHERE campaign_id = ? AND owner = 'party'
            GROUP BY item_slug
        ");
        $stmt->execute([$campaignId]);
        $partyQuantities = [];
        foreach ($stmt->fetchAll() as $row) {
            $partyQuantities[$row['item_slug']] = (int) $row['total'];
        }

        $stmt = $this->pdo->prepare("
            SELECT item_slug, SUM(quantity) AS total
            FROM campaign_inventory
            WHERE campaign_id = ? AND owner != 'party'
            GROUP BY item_slug
        ");
        $stmt->execute([$campaignId]);
        $assignedQuantities = [];
        foreach ($stmt->fetchAll() as $row) {
            $assignedQuantities[$row['item_slug']] = (int) $row['total'];
        }

        $result = [
            'campaign_id' => $campaignId,
            'party_items' => $partyItems,
            'assigned_items' => $assignedItems,
        ];

        foreach ($partyQuantities as $slug => $qty) {
            $available = $qty - ($assignedQuantities[$slug] ?? 0);
            $key = $this->pluralizeSlug($slug) . '_available';
            $result[$key] = $available;
        }

        return $result;
    }

    public function createCraftingProject(array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO downtime_crafting (id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status) VALUES (?, ?, ?, ?, ?, 0, ?, ?)');
            $stmt->execute([
                $data['id'],
                $data['campaign_id'],
                $data['character_id'],
                $data['item_slug'],
                $data['days_required'],
                $data['cost_gp'],
                'active',
            ]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getCraftingProject(string $projectId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM downtime_crafting WHERE id = ?');
        $stmt->execute([$projectId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'id' => $row['id'],
            'campaign_id' => $row['campaign_id'],
            'character_id' => $row['character_id'],
            'item_slug' => $row['item_slug'],
            'days_required' => (int) $row['days_required'],
            'days_completed' => (int) $row['days_completed'],
            'cost_gp' => (int) $row['cost_gp'],
            'status' => $row['status'],
        ];
    }

    public function advanceCraftingProject(string $projectId, int $days): ?array
    {
        $project = $this->getCraftingProject($projectId);
        if (!$project) {
            return null;
        }

        $remaining = $project['days_required'] - $project['days_completed'];
        if ($remaining <= 0) {
            return $project;
        }

        $completed = min($project['days_completed'] + $days, $project['days_required']);
        $status = $completed >= $project['days_required'] ? 'complete' : 'active';

        $stmt = $this->pdo->prepare('UPDATE downtime_crafting SET days_completed = ?, status = ? WHERE id = ?');
        $stmt->execute([$completed, $status, $projectId]);

        $project['days_completed'] = $completed;
        $project['status'] = $status;

        return $project;
    }

    public function createCampaignSession(string $campaignId, array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO campaign_sessions (id, campaign_id, starts_at, duration_minutes, agenda_json) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([
                $data['id'],
                $campaignId,
                $data['starts_at'],
                $data['duration_minutes'],
                json_encode($data['agenda'], JSON_THROW_ON_ERROR),
            ]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getCampaignSession(string $campaignId, string $sessionId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT id, campaign_id, starts_at, duration_minutes, agenda_json FROM campaign_sessions WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$sessionId, $campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return $this->hydrateSession($row);
    }

    public function getNextCampaignSession(string $campaignId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT id, campaign_id, starts_at, duration_minutes, agenda_json FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at ASC, id ASC LIMIT 1');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return $this->hydrateSession($row);
    }

    private function hydrateSession(array $row): array
    {
        return [
            'id' => $row['id'],
            'campaign_id' => $row['campaign_id'],
            'starts_at' => $row['starts_at'],
            'duration_minutes' => (int) $row['duration_minutes'],
            'agenda' => json_decode($row['agenda_json'], true, 512, JSON_THROW_ON_ERROR),
        ];
    }

    public function recordAttendance(string $campaignId, string $sessionId, array $present, array $absent): ?array
    {
        $session = $this->getCampaignSession($campaignId, $sessionId);
        if (!$session) {
            return null;
        }

        $stmt = $this->pdo->prepare('INSERT OR REPLACE INTO session_attendance (session_id, character_id, present) VALUES (?, ?, ?)');
        foreach ($present as $characterId) {
            $stmt->execute([$sessionId, $characterId, 1]);
        }
        foreach ($absent as $characterId) {
            $stmt->execute([$sessionId, $characterId, 0]);
        }

        return [
            'session_id' => $sessionId,
            'present_count' => count($present),
            'absent_count' => count($absent),
        ];
    }

    public function createPlayCampaignScene(string $campaignId, string $sceneId, string $name): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_scenes (campaign_id, scene_id, name, status) VALUES (?, ?, ?, ?)');
            $stmt->execute([$campaignId, $sceneId, $name, 'open']);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignScene(string $campaignId, string $sceneId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT scene_id, name, status FROM play_campaign_scenes WHERE campaign_id = ? AND scene_id = ?');
        $stmt->execute([$campaignId, $sceneId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'id' => $row['scene_id'],
            'name' => $row['name'],
            'status' => $row['status'],
        ];
    }

    public function closePlayCampaignScene(string $campaignId, string $sceneId): bool
    {
        $stmt = $this->pdo->prepare("UPDATE play_campaign_scenes SET status = 'closed' WHERE campaign_id = ? AND scene_id = ? AND status = 'open'");
        $stmt->execute([$campaignId, $sceneId]);

        return $stmt->rowCount() > 0;
    }

    public function setPlayCampaignCurrentScene(string $campaignId, string $sceneId): bool
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?');
            $stmt->execute([$sceneId, $campaignId]);

            $locStmt = $this->pdo->prepare('UPDATE play_campaigns SET current_location_id = ? WHERE id = ? AND current_location_id IS NULL AND EXISTS (SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND location_id = ?)');
            $locStmt->execute([$sceneId, $campaignId, $campaignId, $sceneId]);

            $this->pdo->exec('COMMIT');

            return true;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function addPlayCampaignSceneEvent(string $campaignId, string $actor, string $sceneId): array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_narrations (campaign_id, sequence, actor, kind, text) VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_narrations WHERE campaign_id = ?), 0) + 1, ?, ?, ?)');
            $stmt->execute([$campaignId, $campaignId, $actor, 'scene', $sceneId]);
            $id = (int) $this->pdo->lastInsertId();
            $select = $this->pdo->prepare('SELECT sequence, actor, kind, text FROM play_campaign_narrations WHERE id = ?');
            $select->execute([$id]);
            $row = $select->fetch();
            $this->pdo->exec('COMMIT');

            return [
                'sequence' => (int) $row['sequence'],
                'actor' => $row['actor'],
                'kind' => $row['kind'],
                'text' => $row['text'],
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function addPlayCampaignNudge(string $campaignId, string $actor, string $target, string $message): array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $upd = $this->pdo->prepare('UPDATE play_campaigns SET nudge_count = COALESCE(nudge_count, 0) + 1 WHERE id = ?');
            $upd->execute([$campaignId]);

            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_narrations (campaign_id, sequence, actor, kind, text) VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_narrations WHERE campaign_id = ?), 0) + 1, ?, ?, ?)');
            $stmt->execute([$campaignId, $campaignId, $actor, 'nudge', $message]);

            $select = $this->pdo->prepare('SELECT nudge_count FROM play_campaigns WHERE id = ?');
            $select->execute([$campaignId]);
            $nudgeCount = (int) ($select->fetch()['nudge_count'] ?? 0);

            $this->pdo->exec('COMMIT');

            return [
                'actor' => $actor,
                'target' => $target,
                'message' => $message,
                'nudge_count' => $nudgeCount,
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignCurrentScene(string $campaignId): ?array
    {
        $stmt = $this->pdo->prepare('
            SELECT s.scene_id AS id, s.name, s.status
            FROM play_campaigns c
            JOIN play_campaign_scenes s ON c.current_scene_id = s.scene_id AND c.id = s.campaign_id
            WHERE c.id = ? AND s.status = \'open\'
        ');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'id' => $row['id'],
            'name' => $row['name'],
            'status' => $row['status'],
        ];
    }

    public function createPlayCampaignLocation(string $campaignId, string $locationId, string $name): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_locations (campaign_id, location_id, name) VALUES (?, ?, ?)');
            $stmt->execute([$campaignId, $locationId, $name]);

            $upd = $this->pdo->prepare('UPDATE play_campaigns SET current_location_id = ? WHERE id = ? AND current_location_id IS NULL');
            $upd->execute([$locationId, $campaignId]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignLocation(string $campaignId, string $locationId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT location_id, name FROM play_campaign_locations WHERE campaign_id = ? AND location_id = ?');
        $stmt->execute([$campaignId, $locationId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'id' => $row['location_id'],
            'name' => $row['name'],
        ];
    }

    public function createPlayCampaignLocationConnection(string $campaignId, string $fromId, string $toId, int $travelTurns): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)');
            $stmt->execute([$campaignId, $fromId, $toId, $travelTurns]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignLocationConnections(string $campaignId, string $fromId): array
    {
        $stmt = $this->pdo->prepare('
            SELECT c.to_id AS id, l.name, c.travel_turns
            FROM play_campaign_location_connections c
            JOIN play_campaign_locations l ON c.campaign_id = l.campaign_id AND c.to_id = l.location_id
            WHERE c.campaign_id = ? AND c.from_id = ?
            ORDER BY c.to_id
        ');
        $stmt->execute([$campaignId, $fromId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'id' => $row['id'],
                'name' => $row['name'],
                'travel_turns' => (int) $row['travel_turns'],
            ];
        }

        return $result;
    }

    public function getPlayCampaignLocationConnection(string $campaignId, string $fromId, string $toId): ?array
    {
        $stmt = $this->pdo->prepare('
            SELECT c.to_id AS id, l.name, c.travel_turns
            FROM play_campaign_location_connections c
            JOIN play_campaign_locations l ON c.campaign_id = l.campaign_id AND c.to_id = l.location_id
            WHERE c.campaign_id = ? AND c.from_id = ? AND c.to_id = ?
            LIMIT 1
        ');
        $stmt->execute([$campaignId, $fromId, $toId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'id' => $row['id'],
            'name' => $row['name'],
            'travel_turns' => (int) $row['travel_turns'],
        ];
    }

    public function addPlayCampaignTravel(string $campaignId, string $actor, string $destinationId, int $travelTurns, string $nextActor): array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_narrations (campaign_id, sequence, actor, kind, text) VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_narrations WHERE campaign_id = ?), 0) + 1, ?, ?, ?)');
            $stmt->execute([$campaignId, $campaignId, $actor, 'travel', "Travel to {$destinationId}"]);
            $id = (int) $this->pdo->lastInsertId();

            $upd = $this->pdo->prepare('UPDATE play_campaigns SET current_actor = ? WHERE id = ?');
            $upd->execute([$nextActor, $campaignId]);

            $select = $this->pdo->prepare('SELECT sequence, actor, kind, text FROM play_campaign_narrations WHERE id = ?');
            $select->execute([$id]);
            $row = $select->fetch();
            $this->pdo->exec('COMMIT');

            return [
                'sequence' => (int) $row['sequence'],
                'actor' => $row['actor'],
                'kind' => $row['kind'],
                'destination_id' => $destinationId,
                'travel_turns' => $travelTurns,
                'next_actor' => $nextActor,
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignMemberHp(string $campaignId, string $username): ?array
    {
        $stmt = $this->pdo->prepare('SELECT hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? AND username = ? LIMIT 1');
        $stmt->execute([$campaignId, $username]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'hp_current' => (int) $row['hp_current'],
            'hp_max' => (int) $row['hp_max'],
        ];
    }

    public function addPlayCampaignRest(string $campaignId, string $actor, string $type, int $hpCurrent, int $hpMax, string $nextActor): array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            if ($type === 'long') {
                $upd = $this->pdo->prepare("UPDATE play_campaign_members SET hp_current = hp_max, status = 'conscious', death_save_successes = 0, death_save_failures = 0 WHERE campaign_id = ? AND username = ?");
                $upd->execute([$campaignId, $actor]);
                $hpCurrent = $hpMax;

                $restStmt = $this->pdo->prepare('SELECT class, level FROM play_campaign_members WHERE campaign_id = ? AND username = ? LIMIT 1');
                $restStmt->execute([$campaignId, $actor]);
                $restRow = $restStmt->fetch();
                if ($restRow) {
                    $slots = \App\Domain\SpellRules::spellSlots((string) $restRow['class'], (int) $restRow['level']);
                    $slotsUpd = $this->pdo->prepare('UPDATE play_campaign_members SET spell_slots_json = ? WHERE campaign_id = ? AND username = ?');
                    $slotsUpd->execute([json_encode($slots, JSON_THROW_ON_ERROR), $campaignId, $actor]);
                }
            }

            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_narrations (campaign_id, sequence, actor, kind, type, text) VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_narrations WHERE campaign_id = ?), 0) + 1, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $campaignId, $actor, 'rest', $type, "Rest: {$type}"]);
            $id = (int) $this->pdo->lastInsertId();

            $upd = $this->pdo->prepare('UPDATE play_campaigns SET current_actor = ? WHERE id = ?');
            $upd->execute([$nextActor, $campaignId]);

            $select = $this->pdo->prepare('SELECT sequence, actor, kind, type, text FROM play_campaign_narrations WHERE id = ?');
            $select->execute([$id]);
            $row = $select->fetch();
            $this->pdo->exec('COMMIT');

            return [
                'sequence' => (int) $row['sequence'],
                'actor' => $row['actor'],
                'kind' => $row['kind'],
                'type' => $row['type'],
                'hp_current' => $hpCurrent,
                'hp_max' => $hpMax,
                'next_actor' => $nextActor,
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function hasActivePlayCampaignEncounter(string $campaignId): bool
    {
        $stmt = $this->pdo->prepare("SELECT 1 FROM play_campaign_encounters WHERE campaign_id = ? AND status = 'active' LIMIT 1");
        $stmt->execute([$campaignId]);

        return $stmt->fetch() !== false;
    }

    public function createPlayCampaignEncounter(string $campaignId, string $encounterId, string $name): bool
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            if ($this->hasActivePlayCampaignEncounter($campaignId)) {
                $this->pdo->exec('ROLLBACK');

                return false;
            }

            // Remember the current exploration-turn actor so it can be restored
            // when this encounter ends.
            $upd = $this->pdo->prepare("UPDATE play_campaigns SET pre_combat_actor = current_actor, phase = 'combat' WHERE id = ?");
            $upd->execute([$campaignId]);

            $stmt = $this->pdo->prepare("INSERT INTO play_campaign_encounters (id, campaign_id, name, status, combatants_json, order_json) VALUES (?, ?, ?, 'active', '[]', '[]')");
            $stmt->execute([$encounterId, $campaignId, $name]);
            $this->pdo->exec('COMMIT');

            return true;
        } catch (PDOException $e) {
            $this->pdo->exec('ROLLBACK');
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignEncounter(string $campaignId, string $encounterId): ?array
    {
        $stmt = $this->pdo->prepare("SELECT id, name, status, combatants_json, xp_awarded, loot_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?");
        $stmt->execute([$campaignId, $encounterId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'id' => $row['id'],
            'name' => $row['name'],
            'status' => $row['status'],
            'combatants' => json_decode($row['combatants_json'], true, 512, JSON_THROW_ON_ERROR),
            'xp_awarded' => (int) $row['xp_awarded'],
            'loot' => json_decode($row['loot_json'], true, 512, JSON_THROW_ON_ERROR),
        ];
    }

    public function awardPlayCampaignEncounterRewards(string $campaignId, string $encounterId, int $xp, array $loot): bool
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare("SELECT rewards_awarded FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?");
            $stmt->execute([$campaignId, $encounterId]);
            $row = $stmt->fetch();
            if (!$row || (int) $row['rewards_awarded'] !== 0) {
                $this->pdo->exec('ROLLBACK');

                return false;
            }

            $upd = $this->pdo->prepare("UPDATE play_campaign_encounters SET xp_awarded = ?, loot_json = ?, rewards_awarded = 1 WHERE campaign_id = ? AND id = ?");
            $upd->execute([$xp, json_encode($loot, JSON_THROW_ON_ERROR), $campaignId, $encounterId]);
            $this->pdo->exec('COMMIT');

            return true;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    /**
     * Close an active encounter.
     *
     * Returns true on success, or false if the encounter is missing or already
     * closed.
     */
    public function closePlayCampaignEncounter(string $campaignId, string $encounterId): bool
    {
        $stmt = $this->pdo->prepare("UPDATE play_campaign_encounters SET status = 'closed' WHERE campaign_id = ? AND id = ? AND status = 'active'");
        $stmt->execute([$campaignId, $encounterId]);

        return $stmt->rowCount() > 0;
    }

    /**
     * End combat for an active encounter and restore the campaign's exploration
     * turn actor.
     *
     * Returns the restored actor username on success, or null if the encounter
     * is missing, already closed, or the campaign has no active encounter.
     */
    public function endPlayCampaignEncounter(string $campaignId, string $encounterId): ?string
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare("SELECT status FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?");
            $stmt->execute([$campaignId, $encounterId]);
            $row = $stmt->fetch();
            if (!$row || $row['status'] !== 'active') {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $upd = $this->pdo->prepare("UPDATE play_campaign_encounters SET status = 'closed' WHERE campaign_id = ? AND id = ?");
            $upd->execute([$campaignId, $encounterId]);

            $select = $this->pdo->prepare('SELECT current_actor, pre_combat_actor, owner FROM play_campaigns WHERE id = ?');
            $select->execute([$campaignId]);
            $campaignRow = $select->fetch();
            if (!$campaignRow) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $restoredActor = $campaignRow['pre_combat_actor'] ?? $campaignRow['current_actor'] ?? $campaignRow['owner'];

            $upd2 = $this->pdo->prepare("UPDATE play_campaigns SET current_actor = ?, pre_combat_actor = NULL, phase = 'exploration' WHERE id = ?");
            $upd2->execute([$restoredActor, $campaignId]);

            $this->pdo->exec('COMMIT');

            return $restoredActor;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function addPlayCampaignEncounterCondition(string $campaignId, string $encounterId, string $target, string $condition, int $duration): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO play_campaign_encounter_conditions (campaign_id, encounter_id, target, condition, remaining_rounds) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $encounterId, $target, $condition, $duration]);
    }

    public function getPlayCampaignEncounterConditionsForTarget(string $campaignId, string $encounterId, string $target): array
    {
        $stmt = $this->pdo->prepare('SELECT condition, remaining_rounds FROM play_campaign_encounter_conditions WHERE campaign_id = ? AND encounter_id = ? AND target = ?');
        $stmt->execute([$campaignId, $encounterId, $target]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'condition' => $row['condition'],
                'remaining_rounds' => (int) $row['remaining_rounds'],
            ];
        }

        return $result;
    }

    public function getPlayCampaignEncounterConditionsMap(string $campaignId, string $encounterId): array
    {
        $stmt = $this->pdo->prepare('SELECT target, condition, remaining_rounds FROM play_campaign_encounter_conditions WHERE campaign_id = ? AND encounter_id = ?');
        $stmt->execute([$campaignId, $encounterId]);
        $map = [];
        foreach ($stmt->fetchAll() as $row) {
            $map[$row['target']][] = [
                'condition' => $row['condition'],
                'remaining_rounds' => (int) $row['remaining_rounds'],
            ];
        }

        return $map;
    }

    public function expirePlayCampaignEncounterConditions(string $campaignId, string $encounterId, string $target): void
    {
        $stmt = $this->pdo->prepare('SELECT id, remaining_rounds FROM play_campaign_encounter_conditions WHERE campaign_id = ? AND encounter_id = ? AND target = ?');
        $stmt->execute([$campaignId, $encounterId, $target]);
        foreach ($stmt->fetchAll() as $row) {
            $newRemaining = (int) $row['remaining_rounds'] - 1;
            if ($newRemaining > 0) {
                $upd = $this->pdo->prepare('UPDATE play_campaign_encounter_conditions SET remaining_rounds = ? WHERE id = ?');
                $upd->execute([$newRemaining, $row['id']]);
            } else {
                $del = $this->pdo->prepare('DELETE FROM play_campaign_encounter_conditions WHERE id = ?');
                $del->execute([$row['id']]);
            }
        }
    }

    public function addPlayCampaignEncounterMonster(string $campaignId, string $encounterId, array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_encounter_monsters (campaign_id, encounter_id, monster_id, name, hp_max, hp_current, initiative) VALUES (?, ?, ?, ?, ?, ?, ?)');
            $stmt->execute([
                $campaignId,
                $encounterId,
                $data['monster_id'],
                $data['name'],
                $data['hp_max'],
                $data['hp_max'],
                $data['initiative'],
            ]);
            $this->insertEncounterOrderEntry($campaignId, $encounterId, ['kind' => 'monster', 'id' => $data['monster_id']]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function removePlayCampaignEncounterMonster(string $campaignId, string $encounterId, string $monsterId): bool
    {
        $stmt = $this->pdo->prepare('DELETE FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?');
        $stmt->execute([$campaignId, $encounterId, $monsterId]);
        $removed = $stmt->rowCount() > 0;
        if ($removed) {
            $this->removeEncounterOrderEntry($campaignId, $encounterId, 'monster', $monsterId);
        }

        return $removed;
    }

    public function addPlayCampaignEncounterCombatant(string $campaignId, string $encounterId, array $combatant): bool
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare("SELECT combatants_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?");
            $stmt->execute([$campaignId, $encounterId]);
            $row = $stmt->fetch();
            if (!$row) {
                $this->pdo->exec('ROLLBACK');

                return false;
            }

            $combatants = json_decode($row['combatants_json'], true, 512, JSON_THROW_ON_ERROR);
            foreach ($combatants as $c) {
                if (($c['member'] ?? '') === $combatant['member']) {
                    $this->pdo->exec('ROLLBACK');

                    return false;
                }
            }

            $combatants[] = $combatant;
            $upd = $this->pdo->prepare("UPDATE play_campaign_encounters SET combatants_json = ? WHERE campaign_id = ? AND id = ?");
            $upd->execute([json_encode($combatants, JSON_THROW_ON_ERROR), $campaignId, $encounterId]);
            $this->insertEncounterOrderEntry($campaignId, $encounterId, ['kind' => 'member', 'id' => $combatant['member']]);
            $this->pdo->exec('COMMIT');

            return true;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function removePlayCampaignEncounterCombatant(string $campaignId, string $encounterId, string $member): bool
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare("SELECT combatants_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?");
            $stmt->execute([$campaignId, $encounterId]);
            $row = $stmt->fetch();
            if (!$row) {
                $this->pdo->exec('ROLLBACK');

                return false;
            }

            $combatants = json_decode($row['combatants_json'], true, 512, JSON_THROW_ON_ERROR);
            $found = false;
            $remaining = [];
            foreach ($combatants as $c) {
                if (($c['member'] ?? '') === $member) {
                    $found = true;
                    continue;
                }
                $remaining[] = $c;
            }
            if (!$found) {
                $this->pdo->exec('ROLLBACK');

                return false;
            }

            $upd = $this->pdo->prepare("UPDATE play_campaign_encounters SET combatants_json = ? WHERE campaign_id = ? AND id = ?");
            $upd->execute([json_encode($remaining, JSON_THROW_ON_ERROR), $campaignId, $encounterId]);
            $this->removeEncounterOrderEntry($campaignId, $encounterId, 'member', $member);
            $this->pdo->exec('COMMIT');

            return true;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignEncounterTurn(string $campaignId, string $encounterId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT round, turn_index, combatants_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?');
        $stmt->execute([$campaignId, $encounterId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        $order = $this->resolveEncounterOrder($campaignId, $encounterId, $row['combatants_json']);
        $turnIndex = (int) $row['turn_index'];

        return [
            'round' => (int) $row['round'],
            'turn_index' => $turnIndex,
            'active' => $order[$turnIndex] ?? null,
            'order' => $order,
        ];
    }

    public function advancePlayCampaignEncounterTurn(string $campaignId, string $encounterId): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT round, turn_index, combatants_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?');
            $stmt->execute([$campaignId, $encounterId]);
            $row = $stmt->fetch();
            if (!$row) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $order = $this->resolveEncounterOrder($campaignId, $encounterId, $row['combatants_json']);
            $count = count($order);
            $turnIndex = (int) $row['turn_index'];
            $round = (int) $row['round'];
            $newTurnIndex = $turnIndex;
            $newRound = $round;
            if ($count > 0) {
                $newTurnIndex = $turnIndex + 1;
                if ($newTurnIndex >= $count) {
                    $newTurnIndex = 0;
                    $newRound++;
                }
                $activeId = $this->combatantIdentifier($order[$newTurnIndex] ?? null);
                if ($activeId !== null) {
                    $this->expirePlayCampaignEncounterConditions($campaignId, $encounterId, $activeId);
                }
            }

            $upd = $this->pdo->prepare('UPDATE play_campaign_encounters SET round = ?, turn_index = ? WHERE campaign_id = ? AND id = ?');
            $upd->execute([$newRound, $newTurnIndex, $campaignId, $encounterId]);
            $this->pdo->exec('COMMIT');

            return [
                'round' => $newRound,
                'turn_index' => $newTurnIndex,
                'active' => $order[$newTurnIndex] ?? null,
                'order' => $order,
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    /**
     * Move the current combatant to a later position in the initiative order.
     *
     * Returns null if the encounter is missing, or an array with 'error' =>
     * 'invalid index' if the requested index is not a valid later position.
     */
    public function delayPlayCampaignEncounterTurn(string $campaignId, string $encounterId, int $newIndex): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $turn = $this->getPlayCampaignEncounterTurn($campaignId, $encounterId);
            if ($turn === null) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $order = $turn['order'];
            $count = count($order);
            $turnIndex = $turn['turn_index'];
            if ($newIndex <= $turnIndex || $newIndex >= $count || $count <= 1) {
                $this->pdo->exec('ROLLBACK');

                return ['error' => 'invalid index', 'order' => $order];
            }

            $stmt = $this->pdo->prepare('SELECT order_json, combatants_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?');
            $stmt->execute([$campaignId, $encounterId]);
            $row = $stmt->fetch();
            $entries = json_decode($row['order_json'] ?? '[]', true, 512, JSON_THROW_ON_ERROR);

            $current = array_splice($entries, $turnIndex, 1)[0];
            array_splice($entries, $newIndex, 0, [$current]);

            $this->saveEncounterOrder($campaignId, $encounterId, $entries);
            $upd = $this->pdo->prepare('UPDATE play_campaign_encounters SET turn_index = ? WHERE campaign_id = ? AND id = ?');
            $upd->execute([$newIndex, $campaignId, $encounterId]);
            $this->pdo->exec('COMMIT');

            return [
                'order' => $this->hydrateEncounterOrderEntries($campaignId, $encounterId, $entries, $row['combatants_json']),
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function damagePlayCampaignEncounterCombatant(string $campaignId, string $encounterId, string $target, int $amount): ?array
    {
        $monster = $this->getPlayCampaignEncounterMonster($campaignId, $encounterId, $target);
        if ($monster !== null) {
            $hpBefore = $monster['hp_current'];
            $hpAfter = max(0, $hpBefore - $amount);
            $this->updatePlayCampaignEncounterMonsterHp($campaignId, $encounterId, $target, $hpAfter);

            return [
                'target' => $target,
                'hp_before' => $hpBefore,
                'hp_after' => $hpAfter,
                'damage' => $amount,
            ];
        }

        if ($this->isPlayCampaignEncounterCombatant($campaignId, $encounterId, $target)) {
            $hp = $this->getPlayCampaignMemberHp($campaignId, $target);
            if ($hp === null) {
                return null;
            }
            $hpBefore = $hp['hp_current'];
            $hpAfter = max(0, $hpBefore - $amount);
            $this->updatePlayCampaignMemberHp($campaignId, $target, $hpAfter);

            return [
                'target' => $target,
                'hp_before' => $hpBefore,
                'hp_after' => $hpAfter,
                'damage' => $amount,
            ];
        }

        return null;
    }

    public function healPlayCampaignEncounterCombatant(string $campaignId, string $encounterId, string $target, int $amount): ?array
    {
        $monster = $this->getPlayCampaignEncounterMonster($campaignId, $encounterId, $target);
        if ($monster !== null) {
            $hpBefore = $monster['hp_current'];
            $hpAfter = min($monster['hp_max'], $hpBefore + $amount);
            $this->updatePlayCampaignEncounterMonsterHp($campaignId, $encounterId, $target, $hpAfter);

            return [
                'target' => $target,
                'hp_before' => $hpBefore,
                'hp_after' => $hpAfter,
                'healing' => $amount,
            ];
        }

        if ($this->isPlayCampaignEncounterCombatant($campaignId, $encounterId, $target)) {
            $hp = $this->getPlayCampaignMemberHp($campaignId, $target);
            if ($hp === null) {
                return null;
            }
            $hpBefore = $hp['hp_current'];
            $hpAfter = min($hp['hp_max'], $hpBefore + $amount);
            $this->updatePlayCampaignMemberHp($campaignId, $target, $hpAfter);

            return [
                'target' => $target,
                'hp_before' => $hpBefore,
                'hp_after' => $hpAfter,
                'healing' => $amount,
            ];
        }

        return null;
    }

    public function damagePlayCampaignCharacter(string $campaignId, string $characterId, int $amount): ?array
    {
        $member = $this->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($member === null) {
            return null;
        }

        $hpBefore = $member['hp_current'];
        $hpAfter = max(0, $hpBefore - $amount);
        $this->updatePlayCampaignMemberHp($campaignId, $member['username'], $hpAfter);

        return [
            'target' => $characterId,
            'hp_before' => $hpBefore,
            'hp_after' => $hpAfter,
            'damage' => $amount,
        ];
    }

    public function getPlayCampaignCharacterStatus(string $campaignId, string $characterId): ?array
    {
        $member = $this->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($member === null) {
            return null;
        }

        return [
            'character_id' => $characterId,
            'hp_current' => $member['hp_current'],
            'hp_max' => $member['hp_max'],
            'status' => $member['status'],
        ];
    }

    public function healPlayCampaignCharacterByConsumption(string $campaignId, string $characterId, int $amount): void
    {
        $member = $this->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($member === null) {
            return;
        }

        $hpAfter = min($member['hp_max'], $member['hp_current'] + $amount);
        $this->updatePlayCampaignMemberHp($campaignId, $member['username'], $hpAfter);
    }

    public function recordDeathSave(string $campaignId, string $characterId, string $outcome): ?array
    {
        $member = $this->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($member === null) {
            return null;
        }

        $successes = $member['death_save_successes'];
        $failures = $member['death_save_failures'];
        $status = $member['status'];

        if ($outcome === 'success') {
            $successes++;
            if ($successes >= 3) {
                $status = 'stable';
            }
        } elseif ($outcome === 'failure') {
            $failures++;
            if ($failures >= 3) {
                $status = 'dead';
            }
        }

        $stmt = $this->pdo->prepare('UPDATE play_campaign_members SET death_save_successes = ?, death_save_failures = ?, status = ? WHERE campaign_id = ? AND character_id = ?');
        $stmt->execute([$successes, $failures, $status, $campaignId, $characterId]);

        return [
            'character_id' => $characterId,
            'successes' => $successes,
            'failures' => $failures,
            'status' => $status,
        ];
    }

    private function getPlayCampaignEncounterMonster(string $campaignId, string $encounterId, string $monsterId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT monster_id, name, hp_max, hp_current, initiative FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?');
        $stmt->execute([$campaignId, $encounterId, $monsterId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'monster_id' => $row['monster_id'],
            'name' => $row['name'],
            'hp_max' => (int) $row['hp_max'],
            'hp_current' => (int) $row['hp_current'],
            'initiative' => (int) $row['initiative'],
        ];
    }

    private function updatePlayCampaignEncounterMonsterHp(string $campaignId, string $encounterId, string $monsterId, int $hpCurrent): bool
    {
        $stmt = $this->pdo->prepare('UPDATE play_campaign_encounter_monsters SET hp_current = ? WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?');
        $stmt->execute([$hpCurrent, $campaignId, $encounterId, $monsterId]);

        return $stmt->rowCount() > 0;
    }

    private function isPlayCampaignEncounterCombatant(string $campaignId, string $encounterId, string $target): bool
    {
        $stmt = $this->pdo->prepare('SELECT combatants_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?');
        $stmt->execute([$campaignId, $encounterId]);
        $row = $stmt->fetch();
        if (!$row) {
            return false;
        }

        $combatants = json_decode($row['combatants_json'], true, 512, JSON_THROW_ON_ERROR);
        foreach ($combatants as $c) {
            if (($c['member'] ?? '') === $target) {
                return true;
            }
        }

        return false;
    }

    private function updatePlayCampaignMemberHp(string $campaignId, string $username, int $hpCurrent): bool
    {
        if ($hpCurrent > 0) {
            $status = 'conscious';
            $successes = 0;
            $failures = 0;
        } else {
            $status = 'unconscious';
            $successes = 0;
            $failures = 0;
        }

        $stmt = $this->pdo->prepare('UPDATE play_campaign_members SET hp_current = ?, status = ?, death_save_successes = ?, death_save_failures = ? WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$hpCurrent, $status, $successes, $failures, $campaignId, $username]);

        return $stmt->rowCount() > 0;
    }

    /**
     * Resolve the current initiative order for an encounter.
     *
     * If a stored order exists it is used; otherwise the order is computed
     * deterministically from monster and member initiatives and persisted.
     * The returned entries include an internal 'member' key for ownership checks.
     */
    private function resolveEncounterOrder(string $campaignId, string $encounterId, string $combatantsJson): array
    {
        $stmt = $this->pdo->prepare('SELECT order_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?');
        $stmt->execute([$campaignId, $encounterId]);
        $row = $stmt->fetch();
        $stored = null;
        if ($row && !empty($row['order_json'])) {
            $stored = json_decode($row['order_json'], true, 512, JSON_THROW_ON_ERROR);
        }

        if ($stored === null || count($stored) === 0) {
            $entries = $this->computeSortedEncounterOrderEntries($campaignId, $encounterId, $combatantsJson);
            $this->saveEncounterOrder($campaignId, $encounterId, $entries);

            return $this->hydrateEncounterOrderEntries($campaignId, $encounterId, $entries, $combatantsJson);
        }

        $order = $this->hydrateEncounterOrderEntries($campaignId, $encounterId, $stored, $combatantsJson);
        if (count($order) === 0) {
            $entries = $this->computeSortedEncounterOrderEntries($campaignId, $encounterId, $combatantsJson);
            $this->saveEncounterOrder($campaignId, $encounterId, $entries);

            return $this->hydrateEncounterOrderEntries($campaignId, $encounterId, $entries, $combatantsJson);
        }

        return $order;
    }

    /**
     * Compute a sorted order entry list from current monsters and members.
     */
    private function computeSortedEncounterOrderEntries(string $campaignId, string $encounterId, string $combatantsJson): array
    {
        $stmt = $this->pdo->prepare('SELECT monster_id, name, initiative FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? ORDER BY name');
        $stmt->execute([$campaignId, $encounterId]);
        $entries = [];
        foreach ($stmt->fetchAll() as $row) {
            $entries[] = [
                'kind' => 'monster',
                'id' => $row['monster_id'],
                'name' => $row['name'],
                'initiative' => (int) $row['initiative'],
            ];
        }

        $members = json_decode($combatantsJson, true, 512, JSON_THROW_ON_ERROR);
        foreach ($members as $c) {
            $entries[] = [
                'kind' => 'member',
                'id' => $c['member'] ?? '',
                'name' => (string) ($c['name'] ?? ''),
                'initiative' => (int) ($c['initiative'] ?? 0),
            ];
        }

        usort($entries, static function (array $a, array $b): int {
            if ($a['initiative'] !== $b['initiative']) {
                return $b['initiative'] <=> $a['initiative'];
            }

            return strcmp($a['name'], $b['name']);
        });

        return array_map(static fn (array $e): array => ['kind' => $e['kind'], 'id' => $e['id']], $entries);
    }

    /**
     * Hydrate stored order entries into full combatant records.
     */
    private function hydrateEncounterOrderEntries(string $campaignId, string $encounterId, array $entries, string $combatantsJson): array
    {
        $members = json_decode($combatantsJson, true, 512, JSON_THROW_ON_ERROR);
        $memberMap = [];
        foreach ($members as $c) {
            $memberMap[$c['member'] ?? ''] = $c;
        }

        $order = [];
        foreach ($entries as $entry) {
            $kind = $entry['kind'] ?? '';
            $id = $entry['id'] ?? '';
            if ($kind === 'monster') {
                $m = $this->getPlayCampaignEncounterMonster($campaignId, $encounterId, $id);
                if ($m === null) {
                    continue;
                }
                $order[] = [
                    'name' => $m['name'],
                    'kind' => 'monster',
                    'initiative' => $m['initiative'],
                    'monster_id' => $m['monster_id'],
                    'member' => null,
                    'character_id' => null,
                ];
            } elseif ($kind === 'member' && isset($memberMap[$id])) {
                $c = $memberMap[$id];
                $order[] = [
                    'name' => (string) ($c['name'] ?? ''),
                    'kind' => 'member',
                    'initiative' => (int) ($c['initiative'] ?? 0),
                    'member' => $c['member'] ?? null,
                    'character_id' => $c['character_id'] ?? null,
                    'monster_id' => null,
                ];
            }
        }

        return $order;
    }

    /**
     * Persist the order entry list for an encounter.
     */
    private function saveEncounterOrder(string $campaignId, string $encounterId, array $entries): void
    {
        $stmt = $this->pdo->prepare('UPDATE play_campaign_encounters SET order_json = ? WHERE campaign_id = ? AND id = ?');
        $stmt->execute([json_encode($entries, JSON_THROW_ON_ERROR), $campaignId, $encounterId]);
    }

    /**
     * Insert a new combatant into an existing stored order by initiative.
     */
    private function insertEncounterOrderEntry(string $campaignId, string $encounterId, array $newEntry): void
    {
        $stmt = $this->pdo->prepare('SELECT order_json, combatants_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?');
        $stmt->execute([$campaignId, $encounterId]);
        $row = $stmt->fetch();
        if (!$row || empty($row['order_json'])) {
            return;
        }

        $combatantsJson = $row['combatants_json'];
        $entries = json_decode($row['order_json'], true, 512, JSON_THROW_ON_ERROR);
        if (count($entries) === 0) {
            return;
        }

        $newFull = null;
        if ($newEntry['kind'] === 'monster') {
            $m = $this->getPlayCampaignEncounterMonster($campaignId, $encounterId, $newEntry['id']);
            if ($m !== null) {
                $newFull = ['name' => $m['name'], 'initiative' => $m['initiative']];
            }
        } else {
            $members = json_decode($combatantsJson, true, 512, JSON_THROW_ON_ERROR);
            foreach ($members as $c) {
                if (($c['member'] ?? '') === $newEntry['id']) {
                    $newFull = ['name' => (string) ($c['name'] ?? ''), 'initiative' => (int) ($c['initiative'] ?? 0)];
                    break;
                }
            }
        }
        if ($newFull === null) {
            return;
        }

        $insertIndex = count($entries);
        $full = $this->hydrateEncounterOrderEntries($campaignId, $encounterId, $entries, $combatantsJson);
        foreach ($full as $i => $entry) {
            if ($newFull['initiative'] > $entry['initiative']
                || ($newFull['initiative'] === $entry['initiative'] && strcmp($newFull['name'], $entry['name']) < 0)) {
                $insertIndex = $i;
                break;
            }
        }
        array_splice($entries, $insertIndex, 0, [$newEntry]);
        $this->saveEncounterOrder($campaignId, $encounterId, $entries);
    }

    /**
     * Remove a combatant from the stored order, if one exists.
     */
    private function removeEncounterOrderEntry(string $campaignId, string $encounterId, string $kind, string $id): void
    {
        $stmt = $this->pdo->prepare('SELECT order_json FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?');
        $stmt->execute([$campaignId, $encounterId]);
        $row = $stmt->fetch();
        if (!$row || empty($row['order_json'])) {
            return;
        }

        $entries = json_decode($row['order_json'], true, 512, JSON_THROW_ON_ERROR);
        $filtered = [];
        foreach ($entries as $entry) {
            if (($entry['kind'] ?? '') === $kind && ($entry['id'] ?? '') === $id) {
                continue;
            }
            $filtered[] = $entry;
        }
        $this->saveEncounterOrder($campaignId, $encounterId, $filtered);
    }

    private function combatantIdentifier(?array $combatant): ?string
    {
        if ($combatant === null) {
            return null;
        }
        if (($combatant['kind'] ?? '') === 'monster') {
            return $combatant['monster_id'] ?? null;
        }

        return $combatant['member'] ?? null;
    }

    private function pluralizeSlug(string $slug): string
    {
        $segments = explode('-', $slug);
        $lastIndex = count($segments) - 1;
        $last = $segments[$lastIndex];
        if (!str_ends_with($last, 's')) {
            $segments[$lastIndex] = $last . 's';
        }

        return implode('_', $segments);
    }

    public function getPlayCampaignCharacterInventoryItems(string $campaignId, string $characterId): array
    {
        $stmt = $this->pdo->prepare('SELECT item_id, quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? ORDER BY item_id');
        $stmt->execute([$campaignId, $characterId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'item_id' => $row['item_id'],
                'quantity' => (int) $row['quantity'],
            ];
        }

        return $result;
    }

    public function addPlayCampaignCharacterInventoryItem(string $campaignId, string $characterId, string $itemId, int $quantity): int
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity');
            $stmt->execute([$campaignId, $characterId, $itemId, $quantity]);

            $select = $this->pdo->prepare('SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
            $select->execute([$campaignId, $characterId, $itemId]);
            $total = (int) ($select->fetch()['quantity'] ?? 0);
            $this->pdo->exec('COMMIT');

            return $total;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function removePlayCampaignCharacterInventoryItem(string $campaignId, string $characterId, string $itemId, int $quantity): ?int
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $select = $this->pdo->prepare('SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
            $select->execute([$campaignId, $characterId, $itemId]);
            $row = $select->fetch();
            if (!$row) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $current = (int) $row['quantity'];
            if ($current < $quantity) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $remaining = $current - $quantity;
            if ($remaining > 0) {
                $upd = $this->pdo->prepare('UPDATE play_campaign_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
                $upd->execute([$remaining, $campaignId, $characterId, $itemId]);
            } else {
                $del = $this->pdo->prepare('DELETE FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
                $del->execute([$campaignId, $characterId, $itemId]);
            }
            $this->pdo->exec('COMMIT');

            return $remaining;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignCharacterEquipment(string $campaignId, string $characterId, string $slot): ?array
    {
        $stmt = $this->pdo->prepare('SELECT item_id, attuned FROM play_campaign_character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?');
        $stmt->execute([$campaignId, $characterId, $slot]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'item_id' => $row['item_id'],
            'attuned' => (int) $row['attuned'] === 1,
        ];
    }

    public function setPlayCampaignCharacterEquipment(string $campaignId, string $characterId, string $slot, string $itemId, bool $attuned): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO play_campaign_character_equipment (campaign_id, character_id, slot, item_id, attuned) VALUES (?, ?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET item_id = excluded.item_id, attuned = excluded.attuned');
        $stmt->execute([$campaignId, $characterId, $slot, $itemId, $attuned ? 1 : 0]);
    }

    public function getPlayCampaignCharacterAttunementCount(string $campaignId, string $characterId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM play_campaign_character_equipment WHERE campaign_id = ? AND character_id = ? AND attuned = 1');
        $stmt->execute([$campaignId, $characterId]);

        return (int) ($stmt->fetch()['count'] ?? 0);
    }

    public function createPlayCampaignRecipe(string $campaignId, string $recipeId, string $name, array $ingredients, string $outputItem, int $outputQuantity): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_recipes (campaign_id, recipe_id, name, ingredients_json, output_item, output_quantity) VALUES (?, ?, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $recipeId, $name, json_encode($ingredients, JSON_THROW_ON_ERROR), $outputItem, $outputQuantity]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignRecipes(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT recipe_id, name, ingredients_json, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $ingredients = json_decode($row['ingredients_json'], true, 512, JSON_THROW_ON_ERROR);
            if (!is_array($ingredients)) {
                $ingredients = [];
            }
            $result[] = [
                'recipe_id' => $row['recipe_id'],
                'name' => $row['name'],
                'ingredients' => $ingredients,
                'output_item' => $row['output_item'],
                'output_quantity' => (int) $row['output_quantity'],
            ];
        }

        return $result;
    }

    public function getPlayCampaignRecipe(string $campaignId, string $recipeId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT recipe_id, name, ingredients_json, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $recipeId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $ingredients = json_decode($row['ingredients_json'], true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($ingredients)) {
            $ingredients = [];
        }

        return [
            'recipe_id' => $row['recipe_id'],
            'name' => $row['name'],
            'ingredients' => $ingredients,
            'output_item' => $row['output_item'],
            'output_quantity' => (int) $row['output_quantity'],
        ];
    }

    public function craftPlayCampaignRecipe(string $campaignId, string $recipeId, string $characterId): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $recipe = $this->getPlayCampaignRecipe($campaignId, $recipeId);
            if ($recipe === null) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $charStmt = $this->pdo->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
            $charStmt->execute([$campaignId, $characterId]);
            if (!$charStmt->fetch()) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $invStmt = $this->pdo->prepare('SELECT item_id, quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ?');
            $invStmt->execute([$campaignId, $characterId]);
            $inventory = [];
            foreach ($invStmt->fetchAll() as $row) {
                $inventory[$row['item_id']] = (int) $row['quantity'];
            }

            foreach ($recipe['ingredients'] as $itemId => $required) {
                if (($inventory[$itemId] ?? 0) < $required) {
                    $this->pdo->exec('ROLLBACK');

                    return ['error' => 'insufficient ingredients'];
                }
            }

            foreach ($recipe['ingredients'] as $itemId => $required) {
                $remaining = $inventory[$itemId] - $required;
                if ($remaining > 0) {
                    $upd = $this->pdo->prepare('UPDATE play_campaign_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
                    $upd->execute([$remaining, $campaignId, $characterId, $itemId]);
                } else {
                    $del = $this->pdo->prepare('DELETE FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
                    $del->execute([$campaignId, $characterId, $itemId]);
                }
            }

            $addStmt = $this->pdo->prepare('INSERT INTO play_campaign_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity');
            $addStmt->execute([$campaignId, $characterId, $recipe['output_item'], $recipe['output_quantity']]);

            $this->pdo->exec('COMMIT');

            return [
                'character_id' => $characterId,
                'recipe_id' => $recipeId,
                'output_item' => $recipe['output_item'],
                'output_quantity' => $recipe['output_quantity'],
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function createPlayCampaignLoot(string $campaignId, string $lootId, string $itemId, int $quantity): ?array
    {
        try {
            $stmt = $this->pdo->prepare("INSERT INTO play_campaign_loot (campaign_id, loot_id, item_id, quantity, status) VALUES (?, ?, ?, ?, 'open')");
            $stmt->execute([$campaignId, $lootId, $itemId, $quantity]);

            return [
                'loot_id' => $lootId,
                'item_id' => $itemId,
                'quantity' => $quantity,
                'status' => 'open',
            ];
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return null;
            }
            throw $e;
        }
    }

    public function getPlayCampaignLoot(string $campaignId, string $lootId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT loot_id, item_id, quantity, status, recipient_character_id FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?');
        $stmt->execute([$campaignId, $lootId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'loot_id' => $row['loot_id'],
            'item_id' => $row['item_id'],
            'quantity' => (int) $row['quantity'],
            'status' => $row['status'],
            'recipient_character_id' => $row['recipient_character_id'],
        ];
    }

    public function getPlayCampaignLootVotes(string $campaignId, string $lootId): array
    {
        $stmt = $this->pdo->prepare('SELECT voter, recipient_character_id FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? ORDER BY voter');
        $stmt->execute([$campaignId, $lootId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'voter' => $row['voter'],
                'recipient_character_id' => $row['recipient_character_id'],
            ];
        }

        return $result;
    }

    public function addPlayCampaignLootVote(string $campaignId, string $lootId, string $voter, string $recipientCharacterId): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $loot = $this->getPlayCampaignLoot($campaignId, $lootId);
            if ($loot === null || $loot['status'] !== 'open') {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)');
            $stmt->execute([$campaignId, $lootId, $voter, $recipientCharacterId]);

            $tallyStmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?');
            $tallyStmt->execute([$campaignId, $lootId, $recipientCharacterId]);
            $count = (int) ($tallyStmt->fetch()['count'] ?? 0);

            $this->pdo->exec('COMMIT');

            return ['votes_for_recipient' => $count];
        } catch (PDOException $e) {
            $this->pdo->exec('ROLLBACK');
            if ($e->getCode() === '23000') {
                return null;
            }
            throw $e;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function assignPlayCampaignLoot(string $campaignId, string $lootId): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $loot = $this->getPlayCampaignLoot($campaignId, $lootId);
            if ($loot === null || $loot['status'] !== 'open') {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $votes = $this->getPlayCampaignLootVotes($campaignId, $lootId);
            $tallies = [];
            foreach ($votes as $vote) {
                $recipient = $vote['recipient_character_id'];
                $tallies[$recipient] = ($tallies[$recipient] ?? 0) + 1;
            }
            if (count($tallies) === 0) {
                $this->pdo->exec('ROLLBACK');

                return ['error' => 'no votes'];
            }
            $max = max($tallies);
            $winners = array_filter($tallies, static fn (int $c): bool => $c === $max);
            if (count($winners) > 1) {
                $this->pdo->exec('ROLLBACK');

                return ['error' => 'vote tie'];
            }
            $winner = array_key_first($winners);

            $upd = $this->pdo->prepare("UPDATE play_campaign_loot SET status = 'assigned', recipient_character_id = ? WHERE campaign_id = ? AND loot_id = ? AND status = 'open'");
            $upd->execute([$winner, $campaignId, $lootId]);
            if ($upd->rowCount() === 0) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity');
            $ins->execute([$campaignId, $winner, $loot['item_id'], $loot['quantity']]);

            $this->pdo->exec('COMMIT');

            return [
                'loot_id' => $lootId,
                'recipient_character_id' => $winner,
                'item_id' => $loot['item_id'],
                'quantity' => $loot['quantity'],
                'votes' => $max,
                'status' => 'assigned',
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function createPlayCampaignNpc(string $campaignId, string $npcId, string $name, string $agenda, string $publicStatus): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $npcId, $name, $agenda, $publicStatus]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignNpc(string $campaignId, string $npcId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT npc_id, name, agenda, public_status FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?');
        $stmt->execute([$campaignId, $npcId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'npc_id' => $row['npc_id'],
            'name' => $row['name'],
            'agenda' => $row['agenda'],
            'public_status' => $row['public_status'],
        ];
    }

    public function updatePlayCampaignNpcAgenda(string $campaignId, string $npcId, string $agenda, string $publicStatus): bool
    {
        $stmt = $this->pdo->prepare('UPDATE play_campaign_npcs SET agenda = ?, public_status = ? WHERE campaign_id = ? AND npc_id = ?');
        $stmt->execute([$agenda, $publicStatus, $campaignId, $npcId]);

        return $stmt->rowCount() > 0;
    }

    public function createPlayCampaignFaction(string $campaignId, string $factionId, string $name): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)');
            $stmt->execute([$campaignId, $factionId, $name]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignFaction(string $campaignId, string $factionId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT faction_id, name FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?');
        $stmt->execute([$campaignId, $factionId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'faction_id' => $row['faction_id'],
            'name' => $row['name'],
        ];
    }

    public function addPlayCampaignReputationEntry(string $campaignId, string $factionId, string $characterId, int $delta, string $reason): array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT total_reputation FROM play_campaign_reputation_history WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY id DESC LIMIT 1');
            $stmt->execute([$campaignId, $factionId, $characterId]);
            $row = $stmt->fetch();
            $current = $row !== false ? (int) $row['total_reputation'] : 0;

            $newTotal = max(-100, min(100, $current + $delta));

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_reputation_history (campaign_id, faction_id, character_id, delta, total_reputation, reason) VALUES (?, ?, ?, ?, ?, ?)');
            $ins->execute([$campaignId, $factionId, $characterId, $delta, $newTotal, $reason]);
            $id = (int) $this->pdo->lastInsertId();

            $select = $this->pdo->prepare('SELECT faction_id, character_id, delta, total_reputation, reason FROM play_campaign_reputation_history WHERE id = ?');
            $select->execute([$id]);
            $row = $select->fetch();
            $this->pdo->exec('COMMIT');

            return [
                'faction_id' => $row['faction_id'],
                'character_id' => $row['character_id'],
                'delta' => (int) $row['delta'],
                'total_reputation' => (int) $row['total_reputation'],
                'reason' => $row['reason'],
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignReputationHistory(string $campaignId, string $factionId, ?string $characterId = null): array
    {
        if ($characterId !== null) {
            $stmt = $this->pdo->prepare('SELECT faction_id, character_id, delta, total_reputation, reason FROM play_campaign_reputation_history WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY id');
            $stmt->execute([$campaignId, $factionId, $characterId]);
        } else {
            $stmt = $this->pdo->prepare('SELECT faction_id, character_id, delta, total_reputation, reason FROM play_campaign_reputation_history WHERE campaign_id = ? AND faction_id = ? ORDER BY id');
            $stmt->execute([$campaignId, $factionId]);
        }

        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'faction_id' => $row['faction_id'],
                'character_id' => $row['character_id'],
                'reputation' => (int) $row['total_reputation'],
                'delta' => (int) $row['delta'],
                'reason' => $row['reason'],
            ];
        }

        return $result;
    }

    public function addPlayCampaignNpcDialogue(string $campaignId, string $npcId, string $dialogueId, string $speaker, string $text, string $visibility): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_npc_dialogue (campaign_id, npc_id, dialogue_id, speaker, text, visibility) VALUES (?, ?, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $npcId, $dialogueId, $speaker, $text, $visibility]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignNpcDialogue(string $campaignId, string $npcId, ?string $visibility = null): array
    {
        if ($visibility !== null) {
            $stmt = $this->pdo->prepare('SELECT dialogue_id, speaker, text, visibility FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ? AND visibility = ? ORDER BY id');
            $stmt->execute([$campaignId, $npcId, $visibility]);
        } else {
            $stmt = $this->pdo->prepare('SELECT dialogue_id, speaker, text, visibility FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ? ORDER BY id');
            $stmt->execute([$campaignId, $npcId]);
        }

        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'dialogue_id' => $row['dialogue_id'],
                'speaker' => $row['speaker'],
                'text' => $row['text'],
                'visibility' => $row['visibility'],
            ];
        }

        return $result;
    }

    public function playCampaignEntityExists(string $campaignId, string $entityId): bool
    {
        $stmt = $this->pdo->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $entityId]);
        if ($stmt->fetch() !== false) {
            return true;
        }

        $stmt = $this->pdo->prepare('SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $entityId]);

        return $stmt->fetch() !== false;
    }

    public function addPlayCampaignRelationship(string $campaignId, string $sourceId, string $targetId, string $kind, int $score): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_relationships (campaign_id, source_id, target_id, kind, score) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $sourceId, $targetId, $kind, $score]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignRelationship(string $campaignId, string $sourceId, string $targetId, string $kind): ?array
    {
        $stmt = $this->pdo->prepare('SELECT source_id, target_id, kind, score FROM play_campaign_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?');
        $stmt->execute([$campaignId, $sourceId, $targetId, $kind]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'source_id' => $row['source_id'],
            'target_id' => $row['target_id'],
            'kind' => $row['kind'],
            'score' => (int) $row['score'],
        ];
    }

    public function updatePlayCampaignRelationshipScore(string $campaignId, string $sourceId, string $targetId, string $kind, int $score): bool
    {
        $stmt = $this->pdo->prepare('UPDATE play_campaign_relationships SET score = ? WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?');
        $stmt->execute([$score, $campaignId, $sourceId, $targetId, $kind]);

        return $stmt->rowCount() > 0;
    }

    public function getPlayCampaignRelationships(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT source_id, target_id, kind, score FROM play_campaign_relationships WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'source_id' => $row['source_id'],
                'target_id' => $row['target_id'],
                'kind' => $row['kind'],
                'score' => (int) $row['score'],
            ];
        }

        return $result;
    }

    public function createPlayCampaignClue(string $campaignId, string $clueId, string $text, string $audience, ?string $characterId): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_clues (campaign_id, clue_id, text, audience, character_id) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $clueId, $text, $audience, $characterId]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignClues(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT clue_id, text, audience, character_id FROM play_campaign_clues WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $clue = [
                'clue_id' => $row['clue_id'],
                'text' => $row['text'],
                'audience' => $row['audience'],
            ];
            if ($row['character_id'] !== null) {
                $clue['character_id'] = $row['character_id'];
            }
            $result[] = $clue;
        }

        return $result;
    }

    public function createPlayCampaignQuest(string $campaignId, string $questId, string $title, array $dependsOn): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_quests (campaign_id, quest_id, title, depends_on_json, state) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $questId, $title, json_encode($dependsOn, JSON_THROW_ON_ERROR), 'locked']);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignQuest(string $campaignId, string $questId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT quest_id, title, depends_on_json, state, rewards_json, awarded FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $questId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        $rewards = json_decode($row['rewards_json'], true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($rewards)) {
            $rewards = [];
        }

        return [
            'quest_id' => $row['quest_id'],
            'title' => $row['title'],
            'depends_on' => json_decode($row['depends_on_json'], true, 512, JSON_THROW_ON_ERROR),
            'state' => $row['state'],
            'rewards' => $rewards,
            'awarded' => (int) $row['awarded'] === 1,
        ];
    }

    public function getPlayCampaignQuests(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT quest_id, title, depends_on_json, state, rewards_json FROM play_campaign_quests WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $quest = [
                'quest_id' => $row['quest_id'],
                'title' => $row['title'],
                'depends_on' => json_decode($row['depends_on_json'], true, 512, JSON_THROW_ON_ERROR),
                'state' => $row['state'],
            ];
            $rewards = json_decode($row['rewards_json'], true, 512, JSON_THROW_ON_ERROR);
            if (is_array($rewards) && !empty($rewards)) {
                $quest['rewards'] = $rewards;
            }
            $result[] = $quest;
        }

        return $result;
    }

    public function updatePlayCampaignQuestState(string $campaignId, string $questId, string $state): bool
    {
        $stmt = $this->pdo->prepare('UPDATE play_campaign_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?');
        $stmt->execute([$state, $campaignId, $questId]);

        return $stmt->rowCount() > 0;
    }

    public function setPlayCampaignQuestRewards(string $campaignId, string $questId, int $xp, array $items): ?array
    {
        $quest = $this->getPlayCampaignQuest($campaignId, $questId);
        if ($quest === null) {
            return null;
        }
        if ($quest['awarded'] || !in_array($quest['state'], ['locked', 'active'], true)) {
            return ['error' => 'conflict'];
        }

        $rewards = ['xp' => $xp, 'items' => $items];
        $stmt = $this->pdo->prepare('UPDATE play_campaign_quests SET rewards_json = ? WHERE campaign_id = ? AND quest_id = ?');
        $stmt->execute([json_encode($rewards, JSON_THROW_ON_ERROR), $campaignId, $questId]);

        return $this->getPlayCampaignQuest($campaignId, $questId);
    }

    public function awardPlayCampaignQuestRewards(string $campaignId, string $questId): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $quest = $this->getPlayCampaignQuest($campaignId, $questId);
            if ($quest === null) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }
            if ($quest['state'] !== 'completed' || $quest['awarded']) {
                $this->pdo->exec('ROLLBACK');

                return ['error' => 'conflict'];
            }

            $rewards = $quest['rewards'];
            if (!is_array($rewards) || !isset($rewards['xp']) || !is_int($rewards['xp']) || $rewards['xp'] < 0 || !isset($rewards['items']) || !is_array($rewards['items'])) {
                $this->pdo->exec('ROLLBACK');

                return ['error' => 'conflict'];
            }

            $xp = $rewards['xp'];
            $items = $rewards['items'];

            $members = $this->getPlayCampaignMembers($campaignId);
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_character_quest_rewards (campaign_id, quest_id, character_id, xp, items_json) VALUES (?, ?, ?, ?, ?)');
            foreach ($members as $member) {
                $stmt->execute([$campaignId, $questId, $member['character_id'], $xp, json_encode($items, JSON_THROW_ON_ERROR)]);
            }

            $upd = $this->pdo->prepare('UPDATE play_campaign_quests SET awarded = 1 WHERE campaign_id = ? AND quest_id = ?');
            $upd->execute([$campaignId, $questId]);

            $this->pdo->exec('COMMIT');

            return ['quest_id' => $questId, 'xp' => $xp, 'items' => $items];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignCharacterRewards(string $campaignId, string $characterId): ?array
    {
        $check = $this->pdo->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
        $check->execute([$campaignId, $characterId]);
        if ($check->fetch() === false) {
            return null;
        }

        $stmt = $this->pdo->prepare('SELECT xp, items_json FROM play_campaign_character_quest_rewards WHERE campaign_id = ? AND character_id = ?');
        $stmt->execute([$campaignId, $characterId]);
        $totalXp = 0;
        $items = [];
        foreach ($stmt->fetchAll() as $row) {
            $totalXp += (int) $row['xp'];
            $questItems = json_decode($row['items_json'], true, 512, JSON_THROW_ON_ERROR);
            if (is_array($questItems)) {
                foreach ($questItems as $itemId => $qty) {
                    $items[$itemId] = ($items[$itemId] ?? 0) + (int) $qty;
                }
            }
        }

        return [
            'character_id' => $characterId,
            'xp' => $totalXp,
            'items' => $items,
        ];
    }

    public function createPlayCampaignWorldEvent(string $campaignId, string $eventId, int $turnNumber, string $title, string $text): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_world_events (campaign_id, event_id, turn_number, title, text, status) VALUES (?, ?, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $eventId, $turnNumber, $title, $text, 'scheduled']);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignWorldEvent(string $campaignId, string $eventId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT event_id, turn_number, title, text, status, resolution_turn_number, resolution_text FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $eventId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return $this->hydrateWorldEvent($row);
    }

    public function getPlayCampaignWorldEvents(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT event_id, turn_number, title, text, status, resolution_turn_number, resolution_text FROM play_campaign_world_events WHERE campaign_id = ? ORDER BY turn_number ASC, id ASC');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = $this->hydrateWorldEvent($row);
        }

        return $result;
    }

    public function resolvePlayCampaignWorldEvent(string $campaignId, string $eventId, string $text, int $turnNumber): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $event = $this->getPlayCampaignWorldEvent($campaignId, $eventId);
            if ($event === null) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }
            if ($event['status'] === 'resolved') {
                $this->pdo->exec('ROLLBACK');

                return ['error' => 'already resolved'];
            }

            $stmt = $this->pdo->prepare('UPDATE play_campaign_world_events SET status = ?, resolution_text = ?, resolution_turn_number = ? WHERE campaign_id = ? AND event_id = ?');
            $stmt->execute(['resolved', $text, $turnNumber, $campaignId, $eventId]);

            $event = $this->getPlayCampaignWorldEvent($campaignId, $eventId);
            $this->pdo->exec('COMMIT');

            return $event;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    private function hydrateWorldEvent(array $row): array
    {
        $event = [
            'event_id' => $row['event_id'],
            'turn_number' => (int) $row['turn_number'],
            'title' => $row['title'],
            'text' => $row['text'],
            'status' => $row['status'],
        ];
        if ($row['status'] === 'resolved') {
            $event['resolution'] = [
                'turn_number' => (int) $row['resolution_turn_number'],
                'text' => $row['resolution_text'],
            ];
        }

        return $event;
    }

    public function createPlayCampaignCalendar(string $campaignId, int $day, string $season): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (?, ?, ?)');
            $stmt->execute([$campaignId, $day, $season]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignCalendar(string $campaignId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT campaign_id, day, season FROM play_campaign_calendars WHERE campaign_id = ? LIMIT 1');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'campaign_id' => $row['campaign_id'],
            'day' => (int) $row['day'],
            'season' => $row['season'],
        ];
    }

    public function advancePlayCampaignCalendar(string $campaignId, int $days): ?array
    {
        $calendar = $this->getPlayCampaignCalendar($campaignId);
        if ($calendar === null) {
            return null;
        }

        $newDay = $calendar['day'] + $days;
        $stmt = $this->pdo->prepare('UPDATE play_campaign_calendars SET day = ? WHERE campaign_id = ?');
        $stmt->execute([$newDay, $campaignId]);

        return [
            'campaign_id' => $campaignId,
            'day' => $newDay,
            'season' => $calendar['season'],
        ];
    }

    public function createPlayCampaignSettlement(string $campaignId, string $settlementId, string $name, array $services, string $availability): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_settlements (campaign_id, settlement_id, name, services_json, availability, discovered_by_json) VALUES (?, ?, ?, ?, ?, ?)');
            $stmt->execute([
                $campaignId,
                $settlementId,
                $name,
                json_encode($services, JSON_THROW_ON_ERROR),
                $availability,
                json_encode([], JSON_THROW_ON_ERROR),
            ]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignSettlement(string $campaignId, string $settlementId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT settlement_id, name, services_json, availability, discovered_by_json FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $settlementId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return $this->hydrateSettlement($row);
    }

    public function updatePlayCampaignSettlement(string $campaignId, string $settlementId, string $name, array $services, string $availability): bool
    {
        $stmt = $this->pdo->prepare('UPDATE play_campaign_settlements SET name = ?, services_json = ?, availability = ? WHERE campaign_id = ? AND settlement_id = ?');
        $stmt->execute([
            $name,
            json_encode($services, JSON_THROW_ON_ERROR),
            $availability,
            $campaignId,
            $settlementId,
        ]);

        return $stmt->rowCount() > 0;
    }

    /**
     * Record a settlement discovery by a character.
     *
     * Returns true if the character was newly appended, false if the character
     * had already discovered the settlement.
     */
    public function discoverPlayCampaignSettlement(string $campaignId, string $settlementId, string $characterId): bool
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $settlement = $this->getPlayCampaignSettlement($campaignId, $settlementId);
            if ($settlement === null) {
                $this->pdo->exec('ROLLBACK');
                throw new \RuntimeException('settlement not found');
            }

            $discoveredBy = $settlement['discovered_by'];
            if (in_array($characterId, $discoveredBy, true)) {
                $this->pdo->exec('ROLLBACK');

                return false;
            }

            $discoveredBy[] = $characterId;
            $stmt = $this->pdo->prepare('UPDATE play_campaign_settlements SET discovered_by_json = ? WHERE campaign_id = ? AND settlement_id = ?');
            $stmt->execute([json_encode($discoveredBy, JSON_THROW_ON_ERROR), $campaignId, $settlementId]);

            $this->pdo->exec('COMMIT');

            return true;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignSettlements(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT settlement_id, name, services_json, availability, discovered_by_json FROM play_campaign_settlements WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = $this->hydrateSettlement($row);
        }

        return $result;
    }

    private function hydrateSettlement(array $row): array
    {
        $services = json_decode($row['services_json'], true, 512, JSON_THROW_ON_ERROR);
        $discoveredBy = json_decode($row['discovered_by_json'], true, 512, JSON_THROW_ON_ERROR);

        return [
            'settlement_id' => $row['settlement_id'],
            'name' => $row['name'],
            'services' => is_array($services) ? $services : [],
            'availability' => $row['availability'],
            'discovered_by' => is_array($discoveredBy) ? $discoveredBy : [],
        ];
    }

    public function createPlayCampaignShop(string $campaignId, string $settlementId, string $shopId, string $name, array $stock, int $buyPrice, int $sellPrice): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_shops (campaign_id, settlement_id, shop_id, name, stock_json, buy_price, sell_price) VALUES (?, ?, ?, ?, ?, ?, ?)');
            $stmt->execute([
                $campaignId,
                $settlementId,
                $shopId,
                $name,
                json_encode($stock, JSON_THROW_ON_ERROR),
                $buyPrice,
                $sellPrice,
            ]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignShop(string $campaignId, string $settlementId, string $shopId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT shop_id, name, stock_json, buy_price, sell_price FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $settlementId, $shopId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return $this->hydrateShop($row);
    }

    private function hydrateShop(array $row): array
    {
        $stock = json_decode($row['stock_json'], true, 512, JSON_THROW_ON_ERROR);

        return [
            'shop_id' => $row['shop_id'],
            'name' => $row['name'],
            'stock' => is_array($stock) ? $stock : [],
            'buy_price' => (int) $row['buy_price'],
            'sell_price' => (int) $row['sell_price'],
        ];
    }

    /**
     * Buy an item from a shop.
     *
     * Returns an array with the remaining character gold and shop stock for the
     * item, or null if the shop/character does not exist. Throws on insufficient
     * stock or gold so the caller can return 409.
     *
     * @return array{gold: int, stock: int}
     * @throws \RuntimeException
     */
    public function buyFromShop(string $campaignId, string $settlementId, string $shopId, string $characterId, string $itemId, int $quantity): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $shop = $this->getPlayCampaignShop($campaignId, $settlementId, $shopId);
            if ($shop === null) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $stock = $shop['stock'];
            if (!isset($stock[$itemId]) || !is_int($stock[$itemId]) || $stock[$itemId] < $quantity) {
                $this->pdo->exec('ROLLBACK');
                throw new \RuntimeException('insufficient stock');
            }

            $charStmt = $this->pdo->prepare('SELECT username, gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
            $charStmt->execute([$campaignId, $characterId]);
            $charRow = $charStmt->fetch();
            if (!$charRow) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $totalCost = $shop['buy_price'] * $quantity;
            $gold = (int) ($charRow['gold'] ?? 10);
            if ($gold < $totalCost) {
                $this->pdo->exec('ROLLBACK');
                throw new \RuntimeException('insufficient gold');
            }

            $newGold = $gold - $totalCost;
            $newStock = $stock[$itemId] - $quantity;
            $stock[$itemId] = $newStock;

            $updShop = $this->pdo->prepare('UPDATE play_campaign_shops SET stock_json = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?');
            $updShop->execute([json_encode($stock, JSON_THROW_ON_ERROR), $campaignId, $settlementId, $shopId]);

            $updGold = $this->pdo->prepare('UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?');
            $updGold->execute([$newGold, $campaignId, $characterId]);

            $invStmt = $this->pdo->prepare('INSERT INTO play_campaign_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity');
            $invStmt->execute([$campaignId, $characterId, $itemId, $quantity]);

            $this->pdo->exec('COMMIT');

            return [
                'gold' => $newGold,
                'stock' => $newStock,
            ];
        } catch (\RuntimeException $e) {
            throw $e;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    /**
     * Sell an item to a shop.
     *
     * Returns an array with the remaining character gold and shop stock for the
     * item, or null if the shop/character does not exist. Throws on insufficient
     * inventory so the caller can return 409.
     *
     * @return array{gold: int, stock: int}
     * @throws \RuntimeException
     */
    public function sellToShop(string $campaignId, string $settlementId, string $shopId, string $characterId, string $itemId, int $quantity): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $shop = $this->getPlayCampaignShop($campaignId, $settlementId, $shopId);
            if ($shop === null) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $charStmt = $this->pdo->prepare('SELECT username, gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
            $charStmt->execute([$campaignId, $characterId]);
            $charRow = $charStmt->fetch();
            if (!$charRow) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $invStmt = $this->pdo->prepare('SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ? LIMIT 1');
            $invStmt->execute([$campaignId, $characterId, $itemId]);
            $invRow = $invStmt->fetch();
            if (!$invRow) {
                $this->pdo->exec('ROLLBACK');
                throw new \RuntimeException('insufficient inventory');
            }

            $currentQuantity = (int) $invRow['quantity'];
            if ($currentQuantity < $quantity) {
                $this->pdo->exec('ROLLBACK');
                throw new \RuntimeException('insufficient inventory');
            }

            $stock = $shop['stock'];
            $currentStock = isset($stock[$itemId]) && is_int($stock[$itemId]) ? $stock[$itemId] : 0;
            $newStock = $currentStock + $quantity;
            $stock[$itemId] = $newStock;

            // Sold items remain in character inventory for cumulative recipe use.
            $newGold = (int) ($charRow['gold'] ?? 10) + $shop['sell_price'] * $quantity;

            $updGold = $this->pdo->prepare('UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?');
            $updGold->execute([$newGold, $campaignId, $characterId]);

            $updShop = $this->pdo->prepare('UPDATE play_campaign_shops SET stock_json = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?');
            $updShop->execute([json_encode($stock, JSON_THROW_ON_ERROR), $campaignId, $settlementId, $shopId]);

            $this->pdo->exec('COMMIT');

            return [
                'gold' => $newGold,
                'stock' => $newStock,
            ];
        } catch (\RuntimeException $e) {
            throw $e;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function createPlayCampaignDowntimeActivity(string $campaignId, string $activityId, string $name, int $cyclesRequired): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_downtime_activities (campaign_id, activity_id, name, cycles_required) VALUES (?, ?, ?, ?)');
            $stmt->execute([$campaignId, $activityId, $name, $cyclesRequired]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignDowntimeActivity(string $campaignId, string $activityId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT activity_id, name, cycles_required FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $activityId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'activity_id' => $row['activity_id'],
            'name' => $row['name'],
            'cycles_required' => (int) $row['cycles_required'],
        ];
    }

    public function createPlayCampaignDowntimeAllocation(string $campaignId, string $characterId, string $activityId): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (?, ?, ?, 0, 0)');
            $stmt->execute([$campaignId, $characterId, $activityId]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignDowntimeAllocation(string $campaignId, string $characterId, string $activityId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT character_id, activity_id, cycles_completed, completions FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $characterId, $activityId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'character_id' => $row['character_id'],
            'activity_id' => $row['activity_id'],
            'cycles_completed' => (int) $row['cycles_completed'],
            'completions' => (int) $row['completions'],
        ];
    }

    public function progressPlayCampaignDowntimeAllocation(string $campaignId, string $characterId, string $activityId): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT cycles_completed, completions FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ? LIMIT 1');
            $stmt->execute([$campaignId, $characterId, $activityId]);
            $row = $stmt->fetch();
            if (!$row) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $activityStmt = $this->pdo->prepare('SELECT cycles_required FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ? LIMIT 1');
            $activityStmt->execute([$campaignId, $activityId]);
            $activityRow = $activityStmt->fetch();
            if (!$activityRow) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }
            $cyclesRequired = (int) $activityRow['cycles_required'];

            $cyclesCompleted = (int) $row['cycles_completed'] + 1;
            $completions = (int) $row['completions'];
            if ($cyclesCompleted >= $cyclesRequired) {
                $cyclesCompleted = 0;
                $completions++;
            }

            $upd = $this->pdo->prepare('UPDATE play_campaign_downtime_allocations SET cycles_completed = ?, completions = ? WHERE campaign_id = ? AND character_id = ? AND activity_id = ?');
            $upd->execute([$cyclesCompleted, $completions, $campaignId, $characterId, $activityId]);

            $this->pdo->exec('COMMIT');

            return [
                'character_id' => $characterId,
                'activity_id' => $activityId,
                'cycles_completed' => $cyclesCompleted,
                'completions' => $completions,
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function setPlayCampaignSessionZero(string $campaignId, array $settings): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_session_zero (campaign_id, rules, tone, consent_json) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET rules = excluded.rules, tone = excluded.tone, consent_json = excluded.consent_json');
            $stmt->execute([
                $campaignId,
                $settings['rules'],
                $settings['tone'],
                json_encode($settings['consent'], JSON_THROW_ON_ERROR),
            ]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignSessionZero(string $campaignId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT rules, tone, consent_json FROM play_campaign_session_zero WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'rules' => $row['rules'],
            'tone' => $row['tone'],
            'consent' => json_decode($row['consent_json'], true, 512, JSON_THROW_ON_ERROR),
        ];
    }

    public function createPlayCampaignContent(string $campaignId, string $contentId, string $kind, string $text, array $tags): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_content (campaign_id, content_id, kind, text, tags_json) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $contentId, $kind, $text, json_encode($tags, JSON_THROW_ON_ERROR)]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignContent(string $campaignId, string $contentId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT content_id, kind, text, tags_json FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?');
        $stmt->execute([$campaignId, $contentId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'content_id' => $row['content_id'],
            'kind' => $row['kind'],
            'text' => $row['text'],
            'tags' => json_decode($row['tags_json'], true, 512, JSON_THROW_ON_ERROR),
        ];
    }

    public function updatePlayCampaignContentTags(string $campaignId, string $contentId, array $tags): bool
    {
        $stmt = $this->pdo->prepare('UPDATE play_campaign_content SET tags_json = ? WHERE campaign_id = ? AND content_id = ?');
        $stmt->execute([json_encode($tags, JSON_THROW_ON_ERROR), $campaignId, $contentId]);

        return $stmt->rowCount() > 0;
    }

    public function getPlayCampaignContentList(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT content_id, kind, text, tags_json FROM play_campaign_content WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'content_id' => $row['content_id'],
                'kind' => $row['kind'],
                'text' => $row['text'],
                'tags' => json_decode($row['tags_json'], true, 512, JSON_THROW_ON_ERROR),
            ];
        }

        return $result;
    }

    public function createPlayCampaignNote(string $campaignId, string $noteId, string $text, string $visibility, string $owner): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_notes (campaign_id, note_id, text, visibility, owner) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $noteId, $text, $visibility, $owner]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignNote(string $campaignId, string $noteId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?');
        $stmt->execute([$campaignId, $noteId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'note_id' => $row['note_id'],
            'text' => $row['text'],
            'visibility' => $row['visibility'],
            'owner' => $row['owner'],
        ];
    }

    public function getPlayCampaignNotes(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'note_id' => $row['note_id'],
                'text' => $row['text'],
                'visibility' => $row['visibility'],
                'owner' => $row['owner'],
            ];
        }

        return $result;
    }

    public function updatePlayCampaignNote(string $campaignId, string $noteId, string $text, string $visibility): bool
    {
        $stmt = $this->pdo->prepare('UPDATE play_campaign_notes SET text = ?, visibility = ? WHERE campaign_id = ? AND note_id = ?');
        $stmt->execute([$text, $visibility, $campaignId, $noteId]);

        return $stmt->rowCount() > 0;
    }

    public function createPlayCampaignWhisper(string $campaignId, string $whisperId, string $fromCharacterId, string $toCharacterId, string $text): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $whisperId, $fromCharacterId, $toCharacterId, $text]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignWhispers(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'whisper_id' => $row['whisper_id'],
                'from_character_id' => $row['from_character_id'],
                'to_character_id' => $row['to_character_id'],
                'text' => $row['text'],
            ];
        }

        return $result;
    }

    public function createPlayCampaignMessage(string $campaignId, string $messageId, string $sender, string $text): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_messages (campaign_id, message_id, sender, text) VALUES (?, ?, ?, ?)');
            $stmt->execute([$campaignId, $messageId, $sender, $text]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignMessages(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT message_id, sender, text FROM play_campaign_messages WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'message_id' => $row['message_id'],
                'sender' => $row['sender'],
                'text' => $row['text'],
            ];
        }

        return $result;
    }

    public function createPlayCampaignInvitation(string $campaignId, string $invitationId, string $username, string $characterId): bool
    {
        try {
            $stmt = $this->pdo->prepare('SELECT 1 FROM play_campaign_invitations WHERE campaign_id = ? AND username = ? AND status = ? LIMIT 1');
            $stmt->execute([$campaignId, $username, 'pending']);
            if ($stmt->fetch() !== false) {
                return false;
            }

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_invitations (campaign_id, invitation_id, username, character_id, status) VALUES (?, ?, ?, ?, ?)');
            $ins->execute([$campaignId, $invitationId, $username, $characterId, 'pending']);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignInvitation(string $campaignId, string $invitationId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $invitationId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'invitation_id' => $row['invitation_id'],
            'username' => $row['username'],
            'character_id' => $row['character_id'],
            'status' => $row['status'],
        ];
    }

    public function getPlayCampaignInvitations(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'invitation_id' => $row['invitation_id'],
                'username' => $row['username'],
                'character_id' => $row['character_id'],
                'status' => $row['status'],
            ];
        }

        return $result;
    }

    public function acceptPlayCampaignInvitation(string $campaignId, string $invitationId, string $username): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ? LIMIT 1');
            $stmt->execute([$campaignId, $invitationId]);
            $row = $stmt->fetch();
            if (!$row) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }
            if ($row['username'] !== $username) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }
            if ($row['status'] !== 'pending') {
                $this->pdo->exec('ROLLBACK');

                return ['error' => 'already accepted'];
            }

            $upd = $this->pdo->prepare("UPDATE play_campaign_invitations SET status = 'accepted' WHERE campaign_id = ? AND invitation_id = ?");
            $upd->execute([$campaignId, $invitationId]);

            $characterId = $row['character_id'];
            $name = $username;
            $class = 'fighter';
            $slots = \App\Domain\SpellRules::spellSlots($class, 1);
            $ins = $this->pdo->prepare('INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, level, hp_max, hp_current, owner, spell_slots_json, gold) VALUES (?, ?, ?, ?, ?, ?, 20, 20, ?, ?, 10)');
            $ins->execute([$campaignId, $username, $characterId, $name, $class, 1, $username, json_encode($slots, JSON_THROW_ON_ERROR)]);

            $this->pdo->exec('COMMIT');

            return [
                'invitation_id' => $invitationId,
                'username' => $username,
                'character_id' => $characterId,
                'status' => 'accepted',
            ];
        } catch (PDOException $e) {
            $this->pdo->exec('ROLLBACK');
            if ($e->getCode() === '23000') {
                return null;
            }
            throw $e;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignCharacterSheet(string $campaignId, string $characterId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT character_id, name, class, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $characterId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        // The basic sheet is intentionally deterministic and independent of
        // any later character-progression state.
        return [
            'character_id' => $row['character_id'],
            'owner' => $row['owner'],
            'name' => $row['name'],
            'class' => $row['class'],
            'level' => 1,
            'proficiency_bonus' => 2,
            'hp_max' => 10,
            'armor_class' => 10,
        ];
    }

    public function getPlayCampaignDelegation(string $campaignId, string $username): ?array
    {
        $stmt = $this->pdo->prepare('SELECT username, powers_json, active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ? LIMIT 1');
        $stmt->execute([$campaignId, $username]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'username' => $row['username'],
            'powers' => json_decode($row['powers_json'], true, 512, JSON_THROW_ON_ERROR),
            'active' => (bool) $row['active'],
        ];
    }

    public function grantPlayCampaignDelegation(string $campaignId, string $username, array $powers): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ? LIMIT 1');
            $stmt->execute([$campaignId, $username]);
            $row = $stmt->fetch();
            if ($row && (int) $row['active'] === 1) {
                $this->pdo->exec('ROLLBACK');

                return ['error' => 'already active'];
            }

            $powersJson = json_encode(array_values($powers), JSON_THROW_ON_ERROR);
            if ($row) {
                $upd = $this->pdo->prepare('UPDATE play_campaign_delegations SET powers_json = ?, active = 1 WHERE campaign_id = ? AND username = ?');
                $upd->execute([$powersJson, $campaignId, $username]);
            } else {
                $ins = $this->pdo->prepare('INSERT INTO play_campaign_delegations (campaign_id, username, powers_json, active) VALUES (?, ?, ?, 1)');
                $ins->execute([$campaignId, $username, $powersJson]);
            }

            $this->addPlayCampaignDelegationAuditEntry($campaignId, $username, 'granted', $powers);
            $this->pdo->exec('COMMIT');

            return [
                'username' => $username,
                'powers' => $powers,
                'active' => true,
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function revokePlayCampaignDelegation(string $campaignId, string $username): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT powers_json, active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ? LIMIT 1');
            $stmt->execute([$campaignId, $username]);
            $row = $stmt->fetch();
            if (!$row) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $powers = json_decode($row['powers_json'], true, 512, JSON_THROW_ON_ERROR);
            $upd = $this->pdo->prepare('UPDATE play_campaign_delegations SET active = 0 WHERE campaign_id = ? AND username = ?');
            $upd->execute([$campaignId, $username]);

            $this->addPlayCampaignDelegationAuditEntry($campaignId, $username, 'revoked', $powers);
            $this->pdo->exec('COMMIT');

            return [
                'username' => $username,
                'powers' => $powers,
                'active' => false,
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function hasPlayCampaignDelegationPower(string $campaignId, string $username, string $power): bool
    {
        $stmt = $this->pdo->prepare('SELECT powers_json FROM play_campaign_delegations WHERE campaign_id = ? AND username = ? AND active = 1 LIMIT 1');
        $stmt->execute([$campaignId, $username]);
        $row = $stmt->fetch();
        if (!$row) {
            return false;
        }
        $powers = json_decode($row['powers_json'], true, 512, JSON_THROW_ON_ERROR);

        return in_array($power, $powers, true);
    }

    public function getPlayCampaignDelegationAudit(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT username, action, powers_json FROM play_campaign_delegation_audit WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'username' => $row['username'],
                'action' => $row['action'],
                'powers' => json_decode($row['powers_json'], true, 512, JSON_THROW_ON_ERROR),
            ];
        }

        return $result;
    }

    private function addPlayCampaignDelegationAuditEntry(string $campaignId, string $username, string $action, array $powers): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO play_campaign_delegation_audit (campaign_id, username, action, powers_json) VALUES (?, ?, ?, ?)');
        $stmt->execute([$campaignId, $username, $action, json_encode($powers, JSON_THROW_ON_ERROR)]);
    }

    public function createPlayCampaignAuditEvent(string $campaignId, string $actor, string $role, string $kind, string $correlationId): array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT COALESCE(MAX(timestamp), 0) + 1 FROM play_campaign_audit_events WHERE campaign_id = ?');
            $stmt->execute([$campaignId]);
            $timestamp = (int) $stmt->fetchColumn();

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_audit_events (campaign_id, kind, actor, role, timestamp, correlation_id) VALUES (?, ?, ?, ?, ?, ?)');
            $ins->execute([$campaignId, $kind, $actor, $role, $timestamp, $correlationId]);
            $id = (int) $this->pdo->lastInsertId();

            $select = $this->pdo->prepare('SELECT kind, actor, role, timestamp, correlation_id FROM play_campaign_audit_events WHERE id = ?');
            $select->execute([$id]);
            $row = $select->fetch();
            $this->pdo->exec('COMMIT');

            return [
                'kind' => $row['kind'],
                'actor' => $row['actor'],
                'role' => $row['role'],
                'timestamp' => (int) $row['timestamp'],
                'correlation_id' => $row['correlation_id'],
            ];
        } catch (PDOException $e) {
            $this->pdo->exec('ROLLBACK');
            if ($e->getCode() === '23000') {
                return ['error' => 'duplicate correlation_id'];
            }
            throw $e;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignAuditEvents(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT kind, actor, role, timestamp, correlation_id FROM play_campaign_audit_events WHERE campaign_id = ? ORDER BY timestamp ASC, id ASC');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'kind' => $row['kind'],
                'actor' => $row['actor'],
                'role' => $row['role'],
                'timestamp' => (int) $row['timestamp'],
                'correlation_id' => $row['correlation_id'],
            ];
        }

        return $result;
    }

    public function createPlayCampaignProjectionEvent(string $campaignId, string $eventId, string $kind, ?string $value): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_projection_events WHERE campaign_id = ?');
            $stmt->execute([$campaignId]);
            $sequence = (int) $stmt->fetchColumn();

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_projection_events (campaign_id, sequence, event_id, kind, value) VALUES (?, ?, ?, ?, ?)');
            $ins->execute([$campaignId, $sequence, $eventId, $kind, $value]);
            $id = (int) $this->pdo->lastInsertId();

            $select = $this->pdo->prepare('SELECT sequence, event_id, kind, value FROM play_campaign_projection_events WHERE id = ?');
            $select->execute([$id]);
            $row = $select->fetch();
            $this->incrementPlayCampaignMetric($campaignId, 'projection_events');
            $this->pdo->exec('COMMIT');

            return [
                'sequence' => (int) $row['sequence'],
                'event_id' => $row['event_id'],
                'kind' => $row['kind'],
                'value' => $row['value'],
            ];
        } catch (PDOException $e) {
            $this->pdo->exec('ROLLBACK');
            if ($e->getCode() === '23000') {
                return null;
            }
            throw $e;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignProjectionEvents(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT sequence, event_id, kind, value FROM play_campaign_projection_events WHERE campaign_id = ? ORDER BY sequence ASC, id ASC');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'sequence' => (int) $row['sequence'],
                'event_id' => $row['event_id'],
                'kind' => $row['kind'],
                'value' => $row['value'],
            ];
        }

        return $result;
    }

    public function buildPlayCampaignProjection(string $campaignId): array
    {
        $events = $this->getPlayCampaignProjectionEvents($campaignId);
        $story = '';
        $danger = 0;
        $appliedEventIds = [];
        foreach ($events as $event) {
            $appliedEventIds[] = $event['event_id'];
            if ($event['kind'] === 'set-story') {
                $story = (string) ($event['value'] ?? '');
            } elseif ($event['kind'] === 'increment-danger') {
                $danger++;
            }
        }

        return [
            'story' => $story,
            'danger' => $danger,
            'applied_event_ids' => $appliedEventIds,
        ];
    }

    public function createPlayCampaignIdempotentEvent(string $campaignId, string $eventId, string $value, string $idempotencyKey): array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT sequence, event_id, value, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = ? AND idempotency_key = ?');
            $stmt->execute([$campaignId, $idempotencyKey]);
            $existing = $stmt->fetch();
            if ($existing !== false) {
                $this->pdo->exec('COMMIT');
                if ($existing['event_id'] === $eventId && $existing['value'] === $value) {
                    return [
                        'status' => 'matched',
                        'event' => [
                            'event_id' => $existing['event_id'],
                            'value' => $existing['value'],
                            'sequence' => (int) $existing['sequence'],
                            'idempotency_key' => $existing['idempotency_key'],
                        ],
                    ];
                }

                return ['status' => 'conflict', 'reason' => 'idempotency_key'];
            }

            $stmt = $this->pdo->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_idempotent_events WHERE campaign_id = ?');
            $stmt->execute([$campaignId]);
            $sequence = (int) $stmt->fetchColumn();

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_idempotent_events (campaign_id, sequence, event_id, value, idempotency_key) VALUES (?, ?, ?, ?, ?)');
            $ins->execute([$campaignId, $sequence, $eventId, $value, $idempotencyKey]);
            $id = (int) $this->pdo->lastInsertId();

            $select = $this->pdo->prepare('SELECT sequence, event_id, value, idempotency_key FROM play_campaign_idempotent_events WHERE id = ?');
            $select->execute([$id]);
            $row = $select->fetch();
            $this->pdo->exec('COMMIT');

            return [
                'status' => 'created',
                'event' => [
                    'event_id' => $row['event_id'],
                    'value' => $row['value'],
                    'sequence' => (int) $row['sequence'],
                    'idempotency_key' => $row['idempotency_key'],
                ],
            ];
        } catch (PDOException $e) {
            $this->pdo->exec('ROLLBACK');
            if ($e->getCode() === '23000') {
                return ['status' => 'conflict', 'reason' => 'event_id'];
            }
            throw $e;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignIdempotentEvents(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT sequence, event_id, value, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = ? ORDER BY sequence ASC, id ASC');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'event_id' => $row['event_id'],
                'value' => $row['value'],
                'sequence' => (int) $row['sequence'],
                'idempotency_key' => $row['idempotency_key'],
            ];
        }

        return $result;
    }

    public function getPlayCampaignSafeTurnState(string $campaignId): array
    {
        $this->pdo->prepare('INSERT OR IGNORE INTO play_campaign_safe_turns (campaign_id, current_turn) VALUES (?, 1)')->execute([$campaignId]);

        $stmt = $this->pdo->prepare('SELECT current_turn FROM play_campaign_safe_turns WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        $currentTurn = $row !== false ? (int) $row['current_turn'] : 1;

        $stmt = $this->pdo->prepare('SELECT submission_id, action, accepted_turn, next_turn FROM play_campaign_safe_turn_submissions WHERE campaign_id = ? ORDER BY id ASC');
        $stmt->execute([$campaignId]);
        $accepted = [];
        foreach ($stmt->fetchAll() as $row) {
            $accepted[] = [
                'submission_id' => $row['submission_id'],
                'action' => $row['action'],
                'accepted_turn' => (int) $row['accepted_turn'],
                'next_turn' => (int) $row['next_turn'],
            ];
        }

        return [
            'current_turn' => $currentTurn,
            'accepted' => $accepted,
        ];
    }

    public function submitPlayCampaignSafeTurn(string $campaignId, string $submissionId, string $action, int $expectedTurn): array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $this->pdo->prepare('INSERT OR IGNORE INTO play_campaign_safe_turns (campaign_id, current_turn) VALUES (?, 1)')->execute([$campaignId]);

            $stmt = $this->pdo->prepare('SELECT current_turn FROM play_campaign_safe_turns WHERE campaign_id = ?');
            $stmt->execute([$campaignId]);
            $row = $stmt->fetch();
            $currentTurn = $row !== false ? (int) $row['current_turn'] : 1;

            $stmt = $this->pdo->prepare('SELECT 1 FROM play_campaign_safe_turn_submissions WHERE campaign_id = ? AND submission_id = ?');
            $stmt->execute([$campaignId, $submissionId]);
            if ($stmt->fetch() !== false) {
                $this->pdo->exec('ROLLBACK');

                return ['status' => 'duplicate', 'current_turn' => $currentTurn];
            }

            if ($expectedTurn !== $currentTurn) {
                $this->pdo->exec('ROLLBACK');

                return ['status' => 'stale', 'current_turn' => $currentTurn];
            }

            $nextTurn = $currentTurn + 1;

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_safe_turn_submissions (campaign_id, submission_id, action, accepted_turn, next_turn) VALUES (?, ?, ?, ?, ?)');
            $ins->execute([$campaignId, $submissionId, $action, $currentTurn, $nextTurn]);

            $upd = $this->pdo->prepare('UPDATE play_campaign_safe_turns SET current_turn = ? WHERE campaign_id = ?');
            $upd->execute([$nextTurn, $campaignId]);

            $this->pdo->exec('COMMIT');

            return [
                'status' => 'accepted',
                'submission_id' => $submissionId,
                'action' => $action,
                'accepted_turn' => $currentTurn,
                'next_turn' => $nextTurn,
            ];
        } catch (PDOException $e) {
            $this->pdo->exec('ROLLBACK');
            if ($e->getCode() === '23000') {
                $state = $this->getPlayCampaignSafeTurnState($campaignId);

                return ['status' => 'duplicate', 'current_turn' => $state['current_turn']];
            }
            throw $e;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function createPlayCampaignSearchRecord(string $campaignId, string $recordId, string $text): bool
    {
        $check = $this->pdo->prepare('SELECT 1 FROM play_campaign_search_records WHERE campaign_id = ? AND (record_id = ? OR text = ?)');
        $check->execute([$campaignId, $recordId, $text]);
        if ($check->fetch() !== false) {
            return false;
        }

        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_search_records (campaign_id, record_id, text) VALUES (?, ?, ?)');
            $stmt->execute([$campaignId, $recordId, $text]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function listPlayCampaignSearchRecords(string $campaignId, ?string $query, int $cursor, int $limit): array
    {
        $stmt = $this->pdo->prepare('SELECT record_id, text FROM play_campaign_search_records WHERE campaign_id = ? ORDER BY id ASC');
        $stmt->execute([$campaignId]);
        $records = [];
        foreach ($stmt->fetchAll() as $row) {
            if ($query !== null && $query !== '') {
                if (stripos($row['text'], $query) === false) {
                    continue;
                }
            }
            $records[] = [
                'record_id' => $row['record_id'],
                'text' => $row['text'],
            ];
        }

        $total = count($records);
        $sliced = array_slice($records, $cursor, $limit);
        $nextCursor = null;
        if ($total > $cursor + count($sliced)) {
            $nextCursor = $cursor + count($sliced);
        }

        return [
            'records' => $sliced,
            'next_cursor' => $nextCursor,
        ];
    }

    public function createPlayCampaignRateEvent(string $campaignId, string $eventId, string $actor): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $check = $this->pdo->prepare('SELECT 1 FROM play_campaign_rate_events WHERE campaign_id = ? AND event_id = ? LIMIT 1');
            $check->execute([$campaignId, $eventId]);
            if ($check->fetch() !== false) {
                $this->pdo->exec('ROLLBACK');

                return null;
            }

            $countStmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?');
            $countStmt->execute([$campaignId, $actor]);
            $accepted = (int) ($countStmt->fetch()['count'] ?? 0);
            if ($accepted >= 2) {
                $this->incrementPlayCampaignMetric($campaignId, 'rejected_rate_events');
                $this->pdo->exec('COMMIT');

                return ['error' => 'rate limited', 'limit' => 2, 'remaining' => 0];
            }

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_rate_events (campaign_id, event_id, actor) VALUES (?, ?, ?)');
            $ins->execute([$campaignId, $eventId, $actor]);

            $remaining = 2 - ($accepted + 1);
            $this->incrementPlayCampaignMetric($campaignId, 'accepted_rate_events');
            $this->pdo->exec('COMMIT');

            return [
                'event_id' => $eventId,
                'actor' => $actor,
                'remaining' => $remaining,
            ];
        } catch (PDOException $e) {
            $this->pdo->exec('ROLLBACK');
            if ($e->getCode() === '23000') {
                return null;
            }
            throw $e;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function listPlayCampaignRateEvents(string $campaignId, string $actor): array
    {
        $stmt = $this->pdo->prepare('SELECT event_id, actor FROM play_campaign_rate_events WHERE campaign_id = ? ORDER BY id ASC');
        $stmt->execute([$campaignId]);
        $events = [];
        foreach ($stmt->fetchAll() as $row) {
            $events[] = [
                'event_id' => $row['event_id'],
                'actor' => $row['actor'],
            ];
        }

        $countStmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?');
        $countStmt->execute([$campaignId, $actor]);
        $accepted = (int) ($countStmt->fetch()['count'] ?? 0);

        return [
            'events' => $events,
            'remaining' => max(0, 2 - $accepted),
        ];
    }

    public function getPlayCampaignMetrics(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT accepted_rate_events, rejected_rate_events, projection_events, uptime_ticks FROM play_campaign_metrics WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return [
                'accepted_rate_events' => 0,
                'rejected_rate_events' => 0,
                'projection_events' => 0,
                'uptime_ticks' => 1,
            ];
        }

        return [
            'accepted_rate_events' => (int) $row['accepted_rate_events'],
            'rejected_rate_events' => (int) $row['rejected_rate_events'],
            'projection_events' => (int) $row['projection_events'],
            'uptime_ticks' => (int) $row['uptime_ticks'],
        ];
    }

    public function incrementPlayCampaignMetric(string $campaignId, string $counter): void
    {
        $allowed = ['accepted_rate_events', 'rejected_rate_events', 'projection_events'];
        if (!in_array($counter, $allowed, true)) {
            throw new \InvalidArgumentException('unknown metric');
        }

        $this->pdo->prepare('INSERT OR IGNORE INTO play_campaign_metrics (campaign_id) VALUES (?)')->execute([$campaignId]);
        $stmt = $this->pdo->prepare("UPDATE play_campaign_metrics SET {$counter} = {$counter} + 1 WHERE campaign_id = ?");
        $stmt->execute([$campaignId]);
    }

    public function createPlayCampaignBackup(string $campaignId): ?array
    {
        $campaign = $this->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return null;
        }

        $document = $this->getPlayCampaignDocument($campaignId);

        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_backups WHERE campaign_id = ?');
            $stmt->execute([$campaignId]);
            $sequence = (int) $stmt->fetchColumn();
            $backupId = 'backup-' . $sequence;

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_backups (campaign_id, sequence, backup_id, story, status) VALUES (?, ?, ?, ?, ?)');
            $ins->execute([$campaignId, $sequence, $backupId, $document['story'], $campaign['status']]);

            $this->pdo->exec('COMMIT');

            return [
                'backup_id' => $backupId,
                'story' => $document['story'],
                'status' => $campaign['status'],
            ];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignBackups(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = ? ORDER BY sequence ASC');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'backup_id' => $row['backup_id'],
                'story' => $row['story'],
                'status' => $row['status'],
            ];
        }

        return $result;
    }

    public function getPlayCampaignBackup(string $campaignId, string $backupId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = ? AND backup_id = ?');
        $stmt->execute([$campaignId, $backupId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'backup_id' => $row['backup_id'],
            'story' => $row['story'],
            'status' => $row['status'],
        ];
    }

    public function restorePlayCampaignBackup(string $campaignId, string $backupId): ?array
    {
        $backup = $this->getPlayCampaignBackup($campaignId, $backupId);
        if ($backup === null) {
            return null;
        }

        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $doc = $this->pdo->prepare("INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, '') ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story");
            $doc->execute([$campaignId, $backup['story']]);

            $upd = $this->pdo->prepare('UPDATE play_campaigns SET status = ? WHERE id = ?');
            $upd->execute([$backup['status'], $campaignId]);

            $this->pdo->exec('COMMIT');

            return $backup;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function createPlayCampaignReplayEvent(string $campaignId, string $eventId, string $kind, string $text): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_replay_events WHERE campaign_id = ?');
            $stmt->execute([$campaignId]);
            $sequence = (int) $stmt->fetchColumn();

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_replay_events (campaign_id, event_id, kind, text, sequence) VALUES (?, ?, ?, ?, ?)');
            $ins->execute([$campaignId, $eventId, $kind, $text, $sequence]);
            $id = (int) $this->pdo->lastInsertId();

            $select = $this->pdo->prepare('SELECT event_id, kind, text, sequence FROM play_campaign_replay_events WHERE id = ?');
            $select->execute([$id]);
            $row = $select->fetch();
            $this->pdo->exec('COMMIT');

            return [
                'event_id' => $row['event_id'],
                'kind' => $row['kind'],
                'text' => $row['text'],
                'sequence' => (int) $row['sequence'],
            ];
        } catch (PDOException $e) {
            $this->pdo->exec('ROLLBACK');
            if ($e->getCode() === '23000') {
                return null;
            }
            throw $e;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignReplayState(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT event_id, text FROM play_campaign_replay_events WHERE campaign_id = ? ORDER BY sequence ASC, id ASC');
        $stmt->execute([$campaignId]);
        $eventIds = [];
        $storyParts = [];
        foreach ($stmt->fetchAll() as $row) {
            $eventIds[] = $row['event_id'];
            $storyParts[] = $row['text'];
        }

        $story = implode('', $storyParts);
        $digest = implode(',', $eventIds) . '|' . $story;

        return [
            'story' => $story,
            'event_ids' => $eventIds,
            'digest' => $digest,
        ];
    }

    public function getPlayCampaignRngSeed(string $campaignId): ?string
    {
        $stmt = $this->pdo->prepare('SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();

        return $row !== false ? (string) $row['seed'] : null;
    }

    public function setPlayCampaignRngSeed(string $campaignId, string $seed): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_rng_seeds (campaign_id, seed) VALUES (?, ?)');
            $stmt->execute([$campaignId, $seed]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function appendPlayCampaignRngRoll(string $campaignId, string $rollId, int $sides, string $seed): array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $seqStmt = $this->pdo->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_rng_rolls WHERE campaign_id = ?');
            $seqStmt->execute([$campaignId]);
            $sequence = (int) $seqStmt->fetchColumn();

            $result = \App\Domain\RngLedger::roll($seed, $sequence, $rollId, $sides);

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_rng_rolls (campaign_id, roll_id, sides, result, sequence) VALUES (?, ?, ?, ?, ?)');
            $ins->execute([$campaignId, $rollId, $sides, $result, $sequence]);
            $id = (int) $this->pdo->lastInsertId();

            $select = $this->pdo->prepare('SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls WHERE id = ?');
            $select->execute([$id]);
            $row = $select->fetch();
            $this->pdo->exec('COMMIT');

            return [
                'roll_id' => $row['roll_id'],
                'sides' => (int) $row['sides'],
                'result' => (int) $row['result'],
                'sequence' => (int) $row['sequence'],
            ];
        } catch (PDOException $e) {
            $this->pdo->exec('ROLLBACK');
            if ($e->getCode() === '23000') {
                return ['error' => 'duplicate'];
            }
            throw $e;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignRngRolls(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls WHERE campaign_id = ? ORDER BY sequence ASC, id ASC');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'roll_id' => $row['roll_id'],
                'sides' => (int) $row['sides'],
                'result' => (int) $row['result'],
                'sequence' => (int) $row['sequence'],
            ];
        }

        return $result;
    }

    public function createPlayCampaignModerationReport(string $campaignId, string $reportId, string $targetId, string $reason, string $reporter): array|bool
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $seqStmt = $this->pdo->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_moderation_reports WHERE campaign_id = ?');
            $seqStmt->execute([$campaignId]);
            $sequence = (int) $seqStmt->fetchColumn();

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_moderation_reports (campaign_id, report_id, target_id, reason, status, reporter, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)');
            $ins->execute([$campaignId, $reportId, $targetId, $reason, 'open', $reporter, $sequence]);
            $id = (int) $this->pdo->lastInsertId();

            $select = $this->pdo->prepare('SELECT report_id, target_id, reason, status, reporter, sequence FROM play_campaign_moderation_reports WHERE id = ?');
            $select->execute([$id]);
            $row = $select->fetch();
            $this->pdo->exec('COMMIT');

            return [
                'report_id' => $row['report_id'],
                'target_id' => $row['target_id'],
                'reason' => $row['reason'],
                'status' => $row['status'],
                'reporter' => $row['reporter'],
                'sequence' => (int) $row['sequence'],
            ];
        } catch (PDOException $e) {
            $this->pdo->exec('ROLLBACK');
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignModerationReport(string $campaignId, string $reportId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $reportId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return $this->hydrateModerationReport($row);
    }

    public function getPlayCampaignModerationReports(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM play_campaign_moderation_reports WHERE campaign_id = ? ORDER BY sequence ASC, id ASC');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = $this->hydrateModerationReport($row);
        }

        return $result;
    }

    public function resolvePlayCampaignModerationReport(string $campaignId, string $reportId, string $action, string $note, string $resolver): array|bool
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT id, status FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ? LIMIT 1');
            $stmt->execute([$campaignId, $reportId]);
            $row = $stmt->fetch();
            if (!$row) {
                $this->pdo->exec('ROLLBACK');

                return false;
            }
            if ($row['status'] !== 'open') {
                $this->pdo->exec('ROLLBACK');

                return ['error' => 'already resolved'];
            }

            $upd = $this->pdo->prepare('UPDATE play_campaign_moderation_reports SET status = ?, action = ?, note = ?, resolver = ? WHERE id = ?');
            $upd->execute(['resolved', $action, $note, $resolver, $row['id']]);

            $select = $this->pdo->prepare('SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM play_campaign_moderation_reports WHERE id = ?');
            $select->execute([$row['id']]);
            $updated = $select->fetch();
            $this->pdo->exec('COMMIT');

            return $this->hydrateModerationReport($updated);
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    private function hydrateModerationReport(array $row): array
    {
        $report = [
            'report_id' => $row['report_id'],
            'target_id' => $row['target_id'],
            'reason' => $row['reason'],
            'status' => $row['status'],
            'reporter' => $row['reporter'],
            'sequence' => (int) $row['sequence'],
        ];
        if ($row['status'] === 'resolved') {
            $report['action'] = $row['action'];
            $report['note'] = $row['note'];
            $report['resolver'] = $row['resolver'];
        }

        return $report;
    }

    public function setPlayCampaignSafetyBoundaries(string $campaignId, array $tags): array
    {
        $sorted = $tags;
        sort($sorted, SORT_STRING);

        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_safety_boundaries (campaign_id, blocked_tags_json) VALUES (?, ?) ON CONFLICT(campaign_id) DO UPDATE SET blocked_tags_json = excluded.blocked_tags_json');
            $stmt->execute([$campaignId, json_encode($sorted, JSON_THROW_ON_ERROR)]);
            $this->pdo->exec('COMMIT');

            return ['blocked_tags' => $sorted];
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignSafetyBoundaries(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT blocked_tags_json FROM play_campaign_safety_boundaries WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return ['blocked_tags' => []];
        }

        $tags = json_decode($row['blocked_tags_json'], true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($tags)) {
            $tags = [];
        }

        return ['blocked_tags' => array_values($tags)];
    }

    public function createPlayCampaignSafetyEvent(string $campaignId, string $eventId, string $kind, string $text, array $tags): array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $check = $this->pdo->prepare('SELECT 1 FROM play_campaign_safety_events WHERE campaign_id = ? AND event_id = ? LIMIT 1');
            $check->execute([$campaignId, $eventId]);
            if ($check->fetch() !== false) {
                $this->pdo->exec('ROLLBACK');

                return ['error' => 'event_id already exists'];
            }

            $seqStmt = $this->pdo->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_safety_events WHERE campaign_id = ?');
            $seqStmt->execute([$campaignId]);
            $sequence = (int) $seqStmt->fetchColumn();

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_safety_events (campaign_id, event_id, kind, text, tags_json, sequence) VALUES (?, ?, ?, ?, ?, ?)');
            $ins->execute([$campaignId, $eventId, $kind, $text, json_encode($tags, JSON_THROW_ON_ERROR), $sequence]);
            $id = (int) $this->pdo->lastInsertId();

            $select = $this->pdo->prepare('SELECT event_id, kind, text, tags_json, sequence FROM play_campaign_safety_events WHERE id = ?');
            $select->execute([$id]);
            $row = $select->fetch();
            $this->pdo->exec('COMMIT');

            return [
                'event_id' => $row['event_id'],
                'kind' => $row['kind'],
                'text' => $row['text'],
                'tags' => json_decode($row['tags_json'], true, 512, JSON_THROW_ON_ERROR),
                'sequence' => (int) $row['sequence'],
            ];
        } catch (PDOException $e) {
            $this->pdo->exec('ROLLBACK');
            if ($e->getCode() === '23000') {
                return ['error' => 'event_id already exists'];
            }
            throw $e;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function playCampaignSafetyEventExists(string $campaignId, string $eventId): bool
    {
        $stmt = $this->pdo->prepare('SELECT 1 FROM play_campaign_safety_events WHERE campaign_id = ? AND event_id = ? LIMIT 1');
        $stmt->execute([$campaignId, $eventId]);

        return $stmt->fetch() !== false;
    }

    public function getPlayCampaignSafetyEvents(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT event_id, kind, text, tags_json, sequence FROM play_campaign_safety_events WHERE campaign_id = ? ORDER BY sequence ASC, id ASC');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'event_id' => $row['event_id'],
                'kind' => $row['kind'],
                'text' => $row['text'],
                'tags' => json_decode($row['tags_json'], true, 512, JSON_THROW_ON_ERROR),
                'sequence' => (int) $row['sequence'],
            ];
        }

        return $result;
    }

    public function createPlayCampaignFixture(string $campaignId): array
    {
        $fixture = [
            'fixture_id' => 'canonical-v1',
            'status' => 'seeded',
            'characters' => [
                ['character_id' => 'fixture-hero', 'name' => 'Ari', 'class' => 'fighter'],
                ['character_id' => 'fixture-mage', 'name' => 'Bea', 'class' => 'wizard'],
            ],
            'story' => 'The lantern is lit.',
            'event_ids' => ['fixture-event-1', 'fixture-event-2'],
        ];

        $stmt = $this->pdo->prepare('INSERT INTO play_campaign_fixtures (campaign_id, fixture_id, status, characters_json, story, event_ids_json) VALUES (?, ?, ?, ?, ?, ?)');
        $stmt->execute([
            $campaignId,
            $fixture['fixture_id'],
            $fixture['status'],
            json_encode($fixture['characters'], JSON_THROW_ON_ERROR),
            $fixture['story'],
            json_encode($fixture['event_ids'], JSON_THROW_ON_ERROR),
        ]);

        return $fixture;
    }

    public function getPlayCampaignFixture(string $campaignId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT fixture_id, status, characters_json, story, event_ids_json FROM play_campaign_fixtures WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'fixture_id' => $row['fixture_id'],
            'status' => $row['status'],
            'characters' => json_decode($row['characters_json'], true, 512, JSON_THROW_ON_ERROR),
            'story' => $row['story'],
            'event_ids' => json_decode($row['event_ids_json'], true, 512, JSON_THROW_ON_ERROR),
        ];
    }

    public function createPlayCampaignSpectator(string $spectatorId, string $campaignId): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO play_campaign_spectators (spectator_id, campaign_id) VALUES (?, ?)');
            $stmt->execute([$spectatorId, $campaignId]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getPlayCampaignSpectatorCampaign(string $spectatorId): ?string
    {
        $stmt = $this->pdo->prepare('SELECT campaign_id FROM play_campaign_spectators WHERE spectator_id = ?');
        $stmt->execute([$spectatorId]);
        $row = $stmt->fetch();

        return $row ? (string) $row['campaign_id'] : null;
    }

    public function createPlayCampaignFeedEvent(string $campaignId, string $eventId, string $text): ?array
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->pdo->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_feed_events WHERE campaign_id = ?');
            $stmt->execute([$campaignId]);
            $sequence = (int) $stmt->fetchColumn();

            $ins = $this->pdo->prepare('INSERT INTO play_campaign_feed_events (campaign_id, event_id, text, sequence) VALUES (?, ?, ?, ?)');
            $ins->execute([$campaignId, $eventId, $text, $sequence]);
            $id = (int) $this->pdo->lastInsertId();

            $select = $this->pdo->prepare('SELECT event_id, text, sequence FROM play_campaign_feed_events WHERE id = ?');
            $select->execute([$id]);
            $row = $select->fetch();
            $this->pdo->exec('COMMIT');

            return [
                'event_id' => $row['event_id'],
                'text' => $row['text'],
                'sequence' => (int) $row['sequence'],
            ];
        } catch (PDOException $e) {
            $this->pdo->exec('ROLLBACK');
            if ($e->getCode() === '23000') {
                return null;
            }
            throw $e;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    public function getPlayCampaignFeedEvents(string $campaignId, int $cursor, int $limit): array
    {
        $countStmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM play_campaign_feed_events WHERE campaign_id = ?');
        $countStmt->execute([$campaignId]);
        $total = (int) ($countStmt->fetch()['count'] ?? 0);

        if ($cursor >= $total) {
            return [
                'events' => [],
                'next_cursor' => $cursor,
            ];
        }

        $stmt = $this->pdo->prepare('SELECT event_id, text, sequence FROM play_campaign_feed_events WHERE campaign_id = ? ORDER BY sequence ASC, id ASC LIMIT ? OFFSET ?');
        $stmt->execute([$campaignId, $limit, $cursor]);
        $events = [];
        foreach ($stmt->fetchAll() as $row) {
            $events[] = [
                'event_id' => $row['event_id'],
                'text' => $row['text'],
                'sequence' => (int) $row['sequence'],
            ];
        }

        return [
            'events' => $events,
            'next_cursor' => $cursor + count($events),
        ];
    }
}
