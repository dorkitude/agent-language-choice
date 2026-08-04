import { ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import {
  campaignExists,
  countAttendance,
  createSession,
  getNextSession,
  getSession,
  recordAttendance,
  sessionExists,
} from '../repository.js';
import { isNonEmptyString, isPositiveInteger, isStringArray, isValidISOTimestamp } from '../validators.js';
import type { AttendanceRecord, Session } from '../types.js';

export function handleScheduleSession(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { id, starts_at, duration_minutes, agenda } = body as Record<string, unknown>;
  if (
    !isNonEmptyString(id) ||
    !isValidISOTimestamp(starts_at) ||
    !isPositiveInteger(duration_minutes) ||
    !isStringArray(agenda)
  ) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  if (sessionExists(id)) {
    sendJSON(res, 409, { error: 'session already exists' });
    return;
  }

  const session: Session = {
    id,
    campaign_id: params.id,
    starts_at,
    duration_minutes,
    agenda,
  };
  createSession(session);

  sendJSON(res, 201, {
    id: session.id,
    starts_at: session.starts_at,
    duration_minutes: session.duration_minutes,
    agenda_count: session.agenda.length,
  });
}

export function handleRecordAttendance(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const session = getSession(params.session_id);
  if (!session || session.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { present, absent } = body as Record<string, unknown>;
  if (!isStringArray(present) || !isStringArray(absent)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const records: AttendanceRecord[] = [
    ...present.map((character_id) => ({ session_id: session.id, character_id, present: true })),
    ...absent.map((character_id) => ({ session_id: session.id, character_id, present: false })),
  ];
  recordAttendance(session.id, records);
  const counts = countAttendance(session.id);

  sendJSON(res, 200, {
    session_id: session.id,
    present_count: counts.present,
    absent_count: counts.absent,
  });
}

export function handleNextSession(res: ServerResponse, params: Record<string, string>): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const session = getNextSession(params.id);
  if (!session) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  sendJSON(res, 200, {
    id: session.id,
    starts_at: session.starts_at,
    agenda_count: session.agenda.length,
  });
}
