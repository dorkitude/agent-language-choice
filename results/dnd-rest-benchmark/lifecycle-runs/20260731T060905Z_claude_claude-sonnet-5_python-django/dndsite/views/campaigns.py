"""Planning-time campaign record: characters, the event log, and quests.

Unauthenticated by design — any request can read or mutate a campaign by
ID. Distinct from ``play.py``'s real-time play surface.
"""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dndsite import db
from dndsite.views._util import error_response, json_body, require_campaign, require_method


@csrf_exempt
def campaigns_collection(request):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error
    try:
        body = json_body(request)
        campaign_id = body["id"]
        name = body["name"]
        dm = body["dm"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(campaign_id, str) or not campaign_id:
        return error_response("invalid id", 400)
    if not isinstance(name, str) or not name:
        return error_response("invalid name", 400)
    if not isinstance(dm, str) or not dm:
        return error_response("invalid dm", 400)

    if db.get_campaign(campaign_id) is not None:
        return error_response("campaign already exists", 409)

    campaign = {"id": campaign_id, "name": name, "dm": dm}
    db.create_campaign(campaign)

    return JsonResponse(campaign, status=201)


@csrf_exempt
def campaign_characters_collection(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    _campaign, not_found = require_campaign(campaign_id)
    if not_found:
        return not_found

    try:
        body = json_body(request)
        char_id = body["id"]
        name = body["name"]
        level = body["level"]
        char_class = body["class"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(char_id, str) or not char_id:
        return error_response("invalid id", 400)
    if not isinstance(name, str) or not name:
        return error_response("invalid name", 400)
    if not isinstance(level, int) or isinstance(level, bool):
        return error_response("invalid level", 400)
    if not isinstance(char_class, str) or not char_class:
        return error_response("invalid class", 400)

    if db.get_campaign_character(campaign_id, char_id) is not None:
        return error_response("character already exists", 409)

    character = {"id": char_id, "name": name, "level": level, "class": char_class}
    db.create_campaign_character(campaign_id, character)

    return JsonResponse(character, status=201)


@csrf_exempt
def campaign_events_collection(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    _campaign, not_found = require_campaign(campaign_id)
    if not_found:
        return not_found

    try:
        body = json_body(request)
        event_id = body["id"]
        kind = body["kind"]
        summary = body["summary"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(event_id, str) or not event_id:
        return error_response("invalid id", 400)
    if not isinstance(kind, str) or not kind:
        return error_response("invalid kind", 400)
    if not isinstance(summary, str) or not summary:
        return error_response("invalid summary", 400)

    if db.get_campaign_event(campaign_id, event_id) is not None:
        return error_response("event already exists", 409)

    event = {"id": event_id, "kind": kind, "summary": summary}
    db.create_campaign_event(campaign_id, event)

    return JsonResponse({"id": event_id, "kind": kind}, status=201)


VALID_QUEST_STATUSES = ("active", "completed", "blocked")


@csrf_exempt
def campaign_quests_collection(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    _campaign, not_found = require_campaign(campaign_id)
    if not_found:
        return not_found

    try:
        body = json_body(request)
        quest_id = body["id"]
        title = body["title"]
        status = body["status"]
        milestones = body["milestones"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(quest_id, str) or not quest_id:
        return error_response("invalid id", 400)
    if not isinstance(title, str) or not title:
        return error_response("invalid title", 400)
    if status not in VALID_QUEST_STATUSES:
        return error_response("invalid status", 400)
    if not isinstance(milestones, list) or not all(isinstance(m, str) and m for m in milestones):
        return error_response("invalid milestones", 400)

    if db.get_quest(campaign_id, quest_id) is not None:
        return error_response("quest already exists", 409)

    quest = {
        "id": quest_id,
        "title": title,
        "status": status,
        "milestones": milestones,
        "completed": [],
    }
    db.create_quest(campaign_id, quest)

    return JsonResponse(
        {
            "id": quest["id"],
            "title": quest["title"],
            "status": quest["status"],
            "milestones_total": len(milestones),
            "milestones_done": 0,
        },
        status=201,
    )


@csrf_exempt
def campaign_quest_progress(request, campaign_id, quest_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    _campaign, not_found = require_campaign(campaign_id)
    if not_found:
        return not_found

    quest = db.get_quest(campaign_id, quest_id)
    if quest is None:
        return error_response("quest not found", 404)

    try:
        body = json_body(request)
        completed = body["completed"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(completed, list) or not all(isinstance(m, str) for m in completed):
        return error_response("invalid completed", 400)
    if not all(m in quest["milestones"] for m in completed):
        return error_response("unknown milestone", 400)

    done = set(quest["completed"])
    done.update(completed)
    quest["completed"] = [m for m in quest["milestones"] if m in done]

    if quest["status"] != "blocked" and len(quest["completed"]) == len(quest["milestones"]):
        quest["status"] = "completed"

    db.save_quest(campaign_id, quest)

    return JsonResponse(
        {
            "id": quest["id"],
            "status": quest["status"],
            "milestones_total": len(quest["milestones"]),
            "milestones_done": len(quest["completed"]),
        }
    )


def campaign_quests_summary(request, campaign_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    _campaign, not_found = require_campaign(campaign_id)
    if not_found:
        return not_found

    quests = db.list_quests(campaign_id)
    counts = {"active": 0, "completed": 0, "blocked": 0}
    for quest in quests:
        if quest["status"] in counts:
            counts[quest["status"]] += 1

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "active": counts["active"],
            "completed": counts["completed"],
            "blocked": counts["blocked"],
        }
    )


def campaign_state(request, campaign_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    campaign, not_found = require_campaign(campaign_id)
    if not_found:
        return not_found

    characters = db.list_campaign_characters(campaign_id)
    log_count = db.count_campaign_events(campaign_id)

    return JsonResponse(
        {
            "id": campaign["id"],
            "name": campaign["name"],
            "dm": campaign["dm"],
            "characters": characters,
            "log_count": log_count,
        }
    )


@csrf_exempt
def campaign_inventory_collection(request, campaign_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    _campaign, not_found = require_campaign(campaign_id)
    if not_found:
        return not_found

    try:
        body = json_body(request)
        item_slug = body["item_slug"]
        quantity = body["quantity"]
        owner = body["owner"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(item_slug, str) or not item_slug:
        return error_response("invalid item_slug", 400)
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        return error_response("invalid quantity", 400)
    if not isinstance(owner, str) or not owner:
        return error_response("invalid owner", 400)

    db.add_inventory_item(campaign_id, item_slug, owner, quantity)

    return JsonResponse({"item_slug": item_slug, "quantity": quantity, "owner": owner}, status=201)


@csrf_exempt
def campaign_character_equipment_collection(request, campaign_id, character_id):
    method_error = require_method(request, "POST")
    if method_error:
        return method_error

    _campaign, not_found = require_campaign(campaign_id)
    if not_found:
        return not_found

    if db.get_campaign_character(campaign_id, character_id) is None:
        return error_response("character not found", 404)

    try:
        body = json_body(request)
        item_slug = body["item_slug"]
        quantity = body["quantity"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return error_response("invalid request", 400)

    if not isinstance(item_slug, str) or not item_slug:
        return error_response("invalid item_slug", 400)
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        return error_response("invalid quantity", 400)

    db.assign_equipment(campaign_id, character_id, item_slug, quantity)

    return JsonResponse(
        {"character_id": character_id, "item_slug": item_slug, "quantity": quantity}, status=200
    )


def campaign_inventory_summary(request, campaign_id):
    method_error = require_method(request, "GET")
    if method_error:
        return method_error

    _campaign, not_found = require_campaign(campaign_id)
    if not_found:
        return not_found

    party_items = db.count_inventory_entries(campaign_id, "party")
    assigned_items = db.count_equipment_entries(campaign_id)
    party_potions = db.get_inventory_quantity(campaign_id, "healing-potion", "party")
    assigned_potions = db.get_assigned_quantity(campaign_id, "healing-potion")

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "party_items": party_items,
            "assigned_items": assigned_items,
            "healing_potions_available": max(party_potions - assigned_potions, 0),
        }
    )
