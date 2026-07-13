export type Condition = { condition: string; remaining_rounds: number };

export type Combatant = {
  name: string;
  dex: number;
  score: number;
  conditions: Condition[];
  hadCondition: boolean;
};

export type Session = {
  id: string;
  round: number;
  turn_index: number;
  order: Combatant[];
};

import { getDb } from "../db";

export function getSession(id: string): Session | undefined {
  const row = getDb()
    .prepare(
      "SELECT id, round, turn_index, order_json FROM sessions WHERE id = ?"
    )
    .get(id) as
    | { id: string; round: number; turn_index: number; order_json: string }
    | undefined;
  if (!row) return undefined;
  return {
    id: row.id,
    round: row.round,
    turn_index: row.turn_index,
    order: JSON.parse(row.order_json) as Combatant[],
  };
}

export function hasSession(id: string): boolean {
  return getSession(id) !== undefined;
}

export function saveSession(s: Session): void {
  getDb()
    .prepare(
      `INSERT INTO sessions (id, round, turn_index, order_json)
       VALUES (?, ?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET
         round = excluded.round,
         turn_index = excluded.turn_index,
         order_json = excluded.order_json`
    )
    .run(s.id, s.round, s.turn_index, JSON.stringify(s.order));
}

export function activeView(s: Session): { name: string; score: number } {
  const c = s.order[s.turn_index];
  return { name: c.name, score: c.score };
}

export function conditionsView(
  s: Session
): Record<string, Condition[]> {
  const out: Record<string, Condition[]> = {};
  for (const c of s.order) {
    if (c.hadCondition) {
      out[c.name] = c.conditions.map((x) => ({ ...x }));
    }
  }
  return out;
}
