import { database } from "./storage";
import { abilityModifier, proficiencyBonus, type AbilityName } from "./characters";

export type PlayCampaign = {
  id: string;
  name: string;
  owner: string;
  status: "lobby" | "active";
  max_players: number;
};

export type PlayCampaignMember = {
  username: string;
  character_id: string;
  name: string;
  class: string;
};

export type PlayCampaignSpectatorView = {
  campaign_id: string;
  name: string;
  status: "lobby" | "active";
  party_size: number;
  story: string;
};

export type PlayCampaignOnboarding = {
  role: "dm" | "player";
  next_steps: string[];
  can_mutate: true;
};

export type PlayCampaignInvitation = {
  invitation_id: string;
  username: string;
  character_id: string;
  status: "pending" | "accepted";
};

export type PlayCampaignDelegation = {
  username: string;
  powers: ["narrate"];
  active: boolean;
};

export type PlayCampaignDelegationAuditEntry = {
  username: string;
  action: "granted" | "revoked";
  powers: ["narrate"];
};

export type PlayCampaignAuditEvent = {
  kind: string;
  actor: string;
  role: "DM" | "player";
  timestamp: number;
  correlation_id: string;
};

export type PlayCampaignProjectionEvent = {
  sequence: number;
  event_id: string;
  kind: "set-story" | "increment-danger";
  value?: string;
};

export type PlayCampaignProjection = {
  story: string;
  danger: number;
  applied_event_ids: string[];
};

export type PlayCampaignProjectionEventInput =
  | { event_id: string; kind: "set-story"; value: string }
  | { event_id: string; kind: "increment-danger" };

export type PlayCampaignReplayEvent = {
  event_id: string;
  kind: "append";
  text: string;
  sequence: number;
};

export type PlayCampaignReplay = {
  story: string;
  event_ids: string[];
  digest: string;
};

export type PlayCampaignRngRoll = {
  roll_id: string;
  sides: number;
  result: number;
  sequence: number;
};

export type PlayCampaignRngLedger = {
  seed: string;
  rolls: PlayCampaignRngRoll[];
};

export type PlayCampaignIdempotentEvent = {
  event_id: string;
  value: string;
  sequence: number;
  idempotency_key: string;
};

export type PlayCampaignModerationOpenReport = {
  report_id: string;
  target_id: string;
  reason: string;
  status: "open";
  reporter: string;
  sequence: number;
};

export type PlayCampaignModerationResolvedReport = Omit<PlayCampaignModerationOpenReport, "status"> & {
  status: "resolved";
  action: "allow" | "remove";
  note: string;
  resolver: string;
};

export type PlayCampaignModerationReport = PlayCampaignModerationOpenReport | PlayCampaignModerationResolvedReport;

export type PlayCampaignSafetyEvent = {
  event_id: string;
  kind: "narration" | "chat";
  text: string;
  tags: string[];
  sequence: number;
};

export type PlayCampaignFeedEvent = {
  event_id: string;
  text: string;
  sequence: number;
};

export type PlayCampaignFixtureState = {
  fixture_id: "canonical-v1";
  status: "seeded";
  characters: [
    { character_id: "fixture-hero"; name: "Ari"; class: "fighter" },
    { character_id: "fixture-mage"; name: "Bea"; class: "wizard" },
  ];
  story: "The lantern is lit.";
  event_ids: ["fixture-event-1", "fixture-event-2"];
};

export type PlayCampaignSafeTurn = {
  submission_id: string;
  action: string;
  accepted_turn: number;
  next_turn: number;
};

export type PlayCampaignSessionZeroSettings = {
  rules: string;
  tone: string;
  consent: string[];
};

export type PlayCampaignCharacterOwner = {
  character_id: string;
  owner: string;
};

export type PlayCampaignCharacterCurrency = {
  character_id: string;
  gold: number;
};

export type PlayCampaignCurrencyTransfer = {
  from_character_id: string;
  to_character_id: string;
  gold: number;
  from_gold: number;
  to_gold: number;
  transfer_id: number;
};

export type PlayCampaignTransactionalTransfer = {
  from_character_id: string;
  to_character_id: string;
  amount: number;
  from_gold: number;
  to_gold: number;
  sequence: number;
};

export type PlayCampaignInventoryItem = {
  item_id: string;
  quantity: number;
};

export type PlayCampaignCharacterInventory = {
  character_id: string;
  items: PlayCampaignInventoryItem[];
};

export type PlayCampaignRecipe = {
  recipe_id: string;
  name: string;
  ingredients: Record<string, number>;
  output_item: string;
  output_quantity: number;
};

export type PlayCampaignDowntimeActivity = {
  activity_id: string;
  name: string;
  cycles_required: number;
};

export type PlayCampaignDowntimeAllocation = {
  character_id: string;
  activity_id: string;
  cycles_completed: number;
  completions: number;
};

export type PlayCampaignInventoryItemStack = PlayCampaignInventoryItem & {
  character_id: string;
  total_quantity: number;
};

export type PlayCampaignLoot = {
  loot_id: string;
  item_id: string;
  quantity: number;
  status: "open" | "assigned";
  recipient_character_id: string | null;
  votes: number;
};

export type PlayCampaignLootVote = {
  loot_id: string;
  voter: string;
  recipient_character_id: string;
  votes_for_recipient: number;
};

export type PlayCampaignLootRecord = Omit<PlayCampaignLoot, "votes"> & {
  votes: Record<string, number>;
};

export type PlayCampaignNpc = {
  npc_id: string;
  name: string;
  agenda: string;
  public_status: string;
};

export type PlayCampaignNpcDialogue = {
  dialogue_id: string;
  speaker: string;
  text: string;
  visibility: "public" | "private";
};

export type PlayCampaignRelationship = {
  source_id: string;
  target_id: string;
  kind: string;
  score: number;
};

export type PlayCampaignClue = {
  clue_id: string;
  text: string;
  audience: "character" | "party" | "hidden";
  character_id?: string;
};

export type PlayCampaignContent = {
  content_id: string;
  kind: string;
  text: string;
  tags: string[];
};

export type PlayCampaignNote = {
  note_id: string;
  text: string;
  visibility: "private" | "party";
  owner: string;
};

export type PlayCampaignSearchRecord = {
  record_id: string;
  text: string;
};

export type PlayCampaignRateEvent = {
  event_id: string;
  actor: string;
};

export type PlayCampaignMetrics = {
  accepted_rate_events: number;
  rejected_rate_events: number;
  projection_events: number;
  uptime_ticks: 1;
};

export type PlayCampaignWhisper = {
  whisper_id: string;
  from_character_id: string;
  to_character_id: string;
  text: string;
};

export type PlayCampaignCharacterSheet = {
  character_id: string;
  owner: string;
  name: string;
  class: string;
  level: number;
  proficiency_bonus: number;
  hp_max: number;
  armor_class: number;
};

export type PlayCampaignQuest = {
  quest_id: string;
  title: string;
  depends_on: string[];
  state: "locked" | "active" | "completed";
  rewards?: PlayCampaignQuestRewards;
};

export type PlayCampaignQuestRewards = {
  xp: number;
  items: Record<string, number>;
};

export type PlayCampaignWorldEventResolution = {
  turn_number: number;
  text: string;
};

export type PlayCampaignWorldEvent = {
  event_id: string;
  turn_number: number;
  title: string;
  text: string;
  status: "scheduled" | "resolved";
  resolution?: PlayCampaignWorldEventResolution;
};

export type PlayCampaignSeason = "spring" | "summer" | "autumn" | "winter";

export type PlayCampaignCalendar = {
  day: number;
  season: PlayCampaignSeason;
  weather: "clear" | "rain" | "wind" | "snow";
};

export type PlayCampaignSettlement = {
  settlement_id: string;
  name: string;
  services: string[];
  availability: "open" | "limited" | "closed";
  discovered_by: string[];
};

export type PlayCampaignShop = {
  shop_id: string;
  name: string;
  stock: Record<string, number>;
  buy_price: number;
  sell_price: number;
};

export type PlayCampaignShopTrade = {
  character_id: string;
  item_id: string;
  quantity: number;
  gold: number;
  stock: number;
};

export type PlayCampaignCharacterQuestRewards = {
  character_id: string;
  xp: number;
  items: Record<string, number>;
};

export type PlayCampaignFaction = {
  faction_id: string;
  name: string;
};

export type PlayCampaignFactionReputation = {
  faction_id: string;
  character_id: string;
  reputation: number;
  delta: number;
  reason: string;
};

export type PlayCampaignCharacterEquipment = {
  character_id: string;
  slot: "armor" | "accessory";
  item_id: string;
  attuned: boolean;
};

export type PlayCampaignCharacterAttunedEquipment = PlayCampaignCharacterEquipment & {
  attunement_count: number;
  max_attunements: number;
};

export type PlayCampaignCharacterBuild = {
  race: string;
  class: string;
  background: string;
  abilities: Record<AbilityName, number>;
};

export type PlayCampaignCharacterLevel = {
  character_id: string;
  level: number;
  hp_max: number;
  hit_dice: string;
  proficiency_bonus: number;
};

export type PlayCampaignSpell = {
  spell_id: string;
  name: string;
  level: number;
};

export type PlayCampaignPreparedSpells = {
  character_id: string;
  prepared_spells: string[];
  max_prepared: number;
};

export type PlayCampaignSpellCast = {
  character_id: string;
  spell_id: string;
  target: string;
  slot_level: number;
  slots_remaining: number;
  sequence: number;
};

export type PlayCampaignConcentration = {
  spell_id: string;
  target: string;
  remaining_turns: number;
};

export type PlayCampaignCharacterConcentration = {
  character_id: string;
  concentration: PlayCampaignConcentration | null;
};

export type PlayCampaignDocument = {
  story: string;
  dm_notes: string;
};

export type PlayCampaignExport = {
  version: number;
  story: string;
  status: "lobby" | "active";
};

export type PlayCampaignBackup = {
  backup_id: string;
  story: string;
  status: "lobby" | "active";
};

export type PlayCampaignImport = {
  version: 1;
  story: string;
  status: "lobby" | "started";
};

export type PlayCampaignMigrationState = {
  schema_version: 2;
  story: string;
  campaign_name: string;
};

export type PlayCampaignScene = {
  id: string;
  name: string;
  status: "open" | "closed";
};

export type PlayCampaignLocation = {
  id: string;
  name: string;
};

export type PlayCampaignLocationConnection = {
  from_id: string;
  to_id: string;
  travel_turns: number;
};

export type PlayCampaignEncounter = {
  id: string;
  name: string;
  status: "active";
  combatants: [];
};

export type PlayCampaignEncounterLoot = {
  slug: string;
  quantity: number;
};

export type PlayCampaignEncounterReward = {
  encounter_id: string;
  xp: number;
  loot: PlayCampaignEncounterLoot[];
};

export type PlayCampaignMonster = {
  monster_id: string;
  name: string;
  hp_max: number;
  hp_current: number;
  initiative: number;
};

export type PlayCampaignCombatant = {
  member: string;
  character_id: string;
  name: string;
  initiative: number;
};

export type PlayCampaignEncounterTurnCombatant = {
  name: string;
  kind: "monster" | "player";
  initiative: number;
  member?: string;
  target?: string;
};

export type PlayCampaignEncounterTurn = {
  round: number;
  turn_index: number;
  active: Omit<PlayCampaignEncounterTurnCombatant, "member">;
};

export type PlayCampaignEncounterCondition = {
  condition: string;
  remaining_rounds: number;
};

export type PlayCampaignEncounterStatus = PlayCampaignEncounterTurn & {
  order: Array<Omit<PlayCampaignEncounterTurnCombatant, "member" | "target">>;
  conditions: Record<string, PlayCampaignEncounterCondition[]>;
};

type PlayCampaignOwner = Pick<PlayCampaign, "owner">;
type PlayCampaignMemberName = Pick<PlayCampaignMember, "username">;

// Keep membership order tied to SQLite insertion order: turn rotation and the
// returned queue both depend on that established API invariant.
function orderedPlayCampaignMembers(campaignId: string): PlayCampaignMember[] {
  return database.prepare(`
    SELECT username, character_id, name, class
    FROM play_campaign_members
    WHERE campaign_id = ?
    ORDER BY rowid ASC
  `).all(campaignId) as PlayCampaignMember[];
}

function firstPlayCampaignMember(campaignId: string): PlayCampaignMemberName | undefined {
  return database.prepare(`
    SELECT username
    FROM play_campaign_members
    WHERE campaign_id = ?
    ORDER BY rowid ASC
    LIMIT 1
  `).get(campaignId) as PlayCampaignMemberName | undefined;
}

function playCampaignOwner(campaignId: string): PlayCampaignOwner | undefined {
  return database.prepare("SELECT owner FROM play_campaigns WHERE id = ?")
    .get(campaignId) as PlayCampaignOwner | undefined;
}

export function playCampaignExists(campaignId: string): boolean {
  return Boolean(playCampaignOwner(campaignId));
}

function isPlayCampaignMember(campaignId: string, actor: string): boolean {
  return Boolean(database.prepare(
    "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
  ).get(campaignId, actor));
}

function playCampaignActor(campaignId: string, actor: string): "dm" | "player" | undefined {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return undefined;
  if (campaign.owner === actor) return "dm";
  return isPlayCampaignMember(campaignId, actor) ? "player" : undefined;
}

/** Return the fixed onboarding guidance for an authorized campaign participant. */
export function readPlayCampaignOnboarding(
  campaignId: string,
  actor: string,
): { result: "found"; onboarding: PlayCampaignOnboarding } | { result: "not_found" | "forbidden" } {
  const role = playCampaignActor(campaignId, actor);
  if (!role) return playCampaignExists(campaignId) ? { result: "forbidden" } : { result: "not_found" };
  return role === "dm"
    ? { result: "found", onboarding: { role: "dm", next_steps: ["configure-safety", "invite-players", "start-campaign"], can_mutate: true } }
    : { result: "found", onboarding: { role: "player", next_steps: ["review-party", "take-turn", "submit-action"], can_mutate: true } };
}

function canonicalPlayCampaignFixture(): PlayCampaignFixtureState {
  return {
    fixture_id: "canonical-v1",
    status: "seeded",
    characters: [
      { character_id: "fixture-hero", name: "Ari", class: "fighter" },
      { character_id: "fixture-mage", name: "Bea", class: "wizard" },
    ],
    story: "The lantern is lit.",
    event_ids: ["fixture-event-1", "fixture-event-2"],
  };
}

export function seedPlayCampaignFixture(
  campaignId: string,
  actor: string,
): { result: "seeded" | "existing"; fixture: PlayCampaignFixtureState } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const inserted = database.prepare(`
    INSERT INTO play_campaign_fixture_seeds (campaign_id, fixture_id)
    VALUES (?, 'canonical-v1')
    ON CONFLICT(campaign_id) DO NOTHING
  `).run(campaignId).changes > 0;
  return { result: inserted ? "seeded" : "existing", fixture: canonicalPlayCampaignFixture() };
}

export function readPlayCampaignFixture(
  campaignId: string,
  actor: string,
): { result: "found"; fixture: PlayCampaignFixtureState } | { result: "not_found" | "forbidden" | "unseeded" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!playCampaignActor(campaignId, actor)) return { result: "forbidden" };
  if (!database.prepare("SELECT 1 FROM play_campaign_fixture_seeds WHERE campaign_id = ?").get(campaignId)) {
    return { result: "unseeded" };
  }
  return { result: "found", fixture: canonicalPlayCampaignFixture() };
}

export function createPlayCampaignAuditEvent(
  campaignId: string,
  actor: string,
  input: Pick<PlayCampaignAuditEvent, "kind" | "correlation_id">,
): { result: "created"; entry: PlayCampaignAuditEvent } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  const role: PlayCampaignAuditEvent["role"] = campaign.owner === actor ? "DM" : "player";
  if (role === "player" && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  try {
    const entry = database.prepare(`
      INSERT INTO play_campaign_audit_events (campaign_id, timestamp, kind, actor, role, correlation_id)
      VALUES (?, COALESCE((SELECT MAX(timestamp) FROM play_campaign_audit_events WHERE campaign_id = ?), 0) + 1, ?, ?, ?, ?)
      RETURNING kind, actor, role, timestamp, correlation_id
    `).get(campaignId, campaignId, input.kind, actor, role, input.correlation_id) as PlayCampaignAuditEvent;
    return { result: "created", entry };
  } catch {
    return { result: "conflict" };
  }
}

export function readPlayCampaignAuditEvents(
  campaignId: string,
  actor: string,
): { result: "found"; entries: PlayCampaignAuditEvent[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const entries = database.prepare(`
    SELECT kind, actor, role, timestamp, correlation_id
    FROM play_campaign_audit_events WHERE campaign_id = ? ORDER BY timestamp ASC
  `).all(campaignId) as PlayCampaignAuditEvent[];
  return { result: "found", entries };
}

function projectionFromEvents(events: PlayCampaignProjectionEvent[]): PlayCampaignProjection {
  let story = "";
  let danger = 0;
  for (const event of events) {
    if (event.kind === "set-story") story = event.value!;
    else danger += 1;
  }
  return { story, danger, applied_event_ids: events.map((event) => event.event_id) };
}

function projectionEvents(campaignId: string): PlayCampaignProjectionEvent[] {
  return (database.prepare(`
    SELECT sequence, event_id, kind, value
    FROM play_campaign_projection_events
    WHERE campaign_id = ? ORDER BY sequence ASC
  `).all(campaignId) as Array<{
    sequence: number; event_id: string; kind: "set-story" | "increment-danger"; value: string | null;
  }>).map((event) => event.kind === "set-story"
    ? { sequence: event.sequence, event_id: event.event_id, kind: event.kind, value: event.value! }
    : { sequence: event.sequence, event_id: event.event_id, kind: event.kind });
}

export function appendPlayCampaignProjectionEvent(
  campaignId: string,
  actor: string,
  event: PlayCampaignProjectionEventInput,
): { result: "created"; event: PlayCampaignProjectionEvent } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner === actor || !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  try {
    const stored = database.prepare(`
      INSERT INTO play_campaign_projection_events (campaign_id, sequence, event_id, kind, value)
      VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_projection_events WHERE campaign_id = ?), 0) + 1, ?, ?, ?)
      RETURNING sequence, event_id, kind, value
    `).get(campaignId, campaignId, event.event_id, event.kind, event.kind === "set-story" ? event.value : null) as {
      sequence: number; event_id: string; kind: "set-story" | "increment-danger"; value: string | null;
    };
    return { result: "created", event: stored.kind === "set-story"
      ? { ...stored, value: stored.value! }
      : { sequence: stored.sequence, event_id: stored.event_id, kind: stored.kind } };
  } catch {
    return { result: "conflict" };
  }
}

export function readPlayCampaignProjection(
  campaignId: string,
  actor: string,
): { result: "found"; projection: PlayCampaignProjection } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  return { result: "found", projection: projectionFromEvents(projectionEvents(campaignId)) };
}

function replayFromEvents(events: PlayCampaignReplayEvent[]): PlayCampaignReplay {
  const story = events.map((event) => event.text).join("");
  const event_ids = events.map((event) => event.event_id);
  return { story, event_ids, digest: `${event_ids.join(",")}|${story}` };
}

export function appendPlayCampaignReplayEvent(
  campaignId: string,
  actor: string,
  input: Pick<PlayCampaignReplayEvent, "event_id" | "text">,
): { result: "created"; event: PlayCampaignReplayEvent } | { result: "not_found" | "forbidden" | "conflict" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!playCampaignActor(campaignId, actor)) return { result: "forbidden" };
  try {
    const event = database.prepare(`
      INSERT INTO play_campaign_replay_events (campaign_id, sequence, event_id, text)
      VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_replay_events WHERE campaign_id = ?), 0) + 1, ?, ?)
      RETURNING event_id, text, sequence
    `).get(campaignId, campaignId, input.event_id, input.text) as Omit<PlayCampaignReplayEvent, "kind">;
    return { result: "created", event: { event_id: event.event_id, kind: "append", text: event.text, sequence: event.sequence } };
  } catch {
    return { result: "conflict" };
  }
}

export function readPlayCampaignReplay(
  campaignId: string,
  actor: string,
): { result: "found"; replay: PlayCampaignReplay } | { result: "not_found" | "forbidden" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!playCampaignActor(campaignId, actor)) return { result: "forbidden" };
  const events = database.prepare(`
    SELECT event_id, text, sequence FROM play_campaign_replay_events
    WHERE campaign_id = ? ORDER BY sequence ASC
  `).all(campaignId) as Array<Omit<PlayCampaignReplayEvent, "kind">>;
  return {
    result: "found",
    replay: replayFromEvents(events.map((event) => ({ ...event, kind: "append" }))),
  };
}

/** A campaign-local, byte-for-byte reproducible die result. */
function rngResult(seed: string, sequence: number, rollId: string, sides: number): number {
  const bytes = Buffer.from(`${seed}|${sequence}|${rollId}|${sides}`, "utf8");
  let acc = 0;
  for (const byte of bytes) acc = (Math.imul(acc, 31) + byte) >>> 0;
  return (acc % sides) + 1;
}

export function configurePlayCampaignRngSeed(
  campaignId: string,
  actor: string,
  seed: string,
): { result: "configured"; ledger: PlayCampaignRngLedger } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  try {
    database.prepare("INSERT INTO play_campaign_rng_seeds (campaign_id, seed) VALUES (?, ?)").run(campaignId, seed);
    return { result: "configured", ledger: { seed, rolls: [] } };
  } catch {
    return { result: "conflict" };
  }
}

export function appendPlayCampaignRngRoll(
  campaignId: string,
  actor: string,
  input: Pick<PlayCampaignRngRoll, "roll_id" | "sides">,
): { result: "created"; roll: PlayCampaignRngRoll } | { result: "not_found" | "forbidden" | "unconfigured" | "conflict" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!playCampaignActor(campaignId, actor)) return { result: "forbidden" };
  const seed = database.prepare("SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?").get(campaignId) as { seed: string } | undefined;
  if (!seed) return { result: "unconfigured" };
  if (database.prepare("SELECT 1 FROM play_campaign_rng_rolls WHERE campaign_id = ? AND roll_id = ?").get(campaignId, input.roll_id)) return { result: "conflict" };
  try {
    const sequence = (database.prepare("SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_rng_rolls WHERE campaign_id = ?").get(campaignId) as { sequence: number }).sequence;
    const roll = { roll_id: input.roll_id, sides: input.sides, result: rngResult(seed.seed, sequence, input.roll_id, input.sides), sequence };
    database.prepare(`
      INSERT INTO play_campaign_rng_rolls (campaign_id, sequence, roll_id, sides, result)
      VALUES (?, ?, ?, ?, ?)
    `).run(campaignId, roll.sequence, roll.roll_id, roll.sides, roll.result);
    return { result: "created", roll };
  } catch {
    return { result: "conflict" };
  }
}

export function readPlayCampaignRngLedger(
  campaignId: string,
  actor: string,
): { result: "found"; ledger: PlayCampaignRngLedger } | { result: "not_found" | "forbidden" | "unconfigured" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!playCampaignActor(campaignId, actor)) return { result: "forbidden" };
  const seed = database.prepare("SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?").get(campaignId) as { seed: string } | undefined;
  if (!seed) return { result: "unconfigured" };
  const rolls = database.prepare(`
    SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls
    WHERE campaign_id = ? ORDER BY sequence ASC
  `).all(campaignId) as PlayCampaignRngRoll[];
  return { result: "found", ledger: { seed: seed.seed, rolls } };
}

/** Create a campaign event exactly once for each campaign-scoped idempotency key. */
export function createPlayCampaignIdempotentEvent(
  campaignId: string,
  actor: string,
  input: Pick<PlayCampaignIdempotentEvent, "event_id" | "value" | "idempotency_key">,
): { result: "created" | "replayed"; event: PlayCampaignIdempotentEvent } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };

  const eventForKey = database.prepare(`
    SELECT event_id, value, sequence, idempotency_key
    FROM play_campaign_idempotent_events
    WHERE campaign_id = ? AND idempotency_key = ?
  `).get(campaignId, input.idempotency_key) as PlayCampaignIdempotentEvent | undefined;
  if (eventForKey) {
    return eventForKey.event_id === input.event_id && eventForKey.value === input.value
      ? { result: "replayed", event: eventForKey }
      : { result: "conflict" };
  }

  if (database.prepare(`
    SELECT 1 FROM play_campaign_idempotent_events WHERE campaign_id = ? AND event_id = ?
  `).get(campaignId, input.event_id)) return { result: "conflict" };

  try {
    const event = database.prepare(`
      INSERT INTO play_campaign_idempotent_events (campaign_id, sequence, event_id, value, idempotency_key)
      VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_idempotent_events WHERE campaign_id = ?), 0) + 1, ?, ?, ?)
      RETURNING event_id, value, sequence, idempotency_key
    `).get(campaignId, campaignId, input.event_id, input.value, input.idempotency_key) as PlayCampaignIdempotentEvent;
    return { result: "created", event };
  } catch {
    return { result: "conflict" };
  }
}

export function readPlayCampaignIdempotentEvents(
  campaignId: string,
  actor: string,
): { result: "found"; events: PlayCampaignIdempotentEvent[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const events = database.prepare(`
    SELECT event_id, value, sequence, idempotency_key
    FROM play_campaign_idempotent_events
    WHERE campaign_id = ? ORDER BY sequence ASC
  `).all(campaignId) as PlayCampaignIdempotentEvent[];
  return { result: "found", events };
}

export function createPlayCampaignModerationReport(
  campaignId: string,
  actor: string,
  input: Pick<PlayCampaignModerationOpenReport, "report_id" | "target_id" | "reason">,
): { result: "created"; report: PlayCampaignModerationOpenReport } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  try {
    const report = database.prepare(`
      INSERT INTO play_campaign_moderation_reports
        (campaign_id, sequence, report_id, target_id, reason, status, reporter)
      VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_moderation_reports WHERE campaign_id = ?), 0) + 1, ?, ?, ?, 'open', ?)
      RETURNING report_id, target_id, reason, status, reporter, sequence
    `).get(campaignId, campaignId, input.report_id, input.target_id, input.reason, actor) as PlayCampaignModerationOpenReport;
    return { result: "created", report };
  } catch {
    return { result: "conflict" };
  }
}

export function readPlayCampaignModerationReports(
  campaignId: string,
  actor: string,
): { result: "found"; reports: PlayCampaignModerationReport[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const rows = database.prepare(`
    SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver
    FROM play_campaign_moderation_reports WHERE campaign_id = ? ORDER BY sequence ASC
  `).all(campaignId) as Array<{
    report_id: string; target_id: string; reason: string; status: "open" | "resolved"; reporter: string; sequence: number;
    action: "allow" | "remove" | null; note: string | null; resolver: string | null;
  }>;
  const reports = rows.map(({ action, note, resolver, ...report }) => report.status === "resolved"
    ? { ...report, status: "resolved" as const, action: action!, note: note!, resolver: resolver! }
    : { ...report, status: "open" as const });
  return { result: "found", reports };
}

export function replacePlayCampaignSafetyBoundaries(
  campaignId: string,
  actor: string,
  blockedTags: string[],
): { result: "updated"; blocked_tags: string[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const sortedTags = [...blockedTags].sort();
  database.exec("BEGIN IMMEDIATE");
  try {
    database.prepare("DELETE FROM play_campaign_safety_boundaries WHERE campaign_id = ?").run(campaignId);
    const insert = database.prepare("INSERT INTO play_campaign_safety_boundaries (campaign_id, tag) VALUES (?, ?)");
    for (const tag of sortedTags) insert.run(campaignId, tag);
    database.exec("COMMIT");
    return { result: "updated", blocked_tags: sortedTags };
  } catch (error) {
    try { database.exec("ROLLBACK"); } catch { /* transaction already closed */ }
    throw error;
  }
}

export function readPlayCampaignSafetyBoundaries(
  campaignId: string,
  actor: string,
): { result: "found"; blocked_tags: string[] } | { result: "not_found" | "forbidden" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!playCampaignActor(campaignId, actor)) return { result: "forbidden" };
  const blocked_tags = (database.prepare(`
    SELECT tag FROM play_campaign_safety_boundaries WHERE campaign_id = ? ORDER BY tag ASC
  `).all(campaignId) as Array<{ tag: string }>).map((row) => row.tag);
  return { result: "found", blocked_tags };
}

export function submitPlayCampaignSafetyCheck(
  campaignId: string,
  actor: string,
  input: Omit<PlayCampaignSafetyEvent, "sequence">,
): { result: "created"; event: PlayCampaignSafetyEvent } | { result: "not_found" | "forbidden" | "conflict" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!playCampaignActor(campaignId, actor)) return { result: "forbidden" };
  const blocked = database.prepare(`
    SELECT 1 FROM play_campaign_safety_boundaries WHERE campaign_id = ? AND tag = ?
  `);
  if (input.tags.some((tag) => blocked.get(campaignId, tag))) return { result: "conflict" };
  try {
    const event = database.prepare(`
      INSERT INTO play_campaign_safety_events (campaign_id, sequence, event_id, kind, text, tags_json)
      VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_safety_events WHERE campaign_id = ?), 0) + 1, ?, ?, ?, ?)
      RETURNING event_id, kind, text, tags_json, sequence
    `).get(campaignId, campaignId, input.event_id, input.kind, input.text, JSON.stringify(input.tags)) as Omit<PlayCampaignSafetyEvent, "tags"> & { tags_json: string };
    return {
      result: "created",
      event: {
        event_id: event.event_id,
        kind: event.kind,
        text: event.text,
        tags: JSON.parse(event.tags_json) as string[],
        sequence: event.sequence,
      },
    };
  } catch {
    return { result: "conflict" };
  }
}

export function readPlayCampaignSafetyEvents(
  campaignId: string,
  actor: string,
): { result: "found"; events: PlayCampaignSafetyEvent[] } | { result: "not_found" | "forbidden" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!playCampaignActor(campaignId, actor)) return { result: "forbidden" };
  const rows = database.prepare(`
    SELECT event_id, kind, text, tags_json, sequence FROM play_campaign_safety_events
    WHERE campaign_id = ? ORDER BY sequence ASC
  `).all(campaignId) as Array<Omit<PlayCampaignSafetyEvent, "tags"> & { tags_json: string }>;
  return {
    result: "found",
    events: rows.map((event) => ({
      event_id: event.event_id,
      kind: event.kind,
      text: event.text,
      tags: JSON.parse(event.tags_json) as string[],
      sequence: event.sequence,
    })),
  };
}

/** Append-only feed events use a campaign-local sequence so cursors stay valid as new events arrive. */
export function appendPlayCampaignFeedEvent(
  campaignId: string,
  actor: string,
  input: Pick<PlayCampaignFeedEvent, "event_id" | "text">,
): { result: "created"; event: PlayCampaignFeedEvent } | { result: "not_found" | "forbidden" | "conflict" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!playCampaignActor(campaignId, actor)) return { result: "forbidden" };
  try {
    const event = database.prepare(`
      INSERT INTO play_campaign_feed_events (campaign_id, sequence, event_id, text)
      VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_feed_events WHERE campaign_id = ?), 0) + 1, ?, ?)
      RETURNING event_id, text, sequence
    `).get(campaignId, campaignId, input.event_id, input.text) as PlayCampaignFeedEvent;
    return { result: "created", event };
  } catch {
    return { result: "conflict" };
  }
}

export function readPlayCampaignFeedEvents(
  campaignId: string,
  actor: string,
  cursor: number,
  limit: number,
): { result: "found"; events: PlayCampaignFeedEvent[] } | { result: "not_found" | "forbidden" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!playCampaignActor(campaignId, actor)) return { result: "forbidden" };
  const events = database.prepare(`
    SELECT event_id, text, sequence FROM play_campaign_feed_events
    WHERE campaign_id = ? ORDER BY sequence ASC LIMIT ? OFFSET ?
  `).all(campaignId, limit, cursor) as PlayCampaignFeedEvent[];
  return { result: "found", events };
}

export function resolvePlayCampaignModerationReport(
  campaignId: string,
  actor: string,
  reportId: string,
  input: Pick<PlayCampaignModerationResolvedReport, "action" | "note">,
): { result: "resolved"; report: PlayCampaignModerationResolvedReport } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const report = database.prepare(`
    SELECT status FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?
  `).get(campaignId, reportId) as { status: "open" | "resolved" } | undefined;
  if (!report) return { result: "not_found" };
  if (report.status !== "open") return { result: "conflict" };
  const resolved = database.prepare(`
    UPDATE play_campaign_moderation_reports
    SET status = 'resolved', action = ?, note = ?, resolver = ?
    WHERE campaign_id = ? AND report_id = ? AND status = 'open'
    RETURNING report_id, target_id, reason, status, reporter, sequence, action, note, resolver
  `).get(input.action, input.note, actor, campaignId, reportId) as PlayCampaignModerationResolvedReport | undefined;
  return resolved ? { result: "resolved", report: resolved } : { result: "conflict" };
}

/**
 * Atomically accepts one expected campaign turn.  The transaction ensures that
 * simultaneous requests cannot both consume the same turn.
 */
export function submitPlayCampaignSafeTurn(
  campaignId: string,
  actor: string,
  input: Pick<PlayCampaignSafeTurn, "submission_id" | "action"> & { expected_turn: number },
): { result: "created"; turn: PlayCampaignSafeTurn } | { result: "not_found" | "forbidden" | "duplicate" | "stale"; current_turn?: number } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };

  database.exec("BEGIN IMMEDIATE");
  try {
    database.prepare(`INSERT INTO play_campaign_safe_turn_state (campaign_id, current_turn)
      VALUES (?, 1) ON CONFLICT(campaign_id) DO NOTHING`).run(campaignId);
    const state = database.prepare("SELECT current_turn FROM play_campaign_safe_turn_state WHERE campaign_id = ?")
      .get(campaignId) as { current_turn: number };
    if (database.prepare("SELECT 1 FROM play_campaign_safe_turns WHERE campaign_id = ? AND submission_id = ?")
      .get(campaignId, input.submission_id)) {
      database.exec("COMMIT");
      return { result: "duplicate" };
    }
    if (state.current_turn !== input.expected_turn) {
      database.exec("COMMIT");
      return { result: "stale", current_turn: state.current_turn };
    }
    const next_turn = state.current_turn + 1;
    database.prepare("UPDATE play_campaign_safe_turn_state SET current_turn = ? WHERE campaign_id = ?")
      .run(next_turn, campaignId);
    database.prepare(`INSERT INTO play_campaign_safe_turns
      (campaign_id, submission_id, action, accepted_turn, next_turn) VALUES (?, ?, ?, ?, ?)`)
      .run(campaignId, input.submission_id, input.action, state.current_turn, next_turn);
    database.exec("COMMIT");
    return { result: "created", turn: { submission_id: input.submission_id, action: input.action, accepted_turn: state.current_turn, next_turn } };
  } catch {
    try { database.exec("ROLLBACK"); } catch { /* transaction already closed */ }
    // A uniqueness race can only mean that this submission was accepted by
    // another concurrent request; it must never advance the turn again.
    return { result: "duplicate" };
  }
}

export function readPlayCampaignSafeTurns(
  campaignId: string,
  actor: string,
): { result: "found"; current_turn: number; accepted: PlayCampaignSafeTurn[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  database.prepare(`INSERT INTO play_campaign_safe_turn_state (campaign_id, current_turn)
    VALUES (?, 1) ON CONFLICT(campaign_id) DO NOTHING`).run(campaignId);
  const state = database.prepare("SELECT current_turn FROM play_campaign_safe_turn_state WHERE campaign_id = ?")
    .get(campaignId) as { current_turn: number };
  const accepted = database.prepare(`SELECT submission_id, action, accepted_turn, next_turn
    FROM play_campaign_safe_turns WHERE campaign_id = ? ORDER BY accepted_turn ASC`)
    .all(campaignId) as PlayCampaignSafeTurn[];
  return { result: "found", current_turn: state.current_turn, accepted };
}

const calendarWeather = ["clear", "rain", "wind", "snow"] as const;
const seasonOffset: Record<PlayCampaignSeason, number> = {
  spring: 0,
  summer: 1,
  autumn: 2,
  winter: 3,
};

function calendarFromRow(row: { day: number; season: PlayCampaignSeason }): PlayCampaignCalendar {
  return {
    day: row.day,
    season: row.season,
    weather: calendarWeather[(row.day + seasonOffset[row.season]) % 4],
  };
}

export function initializePlayCampaignCalendar(
  campaignId: string,
  actor: string,
  calendar: Pick<PlayCampaignCalendar, "day" | "season">,
): { result: "created"; calendar: PlayCampaignCalendar } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };

  try {
    database.prepare("INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (?, ?, ?)")
      .run(campaignId, calendar.day, calendar.season);
    return { result: "created", calendar: calendarFromRow(calendar) };
  } catch {
    return { result: "conflict" };
  }
}

export function readPlayCampaignCalendar(
  campaignId: string,
  actor: string,
): { result: "found"; calendar: PlayCampaignCalendar } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };

  const calendar = database.prepare("SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?")
    .get(campaignId) as { day: number; season: PlayCampaignSeason } | undefined;
  return calendar ? { result: "found", calendar: calendarFromRow(calendar) } : { result: "not_found" };
}

export function advancePlayCampaignCalendar(
  campaignId: string,
  actor: string,
  days: number,
): { result: "advanced"; calendar: PlayCampaignCalendar } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };

  const calendar = database.prepare("SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?")
    .get(campaignId) as { day: number; season: PlayCampaignSeason } | undefined;
  if (!calendar) return { result: "not_found" };

  const updated = { ...calendar, day: calendar.day + days };
  database.prepare("UPDATE play_campaign_calendars SET day = ? WHERE campaign_id = ?")
    .run(updated.day, campaignId);
  return { result: "advanced", calendar: calendarFromRow(updated) };
}

type PlayCampaignSettlementRow = Omit<PlayCampaignSettlement, "services" | "discovered_by"> & {
  services_json: string;
};

function settlementFromRow(row: PlayCampaignSettlementRow, discoveredBy: string[]): PlayCampaignSettlement {
  return {
    settlement_id: row.settlement_id,
    name: row.name,
    services: JSON.parse(row.services_json) as string[],
    availability: row.availability,
    discovered_by: discoveredBy,
  };
}

function settlementDiscoverers(campaignId: string, settlementId: string): string[] {
  return (database.prepare(`
    SELECT character_id FROM play_campaign_settlement_discoveries
    WHERE campaign_id = ? AND settlement_id = ?
    ORDER BY rowid ASC
  `).all(campaignId, settlementId) as Array<{ character_id: string }>).map(({ character_id }) => character_id);
}

export function createPlayCampaignSettlement(
  campaignId: string,
  actor: string,
  settlement: Omit<PlayCampaignSettlement, "discovered_by">,
): { result: "created"; settlement: PlayCampaignSettlement } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  try {
    database.prepare(`
      INSERT INTO play_campaign_settlements (campaign_id, settlement_id, name, services_json, availability)
      VALUES (?, ?, ?, ?, ?)
    `).run(campaignId, settlement.settlement_id, settlement.name, JSON.stringify(settlement.services), settlement.availability);
    return { result: "created", settlement: { ...settlement, discovered_by: [] } };
  } catch {
    return { result: "conflict" };
  }
}

export function replacePlayCampaignSettlement(
  campaignId: string,
  settlementId: string,
  actor: string,
  settlement: Pick<PlayCampaignSettlement, "name" | "services" | "availability">,
): { result: "updated"; settlement: PlayCampaignSettlement } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const existing = database.prepare(`
    SELECT settlement_id FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?
  `).get(campaignId, settlementId);
  if (!existing) return { result: "not_found" };
  database.prepare(`
    UPDATE play_campaign_settlements
    SET name = ?, services_json = ?, availability = ?
    WHERE campaign_id = ? AND settlement_id = ?
  `).run(settlement.name, JSON.stringify(settlement.services), settlement.availability, campaignId, settlementId);
  return {
    result: "updated",
    settlement: { settlement_id: settlementId, ...settlement, discovered_by: settlementDiscoverers(campaignId, settlementId) },
  };
}

export function discoverPlayCampaignSettlement(
  campaignId: string,
  settlementId: string,
  actor: string,
): { result: "created" | "found"; settlement: PlayCampaignSettlement } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner === actor) return { result: "forbidden" };
  const member = database.prepare(`
    SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?
  `).get(campaignId, actor) as { character_id: string } | undefined;
  if (!member) return { result: "forbidden" };
  const settlement = database.prepare(`
    SELECT settlement_id, name, services_json, availability
    FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?
  `).get(campaignId, settlementId) as PlayCampaignSettlementRow | undefined;
  if (!settlement) return { result: "not_found" };
  try {
    database.prepare(`
      INSERT INTO play_campaign_settlement_discoveries (campaign_id, settlement_id, character_id)
      VALUES (?, ?, ?)
    `).run(campaignId, settlementId, member.character_id);
    return { result: "created", settlement: settlementFromRow(settlement, [member.character_id]) };
  } catch {
    return { result: "found", settlement: settlementFromRow(settlement, [member.character_id]) };
  }
}

export function readPlayCampaignSettlements(
  campaignId: string,
  actor: string,
): { result: "found"; settlements: PlayCampaignSettlement[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  const isOwner = campaign.owner === actor;
  const member = isOwner ? undefined : database.prepare(`
    SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?
  `).get(campaignId, actor) as { character_id: string } | undefined;
  if (!isOwner && !member) return { result: "forbidden" };
  const rows = database.prepare(`
    SELECT settlement_id, name, services_json, availability
    FROM play_campaign_settlements WHERE campaign_id = ?
    ORDER BY rowid ASC
  `).all(campaignId) as PlayCampaignSettlementRow[];
  const settlements = isOwner
    ? rows.map((row) => settlementFromRow(row, settlementDiscoverers(campaignId, row.settlement_id)))
    : rows.flatMap((row) => {
      const discovered = Boolean(database.prepare(`
        SELECT 1 FROM play_campaign_settlement_discoveries
        WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?
      `).get(campaignId, row.settlement_id, member!.character_id));
      return discovered ? [settlementFromRow(row, [member!.character_id])] : [];
    });
  return { result: "found", settlements };
}

type PlayCampaignShopRow = Omit<PlayCampaignShop, "stock">;

function shopFromRow(campaignId: string, settlementId: string, row: PlayCampaignShopRow): PlayCampaignShop {
  const stockRows = database.prepare(`
    SELECT item_id, quantity FROM play_campaign_shop_stock
    WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?
    ORDER BY item_id ASC
  `).all(campaignId, settlementId, row.shop_id) as PlayCampaignInventoryItem[];
  const stock: Record<string, number> = {};
  for (const item of stockRows) stock[item.item_id] = item.quantity;
  return { shop_id: row.shop_id, name: row.name, stock, buy_price: row.buy_price, sell_price: row.sell_price };
}

function playCampaignSettlementExists(campaignId: string, settlementId: string): boolean {
  return Boolean(database.prepare(`
    SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?
  `).get(campaignId, settlementId));
}

function playCampaignShopRow(campaignId: string, settlementId: string, shopId: string): PlayCampaignShopRow | undefined {
  return database.prepare(`
    SELECT shop_id, name, buy_price, sell_price FROM play_campaign_shops
    WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?
  `).get(campaignId, settlementId, shopId) as PlayCampaignShopRow | undefined;
}

export function createPlayCampaignShop(
  campaignId: string,
  settlementId: string,
  actor: string,
  shop: PlayCampaignShop,
): { result: "created"; shop: PlayCampaignShop } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign || !playCampaignSettlementExists(campaignId, settlementId)) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  database.exec("BEGIN IMMEDIATE");
  try {
    database.prepare(`
      INSERT INTO play_campaign_shops (campaign_id, settlement_id, shop_id, name, buy_price, sell_price)
      VALUES (?, ?, ?, ?, ?, ?)
    `).run(campaignId, settlementId, shop.shop_id, shop.name, shop.buy_price, shop.sell_price);
    const insertStock = database.prepare(`
      INSERT INTO play_campaign_shop_stock (campaign_id, settlement_id, shop_id, item_id, quantity)
      VALUES (?, ?, ?, ?, ?)
    `);
    for (const [itemId, quantity] of Object.entries(shop.stock)) {
      insertStock.run(campaignId, settlementId, shop.shop_id, itemId, quantity);
    }
    database.exec("COMMIT");
    return { result: "created", shop };
  } catch {
    database.exec("ROLLBACK");
    return { result: "conflict" };
  }
}

export function readPlayCampaignShop(
  campaignId: string,
  settlementId: string,
  shopId: string,
  actor: string,
): { result: "found"; shop: PlayCampaignShop } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign || !playCampaignSettlementExists(campaignId, settlementId)) return { result: "not_found" };
  const isOwner = campaign.owner === actor;
  const member = isOwner ? undefined : database.prepare(`
    SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?
  `).get(campaignId, actor) as { character_id: string } | undefined;
  if (!isOwner && !member) return { result: "forbidden" };
  const shop = playCampaignShopRow(campaignId, settlementId, shopId);
  if (!shop) return { result: "not_found" };
  if (!isOwner && !database.prepare(`
    SELECT 1 FROM play_campaign_settlement_discoveries
    WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?
  `).get(campaignId, settlementId, member!.character_id)) return { result: "not_found" };
  return { result: "found", shop: shopFromRow(campaignId, settlementId, shop) };
}

export function tradePlayCampaignShop(
  campaignId: string,
  settlementId: string,
  shopId: string,
  actor: string,
  characterId: string,
  itemId: string,
  quantity: number,
  direction: "buy" | "sell",
): { result: "traded"; trade: PlayCampaignShopTrade } | { result: "not_found" | "forbidden" | "insufficient" } {
  if (!playCampaignOwner(campaignId) || !playCampaignSettlementExists(campaignId, settlementId)) return { result: "not_found" };
  const shop = playCampaignShopRow(campaignId, settlementId, shopId);
  if (!shop) return { result: "not_found" };
  const owner = database.prepare(`
    SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as { owner: string } | undefined;
  if (!owner) return { result: "not_found" };
  if (owner.owner !== actor) return { result: "forbidden" };

  database.exec("BEGIN IMMEDIATE");
  try {
    const stockRow = database.prepare(`
      SELECT quantity FROM play_campaign_shop_stock
      WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? AND item_id = ?
    `).get(campaignId, settlementId, shopId, itemId) as { quantity: number } | undefined;
    const currency = database.prepare(`
      SELECT gold FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id = ?
    `).get(campaignId, characterId) as { gold: number } | undefined;
    const held = database.prepare(`
      SELECT quantity FROM play_campaign_character_inventory_items
      WHERE campaign_id = ? AND character_id = ? AND item_id = ?
    `).get(campaignId, characterId, itemId) as { quantity: number } | undefined;
    if (!currency) {
      database.exec("ROLLBACK");
      return { result: "not_found" };
    }
    if (direction === "buy" && (!stockRow || stockRow.quantity < quantity || currency.gold < shop.buy_price * quantity)) {
      database.exec("ROLLBACK");
      return { result: "insufficient" };
    }
    if (direction === "sell" && (!held || held.quantity < quantity)) {
      database.exec("ROLLBACK");
      return { result: "insufficient" };
    }
    const nextGold = direction === "buy" ? currency.gold - shop.buy_price * quantity : currency.gold + shop.sell_price * quantity;
    const nextStock = (stockRow?.quantity ?? 0) + (direction === "buy" ? -quantity : quantity);
    database.prepare(`UPDATE play_campaign_character_currency SET gold = ? WHERE campaign_id = ? AND character_id = ?`)
      .run(nextGold, campaignId, characterId);
    database.prepare(`
      INSERT INTO play_campaign_shop_stock (campaign_id, settlement_id, shop_id, item_id, quantity)
      VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(campaign_id, settlement_id, shop_id, item_id) DO UPDATE SET quantity = excluded.quantity
    `).run(campaignId, settlementId, shopId, itemId, nextStock);
    if (direction === "buy") {
      database.prepare(`
        INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity
      `).run(campaignId, characterId, itemId, quantity);
    }
    database.exec("COMMIT");
    return { result: "traded", trade: { character_id: characterId, item_id: itemId, quantity, gold: nextGold, stock: nextStock } };
  } catch (error) {
    database.exec("ROLLBACK");
    throw error;
  }
}

export function createPlayCampaignScene(
  campaignId: string,
  owner: string,
  scene: Pick<PlayCampaignScene, "id" | "name">,
): { result: "created"; scene: PlayCampaignScene } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };

  try {
    const created = { ...scene, status: "open" as const };
    database.prepare(`
      INSERT INTO play_campaign_scenes (campaign_id, id, name, status)
      VALUES (?, ?, ?, ?)
    `).run(campaignId, created.id, created.name, created.status);
    return { result: "created", scene: created };
  } catch {
    return { result: "conflict" };
  }
}

export function createPlayCampaignLocation(
  campaignId: string,
  owner: string,
  location: PlayCampaignLocation,
): { result: "created"; location: PlayCampaignLocation } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };

  try {
    database.prepare(`
      INSERT INTO play_campaign_locations (campaign_id, id, name)
      VALUES (?, ?, ?)
    `).run(campaignId, location.id, location.name);
    return { result: "created", location };
  } catch {
    return { result: "conflict" };
  }
}

export function createPlayCampaignLocationConnection(
  campaignId: string,
  owner: string,
  connection: PlayCampaignLocationConnection,
): { result: "created"; connection: PlayCampaignLocationConnection } | { result: "not_found" | "forbidden" | "invalid" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };

  const locations = database.prepare(`
    SELECT
      EXISTS(SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?) AS from_exists,
      EXISTS(SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?) AS to_exists
  `).get(campaignId, connection.from_id, campaignId, connection.to_id) as {
    from_exists: number;
    to_exists: number;
  };
  if (!locations.from_exists || !locations.to_exists) return { result: "invalid" };

  try {
    database.prepare(`
      INSERT INTO play_campaign_location_connections (campaign_id, from_id, to_id, travel_turns)
      VALUES (?, ?, ?, ?)
    `).run(campaignId, connection.from_id, connection.to_id, connection.travel_turns);
    return { result: "created", connection };
  } catch {
    return { result: "invalid" };
  }
}

export function readPlayCampaignTravel(
  campaignId: string,
  actor: string,
  locationId: string,
): { result: "found"; destinations: Array<PlayCampaignLocation & Pick<PlayCampaignLocationConnection, "travel_turns">> } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };

  const location = database.prepare(`
    SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?
  `).get(campaignId, locationId);
  if (!location) return { result: "not_found" };

  const destinations = database.prepare(`
    SELECT locations.id, locations.name, connections.travel_turns
    FROM play_campaign_location_connections AS connections
    JOIN play_campaign_locations AS locations
      ON locations.campaign_id = connections.campaign_id AND locations.id = connections.to_id
    WHERE connections.campaign_id = ? AND connections.from_id = ?
    ORDER BY connections.rowid ASC
  `).all(campaignId, locationId) as Array<PlayCampaignLocation & Pick<PlayCampaignLocationConnection, "travel_turns">>;
  return { result: "found", destinations };
}

export function enterPlayCampaignScene(
  campaignId: string,
  owner: string,
  sceneId: string,
): { result: "entered"; scene: Pick<PlayCampaignScene, "id" | "name"> } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };

  const scene = database.prepare(`
    SELECT id, name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?
  `).get(campaignId, sceneId) as PlayCampaignScene | undefined;
  if (!scene) return { result: "not_found" };
  if (scene.status !== "open") return { result: "conflict" };

  database.prepare(`
    INSERT INTO play_campaign_scene_state (campaign_id, current_scene_id)
    VALUES (?, ?)
    ON CONFLICT(campaign_id) DO UPDATE SET current_scene_id = excluded.current_scene_id
  `).run(campaignId, sceneId);
  database.prepare(`
    INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text)
    VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_events WHERE campaign_id = ?), 0) + 1, 'scene', ?, ?)
  `).run(campaignId, campaignId, owner, sceneId);
  return { result: "entered", scene: { id: scene.id, name: scene.name } };
}

export function closePlayCampaignScene(
  campaignId: string,
  owner: string,
  sceneId: string,
): { result: "closed"; scene: Pick<PlayCampaignScene, "id" | "status"> } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };

  const update = database.prepare(`
    UPDATE play_campaign_scenes SET status = 'closed' WHERE campaign_id = ? AND id = ?
  `).run(campaignId, sceneId);
  if (update.changes !== 1) return { result: "not_found" };
  return { result: "closed", scene: { id: sceneId, status: "closed" } };
}

export function readCurrentPlayCampaignScene(
  campaignId: string,
  actor: string,
): { result: "found"; scene: PlayCampaignScene } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };

  const scene = database.prepare(`
    SELECT scenes.id, scenes.name, scenes.status
    FROM play_campaign_scene_state AS state
    JOIN play_campaign_scenes AS scenes
      ON scenes.campaign_id = state.campaign_id AND scenes.id = state.current_scene_id
    WHERE state.campaign_id = ? AND scenes.status = 'open'
  `).get(campaignId) as PlayCampaignScene | undefined;
  return scene ? { result: "found", scene } : { result: "not_found" };
}

export function updatePlayCampaignDocument(
  campaignId: string,
  owner: string,
  document: PlayCampaignDocument,
): { result: "updated"; document: PlayCampaignDocument } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };

  database.prepare(`
    INSERT INTO play_campaign_documents (campaign_id, story, dm_notes)
    VALUES (?, ?, ?)
    ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story, dm_notes = excluded.dm_notes
  `).run(campaignId, document.story, document.dm_notes);
  return { result: "updated", document };
}

export function readPlayCampaignDocument(
  campaignId: string,
  actor: string,
): { result: "found"; document: PlayCampaignDocument; is_owner: boolean } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };

  const isOwner = campaign.owner === actor;
  if (!isOwner) {
    const member = database.prepare(
      "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
    ).get(campaignId, actor);
    if (!member) return { result: "forbidden" };
  }

  const document = database.prepare(`
    SELECT story, dm_notes FROM play_campaign_documents WHERE campaign_id = ?
  `).get(campaignId) as PlayCampaignDocument | undefined;
  if (!document) return { result: "not_found" };
  return { result: "found", document, is_owner: isOwner };
}

/** Captures the public campaign document in a permanently versioned snapshot. */
export function createPlayCampaignExport(
  campaignId: string,
  actor: string,
): { result: "created"; export: PlayCampaignExport } | { result: "not_found" | "forbidden" } {
  database.exec("BEGIN IMMEDIATE");
  try {
    const campaign = database.prepare("SELECT owner, status FROM play_campaigns WHERE id = ?")
      .get(campaignId) as Pick<PlayCampaign, "owner" | "status"> | undefined;
    if (!campaign) {
      database.exec("ROLLBACK");
      return { result: "not_found" };
    }
    if (campaign.owner !== actor) {
      database.exec("ROLLBACK");
      return { result: "forbidden" };
    }

    const document = database.prepare("SELECT story FROM play_campaign_documents WHERE campaign_id = ?")
      .get(campaignId) as Pick<PlayCampaignDocument, "story"> | undefined;
    // A campaign document is the source of truth for an export.  A missing one
    // is treated as unavailable, just like a document read before it is created.
    if (!document) {
      database.exec("ROLLBACK");
      return { result: "not_found" };
    }

    const row = database.prepare(
      "SELECT COALESCE(MAX(version), 0) + 1 AS version FROM play_campaign_exports WHERE campaign_id = ?",
    ).get(campaignId) as { version: number };
    const snapshot: PlayCampaignExport = {
      version: row.version,
      story: document.story,
      status: campaign.status,
    };
    database.prepare(`
      INSERT INTO play_campaign_exports (campaign_id, version, story, status)
      VALUES (?, ?, ?, ?)
    `).run(campaignId, snapshot.version, snapshot.story, snapshot.status);
    database.exec("COMMIT");
    return { result: "created", export: snapshot };
  } catch (error) {
    try { database.exec("ROLLBACK"); } catch { /* transaction already closed */ }
    throw error;
  }
}

export function readPlayCampaignExports(
  campaignId: string,
  actor: string,
): { result: "found"; exports: PlayCampaignExport[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const exports = database.prepare(`
    SELECT version, story, status
    FROM play_campaign_exports
    WHERE campaign_id = ?
    ORDER BY version ASC
  `).all(campaignId) as PlayCampaignExport[];
  return { result: "found", exports };
}

export function readPlayCampaignExport(
  campaignId: string,
  version: number,
  actor: string,
): { result: "found"; export: PlayCampaignExport } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const snapshot = database.prepare(`
    SELECT version, story, status FROM play_campaign_exports
    WHERE campaign_id = ? AND version = ?
  `).get(campaignId, version) as PlayCampaignExport | undefined;
  return snapshot ? { result: "found", export: snapshot } : { result: "not_found" };
}

/** Captures the public campaign state in a numbered immutable backup. */
export function createPlayCampaignBackup(
  campaignId: string,
  actor: string,
): { result: "created"; backup: PlayCampaignBackup } | { result: "not_found" | "forbidden" } {
  database.exec("BEGIN IMMEDIATE");
  try {
    const campaign = database.prepare("SELECT owner, status FROM play_campaigns WHERE id = ?")
      .get(campaignId) as Pick<PlayCampaign, "owner" | "status"> | undefined;
    if (!campaign) {
      database.exec("ROLLBACK");
      return { result: "not_found" };
    }
    if (campaign.owner !== actor) {
      database.exec("ROLLBACK");
      return { result: "forbidden" };
    }
    const document = database.prepare("SELECT story FROM play_campaign_documents WHERE campaign_id = ?")
      .get(campaignId) as Pick<PlayCampaignDocument, "story"> | undefined;
    if (!document) {
      database.exec("ROLLBACK");
      return { result: "not_found" };
    }
    const row = database.prepare(
      "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_backups WHERE campaign_id = ?",
    ).get(campaignId) as { sequence: number };
    const backup: PlayCampaignBackup = {
      backup_id: `backup-${row.sequence}`,
      story: document.story,
      status: campaign.status,
    };
    database.prepare(`
      INSERT INTO play_campaign_backups (campaign_id, backup_id, sequence, story, status)
      VALUES (?, ?, ?, ?, ?)
    `).run(campaignId, backup.backup_id, row.sequence, backup.story, backup.status);
    database.exec("COMMIT");
    return { result: "created", backup };
  } catch (error) {
    try { database.exec("ROLLBACK"); } catch { /* transaction already closed */ }
    throw error;
  }
}

export function readPlayCampaignBackups(
  campaignId: string,
  actor: string,
): { result: "found"; backups: PlayCampaignBackup[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const backups = database.prepare(`
    SELECT backup_id, story, status FROM play_campaign_backups
    WHERE campaign_id = ? ORDER BY sequence ASC
  `).all(campaignId) as PlayCampaignBackup[];
  return { result: "found", backups };
}

/** Restores story and status only; the immutable backup and event streams are untouched. */
export function restorePlayCampaignBackup(
  campaignId: string,
  backupId: string,
  actor: string,
): { result: "restored"; backup: PlayCampaignBackup } | { result: "not_found" | "forbidden" } {
  database.exec("BEGIN IMMEDIATE");
  try {
    const campaign = database.prepare("SELECT owner FROM play_campaigns WHERE id = ?")
      .get(campaignId) as Pick<PlayCampaign, "owner"> | undefined;
    if (!campaign) {
      database.exec("ROLLBACK");
      return { result: "not_found" };
    }
    if (campaign.owner !== actor) {
      database.exec("ROLLBACK");
      return { result: "forbidden" };
    }
    const backup = database.prepare(`
      SELECT backup_id, story, status FROM play_campaign_backups
      WHERE campaign_id = ? AND backup_id = ?
    `).get(campaignId, backupId) as PlayCampaignBackup | undefined;
    if (!backup) {
      database.exec("ROLLBACK");
      return { result: "not_found" };
    }
    database.prepare(`
      INSERT INTO play_campaign_documents (campaign_id, story, dm_notes)
      VALUES (?, ?, '')
      ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story
    `).run(campaignId, backup.story);
    database.prepare("UPDATE play_campaigns SET status = ? WHERE id = ?")
      .run(backup.status, campaignId);
    database.exec("COMMIT");
    return { result: "restored", backup };
  } catch (error) {
    try { database.exec("ROLLBACK"); } catch { /* transaction already closed */ }
    throw error;
  }
}

/**
 * Applies the compatibility snapshot as one SQLite transaction.  The imported
 * status is kept verbatim for compatibility while the campaign retains its
 * established active/lobby status vocabulary.
 */
export function importPlayCampaign(
  campaignId: string,
  actor: string,
  snapshot: PlayCampaignImport,
): { result: "imported"; snapshot: PlayCampaignImport } | { result: "not_found" | "forbidden" } {
  database.exec("BEGIN IMMEDIATE");
  try {
    const campaign = database.prepare("SELECT owner FROM play_campaigns WHERE id = ?")
      .get(campaignId) as Pick<PlayCampaign, "owner"> | undefined;
    if (!campaign) {
      database.exec("ROLLBACK");
      return { result: "not_found" };
    }
    if (campaign.owner !== actor) {
      database.exec("ROLLBACK");
      return { result: "forbidden" };
    }

    database.prepare(`
      INSERT INTO play_campaign_documents (campaign_id, story, dm_notes)
      VALUES (?, ?, '')
      ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story
    `).run(campaignId, snapshot.story);
    database.prepare("UPDATE play_campaigns SET status = ? WHERE id = ?")
      .run(snapshot.status === "started" ? "active" : "lobby", campaignId);
    database.prepare(`
      INSERT INTO play_campaign_import_states (campaign_id, version, story, status)
      VALUES (?, ?, ?, ?)
      ON CONFLICT(campaign_id) DO UPDATE SET
        version = excluded.version,
        story = excluded.story,
        status = excluded.status
    `).run(campaignId, snapshot.version, snapshot.story, snapshot.status);
    database.exec("COMMIT");
    return { result: "imported", snapshot };
  } catch (error) {
    try { database.exec("ROLLBACK"); } catch { /* transaction already closed */ }
    throw error;
  }
}

export function readPlayCampaignImportState(
  campaignId: string,
  actor: string,
): { result: "found"; snapshot: PlayCampaignImport } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const snapshot = database.prepare(`
    SELECT version, story, status FROM play_campaign_import_states WHERE campaign_id = ?
  `).get(campaignId) as PlayCampaignImport | undefined;
  return snapshot ? { result: "found", snapshot } : { result: "not_found" };
}

/** Migrates the one supported legacy snapshot shape without touching campaign state. */
export function migratePlayCampaignSnapshot(
  campaignId: string,
  actor: string,
  story: string,
): { result: "migrated"; state: PlayCampaignMigrationState; idempotent: boolean } | { result: "not_found" | "forbidden" } {
  database.exec("BEGIN IMMEDIATE");
  try {
    const campaign = database.prepare("SELECT name, owner FROM play_campaigns WHERE id = ?")
      .get(campaignId) as Pick<PlayCampaign, "name" | "owner"> | undefined;
    if (!campaign) {
      database.exec("ROLLBACK");
      return { result: "not_found" };
    }
    if (campaign.owner !== actor) {
      database.exec("ROLLBACK");
      return { result: "forbidden" };
    }

    const existing = database.prepare(`
      SELECT schema_version, story, campaign_name
      FROM play_campaign_migration_states WHERE campaign_id = ?
    `).get(campaignId) as PlayCampaignMigrationState | undefined;
    const state: PlayCampaignMigrationState = { schema_version: 2, story, campaign_name: campaign.name };
    if (existing && existing.story === state.story && existing.campaign_name === state.campaign_name) {
      database.exec("COMMIT");
      return { result: "migrated", state: existing, idempotent: true };
    }

    database.prepare(`
      INSERT INTO play_campaign_migration_states (campaign_id, schema_version, story, campaign_name)
      VALUES (?, ?, ?, ?)
      ON CONFLICT(campaign_id) DO UPDATE SET
        schema_version = excluded.schema_version,
        story = excluded.story,
        campaign_name = excluded.campaign_name
    `).run(campaignId, state.schema_version, state.story, state.campaign_name);
    database.exec("COMMIT");
    return { result: "migrated", state, idempotent: false };
  } catch (error) {
    try { database.exec("ROLLBACK"); } catch { /* transaction already closed */ }
    throw error;
  }
}

export function readPlayCampaignMigrationState(
  campaignId: string,
  actor: string,
): { result: "found"; state: PlayCampaignMigrationState } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const state = database.prepare(`
    SELECT schema_version, story, campaign_name
    FROM play_campaign_migration_states WHERE campaign_id = ?
  `).get(campaignId) as PlayCampaignMigrationState | undefined;
  return state ? { result: "found", state } : { result: "not_found" };
}

export function updatePlayCampaignSessionZeroSettings(
  campaignId: string,
  actor: string,
  settings: PlayCampaignSessionZeroSettings,
): { result: "updated"; settings: PlayCampaignSessionZeroSettings } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = database.prepare("SELECT owner, status FROM play_campaigns WHERE id = ?")
    .get(campaignId) as Pick<PlayCampaign, "owner" | "status"> | undefined;
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  if (campaign.status !== "lobby") return { result: "conflict" };

  database.prepare(`
    INSERT INTO play_campaign_session_zero_settings (campaign_id, rules, tone, consent_json)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(campaign_id) DO UPDATE SET
      rules = excluded.rules,
      tone = excluded.tone,
      consent_json = excluded.consent_json
  `).run(campaignId, settings.rules, settings.tone, JSON.stringify(settings.consent));
  return { result: "updated", settings };
}

export function readPlayCampaignSessionZeroSettings(
  campaignId: string,
  actor: string,
): { result: "found"; settings: PlayCampaignSessionZeroSettings } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };

  const row = database.prepare(`
    SELECT rules, tone, consent_json FROM play_campaign_session_zero_settings WHERE campaign_id = ?
  `).get(campaignId) as { rules: string; tone: string; consent_json: string } | undefined;
  if (!row) return { result: "not_found" };
  return { result: "found", settings: { rules: row.rules, tone: row.tone, consent: JSON.parse(row.consent_json) as string[] } };
}

export function createPlayCampaign(campaign: PlayCampaign): boolean {
  try {
    database.prepare(`
      INSERT INTO play_campaigns (id, name, owner, status, max_players)
      VALUES (?, ?, ?, ?, ?)
    `).run(campaign.id, campaign.name, campaign.owner, campaign.status, campaign.max_players);
    return true;
  } catch {
    return false;
  }
}

/** Create a globally-addressable, bearer-token spectator ticket for an owner. */
export function createPlayCampaignSpectator(
  campaignId: string,
  owner: string,
  spectatorId: string,
): "created" | "not_found" | "forbidden" | "conflict" {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return "not_found";
  if (campaign.owner !== owner) return "forbidden";
  try {
    database.prepare(`
      INSERT INTO play_campaign_spectators (spectator_id, campaign_id)
      VALUES (?, ?)
    `).run(spectatorId, campaignId);
    return "created";
  } catch {
    return "conflict";
  }
}

/** Read the intentionally small, repeat-stable projection available to a spectator. */
export function readPlayCampaignSpectatorView(
  campaignId: string,
  spectatorId: string,
): { result: "found"; view: PlayCampaignSpectatorView } | { result: "not_found" | "unauthorized" | "forbidden" } {
  const campaign = database.prepare(`
    SELECT id, name, status FROM play_campaigns WHERE id = ?
  `).get(campaignId) as Pick<PlayCampaign, "id" | "name" | "status"> | undefined;
  if (!campaign) return { result: "not_found" };

  const ticket = database.prepare(`
    SELECT campaign_id FROM play_campaign_spectators WHERE spectator_id = ?
  `).get(spectatorId) as { campaign_id: string } | undefined;
  if (!ticket) return { result: "unauthorized" };
  if (ticket.campaign_id !== campaignId) return { result: "forbidden" };

  const party = database.prepare(`
    SELECT COUNT(*) AS party_size FROM play_campaign_members WHERE campaign_id = ?
  `).get(campaignId) as { party_size: number };
  const document = database.prepare(`
    SELECT story FROM play_campaign_documents WHERE campaign_id = ?
  `).get(campaignId) as { story: string } | undefined;
  return {
    result: "found",
    view: {
      campaign_id: campaign.id,
      name: campaign.name,
      status: campaign.status,
      party_size: party.party_size,
      story: document?.story ?? "",
    },
  };
}

/** Start combat without consuming or otherwise modifying the exploration turn queue. */
export function createPlayCampaignEncounter(
  campaignId: string,
  owner: string,
  encounter: Pick<PlayCampaignEncounter, "id" | "name">,
): { result: "created"; encounter: PlayCampaignEncounter } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };

  const activeEncounter = database.prepare(
    "SELECT 1 FROM play_campaign_encounters WHERE campaign_id = ? AND status = 'active'",
  ).get(campaignId);
  if (activeEncounter) return { result: "conflict" };

  const created: PlayCampaignEncounter = { ...encounter, status: "active", combatants: [] };
  try {
    database.prepare(`
      INSERT INTO play_campaign_encounters (id, campaign_id, name, status)
      VALUES (?, ?, ?, ?)
    `).run(created.id, campaignId, created.name, created.status);
    database.prepare("UPDATE play_campaigns SET phase = 'combat' WHERE id = ?").run(campaignId);
    return { result: "created", encounter: created };
  } catch {
    return { result: "conflict" };
  }
}

/** Award an encounter's immutable reward record.  Closed encounters remain eligible. */
export function awardPlayCampaignEncounterRewards(
  campaignId: string,
  encounterId: string,
  owner: string,
  reward: Omit<PlayCampaignEncounterReward, "encounter_id">,
): { result: "awarded"; reward: PlayCampaignEncounterReward } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };

  const encounter = database.prepare(
    "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
  ).get(encounterId, campaignId);
  if (!encounter) return { result: "not_found" };

  const created: PlayCampaignEncounterReward = { encounter_id: encounterId, ...reward };
  try {
    database.prepare(`
      INSERT INTO play_campaign_encounter_rewards (encounter_id, xp, loot_json)
      VALUES (?, ?, ?)
    `).run(created.encounter_id, created.xp, JSON.stringify(created.loot));
    return { result: "awarded", reward: created };
  } catch {
    return { result: "conflict" };
  }
}

/** Close an encounter, reporting its previously awarded XP when present. */
export function closePlayCampaignEncounter(
  campaignId: string,
  encounterId: string,
  owner: string,
): { result: "closed"; encounter: { id: string; status: "closed"; xp_awarded: number } } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };

  const encounter = database.prepare(
    "SELECT id FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
  ).get(encounterId, campaignId) as { id: string } | undefined;
  if (!encounter) return { result: "not_found" };

  database.prepare("UPDATE play_campaign_encounters SET status = 'closed' WHERE id = ? AND campaign_id = ?")
    .run(encounterId, campaignId);
  const reward = database.prepare(
    "SELECT xp FROM play_campaign_encounter_rewards WHERE encounter_id = ?",
  ).get(encounterId) as { xp: number } | undefined;
  return { result: "closed", encounter: { id: encounter.id, status: "closed", xp_awarded: reward?.xp ?? 0 } };
}

/** End active combat and deterministically return turn authority to the DM. */
export function endPlayCampaignEncounter(
  campaignId: string,
  encounterId: string,
  owner: string,
): { result: "ended"; campaign: { campaign_id: string; status: "active"; phase: "exploration"; current_actor: string } }
  | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = database.prepare("SELECT owner, status, phase FROM play_campaigns WHERE id = ?")
    .get(campaignId) as Pick<PlayCampaign, "owner" | "status"> & { phase: "combat" | "exploration" } | undefined;
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };
  if (campaign.status !== "active" || campaign.phase !== "combat") return { result: "conflict" };

  const encounter = database.prepare(`
    SELECT status FROM play_campaign_encounters
    WHERE id = ? AND campaign_id = ?
  `).get(encounterId, campaignId) as { status: "active" | "closed" } | undefined;
  if (!encounter) return { result: "conflict" };
  if (encounter.status === "closed" && database.prepare(`
    SELECT 1 FROM play_campaign_encounters
    WHERE campaign_id = ? AND status = 'active'
  `).get(campaignId)) return { result: "conflict" };

  database.prepare(`
    UPDATE play_campaign_encounters
    SET status = 'closed'
    WHERE id = ? AND campaign_id = ? AND status = 'active'
  `).run(encounterId, campaignId);
  database.prepare(`
    INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text)
    VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_events WHERE campaign_id = ?), 0) + 1, 'combat_end', ?, ?)
  `).run(campaignId, campaignId, owner, encounterId);
  database.prepare("UPDATE play_campaigns SET phase = 'exploration' WHERE id = ?").run(campaignId);
  return {
    result: "ended",
    campaign: { campaign_id: campaignId, status: "active", phase: "exploration", current_actor: campaign.owner },
  };
}

/** Add an owner-controlled monster to a campaign encounter. */
export function addPlayCampaignEncounterMonster(
  campaignId: string,
  encounterId: string,
  owner: string,
  monster: Omit<PlayCampaignMonster, "hp_current">,
): { result: "created"; monster: PlayCampaignMonster } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };

  const encounter = database.prepare(
    "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
  ).get(encounterId, campaignId);
  if (!encounter) return { result: "not_found" };

  const created: PlayCampaignMonster = { ...monster, hp_current: monster.hp_max };
  try {
    database.prepare(`
      INSERT INTO play_campaign_encounter_monsters
        (encounter_id, monster_id, name, hp_max, hp_current, initiative)
      VALUES (?, ?, ?, ?, ?, ?)
    `).run(encounterId, created.monster_id, created.name, created.hp_max, created.hp_current, created.initiative);
    return { result: "created", monster: created };
  } catch {
    return { result: "conflict" };
  }
}

/** Remove an owner-controlled monster from a campaign encounter. */
export function removePlayCampaignEncounterMonster(
  campaignId: string,
  encounterId: string,
  owner: string,
  monsterId: string,
): { result: "removed" } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };

  const encounter = database.prepare(
    "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
  ).get(encounterId, campaignId);
  if (!encounter) return { result: "not_found" };

  const result = database.prepare(
    "DELETE FROM play_campaign_encounter_monsters WHERE encounter_id = ? AND monster_id = ?",
  ).run(encounterId, monsterId);
  return result.changes === 1 ? { result: "removed" } : { result: "not_found" };
}

export type PlayCampaignEncounterHpChange = {
  target: string;
  hp_before: number;
  hp_after: number;
};

/** Apply an owner-directed, bounded HP change to an encounter monster. */
function changePlayCampaignEncounterMonsterHp(
  campaignId: string,
  encounterId: string,
  owner: string,
  target: string,
  amount: number,
  direction: "damage" | "healing",
): { result: "changed"; change: PlayCampaignEncounterHpChange } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };

  const encounter = database.prepare(
    "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
  ).get(encounterId, campaignId);
  if (!encounter) return { result: "not_found" };

  const monster = database.prepare(`
    SELECT hp_current, hp_max
    FROM play_campaign_encounter_monsters
    WHERE encounter_id = ? AND monster_id = ?
  `).get(encounterId, target) as { hp_current: number; hp_max: number } | undefined;
  if (!monster) return { result: "not_found" };

  const hpAfter = direction === "damage"
    ? Math.max(0, monster.hp_current - amount)
    : Math.min(monster.hp_max, monster.hp_current + amount);
  database.prepare(`
    UPDATE play_campaign_encounter_monsters
    SET hp_current = ?
    WHERE encounter_id = ? AND monster_id = ?
  `).run(hpAfter, encounterId, target);
  return {
    result: "changed",
    change: { target, hp_before: monster.hp_current, hp_after: hpAfter },
  };
}

export function damagePlayCampaignEncounterCombatant(
  campaignId: string,
  encounterId: string,
  owner: string,
  target: string,
  amount: number,
): { result: "damaged"; damage: PlayCampaignEncounterHpChange } | { result: "not_found" | "forbidden" } {
  const result = changePlayCampaignEncounterMonsterHp(campaignId, encounterId, owner, target, amount, "damage");
  return result.result === "changed"
    ? { result: "damaged", damage: result.change }
    : result;
}

export function healPlayCampaignEncounterCombatant(
  campaignId: string,
  encounterId: string,
  owner: string,
  target: string,
  amount: number,
): { result: "healed"; healing: PlayCampaignEncounterHpChange } | { result: "not_found" | "forbidden" } {
  const result = changePlayCampaignEncounterMonsterHp(campaignId, encounterId, owner, target, amount, "healing");
  return result.result === "changed"
    ? { result: "healed", healing: result.change }
    : result;
}

/** Bind a party member to an active encounter using the member's campaign character. */
export function addPlayCampaignEncounterCombatant(
  campaignId: string,
  encounterId: string,
  owner: string,
  member: string,
  initiative: number,
): { result: "created"; combatant: PlayCampaignCombatant } | { result: "not_found" | "forbidden" | "conflict" | "invalid" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };

  const encounter = database.prepare(
    "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ? AND status = 'active'",
  ).get(encounterId, campaignId);
  if (!encounter) return { result: "not_found" };

  const partyMember = database.prepare(`
    SELECT username AS member, character_id, name
    FROM play_campaign_members
    WHERE campaign_id = ? AND username = ?
  `).get(campaignId, member) as Omit<PlayCampaignCombatant, "initiative"> | undefined;
  if (!partyMember) return { result: "invalid" };

  const combatant: PlayCampaignCombatant = { ...partyMember, initiative };
  try {
    database.prepare(`
      INSERT INTO play_campaign_encounter_combatants
        (encounter_id, member, character_id, name, initiative)
      VALUES (?, ?, ?, ?, ?)
    `).run(encounterId, combatant.member, combatant.character_id, combatant.name, combatant.initiative);
    return { result: "created", combatant };
  } catch {
    return { result: "conflict" };
  }
}

/** Unbind a party member from an active encounter. */
export function removePlayCampaignEncounterCombatant(
  campaignId: string,
  encounterId: string,
  owner: string,
  member: string,
): { result: "removed" } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };

  const encounter = database.prepare(
    "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ? AND status = 'active'",
  ).get(encounterId, campaignId);
  if (!encounter) return { result: "not_found" };

  const deleted = database.prepare(
    "DELETE FROM play_campaign_encounter_combatants WHERE encounter_id = ? AND member = ?",
  ).run(encounterId, member);
  return deleted.changes === 1 ? { result: "removed" } : { result: "not_found" };
}

function encounterCombatOrder(encounterId: string): PlayCampaignEncounterTurnCombatant[] {
  const monsters = database.prepare(`
    SELECT name, initiative, monster_id AS tie_breaker
    FROM play_campaign_encounter_monsters
    WHERE encounter_id = ?
  `).all(encounterId) as Array<{ name: string; initiative: number; tie_breaker: string }>;
  const players = database.prepare(`
    SELECT name, initiative, member
    FROM play_campaign_encounter_combatants
    WHERE encounter_id = ?
  `).all(encounterId) as Array<{ name: string; initiative: number; member: string }>;

  // Name, kind, and stable encounter-local id make initiative ties repeatable.
  const initiativeOrder = [
    ...monsters.map(({ name, initiative, tie_breaker }) => ({ name, initiative, kind: "monster" as const, target: tie_breaker, tieBreaker: tie_breaker })),
    ...players.map(({ name, initiative, member }) => ({ name, initiative, kind: "player" as const, member, target: member, tieBreaker: member })),
  ].sort((left, right) =>
    right.initiative - left.initiative ||
    left.name.localeCompare(right.name) ||
    left.kind.localeCompare(right.kind) ||
    left.tieBreaker.localeCompare(right.tieBreaker),
  ).map(({ tieBreaker: _tieBreaker, ...combatant }) => combatant);

  const delayed = database.prepare("SELECT order_json FROM play_campaign_encounter_turn_orders WHERE encounter_id = ?")
    .get(encounterId) as { order_json: string } | undefined;
  if (!delayed) return initiativeOrder;

  try {
    const targets = JSON.parse(delayed.order_json) as unknown;
    if (!Array.isArray(targets) || !targets.every((target) => typeof target === "string")) return initiativeOrder;
    const byTarget = new Map(initiativeOrder.map((combatant) => [combatant.target, combatant]));
    const ordered: PlayCampaignEncounterTurnCombatant[] = [];
    for (const target of targets) {
      const combatant = byTarget.get(target);
      if (!combatant) return initiativeOrder;
      ordered.push(combatant);
    }
    if (ordered.length !== initiativeOrder.length || new Set(ordered.map((combatant) => combatant.target)).size !== initiativeOrder.length) return initiativeOrder;
    return ordered;
  } catch {
    return initiativeOrder;
  }
}

function visibleEncounterCombatant(combatant: PlayCampaignEncounterTurnCombatant): PlayCampaignEncounterTurn["active"] {
  return { name: combatant.name, kind: combatant.kind, initiative: combatant.initiative };
}

function encounterConditions(encounterId: string): Record<string, PlayCampaignEncounterCondition[]> {
  const rows = database.prepare(`
    SELECT target, condition, remaining_rounds
    FROM play_campaign_encounter_conditions
    WHERE encounter_id = ?
    ORDER BY rowid ASC
  `).all(encounterId) as Array<{ target: string } & PlayCampaignEncounterCondition>;
  const conditions: Record<string, PlayCampaignEncounterCondition[]> = {};
  for (const { target, condition, remaining_rounds } of rows) {
    (conditions[target] ??= []).push({ condition, remaining_rounds });
  }
  return conditions;
}

export function readPlayCampaignEncounterStatus(
  campaignId: string,
  encounterId: string,
  actor: string,
): { result: "found"; status: PlayCampaignEncounterStatus } | { result: "not_found" | "forbidden" | "conflict" } {
  const turn = readPlayCampaignEncounterTurn(campaignId, encounterId, actor);
  if (turn.result !== "found") return turn;
  const order = encounterCombatOrder(encounterId);
  return {
    result: "found",
    status: {
      ...turn.turn,
      order: order.map(visibleEncounterCombatant),
      conditions: encounterConditions(encounterId),
    },
  };
}

/** Apply a named condition to a monster or party member in an active encounter. */
export function addPlayCampaignEncounterCondition(
  campaignId: string,
  encounterId: string,
  owner: string,
  target: string,
  condition: string,
  durationRounds: number,
): { result: "created"; conditions: PlayCampaignEncounterCondition[] } | { result: "not_found" | "forbidden" | "invalid" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };
  const encounter = database.prepare(
    "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ? AND status = 'active'",
  ).get(encounterId, campaignId);
  if (!encounter) return { result: "not_found" };
  if (!encounterCombatOrder(encounterId).some((combatant) => combatant.target === target)) return { result: "invalid" };

  database.prepare(`
    INSERT INTO play_campaign_encounter_conditions (encounter_id, target, condition, remaining_rounds)
    VALUES (?, ?, ?, ?)
  `).run(encounterId, target, condition, durationRounds);
  return { result: "created", conditions: encounterConditions(encounterId)[target] ?? [] };
}

/** Read an active encounter's combat turn as an owner or party member. */
export function readPlayCampaignEncounterTurn(
  campaignId: string,
  encounterId: string,
  actor: string,
): { result: "found"; turn: PlayCampaignEncounterTurn } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };

  const encounter = database.prepare(`
    SELECT round, turn_index AS turnIndex
    FROM play_campaign_encounters
    WHERE id = ? AND campaign_id = ? AND status = 'active'
  `).get(encounterId, campaignId) as { round: number; turnIndex: number } | undefined;
  if (!encounter) return { result: "not_found" };

  const order = encounterCombatOrder(encounterId);
  if (order.length === 0) return { result: "conflict" };
  const turnIndex = encounter.turnIndex % order.length;
  return {
    result: "found",
    turn: { round: encounter.round, turn_index: turnIndex, active: visibleEncounterCombatant(order[turnIndex]) },
  };
}

/** Advance only when called by the owner or the party member currently acting. */
export function advancePlayCampaignEncounterTurn(
  campaignId: string,
  encounterId: string,
  actor: string,
): { result: "advanced"; turn: PlayCampaignEncounterTurn } | { result: "not_found" | "forbidden" | "conflict" } {
  const current = readPlayCampaignEncounterTurn(campaignId, encounterId, actor);
  if (current.result !== "found") return current;

  const campaign = playCampaignOwner(campaignId)!;
  const order = encounterCombatOrder(encounterId);
  const active = order[current.turn.turn_index];
  if (campaign.owner !== actor && active.kind !== "player") return { result: "conflict" };
  if (campaign.owner !== actor && active.member !== actor) return { result: "conflict" };

  const nextIndex = (current.turn.turn_index + 1) % order.length;
  const nextRound = current.turn.round + (nextIndex === 0 ? 1 : 0);
  database.prepare(`
    UPDATE play_campaign_encounters SET round = ?, turn_index = ?
    WHERE id = ? AND campaign_id = ?
  `).run(nextRound, nextIndex, encounterId, campaignId);
  // All entries produced by encounterCombatOrder have an internal target id.
  const target = order[nextIndex].target!;
  database.prepare(`
    DELETE FROM play_campaign_encounter_conditions
    WHERE encounter_id = ? AND target = ? AND remaining_rounds <= 1
  `).run(encounterId, target);
  database.prepare(`
    UPDATE play_campaign_encounter_conditions
    SET remaining_rounds = remaining_rounds - 1
    WHERE encounter_id = ? AND target = ?
  `).run(encounterId, target);
  return {
    result: "advanced",
    turn: { round: nextRound, turn_index: nextIndex, active: visibleEncounterCombatant(order[nextIndex]) },
  };
}

/** Move the active combatant later in the encounter order without adding a turn. */
export function delayPlayCampaignEncounterTurn(
  campaignId: string,
  encounterId: string,
  actor: string,
  targetIndex: number,
): { result: "delayed"; order: Array<Omit<PlayCampaignEncounterTurnCombatant, "member" | "target">> } | { result: "not_found" | "forbidden" | "conflict" | "invalid" } {
  const current = readPlayCampaignEncounterTurn(campaignId, encounterId, actor);
  if (current.result !== "found") return current;

  const campaign = playCampaignOwner(campaignId)!;
  const order = encounterCombatOrder(encounterId);
  const currentCombatant = order[current.turn.turn_index];
  if (campaign.owner !== actor && (currentCombatant.kind !== "player" || currentCombatant.member !== actor)) return { result: "conflict" };
  if (targetIndex <= current.turn.turn_index || targetIndex >= order.length) return { result: "invalid" };

  const reordered = [...order];
  reordered.splice(current.turn.turn_index, 1);
  reordered.splice(targetIndex, 0, currentCombatant);
  database.prepare(`
    INSERT INTO play_campaign_encounter_turn_orders (encounter_id, order_json)
    VALUES (?, ?)
    ON CONFLICT(encounter_id) DO UPDATE SET order_json = excluded.order_json
  `).run(encounterId, JSON.stringify(reordered.map((combatant) => combatant.target)));
  // The same combatant remains current after moving to its delayed slot.
  // Keeping the old numeric cursor would make the combatant that filled the
  // vacated position act instead.
  database.prepare(`
    UPDATE play_campaign_encounters SET turn_index = ?
    WHERE id = ? AND campaign_id = ?
  `).run(targetIndex, encounterId, campaignId);
  return { result: "delayed", order: reordered.map(visibleEncounterCombatant) };
}

/** Record a player's held action while leaving the encounter cursor untouched. */
export function readyPlayCampaignEncounterAction(
  campaignId: string,
  encounterId: string,
  actor: string,
  trigger: string,
): { result: "created"; ready: { actor: string; trigger: string } } | { result: "not_found" | "forbidden" | "conflict" } {
  const current = readPlayCampaignEncounterTurn(campaignId, encounterId, actor);
  if (current.result !== "found") return current;
  const active = encounterCombatOrder(encounterId)[current.turn.turn_index];
  if (active.kind !== "player" || active.member !== actor) return { result: "conflict" };

  database.prepare(`
    INSERT INTO play_campaign_encounter_ready_actions (encounter_id, actor, trigger)
    VALUES (?, ?, ?)
  `).run(encounterId, actor, trigger);
  return { result: "created", ready: { actor, trigger } };
}

export function addPlayCampaignMember(campaignId: string, member: PlayCampaignMember): "created" | "not_found" | "conflict" {
  const campaign = database.prepare("SELECT status, max_players FROM play_campaigns WHERE id = ?")
    .get(campaignId) as Pick<PlayCampaign, "status" | "max_players"> | undefined;
  if (!campaign) return "not_found";

  const duplicate = database.prepare(`
    SELECT 1 FROM play_campaign_members
    WHERE campaign_id = ? AND (username = ? OR character_id = ?)
  `).get(campaignId, member.username, member.character_id);
  const count = database.prepare("SELECT COUNT(*) AS count FROM play_campaign_members WHERE campaign_id = ?")
    .get(campaignId) as { count: number };
  if (campaign.status !== "lobby" || duplicate || count.count >= campaign.max_players) return "conflict";

  try {
    database.prepare(`
      INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class)
      VALUES (?, ?, ?, ?, ?)
    `).run(campaignId, member.username, member.character_id, member.name, member.class);
    database.prepare(`
      INSERT INTO play_campaign_character_health (campaign_id, character_id)
      VALUES (?, ?)
    `).run(campaignId, member.character_id);
    database.prepare(`
      INSERT INTO play_campaign_character_owners (campaign_id, character_id, owner)
      VALUES (?, ?, ?)
    `).run(campaignId, member.character_id, member.username);
    database.prepare(`
      INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold)
      VALUES (?, ?, 10)
    `).run(campaignId, member.character_id);
    return "created";
  } catch {
    return "conflict";
  }
}

export function createPlayCampaignInvitation(
  campaignId: string,
  actor: string,
  invitation: Omit<PlayCampaignInvitation, "status">,
): { result: "created"; invitation: PlayCampaignInvitation } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const created: PlayCampaignInvitation = { ...invitation, status: "pending" };
  try {
    database.prepare(`
      INSERT INTO play_campaign_invitations (campaign_id, invitation_id, username, character_id, status)
      VALUES (?, ?, ?, ?, ?)
    `).run(campaignId, created.invitation_id, created.username, created.character_id, created.status);
    return { result: "created", invitation: created };
  } catch {
    return { result: "conflict" };
  }
}

export function acceptPlayCampaignInvitation(
  campaignId: string,
  invitationId: string,
  actor: string,
): { result: "accepted"; invitation: PlayCampaignInvitation } | { result: "not_found" | "forbidden" | "conflict" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  const invitation = database.prepare(`
    SELECT invitation_id, username, character_id, status
    FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?
  `).get(campaignId, invitationId) as PlayCampaignInvitation | undefined;
  if (!invitation) return { result: "not_found" };
  if (invitation.username !== actor) return { result: "forbidden" };
  if (invitation.status !== "pending") return { result: "conflict" };

  database.exec("BEGIN IMMEDIATE");
  try {
    const updated = database.prepare(`
      UPDATE play_campaign_invitations SET status = 'accepted'
      WHERE campaign_id = ? AND invitation_id = ? AND status = 'pending'
    `).run(campaignId, invitationId);
    if (updated.changes !== 1) {
      database.exec("ROLLBACK");
      return { result: "conflict" };
    }
    database.prepare(`
      INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class)
      VALUES (?, ?, ?, ?, ?)
    `).run(campaignId, actor, invitation.character_id, invitation.character_id, "Adventurer");
    database.prepare(`INSERT INTO play_campaign_character_health (campaign_id, character_id) VALUES (?, ?)`).run(campaignId, invitation.character_id);
    database.prepare(`INSERT INTO play_campaign_character_owners (campaign_id, character_id, owner) VALUES (?, ?, ?)`).run(campaignId, invitation.character_id, actor);
    database.prepare(`INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold) VALUES (?, ?, 10)`).run(campaignId, invitation.character_id);
    database.exec("COMMIT");
    return { result: "accepted", invitation: { ...invitation, status: "accepted" } };
  } catch {
    database.exec("ROLLBACK");
    return { result: "conflict" };
  }
}

export function readPlayCampaignInvitations(
  campaignId: string,
  actor: string,
): { result: "found"; invitations: PlayCampaignInvitation[] } | { result: "not_found" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  const invitations = database.prepare(`
    SELECT invitation_id, username, character_id, status
    FROM play_campaign_invitations
    WHERE campaign_id = ? AND (? = ? OR username = ?)
    ORDER BY rowid ASC
  `).all(campaignId, actor, campaign.owner, actor) as PlayCampaignInvitation[];
  return { result: "found", invitations };
}

const narrationPowers: ["narrate"] = ["narrate"];

export function grantPlayCampaignDelegation(
  campaignId: string,
  actor: string,
  username: string,
): { result: "created"; delegation: PlayCampaignDelegation } | { result: "not_found" | "forbidden" | "invalid" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  if (!isPlayCampaignMember(campaignId, username)) return { result: "invalid" };

  const existing = database.prepare(`
    SELECT username, powers_json, active FROM play_campaign_delegations
    WHERE campaign_id = ? AND username = ?
  `).get(campaignId, username) as { username: string; powers_json: string; active: number } | undefined;
  if (existing?.active === 1) return { result: "conflict" };

  if (existing) {
    database.prepare(`UPDATE play_campaign_delegations SET powers_json = ?, active = 1 WHERE campaign_id = ? AND username = ?`)
      .run(JSON.stringify(narrationPowers), campaignId, username);
  } else {
    database.prepare(`INSERT INTO play_campaign_delegations (campaign_id, username, powers_json, active) VALUES (?, ?, ?, 1)`)
      .run(campaignId, username, JSON.stringify(narrationPowers));
  }
  database.prepare(`INSERT INTO play_campaign_delegation_audit (campaign_id, username, action, powers_json) VALUES (?, ?, 'granted', ?)`)
    .run(campaignId, username, JSON.stringify(narrationPowers));
  return { result: "created", delegation: { username, powers: ["narrate"], active: true } };
}

export function revokePlayCampaignDelegation(
  campaignId: string,
  actor: string,
  username: string,
): { result: "revoked"; delegation: PlayCampaignDelegation } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const changed = database.prepare(`
    UPDATE play_campaign_delegations SET active = 0
    WHERE campaign_id = ? AND username = ? AND active = 1
  `).run(campaignId, username);
  if (changed.changes !== 1) return { result: "not_found" };
  database.prepare(`INSERT INTO play_campaign_delegation_audit (campaign_id, username, action, powers_json) VALUES (?, ?, 'revoked', ?)`)
    .run(campaignId, username, JSON.stringify(narrationPowers));
  return { result: "revoked", delegation: { username, powers: ["narrate"], active: false } };
}

export function readPlayCampaignDelegationAudit(
  campaignId: string,
  actor: string,
): { result: "found"; entries: PlayCampaignDelegationAuditEntry[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const entries = database.prepare(`
    SELECT username, action, powers_json FROM play_campaign_delegation_audit
    WHERE campaign_id = ? ORDER BY rowid ASC
  `).all(campaignId).map((row) => {
    const entry = row as { username: string; action: "granted" | "revoked"; powers_json: string };
    return { username: entry.username, action: entry.action, powers: JSON.parse(entry.powers_json) as ["narrate"] };
  });
  return { result: "found", entries };
}

export function readPlayCampaignCharacterOwner(
  campaignId: string,
  characterId: string,
  actor: string,
): { result: "found"; owner: PlayCampaignCharacterOwner } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (!isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };

  const owner = database.prepare(`
    SELECT character_id, owner
    FROM play_campaign_character_owners
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as PlayCampaignCharacterOwner | undefined;
  return owner ? { result: "found", owner } : { result: "not_found" };
}

export function claimPlayCampaignCharacter(
  campaignId: string,
  characterId: string,
  actor: string,
): { result: "claimed"; owner: PlayCampaignCharacterOwner } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (!isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };

  const character = database.prepare(`
    SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId);
  if (!character) return { result: "not_found" };

  const owner = database.prepare(`
    SELECT owner FROM play_campaign_character_owners
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as { owner: string } | undefined;
  if (owner) return { result: "conflict" };

  try {
    const claimed = { character_id: characterId, owner: actor };
    database.prepare(`
      INSERT INTO play_campaign_character_owners (campaign_id, character_id, owner)
      VALUES (?, ?, ?)
    `).run(campaignId, claimed.character_id, claimed.owner);
    return { result: "claimed", owner: claimed };
  } catch {
    return { result: "conflict" };
  }
}

export function transferPlayCampaignCharacter(
  campaignId: string,
  characterId: string,
  actor: string,
  newOwner: string,
): { result: "transferred"; owner: PlayCampaignCharacterOwner } | { result: "not_found" | "forbidden" | "invalid" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };

  const owner = database.prepare(`
    SELECT owner FROM play_campaign_character_owners
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as { owner: string } | undefined;
  if (!owner) return { result: "not_found" };
  if (owner.owner !== actor) return { result: "forbidden" };
  if (!isPlayCampaignMember(campaignId, newOwner)) return { result: "invalid" };

  database.prepare(`
    UPDATE play_campaign_character_owners SET owner = ?
    WHERE campaign_id = ? AND character_id = ?
  `).run(newOwner, campaignId, characterId);
  return { result: "transferred", owner: { character_id: characterId, owner: newOwner } };
}

export function readPlayCampaignCharacterCurrency(
  campaignId: string,
  characterId: string,
  actor: string,
): { result: "found"; currency: PlayCampaignCharacterCurrency } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (!isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const currency = database.prepare(`
    SELECT character_id, gold
    FROM play_campaign_character_currency
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as PlayCampaignCharacterCurrency | undefined;
  return currency ? { result: "found", currency } : { result: "not_found" };
}

export function transferPlayCampaignCharacterCurrency(
  campaignId: string,
  fromCharacterId: string,
  actor: string,
  toCharacterId: string,
  gold: number,
): { result: "transferred"; transfer: PlayCampaignCurrencyTransfer } | { result: "not_found" | "forbidden" | "invalid" | "insufficient" } {
  const source = ownedPlayCampaignCharacter(campaignId, fromCharacterId, actor);
  if (source !== "found") return { result: source };
  if (toCharacterId === fromCharacterId || gold <= 0) return { result: "invalid" };

  const destination = database.prepare(`
    SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, toCharacterId);
  if (!destination) return { result: "invalid" };

  database.exec("BEGIN IMMEDIATE");
  try {
    const sourceCurrency = database.prepare(`
      SELECT gold FROM play_campaign_character_currency
      WHERE campaign_id = ? AND character_id = ?
    `).get(campaignId, fromCharacterId) as { gold: number } | undefined;
    const destinationCurrency = database.prepare(`
      SELECT gold FROM play_campaign_character_currency
      WHERE campaign_id = ? AND character_id = ?
    `).get(campaignId, toCharacterId) as { gold: number } | undefined;
    if (!sourceCurrency || !destinationCurrency) {
      database.exec("ROLLBACK");
      return { result: "not_found" };
    }
    if (sourceCurrency.gold < gold) {
      database.exec("ROLLBACK");
      return { result: "insufficient" };
    }
    const transferId = (database.prepare(`
      SELECT COALESCE(MAX(transfer_id), 0) + 1 AS transfer_id
      FROM play_campaign_currency_transfers WHERE campaign_id = ?
    `).get(campaignId) as { transfer_id: number }).transfer_id;
    const transfer: PlayCampaignCurrencyTransfer = {
      from_character_id: fromCharacterId,
      to_character_id: toCharacterId,
      gold,
      from_gold: sourceCurrency.gold - gold,
      to_gold: destinationCurrency.gold + gold,
      transfer_id: transferId,
    };
    database.prepare(`
      UPDATE play_campaign_character_currency SET gold = ?
      WHERE campaign_id = ? AND character_id = ?
    `).run(transfer.from_gold, campaignId, fromCharacterId);
    database.prepare(`
      UPDATE play_campaign_character_currency SET gold = ?
      WHERE campaign_id = ? AND character_id = ?
    `).run(transfer.to_gold, campaignId, toCharacterId);
    database.prepare(`
      INSERT INTO play_campaign_currency_transfers
        (campaign_id, transfer_id, from_character_id, to_character_id, gold)
      VALUES (?, ?, ?, ?, ?)
    `).run(campaignId, transfer.transfer_id, fromCharacterId, toCharacterId, gold);
    database.exec("COMMIT");
    return { result: "transferred", transfer };
  } catch (error) {
    database.exec("ROLLBACK");
    throw error;
  }
}

/**
 * Commits both currency balances and the public transfer ledger as one SQLite
 * transaction.  The simulated-failure path deliberately rolls the prepared
 * transaction back before exposing its error to the route handler.
 */
export function createPlayCampaignTransactionalTransfer(
  campaignId: string,
  actor: string,
  input: Pick<PlayCampaignTransactionalTransfer, "from_character_id" | "to_character_id" | "amount"> & { simulate_failure: boolean },
): { result: "created"; transfer: PlayCampaignTransactionalTransfer } | { result: "not_found" | "forbidden" | "invalid" | "insufficient" | "simulated_failure" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (!isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  if (input.from_character_id === input.to_character_id || input.amount <= 0) return { result: "invalid" };

  const sourceOwner = database.prepare(`
    SELECT owner FROM play_campaign_character_owners
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, input.from_character_id) as { owner: string } | undefined;
  const destination = database.prepare(`
    SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, input.to_character_id);
  if (!sourceOwner || !destination) return { result: "invalid" };
  if (sourceOwner.owner !== actor) return { result: "forbidden" };

  database.exec("BEGIN IMMEDIATE");
  try {
    const source = database.prepare(`
      SELECT gold FROM play_campaign_character_currency
      WHERE campaign_id = ? AND character_id = ?
    `).get(campaignId, input.from_character_id) as { gold: number } | undefined;
    const destinationCurrency = database.prepare(`
      SELECT gold FROM play_campaign_character_currency
      WHERE campaign_id = ? AND character_id = ?
    `).get(campaignId, input.to_character_id) as { gold: number } | undefined;
    if (!source || !destinationCurrency) {
      database.exec("ROLLBACK");
      return { result: "invalid" };
    }
    if (source.gold < input.amount) {
      database.exec("ROLLBACK");
      return { result: "insufficient" };
    }

    const transfer: PlayCampaignTransactionalTransfer = {
      from_character_id: input.from_character_id,
      to_character_id: input.to_character_id,
      amount: input.amount,
      from_gold: source.gold - input.amount,
      to_gold: destinationCurrency.gold + input.amount,
      sequence: (database.prepare(`
        SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence
        FROM play_campaign_transactional_transfers WHERE campaign_id = ?
      `).get(campaignId) as { sequence: number }).sequence,
    };
    if (input.simulate_failure) {
      database.exec("ROLLBACK");
      return { result: "simulated_failure" };
    }

    database.prepare(`UPDATE play_campaign_character_currency SET gold = ?
      WHERE campaign_id = ? AND character_id = ?`).run(transfer.from_gold, campaignId, input.from_character_id);
    database.prepare(`UPDATE play_campaign_character_currency SET gold = ?
      WHERE campaign_id = ? AND character_id = ?`).run(transfer.to_gold, campaignId, input.to_character_id);
    database.prepare(`
      INSERT INTO play_campaign_transactional_transfers
        (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).run(campaignId, transfer.sequence, transfer.from_character_id, transfer.to_character_id,
      transfer.amount, transfer.from_gold, transfer.to_gold);
    database.exec("COMMIT");
    return { result: "created", transfer };
  } catch {
    try { database.exec("ROLLBACK"); } catch { /* transaction already closed */ }
    throw new Error("transactional transfer failed");
  }
}

export function readPlayCampaignTransactionalTransfers(
  campaignId: string,
  actor: string,
): { result: "found"; transfers: PlayCampaignTransactionalTransfer[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const transfers = database.prepare(`
    SELECT from_character_id, to_character_id, amount, from_gold, to_gold, sequence
    FROM play_campaign_transactional_transfers
    WHERE campaign_id = ? ORDER BY sequence ASC
  `).all(campaignId) as PlayCampaignTransactionalTransfer[];
  return { result: "found", transfers };
}

const PLAY_CAMPAIGN_INVENTORY_ITEM_IDS = new Set([
  "healing-potion",
  "torch",
  "leather-armor",
  "ring-of-protection",
  "amulet-of-health",
]);
const PLAY_CAMPAIGN_CONSUMABLE_ITEM_IDS = new Set(["healing-potion"]);

const PLAY_CAMPAIGN_EQUIPMENT_SLOTS = new Set(["armor", "accessory"]);
const PLAY_CAMPAIGN_EQUIPMENT_ITEM_SLOTS: Record<string, "armor" | "accessory"> = {
  "leather-armor": "armor",
  "ring-of-protection": "accessory",
  "amulet-of-health": "accessory",
};
const PLAY_CAMPAIGN_ATTUNABLE_ITEM_IDS = new Set(["ring-of-protection", "amulet-of-health"]);

export function isPlayCampaignInventoryItemId(itemId: string): boolean {
  return PLAY_CAMPAIGN_INVENTORY_ITEM_IDS.has(itemId);
}

type PlayCampaignRecipeRow = Omit<PlayCampaignRecipe, "ingredients"> & { ingredients_json: string };

function recipeFromRow(row: PlayCampaignRecipeRow): PlayCampaignRecipe {
  return {
    recipe_id: row.recipe_id,
    name: row.name,
    ingredients: JSON.parse(row.ingredients_json) as Record<string, number>,
    output_item: row.output_item,
    output_quantity: row.output_quantity,
  };
}

export function createPlayCampaignRecipe(
  campaignId: string,
  actor: string,
  recipe: PlayCampaignRecipe,
): { result: "created"; recipe: PlayCampaignRecipe } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  try {
    database.prepare(`
      INSERT INTO play_campaign_recipes
        (campaign_id, recipe_id, name, ingredients_json, output_item, output_quantity)
      VALUES (?, ?, ?, ?, ?, ?)
    `).run(campaignId, recipe.recipe_id, recipe.name, JSON.stringify(recipe.ingredients), recipe.output_item, recipe.output_quantity);
    return { result: "created", recipe };
  } catch {
    return { result: "conflict" };
  }
}

export function readPlayCampaignRecipes(
  campaignId: string,
  actor: string,
): { result: "found"; recipes: PlayCampaignRecipe[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const rows = database.prepare(`
    SELECT recipe_id, name, ingredients_json, output_item, output_quantity
    FROM play_campaign_recipes
    WHERE campaign_id = ?
    ORDER BY rowid ASC
  `).all(campaignId) as PlayCampaignRecipeRow[];
  return { result: "found", recipes: rows.map(recipeFromRow) };
}

export function createPlayCampaignDowntimeActivity(
  campaignId: string,
  actor: string,
  activity: PlayCampaignDowntimeActivity,
): { result: "created"; activity: PlayCampaignDowntimeActivity } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  try {
    database.prepare(`
      INSERT INTO play_campaign_downtime_activities (campaign_id, activity_id, name, cycles_required)
      VALUES (?, ?, ?, ?)
    `).run(campaignId, activity.activity_id, activity.name, activity.cycles_required);
    return { result: "created", activity };
  } catch {
    return { result: "conflict" };
  }
}

function downtimeActivity(campaignId: string, activityId: string): PlayCampaignDowntimeActivity | undefined {
  return database.prepare(`
    SELECT activity_id, name, cycles_required
    FROM play_campaign_downtime_activities
    WHERE campaign_id = ? AND activity_id = ?
  `).get(campaignId, activityId) as PlayCampaignDowntimeActivity | undefined;
}

export function createPlayCampaignDowntimeAllocation(
  campaignId: string,
  characterId: string,
  activityId: string,
  actor: string,
): { result: "created"; allocation: PlayCampaignDowntimeAllocation } | { result: "not_found" | "forbidden" | "conflict" } {
  const ownership = ownedPlayCampaignCharacter(campaignId, characterId, actor);
  if (ownership !== "found") return { result: ownership };
  if (!downtimeActivity(campaignId, activityId)) return { result: "not_found" };
  const allocation: PlayCampaignDowntimeAllocation = {
    character_id: characterId, activity_id: activityId, cycles_completed: 0, completions: 0,
  };
  try {
    database.prepare(`
      INSERT INTO play_campaign_downtime_allocations
        (campaign_id, character_id, activity_id, cycles_completed, completions)
      VALUES (?, ?, ?, 0, 0)
    `).run(campaignId, characterId, activityId);
    return { result: "created", allocation };
  } catch {
    return { result: "conflict" };
  }
}

export function progressPlayCampaignDowntimeAllocation(
  campaignId: string,
  characterId: string,
  activityId: string,
  actor: string,
): { result: "progressed"; allocation: PlayCampaignDowntimeAllocation } | { result: "not_found" | "forbidden" } {
  const ownership = ownedPlayCampaignCharacter(campaignId, characterId, actor);
  if (ownership !== "found") return { result: ownership };
  const activity = downtimeActivity(campaignId, activityId);
  if (!activity) return { result: "not_found" };
  const allocation = database.prepare(`
    SELECT character_id, activity_id, cycles_completed, completions
    FROM play_campaign_downtime_allocations
    WHERE campaign_id = ? AND character_id = ? AND activity_id = ?
  `).get(campaignId, characterId, activityId) as PlayCampaignDowntimeAllocation | undefined;
  if (!allocation) return { result: "not_found" };
  const completes = allocation.cycles_completed + 1 === activity.cycles_required;
  const updated: PlayCampaignDowntimeAllocation = {
    ...allocation,
    cycles_completed: completes ? 0 : allocation.cycles_completed + 1,
    completions: completes ? allocation.completions + 1 : allocation.completions,
  };
  database.prepare(`
    UPDATE play_campaign_downtime_allocations
    SET cycles_completed = ?, completions = ?
    WHERE campaign_id = ? AND character_id = ? AND activity_id = ?
  `).run(updated.cycles_completed, updated.completions, campaignId, characterId, activityId);
  return { result: "progressed", allocation: updated };
}

export function readPlayCampaignDowntimeAllocation(
  campaignId: string,
  characterId: string,
  activityId: string,
  actor: string,
): { result: "found"; allocation: PlayCampaignDowntimeAllocation } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  if (!database.prepare("SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?").get(campaignId, characterId)) {
    return { result: "not_found" };
  }
  if (!downtimeActivity(campaignId, activityId)) return { result: "not_found" };
  const allocation = database.prepare(`
    SELECT character_id, activity_id, cycles_completed, completions
    FROM play_campaign_downtime_allocations
    WHERE campaign_id = ? AND character_id = ? AND activity_id = ?
  `).get(campaignId, characterId, activityId) as PlayCampaignDowntimeAllocation | undefined;
  return allocation ? { result: "found", allocation } : { result: "not_found" };
}

export function craftPlayCampaignRecipe(
  campaignId: string,
  recipeId: string,
  characterId: string,
  actor: string,
): { result: "crafted"; craft: Pick<PlayCampaignRecipe, "recipe_id" | "output_item" | "output_quantity"> & { character_id: string } } | { result: "not_found" | "forbidden" | "insufficient" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner === actor) return { result: "forbidden" };
  const owner = database.prepare(`
    SELECT owner FROM play_campaign_character_owners
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as { owner: string } | undefined;
  if (!owner) return { result: "not_found" };
  if (owner.owner !== actor) return { result: "forbidden" };
  const row = database.prepare(`
    SELECT recipe_id, name, ingredients_json, output_item, output_quantity
    FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?
  `).get(campaignId, recipeId) as PlayCampaignRecipeRow | undefined;
  if (!row) return { result: "not_found" };
  const recipe = recipeFromRow(row);

  database.exec("BEGIN");
  try {
    for (const [itemId, quantity] of Object.entries(recipe.ingredients)) {
      const held = database.prepare(`
        SELECT quantity FROM play_campaign_character_inventory_items
        WHERE campaign_id = ? AND character_id = ? AND item_id = ?
      `).get(campaignId, characterId, itemId) as { quantity: number } | undefined;
      if (!held || held.quantity < quantity) {
        database.exec("ROLLBACK");
        return { result: "insufficient" };
      }
    }
    for (const [itemId, quantity] of Object.entries(recipe.ingredients)) {
      database.prepare(`
        UPDATE play_campaign_character_inventory_items SET quantity = quantity - ?
        WHERE campaign_id = ? AND character_id = ? AND item_id = ?
      `).run(quantity, campaignId, characterId, itemId);
      database.prepare(`
        DELETE FROM play_campaign_character_inventory_items
        WHERE campaign_id = ? AND character_id = ? AND item_id = ? AND quantity = 0
      `).run(campaignId, characterId, itemId);
    }
    database.prepare(`
      INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity)
      VALUES (?, ?, ?, ?)
      ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity
    `).run(campaignId, characterId, recipe.output_item, recipe.output_quantity);
    database.exec("COMMIT");
    return {
      result: "crafted",
      craft: {
        character_id: characterId,
        recipe_id: recipe.recipe_id,
        output_item: recipe.output_item,
        output_quantity: recipe.output_quantity,
      },
    };
  } catch (error) {
    database.exec("ROLLBACK");
    throw error;
  }
}

export function createPlayCampaignLoot(
  campaignId: string,
  actor: string,
  loot: Pick<PlayCampaignLoot, "loot_id" | "item_id" | "quantity">,
): { result: "created"; loot: Pick<PlayCampaignLoot, "loot_id" | "item_id" | "quantity" | "status"> } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  try {
    const created = { ...loot, status: "open" as const };
    database.prepare(`
      INSERT INTO play_campaign_loot (campaign_id, loot_id, item_id, quantity, status)
      VALUES (?, ?, ?, ?, ?)
    `).run(campaignId, created.loot_id, created.item_id, created.quantity, created.status);
    return { result: "created", loot: created };
  } catch {
    return { result: "conflict" };
  }
}

export function createPlayCampaignNpc(
  campaignId: string,
  actor: string,
  npc: PlayCampaignNpc,
): { result: "created"; npc: PlayCampaignNpc } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  try {
    database.prepare(`
      INSERT INTO play_campaign_npcs (campaign_id, npc_id, name, agenda, public_status)
      VALUES (?, ?, ?, ?, ?)
    `).run(campaignId, npc.npc_id, npc.name, npc.agenda, npc.public_status);
    return { result: "created", npc };
  } catch {
    return { result: "conflict" };
  }
}

function isPlayCampaignEntity(campaignId: string, entityId: string): boolean {
  return Boolean(database.prepare(`
    SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?
    UNION ALL
    SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?
    LIMIT 1
  `).get(campaignId, entityId, campaignId, entityId));
}

export function createPlayCampaignRelationship(
  campaignId: string,
  actor: string,
  relationship: PlayCampaignRelationship,
): { result: "created"; edge: PlayCampaignRelationship } | { result: "not_found" | "forbidden" | "invalid" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  if (relationship.source_id === relationship.target_id) return { result: "invalid" };
  if (!isPlayCampaignEntity(campaignId, relationship.source_id) || !isPlayCampaignEntity(campaignId, relationship.target_id)) {
    return { result: "not_found" };
  }
  try {
    database.prepare(`
      INSERT INTO play_campaign_relationships (campaign_id, source_id, target_id, kind, score)
      VALUES (?, ?, ?, ?, ?)
    `).run(campaignId, relationship.source_id, relationship.target_id, relationship.kind, relationship.score);
    return { result: "created", edge: relationship };
  } catch {
    return { result: "conflict" };
  }
}

export function updatePlayCampaignRelationship(
  campaignId: string,
  actor: string,
  sourceId: string,
  targetId: string,
  kind: string,
  score: number,
): { result: "updated"; edge: PlayCampaignRelationship } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const update = database.prepare(`
    UPDATE play_campaign_relationships SET score = ?
    WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?
  `).run(score, campaignId, sourceId, targetId, kind);
  if (update.changes !== 1) return { result: "not_found" };
  return { result: "updated", edge: { source_id: sourceId, target_id: targetId, kind, score } };
}

export function readPlayCampaignRelationships(
  campaignId: string,
  actor: string,
): { result: "found"; edges: PlayCampaignRelationship[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const edges = database.prepare(`
    SELECT source_id, target_id, kind, score
    FROM play_campaign_relationships
    WHERE campaign_id = ?
    ORDER BY rowid ASC
  `).all(campaignId) as PlayCampaignRelationship[];
  return { result: "found", edges };
}

export function createPlayCampaignClue(
  campaignId: string,
  actor: string,
  clue: PlayCampaignClue,
): { result: "created"; clue: PlayCampaignClue } | { result: "not_found" | "forbidden" | "invalid" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  if (clue.audience === "character" && !isPlayCampaignMemberCharacter(campaignId, clue.character_id)) {
    return { result: "invalid" };
  }
  try {
    database.prepare(`
      INSERT INTO play_campaign_clues (campaign_id, clue_id, text, audience, character_id)
      VALUES (?, ?, ?, ?, ?)
    `).run(campaignId, clue.clue_id, clue.text, clue.audience, clue.character_id ?? null);
    return { result: "created", clue };
  } catch {
    return { result: "conflict" };
  }
}

function isPlayCampaignMemberCharacter(campaignId: string, characterId: string | undefined): boolean {
  return typeof characterId === "string" && Boolean(database.prepare(`
    SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId));
}

export function readPlayCampaignClues(
  campaignId: string,
  actor: string,
): { result: "found"; clues: PlayCampaignClue[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner === actor) {
    const clues = database.prepare(`
      SELECT clue_id, text, audience, character_id
      FROM play_campaign_clues WHERE campaign_id = ? ORDER BY rowid ASC
    `).all(campaignId).map(clueFromRow);
    return { result: "found", clues };
  }
  const member = database.prepare(`
    SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?
  `).get(campaignId, actor) as { character_id: string } | undefined;
  if (!member) return { result: "forbidden" };
  const clues = database.prepare(`
    SELECT clue_id, text, audience, character_id
    FROM play_campaign_clues
    WHERE campaign_id = ? AND (audience = 'party' OR (audience = 'character' AND character_id = ?))
    ORDER BY rowid ASC
  `).all(campaignId, member.character_id).map(clueFromRow);
  return { result: "found", clues };
}

function contentFromRow(row: unknown): PlayCampaignContent {
  const content = row as { content_id: string; kind: string; text: string; tags_json: string };
  return {
    content_id: content.content_id,
    kind: content.kind,
    text: content.text,
    tags: JSON.parse(content.tags_json) as string[],
  };
}

export function createPlayCampaignContent(
  campaignId: string,
  actor: string,
  content: PlayCampaignContent,
): { result: "created"; content: PlayCampaignContent } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  try {
    database.prepare(`
      INSERT INTO play_campaign_content (campaign_id, content_id, kind, text, tags_json)
      VALUES (?, ?, ?, ?, ?)
    `).run(campaignId, content.content_id, content.kind, content.text, JSON.stringify(content.tags));
    return { result: "created", content };
  } catch {
    return { result: "conflict" };
  }
}

export function replacePlayCampaignContentTags(
  campaignId: string,
  contentId: string,
  actor: string,
  tags: string[],
): { result: "updated"; content: PlayCampaignContent } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const update = database.prepare(`
    UPDATE play_campaign_content SET tags_json = ?
    WHERE campaign_id = ? AND content_id = ?
  `).run(JSON.stringify(tags), campaignId, contentId);
  if (update.changes !== 1) return { result: "not_found" };
  const content = database.prepare(`
    SELECT content_id, kind, text, tags_json
    FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?
  `).get(campaignId, contentId);
  return { result: "updated", content: contentFromRow(content) };
}

export function readPlayCampaignContent(
  campaignId: string,
  actor: string,
  excludeTag?: string,
): { result: "found"; content: PlayCampaignContent[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  const isOwner = campaign.owner === actor;
  if (!isOwner && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const content = database.prepare(`
    SELECT content_id, kind, text, tags_json
    FROM play_campaign_content WHERE campaign_id = ? ORDER BY rowid ASC
  `).all(campaignId).map(contentFromRow);
  return {
    result: "found",
    content: !isOwner && excludeTag ? content.filter((entry) => !entry.tags.includes(excludeTag)) : content,
  };
}

function clueFromRow(row: unknown): PlayCampaignClue {
  const clue = row as { clue_id: string; text: string; audience: PlayCampaignClue["audience"]; character_id: string | null };
  return clue.audience === "character"
    ? { clue_id: clue.clue_id, text: clue.text, audience: clue.audience, character_id: clue.character_id! }
    : { clue_id: clue.clue_id, text: clue.text, audience: clue.audience };
}

export function createPlayCampaignQuest(
  campaignId: string,
  actor: string,
  quest: Pick<PlayCampaignQuest, "quest_id" | "title" | "depends_on">,
): { result: "created"; quest: PlayCampaignQuest } | { result: "not_found" | "forbidden" | "invalid" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  if (quest.depends_on.includes(quest.quest_id) || quest.depends_on.some((dependency) => !playCampaignQuestExists(campaignId, dependency))) {
    return { result: "invalid" };
  }
  const created: PlayCampaignQuest = { ...quest, state: "locked" };
  try {
    database.prepare(`
      INSERT INTO play_campaign_quests (campaign_id, quest_id, title, depends_on_json, state)
      VALUES (?, ?, ?, ?, ?)
    `).run(campaignId, created.quest_id, created.title, JSON.stringify(created.depends_on), created.state);
    return { result: "created", quest: created };
  } catch {
    return { result: "conflict" };
  }
}

export function updatePlayCampaignQuestState(
  campaignId: string,
  questId: string,
  actor: string,
  state: "active" | "completed",
): { result: "updated"; quest: PlayCampaignQuest } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const quest = database.prepare(`
    SELECT quest_id, title, depends_on_json, state, rewards_xp, rewards_items_json FROM play_campaign_quests
    WHERE campaign_id = ? AND quest_id = ?
  `).get(campaignId, questId) as QuestRow | undefined;
  if (!quest) return { result: "not_found" };
  const current = questFromRow(quest);
  const mayActivate = current.state === "locked" && state === "active" && current.depends_on.every((dependency) => playCampaignQuestCompleted(campaignId, dependency));
  const mayComplete = current.state === "active" && state === "completed";
  if (!mayActivate && !mayComplete) return { result: "conflict" };
  const updated = { ...current, state } as PlayCampaignQuest;
  database.prepare(`UPDATE play_campaign_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?`)
    .run(updated.state, campaignId, questId);
  return { result: "updated", quest: updated };
}

export function readPlayCampaignQuests(
  campaignId: string,
  actor: string,
): { result: "found"; quests: PlayCampaignQuest[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const quests = database.prepare(`
    SELECT quest_id, title, depends_on_json, state, rewards_xp, rewards_items_json FROM play_campaign_quests
    WHERE campaign_id = ? ORDER BY rowid ASC
  `).all(campaignId).map(questFromRow);
  return { result: "found", quests };
}

type QuestRow = {
  quest_id: string;
  title: string;
  depends_on_json: string;
  state: PlayCampaignQuest["state"];
  rewards_xp?: number | null;
  rewards_items_json?: string | null;
};

function questFromRow(row: unknown): PlayCampaignQuest {
  const quest = row as QuestRow;
  const base = { quest_id: quest.quest_id, title: quest.title, depends_on: JSON.parse(quest.depends_on_json) as string[], state: quest.state };
  if (quest.rewards_xp === null || quest.rewards_xp === undefined || !quest.rewards_items_json) return base;
  return { ...base, rewards: { xp: quest.rewards_xp, items: JSON.parse(quest.rewards_items_json) as Record<string, number> } };
}

export function configurePlayCampaignQuestRewards(
  campaignId: string,
  questId: string,
  actor: string,
  rewards: PlayCampaignQuestRewards,
): { result: "updated"; quest: PlayCampaignQuest } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const row = database.prepare(`
    SELECT quest_id, title, depends_on_json, state FROM play_campaign_quests
    WHERE campaign_id = ? AND quest_id = ?
  `).get(campaignId, questId) as QuestRow | undefined;
  if (!row) return { result: "not_found" };
  const quest = questFromRow(row);
  if (quest.state === "completed") return { result: "conflict" };
  database.prepare(`
    UPDATE play_campaign_quests SET rewards_xp = ?, rewards_items_json = ?
    WHERE campaign_id = ? AND quest_id = ?
  `).run(rewards.xp, JSON.stringify(rewards.items), campaignId, questId);
  return { result: "updated", quest: { ...quest, rewards } };
}

export function awardPlayCampaignQuestRewards(
  campaignId: string,
  questId: string,
  actor: string,
): { result: "awarded"; rewards: PlayCampaignQuestRewards } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  database.exec("BEGIN IMMEDIATE");
  try {
    const quest = database.prepare(`
      SELECT state, rewards_xp, rewards_items_json, rewards_awarded
      FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?
    `).get(campaignId, questId) as { state: PlayCampaignQuest["state"]; rewards_xp: number | null; rewards_items_json: string | null; rewards_awarded: number } | undefined;
    if (!quest) { database.exec("ROLLBACK"); return { result: "not_found" }; }
    if (quest.state !== "completed" || quest.rewards_xp === null || !quest.rewards_items_json || quest.rewards_awarded) {
      database.exec("ROLLBACK"); return { result: "conflict" };
    }
    const rewards = { xp: quest.rewards_xp, items: JSON.parse(quest.rewards_items_json) as Record<string, number> };
    const members = database.prepare(`SELECT character_id FROM play_campaign_members WHERE campaign_id = ?`).all(campaignId) as Array<{ character_id: string }>;
    const grant = database.prepare(`
      INSERT INTO play_campaign_quest_reward_grants (campaign_id, quest_id, character_id, xp, items_json)
      VALUES (?, ?, ?, ?, ?)
    `);
    for (const member of members) grant.run(campaignId, questId, member.character_id, rewards.xp, JSON.stringify(rewards.items));
    database.prepare(`UPDATE play_campaign_quests SET rewards_awarded = 1 WHERE campaign_id = ? AND quest_id = ?`)
      .run(campaignId, questId);
    database.exec("COMMIT");
    return { result: "awarded", rewards };
  } catch (error) {
    database.exec("ROLLBACK");
    throw error;
  }
}

export function readPlayCampaignCharacterQuestRewards(
  campaignId: string,
  characterId: string,
  actor: string,
): { result: "found"; rewards: PlayCampaignCharacterQuestRewards } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  if (!isPlayCampaignMemberCharacter(campaignId, characterId)) return { result: "not_found" };
  const grants = database.prepare(`
    SELECT xp, items_json FROM play_campaign_quest_reward_grants
    WHERE campaign_id = ? AND character_id = ? ORDER BY rowid ASC
  `).all(campaignId, characterId) as Array<{ xp: number; items_json: string }>;
  const rewards: PlayCampaignCharacterQuestRewards = { character_id: characterId, xp: 0, items: {} };
  for (const grant of grants) {
    rewards.xp += grant.xp;
    for (const [itemId, quantity] of Object.entries(JSON.parse(grant.items_json) as Record<string, number>)) {
      rewards.items[itemId] = (rewards.items[itemId] ?? 0) + quantity;
    }
  }
  return { result: "found", rewards };
}

function playCampaignQuestExists(campaignId: string, questId: string): boolean {
  return Boolean(database.prepare(`SELECT 1 FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?`).get(campaignId, questId));
}

function playCampaignQuestCompleted(campaignId: string, questId: string): boolean {
  return Boolean(database.prepare(`
    SELECT 1 FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ? AND state = 'completed'
  `).get(campaignId, questId));
}

export function createPlayCampaignFaction(
  campaignId: string,
  actor: string,
  faction: PlayCampaignFaction,
): { result: "created"; faction: PlayCampaignFaction } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  try {
    database.prepare(`
      INSERT INTO play_campaign_factions (campaign_id, faction_id, name)
      VALUES (?, ?, ?)
    `).run(campaignId, faction.faction_id, faction.name);
    return { result: "created", faction };
  } catch {
    return { result: "conflict" };
  }
}

export function changePlayCampaignFactionReputation(
  campaignId: string,
  factionId: string,
  actor: string,
  change: Pick<PlayCampaignFactionReputation, "character_id" | "delta" | "reason">,
): { result: "created"; entry: PlayCampaignFactionReputation } | { result: "not_found" | "forbidden" | "invalid" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  if (!database.prepare(`SELECT 1 FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?`)
    .get(campaignId, factionId)) return { result: "not_found" };
  if (!database.prepare(`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?`)
    .get(campaignId, change.character_id)) return { result: "invalid" };

  const previous = database.prepare(`
    SELECT reputation FROM play_campaign_faction_reputation_history
    WHERE campaign_id = ? AND faction_id = ? AND character_id = ?
    ORDER BY rowid DESC LIMIT 1
  `).get(campaignId, factionId, change.character_id) as Pick<PlayCampaignFactionReputation, "reputation"> | undefined;
  const entry: PlayCampaignFactionReputation = {
    faction_id: factionId,
    character_id: change.character_id,
    reputation: Math.max(-100, Math.min(100, (previous?.reputation ?? 0) + change.delta)),
    delta: change.delta,
    reason: change.reason,
  };
  database.prepare(`
    INSERT INTO play_campaign_faction_reputation_history
      (campaign_id, faction_id, character_id, reputation, delta, reason)
    VALUES (?, ?, ?, ?, ?, ?)
  `).run(campaignId, entry.faction_id, entry.character_id, entry.reputation, entry.delta, entry.reason);
  return { result: "created", entry };
}

export function readPlayCampaignFactionReputation(
  campaignId: string,
  factionId: string,
  actor: string,
): { result: "found"; entries: PlayCampaignFactionReputation[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  const member = database.prepare(`
    SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?
  `).get(campaignId, actor) as Pick<PlayCampaignMember, "character_id"> | undefined;
  if (campaign.owner !== actor && !member) return { result: "forbidden" };
  if (!database.prepare(`SELECT 1 FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?`)
    .get(campaignId, factionId)) return { result: "not_found" };
  const entries = database.prepare(`
    SELECT faction_id, character_id, reputation, delta, reason
    FROM play_campaign_faction_reputation_history
    WHERE campaign_id = ? AND faction_id = ?${campaign.owner === actor ? "" : " AND character_id = ?"}
    ORDER BY rowid ASC
  `).all(...(campaign.owner === actor ? [campaignId, factionId] : [campaignId, factionId, member!.character_id])) as PlayCampaignFactionReputation[];
  return { result: "found", entries };
}

export function updatePlayCampaignNpcAgenda(
  campaignId: string,
  npcId: string,
  actor: string,
  update: Pick<PlayCampaignNpc, "agenda" | "public_status">,
): { result: "updated"; npc: PlayCampaignNpc } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const npc = database.prepare(`
    SELECT npc_id, name FROM play_campaign_npcs
    WHERE campaign_id = ? AND npc_id = ?
  `).get(campaignId, npcId) as Pick<PlayCampaignNpc, "npc_id" | "name"> | undefined;
  if (!npc) return { result: "not_found" };
  database.prepare(`
    UPDATE play_campaign_npcs SET agenda = ?, public_status = ?
    WHERE campaign_id = ? AND npc_id = ?
  `).run(update.agenda, update.public_status, campaignId, npcId);
  return { result: "updated", npc: { ...npc, ...update } };
}

export function readPlayCampaignNpc(
  campaignId: string,
  npcId: string,
  actor: string,
): { result: "found"; npc: PlayCampaignNpc; is_owner: boolean } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  const isOwner = campaign.owner === actor;
  if (!isOwner && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const npc = database.prepare(`
    SELECT npc_id, name, agenda, public_status FROM play_campaign_npcs
    WHERE campaign_id = ? AND npc_id = ?
  `).get(campaignId, npcId) as PlayCampaignNpc | undefined;
  return npc ? { result: "found", npc, is_owner: isOwner } : { result: "not_found" };
}

export function createPlayCampaignNpcDialogue(
  campaignId: string,
  npcId: string,
  actor: string,
  dialogue: PlayCampaignNpcDialogue,
): { result: "created"; dialogue: PlayCampaignNpcDialogue } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  if (!database.prepare(`SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?`)
    .get(campaignId, npcId)) return { result: "not_found" };
  try {
    database.prepare(`
      INSERT INTO play_campaign_npc_dialogue
        (campaign_id, npc_id, dialogue_id, speaker, text, visibility)
      VALUES (?, ?, ?, ?, ?, ?)
    `).run(campaignId, npcId, dialogue.dialogue_id, dialogue.speaker, dialogue.text, dialogue.visibility);
    return { result: "created", dialogue };
  } catch {
    return { result: "conflict" };
  }
}

export function readPlayCampaignNpcDialogue(
  campaignId: string,
  npcId: string,
  actor: string,
): { result: "found"; entries: PlayCampaignNpcDialogue[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  const isOwner = campaign.owner === actor;
  if (!isOwner && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  if (!database.prepare(`SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?`)
    .get(campaignId, npcId)) return { result: "not_found" };
  const entries = database.prepare(`
    SELECT dialogue_id, speaker, text, visibility
    FROM play_campaign_npc_dialogue
    WHERE campaign_id = ? AND npc_id = ?${isOwner ? "" : " AND visibility = 'public'"}
    ORDER BY rowid ASC
  `).all(campaignId, npcId) as PlayCampaignNpcDialogue[];
  return { result: "found", entries };
}

export function voteForPlayCampaignLoot(
  campaignId: string,
  lootId: string,
  actor: string,
  recipientCharacterId: string,
): { result: "created"; vote: PlayCampaignLootVote } | { result: "not_found" | "forbidden" | "invalid" | "conflict" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const loot = database.prepare(`SELECT status FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?`)
    .get(campaignId, lootId) as { status: string } | undefined;
  if (!loot) return { result: "not_found" };
  if (loot.status !== "open") return { result: "conflict" };
  const recipient = database.prepare(`
    SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, recipientCharacterId);
  if (!recipient) return { result: "invalid" };
  try {
    database.prepare(`
      INSERT INTO play_campaign_loot_votes (campaign_id, loot_id, voter, recipient_character_id)
      VALUES (?, ?, ?, ?)
    `).run(campaignId, lootId, actor, recipientCharacterId);
    const count = (database.prepare(`
      SELECT COUNT(*) AS count FROM play_campaign_loot_votes
      WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?
    `).get(campaignId, lootId, recipientCharacterId) as { count: number }).count;
    return { result: "created", vote: { loot_id: lootId, voter: actor, recipient_character_id: recipientCharacterId, votes_for_recipient: count } };
  } catch {
    return { result: "conflict" };
  }
}

export function assignPlayCampaignLoot(
  campaignId: string,
  lootId: string,
  actor: string,
): { result: "assigned"; loot: PlayCampaignLoot } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };

  database.exec("BEGIN IMMEDIATE");
  try {
    const loot = database.prepare(`
      SELECT loot_id, item_id, quantity, status FROM play_campaign_loot
      WHERE campaign_id = ? AND loot_id = ?
    `).get(campaignId, lootId) as Pick<PlayCampaignLoot, "loot_id" | "item_id" | "quantity" | "status"> | undefined;
    if (!loot) {
      database.exec("ROLLBACK");
      return { result: "not_found" };
    }
    if (loot.status !== "open") {
      database.exec("ROLLBACK");
      return { result: "conflict" };
    }
    const leaders = database.prepare(`
      SELECT recipient_character_id, COUNT(*) AS votes
      FROM play_campaign_loot_votes
      WHERE campaign_id = ? AND loot_id = ?
      GROUP BY recipient_character_id
      ORDER BY votes DESC, recipient_character_id ASC
    `).all(campaignId, lootId) as Array<{ recipient_character_id: string; votes: number }>;
    if (leaders.length === 0 || (leaders.length > 1 && leaders[0].votes === leaders[1].votes)) {
      database.exec("ROLLBACK");
      return { result: "conflict" };
    }
    const winner = leaders[0];
    database.prepare(`
      INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity)
      VALUES (?, ?, ?, ?)
      ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity
    `).run(campaignId, winner.recipient_character_id, loot.item_id, loot.quantity);
    database.prepare(`
      UPDATE play_campaign_loot
      SET status = 'assigned', recipient_character_id = ?, votes = ?
      WHERE campaign_id = ? AND loot_id = ? AND status = 'open'
    `).run(winner.recipient_character_id, winner.votes, campaignId, lootId);
    database.exec("COMMIT");
    return {
      result: "assigned",
      loot: { ...loot, status: "assigned", recipient_character_id: winner.recipient_character_id, votes: winner.votes },
    };
  } catch (error) {
    database.exec("ROLLBACK");
    throw error;
  }
}

export function readPlayCampaignLoot(
  campaignId: string,
  lootId: string,
  actor: string,
): { result: "found"; loot: PlayCampaignLootRecord } | { result: "not_found" | "forbidden" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const loot = database.prepare(`
    SELECT loot_id, item_id, quantity, status, recipient_character_id
    FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?
  `).get(campaignId, lootId) as Omit<PlayCampaignLoot, "votes"> | undefined;
  if (!loot) return { result: "not_found" };

  const voteRows = database.prepare(`
    SELECT recipient_character_id, COUNT(*) AS votes
    FROM play_campaign_loot_votes
    WHERE campaign_id = ? AND loot_id = ?
    GROUP BY recipient_character_id
  `).all(campaignId, lootId) as Array<{ recipient_character_id: string; votes: number }>;
  const votes = Object.fromEntries(voteRows.map(({ recipient_character_id, votes }) => [recipient_character_id, votes]));
  return { result: "found", loot: { ...loot, votes } };
}

export function isPlayCampaignConsumableItemId(itemId: string): boolean {
  return PLAY_CAMPAIGN_CONSUMABLE_ITEM_IDS.has(itemId);
}

export function isPlayCampaignEquipmentSlot(slot: string): slot is "armor" | "accessory" {
  return PLAY_CAMPAIGN_EQUIPMENT_SLOTS.has(slot);
}

function ownedPlayCampaignCharacter(campaignId: string, characterId: string, actor: string): "found" | "not_found" | "forbidden" {
  if (!playCampaignOwner(campaignId)) return "not_found";
  const owner = database.prepare(`
    SELECT owner FROM play_campaign_character_owners
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as { owner: string } | undefined;
  if (!owner) return "not_found";
  return owner.owner === actor ? "found" : "forbidden";
}

/** Equipping does not consume an inventory stack; it records the selected held item. */
export function equipPlayCampaignCharacterItem(
  campaignId: string,
  characterId: string,
  actor: string,
  slot: "armor" | "accessory",
  itemId: string,
): { result: "equipped"; equipment: PlayCampaignCharacterEquipment } | { result: "not_found" | "forbidden" | "invalid" } {
  const ownership = ownedPlayCampaignCharacter(campaignId, characterId, actor);
  if (ownership !== "found") return { result: ownership };
  if (PLAY_CAMPAIGN_EQUIPMENT_ITEM_SLOTS[itemId] !== slot) return { result: "invalid" };
  const held = database.prepare(`
    SELECT 1 FROM play_campaign_character_inventory_items
    WHERE campaign_id = ? AND character_id = ? AND item_id = ? AND quantity > 0
  `).get(campaignId, characterId, itemId);
  if (!held) return { result: "invalid" };

  database.prepare(`
    INSERT INTO play_campaign_character_equipment (campaign_id, character_id, slot, item_id, attuned)
    VALUES (?, ?, ?, ?, 0)
    ON CONFLICT(campaign_id, character_id, slot)
    DO UPDATE SET item_id = excluded.item_id, attuned = 0
  `).run(campaignId, characterId, slot, itemId);
  return { result: "equipped", equipment: { character_id: characterId, slot, item_id: itemId, attuned: false } };
}

/** Campaign members may inspect valid equipment slots, including empty slots. */
export function readPlayCampaignCharacterEquipment(
  campaignId: string,
  characterId: string,
  actor: string,
  slot: "armor" | "accessory",
): { result: "found"; equipment: PlayCampaignCharacterEquipment } | { result: "not_found" | "forbidden" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const character = database.prepare(`SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?`).get(campaignId, characterId);
  if (!character) return { result: "not_found" };
  const equipment = database.prepare(`
    SELECT item_id, attuned FROM play_campaign_character_equipment
    WHERE campaign_id = ? AND character_id = ? AND slot = ?
  `).get(campaignId, characterId, slot) as { item_id: string; attuned: number } | undefined;
  return {
    result: "found",
    equipment: { character_id: characterId, slot, item_id: equipment?.item_id ?? "", attuned: Boolean(equipment?.attuned) },
  };
}

export function attunePlayCampaignCharacterEquipment(
  campaignId: string,
  characterId: string,
  actor: string,
  slot: "armor" | "accessory",
): { result: "attuned"; equipment: PlayCampaignCharacterAttunedEquipment } | { result: "not_found" | "forbidden" | "invalid" | "conflict" } {
  const ownership = ownedPlayCampaignCharacter(campaignId, characterId, actor);
  if (ownership !== "found") return { result: ownership };
  const equipment = database.prepare(`
    SELECT item_id, attuned FROM play_campaign_character_equipment
    WHERE campaign_id = ? AND character_id = ? AND slot = ?
  `).get(campaignId, characterId, slot) as { item_id: string; attuned: number } | undefined;
  if (!equipment || slot !== "accessory" || !PLAY_CAMPAIGN_ATTUNABLE_ITEM_IDS.has(equipment.item_id)) return { result: "invalid" };
  const attunementCount = (database.prepare(`
    SELECT COUNT(*) AS count FROM play_campaign_character_equipment
    WHERE campaign_id = ? AND character_id = ? AND attuned = 1
  `).get(campaignId, characterId) as { count: number }).count;
  if (attunementCount >= 1) return { result: "conflict" };

  database.prepare(`
    UPDATE play_campaign_character_equipment SET attuned = 1
    WHERE campaign_id = ? AND character_id = ? AND slot = ?
  `).run(campaignId, characterId, slot);
  return {
    result: "attuned",
    equipment: { character_id: characterId, slot, item_id: equipment.item_id, attuned: true, attunement_count: 1, max_attunements: 1 },
  };
}

/** An inventory stack belongs to its character, so only its owner may change it. */
export function addPlayCampaignCharacterInventoryItem(
  campaignId: string,
  characterId: string,
  actor: string,
  itemId: string,
  quantity: number,
): { result: "created"; item: PlayCampaignInventoryItemStack } | { result: "not_found" | "forbidden" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  const owner = database.prepare(`
    SELECT owner FROM play_campaign_character_owners
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as { owner: string } | undefined;
  if (!owner) return { result: "not_found" };
  if (owner.owner !== actor) return { result: "forbidden" };

  database.prepare(`
    INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity
  `).run(campaignId, characterId, itemId, quantity);
  const total = database.prepare(`
    SELECT quantity FROM play_campaign_character_inventory_items
    WHERE campaign_id = ? AND character_id = ? AND item_id = ?
  `).get(campaignId, characterId, itemId) as { quantity: number };
  return { result: "created", item: { character_id: characterId, item_id: itemId, quantity, total_quantity: total.quantity } };
}

/** Campaign members can inspect any character's held inventory items. */
export function readPlayCampaignCharacterInventoryItems(
  campaignId: string,
  characterId: string,
  actor: string,
): { result: "found"; inventory: PlayCampaignCharacterInventory } | { result: "not_found" | "forbidden" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const character = database.prepare(`
    SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId);
  if (!character) return { result: "not_found" };
  const items = database.prepare(`
    SELECT item_id, quantity
    FROM play_campaign_character_inventory_items
    WHERE campaign_id = ? AND character_id = ?
    ORDER BY item_id ASC
  `).all(campaignId, characterId) as PlayCampaignInventoryItem[];
  return { result: "found", inventory: { character_id: characterId, items } };
}

export function removePlayCampaignCharacterInventoryItem(
  campaignId: string,
  characterId: string,
  actor: string,
  itemId: string,
  quantity: number,
): { result: "removed"; item: PlayCampaignInventoryItemStack } | { result: "not_found" | "forbidden" | "insufficient" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  const owner = database.prepare(`
    SELECT owner FROM play_campaign_character_owners
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as { owner: string } | undefined;
  if (!owner) return { result: "not_found" };
  if (owner.owner !== actor) return { result: "forbidden" };

  const held = database.prepare(`
    SELECT quantity FROM play_campaign_character_inventory_items
    WHERE campaign_id = ? AND character_id = ? AND item_id = ?
  `).get(campaignId, characterId, itemId) as { quantity: number } | undefined;
  if (!held || quantity > held.quantity) return { result: "insufficient" };

  const totalQuantity = held.quantity - quantity;
  if (totalQuantity === 0) {
    database.prepare(`DELETE FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?`)
      .run(campaignId, characterId, itemId);
  } else {
    database.prepare(`UPDATE play_campaign_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?`)
      .run(totalQuantity, campaignId, characterId, itemId);
  }
  return { result: "removed", item: { character_id: characterId, item_id: itemId, quantity, total_quantity: totalQuantity } };
}

/** Consuming an item is owner-only and removes exactly one held stack unit. */
export function consumePlayCampaignCharacterInventoryItem(
  campaignId: string,
  characterId: string,
  actor: string,
  itemId: string,
): { result: "consumed"; item: PlayCampaignInventoryItemStack } | { result: "not_found" | "forbidden" | "invalid" | "insufficient" } {
  if (!isPlayCampaignConsumableItemId(itemId)) return { result: "invalid" };

  const ownership = ownedPlayCampaignCharacter(campaignId, characterId, actor);
  if (ownership !== "found") return { result: ownership };

  const held = database.prepare(`
    SELECT quantity FROM play_campaign_character_inventory_items
    WHERE campaign_id = ? AND character_id = ? AND item_id = ?
  `).get(campaignId, characterId, itemId) as { quantity: number } | undefined;
  if (!held || held.quantity <= 0) return { result: "insufficient" };

  const totalQuantity = held.quantity - 1;
  if (totalQuantity === 0) {
    database.prepare(`DELETE FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?`)
      .run(campaignId, characterId, itemId);
  } else {
    database.prepare(`UPDATE play_campaign_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?`)
      .run(totalQuantity, campaignId, characterId, itemId);
  }
  return { result: "consumed", item: { character_id: characterId, item_id: itemId, quantity: 1, total_quantity: totalQuantity } };
}

/** A spellbook belongs to its character, so only that character's owner can change it. */
export function addPlayCampaignCharacterSpell(
  campaignId: string,
  characterId: string,
  actor: string,
  spell: PlayCampaignSpell,
): { result: "created"; spell: PlayCampaignSpell } | { result: "not_found" | "forbidden" | "invalid" | "conflict" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };

  const character = database.prepare(`
    SELECT members.class, owners.owner
    FROM play_campaign_members AS members
    LEFT JOIN play_campaign_character_owners AS owners
      ON owners.campaign_id = members.campaign_id AND owners.character_id = members.character_id
    WHERE members.campaign_id = ? AND members.character_id = ?
  `).get(campaignId, characterId) as { class: string; owner: string | null } | undefined;
  if (!character || !character.owner) return { result: "not_found" };
  if (character.owner !== actor) return { result: "forbidden" };

  // This API has no separate spell catalog: supplied spells are wizard spells
  // when known by a wizard.  Other classes (including rogues) cannot use a
  // spellbook at this stage.
  if (character.class !== "wizard") return { result: "invalid" };

  try {
    database.prepare(`
      INSERT INTO play_campaign_character_spells (campaign_id, character_id, spell_id, name, level)
      VALUES (?, ?, ?, ?, ?)
    `).run(campaignId, characterId, spell.spell_id, spell.name, spell.level);
    return { result: "created", spell };
  } catch {
    return { result: "conflict" };
  }
}

/** Campaign members can inspect any character's spellbook. */
export function readPlayCampaignCharacterSpells(
  campaignId: string,
  characterId: string,
  actor: string,
): { result: "found"; spells: PlayCampaignSpell[] } | { result: "not_found" | "forbidden" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };

  const character = database.prepare(`
    SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId);
  if (!character) return { result: "not_found" };

  const spells = database.prepare(`
    SELECT spell_id, name, level
    FROM play_campaign_character_spells
    WHERE campaign_id = ? AND character_id = ?
    ORDER BY rowid ASC
  `).all(campaignId, characterId) as PlayCampaignSpell[];
  return { result: "found", spells };
}

function preparedSpellMaximum(characterClass: string, level: number): number {
  // Spellbook support is deliberately wizard-only at this point in the API.
  // A wizard can prepare one known spell per character level.
  return characterClass === "wizard" ? level : 0;
}

type PreparedSpellCharacter = {
  class: string;
  owner: string | null;
  level: number | null;
};

function preparedSpellCharacter(campaignId: string, characterId: string): PreparedSpellCharacter | undefined {
  return database.prepare(`
    SELECT members.class, owners.owner, builds.level
    FROM play_campaign_members AS members
    LEFT JOIN play_campaign_character_owners AS owners
      ON owners.campaign_id = members.campaign_id AND owners.character_id = members.character_id
    LEFT JOIN play_campaign_character_builds AS builds
      ON builds.campaign_id = members.campaign_id AND builds.character_id = members.character_id
    WHERE members.campaign_id = ? AND members.character_id = ?
  `).get(campaignId, characterId) as PreparedSpellCharacter | undefined;
}

/** Prepared spells are an owner-controlled subset of a wizard's spellbook. */
export function preparePlayCampaignCharacterSpells(
  campaignId: string,
  characterId: string,
  actor: string,
  spellIds: string[],
): { result: "updated"; preparedSpells: PlayCampaignPreparedSpells } | { result: "not_found" | "forbidden" | "invalid" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };

  const character = preparedSpellCharacter(campaignId, characterId);
  if (!character || !character.owner) return { result: "not_found" };
  if (character.owner !== actor) return { result: "forbidden" };

  const maxPrepared = preparedSpellMaximum(character.class, character.level ?? 1);
  if (maxPrepared === 0 || new Set(spellIds).size !== spellIds.length || spellIds.length > maxPrepared) {
    return { result: "invalid" };
  }

  const knownSpells = new Set((database.prepare(`
    SELECT spell_id FROM play_campaign_character_spells
    WHERE campaign_id = ? AND character_id = ?
  `).all(campaignId, characterId) as Array<{ spell_id: string }>).map((spell) => spell.spell_id));
  if (!spellIds.every((spellId) => knownSpells.has(spellId))) return { result: "invalid" };

  database.prepare(`
    INSERT INTO play_campaign_character_prepared_spells (campaign_id, character_id, spell_ids_json)
    VALUES (?, ?, ?)
    ON CONFLICT(campaign_id, character_id) DO UPDATE SET spell_ids_json = excluded.spell_ids_json
  `).run(campaignId, characterId, JSON.stringify(spellIds));

  return {
    result: "updated",
    preparedSpells: { character_id: characterId, prepared_spells: spellIds, max_prepared: maxPrepared },
  };
}

/** Campaign members can inspect a character's prepared-spell selection. */
export function readPlayCampaignCharacterPreparedSpells(
  campaignId: string,
  characterId: string,
  actor: string,
): { result: "found"; preparedSpells: PlayCampaignPreparedSpells } | { result: "not_found" | "forbidden" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };

  const character = preparedSpellCharacter(campaignId, characterId);
  if (!character) return { result: "not_found" };
  const stored = database.prepare(`
    SELECT spell_ids_json FROM play_campaign_character_prepared_spells
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as { spell_ids_json: string } | undefined;
  let spellIds: string[] = [];
  if (stored) {
    try {
      const parsed: unknown = JSON.parse(stored.spell_ids_json);
      if (Array.isArray(parsed) && parsed.every((spellId) => typeof spellId === "string")) spellIds = parsed;
    } catch {
      // Existing malformed state is safely represented as no prepared spells.
    }
  }
  return {
    result: "found",
    preparedSpells: {
      character_id: characterId,
      prepared_spells: spellIds,
      max_prepared: preparedSpellMaximum(character.class, character.level ?? 1),
    },
  };
}

function preparedSpellIds(campaignId: string, characterId: string): string[] {
  const stored = database.prepare(`
    SELECT spell_ids_json FROM play_campaign_character_prepared_spells
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as { spell_ids_json: string } | undefined;
  if (!stored) return [];
  try {
    const parsed: unknown = JSON.parse(stored.spell_ids_json);
    return Array.isArray(parsed) && parsed.every((spellId) => typeof spellId === "string") ? parsed : [];
  } catch {
    return [];
  }
}

function concentrationFor(campaignId: string, characterId: string): PlayCampaignConcentration | null {
  return database.prepare(`
    SELECT spell_id, target, remaining_turns
    FROM play_campaign_character_concentrations
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as PlayCampaignConcentration | undefined ?? null;
}

/** An owner can replace their character's active concentration with a prepared spell. */
export function setPlayCampaignCharacterConcentration(
  campaignId: string,
  characterId: string,
  actor: string,
  spellId: string,
  target: string,
  durationTurns: number,
): { result: "updated"; concentration: PlayCampaignCharacterConcentration } | { result: "not_found" | "forbidden" | "invalid" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  const character = preparedSpellCharacter(campaignId, characterId);
  if (!character || !character.owner) return { result: "not_found" };
  if (character.owner !== actor) return { result: "forbidden" };
  if (character.class !== "wizard" || durationTurns < 1) return { result: "invalid" };

  const spell = database.prepare(`
    SELECT 1 FROM play_campaign_character_spells
    WHERE campaign_id = ? AND character_id = ? AND spell_id = ?
  `).get(campaignId, characterId, spellId);
  if (!spell || !preparedSpellIds(campaignId, characterId).includes(spellId)) return { result: "invalid" };

  const concentration: PlayCampaignConcentration = {
    spell_id: spellId,
    target,
    remaining_turns: durationTurns,
  };
  database.prepare(`
    INSERT INTO play_campaign_character_concentrations
      (campaign_id, character_id, spell_id, target, remaining_turns)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(campaign_id, character_id) DO UPDATE SET
      spell_id = excluded.spell_id,
      target = excluded.target,
      remaining_turns = excluded.remaining_turns
  `).run(campaignId, characterId, concentration.spell_id, concentration.target, concentration.remaining_turns);
  return { result: "updated", concentration: { character_id: characterId, concentration } };
}

/** Campaign members can inspect active concentration. */
export function readPlayCampaignCharacterConcentration(
  campaignId: string,
  characterId: string,
  actor: string,
): { result: "found"; concentration: PlayCampaignCharacterConcentration } | { result: "not_found" | "forbidden" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const character = database.prepare(`
    SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId);
  if (!character) return { result: "not_found" };
  return { result: "found", concentration: { character_id: characterId, concentration: concentrationFor(campaignId, characterId) } };
}

/** Campaign members advance (and, at zero, clear) active concentration. */
export function advancePlayCampaignCharacterConcentration(
  campaignId: string,
  characterId: string,
  actor: string,
): { result: "advanced"; concentration: PlayCampaignCharacterConcentration } | { result: "not_found" | "forbidden" } {
  const read = readPlayCampaignCharacterConcentration(campaignId, characterId, actor);
  if (read.result !== "found") return read;
  const current = read.concentration.concentration;
  if (!current) return { result: "advanced", concentration: read.concentration };
  if (current.remaining_turns <= 1) {
    database.prepare(`
      DELETE FROM play_campaign_character_concentrations WHERE campaign_id = ? AND character_id = ?
    `).run(campaignId, characterId);
    return { result: "advanced", concentration: { character_id: characterId, concentration: null } };
  }
  const concentration = { ...current, remaining_turns: current.remaining_turns - 1 };
  database.prepare(`
    UPDATE play_campaign_character_concentrations SET remaining_turns = ?
    WHERE campaign_id = ? AND character_id = ?
  `).run(concentration.remaining_turns, campaignId, characterId);
  return { result: "advanced", concentration: { character_id: characterId, concentration } };
}

/** Only a character owner can voluntarily clear their concentration. */
export function clearPlayCampaignCharacterConcentration(
  campaignId: string,
  characterId: string,
  actor: string,
): { result: "cleared"; concentration: PlayCampaignCharacterConcentration } | { result: "not_found" | "forbidden" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  const character = preparedSpellCharacter(campaignId, characterId);
  if (!character || !character.owner) return { result: "not_found" };
  if (character.owner !== actor) return { result: "forbidden" };
  database.prepare(`
    DELETE FROM play_campaign_character_concentrations WHERE campaign_id = ? AND character_id = ?
  `).run(campaignId, characterId);
  return { result: "cleared", concentration: { character_id: characterId, concentration: null } };
}

function spellSlotsFor(characterClass: string, level: number, slotLevel: number): number {
  // This API currently supports wizard spellcasting.  The stage's deterministic
  // level-one progression grants exactly one first-level slot.
  return characterClass === "wizard" && level === 1 && slotLevel === 1 ? 1 : 0;
}

/** Cast a prepared, known spell and record the remaining slot count. */
export function castPlayCampaignCharacterSpell(
  campaignId: string,
  characterId: string,
  actor: string,
  spellId: string,
  target: string,
): { result: "created"; cast: PlayCampaignSpellCast } | { result: "not_found" | "forbidden" | "invalid" | "exhausted" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };

  const character = preparedSpellCharacter(campaignId, characterId);
  if (!character || !character.owner) return { result: "not_found" };
  if (character.owner !== actor) return { result: "forbidden" };
  if (character.class !== "wizard") return { result: "invalid" };

  const spell = database.prepare(`
    SELECT spell_id, level FROM play_campaign_character_spells
    WHERE campaign_id = ? AND character_id = ? AND spell_id = ?
  `).get(campaignId, characterId, spellId) as Pick<PlayCampaignSpell, "spell_id" | "level"> | undefined;
  if (!spell || !preparedSpellIds(campaignId, characterId).includes(spellId)) return { result: "invalid" };

  const totalSlots = spellSlotsFor(character.class, character.level ?? 1, spell.level);
  const usedSlots = (database.prepare(`
    SELECT COUNT(*) AS count FROM play_campaign_character_casts
    WHERE campaign_id = ? AND character_id = ? AND slot_level = ?
  `).get(campaignId, characterId, spell.level) as { count: number }).count;
  if (usedSlots >= totalSlots) return { result: "exhausted" };

  const sequence = (database.prepare(`
    SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence
    FROM play_campaign_character_casts WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as { sequence: number }).sequence;
  const cast: PlayCampaignSpellCast = {
    character_id: characterId,
    spell_id: spell.spell_id,
    target,
    slot_level: spell.level,
    slots_remaining: totalSlots - usedSlots - 1,
    sequence,
  };
  database.prepare(`
    INSERT INTO play_campaign_character_casts
      (campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `).run(campaignId, characterId, cast.sequence, cast.spell_id, cast.target, cast.slot_level, cast.slots_remaining);
  return { result: "created", cast };
}

/** Any campaign member can inspect a character's ordered cast history. */
export function readPlayCampaignCharacterCasts(
  campaignId: string,
  characterId: string,
  actor: string,
): { result: "found"; casts: PlayCampaignSpellCast[] } | { result: "not_found" | "forbidden" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const character = database.prepare(`
    SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId);
  if (!character) return { result: "not_found" };
  const casts = database.prepare(`
    SELECT character_id, spell_id, target, slot_level, slots_remaining, sequence
    FROM play_campaign_character_casts
    WHERE campaign_id = ? AND character_id = ?
    ORDER BY sequence ASC
  `).all(campaignId, characterId) as PlayCampaignSpellCast[];
  return { result: "found", casts };
}

/** Build choices can only be finalized by the character's current owner. */
export function buildPlayCampaignCharacter(
  campaignId: string,
  characterId: string,
  actor: string,
  build: PlayCampaignCharacterBuild,
): { result: "built"; character: {
  character_id: string;
  race: string;
  class: string;
  background: string;
  level: number;
  hp_max: number;
  proficiency_bonus: number;
} } | { result: "not_found" | "forbidden" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };

  const owner = database.prepare(`
    SELECT owner FROM play_campaign_character_owners
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as { owner: string } | undefined;
  if (!owner) return { result: "not_found" };
  if (owner.owner !== actor) return { result: "forbidden" };

  const level = 1;
  const conModifier = abilityModifier(build.abilities.con);
  const hitDie = {
    barbarian: 12,
    fighter: 10,
    paladin: 10,
    ranger: 10,
    bard: 8,
    cleric: 8,
    druid: 8,
    monk: 8,
    rogue: 8,
    warlock: 8,
    sorcerer: 6,
    wizard: 6,
  }[build.class] ?? 8;
  const hpMax = hitDie + conModifier;
  database.prepare(`
    INSERT INTO play_campaign_character_builds (campaign_id, character_id, class, con_modifier, abilities_json, level, hp_max)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(campaign_id, character_id) DO UPDATE SET
      class = excluded.class,
      con_modifier = excluded.con_modifier,
      abilities_json = excluded.abilities_json,
      level = excluded.level,
      hp_max = excluded.hp_max
  `).run(campaignId, characterId, build.class, conModifier, JSON.stringify(build.abilities), level, hpMax);
  return {
    result: "built",
    character: {
      character_id: characterId,
      race: build.race,
      class: build.class,
      background: build.background,
      level,
      hp_max: hpMax,
      proficiency_bonus: proficiencyBonus(level),
    },
  };
}

export function resolvePlayCampaignSkillCheck(
  campaignId: string,
  characterId: string,
  actor: string,
  ability: AbilityName,
  proficient: boolean,
  roll: number,
): { result: "resolved"; modifier: number; total: number } | { result: "not_found" | "forbidden" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };

  const owner = database.prepare(`
    SELECT owner FROM play_campaign_character_owners
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as { owner: string } | undefined;
  if (!owner) return { result: "not_found" };
  if (owner.owner !== actor) return { result: "forbidden" };

  const build = database.prepare(`
    SELECT abilities_json, level FROM play_campaign_character_builds
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as { abilities_json: string; level: number } | undefined;
  if (!build) return { result: "not_found" };

  let abilities: Partial<Record<AbilityName, unknown>>;
  try {
    abilities = JSON.parse(build.abilities_json) as Partial<Record<AbilityName, unknown>>;
  } catch {
    return { result: "not_found" };
  }
  const score = abilities[ability];
  if (typeof score !== "number") return { result: "not_found" };
  const modifier = abilityModifier(score) + (proficient ? proficiencyBonus(build.level) : 0);
  return { result: "resolved", modifier, total: roll + modifier };
}

/** Level-ups are owned character progression; hit dice use their deterministic average. */
export function levelUpPlayCampaignCharacter(
  campaignId: string,
  characterId: string,
  actor: string,
  requestedLevel: number,
): { result: "leveled"; character: PlayCampaignCharacterLevel } | { result: "not_found" | "forbidden" | "invalid" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };

  const owner = database.prepare(`
    SELECT owner FROM play_campaign_character_owners
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as { owner: string } | undefined;
  if (!owner) return { result: "not_found" };
  if (owner.owner !== actor) return { result: "forbidden" };

  const build = database.prepare(`
    SELECT class, con_modifier, level, hp_max
    FROM play_campaign_character_builds
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as { class: string; con_modifier: number; level: number; hp_max: number } | undefined;
  if (!build || requestedLevel !== build.level + 1) return { result: "invalid" };

  const hitDie = {
    barbarian: 12, fighter: 10, paladin: 10, ranger: 10,
    bard: 8, cleric: 8, druid: 8, monk: 8, rogue: 8, warlock: 8,
    sorcerer: 6, wizard: 6,
  }[build.class] ?? 8;
  const hpGain = Math.floor(hitDie / 2) + 1 + build.con_modifier;
  const hpMax = build.hp_max + hpGain;
  database.prepare(`
    UPDATE play_campaign_character_builds SET level = ?, hp_max = ?
    WHERE campaign_id = ? AND character_id = ?
  `).run(requestedLevel, hpMax, campaignId, characterId);
  database.prepare(`
    UPDATE play_campaign_character_health SET hp_max = ?
    WHERE campaign_id = ? AND character_id = ?
  `).run(hpMax, campaignId, characterId);

  return {
    result: "leveled",
    character: {
      character_id: characterId,
      level: requestedLevel,
      hp_max: hpMax,
      hit_dice: `1d${hitDie}`,
      proficiency_bonus: proficiencyBonus(requestedLevel),
    },
  };
}

/** The campaign owner controls character damage; the member controls their death saves. */
export function damagePlayCampaignCharacter(
  campaignId: string,
  characterId: string,
  actor: string,
  amount: number,
): { result: "damaged"; health: PlayCampaignCharacterDamage } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };

  const member = database.prepare(`
    SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId);
  if (!member) return { result: "not_found" };

  database.prepare(`
    INSERT INTO play_campaign_character_health (campaign_id, character_id)
    VALUES (?, ?)
    ON CONFLICT(campaign_id, character_id) DO NOTHING
  `).run(campaignId, characterId);

  const health = database.prepare(`
    SELECT hp_current, hp_max, status FROM play_campaign_character_health
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as Pick<PlayCampaignCharacterHealth, "hp_current" | "hp_max" | "status">;
  const hpCurrent = Math.max(0, health.hp_current - amount);
  const droppedToZero = health.hp_current > 0 && hpCurrent === 0;
  const status: PlayCharacterStatus = droppedToZero ? "unconscious" : hpCurrent > 0 ? "conscious" : health.status;
  database.prepare(`
    UPDATE play_campaign_character_health
    SET hp_current = ?, status = ?,
        death_save_successes = CASE WHEN ? THEN 0 ELSE death_save_successes END,
        death_save_failures = CASE WHEN ? THEN 0 ELSE death_save_failures END
    WHERE campaign_id = ? AND character_id = ?
  `).run(hpCurrent, status, droppedToZero ? 1 : 0, droppedToZero ? 1 : 0, campaignId, characterId);
  return {
    result: "damaged",
    health: {
      character_id: characterId,
      hp_current: hpCurrent,
      hp_max: health.hp_max,
      status,
      target: characterId,
      hp_before: health.hp_current,
      hp_after: hpCurrent,
      damage: amount,
    },
  };
}

export function recordPlayCampaignDeathSave(
  campaignId: string,
  characterId: string,
  actor: string,
  outcome: "success" | "failure",
): { result: "recorded"; deathSaves: PlayCampaignDeathSaves } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  const member = database.prepare(`
    SELECT username FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as { username: string } | undefined;
  if (!member) return { result: "not_found" };
  if (member.username !== actor) return { result: "forbidden" };

  const health = database.prepare(`
    SELECT death_save_successes, death_save_failures, status
    FROM play_campaign_character_health WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, characterId) as { death_save_successes: number; death_save_failures: number; status: PlayCharacterStatus } | undefined;
  if (!health || health.status !== "unconscious") return { result: "conflict" };

  const successes = health.death_save_successes + (outcome === "success" ? 1 : 0);
  const failures = health.death_save_failures + (outcome === "failure" ? 1 : 0);
  const status: Exclude<PlayCharacterStatus, "conscious"> = successes >= 3 ? "stable" : failures >= 3 ? "dead" : "unconscious";
  database.prepare(`
    UPDATE play_campaign_character_health
    SET death_save_successes = ?, death_save_failures = ?, status = ?
    WHERE campaign_id = ? AND character_id = ?
  `).run(successes, failures, status, campaignId, characterId);
  return { result: "recorded", deathSaves: { character_id: characterId, successes, failures, status } };
}

export function readPlayCampaignCharacterHealth(
  campaignId: string,
  characterId: string,
  actor: string,
): { result: "found"; health: PlayCampaignCharacterHealth } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const health = database.prepare(`
    SELECT health.character_id, health.hp_current, health.hp_max, health.status
    FROM play_campaign_character_health AS health
    JOIN play_campaign_members AS members
      ON members.campaign_id = health.campaign_id AND members.character_id = health.character_id
    WHERE health.campaign_id = ? AND health.character_id = ?
  `).get(campaignId, characterId) as PlayCampaignCharacterHealth | undefined;
  return health ? { result: "found", health } : { result: "not_found" };
}

export type StartedPlayCampaign = {
  id: string;
  status: "active";
  current_actor: string;
  turn_number: 1;
};

export type PlayCampaignTurn = {
  campaign_id: string;
  current_actor: string;
  // Legacy turn reads describe whose turn it is.  The combat-to-exploration
  // transition is additionally observable as the explicit exploration mode.
  phase: "player" | "dm" | "combat" | "exploration";
  turn_number: number;
  queue: string[];
  overdue: false;
  logical_deadline: number;
};

function currentPlayActor(campaignId: string, owner: string, firstPlayer: string): string {
  const latestTurnEvent = database.prepare(`
    SELECT sequence, kind FROM play_campaign_events
    WHERE campaign_id = ? AND kind IN ('action', 'resolution', 'travel', 'rest')
    ORDER BY sequence DESC
    LIMIT 1
  `).get(campaignId) as { sequence: number; kind: "action" | "resolution" | "travel" | "rest" } | undefined;
  const latestCombatEnd = database.prepare(`
    SELECT MAX(sequence) AS sequence FROM play_campaign_events
    WHERE campaign_id = ? AND kind = 'combat_end'
  `).get(campaignId) as { sequence: number | null };
  // Ending combat hands authority to the DM.  The next player action or DM
  // resolution naturally supersedes this transition marker.
  if (latestCombatEnd.sequence !== null && (!latestTurnEvent || latestCombatEnd.sequence > latestTurnEvent.sequence)) {
    return owner;
  }
  if (!latestTurnEvent) return firstPlayer;
  if (latestTurnEvent.kind === "action" || latestTurnEvent.kind === "travel" || latestTurnEvent.kind === "rest") return owner;

  const members = orderedPlayCampaignMembers(campaignId);
  if (members.length === 0) return firstPlayer;
  // A resolution hands the campaign to the member after the player whose turn
  // prompted it. Counting resolutions alone is insufficient when exploration
  // is interrupted by combat or another player-turn event.
  const precedingPlayerEvent = database.prepare(`
    SELECT sequence, actor FROM play_campaign_events
    WHERE campaign_id = ? AND kind IN ('action', 'travel', 'rest')
    ORDER BY sequence DESC
    LIMIT 1
  `).get(campaignId) as { sequence: number; actor: string } | undefined;
  // Combat does not consume an exploration turn.  When it ends while the DM
  // is due to resolve the interrupted turn, that resolution begins the next
  // exploration rotation from the stable party head.  Later exploration
  // actions naturally resume the normal actor-after-player calculation.
  const latestCombatAction = database.prepare(`
    SELECT MAX(sequence) AS sequence
    FROM play_campaign_events
    WHERE campaign_id = ? AND kind = 'combat_action'
  `).get(campaignId) as { sequence: number | null };
  if (precedingPlayerEvent && latestCombatAction.sequence !== null &&
    latestCombatAction.sequence > precedingPlayerEvent.sequence) return firstPlayer;
  const precedingIndex = precedingPlayerEvent
    ? members.findIndex((member) => member.username === precedingPlayerEvent.actor)
    : -1;
  if (precedingIndex >= 0) return members[(precedingIndex + 1) % members.length].username;

  const resolutions = database.prepare(`
    SELECT COUNT(*) AS count FROM play_campaign_events
    WHERE campaign_id = ? AND kind = 'resolution'
  `).get(campaignId) as { count: number };
  return members[resolutions.count % members.length].username;
}

function currentPlayTurnNumber(campaignId: string): number {
  const resolutions = database.prepare(`
    SELECT COUNT(*) AS count FROM play_campaign_events
    WHERE campaign_id = ? AND kind = 'resolution'
  `).get(campaignId) as { count: number };
  return resolutions.count + 1;
}

function readPlayCampaignTurnPhase(
  campaignId: string,
  campaignPhase: "exploration" | "combat",
  currentActor: string,
  owner: string,
): PlayCampaignTurn["phase"] {
  if (campaignPhase === "combat") return "combat";

  const latestTurnEvent = database.prepare(`
    SELECT MAX(sequence) AS sequence FROM play_campaign_events
    WHERE campaign_id = ? AND kind IN ('action', 'resolution', 'travel', 'rest')
  `).get(campaignId) as { sequence: number | null };
  const latestCombatEnd = database.prepare(`
    SELECT MAX(sequence) AS sequence FROM play_campaign_events
    WHERE campaign_id = ? AND kind = 'combat_end'
  `).get(campaignId) as { sequence: number | null };

  // This is a persistent mode transition, not a normal DM-resolution turn.
  if (latestCombatEnd.sequence !== null &&
    (latestTurnEvent.sequence === null || latestCombatEnd.sequence > latestTurnEvent.sequence)) {
    return "exploration";
  }
  return currentActor === owner ? "dm" : "player";
}

function worldEventFromRow(row: unknown): PlayCampaignWorldEvent {
  const event = row as {
    event_id: string;
    turn_number: number;
    title: string;
    text: string;
    resolution_turn_number: number | null;
    resolution_text: string | null;
  };
  if (event.resolution_text === null) {
    return {
      event_id: event.event_id,
      turn_number: event.turn_number,
      title: event.title,
      text: event.text,
      status: "scheduled",
    };
  }
  return {
    event_id: event.event_id,
    turn_number: event.turn_number,
    title: event.title,
    text: event.text,
    status: "resolved",
    resolution: { turn_number: event.resolution_turn_number!, text: event.resolution_text },
  };
}

export function schedulePlayCampaignWorldEvent(
  campaignId: string,
  actor: string,
  event: Pick<PlayCampaignWorldEvent, "event_id" | "turn_number" | "title" | "text">,
): { result: "created"; event: PlayCampaignWorldEvent } | { result: "not_found" | "forbidden" | "invalid" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  if (event.turn_number < currentPlayTurnNumber(campaignId)) return { result: "invalid" };
  try {
    database.prepare(`
      INSERT INTO play_campaign_world_events (campaign_id, event_id, turn_number, title, text)
      VALUES (?, ?, ?, ?, ?)
    `).run(campaignId, event.event_id, event.turn_number, event.title, event.text);
    return { result: "created", event: { ...event, status: "scheduled" } };
  } catch {
    return { result: "conflict" };
  }
}

export function resolvePlayCampaignWorldEvent(
  campaignId: string,
  eventId: string,
  actor: string,
  text: string,
): { result: "created"; event: PlayCampaignWorldEvent } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const row = database.prepare(`
    SELECT event_id, turn_number, title, text, resolution_turn_number, resolution_text
    FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?
  `).get(campaignId, eventId);
  if (!row) return { result: "not_found" };
  const event = worldEventFromRow(row);
  if (event.status === "resolved" || currentPlayTurnNumber(campaignId) !== event.turn_number) return { result: "conflict" };
  database.prepare(`
    UPDATE play_campaign_world_events
    SET resolution_turn_number = ?, resolution_text = ?
    WHERE campaign_id = ? AND event_id = ? AND resolution_text IS NULL
  `).run(event.turn_number, text, campaignId, eventId);
  return { result: "created", event: { ...event, status: "resolved", resolution: { turn_number: event.turn_number, text } } };
}

export function readPlayCampaignWorldEvents(
  campaignId: string,
  actor: string,
): { result: "found"; events: PlayCampaignWorldEvent[] } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const events = database.prepare(`
    SELECT event_id, turn_number, title, text, resolution_turn_number, resolution_text
    FROM play_campaign_world_events WHERE campaign_id = ?
    ORDER BY turn_number ASC, rowid ASC
  `).all(campaignId).map(worldEventFromRow);
  return { result: "found", events };
}

export function readPlayCampaignTurn(
  campaignId: string,
  actor: string,
): { result: "found"; turn: PlayCampaignTurn } | { result: "not_found" } | { result: "forbidden" } {
  const campaign = database.prepare("SELECT owner, phase FROM play_campaigns WHERE id = ?")
    .get(campaignId) as (Pick<PlayCampaign, "owner"> & { phase: "exploration" | "combat" }) | undefined;
  if (!campaign) return { result: "not_found" };

  const isMember = database.prepare(
    "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
  ).get(campaignId, actor);
  if (campaign.owner !== actor && !isMember) return { result: "forbidden" };

  const members = orderedPlayCampaignMembers(campaignId);

  // A campaign can only start after two members join, so an active campaign
  // always has a deterministic first actor.
  if (members.length === 0) return { result: "not_found" };
  const queue = members.flatMap(({ username }) => [username, "dm"]);
  const currentActor = currentPlayActor(campaignId, campaign.owner, queue[0]);
  const turnNumber = currentPlayTurnNumber(campaignId);
  return {
    result: "found",
    turn: {
      campaign_id: campaignId,
      current_actor: currentActor,
      phase: readPlayCampaignTurnPhase(campaignId, campaign.phase, currentActor, campaign.owner),
      turn_number: turnNumber,
      queue,
      overdue: false,
      logical_deadline: turnNumber + 1,
    },
  };
}

export type PlayerTurnContext = {
  is_my_turn: boolean;
  current_actor: string;
  character: { id: string; name: string };
  recent_events: PlayCampaignRecentEvent[];
};

export type GmTurnContext = {
  needs_attention: boolean;
  current_actor: string;
  party: PlayCampaignMember[];
  recent_events: PlayCampaignRecentEvent[];
};

/** The fixed public fields shared by recent-event views. */
export type PlayCampaignRecentEvent = {
  sequence: number;
  kind: string;
  actor: string;
  text: string;
};

function recentPlayCampaignEvents(campaignId: string): PlayCampaignRecentEvent[] {
  return database.prepare(`
    SELECT sequence, kind, actor, text
    FROM play_campaign_events
    WHERE campaign_id = ?
    ORDER BY sequence DESC
    LIMIT 5
  `).all(campaignId) as PlayCampaignRecentEvent[];
}

/** Return the owner-only view of a play campaign's current turn. */
export function readGmTurnContext(
  campaignId: string,
  owner: string,
): { result: "found"; context: GmTurnContext } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };

  const party = orderedPlayCampaignMembers(campaignId);
  const currentActor = party[0]
    ? currentPlayActor(campaignId, campaign.owner, party[0].username)
    : campaign.owner;
  const recentEvents = recentPlayCampaignEvents(campaignId);

  return {
    result: "found",
    context: {
      needs_attention: currentActor === campaign.owner,
      current_actor: currentActor,
      party,
      recent_events: recentEvents,
    },
  };
}

/**
 * Return the public, player-scoped portion of an active play campaign.  The
 * selected columns deliberately exclude any campaign document fields.
 */
export function readPlayerTurnContext(
  campaignId: string,
  actor: string,
): { result: "found"; context: PlayerTurnContext } | { result: "not_found" | "forbidden" } {
  const campaign = database.prepare("SELECT id, owner FROM play_campaigns WHERE id = ?")
    .get(campaignId) as Pick<PlayCampaign, "id" | "owner"> | undefined;
  if (!campaign) return { result: "not_found" };

  const character = database.prepare(`
    SELECT character_id AS id, name
    FROM play_campaign_members
    WHERE campaign_id = ? AND username = ?
  `).get(campaignId, actor) as { id: string; name: string } | undefined;
  if (!character) return { result: "forbidden" };

  const firstMember = firstPlayCampaignMember(campaignId);
  if (!firstMember) return { result: "forbidden" };

  const recentEvents = recentPlayCampaignEvents(campaignId);

  const currentActor = currentPlayActor(campaignId, campaign.owner, firstMember.username);
  return {
    result: "found",
    context: {
      is_my_turn: currentActor === actor,
      current_actor: currentActor,
      character,
      recent_events: recentEvents,
    },
  };
}

export function startPlayCampaign(
  campaignId: string,
  owner: string,
): { result: "started"; campaign: StartedPlayCampaign } | { result: "not_found" | "forbidden" | "conflict" } {
  const update = database.prepare(`
    UPDATE play_campaigns
    SET status = 'active'
    WHERE id = ?
      AND owner = ?
      AND status = 'lobby'
      AND (SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?) >= 2
  `).run(campaignId, owner, campaignId);

  if (update.changes === 1) {
    const firstMember = firstPlayCampaignMember(campaignId)!;
    return {
      result: "started",
      campaign: { id: campaignId, status: "active", current_actor: firstMember.username, turn_number: 1 },
    };
  }

  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };
  return { result: "conflict" };
}

export type PlayCampaignNarration = {
  sequence: number;
  kind: "narration";
  actor: string;
  text: string;
};

export type PlayCampaignAction = {
  sequence: number;
  kind: "action";
  actor: string;
  type: string;
  text: string;
  next_actor: "dm";
};

export type PlayCampaignResolution = {
  sequence: number;
  kind: "resolution";
  actor: string;
  text: string;
  next_actor: string;
  turn_number: number;
};

export type PlayCampaignTravel = {
  sequence: number;
  kind: "travel";
  actor: string;
  destination_id: string;
  travel_turns: number;
  next_actor: "dm";
};

export type PlayCampaignRest = {
  sequence: number;
  kind: "rest";
  actor: string;
  type: "short" | "long";
  hp_current: number;
  hp_max: number;
  next_actor: "dm";
};

export type PlayCharacterStatus = "conscious" | "unconscious" | "stable" | "dead";

export type PlayCampaignCharacterHealth = {
  character_id: string;
  hp_current: number;
  hp_max: number;
  status: PlayCharacterStatus;
};

export type PlayCampaignCharacterDamage = PlayCampaignCharacterHealth & {
  target: string;
  hp_before: number;
  hp_after: number;
  damage: number;
};

export type PlayCampaignDeathSaves = {
  character_id: string;
  successes: number;
  failures: number;
  status: Exclude<PlayCharacterStatus, "conscious">;
};

export type PlayCampaignCombatAction = {
  sequence: number;
  kind: "combat_action";
  actor: string;
  type: "attack" | "help" | "dodge" | "ready";
  target: string;
  text: string;
};

export type PlayCampaignNudge = {
  actor: string;
  target: string;
  message: string;
  nudge_count: number;
};

export function appendPlayCampaignAction(
  campaignId: string,
  actor: string,
  type: string,
  text: string,
): { result: "created"; action: PlayCampaignAction } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = database.prepare("SELECT owner, status FROM play_campaigns WHERE id = ?")
    .get(campaignId) as Pick<PlayCampaign, "owner" | "status"> | undefined;
  if (!campaign) return { result: "not_found" };

  const member = database.prepare(`
    SELECT username FROM play_campaign_members
    WHERE campaign_id = ? AND username = ?
  `).get(campaignId, actor) as { username: string } | undefined;
  if (!member) return { result: campaign.owner === actor ? "conflict" : "forbidden" };

  const firstMember = firstPlayCampaignMember(campaignId);
  if (campaign.status !== "active" || !firstMember || actor !== currentPlayActor(campaignId, campaign.owner, firstMember.username)) {
    return { result: "conflict" };
  }

  const action = database.prepare(`
    INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, type, text)
    VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_events WHERE campaign_id = ?), 0) + 1, 'action', ?, ?, ?)
    RETURNING sequence, kind, actor, type, text
  `).get(campaignId, campaignId, actor, type, text) as Omit<PlayCampaignAction, "next_actor">;
  return { result: "created", action: { ...action, next_actor: "dm" } };
}

/** Record an action from the active player combatant without advancing combat. */
export function appendPlayCampaignCombatAction(
  campaignId: string,
  encounterId: string,
  actor: string,
  type: PlayCampaignCombatAction["type"],
  target: string,
  text: string,
): { result: "created"; action: PlayCampaignCombatAction } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (!isPlayCampaignMember(campaignId, actor)) return { result: campaign.owner === actor ? "conflict" : "forbidden" };

  const encounter = database.prepare(`
    SELECT round, turn_index AS turnIndex
    FROM play_campaign_encounters
    WHERE id = ? AND campaign_id = ? AND status = 'active'
  `).get(encounterId, campaignId) as { round: number; turnIndex: number } | undefined;
  if (!encounter) return { result: "not_found" };

  const order = encounterCombatOrder(encounterId);
  if (order.length === 0) return { result: "conflict" };
  const active = order[encounter.turnIndex % order.length];
  if (active.kind !== "player" || active.member !== actor) return { result: "conflict" };

  const action = database.prepare(`
    INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, type, target, text)
    VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_events WHERE campaign_id = ?), 0) + 1, 'combat_action', ?, ?, ?, ?)
    RETURNING sequence, kind, actor, type, target, text
  `).get(campaignId, campaignId, actor, type, target, text) as PlayCampaignCombatAction;
  return { result: "created", action };
}

/** Move the party along an outbound edge and hand the exploration turn to the GM. */
export function appendPlayCampaignTravel(
  campaignId: string,
  actor: string,
  destinationId: string,
): { result: "created"; travel: PlayCampaignTravel } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = database.prepare("SELECT owner, status FROM play_campaigns WHERE id = ?")
    .get(campaignId) as Pick<PlayCampaign, "owner" | "status"> | undefined;
  if (!campaign) return { result: "not_found" };

  const member = database.prepare(`
    SELECT username FROM play_campaign_members
    WHERE campaign_id = ? AND username = ?
  `).get(campaignId, actor);
  if (!member) return { result: campaign.owner === actor ? "conflict" : "forbidden" };

  const firstMember = firstPlayCampaignMember(campaignId);
  if (campaign.status !== "active" || !firstMember || actor !== currentPlayActor(campaignId, campaign.owner, firstMember.username)) {
    return { result: "conflict" };
  }

  const connection = database.prepare(`
    SELECT travel_turns FROM play_campaign_location_connections
    WHERE campaign_id = ?
      AND from_id = COALESCE(
        (SELECT state.current_scene_id
         FROM play_campaign_scene_state AS state
         JOIN play_campaign_locations AS location
           ON location.campaign_id = state.campaign_id AND location.id = state.current_scene_id
         WHERE state.campaign_id = ?),
        (SELECT id FROM play_campaign_locations WHERE campaign_id = ? ORDER BY rowid ASC LIMIT 1)
      )
      AND to_id = ?
  `).get(campaignId, campaignId, campaignId, destinationId) as { travel_turns: number } | undefined;
  if (!connection) return { result: "conflict" };

  const event = database.prepare(`
    INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text)
    VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_events WHERE campaign_id = ?), 0) + 1, 'travel', ?, ?)
    RETURNING sequence, kind, actor
  `).get(campaignId, campaignId, actor, destinationId) as Pick<PlayCampaignTravel, "sequence" | "kind" | "actor">;
  return {
    result: "created",
    travel: { ...event, destination_id: destinationId, travel_turns: connection.travel_turns, next_actor: "dm" },
  };
}

/** Consume the active player's exploration turn to take a rest. */
export function appendPlayCampaignRest(
  campaignId: string,
  actor: string,
  type: "short" | "long",
): { result: "created"; rest: PlayCampaignRest } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = database.prepare("SELECT owner, status FROM play_campaigns WHERE id = ?")
    .get(campaignId) as Pick<PlayCampaign, "owner" | "status"> | undefined;
  if (!campaign) return { result: "not_found" };

  const member = database.prepare(`
    SELECT character_id FROM play_campaign_members
    WHERE campaign_id = ? AND username = ?
  `).get(campaignId, actor) as Pick<PlayCampaignMember, "character_id"> | undefined;
  if (!member) return { result: campaign.owner === actor ? "conflict" : "forbidden" };

  const firstMember = firstPlayCampaignMember(campaignId);
  if (campaign.status !== "active" || !firstMember || actor !== currentPlayActor(campaignId, campaign.owner, firstMember.username)) {
    return { result: "conflict" };
  }

  database.prepare(`
    INSERT INTO play_campaign_character_health (campaign_id, character_id)
    VALUES (?, ?)
    ON CONFLICT(campaign_id, character_id) DO NOTHING
  `).run(campaignId, member.character_id);
  if (type === "long") {
    database.prepare(`
      UPDATE play_campaign_character_health
      SET hp_current = hp_max, death_save_successes = 0, death_save_failures = 0, status = 'conscious'
      WHERE campaign_id = ? AND character_id = ?
    `).run(campaignId, member.character_id);
  }

  const health = database.prepare(`
    SELECT hp_current, hp_max FROM play_campaign_character_health
    WHERE campaign_id = ? AND character_id = ?
  `).get(campaignId, member.character_id) as Pick<PlayCampaignRest, "hp_current" | "hp_max">;
  const event = database.prepare(`
    INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, type, text)
    VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_events WHERE campaign_id = ?), 0) + 1, 'rest', ?, ?, ?)
    RETURNING sequence, kind, actor, type
  `).get(campaignId, campaignId, actor, type, type) as Pick<PlayCampaignRest, "sequence" | "kind" | "actor" | "type">;
  return { result: "created", rest: { ...event, ...health, next_actor: "dm" } };
}

/** Record the owner's response and hand the turn to the next party member. */
export function appendPlayCampaignResolution(
  campaignId: string,
  owner: string,
  text: string,
): { result: "created"; resolution: PlayCampaignResolution } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = database.prepare("SELECT owner, status FROM play_campaigns WHERE id = ?")
    .get(campaignId) as Pick<PlayCampaign, "owner" | "status"> | undefined;
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };

  const firstMember = firstPlayCampaignMember(campaignId);
  if (campaign.status !== "active" || !firstMember || currentPlayActor(campaignId, campaign.owner, firstMember.username) !== owner) {
    return { result: "conflict" };
  }

  const resolution = database.prepare(`
    INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text)
    VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_events WHERE campaign_id = ?), 0) + 1, 'resolution', ?, ?)
    RETURNING sequence, kind, actor, text
  `).get(campaignId, campaignId, owner, text) as Omit<PlayCampaignResolution, "next_actor" | "turn_number">;
  const nextActor = currentPlayActor(campaignId, campaign.owner, firstMember.username);
  return {
    result: "created",
    resolution: { ...resolution, next_actor: nextActor, turn_number: currentPlayTurnNumber(campaignId) },
  };
}

/** Record an owner reminder without changing the active turn. */
export function appendPlayCampaignNudge(
  campaignId: string,
  owner: string,
  message: string,
): { result: "created"; nudge: PlayCampaignNudge } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== owner) return { result: "forbidden" };

  const firstMember = firstPlayCampaignMember(campaignId);
  const target = firstMember
    ? currentPlayActor(campaignId, campaign.owner, firstMember.username)
    : campaign.owner;

  database.prepare(`
    INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text)
    VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_events WHERE campaign_id = ?), 0) + 1, 'nudge', ?, ?)
  `).run(campaignId, campaignId, owner, message);
  const count = database.prepare(`
    SELECT COUNT(*) AS count FROM play_campaign_events
    WHERE campaign_id = ? AND kind = 'nudge'
  `).get(campaignId) as { count: number };

  return {
    result: "created",
    nudge: { actor: owner, target, message, nudge_count: count.count },
  };
}

export function appendPlayCampaignNarration(
  campaignId: string,
  actor: string,
  text: string,
): { result: "created"; narration: PlayCampaignNarration } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  const delegation = database.prepare(`
    SELECT 1 FROM play_campaign_delegations
    WHERE campaign_id = ? AND username = ? AND active = 1 AND powers_json = ?
  `).get(campaignId, actor, JSON.stringify(narrationPowers));
  if (campaign.owner !== actor && !delegation) return { result: "forbidden" };

  const narration = database.prepare(`
    INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text)
    VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_events WHERE campaign_id = ?), 0) + 1, 'narration', ?, ?)
    RETURNING sequence, kind, actor, text
  `).get(campaignId, campaignId, actor, text) as PlayCampaignNarration;
  return { result: "created", narration };
}

export function createPlayCampaignNote(campaignId: string, actor: string, note: Omit<PlayCampaignNote, "owner">):
  { result: "created"; note: PlayCampaignNote } | { result: "not_found" | "forbidden" | "conflict" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  // The campaign owner is an actor even though owners are not party members.
  if (!playCampaignActor(campaignId, actor)) return { result: "forbidden" };
  const created = { ...note, owner: actor };
  try {
    database.prepare("INSERT INTO play_campaign_notes (campaign_id, note_id, text, visibility, owner) VALUES (?, ?, ?, ?, ?)")
      .run(campaignId, created.note_id, created.text, created.visibility, created.owner);
    return { result: "created", note: created };
  } catch { return { result: "conflict" }; }
}

/** Append a member-authored chat fixture without exposing it in public projections. */
export function createPlayCampaignMessage(
  campaignId: string,
  actor: string,
  text: string,
): { result: "created"; message: { kind: "chat"; actor: string; text: string } } | { result: "not_found" | "forbidden" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!playCampaignActor(campaignId, actor)) return { result: "forbidden" };
  database.prepare(`
    INSERT INTO play_campaign_system_events (campaign_id, sequence, kind, actor, text)
    VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_system_events WHERE campaign_id = ?), 0) + 1, 'chat', ?, ?)
  `).run(campaignId, campaignId, actor, text);
  return { result: "created", message: { kind: "chat", actor, text } };
}

function noteFromRow(row: unknown): PlayCampaignNote {
  const note = row as PlayCampaignNote;
  return { note_id: note.note_id, text: note.text, visibility: note.visibility, owner: note.owner };
}

export function readPlayCampaignNotes(campaignId: string, actor: string):
  { result: "found"; notes: PlayCampaignNote[] } | { result: "not_found" | "forbidden" } {
  const role = playCampaignActor(campaignId, actor);
  if (!role) return playCampaignOwner(campaignId) ? { result: "forbidden" } : { result: "not_found" };
  const notes = database.prepare(`SELECT note_id, text, visibility, owner FROM play_campaign_notes
    WHERE campaign_id = ? ${role === "dm" ? "" : "AND (visibility = 'party' OR owner = ?)"} ORDER BY rowid ASC`)
    .all(...(role === "dm" ? [campaignId] : [campaignId, actor])).map(noteFromRow);
  return { result: "found", notes };
}

export function createPlayCampaignSearchRecord(
  campaignId: string,
  actor: string,
  record: PlayCampaignSearchRecord,
): { result: "created"; record: PlayCampaignSearchRecord } | { result: "not_found" | "forbidden" | "conflict" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };
  const duplicate = database.prepare(`
    SELECT 1 FROM play_campaign_search_records
    WHERE campaign_id = ? AND (record_id = ? OR text = ?)
    LIMIT 1
  `).get(campaignId, record.record_id, record.text);
  if (duplicate) return { result: "conflict" };
  try {
    database.prepare(`
      INSERT INTO play_campaign_search_records (campaign_id, record_id, text)
      VALUES (?, ?, ?)
    `).run(campaignId, record.record_id, record.text);
    return { result: "created", record };
  } catch {
    return { result: "conflict" };
  }
}

export function readPlayCampaignSearchRecords(
  campaignId: string,
  actor: string,
  query: string | undefined,
  limit: number,
  cursor: number,
): { result: "found"; records: PlayCampaignSearchRecord[]; next_cursor: number | null } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };

  const records = database.prepare(`
    SELECT record_id, text FROM play_campaign_search_records
    WHERE campaign_id = ? ORDER BY rowid ASC
  `).all(campaignId) as PlayCampaignSearchRecord[];
  const needle = query?.toLowerCase();
  const filtered = needle === undefined ? records : records.filter((record) => record.text.toLowerCase().includes(needle));
  const page = filtered.slice(cursor, cursor + limit);
  const next_cursor = cursor + page.length < filtered.length ? cursor + page.length : null;
  return { result: "found", records: page, next_cursor };
}

const rateEventLimit = 2;

/**
 * Accept a rate event while holding SQLite's write lock.  This makes the
 * remaining allowance deterministic even when two requests arrive together.
 */
export function createPlayCampaignRateEvent(
  campaignId: string,
  actor: string,
  eventId: string,
): { result: "created"; event: PlayCampaignRateEvent; remaining: number }
  | { result: "not_found" | "forbidden" | "conflict" }
  | { result: "limited"; remaining: 0 } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };

  database.exec("BEGIN IMMEDIATE");
  try {
    if (database.prepare(`SELECT 1 FROM play_campaign_rate_events
      WHERE campaign_id = ? AND event_id = ?`).get(campaignId, eventId)) {
      database.exec("COMMIT");
      return { result: "conflict" };
    }
    const count = database.prepare(`SELECT COUNT(*) AS count FROM play_campaign_rate_events
      WHERE campaign_id = ? AND actor = ?`).get(campaignId, actor) as { count: number };
    if (count.count >= rateEventLimit) {
      database.prepare(`INSERT INTO play_campaign_metrics (campaign_id, rejected_rate_events)
        VALUES (?, 1)
        ON CONFLICT(campaign_id) DO UPDATE SET rejected_rate_events = rejected_rate_events + 1`).run(campaignId);
      database.exec("COMMIT");
      return { result: "limited", remaining: 0 };
    }
    database.prepare(`INSERT INTO play_campaign_rate_events (campaign_id, sequence, event_id, actor)
      VALUES (?, COALESCE((SELECT MAX(sequence) FROM play_campaign_rate_events WHERE campaign_id = ?), 0) + 1, ?, ?)`)
      .run(campaignId, campaignId, eventId, actor);
    database.exec("COMMIT");
    return { result: "created", event: { event_id: eventId, actor }, remaining: rateEventLimit - count.count - 1 };
  } catch {
    try { database.exec("ROLLBACK"); } catch { /* transaction already closed */ }
    return { result: "conflict" };
  }
}

export function readPlayCampaignRateEvents(
  campaignId: string,
  actor: string,
): { result: "found"; events: PlayCampaignRateEvent[]; remaining: number } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor && !isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const events = database.prepare(`SELECT event_id, actor FROM play_campaign_rate_events
    WHERE campaign_id = ? ORDER BY sequence ASC`).all(campaignId) as PlayCampaignRateEvent[];
  const count = database.prepare(`SELECT COUNT(*) AS count FROM play_campaign_rate_events
    WHERE campaign_id = ? AND actor = ?`).get(campaignId, actor) as { count: number };
  return { result: "found", events, remaining: Math.max(0, rateEventLimit - count.count) };
}

/** Returns campaign-level aggregate operational counters without campaign content. */
export function readPlayCampaignMetrics(
  campaignId: string,
  actor: string,
): { result: "found"; metrics: PlayCampaignMetrics } | { result: "not_found" | "forbidden" } {
  const campaign = playCampaignOwner(campaignId);
  if (!campaign) return { result: "not_found" };
  if (campaign.owner !== actor) return { result: "forbidden" };

  const accepted = database.prepare(`SELECT COUNT(*) AS count FROM play_campaign_rate_events
    WHERE campaign_id = ?`).get(campaignId) as { count: number };
  const projections = database.prepare(`SELECT COUNT(*) AS count FROM play_campaign_projection_events
    WHERE campaign_id = ?`).get(campaignId) as { count: number };
  const rejected = database.prepare(`SELECT rejected_rate_events FROM play_campaign_metrics
    WHERE campaign_id = ?`).get(campaignId) as { rejected_rate_events: number } | undefined;
  return {
    result: "found",
    metrics: {
      accepted_rate_events: accepted.count,
      rejected_rate_events: rejected?.rejected_rate_events ?? 0,
      projection_events: projections.count,
      uptime_ticks: 1,
    },
  };
}

export function readPlayCampaignNote(campaignId: string, noteId: string, actor: string):
  { result: "found"; note: PlayCampaignNote } | { result: "not_found" | "forbidden" } {
  const role = playCampaignActor(campaignId, actor);
  if (!role) return playCampaignOwner(campaignId) ? { result: "forbidden" } : { result: "not_found" };
  const row = database.prepare("SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?")
    .get(campaignId, noteId);
  if (!row) return { result: "not_found" };
  const note = noteFromRow(row);
  if (role !== "dm" && note.visibility === "private" && note.owner !== actor) return { result: "forbidden" };
  return { result: "found", note };
}

export function updatePlayCampaignNote(campaignId: string, noteId: string, actor: string, update: Pick<PlayCampaignNote, "text" | "visibility">):
  { result: "updated"; note: PlayCampaignNote } | { result: "not_found" | "forbidden" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  if (!isPlayCampaignMember(campaignId, actor)) return { result: "forbidden" };
  const note = database.prepare("SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?").get(campaignId, noteId);
  if (!note) return { result: "not_found" };
  if (noteFromRow(note).owner !== actor) return { result: "forbidden" };
  database.prepare("UPDATE play_campaign_notes SET text = ?, visibility = ? WHERE campaign_id = ? AND note_id = ?")
    .run(update.text, update.visibility, campaignId, noteId);
  return { result: "updated", note: { note_id: noteId, ...update, owner: actor } };
}

export function createPlayCampaignWhisper(campaignId: string, actor: string, whisper: Omit<PlayCampaignWhisper, "from_character_id">):
  { result: "created"; whisper: PlayCampaignWhisper } | { result: "not_found" | "forbidden" | "invalid" | "conflict" } {
  if (!playCampaignOwner(campaignId)) return { result: "not_found" };
  const sender = database.prepare("SELECT character_id FROM play_campaign_character_owners WHERE campaign_id = ? AND owner = ?").get(campaignId, actor) as { character_id: string } | undefined;
  if (!sender) return isPlayCampaignMember(campaignId, actor) ? { result: "invalid" } : { result: "forbidden" };
  const recipient = database.prepare("SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?").get(campaignId, whisper.to_character_id);
  if (!recipient) return { result: "invalid" };
  const created = { ...whisper, from_character_id: sender.character_id };
  try {
    database.prepare("INSERT INTO play_campaign_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text) VALUES (?, ?, ?, ?, ?)")
      .run(campaignId, created.whisper_id, created.from_character_id, created.to_character_id, created.text);
    return { result: "created", whisper: created };
  } catch { return { result: "conflict" }; }
}

export function readPlayCampaignWhispers(campaignId: string, actor: string):
  { result: "found"; whispers: PlayCampaignWhisper[] } | { result: "not_found" | "forbidden" } {
  const role = playCampaignActor(campaignId, actor);
  if (!role) return playCampaignOwner(campaignId) ? { result: "forbidden" } : { result: "not_found" };
  const member = database.prepare("SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?").get(campaignId, actor) as { character_id: string } | undefined;
  const whispers = database.prepare(`SELECT whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers WHERE campaign_id = ?
    ${role === "dm" ? "" : "AND (from_character_id = ? OR to_character_id = ?)"} ORDER BY rowid ASC`)
    .all(...(role === "dm" ? [campaignId] : [campaignId, member!.character_id, member!.character_id])) as PlayCampaignWhisper[];
  return { result: "found", whispers };
}

export function readPlayCampaignCharacterSheet(campaignId: string, characterId: string, actor: string):
  { result: "found"; sheet: PlayCampaignCharacterSheet } | { result: "not_found" | "forbidden" } {
  const role = playCampaignActor(campaignId, actor);
  if (!role) return playCampaignOwner(campaignId) ? { result: "forbidden" } : { result: "not_found" };
  const member = database.prepare("SELECT username AS owner, character_id, name, class FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?").get(campaignId, characterId) as { owner: string; character_id: string; name: string; class: string } | undefined;
  if (!member) return { result: "not_found" };
  if (role !== "dm" && member.owner !== actor) return { result: "forbidden" };
  // Privacy controls expose the deterministic basic sheet, not mutable build or
  // progression state that may have been established by earlier play endpoints.
  return { result: "found", sheet: { ...member, level: 1, proficiency_bonus: 2, hp_max: 10, armor_class: 10 } };
}
