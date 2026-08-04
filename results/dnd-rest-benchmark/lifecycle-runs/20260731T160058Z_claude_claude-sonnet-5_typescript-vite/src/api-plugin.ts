/**
 * Vite dev-server middleware exposing the D&D REST API.
 *
 * Route tables below map a path to a domain handler; `apiMiddleware` only
 * handles JSON body parsing/serialization and path matching. All game logic
 * and persistence lives in `./domain/*`.
 */

import type { Plugin, ViteDevServer, Connect } from 'vite';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { diceStats, abilityCheck } from './domain/dice.ts';
import { adjustedXp } from './domain/encounters.ts';
import { initiativeOrder, createCombatSession, addCombatCondition, advanceCombatTurn } from './domain/combat.ts';
import { abilityModifier, proficiencyBonus, derivedStats } from './domain/character.ts';
import { registerUser, loginUser } from './domain/auth.ts';
import { spellSlots, longRest, equipmentLoad } from './domain/phb.ts';
import { createMonster, getMonster, createItem, getItem } from './domain/compendium.ts';
import {
  createCampaign,
  addCampaignCharacter,
  addCampaignEvent,
  getCampaignState,
  encounterBuilder,
  lootParcel,
  sessionRecap,
} from './domain/campaigns.ts';
import { initStorage, storageStatus, resetStorageHandler } from './domain/storage.ts';
import { createQuest, updateQuestProgress, questSummary } from './domain/quests.ts';
import { createFaction, createNpc, relationshipSummary } from './domain/npcs.ts';
import { addInventoryItem, assignEquipment, inventorySummary } from './domain/inventory.ts';
import { createCraftingProject, advanceCrafting } from './domain/crafting.ts';
import { scheduleSession, recordAttendance, nextSession } from './domain/sessions.ts';
import { campaignAudit, campaignExport } from './domain/audit.ts';
import { analyticsSummary, analyticsRiskReport } from './domain/analytics.ts';
import {
  createPlayCampaign,
  joinPlayCampaign,
  startPlayCampaign,
  addNarration,
  addChatMessage,
  submitPlayerAction,
  submitResolution,
  getPlayCampaignTurn,
  getPlayerTurnContext,
  getGmStatus,
  getCampaignOnboarding,
  nudgePlayCampaignTurn,
  updateCampaignDocument,
  getCampaignDocument,
  createScene,
  enterScene,
  closeScene,
  getCurrentScene,
  createLocation,
  createLocationConnection,
  getLocationTravel,
  travelToLocation,
  restOnTurn,
  createEncounter,
  addMonsterToEncounter,
  removeMonsterFromEncounter,
  bindEncounterCombatant,
  unbindEncounterCombatant,
  getEncounterTurn,
  advanceEncounterTurn,
  delayEncounterTurn,
  readyEncounterTurn,
  submitCombatAction,
  damageEncounterCombatant,
  healEncounterCombatant,
  damageCharacter,
  recordDeathSave,
  getCharacterStatus,
  addEncounterCondition,
  getEncounterStatus,
  awardEncounterRewards,
  closeEncounter,
  endEncounter,
  getCharacterOwner,
  claimCharacter,
  transferCharacter,
  buildCharacter,
  levelUpCharacter,
  skillCheck,
  addSpell,
  listSpells,
  setPreparedSpells,
  getPreparedSpells,
  castSpell,
  listCasts,
  setConcentration,
  getConcentration,
  advanceConcentrationTurn,
  clearConcentration,
  addInventoryStackItem,
  listInventoryStackItems,
  removeInventoryStackItem,
  equipItem,
  getEquipmentSlot,
  attuneEquipmentSlot,
  consumeInventoryItem,
  getCharacterCurrency,
  transferCurrency,
  createLoot,
  voteLoot,
  assignLoot,
  getLoot,
  createCampaignNpc,
  updateCampaignNpcAgenda,
  getCampaignNpc,
  addNpcDialogue,
  getNpcDialogue,
  createCampaignFaction,
  adjustFactionReputation,
  getFactionReputation,
  createRelationship,
  updateRelationship,
  listRelationships,
  createClue,
  listClues,
  createCampaignQuest,
  listCampaignQuests,
  setCampaignQuestState,
  configureQuestRewards,
  awardQuestRewards,
  getCharacterQuestRewards,
  scheduleWorldEvent,
  resolveWorldEvent,
  listWorldEvents,
  initCalendar,
  getCalendar,
  advanceCalendar,
  createSettlement,
  updateSettlement,
  discoverSettlement,
  listSettlements,
  createShop,
  getShop,
  buyFromShop,
  sellToShop,
  createRecipe,
  listRecipes,
  craftRecipe,
  createDowntimeActivity,
  createDowntimeAllocation,
  progressDowntimeAllocation,
  getDowntimeAllocation,
  updateSessionZero,
  getSessionZero,
  createContent,
  updateContentTags,
  listContent,
  createNote,
  listNotes,
  getNote,
  updateNote,
  createWhisper,
  listWhispers,
  getCharacterSheet,
  createInvitation,
  acceptInvitation,
  listInvitations,
  grantDelegation,
  revokeDelegation,
  getDelegationAudit,
  createAuditEvent,
  getAuditEvents,
  createProjectionEvent,
  getProjection,
  rebuildProjection,
  createIdempotentEvent,
  getIdempotentEvents,
  submitSafeTurn,
  getSafeTurns,
  createTransactionalTransfer,
  listTransactionalTransfers,
  createCampaignExport,
  listCampaignExports,
  getCampaignExport,
  importCampaignSnapshot,
  getCampaignImportState,
  migrateCampaignSnapshot,
  getCampaignMigrationState,
  createSearchRecord,
  listSearchRecords,
  createRateEvent,
  listRateEvents,
  getServiceMetrics,
  isInMaintenance,
  setServiceMode,
  createCampaignBackup,
  listCampaignBackups,
  restoreCampaignBackup,
  appendReplayEvent,
  getReplayState,
  checkReplayState,
  configureRngSeed,
  appendRngRoll,
  getRngLedger,
  createModerationReport,
  listModerationReports,
  resolveModerationReport,
  replaceSafetyBoundaries,
  getSafetyBoundaries,
  submitSafetyCheck,
  listSafetyEvents,
  seedFixture,
  getFixtureState,
  createSpectatorTicket,
  getSpectatorView,
  appendFeedEvent,
  getEventFeed,
} from './domain/play/index.ts';
import type { ApiResult, JsonValue } from './types.ts';

function readJsonBody(req: IncomingMessage): Promise<JsonValue> {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (chunk) => {
      data += chunk;
    });
    req.on('end', () => {
      if (!data) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(data));
      } catch (err) {
        reject(err);
      }
    });
    req.on('error', reject);
  });
}

function sendJson(res: ServerResponse, result: ApiResult): void {
  const payload = JSON.stringify(result.body);
  res.statusCode = result.status;
  res.setHeader('Content-Type', 'application/json');
  res.end(payload);
}

async function handleJsonBodyRoute(
  req: IncomingMessage,
  res: ServerResponse,
  handler: (body: JsonValue) => ApiResult,
): Promise<void> {
  try {
    const body = await readJsonBody(req);
    sendJson(res, handler(body));
  } catch {
    sendJson(res, { status: 400, body: { error: 'invalid JSON body' } });
  }
}

async function handleAuthedJsonBodyRoute(
  req: IncomingMessage,
  res: ServerResponse,
  handler: (authHeader: string | undefined, body: JsonValue) => ApiResult,
): Promise<void> {
  try {
    const body = await readJsonBody(req);
    sendJson(res, handler(req.headers.authorization, body));
  } catch {
    sendJson(res, { status: 400, body: { error: 'invalid JSON body' } });
  }
}

async function handleAuthedIdempotentParamBodyRoute(
  req: IncomingMessage,
  res: ServerResponse,
  handler: (authHeader: string | undefined, param: string, idempotencyKey: string | undefined, body: JsonValue) => ApiResult,
  param: string,
): Promise<void> {
  try {
    const body = await readJsonBody(req);
    const idempotencyKeyHeader = req.headers['idempotency-key'];
    const idempotencyKey = Array.isArray(idempotencyKeyHeader) ? idempotencyKeyHeader[0] : idempotencyKeyHeader;
    sendJson(res, handler(req.headers.authorization, param, idempotencyKey, body));
  } catch {
    sendJson(res, { status: 400, body: { error: 'invalid JSON body' } });
  }
}

async function handleAuthedJsonParamBodyRoute(
  req: IncomingMessage,
  res: ServerResponse,
  handler: (authHeader: string | undefined, param: string, body: JsonValue) => ApiResult,
  param: string,
): Promise<void> {
  try {
    const body = await readJsonBody(req);
    sendJson(res, handler(req.headers.authorization, param, body));
  } catch {
    sendJson(res, { status: 400, body: { error: 'invalid JSON body' } });
  }
}

async function handleAuthedJsonTwoParamBodyRoute(
  req: IncomingMessage,
  res: ServerResponse,
  handler: (authHeader: string | undefined, p1: string, p2: string, body: JsonValue) => ApiResult,
  p1: string,
  p2: string,
): Promise<void> {
  try {
    const body = await readJsonBody(req);
    sendJson(res, handler(req.headers.authorization, p1, p2, body));
  } catch {
    sendJson(res, { status: 400, body: { error: 'invalid JSON body' } });
  }
}

async function handleAuthedJsonThreeParamBodyRoute(
  req: IncomingMessage,
  res: ServerResponse,
  handler: (authHeader: string | undefined, p1: string, p2: string, p3: string, body: JsonValue) => ApiResult,
  p1: string,
  p2: string,
  p3: string,
): Promise<void> {
  try {
    const body = await readJsonBody(req);
    sendJson(res, handler(req.headers.authorization, p1, p2, p3, body));
  } catch {
    sendJson(res, { status: 400, body: { error: 'invalid JSON body' } });
  }
}

async function handleAuthedJsonFourParamBodyRoute(
  req: IncomingMessage,
  res: ServerResponse,
  handler: (authHeader: string | undefined, p1: string, p2: string, p3: string, p4: string, body: JsonValue) => ApiResult,
  p1: string,
  p2: string,
  p3: string,
  p4: string,
): Promise<void> {
  try {
    const body = await readJsonBody(req);
    sendJson(res, handler(req.headers.authorization, p1, p2, p3, p4, body));
  } catch {
    sendJson(res, { status: 400, body: { error: 'invalid JSON body' } });
  }
}

// Static public schema for GET /v1/schema. Endpoints are sorted lexicographically
// by method, then path.
const API_SCHEMA = {
  version: '2026-07-29',
  endpoints: [
    { method: 'GET', path: '/v1/play/campaigns/{id}/rng-ledger', auth: 'member' },
    { method: 'GET', path: '/v1/schema', auth: 'public' },
    { method: 'POST', path: '/v1/play/campaigns', auth: 'dm' },
    { method: 'POST', path: '/v1/play/campaigns/{id}/fixture-seeds', auth: 'dm' },
    { method: 'POST', path: '/v1/play/campaigns/{id}/members', auth: 'member' },
    { method: 'POST', path: '/v1/play/campaigns/{id}/moderation/reports', auth: 'member' },
    { method: 'POST', path: '/v1/play/campaigns/{id}/rng-rolls', auth: 'member' },
    { method: 'PUT', path: '/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution', auth: 'dm' },
    { method: 'PUT', path: '/v1/play/campaigns/{id}/rng-seed', auth: 'dm' },
    { method: 'PUT', path: '/v1/play/campaigns/{id}/safety-boundaries', auth: 'dm' },
  ],
};

// Exact-path POST routes: request body in, ApiResult out.
const JSON_ROUTES: Record<string, (body: JsonValue) => ApiResult> = {
  '/v1/dice/stats': diceStats,
  '/v1/checks/ability': abilityCheck,
  '/v1/encounters/adjusted-xp': adjustedXp,
  '/v1/initiative/order': initiativeOrder,
  '/v1/characters/ability-modifier': abilityModifier,
  '/v1/characters/proficiency': proficiencyBonus,
  '/v1/characters/derived-stats': derivedStats,
  '/v1/auth/register': registerUser,
  '/v1/auth/login': loginUser,
  '/v1/compendium/monsters': createMonster,
  '/v1/compendium/items': createItem,
  '/v1/campaigns': createCampaign,
  '/v1/phb/spell-slots': spellSlots,
  '/v1/phb/rests/long': longRest,
  '/v1/phb/equipment-load': equipmentLoad,
  '/v1/dm/encounter-builder': encounterBuilder,
  '/v1/dm/loot-parcel': lootParcel,
  '/v1/dm/session-recap': sessionRecap,
  '/v1/combat/sessions': createCombatSession,
};

// Exact-path POST routes that require an Authorization header.
const AUTHED_JSON_ROUTES: Record<string, (authHeader: string | undefined, body: JsonValue) => ApiResult> = {
  '/v1/play/campaigns': createPlayCampaign,
};

// Authed POST routes with a path parameter, e.g. /v1/play/campaigns/:id/members.
const AUTHED_JSON_PARAM_ROUTES: {
  pattern: RegExp;
  handler: (authHeader: string | undefined, param: string, body: JsonValue) => ApiResult;
}[] = [
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/members$/, handler: joinPlayCampaign },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/start$/, handler: startPlayCampaign },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/narrations$/, handler: addNarration },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/messages$/, handler: addChatMessage },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/actions$/, handler: submitPlayerAction },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/resolutions$/, handler: submitResolution },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/turn\/nudge$/, handler: nudgePlayCampaignTurn },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/scenes$/, handler: createScene },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/locations$/, handler: createLocation },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/turn\/travel$/, handler: travelToLocation },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/turn\/rest$/, handler: restOnTurn },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/encounters$/, handler: createEncounter },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/loot$/, handler: createLoot },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/npcs$/, handler: createCampaignNpc },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/factions$/, handler: createCampaignFaction },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/relationships$/, handler: createRelationship },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/clues$/, handler: createClue },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/quests$/, handler: createCampaignQuest },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/world-events$/, handler: scheduleWorldEvent },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/calendar$/, handler: initCalendar },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/calendar\/advance$/, handler: advanceCalendar },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/settlements$/, handler: createSettlement },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/recipes$/, handler: createRecipe },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/downtime\/activities$/, handler: createDowntimeActivity },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/content$/, handler: createContent },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/notes$/, handler: createNote },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/whispers$/, handler: createWhisper },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/invitations$/, handler: createInvitation },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/delegations$/, handler: grantDelegation },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/audit-events$/, handler: createAuditEvent },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/projection-events$/, handler: createProjectionEvent },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/safe-turns$/, handler: submitSafeTurn },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/transactional-transfers$/, handler: createTransactionalTransfer },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/exports$/, handler: createCampaignExport },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/imports$/, handler: importCampaignSnapshot },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/migrations$/, handler: migrateCampaignSnapshot },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/search-records$/, handler: createSearchRecord },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/rate-events$/, handler: createRateEvent },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/service-mode$/, handler: setServiceMode },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/backups$/, handler: createCampaignBackup },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/replay-events$/, handler: appendReplayEvent },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/rng-rolls$/, handler: appendRngRoll },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/moderation\/reports$/, handler: createModerationReport },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/safety-checks$/, handler: submitSafetyCheck },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/fixture-seeds$/, handler: seedFixture },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/spectators$/, handler: createSpectatorTicket },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/feed-events$/, handler: appendFeedEvent },
];

// Authed POST routes with a path parameter that also require an
// Idempotency-Key header, e.g. /v1/play/campaigns/:id/idempotent-events.
const AUTHED_IDEMPOTENT_PARAM_ROUTES: {
  pattern: RegExp;
  handler: (authHeader: string | undefined, param: string, idempotencyKey: string | undefined, body: JsonValue) => ApiResult;
}[] = [
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/idempotent-events$/, handler: createIdempotentEvent },
];

// Authed POST routes with two path parameters and a body, e.g.
// /v1/play/campaigns/:id/locations/:from_id/connections.
const AUTHED_JSON_TWO_PARAM_ROUTES: {
  pattern: RegExp;
  handler: (authHeader: string | undefined, p1: string, p2: string, body: JsonValue) => ApiResult;
}[] = [
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/locations\/([^/]+)\/connections$/,
    handler: createLocationConnection,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/loot\/([^/]+)\/votes$/,
    handler: voteLoot,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/factions\/([^/]+)\/reputation$/,
    handler: adjustFactionReputation,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/npcs\/([^/]+)\/dialogue$/,
    handler: addNpcDialogue,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/world-events\/([^/]+)\/resolve$/,
    handler: resolveWorldEvent,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/settlements\/([^/]+)\/shops$/,
    handler: createShop,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/recipes\/([^/]+)\/craft$/,
    handler: craftRecipe,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/backups\/([^/]+)\/restore$/,
    handler: restoreCampaignBackup,
  },
];

// Authed POST routes with three path parameters and a body, e.g.
// /v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id/buy.
const AUTHED_JSON_THREE_PARAM_ROUTES: {
  pattern: RegExp;
  handler: (authHeader: string | undefined, p1: string, p2: string, p3: string, body: JsonValue) => ApiResult;
}[] = [
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/settlements\/([^/]+)\/shops\/([^/]+)\/buy$/,
    handler: buyFromShop,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/settlements\/([^/]+)\/shops\/([^/]+)\/sell$/,
    handler: sellToShop,
  },
];

// Authed POST routes with two path parameters and a body, e.g.
// /v1/play/campaigns/:id/encounters/:enc_id/monsters.
const AUTHED_JSON_TWO_PARAM_ROUTES_MONSTERS: {
  pattern: RegExp;
  handler: (authHeader: string | undefined, p1: string, p2: string, body: JsonValue) => ApiResult;
}[] = [
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/monsters$/,
    handler: addMonsterToEncounter,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/combatants$/,
    handler: bindEncounterCombatant,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/actions$/,
    handler: submitCombatAction,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/damage$/,
    handler: damageEncounterCombatant,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/heal$/,
    handler: healEncounterCombatant,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/damage$/,
    handler: damageCharacter,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/death-saves$/,
    handler: recordDeathSave,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/conditions$/,
    handler: addEncounterCondition,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/turn\/delay$/,
    handler: delayEncounterTurn,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/turn\/ready$/,
    handler: readyEncounterTurn,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/rewards$/,
    handler: awardEncounterRewards,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/claim$/,
    handler: claimCharacter,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/transfer$/,
    handler: transferCharacter,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/build$/,
    handler: buildCharacter,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/level-up$/,
    handler: levelUpCharacter,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/skill-check$/,
    handler: skillCheck,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/currency\/transfers$/,
    handler: transferCurrency,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/spells$/,
    handler: addSpell,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/casts$/,
    handler: castSpell,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/inventory\/items$/,
    handler: addInventoryStackItem,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/downtime\/allocations$/,
    handler: createDowntimeAllocation,
  },
];

// Authed DELETE routes with three path parameters, e.g.
// /v1/play/campaigns/:id/encounters/:enc_id/monsters/:monster_id.
const AUTHED_THREE_PARAM_ROUTES: {
  pattern: RegExp;
  handler: (authHeader: string | undefined, p1: string, p2: string, p3: string) => ApiResult;
}[] = [
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/monsters\/([^/]+)$/,
    handler: removeMonsterFromEncounter,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/combatants\/([^/]+)$/,
    handler: unbindEncounterCombatant,
  },
];

// Authed POST routes with two path parameters and no body, e.g.
// /v1/play/campaigns/:id/scenes/:scene_id/enter.
const AUTHED_PARAM_ROUTES: {
  pattern: RegExp;
  handler: (authHeader: string | undefined, p1: string, p2: string) => ApiResult;
}[] = [
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/scenes\/([^/]+)\/enter$/, handler: enterScene },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/scenes\/([^/]+)\/close$/, handler: closeScene },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/turn\/advance$/,
    handler: advanceEncounterTurn,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/close$/,
    handler: closeEncounter,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/end$/,
    handler: endEncounter,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/concentration\/advance-turn$/,
    handler: advanceConcentrationTurn,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/loot\/([^/]+)\/assign$/,
    handler: assignLoot,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/quests\/([^/]+)\/rewards\/award$/,
    handler: awardQuestRewards,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/settlements\/([^/]+)\/discover$/,
    handler: discoverSettlement,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/invitations\/([^/]+)\/accept$/,
    handler: acceptInvitation,
  },
];

// Authed PUT routes with a path parameter, e.g. /v1/play/campaigns/:id/document.
const AUTHED_JSON_PUT_PARAM_ROUTES: {
  pattern: RegExp;
  handler: (authHeader: string | undefined, param: string, body: JsonValue) => ApiResult;
}[] = [
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/document$/, handler: updateCampaignDocument },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/session-zero$/, handler: updateSessionZero },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/rng-seed$/, handler: configureRngSeed },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/safety-boundaries$/, handler: replaceSafetyBoundaries },
];

// Authed PUT routes with two path parameters, e.g.
// /v1/play/campaigns/:id/characters/:character_id/prepared-spells.
const AUTHED_JSON_PUT_TWO_PARAM_ROUTES: {
  pattern: RegExp;
  handler: (authHeader: string | undefined, p1: string, p2: string, body: JsonValue) => ApiResult;
}[] = [
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/prepared-spells$/,
    handler: setPreparedSpells,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/concentration$/,
    handler: setConcentration,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/npcs\/([^/]+)\/agenda$/,
    handler: updateCampaignNpcAgenda,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/quests\/([^/]+)\/state$/,
    handler: setCampaignQuestState,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/quests\/([^/]+)\/rewards$/,
    handler: configureQuestRewards,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/settlements\/([^/]+)$/,
    handler: updateSettlement,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/content\/([^/]+)\/tags$/,
    handler: updateContentTags,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/notes\/([^/]+)$/,
    handler: updateNote,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/moderation\/reports\/([^/]+)\/resolution$/,
    handler: resolveModerationReport,
  },
];

// Authed PUT routes with three path parameters, e.g.
// /v1/play/campaigns/:id/characters/:character_id/equipment/:slot.
const AUTHED_JSON_PUT_THREE_PARAM_ROUTES: {
  pattern: RegExp;
  handler: (authHeader: string | undefined, p1: string, p2: string, p3: string, body: JsonValue) => ApiResult;
}[] = [
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/equipment\/([^/]+)$/,
    handler: equipItem,
  },
];

// Authed PUT routes with four path parameters, e.g.
// /v1/play/campaigns/:id/relationships/:source_id/:target_id/:kind.
const AUTHED_JSON_PUT_FOUR_PARAM_ROUTES: {
  pattern: RegExp;
  handler: (authHeader: string | undefined, p1: string, p2: string, p3: string, p4: string, body: JsonValue) => ApiResult;
}[] = [
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/relationships\/([^/]+)\/([^/]+)\/([^/]+)$/,
    handler: updateRelationship,
  },
];

// Authed GET routes with three path parameters, e.g.
// /v1/play/campaigns/:id/characters/:character_id/equipment/:slot.
const AUTHED_GET_THREE_PARAM_ROUTES: {
  pattern: RegExp;
  handler: (authHeader: string | undefined, p1: string, p2: string, p3: string) => ApiResult;
}[] = [
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/equipment\/([^/]+)$/,
    handler: getEquipmentSlot,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/settlements\/([^/]+)\/shops\/([^/]+)$/,
    handler: getShop,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/downtime\/allocations\/([^/]+)$/,
    handler: getDowntimeAllocation,
  },
];

// Authed POST routes with three path parameters and no body, e.g.
// /v1/play/campaigns/:id/characters/:character_id/equipment/:slot/attune.
const AUTHED_THREE_PARAM_NO_BODY_ROUTES: {
  pattern: RegExp;
  handler: (authHeader: string | undefined, p1: string, p2: string, p3: string) => ApiResult;
}[] = [
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/equipment\/([^/]+)\/attune$/,
    handler: attuneEquipmentSlot,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/inventory\/items\/([^/]+)\/consume$/,
    handler: consumeInventoryItem,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/downtime\/allocations\/([^/]+)\/progress$/,
    handler: progressDowntimeAllocation,
  },
];

// Authed DELETE routes with two path parameters, e.g.
// /v1/play/campaigns/:id/characters/:character_id/concentration.
const AUTHED_DELETE_TWO_PARAM_ROUTES: {
  pattern: RegExp;
  handler: (authHeader: string | undefined, p1: string, p2: string) => ApiResult;
}[] = [
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/concentration$/,
    handler: clearConcentration,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/delegations\/([^/]+)$/,
    handler: revokeDelegation,
  },
];

// Authed DELETE routes with three path parameters and a body, e.g.
// /v1/play/campaigns/:id/characters/:character_id/inventory/items/:item_id.
const AUTHED_JSON_DELETE_THREE_PARAM_ROUTES: {
  pattern: RegExp;
  handler: (authHeader: string | undefined, p1: string, p2: string, p3: string, body: JsonValue) => ApiResult;
}[] = [
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/inventory\/items\/([^/]+)$/,
    handler: removeInventoryStackItem,
  },
];

// POST routes with a path parameter, e.g. /v1/combat/sessions/:id/conditions.
const JSON_PARAM_ROUTES: { pattern: RegExp; handler: (param: string, body: JsonValue) => ApiResult }[] = [
  { pattern: /^\/v1\/combat\/sessions\/([^/]+)\/conditions$/, handler: addCombatCondition },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/characters$/, handler: addCampaignCharacter },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/events$/, handler: addCampaignEvent },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/quests$/, handler: createQuest },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/factions$/, handler: createFaction },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/npcs$/, handler: createNpc },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/inventory$/, handler: addInventoryItem },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/downtime\/crafting$/, handler: createCraftingProject },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/sessions$/, handler: scheduleSession },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/analytics\/risk-report$/, handler: analyticsRiskReport },
];

// POST routes with two path parameters, e.g. /v1/campaigns/:id/quests/:quest_id/progress.
const JSON_TWO_PARAM_ROUTES: { pattern: RegExp; handler: (p1: string, p2: string, body: JsonValue) => ApiResult }[] = [
  { pattern: /^\/v1\/campaigns\/([^/]+)\/quests\/([^/]+)\/progress$/, handler: updateQuestProgress },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/characters\/([^/]+)\/equipment$/, handler: assignEquipment },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/downtime\/crafting\/([^/]+)\/advance$/, handler: advanceCrafting },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/sessions\/([^/]+)\/attendance$/, handler: recordAttendance },
];

// Authed GET routes with a path parameter, e.g. /v1/play/campaigns/:id/turn.
const AUTHED_GET_PARAM_ROUTES: {
  pattern: RegExp;
  handler: (authHeader: string | undefined, param: string) => ApiResult;
}[] = [
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/turn$/, handler: getPlayCampaignTurn },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/my-turn$/, handler: getPlayerTurnContext },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/gm\/status$/, handler: getGmStatus },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/onboarding$/, handler: getCampaignOnboarding },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/document$/, handler: getCampaignDocument },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/scenes\/current$/, handler: getCurrentScene },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/relationships$/, handler: listRelationships },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/clues$/, handler: listClues },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/quests$/, handler: listCampaignQuests },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/world-events$/, handler: listWorldEvents },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/calendar$/, handler: getCalendar },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/settlements$/, handler: listSettlements },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/recipes$/, handler: listRecipes },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/session-zero$/, handler: getSessionZero },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/notes$/, handler: listNotes },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/whispers$/, handler: listWhispers },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/invitations$/, handler: listInvitations },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/delegations\/audit$/, handler: getDelegationAudit },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/audit-events$/, handler: getAuditEvents },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/projection$/, handler: getProjection },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/projection\/rebuild$/, handler: rebuildProjection },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/idempotent-events$/, handler: getIdempotentEvents },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/safe-turns$/, handler: getSafeTurns },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/transactional-transfers$/, handler: listTransactionalTransfers },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/exports$/, handler: listCampaignExports },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/import-state$/, handler: getCampaignImportState },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/migration-state$/, handler: getCampaignMigrationState },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/rate-events$/, handler: listRateEvents },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/metrics$/, handler: getServiceMetrics },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/backups$/, handler: listCampaignBackups },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/replay$/, handler: getReplayState },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/replay\/check$/, handler: checkReplayState },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/rng-ledger$/, handler: getRngLedger },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/moderation\/reports$/, handler: listModerationReports },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/safety-boundaries$/, handler: getSafetyBoundaries },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/safety-events$/, handler: listSafetyEvents },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/fixture-state$/, handler: getFixtureState },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/spectator-view$/, handler: getSpectatorView },
];

// Authed GET routes with two path parameters, e.g.
// /v1/play/campaigns/:id/locations/:loc_id/travel.
const AUTHED_GET_TWO_PARAM_ROUTES: {
  pattern: RegExp;
  handler: (authHeader: string | undefined, p1: string, p2: string) => ApiResult;
}[] = [
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/locations\/([^/]+)\/travel$/, handler: getLocationTravel },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/turn$/, handler: getEncounterTurn },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/status$/, handler: getCharacterStatus },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/status$/, handler: getEncounterStatus },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/owner$/, handler: getCharacterOwner },
  { pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/spells$/, handler: listSpells },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/prepared-spells$/,
    handler: getPreparedSpells,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/casts$/,
    handler: listCasts,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/concentration$/,
    handler: getConcentration,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/inventory\/items$/,
    handler: listInventoryStackItems,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/currency$/,
    handler: getCharacterCurrency,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/loot\/([^/]+)$/,
    handler: getLoot,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/npcs\/([^/]+)$/,
    handler: getCampaignNpc,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/factions\/([^/]+)\/reputation$/,
    handler: getFactionReputation,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/npcs\/([^/]+)\/dialogue$/,
    handler: getNpcDialogue,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/rewards$/,
    handler: getCharacterQuestRewards,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/notes\/([^/]+)$/,
    handler: getNote,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/sheet$/,
    handler: getCharacterSheet,
  },
  {
    pattern: /^\/v1\/play\/campaigns\/([^/]+)\/exports\/([^/]+)$/,
    handler: getCampaignExport,
  },
];

// GET routes with a path parameter and no body, e.g. /v1/compendium/monsters/:slug.
const GET_PARAM_ROUTES: { pattern: RegExp; handler: (param: string) => ApiResult }[] = [
  { pattern: /^\/v1\/compendium\/monsters\/([^/]+)$/, handler: getMonster },
  { pattern: /^\/v1\/compendium\/items\/([^/]+)$/, handler: getItem },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/quests\/summary$/, handler: questSummary },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/state$/, handler: getCampaignState },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/relationships$/, handler: relationshipSummary },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/inventory\/summary$/, handler: inventorySummary },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/sessions\/next$/, handler: nextSession },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/audit$/, handler: campaignAudit },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/export$/, handler: campaignExport },
  { pattern: /^\/v1\/campaigns\/([^/]+)\/analytics\/summary$/, handler: analyticsSummary },
];

const ADVANCE_TURN_PATTERN = /^\/v1\/combat\/sessions\/([^/]+)\/advance$/;
const CONTENT_LIST_PATTERN = /^\/v1\/play\/campaigns\/([^/]+)\/content$/;
const SEARCH_RECORDS_LIST_PATTERN = /^\/v1\/play\/campaigns\/([^/]+)\/search-records$/;
const EVENT_FEED_LIST_PATTERN = /^\/v1\/play\/campaigns\/([^/]+)\/event-feed$/;

function apiMiddleware(): Connect.NextHandleFunction {
  return (req, res, next) => {
    const url = req.url ?? '';
    const path = url.split('?')[0];
    const method = req.method ?? 'GET';

    if (path === '/health' && method === 'GET') {
      sendJson(res, { status: 200, body: { ok: true } });
      return;
    }
    if (path === '/healthz' && method === 'GET') {
      sendJson(res, { status: 200, body: { status: 'ok' } });
      return;
    }
    if (path === '/readyz' && method === 'GET') {
      sendJson(
        res,
        isInMaintenance()
          ? { status: 503, body: { status: 'maintenance', schema_version: 2 } }
          : { status: 200, body: { status: 'ready', schema_version: 2 } },
      );
      return;
    }
    if (path === '/v1/schema' && method === 'GET') {
      sendJson(res, { status: 200, body: API_SCHEMA });
      return;
    }
    if (path === '/v1/storage/status' && method === 'GET') {
      sendJson(res, storageStatus());
      return;
    }
    if (path === '/v1/storage/reset' && method === 'POST') {
      sendJson(res, resetStorageHandler());
      return;
    }

    if (method === 'POST') {
      const authedHandler = AUTHED_JSON_ROUTES[path];
      if (authedHandler) {
        void handleAuthedJsonBodyRoute(req, res, authedHandler);
        return;
      }

      const handler = JSON_ROUTES[path];
      if (handler) {
        void handleJsonBodyRoute(req, res, handler);
        return;
      }

      for (const route of AUTHED_JSON_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          const param = decodeURIComponent(match[1]);
          void handleAuthedJsonParamBodyRoute(req, res, route.handler, param);
          return;
        }
      }

      for (const route of AUTHED_IDEMPOTENT_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          const param = decodeURIComponent(match[1]);
          void handleAuthedIdempotentParamBodyRoute(req, res, route.handler, param);
          return;
        }
      }

      for (const route of AUTHED_JSON_TWO_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          const p1 = decodeURIComponent(match[1]);
          const p2 = decodeURIComponent(match[2]);
          void handleAuthedJsonTwoParamBodyRoute(req, res, route.handler, p1, p2);
          return;
        }
      }

      for (const route of AUTHED_JSON_TWO_PARAM_ROUTES_MONSTERS) {
        const match = route.pattern.exec(path);
        if (match) {
          const p1 = decodeURIComponent(match[1]);
          const p2 = decodeURIComponent(match[2]);
          void handleAuthedJsonTwoParamBodyRoute(req, res, route.handler, p1, p2);
          return;
        }
      }

      for (const route of AUTHED_JSON_THREE_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          const p1 = decodeURIComponent(match[1]);
          const p2 = decodeURIComponent(match[2]);
          const p3 = decodeURIComponent(match[3]);
          void handleAuthedJsonThreeParamBodyRoute(req, res, route.handler, p1, p2, p3);
          return;
        }
      }

      for (const route of AUTHED_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          const p1 = decodeURIComponent(match[1]);
          const p2 = decodeURIComponent(match[2]);
          sendJson(res, route.handler(req.headers.authorization, p1, p2));
          return;
        }
      }

      for (const route of AUTHED_THREE_PARAM_NO_BODY_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          const p1 = decodeURIComponent(match[1]);
          const p2 = decodeURIComponent(match[2]);
          const p3 = decodeURIComponent(match[3]);
          sendJson(res, route.handler(req.headers.authorization, p1, p2, p3));
          return;
        }
      }

      for (const route of JSON_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          const param = decodeURIComponent(match[1]);
          void handleJsonBodyRoute(req, res, (body) => route.handler(param, body));
          return;
        }
      }

      for (const route of JSON_TWO_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          const p1 = decodeURIComponent(match[1]);
          const p2 = decodeURIComponent(match[2]);
          void handleJsonBodyRoute(req, res, (body) => route.handler(p1, p2, body));
          return;
        }
      }

      const advanceMatch = ADVANCE_TURN_PATTERN.exec(path);
      if (advanceMatch) {
        sendJson(res, advanceCombatTurn(decodeURIComponent(advanceMatch[1])));
        return;
      }
    }

    if (method === 'DELETE') {
      for (const route of AUTHED_THREE_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          const p1 = decodeURIComponent(match[1]);
          const p2 = decodeURIComponent(match[2]);
          const p3 = decodeURIComponent(match[3]);
          sendJson(res, route.handler(req.headers.authorization, p1, p2, p3));
          return;
        }
      }

      for (const route of AUTHED_DELETE_TWO_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          const p1 = decodeURIComponent(match[1]);
          const p2 = decodeURIComponent(match[2]);
          sendJson(res, route.handler(req.headers.authorization, p1, p2));
          return;
        }
      }

      for (const route of AUTHED_JSON_DELETE_THREE_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          const p1 = decodeURIComponent(match[1]);
          const p2 = decodeURIComponent(match[2]);
          const p3 = decodeURIComponent(match[3]);
          void handleAuthedJsonThreeParamBodyRoute(req, res, route.handler, p1, p2, p3);
          return;
        }
      }
    }

    if (method === 'PUT') {
      for (const route of AUTHED_JSON_PUT_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          const param = decodeURIComponent(match[1]);
          void handleAuthedJsonParamBodyRoute(req, res, route.handler, param);
          return;
        }
      }

      for (const route of AUTHED_JSON_PUT_TWO_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          const p1 = decodeURIComponent(match[1]);
          const p2 = decodeURIComponent(match[2]);
          void handleAuthedJsonTwoParamBodyRoute(req, res, route.handler, p1, p2);
          return;
        }
      }

      for (const route of AUTHED_JSON_PUT_THREE_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          const p1 = decodeURIComponent(match[1]);
          const p2 = decodeURIComponent(match[2]);
          const p3 = decodeURIComponent(match[3]);
          void handleAuthedJsonThreeParamBodyRoute(req, res, route.handler, p1, p2, p3);
          return;
        }
      }

      for (const route of AUTHED_JSON_PUT_FOUR_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          const p1 = decodeURIComponent(match[1]);
          const p2 = decodeURIComponent(match[2]);
          const p3 = decodeURIComponent(match[3]);
          const p4 = decodeURIComponent(match[4]);
          void handleAuthedJsonFourParamBodyRoute(req, res, route.handler, p1, p2, p3, p4);
          return;
        }
      }
    }

    if (method === 'GET') {
      const contentMatch = CONTENT_LIST_PATTERN.exec(path);
      if (contentMatch) {
        const campaignId = decodeURIComponent(contentMatch[1]);
        const query = new URLSearchParams(url.split('?')[1] ?? '');
        const excludeTag = query.has('exclude_tag') ? query.get('exclude_tag') ?? '' : undefined;
        sendJson(res, listContent(req.headers.authorization, campaignId, excludeTag));
        return;
      }

      const searchRecordsMatch = SEARCH_RECORDS_LIST_PATTERN.exec(path);
      if (searchRecordsMatch) {
        const campaignId = decodeURIComponent(searchRecordsMatch[1]);
        const query = new URLSearchParams(url.split('?')[1] ?? '');
        sendJson(
          res,
          listSearchRecords(req.headers.authorization, campaignId, {
            q: query.has('q') ? query.get('q') ?? '' : null,
            limit: query.has('limit') ? query.get('limit') ?? '' : null,
            cursor: query.has('cursor') ? query.get('cursor') ?? '' : null,
          }),
        );
        return;
      }

      const eventFeedMatch = EVENT_FEED_LIST_PATTERN.exec(path);
      if (eventFeedMatch) {
        const campaignId = decodeURIComponent(eventFeedMatch[1]);
        const query = new URLSearchParams(url.split('?')[1] ?? '');
        sendJson(
          res,
          getEventFeed(req.headers.authorization, campaignId, {
            cursor: query.has('cursor') ? query.get('cursor') ?? '' : null,
            limit: query.has('limit') ? query.get('limit') ?? '' : null,
          }),
        );
        return;
      }

      for (const route of AUTHED_GET_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          sendJson(res, route.handler(req.headers.authorization, decodeURIComponent(match[1])));
          return;
        }
      }

      for (const route of AUTHED_GET_TWO_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          const p1 = decodeURIComponent(match[1]);
          const p2 = decodeURIComponent(match[2]);
          sendJson(res, route.handler(req.headers.authorization, p1, p2));
          return;
        }
      }

      for (const route of AUTHED_GET_THREE_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          const p1 = decodeURIComponent(match[1]);
          const p2 = decodeURIComponent(match[2]);
          const p3 = decodeURIComponent(match[3]);
          sendJson(res, route.handler(req.headers.authorization, p1, p2, p3));
          return;
        }
      }

      for (const route of GET_PARAM_ROUTES) {
        const match = route.pattern.exec(path);
        if (match) {
          sendJson(res, route.handler(decodeURIComponent(match[1])));
          return;
        }
      }
    }

    next();
  };
}

export function dndApiPlugin(): Plugin {
  return {
    name: 'dnd-rest-api',
    configureServer(server: ViteDevServer) {
      initStorage();
      server.middlewares.use(apiMiddleware());
    },
  };
}
