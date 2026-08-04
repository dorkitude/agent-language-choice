// Faction persistence.

import { db } from './connection.js';
import type { Faction } from '../types.js';

export function createFaction(faction: Faction): void {
  db.prepare('INSERT INTO factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)').run(
    faction.id,
    faction.campaign_id,
    faction.name,
    faction.stance,
  );
}

export function factionExists(id: string): boolean {
  const row = db.prepare('SELECT 1 FROM factions WHERE id = ?').get(id) as { '1': number } | undefined;
  return row !== undefined;
}

export function getFaction(id: string): Faction | undefined {
  const row = db.prepare('SELECT id, campaign_id, name, stance FROM factions WHERE id = ?').get(id) as
    | { id: string; campaign_id: string; name: string; stance: string }
    | undefined;
  if (!row) return undefined;
  return row;
}

export function getFactionsByCampaign(campaignId: string): Faction[] {
  return db.prepare('SELECT id, campaign_id, name, stance FROM factions WHERE campaign_id = ? ORDER BY id').all(campaignId) as Faction[];
}

export function countFactionsByCampaign(campaignId: string): number {
  const row = db.prepare('SELECT COUNT(*) as cnt FROM factions WHERE campaign_id = ?').get(campaignId) as { cnt: number } | undefined;
  return row ? row.cnt : 0;
}
