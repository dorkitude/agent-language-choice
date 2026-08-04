/**
 * Durable combat sessions: persistence plus the response shapes the combat
 * endpoints return. Ordering rules live in `./initiative`.
 */
import { database } from "./db";
import {
  type InitiativeEntry,
  parseInitiativeEntry,
  sortByInitiative,
} from "./initiative";

export type Condition = { condition: string; remaining_rounds: number };

export type Combatant = InitiativeEntry & { conditions: Condition[] };

export type Session = {
  id: string;
  round: number;
  turn_index: number;
  order: Combatant[];
};

/**
 * Sessions are durable: they live in the `combat_sessions` table. The turn
 * order is stored as a JSON column so a session round-trips as one row.
 */
export function getSession(id: string): Session | undefined {
  const row = database()
    .prepare("SELECT id, round, turn_index, order_json FROM combat_sessions WHERE id = ?")
    .get(id) as Record<string, unknown> | undefined;
  if (!row) return undefined;
  return {
    id: row.id as string,
    round: Number(row.round),
    turn_index: Number(row.turn_index),
    order: JSON.parse(row.order_json as string) as Combatant[],
  };
}

export function hasSession(id: string): boolean {
  return getSession(id) !== undefined;
}

export function saveSession(session: Session): void {
  database()
    .prepare(
      `INSERT INTO combat_sessions (id, round, turn_index, order_json)
       VALUES (?, ?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET
         round = excluded.round,
         turn_index = excluded.turn_index,
         order_json = excluded.order_json`,
    )
    .run(session.id, session.round, session.turn_index, JSON.stringify(session.order));
}

/**
 * Build the combatant list from a request payload, or undefined when invalid.
 * Stricter than a one-shot ordering: a stored session addresses combatants by
 * name (conditions target a name), so names must be non-empty and unique.
 */
export function parseCombatants(value: unknown): Combatant[] | undefined {
  if (!Array.isArray(value) || value.length === 0) return undefined;

  const entries: Combatant[] = [];
  const seen = new Set<string>();
  for (const raw of value) {
    const entry = parseInitiativeEntry(raw);
    if (!entry || entry.name === "") return undefined;
    if (seen.has(entry.name)) return undefined;
    seen.add(entry.name);
    entries.push({ ...entry, conditions: [] });
  }
  return sortByInitiative(entries);
}

export function activeCombatant(session: Session): Combatant {
  return session.order[session.turn_index]!;
}

/** Combatants are exposed by name and score only; dex is an internal tiebreaker. */
export function publicCombatant(combatant: Combatant): { name: string; score: number } {
  return { name: combatant.name, score: combatant.score };
}

export function publicConditions(combatant: Combatant): Condition[] {
  return combatant.conditions.map((entry) => ({ ...entry }));
}

/**
 * Conditions keyed by combatant name. Every combatant is present, with an
 * empty list once their conditions have all expired, so callers can keep
 * reading a stable key per combatant.
 */
export function conditionMap(session: Session): Record<string, Condition[]> {
  const result: Record<string, Condition[]> = {};
  for (const combatant of session.order) {
    result[combatant.name] = publicConditions(combatant);
  }
  return result;
}

/** The canonical session body, shared by session create / advance responses. */
export function sessionState(session: Session): Record<string, unknown> {
  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: publicCombatant(activeCombatant(session)),
    order: session.order.map(publicCombatant),
    conditions: conditionMap(session),
  };
}
