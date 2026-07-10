import { NextResponse } from "next/server";

function badRequest() {
  return NextResponse.json({ error: "invalid request" }, { status: 400 });
}

function isAbilityScore(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 30;
}

function abilityModifier(score: number) {
  return Math.floor((score - 10) / 2);
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

  const { score } = body as Record<string, unknown>;
  if (!isAbilityScore(score)) {
    return badRequest();
  }

  return NextResponse.json({
    score,
    modifier: abilityModifier(score),
  });
}
