import { NextResponse } from "next/server";

export function proficiencyBonus(level: number): number {
  return Math.floor((level - 1) / 4) + 2;
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const level = (body as { level?: unknown } | null)?.level;

  if (
    typeof level !== "number" ||
    !Number.isInteger(level) ||
    level < 1 ||
    level > 20
  ) {
    return NextResponse.json({ error: "invalid level" }, { status: 400 });
  }

  return NextResponse.json({ level, proficiency_bonus: proficiencyBonus(level) });
}
