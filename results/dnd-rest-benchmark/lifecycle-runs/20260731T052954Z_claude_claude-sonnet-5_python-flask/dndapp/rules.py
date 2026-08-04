"""D&D 5e rules tables and pure calculation helpers.

These functions have no I/O and no Flask dependency, which is what lets both
the encounters route and the DM tools route share the same encounter-
difficulty math without duplicating it.
"""

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

# Keyed by party-member level; only the levels exercised by the API are populated.
LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

WIZARD_SPELL_SLOTS = {
    5: {"1": 4, "2": 3, "3": 2},
}

DM_RECOMMENDATIONS = {
    "trivial": "skip the fight",
    "easy": "safe warm-up",
    "medium": "balanced challenge",
    "hard": "bring your A-game",
    "deadly": "deadly - proceed with caution",
}

DM_TIER_LOOT = {
    1: {"coins_gp": 75, "items": [{"slug": "healing-potion", "quantity": 2}]},
}


def multiplier_for_count(count):
    """DMG encounter-multiplier table for the number of monsters involved."""
    if count == 1:
        return 1
    if count == 2:
        return 1.5
    if 3 <= count <= 6:
        return 2
    if 7 <= count <= 10:
        return 2.5
    if 11 <= count <= 14:
        return 3
    return 4


def sum_party_thresholds(party):
    """Sum per-difficulty XP thresholds across all party members.

    Raises KeyError/TypeError/ValueError on malformed member entries, and
    ValueError-like signal (via the caller's unsupported-level check) is
    instead surfaced as a `None` sentinel so callers can return their own
    "unsupported level" response.
    """
    thresholds_sum = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = int(member["level"])
        if level not in LEVEL_THRESHOLDS:
            return None
        for key in thresholds_sum:
            thresholds_sum[key] += LEVEL_THRESHOLDS[level][key]
    return thresholds_sum


def classify_difficulty(adjusted_xp, thresholds_sum):
    if adjusted_xp >= thresholds_sum["deadly"]:
        return "deadly"
    if adjusted_xp >= thresholds_sum["hard"]:
        return "hard"
    if adjusted_xp >= thresholds_sum["medium"]:
        return "medium"
    if adjusted_xp >= thresholds_sum["easy"]:
        return "easy"
    return "trivial"


def ability_modifier(score):
    return (score - 10) // 2


def proficiency_bonus(level):
    return 2 + (level - 1) // 4


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


# Classes with a spellcasting feature; any spell is a valid pick for them.
# Every other class (fighter, rogue, barbarian, monk, ...) knows no spells.
SPELLCASTING_CLASSES = {
    "wizard",
    "cleric",
    "druid",
    "bard",
    "sorcerer",
    "warlock",
    "paladin",
    "ranger",
}


def spell_known_by_class(char_class, spell_id):
    return char_class in SPELLCASTING_CLASSES


# Primary spellcasting ability per class, used to size prepared-spell lists.
PREPARED_SPELL_ABILITY = {
    "wizard": "int_modifier",
    "cleric": "wis_modifier",
    "druid": "wis_modifier",
    "ranger": "wis_modifier",
    "paladin": "cha_modifier",
    "bard": "cha_modifier",
    "sorcerer": "cha_modifier",
    "warlock": "cha_modifier",
}


def max_prepared_spells(char_class, level, ability_modifier_value):
    """Spellcasting-ability modifier + class level, floored at 1 for casters."""
    if char_class not in SPELLCASTING_CLASSES:
        return 0
    return max(1, (level or 1) + (ability_modifier_value or 0))


# Spell slots available per character level, keyed by spell level.
# Only the levels exercised by the API are populated.
SPELL_SLOTS_BY_CHARACTER_LEVEL = {
    1: {1: 1},
    5: {1: 4, 2: 3, 3: 2},
}


def spell_slots_at_level(char_level, spell_level):
    return SPELL_SLOTS_BY_CHARACTER_LEVEL.get(char_level, {}).get(spell_level, 0)


def hp_max_at_level1(char_class, con_modifier):
    return HIT_DICE[char_class] + con_modifier


def average_hit_die_value(hit_die):
    return hit_die // 2 + 1
