"""Campaign clue views for live-play campaigns."""

import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import (
    require_play_campaign_dm_owner,
    require_play_campaign_member_or_owner,
)

from ..http import bad_request, conflict, parse_json, require_method

from ..db import db_conn

VALID_AUDIENCES = {"character", "party", "hidden"}


def _character_exists(conn, campaign_id, character_id):
    """Return True if the character_id is a member of the campaign."""
    row = conn.execute(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
        (campaign_id, character_id),
    ).fetchone()
    return row is not None


def _clue_response(clue_id, text, audience, character_id=None):
    """Return the exact clue shape based on audience."""
    if audience == "character":
        return {
            "clue_id": clue_id,
            "text": text,
            "audience": audience,
            "character_id": character_id,
        }
    return {
        "clue_id": clue_id,
        "text": text,
        "audience": audience,
    }


@csrf_exempt
def campaign_clues(request, id):
    """POST creates a clue; GET lists visible clues for the actor."""
    bad = require_method(request, "GET", "POST")
    if bad:
        return bad

    if request.method == "POST":
        return _create_clue(request, id)
    return _list_clues(request, id)


def _create_clue(request, id):
    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")

    try:
        clue_id = body["clue_id"]
        text = body["text"]
        audience = body["audience"]
        if not isinstance(clue_id, str) or not clue_id:
            raise ValueError
        if not isinstance(text, str) or not text:
            raise ValueError
        if audience not in VALID_AUDIENCES:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    character_id = None
    if audience == "character":
        try:
            character_id = body["character_id"]
            if not isinstance(character_id, str) or not character_id:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return bad_request("invalid request")
    else:
        if "character_id" in body:
            return bad_request("invalid request")

    with db_conn() as conn:
        if audience == "character" and not _character_exists(conn, id, character_id):
            return bad_request("invalid request")

        try:
            conn.execute(
                "INSERT INTO play_clues (campaign_id, clue_id, text, audience, character_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (id, clue_id, text, audience, character_id),
            )
        except sqlite3.IntegrityError:
            return conflict("clue already exists")

    return JsonResponse(
        _clue_response(clue_id, text, audience, character_id),
        status=201,
    )


def _list_clues(request, id):
    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        is_dm = actor["username"] == campaign["owner"]
        if is_dm:
            rows = conn.execute(
                "SELECT clue_id, text, audience, character_id FROM play_clues "
                "WHERE campaign_id = ? ORDER BY id",
                (id,),
            ).fetchall()
        else:
            member = conn.execute(
                "SELECT character_id FROM play_campaign_members "
                "WHERE campaign_id = ? AND username = ?",
                (id, actor["username"]),
            ).fetchone()
            own_character_id = member["character_id"] if member else None
            rows = conn.execute(
                "SELECT clue_id, text, audience, character_id FROM play_clues "
                "WHERE campaign_id = ? AND (audience = ? OR (audience = ? AND character_id = ?)) "
                "ORDER BY id",
                (id, "party", "character", own_character_id),
            ).fetchall()

    clues = [
        _clue_response(row["clue_id"], row["text"], row["audience"], row["character_id"])
        for row in rows
    ]

    return JsonResponse({"clues": clues})
