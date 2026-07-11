import { abilityModifier, validateScore } from "../../../lib/dnd.js";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const score = validateScore(body.score);
    return Response.json({ score, modifier: abilityModifier(score) });
  } catch (error) {
    const message = error instanceof Error ? error.message : "invalid request";
    return Response.json({ error: message }, { status: 400 });
  }
}
