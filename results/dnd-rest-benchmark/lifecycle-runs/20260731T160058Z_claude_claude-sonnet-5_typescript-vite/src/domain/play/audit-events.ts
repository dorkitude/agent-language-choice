/**
 * Campaign-scoped actor audit trail for mutating play events. Every entry
 * records the authenticated actor, their role at write time, and a
 * deterministic per-campaign timestamp sequence.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign } from './shared.ts';

interface AuditEventRow {
  timestamp: number;
  kind: string;
  actor: string;
  role: string;
  correlation_id: string;
}

function nextTimestamp(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare('SELECT COALESCE(MAX(timestamp), 0) AS max_timestamp FROM play_campaign_audit_events WHERE campaign_id = ?')
    .get(campaignId) as { max_timestamp: number };
  return row.max_timestamp + 1;
}

function toAuditEntry(row: AuditEventRow): JsonValue {
  return {
    kind: row.kind,
    actor: row.actor,
    role: row.role,
    timestamp: row.timestamp,
    correlation_id: row.correlation_id,
  } as unknown as JsonValue;
}

export function createAuditEvent(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const isOwner = actor.username === campaign.owner;
  const isMemberActor =
    isOwner ||
    db
      .prepare('SELECT username FROM play_campaign_members WHERE campaign_id = ? AND username = ?')
      .get(campaignId, actor.username) !== undefined;
  if (!isMemberActor) {
    return { status: 403, body: { error: 'only campaign members may create audit events' } };
  }

  const kind = body.kind;
  if (typeof kind !== 'string' || kind.length === 0) {
    return { status: 400, body: { error: 'kind must be a non-empty string' } };
  }
  const correlationId = body.correlation_id;
  if (typeof correlationId !== 'string' || correlationId.length === 0) {
    return { status: 400, body: { error: 'correlation_id must be a non-empty string' } };
  }

  const existing = db
    .prepare('SELECT campaign_id FROM play_campaign_audit_events WHERE campaign_id = ? AND correlation_id = ?')
    .get(campaignId, correlationId);
  if (existing) {
    return { status: 409, body: { error: 'correlation_id already used in this campaign' } };
  }

  const role = isOwner ? 'DM' : 'player';
  const timestamp = nextTimestamp(db, campaignId);

  db.prepare(
    'INSERT INTO play_campaign_audit_events (campaign_id, timestamp, kind, actor, role, correlation_id) VALUES (?, ?, ?, ?, ?, ?)',
  ).run(campaignId, timestamp, kind, actor.username, role, correlationId);

  return {
    status: 201,
    body: toAuditEntry({ timestamp, kind, actor: actor.username, role, correlation_id: correlationId }),
  };
}

export function getAuditEvents(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign owner may read the audit trail' } };
  }

  const rows = db
    .prepare(
      'SELECT timestamp, kind, actor, role, correlation_id FROM play_campaign_audit_events WHERE campaign_id = ? ORDER BY timestamp ASC',
    )
    .all(campaignId) as unknown as AuditEventRow[];

  return {
    status: 200,
    body: { entries: rows.map(toAuditEntry) } as unknown as JsonValue,
  };
}
