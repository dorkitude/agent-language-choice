/** Campaign session scheduling: scheduling, attendance, and next-session lookup. */

import { getDb } from '../db.ts';
import type { ApiResult, JsonValue } from '../types.ts';
import { isValidIntInRange } from '../validation.ts';

function isIsoTimestamp(value: unknown): value is string {
  if (typeof value !== 'string' || value.length === 0) return false;
  const parsed = Date.parse(value);
  return !Number.isNaN(parsed);
}

interface CampaignSessionRow {
  id: string;
  starts_at: string;
  duration_minutes: number;
  agenda_json: string;
}

export function scheduleSession(campaignId: string, body: JsonValue): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const id = body.id;
  if (typeof id !== 'string' || id.length === 0) {
    return { status: 400, body: { error: 'id must be a non-empty string' } };
  }

  const startsAt = body.starts_at;
  if (!isIsoTimestamp(startsAt)) {
    return { status: 400, body: { error: 'starts_at must be a valid ISO 8601 timestamp' } };
  }

  const durationMinutes = body.duration_minutes;
  if (!isValidIntInRange(durationMinutes, 1, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'duration_minutes must be a positive integer' } };
  }

  const agenda = body.agenda;
  if (!Array.isArray(agenda) || !agenda.every((entry) => typeof entry === 'string')) {
    return { status: 400, body: { error: 'agenda must be an array of strings' } };
  }

  const existing = db
    .prepare('SELECT id FROM campaign_sessions WHERE campaign_id = ? AND id = ?')
    .get(campaignId, id);
  if (existing) {
    return { status: 409, body: { error: 'session id already exists' } };
  }

  db.prepare(
    'INSERT INTO campaign_sessions (campaign_id, id, starts_at, duration_minutes, agenda_json) VALUES (?, ?, ?, ?, ?)',
  ).run(campaignId, id, startsAt as string, durationMinutes as number, JSON.stringify(agenda));

  return {
    status: 201,
    body: {
      id,
      starts_at: startsAt,
      duration_minutes: durationMinutes,
      agenda_count: (agenda as string[]).length,
    },
  };
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === 'string');
}

export function recordAttendance(campaignId: string, sessionId: string, body: JsonValue): ApiResult {
  const db = getDb();
  const session = db
    .prepare('SELECT id FROM campaign_sessions WHERE campaign_id = ? AND id = ?')
    .get(campaignId, sessionId);
  if (!session) {
    return { status: 404, body: { error: 'unknown session id' } };
  }

  const present = body.present;
  if (!isStringArray(present)) {
    return { status: 400, body: { error: 'present must be an array of strings' } };
  }

  const absent = body.absent;
  if (!isStringArray(absent)) {
    return { status: 400, body: { error: 'absent must be an array of strings' } };
  }

  db.prepare(
    `INSERT INTO campaign_session_attendance (campaign_id, session_id, present_json, absent_json)
     VALUES (?, ?, ?, ?)
     ON CONFLICT (campaign_id, session_id) DO UPDATE SET present_json = excluded.present_json, absent_json = excluded.absent_json`,
  ).run(campaignId, sessionId, JSON.stringify(present), JSON.stringify(absent));

  return {
    status: 200,
    body: {
      session_id: sessionId,
      present_count: present.length,
      absent_count: absent.length,
    },
  };
}

export function nextSession(campaignId: string): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const row = db
    .prepare(
      'SELECT id, starts_at, duration_minutes, agenda_json FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at ASC LIMIT 1',
    )
    .get(campaignId) as CampaignSessionRow | undefined;

  if (!row) {
    return { status: 404, body: { error: 'no sessions scheduled' } };
  }

  const agenda = JSON.parse(row.agenda_json) as string[];

  return {
    status: 200,
    body: {
      id: row.id,
      starts_at: row.starts_at,
      agenda_count: agenda.length,
    },
  };
}
