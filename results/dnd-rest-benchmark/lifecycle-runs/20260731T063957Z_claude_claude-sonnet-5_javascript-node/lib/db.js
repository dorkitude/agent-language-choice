import { DatabaseSync } from 'node:sqlite';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { existsSync, unlinkSync } from 'node:fs';

const __dirname = dirname(fileURLToPath(import.meta.url));
export const DB_PATH = join(__dirname, '..', 'game.db');
export const SCHEMA_VERSION = 1;

// Each server process starts from a clean database: stale files left behind
// by a previous run must not leak state (e.g. registered usernames) into
// this run's evaluation.
if (existsSync(DB_PATH)) {
  unlinkSync(DB_PATH);
}

export const db = new DatabaseSync(DB_PATH);

// Mutable so routes/storage.js can report it without re-importing initSchema state.
export const dbState = { initialized: false };

const TABLES = [
  `CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    password_hash TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS combat_sessions (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS storage_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS monsters (
    slug TEXT PRIMARY KEY,
    data TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS items (
    slug TEXT PRIMARY KEY,
    data TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS campaign_characters (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id)
  )`,
  `CREATE TABLE IF NOT EXISTS campaign_events (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id)
  )`,
  `CREATE TABLE IF NOT EXISTS campaign_quests (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id)
  )`,
  `CREATE TABLE IF NOT EXISTS campaign_factions (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id)
  )`,
  `CREATE TABLE IF NOT EXISTS campaign_npcs (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id)
  )`,
  `CREATE TABLE IF NOT EXISTS campaign_inventory (
    campaign_id TEXT NOT NULL,
    item_slug TEXT NOT NULL,
    owner TEXT NOT NULL,
    quantity INTEGER NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS campaign_equipment (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    item_slug TEXT NOT NULL,
    quantity INTEGER NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS campaign_crafting_projects (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id)
  )`,
  `CREATE TABLE IF NOT EXISTS campaign_sessions (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaigns (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_members (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, character_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_events (
    campaign_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, sequence)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_scenes (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_locations (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_location_connections (
    campaign_id TEXT NOT NULL,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, from_id, to_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_encounters (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_spells (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    spell_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, character_id, spell_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_casts (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, character_id, sequence)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_concentration (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    data TEXT,
    PRIMARY KEY (campaign_id, character_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_items (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, character_id, item_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_equipment (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    slot TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, character_id, slot)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_currency (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, character_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_transfers (
    campaign_id TEXT NOT NULL,
    transfer_id INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, transfer_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_loot (
    campaign_id TEXT NOT NULL,
    loot_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, loot_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (
    campaign_id TEXT NOT NULL,
    loot_id TEXT NOT NULL,
    voter TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, loot_id, voter)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_npcs (
    campaign_id TEXT NOT NULL,
    npc_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, npc_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_factions (
    campaign_id TEXT NOT NULL,
    faction_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, faction_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_reputation_totals (
    campaign_id TEXT NOT NULL,
    faction_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    reputation INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, faction_id, character_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_reputation_history (
    campaign_id TEXT NOT NULL,
    faction_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    reputation INTEGER NOT NULL,
    delta INTEGER NOT NULL,
    reason TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (
    campaign_id TEXT NOT NULL,
    npc_id TEXT NOT NULL,
    dialogue_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, npc_id, dialogue_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_relationships (
    campaign_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, source_id, target_id, kind)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_clues (
    campaign_id TEXT NOT NULL,
    clue_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, clue_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_quests (
    campaign_id TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, quest_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_character_rewards (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, character_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_world_events (
    campaign_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, event_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_calendar (
    campaign_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_settlements (
    campaign_id TEXT NOT NULL,
    settlement_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, settlement_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_shops (
    campaign_id TEXT NOT NULL,
    settlement_id TEXT NOT NULL,
    shop_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, settlement_id, shop_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_recipes (
    campaign_id TEXT NOT NULL,
    recipe_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, recipe_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (
    campaign_id TEXT NOT NULL,
    activity_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, activity_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_downtime_allocations (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    activity_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, character_id, activity_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_session_zero (
    campaign_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_content (
    campaign_id TEXT NOT NULL,
    content_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, content_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_notes (
    campaign_id TEXT NOT NULL,
    note_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, note_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_whispers (
    campaign_id TEXT NOT NULL,
    whisper_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, whisper_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_messages (
    campaign_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, message_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_invitations (
    campaign_id TEXT NOT NULL,
    invitation_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, invitation_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_delegations (
    campaign_id TEXT NOT NULL,
    username TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, username)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (
    campaign_id TEXT NOT NULL,
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    powers TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_audit_events (
    campaign_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, correlation_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_projection_events (
    campaign_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, event_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (
    campaign_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, event_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_idempotency_keys (
    campaign_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, idempotency_key)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_state (
    campaign_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (
    campaign_id TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, submission_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers (
    campaign_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, sequence)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_exports (
    campaign_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, version)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_imports (
    campaign_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_migrations (
    campaign_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_search_records (
    campaign_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, record_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_rate_events (
    campaign_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, event_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_metrics (
    campaign_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_backups (
    campaign_id TEXT NOT NULL,
    backup_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, backup_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_replay_events (
    campaign_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, event_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_rng_config (
    campaign_id TEXT PRIMARY KEY,
    seed TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (
    campaign_id TEXT NOT NULL,
    roll_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, roll_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports (
    campaign_id TEXT NOT NULL,
    report_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, report_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries (
    campaign_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_safety_events (
    campaign_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, event_id)
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_fixture_seeds (
    campaign_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS play_spectator_tickets (
    spectator_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS play_campaign_feed_events (
    campaign_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (campaign_id, event_id)
  )`,
];

const TABLE_NAMES = [
  'users',
  'combat_sessions',
  'storage_meta',
  'monsters',
  'items',
  'campaigns',
  'campaign_characters',
  'campaign_events',
  'campaign_quests',
  'campaign_factions',
  'campaign_npcs',
  'campaign_inventory',
  'campaign_equipment',
  'campaign_crafting_projects',
  'campaign_sessions',
  'play_campaigns',
  'play_campaign_members',
  'play_campaign_events',
  'play_campaign_scenes',
  'play_campaign_locations',
  'play_campaign_location_connections',
  'play_campaign_encounters',
  'play_campaign_spells',
  'play_campaign_casts',
  'play_campaign_concentration',
  'play_campaign_items',
  'play_campaign_equipment',
  'play_campaign_currency',
  'play_campaign_transfers',
  'play_campaign_loot',
  'play_campaign_loot_votes',
  'play_campaign_npcs',
  'play_campaign_factions',
  'play_campaign_reputation_totals',
  'play_campaign_reputation_history',
  'play_campaign_npc_dialogue',
  'play_campaign_relationships',
  'play_campaign_clues',
  'play_campaign_quests',
  'play_campaign_character_rewards',
  'play_campaign_world_events',
  'play_campaign_calendar',
  'play_campaign_settlements',
  'play_campaign_shops',
  'play_campaign_recipes',
  'play_campaign_downtime_activities',
  'play_campaign_downtime_allocations',
  'play_campaign_session_zero',
  'play_campaign_content',
  'play_campaign_notes',
  'play_campaign_whispers',
  'play_campaign_invitations',
  'play_campaign_delegations',
  'play_campaign_delegation_audit',
  'play_campaign_audit_events',
  'play_campaign_projection_events',
  'play_campaign_idempotent_events',
  'play_campaign_idempotency_keys',
  'play_campaign_safe_turn_state',
  'play_campaign_safe_turns',
  'play_campaign_transactional_transfers',
  'play_campaign_exports',
  'play_campaign_imports',
  'play_campaign_migrations',
  'play_campaign_search_records',
  'play_campaign_rate_events',
  'play_campaign_metrics',
  'play_campaign_backups',
  'play_campaign_replay_events',
  'play_campaign_rng_config',
  'play_campaign_rng_rolls',
  'play_campaign_moderation_reports',
  'play_campaign_safety_boundaries',
  'play_campaign_safety_events',
  'play_campaign_fixture_seeds',
  'play_spectator_tickets',
  'play_campaign_feed_events',
];

export function initSchema() {
  db.exec(TABLES.join(';\n') + ';');
  db.prepare('INSERT OR REPLACE INTO storage_meta (key, value) VALUES (?, ?)').run(
    'schema_version',
    String(SCHEMA_VERSION)
  );
  dbState.initialized = true;
}

export function resetSchema() {
  db.exec(TABLE_NAMES.map((name) => `DROP TABLE IF EXISTS ${name}`).join(';\n') + ';');
  initSchema();
}

initSchema();
