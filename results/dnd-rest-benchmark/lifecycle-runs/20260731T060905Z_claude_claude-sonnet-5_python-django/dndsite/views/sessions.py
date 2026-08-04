"""Campaign session scheduling and attendance."""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dndsite import db
from dndsite.views._util import json_body


@csrf_exempt
def campaign_sessions_collection(request, campaign_id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    if db.get_campaign(campaign_id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    try:
        body = json_body(request)
        session_id = body["id"]
        starts_at = body["starts_at"]
        duration_minutes = body["duration_minutes"]
        agenda = body["agenda"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(session_id, str) or not session_id:
        return JsonResponse({"error": "invalid id"}, status=400)
    if not isinstance(starts_at, str) or not starts_at:
        return JsonResponse({"error": "invalid starts_at"}, status=400)
    if (
        not isinstance(duration_minutes, int)
        or isinstance(duration_minutes, bool)
        or duration_minutes <= 0
    ):
        return JsonResponse({"error": "invalid duration_minutes"}, status=400)
    if not isinstance(agenda, list) or not all(isinstance(a, str) and a for a in agenda):
        return JsonResponse({"error": "invalid agenda"}, status=400)

    if db.get_campaign_session(campaign_id, session_id) is not None:
        return JsonResponse({"error": "session already exists"}, status=409)

    session = {
        "id": session_id,
        "starts_at": starts_at,
        "duration_minutes": duration_minutes,
        "agenda": agenda,
    }
    db.create_campaign_session(campaign_id, session)

    return JsonResponse(
        {
            "id": session["id"],
            "starts_at": session["starts_at"],
            "duration_minutes": session["duration_minutes"],
            "agenda_count": len(agenda),
        },
        status=201,
    )


@csrf_exempt
def campaign_session_attendance(request, campaign_id, session_id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    if db.get_campaign(campaign_id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    if db.get_campaign_session(campaign_id, session_id) is None:
        return JsonResponse({"error": "session not found"}, status=404)

    try:
        body = json_body(request)
        present = body["present"]
        absent = body["absent"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(present, list) or not all(isinstance(c, str) and c for c in present):
        return JsonResponse({"error": "invalid present"}, status=400)
    if not isinstance(absent, list) or not all(isinstance(c, str) and c for c in absent):
        return JsonResponse({"error": "invalid absent"}, status=400)

    db.save_session_attendance(campaign_id, session_id, present, absent)

    return JsonResponse(
        {
            "session_id": session_id,
            "present_count": len(present),
            "absent_count": len(absent),
        }
    )


def campaign_next_session(request, campaign_id):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)

    if db.get_campaign(campaign_id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    session = db.get_next_campaign_session(campaign_id)
    if session is None:
        return JsonResponse({"error": "no upcoming session"}, status=404)

    return JsonResponse(
        {
            "id": session["id"],
            "starts_at": session["starts_at"],
            "agenda_count": len(session["agenda"]),
        }
    )
