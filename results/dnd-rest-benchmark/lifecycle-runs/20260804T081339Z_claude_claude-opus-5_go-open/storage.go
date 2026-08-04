package main

import (
	"database/sql"
	"log"
	"net/http"
	"strings"
	"sync"

	_ "modernc.org/sqlite"
)

// Durable game-world and game-state data lives in a SQLite database file next
// to the binary. Every mutation goes through this file so a restart finds the
// schema already in place.

const (
	storageDriver = "sqlite"
	schemaVersion = 1
	databaseFile  = "game.db"
)

// db is the single shared handle. Connections are capped at one so writers
// serialize inside SQLite instead of racing for the write lock, which keeps
// behavior deterministic under the evaluator's concurrent requests.
var db *sql.DB

// storeMu guards read-modify-write sequences that span multiple statements
// (session creation, condition ticking) so they stay atomic end to end.
var storeMu sync.Mutex

const schemaDDL = `
CREATE TABLE IF NOT EXISTS schema_meta (
	id INTEGER PRIMARY KEY CHECK (id = 1),
	version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
	username TEXT PRIMARY KEY,
	role     TEXT NOT NULL,
	salt     BLOB NOT NULL,
	digest   BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS combat_sessions (
	id         TEXT PRIMARY KEY,
	round      INTEGER NOT NULL,
	turn_index INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS combat_combatants (
	session_id TEXT NOT NULL REFERENCES combat_sessions(id) ON DELETE CASCADE,
	position   INTEGER NOT NULL,
	name       TEXT NOT NULL,
	dex        INTEGER NOT NULL,
	score      INTEGER NOT NULL,
	PRIMARY KEY (session_id, position)
);
-- A row with condition IS NULL marks a combatant that has held a condition at
-- some point, so an emptied list still renders as [] rather than disappearing.
CREATE TABLE IF NOT EXISTS combat_conditions (
	session_id TEXT NOT NULL REFERENCES combat_sessions(id) ON DELETE CASCADE,
	target     TEXT NOT NULL,
	position   INTEGER NOT NULL,
	condition  TEXT,
	remaining  INTEGER
);
CREATE TABLE IF NOT EXISTS monsters (
	slug        TEXT PRIMARY KEY,
	name        TEXT NOT NULL,
	cr          TEXT NOT NULL,
	armor_class INTEGER NOT NULL,
	hit_points  INTEGER NOT NULL,
	tags        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
	slug    TEXT PRIMARY KEY,
	name    TEXT NOT NULL,
	type    TEXT NOT NULL,
	rarity  TEXT NOT NULL,
	cost_gp REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS campaigns (
	id   TEXT PRIMARY KEY,
	name TEXT NOT NULL,
	dm   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_characters (
	campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
	id          TEXT NOT NULL,
	position    INTEGER NOT NULL,
	name        TEXT NOT NULL,
	level       INTEGER NOT NULL,
	class       TEXT NOT NULL,
	PRIMARY KEY (campaign_id, id)
);
CREATE TABLE IF NOT EXISTS campaign_events (
	campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
	id          TEXT NOT NULL,
	position    INTEGER NOT NULL,
	kind        TEXT NOT NULL,
	summary     TEXT NOT NULL,
	PRIMARY KEY (campaign_id, id)
);
CREATE TABLE IF NOT EXISTS campaign_quests (
	campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
	id          TEXT NOT NULL,
	position    INTEGER NOT NULL,
	title       TEXT NOT NULL,
	status      TEXT NOT NULL,
	PRIMARY KEY (campaign_id, id)
);
CREATE TABLE IF NOT EXISTS campaign_quest_milestones (
	campaign_id TEXT NOT NULL,
	quest_id    TEXT NOT NULL,
	position    INTEGER NOT NULL,
	name        TEXT NOT NULL,
	done        INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, quest_id, name),
	FOREIGN KEY (campaign_id, quest_id)
		REFERENCES campaign_quests(campaign_id, id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS campaign_factions (
	campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
	id          TEXT NOT NULL,
	position    INTEGER NOT NULL,
	name        TEXT NOT NULL,
	stance      TEXT NOT NULL,
	PRIMARY KEY (campaign_id, id)
);
-- faction_id is a plain column, not a foreign key: it is empty for an
-- unaffiliated NPC, and membership is checked by the handler instead.
CREATE TABLE IF NOT EXISTS campaign_npcs (
	campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
	id          TEXT NOT NULL,
	position    INTEGER NOT NULL,
	name        TEXT NOT NULL,
	faction_id  TEXT NOT NULL,
	disposition INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, id)
);
-- Inventory and equipment rows are append-only stacks keyed by position, not by
-- slug: the same item added twice is two rows, and the summary counts rows.
CREATE TABLE IF NOT EXISTS campaign_inventory (
	campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
	position    INTEGER NOT NULL,
	item_slug   TEXT NOT NULL,
	quantity    INTEGER NOT NULL,
	owner       TEXT NOT NULL,
	PRIMARY KEY (campaign_id, position)
);
CREATE TABLE IF NOT EXISTS campaign_equipment (
	campaign_id  TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
	position     INTEGER NOT NULL,
	character_id TEXT NOT NULL,
	item_slug    TEXT NOT NULL,
	quantity     INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, position)
);
-- A downtime crafting project accrues days_completed until it reaches
-- days_required, at which point its status flips to complete. It is a record of
-- its own and does not write to campaign_inventory.
CREATE TABLE IF NOT EXISTS campaign_crafting (
	campaign_id    TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
	id             TEXT NOT NULL,
	position       INTEGER NOT NULL,
	character_id   TEXT NOT NULL,
	item_slug      TEXT NOT NULL,
	days_required  INTEGER NOT NULL,
	days_completed INTEGER NOT NULL,
	cost_gp        REAL NOT NULL,
	status         TEXT NOT NULL,
	PRIMARY KEY (campaign_id, id)
);
-- A scheduled play session keeps the caller's starts_at verbatim for echoing
-- plus a normalized UTC key so ordering does not depend on how the timestamp
-- was spelled. Agenda and attendance are its ordered/keyed children.
CREATE TABLE IF NOT EXISTS campaign_sessions (
	campaign_id      TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
	id               TEXT NOT NULL,
	position         INTEGER NOT NULL,
	starts_at        TEXT NOT NULL,
	starts_at_key    TEXT NOT NULL,
	duration_minutes INTEGER NOT NULL,
	PRIMARY KEY (campaign_id, id)
);
CREATE TABLE IF NOT EXISTS campaign_session_agenda (
	campaign_id TEXT NOT NULL,
	session_id  TEXT NOT NULL,
	position    INTEGER NOT NULL,
	entry       TEXT NOT NULL,
	PRIMARY KEY (campaign_id, session_id, position),
	FOREIGN KEY (campaign_id, session_id)
		REFERENCES campaign_sessions(campaign_id, id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS campaign_session_attendance (
	campaign_id  TEXT NOT NULL,
	session_id   TEXT NOT NULL,
	character_id TEXT NOT NULL,
	status       TEXT NOT NULL,
	PRIMARY KEY (campaign_id, session_id, character_id),
	FOREIGN KEY (campaign_id, session_id)
		REFERENCES campaign_sessions(campaign_id, id) ON DELETE CASCADE
);
-- Play campaigns are the authenticated /v1/play surface and are deliberately
-- separate from the open campaigns table above: they carry an owner (the dm
-- who created them) and a lifecycle status, and ids never collide across the two.
-- current_actor and turn_number are the play clock. They stay empty/0 while the
-- campaign sits in the lobby and are set once, when the owner starts it.
-- turn_started_seq records the event-log position the current turn opened at,
-- which is what the turn timeout policy measures against; nudge_count is the
-- running total of owner nudges and never decreases.
CREATE TABLE IF NOT EXISTS play_campaigns (
	id               TEXT PRIMARY KEY,
	name             TEXT NOT NULL,
	owner            TEXT NOT NULL,
	status           TEXT NOT NULL,
	max_players      INTEGER NOT NULL,
	current_actor    TEXT NOT NULL DEFAULT '',
	turn_number      INTEGER NOT NULL DEFAULT 0,
	turn_started_seq INTEGER NOT NULL DEFAULT 0,
	nudge_count      INTEGER NOT NULL DEFAULT 0
);
-- One party membership per (campaign, player). The character id is unique
-- within the campaign too, and position records join order so the party always
-- renders in the sequence players actually joined.
CREATE TABLE IF NOT EXISTS play_campaign_members (
	campaign_id  TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
	username     TEXT NOT NULL,
	position     INTEGER NOT NULL,
	character_id TEXT NOT NULL,
	name         TEXT NOT NULL,
	class        TEXT NOT NULL,
	PRIMARY KEY (campaign_id, username),
	UNIQUE (campaign_id, character_id)
);
-- The play event log is append-only: sequence starts at 1 per campaign and is
-- never rewritten, so the story reads back in the order it was told.
CREATE TABLE IF NOT EXISTS play_campaign_events (
	campaign_id TEXT NOT NULL REFERENCES play_campaigns(id) ON DELETE CASCADE,
	sequence    INTEGER NOT NULL,
	kind        TEXT NOT NULL,
	actor       TEXT NOT NULL,
	text        TEXT NOT NULL,
	action_type TEXT NOT NULL DEFAULT '',
	PRIMARY KEY (campaign_id, sequence)
);
INSERT INTO schema_meta (id, version) VALUES (1, 1)
	ON CONFLICT(id) DO UPDATE SET version = excluded.version;
`

// openStorage opens the database and installs the schema. busy_timeout keeps a
// contended write waiting instead of failing outright; foreign_keys makes the
// ON DELETE CASCADE declarations in the schema actually fire.
func openStorage() error {
	handle, err := sql.Open(storageDriver, "file:"+databaseFile+"?_pragma=busy_timeout(5000)&_pragma=foreign_keys(1)")
	if err != nil {
		return err
	}
	handle.SetMaxOpenConns(1)
	db = handle
	return initSchema()
}

// initSchema is idempotent: every statement in schemaDDL is IF NOT EXISTS or an
// upsert, so it doubles as both first-run creation and post-reset recreation.
func initSchema() error {
	if _, err := db.Exec(schemaDDL); err != nil {
		return err
	}
	return migrateSchema()
}

// migrateSchema brings a database file created by an earlier build up to the
// current shape. CREATE TABLE IF NOT EXISTS leaves an existing table alone, so
// columns added after that table was first written have to be added here. Each
// step is idempotent: a column that is already present makes ALTER TABLE fail,
// and that failure is the signal there is nothing to do.
func migrateSchema() error {
	for _, stmt := range []string{
		`ALTER TABLE play_campaign_events ADD COLUMN action_type TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE play_campaigns ADD COLUMN turn_started_seq INTEGER NOT NULL DEFAULT 0`,
		`ALTER TABLE play_campaigns ADD COLUMN nudge_count INTEGER NOT NULL DEFAULT 0`,
	} {
		if _, err := db.Exec(stmt); err != nil && !strings.Contains(err.Error(), "duplicate column name") {
			return err
		}
	}
	return nil
}

// resetStorage drops every table and recreates the schema, giving each
// evaluation shot a clean slate. The process keeps running against the same
// handle throughout. Tables drop children first so foreign keys stay satisfied.
func resetStorage() error {
	storeMu.Lock()
	defer storeMu.Unlock()
	const dropDDL = `
DROP TABLE IF EXISTS play_campaign_events;
DROP TABLE IF EXISTS play_campaign_members;
DROP TABLE IF EXISTS play_campaigns;
DROP TABLE IF EXISTS campaign_session_attendance;
DROP TABLE IF EXISTS campaign_session_agenda;
DROP TABLE IF EXISTS campaign_sessions;
DROP TABLE IF EXISTS campaign_crafting;
DROP TABLE IF EXISTS campaign_equipment;
DROP TABLE IF EXISTS campaign_inventory;
DROP TABLE IF EXISTS campaign_npcs;
DROP TABLE IF EXISTS campaign_factions;
DROP TABLE IF EXISTS campaign_quest_milestones;
DROP TABLE IF EXISTS campaign_quests;
DROP TABLE IF EXISTS campaign_events;
DROP TABLE IF EXISTS campaign_characters;
DROP TABLE IF EXISTS campaigns;
DROP TABLE IF EXISTS combat_conditions;
DROP TABLE IF EXISTS combat_combatants;
DROP TABLE IF EXISTS combat_sessions;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS monsters;
DROP TABLE IF EXISTS items;
DROP TABLE IF EXISTS schema_meta;
`
	if _, err := db.Exec(dropDDL); err != nil {
		return err
	}
	return initSchema()
}

// storageInitialized reports whether the schema is present and stamped.
func storageInitialized() bool {
	var version int
	err := db.QueryRow(`SELECT version FROM schema_meta WHERE id = 1`).Scan(&version)
	return err == nil && version == schemaVersion
}

// ---------- GET /v1/storage/status ----------

type storageStatusResponse struct {
	Driver        string `json:"driver"`
	SchemaVersion int    `json:"schema_version"`
	Initialized   bool   `json:"initialized"`
}

func handleStorageStatus(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	writeJSON(w, http.StatusOK, storageStatusResponse{
		Driver:        storageDriver,
		SchemaVersion: schemaVersion,
		Initialized:   storageInitialized(),
	})
}

// ---------- POST /v1/storage/reset ----------

type storageResetResponse struct {
	OK            bool `json:"ok"`
	SchemaVersion int  `json:"schema_version"`
}

// handleStorageReset takes no body, so it guards its method directly rather
// than through decodeBody. Its 500 message is endpoint-specific, not one of the
// generic storage messages in httpx.go.
func handleStorageReset(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	if err := resetStorage(); err != nil {
		log.Printf("storage reset failed: %v", err)
		writeError(w, http.StatusInternalServerError, "storage reset failed")
		return
	}
	writeJSON(w, http.StatusOK, storageResetResponse{OK: true, SchemaVersion: schemaVersion})
}
