package main

import (
	"log"
	"net"
	"net/http"
	"os"
)

// main initializes the SQLite database, wires all HTTP handlers, and starts
// the server on 127.0.0.1 using the PORT environment variable (default 8080).
func main() {
	if err := initDB(); err != nil {
		log.Fatalf("db init failed: %v", err)
	}

	mux := http.NewServeMux()

	// Health and storage.
	mux.HandleFunc("GET /health", healthHandler)
	mux.HandleFunc("GET /healthz", healthzHandler)
	mux.HandleFunc("GET /readyz", readyzHandler)
	mux.HandleFunc("GET /v1/schema", schemaHandler)
	mux.HandleFunc("GET /v1/storage/status", storageStatusHandler)
	mux.HandleFunc("POST /v1/storage/reset", storageResetHandler)

	// Core utilities.
	mux.HandleFunc("POST /v1/dice/stats", diceStatsHandler)
	mux.HandleFunc("POST /v1/checks/ability", abilityCheckHandler)
	mux.HandleFunc("POST /v1/encounters/adjusted-xp", adjustedXPHandler)
	mux.HandleFunc("POST /v1/initiative/order", initiativeHandler)

	// Character calculations.
	mux.HandleFunc("POST /v1/characters/ability-modifier", abilityModifierHandler)
	mux.HandleFunc("POST /v1/characters/proficiency", proficiencyHandler)
	mux.HandleFunc("POST /v1/characters/derived-stats", derivedStatsHandler)

	// Combat state.
	mux.HandleFunc("POST /v1/combat/sessions", createCombatSessionHandler)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/conditions", addConditionHandler)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/advance", advanceTurnHandler)

	// Auth.
	mux.HandleFunc("POST /v1/auth/register", registerUserHandler)
	mux.HandleFunc("POST /v1/auth/login", loginHandler)

	// Compendium.
	mux.HandleFunc("POST /v1/compendium/monsters", createMonsterHandler)
	mux.HandleFunc("GET /v1/compendium/monsters/{slug}", getMonsterHandler)
	mux.HandleFunc("POST /v1/compendium/items", createItemHandler)
	mux.HandleFunc("GET /v1/compendium/items/{slug}", getItemHandler)

	// Campaigns.
	mux.HandleFunc("POST /v1/campaigns", createCampaignHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/characters", addCampaignCharacterHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/events", addCampaignEventHandler)
	mux.HandleFunc("GET /v1/campaigns/{id}/state", getCampaignStateHandler)
	mux.HandleFunc("GET /v1/campaigns/{id}/audit", getCampaignAuditHandler)
	mux.HandleFunc("GET /v1/campaigns/{id}/export", getCampaignExportHandler)

	// Play campaign surface.
	mux.HandleFunc("POST /v1/play/campaigns", createPlayCampaignHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/members", joinPlayCampaignHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/onboarding", getCampaignOnboardingHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/start", startPlayCampaignHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/session-zero", updateSessionZeroSettingsHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/session-zero", getSessionZeroSettingsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/content", createContentHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/content/{content_id}/tags", updateContentTagsHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/content", listContentHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/notes", createNoteHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/notes", listNotesHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/notes/{note_id}", getNoteHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/notes/{note_id}", updateNoteHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/whispers", createWhisperHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/whispers", listWhispersHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/messages", createMessageHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/invitations", createInvitationHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/invitations/{invitation_id}/accept", acceptInvitationHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/invitations", listInvitationsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/delegations", createDelegationHandler)
	mux.HandleFunc("DELETE /v1/play/campaigns/{id}/delegations/{username}", revokeDelegationHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/delegations/audit", listDelegationAuditHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/audit-events", createAuditEventHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/audit-events", listAuditEventsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/projection-events", createProjectionEventHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/projection", getProjectionHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/projection/rebuild", rebuildProjectionHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/idempotent-events", createIdempotentEventHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/idempotent-events", listIdempotentEventsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/safe-turns", createSafeTurnHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/safe-turns", listSafeTurnsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/narrations", createNarrationHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/actions", createActionHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/turn/travel", travelTurnHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/turn/rest", restTurnHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters", createEncounterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/monsters", addEncounterMonsterHandler)
	mux.HandleFunc("DELETE /v1/play/campaigns/{id}/encounters/{enc_id}/monsters/{monster_id}", removeEncounterMonsterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/combatants", bindEncounterMemberHandler)
	mux.HandleFunc("DELETE /v1/play/campaigns/{id}/encounters/{enc_id}/combatants/{member}", removeEncounterMemberHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/encounters/{enc_id}/turn", getEncounterTurnHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/actions", createEncounterActionHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/advance", advanceEncounterTurnHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/delay", delayEncounterTurnHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/ready", readyEncounterTurnHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/damage", damageEncounterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/heal", healEncounterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/conditions", addEncounterConditionHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/rewards", awardEncounterRewardsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/close", closeEncounterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/end", endEncounterHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/encounters/{enc_id}/status", getEncounterStatusHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/damage", damageCharacterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/death-saves", deathSavesHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{char_id}/status", getCharacterStatusHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{char_id}/owner", getCharacterOwnerHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/sheet", getCharacterSheetHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/claim", claimCharacterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/transfer", transferCharacterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/build", buildCharacterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/level-up", levelUpHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/skill-check", skillCheckHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/spells", addCharacterSpellHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{char_id}/spells", getCharacterSpellsHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/characters/{character_id}/prepared-spells", updateCharacterPreparedSpellsHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/prepared-spells", getCharacterPreparedSpellsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/casts", castSpellHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/casts", getCastHistoryHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/characters/{character_id}/concentration", updateCharacterConcentrationHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/concentration", getCharacterConcentrationHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/concentration/advance-turn", advanceCharacterConcentrationHandler)
	mux.HandleFunc("DELETE /v1/play/campaigns/{id}/characters/{character_id}/concentration", deleteCharacterConcentrationHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/inventory/items", addCharacterInventoryItemHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/inventory/items", getCharacterInventoryItemsHandler)
	mux.HandleFunc("DELETE /v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}", removeCharacterInventoryItemHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}/consume", consumeCharacterInventoryItemHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}", equipCharacterHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}", getCharacterEquipmentHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}/attune", attuneCharacterHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/currency", getCurrencyHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/currency/transfers", transferCurrencyHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/transactional-transfers", createTransactionalTransferHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/transactional-transfers", listTransactionalTransfersHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/loot", createLootHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/loot/{loot_id}/votes", voteLootHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/loot/{loot_id}/assign", assignLootHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/loot/{loot_id}", getLootHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/factions", createPlayFactionHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/factions/{faction_id}/reputation", changeReputationHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/factions/{faction_id}/reputation", getReputationHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/npcs", createPlayNPCHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/npcs/{npc_id}/agenda", updatePlayNPCAgendaHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/npcs/{npc_id}", getPlayNPCHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/npcs/{npc_id}/dialogue", createNPCDialogueHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/npcs/{npc_id}/dialogue", getNPCDialogueHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/relationships", createRelationshipHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/relationships/{source_id}/{target_id}/{kind}", updateRelationshipHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/relationships", listRelationshipsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/clues", createClueHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/clues", listCluesHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/quests", createPlayQuestHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/quests/{quest_id}/state", updatePlayQuestStateHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/quests", listPlayQuestsHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/quests/{quest_id}/rewards", configureQuestRewardsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/quests/{quest_id}/rewards/award", awardQuestRewardsHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/rewards", getCharacterQuestRewardsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/world-events", createWorldEventHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/world-events/{event_id}/resolve", resolveWorldEventHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/world-events", listWorldEventsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/calendar", createCalendarHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/calendar", getCalendarHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/calendar/advance", advanceCalendarHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/settlements", createSettlementHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/settlements/{settlement_id}", updateSettlementHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/settlements/{settlement_id}/discover", discoverSettlementHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/settlements", listSettlementsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/settlements/{settlement_id}/shops", createShopHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}", getShopHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/buy", buyFromShopHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/sell", sellToShopHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/resolutions", createResolutionHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/turn", getPlayCampaignTurnHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/turn/nudge", nudgeTurnHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/my-turn", getPlayerTurnContextHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/gm/status", getGMStatusHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/document", getCampaignDocumentHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/document", updateCampaignDocumentHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/exports", createPlayCampaignExportHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/exports", listPlayCampaignExportsHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/exports/{version}", getPlayCampaignExportHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/imports", createPlayCampaignImportHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/import-state", getPlayCampaignImportStateHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/migrations", createPlayCampaignMigrationHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/migration-state", getPlayCampaignMigrationStateHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/search-records", createSearchRecordHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/search-records", listSearchRecordsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/rate-events", createRateEventHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/rate-events", listRateEventsHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/metrics", getCampaignMetricsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/service-mode", serviceModeHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/backups", createCampaignBackupHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/backups", listCampaignBackupsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/backups/{backup_id}/restore", restoreCampaignBackupHandler)

	// Deterministic replay stream.
	mux.HandleFunc("POST /v1/play/campaigns/{id}/replay-events", appendReplayEventHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/replay", getReplayHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/replay/check", checkReplayHandler)

	// Deterministic RNG ledger.
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/rng-seed", configureRNGSeedHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/rng-rolls", appendRNGRollHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/rng-ledger", getRNGLedgerHandler)

	// Moderation workflow.
	mux.HandleFunc("POST /v1/play/campaigns/{id}/moderation/reports", createModerationReportHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/moderation/reports", listModerationReportsHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution", resolveModerationReportHandler)

	// Safety boundaries and events.
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/safety-boundaries", replaceSafetyBoundariesHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/safety-boundaries", getSafetyBoundariesHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/safety-checks", submitSafetyCheckHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/safety-events", listSafetyEventsHandler)

	// Fixture seeding.
	mux.HandleFunc("POST /v1/play/campaigns/{id}/fixture-seeds", seedFixtureHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/fixture-state", getFixtureStateHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/spectators", createSpectatorHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/spectator-view", getSpectatorViewHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/feed-events", createFeedEventHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/event-feed", listFeedEventsHandler)

	// Scene state.
	mux.HandleFunc("POST /v1/play/campaigns/{id}/scenes", createSceneHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/scenes/{scene_id}/enter", enterSceneHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/scenes/{scene_id}/close", closeSceneHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/scenes/current", getCurrentSceneHandler)

	// Location graph.
	mux.HandleFunc("POST /v1/play/campaigns/{id}/locations", createLocationHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/locations/{from_id}/connections", createConnectionHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/locations/{loc_id}/travel", getValidTravelHandler)

	// Campaign analytics.
	mux.HandleFunc("GET /v1/campaigns/{id}/analytics/summary", getCampaignAnalyticsSummaryHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/analytics/risk-report", getCampaignRiskReportHandler)

	// Quest tracker.
	mux.HandleFunc("POST /v1/campaigns/{id}/quests", createQuestHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/quests/{quest_id}/progress", updateQuestProgressHandler)
	mux.HandleFunc("GET /v1/campaigns/{id}/quests/summary", getQuestSummaryHandler)

	// NPCs and factions.
	mux.HandleFunc("POST /v1/campaigns/{id}/factions", createFactionHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/npcs", createNPCHandler)
	mux.HandleFunc("GET /v1/campaigns/{id}/relationships", getRelationshipSummaryHandler)

	// Recipe catalog.
	mux.HandleFunc("POST /v1/play/campaigns/{id}/recipes", createRecipeHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/recipes", listRecipesHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/recipes/{recipe_id}/craft", craftRecipeHandler)

	// Recurring downtime.
	mux.HandleFunc("POST /v1/play/campaigns/{id}/downtime/activities", createDowntimeActivityHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations", createDowntimeAllocationHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}/progress", progressDowntimeAllocationHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}", getDowntimeAllocationHandler)

	// Inventory and equipment.
	mux.HandleFunc("POST /v1/campaigns/{id}/inventory", addInventoryItemHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/characters/{character_id}/equipment", assignEquipmentHandler)
	mux.HandleFunc("GET /v1/campaigns/{id}/inventory/summary", getInventorySummaryHandler)

	// Downtime crafting.
	mux.HandleFunc("POST /v1/campaigns/{id}/downtime/crafting", createCraftingProjectHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/downtime/crafting/{project_id}/advance", advanceCraftingProjectHandler)

	// Session scheduling.
	mux.HandleFunc("POST /v1/campaigns/{id}/sessions", createCampaignSessionHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/sessions/{session_id}/attendance", recordCampaignSessionAttendanceHandler)
	mux.HandleFunc("GET /v1/campaigns/{id}/sessions/next", getNextCampaignSessionHandler)

	// PHB rules.
	mux.HandleFunc("POST /v1/phb/spell-slots", spellSlotsHandler)
	mux.HandleFunc("POST /v1/phb/rests/long", longRestHandler)
	mux.HandleFunc("POST /v1/phb/equipment-load", equipmentLoadHandler)

	// DM tools.
	mux.HandleFunc("POST /v1/dm/encounter-builder", encounterBuilderHandler)
	mux.HandleFunc("POST /v1/dm/loot-parcel", lootParcelHandler)
	mux.HandleFunc("POST /v1/dm/session-recap", sessionRecapHandler)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	addr := net.JoinHostPort("127.0.0.1", port)
	log.Printf("starting server on %s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
