/**
 * Campaign-scoped projection event log. Projection events are appended by
 * player members and the projection is deterministically rebuilt by folding
 * the ordered event log — never stored as mutable derived state.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, isMember, incrementMetric } from './shared.ts';

interface ProjectionEventRow {
  sequence: number;
  event_id: string;
  kind: string;
  value: string | null;
}

function nextSequence(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_projection_events WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

function toEventBody(row: ProjectionEventRow): JsonValue {
  if (row.kind === 'set-story') {
    return { sequence: row.sequence, event_id: row.event_id, kind: row.kind, value: row.value } as unknown as JsonValue;
  }
  return { sequence: row.sequence, event_id: row.event_id, kind: row.kind } as unknown as JsonValue;
}

function buildProjection(rows: ProjectionEventRow[]): JsonValue {
  let story = '';
  let danger = 0;
  const appliedEventIds: string[] = [];
  for (const row of rows) {
    if (row.kind === 'set-story') {
      story = row.value ?? '';
    } else if (row.kind === 'increment-danger') {
      danger += 1;
    }
    appliedEventIds.push(row.event_id);
  }
  return { story, danger, applied_event_ids: appliedEventIds } as unknown as JsonValue;
}

export function createProjectionEvent(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const isOwner = actor.username === campaign.owner;
  if (isOwner) {
    return { status: 403, body: { error: 'the campaign DM may not append projection events' } };
  }
  if (!isMember(db, campaignId, actor.username)) {
    return { status: 403, body: { error: 'only campaign player members may append projection events' } };
  }

  const eventId = body.event_id;
  if (typeof eventId !== 'string' || eventId.length === 0) {
    return { status: 400, body: { error: 'event_id must be a non-empty string' } };
  }

  const kind = body.kind;
  if (kind !== 'set-story' && kind !== 'increment-danger') {
    return { status: 400, body: { error: 'kind must be "set-story" or "increment-danger"' } };
  }

  let value: string | null = null;
  if (kind === 'set-story') {
    if (typeof body.value !== 'string' || body.value.length === 0) {
      return { status: 400, body: { error: 'value must be a non-empty string for set-story events' } };
    }
    value = body.value;
  } else if (body.value !== undefined) {
    return { status: 400, body: { error: 'value must be omitted for increment-danger events' } };
  }

  const existing = db
    .prepare('SELECT campaign_id FROM play_campaign_projection_events WHERE campaign_id = ? AND event_id = ?')
    .get(campaignId, eventId);
  if (existing) {
    return { status: 409, body: { error: 'event_id already used in this campaign' } };
  }

  const sequence = nextSequence(db, campaignId);
  db.prepare(
    'INSERT INTO play_campaign_projection_events (campaign_id, sequence, event_id, kind, value) VALUES (?, ?, ?, ?, ?)',
  ).run(campaignId, sequence, eventId, kind, value);
  incrementMetric(db, campaignId, 'projection_events');

  return { status: 201, body: toEventBody({ sequence, event_id: eventId, kind, value }) };
}

function readProjection(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const isOwner = actor.username === campaign.owner;
  if (!isOwner && !isMember(db, campaignId, actor.username)) {
    return { status: 403, body: { error: 'only the campaign DM or members may read the projection' } };
  }

  const rows = db
    .prepare(
      'SELECT sequence, event_id, kind, value FROM play_campaign_projection_events WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as unknown as ProjectionEventRow[];

  return { status: 200, body: buildProjection(rows) };
}

export function getProjection(authHeader: string | undefined, campaignId: string): ApiResult {
  return readProjection(authHeader, campaignId);
}

export function rebuildProjection(authHeader: string | undefined, campaignId: string): ApiResult {
  return readProjection(authHeader, campaignId);
}
