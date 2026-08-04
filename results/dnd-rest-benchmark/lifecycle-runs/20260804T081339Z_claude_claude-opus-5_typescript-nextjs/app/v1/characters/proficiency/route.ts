import { proficiencyBonus } from "../../../../lib/characters";
import { badRequest, json, readObject } from "../../../../lib/http";
import { asIntegerInRange } from "../../../../lib/validation";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const level = asIntegerInRange(body.level, 1, 20);
  if (level === undefined) {
    return badRequest("level must be an integer from 1 through 20");
  }

  return json({ level, proficiency_bonus: proficiencyBonus(level) });
}
