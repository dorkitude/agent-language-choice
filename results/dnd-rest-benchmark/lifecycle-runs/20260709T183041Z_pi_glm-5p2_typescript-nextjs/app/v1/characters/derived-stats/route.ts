import { NextResponse } from 'next/server';
import {
  ABILITIES,
  abilityModifier,
  proficiencyBonus,
  isInt,
  isValidLevel,
  isValidScore,
} from '../rules';

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const level = (body as { level?: unknown })?.level;
  if (!isValidLevel(level)) {
    return NextResponse.json({ error: 'invalid level' }, { status: 400 });
  }

  const abilities = (body as { abilities?: unknown })?.abilities;
  if (typeof abilities !== 'object' || abilities === null) {
    return NextResponse.json({ error: 'invalid abilities' }, { status: 400 });
  }

  const modifiers: Record<string, number> = {};
  for (const key of ABILITIES) {
    const score = (abilities as Record<string, unknown>)[key];
    if (!isValidScore(score)) {
      return NextResponse.json({ error: `invalid ${key}` }, { status: 400 });
    }
    modifiers[key] = abilityModifier(score);
  }

  const armor = (body as { armor?: unknown })?.armor;
  if (typeof armor !== 'object' || armor === null) {
    return NextResponse.json({ error: 'invalid armor' }, { status: 400 });
  }
  const base = (armor as { base?: unknown }).base;
  const shield = (armor as { shield?: unknown }).shield;
  const dexCap = (armor as { dex_cap?: unknown }).dex_cap;
  if (!isInt(base)) {
    return NextResponse.json({ error: 'invalid armor base' }, { status: 400 });
  }
  if (shield !== undefined && typeof shield !== 'boolean') {
    return NextResponse.json({ error: 'invalid armor shield' }, { status: 400 });
  }
  if (!isInt(dexCap)) {
    return NextResponse.json({ error: 'invalid armor dex_cap' }, { status: 400 });
  }

  const shieldBonus = shield === true ? 2 : 0;
  const hpMax = level * (6 + modifiers.con);
  const armorClass = base + Math.min(modifiers.dex, dexCap) + shieldBonus;

  return NextResponse.json({
    level,
    proficiency_bonus: proficiencyBonus(level),
    hp_max: hpMax,
    armor_class: armorClass,
    modifiers,
  });
}
