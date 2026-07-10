import { NextResponse } from "next/server";

const ABILITIES = ["str", "dex", "con", "int", "wis", "cha"] as const;

function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

function proficiencyBonus(level: number): number {
  return Math.floor((level - 1) / 4) + 2;
}

function isIntInRange(value: unknown, min: number, max: number): value is number {
  return (
    typeof value === "number" &&
    Number.isInteger(value) &&
    value >= min &&
    value <= max
  );
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const { level, abilities, armor } = (body ?? {}) as {
    level?: unknown;
    abilities?: unknown;
    armor?: unknown;
  };

  if (!isIntInRange(level, 1, 20)) {
    return NextResponse.json({ error: "invalid level" }, { status: 400 });
  }

  if (typeof abilities !== "object" || abilities === null) {
    return NextResponse.json({ error: "invalid abilities" }, { status: 400 });
  }

  const abilityRecord = abilities as Record<string, unknown>;
  const modifiers: Record<string, number> = {};
  for (const key of ABILITIES) {
    const score = abilityRecord[key];
    if (!isIntInRange(score, 1, 30)) {
      return NextResponse.json({ error: "invalid abilities" }, { status: 400 });
    }
    modifiers[key] = abilityModifier(score);
  }

  if (typeof armor !== "object" || armor === null) {
    return NextResponse.json({ error: "invalid armor" }, { status: 400 });
  }

  const { base, shield, dex_cap } = armor as {
    base?: unknown;
    shield?: unknown;
    dex_cap?: unknown;
  };

  if (
    typeof base !== "number" ||
    !Number.isInteger(base) ||
    typeof shield !== "boolean" ||
    typeof dex_cap !== "number" ||
    !Number.isInteger(dex_cap)
  ) {
    return NextResponse.json({ error: "invalid armor" }, { status: 400 });
  }

  const proficiency = proficiencyBonus(level);
  const hpMax = level * (6 + modifiers.con);
  const shieldBonus = shield ? 2 : 0;
  const armorClass = base + Math.min(modifiers.dex, dex_cap) + shieldBonus;

  return NextResponse.json({
    level,
    proficiency_bonus: proficiency,
    hp_max: hpMax,
    armor_class: armorClass,
    modifiers,
  });
}
