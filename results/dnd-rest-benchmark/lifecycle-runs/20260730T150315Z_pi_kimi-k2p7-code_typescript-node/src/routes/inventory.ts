import { ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import {
  addCharacterEquipment,
  addInventoryItem,
  campaignCharacterInCampaign,
  campaignExists,
  countEquipmentRows,
  countInventoryRows,
  decrementInventory,
  getPartyInventoryItem,
  sumInventoryQuantity,
} from '../repository.js';
import { isNonEmptyString, isPositiveInteger } from '../validators.js';

export function handleAddInventoryItem(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { item_slug, quantity, owner } = body as Record<string, unknown>;
  if (!isNonEmptyString(item_slug) || !isPositiveInteger(quantity) || !isNonEmptyString(owner)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  addInventoryItem(params.id, item_slug, quantity, owner);
  sendJSON(res, 201, { item_slug, quantity, owner });
}

export function handleAssignEquipment(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }
  if (!campaignCharacterInCampaign(params.character_id, params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { item_slug, quantity } = body as Record<string, unknown>;
  if (!isNonEmptyString(item_slug) || !isPositiveInteger(quantity)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const partyItem = getPartyInventoryItem(params.id, item_slug);
  if (!partyItem || partyItem.quantity < quantity) {
    sendJSON(res, 400, { error: 'insufficient quantity' });
    return;
  }

  decrementInventory(params.id, item_slug, 'party', quantity);
  addCharacterEquipment(params.id, params.character_id, item_slug, quantity);
  sendJSON(res, 200, { character_id: params.character_id, item_slug, quantity });
}

export function handleInventorySummary(
  res: ServerResponse,
  params: Record<string, string>,
): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  sendJSON(res, 200, {
    campaign_id: params.id,
    party_items: countInventoryRows(params.id),
    assigned_items: countEquipmentRows(params.id),
    healing_potions_available: sumInventoryQuantity(params.id, 'healing-potion', 'party'),
  });
}
