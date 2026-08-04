/**
 * Campaign-scoped safety boundaries and safety checks: only the DM may
 * replace the blocked-tags list, any campaign member (including the DM) may
 * read boundaries, submit safety checks, or read accepted safety events.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant } from './shared.ts';

function parseTagArray(value: unknown, field: string): string[] | ApiResult {
  if (!Array.isArray(value) || value.length === 0) {
    return { status: 400, body: { error: `${field} must be a nonempty array of unique nonempty strings` } };
  }
  const seen = new Set<string>();
  for (const entry of value) {
    if (typeof entry !== 'string' || entry.length === 0) {
      return { status: 400, body: { error: `${field} must be a nonempty array of unique nonempty strings` } };
    }
    if (seen.has(entry)) {
      return { status: 400, body: { error: `${field} must be a nonempty array of unique nonempty strings` } };
    }
    seen.add(entry);
  }
  return value as string[];
}

function getBoundaryRow(db: ReturnType<typeof getDb>, campaignId: string): string[] {
  const row = db
    .prepare('SELECT blocked_tags_json FROM play_campaign_safety_boundaries WHERE campaign_id = ?')
    .get(campaignId) as { blocked_tags_json: string } | undefined;
  if (!row) return [];
  return JSON.parse(row.blocked_tags_json) as string[];
}

export function replaceSafetyBoundaries(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may replace safety boundaries' } };
  }

  const parsed = parseTagArray(body.blocked_tags, 'blocked_tags');
  if (isApiResult(parsed)) return parsed;

  const sorted = parsed.slice().sort();
  db.prepare(
    'INSERT INTO play_campaign_safety_boundaries (campaign_id, blocked_tags_json) VALUES (?, ?) ' +
      'ON CONFLICT(campaign_id) DO UPDATE SET blocked_tags_json = excluded.blocked_tags_json',
  ).run(campaignId, JSON.stringify(sorted));

  return { status: 200, body: { blocked_tags: sorted } };
}

export function getSafetyBoundaries(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  return { status: 200, body: { blocked_tags: getBoundaryRow(db, campaignId) } };
}

function nextSafetyEventSequence(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_safety_events WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

export function submitSafetyCheck(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
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
  if (kind !== 'narration' && kind !== 'chat') {
    return { status: 400, body: { error: "kind must be exactly 'narration' or 'chat'" } };
  }

  const tags = parseTagArray(body.tags, 'tags');
  if (isApiResult(tags)) return tags;

  const existing = db
    .prepare('SELECT event_id FROM play_campaign_safety_events WHERE campaign_id = ? AND event_id = ?')
    .get(campaignId, eventId);
  if (existing) {
    return { status: 409, body: { error: 'event_id already accepted in this campaign' } };
  }

  const blockedTags = new Set(getBoundaryRow(db, campaignId));
  if (tags.some((tag) => blockedTags.has(tag))) {
    return { status: 409, body: { error: 'submitted tags include a blocked tag' } };
  }

  const sequence = nextSafetyEventSequence(db, campaignId);
  db.prepare(
    'INSERT INTO play_campaign_safety_events (campaign_id, sequence, event_id, kind, text, tags_json) VALUES (?, ?, ?, ?, ?, ?)',
  ).run(campaignId, sequence, eventId, kind, text, JSON.stringify(tags));

  return {
    status: 201,
    body: { event_id: eventId, kind, text, tags, sequence },
  };
}

export function listSafetyEvents(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const rows = db
    .prepare(
      'SELECT event_id, kind, text, tags_json, sequence FROM play_campaign_safety_events WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as { event_id: string; kind: string; text: string; tags_json: string; sequence: number }[];

  return {
    status: 200,
    body: {
      events: rows.map((row) => ({
        event_id: row.event_id,
        kind: row.kind,
        text: row.text,
        tags: JSON.parse(row.tags_json) as string[],
        sequence: row.sequence,
      })),
    },
  };
}
