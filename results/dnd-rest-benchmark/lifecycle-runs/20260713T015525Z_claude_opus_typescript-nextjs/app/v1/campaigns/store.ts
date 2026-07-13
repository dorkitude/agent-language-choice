import { getDb } from "../db";

export type Campaign = { id: string; name: string; dm: string };
export type Character = { id: string; name: string; level: number; class: string };
export type CampaignEvent = { id: string; kind: string; summary: string };

export function getCampaign(id: string): Campaign | undefined {
  const row = getDb()
    .prepare("SELECT id, name, dm FROM campaigns WHERE id = ?")
    .get(id) as Campaign | undefined;
  return row ?? undefined;
}

export function insertCampaign(c: Campaign): void {
  getDb()
    .prepare("INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)")
    .run(c.id, c.name, c.dm);
}

export function hasCharacter(campaignId: string, id: string): boolean {
  const row = getDb()
    .prepare(
      "SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?"
    )
    .get(campaignId, id);
  return row !== undefined;
}

export function insertCharacter(campaignId: string, c: Character): void {
  const seq = nextSeq("campaign_characters", campaignId);
  getDb()
    .prepare(
      `INSERT INTO campaign_characters (campaign_id, id, name, level, class, seq)
       VALUES (?, ?, ?, ?, ?, ?)`
    )
    .run(campaignId, c.id, c.name, c.level, c.class, seq);
}

export function listCharacters(campaignId: string): Character[] {
  const rows = getDb()
    .prepare(
      `SELECT id, name, level, class FROM campaign_characters
       WHERE campaign_id = ? ORDER BY seq ASC`
    )
    .all(campaignId) as Character[];
  return rows;
}

export function hasEvent(campaignId: string, id: string): boolean {
  const row = getDb()
    .prepare("SELECT 1 FROM campaign_events WHERE campaign_id = ? AND id = ?")
    .get(campaignId, id);
  return row !== undefined;
}

export function insertEvent(campaignId: string, e: CampaignEvent): void {
  const seq = nextSeq("campaign_events", campaignId);
  getDb()
    .prepare(
      `INSERT INTO campaign_events (campaign_id, id, kind, summary, seq)
       VALUES (?, ?, ?, ?, ?)`
    )
    .run(campaignId, e.id, e.kind, e.summary, seq);
}

export function listEvents(campaignId: string): CampaignEvent[] {
  const rows = getDb()
    .prepare(
      `SELECT id, kind, summary FROM campaign_events
       WHERE campaign_id = ? ORDER BY seq ASC`
    )
    .all(campaignId) as CampaignEvent[];
  return rows;
}

export function countEvents(campaignId: string): number {
  const row = getDb()
    .prepare(
      "SELECT COUNT(*) AS n FROM campaign_events WHERE campaign_id = ?"
    )
    .get(campaignId) as { n: number };
  return row.n;
}

function nextSeq(table: string, campaignId: string): number {
  const row = getDb()
    .prepare(
      `SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM ${table} WHERE campaign_id = ?`
    )
    .get(campaignId) as { next: number };
  return row.next;
}
