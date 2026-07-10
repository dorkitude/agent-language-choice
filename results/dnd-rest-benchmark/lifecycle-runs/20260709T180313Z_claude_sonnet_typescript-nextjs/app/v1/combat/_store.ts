export interface Condition {
  condition: string;
  remaining_rounds: number;
}

export interface Combatant {
  name: string;
  dex: number;
  roll: number;
  score: number;
  conditions: Condition[];
}

export interface CombatSession {
  id: string;
  round: number;
  turn_index: number;
  order: Combatant[];
}

export const sessions = new Map<string, CombatSession>();

export function publicCombatant(c: Combatant) {
  return { name: c.name, score: c.score };
}

export function publicSession(session: CombatSession) {
  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: publicCombatant(session.order[session.turn_index]),
    order: session.order.map(publicCombatant),
  };
}
