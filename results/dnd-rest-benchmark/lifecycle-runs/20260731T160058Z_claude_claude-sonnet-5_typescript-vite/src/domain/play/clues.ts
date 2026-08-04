/**
 * Campaign clues the DM may reveal to one character, the whole party, or
 * nobody (hidden). See shared.ts for the ownership model.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant, findMemberByCharacterId } from './shared.ts';

type ClueRow = {
  clue_id: string;
  text: string;
  audience: string;
  character_id: string | null;
};

function clueBody(row: ClueRow): JsonValue {
  const body: Record<string, unknown> = { clue_id: row.clue_id, text: row.text, audience: row.audience };
  if (row.character_id !== null) {
    body.character_id = row.character_id;
  }
  return body as JsonValue;
}

function nextClueSequence(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_clues WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

export function createClue(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may create clues' } };
  }

  const clueId = body.clue_id;
  if (typeof clueId !== 'string' || clueId.length === 0) {
    return { status: 400, body: { error: 'clue_id must be a non-empty string' } };
  }

  const text = body.text;
  if (typeof text !== 'string' || text.length === 0) {
    return { status: 400, body: { error: 'text must be a non-empty string' } };
  }

  const audience = body.audience;
  if (audience !== 'character' && audience !== 'party' && audience !== 'hidden') {
    return { status: 400, body: { error: "audience must be exactly 'character', 'party', or 'hidden'" } };
  }

  let characterId: string | null = null;
  if (audience === 'character') {
    const rawCharacterId = body.character_id;
    if (typeof rawCharacterId !== 'string' || rawCharacterId.length === 0) {
      return { status: 400, body: { error: 'character_id is required for character audience' } };
    }
    const member = findMemberByCharacterId(db, campaignId, rawCharacterId);
    if (isApiResult(member)) {
      return { status: 400, body: { error: 'character_id is not a known campaign member character' } };
    }
    characterId = rawCharacterId;
  } else if (body.character_id !== undefined) {
    return { status: 400, body: { error: 'character_id must be omitted for this audience' } };
  }

  const existing = db
    .prepare('SELECT clue_id FROM play_campaign_clues WHERE campaign_id = ? AND clue_id = ?')
    .get(campaignId, clueId);
  if (existing) {
    return { status: 409, body: { error: 'clue_id already exists in this campaign' } };
  }

  const sequence = nextClueSequence(db, campaignId);
  db.prepare(
    'INSERT INTO play_campaign_clues (campaign_id, sequence, clue_id, text, audience, character_id) VALUES (?, ?, ?, ?, ?, ?)',
  ).run(campaignId, sequence, clueId, text, audience, characterId);

  return { status: 201, body: clueBody({ clue_id: clueId, text, audience, character_id: characterId }) };
}

export function listClues(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const rows = db
    .prepare(
      'SELECT clue_id, text, audience, character_id FROM play_campaign_clues WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as ClueRow[];

  if (actor.username === campaign.owner) {
    return { status: 200, body: { clues: rows.map((row) => clueBody(row)) } };
  }

  const memberRow = db
    .prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?')
    .get(campaignId, actor.username) as { character_id: string } | undefined;
  const ownCharacterId = memberRow ? memberRow.character_id : null;

  const visible = rows.filter(
    (row) => row.audience === 'party' || (row.audience === 'character' && row.character_id === ownCharacterId),
  );

  return { status: 200, body: { clues: visible.map((row) => clueBody(row)) } };
}
