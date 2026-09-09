"""Live-play world event views."""

import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import (
    require_play_campaign_dm_owner,
    require_play_campaign_member_or_owner,
)
from ..http import bad_request, conflict, not_found, parse_json, require_method
from ..db import db_conn


def _event_record(row):
    """Return the JSON shape for a world event row."""
    record = {
        "event_id": row["event_id"],
        "turn_number": row["turn_number"],
        "title": row["title"],
        "text": row["text"],
        "status": row["status"],
    }
    if row["status"] == "resolved":
        record["resolution"] = {
            "turn_number": row["resolution_turn_number"],
            "text": row["resolution_text"],
        }
    return record


@csrf_exempt
def world_events(request, id):
    """POST schedules a world event; GET lists the campaign's world events."""
    bad = require_method(request, "GET", "POST")
    if bad:
        return bad
    if request.method == "POST":
        return _create_world_event(request, id)
    return _list_world_events(request, id)


def _create_world_event(request, id):
    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")

    try:
        event_id = body["event_id"]
        turn_number = body["turn_number"]
        title = body["title"]
        text = body["text"]
        if not isinstance(event_id, str) or not event_id:
            raise ValueError
        if not isinstance(title, str) or not title:
            raise ValueError
        if not isinstance(text, str) or not text:
            raise ValueError
        if not isinstance(turn_number, int) or isinstance(turn_number, bool):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        if turn_number < campaign["turn_number"]:
            return bad_request("invalid request")

        try:
            conn.execute(
                "INSERT INTO play_world_events (campaign_id, event_id, turn_number, title, text, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (id, event_id, turn_number, title, text, "scheduled"),
            )
        except sqlite3.IntegrityError:
            return conflict("event already exists")

    return JsonResponse(
        {
            "event_id": event_id,
            "turn_number": turn_number,
            "title": title,
            "text": text,
            "status": "scheduled",
        },
        status=201,
    )


@csrf_exempt
def resolve_world_event(request, id, event_id):
    """Resolve a scheduled world event for the current campaign turn."""
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")

    try:
        text = body["text"]
        if not isinstance(text, str) or not text:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, turn_number, title, text, status, resolution_text, resolution_turn_number "
            "FROM play_world_events WHERE campaign_id = ? AND event_id = ?",
            (id, event_id),
        ).fetchone()
        if row is None:
            return not_found("event not found")

        if row["status"] == "resolved":
            return conflict("event already resolved")

        if campaign["turn_number"] != row["turn_number"]:
            return conflict("turn number mismatch")

        conn.execute(
            "UPDATE play_world_events SET status = ?, resolution_text = ?, resolution_turn_number = ? "
            "WHERE campaign_id = ? AND event_id = ?",
            ("resolved", text, campaign["turn_number"], id, event_id),
        )

        record = {
            "event_id": event_id,
            "turn_number": row["turn_number"],
            "title": row["title"],
            "text": row["text"],
            "status": "resolved",
            "resolution": {
                "turn_number": campaign["turn_number"],
                "text": text,
            },
        }

    return JsonResponse(record, status=201)


def _list_world_events(request, id):
    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT event_id, turn_number, title, text, status, resolution_text, resolution_turn_number "
            "FROM play_world_events WHERE campaign_id = ? ORDER BY turn_number ASC, id ASC",
            (id,),
        ).fetchall()

    return JsonResponse({"events": [_event_record(row) for row in rows]})
