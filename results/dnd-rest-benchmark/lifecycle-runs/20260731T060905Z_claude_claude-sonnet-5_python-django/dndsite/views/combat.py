"""Stateful combat sessions: create, apply conditions, advance turn/round."""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dndsite import db
from dndsite.rules import numeric
from dndsite.views._util import json_body


def _session_view(session):
    order = session["order"]
    active = order[session["turn_index"]]
    return {
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": {"name": active["name"], "score": numeric(active["score"])},
        "order": [{"name": c["name"], "score": numeric(c["score"])} for c in order],
    }


@csrf_exempt
def combat_sessions(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        session_id = body["id"]
        combatants = body["combatants"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(session_id, str) or not session_id:
        return JsonResponse({"error": "invalid request"}, status=400)
    if db.get_session(session_id) is not None:
        return JsonResponse({"error": "session already exists"}, status=400)
    if not isinstance(combatants, list) or not combatants:
        return JsonResponse({"error": "invalid request"}, status=400)

    try:
        scored = []
        for combatant in combatants:
            name = combatant["name"]
            dex = combatant["dex"]
            roll = combatant["roll"]
            if not isinstance(name, str) or not isinstance(dex, (int, float)) or isinstance(dex, bool) \
                    or not isinstance(roll, (int, float)) or isinstance(roll, bool):
                return JsonResponse({"error": "invalid request"}, status=400)
            score = roll + dex
            scored.append({"name": name, "dex": dex, "score": score, "conditions": []})
    except (KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))

    session = {
        "id": session_id,
        "round": 1,
        "turn_index": 0,
        "order": scored,
    }
    db.create_session(session)

    return JsonResponse(_session_view(session))


@csrf_exempt
def combat_conditions(request, session_id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    session = db.get_session(session_id)
    if session is None:
        return JsonResponse({"error": "session not found"}, status=404)

    try:
        body = json_body(request)
        target = body["target"]
        condition = body["condition"]
        duration_rounds = body["duration_rounds"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(target, str) or not isinstance(condition, str):
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(duration_rounds, int) or isinstance(duration_rounds, bool) or duration_rounds <= 0:
        return JsonResponse({"error": "invalid request"}, status=400)

    combatant = next((c for c in session["order"] if c["name"] == target), None)
    if combatant is None:
        return JsonResponse({"error": "unknown target"}, status=400)

    combatant["conditions"].append({"condition": condition, "remaining_rounds": duration_rounds})
    db.save_session(session)

    return JsonResponse(
        {
            "target": target,
            "conditions": [
                {"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]}
                for c in combatant["conditions"]
            ],
        }
    )


@csrf_exempt
def combat_advance(request, session_id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    session = db.get_session(session_id)
    if session is None:
        return JsonResponse({"error": "session not found"}, status=404)

    order = session["order"]
    session["turn_index"] += 1
    if session["turn_index"] >= len(order):
        session["turn_index"] = 0
        session["round"] += 1

    active = order[session["turn_index"]]
    remaining = []
    for cond in active["conditions"]:
        cond["remaining_rounds"] -= 1
        if cond["remaining_rounds"] > 0:
            remaining.append(cond)
    active["conditions"] = remaining
    db.save_session(session)

    conditions = {
        c["name"]: [
            {"condition": cond["condition"], "remaining_rounds": cond["remaining_rounds"]}
            for cond in c["conditions"]
        ]
        for c in order
        if c["conditions"] or c is active
    }

    return JsonResponse(
        {
            "id": session["id"],
            "round": session["round"],
            "turn_index": session["turn_index"],
            "active": {"name": active["name"], "score": numeric(active["score"])},
            "conditions": conditions,
        },
    )
