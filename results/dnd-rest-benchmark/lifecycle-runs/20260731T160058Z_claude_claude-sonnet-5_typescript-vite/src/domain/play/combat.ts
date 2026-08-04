/**
 * Encounter and combat-turn machinery: initiative order, turn advance/delay/
 * ready, conditions, combatant binding, monster HP, and encounter rewards.
 * Initiative order and condition state live as JSON columns on
 * play_campaign_encounters and are recomputed from `shared.ts` helpers on
 * every call rather than cached, so writers never race a stale order.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { isValidIntInRange } from '../../validation.ts';
import {
  authenticate,
  isActor,
  isApiResult,
  findCampaign,
  requireParticipant,
  findEncounter,
  buildInitiativeOrder,
  combatantKey,
  parseConditions,
  encounterHasTarget,
  activeCombatantBody,
  findMonsterTarget,
  parseLoot,
  requireNonEmptyString,
  listMembers,
  nextSequence,
  insertEvent,
  type Monster,
  type PartyCombatant,
} from './shared.ts';

export function getEncounterTurn(authHeader: string | undefined, campaignId: string, encounterId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const encounter = findEncounter(db, campaignId, encounterId);
  if (isApiResult(encounter)) return encounter;

  const order = buildInitiativeOrder(encounter);
  if (order.length === 0) {
    return { status: 409, body: { error: 'encounter has no combatants' } };
  }

  const turnIndex = encounter.turn_index % order.length;
  return { status: 200, body: activeCombatantBody(encounter.round, turnIndex, order[turnIndex]) };
}

export function advanceEncounterTurn(
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const encounter = findEncounter(db, campaignId, encounterId);
  if (isApiResult(encounter)) return encounter;

  const order = buildInitiativeOrder(encounter);
  if (order.length === 0) {
    return { status: 409, body: { error: 'encounter has no combatants' } };
  }

  const turnIndex = encounter.turn_index % order.length;
  const active = order[turnIndex];

  const isOwner = actor.username === campaign.owner;
  const isCurrentCombatant = active.kind === 'player' && active.member === actor.username;
  if (!isOwner && !isCurrentCombatant) {
    return { status: 409, body: { error: 'not your turn to advance combat' } };
  }

  let nextIndex = turnIndex + 1;
  let round = encounter.round;
  if (nextIndex >= order.length) {
    nextIndex = 0;
    round += 1;
  }

  const nextActive = order[nextIndex];
  const conditions = parseConditions(encounter);
  const nextKey = combatantKey(nextActive);
  const targetConditions = conditions[nextKey];
  if (targetConditions && targetConditions.length > 0) {
    const decremented = targetConditions
      .map((c) => ({ condition: c.condition, remaining_rounds: c.remaining_rounds - 1 }))
      .filter((c) => c.remaining_rounds > 0);
    if (decremented.length > 0) {
      conditions[nextKey] = decremented;
    } else {
      delete conditions[nextKey];
    }
  }

  db.prepare(
    'UPDATE play_campaign_encounters SET round = ?, turn_index = ?, conditions_json = ? WHERE campaign_id = ? AND id = ?',
  ).run(round, nextIndex, JSON.stringify(conditions), campaignId, encounterId);

  return { status: 200, body: activeCombatantBody(round, nextIndex, nextActive) };
}

export function delayEncounterTurn(
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const encounter = findEncounter(db, campaignId, encounterId);
  if (isApiResult(encounter)) return encounter;

  const order = buildInitiativeOrder(encounter);
  if (order.length === 0) {
    return { status: 409, body: { error: 'encounter has no combatants' } };
  }

  const turnIndex = encounter.turn_index % order.length;
  const active = order[turnIndex];

  const isOwner = actor.username === campaign.owner;
  const isCurrentCombatant = active.kind === 'player' && active.member === actor.username;
  if (!isOwner && !isCurrentCombatant) {
    return { status: 409, body: { error: 'not your turn to delay' } };
  }

  if (!isValidIntInRange(body.new_index, 0, order.length - 1) || (body.new_index as number) <= turnIndex) {
    return { status: 400, body: { error: 'new_index must be a later position in the initiative order' } };
  }
  const newIndex = body.new_index as number;

  const remaining = order.filter((_, index) => index !== turnIndex);
  remaining.splice(newIndex, 0, active);

  db.prepare(
    'UPDATE play_campaign_encounters SET turn_index = ?, order_override_json = ? WHERE campaign_id = ? AND id = ?',
  ).run(newIndex, JSON.stringify(remaining.map(combatantKey)), campaignId, encounterId);

  return {
    status: 200,
    body: { order: remaining.map((c) => ({ name: c.name, kind: c.kind, initiative: c.initiative })) } as unknown as JsonValue,
  };
}

export function readyEncounterTurn(
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const encounter = findEncounter(db, campaignId, encounterId);
  if (isApiResult(encounter)) return encounter;

  const order = buildInitiativeOrder(encounter);
  if (order.length === 0) {
    return { status: 409, body: { error: 'encounter has no combatants' } };
  }

  const turnIndex = encounter.turn_index % order.length;
  const active = order[turnIndex];

  const isCurrentCombatant = active.kind === 'player' && active.member === actor.username;
  if (!isCurrentCombatant) {
    return { status: 409, body: { error: 'not your turn to ready' } };
  }

  const trigger = requireNonEmptyString(body.trigger, 'trigger');
  if (isApiResult(trigger)) return trigger;

  return { status: 201, body: { actor: actor.username, trigger } as unknown as JsonValue };
}

export function addEncounterCondition(
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may apply a condition' } };
  }

  const encounter = findEncounter(db, campaignId, encounterId);
  if (isApiResult(encounter)) return encounter;

  const target = requireNonEmptyString(body.target, 'target');
  if (isApiResult(target)) return target;

  const condition = requireNonEmptyString(body.condition, 'condition');
  if (isApiResult(condition)) return condition;

  if (!isValidIntInRange(body.duration_rounds, 1, 1000000)) {
    return { status: 400, body: { error: 'duration_rounds must be a positive integer' } };
  }
  const durationRounds = body.duration_rounds as number;

  if (!encounterHasTarget(encounter, target)) {
    return { status: 404, body: { error: 'target not found' } };
  }

  const conditions = parseConditions(encounter);
  const existing = conditions[target] ?? [];
  existing.push({ condition, remaining_rounds: durationRounds });
  conditions[target] = existing;

  db.prepare('UPDATE play_campaign_encounters SET conditions_json = ? WHERE campaign_id = ? AND id = ?').run(
    JSON.stringify(conditions),
    campaignId,
    encounterId,
  );

  return { status: 201, body: { target, conditions: existing } as unknown as JsonValue };
}

export function getEncounterStatus(
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const encounter = findEncounter(db, campaignId, encounterId);
  if (isApiResult(encounter)) return encounter;

  const order = buildInitiativeOrder(encounter);
  const turnIndex = order.length > 0 ? encounter.turn_index % order.length : encounter.turn_index;
  const active = order.length > 0 ? order[turnIndex] : null;
  const conditions = parseConditions(encounter);

  return {
    status: 200,
    body: {
      round: encounter.round,
      turn_index: turnIndex,
      active: active ? { name: active.name, kind: active.kind, initiative: active.initiative } : null,
      order: order.map((c) => ({ name: c.name, kind: c.kind, initiative: c.initiative })),
      conditions,
    } as unknown as JsonValue,
  };
}

const COMBAT_ACTION_TYPES = new Set(['attack', 'help', 'dodge', 'ready']);

export function submitCombatAction(
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const encounter = findEncounter(db, campaignId, encounterId);
  if (isApiResult(encounter)) return encounter;

  const order = buildInitiativeOrder(encounter);
  if (order.length === 0) {
    return { status: 409, body: { error: 'encounter has no combatants' } };
  }

  const turnIndex = encounter.turn_index % order.length;
  const active = order[turnIndex];
  const isCurrentCombatant = active.kind === 'player' && active.member === actor.username;
  if (!isCurrentCombatant) {
    return { status: 409, body: { error: 'not your turn to act' } };
  }

  const type = body.type;
  if (typeof type !== 'string' || !COMBAT_ACTION_TYPES.has(type)) {
    return { status: 400, body: { error: 'type must be one of attack, help, dodge, ready' } };
  }

  const text = requireNonEmptyString(body.text, 'text');
  if (isApiResult(text)) return text;

  const target = body.target;
  if (target !== undefined && typeof target !== 'string') {
    return { status: 400, body: { error: 'target must be a string' } };
  }

  const sequence = nextSequence(db, campaignId);
  insertEvent(db, campaignId, sequence, 'combat_action', actor.username, text, type);

  return {
    status: 201,
    body: {
      sequence,
      kind: 'combat_action',
      actor: actor.username,
      type,
      target: target ?? null,
      text,
    },
  };
}

export function bindEncounterCombatant(
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may bind a combatant' } };
  }

  const encounter = findEncounter(db, campaignId, encounterId);
  if (isApiResult(encounter)) return encounter;

  const member = requireNonEmptyString(body.member, 'member');
  if (isApiResult(member)) return member;

  if (!isValidIntInRange(body.initiative, 0, 1000000)) {
    return { status: 400, body: { error: 'initiative must be a non-negative integer' } };
  }
  const initiative = body.initiative as number;

  const partyMember = listMembers(db, campaignId).find((m) => m.username === member);
  if (!partyMember) {
    return { status: 400, body: { error: 'member not found in campaign party' } };
  }

  const combatants = JSON.parse(encounter.party_combatants_json) as PartyCombatant[];
  if (combatants.some((c) => c.member === member)) {
    return { status: 409, body: { error: 'member already bound to encounter' } };
  }

  const combatant: PartyCombatant = {
    member,
    character_id: partyMember.character_id,
    name: partyMember.name,
    initiative,
  };
  combatants.push(combatant);

  db.prepare('UPDATE play_campaign_encounters SET party_combatants_json = ? WHERE campaign_id = ? AND id = ?').run(
    JSON.stringify(combatants),
    campaignId,
    encounterId,
  );

  return { status: 201, body: combatant as unknown as JsonValue };
}

export function unbindEncounterCombatant(
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  member: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may unbind a combatant' } };
  }

  const encounter = findEncounter(db, campaignId, encounterId);
  if (isApiResult(encounter)) return encounter;

  const combatants = JSON.parse(encounter.party_combatants_json) as PartyCombatant[];
  const remaining = combatants.filter((c) => c.member !== member);
  if (remaining.length === combatants.length) {
    return { status: 404, body: { error: 'combatant not found' } };
  }

  db.prepare('UPDATE play_campaign_encounters SET party_combatants_json = ? WHERE campaign_id = ? AND id = ?').run(
    JSON.stringify(remaining),
    campaignId,
    encounterId,
  );

  return { status: 200, body: { removed: member } };
}

export function addMonsterToEncounter(
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may add a monster' } };
  }

  const encounter = findEncounter(db, campaignId, encounterId);
  if (isApiResult(encounter)) return encounter;

  const monsterId = requireNonEmptyString(body.monster_id, 'monster_id');
  if (isApiResult(monsterId)) return monsterId;

  const name = requireNonEmptyString(body.name, 'name');
  if (isApiResult(name)) return name;

  if (!isValidIntInRange(body.hp_max, 1, 1000000)) {
    return { status: 400, body: { error: 'hp_max must be a positive integer' } };
  }
  const hpMax = body.hp_max as number;

  if (!isValidIntInRange(body.initiative, 0, 1000000)) {
    return { status: 400, body: { error: 'initiative must be a non-negative integer' } };
  }
  const initiative = body.initiative as number;

  const monsters = JSON.parse(encounter.combatants_json) as Monster[];
  if (monsters.some((m) => m.monster_id === monsterId)) {
    return { status: 409, body: { error: 'monster id already exists' } };
  }

  const monster: Monster = { monster_id: monsterId, name, hp_max: hpMax, initiative, hp_current: hpMax };
  monsters.push(monster);

  db.prepare('UPDATE play_campaign_encounters SET combatants_json = ? WHERE campaign_id = ? AND id = ?').run(
    JSON.stringify(monsters),
    campaignId,
    encounterId,
  );

  return { status: 201, body: monster as unknown as JsonValue };
}

export function removeMonsterFromEncounter(
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  monsterId: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may remove a monster' } };
  }

  const encounter = findEncounter(db, campaignId, encounterId);
  if (isApiResult(encounter)) return encounter;

  const monsters = JSON.parse(encounter.combatants_json) as Monster[];
  const remaining = monsters.filter((m) => m.monster_id !== monsterId);
  if (remaining.length === monsters.length) {
    return { status: 404, body: { error: 'monster not found' } };
  }

  db.prepare('UPDATE play_campaign_encounters SET combatants_json = ? WHERE campaign_id = ? AND id = ?').run(
    JSON.stringify(remaining),
    campaignId,
    encounterId,
  );

  return { status: 200, body: { removed: monsterId } };
}

export function damageEncounterCombatant(
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may apply damage' } };
  }

  const encounter = findEncounter(db, campaignId, encounterId);
  if (isApiResult(encounter)) return encounter;

  const target = requireNonEmptyString(body.target, 'target');
  if (isApiResult(target)) return target;

  if (!isValidIntInRange(body.amount, 0, 1000000)) {
    return { status: 400, body: { error: 'amount must be a non-negative integer' } };
  }
  const amount = body.amount as number;

  const found = findMonsterTarget(encounter, target);
  if (isApiResult(found)) return found;
  const { monsters, monster } = found;

  const hpBefore = monster.hp_current;
  const hpAfter = Math.max(0, hpBefore - amount);
  monster.hp_current = hpAfter;

  db.prepare('UPDATE play_campaign_encounters SET combatants_json = ? WHERE campaign_id = ? AND id = ?').run(
    JSON.stringify(monsters),
    campaignId,
    encounterId,
  );

  return {
    status: 200,
    body: { target, hp_before: hpBefore, hp_after: hpAfter, damage: amount },
  };
}

export function healEncounterCombatant(
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may apply healing' } };
  }

  const encounter = findEncounter(db, campaignId, encounterId);
  if (isApiResult(encounter)) return encounter;

  const target = requireNonEmptyString(body.target, 'target');
  if (isApiResult(target)) return target;

  if (!isValidIntInRange(body.amount, 0, 1000000)) {
    return { status: 400, body: { error: 'amount must be a non-negative integer' } };
  }
  const amount = body.amount as number;

  const found = findMonsterTarget(encounter, target);
  if (isApiResult(found)) return found;
  const { monsters, monster } = found;

  const hpBefore = monster.hp_current;
  const hpAfter = Math.min(monster.hp_max, hpBefore + amount);
  monster.hp_current = hpAfter;

  db.prepare('UPDATE play_campaign_encounters SET combatants_json = ? WHERE campaign_id = ? AND id = ?').run(
    JSON.stringify(monsters),
    campaignId,
    encounterId,
  );

  return {
    status: 200,
    body: { target, hp_before: hpBefore, hp_after: hpAfter, healing: amount },
  };
}

export function createEncounter(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may start an encounter' } };
  }

  const id = requireNonEmptyString(body.id, 'id');
  if (isApiResult(id)) return id;

  const name = requireNonEmptyString(body.name, 'name');
  if (isApiResult(name)) return name;

  const existing = db
    .prepare('SELECT id FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?')
    .get(campaignId, id);
  if (existing) {
    return { status: 409, body: { error: 'encounter id already exists' } };
  }

  const inCombat = db
    .prepare("SELECT id FROM play_campaign_encounters WHERE campaign_id = ? AND status = 'active'")
    .get(campaignId);
  if (inCombat) {
    return { status: 409, body: { error: 'campaign is already in combat' } };
  }

  db.prepare(
    'INSERT INTO play_campaign_encounters (campaign_id, id, name, status, combatants_json) VALUES (?, ?, ?, ?, ?)',
  ).run(campaignId, id, name, 'active', '[]');

  return {
    status: 201,
    body: { id, name, status: 'active', combatants: [] },
  };
}

export function awardEncounterRewards(
  authHeader: string | undefined,
  campaignId: string,
  encounterId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may award rewards' } };
  }

  const encounter = findEncounter(db, campaignId, encounterId);
  if (isApiResult(encounter)) return encounter;

  if (encounter.rewards_json) {
    return { status: 409, body: { error: 'rewards already awarded for this encounter' } };
  }

  if (!isValidIntInRange(body.xp, 0, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'xp must be a non-negative integer' } };
  }
  const xp = body.xp as number;

  const loot = parseLoot(body.loot);
  if (isApiResult(loot)) return loot;

  const reward = { encounter_id: encounterId, xp, loot };

  db.prepare('UPDATE play_campaign_encounters SET rewards_json = ?, xp_awarded = ? WHERE campaign_id = ? AND id = ?').run(
    JSON.stringify(reward),
    xp,
    campaignId,
    encounterId,
  );

  return { status: 200, body: reward };
}

export function closeEncounter(authHeader: string | undefined, campaignId: string, encounterId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may close the encounter' } };
  }

  const encounter = findEncounter(db, campaignId, encounterId);
  if (isApiResult(encounter)) return encounter;

  db.prepare('UPDATE play_campaign_encounters SET status = ? WHERE campaign_id = ? AND id = ?').run(
    'closed',
    campaignId,
    encounterId,
  );

  return {
    status: 200,
    body: { id: encounterId, status: 'closed', xp_awarded: encounter.xp_awarded },
  };
}

export function endEncounter(authHeader: string | undefined, campaignId: string, encounterId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may end the encounter' } };
  }

  const encounter = findEncounter(db, campaignId, encounterId);
  if (isApiResult(encounter)) return encounter;

  if (encounter.status === 'ended') {
    return { status: 409, body: { error: 'campaign is not in combat' } };
  }

  db.prepare('UPDATE play_campaign_encounters SET status = ? WHERE campaign_id = ? AND id = ?').run(
    'ended',
    campaignId,
    encounterId,
  );

  db.prepare('UPDATE play_campaigns SET current_actor = ?, phase = ? WHERE id = ?').run(
    campaign.owner,
    'exploration',
    campaignId,
  );

  return {
    status: 200,
    body: {
      campaign_id: campaignId,
      status: campaign.status,
      phase: 'exploration',
      current_actor: campaign.owner,
    },
  };
}
