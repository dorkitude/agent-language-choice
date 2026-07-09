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

const LEVEL_THRESHOLDS: Record<number, { easy: number; medium: number; hard: number; deadly: number }> = {
  1: { easy: 25, medium: 50, hard: 75, deadly: 100 },
  2: { easy: 50, medium: 100, hard: 150, deadly: 200 },
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
  4: { easy: 125, medium: 250, hard: 375, deadly: 500 },
  5: { easy: 250, medium: 500, hard: 750, deadly: 1100 },
  6: { easy: 300, medium: 600, hard: 900, deadly: 1400 },
  7: { easy: 350, medium: 750, hard: 1100, deadly: 1700 },
  8: { easy: 450, medium: 900, hard: 1400, deadly: 2100 },
  9: { easy: 550, medium: 1100, hard: 1600, deadly: 2400 },
  10: { easy: 600, medium: 1200, hard: 1900, deadly: 2800 },
  11: { easy: 800, medium: 1600, hard: 2400, deadly: 3600 },
  12: { easy: 1000, medium: 2000, hard: 3000, deadly: 4500 },
  13: { easy: 1100, medium: 2200, hard: 3400, deadly: 5100 },
  14: { easy: 1250, medium: 2500, hard: 3800, deadly: 5700 },
  15: { easy: 1400, medium: 2800, hard: 4300, deadly: 6400 },
  16: { easy: 1600, medium: 3200, hard: 4800, deadly: 7200 },
  17: { easy: 2000, medium: 3900, hard: 5900, deadly: 8800 },
  18: { easy: 2100, medium: 4200, hard: 6300, deadly: 9500 },
  19: { easy: 2400, medium: 4900, hard: 7300, deadly: 10900 },
  20: { easy: 2800, medium: 5700, hard: 8500, deadly: 12700 },
};

function multiplierFor(count: number): number {
  if (count <= 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

interface PartyMember {
  level: number;
}

interface Monster {
  cr: string;
  count: number;
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }

  const { party, monsters } = (body ?? {}) as {
    party?: PartyMember[];
    monsters?: Monster[];
  };

  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    return NextResponse.json({ error: "party and monsters must be arrays" }, { status: 400 });
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of monsters) {
    const xp = CR_XP[String(monster.cr)];
    if (xp === undefined || typeof monster.count !== "number") {
      return NextResponse.json({ error: `unsupported CR: ${monster.cr}` }, { status: 400 });
    }
    baseXp += xp * monster.count;
    monsterCount += monster.count;
  }

  const multiplier = multiplierFor(monsterCount);
  const adjustedXp = baseXp * multiplier;

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    const t = LEVEL_THRESHOLDS[member.level];
    if (!t) {
      return NextResponse.json({ error: `unsupported level: ${member.level}` }, { status: 400 });
    }
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
