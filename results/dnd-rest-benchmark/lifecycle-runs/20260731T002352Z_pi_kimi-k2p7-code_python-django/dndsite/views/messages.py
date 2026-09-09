"""Campaign chat messages."""

import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_play_campaign_member_or_owner
from ..http import bad_request, conflict, parse_json, require_method
from ..db import db_conn


@csrf_exempt
def messages(request, id):
    if request.method == "POST":
        return create_message(request, id)
    return require_method(request, "POST")


def create_message(request, id):
    """Create a chat message for a campaign member or owner."""
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if not isinstance(body, dict):
        return bad_request("invalid request")
    try:
        text = body.get("text") or body.get("content") or body.get("message") or ""
        if not isinstance(text, str) or not text:
            raise ValueError
        message_id = body.get("message_id") or body.get("id") or ""
        if not isinstance(message_id, str):
            raise ValueError
        kind = body.get("kind")
        if kind is None:
            kind = "chat"
        if not isinstance(kind, str) or not kind:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        if not message_id:
            count = conn.execute(
                "SELECT COUNT(*) AS count FROM play_messages WHERE campaign_id = ?",
                (id,),
            ).fetchone()["count"]
            message_id = f"msg-{count + 1}"
        try:
            conn.execute(
                "INSERT INTO play_messages (campaign_id, message_id, text, author, kind) "
                "VALUES (?, ?, ?, ?, ?)",
                (id, message_id, text, actor["username"], kind),
            )
        except sqlite3.IntegrityError:
            return conflict("message already exists")

    return JsonResponse(
        {
            "message_id": message_id,
            "text": text,
            "author": actor["username"],
            "actor": actor["username"],
            "kind": kind,
        },
        status=201,
    )
