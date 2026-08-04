// Campaign NPCs and factions, plus a relationship summary derived from
// their disposition state. Persistent (`campaign_factions`, `campaign_npcs`).
import type { ServerResponse } from "node:http";
import { db } from "../db.js";
import { sendJson } from "../http.js";
import { isPlainObject, isValidInt } from "../validation.js";
import { hasCampaign } from "./campaigns.js";

const VALID_STANCES = new Set(["friendly", "neutral", "hostile"]);

interface FactionRecord {
  campaignId: string;
  id: string;
  name: string;
  stance: string;
}

interface NpcRecord {
  campaignId: string;
  id: string;
  name: string;
  factionId: string | null;
  disposition: number;
}

function hasFaction(campaignId: string, id: string): boolean {
  const row = db.prepare("SELECT 1 FROM campaign_factions WHERE campaign_id = ? AND id = ?").get(campaignId, id);
  return row !== undefined;
}

function saveFaction(faction: FactionRecord): void {
  db.prepare("INSERT INTO campaign_factions (campaign_id, id, name, stance) VALUES (?, ?, ?, ?)").run(
    faction.campaignId,
    faction.id,
    faction.name,
    faction.stance,
  );
}

function hasNpc(campaignId: string, id: string): boolean {
  const row = db.prepare("SELECT 1 FROM campaign_npcs WHERE campaign_id = ? AND id = ?").get(campaignId, id);
  return row !== undefined;
}

function saveNpc(npc: NpcRecord): void {
  db.prepare(
    "INSERT INTO campaign_npcs (campaign_id, id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)",
  ).run(npc.campaignId, npc.id, npc.name, npc.factionId, npc.disposition);
}

function countFactions(campaignId: string): number {
  const row = db.prepare("SELECT COUNT(*) AS count FROM campaign_factions WHERE campaign_id = ?").get(
    campaignId,
  ) as { count: number };
  return row.count;
}

function getNpcs(campaignId: string): NpcRecord[] {
  const rows = db
    .prepare("SELECT campaign_id, id, name, faction_id, disposition FROM campaign_npcs WHERE campaign_id = ?")
    .all(campaignId) as { campaign_id: string; id: string; name: string; faction_id: string | null; disposition: number }[];
  return rows.map((row) => ({
    campaignId: row.campaign_id,
    id: row.id,
    name: row.name,
    factionId: row.faction_id,
    disposition: row.disposition,
  }));
}

export function handleCreateFaction(res: ServerResponse, campaignId: string, body: unknown): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.id !== "string" ||
    !body.id ||
    typeof body.name !== "string" ||
    typeof body.stance !== "string" ||
    !VALID_STANCES.has(body.stance)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (hasFaction(campaignId, body.id)) {
    sendJson(res, 409, { error: "faction already exists" });
    return;
  }

  const faction: FactionRecord = { campaignId, id: body.id, name: body.name, stance: body.stance };
  saveFaction(faction);

  sendJson(res, 201, { id: faction.id, name: faction.name, stance: faction.stance });
}

export function handleCreateNpc(res: ServerResponse, campaignId: string, body: unknown): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.id !== "string" ||
    !body.id ||
    typeof body.name !== "string" ||
    typeof body.faction_id !== "string" ||
    !body.faction_id ||
    !isValidInt(body.disposition, -5, 5)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!hasFaction(campaignId, body.faction_id)) {
    sendJson(res, 404, { error: "faction not found" });
    return;
  }

  if (hasNpc(campaignId, body.id)) {
    sendJson(res, 409, { error: "npc already exists" });
    return;
  }

  const npc: NpcRecord = {
    campaignId,
    id: body.id,
    name: body.name,
    factionId: body.faction_id,
    disposition: body.disposition,
  };
  saveNpc(npc);

  sendJson(res, 201, {
    id: npc.id,
    name: npc.name,
    faction_id: npc.factionId,
    disposition: npc.disposition,
  });
}

export function handleRelationshipSummary(res: ServerResponse, campaignId: string): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const npcs = getNpcs(campaignId);
  const friendlyNpcs = npcs.filter((npc) => npc.disposition > 0).length;

  sendJson(res, 200, {
    campaign_id: campaignId,
    factions: countFactions(campaignId),
    npcs: npcs.length,
    friendly_npcs: friendlyNpcs,
  });
}
