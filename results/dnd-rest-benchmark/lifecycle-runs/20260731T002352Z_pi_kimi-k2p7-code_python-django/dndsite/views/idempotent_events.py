"""Campaign-scoped idempotent event views."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_play_campaign_member_or_owner
from ..http import bad_request, conflict, parse_json, require_method
from ..db import db_conn, _append_idempotent_event, _get_idempotent_event_by_event_id, _get_idempotent_event_by_key, _list_idempotent_events


@csrf_exempt
def create_idempotent_event(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    if not idempotency_key:
        return bad_request("invalid request")

    body = parse_json(request)
    if body is None or not isinstance(body, dict):
        return bad_request("invalid request")
    try:
        event_id = body["event_id"]
        value = body["value"]
        if not isinstance(event_id, str) or not event_id:
            raise ValueError
        if not isinstance(value, str) or not value:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        stored_by_key = _get_idempotent_event_by_key(conn, id, idempotency_key)
        if stored_by_key is not None:
            if stored_by_key["event_id"] == event_id and stored_by_key["value"] == value:
                return JsonResponse(
                    {
                        "event_id": stored_by_key["event_id"],
                        "value": stored_by_key["value"],
                        "sequence": stored_by_key["sequence"],
                        "idempotency_key": idempotency_key,
                    }
                )
            return conflict("idempotency key already used")

        existing_event = _get_idempotent_event_by_event_id(conn, id, event_id)
        if existing_event is not None:
            return conflict("event_id already exists")

        sequence = _append_idempotent_event(conn, id, event_id, value, idempotency_key)

    return JsonResponse(
        {
            "event_id": event_id,
            "value": value,
            "sequence": sequence,
            "idempotency_key": idempotency_key,
        },
        status=201,
    )


@csrf_exempt
def list_idempotent_events(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        events = _list_idempotent_events(conn, id)

    return JsonResponse({"events": events})


@csrf_exempt
def idempotent_events(request, id):
    if request.method == "GET":
        return list_idempotent_events(request, id)
    if request.method == "POST":
        return create_idempotent_event(request, id)
    return bad_request("invalid request")
