import { NextResponse } from "next/server";

const ABILITY_KEYS = ["str", "dex", "con", "int", "wis", "cha"] as const;

type AbilityKey = (typeof ABILITY_KEYS)[number];
type AbilityScores = Record<AbilityKey, number>;
type AbilityModifiers = Record<AbilityKey, number>;

function badRequest() {
  return NextResponse.json({ error: "invalid request" }, { status: 400 });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isAbilityScore(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 30;
}

function isCharacterLevel(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 20;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function abilityModifier(score: number) {
  return Math.floor((score - 10) / 2);
}

function proficiencyBonus(level: number) {
  return Math.floor((level - 1) / 4) + 2;
}

function parseAbilities(value: unknown): AbilityScores | null {
  if (!isRecord(value)) {
    return null;
  }

  const abilities = {} as AbilityScores;
  for (const key of ABILITY_KEYS) {
    const score = value[key];
    if (!isAbilityScore(score)) {
      return null;
    }

    abilities[key] = score;
  }

  return abilities;
}

export async function POST(request: Request) {
  let body: unknown;

  try {
    body = await request.json();
  } catch {
    return badRequest();
  }

  if (!isRecord(body)) {
    return badRequest();
  }

  const { level, abilities: rawAbilities, armor } = body;
  if (!isCharacterLevel(level) || !isRecord(armor)) {
    return badRequest();
  }

  const abilities = parseAbilities(rawAbilities);
  if (abilities === null) {
    return badRequest();
  }

  const { base, shield, dex_cap: dexCap } = armor;
  if (!isFiniteNumber(base) || typeof shield !== "boolean" || !isFiniteNumber(dexCap)) {
    return badRequest();
  }

  const modifiers = {} as AbilityModifiers;
  for (const key of ABILITY_KEYS) {
    modifiers[key] = abilityModifier(abilities[key]);
  }

  const proficiency = proficiencyBonus(level);
  const hpMax = level * (6 + modifiers.con);
  const armorClass = base + Math.min(modifiers.dex, dexCap) + (shield ? 2 : 0);

  return NextResponse.json({
    level,
    proficiency_bonus: proficiency,
    hp_max: hpMax,
    armor_class: armorClass,
    modifiers,
  });
}
