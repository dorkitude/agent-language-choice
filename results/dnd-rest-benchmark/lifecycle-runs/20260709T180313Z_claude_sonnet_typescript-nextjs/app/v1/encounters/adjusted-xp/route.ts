function badRequest(message: string) {
  return Response.json({ error: message }, { status: 400 });
}

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

const LEVEL_THRESHOLDS: Record<number, { easy: number; medium: number; hard: number; deadly: number }> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

function multiplierForCount(count: number): number {
  if (count <= 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
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
    return badRequest("invalid JSON body");
  }

  if (typeof body !== "object" || body === null) {
    return badRequest("body must be an object");
  }

  const { party, monsters } = body as { party?: unknown; monsters?: unknown };

  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    return badRequest("party and monsters must be arrays");
  }

  let thresholdSum = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party as PartyMember[]) {
    const level = member?.level;
    if (typeof level !== "number" || !LEVEL_THRESHOLDS[level]) {
      return badRequest(`unsupported party level: ${String(level)}`);
    }
    const t = LEVEL_THRESHOLDS[level];
    thresholdSum.easy += t.easy;
    thresholdSum.medium += t.medium;
    thresholdSum.hard += t.hard;
    thresholdSum.deadly += t.deadly;
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of monsters as Monster[]) {
    const cr = monster?.cr;
    const count = monster?.count;
    if (typeof cr !== "string" || !(cr in MONSTER_XP) || typeof count !== "number" || count <= 0) {
      return badRequest("invalid monster entry");
    }
    baseXp += MONSTER_XP[cr] * count;
    monsterCount += count;
  }

  const multiplier = multiplierForCount(monsterCount);
  const adjustedXp = baseXp * multiplier;

  let difficulty = "trivial";
  if (adjustedXp >= thresholdSum.deadly) difficulty = "deadly";
  else if (adjustedXp >= thresholdSum.hard) difficulty = "hard";
  else if (adjustedXp >= thresholdSum.medium) difficulty = "medium";
  else if (adjustedXp >= thresholdSum.easy) difficulty = "easy";

  return Response.json({
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty,
    thresholds: thresholdSum,
  });
}
