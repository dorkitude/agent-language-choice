import { sessions, Combatant, publicSession } from "../_store.js";

function badRequest(message: string) {
  return Response.json({ error: message }, { status: 400 });
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return badRequest("invalid JSON body");
  }

  if (typeof body !== "object" || body === null) {
    return badRequest("body must be an object");
  }

  const { id, combatants } = body as { id?: unknown; combatants?: unknown };

  if (typeof id !== "string" || id.length === 0) {
    return badRequest("id must be a non-empty string");
  }

  if (sessions.has(id)) {
    return badRequest("session id already exists");
  }

  if (!Array.isArray(combatants) || combatants.length === 0) {
    return badRequest("combatants must be a non-empty array");
  }

  const parsed: Combatant[] = [];
  for (const entry of combatants) {
    if (typeof entry !== "object" || entry === null) {
      return badRequest("each combatant must be an object");
    }
    const { name, dex, roll } = entry as {
      name?: unknown;
      dex?: unknown;
      roll?: unknown;
    };
    if (typeof name !== "string" || name.length === 0) {
      return badRequest("combatant name must be a non-empty string");
    }
    if (typeof dex !== "number" || !Number.isFinite(dex)) {
      return badRequest("combatant dex must be a number");
    }
    if (typeof roll !== "number" || !Number.isFinite(roll)) {
      return badRequest("combatant roll must be a number");
    }
    parsed.push({ name, dex, roll, score: roll + dex, conditions: [] });
  }

  parsed.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name.localeCompare(b.name);
  });

  const session = {
    id,
    round: 1,
    turn_index: 0,
    order: parsed,
  };

  sessions.set(id, session);

  return Response.json(publicSession(session));
}
