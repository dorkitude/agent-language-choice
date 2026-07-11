import { createMonster } from "../../../lib/compendium.js";

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as Record<string, unknown>;
    const monster = createMonster(body);
    return Response.json(monster, { status: 201 });
  } catch (error) {
    if (error instanceof SyntaxError) {
      return Response.json({ error: "invalid json" }, { status: 400 });
    }
    const message = error instanceof Error ? error.message : "invalid request";
    if (message === "monster slug already exists") {
      return Response.json({ error: message }, { status: 409 });
    }
    return Response.json({ error: message }, { status: 400 });
  }
}
