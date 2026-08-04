import { MONSTER_XP, difficultyFor, multiplierFor, sumPartyThresholds } from "../xp.js";
import { parseJsonBody } from "../../http.js";

interface MonsterInput {
  cr: string;
  count: number;
}

interface PartyMemberInput {
  level: number;
}

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { party, monsters } = (body ?? {}) as {
    party?: PartyMemberInput[];
    monsters?: MonsterInput[];
  };

  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    return Response.json({ error: "party and monsters must be arrays" }, { status: 400 });
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of monsters) {
    const xp = MONSTER_XP[String(monster?.cr)];
    const count = monster?.count;
    if (xp === undefined || typeof count !== "number" || count <= 0) {
      return Response.json({ error: "invalid monster entry" }, { status: 400 });
    }
    baseXp += xp * count;
    monsterCount += count;
  }

  const multiplier = multiplierFor(monsterCount);
  const adjustedXp = baseXp * multiplier;

  const thresholds = sumPartyThresholds(party);
  if (!thresholds) {
    return Response.json({ error: "unsupported party member level" }, { status: 400 });
  }

  const difficulty = difficultyFor(adjustedXp, thresholds);

  return Response.json({
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty,
    thresholds,
  });
}
