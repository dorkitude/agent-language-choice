"""Campaign invitations for live-play campaigns."""

import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import _get_actor, require_play_campaign_dm_owner
from ..http import bad_request, conflict, forbidden, not_found, parse_json, require_method, unauthorized
from ..db import db_conn


@csrf_exempt
def invitations(request, id):
    if request.method == "POST":
        return create_invitation(request, id)
    if request.method == "GET":
        return list_invitations(request, id)
    return require_method(request, "GET", "POST")


@csrf_exempt
def create_invitation(request, id):
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
        invitation_id = body["invitation_id"]
        username = body["username"]
        character_id = body["character_id"]
        if not all(isinstance(v, str) and v for v in (invitation_id, username, character_id)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        user = conn.execute(
            "SELECT role FROM users WHERE username = ?", (username,)
        ).fetchone()
        if user is None or user["role"] != "player":
            return bad_request("invalid request")

        existing = conn.execute(
            "SELECT status FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?",
            (id, invitation_id),
        ).fetchone()
        if existing is not None:
            return conflict("invitation already exists")

        pending = conn.execute(
            "SELECT 1 FROM play_campaign_invitations WHERE campaign_id = ? AND username = ? AND status = ?",
            (id, username, "pending"),
        ).fetchone()
        if pending is not None:
            return conflict("invitation already exists")

        conn.execute(
            "INSERT INTO play_campaign_invitations (campaign_id, invitation_id, username, character_id, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (id, invitation_id, username, character_id, "pending"),
        )

    return JsonResponse(
        {
            "invitation_id": invitation_id,
            "username": username,
            "character_id": character_id,
            "status": "pending",
        },
        status=201,
    )


@csrf_exempt
def accept_invitation(request, id, invitation_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        invitation = conn.execute(
            "SELECT id, username, character_id, status FROM play_campaign_invitations "
            "WHERE campaign_id = ? AND invitation_id = ?",
            (id, invitation_id),
        ).fetchone()
        if invitation is None:
            return not_found("invitation not found")

        if actor["username"] != invitation["username"]:
            return forbidden()

        if invitation["status"] == "accepted":
            return conflict("invitation already accepted")

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM play_campaign_members WHERE campaign_id = ?",
            (id,),
        ).fetchone()["next_sequence"]

        try:
            conn.execute(
                "INSERT INTO play_campaign_members (campaign_id, username, owner, character_id, name, class_name, sequence, hp_current, hp_max, status, death_save_successes, death_save_failures, gold) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (id, invitation["username"], invitation["username"], invitation["character_id"], invitation["character_id"], "adventurer", next_sequence, 20, 20, "conscious", 0, 0, 10),
            )
        except sqlite3.IntegrityError:
            return conflict("already a member")

        conn.execute(
            "UPDATE play_campaign_invitations SET status = ? WHERE id = ?",
            ("accepted", invitation["id"]),
        )

    return JsonResponse(
        {
            "invitation_id": invitation_id,
            "username": invitation["username"],
            "character_id": invitation["character_id"],
            "status": "accepted",
        },
    )


@csrf_exempt
def list_invitations(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] == campaign["owner"]:
            rows = conn.execute(
                "SELECT invitation_id, username, character_id, status FROM play_campaign_invitations "
                "WHERE campaign_id = ? ORDER BY id",
                (id,),
            ).fetchall()
        else:
            own_rows = conn.execute(
                "SELECT invitation_id, username, character_id, status FROM play_campaign_invitations "
                "WHERE campaign_id = ? AND username = ? ORDER BY id",
                (id, actor["username"]),
            ).fetchall()
            if own_rows:
                rows = own_rows
            else:
                is_member = (
                    conn.execute(
                        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                        (id, actor["username"]),
                    ).fetchone()
                    is not None
                )
                if is_member:
                    rows = []
                else:
                    return forbidden()

    invitations = [
        {
            "invitation_id": row["invitation_id"],
            "username": row["username"],
            "character_id": row["character_id"],
            "status": row["status"],
        }
        for row in rows
    ]

    return JsonResponse({"invitations": invitations})
