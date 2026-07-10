// In-memory combat session store.
//
// State only needs to last for the lifetime of the server process. We attach
// the Map to `globalThis` so that even if Next.js bundles this shared module
// separately into each route chunk, all routes see the same singleton store
// within the single `next start` process.

export interface Condition {
  condition: string;
  remaining_rounds: number;
}

export interface Combatant {
  name: string;
  dex: number;
  roll: number;
  score: number;
}

export interface Session {
  id: string;
  order: Combatant[]; // sorted initiative order
  round: number;
  turn_index: number;
  conditions: Record<string, Condition[]>; // keyed by combatant name
}

const STORE_KEY = '__dnd_combat_sessions__';

type GlobalWithStore = typeof globalThis & {
  [STORE_KEY]?: Map<string, Session>;
};

function store(): Map<string, Session> {
  const g = globalThis as GlobalWithStore;
  if (!g[STORE_KEY]) g[STORE_KEY] = new Map<string, Session>();
  return g[STORE_KEY]!;
}

export function getSession(id: string): Session | undefined {
  return store().get(id);
}

export function putSession(session: Session): void {
  store().set(session.id, session);
}
