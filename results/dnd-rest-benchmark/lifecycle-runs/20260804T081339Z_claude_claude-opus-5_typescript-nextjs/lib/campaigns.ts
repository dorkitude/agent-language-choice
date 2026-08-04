/**
 * Campaign aggregate: the campaign row plus its two owned collections, the
 * character roster and the event log.
 *
 * Rows are keyed by `(campaign_id, id)`, so ids only need to be unique inside
 * their campaign. Both collections carry an explicit `seq` column because
 * SQLite does not promise insertion order without an ORDER BY, and the roster
 * and recap endpoints both depend on that order being stable.
 */
import { database } from "./db";

export type Campaign = {
  id: string;
  name: string;
  dm: string;
};

export type CampaignCharacter = {
  id: string;
  name: string;
  level: number;
  class: string;
};

export type CampaignEvent = {
  id: string;
  kind: string;
  summary: string;
};

export function getCampaign(id: string): Campaign | undefined {
  const row = database()
    .prepare("SELECT id, name, dm FROM campaigns WHERE id = ?")
    .get(id) as Record<string, unknown> | undefined;
  if (!row) return undefined;
  return { id: row.id as string, name: row.name as string, dm: row.dm as string };
}

export function insertCampaign(campaign: Campaign): void {
  database()
    .prepare("INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)")
    .run(campaign.id, campaign.name, campaign.dm);
}

export function getCharacter(
  campaignId: string,
  id: string,
): CampaignCharacter | undefined {
  const row = database()
    .prepare(
      `SELECT id, name, level, class FROM campaign_characters
       WHERE campaign_id = ? AND id = ?`,
    )
    .get(campaignId, id) as Record<string, unknown> | undefined;
  return row ? toCharacter(row) : undefined;
}

export function insertCharacter(
  campaignId: string,
  character: CampaignCharacter,
): void {
  database()
    .prepare(
      `INSERT INTO campaign_characters (campaign_id, id, name, level, class, seq)
       VALUES (?, ?, ?, ?, ?, ?)`,
    )
    .run(
      campaignId,
      character.id,
      character.name,
      character.level,
      character.class,
      nextSeq("campaign_characters", campaignId),
    );
}

export function listCharacters(campaignId: string): CampaignCharacter[] {
  const rows = database()
    .prepare(
      `SELECT id, name, level, class FROM campaign_characters
       WHERE campaign_id = ? ORDER BY seq`,
    )
    .all(campaignId) as Record<string, unknown>[];
  return rows.map(toCharacter);
}

export function getEvent(
  campaignId: string,
  id: string,
): CampaignEvent | undefined {
  const row = database()
    .prepare(
      `SELECT id, kind, summary FROM campaign_events
       WHERE campaign_id = ? AND id = ?`,
    )
    .get(campaignId, id) as Record<string, unknown> | undefined;
  return row ? toEvent(row) : undefined;
}

export function insertEvent(campaignId: string, event: CampaignEvent): void {
  database()
    .prepare(
      `INSERT INTO campaign_events (campaign_id, id, kind, summary, seq)
       VALUES (?, ?, ?, ?, ?)`,
    )
    .run(
      campaignId,
      event.id,
      event.kind,
      event.summary,
      nextSeq("campaign_events", campaignId),
    );
}

export function listEvents(campaignId: string): CampaignEvent[] {
  const rows = database()
    .prepare(
      `SELECT id, kind, summary FROM campaign_events
       WHERE campaign_id = ? ORDER BY seq`,
    )
    .all(campaignId) as Record<string, unknown>[];
  return rows.map(toEvent);
}

export function countEvents(campaignId: string): number {
  const row = database()
    .prepare("SELECT COUNT(*) AS total FROM campaign_events WHERE campaign_id = ?")
    .get(campaignId) as { total: number } | undefined;
  return row ? Number(row.total) : 0;
}

function toCharacter(row: Record<string, unknown>): CampaignCharacter {
  return {
    id: row.id as string,
    name: row.name as string,
    level: Number(row.level),
    class: row.class as string,
  };
}

function toEvent(row: Record<string, unknown>): CampaignEvent {
  return {
    id: row.id as string,
    kind: row.kind as string,
    summary: row.summary as string,
  };
}

/** Characters and log events keep their insertion order per campaign. */
function nextSeq(table: "campaign_characters" | "campaign_events", campaignId: string): number {
  const row = database()
    .prepare(`SELECT COALESCE(MAX(seq), 0) AS top FROM ${table} WHERE campaign_id = ?`)
    .get(campaignId) as { top: number } | undefined;
  return (row ? Number(row.top) : 0) + 1;
}
