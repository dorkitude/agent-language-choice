"""Pure D&D 5e rules calculations shared by multiple view modules.

Kept free of Django/HTTP concerns and persistence so the same logic backs
both the standalone `/v1/encounters/adjusted-xp` endpoint and the DM
encounter builder without duplicating the encounter-difficulty math.
"""

import math

CR_XP = {
    "0": 10,
    "1/8": 25,
    "1/4": 50,
    "1/2": 100,
    "1": 200,
    "2": 450,
    "3": 700,
    "4": 1100,
    "5": 1800,
}

# Per-character-level XP thresholds for encounter difficulty (DMG table).
# Only level 3 is seeded; unsupported levels are rejected by callers.
LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}


def numeric(value):
    """Collapse whole-number floats to int so JSON output stays stable (e.g. 5.0 -> 5)."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def ability_modifier(score):
    if not isinstance(score, int) or isinstance(score, bool) or not (1 <= score <= 30):
        return None
    return math.floor((score - 10) / 2)


def proficiency_bonus(level):
    if not isinstance(level, int) or isinstance(level, bool) or not (1 <= level <= 20):
        return None
    return 2 + (level - 1) // 4


def encounter_multiplier(monster_count):
    if monster_count <= 1:
        return 1
    if monster_count == 2:
        return 1.5
    if monster_count <= 6:
        return 2
    if monster_count <= 10:
        return 2.5
    if monster_count <= 14:
        return 3
    return 4


def party_xp_thresholds(party):
    """Sum easy/medium/hard/deadly XP thresholds across a party.

    Raises KeyError/TypeError/ValueError on malformed member entries and
    returns None if any member's level has no seeded threshold row;
    callers translate both into a 400 response.
    """
    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = int(member["level"])
        if level not in LEVEL_THRESHOLDS:
            return None
        for key in thresholds:
            thresholds[key] += LEVEL_THRESHOLDS[level][key]
    return thresholds


VALID_RACES = {
    "human",
    "elf",
    "dwarf",
    "halfling",
    "dragonborn",
    "gnome",
    "half-elf",
    "half-orc",
    "tiefling",
}

VALID_BACKGROUNDS = {
    "acolyte",
    "charlatan",
    "criminal",
    "entertainer",
    "folk-hero",
    "guild-artisan",
    "hermit",
    "noble",
    "outlander",
    "sage",
    "sailor",
    "soldier",
}

# Hit die size per class, used to derive level-1 max hit points.
HIT_DICE = {
    "barbarian": 12,
    "fighter": 10,
    "paladin": 10,
    "ranger": 10,
    "bard": 8,
    "cleric": 8,
    "druid": 8,
    "monk": 8,
    "rogue": 8,
    "warlock": 8,
    "sorcerer": 6,
    "wizard": 6,
}


def hp_max_at_level1(char_class, con_modifier):
    return HIT_DICE[char_class] + con_modifier


# Classes with access to the spell list; others (e.g. rogue, barbarian, fighter,
# monk) cannot learn spells at all.
SPELLCASTING_CLASSES = {
    "bard",
    "cleric",
    "druid",
    "paladin",
    "ranger",
    "sorcerer",
    "warlock",
    "wizard",
}


# Spell slots available per character level, keyed by spell level.
# Only the levels exercised by the API are populated.
SPELL_SLOTS_BY_CHARACTER_LEVEL = {
    1: {1: 1},
    5: {1: 4, 2: 3, 3: 2},
}


def spell_slots_at_level(char_level, spell_level):
    return SPELL_SLOTS_BY_CHARACTER_LEVEL.get(char_level, {}).get(spell_level, 0)


def encounter_difficulty(adjusted_xp, thresholds):
    if adjusted_xp >= thresholds["deadly"]:
        return "deadly"
    if adjusted_xp >= thresholds["hard"]:
        return "hard"
    if adjusted_xp >= thresholds["medium"]:
        return "medium"
    if adjusted_xp >= thresholds["easy"]:
        return "easy"
    return "trivial"
