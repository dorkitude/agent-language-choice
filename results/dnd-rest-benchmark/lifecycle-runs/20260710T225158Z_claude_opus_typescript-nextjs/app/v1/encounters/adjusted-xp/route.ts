import { NextResponse } from "next/server";

const CR_XP: Record<string, number> = {
  "0": 10,
  "1/8": 25,
  "1/4": 50,
  "1/2": 100,
  "1": 200,
  "2": 450,
  "3": 700,
  "4": 1100,
  "5": 1800,
};

const LEVEL_THRESHOLDS: Record<
  number,
  { easy: number; medium: number; hard: number; deadly: number }
> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

function multiplierFor(count: number): number {
  if (count <= 0) return 0;
  if (count === 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
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
  const party = obj.party;
  const monsters = obj.monsters;

  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    return NextResponse.json({ error: "invalid request" }, { status: 400 });
  }

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    const level =
      member && typeof member === "object"
        ? (member as Record<string, unknown>).level
        : undefined;
    if (typeof level !== "number" || !LEVEL_THRESHOLDS[level]) {
      return NextResponse.json({ error: "invalid party" }, { status: 400 });
    }
    const t = LEVEL_THRESHOLDS[level];
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of monsters) {
    const m =
      monster && typeof monster === "object"
        ? (monster as Record<string, unknown>)
        : {};
    const cr = m.cr;
    const count = m.count;
    if (
      typeof cr !== "string" ||
      !(cr in CR_XP) ||
      typeof count !== "number" ||
      !Number.isInteger(count) ||
      count < 0
    ) {
      return NextResponse.json({ error: "invalid monster" }, { status: 400 });
    }
    baseXp += CR_XP[cr] * count;
    monsterCount += count;
  }

  const multiplier = multiplierFor(monsterCount);
  const adjustedXp = baseXp * multiplier;

  let difficulty = "trivial";
  if (adjustedXp >= thresholds.deadly) difficulty = "deadly";
  else if (adjustedXp >= thresholds.hard) difficulty = "hard";
  else if (adjustedXp >= thresholds.medium) difficulty = "medium";
  else if (adjustedXp >= thresholds.easy) difficulty = "easy";

  return NextResponse.json({
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty,
    thresholds,
  });
}
