import { badRequest, isFiniteNumber, isRecord, json, readJson } from "../../../api.js";
import { isValidSlug, monsters } from "../../compendium/data.js";
import { campaigns } from "../../campaigns/state.js";
import { difficultyFor, LEVEL_THRESHOLDS, MONSTER_XP, multiplierForMonsterCount, recommendationForDifficulty } from "../rules.js";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await readJson(request);
  if (
    !isRecord(body) ||
    typeof body.campaign_id !== "string" ||
    campaigns.get(body.campaign_id) === undefined ||
    !Array.isArray(body.party) ||
    !Array.isArray(body.monster_slugs)
  ) {
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
  for (const slug of body.monster_slugs) {
    if (!isValidSlug(slug)) {
      return badRequest();
    }

    const monster = monsters.get(slug);
    if (monster === undefined) {
      return badRequest();
    }

    const xp = MONSTER_XP[monster.cr];
    if (xp === undefined) {
      return badRequest();
    }

    baseXp += xp;
  }

  const monsterCount = body.monster_slugs.length;
  const adjustedXp = baseXp * multiplierForMonsterCount(monsterCount);
  const difficulty = difficultyFor(adjustedXp, thresholds);

  return json({
    campaign_id: body.campaign_id,
    base_xp: baseXp,
    adjusted_xp: adjustedXp,
    difficulty,
    monster_count: monsterCount,
    recommendation: recommendationForDifficulty(difficulty),
  });
}
