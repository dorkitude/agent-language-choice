export type Condition = { condition: string; remaining_rounds: number };

export type Combatant = {
  name: string;
  dex: number;
  score: number;
  conditions: Condition[];
  everHadConditions: boolean;
};

export type Session = {
  id: string;
  round: number;
  turn_index: number;
  order: Combatant[];
};

const globalStore = globalThis as unknown as {
  __combatSessions?: Map<string, Session>;
};

export const sessions: Map<string, Session> =
  globalStore.__combatSessions ?? (globalStore.__combatSessions = new Map());

export function orderView(order: Combatant[]) {
  return order.map((c) => ({ name: c.name, score: c.score }));
}

export function conditionsView(order: Combatant[]) {
  const out: Record<string, Condition[]> = {};
  for (const c of order) {
    if (c.conditions.length > 0 || c.everHadConditions) {
      out[c.name] = c.conditions.map((cond) => ({
        condition: cond.condition,
        remaining_rounds: cond.remaining_rounds,
      }));
    }
  }
  return out;
}
