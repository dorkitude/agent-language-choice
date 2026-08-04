/**
 * Per-identity rate-limited campaign events. Each campaign member has a
 * fixed allowance of accepted events per campaign; the DM and members may
 * create and list them.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant, incrementMetric } from './shared.ts';

interface RateEventRow {
  sequence: number;
  event_id: string;
  actor: string;
}

const RATE_LIMIT = 2;

export function createRateEvent(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
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

  const existing = db
    .prepare('SELECT event_id FROM play_campaign_rate_events WHERE campaign_id = ? AND event_id = ?')
    .get(campaignId, eventId);
  if (existing) {
    return { status: 400, body: { error: 'event_id already exists' } };
  }

  const usedRow = db
    .prepare('SELECT COUNT(*) AS used FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?')
    .get(campaignId, actor.username) as { used: number };
  const remaining = RATE_LIMIT - usedRow.used;
  if (remaining <= 0) {
    incrementMetric(db, campaignId, 'rejected_rate_events');
    return { status: 429, body: { limit: RATE_LIMIT, remaining: 0 } as unknown as JsonValue };
  }

  const sequenceRow = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_rate_events WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };

  db.prepare(
    'INSERT INTO play_campaign_rate_events (campaign_id, sequence, event_id, actor) VALUES (?, ?, ?, ?)',
  ).run(campaignId, sequenceRow.max_sequence + 1, eventId, actor.username);
  incrementMetric(db, campaignId, 'accepted_rate_events');

  return {
    status: 201,
    body: { event_id: eventId, actor: actor.username, remaining: remaining - 1 } as unknown as JsonValue,
  };
}

export function listRateEvents(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const rows = db
    .prepare(
      'SELECT sequence, event_id, actor FROM play_campaign_rate_events WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as unknown as RateEventRow[];

  const usedRow = db
    .prepare('SELECT COUNT(*) AS used FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?')
    .get(campaignId, actor.username) as { used: number };
  const remaining = RATE_LIMIT - usedRow.used;

  return {
    status: 200,
    body: {
      events: rows.map((row) => ({ event_id: row.event_id, actor: row.actor })),
      remaining,
    } as unknown as JsonValue,
  };
}
