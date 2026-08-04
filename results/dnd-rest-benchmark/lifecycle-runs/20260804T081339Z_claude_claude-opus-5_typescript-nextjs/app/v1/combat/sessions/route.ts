import { badRequest, json, readObject } from "../../../../lib/http";
import { hasSession, parseCombatants, saveSession, sessionState } from "../../../../lib/combat";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const id = body.id;
  if (typeof id !== "string" || id === "") return badRequest("id must be a non-empty string");
  if (hasSession(id)) return badRequest("session id already exists");

  const order = parseCombatants(body.combatants);
  if (!order) return badRequest("combatants must be a non-empty array of {name, dex, roll}");

  const session = { id, round: 1, turn_index: 0, order };
  saveSession(session);
  return json(sessionState(session));
}
