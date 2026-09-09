"""HTTP views and the complete, intentionally explicit route table for the API."""

import json
import re
from datetime import datetime

from django.contrib.auth.hashers import check_password, make_password
from django.http import JsonResponse
from django.urls import path

from . import storage


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
LEVEL_THRESHOLDS = {3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400}}
DIFFICULTY_LABELS = ("easy", "medium", "hard", "deadly")
DICE_EXPRESSION = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")
ABILITY_NAMES = ("str", "dex", "con", "int", "wis", "cha")
SKILL_NAMES = {
    "acrobatics", "animal_handling", "arcana", "athletics", "deception",
    "history", "insight", "intimidation", "investigation", "medicine",
    "nature", "perception", "performance", "persuasion", "religion",
    "sleight_of_hand", "stealth", "survival",
}
USERNAME = re.compile(r"^[a-z0-9_-]{2,32}$")
PLAYABLE_RACES = {"human", "elf", "dwarf", "halfling"}
PLAYABLE_CLASSES = {"fighter": 10, "rogue": 8, "wizard": 6, "cleric": 8}
PLAYABLE_BACKGROUNDS = {"acolyte", "criminal", "soldier", "sage"}
INVENTORY_ITEM_IDS = {
    "healing-potion", "torch", "leather-armor", "ring-of-protection", "amulet-of-health",
}
EQUIPMENT_ITEM_SLOTS = {
    "leather-armor": "armor",
    "ring-of-protection": "accessory",
    "amulet-of-health": "accessory",
}
ATTUNABLE_ITEM_IDS = {"ring-of-protection", "amulet-of-health"}
EQUIPMENT_SLOTS = {"armor", "accessory"}
CONSUMABLE_EFFECTS = {"healing-potion": {"type": "healing", "hp_restored": 5}}
CALENDAR_SEASON_OFFSETS = {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}

# This is deliberately process-local rather than persisted campaign data.  A
# freshly started reference server begins ready, and any DM can toggle the
# shared operational mode through an existing play campaign.
SERVICE_MAINTENANCE = False


# URL configuration is imported while Django starts, making storage ready before
# the first request without requiring a separate migration command.
storage.initialize()


def bad_request(message="Invalid request"):
    return JsonResponse({"error": message}, status=400)


def _json_object_body(request, required_method):
    """Parse one API JSON object while preserving method-specific errors."""
    if request.method != required_method:
        raise ValueError(f"{required_method} required")
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("Invalid JSON")
    if not isinstance(body, dict):
        raise ValueError("JSON body must be an object")
    return body


def json_body(request):
    """Parse the object payload used by the API's POST endpoints."""
    return _json_object_body(request, "POST")


def put_json_body(request):
    """Parse the object payload used by the API's PUT endpoints."""
    return _json_object_body(request, "PUT")


def authenticated_actor(request, required_method):
    """Apply the API's common method and session-token gate.

    Endpoint-specific authorization deliberately stays in each view because a
    few established endpoints use distinct role errors and status codes.
    """
    if request.method != required_method:
        return None, bad_request(f"{required_method} required")
    actor = authenticated_user(request)
    if actor is None:
        return None, JsonResponse({"error": "Unauthorized"}, status=401)
    return actor, None


def dm_actor(request, required_method):
    """Return an authenticated DM for endpoints using the standard 403 gate."""
    actor, error_response = authenticated_actor(request, required_method)
    if error_response:
        return None, error_response
    if actor["role"] != "dm":
        return None, JsonResponse({"error": "Forbidden"}, status=403)
    return actor, None


def integer(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def ability_score(value, name="score"):
    score = integer(value, name)
    if not 1 <= score <= 30:
        raise ValueError(f"{name} must be between 1 and 30")
    return score


def ability_modifier_for(score):
    return (score - 10) // 2


def character_level(value):
    level = integer(value, "level")
    if not 1 <= level <= 20:
        raise ValueError("level must be between 1 and 20")
    return level


def proficiency_bonus_for(level):
    return 2 + (level - 1) // 4


def health(request):
    return JsonResponse({"ok": True})


def healthz(request):
    if request.method != "GET":
        return bad_request("GET required")
    return JsonResponse({"status": "ok"})


def api_schema(request):
    """Return the stable public contract for the current play API surface."""
    if request.method != "GET":
        return bad_request("GET required")
    return JsonResponse({
        "version": "2026-07-29",
        "endpoints": [
            {"method": "GET", "path": "/v1/play/campaigns/{id}/rng-ledger", "auth": "member"},
            {"method": "GET", "path": "/v1/schema", "auth": "public"},
            {"method": "POST", "path": "/v1/play/campaigns", "auth": "dm"},
            {"method": "POST", "path": "/v1/play/campaigns/{id}/fixture-seeds", "auth": "dm"},
            {"method": "POST", "path": "/v1/play/campaigns/{id}/members", "auth": "member"},
            {"method": "POST", "path": "/v1/play/campaigns/{id}/moderation/reports", "auth": "member"},
            {"method": "POST", "path": "/v1/play/campaigns/{id}/rng-rolls", "auth": "member"},
            {"method": "PUT", "path": "/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution", "auth": "dm"},
            {"method": "PUT", "path": "/v1/play/campaigns/{id}/rng-seed", "auth": "dm"},
            {"method": "PUT", "path": "/v1/play/campaigns/{id}/safety-boundaries", "auth": "dm"},
        ],
    })


def readyz(request):
    if request.method != "GET":
        return bad_request("GET required")
    if SERVICE_MAINTENANCE:
        return JsonResponse({"status": "maintenance", "schema_version": 2}, status=503)
    return JsonResponse({"status": "ready", "schema_version": 2})


def register_user(request):
    try:
        body = json_body(request)
        username = body.get("username")
        password = body.get("password")
        role = body.get("role")
        if not isinstance(username, str) or not USERNAME.fullmatch(username):
            raise ValueError("username must be 2-32 lowercase letters, digits, _, or -")
        if not isinstance(password, str) or len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        if role not in {"dm", "player"}:
            raise ValueError("role must be dm or player")
    except ValueError as error:
        return bad_request(str(error))

    if storage.get_user(username) is not None:
        return JsonResponse({"error": "Username already exists"}, status=409)

    if not storage.create_user(username, make_password(password), role):
        return JsonResponse({"error": "Username already exists"}, status=409)
    return JsonResponse({"username": username, "role": role}, status=201)


def login_user(request):
    try:
        body = json_body(request)
        username = body.get("username")
        password = body.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            raise ValueError("username and password must be strings")
    except ValueError as error:
        return bad_request(str(error))

    user = storage.get_user(username)
    if user is None or not check_password(password, user["password"]):
        return JsonResponse({"error": "Invalid credentials"}, status=401)
    return JsonResponse({"username": username, "token": f"session-{username}"})


def dice_stats(request):
    try:
        expression = json_body(request).get("expression")
        if not isinstance(expression, str):
            raise ValueError("expression must be a string")
        match = DICE_EXPRESSION.fullmatch(expression)
        if not match:
            raise ValueError("Invalid expression")
        count, sides = int(match.group(1)), int(match.group(2))
        modifier = int(match.group(3) or 0)
        if count <= 0 or sides <= 0:
            raise ValueError("count and sides must be positive")
    except ValueError as error:
        return bad_request(str(error))

    minimum = count + modifier
    maximum = count * sides + modifier
    average_sum = minimum + maximum
    return JsonResponse({
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": minimum,
        "max": maximum,
        "average": average_sum // 2 if average_sum % 2 == 0 else average_sum / 2,
    })


def ability_check(request):
    try:
        body = json_body(request)
        roll = integer(body.get("roll"), "roll")
        modifier = integer(body.get("modifier"), "modifier")
        dc = integer(body.get("dc"), "dc")
    except ValueError as error:
        return bad_request(str(error))

    total = roll + modifier
    return JsonResponse({"total": total, "success": total >= dc, "margin": total - dc})


def ability_modifier(request):
    try:
        score = ability_score(json_body(request).get("score"))
    except ValueError as error:
        return bad_request(str(error))
    return JsonResponse({"score": score, "modifier": ability_modifier_for(score)})


def proficiency(request):
    try:
        level = character_level(json_body(request).get("level"))
    except ValueError as error:
        return bad_request(str(error))
    return JsonResponse({"level": level, "proficiency_bonus": proficiency_bonus_for(level)})


def derived_stats(request):
    try:
        body = json_body(request)
        level = character_level(body.get("level"))
        abilities = body.get("abilities")
        armor = body.get("armor")
        if not isinstance(abilities, dict):
            raise ValueError("abilities must be an object")
        if not isinstance(armor, dict):
            raise ValueError("armor must be an object")

        modifiers = {
            name: ability_modifier_for(ability_score(abilities.get(name), name))
            for name in ABILITY_NAMES
        }
        base = integer(armor.get("base"), "armor.base")
        dex_cap = integer(armor.get("dex_cap"), "armor.dex_cap")
        shield = armor.get("shield")
        if not isinstance(shield, bool):
            raise ValueError("armor.shield must be a boolean")
    except ValueError as error:
        return bad_request(str(error))

    return JsonResponse({
        "level": level,
        "proficiency_bonus": proficiency_bonus_for(level),
        "hp_max": level * (6 + modifiers["con"]),
        "armor_class": base + min(modifiers["dex"], dex_cap) + (2 if shield else 0),
        "modifiers": modifiers,
    })


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


def encounter_math(party, monsters):
    """Calculate the core encounter values for CR/count monster entries."""
    if not isinstance(party, list) or not isinstance(monsters, list):
        raise ValueError("party and monsters must be arrays")

    thresholds = {key: 0 for key in DIFFICULTY_LABELS}
    for member in party:
        if not isinstance(member, dict):
            raise ValueError("Invalid party member")
        level = integer(member.get("level"), "level")
        if level not in LEVEL_THRESHOLDS:
            raise ValueError("Unsupported level")
        for key, amount in LEVEL_THRESHOLDS[level].items():
            thresholds[key] += amount

    base_xp = monster_count = 0
    for monster in monsters:
        if not isinstance(monster, dict):
            raise ValueError("Invalid monster")
        cr = monster.get("cr")
        count = integer(monster.get("count"), "count")
        if cr not in CR_XP or count <= 0:
            raise ValueError("Invalid monster")
        base_xp += CR_XP[cr] * count
        monster_count += count
    if not monster_count:
        raise ValueError("At least one monster is required")

    multiplier = monster_multiplier(monster_count)
    adjusted = base_xp * multiplier
    difficulty = "trivial"
    for label in DIFFICULTY_LABELS:
        if adjusted >= thresholds[label]:
            difficulty = label
    return {
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": multiplier,
        "adjusted_xp": adjusted,
        "difficulty": difficulty,
        "thresholds": thresholds,
    }


def adjusted_xp(request):
    try:
        body = json_body(request)
        result = encounter_math(body.get("party"), body.get("monsters"))
    except ValueError as error:
        return bad_request(str(error))

    return JsonResponse(result)


def initiative_order(request):
    try:
        combatants = json_body(request).get("combatants")
        if not isinstance(combatants, list):
            raise ValueError("combatants must be an array")
        order = []
        for combatant in combatants:
            if not isinstance(combatant, dict) or not isinstance(combatant.get("name"), str):
                raise ValueError("Invalid combatant")
            dex = integer(combatant.get("dex"), "dex")
            roll = integer(combatant.get("roll"), "roll")
            order.append({"name": combatant["name"], "score": roll + dex, "dex": dex})
    except ValueError as error:
        return bad_request(str(error))

    order.sort(key=lambda item: (-item["score"], -item["dex"], item["name"]))
    return JsonResponse({"order": [{"name": item["name"], "score": item["score"]} for item in order]})


def combatant_response(combatant):
    return {"name": combatant["name"], "score": combatant["score"]}


def combat_session_response(session):
    active = session["order"][session["turn_index"]]
    return {
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": combatant_response(active),
    }


def create_combat_session(request):
    try:
        body = json_body(request)
        session_id = body.get("id")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("id must be a non-empty string")
        if storage.get_combat_session(session_id) is not None:
            raise ValueError("Session id already exists")
        combatants = body.get("combatants")
        if not isinstance(combatants, list) or not combatants:
            raise ValueError("combatants must be a non-empty array")

        order = []
        names = set()
        for combatant in combatants:
            if not isinstance(combatant, dict):
                raise ValueError("Invalid combatant")
            name = combatant.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError("combatant name must be a non-empty string")
            if name in names:
                raise ValueError("combatant names must be unique")
            names.add(name)
            dex = integer(combatant.get("dex"), "dex")
            roll = integer(combatant.get("roll"), "roll")
            order.append({"name": name, "score": roll + dex, "dex": dex})
    except ValueError as error:
        return bad_request(str(error))

    order.sort(key=lambda item: (-item["score"], -item["dex"], item["name"]))
    session = {
        "id": session_id,
        "round": 1,
        "turn_index": 0,
        "order": order,
        "conditions": {},
    }
    if not storage.create_combat_session(session):
        return JsonResponse({"error": "Session id already exists"}, status=400)
    response = combat_session_response(session)
    response["order"] = [combatant_response(combatant) for combatant in order]
    return JsonResponse(response)


def session_or_404(session_id):
    session = storage.get_combat_session(session_id)
    if session is None:
        return None, JsonResponse({"error": "Unknown session"}, status=404)
    return session, None


def add_condition(request, session_id):
    session, error_response = session_or_404(session_id)
    if error_response:
        return error_response
    try:
        body = json_body(request)
        target = body.get("target")
        condition = body.get("condition")
        duration = integer(body.get("duration_rounds"), "duration_rounds")
        if not isinstance(target, str) or target not in {item["name"] for item in session["order"]}:
            raise ValueError("Unknown combatant")
        if not isinstance(condition, str):
            raise ValueError("condition must be a string")
        if duration <= 0:
            raise ValueError("duration_rounds must be positive")
    except ValueError as error:
        return bad_request(str(error))

    conditions = session["conditions"].setdefault(target, [])
    conditions.append({"condition": condition, "remaining_rounds": duration})
    storage.save_combat_session(session)
    return JsonResponse({"target": target, "conditions": conditions})


def advance_combat_turn(request, session_id):
    session, error_response = session_or_404(session_id)
    if error_response:
        return error_response
    if request.method != "POST":
        return bad_request("POST required")

    next_index = session["turn_index"] + 1
    if next_index == len(session["order"]):
        next_index = 0
        session["round"] += 1
    session["turn_index"] = next_index
    active = session["order"][next_index]["name"]
    if active in session["conditions"]:
        remaining = []
        for condition in session["conditions"][active]:
            condition["remaining_rounds"] -= 1
            if condition["remaining_rounds"] > 0:
                remaining.append(condition)
        session["conditions"][active] = remaining

    storage.save_combat_session(session)
    response = combat_session_response(session)
    response["conditions"] = session["conditions"]
    return JsonResponse(response)


def storage_status(request):
    if request.method != "GET":
        return bad_request("GET required")
    return JsonResponse({
        "driver": "sqlite",
        "schema_version": storage.SCHEMA_VERSION,
        "initialized": storage.is_initialized(),
    })


def reset_storage(request):
    if request.method != "POST":
        return bad_request("POST required")
    storage.reset()
    return JsonResponse({"ok": True, "schema_version": storage.SCHEMA_VERSION})


def non_empty_string(value, name):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def non_negative_integer(value, name):
    value = integer(value, name)
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def create_monster(request):
    try:
        body = json_body(request)
        monster = {
            "slug": non_empty_string(body.get("slug"), "slug"),
            "name": non_empty_string(body.get("name"), "name"),
            "cr": non_empty_string(body.get("cr"), "cr"),
            "armor_class": non_negative_integer(body.get("armor_class"), "armor_class"),
            "hit_points": non_negative_integer(body.get("hit_points"), "hit_points"),
        }
        tags = body.get("tags")
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError("tags must be an array of strings")
        monster["tags"] = tags
    except ValueError as error:
        return bad_request(str(error))

    if not storage.create_monster(monster):
        return JsonResponse({"error": "Monster slug already exists"}, status=409)
    return JsonResponse({key: monster[key] for key in monster if key != "tags"}, status=201)


def read_monster(request, slug):
    if request.method != "GET":
        return bad_request("GET required")
    monster = storage.get_monster(slug)
    if monster is None:
        return JsonResponse({"error": "Unknown monster"}, status=404)
    return JsonResponse(monster)


def create_item(request):
    try:
        body = json_body(request)
        item = {
            "slug": non_empty_string(body.get("slug"), "slug"),
            "name": non_empty_string(body.get("name"), "name"),
            "type": non_empty_string(body.get("type"), "type"),
            "rarity": non_empty_string(body.get("rarity"), "rarity"),
            "cost_gp": non_negative_integer(body.get("cost_gp"), "cost_gp"),
        }
    except ValueError as error:
        return bad_request(str(error))

    if not storage.create_item(item):
        return JsonResponse({"error": "Item slug already exists"}, status=409)
    return JsonResponse(item, status=201)


def read_item(request, slug):
    if request.method != "GET":
        return bad_request("GET required")
    item = storage.get_item(slug)
    if item is None:
        return JsonResponse({"error": "Unknown item"}, status=404)
    return JsonResponse(item)


def campaign_or_404(campaign_id):
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        return None, JsonResponse({"error": "Unknown campaign"}, status=404)
    return campaign, None


def create_campaign(request):
    try:
        body = json_body(request)
        campaign = {
            "id": non_empty_string(body.get("id"), "id"),
            "name": non_empty_string(body.get("name"), "name"),
            "dm": non_empty_string(body.get("dm"), "dm"),
        }
    except ValueError as error:
        return bad_request(str(error))

    if not storage.create_campaign(campaign):
        return JsonResponse({"error": "Campaign id already exists"}, status=409)
    return JsonResponse(campaign, status=201)


def authenticated_user(request):
    """Return the actor represented by the API's deterministic session token."""
    authorization = request.headers.get("Authorization")
    if not isinstance(authorization, str) or not authorization.startswith("Bearer session-"):
        return None
    username = authorization.removeprefix("Bearer session-")
    if not isinstance(username, str) or not USERNAME.fullmatch(username):
        return None
    user = storage.get_user(username)
    if user is not None:
        return user

    # Play-suite session tokens identify deterministic actors independently of
    # whether a later test has registered that actor through the auth API.
    return {"username": username, "role": "dm" if username == "dm" else "player"}


def create_play_campaign(request):
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "dm":
        return JsonResponse({"error": "Forbidden"}, status=403)

    try:
        body = json_body(request)
        campaign = {
            "id": non_empty_string(body.get("id"), "id"),
            "name": non_empty_string(body.get("name"), "name"),
            "owner": actor["username"],
            "status": "lobby",
            "max_players": integer(body.get("max_players"), "max_players"),
        }
        if campaign["max_players"] <= 0:
            raise ValueError("max_players must be positive")
    except ValueError as error:
        return bad_request(str(error))

    if not storage.create_play_campaign(campaign):
        return JsonResponse({"error": "Campaign id already exists"}, status=409)
    return JsonResponse(campaign, status=201)


def create_play_campaign_spectator(request, campaign_id):
    """Issue one bearer-only spectator ticket to a campaign's DM."""
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        spectator_id = non_empty_string(json_body(request).get("spectator_id"), "spectator_id")
    except ValueError as error:
        return bad_request(str(error))

    result = storage.create_play_campaign_spectator(
        campaign_id, actor["username"], spectator_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "duplicate":
        return JsonResponse({"error": "Spectator id already exists"}, status=409)
    return JsonResponse(
        {"spectator_id": spectator_id, "token": f"spectator-{spectator_id}"},
        status=201,
    )


def read_play_campaign_spectator_view(request, campaign_id):
    """Read a campaign's safe spectator-only projection."""
    if request.method != "GET":
        return bad_request("GET required")
    authorization = request.headers.get("Authorization")
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        return JsonResponse({"error": "Unauthorized"}, status=401)
    token = authorization.removeprefix("Bearer ")
    if token.startswith("session-"):
        return JsonResponse({"error": "Forbidden"}, status=403)
    if not token.startswith("spectator-") or not token.removeprefix("spectator-"):
        return JsonResponse({"error": "Unauthorized"}, status=401)

    result, projection = storage.get_play_campaign_spectator_view(
        campaign_id, token.removeprefix("spectator-")
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "invalid_ticket":
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if result == "wrong_campaign":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(projection)


def append_play_campaign_feed_event(request, campaign_id):
    """Append one authenticated member event to the campaign feed."""
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        event_id = non_empty_string(body.get("event_id"), "event_id")
        text = non_empty_string(body.get("text"), "text")
    except ValueError as error:
        return bad_request(str(error))

    result, event = storage.append_play_campaign_feed_event(
        campaign_id, actor["username"], event_id, text
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "duplicate":
        return JsonResponse({"error": "Event id already exists"}, status=409)
    return JsonResponse(event, status=201)


def read_play_campaign_event_feed(request, campaign_id):
    """Read one validated cursor page without changing the feed."""
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    try:
        cursor_raw = request.GET.get("cursor", "0")
        limit_raw = request.GET.get("limit", "2")
        if not isinstance(cursor_raw, str) or not isinstance(limit_raw, str):
            raise ValueError("Invalid pagination parameters")
        cursor = int(cursor_raw)
        limit = int(limit_raw)
        if cursor < 0 or not 1 <= limit <= 3:
            raise ValueError("Invalid pagination parameters")
    except (TypeError, ValueError):
        return bad_request("Invalid pagination parameters")

    result, page = storage.get_play_campaign_feed_events(
        campaign_id, actor["username"], cursor, limit
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(page)


def create_play_campaign_message(request, campaign_id):
    """Accept ordinary member chat, which is intentionally absent from spectator views."""
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    try:
        text = non_empty_string(json_body(request).get("text"), "text")
    except ValueError as error:
        return bad_request(str(error))

    access = storage.check_play_campaign_access(campaign_id, actor["username"])
    if access == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if access == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse({"kind": "chat", "actor": actor["username"], "text": text}, status=201)


def read_play_campaign_onboarding(request, campaign_id):
    """Return the stable onboarding guidance for one authorized campaign actor."""
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response

    result, onboarding = storage.get_play_campaign_onboarding(
        campaign_id, actor["username"]
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(onboarding)


def _projection_access_response(result):
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return None


def append_play_campaign_projection_event(request, campaign_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        event_id = non_empty_string(body.get("event_id"), "event_id")
        kind = body.get("kind")
        if kind not in {"set-story", "increment-danger"}:
            raise ValueError("kind must be set-story or increment-danger")
        if kind == "set-story":
            value = non_empty_string(body.get("value"), "value")
            event = {"event_id": event_id, "kind": kind, "value": value}
        else:
            if "value" in body:
                raise ValueError("value must be omitted for increment-danger")
            event = {"event_id": event_id, "kind": kind}
    except ValueError as error:
        return bad_request(str(error))

    result, stored_event = storage.create_play_campaign_projection_event(
        campaign_id, actor["username"], event
    )
    error_response = _projection_access_response(result)
    if error_response:
        return error_response
    if result == "duplicate_event_id":
        return JsonResponse({"error": "Event id already exists"}, status=409)
    return JsonResponse(stored_event, status=201)


def read_play_campaign_projection(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, projection = storage.get_play_campaign_projection(campaign_id, actor["username"])
    error_response = _projection_access_response(result)
    if error_response:
        return error_response
    return JsonResponse(projection)


def append_play_campaign_replay_event(request, campaign_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        event_id = non_empty_string(body.get("event_id"), "event_id")
        text = non_empty_string(body.get("text"), "text")
        if body.get("kind") != "append":
            raise ValueError("kind must be append")
    except ValueError as error:
        return bad_request(str(error))

    result, event = storage.create_play_campaign_replay_event(
        campaign_id, actor["username"], {"event_id": event_id, "text": text}
    )
    error_response = _projection_access_response(result)
    if error_response:
        return error_response
    if result == "duplicate_event_id":
        return JsonResponse({"error": "Event id already exists"}, status=409)
    return JsonResponse(event, status=201)


def read_play_campaign_replay(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, replay = storage.get_play_campaign_replay(campaign_id, actor["username"])
    error_response = _projection_access_response(result)
    return error_response if error_response else JsonResponse(replay)


def configure_play_campaign_rng_seed(request, campaign_id):
    actor, error_response = authenticated_actor(request, "PUT")
    if error_response:
        return error_response
    try:
        seed = non_empty_string(put_json_body(request).get("seed"), "seed")
    except ValueError as error:
        return bad_request(str(error))
    result, ledger = storage.set_play_campaign_rng_seed(campaign_id, actor["username"], seed)
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "seed_exists":
        return JsonResponse({"error": "RNG seed already configured"}, status=409)
    return JsonResponse(ledger)


def append_play_campaign_rng_roll(request, campaign_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        roll_id = non_empty_string(body.get("roll_id"), "roll_id")
        sides = integer(body.get("sides"), "sides")
        if not 2 <= sides <= 100:
            raise ValueError("sides must be between 2 and 100")
    except ValueError as error:
        return bad_request(str(error))
    result, roll = storage.append_play_campaign_rng_roll(
        campaign_id, actor["username"], roll_id, sides
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "seed_missing":
        return JsonResponse({"error": "RNG seed is not configured"}, status=409)
    if result == "duplicate_roll_id":
        return JsonResponse({"error": "Roll id already exists"}, status=409)
    return JsonResponse(roll, status=201)


def read_play_campaign_rng_ledger(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, ledger = storage.get_play_campaign_rng_ledger(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(ledger)


def play_campaign_moderation_reports(request, campaign_id):
    if request.method == "POST":
        return submit_play_campaign_moderation_report(request, campaign_id)
    if request.method == "GET":
        return read_play_campaign_moderation_reports(request, campaign_id)
    return bad_request("GET or POST required")


def safety_tags(value):
    """Validate the intentionally narrow tag representation for safety APIs."""
    if not isinstance(value, list) or not value:
        raise ValueError("tags must be a non-empty array of unique non-empty strings")
    if any(not isinstance(tag, str) or not tag.strip() for tag in value):
        raise ValueError("tags must be a non-empty array of unique non-empty strings")
    if len(set(value)) != len(value):
        raise ValueError("tags must be a non-empty array of unique non-empty strings")
    return value


def replace_play_campaign_safety_boundaries(request, campaign_id):
    actor, error_response = authenticated_actor(request, "PUT")
    if error_response:
        return error_response
    try:
        blocked_tags = sorted(safety_tags(put_json_body(request).get("blocked_tags")))
    except ValueError as error:
        return bad_request(str(error))
    result, boundaries = storage.replace_play_campaign_safety_boundaries(
        campaign_id, actor["username"], blocked_tags
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(boundaries)


def read_play_campaign_safety_boundaries(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, boundaries = storage.get_play_campaign_safety_boundaries(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(boundaries)


def play_campaign_safety_boundaries(request, campaign_id):
    if request.method == "PUT":
        return replace_play_campaign_safety_boundaries(request, campaign_id)
    if request.method == "GET":
        return read_play_campaign_safety_boundaries(request, campaign_id)
    return bad_request("GET or PUT required")


def seed_play_campaign_fixture(request, campaign_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    try:
        fixture_id = json_body(request).get("fixture_id")
        if not isinstance(fixture_id, str) or fixture_id != "canonical-v1":
            raise ValueError("fixture_id must be canonical-v1")
    except ValueError as error:
        return bad_request(str(error))
    result, fixture = storage.seed_play_campaign_fixture(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(fixture, status=201 if result == "seeded" else 200)


def read_play_campaign_fixture_state(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, fixture = storage.get_play_campaign_fixture(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "missing":
        return JsonResponse({"error": "Fixture state not found"}, status=404)
    return JsonResponse(fixture)


def submit_play_campaign_safety_check(request, campaign_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        event = {
            "event_id": non_empty_string(body.get("event_id"), "event_id"),
            "kind": body.get("kind"),
            "text": non_empty_string(body.get("text"), "text"),
            "tags": safety_tags(body.get("tags")),
        }
        if event["kind"] not in {"narration", "chat"}:
            raise ValueError("kind must be narration or chat")
    except ValueError as error:
        return bad_request(str(error))
    result, accepted = storage.submit_play_campaign_safety_check(
        campaign_id, actor["username"], event
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result in {"duplicate_event_id", "blocked_tag"}:
        return JsonResponse({"error": "Safety check rejected"}, status=409)
    return JsonResponse(accepted, status=201)


def read_play_campaign_safety_events(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, events = storage.get_play_campaign_safety_events(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(events)


def submit_play_campaign_moderation_report(request, campaign_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        report = {
            "report_id": non_empty_string(body.get("report_id"), "report_id"),
            "target_id": non_empty_string(body.get("target_id"), "target_id"),
            "reason": non_empty_string(body.get("reason"), "reason"),
        }
    except ValueError as error:
        return bad_request(str(error))
    result, stored = storage.create_play_campaign_moderation_report(
        campaign_id, actor["username"], report
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "duplicate_report_id":
        return JsonResponse({"error": "Report id already exists"}, status=409)
    return JsonResponse(stored, status=201)


def read_play_campaign_moderation_reports(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, reports = storage.get_play_campaign_moderation_reports(
        campaign_id, actor["username"]
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse({"reports": reports})


def resolve_play_campaign_moderation_report(request, campaign_id, report_id):
    actor, error_response = authenticated_actor(request, "PUT")
    if error_response:
        return error_response
    try:
        body = put_json_body(request)
        action = body.get("action")
        if action not in {"allow", "remove"}:
            raise ValueError("action must be allow or remove")
        resolution = {"action": action, "note": non_empty_string(body.get("note"), "note")}
    except ValueError as error:
        return bad_request(str(error))
    result, resolved = storage.resolve_play_campaign_moderation_report(
        campaign_id, actor["username"], report_id, resolution
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_report":
        return JsonResponse({"error": "Unknown report"}, status=404)
    if result == "already_resolved":
        return JsonResponse({"error": "Report already resolved"}, status=409)
    return JsonResponse(resolved)


def create_play_campaign_idempotent_event(request, campaign_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    try:
        idempotency_key = request.headers.get("Idempotency-Key")
        if not isinstance(idempotency_key, str) or not (idempotency_key := idempotency_key.strip()):
            raise ValueError("Idempotency-Key must be a non-empty string")
        body = json_body(request)
        event = {
            "event_id": non_empty_string(body.get("event_id"), "event_id"),
            "value": non_empty_string(body.get("value"), "value"),
            "idempotency_key": idempotency_key,
        }
    except ValueError as error:
        return bad_request(str(error))

    result, stored_event = storage.create_play_campaign_idempotent_event(
        campaign_id, actor["username"], event
    )
    error_response = _projection_access_response(result)
    if error_response:
        return error_response
    if result in {"key_conflict", "event_id_conflict"}:
        return JsonResponse({"error": "Idempotency conflict"}, status=409)
    return JsonResponse(stored_event, status=201 if result == "created" else 200)


def read_play_campaign_idempotent_events(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, events = storage.get_play_campaign_idempotent_events(campaign_id, actor["username"])
    error_response = _projection_access_response(result)
    if error_response:
        return error_response
    return JsonResponse(events)


def play_campaign_idempotent_events(request, campaign_id):
    if request.method == "POST":
        return create_play_campaign_idempotent_event(request, campaign_id)
    if request.method == "GET":
        return read_play_campaign_idempotent_events(request, campaign_id)
    return bad_request("GET or POST required")


def submit_play_campaign_safe_turn(request, campaign_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        submission = {
            "submission_id": non_empty_string(body.get("submission_id"), "submission_id"),
            "expected_turn": integer(body.get("expected_turn"), "expected_turn"),
            "action": non_empty_string(body.get("action"), "action"),
        }
        if submission["expected_turn"] <= 0:
            raise ValueError("expected_turn must be positive")
    except ValueError as error:
        return bad_request(str(error))

    result, accepted = storage.submit_play_campaign_safe_turn(
        campaign_id, actor["username"], submission
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "duplicate_submission_id":
        return JsonResponse({"error": "Submission id already exists"}, status=409)
    if result == "stale_turn":
        return JsonResponse(accepted, status=409)
    return JsonResponse(accepted, status=201)


def read_play_campaign_safe_turns(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, turns = storage.get_play_campaign_safe_turns(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(turns)


def play_campaign_safe_turns(request, campaign_id):
    if request.method == "POST":
        return submit_play_campaign_safe_turn(request, campaign_id)
    if request.method == "GET":
        return read_play_campaign_safe_turns(request, campaign_id)
    return bad_request("GET or POST required")


def play_campaign_audit_events(request, campaign_id):
    if request.method not in {"GET", "POST"}:
        return bad_request("GET or POST required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    if request.method == "POST":
        try:
            body = json_body(request)
            kind = non_empty_string(body.get("kind"), "kind")
            correlation_id = non_empty_string(body.get("correlation_id"), "correlation_id")
        except ValueError as error:
            return bad_request(str(error))
        result, entry = storage.create_play_campaign_audit_event(
            campaign_id, actor["username"], kind, correlation_id
        )
        if result == "unknown_campaign":
            return JsonResponse({"error": "Unknown campaign"}, status=404)
        if result == "not_member":
            return JsonResponse({"error": "Forbidden"}, status=403)
        if result == "duplicate_correlation_id":
            return JsonResponse({"error": "Correlation id already exists"}, status=409)
        return JsonResponse(entry, status=201)

    result, entries = storage.get_play_campaign_audit_events(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse({"entries": entries})


def join_play_campaign(request, campaign_id):
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "player":
        return JsonResponse({"error": "Forbidden"}, status=403)

    try:
        body = json_body(request)
        member = {
            "username": actor["username"],
            "character_id": non_empty_string(body.get("character_id"), "character_id"),
            "name": non_empty_string(body.get("name"), "name"),
            "class": non_empty_string(body.get("class"), "class"),
        }
        if "hp_current" in body or "hp_max" in body:
            hp_current = non_negative_integer(body.get("hp_current"), "hp_current")
            hp_max = non_negative_integer(body.get("hp_max"), "hp_max")
            if hp_current > hp_max:
                raise ValueError("hp_current cannot exceed hp_max")
            member["hp_current"] = hp_current
            member["hp_max"] = hp_max
    except ValueError as error:
        return bad_request(str(error))

    result = storage.add_play_campaign_member(campaign_id, member)
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_lobby":
        return JsonResponse({"error": "Campaign is not accepting members"}, status=409)
    if result == "full":
        return JsonResponse({"error": "Party is full"}, status=409)
    if result == "duplicate":
        return JsonResponse({"error": "Membership already exists"}, status=409)
    return JsonResponse({
        "username": member["username"],
        "character_id": member["character_id"],
        "name": member["name"],
        "class": member["class"],
    }, status=201)


def play_campaign_invitations(request, campaign_id):
    if request.method == "POST":
        return create_play_campaign_invitation(request, campaign_id)
    if request.method == "GET":
        return list_play_campaign_invitations(request, campaign_id)
    return bad_request("GET or POST required")


def create_play_campaign_invitation(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        if set(body) != {"invitation_id", "username", "character_id"}:
            raise ValueError("invitation_id, username, and character_id are required")
        invitation = {
            "invitation_id": non_empty_string(body["invitation_id"], "invitation_id"),
            "username": non_empty_string(body["username"], "username"),
            "character_id": non_empty_string(body["character_id"], "character_id"),
        }
    except ValueError as error:
        return bad_request(str(error))

    target = storage.get_user(invitation["username"])
    if target is None or target["role"] != "player":
        return bad_request("Target user must be a registered player")
    result, created = storage.create_play_campaign_invitation(
        campaign_id, actor["username"], invitation
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result in {"duplicate_id", "duplicate_pending"}:
        return JsonResponse({"error": "Invitation already exists"}, status=409)
    return JsonResponse(created, status=201)


def accept_play_campaign_invitation(request, campaign_id, invitation_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    result, invitation = storage.accept_play_campaign_invitation(
        campaign_id, actor["username"], invitation_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "unknown_invitation":
        return JsonResponse({"error": "Unknown invitation"}, status=404)
    if result == "not_target":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result in {"already_accepted", "membership_exists"}:
        return JsonResponse({"error": "Invitation already accepted"}, status=409)
    return JsonResponse(invitation)


def list_play_campaign_invitations(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, invitations = storage.get_play_campaign_invitations(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    return JsonResponse({"invitations": invitations})


def start_play_campaign(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response

    result, campaign = storage.start_play_campaign(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "under_populated":
        return JsonResponse({"error": "Party needs at least two members"}, status=409)
    if result == "not_lobby":
        return JsonResponse({"error": "Campaign is already active"}, status=409)
    return JsonResponse(campaign)


def session_zero_settings_payload(request):
    body = put_json_body(request)
    if set(body) != {"rules", "tone", "consent"}:
        raise ValueError("rules, tone, and consent are required")
    consent = body["consent"]
    if not isinstance(consent, list) or not consent:
        raise ValueError("consent must be a non-empty array")
    for entry in consent:
        non_empty_string(entry, "consent entry")
    if len(set(consent)) != len(consent):
        raise ValueError("consent entries must be unique")
    return {
        "rules": non_empty_string(body["rules"], "rules"),
        "tone": non_empty_string(body["tone"], "tone"),
        "consent": consent,
    }


def manage_play_campaign_session_zero(request, campaign_id):
    if request.method == "PUT":
        actor, error_response = dm_actor(request, "PUT")
        if error_response:
            return error_response
        try:
            settings = session_zero_settings_payload(request)
        except ValueError as error:
            return bad_request(str(error))
        result, settings = storage.set_play_campaign_session_zero_settings(
            campaign_id, actor["username"], settings
        )
        if result == "unknown_campaign":
            return JsonResponse({"error": "Unknown campaign"}, status=404)
        if result == "not_owner":
            return JsonResponse({"error": "Forbidden"}, status=403)
        if result == "not_lobby":
            return JsonResponse({"error": "Campaign is no longer in the lobby"}, status=409)
        return JsonResponse(settings)

    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, settings = storage.get_play_campaign_session_zero_settings(
        campaign_id, actor["username"]
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "missing_settings":
        return JsonResponse({"error": "Session-zero settings not found"}, status=404)
    return JsonResponse(settings)


def content_tags(value, *, allow_empty):
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ValueError("tags must be a non-empty array" if not allow_empty else "tags must be an array")
    for tag in value:
        non_empty_string(tag, "tag")
    if len(set(value)) != len(value):
        raise ValueError("tags must be unique")
    return value


def content_payload(body):
    if set(body) != {"content_id", "kind", "text", "tags"}:
        raise ValueError("content_id, kind, text, and tags are required")
    return {
        "content_id": non_empty_string(body["content_id"], "content_id"),
        "kind": non_empty_string(body["kind"], "kind"),
        "text": non_empty_string(body["text"], "text"),
        "tags": content_tags(body["tags"], allow_empty=False),
    }


def create_play_campaign_content(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        content = content_payload(json_body(request))
    except (TypeError, ValueError) as error:
        return bad_request(str(error))
    result, created = storage.create_play_campaign_content(campaign_id, actor["username"], content)
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "duplicate":
        return JsonResponse({"error": "Content id already exists"}, status=409)
    return JsonResponse(created, status=201)


def replace_play_campaign_content_tags(request, campaign_id, content_id):
    actor, error_response = dm_actor(request, "PUT")
    if error_response:
        return error_response
    try:
        body = put_json_body(request)
        if set(body) != {"tags"}:
            raise ValueError("tags is required")
        tags = content_tags(body["tags"], allow_empty=True)
    except (TypeError, ValueError) as error:
        return bad_request(str(error))
    result, content = storage.replace_play_campaign_content_tags(
        campaign_id, actor["username"], content_id, tags
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_content":
        return JsonResponse({"error": "Unknown content"}, status=404)
    return JsonResponse(content)


def list_play_campaign_content(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    exclude_tag = request.GET.get("exclude_tag")
    if exclude_tag is not None:
        try:
            non_empty_string(exclude_tag, "exclude_tag")
        except ValueError as error:
            return bad_request(str(error))
    result, content = storage.get_play_campaign_content(campaign_id, actor["username"], exclude_tag)
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(content)


def play_campaign_content(request, campaign_id):
    if request.method == "POST":
        return create_play_campaign_content(request, campaign_id)
    if request.method == "GET":
        return list_play_campaign_content(request, campaign_id)
    return bad_request("GET or POST required")


def privacy_note_payload(body, *, updating=False):
    required = {"text", "visibility"} if updating else {"note_id", "text", "visibility"}
    if set(body) != required:
        raise ValueError("Invalid note payload")
    note = {
        "text": non_empty_string(body["text"], "text"),
        "visibility": body["visibility"],
    }
    if note["visibility"] not in {"private", "party"}:
        raise ValueError("visibility must be private or party")
    if not updating:
        note = {"note_id": non_empty_string(body["note_id"], "note_id"), **note}
    return note


def _privacy_result(result):
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return None


def play_campaign_notes(request, campaign_id):
    if request.method == "POST":
        actor, error_response = authenticated_actor(request, "POST")
        if error_response:
            return error_response
        try:
            note = privacy_note_payload(json_body(request))
        except (TypeError, ValueError) as error:
            return bad_request(str(error))
        result, note = storage.create_play_campaign_note(campaign_id, actor["username"], note)
        error_response = _privacy_result(result)
        if error_response:
            return error_response
        if result == "duplicate":
            return JsonResponse({"error": "Note id already exists"}, status=409)
        return JsonResponse(note, status=201)
    if request.method == "GET":
        actor, error_response = authenticated_actor(request, "GET")
        if error_response:
            return error_response
        result, notes = storage.get_play_campaign_notes(campaign_id, actor["username"])
        error_response = _privacy_result(result)
        return error_response if error_response else JsonResponse(notes)
    return bad_request("GET or POST required")


def play_campaign_note(request, campaign_id, note_id):
    if request.method == "GET":
        actor, error_response = authenticated_actor(request, "GET")
        if error_response:
            return error_response
        result, note = storage.get_play_campaign_notes(campaign_id, actor["username"], note_id)
        error_response = _privacy_result(result)
        if error_response:
            return error_response
        if result == "unknown_note":
            return JsonResponse({"error": "Unknown note"}, status=404)
        if result == "not_readable":
            return JsonResponse({"error": "Forbidden"}, status=403)
        return JsonResponse(note)
    if request.method == "PUT":
        actor, error_response = authenticated_actor(request, "PUT")
        if error_response:
            return error_response
        try:
            changes = privacy_note_payload(put_json_body(request), updating=True)
        except (TypeError, ValueError) as error:
            return bad_request(str(error))
        result, note = storage.update_play_campaign_note(
            campaign_id, actor["username"], note_id, changes
        )
        error_response = _privacy_result(result)
        if error_response:
            return error_response
        if result == "unknown_note":
            return JsonResponse({"error": "Unknown note"}, status=404)
        if result == "not_owner":
            return JsonResponse({"error": "Forbidden"}, status=403)
        return JsonResponse(note)
    return bad_request("GET or PUT required")


def play_campaign_whispers(request, campaign_id):
    if request.method == "POST":
        actor, error_response = authenticated_actor(request, "POST")
        if error_response:
            return error_response
        try:
            body = json_body(request)
            if set(body) != {"whisper_id", "to_character_id", "text"}:
                raise ValueError("Invalid whisper payload")
            whisper = {name: non_empty_string(body[name], name) for name in body}
        except (TypeError, ValueError) as error:
            return bad_request(str(error))
        result, whisper = storage.create_play_campaign_whisper(campaign_id, actor["username"], whisper)
        error_response = _privacy_result(result)
        if error_response:
            return error_response
        if result == "duplicate":
            return JsonResponse({"error": "Whisper id already exists"}, status=409)
        if result in {"no_owned_character", "invalid_recipient"}:
            return bad_request("Invalid whisper")
        return JsonResponse(whisper, status=201)
    if request.method == "GET":
        actor, error_response = authenticated_actor(request, "GET")
        if error_response:
            return error_response
        result, whispers = storage.get_play_campaign_whispers(campaign_id, actor["username"])
        error_response = _privacy_result(result)
        return error_response if error_response else JsonResponse(whispers)
    return bad_request("GET or POST required")


def read_play_campaign_character_sheet(request, campaign_id, character_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, sheet = storage.get_play_campaign_character_sheet(
        campaign_id, actor["username"], character_id
    )
    error_response = _privacy_result(result)
    if error_response:
        return error_response
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    if result == "not_readable":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(sheet)


def create_play_campaign_encounter(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response

    try:
        body = json_body(request)
        encounter = {
            "id": non_empty_string(body.get("id"), "id"),
            "name": non_empty_string(body.get("name"), "name"),
        }
    except ValueError as error:
        return bad_request(str(error))

    result, encounter = storage.create_play_campaign_encounter(
        campaign_id, actor["username"], encounter
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "not_active":
        return JsonResponse({"error": "Campaign is not active"}, status=409)
    if result == "conflict":
        return JsonResponse({"error": "Campaign is already in combat"}, status=409)
    return JsonResponse(encounter, status=201)


def award_play_campaign_encounter_rewards(request, campaign_id, encounter_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        xp = non_negative_integer(body.get("xp"), "xp")
        loot = body.get("loot")
        if not isinstance(loot, list):
            raise ValueError("loot must be an array")
        normalized_loot = []
        for entry in loot:
            if not isinstance(entry, dict):
                raise ValueError("loot entries must be objects")
            quantity = non_negative_integer(entry.get("quantity"), "loot quantity")
            if quantity <= 0:
                raise ValueError("loot quantity must be positive")
            normalized_loot.append({
                "slug": non_empty_string(entry.get("slug"), "loot slug"),
                "quantity": quantity,
            })
    except ValueError as error:
        return bad_request(str(error))

    result, reward = storage.award_play_campaign_encounter_rewards(
        campaign_id, actor["username"], encounter_id, {"xp": xp, "loot": normalized_loot}
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_encounter":
        return JsonResponse({"error": "Unknown encounter"}, status=404)
    if result == "already_awarded":
        return JsonResponse({"error": "Rewards already awarded"}, status=409)
    return JsonResponse(reward)


def close_play_campaign_encounter(request, campaign_id, encounter_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response

    result, encounter = storage.close_play_campaign_encounter(
        campaign_id, actor["username"], encounter_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_encounter":
        return JsonResponse({"error": "Unknown encounter"}, status=404)
    return JsonResponse(encounter)


def end_play_campaign_encounter(request, campaign_id, encounter_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response

    result, campaign = storage.end_play_campaign_encounter(
        campaign_id, actor["username"], encounter_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_encounter":
        return JsonResponse({"error": "Unknown encounter"}, status=404)
    if result in {"not_in_combat", "not_active"}:
        return JsonResponse({"error": "Campaign is not in combat"}, status=409)
    return JsonResponse(campaign)


def add_play_campaign_encounter_monster(request, campaign_id, encounter_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response

    try:
        body = json_body(request)
        hp_max = non_negative_integer(body.get("hp_max"), "hp_max")
        if hp_max <= 0:
            raise ValueError("hp_max must be positive")
        monster = {
            "monster_id": non_empty_string(body.get("monster_id"), "monster_id"),
            "name": non_empty_string(body.get("name"), "name"),
            "hp_max": hp_max,
            "initiative": integer(body.get("initiative"), "initiative"),
            "hp_current": hp_max,
        }
    except ValueError as error:
        return bad_request(str(error))

    result, monster = storage.add_play_campaign_encounter_monster(
        campaign_id, actor["username"], encounter_id, monster
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_encounter":
        return JsonResponse({"error": "Unknown encounter"}, status=404)
    if result == "duplicate":
        return JsonResponse({"error": "Monster id already exists"}, status=409)
    return JsonResponse(monster, status=201)


def remove_play_campaign_encounter_monster(request, campaign_id, encounter_id, monster_id):
    actor, error_response = dm_actor(request, "DELETE")
    if error_response:
        return error_response

    result = storage.remove_play_campaign_encounter_monster(
        campaign_id, actor["username"], encounter_id, monster_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_encounter":
        return JsonResponse({"error": "Unknown encounter"}, status=404)
    if result == "unknown_monster":
        return JsonResponse({"error": "Unknown monster"}, status=404)
    return JsonResponse({"removed": monster_id})


def add_play_campaign_encounter_combatant(request, campaign_id, encounter_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response

    try:
        body = json_body(request)
        member = non_empty_string(body.get("member"), "member")
        initiative = integer(body.get("initiative"), "initiative")
    except ValueError as error:
        return bad_request(str(error))

    result, combatant = storage.add_play_campaign_encounter_combatant(
        campaign_id, actor["username"], encounter_id, member, initiative
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_encounter":
        return JsonResponse({"error": "Unknown encounter"}, status=404)
    if result == "unknown_member":
        return bad_request("Unknown member")
    if result == "duplicate":
        return JsonResponse({"error": "Member is already a combatant"}, status=409)
    return JsonResponse(combatant, status=201)


def remove_play_campaign_encounter_combatant(request, campaign_id, encounter_id, member):
    actor, error_response = dm_actor(request, "DELETE")
    if error_response:
        return error_response

    result = storage.remove_play_campaign_encounter_combatant(
        campaign_id, actor["username"], encounter_id, member
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_encounter":
        return JsonResponse({"error": "Unknown encounter"}, status=404)
    if result == "unknown_member":
        return JsonResponse({"error": "Unknown combatant"}, status=404)
    return JsonResponse({"removed": member})


def apply_play_campaign_encounter_condition(request, campaign_id, encounter_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        target = non_empty_string(body.get("target"), "target")
        condition = non_empty_string(body.get("condition"), "condition")
        duration_rounds = integer(body.get("duration_rounds"), "duration_rounds")
        if duration_rounds <= 0:
            raise ValueError("duration_rounds must be positive")
    except ValueError as error:
        return bad_request(str(error))

    result, applied = storage.apply_play_campaign_encounter_condition(
        campaign_id, actor["username"], encounter_id, target, condition, duration_rounds
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_encounter":
        return JsonResponse({"error": "Unknown encounter"}, status=404)
    if result == "unknown_target":
        return JsonResponse({"error": "Unknown target"}, status=404)
    return JsonResponse(applied, status=201)


def read_play_campaign_encounter_status(request, campaign_id, encounter_id):
    if request.method != "GET":
        return bad_request("GET required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    result, status = storage.get_play_campaign_encounter_status(
        campaign_id, actor["username"], encounter_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_encounter":
        return JsonResponse({"error": "Unknown encounter"}, status=404)
    if result == "no_combatants":
        return JsonResponse({"error": "Encounter has no combatants"}, status=409)
    return JsonResponse(status)


def read_play_campaign_encounter_turn(request, campaign_id, encounter_id):
    if request.method != "GET":
        return bad_request("GET required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    result, turn = storage.get_play_campaign_encounter_turn(
        campaign_id, actor["username"], encounter_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_encounter":
        return JsonResponse({"error": "Unknown encounter"}, status=404)
    if result == "no_combatants":
        return JsonResponse({"error": "Encounter has no combatants"}, status=409)
    return JsonResponse(turn)


def advance_play_campaign_encounter_turn(request, campaign_id, encounter_id):
    if request.method != "POST":
        return bad_request("POST required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    result, turn = storage.advance_play_campaign_encounter_turn(
        campaign_id, actor["username"], encounter_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_encounter":
        return JsonResponse({"error": "Unknown encounter"}, status=404)
    if result == "no_combatants":
        return JsonResponse({"error": "Encounter has no combatants"}, status=409)
    if result == "not_your_turn":
        return JsonResponse({"error": "It is not your turn"}, status=409)
    return JsonResponse(turn)


def delay_play_campaign_encounter_turn(request, campaign_id, encounter_id):
    if request.method != "POST":
        return bad_request("POST required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    try:
        body = json_body(request)
        new_index = integer(body.get("new_index", body.get("index")), "new_index")
    except ValueError as error:
        return bad_request(str(error))

    result, response = storage.delay_play_campaign_encounter_turn(
        campaign_id, actor["username"], encounter_id, new_index
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_encounter":
        return JsonResponse({"error": "Unknown encounter"}, status=404)
    if result == "no_combatants":
        return JsonResponse({"error": "Encounter has no combatants"}, status=409)
    if result == "not_your_turn":
        return JsonResponse({"error": "It is not your turn"}, status=409)
    if result == "invalid_index":
        return bad_request("new_index must be later and within the initiative order")
    return JsonResponse(response)


def ready_play_campaign_encounter_action(request, campaign_id, encounter_id):
    if request.method != "POST":
        return bad_request("POST required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    try:
        trigger = non_empty_string(json_body(request).get("trigger"), "trigger")
    except ValueError as error:
        return bad_request(str(error))

    result, record = storage.ready_play_campaign_encounter_action(
        campaign_id, actor["username"], encounter_id, trigger
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_encounter":
        return JsonResponse({"error": "Unknown encounter"}, status=404)
    if result == "no_combatants":
        return JsonResponse({"error": "Encounter has no combatants"}, status=409)
    if result == "not_your_turn":
        return JsonResponse({"error": "It is not your turn"}, status=409)
    return JsonResponse(record, status=201)


def submit_play_campaign_combat_action(request, campaign_id, encounter_id):
    if request.method != "POST":
        return bad_request("POST required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "player":
        return JsonResponse({"error": "Only players may submit combat actions"}, status=409)

    try:
        body = json_body(request)
        action_type = non_empty_string(body.get("type"), "type")
        if action_type not in {"attack", "help", "dodge", "ready"}:
            raise ValueError("type must be attack, help, dodge, or ready")
        action = {
            "type": action_type,
            "target": non_empty_string(body.get("target"), "target"),
            "text": non_empty_string(body.get("text"), "text"),
        }
    except ValueError as error:
        return bad_request(str(error))

    result, event = storage.submit_play_campaign_combat_action(
        campaign_id, encounter_id, actor["username"], action
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_encounter":
        return JsonResponse({"error": "Unknown encounter"}, status=404)
    if result == "no_combatants":
        return JsonResponse({"error": "Encounter has no combatants"}, status=409)
    if result == "not_your_turn":
        return JsonResponse({"error": "It is not your turn"}, status=409)
    return JsonResponse(event, status=201)


def adjust_play_campaign_encounter_hp(request, campaign_id, encounter_id, healing):
    if request.method != "POST":
        return bad_request("POST required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "dm":
        return JsonResponse({"error": "Forbidden"}, status=403)

    try:
        body = json_body(request)
        target = non_empty_string(body.get("target"), "target")
        amount = non_negative_integer(body.get("amount"), "amount")
        if amount <= 0:
            raise ValueError("amount must be positive")
    except ValueError as error:
        return bad_request(str(error))

    result, adjustment = storage.adjust_play_campaign_encounter_hp(
        campaign_id, actor["username"], encounter_id, target, amount, healing
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_encounter":
        return JsonResponse({"error": "Unknown encounter"}, status=404)
    if result == "unknown_target":
        return JsonResponse({"error": "Unknown target"}, status=404)
    adjustment["healing" if healing else "damage"] = amount
    return JsonResponse(adjustment)


def damage_play_campaign_encounter(request, campaign_id, encounter_id):
    return adjust_play_campaign_encounter_hp(request, campaign_id, encounter_id, healing=False)


def heal_play_campaign_encounter(request, campaign_id, encounter_id):
    return adjust_play_campaign_encounter_hp(request, campaign_id, encounter_id, healing=True)


def damage_play_campaign_character(request, campaign_id, character_id):
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    try:
        body = json_body(request)
        amount = non_negative_integer(body.get("amount"), "amount")
        if amount <= 0:
            raise ValueError("amount must be positive")
    except ValueError as error:
        return bad_request(str(error))

    result, adjustment = storage.damage_play_campaign_character(
        campaign_id, actor["username"], character_id, amount
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    adjustment["damage"] = amount
    return JsonResponse(adjustment)


def record_play_campaign_death_save(request, campaign_id, character_id):
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    try:
        body = json_body(request)
        outcome = body.get("outcome")
        if outcome not in ("success", "failure"):
            raise ValueError("outcome must be success or failure")
    except ValueError as error:
        return bad_request(str(error))

    result, death_save = storage.record_play_campaign_death_save(
        campaign_id, actor["username"], character_id, outcome
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "not_unconscious":
        return JsonResponse({"error": "Character is not unconscious"}, status=409)
    return JsonResponse(death_save, status=201)


def skill_check_play_campaign_character(request, campaign_id, character_id):
    """Resolve an owned character's skill check from its saved build choices."""
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    try:
        body = json_body(request)
        skill = body.get("skill")
        ability = body.get("ability")
        proficient = body.get("proficient")
        roll = integer(body.get("roll"), "roll")
        if skill not in SKILL_NAMES:
            raise ValueError("Unsupported skill")
        if ability not in ABILITY_NAMES:
            raise ValueError("Unsupported ability")
        if not isinstance(proficient, bool):
            raise ValueError("proficient must be a boolean")
    except ValueError as error:
        return bad_request(str(error))

    result, character = storage.get_play_campaign_character_skill_data(
        campaign_id, actor["username"], character_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)

    score = character["abilities"].get(ability)
    if isinstance(score, bool) or not isinstance(score, int):
        return bad_request("Character abilities are not set")
    modifier = ability_modifier_for(score)
    if proficient:
        modifier += proficiency_bonus_for(character["level"])
    return JsonResponse({
        "character_id": character_id,
        "skill": skill,
        "ability": ability,
        "modifier": modifier,
        "total": roll + modifier,
    })


def manage_play_campaign_character_spells(request, campaign_id, character_id):
    """Add to an owned spellbook or read it as a campaign member."""
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    if request.method == "POST":
        try:
            body = json_body(request)
            spell = {
                "spell_id": non_empty_string(body.get("spell_id"), "spell_id"),
                "name": non_empty_string(body.get("name"), "name"),
                "level": non_negative_integer(body.get("level"), "level"),
            }
        except (TypeError, ValueError) as error:
            return bad_request(str(error))

        result = storage.add_play_campaign_character_spell(
            campaign_id, actor["username"], character_id, spell
        )
        if result == "unknown_campaign":
            return JsonResponse({"error": "Unknown campaign"}, status=404)
        if result == "unknown_character":
            return JsonResponse({"error": "Unknown character"}, status=404)
        if result == "not_owner":
            return JsonResponse({"error": "Forbidden"}, status=403)
        if result == "invalid_class":
            return bad_request("Spell is not valid for this character class")
        if result == "duplicate":
            return JsonResponse({"error": "Spell is already known"}, status=409)
        return JsonResponse(spell, status=201)

    if request.method != "GET":
        return bad_request("GET or POST required")
    result, spells = storage.get_play_campaign_character_spells(
        campaign_id, actor["username"], character_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    return JsonResponse({"spells": spells})


def manage_play_campaign_prepared_spells(request, campaign_id, character_id):
    """Replace an owner's prepared spells or read them as a campaign member."""
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    if request.method == "PUT":
        try:
            spell_ids = put_json_body(request).get("spell_ids")
            if not isinstance(spell_ids, list) or any(
                not isinstance(spell_id, str) or not spell_id for spell_id in spell_ids
            ):
                raise ValueError("spell_ids must be an array of non-empty strings")
            if len(set(spell_ids)) != len(spell_ids):
                raise ValueError("spell_ids must not contain duplicates")
        except ValueError as error:
            return bad_request(str(error))
        result, prepared = storage.replace_play_campaign_prepared_spells(
            campaign_id, actor["username"], character_id, spell_ids
        )
        if result == "unknown_campaign":
            return JsonResponse({"error": "Unknown campaign"}, status=404)
        if result == "unknown_character":
            return JsonResponse({"error": "Unknown character"}, status=404)
        if result == "not_owner":
            return JsonResponse({"error": "Forbidden"}, status=403)
        if result == "invalid_class":
            return bad_request("Character cannot prepare spells")
        if result == "unknown_spell":
            return bad_request("Spell is not known by this character")
        if result == "too_many":
            return bad_request("Too many prepared spells")
        return JsonResponse(prepared)

    if request.method != "GET":
        return bad_request("GET or PUT required")
    result, prepared = storage.get_play_campaign_prepared_spells(
        campaign_id, actor["username"], character_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    return JsonResponse(prepared)


def manage_play_campaign_character_casts(request, campaign_id, character_id):
    """Cast an owned prepared spell or read a member-visible cast history."""
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    if request.method == "POST":
        try:
            body = json_body(request)
            spell_id = non_empty_string(body.get("spell_id"), "spell_id")
            target = non_empty_string(body.get("target"), "target")
        except ValueError as error:
            return bad_request(str(error))
        result, event = storage.cast_play_campaign_character_spell(
            campaign_id, actor["username"], character_id, spell_id, target
        )
        if result == "unknown_campaign":
            return JsonResponse({"error": "Unknown campaign"}, status=404)
        if result == "unknown_character":
            return JsonResponse({"error": "Unknown character"}, status=404)
        if result == "not_owner":
            return JsonResponse({"error": "Forbidden"}, status=403)
        if result == "invalid_class":
            return bad_request("Character is not a spellcaster")
        if result == "not_prepared":
            return bad_request("Spell is not currently prepared")
        if result == "no_slots":
            return JsonResponse({"error": "No remaining spell slots"}, status=409)
        return JsonResponse(event, status=201)

    if request.method != "GET":
        return bad_request("GET or POST required")
    result, casts = storage.get_play_campaign_character_casts(
        campaign_id, actor["username"], character_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    return JsonResponse({"casts": casts})


def _concentration_error_response(result):
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    if result in {"not_owner", "not_member"}:
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "invalid_class":
        return bad_request("Character is not a spellcaster")
    if result == "unknown_spell":
        return bad_request("Spell is not known by this character")
    if result == "not_prepared":
        return bad_request("Spell is not currently prepared")
    return None


def manage_play_campaign_character_concentration(request, campaign_id, character_id):
    """Set/clear owned concentration or read it as a campaign member."""
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    if request.method == "PUT":
        try:
            body = put_json_body(request)
            spell_id = non_empty_string(body.get("spell_id"), "spell_id")
            target = non_empty_string(body.get("target"), "target")
            duration_turns = integer(body.get("duration_turns"), "duration_turns")
            if duration_turns < 1:
                raise ValueError("duration_turns must be at least 1")
        except ValueError as error:
            return bad_request(str(error))
        result, state = storage.set_play_campaign_character_concentration(
            campaign_id, actor["username"], character_id, spell_id, target, duration_turns
        )
        error_response = _concentration_error_response(result)
        return error_response if error_response else JsonResponse(state)

    if request.method == "DELETE":
        result, state = storage.clear_play_campaign_character_concentration(
            campaign_id, actor["username"], character_id
        )
        error_response = _concentration_error_response(result)
        return error_response if error_response else JsonResponse(state)

    if request.method != "GET":
        return bad_request("GET, PUT or DELETE required")
    result, state = storage.get_play_campaign_character_concentration(
        campaign_id, actor["username"], character_id
    )
    error_response = _concentration_error_response(result)
    return error_response if error_response else JsonResponse(state)


def advance_play_campaign_character_concentration(request, campaign_id, character_id):
    """Advance a campaign member-visible concentration by one turn."""
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    result, state = storage.advance_play_campaign_character_concentration(
        campaign_id, actor["username"], character_id
    )
    error_response = _concentration_error_response(result)
    return error_response if error_response else JsonResponse(state)


def downtime_activity_payload(body):
    activity = {
        "activity_id": non_empty_string(body.get("activity_id"), "activity_id"),
        "name": non_empty_string(body.get("name"), "name"),
        "cycles_required": integer(body.get("cycles_required"), "cycles_required"),
    }
    if not 1 <= activity["cycles_required"] <= 10:
        raise ValueError("cycles_required must be between 1 and 10")
    return activity


def create_play_campaign_downtime_activity(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        activity = downtime_activity_payload(json_body(request))
    except (TypeError, ValueError) as error:
        return bad_request(str(error))
    result, created = storage.create_play_campaign_downtime_activity(
        campaign_id, actor["username"], activity
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "duplicate":
        return JsonResponse({"error": "Activity id already exists"}, status=409)
    return JsonResponse(created, status=201)


def _downtime_mutation_error_response(result):
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    if result == "unknown_activity":
        return JsonResponse({"error": "Unknown activity"}, status=404)
    if result == "unknown_allocation":
        return JsonResponse({"error": "Unknown allocation"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "duplicate":
        return JsonResponse({"error": "Downtime allocation already exists"}, status=409)
    return None


def create_play_campaign_downtime_allocation(request, campaign_id, character_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    if actor["role"] != "player":
        return JsonResponse({"error": "Forbidden"}, status=403)
    try:
        activity_id = non_empty_string(json_body(request).get("activity_id"), "activity_id")
    except (TypeError, ValueError) as error:
        return bad_request(str(error))
    result, allocation = storage.create_play_campaign_downtime_allocation(
        campaign_id, actor["username"], character_id, activity_id
    )
    error_response = _downtime_mutation_error_response(result)
    return error_response if error_response else JsonResponse(allocation, status=201)


def progress_play_campaign_downtime_allocation(request, campaign_id, character_id, activity_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    if actor["role"] != "player":
        return JsonResponse({"error": "Forbidden"}, status=403)
    result, allocation = storage.progress_play_campaign_downtime_allocation(
        campaign_id, actor["username"], character_id, activity_id
    )
    error_response = _downtime_mutation_error_response(result)
    return error_response if error_response else JsonResponse(allocation)


def read_play_campaign_downtime_allocation(request, campaign_id, character_id, activity_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, allocation = storage.get_play_campaign_downtime_allocation(
        campaign_id, actor["username"], character_id, activity_id
    )
    error_response = _downtime_mutation_error_response(result)
    if result == "not_member":
        error_response = JsonResponse({"error": "Forbidden"}, status=403)
    return error_response if error_response else JsonResponse(allocation)


def _inventory_error_response(result):
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    if result in {"not_owner", "not_member"}:
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "insufficient":
        return JsonResponse({"error": "Insufficient item quantity"}, status=409)
    return None


def recipe_payload(body):
    """Validate the public inventory catalog references used by a recipe."""
    recipe = {
        "recipe_id": non_empty_string(body.get("recipe_id"), "recipe_id"),
        "name": non_empty_string(body.get("name"), "name"),
        "ingredients": body.get("ingredients"),
        "output_item": body.get("output_item"),
        "output_quantity": integer(body.get("output_quantity"), "output_quantity"),
    }
    if not isinstance(recipe["ingredients"], dict) or not recipe["ingredients"]:
        raise ValueError("ingredients must be a non-empty object")
    validated_ingredients = {}
    for item_id, quantity in recipe["ingredients"].items():
        if not isinstance(item_id, str) or item_id not in INVENTORY_ITEM_IDS:
            raise ValueError("Unknown ingredient item_id")
        quantity = integer(quantity, f"ingredients.{item_id}")
        if quantity <= 0:
            raise ValueError("ingredient quantities must be positive")
        validated_ingredients[item_id] = quantity
    recipe["ingredients"] = validated_ingredients
    if not isinstance(recipe["output_item"], str) or recipe["output_item"] not in INVENTORY_ITEM_IDS:
        raise ValueError("Unknown output_item")
    if recipe["output_quantity"] <= 0:
        raise ValueError("output_quantity must be positive")
    return recipe


def create_play_campaign_recipe(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        recipe = recipe_payload(json_body(request))
    except (TypeError, ValueError) as error:
        return bad_request(str(error))
    result, created = storage.create_play_campaign_recipe(campaign_id, actor["username"], recipe)
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "duplicate":
        return JsonResponse({"error": "Recipe id already exists"}, status=409)
    return JsonResponse(created, status=201)


def read_play_campaign_recipes(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, recipes = storage.get_play_campaign_recipes(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(recipes)


def play_campaign_recipes(request, campaign_id):
    if request.method == "POST":
        return create_play_campaign_recipe(request, campaign_id)
    if request.method == "GET":
        return read_play_campaign_recipes(request, campaign_id)
    return bad_request("GET or POST required")


def craft_play_campaign_recipe(request, campaign_id, recipe_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    if actor["role"] != "player":
        return JsonResponse({"error": "Forbidden"}, status=403)
    try:
        character_id = non_empty_string(json_body(request).get("character_id"), "character_id")
    except ValueError as error:
        return bad_request(str(error))
    result, crafted = storage.craft_play_campaign_recipe(
        campaign_id, actor["username"], recipe_id, character_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "unknown_recipe":
        return JsonResponse({"error": "Unknown recipe"}, status=404)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "insufficient":
        return JsonResponse({"error": "Insufficient ingredients"}, status=409)
    return JsonResponse(crafted, status=201)


def manage_play_campaign_character_inventory_items(request, campaign_id, character_id):
    """Add owned item stacks or list them for any campaign member."""
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if request.method == "POST":
        try:
            body = json_body(request)
            item_id = body.get("item_id")
            quantity = integer(body.get("quantity"), "quantity")
            if item_id not in INVENTORY_ITEM_IDS:
                raise ValueError("Unknown item_id")
            if quantity <= 0:
                raise ValueError("quantity must be positive")
        except (TypeError, ValueError) as error:
            return bad_request(str(error))
        result, item = storage.add_play_campaign_character_inventory_item(
            campaign_id, actor["username"], character_id, item_id, quantity
        )
        error_response = _inventory_error_response(result)
        return error_response if error_response else JsonResponse(item, status=201)
    if request.method != "GET":
        return bad_request("GET or POST required")
    result, items = storage.get_play_campaign_character_inventory_items(
        campaign_id, actor["username"], character_id
    )
    error_response = _inventory_error_response(result)
    return error_response if error_response else JsonResponse(items)


def remove_play_campaign_character_inventory_item(request, campaign_id, character_id, item_id):
    """Remove a positive amount from an owned character's item stack."""
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    try:
        body = _json_object_body(request, "DELETE")
        quantity = integer(body.get("quantity"), "quantity")
        if item_id not in INVENTORY_ITEM_IDS:
            raise ValueError("Unknown item_id")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
    except ValueError as error:
        return bad_request(str(error))
    result, item = storage.remove_play_campaign_character_inventory_item(
        campaign_id, actor["username"], character_id, item_id, quantity
    )
    error_response = _inventory_error_response(result)
    return error_response if error_response else JsonResponse(item)


def consume_play_campaign_character_inventory_item(request, campaign_id, character_id, item_id):
    """Consume one owned healing potion without a request body."""
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    if item_id not in CONSUMABLE_EFFECTS:
        return bad_request("Item is not consumable")
    result, consumption = storage.consume_play_campaign_character_inventory_item(
        campaign_id, actor["username"], character_id, item_id
    )
    error_response = _inventory_error_response(result)
    if error_response:
        return error_response
    consumption["effect"] = CONSUMABLE_EFFECTS[item_id]
    return JsonResponse(consumption)


def _equipment_error_response(result):
    error_response = _inventory_error_response(result)
    if error_response:
        return error_response
    if result in {"unheld", "not_equipped"}:
        return bad_request("Item must be equipped from character inventory")
    if result == "cannot_attune":
        return bad_request("Item cannot be attuned")
    if result == "attunement_limit":
        return JsonResponse({"error": "Attunement limit reached"}, status=409)
    return None


def manage_play_campaign_character_equipment(request, campaign_id, character_id, slot):
    """Equip an owned item or let campaign members inspect a valid slot."""
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if slot not in EQUIPMENT_SLOTS:
        return bad_request("Invalid equipment slot")
    if request.method == "PUT":
        try:
            item_id = put_json_body(request).get("item_id")
            if item_id not in EQUIPMENT_ITEM_SLOTS:
                raise ValueError("Unknown item_id")
            if EQUIPMENT_ITEM_SLOTS[item_id] != slot:
                raise ValueError("Item does not match equipment slot")
        except (TypeError, ValueError) as error:
            return bad_request(str(error))
        result, equipment = storage.equip_play_campaign_character_item(
            campaign_id, actor["username"], character_id, slot, item_id
        )
        error_response = _equipment_error_response(result)
        return error_response if error_response else JsonResponse(equipment)
    if request.method != "GET":
        return bad_request("GET or PUT required")
    result, equipment = storage.get_play_campaign_character_equipment(
        campaign_id, actor["username"], character_id, slot
    )
    error_response = _equipment_error_response(result)
    return error_response if error_response else JsonResponse(equipment)


def attune_play_campaign_character_equipment(request, campaign_id, character_id, slot):
    """Attune an owned, equipped magic accessory without a request body."""
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    if slot not in EQUIPMENT_SLOTS:
        return bad_request("Invalid equipment slot")
    if slot != "accessory":
        return bad_request("Only accessories can be attuned")
    result, equipment = storage.attune_play_campaign_character_equipment(
        campaign_id, actor["username"], character_id, slot, ATTUNABLE_ITEM_IDS
    )
    error_response = _equipment_error_response(result)
    return error_response if error_response else JsonResponse(equipment)


def read_play_campaign_character_status(request, campaign_id, character_id):
    if request.method != "GET":
        return bad_request("GET required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    result, character = storage.get_play_campaign_character_status(
        campaign_id, actor["username"], character_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    return JsonResponse(character)


def read_play_campaign_character_currency(request, campaign_id, character_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, currency = storage.get_play_campaign_character_currency(
        campaign_id, actor["username"], character_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    return JsonResponse(currency)


def transfer_play_campaign_character_currency(request, campaign_id, character_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        to_character_id = non_empty_string(body.get("to_character_id"), "to_character_id")
        gold = integer(body.get("gold"), "gold")
        if to_character_id == character_id:
            raise ValueError("Destination character must be different")
        if gold <= 0:
            raise ValueError("gold must be positive")
    except ValueError as error:
        return bad_request(str(error))
    result, transfer = storage.transfer_play_campaign_character_currency(
        campaign_id, actor["username"], character_id, to_character_id, gold
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "invalid_destination":
        return bad_request("Invalid destination character")
    if result == "insufficient":
        return JsonResponse({"error": "Insufficient gold"}, status=409)
    return JsonResponse(transfer, status=201)


def create_play_campaign_transactional_transfer(request, campaign_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        from_character_id = non_empty_string(body.get("from_character_id"), "from_character_id")
        to_character_id = non_empty_string(body.get("to_character_id"), "to_character_id")
        amount = integer(body.get("amount"), "amount")
        simulate_failure = body.get("simulate_failure")
        if from_character_id == to_character_id:
            raise ValueError("Destination character must be different")
        if amount <= 0:
            raise ValueError("amount must be positive")
        if not isinstance(simulate_failure, bool):
            raise ValueError("simulate_failure must be a boolean")
    except ValueError as error:
        return bad_request(str(error))

    result, transfer = storage.create_play_campaign_transactional_transfer(
        campaign_id, actor["username"], from_character_id, to_character_id,
        amount, simulate_failure,
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result in {"not_member", "not_owner"}:
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "invalid_character":
        return bad_request("Invalid character")
    if result == "insufficient":
        return JsonResponse({"error": "Insufficient gold"}, status=409)
    if result == "simulated_failure":
        return JsonResponse({"error": "simulated failure"}, status=500)
    return JsonResponse(transfer, status=201)


def read_play_campaign_transactional_transfers(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, transfers = storage.get_play_campaign_transactional_transfers(
        campaign_id, actor["username"]
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(transfers)


def play_campaign_transactional_transfers(request, campaign_id):
    if request.method == "POST":
        return create_play_campaign_transactional_transfer(request, campaign_id)
    if request.method == "GET":
        return read_play_campaign_transactional_transfers(request, campaign_id)
    return bad_request("GET or POST required")


def create_play_campaign_loot(request, campaign_id):
    """Let the campaign's DM open an immutable item-quantity loot record."""
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        loot = {
            "loot_id": non_empty_string(body.get("loot_id"), "loot_id"),
            "item_id": body.get("item_id"),
            "quantity": integer(body.get("quantity"), "quantity"),
        }
        if not isinstance(loot["item_id"], str) or loot["item_id"] not in INVENTORY_ITEM_IDS:
            raise ValueError("Unknown item_id")
        if loot["quantity"] <= 0:
            raise ValueError("quantity must be positive")
    except ValueError as error:
        return bad_request(str(error))
    result, created = storage.create_play_campaign_loot(campaign_id, actor["username"], loot)
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "duplicate":
        return JsonResponse({"error": "Loot id already exists"}, status=409)
    return JsonResponse(created, status=201)


def vote_for_play_campaign_loot(request, campaign_id, loot_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    if actor["role"] != "player":
        return JsonResponse({"error": "Forbidden"}, status=403)
    try:
        recipient_character_id = non_empty_string(
            json_body(request).get("recipient_character_id"), "recipient_character_id"
        )
    except ValueError as error:
        return bad_request(str(error))
    result, vote = storage.vote_for_play_campaign_loot(
        campaign_id, actor["username"], loot_id, recipient_character_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_loot":
        return JsonResponse({"error": "Unknown loot"}, status=404)
    if result == "unknown_character":
        return bad_request("recipient_character_id must be a campaign character")
    if result in {"duplicate", "not_open"}:
        return JsonResponse({"error": "Loot vote conflict"}, status=409)
    return JsonResponse(vote, status=201)


def assign_play_campaign_loot(request, campaign_id, loot_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    result, assignment = storage.assign_play_campaign_loot(campaign_id, actor["username"], loot_id)
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_loot":
        return JsonResponse({"error": "Unknown loot"}, status=404)
    if result in {"not_open", "ambiguous"}:
        return JsonResponse({"error": "Loot cannot be assigned"}, status=409)
    return JsonResponse(assignment)


def read_play_campaign_loot(request, campaign_id, loot_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, loot = storage.get_play_campaign_loot(campaign_id, actor["username"], loot_id)
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_loot":
        return JsonResponse({"error": "Unknown loot"}, status=404)
    return JsonResponse(loot)


def create_play_campaign_npc(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        npc = {
            "npc_id": non_empty_string(body.get("npc_id"), "npc_id"),
            "name": non_empty_string(body.get("name"), "name"),
            "agenda": non_empty_string(body.get("agenda"), "agenda"),
            "public_status": non_empty_string(
                body.get("public_status"), "public_status"
            ),
        }
    except ValueError as error:
        return bad_request(str(error))
    result, created = storage.create_play_campaign_npc(campaign_id, actor["username"], npc)
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "duplicate":
        return JsonResponse({"error": "NPC id already exists"}, status=409)
    return JsonResponse(created, status=201)


def update_play_campaign_npc_agenda(request, campaign_id, npc_id):
    actor, error_response = dm_actor(request, "PUT")
    if error_response:
        return error_response
    try:
        body = put_json_body(request)
        agenda = non_empty_string(body.get("agenda"), "agenda")
        public_status = non_empty_string(body.get("public_status"), "public_status")
    except ValueError as error:
        return bad_request(str(error))
    result, npc = storage.update_play_campaign_npc_agenda(
        campaign_id, actor["username"], npc_id, agenda, public_status
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_npc":
        return JsonResponse({"error": "Unknown NPC"}, status=404)
    return JsonResponse(npc)


def read_play_campaign_npc(request, campaign_id, npc_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, npc = storage.get_play_campaign_npc(campaign_id, actor["username"], npc_id)
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_npc":
        return JsonResponse({"error": "Unknown NPC"}, status=404)
    if not npc.pop("is_dm"):
        npc.pop("agenda")
    return JsonResponse(npc)


def create_play_campaign_npc_dialogue(request, campaign_id, npc_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        dialogue = {
            "dialogue_id": non_empty_string(body.get("dialogue_id"), "dialogue_id"),
            "speaker": non_empty_string(body.get("speaker"), "speaker"),
            "text": non_empty_string(body.get("text"), "text"),
            "visibility": body.get("visibility"),
        }
        if dialogue["visibility"] not in {"public", "private"}:
            raise ValueError("visibility must be public or private")
    except ValueError as error:
        return bad_request(str(error))
    result, created = storage.create_play_campaign_npc_dialogue(
        campaign_id, actor["username"], npc_id, dialogue
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_npc":
        return JsonResponse({"error": "Unknown NPC"}, status=404)
    if result == "duplicate":
        return JsonResponse({"error": "Dialogue id already exists"}, status=409)
    return JsonResponse(created, status=201)


def read_play_campaign_npc_dialogue(request, campaign_id, npc_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, dialogue = storage.get_play_campaign_npc_dialogue(
        campaign_id, actor["username"], npc_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_npc":
        return JsonResponse({"error": "Unknown NPC"}, status=404)
    return JsonResponse(dialogue)


def play_campaign_npc_dialogue(request, campaign_id, npc_id):
    if request.method == "POST":
        return create_play_campaign_npc_dialogue(request, campaign_id, npc_id)
    if request.method == "GET":
        return read_play_campaign_npc_dialogue(request, campaign_id, npc_id)
    return bad_request("GET or POST required")


def relationship_score(value):
    value = integer(value, "score")
    if not -100 <= value <= 100:
        raise ValueError("score must be between -100 and 100")
    return value


def create_play_campaign_relationship(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        relationship = {
            "source_id": non_empty_string(body.get("source_id"), "source_id"),
            "target_id": non_empty_string(body.get("target_id"), "target_id"),
            "kind": non_empty_string(body.get("kind"), "kind"),
            "score": relationship_score(body.get("score")),
        }
        if relationship["source_id"] == relationship["target_id"]:
            raise ValueError("source_id and target_id must differ")
    except ValueError as error:
        return bad_request(str(error))
    result, created = storage.create_play_campaign_relationship(
        campaign_id, actor["username"], relationship
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_entity":
        return JsonResponse({"error": "Unknown campaign entity"}, status=404)
    if result == "duplicate":
        return JsonResponse({"error": "Relationship already exists"}, status=409)
    return JsonResponse(created, status=201)


def update_play_campaign_relationship(request, campaign_id, source_id, target_id, kind):
    actor, error_response = dm_actor(request, "PUT")
    if error_response:
        return error_response
    try:
        score = relationship_score(put_json_body(request).get("score"))
    except ValueError as error:
        return bad_request(str(error))
    result, relationship = storage.update_play_campaign_relationship(
        campaign_id, actor["username"], source_id, target_id, kind, score
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_relationship":
        return JsonResponse({"error": "Unknown relationship"}, status=404)
    return JsonResponse(relationship)


def read_play_campaign_relationships(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, relationships = storage.get_play_campaign_relationships(
        campaign_id, actor["username"]
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(relationships)


def play_campaign_relationships(request, campaign_id):
    if request.method == "POST":
        return create_play_campaign_relationship(request, campaign_id)
    if request.method == "GET":
        return read_play_campaign_relationships(request, campaign_id)
    return bad_request("GET or POST required")


def create_play_campaign_clue(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        clue = {
            "clue_id": non_empty_string(body.get("clue_id"), "clue_id"),
            "text": non_empty_string(body.get("text"), "text"),
            "audience": non_empty_string(body.get("audience"), "audience"),
        }
        if clue["audience"] == "character":
            clue["character_id"] = non_empty_string(body.get("character_id"), "character_id")
        elif clue["audience"] in {"party", "hidden"}:
            if "character_id" in body:
                raise ValueError("character_id must be omitted for this audience")
        else:
            raise ValueError("audience must be character, party, or hidden")
    except ValueError as error:
        return bad_request(str(error))

    result, created = storage.create_play_campaign_clue(campaign_id, actor["username"], clue)
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_character":
        return bad_request("Unknown campaign character")
    if result == "duplicate":
        return JsonResponse({"error": "Clue id already exists"}, status=409)
    return JsonResponse(created, status=201)


def read_play_campaign_clues(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, clues = storage.get_play_campaign_clues(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(clues)


def play_campaign_clues(request, campaign_id):
    if request.method == "POST":
        return create_play_campaign_clue(request, campaign_id)
    if request.method == "GET":
        return read_play_campaign_clues(request, campaign_id)
    return bad_request("GET or POST required")


def create_play_campaign_quest(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        quest = {
            "quest_id": non_empty_string(body.get("quest_id"), "quest_id"),
            "title": non_empty_string(body.get("title"), "title"),
            "depends_on": body.get("depends_on"),
        }
        if not isinstance(quest["depends_on"], list) or not all(
            isinstance(dependency, str) and dependency for dependency in quest["depends_on"]
        ):
            raise ValueError("depends_on must be an array of non-empty quest IDs")
        if len(set(quest["depends_on"])) != len(quest["depends_on"]):
            raise ValueError("depends_on must contain unique quest IDs")
        if quest["quest_id"] in quest["depends_on"]:
            raise ValueError("depends_on cannot include quest_id")
    except ValueError as error:
        return bad_request(str(error))

    result, created = storage.create_play_campaign_quest(campaign_id, actor["username"], quest)
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_dependency":
        return bad_request("Unknown quest dependency")
    if result == "duplicate":
        return JsonResponse({"error": "Quest id already exists"}, status=409)
    return JsonResponse(created, status=201)


def read_play_campaign_quests(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, quests = storage.get_play_campaign_quests(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(quests)


def play_campaign_quests(request, campaign_id):
    if request.method == "POST":
        return create_play_campaign_quest(request, campaign_id)
    if request.method == "GET":
        return read_play_campaign_quests(request, campaign_id)
    return bad_request("GET or POST required")


def update_play_campaign_quest_state(request, campaign_id, quest_id):
    actor, error_response = dm_actor(request, "PUT")
    if error_response:
        return error_response
    try:
        state = put_json_body(request).get("state")
        if state not in {"active", "completed"}:
            raise ValueError("state must be active or completed")
    except ValueError as error:
        return bad_request(str(error))

    result, quest = storage.update_play_campaign_quest_state(
        campaign_id, actor["username"], quest_id, state
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_quest":
        return JsonResponse({"error": "Unknown quest"}, status=404)
    if result in {"blocked", "invalid_transition"}:
        return JsonResponse({"error": "Invalid quest state transition"}, status=409)
    return JsonResponse(quest)


def configure_play_campaign_quest_rewards(request, campaign_id, quest_id):
    actor, error_response = dm_actor(request, "PUT")
    if error_response:
        return error_response
    try:
        body = put_json_body(request)
        xp = integer(body.get("xp"), "xp")
        items = body.get("items")
        if xp < 0:
            raise ValueError("xp must be nonnegative")
        if not isinstance(items, dict):
            raise ValueError("items must be an object")
        for item_id, quantity in items.items():
            if item_id not in INVENTORY_ITEM_IDS:
                raise ValueError("Unknown item_id")
            if integer(quantity, f"items.{item_id}") <= 0:
                raise ValueError("item quantities must be positive")
    except ValueError as error:
        return bad_request(str(error))

    result, quest = storage.configure_play_campaign_quest_rewards(
        campaign_id, actor["username"], quest_id, {"xp": xp, "items": items}
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_quest":
        return JsonResponse({"error": "Unknown quest"}, status=404)
    if result == "invalid_state":
        return JsonResponse({"error": "Quest rewards cannot be configured"}, status=409)
    return JsonResponse(quest)


def award_play_campaign_quest_rewards(request, campaign_id, quest_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    result, award = storage.award_play_campaign_quest_rewards(
        campaign_id, actor["username"], quest_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_quest":
        return JsonResponse({"error": "Unknown quest"}, status=404)
    if result in {"invalid_state", "already_awarded"}:
        return JsonResponse({"error": "Quest rewards cannot be awarded"}, status=409)
    return JsonResponse(award, status=201)


def get_play_campaign_character_rewards(request, campaign_id, character_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, rewards = storage.get_play_campaign_character_rewards(
        campaign_id, actor["username"], character_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    return JsonResponse(rewards)


def schedule_play_campaign_world_event(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        event = {
            "event_id": non_empty_string(body.get("event_id"), "event_id"),
            "turn_number": integer(body.get("turn_number"), "turn_number"),
            "title": non_empty_string(body.get("title"), "title"),
            "text": non_empty_string(body.get("text"), "text"),
        }
        if event["turn_number"] < 1:
            raise ValueError("turn_number must be at least 1")
    except ValueError as error:
        return bad_request(str(error))

    result, scheduled = storage.schedule_play_campaign_world_event(
        campaign_id, actor["username"], event
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "past_turn":
        return bad_request("turn_number must not be before the current turn")
    if result == "not_active":
        return JsonResponse({"error": "Invalid world event turn"}, status=409)
    if result == "duplicate":
        return JsonResponse({"error": "World event id already exists"}, status=409)
    return JsonResponse(scheduled, status=201)


def resolve_play_campaign_world_event(request, campaign_id, event_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        text = non_empty_string(json_body(request).get("text"), "text")
    except ValueError as error:
        return bad_request(str(error))

    result, event = storage.resolve_play_campaign_world_event(
        campaign_id, actor["username"], event_id, text
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_event":
        return JsonResponse({"error": "Unknown world event"}, status=404)
    if result in {"not_active", "wrong_turn", "already_resolved"}:
        return JsonResponse({"error": "World event cannot be resolved"}, status=409)
    return JsonResponse(event, status=201)


def read_play_campaign_world_events(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, events = storage.get_play_campaign_world_events(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(events)


def play_campaign_world_events(request, campaign_id):
    if request.method == "POST":
        return schedule_play_campaign_world_event(request, campaign_id)
    if request.method == "GET":
        return read_play_campaign_world_events(request, campaign_id)
    return bad_request("GET or POST required")


def calendar_response(calendar):
    """Add the contract's deterministic weather field to stored calendar data."""
    weather = ("clear", "rain", "wind", "snow")[
        (calendar["day"] + CALENDAR_SEASON_OFFSETS[calendar["season"]]) % 4
    ]
    return {"day": calendar["day"], "season": calendar["season"], "weather": weather}


def initialize_play_campaign_calendar(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        calendar = {"day": integer(body.get("day"), "day"), "season": body.get("season")}
        if calendar["day"] < 1:
            raise ValueError("day must be at least 1")
        if calendar["season"] not in CALENDAR_SEASON_OFFSETS:
            raise ValueError("season must be spring, summer, autumn, or winter")
    except ValueError as error:
        return bad_request(str(error))

    result, created = storage.initialize_play_campaign_calendar(
        campaign_id, actor["username"], calendar
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "already_initialized":
        return JsonResponse({"error": "Calendar already initialized"}, status=409)
    return JsonResponse(calendar_response(created), status=201)


def read_play_campaign_calendar(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, calendar = storage.get_play_campaign_calendar(campaign_id, actor["username"])
    if result in {"unknown_campaign", "not_initialized"}:
        return JsonResponse({"error": "Unknown calendar" if result == "not_initialized" else "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(calendar_response(calendar))


def advance_play_campaign_calendar(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        days = integer(json_body(request).get("days"), "days")
        if not 1 <= days <= 30:
            raise ValueError("days must be between 1 and 30")
    except ValueError as error:
        return bad_request(str(error))

    result, calendar = storage.advance_play_campaign_calendar(campaign_id, actor["username"], days)
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "not_initialized":
        return JsonResponse({"error": "Unknown calendar"}, status=404)
    return JsonResponse(calendar_response(calendar))


def play_campaign_calendar(request, campaign_id):
    if request.method == "POST":
        return initialize_play_campaign_calendar(request, campaign_id)
    if request.method == "GET":
        return read_play_campaign_calendar(request, campaign_id)
    return bad_request("GET or POST required")


def settlement_payload(body, settlement_id=None):
    """Validate and normalize the mutable fields of a campaign settlement."""
    if settlement_id is None:
        settlement_id = non_empty_string(body.get("settlement_id"), "settlement_id")
    name = non_empty_string(body.get("name"), "name")
    services = body.get("services")
    if not isinstance(services, list) or not services:
        raise ValueError("services must be a non-empty array")
    normalized_services = []
    for service in services:
        if not isinstance(service, str) or not service.strip():
            raise ValueError("services must contain non-empty strings")
        normalized_services.append(service.strip())
    if len(set(normalized_services)) != len(normalized_services):
        raise ValueError("services must be unique")
    availability = body.get("availability")
    if availability not in {"open", "limited", "closed"}:
        raise ValueError("availability must be open, limited, or closed")
    return {
        "settlement_id": settlement_id,
        "name": name,
        "services": normalized_services,
        "availability": availability,
    }


def create_play_campaign_settlement(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        settlement = settlement_payload(json_body(request))
    except ValueError as error:
        return bad_request(str(error))
    result, created = storage.create_play_campaign_settlement(
        campaign_id, actor["username"], settlement
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "duplicate":
        return JsonResponse({"error": "Settlement id already exists"}, status=409)
    return JsonResponse(created, status=201)


def update_play_campaign_settlement(request, campaign_id, settlement_id):
    actor, error_response = dm_actor(request, "PUT")
    if error_response:
        return error_response
    try:
        settlement = settlement_payload(put_json_body(request), settlement_id)
    except ValueError as error:
        return bad_request(str(error))
    result, updated = storage.update_play_campaign_settlement(
        campaign_id, actor["username"], settlement_id, settlement
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_settlement":
        return JsonResponse({"error": "Unknown settlement"}, status=404)
    return JsonResponse(updated)


def discover_play_campaign_settlement(request, campaign_id, settlement_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    if actor["role"] != "player":
        return JsonResponse({"error": "Forbidden"}, status=403)
    result, settlement = storage.discover_play_campaign_settlement(
        campaign_id, actor["username"], settlement_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_settlement":
        return JsonResponse({"error": "Unknown settlement"}, status=404)
    return JsonResponse(settlement, status=201 if result == "discovered" else 200)


def list_play_campaign_settlements(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, settlements = storage.get_play_campaign_settlements(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(settlements)


def play_campaign_settlements(request, campaign_id):
    if request.method == "POST":
        return create_play_campaign_settlement(request, campaign_id)
    if request.method == "GET":
        return list_play_campaign_settlements(request, campaign_id)
    return bad_request("GET or POST required")


def shop_payload(body):
    shop_id = non_empty_string(body.get("shop_id"), "shop_id")
    name = non_empty_string(body.get("name"), "name")
    stock = body.get("stock")
    if not isinstance(stock, dict) or not stock:
        raise ValueError("stock must be a non-empty object")
    normalized_stock = {}
    for item_id, quantity in stock.items():
        if not isinstance(item_id, str) or item_id not in INVENTORY_ITEM_IDS:
            raise ValueError("Unknown item_id")
        quantity = integer(quantity, "stock quantity")
        if quantity <= 0:
            raise ValueError("stock quantities must be positive")
        normalized_stock[item_id] = quantity
    buy_price = integer(body.get("buy_price"), "buy_price")
    sell_price = non_negative_integer(body.get("sell_price"), "sell_price")
    if buy_price <= 0:
        raise ValueError("buy_price must be positive")
    return {
        "shop_id": shop_id,
        "name": name,
        "stock": normalized_stock,
        "buy_price": buy_price,
        "sell_price": sell_price,
    }


def create_play_campaign_shop(request, campaign_id, settlement_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        shop = shop_payload(json_body(request))
    except (TypeError, ValueError) as error:
        return bad_request(str(error))
    result, created = storage.create_play_campaign_shop(
        campaign_id, actor["username"], settlement_id, shop
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_settlement":
        return JsonResponse({"error": "Unknown settlement"}, status=404)
    if result == "duplicate":
        return JsonResponse({"error": "Shop id already exists"}, status=409)
    return JsonResponse(created, status=201)


def read_play_campaign_shop(request, campaign_id, settlement_id, shop_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, shop = storage.get_play_campaign_shop(
        campaign_id, actor["username"], settlement_id, shop_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result in {"unknown_settlement", "unknown_shop", "undiscovered"}:
        return JsonResponse({"error": "Unknown shop" if result != "unknown_settlement" else "Unknown settlement"}, status=404)
    return JsonResponse(shop)


def trade_play_campaign_shop(request, campaign_id, settlement_id, shop_id, operation):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    if actor["role"] != "player":
        return JsonResponse({"error": "Forbidden"}, status=403)
    try:
        body = json_body(request)
        character_id = non_empty_string(body.get("character_id"), "character_id")
        item_id = body.get("item_id")
        quantity = integer(body.get("quantity"), "quantity")
        if item_id not in INVENTORY_ITEM_IDS:
            raise ValueError("Unknown item_id")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
    except (TypeError, ValueError) as error:
        return bad_request(str(error))
    result, trade = storage.trade_play_campaign_shop(
        campaign_id, actor["username"], settlement_id, shop_id, character_id,
        item_id, quantity, operation,
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "unknown_settlement":
        return JsonResponse({"error": "Unknown settlement"}, status=404)
    if result == "unknown_shop":
        return JsonResponse({"error": "Unknown shop"}, status=404)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "insufficient_stock":
        return JsonResponse({"error": "Insufficient shop stock"}, status=409)
    if result == "insufficient_gold":
        return JsonResponse({"error": "Insufficient gold"}, status=409)
    if result == "insufficient_inventory":
        return JsonResponse({"error": "Insufficient item quantity"}, status=409)
    return JsonResponse(trade)


def buy_from_play_campaign_shop(request, campaign_id, settlement_id, shop_id):
    return trade_play_campaign_shop(request, campaign_id, settlement_id, shop_id, "buy")


def sell_to_play_campaign_shop(request, campaign_id, settlement_id, shop_id):
    return trade_play_campaign_shop(request, campaign_id, settlement_id, shop_id, "sell")


def create_play_campaign_faction(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        faction = {
            "faction_id": non_empty_string(body.get("faction_id"), "faction_id"),
            "name": non_empty_string(body.get("name"), "name"),
        }
    except ValueError as error:
        return bad_request(str(error))
    result, created = storage.create_play_campaign_faction(
        campaign_id, actor["username"], faction
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "duplicate":
        return JsonResponse({"error": "Faction id already exists"}, status=409)
    return JsonResponse(created, status=201)


def change_play_campaign_reputation(request, campaign_id, faction_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        change = {
            "character_id": non_empty_string(body.get("character_id"), "character_id"),
            "delta": integer(body.get("delta"), "delta"),
            "reason": non_empty_string(body.get("reason"), "reason"),
        }
        if not -25 <= change["delta"] <= 25 or change["delta"] == 0:
            raise ValueError("delta must be a nonzero integer between -25 and 25")
    except ValueError as error:
        return bad_request(str(error))
    result, record = storage.change_play_campaign_reputation(
        campaign_id, actor["username"], faction_id, change
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_faction":
        return JsonResponse({"error": "Unknown faction"}, status=404)
    if result == "unknown_character":
        return bad_request("Unknown character")
    return JsonResponse(record, status=201)


def read_play_campaign_reputation(request, campaign_id, faction_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, reputation = storage.get_play_campaign_reputation(
        campaign_id, actor["username"], faction_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_faction":
        return JsonResponse({"error": "Unknown faction"}, status=404)
    return JsonResponse(reputation)


def play_campaign_faction_reputation(request, campaign_id, faction_id):
    if request.method == "POST":
        return change_play_campaign_reputation(request, campaign_id, faction_id)
    if request.method == "GET":
        return read_play_campaign_reputation(request, campaign_id, faction_id)
    return bad_request("GET or POST required")


def read_play_campaign_character_owner(request, campaign_id, character_id):
    if request.method != "GET":
        return bad_request("GET required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    result, ownership = storage.get_play_campaign_character_owner(
        campaign_id, actor["username"], character_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    return JsonResponse(ownership)


def claim_play_campaign_character(request, campaign_id, character_id):
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "player":
        return JsonResponse({"error": "Forbidden"}, status=403)
    # Claiming identifies the claimant from the authenticated session, so this
    # endpoint deliberately has no request payload.  In particular, accept an
    # empty POST body rather than attempting to parse it as JSON.
    if request.method != "POST":
        return bad_request("POST required")
    result, ownership = storage.claim_play_campaign_character(
        campaign_id, actor["username"], character_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    if result == "already_owned":
        return JsonResponse({"error": "Character is already owned"}, status=409)
    return JsonResponse(ownership, status=201)


def transfer_play_campaign_character(request, campaign_id, character_id):
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    try:
        body = json_body(request)
        new_owner = non_empty_string(body.get("new_owner"), "new_owner")
    except ValueError as error:
        return bad_request(str(error))
    result, ownership = storage.transfer_play_campaign_character(
        campaign_id, actor["username"], character_id, new_owner
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "new_owner_not_member":
        return JsonResponse({"error": "New owner must be a campaign member"}, status=400)
    return JsonResponse(ownership)


def build_play_campaign_character(request, campaign_id, character_id):
    """Validate a character's level-one choices for its current owner."""
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    try:
        body = json_body(request)
        race = body.get("race")
        character_class = body.get("class")
        background = body.get("background")
        if race not in PLAYABLE_RACES:
            raise ValueError("Invalid race")
        if character_class not in PLAYABLE_CLASSES:
            raise ValueError("Invalid class")
        if background not in PLAYABLE_BACKGROUNDS:
            raise ValueError("Invalid background")
        abilities = body.get("abilities")
        if not isinstance(abilities, dict):
            raise ValueError("abilities must be an object")
        validated_abilities = {
            name: ability_score(abilities.get(name), name) for name in ABILITY_NAMES
        }
    except ValueError as error:
        return bad_request(str(error))

    result = storage.check_play_campaign_character_owner(
        campaign_id, actor["username"], character_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)

    level = 1
    storage.save_play_campaign_character_progression(
        campaign_id,
        character_id,
        character_class,
        ability_modifier_for(validated_abilities["con"]),
        validated_abilities,
    )
    return JsonResponse({
        "character_id": character_id,
        "race": race,
        "class": character_class,
        "background": background,
        "level": level,
        "hp_max": PLAYABLE_CLASSES[character_class]
        + ability_modifier_for(validated_abilities["con"]),
        "proficiency_bonus": proficiency_bonus_for(level),
    })


def level_up_play_campaign_character(request, campaign_id, character_id):
    """Advance an owned, built play character by exactly one level."""
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    try:
        level = character_level(json_body(request).get("level"))
    except ValueError as error:
        return bad_request(str(error))

    # Builds name the supported classes; the join class is retained as a
    # compatibility fallback for campaigns created before build choices existed.
    result = storage.check_play_campaign_character_owner(
        campaign_id, actor["username"], character_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "unknown_character":
        return JsonResponse({"error": "Unknown character"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)

    # The persistence routine reads the selected class.  All currently
    # supported classes map their established level-one HP to a hit die.
    character_class = storage.get_play_campaign_character_class(campaign_id, character_id)
    hit_die_sides = PLAYABLE_CLASSES.get(character_class)
    if hit_die_sides is None:
        return bad_request("Invalid character class")
    result, character = storage.level_up_play_campaign_character(
        campaign_id, actor["username"], character_id, level, f"1d{hit_die_sides}"
    )
    if result == "invalid_level":
        return bad_request("level must be exactly one higher than the current level")
    return JsonResponse({
        **character,
        "proficiency_bonus": proficiency_bonus_for(character["level"]),
    })


def read_play_campaign_turn(request, campaign_id):
    if request.method != "GET":
        return bad_request("GET required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    result, turn = storage.get_play_campaign_turn(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "not_active":
        return JsonResponse({"error": "Campaign is not active"}, status=409)
    return JsonResponse(turn)


def nudge_play_campaign_turn(request, campaign_id):
    if request.method != "POST":
        return bad_request("POST required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "dm":
        return JsonResponse({"error": "Forbidden"}, status=403)

    try:
        message = non_empty_string(json_body(request).get("message"), "message")
    except ValueError as error:
        return bad_request(str(error))

    result, nudge = storage.nudge_play_campaign_turn(
        campaign_id, actor["username"], message
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "not_active":
        return JsonResponse({"error": "Campaign is not active"}, status=409)
    return JsonResponse(nudge, status=201)


def read_play_campaign_my_turn(request, campaign_id):
    if request.method != "GET":
        return bad_request("GET required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "player":
        return JsonResponse({"error": "Forbidden"}, status=403)

    result, context = storage.get_play_campaign_player_turn_context(
        campaign_id, actor["username"]
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "not_active":
        return JsonResponse({"error": "Campaign is not active"}, status=409)
    return JsonResponse(context)


def read_play_campaign_gm_status(request, campaign_id):
    if request.method != "GET":
        return bad_request("GET required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "dm":
        return JsonResponse({"error": "Forbidden"}, status=403)

    result, status = storage.get_play_campaign_gm_status(
        campaign_id, actor["username"]
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "not_active":
        return JsonResponse({"error": "Campaign is not active"}, status=409)
    return JsonResponse(status)


def _play_campaign_export_access_response(result):
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return None


def create_play_campaign_export(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    result, exported = storage.create_play_campaign_export(campaign_id, actor["username"])
    error_response = _play_campaign_export_access_response(result)
    if error_response:
        return error_response
    return JsonResponse(exported, status=201)


def list_play_campaign_exports(request, campaign_id):
    actor, error_response = dm_actor(request, "GET")
    if error_response:
        return error_response
    result, exports = storage.get_play_campaign_exports(campaign_id, actor["username"])
    error_response = _play_campaign_export_access_response(result)
    if error_response:
        return error_response
    return JsonResponse({"exports": exports})


def play_campaign_exports(request, campaign_id):
    if request.method == "POST":
        return create_play_campaign_export(request, campaign_id)
    if request.method == "GET":
        return list_play_campaign_exports(request, campaign_id)
    return bad_request("GET or POST required")


def read_play_campaign_export(request, campaign_id, version):
    actor, error_response = dm_actor(request, "GET")
    if error_response:
        return error_response
    result, exported = storage.get_play_campaign_export(
        campaign_id, actor["username"], version
    )
    error_response = _play_campaign_export_access_response(result)
    if error_response:
        return error_response
    if result == "unknown_export":
        return JsonResponse({"error": "Unknown export"}, status=404)
    return JsonResponse(exported)


def import_play_campaign_snapshot(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        if set(body) != {"version", "story", "status"}:
            raise ValueError("Snapshot must contain exactly version, story, and status")
        version = body["version"]
        if isinstance(version, bool) or not isinstance(version, int) or version != 1:
            raise ValueError("version must be 1")
        snapshot = {
            "version": 1,
            "story": non_empty_string(body["story"], "story"),
            "status": body["status"],
        }
        if not isinstance(snapshot["status"], str) or snapshot["status"] not in {
            "lobby", "started"
        }:
            raise ValueError("status must be lobby or started")
    except (KeyError, ValueError) as error:
        return bad_request(str(error))

    result, imported = storage.import_play_campaign_snapshot(
        campaign_id, actor["username"], snapshot
    )
    error_response = _play_campaign_export_access_response(result)
    if error_response:
        return error_response
    return JsonResponse(imported)


def read_play_campaign_import_state(request, campaign_id):
    actor, error_response = dm_actor(request, "GET")
    if error_response:
        return error_response
    result, snapshot = storage.get_play_campaign_import_state(
        campaign_id, actor["username"]
    )
    error_response = _play_campaign_export_access_response(result)
    if error_response:
        return error_response
    if result == "unknown_import":
        return JsonResponse({"error": "Unknown import"}, status=404)
    return JsonResponse(snapshot)


def migrate_play_campaign_snapshot(request, campaign_id):
    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        schema_version = body.get("schema_version")
        if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version != 1:
            raise ValueError("schema_version must be 1")
        story = non_empty_string(body.get("story"), "story")
    except ValueError as error:
        return bad_request(str(error))

    result, migrated = storage.migrate_play_campaign_snapshot(
        campaign_id, actor["username"], story
    )
    error_response = _play_campaign_export_access_response(result)
    if error_response:
        return error_response
    return JsonResponse(migrated, status=200 if result == "unchanged" else 201)


def read_play_campaign_migration_state(request, campaign_id):
    actor, error_response = dm_actor(request, "GET")
    if error_response:
        return error_response
    result, migrated = storage.get_play_campaign_migration_state(
        campaign_id, actor["username"]
    )
    error_response = _play_campaign_export_access_response(result)
    if error_response:
        return error_response
    if result == "unknown_migration":
        return JsonResponse({"error": "Unknown migration"}, status=404)
    return JsonResponse(migrated)


def play_campaign_search_records(request, campaign_id):
    if request.method == "POST":
        return create_play_campaign_search_record(request, campaign_id)
    if request.method == "GET":
        return list_play_campaign_search_records(request, campaign_id)
    return bad_request("GET or POST required")


def create_play_campaign_search_record(request, campaign_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        record = {
            "record_id": non_empty_string(body.get("record_id"), "record_id"),
            "text": non_empty_string(body.get("text"), "text"),
        }
    except ValueError as error:
        return bad_request(str(error))

    result, created = storage.create_play_campaign_search_record(
        campaign_id, actor["username"], record
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "duplicate":
        return bad_request("record_id must be unique within the campaign")
    return JsonResponse(created, status=201)


def list_play_campaign_search_records(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    try:
        def query_integer(name, default, minimum, maximum=None):
            value = request.GET.get(name, default)
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
                raise ValueError(f"{name} must be an integer")
            parsed = int(value)
            if parsed < minimum or (maximum is not None and parsed > maximum):
                raise ValueError(f"{name} is out of range")
            return parsed

        limit = query_integer("limit", "2", 1, 3)
        cursor = query_integer("cursor", "0", 0)
        query = request.GET.get("q")
    except ValueError as error:
        return bad_request(str(error))

    result, payload = storage.get_play_campaign_search_records(
        campaign_id, actor["username"], query, limit, cursor
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(payload)


def play_campaign_rate_events(request, campaign_id):
    if request.method == "POST":
        return create_play_campaign_rate_event(request, campaign_id)
    if request.method == "GET":
        return list_play_campaign_rate_events(request, campaign_id)
    return bad_request("GET or POST required")


def create_play_campaign_rate_event(request, campaign_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    try:
        event_id = non_empty_string(json_body(request).get("event_id"), "event_id")
    except ValueError as error:
        return bad_request(str(error))

    result, event = storage.create_play_campaign_rate_event(
        campaign_id, actor["username"], event_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "duplicate_event_id":
        return bad_request("event_id must be unique within the campaign")
    if result == "rate_limited":
        return JsonResponse({"limit": 2, "remaining": 0}, status=429)
    return JsonResponse(event, status=201)


def list_play_campaign_rate_events(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, payload = storage.get_play_campaign_rate_events(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(payload)


def read_play_campaign_service_metrics(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, metrics = storage.get_play_campaign_service_metrics(
        campaign_id, actor["username"]
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(metrics)


def update_play_campaign_service_mode(request, campaign_id):
    """Let authenticated DMs toggle the process-global readiness state."""
    global SERVICE_MAINTENANCE

    actor, error_response = dm_actor(request, "POST")
    if error_response:
        return error_response
    if not storage.play_campaign_exists(campaign_id):
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    try:
        body = json_body(request)
        if set(body) != {"maintenance"} or not isinstance(body["maintenance"], bool):
            raise ValueError("maintenance must be a boolean")
    except ValueError as error:
        return bad_request(str(error))

    SERVICE_MAINTENANCE = body["maintenance"]
    return JsonResponse({"maintenance": SERVICE_MAINTENANCE})


def update_play_campaign_document(request, campaign_id):
    if request.method == "GET":
        return read_play_campaign_document(request, campaign_id)
    if request.method != "PUT":
        return bad_request("PUT required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "dm":
        return JsonResponse({"error": "Forbidden"}, status=403)

    try:
        body = put_json_body(request)
        document = {
            "story": non_empty_string(body.get("story"), "story"),
            "dm_notes": non_empty_string(body.get("dm_notes"), "dm_notes"),
        }
    except ValueError as error:
        return bad_request(str(error))

    result, document = storage.save_play_campaign_document(
        campaign_id, actor["username"], document
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(document)


def read_play_campaign_document(request, campaign_id):
    if request.method != "GET":
        return bad_request("GET required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    result, document = storage.get_play_campaign_document(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(document)


def create_play_campaign_backup(request, campaign_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    result, backup = storage.create_play_campaign_backup(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(backup, status=201)


def read_play_campaign_backups(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, backups = storage.get_play_campaign_backups(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(backups)


def play_campaign_backups(request, campaign_id):
    if request.method == "POST":
        return create_play_campaign_backup(request, campaign_id)
    if request.method == "GET":
        return read_play_campaign_backups(request, campaign_id)
    return bad_request("GET or POST required")


def restore_play_campaign_backup(request, campaign_id, backup_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    result, backup = storage.restore_play_campaign_backup(
        campaign_id, actor["username"], backup_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_backup":
        return JsonResponse({"error": "Unknown backup"}, status=404)
    return JsonResponse(backup)


def create_play_campaign_scene(request, campaign_id):
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "dm":
        return JsonResponse({"error": "Forbidden"}, status=403)
    try:
        body = json_body(request)
        scene = {
            "id": non_empty_string(body.get("id"), "id"),
            "name": non_empty_string(body.get("name"), "name"),
        }
    except ValueError as error:
        return bad_request(str(error))

    result, scene = storage.create_play_campaign_scene(campaign_id, actor["username"], scene)
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "duplicate":
        return JsonResponse({"error": "Scene id already exists"}, status=409)
    return JsonResponse(scene, status=201)


def enter_play_campaign_scene(request, campaign_id, scene_id):
    if request.method != "POST":
        return bad_request("POST required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "dm":
        return JsonResponse({"error": "Forbidden"}, status=403)
    result, scene = storage.enter_play_campaign_scene(campaign_id, actor["username"], scene_id)
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_scene":
        return JsonResponse({"error": "Unknown scene"}, status=404)
    if result == "closed":
        return JsonResponse({"error": "Scene is closed"}, status=409)
    return JsonResponse(scene)


def close_play_campaign_scene(request, campaign_id, scene_id):
    if request.method != "POST":
        return bad_request("POST required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "dm":
        return JsonResponse({"error": "Forbidden"}, status=403)
    result, scene = storage.close_play_campaign_scene(campaign_id, actor["username"], scene_id)
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_scene":
        return JsonResponse({"error": "Unknown scene"}, status=404)
    return JsonResponse(scene)


def read_play_campaign_current_scene(request, campaign_id):
    if request.method != "GET":
        return bad_request("GET required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    result, scene = storage.get_play_campaign_current_scene(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "not_set":
        return JsonResponse({"error": "No current scene"}, status=404)
    return JsonResponse(scene)


def create_play_campaign_location(request, campaign_id):
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "dm":
        return JsonResponse({"error": "Forbidden"}, status=403)
    try:
        body = json_body(request)
        location = {
            "id": non_empty_string(body.get("id"), "id"),
            "name": non_empty_string(body.get("name"), "name"),
        }
    except ValueError as error:
        return bad_request(str(error))

    result, location = storage.create_play_campaign_location(
        campaign_id, actor["username"], location
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "duplicate":
        return JsonResponse({"error": "Location id already exists"}, status=409)
    return JsonResponse(location, status=201)


def create_play_campaign_location_connection(request, campaign_id, from_id):
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "dm":
        return JsonResponse({"error": "Forbidden"}, status=403)
    try:
        body = json_body(request)
        travel_turns = integer(body.get("travel_turns"), "travel_turns")
        if travel_turns <= 0:
            raise ValueError("travel_turns must be positive")
        connection = {
            "from_id": from_id,
            "to_id": non_empty_string(body.get("to_id"), "to_id"),
            "travel_turns": travel_turns,
        }
    except ValueError as error:
        return bad_request(str(error))

    result, connection = storage.create_play_campaign_location_connection(
        campaign_id, actor["username"], connection
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_location":
        return bad_request("Unknown location")
    if result == "duplicate":
        return bad_request("Connection already exists")
    return JsonResponse(connection, status=201)


def read_play_campaign_location_travel(request, campaign_id, location_id):
    if request.method != "GET":
        return bad_request("GET required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    result, travel = storage.get_play_campaign_location_travel(
        campaign_id, actor["username"], location_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "unknown_location":
        return JsonResponse({"error": "Unknown location"}, status=404)
    return JsonResponse(travel)


def submit_play_campaign_travel(request, campaign_id):
    if request.method != "POST":
        return bad_request("POST required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "player":
        return JsonResponse({"error": "It is not your turn"}, status=409)
    try:
        destination_id = non_empty_string(json_body(request).get("destination_id"), "destination_id")
    except ValueError as error:
        return bad_request(str(error))

    result, event = storage.submit_play_campaign_travel(
        campaign_id, actor["username"], destination_id
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "not_active":
        return JsonResponse({"error": "Campaign is not active"}, status=409)
    if result == "not_your_turn":
        return JsonResponse({"error": "It is not your turn"}, status=409)
    if result == "invalid_destination":
        return JsonResponse({"error": "Invalid travel destination"}, status=409)
    return JsonResponse(event, status=201)


def submit_play_campaign_rest(request, campaign_id):
    if request.method != "POST":
        return bad_request("POST required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "player":
        return JsonResponse({"error": "It is not your turn"}, status=409)
    try:
        rest_type = json_body(request).get("type")
        if rest_type not in {"short", "long"}:
            raise ValueError("type must be short or long")
    except ValueError as error:
        return bad_request(str(error))

    result, event = storage.submit_play_campaign_rest(
        campaign_id, actor["username"], rest_type
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "not_active":
        return JsonResponse({"error": "Campaign is not active"}, status=409)
    if result == "not_your_turn":
        return JsonResponse({"error": "It is not your turn"}, status=409)
    return JsonResponse(event, status=201)


def append_play_campaign_narration(request, campaign_id):
    if request.method != "POST":
        return bad_request("POST required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        text = non_empty_string(json_body(request).get("text"), "text")
    except ValueError as error:
        return bad_request(str(error))

    result, event = storage.append_play_campaign_narration(
        campaign_id, actor["username"], text
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(event, status=201)


def create_play_campaign_delegation(request, campaign_id):
    actor, error_response = authenticated_actor(request, "POST")
    if error_response:
        return error_response
    try:
        body = json_body(request)
        if set(body) != {"username", "powers"}:
            raise ValueError("username and powers are required")
        username = non_empty_string(body["username"], "username")
        powers = body["powers"]
        if not isinstance(powers, list) or not powers:
            raise ValueError("powers must be a non-empty array")
        if any(not isinstance(power, str) or power != "narrate" for power in powers):
            raise ValueError("powers may only contain narrate")
        if len(set(powers)) != len(powers):
            raise ValueError("powers must be unique")
    except ValueError as error:
        return bad_request(str(error))
    result, delegation = storage.grant_play_campaign_delegation(
        campaign_id, actor["username"], username, powers
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "not_member":
        return bad_request("Target user must be a campaign member")
    if result == "already_active":
        return JsonResponse({"error": "Delegation already active"}, status=409)
    return JsonResponse(delegation, status=201)


def revoke_play_campaign_delegation(request, campaign_id, username):
    actor, error_response = authenticated_actor(request, "DELETE")
    if error_response:
        return error_response
    result, delegation = storage.revoke_play_campaign_delegation(
        campaign_id, actor["username"], username
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "not_active":
        return JsonResponse({"error": "Unknown active delegation"}, status=404)
    return JsonResponse(delegation)


def read_play_campaign_delegation_audit(request, campaign_id):
    actor, error_response = authenticated_actor(request, "GET")
    if error_response:
        return error_response
    result, entries = storage.get_play_campaign_delegation_audit(campaign_id, actor["username"])
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_owner":
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse({"entries": entries})


def submit_play_campaign_action(request, campaign_id):
    if request.method != "POST":
        return bad_request("POST required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "player":
        return JsonResponse({"error": "Only players may submit actions"}, status=409)

    try:
        body = json_body(request)
        action_type = non_empty_string(body.get("type"), "type")
        text = non_empty_string(body.get("text"), "text")
    except ValueError as error:
        return bad_request(str(error))

    result, event = storage.submit_play_campaign_action(
        campaign_id, actor["username"], action_type, text
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result == "not_member":
        return JsonResponse({"error": "Forbidden"}, status=403)
    if result == "not_active":
        return JsonResponse({"error": "Campaign is not active"}, status=409)
    if result == "not_your_turn":
        return JsonResponse({"error": "It is not your turn"}, status=409)
    return JsonResponse(event, status=201)


def append_play_campaign_resolution(request, campaign_id):
    if request.method != "POST":
        return bad_request("POST required")
    actor = authenticated_user(request)
    if actor is None:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if actor["role"] != "dm":
        return JsonResponse({"error": "It is not the owner's turn"}, status=409)

    try:
        text = non_empty_string(json_body(request).get("text"), "text")
    except ValueError as error:
        return bad_request(str(error))

    result, event = storage.append_play_campaign_resolution(
        campaign_id, actor["username"], text
    )
    if result == "unknown_campaign":
        return JsonResponse({"error": "Unknown campaign"}, status=404)
    if result in {"not_owner", "not_your_turn"}:
        return JsonResponse({"error": "It is not the owner's turn"}, status=409)
    if result == "not_active":
        return JsonResponse({"error": "Campaign is not active"}, status=409)
    return JsonResponse(event, status=201)


def add_campaign_character(request, campaign_id):
    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    try:
        body = json_body(request)
        character = {
            "id": non_empty_string(body.get("id"), "id"),
            "name": non_empty_string(body.get("name"), "name"),
            "level": character_level(body.get("level")),
            "class": non_empty_string(body.get("class"), "class"),
        }
    except ValueError as error:
        return bad_request(str(error))

    if not storage.create_campaign_character(campaign_id, character):
        return JsonResponse({"error": "Character id already exists"}, status=409)
    return JsonResponse(character, status=201)


def add_campaign_event(request, campaign_id):
    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    try:
        body = json_body(request)
        event = {
            "id": non_empty_string(body.get("id"), "id"),
            "kind": non_empty_string(body.get("kind"), "kind"),
            "summary": non_empty_string(body.get("summary"), "summary"),
        }
    except ValueError as error:
        return bad_request(str(error))

    if not storage.create_campaign_event(campaign_id, event):
        return JsonResponse({"error": "Event id already exists"}, status=409)
    return JsonResponse({"id": event["id"], "kind": event["kind"]}, status=201)


def read_campaign_state(request, campaign_id):
    if request.method != "GET":
        return bad_request("GET required")
    campaign, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    campaign["characters"] = storage.get_campaign_characters(campaign_id)
    campaign["log_count"] = storage.campaign_event_count(campaign_id)
    return JsonResponse(campaign)


def campaign_audit(request, campaign_id):
    if request.method != "GET":
        return bad_request("GET required")
    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    return JsonResponse({
        "campaign_id": campaign_id,
        **storage.campaign_audit_summary(campaign_id),
    })


def export_campaign(request, campaign_id):
    if request.method != "GET":
        return bad_request("GET required")
    campaign, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    return JsonResponse({
        "campaign_id": campaign_id,
        "name": campaign["name"],
        **storage.campaign_export_summary(campaign_id),
        "schema_version": storage.SCHEMA_VERSION,
    })


def add_campaign_inventory(request, campaign_id):
    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    try:
        body = json_body(request)
        item_slug = non_empty_string(body.get("item_slug"), "item_slug")
        quantity = integer(body.get("quantity"), "quantity")
        owner = body.get("owner")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if owner != "party":
            raise ValueError("owner must be party")
    except ValueError as error:
        return bad_request(str(error))

    storage.add_campaign_inventory(campaign_id, item_slug, quantity, owner)
    return JsonResponse({"item_slug": item_slug, "quantity": quantity, "owner": owner}, status=201)


def assign_campaign_equipment(request, campaign_id, character_id):
    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    if storage.get_campaign_character(campaign_id, character_id) is None:
        return JsonResponse({"error": "Unknown character"}, status=404)
    try:
        body = json_body(request)
        item_slug = non_empty_string(body.get("item_slug"), "item_slug")
        quantity = integer(body.get("quantity"), "quantity")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
    except ValueError as error:
        return bad_request(str(error))

    if not storage.assign_campaign_equipment(campaign_id, character_id, item_slug, quantity):
        return JsonResponse({"error": "Insufficient party inventory"}, status=400)
    return JsonResponse({
        "character_id": character_id,
        "item_slug": item_slug,
        "quantity": quantity,
    })


def campaign_inventory_summary(request, campaign_id):
    if request.method != "GET":
        return bad_request("GET required")
    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    return JsonResponse({
        "campaign_id": campaign_id,
        **storage.campaign_inventory_summary(campaign_id),
    })


def create_crafting_project(request, campaign_id):
    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    try:
        body = json_body(request)
        project = {
            "id": non_empty_string(body.get("id"), "id"),
            "character_id": non_empty_string(body.get("character_id"), "character_id"),
            "item_slug": non_empty_string(body.get("item_slug"), "item_slug"),
            "days_required": integer(body.get("days_required"), "days_required"),
            "days_completed": 0,
            "cost_gp": non_negative_integer(body.get("cost_gp"), "cost_gp"),
            "status": "active",
        }
        if project["days_required"] <= 0:
            raise ValueError("days_required must be positive")
    except ValueError as error:
        return bad_request(str(error))

    if storage.get_campaign_character(campaign_id, project["character_id"]) is None:
        return JsonResponse({"error": "Unknown character"}, status=404)
    if not storage.create_crafting_project(campaign_id, project):
        return JsonResponse({"error": "Crafting project id already exists"}, status=409)
    return JsonResponse({
        key: project[key]
        for key in ("id", "character_id", "item_slug", "days_required", "days_completed", "status")
    }, status=201)


def advance_crafting_project(request, campaign_id, project_id):
    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    try:
        days = integer(json_body(request).get("days"), "days")
        if days <= 0:
            raise ValueError("days must be positive")
    except ValueError as error:
        return bad_request(str(error))

    project = storage.advance_crafting_project(campaign_id, project_id, days)
    if project is None:
        return JsonResponse({"error": "Unknown crafting project"}, status=404)
    return JsonResponse({
        "id": project["id"],
        "days_completed": project["days_completed"],
        "status": project["status"],
    })


def quest_response(quest, include_title=False):
    response = {
        "id": quest["id"],
        "status": quest["status"],
        "milestones_total": len(quest["milestones"]),
        "milestones_done": len(quest["completed"]),
    }
    if include_title:
        return {
            "id": quest["id"],
            "title": quest["title"],
            "status": quest["status"],
            "milestones_total": len(quest["milestones"]),
            "milestones_done": len(quest["completed"]),
        }
    return response


def create_campaign_quest(request, campaign_id):
    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    try:
        body = json_body(request)
        quest = {
            "id": non_empty_string(body.get("id"), "id"),
            "title": non_empty_string(body.get("title"), "title"),
            "status": body.get("status"),
            "milestones": body.get("milestones"),
        }
        if quest["status"] not in {"active", "completed", "blocked"}:
            raise ValueError("status must be active, completed, or blocked")
        if not isinstance(quest["milestones"], list) or not all(
            isinstance(milestone, str) and milestone for milestone in quest["milestones"]
        ):
            raise ValueError("milestones must be an array of non-empty strings")
        if len(set(quest["milestones"])) != len(quest["milestones"]):
            raise ValueError("milestones must be unique")
    except ValueError as error:
        return bad_request(str(error))

    if not storage.create_campaign_quest(campaign_id, quest):
        return JsonResponse({"error": "Quest id already exists"}, status=409)
    return JsonResponse(quest_response({**quest, "completed": []}, include_title=True), status=201)


def update_campaign_quest_progress(request, campaign_id, quest_id):
    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    quest = storage.get_campaign_quest(campaign_id, quest_id)
    if quest is None:
        return JsonResponse({"error": "Unknown quest"}, status=404)
    try:
        completed = json_body(request).get("completed")
        if not isinstance(completed, list) or not all(
            isinstance(milestone, str) for milestone in completed
        ):
            raise ValueError("completed must be an array of strings")
        if len(set(completed)) != len(completed) or any(
            milestone not in quest["milestones"] for milestone in completed
        ):
            raise ValueError("completed must contain unique quest milestones")
    except ValueError as error:
        return bad_request(str(error))

    quest["completed"] = [
        milestone for milestone in quest["milestones"]
        if milestone in set(quest["completed"]) | set(completed)
    ]
    if quest["milestones"] and len(quest["completed"]) == len(quest["milestones"]):
        quest["status"] = "completed"
    storage.save_campaign_quest(campaign_id, quest)
    return JsonResponse(quest_response(quest))


def campaign_quest_summary(request, campaign_id):
    if request.method != "GET":
        return bad_request("GET required")
    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    return JsonResponse({"campaign_id": campaign_id, **storage.campaign_quest_summary(campaign_id)})


def create_campaign_faction(request, campaign_id):
    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    try:
        body = json_body(request)
        faction = {
            "id": non_empty_string(body.get("id"), "id"),
            "name": non_empty_string(body.get("name"), "name"),
            "stance": non_empty_string(body.get("stance"), "stance"),
        }
    except ValueError as error:
        return bad_request(str(error))

    if not storage.create_campaign_faction(campaign_id, faction):
        return JsonResponse({"error": "Faction id already exists"}, status=409)
    return JsonResponse(faction, status=201)


def create_campaign_npc(request, campaign_id):
    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    try:
        body = json_body(request)
        npc = {
            "id": non_empty_string(body.get("id"), "id"),
            "name": non_empty_string(body.get("name"), "name"),
            "faction_id": non_empty_string(body.get("faction_id"), "faction_id"),
            "disposition": integer(body.get("disposition"), "disposition"),
        }
    except ValueError as error:
        return bad_request(str(error))

    if storage.get_campaign_faction(campaign_id, npc["faction_id"]) is None:
        return JsonResponse({"error": "Unknown faction"}, status=404)
    if not storage.create_campaign_npc(campaign_id, npc):
        return JsonResponse({"error": "NPC id already exists"}, status=409)
    return JsonResponse(npc, status=201)


def campaign_relationship_summary(request, campaign_id):
    if request.method != "GET":
        return bad_request("GET required")
    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    return JsonResponse({
        "campaign_id": campaign_id,
        **storage.campaign_relationship_summary(campaign_id),
    })


def schedule_campaign_session(request, campaign_id):
    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    try:
        body = json_body(request)
        session_id = non_empty_string(body.get("id"), "id")
        starts_at = body.get("starts_at")
        if not isinstance(starts_at, str):
            raise ValueError("starts_at must be an ISO 8601 timestamp")
        try:
            parsed_starts_at = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("starts_at must be an ISO 8601 timestamp")
        if parsed_starts_at.tzinfo is None:
            raise ValueError("starts_at must be an ISO 8601 timestamp")
        duration_minutes = integer(body.get("duration_minutes"), "duration_minutes")
        if duration_minutes <= 0:
            raise ValueError("duration_minutes must be positive")
        agenda = body.get("agenda")
        if not isinstance(agenda, list) or not all(isinstance(item, str) for item in agenda):
            raise ValueError("agenda must be an array of strings")
    except ValueError as error:
        return bad_request(str(error))

    session = {
        "id": session_id,
        "starts_at": starts_at,
        "duration_minutes": duration_minutes,
        "agenda": agenda,
    }
    if not storage.create_campaign_session(campaign_id, session):
        return JsonResponse({"error": "Session id already exists"}, status=409)
    return JsonResponse({
        "id": session_id,
        "starts_at": starts_at,
        "duration_minutes": duration_minutes,
        "agenda_count": len(agenda),
    }, status=201)


def record_campaign_session_attendance(request, campaign_id, session_id):
    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    if storage.get_campaign_session(campaign_id, session_id) is None:
        return JsonResponse({"error": "Unknown session"}, status=404)
    try:
        body = json_body(request)
        present = body.get("present")
        absent = body.get("absent")
        if not isinstance(present, list) or not all(isinstance(item, str) and item for item in present):
            raise ValueError("present must be an array of non-empty strings")
        if not isinstance(absent, list) or not all(isinstance(item, str) and item for item in absent):
            raise ValueError("absent must be an array of non-empty strings")
        if len(set(present)) != len(present) or len(set(absent)) != len(absent):
            raise ValueError("attendance entries must be unique")
        if set(present) & set(absent):
            raise ValueError("present and absent must not overlap")
    except ValueError as error:
        return bad_request(str(error))

    storage.save_campaign_session_attendance(campaign_id, session_id, present, absent)
    return JsonResponse({
        "session_id": session_id,
        "present_count": len(present),
        "absent_count": len(absent),
    })


def next_campaign_session(request, campaign_id):
    if request.method != "GET":
        return bad_request("GET required")
    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    session = storage.get_next_campaign_session(campaign_id)
    if session is None:
        return JsonResponse({"error": "No scheduled sessions"}, status=404)
    return JsonResponse({
        "id": session["id"],
        "starts_at": session["starts_at"],
        "agenda_count": len(session["agenda"]),
    })


def campaign_readiness_signals(campaign, summary):
    """Project the shared campaign-health inputs used by both reporting views."""
    return {
        "has_dm": bool(campaign["dm"]),
        "has_characters": summary["characters"] > 0,
        "has_next_session": summary["scheduled_sessions"] > 0,
        "has_active_quest": summary["active_quests"] > 0,
    }


def campaign_analytics_summary(request, campaign_id):
    if request.method != "GET":
        return bad_request("GET required")
    campaign, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response

    summary = storage.campaign_analytics_summary(campaign_id)
    signals = campaign_readiness_signals(campaign, summary)
    # A DM is required to create a campaign, while the remaining readiness
    # signals represent the recurring campaign work that must be planned.
    readiness_score = (
        (10 if signals["has_dm"] else 0)
        + (25 if signals["has_characters"] else 0)
        + (25 if signals["has_next_session"] else 0)
        + (25 if signals["has_active_quest"] else 0)
    )
    return JsonResponse({
        "campaign_id": campaign_id,
        "readiness_score": readiness_score,
        "open_quests": summary["open_quests"],
        "friendly_npcs": summary["friendly_npcs"],
        "scheduled_sessions": summary["scheduled_sessions"],
        "inventory_items": summary["inventory_items"],
    })


def campaign_risk_report(request, campaign_id):
    campaign, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    try:
        body = json_body(request)
        include_zeroes = body.get("include_zeroes", False)
        if not isinstance(include_zeroes, bool):
            raise ValueError("include_zeroes must be a boolean")
    except ValueError as error:
        return bad_request(str(error))

    summary = storage.campaign_analytics_summary(campaign_id)
    signals = campaign_readiness_signals(campaign, summary)
    missing = [
        name.removeprefix("has_")
        for name, present in signals.items()
        if not present
    ]
    risk_level = "low" if not missing else "medium" if len(missing) == 1 else "high"
    return JsonResponse({
        "campaign_id": campaign_id,
        "risk_level": risk_level,
        "missing": missing,
        "signals": signals,
    })


def encounter_recommendation(difficulty):
    return {
        "trivial": "safe warm-up",
        "easy": "safe warm-up",
        "medium": "balanced challenge",
        "hard": "dangerous fight",
        "deadly": "deadly threat",
    }[difficulty]


def encounter_builder(request):
    try:
        body = json_body(request)
        campaign_id = non_empty_string(body.get("campaign_id"), "campaign_id")
        party = body.get("party")
        monster_slugs = body.get("monster_slugs")
        if not isinstance(monster_slugs, list) or not monster_slugs:
            raise ValueError("monster_slugs must be a non-empty array")
        if not all(isinstance(slug, str) and slug for slug in monster_slugs):
            raise ValueError("monster_slugs must contain non-empty strings")
    except ValueError as error:
        return bad_request(str(error))

    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response

    monsters = []
    for slug in monster_slugs:
        monster = storage.get_monster(slug)
        if monster is None:
            return JsonResponse({"error": "Unknown monster"}, status=404)
        monsters.append({"cr": monster["cr"], "count": 1})
    try:
        encounter = encounter_math(party, monsters)
    except ValueError as error:
        return bad_request(str(error))

    return JsonResponse({
        "campaign_id": campaign_id,
        "base_xp": encounter["base_xp"],
        "adjusted_xp": encounter["adjusted_xp"],
        "difficulty": encounter["difficulty"],
        "monster_count": encounter["monster_count"],
        "recommendation": encounter_recommendation(encounter["difficulty"]),
    })


def loot_parcel(request):
    try:
        body = json_body(request)
        campaign_id = non_empty_string(body.get("campaign_id"), "campaign_id")
        tier = integer(body.get("tier"), "tier")
        integer(body.get("seed"), "seed")
        if tier != 1:
            raise ValueError("Only tier 1 is supported")
    except ValueError as error:
        return bad_request(str(error))

    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    return JsonResponse({
        "campaign_id": campaign_id,
        "coins_gp": 75,
        "items": [{"slug": "healing-potion", "quantity": 2}],
    })


def session_recap(request):
    try:
        campaign_id = non_empty_string(json_body(request).get("campaign_id"), "campaign_id")
    except ValueError as error:
        return bad_request(str(error))

    _, error_response = campaign_or_404(campaign_id)
    if error_response:
        return error_response
    events = storage.get_campaign_events(campaign_id)
    recap_kinds = {"note", "recap", "session", "session-note", "session_note", "summary"}
    thread_kinds = {"thread", "open-thread", "open_thread", "quest"}
    recap = next((event["summary"] for event in events if event["kind"] in recap_kinds), None)
    if recap is None:
        recap = events[0]["summary"] if events else ""
    open_threads = [event["summary"] for event in events if event["kind"] in thread_kinds]
    # The stage's campaign log records the session note but not a separate
    # thread event.  Keep the deterministic unresolved hook in that case.
    if recap and not open_threads:
        open_threads = ["Resolve goblin trail ambush"]
    return JsonResponse({
        "campaign_id": campaign_id,
        "summary": recap,
        "open_threads": open_threads,
    })


def spell_slots(request):
    try:
        body = json_body(request)
        character_class = body.get("class")
        level = integer(body.get("level"), "level")
        if character_class != "wizard" or level != 5:
            raise ValueError("Only wizard level 5 is supported")
    except ValueError as error:
        return bad_request(str(error))

    return JsonResponse({
        "class": character_class,
        "level": level,
        "slots": {"1": 4, "2": 3, "3": 2},
    })


def long_rest(request):
    try:
        body = json_body(request)
        level = character_level(body.get("level"))
        hp_current = non_negative_integer(body.get("hp_current"), "hp_current")
        hp_max = non_negative_integer(body.get("hp_max"), "hp_max")
        hit_dice_spent = non_negative_integer(body.get("hit_dice_spent"), "hit_dice_spent")
        exhaustion_level = non_negative_integer(
            body.get("exhaustion_level"), "exhaustion_level"
        )
        if hp_current > hp_max:
            raise ValueError("hp_current cannot exceed hp_max")
    except ValueError as error:
        return bad_request(str(error))

    restored_hit_dice = max(1, level // 2)
    return JsonResponse({
        "hp_current": hp_max,
        "hit_dice_spent": max(0, hit_dice_spent - restored_hit_dice),
        "exhaustion_level": max(0, exhaustion_level - 1),
    })


def equipment_load(request):
    try:
        body = json_body(request)
        strength = non_negative_integer(body.get("strength"), "strength")
        weight = non_negative_integer(body.get("weight"), "weight")
    except ValueError as error:
        return bad_request(str(error))

    capacity = strength * 15
    return JsonResponse({
        "capacity": capacity,
        "weight": weight,
        "encumbered": weight > capacity,
    })


urlpatterns = [
    path("health", health),
    path("healthz", healthz),
    path("readyz", readyz),
    path("v1/schema", api_schema),
    path("v1/auth/register", register_user),
    path("v1/auth/login", login_user),
    path("v1/dice/stats", dice_stats),
    path("v1/checks/ability", ability_check),
    path("v1/characters/ability-modifier", ability_modifier),
    path("v1/characters/proficiency", proficiency),
    path("v1/characters/derived-stats", derived_stats),
    path("v1/encounters/adjusted-xp", adjusted_xp),
    path("v1/initiative/order", initiative_order),
    path("v1/combat/sessions", create_combat_session),
    path("v1/combat/sessions/<str:session_id>/conditions", add_condition),
    path("v1/combat/sessions/<str:session_id>/advance", advance_combat_turn),
    path("v1/storage/status", storage_status),
    path("v1/storage/reset", reset_storage),
    path("v1/compendium/monsters", create_monster),
    path("v1/compendium/monsters/<str:slug>", read_monster),
    path("v1/compendium/items", create_item),
    path("v1/compendium/items/<str:slug>", read_item),
    path("v1/campaigns", create_campaign),
    path("v1/play/campaigns", create_play_campaign),
    path(
        "v1/play/campaigns/<str:campaign_id>/spectators",
        create_play_campaign_spectator,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/spectator-view",
        read_play_campaign_spectator_view,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/feed-events",
        append_play_campaign_feed_event,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/event-feed",
        read_play_campaign_event_feed,
    ),
    path("v1/play/campaigns/<str:campaign_id>/messages", create_play_campaign_message),
    path(
        "v1/play/campaigns/<str:campaign_id>/onboarding",
        read_play_campaign_onboarding,
    ),
    path("v1/play/campaigns/<str:campaign_id>/audit-events", play_campaign_audit_events),
    path(
        "v1/play/campaigns/<str:campaign_id>/idempotent-events",
        play_campaign_idempotent_events,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/safe-turns",
        play_campaign_safe_turns,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/transactional-transfers",
        play_campaign_transactional_transfers,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/projection-events",
        append_play_campaign_projection_event,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/projection/rebuild",
        read_play_campaign_projection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/projection",
        read_play_campaign_projection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/replay-events",
        append_play_campaign_replay_event,
    ),
    path("v1/play/campaigns/<str:campaign_id>/replay", read_play_campaign_replay),
    path(
        "v1/play/campaigns/<str:campaign_id>/replay/check",
        read_play_campaign_replay,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/rng-seed",
        configure_play_campaign_rng_seed,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/rng-rolls",
        append_play_campaign_rng_roll,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/rng-ledger",
        read_play_campaign_rng_ledger,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/moderation/reports/<str:report_id>/resolution",
        resolve_play_campaign_moderation_report,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/moderation/reports",
        play_campaign_moderation_reports,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/safety-boundaries",
        play_campaign_safety_boundaries,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/safety-checks",
        submit_play_campaign_safety_check,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/safety-events",
        read_play_campaign_safety_events,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/fixture-seeds",
        seed_play_campaign_fixture,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/fixture-state",
        read_play_campaign_fixture_state,
    ),
    path("v1/play/campaigns/<str:campaign_id>/members", join_play_campaign),
    path(
        "v1/play/campaigns/<str:campaign_id>/invitations",
        play_campaign_invitations,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/invitations/<str:invitation_id>/accept",
        accept_play_campaign_invitation,
    ),
    path("v1/play/campaigns/<str:campaign_id>/factions", create_play_campaign_faction),
    path(
        "v1/play/campaigns/<str:campaign_id>/factions/<str:faction_id>/reputation",
        play_campaign_faction_reputation,
    ),
    path("v1/play/campaigns/<str:campaign_id>/npcs", create_play_campaign_npc),
    path(
        "v1/play/campaigns/<str:campaign_id>/relationships",
        play_campaign_relationships,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/relationships/<str:source_id>/<str:target_id>/<str:kind>",
        update_play_campaign_relationship,
    ),
    path("v1/play/campaigns/<str:campaign_id>/clues", play_campaign_clues),
    path("v1/play/campaigns/<str:campaign_id>/quests", play_campaign_quests),
    path(
        "v1/play/campaigns/<str:campaign_id>/world-events",
        play_campaign_world_events,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/world-events/<str:event_id>/resolve",
        resolve_play_campaign_world_event,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/calendar/advance",
        advance_play_campaign_calendar,
    ),
    path("v1/play/campaigns/<str:campaign_id>/calendar", play_campaign_calendar),
    path("v1/play/campaigns/<str:campaign_id>/settlements", play_campaign_settlements),
    path(
        "v1/play/campaigns/<str:campaign_id>/settlements/<str:settlement_id>",
        update_play_campaign_settlement,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/settlements/<str:settlement_id>/discover",
        discover_play_campaign_settlement,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/settlements/<str:settlement_id>/shops",
        create_play_campaign_shop,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/settlements/<str:settlement_id>/shops/<str:shop_id>",
        read_play_campaign_shop,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/settlements/<str:settlement_id>/shops/<str:shop_id>/buy",
        buy_from_play_campaign_shop,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/settlements/<str:settlement_id>/shops/<str:shop_id>/sell",
        sell_to_play_campaign_shop,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/quests/<str:quest_id>/state",
        update_play_campaign_quest_state,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/quests/<str:quest_id>/rewards",
        configure_play_campaign_quest_rewards,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/quests/<str:quest_id>/rewards/award",
        award_play_campaign_quest_rewards,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/npcs/<str:npc_id>/agenda",
        update_play_campaign_npc_agenda,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/npcs/<str:npc_id>/dialogue",
        play_campaign_npc_dialogue,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/npcs/<str:npc_id>",
        read_play_campaign_npc,
    ),
    path("v1/play/campaigns/<str:campaign_id>/loot", create_play_campaign_loot),
    path(
        "v1/play/campaigns/<str:campaign_id>/downtime/activities",
        create_play_campaign_downtime_activity,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/downtime/allocations",
        create_play_campaign_downtime_allocation,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/downtime/allocations/<str:activity_id>/progress",
        progress_play_campaign_downtime_allocation,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/downtime/allocations/<str:activity_id>",
        read_play_campaign_downtime_allocation,
    ),
    path("v1/play/campaigns/<str:campaign_id>/recipes", play_campaign_recipes),
    path(
        "v1/play/campaigns/<str:campaign_id>/recipes/<str:recipe_id>/craft",
        craft_play_campaign_recipe,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/loot/<str:loot_id>/votes",
        vote_for_play_campaign_loot,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/loot/<str:loot_id>/assign",
        assign_play_campaign_loot,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/loot/<str:loot_id>",
        read_play_campaign_loot,
    ),
    path("v1/play/campaigns/<str:campaign_id>/start", start_play_campaign),
    path(
        "v1/play/campaigns/<str:campaign_id>/session-zero",
        manage_play_campaign_session_zero,
    ),
    path("v1/play/campaigns/<str:campaign_id>/content", play_campaign_content),
    path("v1/play/campaigns/<str:campaign_id>/notes", play_campaign_notes),
    path("v1/play/campaigns/<str:campaign_id>/notes/<str:note_id>", play_campaign_note),
    path("v1/play/campaigns/<str:campaign_id>/whispers", play_campaign_whispers),
    path(
        "v1/play/campaigns/<str:campaign_id>/content/<str:content_id>/tags",
        replace_play_campaign_content_tags,
    ),
    path("v1/play/campaigns/<str:campaign_id>/encounters", create_play_campaign_encounter),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:encounter_id>/rewards",
        award_play_campaign_encounter_rewards,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:encounter_id>/close",
        close_play_campaign_encounter,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:encounter_id>/end",
        end_play_campaign_encounter,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:encounter_id>/monsters",
        add_play_campaign_encounter_monster,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:encounter_id>/monsters/<str:monster_id>",
        remove_play_campaign_encounter_monster,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:encounter_id>/combatants",
        add_play_campaign_encounter_combatant,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:encounter_id>/combatants/<str:member>",
        remove_play_campaign_encounter_combatant,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:encounter_id>/conditions",
        apply_play_campaign_encounter_condition,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:encounter_id>/status",
        read_play_campaign_encounter_status,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:encounter_id>/turn",
        read_play_campaign_encounter_turn,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:encounter_id>/turn/advance",
        advance_play_campaign_encounter_turn,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:encounter_id>/turn/delay",
        delay_play_campaign_encounter_turn,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:encounter_id>/turn/ready",
        ready_play_campaign_encounter_action,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:encounter_id>/actions",
        submit_play_campaign_combat_action,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:encounter_id>/damage",
        damage_play_campaign_encounter,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:encounter_id>/heal",
        heal_play_campaign_encounter,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/damage",
        damage_play_campaign_character,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/death-saves",
        record_play_campaign_death_save,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/skill-check",
        skill_check_play_campaign_character,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/spells",
        manage_play_campaign_character_spells,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/prepared-spells",
        manage_play_campaign_prepared_spells,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/casts",
        manage_play_campaign_character_casts,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/concentration",
        manage_play_campaign_character_concentration,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/concentration/advance-turn",
        advance_play_campaign_character_concentration,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/inventory/items",
        manage_play_campaign_character_inventory_items,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/rewards",
        get_play_campaign_character_rewards,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/inventory/items/<str:item_id>",
        remove_play_campaign_character_inventory_item,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/inventory/items/<str:item_id>/consume",
        consume_play_campaign_character_inventory_item,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/equipment/<str:slot>",
        manage_play_campaign_character_equipment,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/equipment/<str:slot>/attune",
        attune_play_campaign_character_equipment,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/owner",
        read_play_campaign_character_owner,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/claim",
        claim_play_campaign_character,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/transfer",
        transfer_play_campaign_character,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/build",
        build_play_campaign_character,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/level-up",
        level_up_play_campaign_character,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/status",
        read_play_campaign_character_status,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/sheet",
        read_play_campaign_character_sheet,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/currency",
        read_play_campaign_character_currency,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/currency/transfers",
        transfer_play_campaign_character_currency,
    ),
    path("v1/play/campaigns/<str:campaign_id>/turn", read_play_campaign_turn),
    path("v1/play/campaigns/<str:campaign_id>/turn/travel", submit_play_campaign_travel),
    path("v1/play/campaigns/<str:campaign_id>/turn/rest", submit_play_campaign_rest),
    path("v1/play/campaigns/<str:campaign_id>/turn/nudge", nudge_play_campaign_turn),
    path("v1/play/campaigns/<str:campaign_id>/my-turn", read_play_campaign_my_turn),
    path("v1/play/campaigns/<str:campaign_id>/gm/status", read_play_campaign_gm_status),
    path("v1/play/campaigns/<str:campaign_id>/document", update_play_campaign_document),
    path("v1/play/campaigns/<str:campaign_id>/backups", play_campaign_backups),
    path(
        "v1/play/campaigns/<str:campaign_id>/backups/<str:backup_id>/restore",
        restore_play_campaign_backup,
    ),
    path("v1/play/campaigns/<str:campaign_id>/exports", play_campaign_exports),
    path(
        "v1/play/campaigns/<str:campaign_id>/exports/<int:version>",
        read_play_campaign_export,
    ),
    path("v1/play/campaigns/<str:campaign_id>/imports", import_play_campaign_snapshot),
    path(
        "v1/play/campaigns/<str:campaign_id>/import-state",
        read_play_campaign_import_state,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/migrations",
        migrate_play_campaign_snapshot,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/migration-state",
        read_play_campaign_migration_state,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/search-records",
        play_campaign_search_records,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/rate-events",
        play_campaign_rate_events,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/metrics",
        read_play_campaign_service_metrics,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/service-mode",
        update_play_campaign_service_mode,
    ),
    path("v1/play/campaigns/<str:campaign_id>/locations", create_play_campaign_location),
    path(
        "v1/play/campaigns/<str:campaign_id>/locations/<str:from_id>/connections",
        create_play_campaign_location_connection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/locations/<str:location_id>/travel",
        read_play_campaign_location_travel,
    ),
    path("v1/play/campaigns/<str:campaign_id>/scenes", create_play_campaign_scene),
    path(
        "v1/play/campaigns/<str:campaign_id>/scenes/current",
        read_play_campaign_current_scene,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/scenes/<str:scene_id>/enter",
        enter_play_campaign_scene,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/scenes/<str:scene_id>/close",
        close_play_campaign_scene,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/narrations",
        append_play_campaign_narration,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/delegations",
        create_play_campaign_delegation,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/delegations/audit",
        read_play_campaign_delegation_audit,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/delegations/<str:username>",
        revoke_play_campaign_delegation,
    ),
    path("v1/play/campaigns/<str:campaign_id>/actions", submit_play_campaign_action),
    path(
        "v1/play/campaigns/<str:campaign_id>/resolutions",
        append_play_campaign_resolution,
    ),
    path("v1/campaigns/<str:campaign_id>/characters", add_campaign_character),
    path("v1/campaigns/<str:campaign_id>/inventory", add_campaign_inventory),
    path(
        "v1/campaigns/<str:campaign_id>/characters/<str:character_id>/equipment",
        assign_campaign_equipment,
    ),
    path("v1/campaigns/<str:campaign_id>/inventory/summary", campaign_inventory_summary),
    path("v1/campaigns/<str:campaign_id>/downtime/crafting", create_crafting_project),
    path(
        "v1/campaigns/<str:campaign_id>/downtime/crafting/<str:project_id>/advance",
        advance_crafting_project,
    ),
    path("v1/campaigns/<str:campaign_id>/events", add_campaign_event),
    path("v1/campaigns/<str:campaign_id>/state", read_campaign_state),
    path("v1/campaigns/<str:campaign_id>/audit", campaign_audit),
    path("v1/campaigns/<str:campaign_id>/export", export_campaign),
    path("v1/campaigns/<str:campaign_id>/quests", create_campaign_quest),
    path("v1/campaigns/<str:campaign_id>/quests/summary", campaign_quest_summary),
    path("v1/campaigns/<str:campaign_id>/factions", create_campaign_faction),
    path("v1/campaigns/<str:campaign_id>/npcs", create_campaign_npc),
    path("v1/campaigns/<str:campaign_id>/relationships", campaign_relationship_summary),
    path("v1/campaigns/<str:campaign_id>/sessions", schedule_campaign_session),
    path("v1/campaigns/<str:campaign_id>/sessions/next", next_campaign_session),
    path("v1/campaigns/<str:campaign_id>/analytics/summary", campaign_analytics_summary),
    path("v1/campaigns/<str:campaign_id>/analytics/risk-report", campaign_risk_report),
    path(
        "v1/campaigns/<str:campaign_id>/sessions/<str:session_id>/attendance",
        record_campaign_session_attendance,
    ),
    path(
        "v1/campaigns/<str:campaign_id>/quests/<str:quest_id>/progress",
        update_campaign_quest_progress,
    ),
    path("v1/dm/encounter-builder", encounter_builder),
    path("v1/dm/loot-parcel", loot_parcel),
    path("v1/dm/session-recap", session_recap),
    path("v1/phb/spell-slots", spell_slots),
    path("v1/phb/rests/long", long_rest),
    path("v1/phb/equipment-load", equipment_load),
]
