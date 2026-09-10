"""Pure game-rule and authentication computations.

These functions are deterministic, side-effect free, and depend only on the
constants in `constants.py`.
"""

import hashlib
import hmac

from constants import CLASS_HP_BASE, DICE_RE, THRESHOLDS, XP

# Full spellcasting classes that use the standard PHB spell-slot progression.
FULL_CASTER_CLASSES = {"bard", "cleric", "druid", "sorcerer", "wizard"}

# Standard full-caster spell slots by character level and slot level.
FULL_CASTER_SLOTS = {
    1: {1: 1},
    2: {1: 3},
    3: {1: 4, 2: 2},
    4: {1: 4, 2: 3},
    5: {1: 4, 2: 3, 3: 2},
    6: {1: 4, 2: 3, 3: 3},
    7: {1: 4, 2: 3, 3: 3, 4: 1},
    8: {1: 4, 2: 3, 3: 3, 4: 2},
    9: {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},
    10: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},
    11: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},
    12: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},
    13: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},
    14: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},
    15: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1},
    16: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1},
    17: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1, 9: 1},
    18: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 1, 7: 1, 8: 1, 9: 1},
    19: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 1, 8: 1, 9: 1},
    20: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 2, 8: 1, 9: 1},
}


def multiplier(monster_count: int) -> float:
    """Encounter multiplier based on the total number of monsters (DMG table)."""
    if monster_count == 1:
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


def ability_modifier(score: int) -> int:
    """D&D 5e ability score modifier; floors negative halves."""
    return (score - 10) // 2


def hit_die_for_class(class_: str) -> str:
    """Return the hit-dice expression for a PHB class (e.g. '1d8')."""
    sides = CLASS_HP_BASE[class_]
    return f"1d{sides}"


def average_hit_die_value(class_: str) -> int:
    """Deterministic HP gain per level: average hit die, rounded up."""
    return CLASS_HP_BASE[class_] // 2 + 1


def max_hp_for_level(class_: str, level: int, con_modifier: int) -> int:
    """Maximum HP for a character of class/level with the given CON modifier.

    Level 1 uses the maximum hit die plus CON; each additional level adds the
    deterministic average hit die value plus CON.
    """
    base = CLASS_HP_BASE[class_]
    avg = average_hit_die_value(class_)
    return base + con_modifier + (level - 1) * (avg + con_modifier)


def proficiency_bonus(level: int) -> int:
    """Proficiency bonus for a character of the given level (1-20)."""
    if level <= 4:
        return 2
    if level <= 8:
        return 3
    if level <= 12:
        return 4
    if level <= 16:
        return 5
    return 6


def parse_dice(expr: str):
    """Parse a dice expression like '2d6+3' into (count, sides, modifier)."""
    m = DICE_RE.match(expr)
    if not m:
        raise ValueError("invalid expression")
    count = int(m.group(1))
    sides = int(m.group(2))
    if count <= 0 or sides <= 0:
        raise ValueError("count and sides must be positive")
    mod = 0
    if m.group(3):
        mod = int(m.group(4))
        if m.group(3) == "-":
            mod = -mod
    return count, sides, mod


def calculate_difficulty(party, monsters):
    """Calculate encounter difficulty using the DMG base/adjusted XP rules.

    `party` is a list of dicts with a `level` key. `monsters` is a list of dicts
    with `cr` and `count` keys.
    """
    base_xp = sum(XP[m["cr"]] * m["count"] for m in monsters)
    monster_count = sum(m["count"] for m in monsters)
    mult = multiplier(monster_count)
    adjusted = int(base_xp * mult)
    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = member["level"]
        t = THRESHOLDS[level]
        for key in thresholds:
            thresholds[key] += t[key]
    if adjusted >= thresholds["deadly"]:
        difficulty = "deadly"
    elif adjusted >= thresholds["hard"]:
        difficulty = "hard"
    elif adjusted >= thresholds["medium"]:
        difficulty = "medium"
    elif adjusted >= thresholds["easy"]:
        difficulty = "easy"
    else:
        difficulty = "trivial"
    return {
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": mult,
        "adjusted_xp": adjusted,
        "difficulty": difficulty,
        "thresholds": thresholds,
    }


def recommendation_for(difficulty):
    """Short DM-facing recommendation for an encounter difficulty tier."""
    return {
        "trivial": "no challenge",
        "easy": "safe warm-up",
        "medium": "balanced fight",
        "hard": "risky encounter",
        "deadly": "deadly threat",
    }.get(difficulty, "unknown")


def hash_password(password: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256 password hash with 100,000 iterations."""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)


def skill_check_modifier(ability_score: int, proficiency_bonus: int, proficient: bool) -> int:
    """Skill-check modifier: ability modifier plus proficiency when proficient."""
    modifier = ability_modifier(ability_score)
    if proficient:
        modifier += proficiency_bonus
    return modifier


def is_spellcasting_class(class_: str) -> bool:
    """Return True for classes that use the standard full-caster slot progression."""
    return class_ in FULL_CASTER_CLASSES


def spell_slots(class_: str, level: int):
    """Return a dict of slot level -> remaining slots for a full caster.

    Non-casting classes and unsupported levels receive an empty mapping.
    """
    if not is_spellcasting_class(class_):
        return {}
    slots = FULL_CASTER_SLOTS.get(level)
    if slots is None:
        return {}
    return dict(slots)


def verify_password(password: str, salt: bytes, expected_hash: bytes) -> bool:
    """Constant-time password verification."""
    return hmac.compare_digest(hash_password(password, salt), expected_hash)


def compute_rng_roll(seed: str, sequence: int, roll_id: str, sides: int) -> int:
    """Deterministic campaign-scoped roll result.

    Build ``seed + "|" + sequence + "|" + roll_id + "|" + sides`` and hash
    the UTF-8 bytes with a 31-shift unsigned 32-bit accumulator. Returns
    ``(acc mod sides) + 1``.
    """
    byte_string = f"{seed}|{sequence}|{roll_id}|{sides}".encode("utf-8")
    acc = 0
    for b in byte_string:
        acc = (acc * 31 + b) & 0xFFFFFFFF
    return (acc % sides) + 1
