import type { IncomingMessage, ServerResponse } from 'node:http';
import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin } from 'vite';

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

type InitiativeEntry = {
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
  order: InitiativeEntry[];
  conditions: Map<string, CombatCondition[]>;
  conditionTargets: Set<string>;
};

const monsterXp: Record<string, number> = {
  '0': 10,
  '1/8': 25,
  '1/4': 50,
  '1/2': 100,
  '1': 200,
  '2': 450,
  '3': 700,
  '4': 1100,
  '5': 1800,
};

const levelThresholds: Record<number, { easy: number; medium: number; hard: number; deadly: number }> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

function sendJson(res: ServerResponse, status: number, body: JsonValue): void {
  const payload = JSON.stringify(body);
  res.statusCode = status;
  res.setHeader('content-type', 'application/json; charset=utf-8');
  res.setHeader('content-length', Buffer.byteLength(payload));
  res.end(payload);
}

function badRequest(res: ServerResponse): void {
  sendJson(res, 400, { error: 'bad_request' });
}

function notFound(res: ServerResponse): void {
  sendJson(res, 404, { error: 'not_found' });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isInteger(value: unknown): value is number {
  return Number.isInteger(value);
}

function isAbilityScore(value: unknown): value is number {
  return isInteger(value) && value >= 1 && value <= 30;
}

function isCharacterLevel(value: unknown): value is number {
  return isInteger(value) && value >= 1 && value <= 20;
}

async function readJson(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  const raw = Buffer.concat(chunks).toString('utf8');
  if (raw.length === 0) {
    throw new Error('empty body');
  }
  return JSON.parse(raw);
}

function diceStats(body: unknown): JsonValue | null {
  if (!isRecord(body) || typeof body.expression !== 'string') {
    return null;
  }

  const match = /^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/.exec(body.expression);
  if (!match) {
    return null;
  }

  const diceCount = Number(match[1]);
  const sides = Number(match[2]);
  const modifierMagnitude = match[4] === undefined ? 0 : Number(match[4]);
  const modifier = match[3] === '-' ? -modifierMagnitude : modifierMagnitude;

  if (!Number.isSafeInteger(diceCount) || !Number.isSafeInteger(sides) || diceCount <= 0 || sides <= 0) {
    return null;
  }

  const min = diceCount + modifier;
  const max = diceCount * sides + modifier;
  return {
    dice_count: diceCount,
    sides,
    modifier,
    min,
    max,
    average: (min + max) / 2,
  };
}

function abilityCheck(body: unknown): JsonValue | null {
  if (!isRecord(body) || !isInteger(body.roll) || !isInteger(body.modifier) || !isInteger(body.dc)) {
    return null;
  }

  const total = body.roll + body.modifier;
  return {
    total,
    success: total >= body.dc,
    margin: total - body.dc,
  };
}

function abilityModifierFor(score: number): number {
  return Math.floor((score - 10) / 2);
}

function proficiencyBonusFor(level: number): number {
  return Math.floor((level - 1) / 4) + 2;
}

function abilityModifier(body: unknown): JsonValue | null {
  if (!isRecord(body) || !isAbilityScore(body.score)) {
    return null;
  }

  return {
    score: body.score,
    modifier: abilityModifierFor(body.score),
  };
}

function proficiencyBonus(body: unknown): JsonValue | null {
  if (!isRecord(body) || !isCharacterLevel(body.level)) {
    return null;
  }

  return {
    level: body.level,
    proficiency_bonus: proficiencyBonusFor(body.level),
  };
}

function derivedStats(body: unknown): JsonValue | null {
  if (!isRecord(body) || !isCharacterLevel(body.level) || !isRecord(body.abilities) || !isRecord(body.armor)) {
    return null;
  }

  const abilityNames = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const;
  for (const abilityName of abilityNames) {
    if (!isAbilityScore(body.abilities[abilityName])) {
      return null;
    }
  }
  const abilities = body.abilities as Record<(typeof abilityNames)[number], number>;

  if (!isInteger(body.armor.base) || typeof body.armor.shield !== 'boolean' || !isInteger(body.armor.dex_cap)) {
    return null;
  }

  const modifiers = {
    str: abilityModifierFor(abilities.str),
    dex: abilityModifierFor(abilities.dex),
    con: abilityModifierFor(abilities.con),
    int: abilityModifierFor(abilities.int),
    wis: abilityModifierFor(abilities.wis),
    cha: abilityModifierFor(abilities.cha),
  };
  const shieldBonus = body.armor.shield ? 2 : 0;

  return {
    level: body.level,
    proficiency_bonus: proficiencyBonusFor(body.level),
    hp_max: body.level * (6 + modifiers.con),
    armor_class: body.armor.base + Math.min(modifiers.dex, body.armor.dex_cap) + shieldBonus,
    modifiers,
  };
}

function monsterMultiplier(count: number): number | null {
  if (count <= 0) return null;
  if (count === 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

function encounterAdjustedXp(body: unknown): JsonValue | null {
  if (!isRecord(body) || !Array.isArray(body.party) || !Array.isArray(body.monsters)) {
    return null;
  }

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of body.party) {
    if (!isRecord(member) || !isInteger(member.level) || levelThresholds[member.level] === undefined) {
      return null;
    }
    const memberThresholds = levelThresholds[member.level];
    thresholds.easy += memberThresholds.easy;
    thresholds.medium += memberThresholds.medium;
    thresholds.hard += memberThresholds.hard;
    thresholds.deadly += memberThresholds.deadly;
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of body.monsters) {
    if (!isRecord(monster) || typeof monster.cr !== 'string' || !isInteger(monster.count) || monster.count <= 0) {
      return null;
    }
    const xp = monsterXp[monster.cr];
    if (xp === undefined) {
      return null;
    }
    baseXp += xp * monster.count;
    monsterCount += monster.count;
  }

  const multiplier = monsterMultiplier(monsterCount);
  if (multiplier === null) {
    return null;
  }

  const adjustedXp = baseXp * multiplier;
  let difficulty = 'trivial';
  if (adjustedXp >= thresholds.easy) difficulty = 'easy';
  if (adjustedXp >= thresholds.medium) difficulty = 'medium';
  if (adjustedXp >= thresholds.hard) difficulty = 'hard';
  if (adjustedXp >= thresholds.deadly) difficulty = 'deadly';

  return {
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty,
    thresholds,
  };
}

function initiativeOrder(body: unknown): JsonValue | null {
  if (!isRecord(body) || !Array.isArray(body.combatants)) {
    return null;
  }

  const combatants = body.combatants.map((combatant) => {
    if (!isRecord(combatant) || typeof combatant.name !== 'string' || !isInteger(combatant.dex) || !isInteger(combatant.roll)) {
      return null;
    }
    return {
      name: combatant.name,
      dex: combatant.dex,
      score: combatant.roll + combatant.dex,
    };
  });

  if (combatants.some((combatant) => combatant === null)) {
    return null;
  }

  const order = combatants
    .toSorted((a, b) => b!.score - a!.score || b!.dex - a!.dex || a!.name.localeCompare(b!.name))
    .map((combatant) => ({ name: combatant!.name, score: combatant!.score }));

  return { order };
}

const combatSessions = new Map<string, CombatSession>();

function toPublicOrder(order: InitiativeEntry[]): JsonValue[] {
  return order.map((combatant) => ({ name: combatant.name, score: combatant.score }));
}

function combatSessionResponse(session: CombatSession): JsonValue {
  const active = session.order[session.turn_index];
  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    order: toPublicOrder(session.order),
  };
}

function publicConditions(session: CombatSession): { [key: string]: JsonValue } {
  const conditions: { [key: string]: JsonValue } = {};
  for (const [target, targetConditions] of session.conditions) {
    if (targetConditions.length > 0 || session.conditionTargets.has(target)) {
      conditions[target] = targetConditions.map((condition) => ({
        condition: condition.condition,
        remaining_rounds: condition.remaining_rounds,
      }));
    }
  }
  return conditions;
}

function createCombatSession(body: unknown): JsonValue | null {
  if (!isRecord(body) || typeof body.id !== 'string' || body.id.length === 0 || !Array.isArray(body.combatants)) {
    return null;
  }
  if (combatSessions.has(body.id) || body.combatants.length === 0) {
    return null;
  }

  const combatants = body.combatants.map((combatant) => {
    if (!isRecord(combatant) || typeof combatant.name !== 'string' || combatant.name.length === 0 || !isInteger(combatant.dex) || !isInteger(combatant.roll)) {
      return null;
    }
    return {
      name: combatant.name,
      dex: combatant.dex,
      score: combatant.roll + combatant.dex,
    };
  });

  if (combatants.some((combatant) => combatant === null)) {
    return null;
  }

  const order = combatants.toSorted((a, b) => b!.score - a!.score || b!.dex - a!.dex || a!.name.localeCompare(b!.name)) as InitiativeEntry[];
  const conditions = new Map<string, CombatCondition[]>();
  for (const combatant of order) {
    conditions.set(combatant.name, []);
  }

  const session: CombatSession = {
    id: body.id,
    round: 1,
    turn_index: 0,
    order,
    conditions,
    conditionTargets: new Set(),
  };
  combatSessions.set(session.id, session);

  return combatSessionResponse(session);
}

function addCombatCondition(session: CombatSession, body: unknown): JsonValue | null {
  if (!isRecord(body) || typeof body.target !== 'string' || typeof body.condition !== 'string' || !isInteger(body.duration_rounds) || body.duration_rounds <= 0) {
    return null;
  }

  const targetConditions = session.conditions.get(body.target);
  if (targetConditions === undefined) {
    return null;
  }

  targetConditions.push({ condition: body.condition, remaining_rounds: body.duration_rounds });
  session.conditionTargets.add(body.target);
  return {
    target: body.target,
    conditions: targetConditions.map((condition) => ({
      condition: condition.condition,
      remaining_rounds: condition.remaining_rounds,
    })),
  };
}

function advanceCombatTurn(session: CombatSession): JsonValue {
  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = session.order[session.turn_index];
  const activeConditions = session.conditions.get(active.name) ?? [];
  const remainingConditions = activeConditions
    .map((condition) => ({ condition: condition.condition, remaining_rounds: condition.remaining_rounds - 1 }))
    .filter((condition) => condition.remaining_rounds > 0);
  session.conditions.set(active.name, remainingConditions);

  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    conditions: publicConditions(session),
  };
}

function dndApiPlugin(): Plugin {
  return {
    name: 'dnd-rest-api',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        if (req.url === undefined || req.method === undefined) {
          next();
          return;
        }

        const pathname = new URL(req.url, 'http://127.0.0.1').pathname;
        if (req.method === 'GET' && pathname === '/health') {
          sendJson(res, 200, { ok: true });
          return;
        }

        if (pathname === '/v1/combat/sessions') {
          if (req.method !== 'POST') {
            sendJson(res, 405, { error: 'method_not_allowed' });
            return;
          }

          try {
            const body = await readJson(req);
            const response = createCombatSession(body);
            if (response === null) {
              badRequest(res);
              return;
            }
            sendJson(res, 200, response);
          } catch {
            badRequest(res);
          }
          return;
        }

        const combatConditionMatch = /^\/v1\/combat\/sessions\/([^/]+)\/conditions$/.exec(pathname);
        if (combatConditionMatch !== null) {
          if (req.method !== 'POST') {
            sendJson(res, 405, { error: 'method_not_allowed' });
            return;
          }

          const session = combatSessions.get(decodeURIComponent(combatConditionMatch[1]));
          if (session === undefined) {
            notFound(res);
            return;
          }

          try {
            const body = await readJson(req);
            const response = addCombatCondition(session, body);
            if (response === null) {
              badRequest(res);
              return;
            }
            sendJson(res, 200, response);
          } catch {
            badRequest(res);
          }
          return;
        }

        const combatAdvanceMatch = /^\/v1\/combat\/sessions\/([^/]+)\/advance$/.exec(pathname);
        if (combatAdvanceMatch !== null) {
          if (req.method !== 'POST') {
            sendJson(res, 405, { error: 'method_not_allowed' });
            return;
          }

          const session = combatSessions.get(decodeURIComponent(combatAdvanceMatch[1]));
          if (session === undefined) {
            notFound(res);
            return;
          }

          sendJson(res, 200, advanceCombatTurn(session));
          return;
        }

        const handlers: Record<string, (body: unknown) => JsonValue | null> = {
          '/v1/dice/stats': diceStats,
          '/v1/checks/ability': abilityCheck,
          '/v1/characters/ability-modifier': abilityModifier,
          '/v1/characters/proficiency': proficiencyBonus,
          '/v1/characters/derived-stats': derivedStats,
          '/v1/encounters/adjusted-xp': encounterAdjustedXp,
          '/v1/initiative/order': initiativeOrder,
        };

        const handler = handlers[pathname];
        if (handler === undefined) {
          next();
          return;
        }

        if (req.method !== 'POST') {
          sendJson(res, 405, { error: 'method_not_allowed' });
          return;
        }

        try {
          const body = await readJson(req);
          const response = handler(body);
          if (response === null) {
            badRequest(res);
            return;
          }
          sendJson(res, 200, response);
        } catch {
          badRequest(res);
        }
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), dndApiPlugin()],
  server: {
    host: '127.0.0.1',
    port: Number(process.env.PORT ?? 5173),
    strictPort: true,
  },
});
