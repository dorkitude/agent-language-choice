import { badRequest, json, readObject } from "../../../../lib/http";
import {
  type InitiativeEntry,
  parseInitiativeEntry,
  sortByInitiative,
} from "../../../../lib/initiative";

export const dynamic = "force-dynamic";

/**
 * One-shot ordering: nothing is stored, so unlike a combat session this
 * accepts an empty roster and does not require names to be unique.
 */
export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const combatants = body.combatants;
  if (!Array.isArray(combatants)) return badRequest("combatants must be an array");

  const entries: InitiativeEntry[] = [];
  for (const raw of combatants) {
    const entry = parseInitiativeEntry(raw);
    if (!entry) return badRequest("each combatant needs a name, dex and roll");
    entries.push(entry);
  }

  sortByInitiative(entries);
  return json({ order: entries.map(({ name, score }) => ({ name, score })) });
}
