export interface Condition {
  condition: string;
  remaining_rounds: number;
}

export interface OrderEntry {
  name: string;
  dex: number;
  score: number;
}

export interface CombatSession {
  id: string;
  round: number;
  turn_index: number;
  order: OrderEntry[];
  conditions: Record<string, Condition[]>;
}

const sessions = new Map<string, CombatSession>();

export function getSession(id: string): CombatSession | undefined {
  return sessions.get(id);
}

export function hasSession(id: string): boolean {
  return sessions.has(id);
}

export function createSession(session: CombatSession): void {
  sessions.set(session.id, session);
}
