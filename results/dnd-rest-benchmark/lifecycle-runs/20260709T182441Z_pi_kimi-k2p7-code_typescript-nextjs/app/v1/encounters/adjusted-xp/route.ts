import { NextResponse } from 'next/server';

const XP_TABLE: Record<string, number> = {
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

const LEVEL_THRESHOLDS: Record<number, { easy: number; medium: number; hard: number; deadly: number }> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

function multiplierFor(count: number): number {
  if (count === 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

export async function POST(request: Request) {
  let body: {
    party?: Array<{ level?: number }>;
    monsters?: Array<{ cr?: string; count?: number }>;
  };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const party = Array.isArray(body?.party) ? body.party : [];
  const monsters = Array.isArray(body?.monsters) ? body.monsters : [];

  if (!party.length || !monsters.length) {
    return NextResponse.json({ error: 'party and monsters required' }, { status: 400 });
  }

  let baseXp = 0;
  let monsterCount = 0;

  for (const m of monsters) {
    const cr = m?.cr;
    const count = m?.count;
    if (typeof cr !== 'string' || typeof count !== 'number') {
      return NextResponse.json({ error: 'monster cr and count required' }, { status: 400 });
    }
    if (!(cr in XP_TABLE)) {
      return NextResponse.json({ error: `Unsupported CR: ${cr}` }, { status: 400 });
    }
    if (count <= 0) {
      return NextResponse.json({ error: 'count must be positive' }, { status: 400 });
    }
    baseXp += XP_TABLE[cr] * count;
    monsterCount += count;
  }

  const multiplier = multiplierFor(monsterCount);
  const adjustedXp = Math.round(baseXp * multiplier);

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const p of party) {
    const level = p?.level;
    if (typeof level !== 'number' || !(level in LEVEL_THRESHOLDS)) {
      return NextResponse.json({ error: `Unsupported level: ${level}` }, { status: 400 });
    }
    const t = LEVEL_THRESHOLDS[level];
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

  let difficulty = 'trivial';
  if (adjustedXp >= thresholds.deadly) difficulty = 'deadly';
  else if (adjustedXp >= thresholds.hard) difficulty = 'hard';
  else if (adjustedXp >= thresholds.medium) difficulty = 'medium';
  else if (adjustedXp >= thresholds.easy) difficulty = 'easy';

  return NextResponse.json({
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty,
    thresholds,
  });
}
