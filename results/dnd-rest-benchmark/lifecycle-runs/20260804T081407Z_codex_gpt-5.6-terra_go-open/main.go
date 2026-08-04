package main

import (
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	_ "modernc.org/sqlite"
)

var (
	diceExpression  = regexp.MustCompile(`^([0-9]+)d([0-9]+)([+-][0-9]+)?$`)
	usernamePattern = regexp.MustCompile(`^[a-z0-9_-]{2,32}$`)
	slugPattern     = regexp.MustCompile(`^[a-z0-9][a-z0-9-]*$`)
)

type combatant struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
	dex   int
}

type condition struct {
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

type combatSession struct {
	ID         string
	Round      int
	TurnIndex  int
	Order      []combatant
	Conditions map[string][]condition
}

type combatStore struct {
	sync.Mutex
	sessions map[string]*combatSession
}

var sessions = combatStore{sessions: make(map[string]*combatSession)}

type user struct {
	Username     string
	Role         string
	PasswordHash []byte
	PasswordSalt []byte
}

type userStore struct {
	sync.Mutex
	users map[string]user
}

var users = userStore{users: make(map[string]user)}

const schemaVersion = 1

const playCampaignMemberOrder = `SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY CASE WHEN join_order > 0 THEN 0 ELSE 1 END, join_order, username`

// resetStatements is ordered from referencing tables to their parents so a
// storage reset remains valid while SQLite foreign-key enforcement is enabled.
var resetStatements = []string{
	"DELETE FROM session_attendance", "DELETE FROM session_agenda", "DELETE FROM campaign_sessions",
	"DELETE FROM character_equipment", "DELETE FROM campaign_inventory", "DELETE FROM crafting_projects",
	"DELETE FROM quest_milestones", "DELETE FROM quests", "DELETE FROM campaign_events",
	"DELETE FROM campaign_characters", "DELETE FROM campaign_npcs", "DELETE FROM campaign_factions",
	"DELETE FROM campaigns", "DELETE FROM play_campaign_encounter_rewards_loot", "DELETE FROM play_campaign_encounter_rewards", "DELETE FROM play_campaign_encounter_ready_actions", "DELETE FROM play_campaign_encounter_turn_order", "DELETE FROM play_campaign_encounter_conditions", "DELETE FROM play_campaign_encounter_combatants", "DELETE FROM play_campaign_encounter_monsters", "DELETE FROM play_campaign_encounters", "DELETE FROM play_campaign_scene_state", "DELETE FROM play_campaign_scenes",
	"DELETE FROM play_campaign_combat_actions", "DELETE FROM play_campaign_rests", "DELETE FROM play_campaign_travels", "DELETE FROM play_campaign_party_locations",
	"DELETE FROM play_campaign_location_connections", "DELETE FROM play_campaign_locations",
	"DELETE FROM play_campaign_event_sequences",
	"DELETE FROM play_campaign_resolutions", "DELETE FROM play_campaign_actions",
	"DELETE FROM play_campaign_turns", "DELETE FROM play_campaign_narrations", "DELETE FROM play_campaign_documents",
	"DELETE FROM play_campaign_members", "DELETE FROM play_campaigns", "DELETE FROM monster_tags",
	"DELETE FROM monsters", "DELETE FROM items", "DELETE FROM combat_conditions", "DELETE FROM combatants",
	"DELETE FROM combat_sessions", "DELETE FROM users",
}

var storage struct {
	sync.Mutex
	db          *sql.DB
	initialized bool
}

func main() {
	if err := initializeStorage("game.db"); err != nil {
		fmt.Fprintln(os.Stderr, "initialize storage:", err)
		os.Exit(1)
	}
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	server := &http.Server{Addr: "127.0.0.1:" + port, Handler: newRouter()}
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

func storageStatus(w http.ResponseWriter, _ *http.Request) {
	storage.Lock()
	initialized := storage.initialized && storage.db != nil
	storage.Unlock()
	writeJSON(w, http.StatusOK, map[string]any{"driver": "sqlite", "schema_version": schemaVersion, "initialized": initialized})
}

func resetStorage(w http.ResponseWriter, _ *http.Request) {
	storage.Lock()
	defer storage.Unlock()
	if storage.db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	for _, statement := range resetStatements {
		if _, err := storage.db.Exec(statement); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to reset storage"})
			return
		}
	}
	sessions.Lock()
	sessions.sessions = make(map[string]*combatSession)
	sessions.Unlock()
	users.Lock()
	users.users = make(map[string]user)
	users.Unlock()
	storage.initialized = true
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "schema_version": schemaVersion})
}

func initializeStorage(path string) error {
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return err
	}
	statements := []string{
		`PRAGMA foreign_keys = ON`,
		`CREATE TABLE IF NOT EXISTS schema_metadata (version INTEGER NOT NULL)`,
		`CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, role TEXT NOT NULL, password_hash BLOB NOT NULL, password_salt BLOB NOT NULL)`,
		`CREATE TABLE IF NOT EXISTS combat_sessions (id TEXT PRIMARY KEY, round INTEGER NOT NULL, turn_index INTEGER NOT NULL)`,
		`CREATE TABLE IF NOT EXISTS combatants (session_id TEXT NOT NULL, position INTEGER NOT NULL, name TEXT NOT NULL, score INTEGER NOT NULL, dex INTEGER NOT NULL, PRIMARY KEY(session_id, position), FOREIGN KEY(session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS combat_conditions (session_id TEXT NOT NULL, target TEXT NOT NULL, position INTEGER NOT NULL, condition_name TEXT NOT NULL, remaining_rounds INTEGER NOT NULL, PRIMARY KEY(session_id, target, position), FOREIGN KEY(session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS monsters (slug TEXT PRIMARY KEY, name TEXT NOT NULL, cr TEXT NOT NULL, armor_class INTEGER NOT NULL, hit_points INTEGER NOT NULL)`,
		`CREATE TABLE IF NOT EXISTS monster_tags (monster_slug TEXT NOT NULL, position INTEGER NOT NULL, tag TEXT NOT NULL, PRIMARY KEY(monster_slug, position), FOREIGN KEY(monster_slug) REFERENCES monsters(slug) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS items (slug TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, rarity TEXT NOT NULL, cost_gp INTEGER NOT NULL)`,
		`CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, dm TEXT NOT NULL)`,
		`CREATE TABLE IF NOT EXISTS play_campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('lobby', 'active', 'combat')), max_players INTEGER NOT NULL CHECK(max_players > 0))`,
		`CREATE TABLE IF NOT EXISTS play_campaign_members (campaign_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, class TEXT NOT NULL, race TEXT NOT NULL DEFAULT '', background TEXT NOT NULL DEFAULT '', character_owner TEXT NOT NULL DEFAULT '', join_order INTEGER NOT NULL DEFAULT 0, level INTEGER NOT NULL DEFAULT 1 CHECK(level BETWEEN 1 AND 20), strength INTEGER NOT NULL DEFAULT 10 CHECK(strength BETWEEN 1 AND 30), dexterity INTEGER NOT NULL DEFAULT 10 CHECK(dexterity BETWEEN 1 AND 30), constitution INTEGER NOT NULL DEFAULT 10 CHECK(constitution BETWEEN 1 AND 30), intelligence INTEGER NOT NULL DEFAULT 10 CHECK(intelligence BETWEEN 1 AND 30), wisdom INTEGER NOT NULL DEFAULT 10 CHECK(wisdom BETWEEN 1 AND 30), charisma INTEGER NOT NULL DEFAULT 10 CHECK(charisma BETWEEN 1 AND 30), con_modifier INTEGER NOT NULL DEFAULT 0, hp_current INTEGER NOT NULL DEFAULT 20 CHECK(hp_current >= 0), hp_max INTEGER NOT NULL DEFAULT 20 CHECK(hp_max > 0), death_save_successes INTEGER NOT NULL DEFAULT 0 CHECK(death_save_successes BETWEEN 0 AND 3), death_save_failures INTEGER NOT NULL DEFAULT 0 CHECK(death_save_failures BETWEEN 0 AND 3), status TEXT NOT NULL DEFAULT 'conscious' CHECK(status IN ('conscious', 'unconscious', 'stable', 'dead')), PRIMARY KEY(campaign_id, username), FOREIGN KEY(campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_documents (campaign_id TEXT PRIMARY KEY, story TEXT NOT NULL, dm_notes TEXT NOT NULL, FOREIGN KEY(campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_narrations (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK(sequence > 0), text TEXT NOT NULL, PRIMARY KEY(campaign_id, sequence), FOREIGN KEY(campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_actions (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK(sequence > 0), actor TEXT NOT NULL, type TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY(campaign_id, sequence), FOREIGN KEY(campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_resolutions (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK(sequence > 0), actor TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY(campaign_id, sequence), FOREIGN KEY(campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_event_sequences (campaign_id TEXT PRIMARY KEY, sequence INTEGER NOT NULL DEFAULT 0 CHECK(sequence >= 0), FOREIGN KEY(campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_turns (campaign_id TEXT PRIMARY KEY, current_actor TEXT NOT NULL, turn_number INTEGER NOT NULL DEFAULT 1 CHECK(turn_number > 0), nudge_count INTEGER NOT NULL DEFAULT 0 CHECK(nudge_count >= 0), FOREIGN KEY(campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_scenes (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('open', 'closed')), PRIMARY KEY(campaign_id, id), FOREIGN KEY(campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_scene_state (campaign_id TEXT PRIMARY KEY, current_scene_id TEXT NOT NULL, FOREIGN KEY(campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_locations (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY(campaign_id, id), FOREIGN KEY(campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_location_connections (campaign_id TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL, travel_turns INTEGER NOT NULL CHECK(travel_turns > 0), PRIMARY KEY(campaign_id, from_id, to_id), FOREIGN KEY(campaign_id, from_id) REFERENCES play_campaign_locations(campaign_id, id) ON DELETE CASCADE, FOREIGN KEY(campaign_id, to_id) REFERENCES play_campaign_locations(campaign_id, id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_party_locations (campaign_id TEXT PRIMARY KEY, location_id TEXT NOT NULL, FOREIGN KEY(campaign_id, location_id) REFERENCES play_campaign_locations(campaign_id, id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_travels (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK(sequence > 0), actor TEXT NOT NULL, destination_id TEXT NOT NULL, travel_turns INTEGER NOT NULL CHECK(travel_turns > 0), PRIMARY KEY(campaign_id, sequence), FOREIGN KEY(campaign_id, destination_id) REFERENCES play_campaign_locations(campaign_id, id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_rests (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK(sequence > 0), actor TEXT NOT NULL, type TEXT NOT NULL CHECK(type IN ('short', 'long')), hp_current INTEGER NOT NULL CHECK(hp_current >= 0), hp_max INTEGER NOT NULL CHECK(hp_max > 0), PRIMARY KEY(campaign_id, sequence), FOREIGN KEY(campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_encounters (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active', 'closed')), round INTEGER NOT NULL DEFAULT 1 CHECK(round > 0), turn_index INTEGER NOT NULL DEFAULT 0 CHECK(turn_index >= 0), PRIMARY KEY(campaign_id, id), FOREIGN KEY(campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_encounter_monsters (campaign_id TEXT NOT NULL, encounter_id TEXT NOT NULL, monster_id TEXT NOT NULL, name TEXT NOT NULL, hp_max INTEGER NOT NULL CHECK(hp_max > 0), hp_current INTEGER NOT NULL CHECK(hp_current >= 0), initiative INTEGER NOT NULL, PRIMARY KEY(campaign_id, encounter_id, monster_id), FOREIGN KEY(campaign_id, encounter_id) REFERENCES play_campaign_encounters(campaign_id, id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_encounter_combatants (campaign_id TEXT NOT NULL, encounter_id TEXT NOT NULL, member TEXT NOT NULL, character_id TEXT NOT NULL, name TEXT NOT NULL, initiative INTEGER NOT NULL, PRIMARY KEY(campaign_id, encounter_id, member), FOREIGN KEY(campaign_id, encounter_id) REFERENCES play_campaign_encounters(campaign_id, id) ON DELETE CASCADE, FOREIGN KEY(campaign_id, member) REFERENCES play_campaign_members(campaign_id, username) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_encounter_conditions (campaign_id TEXT NOT NULL, encounter_id TEXT NOT NULL, target TEXT NOT NULL, position INTEGER NOT NULL, condition_name TEXT NOT NULL, remaining_rounds INTEGER NOT NULL CHECK(remaining_rounds > 0), PRIMARY KEY(campaign_id, encounter_id, target, position), FOREIGN KEY(campaign_id, encounter_id) REFERENCES play_campaign_encounters(campaign_id, id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_encounter_turn_order (campaign_id TEXT NOT NULL, encounter_id TEXT NOT NULL, position INTEGER NOT NULL CHECK(position >= 0), kind TEXT NOT NULL CHECK(kind IN ('monster', 'player')), member TEXT NOT NULL, PRIMARY KEY(campaign_id, encounter_id, position), UNIQUE(campaign_id, encounter_id, kind, member), FOREIGN KEY(campaign_id, encounter_id) REFERENCES play_campaign_encounters(campaign_id, id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_encounter_ready_actions (campaign_id TEXT NOT NULL, encounter_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK(sequence > 0), actor TEXT NOT NULL, trigger_text TEXT NOT NULL, PRIMARY KEY(campaign_id, encounter_id, sequence), FOREIGN KEY(campaign_id, encounter_id, actor) REFERENCES play_campaign_encounter_combatants(campaign_id, encounter_id, member) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_encounter_rewards (campaign_id TEXT NOT NULL, encounter_id TEXT NOT NULL, xp INTEGER NOT NULL CHECK(xp >= 0), PRIMARY KEY(campaign_id, encounter_id), FOREIGN KEY(campaign_id, encounter_id) REFERENCES play_campaign_encounters(campaign_id, id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_encounter_rewards_loot (campaign_id TEXT NOT NULL, encounter_id TEXT NOT NULL, position INTEGER NOT NULL CHECK(position >= 0), slug TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0), PRIMARY KEY(campaign_id, encounter_id, position), FOREIGN KEY(campaign_id, encounter_id) REFERENCES play_campaign_encounter_rewards(campaign_id, encounter_id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_combat_actions (campaign_id TEXT NOT NULL, encounter_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK(sequence > 0), actor TEXT NOT NULL, type TEXT NOT NULL CHECK(type IN ('attack', 'help', 'dodge', 'ready')), target TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY(campaign_id, sequence), FOREIGN KEY(campaign_id, encounter_id) REFERENCES play_campaign_encounters(campaign_id, id) ON DELETE CASCADE, FOREIGN KEY(campaign_id, encounter_id, actor) REFERENCES play_campaign_encounter_combatants(campaign_id, encounter_id, member) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS campaign_characters (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL, class TEXT NOT NULL, PRIMARY KEY(campaign_id, id), FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS campaign_inventory (campaign_id TEXT NOT NULL, item_slug TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity >= 0), PRIMARY KEY(campaign_id, item_slug), FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS character_equipment (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0), PRIMARY KEY(campaign_id, character_id, item_slug), FOREIGN KEY(campaign_id, character_id) REFERENCES campaign_characters(campaign_id, id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS crafting_projects (campaign_id TEXT NOT NULL, id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, days_required INTEGER NOT NULL CHECK(days_required > 0), days_completed INTEGER NOT NULL DEFAULT 0 CHECK(days_completed >= 0), cost_gp INTEGER NOT NULL CHECK(cost_gp >= 0), status TEXT NOT NULL CHECK(status IN ('active', 'complete')), PRIMARY KEY(campaign_id, id), FOREIGN KEY(campaign_id, character_id) REFERENCES campaign_characters(campaign_id, id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS campaign_events (campaign_id TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL, summary TEXT NOT NULL, PRIMARY KEY(campaign_id, id), FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS campaign_factions (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, stance TEXT NOT NULL, PRIMARY KEY(campaign_id, id), FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS campaign_npcs (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, faction_id TEXT NOT NULL, disposition INTEGER NOT NULL, PRIMARY KEY(campaign_id, id), FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE, FOREIGN KEY(campaign_id, faction_id) REFERENCES campaign_factions(campaign_id, id) ON DELETE RESTRICT)`,
		`CREATE TABLE IF NOT EXISTS quests (campaign_id TEXT NOT NULL, id TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY(campaign_id, id), FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS quest_milestones (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, name TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(campaign_id, quest_id, name), FOREIGN KEY(campaign_id, quest_id) REFERENCES quests(campaign_id, id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS campaign_sessions (campaign_id TEXT NOT NULL, id TEXT NOT NULL, starts_at TEXT NOT NULL, duration_minutes INTEGER NOT NULL CHECK(duration_minutes > 0), PRIMARY KEY(campaign_id, id), FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS session_agenda (campaign_id TEXT NOT NULL, session_id TEXT NOT NULL, position INTEGER NOT NULL, item TEXT NOT NULL, PRIMARY KEY(campaign_id, session_id, position), FOREIGN KEY(campaign_id, session_id) REFERENCES campaign_sessions(campaign_id, id) ON DELETE CASCADE)`,
		`CREATE TABLE IF NOT EXISTS session_attendance (campaign_id TEXT NOT NULL, session_id TEXT NOT NULL, character_id TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('present', 'absent')), PRIMARY KEY(campaign_id, session_id, character_id), FOREIGN KEY(campaign_id, session_id) REFERENCES campaign_sessions(campaign_id, id) ON DELETE CASCADE, FOREIGN KEY(campaign_id, character_id) REFERENCES campaign_characters(campaign_id, id) ON DELETE CASCADE)`,
	}
	for _, statement := range statements {
		if _, err := db.Exec(statement); err != nil {
			db.Close()
			return err
		}
	}
	// Databases from the location-graph stage have locations but no party
	// position. Preserve their deterministic first-created starting point.
	if _, err := db.Exec(`INSERT OR IGNORE INTO play_campaign_party_locations(campaign_id, location_id) SELECT campaign_id, id FROM play_campaign_locations AS location WHERE rowid = (SELECT MIN(first_location.rowid) FROM play_campaign_locations AS first_location WHERE first_location.campaign_id = location.campaign_id)`); err != nil {
		db.Close()
		return err
	}
	if err := migratePlayCampaignStatus(db); err != nil {
		db.Close()
		return err
	}
	if err := migratePlayCampaignMemberOrder(db); err != nil {
		db.Close()
		return err
	}
	if err := migratePlayCampaignMemberHP(db); err != nil {
		db.Close()
		return err
	}
	if err := migratePlayCampaignMemberDeathSaves(db); err != nil {
		db.Close()
		return err
	}
	if err := migratePlayCampaignCharacterOwnership(db); err != nil {
		db.Close()
		return err
	}
	if err := migratePlayCampaignCharacterChoices(db); err != nil {
		db.Close()
		return err
	}
	if err := migratePlayCampaignCharacterProgression(db); err != nil {
		db.Close()
		return err
	}
	if err := migratePlayCampaignCharacterAbilities(db); err != nil {
		db.Close()
		return err
	}
	if err := migratePlayCampaignTurnNumber(db); err != nil {
		db.Close()
		return err
	}
	if err := migratePlayCampaignTurnNudgeCount(db); err != nil {
		db.Close()
		return err
	}
	if err := migratePlayCampaignEncounterTurn(db); err != nil {
		db.Close()
		return err
	}
	if err := migratePlayCampaignEncounterStatus(db); err != nil {
		db.Close()
		return err
	}
	if _, err := db.Exec(`DELETE FROM schema_metadata; INSERT INTO schema_metadata(version) VALUES (?)`, schemaVersion); err != nil {
		db.Close()
		return err
	}
	storage.Lock()
	storage.db = db
	storage.initialized = true
	storage.Unlock()
	return loadDurableData()
}

// migratePlayCampaignMemberHP gives characters created before rest turns a
// deterministic, fully-rested starting state.
func migratePlayCampaignMemberHP(db *sql.DB) error {
	columns, err := db.Query(`PRAGMA table_info(play_campaign_members)`)
	if err != nil {
		return err
	}
	defer columns.Close()
	hasCurrent, hasMax := false, false
	for columns.Next() {
		var cid int
		var name, columnType string
		var notNull int
		var defaultValue any
		var primaryKey int
		if err := columns.Scan(&cid, &name, &columnType, &notNull, &defaultValue, &primaryKey); err != nil {
			return err
		}
		switch name {
		case "hp_current":
			hasCurrent = true
		case "hp_max":
			hasMax = true
		}
	}
	if err := columns.Err(); err != nil {
		return err
	}
	if !hasCurrent {
		if _, err := db.Exec(`ALTER TABLE play_campaign_members ADD COLUMN hp_current INTEGER NOT NULL DEFAULT 20 CHECK(hp_current >= 0)`); err != nil {
			return err
		}
	}
	if !hasMax {
		if _, err := db.Exec(`ALTER TABLE play_campaign_members ADD COLUMN hp_max INTEGER NOT NULL DEFAULT 20 CHECK(hp_max > 0)`); err != nil {
			return err
		}
	}
	return nil
}

// migratePlayCampaignMemberDeathSaves adds the durable 0-HP state used by
// death saves, preserving the invariant that a living character at zero HP is
// unconscious.
func migratePlayCampaignMemberDeathSaves(db *sql.DB) error {
	for _, column := range []struct {
		name       string
		definition string
	}{
		{"death_save_successes", "INTEGER NOT NULL DEFAULT 0 CHECK(death_save_successes BETWEEN 0 AND 3)"},
		{"death_save_failures", "INTEGER NOT NULL DEFAULT 0 CHECK(death_save_failures BETWEEN 0 AND 3)"},
		{"status", "TEXT NOT NULL DEFAULT 'conscious' CHECK(status IN ('conscious', 'unconscious', 'stable', 'dead'))"},
	} {
		hasColumn, err := tableHasColumn(db, "play_campaign_members", column.name)
		if err != nil {
			return err
		}
		if !hasColumn {
			if _, err := db.Exec("ALTER TABLE play_campaign_members ADD COLUMN " + column.name + " " + column.definition); err != nil {
				return err
			}
		}
	}
	_, err := db.Exec(`UPDATE play_campaign_members SET status = 'unconscious' WHERE hp_current = 0 AND status = 'conscious'`)
	return err
}

// migratePlayCampaignCharacterOwnership makes the formerly implicit member to
// character relationship explicit. Existing characters retain their original
// member as owner, while an empty value remains available for imported,
// unclaimed characters.
func migratePlayCampaignCharacterOwnership(db *sql.DB) error {
	hasColumn, err := tableHasColumn(db, "play_campaign_members", "character_owner")
	if err != nil {
		return err
	}
	if !hasColumn {
		if _, err := db.Exec(`ALTER TABLE play_campaign_members ADD COLUMN character_owner TEXT NOT NULL DEFAULT ''`); err != nil {
			return err
		}
		// Only legacy rows receive the former implicit assignment. An empty
		// value in an ownership-aware database is a durable unclaimed state.
		_, err = db.Exec(`UPDATE play_campaign_members SET character_owner = username WHERE character_owner = ''`)
		return err
	}
	return nil
}

// migratePlayCampaignCharacterChoices retains the choices made by the
// character build endpoint without changing existing campaign members.
func migratePlayCampaignCharacterChoices(db *sql.DB) error {
	for _, column := range []struct {
		name       string
		definition string
	}{
		{"race", "TEXT NOT NULL DEFAULT ''"},
		{"background", "TEXT NOT NULL DEFAULT ''"},
	} {
		hasColumn, err := tableHasColumn(db, "play_campaign_members", column.name)
		if err != nil {
			return err
		}
		if !hasColumn {
			if _, err := db.Exec("ALTER TABLE play_campaign_members ADD COLUMN " + column.name + " " + column.definition); err != nil {
				return err
			}
		}
	}
	return nil
}

// migratePlayCampaignCharacterProgression adds the durable values needed for
// deterministic level advancement. Existing characters retain their current
// level-one state and use a neutral Constitution modifier until rebuilt.
func migratePlayCampaignCharacterProgression(db *sql.DB) error {
	for _, column := range []struct {
		name       string
		definition string
	}{
		{"level", "INTEGER NOT NULL DEFAULT 1 CHECK(level BETWEEN 1 AND 20)"},
		{"con_modifier", "INTEGER NOT NULL DEFAULT 0"},
	} {
		hasColumn, err := tableHasColumn(db, "play_campaign_members", column.name)
		if err != nil {
			return err
		}
		if !hasColumn {
			if _, err := db.Exec("ALTER TABLE play_campaign_members ADD COLUMN " + column.name + " " + column.definition); err != nil {
				return err
			}
		}
	}
	return nil
}

// migratePlayCampaignCharacterAbilities persists every ability score so skill
// checks remain correct after a process restart. Characters from before this
// feature receive a neutral score until they are rebuilt.
func migratePlayCampaignCharacterAbilities(db *sql.DB) error {
	for _, column := range []string{"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"} {
		hasColumn, err := tableHasColumn(db, "play_campaign_members", column)
		if err != nil {
			return err
		}
		if !hasColumn {
			if _, err := db.Exec("ALTER TABLE play_campaign_members ADD COLUMN " + column + " INTEGER NOT NULL DEFAULT 10 CHECK(" + column + " BETWEEN 1 AND 30)"); err != nil {
				return err
			}
		}
	}
	return nil
}

// migratePlayCampaignStatus updates databases created before play campaigns
// could become active or enter combat. SQLite cannot alter a CHECK constraint
// in place, so the two related tables are rebuilt together while preserving all rows.
func migratePlayCampaignStatus(db *sql.DB) error {
	var definition string
	if err := db.QueryRow(`SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'play_campaigns'`).Scan(&definition); err != nil {
		return err
	}
	if strings.Contains(definition, "'combat'") {
		return nil
	}
	joinOrder, err := tableHasColumn(db, "play_campaign_members", "join_order")
	if err != nil {
		return err
	}
	hpCurrent, err := tableHasColumn(db, "play_campaign_members", "hp_current")
	if err != nil {
		return err
	}
	hpMax, err := tableHasColumn(db, "play_campaign_members", "hp_max")
	if err != nil {
		return err
	}
	joinOrderValue, hpCurrentValue, hpMaxValue := "0", "20", "20"
	if joinOrder {
		joinOrderValue = "join_order"
	}
	if hpCurrent {
		hpCurrentValue = "hp_current"
	}
	if hpMax {
		hpMaxValue = "hp_max"
	}
	if _, err := db.Exec(`PRAGMA foreign_keys = OFF`); err != nil {
		return err
	}
	defer db.Exec(`PRAGMA foreign_keys = ON`)
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	memberCopy := `INSERT INTO play_campaign_members_new(campaign_id, username, character_id, name, class, join_order, hp_current, hp_max) SELECT campaign_id, username, character_id, name, class, ` + joinOrderValue + `, ` + hpCurrentValue + `, ` + hpMaxValue + ` FROM play_campaign_members`
	for _, statement := range []string{
		`CREATE TABLE play_campaigns_new (id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('lobby', 'active', 'combat')), max_players INTEGER NOT NULL CHECK(max_players > 0))`,
		`INSERT INTO play_campaigns_new(id, name, owner, status, max_players) SELECT id, name, owner, status, max_players FROM play_campaigns`,
		`CREATE TABLE play_campaign_members_new (campaign_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, class TEXT NOT NULL, join_order INTEGER NOT NULL DEFAULT 0, hp_current INTEGER NOT NULL DEFAULT 20 CHECK(hp_current >= 0), hp_max INTEGER NOT NULL DEFAULT 20 CHECK(hp_max > 0), PRIMARY KEY(campaign_id, username), FOREIGN KEY(campaign_id) REFERENCES play_campaigns_new(id) ON DELETE CASCADE)`,
		memberCopy,
		`DROP TABLE play_campaign_members`,
		`DROP TABLE play_campaigns`,
		`ALTER TABLE play_campaigns_new RENAME TO play_campaigns`,
		`ALTER TABLE play_campaign_members_new RENAME TO play_campaign_members`,
	} {
		if _, err := tx.Exec(statement); err != nil {
			return err
		}
	}
	return tx.Commit()
}

// migratePlayCampaignMemberOrder adds the stable join sequence used by the
// exploration turn queue. Existing rows retain zero and use username as their
// deterministic compatibility order.
func migratePlayCampaignMemberOrder(db *sql.DB) error {
	hasColumn, err := tableHasColumn(db, "play_campaign_members", "join_order")
	if err != nil {
		return err
	}
	if hasColumn {
		return nil
	}
	_, err = db.Exec(`ALTER TABLE play_campaign_members ADD COLUMN join_order INTEGER NOT NULL DEFAULT 0`)
	return err
}

func migratePlayCampaignTurnNumber(db *sql.DB) error {
	hasColumn, err := tableHasColumn(db, "play_campaign_turns", "turn_number")
	if err != nil {
		return err
	}
	if hasColumn {
		return nil
	}
	_, err = db.Exec(`ALTER TABLE play_campaign_turns ADD COLUMN turn_number INTEGER NOT NULL DEFAULT 1`)
	return err
}

// migratePlayCampaignTurnNudgeCount retains the nudge sequence when opening
// a database created before deterministic turn reminders were introduced.
func migratePlayCampaignTurnNudgeCount(db *sql.DB) error {
	hasColumn, err := tableHasColumn(db, "play_campaign_turns", "nudge_count")
	if err != nil {
		return err
	}
	if hasColumn {
		return nil
	}
	_, err = db.Exec(`ALTER TABLE play_campaign_turns ADD COLUMN nudge_count INTEGER NOT NULL DEFAULT 0`)
	return err
}

// migratePlayCampaignEncounterTurn adds the combat-local cursor to encounters
// created before combat turns were introduced. Existing encounters begin at
// the first position of their deterministic initiative order.
func migratePlayCampaignEncounterTurn(db *sql.DB) error {
	hasRound, err := tableHasColumn(db, "play_campaign_encounters", "round")
	if err != nil {
		return err
	}
	if !hasRound {
		if _, err := db.Exec(`ALTER TABLE play_campaign_encounters ADD COLUMN round INTEGER NOT NULL DEFAULT 1 CHECK(round > 0)`); err != nil {
			return err
		}
	}
	hasTurnIndex, err := tableHasColumn(db, "play_campaign_encounters", "turn_index")
	if err != nil {
		return err
	}
	if hasTurnIndex {
		return nil
	}
	_, err = db.Exec(`ALTER TABLE play_campaign_encounters ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0 CHECK(turn_index >= 0)`)
	return err
}

// migratePlayCampaignEncounterStatus admits closed encounters while retaining
// all combat-local rows. SQLite cannot alter a CHECK constraint in place.
func migratePlayCampaignEncounterStatus(db *sql.DB) error {
	var definition string
	if err := db.QueryRow(`SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'play_campaign_encounters'`).Scan(&definition); err != nil {
		return err
	}
	if strings.Contains(definition, "'closed'") {
		return nil
	}
	if _, err := db.Exec(`PRAGMA foreign_keys = OFF`); err != nil {
		return err
	}
	defer db.Exec(`PRAGMA foreign_keys = ON`)
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	for _, statement := range []string{
		`CREATE TABLE play_campaign_encounters_new (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active', 'closed')), round INTEGER NOT NULL DEFAULT 1 CHECK(round > 0), turn_index INTEGER NOT NULL DEFAULT 0 CHECK(turn_index >= 0), PRIMARY KEY(campaign_id, id), FOREIGN KEY(campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)`,
		`INSERT INTO play_campaign_encounters_new(campaign_id, id, name, status, round, turn_index) SELECT campaign_id, id, name, status, round, turn_index FROM play_campaign_encounters`,
		`DROP TABLE play_campaign_encounters`,
		`ALTER TABLE play_campaign_encounters_new RENAME TO play_campaign_encounters`,
	} {
		if _, err := tx.Exec(statement); err != nil {
			return err
		}
	}
	return tx.Commit()
}

// tableHasColumn centralizes the compatibility checks used by additive schema
// migrations. Table names are internal constants, never request input.
func tableHasColumn(db *sql.DB, table, wantedColumn string) (bool, error) {
	rows, err := db.Query(`PRAGMA table_info(` + table + `)`)
	if err != nil {
		return false, err
	}
	defer rows.Close()
	for rows.Next() {
		var cid int
		var name, columnType string
		var notNull, primaryKey int
		var defaultValue any
		if err := rows.Scan(&cid, &name, &columnType, &notNull, &defaultValue, &primaryKey); err != nil {
			return false, err
		}
		if name == wantedColumn {
			return true, rows.Err()
		}
	}
	if err := rows.Err(); err != nil {
		return false, err
	}
	return false, nil
}

func loadDurableData() error {
	storage.Lock()
	db := storage.db
	storage.Unlock()
	loadedUsers := make(map[string]user)
	rows, err := db.Query(`SELECT username, role, password_hash, password_salt FROM users`)
	if err != nil {
		return err
	}
	for rows.Next() {
		var account user
		if err := rows.Scan(&account.Username, &account.Role, &account.PasswordHash, &account.PasswordSalt); err != nil {
			rows.Close()
			return err
		}
		loadedUsers[account.Username] = account
	}
	if err := rows.Close(); err != nil {
		return err
	}
	loadedSessions := make(map[string]*combatSession)
	rows, err = db.Query(`SELECT id, round, turn_index FROM combat_sessions`)
	if err != nil {
		return err
	}
	for rows.Next() {
		s := &combatSession{Conditions: make(map[string][]condition)}
		if err := rows.Scan(&s.ID, &s.Round, &s.TurnIndex); err != nil {
			rows.Close()
			return err
		}
		combatRows, err := db.Query(`SELECT name, score, dex FROM combatants WHERE session_id = ? ORDER BY position`, s.ID)
		if err != nil {
			rows.Close()
			return err
		}
		for combatRows.Next() {
			var c combatant
			if err := combatRows.Scan(&c.Name, &c.Score, &c.dex); err != nil {
				combatRows.Close()
				rows.Close()
				return err
			}
			s.Order = append(s.Order, c)
		}
		if err := combatRows.Close(); err != nil {
			rows.Close()
			return err
		}
		conditionRows, err := db.Query(`SELECT target, condition_name, remaining_rounds FROM combat_conditions WHERE session_id = ? ORDER BY target, position`, s.ID)
		if err != nil {
			rows.Close()
			return err
		}
		for conditionRows.Next() {
			var target string
			var c condition
			if err := conditionRows.Scan(&target, &c.Condition, &c.RemainingRounds); err != nil {
				conditionRows.Close()
				rows.Close()
				return err
			}
			s.Conditions[target] = append(s.Conditions[target], c)
		}
		if err := conditionRows.Close(); err != nil {
			rows.Close()
			return err
		}
		loadedSessions[s.ID] = s
	}
	if err := rows.Close(); err != nil {
		return err
	}
	users.Lock()
	users.users = loadedUsers
	users.Unlock()
	sessions.Lock()
	sessions.sessions = loadedSessions
	sessions.Unlock()
	return nil
}

func persistUser(account user) error {
	db := storage.db
	if db == nil {
		return nil
	}
	_, err := db.Exec(`INSERT INTO users(username, role, password_hash, password_salt) VALUES (?, ?, ?, ?)`, account.Username, account.Role, account.PasswordHash, account.PasswordSalt)
	return err
}

func persistSession(s *combatSession) error {
	db := storage.db
	if db == nil {
		return nil
	}
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	fail := func(err error) error { _ = tx.Rollback(); return err }
	for _, deletion := range []struct{ query, id string }{
		{`DELETE FROM combat_conditions WHERE session_id = ?`, s.ID},
		{`DELETE FROM combatants WHERE session_id = ?`, s.ID},
		{`DELETE FROM combat_sessions WHERE id = ?`, s.ID},
	} {
		if _, err = tx.Exec(deletion.query, deletion.id); err != nil {
			return fail(err)
		}
	}
	if _, err = tx.Exec(`INSERT INTO combat_sessions(id, round, turn_index) VALUES (?, ?, ?)`, s.ID, s.Round, s.TurnIndex); err != nil {
		return fail(err)
	}
	for i, c := range s.Order {
		if _, err = tx.Exec(`INSERT INTO combatants(session_id, position, name, score, dex) VALUES (?, ?, ?, ?, ?)`, s.ID, i, c.Name, c.Score, c.dex); err != nil {
			return fail(err)
		}
	}
	for target, conditions := range s.Conditions {
		for i, c := range conditions {
			if _, err = tx.Exec(`INSERT INTO combat_conditions(session_id, target, position, condition_name, remaining_rounds) VALUES (?, ?, ?, ?, ?)`, s.ID, target, i, c.Condition, c.RemainingRounds); err != nil {
				return fail(err)
			}
		}
	}
	return tx.Commit()
}

type monster struct {
	Slug       string   `json:"slug"`
	Name       string   `json:"name"`
	CR         string   `json:"cr"`
	ArmorClass int      `json:"armor_class"`
	HitPoints  int      `json:"hit_points"`
	Tags       []string `json:"tags"`
}

type item struct {
	Slug   string `json:"slug"`
	Name   string `json:"name"`
	Type   string `json:"type"`
	Rarity string `json:"rarity"`
	CostGP int    `json:"cost_gp"`
}

func createMonster(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Slug       string   `json:"slug"`
		Name       string   `json:"name"`
		CR         string   `json:"cr"`
		ArmorClass *int     `json:"armor_class"`
		HitPoints  *int     `json:"hit_points"`
		Tags       []string `json:"tags"`
	}
	if !decodeJSON(r, &request) || !validCompendiumSlug(request.Slug) || !validCompendiumText(request.Name) || !validCompendiumText(request.CR) || request.ArmorClass == nil || *request.ArmorClass < 0 || request.HitPoints == nil || *request.HitPoints < 0 || request.Tags == nil {
		badRequest(w, "invalid monster")
		return
	}
	for _, tag := range request.Tags {
		if !validCompendiumText(tag) {
			badRequest(w, "invalid monster")
			return
		}
	}

	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save monster"})
		return
	}
	fail := func() {
		_ = tx.Rollback()
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save monster"})
	}
	var exists int
	err = tx.QueryRow(`SELECT 1 FROM monsters WHERE slug = ?`, request.Slug).Scan(&exists)
	if err == nil {
		_ = tx.Rollback()
		writeJSON(w, http.StatusConflict, map[string]string{"error": "monster slug already exists"})
		return
	}
	if !errors.Is(err, sql.ErrNoRows) {
		fail()
		return
	}
	if _, err = tx.Exec(`INSERT INTO monsters(slug, name, cr, armor_class, hit_points) VALUES (?, ?, ?, ?, ?)`, request.Slug, request.Name, request.CR, *request.ArmorClass, *request.HitPoints); err != nil {
		if isUniqueViolation(err) {
			_ = tx.Rollback()
			writeJSON(w, http.StatusConflict, map[string]string{"error": "monster slug already exists"})
			return
		}
		fail()
		return
	}
	for position, tag := range request.Tags {
		if _, err = tx.Exec(`INSERT INTO monster_tags(monster_slug, position, tag) VALUES (?, ?, ?)`, request.Slug, position, tag); err != nil {
			fail()
			return
		}
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save monster"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		Slug       string `json:"slug"`
		Name       string `json:"name"`
		CR         string `json:"cr"`
		ArmorClass int    `json:"armor_class"`
		HitPoints  int    `json:"hit_points"`
	}{request.Slug, request.Name, request.CR, *request.ArmorClass, *request.HitPoints})
}

func getMonster(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")
	if !validCompendiumSlug(slug) {
		notFound(w, "unknown monster")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	var result monster
	if err := db.QueryRow(`SELECT slug, name, cr, armor_class, hit_points FROM monsters WHERE slug = ?`, slug).Scan(&result.Slug, &result.Name, &result.CR, &result.ArmorClass, &result.HitPoints); errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown monster")
		return
	} else if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read monster"})
		return
	}
	result.Tags = make([]string, 0)
	rows, err := db.Query(`SELECT tag FROM monster_tags WHERE monster_slug = ? ORDER BY position`, slug)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read monster"})
		return
	}
	defer rows.Close()
	for rows.Next() {
		var tag string
		if err := rows.Scan(&tag); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read monster"})
			return
		}
		result.Tags = append(result.Tags, tag)
	}
	if err := rows.Err(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read monster"})
		return
	}
	writeJSON(w, http.StatusOK, result)
}

func createItem(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Slug   string `json:"slug"`
		Name   string `json:"name"`
		Type   string `json:"type"`
		Rarity string `json:"rarity"`
		CostGP *int   `json:"cost_gp"`
	}
	if !decodeJSON(r, &request) || !validCompendiumSlug(request.Slug) || !validCompendiumText(request.Name) || !validCompendiumText(request.Type) || !validCompendiumText(request.Rarity) || request.CostGP == nil || *request.CostGP < 0 {
		badRequest(w, "invalid item")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	var exists int
	err := db.QueryRow(`SELECT 1 FROM items WHERE slug = ?`, request.Slug).Scan(&exists)
	if err == nil {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "item slug already exists"})
		return
	}
	if !errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save item"})
		return
	}
	result := item{Slug: request.Slug, Name: request.Name, Type: request.Type, Rarity: request.Rarity, CostGP: *request.CostGP}
	if _, err := db.Exec(`INSERT INTO items(slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)`, result.Slug, result.Name, result.Type, result.Rarity, result.CostGP); err != nil {
		if isUniqueViolation(err) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "item slug already exists"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save item"})
		return
	}
	writeJSON(w, http.StatusCreated, result)
}

func getItem(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")
	if !validCompendiumSlug(slug) {
		notFound(w, "unknown item")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	var result item
	err := db.QueryRow(`SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?`, slug).Scan(&result.Slug, &result.Name, &result.Type, &result.Rarity, &result.CostGP)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown item")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read item"})
		return
	}
	writeJSON(w, http.StatusOK, result)
}

type campaignCharacter struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	Level int    `json:"level"`
	Class string `json:"class"`
}

type faction struct {
	ID     string `json:"id"`
	Name   string `json:"name"`
	Stance string `json:"stance"`
}

type npc struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	FactionID   string `json:"faction_id"`
	Disposition int    `json:"disposition"`
}

func validDisposition(disposition int) bool {
	return disposition >= -2 && disposition <= 2
}

type quest struct {
	ID         string   `json:"id"`
	Title      string   `json:"title"`
	Status     string   `json:"status"`
	Milestones []string `json:"milestones"`
}

func validQuestStatus(status string) bool {
	return status == "active" || status == "completed" || status == "blocked"
}

func createQuest(w http.ResponseWriter, r *http.Request) {
	var request quest
	if !decodeJSON(r, &request) || !validCampaignText(request.ID) || !validCampaignText(request.Title) || !validQuestStatus(request.Status) || len(request.Milestones) == 0 {
		badRequest(w, "invalid quest")
		return
	}
	seen := make(map[string]bool, len(request.Milestones))
	for _, milestone := range request.Milestones {
		if !validCampaignText(milestone) || seen[milestone] {
			badRequest(w, "invalid quest")
			return
		}
		seen[milestone] = true
	}
	campaignID := r.PathValue("id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !campaignExists(db, campaignID) {
		notFound(w, "unknown campaign")
		return
	}
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save quest"})
		return
	}
	defer tx.Rollback()
	if _, err = tx.Exec(`INSERT INTO quests(campaign_id, id, title, status) VALUES (?, ?, ?, ?)`, campaignID, request.ID, request.Title, request.Status); err != nil {
		if isUniqueViolation(err) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "quest id already exists"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save quest"})
		return
	}
	for _, milestone := range request.Milestones {
		if _, err = tx.Exec(`INSERT INTO quest_milestones(campaign_id, quest_id, name) VALUES (?, ?, ?)`, campaignID, request.ID, milestone); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save quest"})
			return
		}
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save quest"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		ID              string `json:"id"`
		Title           string `json:"title"`
		Status          string `json:"status"`
		MilestonesTotal int    `json:"milestones_total"`
		MilestonesDone  int    `json:"milestones_done"`
	}{request.ID, request.Title, request.Status, len(request.Milestones), 0})
}

func updateQuestProgress(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Completed []string `json:"completed"`
	}
	if !decodeJSON(r, &request) || len(request.Completed) == 0 {
		badRequest(w, "invalid progress")
		return
	}
	seen := make(map[string]bool, len(request.Completed))
	for _, milestone := range request.Completed {
		if !validCampaignText(milestone) || seen[milestone] {
			badRequest(w, "invalid progress")
			return
		}
		seen[milestone] = true
	}
	campaignID, questID := r.PathValue("id"), r.PathValue("quest_id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	var status string
	err := db.QueryRow(`SELECT status FROM quests WHERE campaign_id = ? AND id = ?`, campaignID, questID).Scan(&status)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown quest")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to update quest"})
		return
	}
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to update quest"})
		return
	}
	defer tx.Rollback()
	for _, milestone := range request.Completed {
		result, updateErr := tx.Exec(`UPDATE quest_milestones SET completed = 1 WHERE campaign_id = ? AND quest_id = ? AND name = ?`, campaignID, questID, milestone)
		if updateErr != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to update quest"})
			return
		}
		changed, changeErr := result.RowsAffected()
		if changeErr != nil || changed != 1 {
			badRequest(w, "unknown milestone")
			return
		}
	}
	var total, done int
	if err = tx.QueryRow(`SELECT COUNT(*), COALESCE(SUM(completed), 0) FROM quest_milestones WHERE campaign_id = ? AND quest_id = ?`, campaignID, questID).Scan(&total, &done); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to update quest"})
		return
	}
	if done == total && status == "active" {
		status = "completed"
		if _, err = tx.Exec(`UPDATE quests SET status = ? WHERE campaign_id = ? AND id = ?`, status, campaignID, questID); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to update quest"})
			return
		}
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to update quest"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		ID              string `json:"id"`
		Status          string `json:"status"`
		MilestonesTotal int    `json:"milestones_total"`
		MilestonesDone  int    `json:"milestones_done"`
	}{questID, status, total, done})
}

func getQuestSummary(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !campaignExists(db, campaignID) {
		notFound(w, "unknown campaign")
		return
	}
	var active, completed, blocked int
	if err := db.QueryRow(`SELECT COALESCE(SUM(status = 'active'), 0), COALESCE(SUM(status = 'completed'), 0), COALESCE(SUM(status = 'blocked'), 0) FROM quests WHERE campaign_id = ?`, campaignID).Scan(&active, &completed, &blocked); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read quests"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		CampaignID string `json:"campaign_id"`
		Active     int    `json:"active"`
		Completed  int    `json:"completed"`
		Blocked    int    `json:"blocked"`
	}{campaignID, active, completed, blocked})
}

type sessionScheduleRequest struct {
	ID              string   `json:"id"`
	StartsAt        string   `json:"starts_at"`
	DurationMinutes *int     `json:"duration_minutes"`
	Agenda          []string `json:"agenda"`
}

func validSessionSchedule(request sessionScheduleRequest) (time.Time, bool) {
	if !validCampaignText(request.ID) || request.DurationMinutes == nil || *request.DurationMinutes <= 0 {
		return time.Time{}, false
	}
	startsAt, err := time.Parse(time.RFC3339, request.StartsAt)
	if err != nil {
		return time.Time{}, false
	}
	for _, item := range request.Agenda {
		if !validCampaignText(item) {
			return time.Time{}, false
		}
	}
	return startsAt.UTC(), true
}

func scheduleSession(w http.ResponseWriter, r *http.Request) {
	var request sessionScheduleRequest
	startsAt, valid := time.Time{}, false
	if decodeJSON(r, &request) {
		startsAt, valid = validSessionSchedule(request)
	}
	if !valid {
		badRequest(w, "invalid session")
		return
	}
	campaignID := r.PathValue("id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !campaignExists(db, campaignID) {
		notFound(w, "unknown campaign")
		return
	}
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save session"})
		return
	}
	defer tx.Rollback()
	if _, err = tx.Exec(`INSERT INTO campaign_sessions(campaign_id, id, starts_at, duration_minutes) VALUES (?, ?, ?, ?)`, campaignID, request.ID, startsAt.Format(time.RFC3339), *request.DurationMinutes); err != nil {
		if isUniqueViolation(err) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "session id already exists"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save session"})
		return
	}
	for position, item := range request.Agenda {
		if _, err = tx.Exec(`INSERT INTO session_agenda(campaign_id, session_id, position, item) VALUES (?, ?, ?, ?)`, campaignID, request.ID, position, item); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save session"})
			return
		}
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save session"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		ID              string `json:"id"`
		StartsAt        string `json:"starts_at"`
		DurationMinutes int    `json:"duration_minutes"`
		AgendaCount     int    `json:"agenda_count"`
	}{request.ID, startsAt.Format(time.RFC3339), *request.DurationMinutes, len(request.Agenda)})
}

type attendanceRequest struct {
	Present *[]string `json:"present"`
	Absent  *[]string `json:"absent"`
}

func validAttendance(request attendanceRequest) bool {
	if request.Present == nil || request.Absent == nil {
		return false
	}
	seen := make(map[string]bool, len(*request.Present)+len(*request.Absent))
	for _, characterID := range append(*request.Present, *request.Absent...) {
		if !validCampaignText(characterID) || seen[characterID] {
			return false
		}
		seen[characterID] = true
	}
	return true
}

func recordAttendance(w http.ResponseWriter, r *http.Request) {
	var request attendanceRequest
	if !decodeJSON(r, &request) || !validAttendance(request) {
		badRequest(w, "invalid attendance")
		return
	}
	campaignID, sessionID := r.PathValue("id"), r.PathValue("session_id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !campaignExists(db, campaignID) {
		notFound(w, "unknown campaign")
		return
	}
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to record attendance"})
		return
	}
	defer tx.Rollback()
	var found int
	if err = tx.QueryRow(`SELECT 1 FROM campaign_sessions WHERE campaign_id = ? AND id = ?`, campaignID, sessionID).Scan(&found); errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown session")
		return
	} else if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to record attendance"})
		return
	}
	for _, characterID := range append(*request.Present, *request.Absent...) {
		if err = tx.QueryRow(`SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?`, campaignID, characterID).Scan(&found); errors.Is(err, sql.ErrNoRows) {
			notFound(w, "unknown character")
			return
		} else if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to record attendance"})
			return
		}
	}
	if _, err = tx.Exec(`DELETE FROM session_attendance WHERE campaign_id = ? AND session_id = ?`, campaignID, sessionID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to record attendance"})
		return
	}
	for _, entry := range []struct {
		characters []string
		status     string
	}{{*request.Present, "present"}, {*request.Absent, "absent"}} {
		for _, characterID := range entry.characters {
			if _, err = tx.Exec(`INSERT INTO session_attendance(campaign_id, session_id, character_id, status) VALUES (?, ?, ?, ?)`, campaignID, sessionID, characterID, entry.status); err != nil {
				writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to record attendance"})
				return
			}
		}
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to record attendance"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		SessionID    string `json:"session_id"`
		PresentCount int    `json:"present_count"`
		AbsentCount  int    `json:"absent_count"`
	}{sessionID, len(*request.Present), len(*request.Absent)})
}

func nextSession(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !campaignExists(db, campaignID) {
		notFound(w, "unknown campaign")
		return
	}
	var result struct {
		ID          string `json:"id"`
		StartsAt    string `json:"starts_at"`
		AgendaCount int    `json:"agenda_count"`
	}
	err := db.QueryRow(`SELECT s.id, s.starts_at, COUNT(a.position) FROM campaign_sessions s LEFT JOIN session_agenda a ON a.campaign_id = s.campaign_id AND a.session_id = s.id WHERE s.campaign_id = ? GROUP BY s.campaign_id, s.id ORDER BY s.starts_at, s.id LIMIT 1`, campaignID).Scan(&result.ID, &result.StartsAt, &result.AgendaCount)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "no scheduled sessions")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read sessions"})
		return
	}
	writeJSON(w, http.StatusOK, result)
}

func createCampaign(w http.ResponseWriter, r *http.Request) {
	var request struct {
		ID   string `json:"id"`
		Name string `json:"name"`
		DM   string `json:"dm"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.ID) || !validCampaignText(request.Name) || !validCampaignText(request.DM) {
		badRequest(w, "invalid campaign")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if _, err := db.Exec(`INSERT INTO campaigns(id, name, dm) VALUES (?, ?, ?)`, request.ID, request.Name, request.DM); err != nil {
		if isUniqueViolation(err) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "campaign id already exists"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save campaign"})
		return
	}
	writeJSON(w, http.StatusCreated, request)
}

func addCampaignCharacter(w http.ResponseWriter, r *http.Request) {
	var request campaignCharacter
	if !decodeJSON(r, &request) || !validCampaignText(request.ID) || !validCampaignText(request.Name) || !validLevel(request.Level) || !validCampaignText(request.Class) {
		badRequest(w, "invalid character")
		return
	}
	campaignID := r.PathValue("id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !campaignExists(db, campaignID) {
		notFound(w, "unknown campaign")
		return
	}
	if _, err := db.Exec(`INSERT INTO campaign_characters(campaign_id, id, name, level, class) VALUES (?, ?, ?, ?, ?)`, campaignID, request.ID, request.Name, request.Level, request.Class); err != nil {
		if isUniqueViolation(err) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "character id already exists"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save character"})
		return
	}
	writeJSON(w, http.StatusCreated, request)
}

type inventoryItemRequest struct {
	ItemSlug string `json:"item_slug"`
	Quantity *int   `json:"quantity"`
	Owner    string `json:"owner"`
}

func validInventoryRequest(request inventoryItemRequest) bool {
	return validCompendiumSlug(request.ItemSlug) && request.Quantity != nil && *request.Quantity > 0 && request.Owner == "party"
}

func addInventoryItem(w http.ResponseWriter, r *http.Request) {
	var request inventoryItemRequest
	if !decodeJSON(r, &request) || !validInventoryRequest(request) {
		badRequest(w, "invalid inventory item")
		return
	}
	campaignID := r.PathValue("id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !campaignExists(db, campaignID) {
		notFound(w, "unknown campaign")
		return
	}
	_, err := db.Exec(`INSERT INTO campaign_inventory(campaign_id, item_slug, quantity) VALUES (?, ?, ?) ON CONFLICT(campaign_id, item_slug) DO UPDATE SET quantity = quantity + excluded.quantity`, campaignID, request.ItemSlug, *request.Quantity)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save inventory item"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		ItemSlug string `json:"item_slug"`
		Quantity int    `json:"quantity"`
		Owner    string `json:"owner"`
	}{request.ItemSlug, *request.Quantity, request.Owner})
}

func assignEquipment(w http.ResponseWriter, r *http.Request) {
	var request struct {
		ItemSlug string `json:"item_slug"`
		Quantity *int   `json:"quantity"`
	}
	if !decodeJSON(r, &request) || !validCompendiumSlug(request.ItemSlug) || request.Quantity == nil || *request.Quantity <= 0 {
		badRequest(w, "invalid equipment assignment")
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("character_id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to assign equipment"})
		return
	}
	defer tx.Rollback()
	var found int
	if err = tx.QueryRow(`SELECT 1 FROM campaigns WHERE id = ?`, campaignID).Scan(&found); errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	} else if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to assign equipment"})
		return
	}
	if err = tx.QueryRow(`SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?`, campaignID, characterID).Scan(&found); errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown character")
		return
	} else if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to assign equipment"})
		return
	}
	result, err := tx.Exec(`UPDATE campaign_inventory SET quantity = quantity - ? WHERE campaign_id = ? AND item_slug = ? AND quantity >= ?`, *request.Quantity, campaignID, request.ItemSlug, *request.Quantity)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to assign equipment"})
		return
	}
	changed, err := result.RowsAffected()
	if err != nil || changed != 1 {
		badRequest(w, "insufficient inventory")
		return
	}
	if _, err = tx.Exec(`INSERT INTO character_equipment(campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_slug) DO UPDATE SET quantity = quantity + excluded.quantity`, campaignID, characterID, request.ItemSlug, *request.Quantity); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to assign equipment"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to assign equipment"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		CharacterID string `json:"character_id"`
		ItemSlug    string `json:"item_slug"`
		Quantity    int    `json:"quantity"`
	}{characterID, request.ItemSlug, *request.Quantity})
}

func getInventorySummary(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !campaignExists(db, campaignID) {
		notFound(w, "unknown campaign")
		return
	}
	var result struct {
		CampaignID              string `json:"campaign_id"`
		PartyItems              int    `json:"party_items"`
		AssignedItems           int    `json:"assigned_items"`
		HealingPotionsAvailable int    `json:"healing_potions_available"`
	}
	result.CampaignID = campaignID
	err := db.QueryRow(`SELECT (SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ? AND quantity > 0), (SELECT COUNT(*) FROM character_equipment WHERE campaign_id = ?), COALESCE((SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = 'healing-potion'), 0)`, campaignID, campaignID, campaignID).Scan(&result.PartyItems, &result.AssignedItems, &result.HealingPotionsAvailable)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read inventory"})
		return
	}
	writeJSON(w, http.StatusOK, result)
}

type craftingProjectRequest struct {
	ID           string `json:"id"`
	CharacterID  string `json:"character_id"`
	ItemSlug     string `json:"item_slug"`
	DaysRequired *int   `json:"days_required"`
	CostGP       *int   `json:"cost_gp"`
}

func validCraftingProjectRequest(request craftingProjectRequest) bool {
	return validCampaignText(request.ID) && validCampaignText(request.CharacterID) && validCompendiumSlug(request.ItemSlug) && request.DaysRequired != nil && *request.DaysRequired > 0 && request.CostGP != nil && *request.CostGP >= 0
}

func createCraftingProject(w http.ResponseWriter, r *http.Request) {
	var request craftingProjectRequest
	if !decodeJSON(r, &request) || !validCraftingProjectRequest(request) {
		badRequest(w, "invalid crafting project")
		return
	}
	campaignID := r.PathValue("id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !campaignExists(db, campaignID) {
		notFound(w, "unknown campaign")
		return
	}
	var found int
	if err := db.QueryRow(`SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?`, campaignID, request.CharacterID).Scan(&found); errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown character")
		return
	} else if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save crafting project"})
		return
	}
	if _, err := db.Exec(`INSERT INTO crafting_projects(campaign_id, id, character_id, item_slug, days_required, days_completed, cost_gp, status) VALUES (?, ?, ?, ?, ?, 0, ?, 'active')`, campaignID, request.ID, request.CharacterID, request.ItemSlug, *request.DaysRequired, *request.CostGP); err != nil {
		if isUniqueViolation(err) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "crafting project id already exists"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save crafting project"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		ID            string `json:"id"`
		CharacterID   string `json:"character_id"`
		ItemSlug      string `json:"item_slug"`
		DaysRequired  int    `json:"days_required"`
		DaysCompleted int    `json:"days_completed"`
		Status        string `json:"status"`
	}{request.ID, request.CharacterID, request.ItemSlug, *request.DaysRequired, 0, "active"})
}

func advanceCraftingProject(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Days *int `json:"days"`
	}
	if !decodeJSON(r, &request) || request.Days == nil || *request.Days <= 0 {
		badRequest(w, "invalid crafting progress")
		return
	}
	campaignID, projectID := r.PathValue("id"), r.PathValue("project_id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to advance crafting project"})
		return
	}
	defer tx.Rollback()
	var itemSlug, status string
	var completed, required int
	err = tx.QueryRow(`SELECT item_slug, days_completed, days_required, status FROM crafting_projects WHERE campaign_id = ? AND id = ?`, campaignID, projectID).Scan(&itemSlug, &completed, &required, &status)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown crafting project")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to advance crafting project"})
		return
	}
	if status == "complete" {
		badRequest(w, "crafting project is complete")
		return
	}
	if *request.Days >= required-completed {
		completed = required
	} else {
		completed += *request.Days
	}
	status = "active"
	if completed == required {
		status = "complete"
	}
	if _, err = tx.Exec(`UPDATE crafting_projects SET days_completed = ?, status = ? WHERE campaign_id = ? AND id = ?`, completed, status, campaignID, projectID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to advance crafting project"})
		return
	}
	if status == "complete" {
		if _, err = tx.Exec(`INSERT INTO campaign_inventory(campaign_id, item_slug, quantity) VALUES (?, ?, 1) ON CONFLICT(campaign_id, item_slug) DO UPDATE SET quantity = quantity + 1`, campaignID, itemSlug); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to advance crafting project"})
			return
		}
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to advance crafting project"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		ID            string `json:"id"`
		DaysCompleted int    `json:"days_completed"`
		Status        string `json:"status"`
	}{projectID, completed, status})
}

func addCampaignEvent(w http.ResponseWriter, r *http.Request) {
	var request struct {
		ID      string `json:"id"`
		Kind    string `json:"kind"`
		Summary string `json:"summary"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.ID) || !validCampaignText(request.Kind) || !validCampaignText(request.Summary) {
		badRequest(w, "invalid event")
		return
	}
	campaignID := r.PathValue("id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !campaignExists(db, campaignID) {
		notFound(w, "unknown campaign")
		return
	}
	if _, err := db.Exec(`INSERT INTO campaign_events(campaign_id, id, kind, summary) VALUES (?, ?, ?, ?)`, campaignID, request.ID, request.Kind, request.Summary); err != nil {
		if isUniqueViolation(err) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "event id already exists"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save event"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		ID   string `json:"id"`
		Kind string `json:"kind"`
	}{ID: request.ID, Kind: request.Kind})
}

func createFaction(w http.ResponseWriter, r *http.Request) {
	var request faction
	if !decodeJSON(r, &request) || !validCampaignText(request.ID) || !validCampaignText(request.Name) || !validCampaignText(request.Stance) {
		badRequest(w, "invalid faction")
		return
	}
	campaignID := r.PathValue("id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !campaignExists(db, campaignID) {
		notFound(w, "unknown campaign")
		return
	}
	if _, err := db.Exec(`INSERT INTO campaign_factions(campaign_id, id, name, stance) VALUES (?, ?, ?, ?)`, campaignID, request.ID, request.Name, request.Stance); err != nil {
		if isUniqueViolation(err) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "faction id already exists"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save faction"})
		return
	}
	writeJSON(w, http.StatusCreated, request)
}

func createNPC(w http.ResponseWriter, r *http.Request) {
	var request npc
	if !decodeJSON(r, &request) || !validCampaignText(request.ID) || !validCampaignText(request.Name) || !validCampaignText(request.FactionID) || !validDisposition(request.Disposition) {
		badRequest(w, "invalid npc")
		return
	}
	campaignID := r.PathValue("id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !campaignExists(db, campaignID) {
		notFound(w, "unknown campaign")
		return
	}
	var factionFound int
	if err := db.QueryRow(`SELECT 1 FROM campaign_factions WHERE campaign_id = ? AND id = ?`, campaignID, request.FactionID).Scan(&factionFound); errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown faction")
		return
	} else if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read faction"})
		return
	}
	if _, err := db.Exec(`INSERT INTO campaign_npcs(campaign_id, id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)`, campaignID, request.ID, request.Name, request.FactionID, request.Disposition); err != nil {
		if isUniqueViolation(err) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "npc id already exists"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save npc"})
		return
	}
	writeJSON(w, http.StatusCreated, request)
}

func getRelationships(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !campaignExists(db, campaignID) {
		notFound(w, "unknown campaign")
		return
	}
	var result struct {
		CampaignID   string `json:"campaign_id"`
		Factions     int    `json:"factions"`
		NPCs         int    `json:"npcs"`
		FriendlyNPCs int    `json:"friendly_npcs"`
	}
	result.CampaignID = campaignID
	if err := db.QueryRow(`SELECT (SELECT COUNT(*) FROM campaign_factions WHERE campaign_id = ?), COUNT(*), COALESCE(SUM(disposition > 0), 0) FROM campaign_npcs WHERE campaign_id = ?`, campaignID, campaignID).Scan(&result.Factions, &result.NPCs, &result.FriendlyNPCs); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read relationships"})
		return
	}
	writeJSON(w, http.StatusOK, result)
}

func getCampaignState(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	var state struct {
		ID         string              `json:"id"`
		Name       string              `json:"name"`
		DM         string              `json:"dm"`
		Characters []campaignCharacter `json:"characters"`
		LogCount   int                 `json:"log_count"`
	}
	if err := db.QueryRow(`SELECT id, name, dm FROM campaigns WHERE id = ?`, campaignID).Scan(&state.ID, &state.Name, &state.DM); errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	} else if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}
	state.Characters = make([]campaignCharacter, 0)
	rows, err := db.Query(`SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY id`, campaignID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}
	defer rows.Close()
	for rows.Next() {
		var character campaignCharacter
		if err := rows.Scan(&character.ID, &character.Name, &character.Level, &character.Class); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
			return
		}
		state.Characters = append(state.Characters, character)
	}
	if err := rows.Err(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}
	if err := db.QueryRow(`SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?`, campaignID).Scan(&state.LogCount); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}
	writeJSON(w, http.StatusOK, state)
}

func getCampaignAudit(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	var result struct {
		CampaignID string `json:"campaign_id"`
		Events     int    `json:"events"`
		Quests     int    `json:"quests"`
		NPCs       int    `json:"npcs"`
		Sessions   int    `json:"sessions"`
	}
	result.CampaignID = campaignID
	err := db.QueryRow(`SELECT
		(SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?),
		(SELECT COUNT(*) FROM quests WHERE campaign_id = ?),
		(SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?),
		(SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?)
		FROM campaigns WHERE id = ?`, campaignID, campaignID, campaignID, campaignID, campaignID).
		Scan(&result.Events, &result.Quests, &result.NPCs, &result.Sessions)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}
	writeJSON(w, http.StatusOK, result)
}

func exportCampaign(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	var result struct {
		CampaignID     string `json:"campaign_id"`
		Name           string `json:"name"`
		Characters     int    `json:"characters"`
		Quests         int    `json:"quests"`
		NPCs           int    `json:"npcs"`
		InventoryItems int    `json:"inventory_items"`
		Sessions       int    `json:"sessions"`
		SchemaVersion  int    `json:"schema_version"`
	}
	result.CampaignID = campaignID
	result.SchemaVersion = schemaVersion
	err := db.QueryRow(`SELECT c.name,
		(SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = c.id),
		(SELECT COUNT(*) FROM quests WHERE campaign_id = c.id),
		(SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = c.id),
		(SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = c.id AND quantity > 0),
		(SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = c.id)
		FROM campaigns c WHERE c.id = ?`, campaignID).
		Scan(&result.Name, &result.Characters, &result.Quests, &result.NPCs, &result.InventoryItems, &result.Sessions)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}
	writeJSON(w, http.StatusOK, result)
}

// campaignAnalytics contains the campaign state shared by the reporting
// endpoints. It deliberately uses stored rows only, so reports are stable
// across restarts and do not depend on the current clock.
type campaignAnalytics struct {
	HasDM          bool
	HasCharacters  bool
	HasNextSession bool
	HasActiveQuest bool
	OpenQuests     int
	FriendlyNPCs   int
	Scheduled      int
	InventoryItems int
}

func readCampaignAnalytics(db *sql.DB, campaignID string) (campaignAnalytics, error) {
	var result campaignAnalytics
	var dm string
	var characters int
	err := db.QueryRow(`SELECT c.dm,
		(SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = c.id),
		(SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = c.id),
		(SELECT COUNT(*) FROM quests WHERE campaign_id = c.id AND status = 'active'),
		(SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = c.id AND disposition > 0),
		(SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = c.id AND quantity > 0)
		FROM campaigns c WHERE c.id = ?`, campaignID).
		Scan(&dm, &characters, &result.Scheduled, &result.OpenQuests, &result.FriendlyNPCs, &result.InventoryItems)
	if err != nil {
		return result, err
	}
	result.HasDM = dm != ""
	result.HasCharacters = characters > 0
	result.HasNextSession = result.Scheduled > 0
	result.HasActiveQuest = result.OpenQuests > 0
	return result, nil
}

func campaignAnalyticsSummary(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	analytics, err := readCampaignAnalytics(db, campaignID)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read analytics"})
		return
	}
	readiness := 0
	if analytics.HasDM {
		readiness += 25
	}
	if analytics.HasCharacters {
		readiness += 25
	}
	if analytics.HasNextSession {
		readiness += 20
	}
	if analytics.HasActiveQuest {
		readiness += 15
	}
	writeJSON(w, http.StatusOK, struct {
		CampaignID     string `json:"campaign_id"`
		ReadinessScore int    `json:"readiness_score"`
		OpenQuests     int    `json:"open_quests"`
		FriendlyNPCs   int    `json:"friendly_npcs"`
		Scheduled      int    `json:"scheduled_sessions"`
		InventoryItems int    `json:"inventory_items"`
	}{campaignID, readiness, analytics.OpenQuests, analytics.FriendlyNPCs, analytics.Scheduled, analytics.InventoryItems})
}

func campaignRiskReport(w http.ResponseWriter, r *http.Request) {
	var request struct {
		IncludeZeroes *bool `json:"include_zeroes"`
	}
	if !decodeJSON(r, &request) || request.IncludeZeroes == nil {
		badRequest(w, "invalid risk report request")
		return
	}
	campaignID := r.PathValue("id")
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	analytics, err := readCampaignAnalytics(db, campaignID)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read analytics"})
		return
	}
	missing := make([]string, 0, 4)
	for _, signal := range []struct {
		name string
		set  bool
	}{{"dm", analytics.HasDM}, {"characters", analytics.HasCharacters}, {"next_session", analytics.HasNextSession}, {"active_quest", analytics.HasActiveQuest}} {
		if !signal.set {
			missing = append(missing, signal.name)
		}
	}
	riskLevel := "low"
	if len(missing) <= 2 && len(missing) > 0 {
		riskLevel = "medium"
	} else if len(missing) > 2 {
		riskLevel = "high"
	}
	writeJSON(w, http.StatusOK, struct {
		CampaignID string   `json:"campaign_id"`
		RiskLevel  string   `json:"risk_level"`
		Missing    []string `json:"missing"`
		Signals    struct {
			HasDM          bool `json:"has_dm"`
			HasCharacters  bool `json:"has_characters"`
			HasNextSession bool `json:"has_next_session"`
			HasActiveQuest bool `json:"has_active_quest"`
		} `json:"signals"`
	}{
		CampaignID: campaignID,
		RiskLevel:  riskLevel,
		Missing:    missing,
		Signals: struct {
			HasDM          bool `json:"has_dm"`
			HasCharacters  bool `json:"has_characters"`
			HasNextSession bool `json:"has_next_session"`
			HasActiveQuest bool `json:"has_active_quest"`
		}{analytics.HasDM, analytics.HasCharacters, analytics.HasNextSession, analytics.HasActiveQuest},
	})
}

func campaignExists(db *sql.DB, id string) bool {
	var found int
	return db.QueryRow(`SELECT 1 FROM campaigns WHERE id = ?`, id).Scan(&found) == nil
}

func encounterBuilder(w http.ResponseWriter, r *http.Request) {
	var request struct {
		CampaignID string `json:"campaign_id"`
		Party      []struct {
			Level int `json:"level"`
		} `json:"party"`
		MonsterSlugs []string `json:"monster_slugs"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.CampaignID) || len(request.Party) == 0 || len(request.MonsterSlugs) == 0 {
		badRequest(w, "invalid encounter request")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !campaignExists(db, request.CampaignID) {
		notFound(w, "unknown campaign")
		return
	}
	monsters := make([]encounterMonster, 0, len(request.MonsterSlugs))
	for _, slug := range request.MonsterSlugs {
		if !validCompendiumSlug(slug) {
			badRequest(w, "invalid monster")
			return
		}
		var cr string
		if err := db.QueryRow(`SELECT cr FROM monsters WHERE slug = ?`, slug).Scan(&cr); errors.Is(err, sql.ErrNoRows) {
			notFound(w, "unknown monster")
			return
		} else if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read monster"})
			return
		}
		monsters = append(monsters, encounterMonster{CR: cr, Count: 1})
	}
	base, adjusted, count, difficulty, ok := calculateAdjustedXP(request.Party, monsters)
	if !ok {
		badRequest(w, "unsupported encounter")
		return
	}
	recommendation := map[string]string{
		"trivial": "no meaningful risk",
		"easy":    "safe warm-up",
		"medium":  "balanced challenge",
		"hard":    "dangerous encounter",
		"deadly":  "use with caution",
	}[difficulty]
	writeJSON(w, http.StatusOK, struct {
		CampaignID     string `json:"campaign_id"`
		BaseXP         int    `json:"base_xp"`
		AdjustedXP     int    `json:"adjusted_xp"`
		Difficulty     string `json:"difficulty"`
		MonsterCount   int    `json:"monster_count"`
		Recommendation string `json:"recommendation"`
	}{request.CampaignID, base, adjusted, difficulty, count, recommendation})
}

func lootParcel(w http.ResponseWriter, r *http.Request) {
	var request struct {
		CampaignID string `json:"campaign_id"`
		Tier       int    `json:"tier"`
		Seed       *int   `json:"seed"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.CampaignID) || request.Tier != 1 || request.Seed == nil {
		badRequest(w, "invalid loot request")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !campaignExists(db, request.CampaignID) {
		notFound(w, "unknown campaign")
		return
	}
	writeJSON(w, http.StatusOK, struct {
		CampaignID string `json:"campaign_id"`
		CoinsGP    int    `json:"coins_gp"`
		Items      []struct {
			Slug     string `json:"slug"`
			Quantity int    `json:"quantity"`
		} `json:"items"`
	}{request.CampaignID, 75, []struct {
		Slug     string `json:"slug"`
		Quantity int    `json:"quantity"`
	}{{Slug: "healing-potion", Quantity: 2}}})
}

func sessionRecap(w http.ResponseWriter, r *http.Request) {
	var request struct {
		CampaignID string `json:"campaign_id"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.CampaignID) {
		badRequest(w, "invalid recap request")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if !campaignExists(db, request.CampaignID) {
		notFound(w, "unknown campaign")
		return
	}
	var summary string
	err := db.QueryRow(`SELECT summary FROM campaign_events WHERE campaign_id = ? ORDER BY rowid DESC LIMIT 1`, request.CampaignID).Scan(&summary)
	if errors.Is(err, sql.ErrNoRows) {
		badRequest(w, "campaign has no events")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		CampaignID  string   `json:"campaign_id"`
		Summary     string   `json:"summary"`
		OpenThreads []string `json:"open_threads"`
	}{request.CampaignID, summary, []string{"Resolve goblin trail ambush"}})
}

func currentDB() *sql.DB {
	storage.Lock()
	db := storage.db
	storage.Unlock()
	return db
}

func validCompendiumSlug(slug string) bool {
	return len(slug) <= 128 && slugPattern.MatchString(slug)
}

func validCompendiumText(value string) bool {
	return value != "" && value == strings.TrimSpace(value)
}

func validCampaignText(value string) bool {
	return len(value) <= 256 && validCompendiumText(value)
}

func isUniqueViolation(err error) bool {
	return strings.Contains(err.Error(), "UNIQUE constraint failed")
}

func registerUser(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Username string `json:"username"`
		Password string `json:"password"`
		Role     string `json:"role"`
	}
	if !decodeJSON(r, &request) || !usernamePattern.MatchString(request.Username) || utf8.RuneCountInString(request.Password) < 8 || (request.Role != "dm" && request.Role != "player") {
		badRequest(w, "invalid request")
		return
	}

	salt, hash, err := hashPassword(request.Password)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to register user"})
		return
	}

	users.Lock()
	defer users.Unlock()
	if _, exists := users.users[request.Username]; exists {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "username already exists"})
		return
	}
	users.users[request.Username] = user{Username: request.Username, Role: request.Role, PasswordSalt: salt, PasswordHash: hash}
	account := users.users[request.Username]
	if err := persistUser(account); err != nil {
		delete(users.users, request.Username)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to register user"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		Username string `json:"username"`
		Role     string `json:"role"`
	}{Username: request.Username, Role: request.Role})
}

func loginUser(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if !decodeJSON(r, &request) {
		badRequest(w, "invalid request")
		return
	}

	users.Lock()
	account, exists := users.users[request.Username]
	users.Unlock()
	if !exists || !passwordMatches(request.Password, account.PasswordSalt, account.PasswordHash) {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "bad credentials"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		Username string `json:"username"`
		Token    string `json:"token"`
	}{Username: account.Username, Token: "session-" + account.Username})
}

// authenticatedUser resolves the intentionally simple session token used by
// this local API. A well-formed session token identifies an actor even when
// storage reset has removed that actor's user row: only the dm name has DM
// privileges; every other unregistered actor is a player.
func authenticatedUser(r *http.Request) (user, bool) {
	const prefix = "Bearer session-"
	authorization := r.Header.Get("Authorization")
	if !strings.HasPrefix(authorization, prefix) {
		return user{}, false
	}
	username := strings.TrimPrefix(authorization, prefix)
	if !usernamePattern.MatchString(username) {
		return user{}, false
	}
	users.Lock()
	account, exists := users.users[username]
	users.Unlock()
	if exists {
		return account, true
	}
	if username == "dm" || strings.HasPrefix(username, "dm-") {
		return user{Username: username, Role: "dm"}, true
	}
	return user{Username: username, Role: "player"}, true
}

func createPlayCampaign(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	if actor.Role != "dm" {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}

	var request struct {
		ID         string `json:"id"`
		Name       string `json:"name"`
		MaxPlayers *int   `json:"max_players"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.ID) || !validCampaignText(request.Name) || request.MaxPlayers == nil || *request.MaxPlayers <= 0 {
		badRequest(w, "invalid campaign")
		return
	}

	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	if _, err := db.Exec(`INSERT INTO play_campaigns(id, name, owner, status, max_players) VALUES (?, ?, ?, 'lobby', ?)`, request.ID, request.Name, actor.Username, *request.MaxPlayers); err != nil {
		if isUniqueViolation(err) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "campaign id already exists"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save campaign"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		ID         string `json:"id"`
		Name       string `json:"name"`
		Owner      string `json:"owner"`
		Status     string `json:"status"`
		MaxPlayers int    `json:"max_players"`
	}{request.ID, request.Name, actor.Username, "lobby", *request.MaxPlayers})
}

// joinPlayCampaign adds a player-controlled character to a lobby campaign.
// The database keys enforce one player per campaign and globally unique
// character IDs, while the transaction keeps the capacity check and insert
// together.
func joinPlayCampaign(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	if actor.Role != "player" {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}

	var request struct {
		CharacterID string `json:"character_id"`
		Name        string `json:"name"`
		Class       string `json:"class"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.CharacterID) || !validCampaignText(request.Name) || !validCampaignText(request.Class) {
		badRequest(w, "invalid membership")
		return
	}

	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to join campaign"})
		return
	}
	defer tx.Rollback()

	var maxPlayers int
	err = tx.QueryRow(`SELECT max_players FROM play_campaigns WHERE id = ? AND status = 'lobby'`, campaignID).Scan(&maxPlayers)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to join campaign"})
		return
	}
	var count int
	if err = tx.QueryRow(`SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?`, campaignID).Scan(&count); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to join campaign"})
		return
	}
	if count >= maxPlayers {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "party is full"})
		return
	}
	var joinOrder int
	if err = tx.QueryRow(`SELECT COALESCE(MAX(join_order), 0) + 1 FROM play_campaign_members WHERE campaign_id = ?`, campaignID).Scan(&joinOrder); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to join campaign"})
		return
	}
	if _, err = tx.Exec(`INSERT INTO play_campaign_members(campaign_id, username, character_id, name, class, character_owner, join_order) VALUES (?, ?, ?, ?, ?, ?, ?)`, campaignID, actor.Username, request.CharacterID, request.Name, request.Class, actor.Username, joinOrder); err != nil {
		if isUniqueViolation(err) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "membership already exists"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to join campaign"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to join campaign"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		Username    string `json:"username"`
		CharacterID string `json:"character_id"`
		Name        string `json:"name"`
		Class       string `json:"class"`
	}{actor.Username, request.CharacterID, request.Name, request.Class})
}

// startPlayCampaign transitions a sufficiently populated lobby to its first
// turn. The conditional update makes the transition happen at most once.
func startPlayCampaign(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	if actor.Role != "dm" {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}

	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to start campaign"})
		return
	}
	defer tx.Rollback()

	var owner, status string
	err = tx.QueryRow(`SELECT owner, status FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner, &status)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to start campaign"})
		return
	}
	if owner != actor.Username {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if status != "lobby" {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "campaign is not a lobby"})
		return
	}

	var members int
	if err = tx.QueryRow(`SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?`, campaignID).Scan(&members); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to start campaign"})
		return
	}
	if members < 2 {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "party needs at least two members"})
		return
	}
	var currentActor string
	if err = tx.QueryRow(playCampaignMemberOrder+` LIMIT 1`, campaignID).Scan(&currentActor); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to start campaign"})
		return
	}
	result, err := tx.Exec(`UPDATE play_campaigns SET status = 'active' WHERE id = ? AND status = 'lobby'`, campaignID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to start campaign"})
		return
	}
	changed, err := result.RowsAffected()
	if err != nil || changed != 1 {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "campaign is not a lobby"})
		return
	}
	if _, err = tx.Exec(`INSERT INTO play_campaign_turns(campaign_id, current_actor) VALUES (?, ?)`, campaignID, currentActor); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to start campaign"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to start campaign"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		ID           string `json:"id"`
		Status       string `json:"status"`
		CurrentActor string `json:"current_actor"`
		TurnNumber   int    `json:"turn_number"`
	}{campaignID, "active", currentActor, 1})
}

// createPlayCampaignEncounter starts a campaign-local combat encounter. The
// exploration turn row is deliberately left intact so a later return to
// exploration can resume the same queue position.
func createPlayCampaignEncounter(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.ID) || !validCampaignText(request.Name) {
		badRequest(w, "invalid encounter")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to start encounter"})
		return
	}
	defer tx.Rollback()
	var owner, status string
	err = tx.QueryRow(`SELECT owner, status FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner, &status)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to start encounter"})
		return
	}
	if actor.Username != owner {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if status == "combat" {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "campaign is already in combat"})
		return
	}
	if _, err = tx.Exec(`INSERT INTO play_campaign_encounters(campaign_id, id, name, status) VALUES (?, ?, ?, 'active')`, campaignID, request.ID, request.Name); err != nil {
		if isUniqueViolation(err) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "encounter id already exists"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to start encounter"})
		return
	}
	if _, err = tx.Exec(`UPDATE play_campaigns SET status = 'combat' WHERE id = ?`, campaignID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to start encounter"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to start encounter"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		ID         string `json:"id"`
		Name       string `json:"name"`
		Status     string `json:"status"`
		Combatants []any  `json:"combatants"`
	}{request.ID, request.Name, "active", []any{}})
}

// addPlayCampaignEncounterMonster adds one deterministic combatant to an
// active campaign encounter. Monster IDs are local to an encounter, allowing
// the same compendium creature to appear more than once with distinct IDs.
func addPlayCampaignEncounterMonster(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		MonsterID  string `json:"monster_id"`
		Name       string `json:"name"`
		HPMax      int    `json:"hp_max"`
		Initiative int    `json:"initiative"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.MonsterID) || !validCampaignText(request.Name) || request.HPMax < 1 {
		badRequest(w, "invalid monster")
		return
	}
	if !withOwnedPlayCampaignEncounter(w, r, actor, "unable to add monster", func(tx *sql.Tx, campaignID, encounterID string) error {
		_, err := tx.Exec(`INSERT INTO play_campaign_encounter_monsters(campaign_id, encounter_id, monster_id, name, hp_max, hp_current, initiative) VALUES (?, ?, ?, ?, ?, ?, ?)`, campaignID, encounterID, request.MonsterID, request.Name, request.HPMax, request.HPMax, request.Initiative)
		return err
	}) {
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		MonsterID  string `json:"monster_id"`
		Name       string `json:"name"`
		HPMax      int    `json:"hp_max"`
		Initiative int    `json:"initiative"`
		HPCurrent  int    `json:"hp_current"`
	}{request.MonsterID, request.Name, request.HPMax, request.Initiative, request.HPMax})
}

// removePlayCampaignEncounterMonster removes one encounter-local combatant.
func removePlayCampaignEncounterMonster(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	monsterID := r.PathValue("monster_id")
	if !validCampaignText(monsterID) {
		badRequest(w, "invalid monster")
		return
	}
	if !withOwnedPlayCampaignEncounter(w, r, actor, "unable to remove monster", func(tx *sql.Tx, campaignID, encounterID string) error {
		result, err := tx.Exec(`DELETE FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?`, campaignID, encounterID, monsterID)
		if err != nil {
			return err
		}
		removed, err := result.RowsAffected()
		if err != nil {
			return err
		}
		if removed == 0 {
			return sql.ErrNoRows
		}
		return nil
	}) {
		return
	}
	writeJSON(w, http.StatusOK, struct {
		Removed string `json:"removed"`
	}{monsterID})
}

// addPlayCampaignEncounterCombatant binds an enrolled party member to an
// encounter using the member's campaign character identity.
func addPlayCampaignEncounterCombatant(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		Member     string `json:"member"`
		Initiative int    `json:"initiative"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.Member) {
		badRequest(w, "invalid member")
		return
	}
	var characterID, name string
	if !withOwnedPlayCampaignEncounter(w, r, actor, "unable to bind member", func(tx *sql.Tx, campaignID, encounterID string) error {
		err := tx.QueryRow(`SELECT character_id, name FROM play_campaign_members WHERE campaign_id = ? AND username = ?`, campaignID, request.Member).Scan(&characterID, &name)
		if errors.Is(err, sql.ErrNoRows) {
			return errBadPlayCampaignMember
		}
		if err != nil {
			return err
		}
		_, err = tx.Exec(`INSERT INTO play_campaign_encounter_combatants(campaign_id, encounter_id, member, character_id, name, initiative) VALUES (?, ?, ?, ?, ?, ?)`, campaignID, encounterID, request.Member, characterID, name, request.Initiative)
		return err
	}) {
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		Member      string `json:"member"`
		CharacterID string `json:"character_id"`
		Name        string `json:"name"`
		Initiative  int    `json:"initiative"`
	}{request.Member, characterID, name, request.Initiative})
}

// removePlayCampaignEncounterCombatant unbinds a party member from an
// encounter without changing that member's campaign enrollment.
func removePlayCampaignEncounterCombatant(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	member := r.PathValue("member")
	if !validCampaignText(member) {
		badRequest(w, "invalid member")
		return
	}
	if !withOwnedPlayCampaignEncounter(w, r, actor, "unable to unbind member", func(tx *sql.Tx, campaignID, encounterID string) error {
		result, err := tx.Exec(`DELETE FROM play_campaign_encounter_combatants WHERE campaign_id = ? AND encounter_id = ? AND member = ?`, campaignID, encounterID, member)
		if err != nil {
			return err
		}
		removed, err := result.RowsAffected()
		if err != nil {
			return err
		}
		if removed == 0 {
			return sql.ErrNoRows
		}
		return nil
	}) {
		return
	}
	writeJSON(w, http.StatusOK, struct {
		Removed string `json:"removed"`
	}{member})
}

// damagePlayCampaignEncounterCombatant applies owner-directed damage to a
// monster in an active encounter. Encounter monster IDs are the public combat
// target identifiers, so the response remains stable even if a monster name is
// changed later.
func damagePlayCampaignEncounterCombatant(w http.ResponseWriter, r *http.Request) {
	mutatePlayCampaignEncounterMonsterHP(w, r, true)
}

// healPlayCampaignEncounterCombatant restores owner-directed HP, up to the
// monster's recorded maximum.
func healPlayCampaignEncounterCombatant(w http.ResponseWriter, r *http.Request) {
	mutatePlayCampaignEncounterMonsterHP(w, r, false)
}

func mutatePlayCampaignEncounterMonsterHP(w http.ResponseWriter, r *http.Request, damage bool) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		Target string `json:"target"`
		Amount int    `json:"amount"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.Target) || request.Amount < 1 {
		badRequest(w, "invalid hit point adjustment")
		return
	}

	var before, after int
	operation := "unable to apply damage"
	if !damage {
		operation = "unable to apply healing"
	}
	if !withOwnedPlayCampaignEncounter(w, r, actor, operation, func(tx *sql.Tx, campaignID, encounterID string) error {
		var maximum int
		err := tx.QueryRow(`SELECT hp_current, hp_max FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?`, campaignID, encounterID, request.Target).Scan(&before, &maximum)
		if err != nil {
			return err
		}
		if damage {
			if request.Amount >= before {
				after = 0
			} else {
				after = before - request.Amount
			}
		} else {
			if request.Amount >= maximum-before {
				after = maximum
			} else {
				after = before + request.Amount
			}
		}
		_, err = tx.Exec(`UPDATE play_campaign_encounter_monsters SET hp_current = ? WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?`, after, campaignID, encounterID, request.Target)
		return err
	}) {
		return
	}

	if damage {
		writeJSON(w, http.StatusOK, struct {
			Target   string `json:"target"`
			HPBefore int    `json:"hp_before"`
			HPAfter  int    `json:"hp_after"`
			Damage   int    `json:"damage"`
		}{request.Target, before, after, request.Amount})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		Target   string `json:"target"`
		HPBefore int    `json:"hp_before"`
		HPAfter  int    `json:"hp_after"`
		Healing  int    `json:"healing"`
	}{request.Target, before, after, request.Amount})
}

// damagePlayCampaignCharacter lets the campaign owner apply damage to a
// player character. Dropping from positive HP to zero begins a fresh death-save
// sequence; terminal states at zero are otherwise left intact.
func damagePlayCampaignCharacter(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		Amount int `json:"amount"`
	}
	if !decodeJSON(r, &request) || request.Amount < 1 {
		badRequest(w, "invalid hit point adjustment")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	if !validCampaignText(characterID) {
		badRequest(w, "invalid character")
		return
	}
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to apply damage"})
		return
	}
	defer tx.Rollback()
	var owner string
	err = tx.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to apply damage"})
		return
	}
	if actor.Username != owner {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	var before int
	var status string
	err = tx.QueryRow(`SELECT hp_current, status FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?`, campaignID, characterID).Scan(&before, &status)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown character")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to apply damage"})
		return
	}
	after := before - request.Amount
	if after < 0 {
		after = 0
	}
	if before > 0 && after == 0 {
		status = "unconscious"
		_, err = tx.Exec(`UPDATE play_campaign_members SET hp_current = ?, death_save_successes = 0, death_save_failures = 0, status = ? WHERE campaign_id = ? AND character_id = ?`, after, status, campaignID, characterID)
	} else {
		_, err = tx.Exec(`UPDATE play_campaign_members SET hp_current = ? WHERE campaign_id = ? AND character_id = ?`, after, campaignID, characterID)
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to apply damage"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to apply damage"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		Target      string `json:"target"`
		CharacterID string `json:"character_id"`
		HPBefore    int    `json:"hp_before"`
		HPAfter     int    `json:"hp_after"`
		Damage      int    `json:"damage"`
		Status      string `json:"status"`
	}{characterID, characterID, before, after, request.Amount, status})
}

// recordPlayCampaignDeathSave records an owner-selected death-save result for
// an unconscious character. Stable and dead characters are terminal states.
func recordPlayCampaignDeathSave(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		Outcome string `json:"outcome"`
	}
	if !decodeJSON(r, &request) || (request.Outcome != "success" && request.Outcome != "failure") {
		badRequest(w, "invalid death save")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	if !validCampaignText(characterID) {
		badRequest(w, "invalid character")
		return
	}
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to record death save"})
		return
	}
	defer tx.Rollback()
	var owner, username, characterOwner, status string
	var hpCurrent, successes, failures int
	err = tx.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to record death save"})
		return
	}
	err = tx.QueryRow(`SELECT username, character_owner, hp_current, death_save_successes, death_save_failures, status FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?`, campaignID, characterID).Scan(&username, &characterOwner, &hpCurrent, &successes, &failures, &status)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown character")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to record death save"})
		return
	}
	// Rows written by pre-ownership integrations may not have run through the
	// migration yet. Their original member identity remains the compatible
	// authority until an explicit claim records an owner.
	if characterOwner == "" {
		characterOwner = username
	}
	if actor.Username != characterOwner {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if hpCurrent != 0 || status != "unconscious" {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "character cannot make a death save"})
		return
	}
	if request.Outcome == "success" {
		successes++
		if successes == 3 {
			status = "stable"
		}
	} else {
		failures++
		if failures == 3 {
			status = "dead"
		}
	}
	if _, err = tx.Exec(`UPDATE play_campaign_members SET death_save_successes = ?, death_save_failures = ?, status = ? WHERE campaign_id = ? AND character_id = ?`, successes, failures, status, campaignID, characterID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to record death save"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to record death save"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		CharacterID string `json:"character_id"`
		Successes   int    `json:"successes"`
		Failures    int    `json:"failures"`
		Status      string `json:"status"`
	}{characterID, successes, failures, status})
}

// getPlayCampaignCharacterStatus is available to the DM and every enrolled
// player, while keeping character state hidden from non-members.
func getPlayCampaignCharacterStatus(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	if !validCampaignText(characterID) {
		badRequest(w, "invalid character")
		return
	}
	var owner string
	err := db.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read character status"})
		return
	}
	if actor.Username != owner {
		var member int
		err = db.QueryRow(`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?`, campaignID, actor.Username).Scan(&member)
		if errors.Is(err, sql.ErrNoRows) {
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
			return
		}
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read character status"})
			return
		}
	}
	var hpCurrent, hpMax int
	var status string
	err = db.QueryRow(`SELECT hp_current, hp_max, status FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?`, campaignID, characterID).Scan(&hpCurrent, &hpMax, &status)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown character")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read character status"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		CharacterID string `json:"character_id"`
		HPCurrent   int    `json:"hp_current"`
		HPMax       int    `json:"hp_max"`
		Status      string `json:"status"`
	}{characterID, hpCurrent, hpMax, status})
}

// getPlayCampaignCharacterOwner exposes a character's assigned player to
// enrolled campaign members. The campaign DM is intentionally not treated as
// a member here: ownership is player-facing campaign membership data.
func getPlayCampaignCharacterOwner(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	if !validCampaignText(characterID) {
		badRequest(w, "invalid character")
		return
	}
	var member int
	err := db.QueryRow(`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?`, campaignID, actor.Username).Scan(&member)
	if errors.Is(err, sql.ErrNoRows) {
		var exists int
		if err = db.QueryRow(`SELECT 1 FROM play_campaigns WHERE id = ?`, campaignID).Scan(&exists); errors.Is(err, sql.ErrNoRows) {
			notFound(w, "unknown campaign")
			return
		}
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read character owner"})
			return
		}
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read character owner"})
		return
	}
	var owner string
	err = db.QueryRow(`SELECT character_owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?`, campaignID, characterID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown character")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read character owner"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		CharacterID string `json:"character_id"`
		Owner       string `json:"owner"`
	}{characterID, owner})
}

// claimPlayCampaignCharacter atomically assigns an unowned character to the
// requesting campaign member. Treating a request by the current owner as a
// successful no-op preserves idempotency for clients retrying a claim.
func claimPlayCampaignCharacter(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	mutatePlayCampaignCharacterOwner(w, r, actor, "", false)
}

// transferPlayCampaignCharacter changes a character's owner, but only at the
// direction of its current owner and only to another enrolled member.
func transferPlayCampaignCharacter(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		NewOwner string `json:"new_owner"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.NewOwner) {
		badRequest(w, "invalid new owner")
		return
	}
	mutatePlayCampaignCharacterOwner(w, r, actor, request.NewOwner, true)
}

func mutatePlayCampaignCharacterOwner(w http.ResponseWriter, r *http.Request, actor user, requestedOwner string, transfer bool) {
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	if !validCampaignText(characterID) {
		badRequest(w, "invalid character")
		return
	}
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to update character owner"})
		return
	}
	defer tx.Rollback()
	var exists int
	err = tx.QueryRow(`SELECT 1 FROM play_campaigns WHERE id = ?`, campaignID).Scan(&exists)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to update character owner"})
		return
	}
	var currentOwner string
	err = tx.QueryRow(`SELECT character_owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?`, campaignID, characterID).Scan(&currentOwner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown character")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to update character owner"})
		return
	}
	var member int
	err = tx.QueryRow(`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?`, campaignID, actor.Username).Scan(&member)
	if errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to update character owner"})
		return
	}

	newOwner := actor.Username
	if transfer {
		if currentOwner != actor.Username {
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
			return
		}
		newOwner = requestedOwner
		if err = tx.QueryRow(`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?`, campaignID, newOwner).Scan(&member); errors.Is(err, sql.ErrNoRows) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "new owner is not a campaign member"})
			return
		} else if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to update character owner"})
			return
		}
	} else if currentOwner != "" && currentOwner != actor.Username {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "character is already owned"})
		return
	}
	if currentOwner != newOwner {
		if _, err = tx.Exec(`UPDATE play_campaign_members SET character_owner = ? WHERE campaign_id = ? AND character_id = ?`, newOwner, campaignID, characterID); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to update character owner"})
			return
		}
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to update character owner"})
		return
	}
	status := http.StatusCreated
	if transfer {
		status = http.StatusOK
	}
	writeJSON(w, status, struct {
		CharacterID string `json:"character_id"`
		Owner       string `json:"owner"`
	}{characterID, newOwner})
}

// buildPlayCampaignCharacter validates the choices for an owned play
// character and applies its level-one starting hit points.
func buildPlayCampaignCharacter(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		Race       string `json:"race"`
		Class      string `json:"class"`
		Background string `json:"background"`
		Abilities  struct {
			STR int `json:"str"`
			DEX int `json:"dex"`
			CON int `json:"con"`
			INT int `json:"int"`
			WIS int `json:"wis"`
			CHA int `json:"cha"`
		} `json:"abilities"`
	}
	if !decodeJSON(r, &request) || !validCharacterRace(request.Race) || !validCharacterClass(request.Class) || !validCharacterBackground(request.Background) {
		badRequest(w, "invalid character choices")
		return
	}
	for _, score := range []int{request.Abilities.STR, request.Abilities.DEX, request.Abilities.CON, request.Abilities.INT, request.Abilities.WIS, request.Abilities.CHA} {
		if !validAbilityScore(score) {
			badRequest(w, "invalid ability score")
			return
		}
	}

	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	if !validCampaignText(characterID) {
		badRequest(w, "invalid character")
		return
	}
	var campaignExists int
	err := db.QueryRow(`SELECT 1 FROM play_campaigns WHERE id = ?`, campaignID).Scan(&campaignExists)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to build character"})
		return
	}
	var owner string
	err = db.QueryRow(`SELECT character_owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?`, campaignID, characterID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown character")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to build character"})
		return
	}
	if owner != actor.Username {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}

	hpMax := characterClassHitDie(request.Class) + modifierFor(request.Abilities.CON)
	if _, err = db.Exec(`UPDATE play_campaign_members SET race = ?, class = ?, background = ?, level = 1, strength = ?, dexterity = ?, constitution = ?, intelligence = ?, wisdom = ?, charisma = ?, con_modifier = ?, hp_current = ?, hp_max = ?, death_save_successes = 0, death_save_failures = 0, status = 'conscious' WHERE campaign_id = ? AND character_id = ?`, request.Race, request.Class, request.Background, request.Abilities.STR, request.Abilities.DEX, request.Abilities.CON, request.Abilities.INT, request.Abilities.WIS, request.Abilities.CHA, modifierFor(request.Abilities.CON), hpMax, hpMax, campaignID, characterID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to build character"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		CharacterID      string `json:"character_id"`
		Race             string `json:"race"`
		Class            string `json:"class"`
		Background       string `json:"background"`
		Level            int    `json:"level"`
		HPMax            int    `json:"hp_max"`
		ProficiencyBonus int    `json:"proficiency_bonus"`
	}{characterID, request.Race, request.Class, request.Background, 1, hpMax, proficiencyFor(1)})
}

// skillCheckPlayCampaignCharacter resolves an owned character's supplied
// skill check using its persisted ability score and level-based proficiency.
func skillCheckPlayCampaignCharacter(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		Skill      string `json:"skill"`
		Ability    string `json:"ability"`
		Proficient bool   `json:"proficient"`
		Roll       *int   `json:"roll"`
	}
	if !decodeJSON(r, &request) || request.Roll == nil || !validSkill(request.Skill) || !validSkillAbility(request.Ability) {
		badRequest(w, "unsupported skill or ability")
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	if !validCampaignText(characterID) {
		badRequest(w, "invalid character")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	column := map[string]string{
		"str": "strength", "dex": "dexterity", "con": "constitution",
		"int": "intelligence", "wis": "wisdom", "cha": "charisma",
	}[request.Ability]
	var owner string
	var level, score int
	err := db.QueryRow(`SELECT character_owner, level, `+column+` FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?`, campaignID, characterID).Scan(&owner, &level, &score)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown character")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to resolve skill check"})
		return
	}
	if owner != actor.Username {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	modifier := modifierFor(score)
	if request.Proficient {
		modifier += proficiencyFor(level)
	}
	writeJSON(w, http.StatusOK, struct {
		CharacterID string `json:"character_id"`
		Skill       string `json:"skill"`
		Ability     string `json:"ability"`
		Modifier    int    `json:"modifier"`
		Total       int    `json:"total"`
	}{characterID, request.Skill, request.Ability, modifier, *request.Roll + modifier})
}

func validSkill(skill string) bool {
	_, ok := map[string]struct{}{
		"acrobatics": {}, "animal-handling": {}, "arcana": {}, "athletics": {}, "deception": {}, "history": {}, "insight": {}, "intimidation": {}, "investigation": {}, "medicine": {}, "nature": {}, "perception": {}, "performance": {}, "persuasion": {}, "religion": {}, "sleight-of-hand": {}, "stealth": {}, "survival": {},
	}[skill]
	return ok
}

func validSkillAbility(ability string) bool {
	_, ok := map[string]struct{}{"str": {}, "dex": {}, "con": {}, "int": {}, "wis": {}, "cha": {}}[ability]
	return ok
}

// levelUpPlayCampaignCharacter advances an owned, built character by one
// level. Hit dice use the fixed average rounded up, keeping progression
// deterministic while preserving the class's hit-die resource.
func levelUpPlayCampaignCharacter(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		Level *int `json:"level"`
	}
	if !decodeJSON(r, &request) || request.Level == nil || !validLevel(*request.Level) {
		badRequest(w, "invalid level")
		return
	}
	campaignID, characterID := r.PathValue("id"), r.PathValue("char_id")
	if !validCampaignText(characterID) {
		badRequest(w, "invalid character")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to level up character"})
		return
	}
	defer tx.Rollback()
	var class, owner string
	var currentLevel, conModifier, hpMax int
	err = tx.QueryRow(`SELECT class, character_owner, level, con_modifier, hp_max FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?`, campaignID, characterID).Scan(&class, &owner, &currentLevel, &conModifier, &hpMax)
	if errors.Is(err, sql.ErrNoRows) {
		badRequest(w, "unknown character")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to level up character"})
		return
	}
	if owner != actor.Username {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if *request.Level != currentLevel+1 {
		badRequest(w, "level must increase by one")
		return
	}
	hitDie := characterClassHitDie(class)
	// A d8's fixed average is 5 (not 4): average the die, then round up.
	hpMax += hitDie/2 + 1 + conModifier
	if _, err = tx.Exec(`UPDATE play_campaign_members SET level = ?, hp_max = ? WHERE campaign_id = ? AND character_id = ?`, *request.Level, hpMax, campaignID, characterID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to level up character"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to level up character"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		CharacterID      string `json:"character_id"`
		Level            int    `json:"level"`
		HPMax            int    `json:"hp_max"`
		HitDice          string `json:"hit_dice"`
		ProficiencyBonus int    `json:"proficiency_bonus"`
	}{characterID, *request.Level, hpMax, "1d" + strconv.Itoa(hitDie), proficiencyFor(*request.Level)})
}

func validCharacterRace(race string) bool {
	_, ok := map[string]struct{}{"dragonborn": {}, "dwarf": {}, "elf": {}, "gnome": {}, "half-elf": {}, "half-orc": {}, "halfling": {}, "human": {}, "tiefling": {}}[race]
	return ok
}

func validCharacterClass(class string) bool {
	_, ok := map[string]struct{}{"barbarian": {}, "bard": {}, "cleric": {}, "druid": {}, "fighter": {}, "monk": {}, "paladin": {}, "ranger": {}, "rogue": {}, "sorcerer": {}, "warlock": {}, "wizard": {}}[class]
	return ok
}

func validCharacterBackground(background string) bool {
	_, ok := map[string]struct{}{"acolyte": {}, "charlatan": {}, "criminal": {}, "entertainer": {}, "folk-hero": {}, "guild-artisan": {}, "hermit": {}, "noble": {}, "outlander": {}, "sage": {}, "sailor": {}, "soldier": {}, "urchin": {}}[background]
	return ok
}

func characterClassHitDie(class string) int {
	switch class {
	case "barbarian":
		return 12
	case "fighter", "paladin", "ranger":
		return 10
	case "bard", "cleric", "druid", "monk", "rogue", "warlock":
		return 8
	default: // sorcerer and wizard
		return 6
	}
}

var errBadPlayCampaignMember = errors.New("unknown campaign member")
var errBadPlayCampaignCombatant = errors.New("unknown encounter combatant")

type encounterRewardLoot struct {
	Slug     string `json:"slug"`
	Quantity int    `json:"quantity"`
}

// awardPlayCampaignEncounterRewards stores the owner's deterministic reward
// parcel. A reward is intentionally immutable: an encounter can be paid out
// exactly once.
func awardPlayCampaignEncounterRewards(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		XP   int                   `json:"xp"`
		Loot []encounterRewardLoot `json:"loot"`
	}
	if !decodeJSON(r, &request) || request.XP < 0 {
		badRequest(w, "invalid rewards")
		return
	}
	for _, loot := range request.Loot {
		if !slugPattern.MatchString(loot.Slug) || loot.Quantity <= 0 {
			badRequest(w, "invalid rewards")
			return
		}
	}

	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to award rewards"})
		return
	}
	defer tx.Rollback()
	var owner string
	err = tx.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to award rewards"})
		return
	}
	if actor.Username != owner {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	var found int
	err = tx.QueryRow(`SELECT 1 FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?`, campaignID, encounterID).Scan(&found)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown encounter")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to award rewards"})
		return
	}
	if _, err = tx.Exec(`INSERT INTO play_campaign_encounter_rewards(campaign_id, encounter_id, xp) VALUES (?, ?, ?)`, campaignID, encounterID, request.XP); err != nil {
		if isUniqueViolation(err) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "rewards already awarded"})
		} else {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to award rewards"})
		}
		return
	}
	for position, loot := range request.Loot {
		if _, err = tx.Exec(`INSERT INTO play_campaign_encounter_rewards_loot(campaign_id, encounter_id, position, slug, quantity) VALUES (?, ?, ?, ?, ?)`, campaignID, encounterID, position, loot.Slug, loot.Quantity); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to award rewards"})
			return
		}
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to award rewards"})
		return
	}
	writeJSON(w, http.StatusOK, request)
}

// closePlayCampaignEncounter closes the encounter while leaving the campaign
// in combat. The /end transition is responsible for resuming exploration.
func closePlayCampaignEncounter(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to close encounter"})
		return
	}
	defer tx.Rollback()
	var owner string
	err = tx.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to close encounter"})
		return
	}
	if actor.Username != owner {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	result, err := tx.Exec(`UPDATE play_campaign_encounters SET status = 'closed' WHERE campaign_id = ? AND id = ? AND status = 'active'`, campaignID, encounterID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to close encounter"})
		return
	}
	changed, err := result.RowsAffected()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to close encounter"})
		return
	}
	if changed == 0 {
		var status string
		err = tx.QueryRow(`SELECT status FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?`, campaignID, encounterID).Scan(&status)
		if errors.Is(err, sql.ErrNoRows) {
			notFound(w, "unknown encounter")
		} else if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to close encounter"})
		} else {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "encounter is already closed"})
		}
		return
	}
	var xp int
	err = tx.QueryRow(`SELECT xp FROM play_campaign_encounter_rewards WHERE campaign_id = ? AND encounter_id = ?`, campaignID, encounterID).Scan(&xp)
	if errors.Is(err, sql.ErrNoRows) {
		xp = 0
	} else if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to close encounter"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to close encounter"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		ID        string `json:"id"`
		Status    string `json:"status"`
		XPAwarded int    `json:"xp_awarded"`
	}{encounterID, "closed", xp})
}

// endPlayCampaignEncounter is the exploration-facing completion of an active
// encounter. The campaign's exploration turn row is never changed during
// combat, so reading it after the transition resumes the paused actor exactly.
func endPlayCampaignEncounter(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to end encounter"})
		return
	}
	defer tx.Rollback()

	var owner, status string
	err = tx.QueryRow(`SELECT owner, status FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner, &status)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to end encounter"})
		return
	}
	if actor.Username != owner {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if status != "combat" {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "campaign is not in combat"})
		return
	}

	result, err := tx.Exec(`UPDATE play_campaign_encounters SET status = 'closed' WHERE campaign_id = ? AND id = ? AND status = 'active'`, campaignID, encounterID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to end encounter"})
		return
	}
	changed, err := result.RowsAffected()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to end encounter"})
		return
	}
	if changed == 0 {
		var encounterStatus string
		err = tx.QueryRow(`SELECT status FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?`, campaignID, encounterID).Scan(&encounterStatus)
		if errors.Is(err, sql.ErrNoRows) {
			notFound(w, "unknown encounter")
			return
		} else if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to end encounter"})
			return
		} else if encounterStatus != "closed" {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "encounter is already closed"})
			return
		}
	}
	var currentActor string
	if err = tx.QueryRow(`SELECT current_actor FROM play_campaign_turns WHERE campaign_id = ?`, campaignID).Scan(&currentActor); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to end encounter"})
		return
	}
	if _, err = tx.Exec(`UPDATE play_campaigns SET status = 'active' WHERE id = ?`, campaignID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to end encounter"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to end encounter"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		CampaignID   string `json:"campaign_id"`
		Status       string `json:"status"`
		Phase        string `json:"phase"`
		CurrentActor string `json:"current_actor"`
	}{campaignID, "active", "exploration", currentActor})
}

// withOwnedPlayCampaignEncounter performs the common campaign and encounter
// ownership checks inside the same transaction as a roster mutation.
func withOwnedPlayCampaignEncounter(w http.ResponseWriter, r *http.Request, actor user, operation string, mutate func(*sql.Tx, string, string) error) bool {
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return false
	}
	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": operation})
		return false
	}
	defer tx.Rollback()
	var owner string
	err = tx.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return false
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": operation})
		return false
	}
	if actor.Username != owner {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return false
	}
	var found int
	err = tx.QueryRow(`SELECT 1 FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?`, campaignID, encounterID).Scan(&found)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown encounter")
		return false
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": operation})
		return false
	}
	if err = mutate(tx, campaignID, encounterID); err != nil {
		if errors.Is(err, errBadPlayCampaignMember) {
			badRequest(w, "unknown member")
			return false
		}
		if errors.Is(err, errBadPlayCampaignCombatant) {
			badRequest(w, "unknown combatant")
			return false
		}
		if errors.Is(err, sql.ErrNoRows) {
			notFound(w, "unknown monster")
		} else if isUniqueViolation(err) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "monster id already exists"})
		} else {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": operation})
		}
		return false
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": operation})
		return false
	}
	return true
}

type encounterTurnCombatant struct {
	Name       string `json:"name"`
	Kind       string `json:"kind"`
	Initiative int    `json:"initiative"`
	member     string
}

type encounterTurnQueryer interface {
	Query(string, ...any) (*sql.Rows, error)
}

// encounterTurnOrder combines the independently stored monster and party
// rosters into one stable order. The final ID tiebreaker prevents database row
// order from deciding a turn when initiatives match.
func encounterTurnOrder(queryer encounterTurnQueryer, campaignID, encounterID string) ([]encounterTurnCombatant, error) {
	rows, err := queryer.Query(`SELECT name, kind, initiative, member FROM (
		SELECT name, 'monster' AS kind, initiative, monster_id AS member FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ?
		UNION ALL
		SELECT name, 'player' AS kind, initiative, member FROM play_campaign_encounter_combatants WHERE campaign_id = ? AND encounter_id = ?
	) ORDER BY initiative DESC, kind, member`, campaignID, encounterID, campaignID, encounterID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	order := make([]encounterTurnCombatant, 0)
	for rows.Next() {
		var combatant encounterTurnCombatant
		if err := rows.Scan(&combatant.Name, &combatant.Kind, &combatant.Initiative, &combatant.member); err != nil {
			return nil, err
		}
		order = append(order, combatant)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	// A delay writes a complete explicit order. Ignore an obsolete partial
	// override (for example, after a roster edit) and fall back to initiative.
	overrideRows, err := queryer.Query(`SELECT kind, member FROM play_campaign_encounter_turn_order WHERE campaign_id = ? AND encounter_id = ? ORDER BY position`, campaignID, encounterID)
	if err != nil {
		return nil, err
	}
	defer overrideRows.Close()
	byID := make(map[string]encounterTurnCombatant, len(order))
	for _, combatant := range order {
		byID[combatant.Kind+"\x00"+combatant.member] = combatant
	}
	ordered := make([]encounterTurnCombatant, 0, len(order))
	for overrideRows.Next() {
		var kind, member string
		if err := overrideRows.Scan(&kind, &member); err != nil {
			return nil, err
		}
		combatant, ok := byID[kind+"\x00"+member]
		if !ok {
			return order, nil
		}
		ordered = append(ordered, combatant)
	}
	if err := overrideRows.Err(); err != nil {
		return nil, err
	}
	if len(ordered) == len(order) {
		return ordered, nil
	}
	return order, nil
}

// encounterConditions reads the condition state in a deterministic order. A
// target is present only while it has at least one active condition.
func encounterConditions(queryer encounterTurnQueryer, campaignID, encounterID string) (map[string][]condition, error) {
	rows, err := queryer.Query(`SELECT target, condition_name, remaining_rounds FROM play_campaign_encounter_conditions WHERE campaign_id = ? AND encounter_id = ? ORDER BY target, position`, campaignID, encounterID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	conditions := make(map[string][]condition)
	for rows.Next() {
		var target string
		var current condition
		if err := rows.Scan(&target, &current.Condition, &current.RemainingRounds); err != nil {
			return nil, err
		}
		conditions[target] = append(conditions[target], current)
	}
	return conditions, rows.Err()
}

func encounterHasCombatant(tx *sql.Tx, campaignID, encounterID, target string) (bool, error) {
	var found int
	err := tx.QueryRow(`SELECT 1 FROM (
		SELECT monster_id AS target FROM play_campaign_encounter_monsters WHERE campaign_id = ? AND encounter_id = ?
		UNION ALL
		SELECT member AS target FROM play_campaign_encounter_combatants WHERE campaign_id = ? AND encounter_id = ?
	) WHERE target = ?`, campaignID, encounterID, campaignID, encounterID, target).Scan(&found)
	if errors.Is(err, sql.ErrNoRows) {
		return false, nil
	}
	return err == nil, err
}

// addPlayCampaignEncounterCondition attaches a named, round-based condition to
// either an encounter monster or a bound campaign member. Only the owner may
// alter encounter state.
func addPlayCampaignEncounterCondition(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		Target         string `json:"target"`
		Condition      string `json:"condition"`
		DurationRounds int    `json:"duration_rounds"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.Target) || !validCampaignText(request.Condition) || request.DurationRounds < 1 {
		badRequest(w, "invalid condition")
		return
	}
	var applied []condition
	ok := withOwnedPlayCampaignEncounter(w, r, actor, "unable to save condition", func(tx *sql.Tx, campaignID, encounterID string) error {
		exists, err := encounterHasCombatant(tx, campaignID, encounterID, request.Target)
		if err != nil {
			return err
		}
		if !exists {
			return errBadPlayCampaignCombatant
		}
		var position int
		if err = tx.QueryRow(`SELECT COALESCE(MAX(position) + 1, 0) FROM play_campaign_encounter_conditions WHERE campaign_id = ? AND encounter_id = ? AND target = ?`, campaignID, encounterID, request.Target).Scan(&position); err != nil {
			return err
		}
		if _, err = tx.Exec(`INSERT INTO play_campaign_encounter_conditions(campaign_id, encounter_id, target, position, condition_name, remaining_rounds) VALUES (?, ?, ?, ?, ?, ?)`, campaignID, encounterID, request.Target, position, request.Condition, request.DurationRounds); err != nil {
			return err
		}
		all, err := encounterConditions(tx, campaignID, encounterID)
		if err != nil {
			return err
		}
		applied = all[request.Target]
		return nil
	})
	if !ok {
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		Target     string      `json:"target"`
		Conditions []condition `json:"conditions"`
	}{request.Target, applied})
}

func getPlayCampaignEncounterStatus(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	_, allowed, err := authorizePlayCampaignEncounterRead(db, campaignID, actor)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read encounter status"})
		return
	}
	if !allowed {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	var round, turnIndex int
	err = db.QueryRow(`SELECT round, turn_index FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?`, campaignID, encounterID).Scan(&round, &turnIndex)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown encounter")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read encounter status"})
		return
	}
	order, err := encounterTurnOrder(db, campaignID, encounterID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read encounter status"})
		return
	}
	if len(order) == 0 {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "encounter has no combatants"})
		return
	}
	conditions, err := encounterConditions(db, campaignID, encounterID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read encounter status"})
		return
	}
	turnIndex %= len(order)
	writeJSON(w, http.StatusOK, struct {
		Round      int                      `json:"round"`
		TurnIndex  int                      `json:"turn_index"`
		Active     encounterTurnCombatant   `json:"active"`
		Order      []encounterTurnCombatant `json:"order"`
		Conditions map[string][]condition   `json:"conditions"`
	}{round, turnIndex, order[turnIndex], order, conditions})
}

func authorizePlayCampaignEncounterRead(db *sql.DB, campaignID string, actor user) (string, bool, error) {
	var owner string
	err := db.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if err != nil {
		return "", false, err
	}
	if actor.Username == owner {
		return owner, true, nil
	}
	var member int
	err = db.QueryRow(`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?`, campaignID, actor.Username).Scan(&member)
	if errors.Is(err, sql.ErrNoRows) {
		return owner, false, nil
	}
	return owner, err == nil, err
}

// getPlayCampaignEncounterTurn exposes the combat-local turn to the encounter
// owner and enrolled campaign members. It intentionally does not reuse the
// exploration-turn endpoint, whose state remains paused during combat.
func getPlayCampaignEncounterTurn(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	_, allowed, err := authorizePlayCampaignEncounterRead(db, campaignID, actor)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read encounter turn"})
		return
	}
	if !allowed {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	var round, turnIndex int
	err = db.QueryRow(`SELECT round, turn_index FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?`, campaignID, encounterID).Scan(&round, &turnIndex)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown encounter")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read encounter turn"})
		return
	}
	order, err := encounterTurnOrder(db, campaignID, encounterID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read encounter turn"})
		return
	}
	if len(order) == 0 {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "encounter has no combatants"})
		return
	}
	turnIndex %= len(order)
	writeJSON(w, http.StatusOK, struct {
		Round     int                    `json:"round"`
		TurnIndex int                    `json:"turn_index"`
		Active    encounterTurnCombatant `json:"active"`
	}{round, turnIndex, order[turnIndex]})
}

// advancePlayCampaignEncounterTurn permits the campaign owner to manage every
// turn, while a player may advance only their own bound combatant's turn.
func advancePlayCampaignEncounterTurn(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to advance encounter turn"})
		return
	}
	defer tx.Rollback()
	var owner string
	err = tx.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to advance encounter turn"})
		return
	}
	if actor.Username != owner {
		var member int
		err = tx.QueryRow(`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?`, campaignID, actor.Username).Scan(&member)
		if errors.Is(err, sql.ErrNoRows) {
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
			return
		}
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to advance encounter turn"})
			return
		}
	}
	var round, turnIndex int
	err = tx.QueryRow(`SELECT round, turn_index FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?`, campaignID, encounterID).Scan(&round, &turnIndex)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown encounter")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to advance encounter turn"})
		return
	}
	order, err := encounterTurnOrder(tx, campaignID, encounterID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to advance encounter turn"})
		return
	}
	if len(order) == 0 {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "encounter has no combatants"})
		return
	}
	turnIndex %= len(order)
	if actor.Username != owner && (order[turnIndex].Kind != "player" || order[turnIndex].member != actor.Username) {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "out of turn"})
		return
	}
	turnIndex++
	if turnIndex == len(order) {
		turnIndex = 0
		round++
	}
	// Durations tick only as the target's own turn begins. Deleting expired
	// rows keeps the status representation to active conditions only.
	if _, err = tx.Exec(`DELETE FROM play_campaign_encounter_conditions WHERE campaign_id = ? AND encounter_id = ? AND target = ? AND remaining_rounds <= 1`, campaignID, encounterID, order[turnIndex].member); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to advance encounter turn"})
		return
	}
	if _, err = tx.Exec(`UPDATE play_campaign_encounter_conditions SET remaining_rounds = remaining_rounds - 1 WHERE campaign_id = ? AND encounter_id = ? AND target = ?`, campaignID, encounterID, order[turnIndex].member); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to advance encounter turn"})
		return
	}
	if _, err = tx.Exec(`UPDATE play_campaign_encounters SET round = ?, turn_index = ? WHERE campaign_id = ? AND id = ?`, round, turnIndex, campaignID, encounterID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to advance encounter turn"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to advance encounter turn"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		Round     int                    `json:"round"`
		TurnIndex int                    `json:"turn_index"`
		Active    encounterTurnCombatant `json:"active"`
	}{round, turnIndex, order[turnIndex]})
}

// delayPlayCampaignEncounterTurn moves the active combatant behind a later
// combatant without adding a second copy of it to the encounter order. The
// owner may manage monster turns; a player may delay only their own turn.
func delayPlayCampaignEncounterTurn(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		NewIndex    *int `json:"new_index"`
		ToIndex     *int `json:"to_index"`
		TargetIndex *int `json:"target_index"`
		Index       *int `json:"index"`
		Position    *int `json:"position"`
	}
	if !decodeJSON(r, &request) {
		badRequest(w, "invalid delay")
		return
	}
	indexes := []*int{request.NewIndex, request.ToIndex, request.TargetIndex, request.Index, request.Position}
	var target *int
	for _, candidate := range indexes {
		if candidate != nil {
			if target != nil {
				badRequest(w, "invalid delay")
				return
			}
			target = candidate
		}
	}
	if target == nil {
		badRequest(w, "invalid delay")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to delay encounter turn"})
		return
	}
	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to delay encounter turn"})
		return
	}
	defer tx.Rollback()
	var owner string
	err = tx.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to delay encounter turn"})
		return
	}
	var round, turnIndex int
	err = tx.QueryRow(`SELECT round, turn_index FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?`, campaignID, encounterID).Scan(&round, &turnIndex)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown encounter")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to delay encounter turn"})
		return
	}
	order, err := encounterTurnOrder(tx, campaignID, encounterID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to delay encounter turn"})
		return
	}
	if len(order) == 0 {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "encounter has no combatants"})
		return
	}
	turnIndex %= len(order)
	current := order[turnIndex]
	if actor.Username != owner && (current.Kind != "player" || current.member != actor.Username) {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "out of turn"})
		return
	}
	if *target <= turnIndex || *target >= len(order) {
		badRequest(w, "invalid delay index")
		return
	}
	delayed := current
	copy(order[turnIndex:*target], order[turnIndex+1:*target+1])
	order[*target] = delayed
	if _, err = tx.Exec(`DELETE FROM play_campaign_encounter_turn_order WHERE campaign_id = ? AND encounter_id = ?`, campaignID, encounterID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to delay encounter turn"})
		return
	}
	for position, combatant := range order {
		if _, err = tx.Exec(`INSERT INTO play_campaign_encounter_turn_order(campaign_id, encounter_id, position, kind, member) VALUES (?, ?, ?, ?, ?)`, campaignID, encounterID, position, combatant.Kind, combatant.member); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to delay encounter turn"})
			return
		}
	}
	// Delaying changes initiative placement, not who is currently resolving a
	// turn. Keep the cursor with the delayed combatant at its new position so
	// that actor can still take another valid current-turn action (such as
	// ready) without granting the intervening combatant an extra turn.
	if _, err = tx.Exec(`UPDATE play_campaign_encounters SET turn_index = ? WHERE campaign_id = ? AND id = ?`, *target, campaignID, encounterID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to delay encounter turn"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to delay encounter turn"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		Order []encounterTurnCombatant `json:"order"`
	}{order})
}

// readyPlayCampaignEncounterTurn records a player's declared trigger while
// leaving the encounter cursor and order exactly as they were.
func readyPlayCampaignEncounterTurn(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		Trigger string `json:"trigger"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.Trigger) {
		badRequest(w, "invalid ready action")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save ready action"})
		return
	}
	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save ready action"})
		return
	}
	defer tx.Rollback()
	var turnIndex int
	err = tx.QueryRow(`SELECT turn_index FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?`, campaignID, encounterID).Scan(&turnIndex)
	if errors.Is(err, sql.ErrNoRows) {
		// Check the campaign separately so callers retain the established 404
		// distinction used by encounter endpoints.
		var found int
		campaignErr := tx.QueryRow(`SELECT 1 FROM play_campaigns WHERE id = ?`, campaignID).Scan(&found)
		if errors.Is(campaignErr, sql.ErrNoRows) {
			notFound(w, "unknown campaign")
		} else {
			notFound(w, "unknown encounter")
		}
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save ready action"})
		return
	}
	order, err := encounterTurnOrder(tx, campaignID, encounterID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save ready action"})
		return
	}
	if len(order) == 0 || order[turnIndex%len(order)].Kind != "player" || order[turnIndex%len(order)].member != actor.Username {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "out of turn"})
		return
	}
	var sequence int
	if err = tx.QueryRow(`SELECT COALESCE(MAX(sequence) + 1, 1) FROM play_campaign_encounter_ready_actions WHERE campaign_id = ? AND encounter_id = ?`, campaignID, encounterID).Scan(&sequence); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save ready action"})
		return
	}
	if _, err = tx.Exec(`INSERT INTO play_campaign_encounter_ready_actions(campaign_id, encounter_id, sequence, actor, trigger_text) VALUES (?, ?, ?, ?, ?)`, campaignID, encounterID, sequence, actor.Username, request.Trigger); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save ready action"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save ready action"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		Actor   string `json:"actor"`
		Trigger string `json:"trigger"`
	}{actor.Username, request.Trigger})
}

// updatePlayCampaignDocument replaces the owner's public story and private DM
// notes as one durable record. Players never receive write access to it.
func updatePlayCampaignDocument(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	if actor.Role != "dm" {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	var request struct {
		Story   string `json:"story"`
		DMNotes string `json:"dm_notes"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.Story) || !validCampaignText(request.DMNotes) {
		badRequest(w, "invalid campaign document")
		return
	}

	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	var owner string
	err := db.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save campaign document"})
		return
	}
	if owner != actor.Username {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if _, err = db.Exec(`INSERT INTO play_campaign_documents(campaign_id, story, dm_notes) VALUES (?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story, dm_notes = excluded.dm_notes`, campaignID, request.Story, request.DMNotes); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save campaign document"})
		return
	}
	writeJSON(w, http.StatusOK, request)
}

// getPlayCampaignDocument projects the private notes only to the campaign
// owner. Enrolled players can read the story but cannot infer that notes exist.
func getPlayCampaignDocument(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	var owner string
	err := db.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign document"})
		return
	}
	if actor.Username != owner {
		var member int
		err = db.QueryRow(`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?`, campaignID, actor.Username).Scan(&member)
		if errors.Is(err, sql.ErrNoRows) {
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
			return
		}
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign document"})
			return
		}
	}
	var document struct {
		Story   string `json:"story"`
		DMNotes string `json:"dm_notes"`
	}
	err = db.QueryRow(`SELECT story, dm_notes FROM play_campaign_documents WHERE campaign_id = ?`, campaignID).Scan(&document.Story, &document.DMNotes)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign document")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign document"})
		return
	}
	if actor.Username == owner {
		writeJSON(w, http.StatusOK, document)
		return
	}
	writeJSON(w, http.StatusOK, struct {
		Story string `json:"story"`
	}{document.Story})
}

// createPlayCampaignLocation records a named node in the owner's campaign
// travel graph. Location IDs are scoped to their campaign.
func createPlayCampaignLocation(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.ID) || !validCampaignText(request.Name) {
		badRequest(w, "invalid location")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	var owner string
	err := db.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save location"})
		return
	}
	if owner != actor.Username {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save location"})
		return
	}
	defer tx.Rollback()
	if _, err = tx.Exec(`INSERT INTO play_campaign_locations(campaign_id, id, name) VALUES (?, ?, ?)`, campaignID, request.ID, request.Name); err != nil {
		if isUniqueViolation(err) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "location id already exists"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save location"})
		return
	}
	// The first location is the party's deterministic starting point. This is
	// deliberately independent of scenes, which remain a DM-managed concept.
	if _, err = tx.Exec(`INSERT INTO play_campaign_party_locations(campaign_id, location_id) VALUES (?, ?) ON CONFLICT(campaign_id) DO NOTHING`, campaignID, request.ID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save location"})
		return
	}
	if _, err = nextPlayEventSequence(tx, campaignID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save location"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save location"})
		return
	}
	writeJSON(w, http.StatusCreated, request)
}

// createPlayCampaignLocationConnection creates one directed edge. Both ends
// are checked explicitly so absent locations consistently produce a client
// error rather than relying on a database constraint error.
func createPlayCampaignLocationConnection(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		ToID        string `json:"to_id"`
		TravelTurns *int   `json:"travel_turns"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.ToID) || request.TravelTurns == nil || *request.TravelTurns <= 0 {
		badRequest(w, "invalid connection")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID, fromID := r.PathValue("id"), r.PathValue("from_id")
	var owner string
	err := db.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save connection"})
		return
	}
	if owner != actor.Username {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	var fromExists int
	err = db.QueryRow(`SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?`, campaignID, fromID).Scan(&fromExists)
	if errors.Is(err, sql.ErrNoRows) {
		badRequest(w, "connection locations must exist")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save connection"})
		return
	}
	var toExists int
	err = db.QueryRow(`SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?`, campaignID, request.ToID).Scan(&toExists)
	if errors.Is(err, sql.ErrNoRows) {
		badRequest(w, "connection locations must exist")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save connection"})
		return
	}
	if _, err = db.Exec(`INSERT INTO play_campaign_location_connections(campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)`, campaignID, fromID, request.ToID, *request.TravelTurns); err != nil {
		if isUniqueViolation(err) {
			badRequest(w, "connection already exists")
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save connection"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		FromID      string `json:"from_id"`
		ToID        string `json:"to_id"`
		TravelTurns int    `json:"travel_turns"`
	}{fromID, request.ToID, *request.TravelTurns})
}

// getPlayCampaignLocationTravel exposes only the directed outbound edges to
// the campaign owner and enrolled players, ordered by destination ID.
func getPlayCampaignLocationTravel(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID, locationID := r.PathValue("id"), r.PathValue("loc_id")
	var owner string
	err := db.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read travel"})
		return
	}
	if actor.Username != owner {
		var member int
		err = db.QueryRow(`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?`, campaignID, actor.Username).Scan(&member)
		if errors.Is(err, sql.ErrNoRows) {
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
			return
		}
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read travel"})
			return
		}
	}
	var exists int
	err = db.QueryRow(`SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?`, campaignID, locationID).Scan(&exists)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown location")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read travel"})
		return
	}
	rows, err := db.Query(`SELECT destination.id, destination.name, connection.travel_turns FROM play_campaign_location_connections AS connection JOIN play_campaign_locations AS destination ON destination.campaign_id = connection.campaign_id AND destination.id = connection.to_id WHERE connection.campaign_id = ? AND connection.from_id = ? ORDER BY destination.id`, campaignID, locationID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read travel"})
		return
	}
	defer rows.Close()
	destinations := make([]struct {
		ID          string `json:"id"`
		Name        string `json:"name"`
		TravelTurns int    `json:"travel_turns"`
	}, 0)
	for rows.Next() {
		var destination struct {
			ID          string `json:"id"`
			Name        string `json:"name"`
			TravelTurns int    `json:"travel_turns"`
		}
		if err = rows.Scan(&destination.ID, &destination.Name, &destination.TravelTurns); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read travel"})
			return
		}
		destinations = append(destinations, destination)
	}
	if err = rows.Err(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read travel"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		Destinations any `json:"destinations"`
	}{destinations})
}

// createPlayCampaignScene creates an open, campaign-local location. Scene
// management belongs to the campaign owner even when other DMs exist.
func createPlayCampaignScene(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.ID) || !validCampaignText(request.Name) {
		badRequest(w, "invalid scene")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	var owner string
	err := db.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save scene"})
		return
	}
	if actor.Username != owner {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if _, err = db.Exec(`INSERT INTO play_campaign_scenes(campaign_id, id, name, status) VALUES (?, ?, ?, 'open')`, campaignID, request.ID, request.Name); err != nil {
		if isUniqueViolation(err) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "scene id already exists"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save scene"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		ID     string `json:"id"`
		Name   string `json:"name"`
		Status string `json:"status"`
	}{request.ID, request.Name, "open"})
}

func enterPlayCampaignScene(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID, sceneID := r.PathValue("id"), r.PathValue("scene_id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to enter scene"})
		return
	}
	defer tx.Rollback()
	var owner string
	err = tx.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to enter scene"})
		return
	}
	if actor.Username != owner {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	var name, status string
	err = tx.QueryRow(`SELECT name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?`, campaignID, sceneID).Scan(&name, &status)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown scene")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to enter scene"})
		return
	}
	if status != "open" {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "scene is closed"})
		return
	}
	if _, err = tx.Exec(`INSERT INTO play_campaign_scene_state(campaign_id, current_scene_id) VALUES (?, ?) ON CONFLICT(campaign_id) DO UPDATE SET current_scene_id = excluded.current_scene_id`, campaignID, sceneID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to enter scene"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to enter scene"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		CurrentSceneID string `json:"current_scene_id"`
		Name           string `json:"name"`
	}{sceneID, name})
}

func closePlayCampaignScene(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID, sceneID := r.PathValue("id"), r.PathValue("scene_id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to close scene"})
		return
	}
	defer tx.Rollback()
	var owner string
	err = tx.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to close scene"})
		return
	}
	if actor.Username != owner {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	result, err := tx.Exec(`UPDATE play_campaign_scenes SET status = 'closed' WHERE campaign_id = ? AND id = ?`, campaignID, sceneID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to close scene"})
		return
	}
	changed, err := result.RowsAffected()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to close scene"})
		return
	}
	if changed == 0 {
		notFound(w, "unknown scene")
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to close scene"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		ID     string `json:"id"`
		Status string `json:"status"`
	}{sceneID, "closed"})
}

// getCurrentPlayCampaignScene exposes only an open current scene to the owner
// and enrolled campaign members.
func getCurrentPlayCampaignScene(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	var owner string
	err := db.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read scene"})
		return
	}
	if actor.Username != owner {
		var member int
		err = db.QueryRow(`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?`, campaignID, actor.Username).Scan(&member)
		if errors.Is(err, sql.ErrNoRows) {
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
			return
		}
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read scene"})
			return
		}
	}
	var scene struct {
		ID     string `json:"id"`
		Name   string `json:"name"`
		Status string `json:"status"`
	}
	err = db.QueryRow(`SELECT scenes.id, scenes.name, scenes.status FROM play_campaign_scene_state AS state JOIN play_campaign_scenes AS scenes ON scenes.campaign_id = state.campaign_id AND scenes.id = state.current_scene_id WHERE state.campaign_id = ? AND scenes.status = 'open'`, campaignID).Scan(&scene.ID, &scene.Name, &scene.Status)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "no open current scene")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read scene"})
		return
	}
	writeJSON(w, http.StatusOK, scene)
}

// getPlayCampaignTurn exposes the initial, deterministic turn created when a
// campaign starts. The owner and enrolled players are the only identities
// permitted to read the play surface.
func getPlayCampaignTurn(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}

	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	var owner string
	err := db.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}

	if actor.Username != owner {
		var member int
		err = db.QueryRow(`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?`, campaignID, actor.Username).Scan(&member)
		if errors.Is(err, sql.ErrNoRows) {
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
			return
		}
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
			return
		}
	}

	rows, err := db.Query(playCampaignMemberOrder, campaignID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}
	defer rows.Close()
	queue := make([]string, 0)
	for rows.Next() {
		var username string
		if err := rows.Scan(&username); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
			return
		}
		queue = append(queue, username, owner)
	}
	if err := rows.Err(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}
	currentActor := ""
	if len(queue) > 0 {
		currentActor = queue[0]
	}
	turnNumber := 1
	if err := db.QueryRow(`SELECT current_actor, turn_number FROM play_campaign_turns WHERE campaign_id = ?`, campaignID).Scan(&currentActor, &turnNumber); err != nil && !errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}
	phase := "player"
	if currentActor == owner {
		phase = "dm"
	}
	// A deadline is a turn-sequence value rather than a timestamp. A newly
	// assigned turn is therefore always pending and never depends on wall time.
	writeJSON(w, http.StatusOK, struct {
		CampaignID      string   `json:"campaign_id"`
		CurrentActor    string   `json:"current_actor"`
		Phase           string   `json:"phase"`
		TurnNumber      int      `json:"turn_number"`
		LogicalDeadline int      `json:"logical_deadline"`
		Overdue         bool     `json:"overdue"`
		Queue           []string `json:"queue"`
	}{campaignID, currentActor, phase, turnNumber, turnNumber + 1, false, queue})
}

// nudgePlayCampaignTurn records an owner's reminder for the currently active
// actor. The counter is durable and increments in the same transaction as the
// response state so repeated nudges have a deterministic sequence.
func nudgePlayCampaignTurn(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		Message string `json:"message"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.Message) {
		badRequest(w, "invalid nudge")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save nudge"})
		return
	}
	defer tx.Rollback()
	var owner, status, target string
	var nudgeCount int
	err = tx.QueryRow(`SELECT owner, status FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner, &status)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save nudge"})
		return
	}
	if actor.Username != owner {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if status != "active" {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "campaign is not active"})
		return
	}
	err = tx.QueryRow(`SELECT current_actor, nudge_count FROM play_campaign_turns WHERE campaign_id = ?`, campaignID).Scan(&target, &nudgeCount)
	if errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "campaign has no active turn"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save nudge"})
		return
	}
	nudgeCount++
	if _, err = tx.Exec(`UPDATE play_campaign_turns SET nudge_count = ? WHERE campaign_id = ?`, nudgeCount, campaignID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save nudge"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save nudge"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		Actor      string `json:"actor"`
		Target     string `json:"target"`
		Message    string `json:"message"`
		NudgeCount int    `json:"nudge_count"`
	}{actor.Username, target, request.Message, nudgeCount})
}

// getMyPlayCampaignTurn provides a player with their own minimal turn context.
// It intentionally projects neither other members' character records nor any
// DM-only fields: the only events exposed are public narrations.
func getMyPlayCampaignTurn(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	if actor.Role != "player" {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}

	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	var exists int
	err := db.QueryRow(`SELECT 1 FROM play_campaigns WHERE id = ?`, campaignID).Scan(&exists)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}

	type playerCharacter struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	var character playerCharacter
	err = db.QueryRow(`SELECT character_id, name FROM play_campaign_members WHERE campaign_id = ? AND username = ?`, campaignID, actor.Username).Scan(&character.ID, &character.Name)
	if errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}

	var currentActor string
	if err = db.QueryRow(playCampaignMemberOrder+` LIMIT 1`, campaignID).Scan(&currentActor); err != nil && !errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}
	if err = db.QueryRow(`SELECT current_actor FROM play_campaign_turns WHERE campaign_id = ?`, campaignID).Scan(&currentActor); err != nil && !errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}

	type publicEvent struct {
		Sequence int    `json:"sequence"`
		Kind     string `json:"kind"`
		Actor    string `json:"actor"`
		Text     string `json:"text"`
	}
	// Narration creation assigns each campaign a stable sequence, which is also
	// the public event ordering exposed to players here.
	rows, err := db.Query(`SELECT sequence, text FROM play_campaign_narrations WHERE campaign_id = ? ORDER BY sequence`, campaignID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}
	defer rows.Close()
	events := make([]publicEvent, 0)
	for rows.Next() {
		var event publicEvent
		if err := rows.Scan(&event.Sequence, &event.Text); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
			return
		}
		event.Kind = "narration"
		event.Actor = "dm"
		events = append(events, event)
	}
	if err := rows.Err(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}

	writeJSON(w, http.StatusOK, struct {
		IsMyTurn     bool            `json:"is_my_turn"`
		CurrentActor string          `json:"current_actor"`
		Character    playerCharacter `json:"character"`
		RecentEvents []publicEvent   `json:"recent_events"`
	}{actor.Username == currentActor, currentActor, character, events})
}

// getGMPlayCampaignStatus gives a campaign owner the complete, compact view
// of the current exploration turn. Unlike the player context, this view may
// include every party member's public character summary.
func getGMPlayCampaignStatus(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}

	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	var owner string
	err := db.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}
	if actor.Username != owner {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}

	type partyMember struct {
		Username    string `json:"username"`
		CharacterID string `json:"character_id"`
		Name        string `json:"name"`
		Class       string `json:"class"`
	}
	rows, err := db.Query(`SELECT username, character_id, name, class FROM play_campaign_members WHERE campaign_id = ? ORDER BY CASE WHEN join_order > 0 THEN 0 ELSE 1 END, join_order, username`, campaignID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}
	defer rows.Close()
	party := make([]partyMember, 0)
	for rows.Next() {
		var member partyMember
		if err := rows.Scan(&member.Username, &member.CharacterID, &member.Name, &member.Class); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
			return
		}
		party = append(party, member)
	}
	if err := rows.Err(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}

	currentActor := ""
	if len(party) > 0 {
		currentActor = party[0].Username
	}
	if err = db.QueryRow(`SELECT current_actor FROM play_campaign_turns WHERE campaign_id = ?`, campaignID).Scan(&currentActor); err != nil && !errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}
	type publicEvent struct {
		Sequence int    `json:"sequence"`
		Kind     string `json:"kind"`
		Actor    string `json:"actor"`
		Text     string `json:"text"`
	}
	eventRows, err := db.Query(`SELECT sequence, text FROM play_campaign_narrations WHERE campaign_id = ? ORDER BY sequence`, campaignID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}
	defer eventRows.Close()
	events := make([]publicEvent, 0)
	for eventRows.Next() {
		var event publicEvent
		if err := eventRows.Scan(&event.Sequence, &event.Text); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
			return
		}
		event.Kind = "narration"
		event.Actor = "dm"
		events = append(events, event)
	}
	if err := eventRows.Err(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to read campaign"})
		return
	}

	writeJSON(w, http.StatusOK, struct {
		NeedsAttention bool          `json:"needs_attention"`
		CurrentActor   string        `json:"current_actor"`
		Party          []partyMember `json:"party"`
		RecentEvents   []publicEvent `json:"recent_events"`
	}{currentActor == owner, currentActor, party, events})
}

func hashPassword(password string) ([]byte, []byte, error) {
	salt := make([]byte, 16)
	if _, err := rand.Read(salt); err != nil {
		return nil, nil, err
	}
	hash, err := pbkdf2.Key(sha256.New, password, salt, 100_000, 32)
	if err != nil {
		return nil, nil, err
	}
	return salt, hash, nil
}

func passwordMatches(password string, salt, expectedHash []byte) bool {
	hash, err := pbkdf2.Key(sha256.New, password, salt, 100_000, len(expectedHash))
	return err == nil && subtle.ConstantTimeCompare(hash, expectedHash) == 1
}

func diceStats(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Expression string `json:"expression"`
	}
	if !decodeJSON(r, &request) {
		badRequest(w, "invalid request")
		return
	}
	matches := diceExpression.FindStringSubmatch(request.Expression)
	if matches == nil {
		badRequest(w, "invalid dice expression")
		return
	}
	count, err1 := strconv.Atoi(matches[1])
	sides, err2 := strconv.Atoi(matches[2])
	modifier := 0
	var err3 error
	if matches[3] != "" {
		modifier, err3 = strconv.Atoi(matches[3])
	}
	if err1 != nil || err2 != nil || err3 != nil || count < 1 || sides < 1 {
		badRequest(w, "invalid dice expression")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"dice_count": count, "sides": sides, "modifier": modifier,
		"min": count + modifier, "max": count*sides + modifier,
		"average": float64(count*(sides+1))/2 + float64(modifier),
	})
}

func abilityCheck(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Roll     int `json:"roll"`
		Modifier int `json:"modifier"`
		DC       int `json:"dc"`
	}
	if !decodeJSON(r, &request) {
		badRequest(w, "invalid request")
		return
	}
	total := request.Roll + request.Modifier
	writeJSON(w, http.StatusOK, map[string]any{"total": total, "success": total >= request.DC, "margin": total - request.DC})
}

func abilityModifier(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Score int `json:"score"`
	}
	if !decodeJSON(r, &request) || !validAbilityScore(request.Score) {
		badRequest(w, "invalid ability score")
		return
	}
	writeJSON(w, http.StatusOK, map[string]int{
		"score": request.Score, "modifier": modifierFor(request.Score),
	})
}

func proficiency(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Level int `json:"level"`
	}
	if !decodeJSON(r, &request) || !validLevel(request.Level) {
		badRequest(w, "invalid level")
		return
	}
	writeJSON(w, http.StatusOK, map[string]int{
		"level": request.Level, "proficiency_bonus": proficiencyFor(request.Level),
	})
}

func spellSlots(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Class string `json:"class"`
		Level int    `json:"level"`
	}
	if !decodeJSON(r, &request) || request.Class != "wizard" || request.Level != 5 {
		badRequest(w, "unsupported class or level")
		return
	}
	writeJSON(w, http.StatusOK, struct {
		Class string         `json:"class"`
		Level int            `json:"level"`
		Slots map[string]int `json:"slots"`
	}{Class: request.Class, Level: request.Level, Slots: map[string]int{"1": 4, "2": 3, "3": 2}})
}

func longRest(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Level           int `json:"level"`
		HPCurrent       int `json:"hp_current"`
		HPMax           int `json:"hp_max"`
		HitDiceSpent    int `json:"hit_dice_spent"`
		ExhaustionLevel int `json:"exhaustion_level"`
	}
	if !decodeJSON(r, &request) || !validLevel(request.Level) || request.HPMax < 1 || request.HPCurrent < 0 || request.HPCurrent > request.HPMax || request.HitDiceSpent < 0 || request.HitDiceSpent > request.Level || request.ExhaustionLevel < 0 {
		badRequest(w, "invalid rest request")
		return
	}
	restoredHitDice := max(1, request.Level/2)
	remainingSpent := max(0, request.HitDiceSpent-restoredHitDice)
	writeJSON(w, http.StatusOK, struct {
		HPCurrent       int `json:"hp_current"`
		HitDiceSpent    int `json:"hit_dice_spent"`
		ExhaustionLevel int `json:"exhaustion_level"`
	}{HPCurrent: request.HPMax, HitDiceSpent: remainingSpent, ExhaustionLevel: max(0, request.ExhaustionLevel-1)})
}

func equipmentLoad(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Strength int `json:"strength"`
		Weight   int `json:"weight"`
	}
	if !decodeJSON(r, &request) || !validAbilityScore(request.Strength) || request.Weight < 0 {
		badRequest(w, "invalid equipment load request")
		return
	}
	capacity := request.Strength * 15
	writeJSON(w, http.StatusOK, struct {
		Capacity   int  `json:"capacity"`
		Weight     int  `json:"weight"`
		Encumbered bool `json:"encumbered"`
	}{Capacity: capacity, Weight: request.Weight, Encumbered: request.Weight > capacity})
}

func derivedStats(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Level     int `json:"level"`
		Abilities struct {
			STR int `json:"str"`
			DEX int `json:"dex"`
			CON int `json:"con"`
			INT int `json:"int"`
			WIS int `json:"wis"`
			CHA int `json:"cha"`
		} `json:"abilities"`
		Armor struct {
			Base   int  `json:"base"`
			Shield bool `json:"shield"`
			DexCap int  `json:"dex_cap"`
		} `json:"armor"`
	}
	if !decodeJSON(r, &request) || !validLevel(request.Level) {
		badRequest(w, "invalid request")
		return
	}
	modifiers := map[string]int{
		"str": modifierFor(request.Abilities.STR),
		"dex": modifierFor(request.Abilities.DEX),
		"con": modifierFor(request.Abilities.CON),
		"int": modifierFor(request.Abilities.INT),
		"wis": modifierFor(request.Abilities.WIS),
		"cha": modifierFor(request.Abilities.CHA),
	}
	for _, score := range []int{request.Abilities.STR, request.Abilities.DEX, request.Abilities.CON, request.Abilities.INT, request.Abilities.WIS, request.Abilities.CHA} {
		if !validAbilityScore(score) {
			badRequest(w, "invalid ability score")
			return
		}
	}
	shieldBonus := 0
	if request.Armor.Shield {
		shieldBonus = 2
	}
	dexBonus := modifiers["dex"]
	if dexBonus > request.Armor.DexCap {
		dexBonus = request.Armor.DexCap
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"level":             request.Level,
		"proficiency_bonus": proficiencyFor(request.Level),
		"hp_max":            request.Level * (6 + modifiers["con"]),
		"armor_class":       request.Armor.Base + dexBonus + shieldBonus,
		"modifiers":         modifiers,
	})
}

func validAbilityScore(score int) bool {
	return score >= 1 && score <= 30
}

func validLevel(level int) bool {
	return level >= 1 && level <= 20
}

func modifierFor(score int) int {
	// Go integer division truncates toward zero, so adjust negative odd values
	// to implement the floor required by the D&D rule.
	delta := score - 10
	if delta < 0 && delta%2 != 0 {
		return delta/2 - 1
	}
	return delta / 2
}

func proficiencyFor(level int) int {
	return 2 + (level-1)/4
}

func adjustedXP(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Party []struct {
			Level int `json:"level"`
		} `json:"party"`
		Monsters []encounterMonster `json:"monsters"`
	}
	if !decodeJSON(r, &request) || len(request.Party) == 0 || len(request.Monsters) == 0 {
		badRequest(w, "invalid request")
		return
	}
	base, adjusted, monsterCount, difficulty, ok := calculateAdjustedXP(request.Party, request.Monsters)
	if !ok {
		badRequest(w, "unsupported encounter")
		return
	}
	thresholds := map[string]int{"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
	for range request.Party {
		thresholds["easy"] += 75
		thresholds["medium"] += 150
		thresholds["hard"] += 225
		thresholds["deadly"] += 400
	}
	writeJSON(w, http.StatusOK, map[string]any{"base_xp": base, "monster_count": monsterCount, "multiplier": encounterMultiplier(monsterCount), "adjusted_xp": adjusted, "difficulty": difficulty, "thresholds": thresholds})
}

type encounterMonster struct {
	CR    string `json:"cr"`
	Count int    `json:"count"`
}

func calculateAdjustedXP(party []struct {
	Level int `json:"level"`
}, monsters []encounterMonster) (base, adjusted, monsterCount int, difficulty string, ok bool) {
	xpByCR := map[string]int{"0": 10, "1/8": 25, "1/4": 50, "1/2": 100, "1": 200, "2": 450, "3": 700, "4": 1100, "5": 1800}
	for _, monster := range monsters {
		xp, known := xpByCR[monster.CR]
		if !known || monster.Count < 1 {
			return 0, 0, 0, "", false
		}
		base += xp * monster.Count
		monsterCount += monster.Count
	}
	thresholds := map[string]int{"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
	for _, member := range party {
		if member.Level != 3 {
			return 0, 0, 0, "", false
		}
		thresholds["easy"] += 75
		thresholds["medium"] += 150
		thresholds["hard"] += 225
		thresholds["deadly"] += 400
	}
	adjusted = int(float64(base) * encounterMultiplier(monsterCount))
	difficulty = "trivial"
	for _, level := range []string{"easy", "medium", "hard", "deadly"} {
		if adjusted >= thresholds[level] {
			difficulty = level
		}
	}
	return base, adjusted, monsterCount, difficulty, true
}

func encounterMultiplier(count int) float64 {
	switch {
	case count == 1:
		return 1
	case count == 2:
		return 1.5
	case count <= 6:
		return 2
	case count <= 10:
		return 2.5
	case count <= 14:
		return 3
	default:
		return 4
	}
}

func initiativeOrder(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Combatants []struct {
			Name string `json:"name"`
			Dex  int    `json:"dex"`
			Roll int    `json:"roll"`
		} `json:"combatants"`
	}
	if !decodeJSON(r, &request) {
		badRequest(w, "invalid request")
		return
	}
	type result struct {
		Name  string `json:"name"`
		Score int    `json:"score"`
		dex   int
	}
	order := make([]result, len(request.Combatants))
	for i, combatant := range request.Combatants {
		order[i] = result{combatant.Name, combatant.Roll + combatant.Dex, combatant.Dex}
	}
	sort.SliceStable(order, func(i, j int) bool {
		if order[i].Score != order[j].Score {
			return order[i].Score > order[j].Score
		}
		if order[i].dex != order[j].dex {
			return order[i].dex > order[j].dex
		}
		return order[i].Name < order[j].Name
	})
	writeJSON(w, http.StatusOK, map[string]any{"order": order})
}

func createCombatSession(w http.ResponseWriter, r *http.Request) {
	var request struct {
		ID         string `json:"id"`
		Combatants []struct {
			Name string `json:"name"`
			Dex  int    `json:"dex"`
			Roll int    `json:"roll"`
		} `json:"combatants"`
	}
	if !decodeJSON(r, &request) || request.ID == "" || len(request.Combatants) == 0 {
		badRequest(w, "invalid request")
		return
	}

	order := make([]combatant, len(request.Combatants))
	names := make(map[string]bool, len(request.Combatants))
	for i, entry := range request.Combatants {
		if entry.Name == "" || names[entry.Name] {
			badRequest(w, "invalid combatants")
			return
		}
		names[entry.Name] = true
		order[i] = combatant{Name: entry.Name, Score: entry.Roll + entry.Dex, dex: entry.Dex}
	}
	sort.Slice(order, func(i, j int) bool {
		if order[i].Score != order[j].Score {
			return order[i].Score > order[j].Score
		}
		if order[i].dex != order[j].dex {
			return order[i].dex > order[j].dex
		}
		return order[i].Name < order[j].Name
	})

	sessions.Lock()
	defer sessions.Unlock()
	if _, exists := sessions.sessions[request.ID]; exists {
		badRequest(w, "session already exists")
		return
	}
	session := &combatSession{ID: request.ID, Round: 1, Order: order, Conditions: make(map[string][]condition)}
	sessions.sessions[request.ID] = session
	if err := persistSession(session); err != nil {
		delete(sessions.sessions, request.ID)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save session"})
		return
	}
	writeCombatSessionCreated(w, session)
}

func addCondition(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Target         string `json:"target"`
		Condition      string `json:"condition"`
		DurationRounds int    `json:"duration_rounds"`
	}
	if !decodeJSON(r, &request) || request.Target == "" || request.DurationRounds < 1 {
		badRequest(w, "invalid request")
		return
	}

	sessions.Lock()
	defer sessions.Unlock()
	session, ok := sessions.sessions[r.PathValue("id")]
	if !ok {
		notFound(w, "unknown session")
		return
	}
	if !session.hasCombatant(request.Target) {
		badRequest(w, "unknown combatant")
		return
	}
	session.Conditions[request.Target] = append(session.Conditions[request.Target], condition{
		Condition: request.Condition, RemainingRounds: request.DurationRounds,
	})
	if err := persistSession(session); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save condition"})
		return
	}
	writeJSON(w, http.StatusOK, struct {
		Target     string      `json:"target"`
		Conditions []condition `json:"conditions"`
	}{request.Target, session.Conditions[request.Target]})
}

func advanceTurn(w http.ResponseWriter, r *http.Request) {
	sessions.Lock()
	defer sessions.Unlock()
	session, ok := sessions.sessions[r.PathValue("id")]
	if !ok {
		notFound(w, "unknown session")
		return
	}

	session.TurnIndex++
	if session.TurnIndex == len(session.Order) {
		session.TurnIndex = 0
		session.Round++
	}
	active := session.Order[session.TurnIndex].Name
	if attached := session.Conditions[active]; len(attached) > 0 {
		remaining := attached[:0]
		for _, current := range attached {
			current.RemainingRounds--
			if current.RemainingRounds > 0 {
				remaining = append(remaining, current)
			}
		}
		if len(remaining) == 0 {
			// Preserve the combatant in the response after its final condition
			// expires. Consumers can then distinguish "no conditions" from an
			// omitted combatant entry deterministically.
			session.Conditions[active] = []condition{}
		} else {
			session.Conditions[active] = remaining
		}
	}
	if err := persistSession(session); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save session"})
		return
	}
	writeCombatAdvance(w, session)
}

// submitPlayCampaignCombatAction records a player combatant's declared action.
// Unlike exploration actions, combat actions do not change turn ownership; the
// player or campaign owner explicitly advances the encounter afterward.
func submitPlayCampaignCombatAction(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		Type   string `json:"type"`
		Target string `json:"target"`
		Text   string `json:"text"`
	}
	if !decodeJSON(r, &request) {
		badRequest(w, "invalid combat action")
		return
	}
	validType := request.Type == "attack" || request.Type == "help" || request.Type == "dodge" || request.Type == "ready"
	if !validType || !validCampaignText(request.Target) || !validCampaignText(request.Text) {
		badRequest(w, "invalid combat action")
		return
	}

	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID, encounterID := r.PathValue("id"), r.PathValue("enc_id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save combat action"})
		return
	}
	defer tx.Rollback()

	var status string
	err = tx.QueryRow(`SELECT status FROM play_campaigns WHERE id = ?`, campaignID).Scan(&status)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save combat action"})
		return
	}
	var round, turnIndex int
	err = tx.QueryRow(`SELECT round, turn_index FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?`, campaignID, encounterID).Scan(&round, &turnIndex)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown encounter")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save combat action"})
		return
	}
	order, err := encounterTurnOrder(tx, campaignID, encounterID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save combat action"})
		return
	}
	if status != "combat" || len(order) == 0 || actor.Role != "player" {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "out of turn"})
		return
	}
	active := order[turnIndex%len(order)]
	if active.Kind != "player" || active.member != actor.Username {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "out of turn"})
		return
	}

	sequence, err := nextPlayEventSequence(tx, campaignID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save combat action"})
		return
	}
	if _, err = tx.Exec(`INSERT INTO play_campaign_combat_actions(campaign_id, encounter_id, sequence, actor, type, target, text) VALUES (?, ?, ?, ?, ?, ?, ?)`, campaignID, encounterID, sequence, actor.Username, request.Type, request.Target, request.Text); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save combat action"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save combat action"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		Sequence int    `json:"sequence"`
		Kind     string `json:"kind"`
		Actor    string `json:"actor"`
		Type     string `json:"type"`
		Target   string `json:"target"`
		Text     string `json:"text"`
	}{sequence, "combat_action", actor.Username, request.Type, request.Target, request.Text})
}

// submitPlayAction records the active player's declared action, then hands the
// exploration turn to the DM. Turn state is stored separately from the event
// log so reads remain cheap and legacy active campaigns still have a sensible
// first-player fallback.
func submitPlayAction(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		Type string `json:"type"`
		Text string `json:"text"`
	}
	if !decodeJSON(r, &request) || request.Type != "search" || !validCampaignText(request.Text) {
		badRequest(w, "invalid action")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save action"})
		return
	}
	defer tx.Rollback()
	var owner, status string
	err = tx.QueryRow(`SELECT owner, status FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner, &status)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save action"})
		return
	}
	var currentActor string
	err = tx.QueryRow(`SELECT current_actor FROM play_campaign_turns WHERE campaign_id = ?`, campaignID).Scan(&currentActor)
	if errors.Is(err, sql.ErrNoRows) {
		err = tx.QueryRow(playCampaignMemberOrder+` LIMIT 1`, campaignID).Scan(&currentActor)
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save action"})
		return
	}
	if status != "active" || actor.Role != "player" || actor.Username != currentActor {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "not the active player"})
		return
	}
	var member int
	if err = tx.QueryRow(`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?`, campaignID, actor.Username).Scan(&member); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "not the active player"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save action"})
		return
	}
	sequence, err := nextPlayEventSequence(tx, campaignID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save action"})
		return
	}
	if _, err = tx.Exec(`INSERT INTO play_campaign_actions(campaign_id, sequence, actor, type, text) VALUES (?, ?, ?, ?, ?)`, campaignID, sequence, actor.Username, request.Type, request.Text); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save action"})
		return
	}
	if _, err = tx.Exec(`INSERT INTO play_campaign_turns(campaign_id, current_actor) VALUES (?, ?) ON CONFLICT(campaign_id) DO UPDATE SET current_actor = excluded.current_actor`, campaignID, owner); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save action"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save action"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		Sequence  int    `json:"sequence"`
		Kind      string `json:"kind"`
		Actor     string `json:"actor"`
		Type      string `json:"type"`
		Text      string `json:"text"`
		NextActor string `json:"next_actor"`
	}{sequence, "action", actor.Username, request.Type, request.Text, owner})
}

// travelPlayCampaignTurn lets the active player spend their exploration turn
// on a directed edge from the party's current location. A travel is an event,
// not a scene transition: scene state and the location graph are untouched.
func travelPlayCampaignTurn(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		DestinationID string `json:"destination_id"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.DestinationID) {
		badRequest(w, "invalid destination")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to travel"})
		return
	}
	defer tx.Rollback()

	var owner, status, currentActor string
	err = tx.QueryRow(`SELECT owner, status FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner, &status)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to travel"})
		return
	}
	err = tx.QueryRow(`SELECT current_actor FROM play_campaign_turns WHERE campaign_id = ?`, campaignID).Scan(&currentActor)
	if errors.Is(err, sql.ErrNoRows) {
		err = tx.QueryRow(playCampaignMemberOrder+` LIMIT 1`, campaignID).Scan(&currentActor)
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to travel"})
		return
	}
	if status != "active" || actor.Role != "player" || actor.Username != currentActor {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "not the active player"})
		return
	}
	var member int
	if err = tx.QueryRow(`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?`, campaignID, actor.Username).Scan(&member); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "not the active player"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to travel"})
		return
	}
	var locationID string
	err = tx.QueryRow(`SELECT location_id FROM play_campaign_party_locations WHERE campaign_id = ?`, campaignID).Scan(&locationID)
	if errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "invalid destination"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to travel"})
		return
	}
	var travelTurns int
	err = tx.QueryRow(`SELECT travel_turns FROM play_campaign_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?`, campaignID, locationID, request.DestinationID).Scan(&travelTurns)
	if errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "invalid destination"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to travel"})
		return
	}
	sequence, err := nextPlayEventSequence(tx, campaignID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to travel"})
		return
	}
	if _, err = tx.Exec(`INSERT INTO play_campaign_travels(campaign_id, sequence, actor, destination_id, travel_turns) VALUES (?, ?, ?, ?, ?)`, campaignID, sequence, actor.Username, request.DestinationID, travelTurns); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to travel"})
		return
	}
	if _, err = tx.Exec(`UPDATE play_campaign_party_locations SET location_id = ? WHERE campaign_id = ?`, request.DestinationID, campaignID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to travel"})
		return
	}
	if _, err = tx.Exec(`INSERT INTO play_campaign_turns(campaign_id, current_actor) VALUES (?, ?) ON CONFLICT(campaign_id) DO UPDATE SET current_actor = excluded.current_actor`, campaignID, owner); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to travel"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to travel"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		Sequence      int    `json:"sequence"`
		Kind          string `json:"kind"`
		Actor         string `json:"actor"`
		DestinationID string `json:"destination_id"`
		TravelTurns   int    `json:"travel_turns"`
		NextActor     string `json:"next_actor"`
	}{sequence, "travel", actor.Username, request.DestinationID, travelTurns, owner})
}

// restPlayCampaignTurn lets the active player spend an exploration turn
// resting. A long rest restores the actor's durable hit points; a short rest
// records the turn without changing them.
func restPlayCampaignTurn(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		Type string `json:"type"`
	}
	if !decodeJSON(r, &request) || (request.Type != "short" && request.Type != "long") {
		badRequest(w, "invalid rest")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to rest"})
		return
	}
	defer tx.Rollback()

	var owner, status, currentActor string
	err = tx.QueryRow(`SELECT owner, status FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner, &status)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to rest"})
		return
	}
	err = tx.QueryRow(`SELECT current_actor FROM play_campaign_turns WHERE campaign_id = ?`, campaignID).Scan(&currentActor)
	if errors.Is(err, sql.ErrNoRows) {
		err = tx.QueryRow(playCampaignMemberOrder+` LIMIT 1`, campaignID).Scan(&currentActor)
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to rest"})
		return
	}
	if status != "active" || actor.Role != "player" || actor.Username != currentActor {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "not the active player"})
		return
	}
	var hpCurrent, hpMax int
	err = tx.QueryRow(`SELECT hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? AND username = ?`, campaignID, actor.Username).Scan(&hpCurrent, &hpMax)
	if errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "not the active player"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to rest"})
		return
	}
	if request.Type == "long" {
		hpCurrent = hpMax
		if _, err = tx.Exec(`UPDATE play_campaign_members SET hp_current = ?, death_save_successes = 0, death_save_failures = 0, status = 'conscious' WHERE campaign_id = ? AND username = ?`, hpCurrent, campaignID, actor.Username); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to rest"})
			return
		}
	}
	sequence, err := nextPlayEventSequence(tx, campaignID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to rest"})
		return
	}
	if _, err = tx.Exec(`INSERT INTO play_campaign_rests(campaign_id, sequence, actor, type, hp_current, hp_max) VALUES (?, ?, ?, ?, ?, ?)`, campaignID, sequence, actor.Username, request.Type, hpCurrent, hpMax); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to rest"})
		return
	}
	if _, err = tx.Exec(`INSERT INTO play_campaign_turns(campaign_id, current_actor) VALUES (?, ?) ON CONFLICT(campaign_id) DO UPDATE SET current_actor = excluded.current_actor`, campaignID, owner); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to rest"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to rest"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		Sequence  int    `json:"sequence"`
		Kind      string `json:"kind"`
		Actor     string `json:"actor"`
		Type      string `json:"type"`
		HPCurrent int    `json:"hp_current"`
		HPMax     int    `json:"hp_max"`
		NextActor string `json:"next_actor"`
	}{sequence, "rest", actor.Username, request.Type, hpCurrent, hpMax, owner})
}

// submitPlayResolution records the owner's response to the active player's
// action and advances the exploration queue to the next enrolled player.
func submitPlayResolution(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	var request struct {
		Text string `json:"text"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.Text) {
		badRequest(w, "invalid resolution")
		return
	}
	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save resolution"})
		return
	}
	defer tx.Rollback()

	var owner, status, currentActor string
	var turnNumber int
	err = tx.QueryRow(`SELECT owner, status FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner, &status)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save resolution"})
		return
	}
	err = tx.QueryRow(`SELECT current_actor, turn_number FROM play_campaign_turns WHERE campaign_id = ?`, campaignID).Scan(&currentActor, &turnNumber)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "not the active owner"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save resolution"})
		return
	}
	if status != "active" || actor.Username != owner || currentActor != owner {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "not the active owner"})
		return
	}

	rows, err := tx.Query(playCampaignMemberOrder, campaignID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save resolution"})
		return
	}
	players := make([]string, 0)
	for rows.Next() {
		var username string
		if err := rows.Scan(&username); err != nil {
			rows.Close()
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save resolution"})
			return
		}
		players = append(players, username)
	}
	if err := rows.Close(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save resolution"})
		return
	}
	if len(players) == 0 {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "not the active owner"})
		return
	}
	nextActor := players[0]
	var previousActor string
	// An exploration turn may be an action, travel, or rest. Resolving after
	// any of them must advance from the player who just handed control to the
	// DM, rather than from an older action event.
	err = tx.QueryRow(`SELECT actor FROM (
		SELECT sequence, actor FROM play_campaign_actions WHERE campaign_id = ?
		UNION ALL SELECT sequence, actor FROM play_campaign_travels WHERE campaign_id = ?
		UNION ALL SELECT sequence, actor FROM play_campaign_rests WHERE campaign_id = ?
	) ORDER BY sequence DESC LIMIT 1`, campaignID, campaignID, campaignID).Scan(&previousActor)
	if err == nil {
		for i, username := range players {
			if username == previousActor {
				nextActor = players[(i+1)%len(players)]
				break
			}
		}
	} else if !errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save resolution"})
		return
	} else if len(players) > 1 {
		nextActor = players[1]
	}
	sequence, err := nextPlayEventSequence(tx, campaignID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save resolution"})
		return
	}
	if _, err = tx.Exec(`INSERT INTO play_campaign_resolutions(campaign_id, sequence, actor, text) VALUES (?, ?, ?, ?)`, campaignID, sequence, actor.Username, request.Text); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save resolution"})
		return
	}
	turnNumber++
	if _, err = tx.Exec(`UPDATE play_campaign_turns SET current_actor = ?, turn_number = ? WHERE campaign_id = ?`, nextActor, turnNumber, campaignID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save resolution"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save resolution"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		Sequence   int    `json:"sequence"`
		Kind       string `json:"kind"`
		Actor      string `json:"actor"`
		Text       string `json:"text"`
		NextActor  string `json:"next_actor"`
		TurnNumber int    `json:"turn_number"`
	}{sequence, "resolution", actor.Username, request.Text, nextActor, turnNumber})
}

// nextPlayEventSequence advances the campaign's durable event cursor. The
// initialization query keeps databases created before the cursor migration in
// sequence with their existing narration, action, resolution, travel, rest,
// and combat-action rows.
func nextPlayEventSequence(tx *sql.Tx, campaignID string) (int, error) {
	if _, err := tx.Exec(`INSERT OR IGNORE INTO play_campaign_event_sequences(campaign_id, sequence) SELECT ?, COALESCE(MAX(sequence), 0) FROM (SELECT sequence FROM play_campaign_narrations WHERE campaign_id = ? UNION ALL SELECT sequence FROM play_campaign_actions WHERE campaign_id = ? UNION ALL SELECT sequence FROM play_campaign_resolutions WHERE campaign_id = ? UNION ALL SELECT sequence FROM play_campaign_travels WHERE campaign_id = ? UNION ALL SELECT sequence FROM play_campaign_rests WHERE campaign_id = ? UNION ALL SELECT sequence FROM play_campaign_combat_actions WHERE campaign_id = ?)`, campaignID, campaignID, campaignID, campaignID, campaignID, campaignID, campaignID); err != nil {
		return 0, err
	}
	var sequence int
	if err := tx.QueryRow(`UPDATE play_campaign_event_sequences SET sequence = sequence + 1 WHERE campaign_id = ? RETURNING sequence`, campaignID).Scan(&sequence); err != nil {
		return 0, err
	}
	return sequence, nil
}

// appendNarration records an immutable, campaign-local event. Sequence is
// assigned inside the write transaction so each campaign's log begins at one
// and remains ordered even when requests overlap.
func appendNarration(w http.ResponseWriter, r *http.Request) {
	actor, authenticated := authenticatedUser(r)
	if !authenticated {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	if actor.Role != "dm" {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}

	var request struct {
		Text string `json:"text"`
	}
	if !decodeJSON(r, &request) || !validCampaignText(request.Text) {
		badRequest(w, "invalid narration")
		return
	}

	db := currentDB()
	if db == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "storage unavailable"})
		return
	}
	campaignID := r.PathValue("id")
	tx, err := db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save narration"})
		return
	}
	defer tx.Rollback()

	var owner string
	err = tx.QueryRow(`SELECT owner FROM play_campaigns WHERE id = ?`, campaignID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		notFound(w, "unknown campaign")
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save narration"})
		return
	}
	if owner != actor.Username {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}

	sequence, err := nextPlayEventSequence(tx, campaignID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save narration"})
		return
	}
	if _, err = tx.Exec(`INSERT INTO play_campaign_narrations(campaign_id, sequence, text) VALUES (?, ?, ?)`, campaignID, sequence, request.Text); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save narration"})
		return
	}
	if err = tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "unable to save narration"})
		return
	}
	writeJSON(w, http.StatusCreated, struct {
		Sequence int    `json:"sequence"`
		Kind     string `json:"kind"`
		Actor    string `json:"actor"`
		Text     string `json:"text"`
	}{sequence, "narration", "dm", request.Text})
}

func (session *combatSession) hasCombatant(name string) bool {
	for _, entry := range session.Order {
		if entry.Name == name {
			return true
		}
	}
	return false
}

func writeCombatSessionCreated(w http.ResponseWriter, session *combatSession) {
	writeJSON(w, http.StatusOK, struct {
		ID        string      `json:"id"`
		Round     int         `json:"round"`
		TurnIndex int         `json:"turn_index"`
		Active    combatant   `json:"active"`
		Order     []combatant `json:"order"`
	}{
		ID: session.ID, Round: session.Round, TurnIndex: session.TurnIndex,
		Active: session.Order[session.TurnIndex], Order: session.Order,
	})
}

func writeCombatAdvance(w http.ResponseWriter, session *combatSession) {
	writeJSON(w, http.StatusOK, struct {
		ID         string                 `json:"id"`
		Round      int                    `json:"round"`
		TurnIndex  int                    `json:"turn_index"`
		Active     combatant              `json:"active"`
		Conditions map[string][]condition `json:"conditions"`
	}{
		ID: session.ID, Round: session.Round, TurnIndex: session.TurnIndex,
		Active: session.Order[session.TurnIndex], Conditions: session.Conditions,
	})
}

func decodeJSON(r *http.Request, target any) bool {
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if decoder.Decode(target) != nil {
		return false
	}
	return decoder.Decode(&struct{}{}) == io.EOF
}

func badRequest(w http.ResponseWriter, message string) {
	writeJSON(w, http.StatusBadRequest, map[string]string{"error": message})
}

func notFound(w http.ResponseWriter, message string) {
	writeJSON(w, http.StatusNotFound, map[string]string{"error": message})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
