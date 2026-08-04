import { getMonster } from "../../compendium/store.js";
import {
  MONSTER_XP,
  difficultyFor,
  multiplierFor,
  sumPartyThresholds,
} from "../../encounters/xp.js";
import { parseJsonBody } from "../../http.js";

interface PartyMemberInput {
  level: number;
}

function recommendationFor(difficulty: string): string {
  switch (difficulty) {
    case "trivial":
      return "trivial encounter";
    case "easy":
      return "safe warm-up";
    case "medium":
      return "balanced challenge";
    case "hard":
      return "difficult fight, expect resource use";
    default:
      return "deadly encounter, proceed with caution";
  }
}

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { campaign_id, party, monster_slugs } = (body ?? {}) as {
    campaign_id?: string;
    party?: PartyMemberInput[];
    monster_slugs?: string[];
  };

  if (typeof campaign_id !== "string" || campaign_id.length === 0) {
    return Response.json({ error: "campaign_id is required" }, { status: 400 });
  }
  if (!Array.isArray(party) || party.length === 0) {
    return Response.json({ error: "party must be a non-empty array" }, { status: 400 });
  }
  if (!Array.isArray(monster_slugs) || monster_slugs.length === 0) {
    return Response.json({ error: "monster_slugs must be a non-empty array" }, { status: 400 });
  }

  let baseXp = 0;
  for (const slug of monster_slugs) {
    if (typeof slug !== "string") {
      return Response.json({ error: "monster_slugs must contain strings" }, { status: 400 });
    }
    const monster = getMonster(slug);
    if (!monster) {
      return Response.json({ error: `unknown monster slug: ${slug}` }, { status: 400 });
    }
    const xp = MONSTER_XP[monster.cr];
    if (xp === undefined) {
      return Response.json({ error: `unsupported monster CR: ${monster.cr}` }, { status: 400 });
    }
    baseXp += xp;
  }

  const monsterCount = monster_slugs.length;
  const multiplier = multiplierFor(monsterCount);
  const adjustedXp = baseXp * multiplier;

  const thresholds = sumPartyThresholds(party);
  if (!thresholds) {
    return Response.json({ error: "unsupported party member level" }, { status: 400 });
  }

  const difficulty = difficultyFor(adjustedXp, thresholds);

  return Response.json({
    campaign_id,
    base_xp: baseXp,
    adjusted_xp: adjustedXp,
    difficulty,
    monster_count: monsterCount,
    recommendation: recommendationFor(difficulty),
  });
}
