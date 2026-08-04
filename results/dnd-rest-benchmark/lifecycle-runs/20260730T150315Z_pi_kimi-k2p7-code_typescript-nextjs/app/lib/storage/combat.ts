/**
 * Combat session repository. Stores turn order, active turn, and conditions.
 */

import { getDb } from "./core.js";
import type { CombatSession, SessionCombatant } from "../types.js";

export function getCombatSession(id: string): CombatSession | null {
  const database = getDb();
  const sessionRow = database
    .prepare("SELECT id, round, turn_index FROM combat_sessions WHERE id = ?")
    .get(id) as { id: string; round: number; turn_index: number } | undefined;
  if (!sessionRow) return null;

  const combatantRows = database
    .prepare(
      "SELECT id, name, score, dex, order_index FROM combatants WHERE session_id = ? ORDER BY order_index"
    )
    .all(id) as Array<{
    id: number;
    name: string;
    score: number;
    dex: number;
    order_index: number;
  }>;

  const combatants: SessionCombatant[] = combatantRows.map((row) => {
    const conditionRows = database
      .prepare(
        "SELECT condition, remaining_rounds FROM conditions WHERE combatant_id = ?"
      )
      .all(row.id) as Array<{ condition: string; remaining_rounds: number }>;
    return {
      name: row.name,
      score: row.score,
      dex: row.dex,
      conditions: conditionRows.map((c) => ({
        condition: c.condition,
        remaining_rounds: c.remaining_rounds,
      })),
    };
  });

  return {
    id: sessionRow.id,
    round: sessionRow.round,
    turn_index: sessionRow.turn_index,
    combatants,
  };
}

export function insertCombatSession(
  id: string,
  combatants: SessionCombatant[]
): boolean {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO combat_sessions (id, round, turn_index) VALUES (?, 1, 0)"
      )
      .run(id);
    for (let i = 0; i < combatants.length; i++) {
      const c = combatants[i];
      const result = database
        .prepare(
          "INSERT INTO combatants (session_id, name, score, dex, order_index) VALUES (?, ?, ?, ?, ?)"
        )
        .run(id, c.name, c.score, c.dex, i);
      const combatantId = result.lastInsertRowid as number;
      for (const cond of c.conditions) {
        database
          .prepare(
            "INSERT INTO conditions (combatant_id, condition, remaining_rounds) VALUES (?, ?, ?)"
          )
          .run(combatantId, cond.condition, cond.remaining_rounds);
      }
    }
    database.exec("COMMIT;");
    return true;
  } catch {
    database.exec("ROLLBACK;");
    return false;
  }
}

/**
 * Replaces the stored combatants and conditions for a session with the current
 * in-memory state. This is intentionally a full rewrite rather than an UPDATE
 * because conditions are owned by combatants and the simplest deterministic path
 * is to delete and reinsert.
 */
export function replaceCombatSession(session: CombatSession): void {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "UPDATE combat_sessions SET round = ?, turn_index = ? WHERE id = ?"
      )
      .run(session.round, session.turn_index, session.id);
    database
      .prepare(
        "DELETE FROM conditions WHERE combatant_id IN (SELECT id FROM combatants WHERE session_id = ?)"
      )
      .run(session.id);
    database
      .prepare("DELETE FROM combatants WHERE session_id = ?")
      .run(session.id);
    for (let i = 0; i < session.combatants.length; i++) {
      const c = session.combatants[i];
      const result = database
        .prepare(
          "INSERT INTO combatants (session_id, name, score, dex, order_index) VALUES (?, ?, ?, ?, ?)"
        )
        .run(session.id, c.name, c.score, c.dex, i);
      const combatantId = result.lastInsertRowid as number;
      for (const cond of c.conditions) {
        database
          .prepare(
            "INSERT INTO conditions (combatant_id, condition, remaining_rounds) VALUES (?, ?, ?)"
          )
          .run(combatantId, cond.condition, cond.remaining_rounds);
      }
    }
    database.exec("COMMIT;");
  } catch (e) {
    database.exec("ROLLBACK;");
    throw e;
  }
}
