import http from "node:http";
import { URL } from "node:url";

const PORT = parseInt(process.env.PORT || "3000", 10);

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

const ABILITY_NAMES = ["str", "dex", "con", "int", "wis", "cha"] as const;
type AbilityName = (typeof ABILITY_NAMES)[number];

type Condition = { condition: string; remaining_rounds: number };
type Combatant = { name: string; dex: number; roll: number; score: number };
type Session = {
  id: string;
  round: number;
  turn_index: number;
  combatants: Combatant[];
  order: { name: string; score: number }[];
  conditions: Record<string, Condition[]>;
};

const sessions = new Map<string, Session>();

function sendJson(res: http.ServerResponse, status: number, data: unknown): void {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(data));
}

async function readBody(req: http.IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf-8");
}

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function parseDiceStats(expression: unknown): {
  dice_count: number;
  sides: number;
  modifier: number;
  min: number;
  max: number;
  average: number;
} | null {
  if (typeof expression !== "string") return null;
  const match = expression.match(/^([1-9][0-9]*)d([1-9][0-9]*)([+-][0-9]+)?$/);
  if (!match) return null;
  const dice_count = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] ? parseInt(match[3], 10) : 0;
  return {
    dice_count,
    sides,
    modifier,
    min: dice_count + modifier,
    max: dice_count * sides + modifier,
    average: (dice_count * (1 + sides)) / 2 + modifier,
  };
}

function parseAbilityCheck(body: unknown): { total: number; success: boolean; margin: number } | null {
  if (!body || typeof body !== "object") return null;
  const { roll, modifier, dc } = body as Record<string, unknown>;
  if (typeof roll !== "number" || typeof modifier !== "number" || typeof dc !== "number") return null;
  const total = roll + modifier;
  return { total, success: total >= dc, margin: total - dc };
}

function getMultiplier(monsterCount: number): number {
  if (monsterCount === 1) return 1;
  if (monsterCount === 2) return 1.5;
  if (monsterCount <= 6) return 2;
  if (monsterCount <= 10) return 2.5;
  if (monsterCount <= 14) return 3;
  return 4;
}

function parseAdjustedXp(body: unknown): {
  base_xp: number;
  monster_count: number;
  multiplier: number;
  adjusted_xp: number;
  difficulty: string;
  thresholds: { easy: number; medium: number; hard: number; deadly: number };
} | null {
  if (!body || typeof body !== "object") return null;
  const { party, monsters } = body as { party?: unknown[]; monsters?: unknown[] };
  if (!Array.isArray(party) || !Array.isArray(monsters)) return null;

  let base_xp = 0;
  let monster_count = 0;
  for (const m of monsters) {
    if (!m || typeof m !== "object") return null;
    const { cr, count } = m as { cr?: unknown; count?: unknown };
    if (typeof cr !== "string" || typeof count !== "number") return null;
    const xp = CR_XP[cr];
    if (xp === undefined) return null;
    base_xp += xp * count;
    monster_count += count;
  }

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const p of party) {
    if (!p || typeof p !== "object") return null;
    const { level } = p as { level?: unknown };
    if (typeof level !== "number") return null;
    const t = LEVEL_THRESHOLDS[level];
    if (!t) return null;
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

  const multiplier = getMultiplier(monster_count);
  const adjusted_xp = base_xp * multiplier;

  let difficulty = "trivial";
  if (adjusted_xp >= thresholds.deadly) difficulty = "deadly";
  else if (adjusted_xp >= thresholds.hard) difficulty = "hard";
  else if (adjusted_xp >= thresholds.medium) difficulty = "medium";
  else if (adjusted_xp >= thresholds.easy) difficulty = "easy";

  return { base_xp, monster_count, multiplier, adjusted_xp, difficulty, thresholds };
}

function parseInitiative(body: unknown): { order: { name: string; score: number }[] } | null {
  if (!body || typeof body !== "object") return null;
  const { combatants } = body as { combatants?: unknown[] };
  if (!Array.isArray(combatants)) return null;

  const order: { name: string; score: number }[] = [];
  for (const c of combatants) {
    if (!c || typeof c !== "object") return null;
    const { name, dex, roll } = c as { name?: unknown; dex?: unknown; roll?: unknown };
    if (typeof name !== "string" || typeof dex !== "number" || typeof roll !== "number") return null;
    order.push({ name, score: roll + dex });
  }

  order.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    const aDex = (combatants.find((c) => (c as { name: string }).name === a.name) as { dex: number }).dex;
    const bDex = (combatants.find((c) => (c as { name: string }).name === b.name) as { dex: number }).dex;
    if (bDex !== aDex) return bDex - aDex;
    return a.name.localeCompare(b.name);
  });

  return { order };
}

function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

function proficiencyBonus(level: number): number {
  if (level <= 4) return 2;
  if (level <= 8) return 3;
  if (level <= 12) return 4;
  if (level <= 16) return 5;
  return 6;
}

function parseAbilityModifier(body: unknown): { score: number; modifier: number } | null {
  if (!body || typeof body !== "object") return null;
  const { score } = body as { score?: unknown };
  if (!isInteger(score) || score < 1 || score > 30) return null;
  return { score, modifier: abilityModifier(score) };
}

function parseProficiency(body: unknown): { level: number; proficiency_bonus: number } | null {
  if (!body || typeof body !== "object") return null;
  const { level } = body as { level?: unknown };
  if (!isInteger(level) || level < 1 || level > 20) return null;
  return { level, proficiency_bonus: proficiencyBonus(level) };
}

function parseDerivedStats(body: unknown): {
  level: number;
  proficiency_bonus: number;
  hp_max: number;
  armor_class: number;
  modifiers: Record<AbilityName, number>;
} | null {
  if (!body || typeof body !== "object") return null;
  const { level, abilities, armor } = body as { level?: unknown; abilities?: unknown; armor?: unknown };

  if (!isInteger(level) || level < 1 || level > 20) return null;
  if (!abilities || typeof abilities !== "object") return null;
  if (!armor || typeof armor !== "object") return null;

  const modifiers: Partial<Record<AbilityName, number>> = {};
  for (const name of ABILITY_NAMES) {
    const score = (abilities as Record<string, unknown>)[name];
    if (!isInteger(score) || score < 1 || score > 30) return null;
    modifiers[name] = abilityModifier(score);
  }

  const { base, shield, dex_cap } = armor as { base?: unknown; shield?: unknown; dex_cap?: unknown };
  if (!isInteger(base)) return null;
  if (typeof shield !== "boolean") return null;
  if (!isInteger(dex_cap)) return null;

  const dexModifier = modifiers.dex!;
  const shieldBonus = shield ? 2 : 0;
  const armorClass = base + Math.min(dexModifier, dex_cap) + shieldBonus;
  const hpMax = level * (6 + modifiers.con!);

  return {
    level,
    proficiency_bonus: proficiencyBonus(level),
    hp_max: hpMax,
    armor_class: armorClass,
    modifiers: modifiers as Record<AbilityName, number>,
  };
}

function sortCombatants(combatants: Combatant[]): Combatant[] {
  return [...combatants].sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name.localeCompare(b.name);
  });
}

function combatantsFromBody(body: unknown): Combatant[] | null {
  if (!body || typeof body !== "object") return null;
  const { combatants } = body as { combatants?: unknown };
  if (!Array.isArray(combatants) || combatants.length === 0) return null;

  const result: Combatant[] = [];
  for (const c of combatants) {
    if (!c || typeof c !== "object") return null;
    const { name, dex, roll } = c as { name?: unknown; dex?: unknown; roll?: unknown };
    if (!isNonEmptyString(name) || typeof dex !== "number" || typeof roll !== "number") return null;
    result.push({ name, dex, roll, score: roll + dex });
  }
  return result;
}

function formatSessionResponse(session: Session): {
  id: string;
  round: number;
  turn_index: number;
  active: { name: string; score: number };
  order: { name: string; score: number }[];
} {
  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: session.order[session.turn_index],
    order: session.order,
  };
}

function formatConditions(session: Session): Record<string, Condition[]> {
  const conditions: Record<string, Condition[]> = {};
  for (const combatant of session.order) {
    conditions[combatant.name] = session.conditions[combatant.name] ?? [];
  }
  return conditions;
}

function handleCreateCombatSession(body: unknown, res: http.ServerResponse): void {
  if (!body || typeof body !== "object") {
    sendJson(res, 400, { error: "bad request" });
    return;
  }
  const { id } = body as { id?: unknown };
  if (!isNonEmptyString(id)) {
    sendJson(res, 400, { error: "bad request" });
    return;
  }
  if (sessions.has(id)) {
    sendJson(res, 400, { error: "session already exists" });
    return;
  }
  const combatants = combatantsFromBody(body);
  if (!combatants) {
    sendJson(res, 400, { error: "bad request" });
    return;
  }

  const order = sortCombatants(combatants).map(({ name, score }) => ({ name, score }));
  const session: Session = {
    id,
    round: 1,
    turn_index: 0,
    combatants,
    order,
    conditions: {},
  };
  sessions.set(id, session);
  sendJson(res, 200, formatSessionResponse(session));
}

function handleAddCondition(sessionId: string, body: unknown, res: http.ServerResponse): void {
  const session = sessions.get(sessionId);
  if (!session) {
    sendJson(res, 404, { error: "session not found" });
    return;
  }
  if (!body || typeof body !== "object") {
    sendJson(res, 400, { error: "bad request" });
    return;
  }
  const { target, condition, duration_rounds } = body as {
    target?: unknown;
    condition?: unknown;
    duration_rounds?: unknown;
  };
  if (!isNonEmptyString(target) || typeof condition !== "string" || !isInteger(duration_rounds) || duration_rounds < 1) {
    sendJson(res, 400, { error: "bad request" });
    return;
  }
  if (!session.combatants.some((c) => c.name === target)) {
    sendJson(res, 400, { error: "target not found" });
    return;
  }

  if (!session.conditions[target]) session.conditions[target] = [];
  session.conditions[target].push({ condition, remaining_rounds: duration_rounds });
  sendJson(res, 200, { target, conditions: session.conditions[target] });
}

function handleAdvanceTurn(sessionId: string, res: http.ServerResponse): void {
  const session = sessions.get(sessionId);
  if (!session) {
    sendJson(res, 404, { error: "session not found" });
    return;
  }
  if (session.order.length === 0) {
    sendJson(res, 400, { error: "no combatants" });
    return;
  }

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const activeName = session.order[session.turn_index].name;
  const activeConditions = session.conditions[activeName];
  if (activeConditions) {
    session.conditions[activeName] = activeConditions
      .map((c) => ({ ...c, remaining_rounds: c.remaining_rounds - 1 }))
      .filter((c) => c.remaining_rounds > 0);
  }

  sendJson(res, 200, {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: session.order[session.turn_index],
    conditions: formatConditions(session),
  });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);
  const path = url.pathname;

  try {
    if (req.method === "GET" && path === "/health") {
      sendJson(res, 200, { ok: true });
      return;
    }

    if (req.method !== "POST") {
      sendJson(res, 405, { error: "method not allowed" });
      return;
    }

    let body: unknown;
    try {
      const raw = await readBody(req);
      body = raw ? JSON.parse(raw) : undefined;
    } catch {
      sendJson(res, 400, { error: "invalid json" });
      return;
    }

    if (path === "/v1/dice/stats") {
      if (!body || typeof body !== "object" || typeof (body as { expression?: unknown }).expression !== "string") {
        sendJson(res, 400, { error: "bad request" });
        return;
      }
      const result = parseDiceStats((body as { expression: string }).expression);
      if (!result) {
        sendJson(res, 400, { error: "invalid expression" });
        return;
      }
      sendJson(res, 200, result);
      return;
    }

    if (path === "/v1/checks/ability") {
      const result = parseAbilityCheck(body);
      if (!result) {
        sendJson(res, 400, { error: "bad request" });
        return;
      }
      sendJson(res, 200, result);
      return;
    }

    if (path === "/v1/encounters/adjusted-xp") {
      const result = parseAdjustedXp(body);
      if (!result) {
        sendJson(res, 400, { error: "bad request" });
        return;
      }
      sendJson(res, 200, result);
      return;
    }

    if (path === "/v1/initiative/order") {
      const result = parseInitiative(body);
      if (!result) {
        sendJson(res, 400, { error: "bad request" });
        return;
      }
      sendJson(res, 200, result);
      return;
    }

    if (path === "/v1/characters/ability-modifier") {
      const result = parseAbilityModifier(body);
      if (!result) {
        sendJson(res, 400, { error: "bad request" });
        return;
      }
      sendJson(res, 200, result);
      return;
    }

    if (path === "/v1/characters/proficiency") {
      const result = parseProficiency(body);
      if (!result) {
        sendJson(res, 400, { error: "bad request" });
        return;
      }
      sendJson(res, 200, result);
      return;
    }

    if (path === "/v1/characters/derived-stats") {
      const result = parseDerivedStats(body);
      if (!result) {
        sendJson(res, 400, { error: "bad request" });
        return;
      }
      sendJson(res, 200, result);
      return;
    }

    if (path === "/v1/combat/sessions") {
      handleCreateCombatSession(body, res);
      return;
    }

    const conditionsMatch = path.match(/^\/v1\/combat\/sessions\/([^/]+)\/conditions$/);
    if (conditionsMatch) {
      handleAddCondition(decodeURIComponent(conditionsMatch[1]), body, res);
      return;
    }

    const advanceMatch = path.match(/^\/v1\/combat\/sessions\/([^/]+)\/advance$/);
    if (advanceMatch) {
      handleAdvanceTurn(decodeURIComponent(advanceMatch[1]), res);
      return;
    }

    sendJson(res, 404, { error: "not found" });
  } catch (err) {
    sendJson(res, 500, { error: "internal server error" });
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`Server listening on http://127.0.0.1:${PORT}`);
});
