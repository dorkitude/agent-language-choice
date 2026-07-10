import { NextResponse } from "next/server";

function badRequest() {
  return NextResponse.json({ error: "invalid request" }, { status: 400 });
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export async function POST(request: Request) {
  let body: unknown;

  try {
    body = await request.json();
  } catch {
    return badRequest();
  }

  if (typeof body !== "object" || body === null) {
    return badRequest();
  }

  const { combatants } = body as Record<string, unknown>;
  if (!Array.isArray(combatants)) {
    return badRequest();
  }

  const parsed: Array<{ name: string; dex: number; score: number }> = [];

  for (const combatant of combatants) {
    if (typeof combatant !== "object" || combatant === null) {
      return badRequest();
    }

    const { name, dex, roll } = combatant as Record<string, unknown>;
    if (typeof name !== "string" || !isNumber(dex) || !isNumber(roll)) {
      return badRequest();
    }

    parsed.push({
      name,
      dex,
      score: roll + dex,
    });
  }

  const order = parsed
    .toSorted((left, right) => {
      if (left.score !== right.score) return right.score - left.score;
      if (left.dex !== right.dex) return right.dex - left.dex;
      return left.name.localeCompare(right.name);
    })
    .map(({ name, score }) => ({ name, score }));

  return NextResponse.json({ order });
}
