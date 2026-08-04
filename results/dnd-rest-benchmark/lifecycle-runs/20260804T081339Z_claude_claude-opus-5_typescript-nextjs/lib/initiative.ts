/**
 * Initiative ordering: pure, stateless, and free of any database import.
 *
 * Both the one-shot `/v1/initiative/order` endpoint and the durable combat
 * sessions in `./combat` build on these, so a tie breaks the same way whether
 * or not the roll is being persisted.
 */
import { asInteger, isObject } from "./validation";

export type InitiativeEntry = {
  name: string;
  dex: number;
  score: number;
};

/** Score descending, then dex descending, then name ascending. Total and deterministic. */
export function compareInitiative(a: InitiativeEntry, b: InitiativeEntry): number {
  if (a.score !== b.score) return b.score - a.score;
  if (a.dex !== b.dex) return b.dex - a.dex;
  return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
}

/** Sort in place — callers own freshly built arrays, so this never aliases stored state. */
export function sortByInitiative<T extends InitiativeEntry>(entries: T[]): T[] {
  return entries.sort(compareInitiative);
}

/**
 * Read one `{name, dex?, roll}` payload entry, or undefined when it is
 * malformed. `dex` defaults to 0; the initiative score is always `roll + dex`.
 */
export function parseInitiativeEntry(raw: unknown): InitiativeEntry | undefined {
  if (!isObject(raw)) return undefined;
  const name = raw.name;
  const dex = asInteger(raw.dex ?? 0);
  const roll = asInteger(raw.roll);
  if (typeof name !== "string" || dex === undefined || roll === undefined) {
    return undefined;
  }
  return { name, dex, score: roll + dex };
}
