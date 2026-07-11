import { badRequest, isRecord, json, readJson } from "../../../api.js";
import { isIntegerInRange } from "../../characters/rules.js";

export async function POST(request: Request) {
  const body = await readJson(request);
  if (
    !isRecord(body) ||
    !isIntegerInRange(body.strength, 1, 30) ||
    !isIntegerInRange(body.weight, 0, Number.MAX_SAFE_INTEGER)
  ) {
    return badRequest();
  }

  const capacity = body.strength * 15;

  return json({
    capacity,
    weight: body.weight,
    encumbered: body.weight > capacity,
  });
}
