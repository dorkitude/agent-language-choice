// Classic campaign persistence: campaigns, characters, events, and aggregate counts.

import { db } from './connection.js';
import type { Campaign, Character, Event } from '../types.js';

export function createCampaign(campaign: Campaign): void {
  db.prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)').run(campaign.id, campaign.name, campaign.dm);
}

export function getCampaign(id: string): Campaign | undefined {
  const row = db.prepare('SELECT id, name, dm FROM campaigns WHERE id = ?').get(id) as
    | { id: string; name: string; dm: string }
    | undefined;
  if (!row) return undefined;
  return row;
}

export function campaignExists(id: string): boolean {
  const row = db.prepare('SELECT 1 FROM campaigns WHERE id = ?').get(id) as { '1': number } | undefined;
  return row !== undefined;
}

export function createCharacter(character: Character): void {
  db.prepare('INSERT INTO characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)').run(
    character.id,
    character.campaign_id,
    character.name,
    character.level,
    character.class,
  );
}

export function getCharactersByCampaign(campaignId: string): Character[] {
  return db.prepare('SELECT id, campaign_id, name, level, class FROM characters WHERE campaign_id = ?').all(campaignId) as Character[];
}

export function getCharacterById(id: string): Character | undefined {
  const row = db.prepare('SELECT id, campaign_id, name, level, class FROM characters WHERE id = ?').get(id) as
    | { id: string; campaign_id: string; name: string; level: number; class: string }
    | undefined;
  if (!row) return undefined;
  return row;
}

export function characterExists(id: string): boolean {
  const row = db.prepare('SELECT 1 FROM characters WHERE id = ?').get(id) as { '1': number } | undefined;
  return row !== undefined;
}

export function createEvent(event: Event): void {
  db.prepare('INSERT INTO events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)').run(
    event.id,
    event.campaign_id,
    event.kind,
    event.summary,
  );
}

export function getEventsByCampaign(campaignId: string): Event[] {
  return db.prepare('SELECT id, campaign_id, kind, summary FROM events WHERE campaign_id = ? ORDER BY id').all(campaignId) as Event[];
}

export function eventExists(id: string): boolean {
  const row = db.prepare('SELECT 1 FROM events WHERE id = ?').get(id) as { '1': number } | undefined;
  return row !== undefined;
}

export function countEventsByCampaign(campaignId: string): number {
  const row = db.prepare('SELECT COUNT(*) as cnt FROM events WHERE campaign_id = ?').get(campaignId) as { cnt: number } | undefined;
  return row ? row.cnt : 0;
}

export function countCharactersByCampaign(campaignId: string): number {
  const row = db.prepare('SELECT COUNT(*) as cnt FROM characters WHERE campaign_id = ?').get(campaignId) as { cnt: number } | undefined;
  return row ? row.cnt : 0;
}

export function countQuestsByCampaign(campaignId: string): number {
  const row = db.prepare('SELECT COUNT(*) as cnt FROM quests WHERE campaign_id = ?').get(campaignId) as { cnt: number } | undefined;
  return row ? row.cnt : 0;
}

export function countSessionsByCampaign(campaignId: string): number {
  const row = db.prepare('SELECT COUNT(*) as cnt FROM sessions WHERE campaign_id = ?').get(campaignId) as { cnt: number } | undefined;
  return row ? row.cnt : 0;
}

export function countInventoryItemsByCampaign(campaignId: string): number {
  const row = db.prepare('SELECT COUNT(*) as cnt FROM inventory WHERE campaign_id = ? AND quantity > 0').get(campaignId) as
    | { cnt: number }
    | undefined;
  return row ? row.cnt : 0;
}
