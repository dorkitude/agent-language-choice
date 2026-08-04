// Game session scheduling and attendance persistence.

import { db } from './connection.js';
import type { GameSession } from '../types.js';

export function createSession(session: GameSession): void {
  db.prepare('INSERT INTO sessions (id, campaign_id, starts_at, duration_minutes, agenda) VALUES (?, ?, ?, ?, ?)').run(
    session.id,
    session.campaign_id,
    session.starts_at,
    session.duration_minutes,
    JSON.stringify(session.agenda),
  );
}

export function sessionExists(id: string): boolean {
  const row = db.prepare('SELECT 1 FROM sessions WHERE id = ?').get(id) as { '1': number } | undefined;
  return row !== undefined;
}

export function getSession(id: string): GameSession | undefined {
  const row = db.prepare('SELECT id, campaign_id, starts_at, duration_minutes, agenda FROM sessions WHERE id = ?').get(id) as
    | { id: string; campaign_id: string; starts_at: string; duration_minutes: number; agenda: string }
    | undefined;
  if (!row) return undefined;
  return {
    id: row.id,
    campaign_id: row.campaign_id,
    starts_at: row.starts_at,
    duration_minutes: row.duration_minutes,
    agenda: JSON.parse(row.agenda) as string[],
  };
}

export function getSessionsByCampaign(campaignId: string): GameSession[] {
  const rows = db
    .prepare('SELECT id, campaign_id, starts_at, duration_minutes, agenda FROM sessions WHERE campaign_id = ? ORDER BY starts_at, id')
    .all(campaignId) as {
    id: string;
    campaign_id: string;
    starts_at: string;
    duration_minutes: number;
    agenda: string;
  }[];
  return rows.map((row) => ({
    id: row.id,
    campaign_id: row.campaign_id,
    starts_at: row.starts_at,
    duration_minutes: row.duration_minutes,
    agenda: JSON.parse(row.agenda) as string[],
  }));
}

export function recordAttendance(sessionId: string, present: string[], absent: string[]): void {
  const insert = db.prepare('INSERT OR REPLACE INTO attendance (session_id, character_id, present) VALUES (?, ?, ?)');
  for (const characterId of present) {
    insert.run(sessionId, characterId, 1);
  }
  for (const characterId of absent) {
    insert.run(sessionId, characterId, 0);
  }
}

export function getAttendanceBySession(sessionId: string): { present: string[]; absent: string[] } {
  const rows = db.prepare('SELECT character_id, present FROM attendance WHERE session_id = ?').all(sessionId) as {
    character_id: string;
    present: number;
  }[];
  const present: string[] = [];
  const absent: string[] = [];
  for (const row of rows) {
    if (row.present) {
      present.push(row.character_id);
    } else {
      absent.push(row.character_id);
    }
  }
  return { present, absent };
}
