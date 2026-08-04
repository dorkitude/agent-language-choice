/**
 * Authenticated campaign-member append-only event feed with cursor
 * pagination that stays stable when new events are appended between reads.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant } from './shared.ts';

interface FeedEventRow {
  sequence: number;
  event_id: string;
  text: string;
}

const MIN_LIMIT = 1;
const MAX_LIMIT = 3;
const DEFAULT_LIMIT = 2;

export function appendFeedEvent(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const record = body as Record<string, unknown>;
  const eventId = record?.event_id;
  if (typeof eventId !== 'string' || eventId.length === 0) {
    return { status: 400, body: { error: 'event_id must be a non-empty string' } };
  }
  const text = record?.text;
  if (typeof text !== 'string' || text.length === 0) {
    return { status: 400, body: { error: 'text must be a non-empty string' } };
  }

  const existing = db
    .prepare('SELECT event_id FROM play_campaign_feed_events WHERE campaign_id = ? AND event_id = ?')
    .get(campaignId, eventId);
  if (existing) {
    return { status: 409, body: { error: 'event_id already exists' } };
  }

  const sequenceRow = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_feed_events WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };
  const sequence = sequenceRow.max_sequence + 1;

  db.prepare(
    'INSERT INTO play_campaign_feed_events (campaign_id, sequence, event_id, text) VALUES (?, ?, ?, ?)',
  ).run(campaignId, sequence, eventId, text);

  return { status: 201, body: { event_id: eventId, text, sequence } as unknown as JsonValue };
}

function parseLimit(raw: string | null): number | ApiResult {
  if (raw === null) return DEFAULT_LIMIT;
  if (!/^-?\d+$/.test(raw)) {
    return { status: 400, body: { error: 'limit must be an integer from 1 through 3' } };
  }
  const value = Number(raw);
  if (!Number.isInteger(value) || value < MIN_LIMIT || value > MAX_LIMIT) {
    return { status: 400, body: { error: 'limit must be an integer from 1 through 3' } };
  }
  return value;
}

function parseCursor(raw: string | null): number | ApiResult {
  if (raw === null) return 0;
  if (!/^-?\d+$/.test(raw)) {
    return { status: 400, body: { error: 'cursor must be a nonnegative integer' } };
  }
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 0) {
    return { status: 400, body: { error: 'cursor must be a nonnegative integer' } };
  }
  return value;
}

export function getEventFeed(
  authHeader: string | undefined,
  campaignId: string,
  query: { cursor: string | null; limit: string | null },
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const cursor = parseCursor(query.cursor);
  if (isApiResult(cursor)) return cursor;
  const limit = parseLimit(query.limit);
  if (isApiResult(limit)) return limit;

  const rows = db
    .prepare(
      'SELECT sequence, event_id, text FROM play_campaign_feed_events WHERE campaign_id = ? ORDER BY sequence ASC LIMIT ? OFFSET ?',
    )
    .all(campaignId, limit, cursor) as unknown as FeedEventRow[];

  return {
    status: 200,
    body: {
      events: rows.map((row) => ({ event_id: row.event_id, text: row.text, sequence: row.sequence })),
      next_cursor: cursor + rows.length,
    } as unknown as JsonValue,
  };
}
