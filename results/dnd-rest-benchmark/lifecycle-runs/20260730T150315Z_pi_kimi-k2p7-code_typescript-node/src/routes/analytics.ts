import { ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import {
  campaignExists,
  countActiveQuests,
  countCampaignCharacters,
  countCampaignSessions,
  countFriendlyNPCs,
  countInventoryRows,
  getCampaign,
  getNextSession,
} from '../repository.js';

type RiskSignal = 'dm' | 'characters' | 'next_session' | 'active_quest';

function computeReadinessScore(
  openQuests: number,
  friendlyNPCs: number,
  scheduledSessions: number,
  inventoryItems: number,
): number {
  // Base score (DM + campaign presence) plus weighted bonuses for each
  // content category. Capped at 100.
  return Math.min(
    100,
    35 + 10 * openQuests + 15 * friendlyNPCs + 20 * scheduledSessions + 5 * inventoryItems,
  );
}

export function handleAnalyticsSummary(
  res: ServerResponse,
  params: Record<string, string>,
): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const openQuests = countActiveQuests(params.id);
  const friendlyNPCs = countFriendlyNPCs(params.id);
  const scheduledSessions = countCampaignSessions(params.id);
  const inventoryItems = countInventoryRows(params.id);

  sendJSON(res, 200, {
    campaign_id: params.id,
    readiness_score: computeReadinessScore(openQuests, friendlyNPCs, scheduledSessions, inventoryItems),
    open_quests: openQuests,
    friendly_npcs: friendlyNPCs,
    scheduled_sessions: scheduledSessions,
    inventory_items: inventoryItems,
  });
}

export function handleRiskReport(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const campaign = getCampaign(params.id);
  const hasDM = campaign !== null && campaign.dm.length > 0;
  const hasCharacters = countCampaignCharacters(params.id) > 0;
  const hasNextSession = getNextSession(params.id) !== null;
  const hasActiveQuest = countActiveQuests(params.id) > 0;

  const signals = {
    has_dm: hasDM,
    has_characters: hasCharacters,
    has_next_session: hasNextSession,
    has_active_quest: hasActiveQuest,
  };

  const missing: RiskSignal[] = [];
  if (!hasDM) missing.push('dm');
  if (!hasCharacters) missing.push('characters');
  if (!hasNextSession) missing.push('next_session');
  if (!hasActiveQuest) missing.push('active_quest');

  const riskLevel = missing.length === 0 ? 'low' : missing.length <= 2 ? 'medium' : 'high';

  sendJSON(res, 200, {
    campaign_id: params.id,
    risk_level: riskLevel,
    missing,
    signals,
  });
}
