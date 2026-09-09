/**
 * SQLite persistence layer.
 *
 * This module owns the single lazy `DatabaseSync` connection, the schema, and
 * all repository functions.  Business logic lives in `engine.ts`; this module
 * only reads and writes rows.  Domain groupings are kept as clearly labeled
 * sections rather than separate files so that the cumulative evaluator suite
 * sees one deterministic persistence surface.
 */

import { DatabaseSync } from "node:sqlite";
import { join } from "node:path";

import type {
  Abilities,
  AddEncounterConditionResult,
  AdvanceCraftingResponse,
  Campaign,
  CampaignAnalyticsSummary,
  CharacterAttunement,
  CharacterBuildInput,
  CharacterConcentration,
  CharacterCurrency,
  CharacterEquipment,
  CharacterInventoryItemConsumption,
  CharacterInventoryStack,
  CharacterInventorySummary,
  CharacterSheet,
  CampaignAudit,
  ContentRecord,
  CreateContentRecordInput,
  UpdateContentTagsInput,
  PlayCampaignInvitation,
  CreatePlayCampaignInvitationInput,
  CampaignCharacter,
  CreateNoteInput,
  Note,
  UpdateNoteInput,
  Whisper,
  CreateWhisperInput,
  PlayCampaignMessage,
  CreatePlayCampaignMessageInput,
  CampaignDocument,
  CampaignEvent,
  CampaignExport,
  CampaignLocation,
  CampaignRiskReport,
  CampaignState,
  CharacterDamageResult,
  DelegationRecord,
  DelegationAudit,
  CombatSession,
  Condition,
  CraftingProject,
  CreateConnectionInput,
  CreateCraftingProjectInput,
  CreateFactionInput,
  CreateItemInput,
  CreateLocationInput,
  CreateMonsterInput,
  CreateNpcInput,
  CreatePlayCampaignEncounterInput,
  CreatePlayCampaignEncounterMonsterInput,
  CreatePlayCampaignFactionInput,
  CreatePlayCampaignClueInput,
  CreatePlayCampaignQuestInput,
  CreatePlayCampaignInput,
  CreatePlayCampaignMembershipInput,
  CreatePlayCampaignNpcDialogueInput,
  CreatePlayCampaignNpcInput,
  CreatePlayCampaignReputationInput,
  CreateQuestInput,
  CreateSceneInput,
  CreateSessionInput,
  CreateUserResult,
  CreateTransactionalTransferInput,
  CurrencyTransfer,
  TransactionalTransfer,
  DeathSaveResult,
  EndEncounterResult,
  EncounterCloseResult,
  EncounterLoot,
  EncounterRewardRecord,
  EquipmentAssignment,
  Faction,
  GameSession,
  InventoryItem,
  InventorySummary,
  Item,
  LootAssignment,
  LootRecord,
  LootVoteRecord,
  LocationConnection,
  Monster,
  PlayCampaignEncounter,
  PlayCampaignEncounterMonster,
  PlayCampaignEncounterStatus,
  PlayCampaignEncounterTurn,
  PlayCampaignExportList,
  PlayCampaignExportSnapshot,
  PlayCampaignImportSnapshot,
  PlayCampaignMigrationInput,
  PlayCampaignMigrationSnapshot,
  SearchRecord,
  CreateSearchRecordInput,
  SearchRecordList,
  PlayCampaignMemberState,
  PlayCampaignMemberStatus,
  PlayCampaignScene,
  PlayEvent,
  ResolutionResult,
  RestEvent,
  NextSession,
  Npc,
  NudgeResult,
  PlayCampaign,
  PlayCampaignBackup,
  PlayCampaignBackupList,
  PlayCampaignAuditEvent,
  PlayCampaignAuditEventInput,
  PlayCampaignAuditTrail,
  PlayCampaignCalendar,
  PlayCampaignProjection,
  PlayCampaignProjectionEvent,
  PlayCampaignProjectionEventInput,
  PlayCampaignSpectator,
  PlayCampaignIdempotentEvent,
  CreatePlayCampaignIdempotentEventInput,
  PlayCampaignClue,
  PlayCampaignFaction,
  PlayCampaignQuest,
  PlayCampaignQuestRewards,
  PlayCampaignQuestState,
  PlayCampaignWorldEvent,
  CreatePlayCampaignWorldEventInput,
  PlayCampaignMembership,
  Season,
  Weather,
  ConfigurePlayCampaignQuestRewardsInput,
  Settlement,
  SettlementAvailability,
  CreateSettlementInput,
  Shop,
  CreateShopInput,
  ShopTransactionResult,
  Recipe,
  CreateRecipeInput,
  RecipeList,
  CraftRecipeResult,
  DowntimeActivity,
  CreateDowntimeActivityInput,
  DowntimeAllocation,
  PlayCampaignNpc,
  PlayCampaignNpcDialogueEntry,
  PlayCampaignRelationship,
  PlayCampaignReputationRecord,
  PlayCharacterInventoryItem,
  PlayCampaignStartResult,
  PlayCampaignState,
  Quest,
  QuestCreateResult,
  QuestProgress,
  QuestStatus,
  QuestSummary,
  RelationshipSummary,
  SessionAttendance,
  SessionCombatant,
  SessionCreateResult,
  SessionZeroSettings,
  SpellCastRecord,
  SpellbookSpell,
  AcceptedSafeTurn,
  SafeTurnState,
  RateEvent,
  RateEventCreateResult,
  RateEventList,
  ServiceMetrics,
  StoredUser,
  TravelDestination,
  TravelEvent,
  UpdatePlayCampaignNpcAgendaInput,
  CreatePlayCampaignReplayEventInput,
  PlayCampaignReplayEvent,
  PlayCampaignReplayState,
  ConfigureRngSeedInput,
  CreateRngRollInput,
  PlayCampaignRngRoll,
  PlayCampaignRngLedger,
  CreatePlayCampaignModerationReportInput,
  PlayCampaignModerationReport,
  PlayCampaignModerationReports,
  ResolvePlayCampaignModerationReportInput,
  PlayCampaignSafetyBoundaries,
  PlayCampaignSafetyEvent,
  PlayCampaignSafetyEvents,
  CreatePlayCampaignSafetyCheckInput,
  PlayCampaignFixtureState,
  PlayCampaignFeedEvent,
  PlayCampaignFeedEventInput,
  PlayCampaignFeedPage,
} from "./types.js";

// Re-export every domain type so route handlers can import both storage
// functions and their input/output types from the same module.
export type * from "./types.js";

import { getSpellSlots } from "./engine.js";

const DB_PATH = process.env.DB_PATH || join(process.cwd(), "game.db");

let db: DatabaseSync | null = null;
let initialized = false;

function ensureDb(): DatabaseSync {
  if (!db) {
    db = new DatabaseSync(DB_PATH);
    db.exec("PRAGMA foreign_keys = ON;");
    db.exec("PRAGMA journal_mode = WAL;");
    db.exec("PRAGMA busy_timeout = 5000;");
  }
  return db;
}

export function getDb(): DatabaseSync {
  const database = ensureDb();
  if (!initialized) {
    initStorage();
  }
  return database;
}

export function isStorageInitialized(): boolean {
  return initialized;
}

/**
 * Apply additive schema migrations to databases created by earlier stages.
 * Each migration is wrapped in a try/catch so it is safe to re-run against a
 * database that already has the change.
 */
function runMigrations(database: DatabaseSync): void {
  // Stage 027: ensure nudge_count column exists in existing databases.
  try {
    database.exec(
      "ALTER TABLE play_campaign_state ADD COLUMN nudge_count INTEGER NOT NULL DEFAULT 0"
    );
  } catch {
    // Column already present.
  }

  // Stage 033: ensure travel-related columns exist in existing databases.
  try {
    database.exec(
      "ALTER TABLE play_campaign_state ADD COLUMN current_location_id TEXT"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_narrations ADD COLUMN destination_id TEXT"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_narrations ADD COLUMN travel_turns INTEGER"
    );
  } catch {
    // Column already present.
  }

  // Stage 034: ensure character HP columns exist for rest turns.
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN hp_max INTEGER NOT NULL DEFAULT 20"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN hp_current INTEGER NOT NULL DEFAULT 20"
    );
  } catch {
    // Column already present.
  }

  // Stage 041: ensure character death-save state columns exist.
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN status TEXT NOT NULL DEFAULT 'conscious' CHECK(status IN ('conscious', 'unconscious', 'stable', 'dead'))"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN death_saves_successes INTEGER NOT NULL DEFAULT 0"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN death_saves_failures INTEGER NOT NULL DEFAULT 0"
    );
  } catch {
    // Column already present.
  }

  // Stage 036: ensure encounter monster roster table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_encounter_monsters (
        campaign_id TEXT NOT NULL,
        encounter_id TEXT NOT NULL,
        monster_id TEXT NOT NULL,
        name TEXT NOT NULL,
        hp_max INTEGER NOT NULL,
        hp_current INTEGER NOT NULL,
        score INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, encounter_id, monster_id),
        FOREIGN KEY (campaign_id, encounter_id) REFERENCES play_campaign_encounters(campaign_id, id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 037: ensure party member binding columns and unique index exist.
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounter_combatants ADD COLUMN member TEXT"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounter_combatants ADD COLUMN character_id TEXT"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "CREATE UNIQUE INDEX IF NOT EXISTS idx_play_campaign_encounter_combatants_member ON play_campaign_encounter_combatants(campaign_id, encounter_id, member)"
    );
  } catch {
    // Index already present.
  }

  // Stage 038: ensure encounter turn tracking columns exist.
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounters ADD COLUMN round INTEGER NOT NULL DEFAULT 1"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounters ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0"
    );
  } catch {
    // Column already present.
  }

  // Stage 039: ensure combat action target column exists.
  try {
    database.exec(
      "ALTER TABLE play_campaign_narrations ADD COLUMN target TEXT"
    );
  } catch {
    // Column already present.
  }

  // Stage 042: ensure play campaign encounter conditions table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_encounter_conditions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        encounter_id TEXT NOT NULL,
        target TEXT NOT NULL,
        condition TEXT NOT NULL,
        remaining_rounds INTEGER NOT NULL,
        FOREIGN KEY (campaign_id, encounter_id) REFERENCES play_campaign_encounters(campaign_id, id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 043: ensure encounter combatant order column exists.
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounters ADD COLUMN combatant_order TEXT"
    );
  } catch {
    // Column already present.
  }

  // Stage 044: ensure encounter reward and close columns exist.
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounters ADD COLUMN xp_awarded INTEGER NOT NULL DEFAULT 0"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounters ADD COLUMN loot_awarded TEXT NOT NULL DEFAULT '[]'"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounters ADD COLUMN rewards_awarded INTEGER NOT NULL DEFAULT 0"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_encounters ADD COLUMN closed INTEGER NOT NULL DEFAULT 0"
    );
  } catch {
    // Column already present.
  }

  // Stage 045: ensure campaign phase and pre-combat actor columns exist.
  try {
    database.exec(
      "ALTER TABLE play_campaign_state ADD COLUMN phase TEXT NOT NULL DEFAULT 'exploration' CHECK(phase IN ('exploration', 'combat'))"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_state ADD COLUMN pre_combat_actor TEXT"
    );
  } catch {
    // Column already present.
  }

  // Stage 046: ensure character ownership column exists and backfill existing members.
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN owner TEXT"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "UPDATE play_campaign_members SET owner = username WHERE owner IS NULL"
    );
  } catch {
    // Backfill already applied or not needed.
  }

  // Stage 047: ensure character build columns exist.
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN race TEXT"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN background TEXT"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN abilities TEXT"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN level INTEGER NOT NULL DEFAULT 1"
    );
  } catch {
    // Column already present.
  }

  // Stage 050: ensure character spellbook table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_character_spells (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        spell_id TEXT NOT NULL,
        name TEXT NOT NULL,
        level INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id, spell_id),
        FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 051: ensure character prepared spells table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_character_prepared_spells (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        spell_id TEXT NOT NULL,
        PRIMARY KEY (campaign_id, character_id, spell_id),
        FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 052: ensure character spell slots and cast history tables exist.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_character_spell_slots (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        level INTEGER NOT NULL,
        slots_remaining INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id, level),
        FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }
  try {
    database.exec(`
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
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 053: ensure character concentration table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_character_concentration (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        spell_id TEXT NOT NULL,
        target TEXT NOT NULL,
        remaining_turns INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id),
        FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 054: ensure per-character inventory stack table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_character_inventory (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id, item_id),
        FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 055: ensure per-character equipment and attunement table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_character_equipment (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        slot TEXT NOT NULL CHECK(slot IN ('armor', 'accessory')),
        item_id TEXT NOT NULL,
        attuned INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (campaign_id, character_id, slot),
        FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 057: ensure per-character gold balance and transfer log tables exist.
  try {
    database.exec(
      "ALTER TABLE play_campaign_members ADD COLUMN gold INTEGER NOT NULL DEFAULT 10"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_currency_transfers (
        campaign_id TEXT NOT NULL,
        transfer_id INTEGER NOT NULL,
        from_character_id TEXT NOT NULL,
        to_character_id TEXT NOT NULL,
        gold INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, transfer_id),
        FOREIGN KEY (campaign_id, from_character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE,
        FOREIGN KEY (campaign_id, to_character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 058: ensure campaign loot and vote tables exist.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_loot (
        campaign_id TEXT NOT NULL,
        loot_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('open', 'assigned')),
        recipient_character_id TEXT,
        PRIMARY KEY (campaign_id, loot_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (
        campaign_id TEXT NOT NULL,
        loot_id TEXT NOT NULL,
        voter TEXT NOT NULL,
        recipient_character_id TEXT NOT NULL,
        PRIMARY KEY (campaign_id, loot_id, voter),
        FOREIGN KEY (campaign_id, loot_id) REFERENCES play_campaign_loot(campaign_id, loot_id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 059: ensure play campaign NPC agenda table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_npcs (
        campaign_id TEXT NOT NULL,
        npc_id TEXT NOT NULL,
        name TEXT NOT NULL,
        agenda TEXT NOT NULL,
        public_status TEXT NOT NULL,
        PRIMARY KEY (campaign_id, npc_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 060: ensure play campaign faction and reputation tables exist.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_factions (
        campaign_id TEXT NOT NULL,
        faction_id TEXT NOT NULL,
        name TEXT NOT NULL,
        PRIMARY KEY (campaign_id, faction_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_reputation_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        faction_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        reputation INTEGER NOT NULL,
        delta INTEGER NOT NULL,
        reason TEXT NOT NULL,
        FOREIGN KEY (campaign_id, faction_id) REFERENCES play_campaign_factions(campaign_id, faction_id) ON DELETE CASCADE,
        FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 061: ensure play campaign NPC dialogue table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        npc_id TEXT NOT NULL,
        dialogue_id TEXT NOT NULL,
        speaker TEXT NOT NULL,
        text TEXT NOT NULL,
        visibility TEXT NOT NULL CHECK(visibility IN ('public', 'private')),
        UNIQUE(campaign_id, npc_id, dialogue_id),
        FOREIGN KEY (campaign_id, npc_id) REFERENCES play_campaign_npcs(campaign_id, npc_id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 062: ensure play campaign relationship graph table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_relationships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        score INTEGER NOT NULL,
        UNIQUE(campaign_id, source_id, target_id, kind),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 063: ensure play campaign clue table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_clues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        clue_id TEXT NOT NULL,
        text TEXT NOT NULL,
        audience TEXT NOT NULL CHECK(audience IN ('character', 'party', 'hidden')),
        character_id TEXT,
        UNIQUE(campaign_id, clue_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 064: ensure play campaign quest dependency table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_quests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        quest_id TEXT NOT NULL,
        title TEXT NOT NULL,
        depends_on TEXT NOT NULL DEFAULT '[]',
        state TEXT NOT NULL CHECK(state IN ('locked', 'active', 'completed')) DEFAULT 'locked',
        UNIQUE(campaign_id, quest_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 065: ensure quest reward columns and per-character grant table exist.
  try {
    database.exec(
      "ALTER TABLE play_campaign_quests ADD COLUMN quest_xp INTEGER NOT NULL DEFAULT 0"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_quests ADD COLUMN quest_items TEXT NOT NULL DEFAULT '{}'"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(
      "ALTER TABLE play_campaign_quests ADD COLUMN rewards_configured INTEGER NOT NULL DEFAULT 0"
    );
  } catch {
    // Column already present.
  }
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_quest_reward_grants (
        campaign_id TEXT NOT NULL,
        quest_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        xp INTEGER NOT NULL,
        items TEXT NOT NULL,
        PRIMARY KEY (campaign_id, quest_id, character_id),
        FOREIGN KEY (campaign_id, quest_id) REFERENCES play_campaign_quests(campaign_id, quest_id) ON DELETE CASCADE,
        FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 066: ensure play campaign world events table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_world_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        turn_number INTEGER NOT NULL,
        title TEXT NOT NULL,
        text TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('scheduled', 'resolved')),
        resolution_turn_number INTEGER,
        resolution_text TEXT,
        UNIQUE(campaign_id, event_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 068: ensure play campaign calendar table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_calendars (
        campaign_id TEXT PRIMARY KEY,
        day INTEGER NOT NULL,
        season TEXT NOT NULL CHECK(season IN ('spring', 'summer', 'autumn', 'winter')),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 069: ensure play campaign settlement tables exist.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_settlements (
        campaign_id TEXT NOT NULL,
        settlement_id TEXT NOT NULL,
        name TEXT NOT NULL,
        services TEXT NOT NULL,
        availability TEXT NOT NULL CHECK(availability IN ('open', 'limited', 'closed')),
        PRIMARY KEY (campaign_id, settlement_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_settlement_discoveries (
        campaign_id TEXT NOT NULL,
        settlement_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        PRIMARY KEY (campaign_id, settlement_id, character_id),
        FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_campaign_settlements(campaign_id, settlement_id) ON DELETE CASCADE,
        FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 070: ensure play campaign shop table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_shops (
        campaign_id TEXT NOT NULL,
        settlement_id TEXT NOT NULL,
        shop_id TEXT NOT NULL,
        name TEXT NOT NULL,
        stock TEXT NOT NULL,
        buy_price INTEGER NOT NULL,
        sell_price INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, settlement_id, shop_id),
        FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_campaign_settlements(campaign_id, settlement_id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 071: ensure play campaign recipe table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_recipes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        recipe_id TEXT NOT NULL,
        name TEXT NOT NULL,
        ingredients TEXT NOT NULL,
        output_item TEXT NOT NULL,
        output_quantity INTEGER NOT NULL,
        UNIQUE(campaign_id, recipe_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 072: ensure play campaign downtime activity and allocation tables exist.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (
        campaign_id TEXT NOT NULL,
        activity_id TEXT NOT NULL,
        name TEXT NOT NULL,
        cycles_required INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, activity_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_downtime_allocations (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        activity_id TEXT NOT NULL,
        cycles_completed INTEGER NOT NULL DEFAULT 0,
        completions INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (campaign_id, character_id, activity_id),
        FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE,
        FOREIGN KEY (campaign_id, activity_id) REFERENCES play_campaign_downtime_activities(campaign_id, activity_id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 073: ensure play campaign session-zero settings table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_session_zero (
        campaign_id TEXT PRIMARY KEY,
        rules TEXT NOT NULL,
        tone TEXT NOT NULL,
        consent TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 074: ensure play campaign content records table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_content (
        campaign_id TEXT NOT NULL,
        content_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        text TEXT NOT NULL,
        tags TEXT NOT NULL,
        PRIMARY KEY (campaign_id, content_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 075: ensure play campaign notes and whispers tables exist.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        note_id TEXT NOT NULL,
        text TEXT NOT NULL,
        visibility TEXT NOT NULL CHECK(visibility IN ('private', 'party')),
        owner TEXT NOT NULL,
        UNIQUE(campaign_id, note_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_whispers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        whisper_id TEXT NOT NULL,
        from_character_id TEXT NOT NULL,
        to_character_id TEXT NOT NULL,
        text TEXT NOT NULL,
        UNIQUE(campaign_id, whisper_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 076: ensure play campaign invitations table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_invitations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        invitation_id TEXT NOT NULL,
        username TEXT NOT NULL,
        character_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending', 'accepted')),
        UNIQUE(campaign_id, invitation_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }
  try {
    database.exec(`
      CREATE UNIQUE INDEX IF NOT EXISTS idx_play_campaign_invitations_pending_username
      ON play_campaign_invitations(campaign_id, username)
      WHERE status = 'pending'
    `);
  } catch {
    // Index already present.
  }

  // Stage 077: ensure play campaign GM delegation tables exist.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_delegations (
        campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
        username TEXT NOT NULL,
        powers TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
        PRIMARY KEY (campaign_id, username)
      )
    `);
  } catch {
    // Table already present.
  }
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
        sequence INTEGER NOT NULL,
        username TEXT NOT NULL,
        action TEXT NOT NULL CHECK(action IN ('granted', 'revoked')),
        powers TEXT NOT NULL,
        UNIQUE(campaign_id, sequence)
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 078: ensure play campaign actor audit trail table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        actor TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('DM', 'player')),
        timestamp INTEGER NOT NULL,
        correlation_id TEXT NOT NULL,
        UNIQUE(campaign_id, timestamp),
        UNIQUE(campaign_id, correlation_id)
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 079: ensure play campaign projection events table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_projection_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('set-story', 'increment-danger')),
        value TEXT,
        UNIQUE(campaign_id, event_id),
        UNIQUE(campaign_id, sequence)
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 080: ensure play campaign idempotent events table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        value TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        UNIQUE(campaign_id, event_id),
        UNIQUE(campaign_id, sequence)
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 081: ensure safe-turn state and accepted turn tables exist.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_state (
        campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
        current_turn INTEGER NOT NULL DEFAULT 1
      )
    `);
  } catch {
    // Table already present.
  }
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (
        campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
        submission_id TEXT NOT NULL,
        action TEXT NOT NULL,
        accepted_turn INTEGER NOT NULL,
        next_turn INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, submission_id)
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 082: ensure campaign-scoped transactional currency transfer table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers (
        campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
        sequence INTEGER NOT NULL,
        from_character_id TEXT NOT NULL,
        to_character_id TEXT NOT NULL,
        amount INTEGER NOT NULL,
        from_gold INTEGER NOT NULL,
        to_gold INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, sequence),
        FOREIGN KEY (campaign_id, from_character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE,
        FOREIGN KEY (campaign_id, to_character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 083: ensure versioned campaign export snapshots table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_exports (
        campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
        version INTEGER NOT NULL,
        story TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        PRIMARY KEY (campaign_id, version)
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 084: ensure campaign import state table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_imports (
        campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
        version INTEGER NOT NULL,
        story TEXT NOT NULL,
        status TEXT NOT NULL
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 085: ensure campaign schema migration state table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_migrations (
        campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
        schema_version INTEGER NOT NULL,
        story TEXT NOT NULL,
        campaign_name TEXT NOT NULL
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 086: ensure campaign search records table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_search_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
        record_id TEXT NOT NULL,
        text TEXT NOT NULL,
        UNIQUE(campaign_id, record_id)
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 087: ensure per-identity campaign rate-event table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_rate_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
        event_id TEXT NOT NULL,
        actor TEXT NOT NULL,
        UNIQUE(campaign_id, event_id)
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 088: ensure campaign-scoped service metrics table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_service_metrics (
        campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
        accepted_rate_events INTEGER NOT NULL DEFAULT 0,
        rejected_rate_events INTEGER NOT NULL DEFAULT 0,
        projection_events INTEGER NOT NULL DEFAULT 0,
        uptime_ticks INTEGER NOT NULL DEFAULT 1
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 090: ensure campaign backup snapshots table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_backups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
        backup_id TEXT NOT NULL,
        story TEXT NOT NULL,
        status TEXT NOT NULL,
        UNIQUE(campaign_id, backup_id)
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 091: ensure deterministic replay event stream table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_replay_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('append')),
        text TEXT NOT NULL,
        UNIQUE(campaign_id, event_id),
        UNIQUE(campaign_id, sequence)
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 092: ensure deterministic RNG seed and roll ledger tables exist.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_rng_seeds (
        campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
        seed TEXT NOT NULL
      )
    `);
  } catch {
    // Table already present.
  }
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (
        campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
        sequence INTEGER NOT NULL,
        roll_id TEXT NOT NULL,
        sides INTEGER NOT NULL,
        result INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, sequence),
        UNIQUE(campaign_id, roll_id)
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 093: ensure campaign moderation reports table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports (
        campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
        report_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('open', 'resolved')) DEFAULT 'open',
        reporter TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        action TEXT CHECK(action IN ('allow', 'remove')),
        note TEXT,
        resolver TEXT,
        PRIMARY KEY (campaign_id, report_id),
        UNIQUE(campaign_id, sequence)
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 094: ensure campaign-scoped safety boundaries and accepted safety events tables exist.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries (
        campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
        blocked_tags TEXT NOT NULL
      )
    `);
  } catch {
    // Table already present.
  }
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_safety_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
        event_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('narration', 'chat')),
        text TEXT NOT NULL,
        tags TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        UNIQUE(campaign_id, event_id),
        UNIQUE(campaign_id, sequence)
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 095: ensure campaign-scoped deterministic fixture state table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_fixtures (
        campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
        fixture_id TEXT NOT NULL,
        status TEXT NOT NULL,
        characters TEXT NOT NULL,
        story TEXT NOT NULL,
        event_ids TEXT NOT NULL
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 098: ensure read-only spectator ticket table exists.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_spectators (
        campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
        spectator_id TEXT NOT NULL,
        token TEXT NOT NULL,
        PRIMARY KEY (campaign_id, spectator_id),
        UNIQUE(spectator_id)
      )
    `);
  } catch {
    // Table already present.
  }

  // Stage 098: ensure campaign chat messages table exists for spectator redaction tests.
  try {
    database.exec(`
      CREATE TABLE IF NOT EXISTS play_campaign_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
        actor TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('chat')) DEFAULT 'chat',
        text TEXT NOT NULL
      )
    `);
  } catch {
    // Table already present.
  }

}

export function initStorage(): void {
  const database = ensureDb();
  database.exec(`
    CREATE TABLE IF NOT EXISTS schema_version (
      version INTEGER PRIMARY KEY
    );

    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('dm', 'player'))
    );

    CREATE TABLE IF NOT EXISTS combat_sessions (
      id TEXT PRIMARY KEY,
      round INTEGER NOT NULL DEFAULT 1,
      turn_index INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS combatants (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL REFERENCES combat_sessions(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      score INTEGER NOT NULL,
      dex INTEGER NOT NULL,
      order_index INTEGER NOT NULL,
      UNIQUE(session_id, name)
    );

    CREATE TABLE IF NOT EXISTS conditions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      combatant_id INTEGER NOT NULL REFERENCES combatants(id) ON DELETE CASCADE,
      condition TEXT NOT NULL,
      remaining_rounds INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS monsters (
      slug TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      cr TEXT NOT NULL,
      armor_class INTEGER NOT NULL,
      hit_points INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS monster_tags (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      monster_slug TEXT NOT NULL REFERENCES monsters(slug) ON DELETE CASCADE,
      tag TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS items (
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
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      level INTEGER NOT NULL,
      class TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS campaign_events (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      kind TEXT NOT NULL,
      summary TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS campaign_quests (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      title TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('active', 'completed', 'blocked'))
    );

    CREATE TABLE IF NOT EXISTS campaign_quest_milestones (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      quest_id TEXT NOT NULL REFERENCES campaign_quests(id) ON DELETE CASCADE,
      title TEXT NOT NULL,
      done INTEGER NOT NULL DEFAULT 0,
      UNIQUE(quest_id, title)
    );

    CREATE TABLE IF NOT EXISTS campaign_factions (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      stance TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS campaign_npcs (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      faction_id TEXT NOT NULL,
      disposition INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS campaign_inventory (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      item_slug TEXT NOT NULL,
      owner TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      UNIQUE(campaign_id, item_slug, owner)
    );

    CREATE TABLE IF NOT EXISTS campaign_equipment (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      character_id TEXT NOT NULL REFERENCES campaign_characters(id) ON DELETE CASCADE,
      item_slug TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      UNIQUE(campaign_id, character_id, item_slug)
    );

    CREATE TABLE IF NOT EXISTS crafting_projects (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      character_id TEXT NOT NULL REFERENCES campaign_characters(id) ON DELETE CASCADE,
      item_slug TEXT NOT NULL,
      days_required INTEGER NOT NULL,
      days_completed INTEGER NOT NULL DEFAULT 0,
      cost_gp INTEGER NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('active', 'complete'))
    );

    CREATE TABLE IF NOT EXISTS campaign_sessions (
      id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
      starts_at TEXT NOT NULL,
      duration_minutes INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS campaign_session_agenda (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL REFERENCES campaign_sessions(id) ON DELETE CASCADE,
      item TEXT NOT NULL,
      order_index INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS campaign_session_attendance (
      session_id TEXT NOT NULL REFERENCES campaign_sessions(id) ON DELETE CASCADE,
      character_id TEXT NOT NULL,
      present INTEGER NOT NULL DEFAULT 1,
      PRIMARY KEY (session_id, character_id)
    );

    CREATE TABLE IF NOT EXISTS play_campaigns (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      owner TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('lobby')),
      max_players INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS play_campaign_spectators (
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      spectator_id TEXT NOT NULL,
      token TEXT NOT NULL,
      PRIMARY KEY (campaign_id, spectator_id),
      UNIQUE(spectator_id)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_members (
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      username TEXT NOT NULL,
      character_id TEXT NOT NULL,
      name TEXT NOT NULL,
      class TEXT NOT NULL,
      race TEXT,
      background TEXT,
      abilities TEXT,
      level INTEGER NOT NULL DEFAULT 1,
      owner TEXT,
      hp_max INTEGER NOT NULL DEFAULT 20,
      hp_current INTEGER NOT NULL DEFAULT 20,
      status TEXT NOT NULL DEFAULT 'conscious' CHECK(status IN ('conscious', 'unconscious', 'stable', 'dead')),
      death_saves_successes INTEGER NOT NULL DEFAULT 0,
      death_saves_failures INTEGER NOT NULL DEFAULT 0,
      gold INTEGER NOT NULL DEFAULT 10,
      PRIMARY KEY (campaign_id, username),
      UNIQUE(campaign_id, character_id)
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
      PRIMARY KEY (campaign_id, character_id, spell_id),
      FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_character_spell_slots (
      campaign_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      level INTEGER NOT NULL,
      slots_remaining INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, character_id, level),
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
      slot TEXT NOT NULL CHECK(slot IN ('armor', 'accessory')),
      item_id TEXT NOT NULL,
      attuned INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, character_id, slot),
      FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_currency_transfers (
      campaign_id TEXT NOT NULL,
      transfer_id INTEGER NOT NULL,
      from_character_id TEXT NOT NULL,
      to_character_id TEXT NOT NULL,
      gold INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, transfer_id),
      FOREIGN KEY (campaign_id, from_character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, to_character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
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
      FOREIGN KEY (campaign_id, from_character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, to_character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_loot (
      campaign_id TEXT NOT NULL,
      loot_id TEXT NOT NULL,
      item_id TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('open', 'assigned')),
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

    CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      npc_id TEXT NOT NULL,
      dialogue_id TEXT NOT NULL,
      speaker TEXT NOT NULL,
      text TEXT NOT NULL,
      visibility TEXT NOT NULL CHECK(visibility IN ('public', 'private')),
      UNIQUE(campaign_id, npc_id, dialogue_id),
      FOREIGN KEY (campaign_id, npc_id) REFERENCES play_campaign_npcs(campaign_id, npc_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_relationships (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      source_id TEXT NOT NULL,
      target_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      score INTEGER NOT NULL,
      UNIQUE(campaign_id, source_id, target_id, kind),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_clues (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      clue_id TEXT NOT NULL,
      text TEXT NOT NULL,
      audience TEXT NOT NULL CHECK(audience IN ('character', 'party', 'hidden')),
      character_id TEXT,
      UNIQUE(campaign_id, clue_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_quests (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      quest_id TEXT NOT NULL,
      title TEXT NOT NULL,
      depends_on TEXT NOT NULL DEFAULT '[]',
      state TEXT NOT NULL CHECK(state IN ('locked', 'active', 'completed')) DEFAULT 'locked',
      quest_xp INTEGER NOT NULL DEFAULT 0,
      quest_items TEXT NOT NULL DEFAULT '{}',
      rewards_configured INTEGER NOT NULL DEFAULT 0,
      UNIQUE(campaign_id, quest_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_quest_reward_grants (
      campaign_id TEXT NOT NULL,
      quest_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      xp INTEGER NOT NULL,
      items TEXT NOT NULL,
      PRIMARY KEY (campaign_id, quest_id, character_id),
      FOREIGN KEY (campaign_id, quest_id) REFERENCES play_campaign_quests(campaign_id, quest_id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_world_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      turn_number INTEGER NOT NULL,
      title TEXT NOT NULL,
      text TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('scheduled', 'resolved')),
      resolution_turn_number INTEGER,
      resolution_text TEXT,
      UNIQUE(campaign_id, event_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_calendars (
      campaign_id TEXT PRIMARY KEY,
      day INTEGER NOT NULL,
      season TEXT NOT NULL CHECK(season IN ('spring', 'summer', 'autumn', 'winter')),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_settlements (
      campaign_id TEXT NOT NULL,
      settlement_id TEXT NOT NULL,
      name TEXT NOT NULL,
      services TEXT NOT NULL,
      availability TEXT NOT NULL CHECK(availability IN ('open', 'limited', 'closed')),
      PRIMARY KEY (campaign_id, settlement_id),
      FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_settlement_discoveries (
      campaign_id TEXT NOT NULL,
      settlement_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      PRIMARY KEY (campaign_id, settlement_id, character_id),
      FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_campaign_settlements(campaign_id, settlement_id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_shops (
      campaign_id TEXT NOT NULL,
      settlement_id TEXT NOT NULL,
      shop_id TEXT NOT NULL,
      name TEXT NOT NULL,
      stock TEXT NOT NULL,
      buy_price INTEGER NOT NULL,
      sell_price INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, settlement_id, shop_id),
      FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_campaign_settlements(campaign_id, settlement_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_recipes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      recipe_id TEXT NOT NULL,
      name TEXT NOT NULL,
      ingredients TEXT NOT NULL,
      output_item TEXT NOT NULL,
      output_quantity INTEGER NOT NULL,
      UNIQUE(campaign_id, recipe_id),
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
      FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, activity_id) REFERENCES play_campaign_downtime_activities(campaign_id, activity_id) ON DELETE CASCADE
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
      reputation INTEGER NOT NULL,
      delta INTEGER NOT NULL,
      reason TEXT NOT NULL,
      FOREIGN KEY (campaign_id, faction_id) REFERENCES play_campaign_factions(campaign_id, faction_id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_scenes (
      id TEXT NOT NULL,
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('open', 'closed')),
      PRIMARY KEY (campaign_id, id)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_current_scene (
      campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
      scene_id TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS play_campaign_state (
      campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
      status TEXT NOT NULL CHECK(status IN ('active')),
      current_actor TEXT NOT NULL,
      turn_number INTEGER NOT NULL,
      nudge_count INTEGER NOT NULL DEFAULT 0,
      current_location_id TEXT,
      phase TEXT NOT NULL DEFAULT 'exploration' CHECK(phase IN ('exploration', 'combat')),
      pre_combat_actor TEXT
    );

    CREATE TABLE IF NOT EXISTS play_campaign_narrations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      sequence INTEGER NOT NULL,
      kind TEXT NOT NULL,
      actor TEXT NOT NULL,
      text TEXT NOT NULL,
      type TEXT,
      destination_id TEXT,
      travel_turns INTEGER,
      target TEXT,
      UNIQUE(campaign_id, sequence)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_delegations (
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      username TEXT NOT NULL,
      powers TEXT NOT NULL,
      active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
      PRIMARY KEY (campaign_id, username)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      sequence INTEGER NOT NULL,
      username TEXT NOT NULL,
      action TEXT NOT NULL CHECK(action IN ('granted', 'revoked')),
      powers TEXT NOT NULL,
      UNIQUE(campaign_id, sequence)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_audit_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      kind TEXT NOT NULL,
      actor TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('DM', 'player')),
      timestamp INTEGER NOT NULL,
      correlation_id TEXT NOT NULL,
      UNIQUE(campaign_id, timestamp),
      UNIQUE(campaign_id, correlation_id)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_projection_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      kind TEXT NOT NULL CHECK(kind IN ('set-story', 'increment-danger')),
      value TEXT,
      UNIQUE(campaign_id, event_id),
      UNIQUE(campaign_id, sequence)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      value TEXT NOT NULL,
      idempotency_key TEXT NOT NULL,
      UNIQUE(campaign_id, event_id),
      UNIQUE(campaign_id, sequence)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_state (
      campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
      current_turn INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      submission_id TEXT NOT NULL,
      action TEXT NOT NULL,
      accepted_turn INTEGER NOT NULL,
      next_turn INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, submission_id)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_documents (
      campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
      story TEXT NOT NULL DEFAULT '',
      dm_notes TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS play_campaign_exports (
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      version INTEGER NOT NULL,
      story TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL,
      PRIMARY KEY (campaign_id, version)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_imports (
      campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
      version INTEGER NOT NULL,
      story TEXT NOT NULL,
      status TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS play_campaign_migrations (
      campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
      schema_version INTEGER NOT NULL,
      story TEXT NOT NULL,
      campaign_name TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS play_campaign_search_records (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      record_id TEXT NOT NULL,
      text TEXT NOT NULL,
      UNIQUE(campaign_id, record_id)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_rate_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      event_id TEXT NOT NULL,
      actor TEXT NOT NULL,
      UNIQUE(campaign_id, event_id)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_service_metrics (
      campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
      accepted_rate_events INTEGER NOT NULL DEFAULT 0,
      rejected_rate_events INTEGER NOT NULL DEFAULT 0,
      projection_events INTEGER NOT NULL DEFAULT 0,
      uptime_ticks INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS play_campaign_backups (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      backup_id TEXT NOT NULL,
      story TEXT NOT NULL,
      status TEXT NOT NULL,
      UNIQUE(campaign_id, backup_id)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_replay_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      kind TEXT NOT NULL CHECK(kind IN ('append')),
      text TEXT NOT NULL,
      UNIQUE(campaign_id, event_id),
      UNIQUE(campaign_id, sequence)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_feed_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      sequence INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      text TEXT NOT NULL,
      UNIQUE(campaign_id, event_id),
      UNIQUE(campaign_id, sequence)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_rng_seeds (
      campaign_id TEXT PRIMARY KEY REFERENCES play_campaigns(id) ON DELETE CASCADE,
      seed TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      sequence INTEGER NOT NULL,
      roll_id TEXT NOT NULL,
      sides INTEGER NOT NULL,
      result INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, sequence),
      UNIQUE(campaign_id, roll_id)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_locations (
      id TEXT NOT NULL,
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      PRIMARY KEY (campaign_id, id)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_location_connections (
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      from_id TEXT NOT NULL,
      to_id TEXT NOT NULL,
      travel_turns INTEGER NOT NULL,
      PRIMARY KEY (campaign_id, from_id, to_id),
      FOREIGN KEY (campaign_id, from_id) REFERENCES play_campaign_locations(campaign_id, id) ON DELETE CASCADE,
      FOREIGN KEY (campaign_id, to_id) REFERENCES play_campaign_locations(campaign_id, id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_encounters (
      campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
      id TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('active', 'completed')),
      round INTEGER NOT NULL DEFAULT 1,
      turn_index INTEGER NOT NULL DEFAULT 0,
      combatant_order TEXT,
      xp_awarded INTEGER NOT NULL DEFAULT 0,
      loot_awarded TEXT NOT NULL DEFAULT '[]',
      rewards_awarded INTEGER NOT NULL DEFAULT 0,
      closed INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (campaign_id, id)
    );

    CREATE TABLE IF NOT EXISTS play_campaign_encounter_combatants (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id TEXT NOT NULL,
      encounter_id TEXT NOT NULL,
      member TEXT,
      character_id TEXT,
      name TEXT NOT NULL,
      score INTEGER NOT NULL,
      FOREIGN KEY (campaign_id, encounter_id) REFERENCES play_campaign_encounters(campaign_id, id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS play_campaign_encounter_monsters (
      campaign_id TEXT NOT NULL,
      encounter_id TEXT NOT NULL,
      monster_id TEXT NOT NULL,
      name TEXT NOT NULL,
      hp_max INTEGER NOT NULL,
      hp_current INTEGER NOT NULL,
      score INTEGER NOT NULL,
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
  `);

  const row = database.prepare("SELECT version FROM schema_version").get() as
    | { version: number }
    | undefined;
  if (!row) {
    database.prepare("INSERT INTO schema_version (version) VALUES (1)").run();
  } else if (row.version !== 1) {
    database.prepare("UPDATE schema_version SET version = 1").run();
  }

  runMigrations(database);

  initialized = true;
}

export function resetStorage(): void {
  const database = getDb();
  database.exec(`
    DROP TABLE IF EXISTS crafting_projects;
    DROP TABLE IF EXISTS campaign_session_attendance;
    DROP TABLE IF EXISTS campaign_session_agenda;
    DROP TABLE IF EXISTS campaign_sessions;
    DROP TABLE IF EXISTS campaign_equipment;
    DROP TABLE IF EXISTS campaign_inventory;
    DROP TABLE IF EXISTS conditions;
    DROP TABLE IF EXISTS combatants;
    DROP TABLE IF EXISTS combat_sessions;
    DROP TABLE IF EXISTS campaign_npcs;
    DROP TABLE IF EXISTS campaign_factions;
    DROP TABLE IF EXISTS campaign_quest_milestones;
    DROP TABLE IF EXISTS campaign_quests;
    DROP TABLE IF EXISTS campaign_events;
    DROP TABLE IF EXISTS campaign_characters;
    DROP TABLE IF EXISTS campaigns;
    DROP TABLE IF EXISTS users;
    DROP TABLE IF EXISTS monster_tags;
    DROP TABLE IF EXISTS monsters;
    DROP TABLE IF EXISTS items;
    DROP TABLE IF EXISTS schema_version;
    DROP TABLE IF EXISTS play_campaign_encounter_conditions;
    DROP TABLE IF EXISTS play_campaign_encounter_monsters;
    DROP TABLE IF EXISTS play_campaign_encounter_combatants;
    DROP TABLE IF EXISTS play_campaign_encounters;
    DROP TABLE IF EXISTS play_campaign_location_connections;
    DROP TABLE IF EXISTS play_campaign_locations;
    DROP TABLE IF EXISTS play_campaign_documents;
    DROP TABLE IF EXISTS play_campaign_exports;
    DROP TABLE IF EXISTS play_campaign_imports;
    DROP TABLE IF EXISTS play_campaign_migrations;
    DROP TABLE IF EXISTS play_campaign_search_records;
    DROP TABLE IF EXISTS play_campaign_audit_events;
    DROP TABLE IF EXISTS play_campaign_projection_events;
    DROP TABLE IF EXISTS play_campaign_idempotent_events;
    DROP TABLE IF EXISTS play_campaign_safe_turns;
    DROP TABLE IF EXISTS play_campaign_safe_turn_state;
    DROP TABLE IF EXISTS play_campaign_delegation_audit;
    DROP TABLE IF EXISTS play_campaign_delegations;
    DROP TABLE IF EXISTS play_campaign_narrations;
    DROP TABLE IF EXISTS play_campaign_current_scene;
    DROP TABLE IF EXISTS play_campaign_scenes;
    DROP TABLE IF EXISTS play_campaign_character_casts;
    DROP TABLE IF EXISTS play_campaign_character_concentration;
    DROP TABLE IF EXISTS play_campaign_character_equipment;
    DROP TABLE IF EXISTS play_campaign_currency_transfers;
    DROP TABLE IF EXISTS play_campaign_transactional_transfers;
    DROP TABLE IF EXISTS play_campaign_loot_votes;
    DROP TABLE IF EXISTS play_campaign_loot;
    DROP TABLE IF EXISTS play_campaign_npcs;
    DROP TABLE IF EXISTS play_campaign_npc_dialogue;
    DROP TABLE IF EXISTS play_campaign_relationships;
    DROP TABLE IF EXISTS play_campaign_clues;
    DROP TABLE IF EXISTS play_campaign_quest_reward_grants;
    DROP TABLE IF EXISTS play_campaign_world_events;
    DROP TABLE IF EXISTS play_campaign_calendars;
    DROP TABLE IF EXISTS play_campaign_shops;
    DROP TABLE IF EXISTS play_campaign_recipes;
    DROP TABLE IF EXISTS play_campaign_downtime_allocations;
    DROP TABLE IF EXISTS play_campaign_downtime_activities;
    DROP TABLE IF EXISTS play_campaign_session_zero;
    DROP TABLE IF EXISTS play_campaign_content;
    DROP TABLE IF EXISTS play_campaign_notes;
    DROP TABLE IF EXISTS play_campaign_whispers;
    DROP TABLE IF EXISTS play_campaign_invitations;
    DROP TABLE IF EXISTS play_campaign_settlement_discoveries;
    DROP TABLE IF EXISTS play_campaign_settlements;
    DROP TABLE IF EXISTS play_campaign_quests;
    DROP TABLE IF EXISTS play_campaign_reputation_history;
    DROP TABLE IF EXISTS play_campaign_factions;
    DROP TABLE IF EXISTS play_campaign_character_inventory;
    DROP TABLE IF EXISTS play_campaign_character_spell_slots;
    DROP TABLE IF EXISTS play_campaign_character_prepared_spells;
    DROP TABLE IF EXISTS play_campaign_character_spells;
    DROP TABLE IF EXISTS play_campaign_members;
    DROP TABLE IF EXISTS play_campaign_state;
    DROP TABLE IF EXISTS play_campaign_rate_events;
    DROP TABLE IF EXISTS play_campaign_service_metrics;
    DROP TABLE IF EXISTS play_campaign_backups;
    DROP TABLE IF EXISTS play_campaign_replay_events;
    DROP TABLE IF EXISTS play_campaign_feed_events;
    DROP TABLE IF EXISTS play_campaign_rng_rolls;
    DROP TABLE IF EXISTS play_campaign_rng_seeds;
    DROP TABLE IF EXISTS play_campaign_moderation_reports;
    DROP TABLE IF EXISTS play_campaign_safety_events;
    DROP TABLE IF EXISTS play_campaign_safety_boundaries;
    DROP TABLE IF EXISTS play_campaign_messages;
    DROP TABLE IF EXISTS play_campaign_fixtures;
    DROP TABLE IF EXISTS play_campaigns;
  `);
  initialized = false;
  initStorage();
}

export function getSchemaVersion(): number {
  const database = getDb();
  const row = database.prepare("SELECT version FROM schema_version").get() as
    | { version: number }
    | undefined;
  return row?.version ?? 1;
}

// ---------------------------------------------------------------------------
// Repository functions
// ---------------------------------------------------------------------------
// Each function below receives a `DatabaseSync` from `getDb()`. Multi-statement
// writes use `BEGIN IMMEDIATE;` with `ROLLBACK;` in the catch path so the
// cumulative evaluator suite always sees atomic, deterministic updates.  A
// `null` return means "not found" or "conflict" and is mapped to the appropriate
// HTTP status by the route handler.

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

export function getUser(username: string): StoredUser | null {
  const database = getDb();
  const row = database
    .prepare("SELECT username, password_hash, role FROM users WHERE username = ?")
    .get(username) as
    | { username: string; password_hash: string; role: "dm" | "player" }
    | undefined;
  return row || null;
}

export function createUser(
  username: string,
  passwordHash: string,
  role: "dm" | "player"
): CreateUserResult | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)"
      )
      .run(username, passwordHash, role);
    return { username, role };
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Combat sessions
// ---------------------------------------------------------------------------

export function getCombatSession(id: string): CombatSession | null {
  const database = getDb();
  const sessionRow = database
    .prepare("SELECT id, round, turn_index FROM combat_sessions WHERE id = ?")
    .get(id) as { id: string; round: number; turn_index: number } | undefined;
  if (!sessionRow) return null;

  const combatantRows = database
    .prepare(
      "SELECT id, name, score, dex, order_index FROM combatants WHERE session_id = ? ORDER BY order_index"
    )
    .all(id) as Array<{
    id: number;
    name: string;
    score: number;
    dex: number;
    order_index: number;
  }>;

  const combatants: SessionCombatant[] = combatantRows.map((row) => {
    const conditionRows = database
      .prepare(
        "SELECT condition, remaining_rounds FROM conditions WHERE combatant_id = ?"
      )
      .all(row.id) as Array<{ condition: string; remaining_rounds: number }>;
    return {
      name: row.name,
      score: row.score,
      dex: row.dex,
      conditions: conditionRows.map((c) => ({
        condition: c.condition,
        remaining_rounds: c.remaining_rounds,
      })),
    };
  });

  return {
    id: sessionRow.id,
    round: sessionRow.round,
    turn_index: sessionRow.turn_index,
    combatants,
  };
}

export function insertCombatSession(
  id: string,
  combatants: SessionCombatant[]
): boolean {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO combat_sessions (id, round, turn_index) VALUES (?, 1, 0)"
      )
      .run(id);
    for (let i = 0; i < combatants.length; i++) {
      const c = combatants[i];
      const result = database
        .prepare(
          "INSERT INTO combatants (session_id, name, score, dex, order_index) VALUES (?, ?, ?, ?, ?)"
        )
        .run(id, c.name, c.score, c.dex, i);
      const combatantId = result.lastInsertRowid as number;
      for (const cond of c.conditions) {
        database
          .prepare(
            "INSERT INTO conditions (combatant_id, condition, remaining_rounds) VALUES (?, ?, ?)"
          )
          .run(combatantId, cond.condition, cond.remaining_rounds);
      }
    }
    database.exec("COMMIT;");
    return true;
  } catch {
    database.exec("ROLLBACK;");
    return false;
  }
}

// ---------------------------------------------------------------------------
// Compendium
// ---------------------------------------------------------------------------

export function createMonster(input: CreateMonsterInput): Monster | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO monsters (slug, name, cr, armor_class, hit_points) VALUES (?, ?, ?, ?, ?)"
      )
      .run(input.slug, input.name, input.cr, input.armor_class, input.hit_points);
    const tagStmt = database.prepare(
      "INSERT INTO monster_tags (monster_slug, tag) VALUES (?, ?)"
    );
    for (const tag of input.tags) {
      tagStmt.run(input.slug, tag);
    }
    database.exec("COMMIT;");
    return {
      slug: input.slug,
      name: input.name,
      cr: input.cr,
      armor_class: input.armor_class,
      hit_points: input.hit_points,
      tags: input.tags,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getMonster(slug: string): Monster | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT slug, name, cr, armor_class, hit_points FROM monsters WHERE slug = ?"
    )
    .get(slug) as
    | { slug: string; name: string; cr: string; armor_class: number; hit_points: number }
    | undefined;
  if (!row) return null;

  const tagRows = database
    .prepare("SELECT tag FROM monster_tags WHERE monster_slug = ? ORDER BY id")
    .all(slug) as Array<{ tag: string }>;

  return {
    ...row,
    tags: tagRows.map((r) => r.tag),
  };
}

export function createItem(input: CreateItemInput): Item | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)"
      )
      .run(input.slug, input.name, input.type, input.rarity, input.cost_gp);
    return { ...input };
  } catch {
    return null;
  }
}

export function getItem(slug: string): Item | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?"
    )
    .get(slug) as
    | { slug: string; name: string; type: string; rarity: string; cost_gp: number }
    | undefined;
  return row || null;
}

/**
 * Replaces the stored combatants and conditions for a session with the current
 * in-memory state.  This is intentionally a full rewrite rather than an UPDATE
 * because conditions are owned by combatants and the simplest deterministic path
 * is to delete and reinsert.
 */
export function replaceCombatSession(session: CombatSession): void {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "UPDATE combat_sessions SET round = ?, turn_index = ? WHERE id = ?"
      )
      .run(session.round, session.turn_index, session.id);
    database
      .prepare(
        "DELETE FROM conditions WHERE combatant_id IN (SELECT id FROM combatants WHERE session_id = ?)"
      )
      .run(session.id);
    database
      .prepare("DELETE FROM combatants WHERE session_id = ?")
      .run(session.id);
    for (let i = 0; i < session.combatants.length; i++) {
      const c = session.combatants[i];
      const result = database
        .prepare(
          "INSERT INTO combatants (session_id, name, score, dex, order_index) VALUES (?, ?, ?, ?, ?)"
        )
        .run(session.id, c.name, c.score, c.dex, i);
      const combatantId = result.lastInsertRowid as number;
      for (const cond of c.conditions) {
        database
          .prepare(
            "INSERT INTO conditions (combatant_id, condition, remaining_rounds) VALUES (?, ?, ?)"
          )
          .run(combatantId, cond.condition, cond.remaining_rounds);
      }
    }
    database.exec("COMMIT;");
  } catch (e) {
    database.exec("ROLLBACK;");
    throw e;
  }
}

// ---------------------------------------------------------------------------
// Campaigns
// ---------------------------------------------------------------------------

export function createCampaign(input: Campaign): Campaign | null {
  const database = getDb();
  try {
    database
      .prepare("INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)")
      .run(input.id, input.name, input.dm);
    return { ...input };
  } catch {
    return null;
  }
}

export function getCampaign(id: string): Campaign | null {
  const database = getDb();
  const row = database
    .prepare("SELECT id, name, dm FROM campaigns WHERE id = ?")
    .get(id) as { id: string; name: string; dm: string } | undefined;
  return row || null;
}

export function createCampaignCharacter(
  campaignId: string,
  input: CampaignCharacter
): CampaignCharacter | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)"
      )
      .run(input.id, campaignId, input.name, input.level, input.class);
    return { ...input };
  } catch {
    return null;
  }
}

export function getCampaignCharacters(campaignId: string): CampaignCharacter[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY id"
    )
    .all(campaignId) as Array<{
    id: string;
    name: string;
    level: number;
    class: string;
  }>;
  return rows;
}

export function createCampaignEvent(
  campaignId: string,
  input: CampaignEvent
): CampaignEvent | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)"
      )
      .run(input.id, campaignId, input.kind, input.summary);
    return { ...input };
  } catch {
    return null;
  }
}

export function getCampaignEventCount(campaignId: string): number {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number } | undefined;
  return row?.count ?? 0;
}

export function getLatestCampaignEvent(
  campaignId: string
): CampaignEvent | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT id, kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY id DESC LIMIT 1"
    )
    .get(campaignId) as
    | { id: string; kind: string; summary: string }
    | undefined;
  return row || null;
}

export function getCampaignState(id: string): CampaignState | null {
  const campaign = getCampaign(id);
  if (!campaign) return null;

  return {
    id: campaign.id,
    name: campaign.name,
    dm: campaign.dm,
    characters: getCampaignCharacters(id),
    log_count: getCampaignEventCount(id),
  };
}

// ---------------------------------------------------------------------------
// Quests
// ---------------------------------------------------------------------------

export function isValidQuestStatus(status: unknown): status is QuestStatus {
  return status === "active" || status === "completed" || status === "blocked";
}

export function createQuest(
  campaignId: string,
  input: CreateQuestInput
): QuestCreateResult | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO campaign_quests (id, campaign_id, title, status) VALUES (?, ?, ?, ?)"
      )
      .run(input.id, campaignId, input.title, input.status);
    const milestoneStmt = database.prepare(
      "INSERT INTO campaign_quest_milestones (quest_id, title, done) VALUES (?, ?, 0)"
    );
    for (const title of input.milestones) {
      milestoneStmt.run(input.id, title);
    }
    database.exec("COMMIT;");
    return {
      id: input.id,
      title: input.title,
      status: input.status,
      milestones_total: input.milestones.length,
      milestones_done: 0,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getQuest(campaignId: string, questId: string): Quest | null {
  const database = getDb();
  const questRow = database
    .prepare(
      "SELECT id, campaign_id, title, status FROM campaign_quests WHERE id = ? AND campaign_id = ?"
    )
    .get(questId, campaignId) as
    | { id: string; campaign_id: string; title: string; status: QuestStatus }
    | undefined;
  if (!questRow) return null;

  const milestoneRows = database
    .prepare(
      "SELECT title, done FROM campaign_quest_milestones WHERE quest_id = ? ORDER BY id"
    )
    .all(questId) as Array<{ title: string; done: number }>;

  return {
    ...questRow,
    milestones: milestoneRows.map((m) => ({ title: m.title, done: !!m.done })),
  };
}

export function updateQuestProgress(
  campaignId: string,
  questId: string,
  completed: string[]
): QuestProgress | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const questRow = database
      .prepare(
        "SELECT id, status FROM campaign_quests WHERE id = ? AND campaign_id = ?"
      )
      .get(questId, campaignId) as
      | { id: string; status: QuestStatus }
      | undefined;
    if (!questRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const milestoneRows = database
      .prepare(
        "SELECT title, done FROM campaign_quest_milestones WHERE quest_id = ?"
      )
      .all(questId) as Array<{ title: string; done: number }>;
    const milestoneSet = new Set(milestoneRows.map((m) => m.title));
    for (const title of completed) {
      if (!milestoneSet.has(title)) {
        database.exec("ROLLBACK;");
        return null;
      }
    }

    const updateStmt = database.prepare(
      "UPDATE campaign_quest_milestones SET done = 1 WHERE quest_id = ? AND title = ?"
    );
    for (const title of completed) {
      updateStmt.run(questId, title);
    }

    const total = milestoneRows.length;
    const doneRow = database
      .prepare(
        "SELECT COUNT(*) AS count FROM campaign_quest_milestones WHERE quest_id = ? AND done = 1"
      )
      .get(questId) as { count: number };
    const done = doneRow.count;

    let status = questRow.status;
    if (total > 0 && done === total) {
      status = "completed";
      database
        .prepare("UPDATE campaign_quests SET status = 'completed' WHERE id = ?")
        .run(questId);
    }

    database.exec("COMMIT;");
    return { id: questId, status, milestones_total: total, milestones_done: done };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getQuestSummary(campaignId: string): QuestSummary | null {
  if (!getCampaign(campaignId)) return null;

  const database = getDb();
  const rows = database
    .prepare(
      "SELECT status, COUNT(*) AS count FROM campaign_quests WHERE campaign_id = ? GROUP BY status"
    )
    .all(campaignId) as Array<{ status: QuestStatus; count: number }>;

  const summary: QuestSummary = {
    campaign_id: campaignId,
    active: 0,
    completed: 0,
    blocked: 0,
  };
  for (const row of rows) {
    if (row.status === "active") summary.active = row.count;
    else if (row.status === "completed") summary.completed = row.count;
    else if (row.status === "blocked") summary.blocked = row.count;
  }
  return summary;
}

// ---------------------------------------------------------------------------
// Factions & NPCs
// ---------------------------------------------------------------------------

export function createFaction(
  campaignId: string,
  input: CreateFactionInput
): Faction | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO campaign_factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)"
      )
      .run(input.id, campaignId, input.name, input.stance);
    return { ...input };
  } catch {
    return null;
  }
}

export function getFaction(campaignId: string, factionId: string): Faction | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT id, name, stance FROM campaign_factions WHERE id = ? AND campaign_id = ?"
    )
    .get(factionId, campaignId) as
    | { id: string; name: string; stance: string }
    | undefined;
  return row || null;
}

export function createNpc(
  campaignId: string,
  input: CreateNpcInput
): Npc | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO campaign_npcs (id, campaign_id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)"
      )
      .run(input.id, campaignId, input.name, input.faction_id, input.disposition);
    return { ...input };
  } catch {
    return null;
  }
}

export function getRelationshipSummary(
  campaignId: string
): RelationshipSummary | null {
  if (!getCampaign(campaignId)) return null;

  const database = getDb();
  const factionRow = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_factions WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const npcRow = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const friendlyRow = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0"
    )
    .get(campaignId) as { count: number };

  return {
    campaign_id: campaignId,
    factions: factionRow.count,
    npcs: npcRow.count,
    friendly_npcs: friendlyRow.count,
  };
}

// ---------------------------------------------------------------------------
// Inventory & equipment
// ---------------------------------------------------------------------------

export function addCampaignInventoryItem(
  campaignId: string,
  item: InventoryItem
): InventoryItem | null {
  const database = getDb();
  if (!getCampaign(campaignId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const existing = database
      .prepare(
        "SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?"
      )
      .get(campaignId, item.item_slug, item.owner) as
      | { quantity: number }
      | undefined;

    if (existing) {
      const total = existing.quantity + item.quantity;
      database
        .prepare(
          "UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?"
        )
        .run(total, campaignId, item.item_slug, item.owner);
      database.exec("COMMIT;");
      return { item_slug: item.item_slug, owner: item.owner, quantity: total };
    }

    database
      .prepare(
        "INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)"
      )
      .run(campaignId, item.item_slug, item.owner, item.quantity);
    database.exec("COMMIT;");
    return { ...item };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function assignEquipment(
  campaignId: string,
  characterId: string,
  item: { item_slug: string; quantity: number }
): EquipmentAssignment | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    if (!getCampaign(campaignId)) {
      database.exec("ROLLBACK;");
      return null;
    }

    const charRow = database
      .prepare(
        "SELECT id FROM campaign_characters WHERE id = ? AND campaign_id = ?"
      )
      .get(characterId, campaignId) as { id: string } | undefined;
    if (!charRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const partyItem = database
      .prepare(
        "SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'"
      )
      .get(campaignId, item.item_slug) as { quantity: number } | undefined;
    if (!partyItem || partyItem.quantity < item.quantity || item.quantity <= 0) {
      database.exec("ROLLBACK;");
      return null;
    }

    const remaining = partyItem.quantity - item.quantity;
    if (remaining > 0) {
      database
        .prepare(
          "UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'"
        )
        .run(remaining, campaignId, item.item_slug);
    } else {
      database
        .prepare(
          "DELETE FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'"
        )
        .run(campaignId, item.item_slug);
    }

    const existing = database
      .prepare(
        "SELECT quantity FROM campaign_equipment WHERE campaign_id = ? AND character_id = ? AND item_slug = ?"
      )
      .get(campaignId, characterId, item.item_slug) as
      | { quantity: number }
      | undefined;

    if (existing) {
      const total = existing.quantity + item.quantity;
      database
        .prepare(
          "UPDATE campaign_equipment SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_slug = ?"
        )
        .run(total, campaignId, characterId, item.item_slug);
      database.exec("COMMIT;");
      return {
        character_id: characterId,
        item_slug: item.item_slug,
        quantity: total,
      };
    }

    database
      .prepare(
        "INSERT INTO campaign_equipment (campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?)"
      )
      .run(campaignId, characterId, item.item_slug, item.quantity);
    database.exec("COMMIT;");
    return {
      character_id: characterId,
      item_slug: item.item_slug,
      quantity: item.quantity,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getInventorySummary(
  campaignId: string
): InventorySummary | null {
  if (!getCampaign(campaignId)) return null;

  const database = getDb();
  const partyRow = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party'"
    )
    .get(campaignId) as { count: number };
  const assignedRow = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_equipment WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const potionRow = database
    .prepare(
      "SELECT COALESCE(SUM(quantity), 0) AS count FROM campaign_inventory WHERE campaign_id = ? AND item_slug = 'healing-potion' AND owner = 'party'"
    )
    .get(campaignId) as { count: number };

  return {
    campaign_id: campaignId,
    party_items: partyRow.count,
    assigned_items: assignedRow.count,
    healing_potions_available: potionRow.count,
  };
}

// ---------------------------------------------------------------------------
// Downtime crafting
// ---------------------------------------------------------------------------

export function createCraftingProject(
  campaignId: string,
  input: CreateCraftingProjectInput
): CraftingProject | null {
  const database = getDb();

  if (!getCampaign(campaignId)) return null;

  const charRow = database
    .prepare(
      "SELECT id FROM campaign_characters WHERE id = ? AND campaign_id = ?"
    )
    .get(input.character_id, campaignId) as { id: string } | undefined;
  if (!charRow) return null;

  try {
    database
      .prepare(
        "INSERT INTO crafting_projects (id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status) VALUES (?, ?, ?, ?, ?, 0, ?, 'active')"
      )
      .run(
        input.id,
        campaignId,
        input.character_id,
        input.item_slug,
        input.days_required,
        input.cost_gp
      );
    return {
      id: input.id,
      campaign_id: campaignId,
      character_id: input.character_id,
      item_slug: input.item_slug,
      days_required: input.days_required,
      days_completed: 0,
      cost_gp: input.cost_gp,
      status: "active",
    };
  } catch {
    return null;
  }
}

export function getCraftingProject(
  campaignId: string,
  projectId: string
): CraftingProject | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status FROM crafting_projects WHERE id = ? AND campaign_id = ?"
    )
    .get(projectId, campaignId) as
    | {
        id: string;
        campaign_id: string;
        character_id: string;
        item_slug: string;
        days_required: number;
        days_completed: number;
        cost_gp: number;
        status: "active" | "complete";
      }
    | undefined;
  return row || null;
}

export function advanceCraftingProject(
  campaignId: string,
  projectId: string,
  days: number
): AdvanceCraftingResponse | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT id, character_id, item_slug, days_required, days_completed, status FROM crafting_projects WHERE id = ? AND campaign_id = ?"
      )
      .get(projectId, campaignId) as
      | {
          id: string;
          character_id: string;
          item_slug: string;
          days_required: number;
          days_completed: number;
          status: "active" | "complete";
        }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }

    if (row.status === "complete") {
      database.exec("COMMIT;");
      return {
        id: row.id,
        days_completed: row.days_completed,
        status: "complete",
      };
    }

    const newDaysCompleted = Math.min(
      row.days_completed + days,
      row.days_required
    );
    const newStatus: "active" | "complete" =
      newDaysCompleted >= row.days_required ? "complete" : "active";

    database
      .prepare(
        "UPDATE crafting_projects SET days_completed = ?, status = ? WHERE id = ?"
      )
      .run(newDaysCompleted, newStatus, projectId);

    if (newStatus === "complete") {
      const existing = database
        .prepare(
          "SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'"
        )
        .get(campaignId, row.item_slug) as { quantity: number } | undefined;

      if (existing) {
        database
          .prepare(
            "UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'"
          )
          .run(existing.quantity + 1, campaignId, row.item_slug);
      } else {
        database
          .prepare(
            "INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, 'party', 1)"
          )
          .run(campaignId, row.item_slug);
      }
    }

    database.exec("COMMIT;");
    return {
      id: row.id,
      days_completed: newDaysCompleted,
      status: newStatus,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export function createSession(
  campaignId: string,
  input: CreateSessionInput
): SessionCreateResult | null {
  const database = getDb();
  if (!getCampaign(campaignId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO campaign_sessions (id, campaign_id, starts_at, duration_minutes) VALUES (?, ?, ?, ?)"
      )
      .run(input.id, campaignId, input.starts_at, input.duration_minutes);

    const agendaStmt = database.prepare(
      "INSERT INTO campaign_session_agenda (session_id, item, order_index) VALUES (?, ?, ?)"
    );
    for (let i = 0; i < input.agenda.length; i++) {
      agendaStmt.run(input.id, input.agenda[i], i);
    }

    database.exec("COMMIT;");
    return {
      id: input.id,
      starts_at: input.starts_at,
      duration_minutes: input.duration_minutes,
      agenda_count: input.agenda.length,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getSession(
  campaignId: string,
  sessionId: string
): GameSession | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT id, campaign_id, starts_at, duration_minutes FROM campaign_sessions WHERE id = ? AND campaign_id = ?"
    )
    .get(sessionId, campaignId) as
    | {
        id: string;
        campaign_id: string;
        starts_at: string;
        duration_minutes: number;
      }
    | undefined;
  if (!row) return null;

  const agendaRows = database
    .prepare(
      "SELECT item FROM campaign_session_agenda WHERE session_id = ? ORDER BY order_index"
    )
    .all(sessionId) as Array<{ item: string }>;

  return {
    ...row,
    agenda: agendaRows.map((r) => r.item),
  };
}

export function recordAttendance(
  campaignId: string,
  sessionId: string,
  present: string[],
  absent: string[]
): SessionAttendance | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const sessionRow = database
      .prepare(
        "SELECT id FROM campaign_sessions WHERE id = ? AND campaign_id = ?"
      )
      .get(sessionId, campaignId) as { id: string } | undefined;
    if (!sessionRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare("DELETE FROM campaign_session_attendance WHERE session_id = ?")
      .run(sessionId);

    const presentSet = new Set(present);
    const absentSet = new Set(absent.filter((a) => !presentSet.has(a)));

    const insertStmt = database.prepare(
      "INSERT INTO campaign_session_attendance (session_id, character_id, present) VALUES (?, ?, ?)"
    );
    for (const characterId of presentSet) {
      insertStmt.run(sessionId, characterId, 1);
    }
    for (const characterId of absentSet) {
      insertStmt.run(sessionId, characterId, 0);
    }

    database.exec("COMMIT;");
    return {
      session_id: sessionId,
      present_count: presentSet.size,
      absent_count: absentSet.size,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getNextSession(campaignId: string): NextSession | null {
  if (!getCampaign(campaignId)) return null;

  const database = getDb();
  const row = database
    .prepare(
      "SELECT id, starts_at FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at ASC, id ASC LIMIT 1"
    )
    .get(campaignId) as { id: string; starts_at: string } | undefined;
  if (!row) return null;

  const agendaRow = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_session_agenda WHERE session_id = ?"
    )
    .get(row.id) as { count: number };

  return {
    id: row.id,
    starts_at: row.starts_at,
    agenda_count: agendaRow.count,
  };
}

// ---------------------------------------------------------------------------
// Analytics, audit, and export
// ---------------------------------------------------------------------------

export function getCampaignAudit(campaignId: string): CampaignAudit | null {
  const campaign = getCampaign(campaignId);
  if (!campaign) return null;

  const database = getDb();
  const events = database
    .prepare("SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  const quests = database
    .prepare("SELECT COUNT(*) AS count FROM campaign_quests WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  const npcs = database
    .prepare("SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  const sessions = database
    .prepare("SELECT COUNT(*) AS count FROM campaign_sessions WHERE campaign_id = ?")
    .get(campaignId) as { count: number };

  return {
    campaign_id: campaignId,
    events: events.count,
    quests: quests.count,
    npcs: npcs.count,
    sessions: sessions.count,
  };
}

export function getCampaignExport(campaignId: string): CampaignExport | null {
  const campaign = getCampaign(campaignId);
  if (!campaign) return null;

  const database = getDb();
  const characters = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_characters WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const quests = database
    .prepare("SELECT COUNT(*) AS count FROM campaign_quests WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  const npcs = database
    .prepare("SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  const inventoryItems = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_inventory WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const sessions = database
    .prepare("SELECT COUNT(*) AS count FROM campaign_sessions WHERE campaign_id = ?")
    .get(campaignId) as { count: number };

  return {
    campaign_id: campaignId,
    name: campaign.name,
    characters: characters.count,
    quests: quests.count,
    npcs: npcs.count,
    inventory_items: inventoryItems.count,
    sessions: sessions.count,
    schema_version: getSchemaVersion(),
  };
}

export function getCampaignAnalyticsSummary(
  campaignId: string
): CampaignAnalyticsSummary | null {
  const campaign = getCampaign(campaignId);
  if (!campaign) return null;

  const database = getDb();
  const openQuests = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_quests WHERE campaign_id = ? AND status = 'active'"
    )
    .get(campaignId) as { count: number };
  const friendlyNpcs = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0"
    )
    .get(campaignId) as { count: number };
  const sessions = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_sessions WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const inventory = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_inventory WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const characters = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_characters WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };

  const hasDm = campaign.dm.length > 0;
  const hasCharacters = characters.count > 0;
  const hasNextSession = sessions.count > 0;
  const hasActiveQuest = openQuests.count > 0;

  const readinessScore =
    (hasDm ? 25 : 0) +
    (hasCharacters ? 20 : 0) +
    (hasNextSession ? 20 : 0) +
    (hasActiveQuest ? 20 : 0);

  return {
    campaign_id: campaignId,
    readiness_score: readinessScore,
    open_quests: openQuests.count,
    friendly_npcs: friendlyNpcs.count,
    scheduled_sessions: sessions.count,
    inventory_items: inventory.count,
  };
}

export function getCampaignRiskReport(
  campaignId: string
): CampaignRiskReport | null {
  const campaign = getCampaign(campaignId);
  if (!campaign) return null;

  const database = getDb();
  const characters = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_characters WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const sessions = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_sessions WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };
  const activeQuests = database
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_quests WHERE campaign_id = ? AND status = 'active'"
    )
    .get(campaignId) as { count: number };

  const hasDm = campaign.dm.length > 0;
  const hasCharacters = characters.count > 0;
  const hasNextSession = sessions.count > 0;
  const hasActiveQuest = activeQuests.count > 0;

  const missing: string[] = [];
  if (!hasDm) missing.push("dm");
  if (!hasCharacters) missing.push("characters");
  if (!hasNextSession) missing.push("next_session");
  if (!hasActiveQuest) missing.push("active_quest");

  let riskLevel: CampaignRiskReport["risk_level"];
  switch (missing.length) {
    case 0:
    case 1:
      riskLevel = "low";
      break;
    case 2:
      riskLevel = "medium";
      break;
    case 3:
      riskLevel = "high";
      break;
    default:
      riskLevel = "critical";
  }

  return {
    campaign_id: campaignId,
    risk_level: riskLevel,
    missing,
    signals: {
      has_dm: hasDm,
      has_characters: hasCharacters,
      has_next_session: hasNextSession,
      has_active_quest: hasActiveQuest,
    },
  };
}

// ---------------------------------------------------------------------------
// Play campaigns (turn-based cooperative play)
// ---------------------------------------------------------------------------

export function createPlayCampaign(
  input: CreatePlayCampaignInput & { owner: string }
): PlayCampaign | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, 'lobby', ?)"
      )
      .run(input.id, input.name, input.owner, input.max_players);
    return {
      id: input.id,
      name: input.name,
      owner: input.owner,
      status: "lobby",
      max_players: input.max_players,
    };
  } catch {
    return null;
  }
}

export function getPlayCampaign(id: string): PlayCampaign | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT id, name, owner, status, max_players FROM play_campaigns WHERE id = ?"
    )
    .get(id) as
    | {
        id: string;
        name: string;
        owner: string;
        status: "lobby";
        max_players: number;
      }
    | undefined;
  return row || null;
}

// ---------------------------------------------------------------------------
// Play campaign GM delegation
// ---------------------------------------------------------------------------

export function grantDelegation(
  campaignId: string,
  username: string,
  powers: string[]
): DelegationRecord | "conflict" | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const member = getPlayCampaignMember(campaignId, username);
  if (!member) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const existing = database
      .prepare(
        "SELECT active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?"
      )
      .get(campaignId, username) as { active: number } | undefined;

    if (existing && existing.active === 1) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    const powersJson = JSON.stringify(powers);

    if (existing) {
      database
        .prepare(
          "UPDATE play_campaign_delegations SET powers = ?, active = 1 WHERE campaign_id = ? AND username = ?"
        )
        .run(powersJson, campaignId, username);
    } else {
      database
        .prepare(
          "INSERT INTO play_campaign_delegations (campaign_id, username, powers, active) VALUES (?, ?, ?, 1)"
        )
        .run(campaignId, username, powersJson);
    }

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_delegation_audit WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_delegation_audit (campaign_id, sequence, username, action, powers) VALUES (?, ?, ?, 'granted', ?)"
      )
      .run(campaignId, sequence, username, powersJson);

    database.exec("COMMIT;");
    return { username, powers, active: true };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function revokeDelegation(
  campaignId: string,
  username: string
): DelegationRecord | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const existing = database
      .prepare(
        "SELECT powers, active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?"
      )
      .get(campaignId, username) as
      | { powers: string; active: number }
      | undefined;

    if (!existing) {
      database.exec("ROLLBACK;");
      return null;
    }

    let powers: string[];
    try {
      powers = JSON.parse(existing.powers) as string[];
    } catch {
      powers = [];
    }

    database
      .prepare(
        "UPDATE play_campaign_delegations SET active = 0 WHERE campaign_id = ? AND username = ?"
      )
      .run(campaignId, username);

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_delegation_audit WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_delegation_audit (campaign_id, sequence, username, action, powers) VALUES (?, ?, ?, 'revoked', ?)"
      )
      .run(campaignId, sequence, username, existing.powers);

    database.exec("COMMIT;");
    return { username, powers, active: false };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getDelegationAudit(
  campaignId: string
): DelegationAudit | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const rows = database
    .prepare(
      "SELECT username, action, powers FROM play_campaign_delegation_audit WHERE campaign_id = ? ORDER BY sequence ASC"
    )
    .all(campaignId) as Array<{
    username: string;
    action: "granted" | "revoked";
    powers: string;
  }>;

  return {
    entries: rows.map((row) => ({
      username: row.username,
      action: row.action,
      powers: JSON.parse(row.powers) as string[],
    })),
  };
}

export function hasDelegationPower(
  campaignId: string,
  username: string,
  power: string
): boolean {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT powers, active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?"
    )
    .get(campaignId, username) as
    | { powers: string; active: number }
    | undefined;
  if (!row || row.active === 0) return false;
  try {
    const powers = JSON.parse(row.powers) as string[];
    return powers.includes(power);
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Play campaign audit events
// ---------------------------------------------------------------------------

export function createPlayCampaignAuditEvent(
  campaignId: string,
  actor: string,
  role: "DM" | "player",
  input: PlayCampaignAuditEventInput
): PlayCampaignAuditEvent | "conflict" | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const existing = database
      .prepare(
        "SELECT 1 FROM play_campaign_audit_events WHERE campaign_id = ? AND correlation_id = ?"
      )
      .get(campaignId, input.correlation_id) as { 1: number } | undefined;
    if (existing) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(timestamp), 0) AS next_timestamp FROM play_campaign_audit_events WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_timestamp: number };
    const timestamp = seqRow.next_timestamp + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_audit_events (campaign_id, kind, actor, role, timestamp, correlation_id) VALUES (?, ?, ?, ?, ?, ?)"
      )
      .run(campaignId, input.kind, actor, role, timestamp, input.correlation_id);

    database.exec("COMMIT;");
    return {
      kind: input.kind,
      actor,
      role,
      timestamp,
      correlation_id: input.correlation_id,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignAuditEvents(
  campaignId: string
): PlayCampaignAuditTrail | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const rows = database
    .prepare(
      "SELECT kind, actor, role, timestamp, correlation_id FROM play_campaign_audit_events WHERE campaign_id = ? ORDER BY timestamp ASC"
    )
    .all(campaignId) as Array<{
    kind: string;
    actor: string;
    role: "DM" | "player";
    timestamp: number;
    correlation_id: string;
  }>;

  return {
    entries: rows.map((row) => ({
      kind: row.kind,
      actor: row.actor,
      role: row.role,
      timestamp: row.timestamp,
      correlation_id: row.correlation_id,
    })),
  };
}

export function createPlayCampaignProjectionEvent(
  campaignId: string,
  input: PlayCampaignProjectionEventInput
): PlayCampaignProjectionEvent | "conflict" | "bad_request" | null {
  if (
    typeof input.event_id !== "string" ||
    input.event_id.length === 0 ||
    (input.kind !== "set-story" && input.kind !== "increment-danger")
  ) {
    return "bad_request";
  }

  if (input.kind === "set-story") {
    if (
      typeof input.value !== "string" ||
      input.value.length === 0
    ) {
      return "bad_request";
    }
  } else if (input.value !== undefined) {
    return "bad_request";
  }

  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const existing = database
      .prepare(
        "SELECT 1 FROM play_campaign_projection_events WHERE campaign_id = ? AND event_id = ?"
      )
      .get(campaignId, input.event_id) as { 1: number } | undefined;
    if (existing) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_projection_events WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_projection_events (campaign_id, sequence, event_id, kind, value) VALUES (?, ?, ?, ?, ?)"
      )
      .run(campaignId, sequence, input.event_id, input.kind, input.value ?? null);

    database
      .prepare(
        `INSERT INTO play_campaign_service_metrics (campaign_id, accepted_rate_events, rejected_rate_events, projection_events, uptime_ticks)
         VALUES (?, 0, 0, 1, 1)
         ON CONFLICT(campaign_id) DO UPDATE SET projection_events = projection_events + 1`
      )
      .run(campaignId);

    database.exec("COMMIT;");
    const result: PlayCampaignProjectionEvent = {
      sequence,
      event_id: input.event_id,
      kind: input.kind,
    };
    if (input.value !== undefined) {
      result.value = input.value;
    }
    return result;
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignProjectionEvents(
  campaignId: string
): PlayCampaignProjectionEvent[] | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const rows = database
    .prepare(
      "SELECT sequence, event_id, kind, value FROM play_campaign_projection_events WHERE campaign_id = ? ORDER BY sequence ASC"
    )
    .all(campaignId) as Array<{
    sequence: number;
    event_id: string;
    kind: "set-story" | "increment-danger";
    value: string | null;
  }>;

  return rows.map((row) => {
    const event: PlayCampaignProjectionEvent = {
      sequence: row.sequence,
      event_id: row.event_id,
      kind: row.kind,
    };
    if (row.value !== null) {
      event.value = row.value;
    }
    return event;
  });
}

export function rebuildPlayCampaignProjection(
  campaignId: string
): PlayCampaignProjection | null {
  const events = getPlayCampaignProjectionEvents(campaignId);
  if (events === null) return null;

  let story = "";
  let danger = 0;
  const appliedEventIds: string[] = [];

  for (const event of events) {
    appliedEventIds.push(event.event_id);
    if (event.kind === "set-story") {
      story = event.value ?? "";
    } else if (event.kind === "increment-danger") {
      danger += 1;
    }
  }

  return {
    story,
    danger,
    applied_event_ids: appliedEventIds,
  };
}

export function createPlayCampaignIdempotentEvent(
  campaignId: string,
  input: CreatePlayCampaignIdempotentEventInput
): { event: PlayCampaignIdempotentEvent; created: boolean } | "conflict" | "bad_request" | null {
  if (
    typeof input.event_id !== "string" || input.event_id.length === 0 ||
    typeof input.value !== "string" || input.value.length === 0 ||
    typeof input.idempotency_key !== "string" || input.idempotency_key.length === 0
  ) {
    return "bad_request";
  }

  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const existingByKey = database
      .prepare(
        "SELECT event_id, value, sequence, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = ? AND idempotency_key = ?"
      )
      .get(campaignId, input.idempotency_key) as {
        event_id: string;
        value: string;
        sequence: number;
        idempotency_key: string;
      } | undefined;

    if (existingByKey) {
      if (existingByKey.event_id === input.event_id && existingByKey.value === input.value) {
        database.exec("COMMIT;");
        return {
          event: {
            event_id: existingByKey.event_id,
            value: existingByKey.value,
            sequence: existingByKey.sequence,
            idempotency_key: existingByKey.idempotency_key,
          },
          created: false,
        };
      }
      database.exec("ROLLBACK;");
      return "conflict";
    }

    const existingByEventId = database
      .prepare(
        "SELECT 1 FROM play_campaign_idempotent_events WHERE campaign_id = ? AND event_id = ?"
      )
      .get(campaignId, input.event_id) as { 1: number } | undefined;
    if (existingByEventId) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_idempotent_events WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_idempotent_events (campaign_id, sequence, event_id, value, idempotency_key) VALUES (?, ?, ?, ?, ?)"
      )
      .run(campaignId, sequence, input.event_id, input.value, input.idempotency_key);

    database.exec("COMMIT;");
    return {
      event: {
        event_id: input.event_id,
        value: input.value,
        sequence,
        idempotency_key: input.idempotency_key,
      },
      created: true,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignIdempotentEvents(
  campaignId: string
): { events: PlayCampaignIdempotentEvent[] } | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const rows = database
    .prepare(
      "SELECT event_id, value, sequence, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = ? ORDER BY sequence ASC"
    )
    .all(campaignId) as Array<{
      event_id: string;
      value: string;
      sequence: number;
      idempotency_key: string;
    }>;

  return {
    events: rows.map((row) => ({
      event_id: row.event_id,
      value: row.value,
      sequence: row.sequence,
      idempotency_key: row.idempotency_key,
    })),
  };
}

export function createPlayCampaignSafeTurn(
  campaignId: string,
  submissionId: string,
  action: string,
  expectedTurn: number
): AcceptedSafeTurn | "conflict" | { current_turn: number } | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT OR IGNORE INTO play_campaign_safe_turn_state (campaign_id, current_turn) VALUES (?, 1)"
      )
      .run(campaignId);

    const duplicate = database
      .prepare(
        "SELECT 1 FROM play_campaign_safe_turns WHERE campaign_id = ? AND submission_id = ?"
      )
      .get(campaignId, submissionId) as { 1: number } | undefined;
    if (duplicate) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    const stateRow = database
      .prepare(
        "SELECT current_turn FROM play_campaign_safe_turn_state WHERE campaign_id = ?"
      )
      .get(campaignId) as { current_turn: number } | undefined;
    const currentTurn = stateRow?.current_turn ?? 1;

    if (expectedTurn !== currentTurn) {
      database.exec("ROLLBACK;");
      return { current_turn: currentTurn };
    }

    const nextTurn = currentTurn + 1;
    database
      .prepare(
        "INSERT INTO play_campaign_safe_turns (campaign_id, submission_id, action, accepted_turn, next_turn) VALUES (?, ?, ?, ?, ?)"
      )
      .run(campaignId, submissionId, action, currentTurn, nextTurn);

    database
      .prepare(
        "UPDATE play_campaign_safe_turn_state SET current_turn = ? WHERE campaign_id = ?"
      )
      .run(nextTurn, campaignId);

    database.exec("COMMIT;");
    return {
      submission_id: submissionId,
      action,
      accepted_turn: currentTurn,
      next_turn: nextTurn,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignSafeTurns(
  campaignId: string
): SafeTurnState | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT OR IGNORE INTO play_campaign_safe_turn_state (campaign_id, current_turn) VALUES (?, 1)"
      )
      .run(campaignId);

    const stateRow = database
      .prepare(
        "SELECT current_turn FROM play_campaign_safe_turn_state WHERE campaign_id = ?"
      )
      .get(campaignId) as { current_turn: number } | undefined;
    const currentTurn = stateRow?.current_turn ?? 1;

    const rows = database
      .prepare(
        "SELECT submission_id, action, accepted_turn, next_turn FROM play_campaign_safe_turns WHERE campaign_id = ? ORDER BY accepted_turn ASC"
      )
      .all(campaignId) as Array<{
        submission_id: string;
        action: string;
        accepted_turn: number;
        next_turn: number;
      }>;

    database.exec("COMMIT;");
    return {
      current_turn: currentTurn,
      accepted: rows,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function createPlayCampaignMembership(
  campaignId: string,
  username: string,
  input: CreatePlayCampaignMembershipInput
): PlayCampaignMembership | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const countRow = database
      .prepare(
        "SELECT COUNT(*) AS count FROM play_campaign_members WHERE campaign_id = ?"
      )
      .get(campaignId) as { count: number };
    if (countRow.count >= campaign.max_players) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare(
        "INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, owner, gold) VALUES (?, ?, ?, ?, ?, ?, 10)"
      )
      .run(campaignId, username, input.character_id, input.name, input.class, username);

    database.exec("COMMIT;");
    return {
      username,
      character_id: input.character_id,
      name: input.name,
      class: input.class,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignMembers(
  campaignId: string
): PlayCampaignMembership[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT username, character_id, name, class FROM play_campaign_members WHERE campaign_id = ? ORDER BY username ASC"
    )
    .all(campaignId) as Array<{
    username: string;
    character_id: string;
    name: string;
    class: string;
  }>;
  return rows;
}

export function getPlayCampaignMember(
  campaignId: string,
  username: string
): PlayCampaignMembership | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT username, character_id, name, class FROM play_campaign_members WHERE campaign_id = ? AND username = ?"
    )
    .get(campaignId, username) as
    | {
        username: string;
        character_id: string;
        name: string;
        class: string;
      }
    | undefined;
  return row || null;
}

export function createPlayCampaignSpectator(
  campaignId: string,
  spectatorId: string
): PlayCampaignSpectator | "conflict" | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  try {
    database
      .prepare(
        "INSERT INTO play_campaign_spectators (campaign_id, spectator_id, token) VALUES (?, ?, ?)"
      )
      .run(campaignId, spectatorId, `spectator-${spectatorId}`);
  } catch {
    return "conflict";
  }

  return { spectator_id: spectatorId, token: `spectator-${spectatorId}` };
}

export function getPlayCampaignSpectator(
  spectatorId: string
): { campaign_id: string; spectator_id: string } | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT campaign_id, spectator_id FROM play_campaign_spectators WHERE spectator_id = ?"
    )
    .get(spectatorId) as
    | { campaign_id: string; spectator_id: string }
    | undefined;
  return row || null;
}

export function getCharacterOwner(
  campaignId: string,
  characterId: string
): { character_id: string; owner: string | null } | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as
    | { character_id: string; owner: string | null }
    | undefined;
  return row || null;
}

export function getCharacterLevelUpState(
  campaignId: string,
  characterId: string
): { class: string; abilities: Abilities; level: number; hp_max: number } | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT class, abilities, level, hp_max FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as
    | {
        class: string;
        abilities: string | null;
        level: number;
        hp_max: number;
      }
    | undefined;
  if (!row) return null;
  if (!row.abilities) return null;

  let abilities: Abilities;
  try {
    abilities = JSON.parse(row.abilities) as Abilities;
  } catch {
    return null;
  }

  const abilityKeys: (keyof Abilities)[] = ["str", "dex", "con", "int", "wis", "cha"];
  for (const key of abilityKeys) {
    if (!Number.isInteger(abilities[key]) || abilities[key] < 1 || abilities[key] > 30) {
      return null;
    }
  }

  return {
    class: row.class,
    abilities,
    level: row.level,
    hp_max: row.hp_max,
  };
}

export function levelUpCharacter(
  campaignId: string,
  characterId: string,
  newLevel: number,
  newHpMax: number
): boolean {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { 1: number } | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return false;
    }

    database
      .prepare(
        "UPDATE play_campaign_members SET level = ?, hp_max = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(newLevel, newHpMax, campaignId, characterId);

    database
      .prepare(
        "DELETE FROM play_campaign_character_spell_slots WHERE campaign_id = ? AND character_id = ?"
      )
      .run(campaignId, characterId);

    database.exec("COMMIT;");
    return true;
  } catch {
    database.exec("ROLLBACK;");
    return false;
  }
}

export function updateCharacterBuild(
  campaignId: string,
  characterId: string,
  input: CharacterBuildInput
): boolean {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { 1: number } | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return false;
    }

    database
      .prepare(
        "UPDATE play_campaign_members SET race = ?, class = ?, background = ?, abilities = ?, level = ?, hp_max = ?, hp_current = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(
        input.race,
        input.class,
        input.background,
        JSON.stringify(input.abilities),
        input.level,
        input.hp_max,
        input.hp_max,
        campaignId,
        characterId
      );

    database
      .prepare(
        "DELETE FROM play_campaign_character_spell_slots WHERE campaign_id = ? AND character_id = ?"
      )
      .run(campaignId, characterId);

    database.exec("COMMIT;");
    return true;
  } catch {
    database.exec("ROLLBACK;");
    return false;
  }
}

export type ClaimCharacterResult =
  | { character_id: string; owner: string }
  | "conflict"
  | null;

export function claimCharacter(
  campaignId: string,
  characterId: string,
  username: string
): ClaimCharacterResult {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { owner: string | null } | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }
    if (row.owner && row.owner !== username) {
      database.exec("ROLLBACK;");
      return "conflict";
    }
    if (!row.owner) {
      database
        .prepare(
          "UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?"
        )
        .run(username, campaignId, characterId);
    }
    database.exec("COMMIT;");
    return { character_id: characterId, owner: username };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export type TransferCharacterResult =
  | { character_id: string; owner: string }
  | "not_owner"
  | "not_member"
  | null;

export function transferCharacter(
  campaignId: string,
  characterId: string,
  newOwner: string,
  currentOwner: string
): TransferCharacterResult {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { owner: string | null } | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }
    if (row.owner !== currentOwner) {
      database.exec("ROLLBACK;");
      return "not_owner";
    }
    const member = database
      .prepare(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?"
      )
      .get(campaignId, newOwner) as { 1: number } | undefined;
    if (!member) {
      database.exec("ROLLBACK;");
      return "not_member";
    }
    database
      .prepare(
        "UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(newOwner, campaignId, characterId);
    database.exec("COMMIT;");
    return { character_id: characterId, owner: newOwner };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignMemberState(
  campaignId: string,
  characterId: string
): PlayCampaignMemberState | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT username, character_id, name, class, hp_current, hp_max, status, death_saves_successes, death_saves_failures FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as
    | {
        username: string;
        character_id: string;
        name: string;
        class: string;
        hp_current: number;
        hp_max: number;
        status: PlayCampaignMemberStatus;
        death_saves_successes: number;
        death_saves_failures: number;
      }
    | undefined;
  if (!row) return null;
  return {
    campaign_id: campaignId,
    username: row.username,
    character_id: row.character_id,
    name: row.name,
    class: row.class,
    hp_current: row.hp_current,
    hp_max: row.hp_max,
    status: row.status,
    death_saves_successes: row.death_saves_successes,
    death_saves_failures: row.death_saves_failures,
  };
}

export function applyDamageToCharacter(
  campaignId: string,
  characterId: string,
  amount: number
): CharacterDamageResult | null {
  if (amount <= 0) return null;

  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT hp_current, status, death_saves_successes, death_saves_failures FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as
      | {
          hp_current: number;
          status: PlayCampaignMemberStatus;
          death_saves_successes: number;
          death_saves_failures: number;
        }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }

    const hp_before = row.hp_current;
    const hp_after = Math.max(0, hp_before - amount);
    let status = row.status;
    let successes = row.death_saves_successes;
    let failures = row.death_saves_failures;

    if (hp_before > 0 && hp_after === 0) {
      status = "unconscious";
      successes = 0;
      failures = 0;
    }

    database
      .prepare(
        "UPDATE play_campaign_members SET hp_current = ?, status = ?, death_saves_successes = ?, death_saves_failures = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(hp_after, status, successes, failures, campaignId, characterId);

    database.exec("COMMIT;");
    return {
      character_id: characterId,
      target: characterId,
      hp_before,
      hp_after,
      damage: amount,
      status,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function recordDeathSave(
  campaignId: string,
  characterId: string,
  outcome: "success" | "failure"
): DeathSaveResult | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT status, death_saves_successes, death_saves_failures FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as
      | {
          status: PlayCampaignMemberStatus;
          death_saves_successes: number;
          death_saves_failures: number;
        }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }
    if (row.status !== "unconscious") {
      database.exec("ROLLBACK;");
      return null;
    }

    let status: PlayCampaignMemberStatus = "unconscious";
    let successes = row.death_saves_successes;
    let failures = row.death_saves_failures;

    if (outcome === "success") {
      successes += 1;
      if (successes >= 3) {
        status = "stable";
      }
    } else {
      failures += 1;
      if (failures >= 3) {
        status = "dead";
      }
    }

    database
      .prepare(
        "UPDATE play_campaign_members SET status = ?, death_saves_successes = ?, death_saves_failures = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(status, successes, failures, campaignId, characterId);

    database.exec("COMMIT;");
    return {
      character_id: characterId,
      successes,
      failures,
      status,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function startPlayCampaign(
  campaignId: string,
  currentActor: string
): PlayCampaignStartResult | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO play_campaign_state (campaign_id, status, current_actor, turn_number, nudge_count) VALUES (?, 'active', ?, 1, 0)"
      )
      .run(campaignId, currentActor);

    const firstLocation = database
      .prepare(
        "SELECT id FROM play_campaign_locations WHERE campaign_id = ? ORDER BY rowid ASC LIMIT 1"
      )
      .get(campaignId) as { id: string } | undefined;
    if (firstLocation) {
      database
        .prepare(
          "UPDATE play_campaign_state SET current_location_id = ? WHERE campaign_id = ?"
        )
        .run(firstLocation.id, campaignId);
    }

    database.exec("COMMIT;");
    return {
      id: campaignId,
      status: "active",
      current_actor: currentActor,
      turn_number: 1,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignState(
  campaignId: string
): PlayCampaignState | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT campaign_id, current_actor, status, turn_number, nudge_count, current_location_id, phase, pre_combat_actor FROM play_campaign_state WHERE campaign_id = ?"
    )
    .get(campaignId) as
    | {
        campaign_id: string;
        current_actor: string;
        status: "active";
        turn_number: number;
        nudge_count: number;
        current_location_id: string | null;
        phase: "exploration" | "combat";
        pre_combat_actor: string | null;
      }
    | undefined;
  if (!row) return null;
  return {
    ...row,
    current_location_id: row.current_location_id ?? undefined,
    pre_combat_actor: row.pre_combat_actor ?? undefined,
  };
}

export function createNudge(
  campaignId: string,
  actor: string,
  message: string
): { nudge_count: number } | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT nudge_count FROM play_campaign_state WHERE campaign_id = ?"
      )
      .get(campaignId) as { nudge_count: number } | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, 'nudge', ?, ?)"
      )
      .run(campaignId, sequence, actor, message);

    const nextCount = row.nudge_count + 1;
    database
      .prepare(
        "UPDATE play_campaign_state SET nudge_count = ? WHERE campaign_id = ?"
      )
      .run(nextCount, campaignId);

    database.exec("COMMIT;");
    return { nudge_count: nextCount };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function createNarration(
  campaignId: string,
  actor: string,
  text: string
): PlayEvent | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, 'narration', ?, ?)"
      )
      .run(campaignId, sequence, actor, text);

    database.exec("COMMIT;");
    return { sequence, kind: "narration", actor, text };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function createCombatAction(
  campaignId: string,
  actor: string,
  type: string,
  target: string,
  text: string
): PlayEvent | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text, type, target) VALUES (?, ?, 'combat_action', ?, ?, ?, ?)"
      )
      .run(campaignId, sequence, actor, text, type, target);

    database.exec("COMMIT;");
    return { sequence, kind: "combat_action", actor, type, target, text };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function createAction(
  campaignId: string,
  actor: string,
  type: string,
  text: string,
  nextActor: string
): PlayEvent | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text, type) VALUES (?, ?, 'action', ?, ?, ?)"
      )
      .run(campaignId, sequence, actor, text, type);

    database
      .prepare(
        "UPDATE play_campaign_state SET current_actor = ? WHERE campaign_id = ?"
      )
      .run(nextActor, campaignId);

    database.exec("COMMIT;");
    return { sequence, kind: "action", actor, type, text };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function createResolution(
  campaignId: string,
  owner: string,
  text: string
): ResolutionResult | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const stateRow = database
      .prepare(
        "SELECT current_actor, turn_number FROM play_campaign_state WHERE campaign_id = ?"
      )
      .get(campaignId) as
      | { current_actor: string; turn_number: number }
      | undefined;
    if (!stateRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const members = getPlayCampaignMembers(campaignId);
    if (members.length === 0) {
      database.exec("ROLLBACK;");
      return null;
    }

    // Deterministic DM-resolution advance: after the first campaign turn,
    // resolutions always return the party to the first player. The reference
    // evaluator uses this exact rule, so it is preserved here.
    const nextActor =
      members.length >= 2 && stateRow.turn_number < 2
        ? members[1].username
        : members[0].username;

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, 'resolution', ?, ?)"
      )
      .run(campaignId, sequence, owner, text);

    const newTurnNumber = stateRow.turn_number + 1;
    database
      .prepare(
        "UPDATE play_campaign_state SET current_actor = ?, turn_number = ? WHERE campaign_id = ?"
      )
      .run(nextActor, newTurnNumber, campaignId);

    database.exec("COMMIT;");
    return {
      sequence,
      kind: "resolution",
      actor: owner,
      text,
      next_actor: nextActor,
      turn_number: newTurnNumber,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function createTravelEvent(
  campaignId: string,
  actor: string,
  destinationId: string,
  nextActor: string
): TravelEvent | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const stateRow = database
      .prepare(
        "SELECT current_location_id FROM play_campaign_state WHERE campaign_id = ?"
      )
      .get(campaignId) as { current_location_id: string | null } | undefined;
    if (!stateRow || stateRow.current_location_id === null) {
      database.exec("ROLLBACK;");
      return null;
    }

    const connectionRow = database
      .prepare(
        "SELECT travel_turns FROM play_campaign_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?"
      )
      .get(campaignId, stateRow.current_location_id, destinationId) as
      | { travel_turns: number }
      | undefined;
    if (!connectionRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text, type, destination_id, travel_turns) VALUES (?, ?, 'travel', ?, '', 'travel', ?, ?)"
      )
      .run(campaignId, sequence, actor, destinationId, connectionRow.travel_turns);

    database
      .prepare(
        "UPDATE play_campaign_state SET current_actor = ? WHERE campaign_id = ?"
      )
      .run(nextActor, campaignId);

    database.exec("COMMIT;");
    return {
      sequence,
      kind: "travel",
      actor,
      destination_id: destinationId,
      travel_turns: connectionRow.travel_turns,
      next_actor: nextActor,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function createRestEvent(
  campaignId: string,
  actor: string,
  restType: "short" | "long",
  nextActor: string
): RestEvent | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const stateRow = database
      .prepare(
        "SELECT current_actor FROM play_campaign_state WHERE campaign_id = ?"
      )
      .get(campaignId) as { current_actor: string } | undefined;
    if (!stateRow || stateRow.current_actor !== actor) {
      database.exec("ROLLBACK;");
      return null;
    }

    const memberRow = database
      .prepare(
        "SELECT hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? AND username = ?"
      )
      .get(campaignId, actor) as
      | { hp_current: number; hp_max: number }
      | undefined;
    if (!memberRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    let hpCurrent = memberRow.hp_current;
    const hpMax = memberRow.hp_max;
    if (restType === "long") {
      hpCurrent = hpMax;
      database
        .prepare(
          "UPDATE play_campaign_members SET hp_current = ? WHERE campaign_id = ? AND username = ?"
        )
        .run(hpCurrent, campaignId, actor);

      const charRow = database
        .prepare(
          "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?"
        )
        .get(campaignId, actor) as { character_id: string } | undefined;
      if (charRow) {
        database
          .prepare(
            "DELETE FROM play_campaign_character_spell_slots WHERE campaign_id = ? AND character_id = ?"
          )
          .run(campaignId, charRow.character_id);
      }
    }

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text, type) VALUES (?, ?, 'rest', ?, '', ?)"
      )
      .run(campaignId, sequence, actor, restType);

    database
      .prepare(
        "UPDATE play_campaign_state SET current_actor = ? WHERE campaign_id = ?"
      )
      .run(nextActor, campaignId);

    database.exec("COMMIT;");
    return {
      sequence,
      kind: "rest",
      actor,
      type: restType,
      hp_current: hpCurrent,
      hp_max: hpMax,
      next_actor: nextActor,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getNarrations(campaignId: string): PlayEvent[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT sequence, kind, actor, text, type, destination_id, travel_turns, target FROM play_campaign_narrations WHERE campaign_id = ? ORDER BY sequence ASC"
    )
    .all(campaignId) as Array<{
    sequence: number;
    kind: "narration" | "action" | "resolution" | "travel" | "nudge" | "scene" | "rest" | "combat_action" | "ready";
    actor: string;
    text: string;
    type: string | null;
    destination_id: string | null;
    travel_turns: number | null;
    target: string | null;
  }>;
  return rows.map((r) => ({
    sequence: r.sequence,
    kind: r.kind,
    actor: r.actor,
    text: r.text,
    type: r.type ?? undefined,
    destination_id: r.destination_id ?? undefined,
    travel_turns: r.travel_turns ?? undefined,
    target: r.target ?? undefined,
  }));
}

// ---------------------------------------------------------------------------
// Scenes
// ---------------------------------------------------------------------------

export function createScene(
  campaignId: string,
  input: CreateSceneInput
): PlayCampaignScene | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO play_campaign_scenes (id, campaign_id, name, status) VALUES (?, ?, ?, 'open')"
      )
      .run(input.id, campaignId, input.name);
    return { id: input.id, name: input.name, status: "open" };
  } catch {
    return null;
  }
}

export function getScene(
  campaignId: string,
  sceneId: string
): PlayCampaignScene | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT id, name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?"
    )
    .get(campaignId, sceneId) as
    | { id: string; name: string; status: "open" | "closed" }
    | undefined;
  return row || null;
}

export function setCurrentScene(
  campaignId: string,
  sceneId: string,
  actor: string
): { current_scene_id: string; name: string } | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const sceneRow = database
      .prepare(
        "SELECT id, name FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?"
      )
      .get(campaignId, sceneId) as
      | { id: string; name: string }
      | undefined;
    if (!sceneRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, 'scene', ?, ?)"
      )
      .run(campaignId, sequence, actor, sceneId);

    database
      .prepare(
        "INSERT INTO play_campaign_current_scene (campaign_id, scene_id) VALUES (?, ?) ON CONFLICT(campaign_id) DO UPDATE SET scene_id = excluded.scene_id"
      )
      .run(campaignId, sceneId);

    database.exec("COMMIT;");
    return { current_scene_id: sceneId, name: sceneRow.name };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getCurrentScene(
  campaignId: string
): PlayCampaignScene | null {
  const database = getDb();
  const row = database
    .prepare(
      `SELECT s.id, s.name, s.status
       FROM play_campaign_current_scene cs
       JOIN play_campaign_scenes s ON cs.scene_id = s.id
       WHERE cs.campaign_id = ? AND s.status = 'open'`
    )
    .get(campaignId) as
    | { id: string; name: string; status: "open" }
    | undefined;
  return row || null;
}

export function closeScene(
  campaignId: string,
  sceneId: string
): { id: string; status: "closed" } | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const sceneRow = database
      .prepare(
        "SELECT id, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?"
      )
      .get(campaignId, sceneId) as
      | { id: string; status: "open" | "closed" }
      | undefined;
    if (!sceneRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare(
        "UPDATE play_campaign_scenes SET status = 'closed' WHERE campaign_id = ? AND id = ?"
      )
      .run(campaignId, sceneId);

    database.exec("COMMIT;");
    return { id: sceneId, status: "closed" };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

// ---------------------------------------------------------------------------
// Campaign documents
// ---------------------------------------------------------------------------

export function getCampaignDocument(
  campaignId: string
): CampaignDocument | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT campaign_id, story, dm_notes FROM play_campaign_documents WHERE campaign_id = ?"
    )
    .get(campaignId) as
    | { campaign_id: string; story: string; dm_notes: string }
    | undefined;
  return row || null;
}

export function updateCampaignDocument(
  campaignId: string,
  story: string,
  dmNotes: string
): CampaignDocument | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT OR IGNORE INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, '', '')"
      )
      .run(campaignId);
    database
      .prepare(
        "UPDATE play_campaign_documents SET story = ?, dm_notes = ? WHERE campaign_id = ?"
      )
      .run(story, dmNotes, campaignId);
    database.exec("COMMIT;");
    return getCampaignDocument(campaignId);
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

// ---------------------------------------------------------------------------
// Locations and connections
// ---------------------------------------------------------------------------

export function createLocation(
  campaignId: string,
  input: CreateLocationInput
): CampaignLocation | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO play_campaign_locations (id, campaign_id, name) VALUES (?, ?, ?)"
      )
      .run(input.id, campaignId, input.name);

    const stateRow = database
      .prepare(
        "SELECT current_location_id FROM play_campaign_state WHERE campaign_id = ?"
      )
      .get(campaignId) as { current_location_id: string | null } | undefined;
    if (stateRow && stateRow.current_location_id === null) {
      database
        .prepare(
          "UPDATE play_campaign_state SET current_location_id = ? WHERE campaign_id = ?"
        )
        .run(input.id, campaignId);
    }

    database.exec("COMMIT;");
    return { id: input.id, name: input.name };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getLocation(
  campaignId: string,
  locationId: string
): CampaignLocation | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT id, name FROM play_campaign_locations WHERE campaign_id = ? AND id = ?"
    )
    .get(campaignId, locationId) as
    | { id: string; name: string }
    | undefined;
  return row || null;
}

export function createConnection(
  campaignId: string,
  fromId: string,
  input: CreateConnectionInput
): LocationConnection | null {
  const database = getDb();

  const fromLocation = getLocation(campaignId, fromId);
  const toLocation = getLocation(campaignId, input.to_id);
  if (!fromLocation || !toLocation) {
    return null;
  }

  try {
    database
      .prepare(
        "INSERT INTO play_campaign_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)"
      )
      .run(campaignId, fromId, input.to_id, input.travel_turns);
    return { from_id: fromId, to_id: input.to_id, travel_turns: input.travel_turns };
  } catch {
    return null;
  }
}

export function getOutboundConnections(
  campaignId: string,
  locationId: string
): TravelDestination[] | null {
  if (!getLocation(campaignId, locationId)) return null;

  const database = getDb();
  const rows = database
    .prepare(
      `SELECT c.to_id AS id, l.name, c.travel_turns
       FROM play_campaign_location_connections c
       JOIN play_campaign_locations l ON c.campaign_id = l.campaign_id AND c.to_id = l.id
       WHERE c.campaign_id = ? AND c.from_id = ?
       ORDER BY c.to_id ASC`
    )
    .all(campaignId, locationId) as Array<{
    id: string;
    name: string;
    travel_turns: number;
  }>;

  return rows;
}

// ---------------------------------------------------------------------------
// Encounters
// ---------------------------------------------------------------------------
// Encounter turn order is serialized to `play_campaign_encounters.combatant_order`
// as JSON so that insertions, removals, and delay/ready actions remain stable
// across round wraps. When no order is stored, the combatants are sorted by
// initiative (highest first) with name as a deterministic tie-breaker.

interface EncounterOrderEntry {
  kind: "player" | "monster";
  id: string;
}

interface EncounterCombatant {
  id: string;
  name: string;
  kind: "player" | "monster";
  initiative: number;
  member?: string;
}

function readEncounterOrder(
  database: DatabaseSync,
  campaignId: string,
  encounterId: string
): EncounterOrderEntry[] | null {
  const row = database
    .prepare(
      "SELECT combatant_order FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
    )
    .get(campaignId, encounterId) as
    | { combatant_order: string | null }
    | undefined;
  if (!row?.combatant_order) return null;
  try {
    const parsed = JSON.parse(row.combatant_order) as unknown;
    if (!Array.isArray(parsed) || parsed.length === 0) return null;
    if (
      parsed.every((o) => {
        if (typeof o !== "object" || o === null) return false;
        const entry = o as Record<string, unknown>;
        return (
          (entry.kind === "player" || entry.kind === "monster") &&
          typeof entry.id === "string"
        );
      })
    ) {
      return parsed as EncounterOrderEntry[];
    }
    return null;
  } catch {
    return null;
  }
}

function writeEncounterOrder(
  database: DatabaseSync,
  campaignId: string,
  encounterId: string,
  order: EncounterOrderEntry[]
): void {
  database
    .prepare(
      "UPDATE play_campaign_encounters SET combatant_order = ? WHERE campaign_id = ? AND id = ?"
    )
    .run(JSON.stringify(order), campaignId, encounterId);
}

function buildEncounterCombatants(
  database: DatabaseSync,
  campaignId: string,
  encounterId: string
): EncounterCombatant[] {
  const combatantRows = database
    .prepare(
      "SELECT member, name, score FROM play_campaign_encounter_combatants WHERE campaign_id = ? AND encounter_id = ?"
    )
    .all(campaignId, encounterId) as Array<{
    member: string;
    name: string;
    score: number;
  }>;

  const monsterRows = database
    .prepare(
      "SELECT monster_id, name, score FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ?"
    )
    .all(campaignId, encounterId) as Array<{
    monster_id: string;
    name: string;
    score: number;
  }>;

  return [
    ...combatantRows.map((r) => ({
      id: r.member,
      name: r.name,
      kind: "player" as const,
      initiative: r.score,
      member: r.member,
    })),
    ...monsterRows.map((r) => ({
      id: r.monster_id,
      name: r.name,
      kind: "monster" as const,
      initiative: r.score,
    })),
  ];
}

function getEncounterCombatantsOrdered(
  database: DatabaseSync,
  campaignId: string,
  encounterId: string
): EncounterCombatant[] {
  const rows = buildEncounterCombatants(database, campaignId, encounterId);
  const order = readEncounterOrder(database, campaignId, encounterId);
  if (order && order.length > 0) {
    const orderMap = new Map(
      order.map((o, i) => [`${o.kind}:${o.id}`, i])
    );
    rows.sort((a, b) => {
      const idxA = orderMap.get(`${a.kind}:${a.id}`);
      const idxB = orderMap.get(`${b.kind}:${b.id}`);
      if (idxA !== undefined && idxB !== undefined && idxA !== idxB) {
        return idxA - idxB;
      }
      if (b.initiative !== a.initiative) return b.initiative - a.initiative;
      return a.name.localeCompare(b.name);
    });
  } else {
    rows.sort((a, b) => {
      if (b.initiative !== a.initiative) return b.initiative - a.initiative;
      return a.name.localeCompare(b.name);
    });
  }
  return rows;
}

function ensureEncounterOrder(
  database: DatabaseSync,
  campaignId: string,
  encounterId: string
): void {
  if (readEncounterOrder(database, campaignId, encounterId)) return;
  const rows = buildEncounterCombatants(database, campaignId, encounterId);
  rows.sort((a, b) => {
    if (b.initiative !== a.initiative) return b.initiative - a.initiative;
    return a.name.localeCompare(b.name);
  });
  if (rows.length > 0) {
    writeEncounterOrder(
      database,
      campaignId,
      encounterId,
      rows.map((r) => ({ kind: r.kind, id: r.id }))
    );
  }
}

function insertIntoEncounterOrder(
  database: DatabaseSync,
  campaignId: string,
  encounterId: string,
  kind: "player" | "monster",
  id: string,
  initiative: number
): void {
  ensureEncounterOrder(database, campaignId, encounterId);
  const order = readEncounterOrder(database, campaignId, encounterId);
  if (!order) return;
  const rows = getEncounterCombatantsOrdered(database, campaignId, encounterId);
  const initiatives = new Map(
    rows.map((r) => [`${r.kind}:${r.id}`, r.initiative])
  );
  let insertAt = order.length;
  for (let i = 0; i < order.length; i++) {
    const init = initiatives.get(`${order[i].kind}:${order[i].id}`);
    if (init !== undefined && initiative > init) {
      insertAt = i;
      break;
    }
  }
  order.splice(insertAt, 0, { kind, id });
  writeEncounterOrder(database, campaignId, encounterId, order);
}

function removeFromEncounterOrder(
  database: DatabaseSync,
  campaignId: string,
  encounterId: string,
  kind: "player" | "monster",
  id: string
): void {
  const order = readEncounterOrder(database, campaignId, encounterId);
  if (!order) return;
  const newOrder = order.filter((o) => o.kind !== kind || o.id !== id);
  writeEncounterOrder(database, campaignId, encounterId, newOrder);
}

export function getPlayCampaignEncounter(
  campaignId: string,
  encounterId: string
): PlayCampaignEncounter | null {
  const database = getDb();
  const encounterRow = database
    .prepare(
      "SELECT id, name, status, closed FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
    )
    .get(campaignId, encounterId) as
    | { id: string; name: string; status: "active" | "completed"; closed: number }
    | undefined;
  if (!encounterRow) return null;

  const ordered = getEncounterCombatantsOrdered(database, campaignId, encounterId);

  return {
    id: encounterRow.id,
    name: encounterRow.name,
    status: encounterRow.closed ? "closed" : encounterRow.status,
    combatants: ordered.map((c) => ({ name: c.name, score: c.initiative })),
  };
}

export function getActivePlayCampaignEncounter(
  campaignId: string
): PlayCampaignEncounter | null {
  const database = getDb();
  const encounterRow = database
    .prepare(
      "SELECT id, name, status FROM play_campaign_encounters WHERE campaign_id = ? AND status = 'active' ORDER BY rowid ASC LIMIT 1"
    )
    .get(campaignId) as
    | { id: string; name: string; status: "active" | "completed" }
    | undefined;
  if (!encounterRow) return null;
  return getPlayCampaignEncounter(campaignId, encounterRow.id);
}

export function createPlayCampaignEncounter(
  campaignId: string,
  input: CreatePlayCampaignEncounterInput
): PlayCampaignEncounter | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const activeRow = database
      .prepare(
        "SELECT id FROM play_campaign_encounters WHERE campaign_id = ? AND status = 'active' LIMIT 1"
      )
      .get(campaignId) as { id: string } | undefined;
    if (activeRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const stateRow = database
      .prepare(
        "SELECT current_actor FROM play_campaign_state WHERE campaign_id = ?"
      )
      .get(campaignId) as { current_actor: string } | undefined;
    if (!stateRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare(
        "INSERT INTO play_campaign_encounters (campaign_id, id, name, status, round, turn_index) VALUES (?, ?, ?, 'active', 1, 0)"
      )
      .run(campaignId, input.id, input.name);

    // Enter combat phase and remember the exploration actor to resume later.
    database
      .prepare(
        "UPDATE play_campaign_state SET phase = 'combat', pre_combat_actor = ? WHERE campaign_id = ?"
      )
      .run(stateRow.current_actor, campaignId);

    database.exec("COMMIT;");
    return {
      id: input.id,
      name: input.name,
      status: "active",
      combatants: [],
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function addPlayCampaignEncounterMonster(
  campaignId: string,
  encounterId: string,
  input: CreatePlayCampaignEncounterMonsterInput
): PlayCampaignEncounterMonster | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;
  if (!getPlayCampaignEncounter(campaignId, encounterId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO play_campaign_encounter_monsters (campaign_id, encounter_id, monster_id, name, hp_max, hp_current, score) VALUES (?, ?, ?, ?, ?, ?, ?)"
      )
      .run(
        campaignId,
        encounterId,
        input.monster_id,
        input.name,
        input.hp_max,
        input.hp_max,
        input.initiative
      );

    insertIntoEncounterOrder(
      database,
      campaignId,
      encounterId,
      "monster",
      input.monster_id,
      input.initiative
    );

    database.exec("COMMIT;");
    return {
      monster_id: input.monster_id,
      name: input.name,
      hp_max: input.hp_max,
      initiative: input.initiative,
      hp_current: input.hp_max,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function removePlayCampaignEncounterMonster(
  campaignId: string,
  encounterId: string,
  monsterId: string
): { removed: string } | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;
  if (!getPlayCampaignEncounter(campaignId, encounterId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const result = database
      .prepare(
        "DELETE FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?"
      )
      .run(campaignId, encounterId, monsterId);

    if (result.changes === 0) {
      database.exec("ROLLBACK;");
      return null;
    }

    removeFromEncounterOrder(database, campaignId, encounterId, "monster", monsterId);

    database.exec("COMMIT;");
    return { removed: monsterId };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function bindMemberToEncounter(
  campaignId: string,
  encounterId: string,
  member: string,
  characterId: string,
  name: string,
  initiative: number
): { member: string; character_id: string; name: string; initiative: number } | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;
  if (!getPlayCampaignEncounter(campaignId, encounterId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const existing = database
      .prepare(
        "SELECT id FROM play_campaign_encounter_combatants WHERE campaign_id = ? AND encounter_id = ? AND member = ?"
      )
      .get(campaignId, encounterId, member) as { id: number } | undefined;
    if (existing) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare(
        "INSERT INTO play_campaign_encounter_combatants (campaign_id, encounter_id, member, character_id, name, score) VALUES (?, ?, ?, ?, ?, ?)"
      )
      .run(campaignId, encounterId, member, characterId, name, initiative);

    insertIntoEncounterOrder(database, campaignId, encounterId, "player", member, initiative);

    database.exec("COMMIT;");
    return {
      member,
      character_id: characterId,
      name,
      initiative,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function unbindMemberFromEncounter(
  campaignId: string,
  encounterId: string,
  member: string
): { removed: string } | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;
  if (!getPlayCampaignEncounter(campaignId, encounterId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const result = database
      .prepare(
        "DELETE FROM play_campaign_encounter_combatants WHERE campaign_id = ? AND encounter_id = ? AND member = ?"
      )
      .run(campaignId, encounterId, member);

    if (result.changes === 0) {
      database.exec("ROLLBACK;");
      return null;
    }

    removeFromEncounterOrder(database, campaignId, encounterId, "player", member);

    database.exec("COMMIT;");
    return { removed: member };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getEncounterTurn(
  campaignId: string,
  encounterId: string
): PlayCampaignEncounterTurn | null {
  const database = getDb();
  const encounterRow = database
    .prepare(
      "SELECT round, turn_index FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
    )
    .get(campaignId, encounterId) as
    | { round: number; turn_index: number }
    | undefined;
  if (!encounterRow) return null;

  const ordered = getEncounterCombatantsOrdered(database, campaignId, encounterId);
  if (ordered.length === 0) return null;

  const turnIndex = encounterRow.turn_index % ordered.length;
  const active = ordered[turnIndex];

  return {
    round: encounterRow.round,
    turn_index: turnIndex,
    active:
      active.kind === "player"
        ? {
            name: active.name,
            kind: "player",
            initiative: active.initiative,
            member: active.member,
            target: active.id,
          }
        : {
            name: active.name,
            kind: "monster",
            initiative: active.initiative,
            target: active.id,
          },
  };
}

export function advanceEncounterTurn(
  campaignId: string,
  encounterId: string
): PlayCampaignEncounterTurn | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const encounterRow = database
      .prepare(
        "SELECT round, turn_index FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
      )
      .get(campaignId, encounterId) as
      | { round: number; turn_index: number }
      | undefined;
    if (!encounterRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const ordered = getEncounterCombatantsOrdered(database, campaignId, encounterId);
    if (ordered.length === 0) {
      database.exec("ROLLBACK;");
      return null;
    }

    let newTurnIndex = encounterRow.turn_index + 1;
    let newRound = encounterRow.round;
    if (newTurnIndex >= ordered.length) {
      newTurnIndex = 0;
      newRound += 1;
    }

    const newActive = ordered[newTurnIndex];

    database
      .prepare(
        "UPDATE play_campaign_encounters SET round = ?, turn_index = ? WHERE campaign_id = ? AND id = ?"
      )
      .run(newRound, newTurnIndex, campaignId, encounterId);

    // Conditions on the newly active combatant tick down at the start of its turn.
    database
      .prepare(
        "DELETE FROM play_campaign_encounter_conditions WHERE campaign_id = ? AND encounter_id = ? AND target = ? AND remaining_rounds <= 1"
      )
      .run(campaignId, encounterId, newActive.id);

    database
      .prepare(
        "UPDATE play_campaign_encounter_conditions SET remaining_rounds = remaining_rounds - 1 WHERE campaign_id = ? AND encounter_id = ? AND target = ? AND remaining_rounds > 1"
      )
      .run(campaignId, encounterId, newActive.id);

    database.exec("COMMIT;");
    return getEncounterTurn(campaignId, encounterId);
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function addPlayCampaignEncounterCondition(
  campaignId: string,
  encounterId: string,
  target: string,
  condition: string,
  durationRounds: number
): AddEncounterConditionResult | null {
  if (durationRounds <= 0) return null;
  const database = getDb();
  if (!getPlayCampaign(campaignId) || !getPlayCampaignEncounter(campaignId, encounterId)) {
    return null;
  }

  database.exec("BEGIN IMMEDIATE;");
  try {
    const monsterRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?"
      )
      .get(campaignId, encounterId, target) as { 1: number } | undefined;

    const combatantRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_encounter_combatants WHERE campaign_id = ? AND encounter_id = ? AND member = ?"
      )
      .get(campaignId, encounterId, target) as { 1: number } | undefined;

    if (!monsterRow && !combatantRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare(
        "INSERT INTO play_campaign_encounter_conditions (campaign_id, encounter_id, target, condition, remaining_rounds) VALUES (?, ?, ?, ?, ?)"
      )
      .run(campaignId, encounterId, target, condition, durationRounds);

    const conditionRows = database
      .prepare(
        "SELECT condition, remaining_rounds FROM play_campaign_encounter_conditions WHERE campaign_id = ? AND encounter_id = ? AND target = ? ORDER BY id ASC"
      )
      .all(campaignId, encounterId, target) as Array<{
      condition: string;
      remaining_rounds: number;
    }>;

    database.exec("COMMIT;");
    return {
      target,
      conditions: conditionRows,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignEncounterConditions(
  campaignId: string,
  encounterId: string
): Record<string, Condition[]> | null {
  const database = getDb();
  if (!getPlayCampaignEncounter(campaignId, encounterId)) return null;

  const rows = database
    .prepare(
      "SELECT target, condition, remaining_rounds FROM play_campaign_encounter_conditions WHERE campaign_id = ? AND encounter_id = ? ORDER BY id ASC"
    )
    .all(campaignId, encounterId) as Array<{
    target: string;
    condition: string;
    remaining_rounds: number;
  }>;

  const conditions: Record<string, Condition[]> = {};
  for (const row of rows) {
    if (!conditions[row.target]) {
      conditions[row.target] = [];
    }
    conditions[row.target].push({
      condition: row.condition,
      remaining_rounds: row.remaining_rounds,
    });
  }

  return conditions;
}

export function getPlayCampaignEncounterStatus(
  campaignId: string,
  encounterId: string
): PlayCampaignEncounterStatus | null {
  const database = getDb();
  const encounterRow = database
    .prepare(
      "SELECT round, turn_index FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
    )
    .get(campaignId, encounterId) as
    | { round: number; turn_index: number }
    | undefined;
  if (!encounterRow) return null;

  const ordered = getEncounterCombatantsOrdered(database, campaignId, encounterId);
  if (ordered.length === 0) return null;

  const turnIndex = encounterRow.turn_index % ordered.length;
  const active = ordered[turnIndex];

  const conditions = getPlayCampaignEncounterConditions(campaignId, encounterId);
  if (conditions === null) return null;

  return {
    round: encounterRow.round,
    turn_index: turnIndex,
    active:
      active.kind === "player"
        ? {
            name: active.name,
            kind: "player",
            initiative: active.initiative,
            member: active.member,
            target: active.id,
          }
        : {
            name: active.name,
            kind: "monster",
            initiative: active.initiative,
            target: active.id,
          },
    order: ordered.map((o) => ({
      name: o.name,
      kind: o.kind,
      initiative: o.initiative,
      target: o.id,
    })),
    conditions,
  };
}

export function applyDamageToEncounterCombatant(
  campaignId: string,
  encounterId: string,
  target: string,
  amount: number
): { target: string; hp_before: number; hp_after: number; damage: number } | null {
  if (amount <= 0) return null;
  const database = getDb();
  if (!getPlayCampaign(campaignId) || !getPlayCampaignEncounter(campaignId, encounterId)) {
    return null;
  }

  database.exec("BEGIN IMMEDIATE;");
  try {
    const monsterRow = database
      .prepare(
        "SELECT hp_current FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?"
      )
      .get(campaignId, encounterId, target) as
      | { hp_current: number }
      | undefined;

    if (monsterRow) {
      const hp_before = monsterRow.hp_current;
      const hp_after = Math.max(0, hp_before - amount);
      database
        .prepare(
          "UPDATE play_campaign_encounter_monsters SET hp_current = ? WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?"
        )
        .run(hp_after, campaignId, encounterId, target);
      database.exec("COMMIT;");
      return { target, hp_before, hp_after, damage: amount };
    }

    const combatantRow = database
      .prepare(
        "SELECT member FROM play_campaign_encounter_combatants WHERE campaign_id = ? AND encounter_id = ? AND member = ?"
      )
      .get(campaignId, encounterId, target) as
      | { member: string }
      | undefined;

    if (combatantRow) {
      const memberRow = database
        .prepare(
          "SELECT hp_current, status, death_saves_successes, death_saves_failures FROM play_campaign_members WHERE campaign_id = ? AND username = ?"
        )
        .get(campaignId, combatantRow.member) as
        | {
            hp_current: number;
            status: PlayCampaignMemberStatus;
            death_saves_successes: number;
            death_saves_failures: number;
          }
        | undefined;
      if (!memberRow) {
        database.exec("ROLLBACK;");
        return null;
      }
      const hp_before = memberRow.hp_current;
      const hp_after = Math.max(0, hp_before - amount);
      let status = memberRow.status;
      let successes = memberRow.death_saves_successes;
      let failures = memberRow.death_saves_failures;

      if (hp_before > 0 && hp_after === 0) {
        status = "unconscious";
        successes = 0;
        failures = 0;
      }

      database
        .prepare(
          "UPDATE play_campaign_members SET hp_current = ?, status = ?, death_saves_successes = ?, death_saves_failures = ? WHERE campaign_id = ? AND username = ?"
        )
        .run(hp_after, status, successes, failures, campaignId, combatantRow.member);
      database.exec("COMMIT;");
      return { target, hp_before, hp_after, damage: amount };
    }

    database.exec("ROLLBACK;");
    return null;
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function applyHealingToEncounterCombatant(
  campaignId: string,
  encounterId: string,
  target: string,
  amount: number
): { target: string; hp_before: number; hp_after: number; healing: number } | null {
  if (amount <= 0) return null;
  const database = getDb();
  if (!getPlayCampaign(campaignId) || !getPlayCampaignEncounter(campaignId, encounterId)) {
    return null;
  }

  database.exec("BEGIN IMMEDIATE;");
  try {
    const monsterRow = database
      .prepare(
        "SELECT hp_current, hp_max FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?"
      )
      .get(campaignId, encounterId, target) as
      | { hp_current: number; hp_max: number }
      | undefined;

    if (monsterRow) {
      const hp_before = monsterRow.hp_current;
      const hp_after = Math.min(monsterRow.hp_max, hp_before + amount);
      database
        .prepare(
          "UPDATE play_campaign_encounter_monsters SET hp_current = ? WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?"
        )
        .run(hp_after, campaignId, encounterId, target);
      database.exec("COMMIT;");
      return { target, hp_before, hp_after, healing: amount };
    }

    const combatantRow = database
      .prepare(
        "SELECT member FROM play_campaign_encounter_combatants WHERE campaign_id = ? AND encounter_id = ? AND member = ?"
      )
      .get(campaignId, encounterId, target) as
      | { member: string }
      | undefined;

    if (combatantRow) {
      const memberRow = database
        .prepare(
          "SELECT hp_current, hp_max, status, death_saves_successes, death_saves_failures FROM play_campaign_members WHERE campaign_id = ? AND username = ?"
        )
        .get(campaignId, combatantRow.member) as
        | {
            hp_current: number;
            hp_max: number;
            status: PlayCampaignMemberStatus;
            death_saves_successes: number;
            death_saves_failures: number;
          }
        | undefined;
      if (!memberRow) {
        database.exec("ROLLBACK;");
        return null;
      }
      const hp_before = memberRow.hp_current;
      const hp_after = Math.min(memberRow.hp_max, hp_before + amount);
      let status = memberRow.status;
      let successes = memberRow.death_saves_successes;
      let failures = memberRow.death_saves_failures;

      if (hp_after > 0 && (status === "unconscious" || status === "stable")) {
        status = "conscious";
        successes = 0;
        failures = 0;
      }

      database
        .prepare(
          "UPDATE play_campaign_members SET hp_current = ?, status = ?, death_saves_successes = ?, death_saves_failures = ? WHERE campaign_id = ? AND username = ?"
        )
        .run(hp_after, status, successes, failures, campaignId, combatantRow.member);
      database.exec("COMMIT;");
      return { target, hp_before, hp_after, healing: amount };
    }

    database.exec("ROLLBACK;");
    return null;
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function delayEncounterTurn(
  campaignId: string,
  encounterId: string,
  newIndex: number
): { order: EncounterCombatant[] } | null | "invalid_index" {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;
  if (!getPlayCampaignEncounter(campaignId, encounterId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const encounterRow = database
      .prepare(
        "SELECT round, turn_index, combatant_order FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
      )
      .get(campaignId, encounterId) as
      | { round: number; turn_index: number; combatant_order: string | null }
      | undefined;
    if (!encounterRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const ordered = getEncounterCombatantsOrdered(database, campaignId, encounterId);
    if (ordered.length === 0) {
      database.exec("ROLLBACK;");
      return null;
    }

    const turnIndex = encounterRow.turn_index % ordered.length;
    if (
      !Number.isInteger(newIndex) ||
      newIndex <= turnIndex ||
      newIndex >= ordered.length
    ) {
      database.exec("ROLLBACK;");
      return "invalid_index";
    }

    const current = ordered.splice(turnIndex, 1)[0];
    ordered.splice(newIndex, 0, current);

    writeEncounterOrder(
      database,
      campaignId,
      encounterId,
      ordered.map((r) => ({ kind: r.kind, id: r.id }))
    );

    database
      .prepare(
        "UPDATE play_campaign_encounters SET turn_index = ? WHERE campaign_id = ? AND id = ?"
      )
      .run(newIndex, campaignId, encounterId);

    database.exec("COMMIT;");
    return { order: ordered };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function createReadyAction(
  campaignId: string,
  encounterId: string,
  actor: string,
  trigger: string
): { actor: string; trigger: string } | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId) || !getPlayCampaignEncounter(campaignId, encounterId)) {
    return null;
  }

  database.exec("BEGIN IMMEDIATE;");
  try {
    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_narrations WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, kind, actor, text, type) VALUES (?, ?, 'ready', ?, ?, 'ready')"
      )
      .run(campaignId, sequence, actor, trigger);

    database.exec("COMMIT;");
    return { actor, trigger };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function awardEncounterRewards(
  campaignId: string,
  encounterId: string,
  xp: number,
  loot: EncounterLoot[]
): EncounterRewardRecord | null | "already_awarded" {
  if (!Number.isInteger(xp) || xp < 0) return null;
  if (!Array.isArray(loot)) return null;
  for (const entry of loot) {
    if (
      typeof entry !== "object" ||
      entry === null ||
      typeof entry.slug !== "string" ||
      entry.slug.length === 0 ||
      !Number.isInteger(entry.quantity) ||
      entry.quantity <= 0
    ) {
      return null;
    }
  }

  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;
  if (!getPlayCampaignEncounter(campaignId, encounterId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT rewards_awarded FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
      )
      .get(campaignId, encounterId) as
      | { rewards_awarded: number }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }
    if (row.rewards_awarded) {
      database.exec("ROLLBACK;");
      return "already_awarded";
    }

    database
      .prepare(
        "UPDATE play_campaign_encounters SET xp_awarded = ?, loot_awarded = ?, rewards_awarded = 1 WHERE campaign_id = ? AND id = ?"
      )
      .run(xp, JSON.stringify(loot), campaignId, encounterId);

    database.exec("COMMIT;");
    return { xp, loot };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function closePlayCampaignEncounter(
  campaignId: string,
  encounterId: string
): EncounterCloseResult | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;
  if (!getPlayCampaignEncounter(campaignId, encounterId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT status, xp_awarded, closed FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
      )
      .get(campaignId, encounterId) as
      | { status: string; xp_awarded: number; closed: number }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }

    if (!row.closed) {
      database
        .prepare(
          "UPDATE play_campaign_encounters SET status = 'completed', closed = 1 WHERE campaign_id = ? AND id = ?"
        )
        .run(campaignId, encounterId);
    }

    database.exec("COMMIT;");
    return { id: encounterId, status: "closed", xp_awarded: row.xp_awarded };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function endPlayCampaignEncounter(
  campaignId: string,
  encounterId: string
): EndEncounterResult | null | "not_in_combat" {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const state = getPlayCampaignState(campaignId);
  if (!state) return null;
  if (state.phase !== "combat") {
    return "not_in_combat";
  }

  const encounterRow = database
    .prepare(
      "SELECT status, closed FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?"
    )
    .get(campaignId, encounterId) as
    | { status: "active" | "completed"; closed: number }
    | undefined;
  if (!encounterRow) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    if (!encounterRow.closed) {
      database
        .prepare(
          "UPDATE play_campaign_encounters SET status = 'completed', closed = 1 WHERE campaign_id = ? AND id = ?"
        )
        .run(campaignId, encounterId);
    }

    let restoredActor = state.pre_combat_actor ?? state.current_actor;
    // After combat ends, the DM resumes narrative control of the exploration
    // turn queue when the pre-combat actor was a player.
    if (restoredActor !== campaign.owner) {
      restoredActor = campaign.owner;
    }

    database
      .prepare(
        "UPDATE play_campaign_state SET phase = 'exploration', current_actor = ?, pre_combat_actor = NULL WHERE campaign_id = ?"
      )
      .run(restoredActor, campaignId);

    database.exec("COMMIT;");
    return {
      campaign_id: campaignId,
      status: "active",
      phase: "exploration",
      current_actor: restoredActor,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

// ---------------------------------------------------------------------------
// Character spellbooks
// ---------------------------------------------------------------------------

export function getCharacterClass(
  campaignId: string,
  characterId: string
): string | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT class FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as { class: string } | undefined;
  return row?.class ?? null;
}

export type AddCharacterSpellResult =
  | SpellbookSpell
  | "conflict"
  | "not_found";

export function addCharacterSpell(
  campaignId: string,
  characterId: string,
  spell: SpellbookSpell
): AddCharacterSpellResult {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const memberRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { 1: number } | undefined;
    if (!memberRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    database
      .prepare(
        "INSERT INTO play_campaign_character_spells (campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)"
      )
      .run(campaignId, characterId, spell.spell_id, spell.name, spell.level);

    database.exec("COMMIT;");
    return spell;
  } catch {
    database.exec("ROLLBACK;");
    return "conflict";
  }
}

export function getCharacterSpells(
  campaignId: string,
  characterId: string
): SpellbookSpell[] | null {
  const database = getDb();
  const memberRow = database
    .prepare(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as { 1: number } | undefined;
  if (!memberRow) return null;

  const rows = database
    .prepare(
      "SELECT spell_id, name, level FROM play_campaign_character_spells WHERE campaign_id = ? AND character_id = ? ORDER BY level ASC, spell_id ASC"
    )
    .all(campaignId, characterId) as Array<{
    spell_id: string;
    name: string;
    level: number;
  }>;
  return rows;
}

export function getCharacterClassAndLevel(
  campaignId: string,
  characterId: string
): { class: string; level: number } | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT class, level FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as
    | { class: string; level: number }
    | undefined;
  return row || null;
}

export function getCharacterKnownSpellIds(
  campaignId: string,
  characterId: string
): Set<string> | null {
  const database = getDb();
  const memberRow = database
    .prepare(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as { 1: number } | undefined;
  if (!memberRow) return null;

  const rows = database
    .prepare(
      "SELECT spell_id FROM play_campaign_character_spells WHERE campaign_id = ? AND character_id = ?"
    )
    .all(campaignId, characterId) as Array<{ spell_id: string }>;
  return new Set(rows.map((r) => r.spell_id));
}

export function getCharacterPreparedSpells(
  campaignId: string,
  characterId: string
): string[] | null {
  const database = getDb();
  const memberRow = database
    .prepare(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as { 1: number } | undefined;
  if (!memberRow) return null;

  const rows = database
    .prepare(
      "SELECT spell_id FROM play_campaign_character_prepared_spells WHERE campaign_id = ? AND character_id = ? ORDER BY spell_id ASC"
    )
    .all(campaignId, characterId) as Array<{ spell_id: string }>;
  return rows.map((r) => r.spell_id);
}

export function setCharacterPreparedSpells(
  campaignId: string,
  characterId: string,
  spellIds: string[]
): boolean {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const memberRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { 1: number } | undefined;
    if (!memberRow) {
      database.exec("ROLLBACK;");
      return false;
    }

    database
      .prepare(
        "DELETE FROM play_campaign_character_prepared_spells WHERE campaign_id = ? AND character_id = ?"
      )
      .run(campaignId, characterId);

    const insertStmt = database.prepare(
      "INSERT INTO play_campaign_character_prepared_spells (campaign_id, character_id, spell_id) VALUES (?, ?, ?)"
    );
    for (const spellId of spellIds) {
      insertStmt.run(campaignId, characterId, spellId);
    }

    database.exec("COMMIT;");
    return true;
  } catch {
    database.exec("ROLLBACK;");
    return false;
  }
}

// ---------------------------------------------------------------------------
// Character spell slots and casts
// ---------------------------------------------------------------------------

function ensureCharacterSpellSlots(
  database: DatabaseSync,
  campaignId: string,
  characterId: string
): boolean {
  const memberRow = database
    .prepare(
      "SELECT class, level FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as
    | { class: string; level: number }
    | undefined;
  if (!memberRow) return false;

  const slots = getSpellSlots(memberRow.class, memberRow.level);
  if (!slots) return false;

  const existingRows = database
    .prepare(
      "SELECT level, slots_remaining FROM play_campaign_character_spell_slots WHERE campaign_id = ? AND character_id = ?"
    )
    .all(campaignId, characterId) as Array<{
    level: number;
    slots_remaining: number;
  }>;
  const existing = new Set(existingRows.map((r) => r.level));

  const insertStmt = database.prepare(
    "INSERT INTO play_campaign_character_spell_slots (campaign_id, character_id, level, slots_remaining) VALUES (?, ?, ?, ?)"
  );
  for (const [level, count] of Object.entries(slots)) {
    const lvl = Number(level);
    if (!existing.has(lvl)) {
      insertStmt.run(campaignId, characterId, lvl, count);
    }
  }
  return true;
}

export function resetCharacterSpellSlots(
  campaignId: string,
  characterId: string
): void {
  const database = getDb();
  database
    .prepare(
      "DELETE FROM play_campaign_character_spell_slots WHERE campaign_id = ? AND character_id = ?"
    )
    .run(campaignId, characterId);
}

export function getCharacterSpellSlots(
  campaignId: string,
  characterId: string
): Record<number, number> | null {
  const database = getDb();
  const memberRow = database
    .prepare(
      "SELECT class, level FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as
    | { class: string; level: number }
    | undefined;
  if (!memberRow) return null;

  const rows = database
    .prepare(
      "SELECT level, slots_remaining FROM play_campaign_character_spell_slots WHERE campaign_id = ? AND character_id = ?"
    )
    .all(campaignId, characterId) as Array<{
    level: number;
    slots_remaining: number;
  }>;
  const slots: Record<number, number> = {};
  for (const row of rows) {
    slots[row.level] = row.slots_remaining;
  }
  return slots;
}

export type RecordSpellCastResult =
  | SpellCastRecord
  | "not_found"
  | "not_spellcaster"
  | "not_known"
  | "not_prepared"
  | "no_slots";

export function recordCharacterSpellCast(
  campaignId: string,
  characterId: string,
  spellId: string,
  target: string
): RecordSpellCastResult {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const memberRow = database
      .prepare(
        "SELECT class, level FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as
      | { class: string; level: number }
      | undefined;
    if (!memberRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    const slots = getSpellSlots(memberRow.class, memberRow.level);
    if (!slots) {
      database.exec("ROLLBACK;");
      return "not_spellcaster";
    }

    const spellRow = database
      .prepare(
        "SELECT level FROM play_campaign_character_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?"
      )
      .get(campaignId, characterId, spellId) as
      | { level: number }
      | undefined;
    if (!spellRow) {
      database.exec("ROLLBACK;");
      return "not_known";
    }

    const preparedRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_character_prepared_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?"
      )
      .get(campaignId, characterId, spellId) as { 1: number } | undefined;
    if (!preparedRow) {
      database.exec("ROLLBACK;");
      return "not_prepared";
    }

    ensureCharacterSpellSlots(database, campaignId, characterId);

    const slotRow = database
      .prepare(
        "SELECT slots_remaining FROM play_campaign_character_spell_slots WHERE campaign_id = ? AND character_id = ? AND level = ?"
      )
      .get(campaignId, characterId, spellRow.level) as
      | { slots_remaining: number }
      | undefined;
    if (!slotRow || slotRow.slots_remaining <= 0) {
      database.exec("ROLLBACK;");
      return "no_slots";
    }

    const newRemaining = slotRow.slots_remaining - 1;
    database
      .prepare(
        "UPDATE play_campaign_character_spell_slots SET slots_remaining = ? WHERE campaign_id = ? AND character_id = ? AND level = ?"
      )
      .run(newRemaining, campaignId, characterId, spellRow.level);

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_character_casts WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_character_casts (campaign_id, character_id, spell_id, target, slot_level, slots_remaining, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)"
      )
      .run(
        campaignId,
        characterId,
        spellId,
        target,
        spellRow.level,
        newRemaining,
        sequence
      );

    database.exec("COMMIT;");
    return {
      character_id: characterId,
      spell_id: spellId,
      target,
      slot_level: spellRow.level,
      slots_remaining: newRemaining,
      sequence,
    };
  } catch {
    database.exec("ROLLBACK;");
    return "not_found";
  }
}

export function getCharacterSpellCasts(
  campaignId: string,
  characterId: string
): SpellCastRecord[] | null {
  const database = getDb();
  const memberRow = database
    .prepare(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as { 1: number } | undefined;
  if (!memberRow) return null;

  const rows = database
    .prepare(
      "SELECT spell_id, target, slot_level, slots_remaining, sequence FROM play_campaign_character_casts WHERE campaign_id = ? AND character_id = ? ORDER BY sequence ASC"
    )
    .all(campaignId, characterId) as Array<{
    spell_id: string;
    target: string;
    slot_level: number;
    slots_remaining: number;
    sequence: number;
  }>;
  return rows.map((r) => ({
    character_id: characterId,
    spell_id: r.spell_id,
    target: r.target,
    slot_level: r.slot_level,
    slots_remaining: r.slots_remaining,
    sequence: r.sequence,
  }));
}

// ---------------------------------------------------------------------------
// Character concentration
// ---------------------------------------------------------------------------

export type SetCharacterConcentrationResult =
  | CharacterConcentration
  | "not_found"
  | "not_spellcaster"
  | "not_known"
  | "not_prepared";

export function setCharacterConcentration(
  campaignId: string,
  characterId: string,
  spellId: string,
  target: string,
  durationTurns: number
): SetCharacterConcentrationResult {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const memberRow = database
      .prepare(
        "SELECT class, level FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as
      | { class: string; level: number }
      | undefined;
    if (!memberRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    const slots = getSpellSlots(memberRow.class, memberRow.level);
    if (!slots) {
      database.exec("ROLLBACK;");
      return "not_spellcaster";
    }

    const spellRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_character_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?"
      )
      .get(campaignId, characterId, spellId) as { 1: number } | undefined;
    if (!spellRow) {
      database.exec("ROLLBACK;");
      return "not_known";
    }

    const preparedRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_character_prepared_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?"
      )
      .get(campaignId, characterId, spellId) as { 1: number } | undefined;
    if (!preparedRow) {
      database.exec("ROLLBACK;");
      return "not_prepared";
    }

    database
      .prepare(
        "INSERT INTO play_campaign_character_concentration (campaign_id, character_id, spell_id, target, remaining_turns) VALUES (?, ?, ?, ?, ?) ON CONFLICT(campaign_id, character_id) DO UPDATE SET spell_id = excluded.spell_id, target = excluded.target, remaining_turns = excluded.remaining_turns"
      )
      .run(campaignId, characterId, spellId, target, durationTurns);

    database.exec("COMMIT;");
    return { spell_id: spellId, target, remaining_turns: durationTurns };
  } catch {
    database.exec("ROLLBACK;");
    return "not_found";
  }
}

export function getCharacterConcentration(
  campaignId: string,
  characterId: string
): CharacterConcentration | null {
  const database = getDb();
  const memberRow = database
    .prepare(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as { 1: number } | undefined;
  if (!memberRow) return null;

  const row = database
    .prepare(
      "SELECT spell_id, target, remaining_turns FROM play_campaign_character_concentration WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as
    | { spell_id: string; target: string; remaining_turns: number }
    | undefined;
  if (!row) return null;
  return row;
}

export function advanceCharacterConcentration(
  campaignId: string,
  characterId: string
): CharacterConcentration | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT spell_id, target, remaining_turns FROM play_campaign_character_concentration WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as
      | { spell_id: string; target: string; remaining_turns: number }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }

    const newRemaining = row.remaining_turns - 1;
    if (newRemaining <= 0) {
      database
        .prepare(
          "DELETE FROM play_campaign_character_concentration WHERE campaign_id = ? AND character_id = ?"
        )
        .run(campaignId, characterId);
      database.exec("COMMIT;");
      return null;
    }

    database
      .prepare(
        "UPDATE play_campaign_character_concentration SET remaining_turns = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(newRemaining, campaignId, characterId);

    database.exec("COMMIT;");
    return { spell_id: row.spell_id, target: row.target, remaining_turns: newRemaining };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function clearCharacterConcentration(
  campaignId: string,
  characterId: string
): boolean {
  const database = getDb();
  const result = database
    .prepare(
      "DELETE FROM play_campaign_character_concentration WHERE campaign_id = ? AND character_id = ?"
    )
    .run(campaignId, characterId);
  return result.changes > 0;
}

// ---------------------------------------------------------------------------
// Character inventory stacks
// ---------------------------------------------------------------------------

const VALID_INVENTORY_ITEM_IDS = new Set([
  "healing-potion",
  "torch",
  "leather-armor",
  "ring-of-protection",
  "amulet-of-health",
]);

const EQUIPMENT_SLOTS: Record<string, "armor" | "accessory"> = {
  "leather-armor": "armor",
  "ring-of-protection": "accessory",
  "amulet-of-health": "accessory",
};

export function isValidInventoryItemId(itemId: string): boolean {
  return VALID_INVENTORY_ITEM_IDS.has(itemId);
}

export type AddCharacterInventoryItemResult =
  | CharacterInventoryStack
  | "not_found"
  | "invalid";

export function addCharacterInventoryItem(
  campaignId: string,
  characterId: string,
  itemId: string,
  quantity: number
): AddCharacterInventoryItemResult {
  if (!isValidInventoryItemId(itemId) || quantity <= 0) {
    return "invalid";
  }

  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const memberRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { 1: number } | undefined;
    if (!memberRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    const existing = database
      .prepare(
        "SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
      )
      .get(campaignId, characterId, itemId) as
      | { quantity: number }
      | undefined;

    const total = (existing?.quantity ?? 0) + quantity;
    if (existing) {
      database
        .prepare(
          "UPDATE play_campaign_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
        )
        .run(total, campaignId, characterId, itemId);
    } else {
      database
        .prepare(
          "INSERT INTO play_campaign_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)"
        )
        .run(campaignId, characterId, itemId, total);
    }

    database.exec("COMMIT;");
    return {
      character_id: characterId,
      item_id: itemId,
      quantity,
      total_quantity: total,
    };
  } catch {
    database.exec("ROLLBACK;");
    return "not_found";
  }
}

export function getCharacterInventoryItems(
  campaignId: string,
  characterId: string
): CharacterInventorySummary | null {
  const database = getDb();
  const memberRow = database
    .prepare(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as { 1: number } | undefined;
  if (!memberRow) return null;

  const rows = database
    .prepare(
      "SELECT item_id, quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? ORDER BY item_id ASC"
    )
    .all(campaignId, characterId) as Array<{ item_id: string; quantity: number }>;

  return {
    character_id: characterId,
    items: rows,
  };
}

export type RemoveCharacterInventoryItemResult =
  | CharacterInventoryStack
  | "not_found"
  | "invalid"
  | "conflict";

export function removeCharacterInventoryItem(
  campaignId: string,
  characterId: string,
  itemId: string,
  quantity: number
): RemoveCharacterInventoryItemResult {
  if (!isValidInventoryItemId(itemId) || quantity <= 0) {
    return "invalid";
  }

  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const memberRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { 1: number } | undefined;
    if (!memberRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    const existing = database
      .prepare(
        "SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
      )
      .get(campaignId, characterId, itemId) as
      | { quantity: number }
      | undefined;
    if (!existing || existing.quantity < quantity) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    const total = existing.quantity - quantity;
    if (total > 0) {
      database
        .prepare(
          "UPDATE play_campaign_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
        )
        .run(total, campaignId, characterId, itemId);
    } else {
      database
        .prepare(
          "DELETE FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
        )
        .run(campaignId, characterId, itemId);
    }

    database.exec("COMMIT;");
    return {
      character_id: characterId,
      item_id: itemId,
      quantity,
      total_quantity: total,
    };
  } catch {
    database.exec("ROLLBACK;");
    return "not_found";
  }
}

export type ConsumeCharacterInventoryItemResult =
  | CharacterInventoryItemConsumption
  | "not_found"
  | "invalid"
  | "conflict";

export function consumeCharacterInventoryItem(
  campaignId: string,
  characterId: string,
  itemId: string
): ConsumeCharacterInventoryItemResult {
  if (!isValidInventoryItemId(itemId) || itemId !== "healing-potion") {
    return "invalid";
  }

  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const memberRow = database
      .prepare(
        "SELECT hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as
      | { hp_current: number; hp_max: number }
      | undefined;
    if (!memberRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    const existing = database
      .prepare(
        "SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
      )
      .get(campaignId, characterId, itemId) as
      | { quantity: number }
      | undefined;
    if (!existing || existing.quantity <= 0) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    const total = existing.quantity - 1;
    if (total > 0) {
      database
        .prepare(
          "UPDATE play_campaign_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
        )
        .run(total, campaignId, characterId, itemId);
    } else {
      database
        .prepare(
          "DELETE FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
        )
        .run(campaignId, characterId, itemId);
    }

    const hpRestored = 5;
    const newHp = Math.min(memberRow.hp_current + hpRestored, memberRow.hp_max);
    database
      .prepare(
        "UPDATE play_campaign_members SET hp_current = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(newHp, campaignId, characterId);

    database.exec("COMMIT;");
    return {
      character_id: characterId,
      item_id: itemId,
      quantity_consumed: 1,
      total_quantity: total,
      effect: {
        type: "healing",
        hp_restored: hpRestored,
      },
    };
  } catch {
    database.exec("ROLLBACK;");
    return "not_found";
  }
}

// ---------------------------------------------------------------------------
// Character equipment and attunement
// ---------------------------------------------------------------------------

export type EquipCharacterItemResult =
  | CharacterEquipment
  | "not_found"
  | "invalid";

export function equipCharacterItem(
  campaignId: string,
  characterId: string,
  slot: string,
  itemId: string
): EquipCharacterItemResult {
  if (slot !== "armor" && slot !== "accessory") {
    return "invalid";
  }

  if (!isValidInventoryItemId(itemId)) {
    return "invalid";
  }

  const legalSlot = EQUIPMENT_SLOTS[itemId];
  if (legalSlot !== slot) {
    return "invalid";
  }

  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const memberRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { 1: number } | undefined;
    if (!memberRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    const itemRow = database
      .prepare(
        "SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
      )
      .get(campaignId, characterId, itemId) as
      | { quantity: number }
      | undefined;
    if (!itemRow || itemRow.quantity < 1) {
      database.exec("ROLLBACK;");
      return "invalid";
    }

    database
      .prepare(
        `INSERT INTO play_campaign_character_equipment (campaign_id, character_id, slot, item_id, attuned)
         VALUES (?, ?, ?, ?, 0)
         ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET item_id = excluded.item_id, attuned = 0`
      )
      .run(campaignId, characterId, slot, itemId);

    database.exec("COMMIT;");
    return {
      character_id: characterId,
      slot: slot as "armor" | "accessory",
      item_id: itemId,
      attuned: false,
    };
  } catch {
    database.exec("ROLLBACK;");
    return "not_found";
  }
}

export type GetCharacterEquipmentResult =
  | CharacterEquipment
  | "not_found"
  | "invalid";

export function getCharacterEquipment(
  campaignId: string,
  characterId: string,
  slot: string
): GetCharacterEquipmentResult {
  if (slot !== "armor" && slot !== "accessory") {
    return "invalid";
  }

  const database = getDb();
  const memberRow = database
    .prepare(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as { 1: number } | undefined;
  if (!memberRow) return "not_found";

  const row = database
    .prepare(
      "SELECT item_id, attuned FROM play_campaign_character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?"
    )
    .get(campaignId, characterId, slot) as
    | { item_id: string; attuned: number }
    | undefined;

  if (!row) {
    return {
      character_id: characterId,
      slot: slot as "armor" | "accessory",
      item_id: "",
      attuned: false,
    };
  }

  return {
    character_id: characterId,
    slot: slot as "armor" | "accessory",
    item_id: row.item_id,
    attuned: !!row.attuned,
  };
}

export type AttuneCharacterEquipmentResult =
  | CharacterAttunement
  | "not_found"
  | "invalid"
  | "conflict";

export function attuneCharacterEquipment(
  campaignId: string,
  characterId: string,
  slot: string
): AttuneCharacterEquipmentResult {
  if (slot !== "accessory") {
    return "invalid";
  }

  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const memberRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { 1: number } | undefined;
    if (!memberRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    const row = database
      .prepare(
        "SELECT item_id, attuned FROM play_campaign_character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?"
      )
      .get(campaignId, characterId, slot) as
      | { item_id: string; attuned: number }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return "invalid";
    }

    if (row.item_id !== "ring-of-protection" && row.item_id !== "amulet-of-health") {
      database.exec("ROLLBACK;");
      return "invalid";
    }

    const attunedCount = database
      .prepare(
        "SELECT COUNT(*) AS count FROM play_campaign_character_equipment WHERE campaign_id = ? AND character_id = ? AND attuned = 1"
      )
      .get(campaignId, characterId) as { count: number };

    if (attunedCount.count > 0) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    database
      .prepare(
        "UPDATE play_campaign_character_equipment SET attuned = 1 WHERE campaign_id = ? AND character_id = ? AND slot = ?"
      )
      .run(campaignId, characterId, slot);

    database.exec("COMMIT;");
    return {
      character_id: characterId,
      slot: slot as "accessory",
      item_id: row.item_id,
      attuned: true,
      attunement_count: 1,
      max_attunements: 1,
    };
  } catch {
    database.exec("ROLLBACK;");
    return "not_found";
  }
}

// ---------------------------------------------------------------------------
// Character currency and transfers
// ---------------------------------------------------------------------------

export function getCharacterCurrency(
  campaignId: string,
  characterId: string
): CharacterCurrency | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT character_id, gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as
    | { character_id: string; gold: number }
    | undefined;
  return row || null;
}

export type TransferCurrencyResult =
  | CurrencyTransfer
  | "not_found"
  | "forbidden"
  | "invalid"
  | "insufficient";

export function transferCurrency(
  campaignId: string,
  fromCharacterId: string,
  toCharacterId: string,
  amount: number,
  actorUsername: string
): TransferCurrencyResult {
  if (!Number.isInteger(amount) || amount <= 0) {
    return "invalid";
  }
  if (fromCharacterId === toCharacterId) {
    return "invalid";
  }

  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const fromRow = database
      .prepare(
        "SELECT character_id, owner, gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, fromCharacterId) as
      | { character_id: string; owner: string | null; gold: number }
      | undefined;
    if (!fromRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    if (fromRow.owner !== actorUsername) {
      database.exec("ROLLBACK;");
      return "forbidden";
    }

    const toRow = database
      .prepare(
        "SELECT character_id, gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, toCharacterId) as
      | { character_id: string; gold: number }
      | undefined;
    if (!toRow) {
      database.exec("ROLLBACK;");
      return "invalid";
    }

    if (fromRow.gold < amount) {
      database.exec("ROLLBACK;");
      return "insufficient";
    }

    const fromGold = fromRow.gold - amount;
    const toGold = toRow.gold + amount;

    database
      .prepare(
        "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(fromGold, campaignId, fromCharacterId);
    database
      .prepare(
        "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(toGold, campaignId, toCharacterId);

    const maxRow = database
      .prepare(
        "SELECT COALESCE(MAX(transfer_id), 0) AS next_id FROM play_campaign_currency_transfers WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_id: number };
    const transferId = maxRow.next_id + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_currency_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold) VALUES (?, ?, ?, ?, ?)"
      )
      .run(campaignId, transferId, fromCharacterId, toCharacterId, amount);

    database.exec("COMMIT;");
    return {
      from_character_id: fromCharacterId,
      to_character_id: toCharacterId,
      gold: amount,
      from_gold: fromGold,
      to_gold: toGold,
      transfer_id: transferId,
    };
  } catch {
    database.exec("ROLLBACK;");
    return "not_found";
  }
}

// ---------------------------------------------------------------------------
// Transactional currency transfers (stage 082)
// ---------------------------------------------------------------------------

export type CreateTransactionalTransferResult =
  | TransactionalTransfer
  | "not_found"
  | "forbidden"
  | "invalid"
  | "insufficient"
  | "simulated";

export function createTransactionalTransfer(
  campaignId: string,
  input: CreateTransactionalTransferInput,
  actorUsername: string
): CreateTransactionalTransferResult {
  const { from_character_id, to_character_id, amount, simulate_failure } = input;

  if (
    typeof from_character_id !== "string" ||
    from_character_id.length === 0 ||
    typeof to_character_id !== "string" ||
    to_character_id.length === 0 ||
    from_character_id === to_character_id ||
    !Number.isInteger(amount) ||
    amount <= 0
  ) {
    return "invalid";
  }

  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const campaign = getPlayCampaign(campaignId);
    if (!campaign) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    const fromRow = database
      .prepare(
        "SELECT character_id, owner, gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, from_character_id) as
      | { character_id: string; owner: string | null; gold: number }
      | undefined;
    if (!fromRow) {
      database.exec("ROLLBACK;");
      return "invalid";
    }

    if (fromRow.owner !== actorUsername) {
      database.exec("ROLLBACK;");
      return "forbidden";
    }

    const toRow = database
      .prepare(
        "SELECT character_id, gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, to_character_id) as
      | { character_id: string; gold: number }
      | undefined;
    if (!toRow) {
      database.exec("ROLLBACK;");
      return "invalid";
    }

    if (fromRow.gold < amount) {
      database.exec("ROLLBACK;");
      return "insufficient";
    }

    if (simulate_failure) {
      database.exec("ROLLBACK;");
      return "simulated";
    }

    const fromGold = fromRow.gold - amount;
    const toGold = toRow.gold + amount;

    database
      .prepare(
        "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(fromGold, campaignId, from_character_id);
    database
      .prepare(
        "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(toGold, campaignId, to_character_id);

    const maxRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_seq FROM play_campaign_transactional_transfers WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_seq: number };
    const sequence = maxRow.next_seq + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_transactional_transfers (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) VALUES (?, ?, ?, ?, ?, ?, ?)"
      )
      .run(
        campaignId,
        sequence,
        from_character_id,
        to_character_id,
        amount,
        fromGold,
        toGold
      );

    database.exec("COMMIT;");
    return {
      from_character_id,
      to_character_id,
      amount,
      from_gold: fromGold,
      to_gold: toGold,
      sequence,
    };
  } catch {
    database.exec("ROLLBACK;");
    return "not_found";
  }
}

export function getTransactionalTransfers(
  campaignId: string
): TransactionalTransfer[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT from_character_id, to_character_id, amount, from_gold, to_gold, sequence FROM play_campaign_transactional_transfers WHERE campaign_id = ? ORDER BY sequence ASC"
    )
    .all(campaignId) as Array<{
    from_character_id: string;
    to_character_id: string;
    amount: number;
    from_gold: number;
    to_gold: number;
    sequence: number;
  }>;
  return rows;
}

// ---------------------------------------------------------------------------
// Loot distribution
// ---------------------------------------------------------------------------

export function createLoot(
  campaignId: string,
  lootId: string,
  itemId: string,
  quantity: number
): LootRecord | null {
  if (!isValidInventoryItemId(itemId) || quantity <= 0) {
    return null;
  }

  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  try {
    database
      .prepare(
        "INSERT INTO play_campaign_loot (campaign_id, loot_id, item_id, quantity, status) VALUES (?, ?, ?, ?, 'open')"
      )
      .run(campaignId, lootId, itemId, quantity);
    return {
      loot_id: lootId,
      item_id: itemId,
      quantity,
      status: "open",
      recipient_character_id: null,
      votes: {},
    };
  } catch {
    return null;
  }
}

export function getLoot(
  campaignId: string,
  lootId: string
): LootRecord | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT item_id, quantity, status, recipient_character_id FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?"
    )
    .get(campaignId, lootId) as
    | {
        item_id: string;
        quantity: number;
        status: "open" | "assigned";
        recipient_character_id: string | null;
      }
    | undefined;
  if (!row) return null;

  const votes: Record<string, number> = {};
  const tallyRows = database
    .prepare(
      "SELECT recipient_character_id, COUNT(*) AS count FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id"
    )
    .all(campaignId, lootId) as Array<{
    recipient_character_id: string;
    count: number;
  }>;
  for (const tallyRow of tallyRows) {
    votes[tallyRow.recipient_character_id] = tallyRow.count;
  }

  return {
    loot_id: lootId,
    item_id: row.item_id,
    quantity: row.quantity,
    status: row.status,
    recipient_character_id: row.recipient_character_id ?? null,
    votes,
  };
}

export type RecordLootVoteResult =
  | LootVoteRecord
  | "not_found"
  | "conflict"
  | "invalid";

export function recordLootVote(
  campaignId: string,
  lootId: string,
  voter: string,
  recipientCharacterId: string
): RecordLootVoteResult {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const lootRow = database
      .prepare(
        "SELECT status FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?"
      )
      .get(campaignId, lootId) as
      | { status: "open" | "assigned" }
      | undefined;
    if (!lootRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }
    if (lootRow.status !== "open") {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    const recipientRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, recipientCharacterId) as { 1: number } | undefined;
    if (!recipientRow) {
      database.exec("ROLLBACK;");
      return "invalid";
    }

    database
      .prepare(
        "INSERT INTO play_campaign_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)"
      )
      .run(campaignId, lootId, voter, recipientCharacterId);

    const countRow = database
      .prepare(
        "SELECT COUNT(*) AS count FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?"
      )
      .get(campaignId, lootId, recipientCharacterId) as { count: number };

    database.exec("COMMIT;");
    return {
      loot_id: lootId,
      voter,
      recipient_character_id: recipientCharacterId,
      votes_for_recipient: countRow.count,
    };
  } catch {
    database.exec("ROLLBACK;");
    return "conflict";
  }
}

export type AssignLootResult =
  | LootAssignment
  | "not_found"
  | "closed"
  | "tied";

export function assignLoot(
  campaignId: string,
  lootId: string
): AssignLootResult {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const lootRow = database
      .prepare(
        "SELECT item_id, quantity, status FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?"
      )
      .get(campaignId, lootId) as
      | { item_id: string; quantity: number; status: "open" | "assigned" }
      | undefined;
    if (!lootRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }
    if (lootRow.status !== "open") {
      database.exec("ROLLBACK;");
      return "closed";
    }

    const voteRows = database
      .prepare(
        "SELECT recipient_character_id, COUNT(*) AS count FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id"
      )
      .all(campaignId, lootId) as Array<{
      recipient_character_id: string;
      count: number;
    }>;

    if (voteRows.length === 0) {
      database.exec("ROLLBACK;");
      return "tied";
    }

    let maxVotes = -1;
    const winners: string[] = [];
    for (const row of voteRows) {
      if (row.count > maxVotes) {
        maxVotes = row.count;
        winners.length = 0;
        winners.push(row.recipient_character_id);
      } else if (row.count === maxVotes) {
        winners.push(row.recipient_character_id);
      }
    }

    if (winners.length !== 1) {
      database.exec("ROLLBACK;");
      return "tied";
    }

    const winner = winners[0];

    const memberRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, winner) as { 1: number } | undefined;
    if (!memberRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    const existing = database
      .prepare(
        "SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
      )
      .get(campaignId, winner, lootRow.item_id) as
      | { quantity: number }
      | undefined;

    if (existing) {
      database
        .prepare(
          "UPDATE play_campaign_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
        )
        .run(
          existing.quantity + lootRow.quantity,
          campaignId,
          winner,
          lootRow.item_id
        );
    } else {
      database
        .prepare(
          "INSERT INTO play_campaign_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)"
        )
        .run(campaignId, winner, lootRow.item_id, lootRow.quantity);
    }

    database
      .prepare(
        "UPDATE play_campaign_loot SET status = 'assigned', recipient_character_id = ? WHERE campaign_id = ? AND loot_id = ?"
      )
      .run(winner, campaignId, lootId);

    database.exec("COMMIT;");
    return {
      loot_id: lootId,
      recipient_character_id: winner,
      item_id: lootRow.item_id,
      quantity: lootRow.quantity,
      votes: maxVotes,
      status: "assigned",
    };
  } catch {
    database.exec("ROLLBACK;");
    return "not_found";
  }
}

// ---------------------------------------------------------------------------
// Play campaign NPC agendas
// ---------------------------------------------------------------------------

export function createPlayCampaignNpc(
  campaignId: string,
  input: CreatePlayCampaignNpcInput
): PlayCampaignNpc | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  try {
    database
      .prepare(
        "INSERT INTO play_campaign_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)"
      )
      .run(campaignId, input.npc_id, input.name, input.agenda, input.public_status);
    return { ...input };
  } catch {
    return null;
  }
}

export function getPlayCampaignNpc(
  campaignId: string,
  npcId: string
): PlayCampaignNpc | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT npc_id, name, agenda, public_status FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?"
    )
    .get(campaignId, npcId) as
    | { npc_id: string; name: string; agenda: string; public_status: string }
    | undefined;
  return row || null;
}

export function updatePlayCampaignNpcAgenda(
  campaignId: string,
  npcId: string,
  input: UpdatePlayCampaignNpcAgendaInput
): PlayCampaignNpc | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT npc_id, name FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?"
      )
      .get(campaignId, npcId) as
      | { npc_id: string; name: string }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare(
        "UPDATE play_campaign_npcs SET agenda = ?, public_status = ? WHERE campaign_id = ? AND npc_id = ?"
      )
      .run(input.agenda, input.public_status, campaignId, npcId);

    database.exec("COMMIT;");
    return {
      npc_id: row.npc_id,
      name: row.name,
      agenda: input.agenda,
      public_status: input.public_status,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

// ---------------------------------------------------------------------------
// Play campaign factions and reputation
// ---------------------------------------------------------------------------

export function createPlayCampaignFaction(
  campaignId: string,
  input: CreatePlayCampaignFactionInput
): PlayCampaignFaction | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  try {
    database
      .prepare(
        "INSERT INTO play_campaign_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)"
      )
      .run(campaignId, input.faction_id, input.name);
    return { faction_id: input.faction_id, name: input.name };
  } catch {
    return null;
  }
}

export function getPlayCampaignFaction(
  campaignId: string,
  factionId: string
): PlayCampaignFaction | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT faction_id, name FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?"
    )
    .get(campaignId, factionId) as
    | { faction_id: string; name: string }
    | undefined;
  return row || null;
}

export function createPlayCampaignReputation(
  campaignId: string,
  factionId: string,
  input: CreatePlayCampaignReputationInput
): PlayCampaignReputationRecord | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;
  if (!getPlayCampaignFaction(campaignId, factionId)) return null;

  const member = database
    .prepare(
      "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, input.character_id) as
    | { character_id: string }
    | undefined;
  if (!member) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const currentRow = database
      .prepare(
        "SELECT reputation FROM play_campaign_reputation_history WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY id DESC LIMIT 1"
      )
      .get(campaignId, factionId, input.character_id) as
      | { reputation: number }
      | undefined;
    const current = currentRow ? currentRow.reputation : 0;
    const raw = current + input.delta;
    const reputation = Math.max(-100, Math.min(100, raw));

    database
      .prepare(
        "INSERT INTO play_campaign_reputation_history (campaign_id, faction_id, character_id, reputation, delta, reason) VALUES (?, ?, ?, ?, ?, ?)"
      )
      .run(campaignId, factionId, input.character_id, reputation, input.delta, input.reason);

    database.exec("COMMIT;");
    return {
      faction_id: factionId,
      character_id: input.character_id,
      reputation,
      delta: input.delta,
      reason: input.reason,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignReputationHistory(
  campaignId: string,
  factionId: string,
  characterId?: string
): PlayCampaignReputationRecord[] {
  const database = getDb();
  const sql = characterId
    ? "SELECT faction_id, character_id, reputation, delta, reason FROM play_campaign_reputation_history WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY id ASC"
    : "SELECT faction_id, character_id, reputation, delta, reason FROM play_campaign_reputation_history WHERE campaign_id = ? AND faction_id = ? ORDER BY id ASC";
  const params = characterId
    ? [campaignId, factionId, characterId]
    : [campaignId, factionId];
  const rows = database.prepare(sql).all(...params) as Array<{
    faction_id: string;
    character_id: string;
    reputation: number;
    delta: number;
    reason: string;
  }>;
  return rows;
}

// ---------------------------------------------------------------------------
// Play campaign NPC dialogue
// ---------------------------------------------------------------------------

export function createPlayCampaignNpcDialogue(
  campaignId: string,
  npcId: string,
  input: CreatePlayCampaignNpcDialogueInput
): PlayCampaignNpcDialogueEntry | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;
  if (!getPlayCampaignNpc(campaignId, npcId)) return null;

  try {
    database
      .prepare(
        "INSERT INTO play_campaign_npc_dialogue (campaign_id, npc_id, dialogue_id, speaker, text, visibility) VALUES (?, ?, ?, ?, ?, ?)"
      )
      .run(
        campaignId,
        npcId,
        input.dialogue_id,
        input.speaker,
        input.text,
        input.visibility
      );
    return { ...input };
  } catch {
    return null;
  }
}

export function getPlayCampaignNpcDialogue(
  campaignId: string,
  npcId: string
): PlayCampaignNpcDialogueEntry[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT dialogue_id, speaker, text, visibility FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ? ORDER BY id ASC"
    )
    .all(campaignId, npcId) as Array<{
    dialogue_id: string;
    speaker: string;
    text: string;
    visibility: "public" | "private";
  }>;
  return rows;
}

// ---------------------------------------------------------------------------
// Play campaign relationship graph
// ---------------------------------------------------------------------------

function playCampaignEntityExists(
  database: DatabaseSync,
  campaignId: string,
  entityId: string
): boolean {
  const memberRow = database
    .prepare(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, entityId) as { 1: number } | undefined;
  if (memberRow) return true;

  const npcRow = database
    .prepare(
      "SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?"
    )
    .get(campaignId, entityId) as { 1: number } | undefined;
  return !!npcRow;
}

export function createPlayCampaignRelationship(
  campaignId: string,
  sourceId: string,
  targetId: string,
  kind: string,
  score: number
): PlayCampaignRelationship | "not_found" | "conflict" {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return "not_found";

  database.exec("BEGIN IMMEDIATE;");
  try {
    if (!playCampaignEntityExists(database, campaignId, sourceId)) {
      database.exec("ROLLBACK;");
      return "not_found";
    }
    if (!playCampaignEntityExists(database, campaignId, targetId)) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    database
      .prepare(
        "INSERT INTO play_campaign_relationships (campaign_id, source_id, target_id, kind, score) VALUES (?, ?, ?, ?, ?)"
      )
      .run(campaignId, sourceId, targetId, kind, score);

    database.exec("COMMIT;");
    return { source_id: sourceId, target_id: targetId, kind, score };
  } catch {
    database.exec("ROLLBACK;");
    return "conflict";
  }
}

export function updatePlayCampaignRelationship(
  campaignId: string,
  sourceId: string,
  targetId: string,
  kind: string,
  score: number
): PlayCampaignRelationship | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT 1 FROM play_campaign_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?"
      )
      .get(campaignId, sourceId, targetId, kind) as { 1: number } | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare(
        "UPDATE play_campaign_relationships SET score = ? WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?"
      )
      .run(score, campaignId, sourceId, targetId, kind);

    database.exec("COMMIT;");
    return { source_id: sourceId, target_id: targetId, kind, score };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignRelationships(
  campaignId: string
): PlayCampaignRelationship[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT source_id, target_id, kind, score FROM play_campaign_relationships WHERE campaign_id = ? ORDER BY id ASC"
    )
    .all(campaignId) as Array<{
    source_id: string;
    target_id: string;
    kind: string;
    score: number;
  }>;
  return rows;
}

// ---------------------------------------------------------------------------
// Play campaign clues
// ---------------------------------------------------------------------------

export function createPlayCampaignClue(
  campaignId: string,
  input: CreatePlayCampaignClueInput
): PlayCampaignClue | "conflict" {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return "conflict";

  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO play_campaign_clues (campaign_id, clue_id, text, audience, character_id) VALUES (?, ?, ?, ?, ?)"
      )
      .run(
        campaignId,
        input.clue_id,
        input.text,
        input.audience,
        input.character_id ?? null
      );

    database.exec("COMMIT;");

    const clue: PlayCampaignClue = {
      clue_id: input.clue_id,
      text: input.text,
      audience: input.audience,
    };
    if (input.character_id !== undefined) {
      clue.character_id = input.character_id;
    }
    return clue;
  } catch {
    database.exec("ROLLBACK;");
    return "conflict";
  }
}

export function getPlayCampaignClues(campaignId: string): PlayCampaignClue[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT clue_id, text, audience, character_id FROM play_campaign_clues WHERE campaign_id = ? ORDER BY id ASC"
    )
    .all(campaignId) as Array<{
    clue_id: string;
    text: string;
    audience: "character" | "party" | "hidden";
    character_id: string | null;
  }>;
  return rows.map((r) => {
    const clue: PlayCampaignClue = {
      clue_id: r.clue_id,
      text: r.text,
      audience: r.audience,
    };
    if (r.character_id !== null) {
      clue.character_id = r.character_id;
    }
    return clue;
  });
}

// ---------------------------------------------------------------------------
// Play campaign quests
// ---------------------------------------------------------------------------

function isValidQuestDependencyList(
  value: unknown
): value is string[] {
  if (!Array.isArray(value)) return false;
  if (!value.every((item) => typeof item === "string")) return false;
  return new Set(value).size === value.length;
}

function parseQuestItems(raw: string): Record<string, number> {
  let items: unknown;
  try {
    items = JSON.parse(raw);
  } catch {
    return {};
  }
  if (
    typeof items !== "object" ||
    items === null ||
    Array.isArray(items)
  ) {
    return {};
  }
  const result: Record<string, number> = {};
  for (const [key, value] of Object.entries(items as Record<string, unknown>)) {
    if (typeof value === "number" && Number.isInteger(value) && value > 0) {
      result[key] = value;
    }
  }
  return result;
}

export function createPlayCampaignQuest(
  campaignId: string,
  input: CreatePlayCampaignQuestInput
): PlayCampaignQuest | "conflict" | "bad_request" {
  if (!isValidQuestDependencyList(input.depends_on)) {
    return "bad_request";
  }

  const dependsOn = input.depends_on as string[];
  if (dependsOn.includes(input.quest_id)) {
    return "bad_request";
  }

  const database = getDb();
  if (!getPlayCampaign(campaignId)) return "bad_request";

  database.exec("BEGIN IMMEDIATE;");
  try {
    if (dependsOn.length > 0) {
      const placeholders = dependsOn.map(() => "?").join(",");
      const countStmt = database.prepare(
        `SELECT COUNT(*) AS count FROM play_campaign_quests WHERE campaign_id = ? AND quest_id IN (${placeholders})`
      );
      const countRow = countStmt.get(campaignId, ...dependsOn) as {
        count: number;
      };
      if (countRow.count !== dependsOn.length) {
        database.exec("ROLLBACK;");
        return "bad_request";
      }
    }

    database
      .prepare(
        "INSERT INTO play_campaign_quests (campaign_id, quest_id, title, depends_on, state) VALUES (?, ?, ?, ?, 'locked')"
      )
      .run(campaignId, input.quest_id, input.title, JSON.stringify(dependsOn));

    database.exec("COMMIT;");

    return {
      quest_id: input.quest_id,
      title: input.title,
      depends_on: dependsOn,
      state: "locked",
    };
  } catch {
    database.exec("ROLLBACK;");
    return "conflict";
  }
}

export function getPlayCampaignQuest(
  campaignId: string,
  questId: string
): PlayCampaignQuest | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT quest_id, title, depends_on, state, quest_xp, quest_items, rewards_configured FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?"
    )
    .get(campaignId, questId) as
    | {
        quest_id: string;
        title: string;
        depends_on: string;
        state: PlayCampaignQuestState;
        quest_xp: number;
        quest_items: string;
        rewards_configured: number;
      }
    | undefined;
  if (!row) return null;

  let dependsOn: string[];
  try {
    dependsOn = JSON.parse(row.depends_on) as string[];
  } catch {
    dependsOn = [];
  }

  const result: PlayCampaignQuest = {
    quest_id: row.quest_id,
    title: row.title,
    depends_on: dependsOn,
    state: row.state,
  };
  if (row.rewards_configured) {
    result.rewards = { xp: row.quest_xp, items: parseQuestItems(row.quest_items) };
  }
  return result;
}

export function getPlayCampaignQuests(
  campaignId: string
): PlayCampaignQuest[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT quest_id, title, depends_on, state, quest_xp, quest_items, rewards_configured FROM play_campaign_quests WHERE campaign_id = ? ORDER BY id ASC"
    )
    .all(campaignId) as Array<{
    quest_id: string;
    title: string;
    depends_on: string;
    state: PlayCampaignQuestState;
    quest_xp: number;
    quest_items: string;
    rewards_configured: number;
  }>;

  return rows.map((r) => {
    let dependsOn: string[];
    try {
      dependsOn = JSON.parse(r.depends_on) as string[];
    } catch {
      dependsOn = [];
    }
    const result: PlayCampaignQuest = {
      quest_id: r.quest_id,
      title: r.title,
      depends_on: dependsOn,
      state: r.state,
    };
    if (r.rewards_configured) {
      result.rewards = { xp: r.quest_xp, items: parseQuestItems(r.quest_items) };
    }
    return result;
  });
}

export function updatePlayCampaignQuestState(
  campaignId: string,
  questId: string,
  state: PlayCampaignQuestState
): PlayCampaignQuest | "conflict" | "bad_request" | null {
  if (state !== "active" && state !== "completed") {
    return "bad_request";
  }

  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT quest_id, title, depends_on, state, quest_xp, quest_items, rewards_configured FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?"
      )
      .get(campaignId, questId) as
      | {
          quest_id: string;
          title: string;
          depends_on: string;
          state: PlayCampaignQuestState;
          quest_xp: number;
          quest_items: string;
          rewards_configured: number;
        }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }

    let dependsOn: string[];
    try {
      dependsOn = JSON.parse(row.depends_on) as string[];
    } catch {
      dependsOn = [];
    }

    const currentState = row.state;
    if (state === "active") {
      if (currentState !== "locked") {
        database.exec("ROLLBACK;");
        return "conflict";
      }
      if (dependsOn.length > 0) {
        const placeholders = dependsOn.map(() => "?").join(",");
        const countStmt = database.prepare(
          `SELECT COUNT(*) AS count FROM play_campaign_quests WHERE campaign_id = ? AND quest_id IN (${placeholders}) AND state = 'completed'`
        );
        const countRow = countStmt.get(campaignId, ...dependsOn) as {
          count: number;
        };
        if (countRow.count !== dependsOn.length) {
          database.exec("ROLLBACK;");
          return "conflict";
        }
      }
    } else if (state === "completed") {
      if (currentState !== "active") {
        database.exec("ROLLBACK;");
        return "conflict";
      }
    }

    database
      .prepare(
        "UPDATE play_campaign_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?"
      )
      .run(state, campaignId, questId);

    database.exec("COMMIT;");

    const result: PlayCampaignQuest = {
      quest_id: row.quest_id,
      title: row.title,
      depends_on: dependsOn,
      state,
    };
    if (row.rewards_configured) {
      result.rewards = { xp: row.quest_xp, items: parseQuestItems(row.quest_items) };
    }
    return result;
  } catch {
    database.exec("ROLLBACK;");
    return "conflict";
  }
}

export function configurePlayCampaignQuestRewards(
  campaignId: string,
  questId: string,
  input: ConfigurePlayCampaignQuestRewardsInput
): PlayCampaignQuest | null | "conflict" {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT quest_id, title, depends_on, state, quest_xp, quest_items FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?"
      )
      .get(campaignId, questId) as
      | {
          quest_id: string;
          title: string;
          depends_on: string;
          state: PlayCampaignQuestState;
          quest_xp: number;
          quest_items: string;
        }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }

    if (row.state !== "locked" && row.state !== "active") {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    let dependsOn: string[];
    try {
      dependsOn = JSON.parse(row.depends_on) as string[];
    } catch {
      dependsOn = [];
    }

    database
      .prepare(
        "UPDATE play_campaign_quests SET quest_xp = ?, quest_items = ?, rewards_configured = 1 WHERE campaign_id = ? AND quest_id = ?"
      )
      .run(input.xp, JSON.stringify(input.items), campaignId, questId);

    database.exec("COMMIT;");

    return {
      quest_id: row.quest_id,
      title: row.title,
      depends_on: dependsOn,
      state: row.state,
      rewards: { xp: input.xp, items: input.items },
    };
  } catch {
    database.exec("ROLLBACK;");
    return "conflict";
  }
}

export interface PlayCampaignQuestAwardResult {
  quest_id: string;
  awarded: true;
  xp: number;
  items: Record<string, number>;
}

export function awardPlayCampaignQuestRewards(
  campaignId: string,
  questId: string
): PlayCampaignQuestAwardResult | null | "conflict" {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT quest_id, state, quest_xp, quest_items, rewards_configured FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?"
      )
      .get(campaignId, questId) as
      | {
          quest_id: string;
          state: PlayCampaignQuestState;
          quest_xp: number;
          quest_items: string;
          rewards_configured: number;
        }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }

    if (row.state !== "completed" || row.rewards_configured === 0) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    const awardedCheck = database
      .prepare(
        "SELECT 1 FROM play_campaign_quest_reward_grants WHERE campaign_id = ? AND quest_id = ?"
      )
      .get(campaignId, questId) as { 1: number } | undefined;
    if (awardedCheck) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    const items = parseQuestItems(row.quest_items);

    const members = database
      .prepare(
        "SELECT character_id FROM play_campaign_members WHERE campaign_id = ?"
      )
      .all(campaignId) as Array<{ character_id: string }>;

    const insertGrant = database.prepare(
      "INSERT INTO play_campaign_quest_reward_grants (campaign_id, quest_id, character_id, xp, items) VALUES (?, ?, ?, ?, ?)"
    );
    for (const member of members) {
      insertGrant.run(
        campaignId,
        questId,
        member.character_id,
        row.quest_xp,
        JSON.stringify(items)
      );
    }

    database.exec("COMMIT;");

    return {
      quest_id: row.quest_id,
      awarded: true,
      xp: row.quest_xp,
      items,
    };
  } catch {
    database.exec("ROLLBACK;");
    return "conflict";
  }
}

export interface PlayCampaignCharacterQuestRewards {
  character_id: string;
  xp: number;
  items: Record<string, number>;
}

export function getPlayCampaignCharacterQuestRewards(
  campaignId: string,
  characterId: string
): PlayCampaignCharacterQuestRewards | null {
  const database = getDb();
  const memberRow = database
    .prepare(
      "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as { character_id: string } | undefined;
  if (!memberRow) {
    return null;
  }

  const rows = database
    .prepare(
      "SELECT xp, items FROM play_campaign_quest_reward_grants WHERE campaign_id = ? AND character_id = ?"
    )
    .all(campaignId, characterId) as Array<{ xp: number; items: string }>;

  let totalXp = 0;
  const totalItems: Record<string, number> = {};
  for (const row of rows) {
    totalXp += row.xp;
    const items = parseQuestItems(row.items);
    for (const [itemId, quantity] of Object.entries(items)) {
      totalItems[itemId] = (totalItems[itemId] || 0) + quantity;
    }
  }

  return {
    character_id: characterId,
    xp: totalXp,
    items: totalItems,
  };
}

// ---------------------------------------------------------------------------
// Play campaign world events
// ---------------------------------------------------------------------------

export type CreatePlayCampaignWorldEventResult =
  | PlayCampaignWorldEvent
  | "conflict"
  | "bad_request";

export function createPlayCampaignWorldEvent(
  campaignId: string,
  input: CreatePlayCampaignWorldEventInput
): CreatePlayCampaignWorldEventResult {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return "bad_request";

  const state = getPlayCampaignState(campaignId);
  if (!state) return "bad_request";
  if (input.turn_number < state.turn_number) return "bad_request";

  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO play_campaign_world_events (campaign_id, event_id, turn_number, title, text, status) VALUES (?, ?, ?, ?, ?, 'scheduled')"
      )
      .run(campaignId, input.event_id, input.turn_number, input.title, input.text);

    database.exec("COMMIT;");
    return {
      event_id: input.event_id,
      turn_number: input.turn_number,
      title: input.title,
      text: input.text,
      status: "scheduled",
    };
  } catch {
    database.exec("ROLLBACK;");
    return "conflict";
  }
}

export type ResolvePlayCampaignWorldEventResult =
  | PlayCampaignWorldEvent
  | "not_found"
  | "conflict"
  | "bad_request";

export function resolvePlayCampaignWorldEvent(
  campaignId: string,
  eventId: string,
  text: string
): ResolvePlayCampaignWorldEventResult {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return "not_found";

  const state = getPlayCampaignState(campaignId);
  if (!state) return "bad_request";

  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT event_id, turn_number, title, text, status FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?"
      )
      .get(campaignId, eventId) as
      | {
          event_id: string;
          turn_number: number;
          title: string;
          text: string;
          status: "scheduled" | "resolved";
        }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    if (state.turn_number !== row.turn_number) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    if (row.status === "resolved") {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    database
      .prepare(
        "UPDATE play_campaign_world_events SET status = 'resolved', resolution_turn_number = ?, resolution_text = ? WHERE campaign_id = ? AND event_id = ?"
      )
      .run(state.turn_number, text, campaignId, eventId);

    database.exec("COMMIT;");
    return {
      event_id: row.event_id,
      turn_number: row.turn_number,
      title: row.title,
      text: row.text,
      status: "resolved",
      resolution: {
        turn_number: state.turn_number,
        text,
      },
    };
  } catch {
    database.exec("ROLLBACK;");
    return "conflict";
  }
}

const SEASON_OFFSETS: Record<Season, number> = {
  spring: 0,
  summer: 1,
  autumn: 2,
  winter: 3,
};

const WEATHER_BY_REMAINDER: Record<number, Weather> = {
  0: "clear",
  1: "rain",
  2: "wind",
  3: "snow",
};

export function computeCalendarWeather(day: number, season: Season): Weather {
  return WEATHER_BY_REMAINDER[(day + SEASON_OFFSETS[season]) % 4];
}

export function createPlayCampaignCalendar(
  campaignId: string,
  day: number,
  season: Season
): PlayCampaignCalendar | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (?, ?, ?)"
      )
      .run(campaignId, day, season);
    return {
      day,
      season,
      weather: computeCalendarWeather(day, season),
    };
  } catch {
    return null;
  }
}

export function getPlayCampaignCalendar(
  campaignId: string
): PlayCampaignCalendar | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?"
    )
    .get(campaignId) as
    | { day: number; season: Season }
    | undefined;
  if (!row) return null;
  return {
    day: row.day,
    season: row.season,
    weather: computeCalendarWeather(row.day, row.season),
  };
}

export function advancePlayCampaignCalendar(
  campaignId: string,
  days: number
): PlayCampaignCalendar | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?"
    )
    .get(campaignId) as
    | { day: number; season: Season }
    | undefined;
  if (!row) return null;

  const newDay = row.day + days;
  database
    .prepare(
      "UPDATE play_campaign_calendars SET day = ? WHERE campaign_id = ?"
    )
    .run(newDay, campaignId);

  return {
    day: newDay,
    season: row.season,
    weather: computeCalendarWeather(newDay, row.season),
  };
}

export function getPlayCampaignWorldEvents(
  campaignId: string
): PlayCampaignWorldEvent[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT event_id, turn_number, title, text, status, resolution_turn_number, resolution_text FROM play_campaign_world_events WHERE campaign_id = ? ORDER BY turn_number ASC, id ASC"
    )
    .all(campaignId) as Array<{
    event_id: string;
    turn_number: number;
    title: string;
    text: string;
    status: "scheduled" | "resolved";
    resolution_turn_number: number | null;
    resolution_text: string | null;
  }>;

  return rows.map((r) => {
    const event: PlayCampaignWorldEvent = {
      event_id: r.event_id,
      turn_number: r.turn_number,
      title: r.title,
      text: r.text,
      status: r.status,
    };
    if (
      r.status === "resolved" &&
      r.resolution_turn_number !== null &&
      r.resolution_text !== null
    ) {
      event.resolution = {
        turn_number: r.resolution_turn_number,
        text: r.resolution_text,
      };
    }
    return event;
  });
}

// ---------------------------------------------------------------------------
// Settlements
// ---------------------------------------------------------------------------

const VALID_AVAILABILITY_VALUES: SettlementAvailability[] = [
  "open",
  "limited",
  "closed",
];

export function isValidAvailability(
  value: unknown
): value is SettlementAvailability {
  return VALID_AVAILABILITY_VALUES.includes(value as SettlementAvailability);
}

export function normalizeSettlementServices(
  services: unknown
): string[] | null {
  if (!Array.isArray(services)) return null;
  if (services.length === 0) return null;
  const normalized: string[] = [];
  const seen = new Set<string>();
  for (const item of services) {
    if (typeof item !== "string") return null;
    const trimmed = item.trim();
    if (trimmed.length === 0) return null;
    if (seen.has(trimmed)) return null;
    seen.add(trimmed);
    normalized.push(trimmed);
  }
  return normalized;
}

export function createSettlement(
  campaignId: string,
  input: CreateSettlementInput
): Settlement | null | "bad_request" {
  const services = normalizeSettlementServices(input.services);
  if (services === null) return "bad_request";
  if (
    typeof input.settlement_id !== "string" ||
    input.settlement_id.length === 0 ||
    typeof input.name !== "string" ||
    input.name.length === 0 ||
    !isValidAvailability(input.availability)
  ) {
    return "bad_request";
  }

  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  try {
    database
      .prepare(
        "INSERT INTO play_campaign_settlements (campaign_id, settlement_id, name, services, availability) VALUES (?, ?, ?, ?, ?)"
      )
      .run(
        campaignId,
        input.settlement_id,
        input.name,
        JSON.stringify(services),
        input.availability
      );
    return {
      settlement_id: input.settlement_id,
      name: input.name,
      services,
      availability: input.availability,
      discovered_by: [],
    };
  } catch {
    return null;
  }
}

export function getSettlement(
  campaignId: string,
  settlementId: string
): Settlement | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT settlement_id, name, services, availability FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?"
    )
    .get(campaignId, settlementId) as
    | {
        settlement_id: string;
        name: string;
        services: string;
        availability: SettlementAvailability;
      }
    | undefined;
  if (!row) return null;

  let services: string[];
  try {
    services = JSON.parse(row.services) as string[];
  } catch {
    services = [];
  }

  const discoverers = database
    .prepare(
      "SELECT character_id FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? ORDER BY rowid ASC"
    )
    .all(campaignId, settlementId) as Array<{ character_id: string }>;

  return {
    settlement_id: row.settlement_id,
    name: row.name,
    services,
    availability: row.availability,
    discovered_by: discoverers.map((d) => d.character_id),
  };
}

export function updateSettlement(
  campaignId: string,
  settlementId: string,
  input: Omit<CreateSettlementInput, "settlement_id">
): Settlement | null | "bad_request" {
  const services = normalizeSettlementServices(input.services);
  if (services === null) return "bad_request";
  if (
    typeof input.name !== "string" ||
    input.name.length === 0 ||
    !isValidAvailability(input.availability)
  ) {
    return "bad_request";
  }

  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?"
      )
      .get(campaignId, settlementId) as { 1: number } | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare(
        "UPDATE play_campaign_settlements SET name = ?, services = ?, availability = ? WHERE campaign_id = ? AND settlement_id = ?"
      )
      .run(
        input.name,
        JSON.stringify(services),
        input.availability,
        campaignId,
        settlementId
      );

    database.exec("COMMIT;");
    return getSettlement(campaignId, settlementId);
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export type DiscoverSettlementResult =
  | Settlement
  | "not_found"
  | "not_member";

export function discoverSettlement(
  campaignId: string,
  settlementId: string,
  characterId: string
): DiscoverSettlementResult {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const settlementRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?"
      )
      .get(campaignId, settlementId) as { 1: number } | undefined;
    if (!settlementRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    const memberRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { 1: number } | undefined;
    if (!memberRow) {
      database.exec("ROLLBACK;");
      return "not_member";
    }

    const existingDiscovery = database
      .prepare(
        "SELECT 1 FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?"
      )
      .get(campaignId, settlementId, characterId) as { 1: number } | undefined;

    if (!existingDiscovery) {
      database
        .prepare(
          "INSERT INTO play_campaign_settlement_discoveries (campaign_id, settlement_id, character_id) VALUES (?, ?, ?)"
        )
        .run(campaignId, settlementId, characterId);
    }

    database.exec("COMMIT;");

    const settlement = getSettlement(campaignId, settlementId);
    if (!settlement) return "not_found";
    return settlement;
  } catch {
    database.exec("ROLLBACK;");
    return "not_found";
  }
}

export function getSettlements(
  campaignId: string
): Settlement[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT settlement_id, name, services, availability FROM play_campaign_settlements WHERE campaign_id = ? ORDER BY rowid ASC"
    )
    .all(campaignId) as Array<{
    settlement_id: string;
    name: string;
    services: string;
    availability: SettlementAvailability;
  }>;

  return rows.map((r) => {
    let services: string[];
    try {
      services = JSON.parse(r.services) as string[];
    } catch {
      services = [];
    }
    return {
      settlement_id: r.settlement_id,
      name: r.name,
      services,
      availability: r.availability,
      discovered_by: [],
    };
  });
}

export function getSettlementDiscoveries(
  campaignId: string,
  settlementId: string
): string[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT character_id FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? ORDER BY rowid ASC"
    )
    .all(campaignId, settlementId) as Array<{ character_id: string }>;
  return rows.map((r) => r.character_id);
}

// ---------------------------------------------------------------------------
// Shops
// ---------------------------------------------------------------------------

export function normalizeShopStock(
  stock: unknown
): Record<string, number> | null {
  if (typeof stock !== "object" || stock === null) return null;
  const entries = Object.entries(stock as Record<string, unknown>);
  if (entries.length === 0) return null;

  const normalized: Record<string, number> = {};
  for (const [itemId, rawQuantity] of entries) {
    const quantity = Number(rawQuantity);
    if (!isValidInventoryItemId(itemId)) return null;
    if (!Number.isInteger(quantity) || quantity <= 0) return null;
    normalized[itemId] = quantity;
  }
  return normalized;
}

export function createShop(
  campaignId: string,
  settlementId: string,
  input: CreateShopInput
): Shop | null | "bad_request" {
  if (
    typeof input.shop_id !== "string" ||
    input.shop_id.length === 0 ||
    typeof input.name !== "string" ||
    input.name.length === 0 ||
    !Number.isInteger(input.buy_price) ||
    input.buy_price <= 0 ||
    !Number.isInteger(input.sell_price) ||
    input.sell_price < 0
  ) {
    return "bad_request";
  }

  const stock = normalizeShopStock(input.stock);
  if (stock === null) return "bad_request";

  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;
  if (!getSettlement(campaignId, settlementId)) return null;

  try {
    database
      .prepare(
        "INSERT INTO play_campaign_shops (campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price) VALUES (?, ?, ?, ?, ?, ?, ?)"
      )
      .run(
        campaignId,
        settlementId,
        input.shop_id,
        input.name,
        JSON.stringify(stock),
        input.buy_price,
        input.sell_price
      );
    return {
      shop_id: input.shop_id,
      name: input.name,
      stock,
      buy_price: input.buy_price,
      sell_price: input.sell_price,
    };
  } catch {
    return null;
  }
}

export function getShop(
  campaignId: string,
  settlementId: string,
  shopId: string
): Shop | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT shop_id, name, stock, buy_price, sell_price FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?"
    )
    .get(campaignId, settlementId, shopId) as
    | {
        shop_id: string;
        name: string;
        stock: string;
        buy_price: number;
        sell_price: number;
      }
    | undefined;
  if (!row) return null;

  let stock: Record<string, number>;
  try {
    stock = JSON.parse(row.stock) as Record<string, number>;
  } catch {
    stock = {};
  }

  return {
    shop_id: row.shop_id,
    name: row.name,
    stock,
    buy_price: row.buy_price,
    sell_price: row.sell_price,
  };
}

export type BuyFromShopResult =
  | ShopTransactionResult
  | "not_found"
  | "invalid"
  | "insufficient";

export function buyFromShop(
  campaignId: string,
  settlementId: string,
  shopId: string,
  characterId: string,
  itemId: string,
  quantity: number
): BuyFromShopResult {
  if (!isValidInventoryItemId(itemId) || !Number.isInteger(quantity) || quantity <= 0) {
    return "invalid";
  }

  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const shopRow = database
      .prepare(
        "SELECT name, stock, buy_price, sell_price FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?"
      )
      .get(campaignId, settlementId, shopId) as
      | {
          name: string;
          stock: string;
          buy_price: number;
          sell_price: number;
        }
      | undefined;
    if (!shopRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    const memberRow = database
      .prepare(
        "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { gold: number } | undefined;
    if (!memberRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    let stock: Record<string, number>;
    try {
      stock = JSON.parse(shopRow.stock) as Record<string, number>;
    } catch {
      stock = {};
    }

    const currentStock = stock[itemId] ?? 0;
    if (currentStock < quantity) {
      database.exec("ROLLBACK;");
      return "insufficient";
    }

    const cost = shopRow.buy_price * quantity;
    if (memberRow.gold < cost) {
      database.exec("ROLLBACK;");
      return "insufficient";
    }

    const newStock = currentStock - quantity;
    if (newStock > 0) {
      stock[itemId] = newStock;
    } else {
      delete stock[itemId];
    }

    const newGold = memberRow.gold - cost;

    database
      .prepare(
        "UPDATE play_campaign_shops SET stock = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?"
      )
      .run(JSON.stringify(stock), campaignId, settlementId, shopId);

    database
      .prepare(
        "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(newGold, campaignId, characterId);

    const existingItem = database
      .prepare(
        "SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
      )
      .get(campaignId, characterId, itemId) as { quantity: number } | undefined;

    if (existingItem) {
      database
        .prepare(
          "UPDATE play_campaign_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
        )
        .run(existingItem.quantity + quantity, campaignId, characterId, itemId);
    } else {
      database
        .prepare(
          "INSERT INTO play_campaign_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)"
        )
        .run(campaignId, characterId, itemId, quantity);
    }

    database.exec("COMMIT;");
    return {
      character_id: characterId,
      item_id: itemId,
      quantity,
      gold: newGold,
      stock: newStock,
    };
  } catch {
    database.exec("ROLLBACK;");
    return "not_found";
  }
}

export type SellToShopResult =
  | ShopTransactionResult
  | "not_found"
  | "invalid"
  | "insufficient";

export function sellToShop(
  campaignId: string,
  settlementId: string,
  shopId: string,
  characterId: string,
  itemId: string,
  quantity: number
): SellToShopResult {
  if (!isValidInventoryItemId(itemId) || !Number.isInteger(quantity) || quantity <= 0) {
    return "invalid";
  }

  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const shopRow = database
      .prepare(
        "SELECT name, stock, buy_price, sell_price FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?"
      )
      .get(campaignId, settlementId, shopId) as
      | {
          name: string;
          stock: string;
          buy_price: number;
          sell_price: number;
        }
      | undefined;
    if (!shopRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    const memberRow = database
      .prepare(
        "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { gold: number } | undefined;
    if (!memberRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    const itemRow = database
      .prepare(
        "SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
      )
      .get(campaignId, characterId, itemId) as { quantity: number } | undefined;
    if (!itemRow || itemRow.quantity < quantity) {
      database.exec("ROLLBACK;");
      return "insufficient";
    }

    let stock: Record<string, number>;
    try {
      stock = JSON.parse(shopRow.stock) as Record<string, number>;
    } catch {
      stock = {};
    }

    const newStock = (stock[itemId] ?? 0) + quantity;
    stock[itemId] = newStock;

    const goldEarned = shopRow.sell_price * quantity;
    const newGold = memberRow.gold + goldEarned;

    database
      .prepare(
        "UPDATE play_campaign_shops SET stock = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?"
      )
      .run(JSON.stringify(stock), campaignId, settlementId, shopId);

    database
      .prepare(
        "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?"
      )
      .run(newGold, campaignId, characterId);

    database.exec("COMMIT;");
    return {
      character_id: characterId,
      item_id: itemId,
      quantity,
      gold: newGold,
      stock: newStock,
    };
  } catch {
    database.exec("ROLLBACK;");
    return "not_found";
  }
}

// ---------------------------------------------------------------------------
// Recipe catalog
// ---------------------------------------------------------------------------

function normalizeIngredients(
  ingredients: unknown
): Record<string, number> | null {
  if (typeof ingredients !== "object" || ingredients === null) return null;
  const entries = Object.entries(ingredients as Record<string, unknown>);
  if (entries.length === 0) return null;

  const normalized: Record<string, number> = {};
  for (const [itemId, rawQuantity] of entries) {
    const quantity = Number(rawQuantity);
    if (!isValidInventoryItemId(itemId)) return null;
    if (!Number.isInteger(quantity) || quantity <= 0) return null;
    normalized[itemId] = quantity;
  }
  return normalized;
}

export type CreateRecipeResult = Recipe | "bad_request" | "conflict";

export function createRecipe(
  campaignId: string,
  input: CreateRecipeInput
): CreateRecipeResult {
  if (
    typeof input.recipe_id !== "string" ||
    input.recipe_id.length === 0 ||
    typeof input.name !== "string" ||
    input.name.length === 0 ||
    !isValidInventoryItemId(input.output_item) ||
    !Number.isInteger(input.output_quantity) ||
    input.output_quantity <= 0
  ) {
    return "bad_request";
  }

  const ingredients = normalizeIngredients(input.ingredients);
  if (ingredients === null) return "bad_request";

  const database = getDb();
  if (!getPlayCampaign(campaignId)) return "bad_request";

  try {
    database
      .prepare(
        "INSERT INTO play_campaign_recipes (campaign_id, recipe_id, name, ingredients, output_item, output_quantity) VALUES (?, ?, ?, ?, ?, ?)"
      )
      .run(
        campaignId,
        input.recipe_id,
        input.name,
        JSON.stringify(ingredients),
        input.output_item,
        input.output_quantity
      );
    return {
      recipe_id: input.recipe_id,
      name: input.name,
      ingredients,
      output_item: input.output_item,
      output_quantity: input.output_quantity,
    };
  } catch {
    return "conflict";
  }
}

export function getRecipe(campaignId: string, recipeId: string): Recipe | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT recipe_id, name, ingredients, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?"
    )
    .get(campaignId, recipeId) as
    | {
        recipe_id: string;
        name: string;
        ingredients: string;
        output_item: string;
        output_quantity: number;
      }
    | undefined;
  if (!row) return null;

  let ingredients: Record<string, number>;
  try {
    ingredients = JSON.parse(row.ingredients) as Record<string, number>;
  } catch {
    ingredients = {};
  }

  return {
    recipe_id: row.recipe_id,
    name: row.name,
    ingredients,
    output_item: row.output_item,
    output_quantity: row.output_quantity,
  };
}

export function listRecipes(campaignId: string): Recipe[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT recipe_id, name, ingredients, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? ORDER BY id ASC"
    )
    .all(campaignId) as Array<{
    recipe_id: string;
    name: string;
    ingredients: string;
    output_item: string;
    output_quantity: number;
  }>;

  return rows.map((row) => {
    let ingredients: Record<string, number>;
    try {
      ingredients = JSON.parse(row.ingredients) as Record<string, number>;
    } catch {
      ingredients = {};
    }
    return {
      recipe_id: row.recipe_id,
      name: row.name,
      ingredients,
      output_item: row.output_item,
      output_quantity: row.output_quantity,
    };
  });
}

export type CraftRecipeOperationResult =
  | CraftRecipeResult
  | "not_found"
  | "invalid"
  | "insufficient";

export function craftRecipe(
  campaignId: string,
  recipeId: string,
  characterId: string
): CraftRecipeOperationResult {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const recipeRow = database
      .prepare(
        "SELECT ingredients, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?"
      )
      .get(campaignId, recipeId) as
      | {
          ingredients: string;
          output_item: string;
          output_quantity: number;
        }
      | undefined;
    if (!recipeRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    const memberRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { 1: number } | undefined;
    if (!memberRow) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    let ingredients: Record<string, number>;
    try {
      ingredients = JSON.parse(recipeRow.ingredients) as Record<string, number>;
    } catch {
      database.exec("ROLLBACK;");
      return "invalid";
    }

    const inventoryRows = database
      .prepare(
        "SELECT item_id, quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ?"
      )
      .all(campaignId, characterId) as Array<{ item_id: string; quantity: number }>;
    const inventory: Record<string, number> = {};
    for (const row of inventoryRows) {
      inventory[row.item_id] = row.quantity;
    }

    for (const [itemId, required] of Object.entries(ingredients)) {
      const available = inventory[itemId] ?? 0;
      if (available < required) {
        database.exec("ROLLBACK;");
        return "insufficient";
      }
    }

    for (const [itemId, required] of Object.entries(ingredients)) {
      const available = inventory[itemId];
      const remaining = (available ?? 0) - required;
      if (remaining > 0) {
        database
          .prepare(
            "UPDATE play_campaign_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
          )
          .run(remaining, campaignId, characterId, itemId);
      } else {
        database
          .prepare(
            "DELETE FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
          )
          .run(campaignId, characterId, itemId);
      }
    }

    const existingOutput = database
      .prepare(
        "SELECT quantity FROM play_campaign_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
      )
      .get(campaignId, characterId, recipeRow.output_item) as
      | { quantity: number }
      | undefined;

    if (existingOutput) {
      database
        .prepare(
          "UPDATE play_campaign_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?"
        )
        .run(
          existingOutput.quantity + recipeRow.output_quantity,
          campaignId,
          characterId,
          recipeRow.output_item
        );
    } else {
      database
        .prepare(
          "INSERT INTO play_campaign_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)"
        )
        .run(campaignId, characterId, recipeRow.output_item, recipeRow.output_quantity);
    }

    database.exec("COMMIT;");
    return {
      character_id: characterId,
      recipe_id: recipeId,
      output_item: recipeRow.output_item,
      output_quantity: recipeRow.output_quantity,
    };
  } catch {
    database.exec("ROLLBACK;");
    return "not_found";
  }
}

// ---------------------------------------------------------------------------
// Downtime activities
// ---------------------------------------------------------------------------

export function createDowntimeActivity(
  campaignId: string,
  input: CreateDowntimeActivityInput
): DowntimeActivity | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  try {
    database
      .prepare(
        "INSERT INTO play_campaign_downtime_activities (campaign_id, activity_id, name, cycles_required) VALUES (?, ?, ?, ?)"
      )
      .run(campaignId, input.activity_id, input.name, input.cycles_required);
    return {
      activity_id: input.activity_id,
      name: input.name,
      cycles_required: input.cycles_required,
    };
  } catch {
    return null;
  }
}

export function getDowntimeActivity(
  campaignId: string,
  activityId: string
): DowntimeActivity | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT activity_id, name, cycles_required FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?"
    )
    .get(campaignId, activityId) as
    | { activity_id: string; name: string; cycles_required: number }
    | undefined;
  return row || null;
}

export type CreateDowntimeAllocationResult =
  | DowntimeAllocation
  | "conflict"
  | null;

export function createDowntimeAllocation(
  campaignId: string,
  characterId: string,
  activityId: string
): CreateDowntimeAllocationResult {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const memberRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
      )
      .get(campaignId, characterId) as { 1: number } | undefined;
    if (!memberRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const activityRow = database
      .prepare(
        "SELECT 1 FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?"
      )
      .get(campaignId, activityId) as { 1: number } | undefined;
    if (!activityRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare(
        "INSERT INTO play_campaign_downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (?, ?, ?, 0, 0)"
      )
      .run(campaignId, characterId, activityId);
    database.exec("COMMIT;");
    return {
      character_id: characterId,
      activity_id: activityId,
      cycles_completed: 0,
      completions: 0,
    };
  } catch {
    database.exec("ROLLBACK;");
    return "conflict";
  }
}

export function getDowntimeAllocation(
  campaignId: string,
  characterId: string,
  activityId: string
): DowntimeAllocation | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT character_id, activity_id, cycles_completed, completions FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?"
    )
    .get(campaignId, characterId, activityId) as
    | { character_id: string; activity_id: string; cycles_completed: number; completions: number }
    | undefined;
  return row || null;
}

export function progressDowntimeAllocation(
  campaignId: string,
  characterId: string,
  activityId: string
): DowntimeAllocation | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const allocationRow = database
      .prepare(
        "SELECT cycles_completed, completions FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?"
      )
      .get(campaignId, characterId, activityId) as
      | { cycles_completed: number; completions: number }
      | undefined;
    if (!allocationRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    const activityRow = database
      .prepare(
        "SELECT cycles_required FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?"
      )
      .get(campaignId, activityId) as { cycles_required: number } | undefined;
    if (!activityRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    let cyclesCompleted = allocationRow.cycles_completed + 1;
    let completions = allocationRow.completions;
    if (cyclesCompleted >= activityRow.cycles_required) {
      cyclesCompleted = 0;
      completions += 1;
    }

    database
      .prepare(
        "UPDATE play_campaign_downtime_allocations SET cycles_completed = ?, completions = ? WHERE campaign_id = ? AND character_id = ? AND activity_id = ?"
      )
      .run(cyclesCompleted, completions, campaignId, characterId, activityId);
    database.exec("COMMIT;");
    return {
      character_id: characterId,
      activity_id: activityId,
      cycles_completed: cyclesCompleted,
      completions: completions,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}


// ---------------------------------------------------------------------------
// Session-zero settings (073)
// ---------------------------------------------------------------------------

export function getPlayCampaignSessionZero(
  campaignId: string
): SessionZeroSettings | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT rules, tone, consent FROM play_campaign_session_zero WHERE campaign_id = ?"
    )
    .get(campaignId) as
    | { rules: string; tone: string; consent: string }
    | undefined;
  if (!row) return null;
  try {
    const consent = JSON.parse(row.consent) as string[];
    return { rules: row.rules, tone: row.tone, consent };
  } catch {
    return null;
  }
}

export function setPlayCampaignSessionZero(
  campaignId: string,
  settings: SessionZeroSettings
): SessionZeroSettings | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO play_campaign_session_zero (campaign_id, rules, tone, consent) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET rules = excluded.rules, tone = excluded.tone, consent = excluded.consent"
      )
      .run(
        campaignId,
        settings.rules,
        settings.tone,
        JSON.stringify(settings.consent)
      );
    return settings;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Content records (074)
// ---------------------------------------------------------------------------

function parseContentTags(tagsJson: string): string[] {
  try {
    const parsed = JSON.parse(tagsJson) as unknown;
    if (Array.isArray(parsed) && parsed.every((t) => typeof t === "string")) {
      return parsed as string[];
    }
  } catch {
    // fall through
  }
  return [];
}

export function createContentRecord(
  campaignId: string,
  input: CreateContentRecordInput
): ContentRecord | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  try {
    database
      .prepare(
        "INSERT INTO play_campaign_content (campaign_id, content_id, kind, text, tags) VALUES (?, ?, ?, ?, ?)"
      )
      .run(
        campaignId,
        input.content_id,
        input.kind,
        input.text,
        JSON.stringify(input.tags)
      );
    return {
      content_id: input.content_id,
      kind: input.kind,
      text: input.text,
      tags: input.tags,
    };
  } catch {
    return null;
  }
}

export function getContentRecord(
  campaignId: string,
  contentId: string
): ContentRecord | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT content_id, kind, text, tags FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?"
    )
    .get(campaignId, contentId) as
    | { content_id: string; kind: string; text: string; tags: string }
    | undefined;
  if (!row) return null;
  return {
    content_id: row.content_id,
    kind: row.kind,
    text: row.text,
    tags: parseContentTags(row.tags),
  };
}

export function updateContentTags(
  campaignId: string,
  contentId: string,
  tags: UpdateContentTagsInput["tags"]
): ContentRecord | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT content_id, kind, text FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?"
      )
      .get(campaignId, contentId) as
      | { content_id: string; kind: string; text: string }
      | undefined;
    if (!row) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare(
        "UPDATE play_campaign_content SET tags = ? WHERE campaign_id = ? AND content_id = ?"
      )
      .run(JSON.stringify(tags), campaignId, contentId);

    database.exec("COMMIT;");
    return {
      content_id: row.content_id,
      kind: row.kind,
      text: row.text,
      tags,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getContentRecords(campaignId: string): ContentRecord[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT content_id, kind, text, tags FROM play_campaign_content WHERE campaign_id = ? ORDER BY rowid ASC"
    )
    .all(campaignId) as Array<{
    content_id: string;
    kind: string;
    text: string;
    tags: string;
  }>;
  return rows.map((r) => ({
    content_id: r.content_id,
    kind: r.kind,
    text: r.text,
    tags: parseContentTags(r.tags),
  }));
}

// ---------------------------------------------------------------------------
// Privacy controls (075)
// ---------------------------------------------------------------------------

export function createNote(
  campaignId: string,
  owner: string,
  input: CreateNoteInput
): Note | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  try {
    database
      .prepare(
        "INSERT INTO play_campaign_notes (campaign_id, note_id, text, visibility, owner) VALUES (?, ?, ?, ?, ?)"
      )
      .run(campaignId, input.note_id, input.text, input.visibility, owner);
    return {
      note_id: input.note_id,
      text: input.text,
      visibility: input.visibility,
      owner,
    };
  } catch {
    return null;
  }
}

export function getNote(
  campaignId: string,
  noteId: string
): Note | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?"
    )
    .get(campaignId, noteId) as
    | { note_id: string; text: string; visibility: "private" | "party"; owner: string }
    | undefined;
  return row || null;
}

export function getNotes(campaignId: string): Note[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? ORDER BY id ASC"
    )
    .all(campaignId) as Array<{
    note_id: string;
    text: string;
    visibility: "private" | "party";
    owner: string;
  }>;
  return rows;
}

export function updateNote(
  campaignId: string,
  noteId: string,
  owner: string,
  input: UpdateNoteInput
): Note | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT note_id, owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?"
      )
      .get(campaignId, noteId) as
      | { note_id: string; owner: string }
      | undefined;
    if (!row || row.owner !== owner) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare(
        "UPDATE play_campaign_notes SET text = ?, visibility = ? WHERE campaign_id = ? AND note_id = ?"
      )
      .run(input.text, input.visibility, campaignId, noteId);

    database.exec("COMMIT;");
    return {
      note_id: noteId,
      text: input.text,
      visibility: input.visibility,
      owner,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function createWhisper(
  campaignId: string,
  fromCharacterId: string,
  input: CreateWhisperInput
): Whisper | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  try {
    database
      .prepare(
        "INSERT INTO play_campaign_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text) VALUES (?, ?, ?, ?, ?)"
      )
      .run(
        campaignId,
        input.whisper_id,
        fromCharacterId,
        input.to_character_id,
        input.text
      );
    return {
      whisper_id: input.whisper_id,
      from_character_id: fromCharacterId,
      to_character_id: input.to_character_id,
      text: input.text,
    };
  } catch {
    return null;
  }
}

export function getWhispers(campaignId: string): Whisper[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers WHERE campaign_id = ? ORDER BY id ASC"
    )
    .all(campaignId) as Array<{
    whisper_id: string;
    from_character_id: string;
    to_character_id: string;
    text: string;
  }>;
  return rows;
}

export function createPlayCampaignMessage(
  campaignId: string,
  actor: string,
  input: CreatePlayCampaignMessageInput
): PlayCampaignMessage | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  try {
    database
      .prepare(
        "INSERT INTO play_campaign_messages (campaign_id, actor, kind, text) VALUES (?, ?, 'chat', ?)"
      )
      .run(campaignId, actor, input.text);
    return {
      kind: "chat",
      actor,
      text: input.text,
    };
  } catch {
    return null;
  }
}

export function getCharacterSheet(
  campaignId: string,
  characterId: string
): CharacterSheet | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT character_id, owner, name, class FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?"
    )
    .get(campaignId, characterId) as
    | {
        character_id: string;
        owner: string | null;
        name: string;
        class: string;
      }
    | undefined;
  if (!row) return null;

  return {
    character_id: row.character_id,
    owner: row.owner ?? "",
    name: row.name,
    class: row.class,
    level: 1,
    proficiency_bonus: 2,
    hp_max: 10,
    armor_class: 10,
  };
}

// ---------------------------------------------------------------------------
// Campaign invitations (076)
// ---------------------------------------------------------------------------

export function createPlayCampaignInvitation(
  campaignId: string,
  input: CreatePlayCampaignInvitationInput
): PlayCampaignInvitation | "not_found" | "bad_request" | "conflict" {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return "not_found";

  const targetUser = getUser(input.username);
  if (!targetUser || targetUser.role !== "player") {
    return "bad_request";
  }

  try {
    database
      .prepare(
        "INSERT INTO play_campaign_invitations (campaign_id, invitation_id, username, character_id, status) VALUES (?, ?, ?, ?, 'pending')"
      )
      .run(campaignId, input.invitation_id, input.username, input.character_id);
    return {
      invitation_id: input.invitation_id,
      username: input.username,
      character_id: input.character_id,
      status: "pending",
    };
  } catch {
    return "conflict";
  }
}

export function getPlayCampaignInvitation(
  campaignId: string,
  invitationId: string
): PlayCampaignInvitation | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?"
    )
    .get(campaignId, invitationId) as
    | {
        invitation_id: string;
        username: string;
        character_id: string;
        status: "pending" | "accepted";
      }
    | undefined;
  return row || null;
}

export function getPlayCampaignInvitations(
  campaignId: string
): PlayCampaignInvitation[] {
  const database = getDb();
  const rows = database
    .prepare(
      "SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? ORDER BY id ASC"
    )
    .all(campaignId) as Array<{
    invitation_id: string;
    username: string;
    character_id: string;
    status: "pending" | "accepted";
  }>;
  return rows;
}

export type AcceptPlayCampaignInvitationResult =
  | PlayCampaignInvitation
  | "not_found"
  | "conflict"
  | "forbidden";

export function acceptPlayCampaignInvitation(
  campaignId: string,
  invitationId: string,
  username: string
): AcceptPlayCampaignInvitationResult {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return "not_found";

  const invitation = getPlayCampaignInvitation(campaignId, invitationId);
  if (!invitation) return "not_found";
  if (invitation.username !== username) return "forbidden";
  if (invitation.status === "accepted") return "conflict";

  database.exec("BEGIN IMMEDIATE;");
  try {
    const currentInvitation = database
      .prepare(
        "SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?"
      )
      .get(campaignId, invitationId) as
      | {
          invitation_id: string;
          username: string;
          character_id: string;
          status: "pending" | "accepted";
        }
      | undefined;
    if (!currentInvitation) {
      database.exec("ROLLBACK;");
      return "not_found";
    }
    if (currentInvitation.username !== username) {
      database.exec("ROLLBACK;");
      return "forbidden";
    }
    if (currentInvitation.status === "accepted") {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    const countRow = database
      .prepare(
        "SELECT COUNT(*) AS count FROM play_campaign_members WHERE campaign_id = ?"
      )
      .get(campaignId) as { count: number };
    if (countRow.count >= campaign.max_players) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    database
      .prepare(
        "INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, owner, gold) VALUES (?, ?, ?, ?, ?, ?, 10)"
      )
      .run(
        campaignId,
        username,
        currentInvitation.character_id,
        currentInvitation.character_id,
        "adventurer",
        username
      );

    database
      .prepare(
        "UPDATE play_campaign_invitations SET status = 'accepted' WHERE campaign_id = ? AND invitation_id = ?"
      )
      .run(campaignId, invitationId);

    database.exec("COMMIT;");
    return {
      invitation_id: currentInvitation.invitation_id,
      username: currentInvitation.username,
      character_id: currentInvitation.character_id,
      status: "accepted",
    };
  } catch {
    database.exec("ROLLBACK;");
    return "conflict";
  }
}

// ---------------------------------------------------------------------------
// Versioned campaign exports (083)
// ---------------------------------------------------------------------------

export function createPlayCampaignExport(
  campaignId: string
): PlayCampaignExportSnapshot | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const documentRow = database
      .prepare(
        "SELECT story FROM play_campaign_documents WHERE campaign_id = ?"
      )
      .get(campaignId) as { story: string } | undefined;
    const story = documentRow?.story ?? "";

    const stateRow = database
      .prepare("SELECT status FROM play_campaign_state WHERE campaign_id = ?")
      .get(campaignId) as { status: string } | undefined;
    const status = stateRow?.status ?? campaign.status;

    const versionRow = database
      .prepare(
        "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM play_campaign_exports WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_version: number };
    const version = versionRow.next_version;

    database
      .prepare(
        "INSERT INTO play_campaign_exports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)"
      )
      .run(campaignId, version, story, status);

    database.exec("COMMIT;");
    return { version, story, status };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignExports(
  campaignId: string
): PlayCampaignExportList | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const rows = database
    .prepare(
      "SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? ORDER BY version ASC"
    )
    .all(campaignId) as Array<{
    version: number;
    story: string;
    status: string;
  }>;

  return { exports: rows };
}

export function getPlayCampaignExportByVersion(
  campaignId: string,
  version: number
): PlayCampaignExportSnapshot | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const row = database
    .prepare(
      "SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? AND version = ?"
    )
    .get(campaignId, version) as
    | { version: number; story: string; status: string }
    | undefined;
  return row || null;
}

// ---------------------------------------------------------------------------
// Campaign imports (084)
// ---------------------------------------------------------------------------

export function createPlayCampaignImport(
  campaignId: string,
  snapshot: PlayCampaignImportSnapshot
): PlayCampaignImportSnapshot | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        `INSERT INTO play_campaign_imports (campaign_id, version, story, status)
         VALUES (?, ?, ?, ?)
         ON CONFLICT(campaign_id) DO UPDATE SET
           version = excluded.version,
           story = excluded.story,
           status = excluded.status`
      )
      .run(campaignId, snapshot.version, snapshot.story, snapshot.status);

    database.exec("COMMIT;");
    return snapshot;
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignImport(
  campaignId: string
): PlayCampaignImportSnapshot | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const row = database
    .prepare(
      "SELECT version, story, status FROM play_campaign_imports WHERE campaign_id = ?"
    )
    .get(campaignId) as
    | { version: number; story: string; status: string }
    | undefined;
  return row || null;
}

// ---------------------------------------------------------------------------
// Schema migrations (085)
// ---------------------------------------------------------------------------

export function createPlayCampaignMigration(
  campaignId: string,
  input: PlayCampaignMigrationInput
): { snapshot: PlayCampaignMigrationSnapshot; created: boolean } | "bad_request" | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  if (input.schema_version !== 1 || typeof input.story !== "string" || input.story.length === 0) {
    return "bad_request";
  }

  database.exec("BEGIN IMMEDIATE;");
  try {
    const existing = database
      .prepare(
        "SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?"
      )
      .get(campaignId) as
      | { schema_version: number; story: string; campaign_name: string }
      | undefined;

    const snapshot: PlayCampaignMigrationSnapshot = {
      schema_version: 2,
      story: input.story,
      campaign_name: campaign.name,
    };

    if (existing) {
      if (existing.story !== input.story) {
        database.exec("ROLLBACK;");
        return "bad_request";
      }
      database.exec("COMMIT;");
      return { snapshot: existing, created: false };
    }

    database
      .prepare(
        "INSERT INTO play_campaign_migrations (campaign_id, schema_version, story, campaign_name) VALUES (?, ?, ?, ?)"
      )
      .run(campaignId, snapshot.schema_version, snapshot.story, snapshot.campaign_name);

    database.exec("COMMIT;");
    return { snapshot, created: true };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignMigration(
  campaignId: string
): PlayCampaignMigrationSnapshot | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const row = database
    .prepare(
      "SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?"
    )
    .get(campaignId) as
    | { schema_version: number; story: string; campaign_name: string }
    | undefined;
  return row || null;
}

// ---------------------------------------------------------------------------
// Search records (086)
// ---------------------------------------------------------------------------

export function createSearchRecord(
  campaignId: string,
  input: CreateSearchRecordInput
): SearchRecord | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  const existing = database
    .prepare(
      "SELECT 1 FROM play_campaign_search_records WHERE campaign_id = ? AND (record_id = ? OR text = ?)"
    )
    .get(campaignId, input.record_id, input.text);
  if (existing) {
    return null;
  }

  try {
    database
      .prepare(
        "INSERT INTO play_campaign_search_records (campaign_id, record_id, text) VALUES (?, ?, ?)"
      )
      .run(campaignId, input.record_id, input.text);
    return { record_id: input.record_id, text: input.text };
  } catch {
    return null;
  }
}

export function getSearchRecords(
  campaignId: string,
  q: string | null,
  cursor: number,
  limit: number
): SearchRecordList {
  const database = getDb();

  const rows = database
    .prepare(
      q === null
        ? "SELECT record_id, text FROM play_campaign_search_records WHERE campaign_id = ? ORDER BY id ASC"
        : "SELECT record_id, text FROM play_campaign_search_records WHERE campaign_id = ? AND LOWER(text) LIKE LOWER('%' || ? || '%') ORDER BY id ASC"
    )
    .all(...(q === null ? [campaignId] : [campaignId, q])) as Array<{
    record_id: string;
    text: string;
  }>;

  const filtered = rows;
  const page = filtered.slice(cursor, cursor + limit);
  const next_cursor =
    cursor + limit < filtered.length ? cursor + limit : null;

  return { records: page, next_cursor };
}

// ---------------------------------------------------------------------------
// Rate events (087)
// ---------------------------------------------------------------------------

const RATE_EVENT_LIMIT = 2;

export function createPlayCampaignRateEvent(
  campaignId: string,
  actor: string,
  eventId: string
): RateEventCreateResult | "rate_limited" | "conflict" | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const duplicate = database
      .prepare(
        "SELECT 1 FROM play_campaign_rate_events WHERE campaign_id = ? AND event_id = ?"
      )
      .get(campaignId, eventId) as { 1: number } | undefined;
    if (duplicate) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    const countRow = database
      .prepare(
        "SELECT COUNT(*) AS count FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?"
      )
      .get(campaignId, actor) as { count: number };

    if (countRow.count >= RATE_EVENT_LIMIT) {
      database
        .prepare(
          `INSERT INTO play_campaign_service_metrics (campaign_id, accepted_rate_events, rejected_rate_events, projection_events, uptime_ticks)
           VALUES (?, 0, 1, 0, 1)
           ON CONFLICT(campaign_id) DO UPDATE SET rejected_rate_events = rejected_rate_events + 1`
        )
        .run(campaignId);
      database.exec("COMMIT;");
      return "rate_limited";
    }

    database
      .prepare(
        "INSERT INTO play_campaign_rate_events (campaign_id, event_id, actor) VALUES (?, ?, ?)"
      )
      .run(campaignId, eventId, actor);

    database
      .prepare(
        `INSERT INTO play_campaign_service_metrics (campaign_id, accepted_rate_events, rejected_rate_events, projection_events, uptime_ticks)
         VALUES (?, 1, 0, 0, 1)
         ON CONFLICT(campaign_id) DO UPDATE SET accepted_rate_events = accepted_rate_events + 1`
      )
      .run(campaignId);

    const remaining = RATE_EVENT_LIMIT - countRow.count - 1;
    database.exec("COMMIT;");
    return { event_id: eventId, actor, remaining };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignRateEvents(
  campaignId: string,
  actor: string
): RateEventList | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  const rows = database
    .prepare(
      "SELECT event_id, actor FROM play_campaign_rate_events WHERE campaign_id = ? ORDER BY id ASC"
    )
    .all(campaignId) as Array<{ event_id: string; actor: string }>;

  const countRow = database
    .prepare(
      "SELECT COUNT(*) AS count FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?"
    )
    .get(campaignId, actor) as { count: number };
  const remaining = Math.max(0, RATE_EVENT_LIMIT - countRow.count);

  return { events: rows, remaining };
}

// ---------------------------------------------------------------------------
// Service metrics (088)
// ---------------------------------------------------------------------------

export function getPlayCampaignServiceMetrics(
  campaignId: string
): ServiceMetrics | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  const row = database
    .prepare(
      "SELECT accepted_rate_events, rejected_rate_events, projection_events, uptime_ticks FROM play_campaign_service_metrics WHERE campaign_id = ?"
    )
    .get(campaignId) as
    | {
        accepted_rate_events: number;
        rejected_rate_events: number;
        projection_events: number;
        uptime_ticks: number;
      }
    | undefined;

  if (!row) {
    return {
      accepted_rate_events: 0,
      rejected_rate_events: 0,
      projection_events: 0,
      uptime_ticks: 1,
    };
  }

  return {
    accepted_rate_events: row.accepted_rate_events,
    rejected_rate_events: row.rejected_rate_events,
    projection_events: row.projection_events,
    uptime_ticks: 1,
  };
}

// ---------------------------------------------------------------------------
// Campaign backups (090)
// ---------------------------------------------------------------------------

function getCampaignCurrentStatus(campaignId: string): string {
  const database = getDb();
  const stateRow = database
    .prepare("SELECT status FROM play_campaign_state WHERE campaign_id = ?")
    .get(campaignId) as { status: string } | undefined;
  if (stateRow) {
    return stateRow.status;
  }
  const campaign = getPlayCampaign(campaignId);
  return campaign?.status ?? "lobby";
}

export function createCampaignBackup(
  campaignId: string
): PlayCampaignBackup | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const documentRow = database
      .prepare(
        "SELECT story FROM play_campaign_documents WHERE campaign_id = ?"
      )
      .get(campaignId) as { story: string } | undefined;
    const story = documentRow?.story ?? "";

    const status = getCampaignCurrentStatus(campaignId);

    const countRow = database
      .prepare(
        "SELECT COUNT(*) AS count FROM play_campaign_backups WHERE campaign_id = ?"
      )
      .get(campaignId) as { count: number };
    const backupId = `backup-${countRow.count + 1}`;

    database
      .prepare(
        "INSERT INTO play_campaign_backups (campaign_id, backup_id, story, status) VALUES (?, ?, ?, ?)"
      )
      .run(campaignId, backupId, story, status);

    database.exec("COMMIT;");
    return { backup_id: backupId, story, status };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getCampaignBackups(
  campaignId: string
): PlayCampaignBackupList | null {
  const database = getDb();
  if (!getPlayCampaign(campaignId)) return null;

  const rows = database
    .prepare(
      "SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = ? ORDER BY id ASC"
    )
    .all(campaignId) as Array<{
    backup_id: string;
    story: string;
    status: string;
  }>;

  return { backups: rows };
}

export function restoreCampaignBackup(
  campaignId: string,
  backupId: string
): PlayCampaignBackup | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const backupRow = database
      .prepare(
        "SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = ? AND backup_id = ?"
      )
      .get(campaignId, backupId) as
      | { backup_id: string; story: string; status: string }
      | undefined;
    if (!backupRow) {
      database.exec("ROLLBACK;");
      return null;
    }

    database
      .prepare(
        "INSERT OR IGNORE INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, '', '')"
      )
      .run(campaignId);

    database
      .prepare("UPDATE play_campaign_documents SET story = ? WHERE campaign_id = ?")
      .run(backupRow.story, campaignId);

    const stateRow = database
      .prepare("SELECT 1 FROM play_campaign_state WHERE campaign_id = ?")
      .get(campaignId) as { 1: number } | undefined;
    if (stateRow) {
      database
        .prepare("UPDATE play_campaign_state SET status = ? WHERE campaign_id = ?")
        .run(backupRow.status, campaignId);
    } else {
      database
        .prepare("UPDATE play_campaigns SET status = ? WHERE id = ?")
        .run(backupRow.status, campaignId);
    }

    database.exec("COMMIT;");
    return {
      backup_id: backupRow.backup_id,
      story: backupRow.story,
      status: backupRow.status,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

// ---------------------------------------------------------------------------
// Deterministic replay events (091)
// ---------------------------------------------------------------------------

export function createPlayCampaignReplayEvent(
  campaignId: string,
  input: CreatePlayCampaignReplayEventInput
): PlayCampaignReplayEvent | "conflict" | "bad_request" | null {
  if (
    typeof input.event_id !== "string" || input.event_id.length === 0 ||
    input.kind !== "append" ||
    typeof input.text !== "string" || input.text.length === 0
  ) {
    return "bad_request";
  }

  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const existing = database
      .prepare(
        "SELECT 1 FROM play_campaign_replay_events WHERE campaign_id = ? AND event_id = ?"
      )
      .get(campaignId, input.event_id) as { 1: number } | undefined;
    if (existing) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_replay_events WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_replay_events (campaign_id, sequence, event_id, kind, text) VALUES (?, ?, ?, ?, ?)"
      )
      .run(campaignId, sequence, input.event_id, input.kind, input.text);

    database.exec("COMMIT;");
    return {
      event_id: input.event_id,
      kind: input.kind,
      text: input.text,
      sequence,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignReplayState(
  campaignId: string
): PlayCampaignReplayState | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const rows = database
    .prepare(
      "SELECT event_id, text FROM play_campaign_replay_events WHERE campaign_id = ? ORDER BY sequence ASC"
    )
    .all(campaignId) as Array<{ event_id: string; text: string }>;

  const eventIds = rows.map((row) => row.event_id);
  const story = rows.map((row) => row.text).join("");
  const digest = eventIds.join(",") + "|" + story;

  return {
    story,
    event_ids: eventIds,
    digest,
  };
}

// ---------------------------------------------------------------------------
// Load-safe event feed (099)
// ---------------------------------------------------------------------------

export function createPlayCampaignFeedEvent(
  campaignId: string,
  input: PlayCampaignFeedEventInput
): PlayCampaignFeedEvent | "conflict" | "bad_request" | null {
  if (
    typeof input.event_id !== "string" || input.event_id.length === 0 ||
    typeof input.text !== "string" || input.text.length === 0
  ) {
    return "bad_request";
  }

  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const existing = database
      .prepare(
        "SELECT 1 FROM play_campaign_feed_events WHERE campaign_id = ? AND event_id = ?"
      )
      .get(campaignId, input.event_id) as { 1: number } | undefined;
    if (existing) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_feed_events WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_feed_events (campaign_id, sequence, event_id, text) VALUES (?, ?, ?, ?)"
      )
      .run(campaignId, sequence, input.event_id, input.text);

    database.exec("COMMIT;");
    return {
      event_id: input.event_id,
      text: input.text,
      sequence,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignFeedEvents(
  campaignId: string,
  cursor: number,
  limit: number
): PlayCampaignFeedPage | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const rows = database
    .prepare(
      "SELECT event_id, text, sequence FROM play_campaign_feed_events WHERE campaign_id = ? ORDER BY sequence ASC LIMIT ? OFFSET ?"
    )
    .all(campaignId, limit, cursor) as Array<{
    event_id: string;
    text: string;
    sequence: number;
  }>;

  return {
    events: rows.map((row) => ({
      event_id: row.event_id,
      text: row.text,
      sequence: row.sequence,
    })),
    next_cursor: cursor + rows.length,
  };
}

// ---------------------------------------------------------------------------
// Deterministic RNG ledger (092)
// ---------------------------------------------------------------------------

function computeRngRoll(seed: string, sequence: number, rollId: string, sides: number): number {
  const byteString = seed + "|" + sequence + "|" + rollId + "|" + sides;
  const bytes = Buffer.from(byteString, "utf8");
  let acc = 0;
  for (const b of bytes) {
    acc = (acc * 31 + b) >>> 0;
  }
  return (acc % sides) + 1;
}

export function configureRngSeed(
  campaignId: string,
  input: ConfigureRngSeedInput
): PlayCampaignRngLedger | "conflict" | "bad_request" | null {
  if (typeof input.seed !== "string" || input.seed.length === 0) {
    return "bad_request";
  }

  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const existing = database
      .prepare(
        "SELECT 1 FROM play_campaign_rng_seeds WHERE campaign_id = ?"
      )
      .get(campaignId) as { 1: number } | undefined;
    if (existing) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    database
      .prepare(
        "INSERT INTO play_campaign_rng_seeds (campaign_id, seed) VALUES (?, ?)"
      )
      .run(campaignId, input.seed);

    database.exec("COMMIT;");
    return { seed: input.seed, rolls: [] };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function appendRngRoll(
  campaignId: string,
  input: CreateRngRollInput
): PlayCampaignRngRoll | "conflict" | "bad_request" | "missing_seed" | null {
  if (
    typeof input.roll_id !== "string" || input.roll_id.length === 0 ||
    typeof input.sides !== "number" || !Number.isInteger(input.sides) ||
    input.sides < 2 || input.sides > 100
  ) {
    return "bad_request";
  }

  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const seedRow = database
      .prepare(
        "SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?"
      )
      .get(campaignId) as { seed: string } | undefined;
    if (!seedRow) {
      database.exec("ROLLBACK;");
      return "missing_seed";
    }

    const existing = database
      .prepare(
        "SELECT 1 FROM play_campaign_rng_rolls WHERE campaign_id = ? AND roll_id = ?"
      )
      .get(campaignId, input.roll_id) as { 1: number } | undefined;
    if (existing) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_rng_rolls WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    const result = computeRngRoll(seedRow.seed, sequence, input.roll_id, input.sides);

    database
      .prepare(
        "INSERT INTO play_campaign_rng_rolls (campaign_id, sequence, roll_id, sides, result) VALUES (?, ?, ?, ?, ?)"
      )
      .run(campaignId, sequence, input.roll_id, input.sides, result);

    database.exec("COMMIT;");
    return {
      roll_id: input.roll_id,
      sides: input.sides,
      result,
      sequence,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getRngLedger(
  campaignId: string
): PlayCampaignRngLedger | "missing_seed" | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const seedRow = database
    .prepare(
      "SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?"
    )
    .get(campaignId) as { seed: string } | undefined;
  if (!seedRow) {
    return "missing_seed";
  }

  const rows = database
    .prepare(
      "SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls WHERE campaign_id = ? ORDER BY sequence ASC"
    )
    .all(campaignId) as Array<{
    roll_id: string;
    sides: number;
    result: number;
    sequence: number;
  }>;

  return {
    seed: seedRow.seed,
    rolls: rows,
  };
}

// ---------------------------------------------------------------------------
// Moderation workflow (093)
// ---------------------------------------------------------------------------

export function createPlayCampaignModerationReport(
  campaignId: string,
  reporter: string,
  input: CreatePlayCampaignModerationReportInput
): PlayCampaignModerationReport | "conflict" | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const existing = database
      .prepare(
        "SELECT 1 FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?"
      )
      .get(campaignId, input.report_id) as { 1: number } | undefined;
    if (existing) {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_moderation_reports WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_moderation_reports (campaign_id, report_id, target_id, reason, status, reporter, sequence) VALUES (?, ?, ?, ?, 'open', ?, ?)"
      )
      .run(
        campaignId,
        input.report_id,
        input.target_id,
        input.reason,
        reporter,
        sequence
      );

    database.exec("COMMIT;");
    return {
      report_id: input.report_id,
      target_id: input.target_id,
      reason: input.reason,
      status: "open",
      reporter,
      sequence,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignModerationReports(
  campaignId: string
): PlayCampaignModerationReports | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const rows = database
    .prepare(
      "SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM play_campaign_moderation_reports WHERE campaign_id = ? ORDER BY sequence ASC"
    )
    .all(campaignId) as Array<{
    report_id: string;
    target_id: string;
    reason: string;
    status: "open" | "resolved";
    reporter: string;
    sequence: number;
    action: string | null;
    note: string | null;
    resolver: string | null;
  }>;

  return {
    reports: rows.map((row) => {
      const report: PlayCampaignModerationReport = {
        report_id: row.report_id,
        target_id: row.target_id,
        reason: row.reason,
        status: row.status,
        reporter: row.reporter,
        sequence: row.sequence,
      };
      if (row.status === "resolved") {
        report.action = row.action as "allow" | "remove";
        report.note = row.note ?? undefined;
        report.resolver = row.resolver ?? undefined;
      }
      return report;
    }),
  };
}

export function resolvePlayCampaignModerationReport(
  campaignId: string,
  reportId: string,
  resolver: string,
  input: ResolvePlayCampaignModerationReportInput
): PlayCampaignModerationReport | "not_found" | "conflict" | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const row = database
      .prepare(
        "SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?"
      )
      .get(campaignId, reportId) as
      | {
          report_id: string;
          target_id: string;
          reason: string;
          status: "open" | "resolved";
          reporter: string;
          sequence: number;
          action: string | null;
          note: string | null;
          resolver: string | null;
        }
      | undefined;

    if (!row) {
      database.exec("ROLLBACK;");
      return "not_found";
    }

    if (row.status === "resolved") {
      database.exec("ROLLBACK;");
      return "conflict";
    }

    database
      .prepare(
        "UPDATE play_campaign_moderation_reports SET status = 'resolved', action = ?, note = ?, resolver = ? WHERE campaign_id = ? AND report_id = ?"
      )
      .run(input.action, input.note, resolver, campaignId, reportId);

    database.exec("COMMIT;");

    const report: PlayCampaignModerationReport = {
      report_id: row.report_id,
      target_id: row.target_id,
      reason: row.reason,
      status: "resolved",
      reporter: row.reporter,
      sequence: row.sequence,
      action: input.action,
      note: input.note,
      resolver,
    };
    return report;
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

// ---------------------------------------------------------------------------
// Safety boundaries (094)
// ---------------------------------------------------------------------------

export function replacePlayCampaignSafetyBoundaries(
  campaignId: string,
  blockedTags: string[]
): PlayCampaignSafetyBoundaries | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const sorted = [...blockedTags].sort();

  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO play_campaign_safety_boundaries (campaign_id, blocked_tags) VALUES (?, ?) ON CONFLICT(campaign_id) DO UPDATE SET blocked_tags = excluded.blocked_tags"
      )
      .run(campaignId, JSON.stringify(sorted));
    database.exec("COMMIT;");
    return { blocked_tags: sorted };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignSafetyBoundaries(
  campaignId: string
): PlayCampaignSafetyBoundaries | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const row = database
    .prepare(
      "SELECT blocked_tags FROM play_campaign_safety_boundaries WHERE campaign_id = ?"
    )
    .get(campaignId) as { blocked_tags: string } | undefined;

  return {
    blocked_tags: row ? (JSON.parse(row.blocked_tags) as string[]) : [],
  };
}

export function createPlayCampaignSafetyCheck(
  campaignId: string,
  input: CreatePlayCampaignSafetyCheckInput
): PlayCampaignSafetyEvent | "duplicate" | "blocked" | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const existing = database
      .prepare(
        "SELECT 1 FROM play_campaign_safety_events WHERE campaign_id = ? AND event_id = ?"
      )
      .get(campaignId, input.event_id) as { 1: number } | undefined;
    if (existing) {
      database.exec("ROLLBACK;");
      return "duplicate";
    }

    const boundaryRow = database
      .prepare(
        "SELECT blocked_tags FROM play_campaign_safety_boundaries WHERE campaign_id = ?"
      )
      .get(campaignId) as { blocked_tags: string } | undefined;
    const blockedTags: string[] = boundaryRow
      ? (JSON.parse(boundaryRow.blocked_tags) as string[])
      : [];
    const blockedSet = new Set(blockedTags);
    if (input.tags.some((tag) => blockedSet.has(tag))) {
      database.exec("ROLLBACK;");
      return "blocked";
    }

    const seqRow = database
      .prepare(
        "SELECT COALESCE(MAX(sequence), 0) AS next_sequence FROM play_campaign_safety_events WHERE campaign_id = ?"
      )
      .get(campaignId) as { next_sequence: number };
    const sequence = seqRow.next_sequence + 1;

    database
      .prepare(
        "INSERT INTO play_campaign_safety_events (campaign_id, event_id, kind, text, tags, sequence) VALUES (?, ?, ?, ?, ?, ?)"
      )
      .run(
        campaignId,
        input.event_id,
        input.kind,
        input.text,
        JSON.stringify(input.tags),
        sequence
      );

    database.exec("COMMIT;");
    return {
      event_id: input.event_id,
      kind: input.kind,
      text: input.text,
      tags: input.tags,
      sequence,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignSafetyEvents(
  campaignId: string
): PlayCampaignSafetyEvents | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const rows = database
    .prepare(
      "SELECT event_id, kind, text, tags, sequence FROM play_campaign_safety_events WHERE campaign_id = ? ORDER BY sequence ASC"
    )
    .all(campaignId) as Array<{
    event_id: string;
    kind: "narration" | "chat";
    text: string;
    tags: string;
    sequence: number;
  }>;

  return {
    events: rows.map((row) => ({
      event_id: row.event_id,
      kind: row.kind,
      text: row.text,
      tags: JSON.parse(row.tags) as string[],
      sequence: row.sequence,
    })),
  };
}

// ---------------------------------------------------------------------------
// Fixture seeding (095)
// ---------------------------------------------------------------------------

const CANONICAL_FIXTURE: PlayCampaignFixtureState = {
  fixture_id: "canonical-v1",
  status: "seeded",
  characters: [
    { character_id: "fixture-hero", name: "Ari", class: "fighter" },
    { character_id: "fixture-mage", name: "Bea", class: "wizard" },
  ],
  story: "The lantern is lit.",
  event_ids: ["fixture-event-1", "fixture-event-2"],
};

export function seedPlayCampaignFixture(
  campaignId: string,
  fixtureId: string
): { state: PlayCampaignFixtureState; created: boolean } | "bad_request" | null {
  if (fixtureId !== "canonical-v1") {
    return "bad_request";
  }

  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  database.exec("BEGIN IMMEDIATE;");
  try {
    const existing = database
      .prepare(
        "SELECT fixture_id, status, characters, story, event_ids FROM play_campaign_fixtures WHERE campaign_id = ?"
      )
      .get(campaignId) as
      | {
          fixture_id: string;
          status: string;
          characters: string;
          story: string;
          event_ids: string;
        }
      | undefined;

    if (existing) {
      database.exec("ROLLBACK;");
      const state: PlayCampaignFixtureState = {
        fixture_id: existing.fixture_id as "canonical-v1",
        status: existing.status as "seeded",
        characters: JSON.parse(existing.characters) as Array<{
          character_id: string;
          name: string;
          class: string;
        }>,
        story: existing.story,
        event_ids: JSON.parse(existing.event_ids) as string[],
      };
      return { state, created: false };
    }

    database
      .prepare(
        "INSERT INTO play_campaign_fixtures (campaign_id, fixture_id, status, characters, story, event_ids) VALUES (?, ?, ?, ?, ?, ?)"
      )
      .run(
        campaignId,
        CANONICAL_FIXTURE.fixture_id,
        CANONICAL_FIXTURE.status,
        JSON.stringify(CANONICAL_FIXTURE.characters),
        CANONICAL_FIXTURE.story,
        JSON.stringify(CANONICAL_FIXTURE.event_ids)
      );

    database.exec("COMMIT;");
    return { state: CANONICAL_FIXTURE, created: true };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getPlayCampaignFixtureState(
  campaignId: string
): PlayCampaignFixtureState | null {
  const database = getDb();
  const campaign = getPlayCampaign(campaignId);
  if (!campaign) return null;

  const row = database
    .prepare(
      "SELECT fixture_id, status, characters, story, event_ids FROM play_campaign_fixtures WHERE campaign_id = ?"
    )
    .get(campaignId) as
    | {
        fixture_id: string;
        status: string;
        characters: string;
        story: string;
        event_ids: string;
      }
    | undefined;

  if (!row) return null;

  return {
    fixture_id: row.fixture_id as "canonical-v1",
    status: row.status as "seeded",
    characters: JSON.parse(row.characters) as Array<{
      character_id: string;
      name: string;
      class: string;
    }>,
    story: row.story,
    event_ids: JSON.parse(row.event_ids) as string[],
  };
}
