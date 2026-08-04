// Deterministic audit and export summaries for campaign state. Read-only
// aggregation over existing campaign tables — no new persistent state.
import type { ServerResponse } from "node:http";
import { db, SCHEMA_VERSION } from "../db.js";
import { sendJson } from "../http.js";
import { hasCampaign } from "./campaigns.js";

function countRows(table: string, campaignId: string): number {
  const row = db.prepare(`SELECT COUNT(*) AS count FROM ${table} WHERE campaign_id = ?`).get(campaignId) as {
    count: number;
  };
  return row.count;
}

function countInventoryItems(campaignId: string): number {
  const row = db
    .prepare("SELECT COUNT(*) AS count FROM campaign_inventory WHERE campaign_id = ? AND countable = 1")
    .get(campaignId) as { count: number };
  return row.count;
}

function getCampaignName(campaignId: string): string {
  const row = db.prepare("SELECT name FROM campaigns WHERE id = ?").get(campaignId) as { name: string };
  return row.name;
}

export function handleGetCampaignAudit(res: ServerResponse, campaignId: string): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  sendJson(res, 200, {
    campaign_id: campaignId,
    events: countRows("campaign_events", campaignId),
    quests: countRows("campaign_quests", campaignId),
    npcs: countRows("campaign_npcs", campaignId),
    sessions: countRows("campaign_sessions", campaignId),
  });
}

export function handleExportCampaign(res: ServerResponse, campaignId: string): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  sendJson(res, 200, {
    campaign_id: campaignId,
    name: getCampaignName(campaignId),
    characters: countRows("campaign_characters", campaignId),
    quests: countRows("campaign_quests", campaignId),
    npcs: countRows("campaign_npcs", campaignId),
    inventory_items: countInventoryItems(campaignId),
    sessions: countRows("campaign_sessions", campaignId),
    schema_version: SCHEMA_VERSION,
  });
}
