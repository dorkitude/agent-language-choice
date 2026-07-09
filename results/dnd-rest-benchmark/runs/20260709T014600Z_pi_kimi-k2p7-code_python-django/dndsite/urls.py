import json
import re

from django.http import JsonResponse
from django.urls import path
from django.views.decorators.http import require_http_methods


def _bad_request(message="Invalid request"):
    return JsonResponse({"error": message}, status=400)


def health(request):
    return JsonResponse({"ok": True})


DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")


@require_http_methods(["POST"])
def dice_stats(request):
    try:
        data = json.loads(request.body)
        expr = data["expression"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return _bad_request()

    match = DICE_RE.match(str(expr))
    if not match:
        return _bad_request("Invalid expression")

    dice_count = int(match.group(1))
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0

    if dice_count <= 0 or sides <= 0:
        return _bad_request("count and sides must be positive")

    min_value = dice_count + modifier
    max_value = dice_count * sides + modifier
    average = dice_count * (sides + 1) / 2 + modifier
    if isinstance(average, float) and average.is_integer():
        average = int(average)

    return JsonResponse(
        {
            "dice_count": dice_count,
            "sides": sides,
            "modifier": modifier,
            "min": min_value,
            "max": max_value,
            "average": average,
        }
    )


@require_http_methods(["POST"])
def ability_check(request):
    try:
        data = json.loads(request.body)
        roll = int(data["roll"])
        modifier = int(data["modifier"])
        dc = int(data["dc"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return _bad_request()

    total = roll + modifier
    return JsonResponse(
        {
            "total": total,
            "success": total >= dc,
            "margin": total - dc,
        }
    )


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

LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}


def _encounter_multiplier(monster_count):
    if monster_count == 1:
        return 1
    if monster_count == 2:
        return 1.5
    if 3 <= monster_count <= 6:
        return 2
    if 7 <= monster_count <= 10:
        return 2.5
    if 11 <= monster_count <= 14:
        return 3
    return 4


@require_http_methods(["POST"])
def adjusted_xp(request):
    try:
        data = json.loads(request.body)
        party = data["party"]
        monsters = data["monsters"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return _bad_request()

    if not isinstance(party, list) or not isinstance(monsters, list):
        return _bad_request()

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = int(member["level"])
        level_thresholds = LEVEL_THRESHOLDS.get(level)
        if level_thresholds is None:
            return _bad_request("Unsupported level")
        for key in thresholds:
            thresholds[key] += level_thresholds[key]

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        cr = str(monster["cr"])
        count = int(monster["count"])
        xp = CR_XP.get(cr)
        if xp is None or count <= 0:
            return _bad_request("Unsupported CR or invalid count")
        base_xp += xp * count
        monster_count += count

    multiplier = _encounter_multiplier(monster_count)
    adjusted_xp_value = base_xp * multiplier
    if isinstance(adjusted_xp_value, float) and adjusted_xp_value.is_integer():
        adjusted_xp_value = int(adjusted_xp_value)

    if adjusted_xp_value >= thresholds["deadly"]:
        difficulty = "deadly"
    elif adjusted_xp_value >= thresholds["hard"]:
        difficulty = "hard"
    elif adjusted_xp_value >= thresholds["medium"]:
        difficulty = "medium"
    elif adjusted_xp_value >= thresholds["easy"]:
        difficulty = "easy"
    else:
        difficulty = "trivial"

    return JsonResponse(
        {
            "base_xp": base_xp,
            "monster_count": monster_count,
            "multiplier": multiplier,
            "adjusted_xp": adjusted_xp_value,
            "difficulty": difficulty,
            "thresholds": thresholds,
        }
    )


@require_http_methods(["POST"])
def initiative_order(request):
    try:
        data = json.loads(request.body)
        combatants = data["combatants"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return _bad_request()

    if not isinstance(combatants, list):
        return _bad_request()

    scored = []
    for combatant in combatants:
        name = str(combatant["name"])
        dex = int(combatant["dex"])
        roll = int(combatant["roll"])
        scored.append((name, roll + dex, dex))

    scored.sort(key=lambda item: (-item[1], -item[2], item[0]))

    return JsonResponse(
        {"order": [{"name": name, "score": score} for name, score, _ in scored]}
    )


urlpatterns = [
    path("health", health),
    path("v1/dice/stats", dice_stats),
    path("v1/checks/ability", ability_check),
    path("v1/encounters/adjusted-xp", adjusted_xp),
    path("v1/initiative/order", initiative_order),
]
