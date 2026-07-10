import json
import re

from django.http import JsonResponse
from django.urls import path


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

DICE_RE = re.compile(r"^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$")
ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")
COMBAT_SESSIONS = {}


def json_error(status=400):
    return JsonResponse({"error": "bad request"}, status=status)


def json_number(value):
    return int(value) if value == int(value) else value


def body_json(request):
    if request.method != "POST":
        return None
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def bounded_int(value, minimum, maximum):
    value = json_int(value)
    if value < minimum or value > maximum:
        raise ValueError
    return value


def json_int(value):
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError
    return value


def ability_modifier_for(score):
    return (bounded_int(score, 1, 30) - 10) // 2


def proficiency_bonus_for(level):
    level = bounded_int(level, 1, 20)
    return 2 + (level - 1) // 4


def health(request):
    return JsonResponse({"ok": True})


def dice_stats(request):
    payload = body_json(request)
    if payload is None:
        return json_error()

    expression = payload.get("expression")
    if not isinstance(expression, str):
        return json_error()

    match = DICE_RE.fullmatch(expression)
    if not match:
        return json_error()

    count = int(match.group(1))
    sides = int(match.group(2))
    if count <= 0 or sides <= 0:
        return json_error()

    modifier = int(match.group(4) or "0")
    if match.group(3) == "-":
        modifier = -modifier

    return JsonResponse(
        {
            "dice_count": count,
            "sides": sides,
            "modifier": modifier,
            "min": count + modifier,
            "max": count * sides + modifier,
            "average": json_number(count * (sides + 1) / 2 + modifier),
        }
    )


def ability_check(request):
    payload = body_json(request)
    if payload is None:
        return json_error()

    try:
        roll = int(payload["roll"])
        modifier = int(payload["modifier"])
        dc = int(payload["dc"])
    except (KeyError, TypeError, ValueError):
        return json_error()

    total = roll + modifier
    return JsonResponse({"total": total, "success": total >= dc, "margin": total - dc})


def monster_multiplier(monster_count):
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
    payload = body_json(request)
    if payload is None:
        return json_error()

    party = payload.get("party")
    monsters = payload.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        return json_error()

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    try:
        for member in party:
            member_thresholds = LEVEL_THRESHOLDS[int(member["level"])]
            for key in thresholds:
                thresholds[key] += member_thresholds[key]

        base_xp = 0
        monster_count = 0
        for monster in monsters:
            count = int(monster["count"])
            if count < 0:
                return json_error()
            base_xp += CR_XP[str(monster["cr"])] * count
            monster_count += count
    except (KeyError, TypeError, ValueError):
        return json_error()

    multiplier = monster_multiplier(monster_count) if monster_count > 0 else 0
    adjusted = base_xp * multiplier
    difficulty = "trivial"
    for name in ("easy", "medium", "hard", "deadly"):
        if adjusted >= thresholds[name]:
            difficulty = name

    return JsonResponse(
        {
            "base_xp": base_xp,
            "monster_count": monster_count,
            "multiplier": multiplier,
            "adjusted_xp": adjusted,
            "difficulty": difficulty,
            "thresholds": thresholds,
        }
    )


def initiative_order(request):
    payload = body_json(request)
    if payload is None:
        return json_error()

    combatants = payload.get("combatants")
    if not isinstance(combatants, list):
        return json_error()

    order = []
    try:
        for combatant in combatants:
            name = str(combatant["name"])
            dex = int(combatant["dex"])
            roll = int(combatant["roll"])
            order.append({"name": name, "dex": dex, "score": roll + dex})
    except (KeyError, TypeError, ValueError):
        return json_error()

    order.sort(key=lambda item: (-item["score"], -item["dex"], item["name"]))
    return JsonResponse(
        {"order": [{"name": item["name"], "score": item["score"]} for item in order]}
    )


def combatant_order(combatants):
    order = []
    for combatant in combatants:
        name = combatant["name"]
        if not isinstance(name, str):
            raise ValueError
        dex = json_int(combatant["dex"])
        roll = json_int(combatant["roll"])
        order.append({"name": name, "dex": dex, "score": roll + dex})

    if not order:
        raise ValueError

    order.sort(key=lambda item: (-item["score"], -item["dex"], item["name"]))
    return order


def public_order(order):
    return [{"name": item["name"], "score": item["score"]} for item in order]


def public_session(session):
    order = session["order"]
    active = order[session["turn_index"]]
    return {
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": {"name": active["name"], "score": active["score"]},
        "order": public_order(order),
    }


def public_conditions(session):
    conditions = {}
    for name, entries in session["conditions"].items():
        if entries or name in session["condition_targets"]:
            conditions[name] = [
                {
                    "condition": entry["condition"],
                    "remaining_rounds": entry["remaining_rounds"],
                }
                for entry in entries
            ]
    return conditions


def create_combat_session(request):
    payload = body_json(request)
    if payload is None:
        return json_error()

    session_id = payload.get("id")
    combatants = payload.get("combatants")
    if not isinstance(session_id, str) or not isinstance(combatants, list):
        return json_error()
    if session_id in COMBAT_SESSIONS:
        return json_error()

    try:
        order = combatant_order(combatants)
    except (KeyError, TypeError, ValueError):
        return json_error()

    session = {
        "id": session_id,
        "round": 1,
        "turn_index": 0,
        "order": order,
        "conditions": {combatant["name"]: [] for combatant in order},
        "condition_targets": set(),
    }
    COMBAT_SESSIONS[session_id] = session
    return JsonResponse(public_session(session))


def add_condition(request, session_id):
    payload = body_json(request)
    if payload is None:
        return json_error()

    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        return json_error(status=404)

    target = payload.get("target")
    condition = payload.get("condition")
    try:
        duration_rounds = json_int(payload["duration_rounds"])
    except (KeyError, ValueError):
        return json_error()

    if (
        not isinstance(target, str)
        or target not in session["conditions"]
        or not isinstance(condition, str)
        or duration_rounds <= 0
    ):
        return json_error()

    session["conditions"][target].append(
        {"condition": condition, "remaining_rounds": duration_rounds}
    )
    session["condition_targets"].add(target)
    return JsonResponse({"target": target, "conditions": session["conditions"][target]})


def advance_combat_session(request, session_id):
    if body_json(request) is None:
        return json_error()

    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        return json_error(status=404)

    session["turn_index"] += 1
    if session["turn_index"] >= len(session["order"]):
        session["turn_index"] = 0
        session["round"] += 1

    active = session["order"][session["turn_index"]]
    active_conditions = session["conditions"][active["name"]]
    remaining = []
    for condition in active_conditions:
        condition["remaining_rounds"] -= 1
        if condition["remaining_rounds"] > 0:
            remaining.append(condition)
    session["conditions"][active["name"]] = remaining

    return JsonResponse(
        {
            "id": session["id"],
            "round": session["round"],
            "turn_index": session["turn_index"],
            "active": {"name": active["name"], "score": active["score"]},
            "conditions": public_conditions(session),
        }
    )


def ability_modifier(request):
    payload = body_json(request)
    if payload is None:
        return json_error()

    try:
        score = bounded_int(payload["score"], 1, 30)
    except (KeyError, ValueError):
        return json_error()

    return JsonResponse({"score": score, "modifier": ability_modifier_for(score)})


def proficiency(request):
    payload = body_json(request)
    if payload is None:
        return json_error()

    try:
        level = bounded_int(payload["level"], 1, 20)
    except (KeyError, ValueError):
        return json_error()

    return JsonResponse(
        {"level": level, "proficiency_bonus": proficiency_bonus_for(level)}
    )


def derived_stats(request):
    payload = body_json(request)
    if payload is None:
        return json_error()

    abilities = payload.get("abilities")
    armor = payload.get("armor")
    if not isinstance(abilities, dict) or not isinstance(armor, dict):
        return json_error()

    try:
        level = bounded_int(payload["level"], 1, 20)
        modifiers = {key: ability_modifier_for(abilities[key]) for key in ABILITY_KEYS}
        armor_base = json_int(armor["base"])
        dex_cap = json_int(armor["dex_cap"])
        shield = armor["shield"]
        if not isinstance(shield, bool):
            return json_error()
    except (KeyError, ValueError):
        return json_error()

    proficiency_bonus = proficiency_bonus_for(level)
    hp_max = level * (6 + modifiers["con"])
    armor_class = armor_base + min(modifiers["dex"], dex_cap) + (2 if shield else 0)
    return JsonResponse(
        {
            "level": level,
            "proficiency_bonus": proficiency_bonus,
            "hp_max": hp_max,
            "armor_class": armor_class,
            "modifiers": modifiers,
        }
    )


urlpatterns = [
    path("health", health),
    path("v1/dice/stats", dice_stats),
    path("v1/checks/ability", ability_check),
    path("v1/encounters/adjusted-xp", adjusted_xp),
    path("v1/initiative/order", initiative_order),
    path("v1/characters/ability-modifier", ability_modifier),
    path("v1/characters/proficiency", proficiency),
    path("v1/characters/derived-stats", derived_stats),
    path("v1/combat/sessions", create_combat_session),
    path("v1/combat/sessions/<str:session_id>/conditions", add_condition),
    path("v1/combat/sessions/<str:session_id>/advance", advance_combat_session),
]
