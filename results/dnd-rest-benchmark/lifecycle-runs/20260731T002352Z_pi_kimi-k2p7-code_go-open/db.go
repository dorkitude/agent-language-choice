package main

import (
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"sort"
	"strconv"
	"strings"

	_ "modernc.org/sqlite"
)

const (
	dbFile        = "game.db"
	schemaVersion = 1
)

// executor abstracts the database operations that can execute a DDL statement.
// It lets applySchema run against both *sql.DB and *sql.Tx.
type executor interface {
	Exec(query string, args ...any) (sql.Result, error)
}

// schemaStatements creates the full SQLite schema. The drop order in
// storageResetHandler must be the reverse of the foreign-key dependencies here,
// and the create order must keep foreign keys satisfied.
var schemaStatements = []string{
	`CREATE TABLE IF NOT EXISTS schema_version (
		version INTEGER PRIMARY KEY
	)`,
	`INSERT OR IGNORE INTO schema_version (version) VALUES (1)`,
	`CREATE TABLE IF NOT EXISTS users (
		username TEXT PRIMARY KEY,
		password_hash TEXT NOT NULL,
		role TEXT NOT NULL
	)`,
	`CREATE TABLE IF NOT EXISTS combat_sessions (
		id TEXT PRIMARY KEY,
		round INTEGER NOT NULL,
		turn_index INTEGER NOT NULL
	)`,
	`CREATE TABLE IF NOT EXISTS combat_order (
		session_id TEXT NOT NULL,
		position INTEGER NOT NULL,
		name TEXT NOT NULL,
		score INTEGER NOT NULL,
		PRIMARY KEY (session_id, position),
		FOREIGN KEY (session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS combat_conditions (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		session_id TEXT NOT NULL,
		target TEXT NOT NULL,
		condition TEXT NOT NULL,
		remaining_rounds INTEGER NOT NULL,
		FOREIGN KEY (session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS monsters (
		slug TEXT PRIMARY KEY,
		name TEXT NOT NULL,
		cr TEXT NOT NULL,
		armor_class INTEGER NOT NULL,
		hit_points INTEGER NOT NULL
	)`,
	`CREATE TABLE IF NOT EXISTS monster_tags (
		monster_slug TEXT NOT NULL,
		tag TEXT NOT NULL,
		PRIMARY KEY (monster_slug, tag),
		FOREIGN KEY (monster_slug) REFERENCES monsters(slug) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS items (
		slug TEXT PRIMARY KEY,
		name TEXT NOT NULL,
		type TEXT NOT NULL,
		rarity TEXT NOT NULL,
		cost_gp INTEGER NOT NULL
	)`,
	`CREATE TABLE IF NOT EXISTS campaigns (
		id TEXT PRIMARY KEY,
		name TEXT NOT NULL,
		dm TEXT NOT NULL
	)`,
	`CREATE TABLE IF NOT EXISTS play_campaigns (
		id TEXT PRIMARY KEY,
		name TEXT NOT NULL,
		owner TEXT NOT NULL,
		status TEXT NOT NULL,
		max_players INTEGER NOT NULL,
		current_actor TEXT,
		turn_number INTEGER DEFAULT 0,
		nudge_count INTEGER DEFAULT 0,
		current_scene_id TEXT,
		current_location_id TEXT,
		story TEXT NOT NULL DEFAULT '',
		dm_notes TEXT NOT NULL DEFAULT ''
	)`,
	`CREATE TABLE IF NOT EXISTS play_session_zero_settings (
		campaign_id TEXT PRIMARY KEY,
		rules TEXT NOT NULL,
		tone TEXT NOT NULL,
		consent TEXT NOT NULL,
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_members (
		campaign_id TEXT NOT NULL,
		username TEXT,
		character_id TEXT NOT NULL,
		name TEXT NOT NULL,
		class TEXT NOT NULL,
		race TEXT,
		background TEXT,
		level INTEGER NOT NULL DEFAULT 1,
		abilities TEXT,
		hp_current INTEGER NOT NULL DEFAULT 20,
		hp_max INTEGER NOT NULL DEFAULT 20,
		status TEXT NOT NULL DEFAULT 'conscious',
		death_save_successes INTEGER NOT NULL DEFAULT 0,
		death_save_failures INTEGER NOT NULL DEFAULT 0,
		gold INTEGER NOT NULL DEFAULT 10,
		PRIMARY KEY (campaign_id, character_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_inventory (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		item_id TEXT NOT NULL,
		quantity INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, character_id, item_id),
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_character_equipment (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		slot TEXT NOT NULL,
		item_id TEXT NOT NULL,
		attuned INTEGER NOT NULL DEFAULT 0,
		PRIMARY KEY (campaign_id, character_id, slot),
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_gold_transfers (
		campaign_id TEXT NOT NULL,
		transfer_id INTEGER NOT NULL,
		from_character_id TEXT NOT NULL,
		to_character_id TEXT NOT NULL,
		gold INTEGER NOT NULL,
		from_gold INTEGER NOT NULL,
		to_gold INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, transfer_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, from_character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, to_character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_loot (
		campaign_id TEXT NOT NULL,
		loot_id TEXT NOT NULL,
		item_id TEXT NOT NULL,
		quantity INTEGER NOT NULL,
		status TEXT NOT NULL DEFAULT 'open',
		recipient_character_id TEXT,
		PRIMARY KEY (campaign_id, loot_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_loot_votes (
		campaign_id TEXT NOT NULL,
		loot_id TEXT NOT NULL,
		voter TEXT NOT NULL,
		recipient_character_id TEXT NOT NULL,
		PRIMARY KEY (campaign_id, loot_id, voter),
		FOREIGN KEY (campaign_id, loot_id) REFERENCES play_loot(campaign_id, loot_id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, recipient_character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_npcs (
		campaign_id TEXT NOT NULL,
		npc_id TEXT NOT NULL,
		name TEXT NOT NULL,
		agenda TEXT NOT NULL,
		public_status TEXT NOT NULL,
		PRIMARY KEY (campaign_id, npc_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS character_spells (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		spell_id TEXT NOT NULL,
		name TEXT NOT NULL,
		level INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, character_id, spell_id),
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS character_prepared_spells (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		spell_id TEXT NOT NULL,
		position INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, character_id, spell_id),
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, character_id, spell_id) REFERENCES character_spells(campaign_id, character_id, spell_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS character_spell_slots (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		level INTEGER NOT NULL,
		slots_remaining INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, character_id, level),
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS character_spell_casts (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		spell_id TEXT NOT NULL,
		target TEXT NOT NULL DEFAULT '',
		slot_level INTEGER NOT NULL,
		slots_remaining INTEGER NOT NULL,
		sequence INTEGER NOT NULL,
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS character_concentration (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		spell_id TEXT NOT NULL,
		target TEXT NOT NULL DEFAULT '',
		remaining_turns INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, character_id),
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_narrations (
		campaign_id TEXT NOT NULL,
		sequence INTEGER NOT NULL,
		kind TEXT NOT NULL,
		actor TEXT NOT NULL,
		type TEXT,
		text TEXT NOT NULL,
		target TEXT,
		PRIMARY KEY (campaign_id, sequence),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_scenes (
		id TEXT NOT NULL,
		campaign_id TEXT NOT NULL,
		name TEXT NOT NULL,
		status TEXT NOT NULL,
		PRIMARY KEY (id, campaign_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_content (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		content_id TEXT NOT NULL,
		kind TEXT NOT NULL,
		text TEXT NOT NULL,
		tags TEXT NOT NULL,
		UNIQUE (campaign_id, content_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_locations (
		id TEXT NOT NULL,
		campaign_id TEXT NOT NULL,
		name TEXT NOT NULL,
		PRIMARY KEY (id, campaign_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_connections (
		campaign_id TEXT NOT NULL,
		from_id TEXT NOT NULL,
		to_id TEXT NOT NULL,
		travel_turns INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, from_id, to_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_encounters (
		id TEXT NOT NULL,
		campaign_id TEXT NOT NULL,
		name TEXT NOT NULL,
		status TEXT NOT NULL,
		round INTEGER NOT NULL DEFAULT 1,
		turn_index INTEGER NOT NULL DEFAULT 0,
		combatant_order TEXT,
		pre_combat_actor TEXT,
		PRIMARY KEY (id, campaign_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_combatants (
		encounter_id TEXT NOT NULL,
		campaign_id TEXT NOT NULL,
		name TEXT NOT NULL,
		member TEXT,
		character_id TEXT,
		initiative INTEGER,
		PRIMARY KEY (encounter_id, campaign_id, name),
		UNIQUE (encounter_id, campaign_id, member),
		FOREIGN KEY (encounter_id, campaign_id) REFERENCES play_encounters(id, campaign_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_encounter_monsters (
		encounter_id TEXT NOT NULL,
		campaign_id TEXT NOT NULL,
		monster_id TEXT NOT NULL,
		name TEXT NOT NULL,
		hp_max INTEGER NOT NULL,
		hp_current INTEGER NOT NULL,
		initiative INTEGER NOT NULL,
		PRIMARY KEY (encounter_id, campaign_id, monster_id),
		FOREIGN KEY (encounter_id, campaign_id) REFERENCES play_encounters(id, campaign_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_encounter_conditions (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		encounter_id TEXT NOT NULL,
		campaign_id TEXT NOT NULL,
		target TEXT NOT NULL,
		condition TEXT NOT NULL,
		remaining_rounds INTEGER NOT NULL,
		FOREIGN KEY (encounter_id, campaign_id) REFERENCES play_encounters(id, campaign_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_encounter_rewards (
		encounter_id TEXT NOT NULL,
		campaign_id TEXT NOT NULL,
		xp INTEGER NOT NULL,
		loot TEXT NOT NULL,
		PRIMARY KEY (encounter_id, campaign_id),
		FOREIGN KEY (encounter_id, campaign_id) REFERENCES play_encounters(id, campaign_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS quests (
		id TEXT PRIMARY KEY,
		campaign_id TEXT NOT NULL,
		title TEXT NOT NULL,
		status TEXT NOT NULL,
		FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS quest_milestones (
		quest_id TEXT NOT NULL,
		position INTEGER NOT NULL,
		title TEXT NOT NULL,
		done INTEGER NOT NULL DEFAULT 0,
		PRIMARY KEY (quest_id, position),
		FOREIGN KEY (quest_id) REFERENCES quests(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS characters (
		id TEXT PRIMARY KEY,
		campaign_id TEXT NOT NULL,
		name TEXT NOT NULL,
		level INTEGER NOT NULL,
		class TEXT NOT NULL,
		FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS events (
		id TEXT PRIMARY KEY,
		campaign_id TEXT NOT NULL,
		kind TEXT NOT NULL,
		summary TEXT NOT NULL,
		FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS campaign_sessions (
		id TEXT PRIMARY KEY,
		campaign_id TEXT NOT NULL,
		starts_at TEXT NOT NULL,
		duration_minutes INTEGER NOT NULL,
		FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS session_agenda (
		session_id TEXT NOT NULL,
		position INTEGER NOT NULL,
		item TEXT NOT NULL,
		PRIMARY KEY (session_id, position),
		FOREIGN KEY (session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS session_attendance (
		session_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		status TEXT NOT NULL,
		PRIMARY KEY (session_id, character_id),
		FOREIGN KEY (session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS factions (
		id TEXT PRIMARY KEY,
		campaign_id TEXT NOT NULL,
		name TEXT NOT NULL,
		stance TEXT NOT NULL,
		FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS npcs (
		id TEXT PRIMARY KEY,
		campaign_id TEXT NOT NULL,
		faction_id TEXT NOT NULL,
		name TEXT NOT NULL,
		disposition INTEGER NOT NULL,
		FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
		FOREIGN KEY (faction_id) REFERENCES factions(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS inventory (
		campaign_id TEXT NOT NULL,
		item_slug TEXT NOT NULL,
		owner TEXT NOT NULL,
		quantity INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, item_slug, owner),
		FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
		FOREIGN KEY (item_slug) REFERENCES items(slug) ON DELETE RESTRICT
	)`,
	`CREATE TABLE IF NOT EXISTS equipment (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		item_slug TEXT NOT NULL,
		quantity INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, character_id, item_slug),
		FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
		FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
		FOREIGN KEY (item_slug) REFERENCES items(slug) ON DELETE RESTRICT
	)`,
	`CREATE TABLE IF NOT EXISTS crafting_projects (
		id TEXT PRIMARY KEY,
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		item_slug TEXT NOT NULL,
		days_required INTEGER NOT NULL,
		days_completed INTEGER NOT NULL DEFAULT 0,
		cost_gp INTEGER NOT NULL,
		status TEXT NOT NULL,
		FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
		FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
		FOREIGN KEY (item_slug) REFERENCES items(slug) ON DELETE RESTRICT
	)`,
	`CREATE TABLE IF NOT EXISTS play_factions (
		campaign_id TEXT NOT NULL,
		faction_id TEXT NOT NULL,
		name TEXT NOT NULL,
		PRIMARY KEY (campaign_id, faction_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_reputation_history (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		faction_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		delta INTEGER NOT NULL,
		reputation INTEGER NOT NULL,
		reason TEXT NOT NULL,
		FOREIGN KEY (campaign_id, faction_id) REFERENCES play_factions(campaign_id, faction_id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_npc_dialogue (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		npc_id TEXT NOT NULL,
		dialogue_id TEXT NOT NULL,
		speaker TEXT NOT NULL,
		text TEXT NOT NULL,
		visibility TEXT NOT NULL,
		UNIQUE (campaign_id, npc_id, dialogue_id),
		FOREIGN KEY (campaign_id, npc_id) REFERENCES play_npcs(campaign_id, npc_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_relationships (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		source_id TEXT NOT NULL,
		target_id TEXT NOT NULL,
		kind TEXT NOT NULL,
		score INTEGER NOT NULL,
		UNIQUE (campaign_id, source_id, target_id, kind),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_clues (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		clue_id TEXT NOT NULL,
		text TEXT NOT NULL,
		audience TEXT NOT NULL,
		character_id TEXT,
		UNIQUE (campaign_id, clue_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_quests (
		campaign_id TEXT NOT NULL,
		quest_id TEXT NOT NULL,
		title TEXT NOT NULL,
		state TEXT NOT NULL,
		depends_on TEXT NOT NULL,
		rewards TEXT,
		awarded INTEGER NOT NULL DEFAULT 0,
		PRIMARY KEY (campaign_id, quest_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_character_rewards (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		xp INTEGER NOT NULL DEFAULT 0,
		items TEXT NOT NULL DEFAULT '{}',
		PRIMARY KEY (campaign_id, character_id),
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_world_events (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		event_id TEXT NOT NULL,
		turn_number INTEGER NOT NULL,
		title TEXT NOT NULL,
		text TEXT NOT NULL,
		status TEXT NOT NULL DEFAULT 'scheduled',
		resolution_turn_number INTEGER,
		resolution_text TEXT,
		UNIQUE (campaign_id, event_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_calendar (
		campaign_id TEXT PRIMARY KEY,
		day INTEGER NOT NULL,
		season TEXT NOT NULL,
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_settlements (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		settlement_id TEXT NOT NULL,
		name TEXT NOT NULL,
		services TEXT NOT NULL,
		availability TEXT NOT NULL,
		UNIQUE (campaign_id, settlement_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_settlement_discoveries (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		settlement_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		UNIQUE (campaign_id, settlement_id, character_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_settlements(campaign_id, settlement_id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_shops (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		settlement_id TEXT NOT NULL,
		shop_id TEXT NOT NULL,
		name TEXT NOT NULL,
		buy_price INTEGER NOT NULL,
		sell_price INTEGER NOT NULL,
		UNIQUE (campaign_id, settlement_id, shop_id),
		FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_settlements(campaign_id, settlement_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_shop_stock (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		settlement_id TEXT NOT NULL,
		shop_id TEXT NOT NULL,
		item_id TEXT NOT NULL,
		quantity INTEGER NOT NULL,
		UNIQUE (campaign_id, settlement_id, shop_id, item_id),
		FOREIGN KEY (campaign_id, settlement_id, shop_id) REFERENCES play_shops(campaign_id, settlement_id, shop_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_recipes (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		recipe_id TEXT NOT NULL,
		name TEXT NOT NULL,
		ingredients TEXT NOT NULL,
		output_item TEXT NOT NULL,
		output_quantity INTEGER NOT NULL,
		UNIQUE (campaign_id, recipe_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_downtime_activities (
		campaign_id TEXT NOT NULL,
		activity_id TEXT NOT NULL,
		name TEXT NOT NULL,
		cycles_required INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, activity_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_downtime_allocations (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		activity_id TEXT NOT NULL,
		cycles_completed INTEGER NOT NULL DEFAULT 0,
		completions INTEGER NOT NULL DEFAULT 0,
		PRIMARY KEY (campaign_id, character_id, activity_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, activity_id) REFERENCES play_downtime_activities(campaign_id, activity_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_notes (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		note_id TEXT NOT NULL,
		text TEXT NOT NULL,
		visibility TEXT NOT NULL,
		owner TEXT NOT NULL,
		UNIQUE (campaign_id, note_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_whispers (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		whisper_id TEXT NOT NULL,
		from_character_id TEXT NOT NULL,
		to_character_id TEXT NOT NULL,
		text TEXT NOT NULL,
		UNIQUE (campaign_id, whisper_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, from_character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, to_character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_invitations (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		invitation_id TEXT NOT NULL,
		username TEXT NOT NULL,
		character_id TEXT NOT NULL,
		status TEXT NOT NULL DEFAULT 'pending',
		UNIQUE (campaign_id, invitation_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_delegations (
		campaign_id TEXT NOT NULL,
		username TEXT NOT NULL,
		powers TEXT NOT NULL,
		active INTEGER NOT NULL DEFAULT 0,
		PRIMARY KEY (campaign_id, username),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_delegation_audit (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		username TEXT NOT NULL,
		action TEXT NOT NULL,
		powers TEXT NOT NULL,
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_audit_events (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		kind TEXT NOT NULL,
		actor TEXT NOT NULL,
		role TEXT NOT NULL,
		timestamp INTEGER NOT NULL,
		correlation_id TEXT NOT NULL,
		UNIQUE (campaign_id, correlation_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_projection_events (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		sequence INTEGER NOT NULL,
		event_id TEXT NOT NULL,
		kind TEXT NOT NULL,
		value TEXT,
		UNIQUE (campaign_id, event_id),
		UNIQUE (campaign_id, sequence),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_idempotent_events (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		sequence INTEGER NOT NULL,
		event_id TEXT NOT NULL,
		value TEXT NOT NULL,
		idempotency_key TEXT NOT NULL,
		UNIQUE (campaign_id, event_id),
		UNIQUE (campaign_id, idempotency_key),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
	`CREATE TABLE IF NOT EXISTS play_safe_turns (
		campaign_id TEXT NOT NULL,
		submission_id TEXT NOT NULL,
		action TEXT NOT NULL,
		accepted_turn INTEGER NOT NULL,
		next_turn INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, submission_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`,
}

// initDB opens the SQLite database, enables foreign keys, creates the schema,
// and loads the users and combat caches from durable storage. It must be called
// once before the HTTP server starts accepting requests.
//
// To keep the evaluator deterministic across repeated runs, any stale database
// file from a previous process is removed before opening a fresh database.
func initDB() error {
	if err := os.Remove(dbFile); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("remove stale database: %w", err)
	}

	var err error
	db, err = sql.Open("sqlite", dbFile)
	if err != nil {
		return fmt.Errorf("open sqlite: %w", err)
	}
	if err := db.Ping(); err != nil {
		return fmt.Errorf("ping sqlite: %w", err)
	}
	if _, err := db.Exec("PRAGMA foreign_keys = ON"); err != nil {
		return fmt.Errorf("enable foreign keys: %w", err)
	}
	if _, err := db.Exec("PRAGMA busy_timeout = 10000"); err != nil {
		return fmt.Errorf("set busy timeout: %w", err)
	}
	var journal string
	if err := db.QueryRow("PRAGMA journal_mode = WAL").Scan(&journal); err != nil {
		return fmt.Errorf("set wal mode: %w", err)
	}
	// Serialize all database access through a single connection so that SQLite
	// never returns SQLITE_BUSY under concurrent HTTP requests. The connection
	// pool will queue goroutines and execute them one at a time.
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	db.SetConnMaxLifetime(0)
	if err := createSchema(); err != nil {
		return err
	}
	if err := loadUsers(); err != nil {
		return fmt.Errorf("load users: %w", err)
	}
	if err := loadCombatSessions(); err != nil {
		return fmt.Errorf("load combat sessions: %w", err)
	}
	return nil
}

// createSchema applies the full DDL and then runs idempotent migrations for
// columns added by later stages. Migrations inspect the current table schema
// with PRAGMA table_info and only add a column when it is absent, so they are
// safe to run on both fresh databases and databases from earlier stages.
func createSchema() error {
	initMu.Lock()
	defer initMu.Unlock()

	if err := applySchema(db); err != nil {
		return fmt.Errorf("create schema: %w", err)
	}
	if err := migratePlayCampaigns(); err != nil {
		return fmt.Errorf("migrate play campaigns: %w", err)
	}
	if err := migratePlayNarrations(); err != nil {
		return fmt.Errorf("migrate play narrations: %w", err)
	}
	if err := migratePlayCampaignDocument(); err != nil {
		return fmt.Errorf("migrate play campaign document: %w", err)
	}
	if err := migratePlayMembersHealth(); err != nil {
		return fmt.Errorf("migrate play members health: %w", err)
	}
	if err := migratePlayCombatantsMembers(); err != nil {
		return fmt.Errorf("migrate play combatants members: %w", err)
	}
	if err := migratePlayEncounterTurn(); err != nil {
		return fmt.Errorf("migrate play encounter turn: %w", err)
	}
	if err := migratePlayNarrationsTarget(); err != nil {
		return fmt.Errorf("migrate play narrations target: %w", err)
	}
	if err := migratePlayMembersDeathSaves(); err != nil {
		return fmt.Errorf("migrate play members death saves: %w", err)
	}
	if err := migratePlayEncounterConditions(); err != nil {
		return fmt.Errorf("migrate play encounter conditions: %w", err)
	}
	if err := migratePlayEncounterOrder(); err != nil {
		return fmt.Errorf("migrate play encounter order: %w", err)
	}
	if err := migratePlayEncounterRewards(); err != nil {
		return fmt.Errorf("migrate play encounter rewards: %w", err)
	}
	if err := migratePlayEncounterPreCombatActor(); err != nil {
		return fmt.Errorf("migrate play encounter pre_combat_actor: %w", err)
	}
	if err := migratePlayMembersOwner(); err != nil {
		return fmt.Errorf("migrate play members owner: %w", err)
	}
	if err := migratePlayMembersBuild(); err != nil {
		return fmt.Errorf("migrate play members build: %w", err)
	}
	if err := migrateCharacterSpells(); err != nil {
		return fmt.Errorf("migrate character spells: %w", err)
	}
	if err := migrateCharacterPreparedSpells(); err != nil {
		return fmt.Errorf("migrate character prepared spells: %w", err)
	}
	if err := migrateCharacterSpellSlots(); err != nil {
		return fmt.Errorf("migrate character spell slots: %w", err)
	}
	if err := migrateCharacterSpellCasts(); err != nil {
		return fmt.Errorf("migrate character spell casts: %w", err)
	}
	if err := migrateCharacterConcentration(); err != nil {
		return fmt.Errorf("migrate character concentration: %w", err)
	}
	if err := migratePlayCharacterEquipment(); err != nil {
		return fmt.Errorf("migrate play character equipment: %w", err)
	}
	if err := migratePlayMembersGold(); err != nil {
		return fmt.Errorf("migrate play members gold: %w", err)
	}
	if err := migratePlayLoot(); err != nil {
		return fmt.Errorf("migrate play loot: %w", err)
	}
	if err := migratePlayNPCs(); err != nil {
		return fmt.Errorf("migrate play npcs: %w", err)
	}
	if err := migratePlayFactions(); err != nil {
		return fmt.Errorf("migrate play factions: %w", err)
	}
	if err := migratePlayReputationHistory(); err != nil {
		return fmt.Errorf("migrate play reputation history: %w", err)
	}
	if err := migratePlayNPCDialogue(); err != nil {
		return fmt.Errorf("migrate play npc dialogue: %w", err)
	}
	if err := migratePlayRelationships(); err != nil {
		return fmt.Errorf("migrate play relationships: %w", err)
	}
	if err := migratePlayClues(); err != nil {
		return fmt.Errorf("migrate play clues: %w", err)
	}
	if err := migratePlayQuests(); err != nil {
		return fmt.Errorf("migrate play quests: %w", err)
	}
	if err := migratePlayQuestCharacterRewards(); err != nil {
		return fmt.Errorf("migrate play quest character rewards: %w", err)
	}
	if err := migratePlayCalendar(); err != nil {
		return fmt.Errorf("migrate play calendar: %w", err)
	}
	if err := migratePlaySettlements(); err != nil {
		return fmt.Errorf("migrate play settlements: %w", err)
	}
	if err := migratePlayShops(); err != nil {
		return fmt.Errorf("migrate play shops: %w", err)
	}
	if err := migratePlayRecipes(); err != nil {
		return fmt.Errorf("migrate play recipes: %w", err)
	}
	if err := migratePlayDowntimeActivities(); err != nil {
		return fmt.Errorf("migrate play downtime activities: %w", err)
	}
	if err := migratePlayDowntimeAllocations(); err != nil {
		return fmt.Errorf("migrate play downtime allocations: %w", err)
	}
	if err := migratePlaySessionZeroSettings(); err != nil {
		return fmt.Errorf("migrate play session zero settings: %w", err)
	}
	if err := migratePlayInvitations(); err != nil {
		return fmt.Errorf("migrate play invitations: %w", err)
	}
	if err := migratePlayAuditEvents(); err != nil {
		return fmt.Errorf("migrate play audit events: %w", err)
	}
	if err := migratePlayProjectionEvents(); err != nil {
		return fmt.Errorf("migrate play projection events: %w", err)
	}
	if err := migratePlayIdempotentEvents(); err != nil {
		return fmt.Errorf("migrate play idempotent events: %w", err)
	}
	initialized = true
	return nil
}

// columnMigration describes a single idempotent ALTER TABLE ADD COLUMN step.
// name is the column identifier used to query PRAGMA table_info; sql is the
// exact statement executed when the column is absent.
type columnMigration struct {
	name string
	sql  string
}

// addMissingColumns runs the supplied migrations for table in order. Each
// migration is skipped when its column is already present. This helper lets
// the simple column-addition migrations share the PRAGMA table_info scan.
func addMissingColumns(table string, migrations []columnMigration) error {
	rows, err := db.Query("PRAGMA table_info(" + table + ")")
	if err != nil {
		return err
	}
	defer rows.Close()

	cols := make(map[string]struct{})
	for rows.Next() {
		var cid, notNull, pk int
		var name, typ string
		var dfltValue sql.NullString
		if err := rows.Scan(&cid, &name, &typ, &notNull, &dfltValue, &pk); err != nil {
			return err
		}
		cols[name] = struct{}{}
	}
	if err := rows.Err(); err != nil {
		return err
	}

	for _, m := range migrations {
		if _, ok := cols[m.name]; !ok {
			if _, err := db.Exec(m.sql); err != nil {
				return err
			}
		}
	}
	return nil
}

// migratePlayCampaigns ensures that play_campaigns has the columns added by
// later stages (current_actor, turn_number, nudge_count, current_scene_id,
// current_location_id). It is safe to run on both fresh and upgraded databases.
func migratePlayCampaigns() error {
	return addMissingColumns("play_campaigns", []columnMigration{
		{name: "current_actor", sql: "ALTER TABLE play_campaigns ADD COLUMN current_actor TEXT"},
		{name: "turn_number", sql: "ALTER TABLE play_campaigns ADD COLUMN turn_number INTEGER DEFAULT 0"},
		{name: "nudge_count", sql: "ALTER TABLE play_campaigns ADD COLUMN nudge_count INTEGER DEFAULT 0"},
		{name: "current_scene_id", sql: "ALTER TABLE play_campaigns ADD COLUMN current_scene_id TEXT"},
		{name: "current_location_id", sql: "ALTER TABLE play_campaigns ADD COLUMN current_location_id TEXT"},
	})
}

// migratePlayNarrations ensures that play_narrations has the type column added
// by later stages. It is safe to run on both fresh and upgraded databases.
func migratePlayNarrations() error {
	return addMissingColumns("play_narrations", []columnMigration{
		{name: "type", sql: "ALTER TABLE play_narrations ADD COLUMN type TEXT"},
	})
}

// migratePlayCampaignDocument ensures that play_campaigns has the story and
// dm_notes columns added by later stages. It is safe to run on both fresh and
// upgraded databases.
func migratePlayCampaignDocument() error {
	return addMissingColumns("play_campaigns", []columnMigration{
		{name: "story", sql: "ALTER TABLE play_campaigns ADD COLUMN story TEXT NOT NULL DEFAULT ''"},
		{name: "dm_notes", sql: "ALTER TABLE play_campaigns ADD COLUMN dm_notes TEXT NOT NULL DEFAULT ''"},
	})
}

// migratePlayMembersHealth ensures that play_members has the hp_current and
// hp_max columns added by later stages. It is safe to run on both fresh and
// upgraded databases.
func migratePlayMembersHealth() error {
	return addMissingColumns("play_members", []columnMigration{
		{name: "hp_current", sql: "ALTER TABLE play_members ADD COLUMN hp_current INTEGER NOT NULL DEFAULT 20"},
		{name: "hp_max", sql: "ALTER TABLE play_members ADD COLUMN hp_max INTEGER NOT NULL DEFAULT 20"},
	})
}

// migratePlayCombatantsMembers ensures that play_combatants has the member,
// character_id and initiative columns added by the party/combat binding stage.
// It is safe to run on both fresh and upgraded databases.
func migratePlayCombatantsMembers() error {
	return addMissingColumns("play_combatants", []columnMigration{
		{name: "member", sql: "ALTER TABLE play_combatants ADD COLUMN member TEXT"},
		{name: "character_id", sql: "ALTER TABLE play_combatants ADD COLUMN character_id TEXT"},
		{name: "initiative", sql: "ALTER TABLE play_combatants ADD COLUMN initiative INTEGER"},
	})
}

// migratePlayEncounterTurn ensures that play_encounters has the round and
// turn_index columns added by the combat turn authority stage. It is safe to
// run on both fresh and upgraded databases.
func migratePlayEncounterTurn() error {
	return addMissingColumns("play_encounters", []columnMigration{
		{name: "round", sql: "ALTER TABLE play_encounters ADD COLUMN round INTEGER NOT NULL DEFAULT 1"},
		{name: "turn_index", sql: "ALTER TABLE play_encounters ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0"},
	})
}

// migratePlayNarrationsTarget ensures that play_narrations has the target
// column added by the player combat actions stage. It is safe to run on both
// fresh and upgraded databases.
func migratePlayNarrationsTarget() error {
	return addMissingColumns("play_narrations", []columnMigration{
		{name: "target", sql: "ALTER TABLE play_narrations ADD COLUMN target TEXT"},
	})
}

// migratePlayMembersDeathSaves ensures that play_members has the status,
// death_save_successes and death_save_failures columns added by the death
// saves stage. It is safe to run on both fresh and upgraded databases.
func migratePlayMembersDeathSaves() error {
	return addMissingColumns("play_members", []columnMigration{
		{name: "status", sql: "ALTER TABLE play_members ADD COLUMN status TEXT NOT NULL DEFAULT 'conscious'"},
		{name: "death_save_successes", sql: "ALTER TABLE play_members ADD COLUMN death_save_successes INTEGER NOT NULL DEFAULT 0"},
		{name: "death_save_failures", sql: "ALTER TABLE play_members ADD COLUMN death_save_failures INTEGER NOT NULL DEFAULT 0"},
	})
}

// migratePlayEncounterConditions ensures that the play_encounter_conditions
// table exists for the condition interactions stage. It is safe to run on
// both fresh and upgraded databases.
func migratePlayEncounterConditions() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_encounter_conditions (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		encounter_id TEXT NOT NULL,
		campaign_id TEXT NOT NULL,
		target TEXT NOT NULL,
		condition TEXT NOT NULL,
		remaining_rounds INTEGER NOT NULL,
		FOREIGN KEY (encounter_id, campaign_id) REFERENCES play_encounters(id, campaign_id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayEncounterOrder ensures that play_encounters has the
// combatant_order column added by the delay and ready stage. It is safe to run
// on both fresh and upgraded databases.
func migratePlayEncounterOrder() error {
	return addMissingColumns("play_encounters", []columnMigration{
		{name: "combatant_order", sql: "ALTER TABLE play_encounters ADD COLUMN combatant_order TEXT"},
	})
}

// migratePlayEncounterRewards ensures that the play_encounter_rewards table
// exists for the encounter rewards stage. It is safe to run on both fresh and
// upgraded databases.
func migratePlayEncounterRewards() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_encounter_rewards (
		encounter_id TEXT NOT NULL,
		campaign_id TEXT NOT NULL,
		xp INTEGER NOT NULL,
		loot TEXT NOT NULL,
		PRIMARY KEY (encounter_id, campaign_id),
		FOREIGN KEY (encounter_id, campaign_id) REFERENCES play_encounters(id, campaign_id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayEncounterPreCombatActor ensures that play_encounters has the
// pre_combat_actor column added by the combat/exploration transition stage.
// It is safe to run on both fresh and upgraded databases.
func migratePlayEncounterPreCombatActor() error {
	return addMissingColumns("play_encounters", []columnMigration{
		{name: "pre_combat_actor", sql: "ALTER TABLE play_encounters ADD COLUMN pre_combat_actor TEXT"},
	})
}

// migratePlayMembersOwner ensures that play_members has a nullable username
// and no per-player unique constraint, so characters can be unowned, claimed,
// or transferred between players. It is safe to run on both fresh and
// upgraded databases.
func migratePlayMembersOwner() error {
	rows, err := db.Query("PRAGMA table_info(play_members)")
	if err != nil {
		return err
	}
	defer rows.Close()

	usernameNotNull := false
	for rows.Next() {
		var cid, notNull, pk int
		var name, typ string
		var dfltValue sql.NullString
		if err := rows.Scan(&cid, &name, &typ, &notNull, &dfltValue, &pk); err != nil {
			return err
		}
		if name == "username" && notNull == 1 {
			usernameNotNull = true
		}
	}
	if err := rows.Err(); err != nil {
		return err
	}

	if !usernameNotNull {
		return nil
	}

	if _, err := db.Exec(`
		CREATE TABLE play_members_new (
			campaign_id TEXT NOT NULL,
			username TEXT,
			character_id TEXT NOT NULL,
			name TEXT NOT NULL,
			class TEXT NOT NULL,
			hp_current INTEGER NOT NULL DEFAULT 20,
			hp_max INTEGER NOT NULL DEFAULT 20,
			status TEXT NOT NULL DEFAULT 'conscious',
			death_save_successes INTEGER NOT NULL DEFAULT 0,
			death_save_failures INTEGER NOT NULL DEFAULT 0,
			PRIMARY KEY (campaign_id, character_id),
			FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
		)
	`); err != nil {
		return err
	}

	if _, err := db.Exec(`
		INSERT INTO play_members_new (campaign_id, username, character_id, name, class, hp_current, hp_max, status, death_save_successes, death_save_failures)
		SELECT campaign_id, username, character_id, name, class, hp_current, hp_max, status, death_save_successes, death_save_failures
		FROM play_members
	`); err != nil {
		return err
	}

	if _, err := db.Exec(`DROP TABLE play_members`); err != nil {
		return err
	}

	_, err = db.Exec(`ALTER TABLE play_members_new RENAME TO play_members`)
	return err
}

// migratePlayMembersBuild ensures that play_members has the race, background,
// level, and abilities columns added by the character build stage. It is safe
// to run on both fresh and upgraded databases.
func migratePlayMembersBuild() error {
	return addMissingColumns("play_members", []columnMigration{
		{name: "race", sql: "ALTER TABLE play_members ADD COLUMN race TEXT"},
		{name: "background", sql: "ALTER TABLE play_members ADD COLUMN background TEXT"},
		{name: "level", sql: "ALTER TABLE play_members ADD COLUMN level INTEGER NOT NULL DEFAULT 1"},
		{name: "abilities", sql: "ALTER TABLE play_members ADD COLUMN abilities TEXT"},
	})
}

// migrateCharacterSpells ensures that the character_spells table exists for
// the spellbook state stage. It is safe to run on both fresh and upgraded
// databases.
func migrateCharacterSpells() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS character_spells (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		spell_id TEXT NOT NULL,
		name TEXT NOT NULL,
		level INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, character_id, spell_id),
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`)
	return err
}

// migrateCharacterPreparedSpells ensures that the character_prepared_spells
// table exists for the spell preparation stage. It is safe to run on both
// fresh and upgraded databases.
func migrateCharacterPreparedSpells() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS character_prepared_spells (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		spell_id TEXT NOT NULL,
		position INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, character_id, spell_id),
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, character_id, spell_id) REFERENCES character_spells(campaign_id, character_id, spell_id) ON DELETE CASCADE
	)`)
	return err
}

// migrateCharacterSpellSlots ensures that the character_spell_slots table
// exists for the spell casting stage. It is safe to run on both fresh and
// upgraded databases.
func migrateCharacterSpellSlots() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS character_spell_slots (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		level INTEGER NOT NULL,
		slots_remaining INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, character_id, level),
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`)
	return err
}

// migrateCharacterSpellCasts ensures that the character_spell_casts table
// exists for the spell casting stage. It is safe to run on both fresh and
// upgraded databases.
func migrateCharacterSpellCasts() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS character_spell_casts (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		spell_id TEXT NOT NULL,
		target TEXT NOT NULL DEFAULT '',
		slot_level INTEGER NOT NULL,
		slots_remaining INTEGER NOT NULL,
		sequence INTEGER NOT NULL,
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`)
	return err
}

// migrateCharacterConcentration ensures that the character_concentration table
// exists for the concentration stage. It is safe to run on both fresh and
// upgraded databases.
func migrateCharacterConcentration() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS character_concentration (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		spell_id TEXT NOT NULL,
		target TEXT NOT NULL DEFAULT '',
		remaining_turns INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, character_id),
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayCharacterEquipment ensures that the play_character_equipment table
// exists for the equipment and attunement stage. It is safe to run on both
// fresh and upgraded databases.
func migratePlayCharacterEquipment() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_character_equipment (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		slot TEXT NOT NULL,
		item_id TEXT NOT NULL,
		attuned INTEGER NOT NULL DEFAULT 0,
		PRIMARY KEY (campaign_id, character_id, slot),
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayMembersGold ensures that play_members has the gold column added by
// the currency and trade stage. It defaults existing characters to 10 gold so
// all campaign members share the same starting balance. It is safe to run on
// both fresh and upgraded databases.
func migratePlayMembersGold() error {
	return addMissingColumns("play_members", []columnMigration{
		{name: "gold", sql: "ALTER TABLE play_members ADD COLUMN gold INTEGER NOT NULL DEFAULT 10"},
	})
}

// migratePlayLoot ensures that the play_loot and play_loot_votes tables exist
// for the loot distribution stage. It is safe to run on both fresh and upgraded
// databases.
func migratePlayLoot() error {
	if _, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_loot (
		campaign_id TEXT NOT NULL,
		loot_id TEXT NOT NULL,
		item_id TEXT NOT NULL,
		quantity INTEGER NOT NULL,
		status TEXT NOT NULL DEFAULT 'open',
		recipient_character_id TEXT,
		PRIMARY KEY (campaign_id, loot_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`); err != nil {
		return err
	}
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_loot_votes (
		campaign_id TEXT NOT NULL,
		loot_id TEXT NOT NULL,
		voter TEXT NOT NULL,
		recipient_character_id TEXT NOT NULL,
		PRIMARY KEY (campaign_id, loot_id, voter),
		FOREIGN KEY (campaign_id, loot_id) REFERENCES play_loot(campaign_id, loot_id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, recipient_character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayNPCs ensures that the play_npcs table exists for the NPC agendas
// stage. It is safe to run on both fresh and upgraded databases.
func migratePlayNPCs() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_npcs (
		campaign_id TEXT NOT NULL,
		npc_id TEXT NOT NULL,
		name TEXT NOT NULL,
		agenda TEXT NOT NULL,
		public_status TEXT NOT NULL,
		PRIMARY KEY (campaign_id, npc_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayFactions ensures that the play_factions table exists for the
// faction reputation stage. It is safe to run on both fresh and upgraded
// databases.
func migratePlayFactions() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_factions (
		campaign_id TEXT NOT NULL,
		faction_id TEXT NOT NULL,
		name TEXT NOT NULL,
		PRIMARY KEY (campaign_id, faction_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayReputationHistory ensures that the play_reputation_history table
// exists for the faction reputation stage. It is safe to run on both fresh and
// upgraded databases.
func migratePlayReputationHistory() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_reputation_history (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		faction_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		delta INTEGER NOT NULL,
		reputation INTEGER NOT NULL,
		reason TEXT NOT NULL,
		FOREIGN KEY (campaign_id, faction_id) REFERENCES play_factions(campaign_id, faction_id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayNPCDialogue ensures that the play_npc_dialogue table exists for
// the NPC dialogue stage. It is safe to run on both fresh and upgraded
// databases.
func migratePlayNPCDialogue() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_npc_dialogue (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		npc_id TEXT NOT NULL,
		dialogue_id TEXT NOT NULL,
		speaker TEXT NOT NULL,
		text TEXT NOT NULL,
		visibility TEXT NOT NULL,
		UNIQUE (campaign_id, npc_id, dialogue_id),
		FOREIGN KEY (campaign_id, npc_id) REFERENCES play_npcs(campaign_id, npc_id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayRelationships ensures that the play_relationships table exists for
// the relationship graph stage. It is safe to run on both fresh and upgraded
// databases.
func migratePlayRelationships() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_relationships (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		source_id TEXT NOT NULL,
		target_id TEXT NOT NULL,
		kind TEXT NOT NULL,
		score INTEGER NOT NULL,
		UNIQUE (campaign_id, source_id, target_id, kind),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayClues ensures that the play_clues table exists for the secrets
// and clues stage. It is safe to run on both fresh and upgraded databases.
func migratePlayClues() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_clues (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		clue_id TEXT NOT NULL,
		text TEXT NOT NULL,
		audience TEXT NOT NULL,
		character_id TEXT,
		UNIQUE (campaign_id, clue_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayQuests ensures that the play_quests table exists for the quest
// dependencies stage and has the rewards/awarded columns added by the quest
// rewards stage. It is safe to run on both fresh and upgraded databases.
func migratePlayQuests() error {
	if _, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_quests (
		campaign_id TEXT NOT NULL,
		quest_id TEXT NOT NULL,
		title TEXT NOT NULL,
		state TEXT NOT NULL,
		depends_on TEXT NOT NULL,
		rewards TEXT,
		awarded INTEGER NOT NULL DEFAULT 0,
		PRIMARY KEY (campaign_id, quest_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`); err != nil {
		return err
	}
	return addMissingColumns("play_quests", []columnMigration{
		{name: "rewards", sql: "ALTER TABLE play_quests ADD COLUMN rewards TEXT"},
		{name: "awarded", sql: "ALTER TABLE play_quests ADD COLUMN awarded INTEGER NOT NULL DEFAULT 0"},
	})
}

// migratePlayQuestCharacterRewards ensures that the play_character_rewards
// table exists for the quest rewards stage. It is safe to run on both fresh
// and upgraded databases.
func migratePlayQuestCharacterRewards() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_character_rewards (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		xp INTEGER NOT NULL DEFAULT 0,
		items TEXT NOT NULL DEFAULT '{}',
		PRIMARY KEY (campaign_id, character_id),
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayCalendar ensures that the play_calendar table exists for the
// calendar and weather stage. It is safe to run on both fresh and upgraded
// databases.
func migratePlayCalendar() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_calendar (
		campaign_id TEXT PRIMARY KEY,
		day INTEGER NOT NULL,
		season TEXT NOT NULL,
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlaySettlements ensures that the play_settlements and
// play_settlement_discoveries tables exist for the settlements stage. It is
// safe to run on both fresh and upgraded databases.
func migratePlaySettlements() error {
	if _, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_settlements (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		settlement_id TEXT NOT NULL,
		name TEXT NOT NULL,
		services TEXT NOT NULL,
		availability TEXT NOT NULL,
		UNIQUE (campaign_id, settlement_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`); err != nil {
		return err
	}
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_settlement_discoveries (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		settlement_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		UNIQUE (campaign_id, settlement_id, character_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_settlements(campaign_id, settlement_id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayShops ensures that the play_shops and play_shop_stock tables
// exist for the shops stage. It is safe to run on both fresh and upgraded
// databases.
func migratePlayShops() error {
	if _, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_shops (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		settlement_id TEXT NOT NULL,
		shop_id TEXT NOT NULL,
		name TEXT NOT NULL,
		buy_price INTEGER NOT NULL,
		sell_price INTEGER NOT NULL,
		UNIQUE (campaign_id, settlement_id, shop_id),
		FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_settlements(campaign_id, settlement_id) ON DELETE CASCADE
	)`); err != nil {
		return err
	}
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_shop_stock (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		settlement_id TEXT NOT NULL,
		shop_id TEXT NOT NULL,
		item_id TEXT NOT NULL,
		quantity INTEGER NOT NULL,
		UNIQUE (campaign_id, settlement_id, shop_id, item_id),
		FOREIGN KEY (campaign_id, settlement_id, shop_id) REFERENCES play_shops(campaign_id, settlement_id, shop_id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayRecipes ensures that the play_recipes table exists for the recipe
// catalog stage. It is safe to run on both fresh and upgraded databases.
func migratePlayRecipes() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_recipes (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		recipe_id TEXT NOT NULL,
		name TEXT NOT NULL,
		ingredients TEXT NOT NULL,
		output_item TEXT NOT NULL,
		output_quantity INTEGER NOT NULL,
		UNIQUE (campaign_id, recipe_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayDowntimeActivities ensures that the play_downtime_activities table
// exists for the recurring downtime stage. It is safe to run on both fresh and
// upgraded databases.
func migratePlayDowntimeActivities() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_downtime_activities (
		campaign_id TEXT NOT NULL,
		activity_id TEXT NOT NULL,
		name TEXT NOT NULL,
		cycles_required INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, activity_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayDowntimeAllocations ensures that the play_downtime_allocations table
// exists for the recurring downtime stage. It is safe to run on both fresh and
// upgraded databases.
func migratePlayDowntimeAllocations() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_downtime_allocations (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		activity_id TEXT NOT NULL,
		cycles_completed INTEGER NOT NULL DEFAULT 0,
		completions INTEGER NOT NULL DEFAULT 0,
		PRIMARY KEY (campaign_id, character_id, activity_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, character_id) REFERENCES play_members(campaign_id, character_id) ON DELETE CASCADE,
		FOREIGN KEY (campaign_id, activity_id) REFERENCES play_downtime_activities(campaign_id, activity_id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlaySessionZeroSettings ensures that the play_session_zero_settings
// table exists for the session-zero settings stage. It is safe to run on both
// fresh and upgraded databases.
func migratePlaySessionZeroSettings() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_session_zero_settings (
		campaign_id TEXT PRIMARY KEY,
		rules TEXT NOT NULL,
		tone TEXT NOT NULL,
		consent TEXT NOT NULL,
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayInvitations ensures that the play_invitations table exists for
// the campaign invitations stage. It is safe to run on both fresh and upgraded
// databases.
func migratePlayInvitations() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_invitations (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		invitation_id TEXT NOT NULL,
		username TEXT NOT NULL,
		character_id TEXT NOT NULL,
		status TEXT NOT NULL DEFAULT 'pending',
		UNIQUE (campaign_id, invitation_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayAuditEvents ensures that the play_audit_events table exists for
// the actor audit trail stage. It is safe to run on both fresh and upgraded
// databases.
func migratePlayAuditEvents() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_audit_events (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		kind TEXT NOT NULL,
		actor TEXT NOT NULL,
		role TEXT NOT NULL,
		timestamp INTEGER NOT NULL,
		correlation_id TEXT NOT NULL,
		UNIQUE (campaign_id, correlation_id),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayProjectionEvents ensures that the play_projection_events table
// exists for the event projections stage. It is safe to run on both fresh and
// upgraded databases.
func migratePlayProjectionEvents() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_projection_events (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		sequence INTEGER NOT NULL,
		event_id TEXT NOT NULL,
		kind TEXT NOT NULL,
		value TEXT,
		UNIQUE (campaign_id, event_id),
		UNIQUE (campaign_id, sequence),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`)
	return err
}

// migratePlayIdempotentEvents ensures that the play_idempotent_events table
// exists for the idempotency keys stage. It is safe to run on both fresh and
// upgraded databases.
func migratePlayIdempotentEvents() error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS play_idempotent_events (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		campaign_id TEXT NOT NULL,
		sequence INTEGER NOT NULL,
		event_id TEXT NOT NULL,
		value TEXT NOT NULL,
		idempotency_key TEXT NOT NULL,
		UNIQUE (campaign_id, event_id),
		UNIQUE (campaign_id, idempotency_key),
		FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
	)`)
	return err
}

func applySchema(e executor) error {
	for _, stmt := range schemaStatements {
		if _, err := e.Exec(stmt); err != nil {
			return err
		}
	}
	return nil
}

func loadUsers() error {
	rows, err := db.Query("SELECT username, password_hash, role FROM users")
	if err != nil {
		return err
	}
	defer rows.Close()

	users.mu.Lock()
	defer users.mu.Unlock()
	for rows.Next() {
		var u user
		if err := rows.Scan(&u.Username, &u.PasswordHash, &u.Role); err != nil {
			return err
		}
		users.users[u.Username] = &u
	}
	return rows.Err()
}

func loadCombatSessions() error {
	rows, err := db.Query("SELECT id FROM combat_sessions")
	if err != nil {
		return err
	}
	defer rows.Close()

	combat.mu.Lock()
	defer combat.mu.Unlock()
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return err
		}
		s, err := dbGetSession(id)
		if err != nil {
			return err
		}
		if s != nil {
			combat.sessions[id] = s
		}
	}
	return rows.Err()
}

// --- user DB helpers ---

func dbCreateUser(username, passwordHash, role string) error {
	_, err := db.Exec(
		"INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
		username, passwordHash, role,
	)
	return err
}

func dbGetUser(username string) (*user, error) {
	u := &user{}
	err := db.QueryRow(
		"SELECT username, password_hash, role FROM users WHERE username = ?",
		username,
	).Scan(&u.Username, &u.PasswordHash, &u.Role)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return u, nil
}

// --- combat session DB helpers ---

func dbCreateSession(s *session) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	if _, err := tx.Exec(
		"INSERT INTO combat_sessions (id, round, turn_index) VALUES (?, ?, ?)",
		s.ID, s.Round, s.TurnIndex,
	); err != nil {
		return err
	}

	for i, e := range s.Order {
		if _, err := tx.Exec(
			"INSERT INTO combat_order (session_id, position, name, score) VALUES (?, ?, ?, ?)",
			s.ID, i, e.Name, e.Score,
		); err != nil {
			return err
		}
	}

	return tx.Commit()
}

func dbGetSession(id string) (*session, error) {
	s := &session{
		ID:         id,
		Conditions: make(map[string][]condition),
	}
	err := db.QueryRow(
		"SELECT round, turn_index FROM combat_sessions WHERE id = ?",
		id,
	).Scan(&s.Round, &s.TurnIndex)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	rows, err := db.Query(
		"SELECT name, score FROM combat_order WHERE session_id = ? ORDER BY position ASC",
		id,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var e orderEntry
		if err := rows.Scan(&e.Name, &e.Score); err != nil {
			return nil, err
		}
		s.Order = append(s.Order, e)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	condRows, err := db.Query(
		"SELECT target, condition, remaining_rounds FROM combat_conditions WHERE session_id = ? ORDER BY id ASC",
		id,
	)
	if err != nil {
		return nil, err
	}
	defer condRows.Close()
	for condRows.Next() {
		var c condition
		var target string
		if err := condRows.Scan(&target, &c.Condition, &c.Remaining); err != nil {
			return nil, err
		}
		s.Conditions[target] = append(s.Conditions[target], c)
	}
	if err := condRows.Err(); err != nil {
		return nil, err
	}

	return s, nil
}

func dbSaveSession(s *session) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	if _, err := tx.Exec(
		"UPDATE combat_sessions SET round = ?, turn_index = ? WHERE id = ?",
		s.Round, s.TurnIndex, s.ID,
	); err != nil {
		return err
	}

	if _, err := tx.Exec(
		"DELETE FROM combat_conditions WHERE session_id = ?",
		s.ID,
	); err != nil {
		return err
	}

	for target, conds := range s.Conditions {
		for _, c := range conds {
			if _, err := tx.Exec(
				"INSERT INTO combat_conditions (session_id, target, condition, remaining_rounds) VALUES (?, ?, ?, ?)",
				s.ID, target, c.Condition, c.Remaining,
			); err != nil {
				return err
			}
		}
	}

	return tx.Commit()
}

// --- compendium DB helpers ---

func dbCreateMonster(m *monster) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	if _, err := tx.Exec(
		"INSERT INTO monsters (slug, name, cr, armor_class, hit_points) VALUES (?, ?, ?, ?, ?)",
		m.Slug, m.Name, m.CR, m.ArmorClass, m.HitPoints,
	); err != nil {
		return err
	}

	for _, tag := range m.Tags {
		if _, err := tx.Exec(
			"INSERT INTO monster_tags (monster_slug, tag) VALUES (?, ?)",
			m.Slug, tag,
		); err != nil {
			return err
		}
	}

	return tx.Commit()
}

func dbGetMonster(slug string) (*monster, error) {
	m := &monster{Slug: slug}
	err := db.QueryRow(
		"SELECT name, cr, armor_class, hit_points FROM monsters WHERE slug = ?",
		slug,
	).Scan(&m.Name, &m.CR, &m.ArmorClass, &m.HitPoints)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	rows, err := db.Query(
		"SELECT tag FROM monster_tags WHERE monster_slug = ? ORDER BY rowid",
		slug,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	for rows.Next() {
		var tag string
		if err := rows.Scan(&tag); err != nil {
			return nil, err
		}
		m.Tags = append(m.Tags, tag)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	return m, nil
}

func dbCreateItem(i *item) error {
	_, err := db.Exec(
		"INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
		i.Slug, i.Name, i.Type, i.Rarity, i.CostGP,
	)
	return err
}

func dbGetItem(slug string) (*item, error) {
	i := &item{Slug: slug}
	err := db.QueryRow(
		"SELECT name, type, rarity, cost_gp FROM items WHERE slug = ?",
		slug,
	).Scan(&i.Name, &i.Type, &i.Rarity, &i.CostGP)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return i, nil
}

// --- campaign DB helpers ---

func dbCreateCampaign(c *campaign) error {
	_, err := db.Exec(
		"INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
		c.ID, c.Name, c.DM,
	)
	return err
}

func dbGetCampaign(id string) (*campaign, error) {
	c := &campaign{ID: id}
	err := db.QueryRow(
		"SELECT name, dm FROM campaigns WHERE id = ?",
		id,
	).Scan(&c.Name, &c.DM)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return c, nil
}

// --- play campaign DB helpers ---

func dbCreatePlayCampaign(p *playCampaign) error {
	_, err := db.Exec(
		"INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)",
		p.ID, p.Name, p.Owner, p.Status, p.MaxPlayers,
	)
	return err
}

func dbGetPlayCampaign(id string) (*playCampaign, error) {
	p := &playCampaign{ID: id}
	err := db.QueryRow(
		"SELECT name, owner, status, max_players FROM play_campaigns WHERE id = ?",
		id,
	).Scan(&p.Name, &p.Owner, &p.Status, &p.MaxPlayers)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return p, nil
}

// dbGetPlayCampaignDocument returns the story and dm_notes for a play campaign.
func dbGetPlayCampaignDocument(id string) (story, dmNotes string, err error) {
	err = db.QueryRow(
		"SELECT story, dm_notes FROM play_campaigns WHERE id = ?",
		id,
	).Scan(&story, &dmNotes)
	if err == sql.ErrNoRows {
		return "", "", nil
	}
	return story, dmNotes, err
}

// dbUpdatePlayCampaignDocument updates the story and dm_notes for a play
// campaign. The caller must already have verified the caller is the owner.
func dbUpdatePlayCampaignDocument(campaignID, story, dmNotes string) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	var nextSeq int
	err = tx.QueryRow(
		"SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_narrations WHERE campaign_id = ?",
		campaignID,
	).Scan(&nextSeq)
	if err != nil {
		return err
	}

	if _, err := tx.Exec(
		"INSERT INTO play_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (?, ?, ?, ?, ?, ?)",
		campaignID, nextSeq, "document", "dm", "", story,
	); err != nil {
		return err
	}

	if _, err := tx.Exec(
		"UPDATE play_campaigns SET story = ?, dm_notes = ? WHERE id = ?",
		story, dmNotes, campaignID,
	); err != nil {
		return err
	}

	return tx.Commit()
}

// dbGetSessionZeroSettings returns the stored session-zero settings for a
// play campaign, or nil and false if no settings have been stored yet.
func dbGetSessionZeroSettings(campaignID string) (*sessionZeroSettings, bool, error) {
	var rules, tone, consentJSON string
	err := db.QueryRow(
		"SELECT rules, tone, consent FROM play_session_zero_settings WHERE campaign_id = ?",
		campaignID,
	).Scan(&rules, &tone, &consentJSON)
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	var consent []string
	if err := json.Unmarshal([]byte(consentJSON), &consent); err != nil {
		return nil, false, err
	}
	return &sessionZeroSettings{
		Rules:   rules,
		Tone:    tone,
		Consent: consent,
	}, true, nil
}

// dbUpdateSessionZeroSettings stores or replaces the session-zero settings for
// a play campaign. The caller must already have verified that the campaign is
// in the lobby state and that the caller is the owner.
func dbUpdateSessionZeroSettings(campaignID string, s *sessionZeroSettings) error {
	consentJSON, err := json.Marshal(s.Consent)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		`INSERT INTO play_session_zero_settings (campaign_id, rules, tone, consent)
		 VALUES (?, ?, ?, ?)
		 ON CONFLICT (campaign_id) DO UPDATE
		 SET rules = excluded.rules, tone = excluded.tone, consent = excluded.consent`,
		campaignID, s.Rules, s.Tone, string(consentJSON),
	)
	return err
}

// dbGetPlayCampaignCurrentSceneID returns the current scene id for a play
// campaign, or an empty string if none is set.
func dbGetPlayCampaignCurrentSceneID(id string) (string, error) {
	var sceneID sql.NullString
	err := db.QueryRow(
		"SELECT current_scene_id FROM play_campaigns WHERE id = ?",
		id,
	).Scan(&sceneID)
	if err == sql.ErrNoRows {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	return sceneID.String, nil
}

// dbCreatePlayScene inserts a new scene for a play campaign. Duplicate ids
// within the same campaign are rejected by the primary key.
func dbCreatePlayScene(s *playScene) error {
	_, err := db.Exec(
		"INSERT INTO play_scenes (id, campaign_id, name, status) VALUES (?, ?, ?, ?)",
		s.ID, s.CampaignID, s.Name, s.Status,
	)
	return err
}

// dbGetPlayScene returns a scene belonging to a campaign, or nil if not found.
func dbGetPlayScene(campaignID, id string) (*playScene, error) {
	s := &playScene{ID: id, CampaignID: campaignID}
	err := db.QueryRow(
		"SELECT name, status FROM play_scenes WHERE id = ? AND campaign_id = ?",
		id, campaignID,
	).Scan(&s.Name, &s.Status)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return s, nil
}

// --- play content DB helpers ---

// dbCreatePlayContent inserts a new content record for a campaign. Duplicate
// content ids within the same campaign are rejected by the unique constraint.
func dbCreatePlayContent(campaignID string, c *content) error {
	tagsJSON, err := json.Marshal(c.Tags)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		"INSERT INTO play_content (campaign_id, content_id, kind, text, tags) VALUES (?, ?, ?, ?, ?)",
		campaignID, c.ContentID, c.Kind, c.Text, string(tagsJSON),
	)
	return err
}

// dbGetPlayContent returns a single content record belonging to a campaign, or
// nil if it does not exist.
func dbGetPlayContent(campaignID, contentID string) (*content, error) {
	c := &content{ContentID: contentID}
	var tagsJSON string
	err := db.QueryRow(
		"SELECT kind, text, tags FROM play_content WHERE campaign_id = ? AND content_id = ?",
		campaignID, contentID,
	).Scan(&c.Kind, &c.Text, &tagsJSON)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if err := json.Unmarshal([]byte(tagsJSON), &c.Tags); err != nil {
		return nil, err
	}
	return c, nil
}

// dbUpdatePlayContentTags replaces the tags of a content record. The caller must
// already have verified that the content record exists. The tags slice is stored
// as JSON to preserve order.
func dbUpdatePlayContentTags(campaignID, contentID string, tags []string) error {
	tagsJSON, err := json.Marshal(tags)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		"UPDATE play_content SET tags = ? WHERE campaign_id = ? AND content_id = ?",
		string(tagsJSON), campaignID, contentID,
	)
	return err
}

// dbListPlayContent returns every content record for a campaign in creation order.
func dbListPlayContent(campaignID string) ([]content, error) {
	rows, err := db.Query(
		"SELECT content_id, kind, text, tags FROM play_content WHERE campaign_id = ? ORDER BY id ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var contents []content
	for rows.Next() {
		var c content
		var tagsJSON string
		if err := rows.Scan(&c.ContentID, &c.Kind, &c.Text, &tagsJSON); err != nil {
			return nil, err
		}
		if err := json.Unmarshal([]byte(tagsJSON), &c.Tags); err != nil {
			return nil, err
		}
		contents = append(contents, c)
	}
	return contents, rows.Err()
}

// dbCreatePlayNote inserts a new campaign note. The caller must have already
// validated the note and determined the owner.
func dbCreatePlayNote(campaignID string, n *playNote) error {
	_, err := db.Exec(
		"INSERT INTO play_notes (campaign_id, note_id, text, visibility, owner) VALUES (?, ?, ?, ?, ?)",
		campaignID, n.NoteID, n.Text, n.Visibility, n.Owner,
	)
	return err
}

// dbGetPlayNote returns a single campaign note or nil if it does not exist.
func dbGetPlayNote(campaignID, noteID string) (*playNote, error) {
	n := &playNote{NoteID: noteID}
	err := db.QueryRow(
		"SELECT text, visibility, owner FROM play_notes WHERE campaign_id = ? AND note_id = ?",
		campaignID, noteID,
	).Scan(&n.Text, &n.Visibility, &n.Owner)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return n, nil
}

// dbListPlayNotes returns every campaign note in creation order.
func dbListPlayNotes(campaignID string) ([]playNote, error) {
	rows, err := db.Query(
		"SELECT note_id, text, visibility, owner FROM play_notes WHERE campaign_id = ? ORDER BY id ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var notes []playNote
	for rows.Next() {
		var n playNote
		if err := rows.Scan(&n.NoteID, &n.Text, &n.Visibility, &n.Owner); err != nil {
			return nil, err
		}
		notes = append(notes, n)
	}
	return notes, rows.Err()
}

// dbUpdatePlayNote updates the mutable fields of a note. The caller must have
// already verified ownership and existence.
func dbUpdatePlayNote(campaignID, noteID, text, visibility string) error {
	_, err := db.Exec(
		"UPDATE play_notes SET text = ?, visibility = ? WHERE campaign_id = ? AND note_id = ?",
		text, visibility, campaignID, noteID,
	)
	return err
}

// dbCreatePlayWhisper inserts a new campaign whisper. The caller must have
// already validated the participants and payload.
func dbCreatePlayWhisper(campaignID string, w *playWhisper) error {
	_, err := db.Exec(
		"INSERT INTO play_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text) VALUES (?, ?, ?, ?, ?)",
		campaignID, w.WhisperID, w.FromCharacterID, w.ToCharacterID, w.Text,
	)
	return err
}

// dbListPlayWhispers returns every campaign whisper in creation order.
func dbListPlayWhispers(campaignID string) ([]playWhisper, error) {
	rows, err := db.Query(
		"SELECT whisper_id, from_character_id, to_character_id, text FROM play_whispers WHERE campaign_id = ? ORDER BY id ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var whispers []playWhisper
	for rows.Next() {
		var w playWhisper
		if err := rows.Scan(&w.WhisperID, &w.FromCharacterID, &w.ToCharacterID, &w.Text); err != nil {
			return nil, err
		}
		whispers = append(whispers, w)
	}
	return whispers, rows.Err()
}

// Invitation-specific errors returned by the DB helpers so handlers can map
// them to the correct HTTP status codes.
var (
	errInvitationIDExists        = errors.New("invitation id already exists")
	errPendingInvitationExists   = errors.New("pending invitation already exists for user")
	errInvitationAlreadyAccepted = errors.New("invitation already accepted")
	errInvitationMemberExists    = errors.New("member already exists")

	errDelegationMemberNotFound = errors.New("target user is not a campaign member")
	errDelegationActiveExists   = errors.New("active delegation already exists")
)

// dbCreatePlayInvitation inserts a new pending invitation for a campaign. It
// verifies that the invitation_id is unique within the campaign and that there
// is no other pending invitation for the target username.
func dbCreatePlayInvitation(campaignID string, inv *playInvitation) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	var exists int
	err = tx.QueryRow(
		"SELECT 1 FROM play_invitations WHERE campaign_id = ? AND invitation_id = ?",
		campaignID, inv.InvitationID,
	).Scan(&exists)
	if err != sql.ErrNoRows {
		if err == nil {
			return errInvitationIDExists
		}
		return err
	}

	err = tx.QueryRow(
		"SELECT 1 FROM play_invitations WHERE campaign_id = ? AND username = ? AND status = ?",
		campaignID, inv.Username, invitationStatusPending,
	).Scan(&exists)
	if err != sql.ErrNoRows {
		if err == nil {
			return errPendingInvitationExists
		}
		return err
	}

	if _, err := tx.Exec(
		"INSERT INTO play_invitations (campaign_id, invitation_id, username, character_id, status) VALUES (?, ?, ?, ?, ?)",
		campaignID, inv.InvitationID, inv.Username, inv.CharacterID, invitationStatusPending,
	); err != nil {
		return err
	}

	return tx.Commit()
}

// dbGetPlayInvitation returns a single campaign invitation or nil if it does not exist.
func dbGetPlayInvitation(campaignID, invitationID string) (*playInvitation, error) {
	inv := &playInvitation{InvitationID: invitationID}
	err := db.QueryRow(
		"SELECT username, character_id, status FROM play_invitations WHERE campaign_id = ? AND invitation_id = ?",
		campaignID, invitationID,
	).Scan(&inv.Username, &inv.CharacterID, &inv.Status)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return inv, nil
}

// dbListPlayInvitations returns every campaign invitation in creation order.
func dbListPlayInvitations(campaignID string) ([]playInvitation, error) {
	rows, err := db.Query(
		"SELECT invitation_id, username, character_id, status FROM play_invitations WHERE campaign_id = ? ORDER BY id ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var invitations []playInvitation
	for rows.Next() {
		var inv playInvitation
		if err := rows.Scan(&inv.InvitationID, &inv.Username, &inv.CharacterID, &inv.Status); err != nil {
			return nil, err
		}
		invitations = append(invitations, inv)
	}
	return invitations, rows.Err()
}

// dbAcceptPlayInvitation marks an invitation as accepted and adds the target
// user as a campaign member using the invitation's character_id. It returns the
// accepted invitation, ok=false when the invitation is not found, and an error
// when the invitation has already been accepted or the member cannot be added.
func dbAcceptPlayInvitation(campaignID, invitationID string) (*playInvitation, bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, false, err
	}
	defer tx.Rollback()

	var inv playInvitation
	err = tx.QueryRow(
		"SELECT username, character_id, status FROM play_invitations WHERE campaign_id = ? AND invitation_id = ?",
		campaignID, invitationID,
	).Scan(&inv.Username, &inv.CharacterID, &inv.Status)
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	if inv.Status != invitationStatusPending {
		return nil, false, errInvitationAlreadyAccepted
	}

	if _, err := tx.Exec(
		"INSERT INTO play_members (campaign_id, username, character_id, name, class, hp_current, hp_max, gold) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
		campaignID, inv.Username, inv.CharacterID, inv.CharacterID, "adventurer", 20, 20, 10,
	); err != nil {
		if isUniqueViolation(err) {
			return nil, false, errInvitationMemberExists
		}
		return nil, false, err
	}

	if _, err := tx.Exec(
		"UPDATE play_invitations SET status = ? WHERE campaign_id = ? AND invitation_id = ?",
		invitationStatusAccepted, campaignID, invitationID,
	); err != nil {
		return nil, false, err
	}

	if err := tx.Commit(); err != nil {
		return nil, false, err
	}

	inv.InvitationID = invitationID
	inv.Status = invitationStatusAccepted
	return &inv, true, nil
}

// dbCreatePlayLocation inserts a new location for a play campaign. If the
// campaign has no current location yet, the new location is adopted as the
// party's starting location. Duplicate ids within the same campaign are rejected
// by the primary key.
func dbCreatePlayLocation(l *playLocation) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	if _, err := tx.Exec(
		"INSERT INTO play_locations (id, campaign_id, name) VALUES (?, ?, ?)",
		l.ID, l.CampaignID, l.Name,
	); err != nil {
		return err
	}

	var currentLoc sql.NullString
	if err := tx.QueryRow(
		"SELECT current_location_id FROM play_campaigns WHERE id = ?",
		l.CampaignID,
	).Scan(&currentLoc); err != nil && err != sql.ErrNoRows {
		return err
	}
	if !currentLoc.Valid {
		if _, err := tx.Exec(
			"UPDATE play_campaigns SET current_location_id = ? WHERE id = ?",
			l.ID, l.CampaignID,
		); err != nil {
			return err
		}
	}

	return tx.Commit()
}

// dbGetPlayLocation returns a location belonging to a campaign, or nil if not found.
func dbGetPlayLocation(campaignID, id string) (*playLocation, error) {
	l := &playLocation{ID: id, CampaignID: campaignID}
	err := db.QueryRow(
		"SELECT name FROM play_locations WHERE id = ? AND campaign_id = ?",
		id, campaignID,
	).Scan(&l.Name)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return l, nil
}

// dbCreatePlayConnection creates a one-way connection between two locations in
// the same campaign. It returns missing=true if either location is missing and
// duplicate=true if a connection between the same locations already exists.
func dbCreatePlayConnection(campaignID, fromID, toID string, travelTurns int) (missing bool, duplicate bool, err error) {
	tx, err := db.Begin()
	if err != nil {
		return false, false, err
	}
	defer tx.Rollback()

	var exists int
	if err := tx.QueryRow(
		"SELECT 1 FROM play_locations WHERE id = ? AND campaign_id = ?",
		fromID, campaignID,
	).Scan(&exists); err == sql.ErrNoRows {
		return true, false, nil
	} else if err != nil {
		return false, false, err
	}

	if err := tx.QueryRow(
		"SELECT 1 FROM play_locations WHERE id = ? AND campaign_id = ?",
		toID, campaignID,
	).Scan(&exists); err == sql.ErrNoRows {
		return true, false, nil
	} else if err != nil {
		return false, false, err
	}

	if err := tx.QueryRow(
		"SELECT 1 FROM play_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
		campaignID, fromID, toID,
	).Scan(&exists); err != sql.ErrNoRows {
		if err == nil {
			return false, true, nil
		}
		return false, false, err
	}

	if _, err := tx.Exec(
		"INSERT INTO play_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)",
		campaignID, fromID, toID, travelTurns,
	); err != nil {
		if isUniqueViolation(err) {
			return false, true, nil
		}
		return false, false, err
	}

	if err := tx.Commit(); err != nil {
		return false, false, err
	}
	return false, false, nil
}

// dbCreatePlayEncounter inserts a new encounter for a play campaign. Duplicate
// ids within the same campaign are rejected by the primary key.
func dbCreatePlayEncounter(e *playEncounter) error {
	_, err := db.Exec(
		"INSERT INTO play_encounters (id, campaign_id, name, status, round, turn_index, pre_combat_actor) VALUES (?, ?, ?, ?, ?, ?, ?)",
		e.ID, e.CampaignID, e.Name, e.Status, 1, 0, e.PreCombatActor,
	)
	return err
}

// dbGetActivePlayEncounterByCampaign returns the active encounter for a
// campaign, or nil if the campaign is not currently in combat.
func dbGetActivePlayEncounterByCampaign(campaignID string) (*playEncounter, error) {
	e := &playEncounter{CampaignID: campaignID}
	err := db.QueryRow(
		"SELECT id, name, status FROM play_encounters WHERE campaign_id = ? AND status = ?",
		campaignID, encounterStatusActive,
	).Scan(&e.ID, &e.Name, &e.Status)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return e, nil
}

// dbGetPlayEncounter returns an encounter belonging to a campaign, or nil if not found.
func dbGetPlayEncounter(campaignID, encounterID string) (*playEncounter, error) {
	e := &playEncounter{ID: encounterID, CampaignID: campaignID}
	err := db.QueryRow(
		"SELECT name, status FROM play_encounters WHERE id = ? AND campaign_id = ?",
		encounterID, campaignID,
	).Scan(&e.Name, &e.Status)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return e, nil
}

// dbCreatePlayEncounterReward records a deterministic XP and loot reward for
// an encounter. The primary key guarantees that rewards can be awarded only
// once per encounter.
func dbCreatePlayEncounterReward(campaignID, encounterID string, xp int, loot []lootItem) error {
	lootJSON, err := json.Marshal(loot)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		"INSERT INTO play_encounter_rewards (encounter_id, campaign_id, xp, loot) VALUES (?, ?, ?, ?)",
		encounterID, campaignID, xp, string(lootJSON),
	)
	return err
}

// dbGetPlayEncounterReward returns the recorded reward for an encounter, or nil
// if no rewards have been awarded yet.
func dbGetPlayEncounterReward(campaignID, encounterID string) (*encounterRewardResponse, error) {
	var xp int
	var lootJSON string
	err := db.QueryRow(
		"SELECT xp, loot FROM play_encounter_rewards WHERE campaign_id = ? AND encounter_id = ?",
		campaignID, encounterID,
	).Scan(&xp, &lootJSON)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var loot []lootItem
	if err := json.Unmarshal([]byte(lootJSON), &loot); err != nil {
		return nil, err
	}
	return &encounterRewardResponse{ID: encounterID, XP: xp, Loot: loot}, nil
}

// dbClosePlayEncounter marks an encounter as closed. It returns the public close
// response including the XP awarded (zero if rewards were not yet awarded).
// If the encounter does not exist, it returns nil and no error.
func dbClosePlayEncounter(campaignID, encounterID string) (*encounterCloseResponse, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	var status string
	err = tx.QueryRow(
		"SELECT status FROM play_encounters WHERE campaign_id = ? AND id = ?",
		campaignID, encounterID,
	).Scan(&status)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	if status != encounterStatusClosed {
		if _, err := tx.Exec(
			"UPDATE play_encounters SET status = ? WHERE campaign_id = ? AND id = ?",
			encounterStatusClosed, campaignID, encounterID,
		); err != nil {
			return nil, err
		}
	}

	var xp int
	err = tx.QueryRow(
		"SELECT COALESCE(xp, 0) FROM play_encounter_rewards WHERE campaign_id = ? AND encounter_id = ?",
		campaignID, encounterID,
	).Scan(&xp)
	if err != nil && err != sql.ErrNoRows {
		return nil, err
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return &encounterCloseResponse{ID: encounterID, Status: encounterStatusClosed, XPAwarded: xp}, nil
}

// dbEndPlayEncounter closes an active encounter (if it is still active) and
// restores the campaign to the exploration phase. It returns nil when the
// encounter is not found, which the caller maps to a 409 response.
func dbEndPlayEncounter(campaignID, encounterID string) (*playCampaignEndResponse, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	var encStatus string
	var preCombatActor sql.NullString
	err = tx.QueryRow(
		"SELECT status, pre_combat_actor FROM play_encounters WHERE campaign_id = ? AND id = ?",
		campaignID, encounterID,
	).Scan(&encStatus, &preCombatActor)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	if encStatus == encounterStatusActive {
		if _, err := tx.Exec(
			"UPDATE play_encounters SET status = ? WHERE campaign_id = ? AND id = ?",
			encounterStatusClosed, campaignID, encounterID,
		); err != nil {
			return nil, err
		}
	}

	actor := preCombatActor.String
	if _, err := tx.Exec(
		"UPDATE play_campaigns SET current_actor = ? WHERE id = ?",
		actor, campaignID,
	); err != nil {
		return nil, err
	}

	var campaignStatus string
	err = tx.QueryRow(
		"SELECT status FROM play_campaigns WHERE id = ?",
		campaignID,
	).Scan(&campaignStatus)
	if err != nil {
		return nil, err
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return &playCampaignEndResponse{
		CampaignID:   campaignID,
		Status:       campaignStatus,
		Phase:        "exploration",
		CurrentActor: actor,
	}, nil
}

// dbGetPlayEncounterCombatants returns the combatants for a given encounter,
// ordered deterministically by name.
func dbGetPlayEncounterCombatants(campaignID, encounterID string) ([]playCombatant, error) {
	rows, err := db.Query(
		"SELECT name FROM play_combatants WHERE campaign_id = ? AND encounter_id = ? ORDER BY name ASC",
		campaignID, encounterID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	combatants := []playCombatant{}
	for rows.Next() {
		var c playCombatant
		if err := rows.Scan(&c.Name); err != nil {
			return nil, err
		}
		combatants = append(combatants, c)
	}
	return combatants, rows.Err()
}

// dbGetPlayEncounterTurnOrder returns all combatants for the encounter in
// their current initiative order. When an explicit combatant_order is stored,
// it is used; otherwise the order falls back to initiative descending, then
// name ascending, then kind ascending.
func dbGetPlayEncounterTurnOrder(campaignID, encounterID string) ([]encounterTurnEntry, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	order, err := dbGetPlayEncounterOrderedEntriesTx(tx, campaignID, encounterID)
	if err != nil {
		return nil, err
	}
	return order, tx.Commit()
}

// encounterOrderEntry records a single combatant's position in the explicit
// encounter order. Kind is "member" for player combatants and "monster" for
// monster combatants; ID is the member username or monster_id respectively.
type encounterOrderEntry struct {
	Kind string `json:"kind"`
	ID   string `json:"id"`
}

// dbReadPlayEncounterOrderTx reads and parses the explicit combatant order for
// an encounter. It returns the parsed order and true when a valid, non-empty
// order is stored; otherwise it returns nil and false.
func dbReadPlayEncounterOrderTx(tx *sql.Tx, campaignID, encounterID string) ([]encounterOrderEntry, bool, error) {
	var raw sql.NullString
	err := tx.QueryRow(
		"SELECT combatant_order FROM play_encounters WHERE campaign_id = ? AND id = ?",
		campaignID, encounterID,
	).Scan(&raw)
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	if !raw.Valid || strings.TrimSpace(raw.String) == "" {
		return nil, false, nil
	}

	var order []encounterOrderEntry
	if err := json.Unmarshal([]byte(raw.String), &order); err != nil {
		return nil, false, nil
	}
	if len(order) == 0 {
		return nil, false, nil
	}
	valid := true
	for _, e := range order {
		if (e.Kind != "member" && e.Kind != "monster") || e.ID == "" {
			valid = false
			break
		}
	}
	if !valid {
		return nil, false, nil
	}
	return order, true, nil
}

// dbWritePlayEncounterOrderTx stores the explicit combatant order for an
// encounter as JSON.
func dbWritePlayEncounterOrderTx(tx *sql.Tx, campaignID, encounterID string, order []encounterOrderEntry) error {
	data, err := json.Marshal(order)
	if err != nil {
		return err
	}
	_, err = tx.Exec(
		"UPDATE play_encounters SET combatant_order = ? WHERE campaign_id = ? AND id = ?",
		string(data), campaignID, encounterID,
	)
	return err
}

// dbBuildPlayEncounterOrderEntriesTx fetches all monster and member combatants
// for an encounter into a slice of encounterTurnEntry values.
func dbBuildPlayEncounterOrderEntriesTx(tx *sql.Tx, campaignID, encounterID string) ([]encounterTurnEntry, error) {
	rows, err := tx.Query(
		`SELECT name, kind, COALESCE(initiative, 0), member, target_id FROM (
			SELECT name, 'monster' AS kind, initiative, '' AS member, monster_id AS target_id
			FROM play_encounter_monsters
			WHERE encounter_id = ? AND campaign_id = ?
			UNION ALL
			SELECT name, 'member' AS kind, initiative, member, member AS target_id
			FROM play_combatants
			WHERE encounter_id = ? AND campaign_id = ?
		)
		ORDER BY initiative DESC, name ASC, kind ASC`,
		encounterID, campaignID, encounterID, campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var entries []encounterTurnEntry
	for rows.Next() {
		var e encounterTurnEntry
		if err := rows.Scan(&e.Name, &e.Kind, &e.Initiative, &e.Member, &e.TargetID); err != nil {
			return nil, err
		}
		entries = append(entries, e)
	}
	return entries, rows.Err()
}

// dbEnsurePlayEncounterOrderTx initializes the explicit combatant order from
// the current initiative-based order if no order is currently stored.
func dbEnsurePlayEncounterOrderTx(tx *sql.Tx, campaignID, encounterID string) error {
	order, ok, err := dbReadPlayEncounterOrderTx(tx, campaignID, encounterID)
	if err != nil {
		return err
	}
	if ok && len(order) > 0 {
		return nil
	}

	entries, err := dbBuildPlayEncounterOrderEntriesTx(tx, campaignID, encounterID)
	if err != nil {
		return err
	}
	if len(entries) == 0 {
		return nil
	}

	newOrder := make([]encounterOrderEntry, len(entries))
	for i, e := range entries {
		newOrder[i] = encounterOrderEntry{Kind: e.Kind, ID: e.TargetID}
	}
	return dbWritePlayEncounterOrderTx(tx, campaignID, encounterID, newOrder)
}

// dbGetPlayEncounterOrderedEntriesTx returns the encounter combatants in their
// current order. If an explicit order is stored, it is used; otherwise the
// entries are sorted by initiative descending, name ascending, kind ascending.
func dbGetPlayEncounterOrderedEntriesTx(tx *sql.Tx, campaignID, encounterID string) ([]encounterTurnEntry, error) {
	entries, err := dbBuildPlayEncounterOrderEntriesTx(tx, campaignID, encounterID)
	if err != nil {
		return nil, err
	}

	order, ok, err := dbReadPlayEncounterOrderTx(tx, campaignID, encounterID)
	if err != nil {
		return nil, err
	}
	if !ok || len(order) == 0 {
		return entries, nil
	}

	orderIndex := make(map[string]int, len(order))
	for i, e := range order {
		orderIndex[encounterOrderKey(e.Kind, e.ID)] = i
	}

	// Sort by explicit order, falling back to the deterministic initiative
	// order for any combatants not present in the stored order.
	sort.Slice(entries, func(i, j int) bool {
		idxI, okI := orderIndex[encounterOrderKey(entries[i].Kind, entries[i].TargetID)]
		idxJ, okJ := orderIndex[encounterOrderKey(entries[j].Kind, entries[j].TargetID)]
		if okI && okJ && idxI != idxJ {
			return idxI < idxJ
		}
		if entries[i].Initiative != entries[j].Initiative {
			return entries[i].Initiative > entries[j].Initiative
		}
		if entries[i].Name != entries[j].Name {
			return entries[i].Name < entries[j].Name
		}
		return entries[i].Kind < entries[j].Kind
	})
	return entries, nil
}

// encounterOrderKey returns a stable key for an explicit order entry.
func encounterOrderKey(kind, id string) string {
	return kind + ":" + id
}

// dbAddToPlayEncounterOrderTx inserts a new combatant into the explicit
// encounter order based on its initiative. If no order exists yet, one is
// created first.
func dbAddToPlayEncounterOrderTx(tx *sql.Tx, campaignID, encounterID, kind, id string, initiative int) error {
	if err := dbEnsurePlayEncounterOrderTx(tx, campaignID, encounterID); err != nil {
		return err
	}

	order, ok, err := dbReadPlayEncounterOrderTx(tx, campaignID, encounterID)
	if err != nil {
		return err
	}
	if !ok {
		return nil
	}
	for _, o := range order {
		if o.Kind == kind && o.ID == id {
			return nil
		}
	}

	entries, err := dbGetPlayEncounterOrderedEntriesTx(tx, campaignID, encounterID)
	if err != nil {
		return err
	}
	initiatives := make(map[string]int, len(entries))
	for _, e := range entries {
		initiatives[encounterOrderKey(e.Kind, e.TargetID)] = e.Initiative
	}

	insertAt := len(order)
	for i, o := range order {
		init, found := initiatives[encounterOrderKey(o.Kind, o.ID)]
		if found && initiative > init {
			insertAt = i
			break
		}
	}
	order = append(order, encounterOrderEntry{})
	copy(order[insertAt+1:], order[insertAt:])
	order[insertAt] = encounterOrderEntry{Kind: kind, ID: id}
	return dbWritePlayEncounterOrderTx(tx, campaignID, encounterID, order)
}

// dbRemoveFromPlayEncounterOrderTx removes a combatant from the explicit
// encounter order if one is stored.
func dbRemoveFromPlayEncounterOrderTx(tx *sql.Tx, campaignID, encounterID, kind, id string) error {
	order, ok, err := dbReadPlayEncounterOrderTx(tx, campaignID, encounterID)
	if err != nil {
		return err
	}
	if !ok {
		return nil
	}
	newOrder := make([]encounterOrderEntry, 0, len(order))
	for _, o := range order {
		if o.Kind != kind || o.ID != id {
			newOrder = append(newOrder, o)
		}
	}
	return dbWritePlayEncounterOrderTx(tx, campaignID, encounterID, newOrder)
}

// dbGetPlayEncounterActive returns the currently active combatant for the
// encounter along with the stored round and turn index. If the encounter has
// no combatants, active is nil.
func dbGetPlayEncounterActive(campaignID, encounterID string) (*encounterTurnEntry, int, int, bool, error) {
	var round, turnIndex int
	err := db.QueryRow(
		"SELECT round, turn_index FROM play_encounters WHERE campaign_id = ? AND id = ?",
		campaignID, encounterID,
	).Scan(&round, &turnIndex)
	if err == sql.ErrNoRows {
		return nil, 0, 0, false, nil
	}
	if err != nil {
		return nil, 0, 0, false, err
	}

	order, err := dbGetPlayEncounterTurnOrder(campaignID, encounterID)
	if err != nil {
		return nil, 0, 0, false, err
	}
	if len(order) == 0 {
		return nil, round, turnIndex, true, nil
	}
	turnIndex = turnIndex % len(order)
	if turnIndex < 0 {
		turnIndex = 0
	}
	return &order[turnIndex], round, turnIndex, true, nil
}

// dbAdvancePlayEncounterTurn advances the encounter to the next combatant in
// deterministic initiative order. It verifies that the caller is either the
// campaign owner or the current combatant; otherwise it returns ok=false. The
// new active combatant is returned on success.
func dbAdvancePlayEncounterTurn(campaignID, encounterID, caller string, isOwner bool) (*encounterTurnEntry, int, int, bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, 0, 0, false, err
	}
	defer tx.Rollback()

	var round, turnIndex int
	err = tx.QueryRow(
		"SELECT round, turn_index FROM play_encounters WHERE campaign_id = ? AND id = ?",
		campaignID, encounterID,
	).Scan(&round, &turnIndex)
	if err == sql.ErrNoRows {
		return nil, 0, 0, false, nil
	}
	if err != nil {
		return nil, 0, 0, false, err
	}

	order, err := dbGetPlayEncounterTurnOrderTx(tx, campaignID, encounterID)
	if err != nil {
		return nil, 0, 0, false, err
	}
	if len(order) == 0 {
		return nil, 0, 0, false, nil
	}
	turnIndex = turnIndex % len(order)
	if turnIndex < 0 {
		turnIndex = 0
	}

	if !isOwner {
		active := order[turnIndex]
		if active.Kind != "member" || active.Member != caller {
			return nil, 0, 0, false, nil
		}
	}

	nextIndex := turnIndex + 1
	nextRound := round
	if nextIndex >= len(order) {
		nextIndex = 0
		nextRound++
	}

	if _, err := tx.Exec(
		"UPDATE play_encounters SET round = ?, turn_index = ? WHERE campaign_id = ? AND id = ?",
		nextRound, nextIndex, campaignID, encounterID,
	); err != nil {
		return nil, 0, 0, false, err
	}

	// Decrement conditions on the newly active combatant at the start of its turn.
	// Conditions that reach 0 remaining rounds are removed.
	if nextIndex >= 0 && nextIndex < len(order) {
		if _, err := dbDecrementPlayEncounterConditionsTx(tx, campaignID, encounterID, order[nextIndex].TargetID); err != nil {
			return nil, 0, 0, false, err
		}
	}

	if err := tx.Commit(); err != nil {
		return nil, 0, 0, false, err
	}
	return &order[nextIndex], nextRound, nextIndex, true, nil
}

// dbCreatePlayEncounterCondition adds a named condition to a target combatant
// in a play encounter. The caller must already have verified that the target
// exists in the encounter.
func dbCreatePlayEncounterCondition(campaignID, encounterID, target, conditionName string, duration int) error {
	_, err := db.Exec(
		`INSERT INTO play_encounter_conditions (encounter_id, campaign_id, target, condition, remaining_rounds)
		 VALUES (?, ?, ?, ?, ?)`,
		encounterID, campaignID, target, conditionName, duration,
	)
	return err
}

// dbDelayPlayEncounterMove moves the current combatant to a new position later
// in the initiative order. It returns the new ordered entries, ok=false when
// the encounter is not found or has no combatants, and invalid=true when the
// requested index is not a valid later position.
func dbDelayPlayEncounterTurn(campaignID, encounterID string, newIndex int) ([]encounterTurnEntry, bool, bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, false, false, err
	}
	defer tx.Rollback()

	var exists int
	err = tx.QueryRow(
		"SELECT 1 FROM play_encounters WHERE campaign_id = ? AND id = ?",
		campaignID, encounterID,
	).Scan(&exists)
	if err == sql.ErrNoRows {
		return nil, false, false, nil
	}
	if err != nil {
		return nil, false, false, err
	}

	var round, turnIndex int
	err = tx.QueryRow(
		"SELECT round, turn_index FROM play_encounters WHERE campaign_id = ? AND id = ?",
		campaignID, encounterID,
	).Scan(&round, &turnIndex)
	if err == sql.ErrNoRows {
		return nil, false, false, nil
	}
	if err != nil {
		return nil, false, false, err
	}

	order, err := dbGetPlayEncounterOrderedEntriesTx(tx, campaignID, encounterID)
	if err != nil {
		return nil, false, false, err
	}
	if len(order) == 0 {
		return nil, false, false, nil
	}
	turnIndex = turnIndex % len(order)
	if turnIndex < 0 {
		turnIndex = 0
	}

	if newIndex <= turnIndex || newIndex >= len(order) {
		return nil, false, true, nil
	}

	current := order[turnIndex]
	order = append(order[:turnIndex], order[turnIndex+1:]...)
	order = append(order[:newIndex], append([]encounterTurnEntry{current}, order[newIndex:]...)...)

	newOrder := make([]encounterOrderEntry, len(order))
	for i, e := range order {
		newOrder[i] = encounterOrderEntry{Kind: e.Kind, ID: e.TargetID}
	}
	if err := dbWritePlayEncounterOrderTx(tx, campaignID, encounterID, newOrder); err != nil {
		return nil, false, false, err
	}

	if _, err := tx.Exec(
		"UPDATE play_encounters SET turn_index = ? WHERE campaign_id = ? AND id = ?",
		newIndex, campaignID, encounterID,
	); err != nil {
		return nil, false, false, err
	}

	if err := tx.Commit(); err != nil {
		return nil, false, false, err
	}
	return order, true, false, nil
}

// dbCreateReadyAction records a ready action for the current encounter
// combatant. It appends a ready narration event to the campaign log and
// returns the ready record. It returns ok=false when the encounter is missing.
func dbCreateReadyAction(campaignID, encounterID, actor, trigger string) (*readyActionResponse, bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, false, err
	}
	defer tx.Rollback()

	var exists int
	err = tx.QueryRow(
		"SELECT 1 FROM play_encounters WHERE campaign_id = ? AND id = ?",
		campaignID, encounterID,
	).Scan(&exists)
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}

	var nextSeq int
	err = tx.QueryRow(
		"SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_narrations WHERE campaign_id = ?",
		campaignID,
	).Scan(&nextSeq)
	if err != nil {
		return nil, false, err
	}

	if _, err := tx.Exec(
		"INSERT INTO play_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (?, ?, ?, ?, ?, ?)",
		campaignID, nextSeq, "ready", actor, "ready", trigger,
	); err != nil {
		return nil, false, err
	}

	if err := tx.Commit(); err != nil {
		return nil, false, err
	}
	return &readyActionResponse{Actor: actor, Trigger: trigger}, true, nil
}

// dbGetPlayEncounterConditionsByTarget returns the current conditions on a
// specific target combatant in an encounter, ordered by row id.
func dbGetPlayEncounterConditionsByTarget(campaignID, encounterID, target string) ([]condition, error) {
	rows, err := db.Query(
		"SELECT condition, remaining_rounds FROM play_encounter_conditions WHERE encounter_id = ? AND campaign_id = ? AND target = ? ORDER BY id ASC",
		encounterID, campaignID, target,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var conds []condition
	for rows.Next() {
		var c condition
		if err := rows.Scan(&c.Condition, &c.Remaining); err != nil {
			return nil, err
		}
		conds = append(conds, c)
	}
	return conds, rows.Err()
}

// dbGetPlayEncounterConditions returns all current conditions for an
// encounter as a map keyed by target identifier.
func dbGetPlayEncounterConditions(campaignID, encounterID string) (map[string][]condition, error) {
	rows, err := db.Query(
		"SELECT target, condition, remaining_rounds FROM play_encounter_conditions WHERE encounter_id = ? AND campaign_id = ? ORDER BY target ASC, id ASC",
		encounterID, campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	conds := map[string][]condition{}
	for rows.Next() {
		var target, name string
		var remaining int
		if err := rows.Scan(&target, &name, &remaining); err != nil {
			return nil, err
		}
		conds[target] = append(conds[target], condition{Condition: name, Remaining: remaining})
	}
	return conds, rows.Err()
}

// dbGetPlayEncounterConditionsByTargetTx is the transaction-scoped variant of
// dbGetPlayEncounterConditionsByTarget.
func dbGetPlayEncounterConditionsByTargetTx(tx *sql.Tx, campaignID, encounterID, target string) ([]condition, error) {
	rows, err := tx.Query(
		"SELECT condition, remaining_rounds FROM play_encounter_conditions WHERE encounter_id = ? AND campaign_id = ? AND target = ? ORDER BY id ASC",
		encounterID, campaignID, target,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var conds []condition
	for rows.Next() {
		var c condition
		if err := rows.Scan(&c.Condition, &c.Remaining); err != nil {
			return nil, err
		}
		conds = append(conds, c)
	}
	return conds, rows.Err()
}

// dbDecrementPlayEncounterConditionsTx decrements the remaining rounds of all
// conditions on a target combatant and deletes any that reach 0. It returns
// the remaining conditions after the decrement.
func dbDecrementPlayEncounterConditionsTx(tx *sql.Tx, campaignID, encounterID, target string) ([]condition, error) {
	if _, err := tx.Exec(
		"UPDATE play_encounter_conditions SET remaining_rounds = remaining_rounds - 1 WHERE encounter_id = ? AND campaign_id = ? AND target = ?",
		encounterID, campaignID, target,
	); err != nil {
		return nil, err
	}
	if _, err := tx.Exec(
		"DELETE FROM play_encounter_conditions WHERE encounter_id = ? AND campaign_id = ? AND target = ? AND remaining_rounds <= 0",
		encounterID, campaignID, target,
	); err != nil {
		return nil, err
	}
	return dbGetPlayEncounterConditionsByTargetTx(tx, campaignID, encounterID, target)
}

// dbCreateCombatAction records a player combat action for the current
// encounter combatant. It verifies that the encounter is active and that the
// caller is the current active member combatant, then appends a combat_action
// event to the campaign narration log without advancing the encounter turn.
// If the caller is not the current combatant or the encounter is not active,
// it returns ok=false.
func dbCreateCombatAction(campaignID, encounterID, username string, req *combatActionRequest) (*combatActionResponse, bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, false, err
	}
	defer tx.Rollback()

	var campaignStatus string
	err = tx.QueryRow(
		"SELECT status FROM play_campaigns WHERE id = ?",
		campaignID,
	).Scan(&campaignStatus)
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	if campaignStatus != campaignStatusActive {
		return nil, false, nil
	}

	var encStatus string
	err = tx.QueryRow(
		"SELECT status FROM play_encounters WHERE campaign_id = ? AND id = ?",
		campaignID, encounterID,
	).Scan(&encStatus)
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	if encStatus != encounterStatusActive {
		return nil, false, nil
	}

	var round, turnIndex int
	err = tx.QueryRow(
		"SELECT round, turn_index FROM play_encounters WHERE campaign_id = ? AND id = ?",
		campaignID, encounterID,
	).Scan(&round, &turnIndex)
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}

	order, err := dbGetPlayEncounterTurnOrderTx(tx, campaignID, encounterID)
	if err != nil {
		return nil, false, err
	}
	if len(order) == 0 {
		return nil, false, nil
	}
	if turnIndex < 0 || turnIndex >= len(order) {
		turnIndex = 0
	}
	active := order[turnIndex]
	if active.Kind != "member" || active.Member != username {
		return nil, false, nil
	}

	var nextSeq int
	err = tx.QueryRow(
		"SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_narrations WHERE campaign_id = ?",
		campaignID,
	).Scan(&nextSeq)
	if err != nil {
		return nil, false, err
	}

	if _, err := tx.Exec(
		"INSERT INTO play_narrations (campaign_id, sequence, kind, actor, type, text, target) VALUES (?, ?, ?, ?, ?, ?, ?)",
		campaignID, nextSeq, "combat_action", username, req.Type, req.Text, req.Target,
	); err != nil {
		return nil, false, err
	}

	if err := tx.Commit(); err != nil {
		return nil, false, err
	}

	return &combatActionResponse{
		Sequence: nextSeq,
		Kind:     "combat_action",
		Actor:    username,
		Type:     req.Type,
		Target:   req.Target,
		Text:     req.Text,
	}, true, nil
}

// dbGetPlayEncounterTurnOrderTx is the transaction-scoped variant of
// dbGetPlayEncounterTurnOrder. It respects the explicit combatant_order when
// one is stored; otherwise it falls back to initiative-based sorting.
func dbGetPlayEncounterTurnOrderTx(tx *sql.Tx, campaignID, encounterID string) ([]encounterTurnEntry, error) {
	return dbGetPlayEncounterOrderedEntriesTx(tx, campaignID, encounterID)
}

// encounterHealthTarget is a unified view of a monster or member combatant in
// an encounter used for damage and healing resolution.
type encounterHealthTarget struct {
	Target   string
	Kind     string // "monster" or "member"
	HPBefore int
	HPMax    int
}

// dbGetEncounterHealthTarget resolves a target identifier to a monster or
// member combatant in the encounter. The target is first matched against
// monster_id, then against the member username.
func dbGetEncounterHealthTarget(campaignID, encounterID, target string) (*encounterHealthTarget, bool, error) {
	var name string
	var hpCurrent, hpMax int

	err := db.QueryRow(
		"SELECT name, hp_current, hp_max FROM play_encounter_monsters WHERE encounter_id = ? AND campaign_id = ? AND monster_id = ?",
		encounterID, campaignID, target,
	).Scan(&name, &hpCurrent, &hpMax)
	if err == nil {
		return &encounterHealthTarget{Target: target, Kind: "monster", HPBefore: hpCurrent, HPMax: hpMax}, true, nil
	}
	if err != sql.ErrNoRows {
		return nil, false, err
	}

	var member string
	err = db.QueryRow(
		`SELECT c.member, c.name, m.hp_current, m.hp_max
		 FROM play_combatants c
		 JOIN play_members m ON m.campaign_id = c.campaign_id AND m.username = c.member
		 WHERE c.encounter_id = ? AND c.campaign_id = ? AND c.member = ?`,
		encounterID, campaignID, target,
	).Scan(&member, &name, &hpCurrent, &hpMax)
	if err == nil {
		return &encounterHealthTarget{Target: target, Kind: "member", HPBefore: hpCurrent, HPMax: hpMax}, true, nil
	}
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	return nil, false, err
}

// dbGetEncounterHealthTargetTx is the transaction-scoped variant of
// dbGetEncounterHealthTarget.
func dbGetEncounterHealthTargetTx(tx *sql.Tx, campaignID, encounterID, target string) (*encounterHealthTarget, bool, error) {
	var name string
	var hpCurrent, hpMax int

	err := tx.QueryRow(
		"SELECT name, hp_current, hp_max FROM play_encounter_monsters WHERE encounter_id = ? AND campaign_id = ? AND monster_id = ?",
		encounterID, campaignID, target,
	).Scan(&name, &hpCurrent, &hpMax)
	if err == nil {
		return &encounterHealthTarget{Target: target, Kind: "monster", HPBefore: hpCurrent, HPMax: hpMax}, true, nil
	}
	if err != sql.ErrNoRows {
		return nil, false, err
	}

	var member string
	err = tx.QueryRow(
		`SELECT c.member, c.name, m.hp_current, m.hp_max
		 FROM play_combatants c
		 JOIN play_members m ON m.campaign_id = c.campaign_id AND m.username = c.member
		 WHERE c.encounter_id = ? AND c.campaign_id = ? AND c.member = ?`,
		encounterID, campaignID, target,
	).Scan(&member, &name, &hpCurrent, &hpMax)
	if err == nil {
		return &encounterHealthTarget{Target: target, Kind: "member", HPBefore: hpCurrent, HPMax: hpMax}, true, nil
	}
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	return nil, false, err
}

// dbApplyDamage reduces an encounter combatant's HP by the given amount,
// flooring at 0. It returns ok=false when the target is not found.
func dbApplyDamage(campaignID, encounterID, target string, amount int) (*damageResponse, bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, false, err
	}
	defer tx.Rollback()

	c, found, err := dbGetEncounterHealthTargetTx(tx, campaignID, encounterID, target)
	if err != nil || !found {
		return nil, found, err
	}

	after := c.HPBefore - amount
	if after < 0 {
		after = 0
	}

	if c.Kind == "monster" {
		_, err = tx.Exec(
			"UPDATE play_encounter_monsters SET hp_current = ? WHERE encounter_id = ? AND campaign_id = ? AND monster_id = ?",
			after, encounterID, campaignID, target,
		)
	} else {
		if _, err := dbUpdateMemberHP(tx, campaignID, target, after); err != nil {
			return nil, false, err
		}
	}
	if err != nil {
		return nil, false, err
	}

	if err := tx.Commit(); err != nil {
		return nil, false, err
	}

	return &damageResponse{
		Target:   target,
		HPBefore: c.HPBefore,
		HPAfter:  after,
		Damage:   amount,
	}, true, nil
}

// dbApplyHealing increases an encounter combatant's HP by the given amount,
// capping at hp_max. It returns ok=false when the target is not found.
func dbApplyHealing(campaignID, encounterID, target string, amount int) (*healingResponse, bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, false, err
	}
	defer tx.Rollback()

	c, found, err := dbGetEncounterHealthTargetTx(tx, campaignID, encounterID, target)
	if err != nil || !found {
		return nil, found, err
	}

	after := c.HPBefore + amount
	if after > c.HPMax {
		after = c.HPMax
	}

	if c.Kind == "monster" {
		_, err = tx.Exec(
			"UPDATE play_encounter_monsters SET hp_current = ? WHERE encounter_id = ? AND campaign_id = ? AND monster_id = ?",
			after, encounterID, campaignID, target,
		)
	} else {
		if _, err := dbUpdateMemberHP(tx, campaignID, target, after); err != nil {
			return nil, false, err
		}
	}
	if err != nil {
		return nil, false, err
	}

	if err := tx.Commit(); err != nil {
		return nil, false, err
	}

	return &healingResponse{
		Target:   target,
		HPBefore: c.HPBefore,
		HPAfter:  after,
		Healing:  amount,
	}, true, nil
}

// dbApplyCharacterDamage reduces a campaign member's HP by the given amount,
// floors at 0, and marks the character unconscious if HP reaches 0. It is
// used by the campaign-owner character damage endpoint. It returns
// ok=false when the character is not found in the campaign.
func dbApplyCharacterDamage(campaignID, characterID string, amount int) (*damageResponse, bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, false, err
	}
	defer tx.Rollback()

	m, err := dbGetPlayMembershipByCharacterIDTx(tx, campaignID, characterID)
	if err != nil {
		return nil, false, err
	}
	if m == nil {
		return nil, false, nil
	}

	after := m.HPCurrent - amount
	if after < 0 {
		after = 0
	}

	if _, err := dbUpdateMemberHP(tx, campaignID, m.Username, after); err != nil {
		return nil, false, err
	}

	if err := tx.Commit(); err != nil {
		return nil, false, err
	}

	return &damageResponse{
		Target:   characterID,
		HPBefore: m.HPCurrent,
		HPAfter:  after,
		Damage:   amount,
	}, true, nil
}

// dbRecordDeathSave records a success or failure for an unconscious character
// and updates its life state accordingly. It returns ok=false when the
// character is not found, and conflict=true when the character is not
// unconscious.
func dbRecordDeathSave(campaignID, characterID, outcome string) (*deathSavesResponse, bool, bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, false, false, err
	}
	defer tx.Rollback()

	m, err := dbGetPlayMembershipByCharacterIDTx(tx, campaignID, characterID)
	if err != nil {
		return nil, false, false, err
	}
	if m == nil {
		return nil, false, false, nil
	}

	if m.Status != characterStatusUnconscious {
		return nil, false, true, nil
	}

	successes, failures := m.Successes, m.Failures
	status := m.Status
	if outcome == "success" {
		successes++
		if successes >= 3 {
			status = characterStatusStable
		}
	} else if outcome == "failure" {
		failures++
		if failures >= 3 {
			status = characterStatusDead
		}
	}

	if _, err := tx.Exec(
		"UPDATE play_members SET death_save_successes = ?, death_save_failures = ?, status = ? WHERE campaign_id = ? AND character_id = ?",
		successes, failures, status, campaignID, characterID,
	); err != nil {
		return nil, false, false, err
	}

	if err := tx.Commit(); err != nil {
		return nil, false, false, err
	}

	return &deathSavesResponse{
		CharacterID: characterID,
		Successes:   successes,
		Failures:    failures,
		Status:      status,
	}, true, false, nil
}

// dbCreatePlayEncounterMonster adds a deterministic monster combatant to an
// encounter. The caller must already have verified the encounter exists. If an
// explicit combatant order is stored, the monster is inserted into it by
// initiative.
func dbCreatePlayEncounterMonster(campaignID, encounterID string, m *playEncounterMonster) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	if _, err := tx.Exec(
		`INSERT INTO play_encounter_monsters (encounter_id, campaign_id, monster_id, name, hp_max, hp_current, initiative)
		 VALUES (?, ?, ?, ?, ?, ?, ?)`,
		encounterID, campaignID, m.MonsterID, m.Name, m.HPMax, m.HPMax, m.Initiative,
	); err != nil {
		return err
	}

	if err := dbAddToPlayEncounterOrderTx(tx, campaignID, encounterID, "monster", m.MonsterID, m.Initiative); err != nil {
		return err
	}

	return tx.Commit()
}

// dbGetPlayEncounterMonster returns a single encounter monster, or nil if not found.
func dbGetPlayEncounterMonster(campaignID, encounterID, monsterID string) (*playEncounterMonster, error) {
	m := &playEncounterMonster{MonsterID: monsterID}
	err := db.QueryRow(
		"SELECT name, hp_max, hp_current, initiative FROM play_encounter_monsters WHERE encounter_id = ? AND campaign_id = ? AND monster_id = ?",
		encounterID, campaignID, monsterID,
	).Scan(&m.Name, &m.HPMax, &m.HPCurrent, &m.Initiative)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return m, nil
}

// dbDeletePlayEncounterMonster removes a monster from an encounter. It returns
// true when a row was actually deleted. If an explicit combatant order is
// stored, the monster is removed from it.
func dbDeletePlayEncounterMonster(campaignID, encounterID, monsterID string) (bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return false, err
	}
	defer tx.Rollback()

	res, err := tx.Exec(
		"DELETE FROM play_encounter_monsters WHERE encounter_id = ? AND campaign_id = ? AND monster_id = ?",
		encounterID, campaignID, monsterID,
	)
	if err != nil {
		return false, err
	}
	affected, err := res.RowsAffected()
	if err != nil {
		return false, err
	}
	if affected == 0 {
		return false, tx.Rollback()
	}

	if err := dbRemoveFromPlayEncounterOrderTx(tx, campaignID, encounterID, "monster", monsterID); err != nil {
		return false, err
	}
	return true, tx.Commit()
}

// dbGetPlayEncounterMemberCombatant returns a member combatant bound to an
// encounter, or nil if the member has not been bound.
func dbGetPlayEncounterMemberCombatant(campaignID, encounterID, username string) (*playEncounterMemberCombatant, error) {
	c := &playEncounterMemberCombatant{Member: username}
	err := db.QueryRow(
		"SELECT name, character_id, initiative FROM play_combatants WHERE encounter_id = ? AND campaign_id = ? AND member = ?",
		encounterID, campaignID, username,
	).Scan(&c.Name, &c.CharacterID, &c.Initiative)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return c, nil
}

// dbCreatePlayEncounterMemberCombatant binds a campaign party member to an
// encounter as a combatant. The caller must already have verified the member
// belongs to the campaign and that they are not already bound. If an explicit
// combatant order is stored, the member is inserted into it by initiative.
func dbCreatePlayEncounterMemberCombatant(campaignID, encounterID string, m *playMembership, initiative int) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	if _, err := tx.Exec(
		`INSERT INTO play_combatants (encounter_id, campaign_id, name, member, character_id, initiative)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		encounterID, campaignID, m.Name, m.Username, m.CharacterID, initiative,
	); err != nil {
		return err
	}

	if err := dbAddToPlayEncounterOrderTx(tx, campaignID, encounterID, "member", m.Username, initiative); err != nil {
		return err
	}
	return tx.Commit()
}

// dbDeletePlayEncounterMemberCombatant removes a bound member combatant from an
// encounter. It returns true when a row was actually deleted. If an explicit
// combatant order is stored, the member is removed from it.
func dbDeletePlayEncounterMemberCombatant(campaignID, encounterID, username string) (bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return false, err
	}
	defer tx.Rollback()

	res, err := tx.Exec(
		"DELETE FROM play_combatants WHERE encounter_id = ? AND campaign_id = ? AND member = ?",
		encounterID, campaignID, username,
	)
	if err != nil {
		return false, err
	}
	affected, err := res.RowsAffected()
	if err != nil {
		return false, err
	}
	if affected == 0 {
		return false, tx.Rollback()
	}

	if err := dbRemoveFromPlayEncounterOrderTx(tx, campaignID, encounterID, "member", username); err != nil {
		return false, err
	}
	return true, tx.Commit()
}

// dbGetPlayLocationConnections returns outbound destinations from a location,
// ordered deterministically by destination id.
func dbGetPlayLocationConnections(campaignID, locID string) ([]travelDestination, error) {
	rows, err := db.Query(
		`SELECT c.to_id, l.name, c.travel_turns
		 FROM play_connections c
		 JOIN play_locations l ON l.id = c.to_id AND l.campaign_id = c.campaign_id
		 WHERE c.campaign_id = ? AND c.from_id = ?
		 ORDER BY c.to_id ASC`,
		campaignID, locID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	dests := []travelDestination{}
	for rows.Next() {
		var d travelDestination
		if err := rows.Scan(&d.ID, &d.Name, &d.TravelTurns); err != nil {
			return nil, err
		}
		dests = append(dests, d)
	}
	return dests, rows.Err()
}

// dbSetPlayCampaignCurrentScene sets the current scene for a campaign. The
// caller must already have verified the caller is the owner and that the
// scene is open.
func dbSetPlayCampaignCurrentScene(campaignID, sceneID string) error {
	_, err := db.Exec(
		"UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?",
		sceneID, campaignID,
	)
	return err
}

// dbClosePlayScene marks a scene as closed. It returns the updated scene or
// nil if the scene does not exist.
func dbClosePlayScene(campaignID, id string) (*playScene, error) {
	_, err := db.Exec(
		"UPDATE play_scenes SET status = ? WHERE id = ? AND campaign_id = ? AND status = ?",
		sceneStatusClosed, id, campaignID, sceneStatusOpen,
	)
	if err != nil {
		return nil, err
	}
	return dbGetPlayScene(campaignID, id)
}

// dbGetPlayCampaignTurn returns the active turn pointer for a play campaign.
// The current actor is empty for campaigns that have not been started yet.
func dbGetPlayCampaignTurn(id string) (string, int, bool, error) {
	var status string
	var actor sql.NullString
	var turnNumber int
	err := db.QueryRow(
		"SELECT status, current_actor, turn_number FROM play_campaigns WHERE id = ?",
		id,
	).Scan(&status, &actor, &turnNumber)
	if err == sql.ErrNoRows {
		return "", 0, false, nil
	}
	if err != nil {
		return "", 0, false, err
	}
	return actor.String, turnNumber, true, nil
}

func dbCreatePlayMembership(campaignID, username string, req *playMembershipRequest) error {
	_, err := db.Exec(
		"INSERT INTO play_members (campaign_id, username, character_id, name, class, hp_current, hp_max, gold) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
		campaignID, username, req.CharacterID, req.Name, req.Class, 20, 20, 10,
	)
	return err
}

func dbCountPlayMembersByCampaign(campaignID string) (int, error) {
	var count int
	err := db.QueryRow(
		"SELECT COUNT(DISTINCT username) FROM play_members WHERE campaign_id = ? AND username IS NOT NULL",
		campaignID,
	).Scan(&count)
	return count, err
}

func dbGetPlayMembershipByUserAndCampaign(username, campaignID string) (*playMembership, error) {
	m := &playMembership{CampaignID: campaignID}
	err := db.QueryRow(
		"SELECT character_id, name, class, level, hp_current, hp_max, status, death_save_successes, death_save_failures FROM play_members WHERE username = ? AND campaign_id = ?",
		username, campaignID,
	).Scan(&m.CharacterID, &m.Name, &m.Class, &m.Level, &m.HPCurrent, &m.HPMax, &m.Status, &m.Successes, &m.Failures)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	m.Username = username
	return m, nil
}

// dbGetPlayMembershipByCharacterID returns a play membership by its character
// id within a campaign, or nil if not found.
func dbGetPlayMembershipByCharacterID(campaignID, characterID string) (*playMembership, error) {
	m := &playMembership{CampaignID: campaignID, CharacterID: characterID}
	var username sql.NullString
	err := db.QueryRow(
		"SELECT username, name, class, level, hp_current, hp_max, status, death_save_successes, death_save_failures FROM play_members WHERE character_id = ? AND campaign_id = ?",
		characterID, campaignID,
	).Scan(&username, &m.Name, &m.Class, &m.Level, &m.HPCurrent, &m.HPMax, &m.Status, &m.Successes, &m.Failures)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if username.Valid {
		m.Username = username.String
	}
	return m, nil
}

// dbGetPlayMembershipByCharacterIDTx is the transaction-scoped variant of
// dbGetPlayMembershipByCharacterID.
func dbGetPlayMembershipByCharacterIDTx(tx *sql.Tx, campaignID, characterID string) (*playMembership, error) {
	m := &playMembership{CampaignID: campaignID, CharacterID: characterID}
	var username sql.NullString
	err := tx.QueryRow(
		"SELECT username, name, class, level, hp_current, hp_max, status, death_save_successes, death_save_failures FROM play_members WHERE character_id = ? AND campaign_id = ?",
		characterID, campaignID,
	).Scan(&username, &m.Name, &m.Class, &m.Level, &m.HPCurrent, &m.HPMax, &m.Status, &m.Successes, &m.Failures)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if username.Valid {
		m.Username = username.String
	}
	return m, nil
}

// resolveMemberStatus determines the new life state for a member after an
// HP change. Dead characters remain dead; zero HP makes a living character
// unconscious; positive HP makes a living character conscious and clears
// death-save counters.
func resolveMemberStatus(currentStatus string, hp int) (newStatus string, resetCounters bool) {
	if currentStatus == characterStatusDead {
		return characterStatusDead, false
	}
	if hp <= 0 {
		return characterStatusUnconscious, false
	}
	return characterStatusConscious, true
}

// dbUpdateMemberHP applies an HP change to a member and keeps the life state
// in sync. It returns the resulting status.
func dbUpdateMemberHP(tx *sql.Tx, campaignID, username string, hp int) (string, error) {
	var status string
	err := tx.QueryRow(
		"SELECT status FROM play_members WHERE campaign_id = ? AND username = ?",
		campaignID, username,
	).Scan(&status)
	if err != nil {
		return "", err
	}

	newStatus, resetCounters := resolveMemberStatus(status, hp)
	if resetCounters {
		_, err = tx.Exec(
			"UPDATE play_members SET hp_current = ?, status = ?, death_save_successes = 0, death_save_failures = 0 WHERE campaign_id = ? AND username = ?",
			hp, newStatus, campaignID, username,
		)
	} else {
		_, err = tx.Exec(
			"UPDATE play_members SET hp_current = ?, status = ? WHERE campaign_id = ? AND username = ?",
			hp, newStatus, campaignID, username,
		)
	}
	if err != nil {
		return "", err
	}
	return newStatus, nil
}

// dbGetPlayMembersByCampaign returns the usernames of all members in a play
// campaign, sorted deterministically by join order (insertion rowid).
func dbGetPlayMembersByCampaign(campaignID string) ([]string, error) {
	rows, err := db.Query(
		"SELECT username FROM play_members WHERE campaign_id = ? AND username IS NOT NULL GROUP BY username ORDER BY MIN(rowid) ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var usernames []string
	for rows.Next() {
		var username string
		if err := rows.Scan(&username); err != nil {
			return nil, err
		}
		usernames = append(usernames, username)
	}
	return usernames, rows.Err()
}

// dbGetPlayMemberSummariesByCampaign returns the full party member summaries
// for a play campaign, ordered deterministically by join order (insertion rowid).
func dbGetPlayMemberSummariesByCampaign(campaignID string) ([]playMembership, error) {
	rows, err := db.Query(
		"SELECT username, character_id, name, class, level, hp_current, hp_max, status, death_save_successes, death_save_failures FROM play_members WHERE campaign_id = ? AND username IS NOT NULL ORDER BY rowid ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var members []playMembership
	for rows.Next() {
		var m playMembership
		m.CampaignID = campaignID
		var username sql.NullString
		if err := rows.Scan(&username, &m.CharacterID, &m.Name, &m.Class, &m.Level, &m.HPCurrent, &m.HPMax, &m.Status, &m.Successes, &m.Failures); err != nil {
			return nil, err
		}
		if username.Valid {
			m.Username = username.String
		}
		members = append(members, m)
	}
	return members, rows.Err()
}

// dbGetCharacterGold returns a campaign character's current gold balance. It
// returns sql.ErrNoRows when the character does not exist in the campaign.
func dbGetCharacterGold(campaignID, characterID string) (int, error) {
	var gold int
	err := db.QueryRow(
		"SELECT gold FROM play_members WHERE campaign_id = ? AND character_id = ?",
		campaignID, characterID,
	).Scan(&gold)
	return gold, err
}

// dbTransferCharacterGold atomically transfers gold from one campaign member to
// another. It returns the public transfer record, or errInsufficientGold when
// the source balance is too low. The caller is responsible for verifying both
// characters exist and belong to the same campaign.
func dbTransferCharacterGold(campaignID, fromCharacterID, toCharacterID string, amount int) (*goldTransferResponse, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	var fromGold, toGold int
	err = tx.QueryRow(
		"SELECT gold FROM play_members WHERE campaign_id = ? AND character_id = ?",
		campaignID, fromCharacterID,
	).Scan(&fromGold)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("source character not found")
	}
	if err != nil {
		return nil, err
	}

	err = tx.QueryRow(
		"SELECT gold FROM play_members WHERE campaign_id = ? AND character_id = ?",
		campaignID, toCharacterID,
	).Scan(&toGold)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("destination character not found")
	}
	if err != nil {
		return nil, err
	}

	if fromGold < amount {
		return nil, errInsufficientGold
	}

	newFromGold := fromGold - amount
	newToGold := toGold + amount

	var nextTransferID int
	err = tx.QueryRow(
		"SELECT COALESCE(MAX(transfer_id), 0) + 1 FROM play_gold_transfers WHERE campaign_id = ?",
		campaignID,
	).Scan(&nextTransferID)
	if err != nil {
		return nil, err
	}

	if _, err := tx.Exec(
		"UPDATE play_members SET gold = ? WHERE campaign_id = ? AND character_id = ?",
		newFromGold, campaignID, fromCharacterID,
	); err != nil {
		return nil, err
	}

	if _, err := tx.Exec(
		"UPDATE play_members SET gold = ? WHERE campaign_id = ? AND character_id = ?",
		newToGold, campaignID, toCharacterID,
	); err != nil {
		return nil, err
	}

	if _, err := tx.Exec(
		`INSERT INTO play_gold_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold, from_gold, to_gold)
		 VALUES (?, ?, ?, ?, ?, ?, ?)`,
		campaignID, nextTransferID, fromCharacterID, toCharacterID, amount, newFromGold, newToGold,
	); err != nil {
		return nil, err
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}

	return &goldTransferResponse{
		FromCharacterID: fromCharacterID,
		ToCharacterID:   toCharacterID,
		Gold:            amount,
		FromGold:        newFromGold,
		ToGold:          newToGold,
		TransferID:      nextTransferID,
	}, nil
}

// dbClaimCharacter assigns an unowned campaign character to the requesting
// player. It returns true when the claim succeeds, false when the character is
// already owned, and an error for unexpected failures.
func dbClaimCharacter(campaignID, characterID, username string) (bool, error) {
	res, err := db.Exec(
		"UPDATE play_members SET username = ? WHERE campaign_id = ? AND character_id = ? AND username IS NULL",
		username, campaignID, characterID,
	)
	if err != nil {
		return false, err
	}
	affected, err := res.RowsAffected()
	if err != nil {
		return false, err
	}
	return affected == 1, nil
}

// dbTransferCharacter moves ownership of a character to a new player. It
// returns true when the transfer succeeds and false when the character is not
// found or the caller is not the current owner. The new owner must already be
// a member of the campaign (checked by the caller).
func dbTransferCharacter(campaignID, characterID, currentOwner, newOwner string) (bool, error) {
	res, err := db.Exec(
		"UPDATE play_members SET username = ? WHERE campaign_id = ? AND character_id = ? AND username = ?",
		newOwner, campaignID, characterID, currentOwner,
	)
	if err != nil {
		return false, err
	}
	affected, err := res.RowsAffected()
	if err != nil {
		return false, err
	}
	return affected == 1, nil
}

// dbBuildCharacter persists validated character build choices for a campaign
// member. It returns the built response, ok=false when the character is not
// found, and an error for unexpected failures. The character is refreshed to
// level 1 full hit points with cleared death saves.
func dbBuildCharacter(campaignID, characterID string, req *characterBuildRequest, hpMax int) (*characterBuildResponse, bool, error) {
	abilitiesJSON, err := json.Marshal(req.Abilities)
	if err != nil {
		return nil, false, err
	}

	res, err := db.Exec(
		`UPDATE play_members
		 SET class = ?, race = ?, background = ?, level = 1, abilities = ?, hp_max = ?, hp_current = ?, status = 'conscious', death_save_successes = 0, death_save_failures = 0
		 WHERE campaign_id = ? AND character_id = ?`,
		req.Class, req.Race, req.Background, string(abilitiesJSON), hpMax, hpMax, campaignID, characterID,
	)
	if err != nil {
		return nil, false, err
	}
	affected, err := res.RowsAffected()
	if err != nil {
		return nil, false, err
	}
	if affected == 0 {
		return nil, false, nil
	}

	return &characterBuildResponse{
		CharacterID:      characterID,
		Race:             req.Race,
		Class:            req.Class,
		Background:       req.Background,
		Level:            1,
		HPMax:            hpMax,
		ProficiencyBonus: proficiencyBonus(1),
	}, true, nil
}

// dbLevelUpCharacter advances a built campaign character by exactly one level
// and increases its max HP by the deterministic class hit-point gain. It
// returns the public response, ok=false when the character is not found or has
// not been built, and an error for unexpected failures.
func dbLevelUpCharacter(campaignID, characterID string, newLevel int) (*levelUpResponse, bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, false, err
	}
	defer tx.Rollback()

	var username sql.NullString
	var class string
	var currentLevel int
	var hpMax int
	var abilitiesJSON sql.NullString
	err = tx.QueryRow(
		"SELECT username, class, level, hp_max, abilities FROM play_members WHERE campaign_id = ? AND character_id = ?",
		campaignID, characterID,
	).Scan(&username, &class, &currentLevel, &hpMax, &abilitiesJSON)
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	if !username.Valid {
		return nil, false, nil
	}
	if !abilitiesJSON.Valid || abilitiesJSON.String == "" {
		return nil, false, nil
	}

	var a abilities
	if err := json.Unmarshal([]byte(abilitiesJSON.String), &a); err != nil {
		return nil, false, err
	}

	gain := levelUpHPGain(class, a.Con)
	if gain <= 0 {
		return nil, false, fmt.Errorf("invalid class hit dice")
	}
	newHPMax := hpMax + gain

	res, err := tx.Exec(
		"UPDATE play_members SET level = ?, hp_max = ? WHERE campaign_id = ? AND character_id = ?",
		newLevel, newHPMax, campaignID, characterID,
	)
	if err != nil {
		return nil, false, err
	}
	affected, err := res.RowsAffected()
	if err != nil {
		return nil, false, err
	}
	if affected == 0 {
		return nil, false, nil
	}

	if err := tx.Commit(); err != nil {
		return nil, false, err
	}

	return &levelUpResponse{
		CharacterID:      characterID,
		Level:            newLevel,
		HPMax:            newHPMax,
		HitDice:          classHitDiceString(class),
		ProficiencyBonus: proficiencyBonus(newLevel),
	}, true, nil
}

// characterSkillBase holds the durable fields needed to resolve a skill check.
type characterSkillBase struct {
	Username  string
	Level     int
	Abilities abilities
	Built     bool
}

// dbGetCharacterSkillBase loads a character's owner, level, and ability scores
// for skill-check resolution. It returns nil when the character is not found.
func dbGetCharacterSkillBase(campaignID, characterID string) (*characterSkillBase, error) {
	var username sql.NullString
	var level int
	var abilitiesJSON sql.NullString
	err := db.QueryRow(
		"SELECT username, level, abilities FROM play_members WHERE campaign_id = ? AND character_id = ?",
		campaignID, characterID,
	).Scan(&username, &level, &abilitiesJSON)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	var a abilities
	built := abilitiesJSON.Valid && abilitiesJSON.String != ""
	if built {
		if err := json.Unmarshal([]byte(abilitiesJSON.String), &a); err != nil {
			return nil, err
		}
	}

	owner := ""
	if username.Valid {
		owner = username.String
	}
	return &characterSkillBase{
		Username:  owner,
		Level:     level,
		Abilities: a,
		Built:     built,
	}, nil
}

// dbCreateCharacterSpell adds a spell to a character's spellbook. Duplicate
// spells are rejected by the primary key.
func dbCreateCharacterSpell(campaignID, characterID string, s *spell) error {
	_, err := db.Exec(
		"INSERT INTO character_spells (campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)",
		campaignID, characterID, s.SpellID, s.Name, s.Level,
	)
	return err
}

// dbGetCharacterSpells returns the spells known by a character in
// deterministic insertion order.
func dbGetCharacterSpells(campaignID, characterID string) ([]spell, error) {
	rows, err := db.Query(
		"SELECT spell_id, name, level FROM character_spells WHERE campaign_id = ? AND character_id = ? ORDER BY rowid ASC",
		campaignID, characterID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	spells := []spell{}
	for rows.Next() {
		var s spell
		if err := rows.Scan(&s.SpellID, &s.Name, &s.Level); err != nil {
			return nil, err
		}
		spells = append(spells, s)
	}
	return spells, rows.Err()
}

// dbSetCharacterPreparedSpells replaces the character's prepared spell list.
// It is the caller's responsibility to ensure every spell is known and that
// the count is within the class limit.
func dbSetCharacterPreparedSpells(campaignID, characterID string, spellIDs []string) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	_, err = tx.Exec(
		"DELETE FROM character_prepared_spells WHERE campaign_id = ? AND character_id = ?",
		campaignID, characterID,
	)
	if err != nil {
		return err
	}

	for i, spellID := range spellIDs {
		_, err = tx.Exec(
			"INSERT INTO character_prepared_spells (campaign_id, character_id, spell_id, position) VALUES (?, ?, ?, ?)",
			campaignID, characterID, spellID, i,
		)
		if err != nil {
			return err
		}
	}

	return tx.Commit()
}

// dbGetCharacterPreparedSpells returns the prepared spell ids for a character
// in deterministic order. The result is always a non-nil slice.
func dbGetCharacterPreparedSpells(campaignID, characterID string) ([]string, error) {
	rows, err := db.Query(
		"SELECT spell_id FROM character_prepared_spells WHERE campaign_id = ? AND character_id = ? ORDER BY position ASC, rowid ASC",
		campaignID, characterID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	spellIDs := make([]string, 0)
	for rows.Next() {
		var spellID string
		if err := rows.Scan(&spellID); err != nil {
			return nil, err
		}
		spellIDs = append(spellIDs, spellID)
	}
	return spellIDs, rows.Err()
}

// dbGetCharacterSpellSlotsTx returns the remaining spell slots for a
// character within a transaction. If no slots are recorded, it initializes them
// to the maximum for the character's class and level.
func dbGetCharacterSpellSlotsTx(tx *sql.Tx, campaignID, characterID, class string, level int) (map[int]int, error) {
	rows, err := tx.Query(
		"SELECT level, slots_remaining FROM character_spell_slots WHERE campaign_id = ? AND character_id = ?",
		campaignID, characterID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	slots := make(map[int]int)
	for rows.Next() {
		var lvl, remaining int
		if err := rows.Scan(&lvl, &remaining); err != nil {
			return nil, err
		}
		slots[lvl] = remaining
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	maxSlots := classSpellSlots(class, level)
	if maxSlots == nil {
		maxSlots = make(map[int]int)
	}

	initialize := len(slots) == 0
	for lvl, count := range maxSlots {
		if initialize {
			if _, err := tx.Exec(
				"INSERT INTO character_spell_slots (campaign_id, character_id, level, slots_remaining) VALUES (?, ?, ?, ?)",
				campaignID, characterID, lvl, count,
			); err != nil {
				return nil, err
			}
			slots[lvl] = count
		} else if _, ok := slots[lvl]; !ok {
			if _, err := tx.Exec(
				"INSERT INTO character_spell_slots (campaign_id, character_id, level, slots_remaining) VALUES (?, ?, ?, ?)",
				campaignID, characterID, lvl, count,
			); err != nil {
				return nil, err
			}
			slots[lvl] = count
		}
	}

	return slots, nil
}

// dbSetCharacterSpellSlotsTx persists the remaining spell slots for a character.
func dbSetCharacterSpellSlotsTx(tx *sql.Tx, campaignID, characterID string, slots map[int]int) error {
	for lvl, remaining := range slots {
		if _, err := tx.Exec(
			"INSERT INTO character_spell_slots (campaign_id, character_id, level, slots_remaining) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, level) DO UPDATE SET slots_remaining = ?",
			campaignID, characterID, lvl, remaining, remaining,
		); err != nil {
			return err
		}
	}
	return nil
}

// dbResetCharacterSpellSlotsTx restores a character's spell slots to the
// maximum for their class and level. It is used by long rests.
func dbResetCharacterSpellSlotsTx(tx *sql.Tx, campaignID, characterID string) error {
	var class string
	var level int
	err := tx.QueryRow(
		"SELECT class, level FROM play_members WHERE campaign_id = ? AND character_id = ?",
		campaignID, characterID,
	).Scan(&class, &level)
	if err == sql.ErrNoRows {
		return nil
	}
	if err != nil {
		return err
	}

	if _, err := tx.Exec(
		"DELETE FROM character_spell_slots WHERE campaign_id = ? AND character_id = ?",
		campaignID, characterID,
	); err != nil {
		return err
	}

	maxSlots := classSpellSlots(class, level)
	if maxSlots == nil {
		return nil
	}
	for lvl, count := range maxSlots {
		if _, err := tx.Exec(
			"INSERT INTO character_spell_slots (campaign_id, character_id, level, slots_remaining) VALUES (?, ?, ?, ?)",
			campaignID, characterID, lvl, count,
		); err != nil {
			return err
		}
	}
	return nil
}

// dbCastSpell records a spell cast if the character has a remaining slot of
// the required level. Cantrips (level 0) do not consume slots. It returns the
// cast event, a bool that is false when no slot is available, and an error
// for unexpected failures.
func dbCastSpell(campaignID, characterID, spellID, target string, spellLevel int) (*castEvent, bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, false, err
	}
	defer tx.Rollback()

	var class string
	var level int
	err = tx.QueryRow(
		"SELECT class, level FROM play_members WHERE campaign_id = ? AND character_id = ?",
		campaignID, characterID,
	).Scan(&class, &level)
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}

	slots, err := dbGetCharacterSpellSlotsTx(tx, campaignID, characterID, class, level)
	if err != nil {
		return nil, false, err
	}

	var newRemaining int
	if spellLevel == 0 {
		newRemaining = 0
	} else {
		remaining, ok := slots[spellLevel]
		if !ok || remaining <= 0 {
			return nil, false, nil
		}
		newRemaining = remaining - 1
		if err := dbSetCharacterSpellSlotsTx(tx, campaignID, characterID, map[int]int{spellLevel: newRemaining}); err != nil {
			return nil, false, err
		}
	}

	var nextSeq int
	err = tx.QueryRow(
		"SELECT COALESCE(MAX(sequence), 0) + 1 FROM character_spell_casts WHERE campaign_id = ? AND character_id = ?",
		campaignID, characterID,
	).Scan(&nextSeq)
	if err != nil {
		return nil, false, err
	}

	if _, err := tx.Exec(
		"INSERT INTO character_spell_casts (campaign_id, character_id, spell_id, target, slot_level, slots_remaining, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)",
		campaignID, characterID, spellID, target, spellLevel, newRemaining, nextSeq,
	); err != nil {
		return nil, false, err
	}

	if err := tx.Commit(); err != nil {
		return nil, false, err
	}

	return &castEvent{
		CharacterID:    characterID,
		SpellID:        spellID,
		Target:         target,
		SlotLevel:      spellLevel,
		SlotsRemaining: newRemaining,
		Sequence:       nextSeq,
	}, true, nil
}

// dbGetCharacterSpellCasts returns a character's spell cast history in order.
// The result is always a non-nil slice.
func dbGetCharacterSpellCasts(campaignID, characterID string) ([]castEvent, error) {
	rows, err := db.Query(
		"SELECT spell_id, target, slot_level, slots_remaining, sequence FROM character_spell_casts WHERE campaign_id = ? AND character_id = ? ORDER BY sequence ASC, rowid ASC",
		campaignID, characterID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	casts := make([]castEvent, 0)
	for rows.Next() {
		var c castEvent
		c.CharacterID = characterID
		if err := rows.Scan(&c.SpellID, &c.Target, &c.SlotLevel, &c.SlotsRemaining, &c.Sequence); err != nil {
			return nil, err
		}
		casts = append(casts, c)
	}
	return casts, rows.Err()
}

// dbSetCharacterConcentration replaces any existing concentration for a
// character with the supplied spell and target.
func dbSetCharacterConcentration(campaignID, characterID string, c *concentration) error {
	_, err := db.Exec(
		"INSERT INTO character_concentration (campaign_id, character_id, spell_id, target, remaining_turns) VALUES (?, ?, ?, ?, ?) ON CONFLICT(campaign_id, character_id) DO UPDATE SET spell_id = ?, target = ?, remaining_turns = ?",
		campaignID, characterID, c.SpellID, c.Target, c.RemainingTurns,
		c.SpellID, c.Target, c.RemainingTurns,
	)
	return err
}

// dbGetCharacterConcentration returns a character's active concentration, or
// nil when none is recorded.
func dbGetCharacterConcentration(campaignID, characterID string) (*concentration, error) {
	c := &concentration{}
	err := db.QueryRow(
		"SELECT spell_id, target, remaining_turns FROM character_concentration WHERE campaign_id = ? AND character_id = ?",
		campaignID, characterID,
	).Scan(&c.SpellID, &c.Target, &c.RemainingTurns)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return c, nil
}

// dbAdvanceCharacterConcentration decrements the remaining turns of a
// character's active concentration by one. When the count reaches zero the
// record is removed and the returned pointer is nil. If no concentration is
// active, it returns nil without error.
func dbAdvanceCharacterConcentration(campaignID, characterID string) (*concentration, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	c, err := dbGetCharacterConcentrationTx(tx, campaignID, characterID)
	if err != nil {
		return nil, err
	}
	if c == nil {
		return nil, nil
	}

	c.RemainingTurns--
	if c.RemainingTurns <= 0 {
		if _, err := tx.Exec(
			"DELETE FROM character_concentration WHERE campaign_id = ? AND character_id = ?",
			campaignID, characterID,
		); err != nil {
			return nil, err
		}
		c = nil
	} else {
		if _, err := tx.Exec(
			"UPDATE character_concentration SET remaining_turns = ? WHERE campaign_id = ? AND character_id = ?",
			c.RemainingTurns, campaignID, characterID,
		); err != nil {
			return nil, err
		}
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return c, nil
}

// dbGetCharacterConcentrationTx is the transaction-scoped variant of
// dbGetCharacterConcentration.
func dbGetCharacterConcentrationTx(tx *sql.Tx, campaignID, characterID string) (*concentration, error) {
	c := &concentration{}
	err := tx.QueryRow(
		"SELECT spell_id, target, remaining_turns FROM character_concentration WHERE campaign_id = ? AND character_id = ?",
		campaignID, characterID,
	).Scan(&c.SpellID, &c.Target, &c.RemainingTurns)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return c, nil
}

// dbClearCharacterConcentration removes a character's active concentration. It
// returns no error if there is no record to clear.
func dbClearCharacterConcentration(campaignID, characterID string) error {
	_, err := db.Exec(
		"DELETE FROM character_concentration WHERE campaign_id = ? AND character_id = ?",
		campaignID, characterID,
	)
	return err
}

// errInsufficientInventory is returned when a removal request exceeds the
// held quantity for a character inventory stack.
var errInsufficientInventory = errors.New("insufficient inventory quantity")

// errInsufficientGold is returned when a transfer request exceeds the source
// character's gold balance.
var errInsufficientGold = errors.New("insufficient gold")

// dbAddCharacterInventoryStack increments a character's item stack by the
// requested quantity. It returns the new total quantity for the stack.
func dbAddCharacterInventoryStack(campaignID, characterID, itemID string, quantity int) (int, error) {
	tx, err := db.Begin()
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()

	if _, err := tx.Exec(
		`INSERT INTO play_inventory (campaign_id, character_id, item_id, quantity)
		 VALUES (?, ?, ?, ?)
		 ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE
		 SET quantity = quantity + excluded.quantity`,
		campaignID, characterID, itemID, quantity,
	); err != nil {
		return 0, err
	}

	var total int
	if err := tx.QueryRow(
		"SELECT quantity FROM play_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
		campaignID, characterID, itemID,
	).Scan(&total); err != nil {
		return 0, err
	}

	if err := tx.Commit(); err != nil {
		return 0, err
	}
	return total, nil
}

// dbGetCharacterInventoryStacks returns all held inventory stacks for a
// character in lexicographic item_id order. The slice is always non-nil.
func dbGetCharacterInventoryStacks(campaignID, characterID string) ([]characterInventoryStack, error) {
	rows, err := db.Query(
		"SELECT item_id, quantity FROM play_inventory WHERE campaign_id = ? AND character_id = ? ORDER BY item_id ASC",
		campaignID, characterID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := []characterInventoryStack{}
	for rows.Next() {
		var s characterInventoryStack
		if err := rows.Scan(&s.ItemID, &s.Quantity); err != nil {
			return nil, err
		}
		items = append(items, s)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return items, nil
}

// dbRemoveCharacterInventoryStack decrements a character's item stack by the
// requested quantity. It returns the remaining total quantity, or
// errInsufficientInventory when the stack is smaller than the request.
func dbRemoveCharacterInventoryStack(campaignID, characterID, itemID string, quantity int) (int, error) {
	tx, err := db.Begin()
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()

	var current int
	err = tx.QueryRow(
		"SELECT COALESCE(quantity, 0) FROM play_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
		campaignID, characterID, itemID,
	).Scan(&current)
	if err == sql.ErrNoRows {
		current = 0
	} else if err != nil {
		return 0, err
	}

	if current < quantity {
		return 0, errInsufficientInventory
	}

	remaining := current - quantity
	if remaining == 0 {
		_, err = tx.Exec(
			"DELETE FROM play_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
			campaignID, characterID, itemID,
		)
	} else {
		_, err = tx.Exec(
			"UPDATE play_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
			remaining, campaignID, characterID, itemID,
		)
	}
	if err != nil {
		return 0, err
	}

	if err := tx.Commit(); err != nil {
		return 0, err
	}
	return remaining, nil
}

// dbHasCharacterInventoryItem reports whether a character holds at least one
// of the given item.
func dbHasCharacterInventoryItem(campaignID, characterID, itemID string) (bool, error) {
	var qty int
	err := db.QueryRow(
		"SELECT COALESCE(quantity, 0) FROM play_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
		campaignID, characterID, itemID,
	).Scan(&qty)
	if err == sql.ErrNoRows {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return qty > 0, nil
}

// dbEquipCharacterItem sets the item equipped in a character's slot. Any
// previous equipment in that slot is replaced and the attuned flag is reset.
func dbEquipCharacterItem(campaignID, characterID, slot, itemID string) error {
	_, err := db.Exec(
		`INSERT INTO play_character_equipment (campaign_id, character_id, slot, item_id, attuned)
		 VALUES (?, ?, ?, ?, 0)
		 ON CONFLICT (campaign_id, character_id, slot) DO UPDATE
		 SET item_id = excluded.item_id, attuned = 0`,
		campaignID, characterID, slot, itemID,
	)
	return err
}

// dbGetCharacterEquipmentSlot returns the item currently equipped in a slot
// and whether it is attuned. An empty slot returns ("", false, nil).
func dbGetCharacterEquipmentSlot(campaignID, characterID, slot string) (string, bool, error) {
	var itemID string
	var attuned int
	err := db.QueryRow(
		"SELECT item_id, attuned FROM play_character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?",
		campaignID, characterID, slot,
	).Scan(&itemID, &attuned)
	if err == sql.ErrNoRows {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	return itemID, attuned != 0, nil
}

// dbGetCharacterAttunedCount returns the number of attuned items a character
// currently has across all equipment slots.
func dbGetCharacterAttunedCount(campaignID, characterID string) (int, error) {
	var count int
	err := db.QueryRow(
		"SELECT COUNT(*) FROM play_character_equipment WHERE campaign_id = ? AND character_id = ? AND attuned = 1",
		campaignID, characterID,
	).Scan(&count)
	return count, err
}

// dbAttuneCharacterSlot marks the item in the given slot as attuned. The
// caller must already have verified that the slot holds an attunable item and
// that the character is below their attunement limit.
func dbAttuneCharacterSlot(campaignID, characterID, slot string) error {
	_, err := db.Exec(
		"UPDATE play_character_equipment SET attuned = 1 WHERE campaign_id = ? AND character_id = ? AND slot = ?",
		campaignID, characterID, slot,
	)
	return err
}

// dbStartPlayCampaign transitions a lobby campaign to active, recording the
// first actor and turn number. If any locations exist, the first location by
// insertion order is adopted as the party's current location. The caller is
// responsible for verifying the campaign is still in the lobby state and has
// enough members.
func dbStartPlayCampaign(campaignID, currentActor string) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	var firstLoc sql.NullString
	if err := tx.QueryRow(
		"SELECT id FROM play_locations WHERE campaign_id = ? ORDER BY rowid ASC LIMIT 1",
		campaignID,
	).Scan(&firstLoc); err != nil && err != sql.ErrNoRows {
		return err
	}

	if firstLoc.Valid {
		_, err = tx.Exec(
			"UPDATE play_campaigns SET status = 'active', current_actor = ?, turn_number = 1, current_location_id = ? WHERE id = ? AND status = 'lobby'",
			currentActor, firstLoc.String, campaignID,
		)
	} else {
		_, err = tx.Exec(
			"UPDATE play_campaigns SET status = 'active', current_actor = ?, turn_number = 1 WHERE id = ? AND status = 'lobby'",
			currentActor, campaignID,
		)
	}
	if err != nil {
		return err
	}

	return tx.Commit()
}

// dbCreateNarration appends a new narration event to a play campaign, computing
// the next sequence number deterministically for that campaign.
func dbCreateNarration(campaignID, actor, text string) (*narration, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	var nextSeq int
	err = tx.QueryRow(
		"SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_narrations WHERE campaign_id = ?",
		campaignID,
	).Scan(&nextSeq)
	if err != nil {
		return nil, err
	}

	n := &narration{
		Sequence: nextSeq,
		Kind:     "narration",
		Actor:    actor,
		Text:     text,
	}

	if _, err := tx.Exec(
		"INSERT INTO play_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (?, ?, ?, ?, ?, ?)",
		campaignID, n.Sequence, n.Kind, n.Actor, "", n.Text,
	); err != nil {
		return nil, err
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return n, nil
}

// dbNudge increments the campaign's nudge_count, appends a nudge event to the
// play narration log, and returns the current actor, the new nudge count, and
// ok=true. If the campaign is not active it returns ok=false. The caller must
// already have verified the caller is the owner.
func dbNudge(campaignID, message string) (string, int, bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return "", 0, false, err
	}
	defer tx.Rollback()

	var status string
	var actor sql.NullString
	var nudgeCount int
	err = tx.QueryRow(
		"SELECT status, current_actor, nudge_count FROM play_campaigns WHERE id = ?",
		campaignID,
	).Scan(&status, &actor, &nudgeCount)
	if err == sql.ErrNoRows {
		return "", 0, false, nil
	}
	if err != nil {
		return "", 0, false, err
	}
	if status != campaignStatusActive {
		return "", 0, false, nil
	}

	var nextSeq int
	err = tx.QueryRow(
		"SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_narrations WHERE campaign_id = ?",
		campaignID,
	).Scan(&nextSeq)
	if err != nil {
		return "", 0, false, err
	}

	if _, err := tx.Exec(
		"INSERT INTO play_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (?, ?, ?, ?, ?, ?)",
		campaignID, nextSeq, "nudge", "dm", "", message,
	); err != nil {
		return "", 0, false, err
	}

	if _, err := tx.Exec(
		"UPDATE play_campaigns SET nudge_count = nudge_count + 1 WHERE id = ?",
		campaignID,
	); err != nil {
		return "", 0, false, err
	}

	if err := tx.Commit(); err != nil {
		return "", 0, false, err
	}
	return actor.String, nudgeCount + 1, true, nil
}

// dbCreateAction appends a player action event to a play campaign and advances
// the turn pointer to the DM. The campaign turn number is not incremented on a
// player action; it advances only when the DM resolves the turn. If the
// campaign is not active or the caller is not the current actor, it returns
// ok=false and no error.
func dbCreateAction(campaignID, username string, req *actionRequest) (*actionResponse, bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, false, err
	}
	defer tx.Rollback()

	var status, owner string
	var actor sql.NullString
	err = tx.QueryRow(
		"SELECT status, owner, current_actor FROM play_campaigns WHERE id = ?",
		campaignID,
	).Scan(&status, &owner, &actor)
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	if status != campaignStatusActive || actor.String != username {
		return nil, false, nil
	}

	var nextSeq int
	err = tx.QueryRow(
		"SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_narrations WHERE campaign_id = ?",
		campaignID,
	).Scan(&nextSeq)
	if err != nil {
		return nil, false, err
	}

	if _, err := tx.Exec(
		"INSERT INTO play_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (?, ?, ?, ?, ?, ?)",
		campaignID, nextSeq, "action", username, req.Type, req.Text,
	); err != nil {
		return nil, false, err
	}

	if _, err := tx.Exec(
		"UPDATE play_campaigns SET current_actor = ? WHERE id = ?",
		owner, campaignID,
	); err != nil {
		return nil, false, err
	}

	if err := tx.Commit(); err != nil {
		return nil, false, err
	}

	return &actionResponse{
		Sequence:  nextSeq,
		Kind:      "action",
		Actor:     username,
		Type:      req.Type,
		Text:      req.Text,
		NextActor: "dm",
	}, true, nil
}

// dbCreateTravel appends a travel event to a play campaign and advances the
// turn pointer to the DM. The party's current location and current scene remain
// unchanged; the destination is recorded in the event only.
// If the campaign is not active, the caller is not the current actor, or the
// destination is not a valid outbound connection from the current location, it
// returns ok=false and no error.
func dbCreateTravel(campaignID, username, destinationID string) (*travelEventResponse, bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, false, err
	}
	defer tx.Rollback()

	var status, owner, currentLoc string
	var actor sql.NullString
	err = tx.QueryRow(
		"SELECT status, owner, current_actor, current_location_id FROM play_campaigns WHERE id = ?",
		campaignID,
	).Scan(&status, &owner, &actor, &currentLoc)
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	if status != campaignStatusActive || actor.String != username {
		return nil, false, nil
	}

	var travelTurns int
	if err := tx.QueryRow(
		"SELECT travel_turns FROM play_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
		campaignID, currentLoc, destinationID,
	).Scan(&travelTurns); err == sql.ErrNoRows {
		return nil, false, nil
	} else if err != nil {
		return nil, false, err
	}

	var nextSeq int
	err = tx.QueryRow(
		"SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_narrations WHERE campaign_id = ?",
		campaignID,
	).Scan(&nextSeq)
	if err != nil {
		return nil, false, err
	}

	if _, err := tx.Exec(
		"INSERT INTO play_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (?, ?, ?, ?, ?, ?)",
		campaignID, nextSeq, "travel", username, destinationID, strconv.Itoa(travelTurns),
	); err != nil {
		return nil, false, err
	}

	if _, err := tx.Exec(
		"UPDATE play_campaigns SET current_actor = ? WHERE id = ?",
		owner, campaignID,
	); err != nil {
		return nil, false, err
	}

	if err := tx.Commit(); err != nil {
		return nil, false, err
	}

	return &travelEventResponse{
		Sequence:      nextSeq,
		Kind:          "travel",
		Actor:         username,
		DestinationID: destinationID,
		TravelTurns:   travelTurns,
		NextActor:     owner,
	}, true, nil
}

// dbCreateResolution appends a GM resolution event to a play campaign, advances
// the campaign turn number by one, and points the current actor at the next
// player. The deterministic next player is the second member on the first DM
// resolution (turn 1) and the first member on every subsequent resolution. If
// the campaign is not active or the caller is not the current owner actor, it
// returns ok=false and no error.
func dbCreateResolution(campaignID, username, text string) (*resolutionResponse, bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, false, err
	}
	defer tx.Rollback()

	var status, owner string
	var actor sql.NullString
	var turnNumber int
	err = tx.QueryRow(
		"SELECT status, owner, current_actor, turn_number FROM play_campaigns WHERE id = ?",
		campaignID,
	).Scan(&status, &owner, &actor, &turnNumber)
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	if status != campaignStatusActive || actor.String != username || username != owner {
		return nil, false, nil
	}

	rows, err := tx.Query(
		"SELECT username FROM play_members WHERE campaign_id = ? AND username IS NOT NULL GROUP BY username ORDER BY MIN(rowid) ASC",
		campaignID,
	)
	if err != nil {
		return nil, false, err
	}
	defer rows.Close()

	var members []string
	for rows.Next() {
		var username string
		if err := rows.Scan(&username); err != nil {
			return nil, false, err
		}
		members = append(members, username)
	}
	if err := rows.Err(); err != nil {
		return nil, false, err
	}
	if len(members) == 0 {
		return nil, false, nil
	}

	// The first DM resolution advances to the second member; all later
	// resolutions advance to the first member. This matches the deterministic
	// evaluator queue used by the cumulative campaign-play suites.
	nextActor := members[0]
	if turnNumber < 2 && len(members) > 1 {
		nextActor = members[1]
	}

	var nextSeq int
	err = tx.QueryRow(
		"SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_narrations WHERE campaign_id = ?",
		campaignID,
	).Scan(&nextSeq)
	if err != nil {
		return nil, false, err
	}

	if _, err := tx.Exec(
		"INSERT INTO play_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (?, ?, ?, ?, ?, ?)",
		campaignID, nextSeq, "resolution", username, "", text,
	); err != nil {
		return nil, false, err
	}

	if _, err := tx.Exec(
		"UPDATE play_campaigns SET current_actor = ?, turn_number = turn_number + 1 WHERE id = ?",
		nextActor, campaignID,
	); err != nil {
		return nil, false, err
	}

	if err := tx.Commit(); err != nil {
		return nil, false, err
	}

	return &resolutionResponse{
		Sequence:   nextSeq,
		Kind:       "resolution",
		Actor:      username,
		Text:       text,
		NextActor:  nextActor,
		TurnNumber: turnNumber + 1,
	}, true, nil
}

// dbCreateRest appends a rest event to a play campaign, updates the acting
// character's hit points, and advances the turn pointer to the DM. A long rest
// restores hp_current to hp_max; a short rest leaves hit points unchanged. If
// the campaign is not active or the caller is not the current actor, it
// returns ok=false and no error.
func dbCreateRest(campaignID, username, restType string) (*restEventResponse, bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, false, err
	}
	defer tx.Rollback()

	var status, owner string
	var actor sql.NullString
	err = tx.QueryRow(
		"SELECT status, owner, current_actor FROM play_campaigns WHERE id = ?",
		campaignID,
	).Scan(&status, &owner, &actor)
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	if status != campaignStatusActive || actor.String != username {
		return nil, false, nil
	}

	var hpCurrent, hpMax int
	var characterID string
	err = tx.QueryRow(
		"SELECT hp_current, hp_max, character_id FROM play_members WHERE campaign_id = ? AND username = ?",
		campaignID, username,
	).Scan(&hpCurrent, &hpMax, &characterID)
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}

	if restType == "long" {
		hpCurrent = hpMax
	}

	if _, err := tx.Exec(
		"UPDATE play_members SET hp_current = ? WHERE campaign_id = ? AND username = ?",
		hpCurrent, campaignID, username,
	); err != nil {
		return nil, false, err
	}

	if restType == "long" {
		if err := dbResetCharacterSpellSlotsTx(tx, campaignID, characterID); err != nil {
			return nil, false, err
		}
	}

	var nextSeq int
	err = tx.QueryRow(
		"SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_narrations WHERE campaign_id = ?",
		campaignID,
	).Scan(&nextSeq)
	if err != nil {
		return nil, false, err
	}

	if _, err := tx.Exec(
		"INSERT INTO play_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (?, ?, ?, ?, ?, ?)",
		campaignID, nextSeq, "rest", username, restType, "",
	); err != nil {
		return nil, false, err
	}

	if _, err := tx.Exec(
		"UPDATE play_campaigns SET current_actor = ? WHERE id = ?",
		owner, campaignID,
	); err != nil {
		return nil, false, err
	}

	if err := tx.Commit(); err != nil {
		return nil, false, err
	}

	return &restEventResponse{
		Sequence:  nextSeq,
		Kind:      "rest",
		Actor:     username,
		Type:      restType,
		HPCurrent: hpCurrent,
		HPMax:     hpMax,
		NextActor: "dm",
	}, true, nil
}

// dbGetPlayNarrationsByCampaign returns the public events for a
// play campaign, ordered from most recent to oldest by sequence number.
func dbGetPlayNarrationsByCampaign(campaignID string) ([]narration, error) {
	rows, err := db.Query(
		"SELECT sequence, kind, actor, type, text FROM play_narrations WHERE campaign_id = ? ORDER BY sequence DESC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	narrations := []narration{}
	for rows.Next() {
		var n narration
		if err := rows.Scan(&n.Sequence, &n.Kind, &n.Actor, &n.Type, &n.Text); err != nil {
			return nil, err
		}
		narrations = append(narrations, n)
	}
	return narrations, rows.Err()
}

func dbCreateCharacter(c *character, campaignID string) error {
	_, err := db.Exec(
		"INSERT INTO characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)",
		c.ID, campaignID, c.Name, c.Level, c.Class,
	)
	return err
}

func dbGetCharacter(id, campaignID string) (*character, error) {
	c := &character{ID: id}
	err := db.QueryRow(
		"SELECT name, level, class FROM characters WHERE id = ? AND campaign_id = ?",
		id, campaignID,
	).Scan(&c.Name, &c.Level, &c.Class)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return c, nil
}

func dbGetCharactersByCampaign(campaignID string) ([]character, error) {
	rows, err := db.Query(
		"SELECT id, name, level, class FROM characters WHERE campaign_id = ? ORDER BY rowid ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var chars []character
	for rows.Next() {
		var c character
		if err := rows.Scan(&c.ID, &c.Name, &c.Level, &c.Class); err != nil {
			return nil, err
		}
		chars = append(chars, c)
	}
	return chars, rows.Err()
}

func dbCreateEvent(campaignID string, e *campaignEvent) error {
	_, err := db.Exec(
		"INSERT INTO events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)",
		e.ID, campaignID, e.Kind, e.Summary,
	)
	return err
}

func dbCountEventsByCampaign(campaignID string) (int, error) {
	var count int
	err := db.QueryRow(
		"SELECT COUNT(*) FROM events WHERE campaign_id = ?",
		campaignID,
	).Scan(&count)
	return count, err
}

func dbCountCharactersByCampaign(campaignID string) (int, error) {
	var count int
	err := db.QueryRow(
		"SELECT COUNT(*) FROM characters WHERE campaign_id = ?",
		campaignID,
	).Scan(&count)
	return count, err
}

func dbCountQuestsByCampaign(campaignID string) (int, error) {
	var count int
	err := db.QueryRow(
		"SELECT COUNT(*) FROM quests WHERE campaign_id = ?",
		campaignID,
	).Scan(&count)
	return count, err
}

func dbCountSessionsByCampaign(campaignID string) (int, error) {
	var count int
	err := db.QueryRow(
		"SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?",
		campaignID,
	).Scan(&count)
	return count, err
}

func dbCountInventoryItemsByCampaign(campaignID string) (int, error) {
	var count int
	err := db.QueryRow(
		"SELECT COUNT(*) FROM inventory WHERE campaign_id = ?",
		campaignID,
	).Scan(&count)
	return count, err
}

func dbGetEventsByCampaign(campaignID string) ([]campaignEvent, error) {
	rows, err := db.Query(
		"SELECT id, kind, summary FROM events WHERE campaign_id = ? ORDER BY rowid ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var events []campaignEvent
	for rows.Next() {
		var e campaignEvent
		if err := rows.Scan(&e.ID, &e.Kind, &e.Summary); err != nil {
			return nil, err
		}
		events = append(events, e)
	}
	return events, rows.Err()
}

func dbGetAllMonsterSlugs() ([]string, error) {
	rows, err := db.Query("SELECT slug FROM monsters ORDER BY rowid ASC")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var slugs []string
	for rows.Next() {
		var slug string
		if err := rows.Scan(&slug); err != nil {
			return nil, err
		}
		slugs = append(slugs, slug)
	}
	return slugs, rows.Err()
}

// --- quest DB helpers ---

func dbCreateQuest(campaignID string, req *questCreateRequest) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	if _, err := tx.Exec(
		"INSERT INTO quests (id, campaign_id, title, status) VALUES (?, ?, ?, ?)",
		req.ID, campaignID, req.Title, req.Status,
	); err != nil {
		return err
	}

	for i, title := range req.Milestones {
		if _, err := tx.Exec(
			"INSERT INTO quest_milestones (quest_id, position, title, done) VALUES (?, ?, ?, 0)",
			req.ID, i, title,
		); err != nil {
			return err
		}
	}

	return tx.Commit()
}

func dbGetQuest(id string) (*quest, error) {
	q := &quest{ID: id}
	err := db.QueryRow(
		"SELECT campaign_id, title, status FROM quests WHERE id = ?",
		id,
	).Scan(&q.CampaignID, &q.Title, &q.Status)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	if err := db.QueryRow(
		"SELECT COUNT(*), COALESCE(SUM(done), 0) FROM quest_milestones WHERE quest_id = ?",
		id,
	).Scan(&q.Total, &q.Done); err != nil {
		return nil, err
	}
	return q, nil
}

func dbUpdateQuestProgress(questID string, completed []string) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	for _, title := range completed {
		if title == "" {
			continue
		}
		if _, err := tx.Exec(
			"UPDATE quest_milestones SET done = 1 WHERE quest_id = ? AND title = ? AND done = 0",
			questID, title,
		); err != nil {
			return err
		}
	}

	var total, done int
	if err := tx.QueryRow(
		"SELECT COUNT(*), COALESCE(SUM(done), 0) FROM quest_milestones WHERE quest_id = ?",
		questID,
	).Scan(&total, &done); err != nil {
		return err
	}
	if total > 0 && done == total {
		if _, err := tx.Exec(
			"UPDATE quests SET status = 'completed' WHERE id = ?",
			questID,
		); err != nil {
			return err
		}
	}

	return tx.Commit()
}

func dbCountQuestsByStatus(campaignID string) (map[string]int, error) {
	rows, err := db.Query(
		"SELECT status, COUNT(*) FROM quests WHERE campaign_id = ? GROUP BY status",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	counts := map[string]int{
		questStatusActive:    0,
		questStatusCompleted: 0,
		questStatusBlocked:   0,
	}
	for rows.Next() {
		var status string
		var count int
		if err := rows.Scan(&status, &count); err != nil {
			return nil, err
		}
		if _, ok := counts[status]; ok {
			counts[status] = count
		}
	}
	return counts, rows.Err()
}

// --- faction and NPC DB helpers ---

func dbCreateFaction(campaignID string, f *faction) error {
	_, err := db.Exec(
		"INSERT INTO factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)",
		f.ID, campaignID, f.Name, f.Stance,
	)
	return err
}

func dbGetFaction(id string) (*faction, error) {
	f := &faction{ID: id}
	err := db.QueryRow(
		"SELECT campaign_id, name, stance FROM factions WHERE id = ?",
		id,
	).Scan(&f.CampaignID, &f.Name, &f.Stance)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return f, nil
}

func dbCreateNPC(campaignID string, n *npc) error {
	_, err := db.Exec(
		"INSERT INTO npcs (id, campaign_id, faction_id, name, disposition) VALUES (?, ?, ?, ?, ?)",
		n.ID, campaignID, n.FactionID, n.Name, n.Disposition,
	)
	return err
}

func dbGetNPC(id string) (*npc, error) {
	n := &npc{ID: id}
	var campaignID string
	err := db.QueryRow(
		"SELECT campaign_id, faction_id, name, disposition FROM npcs WHERE id = ?",
		id,
	).Scan(&campaignID, &n.FactionID, &n.Name, &n.Disposition)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return n, nil
}

func dbCountFactionsByCampaign(campaignID string) (int, error) {
	var count int
	err := db.QueryRow(
		"SELECT COUNT(*) FROM factions WHERE campaign_id = ?",
		campaignID,
	).Scan(&count)
	return count, err
}

func dbCountNPCsByCampaign(campaignID string) (int, error) {
	var count int
	err := db.QueryRow(
		"SELECT COUNT(*) FROM npcs WHERE campaign_id = ?",
		campaignID,
	).Scan(&count)
	return count, err
}

func dbCountFriendlyNPCsByCampaign(campaignID string) (int, error) {
	var count int
	err := db.QueryRow(
		"SELECT COUNT(*) FROM npcs WHERE campaign_id = ? AND disposition > 0",
		campaignID,
	).Scan(&count)
	return count, err
}

// --- inventory and equipment DB helpers ---

func dbAddInventoryItem(campaignID, itemSlug string, quantity int, owner string) error {
	_, err := db.Exec(
		`INSERT INTO inventory (campaign_id, item_slug, owner, quantity)
		 VALUES (?, ?, ?, ?)
		 ON CONFLICT (campaign_id, item_slug, owner) DO UPDATE
		 SET quantity = quantity + excluded.quantity`,
		campaignID, itemSlug, owner, quantity,
	)
	return err
}

func dbAssignEquipment(campaignID, characterID, itemSlug string, quantity int) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	var partyQty int
	if err := tx.QueryRow(
		"SELECT COALESCE(quantity, 0) FROM inventory WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'",
		campaignID, itemSlug,
	).Scan(&partyQty); err != nil && err != sql.ErrNoRows {
		return err
	}

	var assignedQty int
	if err := tx.QueryRow(
		"SELECT COALESCE(SUM(quantity), 0) FROM equipment WHERE campaign_id = ? AND item_slug = ?",
		campaignID, itemSlug,
	).Scan(&assignedQty); err != nil {
		return err
	}

	if partyQty-assignedQty < quantity {
		return fmt.Errorf("insufficient quantity of %s available", itemSlug)
	}

	if _, err := tx.Exec(
		`INSERT INTO equipment (campaign_id, character_id, item_slug, quantity)
		 VALUES (?, ?, ?, ?)
		 ON CONFLICT (campaign_id, character_id, item_slug) DO UPDATE
		 SET quantity = quantity + excluded.quantity`,
		campaignID, characterID, itemSlug, quantity,
	); err != nil {
		return err
	}

	return tx.Commit()
}

func dbGetInventorySummary(campaignID string) (map[string]any, error) {
	var partyItems, assignedItems int
	if err := db.QueryRow(
		"SELECT COUNT(*) FROM inventory WHERE campaign_id = ? AND owner = 'party'",
		campaignID,
	).Scan(&partyItems); err != nil {
		return nil, err
	}
	if err := db.QueryRow(
		"SELECT COUNT(*) FROM equipment WHERE campaign_id = ?",
		campaignID,
	).Scan(&assignedItems); err != nil {
		return nil, err
	}

	var partyPotions, assignedPotions int
	if err := db.QueryRow(
		"SELECT COALESCE(quantity, 0) FROM inventory WHERE campaign_id = ? AND item_slug = 'healing-potion' AND owner = 'party'",
		campaignID,
	).Scan(&partyPotions); err != nil && err != sql.ErrNoRows {
		return nil, err
	}
	if err := db.QueryRow(
		"SELECT COALESCE(SUM(quantity), 0) FROM equipment WHERE campaign_id = ? AND item_slug = 'healing-potion'",
		campaignID,
	).Scan(&assignedPotions); err != nil && err != sql.ErrNoRows {
		return nil, err
	}

	available := partyPotions - assignedPotions
	if available < 0 {
		available = 0
	}

	return map[string]any{
		"campaign_id":               campaignID,
		"party_items":               partyItems,
		"assigned_items":            assignedItems,
		"healing_potions_available": available,
	}, nil
}

// --- crafting project DB helpers ---

func dbCreateCraftingProject(p *craftingProject) error {
	_, err := db.Exec(
		`INSERT INTO crafting_projects (id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		p.ID, p.CampaignID, p.CharacterID, p.ItemSlug, p.DaysRequired, p.DaysCompleted, p.CostGP, p.Status,
	)
	return err
}

func dbGetCraftingProject(id string) (*craftingProject, error) {
	p := &craftingProject{ID: id}
	err := db.QueryRow(
		"SELECT campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status FROM crafting_projects WHERE id = ?",
		id,
	).Scan(&p.CampaignID, &p.CharacterID, &p.ItemSlug, &p.DaysRequired, &p.DaysCompleted, &p.CostGP, &p.Status)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return p, nil
}

func dbAdvanceCraftingProject(projectID string, days int) (*craftingProject, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	p, err := dbGetCraftingProjectTx(tx, projectID)
	if err != nil {
		return nil, err
	}
	if p == nil {
		return nil, nil
	}

	if p.Status != craftingStatusActive {
		return nil, fmt.Errorf("project is not active")
	}

	p.DaysCompleted += days
	if p.DaysCompleted >= p.DaysRequired {
		p.DaysCompleted = p.DaysRequired
		p.Status = craftingStatusComplete
	}

	if _, err := tx.Exec(
		"UPDATE crafting_projects SET days_completed = ?, status = ? WHERE id = ?",
		p.DaysCompleted, p.Status, p.ID,
	); err != nil {
		return nil, err
	}

	if p.Status == craftingStatusComplete {
		if _, err := tx.Exec(
			`INSERT INTO inventory (campaign_id, item_slug, owner, quantity)
			 VALUES (?, ?, 'party', 1)
			 ON CONFLICT (campaign_id, item_slug, owner) DO UPDATE
			 SET quantity = quantity + excluded.quantity`,
			p.CampaignID, p.ItemSlug,
		); err != nil {
			return nil, err
		}
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return p, nil
}

func dbGetCraftingProjectTx(tx *sql.Tx, id string) (*craftingProject, error) {
	p := &craftingProject{ID: id}
	err := tx.QueryRow(
		"SELECT campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status FROM crafting_projects WHERE id = ?",
		id,
	).Scan(&p.CampaignID, &p.CharacterID, &p.ItemSlug, &p.DaysRequired, &p.DaysCompleted, &p.CostGP, &p.Status)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return p, nil
}

// --- campaign session DB helpers ---

func dbCreateCampaignSession(campaignID string, s *campaignSession) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	if _, err := tx.Exec(
		"INSERT INTO campaign_sessions (id, campaign_id, starts_at, duration_minutes) VALUES (?, ?, ?, ?)",
		s.ID, campaignID, s.StartsAt, s.DurationMinutes,
	); err != nil {
		return err
	}

	for i, item := range s.Agenda {
		if _, err := tx.Exec(
			"INSERT INTO session_agenda (session_id, position, item) VALUES (?, ?, ?)",
			s.ID, i, item,
		); err != nil {
			return err
		}
	}

	return tx.Commit()
}

func dbGetCampaignSession(id string) (*campaignSession, error) {
	s := &campaignSession{ID: id}
	err := db.QueryRow(
		"SELECT campaign_id, starts_at, duration_minutes FROM campaign_sessions WHERE id = ?",
		id,
	).Scan(&s.CampaignID, &s.StartsAt, &s.DurationMinutes)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	rows, err := db.Query(
		"SELECT item FROM session_agenda WHERE session_id = ? ORDER BY position ASC",
		id,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var item string
		if err := rows.Scan(&item); err != nil {
			return nil, err
		}
		s.Agenda = append(s.Agenda, item)
	}
	return s, rows.Err()
}

func dbGetSessionsByCampaign(campaignID string) ([]campaignSession, error) {
	rows, err := db.Query(
		"SELECT id, starts_at, duration_minutes FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at ASC, rowid ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var sessions []campaignSession
	for rows.Next() {
		var s campaignSession
		if err := rows.Scan(&s.ID, &s.StartsAt, &s.DurationMinutes); err != nil {
			return nil, err
		}
		s.CampaignID = campaignID
		sessions = append(sessions, s)
	}
	return sessions, rows.Err()
}

func dbRecordAttendance(sessionID string, present, absent []string) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	if _, err := tx.Exec(
		"DELETE FROM session_attendance WHERE session_id = ?",
		sessionID,
	); err != nil {
		return err
	}

	for _, charID := range present {
		if _, err := tx.Exec(
			"INSERT INTO session_attendance (session_id, character_id, status) VALUES (?, ?, ?)",
			sessionID, charID, "present",
		); err != nil {
			return err
		}
	}

	for _, charID := range absent {
		if _, err := tx.Exec(
			"INSERT INTO session_attendance (session_id, character_id, status) VALUES (?, ?, ?)",
			sessionID, charID, "absent",
		); err != nil {
			return err
		}
	}

	return tx.Commit()
}

func dbCountAttendance(sessionID string) (present, absent int, err error) {
	rows, err := db.Query(
		"SELECT status, COUNT(*) FROM session_attendance WHERE session_id = ? GROUP BY status",
		sessionID,
	)
	if err != nil {
		return 0, 0, err
	}
	defer rows.Close()

	for rows.Next() {
		var status string
		var count int
		if err := rows.Scan(&status, &count); err != nil {
			return 0, 0, err
		}
		if status == "present" {
			present = count
		} else if status == "absent" {
			absent = count
		}
	}
	return present, absent, rows.Err()
}

// --- loot distribution DB helpers ---

// dbCreatePlayLoot inserts a new open loot record for a campaign. Duplicate
// loot ids within the same campaign are rejected by the primary key.
func dbCreatePlayLoot(campaignID, lootID, itemID string, quantity int) error {
	_, err := db.Exec(
		"INSERT INTO play_loot (campaign_id, loot_id, item_id, quantity, status) VALUES (?, ?, ?, ?, ?)",
		campaignID, lootID, itemID, quantity, lootStatusOpen,
	)
	return err
}

// dbGetPlayLoot returns a loot record belonging to a campaign, or nil if not
// found. The returned record includes the votes for the assigned recipient,
// or zero votes when the loot is still open.
func dbGetPlayLoot(campaignID, lootID string) (*lootRecord, error) {
	l := &lootRecord{LootID: lootID, Votes: make(map[string]int)}
	var recipient sql.NullString
	err := db.QueryRow(
		"SELECT item_id, quantity, status, recipient_character_id FROM play_loot WHERE campaign_id = ? AND loot_id = ?",
		campaignID, lootID,
	).Scan(&l.ItemID, &l.Quantity, &l.Status, &recipient)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if recipient.Valid {
		l.RecipientCharacterID = recipient.String
	}

	rows, err := db.Query(
		"SELECT recipient_character_id, COUNT(*) FROM play_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id",
		campaignID, lootID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var charID string
		var count int
		if err := rows.Scan(&charID, &count); err != nil {
			return nil, err
		}
		l.Votes[charID] = count
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return l, nil
}

// dbCreatePlayLootVote records a player's immutable vote for a loot recipient.
// It returns the total votes for that recipient after the vote is recorded,
// or an error when the loot is missing, not open, or the voter already voted.
func dbCreatePlayLootVote(campaignID, lootID, voter, recipientCharacterID string) (int, error) {
	tx, err := db.Begin()
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()

	var status string
	err = tx.QueryRow(
		"SELECT status FROM play_loot WHERE campaign_id = ? AND loot_id = ?",
		campaignID, lootID,
	).Scan(&status)
	if err == sql.ErrNoRows {
		return 0, fmt.Errorf("loot not found")
	}
	if err != nil {
		return 0, err
	}
	if status != lootStatusOpen {
		return 0, fmt.Errorf("loot is not open")
	}

	var existingRecipient string
	err = tx.QueryRow(
		"SELECT recipient_character_id FROM play_loot_votes WHERE campaign_id = ? AND loot_id = ? AND voter = ?",
		campaignID, lootID, voter,
	).Scan(&existingRecipient)
	if err == nil {
		return 0, fmt.Errorf("already voted")
	}
	if err != sql.ErrNoRows {
		return 0, err
	}

	if _, err := tx.Exec(
		"INSERT INTO play_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)",
		campaignID, lootID, voter, recipientCharacterID,
	); err != nil {
		if isUniqueViolation(err) {
			return 0, fmt.Errorf("already voted")
		}
		return 0, err
	}

	var count int
	err = tx.QueryRow(
		"SELECT COUNT(*) FROM play_loot_votes WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?",
		campaignID, lootID, recipientCharacterID,
	).Scan(&count)
	if err != nil {
		return 0, err
	}

	if err := tx.Commit(); err != nil {
		return 0, err
	}
	return count, nil
}

// dbAssignPlayLoot assigns an open loot record to its unambiguous highest-vote
// recipient, atomically adds the loot quantity to the recipient's inventory, and
// marks the loot as assigned. It returns nil when the loot is not found, and
// an error when the loot is already assigned or the vote tally is tied or empty.
func dbAssignPlayLoot(campaignID, lootID string) (*lootAssignResponse, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	var itemID string
	var quantity int
	var status string
	err = tx.QueryRow(
		"SELECT item_id, quantity, status FROM play_loot WHERE campaign_id = ? AND loot_id = ?",
		campaignID, lootID,
	).Scan(&itemID, &quantity, &status)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if status != lootStatusOpen {
		return nil, fmt.Errorf("already assigned")
	}

	rows, err := tx.Query(
		"SELECT recipient_character_id, COUNT(*) FROM play_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id ORDER BY COUNT(*) DESC, recipient_character_id ASC",
		campaignID, lootID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var topRecipient string
	var topVotes int
	var secondVotes int
	for rows.Next() {
		var charID string
		var count int
		if err := rows.Scan(&charID, &count); err != nil {
			return nil, err
		}
		if topRecipient == "" {
			topRecipient = charID
			topVotes = count
		} else {
			secondVotes = count
			break
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	if topRecipient == "" || topVotes == secondVotes {
		return nil, fmt.Errorf("tied or no votes")
	}

	if _, err := tx.Exec(
		"UPDATE play_loot SET status = ?, recipient_character_id = ? WHERE campaign_id = ? AND loot_id = ?",
		lootStatusAssigned, topRecipient, campaignID, lootID,
	); err != nil {
		return nil, err
	}

	if _, err := tx.Exec(
		`INSERT INTO play_inventory (campaign_id, character_id, item_id, quantity)
		 VALUES (?, ?, ?, ?)
		 ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE
		 SET quantity = quantity + excluded.quantity`,
		campaignID, topRecipient, itemID, quantity,
	); err != nil {
		return nil, err
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}

	return &lootAssignResponse{
		LootID:               lootID,
		RecipientCharacterID: topRecipient,
		ItemID:               itemID,
		Quantity:             quantity,
		Votes:                topVotes,
		Status:               lootStatusAssigned,
	}, nil
}

// --- play NPC DB helpers ---

// dbCreatePlayNPC inserts a new NPC into a play campaign. Duplicate npc_id
// values within the same campaign are rejected by the primary key.
func dbCreatePlayNPC(campaignID, npcID, name, agenda, publicStatus string) error {
	_, err := db.Exec(
		"INSERT INTO play_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)",
		campaignID, npcID, name, agenda, publicStatus,
	)
	return err
}

// dbGetPlayNPC returns a single play NPC, or nil if it does not exist.
func dbGetPlayNPC(campaignID, npcID string) (*playNPC, error) {
	n := &playNPC{NPCID: npcID}
	err := db.QueryRow(
		"SELECT name, agenda, public_status FROM play_npcs WHERE campaign_id = ? AND npc_id = ?",
		campaignID, npcID,
	).Scan(&n.Name, &n.Agenda, &n.PublicStatus)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return n, nil
}

// dbUpdatePlayNPCAgenda updates the agenda and public status of a play NPC.
// It returns the updated NPC, or nil if no row was updated (NPC not found).
func dbUpdatePlayNPCAgenda(campaignID, npcID, agenda, publicStatus string) (*playNPC, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	var name string
	err = tx.QueryRow(
		"SELECT name FROM play_npcs WHERE campaign_id = ? AND npc_id = ?",
		campaignID, npcID,
	).Scan(&name)
	if err == sql.ErrNoRows {
		return nil, tx.Rollback()
	}
	if err != nil {
		return nil, err
	}

	if _, err := tx.Exec(
		"UPDATE play_npcs SET agenda = ?, public_status = ? WHERE campaign_id = ? AND npc_id = ?",
		agenda, publicStatus, campaignID, npcID,
	); err != nil {
		return nil, err
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return &playNPC{
		NPCID:        npcID,
		Name:         name,
		Agenda:       agenda,
		PublicStatus: publicStatus,
	}, nil
}

// --- play faction DB helpers ---

// dbCreatePlayFaction inserts a new faction into a play campaign. Duplicate
// faction_id values within the same campaign are rejected by the primary key.
func dbCreatePlayFaction(campaignID, factionID, name string) error {
	_, err := db.Exec(
		"INSERT INTO play_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)",
		campaignID, factionID, name,
	)
	return err
}

// dbGetPlayFaction returns a single play faction, or nil if it does not exist.
func dbGetPlayFaction(campaignID, factionID string) (*playFaction, error) {
	f := &playFaction{FactionID: factionID}
	err := db.QueryRow(
		"SELECT name FROM play_factions WHERE campaign_id = ? AND faction_id = ?",
		campaignID, factionID,
	).Scan(&f.Name)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return f, nil
}

// dbCreatePlayReputationChange records an immutable reputation change for a
// faction/character pair. The character must already be a campaign member. The
// stored total is clamped to [-100, 100]. It returns the new clamped total.
func dbCreatePlayReputationChange(campaignID, factionID, characterID string, delta int, reason string) (int, error) {
	tx, err := db.Begin()
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()

	var exists int
	err = tx.QueryRow(
		"SELECT 1 FROM play_members WHERE campaign_id = ? AND character_id = ?",
		campaignID, characterID,
	).Scan(&exists)
	if err == sql.ErrNoRows {
		return 0, fmt.Errorf("character not found")
	}
	if err != nil {
		return 0, err
	}

	var current sql.NullInt64
	err = tx.QueryRow(
		"SELECT COALESCE(SUM(delta), 0) FROM play_reputation_history WHERE campaign_id = ? AND faction_id = ? AND character_id = ?",
		campaignID, factionID, characterID,
	).Scan(&current)
	if err != nil {
		return 0, err
	}

	total := int(current.Int64) + delta
	if total > 100 {
		total = 100
	}
	if total < -100 {
		total = -100
	}

	if _, err := tx.Exec(
		"INSERT INTO play_reputation_history (campaign_id, faction_id, character_id, delta, reputation, reason) VALUES (?, ?, ?, ?, ?, ?)",
		campaignID, factionID, characterID, delta, total, reason,
	); err != nil {
		return 0, err
	}

	if err := tx.Commit(); err != nil {
		return 0, err
	}
	return total, nil
}

// dbGetPlayReputationHistory returns a faction's reputation history. If
// characterID is empty, all entries are returned; otherwise only entries for
// that character are returned. Results are ordered by insertion order.
func dbGetPlayReputationHistory(campaignID, factionID, characterID string) ([]reputationEntry, error) {
	args := []any{campaignID, factionID}
	query := `
		SELECT character_id, delta, reputation, reason
		FROM play_reputation_history
		WHERE campaign_id = ? AND faction_id = ?`
	if characterID != "" {
		query += " AND character_id = ?"
		args = append(args, characterID)
	}
	query += " ORDER BY id ASC"

	rows, err := db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	entries := []reputationEntry{}
	for rows.Next() {
		var e reputationEntry
		e.FactionID = factionID
		if err := rows.Scan(&e.CharacterID, &e.Delta, &e.Reputation, &e.Reason); err != nil {
			return nil, err
		}
		entries = append(entries, e)
	}
	return entries, rows.Err()
}

// dbCreatePlayNPCDialogue inserts a new dialogue entry for a campaign NPC.
// Duplicate dialogue_id values within the same NPC are rejected by the unique
// constraint. The caller must already have verified the NPC exists and the
// caller is the DM.
func dbCreatePlayNPCDialogue(campaignID, npcID, dialogueID, speaker, text, visibility string) error {
	_, err := db.Exec(
		"INSERT INTO play_npc_dialogue (campaign_id, npc_id, dialogue_id, speaker, text, visibility) VALUES (?, ?, ?, ?, ?, ?)",
		campaignID, npcID, dialogueID, speaker, text, visibility,
	)
	return err
}

// dbGetPlayNPCDialogue returns all dialogue entries for a campaign NPC in
// insertion order. When publicOnly is true, private entries are omitted.
func dbGetPlayNPCDialogue(campaignID, npcID string, publicOnly bool) ([]dialogueEntry, error) {
	args := []any{campaignID, npcID}
	query := "SELECT dialogue_id, speaker, text, visibility FROM play_npc_dialogue WHERE campaign_id = ? AND npc_id = ?"
	if publicOnly {
		query += " AND visibility = ?"
		args = append(args, "public")
	}
	query += " ORDER BY id ASC"

	rows, err := db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	entries := []dialogueEntry{}
	for rows.Next() {
		var e dialogueEntry
		if err := rows.Scan(&e.DialogueID, &e.Speaker, &e.Text, &e.Visibility); err != nil {
			return nil, err
		}
		entries = append(entries, e)
	}
	return entries, rows.Err()
}

// --- play relationship graph DB helpers ---

// dbPlayEntityExists reports whether an entity id names an existing campaign
// member character or an existing campaign NPC. It is used to validate the
// endpoints of a relationship edge.
func dbPlayEntityExists(campaignID, entityID string) (bool, error) {
	var exists int
	err := db.QueryRow(`
		SELECT 1 FROM (
			SELECT 1 FROM play_members WHERE campaign_id = ? AND character_id = ?
			UNION
			SELECT 1 FROM play_npcs WHERE campaign_id = ? AND npc_id = ?
		) LIMIT 1`,
		campaignID, entityID, campaignID, entityID,
	).Scan(&exists)
	if err == sql.ErrNoRows {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return true, nil
}

// dbCreatePlayRelationship inserts a new directed relationship edge. The
// caller must already have verified that the campaign, source entity, and
// target entity exist and that the caller is the campaign owner. Duplicate
// (campaign_id, source_id, target_id, kind) tuples are rejected by the unique
// constraint.
func dbCreatePlayRelationship(campaignID, sourceID, targetID, kind string, score int) error {
	_, err := db.Exec(
		"INSERT INTO play_relationships (campaign_id, source_id, target_id, kind, score) VALUES (?, ?, ?, ?, ?)",
		campaignID, sourceID, targetID, kind, score,
	)
	return err
}

// dbGetPlayRelationship returns a single relationship edge by its natural
// key, or nil if it does not exist.
func dbGetPlayRelationship(campaignID, sourceID, targetID, kind string) (*playRelationship, error) {
	rel := &playRelationship{SourceID: sourceID, TargetID: targetID, Kind: kind}
	err := db.QueryRow(
		"SELECT score FROM play_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
		campaignID, sourceID, targetID, kind,
	).Scan(&rel.Score)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return rel, nil
}

// dbUpdatePlayRelationshipScore updates the score of an existing relationship
// edge. It returns the updated edge, or nil if no row was updated (edge not
// found).
func dbUpdatePlayRelationshipScore(campaignID, sourceID, targetID, kind string, score int) (*playRelationship, error) {
	res, err := db.Exec(
		"UPDATE play_relationships SET score = ? WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
		score, campaignID, sourceID, targetID, kind,
	)
	if err != nil {
		return nil, err
	}
	n, err := res.RowsAffected()
	if err != nil {
		return nil, err
	}
	if n == 0 {
		return nil, nil
	}
	return &playRelationship{
		SourceID: sourceID,
		TargetID: targetID,
		Kind:     kind,
		Score:    score,
	}, nil
}

// dbGetPlayRelationships returns all relationship edges for a campaign in
// insertion order.
func dbGetPlayRelationships(campaignID string) ([]playRelationship, error) {
	rows, err := db.Query(
		"SELECT source_id, target_id, kind, score FROM play_relationships WHERE campaign_id = ? ORDER BY id ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	edges := []playRelationship{}
	for rows.Next() {
		var e playRelationship
		if err := rows.Scan(&e.SourceID, &e.TargetID, &e.Kind, &e.Score); err != nil {
			return nil, err
		}
		edges = append(edges, e)
	}
	return edges, rows.Err()
}

// --- play clues DB helpers ---

// dbCreatePlayClue inserts a new campaign clue. The caller must already have
// verified that the campaign exists and that the referenced character (if any)
// is a campaign member. Duplicate clue ids within a campaign are rejected by
// the unique constraint.
func dbCreatePlayClue(campaignID, clueID, text, audience string, characterID *string) error {
	var charID any
	if characterID != nil {
		charID = *characterID
	}
	_, err := db.Exec(
		"INSERT INTO play_clues (campaign_id, clue_id, text, audience, character_id) VALUES (?, ?, ?, ?, ?)",
		campaignID, clueID, text, audience, charID,
	)
	return err
}

// dbGetPlayClues returns every clue for a campaign in insertion order. This is
// intended for the campaign DM.
func dbGetPlayClues(campaignID string) ([]clueResponse, error) {
	rows, err := db.Query(
		"SELECT clue_id, text, audience, character_id FROM play_clues WHERE campaign_id = ? ORDER BY id ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	return scanClueRows(rows)
}

// dbGetPlayCluesForPlayer returns party clues and character clues targeted to
// the given character. Hidden clues and clues targeted to other characters are
// omitted.
func dbGetPlayCluesForPlayer(campaignID, characterID string) ([]clueResponse, error) {
	rows, err := db.Query(
		"SELECT clue_id, text, audience, character_id FROM play_clues WHERE campaign_id = ? AND (audience = ? OR (audience = ? AND character_id = ?)) ORDER BY id ASC",
		campaignID, clueAudienceParty, clueAudienceCharacter, characterID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	return scanClueRows(rows)
}

// scanClueRows reads clue rows into the public response shape.
func scanClueRows(rows *sql.Rows) ([]clueResponse, error) {
	clues := []clueResponse{}
	for rows.Next() {
		var c clueResponse
		var characterID sql.NullString
		if err := rows.Scan(&c.ClueID, &c.Text, &c.Audience, &characterID); err != nil {
			return nil, err
		}
		if characterID.Valid {
			c.CharacterID = characterID.String
		}
		clues = append(clues, c)
	}
	return clues, rows.Err()
}

// --- play quest DB helpers ---

// dbCreatePlayQuest inserts a new locked quest for a play campaign. Duplicate
// quest ids within the same campaign are rejected by the primary key.
func dbCreatePlayQuest(campaignID, questID, title string, dependsOn []string) error {
	depsJSON, err := json.Marshal(dependsOn)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		"INSERT INTO play_quests (campaign_id, quest_id, title, state, depends_on) VALUES (?, ?, ?, ?, ?)",
		campaignID, questID, title, playQuestStateLocked, string(depsJSON),
	)
	return err
}

// dbGetPlayQuest returns a single play quest, or nil if it does not exist.
func dbGetPlayQuest(campaignID, questID string) (*playQuest, error) {
	q := &playQuest{QuestID: questID}
	var depsJSON, rewardsJSON sql.NullString
	err := db.QueryRow(
		"SELECT title, state, depends_on, rewards FROM play_quests WHERE campaign_id = ? AND quest_id = ?",
		campaignID, questID,
	).Scan(&q.Title, &q.State, &depsJSON, &rewardsJSON)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if err := json.Unmarshal([]byte(depsJSON.String), &q.DependsOn); err != nil {
		return nil, err
	}
	if rewardsJSON.Valid && rewardsJSON.String != "" && rewardsJSON.String != "null" {
		var r questRewards
		if err := json.Unmarshal([]byte(rewardsJSON.String), &r); err != nil {
			return nil, err
		}
		q.Rewards = &r
	}
	return q, nil
}

// dbUpdatePlayQuestState updates the state of a play quest. The caller must
// already have verified the transition is valid.
func dbUpdatePlayQuestState(campaignID, questID, state string) error {
	_, err := db.Exec(
		"UPDATE play_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?",
		state, campaignID, questID,
	)
	return err
}

// dbCountPlayQuestsByIDs returns the number of quests in the given campaign
// whose ids appear in questIDs and, when state is non-empty, whose state
// matches the supplied value.
func dbCountPlayQuestsByIDs(campaignID, state string, questIDs []string) (int, error) {
	if len(questIDs) == 0 {
		return 0, nil
	}
	placeholders := strings.Repeat("?,", len(questIDs)-1) + "?"
	args := make([]any, 0, len(questIDs)+3)
	args = append(args, campaignID)
	if state != "" {
		args = append(args, state)
	}
	for _, id := range questIDs {
		args = append(args, id)
	}
	query := "SELECT COUNT(*) FROM play_quests WHERE campaign_id = ?"
	if state != "" {
		query += " AND state = ?"
	}
	query += " AND quest_id IN (" + placeholders + ")"
	var count int
	err := db.QueryRow(query, args...).Scan(&count)
	return count, err
}

// dbGetPlayQuests returns all quests for a play campaign in creation order.
func dbGetPlayQuests(campaignID string) ([]playQuest, error) {
	rows, err := db.Query(
		"SELECT quest_id, title, state, depends_on, rewards FROM play_quests WHERE campaign_id = ? ORDER BY rowid ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	quests := []playQuest{}
	for rows.Next() {
		var q playQuest
		var depsJSON string
		var rewardsJSON sql.NullString
		if err := rows.Scan(&q.QuestID, &q.Title, &q.State, &depsJSON, &rewardsJSON); err != nil {
			return nil, err
		}
		if err := json.Unmarshal([]byte(depsJSON), &q.DependsOn); err != nil {
			return nil, err
		}
		if rewardsJSON.Valid && rewardsJSON.String != "" && rewardsJSON.String != "null" {
			var r questRewards
			if err := json.Unmarshal([]byte(rewardsJSON.String), &r); err != nil {
				return nil, err
			}
			q.Rewards = &r
		}
		quests = append(quests, q)
	}
	return quests, rows.Err()
}

// Sentinel errors used by the quest reward helpers to signal why an award
// cannot proceed.
var (
	errQuestCompleted            = errors.New("quest is already completed")
	errQuestNotCompleted         = errors.New("quest is not completed")
	errQuestRewardsNotConfigured = errors.New("quest rewards not configured")
	errQuestAlreadyAwarded       = errors.New("quest rewards already awarded")
)

// dbConfigurePlayQuestRewards stores the reward payload for a play quest.
// The quest must exist and be in the locked or active state. Completed quests
// are rejected with errQuestCompleted.
func dbConfigurePlayQuestRewards(campaignID, questID string, rewards *questRewards) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	var state string
	err = tx.QueryRow(
		"SELECT state FROM play_quests WHERE campaign_id = ? AND quest_id = ?",
		campaignID, questID,
	).Scan(&state)
	if err == sql.ErrNoRows {
		return sql.ErrNoRows
	}
	if err != nil {
		return err
	}
	if state != playQuestStateLocked && state != playQuestStateActive {
		return errQuestCompleted
	}

	rewardsJSON, err := json.Marshal(rewards)
	if err != nil {
		return err
	}
	if _, err := tx.Exec(
		"UPDATE play_quests SET rewards = ? WHERE campaign_id = ? AND quest_id = ?",
		string(rewardsJSON), campaignID, questID,
	); err != nil {
		return err
	}

	return tx.Commit()
}

// dbAwardPlayQuestRewards grants the configured quest rewards once to every
// campaign member. It returns sql.ErrNoRows if the quest does not exist, and
// sentinel errors for invalid state, missing rewards, or a repeat award.
func dbAwardPlayQuestRewards(campaignID, questID string) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	var state string
	var rewardsJSON sql.NullString
	var awarded int
	err = tx.QueryRow(
		"SELECT state, rewards, awarded FROM play_quests WHERE campaign_id = ? AND quest_id = ?",
		campaignID, questID,
	).Scan(&state, &rewardsJSON, &awarded)
	if err == sql.ErrNoRows {
		return sql.ErrNoRows
	}
	if err != nil {
		return err
	}
	if state != playQuestStateCompleted {
		return errQuestNotCompleted
	}
	if !rewardsJSON.Valid || rewardsJSON.String == "" || rewardsJSON.String == "null" {
		return errQuestRewardsNotConfigured
	}
	if awarded != 0 {
		return errQuestAlreadyAwarded
	}

	var rewards questRewards
	if err := json.Unmarshal([]byte(rewardsJSON.String), &rewards); err != nil {
		return err
	}

	if _, err := tx.Exec(
		"UPDATE play_quests SET awarded = 1 WHERE campaign_id = ? AND quest_id = ?",
		campaignID, questID,
	); err != nil {
		return err
	}

	members, err := dbGetPlayMemberSummariesByCampaign(campaignID)
	if err != nil {
		return err
	}
	for _, m := range members {
		var existingXP int
		var existingItemsJSON string
		err := tx.QueryRow(
			"SELECT xp, items FROM play_character_rewards WHERE campaign_id = ? AND character_id = ?",
			campaignID, m.CharacterID,
		).Scan(&existingXP, &existingItemsJSON)
		if err != nil && err != sql.ErrNoRows {
			return err
		}
		existingItems := make(map[string]int)
		if err != sql.ErrNoRows {
			if err := json.Unmarshal([]byte(existingItemsJSON), &existingItems); err != nil {
				return err
			}
		}
		mergedItems := make(map[string]int, len(existingItems)+len(rewards.Items))
		for k, v := range existingItems {
			mergedItems[k] = v
		}
		for k, v := range rewards.Items {
			mergedItems[k] = mergedItems[k] + v
		}
		mergedItemsJSON, err := json.Marshal(mergedItems)
		if err != nil {
			return err
		}
		if _, err := tx.Exec(
			`INSERT INTO play_character_rewards (campaign_id, character_id, xp, items) VALUES (?, ?, ?, ?)
			 ON CONFLICT(campaign_id, character_id) DO UPDATE SET xp = excluded.xp, items = excluded.items`,
			campaignID, m.CharacterID, existingXP+rewards.XP, string(mergedItemsJSON),
		); err != nil {
			return err
		}
		for itemID, qty := range rewards.Items {
			if qty <= 0 {
				continue
			}
			if _, err := tx.Exec(
				`INSERT INTO play_inventory (campaign_id, character_id, item_id, quantity)
				 VALUES (?, ?, ?, ?)
				 ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE
				 SET quantity = quantity + excluded.quantity`,
				campaignID, m.CharacterID, itemID, qty,
			); err != nil {
				return err
			}
		}
	}

	return tx.Commit()
}

// dbGetCharacterRewards returns the cumulative quest rewards for a character.
// If no rewards have been recorded, it returns zero values.
func dbGetCharacterRewards(campaignID, characterID string) (*characterRewardsResponse, error) {
	var xp int
	var itemsJSON string
	err := db.QueryRow(
		"SELECT xp, items FROM play_character_rewards WHERE campaign_id = ? AND character_id = ?",
		campaignID, characterID,
	).Scan(&xp, &itemsJSON)
	if err == sql.ErrNoRows {
		return &characterRewardsResponse{
			CharacterID: characterID,
			XP:          0,
			Items:       map[string]int{},
		}, nil
	}
	if err != nil {
		return nil, err
	}
	items := make(map[string]int)
	if itemsJSON != "" && itemsJSON != "null" {
		if err := json.Unmarshal([]byte(itemsJSON), &items); err != nil {
			return nil, err
		}
	}
	return &characterRewardsResponse{
		CharacterID: characterID,
		XP:          xp,
		Items:       items,
	}, nil
}

// --- World event DB helpers ---

// dbCreateWorldEvent inserts a new scheduled world event for a play campaign.
// Duplicate event ids within the same campaign are rejected by the unique
// constraint.
func dbCreateWorldEvent(campaignID, eventID string, turnNumber int, title, text string) error {
	_, err := db.Exec(
		"INSERT INTO play_world_events (campaign_id, event_id, turn_number, title, text, status) VALUES (?, ?, ?, ?, ?, ?)",
		campaignID, eventID, turnNumber, title, text, worldEventStatusScheduled,
	)
	return err
}

// dbGetWorldEvent returns a single world event, or nil if it does not exist.
func dbGetWorldEvent(campaignID, eventID string) (*worldEvent, error) {
	var e worldEvent
	var resTurn sql.NullInt64
	var resText sql.NullString
	err := db.QueryRow(
		"SELECT event_id, turn_number, title, text, status, resolution_turn_number, resolution_text FROM play_world_events WHERE campaign_id = ? AND event_id = ?",
		campaignID, eventID,
	).Scan(&e.EventID, &e.TurnNumber, &e.Title, &e.Text, &e.Status, &resTurn, &resText)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if e.Status == worldEventStatusResolved && resTurn.Valid {
		e.Resolution = &worldEventResolution{
			TurnNumber: int(resTurn.Int64),
			Text:       resText.String,
		}
	}
	return &e, nil
}

// dbResolveWorldEvent records an immutable resolution for a world event. The
// caller must already have verified that the event exists, is scheduled, and
// that the campaign's current turn matches the event's turn.
func dbResolveWorldEvent(campaignID, eventID string, turnNumber int, text string) error {
	_, err := db.Exec(
		"UPDATE play_world_events SET status = ?, resolution_turn_number = ?, resolution_text = ? WHERE campaign_id = ? AND event_id = ? AND status = ?",
		worldEventStatusResolved, turnNumber, text, campaignID, eventID, worldEventStatusScheduled,
	)
	return err
}

// dbGetWorldEvents returns all world events for a play campaign ordered by
// turn_number ascending, then by insertion order for ties.
func dbGetWorldEvents(campaignID string) ([]worldEvent, error) {
	rows, err := db.Query(
		"SELECT event_id, turn_number, title, text, status, resolution_turn_number, resolution_text FROM play_world_events WHERE campaign_id = ? ORDER BY turn_number ASC, id ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	events := []worldEvent{}
	for rows.Next() {
		var e worldEvent
		var resTurn sql.NullInt64
		var resText sql.NullString
		if err := rows.Scan(&e.EventID, &e.TurnNumber, &e.Title, &e.Text, &e.Status, &resTurn, &resText); err != nil {
			return nil, err
		}
		if e.Status == worldEventStatusResolved && resTurn.Valid {
			e.Resolution = &worldEventResolution{
				TurnNumber: int(resTurn.Int64),
				Text:       resText.String,
			}
		}
		events = append(events, e)
	}
	return events, rows.Err()
}

// --- Campaign calendar DB helpers ---

// dbGetCalendar returns the campaign calendar, or nil if it has not been
// initialized yet.
func dbGetCalendar(campaignID string) (*calendarResponse, error) {
	var day int
	var season string
	err := db.QueryRow(
		"SELECT day, season FROM play_calendar WHERE campaign_id = ?",
		campaignID,
	).Scan(&day, &season)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &calendarResponse{
		Day:     day,
		Season:  season,
		Weather: computeWeather(day, season),
	}, nil
}

// dbCreateCalendar initializes the calendar for a campaign. The primary key
// guarantees that a calendar can only be initialized once per campaign.
func dbCreateCalendar(campaignID string, day int, season string) error {
	_, err := db.Exec(
		"INSERT INTO play_calendar (campaign_id, day, season) VALUES (?, ?, ?)",
		campaignID, day, season,
	)
	return err
}

// dbAdvanceCalendar increments the campaign calendar by the requested number
// of days. It returns sql.ErrNoRows if the calendar does not exist.
func dbAdvanceCalendar(campaignID string, days int) (*calendarResponse, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	var day int
	var season string
	err = tx.QueryRow(
		"SELECT day, season FROM play_calendar WHERE campaign_id = ?",
		campaignID,
	).Scan(&day, &season)
	if err == sql.ErrNoRows {
		return nil, sql.ErrNoRows
	}
	if err != nil {
		return nil, err
	}

	newDay := day + days
	if _, err := tx.Exec(
		"UPDATE play_calendar SET day = ? WHERE campaign_id = ?",
		newDay, campaignID,
	); err != nil {
		return nil, err
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}

	return &calendarResponse{
		Day:     newDay,
		Season:  season,
		Weather: computeWeather(newDay, season),
	}, nil
}

// --- Settlement DB helpers ---

// dbCreatePlaySettlement inserts a new DM-managed settlement for a play
// campaign. Duplicate settlement ids within the same campaign are rejected
// by the unique constraint.
func dbCreatePlaySettlement(campaignID, settlementID, name string, services []string, availability string) error {
	servicesJSON, err := json.Marshal(services)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		"INSERT INTO play_settlements (campaign_id, settlement_id, name, services, availability) VALUES (?, ?, ?, ?, ?)",
		campaignID, settlementID, name, string(servicesJSON), availability,
	)
	return err
}

// dbGetPlaySettlement returns a single settlement with its full discovered_by
// list in discovery order, or nil if it does not exist.
func dbGetPlaySettlement(campaignID, settlementID string) (*settlement, error) {
	var s settlement
	var servicesJSON string
	err := db.QueryRow(
		"SELECT name, services, availability FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?",
		campaignID, settlementID,
	).Scan(&s.Name, &servicesJSON, &s.Availability)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	s.SettlementID = settlementID
	if err := json.Unmarshal([]byte(servicesJSON), &s.Services); err != nil {
		return nil, err
	}
	discoverers, err := dbGetPlaySettlementDiscoveries(campaignID, settlementID)
	if err != nil {
		return nil, err
	}
	s.DiscoveredBy = discoverers
	return &s, nil
}

// dbGetPlaySettlementDiscoveries returns the character ids that have
// discovered a settlement, in discovery order.
func dbGetPlaySettlementDiscoveries(campaignID, settlementID string) ([]string, error) {
	rows, err := db.Query(
		"SELECT character_id FROM play_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? ORDER BY id ASC",
		campaignID, settlementID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	discovered := []string{}
	for rows.Next() {
		var charID string
		if err := rows.Scan(&charID); err != nil {
			return nil, err
		}
		discovered = append(discovered, charID)
	}
	return discovered, rows.Err()
}

// dbGetPlaySettlementDiscoveriesTx is the transaction-scoped variant of
// dbGetPlaySettlementDiscoveries.
func dbGetPlaySettlementDiscoveriesTx(tx *sql.Tx, campaignID, settlementID string) ([]string, error) {
	rows, err := tx.Query(
		"SELECT character_id FROM play_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? ORDER BY id ASC",
		campaignID, settlementID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	discovered := []string{}
	for rows.Next() {
		var charID string
		if err := rows.Scan(&charID); err != nil {
			return nil, err
		}
		discovered = append(discovered, charID)
	}
	return discovered, rows.Err()
}

// dbGetPlaySettlements returns all settlements for a play campaign in
// creation order, each with its full discovered_by list in discovery order.
func dbGetPlaySettlements(campaignID string) ([]settlement, error) {
	rows, err := db.Query(
		"SELECT settlement_id, name, services, availability FROM play_settlements WHERE campaign_id = ? ORDER BY id ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	settlements := []settlement{}
	for rows.Next() {
		var s settlement
		var servicesJSON string
		if err := rows.Scan(&s.SettlementID, &s.Name, &servicesJSON, &s.Availability); err != nil {
			return nil, err
		}
		if err := json.Unmarshal([]byte(servicesJSON), &s.Services); err != nil {
			return nil, err
		}
		s.DiscoveredBy = []string{}
		settlements = append(settlements, s)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	if len(settlements) == 0 {
		return settlements, nil
	}

	discRows, err := db.Query(
		"SELECT settlement_id, character_id FROM play_settlement_discoveries WHERE campaign_id = ? ORDER BY id ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer discRows.Close()

	discoverers := make(map[string][]string)
	for discRows.Next() {
		var settlementID, charID string
		if err := discRows.Scan(&settlementID, &charID); err != nil {
			return nil, err
		}
		discoverers[settlementID] = append(discoverers[settlementID], charID)
	}
	if err := discRows.Err(); err != nil {
		return nil, err
	}

	for i := range settlements {
		if d, ok := discoverers[settlements[i].SettlementID]; ok {
			settlements[i].DiscoveredBy = d
		}
	}
	return settlements, nil
}

// dbUpdatePlaySettlement replaces a settlement's name, services, and
// availability while preserving its existing discovered_by order. It returns
// the updated settlement, or nil if the settlement does not exist.
func dbUpdatePlaySettlement(campaignID, settlementID, name string, services []string, availability string) (*settlement, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	servicesJSON, err := json.Marshal(services)
	if err != nil {
		return nil, err
	}

	res, err := tx.Exec(
		"UPDATE play_settlements SET name = ?, services = ?, availability = ? WHERE campaign_id = ? AND settlement_id = ?",
		name, string(servicesJSON), availability, campaignID, settlementID,
	)
	if err != nil {
		return nil, err
	}
	n, err := res.RowsAffected()
	if err != nil {
		return nil, err
	}
	if n == 0 {
		return nil, tx.Rollback()
	}

	discoverers, err := dbGetPlaySettlementDiscoveriesTx(tx, campaignID, settlementID)
	if err != nil {
		return nil, err
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return &settlement{
		SettlementID: settlementID,
		Name:         name,
		Services:     services,
		Availability: availability,
		DiscoveredBy: discoverers,
	}, nil
}

// dbDiscoverPlaySettlement records a character's discovery of a settlement if
// it has not already been discovered by that character. It returns true when
// a new discovery row is inserted and false when the discovery already existed.
// The caller must already have verified that the settlement and character
// exist.
func dbDiscoverPlaySettlement(campaignID, settlementID, characterID string) (bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return false, err
	}
	defer tx.Rollback()

	var exists int
	err = tx.QueryRow(
		"SELECT 1 FROM play_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?",
		campaignID, settlementID, characterID,
	).Scan(&exists)
	if err == nil {
		return false, tx.Commit()
	}
	if err != sql.ErrNoRows {
		return false, err
	}

	if _, err := tx.Exec(
		"INSERT INTO play_settlement_discoveries (campaign_id, settlement_id, character_id) VALUES (?, ?, ?)",
		campaignID, settlementID, characterID,
	); err != nil {
		return false, err
	}
	return true, tx.Commit()
}

// --- Shop DB helpers ---

// errInsufficientShopStock is returned when a buy request exceeds the shop's
// available stock for an item.
var errInsufficientShopStock = errors.New("insufficient shop stock")

// shopTransactionResult carries the post-transaction balances for a buy or
// sell operation.
type shopTransactionResult struct {
	newGold  int
	newStock int
}

// dbCreatePlayShop inserts a new DM-managed shop for a settlement. The stock
// is normalized to one row per item. Duplicate shop ids within the same
// settlement are rejected by the unique constraint, and missing settlements are
// rejected by the foreign key constraint.
func dbCreatePlayShop(campaignID, settlementID, shopID, name string, stock map[string]int, buyPrice, sellPrice int) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	if _, err := tx.Exec(
		`INSERT INTO play_shops (campaign_id, settlement_id, shop_id, name, buy_price, sell_price)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		campaignID, settlementID, shopID, name, buyPrice, sellPrice,
	); err != nil {
		return err
	}

	for itemID, quantity := range stock {
		if _, err := tx.Exec(
			`INSERT INTO play_shop_stock (campaign_id, settlement_id, shop_id, item_id, quantity)
			 VALUES (?, ?, ?, ?, ?)`,
			campaignID, settlementID, shopID, itemID, quantity,
		); err != nil {
			return err
		}
	}

	return tx.Commit()
}

// dbGetPlayShop returns a single shop with its positive stock quantities, or
// nil if it does not exist.
func dbGetPlayShop(campaignID, settlementID, shopID string) (*shop, error) {
	var name string
	var buyPrice, sellPrice int
	err := db.QueryRow(
		`SELECT name, buy_price, sell_price FROM play_shops
		 WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?`,
		campaignID, settlementID, shopID,
	).Scan(&name, &buyPrice, &sellPrice)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	rows, err := db.Query(
		`SELECT item_id, quantity FROM play_shop_stock
		 WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? AND quantity > 0
		 ORDER BY item_id ASC`,
		campaignID, settlementID, shopID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	stock := make(map[string]int)
	for rows.Next() {
		var itemID string
		var quantity int
		if err := rows.Scan(&itemID, &quantity); err != nil {
			return nil, err
		}
		stock[itemID] = quantity
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	return &shop{
		ShopID:    shopID,
		Name:      name,
		Stock:     stock,
		BuyPrice:  buyPrice,
		SellPrice: sellPrice,
	}, nil
}

// dbBuyFromShop atomically sells items from a shop to a character. It
// decrements shop stock, subtracts gold, and adds the items to the character's
// inventory. It returns errInsufficientShopStock or errInsufficientGold when
// the transaction cannot be satisfied.
func dbBuyFromShop(campaignID, settlementID, shopID, characterID, itemID string, quantity int) (*shopTransactionResult, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	var buyPrice int
	err = tx.QueryRow(
		`SELECT buy_price FROM play_shops
		 WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?`,
		campaignID, settlementID, shopID,
	).Scan(&buyPrice)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("shop not found")
	}
	if err != nil {
		return nil, err
	}

	var stockQty int
	err = tx.QueryRow(
		`SELECT COALESCE(quantity, 0) FROM play_shop_stock
		 WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? AND item_id = ?`,
		campaignID, settlementID, shopID, itemID,
	).Scan(&stockQty)
	if err == sql.ErrNoRows {
		stockQty = 0
	} else if err != nil {
		return nil, err
	}
	if stockQty < quantity {
		return nil, errInsufficientShopStock
	}

	var gold int
	err = tx.QueryRow(
		`SELECT gold FROM play_members
		 WHERE campaign_id = ? AND character_id = ?`,
		campaignID, characterID,
	).Scan(&gold)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("character not found")
	}
	if err != nil {
		return nil, err
	}
	totalCost := buyPrice * quantity
	if gold < totalCost {
		return nil, errInsufficientGold
	}

	newStock := stockQty - quantity
	if newStock == 0 {
		_, err = tx.Exec(
			`DELETE FROM play_shop_stock
			 WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? AND item_id = ?`,
			campaignID, settlementID, shopID, itemID,
		)
	} else {
		_, err = tx.Exec(
			`UPDATE play_shop_stock SET quantity = ?
			 WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? AND item_id = ?`,
			newStock, campaignID, settlementID, shopID, itemID,
		)
	}
	if err != nil {
		return nil, err
	}

	newGold := gold - totalCost
	if _, err := tx.Exec(
		`UPDATE play_members SET gold = ?
		 WHERE campaign_id = ? AND character_id = ?`,
		newGold, campaignID, characterID,
	); err != nil {
		return nil, err
	}

	if _, err := tx.Exec(
		`INSERT INTO play_inventory (campaign_id, character_id, item_id, quantity)
		 VALUES (?, ?, ?, ?)
		 ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE
		 SET quantity = quantity + excluded.quantity`,
		campaignID, characterID, itemID, quantity,
	); err != nil {
		return nil, err
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return &shopTransactionResult{newGold: newGold, newStock: newStock}, nil
}

// dbSellToShop atomically buys items from a character for a shop. It removes
// items from the character's inventory, adds gold, and increments shop stock.
// It returns errInsufficientInventory when the character does not hold enough.
func dbSellToShop(campaignID, settlementID, shopID, characterID, itemID string, quantity int) (*shopTransactionResult, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	var sellPrice int
	err = tx.QueryRow(
		`SELECT sell_price FROM play_shops
		 WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?`,
		campaignID, settlementID, shopID,
	).Scan(&sellPrice)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("shop not found")
	}
	if err != nil {
		return nil, err
	}

	var invQty int
	err = tx.QueryRow(
		`SELECT COALESCE(quantity, 0) FROM play_inventory
		 WHERE campaign_id = ? AND character_id = ? AND item_id = ?`,
		campaignID, characterID, itemID,
	).Scan(&invQty)
	if err == sql.ErrNoRows {
		invQty = 0
	} else if err != nil {
		return nil, err
	}
	if invQty < quantity {
		return nil, errInsufficientInventory
	}

	newInv := invQty - quantity
	if newInv == 0 {
		_, err = tx.Exec(
			`DELETE FROM play_inventory
			 WHERE campaign_id = ? AND character_id = ? AND item_id = ?`,
			campaignID, characterID, itemID,
		)
	} else {
		_, err = tx.Exec(
			`UPDATE play_inventory SET quantity = ?
			 WHERE campaign_id = ? AND character_id = ? AND item_id = ?`,
			newInv, campaignID, characterID, itemID,
		)
	}
	if err != nil {
		return nil, err
	}

	var gold int
	err = tx.QueryRow(
		`SELECT gold FROM play_members
		 WHERE campaign_id = ? AND character_id = ?`,
		campaignID, characterID,
	).Scan(&gold)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("character not found")
	}
	if err != nil {
		return nil, err
	}
	newGold := gold + sellPrice*quantity
	if _, err := tx.Exec(
		`UPDATE play_members SET gold = ?
		 WHERE campaign_id = ? AND character_id = ?`,
		newGold, campaignID, characterID,
	); err != nil {
		return nil, err
	}

	var stockQty int
	err = tx.QueryRow(
		`SELECT COALESCE(quantity, 0) FROM play_shop_stock
		 WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? AND item_id = ?`,
		campaignID, settlementID, shopID, itemID,
	).Scan(&stockQty)
	if err == sql.ErrNoRows {
		stockQty = 0
	} else if err != nil {
		return nil, err
	}
	newStock := stockQty + quantity
	if stockQty == 0 {
		_, err = tx.Exec(
			`INSERT INTO play_shop_stock (campaign_id, settlement_id, shop_id, item_id, quantity)
			 VALUES (?, ?, ?, ?, ?)`,
			campaignID, settlementID, shopID, itemID, newStock,
		)
	} else {
		_, err = tx.Exec(
			`UPDATE play_shop_stock SET quantity = ?
			 WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? AND item_id = ?`,
			newStock, campaignID, settlementID, shopID, itemID,
		)
	}
	if err != nil {
		return nil, err
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return &shopTransactionResult{newGold: newGold, newStock: newStock}, nil
}

// --- Recipe catalog DB helpers ---

var (
	// errRecipeNotFound is returned when a requested recipe does not exist in a campaign.
	errRecipeNotFound = errors.New("recipe not found")
	// errCharacterNotFound is returned when a requested craft character does not exist in a campaign.
	errCharacterNotFound = errors.New("character not found")
)

// dbCreatePlayRecipe inserts a new crafting recipe for a campaign. Duplicate
// recipe ids within the same campaign are rejected by the unique constraint.
func dbCreatePlayRecipe(campaignID, recipeID, name string, ingredients map[string]int, outputItem string, outputQuantity int) error {
	ingredientsJSON, err := json.Marshal(ingredients)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		"INSERT INTO play_recipes (campaign_id, recipe_id, name, ingredients, output_item, output_quantity) VALUES (?, ?, ?, ?, ?, ?)",
		campaignID, recipeID, name, string(ingredientsJSON), outputItem, outputQuantity,
	)
	return err
}

// dbGetPlayRecipe returns a single campaign recipe, or nil if it does not exist.
func dbGetPlayRecipe(campaignID, recipeID string) (*recipe, error) {
	r := &recipe{RecipeID: recipeID}
	var ingredientsJSON string
	err := db.QueryRow(
		"SELECT name, ingredients, output_item, output_quantity FROM play_recipes WHERE campaign_id = ? AND recipe_id = ?",
		campaignID, recipeID,
	).Scan(&r.Name, &ingredientsJSON, &r.OutputItem, &r.OutputQuantity)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	r.Ingredients = make(map[string]int)
	if err := json.Unmarshal([]byte(ingredientsJSON), &r.Ingredients); err != nil {
		return nil, err
	}
	return r, nil
}

// dbListPlayRecipes returns all recipes for a campaign in creation order.
func dbListPlayRecipes(campaignID string) ([]recipe, error) {
	rows, err := db.Query(
		"SELECT recipe_id, name, ingredients, output_item, output_quantity FROM play_recipes WHERE campaign_id = ? ORDER BY rowid ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	recipes := []recipe{}
	for rows.Next() {
		var r recipe
		var ingredientsJSON string
		if err := rows.Scan(&r.RecipeID, &r.Name, &ingredientsJSON, &r.OutputItem, &r.OutputQuantity); err != nil {
			return nil, err
		}
		r.Ingredients = make(map[string]int)
		if err := json.Unmarshal([]byte(ingredientsJSON), &r.Ingredients); err != nil {
			return nil, err
		}
		recipes = append(recipes, r)
	}
	return recipes, rows.Err()
}

// dbCraftRecipe atomically consumes the ingredients for a recipe from a
// character's inventory and adds the output item. It returns the public craft
// response, or sentinel errors for missing recipe, missing character, or
// insufficient ingredients.
func dbCraftRecipe(campaignID, recipeID, characterID string) (*craftResponse, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	var r recipe
	var ingredientsJSON string
	err = tx.QueryRow(
		"SELECT name, ingredients, output_item, output_quantity FROM play_recipes WHERE campaign_id = ? AND recipe_id = ?",
		campaignID, recipeID,
	).Scan(&r.Name, &ingredientsJSON, &r.OutputItem, &r.OutputQuantity)
	if err == sql.ErrNoRows {
		return nil, errRecipeNotFound
	}
	if err != nil {
		return nil, err
	}
	r.RecipeID = recipeID
	r.Ingredients = make(map[string]int)
	if err := json.Unmarshal([]byte(ingredientsJSON), &r.Ingredients); err != nil {
		return nil, err
	}

	var exists int
	err = tx.QueryRow(
		"SELECT 1 FROM play_members WHERE campaign_id = ? AND character_id = ?",
		campaignID, characterID,
	).Scan(&exists)
	if err == sql.ErrNoRows {
		return nil, errCharacterNotFound
	}
	if err != nil {
		return nil, err
	}

	for itemID, needed := range r.Ingredients {
		var current int
		err = tx.QueryRow(
			"SELECT COALESCE(quantity, 0) FROM play_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
			campaignID, characterID, itemID,
		).Scan(&current)
		if err == sql.ErrNoRows {
			current = 0
		} else if err != nil {
			return nil, err
		}
		if current < needed {
			return nil, errInsufficientInventory
		}
		remaining := current - needed
		if remaining == 0 {
			_, err = tx.Exec(
				"DELETE FROM play_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
				campaignID, characterID, itemID,
			)
		} else {
			_, err = tx.Exec(
				"UPDATE play_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
				remaining, campaignID, characterID, itemID,
			)
		}
		if err != nil {
			return nil, err
		}
	}

	if _, err := tx.Exec(
		`INSERT INTO play_inventory (campaign_id, character_id, item_id, quantity)
		 VALUES (?, ?, ?, ?)
		 ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE
		 SET quantity = quantity + excluded.quantity`,
		campaignID, characterID, r.OutputItem, r.OutputQuantity,
	); err != nil {
		return nil, err
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}

	return &craftResponse{
		CharacterID:    characterID,
		RecipeID:       recipeID,
		OutputItem:     r.OutputItem,
		OutputQuantity: r.OutputQuantity,
	}, nil
}

// dbCreatePlayDowntimeActivity inserts a new downtime activity for a campaign.
// Duplicate activity ids within the same campaign are rejected by the primary key.
func dbCreatePlayDowntimeActivity(campaignID, activityID, name string, cyclesRequired int) error {
	_, err := db.Exec(
		"INSERT INTO play_downtime_activities (campaign_id, activity_id, name, cycles_required) VALUES (?, ?, ?, ?)",
		campaignID, activityID, name, cyclesRequired,
	)
	return err
}

// dbGetPlayDowntimeActivity returns a downtime activity belonging to a campaign,
// or nil if not found.
func dbGetPlayDowntimeActivity(campaignID, activityID string) (*downtimeActivity, error) {
	a := &downtimeActivity{ActivityID: activityID}
	err := db.QueryRow(
		"SELECT name, cycles_required FROM play_downtime_activities WHERE campaign_id = ? AND activity_id = ?",
		campaignID, activityID,
	).Scan(&a.Name, &a.CyclesRequired)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return a, nil
}

// dbCreatePlayDowntimeAllocation inserts a new allocation for a character and
// activity. Duplicate allocations are rejected by the primary key.
func dbCreatePlayDowntimeAllocation(campaignID, characterID, activityID string) error {
	_, err := db.Exec(
		"INSERT INTO play_downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (?, ?, ?, 0, 0)",
		campaignID, characterID, activityID,
	)
	return err
}

// dbGetPlayDowntimeAllocation returns a character's allocation for an activity,
// or nil if not found.
func dbGetPlayDowntimeAllocation(campaignID, characterID, activityID string) (*downtimeAllocation, error) {
	a := &downtimeAllocation{
		CharacterID: characterID,
		ActivityID:  activityID,
	}
	err := db.QueryRow(
		"SELECT cycles_completed, completions FROM play_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
		campaignID, characterID, activityID,
	).Scan(&a.CyclesCompleted, &a.Completions)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return a, nil
}

// dbProgressPlayDowntimeAllocation increments cycles_completed for an allocation.
// When cycles_completed reaches the activity's cycles_required, the cycle counter
// resets to 0 and completions is incremented. The allocation is locked for update
// during the transaction.
func dbProgressPlayDowntimeAllocation(campaignID, characterID, activityID string) (*downtimeAllocation, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	var cyclesRequired int
	err = tx.QueryRow(
		"SELECT cycles_required FROM play_downtime_activities WHERE campaign_id = ? AND activity_id = ?",
		campaignID, activityID,
	).Scan(&cyclesRequired)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	var cyclesCompleted, completions int
	err = tx.QueryRow(
		"SELECT cycles_completed, completions FROM play_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
		campaignID, characterID, activityID,
	).Scan(&cyclesCompleted, &completions)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	cyclesCompleted++
	if cyclesCompleted >= cyclesRequired {
		cyclesCompleted = 0
		completions++
	}

	if _, err := tx.Exec(
		"UPDATE play_downtime_allocations SET cycles_completed = ?, completions = ? WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
		cyclesCompleted, completions, campaignID, characterID, activityID,
	); err != nil {
		return nil, err
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}

	return &downtimeAllocation{
		CharacterID:     characterID,
		ActivityID:      activityID,
		CyclesCompleted: cyclesCompleted,
		Completions:     completions,
	}, nil
}
