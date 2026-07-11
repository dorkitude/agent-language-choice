import { NextResponse } from 'next/server';

const ABILITIES = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const;
type Ability = (typeof ABILITIES)[number];

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

function proficiencyBonus(level: number): number {
  return 2 + Math.floor((level - 1) / 4);
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const data = body as {
    level?: unknown;
    abilities?: unknown;
    armor?: unknown;
  };

  const level = data?.level;
  if (
    typeof level !== 'number' ||
    !Number.isInteger(level) ||
    level < 1 ||
    level > 20
  ) {
    return NextResponse.json({ error: 'invalid level' }, { status: 400 });
  }

  const rawAbilities = data?.abilities;
  if (typeof rawAbilities !== 'object' || rawAbilities === null) {
    return NextResponse.json({ error: 'invalid abilities' }, { status: 400 });
  }
  const abilityMap = rawAbilities as Record<string, unknown>;

  const modifiers = {} as Record<Ability, number>;
  for (const key of ABILITIES) {
    const value = abilityMap[key];
    if (
      typeof value !== 'number' ||
      !Number.isInteger(value) ||
      value < 1 ||
      value > 30
    ) {
      return NextResponse.json({ error: 'invalid ability' }, { status: 400 });
    }
    modifiers[key] = abilityModifier(value);
  }

  const rawArmor = data?.armor;
  if (typeof rawArmor !== 'object' || rawArmor === null) {
    return NextResponse.json({ error: 'invalid armor' }, { status: 400 });
  }
  const armor = rawArmor as { base?: unknown; shield?: unknown; dex_cap?: unknown };

  if (!isFiniteNumber(armor?.base)) {
    return NextResponse.json({ error: 'invalid armor base' }, { status: 400 });
  }
  if (!isFiniteNumber(armor?.dex_cap)) {
    return NextResponse.json({ error: 'invalid armor dex_cap' }, { status: 400 });
  }

  const shieldBonus = armor?.shield === true ? 2 : 0;
  const armor_class =
    armor.base + Math.min(modifiers.dex, armor.dex_cap) + shieldBonus;

  const hp_max = level * (6 + modifiers.con);
  const proficiency_bonus = proficiencyBonus(level);

  return NextResponse.json({
    level,
    proficiency_bonus,
    hp_max,
    armor_class,
    modifiers,
  });
}
