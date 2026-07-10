import { NextResponse } from 'next/server';

const XP_BY_CR: Record<string, number> = {
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

// [easy, medium, hard, deadly] per level
const THRESHOLDS_BY_LEVEL: Record<number, [number, number, number, number]> = {
  3: [75, 150, 225, 400],
};

function countMultiplier(monsterCount: number): number {
  if (monsterCount <= 1) return 1;
  if (monsterCount === 2) return 1.5;
  if (monsterCount <= 6) return 2;
  if (monsterCount <= 10) return 2.5;
  if (monsterCount <= 14) return 3;
  return 4;
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const { party, monsters } = (body as Record<string, unknown>) ?? {};
  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    return NextResponse.json({ error: 'invalid request' }, { status: 400 });
  }

  let baseXp = 0;
  let monsterCount = 0;

  for (const mon of monsters) {
    const cr = (mon as { cr?: unknown })?.cr;
    const count = Number((mon as { count?: unknown })?.count);
    if (
      typeof cr !== 'string' ||
      !(cr in XP_BY_CR) ||
      !Number.isInteger(count) ||
      count <= 0
    ) {
      return NextResponse.json({ error: 'invalid monster' }, { status: 400 });
    }
    baseXp += XP_BY_CR[cr] * count;
    monsterCount += count;
  }

  const multiplier = countMultiplier(monsterCount);
  const adjustedXp = baseXp * multiplier;

  let easy = 0;
  let medium = 0;
  let hard = 0;
  let deadly = 0;

  for (const member of party) {
    const level = Number((member as { level?: unknown })?.level);
    if (!Number.isInteger(level) || !(level in THRESHOLDS_BY_LEVEL)) {
      return NextResponse.json({ error: 'invalid party' }, { status: 400 });
    }
    const [e, me, ha, d] = THRESHOLDS_BY_LEVEL[level];
    easy += e;
    medium += me;
    hard += ha;
    deadly += d;
  }

  let difficulty: string;
  if (adjustedXp >= deadly) difficulty = 'deadly';
  else if (adjustedXp >= hard) difficulty = 'hard';
  else if (adjustedXp >= medium) difficulty = 'medium';
  else if (adjustedXp >= easy) difficulty = 'easy';
  else difficulty = 'trivial';

  return NextResponse.json({
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty,
    thresholds: { easy, medium, hard, deadly },
  });
}
