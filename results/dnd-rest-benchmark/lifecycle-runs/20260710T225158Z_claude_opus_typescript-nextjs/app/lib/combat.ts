export type Combatant = { name: string; dex: number; score: number };

export type Condition = { condition: string; remaining_rounds: number };

export type Session = {
  id: string;
  round: number;
  turn_index: number;
  order: Combatant[];
  conditions: Map<string, Condition[]>;
};

type Store = { sessions: Map<string, Session> };

const g = globalThis as unknown as { __combatStore?: Store };

export function store(): Store {
  if (!g.__combatStore) {
    g.__combatStore = { sessions: new Map() };
  }
  return g.__combatStore;
}

export function sortCombatants(list: Combatant[]): Combatant[] {
  const copy = list.slice();
  copy.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });
  return copy;
}

export function conditionsObject(s: Session): Record<string, Condition[]> {
  const out: Record<string, Condition[]> = {};
  for (const c of s.order) {
    const list = s.conditions.get(c.name);
    if (list) {
      out[c.name] = list.map((x) => ({ ...x }));
    }
  }
  return out;
}
