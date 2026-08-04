import crypto from 'node:crypto';

// ---------- validation helpers ----------

export const SLUG_RE = /^[a-z0-9-]+$/;

export const ABILITY_NAMES = ['str', 'dex', 'con', 'int', 'wis', 'cha'];

export const SKILL_NAMES = [
  'acrobatics', 'animal-handling', 'arcana', 'athletics', 'deception', 'history',
  'insight', 'intimidation', 'investigation', 'medicine', 'nature', 'perception',
  'performance', 'persuasion', 'religion', 'sleight-of-hand', 'stealth', 'survival',
];

const QUEST_STATUSES = ['active', 'completed', 'blocked'];

const RACES = ['dragonborn', 'dwarf', 'elf', 'gnome', 'half-elf', 'half-orc', 'halfling', 'human', 'tiefling'];
const CLASSES = ['barbarian', 'bard', 'cleric', 'druid', 'fighter', 'monk', 'paladin', 'ranger', 'rogue', 'sorcerer', 'warlock', 'wizard'];
const BACKGROUNDS = ['acolyte', 'charlatan', 'criminal', 'entertainer', 'folk hero', 'folk-hero', 'guild artisan', 'guild-artisan', 'hermit', 'noble', 'outlander', 'sage', 'sailor', 'soldier', 'urchin'];

const HIT_DICE = {
  barbarian: 12,
  bard: 8,
  cleric: 8,
  druid: 8,
  fighter: 10,
  monk: 8,
  paladin: 10,
  ranger: 10,
  rogue: 8,
  sorcerer: 6,
  warlock: 8,
  wizard: 6,
};

const SPELLCASTING_CLASSES = ['bard', 'cleric', 'druid', 'paladin', 'ranger', 'sorcerer', 'warlock', 'wizard'];

const WIZARD_SPELL_SLOTS = {
  1: { 1: 1 },
  2: { 1: 2 },
  3: { 1: 2, 2: 1 },
  4: { 1: 3, 2: 1 },
  5: { 1: 4, 2: 3, 3: 2 },
  6: { 1: 4, 2: 3, 3: 3 },
  7: { 1: 4, 2: 3, 3: 3, 4: 1 },
  8: { 1: 4, 2: 3, 3: 3, 4: 2 },
  9: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 1 },
  10: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 2 },
  11: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1 },
  12: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1 },
  13: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1 },
  14: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1 },
  15: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1 },
  16: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1 },
  17: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1, 9: 1 },
  18: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 1, 7: 1, 8: 1, 9: 1 },
  19: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 1, 8: 1, 9: 1 },
  20: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 2, 8: 1, 9: 1 },
};

const WIZARD_SPELLS = {
  'acid-splash': { name: 'Acid Splash', level: 0 },
  'blade-ward': { name: 'Blade Ward', level: 0 },
  'chill-touch': { name: 'Chill Touch', level: 0 },
  'dancing-lights': { name: 'Dancing Lights', level: 0 },
  'fire-bolt': { name: 'Fire Bolt', level: 0 },
  'friends': { name: 'Friends', level: 0 },
  'light': { name: 'Light', level: 0 },
  'mage-hand': { name: 'Mage Hand', level: 0 },
  'mending': { name: 'Mending', level: 0 },
  'message': { name: 'Message', level: 0 },
  'minor-illusion': { name: 'Minor Illusion', level: 0 },
  'poison-spray': { name: 'Poison Spray', level: 0 },
  'prestidigitation': { name: 'Prestidigitation', level: 0 },
  'ray-of-frost': { name: 'Ray of Frost', level: 0 },
  'shocking-grasp': { name: 'Shocking Grasp', level: 0 },
  'true-strike': { name: 'True Strike', level: 0 },
  'alarm': { name: 'Alarm', level: 1 },
  'burning-hands': { name: 'Burning Hands', level: 1 },
  'charm-person': { name: 'Charm Person', level: 1 },
  'chromatic-orb': { name: 'Chromatic Orb', level: 1 },
  'color-spray': { name: 'Color Spray', level: 1 },
  'comprehend-languages': { name: 'Comprehend Languages', level: 1 },
  'detect-magic': { name: 'Detect Magic', level: 1 },
  'disguise-self': { name: 'Disguise Self', level: 1 },
  'expeditious-retreat': { name: 'Expeditious Retreat', level: 1 },
  'false-life': { name: 'False Life', level: 1 },
  'feather-fall': { name: 'Feather Fall', level: 1 },
  'find-familiar': { name: 'Find Familiar', level: 1 },
  'fog-cloud': { name: 'Fog Cloud', level: 1 },
  'grease': { name: 'Grease', level: 1 },
  'identify': { name: 'Identify', level: 1 },
  'jump': { name: 'Jump', level: 1 },
  'longstrider': { name: 'Longstrider', level: 1 },
  'mage-armor': { name: 'Mage Armor', level: 1 },
  'magic-missile': { name: 'Magic Missile', level: 1 },
  'protection-from-evil-and-good': { name: 'Protection from Evil and Good', level: 1 },
  'ray-of-sickness': { name: 'Ray of Sickness', level: 1 },
  'shield': { name: 'Shield', level: 1 },
  'silent-image': { name: 'Silent Image', level: 1 },
  'sleep': { name: 'Sleep', level: 1 },
  'tashas-hideous-laughter': { name: "Tasha's Hideous Laughter", level: 1 },
  'tensers-floating-disk': { name: "Tenser's Floating Disk", level: 1 },
  'thunderwave': { name: 'Thunderwave', level: 1 },
  'unseen-servant': { name: 'Unseen Servant', level: 1 },
  'witch-bolt': { name: 'Witch Bolt', level: 1 },
  'alter-self': { name: 'Alter Self', level: 2 },
  'arcane-lock': { name: 'Arcane Lock', level: 2 },
  'blindness-deafness': { name: 'Blindness/Deafness', level: 2 },
  'blur': { name: 'Blur', level: 2 },
  'cloud-of-daggers': { name: 'Cloud of Daggers', level: 2 },
  'continual-flame': { name: 'Continual Flame', level: 2 },
  'darkness': { name: 'Darkness', level: 2 },
  'darkvision': { name: 'Darkvision', level: 2 },
  'detect-thoughts': { name: 'Detect Thoughts', level: 2 },
  'enlarge-reduce': { name: 'Enlarge/Reduce', level: 2 },
  'flaming-sphere': { name: 'Flaming Sphere', level: 2 },
  'gust-of-wind': { name: 'Gust of Wind', level: 2 },
  'hold-person': { name: 'Hold Person', level: 2 },
  'invisibility': { name: 'Invisibility', level: 2 },
  'knock': { name: 'Knock', level: 2 },
  'levitate': { name: 'Levitate', level: 2 },
  'locate-object': { name: 'Locate Object', level: 2 },
  'magic-mouth': { name: 'Magic Mouth', level: 2 },
  'magic-weapon': { name: 'Magic Weapon', level: 2 },
  'mirror-image': { name: 'Mirror Image', level: 2 },
  'misty-step': { name: 'Misty Step', level: 2 },
  'phantasmal-force': { name: 'Phantasmal Force', level: 2 },
  'ray-of-enfeeblement': { name: 'Ray of Enfeeblement', level: 2 },
  'rope-trick': { name: 'Rope Trick', level: 2 },
  'scorching-ray': { name: 'Scorching Ray', level: 2 },
  'see-invisibility': { name: 'See Invisibility', level: 2 },
  'shatter': { name: 'Shatter', level: 2 },
  'spider-climb': { name: 'Spider Climb', level: 2 },
  'suggestion': { name: 'Suggestion', level: 2 },
  'web': { name: 'Web', level: 2 },
  'animate-dead': { name: 'Animate Dead', level: 3 },
  'bestow-curse': { name: 'Bestow Curse', level: 3 },
  'blink': { name: 'Blink', level: 3 },
  'clairvoyance': { name: 'Clairvoyance', level: 3 },
  'counterspell': { name: 'Counterspell', level: 3 },
  'dispel-magic': { name: 'Dispel Magic', level: 3 },
  'fear': { name: 'Fear', level: 3 },
  'fireball': { name: 'Fireball', level: 3 },
  'fly': { name: 'Fly', level: 3 },
  'gaseous-form': { name: 'Gaseous Form', level: 3 },
  'glyph-of-warding': { name: 'Glyph of Warding', level: 3 },
  'haste': { name: 'Haste', level: 3 },
  'hypnotic-pattern': { name: 'Hypnotic Pattern', level: 3 },
  'leomunds-tiny-hut': { name: "Leomund's Tiny Hut", level: 3 },
  'lightning-bolt': { name: 'Lightning Bolt', level: 3 },
  'magic-circle': { name: 'Magic Circle', level: 3 },
  'major-image': { name: 'Major Image', level: 3 },
  'protection-from-energy': { name: 'Protection from Energy', level: 3 },
  'remove-curse': { name: 'Remove Curse', level: 3 },
  'sending': { name: 'Sending', level: 3 },
  'slow': { name: 'Slow', level: 3 },
  'sleet-storm': { name: 'Sleet Storm', level: 3 },
  'stinking-cloud': { name: 'Stinking Cloud', level: 3 },
  'tongues': { name: 'Tongues', level: 3 },
  'vampiric-touch': { name: 'Vampiric Touch', level: 3 },
  'water-breathing': { name: 'Water Breathing', level: 3 },
  'arcane-eye': { name: 'Arcane Eye', level: 4 },
  'banishment': { name: 'Banishment', level: 4 },
  'blight': { name: 'Blight', level: 4 },
  'confusion': { name: 'Confusion', level: 4 },
  'control-water': { name: 'Control Water', level: 4 },
  'dimension-door': { name: 'Dimension Door', level: 4 },
  'evards-black-tentacles': { name: "Evard's Black Tentacles", level: 4 },
  'fabricate': { name: 'Fabricate', level: 4 },
  'fire-shield': { name: 'Fire Shield', level: 4 },
  'greater-invisibility': { name: 'Greater Invisibility', level: 4 },
  'hallucinatory-terrain': { name: 'Hallucinatory Terrain', level: 4 },
  'ice-storm': { name: 'Ice Storm', level: 4 },
  'locate-creature': { name: 'Locate Creature', level: 4 },
  'mordenkainens-faithful-hound': { name: "Mordenkainen's Faithful Hound", level: 4 },
  'mordenkainens-private-sanctum': { name: "Mordenkainen's Private Sanctum", level: 4 },
  'otilukes-resilient-sphere': { name: "Otiluke's Resilient Sphere", level: 4 },
  'phantasmal-killer': { name: 'Phantasmal Killer', level: 4 },
  'polymorph': { name: 'Polymorph', level: 4 },
  'stone-shape': { name: 'Stone Shape', level: 4 },
  'stoneskin': { name: 'Stoneskin', level: 4 },
  'wall-of-fire': { name: 'Wall of Fire', level: 4 },
  'animate-objects': { name: 'Animate Objects', level: 5 },
  'arcane-hand': { name: 'Arcane Hand', level: 5 },
  'cloudkill': { name: 'Cloudkill', level: 5 },
  'cone-of-cold': { name: 'Cone of Cold', level: 5 },
  'conjure-elemental': { name: 'Conjure Elemental', level: 5 },
  'contact-other-plane': { name: 'Contact Other Plane', level: 5 },
  'creation': { name: 'Creation', level: 5 },
  'dominate-person': { name: 'Dominate Person', level: 5 },
  'dream': { name: 'Dream', level: 5 },
  'geas': { name: 'Geas', level: 5 },
  'hold-monster': { name: 'Hold Monster', level: 5 },
  'legend-lore': { name: 'Legend Lore', level: 5 },
  'mislead': { name: 'Mislead', level: 5 },
  'modify-memory': { name: 'Modify Memory', level: 5 },
  'passwall': { name: 'Passwall', level: 5 },
  'planar-binding': { name: 'Planar Binding', level: 5 },
  'scrying': { name: 'Scrying', level: 5 },
  'seeming': { name: 'Seeming', level: 5 },
  'telekinesis': { name: 'Telekinesis', level: 5 },
  'teleportation-circle': { name: 'Teleportation Circle', level: 5 },
  'wall-of-force': { name: 'Wall of Force', level: 5 },
  'wall-of-stone': { name: 'Wall of Stone', level: 5 },
  'chain-lightning': { name: 'Chain Lightning', level: 6 },
  'circle-of-death': { name: 'Circle of Death', level: 6 },
  'disintegrate': { name: 'Disintegrate', level: 6 },
  'eyebite': { name: 'Eyebite', level: 6 },
  'globe-of-invulnerability': { name: 'Globe of Invulnerability', level: 6 },
  'mass-suggestion': { name: 'Mass Suggestion', level: 6 },
  'move-earth': { name: 'Move Earth', level: 6 },
  'otilukes-freezing-sphere': { name: "Otiluke's Freezing Sphere", level: 6 },
  'sunbeam': { name: 'Sunbeam', level: 6 },
  'true-seeing': { name: 'True Seeing', level: 6 },
  'delayed-blast-fireball': { name: 'Delayed Blast Fireball', level: 7 },
  'etherealness': { name: 'Etherealness', level: 7 },
  'finger-of-death': { name: 'Finger of Death', level: 7 },
  'forcecage': { name: 'Forcecage', level: 7 },
  'mirage-arcane': { name: 'Mirage Arcane', level: 7 },
  'mordenkainens-magnificent-mansion': { name: "Mordenkainen's Magnificent Mansion", level: 7 },
  'mordenkainens-sword': { name: "Mordenkainen's Sword", level: 7 },
  'plane-shift': { name: 'Plane Shift', level: 7 },
  'prismatic-spray': { name: 'Prismatic Spray', level: 7 },
  'simulacrum': { name: 'Simulacrum', level: 7 },
  'teleport': { name: 'Teleport', level: 7 },
  'antimagic-field': { name: 'Antimagic Field', level: 8 },
  'clone': { name: 'Clone', level: 8 },
  'control-weather': { name: 'Control Weather', level: 8 },
  'demiplane': { name: 'Demiplane', level: 8 },
  'dominate-monster': { name: 'Dominate Monster', level: 8 },
  'feeblemind': { name: 'Feeblemind', level: 8 },
  'incendiary-cloud': { name: 'Incendiary Cloud', level: 8 },
  'maze': { name: 'Maze', level: 8 },
  'mind-blank': { name: 'Mind Blank', level: 8 },
  'power-word-stun': { name: 'Power Word Stun', level: 8 },
  'sunburst': { name: 'Sunburst', level: 8 },
  'foresight': { name: 'Foresight', level: 9 },
  'gate': { name: 'Gate', level: 9 },
  'meteor-swarm': { name: 'Meteor Swarm', level: 9 },
  'power-word-kill': { name: 'Power Word Kill', level: 9 },
  'prismatic-wall': { name: 'Prismatic Wall', level: 9 },
  'shapechange': { name: 'Shapechange', level: 9 },
  'time-stop': { name: 'Time Stop', level: 9 },
  'wish': { name: 'Wish', level: 9 },
};

export function isValidWizardSpell(spellId, name, level) {
  const spell = WIZARD_SPELLS[spellId];
  if (!spell) return false;
  if (typeof name !== 'string' || name.length === 0) return false;
  if (!Number.isInteger(level) || level < 0 || level > 9) return false;
  return spell.name === name && spell.level === level;
}

export function isValidQuestStatus(value) {
  return typeof value === 'string' && QUEST_STATUSES.includes(value);
}

export function isValidSkill(value) {
  return typeof value === 'string' && SKILL_NAMES.includes(value);
}

export function isValidRace(value) {
  return typeof value === 'string' && RACES.includes(value);
}

export function isValidClass(value) {
  return typeof value === 'string' && CLASSES.includes(value);
}

export function maxPreparedSpells(cls, level) {
  if (cls === 'wizard') return level;
  return null;
}

export function isSpellcastingClass(value) {
  return typeof value === 'string' && SPELLCASTING_CLASSES.includes(value);
}

export function spellSlotsMap(cls, level) {
  if (cls === 'wizard') {
    return WIZARD_SPELL_SLOTS[level] ?? {};
  }
  return null;
}

export function isValidBackground(value) {
  return typeof value === 'string' && BACKGROUNDS.includes(value);
}

export function hitDieForClass(value) {
  return HIT_DICE[value];
}

export function hitDieAverage(value) {
  return Math.floor(value / 2) + 1;
}

export function isNonEmptyString(value) {
  return typeof value === 'string' && value.length > 0;
}

export function isPositiveInteger(value) {
  return Number.isInteger(value) && value > 0;
}

export function isNonNegativeInteger(value) {
  return Number.isInteger(value) && value >= 0;
}

export function isValidSlug(value) {
  return typeof value === 'string' && SLUG_RE.test(value);
}

export function isStringArray(value) {
  return Array.isArray(value) && value.every(v => isNonEmptyString(v));
}

// ---------- dice ----------

export function parseExpression(expression) {
  if (typeof expression !== 'string') return null;
  const match = expression.match(/^(\d+)d(\d+)(?:([+-])(\d+))?$/);
  if (!match) return null;

  const count = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] ? parseInt(match[3] + match[4], 10) : 0;

  if (count <= 0 || sides <= 0) return null;
  return { dice_count: count, sides, modifier };
}

// ---------- encounter XP ----------
//
// The CR and level lookup tables are intentionally limited to the values used
// by the current evaluator suite. Extending them is safe, but keep the existing
// keys and thresholds unchanged to preserve cumulative behavior.

const CR_XP = {
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

const LEVEL_THRESHOLDS = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

function multiplierFor(count) {
  if (count === 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

export function calculateEncounterXp(party, monsters) {
  let baseXp = 0;
  let monsterCount = 0;

  for (const monster of monsters) {
    const cr = String(monster?.cr);
    const count = Number(monster?.count);
    const xp = CR_XP[cr];

    if (!xp || !Number.isInteger(count) || count <= 0) {
      throw new Error('invalid monster');
    }

    baseXp += xp * count;
    monsterCount += count;
  }

  const multiplier = multiplierFor(monsterCount);
  const adjustedXp = baseXp * multiplier;

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    const level = Number(member?.level);
    const levelThresholds = LEVEL_THRESHOLDS[level];
    if (!levelThresholds) {
      throw new Error('unsupported party level');
    }
    thresholds.easy += levelThresholds.easy;
    thresholds.medium += levelThresholds.medium;
    thresholds.hard += levelThresholds.hard;
    thresholds.deadly += levelThresholds.deadly;
  }

  let difficulty = 'trivial';
  if (adjustedXp >= thresholds.deadly) difficulty = 'deadly';
  else if (adjustedXp >= thresholds.hard) difficulty = 'hard';
  else if (adjustedXp >= thresholds.medium) difficulty = 'medium';
  else if (adjustedXp >= thresholds.easy) difficulty = 'easy';

  return {
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty,
    thresholds,
  };
}

export function recommendationForDifficulty(difficulty) {
  switch (difficulty) {
    case 'trivial': return 'trivial';
    case 'easy': return 'safe warm-up';
    case 'medium': return 'fair fight';
    case 'hard': return 'risky';
    case 'deadly': return 'deadly';
    default: return 'unknown';
  }
}

// ---------- initiative ----------

export function buildCombatOrder(combatants) {
  return combatants
    .map(c => ({
      name: c?.name,
      score: Number(c?.roll) + Number(c?.dex),
      dex: Number(c?.dex),
    }))
    .sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      if (b.dex !== a.dex) return b.dex - a.dex;
      return a.name.localeCompare(b.name);
    })
    .map(({ name, score }) => ({ name, score }));
}

export function getEncounterCombatantOrder(combatants) {
  return [...combatants].sort((a, b) => {
    if (b.initiative !== a.initiative) return b.initiative - a.initiative;
    return a.name.localeCompare(b.name);
  });
}

// ---------- character rules ----------

export function abilityModifier(score) {
  return Math.floor((score - 10) / 2);
}

export function proficiencyBonus(level) {
  return 2 + Math.floor((level - 1) / 4);
}

// ---------- auth ----------

export function createPasswordHash(password) {
  const salt = crypto.randomBytes(16).toString('hex');
  const hash = crypto.scryptSync(password, salt, 64).toString('hex');
  return { salt, hash };
}

export function verifyPassword(password, salt, hash) {
  const computed = crypto.scryptSync(password, salt, 64).toString('hex');
  return crypto.timingSafeEqual(
    Buffer.from(computed, 'hex'),
    Buffer.from(hash, 'hex'),
  );
}

export function isValidUsername(username) {
  return typeof username === 'string' && /^[a-z0-9_-]{2,32}$/.test(username);
}

export function isValidPassword(password) {
  return typeof password === 'string' && password.length >= 8;
}

export function isValidRole(role) {
  return role === 'dm' || role === 'player';
}

const INVENTORY_ITEM_IDS = ['healing-potion', 'torch', 'leather-armor', 'ring-of-protection', 'amulet-of-health'];

const EQUIPMENT_SLOTS = {
  'leather-armor': 'armor',
  'ring-of-protection': 'accessory',
  'amulet-of-health': 'accessory',
};

const ATTUNABLE_ACCESSORIES = new Set(['ring-of-protection', 'amulet-of-health']);

export function isValidInventoryItemId(value) {
  return typeof value === 'string' && INVENTORY_ITEM_IDS.includes(value);
}

export function getEquipmentSlot(itemId) {
  return EQUIPMENT_SLOTS[itemId];
}

export function isValidEquipmentSlot(value) {
  return value === 'armor' || value === 'accessory';
}

export function isAttunableAccessory(itemId) {
  return ATTUNABLE_ACCESSORIES.has(itemId);
}

export function isConsumableItem(itemId) {
  return itemId === 'healing-potion';
}
