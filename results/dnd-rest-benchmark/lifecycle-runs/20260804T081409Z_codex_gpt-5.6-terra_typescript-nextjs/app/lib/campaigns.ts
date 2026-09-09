import { database } from "./storage";

export type Campaign = { id: string; name: string; dm: string };
export type CampaignCharacter = { id: string; name: string; level: number; class: string };
export type CampaignEvent = { id: string; kind: string; summary: string };
export type CampaignFaction = { id: string; name: string; stance: string };
export type CampaignNpc = { id: string; name: string; faction_id: string; disposition: number };
export type QuestStatus = "active" | "completed" | "blocked";
export type CampaignQuest = {
  id: string;
  title: string;
  status: QuestStatus;
  milestones_total: number;
  milestones_done: number;
};
export type CraftingProject = {
  id: string;
  character_id: string;
  item_slug: string;
  days_required: number;
  days_completed: number;
  status: "active" | "complete";
};
export type CampaignSession = {
  id: string;
  starts_at: string;
  duration_minutes: number;
  agenda_count: number;
};

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

export function getFaction(campaignId: string, factionId: string): CampaignFaction | undefined {
  return database.prepare("SELECT id, name, stance FROM campaign_factions WHERE campaign_id = ? AND id = ?")
    .get(campaignId, factionId) as CampaignFaction | undefined;
}

export function createFaction(campaignId: string, faction: CampaignFaction): boolean {
  if (database.prepare("SELECT 1 FROM campaign_factions WHERE id = ?").get(faction.id)) return false;
  database.prepare("INSERT INTO campaign_factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)")
    .run(faction.id, campaignId, faction.name, faction.stance);
  return true;
}

export function createNpc(campaignId: string, npc: CampaignNpc): boolean {
  if (database.prepare("SELECT 1 FROM campaign_npcs WHERE id = ?").get(npc.id)) return false;
  database.prepare("INSERT INTO campaign_npcs (id, campaign_id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)")
    .run(npc.id, campaignId, npc.name, npc.faction_id, npc.disposition);
  return true;
}

export function relationshipSummary(campaignId: string): { factions: number; npcs: number; friendly_npcs: number } {
  return database.prepare(`
    SELECT
      (SELECT COUNT(*) FROM campaign_factions WHERE campaign_id = ?) AS factions,
      (SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?) AS npcs,
      (SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0) AS friendly_npcs
  `).get(campaignId, campaignId, campaignId) as { factions: number; npcs: number; friendly_npcs: number };
}

export function campaignState(id: string): (Campaign & { characters: CampaignCharacter[]; log_count: number }) | undefined {
  const campaign = getCampaign(id);
  if (!campaign) return undefined;
  const characters = database.prepare("SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid")
    .all(id) as CampaignCharacter[];
  const count = database.prepare("SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?").get(id) as { count: number };
  return { ...campaign, characters, log_count: count.count };
}

function questDetails(campaignId: string, questId: string): CampaignQuest | undefined {
  return database.prepare(`
    SELECT q.id, q.title, q.status,
      COUNT(m.title) AS milestones_total,
      COALESCE(SUM(m.completed), 0) AS milestones_done
    FROM campaign_quests q
    LEFT JOIN quest_milestones m ON m.quest_id = q.id
    WHERE q.campaign_id = ? AND q.id = ?
    GROUP BY q.id, q.title, q.status
  `).get(campaignId, questId) as CampaignQuest | undefined;
}

export function createQuest(campaignId: string, quest: { id: string; title: string; status: QuestStatus; milestones: string[] }): CampaignQuest | undefined {
  if (database.prepare("SELECT 1 FROM campaign_quests WHERE id = ?").get(quest.id)) return undefined;
  const insertQuest = database.prepare("INSERT INTO campaign_quests (id, campaign_id, title, status) VALUES (?, ?, ?, ?)");
  const insertMilestone = database.prepare("INSERT INTO quest_milestones (quest_id, title) VALUES (?, ?)");
  insertQuest.run(quest.id, campaignId, quest.title, quest.status);
  for (const milestone of quest.milestones) insertMilestone.run(quest.id, milestone);
  return questDetails(campaignId, quest.id);
}

export function updateQuestProgress(campaignId: string, questId: string, completed: string[]): CampaignQuest | undefined | null {
  const quest = questDetails(campaignId, questId);
  if (!quest) return undefined;
  const known = database.prepare("SELECT title FROM quest_milestones WHERE quest_id = ?").all(questId) as { title: string }[];
  const knownTitles = new Set(known.map(({ title }) => title));
  if (completed.some((milestone) => !knownTitles.has(milestone))) return null;

  const markComplete = database.prepare("UPDATE quest_milestones SET completed = 1 WHERE quest_id = ? AND title = ?");
  for (const milestone of completed) markComplete.run(questId, milestone);
  const progress = questDetails(campaignId, questId)!;
  if (progress.milestones_total > 0 && progress.milestones_done === progress.milestones_total) {
    database.prepare("UPDATE campaign_quests SET status = 'completed' WHERE id = ? AND status = 'active'").run(questId);
  }
  return questDetails(campaignId, questId);
}

export function questSummary(campaignId: string): { active: number; completed: number; blocked: number } {
  const counts = database.prepare(`
    SELECT
      COALESCE(SUM(status = 'active'), 0) AS active,
      COALESCE(SUM(status = 'completed'), 0) AS completed,
      COALESCE(SUM(status = 'blocked'), 0) AS blocked
    FROM campaign_quests
    WHERE campaign_id = ?
  `).get(campaignId) as { active: number; completed: number; blocked: number };
  return counts;
}

export function addPartyInventory(campaignId: string, itemSlug: string, quantity: number): void {
  database.prepare(`
    INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity)
    VALUES (?, ?, 'party', ?)
    ON CONFLICT(campaign_id, item_slug, owner)
    DO UPDATE SET quantity = quantity + excluded.quantity
  `).run(campaignId, itemSlug, quantity);
}

export function createCraftingProject(
  campaignId: string,
  project: Omit<CraftingProject, "days_completed" | "status"> & { cost_gp: number },
): CraftingProject | undefined {
  if (database.prepare("SELECT 1 FROM crafting_projects WHERE id = ?").get(project.id)) return undefined;
  database.prepare(`
    INSERT INTO crafting_projects
      (id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status)
    VALUES (?, ?, ?, ?, ?, 0, ?, 'active')
  `).run(project.id, campaignId, project.character_id, project.item_slug, project.days_required, project.cost_gp);
  return {
    id: project.id,
    character_id: project.character_id,
    item_slug: project.item_slug,
    days_required: project.days_required,
    days_completed: 0,
    status: "active",
  };
}

export function advanceCraftingProject(
  campaignId: string,
  projectId: string,
  days: number,
): Pick<CraftingProject, "id" | "days_completed" | "status"> | undefined {
  const project = database.prepare(`
    SELECT id, item_slug, days_required, days_completed, status
    FROM crafting_projects WHERE campaign_id = ? AND id = ?
  `).get(campaignId, projectId) as {
    id: string; item_slug: string; days_required: number; days_completed: number; status: "active" | "complete";
  } | undefined;
  if (!project) return undefined;

  if (project.status === "complete") {
    return { id: project.id, days_completed: project.days_completed, status: project.status };
  }

  const daysCompleted = Math.min(project.days_required, project.days_completed + days);
  const status = daysCompleted === project.days_required ? "complete" : "active";
  database.exec("BEGIN");
  try {
    database.prepare("UPDATE crafting_projects SET days_completed = ?, status = ? WHERE id = ?")
      .run(daysCompleted, status, project.id);
    if (status === "complete") addPartyInventory(campaignId, project.item_slug, 1);
    database.exec("COMMIT");
  } catch (error) {
    database.exec("ROLLBACK");
    throw error;
  }
  return { id: project.id, days_completed: daysCompleted, status };
}

export function hasCampaignCharacter(campaignId: string, characterId: string): boolean {
  return Boolean(database.prepare(
    "SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?",
  ).get(campaignId, characterId));
}

export function createCampaignSession(
  campaignId: string,
  session: { id: string; starts_at: string; duration_minutes: number; agenda: string[] },
): CampaignSession | undefined {
  if (database.prepare("SELECT 1 FROM campaign_sessions WHERE id = ?").get(session.id)) return undefined;
  database.prepare(`
    INSERT INTO campaign_sessions (id, campaign_id, starts_at, duration_minutes, agenda_json)
    VALUES (?, ?, ?, ?, ?)
  `).run(session.id, campaignId, session.starts_at, session.duration_minutes, JSON.stringify(session.agenda));
  return {
    id: session.id,
    starts_at: session.starts_at,
    duration_minutes: session.duration_minutes,
    agenda_count: session.agenda.length,
  };
}

export function recordSessionAttendance(
  campaignId: string,
  sessionId: string,
  present: string[],
  absent: string[],
): { session_id: string; present_count: number; absent_count: number } | undefined {
  const session = database.prepare("SELECT 1 FROM campaign_sessions WHERE campaign_id = ? AND id = ?")
    .get(campaignId, sessionId);
  if (!session) return undefined;

  database.exec("BEGIN");
  try {
    database.prepare("DELETE FROM session_attendance WHERE session_id = ?").run(sessionId);
    const insert = database.prepare(
      "INSERT INTO session_attendance (session_id, character_id, status) VALUES (?, ?, ?)",
    );
    for (const characterId of present) insert.run(sessionId, characterId, "present");
    for (const characterId of absent) insert.run(sessionId, characterId, "absent");
    database.exec("COMMIT");
  } catch (error) {
    database.exec("ROLLBACK");
    throw error;
  }
  return { session_id: sessionId, present_count: present.length, absent_count: absent.length };
}

export function nextCampaignSession(campaignId: string): Pick<CampaignSession, "id" | "starts_at" | "agenda_count"> | undefined {
  const session = database.prepare(`
    SELECT id, starts_at, agenda_json
    FROM campaign_sessions
    WHERE campaign_id = ?
    ORDER BY julianday(starts_at), id
    LIMIT 1
  `).get(campaignId) as { id: string; starts_at: string; agenda_json: string } | undefined;
  if (!session) return undefined;
  return { id: session.id, starts_at: session.starts_at, agenda_count: (JSON.parse(session.agenda_json) as unknown[]).length };
}

/** Returns false when the party does not have enough of the requested item. */
export function assignEquipment(campaignId: string, characterId: string, itemSlug: string, quantity: number): boolean {
  const inventory = database.prepare(
    "SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'",
  ).get(campaignId, itemSlug) as { quantity: number } | undefined;
  if (!inventory || inventory.quantity < quantity) return false;

  database.exec("BEGIN");
  try {
    database.prepare(
      "UPDATE campaign_inventory SET quantity = quantity - ? WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'",
    ).run(quantity, campaignId, itemSlug);
    database.prepare("DELETE FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = 'party' AND quantity = 0")
      .run(campaignId, itemSlug);
    database.prepare(`
      INSERT INTO character_equipment (campaign_id, character_id, item_slug, quantity)
      VALUES (?, ?, ?, ?)
      ON CONFLICT(campaign_id, character_id, item_slug)
      DO UPDATE SET quantity = quantity + excluded.quantity
    `).run(campaignId, characterId, itemSlug, quantity);
    database.exec("COMMIT");
    return true;
  } catch (error) {
    database.exec("ROLLBACK");
    throw error;
  }
}

export function inventorySummary(campaignId: string): { party_items: number; assigned_items: number; healing_potions_available: number } {
  return database.prepare(`
    SELECT
      (SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party') AS party_items,
      (SELECT COUNT(*) FROM character_equipment WHERE campaign_id = ?) AS assigned_items,
      COALESCE((SELECT quantity FROM campaign_inventory
        WHERE campaign_id = ? AND item_slug = 'healing-potion' AND owner = 'party'), 0) AS healing_potions_available
  `).get(campaignId, campaignId, campaignId) as { party_items: number; assigned_items: number; healing_potions_available: number };
}

/** Counts the persisted campaign resources used by the audit and export views. */
export function campaignResourceCounts(campaignId: string): {
  characters: number;
  events: number;
  quests: number;
  npcs: number;
  inventory_items: number;
  sessions: number;
} {
  return database.prepare(`
    SELECT
      (SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?) AS characters,
      (SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?) AS events,
      (SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ?) AS quests,
      (SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?) AS npcs,
      (SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ?) AS inventory_items,
      (SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?) AS sessions
  `).get(campaignId, campaignId, campaignId, campaignId, campaignId, campaignId) as {
    characters: number;
    events: number;
    quests: number;
    npcs: number;
    inventory_items: number;
    sessions: number;
  };
}

export type CampaignAnalytics = {
  readiness_score: number;
  open_quests: number;
  friendly_npcs: number;
  scheduled_sessions: number;
  inventory_items: number;
  signals: {
    has_dm: boolean;
    has_characters: boolean;
    has_next_session: boolean;
    has_active_quest: boolean;
  };
};

/** Returns the stable campaign-wide values used by the analytics endpoints. */
export function campaignAnalytics(campaignId: string): CampaignAnalytics {
  const values = database.prepare(`
    SELECT
      (SELECT dm <> '' FROM campaigns WHERE id = ?) AS has_dm,
      (SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?) AS characters,
      (SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ? AND status = 'active') AS open_quests,
      (SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0) AS friendly_npcs,
      (SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?) AS scheduled_sessions,
      (SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party') AS inventory_items
  `).get(campaignId, campaignId, campaignId, campaignId, campaignId, campaignId) as {
    has_dm: number;
    characters: number;
    open_quests: number;
    friendly_npcs: number;
    scheduled_sessions: number;
    inventory_items: number;
  };

  const signals = {
    has_dm: values.has_dm === 1,
    has_characters: values.characters > 0,
    has_next_session: values.scheduled_sessions > 0,
    has_active_quest: values.open_quests > 0,
  };
  // The score intentionally emphasizes the four prerequisites reported by the
  // risk endpoint. A fully prepared campaign therefore has a score of 85.
  const readiness_score =
    (signals.has_dm ? 20 : 0) +
    (signals.has_characters ? 25 : 0) +
    (signals.has_next_session ? 20 : 0) +
    (signals.has_active_quest ? 20 : 0);

  return {
    readiness_score,
    open_quests: values.open_quests,
    friendly_npcs: values.friendly_npcs,
    scheduled_sessions: values.scheduled_sessions,
    inventory_items: values.inventory_items,
    signals,
  };
}
