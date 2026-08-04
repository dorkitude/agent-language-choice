/**
 * Per-character inventory item stacks within a play campaign. See shared.ts
 * for the ownership model.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { isValidIntInRange } from '../../validation.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant, resolveCharacterOwner } from './shared.ts';

export const VALID_ITEM_IDS = new Set([
  'healing-potion',
  'torch',
  'leather-armor',
  'ring-of-protection',
  'amulet-of-health',
]);

const VALID_EQUIPMENT_SLOTS = new Set(['armor', 'accessory']);

const ITEM_SLOT_MAP: Record<string, string> = {
  'leather-armor': 'armor',
  'ring-of-protection': 'accessory',
  'amulet-of-health': 'accessory',
};

const ATTUNABLE_ITEM_IDS = new Set(['ring-of-protection', 'amulet-of-health']);

const MAX_ATTUNEMENTS = 1;

const CONSUMABLE_ITEM_IDS = new Set(['healing-potion']);

const CONSUMABLE_EFFECTS: Record<string, JsonValue> = {
  'healing-potion': { type: 'healing', hp_restored: 5 },
};

export function addInventoryStackItem(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }
  if (owner !== actor.username) {
    return { status: 403, body: { error: 'only the character owner may add inventory items' } };
  }

  const itemId = body.item_id;
  if (typeof itemId !== 'string' || !VALID_ITEM_IDS.has(itemId)) {
    return { status: 400, body: { error: 'item_id must be a valid catalog item' } };
  }

  if (!isValidIntInRange(body.quantity, 1, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'quantity must be a positive integer' } };
  }
  const quantity = body.quantity as number;

  const existing = db
    .prepare('SELECT quantity FROM play_campaign_inventory_stacks WHERE campaign_id = ? AND character_id = ? AND item_id = ?')
    .get(campaignId, characterId, itemId) as { quantity: number } | undefined;

  const totalQuantity = (existing?.quantity ?? 0) + quantity;

  if (existing) {
    db.prepare(
      'UPDATE play_campaign_inventory_stacks SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
    ).run(totalQuantity, campaignId, characterId, itemId);
  } else {
    db.prepare(
      'INSERT INTO play_campaign_inventory_stacks (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)',
    ).run(campaignId, characterId, itemId, totalQuantity);
  }

  return {
    status: 201,
    body: { character_id: characterId, item_id: itemId, quantity, total_quantity: totalQuantity },
  };
}

export function listInventoryStackItems(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }

  const rows = db
    .prepare(
      'SELECT item_id, quantity FROM play_campaign_inventory_stacks WHERE campaign_id = ? AND character_id = ? ORDER BY item_id ASC',
    )
    .all(campaignId, characterId) as { item_id: string; quantity: number }[];

  return {
    status: 200,
    body: { character_id: characterId, items: rows.map((row) => ({ item_id: row.item_id, quantity: row.quantity })) },
  };
}

export function removeInventoryStackItem(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  itemId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }
  if (owner !== actor.username) {
    return { status: 403, body: { error: 'only the character owner may remove inventory items' } };
  }

  if (!VALID_ITEM_IDS.has(itemId)) {
    return { status: 400, body: { error: 'item_id must be a valid catalog item' } };
  }

  if (!isValidIntInRange(body.quantity, 1, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'quantity must be a positive integer' } };
  }
  const quantity = body.quantity as number;

  const existing = db
    .prepare('SELECT quantity FROM play_campaign_inventory_stacks WHERE campaign_id = ? AND character_id = ? AND item_id = ?')
    .get(campaignId, characterId, itemId) as { quantity: number } | undefined;
  const heldQuantity = existing?.quantity ?? 0;

  if (quantity > heldQuantity) {
    return { status: 409, body: { error: 'quantity exceeds held stack' } };
  }

  const totalQuantity = heldQuantity - quantity;
  if (totalQuantity === 0) {
    db.prepare('DELETE FROM play_campaign_inventory_stacks WHERE campaign_id = ? AND character_id = ? AND item_id = ?').run(
      campaignId,
      characterId,
      itemId,
    );
  } else {
    db.prepare(
      'UPDATE play_campaign_inventory_stacks SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
    ).run(totalQuantity, campaignId, characterId, itemId);
  }

  return {
    status: 200,
    body: { character_id: characterId, item_id: itemId, quantity, total_quantity: totalQuantity },
  };
}

export function consumeInventoryItem(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  itemId: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }
  if (owner !== actor.username) {
    return { status: 403, body: { error: 'only the character owner may consume inventory items' } };
  }

  if (!VALID_ITEM_IDS.has(itemId) || !CONSUMABLE_ITEM_IDS.has(itemId)) {
    return { status: 400, body: { error: 'item_id must be a valid consumable item' } };
  }

  const existing = db
    .prepare('SELECT quantity FROM play_campaign_inventory_stacks WHERE campaign_id = ? AND character_id = ? AND item_id = ?')
    .get(campaignId, characterId, itemId) as { quantity: number } | undefined;
  const heldQuantity = existing?.quantity ?? 0;

  if (heldQuantity < 1) {
    return { status: 409, body: { error: 'no held stack to consume' } };
  }

  const totalQuantity = heldQuantity - 1;
  if (totalQuantity === 0) {
    db.prepare('DELETE FROM play_campaign_inventory_stacks WHERE campaign_id = ? AND character_id = ? AND item_id = ?').run(
      campaignId,
      characterId,
      itemId,
    );
  } else {
    db.prepare(
      'UPDATE play_campaign_inventory_stacks SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
    ).run(totalQuantity, campaignId, characterId, itemId);
  }

  return {
    status: 200,
    body: {
      character_id: characterId,
      item_id: itemId,
      quantity_consumed: 1,
      total_quantity: totalQuantity,
      effect: CONSUMABLE_EFFECTS[itemId],
    },
  };
}

type EquipmentRow = { item_id: string; attuned: number };

function getEquipmentRow(
  db: ReturnType<typeof getDb>,
  campaignId: string,
  characterId: string,
  slot: string,
): EquipmentRow | undefined {
  return db
    .prepare(
      'SELECT item_id, attuned FROM play_campaign_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?',
    )
    .get(campaignId, characterId, slot) as EquipmentRow | undefined;
}

export function equipItem(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  slot: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }
  if (owner !== actor.username) {
    return { status: 403, body: { error: 'only the character owner may equip items' } };
  }

  if (!VALID_EQUIPMENT_SLOTS.has(slot)) {
    return { status: 400, body: { error: 'slot must be armor or accessory' } };
  }

  const itemId = body.item_id;
  if (typeof itemId !== 'string' || !ITEM_SLOT_MAP[itemId]) {
    return { status: 400, body: { error: 'item_id must be a valid equippable item' } };
  }

  if (ITEM_SLOT_MAP[itemId] !== slot) {
    return { status: 400, body: { error: 'item_id does not match slot' } };
  }

  const held = db
    .prepare('SELECT quantity FROM play_campaign_inventory_stacks WHERE campaign_id = ? AND character_id = ? AND item_id = ?')
    .get(campaignId, characterId, itemId) as { quantity: number } | undefined;
  if (!held || held.quantity < 1) {
    return { status: 400, body: { error: 'item must be held in inventory' } };
  }

  db.prepare(
    `INSERT INTO play_campaign_equipment (campaign_id, character_id, slot, item_id, attuned)
     VALUES (?, ?, ?, ?, 0)
     ON CONFLICT (campaign_id, character_id, slot) DO UPDATE SET item_id = excluded.item_id, attuned = 0`,
  ).run(campaignId, characterId, slot, itemId);

  return {
    status: 200,
    body: { character_id: characterId, slot, item_id: itemId, attuned: false },
  };
}

export function getEquipmentSlot(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  slot: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }

  if (!VALID_EQUIPMENT_SLOTS.has(slot)) {
    return { status: 400, body: { error: 'slot must be armor or accessory' } };
  }

  const row = getEquipmentRow(db, campaignId, characterId, slot);

  return {
    status: 200,
    body: {
      character_id: characterId,
      slot,
      item_id: row?.item_id ?? '',
      attuned: row ? row.attuned === 1 : false,
    },
  };
}

export function attuneEquipmentSlot(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  slot: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }
  if (owner !== actor.username) {
    return { status: 403, body: { error: 'only the character owner may attune items' } };
  }

  if (!VALID_EQUIPMENT_SLOTS.has(slot)) {
    return { status: 400, body: { error: 'slot must be armor or accessory' } };
  }

  const row = getEquipmentRow(db, campaignId, characterId, slot);
  if (!row || !ATTUNABLE_ITEM_IDS.has(row.item_id)) {
    return { status: 400, body: { error: 'slot must contain an equipped attunable item' } };
  }

  if (row.attuned === 1) {
    return { status: 409, body: { error: 'item is already attuned' } };
  }

  const attunedCount = db
    .prepare('SELECT COUNT(*) AS count FROM play_campaign_equipment WHERE campaign_id = ? AND character_id = ? AND attuned = 1')
    .get(campaignId, characterId) as { count: number };
  if (attunedCount.count >= MAX_ATTUNEMENTS) {
    return { status: 409, body: { error: 'maximum attunements reached' } };
  }

  db.prepare(
    'UPDATE play_campaign_equipment SET attuned = 1 WHERE campaign_id = ? AND character_id = ? AND slot = ?',
  ).run(campaignId, characterId, slot);

  return {
    status: 200,
    body: {
      character_id: characterId,
      slot,
      item_id: row.item_id,
      attuned: true,
      attunement_count: attunedCount.count + 1,
      max_attunements: MAX_ATTUNEMENTS,
    },
  };
}
