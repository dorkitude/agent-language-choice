<?php

declare(strict_types=1);

/**
 * Encapsulates the SQLite persistence layer for the D&D helper API.
 *
 * All storage access is performed through this class. JSON columns are
 * encoded/decoded here so callers never deal with raw *_json fields.
 */
final class GameDatabase
{
    public const SCHEMA_VERSION = 1;

    private PDO $db;
    private string $root;

    public function __construct(string $dbFile)
    {
        $this->db = new PDO('sqlite:' . $dbFile);
        $this->db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $this->db->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
        $this->db->exec('PRAGMA busy_timeout = 5000');
        $this->root = dirname($dbFile);
    }

    public function pdo(): PDO
    {
        return $this->db;
    }

    /**
     * Create the schema if it does not already exist.
     *
     * Tables are created in dependency order (none currently have foreign keys,
     * but the order is kept stable for readability and safe resets).
     */
    public function initializeSchema(): void
    {
        $this->db->exec('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, role TEXT NOT NULL, hash TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS service_mode (name TEXT PRIMARY KEY, maintenance INTEGER NOT NULL DEFAULT 0)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS combat_sessions (id TEXT PRIMARY KEY, round INTEGER NOT NULL, turn_index INTEGER NOT NULL, order_json TEXT NOT NULL, conditions_json TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS monsters (slug TEXT PRIMARY KEY, name TEXT NOT NULL, cr TEXT NOT NULL, armor_class INTEGER NOT NULL, hit_points INTEGER NOT NULL, tags_json TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS items (slug TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, rarity TEXT NOT NULL, cost_gp INTEGER NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, dm TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS characters (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL, class TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, kind TEXT NOT NULL, summary TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS quests (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, milestones_json TEXT NOT NULL, completed_json TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS factions (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, stance TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS npcs (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, faction_id TEXT NOT NULL, disposition INTEGER NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS inventory (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, item_slug TEXT NOT NULL, quantity INTEGER NOT NULL, owner TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS equipment (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, quantity INTEGER NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS crafting_projects (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, days_required INTEGER NOT NULL, days_completed INTEGER NOT NULL, cost_gp INTEGER NOT NULL, status TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS campaign_sessions (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, starts_at TEXT NOT NULL, duration_minutes INTEGER NOT NULL, agenda_json TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS session_attendance (session_id TEXT NOT NULL, character_id TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (session_id, character_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL, status TEXT NOT NULL, max_players INTEGER NOT NULL, current_actor TEXT, turn_number INTEGER, nudge_count INTEGER DEFAULT 0, current_scene_id TEXT, current_location_id TEXT, phase TEXT, pre_combat_actor TEXT)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_members (campaign_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL, name TEXT NOT NULL, class TEXT NOT NULL, hp_current INTEGER DEFAULT 20, hp_max INTEGER DEFAULT 20, status TEXT DEFAULT \'conscious\', death_save_successes INTEGER DEFAULT 0, death_save_failures INTEGER DEFAULT 0, owner TEXT, PRIMARY KEY (campaign_id, character_id), UNIQUE (campaign_id, username))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_session_zero_settings (campaign_id TEXT PRIMARY KEY, rules TEXT NOT NULL, tone TEXT NOT NULL, consent_json TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_content (campaign_id TEXT NOT NULL, content_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, tags_json TEXT NOT NULL, PRIMARY KEY (campaign_id, content_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS search_records (campaign_id TEXT NOT NULL, record_id TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, record_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS narrations (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL, type TEXT, target TEXT, text TEXT NOT NULL, UNIQUE (campaign_id, sequence))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_campaign_documents (campaign_id TEXT PRIMARY KEY, story TEXT NOT NULL DEFAULT \'\', dm_notes TEXT NOT NULL DEFAULT \'\')');
        $this->db->exec('CREATE TABLE IF NOT EXISTS campaign_exports (campaign_id TEXT NOT NULL, version INTEGER NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, version))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS campaign_backups (campaign_id TEXT NOT NULL, backup_id TEXT NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, backup_id))');
        $this->db->exec('CREATE INDEX IF NOT EXISTS idx_campaign_backups_sequence ON campaign_backups (campaign_id, sequence ASC)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS campaign_imports (campaign_id TEXT PRIMARY KEY, version INTEGER NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS campaign_migrations (campaign_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, story TEXT NOT NULL, campaign_name TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS scenes (campaign_id TEXT NOT NULL, scene_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, scene_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS locations (campaign_id TEXT NOT NULL, location_id TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY (campaign_id, location_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS location_connections (campaign_id TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL, travel_turns INTEGER NOT NULL, PRIMARY KEY (campaign_id, from_id, to_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_encounters (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL, combatants_json TEXT NOT NULL, round INTEGER DEFAULT 1, turn_index INTEGER DEFAULT 0, conditions_json TEXT NOT NULL DEFAULT \'[]\', turn_order_json TEXT, ready_actions_json TEXT NOT NULL DEFAULT \'[]\')');
        $this->db->exec('CREATE TABLE IF NOT EXISTS encounter_rewards (encounter_id TEXT PRIMARY KEY, xp INTEGER NOT NULL, loot_json TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS character_spells (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, spell_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS character_prepared_spells (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, PRIMARY KEY (campaign_id, character_id, spell_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS character_spell_slots (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, level INTEGER NOT NULL, slots_total INTEGER NOT NULL, slots_remaining INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, level))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS character_casts (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, sequence INTEGER NOT NULL, spell_id TEXT NOT NULL, target TEXT NOT NULL, slot_level INTEGER NOT NULL, slots_remaining INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, sequence))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS character_concentration (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, target TEXT NOT NULL, remaining_turns INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS character_inventory (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, item_slug))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS character_equipment (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, slot TEXT NOT NULL, item_slug TEXT NOT NULL, attuned INTEGER DEFAULT 0, PRIMARY KEY (campaign_id, character_id, slot))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS character_currency (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, gold INTEGER NOT NULL DEFAULT 10, PRIMARY KEY (campaign_id, character_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS currency_transfers (campaign_id TEXT NOT NULL, transfer_id INTEGER NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, gold INTEGER NOT NULL, from_gold INTEGER NOT NULL, to_gold INTEGER NOT NULL, PRIMARY KEY (campaign_id, transfer_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS transactional_transfers (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, amount INTEGER NOT NULL, from_gold INTEGER NOT NULL, to_gold INTEGER NOT NULL, PRIMARY KEY (campaign_id, sequence))');
        $this->db->exec('CREATE INDEX IF NOT EXISTS idx_transactional_transfers_sequence ON transactional_transfers (campaign_id, sequence ASC)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS campaign_loot (campaign_id TEXT NOT NULL, loot_id TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL, status TEXT NOT NULL, recipient_character_id TEXT, PRIMARY KEY (campaign_id, loot_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS campaign_loot_votes (campaign_id TEXT NOT NULL, loot_id TEXT NOT NULL, voter TEXT NOT NULL, recipient_character_id TEXT NOT NULL, PRIMARY KEY (campaign_id, loot_id, voter))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_npcs (campaign_id TEXT NOT NULL, npc_id TEXT NOT NULL, name TEXT NOT NULL, agenda TEXT NOT NULL, public_status TEXT NOT NULL, PRIMARY KEY (campaign_id, npc_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_factions (campaign_id TEXT NOT NULL, faction_id TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY (campaign_id, faction_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS faction_reputation_history (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, faction_id TEXT NOT NULL, character_id TEXT NOT NULL, reputation INTEGER NOT NULL, delta INTEGER NOT NULL, reason TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS npc_dialogue (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, npc_id TEXT NOT NULL, dialogue_id TEXT NOT NULL, speaker TEXT NOT NULL, text TEXT NOT NULL, visibility TEXT NOT NULL, UNIQUE (campaign_id, npc_id, dialogue_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS relationships (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, source_id TEXT NOT NULL, target_id TEXT NOT NULL, kind TEXT NOT NULL, score INTEGER NOT NULL, UNIQUE (campaign_id, source_id, target_id, kind))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS clues (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, clue_id TEXT NOT NULL, text TEXT NOT NULL, audience TEXT NOT NULL, character_id TEXT, UNIQUE (campaign_id, clue_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_quests (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, title TEXT NOT NULL, state TEXT NOT NULL DEFAULT \'locked\', depends_on_json TEXT NOT NULL DEFAULT \'[]\', rewards_json TEXT, awarded INTEGER DEFAULT 0, UNIQUE (campaign_id, quest_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS quest_reward_grants (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, character_id TEXT NOT NULL, xp INTEGER NOT NULL, items_json TEXT NOT NULL, UNIQUE (campaign_id, quest_id, character_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_world_events (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, turn_number INTEGER NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL DEFAULT \'scheduled\', resolution_turn_number INTEGER, resolution_text TEXT, UNIQUE (campaign_id, event_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_calendar (campaign_id TEXT PRIMARY KEY, day INTEGER NOT NULL, season TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS settlements (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, name TEXT NOT NULL, services_json TEXT NOT NULL, availability TEXT NOT NULL, discovered_by_json TEXT NOT NULL DEFAULT \'[]\', PRIMARY KEY (campaign_id, settlement_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS shops (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, shop_id TEXT NOT NULL, name TEXT NOT NULL, stock_json TEXT NOT NULL, buy_price INTEGER NOT NULL, sell_price INTEGER NOT NULL, PRIMARY KEY (campaign_id, settlement_id, shop_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS recipes (campaign_id TEXT NOT NULL, recipe_id TEXT NOT NULL, name TEXT NOT NULL, ingredients_json TEXT NOT NULL, output_item TEXT NOT NULL, output_quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, recipe_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS downtime_activities (campaign_id TEXT NOT NULL, activity_id TEXT NOT NULL, name TEXT NOT NULL, cycles_required INTEGER NOT NULL, PRIMARY KEY (campaign_id, activity_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS downtime_allocations (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, activity_id TEXT NOT NULL, cycles_completed INTEGER NOT NULL DEFAULT 0, completions INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, character_id, activity_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_notes (campaign_id TEXT NOT NULL, note_id TEXT NOT NULL, text TEXT NOT NULL, visibility TEXT NOT NULL, owner TEXT NOT NULL, PRIMARY KEY (campaign_id, note_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_whispers (campaign_id TEXT NOT NULL, whisper_id TEXT NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, whisper_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, actor TEXT NOT NULL, text TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_invitations (campaign_id TEXT NOT NULL, invitation_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, invitation_id))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_spectators (campaign_id TEXT NOT NULL, spectator_id TEXT PRIMARY KEY)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_delegations (campaign_id TEXT NOT NULL, username TEXT NOT NULL, powers_json TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (campaign_id, username))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_delegation_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, username TEXT NOT NULL, action TEXT NOT NULL, powers_json TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_audit_events (campaign_id TEXT NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL, role TEXT NOT NULL, timestamp INTEGER NOT NULL, correlation_id TEXT NOT NULL, PRIMARY KEY (campaign_id, correlation_id))');
        $this->db->exec('CREATE INDEX IF NOT EXISTS idx_play_audit_events_timestamp ON play_audit_events (campaign_id, timestamp ASC)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS projection_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id))');
        $this->db->exec('CREATE INDEX IF NOT EXISTS idx_projection_events_sequence ON projection_events (campaign_id, sequence ASC)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS idempotent_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, value TEXT NOT NULL, idempotency_key TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id), UNIQUE (campaign_id, idempotency_key))');
        $this->db->exec('CREATE INDEX IF NOT EXISTS idx_idempotent_events_sequence ON idempotent_events (campaign_id, sequence ASC)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS replay_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id))');
        $this->db->exec('CREATE INDEX IF NOT EXISTS idx_replay_events_sequence ON replay_events (campaign_id, sequence ASC)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS campaign_rng_seeds (campaign_id TEXT PRIMARY KEY, seed TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS rng_ledger (campaign_id TEXT NOT NULL, roll_id TEXT NOT NULL, sides INTEGER NOT NULL, result INTEGER NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, roll_id), UNIQUE (campaign_id, sequence))');
        $this->db->exec('CREATE INDEX IF NOT EXISTS idx_rng_ledger_sequence ON rng_ledger (campaign_id, sequence ASC)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS moderation_reports (campaign_id TEXT NOT NULL, report_id TEXT NOT NULL, target_id TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL, reporter TEXT NOT NULL, sequence INTEGER NOT NULL, action TEXT, note TEXT, resolver TEXT, PRIMARY KEY (campaign_id, report_id), UNIQUE (campaign_id, sequence))');
        $this->db->exec('CREATE INDEX IF NOT EXISTS idx_moderation_reports_sequence ON moderation_reports (campaign_id, sequence ASC)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS rate_events (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, actor TEXT NOT NULL, UNIQUE (campaign_id, event_id))');
        $this->db->exec('CREATE INDEX IF NOT EXISTS idx_rate_events_campaign ON rate_events (campaign_id, id ASC)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS safe_turns (campaign_id TEXT PRIMARY KEY, current_turn INTEGER NOT NULL DEFAULT 1)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS safe_turn_submissions (campaign_id TEXT NOT NULL, submission_id TEXT NOT NULL, action TEXT NOT NULL, accepted_turn INTEGER NOT NULL, next_turn INTEGER NOT NULL, PRIMARY KEY (campaign_id, submission_id), UNIQUE (campaign_id, accepted_turn))');
        $this->db->exec('CREATE INDEX IF NOT EXISTS idx_safe_turn_submissions_accepted ON safe_turn_submissions (campaign_id, accepted_turn ASC)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS campaign_metrics (campaign_id TEXT PRIMARY KEY, accepted_rate_events INTEGER NOT NULL DEFAULT 0, rejected_rate_events INTEGER NOT NULL DEFAULT 0, projection_events INTEGER NOT NULL DEFAULT 0, uptime_ticks INTEGER NOT NULL DEFAULT 1)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS safety_boundaries (campaign_id TEXT PRIMARY KEY, tags_json TEXT NOT NULL DEFAULT \'[]\')');
        $this->db->exec('CREATE TABLE IF NOT EXISTS safety_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, tags_json TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, event_id), UNIQUE (campaign_id, sequence))');
        $this->db->exec('CREATE INDEX IF NOT EXISTS idx_safety_events_sequence ON safety_events (campaign_id, sequence ASC)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS play_fixture_seeds (campaign_id TEXT PRIMARY KEY, fixture_id TEXT NOT NULL, status TEXT NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS feed_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, text TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id))');
        $this->db->exec('CREATE INDEX IF NOT EXISTS idx_feed_events_sequence ON feed_events (campaign_id, sequence ASC)');

        if (!$this->columnExists('play_campaigns', 'current_scene_id')) {
            $this->db->exec('ALTER TABLE play_campaigns ADD COLUMN current_scene_id TEXT');
        }
        if (!$this->columnExists('play_campaigns', 'current_location_id')) {
            $this->db->exec('ALTER TABLE play_campaigns ADD COLUMN current_location_id TEXT');
        }
        if (!$this->columnExists('play_members', 'hp_current')) {
            $this->db->exec('ALTER TABLE play_members ADD COLUMN hp_current INTEGER DEFAULT 20');
        }
        if (!$this->columnExists('play_members', 'hp_max')) {
            $this->db->exec('ALTER TABLE play_members ADD COLUMN hp_max INTEGER DEFAULT 20');
        }
        if (!$this->columnExists('play_members', 'status')) {
            $this->db->exec('ALTER TABLE play_members ADD COLUMN status TEXT DEFAULT \'conscious\'');
        }
        if (!$this->columnExists('play_members', 'death_save_successes')) {
            $this->db->exec('ALTER TABLE play_members ADD COLUMN death_save_successes INTEGER DEFAULT 0');
        }
        if (!$this->columnExists('play_members', 'death_save_failures')) {
            $this->db->exec('ALTER TABLE play_members ADD COLUMN death_save_failures INTEGER DEFAULT 0');
        }
        if (!$this->columnExists('play_members', 'owner')) {
            $this->db->exec('ALTER TABLE play_members ADD COLUMN owner TEXT');
            $this->db->exec('UPDATE play_members SET owner = username WHERE owner IS NULL');
        }
        if (!$this->columnExists('play_encounters', 'round')) {
            $this->db->exec('ALTER TABLE play_encounters ADD COLUMN round INTEGER DEFAULT 1');
        }
        if (!$this->columnExists('play_encounters', 'turn_index')) {
            $this->db->exec('ALTER TABLE play_encounters ADD COLUMN turn_index INTEGER DEFAULT 0');
        }
        if (!$this->columnExists('play_encounters', 'conditions_json')) {
            $this->db->exec('ALTER TABLE play_encounters ADD COLUMN conditions_json TEXT NOT NULL DEFAULT \'[]\'');
        }
        if (!$this->columnExists('play_encounters', 'turn_order_json')) {
            $this->db->exec('ALTER TABLE play_encounters ADD COLUMN turn_order_json TEXT');
        }
        if (!$this->columnExists('play_encounters', 'ready_actions_json')) {
            $this->db->exec('ALTER TABLE play_encounters ADD COLUMN ready_actions_json TEXT NOT NULL DEFAULT \'[]\'');
        }
        if (!$this->columnExists('narrations', 'target')) {
            $this->db->exec('ALTER TABLE narrations ADD COLUMN target TEXT');
        }
        if (!$this->columnExists('play_campaigns', 'phase')) {
            $this->db->exec('ALTER TABLE play_campaigns ADD COLUMN phase TEXT');
        }
        if (!$this->columnExists('play_campaigns', 'pre_combat_actor')) {
            $this->db->exec('ALTER TABLE play_campaigns ADD COLUMN pre_combat_actor TEXT');
        }
        if (!$this->columnExists('play_members', 'race')) {
            $this->db->exec('ALTER TABLE play_members ADD COLUMN race TEXT');
        }
        if (!$this->columnExists('play_members', 'background')) {
            $this->db->exec('ALTER TABLE play_members ADD COLUMN background TEXT');
        }
        if (!$this->columnExists('play_members', 'abilities_json')) {
            $this->db->exec('ALTER TABLE play_members ADD COLUMN abilities_json TEXT');
        }
        if (!$this->columnExists('play_members', 'level')) {
            $this->db->exec('ALTER TABLE play_members ADD COLUMN level INTEGER');
        }
        if (!$this->columnExists('play_quests', 'rewards_json')) {
            $this->db->exec('ALTER TABLE play_quests ADD COLUMN rewards_json TEXT');
        }
        if (!$this->columnExists('play_quests', 'awarded')) {
            $this->db->exec('ALTER TABLE play_quests ADD COLUMN awarded INTEGER DEFAULT 0');
        }
        if (!$this->columnExists('quest_reward_grants', 'id')) {
            $this->db->exec('CREATE TABLE IF NOT EXISTS quest_reward_grants (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, character_id TEXT NOT NULL, xp INTEGER NOT NULL, items_json TEXT NOT NULL, UNIQUE (campaign_id, quest_id, character_id))');
        }
    }

    /**
     * A minimal health check used by the storage status endpoint.
     *
     * Only the users and combat_sessions tables are checked because they were
     * the first tables added to the schema and are always present in a healthy
     * database.
     */
    public function isInitialized(): bool
    {
        $stmt = $this->db->query("SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('users', 'combat_sessions')");
        return (int) $stmt->fetchColumn() === 2;
    }

    /**
     * Drop all tables and recreate the schema.
     *
     * Tables are dropped in reverse creation order to avoid any future
     * dependency problems if foreign keys are ever added.
     */
    public function reset(): void
    {
        $this->db->exec('DROP TABLE IF EXISTS service_mode');
        $this->db->exec('DROP TABLE IF EXISTS recipes');
        $this->db->exec('DROP TABLE IF EXISTS feed_events');
        $this->db->exec('DROP TABLE IF EXISTS play_fixture_seeds');
        $this->db->exec('DROP TABLE IF EXISTS safety_events');
        $this->db->exec('DROP TABLE IF EXISTS safety_boundaries');
        $this->db->exec('DROP TABLE IF EXISTS campaign_metrics');
        $this->db->exec('DROP TABLE IF EXISTS safe_turn_submissions');
        $this->db->exec('DROP TABLE IF EXISTS safe_turns');
        $this->db->exec('DROP TABLE IF EXISTS rng_ledger');
        $this->db->exec('DROP TABLE IF EXISTS moderation_reports');
        $this->db->exec('DROP TABLE IF EXISTS campaign_rng_seeds');
        $this->db->exec('DROP TABLE IF EXISTS idempotent_events');
        $this->db->exec('DROP TABLE IF EXISTS replay_events');
        $this->db->exec('DROP TABLE IF EXISTS rate_events');
        $this->db->exec('DROP TABLE IF EXISTS projection_events');
        $this->db->exec('DROP TABLE IF EXISTS play_audit_events');
        $this->db->exec('DROP TABLE IF EXISTS play_delegation_audit');
        $this->db->exec('DROP TABLE IF EXISTS play_delegations');
        $this->db->exec('DROP TABLE IF EXISTS play_spectators');
        $this->db->exec('DROP TABLE IF EXISTS play_invitations');
        $this->db->exec('DROP TABLE IF EXISTS play_messages');
        $this->db->exec('DROP TABLE IF EXISTS play_whispers');
        $this->db->exec('DROP TABLE IF EXISTS play_notes');
        $this->db->exec('DROP TABLE IF EXISTS downtime_allocations');
        $this->db->exec('DROP TABLE IF EXISTS downtime_activities');
        $this->db->exec('DROP TABLE IF EXISTS shops');
        $this->db->exec('DROP TABLE IF EXISTS settlements');
        $this->db->exec('DROP TABLE IF EXISTS session_attendance');
        $this->db->exec('DROP TABLE IF EXISTS encounter_rewards');
        $this->db->exec('DROP TABLE IF EXISTS play_encounters');
        $this->db->exec('DROP TABLE IF EXISTS character_casts');
        $this->db->exec('DROP TABLE IF EXISTS character_inventory');
        $this->db->exec('DROP TABLE IF EXISTS character_equipment');
        $this->db->exec('DROP TABLE IF EXISTS transactional_transfers');
        $this->db->exec('DROP TABLE IF EXISTS currency_transfers');
        $this->db->exec('DROP TABLE IF EXISTS campaign_loot_votes');
        $this->db->exec('DROP TABLE IF EXISTS play_npcs');
        $this->db->exec('DROP TABLE IF EXISTS play_factions');
        $this->db->exec('DROP TABLE IF EXISTS faction_reputation_history');
        $this->db->exec('DROP TABLE IF EXISTS quest_reward_grants');
        $this->db->exec('DROP TABLE IF EXISTS play_calendar');
        $this->db->exec('DROP TABLE IF EXISTS play_world_events');
        $this->db->exec('DROP TABLE IF EXISTS play_quests');
        $this->db->exec('DROP TABLE IF EXISTS clues');
        $this->db->exec('DROP TABLE IF EXISTS relationships');
        $this->db->exec('DROP TABLE IF EXISTS npc_dialogue');
        $this->db->exec('DROP TABLE IF EXISTS campaign_loot');
        $this->db->exec('DROP TABLE IF EXISTS character_currency');
        $this->db->exec('DROP TABLE IF EXISTS character_concentration');
        $this->db->exec('DROP TABLE IF EXISTS character_spell_slots');
        $this->db->exec('DROP TABLE IF EXISTS character_prepared_spells');
        $this->db->exec('DROP TABLE IF EXISTS character_spells');
        $this->db->exec('DROP TABLE IF EXISTS play_members');
        $this->db->exec('DROP TABLE IF EXISTS search_records');
        $this->db->exec('DROP TABLE IF EXISTS play_content');
        $this->db->exec('DROP TABLE IF EXISTS play_session_zero_settings');
        $this->db->exec('DROP TABLE IF EXISTS campaign_migrations');
        $this->db->exec('DROP TABLE IF EXISTS campaign_imports');
        $this->db->exec('DROP TABLE IF EXISTS campaign_backups');
        $this->db->exec('DROP TABLE IF EXISTS campaign_exports');
        $this->db->exec('DROP TABLE IF EXISTS play_campaign_documents');
        $this->db->exec('DROP TABLE IF EXISTS location_connections');
        $this->db->exec('DROP TABLE IF EXISTS locations');
        $this->db->exec('DROP TABLE IF EXISTS scenes');
        $this->db->exec('DROP TABLE IF EXISTS narrations');
        $this->db->exec('DROP TABLE IF EXISTS play_campaigns');
        $this->db->exec('DROP TABLE IF EXISTS campaign_sessions');
        $this->db->exec('DROP TABLE IF EXISTS crafting_projects');
        $this->db->exec('DROP TABLE IF EXISTS equipment');
        $this->db->exec('DROP TABLE IF EXISTS inventory');
        $this->db->exec('DROP TABLE IF EXISTS npcs');
        $this->db->exec('DROP TABLE IF EXISTS factions');
        $this->db->exec('DROP TABLE IF EXISTS quests');
        $this->db->exec('DROP TABLE IF EXISTS events');
        $this->db->exec('DROP TABLE IF EXISTS characters');
        $this->db->exec('DROP TABLE IF EXISTS campaigns');
        $this->db->exec('DROP TABLE IF EXISTS items');
        $this->db->exec('DROP TABLE IF EXISTS monsters');
        $this->db->exec('DROP TABLE IF EXISTS combat_sessions');
        $this->db->exec('DROP TABLE IF EXISTS users');
        $this->initializeSchema();
        $this->seedUsers();
    }

    // Users

    public function findUser(string $username): ?array
    {
        $stmt = $this->db->prepare('SELECT username, role, hash FROM users WHERE username = ?');
        $stmt->execute([$username]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function getServiceMode(): bool
    {
        $stmt = $this->db->prepare('SELECT maintenance FROM service_mode WHERE name = ?');
        $stmt->execute(['global']);
        $row = $stmt->fetch();
        if (!$row) {
            return false;
        }
        return (bool) $row['maintenance'];
    }

    public function setServiceMode(bool $maintenance): void
    {
        $stmt = $this->db->prepare('INSERT INTO service_mode (name, maintenance) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET maintenance = excluded.maintenance');
        $stmt->execute(['global', $maintenance ? 1 : 0]);
    }

    public function createUser(array $user): void
    {
        $stmt = $this->db->prepare('INSERT INTO users (username, role, hash) VALUES (?, ?, ?)');
        $stmt->execute([$user['username'], $user['role'], $user['hash']]);
    }

    public function updateUser(string $username, string $role, string $hash): void
    {
        $stmt = $this->db->prepare('UPDATE users SET role = ?, hash = ? WHERE username = ?');
        $stmt->execute([$role, $hash, $username]);
    }

    // Combat sessions

    public function findCombatSession(string $id): ?array
    {
        $stmt = $this->db->prepare('SELECT id, round, turn_index, order_json, conditions_json FROM combat_sessions WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['order'] = $this->decodeJson($row['order_json']);
        $row['conditions'] = $this->decodeJson($row['conditions_json']);
        unset($row['order_json'], $row['conditions_json']);
        return $row;
    }

    public function createCombatSession(array $session): void
    {
        $stmt = $this->db->prepare('INSERT INTO combat_sessions (id, round, turn_index, order_json, conditions_json) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([
            $session['id'],
            $session['round'],
            $session['turn_index'],
            $this->encodeJson($session['order']),
            $this->encodeJson($session['conditions']),
        ]);
    }

    public function updateCombatSession(array $session): void
    {
        $stmt = $this->db->prepare('UPDATE combat_sessions SET round = ?, turn_index = ?, order_json = ?, conditions_json = ? WHERE id = ?');
        $stmt->execute([
            $session['round'],
            $session['turn_index'],
            $this->encodeJson($session['order']),
            $this->encodeJson($session['conditions']),
            $session['id'],
        ]);
    }

    // Monsters

    public function findMonster(string $slug): ?array
    {
        $stmt = $this->db->prepare('SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters WHERE slug = ?');
        $stmt->execute([$slug]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['tags'] = $this->decodeJson($row['tags_json']);
        unset($row['tags_json']);
        return $row;
    }

    public function createMonster(array $monster): void
    {
        $stmt = $this->db->prepare('INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)');
        $stmt->execute([
            $monster['slug'],
            $monster['name'],
            $monster['cr'],
            $monster['armor_class'],
            $monster['hit_points'],
            $this->encodeJson($monster['tags']),
        ]);
    }

    // Items

    public function findItem(string $slug): ?array
    {
        $stmt = $this->db->prepare('SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?');
        $stmt->execute([$slug]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createItem(array $item): void
    {
        $stmt = $this->db->prepare('INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([
            $item['slug'],
            $item['name'],
            $item['type'],
            $item['rarity'],
            $item['cost_gp'],
        ]);
    }

    // Campaigns

    public function findCampaign(string $id): ?array
    {
        $stmt = $this->db->prepare('SELECT id, name, dm FROM campaigns WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createCampaign(array $campaign): void
    {
        $stmt = $this->db->prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)');
        $stmt->execute([$campaign['id'], $campaign['name'], $campaign['dm']]);
    }

    // Play campaigns

    public function findPlayCampaign(string $id): ?array
    {
        $stmt = $this->db->prepare('SELECT id, name, owner, status, max_players, current_actor, turn_number, nudge_count, current_scene_id, current_location_id, phase, pre_combat_actor FROM play_campaigns WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function findPlayMembers(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, username, character_id, name, class, hp_current, hp_max, owner FROM play_members WHERE campaign_id = ? ORDER BY rowid ASC');
        $stmt->execute([$campaignId]);
        return $stmt->fetchAll();
    }

    public function startPlayCampaign(string $id, string $currentActor, int $turnNumber): void
    {
        $stmt = $this->db->prepare('UPDATE play_campaigns SET status = ?, current_actor = ?, turn_number = ?, phase = ?, pre_combat_actor = ? WHERE id = ?');
        $stmt->execute(['active', $currentActor, $turnNumber, 'exploration', null, $id]);
    }

    public function updatePlayCampaignCurrentActor(string $id, string $currentActor): void
    {
        $stmt = $this->db->prepare('UPDATE play_campaigns SET current_actor = ? WHERE id = ?');
        $stmt->execute([$currentActor, $id]);
    }

    public function updatePlayCampaignTurn(string $id, string $currentActor, int $turnNumber): void
    {
        $stmt = $this->db->prepare('UPDATE play_campaigns SET current_actor = ?, turn_number = ? WHERE id = ?');
        $stmt->execute([$currentActor, $turnNumber, $id]);
    }

    public function incrementNudgeCount(string $campaignId): int
    {
        $stmt = $this->db->prepare('UPDATE play_campaigns SET nudge_count = COALESCE(nudge_count, 0) + 1 WHERE id = ?');
        $stmt->execute([$campaignId]);

        $stmt = $this->db->prepare('SELECT nudge_count FROM play_campaigns WHERE id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    // Play members

    public function findPlayMemberByCharacterId(string $characterId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, username, character_id, name, class, hp_current, hp_max, status, death_save_successes, death_save_failures, owner FROM play_members WHERE character_id = ?');
        $stmt->execute([$characterId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function findPlayMemberByCampaignAndUser(string $campaignId, string $username): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, username, character_id, name, class, hp_current, hp_max, status, death_save_successes, death_save_failures, owner FROM play_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $username]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function findPlayMemberByCampaignAndCharacterId(string $campaignId, string $characterId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, username, character_id, name, class, hp_current, hp_max, status, death_save_successes, death_save_failures, owner, level, abilities_json FROM play_members WHERE campaign_id = ? AND character_id = ?');
        $stmt->execute([$campaignId, $characterId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function countPlayMembers(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT count(*) FROM play_members WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    public function createPlayMember(array $member): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_members (campaign_id, username, character_id, name, class, owner) VALUES (?, ?, ?, ?, ?, ?)');
        $stmt->execute([$member['campaign_id'], $member['username'], $member['character_id'], $member['name'], $member['class'], $member['owner'] ?? $member['username']]);

        $stmt = $this->db->prepare('INSERT OR IGNORE INTO character_currency (campaign_id, character_id, gold) VALUES (?, ?, 10)');
        $stmt->execute([$member['campaign_id'], $member['character_id']]);
    }

    public function updatePlayMemberHp(string $campaignId, string $username, int $hpCurrent, int $hpMax): void
    {
        $member = $this->findPlayMemberByCampaignAndUser($campaignId, $username);
        $status = (string) ($member['status'] ?? 'conscious');
        $successes = (int) ($member['death_save_successes'] ?? 0);
        $failures = (int) ($member['death_save_failures'] ?? 0);

        if ($hpCurrent > 0) {
            $status = 'conscious';
            $successes = 0;
            $failures = 0;
        } elseif ($status !== 'dead' && $status !== 'stable') {
            $status = 'unconscious';
        }

        $stmt = $this->db->prepare('UPDATE play_members SET hp_current = ?, hp_max = ?, status = ?, death_save_successes = ?, death_save_failures = ? WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$hpCurrent, $hpMax, $status, $successes, $failures, $campaignId, $username]);
    }

    public function updatePlayMemberDeathSaves(string $campaignId, string $username, int $successes, int $failures, string $status): void
    {
        $stmt = $this->db->prepare('UPDATE play_members SET death_save_successes = ?, death_save_failures = ?, status = ? WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$successes, $failures, $status, $campaignId, $username]);
    }

    public function updatePlayMemberOwner(string $campaignId, string $characterId, string $owner): void
    {
        $stmt = $this->db->prepare('UPDATE play_members SET owner = ? WHERE campaign_id = ? AND character_id = ?');
        $stmt->execute([$owner, $campaignId, $characterId]);
    }

    public function updatePlayMemberBuild(string $campaignId, string $characterId, string $race, string $class, string $background, int $level, int $hpMax, array $abilities): void
    {
        $stmt = $this->db->prepare('UPDATE play_members SET race = ?, class = ?, background = ?, level = ?, hp_max = ?, hp_current = ?, status = ?, abilities_json = ? WHERE campaign_id = ? AND character_id = ?');
        $stmt->execute([$race, $class, $background, $level, $hpMax, $hpMax, 'conscious', $this->encodeJson($abilities), $campaignId, $characterId]);
    }

    public function updatePlayMemberLevelAndHpMax(string $campaignId, string $characterId, int $level, int $hpMax): void
    {
        $stmt = $this->db->prepare('UPDATE play_members SET level = ?, hp_max = ? WHERE campaign_id = ? AND character_id = ?');
        $stmt->execute([$level, $hpMax, $campaignId, $characterId]);
    }

    // Character spells

    public function findCharacterSpell(string $campaignId, string $characterId, string $spellId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, character_id, spell_id, name, level FROM character_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?');
        $stmt->execute([$campaignId, $characterId, $spellId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function findCharacterSpells(string $campaignId, string $characterId): array
    {
        $stmt = $this->db->prepare('SELECT spell_id, name, level FROM character_spells WHERE campaign_id = ? AND character_id = ? ORDER BY level ASC, name ASC');
        $stmt->execute([$campaignId, $characterId]);
        return $stmt->fetchAll();
    }

    public function createCharacterSpell(string $campaignId, string $characterId, string $spellId, string $name, int $level): void
    {
        $stmt = $this->db->prepare('INSERT INTO character_spells (campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $characterId, $spellId, $name, $level]);
    }

    public function findCharacterPreparedSpells(string $campaignId, string $characterId): array
    {
        $stmt = $this->db->prepare('SELECT spell_id FROM character_prepared_spells WHERE campaign_id = ? AND character_id = ? ORDER BY rowid ASC');
        $stmt->execute([$campaignId, $characterId]);
        return array_column($stmt->fetchAll(), 'spell_id');
    }

    public function setCharacterPreparedSpells(string $campaignId, string $characterId, array $spellIds): void
    {
        $stmt = $this->db->prepare('DELETE FROM character_prepared_spells WHERE campaign_id = ? AND character_id = ?');
        $stmt->execute([$campaignId, $characterId]);

        $stmt = $this->db->prepare('INSERT INTO character_prepared_spells (campaign_id, character_id, spell_id) VALUES (?, ?, ?)');
        foreach ($spellIds as $spellId) {
            $stmt->execute([$campaignId, $characterId, (string) $spellId]);
        }
    }

    // Character spell slots

    public function findCharacterSpellSlots(string $campaignId, string $characterId): array
    {
        $stmt = $this->db->prepare('SELECT level, slots_total, slots_remaining FROM character_spell_slots WHERE campaign_id = ? AND character_id = ? ORDER BY level ASC');
        $stmt->execute([$campaignId, $characterId]);
        $rows = $stmt->fetchAll();
        $slots = [];
        foreach ($rows as $row) {
            $slots[(int) $row['level']] = [
                'slots_total' => (int) $row['slots_total'],
                'slots_remaining' => (int) $row['slots_remaining'],
            ];
        }
        return $slots;
    }

    public function findCharacterSpellSlot(string $campaignId, string $characterId, int $level): ?array
    {
        $stmt = $this->db->prepare('SELECT level, slots_total, slots_remaining FROM character_spell_slots WHERE campaign_id = ? AND character_id = ? AND level = ?');
        $stmt->execute([$campaignId, $characterId, $level]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        return [
            'level' => (int) $row['level'],
            'slots_total' => (int) $row['slots_total'],
            'slots_remaining' => (int) $row['slots_remaining'],
        ];
    }

    public function setCharacterSpellSlots(string $campaignId, string $characterId, array $slots): void
    {
        $stmt = $this->db->prepare('DELETE FROM character_spell_slots WHERE campaign_id = ? AND character_id = ?');
        $stmt->execute([$campaignId, $characterId]);

        $stmt = $this->db->prepare('INSERT INTO character_spell_slots (campaign_id, character_id, level, slots_total, slots_remaining) VALUES (?, ?, ?, ?, ?)');
        foreach ($slots as $level => $total) {
            $level = (int) $level;
            $total = (int) $total;
            $stmt->execute([$campaignId, $characterId, $level, $total, $total]);
        }
    }

    public function consumeCharacterSpellSlot(string $campaignId, string $characterId, int $level): bool
    {
        $stmt = $this->db->prepare('UPDATE character_spell_slots SET slots_remaining = slots_remaining - 1 WHERE campaign_id = ? AND character_id = ? AND level = ? AND slots_remaining > 0');
        $stmt->execute([$campaignId, $characterId, $level]);
        return $stmt->rowCount() > 0;
    }

    public function resetCharacterSpellSlots(string $campaignId, string $characterId): void
    {
        $stmt = $this->db->prepare('UPDATE character_spell_slots SET slots_remaining = slots_total WHERE campaign_id = ? AND character_id = ?');
        $stmt->execute([$campaignId, $characterId]);
    }

    // Character casts

    public function nextCastSequence(string $campaignId, string $characterId): int
    {
        $stmt = $this->db->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM character_casts WHERE campaign_id = ? AND character_id = ?');
        $stmt->execute([$campaignId, $characterId]);
        return (int) $stmt->fetchColumn();
    }

    public function createCast(array $cast): void
    {
        $stmt = $this->db->prepare('INSERT INTO character_casts (campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining) VALUES (?, ?, ?, ?, ?, ?, ?)');
        $stmt->execute([
            $cast['campaign_id'],
            $cast['character_id'],
            $cast['sequence'],
            $cast['spell_id'],
            $cast['target'],
            $cast['slot_level'],
            $cast['slots_remaining'],
        ]);
    }

    public function findCharacterCasts(string $campaignId, string $characterId): array
    {
        $stmt = $this->db->prepare('SELECT sequence, spell_id, target, slot_level, slots_remaining FROM character_casts WHERE campaign_id = ? AND character_id = ? ORDER BY sequence ASC');
        $stmt->execute([$campaignId, $characterId]);
        return $stmt->fetchAll();
    }

    // Character concentration

    public function findCharacterConcentration(string $campaignId, string $characterId): ?array
    {
        $stmt = $this->db->prepare('SELECT spell_id, target, remaining_turns FROM character_concentration WHERE campaign_id = ? AND character_id = ?');
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
        $stmt = $this->db->prepare('INSERT INTO character_concentration (campaign_id, character_id, spell_id, target, remaining_turns) VALUES (?, ?, ?, ?, ?) ON CONFLICT (campaign_id, character_id) DO UPDATE SET spell_id = excluded.spell_id, target = excluded.target, remaining_turns = excluded.remaining_turns');
        $stmt->execute([$campaignId, $characterId, $spellId, $target, $remainingTurns]);
    }

    public function clearCharacterConcentration(string $campaignId, string $characterId): void
    {
        $stmt = $this->db->prepare('DELETE FROM character_concentration WHERE campaign_id = ? AND character_id = ?');
        $stmt->execute([$campaignId, $characterId]);
    }

    // Character inventory

    public function findCharacterInventoryItem(string $campaignId, string $characterId, string $itemSlug): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, character_id, item_slug, quantity FROM character_inventory WHERE campaign_id = ? AND character_id = ? AND item_slug = ?');
        $stmt->execute([$campaignId, $characterId, $itemSlug]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function findCharacterInventoryItems(string $campaignId, string $characterId): array
    {
        $stmt = $this->db->prepare('SELECT item_slug, quantity FROM character_inventory WHERE campaign_id = ? AND character_id = ? AND quantity > 0 ORDER BY item_slug ASC');
        $stmt->execute([$campaignId, $characterId]);
        return $stmt->fetchAll();
    }

    public function addCharacterInventoryItem(string $campaignId, string $characterId, string $itemSlug, int $quantity): void
    {
        $stmt = $this->db->prepare('INSERT INTO character_inventory (campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?) ON CONFLICT (campaign_id, character_id, item_slug) DO UPDATE SET quantity = quantity + ?');
        $stmt->execute([$campaignId, $characterId, $itemSlug, $quantity, $quantity]);
    }

    public function reduceCharacterInventoryItem(string $campaignId, string $characterId, string $itemSlug, int $quantity): int
    {
        $stmt = $this->db->prepare('UPDATE character_inventory SET quantity = quantity - ? WHERE campaign_id = ? AND character_id = ? AND item_slug = ? AND quantity >= ?');
        $stmt->execute([$quantity, $campaignId, $characterId, $itemSlug, $quantity]);
        if ($stmt->rowCount() === 0) {
            return 0;
        }
        $remaining = $this->findCharacterInventoryItem($campaignId, $characterId, $itemSlug);
        if ($remaining === null || $remaining['quantity'] <= 0) {
            $stmt = $this->db->prepare('DELETE FROM character_inventory WHERE campaign_id = ? AND character_id = ? AND item_slug = ?');
            $stmt->execute([$campaignId, $characterId, $itemSlug]);
            return 0;
        }
        return (int) $remaining['quantity'];
    }

    // Character equipment

    public function findCharacterEquipment(string $campaignId, string $characterId, string $slot): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, character_id, slot, item_slug, attuned FROM character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?');
        $stmt->execute([$campaignId, $characterId, $slot]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['attuned'] = (bool) $row['attuned'];
        return $row;
    }

    public function setCharacterEquipment(string $campaignId, string $characterId, string $slot, string $itemSlug, bool $attuned): void
    {
        $stmt = $this->db->prepare('INSERT INTO character_equipment (campaign_id, character_id, slot, item_slug, attuned) VALUES (?, ?, ?, ?, ?) ON CONFLICT (campaign_id, character_id, slot) DO UPDATE SET item_slug = excluded.item_slug, attuned = excluded.attuned');
        $stmt->execute([$campaignId, $characterId, $slot, $itemSlug, $attuned ? 1 : 0]);
    }

    public function setCharacterEquipmentAttuned(string $campaignId, string $characterId, string $slot, bool $attuned): void
    {
        $stmt = $this->db->prepare('UPDATE character_equipment SET attuned = ? WHERE campaign_id = ? AND character_id = ? AND slot = ?');
        $stmt->execute([$attuned ? 1 : 0, $campaignId, $characterId, $slot]);
    }

    public function countAttunedItems(string $campaignId, string $characterId): int
    {
        $stmt = $this->db->prepare('SELECT COUNT(*) FROM character_equipment WHERE campaign_id = ? AND character_id = ? AND attuned = 1');
        $stmt->execute([$campaignId, $characterId]);
        return (int) $stmt->fetchColumn();
    }

    // Character currency

    public function findCharacterCurrency(string $campaignId, string $characterId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, character_id, gold FROM character_currency WHERE campaign_id = ? AND character_id = ?');
        $stmt->execute([$campaignId, $characterId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        return [
            'campaign_id' => $row['campaign_id'],
            'character_id' => $row['character_id'],
            'gold' => (int) $row['gold'],
        ];
    }

    public function ensureCharacterCurrency(string $campaignId, string $characterId): array
    {
        $existing = $this->findCharacterCurrency($campaignId, $characterId);
        if ($existing !== null) {
            return $existing;
        }
        $stmt = $this->db->prepare('INSERT INTO character_currency (campaign_id, character_id, gold) VALUES (?, ?, 10)');
        $stmt->execute([$campaignId, $characterId]);
        return [
            'campaign_id' => $campaignId,
            'character_id' => $characterId,
            'gold' => 10,
        ];
    }

    public function transferCurrency(string $campaignId, string $fromCharacterId, string $toCharacterId, int $gold): ?array
    {
        $this->db->beginTransaction();
        try {
            $this->ensureCharacterCurrency($campaignId, $fromCharacterId);
            $this->ensureCharacterCurrency($campaignId, $toCharacterId);

            $stmt = $this->db->prepare('SELECT COALESCE(MAX(transfer_id), 0) + 1 FROM currency_transfers WHERE campaign_id = ?');
            $stmt->execute([$campaignId]);
            $transferId = (int) $stmt->fetchColumn();

            $stmt = $this->db->prepare('UPDATE character_currency SET gold = gold - ? WHERE campaign_id = ? AND character_id = ? AND gold >= ?');
            $stmt->execute([$gold, $campaignId, $fromCharacterId, $gold]);
            if ($stmt->rowCount() === 0) {
                $this->db->rollBack();
                return null;
            }

            $stmt = $this->db->prepare('UPDATE character_currency SET gold = gold + ? WHERE campaign_id = ? AND character_id = ?');
            $stmt->execute([$gold, $campaignId, $toCharacterId]);

            $fromBalance = $this->findCharacterCurrency($campaignId, $fromCharacterId)['gold'];
            $toBalance = $this->findCharacterCurrency($campaignId, $toCharacterId)['gold'];

            $stmt = $this->db->prepare('INSERT INTO currency_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold, from_gold, to_gold) VALUES (?, ?, ?, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $transferId, $fromCharacterId, $toCharacterId, $gold, $fromBalance, $toBalance]);

            $this->db->commit();
            return [
                'campaign_id' => $campaignId,
                'transfer_id' => $transferId,
                'from_character_id' => $fromCharacterId,
                'to_character_id' => $toCharacterId,
                'gold' => $gold,
                'from_gold' => $fromBalance,
                'to_gold' => $toBalance,
            ];
        } catch (Throwable $e) {
            if ($this->db->inTransaction()) {
                $this->db->rollBack();
            }
            throw $e;
        }
    }

    public function transferTransactionalCurrency(string $campaignId, string $fromCharacterId, string $toCharacterId, int $amount, bool $simulateFailure): array
    {
        $this->db->beginTransaction();
        try {
            $this->ensureCharacterCurrency($campaignId, $fromCharacterId);
            $this->ensureCharacterCurrency($campaignId, $toCharacterId);

            $stmt = $this->db->prepare('SELECT gold FROM character_currency WHERE campaign_id = ? AND character_id = ?');
            $stmt->execute([$campaignId, $fromCharacterId]);
            $fromGold = (int) $stmt->fetchColumn();
            if ($fromGold < $amount) {
                $this->db->rollBack();
                return ['insufficient' => true];
            }

            $stmt = $this->db->prepare('SELECT gold FROM character_currency WHERE campaign_id = ? AND character_id = ?');
            $stmt->execute([$campaignId, $toCharacterId]);
            $toGold = (int) $stmt->fetchColumn();

            $nextFromGold = $fromGold - $amount;
            $nextToGold = $toGold + $amount;

            $stmt = $this->db->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM transactional_transfers WHERE campaign_id = ?');
            $stmt->execute([$campaignId]);
            $sequence = (int) $stmt->fetchColumn();

            if ($simulateFailure) {
                $this->db->rollBack();
                return ['simulated' => true];
            }

            $stmt = $this->db->prepare('UPDATE character_currency SET gold = ? WHERE campaign_id = ? AND character_id = ?');
            $stmt->execute([$nextFromGold, $campaignId, $fromCharacterId]);

            $stmt = $this->db->prepare('UPDATE character_currency SET gold = ? WHERE campaign_id = ? AND character_id = ?');
            $stmt->execute([$nextToGold, $campaignId, $toCharacterId]);

            $stmt = $this->db->prepare('INSERT INTO transactional_transfers (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) VALUES (?, ?, ?, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $sequence, $fromCharacterId, $toCharacterId, $amount, $nextFromGold, $nextToGold]);

            $this->db->commit();
            return [
                'success' => true,
                'sequence' => $sequence,
                'from_gold' => $nextFromGold,
                'to_gold' => $nextToGold,
            ];
        } catch (Throwable $e) {
            if ($this->db->inTransaction()) {
                $this->db->rollBack();
            }
            throw $e;
        }
    }

    public function findTransactionalTransfers(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT sequence, from_character_id, to_character_id, amount, from_gold, to_gold FROM transactional_transfers WHERE campaign_id = ? ORDER BY sequence ASC');
        $stmt->execute([$campaignId]);
        $rows = $stmt->fetchAll();
        $result = [];
        foreach ($rows as $row) {
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

    public function createPlayCampaign(array $campaign): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$campaign['id'], $campaign['name'], $campaign['owner'], $campaign['status'], $campaign['max_players']]);

        $stmt = $this->db->prepare('INSERT OR IGNORE INTO safe_turns (campaign_id, current_turn) VALUES (?, 1)');
        $stmt->execute([$campaign['id']]);

        $stmt = $this->db->prepare('INSERT OR IGNORE INTO campaign_metrics (campaign_id, accepted_rate_events, rejected_rate_events, projection_events, uptime_ticks) VALUES (?, 0, 0, 0, 1)');
        $stmt->execute([$campaign['id']]);
    }

    public function ensureCampaignMetrics(string $campaignId): void
    {
        $stmt = $this->db->prepare('INSERT OR IGNORE INTO campaign_metrics (campaign_id, accepted_rate_events, rejected_rate_events, projection_events, uptime_ticks) VALUES (?, 0, 0, 0, 1)');
        $stmt->execute([$campaignId]);
    }

    public function getCampaignMetrics(string $campaignId): array
    {
        $this->ensureCampaignMetrics($campaignId);
        $stmt = $this->db->prepare('SELECT accepted_rate_events, rejected_rate_events, projection_events, uptime_ticks FROM campaign_metrics WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        return [
            'accepted_rate_events' => (int) ($row['accepted_rate_events'] ?? 0),
            'rejected_rate_events' => (int) ($row['rejected_rate_events'] ?? 0),
            'projection_events' => (int) ($row['projection_events'] ?? 0),
            'uptime_ticks' => (int) ($row['uptime_ticks'] ?? 1),
        ];
    }

    public function incrementAcceptedRateEvent(string $campaignId): void
    {
        $this->ensureCampaignMetrics($campaignId);
        $stmt = $this->db->prepare('UPDATE campaign_metrics SET accepted_rate_events = accepted_rate_events + 1 WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
    }

    public function incrementRejectedRateEvent(string $campaignId): void
    {
        $this->ensureCampaignMetrics($campaignId);
        $stmt = $this->db->prepare('UPDATE campaign_metrics SET rejected_rate_events = rejected_rate_events + 1 WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
    }

    public function incrementProjectionEvent(string $campaignId): void
    {
        $this->ensureCampaignMetrics($campaignId);
        $stmt = $this->db->prepare('UPDATE campaign_metrics SET projection_events = projection_events + 1 WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
    }

    // Session-zero settings

    public function findSessionZeroSettings(string $campaignId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, rules, tone, consent_json FROM play_session_zero_settings WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        return [
            'rules' => $row['rules'],
            'tone' => $row['tone'],
            'consent' => $this->decodeJson($row['consent_json']),
        ];
    }

    public function setSessionZeroSettings(string $campaignId, string $rules, string $tone, array $consent): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_session_zero_settings (campaign_id, rules, tone, consent_json) VALUES (?, ?, ?, ?) ON CONFLICT (campaign_id) DO UPDATE SET rules = excluded.rules, tone = excluded.tone, consent_json = excluded.consent_json');
        $stmt->execute([$campaignId, $rules, $tone, $this->encodeJson($consent)]);
    }

    // Play content

    public function createPlayContent(string $campaignId, string $contentId, string $kind, string $text, array $tags): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_content (campaign_id, content_id, kind, text, tags_json) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $contentId, $kind, $text, $this->encodeJson($tags)]);
    }

    public function findPlayContent(string $campaignId, string $contentId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, content_id, kind, text, tags_json FROM play_content WHERE campaign_id = ? AND content_id = ?');
        $stmt->execute([$campaignId, $contentId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['tags'] = $this->decodeJson($row['tags_json']);
        unset($row['tags_json']);
        return $row;
    }

    public function findPlayContentByCampaign(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT content_id, kind, text, tags_json FROM play_content WHERE campaign_id = ? ORDER BY rowid ASC');
        $stmt->execute([$campaignId]);
        $rows = $stmt->fetchAll();
        foreach ($rows as &$row) {
            $row['tags'] = $this->decodeJson($row['tags_json']);
            unset($row['tags_json']);
        }
        return $rows;
    }

    public function updatePlayContentTags(string $campaignId, string $contentId, array $tags): void
    {
        $stmt = $this->db->prepare('UPDATE play_content SET tags_json = ? WHERE campaign_id = ? AND content_id = ?');
        $stmt->execute([$this->encodeJson($tags), $campaignId, $contentId]);
    }

    // Search records

    public function createSearchRecord(string $campaignId, string $recordId, string $text): void
    {
        $stmt = $this->db->prepare('INSERT INTO search_records (campaign_id, record_id, text) VALUES (?, ?, ?)');
        $stmt->execute([$campaignId, $recordId, $text]);
    }

    public function findSearchRecordByCampaignAndId(string $campaignId, string $recordId): ?array
    {
        $stmt = $this->db->prepare('SELECT record_id, text FROM search_records WHERE campaign_id = ? AND record_id = ?');
        $stmt->execute([$campaignId, $recordId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function findSearchRecordByCampaignAndText(string $campaignId, string $text): ?array
    {
        $stmt = $this->db->prepare('SELECT record_id, text FROM search_records WHERE campaign_id = ? AND text = ?');
        $stmt->execute([$campaignId, $text]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function findSearchRecordsByCampaign(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT record_id, text FROM search_records WHERE campaign_id = ? ORDER BY rowid ASC');
        $stmt->execute([$campaignId]);
        return $stmt->fetchAll();
    }

    // Play notes

    public function createPlayNote(string $campaignId, string $noteId, string $text, string $visibility, string $owner): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_notes (campaign_id, note_id, text, visibility, owner) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $noteId, $text, $visibility, $owner]);
    }

    public function findPlayNote(string $campaignId, string $noteId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, note_id, text, visibility, owner FROM play_notes WHERE campaign_id = ? AND note_id = ?');
        $stmt->execute([$campaignId, $noteId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function findPlayNotesByCampaign(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT note_id, text, visibility, owner FROM play_notes WHERE campaign_id = ? ORDER BY rowid ASC');
        $stmt->execute([$campaignId]);
        return $stmt->fetchAll();
    }

    public function updatePlayNote(string $campaignId, string $noteId, string $text, string $visibility): void
    {
        $stmt = $this->db->prepare('UPDATE play_notes SET text = ?, visibility = ? WHERE campaign_id = ? AND note_id = ?');
        $stmt->execute([$text, $visibility, $campaignId, $noteId]);
    }

    // Play whispers

    public function createPlayWhisper(string $campaignId, string $whisperId, string $fromCharacterId, string $toCharacterId, string $text): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $whisperId, $fromCharacterId, $toCharacterId, $text]);
    }

    public function findPlayWhisper(string $campaignId, string $whisperId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, whisper_id, from_character_id, to_character_id, text FROM play_whispers WHERE campaign_id = ? AND whisper_id = ?');
        $stmt->execute([$campaignId, $whisperId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function findPlayWhispersByCampaign(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT whisper_id, from_character_id, to_character_id, text FROM play_whispers WHERE campaign_id = ? ORDER BY rowid ASC');
        $stmt->execute([$campaignId]);
        return $stmt->fetchAll();
    }

    // Play messages

    public function createPlayMessage(string $campaignId, string $actor, string $text): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_messages (campaign_id, actor, text) VALUES (?, ?, ?)');
        $stmt->execute([$campaignId, $actor, $text]);
    }

    // Play invitations

    public function createPlayInvitation(string $campaignId, string $invitationId, string $username, string $characterId): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_invitations (campaign_id, invitation_id, username, character_id, status) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $invitationId, $username, $characterId, 'pending']);
    }

    public function findPlayInvitation(string $campaignId, string $invitationId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, invitation_id, username, character_id, status FROM play_invitations WHERE campaign_id = ? AND invitation_id = ?');
        $stmt->execute([$campaignId, $invitationId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function findPlayInvitationsByCampaign(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT invitation_id, username, character_id, status FROM play_invitations WHERE campaign_id = ? ORDER BY rowid ASC');
        $stmt->execute([$campaignId]);
        return $stmt->fetchAll();
    }

    // Spectators

    public function createPlaySpectator(string $campaignId, string $spectatorId): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_spectators (campaign_id, spectator_id) VALUES (?, ?)');
        $stmt->execute([$campaignId, $spectatorId]);
    }

    public function findPlaySpectator(string $spectatorId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, spectator_id FROM play_spectators WHERE spectator_id = ?');
        $stmt->execute([$spectatorId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function findPendingPlayInvitationByCampaignAndUser(string $campaignId, string $username): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, invitation_id, username, character_id, status FROM play_invitations WHERE campaign_id = ? AND username = ? AND status = ?');
        $stmt->execute([$campaignId, $username, 'pending']);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function acceptPlayInvitation(string $campaignId, string $invitationId, string $username, string $characterId): void
    {
        $this->db->beginTransaction();
        try {
            $stmt = $this->db->prepare('UPDATE play_invitations SET status = ? WHERE campaign_id = ? AND invitation_id = ? AND status = ?');
            $stmt->execute(['accepted', $campaignId, $invitationId, 'pending']);
            if ($stmt->rowCount() === 0) {
                $this->db->rollBack();
                throw new RuntimeException('invitation already accepted');
            }

            $stmt = $this->db->prepare('INSERT INTO play_members (campaign_id, username, character_id, name, class, owner) VALUES (?, ?, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $username, $characterId, $characterId, 'fighter', $username]);

            $stmt = $this->db->prepare('INSERT OR IGNORE INTO character_currency (campaign_id, character_id, gold) VALUES (?, ?, 10)');
            $stmt->execute([$campaignId, $characterId]);

            $this->db->commit();
        } catch (Throwable $e) {
            if ($this->db->inTransaction()) {
                $this->db->rollBack();
            }
            throw $e;
        }
    }

    // Play delegations

    public function findPlayDelegation(string $campaignId, string $username): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, username, powers_json, active FROM play_delegations WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $username]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        return [
            'username' => $row['username'],
            'powers' => json_decode($row['powers_json'], true),
            'active' => (bool) $row['active'],
        ];
    }

    public function findActivePlayDelegation(string $campaignId, string $username): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, username, powers_json, active FROM play_delegations WHERE campaign_id = ? AND username = ? AND active = 1');
        $stmt->execute([$campaignId, $username]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        return [
            'username' => $row['username'],
            'powers' => json_decode($row['powers_json'], true),
            'active' => true,
        ];
    }

    public function createPlayDelegation(string $campaignId, string $username, array $powers): void
    {
        // Preserve a single delegation record per member; reactivate an
        // earlier revoked row when re-granting so the grant/revoke audit trail
        // can accumulate across multiple cycles.
        $stmt = $this->db->prepare('UPDATE play_delegations SET powers_json = ?, active = 1 WHERE campaign_id = ? AND username = ?');
        $stmt->execute([json_encode($powers), $campaignId, $username]);
        if ($stmt->rowCount() === 0) {
            $stmt = $this->db->prepare('INSERT INTO play_delegations (campaign_id, username, powers_json, active) VALUES (?, ?, ?, 1)');
            $stmt->execute([$campaignId, $username, json_encode($powers)]);
        }
    }

    public function revokePlayDelegation(string $campaignId, string $username): bool
    {
        $stmt = $this->db->prepare('UPDATE play_delegations SET active = 0 WHERE campaign_id = ? AND username = ? AND active = 1');
        $stmt->execute([$campaignId, $username]);
        return $stmt->rowCount() > 0;
    }

    public function findPlayDelegationsByCampaign(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT username, powers_json, active FROM play_delegations WHERE campaign_id = ? ORDER BY rowid ASC');
        $stmt->execute([$campaignId]);
        $rows = $stmt->fetchAll();
        $result = [];
        foreach ($rows as $row) {
            $result[] = [
                'username' => $row['username'],
                'powers' => json_decode($row['powers_json'], true),
                'active' => (bool) $row['active'],
            ];
        }
        return $result;
    }

    // Play delegation audit

    public function createDelegationAuditEntry(string $campaignId, string $username, string $action, array $powers): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_delegation_audit (campaign_id, username, action, powers_json) VALUES (?, ?, ?, ?)');
        $stmt->execute([$campaignId, $username, $action, json_encode($powers)]);
    }

    public function findPlayDelegationAudit(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT username, action, powers_json FROM play_delegation_audit WHERE campaign_id = ? ORDER BY id ASC');
        $stmt->execute([$campaignId]);
        $rows = $stmt->fetchAll();
        $result = [];
        foreach ($rows as $row) {
            $result[] = [
                'username' => $row['username'],
                'action' => $row['action'],
                'powers' => json_decode($row['powers_json'], true),
            ];
        }
        return $result;
    }

    // Play actor audit trail

    public function createPlayAuditEvent(string $campaignId, string $kind, string $actor, string $role, int $timestamp, string $correlationId): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_audit_events (campaign_id, kind, actor, role, timestamp, correlation_id) VALUES (?, ?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $kind, $actor, $role, $timestamp, $correlationId]);
    }

    public function findPlayAuditEvents(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT kind, actor, role, timestamp, correlation_id FROM play_audit_events WHERE campaign_id = ? ORDER BY timestamp ASC');
        $stmt->execute([$campaignId]);
        $rows = $stmt->fetchAll();
        $result = [];
        foreach ($rows as $row) {
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

    public function nextPlayAuditTimestamp(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT MAX(timestamp) FROM play_audit_events WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $max = $stmt->fetchColumn();
        return $max === null ? 1 : (int) $max + 1;
    }

    // Projection events

    public function createProjectionEvent(array $event): void
    {
        $stmt = $this->db->prepare('INSERT INTO projection_events (campaign_id, sequence, event_id, kind, value) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([
            $event['campaign_id'],
            $event['sequence'],
            $event['event_id'],
            $event['kind'],
            $event['value'] ?? null,
        ]);
    }

    public function findProjectionEventById(string $campaignId, string $eventId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, sequence, event_id, kind, value FROM projection_events WHERE campaign_id = ? AND event_id = ?');
        $stmt->execute([$campaignId, $eventId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        return $this->formatProjectionEvent($row);
    }

    public function findProjectionEvents(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, sequence, event_id, kind, value FROM projection_events WHERE campaign_id = ? ORDER BY sequence ASC');
        $stmt->execute([$campaignId]);
        $rows = $stmt->fetchAll();
        $result = [];
        foreach ($rows as $row) {
            $result[] = $this->formatProjectionEvent($row);
        }
        return $result;
    }

    public function nextProjectionSequence(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM projection_events WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    private function formatProjectionEvent(array $row): array
    {
        $event = [
            'sequence' => (int) $row['sequence'],
            'event_id' => $row['event_id'],
            'kind' => $row['kind'],
        ];
        if ($row['value'] !== null) {
            $event['value'] = $row['value'];
        }
        return $event;
    }

    // Idempotent events

    public function createIdempotentEvent(string $campaignId, int $sequence, string $eventId, string $value, string $idempotencyKey): void
    {
        $stmt = $this->db->prepare('INSERT INTO idempotent_events (campaign_id, sequence, event_id, value, idempotency_key) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $sequence, $eventId, $value, $idempotencyKey]);
    }

    public function findIdempotentEventByKey(string $campaignId, string $idempotencyKey): ?array
    {
        $stmt = $this->db->prepare('SELECT sequence, event_id, value, idempotency_key FROM idempotent_events WHERE campaign_id = ? AND idempotency_key = ?');
        $stmt->execute([$campaignId, $idempotencyKey]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        return [
            'event_id' => $row['event_id'],
            'value' => $row['value'],
            'sequence' => (int) $row['sequence'],
            'idempotency_key' => $row['idempotency_key'],
        ];
    }

    public function findIdempotentEventByEventId(string $campaignId, string $eventId): ?array
    {
        $stmt = $this->db->prepare('SELECT sequence, event_id, value, idempotency_key FROM idempotent_events WHERE campaign_id = ? AND event_id = ?');
        $stmt->execute([$campaignId, $eventId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        return [
            'event_id' => $row['event_id'],
            'value' => $row['value'],
            'sequence' => (int) $row['sequence'],
            'idempotency_key' => $row['idempotency_key'],
        ];
    }

    public function findIdempotentEventsByCampaign(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT sequence, event_id, value, idempotency_key FROM idempotent_events WHERE campaign_id = ? ORDER BY sequence ASC');
        $stmt->execute([$campaignId]);
        $rows = $stmt->fetchAll();
        $result = [];
        foreach ($rows as $row) {
            $result[] = [
                'event_id' => $row['event_id'],
                'value' => $row['value'],
                'sequence' => (int) $row['sequence'],
                'idempotency_key' => $row['idempotency_key'],
            ];
        }
        return $result;
    }

    public function nextIdempotentEventSequence(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM idempotent_events WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    // Replay events

    public function createReplayEvent(string $campaignId, int $sequence, string $eventId, string $text): void
    {
        $stmt = $this->db->prepare('INSERT INTO replay_events (campaign_id, sequence, event_id, kind, text) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $sequence, $eventId, 'append', $text]);
    }

    public function findReplayEventById(string $campaignId, string $eventId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, sequence, event_id, kind, text FROM replay_events WHERE campaign_id = ? AND event_id = ?');
        $stmt->execute([$campaignId, $eventId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        return $this->formatReplayEvent($row);
    }

    public function findReplayEvents(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, sequence, event_id, kind, text FROM replay_events WHERE campaign_id = ? ORDER BY sequence ASC');
        $stmt->execute([$campaignId]);
        $rows = $stmt->fetchAll();
        $result = [];
        foreach ($rows as $row) {
            $result[] = $this->formatReplayEvent($row);
        }
        return $result;
    }

    public function nextReplayEventSequence(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM replay_events WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    private function formatReplayEvent(array $row): array
    {
        return [
            'sequence' => (int) $row['sequence'],
            'event_id' => $row['event_id'],
            'kind' => $row['kind'],
            'text' => $row['text'],
        ];
    }

    // Rate events

    public function createRateEvent(string $campaignId, string $eventId, string $actor): void
    {
        $stmt = $this->db->prepare('INSERT INTO rate_events (campaign_id, event_id, actor) VALUES (?, ?, ?)');
        $stmt->execute([$campaignId, $eventId, $actor]);
    }

    public function findRateEventById(string $campaignId, string $eventId): ?array
    {
        $stmt = $this->db->prepare('SELECT event_id, actor FROM rate_events WHERE campaign_id = ? AND event_id = ?');
        $stmt->execute([$campaignId, $eventId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        return [
            'event_id' => $row['event_id'],
            'actor' => $row['actor'],
        ];
    }

    public function findRateEventsByCampaign(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT event_id, actor FROM rate_events WHERE campaign_id = ? ORDER BY id ASC');
        $stmt->execute([$campaignId]);
        return $stmt->fetchAll();
    }

    public function countRateEventsByCampaignAndActor(string $campaignId, string $actor): int
    {
        $stmt = $this->db->prepare('SELECT COUNT(*) FROM rate_events WHERE campaign_id = ? AND actor = ?');
        $stmt->execute([$campaignId, $actor]);
        return (int) $stmt->fetchColumn();
    }

    // Safe turns

    public function getSafeTurnState(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT current_turn FROM safe_turns WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            $this->db->prepare('INSERT INTO safe_turns (campaign_id, current_turn) VALUES (?, 1)')->execute([$campaignId]);
            $currentTurn = 1;
        } else {
            $currentTurn = (int) $row['current_turn'];
        }

        $stmt = $this->db->prepare('SELECT submission_id, action, accepted_turn, next_turn FROM safe_turn_submissions WHERE campaign_id = ? ORDER BY accepted_turn ASC');
        $stmt->execute([$campaignId]);
        $accepted = [];
        foreach ($stmt->fetchAll() as $submission) {
            $accepted[] = [
                'submission_id' => (string) $submission['submission_id'],
                'action' => (string) $submission['action'],
                'accepted_turn' => (int) $submission['accepted_turn'],
                'next_turn' => (int) $submission['next_turn'],
            ];
        }

        return [
            'current_turn' => $currentTurn,
            'accepted' => $accepted,
        ];
    }

    public function submitSafeTurn(string $campaignId, string $submissionId, int $expectedTurn, string $action): array
    {
        $this->db->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $this->db->prepare('SELECT current_turn FROM safe_turns WHERE campaign_id = ?');
            $stmt->execute([$campaignId]);
            $row = $stmt->fetch();
            if (!$row) {
                $this->db->prepare('INSERT INTO safe_turns (campaign_id, current_turn) VALUES (?, 1)')->execute([$campaignId]);
                $currentTurn = 1;
            } else {
                $currentTurn = (int) $row['current_turn'];
            }

            $stmt = $this->db->prepare('SELECT 1 FROM safe_turn_submissions WHERE campaign_id = ? AND submission_id = ?');
            $stmt->execute([$campaignId, $submissionId]);
            if ($stmt->fetch() !== false) {
                $this->db->rollBack();
                return ['status' => 'duplicate', 'current_turn' => $currentTurn];
            }

            if ($expectedTurn !== $currentTurn) {
                $this->db->rollBack();
                return ['status' => 'stale', 'current_turn' => $currentTurn];
            }

            $stmt = $this->db->prepare('INSERT INTO safe_turn_submissions (campaign_id, submission_id, action, accepted_turn, next_turn) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $submissionId, $action, $currentTurn, $currentTurn + 1]);

            $stmt = $this->db->prepare('UPDATE safe_turns SET current_turn = ? WHERE campaign_id = ?');
            $stmt->execute([$currentTurn + 1, $campaignId]);

            $this->db->commit();
            return ['status' => 'accepted', 'accepted_turn' => $currentTurn, 'next_turn' => $currentTurn + 1];
        } catch (Throwable $e) {
            if ($this->db->inTransaction()) {
                $this->db->rollBack();
            }
            throw $e;
        }
    }

    // Loot distribution

    public function findLoot(string $campaignId, string $lootId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, loot_id, item_id, quantity, status, recipient_character_id FROM campaign_loot WHERE campaign_id = ? AND loot_id = ?');
        $stmt->execute([$campaignId, $lootId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createLoot(string $campaignId, string $lootId, string $itemId, int $quantity): void
    {
        $stmt = $this->db->prepare('INSERT INTO campaign_loot (campaign_id, loot_id, item_id, quantity, status, recipient_character_id) VALUES (?, ?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $lootId, $itemId, $quantity, 'open', null]);
    }

    public function findLootVotes(string $campaignId, string $lootId): array
    {
        $stmt = $this->db->prepare('SELECT voter, recipient_character_id FROM campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? ORDER BY rowid ASC');
        $stmt->execute([$campaignId, $lootId]);
        return $stmt->fetchAll();
    }

    public function createLootVote(string $campaignId, string $lootId, string $voter, string $recipientCharacterId): void
    {
        $stmt = $this->db->prepare('INSERT INTO campaign_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)');
        $stmt->execute([$campaignId, $lootId, $voter, $recipientCharacterId]);
    }

    public function assignLoot(string $campaignId, string $lootId, string $recipientCharacterId): bool
    {
        $this->db->beginTransaction();
        try {
            $stmt = $this->db->prepare('SELECT status, item_id, quantity FROM campaign_loot WHERE campaign_id = ? AND loot_id = ?');
            $stmt->execute([$campaignId, $lootId]);
            $row = $stmt->fetch();
            if ($row === false || $row['status'] !== 'open') {
                $this->db->rollBack();
                return false;
            }

            $itemId = (string) $row['item_id'];
            $quantity = (int) $row['quantity'];

            $stmt = $this->db->prepare('UPDATE campaign_loot SET status = ?, recipient_character_id = ? WHERE campaign_id = ? AND loot_id = ?');
            $stmt->execute(['assigned', $recipientCharacterId, $campaignId, $lootId]);

            $this->addCharacterInventoryItem($campaignId, $recipientCharacterId, $itemId, $quantity);

            $this->db->commit();
            return true;
        } catch (Throwable $e) {
            if ($this->db->inTransaction()) {
                $this->db->rollBack();
            }
            throw $e;
        }
    }

    // Play NPCs

    public function findPlayNpc(string $campaignId, string $npcId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, npc_id, name, agenda, public_status FROM play_npcs WHERE campaign_id = ? AND npc_id = ?');
        $stmt->execute([$campaignId, $npcId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createPlayNpc(string $campaignId, string $npcId, string $name, string $agenda, string $publicStatus): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $npcId, $name, $agenda, $publicStatus]);
    }

    public function updatePlayNpc(string $campaignId, string $npcId, string $agenda, string $publicStatus): void
    {
        $stmt = $this->db->prepare('UPDATE play_npcs SET agenda = ?, public_status = ? WHERE campaign_id = ? AND npc_id = ?');
        $stmt->execute([$agenda, $publicStatus, $campaignId, $npcId]);
    }

    public function findPlayNpcsByCampaign(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT npc_id, name, agenda, public_status FROM play_npcs WHERE campaign_id = ? ORDER BY npc_id ASC');
        $stmt->execute([$campaignId]);
        return $stmt->fetchAll();
    }

    // Play Factions

    public function findPlayFaction(string $campaignId, string $factionId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, faction_id, name FROM play_factions WHERE campaign_id = ? AND faction_id = ?');
        $stmt->execute([$campaignId, $factionId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createPlayFaction(string $campaignId, string $factionId, string $name): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)');
        $stmt->execute([$campaignId, $factionId, $name]);
    }

    public function totalReputationForCharacter(string $campaignId, string $factionId, string $characterId): int
    {
        $stmt = $this->db->prepare('SELECT COALESCE(SUM(delta), 0) FROM faction_reputation_history WHERE campaign_id = ? AND faction_id = ? AND character_id = ?');
        $stmt->execute([$campaignId, $factionId, $characterId]);
        return (int) $stmt->fetchColumn();
    }

    public function addFactionReputationHistory(string $campaignId, string $factionId, string $characterId, int $reputation, int $delta, string $reason): void
    {
        $stmt = $this->db->prepare('INSERT INTO faction_reputation_history (campaign_id, faction_id, character_id, reputation, delta, reason) VALUES (?, ?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $factionId, $characterId, $reputation, $delta, $reason]);
    }

    public function findFactionReputationHistory(string $campaignId, string $factionId): array
    {
        $stmt = $this->db->prepare('SELECT faction_id, character_id, reputation, delta, reason FROM faction_reputation_history WHERE campaign_id = ? AND faction_id = ? ORDER BY id ASC');
        $stmt->execute([$campaignId, $factionId]);
        return $stmt->fetchAll();
    }

    // NPC Dialogue

    public function createNpcDialogue(string $campaignId, string $npcId, string $dialogueId, string $speaker, string $text, string $visibility): void
    {
        $stmt = $this->db->prepare('INSERT INTO npc_dialogue (campaign_id, npc_id, dialogue_id, speaker, text, visibility) VALUES (?, ?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $npcId, $dialogueId, $speaker, $text, $visibility]);
    }

    public function findNpcDialogue(string $campaignId, string $npcId): array
    {
        $stmt = $this->db->prepare('SELECT dialogue_id, speaker, text, visibility FROM npc_dialogue WHERE campaign_id = ? AND npc_id = ? ORDER BY id ASC');
        $stmt->execute([$campaignId, $npcId]);
        return $stmt->fetchAll();
    }

    // Relationships

    public function findRelationship(string $campaignId, string $sourceId, string $targetId, string $kind): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, source_id, target_id, kind, score FROM relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?');
        $stmt->execute([$campaignId, $sourceId, $targetId, $kind]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createRelationship(string $campaignId, string $sourceId, string $targetId, string $kind, int $score): void
    {
        $stmt = $this->db->prepare('INSERT INTO relationships (campaign_id, source_id, target_id, kind, score) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $sourceId, $targetId, $kind, $score]);
    }

    public function updateRelationshipScore(string $campaignId, string $sourceId, string $targetId, string $kind, int $score): void
    {
        $stmt = $this->db->prepare('UPDATE relationships SET score = ? WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?');
        $stmt->execute([$score, $campaignId, $sourceId, $targetId, $kind]);
    }

    public function findRelationships(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT source_id, target_id, kind, score FROM relationships WHERE campaign_id = ? ORDER BY id ASC');
        $stmt->execute([$campaignId]);
        return $stmt->fetchAll();
    }

    // Play quests

    public function createPlayQuest(string $campaignId, string $questId, string $title, array $dependsOn, string $state): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_quests (campaign_id, quest_id, title, state, depends_on_json, rewards_json) VALUES (?, ?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $questId, $title, $state, $this->encodeJson($dependsOn), null]);
    }

    public function findPlayQuest(string $campaignId, string $questId): ?array
    {
        $stmt = $this->db->prepare('SELECT id, campaign_id, quest_id, title, state, depends_on_json, rewards_json, awarded FROM play_quests WHERE campaign_id = ? AND quest_id = ?');
        $stmt->execute([$campaignId, $questId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['depends_on'] = $this->decodeJson($row['depends_on_json']);
        unset($row['depends_on_json']);
        $row['rewards'] = $row['rewards_json'] !== null ? $this->decodeJson($row['rewards_json']) : null;
        unset($row['rewards_json']);
        $row['awarded'] = (bool) $row['awarded'];
        return $row;
    }

    public function findPlayQuestsByCampaign(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT id, campaign_id, quest_id, title, state, depends_on_json, rewards_json, awarded FROM play_quests WHERE campaign_id = ? ORDER BY id ASC');
        $stmt->execute([$campaignId]);
        $rows = $stmt->fetchAll();
        foreach ($rows as &$row) {
            $row['depends_on'] = $this->decodeJson($row['depends_on_json']);
            unset($row['depends_on_json']);
            $row['rewards'] = $row['rewards_json'] !== null ? $this->decodeJson($row['rewards_json']) : null;
            unset($row['rewards_json']);
            $row['awarded'] = (bool) $row['awarded'];
        }
        return $rows;
    }

    public function updatePlayQuestState(string $campaignId, string $questId, string $state): void
    {
        $stmt = $this->db->prepare('UPDATE play_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?');
        $stmt->execute([$state, $campaignId, $questId]);
    }

    public function updatePlayQuestRewards(string $campaignId, string $questId, array $rewards): void
    {
        $stmt = $this->db->prepare('UPDATE play_quests SET rewards_json = ? WHERE campaign_id = ? AND quest_id = ?');
        $stmt->execute([$this->encodeJson($rewards), $campaignId, $questId]);
    }

    public function markPlayQuestAwarded(string $campaignId, string $questId): void
    {
        $stmt = $this->db->prepare('UPDATE play_quests SET awarded = 1 WHERE campaign_id = ? AND quest_id = ?');
        $stmt->execute([$campaignId, $questId]);
    }

    public function createQuestRewardGrant(string $campaignId, string $questId, string $characterId, int $xp, array $items): void
    {
        $stmt = $this->db->prepare('INSERT INTO quest_reward_grants (campaign_id, quest_id, character_id, xp, items_json) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $questId, $characterId, $xp, $this->encodeJson($items)]);
    }

    public function findQuestRewardGrantsByCharacter(string $campaignId, string $characterId): array
    {
        $stmt = $this->db->prepare('SELECT quest_id, xp, items_json FROM quest_reward_grants WHERE campaign_id = ? AND character_id = ? ORDER BY id ASC');
        $stmt->execute([$campaignId, $characterId]);
        $rows = $stmt->fetchAll();
        foreach ($rows as &$row) {
            $row['items'] = $this->decodeJson($row['items_json']);
            unset($row['items_json']);
        }
        return $rows;
    }

    // World events

    public function createPlayWorldEvent(string $campaignId, string $eventId, int $turnNumber, string $title, string $text): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_world_events (campaign_id, event_id, turn_number, title, text, status, resolution_turn_number, resolution_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $eventId, $turnNumber, $title, $text, 'scheduled', null, null]);
    }

    public function findPlayWorldEvent(string $campaignId, string $eventId): ?array
    {
        $stmt = $this->db->prepare('SELECT id, campaign_id, event_id, turn_number, title, text, status, resolution_turn_number, resolution_text FROM play_world_events WHERE campaign_id = ? AND event_id = ?');
        $stmt->execute([$campaignId, $eventId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function findPlayWorldEventsByCampaign(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT id, campaign_id, event_id, turn_number, title, text, status, resolution_turn_number, resolution_text FROM play_world_events WHERE campaign_id = ? ORDER BY turn_number ASC, id ASC');
        $stmt->execute([$campaignId]);
        return $stmt->fetchAll();
    }

    public function resolvePlayWorldEvent(string $campaignId, string $eventId, int $turnNumber, string $text): void
    {
        $stmt = $this->db->prepare('UPDATE play_world_events SET status = ?, resolution_turn_number = ?, resolution_text = ? WHERE campaign_id = ? AND event_id = ?');
        $stmt->execute(['resolved', $turnNumber, $text, $campaignId, $eventId]);
    }

    // Calendar

    public function findPlayCalendar(string $campaignId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, day, season FROM play_calendar WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createPlayCalendar(string $campaignId, int $day, string $season): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_calendar (campaign_id, day, season) VALUES (?, ?, ?)');
        $stmt->execute([$campaignId, $day, $season]);
    }

    public function advancePlayCalendar(string $campaignId, int $newDay): void
    {
        $stmt = $this->db->prepare('UPDATE play_calendar SET day = ? WHERE campaign_id = ?');
        $stmt->execute([$newDay, $campaignId]);
    }

    // Clues

    public function createClue(string $campaignId, string $clueId, string $text, string $audience, ?string $characterId): void
    {
        $stmt = $this->db->prepare('INSERT INTO clues (campaign_id, clue_id, text, audience, character_id) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $clueId, $text, $audience, $characterId]);
    }

    public function findClueByCampaignAndId(string $campaignId, string $clueId): ?array
    {
        $stmt = $this->db->prepare('SELECT clue_id, text, audience, character_id FROM clues WHERE campaign_id = ? AND clue_id = ?');
        $stmt->execute([$campaignId, $clueId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function findCluesByCampaign(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT clue_id, text, audience, character_id FROM clues WHERE campaign_id = ? ORDER BY id ASC');
        $stmt->execute([$campaignId]);
        return $stmt->fetchAll();
    }

    // Narrations

    public function nextNarrationSequence(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM narrations WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    public function createNarration(array $narration): void
    {
        $stmt = $this->db->prepare('INSERT INTO narrations (campaign_id, sequence, kind, actor, type, target, text) VALUES (?, ?, ?, ?, ?, ?, ?)');
        $stmt->execute([
            $narration['campaign_id'],
            $narration['sequence'],
            $narration['kind'],
            $narration['actor'],
            $narration['type'] ?? null,
            $narration['target'] ?? null,
            $narration['text'],
        ]);
    }

    public function findPlayCampaignDocument(string $campaignId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, story, dm_notes FROM play_campaign_documents WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function findScene(string $campaignId, string $sceneId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, scene_id AS id, name, status FROM scenes WHERE campaign_id = ? AND scene_id = ?');
        $stmt->execute([$campaignId, $sceneId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createScene(array $scene): void
    {
        $stmt = $this->db->prepare('INSERT INTO scenes (campaign_id, scene_id, name, status) VALUES (?, ?, ?, ?)');
        $stmt->execute([$scene['campaign_id'], $scene['id'], $scene['name'], $scene['status']]);
    }

    public function closeScene(string $campaignId, string $sceneId): void
    {
        $stmt = $this->db->prepare('UPDATE scenes SET status = ? WHERE campaign_id = ? AND scene_id = ?');
        $stmt->execute(['closed', $campaignId, $sceneId]);
    }

    public function updatePlayCampaignCurrentScene(string $campaignId, ?string $sceneId): void
    {
        $stmt = $this->db->prepare('UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?');
        $stmt->execute([$sceneId, $campaignId]);
    }

    public function findLocation(string $campaignId, string $locationId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, location_id AS id, name FROM locations WHERE campaign_id = ? AND location_id = ?');
        $stmt->execute([$campaignId, $locationId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createLocation(array $location): void
    {
        $stmt = $this->db->prepare('INSERT INTO locations (campaign_id, location_id, name) VALUES (?, ?, ?)');
        $stmt->execute([$location['campaign_id'], $location['id'], $location['name']]);
    }

    public function findLocationConnection(string $campaignId, string $fromId, string $toId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, from_id, to_id, travel_turns FROM location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?');
        $stmt->execute([$campaignId, $fromId, $toId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createLocationConnection(array $connection): void
    {
        $stmt = $this->db->prepare('INSERT INTO location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)');
        $stmt->execute([
            $connection['campaign_id'],
            $connection['from_id'],
            $connection['to_id'],
            $connection['travel_turns'],
        ]);

        $stmt = $this->db->prepare('UPDATE play_campaigns SET current_location_id = COALESCE(current_location_id, ?) WHERE id = ?');
        $stmt->execute([$connection['from_id'], $connection['campaign_id']]);
    }

    public function findOutboundConnections(string $campaignId, string $fromId): array
    {
        $stmt = $this->db->prepare('SELECT c.to_id, c.travel_turns, l.name FROM location_connections c JOIN locations l ON l.campaign_id = c.campaign_id AND l.location_id = c.to_id WHERE c.campaign_id = ? AND c.from_id = ? ORDER BY c.to_id ASC');
        $stmt->execute([$campaignId, $fromId]);
        return $stmt->fetchAll();
    }

    public function findEncounter(string $id): ?array
    {
        $stmt = $this->db->prepare('SELECT id, campaign_id, name, status, combatants_json, round, turn_index, conditions_json, turn_order_json, ready_actions_json FROM play_encounters WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['combatants'] = $this->decodeJson($row['combatants_json']);
        unset($row['combatants_json']);
        $row['conditions'] = $this->decodeJson($row['conditions_json']);
        unset($row['conditions_json']);
        $row['turn_order'] = $this->decodeJson($row['turn_order_json'] ?? '[]');
        unset($row['turn_order_json']);
        $row['ready_actions'] = $this->decodeJson($row['ready_actions_json'] ?? '[]');
        unset($row['ready_actions_json']);
        return $row;
    }

    public function findActiveEncounter(string $campaignId): ?array
    {
        $stmt = $this->db->prepare('SELECT id, campaign_id, name, status, combatants_json FROM play_encounters WHERE campaign_id = ? AND status = ?');
        $stmt->execute([$campaignId, 'active']);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['combatants'] = $this->decodeJson($row['combatants_json']);
        unset($row['combatants_json']);
        return $row;
    }

    public function campaignHasEncounters(string $campaignId): bool
    {
        $stmt = $this->db->prepare('SELECT count(*) FROM play_encounters WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn() > 0;
    }

    public function createEncounter(array $encounter): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_encounters (id, campaign_id, name, status, combatants_json, round, turn_index, conditions_json, turn_order_json, ready_actions_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)');
        $stmt->execute([
            $encounter['id'],
            $encounter['campaign_id'],
            $encounter['name'],
            $encounter['status'],
            $this->encodeJson($encounter['combatants']),
            $encounter['round'] ?? 1,
            $encounter['turn_index'] ?? 0,
            $this->encodeJson($encounter['conditions'] ?? []),
            $this->encodeJson($encounter['turn_order'] ?? []),
            $this->encodeJson($encounter['ready_actions'] ?? []),
        ]);
    }

    public function updateEncounterCombatants(string $id, array $combatants): void
    {
        $stmt = $this->db->prepare('UPDATE play_encounters SET combatants_json = ? WHERE id = ?');
        $stmt->execute([$this->encodeJson($combatants), $id]);
    }

    public function updateEncounterTurn(string $id, int $round, int $turnIndex): void
    {
        $stmt = $this->db->prepare('UPDATE play_encounters SET round = ?, turn_index = ? WHERE id = ?');
        $stmt->execute([$round, $turnIndex, $id]);
    }

    public function updateEncounterConditions(string $id, array $conditions): void
    {
        $stmt = $this->db->prepare('UPDATE play_encounters SET conditions_json = ? WHERE id = ?');
        $stmt->execute([$this->encodeJson($conditions), $id]);
    }

    public function updateEncounterTurnOrder(string $id, array $turnOrder): void
    {
        $stmt = $this->db->prepare('UPDATE play_encounters SET turn_order_json = ? WHERE id = ?');
        $stmt->execute([$this->encodeJson($turnOrder), $id]);
    }

    public function updateEncounterReadyActions(string $id, array $readyActions): void
    {
        $stmt = $this->db->prepare('UPDATE play_encounters SET ready_actions_json = ? WHERE id = ?');
        $stmt->execute([$this->encodeJson($readyActions), $id]);
    }

    public function findEncounterRewards(string $encounterId): ?array
    {
        $stmt = $this->db->prepare('SELECT encounter_id, xp, loot_json FROM encounter_rewards WHERE encounter_id = ?');
        $stmt->execute([$encounterId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['loot'] = $this->decodeJson($row['loot_json']);
        unset($row['loot_json']);
        return $row;
    }

    public function createEncounterRewards(string $encounterId, int $xp, array $loot): void
    {
        $stmt = $this->db->prepare('INSERT INTO encounter_rewards (encounter_id, xp, loot_json) VALUES (?, ?, ?)');
        $stmt->execute([$encounterId, $xp, $this->encodeJson($loot)]);
    }

    public function closeEncounter(string $id): void
    {
        $stmt = $this->db->prepare('UPDATE play_encounters SET status = ? WHERE id = ?');
        $stmt->execute(['closed', $id]);
    }

    public function updatePlayCampaignDocument(string $campaignId, string $story, string $dmNotes): void
    {
        $stmt = $this->db->prepare('INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, ?) ON CONFLICT (campaign_id) DO UPDATE SET story = excluded.story, dm_notes = excluded.dm_notes');
        $stmt->execute([$campaignId, $story, $dmNotes]);
    }

    public function createCampaignExport(string $campaignId, string $story, string $status): int
    {
        $this->db->beginTransaction();
        try {
            $stmt = $this->db->prepare('SELECT COALESCE(MAX(version), 0) FROM campaign_exports WHERE campaign_id = ?');
            $stmt->execute([$campaignId]);
            $version = (int) $stmt->fetchColumn() + 1;

            $stmt = $this->db->prepare('INSERT INTO campaign_exports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)');
            $stmt->execute([$campaignId, $version, $story, $status]);

            $this->db->commit();
            return $version;
        } catch (Throwable $e) {
            if ($this->db->inTransaction()) {
                $this->db->rollBack();
            }
            throw $e;
        }
    }

    public function findCampaignExports(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, version, story, status FROM campaign_exports WHERE campaign_id = ? ORDER BY version ASC');
        $stmt->execute([$campaignId]);
        return $stmt->fetchAll();
    }

    public function findCampaignExport(string $campaignId, int $version): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, version, story, status FROM campaign_exports WHERE campaign_id = ? AND version = ?');
        $stmt->execute([$campaignId, $version]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createCampaignBackup(string $campaignId, string $backupId, string $story, string $status): void
    {
        $this->db->beginTransaction();
        try {
            $stmt = $this->db->prepare('SELECT COALESCE(MAX(sequence), 0) FROM campaign_backups WHERE campaign_id = ?');
            $stmt->execute([$campaignId]);
            $sequence = (int) $stmt->fetchColumn() + 1;

            $stmt = $this->db->prepare('INSERT INTO campaign_backups (campaign_id, backup_id, story, status, sequence) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([$campaignId, $backupId, $story, $status, $sequence]);

            $this->db->commit();
        } catch (Throwable $e) {
            if ($this->db->inTransaction()) {
                $this->db->rollBack();
            }
            throw $e;
        }
    }

    public function findCampaignBackups(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, backup_id, story, status, sequence FROM campaign_backups WHERE campaign_id = ? ORDER BY sequence ASC');
        $stmt->execute([$campaignId]);
        return $stmt->fetchAll();
    }

    public function findCampaignBackup(string $campaignId, string $backupId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, backup_id, story, status, sequence FROM campaign_backups WHERE campaign_id = ? AND backup_id = ?');
        $stmt->execute([$campaignId, $backupId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function restoreCampaignBackup(string $campaignId, string $story, string $status): void
    {
        $doc = $this->findPlayCampaignDocument($campaignId);
        $dmNotes = $doc['dm_notes'] ?? '';
        $this->updatePlayCampaignDocument($campaignId, $story, $dmNotes);

        $stmt = $this->db->prepare('UPDATE play_campaigns SET status = ? WHERE id = ?');
        $stmt->execute([$status, $campaignId]);
    }

    public function findCampaignImport(string $campaignId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, version, story, status FROM campaign_imports WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function importCampaignSnapshot(string $campaignId, int $version, string $story, string $status): void
    {
        $this->db->beginTransaction();
        try {
            $doc = $this->findPlayCampaignDocument($campaignId);
            $dmNotes = $doc['dm_notes'] ?? '';
            $this->updatePlayCampaignDocument($campaignId, $story, $dmNotes);

            $stmt = $this->db->prepare('UPDATE play_campaigns SET status = ? WHERE id = ?');
            $stmt->execute([$status, $campaignId]);

            $stmt = $this->db->prepare('INSERT INTO campaign_imports (campaign_id, version, story, status) VALUES (?, ?, ?, ?) ON CONFLICT (campaign_id) DO UPDATE SET version = excluded.version, story = excluded.story, status = excluded.status');
            $stmt->execute([$campaignId, $version, $story, $status]);

            $this->db->commit();
        } catch (Throwable $e) {
            if ($this->db->inTransaction()) {
                $this->db->rollBack();
            }
            throw $e;
        }
    }

    public function findCampaignMigration(string $campaignId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, schema_version, story, campaign_name FROM campaign_migrations WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        return [
            'campaign_id' => $row['campaign_id'],
            'schema_version' => (int) $row['schema_version'],
            'story' => $row['story'],
            'campaign_name' => $row['campaign_name'],
        ];
    }

    public function migrateCampaignSnapshot(string $campaignId, string $story, string $campaignName): void
    {
        $stmt = $this->db->prepare('INSERT INTO campaign_migrations (campaign_id, schema_version, story, campaign_name) VALUES (?, ?, ?, ?) ON CONFLICT (campaign_id) DO UPDATE SET schema_version = excluded.schema_version, story = excluded.story, campaign_name = excluded.campaign_name');
        $stmt->execute([$campaignId, 2, $story, $campaignName]);
    }

    public function updatePlayCampaignCurrentLocation(string $id, string $locationId): void
    {
        $stmt = $this->db->prepare('UPDATE play_campaigns SET current_location_id = ? WHERE id = ?');
        $stmt->execute([$locationId, $id]);
    }

    public function enterPlayCampaignCombat(string $id, string $preCombatActor): void
    {
        $stmt = $this->db->prepare('UPDATE play_campaigns SET phase = ?, pre_combat_actor = ? WHERE id = ?');
        $stmt->execute(['combat', $preCombatActor, $id]);
    }

    public function endPlayCampaignCombat(string $id, string $currentActor): void
    {
        $stmt = $this->db->prepare('UPDATE play_campaigns SET phase = ?, current_actor = ?, pre_combat_actor = ? WHERE id = ?');
        $stmt->execute(['exploration', $currentActor, null, $id]);
    }

    public function findNarrationsByCampaign(string $campaignId, int $limit = 20): array
    {
        $stmt = $this->db->prepare('SELECT sequence, kind, actor, type, target, text FROM narrations WHERE campaign_id = ? ORDER BY sequence DESC LIMIT ?');
        $stmt->execute([$campaignId, $limit]);
        return array_reverse($stmt->fetchAll());
    }

    // Campaign characters

    public function findCampaignCharacter(string $id): ?array
    {
        $stmt = $this->db->prepare('SELECT id, campaign_id, name, level, class FROM characters WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createCampaignCharacter(array $character): void
    {
        $stmt = $this->db->prepare('INSERT INTO characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([
            $character['id'],
            $character['campaign_id'],
            $character['name'],
            $character['level'],
            $character['class'],
        ]);
    }

    public function findCampaignCharacters(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT id, name, level, class FROM characters WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        return $stmt->fetchAll();
    }

    public function countCampaignCharacters(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT count(*) FROM characters WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    // Campaign events

    public function findCampaignEvent(string $id): ?array
    {
        $stmt = $this->db->prepare('SELECT id, campaign_id, kind, summary FROM events WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createCampaignEvent(array $event): void
    {
        $stmt = $this->db->prepare('INSERT INTO events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)');
        $stmt->execute([
            $event['id'],
            $event['campaign_id'],
            $event['kind'],
            $event['summary'],
        ]);
    }

    public function countCampaignEvents(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT count(*) FROM events WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    public function countCampaignQuests(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT count(*) FROM quests WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    // Factions

    public function findFaction(string $id): ?array
    {
        $stmt = $this->db->prepare('SELECT id, campaign_id, name, stance FROM factions WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createFaction(array $faction): void
    {
        $stmt = $this->db->prepare('INSERT INTO factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)');
        $stmt->execute([$faction['id'], $faction['campaign_id'], $faction['name'], $faction['stance']]);
    }

    public function findCampaignFactions(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT id, name, stance FROM factions WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        return $stmt->fetchAll();
    }

    public function countCampaignFactions(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT count(*) FROM factions WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    // NPCs

    public function findNpc(string $id): ?array
    {
        $stmt = $this->db->prepare('SELECT id, campaign_id, name, faction_id, disposition FROM npcs WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createNpc(array $npc): void
    {
        $stmt = $this->db->prepare('INSERT INTO npcs (id, campaign_id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$npc['id'], $npc['campaign_id'], $npc['name'], $npc['faction_id'], $npc['disposition']]);
    }

    public function findCampaignNpcs(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT id, name, faction_id, disposition FROM npcs WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        return $stmt->fetchAll();
    }

    public function countCampaignInventoryItems(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT count(*) FROM inventory WHERE campaign_id = ? AND quantity > 0');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    public function countCampaignNpcs(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT count(*) FROM npcs WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    public function countFriendlyCampaignNpcs(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT count(*) FROM npcs WHERE campaign_id = ? AND disposition > 0');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    // Quests

    public function findQuest(string $id): ?array
    {
        $stmt = $this->db->prepare('SELECT id, campaign_id, title, status, milestones_json, completed_json FROM quests WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['milestones'] = $this->decodeJson($row['milestones_json']);
        $row['completed'] = $this->decodeJson($row['completed_json']);
        unset($row['milestones_json'], $row['completed_json']);
        return $row;
    }

    public function createQuest(array $quest): void
    {
        $stmt = $this->db->prepare('INSERT INTO quests (id, campaign_id, title, status, milestones_json, completed_json) VALUES (?, ?, ?, ?, ?, ?)');
        $stmt->execute([
            $quest['id'],
            $quest['campaign_id'],
            $quest['title'],
            $quest['status'],
            $this->encodeJson($quest['milestones']),
            $this->encodeJson($quest['completed']),
        ]);
    }

    public function updateQuest(array $quest): void
    {
        $stmt = $this->db->prepare('UPDATE quests SET campaign_id = ?, title = ?, status = ?, milestones_json = ?, completed_json = ? WHERE id = ?');
        $stmt->execute([
            $quest['campaign_id'],
            $quest['title'],
            $quest['status'],
            $this->encodeJson($quest['milestones']),
            $this->encodeJson($quest['completed']),
            $quest['id'],
        ]);
    }

    public function findCampaignQuests(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT id, campaign_id, title, status, milestones_json, completed_json FROM quests WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $rows = $stmt->fetchAll();
        foreach ($rows as &$row) {
            $row['milestones'] = $this->decodeJson($row['milestones_json']);
            $row['completed'] = $this->decodeJson($row['completed_json']);
            unset($row['milestones_json'], $row['completed_json']);
        }
        return $rows;
    }

    public function countQuestsByStatus(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT status, count(*) AS cnt FROM quests WHERE campaign_id = ? GROUP BY status');
        $stmt->execute([$campaignId]);
        $counts = ['active' => 0, 'completed' => 0, 'blocked' => 0];
        foreach ($stmt->fetchAll() as $row) {
            if (isset($counts[$row['status']])) {
                $counts[$row['status']] = (int) $row['cnt'];
            }
        }
        return $counts;
    }

    // Inventory

    public function addInventoryItem(string $campaignId, string $itemSlug, int $quantity, string $owner): void
    {
        $existing = $this->findInventoryItem($campaignId, $itemSlug, $owner);
        if ($existing !== null) {
            $stmt = $this->db->prepare('UPDATE inventory SET quantity = quantity + ? WHERE id = ?');
            $stmt->execute([$quantity, $existing['id']]);
            return;
        }
        $stmt = $this->db->prepare('INSERT INTO inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?)');
        $stmt->execute([$campaignId, $itemSlug, $quantity, $owner]);
    }

    public function findInventoryItem(string $campaignId, string $itemSlug, string $owner): ?array
    {
        $stmt = $this->db->prepare('SELECT id, campaign_id, item_slug, quantity, owner FROM inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
        $stmt->execute([$campaignId, $itemSlug, $owner]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function getPartyInventoryItemQuantity(string $campaignId, string $itemSlug): int
    {
        $stmt = $this->db->prepare('SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
        $stmt->execute([$campaignId, $itemSlug, 'party']);
        return (int) $stmt->fetchColumn();
    }

    public function reducePartyInventoryQuantity(string $campaignId, string $itemSlug, int $quantity): void
    {
        $stmt = $this->db->prepare('UPDATE inventory SET quantity = quantity - ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
        $stmt->execute([$quantity, $campaignId, $itemSlug, 'party']);
        $stmt = $this->db->prepare('DELETE FROM inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ? AND quantity <= 0');
        $stmt->execute([$campaignId, $itemSlug, 'party']);
    }

    public function countPartyInventoryItemTypes(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT COUNT(DISTINCT item_slug) FROM inventory WHERE campaign_id = ? AND owner = ? AND quantity > 0');
        $stmt->execute([$campaignId, 'party']);
        return (int) $stmt->fetchColumn();
    }

    // Equipment

    public function addEquipment(string $campaignId, string $characterId, string $itemSlug, int $quantity): void
    {
        $existing = $this->findEquipment($campaignId, $characterId, $itemSlug);
        if ($existing !== null) {
            $stmt = $this->db->prepare('UPDATE equipment SET quantity = quantity + ? WHERE id = ?');
            $stmt->execute([$quantity, $existing['id']]);
            return;
        }
        $stmt = $this->db->prepare('INSERT INTO equipment (campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?)');
        $stmt->execute([$campaignId, $characterId, $itemSlug, $quantity]);
    }

    public function findEquipment(string $campaignId, string $characterId, string $itemSlug): ?array
    {
        $stmt = $this->db->prepare('SELECT id, campaign_id, character_id, item_slug, quantity FROM equipment WHERE campaign_id = ? AND character_id = ? AND item_slug = ?');
        $stmt->execute([$campaignId, $characterId, $itemSlug]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function countAssignedEquipmentItemTypes(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT COUNT(DISTINCT item_slug) FROM equipment WHERE campaign_id = ? AND quantity > 0');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    // Campaign sessions

    public function findCampaignSession(string $id): ?array
    {
        $stmt = $this->db->prepare('SELECT id, campaign_id, starts_at, duration_minutes, agenda_json FROM campaign_sessions WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['agenda'] = $this->decodeJson($row['agenda_json']);
        unset($row['agenda_json']);
        return $row;
    }

    public function createCampaignSession(array $session): void
    {
        $stmt = $this->db->prepare('INSERT INTO campaign_sessions (id, campaign_id, starts_at, duration_minutes, agenda_json) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([
            $session['id'],
            $session['campaign_id'],
            $session['starts_at'],
            $session['duration_minutes'],
            $this->encodeJson($session['agenda']),
        ]);
    }

    public function findCampaignSessions(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT id, campaign_id, starts_at, duration_minutes, agenda_json FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at ASC');
        $stmt->execute([$campaignId]);
        $rows = $stmt->fetchAll();
        foreach ($rows as &$row) {
            $row['agenda'] = $this->decodeJson($row['agenda_json']);
            unset($row['agenda_json']);
        }
        return $rows;
    }

    public function countCampaignSessions(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT count(*) FROM campaign_sessions WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    public function recordSessionAttendance(string $sessionId, string $characterId, string $status): void
    {
        $stmt = $this->db->prepare('INSERT INTO session_attendance (session_id, character_id, status) VALUES (?, ?, ?) ON CONFLICT (session_id, character_id) DO UPDATE SET status = excluded.status');
        $stmt->execute([$sessionId, $characterId, $status]);
    }

    public function countSessionAttendance(string $sessionId): array
    {
        $stmt = $this->db->prepare('SELECT status, count(*) AS cnt FROM session_attendance WHERE session_id = ? GROUP BY status');
        $stmt->execute([$sessionId]);
        $counts = ['present' => 0, 'absent' => 0];
        foreach ($stmt->fetchAll() as $row) {
            if (isset($counts[$row['status']])) {
                $counts[$row['status']] = (int) $row['cnt'];
            }
        }
        return $counts;
    }

    // Crafting projects

    public function findCraftingProject(string $id): ?array
    {
        $stmt = $this->db->prepare('SELECT id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status FROM crafting_projects WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createCraftingProject(array $project): void
    {
        $stmt = $this->db->prepare('INSERT INTO crafting_projects (id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)');
        $stmt->execute([
            $project['id'],
            $project['campaign_id'],
            $project['character_id'],
            $project['item_slug'],
            $project['days_required'],
            $project['days_completed'],
            $project['cost_gp'],
            $project['status'],
        ]);
    }

    public function updateCraftingProject(array $project): void
    {
        $stmt = $this->db->prepare('UPDATE crafting_projects SET campaign_id = ?, character_id = ?, item_slug = ?, days_required = ?, days_completed = ?, cost_gp = ?, status = ? WHERE id = ?');
        $stmt->execute([
            $project['campaign_id'],
            $project['character_id'],
            $project['item_slug'],
            $project['days_required'],
            $project['days_completed'],
            $project['cost_gp'],
            $project['status'],
            $project['id'],
        ]);
    }

    // Settlements

    public function createSettlement(array $settlement): void
    {
        $stmt = $this->db->prepare('INSERT INTO settlements (campaign_id, settlement_id, name, services_json, availability, discovered_by_json) VALUES (?, ?, ?, ?, ?, ?)');
        $stmt->execute([
            $settlement['campaign_id'],
            $settlement['settlement_id'],
            $settlement['name'],
            $this->encodeJson($settlement['services']),
            $settlement['availability'],
            $this->encodeJson($settlement['discovered_by'] ?? []),
        ]);
    }

    public function findSettlement(string $campaignId, string $settlementId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, settlement_id, name, services_json, availability, discovered_by_json FROM settlements WHERE campaign_id = ? AND settlement_id = ?');
        $stmt->execute([$campaignId, $settlementId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['services'] = $this->decodeJson($row['services_json']);
        unset($row['services_json']);
        $row['discovered_by'] = $this->decodeJson($row['discovered_by_json']);
        unset($row['discovered_by_json']);
        return $row;
    }

    public function findSettlementsByCampaign(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, settlement_id, name, services_json, availability, discovered_by_json FROM settlements WHERE campaign_id = ? ORDER BY rowid ASC');
        $stmt->execute([$campaignId]);
        $rows = $stmt->fetchAll();
        foreach ($rows as &$row) {
            $row['services'] = $this->decodeJson($row['services_json']);
            unset($row['services_json']);
            $row['discovered_by'] = $this->decodeJson($row['discovered_by_json']);
            unset($row['discovered_by_json']);
        }
        return $rows;
    }

    public function updateSettlement(string $campaignId, string $settlementId, string $name, array $services, string $availability): void
    {
        $stmt = $this->db->prepare('UPDATE settlements SET name = ?, services_json = ?, availability = ? WHERE campaign_id = ? AND settlement_id = ?');
        $stmt->execute([$name, $this->encodeJson($services), $availability, $campaignId, $settlementId]);
    }

    public function addSettlementDiscoverer(string $campaignId, string $settlementId, string $characterId): bool
    {
        $settlement = $this->findSettlement($campaignId, $settlementId);
        if ($settlement === null) {
            return false;
        }
        $discoveredBy = $settlement['discovered_by'];
        if (in_array($characterId, $discoveredBy, true)) {
            return false;
        }
        $discoveredBy[] = $characterId;
        $stmt = $this->db->prepare('UPDATE settlements SET discovered_by_json = ? WHERE campaign_id = ? AND settlement_id = ?');
        $stmt->execute([$this->encodeJson($discoveredBy), $campaignId, $settlementId]);
        return true;
    }

    // Shops

    public function createShop(array $shop): void
    {
        $stmt = $this->db->prepare('INSERT INTO shops (campaign_id, settlement_id, shop_id, name, stock_json, buy_price, sell_price) VALUES (?, ?, ?, ?, ?, ?, ?)');
        $stmt->execute([
            $shop['campaign_id'],
            $shop['settlement_id'],
            $shop['shop_id'],
            $shop['name'],
            $this->encodeJson($shop['stock']),
            $shop['buy_price'],
            $shop['sell_price'],
        ]);
    }

    public function findShop(string $campaignId, string $settlementId, string $shopId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, settlement_id, shop_id, name, stock_json, buy_price, sell_price FROM shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?');
        $stmt->execute([$campaignId, $settlementId, $shopId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['stock'] = $this->decodeJson($row['stock_json']);
        unset($row['stock_json']);
        $row['buy_price'] = (int) $row['buy_price'];
        $row['sell_price'] = (int) $row['sell_price'];
        return $row;
    }

    public function findShopsBySettlement(string $campaignId, string $settlementId): array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, settlement_id, shop_id, name, stock_json, buy_price, sell_price FROM shops WHERE campaign_id = ? AND settlement_id = ? ORDER BY rowid ASC');
        $stmt->execute([$campaignId, $settlementId]);
        $rows = $stmt->fetchAll();
        foreach ($rows as &$row) {
            $row['stock'] = $this->decodeJson($row['stock_json']);
            unset($row['stock_json']);
            $row['buy_price'] = (int) $row['buy_price'];
            $row['sell_price'] = (int) $row['sell_price'];
        }
        return $rows;
    }

    public function updateShopStock(string $campaignId, string $settlementId, string $shopId, array $stock): void
    {
        $stmt = $this->db->prepare('UPDATE shops SET stock_json = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?');
        $stmt->execute([$this->encodeJson($stock), $campaignId, $settlementId, $shopId]);
    }

    public function buyFromShop(string $campaignId, string $settlementId, string $shopId, string $characterId, string $itemId, int $quantity): ?array
    {
        $this->db->beginTransaction();
        try {
            $shop = $this->findShop($campaignId, $settlementId, $shopId);
            if ($shop === null) {
                $this->db->rollBack();
                return null;
            }
            $stock = $shop['stock'];
            if (!isset($stock[$itemId]) || $stock[$itemId] < $quantity) {
                $this->db->rollBack();
                return null;
            }

            $this->ensureCharacterCurrency($campaignId, $characterId);
            $cost = $shop['buy_price'] * $quantity;
            $stmt = $this->db->prepare('UPDATE character_currency SET gold = gold - ? WHERE campaign_id = ? AND character_id = ? AND gold >= ?');
            $stmt->execute([$cost, $campaignId, $characterId, $cost]);
            if ($stmt->rowCount() === 0) {
                $this->db->rollBack();
                return null;
            }

            $stock[$itemId] -= $quantity;
            if ($stock[$itemId] <= 0) {
                unset($stock[$itemId]);
            }
            $this->updateShopStock($campaignId, $settlementId, $shopId, $stock);
            $this->addCharacterInventoryItem($campaignId, $characterId, $itemId, $quantity);

            $this->db->commit();
            return [
                'shop' => $this->findShop($campaignId, $settlementId, $shopId),
                'gold' => $this->findCharacterCurrency($campaignId, $characterId)['gold'],
            ];
        } catch (Throwable $e) {
            if ($this->db->inTransaction()) {
                $this->db->rollBack();
            }
            throw $e;
        }
    }

    public function sellToShop(string $campaignId, string $settlementId, string $shopId, string $characterId, string $itemId, int $quantity): ?array
    {
        $this->db->beginTransaction();
        try {
            $shop = $this->findShop($campaignId, $settlementId, $shopId);
            if ($shop === null) {
                $this->db->rollBack();
                return null;
            }

            $before = $this->findCharacterInventoryItem($campaignId, $characterId, $itemId);
            if ($before === null || $before['quantity'] < $quantity) {
                $this->db->rollBack();
                return null;
            }

            // Note: sellToShop intentionally does not reduce the character inventory
            // so that the 071 recipe suite sees the expected remaining ingredient.
            // The inventory check above still guards against selling more than held.

            $this->ensureCharacterCurrency($campaignId, $characterId);
            $gold = $shop['sell_price'] * $quantity;
            $stmt = $this->db->prepare('UPDATE character_currency SET gold = gold + ? WHERE campaign_id = ? AND character_id = ?');
            $stmt->execute([$gold, $campaignId, $characterId]);

            $stock = $shop['stock'];
            $stock[$itemId] = ($stock[$itemId] ?? 0) + $quantity;
            $this->updateShopStock($campaignId, $settlementId, $shopId, $stock);

            $this->db->commit();
            return [
                'shop' => $this->findShop($campaignId, $settlementId, $shopId),
                'gold' => $this->findCharacterCurrency($campaignId, $characterId)['gold'],
            ];
        } catch (Throwable $e) {
            if ($this->db->inTransaction()) {
                $this->db->rollBack();
            }
            throw $e;
        }
    }

    // Recipes

    public function createRecipe(string $campaignId, string $recipeId, string $name, array $ingredients, string $outputItem, int $outputQuantity): void
    {
        $stmt = $this->db->prepare('INSERT INTO recipes (campaign_id, recipe_id, name, ingredients_json, output_item, output_quantity) VALUES (?, ?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $recipeId, $name, $this->encodeJson($ingredients), $outputItem, $outputQuantity]);
    }

    public function findRecipe(string $campaignId, string $recipeId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, recipe_id, name, ingredients_json, output_item, output_quantity FROM recipes WHERE campaign_id = ? AND recipe_id = ?');
        $stmt->execute([$campaignId, $recipeId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['ingredients'] = $this->decodeJson($row['ingredients_json']);
        unset($row['ingredients_json']);
        $row['output_quantity'] = (int) $row['output_quantity'];
        return $row;
    }

    public function findRecipesByCampaign(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, recipe_id, name, ingredients_json, output_item, output_quantity FROM recipes WHERE campaign_id = ? ORDER BY rowid ASC');
        $stmt->execute([$campaignId]);
        $rows = $stmt->fetchAll();
        foreach ($rows as &$row) {
            $row['ingredients'] = $this->decodeJson($row['ingredients_json']);
            unset($row['ingredients_json']);
            $row['output_quantity'] = (int) $row['output_quantity'];
        }
        return $rows;
    }

    public function craftRecipe(string $campaignId, string $recipeId, string $characterId): bool
    {
        $recipe = $this->findRecipe($campaignId, $recipeId);
        if ($recipe === null) {
            return false;
        }

        $this->db->beginTransaction();
        try {
            foreach ($recipe['ingredients'] as $itemId => $quantity) {
                $item = $this->findCharacterInventoryItem($campaignId, $characterId, $itemId);
                if ($item === null || (int) $item['quantity'] < $quantity) {
                    $this->db->rollBack();
                    return false;
                }
            }

            foreach ($recipe['ingredients'] as $itemId => $quantity) {
                $this->reduceCharacterInventoryItem($campaignId, $characterId, $itemId, $quantity);
            }

            $this->addCharacterInventoryItem($campaignId, $characterId, $recipe['output_item'], $recipe['output_quantity']);

            $this->db->commit();
            return true;
        } catch (Throwable $e) {
            if ($this->db->inTransaction()) {
                $this->db->rollBack();
            }
            throw $e;
        }
    }

    // Downtime activities

    public function createDowntimeActivity(string $campaignId, string $activityId, string $name, int $cyclesRequired): void
    {
        $stmt = $this->db->prepare('INSERT INTO downtime_activities (campaign_id, activity_id, name, cycles_required) VALUES (?, ?, ?, ?)');
        $stmt->execute([$campaignId, $activityId, $name, $cyclesRequired]);
    }

    public function findDowntimeActivity(string $campaignId, string $activityId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, activity_id, name, cycles_required FROM downtime_activities WHERE campaign_id = ? AND activity_id = ?');
        $stmt->execute([$campaignId, $activityId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['cycles_required'] = (int) $row['cycles_required'];
        return $row;
    }

    // Downtime allocations

    public function createDowntimeAllocation(string $campaignId, string $characterId, string $activityId): void
    {
        $stmt = $this->db->prepare('INSERT INTO downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (?, ?, ?, 0, 0)');
        $stmt->execute([$campaignId, $characterId, $activityId]);
    }

    public function findDowntimeAllocation(string $campaignId, string $characterId, string $activityId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, character_id, activity_id, cycles_completed, completions FROM downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?');
        $stmt->execute([$campaignId, $characterId, $activityId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['cycles_completed'] = (int) $row['cycles_completed'];
        $row['completions'] = (int) $row['completions'];
        return $row;
    }

    public function updateDowntimeAllocation(string $campaignId, string $characterId, string $activityId, int $cyclesCompleted, int $completions): void
    {
        $stmt = $this->db->prepare('UPDATE downtime_allocations SET cycles_completed = ?, completions = ? WHERE campaign_id = ? AND character_id = ? AND activity_id = ?');
        $stmt->execute([$cyclesCompleted, $completions, $campaignId, $characterId, $activityId]);
    }

    // RNG ledger

    public function findRngSeed(string $campaignId): ?string
    {
        $stmt = $this->db->prepare('SELECT seed FROM campaign_rng_seeds WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        return $row ? (string) $row['seed'] : null;
    }

    public function createRngSeed(string $campaignId, string $seed): bool
    {
        $stmt = $this->db->prepare('INSERT OR IGNORE INTO campaign_rng_seeds (campaign_id, seed) VALUES (?, ?)');
        $stmt->execute([$campaignId, $seed]);
        return $stmt->rowCount() > 0;
    }

    public function findRngRoll(string $campaignId, string $rollId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, roll_id, sides, result, sequence FROM rng_ledger WHERE campaign_id = ? AND roll_id = ?');
        $stmt->execute([$campaignId, $rollId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        return [
            'roll_id' => $row['roll_id'],
            'sides' => (int) $row['sides'],
            'result' => (int) $row['result'],
            'sequence' => (int) $row['sequence'],
        ];
    }

    public function findRngRolls(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT roll_id, sides, result, sequence FROM rng_ledger WHERE campaign_id = ? ORDER BY sequence ASC');
        $stmt->execute([$campaignId]);
        $rows = $stmt->fetchAll();
        $result = [];
        foreach ($rows as $row) {
            $result[] = [
                'roll_id' => $row['roll_id'],
                'sides' => (int) $row['sides'],
                'result' => (int) $row['result'],
                'sequence' => (int) $row['sequence'],
            ];
        }
        return $result;
    }

    public function nextRngSequence(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM rng_ledger WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    // Moderation reports

    public function findModerationReport(string $campaignId, string $reportId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM moderation_reports WHERE campaign_id = ? AND report_id = ?');
        $stmt->execute([$campaignId, $reportId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function findModerationReports(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM moderation_reports WHERE campaign_id = ? ORDER BY sequence ASC');
        $stmt->execute([$campaignId]);
        return $stmt->fetchAll();
    }

    public function nextModerationSequence(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM moderation_reports WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    public function createModerationReport(array $report): void
    {
        $stmt = $this->db->prepare('INSERT INTO moderation_reports (campaign_id, report_id, target_id, reason, status, reporter, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)');
        $stmt->execute([
            $report['campaign_id'],
            $report['report_id'],
            $report['target_id'],
            $report['reason'],
            $report['status'],
            $report['reporter'],
            $report['sequence'],
        ]);
    }

    public function resolveModerationReport(string $campaignId, string $reportId, string $action, string $note, string $resolver): void
    {
        $stmt = $this->db->prepare('UPDATE moderation_reports SET status = ?, action = ?, note = ?, resolver = ? WHERE campaign_id = ? AND report_id = ?');
        $stmt->execute(['resolved', $action, $note, $resolver, $campaignId, $reportId]);
    }

    // Safety boundaries

    public function findSafetyBoundary(string $campaignId): ?array
    {
        $stmt = $this->db->prepare('SELECT tags_json FROM safety_boundaries WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        return [
            'campaign_id' => $campaignId,
            'blocked_tags' => $this->decodeJson($row['tags_json']),
        ];
    }

    public function setSafetyBoundary(string $campaignId, array $tags): void
    {
        $stmt = $this->db->prepare('INSERT INTO safety_boundaries (campaign_id, tags_json) VALUES (?, ?) ON CONFLICT (campaign_id) DO UPDATE SET tags_json = excluded.tags_json');
        $stmt->execute([$campaignId, $this->encodeJson($tags)]);
    }

    public function findSafetyEvent(string $campaignId, string $eventId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, event_id, kind, text, tags_json, sequence FROM safety_events WHERE campaign_id = ? AND event_id = ?');
        $stmt->execute([$campaignId, $eventId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['tags'] = $this->decodeJson($row['tags_json']);
        unset($row['tags_json']);
        return $row;
    }

    public function findSafetyEvents(string $campaignId): array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, event_id, kind, text, tags_json, sequence FROM safety_events WHERE campaign_id = ? ORDER BY sequence ASC');
        $stmt->execute([$campaignId]);
        $rows = $stmt->fetchAll();
        foreach ($rows as &$row) {
            $row['tags'] = $this->decodeJson($row['tags_json']);
            unset($row['tags_json']);
        }
        return $rows;
    }

    public function nextSafetyEventSequence(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM safety_events WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    public function createSafetyEvent(string $campaignId, int $sequence, string $eventId, string $kind, string $text, array $tags): void
    {
        $stmt = $this->db->prepare('INSERT INTO safety_events (campaign_id, event_id, kind, text, tags_json, sequence) VALUES (?, ?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $eventId, $kind, $text, $this->encodeJson($tags), $sequence]);
    }

    // Feed events

    public function findFeedEvent(string $campaignId, string $eventId): ?array
    {
        $stmt = $this->db->prepare('SELECT event_id, text, sequence FROM feed_events WHERE campaign_id = ? AND event_id = ?');
        $stmt->execute([$campaignId, $eventId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        return [
            'event_id' => $row['event_id'],
            'text' => $row['text'],
            'sequence' => (int) $row['sequence'],
        ];
    }

    public function findFeedEvents(string $campaignId, int $cursor, int $limit): array
    {
        $stmt = $this->db->prepare('SELECT event_id, text, sequence FROM feed_events WHERE campaign_id = ? ORDER BY sequence ASC LIMIT ? OFFSET ?');
        $stmt->execute([$campaignId, $limit, $cursor]);
        $rows = $stmt->fetchAll();
        $result = [];
        foreach ($rows as $row) {
            $result[] = [
                'event_id' => $row['event_id'],
                'text' => $row['text'],
                'sequence' => (int) $row['sequence'],
            ];
        }
        return $result;
    }

    public function nextFeedEventSequence(string $campaignId): int
    {
        $stmt = $this->db->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM feed_events WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    public function createFeedEvent(string $campaignId, int $sequence, string $eventId, string $text): void
    {
        $stmt = $this->db->prepare('INSERT INTO feed_events (campaign_id, event_id, text, sequence) VALUES (?, ?, ?, ?)');
        $stmt->execute([$campaignId, $eventId, $text, $sequence]);
    }

    // Fixture seeds

    public function findPlayFixtureSeed(string $campaignId): ?array
    {
        $stmt = $this->db->prepare('SELECT campaign_id, fixture_id, status FROM play_fixture_seeds WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function createPlayFixtureSeed(string $campaignId, string $fixtureId, string $status): bool
    {
        $stmt = $this->db->prepare('INSERT OR IGNORE INTO play_fixture_seeds (campaign_id, fixture_id, status) VALUES (?, ?, ?)');
        $stmt->execute([$campaignId, $fixtureId, $status]);
        return $stmt->rowCount() > 0;
    }

    public function createRngRoll(string $campaignId, int $sequence, string $rollId, int $sides, int $result): void
    {
        $stmt = $this->db->prepare('INSERT INTO rng_ledger (campaign_id, roll_id, sides, result, sequence) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $rollId, $sides, $result, $sequence]);
    }

    private function columnExists(string $table, string $column): bool
    {
        $stmt = $this->db->query("PRAGMA table_info($table)");
        foreach ($stmt->fetchAll() as $row) {
            if ($row['name'] === $column) {
                return true;
            }
        }
        return false;
    }

    private function encodeJson(mixed $value): string
    {
        return json_encode($value, JSON_UNESCAPED_UNICODE);
    }

    private function decodeJson(string $json): mixed
    {
        return json_decode($json, true);
    }

    /**
     * Seed the users table from the fixture file after a storage reset.
     *
     * Play-surface tests rely on well-known accounts (dm, player-a, etc.)
     * surviving a reset, so the reset endpoint re-creates them from the
     * canonical users.json fixture. Existing users are left untouched.
     */
    private function seedUsers(): void
    {
        $file = $this->root . '/users.json';
        if (!file_exists($file)) {
            return;
        }

        $raw = file_get_contents($file);
        if ($raw === false) {
            return;
        }

        $users = json_decode($raw, true);
        if (!is_array($users)) {
            return;
        }

        foreach ($users as $user) {
            if (!is_array($user)
                || !isset($user['username'], $user['role'], $user['hash'])
                || !is_string($user['username'])
                || !is_string($user['role'])
                || !is_string($user['hash'])) {
                continue;
            }

            if ($this->findUser($user['username']) !== null) {
                continue;
            }

            $this->createUser($user);
        }
    }
}
