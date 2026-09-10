<?php
declare(strict_types=1);

const STORAGE_SCHEMA_VERSION = 1;

/**
 * Keep the create and reset inventories together: resetDatabase() is expected
 * to return the database to the exact schema initializeDatabase() creates.
 * RESET_TABLES deliberately retains the established drop sequence.
 *
 * @var list<string>
 */
const TABLE_DEFINITIONS = [
    'CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL)',
    'CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, role TEXT NOT NULL, password_hash TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS combat_sessions (id TEXT PRIMARY KEY, state TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS compendium_monsters (slug TEXT PRIMARY KEY, name TEXT NOT NULL, cr TEXT NOT NULL, armor_class INTEGER NOT NULL, hit_points INTEGER NOT NULL, tags TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS compendium_items (slug TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, rarity TEXT NOT NULL, cost_gp INTEGER NOT NULL)',
    'CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, dm TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS play_campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL, status TEXT NOT NULL, max_players INTEGER NOT NULL, current_actor TEXT, turn_number INTEGER, nudge_count INTEGER NOT NULL DEFAULT 0, current_scene_id TEXT, current_location_id TEXT, phase TEXT)',
    'CREATE TABLE IF NOT EXISTS play_campaign_spectators (spectator_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS play_campaign_feed_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, text TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, event_id), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_messages (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, actor TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_invitations (campaign_id TEXT NOT NULL, invitation_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, invitation_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_delegations (campaign_id TEXT NOT NULL, username TEXT NOT NULL, active INTEGER NOT NULL, PRIMARY KEY (campaign_id, username))',
    'CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, username TEXT NOT NULL, action TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_audit_events (campaign_id TEXT NOT NULL, timestamp INTEGER NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL, role TEXT NOT NULL, correlation_id TEXT NOT NULL, PRIMARY KEY (campaign_id, timestamp), UNIQUE (campaign_id, correlation_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_projection_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (campaign_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, event_id TEXT NOT NULL, value TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, idempotency_key), UNIQUE (campaign_id, event_id), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (campaign_id TEXT PRIMARY KEY, current_turn INTEGER NOT NULL)',
    'CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_submissions (campaign_id TEXT NOT NULL, submission_id TEXT NOT NULL, action TEXT NOT NULL, accepted_turn INTEGER NOT NULL, next_turn INTEGER NOT NULL, PRIMARY KEY (campaign_id, submission_id), UNIQUE (campaign_id, accepted_turn))',
    'CREATE TABLE IF NOT EXISTS play_campaign_session_zero_settings (campaign_id TEXT PRIMARY KEY, rules TEXT NOT NULL, tone TEXT NOT NULL, consent TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS play_campaign_content (campaign_id TEXT NOT NULL, content_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, tags TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, content_id), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_notes (campaign_id TEXT NOT NULL, note_id TEXT NOT NULL, text TEXT NOT NULL, visibility TEXT NOT NULL, owner TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, note_id), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_whispers (campaign_id TEXT NOT NULL, whisper_id TEXT NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, text TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, whisper_id), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_narrations (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, actor TEXT NOT NULL DEFAULT \'dm\', text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_actions (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, actor TEXT NOT NULL, type TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_resolutions (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_travels (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, actor TEXT NOT NULL, destination_id TEXT NOT NULL, travel_turns INTEGER NOT NULL, PRIMARY KEY (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_rests (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, actor TEXT NOT NULL, type TEXT NOT NULL, hp_current INTEGER NOT NULL, hp_max INTEGER NOT NULL, PRIMARY KEY (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_encounters (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL, combatants TEXT NOT NULL, round INTEGER NOT NULL DEFAULT 1, turn_index INTEGER NOT NULL DEFAULT 0, conditions TEXT NOT NULL DEFAULT \'{}\', exploration_actor TEXT)',
    'CREATE TABLE IF NOT EXISTS play_campaign_encounter_rewards (encounter_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, xp INTEGER NOT NULL, loot TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS play_campaign_combat_actions (campaign_id TEXT NOT NULL, encounter_id TEXT NOT NULL, sequence INTEGER NOT NULL, actor TEXT NOT NULL, type TEXT NOT NULL, target TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_ready_actions (campaign_id TEXT NOT NULL, encounter_id TEXT NOT NULL, sequence INTEGER NOT NULL, actor TEXT NOT NULL, trigger TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_members (character_id TEXT NOT NULL, campaign_id TEXT NOT NULL, username TEXT NOT NULL, name TEXT NOT NULL, class TEXT NOT NULL, level INTEGER NOT NULL DEFAULT 1, con_modifier INTEGER NOT NULL DEFAULT 0, ability_scores TEXT NOT NULL DEFAULT \'{}\', hp_current INTEGER NOT NULL DEFAULT 20, hp_max INTEGER NOT NULL DEFAULT 20, death_save_successes INTEGER NOT NULL DEFAULT 0, death_save_failures INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT \'conscious\', PRIMARY KEY (campaign_id, character_id), UNIQUE (campaign_id, username))',
    'CREATE TABLE IF NOT EXISTS play_campaign_character_owners (character_id TEXT NOT NULL, campaign_id TEXT NOT NULL, owner TEXT, PRIMARY KEY (campaign_id, character_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_character_spells (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, spell_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_character_prepared_spells (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, spell_id), UNIQUE (campaign_id, character_id, position))',
    'CREATE TABLE IF NOT EXISTS play_campaign_character_casts (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, sequence INTEGER NOT NULL, spell_id TEXT NOT NULL, target TEXT NOT NULL, slot_level INTEGER NOT NULL, slots_remaining INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_character_concentrations (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, target TEXT NOT NULL, remaining_turns INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_character_inventory_items (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, item_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_recipes (campaign_id TEXT NOT NULL, recipe_id TEXT NOT NULL, name TEXT NOT NULL, ingredients TEXT NOT NULL, output_item TEXT NOT NULL, output_quantity INTEGER NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, recipe_id), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (campaign_id TEXT NOT NULL, activity_id TEXT NOT NULL, name TEXT NOT NULL, cycles_required INTEGER NOT NULL, PRIMARY KEY (campaign_id, activity_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_downtime_allocations (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, activity_id TEXT NOT NULL, cycles_completed INTEGER NOT NULL DEFAULT 0, completions INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, character_id, activity_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_loot (campaign_id TEXT NOT NULL, loot_id TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL, status TEXT NOT NULL, recipient_character_id TEXT, PRIMARY KEY (campaign_id, loot_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (campaign_id TEXT NOT NULL, loot_id TEXT NOT NULL, voter TEXT NOT NULL, recipient_character_id TEXT NOT NULL, PRIMARY KEY (campaign_id, loot_id, voter))',
    'CREATE TABLE IF NOT EXISTS play_campaign_npcs (campaign_id TEXT NOT NULL, npc_id TEXT NOT NULL, name TEXT NOT NULL, agenda TEXT NOT NULL, public_status TEXT NOT NULL, PRIMARY KEY (campaign_id, npc_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (campaign_id TEXT NOT NULL, npc_id TEXT NOT NULL, dialogue_id TEXT NOT NULL, speaker TEXT NOT NULL, text TEXT NOT NULL, visibility TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, npc_id, dialogue_id), UNIQUE (campaign_id, npc_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_relationships (campaign_id TEXT NOT NULL, source_id TEXT NOT NULL, target_id TEXT NOT NULL, kind TEXT NOT NULL, score INTEGER NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, source_id, target_id, kind), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_clues (campaign_id TEXT NOT NULL, clue_id TEXT NOT NULL, text TEXT NOT NULL, audience TEXT NOT NULL, character_id TEXT, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, clue_id), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_quests (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, title TEXT NOT NULL, depends_on TEXT NOT NULL, state TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, quest_id), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_quest_rewards (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, xp INTEGER NOT NULL, items TEXT NOT NULL, awarded INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, quest_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_quest_reward_grants (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, character_id TEXT NOT NULL, xp INTEGER NOT NULL, items TEXT NOT NULL, PRIMARY KEY (campaign_id, quest_id, character_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_world_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, turn_number INTEGER NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL, sequence INTEGER NOT NULL, resolution_text TEXT, resolution_turn_number INTEGER, PRIMARY KEY (campaign_id, event_id), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_factions (campaign_id TEXT NOT NULL, faction_id TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY (campaign_id, faction_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_faction_reputations (campaign_id TEXT NOT NULL, faction_id TEXT NOT NULL, character_id TEXT NOT NULL, reputation INTEGER NOT NULL, PRIMARY KEY (campaign_id, faction_id, character_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_faction_reputation_history (campaign_id TEXT NOT NULL, faction_id TEXT NOT NULL, sequence INTEGER NOT NULL, character_id TEXT NOT NULL, reputation INTEGER NOT NULL, delta INTEGER NOT NULL, reason TEXT NOT NULL, PRIMARY KEY (campaign_id, faction_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_character_currency (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, gold INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_currency_transfers (campaign_id TEXT NOT NULL, transfer_id INTEGER NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, gold INTEGER NOT NULL, PRIMARY KEY (campaign_id, transfer_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, amount INTEGER NOT NULL, from_gold INTEGER NOT NULL, to_gold INTEGER NOT NULL, PRIMARY KEY (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_character_equipment (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, slot TEXT NOT NULL, item_id TEXT NOT NULL, attuned INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, character_id, slot))',
    'CREATE TABLE IF NOT EXISTS play_campaign_documents (campaign_id TEXT PRIMARY KEY, story TEXT NOT NULL, dm_notes TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS play_campaign_backups (campaign_id TEXT NOT NULL, backup_id TEXT NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, backup_id), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_replay_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, event_id), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_rng_seeds (campaign_id TEXT PRIMARY KEY, seed TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (campaign_id TEXT NOT NULL, roll_id TEXT NOT NULL, sides INTEGER NOT NULL, result INTEGER NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, roll_id), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports (campaign_id TEXT NOT NULL, report_id TEXT NOT NULL, target_id TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL, reporter TEXT NOT NULL, sequence INTEGER NOT NULL, action TEXT, note TEXT, resolver TEXT, PRIMARY KEY (campaign_id, report_id), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries (campaign_id TEXT PRIMARY KEY, blocked_tags TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS play_campaign_safety_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, tags TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, event_id), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_fixture_seeds (campaign_id TEXT PRIMARY KEY, fixture_id TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS play_campaign_exports (campaign_id TEXT NOT NULL, version INTEGER NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, version))',
    'CREATE TABLE IF NOT EXISTS play_campaign_imports (campaign_id TEXT PRIMARY KEY, version INTEGER NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS play_campaign_migrations (campaign_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, story TEXT NOT NULL, campaign_name TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS play_campaign_search_records (campaign_id TEXT NOT NULL, record_id TEXT NOT NULL, text TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, record_id), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_rate_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, actor TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, event_id), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_service_metrics (campaign_id TEXT PRIMARY KEY, accepted_rate_events INTEGER NOT NULL DEFAULT 0, rejected_rate_events INTEGER NOT NULL DEFAULT 0, projection_events INTEGER NOT NULL DEFAULT 0)',
    'CREATE TABLE IF NOT EXISTS service_mode (id INTEGER PRIMARY KEY CHECK (id = 1), maintenance INTEGER NOT NULL CHECK (maintenance IN (0, 1)))',
    'CREATE TABLE IF NOT EXISTS play_campaign_calendars (campaign_id TEXT PRIMARY KEY, day INTEGER NOT NULL, season TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS play_campaign_settlements (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, name TEXT NOT NULL, services TEXT NOT NULL, availability TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, settlement_id), UNIQUE (campaign_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_settlement_discoveries (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, character_id TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, settlement_id, character_id), UNIQUE (campaign_id, settlement_id, sequence))',
    'CREATE TABLE IF NOT EXISTS play_campaign_shops (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, shop_id TEXT NOT NULL, name TEXT NOT NULL, stock TEXT NOT NULL, buy_price INTEGER NOT NULL, sell_price INTEGER NOT NULL, PRIMARY KEY (campaign_id, settlement_id, shop_id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_scenes (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_locations (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY (campaign_id, id))',
    'CREATE TABLE IF NOT EXISTS play_campaign_location_connections (campaign_id TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL, travel_turns INTEGER NOT NULL, PRIMARY KEY (campaign_id, from_id, to_id))',
    'CREATE TABLE IF NOT EXISTS campaign_characters (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL, class TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS campaign_events (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, kind TEXT NOT NULL, summary TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS campaign_quests (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, milestones TEXT NOT NULL, completed TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS campaign_factions (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, stance TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS campaign_npcs (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, faction_id TEXT NOT NULL, disposition INTEGER NOT NULL)',
    'CREATE TABLE IF NOT EXISTS campaign_inventory (campaign_id TEXT NOT NULL, item_slug TEXT NOT NULL, owner TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, item_slug, owner))',
    'CREATE TABLE IF NOT EXISTS campaign_equipment (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, item_slug))',
    'CREATE TABLE IF NOT EXISTS crafting_projects (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, days_required INTEGER NOT NULL, days_completed INTEGER NOT NULL, cost_gp INTEGER NOT NULL, status TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS campaign_sessions (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, starts_at TEXT NOT NULL, starts_at_timestamp INTEGER NOT NULL, duration_minutes INTEGER NOT NULL, agenda TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS campaign_session_attendance (session_id TEXT NOT NULL, character_id TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (session_id, character_id))',
];

/** @var list<string> */
const RESET_TABLES = [
    'play_campaign_ready_actions', 'play_campaign_combat_actions', 'play_campaign_encounter_rewards', 'play_campaign_encounters', 'play_campaign_rests', 'play_campaign_travels', 'play_campaign_resolutions', 'play_campaign_actions', 'play_campaign_narrations', 'play_campaign_messages', 'play_campaign_whispers', 'play_campaign_notes', 'play_campaign_content', 'play_campaign_service_metrics', 'play_campaign_rate_events', 'play_campaign_search_records', 'play_campaign_migrations', 'play_campaign_imports', 'play_campaign_exports', 'play_campaign_moderation_reports', 'play_campaign_fixture_seeds', 'play_campaign_safety_events', 'play_campaign_safety_boundaries', 'play_campaign_rng_rolls', 'play_campaign_rng_seeds', 'play_campaign_replay_events', 'play_campaign_backups', 'play_campaign_documents', 'play_campaign_shops', 'play_campaign_settlement_discoveries', 'play_campaign_settlements', 'play_campaign_calendars', 'play_campaign_scenes', 'play_campaign_session_zero_settings', 'play_campaign_safe_turn_submissions', 'play_campaign_safe_turns', 'play_campaign_idempotent_events', 'play_campaign_projection_events', 'play_campaign_audit_events', 'play_campaign_delegation_audit', 'play_campaign_delegations', 'play_campaign_feed_events', 'play_campaign_spectators', 'service_mode',
    'play_campaign_location_connections', 'play_campaign_locations',
    'campaign_session_attendance', 'campaign_sessions', 'crafting_projects', 'campaign_equipment',
    'campaign_inventory', 'campaign_npcs', 'campaign_factions', 'campaign_quests', 'campaign_events',
    'play_campaign_faction_reputation_history', 'play_campaign_faction_reputations', 'play_campaign_factions', 'play_campaign_world_events', 'play_campaign_quest_reward_grants', 'play_campaign_quest_rewards', 'play_campaign_quests', 'play_campaign_clues', 'play_campaign_relationships', 'play_campaign_npc_dialogue',
    'campaign_characters', 'play_campaign_character_equipment', 'play_campaign_transactional_transfers', 'play_campaign_currency_transfers', 'play_campaign_character_currency', 'play_campaign_npcs', 'play_campaign_loot_votes', 'play_campaign_loot', 'play_campaign_downtime_allocations', 'play_campaign_downtime_activities', 'play_campaign_recipes', 'play_campaign_character_inventory_items', 'play_campaign_character_concentrations', 'play_campaign_character_casts', 'play_campaign_character_prepared_spells', 'play_campaign_character_spells', 'play_campaign_character_owners', 'play_campaign_members', 'play_campaign_invitations', 'campaigns', 'play_campaigns', 'compendium_items',
    'compendium_monsters', 'combat_sessions', 'users', 'schema_meta',
];

function database(): PDO
{
    static $database = null;
    if ($database instanceof PDO) {
        return $database;
    }

    $database = new PDO('sqlite:' . __DIR__ . '/game.db', null, null, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
    $database->exec('PRAGMA busy_timeout = 5000');
    initializeDatabase($database);
    return $database;
}

/**
 * Apply additive SQLite migrations in declaration order and report additions.
 *
 * SQLite only supports these migrations one column at a time. Keeping the
 * column inventory at each call site makes the compatibility contract visible
 * while avoiding subtly different copies of the same PRAGMA/check/ALTER loop.
 *
 * @param array<string, string> $definitions column name => ALTER TABLE suffix
 * @return array<string, bool> column name => whether this invocation added it
 */
function addMissingColumns(PDO $database, string $table, array $definitions): array
{
    $columns = $database->query("PRAGMA table_info({$table})")->fetchAll(PDO::FETCH_COLUMN, 1);
    $added = [];
    foreach ($definitions as $name => $definition) {
        $added[$name] = !in_array($name, $columns, true);
        if ($added[$name]) {
            $database->exec("ALTER TABLE {$table} ADD COLUMN {$definition}");
            $columns[] = $name;
        }
    }
    return $added;
}

function initializeDatabase(?PDO $database = null): void
{
    $database ??= new PDO('sqlite:' . __DIR__ . '/game.db', null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
    foreach (TABLE_DEFINITIONS as $definition) {
        $database->exec($definition);
    }
    $database->exec('INSERT OR IGNORE INTO service_mode (id, maintenance) VALUES (1, 0)');

    // These additions keep databases made before the columns existed usable.
    // New databases already receive them through TABLE_DEFINITIONS above.
    addMissingColumns($database, 'play_campaigns', [
        'current_actor' => 'current_actor TEXT',
        'turn_number' => 'turn_number INTEGER',
        'nudge_count' => 'nudge_count INTEGER NOT NULL DEFAULT 0',
        'current_scene_id' => 'current_scene_id TEXT',
        'current_location_id' => 'current_location_id TEXT',
        'phase' => 'phase TEXT',
    ]);
    $addedMemberColumns = addMissingColumns($database, 'play_campaign_members', [
        'level' => 'level INTEGER NOT NULL DEFAULT 1',
        'con_modifier' => 'con_modifier INTEGER NOT NULL DEFAULT 0',
        'ability_scores' => "ability_scores TEXT NOT NULL DEFAULT '{}'",
        'hp_current' => 'hp_current INTEGER NOT NULL DEFAULT 20',
        'hp_max' => 'hp_max INTEGER NOT NULL DEFAULT 20',
        'death_save_successes' => 'death_save_successes INTEGER NOT NULL DEFAULT 0',
        'death_save_failures' => 'death_save_failures INTEGER NOT NULL DEFAULT 0',
        'status' => "status TEXT NOT NULL DEFAULT 'conscious'",
    ]);
    if ($addedMemberColumns['status']) {
        $database->exec("UPDATE play_campaign_members SET status = 'unconscious' WHERE hp_current = 0");
    }
    // Membership historically assigned a character directly to its joining
    // player. Seed the explicit ownership relation for databases created
    // before that relation was introduced.
    $database->exec('INSERT OR IGNORE INTO play_campaign_character_owners (character_id, campaign_id, owner) SELECT character_id, campaign_id, username FROM play_campaign_members');
    // Existing campaign characters acquire the same initial purse as newly
    // joined characters when this additive schema migration is first applied.
    $database->exec('INSERT OR IGNORE INTO play_campaign_character_currency (campaign_id, character_id, gold) SELECT campaign_id, character_id, 10 FROM play_campaign_members');
    // Seed aggregate-only service metrics for databases created before this
    // table existed; the event tables contain the accepted historical totals.
    $database->exec('INSERT OR IGNORE INTO play_campaign_service_metrics (campaign_id, accepted_rate_events, projection_events) SELECT c.id, (SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = c.id), (SELECT COUNT(*) FROM play_campaign_projection_events WHERE campaign_id = c.id) FROM play_campaigns c');
    addMissingColumns($database, 'play_campaign_encounters', [
        'round' => 'round INTEGER NOT NULL DEFAULT 1',
        'turn_index' => 'turn_index INTEGER NOT NULL DEFAULT 0',
        'conditions' => "conditions TEXT NOT NULL DEFAULT '{}'",
        'exploration_actor' => 'exploration_actor TEXT',
    ]);
    addMissingColumns($database, 'play_campaign_narrations', [
        'actor' => "actor TEXT NOT NULL DEFAULT 'dm'",
    ]);
    $database->exec('DELETE FROM schema_meta');
    $statement = $database->prepare('INSERT INTO schema_meta (version) VALUES (?)');
    $statement->execute([STORAGE_SCHEMA_VERSION]);
}

function resetDatabase(): void
{
    $database = database();
    foreach (RESET_TABLES as $table) {
        $database->exec("DROP TABLE IF EXISTS {$table}");
    }
    initializeDatabase($database);
}
