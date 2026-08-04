// Campaigns and their nested characters/events. `hasCampaign` is also used
// by routes/dm.ts, since every DM tool operates within a campaign.
import type { ServerResponse } from "node:http";
import { db } from "../db.js";
import { sendJson } from "../http.js";
import { isPlainObject, isValidInt } from "../validation.js";

interface CampaignRecord {
  id: string;
  name: string;
  dm: string;
}

interface CampaignCharacterRecord {
  campaignId: string;
  id: string;
  name: string;
  level: number;
  class: string;
}

interface CampaignEventRecord {
  campaignId: string;
  id: string;
  kind: string;
  summary: string;
}

export function hasCampaign(id: string): boolean {
  const row = db.prepare("SELECT 1 FROM campaigns WHERE id = ?").get(id);
  return row !== undefined;
}

function getCampaign(id: string): CampaignRecord | undefined {
  const row = db.prepare("SELECT id, name, dm FROM campaigns WHERE id = ?").get(id) as
    | { id: string; name: string; dm: string }
    | undefined;
  if (!row) return undefined;
  return { id: row.id, name: row.name, dm: row.dm };
}

function saveCampaign(campaign: CampaignRecord): void {
  db.prepare("INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)").run(campaign.id, campaign.name, campaign.dm);
}

export function hasCampaignCharacter(campaignId: string, id: string): boolean {
  const row = db.prepare("SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?").get(campaignId, id);
  return row !== undefined;
}

function saveCampaignCharacter(character: CampaignCharacterRecord): void {
  db.prepare(
    "INSERT INTO campaign_characters (campaign_id, id, name, level, class) VALUES (?, ?, ?, ?, ?)",
  ).run(character.campaignId, character.id, character.name, character.level, character.class);
}

function getCampaignCharacters(campaignId: string): CampaignCharacterRecord[] {
  const rows = db
    .prepare("SELECT campaign_id, id, name, level, class FROM campaign_characters WHERE campaign_id = ?")
    .all(campaignId) as { campaign_id: string; id: string; name: string; level: number; class: string }[];
  return rows.map((row) => ({
    campaignId: row.campaign_id,
    id: row.id,
    name: row.name,
    level: row.level,
    class: row.class,
  }));
}

function hasCampaignEvent(campaignId: string, id: string): boolean {
  const row = db.prepare("SELECT 1 FROM campaign_events WHERE campaign_id = ? AND id = ?").get(campaignId, id);
  return row !== undefined;
}

function saveCampaignEvent(event: CampaignEventRecord): void {
  db.prepare("INSERT INTO campaign_events (campaign_id, id, kind, summary) VALUES (?, ?, ?, ?)").run(
    event.campaignId,
    event.id,
    event.kind,
    event.summary,
  );
}

function countCampaignEvents(campaignId: string): number {
  const row = db.prepare("SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?").get(campaignId) as {
    count: number;
  };
  return row.count;
}

export function handleCreateCampaign(res: ServerResponse, body: unknown): void {
  if (
    !isPlainObject(body) ||
    typeof body.id !== "string" ||
    !body.id ||
    typeof body.name !== "string" ||
    typeof body.dm !== "string"
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (hasCampaign(body.id)) {
    sendJson(res, 409, { error: "campaign already exists" });
    return;
  }

  const campaign: CampaignRecord = { id: body.id, name: body.name, dm: body.dm };
  saveCampaign(campaign);

  sendJson(res, 201, { id: campaign.id, name: campaign.name, dm: campaign.dm });
}

export function handleAddCampaignCharacter(res: ServerResponse, campaignId: string, body: unknown): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.id !== "string" ||
    !body.id ||
    typeof body.name !== "string" ||
    !isValidInt(body.level, 1, 20) ||
    typeof body.class !== "string"
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (hasCampaignCharacter(campaignId, body.id)) {
    sendJson(res, 409, { error: "character already exists" });
    return;
  }

  const character: CampaignCharacterRecord = {
    campaignId,
    id: body.id,
    name: body.name,
    level: body.level,
    class: body.class,
  };
  saveCampaignCharacter(character);

  sendJson(res, 201, {
    id: character.id,
    name: character.name,
    level: character.level,
    class: character.class,
  });
}

export function handleAddCampaignEvent(res: ServerResponse, campaignId: string, body: unknown): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.id !== "string" ||
    !body.id ||
    typeof body.kind !== "string" ||
    typeof body.summary !== "string"
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (hasCampaignEvent(campaignId, body.id)) {
    sendJson(res, 409, { error: "event already exists" });
    return;
  }

  const event: CampaignEventRecord = {
    campaignId,
    id: body.id,
    kind: body.kind,
    summary: body.summary,
  };
  saveCampaignEvent(event);

  sendJson(res, 201, { id: event.id, kind: event.kind });
}

export function handleGetCampaignState(res: ServerResponse, campaignId: string): void {
  const campaign = getCampaign(campaignId);
  if (!campaign) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const characters = getCampaignCharacters(campaignId);
  const logCount = countCampaignEvents(campaignId);

  sendJson(res, 200, {
    id: campaign.id,
    name: campaign.name,
    dm: campaign.dm,
    characters: characters.map(({ id, name, level, class: klass }) => ({ id, name, level, class: klass })),
    log_count: logCount,
  });
}
