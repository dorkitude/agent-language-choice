/**
 * Shared types, row lookups, and auth/turn helpers for the `/v1/play/*`
 * surface. Every submodule in this directory (campaign-turns, scenes,
 * locations, combat, characters) imports from here rather than duplicating
 * these lookups, so a schema or auth-rule change only needs to happen once.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { getUserRole } from '../auth.ts';
import { isValidIntInRange } from '../../validation.ts';

export interface Actor {
  username: string;
  role: 'dm' | 'player';
}

export interface PlayCampaignRow {
  id: string;
  name: string;
  owner: string;
  status: string;
  current_actor: string | null;
  turn_number: number | null;
  turn_nudge_count: number;
  story: string;
  dm_notes: string;
  max_players: number;
  current_scene_id: string | null;
  current_location_id: string | null;
  phase: string | null;
}

export interface SceneRow {
  campaign_id: string;
  id: string;
  name: string;
  status: string;
}

export type MemberRow = {
  username: string;
  character_id: string;
  name: string;
  class: string;
  hp_current: number;
  hp_max: number;
  status: string;
  death_save_successes: number;
  death_save_failures: number;
  level: number;
  con_modifier: number;
  str_modifier: number;
  dex_modifier: number;
  int_modifier: number;
  wis_modifier: number;
  cha_modifier: number;
  gold: number;
};

export type EventRow = {
  sequence: number;
  kind: string;
  actor: string;
  text: string;
};

export interface LocationRow {
  campaign_id: string;
  id: string;
  name: string;
}

export interface EncounterRow {
  campaign_id: string;
  id: string;
  name: string;
  status: string;
  combatants_json: string;
  party_combatants_json: string;
  round: number;
  turn_index: number;
  conditions_json: string;
  order_override_json: string | null;
  rewards_json: string | null;
  xp_awarded: number;
}

export interface Monster {
  monster_id: string;
  name: string;
  hp_max: number;
  initiative: number;
  hp_current: number;
}

export interface PartyCombatant {
  member: string;
  character_id: string;
  name: string;
  initiative: number;
}

export interface TurnCombatant {
  name: string;
  kind: 'monster' | 'player';
  initiative: number;
  member?: string;
  monsterId?: string;
}

export interface ConditionEntry {
  condition: string;
  remaining_rounds: number;
}

export type ConditionsMap = Record<string, ConditionEntry[]>;

export interface LootEntry {
  slug: string;
  quantity: number;
}

const BEARER_RE = /^Bearer session-(.+)$/;

// Number of nudges a turn tolerates before it is considered overdue. Purely
// logical/turn-based — never derived from wall-clock time.
export const TURN_DEADLINE_NUDGES = 3;

export function authenticate(authHeader: string | undefined): Actor | ApiResult {
  if (typeof authHeader !== 'string') {
    return { status: 401, body: { error: 'missing bearer token' } };
  }
  const match = BEARER_RE.exec(authHeader);
  if (!match) {
    return { status: 401, body: { error: 'invalid bearer token' } };
  }
  const username = match[1];
  const role = getUserRole(username) ?? (username === 'dm' ? 'dm' : 'player');
  return { username, role };
}

export function isActor(value: Actor | ApiResult): value is Actor {
  return 'username' in value;
}

// Row types (e.g. PlayCampaignRow) also have a `status` field, so disambiguate
// on `body`, which only ApiResult carries.
export function isApiResult(value: unknown): value is ApiResult {
  return typeof value === 'object' && value !== null && 'body' in value;
}

const NOT_FOUND: ApiResult = { status: 404, body: { error: 'play campaign not found' } };

export function findCampaign(db: ReturnType<typeof getDb>, campaignId: string): PlayCampaignRow | ApiResult {
  const campaign = db
    .prepare(
      'SELECT id, name, owner, status, current_actor, turn_number, turn_nudge_count, story, dm_notes, max_players, current_scene_id, current_location_id, phase FROM play_campaigns WHERE id = ?',
    )
    .get(campaignId) as PlayCampaignRow | undefined;
  return campaign ?? NOT_FOUND;
}

const SCENE_NOT_FOUND: ApiResult = { status: 404, body: { error: 'scene not found' } };

export function findScene(db: ReturnType<typeof getDb>, campaignId: string, sceneId: string): SceneRow | ApiResult {
  const scene = db
    .prepare('SELECT campaign_id, id, name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?')
    .get(campaignId, sceneId) as SceneRow | undefined;
  return scene ?? SCENE_NOT_FOUND;
}

const MEMBER_COLUMNS =
  'username, character_id, name, class, hp_current, hp_max, status, death_save_successes, death_save_failures, level, con_modifier, str_modifier, dex_modifier, int_modifier, wis_modifier, cha_modifier, gold';

export function listMembers(db: ReturnType<typeof getDb>, campaignId: string): MemberRow[] {
  return db
    .prepare(`SELECT ${MEMBER_COLUMNS} FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid ASC`)
    .all(campaignId) as MemberRow[];
}

const CHARACTER_NOT_FOUND: ApiResult = { status: 404, body: { error: 'character not found' } };

export function findMemberByCharacterId(
  db: ReturnType<typeof getDb>,
  campaignId: string,
  characterId: string,
): MemberRow | ApiResult {
  const member = db
    .prepare(`SELECT ${MEMBER_COLUMNS} FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?`)
    .get(campaignId, characterId) as MemberRow | undefined;
  return member ?? CHARACTER_NOT_FOUND;
}

export function isMember(db: ReturnType<typeof getDb>, campaignId: string, username: string): boolean {
  return (
    db
      .prepare('SELECT username FROM play_campaign_members WHERE campaign_id = ? AND username = ?')
      .get(campaignId, username) !== undefined
  );
}

// Owner or roster member may view campaign-scoped data; anyone else is forbidden.
export function requireParticipant(
  db: ReturnType<typeof getDb>,
  campaign: PlayCampaignRow,
  actor: Actor,
  forbiddenMessage: string,
): ApiResult | null {
  if (campaign.owner === actor.username) return null;
  if (isMember(db, campaign.id, actor.username)) return null;
  return { status: 403, body: { error: forbiddenMessage } };
}

export function nextSequence(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_events WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

export function nextTransferId(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare(
      'SELECT COALESCE(MAX(transfer_id), 0) AS max_transfer_id FROM play_campaign_currency_transfers WHERE campaign_id = ?',
    )
    .get(campaignId) as { max_transfer_id: number };
  return row.max_transfer_id + 1;
}

export function insertEvent(
  db: ReturnType<typeof getDb>,
  campaignId: string,
  sequence: number,
  kind: string,
  actor: string,
  text: string,
  actionType?: string,
): void {
  db.prepare(
    'INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text, action_type) VALUES (?, ?, ?, ?, ?, ?)',
  ).run(campaignId, sequence, kind, actor, text, actionType ?? null);
}

export function recentEvents(db: ReturnType<typeof getDb>, campaignId: string, limit?: number): EventRow[] {
  const sql = limit
    ? 'SELECT sequence, kind, actor, text FROM play_campaign_events WHERE campaign_id = ? ORDER BY sequence DESC LIMIT ?'
    : 'SELECT sequence, kind, actor, text FROM play_campaign_events WHERE campaign_id = ? ORDER BY sequence ASC';
  const rows = (limit ? db.prepare(sql).all(campaignId, limit) : db.prepare(sql).all(campaignId)) as EventRow[];
  return limit ? rows.slice().reverse() : rows;
}

export function requireNonEmptyString(value: unknown, field: string): string | ApiResult {
  if (typeof value !== 'string' || value.length === 0) {
    return { status: 400, body: { error: `${field} must be a non-empty string` } };
  }
  return value;
}

export function findLocation(
  db: ReturnType<typeof getDb>,
  campaignId: string,
  locationId: string,
): LocationRow | undefined {
  return db
    .prepare('SELECT campaign_id, id, name FROM play_campaign_locations WHERE campaign_id = ? AND id = ?')
    .get(campaignId, locationId) as LocationRow | undefined;
}

const ENCOUNTER_NOT_FOUND: ApiResult = { status: 404, body: { error: 'encounter not found' } };

export function findEncounter(
  db: ReturnType<typeof getDb>,
  campaignId: string,
  encounterId: string,
): EncounterRow | ApiResult {
  const encounter = db
    .prepare(
      'SELECT campaign_id, id, name, status, combatants_json, party_combatants_json, round, turn_index, conditions_json, order_override_json, rewards_json, xp_awarded FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?',
    )
    .get(campaignId, encounterId) as EncounterRow | undefined;
  return encounter ?? ENCOUNTER_NOT_FOUND;
}

// Combined initiative order (monsters + bound party members), highest
// initiative first. Array.prototype.sort is stable, so ties keep the order
// combatants were added in, which keeps this deterministic across calls.
export function buildInitiativeOrder(encounter: EncounterRow): TurnCombatant[] {
  const monsters = JSON.parse(encounter.combatants_json) as Monster[];
  const partyCombatants = JSON.parse(encounter.party_combatants_json) as PartyCombatant[];
  const combined: TurnCombatant[] = [
    ...monsters.map((m) => ({ name: m.name, kind: 'monster' as const, initiative: m.initiative, monsterId: m.monster_id })),
    ...partyCombatants.map((c) => ({ name: c.name, kind: 'player' as const, initiative: c.initiative, member: c.member })),
  ];
  combined.sort((a, b) => b.initiative - a.initiative);

  if (!encounter.order_override_json) return combined;

  // A prior delay call pinned an explicit order (by combatant key). Combatants
  // added since then fall back to their initiative-sorted position, appended
  // after the pinned ones.
  const overrideKeys = JSON.parse(encounter.order_override_json) as string[];
  const byKey = new Map(combined.map((c) => [combatantKey(c), c]));
  const ordered: TurnCombatant[] = [];
  for (const key of overrideKeys) {
    const combatant = byKey.get(key);
    if (combatant) {
      ordered.push(combatant);
      byKey.delete(key);
    }
  }
  for (const combatant of combined) {
    if (byKey.has(combatantKey(combatant))) {
      ordered.push(combatant);
    }
  }
  return ordered;
}

// Identifies a combatant for condition tracking: a monster's monster_id, or
// a bound player's campaign member username.
export function combatantKey(combatant: TurnCombatant): string {
  return combatant.kind === 'player' ? (combatant.member as string) : (combatant.monsterId as string);
}

export function parseConditions(encounter: EncounterRow): ConditionsMap {
  return JSON.parse(encounter.conditions_json) as ConditionsMap;
}

export function encounterHasTarget(encounter: EncounterRow, target: string): boolean {
  const monsters = JSON.parse(encounter.combatants_json) as Monster[];
  const partyCombatants = JSON.parse(encounter.party_combatants_json) as PartyCombatant[];
  return monsters.some((m) => m.monster_id === target) || partyCombatants.some((c) => c.member === target);
}

export function activeCombatantBody(round: number, turnIndex: number, combatant: TurnCombatant): JsonValue {
  return {
    round,
    turn_index: turnIndex,
    active: { name: combatant.name, kind: combatant.kind, initiative: combatant.initiative },
  } as unknown as JsonValue;
}

export function findMonsterTarget(
  encounter: EncounterRow,
  target: string,
): { monsters: Monster[]; monster: Monster } | ApiResult {
  const monsters = JSON.parse(encounter.combatants_json) as Monster[];
  const monster = monsters.find((m) => m.monster_id === target);
  if (!monster) {
    return { status: 404, body: { error: 'target not found' } };
  }
  return { monsters, monster };
}

export function resolveCharacterOwner(
  db: ReturnType<typeof getDb>,
  campaignId: string,
  characterId: string,
): string | null {
  const claimed = db
    .prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?')
    .get(campaignId, characterId) as { owner: string } | undefined;
  if (claimed) return claimed.owner;

  const member = db
    .prepare('SELECT username FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?')
    .get(campaignId, characterId) as { username: string } | undefined;
  return member ? member.username : null;
}

// Reverse of resolveCharacterOwner: the character currently owned by a given
// campaign member, if any. Prefers an explicit transfer record over the
// member's default (as-joined) character, and treats a default character as
// no-longer-owned once it has been transferred away.
export function resolveOwnedCharacterId(
  db: ReturnType<typeof getDb>,
  campaignId: string,
  username: string,
): string | null {
  const claimed = db
    .prepare(
      'SELECT character_id FROM play_campaign_character_owners WHERE campaign_id = ? AND owner = ? ORDER BY rowid DESC LIMIT 1',
    )
    .get(campaignId, username) as { character_id: string } | undefined;
  if (claimed) return claimed.character_id;

  const member = db
    .prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?')
    .get(campaignId, username) as { character_id: string } | undefined;
  if (!member) return null;

  const transfer = db
    .prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?')
    .get(campaignId, member.character_id) as { owner: string } | undefined;
  if (transfer && transfer.owner !== username) return null;

  return member.character_id;
}

export type MetricCounter = 'accepted_rate_events' | 'rejected_rate_events' | 'projection_events';

export function incrementMetric(db: ReturnType<typeof getDb>, campaignId: string, counter: MetricCounter): void {
  db.prepare('INSERT OR IGNORE INTO play_campaign_metrics (campaign_id) VALUES (?)').run(campaignId);
  db.prepare(`UPDATE play_campaign_metrics SET ${counter} = ${counter} + 1 WHERE campaign_id = ?`).run(campaignId);
}

export function parseLoot(value: unknown): LootEntry[] | ApiResult {
  if (!Array.isArray(value)) {
    return { status: 400, body: { error: 'loot must be an array' } };
  }
  const loot: LootEntry[] = [];
  for (const entry of value) {
    const item = entry as JsonValue;
    const slug = item?.slug;
    if (typeof slug !== 'string' || slug.length === 0) {
      return { status: 400, body: { error: 'loot entries require a slug' } };
    }
    if (!isValidIntInRange(item?.quantity, 1, Number.MAX_SAFE_INTEGER)) {
      return { status: 400, body: { error: 'loot entries require a positive integer quantity' } };
    }
    loot.push({ slug, quantity: item.quantity as number });
  }
  return loot;
}
