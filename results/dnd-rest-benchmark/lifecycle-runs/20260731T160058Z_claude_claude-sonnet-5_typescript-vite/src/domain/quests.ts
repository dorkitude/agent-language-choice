/**
 * Campaign quest tracking: create quests with milestones, mark milestones
 * done, and summarize quest counts by status.
 */

import { getDb } from '../db.ts';
import type { ApiResult, JsonValue } from '../types.ts';

const QUEST_STATUSES = new Set(['active', 'completed', 'blocked']);

interface QuestRow {
  id: string;
  title: string;
  status: string;
  milestones_json: string;
  completed_json: string;
}

export function createQuest(campaignId: string, body: JsonValue): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const id = body.id;
  if (typeof id !== 'string' || id.length === 0) {
    return { status: 400, body: { error: 'id must be a non-empty string' } };
  }

  const title = body.title;
  if (typeof title !== 'string' || title.length === 0) {
    return { status: 400, body: { error: 'title must be a non-empty string' } };
  }

  const status = body.status;
  if (typeof status !== 'string' || !QUEST_STATUSES.has(status)) {
    return { status: 400, body: { error: 'status must be one of active, completed, blocked' } };
  }

  const milestones = body.milestones;
  if (
    !Array.isArray(milestones) ||
    milestones.length === 0 ||
    !milestones.every((m) => typeof m === 'string' && m.length > 0)
  ) {
    return { status: 400, body: { error: 'milestones must be a non-empty array of non-empty strings' } };
  }

  const existing = db.prepare('SELECT id FROM campaign_quests WHERE campaign_id = ? AND id = ?').get(campaignId, id);
  if (existing) {
    return { status: 409, body: { error: 'quest id already exists' } };
  }

  db.prepare(
    'INSERT INTO campaign_quests (campaign_id, id, title, status, milestones_json, completed_json) VALUES (?, ?, ?, ?, ?, ?)',
  ).run(campaignId, id, title, status, JSON.stringify(milestones), JSON.stringify([]));

  return {
    status: 201,
    body: {
      id,
      title,
      status,
      milestones_total: milestones.length,
      milestones_done: 0,
    },
  };
}

export function updateQuestProgress(campaignId: string, questId: string, body: JsonValue): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const quest = db
    .prepare('SELECT id, title, status, milestones_json, completed_json FROM campaign_quests WHERE campaign_id = ? AND id = ?')
    .get(campaignId, questId) as QuestRow | undefined;
  if (!quest) {
    return { status: 404, body: { error: 'unknown quest id' } };
  }

  const completedInput = body.completed;
  if (
    !Array.isArray(completedInput) ||
    !completedInput.every((m) => typeof m === 'string' && m.length > 0)
  ) {
    return { status: 400, body: { error: 'completed must be an array of non-empty strings' } };
  }

  const milestones = JSON.parse(quest.milestones_json) as string[];
  for (const m of completedInput as string[]) {
    if (!milestones.includes(m)) {
      return { status: 400, body: { error: `unknown milestone: ${m}` } };
    }
  }

  const completedSet = new Set(JSON.parse(quest.completed_json) as string[]);
  for (const m of completedInput as string[]) {
    completedSet.add(m);
  }

  db.prepare('UPDATE campaign_quests SET completed_json = ? WHERE campaign_id = ? AND id = ?').run(
    JSON.stringify(Array.from(completedSet)),
    campaignId,
    questId,
  );

  return {
    status: 200,
    body: {
      id: quest.id,
      status: quest.status,
      milestones_total: milestones.length,
      milestones_done: completedSet.size,
    },
  };
}

export function questSummary(campaignId: string): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const rows = db
    .prepare('SELECT status FROM campaign_quests WHERE campaign_id = ?')
    .all(campaignId) as unknown as { status: string }[];

  const counts: Record<string, number> = { active: 0, completed: 0, blocked: 0 };
  for (const row of rows) {
    if (counts[row.status] !== undefined) {
      counts[row.status] += 1;
    }
  }

  return {
    status: 200,
    body: {
      campaign_id: campaignId,
      active: counts.active,
      completed: counts.completed,
      blocked: counts.blocked,
    },
  };
}
