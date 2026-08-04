/**
 * All SQL access for the application. This module hides the `node:sqlite`
 * `DatabaseSync` API, serializes complex columns to JSON, and exposes typed
 * read/write functions used by the route handlers. No other file should write
 * SQL directly.
 */
import { getDb } from './db.js';
import type {
  AttendanceRecord,
  Campaign,
  CampaignCharacter,
  CampaignDocument,
  CampaignEvent,
  CharacterEquipment,
  CombatAction,
  CombatSession,
  CraftingProject,
  CraftingProjectStatus,
  EncounterReward,
  Faction,
  InventoryItem,
  LootItem,
  Item,
  Location,
  LocationConnection,
  Monster,
  ActionEvent,
  Narration,
  Resolution,
  RestEvent,
  Scene,
  TravelEvent,
  SceneStatus,
  Nudge,
  NPC,
  PlayCampaign,
  PlayEncounter,
  PlayMembership,
  PlayMembershipStatus,
  Quest,
  ReadiedAction,
  QuestStatus,
  RelationshipSummary,
  Role,
  Session,
  User,
} from './types.js';

// Users
export function createUser(user: User): void {
  const db = getDb();
  const insert = db.prepare('INSERT INTO users (username, role, salt, hash) VALUES (?, ?, ?, ?)');
  insert.run(user.username, user.role, user.salt, user.hash);
}

export function getUser(username: string): User | null {
  const db = getDb();
  const stmt = db.prepare('SELECT username, role, salt, hash FROM users WHERE username = ?');
  const row = stmt.get(username) as { username: string; role: Role; salt: string; hash: string } | undefined;
  return row ?? null;
}

export function userExists(username: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM users WHERE username = ?');
  return stmt.get(username) !== undefined;
}

// Combat sessions
export function createCombatSession(session: CombatSession): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO combat_sessions (id, round, turn_index, order_json, conditions_json) VALUES (?, ?, ?, ?, ?)',
  );
  insert.run(
    session.id,
    session.round,
    session.turn_index,
    JSON.stringify(session.order),
    JSON.stringify(session.conditions),
  );
}

export function getCombatSession(id: string): CombatSession | null {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, round, turn_index, order_json, conditions_json FROM combat_sessions WHERE id = ?',
  );
  const row = stmt.get(id) as
    | { id: string; round: number; turn_index: number; order_json: string; conditions_json: string }
    | undefined;
  if (!row) return null;
  return {
    id: row.id,
    round: Number(row.round),
    turn_index: Number(row.turn_index),
    order: JSON.parse(row.order_json) as CombatSession['order'],
    conditions: JSON.parse(row.conditions_json) as CombatSession['conditions'],
  };
}

export function combatSessionExists(id: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM combat_sessions WHERE id = ?');
  return stmt.get(id) !== undefined;
}

export function updateCombatSession(session: CombatSession): void {
  const db = getDb();
  const stmt = db.prepare(
    'UPDATE combat_sessions SET round = ?, turn_index = ?, order_json = ?, conditions_json = ? WHERE id = ?',
  );
  stmt.run(
    session.round,
    session.turn_index,
    JSON.stringify(session.order),
    JSON.stringify(session.conditions),
    session.id,
  );
}

// Monsters
export function createMonster(monster: Monster): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)',
  );
  insert.run(monster.slug, monster.name, monster.cr, monster.armor_class, monster.hit_points, JSON.stringify(monster.tags));
}

export function getMonster(slug: string): Monster | null {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters WHERE slug = ?',
  );
  const row = stmt.get(slug) as
    | { slug: string; name: string; cr: string; armor_class: number; hit_points: number; tags_json: string }
    | undefined;
  if (!row) return null;
  return {
    slug: row.slug,
    name: row.name,
    cr: row.cr,
    armor_class: Number(row.armor_class),
    hit_points: Number(row.hit_points),
    tags: JSON.parse(row.tags_json) as string[],
  };
}

export function monsterExists(slug: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM monsters WHERE slug = ?');
  return stmt.get(slug) !== undefined;
}

export function listMonsterSlugs(): string[] {
  const db = getDb();
  const rows = db.prepare('SELECT slug FROM monsters ORDER BY slug').all() as Array<{ slug: string }>;
  return rows.map((row) => row.slug);
}

// Items
export function createItem(item: Item): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)',
  );
  insert.run(item.slug, item.name, item.type, item.rarity, item.cost_gp);
}

export function getItem(slug: string): Item | null {
  const db = getDb();
  const stmt = db.prepare('SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?');
  const row = stmt.get(slug) as
    | { slug: string; name: string; type: string; rarity: string; cost_gp: number }
    | undefined;
  if (!row) return null;
  return {
    slug: row.slug,
    name: row.name,
    type: row.type,
    rarity: row.rarity,
    cost_gp: Number(row.cost_gp),
  };
}

export function itemExists(slug: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM items WHERE slug = ?');
  return stmt.get(slug) !== undefined;
}

// Campaigns
export function createCampaign(campaign: Campaign): void {
  const db = getDb();
  const insert = db.prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)');
  insert.run(campaign.id, campaign.name, campaign.dm);
}

export function getCampaign(id: string): Campaign | null {
  const db = getDb();
  const stmt = db.prepare('SELECT id, name, dm FROM campaigns WHERE id = ?');
  const row = stmt.get(id) as { id: string; name: string; dm: string } | undefined;
  return row ?? null;
}

export function campaignExists(id: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM campaigns WHERE id = ?');
  return stmt.get(id) !== undefined;
}

// Play campaigns
export function createPlayCampaign(campaign: PlayCampaign): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)',
  );
  insert.run(campaign.id, campaign.name, campaign.owner, campaign.status, campaign.max_players);
}

export function getPlayCampaign(id: string): PlayCampaign | null {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, name, owner, status, max_players, current_actor, turn_number, phase, current_scene_id, current_location_id, pre_combat_actor FROM play_campaigns WHERE id = ?',
  );
  const row = stmt.get(id) as
    | { id: string; name: string; owner: string; status: string; max_players: number; current_actor: string | null; turn_number: number | null; phase: string | null; current_scene_id: string | null; current_location_id: string | null; pre_combat_actor: string | null }
    | undefined;
  if (!row) return null;
  const campaign: PlayCampaign = {
    id: row.id,
    name: row.name,
    owner: row.owner,
    status: row.status as PlayCampaign['status'],
    max_players: Number(row.max_players),
  };
  if (row.current_actor != null) {
    campaign.current_actor = row.current_actor;
  }
  if (row.turn_number != null) {
    campaign.turn_number = Number(row.turn_number);
  }
  if (row.phase != null) {
    campaign.phase = row.phase;
  }
  if (row.current_scene_id != null) {
    campaign.current_scene_id = row.current_scene_id;
  }
  if (row.current_location_id != null) {
    campaign.current_location_id = row.current_location_id;
  }
  if (row.pre_combat_actor != null) {
    campaign.pre_combat_actor = row.pre_combat_actor;
  }
  return campaign;
}

export function playCampaignExists(id: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM play_campaigns WHERE id = ?');
  return stmt.get(id) !== undefined;
}

export function createPlayEncounter(encounter: PlayEncounter): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO play_encounters (id, campaign_id, name, status, round, turn_index, combatants_json, conditions_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
  );
  insert.run(
    encounter.id,
    encounter.campaign_id,
    encounter.name,
    encounter.status,
    encounter.round,
    encounter.turn_index,
    JSON.stringify(encounter.combatants),
    JSON.stringify(encounter.conditions),
  );
}

export function getPlayEncounter(id: string): PlayEncounter | null {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, campaign_id, name, status, round, turn_index, combatants_json, conditions_json FROM play_encounters WHERE id = ?',
  );
  const row = stmt.get(id) as
    | { id: string; campaign_id: string; name: string; status: string; round: number; turn_index: number; combatants_json: string; conditions_json: string }
    | undefined;
  if (!row) return null;
  return {
    id: row.id,
    campaign_id: row.campaign_id,
    name: row.name,
    status: row.status as PlayEncounter['status'],
    round: Number(row.round),
    turn_index: Number(row.turn_index),
    combatants: JSON.parse(row.combatants_json) as PlayEncounter['combatants'],
    conditions: JSON.parse(row.conditions_json) as PlayEncounter['conditions'],
  };
}

export function updatePlayEncounter(encounter: PlayEncounter): void {
  const db = getDb();
  const stmt = db.prepare(
    'UPDATE play_encounters SET round = ?, turn_index = ?, combatants_json = ?, conditions_json = ? WHERE id = ?',
  );
  stmt.run(encounter.round, encounter.turn_index, JSON.stringify(encounter.combatants), JSON.stringify(encounter.conditions), encounter.id);
}

export function updatePlayEncounterCombatants(encounterId: string, combatants: PlayEncounter['combatants']): void {
  const encounter = getPlayEncounter(encounterId);
  if (!encounter) return;

  const currentId = encounter.combatants[encounter.turn_index]?.id;
  const sorted = [...combatants].sort((a, b) => {
    const ai = a.initiative ?? 0;
    const bi = b.initiative ?? 0;
    if (bi !== ai) return bi - ai;
    return a.name.localeCompare(b.name);
  });

  let turnIndex = 0;
  if (currentId && sorted.length > 0) {
    const idx = sorted.findIndex((c) => c.id === currentId);
    if (idx >= 0) turnIndex = idx;
  }

  updatePlayEncounter({ ...encounter, round: encounter.round, turn_index: turnIndex, combatants: sorted });
}

export function playEncounterExists(id: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM play_encounters WHERE id = ?');
  return stmt.get(id) !== undefined;
}

export function updatePlayEncounterStatus(id: string, status: PlayEncounter['status']): void {
  const db = getDb();
  const stmt = db.prepare('UPDATE play_encounters SET status = ? WHERE id = ?');
  stmt.run(status, id);
}

export function createEncounterReward(reward: EncounterReward): void {
  const db = getDb();
  const insert = db.prepare('INSERT INTO encounter_rewards (encounter_id, xp, loot_json) VALUES (?, ?, ?)');
  insert.run(reward.encounter_id, reward.xp, JSON.stringify(reward.loot));
}

export function getEncounterReward(encounterId: string): EncounterReward | null {
  const db = getDb();
  const stmt = db.prepare('SELECT encounter_id, xp, loot_json FROM encounter_rewards WHERE encounter_id = ?');
  const row = stmt.get(encounterId) as
    | { encounter_id: string; xp: number; loot_json: string }
    | undefined;
  if (!row) return null;
  return {
    encounter_id: row.encounter_id,
    xp: Number(row.xp),
    loot: JSON.parse(row.loot_json) as LootItem[],
  };
}

export function encounterRewardExists(encounterId: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM encounter_rewards WHERE encounter_id = ?');
  return stmt.get(encounterId) !== undefined;
}

export function campaignHasActiveEncounter(campaignId: string): boolean {
  const db = getDb();
  const stmt = db.prepare(
    "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND status = 'active'",
  );
  return stmt.get(campaignId) !== undefined;
}

export function countPlayMembers(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM play_members WHERE campaign_id = ?');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

export function getPlayMembers(campaignId: string): PlayMembership[] {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT campaign_id, username, character_id, name, class, hp_current, hp_max, level, con_modifier, status, death_save_successes, death_save_failures, owner FROM play_members WHERE campaign_id = ? ORDER BY rowid',
  );
  const rows = stmt.all(campaignId) as Array<{ campaign_id: string; username: string; character_id: string; name: string; class: string; hp_current: number; hp_max: number; level: number; con_modifier: number; status: string; death_save_successes: number; death_save_failures: number; owner: string | null }>;
  return rows.map((row) => ({
    campaign_id: row.campaign_id,
    username: row.username,
    character_id: row.character_id,
    name: row.name,
    class: row.class,
    hp_current: Number(row.hp_current),
    hp_max: Number(row.hp_max),
    level: Number(row.level),
    con_modifier: Number(row.con_modifier),
    status: row.status as PlayMembership['status'],
    death_save_successes: Number(row.death_save_successes),
    death_save_failures: Number(row.death_save_failures),
    owner: row.owner ?? null,
  }));
}

export function getPlayMembershipByCampaignAndUser(
  campaignId: string,
  username: string,
): PlayMembership | null {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT campaign_id, username, character_id, name, class, hp_current, hp_max, level, con_modifier, status, death_save_successes, death_save_failures, owner FROM play_members WHERE campaign_id = ? AND username = ?',
  );
  const row = stmt.get(campaignId, username) as
    | { campaign_id: string; username: string; character_id: string; name: string; class: string; hp_current: number; hp_max: number; level: number; con_modifier: number; status: string; death_save_successes: number; death_save_failures: number; owner: string | null }
    | undefined;
  if (!row) return null;
  return {
    campaign_id: row.campaign_id,
    username: row.username,
    character_id: row.character_id,
    name: row.name,
    class: row.class,
    hp_current: Number(row.hp_current),
    hp_max: Number(row.hp_max),
    level: Number(row.level),
    con_modifier: Number(row.con_modifier),
    status: row.status as PlayMembership['status'],
    death_save_successes: Number(row.death_save_successes),
    death_save_failures: Number(row.death_save_failures),
    owner: row.owner ?? null,
  };
}

export function getPlayMembershipByCharacterId(characterId: string): PlayMembership | null {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT campaign_id, username, character_id, name, class, hp_current, hp_max, level, con_modifier, status, death_save_successes, death_save_failures, owner FROM play_members WHERE character_id = ?',
  );
  const row = stmt.get(characterId) as
    | { campaign_id: string; username: string; character_id: string; name: string; class: string; hp_current: number; hp_max: number; level: number; con_modifier: number; status: string; death_save_successes: number; death_save_failures: number; owner: string | null }
    | undefined;
  if (!row) return null;
  return {
    campaign_id: row.campaign_id,
    username: row.username,
    character_id: row.character_id,
    name: row.name,
    class: row.class,
    hp_current: Number(row.hp_current),
    hp_max: Number(row.hp_max),
    level: Number(row.level),
    con_modifier: Number(row.con_modifier),
    status: row.status as PlayMembership['status'],
    death_save_successes: Number(row.death_save_successes),
    death_save_failures: Number(row.death_save_failures),
    owner: row.owner ?? null,
  };
}

export function updatePlayMembershipOwner(campaignId: string, characterId: string, owner: string | null): void {
  const db = getDb();
  const stmt = db.prepare(
    'UPDATE play_members SET owner = ? WHERE campaign_id = ? AND character_id = ?',
  );
  stmt.run(owner, campaignId, characterId);
}

export function createPlayMembership(membership: PlayMembership): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO play_members (campaign_id, username, character_id, name, class, hp_current, hp_max, level, con_modifier, status, death_save_successes, death_save_failures, owner) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  );
  insert.run(
    membership.campaign_id,
    membership.username,
    membership.character_id,
    membership.name,
    membership.class,
    membership.hp_current ?? 20,
    membership.hp_max ?? 20,
    membership.level ?? 1,
    membership.con_modifier ?? 0,
    membership.status ?? 'conscious',
    membership.death_save_successes ?? 0,
    membership.death_save_failures ?? 0,
    membership.owner ?? null,
  );
}

export function updatePlayMembershipHp(campaignId: string, username: string, hp_current: number): void {
  const db = getDb();
  const current = getPlayMembershipByCampaignAndUser(campaignId, username);
  let status: PlayMembershipStatus = 'conscious';
  let successes = 0;
  let failures = 0;
  if (current) {
    if (hp_current > 0) {
      status = 'conscious';
      successes = 0;
      failures = 0;
    } else if (hp_current === 0) {
      if (current.status === 'unconscious') {
        status = 'unconscious';
        successes = current.death_save_successes;
        failures = current.death_save_failures;
      } else {
        // Any other status (conscious, stable) that drops to 0 becomes unconscious
        // with a fresh death save sequence.
        status = 'unconscious';
        successes = 0;
        failures = 0;
      }
    } else {
      status = current.status;
      successes = current.death_save_successes;
      failures = current.death_save_failures;
    }
  }
  const stmt = db.prepare(
    'UPDATE play_members SET hp_current = ?, status = ?, death_save_successes = ?, death_save_failures = ? WHERE campaign_id = ? AND username = ?',
  );
  stmt.run(hp_current, status, successes, failures, campaignId, username);
}

export function updatePlayMembershipDeathSaves(
  campaignId: string,
  username: string,
  status: PlayMembershipStatus,
  successes: number,
  failures: number,
): void {
  const db = getDb();
  const stmt = db.prepare(
    'UPDATE play_members SET status = ?, death_save_successes = ?, death_save_failures = ? WHERE campaign_id = ? AND username = ?',
  );
  stmt.run(status, successes, failures, campaignId, username);
}

export function updatePlayMembershipBuild(
  campaignId: string,
  username: string,
  className: string,
  hpMax: number,
  conModifier: number,
): void {
  const db = getDb();
  const stmt = db.prepare(
    'UPDATE play_members SET class = ?, hp_current = ?, hp_max = ?, con_modifier = ?, level = ?, status = ?, death_save_successes = ?, death_save_failures = ? WHERE campaign_id = ? AND username = ?',
  );
  stmt.run(className, hpMax, hpMax, conModifier, 1, 'conscious', 0, 0, campaignId, username);
}

export function updatePlayMembershipLevel(
  campaignId: string,
  username: string,
  level: number,
  hpMax: number,
): void {
  const db = getDb();
  const stmt = db.prepare(
    'UPDATE play_members SET level = ?, hp_max = ? WHERE campaign_id = ? AND username = ?',
  );
  stmt.run(level, hpMax, campaignId, username);
}

// Narrations
export function createNarration(narration: Narration): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO narrations (id, campaign_id, sequence, actor, text) VALUES (?, ?, ?, ?, ?)',
  );
  insert.run(narration.id, narration.campaign_id, narration.sequence, narration.actor, narration.text);
}

export function countNarrations(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM narrations WHERE campaign_id = ?');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

export function getNarrations(campaignId: string): Narration[] {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, campaign_id, sequence, actor, text FROM narrations WHERE campaign_id = ? ORDER BY sequence',
  );
  const rows = stmt.all(campaignId) as Array<{
    id: string;
    campaign_id: string;
    sequence: number;
    actor: string;
    text: string;
  }>;
  return rows.map((row) => ({
    id: row.id,
    campaign_id: row.campaign_id,
    sequence: Number(row.sequence),
    actor: row.actor as Narration['actor'],
    text: row.text,
  }));
}

export function createAction(action: ActionEvent): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO actions (id, campaign_id, sequence, actor, type, text) VALUES (?, ?, ?, ?, ?, ?)',
  );
  insert.run(action.id, action.campaign_id, action.sequence, action.actor, action.type, action.text);
}

export function countActions(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM actions WHERE campaign_id = ?');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

export function createResolution(resolution: Resolution): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO resolutions (id, campaign_id, sequence, actor, text) VALUES (?, ?, ?, ?, ?)',
  );
  insert.run(resolution.id, resolution.campaign_id, resolution.sequence, resolution.actor, resolution.text);
}

export function countResolutions(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM resolutions WHERE campaign_id = ?');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

export function getResolutions(campaignId: string): Resolution[] {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, campaign_id, sequence, actor, text FROM resolutions WHERE campaign_id = ? ORDER BY sequence',
  );
  const rows = stmt.all(campaignId) as Array<{
    id: string;
    campaign_id: string;
    sequence: number;
    actor: string;
    text: string;
  }>;
  return rows.map((row) => ({
    id: row.id,
    campaign_id: row.campaign_id,
    sequence: Number(row.sequence),
    actor: row.actor as Resolution['actor'],
    text: row.text,
  }));
}

export function countEvents(campaignId: string): number {
  return (
    countNarrations(campaignId) +
    countActions(campaignId) +
    countResolutions(campaignId) +
    countTravels(campaignId) +
    countNudges(campaignId) +
    countScenes(campaignId) +
    countRests(campaignId) +
    countCombatActions(campaignId)
  );
}

export function createCombatAction(action: CombatAction): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO combat_actions (id, campaign_id, encounter_id, sequence, actor, type, target, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
  );
  insert.run(action.id, action.campaign_id, action.encounter_id, action.sequence, action.actor, action.type, action.target, action.text);
}

export function countCombatActions(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM combat_actions WHERE campaign_id = ?');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

export function createReadiedAction(action: ReadiedAction): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO readied_actions (id, encounter_id, actor, trigger) VALUES (?, ?, ?, ?)',
  );
  insert.run(action.id, action.encounter_id, action.actor, action.trigger);
}

export function countReadiedActions(encounterId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM readied_actions WHERE encounter_id = ?');
  const row = stmt.get(encounterId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

export function getReadiedActions(encounterId: string): ReadiedAction[] {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, encounter_id, actor, trigger FROM readied_actions WHERE encounter_id = ? ORDER BY rowid',
  );
  const rows = stmt.all(encounterId) as Array<{
    id: string;
    encounter_id: string;
    actor: string;
    trigger: string;
  }>;
  return rows.map((row) => ({
    id: row.id,
    encounter_id: row.encounter_id,
    actor: row.actor,
    trigger: row.trigger,
  }));
}

export function createTravel(travel: TravelEvent): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO travels (id, campaign_id, sequence, actor, destination_id, travel_turns) VALUES (?, ?, ?, ?, ?, ?)',
  );
  insert.run(travel.id, travel.campaign_id, travel.sequence, travel.actor, travel.destination_id, travel.travel_turns);
}

export function countTravels(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM travels WHERE campaign_id = ?');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

export function getTravels(campaignId: string): TravelEvent[] {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, campaign_id, sequence, actor, destination_id, travel_turns FROM travels WHERE campaign_id = ? ORDER BY sequence',
  );
  const rows = stmt.all(campaignId) as Array<{
    id: string;
    campaign_id: string;
    sequence: number;
    actor: string;
    destination_id: string;
    travel_turns: number;
  }>;
  return rows.map((row) => ({
    id: row.id,
    campaign_id: row.campaign_id,
    sequence: Number(row.sequence),
    actor: row.actor,
    destination_id: row.destination_id,
    travel_turns: Number(row.travel_turns),
  }));
}

export function createRest(rest: RestEvent): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO rests (id, campaign_id, sequence, actor, type, hp_current, hp_max) VALUES (?, ?, ?, ?, ?, ?, ?)',
  );
  insert.run(rest.id, rest.campaign_id, rest.sequence, rest.actor, rest.type, rest.hp_current, rest.hp_max);
}

export function countRests(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM rests WHERE campaign_id = ?');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

export function getRests(campaignId: string): RestEvent[] {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, campaign_id, sequence, actor, type, hp_current, hp_max FROM rests WHERE campaign_id = ? ORDER BY sequence',
  );
  const rows = stmt.all(campaignId) as Array<{
    id: string;
    campaign_id: string;
    sequence: number;
    actor: string;
    type: string;
    hp_current: number;
    hp_max: number;
  }>;
  return rows.map((row) => ({
    id: row.id,
    campaign_id: row.campaign_id,
    sequence: Number(row.sequence),
    actor: row.actor,
    type: row.type as RestEvent['type'],
    hp_current: Number(row.hp_current),
    hp_max: Number(row.hp_max),
  }));
}

export function getLocationConnection(
  fromId: string,
  toId: string,
  campaignId: string,
): { from_id: string; to_id: string; travel_turns: number } | null {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT from_id, to_id, travel_turns FROM location_connections WHERE from_id = ? AND to_id = ? AND campaign_id = ?',
  );
  const row = stmt.get(fromId, toId, campaignId) as
    | { from_id: string; to_id: string; travel_turns: number }
    | undefined;
  if (!row) return null;
  return {
    from_id: row.from_id,
    to_id: row.to_id,
    travel_turns: Number(row.travel_turns),
  };
}

export function getFirstLocation(campaignId: string): Location | null {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, campaign_id, name FROM locations WHERE campaign_id = ? ORDER BY rowid LIMIT 1',
  );
  const row = stmt.get(campaignId) as
    | { id: string; campaign_id: string; name: string }
    | undefined;
  if (!row) return null;
  return {
    id: row.id,
    campaign_id: row.campaign_id,
    name: row.name,
  };
}

// Nudges
export function createNudge(nudge: Nudge): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO nudges (id, campaign_id, turn_number, actor, target, message, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)',
  );
  insert.run(nudge.id, nudge.campaign_id, nudge.turn_number, nudge.actor, nudge.target, nudge.message, nudge.sequence);
}

export function countNudges(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM nudges WHERE campaign_id = ?');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

export function getNudges(campaignId: string): Nudge[] {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, campaign_id, turn_number, actor, target, message, sequence FROM nudges WHERE campaign_id = ? ORDER BY sequence',
  );
  const rows = stmt.all(campaignId) as Array<{
    id: string;
    campaign_id: string;
    turn_number: number;
    actor: string;
    target: string;
    message: string;
    sequence: number;
  }>;
  return rows.map((row) => ({
    id: row.id,
    campaign_id: row.campaign_id,
    turn_number: Number(row.turn_number),
    actor: row.actor,
    target: row.target,
    message: row.message,
    sequence: Number(row.sequence),
  }));
}

export function getActions(campaignId: string): ActionEvent[] {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, campaign_id, sequence, actor, type, text FROM actions WHERE campaign_id = ? ORDER BY sequence',
  );
  const rows = stmt.all(campaignId) as Array<{
    id: string;
    campaign_id: string;
    sequence: number;
    actor: string;
    type: string;
    text: string;
  }>;
  return rows.map((row) => ({
    id: row.id,
    campaign_id: row.campaign_id,
    sequence: Number(row.sequence),
    actor: row.actor,
    type: row.type,
    text: row.text,
  }));
}

export function updatePlayCampaignStatus(campaign: {
  id: string;
  status: PlayCampaign['status'];
  current_actor?: string;
  turn_number?: number;
  phase?: string;
}): void {
  const db = getDb();
  const stmt = db.prepare(
    'UPDATE play_campaigns SET status = ?, current_actor = ?, turn_number = ?, phase = ? WHERE id = ?',
  );
  stmt.run(campaign.status, campaign.current_actor ?? null, campaign.turn_number ?? null, campaign.phase ?? null, campaign.id);
}

export function updatePlayCampaignCurrentScene(campaignId: string, sceneId: string | null): void {
  const db = getDb();
  const stmt = db.prepare('UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?');
  stmt.run(sceneId, campaignId);
}

export function updatePlayCampaignCurrentLocation(campaignId: string, locationId: string | null): void {
  const db = getDb();
  const stmt = db.prepare('UPDATE play_campaigns SET current_location_id = ? WHERE id = ?');
  stmt.run(locationId, campaignId);
}

export function setPlayCampaignPreCombatActor(campaignId: string, actor: string | null): void {
  const db = getDb();
  const stmt = db.prepare('UPDATE play_campaigns SET pre_combat_actor = ? WHERE id = ?');
  stmt.run(actor, campaignId);
}

export function createScene(scene: Scene): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO scenes (id, campaign_id, name, status) VALUES (?, ?, ?, ?)',
  );
  insert.run(scene.id, scene.campaign_id, scene.name, scene.status);
}

export function getScene(id: string, campaignId: string): Scene | null {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, campaign_id, name, status FROM scenes WHERE id = ? AND campaign_id = ?',
  );
  const row = stmt.get(id, campaignId) as
    | { id: string; campaign_id: string; name: string; status: string }
    | undefined;
  if (!row) return null;
  return {
    id: row.id,
    campaign_id: row.campaign_id,
    name: row.name,
    status: row.status as SceneStatus,
  };
}

// Locations
export function createLocation(location: Location): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO locations (id, campaign_id, name) VALUES (?, ?, ?)',
  );
  insert.run(location.id, location.campaign_id, location.name);
}

export function getLocation(id: string, campaignId: string): Location | null {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, campaign_id, name FROM locations WHERE id = ? AND campaign_id = ?',
  );
  const row = stmt.get(id, campaignId) as
    | { id: string; campaign_id: string; name: string }
    | undefined;
  if (!row) return null;
  return {
    id: row.id,
    campaign_id: row.campaign_id,
    name: row.name,
  };
}

export function locationExists(id: string, campaignId: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM locations WHERE id = ? AND campaign_id = ?');
  return stmt.get(id, campaignId) !== undefined;
}

export function createLocationConnection(connection: LocationConnection): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO location_connections (from_id, to_id, campaign_id, travel_turns) VALUES (?, ?, ?, ?)',
  );
  insert.run(connection.from_id, connection.to_id, connection.campaign_id, connection.travel_turns);
}

export function locationConnectionExists(
  fromId: string,
  toId: string,
  campaignId: string,
): boolean {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT 1 FROM location_connections WHERE from_id = ? AND to_id = ? AND campaign_id = ?',
  );
  return stmt.get(fromId, toId, campaignId) !== undefined;
}

export function getLocationConnections(
  fromId: string,
  campaignId: string,
): Array<{ to_id: string; name: string; travel_turns: number }> {
  const db = getDb();
  const stmt = db.prepare(
    `SELECT c.to_id, l.name, c.travel_turns
     FROM location_connections c
     JOIN locations l ON l.id = c.to_id AND l.campaign_id = c.campaign_id
     WHERE c.from_id = ? AND c.campaign_id = ?
     ORDER BY c.to_id`,
  );
  const rows = stmt.all(fromId, campaignId) as Array<{
    to_id: string;
    name: string;
    travel_turns: number;
  }>;
  return rows.map((row) => ({
    to_id: row.to_id,
    name: row.name,
    travel_turns: Number(row.travel_turns),
  }));
}
export function sceneExists(id: string, campaignId: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM scenes WHERE id = ? AND campaign_id = ?');
  return stmt.get(id, campaignId) !== undefined;
}

export function countScenes(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM scenes WHERE campaign_id = ?');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

export function updateSceneStatus(id: string, campaignId: string, status: SceneStatus): void {
  const db = getDb();
  const stmt = db.prepare('UPDATE scenes SET status = ? WHERE id = ? AND campaign_id = ?');
  stmt.run(status, id, campaignId);
}

// Campaign documents
export function getCampaignDocument(campaignId: string): CampaignDocument | null {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT story, dm_notes FROM campaign_documents WHERE campaign_id = ?',
  );
  const row = stmt.get(campaignId) as
    | { story: string; dm_notes: string }
    | undefined;
  return row ?? null;
}

export function setCampaignDocument(campaignId: string, doc: CampaignDocument): void {
  const db = getDb();
  const stmt = db.prepare(
    `INSERT INTO campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, ?)
     ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story, dm_notes = excluded.dm_notes`,
  );
  stmt.run(campaignId, doc.story, doc.dm_notes);
}

// Campaign characters
export function createCampaignCharacter(campaignId: string, character: CampaignCharacter): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)',
  );
  insert.run(character.id, campaignId, character.name, character.level, character.class);
}

export function getCampaignCharacters(campaignId: string): CampaignCharacter[] {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid',
  );
  const rows = stmt.all(campaignId) as Array<{ id: string; name: string; level: number; class: string }>;
  return rows.map((row) => ({
    id: row.id,
    name: row.name,
    level: Number(row.level),
    class: row.class,
  }));
}

export function campaignCharacterExists(id: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM campaign_characters WHERE id = ?');
  return stmt.get(id) !== undefined;
}

export function countCampaignCharacters(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM campaign_characters WHERE campaign_id = ?');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

// Campaign events
export function createCampaignEvent(campaignId: string, event: CampaignEvent): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)',
  );
  insert.run(event.id, campaignId, event.kind, event.summary ?? null);
}

export function countCampaignEvents(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM campaign_events WHERE campaign_id = ?');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

export function campaignEventExists(id: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM campaign_events WHERE id = ?');
  return stmt.get(id) !== undefined;
}

export function getCampaignEvents(campaignId: string): CampaignEvent[] {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY rowid',
  );
  const rows = stmt.all(campaignId) as Array<{ id: string; kind: string; summary: string | null }>;
  return rows.map((row) => ({
    id: row.id,
    kind: row.kind,
    summary: row.summary ?? undefined,
  }));
}

// Quests
export function createQuest(quest: Quest): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO quests (id, campaign_id, title, status, milestones_json, done_milestones_json) VALUES (?, ?, ?, ?, ?, ?)',
  );
  insert.run(
    quest.id,
    quest.campaign_id,
    quest.title,
    quest.status,
    JSON.stringify(quest.milestones),
    JSON.stringify(quest.done_milestones),
  );
}

export function getQuest(id: string): Quest | null {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, campaign_id, title, status, milestones_json, done_milestones_json FROM quests WHERE id = ?',
  );
  const row = stmt.get(id) as
    | { id: string; campaign_id: string; title: string; status: QuestStatus; milestones_json: string; done_milestones_json: string }
    | undefined;
  if (!row) return null;
  return {
    id: row.id,
    campaign_id: row.campaign_id,
    title: row.title,
    status: row.status,
    milestones: JSON.parse(row.milestones_json) as string[],
    done_milestones: JSON.parse(row.done_milestones_json) as string[],
  };
}

export function questExists(id: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM quests WHERE id = ?');
  return stmt.get(id) !== undefined;
}

export function updateQuest(quest: Quest): void {
  const db = getDb();
  const stmt = db.prepare(
    'UPDATE quests SET campaign_id = ?, title = ?, status = ?, milestones_json = ?, done_milestones_json = ? WHERE id = ?',
  );
  stmt.run(
    quest.campaign_id,
    quest.title,
    quest.status,
    JSON.stringify(quest.milestones),
    JSON.stringify(quest.done_milestones),
    quest.id,
  );
}

export function countQuestsByStatus(campaignId: string): Record<QuestStatus, number> {
  const db = getDb();
  const stmt = db.prepare('SELECT status, COUNT(*) as c FROM quests WHERE campaign_id = ? GROUP BY status');
  const rows = stmt.all(campaignId) as Array<{ status: QuestStatus; c: number }>;
  const counts: Record<QuestStatus, number> = { active: 0, completed: 0, blocked: 0 };
  for (const row of rows) {
    counts[row.status] = Number(row.c);
  }
  return counts;
}

export function countCampaignQuests(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM quests WHERE campaign_id = ?');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

export function countActiveQuests(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare("SELECT COUNT(*) as c FROM quests WHERE campaign_id = ? AND status = 'active'");
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

// Factions
export function createFaction(faction: Faction): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)',
  );
  insert.run(faction.id, faction.campaign_id, faction.name, faction.stance);
}

export function getFaction(id: string): Faction | null {
  const db = getDb();
  const stmt = db.prepare('SELECT id, campaign_id, name, stance FROM factions WHERE id = ?');
  const row = stmt.get(id) as { id: string; campaign_id: string; name: string; stance: string } | undefined;
  if (!row) return null;
  return {
    id: row.id,
    campaign_id: row.campaign_id,
    name: row.name,
    stance: row.stance,
  };
}

export function factionExists(id: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM factions WHERE id = ?');
  return stmt.get(id) !== undefined;
}

export function countFactions(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM factions WHERE campaign_id = ?');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

// NPCs
export function createNPC(npc: NPC): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO npcs (id, campaign_id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)',
  );
  insert.run(npc.id, npc.campaign_id, npc.name, npc.faction_id ?? null, npc.disposition);
}

export function getNPC(id: string): NPC | null {
  const db = getDb();
  const stmt = db.prepare('SELECT id, campaign_id, name, faction_id, disposition FROM npcs WHERE id = ?');
  const row = stmt.get(id) as
    | { id: string; campaign_id: string; name: string; faction_id: string | null; disposition: number }
    | undefined;
  if (!row) return null;
  return {
    id: row.id,
    campaign_id: row.campaign_id,
    name: row.name,
    faction_id: row.faction_id ?? undefined,
    disposition: Number(row.disposition),
  };
}

export function npcExists(id: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM npcs WHERE id = ?');
  return stmt.get(id) !== undefined;
}

export function countNPCs(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM npcs WHERE campaign_id = ?');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

export function countFriendlyNPCs(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM npcs WHERE campaign_id = ? AND disposition > 0');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

export function getRelationshipSummary(campaignId: string): RelationshipSummary {
  return {
    campaign_id: campaignId,
    factions: countFactions(campaignId),
    npcs: countNPCs(campaignId),
    friendly_npcs: countFriendlyNPCs(campaignId),
  };
}

// Inventory
export function addInventoryItem(
  campaignId: string,
  itemSlug: string,
  quantity: number,
  owner: string,
): void {
  const db = getDb();
  const existing = db
    .prepare(
      'SELECT quantity FROM inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
    )
    .get(campaignId, itemSlug, owner) as { quantity: number } | undefined;
  if (existing) {
    db.prepare(
      'UPDATE inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
    ).run(existing.quantity + quantity, campaignId, itemSlug, owner);
  } else {
    const id = `${campaignId}-${itemSlug}-${owner}`;
    db.prepare(
      'INSERT INTO inventory (id, campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?, ?)',
    ).run(id, campaignId, itemSlug, quantity, owner);
  }
}

export function getPartyInventoryItem(campaignId: string, itemSlug: string): InventoryItem | null {
  const db = getDb();
  const row = db
    .prepare(
      'SELECT item_slug, quantity, owner FROM inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
    )
    .get(campaignId, itemSlug, 'party') as
    | { item_slug: string; quantity: number; owner: string }
    | undefined;
  if (!row) return null;
  return {
    item_slug: row.item_slug,
    quantity: Number(row.quantity),
    owner: row.owner,
  };
}

export function countInventoryRows(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM inventory WHERE campaign_id = ?');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

export function sumInventoryQuantity(
  campaignId: string,
  itemSlug: string,
  owner: string,
): number {
  const db = getDb();
  const row = db
    .prepare(
      'SELECT COALESCE(SUM(quantity), 0) as c FROM inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
    )
    .get(campaignId, itemSlug, owner) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

export function decrementInventory(
  campaignId: string,
  itemSlug: string,
  owner: string,
  quantity: number,
): void {
  const db = getDb();
  const existing = db
    .prepare(
      'SELECT quantity FROM inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
    )
    .get(campaignId, itemSlug, owner) as { quantity: number } | undefined;
  if (!existing) {
    throw new Error('insufficient quantity');
  }
  const newQty = existing.quantity - quantity;
  if (newQty < 0) {
    throw new Error('insufficient quantity');
  }
  if (newQty === 0) {
    db.prepare(
      'DELETE FROM inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
    ).run(campaignId, itemSlug, owner);
  } else {
    db.prepare(
      'UPDATE inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
    ).run(newQty, campaignId, itemSlug, owner);
  }
}

// Equipment
export function addCharacterEquipment(
  campaignId: string,
  characterId: string,
  itemSlug: string,
  quantity: number,
): void {
  const db = getDb();
  const existing = db
    .prepare(
      'SELECT quantity FROM equipment WHERE campaign_id = ? AND character_id = ? AND item_slug = ?',
    )
    .get(campaignId, characterId, itemSlug) as { quantity: number } | undefined;
  if (existing) {
    db.prepare(
      'UPDATE equipment SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_slug = ?',
    ).run(existing.quantity + quantity, campaignId, characterId, itemSlug);
  } else {
    const id = `${campaignId}-${characterId}-${itemSlug}`;
    db.prepare(
      'INSERT INTO equipment (id, campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?, ?)',
    ).run(id, campaignId, characterId, itemSlug, quantity);
  }
}

export function countEquipmentRows(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM equipment WHERE campaign_id = ?');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

export function campaignCharacterInCampaign(characterId: string, campaignId: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM campaign_characters WHERE id = ? AND campaign_id = ?');
  return stmt.get(characterId, campaignId) !== undefined;
}

// Crafting projects
export function createCraftingProject(project: CraftingProject): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO crafting_projects (id, campaign_id, character_id, item_slug, days_required, days_completed, status, cost_gp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
  );
  insert.run(
    project.id,
    project.campaign_id,
    project.character_id,
    project.item_slug,
    project.days_required,
    project.days_completed,
    project.status,
    project.cost_gp,
  );
}

export function getCraftingProject(id: string): CraftingProject | null {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, campaign_id, character_id, item_slug, days_required, days_completed, status, cost_gp FROM crafting_projects WHERE id = ?',
  );
  const row = stmt.get(id) as
    | {
        id: string;
        campaign_id: string;
        character_id: string;
        item_slug: string;
        days_required: number;
        days_completed: number;
        status: CraftingProjectStatus;
        cost_gp: number;
      }
    | undefined;
  if (!row) return null;
  return {
    id: row.id,
    campaign_id: row.campaign_id,
    character_id: row.character_id,
    item_slug: row.item_slug,
    days_required: Number(row.days_required),
    days_completed: Number(row.days_completed),
    status: row.status,
    cost_gp: Number(row.cost_gp),
  };
}

export function craftingProjectExists(id: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM crafting_projects WHERE id = ?');
  return stmt.get(id) !== undefined;
}

export function updateCraftingProject(project: CraftingProject): void {
  const db = getDb();
  const stmt = db.prepare(
    'UPDATE crafting_projects SET campaign_id = ?, character_id = ?, item_slug = ?, days_required = ?, days_completed = ?, status = ?, cost_gp = ? WHERE id = ?',
  );
  stmt.run(
    project.campaign_id,
    project.character_id,
    project.item_slug,
    project.days_required,
    project.days_completed,
    project.status,
    project.cost_gp,
    project.id,
  );
}

// Sessions
export function createSession(session: Session): void {
  const db = getDb();
  const insert = db.prepare(
    'INSERT INTO sessions (id, campaign_id, starts_at, duration_minutes, agenda_json) VALUES (?, ?, ?, ?, ?)',
  );
  insert.run(
    session.id,
    session.campaign_id,
    session.starts_at,
    session.duration_minutes,
    JSON.stringify(session.agenda),
  );
}

export function getSession(id: string): Session | null {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, campaign_id, starts_at, duration_minutes, agenda_json FROM sessions WHERE id = ?',
  );
  const row = stmt.get(id) as
    | { id: string; campaign_id: string; starts_at: string; duration_minutes: number; agenda_json: string }
    | undefined;
  if (!row) return null;
  return {
    id: row.id,
    campaign_id: row.campaign_id,
    starts_at: row.starts_at,
    duration_minutes: Number(row.duration_minutes),
    agenda: JSON.parse(row.agenda_json) as string[],
  };
}

export function sessionExists(id: string): boolean {
  const db = getDb();
  const stmt = db.prepare('SELECT 1 FROM sessions WHERE id = ?');
  return stmt.get(id) !== undefined;
}

export function getNextSession(campaignId: string): Session | null {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT id, campaign_id, starts_at, duration_minutes, agenda_json FROM sessions WHERE campaign_id = ? ORDER BY starts_at ASC LIMIT 1',
  );
  const row = stmt.get(campaignId) as
    | { id: string; campaign_id: string; starts_at: string; duration_minutes: number; agenda_json: string }
    | undefined;
  if (!row) return null;
  return {
    id: row.id,
    campaign_id: row.campaign_id,
    starts_at: row.starts_at,
    duration_minutes: Number(row.duration_minutes),
    agenda: JSON.parse(row.agenda_json) as string[],
  };
}

export function countCampaignSessions(campaignId: string): number {
  const db = getDb();
  const stmt = db.prepare('SELECT COUNT(*) as c FROM sessions WHERE campaign_id = ?');
  const row = stmt.get(campaignId) as { c: number } | undefined;
  return row ? Number(row.c) : 0;
}

// Session attendance
export function recordAttendance(sessionId: string, records: AttendanceRecord[]): void {
  const db = getDb();
  db.prepare('DELETE FROM session_attendance WHERE session_id = ?').run(sessionId);
  const insert = db.prepare(
    'INSERT INTO session_attendance (session_id, character_id, present) VALUES (?, ?, ?)',
  );
  for (const record of records) {
    insert.run(record.session_id, record.character_id, record.present ? 1 : 0);
  }
}

export function countAttendance(sessionId: string): { present: number; absent: number } {
  const db = getDb();
  const stmt = db.prepare(
    'SELECT present, COUNT(*) as c FROM session_attendance WHERE session_id = ? GROUP BY present',
  );
  const rows = stmt.all(sessionId) as Array<{ present: number; c: number }>;
  const counts = { present: 0, absent: 0 };
  for (const row of rows) {
    if (row.present === 1) {
      counts.present = Number(row.c);
    } else {
      counts.absent = Number(row.c);
    }
  }
  return counts;
}
