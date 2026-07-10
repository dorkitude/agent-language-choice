import json
import re

from django.http import JsonResponse
from django.urls import path
from django.views.decorators.csrf import csrf_exempt

DICE_RE = re.compile(r"^(\d+)d(\d+)(?:([+-])(\d+))?$")

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

DIFFICULTY_ORDER = ["easy", "medium", "hard", "deadly"]


def _num(value):
    """Return an int when the value is whole, otherwise a float."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _parse_body(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def health(request):
    return JsonResponse({"ok": True})


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
    data = _parse_body(request)
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
    if count <= 0 or sides <= 0:
        return JsonResponse({"error": "invalid expression"}, status=400)

    modifier = 0
    if match.group(3):
        modifier = int(match.group(4))
        if match.group(3) == "-":
            modifier = -modifier

    minimum = count * 1 + modifier
    maximum = count * sides + modifier
    average = (minimum + maximum) / 2

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
    data = _parse_body(request)
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


@csrf_exempt
def adjusted_xp(request):
    data = _parse_body(request)
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
            return JsonResponse({"error": "invalid request"}, status=400)
        cr = str(monster.get("cr"))
        count = monster.get("count", 1)
        if cr not in CR_XP or not isinstance(count, int) or isinstance(count, bool):
            return JsonResponse({"error": "invalid request"}, status=400)
        base_xp += CR_XP[cr] * count
        monster_count += count

    multiplier = _multiplier(monster_count)
    adjusted = base_xp * multiplier

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            return JsonResponse({"error": "invalid request"}, status=400)
        level = member.get("level")
        if level not in LEVEL_THRESHOLDS:
            return JsonResponse({"error": "invalid request"}, status=400)
        for key, value in LEVEL_THRESHOLDS[level].items():
            thresholds[key] += value

    difficulty = "trivial"
    for name in DIFFICULTY_ORDER:
        if adjusted >= thresholds[name]:
            difficulty = name

    return JsonResponse(
        {
            "base_xp": _num(base_xp),
            "monster_count": monster_count,
            "multiplier": _num(multiplier),
            "adjusted_xp": _num(adjusted),
            "difficulty": difficulty,
            "thresholds": thresholds,
        }
    )


@csrf_exempt
def initiative_order(request):
    data = _parse_body(request)
    if not isinstance(data, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    combatants = data.get("combatants")
    if not isinstance(combatants, list):
        return JsonResponse({"error": "invalid request"}, status=400)

    entries = []
    for combatant in combatants:
        if not isinstance(combatant, dict):
            return JsonResponse({"error": "invalid request"}, status=400)
        try:
            name = str(combatant["name"])
            dex = int(combatant["dex"])
            roll = int(combatant["roll"])
        except (KeyError, TypeError, ValueError):
            return JsonResponse({"error": "invalid request"}, status=400)
        entries.append({"name": name, "dex": dex, "score": roll + dex})

    entries.sort(key=lambda e: (-e["score"], -e["dex"], e["name"]))

    order = [{"name": e["name"], "score": e["score"]} for e in entries]
    return JsonResponse({"order": order})


def _ability_modifier(score):
    return (score - 10) // 2


def _proficiency_bonus(level):
    return (level - 1) // 4 + 2


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


ABILITY_KEYS = ["str", "dex", "con", "int", "wis", "cha"]


@csrf_exempt
def ability_modifier(request):
    data = _parse_body(request)
    if not isinstance(data, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    score = data.get("score")
    if not _is_int(score) or score < 1 or score > 30:
        return JsonResponse({"error": "invalid request"}, status=400)
    return JsonResponse({"score": score, "modifier": _ability_modifier(score)})


@csrf_exempt
def proficiency(request):
    data = _parse_body(request)
    if not isinstance(data, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    level = data.get("level")
    if not _is_int(level) or level < 1 or level > 20:
        return JsonResponse({"error": "invalid request"}, status=400)
    return JsonResponse({"level": level, "proficiency_bonus": _proficiency_bonus(level)})


@csrf_exempt
def derived_stats(request):
    data = _parse_body(request)
    if not isinstance(data, dict):
        return JsonResponse({"error": "invalid request"}, status=400)

    level = data.get("level")
    if not _is_int(level) or level < 1 or level > 20:
        return JsonResponse({"error": "invalid request"}, status=400)

    abilities = data.get("abilities")
    if not isinstance(abilities, dict):
        return JsonResponse({"error": "invalid request"}, status=400)

    modifiers = {}
    for key in ABILITY_KEYS:
        score = abilities.get(key)
        if not _is_int(score) or score < 1 or score > 30:
            return JsonResponse({"error": "invalid request"}, status=400)
        modifiers[key] = _ability_modifier(score)

    armor = data.get("armor")
    if not isinstance(armor, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    base = armor.get("base")
    dex_cap = armor.get("dex_cap")
    shield = armor.get("shield")
    if not _is_int(base) or not _is_int(dex_cap) or not isinstance(shield, bool):
        return JsonResponse({"error": "invalid request"}, status=400)

    proficiency_bonus = _proficiency_bonus(level)
    hp_max = level * (6 + modifiers["con"])
    shield_bonus = 2 if shield else 0
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus

    return JsonResponse(
        {
            "level": level,
            "proficiency_bonus": proficiency_bonus,
            "hp_max": hp_max,
            "armor_class": armor_class,
            "modifiers": modifiers,
        }
    )


COMBAT_SESSIONS = {}


def _combat_entry(entry):
    return {"name": entry["name"], "score": entry["score"]}


def _conditions_view(session):
    seen = session["conditioned"]
    return {
        name: conditions
        for name, conditions in session["conditions"].items()
        if name in seen
    }


@csrf_exempt
def combat_sessions(request):
    data = _parse_body(request)
    if not isinstance(data, dict):
        return JsonResponse({"error": "invalid request"}, status=400)

    session_id = data.get("id")
    if not isinstance(session_id, str) or not session_id:
        return JsonResponse({"error": "invalid request"}, status=400)
    if session_id in COMBAT_SESSIONS:
        return JsonResponse({"error": "session already exists"}, status=400)

    combatants = data.get("combatants")
    if not isinstance(combatants, list) or not combatants:
        return JsonResponse({"error": "invalid request"}, status=400)

    entries = []
    names = set()
    for combatant in combatants:
        if not isinstance(combatant, dict):
            return JsonResponse({"error": "invalid request"}, status=400)
        try:
            name = str(combatant["name"])
            dex = int(combatant["dex"])
            roll = int(combatant["roll"])
        except (KeyError, TypeError, ValueError):
            return JsonResponse({"error": "invalid request"}, status=400)
        if name in names:
            return JsonResponse({"error": "invalid request"}, status=400)
        names.add(name)
        entries.append({"name": name, "dex": dex, "score": roll + dex})

    entries.sort(key=lambda e: (-e["score"], -e["dex"], e["name"]))

    session = {
        "id": session_id,
        "round": 1,
        "turn_index": 0,
        "order": entries,
        "conditions": {name: [] for name in names},
        "conditioned": set(),
    }
    COMBAT_SESSIONS[session_id] = session

    return JsonResponse(
        {
            "id": session_id,
            "round": session["round"],
            "turn_index": session["turn_index"],
            "active": _combat_entry(entries[session["turn_index"]]),
            "order": [_combat_entry(e) for e in entries],
        }
    )


@csrf_exempt
def combat_conditions(request, session_id):
    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        return JsonResponse({"error": "unknown session"}, status=404)

    data = _parse_body(request)
    if not isinstance(data, dict):
        return JsonResponse({"error": "invalid request"}, status=400)

    target = data.get("target")
    condition = data.get("condition")
    duration = data.get("duration_rounds")
    if not isinstance(target, str) or target not in session["conditions"]:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(condition, str) or not condition:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not _is_int(duration) or duration <= 0:
        return JsonResponse({"error": "invalid request"}, status=400)

    session["conditions"][target].append(
        {"condition": condition, "remaining_rounds": duration}
    )
    session["conditioned"].add(target)

    return JsonResponse(
        {
            "target": target,
            "conditions": session["conditions"][target],
        }
    )


@csrf_exempt
def combat_advance(request, session_id):
    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        return JsonResponse({"error": "unknown session"}, status=404)

    order = session["order"]
    session["turn_index"] += 1
    if session["turn_index"] >= len(order):
        session["turn_index"] = 0
        session["round"] += 1

    active_name = order[session["turn_index"]]["name"]
    remaining = []
    for entry in session["conditions"][active_name]:
        entry["remaining_rounds"] -= 1
        if entry["remaining_rounds"] > 0:
            remaining.append(entry)
    session["conditions"][active_name] = remaining

    return JsonResponse(
        {
            "id": session["id"],
            "round": session["round"],
            "turn_index": session["turn_index"],
            "active": _combat_entry(order[session["turn_index"]]),
            "conditions": _conditions_view(session),
        }
    )


urlpatterns = [
    path("health", health),
    path("v1/combat/sessions", combat_sessions),
    path("v1/combat/sessions/<str:session_id>/conditions", combat_conditions),
    path("v1/combat/sessions/<str:session_id>/advance", combat_advance),
    path("v1/dice/stats", dice_stats),
    path("v1/checks/ability", ability_check),
    path("v1/encounters/adjusted-xp", adjusted_xp),
    path("v1/initiative/order", initiative_order),
    path("v1/characters/ability-modifier", ability_modifier),
    path("v1/characters/proficiency", proficiency),
    path("v1/characters/derived-stats", derived_stats),
]
