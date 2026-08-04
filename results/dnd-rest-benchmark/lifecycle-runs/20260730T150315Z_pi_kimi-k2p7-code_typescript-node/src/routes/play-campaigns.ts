import { IncomingMessage, ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import {
  addInventoryItem,
  campaignHasActiveEncounter,
  countEvents,
  countNudges,
  countPlayMembers,
  createAction,
  createCombatAction,
  createEncounterReward,
  createNarration,
  createNudge,
  createPlayCampaign,
  createPlayEncounter,
  createPlayMembership,
  createReadiedAction,
  countReadiedActions,
  createResolution,
  createRest,
  createTravel,
  encounterRewardExists,
  getActions,
  getEncounterReward,
  getFirstLocation,
  getLocationConnection,
  getNarrations,
  getPlayCampaign,
  getPlayEncounter,
  getPlayMembers,
  getPlayMembershipByCampaignAndUser,
  getPlayMembershipByCharacterId,
  getRests,
  getTravels,
  playCampaignExists,
  playEncounterExists,
  setPlayCampaignPreCombatActor,
  updatePlayCampaignCurrentLocation,
  updatePlayCampaignStatus,
  updatePlayEncounter,
  updatePlayEncounterCombatants,
  updatePlayEncounterStatus,
  updatePlayMembershipBuild,
  updatePlayMembershipDeathSaves,
  updatePlayMembershipHp,
  updatePlayMembershipLevel,
  updatePlayMembershipOwner,
} from '../repository.js';
import { requireActor, requireDM, requirePlayer } from '../play-auth.js';
import { abilityModifier, averageHitDie, classHitDie, proficiencyBonus } from '../rules.js';
import { isNonEmptyString, isNonNegativeInteger, isPositiveInteger, isValidAbilityScores, isValidBackground, isValidClass, isValidDeathSaveOutcome, isValidLootArray, isValidLevel, isValidRace } from '../validators.js';
import type { ActionEvent, CombatAction, LootItem, Narration, Nudge, PlayCampaign, PlayEncounter, PlayEncounterCombatant, PlayMembership, ReadiedAction, Resolution, RestEvent, TravelEvent } from '../types.js';

function getPlayCampaignOr404(res: ServerResponse, id: string): PlayCampaign | null {
  const campaign = getPlayCampaign(id);
  if (!campaign) {
    sendJSON(res, 404, { error: 'not found' });
    return null;
  }
  return campaign;
}

function toRecentEvents(narrations: Narration[]) {
  return narrations.map((n) => ({
    sequence: n.sequence,
    kind: 'narration' as const,
    actor: n.actor,
    text: n.text,
  }));
}

/**
 * Build the deterministic turn queue for a play campaign: each member is
 * followed by the DM, so the round-robin alternates between players and the DM.
 */
function buildTurnQueue(campaignId: string): string[] {
  const members = getPlayMembers(campaignId);
  const queue: string[] = [];
  for (const member of members) {
    queue.push(member.username);
    queue.push('dm');
  }
  return queue;
}

function sortEncounterCombatants(combatants: PlayEncounterCombatant[]): PlayEncounterCombatant[] {
  return [...combatants].sort((a, b) => {
    const ai = a.initiative ?? 0;
    const bi = b.initiative ?? 0;
    if (bi !== ai) return bi - ai;
    return a.name.localeCompare(b.name);
  });
}

function activeCombatantActor(encounter: PlayEncounter, campaign: PlayCampaign): string | null {
  const active = encounter.combatants[encounter.turn_index];
  if (!active) return null;
  if (active.type === 'player') {
    const membership = getPlayMembershipByCharacterId(active.id);
    return membership ? membership.username : null;
  }
  return campaign.owner;
}

function activeCombatantResponse(encounter: PlayEncounter) {
  const active = encounter.combatants[encounter.turn_index];
  return {
    round: encounter.round,
    turn_index: encounter.turn_index,
    active: active ? { name: active.name, kind: active.type, initiative: active.initiative ?? 0 } : null,
  };
}

export function handleCreatePlayCampaign(
  res: ServerResponse,
  _params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireDM(req, res);
  if (!actor) return;

  const { id, name, max_players } = body as Record<string, unknown>;
  if (!isNonEmptyString(id) || !isNonEmptyString(name) || !isPositiveInteger(max_players)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  if (playCampaignExists(id)) {
    sendJSON(res, 409, { error: 'campaign already exists' });
    return;
  }

  const campaign: PlayCampaign = {
    id,
    name,
    owner: actor.username,
    status: 'lobby',
    max_players,
  };
  createPlayCampaign(campaign);
  sendJSON(res, 201, campaign);
}

export function handleJoinPlayCampaign(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requirePlayer(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;
  if (campaign.status !== 'lobby') {
    sendJSON(res, 409, { error: 'campaign not open' });
    return;
  }

  const { character_id, name, class: className } = body as Record<string, unknown>;
  if (!isNonEmptyString(character_id) || !isNonEmptyString(name) || !isNonEmptyString(className)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  if (getPlayMembershipByCampaignAndUser(params.id, actor.username)) {
    sendJSON(res, 409, { error: 'already a member' });
    return;
  }
  if (getPlayMembershipByCharacterId(character_id)) {
    sendJSON(res, 409, { error: 'character already exists' });
    return;
  }
  if (countPlayMembers(params.id) >= campaign.max_players) {
    sendJSON(res, 409, { error: 'party is full' });
    return;
  }

  const membership: PlayMembership = {
    campaign_id: params.id,
    username: actor.username,
    character_id,
    name,
    class: className,
    hp_current: 20,
    hp_max: 20,
    level: 1,
    con_modifier: 0,
    status: 'conscious',
    death_save_successes: 0,
    death_save_failures: 0,
    owner: actor.username,
  };
  createPlayMembership(membership);
  sendJSON(res, 201, {
    username: actor.username,
    character_id,
    name,
    class: className,
  });
}

export function handleStartPlayCampaign(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireDM(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  if (campaign.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }
  if (campaign.status !== 'lobby') {
    sendJSON(res, 409, { error: 'campaign cannot be started' });
    return;
  }
  if (countPlayMembers(params.id) < 2) {
    sendJSON(res, 409, { error: 'party is under-populated' });
    return;
  }

  const members = getPlayMembers(params.id);
  const firstActor = members[0]!;
  if (!campaign.current_location_id) {
    const firstLocation = getFirstLocation(params.id);
    if (firstLocation) {
      updatePlayCampaignCurrentLocation(params.id, firstLocation.id);
    }
  }
  updatePlayCampaignStatus({
    id: params.id,
    status: 'active',
    current_actor: firstActor.username,
    turn_number: 1,
    phase: 'player',
  });

  sendJSON(res, 200, {
    id: campaign.id,
    status: 'active',
    current_actor: firstActor.username,
    turn_number: 1,
  });
}

export function handleGetPlayCampaignTurn(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const isOwner = campaign.owner === actor.username;
  const isMember = getPlayMembershipByCampaignAndUser(params.id, actor.username) !== null;
  if (!isOwner && !isMember) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const defaultPhase = campaign.current_actor === campaign.owner ? 'dm' : 'player';
  sendJSON(res, 200, {
    campaign_id: campaign.id,
    current_actor: campaign.current_actor ?? null,
    phase: campaign.phase ?? defaultPhase,
    turn_number: campaign.turn_number ?? 1,
    overdue: false,
    deadline: (campaign.turn_number ?? 1) + 1,
    logical_deadline: (campaign.turn_number ?? 1) + 1,
    queue: buildTurnQueue(params.id),
  });
}

export function handleGetGMStatus(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  if (campaign.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const members = getPlayMembers(params.id);
  const party = members.map((m) => ({
    username: m.username,
    character_id: m.character_id,
    name: m.name,
    class: m.class,
  }));

  sendJSON(res, 200, {
    needs_attention: campaign.current_actor === campaign.owner,
    current_actor: campaign.current_actor ?? null,
    party,
    recent_events: toRecentEvents(getNarrations(params.id)),
  });
}

export function handleGetMyTurn(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const actor = requirePlayer(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const membership = getPlayMembershipByCampaignAndUser(params.id, actor.username);
  if (!membership) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  sendJSON(res, 200, {
    is_my_turn: campaign.current_actor === actor.username,
    current_actor: campaign.current_actor ?? null,
    character: {
      id: membership.character_id,
      name: membership.name,
    },
    recent_events: toRecentEvents(getNarrations(params.id)),
  });
}

export function handleAddNarration(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireDM(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  if (campaign.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const { text } = body as Record<string, unknown>;
  if (!isNonEmptyString(text)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const sequence = countEvents(params.id) + 1;
  const narration: Narration = {
    id: `narration-${params.id}-${sequence}`,
    campaign_id: params.id,
    sequence,
    actor: 'dm',
    text,
  };
  createNarration(narration);

  sendJSON(res, 201, {
    sequence: narration.sequence,
    kind: 'narration',
    actor: 'dm',
    text: narration.text,
  });
}

export function handleResolution(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  // Only the DM may resolve, and only during the DM's turn.
  if (campaign.current_actor !== campaign.owner || actor.username !== campaign.owner) {
    sendJSON(res, 409, { error: 'not your turn' });
    return;
  }

  const { text } = body as Record<string, unknown>;
  if (!isNonEmptyString(text)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const members = getPlayMembers(params.id);
  const queue = buildTurnQueue(params.id);
  const actions = getActions(params.id);
  const travels = getTravels(params.id);
  const rests = getRests(params.id);
  // The player who submitted the last action, travel, or rest is the anchor for the next turn.
  const lastAction = actions[actions.length - 1] ?? null;
  const lastTravel = travels[travels.length - 1] ?? null;
  const lastRest = rests[rests.length - 1] ?? null;
  const candidates = [lastAction, lastTravel, lastRest].filter((e) => e !== null);
  const lastEvent = candidates.length > 0 ? candidates.sort((a, b) => b.sequence - a.sequence)[0] : null;
  const lastActor = lastEvent ? lastEvent.actor : members[0]!.username;
  const lastActorIndex = queue.indexOf(lastActor);
  // Advance two steps to skip the DM slot and land on the next player.
  const nextIndex = (lastActorIndex + 2) % queue.length;
  const nextActor = queue[nextIndex]!;

  const turnNumber = (campaign.turn_number ?? 1) + 1;
  const sequence = countEvents(params.id) + 1;
  const resolution: Resolution = {
    id: `resolution-${params.id}-${sequence}`,
    campaign_id: params.id,
    sequence,
    actor: 'dm',
    text,
  };
  createResolution(resolution);

  updatePlayCampaignStatus({
    id: params.id,
    status: campaign.status,
    current_actor: nextActor,
    turn_number: turnNumber,
    phase: 'player',
  });

  sendJSON(res, 201, {
    sequence: resolution.sequence,
    kind: 'resolution',
    actor: 'dm',
    text: resolution.text,
    next_actor: nextActor,
    turn_number: turnNumber,
  });
}

export function handleTurnNudge(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  if (campaign.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const { message } = body as Record<string, unknown>;
  if (!isNonEmptyString(message)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const sequence = countNudges(params.id) + 1;
  const nudge: Nudge = {
    id: `nudge-${params.id}-${sequence}`,
    campaign_id: params.id,
    turn_number: campaign.turn_number ?? 1,
    actor: actor.username,
    target: campaign.current_actor ?? '',
    message,
    sequence,
  };
  createNudge(nudge);

  sendJSON(res, 201, {
    actor: nudge.actor,
    target: nudge.target,
    message: nudge.message,
    nudge_count: sequence,
  });
}

export function handleSubmitAction(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  // The DM does not submit actions through this endpoint.
  if (actor.username === campaign.owner) {
    sendJSON(res, 409, { error: 'not your turn' });
    return;
  }

  const membership = getPlayMembershipByCampaignAndUser(params.id, actor.username);
  if (!membership) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  if (campaign.current_actor !== actor.username) {
    sendJSON(res, 409, { error: 'not your turn' });
    return;
  }

  const { type, text } = body as Record<string, unknown>;
  if (!isNonEmptyString(type) || !isNonEmptyString(text)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const sequence = countEvents(params.id) + 1;
  const action: ActionEvent = {
    id: `action-${params.id}-${sequence}`,
    campaign_id: params.id,
    sequence,
    actor: actor.username,
    type,
    text,
  };
  createAction(action);

  updatePlayCampaignStatus({
    id: params.id,
    status: campaign.status,
    current_actor: campaign.owner,
    turn_number: campaign.turn_number,
    phase: 'dm',
  });

  sendJSON(res, 201, {
    sequence: action.sequence,
    kind: 'action',
    actor: action.actor,
    type: action.type,
    text: action.text,
    next_actor: 'dm',
  });
}

export function handleTravelTurn(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  // Travel is a player turn action; the DM cannot consume it.
  if (actor.username === campaign.owner) {
    sendJSON(res, 409, { error: 'not your turn' });
    return;
  }

  const membership = getPlayMembershipByCampaignAndUser(params.id, actor.username);
  if (!membership) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  if (campaign.current_actor !== actor.username) {
    sendJSON(res, 409, { error: 'not your turn' });
    return;
  }

  const { destination_id } = body as Record<string, unknown>;
  if (!isNonEmptyString(destination_id)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const currentLocationId = campaign.current_location_id;
  if (!currentLocationId) {
    sendJSON(res, 409, { error: 'invalid destination' });
    return;
  }

  const connection = getLocationConnection(currentLocationId, destination_id, params.id);
  if (!connection) {
    sendJSON(res, 409, { error: 'invalid destination' });
    return;
  }

  const sequence = countEvents(params.id) + 1;
  const travel: TravelEvent = {
    id: `travel-${params.id}-${sequence}`,
    campaign_id: params.id,
    sequence,
    actor: actor.username,
    destination_id,
    travel_turns: connection.travel_turns,
  };
  createTravel(travel);

  updatePlayCampaignStatus({
    id: params.id,
    status: campaign.status,
    current_actor: campaign.owner,
    turn_number: campaign.turn_number,
    phase: 'dm',
  });
  updatePlayCampaignCurrentLocation(params.id, destination_id);

  sendJSON(res, 201, {
    sequence: travel.sequence,
    kind: 'travel',
    actor: travel.actor,
    destination_id: travel.destination_id,
    travel_turns: travel.travel_turns,
    next_actor: 'dm',
  });
}

export function handleAddMonsterToEncounter(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireDM(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  if (campaign.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const encounter = getPlayEncounter(params.enc_id);
  if (!encounter || encounter.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { monster_id, name, hp_max, initiative } = body as Record<string, unknown>;
  if (
    !isNonEmptyString(monster_id) ||
    !isNonEmptyString(name) ||
    !isPositiveInteger(hp_max) ||
    typeof initiative !== 'number' ||
    !Number.isInteger(initiative)
  ) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  if (encounter.combatants.some((c) => c.id === monster_id)) {
    sendJSON(res, 409, { error: 'monster already exists' });
    return;
  }

  const monster: PlayEncounterCombatant = {
    id: monster_id,
    name,
    type: 'monster',
    initiative,
    hp_current: hp_max,
    hp_max,
  };
  const combatants = [...encounter.combatants, monster];
  updatePlayEncounterCombatants(encounter.id, combatants);

  sendJSON(res, 201, {
    monster_id,
    name,
    hp_max,
    initiative,
    hp_current: hp_max,
  });
}

export function handleRemoveMonsterFromEncounter(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireDM(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  if (campaign.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const encounter = getPlayEncounter(params.enc_id);
  if (!encounter || encounter.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const index = encounter.combatants.findIndex((c) => c.id === params.monster_id);
  if (index === -1) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const combatants = encounter.combatants.slice(0, index).concat(encounter.combatants.slice(index + 1));
  updatePlayEncounterCombatants(encounter.id, combatants);

  sendJSON(res, 200, { removed: params.monster_id });
}

export function handleCreatePlayEncounter(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireDM(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  if (campaign.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const { id, name } = body as Record<string, unknown>;
  if (!isNonEmptyString(id) || !isNonEmptyString(name)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  if (playEncounterExists(id)) {
    sendJSON(res, 409, { error: 'encounter already exists' });
    return;
  }

  if (campaignHasActiveEncounter(params.id)) {
    sendJSON(res, 409, { error: 'campaign already in combat' });
    return;
  }

  const encounter: PlayEncounter = {
    id,
    campaign_id: params.id,
    name,
    status: 'active',
    round: 1,
    turn_index: 0,
    combatants: [],
    conditions: {},
  };
  createPlayEncounter(encounter);

  // Snapshot the exploration actor so we can restore the queue after combat.
  setPlayCampaignPreCombatActor(params.id, campaign.current_actor ?? null);

  sendJSON(res, 201, {
    id: encounter.id,
    name: encounter.name,
    status: encounter.status,
    combatants: encounter.combatants,
  });
}

export function handleRestTurn(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  // Rest is a player turn action; the DM cannot consume it.
  if (actor.username === campaign.owner) {
    sendJSON(res, 409, { error: 'not your turn' });
    return;
  }

  const membership = getPlayMembershipByCampaignAndUser(params.id, actor.username);
  if (!membership) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  if (campaign.current_actor !== actor.username) {
    sendJSON(res, 409, { error: 'not your turn' });
    return;
  }

  const { type } = body as Record<string, unknown>;
  if (type !== 'short' && type !== 'long') {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  let hpCurrent = membership.hp_current ?? 20;
  const hpMax = membership.hp_max ?? 20;
  if (type === 'long') {
    hpCurrent = hpMax;
    updatePlayMembershipHp(params.id, actor.username, hpCurrent);
  }

  const sequence = countEvents(params.id) + 1;
  const rest: RestEvent = {
    id: `rest-${params.id}-${sequence}`,
    campaign_id: params.id,
    sequence,
    actor: actor.username,
    type,
    hp_current: hpCurrent,
    hp_max: hpMax,
  };
  createRest(rest);

  updatePlayCampaignStatus({
    id: params.id,
    status: campaign.status,
    current_actor: campaign.owner,
    turn_number: campaign.turn_number,
    phase: 'dm',
  });

  sendJSON(res, 201, {
    sequence: rest.sequence,
    kind: 'rest',
    actor: rest.actor,
    type: rest.type,
    hp_current: rest.hp_current,
    hp_max: rest.hp_max,
    next_actor: 'dm',
  });
}

export function handleBindMemberToEncounter(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireDM(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;
  if (campaign.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const encounter = getPlayEncounter(params.enc_id);
  if (!encounter || encounter.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { member, initiative } = body as Record<string, unknown>;
  if (!isNonEmptyString(member) || typeof initiative !== 'number' || !Number.isInteger(initiative)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const membership = getPlayMembershipByCampaignAndUser(params.id, member);
  if (!membership) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  if (encounter.combatants.some((c) => c.type === 'player' && c.id === membership.character_id)) {
    sendJSON(res, 409, { error: 'member already bound' });
    return;
  }

  const combatant: PlayEncounterCombatant = {
    id: membership.character_id,
    name: membership.name,
    type: 'player',
    initiative,
    hp_current: membership.hp_current,
    hp_max: membership.hp_max,
  };
  updatePlayEncounterCombatants(encounter.id, [...encounter.combatants, combatant]);

  sendJSON(res, 201, {
    member,
    character_id: membership.character_id,
    name: membership.name,
    initiative,
  });
}

export function handleUnbindMemberFromEncounter(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireDM(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;
  if (campaign.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const encounter = getPlayEncounter(params.enc_id);
  if (!encounter || encounter.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const membership = getPlayMembershipByCampaignAndUser(params.id, params.member);
  if (!membership) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const index = encounter.combatants.findIndex((c) => c.type === 'player' && c.id === membership.character_id);
  if (index === -1) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const combatants = encounter.combatants.slice(0, index).concat(encounter.combatants.slice(index + 1));
  updatePlayEncounterCombatants(encounter.id, combatants);

  sendJSON(res, 200, { removed: params.member });
}

export function handleGetEncounterTurn(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const isMember = campaign.owner === actor.username || getPlayMembershipByCampaignAndUser(params.id, actor.username) !== null;
  if (!isMember) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const encounter = getPlayEncounter(params.enc_id);
  if (!encounter || encounter.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  sendJSON(res, 200, activeCombatantResponse(encounter));
}

export function handleGetEncounterStatus(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const isMember = campaign.owner === actor.username || getPlayMembershipByCampaignAndUser(params.id, actor.username) !== null;
  if (!isMember) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const encounter = getPlayEncounter(params.enc_id);
  if (!encounter || encounter.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const active = encounter.combatants[encounter.turn_index];

  sendJSON(res, 200, {
    id: encounter.id,
    name: encounter.name,
    status: encounter.status,
    round: encounter.round,
    turn_index: encounter.turn_index,
    active: active ? { name: active.name, kind: active.type, initiative: active.initiative ?? 0 } : null,
    order: encounter.combatants.map((c) => ({ name: c.name, kind: c.type, initiative: c.initiative ?? 0 })),
    conditions: encounter.conditions,
  });
}

export function handleAddEncounterCondition(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireDM(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;
  if (campaign.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const encounter = getPlayEncounter(params.enc_id);
  if (!encounter || encounter.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { target, condition, duration_rounds } = body as Record<string, unknown>;
  if (!isNonEmptyString(target) || !isNonEmptyString(condition) || !isPositiveInteger(duration_rounds)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const combatantExists = encounter.combatants.some((c) => c.id === target);
  if (!combatantExists) {
    sendJSON(res, 400, { error: 'invalid target' });
    return;
  }

  if (!encounter.conditions[target]) {
    encounter.conditions[target] = [];
  }
  encounter.conditions[target].push({ condition, remaining_rounds: duration_rounds });
  updatePlayEncounter(encounter);

  sendJSON(res, 201, {
    target,
    conditions: encounter.conditions[target],
  });
}

export function handleAdvanceEncounterTurn(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const encounter = getPlayEncounter(params.enc_id);
  if (!encounter || encounter.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const currentActor = activeCombatantActor(encounter, campaign);
  const isOwner = campaign.owner === actor.username;
  const isCurrent = currentActor === actor.username;
  if (!isOwner && !isCurrent) {
    sendJSON(res, 409, { error: 'not your turn' });
    return;
  }

  if (encounter.combatants.length === 0) {
    sendJSON(res, 200, activeCombatantResponse(encounter));
    return;
  }

  let turnIndex = encounter.turn_index + 1;
  let round = encounter.round;
  if (turnIndex >= encounter.combatants.length) {
    turnIndex = 0;
    round += 1;
  }

  const activeId = encounter.combatants[turnIndex]!.id;
  const updatedConditions = { ...encounter.conditions };
  const activeConditions = updatedConditions[activeId];
  if (activeConditions) {
    const remaining = activeConditions
      .map((cond) => ({ condition: cond.condition, remaining_rounds: cond.remaining_rounds - 1 }))
      .filter((cond) => cond.remaining_rounds > 0);
    if (remaining.length > 0) {
      updatedConditions[activeId] = remaining;
    } else {
      delete updatedConditions[activeId];
    }
  }

  const updated: PlayEncounter = { ...encounter, round, turn_index: turnIndex, combatants: encounter.combatants, conditions: updatedConditions };
  updatePlayEncounter(updated);
  sendJSON(res, 200, activeCombatantResponse(updated));
}

export function handleDelayEncounterTurn(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const encounter = getPlayEncounter(params.enc_id);
  if (!encounter || encounter.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const currentActor = activeCombatantActor(encounter, campaign);
  const isOwner = campaign.owner === actor.username;
  const isCurrent = currentActor === actor.username;
  if (!isOwner && !isCurrent) {
    sendJSON(res, 409, { error: 'not your turn' });
    return;
  }

  const bodyRecord = body as Record<string, unknown>;
  const rawIndex = bodyRecord.new_index ?? bodyRecord.index;
  if (typeof rawIndex !== 'number' || !Number.isInteger(rawIndex)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  const index = rawIndex;

  const currentIndex = encounter.turn_index;
  const n = encounter.combatants.length;
  if (index <= currentIndex || index >= n || n === 0) {
    sendJSON(res, 400, { error: 'invalid index' });
    return;
  }

  const combatants = [...encounter.combatants];
  const [moved] = combatants.splice(currentIndex, 1);
  combatants.splice(index, 0, moved);

  const updated: PlayEncounter = { ...encounter, combatants, turn_index: index };
  updatePlayEncounter(updated);

  sendJSON(res, 200, {
    order: updated.combatants.map((c) => ({ name: c.name, kind: c.type, initiative: c.initiative ?? 0 })),
  });
}

export function handleReadyEncounterTurn(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const encounter = getPlayEncounter(params.enc_id);
  if (!encounter || encounter.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const currentActor = activeCombatantActor(encounter, campaign);
  if (currentActor !== actor.username) {
    sendJSON(res, 409, { error: 'not your turn' });
    return;
  }

  const { trigger } = body as Record<string, unknown>;
  if (!isNonEmptyString(trigger)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const sequence = countReadiedActions(params.enc_id) + 1;
  const readied: ReadiedAction = {
    id: `ready-${params.enc_id}-${sequence}`,
    encounter_id: params.enc_id,
    actor: actor.username,
    trigger,
  };
  createReadiedAction(readied);

  sendJSON(res, 201, {
    actor: readied.actor,
    trigger: readied.trigger,
  });
}

const COMBAT_ACTION_TYPES = ['attack', 'help', 'dodge', 'ready'] as const;
type CombatActionType = (typeof COMBAT_ACTION_TYPES)[number];

function isValidCombatActionType(value: unknown): value is CombatActionType {
  return typeof value === 'string' && COMBAT_ACTION_TYPES.includes(value as CombatActionType);
}

export function handleSubmitCombatAction(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const isMember = campaign.owner === actor.username || getPlayMembershipByCampaignAndUser(params.id, actor.username) !== null;
  if (!isMember) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const encounter = getPlayEncounter(params.enc_id);
  if (!encounter || encounter.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const currentActor = activeCombatantActor(encounter, campaign);
  if (currentActor !== actor.username) {
    sendJSON(res, 409, { error: 'not your turn' });
    return;
  }

  const { type, target, text } = body as Record<string, unknown>;
  if (!isValidCombatActionType(type) || !isNonEmptyString(target) || !isNonEmptyString(text)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const sequence = countEvents(params.id) + 1;
  const action: CombatAction = {
    id: `combat-action-${params.id}-${params.enc_id}-${sequence}`,
    campaign_id: params.id,
    encounter_id: params.enc_id,
    sequence,
    actor: actor.username,
    type,
    target,
    text,
  };
  createCombatAction(action);

  sendJSON(res, 201, {
    sequence: action.sequence,
    kind: 'combat_action',
    actor: action.actor,
    type: action.type,
    target: action.target,
    text: action.text,
  });
}

export function handleDamage(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireDM(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  if (campaign.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const encounter = getPlayEncounter(params.enc_id);
  if (!encounter || encounter.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { target, amount } = body as Record<string, unknown>;
  if (!isNonEmptyString(target) || !isPositiveInteger(amount)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const index = encounter.combatants.findIndex((c) => c.id === target);
  if (index === -1) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const combatant = encounter.combatants[index];
  const hpMax = combatant.hp_max ?? 0;
  const hpBefore = combatant.hp_current ?? hpMax;
  const hpAfter = Math.max(0, hpBefore - amount);

  const updatedCombatants = [...encounter.combatants];
  updatedCombatants[index] = { ...combatant, hp_current: hpAfter };
  updatePlayEncounter({ ...encounter, combatants: updatedCombatants });

  if (combatant.type === 'player') {
    const membership = getPlayMembershipByCharacterId(combatant.id);
    if (membership) {
      updatePlayMembershipHp(membership.campaign_id, membership.username, hpAfter);
    }
  }

  sendJSON(res, 200, {
    target,
    hp_before: hpBefore,
    hp_after: hpAfter,
    damage: amount,
  });
}

export function handleHeal(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireDM(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  if (campaign.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const encounter = getPlayEncounter(params.enc_id);
  if (!encounter || encounter.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { target, amount } = body as Record<string, unknown>;
  if (!isNonEmptyString(target) || !isPositiveInteger(amount)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const index = encounter.combatants.findIndex((c) => c.id === target);
  if (index === -1) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const combatant = encounter.combatants[index];
  const hpMax = combatant.hp_max ?? 0;
  const hpBefore = combatant.hp_current ?? hpMax;
  const hpAfter = Math.min(hpMax, hpBefore + amount);

  const updatedCombatants = [...encounter.combatants];
  updatedCombatants[index] = { ...combatant, hp_current: hpAfter };
  updatePlayEncounter({ ...encounter, combatants: updatedCombatants });

  if (combatant.type === 'player') {
    const membership = getPlayMembershipByCharacterId(combatant.id);
    if (membership) {
      updatePlayMembershipHp(membership.campaign_id, membership.username, hpAfter);
    }
  }

  sendJSON(res, 200, {
    target,
    hp_before: hpBefore,
    hp_after: hpAfter,
    healing: amount,
  });
}

export function handleCharacterDamage(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const membership = getPlayMembershipByCharacterId(params.char_id);
  if (!membership || membership.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const isOwner = campaign.owner === actor.username;
  const isCharacterPlayer = membership.username === actor.username;
  if (!isOwner && !isCharacterPlayer) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const { amount } = body as Record<string, unknown>;
  if (!isPositiveInteger(amount)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const hpBefore = membership.hp_current;
  const hpAfter = Math.max(0, hpBefore - amount);

  updatePlayMembershipHp(membership.campaign_id, membership.username, hpAfter);

  sendJSON(res, 200, {
    target: membership.character_id,
    hp_before: hpBefore,
    hp_after: hpAfter,
    damage: amount,
  });
}

export function handleDeathSaves(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requirePlayer(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const membership = getPlayMembershipByCharacterId(params.char_id);
  if (!membership || membership.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  if (membership.username !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const { outcome } = body as Record<string, unknown>;
  if (!isValidDeathSaveOutcome(outcome)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  if (membership.status !== 'unconscious') {
    sendJSON(res, 409, { error: 'character cannot roll death saves' });
    return;
  }

  let successes = membership.death_save_successes;
  let failures = membership.death_save_failures;
  let status: PlayMembership['status'] = membership.status;

  if (outcome === 'success') {
    successes += 1;
    if (successes >= 3) {
      successes = 3;
      status = 'stable';
    }
  } else {
    failures += 1;
    if (failures >= 3) {
      failures = 3;
      status = 'dead';
    }
  }

  updatePlayMembershipDeathSaves(membership.campaign_id, membership.username, status, successes, failures);

  sendJSON(res, 201, {
    character_id: membership.character_id,
    successes,
    failures,
    status,
  });
}

export function handleGetCharacterStatus(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const isMember = campaign.owner === actor.username || getPlayMembershipByCampaignAndUser(params.id, actor.username) !== null;
  if (!isMember) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const membership = getPlayMembershipByCharacterId(params.char_id);
  if (!membership || membership.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  sendJSON(res, 200, {
    character_id: membership.character_id,
    hp_current: membership.hp_current,
    hp_max: membership.hp_max,
    status: membership.status,
  });
}

export function handleAwardRewards(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  if (campaign.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const encounter = getPlayEncounter(params.enc_id);
  if (!encounter || encounter.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { xp, loot } = body as Record<string, unknown>;
  if (!isNonNegativeInteger(xp) || !isValidLootArray(loot)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  if (encounterRewardExists(params.enc_id)) {
    sendJSON(res, 409, { error: 'rewards already awarded' });
    return;
  }

  const reward = {
    encounter_id: params.enc_id,
    xp,
    loot: loot as LootItem[],
  };
  createEncounterReward(reward);

  for (const item of reward.loot) {
    addInventoryItem(params.id, item.slug, item.quantity, 'party');
  }

  sendJSON(res, 200, {
    id: encounter.id,
    xp: reward.xp,
    loot: reward.loot,
  });
}

export function handleCloseEncounter(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  if (campaign.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const encounter = getPlayEncounter(params.enc_id);
  if (!encounter || encounter.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  updatePlayEncounterStatus(encounter.id, 'closed');
  const reward = getEncounterReward(encounter.id);

  sendJSON(res, 200, {
    id: encounter.id,
    status: 'closed',
    xp_awarded: reward ? reward.xp : 0,
  });
}

export function handleEndEncounter(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireDM(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  if (campaign.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  if (campaign.pre_combat_actor == null) {
    sendJSON(res, 409, { error: 'not in combat' });
    return;
  }

  const encounter = getPlayEncounter(params.enc_id);
  if (!encounter || encounter.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  if (encounter.status === 'active') {
    updatePlayEncounterStatus(encounter.id, 'closed');
  }
  updatePlayCampaignStatus({
    id: params.id,
    status: campaign.status,
    current_actor: campaign.pre_combat_actor,
    turn_number: campaign.turn_number,
    phase: 'exploration',
  });
  setPlayCampaignPreCombatActor(params.id, null);

  sendJSON(res, 200, {
    campaign_id: campaign.id,
    status: campaign.status,
    phase: 'exploration',
    current_actor: campaign.pre_combat_actor,
  });
}

export function handleGetCharacterOwner(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const isMember = campaign.owner === actor.username || getPlayMembershipByCampaignAndUser(params.id, actor.username) !== null;
  if (!isMember) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const membership = getPlayMembershipByCharacterId(params.char_id);
  if (!membership || membership.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  sendJSON(res, 200, {
    character_id: membership.character_id,
    owner: membership.owner,
  });
}

export function handleClaimCharacter(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const actor = requirePlayer(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const membership = getPlayMembershipByCampaignAndUser(params.id, actor.username);
  if (!membership) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const character = getPlayMembershipByCharacterId(params.char_id);
  if (!character || character.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  if (character.owner !== null) {
    sendJSON(res, 409, { error: 'character already owned' });
    return;
  }

  updatePlayMembershipOwner(params.id, params.char_id, actor.username);

  sendJSON(res, 201, {
    character_id: params.char_id,
    owner: actor.username,
  });
}

export function handleTransferCharacter(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const character = getPlayMembershipByCharacterId(params.char_id);
  if (!character || character.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  if (character.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const { new_owner } = body as Record<string, unknown>;
  if (!isNonEmptyString(new_owner)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  if (!getPlayMembershipByCampaignAndUser(params.id, new_owner)) {
    sendJSON(res, 400, { error: 'invalid new owner' });
    return;
  }

  updatePlayMembershipOwner(params.id, params.char_id, new_owner);

  sendJSON(res, 200, {
    character_id: params.char_id,
    owner: new_owner,
  });
}

export function handleBuildCharacter(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const membership = getPlayMembershipByCharacterId(params.char_id);
  if (!membership || membership.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  if (membership.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const { race, class: className, background, abilities } = body as Record<string, unknown>;
  if (
    !isValidRace(race) ||
    !isValidClass(className) ||
    !isValidBackground(background) ||
    !isValidAbilityScores(abilities)
  ) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const conScore = (abilities as Record<string, unknown>).con as number;
  const conModifier = abilityModifier(conScore);
  const hitDie = classHitDie(className.toLowerCase())!;
  const hpMax = hitDie + conModifier;

  updatePlayMembershipBuild(
    membership.campaign_id,
    membership.username,
    className,
    hpMax,
    conModifier,
  );

  sendJSON(res, 200, {
    character_id: membership.character_id,
    race,
    class: className,
    background,
    level: 1,
    hp_max: hpMax,
    proficiency_bonus: 2,
  });
}

export function handleLevelUp(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const membership = getPlayMembershipByCharacterId(params.char_id);
  if (!membership || membership.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  if (membership.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const { level } = body as Record<string, unknown>;
  if (!isValidLevel(level) || level !== membership.level + 1) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const sides = classHitDie(membership.class.toLowerCase());
  if (!sides) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const dieAverage = averageHitDie(sides)!;
  const gain = Math.max(1, dieAverage + membership.con_modifier);
  const newHpMax = membership.hp_max + gain;

  updatePlayMembershipLevel(membership.campaign_id, membership.username, level, newHpMax);

  sendJSON(res, 200, {
    character_id: membership.character_id,
    level,
    hp_max: newHpMax,
    hit_dice: `1d${sides}`,
    proficiency_bonus: proficiencyBonus(level),
  });
}
