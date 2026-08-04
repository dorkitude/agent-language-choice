/**
 * Character-to-character whispers. A sender must be a campaign player with
 * an owned character; the DM can read every whisper, but players only see
 * whispers where their owned character is the sender or the recipient.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import {
  authenticate,
  isActor,
  isApiResult,
  findCampaign,
  requireParticipant,
  findMemberByCharacterId,
  resolveOwnedCharacterId,
} from './shared.ts';

interface WhisperRow {
  campaign_id: string;
  sequence: number;
  whisper_id: string;
  from_character_id: string;
  to_character_id: string;
  text: string;
}

interface WhisperObject {
  whisper_id: string;
  from_character_id: string;
  to_character_id: string;
  text: string;
}

function toWhisperObject(row: WhisperRow): WhisperObject {
  return {
    whisper_id: row.whisper_id,
    from_character_id: row.from_character_id,
    to_character_id: row.to_character_id,
    text: row.text,
  };
}

export function createWhisper(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const fromCharacterId = resolveOwnedCharacterId(db, campaignId, actor.username);
  if (!fromCharacterId) {
    return { status: 403, body: { error: 'only a player with an owned character may send whispers' } };
  }

  const record = body as Record<string, unknown>;
  const whisperId = record?.whisper_id;
  if (typeof whisperId !== 'string' || whisperId.length === 0) {
    return { status: 400, body: { error: 'whisper_id must be a non-empty string' } };
  }
  const toCharacterId = record?.to_character_id;
  if (typeof toCharacterId !== 'string' || toCharacterId.length === 0) {
    return { status: 400, body: { error: 'to_character_id must be a non-empty string' } };
  }
  const text = record?.text;
  if (typeof text !== 'string' || text.length === 0) {
    return { status: 400, body: { error: 'text must be a non-empty string' } };
  }

  const recipientMember = findMemberByCharacterId(db, campaignId, toCharacterId);
  if (isApiResult(recipientMember)) {
    return { status: 400, body: { error: 'to_character_id must belong to a current campaign member' } };
  }

  const existing = db
    .prepare('SELECT whisper_id FROM play_campaign_whispers WHERE campaign_id = ? AND whisper_id = ?')
    .get(campaignId, whisperId);
  if (existing) {
    return { status: 409, body: { error: 'whisper_id already exists' } };
  }

  const sequenceRow = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_whispers WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };

  db.prepare(
    'INSERT INTO play_campaign_whispers (campaign_id, sequence, whisper_id, from_character_id, to_character_id, text) VALUES (?, ?, ?, ?, ?, ?)',
  ).run(campaignId, sequenceRow.max_sequence + 1, whisperId, fromCharacterId, toCharacterId, text);

  return {
    status: 201,
    body: {
      whisper_id: whisperId,
      from_character_id: fromCharacterId,
      to_character_id: toCharacterId,
      text,
    } as unknown as JsonValue,
  };
}

export function listWhispers(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const rows = db
    .prepare(
      'SELECT campaign_id, sequence, whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as unknown as WhisperRow[];

  const isDm = campaign.owner === actor.username;
  const ownedCharacterId = isDm ? null : resolveOwnedCharacterId(db, campaignId, actor.username);

  const items = rows
    .filter(
      (row) =>
        isDm || (ownedCharacterId !== null && (row.from_character_id === ownedCharacterId || row.to_character_id === ownedCharacterId)),
    )
    .map(toWhisperObject);

  return { status: 200, body: { whispers: items } as unknown as JsonValue };
}
