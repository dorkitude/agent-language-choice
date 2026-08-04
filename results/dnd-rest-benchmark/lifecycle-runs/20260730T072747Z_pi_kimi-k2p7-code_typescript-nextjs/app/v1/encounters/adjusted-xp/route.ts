import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

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

const THRESHOLDS: Record<number, { easy: number; medium: number; hard: number; deadly: number }> = {
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

interface PartyMember {
  level: number;
}

interface MonsterGroup {
  cr: string;
  count: number;
}

interface EncounterRequest {
  party: PartyMember[];
  monsters: MonsterGroup[];
}

export async function POST(request: Request) {
  let body: Partial<EncounterRequest>;
  try {
    body = (await request.json()) as Partial<EncounterRequest>;
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const party = Array.isArray(body?.party) ? body.party : [];
  const monsters = Array.isArray(body?.monsters) ? body.monsters : [];

  const thresholds = party.reduce(
    (acc, member) => {
      const level = Number(member?.level);
      const t = THRESHOLDS[level];
      if (!t) return acc;
      return {
        easy: acc.easy + t.easy,
        medium: acc.medium + t.medium,
        hard: acc.hard + t.hard,
        deadly: acc.deadly + t.deadly,
      };
    },
    { easy: 0, medium: 0, hard: 0, deadly: 0 }
  );

  let baseXp = 0;
  let monsterCount = 0;
  for (const group of monsters) {
    const xp = XP_TABLE[group.cr];
    const count = Number(group.count);
    if (xp === undefined || !Number.isFinite(count) || count <= 0) {
      return NextResponse.json({ error: 'Invalid request' }, { status: 400 });
    }
    baseXp += xp * count;
    monsterCount += count;
  }

  const multiplier = multiplierForCount(monsterCount);
  const adjustedXp = baseXp * multiplier;

  let difficulty: string;
  if (adjustedXp >= thresholds.deadly) difficulty = 'deadly';
  else if (adjustedXp >= thresholds.hard) difficulty = 'hard';
  else if (adjustedXp >= thresholds.medium) difficulty = 'medium';
  else if (adjustedXp >= thresholds.easy) difficulty = 'easy';
  else difficulty = 'trivial';

  return NextResponse.json({
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty,
    thresholds,
  });
}
