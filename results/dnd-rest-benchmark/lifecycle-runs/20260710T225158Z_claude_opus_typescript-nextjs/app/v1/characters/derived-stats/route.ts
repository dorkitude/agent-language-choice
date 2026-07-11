import { NextResponse } from "next/server";

const ABILITIES = ["str", "dex", "con", "int", "wis", "cha"] as const;
type Ability = (typeof ABILITIES)[number];

function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

function proficiencyBonus(level: number): number {
  return Math.floor((level - 1) / 4) + 2;
}

function isValidScore(v: unknown): v is number {
  return typeof v === "number" && Number.isInteger(v) && v >= 1 && v <= 30;
}

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }

  const obj =
    body && typeof body === "object" ? (body as Record<string, unknown>) : {};

  const level = obj.level;
  if (
    typeof level !== "number" ||
    !Number.isInteger(level) ||
    level < 1 ||
    level > 20
  ) {
    return NextResponse.json({ error: "invalid level" }, { status: 400 });
  }

  const abilitiesRaw = obj.abilities;
  if (!abilitiesRaw || typeof abilitiesRaw !== "object") {
    return NextResponse.json({ error: "invalid abilities" }, { status: 400 });
  }
  const abilitiesObj = abilitiesRaw as Record<string, unknown>;
  const modifiers: Record<Ability, number> = {} as Record<Ability, number>;
  for (const key of ABILITIES) {
    const score = abilitiesObj[key];
    if (!isValidScore(score)) {
      return NextResponse.json({ error: "invalid abilities" }, { status: 400 });
    }
    modifiers[key] = abilityModifier(score);
  }

  const armorRaw = obj.armor;
  if (!armorRaw || typeof armorRaw !== "object") {
    return NextResponse.json({ error: "invalid armor" }, { status: 400 });
  }
  const armor = armorRaw as Record<string, unknown>;
  const base = armor.base;
  const dexCap = armor.dex_cap;
  const shield = armor.shield;
  if (
    typeof base !== "number" ||
    !Number.isInteger(base) ||
    typeof dexCap !== "number" ||
    !Number.isInteger(dexCap) ||
    typeof shield !== "boolean"
  ) {
    return NextResponse.json({ error: "invalid armor" }, { status: 400 });
  }

  const proficiency = proficiencyBonus(level);
  const hpMax = level * (6 + modifiers.con);
  const shieldBonus = shield ? 2 : 0;
  const armorClass = base + Math.min(modifiers.dex, dexCap) + shieldBonus;

  return NextResponse.json({
    level,
    proficiency_bonus: proficiency,
    hp_max: hpMax,
    armor_class: armorClass,
    modifiers,
  });
}
