import json
import math
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


def health(request):
    return JsonResponse({"ok": True})


def _json_body(request):
    return json.loads(request.body.decode("utf-8") or "{}")


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
def dice_stats(request):
    try:
        body = _json_body(request)
        expression = body["expression"]
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    match = DICE_RE.match(expression.strip()) if isinstance(expression, str) else None
    if not match:
        return JsonResponse({"error": "invalid expression"}, status=400)

    count = int(match.group(1))
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0

    if count <= 0 or sides <= 0:
        return JsonResponse({"error": "invalid expression"}, status=400)

    minimum = count * 1 + modifier
    maximum = count * sides + modifier
    average = (minimum + maximum) / 2
    if average == int(average):
        average = int(average)

    return JsonResponse({
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": minimum,
        "max": maximum,
        "average": average,
    })


@csrf_exempt
def ability_check(request):
    try:
        body = _json_body(request)
        roll = body["roll"]
        modifier = body["modifier"]
        dc = body["dc"]
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    total = roll + modifier
    success = total >= dc
    margin = total - dc

    return JsonResponse({"total": total, "success": success, "margin": margin})


@csrf_exempt
def adjusted_xp(request):
    try:
        body = _json_body(request)
        party = body["party"]
        monsters = body["monsters"]
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    try:
        base_xp = 0
        monster_count = 0
        for monster in monsters:
            cr = str(monster["cr"])
            count = int(monster["count"])
            base_xp += CR_XP[cr] * count
            monster_count += count

        multiplier = _multiplier(monster_count)
        adjusted = base_xp * multiplier

        thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
        for member in party:
            level = int(member["level"])
            level_thresholds = LEVEL_THRESHOLDS[level]
            for key in thresholds:
                thresholds[key] += level_thresholds[key]
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    difficulty = "trivial"
    for key in ("easy", "medium", "hard", "deadly"):
        if adjusted >= thresholds[key]:
            difficulty = key

    return JsonResponse({
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": multiplier,
        "adjusted_xp": adjusted,
        "difficulty": difficulty,
        "thresholds": thresholds,
    })


@csrf_exempt
def initiative_order(request):
    try:
        body = _json_body(request)
        combatants = body["combatants"]
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    try:
        scored = []
        for combatant in combatants:
            name = combatant["name"]
            dex = combatant["dex"]
            roll = combatant["roll"]
            score = roll + dex
            scored.append({"name": name, "dex": dex, "score": score})
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
    order = [{"name": c["name"], "score": c["score"]} for c in scored]

    return JsonResponse({"order": order})


PROFICIENCY_TABLE = [
    (4, 2),
    (8, 3),
    (12, 4),
    (16, 5),
    (20, 6),
]


def _ability_modifier(score):
    return math.floor((score - 10) / 2)


def _proficiency_bonus(level):
    for max_level, bonus in PROFICIENCY_TABLE:
        if level <= max_level:
            return bonus
    raise ValueError("invalid level")


def _valid_int_in_range(value, low, high):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


@csrf_exempt
def ability_modifier_view(request):
    try:
        body = _json_body(request)
        score = body["score"]
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not _valid_int_in_range(score, 1, 30):
        return JsonResponse({"error": "invalid request"}, status=400)

    return JsonResponse({"score": score, "modifier": _ability_modifier(score)})


@csrf_exempt
def proficiency_view(request):
    try:
        body = _json_body(request)
        level = body["level"]
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not _valid_int_in_range(level, 1, 20):
        return JsonResponse({"error": "invalid request"}, status=400)

    return JsonResponse({"level": level, "proficiency_bonus": _proficiency_bonus(level)})


@csrf_exempt
def derived_stats_view(request):
    try:
        body = _json_body(request)
        level = body["level"]
        abilities = body["abilities"]
        armor = body["armor"]
        str_score = abilities["str"]
        dex_score = abilities["dex"]
        con_score = abilities["con"]
        int_score = abilities["int"]
        wis_score = abilities["wis"]
        cha_score = abilities["cha"]
        armor_base = armor["base"]
        shield = armor["shield"]
        dex_cap = armor["dex_cap"]
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not _valid_int_in_range(level, 1, 20):
        return JsonResponse({"error": "invalid request"}, status=400)

    for score in (str_score, dex_score, con_score, int_score, wis_score, cha_score):
        if not _valid_int_in_range(score, 1, 30):
            return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(armor_base, int) or isinstance(armor_base, bool):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(shield, bool):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(dex_cap, int) or isinstance(dex_cap, bool):
        return JsonResponse({"error": "invalid request"}, status=400)

    modifiers = {
        "str": _ability_modifier(str_score),
        "dex": _ability_modifier(dex_score),
        "con": _ability_modifier(con_score),
        "int": _ability_modifier(int_score),
        "wis": _ability_modifier(wis_score),
        "cha": _ability_modifier(cha_score),
    }

    proficiency_bonus = _proficiency_bonus(level)
    hp_max = level * (6 + modifiers["con"])
    shield_bonus = 2 if shield else 0
    armor_class = armor_base + min(modifiers["dex"], dex_cap) + shield_bonus

    return JsonResponse({
        "level": level,
        "proficiency_bonus": proficiency_bonus,
        "hp_max": hp_max,
        "armor_class": armor_class,
        "modifiers": modifiers,
    })


COMBAT_SESSIONS = {}


def _combatant_view(combatant):
    return {"name": combatant["name"], "score": combatant["score"]}


def _conditions_view(session):
    return {
        name: [
            {"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]}
            for c in conditions
        ]
        for name, conditions in session["conditions"].items()
        if conditions or name in session["conditions_ever"]
    }


@csrf_exempt
def combat_sessions_view(request):
    try:
        body = _json_body(request)
        session_id = body["id"]
        combatants = body["combatants"]
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(session_id, str) or not session_id:
        return JsonResponse({"error": "invalid request"}, status=400)

    if session_id in COMBAT_SESSIONS:
        return JsonResponse({"error": "session already exists"}, status=400)

    try:
        scored = []
        for combatant in combatants:
            name = combatant["name"]
            dex = combatant["dex"]
            roll = combatant["roll"]
            score = roll + dex
            scored.append({"name": name, "dex": dex, "score": score})
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not scored:
        return JsonResponse({"error": "invalid request"}, status=400)

    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
    order = [{"name": c["name"], "score": c["score"]} for c in scored]

    session = {
        "id": session_id,
        "round": 1,
        "turn_index": 0,
        "order": order,
        "conditions": {c["name"]: [] for c in order},
        "conditions_ever": set(),
    }
    COMBAT_SESSIONS[session_id] = session

    return JsonResponse({
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": order[session["turn_index"]],
        "order": order,
    })


@csrf_exempt
def combat_conditions_view(request, session_id):
    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        return JsonResponse({"error": "session not found"}, status=404)

    try:
        body = _json_body(request)
        target = body["target"]
        condition = body["condition"]
        duration_rounds = body["duration_rounds"]
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if target not in session["conditions"]:
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(condition, str) or not condition:
        return JsonResponse({"error": "invalid request"}, status=400)

    if (
        not isinstance(duration_rounds, int)
        or isinstance(duration_rounds, bool)
        or duration_rounds <= 0
    ):
        return JsonResponse({"error": "invalid request"}, status=400)

    session["conditions"][target].append({
        "condition": condition,
        "remaining_rounds": duration_rounds,
    })
    session["conditions_ever"].add(target)

    return JsonResponse({
        "target": target,
        "conditions": [
            {"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]}
            for c in session["conditions"][target]
        ],
    })


@csrf_exempt
def combat_advance_view(request, session_id):
    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        return JsonResponse({"error": "session not found"}, status=404)

    order = session["order"]
    session["turn_index"] += 1
    if session["turn_index"] >= len(order):
        session["turn_index"] = 0
        session["round"] += 1

    active = order[session["turn_index"]]
    active_conditions = session["conditions"][active["name"]]
    remaining = []
    for c in active_conditions:
        c["remaining_rounds"] -= 1
        if c["remaining_rounds"] > 0:
            remaining.append(c)
    session["conditions"][active["name"]] = remaining

    return JsonResponse({
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": active,
        "conditions": _conditions_view(session),
    })


urlpatterns = [
    path("health", health),
    path("v1/dice/stats", dice_stats),
    path("v1/checks/ability", ability_check),
    path("v1/encounters/adjusted-xp", adjusted_xp),
    path("v1/initiative/order", initiative_order),
    path("v1/characters/ability-modifier", ability_modifier_view),
    path("v1/characters/proficiency", proficiency_view),
    path("v1/characters/derived-stats", derived_stats_view),
    path("v1/combat/sessions", combat_sessions_view),
    path("v1/combat/sessions/<str:session_id>/conditions", combat_conditions_view),
    path("v1/combat/sessions/<str:session_id>/advance", combat_advance_view),
]
