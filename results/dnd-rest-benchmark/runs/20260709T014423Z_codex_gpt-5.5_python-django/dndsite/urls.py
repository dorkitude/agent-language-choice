import json
import re

from django.http import JsonResponse
from django.urls import path


DICE_RE = re.compile(r"^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$")

MONSTER_XP = {
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


def json_error(status=400):
    return JsonResponse({"error": "bad request"}, status=status)


def load_json(request):
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return None


def require_post(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    return None


def health(request):
    return JsonResponse({"ok": True})


def dice_stats(request):
    method_error = require_post(request)
    if method_error:
        return method_error

    body = load_json(request)
    if not isinstance(body, dict) or not isinstance(body.get("expression"), str):
        return json_error()

    match = DICE_RE.fullmatch(body["expression"])
    if not match:
        return json_error()

    dice_count = int(match.group(1))
    sides = int(match.group(2))
    if dice_count <= 0 or sides <= 0:
        return json_error()

    modifier = int(match.group(4) or 0)
    if match.group(3) == "-":
        modifier = -modifier

    min_value = dice_count + modifier
    max_value = dice_count * sides + modifier
    average = dice_count * (sides + 1) / 2 + modifier
    if average.is_integer():
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


def ability_check(request):
    method_error = require_post(request)
    if method_error:
        return method_error

    body = load_json(request)
    if not isinstance(body, dict):
        return json_error()

    try:
        roll = int(body["roll"])
        modifier = int(body["modifier"])
        dc = int(body["dc"])
    except (KeyError, TypeError, ValueError):
        return json_error()

    total = roll + modifier
    return JsonResponse({"total": total, "success": total >= dc, "margin": total - dc})


def monster_multiplier(monster_count):
    if monster_count <= 0:
        return None
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


def adjusted_xp(request):
    method_error = require_post(request)
    if method_error:
        return method_error

    body = load_json(request)
    if not isinstance(body, dict):
        return json_error()

    party = body.get("party")
    monsters = body.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        return json_error()

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    try:
        for member in party:
            level = int(member["level"])
            level_thresholds = LEVEL_THRESHOLDS[level]
            for name, value in level_thresholds.items():
                thresholds[name] += value

        base_xp = 0
        monster_count = 0
        for monster in monsters:
            cr = str(monster["cr"])
            count = int(monster["count"])
            if count <= 0:
                return json_error()
            base_xp += MONSTER_XP[cr] * count
            monster_count += count
    except (KeyError, TypeError, ValueError):
        return json_error()

    multiplier = monster_multiplier(monster_count)
    if multiplier is None:
        return json_error()

    adjusted = base_xp * multiplier
    adjusted_xp_value = int(adjusted) if float(adjusted).is_integer() else adjusted
    difficulty = "trivial"
    for name in ("easy", "medium", "hard", "deadly"):
        if adjusted_xp_value >= thresholds[name]:
            difficulty = name

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


def initiative_order(request):
    method_error = require_post(request)
    if method_error:
        return method_error

    body = load_json(request)
    if not isinstance(body, dict) or not isinstance(body.get("combatants"), list):
        return json_error()

    combatants = []
    try:
        for combatant in body["combatants"]:
            name = str(combatant["name"])
            dex = int(combatant["dex"])
            roll = int(combatant["roll"])
            combatants.append({"name": name, "dex": dex, "score": roll + dex})
    except (KeyError, TypeError, ValueError):
        return json_error()

    ordered = sorted(combatants, key=lambda item: (-item["score"], -item["dex"], item["name"]))
    return JsonResponse({"order": [{"name": item["name"], "score": item["score"]} for item in ordered]})


urlpatterns = [
    path("health", health),
    path("v1/dice/stats", dice_stats),
    path("v1/checks/ability", ability_check),
    path("v1/encounters/adjusted-xp", adjusted_xp),
    path("v1/initiative/order", initiative_order),
]
