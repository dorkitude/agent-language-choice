/**
 * Deterministic campaign analytics: a readiness summary and a maintenance
 * risk report, both aggregated directly from SQLite state accumulated by
 * every earlier stage. Nothing here mutates data.
 */

import { getDb } from '../db.ts';
import type { ApiResult, JsonValue } from '../types.ts';

interface CampaignRow {
  id: string;
  dm: string;
}

interface QuestMilestonesRow {
  milestones_json: string;
  completed_json: string;
}

function countRows(table: string, campaignId: string, extraWhere?: string): number {
  const db = getDb();
  const where = extraWhere ? ` AND ${extraWhere}` : '';
  const row = db.prepare(`SELECT COUNT(*) as count FROM ${table} WHERE campaign_id = ?${where}`).get(campaignId) as {
    count: number;
  };
  return row.count;
}

function questProgressFraction(campaignId: string): number {
  const db = getDb();
  const rows = db
    .prepare('SELECT milestones_json, completed_json FROM campaign_quests WHERE campaign_id = ?')
    .all(campaignId) as unknown as QuestMilestonesRow[];

  let totalMilestones = 0;
  let totalCompleted = 0;
  for (const row of rows) {
    const milestones = JSON.parse(row.milestones_json) as string[];
    const completed = JSON.parse(row.completed_json) as string[];
    totalMilestones += milestones.length;
    totalCompleted += completed.length;
  }

  return totalMilestones === 0 ? 0 : totalCompleted / totalMilestones;
}

interface CampaignSignals {
  hasDm: boolean;
  hasCharacters: boolean;
  hasNextSession: boolean;
  hasActiveQuest: boolean;
  openQuests: number;
  friendlyNpcs: number;
  scheduledSessions: number;
  inventoryItems: number;
}

function loadSignals(campaignId: string, campaign: CampaignRow): CampaignSignals {
  return {
    hasDm: campaign.dm.length > 0,
    hasCharacters: countRows('campaign_characters', campaignId) > 0,
    hasNextSession: countRows('campaign_sessions', campaignId) > 0,
    hasActiveQuest: countRows('campaign_quests', campaignId, "status = 'active'") > 0,
    openQuests: countRows('campaign_quests', campaignId, "status = 'active'"),
    friendlyNpcs: countRows('campaign_npcs', campaignId, 'disposition > 0'),
    scheduledSessions: countRows('campaign_sessions', campaignId),
    inventoryItems: countRows('campaign_inventory', campaignId),
  };
}

export function analyticsSummary(campaignId: string): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id, dm FROM campaigns WHERE id = ?').get(campaignId) as
    | CampaignRow
    | undefined;
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const signals = loadSignals(campaignId, campaign);
  const progressFraction = questProgressFraction(campaignId);

  const readinessScore = Math.round(
    25 * (signals.hasDm ? 1 : 0) +
      25 * (signals.hasCharacters ? 1 : 0) +
      20 * (signals.hasNextSession ? 1 : 0) +
      30 * progressFraction,
  );

  return {
    status: 200,
    body: {
      campaign_id: campaignId,
      readiness_score: readinessScore,
      open_quests: signals.openQuests,
      friendly_npcs: signals.friendlyNpcs,
      scheduled_sessions: signals.scheduledSessions,
      inventory_items: signals.inventoryItems,
    },
  };
}

const RISK_SIGNAL_KEYS = ['has_dm', 'has_characters', 'has_next_session', 'has_active_quest'] as const;

export function analyticsRiskReport(campaignId: string, body: JsonValue): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id, dm FROM campaigns WHERE id = ?').get(campaignId) as
    | CampaignRow
    | undefined;
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const includeZeroes = body.include_zeroes;
  if (includeZeroes !== undefined && typeof includeZeroes !== 'boolean') {
    return { status: 400, body: { error: 'include_zeroes must be a boolean' } };
  }

  const signals = loadSignals(campaignId, campaign);
  const signalValues: Record<(typeof RISK_SIGNAL_KEYS)[number], boolean> = {
    has_dm: signals.hasDm,
    has_characters: signals.hasCharacters,
    has_next_session: signals.hasNextSession,
    has_active_quest: signals.hasActiveQuest,
  };

  const missing: string[] = [];
  for (const key of RISK_SIGNAL_KEYS) {
    if (!signalValues[key]) {
      missing.push(key);
    }
  }

  if (includeZeroes === true) {
    if (signals.friendlyNpcs === 0) missing.push('friendly_npcs');
    if (signals.scheduledSessions === 0) missing.push('scheduled_sessions');
    if (signals.inventoryItems === 0) missing.push('inventory_items');
  }

  const riskLevel = missing.length === 0 ? 'low' : missing.length <= 2 ? 'medium' : 'high';

  return {
    status: 200,
    body: {
      campaign_id: campaignId,
      risk_level: riskLevel,
      missing,
      signals: signalValues,
    },
  };
}
