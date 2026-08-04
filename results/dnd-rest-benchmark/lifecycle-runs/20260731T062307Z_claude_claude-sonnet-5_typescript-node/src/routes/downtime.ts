// Downtime crafting projects: create, advance days worked, and deposit the
// finished item into campaign inventory on completion. Persistent
// (`campaign_crafting`).
import type { ServerResponse } from "node:http";
import { db } from "../db.js";
import { sendJson } from "../http.js";
import { isPlainObject, isValidInt, SLUG_RE } from "../validation.js";
import { hasCampaign, hasCampaignCharacter } from "./campaigns.js";
import { addInventoryItem } from "./inventory.js";

interface CraftingRecord {
  campaignId: string;
  id: string;
  characterId: string;
  itemSlug: string;
  daysRequired: number;
  daysCompleted: number;
  costGp: number;
  status: string;
}

function getCraftingProject(campaignId: string, id: string): CraftingRecord | undefined {
  const row = db
    .prepare(
      "SELECT campaign_id, id, character_id, item_slug, days_required, days_completed, cost_gp, status FROM campaign_crafting WHERE campaign_id = ? AND id = ?",
    )
    .get(campaignId, id) as
    | {
        campaign_id: string;
        id: string;
        character_id: string;
        item_slug: string;
        days_required: number;
        days_completed: number;
        cost_gp: number;
        status: string;
      }
    | undefined;
  if (!row) return undefined;
  return {
    campaignId: row.campaign_id,
    id: row.id,
    characterId: row.character_id,
    itemSlug: row.item_slug,
    daysRequired: row.days_required,
    daysCompleted: row.days_completed,
    costGp: row.cost_gp,
    status: row.status,
  };
}

function saveCraftingProject(project: CraftingRecord): void {
  db.prepare(
    "INSERT INTO campaign_crafting (campaign_id, id, character_id, item_slug, days_required, days_completed, cost_gp, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
  ).run(
    project.campaignId,
    project.id,
    project.characterId,
    project.itemSlug,
    project.daysRequired,
    project.daysCompleted,
    project.costGp,
    project.status,
  );
}

function updateCraftingProgress(project: CraftingRecord): void {
  db.prepare("UPDATE campaign_crafting SET days_completed = ?, status = ? WHERE campaign_id = ? AND id = ?").run(
    project.daysCompleted,
    project.status,
    project.campaignId,
    project.id,
  );
}

export function handleCreateCraftingProject(res: ServerResponse, campaignId: string, body: unknown): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.id !== "string" ||
    !body.id ||
    typeof body.character_id !== "string" ||
    !body.character_id ||
    typeof body.item_slug !== "string" ||
    !isValidInt(body.days_required, 1, Number.MAX_SAFE_INTEGER) ||
    !isValidInt(body.cost_gp, 0, Number.MAX_SAFE_INTEGER)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!SLUG_RE.test(body.item_slug)) {
    sendJson(res, 400, { error: "invalid item_slug" });
    return;
  }

  if (!hasCampaignCharacter(campaignId, body.character_id)) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (getCraftingProject(campaignId, body.id)) {
    sendJson(res, 409, { error: "crafting project already exists" });
    return;
  }

  const project: CraftingRecord = {
    campaignId,
    id: body.id,
    characterId: body.character_id,
    itemSlug: body.item_slug,
    daysRequired: body.days_required,
    daysCompleted: 0,
    costGp: body.cost_gp,
    status: "active",
  };
  saveCraftingProject(project);

  sendJson(res, 201, {
    id: project.id,
    character_id: project.characterId,
    item_slug: project.itemSlug,
    days_required: project.daysRequired,
    days_completed: project.daysCompleted,
    status: project.status,
  });
}

export function handleAdvanceCrafting(
  res: ServerResponse,
  campaignId: string,
  projectId: string,
  body: unknown,
): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const project = getCraftingProject(campaignId, projectId);
  if (!project) {
    sendJson(res, 404, { error: "crafting project not found" });
    return;
  }

  if (!isPlainObject(body) || !isValidInt(body.days, 1, Number.MAX_SAFE_INTEGER)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (project.status === "complete") {
    sendJson(res, 409, { error: "crafting project already complete" });
    return;
  }

  project.daysCompleted = Math.min(project.daysCompleted + body.days, project.daysRequired);
  const justCompleted = project.daysCompleted >= project.daysRequired;
  project.status = justCompleted ? "complete" : "active";
  updateCraftingProgress(project);

  if (justCompleted) {
    addInventoryItem(campaignId, project.itemSlug, "party", 1, false);
  }

  sendJson(res, 200, {
    id: project.id,
    days_completed: project.daysCompleted,
    status: project.status,
  });
}
