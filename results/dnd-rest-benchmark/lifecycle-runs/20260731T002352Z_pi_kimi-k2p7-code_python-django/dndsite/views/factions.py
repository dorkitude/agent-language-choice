"""Faction reputation views for live-play campaigns."""

import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import (
    require_play_campaign_dm_owner,
    require_play_campaign_member_or_owner,
)

from ..http import bad_request, conflict, not_found, parse_json, require_method

from ..db import db_conn


@csrf_exempt
def create_play_faction(request, id):
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
        faction_id = body["faction_id"]
        name = body["name"]
        if not all(isinstance(v, str) and v for v in (faction_id, name)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO play_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)",
                (id, faction_id, name),
            )
        except sqlite3.IntegrityError:
            return conflict("faction already exists")

    return JsonResponse(
        {"faction_id": faction_id, "name": name},
        status=201,
    )


def _change_reputation(request, id, faction_id):
    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        character_id = body["character_id"]
        delta = body["delta"]
        reason = body["reason"]
        if not isinstance(character_id, str) or not character_id:
            raise ValueError
        if not isinstance(delta, int) or delta == 0 or delta < -25 or delta > 25:
            raise ValueError
        if not isinstance(reason, str) or not reason:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        faction = conn.execute(
            "SELECT 1 FROM play_factions WHERE campaign_id = ? AND faction_id = ?",
            (id, faction_id),
        ).fetchone()
        if faction is None:
            return not_found("faction not found")

        member = conn.execute(
            "SELECT character_id FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, character_id),
        ).fetchone()
        if member is None:
            return bad_request("invalid character")

        row = conn.execute(
            "SELECT reputation FROM play_reputation_history "
            "WHERE campaign_id = ? AND faction_id = ? AND character_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (id, faction_id, character_id),
        ).fetchone()
        current = row["reputation"] if row else 0
        new_reputation = max(-100, min(100, current + delta))

        conn.execute(
            "INSERT INTO play_reputation_history "
            "(campaign_id, faction_id, character_id, delta, reason, reputation) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (id, faction_id, character_id, delta, reason, new_reputation),
        )

    return JsonResponse(
        {
            "faction_id": faction_id,
            "character_id": character_id,
            "reputation": new_reputation,
            "delta": delta,
            "reason": reason,
        },
        status=201,
    )


def _get_reputation(request, id, faction_id):
    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        faction = conn.execute(
            "SELECT name FROM play_factions WHERE campaign_id = ? AND faction_id = ?",
            (id, faction_id),
        ).fetchone()
        if faction is None:
            return not_found("faction not found")

        is_dm = actor["username"] == campaign["owner"]
        if is_dm:
            rows = conn.execute(
                "SELECT character_id, delta, reason, reputation FROM play_reputation_history "
                "WHERE campaign_id = ? AND faction_id = ? ORDER BY id",
                (id, faction_id),
            ).fetchall()
        else:
            member = conn.execute(
                "SELECT character_id FROM play_campaign_members "
                "WHERE campaign_id = ? AND username = ?",
                (id, actor["username"]),
            ).fetchone()
            own_character_id = member["character_id"] if member else None
            rows = conn.execute(
                "SELECT character_id, delta, reason, reputation FROM play_reputation_history "
                "WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY id",
                (id, faction_id, own_character_id),
            ).fetchall()

    entries = [
        {
            "faction_id": faction_id,
            "character_id": row["character_id"],
            "reputation": row["reputation"],
            "delta": row["delta"],
            "reason": row["reason"],
        }
        for row in rows
    ]

    return JsonResponse(
        {
            "faction_id": faction_id,
            "entries": entries,
        }
    )


@csrf_exempt
def faction_reputation(request, id, faction_id):
    bad = require_method(request, "POST", "GET")
    if bad:
        return bad

    if request.method == "POST":
        return _change_reputation(request, id, faction_id)
    return _get_reputation(request, id, faction_id)
