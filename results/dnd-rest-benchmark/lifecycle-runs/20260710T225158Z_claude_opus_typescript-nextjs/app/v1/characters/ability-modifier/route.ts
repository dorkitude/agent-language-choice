import { NextResponse } from "next/server";

function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }

  const obj =
    body && typeof body === "object" ? (body as Record<string, unknown>) : {};
  const score = obj.score;

  if (
    typeof score !== "number" ||
    !Number.isInteger(score) ||
    score < 1 ||
    score > 30
  ) {
    return NextResponse.json({ error: "invalid score" }, { status: 400 });
  }

  return NextResponse.json({ score, modifier: abilityModifier(score) });
}
