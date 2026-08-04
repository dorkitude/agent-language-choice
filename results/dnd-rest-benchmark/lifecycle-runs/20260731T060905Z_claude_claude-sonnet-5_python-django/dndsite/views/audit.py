"""Campaign audit log and full-state export."""

from django.http import JsonResponse

from dndsite import db


def campaign_audit(request, campaign_id):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)

    if db.get_campaign(campaign_id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "events": db.count_campaign_events(campaign_id),
            "quests": db.count_quests(campaign_id),
            "npcs": db.count_npcs(campaign_id),
            "sessions": db.count_campaign_sessions(campaign_id),
        }
    )


def campaign_export(request, campaign_id):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)

    campaign = db.get_campaign(campaign_id)
    if campaign is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    return JsonResponse(
        {
            "campaign_id": campaign["id"],
            "name": campaign["name"],
            "characters": db.count_campaign_characters(campaign_id),
            "quests": db.count_quests(campaign_id),
            "npcs": db.count_npcs(campaign_id),
            "inventory_items": db.count_all_inventory_entries(campaign_id),
            "sessions": db.count_campaign_sessions(campaign_id),
            "schema_version": db.SCHEMA_VERSION,
        }
    )
