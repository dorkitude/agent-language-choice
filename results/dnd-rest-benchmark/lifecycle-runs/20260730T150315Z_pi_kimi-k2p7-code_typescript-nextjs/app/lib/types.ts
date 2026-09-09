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

export interface PlayCampaignSpectator {
  spectator_id: string;
  token: string;
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

export interface DelegationRecord {
  username: string;
  powers: string[];
  active: boolean;
}

export interface DelegationAuditEntry {
  username: string;
  action: "granted" | "revoked";
  powers: string[];
}

export interface DelegationAudit {
  entries: DelegationAuditEntry[];
}

export interface PlayCampaignAuditEvent {
  kind: string;
  actor: string;
  role: "DM" | "player";
  timestamp: number;
  correlation_id: string;
}

export interface PlayCampaignAuditEventInput {
  kind: string;
  correlation_id: string;
}

export interface PlayCampaignAuditTrail {
  entries: PlayCampaignAuditEvent[];
}

export interface PlayCampaignProjectionEvent {
  sequence: number;
  event_id: string;
  kind: "set-story" | "increment-danger";
  value?: string;
}

export interface PlayCampaignProjectionEventInput {
  event_id: string;
  kind: "set-story" | "increment-danger";
  value?: string;
}

export interface PlayCampaignProjection {
  story: string;
  danger: number;
  applied_event_ids: string[];
}

export interface PlayCampaignIdempotentEvent {
  event_id: string;
  value: string;
  sequence: number;
  idempotency_key: string;
}

export interface CreatePlayCampaignIdempotentEventInput {
  event_id: string;
  value: string;
  idempotency_key: string;
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

export interface SpellbookSpell {
  spell_id: string;
  name: string;
  level: number;
}

export interface SpellCastRecord {
  character_id: string;
  spell_id: string;
  target: string;
  slot_level: number;
  slots_remaining: number;
  sequence: number;
}

export interface CharacterConcentration {
  spell_id: string;
  target: string;
  remaining_turns: number;
}

export interface PlayCharacterInventoryItem {
  item_id: string;
  quantity: number;
}

export interface CharacterInventoryStack {
  character_id: string;
  item_id: string;
  quantity: number;
  total_quantity: number;
}

export interface CharacterInventorySummary {
  character_id: string;
  items: PlayCharacterInventoryItem[];
}

export interface CharacterInventoryItemConsumption {
  character_id: string;
  item_id: string;
  quantity_consumed: number;
  total_quantity: number;
  effect: {
    type: "healing";
    hp_restored: number;
  };
}

export interface CharacterEquipment {
  character_id: string;
  slot: "armor" | "accessory";
  item_id: string;
  attuned: boolean;
}

export interface CharacterAttunement {
  character_id: string;
  slot: "armor" | "accessory";
  item_id: string;
  attuned: boolean;
  attunement_count: number;
  max_attunements: 1;
}

export interface CharacterCurrency {
  character_id: string;
  gold: number;
}

export interface CurrencyTransfer {
  from_character_id: string;
  to_character_id: string;
  gold: number;
  from_gold: number;
  to_gold: number;
  transfer_id: number;
}

export interface TransactionalTransfer {
  from_character_id: string;
  to_character_id: string;
  amount: number;
  from_gold: number;
  to_gold: number;
  sequence: number;
}

export interface CreateTransactionalTransferInput {
  from_character_id: string;
  to_character_id: string;
  amount: number;
  simulate_failure: boolean;
}

export interface LootRecord {
  loot_id: string;
  item_id: string;
  quantity: number;
  status: "open" | "assigned";
  recipient_character_id: string | null;
  votes: Record<string, number>;
}

export interface LootVoteRecord {
  loot_id: string;
  voter: string;
  recipient_character_id: string;
  votes_for_recipient: number;
}

export interface LootAssignment {
  loot_id: string;
  recipient_character_id: string;
  item_id: string;
  quantity: number;
  votes: number;
  status: "assigned";
}

export interface PlayCampaignNpc {
  npc_id: string;
  name: string;
  agenda: string;
  public_status: string;
}

export interface CreatePlayCampaignNpcInput {
  npc_id: string;
  name: string;
  agenda: string;
  public_status: string;
}

export interface UpdatePlayCampaignNpcAgendaInput {
  agenda: string;
  public_status: string;
}

export interface PlayCampaignFaction {
  faction_id: string;
  name: string;
}

export interface CreatePlayCampaignFactionInput {
  faction_id: string;
  name: string;
}

export interface PlayCampaignReputationRecord {
  faction_id: string;
  character_id: string;
  reputation: number;
  delta: number;
  reason: string;
}

export interface CreatePlayCampaignReputationInput {
  character_id: string;
  delta: number;
  reason: string;
}

export interface PlayCampaignNpcDialogueEntry {
  dialogue_id: string;
  speaker: string;
  text: string;
  visibility: "public" | "private";
}

export interface CreatePlayCampaignNpcDialogueInput {
  dialogue_id: string;
  speaker: string;
  text: string;
  visibility: "public" | "private";
}

export interface PlayCampaignRelationship {
  source_id: string;
  target_id: string;
  kind: string;
  score: number;
}

export type PlayCampaignClueAudience = "character" | "party" | "hidden";

export interface PlayCampaignClue {
  clue_id: string;
  text: string;
  audience: PlayCampaignClueAudience;
  character_id?: string;
}

export interface CreatePlayCampaignClueInput {
  clue_id: string;
  text: string;
  audience: PlayCampaignClueAudience;
  character_id?: string;
}

export type PlayCampaignQuestState = "locked" | "active" | "completed";

export interface PlayCampaignQuestRewards {
  xp: number;
  items: Record<string, number>;
}

export interface PlayCampaignQuest {
  quest_id: string;
  title: string;
  depends_on: string[];
  state: PlayCampaignQuestState;
  rewards?: PlayCampaignQuestRewards;
}

export interface CreatePlayCampaignQuestInput {
  quest_id: string;
  title: string;
  depends_on: string[];
}

export interface ConfigurePlayCampaignQuestRewardsInput {
  xp: number;
  items: Record<string, number>;
}

export type PlayCampaignWorldEventStatus = "scheduled" | "resolved";

export interface PlayCampaignWorldEventResolution {
  turn_number: number;
  text: string;
}

export interface PlayCampaignWorldEvent {
  event_id: string;
  turn_number: number;
  title: string;
  text: string;
  status: PlayCampaignWorldEventStatus;
  resolution?: PlayCampaignWorldEventResolution;
}

export interface CreatePlayCampaignWorldEventInput {
  event_id: string;
  turn_number: number;
  title: string;
  text: string;
}

export interface ResolvePlayCampaignWorldEventInput {
  text: string;
}

export type Season = "spring" | "summer" | "autumn" | "winter";

export type Weather = "clear" | "rain" | "wind" | "snow";

export interface PlayCampaignCalendar {
  day: number;
  season: Season;
  weather: Weather;
}

export type SettlementAvailability = "open" | "limited" | "closed";

export interface Settlement {
  settlement_id: string;
  name: string;
  services: string[];
  availability: SettlementAvailability;
  discovered_by: string[];
}

export interface CreateSettlementInput {
  settlement_id: string;
  name: string;
  services: string[];
  availability: SettlementAvailability;
}

export interface Shop {
  shop_id: string;
  name: string;
  stock: Record<string, number>;
  buy_price: number;
  sell_price: number;
}

export interface CreateShopInput {
  shop_id: string;
  name: string;
  stock: Record<string, number>;
  buy_price: number;
  sell_price: number;
}

export interface ShopTransactionResult {
  character_id: string;
  item_id: string;
  quantity: number;
  gold: number;
  stock: number;
}

export interface Recipe {
  recipe_id: string;
  name: string;
  ingredients: Record<string, number>;
  output_item: string;
  output_quantity: number;
}

export interface CreateRecipeInput {
  recipe_id: string;
  name: string;
  ingredients: Record<string, number>;
  output_item: string;
  output_quantity: number;
}

export interface RecipeList {
  recipes: Recipe[];
}

export interface CraftRecipeResult {
  character_id: string;
  recipe_id: string;
  output_item: string;
  output_quantity: number;
}

export interface DowntimeActivity {
  activity_id: string;
  name: string;
  cycles_required: number;
}

export interface CreateDowntimeActivityInput {
  activity_id: string;
  name: string;
  cycles_required: number;
}

export interface DowntimeAllocation {
  character_id: string;
  activity_id: string;
  cycles_completed: number;
  completions: number;
}

export interface SessionZeroSettings {
  rules: string;
  tone: string;
  consent: string[];
}

export interface ContentRecord {
  content_id: string;
  kind: string;
  text: string;
  tags: string[];
}

export interface CreateContentRecordInput {
  content_id: string;
  kind: string;
  text: string;
  tags: string[];
}

export interface UpdateContentTagsInput {
  tags: string[];
}

// ---------------------------------------------------------------------------
// Privacy controls (075)
// ---------------------------------------------------------------------------

export interface Note {
  note_id: string;
  text: string;
  visibility: "private" | "party";
  owner: string;
}

export interface CreateNoteInput {
  note_id: string;
  text: string;
  visibility: "private" | "party";
}

export interface UpdateNoteInput {
  text: string;
  visibility: "private" | "party";
}

export interface Whisper {
  whisper_id: string;
  from_character_id: string;
  to_character_id: string;
  text: string;
}

export interface CreateWhisperInput {
  whisper_id: string;
  to_character_id: string;
  text: string;
}

// ---------------------------------------------------------------------------
// Campaign chat messages (098 spectator redaction fixture)
// ---------------------------------------------------------------------------

export interface PlayCampaignMessage {
  kind: "chat";
  actor: string;
  text: string;
}

export interface CreatePlayCampaignMessageInput {
  text: string;
}

export interface CharacterSheet {
  character_id: string;
  owner: string;
  name: string;
  class: string;
  level: number;
  proficiency_bonus: number;
  hp_max: number;
  armor_class: number;
}

// ---------------------------------------------------------------------------
// Campaign invitations (076)
// ---------------------------------------------------------------------------

export interface PlayCampaignInvitation {
  invitation_id: string;
  username: string;
  character_id: string;
  status: "pending" | "accepted";
}

export interface CreatePlayCampaignInvitationInput {
  invitation_id: string;
  username: string;
  character_id: string;
}

// ---------------------------------------------------------------------------
// Concurrent turn safety (081)
// ---------------------------------------------------------------------------

export interface AcceptedSafeTurn {
  submission_id: string;
  action: string;
  accepted_turn: number;
  next_turn: number;
}

export interface SafeTurnState {
  current_turn: number;
  accepted: AcceptedSafeTurn[];
}

// ---------------------------------------------------------------------------
// Versioned campaign exports (083)
// ---------------------------------------------------------------------------

export interface PlayCampaignExportSnapshot {
  version: number;
  story: string;
  status: string;
}

export interface PlayCampaignExportList {
  exports: PlayCampaignExportSnapshot[];
}

// ---------------------------------------------------------------------------
// Campaign imports (084)
// ---------------------------------------------------------------------------

export interface PlayCampaignImportSnapshot {
  version: number;
  story: string;
  status: string;
}

// ---------------------------------------------------------------------------
// Schema migrations (085)
// ---------------------------------------------------------------------------

export interface PlayCampaignMigrationInput {
  schema_version: number;
  story: string;
}

export interface PlayCampaignMigrationSnapshot {
  schema_version: number;
  story: string;
  campaign_name: string;
}

// ---------------------------------------------------------------------------
// Search records (086)
// ---------------------------------------------------------------------------

export interface SearchRecord {
  record_id: string;
  text: string;
}

export interface CreateSearchRecordInput {
  record_id: string;
  text: string;
}

export interface SearchRecordList {
  records: SearchRecord[];
  next_cursor: number | null;
}

// ---------------------------------------------------------------------------
// Rate events (087)
// ---------------------------------------------------------------------------

export interface RateEvent {
  event_id: string;
  actor: string;
}

export interface RateEventCreateResult {
  event_id: string;
  actor: string;
  remaining: number;
}

export interface RateEventList {
  events: RateEvent[];
  remaining: number;
}

// ---------------------------------------------------------------------------
// Service metrics (088)
// ---------------------------------------------------------------------------

export interface ServiceMetrics {
  accepted_rate_events: number;
  rejected_rate_events: number;
  projection_events: number;
  uptime_ticks: number;
}

// ---------------------------------------------------------------------------
// Campaign backups (090)
// ---------------------------------------------------------------------------

export interface PlayCampaignBackup {
  backup_id: string;
  story: string;
  status: string;
}

export interface PlayCampaignBackupList {
  backups: PlayCampaignBackup[];
}

// ---------------------------------------------------------------------------
// Deterministic replay (091)
// ---------------------------------------------------------------------------

export interface CreatePlayCampaignReplayEventInput {
  event_id: string;
  kind: "append";
  text: string;
}

export interface PlayCampaignReplayEvent {
  event_id: string;
  kind: "append";
  text: string;
  sequence: number;
}

export interface PlayCampaignReplayState {
  story: string;
  event_ids: string[];
  digest: string;
}

// ---------------------------------------------------------------------------
// Deterministic RNG ledger (092)
// ---------------------------------------------------------------------------

export interface PlayCampaignRngSeed {
  seed: string;
}

export interface PlayCampaignRngRoll {
  roll_id: string;
  sides: number;
  result: number;
  sequence: number;
}

export interface PlayCampaignRngLedger {
  seed: string;
  rolls: PlayCampaignRngRoll[];
}

export interface ConfigureRngSeedInput {
  seed: string;
}

export interface CreateRngRollInput {
  roll_id: string;
  sides: number;
}

// ---------------------------------------------------------------------------
// Moderation workflow (093)
// ---------------------------------------------------------------------------

export interface PlayCampaignModerationReport {
  report_id: string;
  target_id: string;
  reason: string;
  status: "open" | "resolved";
  reporter: string;
  sequence: number;
  action?: "allow" | "remove";
  note?: string;
  resolver?: string;
}

export interface PlayCampaignModerationReports {
  reports: PlayCampaignModerationReport[];
}

export interface CreatePlayCampaignModerationReportInput {
  report_id: string;
  target_id: string;
  reason: string;
}

export interface ResolvePlayCampaignModerationReportInput {
  action: "allow" | "remove";
  note: string;
}

// ---------------------------------------------------------------------------
// Safety boundaries (094)
// ---------------------------------------------------------------------------

export interface PlayCampaignSafetyBoundaries {
  blocked_tags: string[];
}

export interface PlayCampaignSafetyEvent {
  event_id: string;
  kind: "narration" | "chat";
  text: string;
  tags: string[];
  sequence: number;
}

export interface PlayCampaignSafetyEvents {
  events: PlayCampaignSafetyEvent[];
}

export interface CreatePlayCampaignSafetyCheckInput {
  event_id: string;
  kind: "narration" | "chat";
  text: string;
  tags: string[];
}

// ---------------------------------------------------------------------------
// Fixture seeding (095)
// ---------------------------------------------------------------------------

export interface FixtureCharacter {
  character_id: string;
  name: string;
  class: string;
}

export interface PlayCampaignFixtureState {
  fixture_id: "canonical-v1";
  status: "seeded";
  characters: FixtureCharacter[];
  story: string;
  event_ids: string[];
}

// ---------------------------------------------------------------------------
// Load-safe event feed (099)
// ---------------------------------------------------------------------------

export interface PlayCampaignFeedEvent {
  event_id: string;
  text: string;
  sequence: number;
}

export interface PlayCampaignFeedEventInput {
  event_id: string;
  text: string;
}

export interface PlayCampaignFeedPage {
  events: PlayCampaignFeedEvent[];
  next_cursor: number;
}

