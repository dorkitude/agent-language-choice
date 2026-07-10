import { sessions, Condition } from "../../../_store.js";

function badRequest(message: string) {
  return Response.json({ error: message }, { status: 400 });
}

function notFound(message: string) {
  return Response.json({ error: message }, { status: 404 });
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const session = sessions.get(id);
  if (!session) {
    return notFound("unknown session id");
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return badRequest("invalid JSON body");
  }

  if (typeof body !== "object" || body === null) {
    return badRequest("body must be an object");
  }

  const { target, condition, duration_rounds } = body as {
    target?: unknown;
    condition?: unknown;
    duration_rounds?: unknown;
  };

  if (typeof target !== "string" || target.length === 0) {
    return badRequest("target must be a non-empty string");
  }

  if (typeof condition !== "string" || condition.length === 0) {
    return badRequest("condition must be a non-empty string");
  }

  if (
    typeof duration_rounds !== "number" ||
    !Number.isInteger(duration_rounds) ||
    duration_rounds <= 0
  ) {
    return badRequest("duration_rounds must be a positive integer");
  }

  const combatant = session.order.find((c) => c.name === target);
  if (!combatant) {
    return badRequest("target must name a combatant in the session");
  }

  combatant.conditions.push({ condition, remaining_rounds: duration_rounds });

  return Response.json({
    target: combatant.name,
    conditions: combatant.conditions.map((c: Condition) => ({
      condition: c.condition,
      remaining_rounds: c.remaining_rounds,
    })),
  });
}
