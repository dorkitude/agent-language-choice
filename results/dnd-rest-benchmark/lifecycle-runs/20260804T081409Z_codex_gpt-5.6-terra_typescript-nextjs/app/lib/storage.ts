import { DatabaseSync } from "node:sqlite";
import path from "node:path";

export const SCHEMA_VERSION = 1;

// Use the project directory rather than a temporary directory so game state
// survives a server restart.
const databasePath = path.join(process.cwd(), "game.db");
const globalStorage = globalThis as typeof globalThis & { gameDatabase?: DatabaseSync };
// Turbopack can evaluate several route bundles at once.  Each bundle gets its
// own module cache, so schema initialization can briefly contend across SQLite
// connections.  Wait for the other initializer instead of failing a request.
export const database = globalStorage.gameDatabase ?? new DatabaseSync(databasePath, { timeout: 5_000 });
globalStorage.gameDatabase = database;

function initializeSchema() {
  database.exec(`
    CREATE TABLE IF NOT EXISTS storage_metadata (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      salt TEXT NOT NULL,
      password_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS combat_sessions (
      id TEXT PRIMARY KEY,
      round INTEGER NOT NULL,
      turn_index INTEGER NOT NULL,
      order_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS combat_conditions (
      id INTEGER PRIMARY KEY,
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
      cost_gp REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS campaigns (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      dm TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS play_campaigns (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      owner TEXT NOT NULL,
      status TEXT NOT NULL,
      max_players INTEGER NOT NULL,
      phase TEXT NOT NULL DEFAULT 'exploration'
    );
    CREATE TABLE IF NOT EXISTS play_campaign_spectators (
      spectator_id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_system_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      kind TEXT NOT NULL,
      actor TEXT NOT NULL,
      text TEXT NOT NULL,
      PRIMARY KEY (campaign_id, sequence),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_session_zero_settings (
      campaign_id TEXT PRIMARY KEY,
      rules TEXT NOT NULL,
      tone TEXT NOT NULL,
      consent_json TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_documents (
      campaign_id TEXT PRIMARY KEY,
      story TEXT NOT NULL,
      dm_notes TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_exports (
      campaign_id TEXT NOT NULL,
      version INTEGER NOT NULL,
      story TEXT NOT NULL,
      status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, version),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_backups (
      campaign_id TEXT NOT NULL,
      backup_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      story TEXT NOT NULL,
      status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, backup_id),
      UNIQUE (campaign_id, sequence),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_import_states (
      campaign_id TEXT PRIMARY KEY,
      version INTEGER NOT NULL,
      story TEXT NOT NULL,
      status TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_migration_states (
      campaign_id TEXT PRIMARY KEY,
      schema_version INTEGER NOT NULL,
      story TEXT NOT NULL,
      campaign_name TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_scenes (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_scene_state (
      campaign_id TEXT PRIMARY KEY,
      current_scene_id TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_locations (
      campaign_id TEXT NOT NULL,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_location_connections (
      campaign_id TEXT NOT NULL,
      from_id TEXT NOT NULL,
      to_id TEXT NOT NULL,
      travel_turns INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, from_id, to_id),
      FOREIGN KEY (campaign_id, from_id) REFERENCES play_campaign_locations(campaign_id, id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, to_id) REFERENCES play_campaign_locations(campaign_id, id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_members (
      campaign_id TEXT NOT NULL,
      username TEXT NOT NULL,
      character_id TEXT NOT NULL,
      name TEXT NOT NULL,
      class TEXT NOT NULL,
      PRIMARY KEY (campaign_id, character_id),
      UNIQUE (campaign_id, username),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_delegations (
      campaign_id TEXT NOT NULL,
      username TEXT NOT NULL,
      powers_json TEXT NOT NULL,
      active INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, username),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (
      campaign_id TEXT NOT NULL,
      username TEXT NOT NULL,
      action TEXT NOT NULL,
      powers_json TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_audit_events (
      campaign_id TEXT NOT NULL,
      timestamp INTEGER NOT NULL,
      kind TEXT NOT NULL,
      actor TEXT NOT NULL,
      role TEXT NOT NULL,
      correlation_id TEXT NOT NULL,
      PRIMARY KEY (campaign_id, timestamp),
      UNIQUE (campaign_id, correlation_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_projection_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      value TEXT,
      PRIMARY KEY (campaign_id, sequence),
      UNIQUE (campaign_id, event_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_replay_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      text TEXT NOT NULL,
      PRIMARY KEY (campaign_id, sequence),
      UNIQUE (campaign_id, event_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_rng_seeds (
      campaign_id TEXT PRIMARY KEY,
      seed TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      roll_id TEXT NOT NULL,
      sides INTEGER NOT NULL,
      result INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, sequence),
      UNIQUE (campaign_id, roll_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      value TEXT NOT NULL,
      idempotency_key TEXT NOT NULL,
      PRIMARY KEY (campaign_id, sequence),
      UNIQUE (campaign_id, event_id),
      UNIQUE (campaign_id, idempotency_key),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      report_id TEXT NOT NULL,
      target_id TEXT NOT NULL,
      reason TEXT NOT NULL,
      status TEXT NOT NULL,
      reporter TEXT NOT NULL,
      action TEXT,
      note TEXT,
      resolver TEXT,
      PRIMARY KEY (campaign_id, sequence),
      UNIQUE (campaign_id, report_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries (
      campaign_id TEXT NOT NULL,
      tag TEXT NOT NULL,
      PRIMARY KEY (campaign_id, tag),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_safety_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      text TEXT NOT NULL,
      tags_json TEXT NOT NULL,
      PRIMARY KEY (campaign_id, sequence),
      UNIQUE (campaign_id, event_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_feed_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      text TEXT NOT NULL,
      PRIMARY KEY (campaign_id, sequence),
      UNIQUE (campaign_id, event_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_fixture_seeds (
      campaign_id TEXT PRIMARY KEY,
      fixture_id TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_state (
      campaign_id TEXT PRIMARY KEY,
      current_turn INTEGER NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (
      campaign_id TEXT NOT NULL,
      submission_id TEXT NOT NULL,
      action TEXT NOT NULL,
      accepted_turn INTEGER NOT NULL,
      next_turn INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, submission_id),
      UNIQUE (campaign_id, accepted_turn),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_invitations (
      campaign_id TEXT NOT NULL,
      invitation_id TEXT NOT NULL,
      username TEXT NOT NULL,
      character_id TEXT NOT NULL,
      status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, invitation_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE UNIQUE INDEX IF NOT EXISTS play_campaign_one_pending_invitation
      ON play_campaign_invitations (campaign_id, username)
      WHERE status = 'pending';
    CREATE TABLE IF NOT EXISTS play_campaign_character_owners (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      owner TEXT NOT NULL,
      PRIMARY KEY (campaign_id, character_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id)
        REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_character_currency (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      gold INTEGER NOT NULL DEFAULT 10,
      PRIMARY KEY (campaign_id, character_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id)
        REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_currency_transfers (
      campaign_id TEXT NOT NULL,
      transfer_id INTEGER NOT NULL,
      from_character_id TEXT NOT NULL,
      to_character_id TEXT NOT NULL,
      gold INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, transfer_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      from_character_id TEXT NOT NULL,
      to_character_id TEXT NOT NULL,
      amount INTEGER NOT NULL,
      from_gold INTEGER NOT NULL,
      to_gold INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, sequence),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_character_inventory_items (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      item_id TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id, item_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id)
        REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_recipes (
      campaign_id TEXT NOT NULL,
      recipe_id TEXT NOT NULL,
      name TEXT NOT NULL,
      ingredients_json TEXT NOT NULL,
      output_item TEXT NOT NULL,
      output_quantity INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, recipe_id),
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
      FOREIGN KEY (campaign_id, activity_id)
        REFERENCES play_campaign_downtime_activities(campaign_id, activity_id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id)
        REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_loot (
      campaign_id TEXT NOT NULL,
      loot_id TEXT NOT NULL,
      item_id TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      status TEXT NOT NULL,
      recipient_character_id TEXT,
      votes INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, loot_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (
      campaign_id TEXT NOT NULL,
      loot_id TEXT NOT NULL,
      voter TEXT NOT NULL,
      recipient_character_id TEXT NOT NULL,
      PRIMARY KEY (campaign_id, loot_id, voter),
      FOREIGN KEY (campaign_id, loot_id)
        REFERENCES play_campaign_loot(campaign_id, loot_id) ON DELETE CASCADE
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
    CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (
      campaign_id TEXT NOT NULL,
      npc_id TEXT NOT NULL,
      dialogue_id TEXT NOT NULL,
      speaker TEXT NOT NULL,
      text TEXT NOT NULL,
      visibility TEXT NOT NULL,
      PRIMARY KEY (campaign_id, npc_id, dialogue_id),
      FOREIGN KEY (campaign_id, npc_id)
        REFERENCES play_campaign_npcs(campaign_id, npc_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_relationships (
      campaign_id TEXT NOT NULL,
      source_id TEXT NOT NULL,
      target_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      score INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, source_id, target_id, kind),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_clues (
      campaign_id TEXT NOT NULL,
      clue_id TEXT NOT NULL,
      text TEXT NOT NULL,
      audience TEXT NOT NULL,
      character_id TEXT,
      PRIMARY KEY (campaign_id, clue_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id)
        REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_quests (
      campaign_id TEXT NOT NULL,
      quest_id TEXT NOT NULL,
      title TEXT NOT NULL,
      depends_on_json TEXT NOT NULL,
      state TEXT NOT NULL,
      rewards_xp INTEGER,
      rewards_items_json TEXT,
      rewards_awarded INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, quest_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_quest_reward_grants (
      campaign_id TEXT NOT NULL,
      quest_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      xp INTEGER NOT NULL,
      items_json TEXT NOT NULL,
      PRIMARY KEY (campaign_id, quest_id, character_id),
      FOREIGN KEY (campaign_id, quest_id)
        REFERENCES play_campaign_quests(campaign_id, quest_id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id)
        REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_content (
      campaign_id TEXT NOT NULL,
      content_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      text TEXT NOT NULL,
      tags_json TEXT NOT NULL,
      PRIMARY KEY (campaign_id, content_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_notes (
      campaign_id TEXT NOT NULL,
      note_id TEXT NOT NULL,
      text TEXT NOT NULL,
      visibility TEXT NOT NULL,
      owner TEXT NOT NULL,
      PRIMARY KEY (campaign_id, note_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_search_records (
      campaign_id TEXT NOT NULL,
      record_id TEXT NOT NULL,
      text TEXT NOT NULL,
      PRIMARY KEY (campaign_id, record_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_rate_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      actor TEXT NOT NULL,
      PRIMARY KEY (campaign_id, sequence),
      UNIQUE (campaign_id, event_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_metrics (
      campaign_id TEXT PRIMARY KEY,
      rejected_rate_events INTEGER NOT NULL DEFAULT 0,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_whispers (
      campaign_id TEXT NOT NULL,
      whisper_id TEXT NOT NULL,
      from_character_id TEXT NOT NULL,
      to_character_id TEXT NOT NULL,
      text TEXT NOT NULL,
      PRIMARY KEY (campaign_id, whisper_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_world_events (
      campaign_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      turn_number INTEGER NOT NULL,
      title TEXT NOT NULL,
      text TEXT NOT NULL,
      resolution_turn_number INTEGER,
      resolution_text TEXT,
      PRIMARY KEY (campaign_id, event_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_calendars (
      campaign_id TEXT PRIMARY KEY,
      day INTEGER NOT NULL,
      season TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_settlements (
      campaign_id TEXT NOT NULL,
      settlement_id TEXT NOT NULL,
      name TEXT NOT NULL,
      services_json TEXT NOT NULL,
      availability TEXT NOT NULL,
      PRIMARY KEY (campaign_id, settlement_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_settlement_discoveries (
      campaign_id TEXT NOT NULL,
      settlement_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      PRIMARY KEY (campaign_id, settlement_id, character_id),
      FOREIGN KEY (campaign_id, settlement_id)
        REFERENCES play_campaign_settlements(campaign_id, settlement_id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id)
        REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_shops (
      campaign_id TEXT NOT NULL,
      settlement_id TEXT NOT NULL,
      shop_id TEXT NOT NULL,
      name TEXT NOT NULL,
      buy_price INTEGER NOT NULL,
      sell_price INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, settlement_id, shop_id),
      FOREIGN KEY (campaign_id, settlement_id)
        REFERENCES play_campaign_settlements(campaign_id, settlement_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_shop_stock (
      campaign_id TEXT NOT NULL,
      settlement_id TEXT NOT NULL,
      shop_id TEXT NOT NULL,
      item_id TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, settlement_id, shop_id, item_id),
      FOREIGN KEY (campaign_id, settlement_id, shop_id)
        REFERENCES play_campaign_shops(campaign_id, settlement_id, shop_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_factions (
      campaign_id TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      name TEXT NOT NULL,
      PRIMARY KEY (campaign_id, faction_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_faction_reputation_history (
      campaign_id TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      reputation INTEGER NOT NULL,
      delta INTEGER NOT NULL,
      reason TEXT NOT NULL,
      FOREIGN KEY (campaign_id, faction_id)
        REFERENCES play_campaign_factions(campaign_id, faction_id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id)
        REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_character_equipment (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      slot TEXT NOT NULL,
      item_id TEXT NOT NULL,
      attuned INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, character_id, slot),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id)
        REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_character_health (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      hp_current INTEGER NOT NULL DEFAULT 20,
      hp_max INTEGER NOT NULL DEFAULT 20,
      death_save_successes INTEGER NOT NULL DEFAULT 0,
      death_save_failures INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'conscious',
      PRIMARY KEY (campaign_id, character_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id)
        REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_character_builds (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      class TEXT NOT NULL,
      con_modifier INTEGER NOT NULL,
      abilities_json TEXT NOT NULL,
      level INTEGER NOT NULL DEFAULT 1,
      hp_max INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id)
        REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_character_spells (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      spell_id TEXT NOT NULL,
      name TEXT NOT NULL,
      level INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id, spell_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id)
        REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_character_prepared_spells (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      spell_ids_json TEXT NOT NULL,
      PRIMARY KEY (campaign_id, character_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id)
        REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_character_concentrations (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      spell_id TEXT NOT NULL,
      target TEXT NOT NULL,
      remaining_turns INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id)
        REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_character_casts (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      spell_id TEXT NOT NULL,
      target TEXT NOT NULL,
      slot_level INTEGER NOT NULL,
      slots_remaining INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id, sequence),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id)
        REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_encounters (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL,
      round INTEGER NOT NULL DEFAULT 1,
      turn_index INTEGER NOT NULL DEFAULT 0,
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_encounter_rewards (
      encounter_id TEXT PRIMARY KEY,
      xp INTEGER NOT NULL,
      loot_json TEXT NOT NULL,
      FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_encounter_monsters (
      encounter_id TEXT NOT NULL,
      monster_id TEXT NOT NULL,
      name TEXT NOT NULL,
      hp_max INTEGER NOT NULL,
      hp_current INTEGER NOT NULL,
      initiative INTEGER NOT NULL,
      PRIMARY KEY (encounter_id, monster_id),
      FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_encounter_combatants (
      encounter_id TEXT NOT NULL,
      member TEXT NOT NULL,
      character_id TEXT NOT NULL,
      name TEXT NOT NULL,
      initiative INTEGER NOT NULL,
      PRIMARY KEY (encounter_id, member),
      FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_encounter_conditions (
      id INTEGER PRIMARY KEY,
      encounter_id TEXT NOT NULL,
      target TEXT NOT NULL,
      condition TEXT NOT NULL,
      remaining_rounds INTEGER NOT NULL,
      FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_encounter_turn_orders (
      encounter_id TEXT PRIMARY KEY,
      order_json TEXT NOT NULL,
      FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS play_campaign_encounter_ready_actions (
      encounter_id TEXT NOT NULL,
      actor TEXT NOT NULL,
      trigger TEXT NOT NULL,
      FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id) ON DELETE CASCADE
    );
    CREATE UNIQUE INDEX IF NOT EXISTS play_campaign_one_active_encounter
      ON play_campaign_encounters (campaign_id)
      WHERE status = 'active';
    CREATE TABLE IF NOT EXISTS play_campaign_events (
      campaign_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      kind TEXT NOT NULL,
      actor TEXT NOT NULL,
      type TEXT,
      target TEXT,
      text TEXT NOT NULL,
      PRIMARY KEY (campaign_id, sequence),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
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
      summary TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS campaign_quests (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      title TEXT NOT NULL,
      status TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS quest_milestones (
      quest_id TEXT NOT NULL,
      title TEXT NOT NULL,
      completed INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (quest_id, title),
      FOREIGN KEY (quest_id) REFERENCES campaign_quests(id) ON DELETE CASCADE
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
      name TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      disposition INTEGER NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY (faction_id) REFERENCES campaign_factions(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS campaign_inventory (
      campaign_id TEXT NOT NULL,
      item_slug TEXT NOT NULL,
      owner TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, item_slug, owner),
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS crafting_projects (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      item_slug TEXT NOT NULL,
      days_required INTEGER NOT NULL,
      days_completed INTEGER NOT NULL DEFAULT 0,
      cost_gp REAL NOT NULL,
      status TEXT NOT NULL,
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY (character_id) REFERENCES campaign_characters(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS character_equipment (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      item_slug TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id, item_slug),
      FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY (character_id) REFERENCES campaign_characters(id) ON DELETE CASCADE
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
      status TEXT NOT NULL,
      PRIMARY KEY (session_id, character_id),
      FOREIGN KEY (session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE,
      FOREIGN KEY (character_id) REFERENCES campaign_characters(id) ON DELETE CASCADE
    );
  `);
  // Existing databases from before action submission do not have this
  // optional event attribute.  SQLite has no ADD COLUMN IF NOT EXISTS.
  try {
    database.exec("ALTER TABLE play_campaign_events ADD COLUMN type TEXT");
  } catch {
    // The column already exists.
  }
  try {
    database.exec("ALTER TABLE play_campaign_events ADD COLUMN target TEXT");
  } catch {
    // The column already exists.
  }
  // Encounters created before combat turns were introduced need the same
  // deterministic initial cursor as newly-created encounters.
  try {
    database.exec("ALTER TABLE play_campaign_encounters ADD COLUMN round INTEGER NOT NULL DEFAULT 1");
  } catch {
    // The column already exists.
  }
  try {
    database.exec("ALTER TABLE play_campaign_encounters ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0");
  } catch {
    // The column already exists.
  }
  try {
    database.exec("ALTER TABLE play_campaigns ADD COLUMN phase TEXT NOT NULL DEFAULT 'exploration'");
  } catch {
    // The column already exists.
  }
  try {
    database.exec("ALTER TABLE play_campaign_character_health ADD COLUMN death_save_successes INTEGER NOT NULL DEFAULT 0");
  } catch {
    // The column already exists.
  }
  try {
    database.exec("ALTER TABLE play_campaign_character_health ADD COLUMN death_save_failures INTEGER NOT NULL DEFAULT 0");
  } catch {
    // The column already exists.
  }
  try {
    database.exec("ALTER TABLE play_campaign_character_health ADD COLUMN status TEXT NOT NULL DEFAULT 'conscious'");
  } catch {
    // The column already exists.
  }
  try {
    database.exec("ALTER TABLE play_campaign_character_builds ADD COLUMN abilities_json TEXT NOT NULL DEFAULT '{\"str\":10,\"dex\":10,\"con\":10,\"int\":10,\"wis\":10,\"cha\":10}'");
  } catch {
    // The column already exists.
  }
  try {
    database.exec("ALTER TABLE play_campaign_quests ADD COLUMN rewards_xp INTEGER");
  } catch {
    // The column already exists.
  }
  try {
    database.exec("ALTER TABLE play_campaign_quests ADD COLUMN rewards_items_json TEXT");
  } catch {
    // The column already exists.
  }
  try {
    database.exec("ALTER TABLE play_campaign_quests ADD COLUMN rewards_awarded INTEGER NOT NULL DEFAULT 0");
  } catch {
    // The column already exists.
  }
  // Membership pre-dates explicit ownership.  Existing characters retain the
  // player identity with which they originally joined.
  database.exec(`
    INSERT OR IGNORE INTO play_campaign_character_owners (campaign_id, character_id, owner)
    SELECT campaign_id, character_id, username FROM play_campaign_members
  `);
  // Currency was added after campaign membership.  Preserve the deterministic
  // starting balance for members created by earlier versions as well.
  database.exec(`
    INSERT OR IGNORE INTO play_campaign_character_currency (campaign_id, character_id, gold)
    SELECT campaign_id, character_id, 10 FROM play_campaign_members
  `);
  database.prepare("INSERT OR REPLACE INTO storage_metadata (key, value) VALUES (?, ?)")
    .run("schema_version", String(SCHEMA_VERSION));
}

initializeSchema();

export function storageInitialized(): boolean {
  const row = database.prepare("SELECT value FROM storage_metadata WHERE key = ?").get("schema_version") as { value?: string } | undefined;
  return row?.value === String(SCHEMA_VERSION);
}

export function resetStorage(): void {
  database.exec(`
    DROP TABLE IF EXISTS combat_conditions;
    DROP TABLE IF EXISTS combat_sessions;
    DROP TABLE IF EXISTS compendium_monsters;
    DROP TABLE IF EXISTS compendium_items;
    DROP TABLE IF EXISTS campaign_events;
    DROP TABLE IF EXISTS session_attendance;
    DROP TABLE IF EXISTS campaign_sessions;
    DROP TABLE IF EXISTS character_equipment;
    DROP TABLE IF EXISTS crafting_projects;
    DROP TABLE IF EXISTS campaign_inventory;
    DROP TABLE IF EXISTS campaign_characters;
    DROP TABLE IF EXISTS campaign_npcs;
    DROP TABLE IF EXISTS campaign_factions;
    DROP TABLE IF EXISTS quest_milestones;
    DROP TABLE IF EXISTS campaign_quests;
    DROP TABLE IF EXISTS play_campaign_character_health;
    DROP TABLE IF EXISTS play_campaign_character_concentrations;
    DROP TABLE IF EXISTS play_campaign_character_casts;
    DROP TABLE IF EXISTS play_campaign_character_prepared_spells;
    DROP TABLE IF EXISTS play_campaign_character_spells;
    DROP TABLE IF EXISTS play_campaign_character_builds;
    DROP TABLE IF EXISTS play_campaign_loot_votes;
    DROP TABLE IF EXISTS play_campaign_loot;
    DROP TABLE IF EXISTS play_campaign_faction_reputation_history;
    DROP TABLE IF EXISTS play_campaign_factions;
    DROP TABLE IF EXISTS play_campaign_npc_dialogue;
    DROP TABLE IF EXISTS play_campaign_npcs;
    DROP TABLE IF EXISTS play_campaign_relationships;
    DROP TABLE IF EXISTS play_campaign_clues;
    DROP TABLE IF EXISTS play_campaign_quest_reward_grants;
    DROP TABLE IF EXISTS play_campaign_quests;
    DROP TABLE IF EXISTS play_campaign_content;
    DROP TABLE IF EXISTS play_campaign_notes;
    DROP TABLE IF EXISTS play_campaign_search_records;
    DROP TABLE IF EXISTS play_campaign_metrics;
    DROP TABLE IF EXISTS play_campaign_rate_events;
    DROP TABLE IF EXISTS play_campaign_whispers;
    DROP TABLE IF EXISTS play_campaign_world_events;
    DROP TABLE IF EXISTS play_campaign_calendars;
    DROP TABLE IF EXISTS play_campaign_shop_stock;
    DROP TABLE IF EXISTS play_campaign_shops;
    DROP TABLE IF EXISTS play_campaign_settlement_discoveries;
    DROP TABLE IF EXISTS play_campaign_settlements;
    DROP TABLE IF EXISTS play_campaign_recipes;
    DROP TABLE IF EXISTS play_campaign_downtime_allocations;
    DROP TABLE IF EXISTS play_campaign_downtime_activities;
    DROP TABLE IF EXISTS play_campaign_character_inventory_items;
    DROP TABLE IF EXISTS play_campaign_character_equipment;
    DROP TABLE IF EXISTS play_campaign_transactional_transfers;
    DROP TABLE IF EXISTS play_campaign_currency_transfers;
    DROP TABLE IF EXISTS play_campaign_character_currency;
    DROP TABLE IF EXISTS play_campaign_character_owners;
    DROP TABLE IF EXISTS play_campaign_audit_events;
    DROP TABLE IF EXISTS play_campaign_projection_events;
    DROP TABLE IF EXISTS play_campaign_replay_events;
    DROP TABLE IF EXISTS play_campaign_rng_rolls;
    DROP TABLE IF EXISTS play_campaign_rng_seeds;
    DROP TABLE IF EXISTS play_campaign_idempotent_events;
    DROP TABLE IF EXISTS play_campaign_moderation_reports;
    DROP TABLE IF EXISTS play_campaign_feed_events;
    DROP TABLE IF EXISTS play_campaign_safety_events;
    DROP TABLE IF EXISTS play_campaign_safety_boundaries;
    DROP TABLE IF EXISTS play_campaign_fixture_seeds;
    DROP TABLE IF EXISTS play_campaign_safe_turns;
    DROP TABLE IF EXISTS play_campaign_safe_turn_state;
    DROP TABLE IF EXISTS play_campaign_delegation_audit;
    DROP TABLE IF EXISTS play_campaign_delegations;
    DROP TABLE IF EXISTS play_campaign_spectators;
    DROP TABLE IF EXISTS play_campaign_system_events;
    DROP TABLE IF EXISTS play_campaign_invitations;
    DROP TABLE IF EXISTS play_campaign_members;
    DROP TABLE IF EXISTS play_campaign_encounter_combatants;
    DROP TABLE IF EXISTS play_campaign_encounter_conditions;
    DROP TABLE IF EXISTS play_campaign_encounter_turn_orders;
    DROP TABLE IF EXISTS play_campaign_encounter_ready_actions;
    DROP TABLE IF EXISTS play_campaign_encounter_rewards;
    DROP TABLE IF EXISTS play_campaign_encounter_monsters;
    DROP TABLE IF EXISTS play_campaign_encounters;
    DROP TABLE IF EXISTS play_campaign_events;
    DROP TABLE IF EXISTS play_campaign_session_zero_settings;
    DROP TABLE IF EXISTS play_campaign_documents;
    DROP TABLE IF EXISTS play_campaign_exports;
    DROP TABLE IF EXISTS play_campaign_backups;
    DROP TABLE IF EXISTS play_campaign_import_states;
    DROP TABLE IF EXISTS play_campaign_migration_states;
    DROP TABLE IF EXISTS play_campaign_scene_state;
    DROP TABLE IF EXISTS play_campaign_scenes;
    DROP TABLE IF EXISTS play_campaign_location_connections;
    DROP TABLE IF EXISTS play_campaign_locations;
    DROP TABLE IF EXISTS play_campaigns;
    DROP TABLE IF EXISTS campaigns;
    DROP TABLE IF EXISTS users;
    DROP TABLE IF EXISTS storage_metadata;
  `);
  initializeSchema();
}
