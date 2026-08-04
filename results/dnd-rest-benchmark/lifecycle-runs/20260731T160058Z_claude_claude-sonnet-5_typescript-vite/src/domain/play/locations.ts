/**
 * Location graph and turn-consuming exploration actions: creating locations
 * and connections, inspecting travel options, traveling, and resting.
 * Traveling and resting both end the active player's turn and hand it to
 * the DM, mirroring how `submitPlayerAction` works in campaign-turns.ts.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { isValidIntInRange } from '../../validation.ts';
import {
  authenticate,
  isActor,
  isApiResult,
  findCampaign,
  listMembers,
  requireParticipant,
  nextSequence,
  insertEvent,
  requireNonEmptyString,
  findLocation,
} from './shared.ts';

export function createLocation(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may create a location' } };
  }

  const id = requireNonEmptyString(body.id, 'id');
  if (isApiResult(id)) return id;

  const name = requireNonEmptyString(body.name, 'name');
  if (isApiResult(name)) return name;

  if (findLocation(db, campaignId, id)) {
    return { status: 409, body: { error: 'location id already exists' } };
  }

  db.prepare('INSERT INTO play_campaign_locations (campaign_id, id, name) VALUES (?, ?, ?)').run(
    campaignId,
    id,
    name,
  );

  if (!campaign.current_location_id) {
    db.prepare('UPDATE play_campaigns SET current_location_id = ? WHERE id = ?').run(id, campaignId);
  }

  return { status: 201, body: { id, name } };
}

export function createLocationConnection(
  authHeader: string | undefined,
  campaignId: string,
  fromId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may create a connection' } };
  }

  if (!findLocation(db, campaignId, fromId)) {
    return { status: 404, body: { error: 'location not found' } };
  }

  const toId = requireNonEmptyString(body.to_id, 'to_id');
  if (isApiResult(toId)) return toId;

  if (!isValidIntInRange(body.travel_turns, 1, 1000000)) {
    return { status: 400, body: { error: 'travel_turns must be a positive integer' } };
  }
  const travelTurns = body.travel_turns as number;

  if (!findLocation(db, campaignId, toId)) {
    return { status: 400, body: { error: 'to_id location does not exist' } };
  }

  const existing = db
    .prepare(
      'SELECT from_id FROM play_campaign_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?',
    )
    .get(campaignId, fromId, toId);
  if (existing) {
    return { status: 400, body: { error: 'connection already exists' } };
  }

  db.prepare(
    'INSERT INTO play_campaign_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)',
  ).run(campaignId, fromId, toId, travelTurns);

  return { status: 201, body: { from_id: fromId, to_id: toId, travel_turns: travelTurns } };
}

export function getLocationTravel(
  authHeader: string | undefined,
  campaignId: string,
  locationId: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  if (!findLocation(db, campaignId, locationId)) {
    return { status: 404, body: { error: 'location not found' } };
  }

  const destinations = db
    .prepare(
      `SELECT c.to_id AS id, l.name AS name, c.travel_turns AS travel_turns
       FROM play_campaign_location_connections c
       JOIN play_campaign_locations l ON l.campaign_id = c.campaign_id AND l.id = c.to_id
       WHERE c.campaign_id = ? AND c.from_id = ?
       ORDER BY c.to_id ASC`,
    )
    .all(campaignId, locationId) as { id: string; name: string; travel_turns: number }[];

  return { status: 200, body: { destinations } };
}

export function travelToLocation(
  authHeader: string | undefined,
  campaignId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  if (actor.role !== 'player' || campaign.current_actor !== actor.username) {
    return { status: 409, body: { error: 'only the active player may travel' } };
  }

  const destinationId = requireNonEmptyString(body.destination_id, 'destination_id');
  if (isApiResult(destinationId)) return destinationId;

  if (!campaign.current_location_id) {
    return { status: 409, body: { error: 'no valid connection to destination' } };
  }

  const connection = db
    .prepare(
      'SELECT travel_turns FROM play_campaign_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?',
    )
    .get(campaignId, campaign.current_location_id, destinationId) as { travel_turns: number } | undefined;
  if (!connection) {
    return { status: 409, body: { error: 'no valid connection to destination' } };
  }

  const sequence = nextSequence(db, campaignId);
  insertEvent(db, campaignId, sequence, 'travel', actor.username, `Travel to ${destinationId}`);

  db.prepare(
    'UPDATE play_campaigns SET current_location_id = ?, current_actor = ?, turn_nudge_count = 0 WHERE id = ?',
  ).run(destinationId, campaign.owner, campaignId);

  return {
    status: 201,
    body: {
      sequence,
      kind: 'travel',
      actor: actor.username,
      destination_id: destinationId,
      travel_turns: connection.travel_turns,
      next_actor: 'dm',
    },
  };
}

const REST_TYPES = new Set(['short', 'long']);

export function restOnTurn(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  if (actor.role !== 'player' || campaign.current_actor !== actor.username) {
    return { status: 409, body: { error: 'only the active player may rest' } };
  }

  const type = body.type;
  if (typeof type !== 'string' || !REST_TYPES.has(type)) {
    return { status: 400, body: { error: 'type must be "short" or "long"' } };
  }

  const member = listMembers(db, campaignId).find((m) => m.username === actor.username);
  if (!member) {
    return { status: 403, body: { error: 'not a campaign member' } };
  }

  const hpCurrent = type === 'long' ? member.hp_max : member.hp_current;
  if (type === 'long' && hpCurrent !== member.hp_current) {
    db.prepare('UPDATE play_campaign_members SET hp_current = ? WHERE campaign_id = ? AND username = ?').run(
      hpCurrent,
      campaignId,
      actor.username,
    );
  }

  const sequence = nextSequence(db, campaignId);
  insertEvent(db, campaignId, sequence, 'rest', actor.username, `${type} rest`, type);

  db.prepare('UPDATE play_campaigns SET current_actor = ?, turn_nudge_count = 0 WHERE id = ?').run(
    campaign.owner,
    campaignId,
  );

  return {
    status: 201,
    body: {
      sequence,
      kind: 'rest',
      actor: actor.username,
      type,
      hp_current: hpCurrent,
      hp_max: member.hp_max,
      next_actor: 'dm',
    },
  };
}
