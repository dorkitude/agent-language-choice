/**
 * Shared domain types used by both the game engine and the SQLite persistence layer.
 *
 * This module intentionally contains only type definitions so that `storage.ts`
 * can depend on the domain model without importing business logic from
 * `engine.ts`.
 */

// -----------------------------------------------------------------------------
// Engine / game-rule types
// -----------------------------------------------------------------------------

export interface DiceStats {
  dice_count: number;
  sides: number;
  modifier: number;
  min: number;
  max: number;
  average: number;
}

export interface AbilityCheckResult {
  total: number;
  success: boolean;
  margin: number;
}

export interface EncounterThresholds {
  easy: number;
  medium: number;
  hard: number;
  deadly: number;
}

export interface AdjustedXpResult {
  base_xp: number;
  monster_count: number;
  multiplier: number;
  adjusted_xp: number;
  difficulty: string;
  thresholds: EncounterThresholds;
}

export interface Combatant {
  name: string;
  score: number;
}

export interface Abilities {
  str: number;
  dex: number;
  con: number;
  int: number;
  wis: number;
  cha: number;
}

export interface Armor {
  base: number;
  shield: boolean;
  dex_cap: number;
}

export interface DerivedStatsResult {
  level: number;
  proficiency_bonus: number;
  hp_max: number;
  armor_class: number;
  modifiers: Abilities;
}

export interface SessionCombatantInput {
  name: string;
  dex: number;
  roll: number;
}

export interface Condition {
  condition: string;
  remaining_rounds: number;
}

export interface SessionCombatant {
  name: string;
  score: number;
  dex: number;
  conditions: Condition[];
}

export interface CombatSession {
  id: string;
  round: number;
  turn_index: number;
  combatants: SessionCombatant[];
}

export interface AddConditionResult {
  target: string;
  conditions: Condition[];
}

export interface AdvanceResult {
  id: string;
  round: number;
  turn_index: number;
  active: { name: string; score: number };
  conditions: Record<string, Condition[]>;
}

// -----------------------------------------------------------------------------
// Persistence types
// -----------------------------------------------------------------------------

export interface CreateUserResult {
  username: string;
  role: string;
}

export interface StoredUser {
  username: string;
  password_hash: string;
  role: "dm" | "player";
}

export interface CreateMonsterInput {
  slug: string;
  name: string;
  cr: string;
  armor_class: number;
  hit_points: number;
  tags: string[];
}

export interface Monster {
  slug: string;
  name: string;
  cr: string;
  armor_class: number;
  hit_points: number;
  tags: string[];
}

export interface CreateItemInput {
  slug: string;
  name: string;
  type: string;
  rarity: string;
  cost_gp: number;
}

export interface Item {
  slug: string;
  name: string;
  type: string;
  rarity: string;
  cost_gp: number;
}

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

export interface CampaignState {
  id: string;
  name: string;
  dm: string;
  characters: CampaignCharacter[];
  log_count: number;
}

export type QuestStatus = "active" | "completed" | "blocked";

export interface QuestMilestone {
  title: string;
  done: boolean;
}

export interface Quest {
  id: string;
  campaign_id: string;
  title: string;
  status: QuestStatus;
  milestones: QuestMilestone[];
}

export interface CreateQuestInput {
  id: string;
  title: string;
  status: QuestStatus;
  milestones: string[];
}

export interface QuestCreateResult {
  id: string;
  title: string;
  status: QuestStatus;
  milestones_total: number;
  milestones_done: number;
}

export interface QuestProgress {
  id: string;
  status: QuestStatus;
  milestones_total: number;
  milestones_done: number;
}

export interface QuestSummary {
  campaign_id: string;
  active: number;
  completed: number;
  blocked: number;
}

export interface Faction {
  id: string;
  name: string;
  stance: string;
}

export interface CreateFactionInput {
  id: string;
  name: string;
  stance: string;
}

export interface Npc {
  id: string;
  name: string;
  faction_id: string;
  disposition: number;
}

export interface CreateNpcInput {
  id: string;
  name: string;
  faction_id: string;
  disposition: number;
}

export interface RelationshipSummary {
  campaign_id: string;
  factions: number;
  npcs: number;
  friendly_npcs: number;
}

export interface InventoryItem {
  item_slug: string;
  quantity: number;
  owner: string;
}

export interface EquipmentAssignment {
  character_id: string;
  item_slug: string;
  quantity: number;
}

export interface InventorySummary {
  campaign_id: string;
  party_items: number;
  assigned_items: number;
  healing_potions_available: number;
}

export interface CraftingProject {
  id: string;
  campaign_id: string;
  character_id: string;
  item_slug: string;
  days_required: number;
  days_completed: number;
  cost_gp: number;
  status: "active" | "complete";
}

export interface CreateCraftingProjectInput {
  id: string;
  character_id: string;
  item_slug: string;
  days_required: number;
  cost_gp: number;
}

export interface CraftingProjectCreateResponse {
  id: string;
  character_id: string;
  item_slug: string;
  days_required: number;
  days_completed: number;
  status: "active" | "complete";
}

export interface AdvanceCraftingInput {
  days: number;
}

export interface AdvanceCraftingResponse {
  id: string;
  days_completed: number;
  status: "active" | "complete";
}

export interface GameSession {
  id: string;
  campaign_id: string;
  starts_at: string;
  duration_minutes: number;
  agenda: string[];
}

export interface CreateSessionInput {
  id: string;
  starts_at: string;
  duration_minutes: number;
  agenda: string[];
}

export interface SessionCreateResult {
  id: string;
  starts_at: string;
  duration_minutes: number;
  agenda_count: number;
}

export interface SessionAttendance {
  session_id: string;
  present_count: number;
  absent_count: number;
}

export interface NextSession {
  id: string;
  starts_at: string;
  agenda_count: number;
}

export interface CampaignAudit {
  campaign_id: string;
  events: number;
  quests: number;
  npcs: number;
  sessions: number;
}

export interface CampaignExport {
  campaign_id: string;
  name: string;
  characters: number;
  quests: number;
  npcs: number;
  inventory_items: number;
  sessions: number;
  schema_version: number;
}

export interface CampaignAnalyticsSummary {
  campaign_id: string;
  readiness_score: number;
  open_quests: number;
  friendly_npcs: number;
  scheduled_sessions: number;
  inventory_items: number;
}

export interface CampaignRiskReport {
  campaign_id: string;
  risk_level: "low" | "medium" | "high" | "critical";
  missing: string[];
  signals: {
    has_dm: boolean;
    has_characters: boolean;
    has_next_session: boolean;
    has_active_quest: boolean;
  };
}

export interface PlayCampaign {
  id: string;
  name: string;
  owner: string;
  status: "lobby";
  max_players: number;
}

export interface CreatePlayCampaignInput {
  id: string;
  name: string;
  max_players: number;
}

export interface PlayCampaignMembership {
  username: string;
  character_id: string;
  name: string;
  class: string;
}

export type PlayCampaignMemberStatus =
  | "conscious"
  | "unconscious"
  | "stable"
  | "dead";

export interface PlayCampaignMemberState {
  campaign_id: string;
  username: string;
  character_id: string;
  name: string;
  class: string;
  hp_current: number;
  hp_max: number;
  status: PlayCampaignMemberStatus;
  death_saves_successes: number;
  death_saves_failures: number;
}

export interface CharacterDamageResult {
  character_id: string;
  target: string;
  hp_before: number;
  hp_after: number;
  damage: number;
  status: PlayCampaignMemberStatus;
}

export interface DeathSaveResult {
  character_id: string;
  successes: number;
  failures: number;
  status: PlayCampaignMemberStatus;
}

export interface CharacterStatusResult {
  character_id: string;
  hp_current: number;
  hp_max: number;
  status: PlayCampaignMemberStatus;
}

export interface PlayCampaignStartResult {
  id: string;
  status: "active";
  current_actor: string;
  turn_number: number;
}

export interface PlayCampaignState {
  campaign_id: string;
  current_actor: string;
  status: "active";
  turn_number: number;
  nudge_count: number;
  current_location_id?: string;
  phase: "exploration" | "combat";
  pre_combat_actor?: string;
}

export interface NudgeResult {
  actor: string;
  target: string;
  message: string;
  nudge_count: number;
}

export type PlayEventKind = "narration" | "action" | "resolution" | "travel" | "nudge" | "scene" | "rest" | "combat_action" | "ready";

export interface PlayEvent {
  sequence: number;
  kind: PlayEventKind;
  actor: string;
  text: string;
  type?: string;
  destination_id?: string;
  travel_turns?: number;
  target?: string;
}

export interface ResolutionResult extends PlayEvent {
  kind: "resolution";
  next_actor: string;
  turn_number: number;
}

export interface CreatePlayCampaignMembershipInput {
  character_id: string;
  name: string;
  class: string;
}

export interface CampaignDocument {
  campaign_id: string;
  story: string;
  dm_notes: string;
}

export interface PlayCampaignScene {
  id: string;
  name: string;
  status: "open" | "closed";
}

export interface CreateSceneInput {
  id: string;
  name: string;
}

export interface CampaignLocation {
  id: string;
  name: string;
}

export interface CreateLocationInput {
  id: string;
  name: string;
}

export interface LocationConnection {
  from_id: string;
  to_id: string;
  travel_turns: number;
}

export interface CreateConnectionInput {
  to_id: string;
  travel_turns: number;
}

export interface TravelDestination {
  id: string;
  name: string;
  travel_turns: number;
}

export interface TravelEvent {
  sequence: number;
  kind: "travel";
  actor: string;
  destination_id: string;
  travel_turns: number;
  next_actor: string;
}

export interface RestEvent {
  sequence: number;
  kind: "rest";
  actor: string;
  type: string;
  hp_current: number;
  hp_max: number;
  next_actor: string;
}

export interface PlayCampaignEncounter {
  id: string;
  name: string;
  status: "active" | "completed" | "closed";
  combatants: PlayCampaignEncounterCombatant[];
}

export interface PlayCampaignEncounterCombatant {
  name: string;
  score: number;
}

export interface CreatePlayCampaignEncounterInput {
  id: string;
  name: string;
}

export interface CreatePlayCampaignEncounterMonsterInput {
  monster_id: string;
  name: string;
  hp_max: number;
  initiative: number;
}

export interface PlayCampaignEncounterMonster {
  monster_id: string;
  name: string;
  hp_max: number;
  initiative: number;
  hp_current: number;
}

export interface PlayCampaignEncounterTurn {
  round: number;
  turn_index: number;
  active: {
    name: string;
    kind: "player" | "monster";
    initiative: number;
    member?: string;
    target: string;
  };
}

export interface PlayCampaignEncounterStatus {
  round: number;
  turn_index: number;
  active: {
    name: string;
    kind: "player" | "monster";
    initiative: number;
    member?: string;
    target: string;
  };
  order: Array<{
    name: string;
    kind: "player" | "monster";
    initiative: number;
    target: string;
  }>;
  conditions: Record<string, Condition[]>;
}

export interface AddEncounterConditionResult {
  target: string;
  conditions: Condition[];
}

export interface EncounterLoot {
  slug: string;
  quantity: number;
}

export interface EncounterRewardRecord {
  xp: number;
  loot: EncounterLoot[];
}

export interface EncounterCloseResult {
  id: string;
  status: "closed";
  xp_awarded: number;
}

export interface EndEncounterResult {
  campaign_id: string;
  status: "active";
  phase: "exploration";
  current_actor: string;
}

export interface CharacterBuildInput {
  race: string;
  class: string;
  background: string;
  abilities: Abilities;
  level: number;
  hp_max: number;
}
