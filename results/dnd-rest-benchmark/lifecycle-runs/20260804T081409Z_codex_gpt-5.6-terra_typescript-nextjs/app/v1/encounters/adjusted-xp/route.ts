import { NextResponse } from "next/server";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../lib/http";
import { encounterDifficulty, encounterMultiplier, LEVEL_THREE, XP_BY_CR } from "../../../lib/encounter-math";

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (!isRecord(body) || !Array.isArray(body.party) || !Array.isArray(body.monsters)) {
    return badRequest();
  }

  let easy = 0, medium = 0, hard = 0, deadly = 0;
  for (const member of body.party) {
    if (!isRecord(member) || member.level !== 3) return badRequest("Unsupported party level");
    easy += LEVEL_THREE.easy;
    medium += LEVEL_THREE.medium;
    hard += LEVEL_THREE.hard;
    deadly += LEVEL_THREE.deadly;
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of body.monsters) {
    if (!isRecord(monster) || typeof monster.cr !== "string" ||
        !Object.hasOwn(XP_BY_CR, monster.cr) || !isInteger(monster.count) || monster.count <= 0) {
      return badRequest("Invalid monster");
    }
    baseXp += XP_BY_CR[monster.cr] * monster.count;
    monsterCount += monster.count;
  }
  if (monsterCount === 0) return badRequest("At least one monster is required");

  const multiplier = encounterMultiplier(monsterCount);
  const adjustedXp = baseXp * multiplier;
  const difficulty = encounterDifficulty(adjustedXp, { easy, medium, hard, deadly });

  return NextResponse.json({
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty,
    thresholds: { easy, medium, hard, deadly },
  });
}
