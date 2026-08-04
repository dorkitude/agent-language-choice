import { badRequest, json, readObject } from "../../../../lib/http";
import { spellSlots } from "../../../../lib/phb";
import { asIntegerInRange } from "../../../../lib/validation";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const rawClass = body.class;
  if (typeof rawClass !== "string" || rawClass.trim() === "") {
    return badRequest("class must be a non-empty string");
  }
  const className = rawClass.trim().toLowerCase();

  const level = asIntegerInRange(body.level, 1, 20);
  if (level === undefined) {
    return badRequest("level must be an integer from 1 through 20");
  }

  const slots = spellSlots(className, level);
  if (!slots) return badRequest(`unsupported class: ${rawClass}`);

  return json({ class: className, level, slots });
}
