// NPC persistence.

import { db } from './connection.js';
import type { Npc } from '../types.js';

export function createNpc(npc: Npc): void {
  db.prepare('INSERT INTO npcs (id, campaign_id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)').run(
    npc.id,
    npc.campaign_id,
    npc.name,
    npc.faction_id,
    npc.disposition,
  );
}

export function npcExists(id: string): boolean {
  const row = db.prepare('SELECT 1 FROM npcs WHERE id = ?').get(id) as { '1': number } | undefined;
  return row !== undefined;
}

export function getNpcsByCampaign(campaignId: string): Npc[] {
  return db.prepare('SELECT id, campaign_id, name, faction_id, disposition FROM npcs WHERE campaign_id = ? ORDER BY id').all(
    campaignId,
  ) as Npc[];
}

export function countNpcsByCampaign(campaignId: string): number {
  const row = db.prepare('SELECT COUNT(*) as cnt FROM npcs WHERE campaign_id = ?').get(campaignId) as { cnt: number } | undefined;
  return row ? row.cnt : 0;
}

export function countFriendlyNpcsByCampaign(campaignId: string): number {
  const row = db.prepare('SELECT COUNT(*) as cnt FROM npcs WHERE campaign_id = ? AND disposition > 0').get(campaignId) as
    | { cnt: number }
    | undefined;
  return row ? row.cnt : 0;
}
