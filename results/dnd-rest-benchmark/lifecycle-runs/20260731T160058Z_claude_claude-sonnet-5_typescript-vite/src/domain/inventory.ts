/**
 * Campaign inventory and character equipment assignment. Party stock is
 * tracked separately from per-character assignments; the summary reports
 * remaining healing-potion stock as party quantity minus assigned quantity.
 */

import { getDb } from '../db.ts';
import type { ApiResult, JsonValue } from '../types.ts';
import { isValidIntInRange } from '../validation.ts';

export function addInventoryItem(campaignId: string, body: JsonValue): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const itemSlug = body.item_slug;
  if (typeof itemSlug !== 'string' || itemSlug.length === 0) {
    return { status: 400, body: { error: 'item_slug must be a non-empty string' } };
  }

  const quantity = body.quantity;
  if (!isValidIntInRange(quantity, 1, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'quantity must be a positive integer' } };
  }

  const owner = body.owner;
  if (typeof owner !== 'string' || owner.length === 0) {
    return { status: 400, body: { error: 'owner must be a non-empty string' } };
  }

  db.prepare(
    `INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity)
     VALUES (?, ?, ?, ?)
     ON CONFLICT (campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + excluded.quantity`,
  ).run(campaignId, itemSlug, owner, quantity);

  return { status: 201, body: { item_slug: itemSlug, quantity, owner } };
}

export function assignEquipment(campaignId: string, characterId: string, body: JsonValue): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
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

  const quantity = body.quantity;
  if (!isValidIntInRange(quantity, 1, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'quantity must be a positive integer' } };
  }

  db.prepare(
    `INSERT INTO campaign_equipment (campaign_id, character_id, item_slug, quantity)
     VALUES (?, ?, ?, ?)
     ON CONFLICT (campaign_id, character_id, item_slug) DO UPDATE SET quantity = quantity + excluded.quantity`,
  ).run(campaignId, characterId, itemSlug, quantity);

  return { status: 200, body: { character_id: characterId, item_slug: itemSlug, quantity } };
}

export function inventorySummary(campaignId: string): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const partyItemsRow = db
    .prepare("SELECT COUNT(*) as count FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party'")
    .get(campaignId) as { count: number };

  const assignedItemsRow = db
    .prepare('SELECT COUNT(*) as count FROM campaign_equipment WHERE campaign_id = ?')
    .get(campaignId) as { count: number };

  const partyPotionsRow = db
    .prepare(
      "SELECT COALESCE(SUM(quantity), 0) as total FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party' AND item_slug = 'healing-potion'",
    )
    .get(campaignId) as { total: number };

  const assignedPotionsRow = db
    .prepare(
      "SELECT COALESCE(SUM(quantity), 0) as total FROM campaign_equipment WHERE campaign_id = ? AND item_slug = 'healing-potion'",
    )
    .get(campaignId) as { total: number };

  return {
    status: 200,
    body: {
      campaign_id: campaignId,
      party_items: partyItemsRow.count,
      assigned_items: assignedItemsRow.count,
      healing_potions_available: Math.max(0, partyPotionsRow.total - assignedPotionsRow.total),
    },
  };
}
