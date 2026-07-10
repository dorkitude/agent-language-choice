export type InitiativeEntry = {
  name: string;
  dex: number;
  score: number;
};

export type CombatCondition = {
  condition: string;
  remaining_rounds: number;
};

export type CombatSession = {
  id: string;
  round: number;
  turn_index: number;
  order: InitiativeEntry[];
  conditions: Map<string, CombatCondition[]>;
};

export const sessions = new Map<string, CombatSession>();

export function publicOrder(order: InitiativeEntry[]) {
  return order.map(({ name, score }) => ({ name, score }));
}

export function activeCombatant(session: CombatSession) {
  const active = session.order[session.turn_index];
  return { name: active.name, score: active.score };
}

export function conditionRecord(session: CombatSession, includeEmptyNames: string[] = []) {
  const conditions: Record<string, CombatCondition[]> = {};
  const includeEmpty = new Set(includeEmptyNames);

  for (const [name, entries] of session.conditions) {
    if (entries.length > 0 || includeEmpty.has(name)) {
      conditions[name] = entries.map(({ condition, remaining_rounds }) => ({
        condition,
        remaining_rounds,
      }));
    }
  }

  return conditions;
}
