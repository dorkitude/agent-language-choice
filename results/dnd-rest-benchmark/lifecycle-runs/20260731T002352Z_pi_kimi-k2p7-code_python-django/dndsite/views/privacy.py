"""Privacy controls for live-play campaigns: notes, whispers, and sheets."""

import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_play_campaign_member_or_owner
from ..http import bad_request, conflict, forbidden, not_found, parse_json, require_method
from ..db import db_conn


VALID_VISIBILITIES = {"private", "party"}


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


@csrf_exempt
def notes(request, id):
    if request.method == "POST":
        return create_note(request, id)
    if request.method == "GET":
        return list_notes(request, id)
    return require_method(request, "GET", "POST")


@csrf_exempt
def create_note(request, id):
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
        note_id = body["note_id"]
        text = body["text"]
        visibility = body["visibility"]
        if not isinstance(note_id, str) or not note_id:
            raise ValueError
        if not isinstance(text, str) or not text:
            raise ValueError
        if visibility not in VALID_VISIBILITIES:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        is_owner = actor["username"] == campaign["owner"]
        if not is_owner:
            is_member = (
                conn.execute(
                    "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                    (id, actor["username"]),
                ).fetchone()
                is not None
            )
            if not is_member:
                return forbidden()

        try:
            conn.execute(
                "INSERT INTO play_notes (campaign_id, note_id, text, visibility, owner) "
                "VALUES (?, ?, ?, ?, ?)",
                (id, note_id, text, visibility, actor["username"]),
            )
        except sqlite3.IntegrityError:
            return conflict("note already exists")

    return JsonResponse(
        {
            "note_id": note_id,
            "text": text,
            "visibility": visibility,
            "owner": actor["username"],
        },
        status=201,
    )


@csrf_exempt
def list_notes(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT note_id, text, visibility, owner FROM play_notes "
            "WHERE campaign_id = ? ORDER BY id",
            (id,),
        ).fetchall()

    is_owner = actor["username"] == campaign["owner"]
    notes = []
    for row in rows:
        if is_owner or row["visibility"] == "party" or row["owner"] == actor["username"]:
            notes.append(
                {
                    "note_id": row["note_id"],
                    "text": row["text"],
                    "visibility": row["visibility"],
                    "owner": row["owner"],
                }
            )

    return JsonResponse({"notes": notes})


@csrf_exempt
def note_detail(request, id, note_id):
    if request.method == "GET":
        return get_note(request, id, note_id)
    if request.method == "PUT":
        return update_note(request, id, note_id)
    return require_method(request, "GET", "PUT")


@csrf_exempt
def get_note(request, id, note_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        row = conn.execute(
            "SELECT note_id, text, visibility, owner FROM play_notes "
            "WHERE campaign_id = ? AND note_id = ?",
            (id, note_id),
        ).fetchone()

    if row is None:
        return not_found("note not found")

    is_owner = actor["username"] == campaign["owner"]
    if not is_owner and row["visibility"] == "private" and row["owner"] != actor["username"]:
        return forbidden()

    return JsonResponse(
        {
            "note_id": row["note_id"],
            "text": row["text"],
            "visibility": row["visibility"],
            "owner": row["owner"],
        }
    )


@csrf_exempt
def update_note(request, id, note_id):
    bad = require_method(request, "PUT")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        text = body["text"]
        visibility = body["visibility"]
        if not isinstance(text, str) or not text:
            raise ValueError
        if visibility not in VALID_VISIBILITIES:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        row = conn.execute(
            "SELECT note_id, text, visibility, owner FROM play_notes "
            "WHERE campaign_id = ? AND note_id = ?",
            (id, note_id),
        ).fetchone()
        if row is None:
            return not_found("note not found")

        if row["owner"] != actor["username"]:
            return forbidden()

        conn.execute(
            "UPDATE play_notes SET text = ?, visibility = ? WHERE campaign_id = ? AND note_id = ?",
            (text, visibility, id, note_id),
        )

    return JsonResponse(
        {
            "note_id": note_id,
            "text": text,
            "visibility": visibility,
            "owner": row["owner"],
        }
    )


# ---------------------------------------------------------------------------
# Whispers
# ---------------------------------------------------------------------------


def _owned_character(conn, campaign_id, username):
    """Return the character_id owned by ``username`` in the campaign, if any."""
    row = conn.execute(
        "SELECT character_id FROM play_campaign_members "
        "WHERE campaign_id = ? AND owner = ?",
        (campaign_id, username),
    ).fetchone()
    return None if row is None else row["character_id"]


@csrf_exempt
def whispers(request, id):
    if request.method == "POST":
        return create_whisper(request, id)
    if request.method == "GET":
        return list_whispers(request, id)
    return require_method(request, "GET", "POST")


@csrf_exempt
def create_whisper(request, id):
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
        whisper_id = body["whisper_id"]
        to_character_id = body["to_character_id"]
        text = body["text"]
        if not all(isinstance(v, str) and v for v in (whisper_id, to_character_id, text)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        from_character_id = _owned_character(conn, id, actor["username"])
        if from_character_id is None:
            return forbidden()

        target_member = conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (id, to_character_id),
        ).fetchone()
        if target_member is None:
            return bad_request("invalid request")

        try:
            conn.execute(
                "INSERT INTO play_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text) "
                "VALUES (?, ?, ?, ?, ?)",
                (id, whisper_id, from_character_id, to_character_id, text),
            )
        except sqlite3.IntegrityError:
            return conflict("whisper already exists")

    return JsonResponse(
        {
            "whisper_id": whisper_id,
            "from_character_id": from_character_id,
            "to_character_id": to_character_id,
            "text": text,
        },
        status=201,
    )


@csrf_exempt
def list_whispers(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT whisper_id, from_character_id, to_character_id, text FROM play_whispers "
            "WHERE campaign_id = ? ORDER BY id",
            (id,),
        ).fetchall()
        owned_character = _owned_character(conn, id, actor["username"])

    is_owner = actor["username"] == campaign["owner"]
    if is_owner:
        whispers = [
            {
                "whisper_id": row["whisper_id"],
                "from_character_id": row["from_character_id"],
                "to_character_id": row["to_character_id"],
                "text": row["text"],
            }
            for row in rows
        ]
        return JsonResponse({"whispers": whispers})

    if owned_character is None:
        return JsonResponse({"whispers": []})

    whispers = []
    for row in rows:
        if row["from_character_id"] == owned_character or row["to_character_id"] == owned_character:
            whispers.append(
                {
                    "whisper_id": row["whisper_id"],
                    "from_character_id": row["from_character_id"],
                    "to_character_id": row["to_character_id"],
                    "text": row["text"],
                }
            )

    return JsonResponse({"whispers": whispers})


# ---------------------------------------------------------------------------
# Character sheets
# ---------------------------------------------------------------------------


@csrf_exempt
def character_sheet(request, id, character_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        member = conn.execute(
            "SELECT character_id, owner, name, class_name, level "
            "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (id, character_id),
        ).fetchone()

    if member is None:
        return not_found("character not found")

    is_owner = actor["username"] == campaign["owner"]
    if not is_owner and member["owner"] != actor["username"]:
        return forbidden()

    return JsonResponse(
        {
            "character_id": member["character_id"],
            "owner": member["owner"],
            "name": member["name"],
            "class": member["class_name"],
            "level": 1,
            "proficiency_bonus": 2,
            "hp_max": 10,
            "armor_class": 10,
        }
    )
