// Request routing: a static table of (method, path pattern) -> handler,
// matched top-to-bottom against the incoming request. `parseBody` controls
// whether the request body is read and JSON-parsed before the handler
// runs — GET routes and the two body-less POST routes (advance turn,
// storage reset) must NOT parse the body, since a malformed body on those
// endpoints is expected to be ignored rather than rejected.
import type { IncomingMessage, ServerResponse } from "node:http";
import { parseJsonBody, sendJson } from "./http.js";

import {
  handleHealth,
  handleDiceStats,
  handleAbilityCheck,
  handleLiveness,
  handleReadiness,
  handleGetApiSchema,
} from "./routes/core.js";
import { handleAdjustedXp, handleInitiativeOrder } from "./routes/encounters.js";
import { handleAbilityModifier, handleProficiency, handleDerivedStats } from "./routes/characters.js";
import { handleCreateCombatSession, handleAddCondition, handleAdvanceTurn } from "./routes/combat.js";
import { handleRegister, handleLogin } from "./routes/auth.js";
import { handleCreateMonster, handleGetMonster, handleCreateItem, handleGetItem } from "./routes/compendium.js";
import {
  handleCreateCampaign,
  handleAddCampaignCharacter,
  handleAddCampaignEvent,
  handleGetCampaignState,
} from "./routes/campaigns.js";
import { handleCreateQuest, handleUpdateQuestProgress, handleQuestSummary } from "./routes/quests.js";
import { handleCreateFaction, handleCreateNpc, handleRelationshipSummary } from "./routes/npcs.js";
import { handleSpellSlots, handleLongRest, handleEquipmentLoad } from "./routes/phb.js";
import { handleEncounterBuilder, handleLootParcel, handleSessionRecap } from "./routes/dm.js";
import { handleStorageStatus, handleStorageReset } from "./routes/storage.js";
import { handleAddInventoryItem, handleAssignEquipment, handleInventorySummary } from "./routes/inventory.js";
import { handleCreateCraftingProject, handleAdvanceCrafting } from "./routes/downtime.js";
import { handleScheduleSession, handleRecordAttendance, handleNextSession } from "./routes/sessions.js";
import { handleGetCampaignAudit, handleExportCampaign } from "./routes/audit.js";
import { handleAnalyticsSummary, handleRiskReport } from "./routes/analytics.js";
import {
  handleCreatePlayCampaign,
  handleJoinPlayCampaign,
  handleStartPlayCampaign,
  handleAddPlayNarration,
  handleAddPlayMessage,
  handleSubmitPlayerAction,
  handleGetPlayTurn,
  handleGetMyTurnContext,
  handleGetGmStatus,
  handleAddResolution,
  handleNudgePlayTurn,
  handleGetPlayCampaignDocument,
  handlePutPlayCampaignDocument,
  handleCreatePlayScene,
  handleEnterPlayScene,
  handleClosePlayScene,
  handleGetCurrentPlayScene,
  handleCreatePlayLocation,
  handleCreatePlayConnection,
  handleGetPlayLocationTravel,
  handleTravelPlayCampaignTurn,
  handleRestPlayCampaignTurn,
  handleCreatePlayEncounter,
  handleAddPlayEncounterMonster,
  handleRemovePlayEncounterMonster,
  handleBindPlayEncounterCombatant,
  handleUnbindPlayEncounterCombatant,
  handleGetEncounterTurn,
  handleAdvanceEncounterTurn,
  handleDelayEncounterTurn,
  handleReadyEncounterTurn,
  handleAddPlayEncounterCondition,
  handleGetPlayEncounterStatus,
  handleSubmitEncounterCombatAction,
  handleDamagePlayEncounterCombatant,
  handleHealPlayEncounterCombatant,
  handleDamagePlayCharacter,
  handleRecordDeathSave,
  handleGetCharacterStatus,
  handleAwardEncounterRewards,
  handleClosePlayEncounter,
  handleEndPlayEncounter,
  handleGetCharacterOwner,
  handleClaimCharacter,
  handleTransferCharacter,
  handleBuildCharacter,
  handleLevelUpCharacter,
  handleSkillCheck,
  handleAddPlaySpell,
  handleGetPlaySpells,
  handlePutPreparedSpells,
  handleGetPreparedSpells,
  handleCastPlaySpell,
  handleGetPlayCasts,
  handlePutConcentration,
  handleGetConcentration,
  handleAdvanceConcentrationTurn,
  handleDeleteConcentration,
  handleAddInventoryItemStack,
  handleGetInventoryItemStacks,
  handleRemoveInventoryItemStack,
  handleConsumeInventoryItem,
  handleEquipItem,
  handleGetEquipment,
  handleAttuneEquipment,
  handleGetCharacterCurrency,
  handleTransferCharacterCurrency,
  handleCreateLoot,
  handleVoteLoot,
  handleAssignLoot,
  handleGetLoot,
  handleCreatePlayNpc,
  handleUpdatePlayNpcAgenda,
  handleGetPlayNpc,
  handleCreatePlayNpcDialogue,
  handleGetPlayNpcDialogue,
  handleCreatePlayFaction,
  handleChangePlayFactionReputation,
  handleGetPlayFactionReputation,
  handleCreatePlayRelationship,
  handleUpdatePlayRelationship,
  handleGetPlayRelationships,
  handleCreatePlayClue,
  handleGetPlayClues,
  handleCreatePlayQuest,
  handleUpdatePlayQuestState,
  handleGetPlayQuests,
  handleConfigureQuestRewards,
  handleAwardQuestRewards,
  handleGetCharacterRewards,
  handleCreatePlayWorldEvent,
  handleResolvePlayWorldEvent,
  handleGetPlayWorldEvents,
  handleInitPlayCampaignCalendar,
  handleGetPlayCampaignCalendar,
  handleAdvancePlayCampaignCalendar,
  handleCreatePlaySettlement,
  handleUpdatePlaySettlement,
  handleDiscoverPlaySettlement,
  handleGetPlaySettlements,
  handleCreatePlayShop,
  handleGetPlayShop,
  handleBuyFromPlayShop,
  handleSellToPlayShop,
  handleCreatePlayRecipe,
  handleGetPlayRecipes,
  handleCraftPlayRecipe,
  handleCreatePlayDowntimeActivity,
  handleCreatePlayDowntimeAllocation,
  handleProgressPlayDowntimeAllocation,
  handleGetPlayDowntimeAllocation,
  handlePutPlaySessionZero,
  handleGetPlaySessionZero,
  handleCreatePlayContent,
  handlePutPlayContentTags,
  handleListPlayContent,
  handleCreatePlayNote,
  handleListPlayNotes,
  handleGetPlayNote,
  handleUpdatePlayNote,
  handleCreatePlayWhisper,
  handleListPlayWhispers,
  handleGetPlayCharacterSheet,
  handleCreatePlayInvitation,
  handleListPlayInvitations,
  handleAcceptPlayInvitation,
  handleGrantPlayDelegation,
  handleRevokePlayDelegation,
  handleGetPlayDelegationAudit,
  handleCreatePlayAuditEvent,
  handleGetPlayAuditEvents,
  handleCreatePlayProjectionEvent,
  handleGetPlayProjection,
  handleCreatePlayIdempotentEvent,
  handleGetPlayIdempotentEvents,
  handleSubmitPlaySafeTurn,
  handleGetPlaySafeTurns,
  handleCreatePlayTransactionalTransfer,
  handleGetPlayTransactionalTransfers,
  handleCreatePlayCampaignExport,
  handleGetPlayCampaignExports,
  handleGetPlayCampaignExport,
  handleCreatePlayCampaignImport,
  handleGetPlayCampaignImportState,
  handleCreatePlayCampaignMigration,
  handleGetPlayCampaignMigrationState,
  handleCreatePlaySearchRecord,
  handleListPlaySearchRecords,
  handleCreatePlayRateEvent,
  handleListPlayRateEvents,
  handleGetPlayCampaignMetrics,
  handleSetPlayServiceMode,
  handleCreatePlayBackup,
  handleListPlayBackups,
  handleRestorePlayBackup,
  handleCreatePlayReplayEvent,
  handleGetPlayReplay,
  handleSetPlayRngSeed,
  handleAppendPlayRngRoll,
  handleGetPlayRngLedger,
  handleCreatePlayModerationReport,
  handleGetPlayModerationReports,
  handleResolvePlayModerationReport,
  handlePutPlaySafetyBoundaries,
  handleGetPlaySafetyBoundaries,
  handleCreatePlaySafetyCheck,
  handleGetPlaySafetyEvents,
  handleCreatePlayFixtureSeed,
  handleGetPlayFixtureState,
  handleGetPlayOnboarding,
  handleCreatePlaySpectatorTicket,
  handleGetPlaySpectatorView,
  handleCreatePlayFeedEvent,
  handleGetPlayEventFeed,
} from "./routes/play.js";

interface RouteContext {
  res: ServerResponse;
  params: string[];
  body: unknown;
  authHeader: string | undefined;
  url: URL;
  headers: IncomingMessage["headers"];
}

interface Route {
  method: string;
  pattern: RegExp;
  parseBody: boolean;
  handler: (ctx: RouteContext) => void | Promise<void>;
}

// A pattern with no capture groups must still match the full path exactly,
// so every entry is anchored (`^...$`) up front by `exact`/`param` below.
function exact(path: string): RegExp {
  return new RegExp(`^${path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`);
}

function withParam(prefix: string, suffix: string): RegExp {
  return new RegExp(`^${prefix}([^/]+)${suffix}$`);
}

function withTwoParams(prefix: string, mid: string, suffix: string): RegExp {
  return new RegExp(`^${prefix}([^/]+)${mid}([^/]+)${suffix}$`);
}

function withThreeParams(prefix: string, mid1: string, mid2: string, suffix: string): RegExp {
  return new RegExp(`^${prefix}([^/]+)${mid1}([^/]+)${mid2}([^/]+)${suffix}$`);
}

function withFourParams(prefix: string, mid1: string, mid2: string, mid3: string, suffix: string): RegExp {
  return new RegExp(`^${prefix}([^/]+)${mid1}([^/]+)${mid2}([^/]+)${mid3}([^/]+)${suffix}$`);
}

const routes: Route[] = [
  { method: "GET", pattern: exact("/health"), parseBody: false, handler: ({ res }) => handleHealth(res) },
  { method: "GET", pattern: exact("/healthz"), parseBody: false, handler: ({ res }) => handleLiveness(res) },
  { method: "GET", pattern: exact("/readyz"), parseBody: false, handler: ({ res }) => handleReadiness(res) },
  { method: "GET", pattern: exact("/v1/schema"), parseBody: false, handler: ({ res }) => handleGetApiSchema(res) },

  {
    method: "POST",
    pattern: exact("/v1/dice/stats"),
    parseBody: true,
    handler: ({ res, body }) => handleDiceStats(res, body),
  },
  {
    method: "POST",
    pattern: exact("/v1/checks/ability"),
    parseBody: true,
    handler: ({ res, body }) => handleAbilityCheck(res, body),
  },
  {
    method: "POST",
    pattern: exact("/v1/encounters/adjusted-xp"),
    parseBody: true,
    handler: ({ res, body }) => handleAdjustedXp(res, body),
  },
  {
    method: "POST",
    pattern: exact("/v1/initiative/order"),
    parseBody: true,
    handler: ({ res, body }) => handleInitiativeOrder(res, body),
  },

  {
    method: "POST",
    pattern: exact("/v1/characters/ability-modifier"),
    parseBody: true,
    handler: ({ res, body }) => handleAbilityModifier(res, body),
  },
  {
    method: "POST",
    pattern: exact("/v1/characters/proficiency"),
    parseBody: true,
    handler: ({ res, body }) => handleProficiency(res, body),
  },
  {
    method: "POST",
    pattern: exact("/v1/characters/derived-stats"),
    parseBody: true,
    handler: ({ res, body }) => handleDerivedStats(res, body),
  },

  {
    method: "POST",
    pattern: exact("/v1/combat/sessions"),
    parseBody: true,
    handler: ({ res, body }) => handleCreateCombatSession(res, body),
  },
  {
    method: "POST",
    pattern: withParam("/v1/combat/sessions/", "/conditions"),
    parseBody: true,
    handler: ({ res, params, body }) => handleAddCondition(res, decodeURIComponent(params[0]), body),
  },
  {
    method: "POST",
    pattern: withParam("/v1/combat/sessions/", "/advance"),
    parseBody: false,
    handler: ({ res, params }) => handleAdvanceTurn(res, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: exact("/v1/auth/register"),
    parseBody: true,
    handler: ({ res, body }) => handleRegister(res, body),
  },
  {
    method: "POST",
    pattern: exact("/v1/auth/login"),
    parseBody: true,
    handler: ({ res, body }) => handleLogin(res, body),
  },

  {
    method: "POST",
    pattern: exact("/v1/compendium/monsters"),
    parseBody: true,
    handler: ({ res, body }) => handleCreateMonster(res, body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/compendium/monsters/", ""),
    parseBody: false,
    handler: ({ res, params }) => handleGetMonster(res, decodeURIComponent(params[0])),
  },
  {
    method: "POST",
    pattern: exact("/v1/compendium/items"),
    parseBody: true,
    handler: ({ res, body }) => handleCreateItem(res, body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/compendium/items/", ""),
    parseBody: false,
    handler: ({ res, params }) => handleGetItem(res, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: exact("/v1/campaigns"),
    parseBody: true,
    handler: ({ res, body }) => handleCreateCampaign(res, body),
  },
  {
    method: "POST",
    pattern: withParam("/v1/campaigns/", "/characters"),
    parseBody: true,
    handler: ({ res, params, body }) => handleAddCampaignCharacter(res, decodeURIComponent(params[0]), body),
  },
  {
    method: "POST",
    pattern: withParam("/v1/campaigns/", "/events"),
    parseBody: true,
    handler: ({ res, params, body }) => handleAddCampaignEvent(res, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/campaigns/", "/state"),
    parseBody: false,
    handler: ({ res, params }) => handleGetCampaignState(res, decodeURIComponent(params[0])),
  },

  {
    method: "GET",
    pattern: withParam("/v1/campaigns/", "/quests/summary"),
    parseBody: false,
    handler: ({ res, params }) => handleQuestSummary(res, decodeURIComponent(params[0])),
  },
  {
    method: "POST",
    pattern: withParam("/v1/campaigns/", "/quests"),
    parseBody: true,
    handler: ({ res, params, body }) => handleCreateQuest(res, decodeURIComponent(params[0]), body),
  },
  {
    method: "POST",
    pattern: /^\/v1\/campaigns\/([^/]+)\/quests\/([^/]+)\/progress$/,
    parseBody: true,
    handler: ({ res, params, body }) =>
      handleUpdateQuestProgress(res, decodeURIComponent(params[0]), decodeURIComponent(params[1]), body),
  },

  {
    method: "POST",
    pattern: exact("/v1/phb/spell-slots"),
    parseBody: true,
    handler: ({ res, body }) => handleSpellSlots(res, body),
  },
  {
    method: "POST",
    pattern: exact("/v1/phb/rests/long"),
    parseBody: true,
    handler: ({ res, body }) => handleLongRest(res, body),
  },
  {
    method: "POST",
    pattern: exact("/v1/phb/equipment-load"),
    parseBody: true,
    handler: ({ res, body }) => handleEquipmentLoad(res, body),
  },

  {
    method: "POST",
    pattern: exact("/v1/dm/encounter-builder"),
    parseBody: true,
    handler: ({ res, body }) => handleEncounterBuilder(res, body),
  },
  {
    method: "POST",
    pattern: exact("/v1/dm/loot-parcel"),
    parseBody: true,
    handler: ({ res, body }) => handleLootParcel(res, body),
  },
  {
    method: "POST",
    pattern: exact("/v1/dm/session-recap"),
    parseBody: true,
    handler: ({ res, body }) => handleSessionRecap(res, body),
  },

  {
    method: "POST",
    pattern: withParam("/v1/campaigns/", "/factions"),
    parseBody: true,
    handler: ({ res, params, body }) => handleCreateFaction(res, decodeURIComponent(params[0]), body),
  },
  {
    method: "POST",
    pattern: withParam("/v1/campaigns/", "/npcs"),
    parseBody: true,
    handler: ({ res, params, body }) => handleCreateNpc(res, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/campaigns/", "/relationships"),
    parseBody: false,
    handler: ({ res, params }) => handleRelationshipSummary(res, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/campaigns/", "/inventory"),
    parseBody: true,
    handler: ({ res, params, body }) => handleAddInventoryItem(res, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/campaigns/", "/inventory/summary"),
    parseBody: false,
    handler: ({ res, params }) => handleInventorySummary(res, decodeURIComponent(params[0])),
  },
  {
    method: "POST",
    pattern: /^\/v1\/campaigns\/([^/]+)\/characters\/([^/]+)\/equipment$/,
    parseBody: true,
    handler: ({ res, params, body }) =>
      handleAssignEquipment(res, decodeURIComponent(params[0]), decodeURIComponent(params[1]), body),
  },

  {
    method: "POST",
    pattern: withParam("/v1/campaigns/", "/downtime/crafting"),
    parseBody: true,
    handler: ({ res, params, body }) => handleCreateCraftingProject(res, decodeURIComponent(params[0]), body),
  },
  {
    method: "POST",
    pattern: /^\/v1\/campaigns\/([^/]+)\/downtime\/crafting\/([^/]+)\/advance$/,
    parseBody: true,
    handler: ({ res, params, body }) =>
      handleAdvanceCrafting(res, decodeURIComponent(params[0]), decodeURIComponent(params[1]), body),
  },

  {
    method: "GET",
    pattern: withParam("/v1/campaigns/", "/sessions/next"),
    parseBody: false,
    handler: ({ res, params }) => handleNextSession(res, decodeURIComponent(params[0])),
  },
  {
    method: "POST",
    pattern: withParam("/v1/campaigns/", "/sessions"),
    parseBody: true,
    handler: ({ res, params, body }) => handleScheduleSession(res, decodeURIComponent(params[0]), body),
  },
  {
    method: "POST",
    pattern: /^\/v1\/campaigns\/([^/]+)\/sessions\/([^/]+)\/attendance$/,
    parseBody: true,
    handler: ({ res, params, body }) =>
      handleRecordAttendance(res, decodeURIComponent(params[0]), decodeURIComponent(params[1]), body),
  },

  {
    method: "GET",
    pattern: withParam("/v1/campaigns/", "/audit"),
    parseBody: false,
    handler: ({ res, params }) => handleGetCampaignAudit(res, decodeURIComponent(params[0])),
  },
  {
    method: "GET",
    pattern: withParam("/v1/campaigns/", "/export"),
    parseBody: false,
    handler: ({ res, params }) => handleExportCampaign(res, decodeURIComponent(params[0])),
  },

  {
    method: "GET",
    pattern: withParam("/v1/campaigns/", "/analytics/summary"),
    parseBody: false,
    handler: ({ res, params }) => handleAnalyticsSummary(res, decodeURIComponent(params[0])),
  },
  {
    method: "POST",
    pattern: withParam("/v1/campaigns/", "/analytics/risk-report"),
    parseBody: true,
    handler: ({ res, params, body }) => handleRiskReport(res, decodeURIComponent(params[0]), body),
  },

  {
    method: "POST",
    pattern: exact("/v1/play/campaigns"),
    parseBody: true,
    handler: ({ res, body, authHeader }) => handleCreatePlayCampaign(res, authHeader, body),
  },
  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/members"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleJoinPlayCampaign(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/start"),
    parseBody: false,
    handler: ({ res, params, authHeader }) => handleStartPlayCampaign(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/narrations"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleAddPlayNarration(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/messages"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleAddPlayMessage(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/actions"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleSubmitPlayerAction(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/turn"),
    parseBody: false,
    handler: ({ res, params, authHeader }) => handleGetPlayTurn(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/turn/nudge"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleNudgePlayTurn(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/turn/travel"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleTravelPlayCampaignTurn(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/turn/rest"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleRestPlayCampaignTurn(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/my-turn"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetMyTurnContext(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/gm/status"),
    parseBody: false,
    handler: ({ res, params, authHeader }) => handleGetGmStatus(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/resolutions"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleAddResolution(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/document"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayCampaignDocument(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "PUT",
    pattern: withParam("/v1/play/campaigns/", "/document"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handlePutPlayCampaignDocument(res, authHeader, decodeURIComponent(params[0]), body),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/scenes"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayScene(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/scenes/current"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetCurrentPlayScene(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/scenes/", "/enter"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleEnterPlayScene(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/scenes/", "/close"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleClosePlayScene(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/locations"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayLocation(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/locations/", "/connections"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayConnection(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1]), body),
  },
  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/locations/", "/travel"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayLocationTravel(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/encounters"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayEncounter(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/encounters/", "/monsters"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleAddPlayEncounterMonster(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "DELETE",
    pattern: withThreeParams("/v1/play/campaigns/", "/encounters/", "/monsters/", ""),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleRemovePlayEncounterMonster(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        decodeURIComponent(params[2]),
      ),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/encounters/", "/combatants"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleBindPlayEncounterCombatant(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "DELETE",
    pattern: withThreeParams("/v1/play/campaigns/", "/encounters/", "/combatants/", ""),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleUnbindPlayEncounterCombatant(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        decodeURIComponent(params[2]),
      ),
  },

  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/encounters/", "/turn"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetEncounterTurn(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/encounters/", "/turn/advance"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleAdvanceEncounterTurn(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/encounters/", "/turn/delay"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleDelayEncounterTurn(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/encounters/", "/turn/ready"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleReadyEncounterTurn(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },

  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/encounters/", "/conditions"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleAddPlayEncounterCondition(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/encounters/", "/status"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayEncounterStatus(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },

  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/encounters/", "/actions"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleSubmitEncounterCombatAction(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },

  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/encounters/", "/damage"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleDamagePlayEncounterCombatant(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/encounters/", "/heal"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleHealPlayEncounterCombatant(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },

  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/damage"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleDamagePlayCharacter(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1]), body),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/death-saves"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleRecordDeathSave(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1]), body),
  },
  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/status"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetCharacterStatus(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },

  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/encounters/", "/rewards"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleAwardEncounterRewards(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/encounters/", "/close"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleClosePlayEncounter(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/encounters/", "/end"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleEndPlayEncounter(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },

  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/owner"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetCharacterOwner(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/claim"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleClaimCharacter(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/transfer"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleTransferCharacter(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/build"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleBuildCharacter(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/level-up"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleLevelUpCharacter(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/skill-check"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleSkillCheck(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1]), body),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/spells"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleAddPlaySpell(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1]), body),
  },
  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/spells"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlaySpells(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },
  {
    method: "PUT",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/prepared-spells"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handlePutPreparedSpells(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/prepared-spells"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPreparedSpells(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/casts"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCastPlaySpell(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1]), body),
  },
  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/casts"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayCasts(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },
  {
    method: "PUT",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/concentration"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handlePutConcentration(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1]), body),
  },
  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/concentration"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetConcentration(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/concentration/advance-turn"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleAdvanceConcentrationTurn(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },
  {
    method: "DELETE",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/concentration"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleDeleteConcentration(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },

  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/inventory/items"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleAddInventoryItemStack(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1]), body),
  },
  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/inventory/items"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetInventoryItemStacks(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },
  {
    method: "DELETE",
    pattern: withThreeParams("/v1/play/campaigns/", "/characters/", "/inventory/items/", ""),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleRemoveInventoryItemStack(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        decodeURIComponent(params[2]),
        body,
      ),
  },

  {
    method: "POST",
    pattern: withThreeParams("/v1/play/campaigns/", "/characters/", "/inventory/items/", "/consume"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleConsumeInventoryItem(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        decodeURIComponent(params[2]),
      ),
  },

  {
    method: "PUT",
    pattern: withThreeParams("/v1/play/campaigns/", "/characters/", "/equipment/", ""),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleEquipItem(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        decodeURIComponent(params[2]),
        body,
      ),
  },
  {
    method: "GET",
    pattern: withThreeParams("/v1/play/campaigns/", "/characters/", "/equipment/", ""),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetEquipment(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        decodeURIComponent(params[2]),
      ),
  },
  {
    method: "POST",
    pattern: new RegExp("^/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)/attune$"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleAttuneEquipment(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        decodeURIComponent(params[2]),
      ),
  },

  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/currency"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetCharacterCurrency(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/currency/transfers"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleTransferCharacterCurrency(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/loot"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreateLoot(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/loot/", ""),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetLoot(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/loot/", "/votes"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleVoteLoot(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1]), body),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/loot/", "/assign"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleAssignLoot(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/npcs"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayNpc(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "PUT",
    pattern: withTwoParams("/v1/play/campaigns/", "/npcs/", "/agenda"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleUpdatePlayNpcAgenda(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1]), body),
  },
  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/npcs/", ""),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayNpc(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/npcs/", "/dialogue"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayNpcDialogue(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/npcs/", "/dialogue"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayNpcDialogue(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/relationships"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayRelationship(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/relationships"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayRelationships(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "PUT",
    pattern: withFourParams("/v1/play/campaigns/", "/relationships/", "/", "/", ""),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleUpdatePlayRelationship(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        decodeURIComponent(params[2]),
        decodeURIComponent(params[3]),
        body,
      ),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/clues"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayClue(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/clues"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayClues(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/quests"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayQuest(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/quests"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayQuests(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "PUT",
    pattern: withTwoParams("/v1/play/campaigns/", "/quests/", "/state"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleUpdatePlayQuestState(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "PUT",
    pattern: withTwoParams("/v1/play/campaigns/", "/quests/", "/rewards"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleConfigureQuestRewards(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/quests/", "/rewards/award"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleAwardQuestRewards(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },
  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/rewards"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetCharacterRewards(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/factions"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayFaction(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/factions/", "/reputation"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleChangePlayFactionReputation(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/factions/", "/reputation"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayFactionReputation(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/world-events"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayWorldEvent(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/world-events/", "/resolve"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleResolvePlayWorldEvent(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/world-events"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayWorldEvents(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/calendar"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleInitPlayCampaignCalendar(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/calendar"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayCampaignCalendar(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/calendar/advance"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleAdvancePlayCampaignCalendar(res, authHeader, decodeURIComponent(params[0]), body),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/settlements"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlaySettlement(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "PUT",
    pattern: withTwoParams("/v1/play/campaigns/", "/settlements/", ""),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleUpdatePlaySettlement(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/settlements/", "/discover"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleDiscoverPlaySettlement(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
      ),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/settlements"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlaySettlements(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/settlements/", "/shops"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayShop(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "GET",
    pattern: withThreeParams("/v1/play/campaigns/", "/settlements/", "/shops/", ""),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayShop(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        decodeURIComponent(params[2]),
      ),
  },
  {
    method: "POST",
    pattern: withThreeParams("/v1/play/campaigns/", "/settlements/", "/shops/", "/buy"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleBuyFromPlayShop(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        decodeURIComponent(params[2]),
        body,
      ),
  },
  {
    method: "POST",
    pattern: withThreeParams("/v1/play/campaigns/", "/settlements/", "/shops/", "/sell"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleSellToPlayShop(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        decodeURIComponent(params[2]),
        body,
      ),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/recipes"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayRecipe(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/recipes"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayRecipes(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/recipes/", "/craft"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCraftPlayRecipe(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/downtime/activities"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayDowntimeActivity(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/downtime/allocations"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayDowntimeAllocation(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },
  {
    method: "POST",
    pattern: withThreeParams("/v1/play/campaigns/", "/characters/", "/downtime/allocations/", "/progress"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleProgressPlayDowntimeAllocation(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        decodeURIComponent(params[2]),
      ),
  },
  {
    method: "GET",
    pattern: withThreeParams("/v1/play/campaigns/", "/characters/", "/downtime/allocations/", ""),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayDowntimeAllocation(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        decodeURIComponent(params[2]),
      ),
  },

  {
    method: "PUT",
    pattern: withParam("/v1/play/campaigns/", "/session-zero"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handlePutPlaySessionZero(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/session-zero"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlaySessionZero(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/content"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayContent(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "PUT",
    pattern: withTwoParams("/v1/play/campaigns/", "/content/", "/tags"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handlePutPlayContentTags(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/content"),
    parseBody: false,
    handler: ({ res, params, authHeader, url }) =>
      handleListPlayContent(res, authHeader, decodeURIComponent(params[0]), url.searchParams.get("exclude_tag")),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/notes"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayNote(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/notes"),
    parseBody: false,
    handler: ({ res, params, authHeader }) => handleListPlayNotes(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/notes/", ""),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayNote(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },
  {
    method: "PUT",
    pattern: withTwoParams("/v1/play/campaigns/", "/notes/", ""),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleUpdatePlayNote(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1]), body),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/whispers"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayWhisper(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/whispers"),
    parseBody: false,
    handler: ({ res, params, authHeader }) => handleListPlayWhispers(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/characters/", "/sheet"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayCharacterSheet(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/invitations"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayInvitation(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/invitations"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleListPlayInvitations(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/invitations/", "/accept"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleAcceptPlayInvitation(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/delegations"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleGrantPlayDelegation(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/delegations/audit"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayDelegationAudit(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "DELETE",
    pattern: withTwoParams("/v1/play/campaigns/", "/delegations/", ""),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleRevokePlayDelegation(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/audit-events"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayAuditEvent(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/audit-events"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayAuditEvents(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/projection-events"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayProjectionEvent(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/projection"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayProjection(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/projection/rebuild"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayProjection(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/idempotent-events"),
    parseBody: true,
    handler: ({ res, params, body, authHeader, headers }) =>
      handleCreatePlayIdempotentEvent(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        headers["idempotency-key"],
        body,
      ),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/idempotent-events"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayIdempotentEvents(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/safe-turns"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleSubmitPlaySafeTurn(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/safe-turns"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlaySafeTurns(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/transactional-transfers"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayTransactionalTransfer(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/transactional-transfers"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayTransactionalTransfers(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/exports"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleCreatePlayCampaignExport(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/exports"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayCampaignExports(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "GET",
    pattern: withTwoParams("/v1/play/campaigns/", "/exports/", ""),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayCampaignExport(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/imports"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayCampaignImport(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/import-state"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayCampaignImportState(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/migrations"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayCampaignMigration(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/migration-state"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayCampaignMigrationState(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/search-records"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlaySearchRecord(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/search-records"),
    parseBody: false,
    handler: ({ res, params, authHeader, url }) =>
      handleListPlaySearchRecords(res, authHeader, decodeURIComponent(params[0]), url),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/rate-events"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayRateEvent(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/rate-events"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleListPlayRateEvents(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/metrics"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayCampaignMetrics(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/service-mode"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleSetPlayServiceMode(res, authHeader, decodeURIComponent(params[0]), body),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/backups"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleCreatePlayBackup(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/backups"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleListPlayBackups(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "POST",
    pattern: withTwoParams("/v1/play/campaigns/", "/backups/", "/restore"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleRestorePlayBackup(res, authHeader, decodeURIComponent(params[0]), decodeURIComponent(params[1])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/replay-events"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayReplayEvent(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/replay"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayReplay(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/replay/check"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayReplay(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "PUT",
    pattern: withParam("/v1/play/campaigns/", "/rng-seed"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleSetPlayRngSeed(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/rng-rolls"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleAppendPlayRngRoll(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/rng-ledger"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayRngLedger(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/moderation/reports"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayModerationReport(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/moderation/reports"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayModerationReports(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "PUT",
    pattern: withTwoParams("/v1/play/campaigns/", "/moderation/reports/", "/resolution"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleResolvePlayModerationReport(
        res,
        authHeader,
        decodeURIComponent(params[0]),
        decodeURIComponent(params[1]),
        body,
      ),
  },

  {
    method: "PUT",
    pattern: withParam("/v1/play/campaigns/", "/safety-boundaries"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handlePutPlaySafetyBoundaries(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/safety-boundaries"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlaySafetyBoundaries(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/safety-checks"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlaySafetyCheck(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/safety-events"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlaySafetyEvents(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/fixture-seeds"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayFixtureSeed(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/fixture-state"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayFixtureState(res, authHeader, decodeURIComponent(params[0])),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/onboarding"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlayOnboarding(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/spectators"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlaySpectatorTicket(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/spectator-view"),
    parseBody: false,
    handler: ({ res, params, authHeader }) =>
      handleGetPlaySpectatorView(res, authHeader, decodeURIComponent(params[0])),
  },

  {
    method: "POST",
    pattern: withParam("/v1/play/campaigns/", "/feed-events"),
    parseBody: true,
    handler: ({ res, params, body, authHeader }) =>
      handleCreatePlayFeedEvent(res, authHeader, decodeURIComponent(params[0]), body),
  },
  {
    method: "GET",
    pattern: withParam("/v1/play/campaigns/", "/event-feed"),
    parseBody: false,
    handler: ({ res, params, authHeader, url }) =>
      handleGetPlayEventFeed(res, authHeader, decodeURIComponent(params[0]), url),
  },

  {
    method: "GET",
    pattern: exact("/v1/storage/status"),
    parseBody: false,
    handler: ({ res }) => handleStorageStatus(res),
  },
  {
    method: "POST",
    pattern: exact("/v1/storage/reset"),
    parseBody: false,
    handler: ({ res }) => handleStorageReset(res),
  },
];

export async function dispatch(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const method = req.method ?? "GET";
  const url = new URL(req.url ?? "/", "http://localhost");
  const pathname = url.pathname;

  for (const route of routes) {
    if (route.method !== method) continue;
    const match = route.pattern.exec(pathname);
    if (!match) continue;

    const body = route.parseBody ? await parseJsonBody(req) : undefined;
    await route.handler({
      res,
      params: match.slice(1),
      body,
      authHeader: req.headers.authorization,
      url,
      headers: req.headers,
    });
    return;
  }

  sendJson(res, 404, { error: "not found" });
}
