import json
import math
import re

from django.contrib.auth.hashers import check_password, make_password
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from . import storage

storage.init_schema()

DICE_RE = re.compile(r"^(\d+)d(\d+)(?:([+-])(\d+))?$")

USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")

ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")

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


def _load_json(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def health(request):
    return JsonResponse({"ok": True})


@csrf_exempt
def storage_status(request):
    return JsonResponse({
        "driver": "sqlite",
        "schema_version": storage.SCHEMA_VERSION,
        "initialized": storage.is_initialized(),
    })


@csrf_exempt
def storage_reset(request):
    if request.method != "POST":
        return JsonResponse({"error": "invalid request"}, status=400)

    storage.reset_schema()
    return JsonResponse({"ok": True, "schema_version": storage.SCHEMA_VERSION})


def _sort_key(c):
    return (-c["score"], -c["dex"], c["name"])


def _order_view(session):
    return [{"name": c["name"], "score": c["score"]} for c in session["order"]]


def _conditions_view(session):
    return {
        name: [
            {"condition": cond["condition"], "remaining_rounds": cond["remaining_rounds"]}
            for cond in conds
        ]
        for name, conds in session["conditions"].items()
    }


@csrf_exempt
def combat_sessions(request):
    if request.method != "POST":
        return JsonResponse({"error": "invalid request"}, status=400)

    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    session_id = data.get("id")
    combatants = data.get("combatants")
    if not isinstance(session_id, str) or not session_id:
        return JsonResponse({"error": "invalid request"}, status=400)
    if storage.combat_session_exists(session_id):
        return JsonResponse({"error": "session already exists"}, status=400)
    if not isinstance(combatants, list) or not combatants:
        return JsonResponse({"error": "invalid request"}, status=400)

    enriched = []
    for c in combatants:
        if not isinstance(c, dict):
            return JsonResponse({"error": "invalid request"}, status=400)
        try:
            name = c["name"]
            dex = c["dex"]
            roll = c["roll"]
        except (KeyError, TypeError):
            return JsonResponse({"error": "invalid request"}, status=400)
        if not isinstance(name, str):
            return JsonResponse({"error": "invalid request"}, status=400)
        score = roll + dex
        enriched.append({"name": name, "dex": dex, "roll": roll, "score": score})

    enriched.sort(key=_sort_key)

    session = {
        "id": session_id,
        "round": 1,
        "turn_index": 0,
        "order": enriched,
        "conditions": {},
    }
    storage.save_combat_session(session)

    active = enriched[session["turn_index"]]
    return JsonResponse({
        "id": session_id,
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": {"name": active["name"], "score": active["score"]},
        "order": _order_view(session),
    })


@csrf_exempt
def combat_conditions(request, session_id):
    if request.method != "POST":
        return JsonResponse({"error": "invalid request"}, status=400)

    session = storage.get_combat_session(session_id)
    if session is None:
        return JsonResponse({"error": "session not found"}, status=404)

    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    target = data.get("target")
    condition = data.get("condition")
    duration_rounds = data.get("duration_rounds")

    if target not in {c["name"] for c in session["order"]}:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(condition, str) or not condition:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not _is_int(duration_rounds) or duration_rounds <= 0:
        return JsonResponse({"error": "invalid request"}, status=400)

    session["conditions"].setdefault(target, []).append({
        "condition": condition,
        "remaining_rounds": duration_rounds,
    })
    storage.save_combat_session(session)

    return JsonResponse({
        "target": target,
        "conditions": [
            {"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]}
            for c in session["conditions"][target]
        ],
    })


@csrf_exempt
def combat_advance(request, session_id):
    if request.method != "POST":
        return JsonResponse({"error": "invalid request"}, status=400)

    session = storage.get_combat_session(session_id)
    if session is None:
        return JsonResponse({"error": "session not found"}, status=404)

    order = session["order"]
    session["turn_index"] += 1
    if session["turn_index"] >= len(order):
        session["turn_index"] = 0
        session["round"] += 1

    active = order[session["turn_index"]]
    if active["name"] in session["conditions"]:
        conds = session["conditions"][active["name"]]
        for cond in conds:
            cond["remaining_rounds"] -= 1
        session["conditions"][active["name"]] = [c for c in conds if c["remaining_rounds"] > 0]

    storage.save_combat_session(session)

    return JsonResponse({
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": {"name": active["name"], "score": active["score"]},
        "conditions": _conditions_view(session),
    })


@csrf_exempt
def dice_stats(request):
    data = _load_json(request)
    if data is None or "expression" not in data:
        return JsonResponse({"error": "invalid request"}, status=400)

    expression = data["expression"]
    if not isinstance(expression, str):
        return JsonResponse({"error": "invalid expression"}, status=400)

    match = DICE_RE.match(expression.strip())
    if not match:
        return JsonResponse({"error": "invalid expression"}, status=400)

    count = int(match.group(1))
    sides = int(match.group(2))
    sign = match.group(3)
    mod_value = match.group(4)
    modifier = 0
    if mod_value is not None:
        modifier = int(mod_value)
        if sign == "-":
            modifier = -modifier

    if count <= 0 or sides <= 0:
        return JsonResponse({"error": "invalid expression"}, status=400)

    min_val = count * 1 + modifier
    max_val = count * sides + modifier
    average = (count * (1 + sides) / 2) + modifier
    if float(average).is_integer():
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
    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    try:
        roll = data["roll"]
        modifier = data["modifier"]
        dc = data["dc"]
    except KeyError:
        return JsonResponse({"error": "invalid request"}, status=400)

    if not all(isinstance(v, (int, float)) for v in (roll, modifier, dc)):
        return JsonResponse({"error": "invalid request"}, status=400)

    total = roll + modifier
    success = total >= dc
    margin = total - dc

    return JsonResponse({
        "total": total,
        "success": success,
        "margin": margin,
    })


@csrf_exempt
def adjusted_xp(request):
    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    party = data.get("party")
    monsters = data.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        return JsonResponse({"error": "invalid request"}, status=400)

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        cr = str(monster.get("cr"))
        count = monster.get("count")
        if cr not in CR_XP or not isinstance(count, int):
            return JsonResponse({"error": "invalid request"}, status=400)
        base_xp += CR_XP[cr] * count
        monster_count += count

    multiplier = _multiplier(monster_count)
    adjusted = base_xp * multiplier

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = member.get("level")
        if level not in LEVEL_THRESHOLDS:
            return JsonResponse({"error": "invalid request"}, status=400)
        for key in thresholds:
            thresholds[key] += LEVEL_THRESHOLDS[level][key]

    difficulty = "trivial"
    if adjusted >= thresholds["deadly"]:
        difficulty = "deadly"
    elif adjusted >= thresholds["hard"]:
        difficulty = "hard"
    elif adjusted >= thresholds["medium"]:
        difficulty = "medium"
    elif adjusted >= thresholds["easy"]:
        difficulty = "easy"

    def _norm(x):
        return int(x) if float(x).is_integer() else x

    return JsonResponse({
        "base_xp": _norm(base_xp),
        "monster_count": monster_count,
        "multiplier": _norm(multiplier),
        "adjusted_xp": _norm(adjusted),
        "difficulty": difficulty,
        "thresholds": {k: _norm(v) for k, v in thresholds.items()},
    })


@csrf_exempt
def initiative_order(request):
    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    combatants = data.get("combatants")
    if not isinstance(combatants, list):
        return JsonResponse({"error": "invalid request"}, status=400)

    enriched = []
    for c in combatants:
        try:
            name = c["name"]
            dex = c["dex"]
            roll = c["roll"]
        except (KeyError, TypeError):
            return JsonResponse({"error": "invalid request"}, status=400)
        score = roll + dex
        enriched.append({"name": name, "dex": dex, "score": score})

    enriched.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))

    order = [{"name": c["name"], "score": c["score"]} for c in enriched]

    return JsonResponse({"order": order})


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _ability_modifier(score):
    return math.floor((score - 10) / 2)


def _proficiency_bonus(level):
    return 2 + (level - 1) // 4


@csrf_exempt
def ability_modifier(request):
    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    score = data.get("score")
    if not _is_int(score) or not (1 <= score <= 30):
        return JsonResponse({"error": "invalid request"}, status=400)

    return JsonResponse({"score": score, "modifier": _ability_modifier(score)})


@csrf_exempt
def proficiency(request):
    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    level = data.get("level")
    if not _is_int(level) or not (1 <= level <= 20):
        return JsonResponse({"error": "invalid request"}, status=400)

    return JsonResponse({"level": level, "proficiency_bonus": _proficiency_bonus(level)})


@csrf_exempt
def derived_stats(request):
    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    level = data.get("level")
    abilities = data.get("abilities")
    armor = data.get("armor")

    if not _is_int(level) or not (1 <= level <= 20):
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(abilities, dict) or not isinstance(armor, dict):
        return JsonResponse({"error": "invalid request"}, status=400)

    scores = {}
    for key in ABILITY_KEYS:
        score = abilities.get(key)
        if not _is_int(score) or not (1 <= score <= 30):
            return JsonResponse({"error": "invalid request"}, status=400)
        scores[key] = score

    base = armor.get("base")
    shield = armor.get("shield")
    dex_cap = armor.get("dex_cap")
    if not _is_int(base):
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(shield, bool):
        return JsonResponse({"error": "invalid request"}, status=400)
    if not _is_int(dex_cap):
        return JsonResponse({"error": "invalid request"}, status=400)

    modifiers = {key: _ability_modifier(score) for key, score in scores.items()}
    proficiency_bonus = _proficiency_bonus(level)
    hp_max = level * (6 + modifiers["con"])
    shield_bonus = 2 if shield else 0
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus

    return JsonResponse({
        "level": level,
        "proficiency_bonus": proficiency_bonus,
        "hp_max": hp_max,
        "armor_class": armor_class,
        "modifiers": modifiers,
    })


@csrf_exempt
def auth_register(request):
    if request.method != "POST":
        return JsonResponse({"error": "invalid request"}, status=400)

    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    username = data.get("username")
    password = data.get("password")
    role = data.get("role")

    if not isinstance(username, str) or not USERNAME_RE.match(username):
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(password, str) or len(password) < 8:
        return JsonResponse({"error": "invalid request"}, status=400)
    if role not in ("dm", "player"):
        return JsonResponse({"error": "invalid request"}, status=400)

    if storage.get_user(username) is not None:
        return JsonResponse({"error": "username already exists"}, status=409)

    storage.create_user(username, make_password(password), role)

    return JsonResponse({"username": username, "role": role}, status=201)


SLUG_RE = re.compile(r"^[a-z0-9-]+$")


@csrf_exempt
def compendium_monsters(request):
    if request.method != "POST":
        return JsonResponse({"error": "invalid request"}, status=400)

    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    slug = data.get("slug")
    name = data.get("name")
    cr = data.get("cr")
    armor_class = data.get("armor_class")
    hit_points = data.get("hit_points")
    tags = data.get("tags", [])

    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(name, str) or not name:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(cr, str) or not cr:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not _is_int(armor_class):
        return JsonResponse({"error": "invalid request"}, status=400)
    if not _is_int(hit_points):
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        return JsonResponse({"error": "invalid request"}, status=400)

    if storage.monster_exists(slug):
        return JsonResponse({"error": "monster already exists"}, status=409)

    monster = {
        "slug": slug,
        "name": name,
        "cr": cr,
        "armor_class": armor_class,
        "hit_points": hit_points,
        "tags": tags,
    }
    storage.create_monster(monster)

    return JsonResponse({
        "slug": slug,
        "name": name,
        "cr": cr,
        "armor_class": armor_class,
        "hit_points": hit_points,
    }, status=201)


def compendium_monster_detail(request, slug):
    if request.method != "GET":
        return JsonResponse({"error": "invalid request"}, status=400)

    monster = storage.get_monster(slug)
    if monster is None:
        return JsonResponse({"error": "monster not found"}, status=404)

    return JsonResponse(monster)


@csrf_exempt
def compendium_items(request):
    if request.method != "POST":
        return JsonResponse({"error": "invalid request"}, status=400)

    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    slug = data.get("slug")
    name = data.get("name")
    item_type = data.get("type")
    rarity = data.get("rarity")
    cost_gp = data.get("cost_gp")

    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(name, str) or not name:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(item_type, str) or not item_type:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(rarity, str) or not rarity:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not _is_int(cost_gp) and not isinstance(cost_gp, float):
        return JsonResponse({"error": "invalid request"}, status=400)

    if storage.item_exists(slug):
        return JsonResponse({"error": "item already exists"}, status=409)

    item = {
        "slug": slug,
        "name": name,
        "type": item_type,
        "rarity": rarity,
        "cost_gp": cost_gp,
    }
    storage.create_item(item)

    return JsonResponse(item, status=201)


def compendium_item_detail(request, slug):
    if request.method != "GET":
        return JsonResponse({"error": "invalid request"}, status=400)

    item = storage.get_item(slug)
    if item is None:
        return JsonResponse({"error": "item not found"}, status=404)

    return JsonResponse(item)


@csrf_exempt
def auth_login(request):
    if request.method != "POST":
        return JsonResponse({"error": "invalid request"}, status=400)

    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        return JsonResponse({"error": "invalid request"}, status=400)

    user = storage.get_user(username)
    if user is None or not check_password(password, user["password_hash"]):
        return JsonResponse({"error": "invalid credentials"}, status=401)

    return JsonResponse({"username": username, "token": f"session-{username}"})


@csrf_exempt
def campaigns(request):
    if request.method != "POST":
        return JsonResponse({"error": "invalid request"}, status=400)

    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    campaign_id = data.get("id")
    name = data.get("name")
    dm = data.get("dm")

    if not isinstance(campaign_id, str) or not campaign_id:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(name, str) or not name:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(dm, str) or not dm:
        return JsonResponse({"error": "invalid request"}, status=400)

    if storage.campaign_exists(campaign_id):
        return JsonResponse({"error": "campaign already exists"}, status=409)

    campaign = {"id": campaign_id, "name": name, "dm": dm}
    storage.create_campaign(campaign)

    return JsonResponse(campaign, status=201)


@csrf_exempt
def campaign_characters(request, campaign_id):
    if request.method != "POST":
        return JsonResponse({"error": "invalid request"}, status=400)

    if not storage.campaign_exists(campaign_id):
        return JsonResponse({"error": "campaign not found"}, status=404)

    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    char_id = data.get("id")
    name = data.get("name")
    level = data.get("level")
    char_class = data.get("class")

    if not isinstance(char_id, str) or not char_id:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(name, str) or not name:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not _is_int(level):
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(char_class, str) or not char_class:
        return JsonResponse({"error": "invalid request"}, status=400)

    if storage.campaign_character_exists(campaign_id, char_id):
        return JsonResponse({"error": "character already exists"}, status=409)

    character = {"id": char_id, "name": name, "level": level, "class": char_class}
    storage.add_campaign_character(campaign_id, character)

    return JsonResponse(character, status=201)


@csrf_exempt
def campaign_events(request, campaign_id):
    if request.method != "POST":
        return JsonResponse({"error": "invalid request"}, status=400)

    if not storage.campaign_exists(campaign_id):
        return JsonResponse({"error": "campaign not found"}, status=404)

    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    event_id = data.get("id")
    kind = data.get("kind")
    summary = data.get("summary")

    if not isinstance(event_id, str) or not event_id:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(kind, str) or not kind:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(summary, str) or not summary:
        return JsonResponse({"error": "invalid request"}, status=400)

    if storage.campaign_event_exists(campaign_id, event_id):
        return JsonResponse({"error": "event already exists"}, status=409)

    event = {"id": event_id, "kind": kind, "summary": summary}
    storage.add_campaign_event(campaign_id, event)

    return JsonResponse({"id": event_id, "kind": kind}, status=201)


def campaign_state(request, campaign_id):
    if request.method != "GET":
        return JsonResponse({"error": "invalid request"}, status=400)

    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    characters = storage.list_campaign_characters(campaign_id)
    log_count = storage.count_campaign_events(campaign_id)

    return JsonResponse({
        "id": campaign["id"],
        "name": campaign["name"],
        "dm": campaign["dm"],
        "characters": characters,
        "log_count": log_count,
    })


WIZARD_SPELL_SLOTS = {
    5: {"1": 4, "2": 3, "3": 2},
}


@csrf_exempt
def phb_spell_slots(request):
    if request.method != "POST":
        return JsonResponse({"error": "invalid request"}, status=400)

    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    char_class = data.get("class")
    level = data.get("level")

    if not isinstance(char_class, str) or not char_class:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not _is_int(level):
        return JsonResponse({"error": "invalid request"}, status=400)

    if char_class != "wizard" or level not in WIZARD_SPELL_SLOTS:
        return JsonResponse({"error": "invalid request"}, status=400)

    slots = WIZARD_SPELL_SLOTS[level]

    return JsonResponse({"class": char_class, "level": level, "slots": slots})


@csrf_exempt
def phb_long_rest(request):
    if request.method != "POST":
        return JsonResponse({"error": "invalid request"}, status=400)

    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    level = data.get("level")
    hp_current = data.get("hp_current")
    hp_max = data.get("hp_max")
    hit_dice_spent = data.get("hit_dice_spent")
    exhaustion_level = data.get("exhaustion_level")

    if not _is_int(level) or not (1 <= level <= 20):
        return JsonResponse({"error": "invalid request"}, status=400)
    if not _is_int(hp_current) or hp_current < 0:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not _is_int(hp_max) or hp_max < 0:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not _is_int(hit_dice_spent) or hit_dice_spent < 0:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not _is_int(exhaustion_level) or exhaustion_level < 0:
        return JsonResponse({"error": "invalid request"}, status=400)

    max_recoverable = max(1, level // 2)
    new_hit_dice_spent = max(0, hit_dice_spent - max_recoverable)
    new_exhaustion_level = max(0, exhaustion_level - 1)

    return JsonResponse({
        "hp_current": hp_max,
        "hit_dice_spent": new_hit_dice_spent,
        "exhaustion_level": new_exhaustion_level,
    })


@csrf_exempt
def phb_equipment_load(request):
    if request.method != "POST":
        return JsonResponse({"error": "invalid request"}, status=400)

    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    strength = data.get("strength")
    weight = data.get("weight")

    if not _is_int(strength) or strength < 0:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not _is_int(weight) or weight < 0:
        return JsonResponse({"error": "invalid request"}, status=400)

    capacity = strength * 15

    return JsonResponse({
        "capacity": capacity,
        "weight": weight,
        "encumbered": weight > capacity,
    })


DIFFICULTY_RECOMMENDATIONS = {
    "trivial": "no real threat",
    "easy": "safe warm-up",
    "medium": "solid challenge",
    "hard": "risky fight",
    "deadly": "potential character death",
}

LOOT_TABLES = {
    1: {"coins_gp": 75, "items": [{"slug": "healing-potion", "quantity": 2}]},
}


def _norm_num(x):
    return int(x) if float(x).is_integer() else x


@csrf_exempt
def dm_encounter_builder(request):
    if request.method != "POST":
        return JsonResponse({"error": "invalid request"}, status=400)

    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    campaign_id = data.get("campaign_id")
    party = data.get("party")
    monster_slugs = data.get("monster_slugs")

    if not isinstance(campaign_id, str) or not campaign_id:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(party, list) or not party:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(monster_slugs, list) or not monster_slugs:
        return JsonResponse({"error": "invalid request"}, status=400)

    if not storage.campaign_exists(campaign_id):
        return JsonResponse({"error": "campaign not found"}, status=404)

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            return JsonResponse({"error": "invalid request"}, status=400)
        level = member.get("level")
        if level not in LEVEL_THRESHOLDS:
            return JsonResponse({"error": "invalid request"}, status=400)
        for key in thresholds:
            thresholds[key] += LEVEL_THRESHOLDS[level][key]

    base_xp = 0
    for slug in monster_slugs:
        if not isinstance(slug, str):
            return JsonResponse({"error": "invalid request"}, status=400)
        monster = storage.get_monster(slug)
        if monster is None:
            return JsonResponse({"error": "monster not found"}, status=404)
        cr = str(monster.get("cr"))
        if cr not in CR_XP:
            return JsonResponse({"error": "invalid request"}, status=400)
        base_xp += CR_XP[cr]

    monster_count = len(monster_slugs)
    multiplier = _multiplier(monster_count)
    adjusted_xp = base_xp * multiplier

    difficulty = "trivial"
    if adjusted_xp >= thresholds["deadly"]:
        difficulty = "deadly"
    elif adjusted_xp >= thresholds["hard"]:
        difficulty = "hard"
    elif adjusted_xp >= thresholds["medium"]:
        difficulty = "medium"
    elif adjusted_xp >= thresholds["easy"]:
        difficulty = "easy"

    return JsonResponse({
        "campaign_id": campaign_id,
        "base_xp": _norm_num(base_xp),
        "adjusted_xp": _norm_num(adjusted_xp),
        "difficulty": difficulty,
        "monster_count": monster_count,
        "recommendation": DIFFICULTY_RECOMMENDATIONS[difficulty],
    })


@csrf_exempt
def dm_loot_parcel(request):
    if request.method != "POST":
        return JsonResponse({"error": "invalid request"}, status=400)

    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    campaign_id = data.get("campaign_id")
    tier = data.get("tier")

    if not isinstance(campaign_id, str) or not campaign_id:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not _is_int(tier) or tier < 1:
        return JsonResponse({"error": "invalid request"}, status=400)

    if not storage.campaign_exists(campaign_id):
        return JsonResponse({"error": "campaign not found"}, status=404)

    loot = LOOT_TABLES.get(tier)
    if loot is None:
        loot = {
            "coins_gp": 75 * tier,
            "items": [{"slug": "healing-potion", "quantity": 2 * tier}],
        }

    return JsonResponse({
        "campaign_id": campaign_id,
        "coins_gp": loot["coins_gp"],
        "items": loot["items"],
    })


@csrf_exempt
def dm_session_recap(request):
    if request.method != "POST":
        return JsonResponse({"error": "invalid request"}, status=400)

    data = _load_json(request)
    if data is None:
        return JsonResponse({"error": "invalid request"}, status=400)

    campaign_id = data.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        return JsonResponse({"error": "invalid request"}, status=400)

    if not storage.campaign_exists(campaign_id):
        return JsonResponse({"error": "campaign not found"}, status=404)

    events = storage.list_campaign_events(campaign_id)

    if events:
        summary = events[-1]["summary"]
        open_threads = [
            "Resolve {}".format(event["summary"]) for event in events
        ]
    else:
        summary = "No sessions recorded yet."
        open_threads = []

    return JsonResponse({
        "campaign_id": campaign_id,
        "summary": summary,
        "open_threads": open_threads,
    })
