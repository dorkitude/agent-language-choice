/**
 * Campaign NPCs and factions: create factions, create NPCs (optionally
 * linked to a faction), and summarize relationship counts.
 */

import { getDb } from '../db.ts';
import type { ApiResult, JsonValue } from '../types.ts';
import { isValidIntInRange } from '../validation.ts';

const FACTION_STANCES = new Set(['friendly', 'neutral', 'hostile']);

export function createFaction(campaignId: string, body: JsonValue): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const id = body.id;
  if (typeof id !== 'string' || id.length === 0) {
    return { status: 400, body: { error: 'id must be a non-empty string' } };
  }

  const name = body.name;
  if (typeof name !== 'string' || name.length === 0) {
    return { status: 400, body: { error: 'name must be a non-empty string' } };
  }

  const stance = body.stance;
  if (typeof stance !== 'string' || !FACTION_STANCES.has(stance)) {
    return { status: 400, body: { error: 'stance must be one of friendly, neutral, hostile' } };
  }

  const existing = db.prepare('SELECT id FROM campaign_factions WHERE campaign_id = ? AND id = ?').get(campaignId, id);
  if (existing) {
    return { status: 409, body: { error: 'faction id already exists' } };
  }

  db.prepare('INSERT INTO campaign_factions (campaign_id, id, name, stance) VALUES (?, ?, ?, ?)').run(
    campaignId,
    id,
    name,
    stance,
  );

  return { status: 201, body: { id, name, stance } };
}

export function createNpc(campaignId: string, body: JsonValue): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const id = body.id;
  if (typeof id !== 'string' || id.length === 0) {
    return { status: 400, body: { error: 'id must be a non-empty string' } };
  }

  const name = body.name;
  if (typeof name !== 'string' || name.length === 0) {
    return { status: 400, body: { error: 'name must be a non-empty string' } };
  }

  const factionId = body.faction_id;
  if (factionId !== undefined && factionId !== null && typeof factionId !== 'string') {
    return { status: 400, body: { error: 'faction_id must be a string' } };
  }

  if (typeof factionId === 'string') {
    const faction = db
      .prepare('SELECT id FROM campaign_factions WHERE campaign_id = ? AND id = ?')
      .get(campaignId, factionId);
    if (!faction) {
      return { status: 400, body: { error: 'unknown faction id' } };
    }
  }

  const disposition = body.disposition;
  if (!isValidIntInRange(disposition, -10, 10)) {
    return { status: 400, body: { error: 'disposition must be an integer between -10 and 10' } };
  }

  const existing = db.prepare('SELECT id FROM campaign_npcs WHERE campaign_id = ? AND id = ?').get(campaignId, id);
  if (existing) {
    return { status: 409, body: { error: 'npc id already exists' } };
  }

  db.prepare(
    'INSERT INTO campaign_npcs (campaign_id, id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)',
  ).run(campaignId, id, name, typeof factionId === 'string' ? factionId : null, disposition);

  return {
    status: 201,
    body: { id, name, faction_id: typeof factionId === 'string' ? factionId : null, disposition },
  };
}

export function relationshipSummary(campaignId: string): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const factionCount = db
    .prepare('SELECT COUNT(*) as count FROM campaign_factions WHERE campaign_id = ?')
    .get(campaignId) as unknown as { count: number };

  const npcCount = db
    .prepare('SELECT COUNT(*) as count FROM campaign_npcs WHERE campaign_id = ?')
    .get(campaignId) as unknown as { count: number };

  const friendlyCount = db
    .prepare('SELECT COUNT(*) as count FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0')
    .get(campaignId) as unknown as { count: number };

  return {
    status: 200,
    body: {
      campaign_id: campaignId,
      factions: factionCount.count,
      npcs: npcCount.count,
      friendly_npcs: friendlyCount.count,
    },
  };
}
