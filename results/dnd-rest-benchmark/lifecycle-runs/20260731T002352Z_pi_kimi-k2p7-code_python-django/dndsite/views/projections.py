"""Projection event log and deterministic projection rebuild views."""

import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_play_campaign_member_or_owner
from ..http import bad_request, conflict, forbidden, parse_json, require_method
from ..db import db_conn, _append_projection_event, _rebuild_projection


@csrf_exempt
def append_projection_event(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    # Only player members may append; the DM may read but not append.
    if actor["username"] == campaign["owner"]:
        return forbidden()

    body = parse_json(request)
    if body is None or not isinstance(body, dict):
        return bad_request("invalid request")

    try:
        event_id = body["event_id"]
        kind = body["kind"]
        if not isinstance(event_id, str) or not event_id:
            raise ValueError
        if kind not in ("set-story", "increment-danger"):
            raise ValueError
        if kind == "set-story":
            if "value" not in body:
                raise ValueError
            value = body["value"]
            if not isinstance(value, str) or not value:
                raise ValueError
        else:
            if "value" in body:
                raise ValueError
            value = None
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        try:
            sequence = _append_projection_event(conn, id, event_id, kind, value)
        except sqlite3.IntegrityError:
            return conflict("event_id already exists")

    response = {"sequence": sequence, "event_id": event_id, "kind": kind}
    if value is not None:
        response["value"] = value
    return JsonResponse(response, status=201)


@csrf_exempt
def read_projection(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        projection = _rebuild_projection(conn, id)

    return JsonResponse(projection)


@csrf_exempt
def rebuild_projection_view(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        projection = _rebuild_projection(conn, id)

    return JsonResponse(projection)
