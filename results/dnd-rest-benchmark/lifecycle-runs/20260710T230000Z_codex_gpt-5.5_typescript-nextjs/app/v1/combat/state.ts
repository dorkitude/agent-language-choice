import { db } from "../storage/db.js";

export type InitiativeEntry = {
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
  turn_index: number;
  order: InitiativeEntry[];
  conditions: Map<string, Condition[]>;
};

function parseSession(row: Record<string, unknown>): CombatSession | undefined {
  if (
    typeof row.id !== "string" ||
    typeof row.round !== "number" ||
    typeof row.turn_index !== "number" ||
    typeof row.order_json !== "string" ||
    typeof row.conditions_json !== "string"
  ) {
    return undefined;
  }

  const order = JSON.parse(row.order_json) as InitiativeEntry[];
  const conditionEntries = JSON.parse(row.conditions_json) as [string, Condition[]][];

  return {
    id: row.id,
    round: row.round,
    turn_index: row.turn_index,
    order,
    conditions: new Map(conditionEntries),
  };
}

export const sessions = {
  get(id: string): CombatSession | undefined {
    const row = db()
      .prepare("SELECT id, round, turn_index, order_json, conditions_json FROM combat_sessions WHERE id = ?")
      .get(id);

    return row === undefined ? undefined : parseSession(row);
  },

  has(id: string): boolean {
    return this.get(id) !== undefined;
  },

  set(id: string, session: CombatSession): void {
    db()
      .prepare(
        `INSERT OR REPLACE INTO combat_sessions (id, round, turn_index, order_json, conditions_json)
         VALUES (?, ?, ?, ?, ?)`,
      )
      .run(
        id,
        session.round,
        session.turn_index,
        JSON.stringify(session.order),
        JSON.stringify([...session.conditions.entries()]),
      );
  },
};

export function publicOrder(order: InitiativeEntry[]) {
  return order.map(({ name, score }) => ({ name, score }));
}

export function sessionSummary(session: CombatSession) {
  const active = session.order[session.turn_index];

  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    order: publicOrder(session.order),
  };
}

export function conditionListFor(session: CombatSession, target: string): Condition[] {
  return session.conditions.get(target) ?? [];
}

export function publicConditions(session: CombatSession): Record<string, Condition[]> {
  const conditions: Record<string, Condition[]> = {};

  for (const [target, targetConditions] of session.conditions) {
    conditions[target] = targetConditions.map(({ condition, remaining_rounds }) => ({ condition, remaining_rounds }));
  }

  return conditions;
}
