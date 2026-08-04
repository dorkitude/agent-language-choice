// Command dndrest is a deterministic D&D rules-and-campaign REST API built
// entirely on the Go standard library.
//
// The service is a single package. Each file owns one domain area (see
// CODEBASE.md); main.go only wires routes to handlers and starts the server.
package main

import (
	"log"
	"net/http"
	"os"
)

const defaultPort = "8080"

// routes registers every endpoint. Handlers whose pattern names a method rely
// on the mux to reject others; the rest guard the method themselves with
// requirePost/requireGet, which is why those patterns carry no method prefix.
// Changing an existing pattern's method form changes the 404/405 split, so
// prefer adding new routes in the method-qualified form.
func routes() *http.ServeMux {
	mux := http.NewServeMux()

	// Service health.
	mux.HandleFunc("/health", handleHealth)

	// Stateless core rules.
	mux.HandleFunc("/v1/dice/stats", handleDiceStats)
	mux.HandleFunc("/v1/checks/ability", handleAbilityCheck)
	mux.HandleFunc("/v1/encounters/adjusted-xp", handleAdjustedXP)
	mux.HandleFunc("/v1/initiative/order", handleInitiative)

	// Character build rules.
	mux.HandleFunc("/v1/characters/ability-modifier", handleAbilityModifier)
	mux.HandleFunc("/v1/characters/proficiency", handleProficiency)
	mux.HandleFunc("/v1/characters/derived-stats", handleDerivedStats)

	// Player's Handbook rules.
	mux.HandleFunc("POST /v1/phb/spell-slots", handleSpellSlots)
	mux.HandleFunc("POST /v1/phb/rests/long", handleLongRest)
	mux.HandleFunc("POST /v1/phb/equipment-load", handleEquipmentLoad)

	// Accounts.
	mux.HandleFunc("/v1/auth/register", handleRegister)
	mux.HandleFunc("/v1/auth/login", handleLogin)

	// Stateful combat sessions.
	mux.HandleFunc("POST /v1/combat/sessions", handleCreateSession)
	mux.HandleFunc("GET /v1/combat/sessions/{id}", handleGetSession)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/conditions", handleAddCondition)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/advance", handleAdvanceTurn)

	// Compendium.
	mux.HandleFunc("POST /v1/compendium/monsters", handleCreateMonster)
	mux.HandleFunc("GET /v1/compendium/monsters/{slug}", handleGetMonster)
	mux.HandleFunc("POST /v1/compendium/items", handleCreateItem)
	mux.HandleFunc("GET /v1/compendium/items/{slug}", handleGetItem)

	// Campaigns.
	mux.HandleFunc("POST /v1/campaigns", handleCreateCampaign)
	mux.HandleFunc("POST /v1/campaigns/{id}/characters", handleAddCampaignCharacter)
	mux.HandleFunc("POST /v1/campaigns/{id}/events", handleAddCampaignEvent)
	mux.HandleFunc("GET /v1/campaigns/{id}/state", handleCampaignState)

	// Quest tracking within a campaign. The summary pattern is more specific
	// than the {quest_id} ones, so the mux prefers it for .../quests/summary.
	mux.HandleFunc("POST /v1/campaigns/{id}/quests", handleCreateQuest)
	mux.HandleFunc("GET /v1/campaigns/{id}/quests/summary", handleQuestSummary)
	mux.HandleFunc("POST /v1/campaigns/{id}/quests/{quest_id}/progress", handleQuestProgress)

	// Campaign cast: factions, NPCs, and their relationship summary.
	mux.HandleFunc("POST /v1/campaigns/{id}/factions", handleCreateFaction)
	mux.HandleFunc("POST /v1/campaigns/{id}/npcs", handleCreateNPC)
	mux.HandleFunc("GET /v1/campaigns/{id}/relationships", handleRelationships)

	// Campaign stock and per-character equipment assignment. As with quests,
	// the literal .../inventory/summary pattern wins over .../inventory.
	mux.HandleFunc("POST /v1/campaigns/{id}/inventory", handleAddInventoryItem)
	mux.HandleFunc("GET /v1/campaigns/{id}/inventory/summary", handleInventorySummary)
	mux.HandleFunc("POST /v1/campaigns/{id}/characters/{character_id}/equipment", handleAssignEquipment)

	// Downtime crafting projects within a campaign.
	mux.HandleFunc("POST /v1/campaigns/{id}/downtime/crafting", handleCreateCrafting)
	mux.HandleFunc("POST /v1/campaigns/{id}/downtime/crafting/{project_id}/advance", handleAdvanceCrafting)

	// Scheduled play sessions. As with quests, the literal .../sessions/next
	// pattern is more specific than .../sessions/{session_id}/... and wins.
	mux.HandleFunc("POST /v1/campaigns/{id}/sessions", handleScheduleSession)
	mux.HandleFunc("GET /v1/campaigns/{id}/sessions/next", handleNextSession)
	mux.HandleFunc("POST /v1/campaigns/{id}/sessions/{session_id}/attendance", handleSessionAttendance)

	// Read-only audit and export views over a campaign.
	mux.HandleFunc("GET /v1/campaigns/{id}/audit", handleCampaignAudit)
	mux.HandleFunc("GET /v1/campaigns/{id}/export", handleCampaignExport)

	// Read-only analytics over the accumulated campaign state.
	mux.HandleFunc("GET /v1/campaigns/{id}/analytics/summary", handleAnalyticsSummary)
	mux.HandleFunc("POST /v1/campaigns/{id}/analytics/risk-report", handleAnalyticsRiskReport)

	// DM tools over stored compendium and campaign state.
	mux.HandleFunc("POST /v1/dm/encounter-builder", handleEncounterBuilder)
	mux.HandleFunc("POST /v1/dm/loot-parcel", handleLootParcel)
	mux.HandleFunc("POST /v1/dm/session-recap", handleSessionRecap)

	// Protected campaign play surface (Authorization: Bearer session-<user>).
	mux.HandleFunc("POST /v1/play/campaigns", handleCreatePlayCampaign)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/members", handleJoinPlayCampaign)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/start", handleStartPlayCampaign)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/narrations", handleNarrate)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/actions", handleAction)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/resolutions", handleResolution)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/turn", handleTurn)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/my-turn", handleMyTurn)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/gm/status", handleGMStatus)

	// Storage administration.
	mux.HandleFunc("/v1/storage/status", handleStorageStatus)
	mux.HandleFunc("/v1/storage/reset", handleStorageReset)

	// Unmatched paths get the JSON error envelope, not net/http's plain text.
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		writeError(w, http.StatusNotFound, "not found")
	})

	return mux
}

// ---------- GET /health ----------

func handleHealth(w http.ResponseWriter, r *http.Request) {
	if !requireGet(w, r) {
		return
	}
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

func main() {
	// Restore any previously persisted world before accepting requests.
	initStorage()

	port := os.Getenv("PORT")
	if port == "" {
		port = defaultPort
	}
	addr := "127.0.0.1:" + port

	server := &http.Server{Addr: addr, Handler: routes()}
	log.Printf("listening on %s", addr)
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("server error: %v", err)
	}
}
