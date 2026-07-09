import { NextResponse, type NextRequest } from "next/server";

const XP_BY_CR: Record<string, number> = {
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

const THRESHOLDS_BY_LEVEL: Record<number, { easy: number; medium: number; hard: number; deadly: number }> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

function multiplierForCount(count: number): number {
  if (count === 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

export async function POST(request: NextRequest) {
  let body: {
    party?: Array<{ level?: unknown }>;
    monsters?: Array<{ cr?: unknown; count?: unknown }>;
  };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const party = body?.party;
  const monsters = body?.monsters;
  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    return NextResponse.json({ error: "Invalid fields" }, { status: 400 });
  }

  let base_xp = 0;
  let monster_count = 0;

  for (const m of monsters) {
    const cr = m?.cr;
    const count = Number(m?.count);
    if (typeof cr !== "string" || !Number.isInteger(count) || count <= 0) {
      return NextResponse.json({ error: "Invalid monster" }, { status: 400 });
    }
    const xp = XP_BY_CR[cr];
    if (xp === undefined) {
      return NextResponse.json({ error: "Unsupported CR" }, { status: 400 });
    }
    base_xp += xp * count;
    monster_count += count;
  }

  const multiplier = multiplierForCount(monster_count);
  const adjusted_xp = base_xp * multiplier;

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const p of party) {
    const level = Number(p?.level);
    if (!Number.isInteger(level) || level <= 0) {
      return NextResponse.json({ error: "Invalid party member" }, { status: 400 });
    }
    const t = THRESHOLDS_BY_LEVEL[level];
    if (!t) {
      return NextResponse.json({ error: "Unsupported level" }, { status: 400 });
    }
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

  let difficulty: "trivial" | "easy" | "medium" | "hard" | "deadly" = "trivial";
  if (adjusted_xp >= thresholds.deadly) difficulty = "deadly";
  else if (adjusted_xp >= thresholds.hard) difficulty = "hard";
  else if (adjusted_xp >= thresholds.medium) difficulty = "medium";
  else if (adjusted_xp >= thresholds.easy) difficulty = "easy";

  return NextResponse.json({
    base_xp,
    monster_count,
    multiplier,
    adjusted_xp,
    difficulty,
    thresholds,
  });
}
