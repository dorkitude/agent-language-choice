// Play-mode campaign handlers: lobby management, turn-based actions, and the
// shared campaign document. Authorization is deliberately strict so that the
// DM/owner, party members, and arbitrary actors see different error codes.

import type { IncomingMessage, ServerResponse } from 'node:http';
import { sendError, sendJson } from '../http.js';
import { getAuthUser } from '../auth.js';
import {
  addEncounterCondition,
  addEncounterMember,
  addEncounterMonster,
  advanceEncounterTurn,
  decrementEncounterConditions,
  getEncounterConditions,
  getEncounterConditionsForTarget,
  advancePlayCampaign,
  closePlayScene,
  createCombatAction,
  createConnection,
  createEncounter,
  createLocation,
  createPlayAction,
  createPlayCampaign,
  createPlayCampaignMember,
  createPlayLocationEvent,
  createPlayNarration,
  createPlayResolution,
  createPlayRest,
  createPlayScene,
  createPlayTravel,
  countPlayCampaignMembers,
  encounterExists,
  getActiveEncounter,
  getConnection,
  getConnectionsFrom,
  getEncounter,
  getEncounterActiveCombatant,
  getEncounterTurnOrder,
  getLocation,
  getPlayCampaign,
  getPlayCampaignCurrentScene,
  getPlayCampaignDocument,
  getPlayCampaignMemberByCharacterId,
  getPlayCampaignMemberByPlayer,
  getPlayCampaignMembers,
  getPlayEventsByCampaign,
  getPlayScene,
  incrementPlayCampaignNudgeCount,
  playCampaignExists,
  removeEncounterMember,
  removeEncounterMonster,
  setEncounterCombatants,
  setPlayCampaignCurrentActor,
  setPlayCampaignCurrentLocation,
  setPlayCampaignCurrentScene,
  recordDeathSave,
  setPlayCampaignMemberHp,
  startPlayCampaign,
  updateEncounterMonsterHp,
  upsertPlayCampaignDocument,
} from '../db.js';
import { isCombatActionType, isDeathSaveOutcome, isNonEmptyString, isPositiveInteger } from '../validation.js';
import type { Encounter, Location, PlayCampaign, PlayCampaignMember, PlayScene, RosterMonster } from '../types.js';

export function handleCreatePlayCampaign(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  if (pathname !== '/v1/play/campaigns') return false;

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }
  if (user.role !== 'dm') {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const b = body as any;
  if (!b || !isNonEmptyString(b.id) || !isNonEmptyString(b.name) || !isPositiveInteger(b.max_players)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  if (playCampaignExists(b.id)) {
    sendError(res, 409, 'campaign already exists');
    return true;
  }

  const campaign: PlayCampaign = {
    id: b.id,
    name: b.name,
    owner: user.username,
    status: 'lobby',
    max_players: b.max_players,
  };
  createPlayCampaign(campaign);
  sendJson(res, 201, campaign);
  return true;
}

export function handleJoinPlayCampaign(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/(.+)\/members$/);
  if (!match) return false;
  const campaignId = match[1];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }
  if (user.role !== 'player') {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const b = body as any;
  if (!b || !isNonEmptyString(b.character_id) || !isNonEmptyString(b.name) || !isNonEmptyString(b.class)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  if (!playCampaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  const campaign = getPlayCampaign(campaignId)!;
  if (countPlayCampaignMembers(campaignId) >= campaign.max_players) {
    sendError(res, 409, 'party full');
    return true;
  }

  if (getPlayCampaignMemberByPlayer(campaignId, user.username)) {
    sendError(res, 409, 'already a member');
    return true;
  }

  if (getPlayCampaignMemberByCharacterId(b.character_id)) {
    sendError(res, 409, 'character already exists');
    return true;
  }

  const member: PlayCampaignMember = {
    campaign_id: campaignId,
    username: user.username,
    character_id: b.character_id,
    name: b.name,
    class: b.class,
  };
  if (isPositiveInteger(b.hp_max)) {
    member.hp_max = b.hp_max;
  }
  if (typeof b.hp_current === 'number' && Number.isInteger(b.hp_current) && b.hp_current >= 0 && b.hp_current <= (member.hp_max ?? 20)) {
    member.hp_current = b.hp_current;
  }
  createPlayCampaignMember(member);
  sendJson(res, 201, {
    username: member.username,
    character_id: member.character_id,
    name: member.name,
    class: member.class,
  });
  return true;
}

export function handleStartPlayCampaign(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/(.+)\/start$/);
  if (!match) return false;
  const campaignId = match[1];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }
  if (user.role !== 'dm') {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  if (campaign.status === 'active') {
    sendError(res, 409, 'campaign already active');
    return true;
  }

  const members = getPlayCampaignMembers(campaignId);
  if (members.length < 2) {
    sendError(res, 409, 'insufficient party members');
    return true;
  }

  const currentActor = members[0].username;
  startPlayCampaign(campaignId, currentActor, 1);
  sendJson(res, 200, {
    id: campaignId,
    status: 'active',
    current_actor: currentActor,
    turn_number: 1,
  });
  return true;
}

export function handleGetPlayCampaignTurn(
  pathname: string,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/(.+)\/turn$/);
  if (!match) return false;
  const campaignId = match[1];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username && !getPlayCampaignMemberByPlayer(campaignId, user.username)) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const phase =
    campaign.status === 'lobby'
      ? 'lobby'
      : campaign.current_actor === campaign.owner
        ? 'dm'
        : 'player';

  const members = getPlayCampaignMembers(campaignId);
  const queue: string[] = [];
  if (campaign.status === 'active') {
    for (const member of members) {
      queue.push(member.username);
      queue.push(campaign.owner);
    }
  }

  const logical_deadline = campaign.status === 'active' && campaign.turn_number !== undefined
    ? campaign.turn_number + 1
    : 0;

  sendJson(res, 200, {
    campaign_id: campaignId,
    current_actor: campaign.current_actor ?? null,
    phase,
    turn_number: campaign.turn_number ?? null,
    queue,
    overdue: false,
    logical_deadline,
  });
  return true;
}

export function handleGetPlayCampaignGMStatus(
  pathname: string,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/(.+)\/gm\/status$/);
  if (!match) return false;
  const campaignId = match[1];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const members = getPlayCampaignMembers(campaignId);
  const party = members.map((m) => ({
    username: m.username,
    character_id: m.character_id,
    name: m.name,
    class: m.class,
    is_current: m.username === campaign.current_actor,
  }));

  const recent_events = getPlayEventsByCampaign(campaignId);

  sendJson(res, 200, {
    needs_attention: campaign.current_actor === campaign.owner,
    current_actor: campaign.current_actor ?? null,
    party,
    recent_events,
  });
  return true;
}

export function handleGetPlayCampaignMyTurn(
  pathname: string,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/(.+)\/my-turn$/);
  if (!match) return false;
  const campaignId = match[1];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }
  if (user.role !== 'player') {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  const member = getPlayCampaignMemberByPlayer(campaignId, user.username);
  if (!member) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const events = getPlayEventsByCampaign(campaignId);

  sendJson(res, 200, {
    is_my_turn: campaign.status === 'active' && campaign.current_actor === user.username,
    current_actor: campaign.current_actor ?? null,
    character: { id: member.character_id, name: member.name },
    recent_events: events,
  });
  return true;
}

export function handleCreatePlayNarration(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/(.+)\/narrations$/);
  if (!match) return false;
  const campaignId = match[1];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }
  if (user.role !== 'dm') {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const b = body as any;
  if (!b || !isNonEmptyString(b.text)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  const narration = createPlayNarration(campaignId, 'dm', b.text);
  sendJson(res, 201, {
    sequence: narration.sequence,
    kind: 'narration',
    actor: narration.actor,
    text: narration.text,
  });
  return true;
}

export function handleCreatePlayResolution(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/(.+)\/resolutions$/);
  if (!match) return false;
  const campaignId = match[1];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 409, 'not your turn');
    return true;
  }

  if (campaign.status !== 'active' || campaign.current_actor !== campaign.owner) {
    sendError(res, 409, 'not your turn');
    return true;
  }

  const b = body as any;
  if (!b || !isNonEmptyString(b.text)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  const members = getPlayCampaignMembers(campaignId);
  if (members.length < 2) {
    sendError(res, 409, 'insufficient party members');
    return true;
  }

  const resolution = createPlayResolution(campaignId, user.username, b.text);
  const nextTurnNumber = (campaign.turn_number ?? 1) + 1;
  const nextActor = members[(nextTurnNumber - 1) % members.length].username;
  advancePlayCampaign(campaignId, nextActor, nextTurnNumber);

  sendJson(res, 201, {
    sequence: resolution.sequence,
    kind: 'resolution',
    actor: resolution.actor,
    text: resolution.text,
    next_actor: nextActor,
    turn_number: nextTurnNumber,
  });
  return true;
}

export function handleCreatePlayNudge(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/(.+)\/turn\/nudge$/);
  if (!match) return false;
  const campaignId = match[1];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const b = body as any;
  if (!b || !isNonEmptyString(b.message)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  const nudgeCount = incrementPlayCampaignNudgeCount(campaignId);
  sendJson(res, 201, {
    actor: user.username,
    target: campaign.current_actor ?? null,
    message: b.message,
    nudge_count: nudgeCount,
  });
  return true;
}

export function handleCreatePlayAction(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/(.+)\/actions$/);
  if (!match) return false;
  const campaignId = match[1];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  const member = getPlayCampaignMemberByPlayer(campaignId, user.username);
  if (!member) {
    if (user.role === 'dm' || user.username === campaign.owner) {
      sendError(res, 409, 'not your turn');
      return true;
    }
    sendError(res, 403, 'forbidden');
    return true;
  }

  if (user.role !== 'player' || campaign.status !== 'active' || campaign.current_actor !== user.username) {
    sendError(res, 409, 'not your turn');
    return true;
  }

  const b = body as any;
  if (!b || !isNonEmptyString(b.type) || !isNonEmptyString(b.text)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  const action = createPlayAction(campaignId, user.username, b.type, b.text);
  setPlayCampaignCurrentActor(campaignId, campaign.owner);
  sendJson(res, 201, {
    sequence: action.sequence,
    kind: 'action',
    actor: action.actor,
    type: action.type,
    text: action.text,
    next_actor: 'dm',
  });
  return true;
}

export function handleCreatePlayTravel(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/(.+)\/turn\/travel$/);
  if (!match) return false;
  const campaignId = match[1];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  const member = getPlayCampaignMemberByPlayer(campaignId, user.username);
  if (!member) {
    if (user.role === 'dm' || user.username === campaign.owner) {
      sendError(res, 409, 'not your turn');
      return true;
    }
    sendError(res, 403, 'forbidden');
    return true;
  }

  if (user.role !== 'player' || campaign.status !== 'active' || campaign.current_actor !== user.username) {
    sendError(res, 409, 'not your turn');
    return true;
  }

  const b = body as any;
  if (!b || !isNonEmptyString(b.destination_id)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  const currentLocationId = campaign.current_location_id;
  if (!currentLocationId || !getLocation(campaignId, currentLocationId)) {
    sendError(res, 409, 'invalid destination');
    return true;
  }

  const connection = getConnection(campaignId, currentLocationId, b.destination_id);
  if (!connection) {
    sendError(res, 409, 'invalid destination');
    return true;
  }

  const travel = createPlayTravel(campaignId, user.username, b.destination_id, connection.travel_turns);
  setPlayCampaignCurrentActor(campaignId, campaign.owner);
  setPlayCampaignCurrentLocation(campaignId, b.destination_id);
  sendJson(res, 201, {
    sequence: travel.sequence,
    kind: 'travel',
    actor: travel.actor,
    destination_id: travel.destination_id,
    travel_turns: travel.travel_turns,
    next_actor: campaign.owner,
  });
  return true;
}

export function handleCreatePlayRest(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/(.+)\/turn\/rest$/);
  if (!match) return false;
  const campaignId = match[1];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  const member = getPlayCampaignMemberByPlayer(campaignId, user.username);
  if (!member) {
    if (user.role === 'dm' || user.username === campaign.owner) {
      sendError(res, 409, 'not your turn');
      return true;
    }
    sendError(res, 403, 'forbidden');
    return true;
  }

  if (user.role !== 'player' || campaign.status !== 'active' || campaign.current_actor !== user.username) {
    sendError(res, 409, 'not your turn');
    return true;
  }

  const b = body as any;
  if (!b || (b.type !== 'short' && b.type !== 'long')) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  const hpMax = member.hp_max ?? 20;
  let hpCurrent = member.hp_current ?? hpMax;
  if (b.type === 'long') {
    hpCurrent = hpMax;
    setPlayCampaignMemberHp(campaignId, user.username, hpCurrent);
  }

  const rest = createPlayRest(campaignId, user.username, b.type, hpCurrent, hpMax);
  setPlayCampaignCurrentActor(campaignId, campaign.owner);
  sendJson(res, 201, {
    sequence: rest.sequence,
    kind: 'rest',
    actor: rest.actor,
    type: rest.type,
    hp_current: rest.hp_current,
    hp_max: rest.hp_max,
    next_actor: campaign.owner,
  });
  return true;
}

export function handleCreateEncounter(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/encounters$/);
  if (!match) return false;
  const campaignId = match[1];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const b = body as any;
  if (!b || !isNonEmptyString(b.id) || !isNonEmptyString(b.name)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  if (encounterExists(campaignId, b.id)) {
    sendError(res, 409, 'encounter already exists');
    return true;
  }

  if (getActiveEncounter(campaignId)) {
    sendError(res, 409, 'campaign already in combat');
    return true;
  }

  const encounter: Encounter = {
    campaign_id: campaignId,
    id: b.id,
    name: b.name,
    status: 'active',
    round: 1,
    turn_index: 0,
    combatants: [],
  };
  createEncounter(encounter);
  sendJson(res, 201, {
    id: encounter.id,
    name: encounter.name,
    status: encounter.status,
    combatants: encounter.combatants,
  });
  return true;
}

export function handleGetPlayCampaignDocument(
  pathname: string,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/(.+)\/document$/);
  if (!match) return false;
  const campaignId = match[1];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  const isOwner = campaign.owner === user.username;
  const isMember = !!getPlayCampaignMemberByPlayer(campaignId, user.username);
  if (!isOwner && !isMember) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const doc = getPlayCampaignDocument(campaignId);
  if (isOwner) {
    sendJson(res, 200, { story: doc?.story ?? '', dm_notes: doc?.dm_notes ?? '' });
  } else {
    sendJson(res, 200, { story: doc?.story ?? '' });
  }
  return true;
}

export function handleUpdatePlayCampaignDocument(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/(.+)\/document$/);
  if (!match) return false;
  const campaignId = match[1];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const b = body as any;
  if (!b || typeof b.story !== 'string' || typeof b.dm_notes !== 'string') {
    sendError(res, 400, 'invalid request');
    return true;
  }

  const doc = upsertPlayCampaignDocument(campaignId, b.story, b.dm_notes);
  sendJson(res, 200, { story: doc.story, dm_notes: doc.dm_notes });
  return true;
}

export function handleCreatePlayScene(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/scenes$/);
  if (!match) return false;
  const campaignId = match[1];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const b = body as any;
  if (!b || !isNonEmptyString(b.id) || !isNonEmptyString(b.name)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  if (getPlayScene(campaignId, b.id)) {
    sendError(res, 409, 'scene already exists');
    return true;
  }

  const scene: PlayScene = { campaign_id: campaignId, id: b.id, name: b.name, status: 'open' };
  createPlayScene(scene);
  sendJson(res, 201, { id: scene.id, name: scene.name, status: 'open' });
  return true;
}

export function handleEnterPlayScene(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/scenes\/([^/]+)\/enter$/);
  if (!match) return false;
  const campaignId = match[1];
  const sceneId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const scene = getPlayScene(campaignId, sceneId);
  if (!scene) {
    sendError(res, 404, 'scene not found');
    return true;
  }

  if (scene.status === 'closed') {
    sendError(res, 409, 'scene closed');
    return true;
  }

  setPlayCampaignCurrentScene(campaignId, sceneId);
  sendJson(res, 200, { current_scene_id: sceneId, name: scene.name });
  return true;
}

export function handleClosePlayScene(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/scenes\/([^/]+)\/close$/);
  if (!match) return false;
  const campaignId = match[1];
  const sceneId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  if (!getPlayScene(campaignId, sceneId)) {
    sendError(res, 404, 'scene not found');
    return true;
  }

  closePlayScene(campaignId, sceneId);
  sendJson(res, 200, { id: sceneId, status: 'closed' });
  return true;
}

export function handleGetCurrentPlayScene(
  pathname: string,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/scenes\/current$/);
  if (!match) return false;
  const campaignId = match[1];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username && !getPlayCampaignMemberByPlayer(campaignId, user.username)) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const scene = getPlayCampaignCurrentScene(campaignId);
  if (!scene) {
    sendError(res, 404, 'no current scene');
    return true;
  }

  sendJson(res, 200, { id: scene.id, name: scene.name, status: 'open' });
  return true;
}

export function handleCreateLocation(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/locations$/);
  if (!match) return false;
  const campaignId = match[1];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const b = body as any;
  if (!b || !isNonEmptyString(b.id) || !isNonEmptyString(b.name)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  if (getLocation(campaignId, b.id)) {
    sendError(res, 409, 'location already exists');
    return true;
  }

  const location: Location = { campaign_id: campaignId, id: b.id, name: b.name };
  createLocation(location);
  createPlayLocationEvent(campaignId, user.username, location.id, location.name);
  if (!campaign.current_location_id) {
    setPlayCampaignCurrentLocation(campaignId, b.id);
  }
  sendJson(res, 201, { id: location.id, name: location.name });
  return true;
}

export function handleCreateConnection(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/locations\/([^/]+)\/connections$/);
  if (!match) return false;
  const campaignId = match[1];
  const fromId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const b = body as any;
  if (!b || !isNonEmptyString(b.to_id) || !isPositiveInteger(b.travel_turns)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  if (!getLocation(campaignId, fromId) || !getLocation(campaignId, b.to_id)) {
    sendError(res, 400, 'missing location');
    return true;
  }

  if (getConnection(campaignId, fromId, b.to_id)) {
    sendError(res, 400, 'connection already exists');
    return true;
  }

  createConnection({ campaign_id: campaignId, from_id: fromId, to_id: b.to_id, travel_turns: b.travel_turns });
  sendJson(res, 201, { from_id: fromId, to_id: b.to_id, travel_turns: b.travel_turns });
  return true;
}

export function handleGetTravel(
  pathname: string,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/locations\/([^/]+)\/travel$/);
  if (!match) return false;
  const campaignId = match[1];
  const locId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username && !getPlayCampaignMemberByPlayer(campaignId, user.username)) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  if (!getLocation(campaignId, locId)) {
    sendError(res, 404, 'location not found');
    return true;
  }

  const connections = getConnectionsFrom(campaignId, locId);
  const destinations = connections.map((c) => {
    const loc = getLocation(campaignId, c.to_id)!;
    return { id: loc.id, name: loc.name, travel_turns: c.travel_turns };
  });
  sendJson(res, 200, { destinations });
  return true;
}

export function handleAddEncounterMonster(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/monsters$/);
  if (!match) return false;
  const campaignId = match[1];
  const encounterId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  if (!getEncounter(campaignId, encounterId)) {
    sendError(res, 404, 'encounter not found');
    return true;
  }

  const b = body as any;
  if (
    !b ||
    !isNonEmptyString(b.monster_id) ||
    !isNonEmptyString(b.name) ||
    !isPositiveInteger(b.hp_max) ||
    !isPositiveInteger(b.initiative)
  ) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  const monster: RosterMonster = {
    monster_id: b.monster_id,
    name: b.name,
    hp_max: b.hp_max,
    hp_current: b.hp_max,
    initiative: b.initiative,
  };

  try {
    addEncounterMonster(campaignId, encounterId, monster);
  } catch (err) {
    if (err instanceof Error && err.message === 'duplicate monster_id') {
      sendError(res, 409, 'monster already exists');
      return true;
    }
    throw err;
  }

  sendJson(res, 201, {
    monster_id: monster.monster_id,
    name: monster.name,
    hp_max: monster.hp_max,
    initiative: monster.initiative,
    hp_current: monster.hp_current,
  });
  return true;
}

export function handleRemoveEncounterMonster(
  pathname: string,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/monsters\/([^/]+)$/);
  if (!match) return false;
  const campaignId = match[1];
  const encounterId = match[2];
  const monsterId = match[3];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  if (!getEncounter(campaignId, encounterId)) {
    sendError(res, 404, 'encounter not found');
    return true;
  }

  if (!removeEncounterMonster(campaignId, encounterId, monsterId)) {
    sendError(res, 404, 'monster not found');
    return true;
  }

  sendJson(res, 200, { removed: monsterId });
  return true;
}

export function handleBindEncounterMember(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/combatants$/);
  if (!match) return false;
  const campaignId = match[1];
  const encounterId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  if (!getEncounter(campaignId, encounterId)) {
    sendError(res, 404, 'encounter not found');
    return true;
  }

  const b = body as any;
  if (!b || !isNonEmptyString(b.member) || !Number.isInteger(b.initiative)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  const member = getPlayCampaignMemberByPlayer(campaignId, b.member);
  if (!member) {
    sendError(res, 400, 'member not found');
    return true;
  }

  try {
    addEncounterMember(campaignId, encounterId, member, b.initiative);
  } catch (err) {
    if (err instanceof Error && err.message === 'duplicate member') {
      sendError(res, 409, 'member already bound');
      return true;
    }
    throw err;
  }

  sendJson(res, 201, {
    member: member.username,
    character_id: member.character_id,
    name: member.name,
    initiative: b.initiative,
  });
  return true;
}

export function handleUnbindEncounterMember(
  pathname: string,
  _body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/combatants\/([^/]+)$/);
  if (!match) return false;
  const campaignId = match[1];
  const encounterId = match[2];
  const memberUsername = match[3];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  if (!getEncounter(campaignId, encounterId)) {
    sendError(res, 404, 'encounter not found');
    return true;
  }

  if (!removeEncounterMember(campaignId, encounterId, memberUsername)) {
    sendError(res, 404, 'member not bound');
    return true;
  }

  sendJson(res, 200, { removed: memberUsername });
  return true;
}

function combatantToActiveJson(combatant: RosterMonster): { name: string; kind: string; initiative: number } {
  return {
    name: combatant.name,
    kind: combatant.monster_id ? 'monster' : 'player',
    initiative: combatant.initiative,
  };
}

function isCurrentEncounterCombatant(encounter: Encounter, username: string): boolean {
  const active = getEncounterActiveCombatant(encounter);
  if (!active) return false;
  return active.member === username;
}

export function handleGetEncounterTurn(
  pathname: string,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/turn$/);
  if (!match) return false;
  const campaignId = match[1];
  const encounterId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username && !getPlayCampaignMemberByPlayer(campaignId, user.username)) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const encounter = getEncounter(campaignId, encounterId);
  if (!encounter) {
    sendError(res, 404, 'encounter not found');
    return true;
  }

  const active = getEncounterActiveCombatant(encounter);
  sendJson(res, 200, {
    round: encounter.round,
    turn_index: encounter.turn_index,
    active: active ? combatantToActiveJson(active) : null,
  });
  return true;
}

export function handleAdvanceEncounterTurn(
  pathname: string,
  _body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/turn\/advance$/);
  if (!match) return false;
  const campaignId = match[1];
  const encounterId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  const isOwner = campaign.owner === user.username;
  const isMember = !!getPlayCampaignMemberByPlayer(campaignId, user.username);
  if (!isOwner && !isMember) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const encounter = getEncounter(campaignId, encounterId);
  if (!encounter) {
    sendError(res, 404, 'encounter not found');
    return true;
  }

  if (!isOwner && !isCurrentEncounterCombatant(encounter, user.username)) {
    sendError(res, 409, 'not your turn');
    return true;
  }

  if (encounter.combatants.length === 0) {
    sendError(res, 409, 'no active combatant');
    return true;
  }

  const next = advanceEncounterTurn(campaignId, encounterId);
  const active = getEncounterActiveCombatant(next);
  if (active) {
    const activeKey = active.monster_id ?? active.member ?? active.name;
    decrementEncounterConditions(encounterId, activeKey);
  }
  sendJson(res, 200, {
    round: next.round,
    turn_index: next.turn_index,
    active: active ? combatantToActiveJson(active) : null,
  });
  return true;
}

export function handleCreateEncounterAction(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/actions$/);
  if (!match) return false;
  const campaignId = match[1];
  const encounterId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  const isOwner = campaign.owner === user.username;
  const isMember = !!getPlayCampaignMemberByPlayer(campaignId, user.username);
  if (!isOwner && !isMember) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const encounter = getEncounter(campaignId, encounterId);
  if (!encounter) {
    sendError(res, 404, 'encounter not found');
    return true;
  }

  const active = getEncounterActiveCombatant(encounter);
  if (!active || active.member !== user.username) {
    sendError(res, 409, 'not your turn');
    return true;
  }

  const b = body as any;
  if (!b || !isCombatActionType(b.type) || !isNonEmptyString(b.target) || !isNonEmptyString(b.text)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  const action = createCombatAction(campaignId, encounterId, user.username, b.type, b.target, b.text);
  sendJson(res, 201, {
    sequence: action.sequence,
    kind: 'combat_action',
    actor: action.actor,
    type: action.type,
    target: action.target,
    text: action.text,
  });
  return true;
}

export function handleDamageEncounter(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/damage$/);
  if (!match) return false;
  const campaignId = match[1];
  const encounterId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const encounter = getEncounter(campaignId, encounterId);
  if (!encounter) {
    sendError(res, 404, 'encounter not found');
    return true;
  }

  const b = body as any;
  if (!b || !isNonEmptyString(b.target) || !isPositiveInteger(b.amount)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  const monster = encounter.combatants.find((c) => c.monster_id === b.target);
  if (monster) {
    const hpBefore = monster.hp_current ?? 0;
    const hpAfter = Math.max(0, hpBefore - b.amount);
    updateEncounterMonsterHp(campaignId, encounterId, b.target, hpAfter);
    sendJson(res, 200, { target: b.target, hp_before: hpBefore, hp_after: hpAfter, damage: b.amount });
    return true;
  }

  const memberCombatant = encounter.combatants.find((c) => c.member === b.target);
  if (memberCombatant) {
    const member = getPlayCampaignMemberByPlayer(campaignId, b.target);
    if (!member) {
      sendError(res, 400, 'invalid target');
      return true;
    }
    const hpMax = member.hp_max ?? 20;
    const hpBefore = member.hp_current ?? hpMax;
    const hpAfter = Math.max(0, hpBefore - b.amount);
    setPlayCampaignMemberHp(campaignId, b.target, hpAfter);
    sendJson(res, 200, { target: b.target, hp_before: hpBefore, hp_after: hpAfter, damage: b.amount });
    return true;
  }

  sendError(res, 400, 'invalid target');
  return true;
}

export function handleHealEncounter(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/heal$/);
  if (!match) return false;
  const campaignId = match[1];
  const encounterId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const encounter = getEncounter(campaignId, encounterId);
  if (!encounter) {
    sendError(res, 404, 'encounter not found');
    return true;
  }

  const b = body as any;
  if (!b || !isNonEmptyString(b.target) || !isPositiveInteger(b.amount)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  const monster = encounter.combatants.find((c) => c.monster_id === b.target);
  if (monster) {
    const hpMax = monster.hp_max ?? 0;
    const hpBefore = monster.hp_current ?? 0;
    const hpAfter = Math.min(hpMax, hpBefore + b.amount);
    updateEncounterMonsterHp(campaignId, encounterId, b.target, hpAfter);
    sendJson(res, 200, { target: b.target, hp_before: hpBefore, hp_after: hpAfter, healing: b.amount });
    return true;
  }

  const memberCombatant = encounter.combatants.find((c) => c.member === b.target);
  if (memberCombatant) {
    const member = getPlayCampaignMemberByPlayer(campaignId, b.target);
    if (!member) {
      sendError(res, 400, 'invalid target');
      return true;
    }
    const hpMax = member.hp_max ?? 20;
    const hpBefore = member.hp_current ?? hpMax;
    const hpAfter = Math.min(hpMax, hpBefore + b.amount);
    setPlayCampaignMemberHp(campaignId, b.target, hpAfter);
    sendJson(res, 200, { target: b.target, hp_before: hpBefore, hp_after: hpAfter, healing: b.amount });
    return true;
  }

  sendError(res, 400, 'invalid target');
  return true;
}

export function handleDamageCharacter(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/damage$/);
  if (!match) return false;
  const campaignId = match[1];
  const characterId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const member = getPlayCampaignMemberByCharacterId(characterId);
  if (!member || member.campaign_id !== campaignId) {
    sendError(res, 404, 'character not found');
    return true;
  }

  const b = body as any;
  if (!b || !isPositiveInteger(b.amount)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  const hpMax = member.hp_max ?? 20;
  const hpBefore = member.hp_current ?? hpMax;
  const hpAfter = Math.max(0, hpBefore - b.amount);
  setPlayCampaignMemberHp(campaignId, member.username, hpAfter);
  const updated = getPlayCampaignMemberByCharacterId(characterId)!;
  sendJson(res, 200, {
    target: updated.character_id,
    character_id: updated.character_id,
    hp_before: hpBefore,
    hp_after: hpAfter,
    damage: b.amount,
    status: updated.status,
  });
  return true;
}

export function handleDeathSave(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/death-saves$/);
  if (!match) return false;
  const campaignId = match[1];
  const characterId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  const member = getPlayCampaignMemberByCharacterId(characterId);
  if (!member || member.campaign_id !== campaignId) {
    sendError(res, 404, 'character not found');
    return true;
  }

  if (member.username !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const b = body as any;
  if (!b || !isDeathSaveOutcome(b.outcome)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  if (member.status !== 'unconscious') {
    sendError(res, 409, 'not unconscious');
    return true;
  }

  const updated = recordDeathSave(characterId, b.outcome);
  if (!updated) {
    sendError(res, 404, 'character not found');
    return true;
  }

  sendJson(res, 201, {
    character_id: updated.character_id,
    successes: updated.death_successes,
    failures: updated.death_failures,
    status: updated.status,
  });
  return true;
}

export function handleGetCharacterStatus(
  pathname: string,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/characters\/([^/]+)\/status$/);
  if (!match) return false;
  const campaignId = match[1];
  const characterId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username && !getPlayCampaignMemberByPlayer(campaignId, user.username)) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const member = getPlayCampaignMemberByCharacterId(characterId);
  if (!member || member.campaign_id !== campaignId) {
    sendError(res, 404, 'character not found');
    return true;
  }

  sendJson(res, 200, {
    character_id: member.character_id,
    hp_current: member.hp_current,
    hp_max: member.hp_max,
    status: member.status,
  });
  return true;
}

function getCombatantKey(combatant: RosterMonster): string {
  return combatant.monster_id ?? combatant.member ?? combatant.name;
}

function combatantToOrderJson(combatant: RosterMonster): { name: string; kind: string; initiative: number } {
  return combatantToActiveJson(combatant);
}

function findEncounterCombatant(encounter: Encounter, target: string): RosterMonster | undefined {
  return encounter.combatants.find(
    (c) => c.monster_id === target || c.member === target || c.name === target,
  );
}

export function handleAddEncounterCondition(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/conditions$/);
  if (!match) return false;
  const campaignId = match[1];
  const encounterId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const encounter = getEncounter(campaignId, encounterId);
  if (!encounter) {
    sendError(res, 404, 'encounter not found');
    return true;
  }

  const b = body as any;
  if (!b || !isNonEmptyString(b.target) || !isNonEmptyString(b.condition) || !isPositiveInteger(b.duration_rounds)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  const combatant = findEncounterCombatant(encounter, b.target);
  if (!combatant) {
    sendError(res, 400, 'invalid target');
    return true;
  }

  const targetKey = getCombatantKey(combatant);
  addEncounterCondition(campaignId, encounterId, targetKey, b.condition, b.duration_rounds);
  const conditions = getEncounterConditionsForTarget(encounterId, targetKey);
  sendJson(res, 201, { target: targetKey, conditions });
  return true;
}

export function handleGetEncounterStatus(
  pathname: string,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/status$/);
  if (!match) return false;
  const campaignId = match[1];
  const encounterId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (campaign.owner !== user.username && !getPlayCampaignMemberByPlayer(campaignId, user.username)) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const encounter = getEncounter(campaignId, encounterId);
  if (!encounter) {
    sendError(res, 404, 'encounter not found');
    return true;
  }

  const order = getEncounterTurnOrder(encounter.combatants).map(combatantToOrderJson);
  const active = order[encounter.turn_index] ?? null;

  const conditions: Record<string, { condition: string; remaining_rounds: number }[]> = {};
  for (const combatant of encounter.combatants) {
    conditions[getCombatantKey(combatant)] = [];
  }
  const stored = getEncounterConditions(encounterId);
  for (const target of Object.keys(stored)) {
    conditions[target] = stored[target];
  }

  sendJson(res, 200, {
    round: encounter.round,
    turn_index: encounter.turn_index,
    active,
    order,
    conditions,
  });
  return true;
}

export function handleDelayEncounterTurn(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/turn\/delay$/);
  if (!match) return false;
  const campaignId = match[1];
  const encounterId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  const isOwner = campaign.owner === user.username;
  const isMember = !!getPlayCampaignMemberByPlayer(campaignId, user.username);
  if (!isOwner && !isMember) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const encounter = getEncounter(campaignId, encounterId);
  if (!encounter) {
    sendError(res, 404, 'encounter not found');
    return true;
  }

  const order = getEncounterTurnOrder(encounter.combatants);
  const currentCombatant = getEncounterActiveCombatant(encounter);
  if (!currentCombatant) {
    sendError(res, 409, 'no active combatant');
    return true;
  }

  const isCurrentCombatant = currentCombatant.member === user.username;
  if (!isOwner && !isCurrentCombatant) {
    sendError(res, 409, 'not your turn');
    return true;
  }

  const b = body as any;
  const targetIndex = typeof b?.new_index === 'number' && Number.isInteger(b.new_index)
    ? b.new_index
    : typeof b?.index === 'number' && Number.isInteger(b.index)
      ? b.index
      : undefined;
  if (targetIndex === undefined) {
    sendError(res, 400, 'invalid index');
    return true;
  }

  const currentIndex = order.findIndex((c) => getCombatantKey(c) === getCombatantKey(currentCombatant));
  if (targetIndex <= currentIndex || targetIndex >= order.length) {
    sendError(res, 400, 'invalid index');
    return true;
  }

  const orderWithoutCurrent = order.filter((c) => getCombatantKey(c) !== getCombatantKey(currentCombatant));
  const newOrder = [
    ...orderWithoutCurrent.slice(0, targetIndex),
    currentCombatant,
    ...orderWithoutCurrent.slice(targetIndex),
  ];
  const updatedCombatants = newOrder.map((c, index) => ({ ...c, sequence: index }));
  setEncounterCombatants(campaignId, encounterId, updatedCombatants, targetIndex);

  const newEncounter = getEncounter(campaignId, encounterId)!;
  const responseOrder = getEncounterTurnOrder(newEncounter.combatants).map(combatantToOrderJson);
  sendJson(res, 200, { order: responseOrder });
  return true;
}

export function handleReadyEncounterTurn(
  pathname: string,
  body: unknown,
  req: IncomingMessage,
  res: ServerResponse,
): boolean {
  const match = pathname.match(/^\/v1\/play\/campaigns\/([^/]+)\/encounters\/([^/]+)\/turn\/ready$/);
  if (!match) return false;
  const campaignId = match[1];
  const encounterId = match[2];

  const user = getAuthUser(req);
  if (!user) {
    sendError(res, 401, 'unauthorized');
    return true;
  }

  const campaign = getPlayCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }

  if (!getPlayCampaignMemberByPlayer(campaignId, user.username)) {
    sendError(res, 403, 'forbidden');
    return true;
  }

  const encounter = getEncounter(campaignId, encounterId);
  if (!encounter) {
    sendError(res, 404, 'encounter not found');
    return true;
  }

  const order = getEncounterTurnOrder(encounter.combatants);
  const currentCombatant = getEncounterActiveCombatant(encounter);
  if (!currentCombatant || currentCombatant.member !== user.username) {
    sendError(res, 409, 'not your turn');
    return true;
  }

  const b = body as any;
  if (!b || !isNonEmptyString(b.trigger)) {
    sendError(res, 400, 'invalid request');
    return true;
  }

  sendJson(res, 201, { actor: user.username, trigger: b.trigger });
  return true;
}
