"""Pure game-rule and authentication computations.

These functions are deterministic, side-effect free, and depend only on the
constants in `constants.py`.
"""

import hashlib
import hmac

from constants import DICE_RE, THRESHOLDS, XP


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


def verify_password(password: str, salt: bytes, expected_hash: bytes) -> bool:
    """Constant-time password verification."""
    return hmac.compare_digest(hash_password(password, salt), expected_hash)
