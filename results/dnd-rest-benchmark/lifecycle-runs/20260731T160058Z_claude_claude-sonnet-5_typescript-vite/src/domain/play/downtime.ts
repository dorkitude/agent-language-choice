/**
 * Recurring downtime activities that campaign members allocate to owned
 * characters and progress repeatedly. See shared.ts for the ownership model.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { isValidIntInRange } from '../../validation.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant, resolveCharacterOwner } from './shared.ts';

type ActivityRow = {
  activity_id: string;
  name: string;
  cycles_required: number;
};

type AllocationRow = {
  character_id: string;
  activity_id: string;
  cycles_completed: number;
  completions: number;
};

function activityBody(row: ActivityRow): JsonValue {
  return {
    activity_id: row.activity_id,
    name: row.name,
    cycles_required: row.cycles_required,
  } as JsonValue;
}

function allocationBody(row: AllocationRow): JsonValue {
  return {
    character_id: row.character_id,
    activity_id: row.activity_id,
    cycles_completed: row.cycles_completed,
    completions: row.completions,
  } as JsonValue;
}

function findActivity(db: ReturnType<typeof getDb>, campaignId: string, activityId: string): ActivityRow | ApiResult {
  const row = db
    .prepare(
      'SELECT activity_id, name, cycles_required FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?',
    )
    .get(campaignId, activityId) as ActivityRow | undefined;
  return row ?? { status: 404, body: { error: 'downtime activity not found' } };
}

function findAllocation(
  db: ReturnType<typeof getDb>,
  campaignId: string,
  characterId: string,
  activityId: string,
): AllocationRow | ApiResult {
  const row = db
    .prepare(
      'SELECT character_id, activity_id, cycles_completed, completions FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?',
    )
    .get(campaignId, characterId, activityId) as AllocationRow | undefined;
  return row ?? { status: 404, body: { error: 'downtime allocation not found' } };
}

export function createDowntimeActivity(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may create downtime activities' } };
  }

  const activityId = body.activity_id;
  if (typeof activityId !== 'string' || activityId.length === 0) {
    return { status: 400, body: { error: 'activity_id must be a non-empty string' } };
  }

  const name = body.name;
  if (typeof name !== 'string' || name.length === 0) {
    return { status: 400, body: { error: 'name must be a non-empty string' } };
  }

  if (!isValidIntInRange(body.cycles_required, 1, 10)) {
    return { status: 400, body: { error: 'cycles_required must be an integer from 1 through 10' } };
  }

  const existing = db
    .prepare('SELECT activity_id FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?')
    .get(campaignId, activityId);
  if (existing) {
    return { status: 409, body: { error: 'activity_id already exists in this campaign' } };
  }

  const cyclesRequired = body.cycles_required as number;
  db.prepare(
    'INSERT INTO play_campaign_downtime_activities (campaign_id, activity_id, name, cycles_required) VALUES (?, ?, ?, ?)',
  ).run(campaignId, activityId, name, cyclesRequired);

  return {
    status: 201,
    body: activityBody({ activity_id: activityId, name, cycles_required: cyclesRequired }),
  };
}

export function createDowntimeAllocation(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }
  if (owner !== actor.username) {
    return { status: 403, body: { error: 'only the character owner may allocate downtime' } };
  }

  const activityId = body.activity_id;
  if (typeof activityId !== 'string' || activityId.length === 0) {
    return { status: 400, body: { error: 'activity_id must be a non-empty string' } };
  }

  const activity = findActivity(db, campaignId, activityId);
  if (isApiResult(activity)) return activity;

  const existing = db
    .prepare(
      'SELECT character_id FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?',
    )
    .get(campaignId, characterId, activityId);
  if (existing) {
    return { status: 409, body: { error: 'allocation already exists for this character and activity' } };
  }

  db.prepare(
    'INSERT INTO play_campaign_downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (?, ?, ?, 0, 0)',
  ).run(campaignId, characterId, activityId);

  return {
    status: 201,
    body: allocationBody({ character_id: characterId, activity_id: activityId, cycles_completed: 0, completions: 0 }),
  };
}

export function progressDowntimeAllocation(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  activityId: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }
  if (owner !== actor.username) {
    return { status: 403, body: { error: 'only the character owner may progress downtime' } };
  }

  const activity = findActivity(db, campaignId, activityId);
  if (isApiResult(activity)) return activity;

  const allocation = findAllocation(db, campaignId, characterId, activityId);
  if (isApiResult(allocation)) return allocation;

  let cyclesCompleted = allocation.cycles_completed + 1;
  let completions = allocation.completions;
  if (cyclesCompleted >= activity.cycles_required) {
    cyclesCompleted = 0;
    completions += 1;
  }

  db.prepare(
    'UPDATE play_campaign_downtime_allocations SET cycles_completed = ?, completions = ? WHERE campaign_id = ? AND character_id = ? AND activity_id = ?',
  ).run(cyclesCompleted, completions, campaignId, characterId, activityId);

  return {
    status: 200,
    body: allocationBody({ character_id: characterId, activity_id: activityId, cycles_completed: cyclesCompleted, completions }),
  };
}

export function getDowntimeAllocation(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  activityId: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const activity = findActivity(db, campaignId, activityId);
  if (isApiResult(activity)) return activity;

  const allocation = findAllocation(db, campaignId, characterId, activityId);
  if (isApiResult(allocation)) return allocation;

  return { status: 200, body: allocationBody(allocation) };
}
