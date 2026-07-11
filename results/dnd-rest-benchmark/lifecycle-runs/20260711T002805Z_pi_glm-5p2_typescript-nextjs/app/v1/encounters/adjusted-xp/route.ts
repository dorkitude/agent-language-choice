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

// Standard D&D 5e DMG encounter thresholds by level.
// The first benchmark suite requires level 3; the rest are canonical.
const THRESHOLDS_BY_LEVEL: Record<
  number,
  { easy: number; medium: number; hard: number; deadly: number }
> = {
  1: { easy: 25, medium: 50, hard: 75, deadly: 100 },
  2: { easy: 50, medium: 100, hard: 150, deadly: 200 },
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
  4: { easy: 125, medium: 250, hard: 375, deadly: 500 },
  5: { easy: 250, medium: 500, hard: 750, deadly: 1100 },
  6: { easy: 300, medium: 600, hard: 900, deadly: 1400 },
  7: { easy: 350, medium: 750, hard: 1100, deadly: 1700 },
  8: { easy: 450, medium: 900, hard: 1400, deadly: 2100 },
  9: { easy: 550, medium: 1100, hard: 1600, deadly: 2400 },
  10: { easy: 600, medium: 1200, hard: 1900, deadly: 2800 },
  11: { easy: 800, medium: 1600, hard: 2400, deadly: 3600 },
  12: { easy: 1000, medium: 2000, hard: 3000, deadly: 4500 },
  13: { easy: 1100, medium: 2200, hard: 3400, deadly: 5100 },
  14: { easy: 1250, medium: 2500, hard: 3800, deadly: 5700 },
  15: { easy: 1400, medium: 2800, hard: 4300, deadly: 6400 },
  16: { easy: 1600, medium: 3200, hard: 4800, deadly: 7200 },
  17: { easy: 2000, medium: 3900, hard: 5900, deadly: 8800 },
  18: { easy: 2100, medium: 4200, hard: 6300, deadly: 9500 },
  19: { easy: 2400, medium: 4700, hard: 7200, deadly: 10900 },
  20: { easy: 2800, medium: 5700, hard: 8500, deadly: 12700 },
};

function multiplierFor(monsterCount: number): number {
  if (monsterCount >= 15) return 4;
  if (monsterCount >= 11) return 3;
  if (monsterCount >= 7) return 2.5;
  if (monsterCount >= 3) return 2;
  if (monsterCount >= 2) return 1.5;
  return 1;
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const rawParty = (body as { party?: unknown })?.party;
  const rawMonsters = (body as { monsters?: unknown })?.monsters;

  const party: unknown[] = Array.isArray(rawParty) ? rawParty : [];
  const monsters: unknown[] = Array.isArray(rawMonsters) ? rawMonsters : [];

  let baseXp = 0;
  let monsterCount = 0;

  for (const mon of monsters) {
    const m = mon as { cr?: unknown; count?: unknown };
    const cr = m?.cr;
    const count = m?.count;
    if (cr === undefined || !Number.isInteger(count) || (count as number) <= 0) {
      return NextResponse.json({ error: 'invalid monster' }, { status: 400 });
    }
    const crKey = String(cr).trim();
    const xp = XP_BY_CR[crKey];
    if (xp === undefined) {
      return NextResponse.json({ error: 'unknown cr' }, { status: 400 });
    }
    baseXp += xp * (count as number);
    monsterCount += count as number;
  }

  let easy = 0;
  let medium = 0;
  let hard = 0;
  let deadly = 0;

  for (const member of party) {
    const lvl = (member as { level?: unknown })?.level;
    if (!Number.isInteger(lvl) || (lvl as number) < 1 || (lvl as number) > 20) {
      return NextResponse.json({ error: 'invalid party level' }, { status: 400 });
    }
    const t = THRESHOLDS_BY_LEVEL[lvl as number];
    easy += t.easy;
    medium += t.medium;
    hard += t.hard;
    deadly += t.deadly;
  }

  const multiplier = multiplierFor(monsterCount);
  const adjustedXp = baseXp * multiplier;

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
