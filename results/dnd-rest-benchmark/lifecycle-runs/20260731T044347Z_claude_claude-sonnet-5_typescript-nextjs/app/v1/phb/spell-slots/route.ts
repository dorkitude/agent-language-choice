import { parseJsonBody } from "../../http.js";

// Only the wizard/level-5 combination is supported; this API does not yet
// model the full PHB spell-slot progression table for other classes/levels.
const WIZARD_LEVEL_5_SLOTS: Record<string, number> = { "1": 4, "2": 3, "3": 2 };

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { class: className, level } = (body ?? {}) as {
    class?: unknown;
    level?: unknown;
  };

  if (typeof className !== "string" || typeof level !== "number") {
    return Response.json({ error: "class must be a string and level must be a number" }, { status: 400 });
  }

  if (className !== "wizard" || level !== 5) {
    return Response.json({ error: "unsupported class/level combination" }, { status: 400 });
  }

  return Response.json({ class: className, level, slots: WIZARD_LEVEL_5_SLOTS });
}
