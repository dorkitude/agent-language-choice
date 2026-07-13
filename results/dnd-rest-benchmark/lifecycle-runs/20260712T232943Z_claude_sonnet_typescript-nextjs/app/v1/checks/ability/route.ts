function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid JSON" }, { status: 400 });
  }

  if (typeof body !== "object" || body === null) {
    return Response.json({ error: "invalid request" }, { status: 400 });
  }

  const { roll, modifier, dc } = body as Record<string, unknown>;
  if (!isFiniteNumber(roll) || !isFiniteNumber(modifier) || !isFiniteNumber(dc)) {
    return Response.json({ error: "roll, modifier, and dc are required numbers" }, { status: 400 });
  }

  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;

  return Response.json({ total, success, margin });
}
