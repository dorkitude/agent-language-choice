"""Real-time play surface: lobbies, turn order, and the shared campaign document.

Distinct from ``campaigns.py``, which manages the static/planning-time campaign
record (characters, quests, inventory). A play campaign starts in the
``lobby`` status, moves to ``active`` once the DM starts it, and thereafter
alternates ``current_actor`` between the DM and party members as actions and
resolutions are posted.
"""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dndsite import db
from dndsite.rules import (
    HIT_DICE,
    SPELLCASTING_CLASSES,
    VALID_BACKGROUNDS,
    VALID_RACES,
    ability_modifier,
    hp_max_at_level1,
    proficiency_bonus,
    spell_slots_at_level,
)
from dndsite.views._util import (
    error_response,
    is_play_participant,
    json_body,
    require_method,
    require_play_auth,
    require_play_campaign,
)

ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")

VALID_INVENTORY_ITEM_IDS = (
    "healing-potion",
    "torch",
    "leather-armor",
    "ring-of-protection",
    "amulet-of-health",
)

VALID_EQUIPMENT_SLOTS = ("armor", "accessory")

ITEM_SLOT_BY_ID = {
    "leather-armor": "armor",
    "ring-of-protection": "accessory",
    "amulet-of-health": "accessory",
}

ATTUNABLE_ITEM_IDS = ("ring-of-protection", "amulet-of-health")

MAX_ATTUNEMENTS = 1

CONSUMABLE_ITEM_IDS = ("healing-potion",)

CONSUMABLE_EFFECTS = {
    "healing-potion": {"type": "healing", "hp_restored": 5},
}

VALID_SKILLS = (
    "acrobatics",
    "animal_handling",
    "arcana",
    "athletics",
    "deception",
    "history",
    "insight",
    "intimidation",
    "investigation",
    "medicine",
    "nature",
    "perception",
    "performance",
    "persuasion",
    "religion",
    "sleight_of_hand",
    "stealth",
    "survival",
)


@csrf_exempt
def play_campaigns_collection(request):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error
    if user["role"] != "dm":
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        campaign_id = body["id"]
        name = body["name"]
        max_players = body["max_players"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(campaign_id, str) or not campaign_id:
        return error_response("invalid id", 400)
    if not isinstance(name, str) or not name:
        return error_response("invalid name", 400)
    if not isinstance(max_players, int) or isinstance(max_players, bool) or max_players < 1:
        return error_response("invalid max_players", 400)

    if db.get_play_campaign(campaign_id) is not None:
        return error_response("campaign already exists", 409)

    campaign = {
        "id": campaign_id,
        "name": name,
        "owner": user["username"],
        "status": "lobby",
        "max_players": max_players,
    }
    db.create_play_campaign(campaign)

    return JsonResponse(campaign, status=201)


@csrf_exempt
def play_campaign_members_collection(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error
    if user["role"] != "player":
        return error_response("forbidden", 403)

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    try:
        body = json_body(request)
        character_id = body["character_id"]
        name = body["name"]
        char_class = body["class"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(character_id, str) or not character_id:
        return error_response("invalid character_id", 400)
    if not isinstance(name, str) or not name:
        return error_response("invalid name", 400)
    if not isinstance(char_class, str) or not char_class:
        return error_response("invalid class", 400)

    if db.get_play_campaign_member(campaign_id, user["username"]) is not None:
        return error_response("already a member", 409)
    if db.get_play_campaign_member_by_character(campaign_id, character_id) is not None:
        return error_response("character already in use", 409)

    members = db.get_play_campaign_members(campaign_id)
    if len(members) >= campaign["max_players"]:
        return error_response("campaign full", 409)

    member = {
        "username": user["username"],
        "character_id": character_id,
        "name": name,
        "class": char_class,
    }
    db.create_play_campaign_member(campaign_id, member)

    return JsonResponse(member, status=201)


@csrf_exempt
def play_campaign_start(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["role"] != "dm" or user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    members = db.get_play_campaign_members(campaign_id)
    if campaign["status"] != "lobby" or len(members) < 2:
        return error_response("campaign cannot be started", 409)

    current_actor = members[0]["username"]
    turn_number = 1
    db.start_play_campaign(campaign_id, current_actor, turn_number)

    return JsonResponse(
        {
            "id": campaign_id,
            "status": "active",
            "current_actor": current_actor,
            "turn_number": turn_number,
        }
    )


def _valid_session_zero_payload(body):
    if not isinstance(body, dict):
        return False
    rules = body.get("rules")
    tone = body.get("tone")
    consent = body.get("consent")
    if not isinstance(rules, str) or not rules:
        return False
    if not isinstance(tone, str) or not tone:
        return False
    if not isinstance(consent, list) or not consent:
        return False
    seen = set()
    for entry in consent:
        if not isinstance(entry, str) or not entry or entry in seen:
            return False
        seen.add(entry)
    return True


@csrf_exempt
def play_campaign_session_zero(request, campaign_id):
    method_error = require_method(request, "PUT", "GET")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if request.method == "PUT":
        if user["username"] != campaign["owner"]:
            return error_response("forbidden", 403)

        try:
            body = json_body(request)
        except json.JSONDecodeError:
            return error_response("invalid request", 400)

        if not _valid_session_zero_payload(body):
            return error_response("invalid request", 400)

        if campaign["status"] != "lobby":
            return error_response("campaign already started", 409)

        settings = {
            "rules": body["rules"],
            "tone": body["tone"],
            "consent": list(body["consent"]),
        }
        db.set_play_campaign_session_zero(campaign_id, settings["rules"], settings["tone"], settings["consent"])

        return JsonResponse(settings)

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    settings = db.get_play_campaign_session_zero(campaign_id)
    if settings is None:
        return error_response("session-zero settings not found", 404)

    return JsonResponse(settings)


@csrf_exempt
def play_campaign_narrations_collection(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["role"] != "dm" or user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        text = body["text"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(text, str) or not text:
        return error_response("invalid text", 400)

    event = db.create_play_campaign_event(campaign_id, "narration", "dm", text)

    return JsonResponse(event, status=201)


@csrf_exempt
def play_campaign_actions_collection(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["role"] == "dm":
        return error_response("conflict", 409)
    if user["role"] != "player":
        return error_response("forbidden", 403)

    member = db.get_play_campaign_member(campaign_id, user["username"])
    if member is None:
        return error_response("forbidden", 403)

    if campaign["current_actor"] != user["username"]:
        return error_response("conflict", 409)

    try:
        body = json_body(request)
        action_type = body["type"]
        text = body["text"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(action_type, str) or not action_type:
        return error_response("invalid type", 400)
    if not isinstance(text, str) or not text:
        return error_response("invalid text", 400)

    event = db.create_play_campaign_event(
        campaign_id, "action", user["username"], text, event_type=action_type
    )
    db.set_play_campaign_current_actor(campaign_id, campaign["owner"])

    response = dict(event)
    response["next_actor"] = "dm"
    return JsonResponse(response, status=201)


def _next_action_actor(current_turn_number, member_usernames, campaign_owner):
    """The first party member resumes play once the queue has cycled through
    the DM at least once; the second member goes first on turn 1."""
    if not member_usernames:
        return campaign_owner
    if current_turn_number >= 2:
        return member_usernames[0]
    if len(member_usernames) > 1:
        return member_usernames[1]
    return member_usernames[0]


@csrf_exempt
def play_campaign_resolutions_collection(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["role"] == "player":
        return error_response("conflict", 409)
    if user["role"] != "dm" or user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    if campaign["current_actor"] != user["username"]:
        return error_response("conflict", 409)

    try:
        body = json_body(request)
        text = body["text"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(text, str) or not text:
        return error_response("invalid text", 400)

    event = db.create_play_campaign_event(campaign_id, "resolution", "dm", text)

    members = db.get_play_campaign_members(campaign_id)
    usernames = [member["username"] for member in members]
    next_actor = _next_action_actor(campaign["turn_number"], usernames, campaign["owner"])

    turn_number = campaign["turn_number"] + 1
    db.advance_play_campaign_turn(campaign_id, next_actor, turn_number)

    response = dict(event)
    response["next_actor"] = next_actor
    response["turn_number"] = turn_number
    return JsonResponse(response, status=201)


@csrf_exempt
def play_campaign_turn(request, campaign_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    phase = "dm" if campaign["current_actor"] == campaign["owner"] else "player"

    members = db.get_play_campaign_members(campaign_id)
    queue = []
    for member in members:
        queue.append(member["username"])
        queue.append(campaign["owner"])

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "current_actor": campaign["current_actor"],
            "phase": phase,
            "turn_number": campaign["turn_number"],
            "queue": queue,
            "overdue": False,
            "logical_deadline": campaign["turn_number"] + 1,
        }
    )


@csrf_exempt
def play_campaign_turn_nudge(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    is_owner = user["username"] == campaign["owner"]
    if not is_owner:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        nudge_message = body["message"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(nudge_message, str) or not nudge_message:
        return error_response("invalid message", 400)

    nudge_count = db.increment_play_campaign_nudge_count(campaign_id)
    db.create_play_campaign_event(campaign_id, "nudge", user["username"], nudge_message)

    return JsonResponse(
        {
            "actor": user["username"],
            "target": campaign["current_actor"],
            "message": nudge_message,
            "nudge_count": nudge_count,
        },
        status=201,
    )


@csrf_exempt
def play_campaign_my_turn(request, campaign_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error
    if user["role"] != "player":
        return error_response("forbidden", 403)

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    member = db.get_play_campaign_member(campaign_id, user["username"])
    if member is None:
        return error_response("forbidden", 403)

    is_my_turn = campaign["current_actor"] == user["username"]
    recent_events = db.list_play_campaign_events(campaign_id)

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "is_my_turn": is_my_turn,
            "current_actor": campaign["current_actor"],
            "character": {
                "id": member["character_id"],
                "name": member["name"],
            },
            "recent_events": recent_events,
        }
    )


@csrf_exempt
def play_campaign_document(request, campaign_id):
    method_error = require_method(request, "GET", "PUT")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    is_owner = user["username"] == campaign["owner"]
    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    if request.method == "PUT":
        if not is_owner:
            return error_response("forbidden", 403)

        try:
            body = json_body(request)
            story = body["story"]
            dm_notes = body["dm_notes"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return error_response("invalid request", 400)

        if not isinstance(story, str):
            return error_response("invalid story", 400)
        if not isinstance(dm_notes, str):
            return error_response("invalid dm_notes", 400)

        db.update_play_campaign_document(campaign_id, story, dm_notes)
        campaign = db.get_play_campaign(campaign_id)

    if is_owner:
        return JsonResponse({"story": campaign["story"], "dm_notes": campaign["dm_notes"]})
    return JsonResponse({"story": campaign["story"]})


@csrf_exempt
def play_campaign_scenes_collection(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        scene_id = body["id"]
        name = body["name"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(scene_id, str) or not scene_id:
        return error_response("invalid id", 400)
    if not isinstance(name, str) or not name:
        return error_response("invalid name", 400)

    if db.get_play_scene(campaign_id, scene_id) is not None:
        return error_response("scene already exists", 409)

    scene = {"id": scene_id, "name": name, "status": "open"}
    db.create_play_scene(campaign_id, scene)

    return JsonResponse(scene, status=201)


@csrf_exempt
def play_campaign_scene_enter(request, campaign_id, scene_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    scene = db.get_play_scene(campaign_id, scene_id)
    if scene is None:
        return error_response("scene not found", 404)
    if scene["status"] != "open":
        return error_response("scene closed", 409)

    db.set_play_campaign_current_scene(campaign_id, scene_id)
    db.create_play_campaign_event(campaign_id, "scene", user["username"], scene_id)

    return JsonResponse({"current_scene_id": scene["id"], "name": scene["name"]})


@csrf_exempt
def play_campaign_scene_close(request, campaign_id, scene_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    scene = db.get_play_scene(campaign_id, scene_id)
    if scene is None:
        return error_response("scene not found", 404)

    db.close_play_scene(campaign_id, scene_id)

    return JsonResponse({"id": scene["id"], "status": "closed"})


@csrf_exempt
def play_campaign_scene_current(request, campaign_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    scene_id = campaign["current_scene_id"]
    scene = db.get_play_scene(campaign_id, scene_id) if scene_id else None
    if scene is None or scene["status"] != "open":
        return error_response("no current scene", 404)

    return JsonResponse({"id": scene["id"], "name": scene["name"], "status": scene["status"]})


@csrf_exempt
def play_campaign_gm_status(request, campaign_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    members = db.get_play_campaign_members(campaign_id)
    party = [
        {
            "username": member["username"],
            "character_id": member["character_id"],
            "name": member["name"],
            "class": member["class"],
        }
        for member in members
    ]
    recent_events = db.list_play_campaign_events(campaign_id)

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "needs_attention": campaign["current_actor"] == campaign["owner"],
            "current_actor": campaign["current_actor"],
            "party": party,
            "recent_events": recent_events,
        }
    )


@csrf_exempt
def play_campaign_locations_collection(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        location_id = body["id"]
        name = body["name"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(location_id, str) or not location_id:
        return error_response("invalid id", 400)
    if not isinstance(name, str) or not name:
        return error_response("invalid name", 400)

    if db.get_play_location(campaign_id, location_id) is not None:
        return error_response("location already exists", 409)

    location = {"id": location_id, "name": name}
    db.create_play_location(campaign_id, location)

    return JsonResponse(location, status=201)


@csrf_exempt
def play_campaign_location_connections_collection(request, campaign_id, from_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        to_id = body["to_id"]
        travel_turns = body["travel_turns"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(to_id, str) or not to_id:
        return error_response("invalid to_id", 400)
    if not isinstance(travel_turns, int) or isinstance(travel_turns, bool) or travel_turns < 1:
        return error_response("invalid travel_turns", 400)

    if db.get_play_location(campaign_id, from_id) is None:
        return error_response("location not found", 400)
    if db.get_play_location(campaign_id, to_id) is None:
        return error_response("location not found", 400)
    if db.get_play_connection(campaign_id, from_id, to_id) is not None:
        return error_response("connection already exists", 400)

    db.create_play_connection(campaign_id, from_id, to_id, travel_turns)

    return JsonResponse(
        {"from_id": from_id, "to_id": to_id, "travel_turns": travel_turns}, status=201
    )


@csrf_exempt
def play_campaign_turn_travel(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["role"] == "dm":
        return error_response("conflict", 409)
    if user["role"] != "player":
        return error_response("forbidden", 403)

    member = db.get_play_campaign_member(campaign_id, user["username"])
    if member is None:
        return error_response("forbidden", 403)

    if campaign["current_actor"] != user["username"]:
        return error_response("conflict", 409)

    try:
        body = json_body(request)
        destination_id = body["destination_id"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(destination_id, str) or not destination_id:
        return error_response("invalid destination_id", 400)

    current_location_id = campaign["current_location_id"]
    connection = None
    if current_location_id is not None:
        connection = db.get_play_connection(campaign_id, current_location_id, destination_id)
    if connection is None:
        return error_response("invalid destination", 409)

    event = db.create_play_campaign_travel_event(
        campaign_id, user["username"], destination_id, connection["travel_turns"]
    )
    db.set_play_campaign_current_location(campaign_id, destination_id)
    db.set_play_campaign_current_actor(campaign_id, campaign["owner"])

    response = dict(event)
    response["next_actor"] = "dm"
    return JsonResponse(response, status=201)


@csrf_exempt
def play_campaign_turn_rest(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["role"] == "dm":
        return error_response("conflict", 409)
    if user["role"] != "player":
        return error_response("forbidden", 403)

    member = db.get_play_campaign_member(campaign_id, user["username"])
    if member is None:
        return error_response("forbidden", 403)

    if campaign["current_actor"] != user["username"]:
        return error_response("conflict", 409)

    try:
        body = json_body(request)
        rest_type = body["type"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if rest_type not in ("short", "long"):
        return error_response("invalid type", 400)

    hp_current = member["hp_current"]
    if rest_type == "long":
        hp_current = member["hp_max"]
        db.set_play_campaign_member_hp(campaign_id, user["username"], hp_current)

    event = db.create_play_campaign_rest_event(
        campaign_id, user["username"], rest_type, hp_current, member["hp_max"]
    )
    db.set_play_campaign_current_actor(campaign_id, campaign["owner"])

    response = dict(event)
    response["next_actor"] = "dm"
    return JsonResponse(response, status=201)


@csrf_exempt
def play_campaign_encounters_collection(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        encounter_id = body["id"]
        name = body["name"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(encounter_id, str) or not encounter_id:
        return error_response("invalid id", 400)
    if not isinstance(name, str) or not name:
        return error_response("invalid name", 400)

    if db.get_play_campaign_encounter(campaign_id, encounter_id) is not None:
        return error_response("encounter already exists", 409)
    if db.get_active_play_campaign_encounter(campaign_id) is not None:
        return error_response("campaign already in combat", 409)

    encounter = {"id": encounter_id, "name": name, "status": "active", "combatants": []}
    db.create_play_campaign_encounter(campaign_id, encounter)
    if campaign["combat_phase"] != "combat":
        db.enter_play_campaign_combat(campaign_id, campaign["current_actor"])

    return JsonResponse(encounter, status=201)


@csrf_exempt
def play_campaign_encounter_monsters_collection(request, campaign_id, enc_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    encounter = db.get_play_campaign_encounter(campaign_id, enc_id)
    if encounter is None:
        return error_response("encounter not found", 404)

    try:
        body = json_body(request)
        monster_id = body["monster_id"]
        name = body["name"]
        hp_max = body["hp_max"]
        initiative = body["initiative"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(monster_id, str) or not monster_id:
        return error_response("invalid monster_id", 400)
    if not isinstance(name, str) or not name:
        return error_response("invalid name", 400)
    if not isinstance(hp_max, int) or isinstance(hp_max, bool):
        return error_response("invalid hp_max", 400)
    if not isinstance(initiative, int) or isinstance(initiative, bool):
        return error_response("invalid initiative", 400)

    combatants = encounter["combatants"]
    for combatant in combatants:
        if combatant.get("monster_id") == monster_id:
            return error_response("monster already exists", 409)

    monster = {
        "monster_id": monster_id,
        "name": name,
        "hp_max": hp_max,
        "initiative": initiative,
        "hp_current": hp_max,
    }
    combatants.append(monster)
    db.set_play_campaign_encounter_combatants(campaign_id, enc_id, combatants)

    return JsonResponse(monster, status=201)


@csrf_exempt
def play_campaign_encounter_monster_detail(request, campaign_id, enc_id, monster_id):
    method_error = require_method(request, "DELETE")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    encounter = db.get_play_campaign_encounter(campaign_id, enc_id)
    if encounter is None:
        return error_response("encounter not found", 404)

    combatants = encounter["combatants"]
    remaining = [c for c in combatants if c.get("monster_id") != monster_id]
    if len(remaining) == len(combatants):
        return error_response("monster not found", 404)

    db.set_play_campaign_encounter_combatants(campaign_id, enc_id, remaining)

    return JsonResponse({"removed": monster_id})


@csrf_exempt
def play_campaign_encounter_combatants_collection(request, campaign_id, enc_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    encounter = db.get_play_campaign_encounter(campaign_id, enc_id)
    if encounter is None:
        return error_response("encounter not found", 404)

    try:
        body = json_body(request)
        member_username = body["member"]
        initiative = body["initiative"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(member_username, str) or not member_username:
        return error_response("invalid member", 400)
    if not isinstance(initiative, int) or isinstance(initiative, bool):
        return error_response("invalid initiative", 400)

    member = db.get_play_campaign_member(campaign_id, member_username)
    if member is None:
        return error_response("member not found", 400)

    combatants = encounter["combatants"]
    for combatant in combatants:
        if combatant.get("member") == member_username:
            return error_response("member already exists", 409)

    combatant = {
        "member": member_username,
        "character_id": member["character_id"],
        "name": member["name"],
        "initiative": initiative,
    }
    combatants.append(combatant)
    db.set_play_campaign_encounter_combatants(campaign_id, enc_id, combatants)

    return JsonResponse(combatant, status=201)


@csrf_exempt
def play_campaign_encounter_combatant_detail(request, campaign_id, enc_id, member):
    method_error = require_method(request, "DELETE")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    encounter = db.get_play_campaign_encounter(campaign_id, enc_id)
    if encounter is None:
        return error_response("encounter not found", 404)

    combatants = encounter["combatants"]
    remaining = [c for c in combatants if c.get("member") != member]
    if len(remaining) == len(combatants):
        return error_response("member not found", 404)

    db.set_play_campaign_encounter_combatants(campaign_id, enc_id, remaining)

    return JsonResponse({"removed": member})


def _find_combatant(encounter, target):
    for combatant in encounter["combatants"]:
        if combatant.get("monster_id") == target or combatant.get("member") == target:
            return combatant
    return None


def _apply_hp_delta(request, campaign_id, enc_id, direction):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    encounter = db.get_play_campaign_encounter(campaign_id, enc_id)
    if encounter is None:
        return error_response("encounter not found", 404)

    try:
        body = json_body(request)
        target = body["target"]
        amount = body["amount"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(target, str) or not target:
        return error_response("invalid target", 400)
    if not isinstance(amount, int) or isinstance(amount, bool):
        return error_response("invalid amount", 400)

    combatant = _find_combatant(encounter, target)
    if combatant is None:
        return error_response("target not found", 404)

    hp_before = combatant["hp_current"]
    if direction == "damage":
        hp_after = max(0, hp_before - amount)
    else:
        hp_after = min(combatant["hp_max"], hp_before + amount)
    combatant["hp_current"] = hp_after

    db.set_play_campaign_encounter_combatants(campaign_id, enc_id, encounter["combatants"])

    if direction == "damage":
        return JsonResponse(
            {"target": target, "hp_before": hp_before, "hp_after": hp_after, "damage": amount}
        )
    return JsonResponse(
        {"target": target, "hp_before": hp_before, "hp_after": hp_after, "healing": amount}
    )


@csrf_exempt
def play_campaign_encounter_damage(request, campaign_id, enc_id):
    return _apply_hp_delta(request, campaign_id, enc_id, "damage")


@csrf_exempt
def play_campaign_encounter_heal(request, campaign_id, enc_id):
    return _apply_hp_delta(request, campaign_id, enc_id, "heal")


def _combatant_key(combatant, kind):
    return combatant["monster_id"] if kind == "monster" else combatant["member"]


def _ordered_combatants(encounter):
    """Initiative order: highest initiative first, ties broken by name.

    A prior ``delay`` call may have stored an explicit ``turn_order`` (a list
    of combatant keys). When present, it takes precedence so the delayed
    combatant's new position sticks instead of snapping back to initiative
    order on every request. Combatants not listed in ``turn_order`` (e.g.
    newly added ones) fall in after it, in default initiative order.
    """
    combatants = encounter["combatants"]
    entries = []
    for combatant in combatants:
        if "monster_id" in combatant:
            kind = "monster"
        else:
            kind = "player"
        entries.append((combatant, kind))
    entries.sort(key=lambda entry: (-entry[0]["initiative"], entry[0]["name"]))

    turn_order = encounter.get("turn_order")
    if not turn_order:
        return entries

    by_key = {_combatant_key(combatant, kind): (combatant, kind) for combatant, kind in entries}
    ordered = []
    for key in turn_order:
        entry = by_key.pop(key, None)
        if entry is not None:
            ordered.append(entry)
    for combatant, kind in entries:
        key = _combatant_key(combatant, kind)
        if key in by_key:
            ordered.append((combatant, kind))
    return ordered


def _active_combatant_payload(combatant, kind):
    return {"name": combatant["name"], "kind": kind, "initiative": combatant["initiative"]}


@csrf_exempt
def play_campaign_encounter_turn(request, campaign_id, enc_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    encounter = db.get_play_campaign_encounter(campaign_id, enc_id)
    if encounter is None:
        return error_response("encounter not found", 404)

    order = _ordered_combatants(encounter)
    if not order:
        return error_response("no combatants", 409)

    turn_index = encounter["turn_index"] % len(order)
    combatant, kind = order[turn_index]

    return JsonResponse(
        {
            "round": encounter["round"],
            "turn_index": turn_index,
            "active": _active_combatant_payload(combatant, kind),
        }
    )


@csrf_exempt
def play_campaign_encounter_turn_advance(request, campaign_id, enc_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    encounter = db.get_play_campaign_encounter(campaign_id, enc_id)
    if encounter is None:
        return error_response("encounter not found", 404)

    order = _ordered_combatants(encounter)
    if not order:
        return error_response("no combatants", 409)

    turn_index = encounter["turn_index"] % len(order)
    combatant, kind = order[turn_index]

    is_owner = user["username"] == campaign["owner"]
    is_current_combatant = kind == "player" and combatant["member"] == user["username"]
    if not is_owner and not is_current_combatant:
        return error_response("conflict", 409)

    next_index = turn_index + 1
    round_number = encounter["round"]
    if next_index >= len(order):
        next_index = 0
        round_number += 1

    db.set_play_campaign_encounter_turn(campaign_id, enc_id, round_number, next_index)

    next_combatant, next_kind = order[next_index]
    next_target = next_combatant["member"] if next_kind == "player" else next_combatant["monster_id"]

    conditions = encounter["conditions"]
    target_conditions = conditions.get(next_target)
    if target_conditions:
        remaining = []
        for entry in target_conditions:
            entry["remaining_rounds"] -= 1
            if entry["remaining_rounds"] > 0:
                remaining.append(entry)
        if remaining:
            conditions[next_target] = remaining
        else:
            conditions.pop(next_target, None)
        db.set_play_campaign_encounter_conditions(campaign_id, enc_id, conditions)

    return JsonResponse(
        {
            "round": round_number,
            "turn_index": next_index,
            "active": _active_combatant_payload(next_combatant, next_kind),
        }
    )


@csrf_exempt
def play_campaign_encounter_turn_delay(request, campaign_id, enc_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    encounter = db.get_play_campaign_encounter(campaign_id, enc_id)
    if encounter is None:
        return error_response("encounter not found", 404)

    order = _ordered_combatants(encounter)
    if not order:
        return error_response("no combatants", 409)

    turn_index = encounter["turn_index"] % len(order)
    combatant, kind = order[turn_index]

    is_owner = user["username"] == campaign["owner"]
    is_current_combatant = kind == "player" and combatant["member"] == user["username"]
    if not is_owner and not is_current_combatant:
        return error_response("conflict", 409)

    try:
        body = json_body(request)
        to_index = body["new_index"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(to_index, int) or isinstance(to_index, bool):
        return error_response("invalid index", 400)
    if to_index <= turn_index or to_index >= len(order):
        return error_response("invalid index", 400)

    new_order = list(order)
    current_entry = new_order.pop(turn_index)
    new_order.insert(to_index, current_entry)

    turn_order_keys = [_combatant_key(c, k) for c, k in new_order]
    db.set_play_campaign_encounter_turn_order(campaign_id, enc_id, turn_order_keys, to_index)

    return JsonResponse(
        {"order": [_active_combatant_payload(c, k) for c, k in new_order]}
    )


@csrf_exempt
def play_campaign_encounter_turn_ready(request, campaign_id, enc_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    encounter = db.get_play_campaign_encounter(campaign_id, enc_id)
    if encounter is None:
        return error_response("encounter not found", 404)

    order = _ordered_combatants(encounter)
    if not order:
        return error_response("no combatants", 409)

    turn_index = encounter["turn_index"] % len(order)
    combatant, kind = order[turn_index]

    is_current_combatant = kind == "player" and combatant["member"] == user["username"]
    if not is_current_combatant:
        return error_response("conflict", 409)

    try:
        body = json_body(request)
        trigger = body["trigger"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(trigger, str) or not trigger:
        return error_response("invalid trigger", 400)

    return JsonResponse({"actor": user["username"], "trigger": trigger}, status=201)


@csrf_exempt
def play_campaign_encounter_conditions_collection(request, campaign_id, enc_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    encounter = db.get_play_campaign_encounter(campaign_id, enc_id)
    if encounter is None:
        return error_response("encounter not found", 404)

    try:
        body = json_body(request)
        target = body["target"]
        condition = body["condition"]
        duration_rounds = body["duration_rounds"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(target, str) or not target:
        return error_response("invalid target", 400)
    if not isinstance(condition, str) or not condition:
        return error_response("invalid condition", 400)
    if not isinstance(duration_rounds, int) or isinstance(duration_rounds, bool) or duration_rounds < 1:
        return error_response("invalid duration_rounds", 400)

    if _find_combatant(encounter, target) is None:
        return error_response("target not found", 404)

    conditions = encounter["conditions"]
    target_conditions = conditions.get(target, [])
    target_conditions = [entry for entry in target_conditions if entry["condition"] != condition]
    target_conditions.append({"condition": condition, "remaining_rounds": duration_rounds})
    conditions[target] = target_conditions
    db.set_play_campaign_encounter_conditions(campaign_id, enc_id, conditions)

    return JsonResponse({"target": target, "conditions": target_conditions}, status=201)


@csrf_exempt
def play_campaign_encounter_status(request, campaign_id, enc_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    encounter = db.get_play_campaign_encounter(campaign_id, enc_id)
    if encounter is None:
        return error_response("encounter not found", 404)

    order = _ordered_combatants(encounter)
    turn_index = encounter["turn_index"] % len(order) if order else 0
    active = None
    if order:
        combatant, kind = order[turn_index]
        active = _active_combatant_payload(combatant, kind)

    order_payload = []
    for combatant, kind in order:
        target = combatant["member"] if kind == "player" else combatant["monster_id"]
        order_payload.append({"target": target, "name": combatant["name"], "kind": kind})

    return JsonResponse(
        {
            "round": encounter["round"],
            "turn_index": turn_index,
            "active": active,
            "order": order_payload,
            "conditions": encounter["conditions"],
        }
    )


VALID_COMBAT_ACTION_TYPES = ("attack", "help", "dodge", "ready")


@csrf_exempt
def play_campaign_encounter_actions_collection(request, campaign_id, enc_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    encounter = db.get_play_campaign_encounter(campaign_id, enc_id)
    if encounter is None:
        return error_response("encounter not found", 404)

    order = _ordered_combatants(encounter)
    if not order:
        return error_response("no combatants", 409)

    turn_index = encounter["turn_index"] % len(order)
    combatant, kind = order[turn_index]

    is_current_combatant = kind == "player" and combatant["member"] == user["username"]
    if not is_current_combatant:
        return error_response("conflict", 409)

    try:
        body = json_body(request)
        action_type = body["type"]
        text = body["text"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    target = body.get("target")

    if action_type not in VALID_COMBAT_ACTION_TYPES:
        return error_response("invalid type", 400)
    if not isinstance(text, str) or not text:
        return error_response("invalid text", 400)
    if target is not None and not isinstance(target, str):
        return error_response("invalid target", 400)

    event = db.create_play_campaign_combat_action_event(
        campaign_id, user["username"], action_type, target, text
    )

    return JsonResponse(event, status=201)


@csrf_exempt
def play_campaign_encounter_rewards(request, campaign_id, enc_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    encounter = db.get_play_campaign_encounter(campaign_id, enc_id)
    if encounter is None:
        return error_response("encounter not found", 404)

    if encounter["rewards"] is not None:
        return error_response("rewards already awarded", 409)

    try:
        body = json_body(request)
        xp = body["xp"]
        loot = body["loot"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(xp, int) or isinstance(xp, bool) or xp < 0:
        return error_response("invalid xp", 400)
    if not isinstance(loot, list):
        return error_response("invalid loot", 400)

    for item in loot:
        if not isinstance(item, dict):
            return error_response("invalid loot", 400)
        slug = item.get("slug")
        quantity = item.get("quantity")
        if not isinstance(slug, str) or not slug:
            return error_response("invalid loot", 400)
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
            return error_response("invalid loot", 400)

    rewards = {"encounter_id": enc_id, "xp": xp, "loot": loot}
    db.set_play_campaign_encounter_rewards(campaign_id, enc_id, rewards)

    return JsonResponse(rewards)


@csrf_exempt
def play_campaign_encounter_close(request, campaign_id, enc_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    encounter = db.get_play_campaign_encounter(campaign_id, enc_id)
    if encounter is None:
        return error_response("encounter not found", 404)

    xp_awarded = encounter["rewards"]["xp"] if encounter["rewards"] is not None else 0

    db.set_play_campaign_encounter_status_and_xp(campaign_id, enc_id, "closed", xp_awarded)

    return JsonResponse({"id": enc_id, "status": "closed", "xp_awarded": xp_awarded})


@csrf_exempt
def play_campaign_encounter_end(request, campaign_id, enc_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    encounter = db.get_play_campaign_encounter(campaign_id, enc_id)
    if encounter is None:
        return error_response("encounter not found", 404)

    if campaign["combat_phase"] != "combat":
        return error_response("campaign not in combat", 409)

    if encounter["status"] == "active":
        xp_awarded = encounter["rewards"]["xp"] if encounter["rewards"] is not None else 0
        db.set_play_campaign_encounter_status_and_xp(campaign_id, enc_id, "closed", xp_awarded)

    restored_actor = campaign["pre_combat_actor"] or campaign["owner"]
    db.exit_play_campaign_combat(campaign_id, restored_actor)

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "status": campaign["status"],
            "phase": "exploration",
            "current_actor": restored_actor,
        }
    )


@csrf_exempt
def play_campaign_location_travel(request, campaign_id, loc_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    destinations = db.list_play_connections(campaign_id, loc_id)

    return JsonResponse({"destinations": destinations})


@csrf_exempt
def play_campaign_character_damage(request, campaign_id, char_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    member = db.get_play_campaign_member_by_character(campaign_id, char_id)
    if member is None:
        return error_response("character not found", 404)

    try:
        body = json_body(request)
        amount = body["amount"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(amount, int) or isinstance(amount, bool):
        return error_response("invalid amount", 400)

    hp_before = member["hp_current"]
    hp_after = max(0, hp_before - amount)
    status = member["status"]
    if hp_after == 0 and status == "alive":
        status = "unconscious"

    db.set_play_campaign_member_hp_and_status(campaign_id, member["username"], hp_after, status)

    return JsonResponse(
        {
            "character_id": char_id,
            "target": char_id,
            "hp_before": hp_before,
            "hp_after": hp_after,
            "damage": amount,
            "status": status,
        }
    )


@csrf_exempt
def play_campaign_character_death_saves(request, campaign_id, char_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    member = db.get_play_campaign_member_by_character(campaign_id, char_id)
    if member is None:
        return error_response("character not found", 404)

    if user["username"] != member["username"]:
        return error_response("forbidden", 403)

    if member["status"] != "unconscious":
        return error_response("conflict", 409)

    try:
        body = json_body(request)
        outcome = body["outcome"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if outcome not in ("success", "failure"):
        return error_response("invalid outcome", 400)

    successes = member["death_save_successes"]
    failures = member["death_save_failures"]
    if outcome == "success":
        successes += 1
    else:
        failures += 1

    status = "unconscious"
    if successes >= 3:
        status = "stable"
    elif failures >= 3:
        status = "dead"

    db.set_play_campaign_member_death_saves(campaign_id, member["username"], successes, failures, status)

    return JsonResponse(
        {
            "character_id": char_id,
            "successes": successes,
            "failures": failures,
            "status": status,
        },
        status=201,
    )


@csrf_exempt
def play_campaign_character_owner(request, campaign_id, char_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    member = db.get_play_campaign_member_by_character(campaign_id, char_id)
    if member is None:
        return error_response("character not found", 404)

    return JsonResponse({"character_id": char_id, "owner": member["owner"]})


@csrf_exempt
def play_campaign_character_claim(request, campaign_id, char_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    member = db.get_play_campaign_member_by_character(campaign_id, char_id)
    if member is None:
        return error_response("character not found", 404)

    if member["owner"] is not None and member["owner"] != user["username"]:
        return error_response("conflict", 409)

    db.set_play_campaign_member_owner(campaign_id, member["username"], user["username"])

    return JsonResponse({"character_id": char_id, "owner": user["username"]}, status=201)


@csrf_exempt
def play_campaign_character_transfer(request, campaign_id, char_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    member = db.get_play_campaign_member_by_character(campaign_id, char_id)
    if member is None:
        return error_response("character not found", 404)

    if member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        new_owner = body["new_owner"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(new_owner, str) or not new_owner:
        return error_response("invalid new_owner", 400)

    if db.get_play_campaign_member(campaign_id, new_owner) is None:
        return error_response("new owner not a campaign member", 400)

    db.set_play_campaign_member_owner(campaign_id, member["username"], new_owner)

    return JsonResponse({"character_id": char_id, "owner": new_owner})


@csrf_exempt
def play_campaign_character_status(request, campaign_id, char_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    member = db.get_play_campaign_member_by_character(campaign_id, char_id)
    if member is None:
        return error_response("character not found", 404)

    return JsonResponse(
        {
            "character_id": char_id,
            "hp_current": member["hp_current"],
            "hp_max": member["hp_max"],
            "status": member["status"],
        }
    )


@csrf_exempt
def play_campaign_character_build(request, campaign_id, char_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    member = db.get_play_campaign_member_by_character(campaign_id, char_id)
    if member is None:
        return error_response("character not found", 404)

    if member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        race = body["race"]
        char_class = body["class"]
        background = body["background"]
        abilities = body["abilities"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if race not in VALID_RACES:
        return error_response("invalid race", 400)
    if char_class not in HIT_DICE:
        return error_response("invalid class", 400)
    if background not in VALID_BACKGROUNDS:
        return error_response("invalid background", 400)
    if not isinstance(abilities, dict):
        return error_response("invalid abilities", 400)

    modifiers = {}
    for key in ABILITY_KEYS:
        if key not in abilities:
            return error_response("invalid abilities", 400)
        mod = ability_modifier(abilities[key])
        if mod is None:
            return error_response("invalid abilities", 400)
        modifiers[key] = mod

    level = 1
    hp_max = hp_max_at_level1(char_class, modifiers["con"])
    prof_bonus = proficiency_bonus(level)

    db.set_play_campaign_member_build(
        campaign_id,
        member["username"],
        race,
        char_class,
        background,
        level,
        hp_max,
        prof_bonus,
        modifiers["con"],
        modifiers,
    )

    return JsonResponse(
        {
            "character_id": char_id,
            "race": race,
            "class": char_class,
            "background": background,
            "level": level,
            "hp_max": hp_max,
            "proficiency_bonus": prof_bonus,
        }
    )


@csrf_exempt
def play_campaign_character_level_up(request, campaign_id, char_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    member = db.get_play_campaign_member_by_character(campaign_id, char_id)
    if member is None:
        return error_response("character not found", 404)

    if member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        new_level = body["level"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(new_level, int) or isinstance(new_level, bool) or not (1 <= new_level <= 20):
        return error_response("invalid level", 400)

    current_level = member["level"]
    if new_level != current_level + 1:
        return error_response("level must be exactly one higher than the current level", 400)

    char_class = member["class"]
    if char_class not in HIT_DICE:
        return error_response("character has no class assigned", 400)

    hit_die = HIT_DICE[char_class]
    con_modifier = member["con_modifier"]
    hp_gain = hit_die // 2 + 1 + con_modifier

    new_hp_max = member["hp_max"] + hp_gain
    new_hp_current = min(new_hp_max, member["hp_current"] + hp_gain)
    prof_bonus = proficiency_bonus(new_level)

    db.set_play_campaign_member_level_up(
        campaign_id, member["username"], new_level, new_hp_max, new_hp_current, prof_bonus
    )

    return JsonResponse(
        {
            "character_id": char_id,
            "level": new_level,
            "hp_max": new_hp_max,
            "hit_dice": f"1d{hit_die}",
            "proficiency_bonus": prof_bonus,
        }
    )


@csrf_exempt
def play_campaign_character_skill_check(request, campaign_id, char_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    member = db.get_play_campaign_member_by_character(campaign_id, char_id)
    if member is None:
        return error_response("character not found", 404)

    if member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        skill = body["skill"]
        ability = body["ability"]
        proficient = body["proficient"]
        roll = body["roll"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if skill not in VALID_SKILLS:
        return error_response("invalid skill", 400)
    if ability not in ABILITY_KEYS:
        return error_response("invalid ability", 400)
    if not isinstance(proficient, bool):
        return error_response("invalid proficient", 400)
    if not isinstance(roll, int) or isinstance(roll, bool):
        return error_response("invalid roll", 400)

    ability_modifier_value = member["ability_modifiers"].get(ability, 0)
    modifier = ability_modifier_value + (member["proficiency_bonus"] if proficient else 0)
    total = roll + modifier

    return JsonResponse(
        {
            "character_id": char_id,
            "skill": skill,
            "ability": ability,
            "modifier": modifier,
            "total": total,
        }
    )


@csrf_exempt
def play_campaign_character_spells(request, campaign_id, char_id):
    method_error = require_method(request, "GET", "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    member = db.get_play_campaign_member_by_character(campaign_id, char_id)
    if member is None:
        return error_response("character not found", 404)

    if request.method == "GET":
        if not is_play_participant(campaign, user["username"]):
            return error_response("forbidden", 403)
        spells = db.list_play_campaign_character_spells(campaign_id, char_id)
        return JsonResponse({"spells": spells})

    if member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        spell_id = body["spell_id"]
        name = body["name"]
        level = body["level"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(spell_id, str) or not spell_id:
        return error_response("invalid spell_id", 400)
    if not isinstance(name, str) or not name:
        return error_response("invalid name", 400)
    if not isinstance(level, int) or isinstance(level, bool) or not (0 <= level <= 9):
        return error_response("invalid level", 400)

    if member["class"] not in SPELLCASTING_CLASSES:
        return error_response("invalid class/spell combination", 400)

    if db.get_play_campaign_character_spell(campaign_id, char_id, spell_id) is not None:
        return error_response("spell already known", 409)

    spell = {"spell_id": spell_id, "name": name, "level": level}
    db.create_play_campaign_character_spell(campaign_id, char_id, spell)

    return JsonResponse(spell, status=201)


@csrf_exempt
def play_campaign_character_prepared_spells(request, campaign_id, char_id):
    method_error = require_method(request, "GET", "PUT")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    member = db.get_play_campaign_member_by_character(campaign_id, char_id)
    if member is None:
        return error_response("character not found", 404)

    max_prepared = member["level"]

    if request.method == "GET":
        if not is_play_participant(campaign, user["username"]):
            return error_response("forbidden", 403)
        prepared_spells = db.get_play_campaign_character_prepared_spells(campaign_id, char_id)
        return JsonResponse(
            {
                "character_id": char_id,
                "prepared_spells": prepared_spells,
                "max_prepared": max_prepared,
            }
        )

    if member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        spell_ids = body["spell_ids"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(spell_ids, list) or not all(isinstance(s, str) for s in spell_ids):
        return error_response("invalid spell_ids", 400)

    if member["class"] not in SPELLCASTING_CLASSES:
        return error_response("invalid class/spell combination", 400)

    for spell_id in spell_ids:
        if db.get_play_campaign_character_spell(campaign_id, char_id, spell_id) is None:
            return error_response("unknown spell", 400)

    if len(spell_ids) > max_prepared:
        return error_response("too many prepared spells", 400)

    db.set_play_campaign_character_prepared_spells(campaign_id, char_id, spell_ids)

    return JsonResponse(
        {
            "character_id": char_id,
            "prepared_spells": spell_ids,
            "max_prepared": max_prepared,
        }
    )


@csrf_exempt
def play_campaign_character_casts(request, campaign_id, char_id):
    method_error = require_method(request, "GET", "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    member = db.get_play_campaign_member_by_character(campaign_id, char_id)
    if member is None:
        return error_response("character not found", 404)

    if request.method == "GET":
        if not is_play_participant(campaign, user["username"]):
            return error_response("forbidden", 403)
        casts = db.list_play_campaign_character_casts(campaign_id, char_id)
        return JsonResponse(
            {
                "casts": [
                    {
                        "character_id": char_id,
                        "spell_id": cast["spell_id"],
                        "target": cast["target"],
                        "slot_level": cast["slot_level"],
                        "slots_remaining": cast["slots_remaining"],
                        "sequence": cast["sequence"],
                    }
                    for cast in casts
                ]
            }
        )

    if member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        spell_id = body["spell_id"]
        target = body["target"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(spell_id, str) or not spell_id:
        return error_response("invalid spell_id", 400)
    if not isinstance(target, str) or not target:
        return error_response("invalid target", 400)

    if member["class"] not in SPELLCASTING_CLASSES:
        return error_response("not a spellcasting class", 400)

    spell = db.get_play_campaign_character_spell(campaign_id, char_id, spell_id)
    prepared_spells = db.get_play_campaign_character_prepared_spells(campaign_id, char_id)
    if spell is None or spell_id not in prepared_spells:
        return error_response("spell not prepared", 400)

    spell_level = spell["level"]
    char_level = member["level"] or 1
    slots_max = spell_slots_at_level(char_level, spell_level)
    casts_at_level = db.count_play_campaign_character_casts_at_level(campaign_id, char_id, spell_level)
    slots_remaining = slots_max - casts_at_level
    if slots_remaining < 1:
        return error_response("no spell slots remaining", 409)
    slots_remaining -= 1

    sequence = db.create_play_campaign_character_cast(
        campaign_id,
        char_id,
        {
            "spell_id": spell_id,
            "target": target,
            "slot_level": spell_level,
            "slots_remaining": slots_remaining,
        },
    )

    return JsonResponse(
        {
            "character_id": char_id,
            "spell_id": spell_id,
            "target": target,
            "slot_level": spell_level,
            "slots_remaining": slots_remaining,
            "sequence": sequence,
        },
        status=201,
    )


@csrf_exempt
def play_campaign_character_concentration(request, campaign_id, char_id):
    method_error = require_method(request, "GET", "PUT", "DELETE")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    member = db.get_play_campaign_member_by_character(campaign_id, char_id)
    if member is None:
        return error_response("character not found", 404)

    if request.method == "GET":
        if not is_play_participant(campaign, user["username"]):
            return error_response("forbidden", 403)
        concentration = db.get_play_campaign_character_concentration(campaign_id, char_id)
        return JsonResponse({"character_id": char_id, "concentration": concentration})

    if request.method == "PUT":
        if member["owner"] != user["username"]:
            return error_response("forbidden", 403)

        try:
            body = json_body(request)
            spell_id = body["spell_id"]
            target = body["target"]
            duration_turns = body["duration_turns"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return error_response("invalid request", 400)

        if not isinstance(spell_id, str) or not spell_id:
            return error_response("invalid spell_id", 400)
        if not isinstance(target, str) or not target:
            return error_response("invalid target", 400)
        if (
            not isinstance(duration_turns, int)
            or isinstance(duration_turns, bool)
            or duration_turns < 1
        ):
            return error_response("invalid duration_turns", 400)

        if member["class"] not in SPELLCASTING_CLASSES:
            return error_response("not a spellcasting class", 400)

        spell = db.get_play_campaign_character_spell(campaign_id, char_id, spell_id)
        prepared_spells = db.get_play_campaign_character_prepared_spells(campaign_id, char_id)
        if spell is None or spell_id not in prepared_spells:
            return error_response("spell not prepared", 400)

        concentration = {
            "spell_id": spell_id,
            "target": target,
            "remaining_turns": duration_turns,
        }
        db.set_play_campaign_character_concentration(campaign_id, char_id, concentration)

        return JsonResponse({"character_id": char_id, "concentration": concentration})

    if member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    db.clear_play_campaign_character_concentration(campaign_id, char_id)
    return JsonResponse({"character_id": char_id, "concentration": None})


@csrf_exempt
def play_campaign_character_concentration_advance_turn(request, campaign_id, char_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    member = db.get_play_campaign_member_by_character(campaign_id, char_id)
    if member is None:
        return error_response("character not found", 404)

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    concentration = db.get_play_campaign_character_concentration(campaign_id, char_id)
    if concentration is not None:
        remaining_turns = concentration["remaining_turns"] - 1
        if remaining_turns <= 0:
            db.clear_play_campaign_character_concentration(campaign_id, char_id)
            concentration = None
        else:
            concentration = {**concentration, "remaining_turns": remaining_turns}
            db.set_play_campaign_character_concentration(campaign_id, char_id, concentration)

    return JsonResponse({"character_id": char_id, "concentration": concentration})


@csrf_exempt
def play_campaign_character_inventory_items_collection(request, campaign_id, character_id):
    method_error = require_method(request, "GET", "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    member = db.get_play_campaign_member_by_character(campaign_id, character_id)
    if member is None:
        return error_response("character not found", 404)

    if request.method == "GET":
        if not is_play_participant(campaign, user["username"]):
            return error_response("forbidden", 403)

        items = db.list_play_campaign_character_inventory_items(campaign_id, character_id)
        return JsonResponse({"character_id": character_id, "items": items})

    if member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        item_id = body["item_id"]
        quantity = body["quantity"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if item_id not in VALID_INVENTORY_ITEM_IDS:
        return error_response("invalid item_id", 400)
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        return error_response("invalid quantity", 400)

    total_quantity = db.add_play_campaign_character_inventory_item(
        campaign_id, character_id, item_id, quantity
    )

    return JsonResponse(
        {
            "character_id": character_id,
            "item_id": item_id,
            "quantity": quantity,
            "total_quantity": total_quantity,
        },
        status=201,
    )


@csrf_exempt
def play_campaign_character_inventory_item_detail(request, campaign_id, character_id, item_id):
    method_error = require_method(request, "DELETE")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    member = db.get_play_campaign_member_by_character(campaign_id, character_id)
    if member is None:
        return error_response("character not found", 404)

    if member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        quantity = body["quantity"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if item_id not in VALID_INVENTORY_ITEM_IDS:
        return error_response("invalid item_id", 400)
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        return error_response("invalid quantity", 400)

    held = db.get_play_campaign_character_inventory_item(campaign_id, character_id, item_id)
    held_quantity = held["quantity"] if held is not None else 0
    if quantity > held_quantity:
        return error_response("insufficient quantity", 409)

    total_quantity = db.remove_play_campaign_character_inventory_item(
        campaign_id, character_id, item_id, quantity
    )

    return JsonResponse(
        {
            "character_id": character_id,
            "item_id": item_id,
            "quantity": quantity,
            "total_quantity": total_quantity,
        }
    )


@csrf_exempt
def play_campaign_character_inventory_item_consume(request, campaign_id, character_id, item_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    member = db.get_play_campaign_member_by_character(campaign_id, character_id)
    if member is None:
        return error_response("character not found", 404)

    if member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    if item_id not in VALID_INVENTORY_ITEM_IDS or item_id not in CONSUMABLE_ITEM_IDS:
        return error_response("item not consumable", 400)

    held = db.get_play_campaign_character_inventory_item(campaign_id, character_id, item_id)
    held_quantity = held["quantity"] if held is not None else 0
    if held_quantity < 1:
        return error_response("item not held", 409)

    total_quantity = db.remove_play_campaign_character_inventory_item(
        campaign_id, character_id, item_id, 1
    )

    return JsonResponse(
        {
            "character_id": character_id,
            "item_id": item_id,
            "quantity_consumed": 1,
            "total_quantity": total_quantity,
            "effect": CONSUMABLE_EFFECTS[item_id],
        }
    )


@csrf_exempt
def play_campaign_character_equipment_slot(request, campaign_id, character_id, slot):
    method_error = require_method(request, "GET", "PUT")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    member = db.get_play_campaign_member_by_character(campaign_id, character_id)
    if member is None:
        return error_response("character not found", 404)

    if request.method == "GET":
        if not is_play_participant(campaign, user["username"]):
            return error_response("forbidden", 403)

        if slot not in VALID_EQUIPMENT_SLOTS:
            return error_response("invalid slot", 400)

        equipped = db.get_play_campaign_character_equipment(campaign_id, character_id, slot)
        if equipped is None:
            return JsonResponse(
                {
                    "character_id": character_id,
                    "slot": slot,
                    "item_id": "",
                    "attuned": False,
                }
            )
        return JsonResponse(
            {
                "character_id": character_id,
                "slot": slot,
                "item_id": equipped["item_id"],
                "attuned": equipped["attuned"],
            }
        )

    if member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    if slot not in VALID_EQUIPMENT_SLOTS:
        return error_response("invalid slot", 400)

    try:
        body = json_body(request)
        item_id = body["item_id"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if item_id not in ITEM_SLOT_BY_ID:
        return error_response("invalid item_id", 400)
    if ITEM_SLOT_BY_ID[item_id] != slot:
        return error_response("item does not fit slot", 400)

    held = db.get_play_campaign_character_inventory_item(campaign_id, character_id, item_id)
    if held is None or held["quantity"] < 1:
        return error_response("item not held", 400)

    db.set_play_campaign_character_equipment(campaign_id, character_id, slot, item_id)

    return JsonResponse(
        {
            "character_id": character_id,
            "slot": slot,
            "item_id": item_id,
            "attuned": False,
        }
    )


@csrf_exempt
def play_campaign_character_equipment_slot_attune(request, campaign_id, character_id, slot):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    member = db.get_play_campaign_member_by_character(campaign_id, character_id)
    if member is None:
        return error_response("character not found", 404)

    if member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    if slot not in VALID_EQUIPMENT_SLOTS:
        return error_response("invalid slot", 400)

    equipped = db.get_play_campaign_character_equipment(campaign_id, character_id, slot)
    if equipped is None or equipped["item_id"] not in ATTUNABLE_ITEM_IDS:
        return error_response("invalid slot", 400)

    if equipped["attuned"]:
        return error_response("already attuned", 409)

    attunement_count = db.count_play_campaign_character_attunements(campaign_id, character_id)
    if attunement_count >= MAX_ATTUNEMENTS:
        return error_response("attunement limit reached", 409)

    db.set_play_campaign_character_equipment_attuned(campaign_id, character_id, slot)
    attunement_count += 1

    return JsonResponse(
        {
            "character_id": character_id,
            "slot": slot,
            "item_id": equipped["item_id"],
            "attuned": True,
            "attunement_count": attunement_count,
            "max_attunements": MAX_ATTUNEMENTS,
        }
    )

    return JsonResponse({"character_id": char_id, "concentration": concentration})


@csrf_exempt
def play_campaign_character_currency(request, campaign_id, character_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    member = db.get_play_campaign_member_by_character(campaign_id, character_id)
    if member is None:
        return error_response("character not found", 404)

    return JsonResponse({"character_id": character_id, "gold": member["gold"]})


@csrf_exempt
def play_campaign_character_currency_transfers(request, campaign_id, character_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    member = db.get_play_campaign_member_by_character(campaign_id, character_id)
    if member is None:
        return error_response("character not found", 404)

    if member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        to_character_id = body["to_character_id"]
        gold = body["gold"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(gold, int) or isinstance(gold, bool) or gold <= 0:
        return error_response("invalid gold amount", 400)

    if not isinstance(to_character_id, str) or to_character_id == character_id:
        return error_response("invalid destination", 400)

    destination = db.get_play_campaign_member_by_character(campaign_id, to_character_id)
    if destination is None:
        return error_response("invalid destination", 400)

    result = db.transfer_play_campaign_gold(campaign_id, character_id, to_character_id, gold)
    if result is None:
        return error_response("insufficient gold", 409)

    return JsonResponse(
        {
            "from_character_id": character_id,
            "to_character_id": to_character_id,
            "gold": gold,
            "from_gold": result["from_gold"],
            "to_gold": result["to_gold"],
            "transfer_id": result["transfer_id"],
        },
        status=201,
    )


@csrf_exempt
def play_campaign_loot_collection(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        loot_id = body["loot_id"]
        item_id = body["item_id"]
        quantity = body["quantity"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(loot_id, str) or not loot_id:
        return error_response("invalid loot_id", 400)
    if item_id not in VALID_INVENTORY_ITEM_IDS:
        return error_response("invalid item_id", 400)
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        return error_response("invalid quantity", 400)

    loot = db.create_play_campaign_loot(campaign_id, loot_id, item_id, quantity)
    if loot is None:
        return error_response("loot already exists", 409)

    return JsonResponse(loot, status=201)


@csrf_exempt
def play_campaign_loot_detail(request, campaign_id, loot_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    loot = db.get_play_campaign_loot(campaign_id, loot_id)
    if loot is None:
        return error_response("loot not found", 404)

    return JsonResponse(loot)


@csrf_exempt
def play_campaign_loot_votes_collection(request, campaign_id, loot_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]) or user["username"] == campaign["owner"]:
        return error_response("forbidden", 403)

    loot = db.get_play_campaign_loot(campaign_id, loot_id)
    if loot is None:
        return error_response("loot not found", 404)

    try:
        body = json_body(request)
        recipient_character_id = body["recipient_character_id"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(recipient_character_id, str) or not recipient_character_id:
        return error_response("invalid recipient_character_id", 400)

    recipient = db.get_play_campaign_member_by_character(campaign_id, recipient_character_id)
    if recipient is None:
        return error_response("invalid recipient_character_id", 400)

    result = db.create_play_campaign_loot_vote(
        campaign_id, loot_id, user["username"], recipient_character_id
    )
    if result is None:
        return error_response("conflict", 409)

    return JsonResponse(
        {
            "loot_id": loot_id,
            "voter": user["username"],
            "recipient_character_id": recipient_character_id,
            "votes_for_recipient": result["votes_for_recipient"],
        },
        status=201,
    )


@csrf_exempt
def play_campaign_loot_assign(request, campaign_id, loot_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    if db.get_play_campaign_loot(campaign_id, loot_id) is None:
        return error_response("loot not found", 404)

    result, error = db.assign_play_campaign_loot(campaign_id, loot_id)
    if error is not None:
        return error_response("conflict", 409)

    return JsonResponse(result)


@csrf_exempt
def play_campaign_npcs_collection(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        npc_id = body["npc_id"]
        name = body["name"]
        agenda = body["agenda"]
        public_status = body["public_status"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(npc_id, str) or not npc_id:
        return error_response("invalid npc_id", 400)
    if not isinstance(name, str) or not name:
        return error_response("invalid name", 400)
    if not isinstance(agenda, str) or not agenda:
        return error_response("invalid agenda", 400)
    if not isinstance(public_status, str) or not public_status:
        return error_response("invalid public_status", 400)

    npc = db.create_play_campaign_npc(campaign_id, npc_id, name, agenda, public_status)
    if npc is None:
        return error_response("npc already exists", 409)

    return JsonResponse(npc, status=201)


@csrf_exempt
def play_campaign_npc_agenda(request, campaign_id, npc_id):
    method_error = require_method(request, "PUT")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        agenda = body["agenda"]
        public_status = body["public_status"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(agenda, str) or not agenda:
        return error_response("invalid agenda", 400)
    if not isinstance(public_status, str) or not public_status:
        return error_response("invalid public_status", 400)

    npc = db.update_play_campaign_npc_agenda(campaign_id, npc_id, agenda, public_status)
    if npc is None:
        return error_response("npc not found", 404)

    return JsonResponse(npc)


@csrf_exempt
def play_campaign_npc_detail(request, campaign_id, npc_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    npc = db.get_play_campaign_npc(campaign_id, npc_id)
    if npc is None:
        return error_response("npc not found", 404)

    if user["username"] == campaign["owner"]:
        return JsonResponse(npc)

    return JsonResponse(
        {
            "npc_id": npc["npc_id"],
            "name": npc["name"],
            "public_status": npc["public_status"],
        }
    )


@csrf_exempt
def play_campaign_npc_dialogue_collection(request, campaign_id, npc_id):
    method_error = require_method(request, "GET", "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    is_dm = user["username"] == campaign["owner"]

    if request.method == "POST":
        if not is_dm:
            return error_response("forbidden", 403)

        if db.get_play_campaign_npc(campaign_id, npc_id) is None:
            return error_response("npc not found", 404)

        try:
            body = json_body(request)
            dialogue_id = body["dialogue_id"]
            speaker = body["speaker"]
            text = body["text"]
            visibility = body["visibility"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return error_response("invalid request", 400)

        if not isinstance(dialogue_id, str) or not dialogue_id:
            return error_response("invalid dialogue_id", 400)
        if not isinstance(speaker, str) or not speaker:
            return error_response("invalid speaker", 400)
        if not isinstance(text, str) or not text:
            return error_response("invalid text", 400)
        if visibility not in ("public", "private"):
            return error_response("invalid visibility", 400)

        entry = db.create_play_campaign_npc_dialogue(
            campaign_id, npc_id, dialogue_id, speaker, text, visibility
        )
        if entry is None:
            return error_response("dialogue already exists", 409)

        return JsonResponse(entry, status=201)

    if db.get_play_campaign_npc(campaign_id, npc_id) is None:
        return error_response("npc not found", 404)

    entries = db.list_play_campaign_npc_dialogue(campaign_id, npc_id)
    if not is_dm:
        entries = [entry for entry in entries if entry["visibility"] == "public"]

    return JsonResponse({"npc_id": npc_id, "entries": entries})


MIN_REPUTATION_DELTA = -25
MAX_REPUTATION_DELTA = 25


@csrf_exempt
def play_campaign_factions_collection(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        faction_id = body["faction_id"]
        name = body["name"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(faction_id, str) or not faction_id:
        return error_response("invalid faction_id", 400)
    if not isinstance(name, str) or not name:
        return error_response("invalid name", 400)

    faction = db.create_play_campaign_faction(campaign_id, faction_id, name)
    if faction is None:
        return error_response("faction already exists", 409)

    return JsonResponse(faction, status=201)


@csrf_exempt
def play_campaign_faction_reputation_collection(request, campaign_id, faction_id):
    method_error = require_method(request, "GET", "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if request.method == "GET":
        if not is_play_participant(campaign, user["username"]):
            return error_response("forbidden", 403)

        faction = db.get_play_campaign_faction(campaign_id, faction_id)
        if faction is None:
            return error_response("faction not found", 404)

        is_owner = user["username"] == campaign["owner"]
        if is_owner:
            entries = db.list_play_campaign_faction_reputation(campaign_id, faction_id)
        else:
            member = db.get_play_campaign_member(campaign_id, user["username"])
            character_id = member["character_id"] if member is not None else None
            entries = db.list_play_campaign_faction_reputation(
                campaign_id, faction_id, character_id=character_id
            )

        return JsonResponse({"faction_id": faction_id, "entries": entries})

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    faction = db.get_play_campaign_faction(campaign_id, faction_id)
    if faction is None:
        return error_response("faction not found", 404)

    try:
        body = json_body(request)
        character_id = body["character_id"]
        delta = body["delta"]
        reason = body["reason"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(character_id, str) or not character_id:
        return error_response("invalid character_id", 400)
    if (
        not isinstance(delta, int)
        or isinstance(delta, bool)
        or delta == 0
        or not (MIN_REPUTATION_DELTA <= delta <= MAX_REPUTATION_DELTA)
    ):
        return error_response("invalid delta", 400)
    if not isinstance(reason, str) or not reason:
        return error_response("invalid reason", 400)

    member = db.get_play_campaign_member_by_character(campaign_id, character_id)
    if member is None:
        return error_response("invalid character_id", 400)

    entry = db.create_play_campaign_faction_reputation_entry(
        campaign_id, faction_id, character_id, delta, reason
    )

    return JsonResponse(entry, status=201)


MIN_RELATIONSHIP_SCORE = -100
MAX_RELATIONSHIP_SCORE = 100


def _play_campaign_entity_exists(campaign_id, entity_id):
    """True if ``entity_id`` names a campaign member's character or a campaign NPC."""
    if db.get_play_campaign_member_by_character(campaign_id, entity_id) is not None:
        return True
    return db.get_play_campaign_npc(campaign_id, entity_id) is not None


@csrf_exempt
def play_campaign_relationships_collection(request, campaign_id):
    method_error = require_method(request, "GET", "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    if request.method == "GET":
        edges = db.list_play_campaign_relationships(campaign_id)
        return JsonResponse({"edges": edges})

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        source_id = body["source_id"]
        target_id = body["target_id"]
        kind = body["kind"]
        score = body["score"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(source_id, str) or not source_id:
        return error_response("invalid source_id", 400)
    if not isinstance(target_id, str) or not target_id:
        return error_response("invalid target_id", 400)
    if source_id == target_id:
        return error_response("source_id and target_id must differ", 400)
    if not isinstance(kind, str) or not kind:
        return error_response("invalid kind", 400)
    if (
        not isinstance(score, int)
        or isinstance(score, bool)
        or not (MIN_RELATIONSHIP_SCORE <= score <= MAX_RELATIONSHIP_SCORE)
    ):
        return error_response("invalid score", 400)

    if not _play_campaign_entity_exists(campaign_id, source_id):
        return error_response("source_id not found", 404)
    if not _play_campaign_entity_exists(campaign_id, target_id):
        return error_response("target_id not found", 404)

    edge = db.create_play_campaign_relationship(campaign_id, source_id, target_id, kind, score)
    if edge is None:
        return error_response("relationship already exists", 409)

    return JsonResponse(edge, status=201)


@csrf_exempt
def play_campaign_relationship_detail(request, campaign_id, source_id, target_id, kind):
    method_error = require_method(request, "PUT")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        score = body["score"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if (
        not isinstance(score, int)
        or isinstance(score, bool)
        or not (MIN_RELATIONSHIP_SCORE <= score <= MAX_RELATIONSHIP_SCORE)
    ):
        return error_response("invalid score", 400)

    edge = db.update_play_campaign_relationship(campaign_id, source_id, target_id, kind, score)
    if edge is None:
        return error_response("relationship not found", 404)

    return JsonResponse(edge)


VALID_CLUE_AUDIENCES = ("character", "party", "hidden")


@csrf_exempt
def play_campaign_clues_collection(request, campaign_id):
    method_error = require_method(request, "GET", "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    is_dm = user["username"] == campaign["owner"]

    if request.method == "GET":
        clues = db.list_play_campaign_clues(campaign_id)
        if is_dm:
            return JsonResponse({"clues": clues})

        member = db.get_play_campaign_member(campaign_id, user["username"])
        character_id = member["character_id"] if member is not None else None
        visible = [
            clue
            for clue in clues
            if clue["audience"] == "party"
            or (clue["audience"] == "character" and clue.get("character_id") == character_id)
        ]
        return JsonResponse({"clues": visible})

    if not is_dm:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        clue_id = body["clue_id"]
        text = body["text"]
        audience = body["audience"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(clue_id, str) or not clue_id:
        return error_response("invalid clue_id", 400)
    if not isinstance(text, str) or not text:
        return error_response("invalid text", 400)
    if audience not in VALID_CLUE_AUDIENCES:
        return error_response("invalid audience", 400)

    character_id = body.get("character_id")

    if audience == "character":
        if not isinstance(character_id, str) or not character_id:
            return error_response("invalid character_id", 400)
        if db.get_play_campaign_member_by_character(campaign_id, character_id) is None:
            return error_response("character not found", 400)
    else:
        if character_id is not None:
            return error_response("invalid character_id", 400)
        character_id = None

    if db.get_play_campaign_clue(campaign_id, clue_id) is not None:
        return error_response("clue already exists", 409)

    clue = db.create_play_campaign_clue(campaign_id, clue_id, text, audience, character_id)
    if clue is None:
        return error_response("clue already exists", 409)

    return JsonResponse(clue, status=201)


VALID_QUEST_STATES = ("active", "completed")


@csrf_exempt
def play_campaign_quests_collection(request, campaign_id):
    method_error = require_method(request, "GET", "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    if request.method == "GET":
        quests = db.list_play_campaign_quests(campaign_id)
        return JsonResponse({"quests": quests})

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        quest_id = body["quest_id"]
        title = body["title"]
        depends_on = body["depends_on"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(quest_id, str) or not quest_id:
        return error_response("invalid quest_id", 400)
    if not isinstance(title, str) or not title:
        return error_response("invalid title", 400)
    if not isinstance(depends_on, list) or not all(isinstance(d, str) for d in depends_on):
        return error_response("invalid depends_on", 400)
    if len(set(depends_on)) != len(depends_on):
        return error_response("invalid depends_on", 400)
    if quest_id in depends_on:
        return error_response("invalid depends_on", 400)

    existing_quests = db.list_play_campaign_quests(campaign_id)
    existing_ids = {q["quest_id"] for q in existing_quests}
    if not all(dep in existing_ids for dep in depends_on):
        return error_response("invalid depends_on", 400)

    if db.get_play_campaign_quest(campaign_id, quest_id) is not None:
        return error_response("quest already exists", 409)

    quest = db.create_play_campaign_quest(campaign_id, quest_id, title, depends_on)
    if quest is None:
        return error_response("quest already exists", 409)

    return JsonResponse(quest, status=201)


@csrf_exempt
def play_campaign_quest_state(request, campaign_id, quest_id):
    method_error = require_method(request, "PUT")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    quest = db.get_play_campaign_quest(campaign_id, quest_id)
    if quest is None:
        return error_response("quest not found", 404)

    try:
        body = json_body(request)
        state = body["state"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if state not in VALID_QUEST_STATES:
        return error_response("invalid state", 400)

    current_state = quest["state"]
    if state == "active":
        if current_state != "locked":
            return error_response("invalid transition", 409)
        deps = quest["depends_on"]
        for dep_id in deps:
            dep_quest = db.get_play_campaign_quest(campaign_id, dep_id)
            if dep_quest is None or dep_quest["state"] != "completed":
                return error_response("dependencies not completed", 409)
    elif state == "completed":
        if current_state != "active":
            return error_response("invalid transition", 409)

    updated = db.update_play_campaign_quest_state(campaign_id, quest_id, state)
    return JsonResponse(updated)


@csrf_exempt
def play_campaign_quest_rewards(request, campaign_id, quest_id):
    method_error = require_method(request, "PUT")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    quest = db.get_play_campaign_quest(campaign_id, quest_id)
    if quest is None:
        return error_response("quest not found", 404)

    if quest["state"] == "completed":
        return error_response("quest already completed", 409)

    try:
        body = json_body(request)
        xp = body["xp"]
        items = body["items"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(xp, int) or isinstance(xp, bool) or xp < 0:
        return error_response("invalid xp", 400)
    if not isinstance(items, dict):
        return error_response("invalid items", 400)
    for item_id, quantity in items.items():
        if item_id not in VALID_INVENTORY_ITEM_IDS:
            return error_response("invalid items", 400)
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            return error_response("invalid items", 400)

    updated = db.set_play_campaign_quest_rewards(campaign_id, quest_id, xp, items)
    return JsonResponse(updated)


@csrf_exempt
def play_campaign_quest_rewards_award(request, campaign_id, quest_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    quest = db.get_play_campaign_quest(campaign_id, quest_id)
    if quest is None:
        return error_response("quest not found", 404)

    rewards = quest.get("rewards")
    if quest["state"] != "completed" or rewards is None:
        return error_response("rewards not available", 409)

    if quest["_awarded"]:
        return error_response("rewards already awarded", 409)

    for member in db.get_play_campaign_members(campaign_id):
        db.grant_play_campaign_character_reward(
            campaign_id, member["character_id"], rewards["xp"], rewards["items"]
        )
        for item_id, quantity in rewards["items"].items():
            db.add_play_campaign_character_inventory_item(
                campaign_id, member["character_id"], item_id, quantity
            )

    db.mark_play_campaign_quest_rewards_awarded(campaign_id, quest_id)

    return JsonResponse(
        {
            "quest_id": quest_id,
            "awarded": True,
            "xp": rewards["xp"],
            "items": rewards["items"],
        },
        status=201,
    )


@csrf_exempt
def play_campaign_character_rewards(request, campaign_id, character_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    member = db.get_play_campaign_member_by_character(campaign_id, character_id)
    if member is None:
        return error_response("character not found", 404)

    rewards = db.get_play_campaign_character_rewards(campaign_id, character_id)
    return JsonResponse(
        {"character_id": character_id, "xp": rewards["xp"], "items": rewards["items"]}
    )


@csrf_exempt
def play_campaign_world_events_collection(request, campaign_id):
    method_error = require_method(request, "GET", "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    if request.method == "GET":
        events = db.list_play_campaign_world_events(campaign_id)
        return JsonResponse({"events": events})

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        event_id = body["event_id"]
        turn_number = body["turn_number"]
        title = body["title"]
        text = body["text"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(event_id, str) or not event_id:
        return error_response("invalid event_id", 400)
    if not isinstance(title, str) or not title:
        return error_response("invalid title", 400)
    if not isinstance(text, str) or not text:
        return error_response("invalid text", 400)
    if not isinstance(turn_number, int) or isinstance(turn_number, bool):
        return error_response("invalid turn_number", 400)
    if turn_number < campaign["turn_number"]:
        return error_response("invalid turn_number", 400)

    if db.get_play_campaign_world_event(campaign_id, event_id) is not None:
        return error_response("world event already exists", 409)

    event = db.create_play_campaign_world_event(campaign_id, event_id, turn_number, title, text)
    if event is None:
        return error_response("world event already exists", 409)

    return JsonResponse(event, status=201)


@csrf_exempt
def play_campaign_world_event_resolve(request, campaign_id, event_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    event = db.get_play_campaign_world_event(campaign_id, event_id)
    if event is None:
        return error_response("world event not found", 404)

    try:
        body = json_body(request)
        text = body["text"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(text, str) or not text:
        return error_response("invalid text", 400)

    if event["status"] == "resolved":
        return error_response("world event already resolved", 409)

    if campaign["turn_number"] != event["turn_number"]:
        return error_response("turn mismatch", 409)

    resolved = db.resolve_play_campaign_world_event(
        campaign_id, event_id, campaign["turn_number"], text
    )
    if resolved is None:
        return error_response("world event already resolved", 409)

    return JsonResponse(resolved, status=201)


VALID_SEASONS = ("spring", "summer", "autumn", "winter")


@csrf_exempt
def play_campaign_calendar(request, campaign_id):
    method_error = require_method(request, "GET", "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if request.method == "GET":
        if not is_play_participant(campaign, user["username"]):
            return error_response("forbidden", 403)

        calendar = db.get_play_campaign_calendar(campaign_id)
        if calendar is None:
            return error_response("calendar not found", 404)
        return JsonResponse(calendar)

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        day = body["day"]
        season = body["season"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(day, int) or isinstance(day, bool) or day < 1:
        return error_response("invalid day", 400)
    if not isinstance(season, str) or season not in VALID_SEASONS:
        return error_response("invalid season", 400)

    if db.get_play_campaign_calendar(campaign_id) is not None:
        return error_response("calendar already initialized", 409)

    calendar = db.create_play_campaign_calendar(campaign_id, day, season)
    if calendar is None:
        return error_response("calendar already initialized", 409)

    return JsonResponse(calendar, status=201)


@csrf_exempt
def play_campaign_calendar_advance(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        days = body["days"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(days, int) or isinstance(days, bool) or days < 1 or days > 30:
        return error_response("invalid days", 400)

    calendar = db.advance_play_campaign_calendar(campaign_id, days)
    if calendar is None:
        return error_response("calendar not found", 404)

    return JsonResponse(calendar)


VALID_SETTLEMENT_AVAILABILITY = ("open", "limited", "closed")


def _validate_settlement_payload(body):
    """Validate and normalize a create/update settlement payload.

    Returns ``(name, services, availability, error_response)``; on success
    ``error_response`` is None.
    """
    name = body["name"]
    services = body["services"]
    availability = body["availability"]

    if not isinstance(name, str) or not name:
        return None, None, None, error_response("invalid name", 400)

    if not isinstance(services, list) or not services:
        return None, None, None, error_response("invalid services", 400)

    normalized_services = []
    seen_services = set()
    for service in services:
        if not isinstance(service, str):
            return None, None, None, error_response("invalid services", 400)
        normalized = service.strip()
        if not normalized:
            return None, None, None, error_response("invalid services", 400)
        if normalized in seen_services:
            return None, None, None, error_response("invalid services", 400)
        seen_services.add(normalized)
        normalized_services.append(normalized)

    if not isinstance(availability, str) or availability not in VALID_SETTLEMENT_AVAILABILITY:
        return None, None, None, error_response("invalid availability", 400)

    return name, normalized_services, availability, None


def _player_settlement_view(settlement, character_id):
    discovered_by = [character_id] if character_id in settlement["discovered_by"] else []
    return {**settlement, "discovered_by": discovered_by}


@csrf_exempt
def play_campaign_settlements_collection(request, campaign_id):
    method_error = require_method(request, "GET", "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    if request.method == "GET":
        settlements = db.list_play_campaign_settlements(campaign_id)
        if user["username"] == campaign["owner"]:
            return JsonResponse({"settlements": settlements})

        member = db.get_play_campaign_member(campaign_id, user["username"])
        character_id = member["character_id"]
        visible = [
            _player_settlement_view(settlement, character_id)
            for settlement in settlements
            if character_id in settlement["discovered_by"]
        ]
        return JsonResponse({"settlements": visible})

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        settlement_id = body["settlement_id"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(settlement_id, str) or not settlement_id:
        return error_response("invalid settlement_id", 400)

    try:
        name, services, availability, validation_error = _validate_settlement_payload(body)
    except (KeyError, TypeError):
        return error_response("invalid request", 400)
    if validation_error:
        return validation_error

    if db.get_play_campaign_settlement(campaign_id, settlement_id) is not None:
        return error_response("settlement already exists", 409)

    settlement = db.create_play_campaign_settlement(
        campaign_id, settlement_id, name, services, availability
    )
    if settlement is None:
        return error_response("settlement already exists", 409)

    return JsonResponse(settlement, status=201)


@csrf_exempt
def play_campaign_settlement_detail(request, campaign_id, settlement_id):
    method_error = require_method(request, "PUT")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    if db.get_play_campaign_settlement(campaign_id, settlement_id) is None:
        return error_response("settlement not found", 404)

    try:
        body = json_body(request)
        name, services, availability, validation_error = _validate_settlement_payload(body)
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)
    if validation_error:
        return validation_error

    settlement = db.update_play_campaign_settlement(
        campaign_id, settlement_id, name, services, availability
    )
    if settlement is None:
        return error_response("settlement not found", 404)

    return JsonResponse(settlement)


@csrf_exempt
def play_campaign_settlement_discover(request, campaign_id, settlement_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] == campaign["owner"]:
        return error_response("forbidden", 403)

    member = db.get_play_campaign_member(campaign_id, user["username"])
    if member is None:
        return error_response("forbidden", 403)

    if db.get_play_campaign_settlement(campaign_id, settlement_id) is None:
        return error_response("settlement not found", 404)

    settlement, created = db.discover_play_campaign_settlement(
        campaign_id, settlement_id, member["character_id"]
    )
    if settlement is None:
        return error_response("settlement not found", 404)

    view = _player_settlement_view(settlement, member["character_id"])
    return JsonResponse(view, status=201 if created else 200)


def _validate_shop_payload(body):
    """Validate and normalize a create-shop payload.

    Returns ``(shop_id, name, stock, buy_price, sell_price, error_response)``;
    on success ``error_response`` is None.
    """
    shop_id = body["shop_id"]
    name = body["name"]
    stock = body["stock"]
    buy_price = body["buy_price"]
    sell_price = body["sell_price"]

    if not isinstance(shop_id, str) or not shop_id:
        return None, None, None, None, None, error_response("invalid shop_id", 400)

    if not isinstance(name, str) or not name:
        return None, None, None, None, None, error_response("invalid name", 400)

    if not isinstance(stock, dict) or not stock:
        return None, None, None, None, None, error_response("invalid stock", 400)

    normalized_stock = {}
    for item_id, quantity in stock.items():
        if item_id not in VALID_INVENTORY_ITEM_IDS:
            return None, None, None, None, None, error_response("invalid stock", 400)
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            return None, None, None, None, None, error_response("invalid stock", 400)
        normalized_stock[item_id] = quantity

    if not isinstance(buy_price, int) or isinstance(buy_price, bool) or buy_price < 1:
        return None, None, None, None, None, error_response("invalid buy_price", 400)

    if not isinstance(sell_price, int) or isinstance(sell_price, bool) or sell_price < 0:
        return None, None, None, None, None, error_response("invalid sell_price", 400)

    return shop_id, name, normalized_stock, buy_price, sell_price, None


@csrf_exempt
def play_campaign_settlement_shops_collection(request, campaign_id, settlement_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    if db.get_play_campaign_settlement(campaign_id, settlement_id) is None:
        return error_response("settlement not found", 404)

    try:
        body = json_body(request)
        shop_id, name, stock, buy_price, sell_price, validation_error = _validate_shop_payload(body)
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)
    if validation_error:
        return validation_error

    if db.get_play_campaign_shop(campaign_id, settlement_id, shop_id) is not None:
        return error_response("shop already exists", 409)

    shop = db.create_play_campaign_shop(
        campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price
    )
    if shop is None:
        return error_response("shop already exists", 409)

    return JsonResponse(shop, status=201)


@csrf_exempt
def play_campaign_settlement_shop_detail(request, campaign_id, settlement_id, shop_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    settlement = db.get_play_campaign_settlement(campaign_id, settlement_id)
    if settlement is None:
        return error_response("settlement not found", 404)

    if user["username"] != campaign["owner"]:
        member = db.get_play_campaign_member(campaign_id, user["username"])
        if member is None or member["character_id"] not in settlement["discovered_by"]:
            return error_response("shop not found", 404)

    shop = db.get_play_campaign_shop(campaign_id, settlement_id, shop_id)
    if shop is None:
        return error_response("shop not found", 404)

    return JsonResponse(shop)


def _validate_shop_transaction_body(body):
    """Extract and validate the shared ``character_id``/``item_id``/``quantity`` shape.

    Returns ``(character_id, item_id, quantity, error_response)``; on success
    ``error_response`` is None.
    """
    character_id = body["character_id"]
    item_id = body["item_id"]
    quantity = body["quantity"]

    if not isinstance(character_id, str) or not character_id:
        return None, None, None, error_response("invalid character_id", 400)

    return character_id, item_id, quantity, None


@csrf_exempt
def play_campaign_settlement_shop_buy(request, campaign_id, settlement_id, shop_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if db.get_play_campaign_settlement(campaign_id, settlement_id) is None:
        return error_response("settlement not found", 404)

    if db.get_play_campaign_shop(campaign_id, settlement_id, shop_id) is None:
        return error_response("shop not found", 404)

    try:
        body = json_body(request)
        character_id, item_id, quantity, validation_error = _validate_shop_transaction_body(body)
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)
    if validation_error:
        return validation_error

    member = db.get_play_campaign_member_by_character(campaign_id, character_id)
    if member is None:
        return error_response("character not found", 404)

    if user["username"] == campaign["owner"] or member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    if item_id not in VALID_INVENTORY_ITEM_IDS:
        return error_response("invalid item_id", 400)
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        return error_response("invalid quantity", 400)

    result, error = db.buy_play_campaign_shop_item(
        campaign_id, settlement_id, shop_id, character_id, item_id, quantity
    )
    if error in ("insufficient_stock", "insufficient_gold"):
        return error_response("insufficient stock or funds", 409)
    if error is not None:
        return error_response("not found", 404)

    return JsonResponse(
        {
            "character_id": character_id,
            "item_id": item_id,
            "quantity": quantity,
            "gold": result["gold"],
            "stock": result["stock"],
        }
    )


@csrf_exempt
def play_campaign_settlement_shop_sell(request, campaign_id, settlement_id, shop_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if db.get_play_campaign_settlement(campaign_id, settlement_id) is None:
        return error_response("settlement not found", 404)

    if db.get_play_campaign_shop(campaign_id, settlement_id, shop_id) is None:
        return error_response("shop not found", 404)

    try:
        body = json_body(request)
        character_id, item_id, quantity, validation_error = _validate_shop_transaction_body(body)
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)
    if validation_error:
        return validation_error

    member = db.get_play_campaign_member_by_character(campaign_id, character_id)
    if member is None:
        return error_response("character not found", 404)

    if user["username"] == campaign["owner"] or member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    if item_id not in VALID_INVENTORY_ITEM_IDS:
        return error_response("invalid item_id", 400)
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        return error_response("invalid quantity", 400)

    result, error = db.sell_play_campaign_shop_item(
        campaign_id, settlement_id, shop_id, character_id, item_id, quantity
    )
    if error == "insufficient_inventory":
        return error_response("insufficient inventory", 409)
    if error is not None:
        return error_response("not found", 404)

    return JsonResponse(
        {
            "character_id": character_id,
            "item_id": item_id,
            "quantity": quantity,
            "gold": result["gold"],
            "stock": result["stock"],
        }
    )


def _validate_recipe_body(body):
    """Validate a recipe creation payload against the recipe object contract.

    Returns ``(recipe, error_response)``; on success ``error_response`` is None.
    """
    recipe_id = body["recipe_id"]
    name = body["name"]
    ingredients = body["ingredients"]
    output_item = body["output_item"]
    output_quantity = body["output_quantity"]

    if not isinstance(recipe_id, str) or not recipe_id:
        return None, error_response("invalid recipe_id", 400)
    if not isinstance(name, str) or not name:
        return None, error_response("invalid name", 400)
    if not isinstance(ingredients, dict) or not ingredients:
        return None, error_response("invalid ingredients", 400)
    for item_id, item_quantity in ingredients.items():
        if item_id not in VALID_INVENTORY_ITEM_IDS:
            return None, error_response("invalid ingredients", 400)
        if not isinstance(item_quantity, int) or isinstance(item_quantity, bool) or item_quantity < 1:
            return None, error_response("invalid ingredients", 400)
    if output_item not in VALID_INVENTORY_ITEM_IDS:
        return None, error_response("invalid output_item", 400)
    if not isinstance(output_quantity, int) or isinstance(output_quantity, bool) or output_quantity < 1:
        return None, error_response("invalid output_quantity", 400)

    return {
        "recipe_id": recipe_id,
        "name": name,
        "ingredients": ingredients,
        "output_item": output_item,
        "output_quantity": output_quantity,
    }, None


@csrf_exempt
def play_campaign_recipes_collection(request, campaign_id):
    method_error = require_method(request, "GET", "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    if request.method == "GET":
        recipes = db.list_play_campaign_recipes(campaign_id)
        return JsonResponse({"recipes": recipes})

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        recipe, validation_error = _validate_recipe_body(body)
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)
    if validation_error:
        return validation_error

    if db.get_play_campaign_recipe(campaign_id, recipe["recipe_id"]) is not None:
        return error_response("recipe already exists", 409)

    created = db.create_play_campaign_recipe(
        campaign_id,
        recipe["recipe_id"],
        recipe["name"],
        recipe["ingredients"],
        recipe["output_item"],
        recipe["output_quantity"],
    )
    if created is None:
        return error_response("recipe already exists", 409)

    return JsonResponse(created, status=201)


@csrf_exempt
def play_campaign_recipe_craft(request, campaign_id, recipe_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    recipe = db.get_play_campaign_recipe(campaign_id, recipe_id)
    if recipe is None:
        return error_response("recipe not found", 404)

    try:
        body = json_body(request)
        character_id = body["character_id"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(character_id, str) or not character_id:
        return error_response("invalid character_id", 400)

    member = db.get_play_campaign_member_by_character(campaign_id, character_id)
    if member is None:
        return error_response("character not found", 404)

    if user["username"] == campaign["owner"] or member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    ok, error = db.craft_play_campaign_recipe(campaign_id, character_id, recipe)
    if error == "insufficient_ingredients":
        return error_response("insufficient ingredients", 409)

    return JsonResponse(
        {
            "character_id": character_id,
            "recipe_id": recipe_id,
            "output_item": recipe["output_item"],
            "output_quantity": recipe["output_quantity"],
        },
        status=201,
    )


def _validate_downtime_activity_body(body):
    """Validate a downtime activity creation payload against the activity object contract.

    Returns ``(activity, error_response)``; on success ``error_response`` is None.
    """
    activity_id = body["activity_id"]
    name = body["name"]
    cycles_required = body["cycles_required"]

    if not isinstance(activity_id, str) or not activity_id:
        return None, error_response("invalid activity_id", 400)
    if not isinstance(name, str) or not name:
        return None, error_response("invalid name", 400)
    if (
        not isinstance(cycles_required, int)
        or isinstance(cycles_required, bool)
        or cycles_required < 1
        or cycles_required > 10
    ):
        return None, error_response("invalid cycles_required", 400)

    return {
        "activity_id": activity_id,
        "name": name,
        "cycles_required": cycles_required,
    }, None


@csrf_exempt
def play_campaign_downtime_activities_collection(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        activity, validation_error = _validate_downtime_activity_body(body)
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)
    if validation_error:
        return validation_error

    created = db.create_play_campaign_downtime_activity(
        campaign_id,
        activity["activity_id"],
        activity["name"],
        activity["cycles_required"],
    )
    if created is None:
        return error_response("activity already exists", 409)

    return JsonResponse(created, status=201)


@csrf_exempt
def play_campaign_downtime_allocations_collection(request, campaign_id, character_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    member = db.get_play_campaign_member_by_character(campaign_id, character_id)
    if member is None:
        return error_response("character not found", 404)

    if user["username"] == campaign["owner"] or member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        activity_id = body["activity_id"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(activity_id, str) or not activity_id:
        return error_response("invalid activity_id", 400)

    if db.get_play_campaign_downtime_activity(campaign_id, activity_id) is None:
        return error_response("activity not found", 404)

    allocation = db.create_play_campaign_downtime_allocation(campaign_id, character_id, activity_id)
    if allocation is None:
        return error_response("allocation already exists", 409)

    return JsonResponse(allocation, status=201)


@csrf_exempt
def play_campaign_downtime_allocation_progress(request, campaign_id, character_id, activity_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    member = db.get_play_campaign_member_by_character(campaign_id, character_id)
    if member is None:
        return error_response("character not found", 404)

    if user["username"] == campaign["owner"] or member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    activity = db.get_play_campaign_downtime_activity(campaign_id, activity_id)
    if activity is None:
        return error_response("activity not found", 404)

    allocation = db.advance_play_campaign_downtime_allocation(
        campaign_id, character_id, activity_id, activity["cycles_required"]
    )
    if allocation is None:
        return error_response("allocation not found", 404)

    return JsonResponse(allocation)


def play_campaign_downtime_allocation_detail(request, campaign_id, character_id, activity_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    if db.get_play_campaign_member_by_character(campaign_id, character_id) is None:
        return error_response("character not found", 404)

    if db.get_play_campaign_downtime_activity(campaign_id, activity_id) is None:
        return error_response("activity not found", 404)

    allocation = db.get_play_campaign_downtime_allocation(campaign_id, character_id, activity_id)
    if allocation is None:
        return error_response("allocation not found", 404)

    return JsonResponse(allocation)


def _valid_tag_list(tags):
    if not isinstance(tags, list):
        return False
    seen = set()
    for tag in tags:
        if not isinstance(tag, str) or not tag or tag in seen:
            return False
        seen.add(tag)
    return True


@csrf_exempt
def play_campaign_content_collection(request, campaign_id):
    method_error = require_method(request, "GET", "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    is_dm = user["username"] == campaign["owner"]

    if request.method == "GET":
        exclude_tag = request.GET.get("exclude_tag")
        if exclude_tag is not None and not exclude_tag:
            return error_response("invalid exclude_tag", 400)

        content = db.list_play_campaign_content(campaign_id)
        if is_dm or exclude_tag is None:
            return JsonResponse({"content": content})

        visible = [item for item in content if exclude_tag not in item["tags"]]
        return JsonResponse({"content": visible})

    if not is_dm:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        content_id = body["content_id"]
        kind = body["kind"]
        text = body["text"]
        tags = body["tags"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(content_id, str) or not content_id:
        return error_response("invalid content_id", 400)
    if not isinstance(kind, str) or not kind:
        return error_response("invalid kind", 400)
    if not isinstance(text, str) or not text:
        return error_response("invalid text", 400)
    if not _valid_tag_list(tags) or not tags:
        return error_response("invalid tags", 400)

    if db.get_play_campaign_content_item(campaign_id, content_id) is not None:
        return error_response("content already exists", 409)

    content_item = db.create_play_campaign_content_item(campaign_id, content_id, kind, text, tags)

    return JsonResponse(content_item, status=201)


@csrf_exempt
def play_campaign_content_tags(request, campaign_id, content_id):
    method_error = require_method(request, "PUT")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if user["username"] != campaign["owner"]:
        return error_response("forbidden", 403)

    content_item = db.get_play_campaign_content_item(campaign_id, content_id)
    if content_item is None:
        return error_response("content not found", 404)

    try:
        body = json_body(request)
        tags = body["tags"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not _valid_tag_list(tags):
        return error_response("invalid tags", 400)

    db.set_play_campaign_content_tags(campaign_id, content_id, tags)

    return JsonResponse(
        {
            "content_id": content_item["content_id"],
            "kind": content_item["kind"],
            "text": content_item["text"],
            "tags": list(tags),
        }
    )


VALID_NOTE_VISIBILITIES = ("private", "party")


@csrf_exempt
def play_campaign_notes_collection(request, campaign_id):
    method_error = require_method(request, "GET", "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    is_dm = user["username"] == campaign["owner"]

    if request.method == "GET":
        notes = db.list_play_campaign_notes(campaign_id)
        if is_dm:
            return JsonResponse({"notes": notes})

        visible = [
            note
            for note in notes
            if note["visibility"] == "party" or note["owner"] == user["username"]
        ]
        return JsonResponse({"notes": visible})

    try:
        body = json_body(request)
        note_id = body["note_id"]
        text = body["text"]
        visibility = body["visibility"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(note_id, str) or not note_id:
        return error_response("invalid note_id", 400)
    if not isinstance(text, str) or not text:
        return error_response("invalid text", 400)
    if visibility not in VALID_NOTE_VISIBILITIES:
        return error_response("invalid visibility", 400)

    if db.get_play_campaign_note(campaign_id, note_id) is not None:
        return error_response("note already exists", 409)

    note = db.create_play_campaign_note(campaign_id, note_id, text, visibility, user["username"])

    return JsonResponse(note, status=201)


@csrf_exempt
def play_campaign_note_detail(request, campaign_id, note_id):
    method_error = require_method(request, "GET", "PUT")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    is_dm = user["username"] == campaign["owner"]

    note = db.get_play_campaign_note(campaign_id, note_id)
    if note is None:
        return error_response("note not found", 404)

    if request.method == "GET":
        if is_dm or note["owner"] == user["username"] or note["visibility"] == "party":
            return JsonResponse(note)
        return error_response("forbidden", 403)

    if note["owner"] != user["username"]:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        text = body["text"]
        visibility = body["visibility"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(text, str) or not text:
        return error_response("invalid text", 400)
    if visibility not in VALID_NOTE_VISIBILITIES:
        return error_response("invalid visibility", 400)

    db.update_play_campaign_note(campaign_id, note_id, text, visibility)

    return JsonResponse(
        {
            "note_id": note["note_id"],
            "text": text,
            "visibility": visibility,
            "owner": note["owner"],
        }
    )


@csrf_exempt
def play_campaign_whispers_collection(request, campaign_id):
    method_error = require_method(request, "GET", "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    is_dm = user["username"] == campaign["owner"]

    if request.method == "GET":
        whispers = db.list_play_campaign_whispers(campaign_id)
        if is_dm:
            return JsonResponse({"whispers": whispers})

        my_member = db.get_play_campaign_member_by_owner(campaign_id, user["username"])
        my_character_id = my_member["character_id"] if my_member is not None else None
        visible = [
            whisper
            for whisper in whispers
            if whisper["from_character_id"] == my_character_id
            or whisper["to_character_id"] == my_character_id
        ]
        return JsonResponse({"whispers": visible})

    if is_dm:
        return error_response("forbidden", 403)

    sender_member = db.get_play_campaign_member_by_owner(campaign_id, user["username"])
    if sender_member is None:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        whisper_id = body["whisper_id"]
        to_character_id = body["to_character_id"]
        text = body["text"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(whisper_id, str) or not whisper_id:
        return error_response("invalid whisper_id", 400)
    if not isinstance(to_character_id, str) or not to_character_id:
        return error_response("invalid to_character_id", 400)
    if not isinstance(text, str) or not text:
        return error_response("invalid text", 400)

    if db.get_play_campaign_member_by_character(campaign_id, to_character_id) is None:
        return error_response("invalid to_character_id", 400)

    if db.get_play_campaign_whisper(campaign_id, whisper_id) is not None:
        return error_response("whisper already exists", 409)

    whisper = db.create_play_campaign_whisper(
        campaign_id, whisper_id, sender_member["character_id"], to_character_id, text
    )

    return JsonResponse(whisper, status=201)


@csrf_exempt
def play_campaign_character_sheet(request, campaign_id, character_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    if not is_play_participant(campaign, user["username"]):
        return error_response("forbidden", 403)

    member = db.get_play_campaign_member_by_character(campaign_id, character_id)
    if member is None:
        return error_response("character not found", 404)

    is_dm = user["username"] == campaign["owner"]
    if not is_dm and member["owner"] != user["username"]:
        return error_response("forbidden", 403)

    return JsonResponse(
        {
            "character_id": character_id,
            "owner": member["owner"],
            "name": member["name"],
            "class": member["class"],
            "level": 1,
            "proficiency_bonus": 2,
            "hp_max": 10,
            "armor_class": 10,
        }
    )


@csrf_exempt
def play_campaign_invitations_collection(request, campaign_id):
    method_error = require_method(request, "GET", "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    is_dm = user["username"] == campaign["owner"]

    if request.method == "GET":
        invitations = db.list_play_campaign_invitations(campaign_id)
        if is_dm:
            return JsonResponse({"invitations": invitations})
        mine = [inv for inv in invitations if inv["username"] == user["username"]]
        return JsonResponse({"invitations": mine})

    if not is_dm:
        return error_response("forbidden", 403)

    try:
        body = json_body(request)
        invitation_id = body["invitation_id"]
        username = body["username"]
        character_id = body["character_id"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(invitation_id, str) or not invitation_id:
        return error_response("invalid invitation_id", 400)
    if not isinstance(username, str) or not username:
        return error_response("invalid username", 400)
    if not isinstance(character_id, str) or not character_id:
        return error_response("invalid character_id", 400)

    target_user = db.get_user(username)
    if target_user is None or target_user["role"] != "player":
        return error_response("invalid username", 400)

    if db.get_play_campaign_invitation(campaign_id, invitation_id) is not None:
        return error_response("invitation already exists", 409)
    if db.get_play_campaign_pending_invitation_for_user(campaign_id, username) is not None:
        return error_response("active invitation already exists", 409)

    invitation = db.create_play_campaign_invitation(campaign_id, invitation_id, username, character_id)

    return JsonResponse(invitation, status=201)


@csrf_exempt
def play_campaign_invitation_accept(request, campaign_id, invitation_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    user, auth_error = require_play_auth(request)
    if auth_error:
        return auth_error

    campaign, not_found = require_play_campaign(campaign_id)
    if not_found:
        return not_found

    invitation = db.get_play_campaign_invitation(campaign_id, invitation_id)
    if invitation is None:
        return error_response("invitation not found", 404)

    if invitation["username"] != user["username"]:
        return error_response("forbidden", 403)

    if invitation["status"] != "pending":
        return error_response("invitation already resolved", 409)

    db.accept_play_campaign_invitation(
        campaign_id,
        invitation_id,
        member={
            "username": user["username"],
            "character_id": invitation["character_id"],
            "name": "",
            "class": "",
        },
    )

    return JsonResponse(
        {
            "invitation_id": invitation["invitation_id"],
            "username": invitation["username"],
            "character_id": invitation["character_id"],
            "status": "accepted",
        }
    )
