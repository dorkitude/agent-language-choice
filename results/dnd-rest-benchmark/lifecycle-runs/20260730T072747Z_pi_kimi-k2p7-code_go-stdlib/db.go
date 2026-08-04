package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os/exec"
	"strings"
	"sync"
)

// dbPath is the SQLite database file used by the sqlite3 CLI driver.
// All persistence is serialized through dbMu because the driver is an
// external process and we do not rely on SQLite's own locking for
// transactional behavior.
var dbPath = "game.db"

var dbMu sync.Mutex

// schemaSQL defines the entire durable schema. It is used both when the
// database is first initialized and when the storage reset endpoint rebuilds
// the game tables. All CREATE statements use IF NOT EXISTS so that the same
// script can be replayed safely, and the schema_version row uses INSERT OR
// REPLACE for the same reason.
const schemaSQL = `CREATE TABLE IF NOT EXISTS schema_version (
	version INTEGER PRIMARY KEY
);
INSERT OR REPLACE INTO schema_version(version) VALUES (1);
CREATE TABLE IF NOT EXISTS users (
	username TEXT PRIMARY KEY,
	role TEXT NOT NULL,
	salt TEXT NOT NULL,
	hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS combat_sessions (
	id TEXT PRIMARY KEY,
	round INTEGER NOT NULL,
	turn_index INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS combat_order (
	session_id TEXT NOT NULL,
	idx INTEGER NOT NULL,
	name TEXT NOT NULL,
	score INTEGER NOT NULL,
	dex INTEGER NOT NULL,
	PRIMARY KEY (session_id, idx)
);
CREATE TABLE IF NOT EXISTS combat_conditions (
	id INTEGER PRIMARY KEY,
	session_id TEXT NOT NULL,
	target TEXT NOT NULL,
	"condition" TEXT NOT NULL,
	remaining_rounds INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS compendium_monsters (
	slug TEXT PRIMARY KEY,
	name TEXT NOT NULL,
	cr TEXT NOT NULL,
	armor_class INTEGER NOT NULL,
	hit_points INTEGER NOT NULL,
	tags TEXT NOT NULL
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
	class TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_events (
	id TEXT PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	kind TEXT NOT NULL,
	summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quests (
	id TEXT PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	title TEXT NOT NULL,
	status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quest_milestones (
	id INTEGER PRIMARY KEY,
	quest_id TEXT NOT NULL,
	label TEXT NOT NULL,
	done INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS factions (
	id TEXT PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	name TEXT NOT NULL,
	stance TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS npcs (
	id TEXT PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	name TEXT NOT NULL,
	faction_id TEXT NOT NULL,
	disposition INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_inventory (
	campaign_id TEXT NOT NULL,
	item_slug TEXT NOT NULL,
	quantity INTEGER NOT NULL,
	owner TEXT NOT NULL,
	PRIMARY KEY (campaign_id, item_slug, owner)
);
CREATE TABLE IF NOT EXISTS character_equipment (
	campaign_id TEXT NOT NULL,
	character_id TEXT NOT NULL,
	item_slug TEXT NOT NULL,
	quantity INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, character_id, item_slug)
);
CREATE TABLE IF NOT EXISTS character_inventory_items (
	campaign_id TEXT NOT NULL,
	character_id TEXT NOT NULL,
	item_id TEXT NOT NULL,
	quantity INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, character_id, item_id)
);
CREATE TABLE IF NOT EXISTS character_equipment_slots (
	campaign_id TEXT NOT NULL,
	character_id TEXT NOT NULL,
	slot TEXT NOT NULL,
	item_id TEXT NOT NULL,
	attuned INTEGER NOT NULL DEFAULT 0,
	PRIMARY KEY (campaign_id, character_id, slot)
);
CREATE TABLE IF NOT EXISTS character_spells (
	campaign_id TEXT NOT NULL,
	character_id TEXT NOT NULL,
	spell_id TEXT NOT NULL,
	name TEXT NOT NULL,
	level INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, character_id, spell_id)
);
CREATE TABLE IF NOT EXISTS character_prepared_spells (
	campaign_id TEXT NOT NULL,
	character_id TEXT NOT NULL,
	spell_id TEXT NOT NULL,
	sort_order INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, character_id, spell_id)
);
CREATE TABLE IF NOT EXISTS character_casts (
	campaign_id TEXT NOT NULL,
	character_id TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	spell_id TEXT NOT NULL,
	target TEXT NOT NULL,
	slot_level INTEGER NOT NULL,
	slots_remaining INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, character_id, sequence)
);
CREATE TABLE IF NOT EXISTS character_concentration (
	campaign_id TEXT NOT NULL,
	character_id TEXT NOT NULL,
	spell_id TEXT NOT NULL,
	target TEXT NOT NULL,
	remaining_turns INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, character_id)
);
CREATE TABLE IF NOT EXISTS crafting_projects (
	id TEXT PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	character_id TEXT NOT NULL,
	item_slug TEXT NOT NULL,
	days_required INTEGER NOT NULL,
	days_completed INTEGER NOT NULL DEFAULT 0,
	cost_gp INTEGER NOT NULL,
	status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_sessions (
	id TEXT PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	starts_at TEXT NOT NULL,
	duration_minutes INTEGER NOT NULL,
	agenda TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS session_attendance (
	session_id TEXT PRIMARY KEY,
	present TEXT NOT NULL,
	absent TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS play_campaigns (
	id TEXT PRIMARY KEY,
	name TEXT NOT NULL,
	owner TEXT NOT NULL,
	status TEXT NOT NULL,
	max_players INTEGER NOT NULL,
	turn_number INTEGER NOT NULL DEFAULT 0,
	turn_actor TEXT,
	nudge_count INTEGER NOT NULL DEFAULT 0,
	current_scene_id TEXT,
	current_location_id TEXT,
	phase TEXT,
	pre_combat_actor TEXT
);
CREATE TABLE IF NOT EXISTS campaign_scenes (
	id TEXT NOT NULL,
	campaign_id TEXT NOT NULL,
	name TEXT NOT NULL,
	status TEXT NOT NULL,
	PRIMARY KEY (id, campaign_id)
);
CREATE TABLE IF NOT EXISTS campaign_locations (
	id TEXT NOT NULL,
	campaign_id TEXT NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (id, campaign_id)
);
CREATE TABLE IF NOT EXISTS location_connections (
	campaign_id TEXT NOT NULL,
	from_id TEXT NOT NULL,
	to_id TEXT NOT NULL,
	travel_turns INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, from_id, to_id)
);
CREATE TABLE IF NOT EXISTS play_campaign_members (
	campaign_id TEXT NOT NULL,
	username TEXT NOT NULL,
	character_id TEXT NOT NULL,
	name TEXT NOT NULL,
	class TEXT NOT NULL,
	join_order INTEGER NOT NULL DEFAULT 0,
	level INTEGER NOT NULL DEFAULT 1,
	con_modifier INTEGER NOT NULL DEFAULT 0,
	hp_max INTEGER NOT NULL DEFAULT 20,
	hp_current INTEGER NOT NULL DEFAULT 20,
	status TEXT NOT NULL DEFAULT 'conscious',
	death_saves_successes INTEGER NOT NULL DEFAULT 0,
	death_saves_failures INTEGER NOT NULL DEFAULT 0,
	owner TEXT,
	str_score INTEGER NOT NULL DEFAULT 10,
	dex_score INTEGER NOT NULL DEFAULT 10,
	con_score INTEGER NOT NULL DEFAULT 10,
	int_score INTEGER NOT NULL DEFAULT 10,
	wis_score INTEGER NOT NULL DEFAULT 10,
	cha_score INTEGER NOT NULL DEFAULT 10,
	gold INTEGER NOT NULL DEFAULT 10,
	PRIMARY KEY (campaign_id, character_id),
	UNIQUE(campaign_id, username)
);
CREATE TABLE IF NOT EXISTS campaign_narrations (
	campaign_id TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	kind TEXT NOT NULL,
	actor TEXT NOT NULL,
	text TEXT NOT NULL,
	type TEXT,
	target TEXT,
	destination_id TEXT,
	travel_turns INTEGER,
	PRIMARY KEY (campaign_id, sequence)
);
CREATE TABLE IF NOT EXISTS campaign_documents (
	campaign_id TEXT PRIMARY KEY,
	story TEXT NOT NULL DEFAULT '',
	dm_notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS campaign_encounters (
	id TEXT NOT NULL,
	campaign_id TEXT NOT NULL,
	name TEXT NOT NULL,
	status TEXT NOT NULL,
	combatants TEXT NOT NULL DEFAULT '[]',
	round INTEGER NOT NULL DEFAULT 1,
	turn_index INTEGER NOT NULL DEFAULT 0,
	xp_awarded INTEGER NOT NULL DEFAULT 0,
	loot TEXT NOT NULL DEFAULT '[]',
	rewards_awarded INTEGER NOT NULL DEFAULT 0,
	PRIMARY KEY (id, campaign_id)
);
CREATE TABLE IF NOT EXISTS campaign_encounter_conditions (
	id INTEGER PRIMARY KEY,
	encounter_id TEXT NOT NULL,
	campaign_id TEXT NOT NULL,
	target TEXT NOT NULL,
	"condition" TEXT NOT NULL,
	remaining_rounds INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_currency_transfers (
	campaign_id TEXT NOT NULL,
	transfer_id INTEGER NOT NULL,
	from_character_id TEXT NOT NULL,
	to_character_id TEXT NOT NULL,
	gold INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, transfer_id)
);
CREATE TABLE IF NOT EXISTS campaign_loot (
	campaign_id TEXT NOT NULL,
	loot_id TEXT NOT NULL,
	item_id TEXT NOT NULL,
	quantity INTEGER NOT NULL,
	status TEXT NOT NULL DEFAULT 'open',
	recipient_character_id TEXT,
	PRIMARY KEY (campaign_id, loot_id)
);
CREATE TABLE IF NOT EXISTS campaign_loot_votes (
	campaign_id TEXT NOT NULL,
	loot_id TEXT NOT NULL,
	voter TEXT NOT NULL,
	recipient_character_id TEXT NOT NULL,
	PRIMARY KEY (campaign_id, loot_id, voter)
);
CREATE TABLE IF NOT EXISTS campaign_npcs (
	campaign_id TEXT NOT NULL,
	npc_id TEXT NOT NULL,
	name TEXT NOT NULL,
	agenda TEXT NOT NULL,
	public_status TEXT NOT NULL,
	PRIMARY KEY (campaign_id, npc_id)
);
CREATE TABLE IF NOT EXISTS play_factions (
	campaign_id TEXT NOT NULL,
	faction_id TEXT NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (campaign_id, faction_id)
);
CREATE TABLE IF NOT EXISTS faction_reputation_history (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	faction_id TEXT NOT NULL,
	character_id TEXT NOT NULL,
	delta INTEGER NOT NULL,
	reputation INTEGER NOT NULL,
	reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS npc_dialogue_entries (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	npc_id TEXT NOT NULL,
	dialogue_id TEXT NOT NULL,
	speaker TEXT NOT NULL,
	text TEXT NOT NULL,
	visibility TEXT NOT NULL,
	UNIQUE(campaign_id, npc_id, dialogue_id)
);
CREATE TABLE IF NOT EXISTS campaign_relationships (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	source_id TEXT NOT NULL,
	target_id TEXT NOT NULL,
	kind TEXT NOT NULL,
	score INTEGER NOT NULL,
	UNIQUE(campaign_id, source_id, target_id, kind)
);
CREATE TABLE IF NOT EXISTS campaign_clues (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	clue_id TEXT NOT NULL,
	text TEXT NOT NULL,
	audience TEXT NOT NULL,
	character_id TEXT,
	UNIQUE(campaign_id, clue_id)
);
CREATE TABLE IF NOT EXISTS play_quests (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	quest_id TEXT NOT NULL,
	title TEXT NOT NULL,
	state TEXT NOT NULL,
	rewards_xp INTEGER NOT NULL DEFAULT 0,
	rewards_items TEXT NOT NULL DEFAULT '{}',
	rewards_awarded INTEGER NOT NULL DEFAULT 0,
	UNIQUE(campaign_id, quest_id)
);
CREATE TABLE IF NOT EXISTS play_quest_dependencies (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	quest_id TEXT NOT NULL,
	depends_on TEXT NOT NULL,
	UNIQUE(campaign_id, quest_id, depends_on)
);
CREATE TABLE IF NOT EXISTS play_quest_reward_grants (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	quest_id TEXT NOT NULL,
	character_id TEXT NOT NULL,
	xp INTEGER NOT NULL DEFAULT 0,
	items TEXT NOT NULL DEFAULT '{}',
	UNIQUE(campaign_id, quest_id, character_id)
);
CREATE TABLE IF NOT EXISTS campaign_world_events (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	event_id TEXT NOT NULL,
	turn_number INTEGER NOT NULL,
	title TEXT NOT NULL,
	text TEXT NOT NULL,
	status TEXT NOT NULL DEFAULT 'scheduled',
	resolution_text TEXT,
	UNIQUE(campaign_id, event_id)
);
CREATE TABLE IF NOT EXISTS campaign_calendars (
	campaign_id TEXT PRIMARY KEY,
	day INTEGER NOT NULL,
	season TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_settlements (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	settlement_id TEXT NOT NULL,
	name TEXT NOT NULL,
	services TEXT NOT NULL,
	availability TEXT NOT NULL,
	UNIQUE(campaign_id, settlement_id)
);
CREATE TABLE IF NOT EXISTS settlement_discoveries (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	settlement_id TEXT NOT NULL,
	character_id TEXT NOT NULL,
	UNIQUE(campaign_id, settlement_id, character_id)
);
CREATE TABLE IF NOT EXISTS campaign_shops (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	settlement_id TEXT NOT NULL,
	shop_id TEXT NOT NULL,
	name TEXT NOT NULL,
	stock TEXT NOT NULL,
	buy_price INTEGER NOT NULL,
	sell_price INTEGER NOT NULL,
	UNIQUE(campaign_id, settlement_id, shop_id)
);
CREATE TABLE IF NOT EXISTS campaign_recipes (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	recipe_id TEXT NOT NULL,
	name TEXT NOT NULL,
	ingredients TEXT NOT NULL,
	output_item TEXT NOT NULL,
	output_quantity INTEGER NOT NULL,
	UNIQUE(campaign_id, recipe_id)
);
CREATE TABLE IF NOT EXISTS downtime_activities (
	campaign_id TEXT NOT NULL,
	activity_id TEXT NOT NULL,
	name TEXT NOT NULL,
	cycles_required INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, activity_id)
);
CREATE TABLE IF NOT EXISTS downtime_allocations (
	campaign_id TEXT NOT NULL,
	character_id TEXT NOT NULL,
	activity_id TEXT NOT NULL,
	cycles_completed INTEGER NOT NULL DEFAULT 0,
	completions INTEGER NOT NULL DEFAULT 0,
	PRIMARY KEY (campaign_id, character_id, activity_id)
);
CREATE TABLE IF NOT EXISTS campaign_session_zero_settings (
	campaign_id TEXT PRIMARY KEY,
	rules TEXT NOT NULL,
	tone TEXT NOT NULL,
	consent TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_content (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	content_id TEXT NOT NULL,
	kind TEXT NOT NULL,
	text TEXT NOT NULL,
	tags TEXT NOT NULL,
	sort_order INTEGER NOT NULL,
	UNIQUE(campaign_id, content_id)
);
CREATE TABLE IF NOT EXISTS campaign_notes (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	note_id TEXT NOT NULL,
	text TEXT NOT NULL,
	visibility TEXT NOT NULL,
	owner TEXT NOT NULL,
	sort_order INTEGER NOT NULL,
	UNIQUE(campaign_id, note_id)
);
CREATE TABLE IF NOT EXISTS campaign_whispers (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	whisper_id TEXT NOT NULL,
	from_character_id TEXT NOT NULL,
	to_character_id TEXT NOT NULL,
	text TEXT NOT NULL,
	sort_order INTEGER NOT NULL,
	UNIQUE(campaign_id, whisper_id)
);
CREATE TABLE IF NOT EXISTS campaign_messages (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	actor TEXT NOT NULL,
	kind TEXT NOT NULL,
	text TEXT NOT NULL,
	sort_order INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_invitations (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	invitation_id TEXT NOT NULL,
	username TEXT NOT NULL,
	character_id TEXT NOT NULL,
	status TEXT NOT NULL DEFAULT 'pending',
	sort_order INTEGER NOT NULL,
	UNIQUE(campaign_id, invitation_id)
);
CREATE TABLE IF NOT EXISTS campaign_delegations (
	campaign_id TEXT NOT NULL,
	username TEXT NOT NULL,
	powers TEXT NOT NULL,
	active INTEGER NOT NULL DEFAULT 1,
	PRIMARY KEY (campaign_id, username)
);
CREATE TABLE IF NOT EXISTS campaign_delegation_audit (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	username TEXT NOT NULL,
	action TEXT NOT NULL,
	powers TEXT NOT NULL,
	sort_order INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_audit_events (
	campaign_id TEXT NOT NULL,
	kind TEXT NOT NULL,
	actor TEXT NOT NULL,
	role TEXT NOT NULL,
	timestamp INTEGER NOT NULL,
	correlation_id TEXT NOT NULL,
	PRIMARY KEY (campaign_id, timestamp),
	UNIQUE(campaign_id, correlation_id)
);
CREATE TABLE IF NOT EXISTS campaign_projection_events (
	campaign_id TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	event_id TEXT NOT NULL,
	kind TEXT NOT NULL,
	value TEXT,
	PRIMARY KEY (campaign_id, sequence),
	UNIQUE(campaign_id, event_id)
);
CREATE TABLE IF NOT EXISTS campaign_idempotent_events (
	campaign_id TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	event_id TEXT NOT NULL,
	value TEXT NOT NULL,
	idempotency_key TEXT NOT NULL,
	PRIMARY KEY (campaign_id, sequence),
	UNIQUE(campaign_id, event_id),
	UNIQUE(campaign_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS campaign_safe_turns (
	campaign_id TEXT PRIMARY KEY,
	current_turn INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS campaign_safe_turn_accepted (
	campaign_id TEXT NOT NULL,
	submission_id TEXT NOT NULL,
	action TEXT NOT NULL,
	accepted_turn INTEGER NOT NULL,
	next_turn INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, submission_id),
	UNIQUE(campaign_id, accepted_turn)
);
CREATE TABLE IF NOT EXISTS campaign_transactional_transfers (
	campaign_id TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	from_character_id TEXT NOT NULL,
	to_character_id TEXT NOT NULL,
	amount INTEGER NOT NULL,
	from_gold INTEGER NOT NULL,
	to_gold INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, sequence)
);
CREATE TABLE IF NOT EXISTS campaign_exports (
	campaign_id TEXT NOT NULL,
	version INTEGER NOT NULL,
	story TEXT NOT NULL,
	status TEXT NOT NULL,
	PRIMARY KEY (campaign_id, version)
);
CREATE TABLE IF NOT EXISTS campaign_imports (
	campaign_id TEXT PRIMARY KEY,
	version INTEGER NOT NULL,
	story TEXT NOT NULL,
	status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_migrations (
	campaign_id TEXT PRIMARY KEY,
	schema_version INTEGER NOT NULL,
	story TEXT NOT NULL,
	campaign_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_search_records (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	record_id TEXT NOT NULL,
	text TEXT NOT NULL,
	UNIQUE(campaign_id, record_id)
);
CREATE TABLE IF NOT EXISTS campaign_rate_events (
	campaign_id TEXT NOT NULL,
	event_id TEXT NOT NULL,
	actor TEXT NOT NULL,
	sort_order INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, event_id)
);
CREATE TABLE IF NOT EXISTS campaign_service_metrics (
	campaign_id TEXT PRIMARY KEY,
	accepted_rate_events INTEGER NOT NULL DEFAULT 0,
	rejected_rate_events INTEGER NOT NULL DEFAULT 0,
	projection_events INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS campaign_backups (
	campaign_id TEXT NOT NULL,
	backup_id TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	story TEXT NOT NULL,
	status TEXT NOT NULL,
	PRIMARY KEY (campaign_id, backup_id),
	UNIQUE(campaign_id, sequence)
);
CREATE TABLE IF NOT EXISTS campaign_replay_events (
	campaign_id TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	event_id TEXT NOT NULL,
	kind TEXT NOT NULL,
	text TEXT NOT NULL,
	PRIMARY KEY (campaign_id, sequence),
	UNIQUE(campaign_id, event_id)
);
CREATE TABLE IF NOT EXISTS campaign_rng_seeds (
	campaign_id TEXT PRIMARY KEY,
	seed TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_rng_rolls (
	campaign_id TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	roll_id TEXT NOT NULL,
	sides INTEGER NOT NULL,
	result INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, sequence),
	UNIQUE(campaign_id, roll_id)
);
CREATE TABLE IF NOT EXISTS campaign_moderation_reports (
	campaign_id TEXT NOT NULL,
	report_id TEXT NOT NULL,
	target_id TEXT NOT NULL,
	reason TEXT NOT NULL,
	status TEXT NOT NULL DEFAULT 'open',
	reporter TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	action TEXT,
	note TEXT,
	resolver TEXT,
	PRIMARY KEY (campaign_id, report_id),
	UNIQUE(campaign_id, sequence)
);
CREATE TABLE IF NOT EXISTS campaign_safety_boundaries (
	campaign_id TEXT PRIMARY KEY,
	blocked_tags TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS campaign_safety_events (
	campaign_id TEXT NOT NULL,
	event_id TEXT NOT NULL,
	kind TEXT NOT NULL,
	text TEXT NOT NULL,
	tags TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, event_id),
	UNIQUE(campaign_id, sequence)
);
CREATE TABLE IF NOT EXISTS campaign_fixture_state (
	campaign_id TEXT PRIMARY KEY,
	fixture_id TEXT NOT NULL,
	status TEXT NOT NULL,
	story TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_fixture_characters (
	campaign_id TEXT NOT NULL,
	character_id TEXT NOT NULL,
	name TEXT NOT NULL,
	class TEXT NOT NULL,
	sort_order INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, character_id)
);
CREATE TABLE IF NOT EXISTS campaign_fixture_events (
	campaign_id TEXT NOT NULL,
	event_id TEXT NOT NULL,
	sort_order INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, event_id)
);
CREATE TABLE IF NOT EXISTS campaign_spectators (
	campaign_id TEXT NOT NULL,
	spectator_id TEXT NOT NULL,
	PRIMARY KEY (campaign_id, spectator_id),
	UNIQUE(spectator_id)
);
CREATE TABLE IF NOT EXISTS campaign_feed_events (
	campaign_id TEXT NOT NULL,
	event_id TEXT NOT NULL,
	text TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, event_id),
	UNIQUE(campaign_id, sequence)
);`

// gameTablesDropSQL drops every game table in the order the original reset
// endpoint used. The users table is intentionally omitted so that accounts
// survive a storage reset and authenticated tests can continue to reuse them.
const gameTablesDropSQL = `DROP TABLE IF EXISTS location_connections;
DROP TABLE IF EXISTS campaign_locations;
DROP TABLE IF EXISTS campaign_scenes;
DROP TABLE IF EXISTS play_campaign_members;
DROP TABLE IF EXISTS play_campaigns;
DROP TABLE IF EXISTS campaign_narrations;
DROP TABLE IF EXISTS campaign_relationships;
DROP TABLE IF EXISTS campaign_clues;
DROP TABLE IF EXISTS play_quest_reward_grants;
DROP TABLE IF EXISTS campaign_recipes;
DROP TABLE IF EXISTS campaign_shops;
DROP TABLE IF EXISTS settlement_discoveries;
DROP TABLE IF EXISTS campaign_settlements;
DROP TABLE IF EXISTS campaign_calendars;
DROP TABLE IF EXISTS campaign_world_events;
DROP TABLE IF EXISTS play_quest_dependencies;
DROP TABLE IF EXISTS play_quests;
DROP TABLE IF EXISTS npc_dialogue_entries;
DROP TABLE IF EXISTS faction_reputation_history;
DROP TABLE IF EXISTS play_factions;
DROP TABLE IF EXISTS campaign_npcs;
DROP TABLE IF EXISTS campaign_loot_votes;
DROP TABLE IF EXISTS campaign_loot;
DROP TABLE IF EXISTS campaign_currency_transfers;
DROP TABLE IF EXISTS campaign_encounter_conditions;
DROP TABLE IF EXISTS campaign_encounters;
DROP TABLE IF EXISTS campaign_documents;
DROP TABLE IF EXISTS campaign_exports;
DROP TABLE IF EXISTS campaign_imports;
DROP TABLE IF EXISTS campaign_migrations;
DROP TABLE IF EXISTS session_attendance;
DROP TABLE IF EXISTS campaign_sessions;
DROP TABLE IF EXISTS crafting_projects;
DROP TABLE IF EXISTS character_concentration;
DROP TABLE IF EXISTS character_casts;
DROP TABLE IF EXISTS character_prepared_spells;
DROP TABLE IF EXISTS character_spells;
DROP TABLE IF EXISTS character_equipment_slots;
DROP TABLE IF EXISTS character_inventory_items;
DROP TABLE IF EXISTS character_equipment;
DROP TABLE IF EXISTS campaign_inventory;
DROP TABLE IF EXISTS npcs;
DROP TABLE IF EXISTS factions;
DROP TABLE IF EXISTS campaign_events;
DROP TABLE IF EXISTS quest_milestones;
DROP TABLE IF EXISTS quests;
DROP TABLE IF EXISTS campaign_characters;
DROP TABLE IF EXISTS campaigns;
DROP TABLE IF EXISTS compendium_items;
DROP TABLE IF EXISTS compendium_monsters;
DROP TABLE IF EXISTS combat_conditions;
DROP TABLE IF EXISTS combat_order;
DROP TABLE IF EXISTS combat_sessions;
DROP TABLE IF EXISTS downtime_allocations;
DROP TABLE IF EXISTS downtime_activities;
DROP TABLE IF EXISTS campaign_notes;
DROP TABLE IF EXISTS campaign_whispers;
DROP TABLE IF EXISTS campaign_messages;
DROP TABLE IF EXISTS campaign_invitations;
DROP TABLE IF EXISTS campaign_delegations;
DROP TABLE IF EXISTS campaign_delegation_audit;
DROP TABLE IF EXISTS campaign_projection_events;
DROP TABLE IF EXISTS campaign_idempotent_events;
DROP TABLE IF EXISTS campaign_safe_turn_accepted;
DROP TABLE IF EXISTS campaign_safe_turns;
DROP TABLE IF EXISTS campaign_transactional_transfers;
DROP TABLE IF EXISTS campaign_audit_events;
DROP TABLE IF EXISTS campaign_session_zero_settings;
DROP TABLE IF EXISTS campaign_content;
DROP TABLE IF EXISTS campaign_search_records;
DROP TABLE IF EXISTS campaign_rate_events;
DROP TABLE IF EXISTS campaign_service_metrics;
DROP TABLE IF EXISTS campaign_backups;
DROP TABLE IF EXISTS campaign_replay_events;
DROP TABLE IF EXISTS campaign_rng_rolls;
DROP TABLE IF EXISTS campaign_rng_seeds;
DROP TABLE IF EXISTS campaign_moderation_reports;
DROP TABLE IF EXISTS campaign_safety_events;
DROP TABLE IF EXISTS campaign_safety_boundaries;
DROP TABLE IF EXISTS campaign_spectators;
DROP TABLE IF EXISTS campaign_feed_events;
DROP TABLE IF EXISTS campaign_fixture_events;
DROP TABLE IF EXISTS campaign_fixture_characters;
DROP TABLE IF EXISTS campaign_fixture_state;
DROP TABLE IF EXISTS schema_version;
`

// sq returns a single-quoted SQL string literal with single-quote escaping.
// The caller must still hold dbMu for reads and writes that use this helper.
func sq(s string) string {
	return "'" + strings.ReplaceAll(s, "'", "''") + "'"
}

// queryExists runs a SELECT 1 style query and reports whether any row was
// returned. It centralises the repetitive JSON unmarshal used by existence
// checks across the codebase.
func queryExists(sql string) (bool, error) {
	out, err := dbQuery(sql)
	if err != nil {
		return false, err
	}
	var rows []struct {
		One int `json:"1"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return false, err
	}
	return len(rows) > 0, nil
}

// queryRows runs a query and unmarshals the JSON result set into dest, which
// must be a pointer to a slice. An empty result is unmarshaled as an empty
// slice, matching the contract of dbQuery.
func queryRows(sql string, dest any) error {
	out, err := dbQuery(sql)
	if err != nil {
		return err
	}
	return json.Unmarshal(out, dest)
}

// tableHasColumn reports whether a column exists in the named table. It is
// used by idempotent migration functions to decide whether to run ALTER TABLE.
func tableHasColumn(table, column string) (bool, error) {
	out, err := dbQuery(fmt.Sprintf("PRAGMA table_info(%s);", table))
	if err != nil {
		return false, err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return false, err
	}
	for _, c := range cols {
		if c.Name == column {
			return true, nil
		}
	}
	return false, nil
}

// dbExec runs a SQL statement through the sqlite3 CLI. It is used for DDL,
// DML, and any operation that does not need a result set.
func dbExec(sql string) error {
	cmd := exec.Command("sqlite3", dbPath, sql)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("sqlite3 exec: %v: %s", err, stderr.String())
	}
	return nil
}

// dbQuery runs a SQL query through the sqlite3 CLI and returns the JSON
// result set. An empty result is normalized to the JSON array "[]" so that
// callers always receive a consistent array representation.
func dbQuery(sql string) ([]byte, error) {
	cmd := exec.Command("sqlite3", "-json", dbPath, sql)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("sqlite3 query: %v: %s", err, stderr.String())
	}
	if len(out) == 0 {
		return []byte("[]"), nil
	}
	return out, nil
}

// initDB creates the schema and marks the current schema version. It is safe
// to call multiple times because all CREATE TABLE statements use IF NOT EXISTS.
func initDB() error {
	if err := dbExec(schemaSQL); err != nil {
		return err
	}
	if err := migrateCampaignNarrationsTypeColumn(); err != nil {
		return err
	}
	if err := migratePlayCampaignsTurnColumns(); err != nil {
		return err
	}
	if err := migratePlayCampaignsNudgeCountColumn(); err != nil {
		return err
	}
	if err := migratePlayCampaignsCurrentSceneIDColumn(); err != nil {
		return err
	}
	if err := migrateCampaignNarrationsTravelColumns(); err != nil {
		return err
	}
	if err := migratePlayCampaignsCurrentLocationIDColumn(); err != nil {
		return err
	}
	if err := migratePlayCampaignMembersHPColumns(); err != nil {
		return err
	}
	if err := migratePlayCampaignMembersDeathSavesColumns(); err != nil {
		return err
	}
	if err := migratePlayCampaignMembersOwnerColumn(); err != nil {
		return err
	}
	if err := migrateCampaignEncountersTurnColumns(); err != nil {
		return err
	}
	if err := migrateCampaignNarrationsTargetColumn(); err != nil {
		return err
	}
	if err := migrateCampaignEncounterConditionsTable(); err != nil {
		return err
	}
	if err := migrateCampaignEncountersRewardColumns(); err != nil {
		return err
	}
	if err := migratePlayCampaignsPhaseColumn(); err != nil {
		return err
	}
	if err := migratePlayCampaignsPreCombatActorColumn(); err != nil {
		return err
	}
	if err := migratePlayCampaignMembersLevelColumn(); err != nil {
		return err
	}
	if err := migratePlayCampaignMembersConModifierColumn(); err != nil {
		return err
	}
	if err := migratePlayCampaignMembersAbilityScoreColumns(); err != nil {
		return err
	}
	if err := migrateCharacterSpellsTable(); err != nil {
		return err
	}
	if err := migrateCharacterPreparedSpellsTable(); err != nil {
		return err
	}
	if err := migrateCharacterCastsTable(); err != nil {
		return err
	}
	if err := migrateCharacterConcentrationTable(); err != nil {
		return err
	}
	if err := migrateCharacterInventoryItemsTable(); err != nil {
		return err
	}
	if err := migrateCharacterEquipmentSlotsTable(); err != nil {
		return err
	}
	if err := migratePlayCampaignMembersGoldColumn(); err != nil {
		return err
	}
	if err := migrateCampaignCurrencyTransfersTable(); err != nil {
		return err
	}
	if err := migrateCampaignNpcsTable(); err != nil {
		return err
	}
	if err := migratePlayFactionsTable(); err != nil {
		return err
	}
	if err := migrateFactionReputationHistoryTable(); err != nil {
		return err
	}
	if err := migrateNPCDialogueEntriesTable(); err != nil {
		return err
	}
	if err := migrateCampaignRelationshipsTable(); err != nil {
		return err
	}
	if err := migrateCampaignCluesTable(); err != nil {
		return err
	}
	if err := migratePlayQuestsTables(); err != nil {
		return err
	}
	if err := migratePlayQuestRewardsTables(); err != nil {
		return err
	}
	if err := migrateCampaignWorldEventsTable(); err != nil {
		return err
	}
	if err := migrateCampaignSettlementsTables(); err != nil {
		return err
	}
	if err := migrateCampaignShopsTable(); err != nil {
		return err
	}
	if err := migrateCampaignRecipesTable(); err != nil {
		return err
	}
	if err := migrateDowntimeTables(); err != nil {
		return err
	}
	if err := migratePlayCampaignMembersPrimaryKey(); err != nil {
		return err
	}
	if err := migrateCampaignSessionZeroSettingsTable(); err != nil {
		return err
	}
	if err := migrateCampaignContentTable(); err != nil {
		return err
	}
	if err := migrateCampaignNotesTable(); err != nil {
		return err
	}
	if err := migrateCampaignWhispersTable(); err != nil {
		return err
	}
	if err := migrateCampaignInvitationsTable(); err != nil {
		return err
	}
	if err := migrateCampaignDelegationsTables(); err != nil {
		return err
	}
	if err := migrateCampaignAuditEventsTable(); err != nil {
		return err
	}
	if err := migrateCampaignProjectionEventsTable(); err != nil {
		return err
	}
	if err := migrateCampaignIdempotentEventsTable(); err != nil {
		return err
	}
	if err := migrateCampaignSafeTurnsTables(); err != nil {
		return err
	}
	if err := migrateCampaignTransactionalTransfersTable(); err != nil {
		return err
	}
	if err := migrateCampaignExportsTable(); err != nil {
		return err
	}
	if err := migrateCampaignSearchRecordsTable(); err != nil {
		return err
	}
	if err := migrateCampaignRateEventsTable(); err != nil {
		return err
	}
	if err := migrateCampaignServiceMetricsTable(); err != nil {
		return err
	}
	if err := migrateCampaignBackupsTable(); err != nil {
		return err
	}
	if err := migrateCampaignRNGLedgerTables(); err != nil {
		return err
	}
	if err := migrateCampaignSafetyTables(); err != nil {
		return err
	}
	if err := migrateCampaignSpectatorsTable(); err != nil {
		return err
	}
	if err := migrateCampaignFeedEventsTable(); err != nil {
		return err
	}
	return nil
}

// migrateCampaignWorldEventsTable creates the campaign_world_events table if
// it does not yet exist. It is used when starting against a database created
// before the world-events stage.
func migrateCampaignWorldEventsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_world_events';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_world_events (
		id INTEGER PRIMARY KEY,
		campaign_id TEXT NOT NULL,
		event_id TEXT NOT NULL,
		turn_number INTEGER NOT NULL,
		title TEXT NOT NULL,
		text TEXT NOT NULL,
		status TEXT NOT NULL DEFAULT 'scheduled',
		resolution_text TEXT,
		UNIQUE(campaign_id, event_id)
	);`)
}

// migratePlayQuestRewardsTables adds the quest rewards columns and the per-
// character grant tracking table if they are missing. This allows older
// databases created before the quest-rewards stage to start successfully.
func migratePlayQuestRewardsTables() error {
	out, err := dbQuery(`PRAGMA table_info(play_quests);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	hasRewardsXP := false
	hasRewardsItems := false
	hasRewardsAwarded := false
	for _, c := range cols {
		if c.Name == "rewards_xp" {
			hasRewardsXP = true
		}
		if c.Name == "rewards_items" {
			hasRewardsItems = true
		}
		if c.Name == "rewards_awarded" {
			hasRewardsAwarded = true
		}
	}
	if !hasRewardsXP {
		if err := dbExec(`ALTER TABLE play_quests ADD COLUMN rewards_xp INTEGER NOT NULL DEFAULT 0;`); err != nil {
			return err
		}
	}
	if !hasRewardsItems {
		if err := dbExec(`ALTER TABLE play_quests ADD COLUMN rewards_items TEXT NOT NULL DEFAULT '{}';`); err != nil {
			return err
		}
	}
	if !hasRewardsAwarded {
		if err := dbExec(`ALTER TABLE play_quests ADD COLUMN rewards_awarded INTEGER NOT NULL DEFAULT 0;`); err != nil {
			return err
		}
	}

	out, err = dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='play_quest_reward_grants';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE play_quest_reward_grants (
		id INTEGER PRIMARY KEY,
		campaign_id TEXT NOT NULL,
		quest_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		xp INTEGER NOT NULL DEFAULT 0,
		items TEXT NOT NULL DEFAULT '{}',
		UNIQUE(campaign_id, quest_id, character_id)
	);`)
}

// migrateCampaignNarrationsTypeColumn adds the type column to
// campaign_narrations if it is missing. The column stores the action type
// for action events; narration events leave it NULL.
func migrateCampaignNarrationsTypeColumn() error {
	out, err := dbQuery(`PRAGMA table_info(campaign_narrations);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	for _, c := range cols {
		if c.Name == "type" {
			return nil
		}
	}
	return dbExec(`ALTER TABLE campaign_narrations ADD COLUMN type TEXT;`)
}

// migrateCampaignNarrationsTravelColumns adds the destination_id and
// travel_turns columns to campaign_narrations if they are missing. These
// columns store the travel details for travel-turn events.
func migrateCampaignNarrationsTravelColumns() error {
	out, err := dbQuery(`PRAGMA table_info(campaign_narrations);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	hasDestination := false
	hasTravelTurns := false
	for _, c := range cols {
		if c.Name == "destination_id" {
			hasDestination = true
		}
		if c.Name == "travel_turns" {
			hasTravelTurns = true
		}
	}
	if !hasDestination {
		if err := dbExec(`ALTER TABLE campaign_narrations ADD COLUMN destination_id TEXT;`); err != nil {
			return err
		}
	}
	if !hasTravelTurns {
		if err := dbExec(`ALTER TABLE campaign_narrations ADD COLUMN travel_turns INTEGER;`); err != nil {
			return err
		}
	}
	return nil
}

// migratePlayCampaignsCurrentSceneIDColumn adds the current_scene_id column
// to play_campaigns if it is missing. The column stores the id of the scene
// that is currently active for the campaign.
func migratePlayCampaignsCurrentSceneIDColumn() error {
	out, err := dbQuery(`PRAGMA table_info(play_campaigns);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	for _, c := range cols {
		if c.Name == "current_scene_id" {
			return nil
		}
	}
	return dbExec(`ALTER TABLE play_campaigns ADD COLUMN current_scene_id TEXT;`)
}

// migratePlayCampaignsCurrentLocationIDColumn adds the current_location_id
// column to play_campaigns if it is missing. The column stores the party's
// current location in the deterministic location graph.
func migratePlayCampaignsCurrentLocationIDColumn() error {
	out, err := dbQuery(`PRAGMA table_info(play_campaigns);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	for _, c := range cols {
		if c.Name == "current_location_id" {
			return nil
		}
	}
	return dbExec(`ALTER TABLE play_campaigns ADD COLUMN current_location_id TEXT;`)
}

// migratePlayCampaignsNudgeCountColumn adds the nudge_count column to
// play_campaigns if it is missing. The column tracks the total number of
// owner nudges issued against the campaign for deterministic timeout policy.
func migratePlayCampaignsNudgeCountColumn() error {
	out, err := dbQuery(`PRAGMA table_info(play_campaigns);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	for _, c := range cols {
		if c.Name == "nudge_count" {
			return nil
		}
	}
	return dbExec(`ALTER TABLE play_campaigns ADD COLUMN nudge_count INTEGER NOT NULL DEFAULT 0;`)
}

// migratePlayCampaignsTurnColumns adds the turn tracking columns to
// play_campaigns if they are missing. For active campaigns created before the
// turn queue was introduced, the first member is selected as the initial
// actor and turn_number is set to 1.
func migratePlayCampaignsTurnColumns() error {
	out, err := dbQuery(`PRAGMA table_info(play_campaigns);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	hasTurnNumber := false
	hasTurnActor := false
	for _, c := range cols {
		if c.Name == "turn_number" {
			hasTurnNumber = true
		}
		if c.Name == "turn_actor" {
			hasTurnActor = true
		}
	}
	if hasTurnNumber && hasTurnActor {
		return nil
	}
	if !hasTurnNumber {
		if err := dbExec(`ALTER TABLE play_campaigns ADD COLUMN turn_number INTEGER NOT NULL DEFAULT 0;`); err != nil {
			return err
		}
	}
	if !hasTurnActor {
		if err := dbExec(`ALTER TABLE play_campaigns ADD COLUMN turn_actor TEXT;`); err != nil {
			return err
		}
	}
	// Initialize active campaigns that do not yet have a turn actor.
	return dbExec(`UPDATE play_campaigns
SET turn_actor = (
	SELECT username FROM play_campaign_members
	WHERE play_campaign_members.campaign_id = play_campaigns.id
	ORDER BY join_order LIMIT 1
),
turn_number = 1
WHERE status = 'active' AND turn_actor IS NULL;`)
}

// migrateCampaignNarrationsTargetColumn adds the target column to
// campaign_narrations if it is missing. The column stores the target of
// combat_action events.
func migrateCampaignNarrationsTargetColumn() error {
	out, err := dbQuery(`PRAGMA table_info(campaign_narrations);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	for _, c := range cols {
		if c.Name == "target" {
			return nil
		}
	}
	return dbExec(`ALTER TABLE campaign_narrations ADD COLUMN target TEXT;`)
}

// migrateCampaignEncountersRewardColumns adds the xp_awarded, loot, and
// rewards_awarded columns to campaign_encounters if they are missing. They
// store the deterministic rewards awarded by the encounter owner and whether
// rewards have already been awarded for the encounter.
func migrateCampaignEncountersRewardColumns() error {
	out, err := dbQuery(`PRAGMA table_info(campaign_encounters);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	hasXPAwarded := false
	hasLoot := false
	hasRewardsAwarded := false
	for _, c := range cols {
		switch c.Name {
		case "xp_awarded":
			hasXPAwarded = true
		case "loot":
			hasLoot = true
		case "rewards_awarded":
			hasRewardsAwarded = true
		}
	}
	if !hasXPAwarded {
		if err := dbExec(`ALTER TABLE campaign_encounters ADD COLUMN xp_awarded INTEGER NOT NULL DEFAULT 0;`); err != nil {
			return err
		}
	}
	if !hasLoot {
		if err := dbExec(`ALTER TABLE campaign_encounters ADD COLUMN loot TEXT NOT NULL DEFAULT '[]';`); err != nil {
			return err
		}
	}
	if !hasRewardsAwarded {
		if err := dbExec(`ALTER TABLE campaign_encounters ADD COLUMN rewards_awarded INTEGER NOT NULL DEFAULT 0;`); err != nil {
			return err
		}
	}
	return nil
}

// migrateCampaignEncounterConditionsTable creates the campaign encounter
// conditions table if it does not yet exist. This is needed when the server
// starts against a database created before the condition-interactions stage.
func migrateCampaignEncounterConditionsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_encounter_conditions';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_encounter_conditions (
		id INTEGER PRIMARY KEY,
		encounter_id TEXT NOT NULL,
		campaign_id TEXT NOT NULL,
		target TEXT NOT NULL,
		"condition" TEXT NOT NULL,
		remaining_rounds INTEGER NOT NULL
	);`)
}

// migratePlayCampaignsPhaseColumn adds the phase column to play_campaigns if
// it is missing. The column tracks whether the campaign is in exploration or
// combat phase.
func migratePlayCampaignsPhaseColumn() error {
	out, err := dbQuery(`PRAGMA table_info(play_campaigns);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	for _, c := range cols {
		if c.Name == "phase" {
			return nil
		}
	}
	return dbExec(`ALTER TABLE play_campaigns ADD COLUMN phase TEXT;`)
}

// migratePlayCampaignsPreCombatActorColumn adds the pre_combat_actor column to
// play_campaigns if it is missing. The column stores the exploration turn actor
// so the queue can resume after combat ends.
func migratePlayCampaignsPreCombatActorColumn() error {
	out, err := dbQuery(`PRAGMA table_info(play_campaigns);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	for _, c := range cols {
		if c.Name == "pre_combat_actor" {
			return nil
		}
	}
	return dbExec(`ALTER TABLE play_campaigns ADD COLUMN pre_combat_actor TEXT;`)
}

// migratePlayCampaignMembersOwnerColumn adds the owner column to
// play_campaign_members if it is missing. Existing members have their owner
// set to their username so that the implicit ownership from earlier stages is
// preserved.
func migratePlayCampaignMembersOwnerColumn() error {
	out, err := dbQuery(`PRAGMA table_info(play_campaign_members);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	for _, c := range cols {
		if c.Name == "owner" {
			return nil
		}
	}
	if err := dbExec(`ALTER TABLE play_campaign_members ADD COLUMN owner TEXT;`); err != nil {
		return err
	}
	return dbExec(`UPDATE play_campaign_members SET owner=username WHERE owner IS NULL;`)
}

// migratePlayCampaignMembersLevelColumn adds the level column to
// play_campaign_members if it is missing. Existing members default to level 1.
func migratePlayCampaignMembersLevelColumn() error {
	out, err := dbQuery(`PRAGMA table_info(play_campaign_members);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	for _, c := range cols {
		if c.Name == "level" {
			return nil
		}
	}
	return dbExec(`ALTER TABLE play_campaign_members ADD COLUMN level INTEGER NOT NULL DEFAULT 1;`)
}

// migratePlayCampaignMembersConModifierColumn adds the con_modifier column to
// play_campaign_members if it is missing. Existing members default to 0.
func migratePlayCampaignMembersConModifierColumn() error {
	out, err := dbQuery(`PRAGMA table_info(play_campaign_members);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	for _, c := range cols {
		if c.Name == "con_modifier" {
			return nil
		}
	}
	return dbExec(`ALTER TABLE play_campaign_members ADD COLUMN con_modifier INTEGER NOT NULL DEFAULT 0;`)
}

// migratePlayCampaignMembersAbilityScoreColumns adds the six ability score
// columns to play_campaign_members if they are missing. Existing members
// default to 10 (modifier 0) for skill-check resolution.
func migratePlayCampaignMembersAbilityScoreColumns() error {
	out, err := dbQuery(`PRAGMA table_info(play_campaign_members);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	has := map[string]bool{}
	for _, c := range cols {
		has[c.Name] = true
	}
	for _, col := range []string{"str_score", "dex_score", "con_score", "int_score", "wis_score", "cha_score"} {
		if has[col] {
			continue
		}
		if err := dbExec(fmt.Sprintf(`ALTER TABLE play_campaign_members ADD COLUMN %s INTEGER NOT NULL DEFAULT 10;`, col)); err != nil {
			return err
		}
	}
	return nil
}

// migrateCampaignEncountersTurnColumns adds the round and turn_index columns
// to campaign_encounters if they are missing. Default values start the first
// combatant at round 1, turn index 0.
func migrateCampaignEncountersTurnColumns() error {
	out, err := dbQuery(`PRAGMA table_info(campaign_encounters);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	hasRound := false
	hasTurnIndex := false
	for _, c := range cols {
		if c.Name == "round" {
			hasRound = true
		}
		if c.Name == "turn_index" {
			hasTurnIndex = true
		}
	}
	if !hasRound {
		if err := dbExec(`ALTER TABLE campaign_encounters ADD COLUMN round INTEGER NOT NULL DEFAULT 1;`); err != nil {
			return err
		}
	}
	if !hasTurnIndex {
		if err := dbExec(`ALTER TABLE campaign_encounters ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0;`); err != nil {
			return err
		}
	}
	return nil
}

// migratePlayCampaignMembersHPColumns adds the hp_max and hp_current columns
// to play_campaign_members if they are missing. Default values are provided
// so existing party members receive a deterministic starting HP pool.
func migratePlayCampaignMembersHPColumns() error {
	out, err := dbQuery(`PRAGMA table_info(play_campaign_members);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	hasHPMax := false
	hasHPCurrent := false
	for _, c := range cols {
		if c.Name == "hp_max" {
			hasHPMax = true
		}
		if c.Name == "hp_current" {
			hasHPCurrent = true
		}
	}
	if !hasHPMax {
		if err := dbExec(`ALTER TABLE play_campaign_members ADD COLUMN hp_max INTEGER NOT NULL DEFAULT 20;`); err != nil {
			return err
		}
	}
	if !hasHPCurrent {
		if err := dbExec(`ALTER TABLE play_campaign_members ADD COLUMN hp_current INTEGER NOT NULL DEFAULT 20;`); err != nil {
			return err
		}
	}
	return nil
}

// migratePlayCampaignMembersDeathSavesColumns adds the status and death-save
// counter columns to play_campaign_members if they are missing. Existing
// members start conscious with zero counters.
func migratePlayCampaignMembersDeathSavesColumns() error {
	out, err := dbQuery(`PRAGMA table_info(play_campaign_members);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	hasStatus := false
	hasSuccesses := false
	hasFailures := false
	for _, c := range cols {
		switch c.Name {
		case "status":
			hasStatus = true
		case "death_saves_successes":
			hasSuccesses = true
		case "death_saves_failures":
			hasFailures = true
		}
	}
	if !hasStatus {
		if err := dbExec(`ALTER TABLE play_campaign_members ADD COLUMN status TEXT NOT NULL DEFAULT 'conscious';`); err != nil {
			return err
		}
	}
	if !hasSuccesses {
		if err := dbExec(`ALTER TABLE play_campaign_members ADD COLUMN death_saves_successes INTEGER NOT NULL DEFAULT 0;`); err != nil {
			return err
		}
	}
	if !hasFailures {
		if err := dbExec(`ALTER TABLE play_campaign_members ADD COLUMN death_saves_failures INTEGER NOT NULL DEFAULT 0;`); err != nil {
			return err
		}
	}
	return nil
}

// queryVersion reads the stored schema version. The bool result indicates
// whether a version row exists at all.
func queryVersion() (int, bool, error) {
	var rows []struct {
		Version int `json:"version"`
	}
	if err := queryRows(`SELECT version FROM schema_version LIMIT 1;`, &rows); err != nil {
		return 0, false, err
	}
	if len(rows) == 0 {
		return 0, false, nil
	}
	return rows[0].Version, true, nil
}

// writeJSON writes a JSON response with the given status code. Encoding errors
// are logged but never returned to the client, so the response is already
// committed by the time an error can be detected.
func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(body); err != nil {
		log.Printf("encode error: %v", err)
	}
}

// writeError writes the standard error envelope used by every handler in this
// service. It preserves the exact error messages required by the cumulative
// evaluator suite, so callers should pass the same message strings that were
// used in the original implementation.
func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]any{"error": message})
}

// healthHandler reports that the server is running. It does not exercise the
// database, so it can be used as a liveness check.
func healthHandler(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}

// storageStatusHandler returns the storage driver and schema version. If the
// schema_version table has not been initialized yet, it still reports version 1
// but with initialized=false.
func storageStatusHandler(w http.ResponseWriter, r *http.Request) {
	version, ok, err := queryVersion()
	if err != nil || !ok {
		writeJSON(w, http.StatusOK, map[string]any{"driver": "sqlite", "schema_version": 1, "initialized": false})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"driver": "sqlite", "schema_version": version, "initialized": true})
}

// storageResetHandler drops all game tables and recreates the schema from scratch.
// The users table is preserved so that authenticated play-surface tests can
// reuse accounts created by earlier auth tests. This is intended for test
// isolation and deterministic replays.
func storageResetHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	if err := dbExec(gameTablesDropSQL + schemaSQL); err != nil {
		log.Printf("storage reset error: %v", err)
		writeError(w, http.StatusInternalServerError, "reset failed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "schema_version": 1})
}

// migrateCharacterSpellsTable creates the character_spells table if it does
// not yet exist. It is used when starting against a database created before
// the spellbook-state stage.
func migrateCharacterSpellsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='character_spells';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE character_spells (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		spell_id TEXT NOT NULL,
		name TEXT NOT NULL,
		level INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, character_id, spell_id)
	);`)
}

// migrateCharacterPreparedSpellsTable creates the character_prepared_spells
// table if it does not yet exist. It is used when starting against a database
// created before the spell-preparation stage.
func migrateCharacterPreparedSpellsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='character_prepared_spells';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE character_prepared_spells (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		spell_id TEXT NOT NULL,
		sort_order INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, character_id, spell_id)
	);`)
}

// migrateCharacterCastsTable creates the character_casts table if it does not
// yet exist. It is used when starting against a database created before the
// spell-casting stage.
func migrateCharacterCastsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='character_casts';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE character_casts (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		sequence INTEGER NOT NULL,
		spell_id TEXT NOT NULL,
		target TEXT NOT NULL,
		slot_level INTEGER NOT NULL,
		slots_remaining INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, character_id, sequence)
	);`)
}

// migrateCharacterInventoryItemsTable creates the character_inventory_items table
// if it does not yet exist. It is used when starting against a database created
// before the inventory-stacks stage.
func migrateCharacterInventoryItemsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='character_inventory_items';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE character_inventory_items (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		item_id TEXT NOT NULL,
		quantity INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, character_id, item_id)
	);`)
}

// migrateCharacterEquipmentSlotsTable creates the character_equipment_slots
// table if it does not yet exist. It is used when starting against a database
// created before the equipment-and-attunement stage.
func migrateCharacterEquipmentSlotsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='character_equipment_slots';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE character_equipment_slots (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		slot TEXT NOT NULL,
		item_id TEXT NOT NULL,
		attuned INTEGER NOT NULL DEFAULT 0,
		PRIMARY KEY (campaign_id, character_id, slot)
	);`)
}

// migrateCharacterConcentrationTable creates the character_concentration table
// if it does not yet exist. It is used when starting against a database created
// before the concentration stage.
func migrateCharacterConcentrationTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='character_concentration';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE character_concentration (
		campaign_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		spell_id TEXT NOT NULL,
		target TEXT NOT NULL,
		remaining_turns INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, character_id)
	);`)
}

// migratePlayCampaignMembersPrimaryKey changes the primary key of
// play_campaign_members from a single character_id key to a composite
// (campaign_id, character_id) key. This allows the same character id to be
// reused across different play campaigns while still preventing duplicates
// within a single campaign.
func migratePlayCampaignMembersPrimaryKey() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='play_campaign_members';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) == 0 {
		return nil
	}

	out, err = dbQuery(`PRAGMA table_info(play_campaign_members);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
		PK   int    `json:"pk"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	for _, c := range cols {
		if c.Name == "character_id" && c.PK == 1 {
			if err := dbExec(`ALTER TABLE play_campaign_members RENAME TO _play_campaign_members_old;`); err != nil {
				return err
			}
			if err := dbExec(`CREATE TABLE play_campaign_members (
				campaign_id TEXT NOT NULL,
				username TEXT NOT NULL,
				character_id TEXT NOT NULL,
				name TEXT NOT NULL,
				class TEXT NOT NULL,
				join_order INTEGER NOT NULL DEFAULT 0,
				level INTEGER NOT NULL DEFAULT 1,
				con_modifier INTEGER NOT NULL DEFAULT 0,
				hp_max INTEGER NOT NULL DEFAULT 20,
				hp_current INTEGER NOT NULL DEFAULT 20,
				status TEXT NOT NULL DEFAULT 'conscious',
				death_saves_successes INTEGER NOT NULL DEFAULT 0,
				death_saves_failures INTEGER NOT NULL DEFAULT 0,
				owner TEXT,
				str_score INTEGER NOT NULL DEFAULT 10,
				dex_score INTEGER NOT NULL DEFAULT 10,
				con_score INTEGER NOT NULL DEFAULT 10,
				int_score INTEGER NOT NULL DEFAULT 10,
				wis_score INTEGER NOT NULL DEFAULT 10,
				cha_score INTEGER NOT NULL DEFAULT 10,
				gold INTEGER NOT NULL DEFAULT 10,
				PRIMARY KEY (campaign_id, character_id),
				UNIQUE(campaign_id, username)
			);`); err != nil {
				return err
			}
			if err := dbExec(`INSERT INTO play_campaign_members SELECT * FROM _play_campaign_members_old;`); err != nil {
				return err
			}
			return dbExec(`DROP TABLE _play_campaign_members_old;`)
		}
	}
	return nil
}

// migratePlayCampaignMembersGoldColumn adds the gold column to
// play_campaign_members if it is missing. Existing members receive the
// deterministic starting balance of 10 gold.
func migratePlayCampaignMembersGoldColumn() error {
	out, err := dbQuery(`PRAGMA table_info(play_campaign_members);`)
	if err != nil {
		return err
	}
	var cols []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &cols); err != nil {
		return err
	}
	for _, c := range cols {
		if c.Name == "gold" {
			return nil
		}
	}
	return dbExec(`ALTER TABLE play_campaign_members ADD COLUMN gold INTEGER NOT NULL DEFAULT 10;`)
}

// migrateCampaignNpcsTable creates the campaign_npcs table if it does not yet
// exist. It is used when starting against a database created before the
// npc-agendas stage.
func migrateCampaignNpcsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_npcs';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_npcs (
		campaign_id TEXT NOT NULL,
		npc_id TEXT NOT NULL,
		name TEXT NOT NULL,
		agenda TEXT NOT NULL,
		public_status TEXT NOT NULL,
		PRIMARY KEY (campaign_id, npc_id)
	);`)
}

// migratePlayFactionsTable creates the play_factions table if it does not yet
// exist. It is used when starting against a database created before the
// faction-reputation stage.
func migratePlayFactionsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='play_factions';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE play_factions (
		campaign_id TEXT NOT NULL,
		faction_id TEXT NOT NULL,
		name TEXT NOT NULL,
		PRIMARY KEY (campaign_id, faction_id)
	);`)
}

// migrateFactionReputationHistoryTable creates the faction_reputation_history
// table if it does not yet exist. It is used when starting against a database
// created before the faction-reputation stage.
func migrateFactionReputationHistoryTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='faction_reputation_history';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE faction_reputation_history (
		id INTEGER PRIMARY KEY,
		campaign_id TEXT NOT NULL,
		faction_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		delta INTEGER NOT NULL,
		reputation INTEGER NOT NULL,
		reason TEXT NOT NULL
	);`)
}

// migrateNPCDialogueEntriesTable creates the npc_dialogue_entries table if it
// does not yet exist. It is used when starting against a database created
// before the npc-dialogue stage.
func migrateNPCDialogueEntriesTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='npc_dialogue_entries';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE npc_dialogue_entries (
		id INTEGER PRIMARY KEY,
		campaign_id TEXT NOT NULL,
		npc_id TEXT NOT NULL,
		dialogue_id TEXT NOT NULL,
		speaker TEXT NOT NULL,
		text TEXT NOT NULL,
		visibility TEXT NOT NULL,
		UNIQUE(campaign_id, npc_id, dialogue_id)
	);`)
}

// migrateCampaignRelationshipsTable creates the campaign_relationships table if
// it does not yet exist. It is used when starting against a database created before
// the relationship-graph stage.
func migrateCampaignRelationshipsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_relationships';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_relationships (
		id INTEGER PRIMARY KEY,
		campaign_id TEXT NOT NULL,
		source_id TEXT NOT NULL,
		target_id TEXT NOT NULL,
		kind TEXT NOT NULL,
		score INTEGER NOT NULL,
		UNIQUE(campaign_id, source_id, target_id, kind)
	);`)
}

// migrateCampaignCluesTable creates the campaign_clues table if it does not yet
// exist. It is used when starting against a database created before the
// secrets-and-clues stage.
func migrateCampaignCluesTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_clues';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_clues (
		id INTEGER PRIMARY KEY,
		campaign_id TEXT NOT NULL,
		clue_id TEXT NOT NULL,
		text TEXT NOT NULL,
		audience TEXT NOT NULL,
		character_id TEXT,
		UNIQUE(campaign_id, clue_id)
	);`)
}

// migrateCampaignCurrencyTransfersTable creates the campaign_currency_transfers
// table if it does not yet exist. It is used when starting against a database
// created before the currency-and-trade stage.
func migrateCampaignCurrencyTransfersTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_currency_transfers';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_currency_transfers (
		campaign_id TEXT NOT NULL,
		transfer_id INTEGER NOT NULL,
		from_character_id TEXT NOT NULL,
		to_character_id TEXT NOT NULL,
		gold INTEGER NOT NULL,
		PRIMARY KEY (campaign_id, transfer_id)
	);`)
}

// migratePlayQuestsTables creates the play_quests and play_quest_dependencies
// tables if they do not yet exist. It is used when starting against a database
// created before the quest-dependencies stage.
func migratePlayQuestsTables() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='play_quests';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE play_quests (
		id INTEGER PRIMARY KEY,
		campaign_id TEXT NOT NULL,
		quest_id TEXT NOT NULL,
		title TEXT NOT NULL,
		state TEXT NOT NULL,
		UNIQUE(campaign_id, quest_id)
	);
	CREATE TABLE play_quest_dependencies (
		id INTEGER PRIMARY KEY,
		campaign_id TEXT NOT NULL,
		quest_id TEXT NOT NULL,
		depends_on TEXT NOT NULL,
		UNIQUE(campaign_id, quest_id, depends_on)
	);`)
}

// migrateCampaignSettlementsTables creates the campaign_settlements and
// settlement_discoveries tables if they do not yet exist. It is used when
// starting against a database created before the settlements stage.
func migrateCampaignSettlementsTables() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_settlements';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_settlements (
		id INTEGER PRIMARY KEY,
		campaign_id TEXT NOT NULL,
		settlement_id TEXT NOT NULL,
		name TEXT NOT NULL,
		services TEXT NOT NULL,
		availability TEXT NOT NULL,
		UNIQUE(campaign_id, settlement_id)
	);
	CREATE TABLE settlement_discoveries (
		id INTEGER PRIMARY KEY,
		campaign_id TEXT NOT NULL,
		settlement_id TEXT NOT NULL,
		character_id TEXT NOT NULL,
		UNIQUE(campaign_id, settlement_id, character_id)
	);`)
}

// migrateCampaignShopsTable creates the campaign_shops table if it does not
// yet exist. It is used when starting against a database created before the
// shops stage.
func migrateCampaignShopsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_shops';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_shops (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	settlement_id TEXT NOT NULL,
	shop_id TEXT NOT NULL,
	name TEXT NOT NULL,
	stock TEXT NOT NULL,
	buy_price INTEGER NOT NULL,
	sell_price INTEGER NOT NULL,
	UNIQUE(campaign_id, settlement_id, shop_id)
);`)
}

// migrateCampaignRecipesTable creates the campaign_recipes table if it does
// not yet exist. It is used when starting against a database created before the
// recipe-catalog stage.
func migrateCampaignRecipesTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_recipes';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_recipes (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	recipe_id TEXT NOT NULL,
	name TEXT NOT NULL,
	ingredients TEXT NOT NULL,
	output_item TEXT NOT NULL,
	output_quantity INTEGER NOT NULL,
	UNIQUE(campaign_id, recipe_id)
);`)
}

// migrateDowntimeTables creates the downtime_activities and
// downtime_allocations tables if they do not yet exist. They are used to track
// recurring downtime activities and per-character progress.
func migrateDowntimeTables() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='downtime_activities';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE downtime_activities (
	campaign_id TEXT NOT NULL,
	activity_id TEXT NOT NULL,
	name TEXT NOT NULL,
	cycles_required INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, activity_id)
);
CREATE TABLE downtime_allocations (
	campaign_id TEXT NOT NULL,
	character_id TEXT NOT NULL,
	activity_id TEXT NOT NULL,
	cycles_completed INTEGER NOT NULL DEFAULT 0,
	completions INTEGER NOT NULL DEFAULT 0,
	PRIMARY KEY (campaign_id, character_id, activity_id)
);`)
}

// migrateCampaignSessionZeroSettingsTable creates the
// campaign_session_zero_settings table if it does not yet exist. It is used
// when starting against a database created before the session-zero settings
// stage.
func migrateCampaignSessionZeroSettingsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_session_zero_settings';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_session_zero_settings (
	campaign_id TEXT PRIMARY KEY,
	rules TEXT NOT NULL,
	tone TEXT NOT NULL,
	consent TEXT NOT NULL
);`)
}

// migrateCampaignContentTable creates the campaign_content table if it does
// not yet exist. It is used when starting against a database created before the
// content-tags stage.
func migrateCampaignContentTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_content';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_content (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	content_id TEXT NOT NULL,
	kind TEXT NOT NULL,
	text TEXT NOT NULL,
	tags TEXT NOT NULL,
	sort_order INTEGER NOT NULL,
	UNIQUE(campaign_id, content_id)
);`)
}

// migrateCampaignNotesTable creates the campaign_notes table if it does not
// yet exist. It is used when starting against a database created before the
// privacy-controls stage.
func migrateCampaignNotesTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_notes';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_notes (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	note_id TEXT NOT NULL,
	text TEXT NOT NULL,
	visibility TEXT NOT NULL,
	owner TEXT NOT NULL,
	sort_order INTEGER NOT NULL,
	UNIQUE(campaign_id, note_id)
);`)
}

// migrateCampaignWhispersTable creates the campaign_whispers table if it does
// not yet exist. It is used when starting against a database created before the
// privacy-controls stage.
func migrateCampaignWhispersTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_whispers';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_whispers (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	whisper_id TEXT NOT NULL,
	from_character_id TEXT NOT NULL,
	to_character_id TEXT NOT NULL,
	text TEXT NOT NULL,
	sort_order INTEGER NOT NULL,
	UNIQUE(campaign_id, whisper_id)
);`)
}

// migrateCampaignInvitationsTable creates the campaign_invitations table if it
// does not yet exist. It is used when starting against a database created before
// the campaign-invitations stage.
func migrateCampaignInvitationsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_invitations';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_invitations (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	invitation_id TEXT NOT NULL,
	username TEXT NOT NULL,
	character_id TEXT NOT NULL,
	status TEXT NOT NULL DEFAULT 'pending',
	sort_order INTEGER NOT NULL,
	UNIQUE(campaign_id, invitation_id)
);`)
}

// migrateCampaignAuditEventsTable creates the campaign_audit_events table if
// it does not yet exist. It is used when starting against a database created
// before the actor-audit-trail stage.
func migrateCampaignAuditEventsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_audit_events';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_audit_events (
	campaign_id TEXT NOT NULL,
	kind TEXT NOT NULL,
	actor TEXT NOT NULL,
	role TEXT NOT NULL,
	timestamp INTEGER NOT NULL,
	correlation_id TEXT NOT NULL,
	PRIMARY KEY (campaign_id, timestamp),
	UNIQUE(campaign_id, correlation_id)
);`)
}

// migrateCampaignProjectionEventsTable creates the campaign_projection_events
// table if it does not yet exist. It is used when starting against a database
// created before the event-projections stage.
func migrateCampaignProjectionEventsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_projection_events';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_projection_events (
	campaign_id TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	event_id TEXT NOT NULL,
	kind TEXT NOT NULL,
	value TEXT,
	PRIMARY KEY (campaign_id, sequence),
	UNIQUE(campaign_id, event_id)
);`)
}

// migrateCampaignIdempotentEventsTable creates the campaign_idempotent_events
// table if it does not yet exist. It is used when starting against a database
// created before the idempotency-keys stage.
func migrateCampaignIdempotentEventsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_idempotent_events';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_idempotent_events (
	campaign_id TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	event_id TEXT NOT NULL,
	value TEXT NOT NULL,
	idempotency_key TEXT NOT NULL,
	PRIMARY KEY (campaign_id, sequence),
	UNIQUE(campaign_id, event_id),
	UNIQUE(campaign_id, idempotency_key)
);`)
}

// migrateCampaignSafeTurnsTables creates the campaign_safe_turns and
// campaign_safe_turn_accepted tables if they do not yet exist. They are used
// by the concurrent turn safety stage.
func migrateCampaignSafeTurnsTables() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_safe_turns';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_safe_turns (
	campaign_id TEXT PRIMARY KEY,
	current_turn INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE campaign_safe_turn_accepted (
	campaign_id TEXT NOT NULL,
	submission_id TEXT NOT NULL,
	action TEXT NOT NULL,
	accepted_turn INTEGER NOT NULL,
	next_turn INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, submission_id),
	UNIQUE(campaign_id, accepted_turn)
);`)
}

// migrateCampaignTransactionalTransfersTable creates the
// campaign_transactional_transfers table if it does not yet exist. It is used
// when starting against a database created before the transaction-recovery
// stage.
func migrateCampaignTransactionalTransfersTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_transactional_transfers';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_transactional_transfers (
	campaign_id TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	from_character_id TEXT NOT NULL,
	to_character_id TEXT NOT NULL,
	amount INTEGER NOT NULL,
	from_gold INTEGER NOT NULL,
	to_gold INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, sequence)
);`)
}

// migrateCampaignDelegationsTables creates the campaign_delegations and
// campaign_delegation_audit tables if they do not yet exist. It is used when
// starting against a database created before the gm-delegation stage.
func migrateCampaignDelegationsTables() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_delegations';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) == 0 {
		if err := dbExec(`CREATE TABLE campaign_delegations (
	campaign_id TEXT NOT NULL,
	username TEXT NOT NULL,
	powers TEXT NOT NULL,
	active INTEGER NOT NULL DEFAULT 1,
	PRIMARY KEY (campaign_id, username)
);`); err != nil {
			return err
		}
	}

	out, err = dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_delegation_audit';`)
	if err != nil {
		return err
	}
	rows = nil
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_delegation_audit (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	username TEXT NOT NULL,
	action TEXT NOT NULL,
	powers TEXT NOT NULL,
	sort_order INTEGER NOT NULL
);`)
}

// migrateCampaignExportsTable creates the campaign_exports table if it does not
// yet exist. It is used when starting against a database created before the
// versioned-export stage.
func migrateCampaignExportsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_exports';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_exports (
	campaign_id TEXT NOT NULL,
	version INTEGER NOT NULL,
	story TEXT NOT NULL,
	status TEXT NOT NULL,
	PRIMARY KEY (campaign_id, version)
);`)
}

// migrateCampaignSearchRecordsTable creates the campaign_search_records table
// if it does not yet exist. It is used when starting against a database created
// before the pagination-search stage.
func migrateCampaignSearchRecordsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_search_records';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_search_records (
	id INTEGER PRIMARY KEY,
	campaign_id TEXT NOT NULL,
	record_id TEXT NOT NULL,
	text TEXT NOT NULL,
	UNIQUE(campaign_id, record_id)
);`)
}

// migrateCampaignRateEventsTable creates the campaign_rate_events table if it
// does not yet exist. It is used when starting against a database created before
// the rate-limits stage.
func migrateCampaignRateEventsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_rate_events';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_rate_events (
	campaign_id TEXT NOT NULL,
	event_id TEXT NOT NULL,
	actor TEXT NOT NULL,
	sort_order INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, event_id)
);`)
}

// migrateCampaignServiceMetricsTable creates the campaign_service_metrics table
// if it does not yet exist. It is used when starting against a database created
// before the service-metrics stage.
func migrateCampaignServiceMetricsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_service_metrics';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_service_metrics (
	campaign_id TEXT PRIMARY KEY,
	accepted_rate_events INTEGER NOT NULL DEFAULT 0,
	rejected_rate_events INTEGER NOT NULL DEFAULT 0,
	projection_events INTEGER NOT NULL DEFAULT 0
);`)
}

// migrateCampaignBackupsTable creates the campaign_backups table if it does
// not already exist.
func migrateCampaignBackupsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_backups';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_backups (
	campaign_id TEXT NOT NULL,
	backup_id TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	story TEXT NOT NULL,
	status TEXT NOT NULL,
	PRIMARY KEY (campaign_id, backup_id),
	UNIQUE(campaign_id, sequence)
);`)
}

// migrateCampaignRNGLedgerTables creates the campaign RNG seed and roll ledger
// tables if they do not yet exist. They are used by the deterministic RNG
// ledger stage.
func migrateCampaignRNGLedgerTables() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_rng_seeds';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) == 0 {
		if err := dbExec(`CREATE TABLE campaign_rng_seeds (
		campaign_id TEXT PRIMARY KEY,
		seed TEXT NOT NULL
	);`); err != nil {
			return err
		}
	}

	out, err = dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_rng_rolls';`)
	if err != nil {
		return err
	}
	rows = nil
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_rng_rolls (
	campaign_id TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	roll_id TEXT NOT NULL,
	sides INTEGER NOT NULL,
	result INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, sequence),
	UNIQUE(campaign_id, roll_id)
);`)
}

// migrateCampaignSpectatorsTable creates the spectator ticket table if it
// does not yet exist. Spectator IDs are globally unique across tickets.
func migrateCampaignSpectatorsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_spectators';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_spectators (
	campaign_id TEXT NOT NULL,
	spectator_id TEXT NOT NULL,
	PRIMARY KEY (campaign_id, spectator_id),
	UNIQUE(spectator_id)
);`)
}

// migrateCampaignFeedEventsTable creates the campaign feed event table if it
// does not yet exist. It is used when starting against a database created
// before the load-safe event feed stage.
func migrateCampaignFeedEventsTable() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_feed_events';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_feed_events (
	campaign_id TEXT NOT NULL,
	event_id TEXT NOT NULL,
	text TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, event_id),
	UNIQUE(campaign_id, sequence)
);`)
}

// migrateCampaignSafetyTables creates the safety boundaries and accepted
// safety events tables if they do not yet exist.
func migrateCampaignSafetyTables() error {
	out, err := dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_safety_boundaries';`)
	if err != nil {
		return err
	}
	var rows []struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) == 0 {
		if err := dbExec(`CREATE TABLE campaign_safety_boundaries (
		campaign_id TEXT PRIMARY KEY,
		blocked_tags TEXT NOT NULL DEFAULT '[]'
	);`); err != nil {
			return err
		}
	}

	out, err = dbQuery(`SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_safety_events';`)
	if err != nil {
		return err
	}
	rows = nil
	if err := json.Unmarshal(out, &rows); err != nil {
		return err
	}
	if len(rows) > 0 {
		return nil
	}
	return dbExec(`CREATE TABLE campaign_safety_events (
	campaign_id TEXT NOT NULL,
	event_id TEXT NOT NULL,
	kind TEXT NOT NULL,
	text TEXT NOT NULL,
	tags TEXT NOT NULL,
	sequence INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, event_id),
	UNIQUE(campaign_id, sequence)
);`)
}
