import {
  CR_XP,
  addLevelThresholds,
  crKey,
  difficultyFor,
  emptyThresholds,
  multiplierFor,
} from "../../../../lib/encounters";
import { badRequest, json, readObject } from "../../../../lib/http";
import { asInteger, isObjectLike } from "../../../../lib/validation";

export const dynamic = "force-dynamic";

/**
 * Stateless encounter math: the party and monsters are supplied inline, so
 * nothing is read from or written to storage. The campaign-aware variant is
 * `/v1/dm/encounter-builder`.
 */
export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const party = body.party;
  const monsters = body.monsters;
  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    return badRequest("party and monsters must be arrays");
  }

  // Each member is validated and folded in as it is read, so the first bad
  // field in the array is the one reported.
  const thresholds = emptyThresholds();
  for (const member of party) {
    if (!isObjectLike(member)) return badRequest("party members must be objects");
    const level = asInteger(member.level);
    if (level === undefined) return badRequest("party member level must be an integer");
    if (!addLevelThresholds(thresholds, level)) {
      return badRequest(`unsupported party level: ${level}`);
    }
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of monsters) {
    if (!isObjectLike(monster)) return badRequest("monsters must be objects");
    const key = crKey(monster.cr);
    if (key === undefined) return badRequest("unsupported challenge rating");
    const count = asInteger(monster.count ?? 1);
    if (count === undefined || count < 0) {
      return badRequest("monster count must be a non-negative integer");
    }
    baseXp += CR_XP[key]! * count;
    monsterCount += count;
  }

  const multiplier = multiplierFor(monsterCount);
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
