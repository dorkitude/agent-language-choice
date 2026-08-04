import { IncomingMessage, ServerResponse } from 'node:http';
import { sendJSON } from './http-utils.js';
import { health } from './routes/health.js';
import { storageReset, storageStatus } from './routes/storage.js';
import {
  handleAbilityModifier,
  handleDerivedStats,
  handleProficiencyBonus,
} from './routes/characters.js';
import { handleDiceStats } from './routes/dice.js';
import { handleAbilityCheck } from './routes/checks.js';
import { handleAdjustedXP } from './routes/encounters.js';
import { handleInitiativeOrder } from './routes/initiative.js';
import {
  handleAddCondition,
  handleAdvanceCombat,
  handleCreateCombatSession,
} from './routes/combat.js';
import { handleLogin, handleRegister } from './routes/auth.js';
import {
  handleCreateItem,
  handleCreateMonster,
  handleGetItem,
  handleGetMonster,
} from './routes/compendium.js';
import {
  handleAddCampaignCharacter,
  handleAddCampaignEvent,
  handleCampaignAudit,
  handleCampaignExport,
  handleCampaignState,
  handleCreateCampaign,
} from './routes/campaigns.js';
import {
  handleCreateQuest,
  handleQuestSummary,
  handleUpdateQuestProgress,
} from './routes/quests.js';
import {
  handleAdvanceCraftingProject,
  handleCreateCraftingProject,
} from './routes/crafting.js';
import {
  handleCreateFaction,
  handleCreateNPC,
  handleRelationshipSummary,
} from './routes/relationships.js';
import { handleEquipmentLoad, handleLongRest, handleSpellSlots } from './routes/phb.js';
import { handleAddEncounterCondition, handleAddMonsterToEncounter, handleAddNarration, handleAdvanceEncounterTurn, handleAwardRewards, handleBindMemberToEncounter, handleBuildCharacter, handleCharacterDamage, handleClaimCharacter, handleCloseEncounter, handleCreatePlayCampaign, handleCreatePlayEncounter, handleDamage, handleDeathSaves, handleDelayEncounterTurn, handleEndEncounter, handleGetCharacterOwner, handleGetCharacterStatus, handleGetEncounterStatus, handleGetEncounterTurn, handleGetGMStatus, handleGetMyTurn, handleGetPlayCampaignTurn, handleHeal, handleJoinPlayCampaign, handleLevelUp, handleReadyEncounterTurn, handleRemoveMonsterFromEncounter, handleResolution, handleRestTurn, handleStartPlayCampaign, handleSubmitAction, handleSubmitCombatAction, handleTransferCharacter, handleTravelTurn, handleTurnNudge, handleUnbindMemberFromEncounter } from './routes/play-campaigns.js';
import { handleGetCampaignDocument, handleUpdateCampaignDocument } from './routes/campaign-documents.js';
import { handleCloseScene, handleCreateScene, handleEnterScene, handleGetCurrentScene } from './routes/scenes.js';
import { handleCreateLocation, handleCreateLocationConnection, handleGetTravel } from './routes/locations.js';
import {
  handleEncounterBuilder,
  handleLootParcel,
  handleSessionRecap,
} from './routes/dm.js';
import {
  handleAddInventoryItem,
  handleAssignEquipment,
  handleInventorySummary,
} from './routes/inventory.js';
import {
  handleAnalyticsSummary,
  handleRiskReport,
} from './routes/analytics.js';
import {
  handleNextSession,
  handleRecordAttendance,
  handleScheduleSession,
} from './routes/sessions.js';

type RouteHandler = (res: ServerResponse, params: Record<string, string>, body: unknown, req: IncomingMessage) => Promise<void> | void;

/** Route definition: HTTP method, path pattern, and the handler to invoke. */
interface Route {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE';
  pattern: string;
  handler: RouteHandler;
}

const routes: Route[] = [
  // Health and storage
  { method: 'GET', pattern: '/health', handler: health },
  { method: 'GET', pattern: '/v1/storage/status', handler: storageStatus },
  { method: 'POST', pattern: '/v1/storage/reset', handler: storageReset },

  // Characters
  { method: 'POST', pattern: '/v1/characters/ability-modifier', handler: handleAbilityModifier },
  { method: 'POST', pattern: '/v1/characters/proficiency', handler: handleProficiencyBonus },
  { method: 'POST', pattern: '/v1/characters/derived-stats', handler: handleDerivedStats },

  // Dice and checks
  { method: 'POST', pattern: '/v1/dice/stats', handler: handleDiceStats },
  { method: 'POST', pattern: '/v1/checks/ability', handler: handleAbilityCheck },

  // Encounters and initiative
  { method: 'POST', pattern: '/v1/encounters/adjusted-xp', handler: handleAdjustedXP },
  { method: 'POST', pattern: '/v1/initiative/order', handler: handleInitiativeOrder },

  // Combat sessions
  { method: 'POST', pattern: '/v1/combat/sessions', handler: handleCreateCombatSession },
  { method: 'POST', pattern: '/v1/combat/sessions/:id/conditions', handler: handleAddCondition },
  { method: 'POST', pattern: '/v1/combat/sessions/:id/advance', handler: handleAdvanceCombat },

  // Auth
  { method: 'POST', pattern: '/v1/auth/register', handler: handleRegister },
  { method: 'POST', pattern: '/v1/auth/login', handler: handleLogin },

  // Compendium
  { method: 'GET', pattern: '/v1/compendium/monsters/:slug', handler: handleGetMonster },
  { method: 'POST', pattern: '/v1/compendium/monsters', handler: handleCreateMonster },
  { method: 'GET', pattern: '/v1/compendium/items/:slug', handler: handleGetItem },
  { method: 'POST', pattern: '/v1/compendium/items', handler: handleCreateItem },

  // Campaigns
  { method: 'GET', pattern: '/v1/campaigns/:id/state', handler: handleCampaignState },
  { method: 'GET', pattern: '/v1/campaigns/:id/audit', handler: handleCampaignAudit },
  { method: 'GET', pattern: '/v1/campaigns/:id/export', handler: handleCampaignExport },
  { method: 'GET', pattern: '/v1/campaigns/:id/analytics/summary', handler: handleAnalyticsSummary },
  { method: 'POST', pattern: '/v1/campaigns/:id/analytics/risk-report', handler: handleRiskReport },
  { method: 'GET', pattern: '/v1/campaigns/:id/quests/summary', handler: handleQuestSummary },
  { method: 'GET', pattern: '/v1/campaigns/:id/relationships', handler: handleRelationshipSummary },
  { method: 'GET', pattern: '/v1/campaigns/:id/inventory/summary', handler: handleInventorySummary },
  { method: 'POST', pattern: '/v1/campaigns', handler: handleCreateCampaign },
  { method: 'POST', pattern: '/v1/campaigns/:id/characters', handler: handleAddCampaignCharacter },
  { method: 'POST', pattern: '/v1/campaigns/:id/events', handler: handleAddCampaignEvent },
  { method: 'POST', pattern: '/v1/campaigns/:id/factions', handler: handleCreateFaction },
  { method: 'POST', pattern: '/v1/campaigns/:id/npcs', handler: handleCreateNPC },
  { method: 'POST', pattern: '/v1/campaigns/:id/quests', handler: handleCreateQuest },
  { method: 'POST', pattern: '/v1/campaigns/:id/quests/:quest_id/progress', handler: handleUpdateQuestProgress },
  { method: 'POST', pattern: '/v1/campaigns/:id/inventory', handler: handleAddInventoryItem },
  { method: 'POST', pattern: '/v1/campaigns/:id/characters/:character_id/equipment', handler: handleAssignEquipment },
  { method: 'POST', pattern: '/v1/campaigns/:id/downtime/crafting', handler: handleCreateCraftingProject },
  { method: 'POST', pattern: '/v1/campaigns/:id/downtime/crafting/:project_id/advance', handler: handleAdvanceCraftingProject },
  { method: 'GET', pattern: '/v1/campaigns/:id/sessions/next', handler: handleNextSession },
  { method: 'POST', pattern: '/v1/campaigns/:id/sessions', handler: handleScheduleSession },
  { method: 'POST', pattern: '/v1/campaigns/:id/sessions/:session_id/attendance', handler: handleRecordAttendance },

  // Play campaigns
  { method: 'GET', pattern: '/v1/play/campaigns/:id/turn', handler: handleGetPlayCampaignTurn },
  { method: 'GET', pattern: '/v1/play/campaigns/:id/my-turn', handler: handleGetMyTurn },
  { method: 'GET', pattern: '/v1/play/campaigns/:id/gm/status', handler: handleGetGMStatus },
  { method: 'POST', pattern: '/v1/play/campaigns', handler: handleCreatePlayCampaign },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/members', handler: handleJoinPlayCampaign },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/start', handler: handleStartPlayCampaign },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/narrations', handler: handleAddNarration },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/turn/nudge', handler: handleTurnNudge },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/actions', handler: handleSubmitAction },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/turn/travel', handler: handleTravelTurn },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/turn/rest', handler: handleRestTurn },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/encounters', handler: handleCreatePlayEncounter },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/encounters/:enc_id/monsters', handler: handleAddMonsterToEncounter },
  { method: 'DELETE', pattern: '/v1/play/campaigns/:id/encounters/:enc_id/monsters/:monster_id', handler: handleRemoveMonsterFromEncounter },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/encounters/:enc_id/combatants', handler: handleBindMemberToEncounter },
  { method: 'DELETE', pattern: '/v1/play/campaigns/:id/encounters/:enc_id/combatants/:member', handler: handleUnbindMemberFromEncounter },
  { method: 'GET', pattern: '/v1/play/campaigns/:id/encounters/:enc_id/turn', handler: handleGetEncounterTurn },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/encounters/:enc_id/turn/advance', handler: handleAdvanceEncounterTurn },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/encounters/:enc_id/turn/delay', handler: handleDelayEncounterTurn },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/encounters/:enc_id/turn/ready', handler: handleReadyEncounterTurn },
  { method: 'GET', pattern: '/v1/play/campaigns/:id/encounters/:enc_id/status', handler: handleGetEncounterStatus },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/encounters/:enc_id/conditions', handler: handleAddEncounterCondition },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/encounters/:enc_id/actions', handler: handleSubmitCombatAction },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/encounters/:enc_id/damage', handler: handleDamage },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/encounters/:enc_id/heal', handler: handleHeal },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/encounters/:enc_id/rewards', handler: handleAwardRewards },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/encounters/:enc_id/close', handler: handleCloseEncounter },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/encounters/:enc_id/end', handler: handleEndEncounter },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/characters/:char_id/damage', handler: handleCharacterDamage },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/characters/:char_id/death-saves', handler: handleDeathSaves },
  { method: 'GET', pattern: '/v1/play/campaigns/:id/characters/:char_id/status', handler: handleGetCharacterStatus },
  { method: 'GET', pattern: '/v1/play/campaigns/:id/characters/:char_id/owner', handler: handleGetCharacterOwner },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/characters/:char_id/claim', handler: handleClaimCharacter },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/characters/:char_id/transfer', handler: handleTransferCharacter },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/characters/:char_id/build', handler: handleBuildCharacter },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/characters/:char_id/level-up', handler: handleLevelUp },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/resolutions', handler: handleResolution },
  { method: 'GET', pattern: '/v1/play/campaigns/:id/document', handler: handleGetCampaignDocument },
  { method: 'PUT', pattern: '/v1/play/campaigns/:id/document', handler: handleUpdateCampaignDocument },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/scenes', handler: handleCreateScene },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/scenes/:scene_id/enter', handler: handleEnterScene },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/scenes/:scene_id/close', handler: handleCloseScene },
  { method: 'GET', pattern: '/v1/play/campaigns/:id/scenes/current', handler: handleGetCurrentScene },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/locations', handler: handleCreateLocation },
  { method: 'POST', pattern: '/v1/play/campaigns/:id/locations/:from_id/connections', handler: handleCreateLocationConnection },
  { method: 'GET', pattern: '/v1/play/campaigns/:id/locations/:loc_id/travel', handler: handleGetTravel },

  // PHB rules
  { method: 'POST', pattern: '/v1/phb/spell-slots', handler: handleSpellSlots },
  { method: 'POST', pattern: '/v1/phb/rests/long', handler: handleLongRest },
  { method: 'POST', pattern: '/v1/phb/equipment-load', handler: handleEquipmentLoad },

  // DM tools
  { method: 'POST', pattern: '/v1/dm/encounter-builder', handler: handleEncounterBuilder },
  { method: 'POST', pattern: '/v1/dm/loot-parcel', handler: handleLootParcel },
  { method: 'POST', pattern: '/v1/dm/session-recap', handler: handleSessionRecap },
];

/** Extract the URL pathname from the request, ignoring query parameters. */
function getPath(req: IncomingMessage): string {
  const url = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`);
  return url.pathname;
}

/**
 * Match a concrete path against a route pattern. Segments starting with `:`
 * are captured as named parameters. Returns `null` when the path does not match.
 */
export function matchPath(path: string, pattern: string): Record<string, string> | null {
  const pathParts = path.split('/').filter(Boolean);
  const patternParts = pattern.split('/').filter(Boolean);
  if (pathParts.length !== patternParts.length) return null;

  const params: Record<string, string> = {};
  for (let i = 0; i < patternParts.length; i++) {
    const part = patternParts[i];
    if (part.startsWith(':')) {
      params[part.slice(1)] = pathParts[i];
      continue;
    }
    if (part !== pathParts[i]) return null;
  }
  return params;
}

export async function handleGet(req: IncomingMessage, res: ServerResponse): Promise<boolean> {
  if (req.method !== 'GET') return false;
  return dispatch(req, res, {});
}

export async function handlePost(req: IncomingMessage, res: ServerResponse, body: unknown): Promise<boolean> {
  if (req.method !== 'POST') return false;
  return dispatch(req, res, body);
}

export async function handlePut(req: IncomingMessage, res: ServerResponse, body: unknown): Promise<boolean> {
  if (req.method !== 'PUT') return false;
  return dispatch(req, res, body);
}

export async function handleDelete(req: IncomingMessage, res: ServerResponse): Promise<boolean> {
  if (req.method !== 'DELETE') return false;
  return dispatch(req, res, {});
}

/** Find the first matching route and delegate to its handler. */
async function dispatch(req: IncomingMessage, res: ServerResponse, body: unknown): Promise<boolean> {
  const path = getPath(req);
  for (const route of routes) {
    if (route.method !== req.method) continue;
    const params = matchPath(path, route.pattern);
    if (params) {
      await route.handler(res, params, body, req);
      return true;
    }
  }
  return false;
}

export function sendMethodNotAllowed(res: ServerResponse): void {
  sendJSON(res, 405, { error: 'method not allowed' });
}

export function sendNotFound(res: ServerResponse): void {
  sendJSON(res, 404, { error: 'not found' });
}
