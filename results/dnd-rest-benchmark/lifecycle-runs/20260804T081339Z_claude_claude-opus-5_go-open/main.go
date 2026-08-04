// Command dndrest serves the D&D rest-benchmark HTTP API.
//
// The program is a single main package split by domain, one file per API
// grouping. This file is the entry point and the only place routes are
// declared; see CODEBASE.md for the module map.
package main

import (
	"log"
	"net/http"
	"os"
)

func main() {
	addr := "127.0.0.1:" + listenPort()

	if err := openStorage(); err != nil {
		log.Fatalf("storage init failed: %v", err)
	}
	// A leftover game.db from an earlier run would make previously registered
	// usernames and session ids collide, so each boot starts from a clean
	// schema. Durable state still lives in SQLite for the process lifetime.
	if err := resetStorage(); err != nil {
		log.Fatalf("storage reset failed: %v", err)
	}

	log.Printf("listening on %s", addr)
	if err := http.ListenAndServe(addr, newRouter()); err != nil {
		log.Fatal(err)
	}
}

// listenPort reads PORT, defaulting to 8080 when it is unset or empty.
func listenPort() string {
	if port := os.Getenv("PORT"); port != "" {
		return port
	}
	return "8080"
}

// newRouter builds the complete route table. Patterns carry no method prefix:
// each handler validates its own method so a wrong method yields 405 with an
// Allow header and a JSON error body rather than ServeMux's bare response.
func newRouter() *http.ServeMux {
	mux := http.NewServeMux()

	// Liveness.
	mux.HandleFunc("/health", handleHealth)

	// Stateless rules math (dice.go, checks.go, encounters.go, initiative.go).
	mux.HandleFunc("/v1/dice/stats", handleDiceStats)
	mux.HandleFunc("/v1/checks/ability", handleAbilityCheck)
	mux.HandleFunc("/v1/encounters/adjusted-xp", handleAdjustedXP)
	mux.HandleFunc("/v1/initiative/order", handleInitiative)

	// Character derivation (characters.go).
	mux.HandleFunc("/v1/characters/ability-modifier", handleAbilityModifier)
	mux.HandleFunc("/v1/characters/proficiency", handleProficiency)
	mux.HandleFunc("/v1/characters/derived-stats", handleDerivedStats)

	// Stateful combat trackers (combat.go).
	mux.HandleFunc("/v1/combat/sessions", handleCreateSession)
	mux.HandleFunc("/v1/combat/sessions/{id}/conditions", handleAddCondition)
	mux.HandleFunc("/v1/combat/sessions/{id}/advance", handleAdvance)

	// Users and login tokens (auth.go).
	mux.HandleFunc("/v1/auth/register", handleRegister)
	mux.HandleFunc("/v1/auth/login", handleLogin)

	// Static game world (compendium.go).
	mux.HandleFunc("/v1/compendium/monsters", handleMonsters)
	mux.HandleFunc("/v1/compendium/monsters/{slug}", handleMonsterBySlug)
	mux.HandleFunc("/v1/compendium/items", handleItems)
	mux.HandleFunc("/v1/compendium/items/{slug}", handleItemBySlug)

	// Campaign records (campaigns.go).
	mux.HandleFunc("/v1/campaigns", handleCampaigns)
	mux.HandleFunc("/v1/campaigns/{id}/characters", handleCampaignCharacters)
	mux.HandleFunc("/v1/campaigns/{id}/events", handleCampaignEvents)
	mux.HandleFunc("/v1/campaigns/{id}/state", handleCampaignState)

	// Campaign quest tracking (quests.go). The literal /summary pattern is more
	// specific than the {quest_id} one, so ServeMux prefers it.
	mux.HandleFunc("/v1/campaigns/{id}/quests", handleCampaignQuests)
	mux.HandleFunc("/v1/campaigns/{id}/quests/summary", handleCampaignQuestSummary)
	mux.HandleFunc("/v1/campaigns/{id}/quests/{quest_id}/progress", handleCampaignQuestProgress)

	// Campaign social layer: factions, NPCs, and their summary (npcs.go).
	mux.HandleFunc("/v1/campaigns/{id}/factions", handleCampaignFactions)
	mux.HandleFunc("/v1/campaigns/{id}/npcs", handleCampaignNPCs)
	mux.HandleFunc("/v1/campaigns/{id}/relationships", handleCampaignRelationships)

	// Campaign inventory and per-character equipment (inventory.go). As with
	// quests, the literal /summary pattern wins over the sibling collection.
	mux.HandleFunc("/v1/campaigns/{id}/inventory", handleCampaignInventory)
	mux.HandleFunc("/v1/campaigns/{id}/inventory/summary", handleCampaignInventorySummary)
	mux.HandleFunc("/v1/campaigns/{id}/characters/{character_id}/equipment", handleCharacterEquipment)

	// Downtime crafting projects (crafting.go). Completing one stocks the item
	// in the campaign inventory above.
	mux.HandleFunc("/v1/campaigns/{id}/downtime/crafting", handleCampaignCrafting)
	mux.HandleFunc("/v1/campaigns/{id}/downtime/crafting/{project_id}/advance", handleCampaignCraftingAdvance)

	// Scheduled play sessions (sessions.go). The literal /next pattern outranks
	// the sibling {session_id} routes, as with /quests/summary.
	mux.HandleFunc("/v1/campaigns/{id}/sessions", handleCampaignSessions)
	mux.HandleFunc("/v1/campaigns/{id}/sessions/next", handleCampaignNextSession)
	mux.HandleFunc("/v1/campaigns/{id}/sessions/{session_id}/attendance", handleCampaignSessionAttendance)

	// Read-only campaign rollups (audit.go).
	mux.HandleFunc("/v1/campaigns/{id}/audit", handleCampaignAudit)
	mux.HandleFunc("/v1/campaigns/{id}/export", handleCampaignExport)

	// Deterministic campaign analytics over that accumulated state (analytics.go).
	mux.HandleFunc("/v1/campaigns/{id}/analytics/summary", handleCampaignAnalyticsSummary)
	mux.HandleFunc("/v1/campaigns/{id}/analytics/risk-report", handleCampaignAnalyticsRiskReport)

	// Authenticated campaign play (play.go). Unlike everything above, these
	// routes require a Bearer session token.
	mux.HandleFunc("/v1/play/campaigns", handleCreatePlayCampaign)
	mux.HandleFunc("/v1/play/campaigns/{id}/members", handleJoinPlayCampaign)
	mux.HandleFunc("/v1/play/campaigns/{id}/start", handleStartPlayCampaign)
	mux.HandleFunc("/v1/play/campaigns/{id}/narrations", handleNarratePlayCampaign)
	mux.HandleFunc("/v1/play/campaigns/{id}/turn", handlePlayCampaignTurn)
	mux.HandleFunc("/v1/play/campaigns/{id}/my-turn", handlePlayCampaignMyTurn)
	mux.HandleFunc("/v1/play/campaigns/{id}/gm/status", handlePlayCampaignGMStatus)
	mux.HandleFunc("/v1/play/campaigns/{id}/actions", handleSubmitPlayAction)
	mux.HandleFunc("/v1/play/campaigns/{id}/resolutions", handleResolvePlayTurn)

	// Player's Handbook lookups (phb.go).
	mux.HandleFunc("/v1/phb/spell-slots", handleSpellSlots)
	mux.HandleFunc("/v1/phb/rests/long", handleLongRest)
	mux.HandleFunc("/v1/phb/equipment-load", handleEquipmentLoad)

	// DM tools that read stored state (dm.go).
	mux.HandleFunc("/v1/dm/encounter-builder", handleEncounterBuilder)
	mux.HandleFunc("/v1/dm/loot-parcel", handleLootParcel)
	mux.HandleFunc("/v1/dm/session-recap", handleSessionRecap)

	// Storage introspection and fixture reset (storage.go).
	mux.HandleFunc("/v1/storage/status", handleStorageStatus)
	mux.HandleFunc("/v1/storage/reset", handleStorageReset)

	return mux
}

// handleHealth answers any method so a liveness probe never has to care.
func handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}
