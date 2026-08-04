"""Campaign factions, NPCs, and NPC-to-party relationships."""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dndsite import db
from dndsite.views._util import json_body


@csrf_exempt
def campaign_factions_collection(request, campaign_id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    if db.get_campaign(campaign_id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    try:
        body = json_body(request)
        faction_id = body["id"]
        name = body["name"]
        stance = body["stance"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(faction_id, str) or not faction_id:
        return JsonResponse({"error": "invalid id"}, status=400)
    if not isinstance(name, str) or not name:
        return JsonResponse({"error": "invalid name"}, status=400)
    if not isinstance(stance, str) or not stance:
        return JsonResponse({"error": "invalid stance"}, status=400)

    if db.get_faction(campaign_id, faction_id) is not None:
        return JsonResponse({"error": "faction already exists"}, status=409)

    faction = {"id": faction_id, "name": name, "stance": stance}
    db.create_faction(campaign_id, faction)

    return JsonResponse(faction, status=201)


@csrf_exempt
def campaign_npcs_collection(request, campaign_id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    if db.get_campaign(campaign_id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    try:
        body = json_body(request)
        npc_id = body["id"]
        name = body["name"]
        faction_id = body.get("faction_id")
        disposition = body["disposition"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(npc_id, str) or not npc_id:
        return JsonResponse({"error": "invalid id"}, status=400)
    if not isinstance(name, str) or not name:
        return JsonResponse({"error": "invalid name"}, status=400)
    if faction_id is not None and not isinstance(faction_id, str):
        return JsonResponse({"error": "invalid faction_id"}, status=400)
    if not isinstance(disposition, int) or isinstance(disposition, bool):
        return JsonResponse({"error": "invalid disposition"}, status=400)

    if faction_id is not None and db.get_faction(campaign_id, faction_id) is None:
        return JsonResponse({"error": "faction not found"}, status=400)

    if db.get_npc(campaign_id, npc_id) is not None:
        return JsonResponse({"error": "npc already exists"}, status=409)

    npc = {"id": npc_id, "name": name, "faction_id": faction_id, "disposition": disposition}
    db.create_npc(campaign_id, npc)

    return JsonResponse(npc, status=201)


def campaign_relationships(request, campaign_id):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)

    if db.get_campaign(campaign_id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    faction_count = db.count_factions(campaign_id)
    npcs = db.list_npcs(campaign_id)
    friendly_faction_ids = {
        f["id"]
        for f in [db.get_faction(campaign_id, npc["faction_id"]) for npc in npcs if npc["faction_id"]]
        if f is not None and f["stance"] == "friendly"
    }
    friendly_npcs = sum(1 for npc in npcs if npc["faction_id"] in friendly_faction_ids)

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "factions": faction_count,
            "npcs": len(npcs),
            "friendly_npcs": friendly_npcs,
        }
    )
