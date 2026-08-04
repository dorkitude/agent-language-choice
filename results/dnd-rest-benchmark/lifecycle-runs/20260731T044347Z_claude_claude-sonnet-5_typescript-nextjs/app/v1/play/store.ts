import { getDb } from "../db.js";

export type PlayCampaignStatus = "lobby" | "active";
export type PlayCampaignPhase = "exploration" | "combat";

export interface PlayCampaign {
  id: string;
  name: string;
  owner: string;
  status: PlayCampaignStatus;
  max_players: number;
  current_actor?: string;
  turn_number?: number;
  nudge_count?: number;
  story?: string;
  dm_notes?: string;
  current_scene_id?: string;
  current_location_id?: string;
  phase?: PlayCampaignPhase;
  pre_combat_actor?: string;
  session_zero?: PlaySessionZero;
}

export interface PlaySessionZero {
  rules: string;
  tone: string;
  consent: string[];
}

export function hasPlayCampaign(id: string): boolean {
  const row = getDb().prepare("SELECT id FROM play_campaigns WHERE id = ?").get(id);
  return row !== undefined;
}

export function getPlayCampaign(id: string): PlayCampaign | undefined {
  const row = getDb().prepare("SELECT data FROM play_campaigns WHERE id = ?").get(id) as
    | { data: string }
    | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayCampaign;
}

export function createPlayCampaign(campaign: PlayCampaign): PlayCampaign {
  getDb()
    .prepare("INSERT INTO play_campaigns (id, data) VALUES (?, ?)")
    .run(campaign.id, JSON.stringify(campaign));
  return campaign;
}

export function updatePlayCampaign(campaign: PlayCampaign): PlayCampaign {
  getDb()
    .prepare("UPDATE play_campaigns SET data = ? WHERE id = ?")
    .run(JSON.stringify(campaign), campaign.id);
  return campaign;
}

export type PlayMemberStatus = "conscious" | "unconscious" | "stable" | "dead";

export interface PlayMember {
  campaign_id: string;
  username: string;
  character_id: string;
  name: string;
  class: string;
  hp_current?: number;
  hp_max?: number;
  status?: PlayMemberStatus;
  death_save_successes?: number;
  death_save_failures?: number;
  owner?: string;
  race?: string;
  background?: string;
  level?: number;
  con_modifier?: number;
  ability_modifiers?: Partial<Record<"str" | "dex" | "con" | "int" | "wis" | "cha", number>>;
  prepared_spells?: string[];
  concentration?: PlayConcentration | null;
  inventory_items?: PlayInventoryItem[];
  equipment?: Partial<Record<PlayEquipmentSlot, string>>;
  attuned_item_id?: string;
  gold?: number;
}

export const STARTING_GOLD = 10;

export interface PlayInventoryItem {
  item_id: string;
  quantity: number;
}

export const VALID_INVENTORY_ITEM_IDS = [
  "healing-potion",
  "torch",
  "leather-armor",
  "ring-of-protection",
  "amulet-of-health",
] as const;

export type PlayEquipmentSlot = "armor" | "accessory";

export const VALID_EQUIPMENT_SLOTS = ["armor", "accessory"] as const;

export const EQUIPMENT_ITEM_SLOTS: Record<string, PlayEquipmentSlot> = {
  "leather-armor": "armor",
  "ring-of-protection": "accessory",
  "amulet-of-health": "accessory",
};

export const ATTUNABLE_ITEM_IDS = ["ring-of-protection", "amulet-of-health"] as const;

export const CONSUMABLE_ITEM_IDS = ["healing-potion"] as const;

export const MAX_ATTUNEMENTS = 1;

export interface PlayConcentration {
  spell_id: string;
  target: string;
  remaining_turns: number;
}

export function listPlayMembers(campaignId: string): PlayMember[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_members WHERE campaign_id = ?")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayMember);
}

export function getFirstPlayMember(campaignId: string): PlayMember | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_members WHERE campaign_id = ? ORDER BY rowid LIMIT 1")
    .get(campaignId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayMember;
}

export function hasPlayMemberForUser(campaignId: string, username: string): boolean {
  return listPlayMembers(campaignId).some((member) => member.username === username);
}

export function getPlayMemberForUser(campaignId: string, username: string): PlayMember | undefined {
  return listPlayMembers(campaignId).find((member) => member.username === username);
}

export function getPlayMemberByOwner(campaignId: string, username: string): PlayMember | undefined {
  return listPlayMembers(campaignId).find((member) => (member.owner ?? member.username) === username);
}

export function getPlayMemberByCharacterId(
  campaignId: string,
  characterId: string,
): PlayMember | undefined {
  return listPlayMembers(campaignId).find((member) => member.character_id === characterId);
}

export function updatePlayMember(member: PlayMember): PlayMember {
  getDb()
    .prepare("UPDATE play_members SET data = ? WHERE campaign_id = ? AND character_id = ?")
    .run(JSON.stringify(member), member.campaign_id, member.character_id);
  return member;
}

export function hasPlayMemberCharacter(campaignId: string, characterId: string): boolean {
  const row = getDb()
    .prepare("SELECT campaign_id FROM play_members WHERE campaign_id = ? AND character_id = ?")
    .get(campaignId, characterId);
  return row !== undefined;
}

export function createPlayMember(member: PlayMember): PlayMember {
  getDb()
    .prepare("INSERT INTO play_members (campaign_id, character_id, data) VALUES (?, ?, ?)")
    .run(member.campaign_id, member.character_id, JSON.stringify(member));
  return member;
}

export interface PlayEvent {
  sequence: number;
  kind: string;
  actor: string;
  text: string;
  type?: string;
  target?: string;
}

export function getNextPlayEventSequence(campaignId: string): number {
  const row = getDb()
    .prepare("SELECT MAX(sequence) AS max_sequence FROM play_events WHERE campaign_id = ?")
    .get(campaignId) as { max_sequence: number | null };
  return (row.max_sequence ?? 0) + 1;
}

export function createPlayEvent(campaignId: string, event: PlayEvent): PlayEvent {
  getDb()
    .prepare("INSERT INTO play_events (campaign_id, sequence, data) VALUES (?, ?, ?)")
    .run(campaignId, event.sequence, JSON.stringify(event));
  return event;
}

export function listRecentPlayEvents(campaignId: string, limit: number): PlayEvent[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_events WHERE campaign_id = ? ORDER BY sequence DESC LIMIT ?")
    .all(campaignId, limit) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayEvent);
}

export type PlaySceneStatus = "open" | "closed";

export interface PlayScene {
  campaign_id: string;
  id: string;
  name: string;
  status: PlaySceneStatus;
}

export function hasPlayScene(campaignId: string, sceneId: string): boolean {
  const row = getDb()
    .prepare("SELECT campaign_id FROM play_scenes WHERE campaign_id = ? AND id = ?")
    .get(campaignId, sceneId);
  return row !== undefined;
}

export function getPlayScene(campaignId: string, sceneId: string): PlayScene | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_scenes WHERE campaign_id = ? AND id = ?")
    .get(campaignId, sceneId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayScene;
}

export function createPlayScene(scene: PlayScene): PlayScene {
  getDb()
    .prepare("INSERT INTO play_scenes (campaign_id, id, data) VALUES (?, ?, ?)")
    .run(scene.campaign_id, scene.id, JSON.stringify(scene));
  return scene;
}

export function updatePlayScene(scene: PlayScene): PlayScene {
  getDb()
    .prepare("UPDATE play_scenes SET data = ? WHERE campaign_id = ? AND id = ?")
    .run(JSON.stringify(scene), scene.campaign_id, scene.id);
  return scene;
}

export interface PlayLocation {
  campaign_id: string;
  id: string;
  name: string;
}

export function hasPlayLocation(campaignId: string, locationId: string): boolean {
  const row = getDb()
    .prepare("SELECT campaign_id FROM play_locations WHERE campaign_id = ? AND id = ?")
    .get(campaignId, locationId);
  return row !== undefined;
}

export function getPlayLocation(campaignId: string, locationId: string): PlayLocation | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_locations WHERE campaign_id = ? AND id = ?")
    .get(campaignId, locationId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayLocation;
}

export function createPlayLocation(location: PlayLocation): PlayLocation {
  getDb()
    .prepare("INSERT INTO play_locations (campaign_id, id, data) VALUES (?, ?, ?)")
    .run(location.campaign_id, location.id, JSON.stringify(location));
  return location;
}

export function getFirstPlayLocation(campaignId: string): PlayLocation | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_locations WHERE campaign_id = ? ORDER BY rowid LIMIT 1")
    .get(campaignId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayLocation;
}

export interface PlayLocationConnection {
  campaign_id: string;
  from_id: string;
  to_id: string;
  travel_turns: number;
}

export function hasPlayLocationConnection(campaignId: string, fromId: string, toId: string): boolean {
  const row = getDb()
    .prepare(
      "SELECT campaign_id FROM play_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
    )
    .get(campaignId, fromId, toId);
  return row !== undefined;
}

export function createPlayLocationConnection(
  connection: PlayLocationConnection,
): PlayLocationConnection {
  getDb()
    .prepare(
      "INSERT INTO play_location_connections (campaign_id, from_id, to_id, data) VALUES (?, ?, ?, ?)",
    )
    .run(connection.campaign_id, connection.from_id, connection.to_id, JSON.stringify(connection));
  return connection;
}

export function listPlayLocationConnections(
  campaignId: string,
  fromId: string,
): PlayLocationConnection[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_location_connections WHERE campaign_id = ? AND from_id = ?")
    .all(campaignId, fromId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayLocationConnection);
}

export type PlayEncounterStatus = "active" | "resolved" | "closed";

export interface PlayEncounterLootItem {
  slug: string;
  quantity: number;
}

export interface PlayEncounterRewards {
  xp: number;
  loot: PlayEncounterLootItem[];
}

export interface PlayEncounterCombatant {
  member: string;
  character_id: string;
  name: string;
  initiative: number;
}

export interface PlayEncounterMonster {
  monster_id: string;
  name: string;
  hp_max: number;
  initiative: number;
  hp_current: number;
}

export interface PlayEncounterCondition {
  condition: string;
  remaining_rounds: number;
}

export interface PlayEncounter {
  campaign_id: string;
  id: string;
  name: string;
  status: PlayEncounterStatus;
  combatants: PlayEncounterCombatant[];
  monsters?: PlayEncounterMonster[];
  round?: number;
  turn_index?: number;
  conditions?: Record<string, PlayEncounterCondition[]>;
  rewards?: PlayEncounterRewards;
}

export interface PlayEncounterTurnEntry {
  kind: "player" | "monster";
  name: string;
  initiative: number;
  member?: string;
  target: string;
}

// Deterministic initiative order: highest initiative first, ties broken by
// combatants before monsters, then by the order each was added to the
// encounter (both arrays are append-only).
export function getPlayEncounterTurnOrder(encounter: PlayEncounter): PlayEncounterTurnEntry[] {
  const entries: PlayEncounterTurnEntry[] = [
    ...encounter.combatants.map((combatant) => ({
      kind: "player" as const,
      name: combatant.name,
      initiative: combatant.initiative,
      member: combatant.member,
      target: combatant.member,
    })),
    ...(encounter.monsters ?? []).map((monster) => ({
      kind: "monster" as const,
      name: monster.name,
      initiative: monster.initiative,
      target: monster.monster_id,
    })),
  ];
  return entries
    .map((entry, index) => ({ entry, index }))
    .sort((a, b) => b.entry.initiative - a.entry.initiative || a.index - b.index)
    .map(({ entry }) => entry);
}

// Finds the target key (a combatant's member username or a monster's
// monster_id) for a given identifier, if it currently exists in the
// encounter. Used to validate `target` on condition writes.
export function encounterHasTarget(encounter: PlayEncounter, target: string): boolean {
  if (encounter.combatants.some((combatant) => combatant.member === target)) return true;
  if ((encounter.monsters ?? []).some((monster) => monster.monster_id === target)) return true;
  return false;
}

export function hasPlayEncounter(campaignId: string, encounterId: string): boolean {
  const row = getDb()
    .prepare("SELECT campaign_id FROM play_encounters WHERE campaign_id = ? AND id = ?")
    .get(campaignId, encounterId);
  return row !== undefined;
}

export function getPlayEncounter(
  campaignId: string,
  encounterId: string,
): PlayEncounter | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_encounters WHERE campaign_id = ? AND id = ?")
    .get(campaignId, encounterId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayEncounter;
}

export function hasActivePlayEncounter(campaignId: string): boolean {
  const rows = getDb()
    .prepare("SELECT data FROM play_encounters WHERE campaign_id = ?")
    .all(campaignId) as { data: string }[];
  return rows.some((row) => (JSON.parse(row.data) as PlayEncounter).status === "active");
}

export function createPlayEncounter(encounter: PlayEncounter): PlayEncounter {
  getDb()
    .prepare("INSERT INTO play_encounters (campaign_id, id, data) VALUES (?, ?, ?)")
    .run(encounter.campaign_id, encounter.id, JSON.stringify(encounter));
  return encounter;
}

export function updatePlayEncounter(encounter: PlayEncounter): PlayEncounter {
  getDb()
    .prepare("UPDATE play_encounters SET data = ? WHERE campaign_id = ? AND id = ?")
    .run(JSON.stringify(encounter), encounter.campaign_id, encounter.id);
  return encounter;
}

export interface PlaySpell {
  campaign_id: string;
  character_id: string;
  spell_id: string;
  name: string;
  level: number;
}

export function hasPlaySpell(campaignId: string, characterId: string, spellId: string): boolean {
  const row = getDb()
    .prepare(
      "SELECT campaign_id FROM play_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
    )
    .get(campaignId, characterId, spellId);
  return row !== undefined;
}

export function listPlaySpells(campaignId: string, characterId: string): PlaySpell[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_spells WHERE campaign_id = ? AND character_id = ?")
    .all(campaignId, characterId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlaySpell);
}

export function createPlaySpell(spell: PlaySpell): PlaySpell {
  getDb()
    .prepare(
      "INSERT INTO play_spells (campaign_id, character_id, spell_id, data) VALUES (?, ?, ?, ?)",
    )
    .run(spell.campaign_id, spell.character_id, spell.spell_id, JSON.stringify(spell));
  return spell;
}

export interface PlayCast {
  campaign_id: string;
  character_id: string;
  spell_id: string;
  target: string;
  slot_level: number;
  slots_remaining: number;
  sequence: number;
}

export function listPlayCasts(campaignId: string, characterId: string): PlayCast[] {
  const rows = getDb()
    .prepare(
      "SELECT data FROM play_casts WHERE campaign_id = ? AND character_id = ? ORDER BY sequence ASC",
    )
    .all(campaignId, characterId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayCast);
}

export function createPlayCast(cast: PlayCast): PlayCast {
  getDb()
    .prepare(
      "INSERT INTO play_casts (campaign_id, character_id, sequence, data) VALUES (?, ?, ?, ?)",
    )
    .run(cast.campaign_id, cast.character_id, cast.sequence, JSON.stringify(cast));
  return cast;
}

export interface PlayCurrencyTransfer {
  campaign_id: string;
  transfer_id: number;
  from_character_id: string;
  to_character_id: string;
  gold: number;
}

export function getNextPlayTransferId(campaignId: string): number {
  const row = getDb()
    .prepare("SELECT MAX(transfer_id) AS max_id FROM play_currency_transfers WHERE campaign_id = ?")
    .get(campaignId) as { max_id: number | null };
  return (row.max_id ?? 0) + 1;
}

export function createPlayCurrencyTransfer(transfer: PlayCurrencyTransfer): PlayCurrencyTransfer {
  getDb()
    .prepare(
      "INSERT INTO play_currency_transfers (campaign_id, transfer_id, data) VALUES (?, ?, ?)",
    )
    .run(transfer.campaign_id, transfer.transfer_id, JSON.stringify(transfer));
  return transfer;
}

export type PlayLootStatus = "open" | "assigned";

export interface PlayLootVote {
  voter: string;
  recipient_character_id: string;
}

export interface PlayLoot {
  campaign_id: string;
  loot_id: string;
  item_id: string;
  quantity: number;
  status: PlayLootStatus;
  recipient_character_id?: string;
  votes: PlayLootVote[];
}

export function hasPlayLoot(campaignId: string, lootId: string): boolean {
  const row = getDb()
    .prepare("SELECT campaign_id FROM play_loot WHERE campaign_id = ? AND loot_id = ?")
    .get(campaignId, lootId);
  return row !== undefined;
}

export function getPlayLoot(campaignId: string, lootId: string): PlayLoot | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_loot WHERE campaign_id = ? AND loot_id = ?")
    .get(campaignId, lootId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayLoot;
}

export function createPlayLoot(loot: PlayLoot): PlayLoot {
  getDb()
    .prepare("INSERT INTO play_loot (campaign_id, loot_id, data) VALUES (?, ?, ?)")
    .run(loot.campaign_id, loot.loot_id, JSON.stringify(loot));
  return loot;
}

export function updatePlayLoot(loot: PlayLoot): PlayLoot {
  getDb()
    .prepare("UPDATE play_loot SET data = ? WHERE campaign_id = ? AND loot_id = ?")
    .run(JSON.stringify(loot), loot.campaign_id, loot.loot_id);
  return loot;
}

export interface PlayNpc {
  campaign_id: string;
  npc_id: string;
  name: string;
  agenda: string;
  public_status: string;
}

export function hasPlayNpc(campaignId: string, npcId: string): boolean {
  const row = getDb()
    .prepare("SELECT campaign_id FROM play_npcs WHERE campaign_id = ? AND npc_id = ?")
    .get(campaignId, npcId);
  return row !== undefined;
}

export function getPlayNpc(campaignId: string, npcId: string): PlayNpc | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_npcs WHERE campaign_id = ? AND npc_id = ?")
    .get(campaignId, npcId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayNpc;
}

export function createPlayNpc(npc: PlayNpc): PlayNpc {
  getDb()
    .prepare("INSERT INTO play_npcs (campaign_id, npc_id, data) VALUES (?, ?, ?)")
    .run(npc.campaign_id, npc.npc_id, JSON.stringify(npc));
  return npc;
}

export function updatePlayNpc(npc: PlayNpc): PlayNpc {
  getDb()
    .prepare("UPDATE play_npcs SET data = ? WHERE campaign_id = ? AND npc_id = ?")
    .run(JSON.stringify(npc), npc.campaign_id, npc.npc_id);
  return npc;
}

export interface PlayFaction {
  campaign_id: string;
  faction_id: string;
  name: string;
}

export function hasPlayFaction(campaignId: string, factionId: string): boolean {
  const row = getDb()
    .prepare("SELECT campaign_id FROM play_factions WHERE campaign_id = ? AND faction_id = ?")
    .get(campaignId, factionId);
  return row !== undefined;
}

export function getPlayFaction(campaignId: string, factionId: string): PlayFaction | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_factions WHERE campaign_id = ? AND faction_id = ?")
    .get(campaignId, factionId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayFaction;
}

export function createPlayFaction(faction: PlayFaction): PlayFaction {
  getDb()
    .prepare("INSERT INTO play_factions (campaign_id, faction_id, data) VALUES (?, ?, ?)")
    .run(faction.campaign_id, faction.faction_id, JSON.stringify(faction));
  return faction;
}

export const MIN_FACTION_REPUTATION = -100;
export const MAX_FACTION_REPUTATION = 100;

export interface PlayFactionReputationEntry {
  faction_id: string;
  character_id: string;
  reputation: number;
  delta: number;
  reason: string;
}

export function getPlayFactionReputationTotal(
  campaignId: string,
  factionId: string,
  characterId: string,
): number {
  const row = getDb()
    .prepare(
      "SELECT total FROM play_faction_reputation WHERE campaign_id = ? AND faction_id = ? AND character_id = ?",
    )
    .get(campaignId, factionId, characterId) as { total: number } | undefined;
  return row?.total ?? 0;
}

export function setPlayFactionReputationTotal(
  campaignId: string,
  factionId: string,
  characterId: string,
  total: number,
): void {
  getDb()
    .prepare(
      `INSERT INTO play_faction_reputation (campaign_id, faction_id, character_id, total)
       VALUES (?, ?, ?, ?)
       ON CONFLICT (campaign_id, faction_id, character_id) DO UPDATE SET total = excluded.total`,
    )
    .run(campaignId, factionId, characterId, total);
}

function getNextPlayFactionReputationEntryId(campaignId: string, factionId: string): number {
  const row = getDb()
    .prepare(
      "SELECT MAX(entry_id) AS max_id FROM play_faction_reputation_history WHERE campaign_id = ? AND faction_id = ?",
    )
    .get(campaignId, factionId) as { max_id: number | null };
  return (row.max_id ?? 0) + 1;
}

export function createPlayFactionReputationEntry(
  campaignId: string,
  entry: PlayFactionReputationEntry,
): PlayFactionReputationEntry {
  const entryId = getNextPlayFactionReputationEntryId(campaignId, entry.faction_id);
  getDb()
    .prepare(
      "INSERT INTO play_faction_reputation_history (campaign_id, faction_id, entry_id, data) VALUES (?, ?, ?, ?)",
    )
    .run(campaignId, entry.faction_id, entryId, JSON.stringify(entry));
  return entry;
}

export function listPlayFactionReputationEntries(
  campaignId: string,
  factionId: string,
): PlayFactionReputationEntry[] {
  const rows = getDb()
    .prepare(
      "SELECT data FROM play_faction_reputation_history WHERE campaign_id = ? AND faction_id = ? ORDER BY entry_id ASC",
    )
    .all(campaignId, factionId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayFactionReputationEntry);
}

export interface PlayNpcDialogueEntry {
  dialogue_id: string;
  speaker: string;
  text: string;
  visibility: "public" | "private";
}

export function hasPlayNpcDialogueEntry(
  campaignId: string,
  npcId: string,
  dialogueId: string,
): boolean {
  const row = getDb()
    .prepare(
      "SELECT 1 FROM play_npc_dialogue WHERE campaign_id = ? AND npc_id = ? AND dialogue_id = ?",
    )
    .get(campaignId, npcId, dialogueId);
  return row !== undefined;
}

function getNextPlayNpcDialogueEntryId(campaignId: string, npcId: string): number {
  const row = getDb()
    .prepare(
      "SELECT MAX(entry_id) AS max_id FROM play_npc_dialogue WHERE campaign_id = ? AND npc_id = ?",
    )
    .get(campaignId, npcId) as { max_id: number | null };
  return (row.max_id ?? 0) + 1;
}

export function createPlayNpcDialogueEntry(
  campaignId: string,
  npcId: string,
  entry: PlayNpcDialogueEntry,
): PlayNpcDialogueEntry {
  const entryId = getNextPlayNpcDialogueEntryId(campaignId, npcId);
  getDb()
    .prepare(
      "INSERT INTO play_npc_dialogue (campaign_id, npc_id, dialogue_id, entry_id, data) VALUES (?, ?, ?, ?, ?)",
    )
    .run(campaignId, npcId, entry.dialogue_id, entryId, JSON.stringify(entry));
  return entry;
}

export function listPlayNpcDialogueEntries(
  campaignId: string,
  npcId: string,
): PlayNpcDialogueEntry[] {
  const rows = getDb()
    .prepare(
      "SELECT data FROM play_npc_dialogue WHERE campaign_id = ? AND npc_id = ? ORDER BY entry_id ASC",
    )
    .all(campaignId, npcId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayNpcDialogueEntry);
}

export const MIN_RELATIONSHIP_SCORE = -100;
export const MAX_RELATIONSHIP_SCORE = 100;

export interface PlayRelationship {
  source_id: string;
  target_id: string;
  kind: string;
  score: number;
}

export function hasPlayRelationship(
  campaignId: string,
  sourceId: string,
  targetId: string,
  kind: string,
): boolean {
  const row = getDb()
    .prepare(
      "SELECT 1 FROM play_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
    )
    .get(campaignId, sourceId, targetId, kind);
  return row !== undefined;
}

export function getPlayRelationship(
  campaignId: string,
  sourceId: string,
  targetId: string,
  kind: string,
): PlayRelationship | undefined {
  const row = getDb()
    .prepare(
      "SELECT data FROM play_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
    )
    .get(campaignId, sourceId, targetId, kind) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayRelationship;
}

export function createPlayRelationship(
  campaignId: string,
  relationship: PlayRelationship,
): PlayRelationship {
  getDb()
    .prepare(
      "INSERT INTO play_relationships (campaign_id, source_id, target_id, kind, data) VALUES (?, ?, ?, ?, ?)",
    )
    .run(campaignId, relationship.source_id, relationship.target_id, relationship.kind, JSON.stringify(relationship));
  return relationship;
}

export function updatePlayRelationship(
  campaignId: string,
  relationship: PlayRelationship,
): PlayRelationship {
  getDb()
    .prepare(
      "UPDATE play_relationships SET data = ? WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
    )
    .run(JSON.stringify(relationship), campaignId, relationship.source_id, relationship.target_id, relationship.kind);
  return relationship;
}

export function listPlayRelationships(campaignId: string): PlayRelationship[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_relationships WHERE campaign_id = ? ORDER BY row_id ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayRelationship);
}

export type PlayClueAudience = "character" | "party" | "hidden";

export interface PlayClue {
  clue_id: string;
  text: string;
  audience: PlayClueAudience;
  character_id?: string;
}

export function hasPlayClue(campaignId: string, clueId: string): boolean {
  const row = getDb()
    .prepare("SELECT 1 FROM play_clues WHERE campaign_id = ? AND clue_id = ?")
    .get(campaignId, clueId);
  return row !== undefined;
}

export function createPlayClue(campaignId: string, clue: PlayClue): PlayClue {
  getDb()
    .prepare("INSERT INTO play_clues (campaign_id, clue_id, data) VALUES (?, ?, ?)")
    .run(campaignId, clue.clue_id, JSON.stringify(clue));
  return clue;
}

export function listPlayClues(campaignId: string): PlayClue[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_clues WHERE campaign_id = ? ORDER BY row_id ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayClue);
}

export type PlayQuestState = "locked" | "active" | "completed";

export interface PlayQuestRewards {
  xp: number;
  items: Record<string, number>;
}

export interface PlayQuest {
  quest_id: string;
  title: string;
  depends_on: string[];
  state: PlayQuestState;
  rewards?: PlayQuestRewards;
  rewards_awarded?: boolean;
}

export function hasPlayQuest(campaignId: string, questId: string): boolean {
  const row = getDb()
    .prepare("SELECT 1 FROM play_quests WHERE campaign_id = ? AND quest_id = ?")
    .get(campaignId, questId);
  return row !== undefined;
}

export function getPlayQuest(campaignId: string, questId: string): PlayQuest | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_quests WHERE campaign_id = ? AND quest_id = ?")
    .get(campaignId, questId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayQuest;
}

export function createPlayQuest(campaignId: string, quest: PlayQuest): PlayQuest {
  getDb()
    .prepare("INSERT INTO play_quests (campaign_id, quest_id, data) VALUES (?, ?, ?)")
    .run(campaignId, quest.quest_id, JSON.stringify(quest));
  return quest;
}

export function updatePlayQuest(campaignId: string, quest: PlayQuest): PlayQuest {
  getDb()
    .prepare("UPDATE play_quests SET data = ? WHERE campaign_id = ? AND quest_id = ?")
    .run(JSON.stringify(quest), campaignId, quest.quest_id);
  return quest;
}

export function listPlayQuests(campaignId: string): PlayQuest[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_quests WHERE campaign_id = ? ORDER BY row_id ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayQuest);
}

export interface PlayCharacterRewards {
  xp: number;
  items: Record<string, number>;
}

export function getPlayCharacterRewards(
  campaignId: string,
  characterId: string,
): PlayCharacterRewards | undefined {
  const row = getDb()
    .prepare(
      "SELECT data FROM play_character_rewards WHERE campaign_id = ? AND character_id = ?",
    )
    .get(campaignId, characterId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayCharacterRewards;
}

export function grantPlayCharacterRewards(
  campaignId: string,
  characterId: string,
  grant: PlayCharacterRewards,
): PlayCharacterRewards {
  const existing = getPlayCharacterRewards(campaignId, characterId) ?? { xp: 0, items: {} };
  const merged: PlayCharacterRewards = {
    xp: existing.xp + grant.xp,
    items: { ...existing.items },
  };
  for (const [itemId, quantity] of Object.entries(grant.items)) {
    merged.items[itemId] = (merged.items[itemId] ?? 0) + quantity;
  }

  getDb()
    .prepare(
      `INSERT INTO play_character_rewards (campaign_id, character_id, data)
       VALUES (?, ?, ?)
       ON CONFLICT (campaign_id, character_id) DO UPDATE SET data = excluded.data`,
    )
    .run(campaignId, characterId, JSON.stringify(merged));

  return merged;
}

export type PlayWorldEventStatus = "scheduled" | "resolved";

export interface PlayWorldEventResolution {
  turn_number: number;
  text: string;
}

export interface PlayWorldEvent {
  event_id: string;
  turn_number: number;
  title: string;
  text: string;
  status: PlayWorldEventStatus;
  resolution?: PlayWorldEventResolution;
}

export function hasPlayWorldEvent(campaignId: string, eventId: string): boolean {
  const row = getDb()
    .prepare("SELECT 1 FROM play_world_events WHERE campaign_id = ? AND event_id = ?")
    .get(campaignId, eventId);
  return row !== undefined;
}

export function getPlayWorldEvent(
  campaignId: string,
  eventId: string,
): PlayWorldEvent | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_world_events WHERE campaign_id = ? AND event_id = ?")
    .get(campaignId, eventId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayWorldEvent;
}

export function createPlayWorldEvent(
  campaignId: string,
  event: PlayWorldEvent,
): PlayWorldEvent {
  getDb()
    .prepare("INSERT INTO play_world_events (campaign_id, event_id, data) VALUES (?, ?, ?)")
    .run(campaignId, event.event_id, JSON.stringify(event));
  return event;
}

export function updatePlayWorldEvent(
  campaignId: string,
  event: PlayWorldEvent,
): PlayWorldEvent {
  getDb()
    .prepare("UPDATE play_world_events SET data = ? WHERE campaign_id = ? AND event_id = ?")
    .run(JSON.stringify(event), campaignId, event.event_id);
  return event;
}

export function listPlayWorldEvents(campaignId: string): PlayWorldEvent[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_world_events WHERE campaign_id = ? ORDER BY row_id ASC")
    .all(campaignId) as { data: string }[];
  return rows
    .map((row) => JSON.parse(row.data) as PlayWorldEvent)
    .sort((a, b) => a.turn_number - b.turn_number);
}

export type PlaySeason = "spring" | "summer" | "autumn" | "winter";

export interface PlayCalendar {
  campaign_id: string;
  day: number;
  season: PlaySeason;
}

export function getPlayCalendar(campaignId: string): PlayCalendar | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_calendars WHERE campaign_id = ?")
    .get(campaignId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayCalendar;
}

export function createPlayCalendar(calendar: PlayCalendar): PlayCalendar {
  getDb()
    .prepare("INSERT INTO play_calendars (campaign_id, data) VALUES (?, ?)")
    .run(calendar.campaign_id, JSON.stringify(calendar));
  return calendar;
}

export function updatePlayCalendar(calendar: PlayCalendar): PlayCalendar {
  getDb()
    .prepare("UPDATE play_calendars SET data = ? WHERE campaign_id = ?")
    .run(JSON.stringify(calendar), calendar.campaign_id);
  return calendar;
}

const SEASON_OFFSETS: Record<PlaySeason, number> = {
  spring: 0,
  summer: 1,
  autumn: 2,
  winter: 3,
};

const WEATHER_BY_OFFSET = ["clear", "rain", "wind", "snow"] as const;

export function calendarWeather(day: number, season: PlaySeason): string {
  return WEATHER_BY_OFFSET[(day + SEASON_OFFSETS[season]) % 4];
}

export type PlaySettlementAvailability = "open" | "limited" | "closed";

export interface PlaySettlement {
  settlement_id: string;
  name: string;
  services: string[];
  availability: PlaySettlementAvailability;
  discovered_by: string[];
}

export function hasPlaySettlement(campaignId: string, settlementId: string): boolean {
  const row = getDb()
    .prepare("SELECT 1 FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?")
    .get(campaignId, settlementId);
  return row !== undefined;
}

export function getPlaySettlement(
  campaignId: string,
  settlementId: string,
): PlaySettlement | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?")
    .get(campaignId, settlementId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlaySettlement;
}

export function createPlaySettlement(
  campaignId: string,
  settlement: PlaySettlement,
): PlaySettlement {
  getDb()
    .prepare(
      "INSERT INTO play_settlements (campaign_id, settlement_id, data) VALUES (?, ?, ?)",
    )
    .run(campaignId, settlement.settlement_id, JSON.stringify(settlement));
  return settlement;
}

export function updatePlaySettlement(
  campaignId: string,
  settlement: PlaySettlement,
): PlaySettlement {
  getDb()
    .prepare(
      "UPDATE play_settlements SET data = ? WHERE campaign_id = ? AND settlement_id = ?",
    )
    .run(JSON.stringify(settlement), campaignId, settlement.settlement_id);
  return settlement;
}

export function listPlaySettlements(campaignId: string): PlaySettlement[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_settlements WHERE campaign_id = ? ORDER BY row_id ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlaySettlement);
}

export interface PlayShop {
  campaign_id: string;
  settlement_id: string;
  shop_id: string;
  name: string;
  stock: Record<string, number>;
  buy_price: number;
  sell_price: number;
}

export function hasPlayShop(campaignId: string, settlementId: string, shopId: string): boolean {
  const row = getDb()
    .prepare(
      "SELECT 1 FROM play_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
    )
    .get(campaignId, settlementId, shopId);
  return row !== undefined;
}

export function getPlayShop(
  campaignId: string,
  settlementId: string,
  shopId: string,
): PlayShop | undefined {
  const row = getDb()
    .prepare(
      "SELECT data FROM play_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
    )
    .get(campaignId, settlementId, shopId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayShop;
}

export function createPlayShop(shop: PlayShop): PlayShop {
  getDb()
    .prepare(
      "INSERT INTO play_shops (campaign_id, settlement_id, shop_id, data) VALUES (?, ?, ?, ?)",
    )
    .run(shop.campaign_id, shop.settlement_id, shop.shop_id, JSON.stringify(shop));
  return shop;
}

export function updatePlayShop(shop: PlayShop): PlayShop {
  getDb()
    .prepare(
      "UPDATE play_shops SET data = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
    )
    .run(JSON.stringify(shop), shop.campaign_id, shop.settlement_id, shop.shop_id);
  return shop;
}

export interface PlayRecipe {
  campaign_id: string;
  recipe_id: string;
  name: string;
  ingredients: Record<string, number>;
  output_item: string;
  output_quantity: number;
}

export function hasPlayRecipe(campaignId: string, recipeId: string): boolean {
  const row = getDb()
    .prepare("SELECT 1 FROM play_recipes WHERE campaign_id = ? AND recipe_id = ?")
    .get(campaignId, recipeId);
  return row !== undefined;
}

export function getPlayRecipe(campaignId: string, recipeId: string): PlayRecipe | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_recipes WHERE campaign_id = ? AND recipe_id = ?")
    .get(campaignId, recipeId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayRecipe;
}

export function createPlayRecipe(recipe: PlayRecipe): PlayRecipe {
  getDb()
    .prepare("INSERT INTO play_recipes (campaign_id, recipe_id, data) VALUES (?, ?, ?)")
    .run(recipe.campaign_id, recipe.recipe_id, JSON.stringify(recipe));
  return recipe;
}

export function updatePlayRecipe(recipe: PlayRecipe): PlayRecipe {
  getDb()
    .prepare("UPDATE play_recipes SET data = ? WHERE campaign_id = ? AND recipe_id = ?")
    .run(JSON.stringify(recipe), recipe.campaign_id, recipe.recipe_id);
  return recipe;
}

export function listPlayRecipes(campaignId: string): PlayRecipe[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_recipes WHERE campaign_id = ? ORDER BY row_id ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayRecipe);
}

export interface PlayDowntimeActivity {
  campaign_id: string;
  activity_id: string;
  name: string;
  cycles_required: number;
}

export function hasPlayDowntimeActivity(campaignId: string, activityId: string): boolean {
  const row = getDb()
    .prepare(
      "SELECT 1 FROM play_downtime_activities WHERE campaign_id = ? AND activity_id = ?",
    )
    .get(campaignId, activityId);
  return row !== undefined;
}

export function getPlayDowntimeActivity(
  campaignId: string,
  activityId: string,
): PlayDowntimeActivity | undefined {
  const row = getDb()
    .prepare(
      "SELECT data FROM play_downtime_activities WHERE campaign_id = ? AND activity_id = ?",
    )
    .get(campaignId, activityId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayDowntimeActivity;
}

export function createPlayDowntimeActivity(
  activity: PlayDowntimeActivity,
): PlayDowntimeActivity {
  getDb()
    .prepare(
      "INSERT INTO play_downtime_activities (campaign_id, activity_id, data) VALUES (?, ?, ?)",
    )
    .run(activity.campaign_id, activity.activity_id, JSON.stringify(activity));
  return activity;
}

export interface PlayDowntimeAllocation {
  campaign_id: string;
  character_id: string;
  activity_id: string;
  cycles_completed: number;
  completions: number;
}

export function hasPlayDowntimeAllocation(
  campaignId: string,
  characterId: string,
  activityId: string,
): boolean {
  const row = getDb()
    .prepare(
      "SELECT 1 FROM play_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
    )
    .get(campaignId, characterId, activityId);
  return row !== undefined;
}

export function getPlayDowntimeAllocation(
  campaignId: string,
  characterId: string,
  activityId: string,
): PlayDowntimeAllocation | undefined {
  const row = getDb()
    .prepare(
      "SELECT data FROM play_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
    )
    .get(campaignId, characterId, activityId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayDowntimeAllocation;
}

export function createPlayDowntimeAllocation(
  allocation: PlayDowntimeAllocation,
): PlayDowntimeAllocation {
  getDb()
    .prepare(
      "INSERT INTO play_downtime_allocations (campaign_id, character_id, activity_id, data) VALUES (?, ?, ?, ?)",
    )
    .run(
      allocation.campaign_id,
      allocation.character_id,
      allocation.activity_id,
      JSON.stringify(allocation),
    );
  return allocation;
}

export function updatePlayDowntimeAllocation(
  allocation: PlayDowntimeAllocation,
): PlayDowntimeAllocation {
  getDb()
    .prepare(
      "UPDATE play_downtime_allocations SET data = ? WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
    )
    .run(
      JSON.stringify(allocation),
      allocation.campaign_id,
      allocation.character_id,
      allocation.activity_id,
    );
  return allocation;
}

export interface PlayContent {
  content_id: string;
  kind: string;
  text: string;
  tags: string[];
}

export function hasPlayContent(campaignId: string, contentId: string): boolean {
  const row = getDb()
    .prepare("SELECT 1 FROM play_content WHERE campaign_id = ? AND content_id = ?")
    .get(campaignId, contentId);
  return row !== undefined;
}

export function getPlayContent(campaignId: string, contentId: string): PlayContent | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_content WHERE campaign_id = ? AND content_id = ?")
    .get(campaignId, contentId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayContent;
}

export function createPlayContent(campaignId: string, content: PlayContent): PlayContent {
  getDb()
    .prepare("INSERT INTO play_content (campaign_id, content_id, data) VALUES (?, ?, ?)")
    .run(campaignId, content.content_id, JSON.stringify(content));
  return content;
}

export function updatePlayContent(campaignId: string, content: PlayContent): PlayContent {
  getDb()
    .prepare("UPDATE play_content SET data = ? WHERE campaign_id = ? AND content_id = ?")
    .run(JSON.stringify(content), campaignId, content.content_id);
  return content;
}

export function listPlayContent(campaignId: string): PlayContent[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_content WHERE campaign_id = ? ORDER BY row_id ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayContent);
}

export type PlayNoteVisibility = "private" | "party";

export interface PlayNote {
  note_id: string;
  text: string;
  visibility: PlayNoteVisibility;
  owner: string;
}

export function hasPlayNote(campaignId: string, noteId: string): boolean {
  const row = getDb()
    .prepare("SELECT 1 FROM play_notes WHERE campaign_id = ? AND note_id = ?")
    .get(campaignId, noteId);
  return row !== undefined;
}

export function getPlayNote(campaignId: string, noteId: string): PlayNote | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_notes WHERE campaign_id = ? AND note_id = ?")
    .get(campaignId, noteId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayNote;
}

export function createPlayNote(campaignId: string, note: PlayNote): PlayNote {
  getDb()
    .prepare("INSERT INTO play_notes (campaign_id, note_id, data) VALUES (?, ?, ?)")
    .run(campaignId, note.note_id, JSON.stringify(note));
  return note;
}

export function updatePlayNote(campaignId: string, note: PlayNote): PlayNote {
  getDb()
    .prepare("UPDATE play_notes SET data = ? WHERE campaign_id = ? AND note_id = ?")
    .run(JSON.stringify(note), campaignId, note.note_id);
  return note;
}

export function listPlayNotes(campaignId: string): PlayNote[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_notes WHERE campaign_id = ? ORDER BY row_id ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayNote);
}

export interface PlayWhisper {
  whisper_id: string;
  from_character_id: string;
  to_character_id: string;
  text: string;
}

export function hasPlayWhisper(campaignId: string, whisperId: string): boolean {
  const row = getDb()
    .prepare("SELECT 1 FROM play_whispers WHERE campaign_id = ? AND whisper_id = ?")
    .get(campaignId, whisperId);
  return row !== undefined;
}

export function createPlayWhisper(campaignId: string, whisper: PlayWhisper): PlayWhisper {
  getDb()
    .prepare("INSERT INTO play_whispers (campaign_id, whisper_id, data) VALUES (?, ?, ?)")
    .run(campaignId, whisper.whisper_id, JSON.stringify(whisper));
  return whisper;
}

export function listPlayWhispers(campaignId: string): PlayWhisper[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_whispers WHERE campaign_id = ? ORDER BY row_id ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayWhisper);
}

export type PlayInvitationStatus = "pending" | "accepted";

export interface PlayInvitation {
  invitation_id: string;
  username: string;
  character_id: string;
  status: PlayInvitationStatus;
}

export function hasPlayInvitation(campaignId: string, invitationId: string): boolean {
  const row = getDb()
    .prepare("SELECT 1 FROM play_invitations WHERE campaign_id = ? AND invitation_id = ?")
    .get(campaignId, invitationId);
  return row !== undefined;
}

export function getPlayInvitation(
  campaignId: string,
  invitationId: string,
): PlayInvitation | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_invitations WHERE campaign_id = ? AND invitation_id = ?")
    .get(campaignId, invitationId) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayInvitation;
}

export function createPlayInvitation(
  campaignId: string,
  invitation: PlayInvitation,
): PlayInvitation {
  getDb()
    .prepare("INSERT INTO play_invitations (campaign_id, invitation_id, data) VALUES (?, ?, ?)")
    .run(campaignId, invitation.invitation_id, JSON.stringify(invitation));
  return invitation;
}

export function updatePlayInvitation(
  campaignId: string,
  invitation: PlayInvitation,
): PlayInvitation {
  getDb()
    .prepare("UPDATE play_invitations SET data = ? WHERE campaign_id = ? AND invitation_id = ?")
    .run(JSON.stringify(invitation), campaignId, invitation.invitation_id);
  return invitation;
}

export function listPlayInvitations(campaignId: string): PlayInvitation[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_invitations WHERE campaign_id = ? ORDER BY row_id ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayInvitation);
}

export function hasPendingPlayInvitationForUser(campaignId: string, username: string): boolean {
  return listPlayInvitations(campaignId).some(
    (invitation) => invitation.username === username && invitation.status === "pending",
  );
}

export type PlayDelegationPower = "narrate";

export const VALID_DELEGATION_POWERS: PlayDelegationPower[] = ["narrate"];

export interface PlayDelegation {
  username: string;
  powers: PlayDelegationPower[];
  active: boolean;
}

export function getPlayDelegation(campaignId: string, username: string): PlayDelegation | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_delegations WHERE campaign_id = ? AND username = ?")
    .get(campaignId, username) as { data: string } | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as PlayDelegation;
}

export function createPlayDelegation(campaignId: string, delegation: PlayDelegation): PlayDelegation {
  getDb()
    .prepare("INSERT INTO play_delegations (campaign_id, username, data) VALUES (?, ?, ?)")
    .run(campaignId, delegation.username, JSON.stringify(delegation));
  return delegation;
}

export function updatePlayDelegation(campaignId: string, delegation: PlayDelegation): PlayDelegation {
  getDb()
    .prepare("UPDATE play_delegations SET data = ? WHERE campaign_id = ? AND username = ?")
    .run(JSON.stringify(delegation), campaignId, delegation.username);
  return delegation;
}

export function hasActiveDelegatedPower(
  campaignId: string,
  username: string,
  power: PlayDelegationPower,
): boolean {
  const delegation = getPlayDelegation(campaignId, username);
  return delegation !== undefined && delegation.active && delegation.powers.includes(power);
}

export interface PlayDelegationAuditEntry {
  username: string;
  action: "granted" | "revoked";
  powers: PlayDelegationPower[];
}

export function createPlayDelegationAuditEntry(
  campaignId: string,
  entry: PlayDelegationAuditEntry,
): PlayDelegationAuditEntry {
  getDb()
    .prepare("INSERT INTO play_delegation_audit (campaign_id, data) VALUES (?, ?)")
    .run(campaignId, JSON.stringify(entry));
  return entry;
}

export function listPlayDelegationAuditEntries(campaignId: string): PlayDelegationAuditEntry[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_delegation_audit WHERE campaign_id = ? ORDER BY row_id ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayDelegationAuditEntry);
}

export type PlayAuditActorRole = "DM" | "player";

export interface PlayAuditEntry {
  kind: string;
  actor: string;
  role: PlayAuditActorRole;
  timestamp: number;
  correlation_id: string;
}

export function hasPlayAuditEntryForCorrelationId(
  campaignId: string,
  correlationId: string,
): boolean {
  const row = getDb()
    .prepare("SELECT row_id FROM play_audit_events WHERE campaign_id = ? AND correlation_id = ?")
    .get(campaignId, correlationId);
  return row !== undefined;
}

export function getNextPlayAuditTimestamp(campaignId: string): number {
  const row = getDb()
    .prepare("SELECT COUNT(*) AS count FROM play_audit_events WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  return row.count + 1;
}

export function createPlayAuditEntry(campaignId: string, entry: PlayAuditEntry): PlayAuditEntry {
  getDb()
    .prepare(
      "INSERT INTO play_audit_events (campaign_id, correlation_id, data) VALUES (?, ?, ?)",
    )
    .run(campaignId, entry.correlation_id, JSON.stringify(entry));
  return entry;
}

export function listPlayAuditEntries(campaignId: string): PlayAuditEntry[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_audit_events WHERE campaign_id = ? ORDER BY row_id ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayAuditEntry);
}

export type PlayProjectionEventKind = "set-story" | "increment-danger";

export interface PlayProjectionEvent {
  sequence: number;
  event_id: string;
  kind: PlayProjectionEventKind;
  value?: string;
}

export function hasPlayProjectionEventId(campaignId: string, eventId: string): boolean {
  const row = getDb()
    .prepare("SELECT sequence FROM play_projection_events WHERE campaign_id = ? AND event_id = ?")
    .get(campaignId, eventId);
  return row !== undefined;
}

export function getNextPlayProjectionSequence(campaignId: string): number {
  const row = getDb()
    .prepare("SELECT COUNT(*) AS count FROM play_projection_events WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  return row.count + 1;
}

export function createPlayProjectionEvent(
  campaignId: string,
  event: PlayProjectionEvent,
): PlayProjectionEvent {
  getDb()
    .prepare(
      "INSERT INTO play_projection_events (sequence, campaign_id, event_id, data) VALUES (?, ?, ?, ?)",
    )
    .run(event.sequence, campaignId, event.event_id, JSON.stringify(event));
  return event;
}

export function listPlayProjectionEvents(campaignId: string): PlayProjectionEvent[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_projection_events WHERE campaign_id = ? ORDER BY sequence ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayProjectionEvent);
}

export interface PlayIdempotentEvent {
  sequence: number;
  event_id: string;
  value: string;
  idempotency_key: string;
}

export function getPlayIdempotentEventByKey(
  campaignId: string,
  idempotencyKey: string,
): PlayIdempotentEvent | undefined {
  const row = getDb()
    .prepare(
      "SELECT data FROM play_idempotent_events WHERE campaign_id = ? AND idempotency_key = ?",
    )
    .get(campaignId, idempotencyKey) as { data: string } | undefined;
  return row ? (JSON.parse(row.data) as PlayIdempotentEvent) : undefined;
}

export function hasPlayIdempotentEventId(campaignId: string, eventId: string): boolean {
  const row = getDb()
    .prepare("SELECT sequence FROM play_idempotent_events WHERE campaign_id = ? AND event_id = ?")
    .get(campaignId, eventId);
  return row !== undefined;
}

export function getNextPlayIdempotentSequence(campaignId: string): number {
  const row = getDb()
    .prepare("SELECT COUNT(*) AS count FROM play_idempotent_events WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  return row.count + 1;
}

export function createPlayIdempotentEvent(
  campaignId: string,
  event: PlayIdempotentEvent,
): PlayIdempotentEvent {
  getDb()
    .prepare(
      "INSERT INTO play_idempotent_events (sequence, campaign_id, event_id, idempotency_key, data) VALUES (?, ?, ?, ?, ?)",
    )
    .run(event.sequence, campaignId, event.event_id, event.idempotency_key, JSON.stringify(event));
  return event;
}

export function listPlayIdempotentEvents(campaignId: string): PlayIdempotentEvent[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_idempotent_events WHERE campaign_id = ? ORDER BY sequence ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlayIdempotentEvent);
}

export interface PlaySafeTurn {
  sequence: number;
  submission_id: string;
  action: string;
  accepted_turn: number;
  next_turn: number;
}

export function getPlaySafeTurnCurrentTurn(campaignId: string): number {
  const row = getDb()
    .prepare("SELECT current_turn FROM play_safe_turn_state WHERE campaign_id = ?")
    .get(campaignId) as { current_turn: number } | undefined;
  return row ? row.current_turn : 1;
}

export function getPlaySafeTurnBySubmissionId(
  campaignId: string,
  submissionId: string,
): PlaySafeTurn | undefined {
  const row = getDb()
    .prepare("SELECT data FROM play_safe_turns WHERE campaign_id = ? AND submission_id = ?")
    .get(campaignId, submissionId) as { data: string } | undefined;
  return row ? (JSON.parse(row.data) as PlaySafeTurn) : undefined;
}

export function listPlaySafeTurns(campaignId: string): PlaySafeTurn[] {
  const rows = getDb()
    .prepare("SELECT data FROM play_safe_turns WHERE campaign_id = ? ORDER BY sequence ASC")
    .all(campaignId) as { data: string }[];
  return rows.map((row) => JSON.parse(row.data) as PlaySafeTurn);
}

export function acceptPlaySafeTurn(
  campaignId: string,
  submissionId: string,
  action: string,
): PlaySafeTurn {
  const db = getDb();
  const currentTurn = getPlaySafeTurnCurrentTurn(campaignId);
  const nextTurn = currentTurn + 1;
  const sequenceRow = db
    .prepare("SELECT COUNT(*) AS count FROM play_safe_turns WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  const turn: PlaySafeTurn = {
    sequence: sequenceRow.count + 1,
    submission_id: submissionId,
    action,
    accepted_turn: currentTurn,
    next_turn: nextTurn,
  };
  db.prepare(
    "INSERT INTO play_safe_turns (sequence, campaign_id, submission_id, data) VALUES (?, ?, ?, ?)",
  ).run(turn.sequence, campaignId, submissionId, JSON.stringify(turn));
  db.prepare(
    "INSERT INTO play_safe_turn_state (campaign_id, current_turn) VALUES (?, ?) " +
      "ON CONFLICT(campaign_id) DO UPDATE SET current_turn = excluded.current_turn",
  ).run(campaignId, nextTurn);
  return turn;
}

export interface PlayProjection {
  story: string;
  danger: number;
  applied_event_ids: string[];
}

export function buildPlayProjection(campaignId: string): PlayProjection {
  const events = listPlayProjectionEvents(campaignId);
  let story = "";
  let danger = 0;
  const applied_event_ids: string[] = [];
  for (const event of events) {
    if (event.kind === "set-story") {
      story = event.value ?? "";
    } else if (event.kind === "increment-danger") {
      danger += 1;
    }
    applied_event_ids.push(event.event_id);
  }
  return { story, danger, applied_event_ids };
}
