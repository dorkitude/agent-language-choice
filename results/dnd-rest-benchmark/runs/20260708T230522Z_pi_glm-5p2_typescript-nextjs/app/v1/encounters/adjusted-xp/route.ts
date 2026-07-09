import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

const CR_XP: Record<string, number> = {
  '0': 10,
  '1/8': 25,
  '1/4': 50,
  '1/2': 100,
  '1': 200,
  '2': 450,
  '3': 700,
  '4': 1100,
  '5': 1800,
};

function multiplierFor(count: number): number {
  if (count <= 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

const LEVEL_THRESH: Record<
  number,
  { easy: number; medium: number; hard: number; deadly: number }
> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const b = body as { party?: unknown; monsters?: unknown };
  if (!Array.isArray(b.party) || !Array.isArray(b.monsters)) {
    return NextResponse.json({ error: 'invalid input' }, { status: 400 });
  }

  let base_xp = 0;
  let monster_count = 0;
  for (const m of b.monsters as { cr: string; count: number }[]) {
    const xp = CR_XP[m.cr];
    if (xp === undefined) {
      return NextResponse.json({ error: 'unsupported cr' }, { status: 400 });
    }
    base_xp += xp * m.count;
    monster_count += m.count;
  }

  const multiplier = multiplierFor(monster_count);
  const adjusted_xp = base_xp * multiplier;

  let easy = 0;
  let medium = 0;
  let hard = 0;
  let deadly = 0;
  for (const p of b.party as { level: number }[]) {
    const t = LEVEL_THRESH[p.level];
    if (t) {
      easy += t.easy;
      medium += t.medium;
      hard += t.hard;
      deadly += t.deadly;
    }
  }
  const thresholds = { easy, medium, hard, deadly };

  let difficulty: string;
  if (adjusted_xp >= deadly) difficulty = 'deadly';
  else if (adjusted_xp >= hard) difficulty = 'hard';
  else if (adjusted_xp >= medium) difficulty = 'medium';
  else if (adjusted_xp >= easy) difficulty = 'easy';
  else difficulty = 'trivial';

  return NextResponse.json({
    base_xp,
    monster_count,
    multiplier,
    adjusted_xp,
    difficulty,
    thresholds,
  });
}
