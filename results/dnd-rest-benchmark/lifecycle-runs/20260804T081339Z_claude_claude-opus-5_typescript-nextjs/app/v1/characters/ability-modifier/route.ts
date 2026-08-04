import { abilityModifier } from "../../../../lib/characters";
import { badRequest, json, readObject } from "../../../../lib/http";
import { asIntegerInRange } from "../../../../lib/validation";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const score = asIntegerInRange(body.score, 1, 30);
  if (score === undefined) {
    return badRequest("score must be an integer from 1 through 30");
  }

  return json({ score, modifier: abilityModifier(score) });
}
