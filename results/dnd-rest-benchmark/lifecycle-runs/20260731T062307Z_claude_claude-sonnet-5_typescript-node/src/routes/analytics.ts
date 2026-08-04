// Deterministic campaign analytics: a readiness score/summary and a
// maintenance risk report, both aggregated over existing campaign tables.
// Read-only — no new persistent state.
import type { ServerResponse } from "node:http";
import { db } from "../db.js";
import { sendJson } from "../http.js";
import { isPlainObject } from "../validation.js";
import { hasCampaign } from "./campaigns.js";

function countRows(table: string, campaignId: string, extraWhere = ""): number {
  const row = db
    .prepare(`SELECT COUNT(*) AS count FROM ${table} WHERE campaign_id = ?${extraWhere}`)
    .get(campaignId) as { count: number };
  return row.count;
}

function countActiveQuests(campaignId: string): number {
  return countRows("campaign_quests", campaignId, " AND status = 'active'");
}

function countFriendlyNpcs(campaignId: string): number {
  return countRows("campaign_npcs", campaignId, " AND disposition > 0");
}

function countScheduledSessions(campaignId: string): number {
  return countRows("campaign_sessions", campaignId);
}

function countInventoryItems(campaignId: string): number {
  return countRows("campaign_inventory", campaignId, " AND countable = 1");
}

function hasCampaignCharacters(campaignId: string): boolean {
  return countRows("campaign_characters", campaignId) > 0;
}

function getCampaignDm(campaignId: string): string {
  const row = db.prepare("SELECT dm FROM campaigns WHERE id = ?").get(campaignId) as { dm: string };
  return row.dm;
}

function computeReadinessScore(
  openQuests: number,
  friendlyNpcs: number,
  scheduledSessions: number,
  inventoryItems: number,
): number {
  return Math.min(100, 35 + 10 * openQuests + 15 * friendlyNpcs + 20 * scheduledSessions + 5 * inventoryItems);
}

export function handleAnalyticsSummary(res: ServerResponse, campaignId: string): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const openQuests = countActiveQuests(campaignId);
  const friendlyNpcs = countFriendlyNpcs(campaignId);
  const scheduledSessions = countScheduledSessions(campaignId);
  const inventoryItems = countInventoryItems(campaignId);

  sendJson(res, 200, {
    campaign_id: campaignId,
    readiness_score: computeReadinessScore(openQuests, friendlyNpcs, scheduledSessions, inventoryItems),
    open_quests: openQuests,
    friendly_npcs: friendlyNpcs,
    scheduled_sessions: scheduledSessions,
    inventory_items: inventoryItems,
  });
}

export function handleRiskReport(res: ServerResponse, campaignId: string, body: unknown): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!isPlainObject(body) || (body.include_zeroes !== undefined && typeof body.include_zeroes !== "boolean")) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const hasDm = getCampaignDm(campaignId).length > 0;
  const hasCharacters = hasCampaignCharacters(campaignId);
  const hasNextSession = countScheduledSessions(campaignId) > 0;
  const hasActiveQuest = countActiveQuests(campaignId) > 0;

  const missing: string[] = [];
  if (!hasDm) missing.push("dm");
  if (!hasCharacters) missing.push("characters");
  if (!hasNextSession) missing.push("next_session");
  if (!hasActiveQuest) missing.push("active_quest");

  const riskLevel = missing.length === 0 ? "low" : missing.length <= 2 ? "medium" : "high";

  sendJson(res, 200, {
    campaign_id: campaignId,
    risk_level: riskLevel,
    missing,
    signals: {
      has_dm: hasDm,
      has_characters: hasCharacters,
      has_next_session: hasNextSession,
      has_active_quest: hasActiveQuest,
    },
  });
}
