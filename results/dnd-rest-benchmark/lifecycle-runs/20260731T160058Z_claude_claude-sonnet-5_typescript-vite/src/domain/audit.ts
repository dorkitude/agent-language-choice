/**
 * Deterministic audit log and export summary for campaign state. Both
 * endpoints report counts derived directly from SQLite; no data is mutated.
 */

import { getDb } from '../db.ts';
import { SCHEMA_VERSION } from '../db.ts';
import type { ApiResult } from '../types.ts';

interface CampaignRow {
  id: string;
  name: string;
}

function countRows(table: string, campaignId: string): number {
  const db = getDb();
  const row = db.prepare(`SELECT COUNT(*) as count FROM ${table} WHERE campaign_id = ?`).get(campaignId) as {
    count: number;
  };
  return row.count;
}

export function campaignAudit(campaignId: string): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId) as CampaignRow | undefined;
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  return {
    status: 200,
    body: {
      campaign_id: campaignId,
      events: countRows('campaign_events', campaignId),
      quests: countRows('campaign_quests', campaignId),
      npcs: countRows('campaign_npcs', campaignId),
      sessions: countRows('campaign_sessions', campaignId),
    },
  };
}

export function campaignExport(campaignId: string): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id, name FROM campaigns WHERE id = ?').get(campaignId) as
    | CampaignRow
    | undefined;
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  return {
    status: 200,
    body: {
      campaign_id: campaign.id,
      name: campaign.name,
      characters: countRows('campaign_characters', campaignId),
      quests: countRows('campaign_quests', campaignId),
      npcs: countRows('campaign_npcs', campaignId),
      inventory_items: countRows('campaign_inventory', campaignId),
      sessions: countRows('campaign_sessions', campaignId),
      schema_version: SCHEMA_VERSION,
    },
  };
}
