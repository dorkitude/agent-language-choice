package main

import (
	"database/sql"
	"encoding/json"
	"log"
	"os"
	"strings"
	"sync"

	_ "modernc.org/sqlite"
)

const dbPath = "game.db"
const schemaVersion = 1

var (
	db          *sql.DB
	storageOnce sync.Once
	initialized bool
)

// removeDBFiles wipes any sqlite database file (plus its WAL/SHM sidecars)
// left behind by a previous process, so every server run starts from a
// clean, deterministic state instead of inheriting stale test data.
func removeDBFiles() {
	for _, suffix := range []string{"", "-shm", "-wal"} {
		_ = os.Remove(dbPath + suffix)
	}
}

func openDB() *sql.DB {
	removeDBFiles()
	conn, err := sql.Open("sqlite", dbPath)
	if err != nil {
		log.Fatalf("failed to open sqlite database: %v", err)
	}
	// The pure-Go sqlite driver only allows one writer at a time; pinning
	// database/sql to a single underlying connection serializes all access
	// through it instead of racing multiple connections against the same
	// file, which is a known source of flaky failures under concurrent load.
	conn.SetMaxOpenConns(1)
	if err := conn.Ping(); err != nil {
		log.Fatalf("failed to connect to sqlite database: %v", err)
	}
	return conn
}

func createSchema(conn *sql.DB) {
	statements := []string{
		`CREATE TABLE IF NOT EXISTS storage_meta (
			key TEXT PRIMARY KEY,
			value TEXT NOT NULL
		)`,
		`CREATE TABLE IF NOT EXISTS users (
			username TEXT PRIMARY KEY,
			role TEXT NOT NULL,
			password_hash TEXT NOT NULL
		)`,
		`CREATE TABLE IF NOT EXISTS combat_sessions (
			id TEXT PRIMARY KEY,
			data TEXT NOT NULL
		)`,
		`CREATE TABLE IF NOT EXISTS monsters (
			slug TEXT PRIMARY KEY,
			name TEXT NOT NULL,
			cr TEXT NOT NULL,
			armor_class INTEGER NOT NULL,
			hit_points INTEGER NOT NULL,
			tags TEXT NOT NULL
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
		`CREATE TABLE IF NOT EXISTS campaign_characters (
			campaign_id TEXT NOT NULL,
			id TEXT NOT NULL,
			name TEXT NOT NULL,
			level INTEGER NOT NULL,
			class TEXT NOT NULL,
			PRIMARY KEY (campaign_id, id)
		)`,
		`CREATE TABLE IF NOT EXISTS campaign_events (
			campaign_id TEXT NOT NULL,
			id TEXT NOT NULL,
			kind TEXT NOT NULL,
			summary TEXT NOT NULL,
			PRIMARY KEY (campaign_id, id)
		)`,
		`CREATE TABLE IF NOT EXISTS campaign_quests (
			campaign_id TEXT NOT NULL,
			id TEXT NOT NULL,
			title TEXT NOT NULL,
			status TEXT NOT NULL,
			milestones TEXT NOT NULL,
			done TEXT NOT NULL,
			PRIMARY KEY (campaign_id, id)
		)`,
		`CREATE TABLE IF NOT EXISTS campaign_factions (
			campaign_id TEXT NOT NULL,
			id TEXT NOT NULL,
			name TEXT NOT NULL,
			stance TEXT NOT NULL,
			PRIMARY KEY (campaign_id, id)
		)`,
		`CREATE TABLE IF NOT EXISTS campaign_npcs (
			campaign_id TEXT NOT NULL,
			id TEXT NOT NULL,
			name TEXT NOT NULL,
			faction_id TEXT NOT NULL,
			disposition INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, id)
		)`,
		`CREATE TABLE IF NOT EXISTS campaign_inventory (
			campaign_id TEXT NOT NULL,
			item_slug TEXT NOT NULL,
			owner TEXT NOT NULL,
			quantity INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, item_slug, owner)
		)`,
		`CREATE TABLE IF NOT EXISTS campaign_equipment (
			campaign_id TEXT NOT NULL,
			character_id TEXT NOT NULL,
			item_slug TEXT NOT NULL,
			quantity INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, character_id, item_slug)
		)`,
		`CREATE TABLE IF NOT EXISTS campaign_crafting_projects (
			campaign_id TEXT NOT NULL,
			id TEXT NOT NULL,
			character_id TEXT NOT NULL,
			item_slug TEXT NOT NULL,
			days_required INTEGER NOT NULL,
			days_completed INTEGER NOT NULL,
			cost_gp INTEGER NOT NULL,
			status TEXT NOT NULL,
			PRIMARY KEY (campaign_id, id)
		)`,
		`CREATE TABLE IF NOT EXISTS campaign_sessions (
			campaign_id TEXT NOT NULL,
			id TEXT NOT NULL,
			starts_at TEXT NOT NULL,
			duration_minutes INTEGER NOT NULL,
			agenda TEXT NOT NULL,
			present TEXT NOT NULL,
			absent TEXT NOT NULL,
			attendance_recorded INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_campaigns (
			id TEXT PRIMARY KEY,
			name TEXT NOT NULL,
			owner TEXT NOT NULL,
			status TEXT NOT NULL,
			max_players INTEGER NOT NULL,
			current_actor TEXT NOT NULL DEFAULT '',
			turn_number INTEGER NOT NULL DEFAULT 0,
			nudge_count INTEGER NOT NULL DEFAULT 0,
			story TEXT NOT NULL DEFAULT '',
			dm_notes TEXT NOT NULL DEFAULT ''
		)`,
		`CREATE TABLE IF NOT EXISTS play_members (
			campaign_id TEXT NOT NULL,
			username TEXT NOT NULL,
			character_id TEXT NOT NULL,
			name TEXT NOT NULL,
			class TEXT NOT NULL,
			join_order INTEGER NOT NULL DEFAULT 0,
			owner TEXT NOT NULL DEFAULT '',
			level INTEGER NOT NULL DEFAULT 1,
			con_score INTEGER NOT NULL DEFAULT 10,
			str_score INTEGER NOT NULL DEFAULT 10,
			dex_score INTEGER NOT NULL DEFAULT 10,
			int_score INTEGER NOT NULL DEFAULT 10,
			wis_score INTEGER NOT NULL DEFAULT 10,
			cha_score INTEGER NOT NULL DEFAULT 10,
			PRIMARY KEY (campaign_id, username)
		)`,
		`CREATE TABLE IF NOT EXISTS play_narrations (
			campaign_id TEXT NOT NULL,
			sequence INTEGER NOT NULL,
			kind TEXT NOT NULL,
			actor TEXT NOT NULL,
			type TEXT NOT NULL DEFAULT '',
			target TEXT NOT NULL DEFAULT '',
			text TEXT NOT NULL,
			PRIMARY KEY (campaign_id, sequence)
		)`,
		`CREATE TABLE IF NOT EXISTS play_scenes (
			campaign_id TEXT NOT NULL,
			id TEXT NOT NULL,
			name TEXT NOT NULL,
			status TEXT NOT NULL,
			PRIMARY KEY (campaign_id, id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_locations (
			campaign_id TEXT NOT NULL,
			id TEXT NOT NULL,
			name TEXT NOT NULL,
			PRIMARY KEY (campaign_id, id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_connections (
			campaign_id TEXT NOT NULL,
			from_id TEXT NOT NULL,
			to_id TEXT NOT NULL,
			travel_turns INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, from_id, to_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_encounters (
			campaign_id TEXT NOT NULL,
			id TEXT NOT NULL,
			name TEXT NOT NULL,
			status TEXT NOT NULL,
			PRIMARY KEY (campaign_id, id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_monsters (
			campaign_id TEXT NOT NULL,
			encounter_id TEXT NOT NULL,
			monster_id TEXT NOT NULL,
			name TEXT NOT NULL,
			hp_max INTEGER NOT NULL,
			hp_current INTEGER NOT NULL,
			initiative INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, encounter_id, monster_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_combatants (
			campaign_id TEXT NOT NULL,
			encounter_id TEXT NOT NULL,
			member TEXT NOT NULL,
			character_id TEXT NOT NULL,
			name TEXT NOT NULL,
			initiative INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, encounter_id, member)
		)`,
		`CREATE TABLE IF NOT EXISTS play_conditions (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			campaign_id TEXT NOT NULL,
			encounter_id TEXT NOT NULL,
			target TEXT NOT NULL,
			condition TEXT NOT NULL,
			remaining_rounds INTEGER NOT NULL
		)`,
		`CREATE TABLE IF NOT EXISTS play_encounter_rewards (
			campaign_id TEXT NOT NULL,
			encounter_id TEXT NOT NULL,
			xp INTEGER NOT NULL,
			loot TEXT NOT NULL,
			PRIMARY KEY (campaign_id, encounter_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_spells (
			campaign_id TEXT NOT NULL,
			character_id TEXT NOT NULL,
			spell_id TEXT NOT NULL,
			name TEXT NOT NULL,
			level INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, character_id, spell_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_prepared_spells (
			campaign_id TEXT NOT NULL,
			character_id TEXT NOT NULL,
			spell_ids TEXT NOT NULL,
			PRIMARY KEY (campaign_id, character_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_casts (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			campaign_id TEXT NOT NULL,
			character_id TEXT NOT NULL,
			spell_id TEXT NOT NULL,
			target TEXT NOT NULL,
			slot_level INTEGER NOT NULL,
			slots_remaining INTEGER NOT NULL,
			sequence INTEGER NOT NULL
		)`,
		`CREATE TABLE IF NOT EXISTS play_concentration (
			campaign_id TEXT NOT NULL,
			character_id TEXT NOT NULL,
			spell_id TEXT NOT NULL,
			target TEXT NOT NULL,
			remaining_turns INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, character_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_inventory_items (
			campaign_id TEXT NOT NULL,
			character_id TEXT NOT NULL,
			item_id TEXT NOT NULL,
			quantity INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, character_id, item_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_equipment (
			campaign_id TEXT NOT NULL,
			character_id TEXT NOT NULL,
			slot TEXT NOT NULL,
			item_id TEXT NOT NULL,
			attuned INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, character_id, slot)
		)`,
		`CREATE TABLE IF NOT EXISTS play_currency (
			campaign_id TEXT NOT NULL,
			character_id TEXT NOT NULL,
			gold INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, character_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_transfers (
			campaign_id TEXT NOT NULL,
			transfer_id INTEGER NOT NULL,
			from_character_id TEXT NOT NULL,
			to_character_id TEXT NOT NULL,
			gold INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, transfer_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_loot (
			campaign_id TEXT NOT NULL,
			loot_id TEXT NOT NULL,
			item_id TEXT NOT NULL,
			quantity INTEGER NOT NULL,
			status TEXT NOT NULL,
			recipient_character_id TEXT NOT NULL,
			votes INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, loot_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_loot_votes (
			campaign_id TEXT NOT NULL,
			loot_id TEXT NOT NULL,
			voter TEXT NOT NULL,
			recipient_character_id TEXT NOT NULL,
			PRIMARY KEY (campaign_id, loot_id, voter)
		)`,
		`CREATE TABLE IF NOT EXISTS play_npcs (
			campaign_id TEXT NOT NULL,
			npc_id TEXT NOT NULL,
			name TEXT NOT NULL,
			agenda TEXT NOT NULL,
			public_status TEXT NOT NULL,
			PRIMARY KEY (campaign_id, npc_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_factions (
			campaign_id TEXT NOT NULL,
			faction_id TEXT NOT NULL,
			name TEXT NOT NULL,
			PRIMARY KEY (campaign_id, faction_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_reputation (
			campaign_id TEXT NOT NULL,
			faction_id TEXT NOT NULL,
			entry_id INTEGER NOT NULL,
			character_id TEXT NOT NULL,
			reputation INTEGER NOT NULL,
			delta INTEGER NOT NULL,
			reason TEXT NOT NULL,
			PRIMARY KEY (campaign_id, faction_id, entry_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_npc_dialogue (
			campaign_id TEXT NOT NULL,
			npc_id TEXT NOT NULL,
			entry_id INTEGER NOT NULL,
			dialogue_id TEXT NOT NULL,
			speaker TEXT NOT NULL,
			text TEXT NOT NULL,
			visibility TEXT NOT NULL,
			PRIMARY KEY (campaign_id, npc_id, entry_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_relationships (
			campaign_id TEXT NOT NULL,
			entry_id INTEGER NOT NULL,
			source_id TEXT NOT NULL,
			target_id TEXT NOT NULL,
			kind TEXT NOT NULL,
			score INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, entry_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_clues (
			campaign_id TEXT NOT NULL,
			entry_id INTEGER NOT NULL,
			clue_id TEXT NOT NULL,
			text TEXT NOT NULL,
			audience TEXT NOT NULL,
			character_id TEXT NOT NULL,
			PRIMARY KEY (campaign_id, entry_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_quests (
			campaign_id TEXT NOT NULL,
			entry_id INTEGER NOT NULL,
			quest_id TEXT NOT NULL,
			title TEXT NOT NULL,
			depends_on TEXT NOT NULL,
			state TEXT NOT NULL,
			PRIMARY KEY (campaign_id, entry_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_character_rewards (
			campaign_id TEXT NOT NULL,
			character_id TEXT NOT NULL,
			xp INTEGER NOT NULL,
			items TEXT NOT NULL,
			PRIMARY KEY (campaign_id, character_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_world_events (
			campaign_id TEXT NOT NULL,
			entry_id INTEGER NOT NULL,
			event_id TEXT NOT NULL,
			turn_number INTEGER NOT NULL,
			title TEXT NOT NULL,
			text TEXT NOT NULL,
			resolved INTEGER NOT NULL DEFAULT 0,
			resolution_turn_number INTEGER NOT NULL DEFAULT 0,
			resolution_text TEXT NOT NULL DEFAULT '',
			PRIMARY KEY (campaign_id, entry_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_calendars (
			campaign_id TEXT PRIMARY KEY,
			day INTEGER NOT NULL,
			season TEXT NOT NULL
		)`,
		`CREATE TABLE IF NOT EXISTS play_settlements (
			campaign_id TEXT NOT NULL,
			entry_id INTEGER NOT NULL,
			settlement_id TEXT NOT NULL,
			name TEXT NOT NULL,
			services TEXT NOT NULL,
			availability TEXT NOT NULL,
			discovered_by TEXT NOT NULL DEFAULT '',
			PRIMARY KEY (campaign_id, entry_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_shops (
			campaign_id TEXT NOT NULL,
			settlement_id TEXT NOT NULL,
			shop_id TEXT NOT NULL,
			name TEXT NOT NULL,
			stock TEXT NOT NULL,
			buy_price INTEGER NOT NULL,
			sell_price INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, settlement_id, shop_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_recipes (
			campaign_id TEXT NOT NULL,
			entry_id INTEGER NOT NULL,
			recipe_id TEXT NOT NULL,
			name TEXT NOT NULL,
			ingredients TEXT NOT NULL,
			output_item TEXT NOT NULL,
			output_quantity INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, entry_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_downtime_activities (
			campaign_id TEXT NOT NULL,
			activity_id TEXT NOT NULL,
			name TEXT NOT NULL,
			cycles_required INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, activity_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_downtime_allocations (
			campaign_id TEXT NOT NULL,
			character_id TEXT NOT NULL,
			activity_id TEXT NOT NULL,
			cycles_completed INTEGER NOT NULL,
			completions INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, character_id, activity_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_session_zero (
			campaign_id TEXT PRIMARY KEY,
			rules TEXT NOT NULL,
			tone TEXT NOT NULL,
			consent TEXT NOT NULL
		)`,
		`CREATE TABLE IF NOT EXISTS play_content (
			campaign_id TEXT NOT NULL,
			content_id TEXT NOT NULL,
			entry_id INTEGER NOT NULL,
			kind TEXT NOT NULL,
			text TEXT NOT NULL,
			tags TEXT NOT NULL,
			PRIMARY KEY (campaign_id, content_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_notes (
			campaign_id TEXT NOT NULL,
			note_id TEXT NOT NULL,
			entry_id INTEGER NOT NULL,
			text TEXT NOT NULL,
			visibility TEXT NOT NULL,
			owner TEXT NOT NULL,
			PRIMARY KEY (campaign_id, note_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_whispers (
			campaign_id TEXT NOT NULL,
			whisper_id TEXT NOT NULL,
			entry_id INTEGER NOT NULL,
			from_character_id TEXT NOT NULL,
			to_character_id TEXT NOT NULL,
			text TEXT NOT NULL,
			PRIMARY KEY (campaign_id, whisper_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_invitations (
			campaign_id TEXT NOT NULL,
			invitation_id TEXT NOT NULL,
			entry_id INTEGER NOT NULL,
			username TEXT NOT NULL,
			character_id TEXT NOT NULL,
			status TEXT NOT NULL,
			PRIMARY KEY (campaign_id, invitation_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_delegations (
			campaign_id TEXT NOT NULL,
			username TEXT NOT NULL,
			powers TEXT NOT NULL,
			active INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, username)
		)`,
		`CREATE TABLE IF NOT EXISTS play_delegation_audit (
			campaign_id TEXT NOT NULL,
			entry_id INTEGER NOT NULL,
			username TEXT NOT NULL,
			action TEXT NOT NULL,
			powers TEXT NOT NULL,
			PRIMARY KEY (campaign_id, entry_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_audit_events (
			campaign_id TEXT NOT NULL,
			timestamp INTEGER NOT NULL,
			kind TEXT NOT NULL,
			actor TEXT NOT NULL,
			role TEXT NOT NULL,
			correlation_id TEXT NOT NULL,
			PRIMARY KEY (campaign_id, timestamp)
		)`,
		`CREATE TABLE IF NOT EXISTS play_projection_events (
			campaign_id TEXT NOT NULL,
			sequence INTEGER NOT NULL,
			event_id TEXT NOT NULL,
			kind TEXT NOT NULL,
			value TEXT NOT NULL,
			has_value INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, sequence)
		)`,
		`CREATE TABLE IF NOT EXISTS play_idempotent_events (
			campaign_id TEXT NOT NULL,
			sequence INTEGER NOT NULL,
			event_id TEXT NOT NULL,
			value TEXT NOT NULL,
			idempotency_key TEXT NOT NULL,
			PRIMARY KEY (campaign_id, sequence)
		)`,
		`CREATE TABLE IF NOT EXISTS play_safe_turns (
			campaign_id TEXT NOT NULL,
			sequence INTEGER NOT NULL,
			submission_id TEXT NOT NULL,
			action TEXT NOT NULL,
			accepted_turn INTEGER NOT NULL,
			next_turn INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, sequence)
		)`,
		`CREATE TABLE IF NOT EXISTS play_transactional_transfers (
			campaign_id TEXT NOT NULL,
			sequence INTEGER NOT NULL,
			from_character_id TEXT NOT NULL,
			to_character_id TEXT NOT NULL,
			amount INTEGER NOT NULL,
			from_gold INTEGER NOT NULL,
			to_gold INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, sequence)
		)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_exports (
			campaign_id TEXT NOT NULL,
			version INTEGER NOT NULL,
			story TEXT NOT NULL,
			status TEXT NOT NULL,
			PRIMARY KEY (campaign_id, version)
		)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_imports (
			campaign_id TEXT NOT NULL PRIMARY KEY,
			version INTEGER NOT NULL,
			story TEXT NOT NULL,
			status TEXT NOT NULL
		)`,
		`CREATE TABLE IF NOT EXISTS play_search_records (
			campaign_id TEXT NOT NULL,
			entry_id INTEGER NOT NULL,
			record_id TEXT NOT NULL,
			text TEXT NOT NULL,
			PRIMARY KEY (campaign_id, entry_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_migrations (
			campaign_id TEXT NOT NULL PRIMARY KEY,
			schema_version INTEGER NOT NULL,
			story TEXT NOT NULL,
			campaign_name TEXT NOT NULL
		)`,
		`CREATE TABLE IF NOT EXISTS play_rate_events (
			campaign_id TEXT NOT NULL,
			entry_id INTEGER NOT NULL,
			event_id TEXT NOT NULL,
			actor TEXT NOT NULL,
			PRIMARY KEY (campaign_id, entry_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_metrics (
			campaign_id TEXT NOT NULL PRIMARY KEY,
			rejected_rate_events INTEGER NOT NULL DEFAULT 0
		)`,
		`CREATE TABLE IF NOT EXISTS play_campaign_backups (
			campaign_id TEXT NOT NULL,
			sequence INTEGER NOT NULL,
			backup_id TEXT NOT NULL,
			story TEXT NOT NULL,
			status TEXT NOT NULL,
			PRIMARY KEY (campaign_id, sequence)
		)`,
		`CREATE TABLE IF NOT EXISTS play_replay_events (
			campaign_id TEXT NOT NULL,
			sequence INTEGER NOT NULL,
			event_id TEXT NOT NULL,
			kind TEXT NOT NULL,
			text TEXT NOT NULL,
			PRIMARY KEY (campaign_id, sequence)
		)`,
		`CREATE TABLE IF NOT EXISTS play_rng_seeds (
			campaign_id TEXT NOT NULL PRIMARY KEY,
			seed TEXT NOT NULL
		)`,
		`CREATE TABLE IF NOT EXISTS play_rng_rolls (
			campaign_id TEXT NOT NULL,
			sequence INTEGER NOT NULL,
			roll_id TEXT NOT NULL,
			sides INTEGER NOT NULL,
			result INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, sequence)
		)`,
		`CREATE TABLE IF NOT EXISTS play_moderation_reports (
			campaign_id TEXT NOT NULL,
			report_id TEXT NOT NULL,
			target_id TEXT NOT NULL,
			reason TEXT NOT NULL,
			status TEXT NOT NULL,
			reporter TEXT NOT NULL,
			sequence INTEGER NOT NULL,
			action TEXT NOT NULL DEFAULT '',
			note TEXT NOT NULL DEFAULT '',
			resolver TEXT NOT NULL DEFAULT '',
			PRIMARY KEY (campaign_id, report_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_safety_boundaries (
			campaign_id TEXT NOT NULL PRIMARY KEY,
			blocked_tags TEXT NOT NULL
		)`,
		`CREATE TABLE IF NOT EXISTS play_safety_events (
			campaign_id TEXT NOT NULL,
			event_id TEXT NOT NULL,
			kind TEXT NOT NULL,
			text TEXT NOT NULL,
			tags TEXT NOT NULL,
			sequence INTEGER NOT NULL,
			PRIMARY KEY (campaign_id, event_id)
		)`,
		`CREATE TABLE IF NOT EXISTS play_fixture_states (
			campaign_id TEXT NOT NULL PRIMARY KEY,
			fixture_id TEXT NOT NULL,
			status TEXT NOT NULL,
			characters TEXT NOT NULL,
			story TEXT NOT NULL,
			event_ids TEXT NOT NULL
		)`,
		`CREATE TABLE IF NOT EXISTS play_spectators (
			spectator_id TEXT NOT NULL PRIMARY KEY,
			campaign_id TEXT NOT NULL
		)`,
		`CREATE TABLE IF NOT EXISTS play_feed_events (
			campaign_id TEXT NOT NULL,
			entry_id INTEGER NOT NULL,
			event_id TEXT NOT NULL,
			text TEXT NOT NULL,
			PRIMARY KEY (campaign_id, entry_id)
		)`,
	}
	for _, stmt := range statements {
		if _, err := conn.Exec(stmt); err != nil {
			log.Fatalf("failed to initialize schema: %v", err)
		}
	}
	// These columns were added to play_campaigns/play_members/play_narrations
	// after their initial CREATE TABLE statements above, so they're folded in
	// here via ALTER TABLE instead of being merged into those statements.
	// removeDBFiles wipes game.db on every startup (see main.go), so this
	// always runs against a schema created moments earlier in this same
	// process, not against a genuinely older on-disk database; the
	// duplicate-column tolerance below just makes re-running this list
	// idempotent within a single process lifetime.
	migrations := []string{
		`ALTER TABLE play_campaigns ADD COLUMN current_actor TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE play_campaigns ADD COLUMN turn_number INTEGER NOT NULL DEFAULT 0`,
		`ALTER TABLE play_members ADD COLUMN join_order INTEGER NOT NULL DEFAULT 0`,
		`ALTER TABLE play_narrations ADD COLUMN type TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE play_campaigns ADD COLUMN story TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE play_campaigns ADD COLUMN dm_notes TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE play_campaigns ADD COLUMN current_scene_id TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE play_campaigns ADD COLUMN current_location_id TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE play_members ADD COLUMN hp_current INTEGER NOT NULL DEFAULT 20`,
		`ALTER TABLE play_members ADD COLUMN hp_max INTEGER NOT NULL DEFAULT 20`,
		`ALTER TABLE play_campaigns ADD COLUMN current_encounter_id TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE play_encounters ADD COLUMN round INTEGER NOT NULL DEFAULT 1`,
		`ALTER TABLE play_encounters ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0`,
		`ALTER TABLE play_narrations ADD COLUMN target TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE play_members ADD COLUMN status TEXT NOT NULL DEFAULT 'conscious'`,
		`ALTER TABLE play_members ADD COLUMN death_save_successes INTEGER NOT NULL DEFAULT 0`,
		`ALTER TABLE play_members ADD COLUMN death_save_failures INTEGER NOT NULL DEFAULT 0`,
		`ALTER TABLE play_encounters ADD COLUMN order_override TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE play_encounters ADD COLUMN xp_awarded INTEGER NOT NULL DEFAULT 0`,
		`ALTER TABLE play_campaigns ADD COLUMN pre_combat_actor TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE play_members ADD COLUMN owner TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE play_members ADD COLUMN race TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE play_members ADD COLUMN background TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE play_members ADD COLUMN level INTEGER NOT NULL DEFAULT 1`,
		`ALTER TABLE play_members ADD COLUMN con_score INTEGER NOT NULL DEFAULT 10`,
		`ALTER TABLE play_members ADD COLUMN str_score INTEGER NOT NULL DEFAULT 10`,
		`ALTER TABLE play_members ADD COLUMN dex_score INTEGER NOT NULL DEFAULT 10`,
		`ALTER TABLE play_members ADD COLUMN int_score INTEGER NOT NULL DEFAULT 10`,
		`ALTER TABLE play_members ADD COLUMN wis_score INTEGER NOT NULL DEFAULT 10`,
		`ALTER TABLE play_members ADD COLUMN cha_score INTEGER NOT NULL DEFAULT 10`,
		`ALTER TABLE play_quests ADD COLUMN reward_xp INTEGER NOT NULL DEFAULT 0`,
		`ALTER TABLE play_quests ADD COLUMN reward_items TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE play_quests ADD COLUMN rewards_set INTEGER NOT NULL DEFAULT 0`,
		`ALTER TABLE play_quests ADD COLUMN reward_awarded INTEGER NOT NULL DEFAULT 0`,
		`ALTER TABLE play_campaigns ADD COLUMN phase TEXT NOT NULL DEFAULT ''`,
	}
	for _, stmt := range migrations {
		if _, err := conn.Exec(stmt); err != nil && !strings.Contains(err.Error(), "duplicate column") {
			log.Fatalf("failed to migrate schema: %v", err)
		}
	}
	if _, err := conn.Exec(
		`INSERT INTO storage_meta (key, value) VALUES ('schema_version', ?)
		 ON CONFLICT(key) DO UPDATE SET value = excluded.value`,
		"1",
	); err != nil {
		log.Fatalf("failed to record schema version: %v", err)
	}
}

func initStorage() {
	storageOnce.Do(func() {
		db = openDB()
		createSchema(db)
		loadUsersFromDB()
		loadCombatSessionsFromDB()
		loadMonstersFromDB()
		loadItemsFromDB()
		loadCampaignsFromDB()
		loadPlayCampaignsFromDB()
		loadPlayMembersFromDB()
		loadPlayNarrationsFromDB()
		loadPlayScenesFromDB()
		loadPlayLocationsFromDB()
		loadPlayConnectionsFromDB()
		loadPlayEncountersFromDB()
		loadPlayMonstersFromDB()
		loadPlayCombatantsFromDB()
		loadPlayConditionsFromDB()
		loadPlayEncounterRewardsFromDB()
		loadPlaySpellsFromDB()
		loadPreparedSpellsFromDB()
		loadSpellCastsFromDB()
		loadConcentrationFromDB()
		loadInventoryItemsFromDB()
		loadEquipmentFromDB()
		loadCurrencyFromDB()
		loadTransfersFromDB()
		loadLootFromDB()
		loadLootVotesFromDB()
		loadNPCsFromDB()
		loadFactionsFromDB()
		loadReputationFromDB()
		loadNPCDialogueFromDB()
		loadRelationshipsFromDB()
		loadCluesFromDB()
		loadPlayQuestsFromDB()
		loadPlayCharacterRewardsFromDB()
		loadWorldEventsFromDB()
		loadCalendarsFromDB()
		loadSettlementsFromDB()
		loadShopsFromDB()
		loadRecipesFromDB()
		loadDowntimeActivitiesFromDB()
		loadDowntimeAllocationsFromDB()
		loadSessionZeroFromDB()
		loadContentFromDB()
		loadNotesFromDB()
		loadWhispersFromDB()
		loadInvitationsFromDB()
		loadDelegationsFromDB()
		loadDelegationAuditFromDB()
		loadAuditEventsFromDB()
		loadProjectionEventsFromDB()
		loadIdempotentEventsFromDB()
		loadSafeTurnsFromDB()
		loadTransactionalTransfersFromDB()
		loadCampaignExportsFromDB()
		loadCampaignImportsFromDB()
		loadCampaignMigrationsFromDB()
		loadSearchRecordsFromDB()
		loadRateEventsFromDB()
		loadCampaignMetricsFromDB()
		loadCampaignBackupsFromDB()
		loadReplayEventsFromDB()
		loadRngLedgersFromDB()
		loadModerationReportsFromDB()
		loadSafetyBoundariesFromDB()
		loadSafetyEventsFromDB()
		loadFixtureStatesFromDB()
		loadSpectatorsFromDB()
		loadFeedEventsFromDB()
		initialized = true
	})
}

func resetStorage() error {
	usersMu.Lock()
	combatSessionsMu.Lock()
	monstersMu.Lock()
	itemsMu.Lock()
	campaignsMu.Lock()
	playCampaignsMu.Lock()
	playMembersMu.Lock()
	playNarrationsMu.Lock()
	playScenesMu.Lock()
	playLocationsMu.Lock()
	playConnectionsMu.Lock()
	playEncountersMu.Lock()
	playMonstersMu.Lock()
	playCombatantsMu.Lock()
	playConditionsMu.Lock()
	playSpellsMu.Lock()
	preparedSpellsMu.Lock()
	spellCastsMu.Lock()
	concentrationMu.Lock()
	inventoryItemsMu.Lock()
	currencyMu.Lock()
	transfersMu.Lock()
	campaignLootMu.Lock()
	lootVotesMu.Lock()
	campaignFactionsMu.Lock()
	campaignReputationMu.Lock()
	campaignNPCDialogueMu.Lock()
	defer usersMu.Unlock()
	defer combatSessionsMu.Unlock()
	defer monstersMu.Unlock()
	defer itemsMu.Unlock()
	defer campaignsMu.Unlock()
	defer playCampaignsMu.Unlock()
	defer playMembersMu.Unlock()
	defer playNarrationsMu.Unlock()
	defer playScenesMu.Unlock()
	defer playLocationsMu.Unlock()
	defer playConnectionsMu.Unlock()
	defer playEncountersMu.Unlock()
	defer playMonstersMu.Unlock()
	defer playCombatantsMu.Unlock()
	defer playConditionsMu.Unlock()
	defer playSpellsMu.Unlock()
	defer preparedSpellsMu.Unlock()
	defer spellCastsMu.Unlock()
	defer concentrationMu.Unlock()
	defer inventoryItemsMu.Unlock()
	defer currencyMu.Unlock()
	defer transfersMu.Unlock()
	defer campaignLootMu.Unlock()
	defer lootVotesMu.Unlock()
	defer campaignFactionsMu.Unlock()
	defer campaignReputationMu.Unlock()
	defer campaignNPCDialogueMu.Unlock()

	statements := []string{
		`DROP TABLE IF EXISTS combat_sessions`,
		`DROP TABLE IF EXISTS monsters`,
		`DROP TABLE IF EXISTS items`,
		`DROP TABLE IF EXISTS campaigns`,
		`DROP TABLE IF EXISTS campaign_characters`,
		`DROP TABLE IF EXISTS campaign_events`,
		`DROP TABLE IF EXISTS campaign_quests`,
		`DROP TABLE IF EXISTS campaign_factions`,
		`DROP TABLE IF EXISTS campaign_npcs`,
		`DROP TABLE IF EXISTS campaign_inventory`,
		`DROP TABLE IF EXISTS campaign_equipment`,
		`DROP TABLE IF EXISTS campaign_crafting_projects`,
		`DROP TABLE IF EXISTS campaign_sessions`,
		`DROP TABLE IF EXISTS play_campaigns`,
		`DROP TABLE IF EXISTS play_members`,
		`DROP TABLE IF EXISTS play_narrations`,
		`DROP TABLE IF EXISTS play_scenes`,
		`DROP TABLE IF EXISTS play_locations`,
		`DROP TABLE IF EXISTS play_connections`,
		`DROP TABLE IF EXISTS play_encounters`,
		`DROP TABLE IF EXISTS play_monsters`,
		`DROP TABLE IF EXISTS play_combatants`,
		`DROP TABLE IF EXISTS play_conditions`,
		`DROP TABLE IF EXISTS play_spells`,
		`DROP TABLE IF EXISTS play_prepared_spells`,
		`DROP TABLE IF EXISTS play_casts`,
		`DROP TABLE IF EXISTS play_concentration`,
		`DROP TABLE IF EXISTS play_inventory_items`,
		`DROP TABLE IF EXISTS play_equipment`,
		`DROP TABLE IF EXISTS play_currency`,
		`DROP TABLE IF EXISTS play_transfers`,
		`DROP TABLE IF EXISTS play_loot`,
		`DROP TABLE IF EXISTS play_loot_votes`,
		`DROP TABLE IF EXISTS play_npcs`,
		`DROP TABLE IF EXISTS play_factions`,
		`DROP TABLE IF EXISTS play_reputation`,
		`DROP TABLE IF EXISTS play_npc_dialogue`,
		`DROP TABLE IF EXISTS play_relationships`,
		`DROP TABLE IF EXISTS play_clues`,
		`DROP TABLE IF EXISTS storage_meta`,
	}
	for _, stmt := range statements {
		if _, err := db.Exec(stmt); err != nil {
			return err
		}
	}
	createSchema(db)

	combatSessions = map[string]*combatSession{}
	monsters = map[string]*monster{}
	items = map[string]*item{}
	campaigns = map[string]*campaign{}
	playCampaigns = map[string]*playCampaign{}
	playMembers = map[string]map[string]*playMember{}
	playNarrations = map[string][]*playNarration{}
	playScenes = map[string]map[string]*playScene{}
	playLocations = map[string]map[string]*playLocation{}
	playConnections = map[string][]*playConnection{}
	playEncounters = map[string]map[string]*playEncounter{}
	playMonsters = map[string]map[string]map[string]*playMonster{}
	playCombatants = map[string]map[string]map[string]*playCombatant{}
	playConditions = map[string]map[string]map[string][]*playCondition{}
	playSpells = map[string]map[string][]*playSpell{}
	preparedSpells = map[string]map[string]*playPreparedSpells{}
	spellCasts = map[string]map[string][]*playSpellCast{}
	spellSlotsUsed = map[string]map[string]map[int]int{}
	concentrations = map[string]map[string]*playConcentration{}
	inventoryItems = map[string]map[string]map[string]*playInventoryItem{}
	equipment = map[string]map[string]map[string]*playEquipment{}
	currency = map[string]map[string]*playCurrency{}
	transfers = map[string][]*playTransfer{}
	campaignLoot = map[string]map[string]*playLoot{}
	lootVotes = map[string]map[string]map[string]*playLootVote{}
	campaignFactions = map[string]map[string]*playFaction{}
	campaignReputation = map[string]map[string][]*playReputationEntry{}
	campaignNPCDialogue = map[string]map[string][]*playNPCDialogueEntry{}

	return nil
}

func loadUsersFromDB() {
	rows, err := db.Query(`SELECT username, role, password_hash FROM users`)
	if err != nil {
		log.Fatalf("failed to load users: %v", err)
	}
	defer rows.Close()

	usersMu.Lock()
	defer usersMu.Unlock()
	for rows.Next() {
		u := &user{}
		if err := rows.Scan(&u.Username, &u.Role, &u.PasswordHash); err != nil {
			log.Fatalf("failed to scan user row: %v", err)
		}
		users[u.Username] = u
	}
}

func saveUserToDB(u *user) error {
	_, err := db.Exec(
		`INSERT INTO users (username, role, password_hash) VALUES (?, ?, ?)
		 ON CONFLICT(username) DO UPDATE SET role = excluded.role, password_hash = excluded.password_hash`,
		u.Username, u.Role, u.PasswordHash,
	)
	return err
}

type persistedCondition struct {
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

type persistedCombatant struct {
	Name       string               `json:"name"`
	Dex        int                  `json:"dex"`
	Score      int                  `json:"score"`
	Conditions []persistedCondition `json:"conditions"`
}

type persistedCombatSession struct {
	ID        string               `json:"id"`
	Round     int                  `json:"round"`
	TurnIndex int                  `json:"turn_index"`
	Order     []persistedCombatant `json:"order"`
}

func toPersistedSession(s *combatSession) persistedCombatSession {
	p := persistedCombatSession{ID: s.ID, Round: s.Round, TurnIndex: s.TurnIndex}
	for _, c := range s.Order {
		pc := persistedCombatant{Name: c.Name, Dex: c.Dex, Score: c.Score}
		for _, cond := range c.Conditions {
			pc.Conditions = append(pc.Conditions, persistedCondition{
				Condition:       cond.Condition,
				RemainingRounds: cond.RemainingRounds,
			})
		}
		p.Order = append(p.Order, pc)
	}
	return p
}

func fromPersistedSession(p persistedCombatSession) *combatSession {
	s := &combatSession{ID: p.ID, Round: p.Round, TurnIndex: p.TurnIndex}
	for _, pc := range p.Order {
		c := &combatSessionCombatant{Name: pc.Name, Dex: pc.Dex, Score: pc.Score}
		for _, pcond := range pc.Conditions {
			c.Conditions = append(c.Conditions, condition{
				Condition:       pcond.Condition,
				RemainingRounds: pcond.RemainingRounds,
			})
		}
		s.Order = append(s.Order, c)
	}
	return s
}

func loadCombatSessionsFromDB() {
	rows, err := db.Query(`SELECT data FROM combat_sessions`)
	if err != nil {
		log.Fatalf("failed to load combat sessions: %v", err)
	}
	defer rows.Close()

	combatSessionsMu.Lock()
	defer combatSessionsMu.Unlock()
	for rows.Next() {
		var data string
		if err := rows.Scan(&data); err != nil {
			log.Fatalf("failed to scan combat session row: %v", err)
		}
		var p persistedCombatSession
		if err := json.Unmarshal([]byte(data), &p); err != nil {
			log.Fatalf("failed to decode combat session: %v", err)
		}
		s := fromPersistedSession(p)
		combatSessions[s.ID] = s
	}
}

func saveCombatSessionToDB(s *combatSession) error {
	data, err := json.Marshal(toPersistedSession(s))
	if err != nil {
		return err
	}
	_, err = db.Exec(
		`INSERT INTO combat_sessions (id, data) VALUES (?, ?)
		 ON CONFLICT(id) DO UPDATE SET data = excluded.data`,
		s.ID, string(data),
	)
	return err
}

func loadMonstersFromDB() {
	rows, err := db.Query(`SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters`)
	if err != nil {
		log.Fatalf("failed to load monsters: %v", err)
	}
	defer rows.Close()

	monstersMu.Lock()
	defer monstersMu.Unlock()
	for rows.Next() {
		m := &monster{}
		var tagsJSON string
		if err := rows.Scan(&m.Slug, &m.Name, &m.CR, &m.ArmorClass, &m.HitPoints, &tagsJSON); err != nil {
			log.Fatalf("failed to scan monster row: %v", err)
		}
		if err := json.Unmarshal([]byte(tagsJSON), &m.Tags); err != nil {
			log.Fatalf("failed to decode monster tags: %v", err)
		}
		monsters[m.Slug] = m
	}
}

func saveMonsterToDB(m *monster) error {
	tagsJSON, err := json.Marshal(m.Tags)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		`INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)`,
		m.Slug, m.Name, m.CR, m.ArmorClass, m.HitPoints, string(tagsJSON),
	)
	return err
}

func loadItemsFromDB() {
	rows, err := db.Query(`SELECT slug, name, type, rarity, cost_gp FROM items`)
	if err != nil {
		log.Fatalf("failed to load items: %v", err)
	}
	defer rows.Close()

	itemsMu.Lock()
	defer itemsMu.Unlock()
	for rows.Next() {
		it := &item{}
		if err := rows.Scan(&it.Slug, &it.Name, &it.Type, &it.Rarity, &it.CostGP); err != nil {
			log.Fatalf("failed to scan item row: %v", err)
		}
		items[it.Slug] = it
	}
}

func saveItemToDB(it *item) error {
	_, err := db.Exec(
		`INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)`,
		it.Slug, it.Name, it.Type, it.Rarity, it.CostGP,
	)
	return err
}

func loadCampaignsFromDB() {
	rows, err := db.Query(`SELECT id, name, dm FROM campaigns`)
	if err != nil {
		log.Fatalf("failed to load campaigns: %v", err)
	}
	defer rows.Close()

	campaignsMu.Lock()
	defer campaignsMu.Unlock()
	for rows.Next() {
		c := &campaign{}
		if err := rows.Scan(&c.ID, &c.Name, &c.DM); err != nil {
			log.Fatalf("failed to scan campaign row: %v", err)
		}
		campaigns[c.ID] = c
	}

	charRows, err := db.Query(`SELECT campaign_id, id, name, level, class FROM campaign_characters`)
	if err != nil {
		log.Fatalf("failed to load campaign characters: %v", err)
	}
	defer charRows.Close()
	for charRows.Next() {
		var campaignID string
		ch := &campaignCharacter{}
		if err := charRows.Scan(&campaignID, &ch.ID, &ch.Name, &ch.Level, &ch.Class); err != nil {
			log.Fatalf("failed to scan campaign character row: %v", err)
		}
		if c, ok := campaigns[campaignID]; ok {
			c.Characters = append(c.Characters, ch)
		}
	}

	evtRows, err := db.Query(`SELECT campaign_id, id, kind, summary FROM campaign_events`)
	if err != nil {
		log.Fatalf("failed to load campaign events: %v", err)
	}
	defer evtRows.Close()
	for evtRows.Next() {
		var campaignID string
		ev := &campaignEvent{}
		if err := evtRows.Scan(&campaignID, &ev.ID, &ev.Kind, &ev.Summary); err != nil {
			log.Fatalf("failed to scan campaign event row: %v", err)
		}
		if c, ok := campaigns[campaignID]; ok {
			c.Events = append(c.Events, ev)
		}
	}

	questRows, err := db.Query(`SELECT campaign_id, id, title, status, milestones, done FROM campaign_quests`)
	if err != nil {
		log.Fatalf("failed to load campaign quests: %v", err)
	}
	defer questRows.Close()
	for questRows.Next() {
		var campaignID, milestonesJSON, doneJSON string
		q := &campaignQuest{}
		if err := questRows.Scan(&campaignID, &q.ID, &q.Title, &q.Status, &milestonesJSON, &doneJSON); err != nil {
			log.Fatalf("failed to scan campaign quest row: %v", err)
		}
		if err := json.Unmarshal([]byte(milestonesJSON), &q.Milestones); err != nil {
			log.Fatalf("failed to decode quest milestones: %v", err)
		}
		q.Done = map[string]bool{}
		if err := json.Unmarshal([]byte(doneJSON), &q.Done); err != nil {
			log.Fatalf("failed to decode quest done set: %v", err)
		}
		if c, ok := campaigns[campaignID]; ok {
			c.Quests = append(c.Quests, q)
		}
	}

	factionRows, err := db.Query(`SELECT campaign_id, id, name, stance FROM campaign_factions`)
	if err != nil {
		log.Fatalf("failed to load campaign factions: %v", err)
	}
	defer factionRows.Close()
	for factionRows.Next() {
		var campaignID string
		f := &campaignFaction{}
		if err := factionRows.Scan(&campaignID, &f.ID, &f.Name, &f.Stance); err != nil {
			log.Fatalf("failed to scan campaign faction row: %v", err)
		}
		if c, ok := campaigns[campaignID]; ok {
			c.Factions = append(c.Factions, f)
		}
	}

	npcRows, err := db.Query(`SELECT campaign_id, id, name, faction_id, disposition FROM campaign_npcs`)
	if err != nil {
		log.Fatalf("failed to load campaign npcs: %v", err)
	}
	defer npcRows.Close()
	for npcRows.Next() {
		var campaignID string
		n := &campaignNPC{}
		if err := npcRows.Scan(&campaignID, &n.ID, &n.Name, &n.FactionID, &n.Disposition); err != nil {
			log.Fatalf("failed to scan campaign npc row: %v", err)
		}
		if c, ok := campaigns[campaignID]; ok {
			c.NPCs = append(c.NPCs, n)
		}
	}

	invRows, err := db.Query(`SELECT campaign_id, item_slug, owner, quantity FROM campaign_inventory`)
	if err != nil {
		log.Fatalf("failed to load campaign inventory: %v", err)
	}
	defer invRows.Close()
	for invRows.Next() {
		var campaignID string
		inv := &campaignInventoryItem{}
		if err := invRows.Scan(&campaignID, &inv.ItemSlug, &inv.Owner, &inv.Quantity); err != nil {
			log.Fatalf("failed to scan campaign inventory row: %v", err)
		}
		if c, ok := campaigns[campaignID]; ok {
			c.Inventory = append(c.Inventory, inv)
		}
	}

	equipRows, err := db.Query(`SELECT campaign_id, character_id, item_slug, quantity FROM campaign_equipment`)
	if err != nil {
		log.Fatalf("failed to load campaign equipment: %v", err)
	}
	defer equipRows.Close()
	for equipRows.Next() {
		var campaignID string
		eq := &campaignEquipmentItem{}
		if err := equipRows.Scan(&campaignID, &eq.CharacterID, &eq.ItemSlug, &eq.Quantity); err != nil {
			log.Fatalf("failed to scan campaign equipment row: %v", err)
		}
		if c, ok := campaigns[campaignID]; ok {
			c.Equipment = append(c.Equipment, eq)
		}
	}

	craftRows, err := db.Query(`SELECT campaign_id, id, character_id, item_slug, days_required, days_completed, cost_gp, status FROM campaign_crafting_projects`)
	if err != nil {
		log.Fatalf("failed to load campaign crafting projects: %v", err)
	}
	defer craftRows.Close()
	for craftRows.Next() {
		var campaignID string
		p := &campaignCraftingProject{}
		if err := craftRows.Scan(&campaignID, &p.ID, &p.CharacterID, &p.ItemSlug, &p.DaysRequired, &p.DaysCompleted, &p.CostGP, &p.Status); err != nil {
			log.Fatalf("failed to scan campaign crafting project row: %v", err)
		}
		if c, ok := campaigns[campaignID]; ok {
			c.CraftingProjects = append(c.CraftingProjects, p)
		}
	}

	sessionRows, err := db.Query(`SELECT campaign_id, id, starts_at, duration_minutes, agenda, present, absent, attendance_recorded FROM campaign_sessions`)
	if err != nil {
		log.Fatalf("failed to load campaign sessions: %v", err)
	}
	defer sessionRows.Close()
	for sessionRows.Next() {
		var campaignID, agendaJSON, presentJSON, absentJSON string
		var attendanceRecorded int
		s := &campaignSession{}
		if err := sessionRows.Scan(&campaignID, &s.ID, &s.StartsAt, &s.DurationMinutes, &agendaJSON, &presentJSON, &absentJSON, &attendanceRecorded); err != nil {
			log.Fatalf("failed to scan campaign session row: %v", err)
		}
		if err := json.Unmarshal([]byte(agendaJSON), &s.Agenda); err != nil {
			log.Fatalf("failed to decode session agenda: %v", err)
		}
		if err := json.Unmarshal([]byte(presentJSON), &s.Present); err != nil {
			log.Fatalf("failed to decode session present list: %v", err)
		}
		if err := json.Unmarshal([]byte(absentJSON), &s.Absent); err != nil {
			log.Fatalf("failed to decode session absent list: %v", err)
		}
		s.AttendanceRecorded = attendanceRecorded != 0
		if c, ok := campaigns[campaignID]; ok {
			c.Sessions = append(c.Sessions, s)
		}
	}
}

func saveCampaignToDB(c *campaign) error {
	_, err := db.Exec(
		`INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)`,
		c.ID, c.Name, c.DM,
	)
	return err
}

func saveCampaignCharacterToDB(campaignID string, ch *campaignCharacter) error {
	_, err := db.Exec(
		`INSERT INTO campaign_characters (campaign_id, id, name, level, class) VALUES (?, ?, ?, ?, ?)`,
		campaignID, ch.ID, ch.Name, ch.Level, ch.Class,
	)
	return err
}

func saveCampaignEventToDB(campaignID string, ev *campaignEvent) error {
	_, err := db.Exec(
		`INSERT INTO campaign_events (campaign_id, id, kind, summary) VALUES (?, ?, ?, ?)`,
		campaignID, ev.ID, ev.Kind, ev.Summary,
	)
	return err
}

func saveCampaignQuestToDB(campaignID string, q *campaignQuest) error {
	milestonesJSON, err := json.Marshal(q.Milestones)
	if err != nil {
		return err
	}
	doneJSON, err := json.Marshal(q.Done)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		`INSERT INTO campaign_quests (campaign_id, id, title, status, milestones, done) VALUES (?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, id) DO UPDATE SET title = excluded.title, status = excluded.status, milestones = excluded.milestones, done = excluded.done`,
		campaignID, q.ID, q.Title, q.Status, string(milestonesJSON), string(doneJSON),
	)
	return err
}

func saveCampaignFactionToDB(campaignID string, f *campaignFaction) error {
	_, err := db.Exec(
		`INSERT INTO campaign_factions (campaign_id, id, name, stance) VALUES (?, ?, ?, ?)`,
		campaignID, f.ID, f.Name, f.Stance,
	)
	return err
}

func saveCampaignNPCToDB(campaignID string, n *campaignNPC) error {
	_, err := db.Exec(
		`INSERT INTO campaign_npcs (campaign_id, id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)`,
		campaignID, n.ID, n.Name, n.FactionID, n.Disposition,
	)
	return err
}

func saveCampaignInventoryToDB(campaignID string, inv *campaignInventoryItem) error {
	_, err := db.Exec(
		`INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)
		 ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = excluded.quantity`,
		campaignID, inv.ItemSlug, inv.Owner, inv.Quantity,
	)
	return err
}

func saveCampaignEquipmentToDB(campaignID string, eq *campaignEquipmentItem) error {
	_, err := db.Exec(
		`INSERT INTO campaign_equipment (campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?)
		 ON CONFLICT(campaign_id, character_id, item_slug) DO UPDATE SET quantity = excluded.quantity`,
		campaignID, eq.CharacterID, eq.ItemSlug, eq.Quantity,
	)
	return err
}

func saveCampaignCraftingProjectToDB(campaignID string, p *campaignCraftingProject) error {
	_, err := db.Exec(
		`INSERT INTO campaign_crafting_projects (campaign_id, id, character_id, item_slug, days_required, days_completed, cost_gp, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, id) DO UPDATE SET days_completed = excluded.days_completed, status = excluded.status`,
		campaignID, p.ID, p.CharacterID, p.ItemSlug, p.DaysRequired, p.DaysCompleted, p.CostGP, p.Status,
	)
	return err
}

func saveCampaignSessionToDB(campaignID string, s *campaignSession) error {
	agendaJSON, err := json.Marshal(s.Agenda)
	if err != nil {
		return err
	}
	presentJSON, err := json.Marshal(s.Present)
	if err != nil {
		return err
	}
	absentJSON, err := json.Marshal(s.Absent)
	if err != nil {
		return err
	}
	attendanceRecorded := 0
	if s.AttendanceRecorded {
		attendanceRecorded = 1
	}
	_, err = db.Exec(
		`INSERT INTO campaign_sessions (campaign_id, id, starts_at, duration_minutes, agenda, present, absent, attendance_recorded) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, id) DO UPDATE SET present = excluded.present, absent = excluded.absent, attendance_recorded = excluded.attendance_recorded`,
		campaignID, s.ID, s.StartsAt, s.DurationMinutes, string(agendaJSON), string(presentJSON), string(absentJSON), attendanceRecorded,
	)
	return err
}

func loadPlayCampaignsFromDB() {
	rows, err := db.Query(`SELECT id, name, owner, status, max_players, current_actor, turn_number, nudge_count, story, dm_notes, current_scene_id, current_location_id, current_encounter_id, pre_combat_actor, phase FROM play_campaigns`)
	if err != nil {
		log.Fatalf("failed to load play campaigns: %v", err)
	}
	defer rows.Close()

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()
	for rows.Next() {
		c := &playCampaign{}
		if err := rows.Scan(&c.ID, &c.Name, &c.Owner, &c.Status, &c.MaxPlayers, &c.CurrentActor, &c.TurnNumber, &c.NudgeCount, &c.Story, &c.DMNotes, &c.CurrentSceneID, &c.CurrentLocationID, &c.CurrentEncounterID, &c.PreCombatActor, &c.Phase); err != nil {
			log.Fatalf("failed to scan play campaign row: %v", err)
		}
		playCampaigns[c.ID] = c
	}
}

func savePlayCampaignToDB(c *playCampaign) error {
	_, err := db.Exec(
		`INSERT INTO play_campaigns (id, name, owner, status, max_players, current_actor, turn_number, nudge_count, story, dm_notes, current_scene_id, current_location_id, current_encounter_id, pre_combat_actor, phase) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		 ON CONFLICT(id) DO UPDATE SET name = excluded.name, owner = excluded.owner, status = excluded.status, max_players = excluded.max_players, current_actor = excluded.current_actor, turn_number = excluded.turn_number, nudge_count = excluded.nudge_count, story = excluded.story, dm_notes = excluded.dm_notes, current_scene_id = excluded.current_scene_id, current_location_id = excluded.current_location_id, current_encounter_id = excluded.current_encounter_id, pre_combat_actor = excluded.pre_combat_actor, phase = excluded.phase`,
		c.ID, c.Name, c.Owner, c.Status, c.MaxPlayers, c.CurrentActor, c.TurnNumber, c.NudgeCount, c.Story, c.DMNotes, c.CurrentSceneID, c.CurrentLocationID, c.CurrentEncounterID, c.PreCombatActor, c.Phase,
	)
	return err
}

func loadPlayMembersFromDB() {
	rows, err := db.Query(`SELECT campaign_id, username, character_id, name, class, join_order, hp_current, hp_max, status, death_save_successes, death_save_failures, owner, race, background, level, con_score, str_score, dex_score, int_score, wis_score, cha_score FROM play_members`)
	if err != nil {
		log.Fatalf("failed to load play members: %v", err)
	}
	defer rows.Close()

	playMembersMu.Lock()
	defer playMembersMu.Unlock()
	for rows.Next() {
		m := &playMember{}
		if err := rows.Scan(&m.CampaignID, &m.Username, &m.CharacterID, &m.Name, &m.Class, &m.JoinOrder, &m.HPCurrent, &m.HPMax, &m.Status, &m.DeathSaveSuccesses, &m.DeathSaveFailures, &m.Owner, &m.Race, &m.Background, &m.Level, &m.ConScore, &m.StrScore, &m.DexScore, &m.IntScore, &m.WisScore, &m.ChaScore); err != nil {
			log.Fatalf("failed to scan play member row: %v", err)
		}
		if playMembers[m.CampaignID] == nil {
			playMembers[m.CampaignID] = map[string]*playMember{}
		}
		playMembers[m.CampaignID][m.Username] = m
	}
}

func savePlayMemberToDB(m *playMember) error {
	_, err := db.Exec(
		`INSERT INTO play_members (campaign_id, username, character_id, name, class, join_order, hp_current, hp_max, status, death_save_successes, death_save_failures, owner, race, background, level, con_score, str_score, dex_score, int_score, wis_score, cha_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, username) DO UPDATE SET character_id = excluded.character_id, name = excluded.name, class = excluded.class, join_order = excluded.join_order, hp_current = excluded.hp_current, hp_max = excluded.hp_max, status = excluded.status, death_save_successes = excluded.death_save_successes, death_save_failures = excluded.death_save_failures, owner = excluded.owner, race = excluded.race, background = excluded.background, level = excluded.level, con_score = excluded.con_score, str_score = excluded.str_score, dex_score = excluded.dex_score, int_score = excluded.int_score, wis_score = excluded.wis_score, cha_score = excluded.cha_score`,
		m.CampaignID, m.Username, m.CharacterID, m.Name, m.Class, m.JoinOrder, m.HPCurrent, m.HPMax, m.Status, m.DeathSaveSuccesses, m.DeathSaveFailures, m.Owner, m.Race, m.Background, m.Level, m.ConScore, m.StrScore, m.DexScore, m.IntScore, m.WisScore, m.ChaScore,
	)
	return err
}

func loadPlayNarrationsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, sequence, kind, actor, type, target, text FROM play_narrations ORDER BY campaign_id, sequence`)
	if err != nil {
		log.Fatalf("failed to load play narrations: %v", err)
	}
	defer rows.Close()

	playNarrationsMu.Lock()
	defer playNarrationsMu.Unlock()
	for rows.Next() {
		n := &playNarration{}
		if err := rows.Scan(&n.CampaignID, &n.Sequence, &n.Kind, &n.Actor, &n.Type, &n.Target, &n.Text); err != nil {
			log.Fatalf("failed to scan play narration row: %v", err)
		}
		playNarrations[n.CampaignID] = append(playNarrations[n.CampaignID], n)
	}
}

func savePlayNarrationToDB(n *playNarration) error {
	_, err := db.Exec(
		`INSERT INTO play_narrations (campaign_id, sequence, kind, actor, type, target, text) VALUES (?, ?, ?, ?, ?, ?, ?)`,
		n.CampaignID, n.Sequence, n.Kind, n.Actor, n.Type, n.Target, n.Text,
	)
	return err
}

func loadPlayScenesFromDB() {
	rows, err := db.Query(`SELECT campaign_id, id, name, status FROM play_scenes`)
	if err != nil {
		log.Fatalf("failed to load play scenes: %v", err)
	}
	defer rows.Close()

	playScenesMu.Lock()
	defer playScenesMu.Unlock()
	for rows.Next() {
		s := &playScene{}
		if err := rows.Scan(&s.CampaignID, &s.ID, &s.Name, &s.Status); err != nil {
			log.Fatalf("failed to scan play scene row: %v", err)
		}
		if playScenes[s.CampaignID] == nil {
			playScenes[s.CampaignID] = map[string]*playScene{}
		}
		playScenes[s.CampaignID][s.ID] = s
	}
}

func savePlaySceneToDB(s *playScene) error {
	_, err := db.Exec(
		`INSERT INTO play_scenes (campaign_id, id, name, status) VALUES (?, ?, ?, ?)
		 ON CONFLICT(campaign_id, id) DO UPDATE SET name = excluded.name, status = excluded.status`,
		s.CampaignID, s.ID, s.Name, s.Status,
	)
	return err
}

func loadPlayLocationsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, id, name FROM play_locations`)
	if err != nil {
		log.Fatalf("failed to load play locations: %v", err)
	}
	defer rows.Close()

	playLocationsMu.Lock()
	defer playLocationsMu.Unlock()
	for rows.Next() {
		loc := &playLocation{}
		if err := rows.Scan(&loc.CampaignID, &loc.ID, &loc.Name); err != nil {
			log.Fatalf("failed to scan play location row: %v", err)
		}
		if playLocations[loc.CampaignID] == nil {
			playLocations[loc.CampaignID] = map[string]*playLocation{}
		}
		playLocations[loc.CampaignID][loc.ID] = loc
	}
}

func savePlayLocationToDB(loc *playLocation) error {
	_, err := db.Exec(
		`INSERT INTO play_locations (campaign_id, id, name) VALUES (?, ?, ?)
		 ON CONFLICT(campaign_id, id) DO UPDATE SET name = excluded.name`,
		loc.CampaignID, loc.ID, loc.Name,
	)
	return err
}

func loadPlayConnectionsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, from_id, to_id, travel_turns FROM play_connections`)
	if err != nil {
		log.Fatalf("failed to load play connections: %v", err)
	}
	defer rows.Close()

	playConnectionsMu.Lock()
	defer playConnectionsMu.Unlock()
	for rows.Next() {
		conn := &playConnection{}
		if err := rows.Scan(&conn.CampaignID, &conn.FromID, &conn.ToID, &conn.TravelTurns); err != nil {
			log.Fatalf("failed to scan play connection row: %v", err)
		}
		playConnections[conn.CampaignID] = append(playConnections[conn.CampaignID], conn)
	}
}

func savePlayConnectionToDB(conn *playConnection) error {
	_, err := db.Exec(
		`INSERT INTO play_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)
		 ON CONFLICT(campaign_id, from_id, to_id) DO UPDATE SET travel_turns = excluded.travel_turns`,
		conn.CampaignID, conn.FromID, conn.ToID, conn.TravelTurns,
	)
	return err
}

func loadPlayEncountersFromDB() {
	rows, err := db.Query(`SELECT campaign_id, id, name, status, round, turn_index, order_override, xp_awarded FROM play_encounters`)
	if err != nil {
		log.Fatalf("failed to load play encounters: %v", err)
	}
	defer rows.Close()

	playEncountersMu.Lock()
	defer playEncountersMu.Unlock()
	for rows.Next() {
		enc := &playEncounter{}
		var orderOverride string
		if err := rows.Scan(&enc.CampaignID, &enc.ID, &enc.Name, &enc.Status, &enc.Round, &enc.TurnIndex, &orderOverride, &enc.XPAwarded); err != nil {
			log.Fatalf("failed to scan play encounter row: %v", err)
		}
		enc.OrderOverride = decodeOrderOverride(orderOverride)
		if playEncounters[enc.CampaignID] == nil {
			playEncounters[enc.CampaignID] = map[string]*playEncounter{}
		}
		playEncounters[enc.CampaignID][enc.ID] = enc
	}
}

func savePlayEncounterToDB(enc *playEncounter) error {
	_, err := db.Exec(
		`INSERT INTO play_encounters (campaign_id, id, name, status, round, turn_index, order_override, xp_awarded) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, id) DO UPDATE SET name = excluded.name, status = excluded.status, round = excluded.round, turn_index = excluded.turn_index, order_override = excluded.order_override, xp_awarded = excluded.xp_awarded`,
		enc.CampaignID, enc.ID, enc.Name, enc.Status, enc.Round, enc.TurnIndex, encodeOrderOverride(enc.OrderOverride), enc.XPAwarded,
	)
	return err
}

func loadPlayEncounterRewardsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, encounter_id, xp, loot FROM play_encounter_rewards`)
	if err != nil {
		log.Fatalf("failed to load play encounter rewards: %v", err)
	}
	defer rows.Close()

	playEncounterRewardsMu.Lock()
	defer playEncounterRewardsMu.Unlock()
	for rows.Next() {
		reward := &playEncounterReward{}
		var lootRaw string
		if err := rows.Scan(&reward.CampaignID, &reward.EncounterID, &reward.XP, &lootRaw); err != nil {
			log.Fatalf("failed to scan play encounter reward row: %v", err)
		}
		if err := json.Unmarshal([]byte(lootRaw), &reward.Loot); err != nil {
			log.Fatalf("failed to decode play encounter reward loot: %v", err)
		}
		if playEncounterRewards[reward.CampaignID] == nil {
			playEncounterRewards[reward.CampaignID] = map[string]*playEncounterReward{}
		}
		playEncounterRewards[reward.CampaignID][reward.EncounterID] = reward
	}
}

func savePlayEncounterRewardToDB(reward *playEncounterReward) error {
	lootRaw, err := json.Marshal(reward.Loot)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		`INSERT INTO play_encounter_rewards (campaign_id, encounter_id, xp, loot) VALUES (?, ?, ?, ?)`,
		reward.CampaignID, reward.EncounterID, reward.XP, string(lootRaw),
	)
	return err
}

func loadPlaySpellsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, character_id, spell_id, name, level FROM play_spells`)
	if err != nil {
		log.Fatalf("failed to load play spells: %v", err)
	}
	defer rows.Close()

	playSpellsMu.Lock()
	defer playSpellsMu.Unlock()
	for rows.Next() {
		s := &playSpell{}
		if err := rows.Scan(&s.CampaignID, &s.CharacterID, &s.SpellID, &s.Name, &s.Level); err != nil {
			log.Fatalf("failed to scan play spell row: %v", err)
		}
		if playSpells[s.CampaignID] == nil {
			playSpells[s.CampaignID] = map[string][]*playSpell{}
		}
		playSpells[s.CampaignID][s.CharacterID] = append(playSpells[s.CampaignID][s.CharacterID], s)
	}
}

func savePlaySpellToDB(s *playSpell) error {
	_, err := db.Exec(
		`INSERT INTO play_spells (campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)`,
		s.CampaignID, s.CharacterID, s.SpellID, s.Name, s.Level,
	)
	return err
}

func loadPreparedSpellsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, character_id, spell_ids FROM play_prepared_spells`)
	if err != nil {
		log.Fatalf("failed to load play prepared spells: %v", err)
	}
	defer rows.Close()

	preparedSpellsMu.Lock()
	defer preparedSpellsMu.Unlock()
	for rows.Next() {
		p := &playPreparedSpells{}
		var idsRaw string
		if err := rows.Scan(&p.CampaignID, &p.CharacterID, &idsRaw); err != nil {
			log.Fatalf("failed to scan play prepared spells row: %v", err)
		}
		if idsRaw == "" {
			p.SpellIDs = []string{}
		} else {
			p.SpellIDs = strings.Split(idsRaw, ",")
		}
		if preparedSpells[p.CampaignID] == nil {
			preparedSpells[p.CampaignID] = map[string]*playPreparedSpells{}
		}
		preparedSpells[p.CampaignID][p.CharacterID] = p
	}
}

func savePreparedSpellsToDB(p *playPreparedSpells) error {
	_, err := db.Exec(
		`INSERT INTO play_prepared_spells (campaign_id, character_id, spell_ids) VALUES (?, ?, ?)
		 ON CONFLICT(campaign_id, character_id) DO UPDATE SET spell_ids = excluded.spell_ids`,
		p.CampaignID, p.CharacterID, strings.Join(p.SpellIDs, ","),
	)
	return err
}

func loadSpellCastsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, character_id, spell_id, target, slot_level, slots_remaining, sequence FROM play_casts ORDER BY id ASC`)
	if err != nil {
		log.Fatalf("failed to load play casts: %v", err)
	}
	defer rows.Close()

	spellCastsMu.Lock()
	defer spellCastsMu.Unlock()
	for rows.Next() {
		c := &playSpellCast{}
		if err := rows.Scan(&c.CampaignID, &c.CharacterID, &c.SpellID, &c.Target, &c.SlotLevel, &c.SlotsRemaining, &c.Sequence); err != nil {
			log.Fatalf("failed to scan play cast row: %v", err)
		}
		if spellCasts[c.CampaignID] == nil {
			spellCasts[c.CampaignID] = map[string][]*playSpellCast{}
		}
		spellCasts[c.CampaignID][c.CharacterID] = append(spellCasts[c.CampaignID][c.CharacterID], c)

		if spellSlotsUsed[c.CampaignID] == nil {
			spellSlotsUsed[c.CampaignID] = map[string]map[int]int{}
		}
		if spellSlotsUsed[c.CampaignID][c.CharacterID] == nil {
			spellSlotsUsed[c.CampaignID][c.CharacterID] = map[int]int{}
		}
		spellSlotsUsed[c.CampaignID][c.CharacterID][c.SlotLevel]++
	}
}

func saveSpellCastToDB(c *playSpellCast) error {
	_, err := db.Exec(
		`INSERT INTO play_casts (campaign_id, character_id, spell_id, target, slot_level, slots_remaining, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)`,
		c.CampaignID, c.CharacterID, c.SpellID, c.Target, c.SlotLevel, c.SlotsRemaining, c.Sequence,
	)
	return err
}

func loadConcentrationFromDB() {
	rows, err := db.Query(`SELECT campaign_id, character_id, spell_id, target, remaining_turns FROM play_concentration`)
	if err != nil {
		log.Fatalf("failed to load play concentration: %v", err)
	}
	defer rows.Close()

	concentrationMu.Lock()
	defer concentrationMu.Unlock()
	for rows.Next() {
		c := &playConcentration{}
		if err := rows.Scan(&c.CampaignID, &c.CharacterID, &c.SpellID, &c.Target, &c.RemainingTurns); err != nil {
			log.Fatalf("failed to scan play concentration row: %v", err)
		}
		if concentrations[c.CampaignID] == nil {
			concentrations[c.CampaignID] = map[string]*playConcentration{}
		}
		concentrations[c.CampaignID][c.CharacterID] = c
	}
}

func saveConcentrationToDB(c *playConcentration) error {
	_, err := db.Exec(
		`INSERT INTO play_concentration (campaign_id, character_id, spell_id, target, remaining_turns) VALUES (?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, character_id) DO UPDATE SET spell_id = excluded.spell_id, target = excluded.target, remaining_turns = excluded.remaining_turns`,
		c.CampaignID, c.CharacterID, c.SpellID, c.Target, c.RemainingTurns,
	)
	return err
}

func deleteConcentrationFromDB(campaignID, charID string) error {
	_, err := db.Exec(
		`DELETE FROM play_concentration WHERE campaign_id = ? AND character_id = ?`,
		campaignID, charID,
	)
	return err
}

func loadInventoryItemsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, character_id, item_id, quantity FROM play_inventory_items`)
	if err != nil {
		log.Fatalf("failed to load play inventory items: %v", err)
	}
	defer rows.Close()

	inventoryItemsMu.Lock()
	defer inventoryItemsMu.Unlock()
	for rows.Next() {
		i := &playInventoryItem{}
		if err := rows.Scan(&i.CampaignID, &i.CharacterID, &i.ItemID, &i.Quantity); err != nil {
			log.Fatalf("failed to scan play inventory item row: %v", err)
		}
		if inventoryItems[i.CampaignID] == nil {
			inventoryItems[i.CampaignID] = map[string]map[string]*playInventoryItem{}
		}
		if inventoryItems[i.CampaignID][i.CharacterID] == nil {
			inventoryItems[i.CampaignID][i.CharacterID] = map[string]*playInventoryItem{}
		}
		inventoryItems[i.CampaignID][i.CharacterID][i.ItemID] = i
	}
}

func saveInventoryItemToDB(i *playInventoryItem) error {
	_, err := db.Exec(
		`INSERT INTO play_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)
		 ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = excluded.quantity`,
		i.CampaignID, i.CharacterID, i.ItemID, i.Quantity,
	)
	return err
}

func deleteInventoryItemFromDB(campaignID, charID, itemID string) error {
	_, err := db.Exec(
		`DELETE FROM play_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?`,
		campaignID, charID, itemID,
	)
	return err
}

func loadEquipmentFromDB() {
	rows, err := db.Query(`SELECT campaign_id, character_id, slot, item_id, attuned FROM play_equipment`)
	if err != nil {
		log.Fatalf("failed to load play equipment: %v", err)
	}
	defer rows.Close()

	equipmentMu.Lock()
	defer equipmentMu.Unlock()
	for rows.Next() {
		e := &playEquipment{}
		if err := rows.Scan(&e.CampaignID, &e.CharacterID, &e.Slot, &e.ItemID, &e.Attuned); err != nil {
			log.Fatalf("failed to scan play equipment row: %v", err)
		}
		if equipment[e.CampaignID] == nil {
			equipment[e.CampaignID] = map[string]map[string]*playEquipment{}
		}
		if equipment[e.CampaignID][e.CharacterID] == nil {
			equipment[e.CampaignID][e.CharacterID] = map[string]*playEquipment{}
		}
		equipment[e.CampaignID][e.CharacterID][e.Slot] = e
	}
}

func saveEquipmentToDB(e *playEquipment) error {
	_, err := db.Exec(
		`INSERT INTO play_equipment (campaign_id, character_id, slot, item_id, attuned) VALUES (?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET item_id = excluded.item_id, attuned = excluded.attuned`,
		e.CampaignID, e.CharacterID, e.Slot, e.ItemID, e.Attuned,
	)
	return err
}

func loadCurrencyFromDB() {
	rows, err := db.Query(`SELECT campaign_id, character_id, gold FROM play_currency`)
	if err != nil {
		log.Fatalf("failed to load play currency: %v", err)
	}
	defer rows.Close()

	currencyMu.Lock()
	defer currencyMu.Unlock()
	for rows.Next() {
		c := &playCurrency{}
		if err := rows.Scan(&c.CampaignID, &c.CharacterID, &c.Gold); err != nil {
			log.Fatalf("failed to scan play currency row: %v", err)
		}
		if currency[c.CampaignID] == nil {
			currency[c.CampaignID] = map[string]*playCurrency{}
		}
		currency[c.CampaignID][c.CharacterID] = c
	}
}

func saveCurrencyToDB(c *playCurrency) error {
	_, err := db.Exec(
		`INSERT INTO play_currency (campaign_id, character_id, gold) VALUES (?, ?, ?)
		 ON CONFLICT(campaign_id, character_id) DO UPDATE SET gold = excluded.gold`,
		c.CampaignID, c.CharacterID, c.Gold,
	)
	return err
}

func loadTransfersFromDB() {
	rows, err := db.Query(`SELECT campaign_id, transfer_id, from_character_id, to_character_id, gold FROM play_transfers ORDER BY campaign_id, transfer_id`)
	if err != nil {
		log.Fatalf("failed to load play transfers: %v", err)
	}
	defer rows.Close()

	transfersMu.Lock()
	defer transfersMu.Unlock()
	for rows.Next() {
		t := &playTransfer{}
		if err := rows.Scan(&t.CampaignID, &t.TransferID, &t.FromCharacterID, &t.ToCharacterID, &t.Gold); err != nil {
			log.Fatalf("failed to scan play transfer row: %v", err)
		}
		transfers[t.CampaignID] = append(transfers[t.CampaignID], t)
	}
}

func loadLootFromDB() {
	rows, err := db.Query(`SELECT campaign_id, loot_id, item_id, quantity, status, recipient_character_id, votes FROM play_loot`)
	if err != nil {
		log.Fatalf("failed to load play loot: %v", err)
	}
	defer rows.Close()

	campaignLootMu.Lock()
	defer campaignLootMu.Unlock()
	for rows.Next() {
		l := &playLoot{}
		if err := rows.Scan(&l.CampaignID, &l.LootID, &l.ItemID, &l.Quantity, &l.Status, &l.RecipientCharacterID, &l.Votes); err != nil {
			log.Fatalf("failed to scan play loot row: %v", err)
		}
		if campaignLoot[l.CampaignID] == nil {
			campaignLoot[l.CampaignID] = map[string]*playLoot{}
		}
		campaignLoot[l.CampaignID][l.LootID] = l
	}
}

func saveLootToDB(l *playLoot) error {
	_, err := db.Exec(
		`INSERT INTO play_loot (campaign_id, loot_id, item_id, quantity, status, recipient_character_id, votes)
		 VALUES (?, ?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, loot_id) DO UPDATE SET
			status = excluded.status,
			recipient_character_id = excluded.recipient_character_id,
			votes = excluded.votes`,
		l.CampaignID, l.LootID, l.ItemID, l.Quantity, l.Status, l.RecipientCharacterID, l.Votes,
	)
	return err
}

func loadLootVotesFromDB() {
	rows, err := db.Query(`SELECT campaign_id, loot_id, voter, recipient_character_id FROM play_loot_votes`)
	if err != nil {
		log.Fatalf("failed to load play loot votes: %v", err)
	}
	defer rows.Close()

	lootVotesMu.Lock()
	defer lootVotesMu.Unlock()
	for rows.Next() {
		v := &playLootVote{}
		if err := rows.Scan(&v.CampaignID, &v.LootID, &v.Voter, &v.RecipientCharacterID); err != nil {
			log.Fatalf("failed to scan play loot vote row: %v", err)
		}
		if lootVotes[v.CampaignID] == nil {
			lootVotes[v.CampaignID] = map[string]map[string]*playLootVote{}
		}
		if lootVotes[v.CampaignID][v.LootID] == nil {
			lootVotes[v.CampaignID][v.LootID] = map[string]*playLootVote{}
		}
		lootVotes[v.CampaignID][v.LootID][v.Voter] = v
	}
}

func saveLootVoteToDB(v *playLootVote) error {
	_, err := db.Exec(
		`INSERT INTO play_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)`,
		v.CampaignID, v.LootID, v.Voter, v.RecipientCharacterID,
	)
	return err
}

func loadNPCsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, npc_id, name, agenda, public_status FROM play_npcs`)
	if err != nil {
		log.Fatalf("failed to load play npcs: %v", err)
	}
	defer rows.Close()

	campaignNPCsMu.Lock()
	defer campaignNPCsMu.Unlock()
	for rows.Next() {
		n := &playNPC{}
		if err := rows.Scan(&n.CampaignID, &n.NPCID, &n.Name, &n.Agenda, &n.PublicStatus); err != nil {
			log.Fatalf("failed to scan play npc row: %v", err)
		}
		if campaignNPCs[n.CampaignID] == nil {
			campaignNPCs[n.CampaignID] = map[string]*playNPC{}
		}
		campaignNPCs[n.CampaignID][n.NPCID] = n
	}
}

func saveNPCToDB(n *playNPC) error {
	_, err := db.Exec(
		`INSERT INTO play_npcs (campaign_id, npc_id, name, agenda, public_status)
		 VALUES (?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, npc_id) DO UPDATE SET
			agenda = excluded.agenda,
			public_status = excluded.public_status`,
		n.CampaignID, n.NPCID, n.Name, n.Agenda, n.PublicStatus,
	)
	return err
}

func loadFactionsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, faction_id, name FROM play_factions`)
	if err != nil {
		log.Fatalf("failed to load play factions: %v", err)
	}
	defer rows.Close()

	campaignFactionsMu.Lock()
	defer campaignFactionsMu.Unlock()
	for rows.Next() {
		f := &playFaction{}
		if err := rows.Scan(&f.CampaignID, &f.FactionID, &f.Name); err != nil {
			log.Fatalf("failed to scan play faction row: %v", err)
		}
		if campaignFactions[f.CampaignID] == nil {
			campaignFactions[f.CampaignID] = map[string]*playFaction{}
		}
		campaignFactions[f.CampaignID][f.FactionID] = f
	}
}

func saveFactionToDB(f *playFaction) error {
	_, err := db.Exec(
		`INSERT INTO play_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)`,
		f.CampaignID, f.FactionID, f.Name,
	)
	return err
}

func loadReputationFromDB() {
	rows, err := db.Query(`SELECT campaign_id, faction_id, entry_id, character_id, reputation, delta, reason FROM play_reputation ORDER BY campaign_id, faction_id, entry_id`)
	if err != nil {
		log.Fatalf("failed to load play reputation: %v", err)
	}
	defer rows.Close()

	campaignReputationMu.Lock()
	defer campaignReputationMu.Unlock()
	for rows.Next() {
		e := &playReputationEntry{}
		var entryID int
		if err := rows.Scan(&e.CampaignID, &e.FactionID, &entryID, &e.CharacterID, &e.Reputation, &e.Delta, &e.Reason); err != nil {
			log.Fatalf("failed to scan play reputation row: %v", err)
		}
		if campaignReputation[e.CampaignID] == nil {
			campaignReputation[e.CampaignID] = map[string][]*playReputationEntry{}
		}
		campaignReputation[e.CampaignID][e.FactionID] = append(campaignReputation[e.CampaignID][e.FactionID], e)
	}
}

func saveReputationEntryToDB(e *playReputationEntry, entryID int) error {
	_, err := db.Exec(
		`INSERT INTO play_reputation (campaign_id, faction_id, entry_id, character_id, reputation, delta, reason) VALUES (?, ?, ?, ?, ?, ?, ?)`,
		e.CampaignID, e.FactionID, entryID, e.CharacterID, e.Reputation, e.Delta, e.Reason,
	)
	return err
}

func loadNPCDialogueFromDB() {
	rows, err := db.Query(`SELECT campaign_id, npc_id, entry_id, dialogue_id, speaker, text, visibility FROM play_npc_dialogue ORDER BY campaign_id, npc_id, entry_id`)
	if err != nil {
		log.Fatalf("failed to load play npc dialogue: %v", err)
	}
	defer rows.Close()

	campaignNPCDialogueMu.Lock()
	defer campaignNPCDialogueMu.Unlock()
	for rows.Next() {
		e := &playNPCDialogueEntry{}
		var entryID int
		if err := rows.Scan(&e.CampaignID, &e.NPCID, &entryID, &e.DialogueID, &e.Speaker, &e.Text, &e.Visibility); err != nil {
			log.Fatalf("failed to scan play npc dialogue row: %v", err)
		}
		if campaignNPCDialogue[e.CampaignID] == nil {
			campaignNPCDialogue[e.CampaignID] = map[string][]*playNPCDialogueEntry{}
		}
		campaignNPCDialogue[e.CampaignID][e.NPCID] = append(campaignNPCDialogue[e.CampaignID][e.NPCID], e)
	}
}

func saveNPCDialogueEntryToDB(e *playNPCDialogueEntry, entryID int) error {
	_, err := db.Exec(
		`INSERT INTO play_npc_dialogue (campaign_id, npc_id, entry_id, dialogue_id, speaker, text, visibility) VALUES (?, ?, ?, ?, ?, ?, ?)`,
		e.CampaignID, e.NPCID, entryID, e.DialogueID, e.Speaker, e.Text, e.Visibility,
	)
	return err
}

func loadRelationshipsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, entry_id, source_id, target_id, kind, score FROM play_relationships ORDER BY campaign_id, entry_id`)
	if err != nil {
		log.Fatalf("failed to load play relationships: %v", err)
	}
	defer rows.Close()

	campaignRelationshipsMu.Lock()
	defer campaignRelationshipsMu.Unlock()
	for rows.Next() {
		rel := &playRelationship{}
		var entryID int
		if err := rows.Scan(&rel.CampaignID, &entryID, &rel.SourceID, &rel.TargetID, &rel.Kind, &rel.Score); err != nil {
			log.Fatalf("failed to scan play relationship row: %v", err)
		}
		campaignRelationships[rel.CampaignID] = append(campaignRelationships[rel.CampaignID], rel)
	}
}

func saveRelationshipToDB(rel *playRelationship) error {
	_, err := db.Exec(
		`INSERT INTO play_relationships (campaign_id, entry_id, source_id, target_id, kind, score)
		 VALUES (?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, entry_id) DO UPDATE SET score = excluded.score`,
		rel.CampaignID, relationshipEntryID(rel), rel.SourceID, rel.TargetID, rel.Kind, rel.Score,
	)
	return err
}

// relationshipEntryID derives a stable per-campaign entry id for rel from its
// position in campaignRelationships. Callers must already hold
// campaignRelationshipsMu.
func relationshipEntryID(rel *playRelationship) int {
	for i, e := range campaignRelationships[rel.CampaignID] {
		if e == rel {
			return i + 1
		}
	}
	return len(campaignRelationships[rel.CampaignID]) + 1
}

func loadCluesFromDB() {
	rows, err := db.Query(`SELECT campaign_id, entry_id, clue_id, text, audience, character_id FROM play_clues ORDER BY campaign_id, entry_id`)
	if err != nil {
		log.Fatalf("failed to load play clues: %v", err)
	}
	defer rows.Close()

	campaignCluesMu.Lock()
	defer campaignCluesMu.Unlock()
	for rows.Next() {
		clue := &playClue{}
		var entryID int
		if err := rows.Scan(&clue.CampaignID, &entryID, &clue.ClueID, &clue.Text, &clue.Audience, &clue.CharacterID); err != nil {
			log.Fatalf("failed to scan play clue row: %v", err)
		}
		campaignClues[clue.CampaignID] = append(campaignClues[clue.CampaignID], clue)
	}
}

func saveClueToDB(clue *playClue) error {
	_, err := db.Exec(
		`INSERT INTO play_clues (campaign_id, entry_id, clue_id, text, audience, character_id) VALUES (?, ?, ?, ?, ?, ?)`,
		clue.CampaignID, len(campaignClues[clue.CampaignID]), clue.ClueID, clue.Text, clue.Audience, clue.CharacterID,
	)
	return err
}

func loadSearchRecordsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, entry_id, record_id, text FROM play_search_records ORDER BY campaign_id, entry_id`)
	if err != nil {
		log.Fatalf("failed to load play search records: %v", err)
	}
	defer rows.Close()

	campaignSearchRecordsMu.Lock()
	defer campaignSearchRecordsMu.Unlock()
	for rows.Next() {
		rec := &playSearchRecord{}
		var entryID int
		if err := rows.Scan(&rec.CampaignID, &entryID, &rec.RecordID, &rec.Text); err != nil {
			log.Fatalf("failed to scan play search record row: %v", err)
		}
		campaignSearchRecords[rec.CampaignID] = append(campaignSearchRecords[rec.CampaignID], rec)
	}
}

func saveSearchRecordToDB(rec *playSearchRecord) error {
	_, err := db.Exec(
		`INSERT INTO play_search_records (campaign_id, entry_id, record_id, text) VALUES (?, ?, ?, ?)`,
		rec.CampaignID, len(campaignSearchRecords[rec.CampaignID]), rec.RecordID, rec.Text,
	)
	return err
}

func loadFeedEventsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, entry_id, event_id, text FROM play_feed_events ORDER BY campaign_id, entry_id`)
	if err != nil {
		log.Fatalf("failed to load play feed events: %v", err)
	}
	defer rows.Close()

	campaignFeedEventsMu.Lock()
	defer campaignFeedEventsMu.Unlock()
	for rows.Next() {
		e := &playFeedEvent{}
		var entryID int
		if err := rows.Scan(&e.CampaignID, &entryID, &e.EventID, &e.Text); err != nil {
			log.Fatalf("failed to scan play feed event row: %v", err)
		}
		e.Sequence = entryID + 1
		campaignFeedEvents[e.CampaignID] = append(campaignFeedEvents[e.CampaignID], e)
	}
}

func saveFeedEventToDB(e *playFeedEvent) error {
	_, err := db.Exec(
		`INSERT INTO play_feed_events (campaign_id, entry_id, event_id, text) VALUES (?, ?, ?, ?)`,
		e.CampaignID, len(campaignFeedEvents[e.CampaignID]), e.EventID, e.Text,
	)
	return err
}

func loadRateEventsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, entry_id, event_id, actor FROM play_rate_events ORDER BY campaign_id, entry_id`)
	if err != nil {
		log.Fatalf("failed to load play rate events: %v", err)
	}
	defer rows.Close()

	campaignRateEventsMu.Lock()
	defer campaignRateEventsMu.Unlock()
	for rows.Next() {
		e := &rateEvent{}
		if err := rows.Scan(&e.CampaignID, &e.EntryID, &e.EventID, &e.Actor); err != nil {
			log.Fatalf("failed to scan play rate event row: %v", err)
		}
		campaignRateEvents[e.CampaignID] = append(campaignRateEvents[e.CampaignID], e)
	}
}

func saveRateEventToDB(e *rateEvent) error {
	_, err := db.Exec(
		`INSERT INTO play_rate_events (campaign_id, entry_id, event_id, actor) VALUES (?, ?, ?, ?)`,
		e.CampaignID, e.EntryID, e.EventID, e.Actor,
	)
	return err
}

func loadCampaignMetricsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, rejected_rate_events FROM play_campaign_metrics`)
	if err != nil {
		log.Fatalf("failed to load play campaign metrics: %v", err)
	}
	defer rows.Close()

	campaignMetricsMu.Lock()
	defer campaignMetricsMu.Unlock()
	for rows.Next() {
		var campaignID string
		var rejected int
		if err := rows.Scan(&campaignID, &rejected); err != nil {
			log.Fatalf("failed to scan play campaign metrics row: %v", err)
		}
		campaignRejectedRateEvents[campaignID] = rejected
	}
}

func saveCampaignMetricsToDB(campaignID string, rejected int) error {
	_, err := db.Exec(
		`INSERT INTO play_campaign_metrics (campaign_id, rejected_rate_events) VALUES (?, ?)
		 ON CONFLICT(campaign_id) DO UPDATE SET rejected_rate_events = excluded.rejected_rate_events`,
		campaignID, rejected,
	)
	return err
}

func loadPlayQuestsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, entry_id, quest_id, title, depends_on, state, reward_xp, reward_items, rewards_set, reward_awarded FROM play_quests ORDER BY campaign_id, entry_id`)
	if err != nil {
		log.Fatalf("failed to load play quests: %v", err)
	}
	defer rows.Close()

	campaignQuestsMu.Lock()
	defer campaignQuestsMu.Unlock()
	for rows.Next() {
		q := &playQuest{}
		var entryID int
		var dependsOnRaw string
		var rewardXP int
		var rewardItemsRaw string
		var rewardsSet bool
		var rewardAwarded bool
		if err := rows.Scan(&q.CampaignID, &entryID, &q.QuestID, &q.Title, &dependsOnRaw, &q.State, &rewardXP, &rewardItemsRaw, &rewardsSet, &rewardAwarded); err != nil {
			log.Fatalf("failed to scan play quest row: %v", err)
		}
		deps := decodeOrderOverride(dependsOnRaw)
		if deps == nil {
			deps = []string{}
		}
		q.DependsOn = deps
		if rewardsSet {
			items := map[string]int{}
			if rewardItemsRaw != "" {
				if err := json.Unmarshal([]byte(rewardItemsRaw), &items); err != nil {
					log.Fatalf("failed to decode quest reward items: %v", err)
				}
			}
			q.Rewards = &questRewardConfig{XP: rewardXP, Items: items, Awarded: rewardAwarded}
		}
		campaignQuests[q.CampaignID] = append(campaignQuests[q.CampaignID], q)
	}
}

func saveQuestToDB(q *playQuest) error {
	rewardXP := 0
	rewardItemsRaw := ""
	rewardsSet := false
	rewardAwarded := false
	if q.Rewards != nil {
		rewardXP = q.Rewards.XP
		items := q.Rewards.Items
		if items == nil {
			items = map[string]int{}
		}
		encoded, err := json.Marshal(items)
		if err != nil {
			return err
		}
		rewardItemsRaw = string(encoded)
		rewardsSet = true
		rewardAwarded = q.Rewards.Awarded
	}
	_, err := db.Exec(
		`INSERT INTO play_quests (campaign_id, entry_id, quest_id, title, depends_on, state, reward_xp, reward_items, rewards_set, reward_awarded) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, entry_id) DO UPDATE SET state = excluded.state, reward_xp = excluded.reward_xp, reward_items = excluded.reward_items, rewards_set = excluded.rewards_set, reward_awarded = excluded.reward_awarded`,
		q.CampaignID, playQuestEntryID(q), q.QuestID, q.Title, encodeOrderOverride(q.DependsOn), q.State, rewardXP, rewardItemsRaw, rewardsSet, rewardAwarded,
	)
	return err
}

func loadPlayCharacterRewardsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, character_id, xp, items FROM play_character_rewards`)
	if err != nil {
		log.Fatalf("failed to load play character rewards: %v", err)
	}
	defer rows.Close()

	characterRewardsMu.Lock()
	defer characterRewardsMu.Unlock()
	for rows.Next() {
		totals := &characterRewardTotals{}
		var itemsRaw string
		if err := rows.Scan(&totals.CampaignID, &totals.CharacterID, &totals.XP, &itemsRaw); err != nil {
			log.Fatalf("failed to scan play character reward row: %v", err)
		}
		items := map[string]int{}
		if itemsRaw != "" {
			if err := json.Unmarshal([]byte(itemsRaw), &items); err != nil {
				log.Fatalf("failed to decode character reward items: %v", err)
			}
		}
		totals.Items = items
		if characterRewards[totals.CampaignID] == nil {
			characterRewards[totals.CampaignID] = map[string]*characterRewardTotals{}
		}
		characterRewards[totals.CampaignID][totals.CharacterID] = totals
	}
}

func saveCharacterRewardsToDB(totals *characterRewardTotals) error {
	items := totals.Items
	if items == nil {
		items = map[string]int{}
	}
	encoded, err := json.Marshal(items)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		`INSERT INTO play_character_rewards (campaign_id, character_id, xp, items) VALUES (?, ?, ?, ?)
		 ON CONFLICT(campaign_id, character_id) DO UPDATE SET xp = excluded.xp, items = excluded.items`,
		totals.CampaignID, totals.CharacterID, totals.XP, string(encoded),
	)
	return err
}

// playQuestEntryID derives a stable per-campaign entry id for q from its
// position in campaignQuests. Callers must already hold campaignQuestsMu.
func playQuestEntryID(q *playQuest) int {
	for i, e := range campaignQuests[q.CampaignID] {
		if e == q {
			return i
		}
	}
	return len(campaignQuests[q.CampaignID])
}

func loadWorldEventsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, entry_id, event_id, turn_number, title, text, resolved, resolution_turn_number, resolution_text FROM play_world_events ORDER BY campaign_id, entry_id`)
	if err != nil {
		log.Fatalf("failed to load world events: %v", err)
	}
	defer rows.Close()

	worldEventsMu.Lock()
	defer worldEventsMu.Unlock()
	for rows.Next() {
		e := &worldEvent{}
		var entryID int
		if err := rows.Scan(&e.CampaignID, &entryID, &e.EventID, &e.TurnNumber, &e.Title, &e.Text, &e.Resolved, &e.ResolutionTurnNumber, &e.ResolutionText); err != nil {
			log.Fatalf("failed to scan world event row: %v", err)
		}
		worldEvents[e.CampaignID] = append(worldEvents[e.CampaignID], e)
	}
}

// worldEventEntryID derives a stable per-campaign entry id for e from its
// position in worldEvents. Callers must already hold worldEventsMu.
func worldEventEntryID(e *worldEvent) int {
	for i, existing := range worldEvents[e.CampaignID] {
		if existing == e {
			return i
		}
	}
	return len(worldEvents[e.CampaignID])
}

func saveWorldEventToDB(e *worldEvent) error {
	_, err := db.Exec(
		`INSERT INTO play_world_events (campaign_id, entry_id, event_id, turn_number, title, text, resolved, resolution_turn_number, resolution_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, entry_id) DO UPDATE SET resolved = excluded.resolved, resolution_turn_number = excluded.resolution_turn_number, resolution_text = excluded.resolution_text`,
		e.CampaignID, worldEventEntryID(e), e.EventID, e.TurnNumber, e.Title, e.Text, e.Resolved, e.ResolutionTurnNumber, e.ResolutionText,
	)
	return err
}

func loadCalendarsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, day, season FROM play_calendars`)
	if err != nil {
		log.Fatalf("failed to load calendars: %v", err)
	}
	defer rows.Close()

	calendarsMu.Lock()
	defer calendarsMu.Unlock()
	for rows.Next() {
		c := &playCalendar{}
		if err := rows.Scan(&c.CampaignID, &c.Day, &c.Season); err != nil {
			log.Fatalf("failed to scan calendar row: %v", err)
		}
		calendars[c.CampaignID] = c
	}
}

func saveCalendarToDB(c *playCalendar) error {
	_, err := db.Exec(
		`INSERT INTO play_calendars (campaign_id, day, season) VALUES (?, ?, ?)
		 ON CONFLICT(campaign_id) DO UPDATE SET day = excluded.day, season = excluded.season`,
		c.CampaignID, c.Day, c.Season,
	)
	return err
}

func loadSettlementsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, entry_id, settlement_id, name, services, availability, discovered_by FROM play_settlements ORDER BY campaign_id, entry_id`)
	if err != nil {
		log.Fatalf("failed to load settlements: %v", err)
	}
	defer rows.Close()

	campaignSettlementsMu.Lock()
	defer campaignSettlementsMu.Unlock()
	for rows.Next() {
		s := &playSettlement{}
		var entryID int
		var servicesRaw, discoveredRaw string
		if err := rows.Scan(&s.CampaignID, &entryID, &s.SettlementID, &s.Name, &servicesRaw, &s.Availability, &discoveredRaw); err != nil {
			log.Fatalf("failed to scan settlement row: %v", err)
		}
		if err := json.Unmarshal([]byte(servicesRaw), &s.Services); err != nil {
			log.Fatalf("failed to decode settlement services: %v", err)
		}
		s.DiscoveredBy = []string{}
		if discoveredRaw != "" {
			if err := json.Unmarshal([]byte(discoveredRaw), &s.DiscoveredBy); err != nil {
				log.Fatalf("failed to decode settlement discovered_by: %v", err)
			}
		}
		campaignSettlements[s.CampaignID] = append(campaignSettlements[s.CampaignID], s)
	}
}

// settlementEntryID derives a stable per-campaign entry id for s from its
// position in campaignSettlements. Callers must already hold
// campaignSettlementsMu.
func settlementEntryID(s *playSettlement) int {
	for i, existing := range campaignSettlements[s.CampaignID] {
		if existing == s {
			return i
		}
	}
	return len(campaignSettlements[s.CampaignID])
}

func saveSettlementToDB(s *playSettlement) error {
	servicesRaw, err := json.Marshal(s.Services)
	if err != nil {
		return err
	}
	discoveredRaw, err := json.Marshal(s.DiscoveredBy)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		`INSERT INTO play_settlements (campaign_id, entry_id, settlement_id, name, services, availability, discovered_by) VALUES (?, ?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, entry_id) DO UPDATE SET name = excluded.name, services = excluded.services, availability = excluded.availability, discovered_by = excluded.discovered_by`,
		s.CampaignID, settlementEntryID(s), s.SettlementID, s.Name, string(servicesRaw), s.Availability, string(discoveredRaw),
	)
	return err
}

func loadShopsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price FROM play_shops ORDER BY campaign_id, settlement_id, shop_id`)
	if err != nil {
		log.Fatalf("failed to load shops: %v", err)
	}
	defer rows.Close()

	campaignShopsMu.Lock()
	defer campaignShopsMu.Unlock()
	for rows.Next() {
		s := &playShop{}
		var stockRaw string
		if err := rows.Scan(&s.CampaignID, &s.SettlementID, &s.ShopID, &s.Name, &stockRaw, &s.BuyPrice, &s.SellPrice); err != nil {
			log.Fatalf("failed to scan shop row: %v", err)
		}
		if err := json.Unmarshal([]byte(stockRaw), &s.Stock); err != nil {
			log.Fatalf("failed to decode shop stock: %v", err)
		}
		if campaignShops[s.CampaignID] == nil {
			campaignShops[s.CampaignID] = map[string][]*playShop{}
		}
		campaignShops[s.CampaignID][s.SettlementID] = append(campaignShops[s.CampaignID][s.SettlementID], s)
	}
}

func saveShopToDB(s *playShop) error {
	stockRaw, err := json.Marshal(s.Stock)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		`INSERT INTO play_shops (campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price) VALUES (?, ?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, settlement_id, shop_id) DO UPDATE SET name = excluded.name, stock = excluded.stock, buy_price = excluded.buy_price, sell_price = excluded.sell_price`,
		s.CampaignID, s.SettlementID, s.ShopID, s.Name, string(stockRaw), s.BuyPrice, s.SellPrice,
	)
	return err
}

func loadRecipesFromDB() {
	rows, err := db.Query(`SELECT campaign_id, entry_id, recipe_id, name, ingredients, output_item, output_quantity FROM play_recipes ORDER BY campaign_id, entry_id`)
	if err != nil {
		log.Fatalf("failed to load recipes: %v", err)
	}
	defer rows.Close()

	campaignRecipesMu.Lock()
	defer campaignRecipesMu.Unlock()
	for rows.Next() {
		rec := &playRecipe{}
		var entryID int
		var ingredientsRaw string
		if err := rows.Scan(&rec.CampaignID, &entryID, &rec.RecipeID, &rec.Name, &ingredientsRaw, &rec.OutputItem, &rec.OutputQuantity); err != nil {
			log.Fatalf("failed to scan recipe row: %v", err)
		}
		if err := json.Unmarshal([]byte(ingredientsRaw), &rec.Ingredients); err != nil {
			log.Fatalf("failed to decode recipe ingredients: %v", err)
		}
		campaignRecipes[rec.CampaignID] = append(campaignRecipes[rec.CampaignID], rec)
	}
}

// recipeEntryID derives a stable per-campaign entry id for rec from its
// position in campaignRecipes. Callers must already hold campaignRecipesMu.
func recipeEntryID(rec *playRecipe) int {
	for i, existing := range campaignRecipes[rec.CampaignID] {
		if existing == rec {
			return i
		}
	}
	return len(campaignRecipes[rec.CampaignID])
}

func saveRecipeToDB(rec *playRecipe) error {
	ingredientsRaw, err := json.Marshal(rec.Ingredients)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		`INSERT INTO play_recipes (campaign_id, entry_id, recipe_id, name, ingredients, output_item, output_quantity) VALUES (?, ?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, entry_id) DO UPDATE SET name = excluded.name, ingredients = excluded.ingredients, output_item = excluded.output_item, output_quantity = excluded.output_quantity`,
		rec.CampaignID, recipeEntryID(rec), rec.RecipeID, rec.Name, string(ingredientsRaw), rec.OutputItem, rec.OutputQuantity,
	)
	return err
}

func loadDowntimeActivitiesFromDB() {
	rows, err := db.Query(`SELECT campaign_id, activity_id, name, cycles_required FROM play_downtime_activities ORDER BY campaign_id, activity_id`)
	if err != nil {
		log.Fatalf("failed to load downtime activities: %v", err)
	}
	defer rows.Close()

	downtimeActivitiesMu.Lock()
	defer downtimeActivitiesMu.Unlock()
	for rows.Next() {
		act := &playDowntimeActivity{}
		if err := rows.Scan(&act.CampaignID, &act.ActivityID, &act.Name, &act.CyclesRequired); err != nil {
			log.Fatalf("failed to scan downtime activity row: %v", err)
		}
		downtimeActivities[act.CampaignID] = append(downtimeActivities[act.CampaignID], act)
	}
}

func saveDowntimeActivityToDB(act *playDowntimeActivity) error {
	_, err := db.Exec(
		`INSERT INTO play_downtime_activities (campaign_id, activity_id, name, cycles_required) VALUES (?, ?, ?, ?)`,
		act.CampaignID, act.ActivityID, act.Name, act.CyclesRequired,
	)
	return err
}

func loadDowntimeAllocationsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, character_id, activity_id, cycles_completed, completions FROM play_downtime_allocations ORDER BY campaign_id, character_id, activity_id`)
	if err != nil {
		log.Fatalf("failed to load downtime allocations: %v", err)
	}
	defer rows.Close()

	downtimeAllocationsMu.Lock()
	defer downtimeAllocationsMu.Unlock()
	for rows.Next() {
		a := &playDowntimeAllocation{}
		if err := rows.Scan(&a.CampaignID, &a.CharacterID, &a.ActivityID, &a.CyclesCompleted, &a.Completions); err != nil {
			log.Fatalf("failed to scan downtime allocation row: %v", err)
		}
		if downtimeAllocations[a.CampaignID] == nil {
			downtimeAllocations[a.CampaignID] = map[string]map[string]*playDowntimeAllocation{}
		}
		if downtimeAllocations[a.CampaignID][a.CharacterID] == nil {
			downtimeAllocations[a.CampaignID][a.CharacterID] = map[string]*playDowntimeAllocation{}
		}
		downtimeAllocations[a.CampaignID][a.CharacterID][a.ActivityID] = a
	}
}

func saveDowntimeAllocationToDB(a *playDowntimeAllocation) error {
	_, err := db.Exec(
		`INSERT INTO play_downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, character_id, activity_id) DO UPDATE SET cycles_completed = excluded.cycles_completed, completions = excluded.completions`,
		a.CampaignID, a.CharacterID, a.ActivityID, a.CyclesCompleted, a.Completions,
	)
	return err
}

func loadSessionZeroFromDB() {
	rows, err := db.Query(`SELECT campaign_id, rules, tone, consent FROM play_session_zero`)
	if err != nil {
		log.Fatalf("failed to load session-zero settings: %v", err)
	}
	defer rows.Close()

	sessionZeroMu.Lock()
	defer sessionZeroMu.Unlock()
	for rows.Next() {
		s := &sessionZeroSettings{}
		var consentRaw string
		if err := rows.Scan(&s.CampaignID, &s.Rules, &s.Tone, &consentRaw); err != nil {
			log.Fatalf("failed to scan session-zero row: %v", err)
		}
		if err := json.Unmarshal([]byte(consentRaw), &s.Consent); err != nil {
			log.Fatalf("failed to decode session-zero consent: %v", err)
		}
		sessionZeroByCampaign[s.CampaignID] = s
	}
}

func saveSessionZeroToDB(s *sessionZeroSettings) error {
	consentRaw, err := json.Marshal(s.Consent)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		`INSERT INTO play_session_zero (campaign_id, rules, tone, consent) VALUES (?, ?, ?, ?)
		 ON CONFLICT(campaign_id) DO UPDATE SET rules = excluded.rules, tone = excluded.tone, consent = excluded.consent`,
		s.CampaignID, s.Rules, s.Tone, string(consentRaw),
	)
	return err
}

func loadContentFromDB() {
	rows, err := db.Query(`SELECT campaign_id, content_id, kind, text, tags FROM play_content ORDER BY campaign_id, entry_id`)
	if err != nil {
		log.Fatalf("failed to load content: %v", err)
	}
	defer rows.Close()

	campaignContentMu.Lock()
	defer campaignContentMu.Unlock()
	for rows.Next() {
		c := &playContent{}
		var tagsRaw string
		if err := rows.Scan(&c.CampaignID, &c.ContentID, &c.Kind, &c.Text, &tagsRaw); err != nil {
			log.Fatalf("failed to scan content row: %v", err)
		}
		if err := json.Unmarshal([]byte(tagsRaw), &c.Tags); err != nil {
			log.Fatalf("failed to decode content tags: %v", err)
		}
		campaignContent[c.CampaignID] = append(campaignContent[c.CampaignID], c)
	}
}

// contentEntryID derives a stable per-campaign entry id for c from its
// position in campaignContent. Callers must already hold campaignContentMu.
func contentEntryID(c *playContent) int {
	for i, existing := range campaignContent[c.CampaignID] {
		if existing == c {
			return i
		}
	}
	return len(campaignContent[c.CampaignID])
}

func saveContentToDB(c *playContent) error {
	tagsRaw, err := json.Marshal(c.Tags)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		`INSERT INTO play_content (campaign_id, content_id, entry_id, kind, text, tags) VALUES (?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, content_id) DO UPDATE SET kind = excluded.kind, text = excluded.text, tags = excluded.tags`,
		c.CampaignID, c.ContentID, contentEntryID(c), c.Kind, c.Text, string(tagsRaw),
	)
	return err
}

func loadNotesFromDB() {
	rows, err := db.Query(`SELECT campaign_id, note_id, text, visibility, owner FROM play_notes ORDER BY campaign_id, entry_id`)
	if err != nil {
		log.Fatalf("failed to load notes: %v", err)
	}
	defer rows.Close()

	campaignNotesMu.Lock()
	defer campaignNotesMu.Unlock()
	for rows.Next() {
		n := &playNote{}
		if err := rows.Scan(&n.CampaignID, &n.NoteID, &n.Text, &n.Visibility, &n.Owner); err != nil {
			log.Fatalf("failed to scan note row: %v", err)
		}
		campaignNotes[n.CampaignID] = append(campaignNotes[n.CampaignID], n)
	}
}

// noteEntryID derives a stable per-campaign entry id for n from its position
// in campaignNotes. Callers must already hold campaignNotesMu.
func noteEntryID(n *playNote) int {
	for i, existing := range campaignNotes[n.CampaignID] {
		if existing == n {
			return i
		}
	}
	return len(campaignNotes[n.CampaignID])
}

func saveNoteToDB(n *playNote) error {
	_, err := db.Exec(
		`INSERT INTO play_notes (campaign_id, note_id, entry_id, text, visibility, owner) VALUES (?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, note_id) DO UPDATE SET text = excluded.text, visibility = excluded.visibility`,
		n.CampaignID, n.NoteID, noteEntryID(n), n.Text, n.Visibility, n.Owner,
	)
	return err
}

func loadWhispersFromDB() {
	rows, err := db.Query(`SELECT campaign_id, whisper_id, from_character_id, to_character_id, text FROM play_whispers ORDER BY campaign_id, entry_id`)
	if err != nil {
		log.Fatalf("failed to load whispers: %v", err)
	}
	defer rows.Close()

	campaignWhispersMu.Lock()
	defer campaignWhispersMu.Unlock()
	for rows.Next() {
		wh := &playWhisper{}
		if err := rows.Scan(&wh.CampaignID, &wh.WhisperID, &wh.FromCharacterID, &wh.ToCharacterID, &wh.Text); err != nil {
			log.Fatalf("failed to scan whisper row: %v", err)
		}
		campaignWhispers[wh.CampaignID] = append(campaignWhispers[wh.CampaignID], wh)
	}
}

// whisperEntryID derives a stable per-campaign entry id for wh from its
// position in campaignWhispers. Callers must already hold campaignWhispersMu.
func whisperEntryID(wh *playWhisper) int {
	for i, existing := range campaignWhispers[wh.CampaignID] {
		if existing == wh {
			return i
		}
	}
	return len(campaignWhispers[wh.CampaignID])
}

func saveWhisperToDB(wh *playWhisper) error {
	_, err := db.Exec(
		`INSERT INTO play_whispers (campaign_id, whisper_id, entry_id, from_character_id, to_character_id, text) VALUES (?, ?, ?, ?, ?, ?)`,
		wh.CampaignID, wh.WhisperID, whisperEntryID(wh), wh.FromCharacterID, wh.ToCharacterID, wh.Text,
	)
	return err
}

func loadInvitationsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, invitation_id, username, character_id, status FROM play_invitations ORDER BY campaign_id, entry_id`)
	if err != nil {
		log.Fatalf("failed to load invitations: %v", err)
	}
	defer rows.Close()

	campaignInvitationsMu.Lock()
	defer campaignInvitationsMu.Unlock()
	for rows.Next() {
		inv := &playInvitation{}
		if err := rows.Scan(&inv.CampaignID, &inv.InvitationID, &inv.Username, &inv.CharacterID, &inv.Status); err != nil {
			log.Fatalf("failed to scan invitation row: %v", err)
		}
		campaignInvitations[inv.CampaignID] = append(campaignInvitations[inv.CampaignID], inv)
	}
}

// invitationEntryID derives a stable per-campaign entry id for inv from its
// position in campaignInvitations. Callers must already hold
// campaignInvitationsMu.
func invitationEntryID(inv *playInvitation) int {
	for i, existing := range campaignInvitations[inv.CampaignID] {
		if existing == inv {
			return i
		}
	}
	return len(campaignInvitations[inv.CampaignID])
}

func saveInvitationToDB(inv *playInvitation) error {
	_, err := db.Exec(
		`INSERT INTO play_invitations (campaign_id, invitation_id, entry_id, username, character_id, status) VALUES (?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, invitation_id) DO UPDATE SET status = excluded.status`,
		inv.CampaignID, inv.InvitationID, invitationEntryID(inv), inv.Username, inv.CharacterID, inv.Status,
	)
	return err
}

func loadSpectatorsFromDB() {
	rows, err := db.Query(`SELECT spectator_id, campaign_id FROM play_spectators`)
	if err != nil {
		log.Fatalf("failed to load spectators: %v", err)
	}
	defer rows.Close()

	playSpectatorsMu.Lock()
	defer playSpectatorsMu.Unlock()
	for rows.Next() {
		s := &playSpectator{}
		if err := rows.Scan(&s.SpectatorID, &s.CampaignID); err != nil {
			log.Fatalf("failed to scan spectator row: %v", err)
		}
		playSpectators[s.SpectatorID] = s
	}
}

func saveSpectatorToDB(s *playSpectator) error {
	_, err := db.Exec(
		`INSERT INTO play_spectators (spectator_id, campaign_id) VALUES (?, ?)`,
		s.SpectatorID, s.CampaignID,
	)
	return err
}

func loadDelegationsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, username, powers, active FROM play_delegations`)
	if err != nil {
		log.Fatalf("failed to load delegations: %v", err)
	}
	defer rows.Close()

	campaignDelegationsMu.Lock()
	defer campaignDelegationsMu.Unlock()
	for rows.Next() {
		d := &playDelegation{}
		var powersRaw string
		var active int
		if err := rows.Scan(&d.CampaignID, &d.Username, &powersRaw, &active); err != nil {
			log.Fatalf("failed to scan delegation row: %v", err)
		}
		d.Powers = decodeOrderOverride(powersRaw)
		d.Active = active != 0
		if campaignDelegations[d.CampaignID] == nil {
			campaignDelegations[d.CampaignID] = map[string]*playDelegation{}
		}
		campaignDelegations[d.CampaignID][d.Username] = d
	}
}

func saveDelegationToDB(d *playDelegation) error {
	active := 0
	if d.Active {
		active = 1
	}
	_, err := db.Exec(
		`INSERT INTO play_delegations (campaign_id, username, powers, active) VALUES (?, ?, ?, ?)
		 ON CONFLICT(campaign_id, username) DO UPDATE SET powers = excluded.powers, active = excluded.active`,
		d.CampaignID, d.Username, encodeOrderOverride(d.Powers), active,
	)
	return err
}

func loadDelegationAuditFromDB() {
	rows, err := db.Query(`SELECT campaign_id, username, action, powers FROM play_delegation_audit ORDER BY campaign_id, entry_id`)
	if err != nil {
		log.Fatalf("failed to load delegation audit: %v", err)
	}
	defer rows.Close()

	campaignDelegationAuditMu.Lock()
	defer campaignDelegationAuditMu.Unlock()
	for rows.Next() {
		e := &playDelegationAuditEntry{}
		var powersRaw string
		if err := rows.Scan(&e.CampaignID, &e.Username, &e.Action, &powersRaw); err != nil {
			log.Fatalf("failed to scan delegation audit row: %v", err)
		}
		e.Powers = decodeOrderOverride(powersRaw)
		campaignDelegationAudit[e.CampaignID] = append(campaignDelegationAudit[e.CampaignID], e)
	}
}

// delegationAuditEntryID derives a stable per-campaign entry id for e from
// its position in campaignDelegationAudit. Callers must already hold
// campaignDelegationAuditMu.
func delegationAuditEntryID(e *playDelegationAuditEntry) int {
	for i, existing := range campaignDelegationAudit[e.CampaignID] {
		if existing == e {
			return i
		}
	}
	return len(campaignDelegationAudit[e.CampaignID])
}

func saveDelegationAuditToDB(e *playDelegationAuditEntry) error {
	_, err := db.Exec(
		`INSERT INTO play_delegation_audit (campaign_id, entry_id, username, action, powers) VALUES (?, ?, ?, ?, ?)`,
		e.CampaignID, delegationAuditEntryID(e), e.Username, e.Action, encodeOrderOverride(e.Powers),
	)
	return err
}

func loadAuditEventsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, timestamp, kind, actor, role, correlation_id FROM play_audit_events ORDER BY campaign_id, timestamp`)
	if err != nil {
		log.Fatalf("failed to load audit events: %v", err)
	}
	defer rows.Close()

	campaignAuditMu.Lock()
	defer campaignAuditMu.Unlock()
	for rows.Next() {
		e := &playAuditEntry{}
		if err := rows.Scan(&e.CampaignID, &e.Timestamp, &e.Kind, &e.Actor, &e.Role, &e.CorrelationID); err != nil {
			log.Fatalf("failed to scan audit event row: %v", err)
		}
		campaignAudit[e.CampaignID] = append(campaignAudit[e.CampaignID], e)
	}
}

func saveAuditEventToDB(e *playAuditEntry) error {
	_, err := db.Exec(
		`INSERT INTO play_audit_events (campaign_id, timestamp, kind, actor, role, correlation_id) VALUES (?, ?, ?, ?, ?, ?)`,
		e.CampaignID, e.Timestamp, e.Kind, e.Actor, e.Role, e.CorrelationID,
	)
	return err
}

func loadProjectionEventsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, sequence, event_id, kind, value, has_value FROM play_projection_events ORDER BY campaign_id, sequence`)
	if err != nil {
		log.Fatalf("failed to load projection events: %v", err)
	}
	defer rows.Close()

	campaignProjectionsMu.Lock()
	defer campaignProjectionsMu.Unlock()
	for rows.Next() {
		e := &projectionEvent{}
		var hasValue int
		if err := rows.Scan(&e.CampaignID, &e.Sequence, &e.EventID, &e.Kind, &e.Value, &hasValue); err != nil {
			log.Fatalf("failed to scan projection event row: %v", err)
		}
		e.HasValue = hasValue != 0
		campaignProjectionEvents[e.CampaignID] = append(campaignProjectionEvents[e.CampaignID], e)
	}
}

func saveProjectionEventToDB(e *projectionEvent) error {
	hasValue := 0
	if e.HasValue {
		hasValue = 1
	}
	_, err := db.Exec(
		`INSERT INTO play_projection_events (campaign_id, sequence, event_id, kind, value, has_value) VALUES (?, ?, ?, ?, ?, ?)`,
		e.CampaignID, e.Sequence, e.EventID, e.Kind, e.Value, hasValue,
	)
	return err
}

func loadIdempotentEventsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, sequence, event_id, value, idempotency_key FROM play_idempotent_events ORDER BY campaign_id, sequence`)
	if err != nil {
		log.Fatalf("failed to load idempotent events: %v", err)
	}
	defer rows.Close()

	campaignIdempotentEventsMu.Lock()
	defer campaignIdempotentEventsMu.Unlock()
	for rows.Next() {
		e := &idempotentEvent{}
		if err := rows.Scan(&e.CampaignID, &e.Sequence, &e.EventID, &e.Value, &e.IdempotencyKey); err != nil {
			log.Fatalf("failed to scan idempotent event row: %v", err)
		}
		campaignIdempotentEvents[e.CampaignID] = append(campaignIdempotentEvents[e.CampaignID], e)
	}
}

func saveIdempotentEventToDB(e *idempotentEvent) error {
	_, err := db.Exec(
		`INSERT INTO play_idempotent_events (campaign_id, sequence, event_id, value, idempotency_key) VALUES (?, ?, ?, ?, ?)`,
		e.CampaignID, e.Sequence, e.EventID, e.Value, e.IdempotencyKey,
	)
	return err
}

func loadSafeTurnsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, sequence, submission_id, action, accepted_turn, next_turn FROM play_safe_turns ORDER BY campaign_id, sequence`)
	if err != nil {
		log.Fatalf("failed to load safe turns: %v", err)
	}
	defer rows.Close()

	campaignSafeTurnsMu.Lock()
	defer campaignSafeTurnsMu.Unlock()
	for rows.Next() {
		t := &acceptedSafeTurn{}
		var sequence int
		if err := rows.Scan(&t.CampaignID, &sequence, &t.SubmissionID, &t.Action, &t.AcceptedTurn, &t.NextTurn); err != nil {
			log.Fatalf("failed to scan safe turn row: %v", err)
		}
		campaignSafeTurnHistory[t.CampaignID] = append(campaignSafeTurnHistory[t.CampaignID], t)
		campaignSafeTurnState[t.CampaignID] = t.NextTurn
		if campaignSafeTurnSeen[t.CampaignID] == nil {
			campaignSafeTurnSeen[t.CampaignID] = map[string]bool{}
		}
		campaignSafeTurnSeen[t.CampaignID][t.SubmissionID] = true
	}
}

func saveSafeTurnToDB(t *acceptedSafeTurn) error {
	sequence := len(campaignSafeTurnHistory[t.CampaignID]) + 1
	_, err := db.Exec(
		`INSERT INTO play_safe_turns (campaign_id, sequence, submission_id, action, accepted_turn, next_turn) VALUES (?, ?, ?, ?, ?, ?)`,
		t.CampaignID, sequence, t.SubmissionID, t.Action, t.AcceptedTurn, t.NextTurn,
	)
	return err
}

func saveTransferToDB(t *playTransfer) error {
	_, err := db.Exec(
		`INSERT INTO play_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold) VALUES (?, ?, ?, ?, ?)`,
		t.CampaignID, t.TransferID, t.FromCharacterID, t.ToCharacterID, t.Gold,
	)
	return err
}

func loadTransactionalTransfersFromDB() {
	rows, err := db.Query(`SELECT campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold FROM play_transactional_transfers ORDER BY campaign_id, sequence`)
	if err != nil {
		log.Fatalf("failed to load transactional transfers: %v", err)
	}
	defer rows.Close()

	transactionalTransfersMu.Lock()
	defer transactionalTransfersMu.Unlock()
	for rows.Next() {
		t := &transactionalTransfer{}
		if err := rows.Scan(&t.CampaignID, &t.Sequence, &t.FromCharacterID, &t.ToCharacterID, &t.Amount, &t.FromGold, &t.ToGold); err != nil {
			log.Fatalf("failed to scan transactional transfer row: %v", err)
		}
		transactionalTransfers[t.CampaignID] = append(transactionalTransfers[t.CampaignID], t)
	}
}

func saveTransactionalTransferToDB(t *transactionalTransfer) error {
	_, err := db.Exec(
		`INSERT INTO play_transactional_transfers (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) VALUES (?, ?, ?, ?, ?, ?, ?)`,
		t.CampaignID, t.Sequence, t.FromCharacterID, t.ToCharacterID, t.Amount, t.FromGold, t.ToGold,
	)
	return err
}

func loadCampaignExportsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, version, story, status FROM play_campaign_exports ORDER BY campaign_id, version`)
	if err != nil {
		log.Fatalf("failed to load campaign exports: %v", err)
	}
	defer rows.Close()

	campaignExportsMu.Lock()
	defer campaignExportsMu.Unlock()
	for rows.Next() {
		e := &campaignExport{}
		if err := rows.Scan(&e.CampaignID, &e.Version, &e.Story, &e.Status); err != nil {
			log.Fatalf("failed to scan campaign export row: %v", err)
		}
		campaignExports[e.CampaignID] = append(campaignExports[e.CampaignID], e)
	}
}

func saveCampaignExportToDB(e *campaignExport) error {
	_, err := db.Exec(
		`INSERT INTO play_campaign_exports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)`,
		e.CampaignID, e.Version, e.Story, e.Status,
	)
	return err
}

func loadCampaignBackupsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, sequence, backup_id, story, status FROM play_campaign_backups ORDER BY campaign_id, sequence`)
	if err != nil {
		log.Fatalf("failed to load campaign backups: %v", err)
	}
	defer rows.Close()

	campaignBackupsMu.Lock()
	defer campaignBackupsMu.Unlock()
	for rows.Next() {
		b := &campaignBackup{}
		if err := rows.Scan(&b.CampaignID, &b.Sequence, &b.BackupID, &b.Story, &b.Status); err != nil {
			log.Fatalf("failed to scan campaign backup row: %v", err)
		}
		campaignBackups[b.CampaignID] = append(campaignBackups[b.CampaignID], b)
	}
}

func saveCampaignBackupToDB(b *campaignBackup) error {
	_, err := db.Exec(
		`INSERT INTO play_campaign_backups (campaign_id, sequence, backup_id, story, status) VALUES (?, ?, ?, ?, ?)`,
		b.CampaignID, b.Sequence, b.BackupID, b.Story, b.Status,
	)
	return err
}

func loadReplayEventsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, sequence, event_id, kind, text FROM play_replay_events ORDER BY campaign_id, sequence`)
	if err != nil {
		log.Fatalf("failed to load replay events: %v", err)
	}
	defer rows.Close()

	campaignReplayEventsMu.Lock()
	defer campaignReplayEventsMu.Unlock()
	for rows.Next() {
		e := &replayEvent{}
		if err := rows.Scan(&e.CampaignID, &e.Sequence, &e.EventID, &e.Kind, &e.Text); err != nil {
			log.Fatalf("failed to scan replay event row: %v", err)
		}
		campaignReplayEvents[e.CampaignID] = append(campaignReplayEvents[e.CampaignID], e)
	}
}

func saveReplayEventToDB(e *replayEvent) error {
	_, err := db.Exec(
		`INSERT INTO play_replay_events (campaign_id, sequence, event_id, kind, text) VALUES (?, ?, ?, ?, ?)`,
		e.CampaignID, e.Sequence, e.EventID, e.Kind, e.Text,
	)
	return err
}

func loadRngLedgersFromDB() {
	rngLedgersMu.Lock()
	defer rngLedgersMu.Unlock()

	seedRows, err := db.Query(`SELECT campaign_id, seed FROM play_rng_seeds`)
	if err != nil {
		log.Fatalf("failed to load rng seeds: %v", err)
	}
	defer seedRows.Close()
	for seedRows.Next() {
		var campaignID, seed string
		if err := seedRows.Scan(&campaignID, &seed); err != nil {
			log.Fatalf("failed to scan rng seed row: %v", err)
		}
		rngLedgers[campaignID] = &rngLedger{CampaignID: campaignID, Seed: seed, Rolls: []*rngRoll{}}
	}

	rollRows, err := db.Query(`SELECT campaign_id, sequence, roll_id, sides, result FROM play_rng_rolls ORDER BY campaign_id, sequence`)
	if err != nil {
		log.Fatalf("failed to load rng rolls: %v", err)
	}
	defer rollRows.Close()
	for rollRows.Next() {
		roll := &rngRoll{}
		if err := rollRows.Scan(&roll.CampaignID, &roll.Sequence, &roll.RollID, &roll.Sides, &roll.Result); err != nil {
			log.Fatalf("failed to scan rng roll row: %v", err)
		}
		if l, ok := rngLedgers[roll.CampaignID]; ok {
			l.Rolls = append(l.Rolls, roll)
		}
	}
}

func saveRngSeedToDB(l *rngLedger) error {
	_, err := db.Exec(
		`INSERT INTO play_rng_seeds (campaign_id, seed) VALUES (?, ?)`,
		l.CampaignID, l.Seed,
	)
	return err
}

func saveRngRollToDB(roll *rngRoll) error {
	_, err := db.Exec(
		`INSERT INTO play_rng_rolls (campaign_id, sequence, roll_id, sides, result) VALUES (?, ?, ?, ?, ?)`,
		roll.CampaignID, roll.Sequence, roll.RollID, roll.Sides, roll.Result,
	)
	return err
}

func loadModerationReportsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM play_moderation_reports ORDER BY campaign_id, sequence`)
	if err != nil {
		log.Fatalf("failed to load moderation reports: %v", err)
	}
	defer rows.Close()

	moderationReportsMu.Lock()
	defer moderationReportsMu.Unlock()
	for rows.Next() {
		rep := &moderationReport{}
		if err := rows.Scan(&rep.CampaignID, &rep.ReportID, &rep.TargetID, &rep.Reason, &rep.Status, &rep.Reporter, &rep.Sequence, &rep.Action, &rep.Note, &rep.Resolver); err != nil {
			log.Fatalf("failed to scan moderation report row: %v", err)
		}
		moderationReports[rep.CampaignID] = append(moderationReports[rep.CampaignID], rep)
	}
}

func saveModerationReportToDB(rep *moderationReport) error {
	_, err := db.Exec(
		`INSERT INTO play_moderation_reports (campaign_id, report_id, target_id, reason, status, reporter, sequence, action, note, resolver)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		 ON CONFLICT (campaign_id, report_id) DO UPDATE SET status = excluded.status, action = excluded.action, note = excluded.note, resolver = excluded.resolver`,
		rep.CampaignID, rep.ReportID, rep.TargetID, rep.Reason, rep.Status, rep.Reporter, rep.Sequence, rep.Action, rep.Note, rep.Resolver,
	)
	return err
}

func loadSafetyBoundariesFromDB() {
	rows, err := db.Query(`SELECT campaign_id, blocked_tags FROM play_safety_boundaries`)
	if err != nil {
		log.Fatalf("failed to load safety boundaries: %v", err)
	}
	defer rows.Close()

	safetyBoundariesMu.Lock()
	defer safetyBoundariesMu.Unlock()
	for rows.Next() {
		b := &safetyBoundary{}
		var tagsRaw string
		if err := rows.Scan(&b.CampaignID, &tagsRaw); err != nil {
			log.Fatalf("failed to scan safety boundary row: %v", err)
		}
		if err := json.Unmarshal([]byte(tagsRaw), &b.BlockedTags); err != nil {
			log.Fatalf("failed to decode safety boundary tags: %v", err)
		}
		safetyBoundaries[b.CampaignID] = b
	}
}

func saveSafetyBoundaryToDB(b *safetyBoundary) error {
	tagsRaw, err := json.Marshal(b.BlockedTags)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		`INSERT INTO play_safety_boundaries (campaign_id, blocked_tags) VALUES (?, ?)
		 ON CONFLICT(campaign_id) DO UPDATE SET blocked_tags = excluded.blocked_tags`,
		b.CampaignID, string(tagsRaw),
	)
	return err
}

func loadSafetyEventsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, event_id, kind, text, tags, sequence FROM play_safety_events ORDER BY campaign_id, sequence`)
	if err != nil {
		log.Fatalf("failed to load safety events: %v", err)
	}
	defer rows.Close()

	safetyEventsMu.Lock()
	defer safetyEventsMu.Unlock()
	for rows.Next() {
		ev := &safetyEvent{}
		var tagsRaw string
		if err := rows.Scan(&ev.CampaignID, &ev.EventID, &ev.Kind, &ev.Text, &tagsRaw, &ev.Sequence); err != nil {
			log.Fatalf("failed to scan safety event row: %v", err)
		}
		if err := json.Unmarshal([]byte(tagsRaw), &ev.Tags); err != nil {
			log.Fatalf("failed to decode safety event tags: %v", err)
		}
		safetyEvents[ev.CampaignID] = append(safetyEvents[ev.CampaignID], ev)
	}
}

func saveSafetyEventToDB(ev *safetyEvent) error {
	tagsRaw, err := json.Marshal(ev.Tags)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		`INSERT INTO play_safety_events (campaign_id, event_id, kind, text, tags, sequence) VALUES (?, ?, ?, ?, ?, ?)`,
		ev.CampaignID, ev.EventID, ev.Kind, ev.Text, string(tagsRaw), ev.Sequence,
	)
	return err
}

func loadFixtureStatesFromDB() {
	rows, err := db.Query(`SELECT campaign_id, fixture_id, status, characters, story, event_ids FROM play_fixture_states`)
	if err != nil {
		log.Fatalf("failed to load fixture states: %v", err)
	}
	defer rows.Close()

	fixtureStatesMu.Lock()
	defer fixtureStatesMu.Unlock()
	for rows.Next() {
		s := &fixtureState{}
		var charactersRaw, eventIDsRaw string
		if err := rows.Scan(&s.CampaignID, &s.FixtureID, &s.Status, &charactersRaw, &s.Story, &eventIDsRaw); err != nil {
			log.Fatalf("failed to scan fixture state row: %v", err)
		}
		if err := json.Unmarshal([]byte(charactersRaw), &s.Characters); err != nil {
			log.Fatalf("failed to decode fixture state characters: %v", err)
		}
		if err := json.Unmarshal([]byte(eventIDsRaw), &s.EventIDs); err != nil {
			log.Fatalf("failed to decode fixture state event ids: %v", err)
		}
		fixtureStates[s.CampaignID] = s
	}
}

func saveFixtureStateToDB(s *fixtureState) error {
	charactersRaw, err := json.Marshal(s.Characters)
	if err != nil {
		return err
	}
	eventIDsRaw, err := json.Marshal(s.EventIDs)
	if err != nil {
		return err
	}
	_, err = db.Exec(
		`INSERT INTO play_fixture_states (campaign_id, fixture_id, status, characters, story, event_ids) VALUES (?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id) DO UPDATE SET fixture_id = excluded.fixture_id, status = excluded.status, characters = excluded.characters, story = excluded.story, event_ids = excluded.event_ids`,
		s.CampaignID, s.FixtureID, s.Status, string(charactersRaw), s.Story, string(eventIDsRaw),
	)
	return err
}

func loadCampaignImportsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, version, story, status FROM play_campaign_imports`)
	if err != nil {
		log.Fatalf("failed to load campaign imports: %v", err)
	}
	defer rows.Close()

	campaignImportsMu.Lock()
	defer campaignImportsMu.Unlock()
	for rows.Next() {
		s := &campaignImportState{}
		if err := rows.Scan(&s.CampaignID, &s.Version, &s.Story, &s.Status); err != nil {
			log.Fatalf("failed to scan campaign import row: %v", err)
		}
		campaignImports[s.CampaignID] = s
	}
}

func saveCampaignImportToDB(s *campaignImportState) error {
	_, err := db.Exec(
		`INSERT INTO play_campaign_imports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)
		 ON CONFLICT(campaign_id) DO UPDATE SET version = excluded.version, story = excluded.story, status = excluded.status`,
		s.CampaignID, s.Version, s.Story, s.Status,
	)
	return err
}

func loadCampaignMigrationsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, schema_version, story, campaign_name FROM play_campaign_migrations`)
	if err != nil {
		log.Fatalf("failed to load campaign migrations: %v", err)
	}
	defer rows.Close()

	campaignMigrationsMu.Lock()
	defer campaignMigrationsMu.Unlock()
	for rows.Next() {
		s := &campaignMigrationState{}
		if err := rows.Scan(&s.CampaignID, &s.SchemaVer, &s.Story, &s.CampaignName); err != nil {
			log.Fatalf("failed to scan campaign migration row: %v", err)
		}
		campaignMigrations[s.CampaignID] = s
	}
}

func saveCampaignMigrationToDB(s *campaignMigrationState) error {
	_, err := db.Exec(
		`INSERT INTO play_campaign_migrations (campaign_id, schema_version, story, campaign_name) VALUES (?, ?, ?, ?)
		 ON CONFLICT(campaign_id) DO UPDATE SET schema_version = excluded.schema_version, story = excluded.story, campaign_name = excluded.campaign_name`,
		s.CampaignID, s.SchemaVer, s.Story, s.CampaignName,
	)
	return err
}

// encodeOrderOverride serializes a combatant target-id order as a
// comma-separated string for storage; target ids (monster ids and member
// usernames) never contain commas.
func encodeOrderOverride(order []string) string {
	return strings.Join(order, ",")
}

func decodeOrderOverride(raw string) []string {
	if raw == "" {
		return nil
	}
	return strings.Split(raw, ",")
}

func loadPlayMonstersFromDB() {
	rows, err := db.Query(`SELECT campaign_id, encounter_id, monster_id, name, hp_max, hp_current, initiative FROM play_monsters`)
	if err != nil {
		log.Fatalf("failed to load play monsters: %v", err)
	}
	defer rows.Close()

	playMonstersMu.Lock()
	defer playMonstersMu.Unlock()
	for rows.Next() {
		m := &playMonster{}
		if err := rows.Scan(&m.CampaignID, &m.EncounterID, &m.MonsterID, &m.Name, &m.HPMax, &m.HPCurrent, &m.Initiative); err != nil {
			log.Fatalf("failed to scan play monster row: %v", err)
		}
		if playMonsters[m.CampaignID] == nil {
			playMonsters[m.CampaignID] = map[string]map[string]*playMonster{}
		}
		if playMonsters[m.CampaignID][m.EncounterID] == nil {
			playMonsters[m.CampaignID][m.EncounterID] = map[string]*playMonster{}
		}
		playMonsters[m.CampaignID][m.EncounterID][m.MonsterID] = m
	}
}

func savePlayMonsterToDB(m *playMonster) error {
	_, err := db.Exec(
		`INSERT INTO play_monsters (campaign_id, encounter_id, monster_id, name, hp_max, hp_current, initiative)
		 VALUES (?, ?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, encounter_id, monster_id) DO UPDATE SET
		 	name = excluded.name, hp_max = excluded.hp_max, hp_current = excluded.hp_current, initiative = excluded.initiative`,
		m.CampaignID, m.EncounterID, m.MonsterID, m.Name, m.HPMax, m.HPCurrent, m.Initiative,
	)
	return err
}

func deletePlayMonsterFromDB(campaignID, encounterID, monsterID string) error {
	_, err := db.Exec(
		`DELETE FROM play_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?`,
		campaignID, encounterID, monsterID,
	)
	return err
}

func loadPlayCombatantsFromDB() {
	rows, err := db.Query(`SELECT campaign_id, encounter_id, member, character_id, name, initiative FROM play_combatants`)
	if err != nil {
		log.Fatalf("failed to load play combatants: %v", err)
	}
	defer rows.Close()

	playCombatantsMu.Lock()
	defer playCombatantsMu.Unlock()
	for rows.Next() {
		c := &playCombatant{}
		if err := rows.Scan(&c.CampaignID, &c.EncounterID, &c.Member, &c.CharacterID, &c.Name, &c.Initiative); err != nil {
			log.Fatalf("failed to scan play combatant row: %v", err)
		}
		if playCombatants[c.CampaignID] == nil {
			playCombatants[c.CampaignID] = map[string]map[string]*playCombatant{}
		}
		if playCombatants[c.CampaignID][c.EncounterID] == nil {
			playCombatants[c.CampaignID][c.EncounterID] = map[string]*playCombatant{}
		}
		playCombatants[c.CampaignID][c.EncounterID][c.Member] = c
	}
}

func savePlayCombatantToDB(c *playCombatant) error {
	_, err := db.Exec(
		`INSERT INTO play_combatants (campaign_id, encounter_id, member, character_id, name, initiative)
		 VALUES (?, ?, ?, ?, ?, ?)
		 ON CONFLICT(campaign_id, encounter_id, member) DO UPDATE SET
		 	character_id = excluded.character_id, name = excluded.name, initiative = excluded.initiative`,
		c.CampaignID, c.EncounterID, c.Member, c.CharacterID, c.Name, c.Initiative,
	)
	return err
}

func deletePlayCombatantFromDB(campaignID, encounterID, member string) error {
	_, err := db.Exec(
		`DELETE FROM play_combatants WHERE campaign_id = ? AND encounter_id = ? AND member = ?`,
		campaignID, encounterID, member,
	)
	return err
}

func loadPlayConditionsFromDB() {
	rows, err := db.Query(`SELECT id, campaign_id, encounter_id, target, condition, remaining_rounds FROM play_conditions`)
	if err != nil {
		log.Fatalf("failed to load play conditions: %v", err)
	}
	defer rows.Close()

	playConditionsMu.Lock()
	defer playConditionsMu.Unlock()
	for rows.Next() {
		c := &playCondition{}
		if err := rows.Scan(&c.ID, &c.CampaignID, &c.EncounterID, &c.Target, &c.Condition, &c.RemainingRounds); err != nil {
			log.Fatalf("failed to scan play condition row: %v", err)
		}
		if playConditions[c.CampaignID] == nil {
			playConditions[c.CampaignID] = map[string]map[string][]*playCondition{}
		}
		if playConditions[c.CampaignID][c.EncounterID] == nil {
			playConditions[c.CampaignID][c.EncounterID] = map[string][]*playCondition{}
		}
		playConditions[c.CampaignID][c.EncounterID][c.Target] = append(playConditions[c.CampaignID][c.EncounterID][c.Target], c)
	}
}

func insertPlayConditionToDB(c *playCondition) error {
	res, err := db.Exec(
		`INSERT INTO play_conditions (campaign_id, encounter_id, target, condition, remaining_rounds) VALUES (?, ?, ?, ?, ?)`,
		c.CampaignID, c.EncounterID, c.Target, c.Condition, c.RemainingRounds,
	)
	if err != nil {
		return err
	}
	id, err := res.LastInsertId()
	if err != nil {
		return err
	}
	c.ID = id
	return nil
}

func updatePlayConditionRemainingInDB(id int64, remainingRounds int) error {
	_, err := db.Exec(
		`UPDATE play_conditions SET remaining_rounds = ? WHERE id = ?`,
		remainingRounds, id,
	)
	return err
}

func deletePlayConditionFromDB(id int64) error {
	_, err := db.Exec(`DELETE FROM play_conditions WHERE id = ?`, id)
	return err
}
