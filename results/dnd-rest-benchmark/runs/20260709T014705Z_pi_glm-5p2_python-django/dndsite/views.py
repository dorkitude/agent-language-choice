import json
import re

from django.http import JsonResponse, HttpResponseBadRequest

# Challenge rating -> XP (first benchmark suite).
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

# Per-level encounter thresholds (first benchmark suite: level 3 only).
LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

# <count>d<sides>[+<modifier>|-<modifier>]
DICE_RE = re.compile(r"^(\d+)d(\d+)(?:([+-]\d+))?$")


def _num(x):
    """Return an int when the value is integral, otherwise a float."""
    f = float(x)
    if f.is_integer():
        return int(f)
    return f


def _monster_multiplier(count):
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
    if count >= 15:
        return 4
    return 1  # count <= 0: no monsters, neutral multiplier.


def _parse_json(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return None


def _bad():
    return HttpResponseBadRequest()


def health(request):
    return JsonResponse({"ok": True})


def dice_stats(request):
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad()
    expression = data.get("expression")
    if not isinstance(expression, str):
        return _bad()
    m = DICE_RE.fullmatch(expression)
    if not m:
        return _bad()
    count = int(m.group(1))
    sides = int(m.group(2))
    modifier = int(m.group(3)) if m.group(3) else 0
    if count <= 0 or sides <= 0:
        return _bad()
    mn = count + modifier
    mx = count * sides + modifier
    avg = (mn + mx) / 2
    return JsonResponse({
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": mn,
        "max": mx,
        "average": _num(avg),
    })


def ability_check(request):
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad()
    try:
        roll = int(data["roll"])
        modifier = int(data["modifier"])
        dc = int(data["dc"])
    except (KeyError, TypeError, ValueError):
        return _bad()
    total = roll + modifier
    return JsonResponse({
        "total": total,
        "success": total >= dc,
        "margin": total - dc,
    })


def adjusted_xp(request):
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad()
    party = data.get("party")
    monsters = data.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        return _bad()

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            return _bad()
        try:
            level = int(member["level"])
        except (KeyError, TypeError, ValueError):
            return _bad()
        th = LEVEL_THRESHOLDS.get(level)
        if th is None:
            return _bad()
        for key in thresholds:
            thresholds[key] += th[key]

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        if not isinstance(monster, dict):
            return _bad()
        cr = monster.get("cr")
        try:
            count = int(monster["count"])
        except (KeyError, TypeError, ValueError):
            return _bad()
        if not isinstance(cr, str) or count < 0:
            return _bad()
        xp = CR_XP.get(cr)
        if xp is None:
            return _bad()
        base_xp += xp * count
        monster_count += count

    multiplier = _monster_multiplier(monster_count)
    adjusted = base_xp * multiplier

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

    return JsonResponse({
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": _num(multiplier),
        "adjusted_xp": _num(adjusted),
        "difficulty": difficulty,
        "thresholds": thresholds,
    })


def initiative_order(request):
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad()
    combatants = data.get("combatants")
    if not isinstance(combatants, list):
        return _bad()

    entries = []
    for c in combatants:
        if not isinstance(c, dict):
            return _bad()
        try:
            name = c["name"]
            dex = int(c["dex"])
            roll = int(c["roll"])
        except (KeyError, TypeError, ValueError):
            return _bad()
        entries.append((roll + dex, dex, name))

    # score desc, dex desc, name asc.
    entries.sort(key=lambda e: (-e[0], -e[1], e[2]))

    return JsonResponse({
        "order": [{"name": e[2], "score": e[0]} for e in entries]
    })
