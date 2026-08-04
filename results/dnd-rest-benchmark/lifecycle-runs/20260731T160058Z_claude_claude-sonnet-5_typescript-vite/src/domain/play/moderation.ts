/**
 * Campaign-scoped moderation reports: any member (including the DM) may
 * submit or read reports; only the DM may resolve one, and only once.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant } from './shared.ts';

type ReportRow = {
  report_id: string;
  target_id: string;
  reason: string;
  status: string;
  reporter: string;
  sequence: number;
  action: string | null;
  note: string | null;
  resolver: string | null;
};

function reportBody(row: ReportRow): JsonValue {
  const body: Record<string, unknown> = {
    report_id: row.report_id,
    target_id: row.target_id,
    reason: row.reason,
    status: row.status,
    reporter: row.reporter,
    sequence: row.sequence,
  };
  if (row.status === 'resolved') {
    body.action = row.action;
    body.note = row.note;
    body.resolver = row.resolver;
  }
  return body as JsonValue;
}

function nextReportSequence(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_moderation_reports WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

export function createModerationReport(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const reportId = body.report_id;
  if (typeof reportId !== 'string' || reportId.length === 0) {
    return { status: 400, body: { error: 'report_id must be a non-empty string' } };
  }

  const targetId = body.target_id;
  if (typeof targetId !== 'string' || targetId.length === 0) {
    return { status: 400, body: { error: 'target_id must be a non-empty string' } };
  }

  const reason = body.reason;
  if (typeof reason !== 'string' || reason.length === 0) {
    return { status: 400, body: { error: 'reason must be a non-empty string' } };
  }

  const existing = db
    .prepare('SELECT report_id FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?')
    .get(campaignId, reportId);
  if (existing) {
    return { status: 409, body: { error: 'report_id already exists in this campaign' } };
  }

  const sequence = nextReportSequence(db, campaignId);
  db.prepare(
    'INSERT INTO play_campaign_moderation_reports (campaign_id, sequence, report_id, target_id, reason, status, reporter) VALUES (?, ?, ?, ?, ?, ?, ?)',
  ).run(campaignId, sequence, reportId, targetId, reason, 'open', actor.username);

  return {
    status: 201,
    body: reportBody({
      report_id: reportId,
      target_id: targetId,
      reason,
      status: 'open',
      reporter: actor.username,
      sequence,
      action: null,
      note: null,
      resolver: null,
    }),
  };
}

export function listModerationReports(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const rows = db
    .prepare(
      'SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM play_campaign_moderation_reports WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as ReportRow[];

  return { status: 200, body: { reports: rows.map((row) => reportBody(row)) } };
}

export function resolveModerationReport(
  authHeader: string | undefined,
  campaignId: string,
  reportId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may resolve reports' } };
  }

  const row = db
    .prepare(
      'SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?',
    )
    .get(campaignId, reportId) as ReportRow | undefined;
  if (!row) {
    return { status: 404, body: { error: 'report not found' } };
  }

  const action = body.action;
  if (action !== 'allow' && action !== 'remove') {
    return { status: 400, body: { error: "action must be exactly 'allow' or 'remove'" } };
  }

  const note = body.note;
  if (typeof note !== 'string' || note.length === 0) {
    return { status: 400, body: { error: 'note must be a non-empty string' } };
  }

  if (row.status === 'resolved') {
    return { status: 409, body: { error: 'report already resolved' } };
  }

  db.prepare(
    "UPDATE play_campaign_moderation_reports SET status = 'resolved', action = ?, note = ?, resolver = ? WHERE campaign_id = ? AND report_id = ?",
  ).run(action, note, actor.username, campaignId, reportId);

  return {
    status: 200,
    body: reportBody({ ...row, status: 'resolved', action, note, resolver: actor.username }),
  };
}
