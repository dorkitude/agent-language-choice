// Quest persistence and status aggregation.

import { db } from './connection.js';
import type { Quest, QuestStatus } from '../types.js';

export function createQuest(quest: Quest): void {
  db.prepare('INSERT INTO quests (id, campaign_id, title, status, milestones, completed) VALUES (?, ?, ?, ?, ?, ?)').run(
    quest.id,
    quest.campaign_id,
    quest.title,
    quest.status,
    JSON.stringify(quest.milestones),
    JSON.stringify(quest.completed),
  );
}

export function getQuest(id: string): Quest | undefined {
  const row = db.prepare('SELECT id, campaign_id, title, status, milestones, completed FROM quests WHERE id = ?').get(id) as
    | { id: string; campaign_id: string; title: string; status: QuestStatus; milestones: string; completed: string }
    | undefined;
  if (!row) return undefined;
  return {
    id: row.id,
    campaign_id: row.campaign_id,
    title: row.title,
    status: row.status,
    milestones: JSON.parse(row.milestones) as string[],
    completed: JSON.parse(row.completed) as string[],
  };
}

export function questExists(id: string): boolean {
  const row = db.prepare('SELECT 1 FROM quests WHERE id = ?').get(id) as { '1': number } | undefined;
  return row !== undefined;
}

export function updateQuest(quest: Quest): void {
  db.prepare('UPDATE quests SET title = ?, status = ?, milestones = ?, completed = ? WHERE id = ?').run(
    quest.title,
    quest.status,
    JSON.stringify(quest.milestones),
    JSON.stringify(quest.completed),
    quest.id,
  );
}

export function getQuestsByCampaign(campaignId: string): Quest[] {
  const rows = db
    .prepare('SELECT id, campaign_id, title, status, milestones, completed FROM quests WHERE campaign_id = ? ORDER BY id')
    .all(campaignId) as {
    id: string;
    campaign_id: string;
    title: string;
    status: QuestStatus;
    milestones: string;
    completed: string;
  }[];
  return rows.map((row) => ({
    id: row.id,
    campaign_id: row.campaign_id,
    title: row.title,
    status: row.status,
    milestones: JSON.parse(row.milestones) as string[],
    completed: JSON.parse(row.completed) as string[],
  }));
}

export function countQuestsByStatus(campaignId: string): Record<QuestStatus, number> {
  const rows = db.prepare('SELECT status, COUNT(*) as cnt FROM quests WHERE campaign_id = ? GROUP BY status').all(campaignId) as {
    status: QuestStatus;
    cnt: number;
  }[];
  const result: Record<QuestStatus, number> = { active: 0, completed: 0, blocked: 0 };
  for (const row of rows) {
    result[row.status] = row.cnt;
  }
  return result;
}
