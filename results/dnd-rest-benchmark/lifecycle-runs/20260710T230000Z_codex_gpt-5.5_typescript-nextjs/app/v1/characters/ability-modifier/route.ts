import { badRequest, isRecord, json, readJson } from "../../../api.js";
import { abilityModifier, isIntegerInRange } from "../rules.js";

export async function POST(request: Request) {
  const body = await readJson(request);
  if (!isRecord(body) || !isIntegerInRange(body.score, 1, 30)) {
    return badRequest();
  }

  return json({
    score: body.score,
    modifier: abilityModifier(body.score),
  });
}
