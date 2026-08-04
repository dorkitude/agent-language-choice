/**
 * Campaign notes with role-filtered privacy. Any campaign member may create
 * a note owned by themselves; the DM can read every note, but players only
 * see `party` notes plus their own `private` notes.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant } from './shared.ts';

interface NoteRow {
  campaign_id: string;
  sequence: number;
  note_id: string;
  text: string;
  visibility: string;
  owner: string;
}

interface NoteObject {
  note_id: string;
  text: string;
  visibility: string;
  owner: string;
}

const VALID_VISIBILITY = new Set(['private', 'party']);

function toNoteObject(row: NoteRow): NoteObject {
  return { note_id: row.note_id, text: row.text, visibility: row.visibility, owner: row.owner };
}

export function createNote(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const record = body as Record<string, unknown>;
  const noteId = record?.note_id;
  if (typeof noteId !== 'string' || noteId.length === 0) {
    return { status: 400, body: { error: 'note_id must be a non-empty string' } };
  }
  const text = record?.text;
  if (typeof text !== 'string' || text.length === 0) {
    return { status: 400, body: { error: 'text must be a non-empty string' } };
  }
  const visibility = record?.visibility;
  if (typeof visibility !== 'string' || !VALID_VISIBILITY.has(visibility)) {
    return { status: 400, body: { error: 'visibility must be "private" or "party"' } };
  }

  const existing = db
    .prepare('SELECT note_id FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?')
    .get(campaignId, noteId);
  if (existing) {
    return { status: 409, body: { error: 'note_id already exists' } };
  }

  const sequenceRow = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_notes WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };

  db.prepare(
    'INSERT INTO play_campaign_notes (campaign_id, sequence, note_id, text, visibility, owner) VALUES (?, ?, ?, ?, ?, ?)',
  ).run(campaignId, sequenceRow.max_sequence + 1, noteId, text, visibility, actor.username);

  return {
    status: 201,
    body: { note_id: noteId, text, visibility, owner: actor.username } as unknown as JsonValue,
  };
}

export function listNotes(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const rows = db
    .prepare(
      'SELECT campaign_id, sequence, note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as unknown as NoteRow[];

  const isDm = campaign.owner === actor.username;
  const items = rows
    .filter((row) => isDm || row.visibility === 'party' || row.owner === actor.username)
    .map(toNoteObject);

  return { status: 200, body: { notes: items } as unknown as JsonValue };
}

export function getNote(authHeader: string | undefined, campaignId: string, noteId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const row = db
    .prepare('SELECT campaign_id, sequence, note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?')
    .get(campaignId, noteId) as NoteRow | undefined;
  if (!row) {
    return { status: 404, body: { error: 'note not found' } };
  }

  const isDm = campaign.owner === actor.username;
  if (row.visibility === 'private' && row.owner !== actor.username && !isDm) {
    return { status: 403, body: { error: 'note is private' } };
  }

  return { status: 200, body: toNoteObject(row) as unknown as JsonValue };
}

export function updateNote(
  authHeader: string | undefined,
  campaignId: string,
  noteId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const row = db
    .prepare('SELECT campaign_id, sequence, note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?')
    .get(campaignId, noteId) as NoteRow | undefined;
  if (!row) {
    return { status: 404, body: { error: 'note not found' } };
  }

  const record = body as Record<string, unknown>;
  const text = record?.text;
  if (typeof text !== 'string' || text.length === 0) {
    return { status: 400, body: { error: 'text must be a non-empty string' } };
  }
  const visibility = record?.visibility;
  if (typeof visibility !== 'string' || !VALID_VISIBILITY.has(visibility)) {
    return { status: 400, body: { error: 'visibility must be "private" or "party"' } };
  }

  if (row.owner !== actor.username) {
    return { status: 403, body: { error: 'only the note owner may update this note' } };
  }

  db.prepare('UPDATE play_campaign_notes SET text = ?, visibility = ? WHERE campaign_id = ? AND note_id = ?').run(
    text,
    visibility,
    campaignId,
    noteId,
  );

  return {
    status: 200,
    body: { note_id: noteId, text, visibility, owner: row.owner } as unknown as JsonValue,
  };
}
