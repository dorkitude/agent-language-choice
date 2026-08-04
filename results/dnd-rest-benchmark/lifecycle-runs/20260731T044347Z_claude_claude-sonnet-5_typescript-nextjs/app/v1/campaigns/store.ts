import { getDb } from "../db.js";

export interface Campaign {
  id: string;
  name: string;
  dm: string;
}

export interface CampaignCharacter {
  id: string;
  name: string;
  level: number;
  class: string;
}

export interface CampaignEvent {
  id: string;
  kind: string;
  summary: string;
}

export type QuestStatus = "active" | "completed" | "blocked";

export interface CampaignQuest {
  id: string;
  title: string;
  status: QuestStatus;
  milestones: string[];
  completedMilestones: string[];
}

export function hasCampaign(id: string): boolean {
  const row = getDb().prepare("SELECT id FROM campaigns WHERE id = ?").get(id);
  return row !== undefined;
}

export function getCampaign(id: string): Campaign | undefined {
  const row = getDb().prepare("SELECT data FROM campaigns WHERE id = ?").get(id) as
    | { data: string }
    | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as Campaign;
}

export function createCampaign(campaign: Campaign): Campaign {
  getDb()
    .prepare("INSERT INTO campaigns (id, data) VALUES (?, ?)")
    .run(campaign.id, JSON.stringify(campaign));
  return campaign;
}

export function hasCampaignCharacter(campaignId: string, id: string): boolean {
  const row = getDb()
    .prepare("SELECT id FROM campaign_characters WHERE campaign_id = ? AND id = ?")
    .get(campaignId, id);
  return row !== undefined;
}

export function listCampaignCharacters(campaignId: string): CampaignCharacter[] {
  const rows = getDb()
    .prepare("SELECT data FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as CampaignCharacter);
}

export function createCampaignCharacter(
  campaignId: string,
  character: CampaignCharacter,
): CampaignCharacter {
  getDb()
    .prepare("INSERT INTO campaign_characters (campaign_id, id, data) VALUES (?, ?, ?)")
    .run(campaignId, character.id, JSON.stringify(character));
  return character;
}

export function hasCampaignEvent(campaignId: string, id: string): boolean {
  const row = getDb()
    .prepare("SELECT id FROM campaign_events WHERE campaign_id = ? AND id = ?")
    .get(campaignId, id);
  return row !== undefined;
}

export function countCampaignEvents(campaignId: string): number {
  const row = getDb()
    .prepare("SELECT COUNT(*) as count FROM campaign_events WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  return row.count;
}

export function createCampaignEvent(campaignId: string, event: CampaignEvent): CampaignEvent {
  getDb()
    .prepare("INSERT INTO campaign_events (campaign_id, id, data) VALUES (?, ?, ?)")
    .run(campaignId, event.id, JSON.stringify(event));
  return event;
}

export function hasCampaignQuest(campaignId: string, id: string): boolean {
  const row = getDb()
    .prepare("SELECT id FROM campaign_quests WHERE campaign_id = ? AND id = ?")
    .get(campaignId, id);
  return row !== undefined;
}

export function getCampaignQuest(campaignId: string, id: string): CampaignQuest | undefined {
  const row = getDb()
    .prepare("SELECT data FROM campaign_quests WHERE campaign_id = ? AND id = ?")
    .get(campaignId, id) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as CampaignQuest;
}

export function listCampaignQuests(campaignId: string): CampaignQuest[] {
  const rows = getDb()
    .prepare("SELECT data FROM campaign_quests WHERE campaign_id = ? ORDER BY rowid ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as CampaignQuest);
}

export function createCampaignQuest(campaignId: string, quest: CampaignQuest): CampaignQuest {
  getDb()
    .prepare("INSERT INTO campaign_quests (campaign_id, id, data) VALUES (?, ?, ?)")
    .run(campaignId, quest.id, JSON.stringify(quest));
  return quest;
}

export function updateCampaignQuest(campaignId: string, quest: CampaignQuest): CampaignQuest {
  getDb()
    .prepare("UPDATE campaign_quests SET data = ? WHERE campaign_id = ? AND id = ?")
    .run(JSON.stringify(quest), campaignId, quest.id);
  return quest;
}

export type FactionStance = "friendly" | "neutral" | "hostile";

export interface CampaignFaction {
  id: string;
  name: string;
  stance: FactionStance;
}

export interface CampaignNpc {
  id: string;
  name: string;
  faction_id: string | null;
  disposition: number;
}

export function hasCampaignFaction(campaignId: string, id: string): boolean {
  const row = getDb()
    .prepare("SELECT id FROM campaign_factions WHERE campaign_id = ? AND id = ?")
    .get(campaignId, id);
  return row !== undefined;
}

export function getCampaignFaction(
  campaignId: string,
  id: string,
): CampaignFaction | undefined {
  const row = getDb()
    .prepare("SELECT data FROM campaign_factions WHERE campaign_id = ? AND id = ?")
    .get(campaignId, id) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as CampaignFaction;
}

export function listCampaignFactions(campaignId: string): CampaignFaction[] {
  const rows = getDb()
    .prepare("SELECT data FROM campaign_factions WHERE campaign_id = ? ORDER BY rowid ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as CampaignFaction);
}

export function createCampaignFaction(
  campaignId: string,
  faction: CampaignFaction,
): CampaignFaction {
  getDb()
    .prepare("INSERT INTO campaign_factions (campaign_id, id, data) VALUES (?, ?, ?)")
    .run(campaignId, faction.id, JSON.stringify(faction));
  return faction;
}

export function hasCampaignNpc(campaignId: string, id: string): boolean {
  const row = getDb()
    .prepare("SELECT id FROM campaign_npcs WHERE campaign_id = ? AND id = ?")
    .get(campaignId, id);
  return row !== undefined;
}

export function listCampaignNpcs(campaignId: string): CampaignNpc[] {
  const rows = getDb()
    .prepare("SELECT data FROM campaign_npcs WHERE campaign_id = ? ORDER BY rowid ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as CampaignNpc);
}

export function createCampaignNpc(campaignId: string, npc: CampaignNpc): CampaignNpc {
  getDb()
    .prepare("INSERT INTO campaign_npcs (campaign_id, id, data) VALUES (?, ?, ?)")
    .run(campaignId, npc.id, JSON.stringify(npc));
  return npc;
}

export interface CampaignInventoryItem {
  item_slug: string;
  quantity: number;
  owner: string;
}

export interface CampaignEquipmentAssignment {
  character_id: string;
  item_slug: string;
  quantity: number;
}

export function createCampaignInventoryItem(
  campaignId: string,
  item: CampaignInventoryItem,
): CampaignInventoryItem {
  getDb()
    .prepare("INSERT INTO campaign_inventory (campaign_id, data) VALUES (?, ?)")
    .run(campaignId, JSON.stringify(item));
  return item;
}

export function listCampaignInventory(campaignId: string): CampaignInventoryItem[] {
  const rows = getDb()
    .prepare("SELECT data FROM campaign_inventory WHERE campaign_id = ? ORDER BY entry_id ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as CampaignInventoryItem);
}

export function createCampaignEquipmentAssignment(
  campaignId: string,
  assignment: CampaignEquipmentAssignment,
): CampaignEquipmentAssignment {
  getDb()
    .prepare("INSERT INTO campaign_equipment (campaign_id, data) VALUES (?, ?)")
    .run(campaignId, JSON.stringify(assignment));
  return assignment;
}

export function listCampaignEquipment(campaignId: string): CampaignEquipmentAssignment[] {
  const rows = getDb()
    .prepare("SELECT data FROM campaign_equipment WHERE campaign_id = ? ORDER BY entry_id ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as CampaignEquipmentAssignment);
}

export type CraftingStatus = "active" | "complete";

export interface CampaignCraftingProject {
  id: string;
  character_id: string;
  item_slug: string;
  days_required: number;
  days_completed: number;
  cost_gp: number;
  status: CraftingStatus;
}

export function hasCampaignCraftingProject(campaignId: string, id: string): boolean {
  const row = getDb()
    .prepare("SELECT id FROM campaign_crafting_projects WHERE campaign_id = ? AND id = ?")
    .get(campaignId, id);
  return row !== undefined;
}

export function getCampaignCraftingProject(
  campaignId: string,
  id: string,
): CampaignCraftingProject | undefined {
  const row = getDb()
    .prepare("SELECT data FROM campaign_crafting_projects WHERE campaign_id = ? AND id = ?")
    .get(campaignId, id) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as CampaignCraftingProject;
}

export function createCampaignCraftingProject(
  campaignId: string,
  project: CampaignCraftingProject,
): CampaignCraftingProject {
  getDb()
    .prepare("INSERT INTO campaign_crafting_projects (campaign_id, id, data) VALUES (?, ?, ?)")
    .run(campaignId, project.id, JSON.stringify(project));
  return project;
}

export function updateCampaignCraftingProject(
  campaignId: string,
  project: CampaignCraftingProject,
): CampaignCraftingProject {
  getDb()
    .prepare("UPDATE campaign_crafting_projects SET data = ? WHERE campaign_id = ? AND id = ?")
    .run(JSON.stringify(project), campaignId, project.id);
  return project;
}

export interface CampaignSession {
  id: string;
  starts_at: string;
  duration_minutes: number;
  agenda: string[];
  present: string[];
  absent: string[];
}

export function hasCampaignSession(campaignId: string, id: string): boolean {
  const row = getDb()
    .prepare("SELECT id FROM campaign_sessions WHERE campaign_id = ? AND id = ?")
    .get(campaignId, id);
  return row !== undefined;
}

export function getCampaignSession(
  campaignId: string,
  id: string,
): CampaignSession | undefined {
  const row = getDb()
    .prepare("SELECT data FROM campaign_sessions WHERE campaign_id = ? AND id = ?")
    .get(campaignId, id) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as CampaignSession;
}

export function listCampaignSessions(campaignId: string): CampaignSession[] {
  const rows = getDb()
    .prepare("SELECT data FROM campaign_sessions WHERE campaign_id = ? ORDER BY rowid ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as CampaignSession);
}

export function createCampaignSession(
  campaignId: string,
  session: CampaignSession,
): CampaignSession {
  getDb()
    .prepare("INSERT INTO campaign_sessions (campaign_id, id, data) VALUES (?, ?, ?)")
    .run(campaignId, session.id, JSON.stringify(session));
  return session;
}

export function updateCampaignSession(
  campaignId: string,
  session: CampaignSession,
): CampaignSession {
  getDb()
    .prepare("UPDATE campaign_sessions SET data = ? WHERE campaign_id = ? AND id = ?")
    .run(JSON.stringify(session), campaignId, session.id);
  return session;
}

export function getNextCampaignSession(campaignId: string): CampaignSession | undefined {
  const sessions = listCampaignSessions(campaignId);
  if (sessions.length === 0) return undefined;
  return sessions.reduce((earliest, session) =>
    session.starts_at < earliest.starts_at ? session : earliest,
  );
}
