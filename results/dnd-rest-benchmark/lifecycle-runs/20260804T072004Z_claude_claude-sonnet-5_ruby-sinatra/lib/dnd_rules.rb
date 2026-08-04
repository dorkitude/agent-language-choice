# Core 5e-style rules data and pure calculations shared by the /v1/checks,
# /v1/encounters, /v1/characters, /v1/phb, and /v1/dm route groups.
#
# Data tables (CR_XP, LEVEL_THRESHOLDS, WIZARD_SPELL_SLOTS) are intentionally
# small: they cover only the fixtures exercised by the API today. Callers
# must treat an unsupported key (unlisted CR, level, or class) as a 400/404,
# never as "0".

CR_XP = {
  '0' => 10,
  '1/8' => 25,
  '1/4' => 50,
  '1/2' => 100,
  '1' => 200,
  '2' => 450,
  '3' => 700,
  '4' => 1100,
  '5' => 1800
}.freeze

LEVEL_THRESHOLDS = {
  3 => { 'easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400 }
}.freeze

WIZARD_SPELL_SLOTS = {
  5 => { '1' => 4, '2' => 3, '3' => 2 }
}.freeze

DM_DIFFICULTY_RECOMMENDATIONS = {
  'trivial' => 'stand down',
  'easy' => 'safe warm-up',
  'medium' => 'balanced challenge',
  'hard' => 'bring backup',
  'deadly' => 'consider retreat'
}.freeze

DM_LOOT_TIERS = {
  1 => { coins_gp: 75, items: [{ slug: 'healing-potion', quantity: 2 }] }
}.freeze

# DMG-style multiplier applied to total monster XP based on how many
# monsters are in the encounter (more monsters are harder than their raw
# XP total suggests).
def count_multiplier(count)
  case count
  when 1 then 1
  when 2 then 1.5
  when 3..6 then 2
  when 7..10 then 2.5
  when 11..14 then 3
  else 4
  end
end

def ability_modifier(score)
  ((score - 10) / 2.0).floor
end

VALID_RACES = %w[human elf dwarf halfling dragonborn gnome half-elf half-orc tiefling].freeze

VALID_BACKGROUNDS = %w[
  acolyte charlatan criminal entertainer folk-hero guild-artisan
  hermit noble outlander sage sailor soldier
].freeze

# Level-1 max hit die per class, used to derive hp_max = hit_die + con_modifier.
CLASS_HIT_DICE = {
  'barbarian' => 12,
  'fighter' => 10,
  'paladin' => 10,
  'ranger' => 10,
  'bard' => 8,
  'cleric' => 8,
  'druid' => 8,
  'monk' => 8,
  'rogue' => 8,
  'warlock' => 8,
  'sorcerer' => 6,
  'wizard' => 6
}.freeze

ABILITY_KEYS = %w[str dex con int wis cha].freeze

# Canonical 5e skill -> governing-ability pairing. A skill check must name
# the ability that actually governs it (e.g. stealth is always dex), so this
# doubles as the whitelist of supported skills.
SKILL_ABILITIES = {
  'acrobatics' => 'dex',
  'animal-handling' => 'wis',
  'arcana' => 'int',
  'athletics' => 'str',
  'deception' => 'cha',
  'history' => 'int',
  'insight' => 'wis',
  'intimidation' => 'cha',
  'investigation' => 'int',
  'medicine' => 'wis',
  'nature' => 'int',
  'perception' => 'wis',
  'performance' => 'cha',
  'persuasion' => 'cha',
  'religion' => 'int',
  'sleight-of-hand' => 'dex',
  'stealth' => 'dex',
  'survival' => 'wis'
}.freeze

# Known-spell compendium: which classes can learn a given spell. A class
# absent from every entry's classes list (e.g. rogue) simply can never
# learn a spell, per the PHB (only certain classes are spellcasters).
SPELL_COMPENDIUM = {
  'fire-bolt' => { name: 'Fire Bolt', level: 0, classes: %w[sorcerer wizard] },
  'mage-hand' => { name: 'Mage Hand', level: 0, classes: %w[bard sorcerer warlock wizard] },
  'magic-missile' => { name: 'Magic Missile', level: 1, classes: %w[sorcerer wizard] },
  'shield' => { name: 'Shield', level: 1, classes: %w[sorcerer wizard] },
  'guidance' => { name: 'Guidance', level: 0, classes: %w[cleric druid] },
  'sacred-flame' => { name: 'Sacred Flame', level: 0, classes: %w[cleric] },
  'bless' => { name: 'Bless', level: 1, classes: %w[cleric paladin] },
  'cure-wounds' => { name: 'Cure Wounds', level: 1, classes: %w[bard cleric druid paladin ranger] },
  'druidcraft' => { name: 'Druidcraft', level: 0, classes: %w[druid] },
  'vicious-mockery' => { name: 'Vicious Mockery', level: 0, classes: %w[bard] },
  'eldritch-blast' => { name: 'Eldritch Blast', level: 0, classes: %w[warlock] },
  'hunters-mark' => { name: "Hunter's Mark", level: 1, classes: %w[ranger] }
}.freeze

# Classes that can prepare/cast spells at all. A rogue (or any class absent
# here) always fails spell-preparation checks regardless of what it "knows".
SPELLCASTING_CLASSES = %w[bard cleric druid paladin ranger sorcerer warlock wizard].freeze

# Level-1 spell slots available to a spellcasting character, by character
# level. At level 1 a caster has exactly one first-level slot (per the PHB's
# "take the average instead of rolling" simplification this API already
# applies to hit points). Cantrips (spell level 0) are always castable and
# never consume a slot.
PLAY_SPELL_SLOTS = {
  1 => { 1 => 1 },
  2 => { 1 => 3 },
  3 => { 1 => 4, 2 => 2 },
  4 => { 1 => 4, 2 => 3 },
  5 => { 1 => 4, 2 => 3, 3 => 2 }
}.freeze

def proficiency_bonus(level)
  case level
  when 1..4 then 2
  when 5..8 then 3
  when 9..12 then 4
  when 13..16 then 5
  when 17..20 then 6
  end
end

# Sums per-party-member difficulty thresholds for an encounter. Halts the
# request (via the caller's Sinatra context) if any member's level is
# unsupported, so this must be called from within a route handler.
def party_xp_thresholds(party)
  thresholds = { 'easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0 }
  party.each do |p|
    level = p['level']
    halt 400, { error: 'invalid level' }.to_json unless numericish(level)
    level_thresholds = LEVEL_THRESHOLDS[level]
    halt 400, { error: "unsupported level #{level}" }.to_json unless level_thresholds

    thresholds.each_key { |k| thresholds[k] += level_thresholds[k] }
  end
  thresholds
end

def difficulty_for_xp(adjusted_xp, thresholds)
  difficulty = 'trivial'
  difficulty = 'easy' if adjusted_xp >= thresholds['easy']
  difficulty = 'medium' if adjusted_xp >= thresholds['medium']
  difficulty = 'hard' if adjusted_xp >= thresholds['hard']
  difficulty = 'deadly' if adjusted_xp >= thresholds['deadly']
  difficulty
end
