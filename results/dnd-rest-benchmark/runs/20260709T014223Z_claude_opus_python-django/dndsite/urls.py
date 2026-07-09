import json
import re

from django.http import JsonResponse
from django.urls import path
from django.views.decorators.csrf import csrf_exempt

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

DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")


def _num(value):
    """Return an int when the value is whole, else a float."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _parse_json(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def health(request):
    return JsonResponse({"ok": True})


@csrf_exempt
def dice_stats(request):
    data = _parse_json(request)
    if not isinstance(data, dict):
        return JsonResponse({"error": "invalid request"}, status=400)

    expression = data.get("expression")
    if not isinstance(expression, str):
        return JsonResponse({"error": "invalid expression"}, status=400)

    match = DICE_RE.match(expression.strip())
    if not match:
        return JsonResponse({"error": "invalid expression"}, status=400)

    count = int(match.group(1))
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0

    if count <= 0 or sides <= 0:
        return JsonResponse({"error": "invalid expression"}, status=400)

    minimum = count * 1 + modifier
    maximum = count * sides + modifier
    average = count * (1 + sides) / 2 + modifier

    return JsonResponse(
        {
            "dice_count": count,
            "sides": sides,
            "modifier": modifier,
            "min": minimum,
            "max": maximum,
            "average": _num(average),
        }
    )


@csrf_exempt
def ability_check(request):
    data = _parse_json(request)
    if not isinstance(data, dict):
        return JsonResponse({"error": "invalid request"}, status=400)

    try:
        roll = int(data["roll"])
        modifier = int(data["modifier"])
        dc = int(data["dc"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "invalid request"}, status=400)

    total = roll + modifier
    return JsonResponse(
        {
            "total": total,
            "success": total >= dc,
            "margin": total - dc,
        }
    )


def _multiplier(monster_count):
    if monster_count <= 1:
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


@csrf_exempt
def adjusted_xp(request):
    data = _parse_json(request)
    if not isinstance(data, dict):
        return JsonResponse({"error": "invalid request"}, status=400)

    party = data.get("party")
    monsters = data.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        return JsonResponse({"error": "invalid request"}, status=400)

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        if not isinstance(monster, dict):
            return JsonResponse({"error": "invalid monster"}, status=400)
        cr = monster.get("cr")
        count = monster.get("count")
        cr_key = str(cr)
        if cr_key not in CR_XP or not isinstance(count, int):
            return JsonResponse({"error": "invalid monster"}, status=400)
        base_xp += CR_XP[cr_key] * count
        monster_count += count

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            return JsonResponse({"error": "invalid party"}, status=400)
        level = member.get("level")
        if level not in LEVEL_THRESHOLDS:
            return JsonResponse({"error": "unsupported level"}, status=400)
        for key, value in LEVEL_THRESHOLDS[level].items():
            thresholds[key] += value

    multiplier = _multiplier(monster_count)
    adjusted = base_xp * multiplier

    difficulty = "trivial"
    for name in ("easy", "medium", "hard", "deadly"):
        if adjusted >= thresholds[name]:
            difficulty = name

    return JsonResponse(
        {
            "base_xp": base_xp,
            "monster_count": monster_count,
            "multiplier": _num(multiplier),
            "adjusted_xp": _num(adjusted),
            "difficulty": difficulty,
            "thresholds": thresholds,
        }
    )


@csrf_exempt
def initiative_order(request):
    data = _parse_json(request)
    if not isinstance(data, dict):
        return JsonResponse({"error": "invalid request"}, status=400)

    combatants = data.get("combatants")
    if not isinstance(combatants, list):
        return JsonResponse({"error": "invalid request"}, status=400)

    entries = []
    for combatant in combatants:
        if not isinstance(combatant, dict):
            return JsonResponse({"error": "invalid combatant"}, status=400)
        try:
            name = combatant["name"]
            dex = int(combatant["dex"])
            roll = int(combatant["roll"])
        except (KeyError, TypeError, ValueError):
            return JsonResponse({"error": "invalid combatant"}, status=400)
        if not isinstance(name, str):
            return JsonResponse({"error": "invalid combatant"}, status=400)
        entries.append({"name": name, "dex": dex, "score": roll + dex})

    entries.sort(key=lambda e: (-e["score"], -e["dex"], e["name"]))

    return JsonResponse(
        {"order": [{"name": e["name"], "score": e["score"]} for e in entries]}
    )


urlpatterns = [
    path("health", health),
    path("v1/dice/stats", dice_stats),
    path("v1/checks/ability", ability_check),
    path("v1/encounters/adjusted-xp", adjusted_xp),
    path("v1/initiative/order", initiative_order),
]
