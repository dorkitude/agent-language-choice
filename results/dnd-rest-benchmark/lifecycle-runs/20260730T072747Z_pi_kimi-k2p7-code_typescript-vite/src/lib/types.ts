// Domain models used by the API. Names and shapes mirror the JSON contracts
// exposed by the endpoints so the storage layer and handlers stay aligned.

export type UserRole = 'dm' | 'player';

export type User = {
  username: string;
  role: UserRole;
  passwordHash: string;
};

export type Combatant = {
  name: string;
  dex: number;
  roll: number;
  score: number;
};

export type Condition = {
  condition: string;
  remaining_rounds: number;
};

export type CombatSession = {
  id: string;
  round: number;
  turn_index: number;
  combatants: Combatant[];
  order: { name: string; score: number }[];
  conditions: Record<string, Condition[]>;
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

export type Character = {
  id: string;
  campaign_id: string;
  name: string;
  level: number;
  class: string;
};

export type Event = {
  id: string;
  campaign_id: string;
  kind: string;
  summary: string;
};

export type QuestStatus = 'active' | 'completed' | 'blocked';

export type Quest = {
  id: string;
  campaign_id: string;
  title: string;
  status: QuestStatus;
  milestones: string[];
  completed: string[];
};

export type Faction = {
  id: string;
  campaign_id: string;
  name: string;
  stance: string;
};

export type Npc = {
  id: string;
  campaign_id: string;
  name: string;
  faction_id: string;
  disposition: number;
};

export type Inventory = {
  id: number;
  campaign_id: string;
  item_slug: string;
  quantity: number;
  owner: string;
};

export type Equipment = {
  id: number;
  campaign_id: string;
  character_id: string;
  item_slug: string;
  quantity: number;
};

export type CraftingStatus = 'active' | 'complete';

export type CraftingProject = {
  id: string;
  campaign_id: string;
  character_id: string;
  item_slug: string;
  days_required: number;
  days_completed: number;
  cost_gp: number;
  status: CraftingStatus;
};

export type GameSession = {
  id: string;
  campaign_id: string;
  starts_at: string;
  duration_minutes: number;
  agenda: string[];
};

export type PlayCampaign = {
  id: string;
  name: string;
  owner: string;
  status: 'lobby' | 'active';
  max_players: number;
  current_actor?: string;
  turn_number?: number;
  nudge_count?: number;
  current_location_id?: string;
};

export type PlayCampaignMember = {
  campaign_id: string;
  username: string;
  character_id: string;
  name: string;
  class: string;
  sequence?: number;
  hp_max?: number;
  hp_current?: number;
  status?: 'alive' | 'unconscious' | 'stable' | 'dead';
  death_successes?: number;
  death_failures?: number;
};

export type Narration = {
  sequence: number;
  campaign_id: string;
  actor: string;
  text: string;
};

export type Action = {
  sequence: number;
  campaign_id: string;
  actor: string;
  type: string;
  text: string;
};

export type CombatAction = {
  sequence: number;
  campaign_id: string;
  encounter_id: string;
  actor: string;
  type: string;
  target: string;
  text: string;
};

export type Resolution = {
  sequence: number;
  campaign_id: string;
  actor: string;
  text: string;
};

export type CampaignDocument = {
  campaign_id: string;
  story: string;
  dm_notes: string;
};

export type PlayScene = {
  campaign_id: string;
  id: string;
  name: string;
  status: 'open' | 'closed';
};

export type Location = {
  campaign_id: string;
  id: string;
  name: string;
};

export type LocationConnection = {
  campaign_id: string;
  from_id: string;
  to_id: string;
  travel_turns: number;
};

export type Travel = {
  sequence: number;
  campaign_id: string;
  actor: string;
  destination_id: string;
  travel_turns: number;
};

export type Rest = {
  sequence: number;
  campaign_id: string;
  actor: string;
  type: 'short' | 'long';
  hp_current: number;
  hp_max: number;
};

export type RosterMonster = {
  monster_id?: string;
  member?: string;
  character_id?: string;
  name: string;
  hp_max?: number;
  hp_current?: number;
  initiative: number;
  sequence?: number;
};

export type Encounter = {
  campaign_id: string;
  id: string;
  name: string;
  status: 'active';
  round: number;
  turn_index: number;
  combatants: RosterMonster[];
};

export type LocationEvent = {
  sequence: number;
  campaign_id: string;
  actor: string;
  location_id: string;
  name: string;
};

export type DiceStats = {
  dice_count: number;
  sides: number;
  modifier: number;
  min: number;
  max: number;
  average: number;
};
