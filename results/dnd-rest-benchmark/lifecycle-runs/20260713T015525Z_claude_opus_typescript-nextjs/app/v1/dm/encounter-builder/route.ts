import { NextResponse } from "next/server";
import { getMonster } from "../../compendium/store";

// Reuse the core adjusted-XP math shared with /v1/encounters/adjusted-xp.
const CR_XP: Record<string, number> = {
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

const LEVEL_THRESHOLDS: Record<
  number,
  { easy: number; medium: number; hard: number; deadly: number }
> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

function multiplierFor(count: number): number {
  if (count <= 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

// Deterministic recommendation keyed by the computed encounter difficulty.
const RECOMMENDATION: Record<string, string> = {
  trivial: "cakewalk",
  easy: "safe warm-up",
  medium: "a fair fight",
  hard: "tough battle",
  deadly: "risk of a wipe",
};

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const obj =
    typeof body === "object" && body !== null
      ? (body as Record<string, unknown>)
      : {};
  const campaignId = obj.campaign_id;
  const party = obj.party;
  const monsterSlugs = obj.monster_slugs;

  if (typeof campaignId !== "string" || campaignId.length === 0) {
    return NextResponse.json({ error: "invalid campaign_id" }, { status: 400 });
  }
  if (!Array.isArray(party) || party.length === 0) {
    return NextResponse.json({ error: "invalid party" }, { status: 400 });
  }
  if (!Array.isArray(monsterSlugs) || monsterSlugs.length === 0) {
    return NextResponse.json(
      { error: "invalid monster_slugs" },
      { status: 400 },
    );
  }

  // Base XP: look up each monster's CR from the compendium and sum its value.
  let baseXp = 0;
  for (const slug of monsterSlugs) {
    if (typeof slug !== "string" || slug.length === 0) {
      return NextResponse.json(
        { error: "invalid monster slug" },
        { status: 400 },
      );
    }
    const monster = getMonster(slug);
    if (!monster) {
      return NextResponse.json({ error: "monster not found" }, { status: 404 });
    }
    if (!(monster.cr in CR_XP)) {
      return NextResponse.json({ error: "unsupported cr" }, { status: 400 });
    }
    baseXp += CR_XP[monster.cr];
  }

  const monsterCount = monsterSlugs.length;
  const multiplier = multiplierFor(monsterCount);
  const adjustedXp = baseXp * multiplier;

  // Party difficulty thresholds, reusing the core adjusted-XP math.
  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    const level =
      member && typeof member === "object"
        ? (member as Record<string, unknown>).level
        : undefined;
    if (typeof level !== "number" || !LEVEL_THRESHOLDS[level]) {
      return NextResponse.json(
        { error: "unsupported party level" },
        { status: 400 },
      );
    }
    const t = LEVEL_THRESHOLDS[level];
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

  let difficulty = "trivial";
  if (adjustedXp >= thresholds.deadly) difficulty = "deadly";
  else if (adjustedXp >= thresholds.hard) difficulty = "hard";
  else if (adjustedXp >= thresholds.medium) difficulty = "medium";
  else if (adjustedXp >= thresholds.easy) difficulty = "easy";

  return NextResponse.json({
    campaign_id: campaignId,
    base_xp: baseXp,
    adjusted_xp: adjustedXp,
    difficulty,
    monster_count: monsterCount,
    recommendation: RECOMMENDATION[difficulty],
  });
}
