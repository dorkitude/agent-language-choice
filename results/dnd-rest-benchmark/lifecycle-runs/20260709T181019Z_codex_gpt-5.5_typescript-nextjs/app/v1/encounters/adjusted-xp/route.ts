import { NextResponse } from "next/server";

const MONSTER_XP: Record<string, number> = {
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

const LEVEL_3_THRESHOLDS = {
  easy: 75,
  medium: 150,
  hard: 225,
  deadly: 400,
};

type Difficulty = "trivial" | "easy" | "medium" | "hard" | "deadly";

function badRequest() {
  return NextResponse.json({ error: "invalid request" }, { status: 400 });
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function multiplierFor(monsterCount: number) {
  if (monsterCount === 1) return 1;
  if (monsterCount === 2) return 1.5;
  if (monsterCount <= 6) return 2;
  if (monsterCount <= 10) return 2.5;
  if (monsterCount <= 14) return 3;
  return 4;
}

function difficultyFor(adjustedXp: number, thresholds: typeof LEVEL_3_THRESHOLDS): Difficulty {
  if (adjustedXp >= thresholds.deadly) return "deadly";
  if (adjustedXp >= thresholds.hard) return "hard";
  if (adjustedXp >= thresholds.medium) return "medium";
  if (adjustedXp >= thresholds.easy) return "easy";
  return "trivial";
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

  const { party, monsters } = body as Record<string, unknown>;
  if (!Array.isArray(party) || !Array.isArray(monsters) || party.length === 0 || monsters.length === 0) {
    return badRequest();
  }

  for (const member of party) {
    if (
      typeof member !== "object" ||
      member === null ||
      (member as { level?: unknown }).level !== 3
    ) {
      return badRequest();
    }
  }

  let baseXp = 0;
  let monsterCount = 0;

  for (const monster of monsters) {
    if (typeof monster !== "object" || monster === null) {
      return badRequest();
    }

    const { cr, count } = monster as { cr?: unknown; count?: unknown };
    if (typeof cr !== "string" || !(cr in MONSTER_XP) || !isPositiveInteger(count)) {
      return badRequest();
    }

    baseXp += MONSTER_XP[cr] * count;
    monsterCount += count;
  }

  const multiplier = multiplierFor(monsterCount);
  const adjustedXp = baseXp * multiplier;
  const thresholds = {
    easy: LEVEL_3_THRESHOLDS.easy * party.length,
    medium: LEVEL_3_THRESHOLDS.medium * party.length,
    hard: LEVEL_3_THRESHOLDS.hard * party.length,
    deadly: LEVEL_3_THRESHOLDS.deadly * party.length,
  };

  return NextResponse.json({
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty: difficultyFor(adjustedXp, thresholds),
    thresholds,
  });
}
