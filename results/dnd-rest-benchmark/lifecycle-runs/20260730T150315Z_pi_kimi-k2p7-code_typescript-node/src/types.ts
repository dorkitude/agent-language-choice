/**
 * Shared domain types used by the repository, rules, and HTTP handlers.
 */

export type Role = 'dm' | 'player';

export type User = {
  username: string;
  role: Role;
  salt: string;
  hash: string;
};

/** Raw combatant input before the initiative score is computed. */
export type Combatant = {
  name: string;
  dex: number;
  roll: number;
};

/** Combatant after adding the deterministic initiative score. */
export type ScoredCombatant = Combatant & {
  score: number;
};

export type CombatSession = {
  id: string;
  round: number;
  turn_index: number;
  order: ScoredCombatant[];
  conditions: Record<string, Array<{ condition: string; remaining_rounds: number }>>;
};

export type Monster = {
  slug: string;
  name: string;
  cr: string;
  armor_class: number;
  hit_points: number;
  tags: string[];
};

export type Item = {
  slug: string;
  name: string;
  type: string;
  rarity: string;
  cost_gp: number;
};

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
  summary?: string;
};

export type QuestStatus = 'active' | 'completed' | 'blocked';

export type Quest = {
  id: string;
  campaign_id: string;
  title: string;
  status: QuestStatus;
  milestones: string[];
  done_milestones: string[];
};

export type Faction = {
  id: string;
  campaign_id: string;
  name: string;
  stance: string;
};

export type NPC = {
  id: string;
  campaign_id: string;
  name: string;
  faction_id?: string;
  disposition: number;
};

export type RelationshipSummary = {
  campaign_id: string;
  factions: number;
  npcs: number;
  friendly_npcs: number;
};

export type InventoryItem = {
  item_slug: string;
  quantity: number;
  owner: string;
};

export type CharacterEquipment = {
  character_id: string;
  item_slug: string;
  quantity: number;
};

export type InventorySummary = {
  campaign_id: string;
  party_items: number;
  assigned_items: number;
  healing_potions_available: number;
};

export type CraftingProjectStatus = 'active' | 'complete';

export type CraftingProject = {
  id: string;
  campaign_id: string;
  character_id: string;
  item_slug: string;
  days_required: number;
  days_completed: number;
  status: CraftingProjectStatus;
  cost_gp: number;
};

export type Session = {
  id: string;
  campaign_id: string;
  starts_at: string;
  duration_minutes: number;
  agenda: string[];
};

export type AttendanceRecord = {
  session_id: string;
  character_id: string;
  present: boolean;
};

export type PlayCampaignStatus = 'lobby' | 'active' | 'closed';

export type PlayCampaign = {
  id: string;
  name: string;
  owner: string;
  status: PlayCampaignStatus;
  max_players: number;
  current_actor?: string;
  turn_number?: number;
  phase?: string;
  current_scene_id?: string;
  current_location_id?: string;
  pre_combat_actor?: string | null;
};

export type PlayMembershipStatus = 'conscious' | 'unconscious' | 'stable' | 'dead';

export type PlayMembership = {
  campaign_id: string;
  username: string;
  character_id: string;
  name: string;
  class: string;
  hp_current: number;
  hp_max: number;
  level: number;
  con_modifier: number;
  status: PlayMembershipStatus;
  death_save_successes: number;
  death_save_failures: number;
  owner: string | null;
};

export type Narration = {
  id: string;
  campaign_id: string;
  sequence: number;
  actor: 'dm';
  text: string;
};

export type ActionEvent = {
  id: string;
  campaign_id: string;
  sequence: number;
  actor: string;
  type: string;
  text: string;
};

export type Resolution = {
  id: string;
  campaign_id: string;
  sequence: number;
  actor: 'dm';
  text: string;
};

export type Nudge = {
  id: string;
  campaign_id: string;
  turn_number: number;
  actor: string;
  target: string;
  message: string;
  sequence: number;
};

export type TravelEvent = {
  id: string;
  campaign_id: string;
  sequence: number;
  actor: string;
  destination_id: string;
  travel_turns: number;
};

export type RestEvent = {
  id: string;
  campaign_id: string;
  sequence: number;
  actor: string;
  type: 'short' | 'long';
  hp_current: number;
  hp_max: number;
};

export type CampaignDocument = {
  story: string;
  dm_notes: string;
};

export type SceneStatus = 'open' | 'closed';

export type Scene = {
  id: string;
  campaign_id: string;
  name: string;
  status: SceneStatus;
};

export type Location = {
  id: string;
  campaign_id: string;
  name: string;
};

export type LocationConnection = {
  from_id: string;
  to_id: string;
  campaign_id: string;
  travel_turns: number;
};

export type PlayEncounterCombatant = {
  id: string;
  name: string;
  type: 'player' | 'monster' | 'npc';
  initiative?: number;
  hp_current?: number;
  hp_max?: number;
};

export type PlayEncounter = {
  id: string;
  campaign_id: string;
  name: string;
  status: 'active' | 'resolved' | 'closed';
  round: number;
  turn_index: number;
  combatants: PlayEncounterCombatant[];
  conditions: Record<string, Array<{ condition: string; remaining_rounds: number }>>;
};

export type LootItem = {
  slug: string;
  quantity: number;
};

export type EncounterReward = {
  encounter_id: string;
  xp: number;
  loot: LootItem[];
};

export type CombatAction = {
  id: string;
  campaign_id: string;
  encounter_id: string;
  sequence: number;
  actor: string;
  type: 'attack' | 'help' | 'dodge' | 'ready';
  target: string;
  text: string;
};

export type ReadiedAction = {
  id: string;
  encounter_id: string;
  actor: string;
  trigger: string;
};
