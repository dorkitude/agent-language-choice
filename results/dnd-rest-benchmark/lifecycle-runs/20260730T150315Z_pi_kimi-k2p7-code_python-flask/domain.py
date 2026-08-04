"""Pure D&D 5e helper calculations and static tables.

These functions have no side effects and do not depend on the database.
They are used by both the route layer and the persistence layer.
"""

import re

# XP values for challenge ratings used by encounter math.
XP_TABLE = {
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

# Per-character thresholds for a level-3 party.
LEVEL_3_THRESHOLDS = {"easy": 75, "medium": 150, "hard": 225, "deadly": 400}

# Human-readable guidance keyed by encounter difficulty.
DIFFICULTY_RECOMMENDATION = {
    "trivial": "no challenge",
    "easy": "safe warm-up",
    "medium": "fair fight",
    "hard": "risky encounter",
    "deadly": "deadly threat",
}

# Valid choices for character creation builds.
VALID_RACES = {
    "dragonborn",
    "dwarf",
    "elf",
    "gnome",
    "half-elf",
    "half-orc",
    "halfling",
    "human",
    "tiefling",
}
VALID_CLASSES = {
    "barbarian",
    "bard",
    "cleric",
    "druid",
    "fighter",
    "monk",
    "paladin",
    "ranger",
    "rogue",
    "sorcerer",
    "warlock",
    "wizard",
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
    "soldier",
    "urchin",
}

VALID_ABILITIES = {"str", "dex", "con", "int", "wis", "cha"}

VALID_SKILLS = {
    "acrobatics",
    "animal handling",
    "arcana",
    "athletics",
    "deception",
    "history",
    "insight",
    "intimidation",
    "investigation",
    "medicine",
    "nature",
    "perception",
    "performance",
    "persuasion",
    "religion",
    "sleight of hand",
    "stealth",
    "survival",
}

# Full spellcasting classes that use the standard full-caster slot table.
FULL_CASTER_CLASSES = {"bard", "cleric", "druid", "sorcerer", "warlock", "wizard"}

# Standard full-caster spell slots by character level.  Level 1 is pinned to
# one first-level slot to match the staged spell-casting contract; higher
# levels follow the D&D 5e full-caster progression.
FULL_CASTER_SLOTS = {
    1: {"1": 1},
    2: {"1": 3},
    3: {"1": 4, "2": 2},
    4: {"1": 4, "2": 3},
    5: {"1": 4, "2": 3, "3": 2},
    6: {"1": 4, "2": 3, "3": 3},
    7: {"1": 4, "2": 3, "3": 3, "4": 1},
    8: {"1": 4, "2": 3, "3": 3, "4": 2},
    9: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 1},
    10: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2},
    11: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1},
    12: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1},
    13: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1},
    14: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1},
    15: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1, "8": 1},
    16: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1, "8": 1},
    17: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1, "8": 1, "9": 1},
    18: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 1, "7": 1, "8": 1, "9": 1},
    19: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 2, "7": 1, "8": 1, "9": 1},
    20: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 2, "7": 2, "8": 1, "9": 1},
}

# Wizard spells that can be recorded in a character's spellbook.
WIZARD_SPELLS = {
    # Cantrips
    "acid-splash",
    "blade-ward",
    "chill-touch",
    "dancing-lights",
    "fire-bolt",
    "friends",
    "gust",
    "light",
    "mage-hand",
    "mending",
    "message",
    "minor-illusion",
    "poison-spray",
    "prestidigitation",
    "ray-of-frost",
    "shocking-grasp",
    "thunderclap",
    "true-strike",
    # 1st level
    "alarm",
    "burning-hands",
    "charm-person",
    "chromatic-orb",
    "color-spray",
    "comprehend-languages",
    "detect-magic",
    "disguise-self",
    "expeditious-retreat",
    "false-life",
    "feather-fall",
    "find-familiar",
    "fog-cloud",
    "grease",
    "identify",
    "jump",
    "longstrider",
    "mage-armor",
    "magic-missile",
    "protection-from-evil-and-good",
    "ray-of-sickness",
    "shield",
    "silent-image",
    "sleep",
    "tashas-hideous-laughter",
    "tensers-floating-disk",
    "thunderwave",
    "unseen-servant",
    "witch-bolt",
}

# Max hit die value at level 1 for each class.
CLASS_HIT_DIE_MAX = {
    "barbarian": 12,
    "bard": 8,
    "cleric": 8,
    "druid": 8,
    "fighter": 10,
    "monk": 8,
    "paladin": 10,
    "ranger": 10,
    "rogue": 8,
    "sorcerer": 6,
    "warlock": 8,
    "wizard": 6,
}

# Initiative order is deterministic: highest score wins, then highest dex,
# then alphabetical name.
_INITIATIVE_KEY = lambda c: (-c["score"], -c["dex"], c["name"])


def ability_modifier(score):
    """Return the D&D 5e ability modifier for a score in [1, 30]."""
    return (score - 10) // 2


def proficiency_bonus(level):
    """Return the proficiency bonus for a level in [1, 20]."""
    if level <= 4:
        return 2
    if level <= 8:
        return 3
    if level <= 12:
        return 4
    if level <= 16:
        return 5
    return 6


def multiplier_for_count(count):
    """Encounter multiplier for the number of monsters."""
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


def initiative_order(combatants):
    """Return combatants sorted by initiative score, dex, then name.

    Input combatants must have 'name', 'score', and 'dex' keys.
    The returned list preserves the full input fields.
    """
    return sorted(combatants, key=_INITIATIVE_KEY)


def encounter_difficulty(adjusted_xp, thresholds):
    """Classify an adjusted XP total against a party's thresholds."""
    if adjusted_xp >= thresholds["deadly"]:
        return "deadly"
    if adjusted_xp >= thresholds["hard"]:
        return "hard"
    if adjusted_xp >= thresholds["medium"]:
        return "medium"
    if adjusted_xp >= thresholds["easy"]:
        return "easy"
    return "trivial"


def compute_dice_stats(expression):
    """Parse 'XdY+Z' or 'XdY-Z' and return stats, or None if invalid."""
    match = re.fullmatch(r"(\d+)d(\d+)(?:([+-])(\d+))?", expression)
    if not match:
        return None
    count = int(match.group(1))
    sides = int(match.group(2))
    if count <= 0 or sides <= 0:
        return None
    modifier = 0
    if match.group(3):
        sign = 1 if match.group(3) == "+" else -1
        modifier = sign * int(match.group(4))
    min_value = count + modifier
    max_value = count * sides + modifier
    total = min_value + max_value
    if total % 2 == 0:
        average = total // 2
    else:
        average = total / 2
    return {
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": min_value,
        "max": max_value,
        "average": average,
    }


def compute_ability_check(roll, modifier, dc):
    """Return the total, success flag, and margin for a d20 check."""
    total = roll + modifier
    return {"total": total, "success": total >= dc, "margin": total - dc}


def compute_adjusted_xp(party, monsters):
    """Calculate encounter difficulty from party levels and monster counts.

    Returns a dict on success or None on invalid input.
    """
    if not isinstance(party, list) or not isinstance(monsters, list):
        return None

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        try:
            cr = str(monster["cr"])
            count = int(monster["count"])
        except (KeyError, TypeError, ValueError):
            return None
        if cr not in XP_TABLE or count <= 0:
            return None
        base_xp += XP_TABLE[cr] * count
        monster_count += count

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        try:
            level = int(member["level"])
        except (KeyError, TypeError, ValueError):
            return None
        if level != 3:
            return None
        for key in thresholds:
            thresholds[key] += LEVEL_3_THRESHOLDS[key]

    multiplier = multiplier_for_count(monster_count)
    adjusted_xp = int(base_xp * multiplier)
    difficulty = encounter_difficulty(adjusted_xp, thresholds)

    return {
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": multiplier,
        "adjusted_xp": adjusted_xp,
        "difficulty": difficulty,
        "thresholds": thresholds,
    }


def compute_derived_stats(level, abilities, armor):
    """Compute HP, AC, and modifiers for a character.

    Returns a dict on success or None on invalid input.
    """
    if level < 1 or level > 20:
        return None

    ability_names = ["str", "dex", "con", "int", "wis", "cha"]
    modifiers = {}
    for name in ability_names:
        try:
            score = int(abilities[name])
        except (KeyError, TypeError, ValueError):
            return None
        if score < 1 or score > 30:
            return None
        modifiers[name] = ability_modifier(score)

    try:
        base = int(armor["base"])
        dex_cap = int(armor["dex_cap"])
        shield = bool(armor["shield"])
    except (KeyError, TypeError, ValueError):
        return None

    shield_bonus = 2 if shield else 0
    hp_max = level * (6 + modifiers["con"])
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus

    return {
        "level": level,
        "proficiency_bonus": proficiency_bonus(level),
        "hp_max": hp_max,
        "armor_class": armor_class,
        "modifiers": modifiers,
    }


def compute_long_rest(level, hp_current, hp_max, hit_dice_spent, exhaustion_level):
    """Return post-long-rest values."""
    if level < 1 or hp_max < 1 or hit_dice_spent < 0 or exhaustion_level < 0:
        return None
    restored = max(1, level // 2)
    return {
        "hp_current": hp_max,
        "hit_dice_spent": max(0, hit_dice_spent - restored),
        "exhaustion_level": max(0, exhaustion_level - 1),
    }


def compute_equipment_load(strength, weight):
    """Return carrying capacity and encumbrance status."""
    if strength < 1 or weight < 0:
        return None
    capacity = strength * 15
    return {"capacity": capacity, "weight": weight, "encumbered": weight > capacity}


def compute_spell_slots(class_name, level):
    """Return fixed spell slots for supported class/level combinations."""
    try:
        level = int(level)
    except (TypeError, ValueError):
        return None
    if level < 1 or level > 20:
        return None
    if class_name not in FULL_CASTER_CLASSES:
        return None
    slots = FULL_CASTER_SLOTS.get(level)
    if slots is None:
        return None
    return {"class": class_name, "level": level, "slots": slots}


def validate_build_choices(race, class_name, background):
    """Return True when race, class, and background are all supported."""
    return (
        race in VALID_RACES
        and class_name in VALID_CLASSES
        and background in VALID_BACKGROUNDS
    )


def validate_build_abilities(abilities):
    """Return True when all six ability scores are integers in [1, 30]."""
    if not isinstance(abilities, dict):
        return False
    for name in ("str", "dex", "con", "int", "wis", "cha"):
        try:
            score = int(abilities[name])
        except (KeyError, TypeError, ValueError):
            return False
        if score < 1 or score > 30:
            return False
    return True


def compute_build_hp_max(class_name, level, con_score):
    """Return maximum HP for a level-1 character of the given class.

    Uses the standard D&D 5e level-1 hit point formula: max hit die
    plus the Constitution modifier. Returns None for unsupported classes
    or levels outside [1, 20].
    """
    if level < 1 or level > 20:
        return None
    hit_die_max = CLASS_HIT_DIE_MAX.get(class_name)
    if hit_die_max is None:
        return None
    return hit_die_max + ability_modifier(con_score)


def compute_skill_modifier(ability_score, level, proficient):
    """Return a skill check modifier for a character.

    Modifier = ability_modifier(ability_score) + proficiency_bonus(level)
    if proficient is True.
    """
    modifier = ability_modifier(ability_score)
    if proficient:
        modifier += proficiency_bonus(level)
    return modifier
