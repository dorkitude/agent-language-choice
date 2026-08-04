import { NextResponse } from "next/server";
import {
  adjustedXp,
  recommendationForDifficulty,
} from "../../../lib/engine.js";
import { badRequest, notFound, parseJsonBody } from "../../../lib/http.js";
import { getCampaign, getMonster } from "../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    typeof b.campaign_id !== "string" ||
    !Array.isArray(b.party) ||
    !Array.isArray(b.monster_slugs)
  ) {
    return badRequest();
  }

  if (!getCampaign(b.campaign_id)) {
    return notFound();
  }

  const party: Array<{ level: number }> = [];
  for (const member of b.party) {
    if (
      typeof member !== "object" ||
      member === null ||
      !Number.isInteger((member as Record<string, unknown>).level)
    ) {
      return badRequest();
    }
    party.push({ level: Number((member as Record<string, unknown>).level) });
  }

  const counts = new Map<string, number>();
  for (const slug of b.monster_slugs) {
    if (typeof slug !== "string" || slug.length === 0) {
      return badRequest();
    }
    counts.set(slug, (counts.get(slug) ?? 0) + 1);
  }

  const monsters: Array<{ cr: string; count: number }> = [];
  for (const [slug, count] of counts) {
    const monster = getMonster(slug);
    if (!monster) {
      return badRequest();
    }
    monsters.push({ cr: monster.cr, count });
  }

  const result = adjustedXp(party, monsters);
  if (!result) {
    return badRequest();
  }

  return NextResponse.json({
    campaign_id: b.campaign_id,
    base_xp: result.base_xp,
    adjusted_xp: result.adjusted_xp,
    difficulty: result.difficulty,
    monster_count: result.monster_count,
    recommendation: recommendationForDifficulty(result.difficulty),
  });
}
