import { createServer, IncomingMessage, ServerResponse } from "node:http";

type Json = Record<string, unknown>;

const PORT = Number(process.env.PORT ?? "3000");
const HOST = "127.0.0.1";

function sendJson(res: ServerResponse, status: number, body: Json): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

function badRequest(res: ServerResponse, message = "invalid request"): void {
  sendJson(res, 400, { error: message });
}

function readBody(req: IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => chunks.push(chunk));
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf8");
      if (raw.trim() === "") {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(raw));
      } catch {
        reject(new Error("invalid json"));
      }
    });
    req.on("error", reject);
  });
}

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

// --- /v1/dice/stats ---

const DICE_RE = /^(\d+)d(\d+)([+-]\d+)?$/;

function diceStats(body: unknown): Json | null {
  if (typeof body !== "object" || body === null) return null;
  const expression = (body as Json).expression;
  if (typeof expression !== "string") return null;
  const match = DICE_RE.exec(expression.trim());
  if (!match) return null;
  const diceCount = Number.parseInt(match[1]!, 10);
  const sides = Number.parseInt(match[2]!, 10);
  const modifier = match[3] ? Number.parseInt(match[3], 10) : 0;
  if (diceCount <= 0 || sides <= 0) return null;
  const min = diceCount * 1 + modifier;
  const max = diceCount * sides + modifier;
  const average = (min + max) / 2;
  return {
    dice_count: diceCount,
    sides,
    modifier,
    min,
    max,
    average,
  };
}

// --- /v1/checks/ability ---

function abilityCheck(body: unknown): Json | null {
  if (typeof body !== "object" || body === null) return null;
  const { roll, modifier, dc } = body as Json;
  if (!isInteger(roll) || !isInteger(modifier) || !isInteger(dc)) return null;
  const total = roll + modifier;
  return {
    total,
    success: total >= dc,
    margin: total - dc,
  };
}

// --- /v1/encounters/adjusted-xp ---

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

function countMultiplier(count: number): number {
  if (count <= 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

function adjustedXp(body: unknown): Json | null {
  if (typeof body !== "object" || body === null) return null;
  const { party, monsters } = body as Json;
  if (!Array.isArray(party) || !Array.isArray(monsters)) return null;

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    if (typeof member !== "object" || member === null) return null;
    const level = (member as Json).level;
    if (!isInteger(level)) return null;
    const t = LEVEL_THRESHOLDS[level];
    if (!t) return null;
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of monsters) {
    if (typeof monster !== "object" || monster === null) return null;
    const cr = (monster as Json).cr;
    const count = (monster as Json).count;
    if (typeof cr !== "string" || !isInteger(count) || count < 0) return null;
    const xp = CR_XP[cr];
    if (xp === undefined) return null;
    baseXp += xp * count;
    monsterCount += count;
  }

  const multiplier = countMultiplier(monsterCount);
  const adjusted = baseXp * multiplier;

  let difficulty = "trivial";
  if (adjusted >= thresholds.deadly) difficulty = "deadly";
  else if (adjusted >= thresholds.hard) difficulty = "hard";
  else if (adjusted >= thresholds.medium) difficulty = "medium";
  else if (adjusted >= thresholds.easy) difficulty = "easy";

  return {
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjusted,
    difficulty,
    thresholds,
  };
}

// --- /v1/initiative/order ---

function initiativeOrder(body: unknown): Json | null {
  if (typeof body !== "object" || body === null) return null;
  const combatants = (body as Json).combatants;
  if (!Array.isArray(combatants)) return null;

  const entries: { name: string; dex: number; score: number }[] = [];
  for (const c of combatants) {
    if (typeof c !== "object" || c === null) return null;
    const { name, dex, roll } = c as Json;
    if (typeof name !== "string" || !isInteger(dex) || !isInteger(roll)) return null;
    entries.push({ name, dex, score: roll + dex });
  }

  entries.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });

  return {
    order: entries.map((e) => ({ name: e.name, score: e.score })),
  };
}

// --- /v1/characters/ability-modifier ---

function abilityModifierValue(score: number): number {
  return Math.floor((score - 10) / 2);
}

function abilityModifier(body: unknown): Json | null {
  if (typeof body !== "object" || body === null) return null;
  const score = (body as Json).score;
  if (!isInteger(score) || score < 1 || score > 30) return null;
  return { score, modifier: abilityModifierValue(score) };
}

// --- /v1/characters/proficiency ---

function proficiencyBonusValue(level: number): number {
  return Math.floor((level - 1) / 4) + 2;
}

function proficiency(body: unknown): Json | null {
  if (typeof body !== "object" || body === null) return null;
  const level = (body as Json).level;
  if (!isInteger(level) || level < 1 || level > 20) return null;
  return { level, proficiency_bonus: proficiencyBonusValue(level) };
}

// --- /v1/characters/derived-stats ---

const ABILITY_KEYS = ["str", "dex", "con", "int", "wis", "cha"] as const;

function derivedStats(body: unknown): Json | null {
  if (typeof body !== "object" || body === null) return null;
  const { level, abilities, armor } = body as Json;
  if (!isInteger(level) || level < 1 || level > 20) return null;
  if (typeof abilities !== "object" || abilities === null) return null;
  if (typeof armor !== "object" || armor === null) return null;

  const modifiers: Record<string, number> = {};
  for (const key of ABILITY_KEYS) {
    const score = (abilities as Json)[key];
    if (!isInteger(score) || score < 1 || score > 30) return null;
    modifiers[key] = abilityModifierValue(score);
  }

  const armorObj = armor as Json;
  const base = armorObj.base;
  const shield = armorObj.shield;
  const dexCap = armorObj.dex_cap;
  if (!isInteger(base)) return null;
  if (typeof shield !== "boolean") return null;
  if (!isInteger(dexCap)) return null;

  const proficiencyBonus = proficiencyBonusValue(level);
  const hpMax = level * (6 + modifiers.con!);
  const shieldBonus = shield ? 2 : 0;
  const armorClass = base + Math.min(modifiers.dex!, dexCap) + shieldBonus;

  return {
    level,
    proficiency_bonus: proficiencyBonus,
    hp_max: hpMax,
    armor_class: armorClass,
    modifiers,
  };
}

// --- combat sessions (in-memory state) ---

interface Combatant {
  name: string;
  dex: number;
  score: number;
  conditions: { condition: string; remaining_rounds: number }[];
  tracked: boolean;
}

interface CombatSession {
  id: string;
  round: number;
  turn_index: number;
  order: Combatant[];
}

const combatSessions = new Map<string, CombatSession>();

function activeView(session: CombatSession): Json {
  const active = session.order[session.turn_index]!;
  return { name: active.name, score: active.score };
}

function conditionsView(session: CombatSession): Json {
  const out: Json = {};
  for (const c of session.order) {
    if (c.tracked) {
      out[c.name] = c.conditions.map((x) => ({
        condition: x.condition,
        remaining_rounds: x.remaining_rounds,
      }));
    }
  }
  return out;
}

function sessionSummary(session: CombatSession): Json {
  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeView(session),
    order: session.order.map((c) => ({ name: c.name, score: c.score })),
  };
}

function createCombatSession(body: unknown): Json | null {
  if (typeof body !== "object" || body === null) return null;
  const { id, combatants } = body as Json;
  if (typeof id !== "string" || id === "") return null;
  if (combatSessions.has(id)) return null;
  if (!Array.isArray(combatants) || combatants.length === 0) return null;

  const entries: Combatant[] = [];
  const names = new Set<string>();
  for (const c of combatants) {
    if (typeof c !== "object" || c === null) return null;
    const { name, dex, roll } = c as Json;
    if (typeof name !== "string" || name === "" || !isInteger(dex) || !isInteger(roll)) return null;
    if (names.has(name)) return null;
    names.add(name);
    entries.push({ name, dex, score: roll + dex, conditions: [], tracked: false });
  }

  entries.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });

  const session: CombatSession = { id, round: 1, turn_index: 0, order: entries };
  combatSessions.set(id, session);
  return sessionSummary(session);
}

function addCondition(session: CombatSession, body: unknown): Json | null {
  if (typeof body !== "object" || body === null) return null;
  const { target, condition, duration_rounds } = body as Json;
  if (typeof target !== "string" || typeof condition !== "string") return null;
  if (!isInteger(duration_rounds) || duration_rounds <= 0) return null;
  const combatant = session.order.find((c) => c.name === target);
  if (!combatant) return null;
  combatant.tracked = true;
  combatant.conditions.push({ condition, remaining_rounds: duration_rounds });
  return {
    target,
    conditions: combatant.conditions.map((x) => ({
      condition: x.condition,
      remaining_rounds: x.remaining_rounds,
    })),
  };
}

function advanceTurn(session: CombatSession): Json {
  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }
  const active = session.order[session.turn_index]!;
  active.conditions = active.conditions
    .map((c) => ({ condition: c.condition, remaining_rounds: c.remaining_rounds - 1 }))
    .filter((c) => c.remaining_rounds > 0);
  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeView(session),
    conditions: conditionsView(session),
  };
}

// --- routing ---

const SESSION_RE = /^\/v1\/combat\/sessions\/([^/]+)(\/conditions|\/advance)?$/;

const server = createServer(async (req, res) => {
  const method = req.method ?? "GET";
  const url = req.url ?? "/";

  if (method === "GET" && url === "/health") {
    sendJson(res, 200, { ok: true });
    return;
  }

  if (method === "POST" && url === "/v1/combat/sessions") {
    let body: unknown;
    try {
      body = await readBody(req);
    } catch {
      badRequest(res, "invalid json");
      return;
    }
    const result = createCombatSession(body);
    if (result === null) {
      badRequest(res);
      return;
    }
    sendJson(res, 200, result);
    return;
  }

  if (method === "POST") {
    const m = SESSION_RE.exec(url);
    if (m) {
      const sessionId = decodeURIComponent(m[1]!);
      const sub = m[2];
      const session = combatSessions.get(sessionId);
      if (!session) {
        sendJson(res, 404, { error: "unknown session" });
        return;
      }
      if (sub === "/conditions") {
        let body: unknown;
        try {
          body = await readBody(req);
        } catch {
          badRequest(res, "invalid json");
          return;
        }
        const result = addCondition(session, body);
        if (result === null) {
          badRequest(res);
          return;
        }
        sendJson(res, 200, result);
        return;
      }
      if (sub === "/advance") {
        sendJson(res, 200, advanceTurn(session));
        return;
      }
    }
  }

  const handlers: Record<string, (body: unknown) => Json | null> = {
    "/v1/dice/stats": diceStats,
    "/v1/checks/ability": abilityCheck,
    "/v1/encounters/adjusted-xp": adjustedXp,
    "/v1/initiative/order": initiativeOrder,
    "/v1/characters/ability-modifier": abilityModifier,
    "/v1/characters/proficiency": proficiency,
    "/v1/characters/derived-stats": derivedStats,
  };

  if (method === "POST" && url in handlers) {
    let body: unknown;
    try {
      body = await readBody(req);
    } catch {
      badRequest(res, "invalid json");
      return;
    }
    const result = handlers[url]!(body);
    if (result === null) {
      badRequest(res);
      return;
    }
    sendJson(res, 200, result);
    return;
  }

  sendJson(res, 404, { error: "not found" });
});

server.listen(PORT, HOST, () => {
  console.log(`listening on http://${HOST}:${PORT}`);
});
