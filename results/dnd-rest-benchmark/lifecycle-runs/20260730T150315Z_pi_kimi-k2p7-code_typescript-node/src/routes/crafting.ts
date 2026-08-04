import { ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import {
  addInventoryItem,
  campaignCharacterInCampaign,
  campaignExists,
  craftingProjectExists,
  createCraftingProject,
  getCraftingProject,
  updateCraftingProject,
} from '../repository.js';
import { isNonEmptyString, isPositiveInteger } from '../validators.js';
import type { CraftingProject } from '../types.js';

export function handleCreateCraftingProject(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { id, character_id, item_slug, days_required, cost_gp } = body as Record<string, unknown>;
  if (
    !isNonEmptyString(id) ||
    !isNonEmptyString(character_id) ||
    !isNonEmptyString(item_slug) ||
    !isPositiveInteger(days_required) ||
    !isPositiveInteger(cost_gp)
  ) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  if (!campaignCharacterInCampaign(character_id, params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  if (craftingProjectExists(id)) {
    sendJSON(res, 409, { error: 'crafting project already exists' });
    return;
  }

  const project: CraftingProject = {
    id,
    campaign_id: params.id,
    character_id,
    item_slug,
    days_required,
    days_completed: 0,
    status: 'active',
    cost_gp,
  };
  createCraftingProject(project);

  sendJSON(res, 201, {
    id,
    character_id,
    item_slug,
    days_required,
    days_completed: 0,
    status: 'active',
  });
}

export function handleAdvanceCraftingProject(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const project = getCraftingProject(params.project_id);
  if (!project || project.campaign_id !== params.id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { days } = body as Record<string, unknown>;
  if (!isPositiveInteger(days)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  if (project.status === 'complete') {
    sendJSON(res, 400, { error: 'project already complete' });
    return;
  }

  const newDaysCompleted = Math.min(project.days_required, project.days_completed + days);
  const becomesComplete = newDaysCompleted >= project.days_required;
  const updatedProject: CraftingProject = {
    ...project,
    days_completed: newDaysCompleted,
    status: becomesComplete ? 'complete' : 'active',
  };
  updateCraftingProject(updatedProject);

  if (becomesComplete) {
    addInventoryItem(params.id, project.item_slug, 1, 'party');
  }

  sendJSON(res, 200, {
    id: project.id,
    days_completed: updatedProject.days_completed,
    status: updatedProject.status,
  });
}
