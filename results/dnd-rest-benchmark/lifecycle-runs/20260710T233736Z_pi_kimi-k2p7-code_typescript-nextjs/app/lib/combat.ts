import { getDb } from "./db.js";

export interface CombatantInput {
  name: string;
  dex: number;
  roll: number;
}

export interface CombatantOrder {
  name: string;
  score: number;
}

export interface Condition {
  condition: string;
  remaining_rounds: number;
}

export interface CombatSession {
  id: string;
  round: number;
  turn_index: number;
  order: CombatantOrder[];
  conditions: Record<string, Condition[]>;
}

function rowToSession(
  row: Record<string, unknown> | undefined
): CombatSession | undefined {
  if (!row) return undefined;
  return {
    id: String(row.id),
    round: Number(row.round),
    turn_index: Number(row.turn_index),
    order: JSON.parse(String(row.order_json)),
    conditions: JSON.parse(String(row.conditions_json)),
  };
}

function getSessionById(id: string): CombatSession | undefined {
  const db = getDb();
  const row = db
    .prepare(
      "SELECT id, round, turn_index, order_json, conditions_json FROM combat_sessions WHERE id = ?"
    )
    .get(id);
  return rowToSession(row);
}

function saveSession(session: CombatSession): void {
  const db = getDb();
  db.prepare(
    `
    INSERT INTO combat_sessions (id, round, turn_index, order_json, conditions_json)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
      round = excluded.round,
      turn_index = excluded.turn_index,
      order_json = excluded.order_json,
      conditions_json = excluded.conditions_json
    `
  ).run(
    session.id,
    session.round,
    session.turn_index,
    JSON.stringify(session.order),
    JSON.stringify(session.conditions)
  );
}

export function createSession(
  id: unknown,
  combatants: unknown
): CombatSession {
  if (typeof id !== "string" || id.length === 0) {
    throw new Error("id must be a non-empty string");
  }
  if (!Array.isArray(combatants) || combatants.length === 0) {
    throw new Error("combatants must be a non-empty array");
  }

  const seen = new Set<string>();
  for (const c of combatants) {
    if (typeof c !== "object" || c === null) {
      throw new Error("each combatant must be an object");
    }
    const combatant = c as Record<string, unknown>;
    if (typeof combatant.name !== "string" || combatant.name.length === 0) {
      throw new Error("combatant name must be a non-empty string");
    }
    if (seen.has(combatant.name)) {
      throw new Error("combatant names must be unique");
    }
    seen.add(combatant.name);
    if (
      typeof combatant.dex !== "number" ||
      !Number.isInteger(combatant.dex)
    ) {
      throw new Error("combatant dex must be an integer");
    }
    if (
      typeof combatant.roll !== "number" ||
      !Number.isInteger(combatant.roll)
    ) {
      throw new Error("combatant roll must be an integer");
    }
  }

  const db = getDb();
  const existing = db
    .prepare("SELECT id FROM combat_sessions WHERE id = ?")
    .get(id);
  if (existing) {
    throw new Error("session id already exists");
  }

  const order = (combatants as CombatantInput[])
    .map((c) => ({ name: c.name, score: c.roll + c.dex, dex: c.dex }))
    .sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      if (b.dex !== a.dex) return b.dex - a.dex;
      return a.name.localeCompare(b.name);
    })
    .map(({ name, score }) => ({ name, score }));

  const session: CombatSession = {
    id,
    round: 1,
    turn_index: 0,
    order,
    conditions: {},
  };

  saveSession(session);
  return session;
}

export function addCondition(
  sessionId: string,
  target: unknown,
  condition: unknown,
  durationRounds: unknown
): { target: string; conditions: Condition[] } {
  const session = getSessionById(sessionId);
  if (!session) {
    throw new Error("session not found");
  }

  if (typeof target !== "string" || target.length === 0) {
    throw new Error("target must be a non-empty string");
  }
  if (!session.order.some((c) => c.name === target)) {
    throw new Error("target must be a combatant in the session");
  }
  if (typeof condition !== "string") {
    throw new Error("condition must be a string");
  }
  if (
    typeof durationRounds !== "number" ||
    !Number.isInteger(durationRounds) ||
    durationRounds <= 0
  ) {
    throw new Error("duration_rounds must be a positive integer");
  }

  const newCondition: Condition = {
    condition,
    remaining_rounds: durationRounds,
  };
  session.conditions[target] = [
    ...(session.conditions[target] ?? []),
    newCondition,
  ];

  saveSession(session);
  return { target, conditions: session.conditions[target] };
}

export function advanceTurn(sessionId: string): {
  id: string;
  round: number;
  turn_index: number;
  active: CombatantOrder;
  conditions: Record<string, Condition[]>;
} {
  const session = getSessionById(sessionId);
  if (!session) {
    throw new Error("session not found");
  }

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const activeName = session.order[session.turn_index].name;
  const activeConditions = session.conditions[activeName] ?? [];
  const remaining = activeConditions
    .map((c) => ({ ...c, remaining_rounds: c.remaining_rounds - 1 }))
    .filter((c) => c.remaining_rounds > 0);

  if (activeConditions.length > 0) {
    session.conditions[activeName] = remaining;
  } else {
    delete session.conditions[activeName];
  }

  saveSession(session);

  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: session.order[session.turn_index],
    conditions: session.conditions,
  };
}
