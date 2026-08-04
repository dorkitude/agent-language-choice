// Campaign analytics handlers. These endpoints aggregate long-lived campaign
// state into deterministic summary and risk reports.

import type { ServerResponse } from 'node:http';
import { sendError, sendJson } from '../http.js';
import {
  campaignExists,
  countCharactersByCampaign,
  countFriendlyNpcsByCampaign,
  countInventoryItemsByCampaign,
  countQuestsByStatus,
  countSessionsByCampaign,
  getCampaign,
} from '../db.js';

type AnalyticsSignals = {
  has_dm: boolean;
  has_characters: boolean;
  has_next_session: boolean;
  has_active_quest: boolean;
};

function computeSignals(campaignId: string): AnalyticsSignals {
  const campaign = getCampaign(campaignId);
  const activeQuests = countQuestsByStatus(campaignId).active;
  return {
    has_dm: campaign !== undefined && campaign.dm.length > 0,
    has_characters: countCharactersByCampaign(campaignId) > 0,
    has_next_session: countSessionsByCampaign(campaignId) > 0,
    has_active_quest: activeQuests > 0,
  };
}

function computeReadinessScore(signals: AnalyticsSignals): number {
  const trueCount = Object.values(signals).filter(Boolean).length;
  return Math.min(25 + trueCount * 15, 100);
}

function computeRiskLevel(missingSignalCount: number): 'low' | 'medium' | 'high' {
  if (missingSignalCount === 0) return 'low';
  if (missingSignalCount <= 2) return 'medium';
  return 'high';
}

function isValidRiskBody(body: unknown): body is { include_zeroes: boolean } {
  const b = body as Record<string, unknown> | undefined;
  return b !== undefined && typeof b === 'object' && typeof b.include_zeroes === 'boolean';
}

export function handleCampaignAnalyticsSummary(pathname: string, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/analytics\/summary$/);
  if (!match) return false;
  const campaignId = match[1];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const signals = computeSignals(campaignId);
  sendJson(res, 200, {
    campaign_id: campaignId,
    readiness_score: computeReadinessScore(signals),
    open_quests: countQuestsByStatus(campaignId).active,
    friendly_npcs: countFriendlyNpcsByCampaign(campaignId),
    scheduled_sessions: countSessionsByCampaign(campaignId),
    inventory_items: countInventoryItemsByCampaign(campaignId),
  });
  return true;
}

export function handleCampaignRiskReport(pathname: string, body: unknown, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/analytics\/risk-report$/);
  if (!match) return false;
  if (!isValidRiskBody(body)) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  const campaignId = match[1];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const signals = computeSignals(campaignId);
  const missing = new Set<string>();
  for (const [key, value] of Object.entries(signals)) {
    if (!value) missing.add(key);
  }
  const openQuests = countQuestsByStatus(campaignId).active;
  const friendlyNpcs = countFriendlyNpcsByCampaign(campaignId);
  const scheduledSessions = countSessionsByCampaign(campaignId);
  const inventoryItems = countInventoryItemsByCampaign(campaignId);
  if (body.include_zeroes) {
    if (openQuests === 0) missing.add('open_quests');
    if (friendlyNpcs === 0) missing.add('friendly_npcs');
    if (scheduledSessions === 0) missing.add('scheduled_sessions');
    if (inventoryItems === 0) missing.add('inventory_items');
  }
  const missingSignals = Object.values(signals).filter((v) => !v).length;
  sendJson(res, 200, {
    campaign_id: campaignId,
    risk_level: computeRiskLevel(missingSignals),
    missing: Array.from(missing),
    signals,
  });
  return true;
}
