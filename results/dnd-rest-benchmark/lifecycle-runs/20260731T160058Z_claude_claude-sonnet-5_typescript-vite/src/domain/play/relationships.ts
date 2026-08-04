/**
 * Directed relationship graph among campaign entities (member characters and
 * NPCs). See shared.ts for the ownership model.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant } from './shared.ts';
import { isValidIntInRange } from '../../validation.ts';

type RelationshipRow = {
  source_id: string;
  target_id: string;
  kind: string;
  score: number;
};

function edgeBody(row: RelationshipRow): JsonValue {
  return { source_id: row.source_id, target_id: row.target_id, kind: row.kind, score: row.score } as unknown as JsonValue;
}

function isCampaignEntity(db: ReturnType<typeof getDb>, campaignId: string, entityId: string): boolean {
  const member = db
    .prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?')
    .get(campaignId, entityId);
  if (member) return true;
  const npc = db
    .prepare('SELECT npc_id FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?')
    .get(campaignId, entityId);
  return npc !== undefined;
}

function nextRelationshipSequence(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_relationships WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

export function createRelationship(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may create relationships' } };
  }

  const sourceId = body.source_id;
  if (typeof sourceId !== 'string' || sourceId.length === 0) {
    return { status: 400, body: { error: 'source_id must be a non-empty string' } };
  }

  const targetId = body.target_id;
  if (typeof targetId !== 'string' || targetId.length === 0) {
    return { status: 400, body: { error: 'target_id must be a non-empty string' } };
  }

  const kind = body.kind;
  if (typeof kind !== 'string' || kind.length === 0) {
    return { status: 400, body: { error: 'kind must be a non-empty string' } };
  }

  if (!isValidIntInRange(body.score, -100, 100)) {
    return { status: 400, body: { error: 'score must be an integer from -100 through 100' } };
  }

  if (sourceId === targetId) {
    return { status: 400, body: { error: 'source_id and target_id must differ' } };
  }

  if (!isCampaignEntity(db, campaignId, sourceId)) {
    return { status: 404, body: { error: 'source_id is not a known campaign entity' } };
  }
  if (!isCampaignEntity(db, campaignId, targetId)) {
    return { status: 404, body: { error: 'target_id is not a known campaign entity' } };
  }

  const existing = db
    .prepare(
      'SELECT source_id FROM play_campaign_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?',
    )
    .get(campaignId, sourceId, targetId, kind);
  if (existing) {
    return { status: 409, body: { error: 'relationship edge already exists' } };
  }

  const score = body.score as number;
  const sequence = nextRelationshipSequence(db, campaignId);
  db.prepare(
    'INSERT INTO play_campaign_relationships (campaign_id, sequence, source_id, target_id, kind, score) VALUES (?, ?, ?, ?, ?, ?)',
  ).run(campaignId, sequence, sourceId, targetId, kind, score);

  return { status: 201, body: edgeBody({ source_id: sourceId, target_id: targetId, kind, score }) };
}

export function updateRelationship(
  authHeader: string | undefined,
  campaignId: string,
  sourceId: string,
  targetId: string,
  kind: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may update relationships' } };
  }

  const row = db
    .prepare(
      'SELECT source_id, target_id, kind, score FROM play_campaign_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?',
    )
    .get(campaignId, sourceId, targetId, kind) as RelationshipRow | undefined;
  if (!row) {
    return { status: 404, body: { error: 'relationship edge not found' } };
  }

  if (!isValidIntInRange(body.score, -100, 100)) {
    return { status: 400, body: { error: 'score must be an integer from -100 through 100' } };
  }

  const score = body.score as number;
  db.prepare(
    'UPDATE play_campaign_relationships SET score = ? WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?',
  ).run(score, campaignId, sourceId, targetId, kind);

  return { status: 200, body: edgeBody({ source_id: sourceId, target_id: targetId, kind, score }) };
}

export function listRelationships(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const rows = db
    .prepare(
      'SELECT source_id, target_id, kind, score FROM play_campaign_relationships WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as RelationshipRow[];

  return { status: 200, body: { edges: rows.map((row) => edgeBody(row)) } };
}
