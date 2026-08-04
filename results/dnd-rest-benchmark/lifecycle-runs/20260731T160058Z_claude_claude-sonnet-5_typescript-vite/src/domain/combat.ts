/**
 * Initiative ordering and stateful combat sessions.
 *
 * Combat sessions live in the `combatSessions` in-memory map for fast turn-by-turn
 * access, and are mirrored to SQLite on every mutation so state survives a restart.
 * `loadCombatSessionsFromDb` rehydrates the map at startup; it is the inverse of
 * `persistCombatSession`/`persistCombatConditions`.
 */

import { getDb } from '../db.ts';
import type { ApiResult, JsonValue } from '../types.ts';

export function initiativeOrder(body: JsonValue): ApiResult {
  const combatants = body.combatants;
  if (!Array.isArray(combatants)) {
    return { status: 400, body: { error: 'combatants must be an array' } };
  }

  const scored = combatants.map((c) => {
    const cc = c as JsonValue;
    const name = String(cc.name);
    const dex = Number(cc.dex);
    const roll = Number(cc.roll);
    return { name, dex, score: roll + dex };
  });

  scored.sort(byScoreThenDexThenName);

  return {
    status: 200,
    body: {
      order: scored.map((s) => ({ name: s.name, score: s.score })),
    },
  };
}

interface Condition {
  condition: string;
  remaining_rounds: number;
}

interface CombatSession {
  id: string;
  round: number;
  turn_index: number;
  order: { name: string; score: number; dex: number }[];
  conditions: Record<string, Condition[]>;
}

function byScoreThenDexThenName(
  a: { name: string; dex: number; score: number },
  b: { name: string; dex: number; score: number },
): number {
  if (b.score !== a.score) return b.score - a.score;
  if (b.dex !== a.dex) return b.dex - a.dex;
  return a.name.localeCompare(b.name);
}

const combatSessions = new Map<string, CombatSession>();

function persistCombatSession(session: CombatSession): void {
  const db = getDb();
  db.prepare(
    'INSERT INTO combat_sessions (id, round, turn_index, order_json) VALUES (?, ?, ?, ?) ' +
      'ON CONFLICT(id) DO UPDATE SET round = excluded.round, turn_index = excluded.turn_index, order_json = excluded.order_json',
  ).run(session.id, session.round, session.turn_index, JSON.stringify(session.order));
}

function persistCombatConditions(sessionId: string, target: string, conditions: Condition[]): void {
  const db = getDb();
  db.prepare(
    'INSERT INTO combat_conditions (session_id, target, conditions_json) VALUES (?, ?, ?) ' +
      'ON CONFLICT(session_id, target) DO UPDATE SET conditions_json = excluded.conditions_json',
  ).run(sessionId, target, JSON.stringify(conditions));
}

export function loadCombatSessionsFromDb(): void {
  const db = getDb();
  const rows = db.prepare('SELECT id, round, turn_index, order_json FROM combat_sessions').all() as {
    id: string;
    round: number;
    turn_index: number;
    order_json: string;
  }[];
  for (const row of rows) {
    combatSessions.set(row.id, {
      id: row.id,
      round: row.round,
      turn_index: row.turn_index,
      order: JSON.parse(row.order_json),
      conditions: {},
    });
  }
  const conditionRows = db.prepare('SELECT session_id, target, conditions_json FROM combat_conditions').all() as {
    session_id: string;
    target: string;
    conditions_json: string;
  }[];
  for (const row of conditionRows) {
    const session = combatSessions.get(row.session_id);
    if (session) {
      session.conditions[row.target] = JSON.parse(row.conditions_json);
    }
  }
}

export function clearCombatSessions(): void {
  combatSessions.clear();
}

function activeCombatant(session: CombatSession): { name: string; score: number } {
  const c = session.order[session.turn_index];
  return { name: c.name, score: c.score };
}

function createSessionResponse(session: CombatSession): JsonValue {
  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeCombatant(session),
    order: session.order.map((c) => ({ name: c.name, score: c.score })),
  };
}

export function createCombatSession(body: JsonValue): ApiResult {
  const id = body.id;
  if (typeof id !== 'string' || id.length === 0) {
    return { status: 400, body: { error: 'id must be a non-empty string' } };
  }
  if (combatSessions.has(id)) {
    return { status: 400, body: { error: 'session id already exists' } };
  }

  const combatants = body.combatants;
  if (!Array.isArray(combatants) || combatants.length === 0) {
    return { status: 400, body: { error: 'combatants must be a non-empty array' } };
  }

  const scored: { name: string; dex: number; score: number }[] = [];
  for (const c of combatants) {
    if (typeof c !== 'object' || c === null || Array.isArray(c)) {
      return { status: 400, body: { error: 'invalid combatant entry' } };
    }
    const cc = c as JsonValue;
    const name = cc.name;
    const dex = cc.dex;
    const roll = cc.roll;
    if (typeof name !== 'string' || name.length === 0) {
      return { status: 400, body: { error: 'combatant.name must be a non-empty string' } };
    }
    if (typeof dex !== 'number' || !Number.isFinite(dex)) {
      return { status: 400, body: { error: 'combatant.dex must be a number' } };
    }
    if (typeof roll !== 'number' || !Number.isFinite(roll)) {
      return { status: 400, body: { error: 'combatant.roll must be a number' } };
    }
    scored.push({ name, dex, score: roll + dex });
  }

  scored.sort(byScoreThenDexThenName);

  const session: CombatSession = {
    id,
    round: 1,
    turn_index: 0,
    order: scored,
    conditions: {},
  };
  combatSessions.set(id, session);
  persistCombatSession(session);

  return { status: 200, body: createSessionResponse(session) };
}

export function addCombatCondition(id: string, body: JsonValue): ApiResult {
  const session = combatSessions.get(id);
  if (!session) {
    return { status: 404, body: { error: 'unknown session id' } };
  }

  const target = body.target;
  if (typeof target !== 'string' || !session.order.some((c) => c.name === target)) {
    return { status: 400, body: { error: 'target must name a combatant in the session' } };
  }

  const condition = body.condition;
  if (typeof condition !== 'string' || condition.length === 0) {
    return { status: 400, body: { error: 'condition must be a non-empty string' } };
  }

  const durationRounds = body.duration_rounds;
  if (!Number.isInteger(durationRounds) || (durationRounds as number) <= 0) {
    return { status: 400, body: { error: 'duration_rounds must be a positive integer' } };
  }

  if (!session.conditions[target]) {
    session.conditions[target] = [];
  }
  session.conditions[target].push({ condition, remaining_rounds: durationRounds as number });
  persistCombatConditions(session.id, target, session.conditions[target]);

  return {
    status: 200,
    body: {
      target,
      conditions: session.conditions[target].map((c) => ({ ...c })),
    },
  };
}

export function advanceCombatTurn(id: string): ApiResult {
  const session = combatSessions.get(id);
  if (!session) {
    return { status: 404, body: { error: 'unknown session id' } };
  }

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }
  persistCombatSession(session);

  // Conditions tick down only for the combatant whose turn is starting, D&D-style.
  const active = activeCombatant(session);
  const activeConditions = session.conditions[active.name];
  if (activeConditions) {
    session.conditions[active.name] = activeConditions
      .map((c) => ({ ...c, remaining_rounds: c.remaining_rounds - 1 }))
      .filter((c) => c.remaining_rounds > 0);
    persistCombatConditions(session.id, active.name, session.conditions[active.name]);
  }

  const conditions: JsonValue = {};
  for (const [name, conds] of Object.entries(session.conditions)) {
    conditions[name] = conds.map((c) => ({ ...c }));
  }

  return {
    status: 200,
    body: {
      id: session.id,
      round: session.round,
      turn_index: session.turn_index,
      active,
      conditions,
    },
  };
}
