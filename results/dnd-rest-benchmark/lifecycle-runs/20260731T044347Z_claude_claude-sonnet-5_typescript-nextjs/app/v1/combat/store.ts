import { getDb } from "../db.js";

export interface Condition {
  condition: string;
  remaining_rounds: number;
}

export interface Combatant {
  name: string;
  dex: number;
  score: number;
  conditions: Condition[];
}

export interface CombatSession {
  id: string;
  round: number;
  turn_index: number;
  order: Combatant[];
}

export function saveSession(session: CombatSession): void {
  getDb()
    .prepare("UPDATE combat_sessions SET data = ? WHERE id = ?")
    .run(JSON.stringify(session), session.id);
}

export function getSession(id: string): CombatSession | undefined {
  const row = getDb()
    .prepare("SELECT data FROM combat_sessions WHERE id = ?")
    .get(id) as { data: string } | undefined;

  if (!row) return undefined;

  return JSON.parse(row.data) as CombatSession;
}

export function hasSession(id: string): boolean {
  const row = getDb()
    .prepare("SELECT id FROM combat_sessions WHERE id = ?")
    .get(id);
  return row !== undefined;
}

export function createSession(session: CombatSession): void {
  getDb()
    .prepare("INSERT INTO combat_sessions (id, data) VALUES (?, ?)")
    .run(session.id, JSON.stringify(session));
}
