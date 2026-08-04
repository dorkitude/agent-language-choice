// Combat session and condition persistence.

import { db } from './connection.js';
import type { CombatSession, Condition } from '../types.js';

export function createCombatSession(session: CombatSession): void {
  db.prepare('INSERT INTO combat_sessions (id, round, turn_index, combatants, order_data) VALUES (?, ?, ?, ?, ?)').run(
    session.id,
    session.round,
    session.turn_index,
    JSON.stringify(session.combatants),
    JSON.stringify(session.order),
  );
}

export function combatSessionExists(id: string): boolean {
  const row = db.prepare('SELECT 1 FROM combat_sessions WHERE id = ?').get(id) as { '1': number } | undefined;
  return row !== undefined;
}

export function getCombatSession(id: string): CombatSession | undefined {
  const row = db.prepare('SELECT id, round, turn_index, combatants, order_data FROM combat_sessions WHERE id = ?').get(id) as
    | { id: string; round: number; turn_index: number; combatants: string; order_data: string }
    | undefined;
  if (!row) return undefined;
  const combatants = JSON.parse(row.combatants) as CombatSession['combatants'];
  return {
    id: row.id,
    round: row.round,
    turn_index: row.turn_index,
    combatants,
    order: JSON.parse(row.order_data) as CombatSession['order'],
    conditions: getConditions(id, combatants.map((c) => c.name)),
  };
}

export function updateCombatSessionRound(id: string, round: number, turnIndex: number): void {
  db.prepare('UPDATE combat_sessions SET round = ?, turn_index = ? WHERE id = ?').run(round, turnIndex, id);
}

export function getConditions(sessionId: string, combatantNames?: string[]): Record<string, Condition[]> {
  const rows = db.prepare('SELECT target, condition, remaining_rounds FROM conditions WHERE session_id = ?').all(sessionId) as {
    target: string;
    condition: string;
    remaining_rounds: number;
  }[];
  const result: Record<string, Condition[]> = {};
  if (combatantNames) {
    for (const name of combatantNames) {
      result[name] = [];
    }
  }
  for (const row of rows) {
    if (!result[row.target]) result[row.target] = [];
    result[row.target].push({ condition: row.condition, remaining_rounds: row.remaining_rounds });
  }
  return result;
}

export function getConditionsForTarget(sessionId: string, target: string): Condition[] {
  const rows = db.prepare('SELECT condition, remaining_rounds FROM conditions WHERE session_id = ? AND target = ?').all(sessionId, target) as {
    condition: string;
    remaining_rounds: number;
  }[];
  return rows.map((row) => ({ condition: row.condition, remaining_rounds: row.remaining_rounds }));
}

export function addCombatCondition(sessionId: string, target: string, condition: string, remainingRounds: number): void {
  db.prepare('INSERT INTO conditions (session_id, target, condition, remaining_rounds) VALUES (?, ?, ?, ?)').run(
    sessionId,
    target,
    condition,
    remainingRounds,
  );
}

export function decrementConditions(sessionId: string, target: string): void {
  db.prepare('UPDATE conditions SET remaining_rounds = remaining_rounds - 1 WHERE session_id = ? AND target = ?').run(
    sessionId,
    target,
  );
  db.prepare('DELETE FROM conditions WHERE session_id = ? AND target = ? AND remaining_rounds <= 0').run(sessionId, target);
}
