import { badRequest, isRecord, json, readJson } from "../../../api.js";
import { isIntegerInRange, proficiencyBonus } from "../rules.js";

export async function POST(request: Request) {
  const body = await readJson(request);
  if (!isRecord(body) || !isIntegerInRange(body.level, 1, 20)) {
    return badRequest();
  }

  return json({
    level: body.level,
    proficiency_bonus: proficiencyBonus(body.level),
  });
}
