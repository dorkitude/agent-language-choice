"""Load-safe campaign event feed views."""

import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_play_campaign_member_or_owner
from ..db import (
    _append_feed_event,
    _get_feed_event_by_event_id,
    _list_feed_events,
    db_conn,
)
from ..http import bad_request, conflict, parse_json, require_method


@csrf_exempt
def create_feed_event(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None or not isinstance(body, dict):
        return bad_request("invalid request")
    try:
        event_id = body["event_id"]
        text = body["text"]
        if not isinstance(event_id, str) or not event_id:
            raise ValueError
        if not isinstance(text, str) or not text:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        existing = _get_feed_event_by_event_id(conn, id, event_id)
        if existing is not None:
            return conflict("event_id already exists")

        try:
            sequence = _append_feed_event(conn, id, event_id, text)
        except sqlite3.IntegrityError:
            return conflict("event_id already exists")

    return JsonResponse(
        {"event_id": event_id, "text": text, "sequence": sequence},
        status=201,
    )


@csrf_exempt
def read_event_feed(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    try:
        cursor = int(request.GET.get("cursor", "0"))
    except (TypeError, ValueError):
        return bad_request("invalid request")
    try:
        limit = int(request.GET.get("limit", "2"))
    except (TypeError, ValueError):
        return bad_request("invalid request")

    if cursor < 0 or limit < 1 or limit > 3:
        return bad_request("invalid request")

    with db_conn() as conn:
        events = _list_feed_events(conn, id, cursor, limit)

    next_cursor = cursor + len(events)
    return JsonResponse({"events": events, "next_cursor": next_cursor})
