import { Condition, getSession, saveSession } from "../../../store.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { target, condition, duration_rounds } = (body ?? {}) as {
    target?: unknown;
    condition?: unknown;
    duration_rounds?: unknown;
  };

  const validTarget = requireNonEmptyString(target, "target");
  if (validTarget instanceof Response) return validTarget;

  const validCondition = requireNonEmptyString(condition, "condition");
  if (validCondition instanceof Response) return validCondition;

  if (
    typeof duration_rounds !== "number" ||
    !Number.isInteger(duration_rounds) ||
    duration_rounds <= 0
  ) {
    return Response.json(
      { error: "duration_rounds must be a positive integer" },
      { status: 400 },
    );
  }

  const session = getSession(id);
  if (!session) {
    return Response.json({ error: `session ${id} not found` }, { status: 404 });
  }

  const combatant = session.order.find((entry) => entry.name === validTarget);
  if (!combatant) {
    return Response.json({ error: `combatant ${validTarget} not found` }, { status: 400 });
  }

  combatant.conditions.push({ condition: validCondition, remaining_rounds: duration_rounds });

  saveSession(session);

  return Response.json({
    target: combatant.name,
    conditions: combatant.conditions.map((entry: Condition) => ({
      condition: entry.condition,
      remaining_rounds: entry.remaining_rounds,
    })),
  });
}
