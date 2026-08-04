// Campaign inventory and equipment assignment. Persistent
// (`campaign_inventory`, `campaign_equipment`).
import type { ServerResponse } from "node:http";
import { db } from "../db.js";
import { sendJson } from "../http.js";
import { isPlainObject, isValidInt, SLUG_RE } from "../validation.js";
import { hasCampaign, hasCampaignCharacter } from "./campaigns.js";

export function addInventoryItem(
  campaignId: string,
  itemSlug: string,
  owner: string,
  quantity: number,
  countable = true,
): void {
  db.prepare(
    "INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity, countable) VALUES (?, ?, ?, ?, ?)",
  ).run(campaignId, itemSlug, owner, quantity, countable ? 1 : 0);
}

function addEquipmentAssignment(
  campaignId: string,
  characterId: string,
  itemSlug: string,
  quantity: number,
): void {
  db.prepare(
    "INSERT INTO campaign_equipment (campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?)",
  ).run(campaignId, characterId, itemSlug, quantity);
}

function countInventoryRows(campaignId: string, owner: string): number {
  const row = db
    .prepare(
      "SELECT COUNT(*) AS count FROM campaign_inventory WHERE campaign_id = ? AND owner = ? AND countable = 1",
    )
    .get(campaignId, owner) as { count: number };
  return row.count;
}

function countEquipmentRows(campaignId: string): number {
  const row = db.prepare("SELECT COUNT(*) AS count FROM campaign_equipment WHERE campaign_id = ?").get(
    campaignId,
  ) as { count: number };
  return row.count;
}

function sumInventoryQuantity(campaignId: string, itemSlug: string, owner: string): number {
  const row = db
    .prepare(
      "SELECT COALESCE(SUM(quantity), 0) AS total FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
    )
    .get(campaignId, itemSlug, owner) as { total: number };
  return row.total;
}

function sumEquipmentQuantity(campaignId: string, itemSlug: string): number {
  const row = db
    .prepare(
      "SELECT COALESCE(SUM(quantity), 0) AS total FROM campaign_equipment WHERE campaign_id = ? AND item_slug = ?",
    )
    .get(campaignId, itemSlug) as { total: number };
  return row.total;
}

export function handleAddInventoryItem(res: ServerResponse, campaignId: string, body: unknown): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.item_slug !== "string" ||
    !isValidInt(body.quantity, 1, Number.MAX_SAFE_INTEGER) ||
    typeof body.owner !== "string" ||
    !body.owner
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!SLUG_RE.test(body.item_slug)) {
    sendJson(res, 400, { error: "invalid item_slug" });
    return;
  }

  addInventoryItem(campaignId, body.item_slug, body.owner, body.quantity);

  sendJson(res, 201, { item_slug: body.item_slug, quantity: body.quantity, owner: body.owner });
}

export function handleAssignEquipment(
  res: ServerResponse,
  campaignId: string,
  characterId: string,
  body: unknown,
): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (!hasCampaignCharacter(campaignId, characterId)) {
    sendJson(res, 404, { error: "character not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.item_slug !== "string" ||
    !isValidInt(body.quantity, 1, Number.MAX_SAFE_INTEGER)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!SLUG_RE.test(body.item_slug)) {
    sendJson(res, 400, { error: "invalid item_slug" });
    return;
  }

  addEquipmentAssignment(campaignId, characterId, body.item_slug, body.quantity);

  sendJson(res, 200, { character_id: characterId, item_slug: body.item_slug, quantity: body.quantity });
}

export function handleInventorySummary(res: ServerResponse, campaignId: string): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const partyItems = countInventoryRows(campaignId, "party");
  const assignedItems = countEquipmentRows(campaignId);
  const healingPotionsAvailable =
    sumInventoryQuantity(campaignId, "healing-potion", "party") - sumEquipmentQuantity(campaignId, "healing-potion");

  sendJson(res, 200, {
    campaign_id: campaignId,
    party_items: partyItems,
    assigned_items: assignedItems,
    healing_potions_available: healingPotionsAvailable,
  });
}
