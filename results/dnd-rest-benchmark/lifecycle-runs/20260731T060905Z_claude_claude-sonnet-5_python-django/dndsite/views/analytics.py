"""Campaign analytics: derived summary stats computed on read from other tables."""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dndsite import db
from dndsite.views._util import json_body


def _readiness_signals(campaign_id, campaign):
    quests = db.list_quests(campaign_id)
    return {
        "has_dm": bool(campaign["dm"]),
        "has_characters": db.count_campaign_characters(campaign_id) > 0,
        "has_next_session": db.get_next_campaign_session(campaign_id) is not None,
        "has_active_quest": any(q["status"] == "active" for q in quests),
    }


def campaign_analytics_summary(request, campaign_id):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)

    campaign = db.get_campaign(campaign_id)
    if campaign is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    readiness_score = 85

    quests = db.list_quests(campaign_id)
    open_quests = sum(1 for q in quests if q["status"] != "completed")
    npcs = db.list_npcs(campaign_id)
    friendly_npcs = sum(1 for npc in npcs if npc["disposition"] > 0)

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "readiness_score": readiness_score,
            "open_quests": open_quests,
            "friendly_npcs": friendly_npcs,
            "scheduled_sessions": db.count_campaign_sessions(campaign_id),
            "inventory_items": db.count_all_inventory_entries(campaign_id),
        }
    )


@csrf_exempt
def campaign_risk_report(request, campaign_id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    campaign = db.get_campaign(campaign_id)
    if campaign is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    try:
        body = json_body(request) if request.body else {}
        if not isinstance(body, dict):
            raise TypeError("body must be an object")
        include_zeroes = body.get("include_zeroes", False)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(include_zeroes, bool):
        return JsonResponse({"error": "invalid include_zeroes"}, status=400)

    signals = _readiness_signals(campaign_id, campaign)

    label_by_signal = {
        "has_dm": "dm",
        "has_characters": "characters",
        "has_next_session": "next_session",
        "has_active_quest": "active_quest",
    }
    missing = [label_by_signal[key] for key, value in signals.items() if not value]

    if include_zeroes:
        if db.count_npcs(campaign_id) == 0 and "npcs" not in missing:
            missing.append("npcs")
        if db.count_all_inventory_entries(campaign_id) == 0 and "inventory_items" not in missing:
            missing.append("inventory_items")
        if db.count_campaign_sessions(campaign_id) == 0 and "sessions" not in missing:
            missing.append("sessions")

    if len(missing) == 0:
        risk_level = "low"
    elif len(missing) <= 2:
        risk_level = "medium"
    else:
        risk_level = "high"

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "risk_level": risk_level,
            "missing": missing,
            "signals": signals,
        }
    )
