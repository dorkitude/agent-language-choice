"""Campaign-scoped safe turn submission views."""

import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_play_campaign_member_or_owner
from ..http import bad_request, conflict, parse_json, require_method
from ..db import db_conn


@csrf_exempt
def safe_turns(request, id):
    """Dispatch GET/POST for /v1/play/campaigns/{id}/safe-turns."""
    bad = require_method(request, "GET", "POST")
    if bad:
        return bad
    if request.method == "POST":
        return submit_safe_turn(request, id)
    return get_safe_turns(request, id)


@csrf_exempt
def submit_safe_turn(request, id):
    """Accept or reject a deterministic safe-turn submission."""
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        submission_id = body["submission_id"]
        expected_turn = body["expected_turn"]
        action = body["action"]
        if not isinstance(submission_id, str) or not submission_id:
            raise ValueError
        if not isinstance(action, str) or not action:
            raise ValueError
        if not isinstance(expected_turn, int) or isinstance(expected_turn, bool) or expected_turn < 1:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        current_turn = campaign["safe_turn_current_turn"]

        existing = conn.execute(
            "SELECT 1 FROM safe_turn_submissions WHERE campaign_id = ? AND submission_id = ?",
            (id, submission_id),
        ).fetchone()
        if existing is not None:
            return conflict("duplicate submission_id")

        if expected_turn != current_turn:
            conn.execute(
                "INSERT INTO safe_turn_submissions (campaign_id, submission_id, action, accepted_turn, next_turn, accepted) "
                "VALUES (?, ?, ?, NULL, NULL, 0)",
                (id, submission_id, action),
            )
            return JsonResponse({"current_turn": current_turn}, status=409)

        next_turn = current_turn + 1
        conn.execute(
            "INSERT INTO safe_turn_submissions (campaign_id, submission_id, action, accepted_turn, next_turn, accepted) "
            "VALUES (?, ?, ?, ?, ?, 1)",
            (id, submission_id, action, current_turn, next_turn),
        )
        conn.execute(
            "UPDATE play_campaigns SET safe_turn_current_turn = ? WHERE id = ?",
            (next_turn, id),
        )

    return JsonResponse(
        {
            "submission_id": submission_id,
            "action": action,
            "accepted_turn": current_turn,
            "next_turn": next_turn,
        },
        status=201,
    )


@csrf_exempt
def get_safe_turns(request, id):
    """Return the ordered accepted safe-turn history and current turn."""
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT submission_id, action, accepted_turn, next_turn FROM safe_turn_submissions "
            "WHERE campaign_id = ? AND accepted = 1 ORDER BY id ASC",
            (id,),
        ).fetchall()

    accepted = [
        {
            "submission_id": row["submission_id"],
            "action": row["action"],
            "accepted_turn": row["accepted_turn"],
            "next_turn": row["next_turn"],
        }
        for row in rows
    ]

    return JsonResponse(
        {
            "current_turn": campaign["safe_turn_current_turn"],
            "accepted": accepted,
        }
    )
