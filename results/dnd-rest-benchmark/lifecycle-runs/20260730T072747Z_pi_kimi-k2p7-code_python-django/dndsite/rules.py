"""D&D 5e-style calculations shared by the API endpoints.

This is a deliberately narrow rules implementation: only the specific levels,
CRs, classes, and formulas exercised by the API are supported.
"""

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

LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}


def _monster_multiplier(count):
    """DMG encounter multiplier based on the number of monsters."""
    if count == 1:
        return 1
    if count == 2:
        return 1.5
    if count <= 6:
        return 2
    if count <= 10:
        return 2.5
    if count <= 14:
        return 3
    return 4


def _ability_modifier(score):
    return (score - 10) // 2


def _proficiency_bonus(level):
    return (level - 1) // 4 + 2


def compute_initiative_order(combatants):
    """Return combatants sorted by initiative score, then dex, then name.

    Raises ValueError if the input shape is unexpected.
    """
    scored = []
    for combatant in combatants:
        scored.append({
            "name": str(combatant["name"]),
            "dex": int(combatant["dex"]),
            "score": int(combatant["roll"]) + int(combatant["dex"]),
        })

    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
    return [{"name": c["name"], "score": c["score"]} for c in scored]


def evaluate_encounter(party, monsters):
    """Compute base XP, adjusted XP, multiplier, difficulty, and thresholds.

    Args:
        party: iterable of dicts with integer "level".
        monsters: iterable of dicts with "cr" and integer "count".

    Returns:
        A dict with the encounter math.

    Raises:
        ValueError: if a party level or monster CR is not supported. The message
            matches the API's error string.
    """
    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = int(member["level"])
        level_thresholds = LEVEL_THRESHOLDS.get(level)
        if not level_thresholds:
            raise ValueError("unsupported level")
        for key in thresholds:
            thresholds[key] += level_thresholds[key]

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        cr = monster["cr"]
        count = int(monster["count"])
        if cr not in XP_TABLE:
            raise ValueError("unsupported cr")
        base_xp += XP_TABLE[cr] * count
        monster_count += count

    multiplier = _monster_multiplier(monster_count)
    adjusted_xp = int(base_xp * multiplier)

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
