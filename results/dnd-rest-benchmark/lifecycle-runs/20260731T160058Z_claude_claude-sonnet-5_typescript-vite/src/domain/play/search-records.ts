/**
 * Campaign-scoped search records with stable pagination, filtering, and
 * ordering. Only the campaign DM may create records; the DM and campaign
 * members may list them, preserving creation order.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant } from './shared.ts';

interface SearchRecordRow {
  sequence: number;
  record_id: string;
  text: string;
}

const MIN_LIMIT = 1;
const MAX_LIMIT = 3;
const DEFAULT_LIMIT = 2;

export function createSearchRecord(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign DM may create search records' } };
  }

  const record = body as Record<string, unknown>;
  const recordId = record?.record_id;
  if (typeof recordId !== 'string' || recordId.length === 0) {
    return { status: 400, body: { error: 'record_id must be a non-empty string' } };
  }
  const text = record?.text;
  if (typeof text !== 'string' || text.length === 0) {
    return { status: 400, body: { error: 'text must be a non-empty string' } };
  }

  const existing = db
    .prepare('SELECT record_id FROM play_campaign_search_records WHERE campaign_id = ? AND record_id = ?')
    .get(campaignId, recordId);
  if (existing) {
    return { status: 400, body: { error: 'record_id already exists' } };
  }

  const existingText = db
    .prepare('SELECT record_id FROM play_campaign_search_records WHERE campaign_id = ? AND LOWER(text) = LOWER(?)')
    .get(campaignId, text);
  if (existingText) {
    return { status: 400, body: { error: 'text already exists' } };
  }

  const sequenceRow = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_search_records WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };

  db.prepare(
    'INSERT INTO play_campaign_search_records (campaign_id, sequence, record_id, text) VALUES (?, ?, ?, ?)',
  ).run(campaignId, sequenceRow.max_sequence + 1, recordId, text);

  return { status: 201, body: { record_id: recordId, text } as unknown as JsonValue };
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

export function listSearchRecords(
  authHeader: string | undefined,
  campaignId: string,
  query: { q: string | null; limit: string | null; cursor: string | null },
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const limit = parseLimit(query.limit);
  if (isApiResult(limit)) return limit;
  const cursor = parseCursor(query.cursor);
  if (isApiResult(cursor)) return cursor;

  const rows = db
    .prepare(
      'SELECT sequence, record_id, text FROM play_campaign_search_records WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as unknown as SearchRecordRow[];

  const q = query.q;
  const filtered = q === null ? rows : rows.filter((row) => row.text.toLowerCase().includes(q.toLowerCase()));

  const page = filtered.slice(cursor, cursor + limit);
  const nextOffset = cursor + page.length;
  const nextCursor = nextOffset < filtered.length ? nextOffset : null;

  return {
    status: 200,
    body: {
      records: page.map((row) => ({ record_id: row.record_id, text: row.text })),
      next_cursor: nextCursor,
    } as unknown as JsonValue,
  };
}
