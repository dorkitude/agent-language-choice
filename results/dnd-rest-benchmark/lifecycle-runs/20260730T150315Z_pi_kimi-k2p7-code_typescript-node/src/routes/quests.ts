import { ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import {
  campaignExists,
  createQuest,
  getQuest,
  questExists,
  updateQuest,
  countQuestsByStatus,
} from '../repository.js';
import { isNonEmptyString, isStringArray, isValidQuestStatus } from '../validators.js';
import type { Quest } from '../types.js';

export function handleCreateQuest(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { id, title, status, milestones } = body as Record<string, unknown>;
  if (
    !isNonEmptyString(id) ||
    !isNonEmptyString(title) ||
    !isValidQuestStatus(status) ||
    !isStringArray(milestones)
  ) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  if (questExists(id)) {
    sendJSON(res, 409, { error: 'quest already exists' });
    return;
  }

  const quest: Quest = {
    id,
    campaign_id: params.id,
    title,
    status,
    milestones,
    done_milestones: [],
  };
  createQuest(quest);
  sendJSON(res, 201, {
    id: quest.id,
    title: quest.title,
    status: quest.status,
    milestones_total: quest.milestones.length,
    milestones_done: 0,
  });
}

export function handleUpdateQuestProgress(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const quest = getQuest(params.quest_id);
  if (!quest || quest.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { completed } = body as Record<string, unknown>;
  if (!isStringArray(completed)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const milestoneSet = new Set(quest.milestones);
  const doneSet = new Set(quest.done_milestones);
  for (const name of completed) {
    if (milestoneSet.has(name)) {
      doneSet.add(name);
    }
  }
  quest.done_milestones = Array.from(doneSet);
  updateQuest(quest);

  sendJSON(res, 200, {
    id: quest.id,
    status: quest.status,
    milestones_total: quest.milestones.length,
    milestones_done: quest.done_milestones.length,
  });
}

export function handleQuestSummary(res: ServerResponse, params: Record<string, string>): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }
  const counts = countQuestsByStatus(params.id);
  sendJSON(res, 200, {
    campaign_id: params.id,
    active: counts.active,
    completed: counts.completed,
    blocked: counts.blocked,
  });
}
