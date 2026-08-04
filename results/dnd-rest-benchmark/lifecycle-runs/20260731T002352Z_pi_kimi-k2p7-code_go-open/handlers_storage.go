package main

import (
	"log"
	"net/http"
)

func storageStatusHandler(w http.ResponseWriter, r *http.Request) {
	initMu.Lock()
	defer initMu.Unlock()
	writeJSON(w, http.StatusOK, map[string]any{
		"driver":         "sqlite",
		"schema_version": schemaVersion,
		"initialized":    initialized,
	})
}

func storageResetHandler(w http.ResponseWriter, r *http.Request) {
	initMu.Lock()
	defer initMu.Unlock()

	tx, err := db.Begin()
	if err != nil {
		log.Printf("begin reset: %v", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "reset failed"})
		return
	}
	defer tx.Rollback()

	// Drop order is the reverse of the foreign-key graph so cascading deletes
	// are not required for a clean reset. Users are preserved so that
	// authenticated play-surface requests remain valid after a reset.
	drops := []string{
		"DROP TABLE IF EXISTS equipment",
		"DROP TABLE IF EXISTS crafting_projects",
		"DROP TABLE IF EXISTS inventory",
		"DROP TABLE IF EXISTS npcs",
		"DROP TABLE IF EXISTS factions",
		"DROP TABLE IF EXISTS session_attendance",
		"DROP TABLE IF EXISTS session_agenda",
		"DROP TABLE IF EXISTS campaign_sessions",
		"DROP TABLE IF EXISTS events",
		"DROP TABLE IF EXISTS characters",
		"DROP TABLE IF EXISTS quest_milestones",
		"DROP TABLE IF EXISTS quests",
		"DROP TABLE IF EXISTS campaigns",
		"DROP TABLE IF EXISTS play_narrations",
		"DROP TABLE IF EXISTS character_concentration",
		"DROP TABLE IF EXISTS character_spell_casts",
		"DROP TABLE IF EXISTS character_spell_slots",
		"DROP TABLE IF EXISTS character_prepared_spells",
		"DROP TABLE IF EXISTS character_spells",
		"DROP TABLE IF EXISTS play_character_equipment",
		"DROP TABLE IF EXISTS play_character_rewards",
		"DROP TABLE IF EXISTS play_gold_transfers",
		"DROP TABLE IF EXISTS play_loot_votes",
		"DROP TABLE IF EXISTS play_loot",
		"DROP TABLE IF EXISTS play_reputation_history",
		"DROP TABLE IF EXISTS play_npc_dialogue",
		"DROP TABLE IF EXISTS play_relationships",
		"DROP TABLE IF EXISTS play_clues",
		"DROP TABLE IF EXISTS play_quests",
		"DROP TABLE IF EXISTS play_world_events",
		"DROP TABLE IF EXISTS play_calendar",
		"DROP TABLE IF EXISTS play_npcs",
		"DROP TABLE IF EXISTS play_factions",
		"DROP TABLE IF EXISTS play_shop_stock",
		"DROP TABLE IF EXISTS play_shops",
		"DROP TABLE IF EXISTS play_downtime_allocations",
		"DROP TABLE IF EXISTS play_downtime_activities",
		"DROP TABLE IF EXISTS play_recipes",
		"DROP TABLE IF EXISTS play_settlement_discoveries",
		"DROP TABLE IF EXISTS play_inventory",
		"DROP TABLE IF EXISTS play_members",
		"DROP TABLE IF EXISTS play_settlements",
		"DROP TABLE IF EXISTS play_connections",
		"DROP TABLE IF EXISTS play_locations",
		"DROP TABLE IF EXISTS play_scenes",
		"DROP TABLE IF EXISTS play_content",
		"DROP TABLE IF EXISTS play_whispers",
		"DROP TABLE IF EXISTS play_notes",
		"DROP TABLE IF EXISTS play_invitations",
		"DROP TABLE IF EXISTS play_delegation_audit",
		"DROP TABLE IF EXISTS play_delegations",
		"DROP TABLE IF EXISTS play_audit_events",
		"DROP TABLE IF EXISTS play_projection_events",
		"DROP TABLE IF EXISTS play_idempotent_events",
		"DROP TABLE IF EXISTS play_safe_turns",
		"DROP TABLE IF EXISTS play_encounter_conditions",
		"DROP TABLE IF EXISTS play_combatants",
		"DROP TABLE IF EXISTS play_encounter_monsters",
		"DROP TABLE IF EXISTS play_encounter_rewards",
		"DROP TABLE IF EXISTS play_encounters",
		"DROP TABLE IF EXISTS play_campaigns",
		"DROP TABLE IF EXISTS monster_tags",
		"DROP TABLE IF EXISTS monsters",
		"DROP TABLE IF EXISTS items",
		"DROP TABLE IF EXISTS combat_conditions",
		"DROP TABLE IF EXISTS combat_order",
		"DROP TABLE IF EXISTS combat_sessions",
		"DROP TABLE IF EXISTS schema_version",
	}
	for _, stmt := range drops {
		if _, err := tx.Exec(stmt); err != nil {
			log.Printf("drop table: %v", err)
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "reset failed"})
			return
		}
	}

	if err := applySchema(tx); err != nil {
		log.Printf("recreate schema: %v", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "reset failed"})
		return
	}

	if err := tx.Commit(); err != nil {
		log.Printf("commit reset: %v", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "reset failed"})
		return
	}

	combat.mu.Lock()
	combat.sessions = make(map[string]*session)
	combat.mu.Unlock()

	writeJSON(w, http.StatusOK, map[string]any{
		"ok":             true,
		"schema_version": schemaVersion,
	})
}
