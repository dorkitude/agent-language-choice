import { getDb } from "./db.js";

export interface Campaign {
  id: string;
  name: string;
  dm: string;
}

export interface Character {
  id: string;
  name: string;
  level: number;
  class: string;
}

function validateNonEmptyString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${field} must be a non-empty string`);
  }
  return value;
}

function validateInteger(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`${field} must be an integer`);
  }
  return value;
}

export function createCampaign(input: Record<string, unknown>): Campaign {
  const id = validateNonEmptyString(input.id, "id");
  const name = validateNonEmptyString(input.name, "name");
  const dm = validateNonEmptyString(input.dm, "dm");

  const db = getDb();
  const existing = db
    .prepare("SELECT id FROM campaigns WHERE id = ?")
    .get(id);
  if (existing) {
    throw new Error("campaign id already exists");
  }

  db.prepare(
    "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)"
  ).run(id, name, dm);

  return { id, name, dm };
}

export function addCharacter(
  campaignId: string,
  input: Record<string, unknown>
): Character {
  const id = validateNonEmptyString(input.id, "id");
  const name = validateNonEmptyString(input.name, "name");
  const level = validateInteger(input.level, "level");
  const charClass = validateNonEmptyString(input.class, "class");

  const db = getDb();
  const campaign = db
    .prepare("SELECT id FROM campaigns WHERE id = ?")
    .get(campaignId);
  if (!campaign) {
    throw new Error("campaign not found");
  }

  const existing = db
    .prepare("SELECT id FROM characters WHERE id = ?")
    .get(id);
  if (existing) {
    throw new Error("character id already exists");
  }

  db.prepare(
    "INSERT INTO characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)"
  ).run(id, campaignId, name, level, charClass);

  return { id, name, level, class: charClass };
}

export function addEvent(
  campaignId: string,
  input: Record<string, unknown>
): { id: string; kind: string } {
  const id = validateNonEmptyString(input.id, "id");
  const kind = validateNonEmptyString(input.kind, "kind");
  const summary = validateNonEmptyString(input.summary, "summary");

  const db = getDb();
  const campaign = db
    .prepare("SELECT id FROM campaigns WHERE id = ?")
    .get(campaignId);
  if (!campaign) {
    throw new Error("campaign not found");
  }

  const existing = db.prepare("SELECT id FROM events WHERE id = ?").get(id);
  if (existing) {
    throw new Error("event id already exists");
  }

  db.prepare(
    "INSERT INTO events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)"
  ).run(id, campaignId, kind, summary);

  return { id, kind };
}

export interface Event {
  id: string;
  kind: string;
  summary: string;
}

export function getEvents(campaignId: string): Event[] {
  const db = getDb();
  const campaign = db
    .prepare("SELECT id FROM campaigns WHERE id = ?")
    .get(campaignId);
  if (!campaign) {
    throw new Error("campaign not found");
  }

  const rows = db
    .prepare(
      "SELECT id, kind, summary FROM events WHERE campaign_id = ? ORDER BY id"
    )
    .all(campaignId) as unknown as Event[];

  return rows;
}

export function getCampaignState(campaignId: string): Campaign & {
  characters: Character[];
  log_count: number;
} {
  const db = getDb();
  const campaign = db
    .prepare("SELECT id, name, dm FROM campaigns WHERE id = ?")
    .get(campaignId) as { id: string; name: string; dm: string } | undefined;
  if (!campaign) {
    throw new Error("campaign not found");
  }

  const characters = db
    .prepare(
      "SELECT id, name, level, class FROM characters WHERE campaign_id = ? ORDER BY id"
    )
    .all(campaignId) as unknown as Character[];

  const logCount = db
    .prepare(
      "SELECT COUNT(*) AS count FROM events WHERE campaign_id = ?"
    )
    .get(campaignId) as { count: number };

  return {
    id: campaign.id,
    name: campaign.name,
    dm: campaign.dm,
    characters,
    log_count: logCount.count,
  };
}
