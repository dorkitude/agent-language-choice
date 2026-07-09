type PartyMember = {
  level?: unknown;
};

type MonsterGroup = {
  cr?: unknown;
  count?: unknown;
};

type EncounterRequest = {
  party?: unknown;
  monsters?: unknown;
};

const XP_BY_CR: Record<string, number> = {
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

function badRequest() {
  return Response.json({ error: "bad_request" }, { status: 400 });
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function multiplierFor(monsterCount: number) {
  if (monsterCount === 1) return 1;
  if (monsterCount === 2) return 1.5;
  if (monsterCount <= 6) return 2;
  if (monsterCount <= 10) return 2.5;
  if (monsterCount <= 14) return 3;
  return 4;
}

function difficultyFor(adjustedXp: number, thresholds: typeof LEVEL_3_THRESHOLDS) {
  if (adjustedXp >= thresholds.deadly) return "deadly";
  if (adjustedXp >= thresholds.hard) return "hard";
  if (adjustedXp >= thresholds.medium) return "medium";
  if (adjustedXp >= thresholds.easy) return "easy";
  return "trivial";
}

export async function POST(request: Request) {
  let body: EncounterRequest;

  try {
    body = await request.json();
  } catch {
    return badRequest();
  }

  if (!Array.isArray(body.party) || !Array.isArray(body.monsters) || body.party.length === 0) {
    return badRequest();
  }

  const party = body.party as PartyMember[];
  const monsters = body.monsters as MonsterGroup[];

  if (!party.every((member) => member !== null && typeof member === "object" && member.level === 3)) {
    return badRequest();
  }

  let baseXp = 0;
  let monsterCount = 0;

  for (const monster of monsters) {
    if (monster === null || typeof monster !== "object" || typeof monster.cr !== "string" || !isPositiveInteger(monster.count)) {
      return badRequest();
    }

    const xp = XP_BY_CR[monster.cr];
    if (xp === undefined) {
      return badRequest();
    }

    baseXp += xp * monster.count;
    monsterCount += monster.count;
  }

  if (monsterCount === 0) {
    return badRequest();
  }

  const multiplier = multiplierFor(monsterCount);
  const adjustedXp = baseXp * multiplier;
  const thresholds = {
    easy: LEVEL_3_THRESHOLDS.easy * party.length,
    medium: LEVEL_3_THRESHOLDS.medium * party.length,
    hard: LEVEL_3_THRESHOLDS.hard * party.length,
    deadly: LEVEL_3_THRESHOLDS.deadly * party.length,
  };

  return Response.json({
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty: difficultyFor(adjustedXp, thresholds),
    thresholds,
  });
}
