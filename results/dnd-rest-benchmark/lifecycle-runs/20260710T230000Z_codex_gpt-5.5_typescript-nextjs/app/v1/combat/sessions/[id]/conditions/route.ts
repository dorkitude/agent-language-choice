import { badRequest, isRecord, json, readJson } from "../../../../../api.js";
import { conditionListFor, sessions } from "../../../state.js";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ id: string }>;
};

export async function POST(request: Request, context: RouteContext) {
  const { id } = await context.params;
  const session = sessions.get(id);
  if (session === undefined) {
    return json({ error: "not_found" }, 404);
  }

  const body = await readJson(request);
  if (
    !isRecord(body) ||
    typeof body.target !== "string" ||
    typeof body.condition !== "string" ||
    typeof body.duration_rounds !== "number" ||
    !Number.isSafeInteger(body.duration_rounds) ||
    body.duration_rounds <= 0
  ) {
    return badRequest();
  }

  if (!session.order.some((combatant) => combatant.name === body.target)) {
    return badRequest();
  }

  const conditions = conditionListFor(session, body.target);
  conditions.push({
    condition: body.condition,
    remaining_rounds: body.duration_rounds,
  });
  session.conditions.set(body.target, conditions);
  sessions.set(session.id, session);

  return json({
    target: body.target,
    conditions,
  });
}
