import http from "http";

const PORT = Number(process.env.PORT || "3000");

interface JsonResponse {
  [key: string]: unknown;
}

type RouteHandler = (body: unknown, params: Record<string, string>) => JsonResponse;

interface Route {
  method: string;
  pattern: string;
  handler: RouteHandler;
}

function sendJson(res: http.ServerResponse, status: number, body: JsonResponse): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

function parseJson(req: http.IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    let data = "";
    req.setEncoding("utf8");
    req.on("data", (chunk) => {
      data += chunk;
    });
    req.on("end", () => {
      try {
        resolve(data.trim() === "" ? {} : JSON.parse(data));
      } catch {
        reject(new Error("Invalid JSON"));
      }
    });
    req.on("error", reject);
  });
}

function assertNumber(value: unknown, name: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new BadRequest(`${name} must be a finite number`);
  }
  return value;
}

function assertInteger(value: unknown, name: string): number {
  const n = assertNumber(value, name);
  if (!Number.isInteger(n)) {
    throw new BadRequest(`${name} must be an integer`);
  }
  return n;
}

function assertPositiveInteger(value: unknown, name: string): number {
  const n = assertInteger(value, name);
  if (n <= 0) {
    throw new BadRequest(`${name} must be a positive integer`);
  }
  return n;
}

function assertString(value: unknown, name: string): string {
  if (typeof value !== "string") {
    throw new BadRequest(`${name} must be a string`);
  }
  return value;
}

function assertArray(value: unknown, name: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new BadRequest(`${name} must be an array`);
  }
  return value;
}

function assertObject(value: unknown, name: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new BadRequest(`${name} must be an object`);
  }
  return value as Record<string, unknown>;
}

class BadRequest extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BadRequest";
  }
}

class NotFound extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NotFound";
  }
}

function matchRoute(path: string, pattern: string): Record<string, string> | null {
  const pathParts = path.split("/").filter(Boolean);
  const patternParts = pattern.split("/").filter(Boolean);
  if (pathParts.length !== patternParts.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < patternParts.length; i++) {
    const part = patternParts[i];
    if (part.startsWith(":")) {
      params[part.slice(1)] = decodeURIComponent(pathParts[i]);
    } else if (part !== pathParts[i]) {
      return null;
    }
  }
  return params;
}

const XP_TABLE: Record<string, number> = {
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

const LEVEL_3_THRESHOLDS = {
  easy: 75,
  medium: 150,
  hard: 225,
  deadly: 400,
};

function multiplierFor(count: number): number {
  if (count === 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

function parseDiceExpression(expression: string) {
  const match = expression.match(/^(\d+)d(\d+)(?:(\+|\-)(\d+))?$/);
  if (!match) {
    throw new BadRequest("Invalid dice expression");
  }

  const count = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] ? (match[3] === "+" ? 1 : -1) * parseInt(match[4], 10) : 0;

  if (count <= 0 || sides <= 0) {
    throw new BadRequest("Dice count and sides must be positive");
  }

  const min = count * 1 + modifier;
  const max = count * sides + modifier;
  const average = (min + max) / 2;

  return {
    dice_count: count,
    sides,
    modifier,
    min,
    max,
    average,
  };
}

function handleDiceStats(body: unknown, _params: Record<string, string>): JsonResponse {
  const obj = assertObject(body, "body");
  return parseDiceExpression(assertString(obj.expression, "expression"));
}

function handleAbilityCheck(body: unknown, _params: Record<string, string>): JsonResponse {
  const obj = assertObject(body, "body");
  const roll = assertInteger(obj.roll, "roll");
  const modifier = assertInteger(obj.modifier, "modifier");
  const dc = assertInteger(obj.dc, "dc");
  const total = roll + modifier;
  return {
    total,
    success: total >= dc,
    margin: total - dc,
  };
}

function handleAdjustedXp(body: unknown, _params: Record<string, string>): JsonResponse {
  const obj = assertObject(body, "body");
  const party = assertArray(obj.party, "party");
  const monsters = assertArray(obj.monsters, "monsters");

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    const m = assertObject(member, "party member");
    const level = assertInteger(m.level, "party member level");
    if (level !== 3) {
      throw new BadRequest("Only level 3 party members are supported in this suite");
    }
    thresholds.easy += LEVEL_3_THRESHOLDS.easy;
    thresholds.medium += LEVEL_3_THRESHOLDS.medium;
    thresholds.hard += LEVEL_3_THRESHOLDS.hard;
    thresholds.deadly += LEVEL_3_THRESHOLDS.deadly;
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const entry of monsters) {
    const e = assertObject(entry, "monster entry");
    const cr = assertString(e.cr, "cr");
    const count = assertInteger(e.count, "count");
    if (count <= 0) {
      throw new BadRequest("monster count must be positive");
    }
    const xp = XP_TABLE[cr];
    if (xp === undefined) {
      throw new BadRequest(`Unsupported CR: ${cr}`);
    }
    baseXp += xp * count;
    monsterCount += count;
  }

  const multiplier = multiplierFor(monsterCount);
  const adjustedXp = baseXp * multiplier;

  let difficulty = "trivial";
  if (adjustedXp >= thresholds.deadly) difficulty = "deadly";
  else if (adjustedXp >= thresholds.hard) difficulty = "hard";
  else if (adjustedXp >= thresholds.medium) difficulty = "medium";
  else if (adjustedXp >= thresholds.easy) difficulty = "easy";

  return {
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty,
    thresholds,
  };
}

function handleInitiativeOrder(body: unknown, _params: Record<string, string>): JsonResponse {
  const obj = assertObject(body, "body");
  const combatants = assertArray(obj.combatants, "combatants");

  const scored = combatants.map((c) => {
    const entry = assertObject(c, "combatant");
    const name = assertString(entry.name, "name");
    const dex = assertInteger(entry.dex, "dex");
    const roll = assertInteger(entry.roll, "roll");
    return { name, dex, score: roll + dex };
  });

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name.localeCompare(b.name);
  });

  return {
    order: scored.map((c) => ({ name: c.name, score: c.score })),
  };
}

function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

function proficiencyBonus(level: number): number {
  return Math.floor((level - 1) / 4) + 2;
}

function assertScore(value: unknown, name: string): number {
  const score = assertInteger(value, name);
  if (score < 1 || score > 30) {
    throw new BadRequest(`${name} must be between 1 and 30`);
  }
  return score;
}

function assertLevel(value: unknown, name: string): number {
  const level = assertInteger(value, name);
  if (level < 1 || level > 20) {
    throw new BadRequest(`${name} must be between 1 and 20`);
  }
  return level;
}

function handleAbilityModifier(body: unknown, _params: Record<string, string>): JsonResponse {
  const obj = assertObject(body, "body");
  const score = assertScore(obj.score, "score");
  return { score, modifier: abilityModifier(score) };
}

function handleProficiency(body: unknown, _params: Record<string, string>): JsonResponse {
  const obj = assertObject(body, "body");
  const level = assertLevel(obj.level, "level");
  return { level, proficiency_bonus: proficiencyBonus(level) };
}

const ABILITY_NAMES = ["str", "dex", "con", "int", "wis", "cha"] as const;

type Ability = (typeof ABILITY_NAMES)[number];

function handleDerivedStats(body: unknown, _params: Record<string, string>): JsonResponse {
  const obj = assertObject(body, "body");
  const level = assertLevel(obj.level, "level");
  const abilities = assertObject(obj.abilities, "abilities");
  const armor = assertObject(obj.armor, "armor");

  const modifiers: Record<Ability, number> = {
    str: 0,
    dex: 0,
    con: 0,
    int: 0,
    wis: 0,
    cha: 0,
  };

  for (const ability of ABILITY_NAMES) {
    modifiers[ability] = abilityModifier(
      assertScore(abilities[ability], ability)
    );
  }

  const base = assertInteger(armor.base, "base");
  const dexCap = assertInteger(armor.dex_cap, "dex_cap");
  const shield = armor.shield === true;
  const shieldBonus = shield ? 2 : 0;
  const armorClass = base + Math.min(modifiers.dex, dexCap) + shieldBonus;
  const hpMax = level * (6 + modifiers.con);

  return {
    level,
    proficiency_bonus: proficiencyBonus(level),
    hp_max: hpMax,
    armor_class: armorClass,
    modifiers,
  };
}

interface Combatant {
  name: string;
  score: number;
}

interface Condition {
  condition: string;
  remaining_rounds: number;
}

interface CombatSession {
  id: string;
  round: number;
  turn_index: number;
  order: Combatant[];
  conditions: Record<string, Condition[]>;
}

const sessions = new Map<string, CombatSession>();

function handleCreateCombatSession(body: unknown, _params: Record<string, string>): JsonResponse {
  const obj = assertObject(body, "body");
  const id = assertString(obj.id, "id");
  if (sessions.has(id)) {
    throw new BadRequest("Session id already exists");
  }

  const combatants = assertArray(obj.combatants, "combatants");
  if (combatants.length === 0) {
    throw new BadRequest("combatants must not be empty");
  }

  const scored = combatants.map((c) => {
    const entry = assertObject(c, "combatant");
    const name = assertString(entry.name, "name");
    const dex = assertInteger(entry.dex, "dex");
    const roll = assertInteger(entry.roll, "roll");
    return { name, dex, score: roll + dex };
  });

  const names = new Set<string>();
  for (const c of scored) {
    if (names.has(c.name)) {
      throw new BadRequest("Duplicate combatant name");
    }
    names.add(c.name);
  }

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name.localeCompare(b.name);
  });

  const session: CombatSession = {
    id,
    round: 1,
    turn_index: 0,
    order: scored.map((c) => ({ name: c.name, score: c.score })),
    conditions: {},
  };

  sessions.set(id, session);

  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: session.order[0],
    order: session.order,
  };
}

function handleAddCondition(body: unknown, params: Record<string, string>): JsonResponse {
  const session = sessions.get(params.id);
  if (!session) {
    throw new NotFound("Session not found");
  }

  const obj = assertObject(body, "body");
  const target = assertString(obj.target, "target");
  if (!session.order.some((c) => c.name === target)) {
    throw new BadRequest("Target not found in session");
  }

  const condition = assertString(obj.condition, "condition");
  const duration = assertPositiveInteger(obj.duration_rounds, "duration_rounds");

  if (!session.conditions[target]) {
    session.conditions[target] = [];
  }

  session.conditions[target].push({ condition, remaining_rounds: duration });

  return {
    target,
    conditions: session.conditions[target],
  };
}

function handleAdvance(body: unknown, params: Record<string, string>): JsonResponse {
  const session = sessions.get(params.id);
  if (!session) {
    throw new NotFound("Session not found");
  }

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = session.order[session.turn_index];

  const activeConditions = session.conditions[active.name];
  if (activeConditions) {
    session.conditions[active.name] = activeConditions
      .map((c) => ({ ...c, remaining_rounds: c.remaining_rounds - 1 }))
      .filter((c) => c.remaining_rounds > 0);
  }

  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active,
    conditions: session.conditions,
  };
}

const routes: Route[] = [
  { method: "GET", pattern: "/health", handler: (_body, _params) => ({ ok: true }) },
  { method: "POST", pattern: "/v1/dice/stats", handler: handleDiceStats },
  { method: "POST", pattern: "/v1/checks/ability", handler: handleAbilityCheck },
  { method: "POST", pattern: "/v1/encounters/adjusted-xp", handler: handleAdjustedXp },
  { method: "POST", pattern: "/v1/initiative/order", handler: handleInitiativeOrder },
  { method: "POST", pattern: "/v1/characters/ability-modifier", handler: handleAbilityModifier },
  { method: "POST", pattern: "/v1/characters/proficiency", handler: handleProficiency },
  { method: "POST", pattern: "/v1/characters/derived-stats", handler: handleDerivedStats },
  { method: "POST", pattern: "/v1/combat/sessions", handler: handleCreateCombatSession },
  { method: "POST", pattern: "/v1/combat/sessions/:id/conditions", handler: handleAddCondition },
  { method: "POST", pattern: "/v1/combat/sessions/:id/advance", handler: handleAdvance },
];

const server = http.createServer(async (req, res) => {
  const url = req.url || "/";

  const matchingRoutes = routes.filter((r) => matchRoute(url, r.pattern));
  const route = matchingRoutes.find((r) => r.method === req.method);

  if (!route) {
    sendJson(res, matchingRoutes.length > 0 ? 405 : 404, {
      error: matchingRoutes.length > 0 ? "Method not allowed" : "Not found",
    });
    return;
  }

  const params = matchRoute(url, route.pattern)!;

  try {
    const body = route.method === "POST" ? await parseJson(req) : undefined;
    const result = route.handler(body, params);
    sendJson(res, 200, result);
  } catch (err) {
    if (err instanceof BadRequest) {
      sendJson(res, 400, { error: err.message });
    } else if (err instanceof NotFound) {
      sendJson(res, 404, { error: err.message });
    } else {
      sendJson(res, 400, { error: "Bad request" });
    }
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`Server listening on http://127.0.0.1:${PORT}`);
});
