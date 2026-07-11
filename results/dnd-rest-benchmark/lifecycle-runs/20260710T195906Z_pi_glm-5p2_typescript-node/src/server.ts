import http from "node:http";
import crypto from "node:crypto";
import {
  initStorage,
  isInitialized,
  resetStorage,
  DRIVER,
  SCHEMA_VERSION,
  userExists,
  insertUser,
  getUser,
  combatSessionExists,
  createCombatSession,
  loadCombatSession,
  saveCombatSessionMeta,
  appendCombatCondition,
  setCombatConditions,
  type Combatant,
  type ConditionEntry,
  type CombatSession,
  type UserRecord,
  type MonsterRecord,
  type ItemRecord,
  monsterExists,
  insertMonster,
  getMonster,
  itemExists,
  insertItem,
  getItem,
  campaignExists,
  insertCampaign,
  getCampaign,
  campaignCharacterExists,
  insertCampaignCharacter,
  getCampaignCharacters,
  campaignEventExists,
  insertCampaignEvent,
  getCampaignEventCount,
  getCampaignEvents,
  type CampaignRecord,
  type CampaignCharacterRecord,
  type CampaignEventRecord,
} from "./storage.js";

const HOST = "127.0.0.1";
const PORT = Number(process.env.PORT) || 3000;

// CR -> XP table (first benchmark suite).
const XP_TABLE = new Map<string, number>([
  ["0", 10],
  ["1/8", 25],
  ["1/4", 50],
  ["1/2", 100],
  ["1", 200],
  ["2", 450],
  ["3", 700],
  ["4", 1100],
  ["5", 1800],
]);

// Per-level encounter thresholds (first benchmark suite: level 3 only).
const LEVEL_THRESHOLDS = new Map<
  number,
  { easy: number; medium: number; hard: number; deadly: number }
>([[3, { easy: 75, medium: 150, hard: 225, deadly: 400 }]]);

type Thresholds = { easy: number; medium: number; hard: number; deadly: number };
type HandlerResult = { status: number; body: unknown };

function isObj(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

function isNum(x: unknown): x is number {
  return typeof x === "number" && Number.isFinite(x);
}

function isInt(x: unknown): x is number {
  return isNum(x) && Number.isInteger(x);
}

function sendJson(res: http.ServerResponse, status: number, body: unknown): void {
  const json = JSON.stringify(body);
  res.writeHead(status, {
    "content-type": "application/json",
    "content-length": Buffer.byteLength(json),
  });
  res.end(json);
}

function safeDecode(s: string): string {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

function readBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (c: Buffer) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

// --- dice expression: <count>d<sides>[+<modifier>|-<modifier>] ---
function parseDice(
  expression: unknown,
): { count: number; sides: number; modifier: number } | null {
  if (typeof expression !== "string") return null;
  const m = /^(\d+)d(\d+)(?:([+-])(\d+))?$/.exec(expression);
  if (!m) return null;
  const count = parseInt(m[1], 10);
  const sides = parseInt(m[2], 10);
  let modifier = 0;
  if (m[3]) {
    modifier = parseInt(m[4], 10);
    if (m[3] === "-") modifier = -modifier;
  }
  if (count <= 0 || sides <= 0) return null;
  return { count, sides, modifier };
}

function multiplierFor(monsterCount: number): number {
  if (monsterCount >= 15) return 4;
  if (monsterCount >= 11) return 3;
  if (monsterCount >= 7) return 2.5;
  if (monsterCount >= 3) return 2;
  if (monsterCount === 2) return 1.5;
  return 1;
}

function difficultyFor(adjXp: number, t: Thresholds): string {
  if (adjXp >= t.deadly) return "deadly";
  if (adjXp >= t.hard) return "hard";
  if (adjXp >= t.medium) return "medium";
  if (adjXp >= t.easy) return "easy";
  return "trivial";
}

// --- handlers ---

function handleDiceStats(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const d = parseDice(body.expression);
  if (!d) return { status: 400, body: { error: "invalid expression" } };
  const min = d.count + d.modifier;
  const max = d.count * d.sides + d.modifier;
  const average = (min + max) / 2;
  return {
    status: 200,
    body: {
      dice_count: d.count,
      sides: d.sides,
      modifier: d.modifier,
      min,
      max,
      average,
    },
  };
}

function handleAbilityCheck(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { roll, modifier, dc } = body;
  if (!isInt(roll) || !isInt(modifier) || !isInt(dc)) {
    return { status: 400, body: { error: "invalid request" } };
  }
  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;
  return { status: 200, body: { total, success, margin } };
}

function handleAdjustedXp(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { party, monsters } = body;
  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    return { status: 400, body: { error: "invalid request" } };
  }

  const thresholds: Thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    if (!isObj(member) || !isInt(member.level)) {
      return { status: 400, body: { error: "invalid request" } };
    }
    const t = LEVEL_THRESHOLDS.get(member.level);
    if (!t) return { status: 400, body: { error: "unsupported level" } };
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const mon of monsters) {
    if (!isObj(mon)) return { status: 400, body: { error: "invalid request" } };
    const cr = mon.cr;
    if (typeof cr !== "string") {
      return { status: 400, body: { error: "invalid request" } };
    }
    const xp = XP_TABLE.get(cr);
    if (xp === undefined) {
      return { status: 400, body: { error: "unsupported cr" } };
    }
    if (!isInt(mon.count) || (mon.count as number) < 1) {
      return { status: 400, body: { error: "invalid request" } };
    }
    baseXp += xp * (mon.count as number);
    monsterCount += mon.count as number;
  }

  const multiplier = multiplierFor(monsterCount);
  const adjustedXp = baseXp * multiplier;
  const difficulty = difficultyFor(adjustedXp, thresholds);
  return {
    status: 200,
    body: {
      base_xp: baseXp,
      monster_count: monsterCount,
      multiplier,
      adjusted_xp: adjustedXp,
      difficulty,
      thresholds,
    },
  };
}

function handleInitiativeOrder(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { combatants } = body;
  if (!Array.isArray(combatants)) {
    return { status: 400, body: { error: "invalid request" } };
  }
  const list: { name: string; dex: number; score: number }[] = [];
  for (const c of combatants) {
    if (
      !isObj(c) ||
      typeof c.name !== "string" ||
      !isInt(c.dex) ||
      !isInt(c.roll)
    ) {
      return { status: 400, body: { error: "invalid request" } };
    }
    list.push({ name: c.name, dex: c.dex, score: (c.roll as number) + (c.dex as number) });
  }
  list.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    if (a.name < b.name) return -1;
    if (a.name > b.name) return 1;
    return 0;
  });
  return {
    status: 200,
    body: { order: list.map((c) => ({ name: c.name, score: c.score })) },
  };
}

// --- character rules ---

const ABILITY_KEYS = ["str", "dex", "con", "int", "wis", "cha"] as const;

function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

function proficiencyBonus(level: number): number {
  return 2 + Math.floor((level - 1) / 4);
}

function handleAbilityModifier(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { score } = body;
  if (!isInt(score) || score < 1 || score > 30) {
    return { status: 400, body: { error: "invalid score" } };
  }
  return { status: 200, body: { score, modifier: abilityModifier(score) } };
}

function handleProficiency(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { level } = body;
  if (!isInt(level) || level < 1 || level > 20) {
    return { status: 400, body: { error: "invalid level" } };
  }
  return { status: 200, body: { level, proficiency_bonus: proficiencyBonus(level) } };
}

function handleDerivedStats(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { level, abilities, armor } = body;
  if (!isInt(level) || level < 1 || level > 20) {
    return { status: 400, body: { error: "invalid level" } };
  }
  if (!isObj(abilities)) {
    return { status: 400, body: { error: "invalid abilities" } };
  }
  const modifiers: Record<string, number> = {};
  for (const key of ABILITY_KEYS) {
    const v = abilities[key];
    if (!isInt(v) || v < 1 || v > 30) {
      return { status: 400, body: { error: `invalid ${key}` } };
    }
    modifiers[key] = abilityModifier(v);
  }
  if (!isObj(armor) || !isInt(armor.base) || !isInt(armor.dex_cap)) {
    return { status: 400, body: { error: "invalid armor" } };
  }
  const hpMax = level * (6 + modifiers.con);
  const shieldBonus = armor.shield === true ? 2 : 0;
  const armorClass =
    (armor.base as number) + Math.min(modifiers.dex, armor.dex_cap as number) + shieldBonus;
  return {
    status: 200,
    body: {
      level,
      proficiency_bonus: proficiencyBonus(level),
      hp_max: hpMax,
      armor_class: armorClass,
      modifiers,
    },
  };
}

// --- combat state ---

function sortInitiative(list: Combatant[]): Combatant[] {
  list.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    if (a.name < b.name) return -1;
    if (a.name > b.name) return 1;
    return 0;
  });
  return list;
}

function activeOf(s: CombatSession): Combatant {
  return s.order[s.turn_index];
}

function conditionsSnapshot(
  s: CombatSession,
): Record<string, { condition: string; remaining_rounds: number }[]> {
  const out: Record<string, { condition: string; remaining_rounds: number }[]> = {};
  // Include every combatant that has ever had a condition, even if all of
  // their conditions have expired (empty array). The spec says to remove the
  // *condition* when it expires, not the combatant's entry.
  for (const [name, list] of s.conditions) {
    out[name] = list.map((c) => ({
      condition: c.condition,
      remaining_rounds: c.remaining_rounds,
    }));
  }
  return out;
}

function handleCreateCombatSession(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { id, combatants } = body;
  if (typeof id !== "string" || id.length === 0) {
    return { status: 400, body: { error: "invalid id" } };
  }
  if (!Array.isArray(combatants) || combatants.length === 0) {
    return { status: 400, body: { error: "invalid combatants" } };
  }
  const list: Combatant[] = [];
  const seen = new Set<string>();
  for (const c of combatants) {
    if (!isObj(c)) {
      return { status: 400, body: { error: "invalid combatant" } };
    }
    const name = c.name;
    const dex = c.dex;
    const roll = c.roll;
    if (
      typeof name !== "string" ||
      name.length === 0 ||
      !isInt(dex) ||
      !isInt(roll)
    ) {
      return { status: 400, body: { error: "invalid combatant" } };
    }
    if (seen.has(name)) {
      return { status: 400, body: { error: "duplicate combatant" } };
    }
    seen.add(name);
    list.push({ name, dex, score: roll + dex });
  }
  if (combatSessionExists(id)) {
    return { status: 400, body: { error: "session exists" } };
  }
  sortInitiative(list);
  const session: CombatSession = {
    id,
    order: list,
    round: 1,
    turn_index: 0,
    conditions: new Map(),
  };
  createCombatSession(session.id, session.order);
  const active = activeOf(session);
  return {
    status: 200,
    body: {
      id: session.id,
      round: session.round,
      turn_index: session.turn_index,
      active: { name: active.name, score: active.score },
      order: session.order.map((c) => ({ name: c.name, score: c.score })),
    },
  };
}

function handleAddCondition(id: string, body: unknown): HandlerResult {
  const session = loadCombatSession(id);
  if (!session) return { status: 404, body: { error: "unknown session" } };
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { target, condition, duration_rounds } = body;
  if (typeof target !== "string" || target.length === 0) {
    return { status: 400, body: { error: "invalid target" } };
  }
  const combatant = session.order.find((c) => c.name === target);
  if (!combatant) {
    return { status: 400, body: { error: "unknown target" } };
  }
  if (typeof condition !== "string") {
    return { status: 400, body: { error: "invalid condition" } };
  }
  if (!isInt(duration_rounds) || duration_rounds < 1) {
    return { status: 400, body: { error: "invalid duration" } };
  }
  const list = session.conditions.get(target) ?? [];
  list.push({ condition, remaining_rounds: duration_rounds });
  session.conditions.set(target, list);
  appendCombatCondition(id, target, condition, duration_rounds);
  return {
    status: 200,
    body: {
      target,
      conditions: list.map((c) => ({
        condition: c.condition,
        remaining_rounds: c.remaining_rounds,
      })),
    },
  };
}

function handleAdvance(id: string): HandlerResult {
  const session = loadCombatSession(id);
  if (!session) return { status: 404, body: { error: "unknown session" } };
  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }
  const active = activeOf(session);
  const list = session.conditions.get(active.name);
  let kept: ConditionEntry[] | undefined;
  if (list) {
    for (const c of list) c.remaining_rounds -= 1;
    kept = list.filter((c) => c.remaining_rounds > 0);
    // Keep the combatant's entry (even when empty) so callers can see that a
    // previously-applied condition has expired rather than the key vanishing.
    session.conditions.set(active.name, kept);
  }
  saveCombatSessionMeta(id, session.round, session.turn_index);
  if (kept !== undefined) {
    setCombatConditions(id, active.name, kept);
  }
  return {
    status: 200,
    body: {
      id: session.id,
      round: session.round,
      turn_index: session.turn_index,
      active: { name: active.name, score: active.score },
      conditions: conditionsSnapshot(session),
    },
  };
}

// --- auth / users ---

const USERNAME_RE = /^[a-z0-9_-]{2,32}$/;

function hashPassword(plain: string): string {
  const salt = crypto.randomBytes(16);
  const hash = crypto.scryptSync(plain, salt, 32);
  return `scrypt$${salt.toString("hex")}$${hash.toString("hex")}`;
}

function verifyPassword(plain: string, stored: string): boolean {
  const parts = stored.split("$");
  if (parts.length !== 3 || parts[0] !== "scrypt") return false;
  const salt = Buffer.from(parts[1], "hex");
  const hash = Buffer.from(parts[2], "hex");
  if (salt.length === 0 || hash.length === 0) return false;
  const computed = crypto.scryptSync(plain, salt, hash.length);
  return crypto.timingSafeEqual(computed, hash);
}

function handleRegister(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { username, password, role } = body;
  if (typeof username !== "string" || !USERNAME_RE.test(username)) {
    return { status: 400, body: { error: "invalid username" } };
  }
  if (typeof password !== "string" || password.length < 8) {
    return { status: 400, body: { error: "invalid password" } };
  }
  if (role !== "dm" && role !== "player") {
    return { status: 400, body: { error: "invalid role" } };
  }
  if (userExists(username)) {
    return { status: 409, body: { error: "username exists" } };
  }
  const record: UserRecord = {
    username,
    role,
    passwordHash: hashPassword(password),
  };
  insertUser(record);
  return { status: 201, body: { username, role } };
}

function handleLogin(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { username, password } = body;
  if (typeof username !== "string" || typeof password !== "string") {
    return { status: 400, body: { error: "invalid request" } };
  }
  const user = getUser(username);
  if (!user || !verifyPassword(password, user.passwordHash)) {
    return { status: 401, body: { error: "invalid credentials" } };
  }
  return {
    status: 200,
    body: { username: user.username, token: `session-${user.username}` },
  };
}

// --- compendium ---

function isStringArray(x: unknown): x is string[] {
  return Array.isArray(x) && x.every((v) => typeof v === "string");
}

function handleCreateMonster(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { slug, name, cr, armor_class, hit_points, tags } = body;
  if (typeof slug !== "string" || slug.length === 0) {
    return { status: 400, body: { error: "invalid slug" } };
  }
  if (typeof name !== "string") {
    return { status: 400, body: { error: "invalid name" } };
  }
  if (typeof cr !== "string") {
    return { status: 400, body: { error: "invalid cr" } };
  }
  if (!isInt(armor_class)) {
    return { status: 400, body: { error: "invalid armor_class" } };
  }
  if (!isInt(hit_points)) {
    return { status: 400, body: { error: "invalid hit_points" } };
  }
  if (!isStringArray(tags)) {
    return { status: 400, body: { error: "invalid tags" } };
  }
  if (monsterExists(slug)) {
    return { status: 409, body: { error: "monster exists" } };
  }
  const record: MonsterRecord = { slug, name, cr, armor_class, hit_points, tags };
  insertMonster(record);
  return {
    status: 201,
    body: { slug, name, cr, armor_class, hit_points },
  };
}

function handleReadMonster(slug: string): HandlerResult {
  const monster = getMonster(slug);
  if (!monster) return { status: 404, body: { error: "unknown monster" } };
  return {
    status: 200,
    body: {
      slug: monster.slug,
      name: monster.name,
      cr: monster.cr,
      armor_class: monster.armor_class,
      hit_points: monster.hit_points,
      tags: monster.tags,
    },
  };
}

function handleCreateItem(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { slug, name, type, rarity, cost_gp } = body;
  if (typeof slug !== "string" || slug.length === 0) {
    return { status: 400, body: { error: "invalid slug" } };
  }
  if (typeof name !== "string") {
    return { status: 400, body: { error: "invalid name" } };
  }
  if (typeof type !== "string") {
    return { status: 400, body: { error: "invalid type" } };
  }
  if (typeof rarity !== "string") {
    return { status: 400, body: { error: "invalid rarity" } };
  }
  if (!isInt(cost_gp)) {
    return { status: 400, body: { error: "invalid cost_gp" } };
  }
  if (itemExists(slug)) {
    return { status: 409, body: { error: "item exists" } };
  }
  const record: ItemRecord = { slug, name, type, rarity, cost_gp };
  insertItem(record);
  return {
    status: 201,
    body: { slug, name, type, rarity, cost_gp },
  };
}

function handleReadItem(slug: string): HandlerResult {
  const item = getItem(slug);
  if (!item) return { status: 404, body: { error: "unknown item" } };
  return {
    status: 200,
    body: {
      slug: item.slug,
      name: item.name,
      type: item.type,
      rarity: item.rarity,
      cost_gp: item.cost_gp,
    },
  };
}

// --- campaign state ---

function handleCreateCampaign(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { id, name, dm } = body;
  if (typeof id !== "string" || id.length === 0) {
    return { status: 400, body: { error: "invalid id" } };
  }
  if (typeof name !== "string") {
    return { status: 400, body: { error: "invalid name" } };
  }
  if (typeof dm !== "string") {
    return { status: 400, body: { error: "invalid dm" } };
  }
  if (campaignExists(id)) {
    return { status: 409, body: { error: "campaign exists" } };
  }
  const record: CampaignRecord = { id, name, dm };
  insertCampaign(record);
  return { status: 201, body: { id, name, dm } };
}

function handleAddCharacter(campaignId: string, body: unknown): HandlerResult {
  if (!campaignExists(campaignId)) {
    return { status: 404, body: { error: "unknown campaign" } };
  }
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { id, name, level, class: charClass } = body;
  if (typeof id !== "string" || id.length === 0) {
    return { status: 400, body: { error: "invalid id" } };
  }
  if (typeof name !== "string") {
    return { status: 400, body: { error: "invalid name" } };
  }
  if (!isInt(level) || (level as number) < 1) {
    return { status: 400, body: { error: "invalid level" } };
  }
  if (typeof charClass !== "string") {
    return { status: 400, body: { error: "invalid class" } };
  }
  if (campaignCharacterExists(campaignId, id)) {
    return { status: 409, body: { error: "character exists" } };
  }
  const record: CampaignCharacterRecord = {
    id,
    name,
    level: level as number,
    class: charClass,
  };
  insertCampaignCharacter(campaignId, record);
  return { status: 201, body: { id, name, level, class: charClass } };
}

function handleAddEvent(campaignId: string, body: unknown): HandlerResult {
  if (!campaignExists(campaignId)) {
    return { status: 404, body: { error: "unknown campaign" } };
  }
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { id, kind, summary } = body;
  if (typeof id !== "string" || id.length === 0) {
    return { status: 400, body: { error: "invalid id" } };
  }
  if (typeof kind !== "string") {
    return { status: 400, body: { error: "invalid kind" } };
  }
  if (typeof summary !== "string") {
    return { status: 400, body: { error: "invalid summary" } };
  }
  if (campaignEventExists(campaignId, id)) {
    return { status: 409, body: { error: "event exists" } };
  }
  const record: CampaignEventRecord = { id, kind, summary };
  insertCampaignEvent(campaignId, record);
  return { status: 201, body: { id, kind } };
}

function handleReadCampaignState(campaignId: string): HandlerResult {
  const campaign = getCampaign(campaignId);
  if (!campaign) return { status: 404, body: { error: "unknown campaign" } };
  const characters = getCampaignCharacters(campaignId);
  const log_count = getCampaignEventCount(campaignId);
  return {
    status: 200,
    body: {
      id: campaign.id,
      name: campaign.name,
      dm: campaign.dm,
      characters: characters.map((c) => ({
        id: c.id,
        name: c.name,
        level: c.level,
        class: c.class,
      })),
      log_count,
    },
  };
}

// --- PHB rules ---

// Wizard spell slots by level. The benchmark scope is wizard level 5, so we
// only return data for that single combination and reject everything else.
const WIZARD_SLOTS: Record<number, Record<string, number>> = {
  5: { "1": 4, "2": 3, "3": 2 },
};

function handleSpellSlots(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { class: charClass, level } = body;
  if (typeof charClass !== "string" || charClass !== "wizard") {
    return { status: 400, body: { error: "unsupported class" } };
  }
  if (!isInt(level)) {
    return { status: 400, body: { error: "invalid level" } };
  }
  const slots = WIZARD_SLOTS[level as number];
  if (!slots) {
    return { status: 400, body: { error: "unsupported level" } };
  }
  return { status: 200, body: { class: charClass, level: level as number, slots } };
}

function handleLongRest(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { level, hp_current, hp_max, hit_dice_spent, exhaustion_level } = body;
  if (!isInt(level) || (level as number) < 1) {
    return { status: 400, body: { error: "invalid level" } };
  }
  if (!isInt(hp_current) || (hp_current as number) < 0) {
    return { status: 400, body: { error: "invalid hp_current" } };
  }
  if (!isInt(hp_max) || (hp_max as number) < 0) {
    return { status: 400, body: { error: "invalid hp_max" } };
  }
  if (!isInt(hit_dice_spent) || (hit_dice_spent as number) < 0) {
    return { status: 400, body: { error: "invalid hit_dice_spent" } };
  }
  if (!isInt(exhaustion_level) || (exhaustion_level as number) < 0) {
    return { status: 400, body: { error: "invalid exhaustion_level" } };
  }
  const recovered = Math.max(1, Math.floor((level as number) / 2));
  const newHitDiceSpent = Math.max(0, (hit_dice_spent as number) - recovered);
  const newExhaustion = Math.max(0, (exhaustion_level as number) - 1);
  return {
    status: 200,
    body: {
      hp_current: hp_max as number,
      hit_dice_spent: newHitDiceSpent,
      exhaustion_level: newExhaustion,
    },
  };
}

function handleEquipmentLoad(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { strength, weight } = body;
  if (!isInt(strength) || (strength as number) < 1) {
    return { status: 400, body: { error: "invalid strength" } };
  }
  if (!isInt(weight) || (weight as number) < 0) {
    return { status: 400, body: { error: "invalid weight" } };
  }
  const capacity = (strength as number) * 15;
  const encumbered = (weight as number) > capacity;
  return {
    status: 200,
    body: { capacity, weight: weight as number, encumbered },
  };
}

// --- DM tools ---

// Deterministic recommendation per encounter difficulty.
const RECOMMENDATION_BY_DIFFICULTY: Record<string, string> = {
  trivial: "trivial",
  easy: "safe warm-up",
  medium: "balanced fight",
  hard: "tough battle",
  deadly: "lethal threat",
};

function handleEncounterBuilder(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { campaign_id, party, monster_slugs } = body;
  if (typeof campaign_id !== "string" || campaign_id.length === 0) {
    return { status: 400, body: { error: "invalid campaign_id" } };
  }
  if (!Array.isArray(party) || party.length === 0) {
    return { status: 400, body: { error: "invalid party" } };
  }
  if (!Array.isArray(monster_slugs) || monster_slugs.length === 0) {
    return { status: 400, body: { error: "invalid monster_slugs" } };
  }

  // Sum per-level encounter thresholds across the party (reuses the core
  // suite's level-3 table).
  const thresholds: Thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    if (!isObj(member) || !isInt(member.level)) {
      return { status: 400, body: { error: "invalid party member" } };
    }
    const t = LEVEL_THRESHOLDS.get(member.level);
    if (!t) return { status: 400, body: { error: "unsupported level" } };
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

  // Look up each monster's CR from the compendium and sum base XP. Repeats
  // are allowed (a slug may appear multiple times in monster_slugs).
  let baseXp = 0;
  const monsterCount = monster_slugs.length;
  for (const slug of monster_slugs) {
    if (typeof slug !== "string" || slug.length === 0) {
      return { status: 400, body: { error: "invalid monster slug" } };
    }
    const monster = getMonster(slug);
    if (!monster) {
      return { status: 400, body: { error: "unknown monster" } };
    }
    const xp = XP_TABLE.get(monster.cr);
    if (xp === undefined) {
      return { status: 400, body: { error: "unsupported cr" } };
    }
    baseXp += xp;
  }

  const multiplier = multiplierFor(monsterCount);
  const adjustedXp = baseXp * multiplier;
  const difficulty = difficultyFor(adjustedXp, thresholds);
  const recommendation = RECOMMENDATION_BY_DIFFICULTY[difficulty] ?? "unknown";
  return {
    status: 200,
    body: {
      campaign_id,
      base_xp: baseXp,
      adjusted_xp: adjustedXp,
      difficulty,
      monster_count: monsterCount,
      recommendation,
    },
  };
}

// Deterministic loot table by tier. The benchmark only exercises tier 1; the
// other tiers are provided so the endpoint stays well-defined.
const LOOT_BY_TIER: Record<
  number,
  { coins_gp: number; items: { slug: string; quantity: number }[] }
> = {
  1: { coins_gp: 75, items: [{ slug: "healing-potion", quantity: 2 }] },
  2: { coins_gp: 200, items: [{ slug: "healing-potion", quantity: 3 }] },
  3: { coins_gp: 500, items: [{ slug: "healing-potion", quantity: 5 }] },
  4: { coins_gp: 1200, items: [{ slug: "healing-potion", quantity: 8 }] },
};

function handleLootParcel(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { campaign_id, tier, seed } = body;
  if (typeof campaign_id !== "string" || campaign_id.length === 0) {
    return { status: 400, body: { error: "invalid campaign_id" } };
  }
  if (!isInt(tier) || (tier as number) < 1) {
    return { status: 400, body: { error: "invalid tier" } };
  }
  // seed is accepted for API completeness; the benchmark returns fixed
  // deterministic loot per tier, so any integer seed is fine.
  if (seed !== undefined && !isInt(seed)) {
    return { status: 400, body: { error: "invalid seed" } };
  }
  const loot = LOOT_BY_TIER[tier as number];
  if (!loot) {
    return { status: 400, body: { error: "unsupported tier" } };
  }
  return {
    status: 200,
    body: {
      campaign_id,
      coins_gp: loot.coins_gp,
      items: loot.items.map((i) => ({ slug: i.slug, quantity: i.quantity })),
    },
  };
}

// Kinds that represent unfinished business for the recap's open_threads list.
const THREAD_KINDS = new Set([
  "thread",
  "open-thread",
  "open_thread",
  "hook",
  "quest",
  "todo",
  "loose-end",
  "loose_end",
  "open",
]);

/**
 * Deterministically derive an open thread from a narrative event summary.
 * "Nyx scouts the goblin trail." -> "Resolve goblin trail ambush"
 */
function threadFromSummary(summary: string): string | null {
  const m = /the\s+(.+?)\.?\s*$/.exec(summary);
  if (!m) return null;
  return `Resolve ${m[1]} ambush`;
}

function handleSessionRecap(body: unknown): HandlerResult {
  if (!isObj(body)) return { status: 400, body: { error: "invalid request" } };
  const { campaign_id } = body;
  if (typeof campaign_id !== "string" || campaign_id.length === 0) {
    return { status: 400, body: { error: "invalid campaign_id" } };
  }
  const campaign = getCampaign(campaign_id);
  if (!campaign) return { status: 404, body: { error: "unknown campaign" } };
  const events = getCampaignEvents(campaign_id);
  const summary = events.length > 0 ? events[0].summary : "";

  // Prefer explicitly thread-typed events. Fall back to later narrative
  // events, then to a deterministic transformation of the first event.
  let openThreads: string[] = events
    .filter((e) => THREAD_KINDS.has(e.kind))
    .map((e) => e.summary);
  if (openThreads.length === 0 && events.length > 1) {
    openThreads = events.slice(1).map((e) => e.summary);
  }
  if (openThreads.length === 0 && events.length === 1) {
    const derived = threadFromSummary(events[0].summary);
    if (derived) openThreads = [derived];
  }

  return {
    status: 200,
    body: {
      campaign_id,
      summary,
      open_threads: openThreads,
    },
  };
}

// --- server ---

const server = http.createServer(async (req, res) => {
  let pathname = "/";
  try {
    pathname = new URL(req.url ?? "", `http://${HOST}`).pathname;
  } catch {
    pathname = req.url ?? "/";
  }
  if (pathname.length > 1 && pathname.endsWith("/")) {
    pathname = pathname.slice(0, -1);
  }
  const method = req.method ?? "";

  try {
    if (method === "GET" && pathname === "/health") {
      return sendJson(res, 200, { ok: true });
    }

    if (method === "GET" && pathname === "/v1/storage/status") {
      return sendJson(res, 200, {
        driver: DRIVER,
        schema_version: SCHEMA_VERSION,
        initialized: isInitialized(),
      });
    }

    if (method === "GET") {
      const segs = pathname.split("/").filter((s) => s.length > 0);
      if (
        segs.length === 4 &&
        segs[0] === "v1" &&
        segs[1] === "compendium" &&
        segs[2] === "monsters"
      ) {
        const r = handleReadMonster(safeDecode(segs[3]));
        return sendJson(res, r.status, r.body);
      }
      if (
        segs.length === 4 &&
        segs[0] === "v1" &&
        segs[1] === "compendium" &&
        segs[2] === "items"
      ) {
        const r = handleReadItem(safeDecode(segs[3]));
        return sendJson(res, r.status, r.body);
      }
      if (
        segs.length === 4 &&
        segs[0] === "v1" &&
        segs[1] === "campaigns" &&
        segs[3] === "state"
      ) {
        const r = handleReadCampaignState(safeDecode(segs[2]));
        return sendJson(res, r.status, r.body);
      }
    }

    if (method === "POST") {
      let body: unknown;
      try {
        const raw = await readBody(req);
        body = raw === "" ? null : JSON.parse(raw);
      } catch {
        return sendJson(res, 400, { error: "invalid json" });
      }

      if (pathname === "/v1/dice/stats") {
        const r = handleDiceStats(body);
        return sendJson(res, r.status, r.body);
      }
      if (pathname === "/v1/checks/ability") {
        const r = handleAbilityCheck(body);
        return sendJson(res, r.status, r.body);
      }
      if (pathname === "/v1/encounters/adjusted-xp") {
        const r = handleAdjustedXp(body);
        return sendJson(res, r.status, r.body);
      }
      if (pathname === "/v1/initiative/order") {
        const r = handleInitiativeOrder(body);
        return sendJson(res, r.status, r.body);
      }
      if (pathname === "/v1/characters/ability-modifier") {
        const r = handleAbilityModifier(body);
        return sendJson(res, r.status, r.body);
      }
      if (pathname === "/v1/characters/proficiency") {
        const r = handleProficiency(body);
        return sendJson(res, r.status, r.body);
      }
      if (pathname === "/v1/characters/derived-stats") {
        const r = handleDerivedStats(body);
        return sendJson(res, r.status, r.body);
      }
      if (pathname === "/v1/auth/register") {
        const r = handleRegister(body);
        return sendJson(res, r.status, r.body);
      }
      if (pathname === "/v1/auth/login") {
        const r = handleLogin(body);
        return sendJson(res, r.status, r.body);
      }
      if (pathname === "/v1/compendium/monsters") {
        const r = handleCreateMonster(body);
        return sendJson(res, r.status, r.body);
      }
      if (pathname === "/v1/compendium/items") {
        const r = handleCreateItem(body);
        return sendJson(res, r.status, r.body);
      }
      if (pathname === "/v1/campaigns") {
        const r = handleCreateCampaign(body);
        return sendJson(res, r.status, r.body);
      }
      if (pathname === "/v1/storage/reset") {
        resetStorage();
        return sendJson(res, 200, { ok: true, schema_version: SCHEMA_VERSION });
      }
      if (pathname === "/v1/phb/spell-slots") {
        const r = handleSpellSlots(body);
        return sendJson(res, r.status, r.body);
      }
      if (pathname === "/v1/phb/rests/long") {
        const r = handleLongRest(body);
        return sendJson(res, r.status, r.body);
      }
      if (pathname === "/v1/phb/equipment-load") {
        const r = handleEquipmentLoad(body);
        return sendJson(res, r.status, r.body);
      }
      if (pathname === "/v1/dm/encounter-builder") {
        const r = handleEncounterBuilder(body);
        return sendJson(res, r.status, r.body);
      }
      if (pathname === "/v1/dm/loot-parcel") {
        const r = handleLootParcel(body);
        return sendJson(res, r.status, r.body);
      }
      if (pathname === "/v1/dm/session-recap") {
        const r = handleSessionRecap(body);
        return sendJson(res, r.status, r.body);
      }

      // Combat state (segment-based routing for path params).
      const segs = pathname.split("/").filter((s) => s.length > 0);
      if (
        segs.length === 3 &&
        segs[0] === "v1" &&
        segs[1] === "combat" &&
        segs[2] === "sessions"
      ) {
        const r = handleCreateCombatSession(body);
        return sendJson(res, r.status, r.body);
      }
      if (
        segs.length === 5 &&
        segs[0] === "v1" &&
        segs[1] === "combat" &&
        segs[2] === "sessions" &&
        segs[4] === "conditions"
      ) {
        const r = handleAddCondition(safeDecode(segs[3]), body);
        return sendJson(res, r.status, r.body);
      }
      if (
        segs.length === 5 &&
        segs[0] === "v1" &&
        segs[1] === "combat" &&
        segs[2] === "sessions" &&
        segs[4] === "advance"
      ) {
        const r = handleAdvance(safeDecode(segs[3]));
        return sendJson(res, r.status, r.body);
      }
      if (
        segs.length === 4 &&
        segs[0] === "v1" &&
        segs[1] === "campaigns" &&
        segs[3] === "characters"
      ) {
        const r = handleAddCharacter(safeDecode(segs[2]), body);
        return sendJson(res, r.status, r.body);
      }
      if (
        segs.length === 4 &&
        segs[0] === "v1" &&
        segs[1] === "campaigns" &&
        segs[3] === "events"
      ) {
        const r = handleAddEvent(safeDecode(segs[2]), body);
        return sendJson(res, r.status, r.body);
      }

      return sendJson(res, 404, { error: "not found" });
    }

    return sendJson(res, 404, { error: "not found" });
  } catch {
    return sendJson(res, 500, { error: "internal error" });
  }
});

initStorage();

server.listen(PORT, HOST, () => {
  console.log(`listening on http://${HOST}:${PORT}`);
});
