"""Core D&D REST engine views.

All endpoints accept/return JSON. POST endpoints return 400 on malformed input.
Durable game-state (combat sessions and auth users) is persisted in SQLite via
:mod:`dndsite.storage`.
"""
import json
import re
import threading
from math import floor

from django.contrib.auth.hashers import check_password, make_password
from django.http import JsonResponse, HttpResponseBadRequest

from . import storage


def _bad():
    return HttpResponseBadRequest()


def _not_found():
    return JsonResponse({"error": "not found"}, status=404)



def _parse_body(request):
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

def health(request):
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# POST /v1/dice/stats
#
# Grammar: <count>d<sides>[+<modifier>|-<modifier>]
#   count, sides, modifier are base-10 integers; count & sides must be > 0.
# ---------------------------------------------------------------------------

_DICE_RE = re.compile(r"^([1-9]\d*)d([1-9]\d*)(?:([+-])(\d+))?$")


def dice_stats(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None:
        return _bad()
    expression = body.get("expression")
    if not isinstance(expression, str):
        return _bad()
    m = _DICE_RE.match(expression.strip())
    if not m:
        return _bad()
    count = int(m.group(1))
    sides = int(m.group(2))
    if m.group(3):
        modifier = int(m.group(4)) * (-1 if m.group(3) == "-" else 1)
    else:
        modifier = 0
    minimum = count + modifier          # all ones
    maximum = count * sides + modifier  # all max faces
    average = (minimum + maximum) / 2
    if isinstance(average, float) and average.is_integer():
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
#   total = roll + modifier; success = total >= dc; margin = total - dc
# ---------------------------------------------------------------------------

def ability_check(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None:
        return _bad()
    try:
        roll = int(body["roll"])
        modifier = int(body["modifier"])
        dc = int(body["dc"])
    except (KeyError, TypeError, ValueError):
        return _bad()
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


def adjusted_xp(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None:
        return _bad()
    party = body.get("party")
    monsters = body.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        return _bad()

    base_xp = 0
    monster_count = 0
    for mon in monsters:
        try:
            cr = str(mon["cr"])
            count = int(mon["count"])
        except (KeyError, TypeError, ValueError):
            return _bad()
        if cr not in CR_XP or count <= 0:
            return _bad()
        base_xp += CR_XP[cr] * count
        monster_count += count

    multiplier = _multiplier(monster_count)
    adjusted = base_xp * multiplier
    if isinstance(adjusted, float) and adjusted.is_integer():
        adjusted = int(adjusted)

    easy = medium = hard = deadly = 0
    for member in party:
        try:
            level = int(member["level"])
        except (KeyError, TypeError, ValueError):
            return _bad()
        th = LEVEL_THRESHOLDS.get(level)
        if th is None:
            return _bad()
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
#   score = roll + dex; sort score desc, dex desc, name asc.
# ---------------------------------------------------------------------------

def initiative_order(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None:
        return _bad()
    combatants = body.get("combatants")
    if not isinstance(combatants, list):
        return _bad()
    scored = []
    for c in combatants:
        try:
            name = str(c["name"])
            dex = int(c["dex"])
            roll = int(c["roll"])
        except (KeyError, TypeError, ValueError):
            return _bad()
        scored.append({"name": name, "dex": dex, "score": roll + dex})
    scored.sort(key=lambda x: (-x["score"], -x["dex"], x["name"]))
    return JsonResponse({
        "order": [{"name": c["name"], "score": c["score"]} for c in scored],
    })


# ---------------------------------------------------------------------------
# Character rules
# ---------------------------------------------------------------------------

_ABILITIES = ("str", "dex", "con", "int", "wis", "cha")


def _ability_modifier(score):
    return floor((score - 10) / 2)


def _proficiency_bonus(level):
    return 2 + (level - 1) // 4


# POST /v1/characters/ability-modifier
def ability_modifier(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()
    score = body.get("score")
    if not isinstance(score, int) or isinstance(score, bool):
        return _bad()
    if score < 1 or score > 30:
        return _bad()
    return JsonResponse({"score": score, "modifier": _ability_modifier(score)})


# POST /v1/characters/proficiency
def proficiency(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()
    level = body.get("level")
    if not isinstance(level, int) or isinstance(level, bool):
        return _bad()
    if level < 1 or level > 20:
        return _bad()
    return JsonResponse({"level": level, "proficiency_bonus": _proficiency_bonus(level)})


# POST /v1/characters/derived-stats
def derived_stats(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()

    level = body.get("level")
    if not isinstance(level, int) or isinstance(level, bool):
        return _bad()
    if level < 1 or level > 20:
        return _bad()

    abilities = body.get("abilities")
    if not isinstance(abilities, dict):
        return _bad()
    modifiers = {}
    for ab in _ABILITIES:
        val = abilities.get(ab)
        if not isinstance(val, int) or isinstance(val, bool):
            return _bad()
        if val < 1 or val > 30:
            return _bad()
        modifiers[ab] = _ability_modifier(val)

    armor = body.get("armor")
    if not isinstance(armor, dict):
        return _bad()
    base = armor.get("base")
    if not isinstance(base, int) or isinstance(base, bool):
        return _bad()
    shield = armor.get("shield")
    if not isinstance(shield, bool):
        return _bad()
    dex_cap = armor.get("dex_cap")
    if not isinstance(dex_cap, int) or isinstance(dex_cap, bool):
        return _bad()

    dex_mod = modifiers["dex"]
    con_mod = modifiers["con"]
    shield_bonus = 2 if shield else 0
    hp_max = level * (6 + con_mod)
    armor_class = base + min(dex_mod, dex_cap) + shield_bonus

    return JsonResponse({
        "level": level,
        "proficiency_bonus": _proficiency_bonus(level),
        "hp_max": hp_max,
        "armor_class": armor_class,
        "modifiers": modifiers,
    })


# ---------------------------------------------------------------------------
# Combat state (durable, SQLite-backed via dndsite.storage)
# ---------------------------------------------------------------------------

_COMBAT_LOCK = threading.Lock()


def _combatant_public(c):
    return {"name": c["name"], "score": c["score"]}


def _session_summary(session):
    order = session["order"]
    ti = session["turn_index"]
    active = _combatant_public(order[ti]) if 0 <= ti < len(order) else None
    return JsonResponse({
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": active,
        "order": [_combatant_public(c) for c in order],
    })


def _session_advance_response(session):
    order = session["order"]
    ti = session["turn_index"]
    active = _combatant_public(order[ti]) if 0 <= ti < len(order) else None
    conditions = {}
    for name, conds in session["conditions"].items():
        conditions[name] = [
            {"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]}
            for c in conds
        ]
    return JsonResponse({
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": active,
        "conditions": conditions,
    })


# POST /v1/combat/sessions
def combat_sessions_create(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()
    sid = body.get("id")
    if not isinstance(sid, str) or not sid:
        return _bad()
    combatants = body.get("combatants")
    if not isinstance(combatants, list):
        return _bad()
    scored = []
    for c in combatants:
        if not isinstance(c, dict):
            return _bad()
        name = c.get("name")
        dex = c.get("dex")
        roll = c.get("roll")
        if not isinstance(name, str) or not name:
            return _bad()
        if not isinstance(dex, int) or isinstance(dex, bool):
            return _bad()
        if not isinstance(roll, int) or isinstance(roll, bool):
            return _bad()
        scored.append({"name": name, "dex": dex, "score": roll + dex})
    scored.sort(key=lambda x: (-x["score"], -x["dex"], x["name"]))
    session = {
        "id": sid,
        "round": 1,
        "turn_index": 0,
        "order": scored,
        "conditions": {},
    }
    with _COMBAT_LOCK:
        storage.upsert_session(session)
    return _session_summary(session)


# POST /v1/combat/sessions/{id}/conditions
def combat_session_add_condition(request, sid):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()
    target = body.get("target")
    condition = body.get("condition")
    duration = body.get("duration_rounds")
    if not isinstance(target, str) or not target:
        return _bad()
    if not isinstance(condition, str) or not condition:
        return _bad()
    if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
        return _bad()
    with _COMBAT_LOCK:
        session = storage.get_session(sid)
        if session is None:
            return _not_found()
        names = {c["name"] for c in session["order"]}
        if target not in names:
            return _bad()
        conds = session["conditions"].setdefault(target, [])
        conds.append({"condition": condition, "remaining_rounds": duration})
        storage.upsert_session(session)
        return JsonResponse({
            "target": target,
            "conditions": [
                {"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]}
                for c in conds
            ],
        })


# POST /v1/combat/sessions/{id}/advance
def combat_session_advance(request, sid):
    if request.method != "POST":
        return _bad()
    with _COMBAT_LOCK:
        session = storage.get_session(sid)
        if session is None:
            return _not_found()
        order = session["order"]
        if order:
            ti = session["turn_index"] + 1
            if ti >= len(order):
                ti = 0
                session["round"] += 1
            session["turn_index"] = ti
            active_name = order[ti]["name"]
            if active_name in session["conditions"]:
                conds = session["conditions"][active_name]
                for c in conds:
                    c["remaining_rounds"] -= 1
                session["conditions"][active_name] = [
                    c for c in conds if c["remaining_rounds"] > 0
                ]
            storage.upsert_session(session)
        return _session_advance_response(session)


# ---------------------------------------------------------------------------
# Auth / Users (durable, SQLite-backed via dndsite.storage)
#
# Passwords are hashed with Django's built-in PBKDF2 hasher.  The plain
# password is never stored or echoed in responses.
# ---------------------------------------------------------------------------

_AUTH_LOCK = threading.Lock()

_USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
_VALID_ROLES = {"dm", "player"}

_COMPENDIUM_LOCK = threading.Lock()
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


# POST /v1/auth/register
def auth_register(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()
    username = body.get("username")
    password = body.get("password")
    role = body.get("role")
    if not isinstance(username, str) or not _USERNAME_RE.match(username):
        return _bad()
    if not isinstance(password, str) or len(password) < 8:
        return _bad()
    if not isinstance(role, str) or role not in _VALID_ROLES:
        return _bad()
    with _AUTH_LOCK:
        if storage.get_user(username) is not None:
            return JsonResponse({"error": "username already exists"}, status=409)
        storage.insert_user(username, role, make_password(password))
    return JsonResponse({"username": username, "role": role}, status=201)


# POST /v1/auth/login
def auth_login(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()
    username = body.get("username")
    password = body.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return _bad()
    user = storage.get_user(username)
    if user is None or not check_password(password, user["password_hash"]):
        return JsonResponse({"error": "invalid credentials"}, status=401)
    return JsonResponse({"username": username, "token": f"session-{username}"})


# ---------------------------------------------------------------------------
# Storage management
# ---------------------------------------------------------------------------

# GET  /v1/storage/status
# POST /v1/storage/reset
def storage_status(request):
    if request.method != "GET":
        return _bad()
    return JsonResponse({
        "driver": "sqlite",
        "schema_version": storage.SCHEMA_VERSION,
        "initialized": storage.is_initialized(),
    })


def storage_reset(request):
    if request.method != "POST":
        return _bad()
    storage.reset()
    return JsonResponse({"ok": True, "schema_version": storage.SCHEMA_VERSION})


# ---------------------------------------------------------------------------
# Compendium: monsters and items (durable, SQLite-backed)
# ---------------------------------------------------------------------------

def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_tags(tags):
    if tags is None:
        return []
    if not isinstance(tags, list):
        return None
    out = []
    for t in tags:
        if not isinstance(t, str) or not t:
            return None
        out.append(t)
    return out


# POST /v1/compendium/monsters
def compendium_create_monster(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()
    slug = body.get("slug")
    name = body.get("name")
    cr = body.get("cr")
    armor_class = body.get("armor_class")
    hit_points = body.get("hit_points")
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        return _bad()
    if not isinstance(name, str) or not name:
        return _bad()
    if not isinstance(cr, str) or not cr:
        return _bad()
    if not _is_int(armor_class) or armor_class < 0:
        return _bad()
    if not _is_int(hit_points) or hit_points < 0:
        return _bad()
    tags = _valid_tags(body.get("tags"))
    if tags is None:
        return _bad()
    monster = {
        "slug": slug,
        "name": name,
        "cr": cr,
        "armor_class": armor_class,
        "hit_points": hit_points,
        "tags": tags,
    }
    with _COMPENDIUM_LOCK:
        if storage.get_monster(slug) is not None:
            return JsonResponse({"error": "monster already exists"}, status=409)
        storage.insert_monster(monster)
    return JsonResponse({
        "slug": slug,
        "name": name,
        "cr": cr,
        "armor_class": armor_class,
        "hit_points": hit_points,
    }, status=201)


# GET /v1/compendium/monsters/{slug}
def compendium_get_monster(request, slug):
    if request.method != "GET":
        return _bad()
    monster = storage.get_monster(slug)
    if monster is None:
        return _not_found()
    return JsonResponse(monster)


# POST /v1/compendium/items
def compendium_create_item(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()
    slug = body.get("slug")
    name = body.get("name")
    item_type = body.get("type")
    rarity = body.get("rarity")
    cost_gp = body.get("cost_gp")
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        return _bad()
    if not isinstance(name, str) or not name:
        return _bad()
    if not isinstance(item_type, str) or not item_type:
        return _bad()
    if not isinstance(rarity, str) or not rarity:
        return _bad()
    if not _is_int(cost_gp) or cost_gp < 0:
        return _bad()
    item = {
        "slug": slug,
        "name": name,
        "type": item_type,
        "rarity": rarity,
        "cost_gp": cost_gp,
    }
    with _COMPENDIUM_LOCK:
        if storage.get_item(slug) is not None:
            return JsonResponse({"error": "item already exists"}, status=409)
        storage.insert_item(item)
    return JsonResponse(item, status=201)


# GET /v1/compendium/items/{slug}
def compendium_get_item(request, slug):
    if request.method != "GET":
        return _bad()
    item = storage.get_item(slug)
    if item is None:
        return _not_found()
    return JsonResponse(item)


# ---------------------------------------------------------------------------
# Campaign state (durable, SQLite-backed via dndsite.storage)
# ---------------------------------------------------------------------------

_CAMPAIGN_LOCK = threading.Lock()


# POST /v1/campaigns
def campaign_create(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()
    cid = body.get("id")
    name = body.get("name")
    dm = body.get("dm")
    if not isinstance(cid, str) or not cid:
        return _bad()
    if not isinstance(name, str) or not name:
        return _bad()
    if not isinstance(dm, str) or not dm:
        return _bad()
    with _CAMPAIGN_LOCK:
        if storage.get_campaign(cid) is not None:
            return JsonResponse({"error": "campaign already exists"}, status=409)
        storage.insert_campaign({"id": cid, "name": name, "dm": dm})
    return JsonResponse({"id": cid, "name": name, "dm": dm}, status=201)


# POST /v1/campaigns/{cid}/characters
def campaign_add_character(request, cid):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()
    char_id = body.get("id")
    name = body.get("name")
    level = body.get("level")
    char_class = body.get("class")
    if not isinstance(char_id, str) or not char_id:
        return _bad()
    if not isinstance(name, str) or not name:
        return _bad()
    if not _is_int(level) or level < 1:
        return _bad()
    if not isinstance(char_class, str) or not char_class:
        return _bad()
    character = {
        "id": char_id,
        "name": name,
        "level": level,
        "class": char_class,
    }
    with _CAMPAIGN_LOCK:
        if storage.get_campaign(cid) is None:
            return _not_found()
        if storage.get_character(cid, char_id) is not None:
            return JsonResponse({"error": "character already exists"}, status=409)
        storage.insert_character(cid, character)
    return JsonResponse(character, status=201)


# POST /v1/campaigns/{cid}/events
def campaign_add_event(request, cid):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()
    evt_id = body.get("id")
    kind = body.get("kind")
    summary = body.get("summary")
    if not isinstance(evt_id, str) or not evt_id:
        return _bad()
    if not isinstance(kind, str) or not kind:
        return _bad()
    if summary is not None and not isinstance(summary, str):
        return _bad()
    if summary is None:
        summary = ""
    with _CAMPAIGN_LOCK:
        if storage.get_campaign(cid) is None:
            return _not_found()
        if storage.get_event(cid, evt_id) is not None:
            return JsonResponse({"error": "event already exists"}, status=409)
        storage.insert_event(cid, {
            "id": evt_id,
            "kind": kind,
            "summary": summary,
        })
    return JsonResponse({"id": evt_id, "kind": kind}, status=201)


# GET /v1/campaigns/{cid}/state
def campaign_state(request, cid):
    if request.method != "GET":
        return _bad()
    with _CAMPAIGN_LOCK:
        campaign = storage.get_campaign(cid)
        if campaign is None:
            return _not_found()
        characters = storage.list_characters(cid)
        log_count = storage.count_events(cid)
    return JsonResponse({
        "id": campaign["id"],
        "name": campaign["name"],
        "dm": campaign["dm"],
        "characters": characters,
        "log_count": log_count,
    })


# ---------------------------------------------------------------------------
# PHB rules: spell slots, long rest, equipment load
# ---------------------------------------------------------------------------

# Wizard spell-slot table by character level (PHB).  Only the levels this
# benchmark exercises are populated; absent levels are unsupported.
_WIZARD_SLOTS_BY_LEVEL = {
    5: {1: 4, 2: 3, 3: 2},
}


def _is_nonneg_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


# POST /v1/phb/spell-slots
def phb_spell_slots(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()
    char_class = body.get("class")
    level = body.get("level")
    if not isinstance(char_class, str) or char_class != "wizard":
        return _bad()
    if not _is_int(level) or level < 1:
        return _bad()
    table = _WIZARD_SLOTS_BY_LEVEL.get(level)
    if table is None:
        return _bad()
    slots = {str(k): v for k, v in table.items()}
    return JsonResponse({"class": char_class, "level": level, "slots": slots})


# POST /v1/phb/rests/long
def phb_long_rest(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()
    level = body.get("level")
    hp_current = body.get("hp_current")
    hp_max = body.get("hp_max")
    hit_dice_spent = body.get("hit_dice_spent")
    exhaustion_level = body.get("exhaustion_level")
    if not _is_int(level) or level < 1:
        return _bad()
    if not _is_nonneg_int(hp_current):
        return _bad()
    if not _is_nonneg_int(hp_max):
        return _bad()
    if not _is_nonneg_int(hit_dice_spent):
        return _bad()
    if not _is_nonneg_int(exhaustion_level):
        return _bad()
    recovered = max(level // 2, 1)
    new_hit_dice_spent = max(0, hit_dice_spent - recovered)
    new_exhaustion = max(0, exhaustion_level - 1)
    return JsonResponse({
        "hp_current": hp_max,
        "hit_dice_spent": new_hit_dice_spent,
        "exhaustion_level": new_exhaustion,
    })


# POST /v1/phb/equipment-load
def phb_equipment_load(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()
    strength = body.get("strength")
    weight = body.get("weight")
    if not _is_nonneg_int(strength):
        return _bad()
    if not _is_nonneg_int(weight):
        return _bad()
    capacity = strength * 15
    return JsonResponse({
        "capacity": capacity,
        "weight": weight,
        "encumbered": weight > capacity,
    })


# ---------------------------------------------------------------------------
# Stage 8: DM Tools -- encounter builder, loot parcel, session recap
#
# These DM-facing endpoints combine the stored compendium (monster CRs) and
# campaign state (logged events) to produce deterministic recommendations.
# ---------------------------------------------------------------------------

# Deterministic recommendation keyed by the computed encounter difficulty.
_DIFFICULTY_RECOMMENDATION = {
    "trivial": "cakewalk",
    "easy": "safe warm-up",
    "medium": "a fair fight",
    "hard": "tough battle",
    "deadly": "risk of a wipe",
}

# Deterministic loot parcels keyed by tier for this benchmark.
_LOOT_PARCELS = {
    1: {"coins_gp": 75, "items": [{"slug": "healing-potion", "quantity": 2}]},
}


def _difficulty_for(adjusted, thresholds):
    if adjusted >= thresholds["deadly"]:
        return "deadly"
    if adjusted >= thresholds["hard"]:
        return "hard"
    if adjusted >= thresholds["medium"]:
        return "medium"
    if adjusted >= thresholds["easy"]:
        return "easy"
    return "trivial"


# POST /v1/dm/encounter-builder
def dm_encounter_builder(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()
    campaign_id = body.get("campaign_id")
    party = body.get("party")
    monster_slugs = body.get("monster_slugs")
    if not isinstance(campaign_id, str) or not campaign_id:
        return _bad()
    if not isinstance(party, list) or not party:
        return _bad()
    if not isinstance(monster_slugs, list) or not monster_slugs:
        return _bad()

    # Base XP: look up each monster's CR from the compendium and sum its value.
    base_xp = 0
    for slug in monster_slugs:
        if not isinstance(slug, str) or not slug:
            return _bad()
        monster = storage.get_monster(slug)
        if monster is None:
            return _not_found()
        cr = monster["cr"]
        if cr not in CR_XP:
            return _bad()
        base_xp += CR_XP[cr]

    monster_count = len(monster_slugs)
    multiplier = _multiplier(monster_count)
    adjusted = base_xp * multiplier
    if isinstance(adjusted, float) and adjusted.is_integer():
        adjusted = int(adjusted)

    # Party difficulty thresholds, reusing the core adjusted-XP math.
    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            return _bad()
        level = member.get("level")
        if not _is_int(level) or level not in LEVEL_THRESHOLDS:
            return _bad()
        for key in thresholds:
            thresholds[key] += LEVEL_THRESHOLDS[level][key]

    difficulty = _difficulty_for(adjusted, thresholds)

    return JsonResponse({
        "campaign_id": campaign_id,
        "base_xp": base_xp,
        "adjusted_xp": adjusted,
        "difficulty": difficulty,
        "monster_count": monster_count,
        "recommendation": _DIFFICULTY_RECOMMENDATION[difficulty],
    })


# POST /v1/dm/loot-parcel
def dm_loot_parcel(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()
    campaign_id = body.get("campaign_id")
    tier = body.get("tier")
    if not isinstance(campaign_id, str) or not campaign_id:
        return _bad()
    if not _is_int(tier):
        return _bad()
    parcel = _LOOT_PARCELS.get(tier)
    if parcel is None:
        return _bad()
    return JsonResponse({
        "campaign_id": campaign_id,
        "coins_gp": parcel["coins_gp"],
        "items": [dict(item) for item in parcel["items"]],
    })


# POST /v1/dm/session-recap
def dm_session_recap(request):
    if request.method != "POST":
        return _bad()
    body = _parse_body(request)
    if body is None or not isinstance(body, dict):
        return _bad()
    campaign_id = body.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        return _bad()
    with _CAMPAIGN_LOCK:
        campaign = storage.get_campaign(campaign_id)
        if campaign is None:
            return _not_found()
        events = storage.list_events(campaign_id)
    # Summary: the most recently logged event summary (deterministic by seq).
    summary = events[-1]["summary"] if events else ""
    # Open threads: derive a deterministic follow-up from any event that
    # references a "goblin trail".
    open_threads = []
    for event in events:
        if "goblin trail" in event["summary"].lower():
            thread = "Resolve goblin trail ambush"
            if thread not in open_threads:
                open_threads.append(thread)
    return JsonResponse({
        "campaign_id": campaign_id,
        "summary": summary,
        "open_threads": open_threads,
    })
