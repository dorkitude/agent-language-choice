import type { ServerResponse } from 'node:http';
import { sendError, sendJson } from '../http.js';
import {
  addEquipment,
  addInventory,
  campaignExists,
  countAssignedItems,
  countPartyItems,
  decrementPartyInventory,
  getCharacterById,
  getPartyInventoryQuantity,
} from '../db.js';
import { isNonEmptyString, isPositiveInteger } from '../validation.js';

export function handleAddInventoryItem(pathname: string, body: unknown, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/inventory$/);
  if (!match) return false;
  const campaignId = match[1];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const b = body as any;
  if (!b || !isNonEmptyString(b.item_slug) || !isPositiveInteger(b.quantity) || !isNonEmptyString(b.owner)) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  addInventory(campaignId, b.item_slug, b.quantity, b.owner);
  sendJson(res, 201, { item_slug: b.item_slug, quantity: b.quantity, owner: b.owner });
  return true;
}

export function handleAssignEquipment(pathname: string, body: unknown, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/characters\/(.+)\/equipment$/);
  if (!match) return false;
  const campaignId = match[1];
  const characterId = match[2];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const character = getCharacterById(characterId);
  if (!character || character.campaign_id !== campaignId) {
    sendError(res, 404, 'character not found');
    return true;
  }
  const b = body as any;
  if (!b || !isNonEmptyString(b.item_slug) || !isPositiveInteger(b.quantity)) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  const available = getPartyInventoryQuantity(campaignId, b.item_slug);
  if (available < b.quantity) {
    sendError(res, 400, 'insufficient quantity');
    return true;
  }
  decrementPartyInventory(campaignId, b.item_slug, b.quantity);
  addEquipment(campaignId, characterId, b.item_slug, b.quantity);
  sendJson(res, 200, { character_id: characterId, item_slug: b.item_slug, quantity: b.quantity });
  return true;
}

export function handleGetInventorySummary(pathname: string, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/inventory\/summary$/);
  if (!match) return false;
  const campaignId = match[1];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  sendJson(res, 200, {
    campaign_id: campaignId,
    party_items: countPartyItems(campaignId),
    assigned_items: countAssignedItems(campaignId),
    healing_potions_available: getPartyInventoryQuantity(campaignId, 'healing-potion'),
  });
  return true;
}
