import { NextResponse } from "next/server";
import { getCampaign } from "../../../lib/campaigns";
import { getMonster } from "../../../lib/compendium";
import { encounterDifficulty, encounterMultiplier, LEVEL_THREE, XP_BY_CR } from "../../../lib/encounter-math";
import { badRequest, isRecord, jsonBody } from "../../../lib/http";

export const runtime = "nodejs";

function recommendationFor(difficulty: string) {
  if (difficulty === "trivial" || difficulty === "easy") return "safe warm-up";
  if (difficulty === "medium") return "balanced challenge";
  if (difficulty === "hard") return "risky battle";
  return "deadly threat";
}

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (!isRecord(body) || typeof body.campaign_id !== "string" || body.campaign_id.length === 0 ||
      !Array.isArray(body.party) || !Array.isArray(body.monster_slugs) || body.monster_slugs.length === 0 ||
      !body.monster_slugs.every((slug) => typeof slug === "string" && slug.length > 0)) {
    return badRequest();
  }
  if (!getCampaign(body.campaign_id)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });

  for (const member of body.party) {
    if (!isRecord(member) || member.level !== 3) return badRequest("Unsupported party level");
  }

  let baseXp = 0;
  for (const slug of body.monster_slugs) {
    const monster = getMonster(slug);
    if (!monster || !Object.hasOwn(XP_BY_CR, monster.cr)) return badRequest("Unknown or unsupported monster");
    baseXp += XP_BY_CR[monster.cr];
  }

  const monsterCount = body.monster_slugs.length;
  const adjustedXp = baseXp * encounterMultiplier(monsterCount);
  const thresholds = {
    easy: body.party.length * LEVEL_THREE.easy,
    medium: body.party.length * LEVEL_THREE.medium,
    hard: body.party.length * LEVEL_THREE.hard,
    deadly: body.party.length * LEVEL_THREE.deadly,
  };
  const difficulty = encounterDifficulty(adjustedXp, thresholds);

  return NextResponse.json({
    campaign_id: body.campaign_id,
    base_xp: baseXp,
    adjusted_xp: adjustedXp,
    difficulty,
    monster_count: monsterCount,
    recommendation: recommendationFor(difficulty),
  });
}
