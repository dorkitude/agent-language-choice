import { badRequest, isRecord, json, readJson } from "../../../api.js";
import { isIntegerInRange } from "../../characters/rules.js";

export async function POST(request: Request) {
  const body = await readJson(request);
  if (!isRecord(body) || body.class !== "wizard" || !isIntegerInRange(body.level, 1, 20) || body.level !== 5) {
    return badRequest();
  }

  return json({
    class: "wizard",
    level: 5,
    slots: {
      "1": 4,
      "2": 3,
      "3": 2,
    },
  });
}
