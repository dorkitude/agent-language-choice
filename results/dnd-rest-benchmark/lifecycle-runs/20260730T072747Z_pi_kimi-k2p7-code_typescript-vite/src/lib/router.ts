// Central request router. Method/path matching is performed in the exact order
// inherited from the original implementation so that precedence and edge-case
// behavior stay unchanged. Matched requests return JSON; unmatched requests fall
// through to Vite's default middleware via `next()`.

import type { IncomingMessage, ServerResponse } from 'node:http';
import { readBody, sendError } from './http.js';
import { handleHealth } from './handlers/health.js';
import { handleStorageReset, handleStorageStatus } from './handlers/storage.js';
import {
  handleCreateCampaign,
  handleCreateCampaignCharacter,
  handleCreateCampaignEvent,
  handleGetCampaignAudit,
  handleGetCampaignExport,
  handleGetCampaignState,
} from './handlers/campaigns.js';
import {
  handleGetNextSession,
  handleRecordAttendance,
  handleScheduleSession,
} from './handlers/sessions.js';
import {
  handleCreateQuest,
  handleGetQuestSummary,
  handleUpdateQuestProgress,
} from './handlers/quests.js';
import {
  handleAddInventoryItem,
  handleAssignEquipment,
  handleGetInventorySummary,
} from './handlers/inventory.js';
import {
  handleAdvanceCraftingProject,
  handleCreateCraftingProject,
} from './handlers/crafting.js';
import {
  handleCreateFaction,
  handleCreateNpc,
  handleGetRelationships,
} from './handlers/npcsFactions.js';
import {
  handleCreateItem,
  handleCreateMonster,
  handleGetItem,
  handleGetMonster,
} from './handlers/compendium.js';
import { handleLogin, handleRegister } from './handlers/auth.js';
import { handleAddEncounterCondition, handleAddEncounterMonster, handleAdvanceEncounterTurn, handleBindEncounterMember, handleClosePlayScene, handleCreateConnection, handleCreateEncounter, handleCreateEncounterAction, handleCreateLocation, handleCreatePlayAction, handleCreatePlayCampaign, handleCreatePlayNarration, handleCreatePlayNudge, handleCreatePlayResolution, handleCreatePlayRest, handleCreatePlayScene, handleCreatePlayTravel, handleDamageCharacter, handleDamageEncounter, handleDeathSave, handleDelayEncounterTurn, handleEnterPlayScene, handleGetCharacterStatus, handleGetCurrentPlayScene, handleGetEncounterStatus, handleGetEncounterTurn, handleGetPlayCampaignDocument, handleGetPlayCampaignGMStatus, handleGetPlayCampaignMyTurn, handleGetPlayCampaignTurn, handleGetTravel, handleHealEncounter, handleJoinPlayCampaign, handleReadyEncounterTurn, handleRemoveEncounterMonster, handleStartPlayCampaign, handleUnbindEncounterMember, handleUpdatePlayCampaignDocument } from './handlers/play.js';
import { handleAbilityCheck, handleDiceStats, handleInitiativeOrder } from './handlers/dice.js';
import { handleAdjustedXp } from './handlers/encounters.js';
import {
  handleAddCondition,
  handleAdvance,
  handleCreateCombatSession,
} from './handlers/combat.js';
import {
  handleAbilityModifier,
  handleDerivedStats,
  handleProficiency,
} from './handlers/characters.js';
import {
  handleEncounterBuilder,
  handleLootParcel,
  handleSessionRecap,
} from './handlers/dmTools.js';
import {
  handleEquipmentLoad,
  handleLongRest,
  handleSpellSlots,
} from './handlers/phb.js';
import {
  handleCampaignAnalyticsSummary,
  handleCampaignRiskReport,
} from './handlers/analytics.js';

export function route(
  req: IncomingMessage,
  res: ServerResponse,
  next: (err?: unknown) => void,
): void | Promise<void> {
  const url = new URL(req.url ?? '/', 'http://localhost');
  const pathname = url.pathname;

  if (req.method === 'GET') {
    if (pathname === '/health') return void handleHealth(res);
    if (pathname === '/v1/storage/status') return void handleStorageStatus(res);
    if (handleGetCampaignState(pathname, res)) return;
    if (handleGetCampaignAudit(pathname, res)) return;
    if (handleGetCampaignExport(pathname, res)) return;
    if (handleGetNextSession(pathname, res)) return;
    if (handleGetRelationships(pathname, res)) return;
    if (handleGetQuestSummary(pathname, res)) return;
    if (handleGetInventorySummary(pathname, res)) return;
    if (handleGetMonster(pathname, res)) return;
    if (handleGetItem(pathname, res)) return;
    if (handleCampaignAnalyticsSummary(pathname, res)) return;
    if (handleGetPlayCampaignMyTurn(pathname, req, res)) return;
    if (handleGetPlayCampaignGMStatus(pathname, req, res)) return;
    if (handleGetEncounterTurn(pathname, req, res)) return;
    if (handleGetEncounterStatus(pathname, req, res)) return;
    if (handleGetPlayCampaignTurn(pathname, req, res)) return;
    if (handleGetPlayCampaignDocument(pathname, req, res)) return;
    if (handleGetCurrentPlayScene(pathname, req, res)) return;
    if (handleGetTravel(pathname, req, res)) return;
    if (handleGetCharacterStatus(pathname, req, res)) return;
  }

  if (req.method === 'DELETE') {
    if (handleRemoveEncounterMonster(pathname, req, res)) return;
    if (handleUnbindEncounterMember(pathname, undefined, req, res)) return;
    next();
    return;
  }

  // POST has the bulk of the handlers; PUT is also accepted here so that a PUT
  // request with a malformed body still returns the same JSON error before
  // falling through to Vite. DELETE has a dedicated small block above. All
  // other methods fall through directly.
  if (req.method !== 'POST' && req.method !== 'PUT') {
    next();
    return;
  }

  return (async () => {
    let body: unknown;
    try {
      const raw = await readBody(req);
      body = raw ? JSON.parse(raw) : undefined;
    } catch {
      sendError(res, 400, 'invalid json');
      return;
    }

    // Post routes are checked in the exact historical order.
    if (pathname === '/v1/storage/reset') return void handleStorageReset(res);
    if (pathname === '/v1/campaigns') return void handleCreateCampaign(body, res);
    if (handleCreateCampaignCharacter(pathname, body, res)) return;
    if (handleCreateCampaignEvent(pathname, body, res)) return;
    if (handleScheduleSession(pathname, body, res)) return;
    if (handleRecordAttendance(pathname, body, res)) return;
    if (handleCreateFaction(pathname, body, res)) return;
    if (handleCreateNpc(pathname, body, res)) return;
    if (handleCreateQuest(pathname, body, res)) return;
    if (handleUpdateQuestProgress(pathname, body, res)) return;
    if (handleAddInventoryItem(pathname, body, res)) return;
    if (handleAssignEquipment(pathname, body, res)) return;
    if (handleCreateCraftingProject(pathname, body, res)) return;
    if (handleAdvanceCraftingProject(pathname, body, res)) return;
    if (pathname === '/v1/auth/register') return void handleRegister(body, res);
    if (pathname === '/v1/auth/login') return void handleLogin(body, res);
    if (pathname === '/v1/dice/stats') return void handleDiceStats(body, res);
    if (pathname === '/v1/checks/ability') return void handleAbilityCheck(body, res);
    if (pathname === '/v1/encounters/adjusted-xp') return void handleAdjustedXp(body, res);
    if (pathname === '/v1/initiative/order') return void handleInitiativeOrder(body, res);
    if (pathname === '/v1/combat/sessions') return void handleCreateCombatSession(body, res);
    if (handleAddCondition(pathname, body, res)) return;
    if (handleAdvance(pathname, body, res)) return;
    if (pathname === '/v1/characters/ability-modifier') return void handleAbilityModifier(body, res);
    if (pathname === '/v1/characters/proficiency') return void handleProficiency(body, res);
    if (pathname === '/v1/characters/derived-stats') return void handleDerivedStats(body, res);
    if (pathname === '/v1/compendium/monsters') return void handleCreateMonster(body, res);
    if (pathname === '/v1/compendium/items') return void handleCreateItem(body, res);
    if (pathname === '/v1/dm/encounter-builder') return void handleEncounterBuilder(body, res);
    if (pathname === '/v1/dm/loot-parcel') return void handleLootParcel(body, res);
    if (pathname === '/v1/dm/session-recap') return void handleSessionRecap(body, res);
    if (pathname === '/v1/phb/spell-slots') return void handleSpellSlots(body, res);
    if (pathname === '/v1/phb/rests/long') return void handleLongRest(body, res);
    if (pathname === '/v1/phb/equipment-load') return void handleEquipmentLoad(body, res);
    if (handleCampaignRiskReport(pathname, body, res)) return;
    if (handleCreatePlayCampaign(pathname, body, req, res)) return;
    if (handleJoinPlayCampaign(pathname, body, req, res)) return;
    if (handleStartPlayCampaign(pathname, body, req, res)) return;
    if (handleCreatePlayNarration(pathname, body, req, res)) return;
    if (handleCreateEncounterAction(pathname, body, req, res)) return;
    if (handleCreatePlayAction(pathname, body, req, res)) return;
    if (handleCreatePlayResolution(pathname, body, req, res)) return;
    if (handleCreatePlayNudge(pathname, body, req, res)) return;
    if (handleUpdatePlayCampaignDocument(pathname, body, req, res)) return;
    if (handleCreatePlayScene(pathname, body, req, res)) return;
    if (handleEnterPlayScene(pathname, body, req, res)) return;
    if (handleClosePlayScene(pathname, body, req, res)) return;
    if (handleCreateLocation(pathname, body, req, res)) return;
    if (handleCreateConnection(pathname, body, req, res)) return;
    if (handleCreatePlayTravel(pathname, body, req, res)) return;
    if (handleCreatePlayRest(pathname, body, req, res)) return;
    if (handleCreateEncounter(pathname, body, req, res)) return;
    if (handleAddEncounterMonster(pathname, body, req, res)) return;
    if (handleAddEncounterCondition(pathname, body, req, res)) return;
    if (handleBindEncounterMember(pathname, body, req, res)) return;
    if (handleAdvanceEncounterTurn(pathname, body, req, res)) return;
    if (handleDelayEncounterTurn(pathname, body, req, res)) return;
    if (handleReadyEncounterTurn(pathname, body, req, res)) return;
    if (handleDamageEncounter(pathname, body, req, res)) return;
    if (handleHealEncounter(pathname, body, req, res)) return;
    if (handleDamageCharacter(pathname, body, req, res)) return;
    if (handleDeathSave(pathname, body, req, res)) return;

    next();
  })();
}
