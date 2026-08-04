import { DatabaseSync } from 'node:sqlite';

const DB_PATH = 'game.db';
export const SCHEMA_VERSION = 1;

let initialized = false;

// Parse a JSON column value, returning a fallback when the stored value is
// NULL. Keeps the NULL-sensitive handling consistent across the persistence
// layer without changing the stored representation.
function parseJson(value, fallback = null) {
  return value == null ? fallback : JSON.parse(value);
}

// Table list in dependency order. Child tables must come before their parents
// so that reset() can drop them without SQLite foreign-key violations.
const TABLE_NAMES = [
  'events',
  'character_equipment',
  'campaign_inventory',
  'characters',
  'quests',
  'npcs',
  'factions',
  'crafting_projects',
  'session_attendance',
  'campaign_sessions',
  'play_narrations',
  'play_members',
  'play_character_owners',
  'play_character_spells',
  'play_character_spell_slots',
  'play_character_casts',
  'play_character_concentration',
  'play_location_connections',
  'play_locations',
  'play_scenes',
  'play_encounter_rewards',
  'play_encounters',
  'play_character_prepared_spells',
  'play_character_inventory',
  'play_character_equipment',
  'play_character_currency',
  'play_character_quest_rewards',
  'play_currency_transfers',
  'play_loot',
  'play_faction_reputation',
  'play_factions',
  'play_npc_dialogue',
  'play_npcs',
  'play_clues',
  'play_quest_rewards',
  'play_quests',
  'play_relationships',
  'play_world_events',
  'play_campaigns',
  'campaigns',
  'users',
  'combat_sessions',
  'monsters',
  'items',
];

// Single source of truth for the SQL schema. Used by both init (on a fresh
// database) and reset (after dropping existing tables). Keeping the DDL in one
// place prevents the two paths from drifting apart.
const CREATE_SCHEMA = `
  CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    salt TEXT NOT NULL,
    hash TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS combat_sessions (
    id TEXT PRIMARY KEY,
    round INTEGER NOT NULL,
    turn_index INTEGER NOT NULL,
    order_json TEXT NOT NULL,
    conditions_json TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS monsters (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    cr TEXT NOT NULL,
    armor_class INTEGER NOT NULL,
    hit_points INTEGER NOT NULL,
    tags_json TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS items (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    rarity TEXT NOT NULL,
    cost_gp INTEGER NOT NULL
  );

  CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    dm TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS characters (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    level INTEGER NOT NULL,
    "class" TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS events (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS quests (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    milestones_json TEXT NOT NULL,
    done_milestones_json TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS factions (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    stance TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS campaign_inventory (
    campaign_id TEXT NOT NULL,
    item_slug TEXT NOT NULL,
    owner TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, item_slug, owner),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS character_equipment (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    item_slug TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, character_id, item_slug),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id, character_id) REFERENCES characters(campaign_id, id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS npcs (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    faction_id TEXT NOT NULL,
    disposition INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS crafting_projects (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    item_slug TEXT NOT NULL,
    days_required INTEGER NOT NULL,
    cost_gp INTEGER NOT NULL,
    days_completed INTEGER NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS campaign_sessions (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    agenda_json TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_scenes (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_encounter_rewards (
    campaign_id TEXT NOT NULL,
    encounter_id TEXT NOT NULL,
    xp INTEGER NOT NULL,
    loot_json TEXT NOT NULL,
    PRIMARY KEY (campaign_id, encounter_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id, encounter_id) REFERENCES play_encounters(campaign_id, id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_encounters (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    combatants_json TEXT NOT NULL,
    conditions_json TEXT NOT NULL DEFAULT '{}',
    order_json TEXT,
    round INTEGER,
    turn_index INTEGER,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_npcs (
    campaign_id TEXT NOT NULL,
    npc_id TEXT NOT NULL,
    name TEXT NOT NULL,
    agenda TEXT NOT NULL,
    public_status TEXT NOT NULL,
    PRIMARY KEY (campaign_id, npc_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_quests (
    campaign_id TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    title TEXT NOT NULL,
    depends_on_json TEXT NOT NULL,
    state TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, quest_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_quest_rewards (
    campaign_id TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    xp INTEGER NOT NULL,
    items_json TEXT NOT NULL,
    awarded INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (campaign_id, quest_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id, quest_id) REFERENCES play_quests(campaign_id, quest_id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_relationships (
    campaign_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    score INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, source_id, target_id, kind),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_clues (
    campaign_id TEXT NOT NULL,
    clue_id TEXT NOT NULL,
    text TEXT NOT NULL,
    audience TEXT NOT NULL,
    character_id TEXT,
    sequence INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, clue_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_world_events (
    campaign_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled',
    resolution_turn_number INTEGER,
    resolution_text TEXT,
    sequence INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, event_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_npc_dialogue (
    campaign_id TEXT NOT NULL,
    npc_id TEXT NOT NULL,
    dialogue_id TEXT NOT NULL,
    speaker TEXT NOT NULL,
    text TEXT NOT NULL,
    visibility TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, npc_id, dialogue_id),
    FOREIGN KEY (campaign_id, npc_id) REFERENCES play_npcs(campaign_id, npc_id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner TEXT NOT NULL,
    status TEXT NOT NULL,
    max_players INTEGER NOT NULL,
    current_actor TEXT,
    phase TEXT,
    turn_number INTEGER,
    queue_json TEXT,
    current_index INTEGER,
    nudge_count INTEGER NOT NULL DEFAULT 0,
    story TEXT NOT NULL DEFAULT '',
    dm_notes TEXT NOT NULL DEFAULT '',
    current_scene_id TEXT,
    pre_combat_state_json TEXT
  );

  CREATE TABLE IF NOT EXISTS play_narrations (
    campaign_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    kind TEXT NOT NULL,
    actor TEXT NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (campaign_id, sequence),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_members (
    campaign_id TEXT NOT NULL,
    username TEXT NOT NULL,
    character_id TEXT NOT NULL,
    name TEXT NOT NULL,
    class TEXT NOT NULL,
    hp_current INTEGER NOT NULL DEFAULT 20,
    hp_max INTEGER NOT NULL DEFAULT 20,
    status TEXT NOT NULL DEFAULT 'conscious',
    death_saves_successes INTEGER NOT NULL DEFAULT 0,
    death_saves_failures INTEGER NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 1,
    abilities_json TEXT,
    PRIMARY KEY (campaign_id, username),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_character_owners (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    PRIMARY KEY (campaign_id, character_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_character_spells (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    spell_id TEXT NOT NULL,
    name TEXT NOT NULL,
    level INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, character_id, spell_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_character_prepared_spells (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    prepared_spells_json TEXT NOT NULL,
    PRIMARY KEY (campaign_id, character_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_character_inventory (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, character_id, item_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_character_equipment (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    slot TEXT NOT NULL,
    item_id TEXT NOT NULL,
    attuned INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (campaign_id, character_id, slot),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_character_currency (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    gold INTEGER NOT NULL DEFAULT 10,
    PRIMARY KEY (campaign_id, character_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_character_quest_rewards (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    xp INTEGER NOT NULL DEFAULT 0,
    items_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (campaign_id, character_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_currency_transfers (
    campaign_id TEXT NOT NULL,
    transfer_id INTEGER NOT NULL,
    from_character_id TEXT NOT NULL,
    to_character_id TEXT NOT NULL,
    gold INTEGER NOT NULL,
    from_gold INTEGER NOT NULL,
    to_gold INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, transfer_id)
  );

  CREATE TABLE IF NOT EXISTS play_character_spell_slots (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    slots_json TEXT NOT NULL,
    PRIMARY KEY (campaign_id, character_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_character_casts (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    spell_id TEXT NOT NULL,
    target TEXT NOT NULL,
    slot_level INTEGER NOT NULL,
    slots_remaining INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, character_id, sequence),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_character_concentration (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    spell_id TEXT NOT NULL,
    target TEXT NOT NULL,
    remaining_turns INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, character_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_loot (
    campaign_id TEXT NOT NULL,
    loot_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    status TEXT NOT NULL,
    recipient_character_id TEXT,
    votes_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (campaign_id, loot_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_locations (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_location_connections (
    campaign_id TEXT NOT NULL,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    travel_turns INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, from_id, to_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id, from_id) REFERENCES play_locations(campaign_id, id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id, to_id) REFERENCES play_locations(campaign_id, id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS session_attendance (
    campaign_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    present INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, session_id, character_id),
    FOREIGN KEY (campaign_id, session_id) REFERENCES campaign_sessions(campaign_id, id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_factions (
    campaign_id TEXT NOT NULL,
    faction_id TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (campaign_id, faction_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS play_faction_reputation (
    campaign_id TEXT NOT NULL,
    faction_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    reputation INTEGER NOT NULL,
    delta INTEGER NOT NULL,
    reason TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, faction_id, sequence),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id, faction_id) REFERENCES play_factions(campaign_id, faction_id) ON DELETE CASCADE
  );
`;

const DROP_TABLES = TABLE_NAMES
  .map(name => `DROP TABLE IF EXISTS ${name};`)
  .join('\n');

const db = new DatabaseSync(DB_PATH);

export function isInitialized() {
  return initialized;
}

function ensureSchema() {
  db.exec(CREATE_SCHEMA);
  initialized = true;
}

export function initDb() {
  ensureSchema();
}

export function resetDb() {
  db.exec(DROP_TABLES);
  ensureSchema();
}

// Users

export function getUser(username) {
  const stmt = db.prepare('SELECT username, role, salt, hash FROM users WHERE username = ?');
  return stmt.get(username) ?? null;
}

export function createUser(user) {
  const stmt = db.prepare('INSERT INTO users (username, role, salt, hash) VALUES (?, ?, ?, ?)');
  stmt.run(user.username, user.role, user.salt, user.hash);
}

// Combat sessions

export function getSession(id) {
  const stmt = db.prepare('SELECT id, round, turn_index, order_json, conditions_json FROM combat_sessions WHERE id = ?');
  const row = stmt.get(id);
  if (!row) return null;
  return {
    id: row.id,
    round: row.round,
    turn_index: row.turn_index,
    order: parseJson(row.order_json),
    conditions: parseJson(row.conditions_json),
  };
}

export function createSession(session) {
  const stmt = db.prepare('INSERT INTO combat_sessions (id, round, turn_index, order_json, conditions_json) VALUES (?, ?, ?, ?, ?)');
  stmt.run(session.id, session.round, session.turn_index, JSON.stringify(session.order), JSON.stringify(session.conditions));
}

export function updateSession(session) {
  const stmt = db.prepare('UPDATE combat_sessions SET round = ?, turn_index = ?, order_json = ?, conditions_json = ? WHERE id = ?');
  stmt.run(session.round, session.turn_index, JSON.stringify(session.order), JSON.stringify(session.conditions), session.id);
}

// Monsters

export function getMonster(slug) {
  const stmt = db.prepare('SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters WHERE slug = ?');
  const row = stmt.get(slug);
  if (!row) return null;
  return {
    slug: row.slug,
    name: row.name,
    cr: row.cr,
    armor_class: row.armor_class,
    hit_points: row.hit_points,
    tags: parseJson(row.tags_json),
  };
}

export function createMonster(monster) {
  const stmt = db.prepare('INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)');
  stmt.run(monster.slug, monster.name, monster.cr, monster.armor_class, monster.hit_points, JSON.stringify(monster.tags));
}

// Items

export function getItem(slug) {
  const stmt = db.prepare('SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?');
  return stmt.get(slug) ?? null;
}

export function createItem(item) {
  const stmt = db.prepare('INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)');
  stmt.run(item.slug, item.name, item.type, item.rarity, item.cost_gp);
}

// Campaigns

export function getCampaign(id) {
  const stmt = db.prepare('SELECT id, name, dm FROM campaigns WHERE id = ?');
  return stmt.get(id) ?? null;
}

export function createCampaign(campaign) {
  const stmt = db.prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)');
  stmt.run(campaign.id, campaign.name, campaign.dm);
}

// Campaign characters

export function getCampaignCharacter(campaignId, characterId) {
  const stmt = db.prepare('SELECT id, name, level, "class" FROM characters WHERE campaign_id = ? AND id = ?');
  return stmt.get(campaignId, characterId) ?? null;
}

export function getCampaignCharacters(campaignId) {
  const stmt = db.prepare('SELECT id, name, level, "class" FROM characters WHERE campaign_id = ? ORDER BY rowid');
  return stmt.all(campaignId);
}

export function getCampaignCharacterCount(campaignId) {
  const stmt = db.prepare('SELECT COUNT(*) as count FROM characters WHERE campaign_id = ?');
  const row = stmt.get(campaignId);
  return row?.count ?? 0;
}

export function createCampaignCharacter(campaignId, character) {
  const stmt = db.prepare('INSERT INTO characters (campaign_id, id, name, level, "class") VALUES (?, ?, ?, ?, ?)');
  stmt.run(campaignId, character.id, character.name, character.level, character.class);
}

// Campaign events

export function getCampaignEvent(campaignId, eventId) {
  const stmt = db.prepare('SELECT id, kind FROM events WHERE campaign_id = ? AND id = ?');
  return stmt.get(campaignId, eventId) ?? null;
}

export function getCampaignEventCount(campaignId) {
  const stmt = db.prepare('SELECT COUNT(*) as count FROM events WHERE campaign_id = ?');
  const row = stmt.get(campaignId);
  return row?.count ?? 0;
}

export function createCampaignEvent(campaignId, event) {
  const stmt = db.prepare('INSERT INTO events (campaign_id, id, kind, summary) VALUES (?, ?, ?, ?)');
  stmt.run(campaignId, event.id, event.kind, event.summary ?? null);
}

// Quests

export function getQuest(campaignId, questId) {
  const stmt = db.prepare('SELECT campaign_id, id, title, status, milestones_json, done_milestones_json FROM quests WHERE campaign_id = ? AND id = ?');
  const row = stmt.get(campaignId, questId);
  if (!row) return null;
  return {
    campaign_id: row.campaign_id,
    id: row.id,
    title: row.title,
    status: row.status,
    milestones: parseJson(row.milestones_json),
    done_milestones: parseJson(row.done_milestones_json),
  };
}

export function getQuests(campaignId) {
  const stmt = db.prepare('SELECT campaign_id, id, title, status, milestones_json, done_milestones_json FROM quests WHERE campaign_id = ?');
  const rows = stmt.all(campaignId);
  return rows.map(row => ({
    campaign_id: row.campaign_id,
    id: row.id,
    title: row.title,
    status: row.status,
    milestones: parseJson(row.milestones_json),
    done_milestones: parseJson(row.done_milestones_json),
  }));
}

export function createQuest(campaignId, quest) {
  const stmt = db.prepare('INSERT INTO quests (campaign_id, id, title, status, milestones_json, done_milestones_json) VALUES (?, ?, ?, ?, ?, ?)');
  stmt.run(campaignId, quest.id, quest.title, quest.status, JSON.stringify(quest.milestones), JSON.stringify(quest.done_milestones));
}

export function updateQuest(campaignId, quest) {
  const stmt = db.prepare('UPDATE quests SET title = ?, status = ?, milestones_json = ?, done_milestones_json = ? WHERE campaign_id = ? AND id = ?');
  stmt.run(quest.title, quest.status, JSON.stringify(quest.milestones), JSON.stringify(quest.done_milestones), campaignId, quest.id);
}

export function getCampaignQuestCount(campaignId) {
  const stmt = db.prepare('SELECT COUNT(*) as count FROM quests WHERE campaign_id = ?');
  const row = stmt.get(campaignId);
  return row?.count ?? 0;
}

export function getOpenQuestCount(campaignId) {
  const stmt = db.prepare("SELECT COUNT(*) as count FROM quests WHERE campaign_id = ? AND status != 'completed'");
  const row = stmt.get(campaignId);
  return row?.count ?? 0;
}

// Factions

export function getFaction(campaignId, factionId) {
  const stmt = db.prepare('SELECT campaign_id, id, name, stance FROM factions WHERE campaign_id = ? AND id = ?');
  return stmt.get(campaignId, factionId) ?? null;
}

export function getFactionCount(campaignId) {
  const stmt = db.prepare('SELECT COUNT(*) as count FROM factions WHERE campaign_id = ?');
  const row = stmt.get(campaignId);
  return row?.count ?? 0;
}

export function createFaction(campaignId, faction) {
  const stmt = db.prepare('INSERT INTO factions (campaign_id, id, name, stance) VALUES (?, ?, ?, ?)');
  stmt.run(campaignId, faction.id, faction.name, faction.stance);
}

// NPCs

export function getNpc(campaignId, npcId) {
  const stmt = db.prepare('SELECT campaign_id, id, name, faction_id, disposition FROM npcs WHERE campaign_id = ? AND id = ?');
  return stmt.get(campaignId, npcId) ?? null;
}

export function getNpcs(campaignId) {
  const stmt = db.prepare('SELECT campaign_id, id, name, faction_id, disposition FROM npcs WHERE campaign_id = ? ORDER BY rowid');
  return stmt.all(campaignId);
}

export function getNpcCount(campaignId) {
  const stmt = db.prepare('SELECT COUNT(*) as count FROM npcs WHERE campaign_id = ?');
  const row = stmt.get(campaignId);
  return row?.count ?? 0;
}

export function getFriendlyNpcCount(campaignId) {
  const stmt = db.prepare('SELECT COUNT(*) as count FROM npcs WHERE campaign_id = ? AND disposition > 0');
  const row = stmt.get(campaignId);
  return row?.count ?? 0;
}

export function createNpc(campaignId, npc) {
  const stmt = db.prepare('INSERT INTO npcs (campaign_id, id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)');
  stmt.run(campaignId, npc.id, npc.name, npc.faction_id, npc.disposition);
}

// Crafting projects

export function getCraftingProject(campaignId, projectId) {
  const stmt = db.prepare('SELECT campaign_id, id, character_id, item_slug, days_required, cost_gp, days_completed, status FROM crafting_projects WHERE campaign_id = ? AND id = ?');
  return stmt.get(campaignId, projectId) ?? null;
}

export function createCraftingProject(campaignId, project) {
  const stmt = db.prepare('INSERT INTO crafting_projects (campaign_id, id, character_id, item_slug, days_required, cost_gp, days_completed, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)');
  stmt.run(campaignId, project.id, project.character_id, project.item_slug, project.days_required, project.cost_gp, project.days_completed, project.status);
}

export function updateCraftingProject(campaignId, project) {
  const stmt = db.prepare('UPDATE crafting_projects SET days_completed = ?, status = ? WHERE campaign_id = ? AND id = ?');
  stmt.run(project.days_completed, project.status, campaignId, project.id);
}

// Inventory and equipment

export function addInventoryItem(campaignId, itemSlug, owner, quantity) {
  const stmt = db.prepare(`
    INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity)
    VALUES (?, ?, ?, ?)
    ON CONFLICT (campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + excluded.quantity
  `);
  stmt.run(campaignId, itemSlug, owner, quantity);
}

export function getPartyItemQuantity(campaignId, itemSlug) {
  const stmt = db.prepare('SELECT COALESCE(SUM(quantity), 0) as total FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
  const row = stmt.get(campaignId, itemSlug, 'party');
  return row.total;
}

export function getAssignedQuantity(campaignId, itemSlug) {
  const stmt = db.prepare('SELECT COALESCE(SUM(quantity), 0) as total FROM character_equipment WHERE campaign_id = ? AND item_slug = ?');
  const row = stmt.get(campaignId, itemSlug);
  return row.total;
}

export function getPartyItemCount(campaignId) {
  const stmt = db.prepare('SELECT COUNT(*) as count FROM campaign_inventory WHERE campaign_id = ? AND owner = ?');
  const row = stmt.get(campaignId, 'party');
  return row.count;
}

export function getAssignedItemCount(campaignId) {
  const stmt = db.prepare('SELECT COUNT(*) as count FROM character_equipment WHERE campaign_id = ?');
  const row = stmt.get(campaignId);
  return row.count;
}

export function getCampaignInventoryItemCount(campaignId) {
  const stmt = db.prepare('SELECT COUNT(*) as count FROM campaign_inventory WHERE campaign_id = ?');
  const row = stmt.get(campaignId);
  return row?.count ?? 0;
}

export function assignEquipment(campaignId, characterId, itemSlug, quantity) {
  const stmt = db.prepare(`
    INSERT INTO character_equipment (campaign_id, character_id, item_slug, quantity)
    VALUES (?, ?, ?, ?)
    ON CONFLICT (campaign_id, character_id, item_slug) DO UPDATE SET quantity = quantity + excluded.quantity
  `);
  stmt.run(campaignId, characterId, itemSlug, quantity);
}

// Campaign sessions

export function getCampaignSession(campaignId, sessionId) {
  const stmt = db.prepare('SELECT campaign_id, id, starts_at, duration_minutes, agenda_json FROM campaign_sessions WHERE campaign_id = ? AND id = ?');
  const row = stmt.get(campaignId, sessionId);
  if (!row) return null;
  return {
    campaign_id: row.campaign_id,
    id: row.id,
    starts_at: row.starts_at,
    duration_minutes: row.duration_minutes,
    agenda: parseJson(row.agenda_json),
  };
}

export function getCampaignSessions(campaignId) {
  const stmt = db.prepare('SELECT campaign_id, id, starts_at, duration_minutes, agenda_json FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at ASC');
  const rows = stmt.all(campaignId);
  return rows.map(row => ({
    campaign_id: row.campaign_id,
    id: row.id,
    starts_at: row.starts_at,
    duration_minutes: row.duration_minutes,
    agenda: parseJson(row.agenda_json),
  }));
}

export function getCampaignSessionCount(campaignId) {
  const stmt = db.prepare('SELECT COUNT(*) as count FROM campaign_sessions WHERE campaign_id = ?');
  const row = stmt.get(campaignId);
  return row?.count ?? 0;
}

export function getNextCampaignSession(campaignId) {
  const stmt = db.prepare('SELECT campaign_id, id, starts_at, duration_minutes, agenda_json FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at ASC LIMIT 1');
  const row = stmt.get(campaignId);
  if (!row) return null;
  return {
    campaign_id: row.campaign_id,
    id: row.id,
    starts_at: row.starts_at,
    duration_minutes: row.duration_minutes,
    agenda: parseJson(row.agenda_json),
  };
}

export function createCampaignSession(campaignId, session) {
  const stmt = db.prepare('INSERT INTO campaign_sessions (campaign_id, id, starts_at, duration_minutes, agenda_json) VALUES (?, ?, ?, ?, ?)');
  stmt.run(campaignId, session.id, session.starts_at, session.duration_minutes, JSON.stringify(session.agenda));
}

// Play campaigns

export function getPlayCampaign(id) {
  const stmt = db.prepare('SELECT id, name, owner, status, max_players, current_actor, phase, turn_number, queue_json, current_index, nudge_count, story, dm_notes, current_scene_id, pre_combat_state_json FROM play_campaigns WHERE id = ?');
  const row = stmt.get(id) ?? null;
  if (!row) return null;
  return {
    id: row.id,
    name: row.name,
    owner: row.owner,
    status: row.status,
    max_players: row.max_players,
    current_actor: row.current_actor,
    phase: row.phase,
    turn_number: row.turn_number,
    queue: parseJson(row.queue_json),
    current_index: row.current_index,
    nudge_count: row.nudge_count,
    story: row.story,
    dm_notes: row.dm_notes,
    current_scene_id: row.current_scene_id,
    pre_combat_state: parseJson(row.pre_combat_state_json),
  };
}

export function createPlayCampaign(campaign) {
  const stmt = db.prepare('INSERT INTO play_campaigns (id, name, owner, status, max_players, current_actor, phase, turn_number, queue_json, current_index, nudge_count, story, dm_notes, current_scene_id, pre_combat_state_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)');
  stmt.run(campaign.id, campaign.name, campaign.owner, campaign.status, campaign.max_players, campaign.current_actor ?? null, campaign.phase ?? null, campaign.turn_number ?? null, campaign.queue_json ?? null, campaign.current_index ?? null, campaign.nudge_count ?? 0, campaign.story ?? '', campaign.dm_notes ?? '', campaign.current_scene_id ?? null, campaign.pre_combat_state_json ?? null);
}

export function startPlayCampaign(id, currentActor, phase, turnNumber, queue, currentIndex) {
  const stmt = db.prepare('UPDATE play_campaigns SET status = ?, current_actor = ?, phase = ?, turn_number = ?, queue_json = ?, current_index = ? WHERE id = ?');
  stmt.run('active', currentActor, phase, turnNumber, JSON.stringify(queue), currentIndex, id);
}

export function advancePlayCampaignTurn(id, currentActor, phase, turnNumber, currentIndex) {
  const stmt = db.prepare('UPDATE play_campaigns SET current_actor = ?, phase = ?, turn_number = ?, current_index = ? WHERE id = ?');
  stmt.run(currentActor, phase, turnNumber, currentIndex, id);
}

export function enterPlayCampaignCombat(id, state) {
  const stmt = db.prepare('UPDATE play_campaigns SET pre_combat_state_json = ? WHERE id = ?');
  stmt.run(JSON.stringify(state), id);
}

export function leavePlayCampaignCombat(id, currentActor, phase, turnNumber, currentIndex) {
  const stmt = db.prepare('UPDATE play_campaigns SET current_actor = ?, phase = ?, turn_number = ?, current_index = ?, pre_combat_state_json = NULL WHERE id = ?');
  stmt.run(currentActor, phase, turnNumber, currentIndex, id);
}

export function incrementPlayCampaignNudgeCount(id) {
  const campaign = getPlayCampaign(id);
  if (!campaign) return null;
  const nudgeCount = campaign.nudge_count + 1;
  const stmt = db.prepare('UPDATE play_campaigns SET nudge_count = ? WHERE id = ?');
  stmt.run(nudgeCount, id);
  return nudgeCount;
}

export function updatePlayCampaignDocument(id, story, dmNotes) {
  const stmt = db.prepare('UPDATE play_campaigns SET story = ?, dm_notes = ? WHERE id = ?');
  stmt.run(story, dmNotes, id);
}

export function getSessionAttendance(campaignId, sessionId) {
  const stmt = db.prepare('SELECT character_id, present FROM session_attendance WHERE campaign_id = ? AND session_id = ?');
  const rows = stmt.all(campaignId, sessionId);
  const present = [];
  const absent = [];
  for (const row of rows) {
    if (row.present) present.push(row.character_id);
    else absent.push(row.character_id);
  }
  return { present, absent };
}

export function recordSessionAttendance(campaignId, sessionId, characterId, present) {
  const stmt = db.prepare(`
    INSERT INTO session_attendance (campaign_id, session_id, character_id, present)
    VALUES (?, ?, ?, ?)
    ON CONFLICT (campaign_id, session_id, character_id) DO UPDATE SET present = excluded.present
  `);
  stmt.run(campaignId, sessionId, characterId, present ? 1 : 0);
}

// Play campaign members

export function getPlayMembership(campaignId, username) {
  const stmt = db.prepare('SELECT campaign_id, username, character_id, name, "class", hp_current, hp_max, status, death_saves_successes, death_saves_failures, level, abilities_json FROM play_members WHERE campaign_id = ? AND username = ?');
  const row = stmt.get(campaignId, username) ?? null;
  if (!row) return null;
  return { ...row, abilities: parseJson(row.abilities_json, {}) };
}

export function getPlayMembershipByCharacterId(campaignId, characterId) {
  const stmt = db.prepare('SELECT campaign_id, username, character_id, name, "class", hp_current, hp_max, status, death_saves_successes, death_saves_failures, level, abilities_json FROM play_members WHERE campaign_id = ? AND character_id = ?');
  const row = stmt.get(campaignId, characterId) ?? null;
  if (!row) return null;
  return { ...row, abilities: parseJson(row.abilities_json, {}) };
}

export function getPlayMembershipCount(campaignId) {
  const stmt = db.prepare('SELECT COUNT(*) as count FROM play_members WHERE campaign_id = ?');
  const row = stmt.get(campaignId);
  return row?.count ?? 0;
}

export function getPlayMembers(campaignId) {
  const stmt = db.prepare('SELECT campaign_id, username, character_id, name, "class" FROM play_members WHERE campaign_id = ? ORDER BY rowid');
  return stmt.all(campaignId);
}

export function createPlayMembership(campaignId, membership) {
  const stmt = db.prepare('INSERT INTO play_members (campaign_id, username, character_id, name, "class", hp_current, hp_max) VALUES (?, ?, ?, ?, ?, ?, ?)');
  stmt.run(campaignId, membership.username, membership.character_id, membership.name, membership.class, membership.hp_current ?? 20, membership.hp_max ?? 20);
}

export function getCharacterOwner(campaignId, characterId) {
  const stmt = db.prepare('SELECT owner FROM play_character_owners WHERE campaign_id = ? AND character_id = ?');
  const row = stmt.get(campaignId, characterId);
  return row?.owner ?? null;
}

export function createCharacterOwner(campaignId, characterId, owner) {
  const stmt = db.prepare('INSERT INTO play_character_owners (campaign_id, character_id, owner) VALUES (?, ?, ?)');
  stmt.run(campaignId, characterId, owner);
}

export function setCharacterOwner(campaignId, characterId, owner) {
  const stmt = db.prepare('INSERT INTO play_character_owners (campaign_id, character_id, owner) VALUES (?, ?, ?) ON CONFLICT (campaign_id, character_id) DO UPDATE SET owner = excluded.owner');
  stmt.run(campaignId, characterId, owner);
}

// Play character spells

export function getCharacterSpell(campaignId, characterId, spellId) {
  const stmt = db.prepare('SELECT campaign_id, character_id, spell_id, name, level FROM play_character_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?');
  return stmt.get(campaignId, characterId, spellId) ?? null;
}

export function getCharacterSpells(campaignId, characterId) {
  const stmt = db.prepare('SELECT spell_id, name, level FROM play_character_spells WHERE campaign_id = ? AND character_id = ? ORDER BY level, spell_id');
  return stmt.all(campaignId, characterId);
}

export function createCharacterSpell(campaignId, characterId, spell) {
  const stmt = db.prepare('INSERT INTO play_character_spells (campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)');
  stmt.run(campaignId, characterId, spell.spell_id, spell.name, spell.level);
}

export function getCharacterPreparedSpells(campaignId, characterId) {
  const stmt = db.prepare('SELECT prepared_spells_json FROM play_character_prepared_spells WHERE campaign_id = ? AND character_id = ?');
  const row = stmt.get(campaignId, characterId);
  return row ? parseJson(row.prepared_spells_json) : [];
}

export function setCharacterPreparedSpells(campaignId, characterId, spellIds) {
  const stmt = db.prepare('INSERT INTO play_character_prepared_spells (campaign_id, character_id, prepared_spells_json) VALUES (?, ?, ?) ON CONFLICT (campaign_id, character_id) DO UPDATE SET prepared_spells_json = excluded.prepared_spells_json');
  stmt.run(campaignId, characterId, JSON.stringify(spellIds));
}

export function getCharacterSpellSlots(campaignId, characterId) {
  const stmt = db.prepare('SELECT slots_json FROM play_character_spell_slots WHERE campaign_id = ? AND character_id = ?');
  const row = stmt.get(campaignId, characterId);
  return row ? parseJson(row.slots_json) : null;
}

export function setCharacterSpellSlots(campaignId, characterId, slots) {
  const stmt = db.prepare('INSERT INTO play_character_spell_slots (campaign_id, character_id, slots_json) VALUES (?, ?, ?) ON CONFLICT (campaign_id, character_id) DO UPDATE SET slots_json = excluded.slots_json');
  stmt.run(campaignId, characterId, JSON.stringify(slots));
}

export function getNextCastSequence(campaignId, characterId) {
  const stmt = db.prepare('SELECT COALESCE(MAX(sequence), 0) as next FROM play_character_casts WHERE campaign_id = ? AND character_id = ?');
  const row = stmt.get(campaignId, characterId);
  return (row?.next ?? 0) + 1;
}

export function createCharacterCast(campaignId, characterId, cast) {
  const stmt = db.prepare('INSERT INTO play_character_casts (campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining) VALUES (?, ?, ?, ?, ?, ?, ?)');
  stmt.run(campaignId, characterId, cast.sequence, cast.spell_id, cast.target, cast.slot_level, cast.slots_remaining);
}

export function getCharacterCasts(campaignId, characterId) {
  const stmt = db.prepare('SELECT sequence, spell_id, target, slot_level, slots_remaining FROM play_character_casts WHERE campaign_id = ? AND character_id = ? ORDER BY sequence ASC');
  return stmt.all(campaignId, characterId);
}

export function getCharacterConcentration(campaignId, characterId) {
  const stmt = db.prepare('SELECT spell_id, target, remaining_turns FROM play_character_concentration WHERE campaign_id = ? AND character_id = ?');
  const row = stmt.get(campaignId, characterId);
  if (!row) return null;
  return { spell_id: row.spell_id, target: row.target, remaining_turns: row.remaining_turns };
}

export function setCharacterConcentration(campaignId, characterId, concentration) {
  const stmt = db.prepare('INSERT INTO play_character_concentration (campaign_id, character_id, spell_id, target, remaining_turns) VALUES (?, ?, ?, ?, ?) ON CONFLICT (campaign_id, character_id) DO UPDATE SET spell_id = excluded.spell_id, target = excluded.target, remaining_turns = excluded.remaining_turns');
  stmt.run(campaignId, characterId, concentration.spell_id, concentration.target, concentration.remaining_turns);
}

export function deleteCharacterConcentration(campaignId, characterId) {
  const stmt = db.prepare('DELETE FROM play_character_concentration WHERE campaign_id = ? AND character_id = ?');
  stmt.run(campaignId, characterId);
}

export function updatePlayMembershipHpCurrent(campaignId, username, hpCurrent) {
  const stmt = db.prepare('UPDATE play_members SET hp_current = ? WHERE campaign_id = ? AND username = ?');
  stmt.run(hpCurrent, campaignId, username);
}

export function updatePlayMembershipBuild(campaignId, username, cls, level, hpMax, abilities) {
  const stmt = db.prepare('UPDATE play_members SET "class" = ?, level = ?, hp_max = ?, hp_current = ?, abilities_json = ? WHERE campaign_id = ? AND username = ?');
  stmt.run(cls, level, hpMax, hpMax, JSON.stringify(abilities), campaignId, username);
}

export function updatePlayMembershipLevel(campaignId, username, level, hpMax) {
  const stmt = db.prepare('UPDATE play_members SET level = ?, hp_max = ? WHERE campaign_id = ? AND username = ?');
  stmt.run(level, hpMax, campaignId, username);
}

export function updatePlayMembershipHpAndStatus(campaignId, username, hpCurrent, status) {
  const stmt = db.prepare('UPDATE play_members SET hp_current = ?, status = ? WHERE campaign_id = ? AND username = ?');
  stmt.run(hpCurrent, status, campaignId, username);
}

export function updatePlayMembershipDeathSaves(campaignId, username, successes, failures, status) {
  const stmt = db.prepare('UPDATE play_members SET death_saves_successes = ?, death_saves_failures = ?, status = ? WHERE campaign_id = ? AND username = ?');
  stmt.run(successes, failures, status, campaignId, username);
}

// Play narrations

export function getNextNarrationSequence(campaignId) {
  const stmt = db.prepare('SELECT COALESCE(MAX(sequence), 0) as next FROM play_narrations WHERE campaign_id = ?');
  const row = stmt.get(campaignId);
  return (row?.next ?? 0) + 1;
}

export function getPlayNarrations(campaignId) {
  const stmt = db.prepare('SELECT sequence, kind, actor, text FROM play_narrations WHERE campaign_id = ? ORDER BY sequence ASC');
  return stmt.all(campaignId);
}

export function createNarration(campaignId, narration) {
  const stmt = db.prepare('INSERT INTO play_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)');
  stmt.run(campaignId, narration.sequence, narration.kind, narration.actor, narration.text);
}

// Play scenes

export function getScene(campaignId, sceneId) {
  const stmt = db.prepare('SELECT campaign_id, id, name, status FROM play_scenes WHERE campaign_id = ? AND id = ?');
  return stmt.get(campaignId, sceneId) ?? null;
}

export function createScene(campaignId, scene) {
  const stmt = db.prepare('INSERT INTO play_scenes (campaign_id, id, name, status) VALUES (?, ?, ?, ?)');
  stmt.run(campaignId, scene.id, scene.name, scene.status);
}

export function updateScene(campaignId, scene) {
  const stmt = db.prepare('UPDATE play_scenes SET name = ?, status = ? WHERE campaign_id = ? AND id = ?');
  stmt.run(scene.name, scene.status, campaignId, scene.id);
}

export function setCurrentScene(campaignId, sceneId) {
  const stmt = db.prepare('UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?');
  stmt.run(sceneId, campaignId);
}

// Play encounters

export function getPlayEncounter(campaignId, encounterId) {
  const stmt = db.prepare('SELECT campaign_id, id, name, status, combatants_json, conditions_json, order_json, round, turn_index FROM play_encounters WHERE campaign_id = ? AND id = ?');
  const row = stmt.get(campaignId, encounterId);
  if (!row) return null;
  return {
    campaign_id: row.campaign_id,
    id: row.id,
    name: row.name,
    status: row.status,
    combatants: parseJson(row.combatants_json),
    conditions: parseJson(row.conditions_json, {}),
    order: parseJson(row.order_json, []),
    round: row.round,
    turn_index: row.turn_index,
  };
}

export function getActivePlayEncounter(campaignId) {
  const stmt = db.prepare("SELECT campaign_id, id, name, status, combatants_json, conditions_json FROM play_encounters WHERE campaign_id = ? AND status = 'active'");
  const row = stmt.get(campaignId);
  if (!row) return null;
  return {
    campaign_id: row.campaign_id,
    id: row.id,
    name: row.name,
    status: row.status,
    combatants: parseJson(row.combatants_json),
    conditions: parseJson(row.conditions_json, {}),
  };
}

export function createPlayEncounter(campaignId, encounter) {
  const stmt = db.prepare('INSERT INTO play_encounters (campaign_id, id, name, status, combatants_json, conditions_json, order_json, round, turn_index) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)');
  stmt.run(campaignId, encounter.id, encounter.name, encounter.status, JSON.stringify(encounter.combatants), JSON.stringify(encounter.conditions ?? {}), JSON.stringify(encounter.order ?? []), encounter.round ?? 1, encounter.turn_index ?? 0);
}

// Internal helper: add a combatant to an encounter if it is not already
// present (by the supplied key). Resets the persisted initiative order so the
// next turn read recomputes from the updated roster.
function addCombatant(campaignId, encounterId, combatant, keyFn) {
  const encounter = getPlayEncounter(campaignId, encounterId);
  if (!encounter) return null;
  const combatants = encounter.combatants ?? [];
  if (combatants.some(c => keyFn(c) === keyFn(combatant))) {
    return { duplicate: true };
  }
  combatants.push(combatant);
  const round = encounter.round ?? 1;
  const turnIndex = encounter.turn_index ?? 0;
  const stmt = db.prepare('UPDATE play_encounters SET combatants_json = ?, order_json = ?, round = ?, turn_index = ? WHERE campaign_id = ? AND id = ?');
  stmt.run(JSON.stringify(combatants), '[]', round, turnIndex, campaignId, encounterId);
  return { combatant };
}

// Internal helper: remove a combatant from an encounter by key. If the
// roster becomes empty, reset round/turn; otherwise keep the turn index in
// bounds.
function removeCombatant(campaignId, encounterId, keyValue, keyFn) {
  const encounter = getPlayEncounter(campaignId, encounterId);
  if (!encounter) return null;
  const combatants = encounter.combatants ?? [];
  const index = combatants.findIndex(c => keyFn(c) === keyValue);
  if (index === -1) return { notFound: true };
  combatants.splice(index, 1);
  let round = encounter.round ?? 1;
  let turnIndex = encounter.turn_index ?? 0;
  if (combatants.length === 0) {
    round = 1;
    turnIndex = 0;
  } else if (turnIndex >= combatants.length) {
    turnIndex = 0;
  }
  const stmt = db.prepare('UPDATE play_encounters SET combatants_json = ?, order_json = ?, round = ?, turn_index = ? WHERE campaign_id = ? AND id = ?');
  stmt.run(JSON.stringify(combatants), '[]', round, turnIndex, campaignId, encounterId);
  return { removed: true };
}

export function addEncounterCombatant(campaignId, encounterId, combatant) {
  return addCombatant(campaignId, encounterId, combatant, c => c.monster_id);
}

export function removeEncounterCombatant(campaignId, encounterId, monsterId) {
  return removeCombatant(campaignId, encounterId, monsterId, c => c.monster_id);
}

export function addEncounterMemberCombatant(campaignId, encounterId, combatant) {
  return addCombatant(campaignId, encounterId, combatant, c => c.member);
}

export function removeEncounterMemberCombatant(campaignId, encounterId, member) {
  return removeCombatant(campaignId, encounterId, member, c => c.member);
}

export function advancePlayEncounterTurn(campaignId, encounterId, round, turnIndex) {
  const stmt = db.prepare('UPDATE play_encounters SET round = ?, turn_index = ? WHERE campaign_id = ? AND id = ?');
  stmt.run(round, turnIndex, campaignId, encounterId);
}

export function updateEncounterCombatants(campaignId, encounterId, combatants) {
  const stmt = db.prepare('UPDATE play_encounters SET combatants_json = ? WHERE campaign_id = ? AND id = ?');
  stmt.run(JSON.stringify(combatants), campaignId, encounterId);
}

export function getEncounterReward(campaignId, encounterId) {
  const stmt = db.prepare('SELECT campaign_id, encounter_id, xp, loot_json FROM play_encounter_rewards WHERE campaign_id = ? AND encounter_id = ?');
  const row = stmt.get(campaignId, encounterId);
  if (!row) return null;
  return {
    campaign_id: row.campaign_id,
    encounter_id: row.encounter_id,
    xp: row.xp,
    loot: parseJson(row.loot_json),
  };
}

export function createEncounterReward(campaignId, encounterId, xp, loot) {
  const stmt = db.prepare('INSERT INTO play_encounter_rewards (campaign_id, encounter_id, xp, loot_json) VALUES (?, ?, ?, ?)');
  stmt.run(campaignId, encounterId, xp, JSON.stringify(loot));
}

export function closePlayEncounter(campaignId, encounterId) {
  const stmt = db.prepare("UPDATE play_encounters SET status = 'closed' WHERE campaign_id = ? AND id = ?");
  stmt.run(campaignId, encounterId);
}

export function updateEncounterConditions(campaignId, encounterId, conditions) {
  const stmt = db.prepare('UPDATE play_encounters SET conditions_json = ? WHERE campaign_id = ? AND id = ?');
  stmt.run(JSON.stringify(conditions ?? {}), campaignId, encounterId);
}

export function updateEncounterOrder(campaignId, encounterId, order, turnIndex) {
  const stmt = db.prepare('UPDATE play_encounters SET order_json = ?, turn_index = ? WHERE campaign_id = ? AND id = ?');
  stmt.run(JSON.stringify(order), turnIndex, campaignId, encounterId);
}

// Play locations

export function getPlayLocation(campaignId, locationId) {
  const stmt = db.prepare('SELECT campaign_id, id, name FROM play_locations WHERE campaign_id = ? AND id = ?');
  return stmt.get(campaignId, locationId) ?? null;
}

export function getPlayLocations(campaignId) {
  const stmt = db.prepare('SELECT campaign_id, id, name FROM play_locations WHERE campaign_id = ? ORDER BY id');
  return stmt.all(campaignId);
}

export function getFirstPlayLocation(campaignId) {
  const stmt = db.prepare('SELECT campaign_id, id, name FROM play_locations WHERE campaign_id = ? ORDER BY rowid LIMIT 1');
  return stmt.get(campaignId) ?? null;
}

export function createPlayLocation(campaignId, location) {
  const stmt = db.prepare('INSERT INTO play_locations (campaign_id, id, name) VALUES (?, ?, ?)');
  stmt.run(campaignId, location.id, location.name);
}

export function getPlayLocationConnection(campaignId, fromId, toId) {
  const stmt = db.prepare('SELECT campaign_id, from_id, to_id, travel_turns FROM play_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?');
  return stmt.get(campaignId, fromId, toId) ?? null;
}

export function getPlayLocationConnections(campaignId, fromId) {
  const stmt = db.prepare('SELECT campaign_id, from_id, to_id, travel_turns FROM play_location_connections WHERE campaign_id = ? AND from_id = ? ORDER BY to_id');
  return stmt.all(campaignId, fromId);
}

export function createPlayLocationConnection(campaignId, fromId, toId, travelTurns) {
  const stmt = db.prepare('INSERT INTO play_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)');
  stmt.run(campaignId, fromId, toId, travelTurns);
}

// Play character inventory

export function addPlayCharacterInventoryItem(campaignId, characterId, itemId, quantity) {
  const stmt = db.prepare(`
    INSERT INTO play_character_inventory (campaign_id, character_id, item_id, quantity)
    VALUES (?, ?, ?, ?)
    ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity
  `);
  stmt.run(campaignId, characterId, itemId, quantity);
}

export function getPlayCharacterInventoryItems(campaignId, characterId) {
  const stmt = db.prepare('SELECT item_id, quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? ORDER BY item_id');
  return stmt.all(campaignId, characterId);
}

export function getPlayCharacterInventoryItem(campaignId, characterId, itemId) {
  const stmt = db.prepare('SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
  return stmt.get(campaignId, characterId, itemId) ?? null;
}

export function setPlayCharacterInventoryItem(campaignId, characterId, itemId, quantity) {
  const stmt = db.prepare('UPDATE play_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
  stmt.run(quantity, campaignId, characterId, itemId);
}

export function deletePlayCharacterInventoryItem(campaignId, characterId, itemId) {
  const stmt = db.prepare('DELETE FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
  stmt.run(campaignId, characterId, itemId);
}

export function getPlayCharacterEquipment(campaignId, characterId, slot) {
  const stmt = db.prepare('SELECT item_id, attuned FROM play_character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?');
  const row = stmt.get(campaignId, characterId, slot);
  if (!row) return null;
  return { item_id: row.item_id, attuned: row.attuned === 1 };
}

export function setPlayCharacterEquipment(campaignId, characterId, slot, itemId, attuned) {
  const stmt = db.prepare(`
    INSERT INTO play_character_equipment (campaign_id, character_id, slot, item_id, attuned)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT (campaign_id, character_id, slot) DO UPDATE SET item_id = excluded.item_id, attuned = excluded.attuned
  `);
  stmt.run(campaignId, characterId, slot, itemId, attuned ? 1 : 0);
}

export function getPlayCharacterAttunedCount(campaignId, characterId) {
  const stmt = db.prepare('SELECT COUNT(*) as count FROM play_character_equipment WHERE campaign_id = ? AND character_id = ? AND attuned = 1');
  const row = stmt.get(campaignId, characterId);
  return row?.count ?? 0;
}

// Play character currency

export function getCharacterCurrency(campaignId, characterId) {
  const stmt = db.prepare('SELECT gold FROM play_character_currency WHERE campaign_id = ? AND character_id = ?');
  const row = stmt.get(campaignId, characterId);
  return row?.gold ?? 10;
}

export function createCharacterCurrency(campaignId, characterId, gold) {
  const stmt = db.prepare('INSERT INTO play_character_currency (campaign_id, character_id, gold) VALUES (?, ?, ?)');
  stmt.run(campaignId, characterId, gold);
}

export function setCharacterCurrency(campaignId, characterId, gold) {
  const stmt = db.prepare(`
    INSERT INTO play_character_currency (campaign_id, character_id, gold)
    VALUES (?, ?, ?)
    ON CONFLICT (campaign_id, character_id) DO UPDATE SET gold = excluded.gold
  `);
  stmt.run(campaignId, characterId, gold);
}

export function transferCurrency(campaignId, fromCharacterId, toCharacterId, gold) {
  db.exec('BEGIN IMMEDIATE');
  try {
    const nextIdStmt = db.prepare('SELECT COALESCE(MAX(transfer_id), 0) + 1 as next FROM play_currency_transfers WHERE campaign_id = ?');
    const transferId = nextIdStmt.get(campaignId).next;

    const fromGoldBefore = getCharacterCurrency(campaignId, fromCharacterId);
    const toGoldBefore = getCharacterCurrency(campaignId, toCharacterId);

    if (fromGoldBefore < gold) {
      db.exec('ROLLBACK');
      return { insufficient: true };
    }

    const fromGold = fromGoldBefore - gold;
    const toGold = toGoldBefore + gold;

    setCharacterCurrency(campaignId, fromCharacterId, fromGold);
    setCharacterCurrency(campaignId, toCharacterId, toGold);

    const insertStmt = db.prepare('INSERT INTO play_currency_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold, from_gold, to_gold) VALUES (?, ?, ?, ?, ?, ?, ?)');
    insertStmt.run(campaignId, transferId, fromCharacterId, toCharacterId, gold, fromGold, toGold);

    db.exec('COMMIT');
    return { transfer_id: transferId, from_gold: fromGold, to_gold: toGold };
  } catch (err) {
    db.exec('ROLLBACK');
    throw err;
  }
}

// Play loot

export function getPlayLoot(campaignId, lootId) {
  const stmt = db.prepare('SELECT campaign_id, loot_id, item_id, quantity, status, recipient_character_id, votes_json FROM play_loot WHERE campaign_id = ? AND loot_id = ?');
  const row = stmt.get(campaignId, lootId) ?? null;
  if (!row) return null;
  return { ...row, votes: parseJson(row.votes_json, []) };
}

export function createPlayLoot(campaignId, loot) {
  const stmt = db.prepare('INSERT INTO play_loot (campaign_id, loot_id, item_id, quantity, status, recipient_character_id, votes_json) VALUES (?, ?, ?, ?, ?, ?, ?)');
  stmt.run(campaignId, loot.loot_id, loot.item_id, loot.quantity, loot.status, loot.recipient_character_id ?? null, JSON.stringify(loot.votes ?? []));
}

export function addPlayLootVote(campaignId, lootId, voter, recipient) {
  db.exec('BEGIN IMMEDIATE');
  try {
    const stmt = db.prepare('SELECT status, votes_json FROM play_loot WHERE campaign_id = ? AND loot_id = ?');
    const row = stmt.get(campaignId, lootId);
    if (!row) {
      db.exec('ROLLBACK');
      return { notFound: true };
    }
    if (row.status !== 'open') {
      db.exec('ROLLBACK');
      return { closed: true };
    }
    const votes = parseJson(row.votes_json, []);
    if (votes.some(v => v.voter === voter)) {
      db.exec('ROLLBACK');
      return { alreadyVoted: true };
    }
    votes.push({ voter, recipient_character_id: recipient });
    const update = db.prepare('UPDATE play_loot SET votes_json = ? WHERE campaign_id = ? AND loot_id = ?');
    update.run(JSON.stringify(votes), campaignId, lootId);
    db.exec('COMMIT');
    return { votes };
  } catch (err) {
    db.exec('ROLLBACK');
    throw err;
  }
}

export function assignPlayLoot(campaignId, lootId, recipientCharacterId) {
  db.exec('BEGIN IMMEDIATE');
  try {
    const stmt = db.prepare('SELECT status, item_id, quantity FROM play_loot WHERE campaign_id = ? AND loot_id = ?');
    const row = stmt.get(campaignId, lootId);
    if (!row) {
      db.exec('ROLLBACK');
      return { notFound: true };
    }
    if (row.status !== 'open') {
      db.exec('ROLLBACK');
      return { alreadyAssigned: true };
    }
    addPlayCharacterInventoryItem(campaignId, recipientCharacterId, row.item_id, row.quantity);
    const update = db.prepare("UPDATE play_loot SET status = 'assigned', recipient_character_id = ? WHERE campaign_id = ? AND loot_id = ?");
    update.run(recipientCharacterId, campaignId, lootId);
    db.exec('COMMIT');
    return { assigned: true };
  } catch (err) {
    db.exec('ROLLBACK');
    throw err;
  }
}

// Play NPCs

export function getPlayNpc(campaignId, npcId) {
  const stmt = db.prepare('SELECT campaign_id, npc_id, name, agenda, public_status FROM play_npcs WHERE campaign_id = ? AND npc_id = ?');
  return stmt.get(campaignId, npcId) ?? null;
}

export function createPlayNpc(campaignId, npc) {
  const stmt = db.prepare('INSERT INTO play_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)');
  stmt.run(campaignId, npc.npc_id, npc.name, npc.agenda, npc.public_status);
}

export function updatePlayNpc(campaignId, npc) {
  const stmt = db.prepare('UPDATE play_npcs SET agenda = ?, public_status = ? WHERE campaign_id = ? AND npc_id = ?');
  stmt.run(npc.agenda, npc.public_status, campaignId, npc.npc_id);
}

export function getPlayNpcDialogue(campaignId, npcId) {
  const stmt = db.prepare('SELECT campaign_id, npc_id, dialogue_id, speaker, text, visibility FROM play_npc_dialogue WHERE campaign_id = ? AND npc_id = ? ORDER BY sequence ASC');
  return stmt.all(campaignId, npcId);
}

export function getPlayNpcDialogueEntry(campaignId, npcId, dialogueId) {
  const stmt = db.prepare('SELECT dialogue_id, speaker, text, visibility FROM play_npc_dialogue WHERE campaign_id = ? AND npc_id = ? AND dialogue_id = ?');
  return stmt.get(campaignId, npcId, dialogueId) ?? null;
}

export function createPlayNpcDialogue(campaignId, npcId, dialogueId, speaker, text, visibility) {
  const nextSeqStmt = db.prepare('SELECT COALESCE(MAX(sequence), 0) + 1 as next FROM play_npc_dialogue WHERE campaign_id = ? AND npc_id = ?');
  const sequence = nextSeqStmt.get(campaignId, npcId).next;
  const stmt = db.prepare('INSERT INTO play_npc_dialogue (campaign_id, npc_id, dialogue_id, speaker, text, visibility, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)');
  stmt.run(campaignId, npcId, dialogueId, speaker, text, visibility, sequence);
}

// Play relationships

export function getPlayRelationship(campaignId, sourceId, targetId, kind) {
  const stmt = db.prepare('SELECT source_id, target_id, kind, score FROM play_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?');
  return stmt.get(campaignId, sourceId, targetId, kind) ?? null;
}

export function getPlayRelationships(campaignId) {
  const stmt = db.prepare('SELECT source_id, target_id, kind, score FROM play_relationships WHERE campaign_id = ? ORDER BY rowid');
  return stmt.all(campaignId);
}

export function createPlayRelationship(campaignId, relationship) {
  const stmt = db.prepare('INSERT INTO play_relationships (campaign_id, source_id, target_id, kind, score) VALUES (?, ?, ?, ?, ?)');
  stmt.run(campaignId, relationship.source_id, relationship.target_id, relationship.kind, relationship.score);
}

export function updatePlayRelationship(campaignId, sourceId, targetId, kind, score) {
  const stmt = db.prepare('UPDATE play_relationships SET score = ? WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?');
  stmt.run(score, campaignId, sourceId, targetId, kind);
}

// Play factions

export function getPlayFaction(campaignId, factionId) {
  const stmt = db.prepare('SELECT campaign_id, faction_id, name FROM play_factions WHERE campaign_id = ? AND faction_id = ?');
  return stmt.get(campaignId, factionId) ?? null;
}

export function createPlayFaction(campaignId, faction) {
  const stmt = db.prepare('INSERT INTO play_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)');
  stmt.run(campaignId, faction.faction_id, faction.name);
}

export function getPlayFactionReputationCurrent(campaignId, factionId, characterId) {
  const stmt = db.prepare('SELECT reputation FROM play_faction_reputation WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY sequence DESC LIMIT 1');
  const row = stmt.get(campaignId, factionId, characterId);
  return row?.reputation ?? null;
}

export function createPlayFactionReputation(campaignId, factionId, characterId, reputation, delta, reason) {
  const nextSeqStmt = db.prepare('SELECT COALESCE(MAX(sequence), 0) + 1 as next FROM play_faction_reputation WHERE campaign_id = ? AND faction_id = ?');
  const sequence = nextSeqStmt.get(campaignId, factionId).next;
  const stmt = db.prepare('INSERT INTO play_faction_reputation (campaign_id, faction_id, character_id, reputation, delta, reason, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)');
  stmt.run(campaignId, factionId, characterId, reputation, delta, reason, sequence);
  return { campaign_id: campaignId, faction_id: factionId, character_id: characterId, reputation, delta, reason, sequence };
}

export function getPlayFactionReputationHistory(campaignId, factionId) {
  const stmt = db.prepare('SELECT faction_id, character_id, reputation, delta, reason FROM play_faction_reputation WHERE campaign_id = ? AND faction_id = ? ORDER BY sequence ASC');
  return stmt.all(campaignId, factionId);
}

export function getPlayFactionReputationHistoryForCharacter(campaignId, factionId, characterId) {
  const stmt = db.prepare('SELECT faction_id, character_id, reputation, delta, reason FROM play_faction_reputation WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY sequence ASC');
  return stmt.all(campaignId, factionId, characterId);
}

// Play clues

export function getPlayClue(campaignId, clueId) {
  const stmt = db.prepare('SELECT campaign_id, clue_id, text, audience, character_id, sequence FROM play_clues WHERE campaign_id = ? AND clue_id = ?');
  return stmt.get(campaignId, clueId) ?? null;
}

export function getPlayClues(campaignId) {
  const stmt = db.prepare('SELECT campaign_id, clue_id, text, audience, character_id, sequence FROM play_clues WHERE campaign_id = ? ORDER BY sequence ASC');
  return stmt.all(campaignId);
}

export function createPlayClue(campaignId, clue) {
  const nextSeqStmt = db.prepare('SELECT COALESCE(MAX(sequence), 0) + 1 as next FROM play_clues WHERE campaign_id = ?');
  const sequence = nextSeqStmt.get(campaignId).next;
  const stmt = db.prepare('INSERT INTO play_clues (campaign_id, clue_id, text, audience, character_id, sequence) VALUES (?, ?, ?, ?, ?, ?)');
  stmt.run(campaignId, clue.clue_id, clue.text, clue.audience, clue.character_id ?? null, sequence);
  return { ...clue, sequence };
}

// Play world events

export function getPlayWorldEvent(campaignId, eventId) {
  const stmt = db.prepare('SELECT campaign_id, event_id, turn_number, title, text, status, resolution_turn_number, resolution_text, sequence FROM play_world_events WHERE campaign_id = ? AND event_id = ?');
  return stmt.get(campaignId, eventId) ?? null;
}

export function getPlayWorldEvents(campaignId) {
  const stmt = db.prepare('SELECT campaign_id, event_id, turn_number, title, text, status, resolution_turn_number, resolution_text, sequence FROM play_world_events WHERE campaign_id = ? ORDER BY turn_number ASC, sequence ASC');
  return stmt.all(campaignId);
}

export function createPlayWorldEvent(campaignId, event) {
  const nextSeqStmt = db.prepare('SELECT COALESCE(MAX(sequence), 0) + 1 as next FROM play_world_events WHERE campaign_id = ?');
  const sequence = nextSeqStmt.get(campaignId).next;
  const stmt = db.prepare('INSERT INTO play_world_events (campaign_id, event_id, turn_number, title, text, status, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)');
  stmt.run(campaignId, event.event_id, event.turn_number, event.title, event.text, 'scheduled', sequence);
  return { ...event, status: 'scheduled', sequence };
}

export function resolvePlayWorldEvent(campaignId, eventId, resolutionTurnNumber, resolutionText) {
  const stmt = db.prepare('UPDATE play_world_events SET status = ?, resolution_turn_number = ?, resolution_text = ? WHERE campaign_id = ? AND event_id = ?');
  stmt.run('resolved', resolutionTurnNumber, resolutionText, campaignId, eventId);
}

// Play quests

export function getPlayQuest(campaignId, questId) {
  const stmt = db.prepare(`
    SELECT q.campaign_id, q.quest_id, q.title, q.depends_on_json, q.state, q.sequence,
           r.xp, r.items_json
    FROM play_quests q
    LEFT JOIN play_quest_rewards r ON q.campaign_id = r.campaign_id AND q.quest_id = r.quest_id
    WHERE q.campaign_id = ? AND q.quest_id = ?
  `);
  const row = stmt.get(campaignId, questId);
  if (!row) return null;
  const quest = {
    campaign_id: row.campaign_id,
    quest_id: row.quest_id,
    title: row.title,
    depends_on: parseJson(row.depends_on_json),
    state: row.state,
    sequence: row.sequence,
  };
  if (row.xp != null) {
    quest.rewards = { xp: row.xp, items: parseJson(row.items_json) };
  }
  return quest;
}

export function getPlayQuests(campaignId) {
  const stmt = db.prepare(`
    SELECT q.campaign_id, q.quest_id, q.title, q.depends_on_json, q.state, q.sequence,
           r.xp, r.items_json
    FROM play_quests q
    LEFT JOIN play_quest_rewards r ON q.campaign_id = r.campaign_id AND q.quest_id = r.quest_id
    WHERE q.campaign_id = ? ORDER BY q.sequence ASC
  `);
  const rows = stmt.all(campaignId);
  return rows.map(row => {
    const quest = {
      campaign_id: row.campaign_id,
      quest_id: row.quest_id,
      title: row.title,
      depends_on: parseJson(row.depends_on_json),
      state: row.state,
      sequence: row.sequence,
    };
    if (row.xp != null) {
      quest.rewards = { xp: row.xp, items: parseJson(row.items_json) };
    }
    return quest;
  });
}

export function createPlayQuest(campaignId, quest) {
  const nextSeqStmt = db.prepare('SELECT COALESCE(MAX(sequence), 0) + 1 as next FROM play_quests WHERE campaign_id = ?');
  const sequence = nextSeqStmt.get(campaignId).next;
  const stmt = db.prepare('INSERT INTO play_quests (campaign_id, quest_id, title, depends_on_json, state, sequence) VALUES (?, ?, ?, ?, ?, ?)');
  stmt.run(campaignId, quest.quest_id, quest.title, JSON.stringify(quest.depends_on), quest.state, sequence);
  return { ...quest, sequence };
}

export function updatePlayQuest(campaignId, quest) {
  const stmt = db.prepare('UPDATE play_quests SET title = ?, depends_on_json = ?, state = ? WHERE campaign_id = ? AND quest_id = ?');
  stmt.run(quest.title, JSON.stringify(quest.depends_on), quest.state, campaignId, quest.quest_id);
}

export function getPlayQuestReward(campaignId, questId) {
  const stmt = db.prepare('SELECT campaign_id, quest_id, xp, items_json, awarded FROM play_quest_rewards WHERE campaign_id = ? AND quest_id = ?');
  const row = stmt.get(campaignId, questId);
  if (!row) return null;
  return {
    campaign_id: row.campaign_id,
    quest_id: row.quest_id,
    xp: row.xp,
    items: parseJson(row.items_json),
    awarded: row.awarded === 1,
  };
}

export function setPlayQuestReward(campaignId, questId, xp, items) {
  const stmt = db.prepare(`
    INSERT INTO play_quest_rewards (campaign_id, quest_id, xp, items_json, awarded)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT (campaign_id, quest_id) DO UPDATE SET xp = excluded.xp, items_json = excluded.items_json
  `);
  stmt.run(campaignId, questId, xp, JSON.stringify(items), 0);
}

export function markPlayQuestRewardAwarded(campaignId, questId) {
  const stmt = db.prepare('UPDATE play_quest_rewards SET awarded = 1 WHERE campaign_id = ? AND quest_id = ?');
  stmt.run(campaignId, questId);
}

export function getPlayCharacterQuestReward(campaignId, characterId) {
  const stmt = db.prepare('SELECT campaign_id, character_id, xp, items_json FROM play_character_quest_rewards WHERE campaign_id = ? AND character_id = ?');
  const row = stmt.get(campaignId, characterId);
  if (!row) return { campaign_id: campaignId, character_id: characterId, xp: 0, items: {} };
  return {
    campaign_id: row.campaign_id,
    character_id: row.character_id,
    xp: row.xp,
    items: parseJson(row.items_json),
  };
}

export function addPlayCharacterQuestReward(campaignId, characterId, xp, items) {
  const current = getPlayCharacterQuestReward(campaignId, characterId);
  const newXp = current.xp + xp;
  const newItems = { ...current.items };
  for (const [itemId, quantity] of Object.entries(items)) {
    newItems[itemId] = (newItems[itemId] || 0) + quantity;
  }
  const stmt = db.prepare(`
    INSERT INTO play_character_quest_rewards (campaign_id, character_id, xp, items_json)
    VALUES (?, ?, ?, ?)
    ON CONFLICT (campaign_id, character_id) DO UPDATE SET xp = excluded.xp, items_json = excluded.items_json
  `);
  stmt.run(campaignId, characterId, newXp, JSON.stringify(newItems));
}
