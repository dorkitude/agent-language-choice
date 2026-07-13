import { NextResponse } from "next/server";

const ABILITIES = ["str", "dex", "con", "int", "wis", "cha"] as const;
type Ability = (typeof ABILITIES)[number];

function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

function proficiencyBonus(level: number): number {
  return Math.floor((level - 1) / 4) + 2;
}

function isIntInRange(v: unknown, lo: number, hi: number): v is number {
  return typeof v === "number" && Number.isInteger(v) && v >= lo && v <= hi;
}

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const obj =
    typeof body === "object" && body !== null
      ? (body as Record<string, unknown>)
      : {};

  const level = obj.level;
  if (!isIntInRange(level, 1, 20)) {
    return NextResponse.json({ error: "invalid request" }, { status: 400 });
  }

  const abilitiesRaw = obj.abilities;
  if (typeof abilitiesRaw !== "object" || abilitiesRaw === null) {
    return NextResponse.json({ error: "invalid request" }, { status: 400 });
  }
  const abilitiesObj = abilitiesRaw as Record<string, unknown>;

  const modifiers = {} as Record<Ability, number>;
  for (const key of ABILITIES) {
    const score = abilitiesObj[key];
    if (!isIntInRange(score, 1, 30)) {
      return NextResponse.json({ error: "invalid request" }, { status: 400 });
    }
    modifiers[key] = abilityModifier(score);
  }

  const armorRaw = obj.armor;
  if (typeof armorRaw !== "object" || armorRaw === null) {
    return NextResponse.json({ error: "invalid request" }, { status: 400 });
  }
  const armorObj = armorRaw as Record<string, unknown>;

  const base = armorObj.base;
  const dexCap = armorObj.dex_cap;
  const shield = armorObj.shield;
  if (
    typeof base !== "number" ||
    !Number.isInteger(base) ||
    typeof dexCap !== "number" ||
    !Number.isInteger(dexCap) ||
    typeof shield !== "boolean"
  ) {
    return NextResponse.json({ error: "invalid request" }, { status: 400 });
  }

  const proficiency_bonus = proficiencyBonus(level);
  const hp_max = level * (6 + modifiers.con);
  const shield_bonus = shield ? 2 : 0;
  const armor_class = base + Math.min(modifiers.dex, dexCap) + shield_bonus;

  return NextResponse.json({
    level,
    proficiency_bonus,
    hp_max,
    armor_class,
    modifiers,
  });
}
