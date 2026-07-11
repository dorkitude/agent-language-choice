import { badRequest, isFiniteNumber, isRecord, json, readJson } from "../../../api.js";

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

function multiplierForMonsterCount(count: number): number {
  if (count <= 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

function difficultyFor(adjustedXp: number, thresholds: { easy: number; medium: number; hard: number; deadly: number }): string {
  if (adjustedXp >= thresholds.deadly) return "deadly";
  if (adjustedXp >= thresholds.hard) return "hard";
  if (adjustedXp >= thresholds.medium) return "medium";
  if (adjustedXp >= thresholds.easy) return "easy";
  return "trivial";
}

export async function POST(request: Request) {
  const body = await readJson(request);
  if (!isRecord(body) || !Array.isArray(body.party) || !Array.isArray(body.monsters)) {
    return badRequest();
  }

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of body.party) {
    if (!isRecord(member) || !isFiniteNumber(member.level) || !Number.isSafeInteger(member.level)) {
      return badRequest();
    }
    const memberThresholds = LEVEL_THRESHOLDS[member.level];
    if (memberThresholds === undefined) {
      return badRequest();
    }
    thresholds.easy += memberThresholds.easy;
    thresholds.medium += memberThresholds.medium;
    thresholds.hard += memberThresholds.hard;
    thresholds.deadly += memberThresholds.deadly;
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of body.monsters) {
    if (!isRecord(monster) || typeof monster.cr !== "string" || !isFiniteNumber(monster.count)) {
      return badRequest();
    }
    const xp = MONSTER_XP[monster.cr];
    if (xp === undefined || !Number.isSafeInteger(monster.count) || monster.count <= 0) {
      return badRequest();
    }
    baseXp += xp * monster.count;
    monsterCount += monster.count;
  }

  const multiplier = multiplierForMonsterCount(monsterCount);
  const adjustedXp = baseXp * multiplier;

  return json({
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty: difficultyFor(adjustedXp, thresholds),
    thresholds,
  });
}
