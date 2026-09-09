"""NPC agenda views for live-play campaigns."""

import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import (
    require_play_campaign_dm_owner,
    require_play_campaign_member_or_owner,
)

from ..http import bad_request, conflict, not_found, parse_json, require_method

from ..db import db_conn


_DIALOGUE_COLUMNS = ("dialogue_id", "speaker", "text", "visibility")


@csrf_exempt
def create_play_npc(request, id):
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
        npc_id = body["npc_id"]
        name = body["name"]
        agenda = body["agenda"]
        public_status = body["public_status"]
        if not all(isinstance(v, str) and v for v in (npc_id, name, agenda, public_status)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO play_campaign_npcs (campaign_id, npc_id, name, agenda, public_status) "
                "VALUES (?, ?, ?, ?, ?)",
                (id, npc_id, name, agenda, public_status),
            )
        except sqlite3.IntegrityError:
            return conflict("npc already exists")

    return JsonResponse(
        {
            "npc_id": npc_id,
            "name": name,
            "agenda": agenda,
            "public_status": public_status,
        },
        status=201,
    )


@csrf_exempt
def update_play_npc_agenda(request, id, npc_id):
    bad = require_method(request, "PUT")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        agenda = body["agenda"]
        public_status = body["public_status"]
        if not all(isinstance(v, str) and v for v in (agenda, public_status)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        npc = conn.execute(
            "SELECT name FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
            (id, npc_id),
        ).fetchone()
        if npc is None:
            return not_found("npc not found")

        conn.execute(
            "UPDATE play_campaign_npcs SET agenda = ?, public_status = ? "
            "WHERE campaign_id = ? AND npc_id = ?",
            (agenda, public_status, id, npc_id),
        )

    return JsonResponse(
        {
            "npc_id": npc_id,
            "name": npc["name"],
            "agenda": agenda,
            "public_status": public_status,
        }
    )


@csrf_exempt
def get_play_npc(request, id, npc_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        npc = conn.execute(
            "SELECT name, agenda, public_status FROM play_campaign_npcs "
            "WHERE campaign_id = ? AND npc_id = ?",
            (id, npc_id),
        ).fetchone()
        if npc is None:
            return not_found("npc not found")

    is_dm = actor["username"] == campaign["owner"]
    response = {
        "npc_id": npc_id,
        "name": npc["name"],
        "public_status": npc["public_status"],
    }
    if is_dm:
        response["agenda"] = npc["agenda"]

    return JsonResponse(response)


@csrf_exempt
def npc_dialogue(request, id, npc_id):
    bad = require_method(request, "POST", "GET")
    if bad:
        return bad

    if request.method == "POST":
        return _add_npc_dialogue(request, id, npc_id)
    return _get_npc_dialogue(request, id, npc_id)


def _add_npc_dialogue(request, id, npc_id):
    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        dialogue_id = body["dialogue_id"]
        speaker = body["speaker"]
        text = body["text"]
        visibility = body["visibility"]
        if not all(isinstance(v, str) and v for v in (dialogue_id, speaker, text)):
            raise ValueError
        if visibility not in ("public", "private"):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        npc = conn.execute(
            "SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
            (id, npc_id),
        ).fetchone()
        if npc is None:
            return not_found("npc not found")

        try:
            conn.execute(
                "INSERT INTO play_npc_dialogue "
                "(campaign_id, npc_id, dialogue_id, speaker, text, visibility) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (id, npc_id, dialogue_id, speaker, text, visibility),
            )
        except sqlite3.IntegrityError:
            return conflict("dialogue already exists")

    return JsonResponse(
        {
            "dialogue_id": dialogue_id,
            "speaker": speaker,
            "text": text,
            "visibility": visibility,
        },
        status=201,
    )


def _get_npc_dialogue(request, id, npc_id):
    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        npc = conn.execute(
            "SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
            (id, npc_id),
        ).fetchone()
        if npc is None:
            return not_found("npc not found")

        is_dm = actor["username"] == campaign["owner"]
        if is_dm:
            rows = conn.execute(
                "SELECT dialogue_id, speaker, text, visibility FROM play_npc_dialogue "
                "WHERE campaign_id = ? AND npc_id = ? ORDER BY id",
                (id, npc_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT dialogue_id, speaker, text, visibility FROM play_npc_dialogue "
                "WHERE campaign_id = ? AND npc_id = ? AND visibility = ? ORDER BY id",
                (id, npc_id, "public"),
            ).fetchall()

    entries = [
        {
            "dialogue_id": row["dialogue_id"],
            "speaker": row["speaker"],
            "text": row["text"],
            "visibility": row["visibility"],
        }
        for row in rows
    ]

    return JsonResponse({"npc_id": npc_id, "entries": entries})
