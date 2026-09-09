"""Deterministic replay stream views for campaign members."""

import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_play_campaign_member_or_owner
from ..http import bad_request, conflict, parse_json, require_method
from ..db import db_conn, _append_replay_event, _get_replay_state


def _build_replay_state(conn, campaign_id):
    """Return the deterministic replay state for a campaign."""
    return _get_replay_state(conn, campaign_id)


@csrf_exempt
def append_replay_event(request, id):
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
        kind = body["kind"]
        text = body["text"]
        if not isinstance(event_id, str) or not event_id:
            raise ValueError
        if not isinstance(text, str) or not text:
            raise ValueError
        if kind != "append":
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        try:
            sequence = _append_replay_event(conn, id, event_id, kind, text)
        except sqlite3.IntegrityError:
            return conflict("event_id already exists")

    return JsonResponse(
        {
            "event_id": event_id,
            "kind": kind,
            "text": text,
            "sequence": sequence,
        },
        status=201,
    )


@csrf_exempt
def read_replay(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        state = _build_replay_state(conn, id)

    return JsonResponse(state)


@csrf_exempt
def check_replay(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        state = _build_replay_state(conn, id)

    return JsonResponse(state)
