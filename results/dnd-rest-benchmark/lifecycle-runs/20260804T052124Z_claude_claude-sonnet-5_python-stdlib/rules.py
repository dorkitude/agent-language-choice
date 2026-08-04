"""D&D 5e rule tables and pure calculation helpers.

Everything here is stateless: constants describing rule-book data plus
functions that transform request-shaped input into rule-derived output.
No I/O, no HTTP, no persistence. `server.py` handlers call into this module
and only concern themselves with request parsing / response shaping.
"""
import hashlib
import hmac
import re
import secrets

# Base XP awarded per monster, keyed by challenge rating (string, since "1/4"
# etc. are not valid dict/JSON numeric keys in the source rule tables).
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

# Encounter difficulty XP thresholds per party-member level. Only level 3 is
# populated; other levels intentionally fall through to "unsupported level".
LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

# Matches dice expressions like "2d6", "1d20+3", "4d8-1".
DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")

# Wizard spell slots by character level; only level 5 is populated.
WIZARD_SPELL_SLOTS = {
    5: {"1": 4, "2": 3, "3": 2},
}

# Maximum prepared spells per class, keyed by character level; only wizard
# level 1 is populated (max 1 prepared spell).
MAX_PREPARED_SPELLS = {
    "wizard": {1: 1},
}

# Spell slots available for *casting* (as opposed to the PHB spell-slots
# reference table above), keyed by class -> character level -> spell level.
# Cantrips (spell level 0) are an at-will resource in 5e and are represented
# with a large sentinel count rather than a strict slot pool. Only wizard
# level 1 is populated, matching MAX_PREPARED_SPELLS.
CASTING_SPELL_SLOTS = {
    "wizard": {1: {0: 9999, 1: 1}},
}

DIFFICULTY_RECOMMENDATIONS = {
    "trivial": "no real threat",
    "easy": "safe warm-up",
    "medium": "balanced challenge",
    "hard": "tough fight, expect resource drain",
    "deadly": "deadly encounter, prepare escape options",
}

# DM loot-parcel presets by tier; only tier 1 is populated.
DM_LOOT_TIERS = {
    1: {"coins_gp": 75, "items": [{"slug": "healing-potion", "quantity": 2}]},
}

# (level_low, level_high, proficiency_bonus)
PROFICIENCY_TABLE = [
    (1, 4, 2),
    (5, 8, 3),
    (9, 12, 4),
    (13, 16, 5),
    (17, 20, 6),
]

# PHB skill -> governing ability, keyed by skill slug.
SKILL_ABILITY = {
    "acrobatics": "dex",
    "animal-handling": "wis",
    "arcana": "int",
    "athletics": "str",
    "deception": "cha",
    "history": "int",
    "insight": "wis",
    "intimidation": "cha",
    "investigation": "int",
    "medicine": "wis",
    "nature": "int",
    "perception": "wis",
    "performance": "cha",
    "persuasion": "cha",
    "religion": "int",
    "sleight-of-hand": "dex",
    "stealth": "dex",
    "survival": "wis",
}

USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")

# Level-1 hit die base per class (PHB). hp_max at level 1 = base + con modifier.
CLASS_HIT_DIE = {
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
    "human", "elf", "dwarf", "halfling", "dragonborn",
    "gnome", "half-elf", "half-orc", "tiefling",
}

# Known spells per class, keyed by spell_id -> (canonical name, level).
# Only "wizard" is populated: wizards may know any spell on their list;
# classes absent from this table (e.g. rogue) may not learn any spells.
CLASS_SPELL_LIST = {
    "wizard": {
        "fire-bolt": ("Fire Bolt", 0),
        "mage-hand": ("Mage Hand", 0),
        "prestidigitation": ("Prestidigitation", 0),
        "ray-of-frost": ("Ray of Frost", 0),
        "magic-missile": ("Magic Missile", 1),
        "shield": ("Shield", 1),
        "detect-magic": ("Detect Magic", 1),
        "identify": ("Identify", 1),
    },
}

VALID_BACKGROUNDS = {
    "acolyte", "criminal", "folk-hero", "noble", "sage", "soldier",
    "charlatan", "entertainer", "guild-artisan", "hermit", "outlander",
    "sailor",
}

VALID_INVENTORY_ITEM_IDS = {
    "healing-potion", "torch",
    "leather-armor", "ring-of-protection", "amulet-of-health",
}

VALID_EQUIPMENT_SLOTS = {"armor", "accessory"}

ITEM_EQUIPMENT_SLOT = {
    "leather-armor": "armor",
    "ring-of-protection": "accessory",
    "amulet-of-health": "accessory",
}

ATTUNABLE_ITEM_IDS = {"ring-of-protection", "amulet-of-health"}

MAX_ATTUNEMENTS = 1

CONSUMABLE_ITEM_EFFECTS = {
    "healing-potion": {"type": "healing", "hp_restored": 5},
}


def max_prepared_spells(klass, level):
    return MAX_PREPARED_SPELLS.get(klass, {}).get(level, 0)


def casting_spell_slots(klass, level, spell_level):
    """Total slots of `spell_level` available to `klass` at `level` (0 if none)."""
    return CASTING_SPELL_SLOTS.get(klass, {}).get(level, {}).get(spell_level, 0)


def level_one_hp_max(klass, con_modifier):
    return max(1, CLASS_HIT_DIE[klass] + con_modifier)


def hp_gain_per_level(klass, con_modifier):
    """Deterministic (fixed, non-random) HP gain for levels beyond 1.

    Uses the standard 5e "fixed value" in place of rolling the hit die:
    half the die size rounded up, plus one (e.g. 1d8 -> 5).
    """
    die = CLASS_HIT_DIE[klass]
    return max(1, die // 2 + 1 + con_modifier)


def is_plain_int(x):
    """True for real ints, excluding bool (bool is a subclass of int)."""
    return isinstance(x, int) and not isinstance(x, bool)


def ability_modifier(score):
    return (score - 10) // 2


SEASON_OFFSETS = {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}
WEATHER_BY_OFFSET = {0: "clear", 1: "rain", 2: "wind", 3: "snow"}


def weather_for(day, season):
    offset = (day + SEASON_OFFSETS[season]) % 4
    return WEATHER_BY_OFFSET[offset]


def proficiency_bonus(level):
    for lo, hi, bonus in PROFICIENCY_TABLE:
        if lo <= level <= hi:
            return bonus
    return None


def multiplier_for_count(n):
    """Encounter-multiplier table from the DMG, keyed by monster count."""
    if n <= 1:
        return 1
    if n == 2:
        return 1.5
    if 3 <= n <= 6:
        return 2
    if 7 <= n <= 10:
        return 2.5
    if 11 <= n <= 14:
        return 3
    return 4


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000)
    return salt, digest.hex()


def verify_password(password, salt, expected_hex):
    _, digest_hex = hash_password(password, salt)
    return hmac.compare_digest(digest_hex, expected_hex)
