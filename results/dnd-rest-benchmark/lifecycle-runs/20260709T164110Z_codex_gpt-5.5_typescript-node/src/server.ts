declare const Buffer: {
  byteLength(value: string): number;
  concat(chunks: Uint8Array[]): { toString(encoding: string): string };
  from(value: unknown): Uint8Array;
  isBuffer(value: unknown): value is Uint8Array;
};
declare const process: {
  env: Record<string, string | undefined>;
  exit(code?: number): never;
};
declare const console: {
  error(message?: unknown): void;
};

type IncomingMessage = AsyncIterable<unknown> & {
  method?: string;
  url?: string;
};

type ServerResponse = {
  headersSent: boolean;
  writeHead(status: number, headers: Record<string, string | number>): void;
  end(payload?: string): void;
};

const importRuntime = new Function("specifier", "return import(specifier)") as (specifier: string) => Promise<{
  createServer(handler: (request: IncomingMessage, response: ServerResponse) => void): {
    listen(port: number, host: string): void;
  };
}>;

const { createServer } = await importRuntime("node:http");

type JsonObject = Record<string, unknown>;

type InitiativeCombatant = {
  name: string;
  dex: number;
  score: number;
};

type CombatCondition = {
  condition: string;
  remaining_rounds: number;
};

type CombatSession = {
  id: string;
  round: number;
  turn_index: number;
  order: InitiativeCombatant[];
  conditions: Map<string, CombatCondition[]>;
};

const CR_XP: Record<string, number> = {
  "0": 10,
  "1/8": 25,
  "1/4": 50,
  "1/2": 100,
  "1": 200,
  "2": 450,
  "3": 700,
  "4": 1100,
  "5": 1800,
};

const LEVEL_THRESHOLDS: Record<number, { easy: number; medium: number; hard: number; deadly: number }> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

const combatSessions = new Map<string, CombatSession>();

function sendJson(response: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  response.writeHead(status, {
    "content-type": "application/json",
    "content-length": Buffer.byteLength(payload),
  });
  response.end(payload);
}

function badRequest(response: ServerResponse): void {
  sendJson(response, 400, { error: "bad_request" });
}

function notFound(response: ServerResponse): void {
  sendJson(response, 404, { error: "not_found" });
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isSafeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value);
}

function isAbilityScore(value: unknown): value is number {
  return isSafeInteger(value) && value >= 1 && value <= 30;
}

function isCharacterLevel(value: unknown): value is number {
  return isSafeInteger(value) && value >= 1 && value <= 20;
}

function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

function proficiencyBonus(level: number): number {
  return 2 + Math.floor((level - 1) / 4);
}

async function readJson(request: IncomingMessage): Promise<unknown> {
  const chunks: Uint8Array[] = [];
  for await (const chunk of request) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }

  const raw = Buffer.concat(chunks).toString("utf8");
  if (raw.length === 0) {
    throw new Error("empty body");
  }

  return JSON.parse(raw);
}

function handleDiceStats(body: unknown, response: ServerResponse): void {
  if (!isObject(body) || typeof body.expression !== "string") {
    badRequest(response);
    return;
  }

  const match = /^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/.exec(body.expression);
  if (match === null) {
    badRequest(response);
    return;
  }

  const diceCount = Number(match[1]);
  const sides = Number(match[2]);
  const modifierMagnitude = match[4] === undefined ? 0 : Number(match[4]);
  const modifier = match[3] === "-" ? -modifierMagnitude : modifierMagnitude;

  if (
    !isSafeInteger(diceCount) ||
    !isSafeInteger(sides) ||
    !isSafeInteger(modifierMagnitude) ||
    diceCount <= 0 ||
    sides <= 0
  ) {
    badRequest(response);
    return;
  }

  const min = diceCount + modifier;
  const max = diceCount * sides + modifier;
  const average = (min + max) / 2;

  sendJson(response, 200, {
    dice_count: diceCount,
    sides,
    modifier,
    min,
    max,
    average,
  });
}

function handleAbilityCheck(body: unknown, response: ServerResponse): void {
  if (!isObject(body) || !isFiniteNumber(body.roll) || !isFiniteNumber(body.modifier) || !isFiniteNumber(body.dc)) {
    badRequest(response);
    return;
  }

  const total = body.roll + body.modifier;
  sendJson(response, 200, {
    total,
    success: total >= body.dc,
    margin: total - body.dc,
  });
}

function monsterMultiplier(count: number): number {
  if (count <= 1) {
    return 1;
  }
  if (count === 2) {
    return 1.5;
  }
  if (count <= 6) {
    return 2;
  }
  if (count <= 10) {
    return 2.5;
  }
  if (count <= 14) {
    return 3;
  }
  return 4;
}

function difficultyFor(
  adjustedXp: number,
  thresholds: { easy: number; medium: number; hard: number; deadly: number },
): "trivial" | "easy" | "medium" | "hard" | "deadly" {
  if (adjustedXp >= thresholds.deadly) {
    return "deadly";
  }
  if (adjustedXp >= thresholds.hard) {
    return "hard";
  }
  if (adjustedXp >= thresholds.medium) {
    return "medium";
  }
  if (adjustedXp >= thresholds.easy) {
    return "easy";
  }
  return "trivial";
}

function handleAdjustedXp(body: unknown, response: ServerResponse): void {
  if (!isObject(body) || !Array.isArray(body.party) || !Array.isArray(body.monsters)) {
    badRequest(response);
    return;
  }

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of body.party) {
    if (!isObject(member) || !isSafeInteger(member.level)) {
      badRequest(response);
      return;
    }

    const level = member.level;
    const levelThresholds = LEVEL_THRESHOLDS[level];
    if (levelThresholds === undefined) {
      badRequest(response);
      return;
    }

    thresholds.easy += levelThresholds.easy;
    thresholds.medium += levelThresholds.medium;
    thresholds.hard += levelThresholds.hard;
    thresholds.deadly += levelThresholds.deadly;
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of body.monsters) {
    if (
      !isObject(monster) ||
      typeof monster.cr !== "string" ||
      !isSafeInteger(monster.count) ||
      monster.count <= 0
    ) {
      badRequest(response);
      return;
    }

    const cr = monster.cr;
    const count = monster.count;
    const xp = CR_XP[cr];
    if (xp === undefined) {
      badRequest(response);
      return;
    }

    baseXp += xp * count;
    monsterCount += count;
  }

  const multiplier = monsterMultiplier(monsterCount);
  const adjustedXp = baseXp * multiplier;

  sendJson(response, 200, {
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty: difficultyFor(adjustedXp, thresholds),
    thresholds,
  });
}

function handleInitiativeOrder(body: unknown, response: ServerResponse): void {
  if (!isObject(body) || !Array.isArray(body.combatants)) {
    badRequest(response);
    return;
  }

  const combatants = [];
  for (const combatant of body.combatants) {
    if (
      !isObject(combatant) ||
      typeof combatant.name !== "string" ||
      !isFiniteNumber(combatant.dex) ||
      !isFiniteNumber(combatant.roll)
    ) {
      badRequest(response);
      return;
    }

    combatants.push({
      name: combatant.name,
      dex: combatant.dex,
      score: combatant.roll + combatant.dex,
    });
  }

  combatants.sort((left, right) => {
    const scoreOrder = right.score - left.score;
    if (scoreOrder !== 0) {
      return scoreOrder;
    }

    const dexOrder = right.dex - left.dex;
    if (dexOrder !== 0) {
      return dexOrder;
    }

    return left.name.localeCompare(right.name);
  });

  sendJson(response, 200, {
    order: combatants.map(({ name, score }) => ({ name, score })),
  });
}

function sortInitiative(combatants: InitiativeCombatant[]): void {
  combatants.sort((left, right) => {
    const scoreOrder = right.score - left.score;
    if (scoreOrder !== 0) {
      return scoreOrder;
    }

    const dexOrder = right.dex - left.dex;
    if (dexOrder !== 0) {
      return dexOrder;
    }

    return left.name.localeCompare(right.name);
  });
}

function initiativeSummary(combatant: InitiativeCombatant): { name: string; score: number } {
  return { name: combatant.name, score: combatant.score };
}

function sessionSummary(session: CombatSession): JsonObject {
  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: initiativeSummary(session.order[session.turn_index]),
    order: session.order.map(initiativeSummary),
  };
}

function conditionSnapshot(session: CombatSession): Record<string, CombatCondition[]> {
  const snapshot: Record<string, CombatCondition[]> = {};
  for (const [target, conditions] of session.conditions) {
    snapshot[target] = conditions.map(({ condition, remaining_rounds }) => ({ condition, remaining_rounds }));
  }
  return snapshot;
}

function decodePathSegment(segment: string): string | undefined {
  try {
    return decodeURIComponent(segment);
  } catch {
    return undefined;
  }
}

function handleCreateCombatSession(body: unknown, response: ServerResponse): void {
  if (!isObject(body) || typeof body.id !== "string" || !Array.isArray(body.combatants)) {
    badRequest(response);
    return;
  }

  const id = body.id;
  if (combatSessions.has(id) || body.combatants.length === 0) {
    badRequest(response);
    return;
  }

  const order: InitiativeCombatant[] = [];
  for (const combatant of body.combatants) {
    if (
      !isObject(combatant) ||
      typeof combatant.name !== "string" ||
      !isFiniteNumber(combatant.dex) ||
      !isFiniteNumber(combatant.roll)
    ) {
      badRequest(response);
      return;
    }

    order.push({
      name: combatant.name,
      dex: combatant.dex,
      score: combatant.roll + combatant.dex,
    });
  }

  sortInitiative(order);

  const session: CombatSession = {
    id,
    round: 1,
    turn_index: 0,
    order,
    conditions: new Map(),
  };
  combatSessions.set(id, session);
  sendJson(response, 200, sessionSummary(session));
}

function handleAddCondition(sessionId: string, body: unknown, response: ServerResponse): void {
  const session = combatSessions.get(sessionId);
  if (session === undefined) {
    notFound(response);
    return;
  }

  if (
    !isObject(body) ||
    typeof body.target !== "string" ||
    typeof body.condition !== "string" ||
    !isSafeInteger(body.duration_rounds) ||
    body.duration_rounds <= 0
  ) {
    badRequest(response);
    return;
  }

  const target = body.target;
  if (!session.order.some((combatant) => combatant.name === target)) {
    badRequest(response);
    return;
  }

  const conditions = session.conditions.get(target) ?? [];
  conditions.push({ condition: body.condition, remaining_rounds: body.duration_rounds });
  session.conditions.set(target, conditions);

  sendJson(response, 200, {
    target,
    conditions: conditions.map(({ condition, remaining_rounds }) => ({ condition, remaining_rounds })),
  });
}

function handleAdvanceCombatSession(sessionId: string, response: ServerResponse): void {
  const session = combatSessions.get(sessionId);
  if (session === undefined) {
    notFound(response);
    return;
  }

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = session.order[session.turn_index];
  const activeConditions = session.conditions.get(active.name);
  if (activeConditions !== undefined) {
    const remainingConditions = activeConditions
      .map(({ condition, remaining_rounds }) => ({ condition, remaining_rounds: remaining_rounds - 1 }))
      .filter(({ remaining_rounds }) => remaining_rounds > 0);

    session.conditions.set(active.name, remainingConditions);
  }

  sendJson(response, 200, {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: initiativeSummary(active),
    conditions: conditionSnapshot(session),
  });
}

function handleAbilityModifier(body: unknown, response: ServerResponse): void {
  if (!isObject(body) || !isAbilityScore(body.score)) {
    badRequest(response);
    return;
  }

  sendJson(response, 200, {
    score: body.score,
    modifier: abilityModifier(body.score),
  });
}

function handleProficiency(body: unknown, response: ServerResponse): void {
  if (!isObject(body) || !isCharacterLevel(body.level)) {
    badRequest(response);
    return;
  }

  sendJson(response, 200, {
    level: body.level,
    proficiency_bonus: proficiencyBonus(body.level),
  });
}

function handleDerivedStats(body: unknown, response: ServerResponse): void {
  if (
    !isObject(body) ||
    !isCharacterLevel(body.level) ||
    !isObject(body.abilities) ||
    !isObject(body.armor) ||
    !isFiniteNumber(body.armor.base) ||
    typeof body.armor.shield !== "boolean" ||
    !isFiniteNumber(body.armor.dex_cap)
  ) {
    badRequest(response);
    return;
  }

  const abilities = body.abilities;
  if (
    !isAbilityScore(abilities.str) ||
    !isAbilityScore(abilities.dex) ||
    !isAbilityScore(abilities.con) ||
    !isAbilityScore(abilities.int) ||
    !isAbilityScore(abilities.wis) ||
    !isAbilityScore(abilities.cha)
  ) {
    badRequest(response);
    return;
  }

  const modifiers = {
    str: abilityModifier(abilities.str),
    dex: abilityModifier(abilities.dex),
    con: abilityModifier(abilities.con),
    int: abilityModifier(abilities.int),
    wis: abilityModifier(abilities.wis),
    cha: abilityModifier(abilities.cha),
  };
  const shieldBonus = body.armor.shield ? 2 : 0;

  sendJson(response, 200, {
    level: body.level,
    proficiency_bonus: proficiencyBonus(body.level),
    hp_max: body.level * (6 + modifiers.con),
    armor_class: body.armor.base + Math.min(modifiers.dex, body.armor.dex_cap) + shieldBonus,
    modifiers,
  });
}

function routeGet(path: string, response: ServerResponse): boolean {
  if (path === "/health") {
    sendJson(response, 200, { ok: true });
    return true;
  }

  return false;
}

function routePost(path: string, body: unknown, response: ServerResponse): boolean {
  if (path === "/v1/dice/stats") {
    handleDiceStats(body, response);
    return true;
  }
  if (path === "/v1/checks/ability") {
    handleAbilityCheck(body, response);
    return true;
  }
  if (path === "/v1/encounters/adjusted-xp") {
    handleAdjustedXp(body, response);
    return true;
  }
  if (path === "/v1/initiative/order") {
    handleInitiativeOrder(body, response);
    return true;
  }
  if (path === "/v1/characters/ability-modifier") {
    handleAbilityModifier(body, response);
    return true;
  }
  if (path === "/v1/characters/proficiency") {
    handleProficiency(body, response);
    return true;
  }
  if (path === "/v1/characters/derived-stats") {
    handleDerivedStats(body, response);
    return true;
  }
  if (path === "/v1/combat/sessions") {
    handleCreateCombatSession(body, response);
    return true;
  }

  const conditionMatch = /^\/v1\/combat\/sessions\/([^/]+)\/conditions$/.exec(path);
  if (conditionMatch !== null) {
    const sessionId = decodePathSegment(conditionMatch[1]);
    if (sessionId === undefined) {
      badRequest(response);
      return true;
    }
    handleAddCondition(sessionId, body, response);
    return true;
  }

  return false;
}

function routeBodylessPost(path: string, response: ServerResponse): boolean {
  const advanceMatch = /^\/v1\/combat\/sessions\/([^/]+)\/advance$/.exec(path);
  if (advanceMatch !== null) {
    const sessionId = decodePathSegment(advanceMatch[1]);
    if (sessionId === undefined) {
      badRequest(response);
      return true;
    }
    handleAdvanceCombatSession(sessionId, response);
    return true;
  }

  return false;
}

const server = createServer((request, response) => {
  void (async () => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    const method = request.method ?? "GET";

    if (method === "GET") {
      if (!routeGet(url.pathname, response)) {
        notFound(response);
      }
      return;
    }

    if (method === "POST") {
      if (routeBodylessPost(url.pathname, response)) {
        return;
      }

      let body: unknown;
      try {
        body = await readJson(request);
      } catch {
        badRequest(response);
        return;
      }

      if (!routePost(url.pathname, body, response)) {
        notFound(response);
      }
      return;
    }

    notFound(response);
  })().catch(() => {
    if (!response.headersSent) {
      sendJson(response, 500, { error: "internal_error" });
    } else {
      response.end();
    }
  });
});

const portText = process.env.PORT;
const port = portText === undefined ? NaN : Number(portText);

if (!Number.isSafeInteger(port) || port <= 0 || port > 65535) {
  console.error("PORT must be an integer between 1 and 65535");
  process.exit(1);
}

server.listen(port, "127.0.0.1");
