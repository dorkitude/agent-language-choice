import json
import re
import threading

from django.http import JsonResponse

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

DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")


def _require_post(handler):
    def wrapper(request, *args, **kwargs):
        if request.method != "POST":
            return JsonResponse({"error": "method not allowed"}, status=405)
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "invalid json"}, status=400)
        return handler(data, *args, **kwargs)
    return wrapper


ABILITIES = ("str", "dex", "con", "int", "wis", "cha")

COMBAT_SESSIONS = {}
COMBAT_LOCK = threading.Lock()


def _get_int(data, key, lo=None, hi=None):
    val = data[key]
    if not isinstance(val, int) or isinstance(val, bool):
        raise ValueError
    if lo is not None and val < lo:
        raise ValueError
    if hi is not None and val > hi:
        raise ValueError
    return val


def _ability_modifier(score):
    return (score - 10) // 2


def _proficiency_bonus(level):
    if level <= 4:
        return 2
    if level <= 8:
        return 3
    if level <= 12:
        return 4
    if level <= 16:
        return 5
    return 6


def health(request):
    return JsonResponse({"ok": True})


@_require_post
def dice_stats(data):
    expression = data.get("expression", "")
    match = DICE_RE.match(expression)
    if not match:
        return JsonResponse({"error": "invalid expression"}, status=400)
    count = int(match.group(1))
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0
    if count <= 0 or sides <= 0:
        return JsonResponse({"error": "invalid expression"}, status=400)
    min_val = count + modifier
    max_val = count * sides + modifier
    average = (min_val + max_val) / 2
    if average == int(average):
        average = int(average)
    return JsonResponse({
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": min_val,
        "max": max_val,
        "average": average,
    })


@_require_post
def ability_check(data):
    try:
        roll = int(data["roll"])
        modifier = int(data["modifier"])
        dc = int(data["dc"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "invalid input"}, status=400)
    total = roll + modifier
    return JsonResponse({
        "total": total,
        "success": total >= dc,
        "margin": total - dc,
    })


@_require_post
def adjusted_xp(data):
    try:
        party = data["party"]
        monsters = data["monsters"]
    except KeyError:
        return JsonResponse({"error": "invalid input"}, status=400)

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = member.get("level")
        if level not in LEVEL_THRESHOLDS:
            return JsonResponse({"error": "unsupported level"}, status=400)
        for k, v in LEVEL_THRESHOLDS[level].items():
            thresholds[k] += v

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        cr = monster.get("cr")
        count = monster.get("count")
        if cr not in XP_TABLE or not isinstance(count, int) or count <= 0:
            return JsonResponse({"error": "invalid monster"}, status=400)
        base_xp += XP_TABLE[cr] * count
        monster_count += count

    if monster_count == 0:
        return JsonResponse({"error": "no monsters"}, status=400)

    if monster_count == 1:
        multiplier = 1
    elif monster_count == 2:
        multiplier = 1.5
    elif monster_count <= 6:
        multiplier = 2
    elif monster_count <= 10:
        multiplier = 2.5
    elif monster_count <= 14:
        multiplier = 3
    else:
        multiplier = 4

    adjusted_xp_val = base_xp * multiplier
    if adjusted_xp_val == int(adjusted_xp_val):
        adjusted_xp_val = int(adjusted_xp_val)
    if multiplier == int(multiplier):
        multiplier = int(multiplier)

    difficulty = "trivial"
    if adjusted_xp_val >= thresholds["deadly"]:
        difficulty = "deadly"
    elif adjusted_xp_val >= thresholds["hard"]:
        difficulty = "hard"
    elif adjusted_xp_val >= thresholds["medium"]:
        difficulty = "medium"
    elif adjusted_xp_val >= thresholds["easy"]:
        difficulty = "easy"

    return JsonResponse({
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": multiplier,
        "adjusted_xp": adjusted_xp_val,
        "difficulty": difficulty,
        "thresholds": thresholds,
    })


@_require_post
def initiative_order(data):
    try:
        combatants = data["combatants"]
    except KeyError:
        return JsonResponse({"error": "invalid input"}, status=400)

    entries = []
    for c in combatants:
        try:
            name = c["name"]
            dex = c["dex"]
            roll = c["roll"]
            entries.append((name, dex, roll + dex))
        except (KeyError, TypeError):
            return JsonResponse({"error": "invalid combatant"}, status=400)

    entries.sort(key=lambda x: (-x[2], -x[1], x[0]))

    return JsonResponse({
        "order": [{"name": name, "score": score} for name, _, score in entries],
    })


@_require_post
def ability_modifier(data):
    try:
        score = _get_int(data, "score", 1, 30)
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "invalid score"}, status=400)
    return JsonResponse({
        "score": score,
        "modifier": _ability_modifier(score),
    })


@_require_post
def proficiency(data):
    try:
        level = _get_int(data, "level", 1, 20)
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "invalid level"}, status=400)
    return JsonResponse({
        "level": level,
        "proficiency_bonus": _proficiency_bonus(level),
    })


def _combat_response(session):
    active = session["order"][session["turn_index"]]
    conditions = {
        name: [
            {"condition": cond["condition"], "remaining_rounds": cond["remaining_rounds"]}
            for cond in conds
        ]
        for name, conds in session["conditions"].items()
    }
    return {
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": {"name": active["name"], "score": active["score"]},
        "order": [
            {"name": c["name"], "score": c["score"]}
            for c in session["order"]
        ],
        "conditions": conditions,
    }


@_require_post
def derived_stats(data):
    try:
        level = _get_int(data, "level", 1, 20)
        abilities = data["abilities"]
        armor = data["armor"]
        if not isinstance(abilities, dict) or not isinstance(armor, dict):
            raise ValueError

        modifiers = {}
        for ability in ABILITIES:
            score = _get_int(abilities, ability, 1, 30)
            modifiers[ability] = _ability_modifier(score)

        base = _get_int(armor, "base")
        dex_cap = _get_int(armor, "dex_cap")
        shield = armor.get("shield", False)
        if not isinstance(shield, bool):
            raise ValueError
        shield_bonus = 2 if shield else 0

        con_mod = modifiers["con"]
        dex_mod = modifiers["dex"]
        hp_max = level * (6 + con_mod)
        armor_class = base + min(dex_mod, dex_cap) + shield_bonus
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "invalid input"}, status=400)

    return JsonResponse({
        "level": level,
        "proficiency_bonus": _proficiency_bonus(level),
        "hp_max": hp_max,
        "armor_class": armor_class,
        "modifiers": modifiers,
    })


@_require_post
def create_combat_session(data):
    try:
        session_id = data["id"]
        combatants = data["combatants"]
        if not isinstance(session_id, str) or not isinstance(combatants, list) or not combatants:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "invalid input"}, status=400)

    entries = []
    for c in combatants:
        try:
            name = c["name"]
            dex = _get_int(c, "dex")
            roll = _get_int(c, "roll")
            if not isinstance(name, str) or not isinstance(dex, int) or not isinstance(roll, int):
                raise ValueError
            entries.append({"name": name, "dex": dex, "score": roll + dex})
        except (KeyError, TypeError, ValueError):
            return JsonResponse({"error": "invalid combatant"}, status=400)

    entries.sort(key=lambda x: (-x["score"], -x["dex"], x["name"]))

    with COMBAT_LOCK:
        if session_id in COMBAT_SESSIONS:
            return JsonResponse({"error": "session already exists"}, status=400)
        COMBAT_SESSIONS[session_id] = {
            "id": session_id,
            "round": 1,
            "turn_index": 0,
            "order": entries,
            "conditions": {entry["name"]: [] for entry in entries},
        }
        session = COMBAT_SESSIONS[session_id]
        return JsonResponse({
            "id": session["id"],
            "round": session["round"],
            "turn_index": session["turn_index"],
            "active": {"name": session["order"][0]["name"], "score": session["order"][0]["score"]},
            "order": [{"name": c["name"], "score": c["score"]} for c in session["order"]],
        })


@_require_post
def add_condition(data, session_id):
    with COMBAT_LOCK:
        session = COMBAT_SESSIONS.get(session_id)
        if session is None:
            return JsonResponse({"error": "session not found"}, status=404)

        try:
            target = data["target"]
            condition = data["condition"]
            duration = _get_int(data, "duration_rounds", 1)
            if target not in session["conditions"] or not isinstance(condition, str):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return JsonResponse({"error": "invalid input"}, status=400)

        session["conditions"][target].append({
            "condition": condition,
            "remaining_rounds": duration,
        })

        return JsonResponse({
            "target": target,
            "conditions": [
                {"condition": cond["condition"], "remaining_rounds": cond["remaining_rounds"]}
                for cond in session["conditions"][target]
            ],
        })


def advance_turn(request, session_id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    with COMBAT_LOCK:
        session = COMBAT_SESSIONS.get(session_id)
        if session is None:
            return JsonResponse({"error": "session not found"}, status=404)

        turn_index = session["turn_index"] + 1
        round_num = session["round"]
        if turn_index >= len(session["order"]):
            turn_index = 0
            round_num += 1

        session["turn_index"] = turn_index
        session["round"] = round_num

        active_name = session["order"][turn_index]["name"]
        active_conditions = session["conditions"].get(active_name, [])
        updated = []
        for cond in active_conditions:
            cond["remaining_rounds"] -= 1
            if cond["remaining_rounds"] > 0:
                updated.append(cond)
        session["conditions"][active_name] = updated

        return JsonResponse(_combat_response(session))
