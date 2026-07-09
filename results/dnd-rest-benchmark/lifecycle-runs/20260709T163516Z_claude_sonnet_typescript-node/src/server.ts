import { createServer, IncomingMessage, ServerResponse } from "node:http";

const PORT = Number(process.env.PORT ?? "3000");
const HOST = "127.0.0.1";

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

function multiplierForCount(count: number): number {
  if (count <= 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(payload);
}

async function readJsonBody(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    chunks.push(chunk as Buffer);
  }
  if (chunks.length === 0) return {};
  const text = Buffer.concat(chunks).toString("utf8");
  if (text.trim() === "") return {};
  return JSON.parse(text);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function handleDiceStats(body: unknown): { status: number; body: unknown } {
  if (!isPlainObject(body) || typeof body.expression !== "string") {
    return { status: 400, body: { error: "invalid expression" } };
  }
  const match = /^(\d+)d(\d+)([+-]\d+)?$/.exec(body.expression.trim());
  if (!match) {
    return { status: 400, body: { error: "invalid expression" } };
  }
  const diceCount = Number(match[1]);
  const sides = Number(match[2]);
  const modifier = match[3] ? Number(match[3]) : 0;
  if (diceCount <= 0 || sides <= 0) {
    return { status: 400, body: { error: "invalid expression" } };
  }
  const min = diceCount * 1 + modifier;
  const max = diceCount * sides + modifier;
  const average = (diceCount * (sides + 1)) / 2 + modifier;
  return {
    status: 200,
    body: {
      dice_count: diceCount,
      sides,
      modifier,
      min,
      max,
      average,
    },
  };
}

function handleAbilityCheck(body: unknown): { status: number; body: unknown } {
  if (
    !isPlainObject(body) ||
    typeof body.roll !== "number" ||
    typeof body.modifier !== "number" ||
    typeof body.dc !== "number"
  ) {
    return { status: 400, body: { error: "invalid request" } };
  }
  const total = body.roll + body.modifier;
  const success = total >= body.dc;
  const margin = total - body.dc;
  return { status: 200, body: { total, success, margin } };
}

function handleAdjustedXp(body: unknown): { status: number; body: unknown } {
  if (!isPlainObject(body) || !Array.isArray(body.party) || !Array.isArray(body.monsters)) {
    return { status: 400, body: { error: "invalid request" } };
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of body.monsters) {
    if (!isPlainObject(monster) || typeof monster.cr !== "string" || typeof monster.count !== "number") {
      return { status: 400, body: { error: "invalid monster" } };
    }
    const xp = CR_XP[monster.cr];
    if (xp === undefined) {
      return { status: 400, body: { error: "unsupported cr" } };
    }
    baseXp += xp * monster.count;
    monsterCount += monster.count;
  }

  const multiplier = multiplierForCount(monsterCount);
  const adjustedXp = baseXp * multiplier;

  let easy = 0;
  let medium = 0;
  let hard = 0;
  let deadly = 0;
  for (const member of body.party) {
    if (!isPlainObject(member) || typeof member.level !== "number") {
      return { status: 400, body: { error: "invalid party member" } };
    }
    const thresholds = LEVEL_THRESHOLDS[member.level];
    if (!thresholds) {
      return { status: 400, body: { error: "unsupported level" } };
    }
    easy += thresholds.easy;
    medium += thresholds.medium;
    hard += thresholds.hard;
    deadly += thresholds.deadly;
  }

  let difficulty = "trivial";
  if (adjustedXp >= deadly) difficulty = "deadly";
  else if (adjustedXp >= hard) difficulty = "hard";
  else if (adjustedXp >= medium) difficulty = "medium";
  else if (adjustedXp >= easy) difficulty = "easy";

  return {
    status: 200,
    body: {
      base_xp: baseXp,
      monster_count: monsterCount,
      multiplier,
      adjusted_xp: adjustedXp,
      difficulty,
      thresholds: { easy, medium, hard, deadly },
    },
  };
}

function handleInitiativeOrder(body: unknown): { status: number; body: unknown } {
  if (!isPlainObject(body) || !Array.isArray(body.combatants)) {
    return { status: 400, body: { error: "invalid request" } };
  }

  const combatants: { name: string; dex: number; score: number }[] = [];
  for (const c of body.combatants) {
    if (
      !isPlainObject(c) ||
      typeof c.name !== "string" ||
      typeof c.dex !== "number" ||
      typeof c.roll !== "number"
    ) {
      return { status: 400, body: { error: "invalid combatant" } };
    }
    combatants.push({ name: c.name, dex: c.dex, score: c.roll + c.dex });
  }

  combatants.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });

  return {
    status: 200,
    body: { order: combatants.map((c) => ({ name: c.name, score: c.score })) },
  };
}

function isValidInteger(value: unknown, min: number, max: number): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= min && value <= max;
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

function handleAbilityModifier(body: unknown): { status: number; body: unknown } {
  if (!isPlainObject(body) || !isValidInteger(body.score, 1, 30)) {
    return { status: 400, body: { error: "invalid request" } };
  }
  return { status: 200, body: { score: body.score, modifier: abilityModifier(body.score) } };
}

function handleProficiency(body: unknown): { status: number; body: unknown } {
  if (!isPlainObject(body) || !isValidInteger(body.level, 1, 20)) {
    return { status: 400, body: { error: "invalid request" } };
  }
  return { status: 200, body: { level: body.level, proficiency_bonus: proficiencyBonus(body.level) } };
}

const ABILITY_KEYS = ["str", "dex", "con", "int", "wis", "cha"] as const;

function handleDerivedStats(body: unknown): { status: number; body: unknown } {
  if (!isPlainObject(body) || !isValidInteger(body.level, 1, 20)) {
    return { status: 400, body: { error: "invalid request" } };
  }
  if (!isPlainObject(body.abilities)) {
    return { status: 400, body: { error: "invalid abilities" } };
  }
  const modifiers: Record<string, number> = {};
  for (const key of ABILITY_KEYS) {
    const score = body.abilities[key];
    if (!isValidInteger(score, 1, 30)) {
      return { status: 400, body: { error: "invalid abilities" } };
    }
    modifiers[key] = abilityModifier(score);
  }
  if (!isPlainObject(body.armor) || typeof body.armor.base !== "number" || typeof body.armor.dex_cap !== "number") {
    return { status: 400, body: { error: "invalid armor" } };
  }
  const shieldBonus = body.armor.shield === true ? 2 : 0;
  const armorClass = body.armor.base + Math.min(modifiers.dex, body.armor.dex_cap) + shieldBonus;
  const hpMax = body.level * (6 + modifiers.con);

  return {
    status: 200,
    body: {
      level: body.level,
      proficiency_bonus: proficiencyBonus(body.level),
      hp_max: hpMax,
      armor_class: armorClass,
      modifiers,
    },
  };
}

interface Condition {
  condition: string;
  remaining_rounds: number;
}

interface Combatant {
  name: string;
  dex: number;
  score: number;
  conditions: Condition[];
}

interface CombatSession {
  id: string;
  round: number;
  turn_index: number;
  order: Combatant[];
}

const combatSessions = new Map<string, CombatSession>();

function activeSummary(session: CombatSession): { name: string; score: number } {
  const active = session.order[session.turn_index];
  return { name: active.name, score: active.score };
}

function orderSummary(session: CombatSession): { name: string; score: number }[] {
  return session.order.map((c) => ({ name: c.name, score: c.score }));
}

function handleCreateCombatSession(body: unknown): { status: number; body: unknown } {
  if (!isPlainObject(body) || typeof body.id !== "string" || body.id === "" || !Array.isArray(body.combatants)) {
    return { status: 400, body: { error: "invalid request" } };
  }
  if (combatSessions.has(body.id)) {
    return { status: 400, body: { error: "session already exists" } };
  }
  if (body.combatants.length === 0) {
    return { status: 400, body: { error: "invalid combatants" } };
  }

  const combatants: Combatant[] = [];
  for (const c of body.combatants) {
    if (
      !isPlainObject(c) ||
      typeof c.name !== "string" ||
      typeof c.dex !== "number" ||
      typeof c.roll !== "number"
    ) {
      return { status: 400, body: { error: "invalid combatant" } };
    }
    combatants.push({ name: c.name, dex: c.dex, score: c.roll + c.dex, conditions: [] });
  }

  combatants.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });

  const session: CombatSession = {
    id: body.id,
    round: 1,
    turn_index: 0,
    order: combatants,
  };
  combatSessions.set(session.id, session);

  return {
    status: 200,
    body: {
      id: session.id,
      round: session.round,
      turn_index: session.turn_index,
      active: activeSummary(session),
      order: orderSummary(session),
    },
  };
}

function handleAddCondition(sessionId: string, body: unknown): { status: number; body: unknown } {
  const session = combatSessions.get(sessionId);
  if (!session) {
    return { status: 404, body: { error: "session not found" } };
  }
  if (
    !isPlainObject(body) ||
    typeof body.target !== "string" ||
    typeof body.condition !== "string" ||
    !isValidInteger(body.duration_rounds, 1, Number.MAX_SAFE_INTEGER)
  ) {
    return { status: 400, body: { error: "invalid request" } };
  }
  const target = session.order.find((c) => c.name === body.target);
  if (!target) {
    return { status: 400, body: { error: "unknown target" } };
  }
  target.conditions.push({ condition: body.condition, remaining_rounds: body.duration_rounds });

  return {
    status: 200,
    body: {
      target: target.name,
      conditions: target.conditions.map((c) => ({ condition: c.condition, remaining_rounds: c.remaining_rounds })),
    },
  };
}

function handleAdvanceTurn(sessionId: string): { status: number; body: unknown } {
  const session = combatSessions.get(sessionId);
  if (!session) {
    return { status: 404, body: { error: "session not found" } };
  }

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = session.order[session.turn_index];
  active.conditions = active.conditions
    .map((c) => ({ ...c, remaining_rounds: c.remaining_rounds - 1 }))
    .filter((c) => c.remaining_rounds > 0);

  const conditions: Record<string, Condition[]> = {};
  for (const c of session.order) {
    conditions[c.name] = c.conditions.map((cond) => ({ condition: cond.condition, remaining_rounds: cond.remaining_rounds }));
  }

  return {
    status: 200,
    body: {
      id: session.id,
      round: session.round,
      turn_index: session.turn_index,
      active: activeSummary(session),
      conditions,
    },
  };
}

const server = createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/health") {
      sendJson(res, 200, { ok: true });
      return;
    }

    if (req.method === "POST" && req.url === "/v1/dice/stats") {
      const body = await readJsonBody(req);
      const result = handleDiceStats(body);
      sendJson(res, result.status, result.body);
      return;
    }

    if (req.method === "POST" && req.url === "/v1/checks/ability") {
      const body = await readJsonBody(req);
      const result = handleAbilityCheck(body);
      sendJson(res, result.status, result.body);
      return;
    }

    if (req.method === "POST" && req.url === "/v1/encounters/adjusted-xp") {
      const body = await readJsonBody(req);
      const result = handleAdjustedXp(body);
      sendJson(res, result.status, result.body);
      return;
    }

    if (req.method === "POST" && req.url === "/v1/initiative/order") {
      const body = await readJsonBody(req);
      const result = handleInitiativeOrder(body);
      sendJson(res, result.status, result.body);
      return;
    }

    if (req.method === "POST" && req.url === "/v1/characters/ability-modifier") {
      const body = await readJsonBody(req);
      const result = handleAbilityModifier(body);
      sendJson(res, result.status, result.body);
      return;
    }

    if (req.method === "POST" && req.url === "/v1/characters/proficiency") {
      const body = await readJsonBody(req);
      const result = handleProficiency(body);
      sendJson(res, result.status, result.body);
      return;
    }

    if (req.method === "POST" && req.url === "/v1/characters/derived-stats") {
      const body = await readJsonBody(req);
      const result = handleDerivedStats(body);
      sendJson(res, result.status, result.body);
      return;
    }

    if (req.method === "POST" && req.url === "/v1/combat/sessions") {
      const body = await readJsonBody(req);
      const result = handleCreateCombatSession(body);
      sendJson(res, result.status, result.body);
      return;
    }

    const conditionsMatch = req.url ? /^\/v1\/combat\/sessions\/([^/]+)\/conditions$/.exec(req.url) : null;
    if (req.method === "POST" && conditionsMatch) {
      const body = await readJsonBody(req);
      const result = handleAddCondition(decodeURIComponent(conditionsMatch[1]), body);
      sendJson(res, result.status, result.body);
      return;
    }

    const advanceMatch = req.url ? /^\/v1\/combat\/sessions\/([^/]+)\/advance$/.exec(req.url) : null;
    if (req.method === "POST" && advanceMatch) {
      const result = handleAdvanceTurn(decodeURIComponent(advanceMatch[1]));
      sendJson(res, result.status, result.body);
      return;
    }

    sendJson(res, 404, { error: "not found" });
  } catch (err) {
    sendJson(res, 400, { error: "invalid request" });
  }
});

server.listen(PORT, HOST, () => {
  // eslint-disable-next-line no-console
  console.log(`listening on ${HOST}:${PORT}`);
});
