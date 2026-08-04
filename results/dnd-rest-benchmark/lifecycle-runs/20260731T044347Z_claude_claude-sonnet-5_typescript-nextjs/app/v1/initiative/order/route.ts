import { rankInitiative, InitiativeInput } from "../../shared/initiative.js";
import { parseJsonBody } from "../../http.js";

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { combatants } = (body ?? {}) as { combatants?: InitiativeInput[] };
  if (!Array.isArray(combatants)) {
    return Response.json({ error: "combatants must be an array" }, { status: 400 });
  }

  const scored = rankInitiative(combatants);

  return Response.json({
    order: scored.map((entry) => ({ name: entry.name, score: entry.score })),
  });
}
