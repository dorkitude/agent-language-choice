import { database } from "./storage";

export type Campaign = { id: string; name: string; dm: string };
export type CampaignCharacter = { id: string; name: string; level: number; class: string };
export type CampaignEvent = { id: string; kind: string; summary: string };

export function getCampaign(id: string): Campaign | undefined {
  return database.prepare("SELECT id, name, dm FROM campaigns WHERE id = ?").get(id) as Campaign | undefined;
}

export function createCampaign(campaign: Campaign): boolean {
  if (getCampaign(campaign.id)) return false;
  database.prepare("INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)")
    .run(campaign.id, campaign.name, campaign.dm);
  return true;
}

export function addCharacter(campaignId: string, character: CampaignCharacter): boolean {
  const existing = database.prepare("SELECT 1 FROM campaign_characters WHERE id = ?").get(character.id);
  if (existing) return false;
  database.prepare("INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)")
    .run(character.id, campaignId, character.name, character.level, character.class);
  return true;
}

export function addEvent(campaignId: string, event: { id: string; kind: string; summary: string }): boolean {
  const existing = database.prepare("SELECT 1 FROM campaign_events WHERE id = ?").get(event.id);
  if (existing) return false;
  database.prepare("INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)")
    .run(event.id, campaignId, event.kind, event.summary);
  return true;
}

export function campaignEvents(campaignId: string): CampaignEvent[] {
  return database.prepare(
    "SELECT id, kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY rowid",
  ).all(campaignId) as CampaignEvent[];
}

export function campaignState(id: string): (Campaign & { characters: CampaignCharacter[]; log_count: number }) | undefined {
  const campaign = getCampaign(id);
  if (!campaign) return undefined;
  const characters = database.prepare("SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid")
    .all(id) as CampaignCharacter[];
  const count = database.prepare("SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?").get(id) as { count: number };
  return { ...campaign, characters, log_count: count.count };
}
