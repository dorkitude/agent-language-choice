// Party inventory and character equipment persistence.

import { db } from './connection.js';

export function addInventory(campaignId: string, itemSlug: string, quantity: number, owner: string): void {
  const existing = db
    .prepare('SELECT id, quantity FROM inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?')
    .get(campaignId, itemSlug, owner) as { id: number; quantity: number } | undefined;
  if (existing) {
    db.prepare('UPDATE inventory SET quantity = ? WHERE id = ?').run(existing.quantity + quantity, existing.id);
  } else {
    db.prepare('INSERT INTO inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?)').run(
      campaignId,
      itemSlug,
      quantity,
      owner,
    );
  }
}

export function getPartyInventoryQuantity(campaignId: string, itemSlug: string): number {
  const row = db
    .prepare('SELECT quantity FROM inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?')
    .get(campaignId, itemSlug, 'party') as { quantity: number } | undefined;
  return row ? row.quantity : 0;
}

export function decrementPartyInventory(campaignId: string, itemSlug: string, quantity: number): void {
  const existing = db
    .prepare('SELECT id, quantity FROM inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?')
    .get(campaignId, itemSlug, 'party') as { id: number; quantity: number } | undefined;
  if (!existing) return;
  const remaining = existing.quantity - quantity;
  if (remaining > 0) {
    db.prepare('UPDATE inventory SET quantity = ? WHERE id = ?').run(remaining, existing.id);
  } else {
    db.prepare('DELETE FROM inventory WHERE id = ?').run(existing.id);
  }
}

export function countPartyItems(campaignId: string): number {
  const row = db
    .prepare('SELECT COUNT(*) as cnt FROM inventory WHERE campaign_id = ? AND owner = ? AND quantity > 0')
    .get(campaignId, 'party') as { cnt: number } | undefined;
  return row ? row.cnt : 0;
}

export function addEquipment(campaignId: string, characterId: string, itemSlug: string, quantity: number): void {
  const existing = db
    .prepare('SELECT id, quantity FROM equipment WHERE campaign_id = ? AND character_id = ? AND item_slug = ?')
    .get(campaignId, characterId, itemSlug) as { id: number; quantity: number } | undefined;
  if (existing) {
    db.prepare('UPDATE equipment SET quantity = ? WHERE id = ?').run(existing.quantity + quantity, existing.id);
  } else {
    db.prepare('INSERT INTO equipment (campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?)').run(
      campaignId,
      characterId,
      itemSlug,
      quantity,
    );
  }
}

export function countAssignedItems(campaignId: string): number {
  const row = db
    .prepare('SELECT COUNT(*) as cnt FROM equipment WHERE campaign_id = ? AND quantity > 0')
    .get(campaignId) as { cnt: number } | undefined;
  return row ? row.cnt : 0;
}
