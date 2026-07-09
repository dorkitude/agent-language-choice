import { NextResponse } from "next/server";

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

// Level -> [easy, medium, hard, deadly]
const LEVEL_THRESHOLDS: Record<number, [number, number, number, number]> = {
  3: [75, 150, 225, 400],
};

function multiplierFor(count: number): number {
  if (count <= 0) return 1;
  if (count === 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const { party, monsters } = (body ?? {}) as {
    party?: unknown;
    monsters?: unknown;
  };

  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    return NextResponse.json({ error: "invalid input" }, { status: 400 });
  }

  let base_xp = 0;
  let monster_count = 0;
  for (const mon of monsters) {
    const cr = (mon as { cr?: unknown })?.cr;
    const count = (mon as { count?: unknown })?.count;
    if (typeof cr !== "string" || typeof count !== "number") {
      return NextResponse.json({ error: "invalid monster" }, { status: 400 });
    }
    const xp = CR_XP[cr];
    if (xp === undefined) {
      return NextResponse.json({ error: "unsupported cr" }, { status: 400 });
    }
    base_xp += xp * count;
    monster_count += count;
  }

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    const level = (member as { level?: unknown })?.level;
    if (typeof level !== "number") {
      return NextResponse.json({ error: "invalid party member" }, { status: 400 });
    }
    const t = LEVEL_THRESHOLDS[level];
    if (!t) {
      return NextResponse.json({ error: "unsupported level" }, { status: 400 });
    }
    thresholds.easy += t[0];
    thresholds.medium += t[1];
    thresholds.hard += t[2];
    thresholds.deadly += t[3];
  }

  const multiplier = multiplierFor(monster_count);
  const adjusted_xp = base_xp * multiplier;

  let difficulty = "trivial";
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
