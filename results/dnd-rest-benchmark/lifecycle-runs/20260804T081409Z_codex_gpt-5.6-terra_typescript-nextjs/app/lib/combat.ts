import { database } from "./storage";

export type InitiativeCombatant = {
  name: string;
  dex: number;
  score: number;
};

export type Condition = {
  condition: string;
  remaining_rounds: number;
};

export type CombatSession = {
  id: string;
  round: number;
  turnIndex: number;
  order: InitiativeCombatant[];
  conditions: Map<string, Condition[]>;
};

export function getSession(id: string) {
  const row = database.prepare("SELECT id, round, turn_index AS turnIndex, order_json AS orderJson FROM combat_sessions WHERE id = ?").get(id) as
    { id: string; round: number; turnIndex: number; orderJson: string } | undefined;
  if (!row) return undefined;
  const conditionRows = database.prepare("SELECT target, condition, remaining_rounds AS remainingRounds FROM combat_conditions WHERE session_id = ? ORDER BY rowid").all(id) as
    { target: string; condition: string; remainingRounds: number }[];
  const conditions = new Map<string, Condition[]>();
  for (const item of conditionRows) {
    const values = conditions.get(item.target) ?? [];
    values.push({ condition: item.condition, remaining_rounds: item.remainingRounds });
    conditions.set(item.target, values);
  }
  return { id: row.id, round: row.round, turnIndex: row.turnIndex, order: JSON.parse(row.orderJson) as InitiativeCombatant[], conditions };
}

export function createSession(id: string, order: InitiativeCombatant[]) {
  const session: CombatSession = {
    id,
    round: 1,
    turnIndex: 0,
    order,
    conditions: new Map(),
  };
  database.prepare("INSERT INTO combat_sessions (id, round, turn_index, order_json) VALUES (?, ?, ?, ?)").run(
    id, session.round, session.turnIndex, JSON.stringify(order),
  );
  return session;
}

export function hasSession(id: string) {
  return Boolean(database.prepare("SELECT 1 FROM combat_sessions WHERE id = ?").get(id));
}

export function saveSession(session: CombatSession) {
  database.prepare("UPDATE combat_sessions SET round = ?, turn_index = ? WHERE id = ?").run(session.round, session.turnIndex, session.id);
  database.prepare("DELETE FROM combat_conditions WHERE session_id = ?").run(session.id);
  const insert = database.prepare("INSERT INTO combat_conditions (session_id, target, condition, remaining_rounds) VALUES (?, ?, ?, ?)");
  for (const [target, conditions] of session.conditions) {
    for (const item of conditions) insert.run(session.id, target, item.condition, item.remaining_rounds);
  }
}

export function sessionSummary(session: CombatSession) {
  const active = session.order[session.turnIndex];
  return {
    id: session.id,
    round: session.round,
    turn_index: session.turnIndex,
    active: { name: active.name, score: active.score },
    order: session.order.map(({ name, score }) => ({ name, score })),
  };
}

export function conditionSummary(session: CombatSession) {
  return Object.fromEntries(
    [...session.conditions.entries()].map(([name, conditions]) => [
      name,
      conditions.map(({ condition, remaining_rounds }) => ({ condition, remaining_rounds })),
    ]),
  );
}
