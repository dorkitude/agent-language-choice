import type { ServerResponse } from 'node:http';
import { sendError, sendJson } from '../http.js';
import {
  addInventory,
  campaignExists,
  createCraftingProject,
  getCharacterById,
  getCraftingProject,
  projectExists,
  updateCraftingProject,
} from '../db.js';
import { isNonEmptyString, isPositiveInteger } from '../validation.js';
import type { CraftingProject } from '../types.js';

export function handleCreateCraftingProject(pathname: string, body: unknown, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/downtime\/crafting$/);
  if (!match) return false;
  const campaignId = match[1];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const b = body as any;
  if (
    !b ||
    !isNonEmptyString(b.id) ||
    !isNonEmptyString(b.character_id) ||
    !isNonEmptyString(b.item_slug) ||
    !isPositiveInteger(b.days_required) ||
    !isPositiveInteger(b.cost_gp)
  ) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  if (projectExists(b.id)) {
    sendError(res, 409, 'project already exists');
    return true;
  }
  const character = getCharacterById(b.character_id);
  if (!character || character.campaign_id !== campaignId) {
    sendError(res, 404, 'character not found');
    return true;
  }
  const project: CraftingProject = {
    id: b.id,
    campaign_id: campaignId,
    character_id: b.character_id,
    item_slug: b.item_slug,
    days_required: b.days_required,
    days_completed: 0,
    cost_gp: b.cost_gp,
    status: 'active',
  };
  createCraftingProject(project);
  sendJson(res, 201, {
    id: project.id,
    character_id: project.character_id,
    item_slug: project.item_slug,
    days_required: project.days_required,
    days_completed: project.days_completed,
    status: project.status,
  });
  return true;
}

export function handleAdvanceCraftingProject(pathname: string, body: unknown, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/downtime\/crafting\/(.+)\/advance$/);
  if (!match) return false;
  const campaignId = match[1];
  const projectId = match[2];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const project = getCraftingProject(projectId);
  if (!project || project.campaign_id !== campaignId) {
    sendError(res, 404, 'project not found');
    return true;
  }
  const b = body as any;
  if (!b || !isPositiveInteger(b.days)) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  const days = b.days as number;
  const wasComplete = project.status === 'complete';
  const completed = Math.min(project.days_completed + days, project.days_required);
  const status: 'active' | 'complete' = completed >= project.days_required ? 'complete' : 'active';
  project.days_completed = completed;
  project.status = status;
  updateCraftingProject(project);
  if (status === 'complete' && !wasComplete) {
    addInventory(campaignId, project.item_slug, 1, 'party');
  }
  sendJson(res, 200, { id: project.id, days_completed: project.days_completed, status: project.status });
  return true;
}
