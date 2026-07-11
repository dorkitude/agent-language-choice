import { calculateEncounter } from "../../../lib/encounter.js";
import { getMonster } from "../../../lib/compendium.js";

const RECOMMENDATIONS: Record<string, string> = {
  trivial: "cakewalk",
  easy: "safe warm-up",
  medium: "balanced challenge",
  hard: "tough fight",
  deadly: "deadly",
};

function validateParty(value: unknown): Array<{ level: number }> {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error("party must be a non-empty array");
  }
  const party: Array<{ level: number }> = [];
  for (const member of value) {
    if (typeof member !== "object" || member === null) {
      throw new Error("party member must be an object");
    }
    const level = (member as Record<string, unknown>).level;
    if (typeof level !== "number" || !Number.isInteger(level) || level < 1 || level > 20) {
      throw new Error("party member level must be an integer from 1 to 20");
    }
    party.push({ level });
  }
  return party;
}

function validateMonsterSlugs(value: unknown): string[] {
  if (!Array.isArray(value)) {
    throw new Error("monster_slugs must be an array");
  }
  for (const slug of value) {
    if (typeof slug !== "string" || slug.length === 0) {
      throw new Error("monster_slugs must be non-empty strings");
    }
  }
  return value;
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const campaignId = body.campaign_id;
    if (typeof campaignId !== "string" || campaignId.length === 0) {
      throw new Error("campaign_id must be a non-empty string");
    }

    const party = validateParty(body.party);
    const monsterSlugs = validateMonsterSlugs(body.monster_slugs ?? []);

    const crCounts: Record<string, { cr: string; count: number }> = {};
    for (const slug of monsterSlugs) {
      const monster = getMonster(slug);
      if (!monster) {
        throw new Error(`monster ${slug} not found`);
      }
      if (!crCounts[monster.cr]) {
        crCounts[monster.cr] = { cr: monster.cr, count: 0 };
      }
      crCounts[monster.cr].count += 1;
    }

    const result = calculateEncounter(party, Object.values(crCounts));

    return Response.json({
      campaign_id: campaignId,
      base_xp: result.base_xp,
      adjusted_xp: result.adjusted_xp,
      difficulty: result.difficulty,
      monster_count: result.monster_count,
      recommendation: RECOMMENDATIONS[result.difficulty] ?? "unknown",
    });
  } catch (error) {
    if (error instanceof SyntaxError) {
      return Response.json({ error: "invalid json" }, { status: 400 });
    }
    const message = error instanceof Error ? error.message : "invalid request";
    if (message.startsWith("monster ") && message.endsWith(" not found")) {
      return Response.json({ error: message }, { status: 404 });
    }
    return Response.json({ error: message }, { status: 400 });
  }
}
