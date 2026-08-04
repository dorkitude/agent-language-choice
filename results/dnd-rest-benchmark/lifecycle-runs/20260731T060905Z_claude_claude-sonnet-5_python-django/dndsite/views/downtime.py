"""Downtime crafting projects, keyed off a campaign_id."""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dndsite import db
from dndsite.views._util import json_body


@csrf_exempt
def campaign_crafting_collection(request, campaign_id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    if db.get_campaign(campaign_id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    try:
        body = json_body(request)
        project_id = body["id"]
        character_id = body["character_id"]
        item_slug = body["item_slug"]
        days_required = body["days_required"]
        cost_gp = body["cost_gp"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(project_id, str) or not project_id:
        return JsonResponse({"error": "invalid id"}, status=400)
    if not isinstance(character_id, str) or not character_id:
        return JsonResponse({"error": "invalid character_id"}, status=400)
    if not isinstance(item_slug, str) or not item_slug:
        return JsonResponse({"error": "invalid item_slug"}, status=400)
    if not isinstance(days_required, int) or isinstance(days_required, bool) or days_required <= 0:
        return JsonResponse({"error": "invalid days_required"}, status=400)
    if not isinstance(cost_gp, int) or isinstance(cost_gp, bool) or cost_gp < 0:
        return JsonResponse({"error": "invalid cost_gp"}, status=400)

    if db.get_campaign_character(campaign_id, character_id) is None:
        return JsonResponse({"error": "character not found"}, status=404)

    if db.get_crafting_project(campaign_id, project_id) is not None:
        return JsonResponse({"error": "crafting project already exists"}, status=409)

    project = {
        "id": project_id,
        "character_id": character_id,
        "item_slug": item_slug,
        "days_required": days_required,
        "days_completed": 0,
        "cost_gp": cost_gp,
        "status": "active",
    }
    db.create_crafting_project(campaign_id, project)

    return JsonResponse(
        {
            "id": project["id"],
            "character_id": project["character_id"],
            "item_slug": project["item_slug"],
            "days_required": project["days_required"],
            "days_completed": project["days_completed"],
            "status": project["status"],
        },
        status=201,
    )


@csrf_exempt
def campaign_crafting_advance(request, campaign_id, project_id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    if db.get_campaign(campaign_id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    project = db.get_crafting_project(campaign_id, project_id)
    if project is None:
        return JsonResponse({"error": "crafting project not found"}, status=404)

    try:
        body = json_body(request)
        days = body["days"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
        return JsonResponse({"error": "invalid days"}, status=400)

    if project["status"] != "active":
        return JsonResponse({"error": "crafting project not active"}, status=409)

    project["days_completed"] = min(project["days_completed"] + days, project["days_required"])
    if project["days_completed"] >= project["days_required"]:
        project["status"] = "complete"

    db.save_crafting_project(campaign_id, project)

    if project["status"] == "complete":
        db.add_inventory_item(campaign_id, project["item_slug"], "party", 1)

    return JsonResponse(
        {
            "id": project["id"],
            "days_completed": project["days_completed"],
            "status": project["status"],
        }
    )
