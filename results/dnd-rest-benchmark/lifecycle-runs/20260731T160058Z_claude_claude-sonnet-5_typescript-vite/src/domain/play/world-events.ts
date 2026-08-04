/**
 * Deterministic campaign-level world events, scheduled by the DM for a
 * future campaign turn and resolved exactly once when that turn arrives.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant } from './shared.ts';

type WorldEventRow = {
  event_id: string;
  turn_number: number;
  title: string;
  text: string;
  status: string;
  resolution_turn_number: number | null;
  resolution_text: string | null;
};

const WORLD_EVENT_COLUMNS =
  'event_id, turn_number, title, text, status, resolution_turn_number, resolution_text';

function worldEventBody(row: WorldEventRow): JsonValue {
  const body: Record<string, unknown> = {
    event_id: row.event_id,
    turn_number: row.turn_number,
    title: row.title,
    text: row.text,
    status: row.status,
  };
  if (row.status === 'resolved') {
    body.resolution = { turn_number: row.resolution_turn_number, text: row.resolution_text };
  }
  return body as JsonValue;
}

function nextWorldEventSequence(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_world_events WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

export function scheduleWorldEvent(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may schedule world events' } };
  }

  const eventId = body.event_id;
  if (typeof eventId !== 'string' || eventId.length === 0) {
    return { status: 400, body: { error: 'event_id must be a non-empty string' } };
  }
  const title = body.title;
  if (typeof title !== 'string' || title.length === 0) {
    return { status: 400, body: { error: 'title must be a non-empty string' } };
  }
  const text = body.text;
  if (typeof text !== 'string' || text.length === 0) {
    return { status: 400, body: { error: 'text must be a non-empty string' } };
  }
  const turnNumber = body.turn_number;
  const currentTurn = campaign.turn_number ?? 0;
  if (
    typeof turnNumber !== 'number' ||
    !Number.isInteger(turnNumber) ||
    turnNumber < currentTurn
  ) {
    return { status: 400, body: { error: 'turn_number must be an integer at or after the current turn' } };
  }

  const existing = db
    .prepare('SELECT event_id FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?')
    .get(campaignId, eventId);
  if (existing) {
    return { status: 409, body: { error: 'event_id already exists in this campaign' } };
  }

  const sequence = nextWorldEventSequence(db, campaignId);
  db.prepare(
    'INSERT INTO play_campaign_world_events (campaign_id, sequence, event_id, turn_number, title, text, status) VALUES (?, ?, ?, ?, ?, ?, ?)',
  ).run(campaignId, sequence, eventId, turnNumber, title, text, 'scheduled');

  return {
    status: 201,
    body: worldEventBody({
      event_id: eventId,
      turn_number: turnNumber,
      title,
      text,
      status: 'scheduled',
      resolution_turn_number: null,
      resolution_text: null,
    }),
  };
}

export function resolveWorldEvent(
  authHeader: string | undefined,
  campaignId: string,
  eventId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may resolve world events' } };
  }

  const eventRow = db
    .prepare(`SELECT ${WORLD_EVENT_COLUMNS} FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?`)
    .get(campaignId, eventId) as WorldEventRow | undefined;
  if (!eventRow) {
    return { status: 404, body: { error: 'world event not found' } };
  }

  const resolutionText = body.text;
  if (typeof resolutionText !== 'string' || resolutionText.length === 0) {
    return { status: 400, body: { error: 'text must be a non-empty string' } };
  }

  if (eventRow.status === 'resolved') {
    return { status: 409, body: { error: 'world event has already been resolved' } };
  }

  const currentTurn = campaign.turn_number ?? 0;
  if (currentTurn !== eventRow.turn_number) {
    return { status: 409, body: { error: 'campaign turn number does not match the event turn number' } };
  }

  db.prepare(
    'UPDATE play_campaign_world_events SET status = ?, resolution_turn_number = ?, resolution_text = ? WHERE campaign_id = ? AND event_id = ?',
  ).run('resolved', eventRow.turn_number, resolutionText, campaignId, eventId);

  return {
    status: 201,
    body: worldEventBody({
      ...eventRow,
      status: 'resolved',
      resolution_turn_number: eventRow.turn_number,
      resolution_text: resolutionText,
    }),
  };
}

export function listWorldEvents(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const rows = db
    .prepare(
      `SELECT ${WORLD_EVENT_COLUMNS} FROM play_campaign_world_events WHERE campaign_id = ? ORDER BY turn_number ASC, sequence ASC`,
    )
    .all(campaignId) as WorldEventRow[];

  return { status: 200, body: { events: rows.map((row) => worldEventBody(row)) } };
}
