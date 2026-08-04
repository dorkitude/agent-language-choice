/**
 * Deterministic replay stream for campaign members. Replay events are
 * campaign-scoped, ordered by successful append order, and rebuild a public
 * replay state (`story`, `event_ids`, `digest`) without any randomness.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant } from './shared.ts';

interface ReplayEventRow {
  sequence: number;
  event_id: string;
  kind: string;
  text: string;
}

function nextReplaySequence(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_replay_events WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

function buildReplayState(rows: ReplayEventRow[]): JsonValue {
  const eventIds = rows.map((row) => row.event_id);
  const story = rows.map((row) => row.text).join('');
  const digest = `${eventIds.join(',')}|${story}`;
  return { story, event_ids: eventIds, digest } as unknown as JsonValue;
}

export function appendReplayEvent(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'only campaign members may append replay events');
  if (forbidden) return forbidden;

  const eventId = body.event_id;
  if (typeof eventId !== 'string' || eventId.length === 0) {
    return { status: 400, body: { error: 'event_id must be a non-empty string' } };
  }
  const text = body.text;
  if (typeof text !== 'string' || text.length === 0) {
    return { status: 400, body: { error: 'text must be a non-empty string' } };
  }
  const kind = body.kind;
  if (kind !== 'append') {
    return { status: 400, body: { error: 'kind must be exactly "append"' } };
  }

  const existing = db
    .prepare('SELECT campaign_id FROM play_campaign_replay_events WHERE campaign_id = ? AND event_id = ?')
    .get(campaignId, eventId);
  if (existing) {
    return { status: 409, body: { error: 'event_id already used in this campaign replay stream' } };
  }

  const sequence = nextReplaySequence(db, campaignId);
  db.prepare(
    'INSERT INTO play_campaign_replay_events (campaign_id, sequence, event_id, kind, text) VALUES (?, ?, ?, ?, ?)',
  ).run(campaignId, sequence, eventId, kind, text);

  return {
    status: 201,
    body: { event_id: eventId, kind, text, sequence } as unknown as JsonValue,
  };
}

function readReplayState(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'only campaign members may read replay state');
  if (forbidden) return forbidden;

  const rows = db
    .prepare(
      'SELECT sequence, event_id, kind, text FROM play_campaign_replay_events WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as unknown as ReplayEventRow[];

  return { status: 200, body: buildReplayState(rows) };
}

export function getReplayState(authHeader: string | undefined, campaignId: string): ApiResult {
  return readReplayState(authHeader, campaignId);
}

export function checkReplayState(authHeader: string | undefined, campaignId: string): ApiResult {
  return readReplayState(authHeader, campaignId);
}
