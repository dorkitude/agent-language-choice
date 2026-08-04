export function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

export const ABILITY_KEYS = ["str", "dex", "con", "int", "wis", "cha"] as const;
export type AbilityKey = (typeof ABILITY_KEYS)[number];

// Standard 5e skill -> governing ability mapping.
export const SKILL_ABILITY: Record<string, AbilityKey> = {
  acrobatics: "dex",
  "animal handling": "wis",
  arcana: "int",
  athletics: "str",
  deception: "cha",
  history: "int",
  insight: "wis",
  intimidation: "cha",
  investigation: "int",
  medicine: "wis",
  nature: "int",
  perception: "wis",
  performance: "cha",
  persuasion: "cha",
  religion: "int",
  "sleight of hand": "dex",
  stealth: "dex",
  survival: "wis",
};

export function proficiencyBonus(level: number): number {
  return 2 + Math.floor((level - 1) / 4);
}

// Hit die faces per class, used both for level-1 max HP and for the
// deterministic per-level HP gain applied on level-up.
export const CLASS_HIT_DIE: Record<string, number> = {
  barbarian: 12,
  fighter: 10,
  paladin: 10,
  ranger: 10,
  bard: 8,
  cleric: 8,
  druid: 8,
  monk: 8,
  rogue: 8,
  warlock: 8,
  sorcerer: 6,
  wizard: 6,
};

// Deterministic (fixed, non-random) hit-die roll used for HP gained per
// level beyond 1st, matching the standard "average, rounded up" value for
// a die of the given size (e.g. 1d8 -> 5).
export function fixedHitDieRoll(dieFaces: number): number {
  return Math.ceil(dieFaces / 2) + 1;
}
