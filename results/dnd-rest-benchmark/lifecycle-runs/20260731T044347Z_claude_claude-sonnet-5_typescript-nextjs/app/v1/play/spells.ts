// Deterministic known-spell compendium used to validate a class/spell
// combination. Each entry lists the canonical name, level, and the classes
// permitted to know it; classes absent from every entry (e.g. rogue) can
// never learn a spell.
export interface SpellDefinition {
  spell_id: string;
  name: string;
  level: number;
  classes: string[];
}

export const SPELL_COMPENDIUM: Record<string, SpellDefinition> = {
  "fire-bolt": {
    spell_id: "fire-bolt",
    name: "Fire Bolt",
    level: 0,
    classes: ["wizard", "sorcerer"],
  },
  "mage-hand": {
    spell_id: "mage-hand",
    name: "Mage Hand",
    level: 0,
    classes: ["wizard", "sorcerer", "warlock", "bard"],
  },
  light: {
    spell_id: "light",
    name: "Light",
    level: 0,
    classes: ["wizard", "sorcerer", "cleric", "bard"],
  },
  "sacred-flame": {
    spell_id: "sacred-flame",
    name: "Sacred Flame",
    level: 0,
    classes: ["cleric"],
  },
  guidance: {
    spell_id: "guidance",
    name: "Guidance",
    level: 0,
    classes: ["cleric", "druid"],
  },
  "vicious-mockery": {
    spell_id: "vicious-mockery",
    name: "Vicious Mockery",
    level: 0,
    classes: ["bard"],
  },
  "eldritch-blast": {
    spell_id: "eldritch-blast",
    name: "Eldritch Blast",
    level: 0,
    classes: ["warlock"],
  },
  "magic-missile": {
    spell_id: "magic-missile",
    name: "Magic Missile",
    level: 1,
    classes: ["wizard", "sorcerer"],
  },
  shield: {
    spell_id: "shield",
    name: "Shield",
    level: 1,
    classes: ["wizard", "sorcerer"],
  },
  "cure-wounds": {
    spell_id: "cure-wounds",
    name: "Cure Wounds",
    level: 1,
    classes: ["cleric", "druid", "bard", "paladin", "ranger"],
  },
  bless: {
    spell_id: "bless",
    name: "Bless",
    level: 1,
    classes: ["cleric", "paladin"],
  },
  "healing-word": {
    spell_id: "healing-word",
    name: "Healing Word",
    level: 1,
    classes: ["cleric", "druid", "bard"],
  },
  "detect-magic": {
    spell_id: "detect-magic",
    name: "Detect Magic",
    level: 1,
    classes: ["wizard", "sorcerer", "cleric", "druid", "bard", "paladin", "ranger", "warlock"],
  },
  fireball: {
    spell_id: "fireball",
    name: "Fireball",
    level: 3,
    classes: ["wizard", "sorcerer"],
  },
};

const SPELLCASTING_CLASSES = new Set(
  Object.values(SPELL_COMPENDIUM).flatMap((definition) => definition.classes),
);

export function isSpellcastingClass(characterClass: string): boolean {
  return SPELLCASTING_CLASSES.has(characterClass);
}

// At level 1 a wizard may prepare at most one spell; the maximum prepared
// spell count scales linearly with character level for every prepared caster.
export function maxPreparedSpells(characterClass: string, level: number): number {
  if (!isSpellcastingClass(characterClass)) return 0;
  return Math.max(1, level);
}

// Returns the spell definition when spell_id/name/level match a known spell
// and the class is permitted to know it, or null otherwise.
export function findClassSpell(
  spellId: string,
  name: string,
  level: number,
  characterClass: string,
): SpellDefinition | null {
  const definition = SPELL_COMPENDIUM[spellId];
  if (!definition) return null;
  if (definition.name !== name || definition.level !== level) return null;
  if (!definition.classes.includes(characterClass)) return null;
  return definition;
}

// A large but finite stand-in for "unlimited": cantrips (spell level 0) are
// cast at will and never consume a slot.
export const CANTRIP_SLOT_COUNT = 999999;

// Returns the total number of slots available to a character of the given
// class/level for a spell of the given level, or 0 if the class cannot cast
// spells of that level at all. Slot counts scale linearly with character
// level, mirroring maxPreparedSpells above: at level 1 a spellcaster has
// exactly one slot of a level-1 spell, gaining one more slot of that level
// per character level thereafter.
export function getTotalSpellSlots(
  characterClass: string,
  characterLevel: number,
  spellLevel: number,
): number {
  if (!isSpellcastingClass(characterClass)) return 0;
  if (spellLevel === 0) return CANTRIP_SLOT_COUNT;
  return Math.max(0, characterLevel - spellLevel + 1);
}
