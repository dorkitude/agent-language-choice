package main

import (
	"log"
	"net/http"
	"os"
)

func main() {
	if err := initDB(); err != nil {
		log.Fatalf("failed to initialize database: %v", err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", healthHandler)

	// Core rules and calculators.
	mux.HandleFunc("POST /v1/dice/stats", diceStatsHandler)
	mux.HandleFunc("POST /v1/checks/ability", abilityCheckHandler)
	mux.HandleFunc("POST /v1/encounters/adjusted-xp", adjustedXPHandler)
	mux.HandleFunc("POST /v1/initiative/order", initiativeOrderHandler)
	mux.HandleFunc("POST /v1/characters/ability-modifier", abilityModifierHandler)
	mux.HandleFunc("POST /v1/characters/proficiency", proficiencyBonusHandler)
	mux.HandleFunc("POST /v1/characters/derived-stats", derivedStatsHandler)

	// Authentication.
	mux.HandleFunc("POST /v1/auth/register", registerHandler)
	mux.HandleFunc("POST /v1/auth/login", loginHandler)

	// Combat state.
	mux.HandleFunc("POST /v1/combat/sessions", createCombatSessionHandler)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/conditions", addConditionHandler)
	mux.HandleFunc("POST /v1/combat/sessions/{id}/advance", advanceTurnHandler)

	// Storage lifecycle.
	mux.HandleFunc("GET /v1/storage/status", storageStatusHandler)
	mux.HandleFunc("POST /v1/storage/reset", storageResetHandler)

	// Compendium (monsters and items).
	mux.HandleFunc("POST /v1/compendium/monsters", createMonsterHandler)
	mux.HandleFunc("GET /v1/compendium/monsters/{slug}", getMonsterHandler)
	mux.HandleFunc("POST /v1/compendium/items", createItemHandler)
	mux.HandleFunc("GET /v1/compendium/items/{slug}", getItemHandler)

	// Play campaign surface.
	mux.HandleFunc("POST /v1/play/campaigns", createPlayCampaignHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/members", joinPlayCampaignHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/start", startPlayCampaignHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters", createPlayEncounterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/monsters", addPlayEncounterMonsterHandler)
	mux.HandleFunc("DELETE /v1/play/campaigns/{id}/encounters/{enc_id}/monsters/{monster_id}", removePlayEncounterMonsterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/combatants", bindPlayEncounterMemberHandler)
	mux.HandleFunc("DELETE /v1/play/campaigns/{id}/encounters/{enc_id}/combatants/{member}", unbindPlayEncounterMemberHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/encounters/{enc_id}/turn", getPlayEncounterTurnHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/advance", advancePlayEncounterTurnHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/actions", submitCombatActionHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/damage", damageEncounterCombatantHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/heal", healEncounterCombatantHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/conditions", addPlayEncounterConditionHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/encounters/{enc_id}/status", getPlayEncounterStatusHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/delay", delayPlayEncounterTurnHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/ready", readyPlayEncounterTurnHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/rewards", awardEncounterRewardsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/close", closePlayEncounterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/encounters/{enc_id}/end", endPlayEncounterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/damage", damageCharacterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/death-saves", deathSavesHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{char_id}/status", getCharacterStatusHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{char_id}/owner", getCharacterOwnerHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/claim", claimCharacterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/transfer", transferCharacterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/build", buildCharacterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/level-up", levelUpCharacterHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/skill-check", skillCheckHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/spells", addCharacterSpellHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{char_id}/spells", getCharacterSpellbookHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/characters/{char_id}/prepared-spells", prepareCharacterSpellsHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{char_id}/prepared-spells", getCharacterPreparedSpellsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/casts", castSpellHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{char_id}/casts", getCharacterCastsHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/characters/{char_id}/concentration", setCharacterConcentrationHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{char_id}/concentration", getCharacterConcentrationHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/concentration/advance-turn", advanceCharacterConcentrationHandler)
	mux.HandleFunc("DELETE /v1/play/campaigns/{id}/characters/{char_id}/concentration", clearCharacterConcentrationHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/inventory/items", addCharacterInventoryItemHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{char_id}/inventory/items", getCharacterInventoryItemsHandler)
	mux.HandleFunc("DELETE /v1/play/campaigns/{id}/characters/{char_id}/inventory/items/{item_id}", removeCharacterInventoryItemHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/inventory/items/{item_id}/consume", consumeCharacterInventoryItemHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/characters/{char_id}/equipment/{slot}", equipCharacterItemHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{char_id}/equipment/{slot}", getCharacterEquipmentSlotHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/equipment/{slot}/attune", attuneCharacterItemHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{char_id}/currency", getCharacterCurrencyHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{char_id}/currency/transfers", transferCharacterGoldHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/loot", createLootHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/loot/{loot_id}/votes", voteLootHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/loot/{loot_id}/assign", assignLootHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/loot/{loot_id}", getLootHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/npcs", createPlayNPCHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/npcs/{npc_id}/agenda", updatePlayNPCAgendaHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/npcs/{npc_id}", getPlayNPCHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/npcs/{npc_id}/dialogue", createPlayNPCDialogueHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/npcs/{npc_id}/dialogue", getPlayNPCDialogueHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/relationships", createPlayRelationshipHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/relationships/{source_id}/{target_id}/{kind}", updatePlayRelationshipHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/relationships", getPlayRelationshipsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/clues", createPlayClueHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/clues", getPlayCluesHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/quests", createPlayQuestHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/quests/{quest_id}/state", updatePlayQuestStateHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/quests", getPlayQuestsHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/quests/{quest_id}/rewards", configurePlayQuestRewardsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/quests/{quest_id}/rewards/award", awardPlayQuestRewardsHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/rewards", getCharacterRewardsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/world-events", createWorldEventHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/world-events/{event_id}/resolve", resolveWorldEventHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/world-events", getWorldEventsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/calendar", createCalendarHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/calendar", getCalendarHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/calendar/advance", advanceCalendarHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/settlements", createPlaySettlementHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/settlements/{settlement_id}", updatePlaySettlementHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/settlements/{settlement_id}/discover", discoverPlaySettlementHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/settlements", listPlaySettlementsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/settlements/{settlement_id}/shops", createPlayShopHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}", getPlayShopHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/buy", buyFromPlayShopHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/sell", sellToPlayShopHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/recipes", createPlayRecipeHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/recipes", listPlayRecipesHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/recipes/{recipe_id}/craft", craftRecipeHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/downtime/activities", createPlayDowntimeActivityHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations", createPlayDowntimeAllocationHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}/progress", progressPlayDowntimeAllocationHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}", getPlayDowntimeAllocationHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/factions", createPlayFactionHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/factions/{faction_id}/reputation", createPlayReputationHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/factions/{faction_id}/reputation", getPlayReputationHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/narrations", addNarrationHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/delegations", createPlayDelegationHandler)
	mux.HandleFunc("DELETE /v1/play/campaigns/{id}/delegations/{username}", revokePlayDelegationHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/delegations/audit", listPlayDelegationAuditHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/audit-events", createPlayAuditEventHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/audit-events", listPlayAuditEventsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/projection-events", createProjectionEventHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/projection", getProjectionHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/projection/rebuild", rebuildProjectionHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/idempotent-events", createIdempotentEventHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/idempotent-events", listIdempotentEventsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/safe-turns", submitSafeTurnHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/safe-turns", getSafeTurnsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/actions", submitPlayerActionHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/turn/travel", submitTravelHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/turn/rest", submitRestHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/resolutions", submitResolutionHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/turn", getPlayCampaignTurnHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/turn/nudge", nudgeTurnHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/my-turn", getPlayCampaignMyTurnHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/gm/status", getPlayCampaignGMStatusHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/document", updateCampaignDocumentHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/document", getCampaignDocumentHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/session-zero", updateSessionZeroSettingsHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/session-zero", getSessionZeroSettingsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/scenes", createPlaySceneHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/scenes/{scene_id}/enter", enterPlaySceneHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/scenes/{scene_id}/close", closePlaySceneHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/scenes/current", getCurrentSceneHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/content", createPlayContentHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/content/{content_id}/tags", updatePlayContentTagsHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/content", listPlayContentHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/notes", createPlayNoteHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/notes", listPlayNotesHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/notes/{note_id}", getPlayNoteHandler)
	mux.HandleFunc("PUT /v1/play/campaigns/{id}/notes/{note_id}", updatePlayNoteHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/whispers", createPlayWhisperHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/whispers", listPlayWhispersHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/characters/{character_id}/sheet", getCharacterSheetHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/invitations", createPlayInvitationHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/invitations/{invitation_id}/accept", acceptPlayInvitationHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/invitations", listPlayInvitationsHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/locations", createPlayLocationHandler)
	mux.HandleFunc("POST /v1/play/campaigns/{id}/locations/{from_id}/connections", createPlayConnectionHandler)
	mux.HandleFunc("GET /v1/play/campaigns/{id}/locations/{loc_id}/travel", getPlayLocationTravelHandler)

	// Campaign state.
	mux.HandleFunc("POST /v1/campaigns", createCampaignHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/characters", addCharacterHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/events", addEventHandler)
	mux.HandleFunc("GET /v1/campaigns/{id}/state", getCampaignStateHandler)
	mux.HandleFunc("GET /v1/campaigns/{id}/audit", auditCampaignHandler)
	mux.HandleFunc("GET /v1/campaigns/{id}/export", exportCampaignHandler)

	// Campaign analytics.
	mux.HandleFunc("GET /v1/campaigns/{id}/analytics/summary", campaignAnalyticsSummaryHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/analytics/risk-report", campaignRiskReportHandler)

	// Session scheduling.
	mux.HandleFunc("POST /v1/campaigns/{id}/sessions", createCampaignSessionHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/sessions/{session_id}/attendance", recordAttendanceHandler)
	mux.HandleFunc("GET /v1/campaigns/{id}/sessions/next", getNextSessionHandler)

	// Inventory and equipment.
	mux.HandleFunc("POST /v1/campaigns/{id}/inventory", addInventoryItemHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/characters/{character_id}/equipment", assignEquipmentHandler)
	mux.HandleFunc("GET /v1/campaigns/{id}/inventory/summary", getInventorySummaryHandler)

	// Downtime crafting.
	mux.HandleFunc("POST /v1/campaigns/{id}/downtime/crafting", createCraftingProjectHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/downtime/crafting/{project_id}/advance", advanceCraftingProjectHandler)

	// Quest tracking.
	mux.HandleFunc("POST /v1/campaigns/{id}/quests", createQuestHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/quests/{quest_id}/progress", updateQuestProgressHandler)
	mux.HandleFunc("GET /v1/campaigns/{id}/quests/summary", getQuestSummaryHandler)

	// NPCs and factions.
	mux.HandleFunc("POST /v1/campaigns/{id}/factions", createFactionHandler)
	mux.HandleFunc("POST /v1/campaigns/{id}/npcs", createNPCHandler)
	mux.HandleFunc("GET /v1/campaigns/{id}/relationships", getRelationshipsHandler)

	// Player's Handbook rules.
	mux.HandleFunc("POST /v1/phb/spell-slots", spellSlotsHandler)
	mux.HandleFunc("POST /v1/phb/rests/long", longRestHandler)
	mux.HandleFunc("POST /v1/phb/equipment-load", equipmentLoadHandler)

	// DM tools.
	mux.HandleFunc("POST /v1/dm/encounter-builder", encounterBuilderHandler)
	mux.HandleFunc("POST /v1/dm/loot-parcel", lootParcelHandler)
	mux.HandleFunc("POST /v1/dm/session-recap", sessionRecapHandler)

	port := os.Getenv("PORT")
	if port == "" {
		port = defaultPort
	}
	addr := "127.0.0.1:" + port

	log.Printf("listening on %s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
