function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

export function proficiencyBonus(level: number): number {
  return 2 + Math.floor((level - 1) / 4);
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

  const { level } = body as Record<string, unknown>;
  if (!isInteger(level) || level < 1 || level > 20) {
    return Response.json({ error: "level must be an integer from 1 through 20" }, { status: 400 });
  }

  return Response.json({ level, proficiency_bonus: proficiencyBonus(level) });
}
