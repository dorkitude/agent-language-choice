import type { ServerResponse } from 'node:http';
import { sendError, sendJson } from '../http.js';
import { campaignExists, createQuest, getQuest, getQuestsByCampaign, questExists, updateQuest } from '../db.js';
import { isNonEmptyString, isQuestStatus, isStringArray } from '../validation.js';
import type { Quest, QuestStatus } from '../types.js';

function milestonesDone(quest: Quest): number {
  const valid = new Set(quest.milestones);
  const unique = new Set<string>();
  for (const m of quest.completed) {
    if (valid.has(m)) unique.add(m);
  }
  return unique.size;
}

export function handleCreateQuest(pathname: string, body: unknown, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/quests$/);
  if (!match) return false;
  const campaignId = match[1];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const b = body as any;
  if (!b || !isNonEmptyString(b.id) || !isNonEmptyString(b.title) || !isQuestStatus(b.status) || !isStringArray(b.milestones)) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  if (questExists(b.id)) {
    sendError(res, 409, 'quest already exists');
    return true;
  }
  const quest: Quest = {
    id: b.id,
    campaign_id: campaignId,
    title: b.title,
    status: b.status as QuestStatus,
    milestones: b.milestones,
    completed: [],
  };
  createQuest(quest);
  sendJson(res, 201, {
    id: quest.id,
    title: quest.title,
    status: quest.status,
    milestones_total: quest.milestones.length,
    milestones_done: 0,
  });
  return true;
}

export function handleUpdateQuestProgress(pathname: string, body: unknown, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/quests\/(.+)\/progress$/);
  if (!match) return false;
  const campaignId = match[1];
  const questId = match[2];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const quest = getQuest(questId);
  if (!quest || quest.campaign_id !== campaignId) {
    sendError(res, 404, 'quest not found');
    return true;
  }
  const b = body as any;
  if (!b || !isStringArray(b.completed)) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  const completed = b.completed as string[];
  const valid = new Set(quest.milestones);
  const merged = new Set(quest.completed);
  for (const m of completed) {
    if (valid.has(m)) merged.add(m);
  }
  quest.completed = Array.from(merged);
  if (quest.completed.length >= quest.milestones.length && quest.milestones.length > 0) {
    quest.status = 'completed';
  }
  updateQuest(quest);
  const done = milestonesDone(quest);
  sendJson(res, 200, {
    id: quest.id,
    status: quest.status,
    milestones_total: quest.milestones.length,
    milestones_done: done,
  });
  return true;
}

export function handleGetQuestSummary(pathname: string, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/quests\/summary$/);
  if (!match) return false;
  const campaignId = match[1];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const counts: Record<QuestStatus, number> = { active: 0, completed: 0, blocked: 0 };
  for (const quest of getQuestsByCampaign(campaignId)) {
    counts[quest.status]++;
  }
  sendJson(res, 200, {
    campaign_id: campaignId,
    active: counts.active,
    completed: counts.completed,
    blocked: counts.blocked,
  });
  return true;
}
