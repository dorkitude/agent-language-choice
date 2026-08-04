// Session scheduling handlers for campaigns.

import type { ServerResponse } from 'node:http';
import { sendError, sendJson } from '../http.js';
import { campaignExists, createSession, getSession, getSessionsByCampaign, recordAttendance, sessionExists } from '../db.js';
import { isNonEmptyString, isPositiveInteger, isStringArray } from '../validation.js';
import type { GameSession } from '../types.js';

export function handleScheduleSession(pathname: string, body: unknown, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/sessions$/);
  if (!match) return false;
  const campaignId = match[1];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const b = body as any;
  if (
    !b ||
    !isNonEmptyString(b.id) ||
    !isNonEmptyString(b.starts_at) ||
    !isPositiveInteger(b.duration_minutes) ||
    !isStringArray(b.agenda)
  ) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  if (sessionExists(b.id)) {
    sendError(res, 409, 'session already exists');
    return true;
  }
  const session: GameSession = {
    id: b.id,
    campaign_id: campaignId,
    starts_at: b.starts_at,
    duration_minutes: b.duration_minutes,
    agenda: b.agenda,
  };
  createSession(session);
  sendJson(res, 201, {
    id: session.id,
    starts_at: session.starts_at,
    duration_minutes: session.duration_minutes,
    agenda_count: session.agenda.length,
  });
  return true;
}

export function handleRecordAttendance(pathname: string, body: unknown, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/sessions\/(.+)\/attendance$/);
  if (!match) return false;
  const campaignId = match[1];
  const sessionId = match[2];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const session = getSession(sessionId);
  if (!session || session.campaign_id !== campaignId) {
    sendError(res, 404, 'session not found');
    return true;
  }
  const b = body as any;
  if (!b || !isStringArray(b.present) || !isStringArray(b.absent)) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  recordAttendance(sessionId, b.present, b.absent);
  sendJson(res, 200, {
    session_id: sessionId,
    present_count: b.present.length,
    absent_count: b.absent.length,
  });
  return true;
}

export function handleGetNextSession(pathname: string, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/sessions\/next$/);
  if (!match) return false;
  const campaignId = match[1];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const sessions = getSessionsByCampaign(campaignId);
  if (sessions.length === 0) {
    sendError(res, 404, 'no sessions scheduled');
    return true;
  }
  const next = sessions[0];
  sendJson(res, 200, {
    id: next.id,
    starts_at: next.starts_at,
    agenda_count: next.agenda.length,
  });
  return true;
}
