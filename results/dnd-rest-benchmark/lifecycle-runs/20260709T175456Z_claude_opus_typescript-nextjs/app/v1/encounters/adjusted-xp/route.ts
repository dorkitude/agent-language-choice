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

function countMultiplier(monsterCount: number): number {
  if (monsterCount <= 1) return 1;
  if (monsterCount === 2) return 1.5;
  if (monsterCount <= 6) return 2;
  if (monsterCount <= 10) return 2.5;
  if (monsterCount <= 14) return 3;
  return 4;
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const { party, monsters } = (body ?? {}) as {
    party?: unknown;
    monsters?: unknown;
  };

  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    return NextResponse.json({ error: "invalid input" }, { status: 400 });
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of monsters) {
    const cr = (monster as { cr?: unknown }).cr;
    const count = (monster as { count?: unknown }).count;
    if (typeof cr !== "string" || !(cr in CR_XP)) {
      return NextResponse.json({ error: "unsupported cr" }, { status: 400 });
    }
    if (typeof count !== "number" || !Number.isFinite(count) || count < 0) {
      return NextResponse.json({ error: "invalid count" }, { status: 400 });
    }
    baseXp += CR_XP[cr] * count;
    monsterCount += count;
  }

  const multiplier = countMultiplier(monsterCount);
  const adjustedXp = baseXp * multiplier;

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    const level = (member as { level?: unknown }).level;
    if (typeof level !== "number" || !(level in LEVEL_THRESHOLDS)) {
      return NextResponse.json({ error: "unsupported level" }, { status: 400 });
    }
    const t = LEVEL_THRESHOLDS[level];
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

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
