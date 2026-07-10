import json
import re

from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseNotFound


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

def health(request):
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# POST /v1/dice/stats
# ---------------------------------------------------------------------------

_DICE_RE = re.compile(r"^([1-9]\d*)d([1-9]\d*)(?:([+-])(\d+))?$")


def dice_stats(request):
    if request.method != "POST":
        return HttpResponseBadRequest()
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return HttpResponseBadRequest()
    expression = body.get("expression")
    if not isinstance(expression, str):
        return HttpResponseBadRequest()
    m = _DICE_RE.match(expression.strip())
    if not m:
        return HttpResponseBadRequest()
    count = int(m.group(1))
    sides = int(m.group(2))
    if m.group(3):
        sign = -1 if m.group(3) == "-" else 1
        modifier = sign * int(m.group(4))
    else:
        modifier = 0
    if count <= 0 or sides <= 0:
        return HttpResponseBadRequest()
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


# ---------------------------------------------------------------------------
# POST /v1/checks/ability
# ---------------------------------------------------------------------------

def ability_check(request):
    if request.method != "POST":
        return HttpResponseBadRequest()
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return HttpResponseBadRequest()
    try:
        roll = int(body["roll"])
        modifier = int(body["modifier"])
        dc = int(body["dc"])
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest()
    total = roll + modifier
    return JsonResponse({
        "total": total,
        "success": total >= dc,
        "margin": total - dc,
    })


# ---------------------------------------------------------------------------
# POST /v1/encounters/adjusted-xp
# ---------------------------------------------------------------------------

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
    if monster_count <= 0:
        return 1
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
    if request.method != "POST":
        return HttpResponseBadRequest()
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return HttpResponseBadRequest()

    party = body.get("party")
    monsters = body.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        return HttpResponseBadRequest()

    base_xp = 0
    monster_count = 0
    for mon in monsters:
        try:
            cr = str(mon["cr"])
            count = int(mon["count"])
        except (KeyError, TypeError, ValueError):
            return HttpResponseBadRequest()
        if cr not in CR_XP or count <= 0:
            return HttpResponseBadRequest()
        base_xp += CR_XP[cr] * count
        monster_count += count

    multiplier = _multiplier(monster_count)
    adjusted = base_xp * multiplier

    # Party thresholds summed across members.
    easy = medium = hard = deadly = 0
    for member in party:
        try:
            level = int(member["level"])
        except (KeyError, TypeError, ValueError):
            return HttpResponseBadRequest()
        th = LEVEL_THRESHOLDS.get(level)
        if th is None:
            return HttpResponseBadRequest()
        easy += th["easy"]
        medium += th["medium"]
        hard += th["hard"]
        deadly += th["deadly"]

    thresholds = {"easy": easy, "medium": medium, "hard": hard, "deadly": deadly}

    if adjusted >= deadly:
        difficulty = "deadly"
    elif adjusted >= hard:
        difficulty = "hard"
    elif adjusted >= medium:
        difficulty = "medium"
    elif adjusted >= easy:
        difficulty = "easy"
    else:
        difficulty = "trivial"

    return JsonResponse({
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": multiplier,
        "adjusted_xp": adjusted,
        "difficulty": difficulty,
        "thresholds": thresholds,
    })


# ---------------------------------------------------------------------------
# POST /v1/initiative/order
# ---------------------------------------------------------------------------

def initiative_order(request):
    if request.method != "POST":
        return HttpResponseBadRequest()
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return HttpResponseBadRequest()
    combatants = body.get("combatants")
    if not isinstance(combatants, list):
        return HttpResponseBadRequest()

    scored = []
    for c in combatants:
        try:
            name = str(c["name"])
            dex = int(c["dex"])
            roll = int(c["roll"])
        except (KeyError, TypeError, ValueError):
            return HttpResponseBadRequest()
        scored.append({
            "name": name,
            "dex": dex,
            "score": roll + dex,
        })

    # Sort: score desc, dex desc, name asc.
    scored.sort(key=lambda x: (-x["score"], -x["dex"], x["name"]))

    return JsonResponse({
        "order": [{"name": c["name"], "score": c["score"]} for c in scored],
    })


# ---------------------------------------------------------------------------
# POST /v1/characters/ability-modifier
# ---------------------------------------------------------------------------

_ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def ability_modifier(request):
    if request.method != "POST":
        return HttpResponseBadRequest()
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return HttpResponseBadRequest()
    score = body.get("score")
    if not _is_int(score) or not (1 <= score <= 30):
        return HttpResponseBadRequest()
    modifier = (score - 10) // 2
    return JsonResponse({"score": score, "modifier": modifier})


# ---------------------------------------------------------------------------
# POST /v1/characters/proficiency
# ---------------------------------------------------------------------------

def proficiency(request):
    if request.method != "POST":
        return HttpResponseBadRequest()
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return HttpResponseBadRequest()
    level = body.get("level")
    if not _is_int(level) or not (1 <= level <= 20):
        return HttpResponseBadRequest()
    bonus = 2 + (level - 1) // 4
    return JsonResponse({"level": level, "proficiency_bonus": bonus})


# ---------------------------------------------------------------------------
# POST /v1/characters/derived-stats
# ---------------------------------------------------------------------------

def derived_stats(request):
    if request.method != "POST":
        return HttpResponseBadRequest()
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return HttpResponseBadRequest()
    level = body.get("level")
    if not _is_int(level) or not (1 <= level <= 20):
        return HttpResponseBadRequest()
    abilities = body.get("abilities")
    if not isinstance(abilities, dict):
        return HttpResponseBadRequest()
    modifiers = {}
    for key in _ABILITY_KEYS:
        score = abilities.get(key)
        if not _is_int(score) or not (1 <= score <= 30):
            return HttpResponseBadRequest()
        modifiers[key] = (score - 10) // 2
    armor = body.get("armor")
    if not isinstance(armor, dict):
        return HttpResponseBadRequest()
    base = armor.get("base")
    shield = armor.get("shield")
    dex_cap = armor.get("dex_cap")
    if not _is_int(base) or not isinstance(shield, bool) or not _is_int(dex_cap):
        return HttpResponseBadRequest()
    proficiency_bonus = 2 + (level - 1) // 4
    hp_max = level * (6 + modifiers["con"])
    armor_class = base + min(modifiers["dex"], dex_cap) + (2 if shield else 0)
    return JsonResponse({
        "level": level,
        "proficiency_bonus": proficiency_bonus,
        "hp_max": hp_max,
        "armor_class": armor_class,
        "modifiers": modifiers,
    })


# ---------------------------------------------------------------------------
# POST /v1/combat/sessions  -- create a stateful combat session
# ---------------------------------------------------------------------------

# In-memory store keyed by client-supplied session id. Lives for the process.
_COMBAT_SESSIONS = {}


def _is_pos_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def combat_create_session(request):
    if request.method != "POST":
        return HttpResponseBadRequest()
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return HttpResponseBadRequest()
    if not isinstance(body, dict):
        return HttpResponseBadRequest()
    sid = body.get("id")
    if not isinstance(sid, str) or not sid:
        return HttpResponseBadRequest()
    combatants = body.get("combatants")
    if not isinstance(combatants, list) or len(combatants) == 0:
        return HttpResponseBadRequest()
    scored = []
    for c in combatants:
        if not isinstance(c, dict):
            return HttpResponseBadRequest()
        try:
            name = str(c["name"])
            dex = int(c["dex"])
            roll = int(c["roll"])
        except (KeyError, TypeError, ValueError):
            return HttpResponseBadRequest()
        scored.append({"name": name, "dex": dex, "score": roll + dex})
    # Sort: score desc, dex desc, name asc.
    scored.sort(key=lambda x: (-x["score"], -x["dex"], x["name"]))
    order = [{"name": c["name"], "score": c["score"]} for c in scored]
    _COMBAT_SESSIONS[sid] = {
        "id": sid,
        "order": order,
        "round": 1,
        "turn_index": 0,
        "conditions": {},
    }
    return JsonResponse({
        "id": sid,
        "round": 1,
        "turn_index": 0,
        "active": dict(order[0]),
        "order": [dict(c) for c in order],
    })


# ---------------------------------------------------------------------------
# POST /v1/combat/sessions/{id}/conditions  -- attach a condition
# ---------------------------------------------------------------------------

def combat_add_condition(request, sid):
    if request.method != "POST":
        return HttpResponseBadRequest()
    session = _COMBAT_SESSIONS.get(sid)
    if session is None:
        return HttpResponseNotFound()
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return HttpResponseBadRequest()
    if not isinstance(body, dict):
        return HttpResponseBadRequest()
    target = body.get("target")
    condition = body.get("condition")
    duration = body.get("duration_rounds")
    if not isinstance(target, str) or not target:
        return HttpResponseBadRequest()
    if not isinstance(condition, str) or not condition:
        return HttpResponseBadRequest()
    if not _is_pos_int(duration):
        return HttpResponseBadRequest()
    names = {c["name"] for c in session["order"]}
    if target not in names:
        return HttpResponseBadRequest()
    conds = session["conditions"].setdefault(target, [])
    conds.append({"condition": condition, "remaining_rounds": duration})
    return JsonResponse({
        "target": target,
        "conditions": [dict(c) for c in conds],
    })


# ---------------------------------------------------------------------------
# POST /v1/combat/sessions/{id}/advance  -- advance to the next turn
# ---------------------------------------------------------------------------

def combat_advance(request, sid):
    if request.method != "POST":
        return HttpResponseBadRequest()
    session = _COMBAT_SESSIONS.get(sid)
    if session is None:
        return HttpResponseNotFound()
    order = session["order"]
    n = len(order)
    next_index = session["turn_index"] + 1
    if next_index >= n:
        next_index = 0
        session["round"] += 1
    session["turn_index"] = next_index
    active = order[next_index]
    active_name = active["name"]
    # At the start of this combatant's turn, tick down their conditions.
    had_conditions = active_name in session["conditions"]
    conds = session["conditions"].get(active_name, [])
    for c in conds:
        c["remaining_rounds"] -= 1
    conds = [c for c in conds if c["remaining_rounds"] > 0]
    if had_conditions:
        # Keep the combatant's entry even once all conditions have expired
        # so callers can still see the target with an empty condition list.
        # Combatants who never had conditions are left out of the map.
        session["conditions"][active_name] = conds
    return JsonResponse({
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": dict(active),
        "conditions": {
            name: [dict(c) for c in clist]
            for name, clist in session["conditions"].items()
        },
    })
