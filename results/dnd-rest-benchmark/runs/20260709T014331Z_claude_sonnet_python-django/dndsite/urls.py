import json
import re

from django.http import JsonResponse
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


def health(request):
    return JsonResponse({"ok": True})


def _bad_request(message="invalid request"):
    return JsonResponse({"error": message}, status=400)


def _parse_json(request):
    try:
        return json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


DICE_RE = re.compile(r"^(\d+)d(\d+)(?:([+-])(\d+))?$")


@csrf_exempt
@require_POST
def dice_stats(request):
    data = _parse_json(request)
    if data is None:
        return _bad_request()

    expression = data.get("expression")
    if not isinstance(expression, str):
        return _bad_request()

    match = DICE_RE.match(expression.strip())
    if not match:
        return _bad_request()

    count = int(match.group(1))
    sides = int(match.group(2))
    sign = match.group(3)
    magnitude = match.group(4)
    modifier = 0
    if magnitude is not None:
        modifier = int(magnitude)
        if sign == "-":
            modifier = -modifier

    if count <= 0 or sides <= 0:
        return _bad_request()

    return JsonResponse({
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": count * 1 + modifier,
        "max": count * sides + modifier,
        "average": (count * (sides + 1) / 2) + modifier,
    })


@csrf_exempt
@require_POST
def ability_check(request):
    data = _parse_json(request)
    if data is None:
        return _bad_request()

    try:
        roll = data["roll"]
        modifier = data["modifier"]
        dc = data["dc"]
    except KeyError:
        return _bad_request()

    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (roll, modifier, dc)):
        return _bad_request()

    total = roll + modifier
    return JsonResponse({
        "total": total,
        "success": total >= dc,
        "margin": total - dc,
    })


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


def _multiplier(monster_count):
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


@csrf_exempt
@require_POST
def adjusted_xp(request):
    data = _parse_json(request)
    if data is None:
        return _bad_request()

    party = data.get("party")
    monsters = data.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        return _bad_request()

    thresholds_sum = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = member.get("level")
        thresholds = LEVEL_THRESHOLDS.get(level)
        if thresholds is None:
            return _bad_request()
        for key in thresholds_sum:
            thresholds_sum[key] += thresholds[key]

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        cr = monster.get("cr")
        count = monster.get("count")
        xp = CR_XP.get(cr)
        if xp is None or not isinstance(count, int) or count <= 0:
            return _bad_request()
        base_xp += xp * count
        monster_count += count

    multiplier = _multiplier(monster_count)
    adjusted = base_xp * multiplier

    difficulty = "trivial"
    for key in ("easy", "medium", "hard", "deadly"):
        if adjusted >= thresholds_sum[key]:
            difficulty = key

    return JsonResponse({
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": multiplier,
        "adjusted_xp": adjusted,
        "difficulty": difficulty,
        "thresholds": thresholds_sum,
    })


@csrf_exempt
@require_POST
def initiative_order(request):
    data = _parse_json(request)
    if data is None:
        return _bad_request()

    combatants = data.get("combatants")
    if not isinstance(combatants, list):
        return _bad_request()

    scored = []
    for c in combatants:
        name = c.get("name")
        dex = c.get("dex")
        roll = c.get("roll")
        if name is None or dex is None or roll is None:
            return _bad_request()
        scored.append({"name": name, "dex": dex, "score": roll + dex})

    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))

    return JsonResponse({
        "order": [{"name": c["name"], "score": c["score"]} for c in scored],
    })


urlpatterns = [
    path("health", health),
    path("v1/dice/stats", dice_stats),
    path("v1/checks/ability", ability_check),
    path("v1/encounters/adjusted-xp", adjusted_xp),
    path("v1/initiative/order", initiative_order),
]
