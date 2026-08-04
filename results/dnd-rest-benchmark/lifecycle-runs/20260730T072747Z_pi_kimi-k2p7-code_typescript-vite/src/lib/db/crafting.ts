// Crafting project persistence.

import { db } from './connection.js';
import type { CraftingProject, CraftingStatus } from '../types.js';

export function createCraftingProject(project: CraftingProject): void {
  db.prepare(
    'INSERT INTO crafting_projects (id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
  ).run(
    project.id,
    project.campaign_id,
    project.character_id,
    project.item_slug,
    project.days_required,
    project.days_completed,
    project.cost_gp,
    project.status,
  );
}

export function getCraftingProject(id: string): CraftingProject | undefined {
  const row = db
    .prepare(
      'SELECT id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status FROM crafting_projects WHERE id = ?',
    )
    .get(id) as
    | { id: string; campaign_id: string; character_id: string; item_slug: string; days_required: number; days_completed: number; cost_gp: number; status: CraftingStatus }
    | undefined;
  if (!row) return undefined;
  return row;
}

export function projectExists(id: string): boolean {
  const row = db.prepare('SELECT 1 FROM crafting_projects WHERE id = ?').get(id) as { '1': number } | undefined;
  return row !== undefined;
}

export function updateCraftingProject(project: CraftingProject): void {
  db.prepare(
    'UPDATE crafting_projects SET days_completed = ?, status = ? WHERE id = ?',
  ).run(project.days_completed, project.status, project.id);
}
