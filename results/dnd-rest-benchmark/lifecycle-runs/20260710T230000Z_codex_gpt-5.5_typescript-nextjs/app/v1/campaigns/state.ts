import { db } from "../storage/db.js";

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

function parseCampaign(row: Record<string, unknown> | undefined): Campaign | undefined {
  if (
    row === undefined ||
    typeof row.id !== "string" ||
    typeof row.name !== "string" ||
    typeof row.dm !== "string"
  ) {
    return undefined;
  }

  return {
    id: row.id,
    name: row.name,
    dm: row.dm,
  };
}

function parseCharacter(row: Record<string, unknown>): CampaignCharacter | undefined {
  if (
    typeof row.id !== "string" ||
    typeof row.name !== "string" ||
    typeof row.level !== "number" ||
    typeof row.class !== "string"
  ) {
    return undefined;
  }

  return {
    id: row.id,
    name: row.name,
    level: row.level,
    class: row.class,
  };
}

export const campaigns = {
  get(id: string): Campaign | undefined {
    const row = db().prepare("SELECT id, name, dm FROM campaigns WHERE id = ?").get(id);
    return parseCampaign(row);
  },

  has(id: string): boolean {
    return this.get(id) !== undefined;
  },

  create(campaign: Campaign): void {
    db().prepare("INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)").run(campaign.id, campaign.name, campaign.dm);
  },
};

export const campaignCharacters = {
  has(campaignId: string, id: string): boolean {
    const row = db()
      .prepare("SELECT 1 AS exists_flag FROM campaign_characters WHERE campaign_id = ? AND id = ?")
      .get(campaignId, id);

    return row !== undefined;
  },

  create(campaignId: string, character: CampaignCharacter): void {
    db()
      .prepare(
        `INSERT INTO campaign_characters (id, campaign_id, name, level, class)
         VALUES (?, ?, ?, ?, ?)`,
      )
      .run(character.id, campaignId, character.name, character.level, character.class);
  },

  list(campaignId: string): CampaignCharacter[] {
    const rows = db()
      .prepare("SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid")
      .all(campaignId);

    return rows.flatMap((row) => {
      const character = parseCharacter(row);
      return character === undefined ? [] : [character];
    });
  },
};

export const campaignEvents = {
  has(campaignId: string, id: string): boolean {
    const row = db()
      .prepare("SELECT 1 AS exists_flag FROM campaign_events WHERE campaign_id = ? AND id = ?")
      .get(campaignId, id);

    return row !== undefined;
  },

  create(campaignId: string, event: CampaignEvent): void {
    db()
      .prepare(
        `INSERT INTO campaign_events (id, campaign_id, kind, summary)
         VALUES (?, ?, ?, ?)`,
      )
      .run(event.id, campaignId, event.kind, event.summary);
  },

  count(campaignId: string): number {
    const row = db().prepare("SELECT COUNT(*) AS log_count FROM campaign_events WHERE campaign_id = ?").get(campaignId);
    if (row === undefined || typeof row.log_count !== "number") {
      return 0;
    }

    return row.log_count;
  },

  latestSummary(campaignId: string): string | undefined {
    const row = db()
      .prepare("SELECT summary FROM campaign_events WHERE campaign_id = ? ORDER BY rowid DESC LIMIT 1")
      .get(campaignId);

    if (row === undefined || typeof row.summary !== "string") {
      return undefined;
    }

    return row.summary;
  },
};

export function isValidId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

export function isValidText(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

export function isValidLevel(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}
