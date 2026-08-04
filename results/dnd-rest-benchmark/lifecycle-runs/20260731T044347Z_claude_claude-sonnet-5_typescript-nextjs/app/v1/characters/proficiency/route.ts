import { proficiencyBonus } from "../rules.js";
import { parseJsonBody } from "../../http.js";

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { level } = (body ?? {}) as { level?: unknown };

  if (typeof level !== "number" || !Number.isInteger(level) || level < 1 || level > 20) {
    return Response.json({ error: "level must be an integer from 1 through 20" }, { status: 400 });
  }

  return Response.json({ level, proficiency_bonus: proficiencyBonus(level) });
}
