/**
 * Downtime crafting projects: characters spend days advancing a crafting
 * project toward completion. When a project completes, the crafted item is
 * added to the campaign's party inventory.
 */

import { getDb } from '../db.ts';
import type { ApiResult, JsonValue } from '../types.ts';
import { isValidIntInRange } from '../validation.ts';

interface CraftingProjectRow {
  id: string;
  character_id: string;
  item_slug: string;
  days_required: number;
  days_completed: number;
  status: string;
}

export function createCraftingProject(campaignId: string, body: JsonValue): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const id = body.id;
  if (typeof id !== 'string' || id.length === 0) {
    return { status: 400, body: { error: 'id must be a non-empty string' } };
  }

  const characterId = body.character_id;
  if (typeof characterId !== 'string' || characterId.length === 0) {
    return { status: 400, body: { error: 'character_id must be a non-empty string' } };
  }

  const character = db
    .prepare('SELECT id FROM campaign_characters WHERE campaign_id = ? AND id = ?')
    .get(campaignId, characterId);
  if (!character) {
    return { status: 404, body: { error: 'unknown character id' } };
  }

  const itemSlug = body.item_slug;
  if (typeof itemSlug !== 'string' || itemSlug.length === 0) {
    return { status: 400, body: { error: 'item_slug must be a non-empty string' } };
  }

  const daysRequired = body.days_required;
  if (!isValidIntInRange(daysRequired, 1, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'days_required must be a positive integer' } };
  }

  const costGp = body.cost_gp;
  if (typeof costGp !== 'number' || !Number.isFinite(costGp) || costGp < 0) {
    return { status: 400, body: { error: 'cost_gp must be a non-negative number' } };
  }

  const existing = db
    .prepare('SELECT id FROM campaign_crafting_projects WHERE campaign_id = ? AND id = ?')
    .get(campaignId, id);
  if (existing) {
    return { status: 409, body: { error: 'crafting project id already exists' } };
  }

  db.prepare(
    `INSERT INTO campaign_crafting_projects
       (campaign_id, id, character_id, item_slug, days_required, days_completed, cost_gp, status)
     VALUES (?, ?, ?, ?, ?, 0, ?, 'active')`,
  ).run(campaignId, id, characterId, itemSlug, daysRequired, costGp);

  return {
    status: 201,
    body: {
      id,
      character_id: characterId,
      item_slug: itemSlug,
      days_required: daysRequired,
      days_completed: 0,
      status: 'active',
    },
  };
}

export function advanceCrafting(campaignId: string, projectId: string, body: JsonValue): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const project = db
    .prepare(
      'SELECT id, character_id, item_slug, days_required, days_completed, status FROM campaign_crafting_projects WHERE campaign_id = ? AND id = ?',
    )
    .get(campaignId, projectId) as CraftingProjectRow | undefined;
  if (!project) {
    return { status: 404, body: { error: 'unknown crafting project id' } };
  }

  const days = body.days;
  if (!isValidIntInRange(days, 1, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'days must be a positive integer' } };
  }

  if (project.status === 'complete') {
    return { status: 409, body: { error: 'crafting project is already complete' } };
  }

  const daysCompleted = Math.min(project.days_required, project.days_completed + days);
  const status = daysCompleted >= project.days_required ? 'complete' : 'active';

  db.prepare(
    'UPDATE campaign_crafting_projects SET days_completed = ?, status = ? WHERE campaign_id = ? AND id = ?',
  ).run(daysCompleted, status, campaignId, projectId);

  if (status === 'complete' && project.status !== 'complete') {
    db.prepare(
      `INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity)
       VALUES (?, ?, 'party', 1)
       ON CONFLICT (campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + excluded.quantity`,
    ).run(campaignId, project.item_slug);
  }

  return {
    status: 200,
    body: {
      id: project.id,
      days_completed: daysCompleted,
      status,
    },
  };
}
