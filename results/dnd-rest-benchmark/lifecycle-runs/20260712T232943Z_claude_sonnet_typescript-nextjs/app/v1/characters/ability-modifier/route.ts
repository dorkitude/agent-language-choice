function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

export function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
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

  const { score } = body as Record<string, unknown>;
  if (!isInteger(score) || score < 1 || score > 30) {
    return Response.json({ error: "score must be an integer from 1 through 30" }, { status: 400 });
  }

  return Response.json({ score, modifier: abilityModifier(score) });
}
