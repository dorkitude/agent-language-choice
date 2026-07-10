import { NextResponse } from "next/server";

function badRequest() {
  return NextResponse.json({ error: "invalid request" }, { status: 400 });
}

function isCharacterLevel(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 20;
}

function proficiencyBonus(level: number) {
  return Math.floor((level - 1) / 4) + 2;
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

  const { level } = body as Record<string, unknown>;
  if (!isCharacterLevel(level)) {
    return badRequest();
  }

  return NextResponse.json({
    level,
    proficiency_bonus: proficiencyBonus(level),
  });
}
