"""Pure, stateless D&D game-domain logic."""

from .constants import CR_XP, LEVEL_THRESHOLDS


def ability_modifier(score):
    """D&D 5e ability modifier: floor((score - 10) / 2)."""
    return (score - 10) // 2


def proficiency_bonus(level):
    """D&D 5e proficiency bonus by character tier."""
    if level <= 4:
        return 2
    if level <= 8:
        return 3
    if level <= 12:
        return 4
    if level <= 16:
        return 5
    return 6


def _normalize_number(value):
    """Return int if value has no fractional part, else the original float."""
    if value == int(value):
        return int(value)
    return value


def compute_encounter_xp(party, monsters):
    """Compute encounter XP, multiplier, difficulty, and party thresholds.

    Raises ValueError with a descriptive message for invalid inputs. The outer
    iteration over ``monsters`` and ``party`` is intentionally left uncaught so
    that non-iterable inputs propagate the same way the original view did.
    """
    base_xp = 0
    monster_count = 0
    for monster in monsters:
        try:
            cr = str(monster["cr"])
            count = int(monster["count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid monster entry") from exc
        if cr not in CR_XP or count <= 0:
            raise ValueError("invalid monster entry")
        base_xp += CR_XP[cr] * count
        monster_count += count

    # DMG encounter multiplier based on monster count.
    if monster_count == 1:
        multiplier = 1.0
    elif monster_count == 2:
        multiplier = 1.5
    elif monster_count <= 6:
        multiplier = 2.0
    elif monster_count <= 10:
        multiplier = 2.5
    elif monster_count <= 14:
        multiplier = 3.0
    else:
        multiplier = 4.0

    adjusted_xp = _normalize_number(base_xp * multiplier)
    multiplier = _normalize_number(multiplier)

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        try:
            level = int(member["level"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid party entry") from exc
        if level not in LEVEL_THRESHOLDS:
            raise ValueError("unsupported level")
        easy, medium, hard, deadly = LEVEL_THRESHOLDS[level]
        thresholds["easy"] += easy
        thresholds["medium"] += medium
        thresholds["hard"] += hard
        thresholds["deadly"] += deadly

    if adjusted_xp >= thresholds["deadly"]:
        difficulty = "deadly"
    elif adjusted_xp >= thresholds["hard"]:
        difficulty = "hard"
    elif adjusted_xp >= thresholds["medium"]:
        difficulty = "medium"
    elif adjusted_xp >= thresholds["easy"]:
        difficulty = "easy"
    else:
        difficulty = "trivial"

    return {
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": multiplier,
        "adjusted_xp": adjusted_xp,
        "difficulty": difficulty,
        "thresholds": thresholds,
    }


def build_initiative_order(combatants):
    """Return initiative order sorted by score desc, dex desc, name asc.

    ``combatants`` is an iterable of dicts with keys ``name`` (str), ``dex``
    (int), and ``roll`` (int). The caller is responsible for validation.
    """
    scored = [(c["name"], c["dex"], c["roll"] + c["dex"]) for c in combatants]
    # Deterministic tie-breaker: higher score, then higher dex, then name.
    scored.sort(key=lambda x: (-x[2], -x[1], x[0]))
    return [{"name": name, "score": score} for name, dex, score in scored]


def encounter_recommendation(difficulty):
    """Short DM recommendation string for an encounter difficulty."""
    return {
        "trivial": "no risk",
        "easy": "safe warm-up",
        "medium": "balanced challenge",
        "hard": "tough fight",
        "deadly": "deadly encounter",
    }.get(difficulty, "unknown")


def parse_combatant(raw):
    """Validate and normalize a single combatant dict.

    Raises KeyError, TypeError, or ValueError if any field is missing or wrong.
    """
    return {
        "name": str(raw["name"]),
        "dex": int(raw["dex"]),
        "roll": int(raw["roll"]),
    }
