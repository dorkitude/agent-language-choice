import { badRequest, json, notFound, readObject } from "../../../../../../lib/http";
import { asInteger } from "../../../../../../lib/validation";
import { getSession, publicConditions, saveSession } from "../../../../../../lib/combat";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await context.params;
  const session = getSession(id);
  if (!session) return notFound("unknown session");

  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const target = body.target;
  if (typeof target !== "string") return badRequest("target must be a string");
  const combatant = session.order.find((entry) => entry.name === target);
  if (!combatant) return badRequest("target is not a combatant in this session");

  const condition = body.condition;
  if (typeof condition !== "string" || condition === "") {
    return badRequest("condition must be a non-empty string");
  }

  const duration = asInteger(body.duration_rounds);
  if (duration === undefined || duration <= 0) {
    return badRequest("duration_rounds must be a positive integer");
  }

  combatant.conditions.push({ condition, remaining_rounds: duration });
  saveSession(session);

  return json({ target: combatant.name, conditions: publicConditions(combatant) });
}
