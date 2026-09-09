"""Campaign rate-event views with per-identity allowance."""

from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_play_campaign_member_or_owner
from ..db import db_conn, _record_rate_event_rejection
from ..http import bad_request, parse_json, rate_limited, require_method


RATE_LIMIT = 2


def _actor_event_count(conn, campaign_id, username):
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM play_rate_events "
        "WHERE campaign_id = ? AND actor = ?",
        (campaign_id, username),
    ).fetchone()
    return row["count"]


def _remaining(conn, campaign_id, username):
    return RATE_LIMIT - _actor_event_count(conn, campaign_id, username)


def _list_events(conn, campaign_id):
    rows = conn.execute(
        "SELECT event_id, actor FROM play_rate_events "
        "WHERE campaign_id = ? ORDER BY sequence ASC",
        (campaign_id,),
    ).fetchall()
    return [{"event_id": row["event_id"], "actor": row["actor"]} for row in rows]


def _next_sequence(conn, campaign_id):
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
        "FROM play_rate_events WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    return row["next_sequence"]


@csrf_exempt
def rate_events(request, id):
    if request.method == "POST":
        return create_rate_event(request, id)
    if request.method == "GET":
        return list_rate_events(request, id)
    return HttpResponseBadRequest()


@csrf_exempt
def create_rate_event(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        event_id = body["event_id"]
        if not isinstance(event_id, str) or not event_id:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        remaining = _remaining(conn, id, actor["username"])
        if remaining <= 0:
            _record_rate_event_rejection(conn, id)
            return rate_limited(RATE_LIMIT, 0)

        existing = conn.execute(
            "SELECT 1 FROM play_rate_events WHERE campaign_id = ? AND event_id = ?",
            (id, event_id),
        ).fetchone()
        if existing is not None:
            return bad_request("invalid request")

        sequence = _next_sequence(conn, id)
        conn.execute(
            "INSERT INTO play_rate_events (campaign_id, event_id, actor, sequence) "
            "VALUES (?, ?, ?, ?)",
            (id, event_id, actor["username"], sequence),
        )

    return JsonResponse(
        {
            "event_id": event_id,
            "actor": actor["username"],
            "remaining": remaining - 1,
        },
        status=201,
    )


@csrf_exempt
def list_rate_events(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        events = _list_events(conn, id)
        remaining = _remaining(conn, id, actor["username"])

    return JsonResponse({"events": events, "remaining": remaining})
