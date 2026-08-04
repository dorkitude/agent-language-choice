/**
 * Campaign-scoped idempotent event log. A mutating request tagged with an
 * `Idempotency-Key` has exactly one public effect: the first valid request
 * for a key stores the event, and any repeat of that same key returns the
 * original stored result instead of appending again.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, isMember } from './shared.ts';

interface IdempotentEventRow {
  sequence: number;
  event_id: string;
  value: string;
  idempotency_key: string;
}

function nextSequence(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_idempotent_events WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

function toEventBody(row: IdempotentEventRow): JsonValue {
  return {
    event_id: row.event_id,
    value: row.value,
    sequence: row.sequence,
    idempotency_key: row.idempotency_key,
  } as unknown as JsonValue;
}

export function createIdempotentEvent(
  authHeader: string | undefined,
  campaignId: string,
  idempotencyKeyHeader: string | undefined,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const isOwner = actor.username === campaign.owner;
  if (!isOwner && !isMember(db, campaignId, actor.username)) {
    return { status: 403, body: { error: 'only campaign members may create idempotent events' } };
  }

  const idempotencyKey = typeof idempotencyKeyHeader === 'string' ? idempotencyKeyHeader.trim() : '';
  if (idempotencyKey.length === 0) {
    return { status: 400, body: { error: 'Idempotency-Key header is required' } };
  }

  const eventId = body.event_id;
  if (typeof eventId !== 'string' || eventId.length === 0) {
    return { status: 400, body: { error: 'event_id must be a non-empty string' } };
  }

  const value = body.value;
  if (typeof value !== 'string' || value.length === 0) {
    return { status: 400, body: { error: 'value must be a non-empty string' } };
  }

  const existingByKey = db
    .prepare(
      'SELECT sequence, event_id, value, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = ? AND idempotency_key = ?',
    )
    .get(campaignId, idempotencyKey) as IdempotentEventRow | undefined;

  if (existingByKey) {
    if (existingByKey.event_id === eventId && existingByKey.value === value) {
      return { status: 200, body: toEventBody(existingByKey) };
    }
    return { status: 409, body: { error: 'idempotency key already used with a different event_id or value' } };
  }

  const existingByEventId = db
    .prepare('SELECT campaign_id FROM play_campaign_idempotent_events WHERE campaign_id = ? AND event_id = ?')
    .get(campaignId, eventId);
  if (existingByEventId) {
    return { status: 409, body: { error: 'event_id already used in this campaign' } };
  }

  const sequence = nextSequence(db, campaignId);
  db.prepare(
    'INSERT INTO play_campaign_idempotent_events (campaign_id, sequence, event_id, value, idempotency_key) VALUES (?, ?, ?, ?, ?)',
  ).run(campaignId, sequence, eventId, value, idempotencyKey);

  return { status: 201, body: toEventBody({ sequence, event_id: eventId, value, idempotency_key: idempotencyKey }) };
}

export function getIdempotentEvents(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const isOwner = actor.username === campaign.owner;
  if (!isOwner && !isMember(db, campaignId, actor.username)) {
    return { status: 403, body: { error: 'only the campaign DM or members may read idempotent events' } };
  }

  const rows = db
    .prepare(
      'SELECT sequence, event_id, value, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as unknown as IdempotentEventRow[];

  return { status: 200, body: { events: rows.map(toEventBody) } as unknown as JsonValue };
}
