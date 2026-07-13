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
  "6": 2300,
  "7": 2900,
  "8": 3900,
  "9": 5000,
  "10": 5900,
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

function multiplierFor(monsterCount: number): number {
  if (monsterCount <= 1) return 1;
  if (monsterCount === 2) return 1.5;
  if (monsterCount <= 6) return 2;
  if (monsterCount <= 10) return 2.5;
  if (monsterCount <= 14) return 3;
  return 4;
}

interface Monster {
  cr: string;
  count: number;
}

interface PartyMember {
  level: number;
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid JSON" }, { status: 400 });
  }

  if (typeof body !== "object" || body === null) {
    return Response.json({ error: "invalid request" }, { status: 400 });
  }

  const { party, monsters } = body as Record<string, unknown>;
  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    return Response.json({ error: "party and monsters are required arrays" }, { status: 400 });
  }

  let easyTotal = 0;
  let mediumTotal = 0;
  let hardTotal = 0;
  let deadlyTotal = 0;

  for (const member of party as PartyMember[]) {
    const level = member?.level;
    if (typeof level !== "number" || !LEVEL_THRESHOLDS[level]) {
      return Response.json({ error: "unsupported party level" }, { status: 400 });
    }
    const thresholds = LEVEL_THRESHOLDS[level];
    easyTotal += thresholds.easy;
    mediumTotal += thresholds.medium;
    hardTotal += thresholds.hard;
    deadlyTotal += thresholds.deadly;
  }

  let baseXp = 0;
  let monsterCount = 0;

  for (const monster of monsters as Monster[]) {
    const cr = monster?.cr;
    const count = monster?.count;
    if (typeof cr !== "string" || !(cr in CR_XP) || typeof count !== "number" || count <= 0) {
      return Response.json({ error: "unsupported monster entry" }, { status: 400 });
    }
    baseXp += CR_XP[cr] * count;
    monsterCount += count;
  }

  const multiplier = multiplierFor(monsterCount);
  const adjustedXp = baseXp * multiplier;

  let difficulty = "trivial";
  if (adjustedXp >= deadlyTotal) difficulty = "deadly";
  else if (adjustedXp >= hardTotal) difficulty = "hard";
  else if (adjustedXp >= mediumTotal) difficulty = "medium";
  else if (adjustedXp >= easyTotal) difficulty = "easy";

  return Response.json({
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty,
    thresholds: {
      easy: easyTotal,
      medium: mediumTotal,
      hard: hardTotal,
      deadly: deadlyTotal,
    },
  });
}
