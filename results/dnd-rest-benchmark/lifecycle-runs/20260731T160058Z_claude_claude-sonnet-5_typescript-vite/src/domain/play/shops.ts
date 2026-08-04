/**
 * DM-managed settlement shops with deterministic stock/prices and player
 * buy/sell operations against campaign inventory and currency. See
 * shared.ts for the ownership model and settlements.ts for settlements.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { isValidIntInRange } from '../../validation.ts';
import { VALID_ITEM_IDS } from './inventory.ts';
import {
  authenticate,
  isActor,
  isApiResult,
  findCampaign,
  requireParticipant,
  resolveCharacterOwner,
  findMemberByCharacterId,
} from './shared.ts';
import { findSettlement } from './settlements.ts';

type ShopRow = {
  shop_id: string;
  name: string;
  stock_json: string;
  buy_price: number;
  sell_price: number;
};

function shopBody(row: ShopRow): JsonValue {
  return {
    shop_id: row.shop_id,
    name: row.name,
    stock: JSON.parse(row.stock_json),
    buy_price: row.buy_price,
    sell_price: row.sell_price,
  } as JsonValue;
}

function parseStock(value: unknown): Record<string, number> | ApiResult {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return { status: 400, body: { error: 'stock must be a non-empty object' } };
  }
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0) {
    return { status: 400, body: { error: 'stock must be a non-empty object' } };
  }
  const stock: Record<string, number> = {};
  for (const [itemId, quantity] of entries) {
    if (!VALID_ITEM_IDS.has(itemId)) {
      return { status: 400, body: { error: 'stock keys must be valid catalog item ids' } };
    }
    if (!isValidIntInRange(quantity, 1, Number.MAX_SAFE_INTEGER)) {
      return { status: 400, body: { error: 'stock values must be positive integers' } };
    }
    stock[itemId] = quantity as number;
  }
  return stock;
}

function parseShopFields(
  body: JsonValue,
): { name: string; stock: Record<string, number>; buyPrice: number; sellPrice: number } | ApiResult {
  const name = body.name;
  if (typeof name !== 'string' || name.length === 0) {
    return { status: 400, body: { error: 'name must be a non-empty string' } };
  }

  const stock = parseStock(body.stock);
  if (isApiResult(stock)) return stock;

  if (!isValidIntInRange(body.buy_price, 1, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'buy_price must be a positive integer' } };
  }
  const buyPrice = body.buy_price as number;

  if (!isValidIntInRange(body.sell_price, 0, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'sell_price must be a nonnegative integer' } };
  }
  const sellPrice = body.sell_price as number;

  return { name, stock, buyPrice, sellPrice };
}

function nextShopSequence(db: ReturnType<typeof getDb>, campaignId: string, settlementId: string): number {
  const row = db
    .prepare(
      'SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ?',
    )
    .get(campaignId, settlementId) as { max_sequence: number };
  return row.max_sequence + 1;
}

function findShop(
  db: ReturnType<typeof getDb>,
  campaignId: string,
  settlementId: string,
  shopId: string,
): ShopRow | ApiResult {
  const row = db
    .prepare(
      'SELECT shop_id, name, stock_json, buy_price, sell_price FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?',
    )
    .get(campaignId, settlementId, shopId) as ShopRow | undefined;
  return row ?? { status: 404, body: { error: 'shop not found' } };
}

function hasDiscovered(
  db: ReturnType<typeof getDb>,
  campaignId: string,
  settlementId: string,
  characterId: string,
): boolean {
  return (
    db
      .prepare(
        'SELECT character_id FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?',
      )
      .get(campaignId, settlementId, characterId) !== undefined
  );
}

export function createShop(
  authHeader: string | undefined,
  campaignId: string,
  settlementId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may create shops' } };
  }

  const settlement = findSettlement(db, campaignId, settlementId);
  if (isApiResult(settlement)) return settlement;

  const shopId = body.shop_id;
  if (typeof shopId !== 'string' || shopId.length === 0) {
    return { status: 400, body: { error: 'shop_id must be a non-empty string' } };
  }

  const parsed = parseShopFields(body);
  if (isApiResult(parsed)) return parsed;

  const existing = db
    .prepare('SELECT shop_id FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?')
    .get(campaignId, settlementId, shopId);
  if (existing) {
    return { status: 409, body: { error: 'shop_id already exists in this settlement' } };
  }

  const sequence = nextShopSequence(db, campaignId, settlementId);
  const stockJson = JSON.stringify(parsed.stock);
  db.prepare(
    'INSERT INTO play_campaign_shops (campaign_id, settlement_id, shop_id, sequence, name, stock_json, buy_price, sell_price) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
  ).run(campaignId, settlementId, shopId, sequence, parsed.name, stockJson, parsed.buyPrice, parsed.sellPrice);

  return {
    status: 201,
    body: shopBody({
      shop_id: shopId,
      name: parsed.name,
      stock_json: stockJson,
      buy_price: parsed.buyPrice,
      sell_price: parsed.sellPrice,
    }),
  };
}

export function getShop(
  authHeader: string | undefined,
  campaignId: string,
  settlementId: string,
  shopId: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const settlement = findSettlement(db, campaignId, settlementId);
  if (isApiResult(settlement)) return settlement;

  const shop = findShop(db, campaignId, settlementId, shopId);
  if (isApiResult(shop)) return shop;

  if (campaign.owner === actor.username) {
    return { status: 200, body: shopBody(shop) };
  }

  const memberRow = db
    .prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?')
    .get(campaignId, actor.username) as { character_id: string } | undefined;
  if (!memberRow || !hasDiscovered(db, campaignId, settlementId, memberRow.character_id)) {
    return { status: 404, body: { error: 'shop not found' } };
  }

  return { status: 200, body: shopBody(shop) };
}

function parseTrade(body: JsonValue): { characterId: string; itemId: string; quantity: number } | ApiResult {
  const characterId = body.character_id;
  if (typeof characterId !== 'string' || characterId.length === 0) {
    return { status: 400, body: { error: 'character_id must be a non-empty string' } };
  }

  const itemId = body.item_id;
  if (typeof itemId !== 'string' || !VALID_ITEM_IDS.has(itemId)) {
    return { status: 400, body: { error: 'item_id must be a valid catalog item' } };
  }

  if (!isValidIntInRange(body.quantity, 1, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'quantity must be a positive integer' } };
  }

  return { characterId, itemId, quantity: body.quantity as number };
}

export function buyFromShop(
  authHeader: string | undefined,
  campaignId: string,
  settlementId: string,
  shopId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const settlement = findSettlement(db, campaignId, settlementId);
  if (isApiResult(settlement)) return settlement;

  const shop = findShop(db, campaignId, settlementId, shopId);
  if (isApiResult(shop)) return shop;

  const trade = parseTrade(body);
  if (isApiResult(trade)) return trade;
  const { characterId, itemId, quantity } = trade;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }
  if (owner !== actor.username) {
    return { status: 403, body: { error: 'only the character owner may buy from a shop' } };
  }

  const member = findMemberByCharacterId(db, campaignId, characterId);
  if (isApiResult(member)) return member;

  const stock = JSON.parse(shop.stock_json) as Record<string, number>;
  const heldStock = stock[itemId] ?? 0;
  const cost = shop.buy_price * quantity;

  if (heldStock < quantity || member.gold < cost) {
    return { status: 409, body: { error: 'insufficient stock or funds' } };
  }

  const remainingStock = heldStock - quantity;
  stock[itemId] = remainingStock;
  db.prepare('UPDATE play_campaign_shops SET stock_json = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?').run(
    JSON.stringify(stock),
    campaignId,
    settlementId,
    shopId,
  );

  const remainingGold = member.gold - cost;
  db.prepare('UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?').run(
    remainingGold,
    campaignId,
    characterId,
  );

  const existingStack = db
    .prepare('SELECT quantity FROM play_campaign_inventory_stacks WHERE campaign_id = ? AND character_id = ? AND item_id = ?')
    .get(campaignId, characterId, itemId) as { quantity: number } | undefined;
  const totalQuantity = (existingStack?.quantity ?? 0) + quantity;
  if (existingStack) {
    db.prepare(
      'UPDATE play_campaign_inventory_stacks SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
    ).run(totalQuantity, campaignId, characterId, itemId);
  } else {
    db.prepare(
      'INSERT INTO play_campaign_inventory_stacks (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)',
    ).run(campaignId, characterId, itemId, totalQuantity);
  }

  return {
    status: 200,
    body: { character_id: characterId, item_id: itemId, quantity, gold: remainingGold, stock: remainingStock },
  };
}

export function sellToShop(
  authHeader: string | undefined,
  campaignId: string,
  settlementId: string,
  shopId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const settlement = findSettlement(db, campaignId, settlementId);
  if (isApiResult(settlement)) return settlement;

  const shop = findShop(db, campaignId, settlementId, shopId);
  if (isApiResult(shop)) return shop;

  const trade = parseTrade(body);
  if (isApiResult(trade)) return trade;
  const { characterId, itemId, quantity } = trade;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }
  if (owner !== actor.username) {
    return { status: 403, body: { error: 'only the character owner may sell to a shop' } };
  }

  const member = findMemberByCharacterId(db, campaignId, characterId);
  if (isApiResult(member)) return member;

  const heldItem = db
    .prepare('SELECT quantity FROM play_campaign_inventory_stacks WHERE campaign_id = ? AND character_id = ? AND item_id = ?')
    .get(campaignId, characterId, itemId) as { quantity: number } | undefined;
  const heldQuantity = heldItem?.quantity ?? 0;

  if (heldQuantity < quantity) {
    return { status: 409, body: { error: 'insufficient inventory' } };
  }

  const remainingQuantity = heldQuantity - quantity;
  if (remainingQuantity === 0) {
    db.prepare('DELETE FROM play_campaign_inventory_stacks WHERE campaign_id = ? AND character_id = ? AND item_id = ?').run(
      campaignId,
      characterId,
      itemId,
    );
  } else {
    db.prepare(
      'UPDATE play_campaign_inventory_stacks SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
    ).run(remainingQuantity, campaignId, characterId, itemId);
  }

  const proceeds = shop.sell_price * quantity;
  const totalGold = member.gold + proceeds;
  db.prepare('UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?').run(
    totalGold,
    campaignId,
    characterId,
  );

  const stock = JSON.parse(shop.stock_json) as Record<string, number>;
  const updatedStock = (stock[itemId] ?? 0) + quantity;
  stock[itemId] = updatedStock;
  db.prepare('UPDATE play_campaign_shops SET stock_json = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?').run(
    JSON.stringify(stock),
    campaignId,
    settlementId,
    shopId,
  );

  return {
    status: 200,
    body: { character_id: characterId, item_id: itemId, quantity, gold: totalGold, stock: updatedStock },
  };
}
