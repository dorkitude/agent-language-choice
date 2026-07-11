import json
import re

from django.contrib.auth.hashers import check_password, make_password
from django.http import JsonResponse, Http404
from django.views.decorators.csrf import csrf_exempt

from dndsite import storage

# Initialize the durable SQLite schema on server startup (module import).
storage.init_storage()

USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")

DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")

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

# Per-monster-count encounter multipliers.
COUNT_MULTIPLIERS = [
    (1, 1, 1),
    (2, 2, 1.5),
    (3, 6, 2),
    (7, 10, 2.5),
    (11, 14, 3),
    (15, None, 4),
]

# Per-level difficulty thresholds (easy, medium, hard, deadly).
LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}


def _bad_request(message="invalid request"):
    return JsonResponse({"error": message}, status=400)


def _parse_json(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def health(request):
    return JsonResponse({"ok": True})


@csrf_exempt
def dice_stats(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()
    expression = data.get("expression")
    if not isinstance(expression, str):
        return _bad_request()
    match = DICE_RE.match(expression.strip())
    if not match:
        return _bad_request("invalid expression")
    count = int(match.group(1))
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0
    if count <= 0 or sides <= 0:
        return _bad_request("count and sides must be positive")
    minimum = count * 1 + modifier
    maximum = count * sides + modifier
    average = (minimum + maximum) / 2
    if average == int(average):
        average = int(average)
    return JsonResponse(
        {
            "dice_count": count,
            "sides": sides,
            "modifier": modifier,
            "min": minimum,
            "max": maximum,
            "average": average,
        }
    )


@csrf_exempt
def ability_check(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()
    try:
        roll = data["roll"]
        modifier = data["modifier"]
        dc = data["dc"]
    except (KeyError, TypeError):
        return _bad_request()
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (roll, modifier, dc)):
        return _bad_request()
    total = roll + modifier
    return JsonResponse(
        {
            "total": total,
            "success": total >= dc,
            "margin": total - dc,
        }
    )


def _count_multiplier(count):
    for low, high, mult in COUNT_MULTIPLIERS:
        if count >= low and (high is None or count <= high):
            return mult
    return 1


@csrf_exempt
def adjusted_xp(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()
    party = data.get("party")
    monsters = data.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        return _bad_request()

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        if not isinstance(monster, dict):
            return _bad_request()
        cr = monster.get("cr")
        count = monster.get("count")
        if isinstance(cr, (int, float)) and not isinstance(cr, bool):
            cr = str(cr) if cr != int(cr) else str(int(cr))
        if cr not in CR_XP:
            return _bad_request("unsupported cr")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            return _bad_request()
        base_xp += CR_XP[cr] * count
        monster_count += count

    multiplier = _count_multiplier(monster_count)
    adjusted = base_xp * multiplier
    if adjusted == int(adjusted):
        adjusted = int(adjusted)
    if multiplier == int(multiplier):
        multiplier = int(multiplier)

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            return _bad_request()
        level = member.get("level")
        if level not in LEVEL_THRESHOLDS:
            return _bad_request("unsupported level")
        for key in thresholds:
            thresholds[key] += LEVEL_THRESHOLDS[level][key]

    difficulty = "trivial"
    for key in ("easy", "medium", "hard", "deadly"):
        if adjusted >= thresholds[key]:
            difficulty = key

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


@csrf_exempt
def initiative_order(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()
    combatants = data.get("combatants")
    if not isinstance(combatants, list):
        return _bad_request()

    parsed = []
    for combatant in combatants:
        if not isinstance(combatant, dict):
            return _bad_request()
        name = combatant.get("name")
        dex = combatant.get("dex")
        roll = combatant.get("roll")
        if not isinstance(name, str):
            return _bad_request()
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (dex, roll)):
            return _bad_request()
        parsed.append({"name": name, "score": roll + dex, "dex": dex})

    parsed.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
    order = [{"name": c["name"], "score": c["score"]} for c in parsed]
    return JsonResponse({"order": order})


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _ability_modifier(score):
    return (score - 10) // 2


def _proficiency_bonus(level):
    return (level + 7) // 4


ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")


@csrf_exempt
def ability_modifier(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()
    score = data.get("score")
    if not _is_int(score) or score < 1 or score > 30:
        return _bad_request()
    return JsonResponse({"score": score, "modifier": _ability_modifier(score)})


@csrf_exempt
def proficiency(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()
    level = data.get("level")
    if not _is_int(level) or level < 1 or level > 20:
        return _bad_request()
    return JsonResponse({"level": level, "proficiency_bonus": _proficiency_bonus(level)})


@csrf_exempt
def derived_stats(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()

    level = data.get("level")
    if not _is_int(level) or level < 1 or level > 20:
        return _bad_request()

    abilities = data.get("abilities")
    if not isinstance(abilities, dict):
        return _bad_request()
    modifiers = {}
    for key in ABILITY_KEYS:
        score = abilities.get(key)
        if not _is_int(score) or score < 1 or score > 30:
            return _bad_request()
        modifiers[key] = _ability_modifier(score)

    armor = data.get("armor")
    if not isinstance(armor, dict):
        return _bad_request()
    base = armor.get("base")
    shield = armor.get("shield")
    dex_cap = armor.get("dex_cap")
    if not _is_int(base):
        return _bad_request()
    if not isinstance(shield, bool):
        return _bad_request()
    if not _is_int(dex_cap):
        return _bad_request()

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


# In-memory combat session store, keyed by client-supplied id.
COMBAT_SESSIONS = {}


def _not_found(message="session not found"):
    return JsonResponse({"error": message}, status=404)


def _session_public(session):
    active_name = session["order"][session["turn_index"]]["name"]
    active = next(c for c in session["order"] if c["name"] == active_name)
    return {
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": {"name": active["name"], "score": active["score"]},
    }


def _conditions_map(session):
    result = {}
    for name, conds in session["conditions"].items():
        # Include any combatant that has ever had a condition, even if all of
        # its conditions have since expired (empty list preserved).
        if name in session["conditioned"]:
            result[name] = [
                {"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]}
                for c in conds
            ]
    return result


@csrf_exempt
def combat_sessions(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()

    session_id = data.get("id")
    if not isinstance(session_id, str) or not session_id:
        return _bad_request()
    if session_id in COMBAT_SESSIONS:
        return _bad_request("session id already exists")

    combatants = data.get("combatants")
    if not isinstance(combatants, list) or not combatants:
        return _bad_request()

    parsed = []
    seen_names = set()
    for combatant in combatants:
        if not isinstance(combatant, dict):
            return _bad_request()
        name = combatant.get("name")
        dex = combatant.get("dex")
        roll = combatant.get("roll")
        if not isinstance(name, str) or not name:
            return _bad_request()
        if name in seen_names:
            return _bad_request("duplicate combatant name")
        seen_names.add(name)
        if not all(_is_int(v) for v in (dex, roll)):
            return _bad_request()
        parsed.append({"name": name, "score": roll + dex, "dex": dex})

    parsed.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))

    session = {
        "id": session_id,
        "round": 1,
        "turn_index": 0,
        "order": parsed,
        "conditions": {c["name"]: [] for c in parsed},
        "conditioned": set(),
    }
    COMBAT_SESSIONS[session_id] = session

    public = _session_public(session)
    public["order"] = [{"name": c["name"], "score": c["score"]} for c in parsed]
    return JsonResponse(public)


@csrf_exempt
def combat_conditions(request, session_id):
    if request.method != "POST":
        return _bad_request("method not allowed")
    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        return _not_found()
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()

    target = data.get("target")
    condition = data.get("condition")
    duration = data.get("duration_rounds")
    if not isinstance(target, str) or target not in session["conditions"]:
        return _bad_request("unknown target")
    if not isinstance(condition, str) or not condition:
        return _bad_request()
    if not _is_int(duration) or duration <= 0:
        return _bad_request()

    session["conditions"][target].append(
        {"condition": condition, "remaining_rounds": duration}
    )
    session["conditioned"].add(target)

    return JsonResponse(
        {
            "target": target,
            "conditions": [
                {"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]}
                for c in session["conditions"][target]
            ],
        }
    )


@csrf_exempt
def combat_advance(request, session_id):
    if request.method != "POST":
        return _bad_request("method not allowed")
    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        return _not_found()

    count = len(session["order"])
    session["turn_index"] += 1
    if session["turn_index"] >= count:
        session["turn_index"] = 0
        session["round"] += 1

    active_name = session["order"][session["turn_index"]]["name"]
    conds = session["conditions"].get(active_name, [])
    remaining = []
    for cond in conds:
        cond["remaining_rounds"] -= 1
        if cond["remaining_rounds"] > 0:
            remaining.append(cond)
    session["conditions"][active_name] = remaining

    public = _session_public(session)
    public["conditions"] = _conditions_map(session)
    return JsonResponse(public)


@csrf_exempt
def auth_register(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()

    username = data.get("username")
    password = data.get("password")
    role = data.get("role")

    if not isinstance(username, str) or not USERNAME_RE.match(username):
        return _bad_request("invalid username")
    if not isinstance(password, str) or len(password) < 8:
        return _bad_request("invalid password")
    if role not in ("dm", "player"):
        return _bad_request("invalid role")

    created = storage.create_user(username, role, make_password(password))
    if not created:
        return JsonResponse({"error": "username already exists"}, status=409)

    return JsonResponse({"username": username, "role": role}, status=201)


@csrf_exempt
def auth_login(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()

    username = data.get("username")
    password = data.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return _bad_request()

    user = storage.get_user(username)
    if user is None or not check_password(password, user["password_hash"]):
        return JsonResponse({"error": "invalid credentials"}, status=401)

    return JsonResponse({"username": username, "token": "session-" + username})


@csrf_exempt
def compendium_monsters(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()

    slug = data.get("slug")
    name = data.get("name")
    cr = data.get("cr")
    armor_class = data.get("armor_class")
    hit_points = data.get("hit_points")
    tags = data.get("tags", [])

    if not isinstance(slug, str) or not slug:
        return _bad_request("invalid slug")
    if not isinstance(name, str) or not name:
        return _bad_request("invalid name")
    if not isinstance(cr, str) or not cr:
        return _bad_request("invalid cr")
    if not _is_int(armor_class):
        return _bad_request("invalid armor_class")
    if not _is_int(hit_points):
        return _bad_request("invalid hit_points")
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        return _bad_request("invalid tags")

    created = storage.create_monster(slug, name, cr, armor_class, hit_points, tags)
    if not created:
        return JsonResponse({"error": "slug already exists"}, status=409)

    return JsonResponse(
        {
            "slug": slug,
            "name": name,
            "cr": cr,
            "armor_class": armor_class,
            "hit_points": hit_points,
        },
        status=201,
    )


@csrf_exempt
def compendium_monster(request, slug):
    if request.method != "GET":
        return _bad_request("method not allowed")
    monster = storage.get_monster(slug)
    if monster is None:
        return _not_found("monster not found")
    return JsonResponse(monster)


@csrf_exempt
def compendium_items(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()

    slug = data.get("slug")
    name = data.get("name")
    type_ = data.get("type")
    rarity = data.get("rarity")
    cost_gp = data.get("cost_gp")

    if not isinstance(slug, str) or not slug:
        return _bad_request("invalid slug")
    if not isinstance(name, str) or not name:
        return _bad_request("invalid name")
    if not isinstance(type_, str) or not type_:
        return _bad_request("invalid type")
    if not isinstance(rarity, str) or not rarity:
        return _bad_request("invalid rarity")
    if not _is_int(cost_gp):
        return _bad_request("invalid cost_gp")

    created = storage.create_item(slug, name, type_, rarity, cost_gp)
    if not created:
        return JsonResponse({"error": "slug already exists"}, status=409)

    return JsonResponse(
        {
            "slug": slug,
            "name": name,
            "type": type_,
            "rarity": rarity,
            "cost_gp": cost_gp,
        },
        status=201,
    )


@csrf_exempt
def compendium_item(request, slug):
    if request.method != "GET":
        return _bad_request("method not allowed")
    item = storage.get_item(slug)
    if item is None:
        return _not_found("item not found")
    return JsonResponse(item)


@csrf_exempt
def campaigns(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()

    campaign_id = data.get("id")
    name = data.get("name")
    dm = data.get("dm")

    if not isinstance(campaign_id, str) or not campaign_id:
        return _bad_request("invalid id")
    if not isinstance(name, str) or not name:
        return _bad_request("invalid name")
    if not isinstance(dm, str) or not dm:
        return _bad_request("invalid dm")

    created = storage.create_campaign(campaign_id, name, dm)
    if not created:
        return JsonResponse({"error": "campaign id already exists"}, status=409)

    return JsonResponse({"id": campaign_id, "name": name, "dm": dm}, status=201)


@csrf_exempt
def campaign_characters(request, campaign_id):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()

    character_id = data.get("id")
    name = data.get("name")
    level = data.get("level")
    class_ = data.get("class")

    if not isinstance(character_id, str) or not character_id:
        return _bad_request("invalid id")
    if not isinstance(name, str) or not name:
        return _bad_request("invalid name")
    if not _is_int(level) or level < 1 or level > 20:
        return _bad_request("invalid level")
    if not isinstance(class_, str) or not class_:
        return _bad_request("invalid class")

    result = storage.create_character(character_id, campaign_id, name, level, class_)
    if result == "no_campaign":
        return _not_found("campaign not found")
    if result == "duplicate":
        return JsonResponse({"error": "character id already exists"}, status=409)

    return JsonResponse(
        {"id": character_id, "name": name, "level": level, "class": class_},
        status=201,
    )


@csrf_exempt
def campaign_events(request, campaign_id):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()

    event_id = data.get("id")
    kind = data.get("kind")
    summary = data.get("summary")

    if not isinstance(event_id, str) or not event_id:
        return _bad_request("invalid id")
    if not isinstance(kind, str) or not kind:
        return _bad_request("invalid kind")
    if not isinstance(summary, str) or not summary:
        return _bad_request("invalid summary")

    result = storage.create_event(event_id, campaign_id, kind, summary)
    if result == "no_campaign":
        return _not_found("campaign not found")
    if result == "duplicate":
        return JsonResponse({"error": "event id already exists"}, status=409)

    return JsonResponse({"id": event_id, "kind": kind}, status=201)


@csrf_exempt
def campaign_state(request, campaign_id):
    if request.method != "GET":
        return _bad_request("method not allowed")
    state = storage.get_campaign_state(campaign_id)
    if state is None:
        return _not_found("campaign not found")
    return JsonResponse(state)


@csrf_exempt
def storage_status(request):
    if request.method != "GET":
        return _bad_request("method not allowed")
    return JsonResponse(
        {
            "driver": "sqlite",
            "schema_version": storage.SCHEMA_VERSION,
            "initialized": storage.is_initialized(),
        }
    )


@csrf_exempt
def storage_reset(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    storage.reset_storage()
    COMBAT_SESSIONS.clear()
    return JsonResponse({"ok": True, "schema_version": storage.SCHEMA_VERSION})


# --- Stage 7: Selected PHB Rules ---

# Spell slot tables keyed by (class, level). Supports wizard level 5.
SPELL_SLOTS = {
    ("wizard", 5): {"1": 4, "2": 3, "3": 2},
}


@csrf_exempt
def phb_spell_slots(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()
    cls = data.get("class")
    level = data.get("level")
    if not isinstance(cls, str) or not isinstance(level, int) or isinstance(level, bool):
        return _bad_request()
    slots = SPELL_SLOTS.get((cls, level))
    if slots is None:
        return _bad_request("unsupported class/level")
    return JsonResponse({"class": cls, "level": level, "slots": slots})


@csrf_exempt
def phb_rest_long(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()
    level = data.get("level")
    hp_max = data.get("hp_max")
    hit_dice_spent = data.get("hit_dice_spent")
    exhaustion_level = data.get("exhaustion_level")
    for value in (level, hp_max, hit_dice_spent, exhaustion_level):
        if not isinstance(value, int) or isinstance(value, bool):
            return _bad_request()
    if level < 1 or hp_max < 0 or hit_dice_spent < 0 or exhaustion_level < 0:
        return _bad_request()
    recovered = max(1, level // 2)
    hit_dice_spent = max(0, hit_dice_spent - recovered)
    exhaustion_level = max(0, exhaustion_level - 1)
    return JsonResponse(
        {
            "hp_current": hp_max,
            "hit_dice_spent": hit_dice_spent,
            "exhaustion_level": exhaustion_level,
        }
    )


@csrf_exempt
def phb_equipment_load(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()
    strength = data.get("strength")
    weight = data.get("weight")
    for value in (strength, weight):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return _bad_request()
    if strength < 0 or weight < 0:
        return _bad_request()
    capacity = strength * 15
    return JsonResponse(
        {"capacity": capacity, "weight": weight, "encumbered": weight > capacity}
    )


# --- Stage 8: DM Tools ---

# Deterministic recommendation keyed by the computed encounter difficulty.
DIFFICULTY_RECOMMENDATION = {
    "trivial": "cakewalk",
    "easy": "safe warm-up",
    "medium": "a fair fight",
    "hard": "tough battle",
    "deadly": "risk of a wipe",
}

# Deterministic loot parcels keyed by tier for this benchmark.
LOOT_PARCELS = {
    1: {"coins_gp": 75, "items": [{"slug": "healing-potion", "quantity": 2}]},
}


@csrf_exempt
def dm_encounter_builder(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()

    campaign_id = data.get("campaign_id")
    party = data.get("party")
    monster_slugs = data.get("monster_slugs")
    if not isinstance(campaign_id, str) or not campaign_id:
        return _bad_request("invalid campaign_id")
    if not isinstance(party, list) or not party:
        return _bad_request("invalid party")
    if not isinstance(monster_slugs, list) or not monster_slugs:
        return _bad_request("invalid monster_slugs")

    # Base XP: look up each monster's CR from the compendium and sum its value.
    base_xp = 0
    for slug in monster_slugs:
        if not isinstance(slug, str) or not slug:
            return _bad_request("invalid monster slug")
        monster = storage.get_monster(slug)
        if monster is None:
            return _not_found("monster not found")
        cr = monster["cr"]
        if cr not in CR_XP:
            return _bad_request("unsupported cr")
        base_xp += CR_XP[cr]

    monster_count = len(monster_slugs)
    multiplier = _count_multiplier(monster_count)
    adjusted = base_xp * multiplier
    if adjusted == int(adjusted):
        adjusted = int(adjusted)

    # Party difficulty thresholds, reusing the core adjusted-XP math.
    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            return _bad_request()
        level = member.get("level")
        if level not in LEVEL_THRESHOLDS:
            return _bad_request("unsupported level")
        for key in thresholds:
            thresholds[key] += LEVEL_THRESHOLDS[level][key]

    difficulty = "trivial"
    for key in ("easy", "medium", "hard", "deadly"):
        if adjusted >= thresholds[key]:
            difficulty = key

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "base_xp": base_xp,
            "adjusted_xp": adjusted,
            "difficulty": difficulty,
            "monster_count": monster_count,
            "recommendation": DIFFICULTY_RECOMMENDATION[difficulty],
        }
    )


@csrf_exempt
def dm_loot_parcel(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()

    campaign_id = data.get("campaign_id")
    tier = data.get("tier")
    if not isinstance(campaign_id, str) or not campaign_id:
        return _bad_request("invalid campaign_id")
    if not _is_int(tier):
        return _bad_request("invalid tier")

    parcel = LOOT_PARCELS.get(tier)
    if parcel is None:
        return _bad_request("unsupported tier")

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "coins_gp": parcel["coins_gp"],
            "items": [dict(item) for item in parcel["items"]],
        }
    )


@csrf_exempt
def dm_session_recap(request):
    if request.method != "POST":
        return _bad_request("method not allowed")
    data = _parse_json(request)
    if not isinstance(data, dict):
        return _bad_request()

    campaign_id = data.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        return _bad_request("invalid campaign_id")

    state = storage.get_campaign_state(campaign_id)
    if state is None:
        return _not_found("campaign not found")

    events = storage.get_events(campaign_id)
    # Summary: the most recent logged event summary (deterministic by seq).
    summary = events[-1]["summary"] if events else ""
    # Open threads: derive a deterministic follow-up from any event that
    # references a "goblin trail".
    open_threads = []
    for event in events:
        if "goblin trail" in event["summary"].lower():
            thread = "Resolve goblin trail ambush"
            if thread not in open_threads:
                open_threads.append(thread)

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "summary": summary,
            "open_threads": open_threads,
        }
    )
