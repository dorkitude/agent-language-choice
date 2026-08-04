// Campaign quest tracking: create quests, record milestone progress, and
// summarize quest counts by status. Persistent (`campaign_quests`).
import type { ServerResponse } from "node:http";
import { db } from "../db.js";
import { sendJson } from "../http.js";
import { isPlainObject } from "../validation.js";
import { hasCampaign } from "./campaigns.js";

const VALID_STATUSES = new Set(["active", "completed", "blocked"]);

interface QuestRecord {
  campaignId: string;
  id: string;
  title: string;
  status: string;
  milestones: string[];
  milestonesDone: string[];
}

function getQuest(campaignId: string, id: string): QuestRecord | undefined {
  const row = db
    .prepare("SELECT campaign_id, id, title, status, milestones, milestones_done FROM campaign_quests WHERE campaign_id = ? AND id = ?")
    .get(campaignId, id) as
    | { campaign_id: string; id: string; title: string; status: string; milestones: string; milestones_done: string }
    | undefined;
  if (!row) return undefined;
  return {
    campaignId: row.campaign_id,
    id: row.id,
    title: row.title,
    status: row.status,
    milestones: JSON.parse(row.milestones) as string[],
    milestonesDone: JSON.parse(row.milestones_done) as string[],
  };
}

function saveQuest(quest: QuestRecord): void {
  db.prepare(
    "INSERT INTO campaign_quests (campaign_id, id, title, status, milestones, milestones_done) VALUES (?, ?, ?, ?, ?, ?)",
  ).run(
    quest.campaignId,
    quest.id,
    quest.title,
    quest.status,
    JSON.stringify(quest.milestones),
    JSON.stringify(quest.milestonesDone),
  );
}

function updateQuestProgress(quest: QuestRecord): void {
  db.prepare("UPDATE campaign_quests SET milestones_done = ? WHERE campaign_id = ? AND id = ?").run(
    JSON.stringify(quest.milestonesDone),
    quest.campaignId,
    quest.id,
  );
}

function getCampaignQuests(campaignId: string): QuestRecord[] {
  const rows = db
    .prepare("SELECT campaign_id, id, title, status, milestones, milestones_done FROM campaign_quests WHERE campaign_id = ?")
    .all(campaignId) as { campaign_id: string; id: string; title: string; status: string; milestones: string; milestones_done: string }[];
  return rows.map((row) => ({
    campaignId: row.campaign_id,
    id: row.id,
    title: row.title,
    status: row.status,
    milestones: JSON.parse(row.milestones) as string[],
    milestonesDone: JSON.parse(row.milestones_done) as string[],
  }));
}

export function handleCreateQuest(res: ServerResponse, campaignId: string, body: unknown): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.id !== "string" ||
    !body.id ||
    typeof body.title !== "string" ||
    typeof body.status !== "string" ||
    !VALID_STATUSES.has(body.status) ||
    !Array.isArray(body.milestones) ||
    !body.milestones.every((m) => typeof m === "string")
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (getQuest(campaignId, body.id)) {
    sendJson(res, 409, { error: "quest already exists" });
    return;
  }

  const quest: QuestRecord = {
    campaignId,
    id: body.id,
    title: body.title,
    status: body.status,
    milestones: body.milestones as string[],
    milestonesDone: [],
  };
  saveQuest(quest);

  sendJson(res, 201, {
    id: quest.id,
    title: quest.title,
    status: quest.status,
    milestones_total: quest.milestones.length,
    milestones_done: quest.milestonesDone.length,
  });
}

export function handleUpdateQuestProgress(
  res: ServerResponse,
  campaignId: string,
  questId: string,
  body: unknown,
): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const quest = getQuest(campaignId, questId);
  if (!quest) {
    sendJson(res, 404, { error: "quest not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    !Array.isArray(body.completed) ||
    !body.completed.every((m) => typeof m === "string") ||
    !(body.completed as string[]).every((m) => quest.milestones.includes(m))
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const done = new Set(quest.milestonesDone);
  for (const milestone of body.completed as string[]) {
    done.add(milestone);
  }
  quest.milestonesDone = quest.milestones.filter((m) => done.has(m));
  updateQuestProgress(quest);

  sendJson(res, 200, {
    id: quest.id,
    status: quest.status,
    milestones_total: quest.milestones.length,
    milestones_done: quest.milestonesDone.length,
  });
}

export function handleQuestSummary(res: ServerResponse, campaignId: string): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const quests = getCampaignQuests(campaignId);
  const summary = { active: 0, completed: 0, blocked: 0 };
  for (const quest of quests) {
    if (quest.status === "active") summary.active += 1;
    else if (quest.status === "completed") summary.completed += 1;
    else if (quest.status === "blocked") summary.blocked += 1;
  }

  sendJson(res, 200, {
    campaign_id: campaignId,
    active: summary.active,
    completed: summary.completed,
    blocked: summary.blocked,
  });
}
