import { NextResponse } from "next/server";

export function proficiencyBonus(level: number): number {
  return Math.floor((level - 1) / 4) + 2;
}

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const obj =
    typeof body === "object" && body !== null
      ? (body as Record<string, unknown>)
      : {};
  const level = obj.level;

  if (
    typeof level !== "number" ||
    !Number.isInteger(level) ||
    level < 1 ||
    level > 20
  ) {
    return NextResponse.json({ error: "invalid request" }, { status: 400 });
  }

  return NextResponse.json({ level, proficiency_bonus: proficiencyBonus(level) });
}
