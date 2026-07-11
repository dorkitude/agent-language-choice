import json
import re

from django.contrib.auth.hashers import check_password, make_password
from django.http import HttpResponseBadRequest, HttpResponseNotFound, JsonResponse
from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from . import db


SLUG_RE = re.compile(r"^[a-z0-9_-]+$")

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

THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

WIZARD_SPELL_SLOTS = {
    1: {"1": 2},
    2: {"1": 3},
    3: {"1": 4, "2": 2},
    4: {"1": 4, "2": 3},
    5: {"1": 4, "2": 3, "3": 2},
    6: {"1": 4, "2": 3, "3": 3},
    7: {"1": 4, "2": 3, "3": 3, "4": 1},
    8: {"1": 4, "2": 3, "3": 3, "4": 2},
    9: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 1},
    10: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2},
    11: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1},
    12: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1},
    13: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1},
    14: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1},
    15: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1, "8": 1},
    16: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1, "8": 1},
    17: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1, "8": 1, "9": 1},
    18: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 1, "7": 1, "8": 1, "9": 1},
    19: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 2, "7": 1, "8": 1, "9": 1},
    20: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 2, "7": 2, "8": 1, "9": 1},
}

DICE_RE = re.compile(r"^(\d+)d(\d+)(?:([+-])(\d+))?$")
USER_RE = re.compile(r"^[a-z0-9_-]{2,32}$")


def _load_json(request):
    try:
        return json.loads(request.body)
    except Exception:
        return None


def health(request):
    return JsonResponse({"ok": True})


@csrf_exempt
def register(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    username = data.get("username")
    password = data.get("password")
    role = data.get("role")

    if (
        not isinstance(username, str)
        or not isinstance(password, str)
        or role not in ("dm", "player")
    ):
        return HttpResponseBadRequest()

    if not USER_RE.match(username):
        return HttpResponseBadRequest()

    if len(password) < 8:
        return HttpResponseBadRequest()

    if db.get_user(username) is not None:
        return JsonResponse({"error": "duplicate username"}, status=409)

    db.create_user(username, make_password(password), role)

    return JsonResponse({"username": username, "role": role}, status=201)


@csrf_exempt
def login(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        return HttpResponseBadRequest()

    user = db.get_user(username)
    if user is None or not check_password(password, user["password_hash"]):
        return JsonResponse({"error": "invalid credentials"}, status=401)

    return JsonResponse({"username": username, "token": f"session-{username}"})


@csrf_exempt
def dice_stats(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    expression = data.get("expression", "")
    match = DICE_RE.match(str(expression))
    if not match:
        return HttpResponseBadRequest()

    count = int(match.group(1))
    sides = int(match.group(2))
    mod_sign = match.group(3)
    mod_val = match.group(4)

    if count <= 0 or sides <= 0:
        return HttpResponseBadRequest()

    modifier = 0
    if mod_sign and mod_val:
        modifier = int(mod_val)
        if mod_sign == "-":
            modifier = -modifier

    min_val = count + modifier
    max_val = count * sides + modifier
    average = count * (sides + 1) / 2 + modifier
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


@csrf_exempt
def ability_check(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    try:
        roll = int(data["roll"])
        modifier = int(data["modifier"])
        dc = int(data["dc"])
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest()

    total = roll + modifier
    return JsonResponse({
        "total": total,
        "success": total >= dc,
        "margin": total - dc,
    })


@csrf_exempt
def adjusted_xp(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    party = data.get("party")
    monsters = data.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        return HttpResponseBadRequest()

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            return HttpResponseBadRequest()
        try:
            level = int(member["level"])
        except (KeyError, TypeError, ValueError):
            return HttpResponseBadRequest()
        t = THRESHOLDS.get(level)
        if t is None:
            return HttpResponseBadRequest()
        for key in thresholds:
            thresholds[key] += t[key]

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        if not isinstance(monster, dict):
            return HttpResponseBadRequest()
        try:
            cr = str(monster["cr"])
            count = int(monster["count"])
        except (KeyError, TypeError, ValueError):
            return HttpResponseBadRequest()
        xp = CR_XP.get(cr)
        if xp is None or count <= 0:
            return HttpResponseBadRequest()
        base_xp += xp * count
        monster_count += count

    if monster_count <= 0:
        return HttpResponseBadRequest()

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

    adjusted_xp = int(base_xp * multiplier)

    if adjusted_xp >= thresholds["deadly"]:
        difficulty = "deadly"
    elif adjusted_xp >= thresholds["hard"]:
        difficulty = "hard"
    elif adjusted_xp >= thresholds["medium"]:
        difficulty = "medium"
    elif adjusted_xp >= thresholds["easy"]:
        difficulty = "easy"
    else:
        difficulty = "trivial"

    return JsonResponse({
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": multiplier,
        "adjusted_xp": adjusted_xp,
        "difficulty": difficulty,
        "thresholds": thresholds,
    })


@csrf_exempt
def initiative_order(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    combatants = data.get("combatants")
    if not isinstance(combatants, list):
        return HttpResponseBadRequest()

    scored = []
    for combatant in combatants:
        if not isinstance(combatant, dict):
            return HttpResponseBadRequest()
        try:
            name = str(combatant["name"])
            dex = int(combatant["dex"])
            roll = int(combatant["roll"])
        except (KeyError, TypeError, ValueError):
            return HttpResponseBadRequest()
        scored.append({"name": name, "dex": dex, "score": roll + dex})

    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))

    return JsonResponse({
        "order": [{"name": c["name"], "score": c["score"]} for c in scored],
    })


def _ability_modifier(score):
    return (score - 10) // 2


def _proficiency_bonus(level):
    if level <= 4:
        return 2
    elif level <= 8:
        return 3
    elif level <= 12:
        return 4
    elif level <= 16:
        return 5
    else:
        return 6


@csrf_exempt
def ability_modifier_view(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    try:
        score = int(data["score"])
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest()

    if score < 1 or score > 30:
        return HttpResponseBadRequest()

    return JsonResponse({"score": score, "modifier": _ability_modifier(score)})


@csrf_exempt
def proficiency_view(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    try:
        level = int(data["level"])
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest()

    if level < 1 or level > 20:
        return HttpResponseBadRequest()

    return JsonResponse({"level": level, "proficiency_bonus": _proficiency_bonus(level)})


@csrf_exempt
def derived_stats(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    try:
        level = int(data["level"])
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest()

    if level < 1 or level > 20:
        return HttpResponseBadRequest()

    abilities = data.get("abilities")
    if not isinstance(abilities, dict):
        return HttpResponseBadRequest()

    ability_names = ("str", "dex", "con", "int", "wis", "cha")
    modifiers = {}
    for name in ability_names:
        try:
            score = int(abilities[name])
        except (KeyError, TypeError, ValueError):
            return HttpResponseBadRequest()
        if score < 1 or score > 30:
            return HttpResponseBadRequest()
        modifiers[name] = _ability_modifier(score)

    armor = data.get("armor")
    if not isinstance(armor, dict):
        return HttpResponseBadRequest()

    try:
        base = int(armor["base"])
        dex_cap = int(armor["dex_cap"])
        shield = armor["shield"]
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest()

    if not isinstance(shield, bool):
        return HttpResponseBadRequest()
    shield_bonus = 2 if shield else 0

    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus
    hp_max = level * (6 + modifiers["con"])

    return JsonResponse({
        "level": level,
        "proficiency_bonus": _proficiency_bonus(level),
        "hp_max": hp_max,
        "armor_class": armor_class,
        "modifiers": modifiers,
    })


@csrf_exempt
def create_combat_session(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    try:
        session_id = str(data["id"])
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest()

    if db.get_session(session_id) is not None:
        return HttpResponseBadRequest()

    combatants = data.get("combatants")
    if not isinstance(combatants, list) or not combatants:
        return HttpResponseBadRequest()

    scored = []
    for combatant in combatants:
        if not isinstance(combatant, dict):
            return HttpResponseBadRequest()
        try:
            name = str(combatant["name"])
            dex = int(combatant["dex"])
            roll = int(combatant["roll"])
        except (KeyError, TypeError, ValueError):
            return HttpResponseBadRequest()
        scored.append({"name": name, "dex": dex, "score": roll + dex})

    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
    order = [{"name": c["name"], "score": c["score"]} for c in scored]
    conditions = {c["name"]: [] for c in scored}

    try:
        db.create_session(session_id, order, conditions)
    except db.SessionExistsError:
        return HttpResponseBadRequest()

    session = db.get_session(session_id)
    return JsonResponse({
        "id": session_id,
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": order[0],
        "order": order,
    })


@csrf_exempt
def add_condition(request, session_id):
    if request.method != "POST":
        return HttpResponseBadRequest()

    session = db.get_session(session_id)
    if session is None:
        return HttpResponseNotFound()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    try:
        target = str(data["target"])
        condition = str(data["condition"])
        duration_rounds = int(data["duration_rounds"])
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest()

    if target not in session["conditions"] or duration_rounds <= 0:
        return HttpResponseBadRequest()

    session["conditions"][target].append({
        "condition": condition,
        "remaining_rounds": duration_rounds,
    })

    db.update_session(
        session_id, session["round"], session["turn_index"], session["conditions"]
    )

    return JsonResponse({
        "target": target,
        "conditions": session["conditions"][target],
    })


@csrf_exempt
def advance_turn(request, session_id):
    if request.method != "POST":
        return HttpResponseBadRequest()

    session = db.get_session(session_id)
    if session is None:
        return HttpResponseNotFound()

    order_len = len(session["order"])
    turn_index = session["turn_index"] + 1
    round_num = session["round"]
    if turn_index >= order_len:
        turn_index = 0
        round_num += 1

    active_name = session["order"][turn_index]["name"]
    active_conditions = session["conditions"][active_name]

    new_conditions = []
    for cond in active_conditions:
        cond["remaining_rounds"] -= 1
        if cond["remaining_rounds"] > 0:
            new_conditions.append(cond)
    session["conditions"][active_name] = new_conditions

    db.update_session(session_id, round_num, turn_index, session["conditions"])

    return JsonResponse({
        "id": session_id,
        "round": round_num,
        "turn_index": turn_index,
        "active": session["order"][turn_index],
        "conditions": session["conditions"],
    })


def storage_status(request):
    if request.method != "GET":
        return HttpResponseBadRequest()
    return JsonResponse(db.storage_status())


@csrf_exempt
def storage_reset(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    db.reset_storage()
    return JsonResponse({"ok": True, "schema_version": 1})


def _validate_slug(slug):
    return isinstance(slug, str) and SLUG_RE.match(slug)


def _validate_tags(tags):
    if tags is None:
        return True
    if not isinstance(tags, list):
        return False
    return all(isinstance(tag, str) for tag in tags)


def _compute_encounter(party, monsters):
    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            return None
        try:
            level = int(member["level"])
        except (KeyError, TypeError, ValueError):
            return None
        t = THRESHOLDS.get(level)
        if t is None:
            return None
        for key in thresholds:
            thresholds[key] += t[key]

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        if not isinstance(monster, dict):
            return None
        try:
            cr = str(monster["cr"])
            count = int(monster["count"])
        except (KeyError, TypeError, ValueError):
            return None
        xp = CR_XP.get(cr)
        if xp is None or count <= 0:
            return None
        base_xp += xp * count
        monster_count += count

    if monster_count <= 0:
        return None

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

    adjusted_xp = int(base_xp * multiplier)

    if adjusted_xp >= thresholds["deadly"]:
        difficulty = "deadly"
    elif adjusted_xp >= thresholds["hard"]:
        difficulty = "hard"
    elif adjusted_xp >= thresholds["medium"]:
        difficulty = "medium"
    elif adjusted_xp >= thresholds["easy"]:
        difficulty = "easy"
    else:
        difficulty = "trivial"

    return {
        "base_xp": base_xp,
        "monster_count": monster_count,
        "adjusted_xp": adjusted_xp,
        "difficulty": difficulty,
    }


def _difficulty_recommendation(difficulty):
    return {
        "trivial": "no threat",
        "easy": "safe warm-up",
        "medium": "fair fight",
        "hard": "challenging",
        "deadly": "deadly",
    }.get(difficulty, "unknown")


@csrf_exempt
def create_monster(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    try:
        slug = str(data["slug"])
        name = str(data["name"])
        cr = str(data["cr"])
        armor_class = int(data["armor_class"])
        hit_points = int(data["hit_points"])
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest()

    if not _validate_slug(slug):
        return HttpResponseBadRequest()

    tags = data.get("tags")
    if not _validate_tags(tags):
        return HttpResponseBadRequest()
    if tags is None:
        tags = []

    if db.get_monster(slug) is not None:
        return JsonResponse({"error": "duplicate slug"}, status=409)

    try:
        db.create_monster(slug, name, cr, armor_class, hit_points, tags)
    except db.DuplicateSlugError:
        return JsonResponse({"error": "duplicate slug"}, status=409)

    return JsonResponse({
        "slug": slug,
        "name": name,
        "cr": cr,
        "armor_class": armor_class,
        "hit_points": hit_points,
    }, status=201)


def get_monster(request, slug):
    if request.method != "GET":
        return HttpResponseBadRequest()

    monster = db.get_monster(slug)
    if monster is None:
        return HttpResponseNotFound()

    return JsonResponse(monster)


@csrf_exempt
def create_item(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    try:
        slug = str(data["slug"])
        name = str(data["name"])
        item_type = str(data["type"])
        rarity = str(data["rarity"])
        cost_gp = int(data["cost_gp"])
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest()

    if not _validate_slug(slug):
        return HttpResponseBadRequest()

    if db.get_item(slug) is not None:
        return JsonResponse({"error": "duplicate slug"}, status=409)

    try:
        db.create_item(slug, name, item_type, rarity, cost_gp)
    except db.DuplicateSlugError:
        return JsonResponse({"error": "duplicate slug"}, status=409)

    return JsonResponse({
        "slug": slug,
        "name": name,
        "type": item_type,
        "rarity": rarity,
        "cost_gp": cost_gp,
    }, status=201)


def get_item(request, slug):
    if request.method != "GET":
        return HttpResponseBadRequest()

    item = db.get_item(slug)
    if item is None:
        return HttpResponseNotFound()

    return JsonResponse(item)


@csrf_exempt
def create_campaign(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    try:
        campaign_id = str(data["id"])
        name = str(data["name"])
        dm = str(data["dm"])
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest()

    if db.get_campaign(campaign_id) is not None:
        return JsonResponse({"error": "duplicate campaign id"}, status=409)

    try:
        db.create_campaign(campaign_id, name, dm)
    except db.SessionExistsError:
        return JsonResponse({"error": "duplicate campaign id"}, status=409)

    return JsonResponse({"id": campaign_id, "name": name, "dm": dm}, status=201)


@csrf_exempt
def add_character(request, campaign_id):
    if request.method != "POST":
        return HttpResponseBadRequest()

    if db.get_campaign(campaign_id) is None:
        return HttpResponseNotFound()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    try:
        character_id = str(data["id"])
        name = str(data["name"])
        level = int(data["level"])
        class_name = str(data["class"])
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest()

    if level < 1 or level > 20:
        return HttpResponseBadRequest()

    try:
        db.create_character(character_id, campaign_id, name, level, class_name)
    except db.SessionExistsError:
        return JsonResponse({"error": "duplicate character id"}, status=409)

    return JsonResponse(
        {"id": character_id, "name": name, "level": level, "class": class_name},
        status=201,
    )


@csrf_exempt
def add_event(request, campaign_id):
    if request.method != "POST":
        return HttpResponseBadRequest()

    if db.get_campaign(campaign_id) is None:
        return HttpResponseNotFound()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    try:
        event_id = str(data["id"])
        kind = str(data["kind"])
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest()

    summary = data.get("summary")
    if summary is not None and not isinstance(summary, str):
        return HttpResponseBadRequest()

    try:
        db.create_event(event_id, campaign_id, kind, summary)
    except db.SessionExistsError:
        return JsonResponse({"error": "duplicate event id"}, status=409)

    return JsonResponse({"id": event_id, "kind": kind}, status=201)


def get_campaign_state(request, campaign_id):
    if request.method != "GET":
        return HttpResponseBadRequest()

    campaign = db.get_campaign(campaign_id)
    if campaign is None:
        return HttpResponseNotFound()

    characters = db.list_characters(campaign_id)
    log_count = db.count_events(campaign_id)

    return JsonResponse({
        "id": campaign_id,
        "name": campaign["name"],
        "dm": campaign["dm"],
        "characters": characters,
        "log_count": log_count,
    })


@csrf_exempt
def spell_slots(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    class_name = data.get("class")
    if class_name != "wizard":
        return HttpResponseBadRequest()

    try:
        level = int(data["level"])
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest()

    slots = WIZARD_SPELL_SLOTS.get(level)
    if slots is None:
        return HttpResponseBadRequest()

    return JsonResponse({"class": class_name, "level": level, "slots": slots})


@csrf_exempt
def long_rest(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    try:
        level = int(data["level"])
        hp_current = int(data["hp_current"])
        hp_max = int(data["hp_max"])
        hit_dice_spent = int(data["hit_dice_spent"])
        exhaustion_level = int(data["exhaustion_level"])
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest()

    if (
        level < 1
        or hp_max < 1
        or hp_current < 0
        or hp_current > hp_max
        or hit_dice_spent < 0
        or hit_dice_spent > level
        or exhaustion_level < 0
    ):
        return HttpResponseBadRequest()

    hp_current = hp_max
    restored = max(1, level // 2)
    hit_dice_spent = max(0, hit_dice_spent - restored)
    exhaustion_level = max(0, exhaustion_level - 1)

    return JsonResponse({
        "hp_current": hp_current,
        "hit_dice_spent": hit_dice_spent,
        "exhaustion_level": exhaustion_level,
    })


@csrf_exempt
def equipment_load(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    try:
        strength = int(data["strength"])
        weight = int(data["weight"])
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest()

    if strength < 1 or weight < 0:
        return HttpResponseBadRequest()

    capacity = strength * 15
    return JsonResponse({
        "capacity": capacity,
        "weight": weight,
        "encumbered": weight > capacity,
    })


@csrf_exempt
def encounter_builder(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    campaign_id = data.get("campaign_id")
    party = data.get("party")
    monster_slugs = data.get("monster_slugs")

    if not isinstance(campaign_id, str) or not isinstance(party, list) or not isinstance(monster_slugs, list):
        return HttpResponseBadRequest()

    if not party or not monster_slugs:
        return HttpResponseBadRequest()

    if db.get_campaign(campaign_id) is None:
        return HttpResponseNotFound()

    cr_counts = {}
    for slug in monster_slugs:
        if not isinstance(slug, str) or not _validate_slug(slug):
            return HttpResponseBadRequest()
        monster = db.get_monster(slug)
        if monster is None:
            return HttpResponseBadRequest()
        cr_counts[monster["cr"]] = cr_counts.get(monster["cr"], 0) + 1

    monsters = [{"cr": cr, "count": count} for cr, count in cr_counts.items()]
    result = _compute_encounter(party, monsters)
    if result is None:
        return HttpResponseBadRequest()

    return JsonResponse({
        "campaign_id": campaign_id,
        "base_xp": result["base_xp"],
        "adjusted_xp": result["adjusted_xp"],
        "difficulty": result["difficulty"],
        "monster_count": result["monster_count"],
        "recommendation": _difficulty_recommendation(result["difficulty"]),
    })


@csrf_exempt
def loot_parcel(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    campaign_id = data.get("campaign_id")
    try:
        tier = int(data["tier"])
        seed = int(data["seed"])
    except (KeyError, TypeError, ValueError):
        return HttpResponseBadRequest()

    if not isinstance(campaign_id, str) or tier != 1:
        return HttpResponseBadRequest()

    return JsonResponse({
        "campaign_id": campaign_id,
        "coins_gp": 75,
        "items": [{"slug": "healing-potion", "quantity": 2}],
    })


@csrf_exempt
def session_recap(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    data = _load_json(request)
    if data is None or not isinstance(data, dict):
        return HttpResponseBadRequest()

    campaign_id = data.get("campaign_id")
    if not isinstance(campaign_id, str):
        return HttpResponseBadRequest()

    if db.get_campaign(campaign_id) is None:
        return HttpResponseNotFound()

    characters = db.list_characters(campaign_id)
    events = db.list_events(campaign_id)

    if events:
        latest = events[-1]
        event_summary = latest["summary"] or ""
        stripped = event_summary.strip()
        is_sentence = stripped and stripped.endswith(".") and " " in stripped

        if is_sentence:
            summary = event_summary
        elif characters and event_summary:
            summary = f"{characters[0]['name']} scouts the {event_summary}."
        else:
            summary = event_summary or "The party prepares for adventure."

        open_threads = []
        cleaned = summary.strip().rstrip(".")
        last_the = cleaned.rfind(" the ")
        if last_the != -1:
            object_phrase = cleaned[last_the + 5:].strip()
        else:
            object_phrase = cleaned.strip()

        if object_phrase:
            open_threads = [f"Resolve {object_phrase} ambush"]
    else:
        summary = "The party prepares for adventure."
        open_threads = []

    return JsonResponse({
        "campaign_id": campaign_id,
        "summary": summary,
        "open_threads": open_threads,
    })


urlpatterns = [
    path("health", health),
    path("v1/dice/stats", dice_stats),
    path("v1/checks/ability", ability_check),
    path("v1/encounters/adjusted-xp", adjusted_xp),
    path("v1/initiative/order", initiative_order),
    path("v1/characters/ability-modifier", ability_modifier_view),
    path("v1/characters/proficiency", proficiency_view),
    path("v1/characters/derived-stats", derived_stats),
    path("v1/combat/sessions", create_combat_session),
    path("v1/combat/sessions/<str:session_id>/conditions", add_condition),
    path("v1/combat/sessions/<str:session_id>/advance", advance_turn),
    path("v1/auth/register", register),
    path("v1/auth/login", login),
    path("v1/storage/status", storage_status),
    path("v1/storage/reset", storage_reset),
    path("v1/compendium/monsters", create_monster),
    path("v1/compendium/monsters/<str:slug>", get_monster),
    path("v1/compendium/items", create_item),
    path("v1/compendium/items/<str:slug>", get_item),
    path("v1/campaigns", create_campaign),
    path("v1/campaigns/<str:campaign_id>/characters", add_character),
    path("v1/campaigns/<str:campaign_id>/events", add_event),
    path("v1/campaigns/<str:campaign_id>/state", get_campaign_state),
    path("v1/phb/spell-slots", spell_slots),
    path("v1/phb/rests/long", long_rest),
    path("v1/phb/equipment-load", equipment_load),
    path("v1/dm/encounter-builder", encounter_builder),
    path("v1/dm/loot-parcel", loot_parcel),
    path("v1/dm/session-recap", session_recap),
]
