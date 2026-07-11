import { proficiencyBonus, validateLevel } from "../../../lib/dnd.js";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const level = validateLevel(body.level);
    return Response.json({ level, proficiency_bonus: proficiencyBonus(level) });
  } catch (error) {
    const message = error instanceof Error ? error.message : "invalid request";
    return Response.json({ error: message }, { status: 400 });
  }
}
