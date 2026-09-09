"""Loot distribution views for live-play campaigns."""

import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import (
    require_actor,
    require_play_campaign_dm_owner,
    require_play_campaign_member_or_owner,
)
from .inventory import VALID_ITEM_IDS

from ..http import bad_request, conflict, forbidden, not_found, parse_json, require_method

from ..db import _add_play_inventory_item, db_conn


@csrf_exempt
def create_loot(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "dm")
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        loot_id = body["loot_id"]
        item_id = body["item_id"]
        quantity = body["quantity"]
        if not all(isinstance(v, str) for v in (loot_id, item_id)):
            raise ValueError
        if not isinstance(quantity, int) or isinstance(quantity, bool):
            raise ValueError
        if quantity <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if item_id not in VALID_ITEM_IDS:
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")
        if actor["username"] != campaign["owner"]:
            return forbidden()

        try:
            conn.execute(
                "INSERT INTO play_loot (campaign_id, loot_id, item_id, quantity, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (id, loot_id, item_id, quantity, "open"),
            )
        except sqlite3.IntegrityError:
            return conflict("loot already exists")

    return JsonResponse(
        {
            "loot_id": loot_id,
            "item_id": item_id,
            "quantity": quantity,
            "status": "open",
        },
        status=201,
    )


@csrf_exempt
def vote_loot(request, id, loot_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "player", "only players may vote")
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        recipient_character_id = body["recipient_character_id"]
        if not isinstance(recipient_character_id, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        voter_member = conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (id, actor["username"]),
        ).fetchone()
        if voter_member is None:
            return forbidden()

        recipient = conn.execute(
            "SELECT character_id FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, recipient_character_id),
        ).fetchone()
        if recipient is None:
            return bad_request("invalid request")

        loot = conn.execute(
            "SELECT status FROM play_loot WHERE campaign_id = ? AND loot_id = ?",
            (id, loot_id),
        ).fetchone()
        if loot is None:
            return not_found("loot not found")
        if loot["status"] != "open":
            return conflict("loot not open")

        try:
            conn.execute(
                "INSERT INTO play_loot_votes (campaign_id, loot_id, voter, recipient_character_id) "
                "VALUES (?, ?, ?, ?)",
                (id, loot_id, actor["username"], recipient_character_id),
            )
        except sqlite3.IntegrityError:
            return conflict("vote already cast")

        votes_for_recipient = conn.execute(
            "SELECT COUNT(*) AS count FROM play_loot_votes "
            "WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?",
            (id, loot_id, recipient_character_id),
        ).fetchone()["count"]

    return JsonResponse(
        {
            "loot_id": loot_id,
            "voter": actor["username"],
            "recipient_character_id": recipient_character_id,
            "votes_for_recipient": votes_for_recipient,
        },
        status=201,
    )


@csrf_exempt
def assign_loot(request, id, loot_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        loot = conn.execute(
            "SELECT item_id, quantity, status FROM play_loot WHERE campaign_id = ? AND loot_id = ?",
            (id, loot_id),
        ).fetchone()
        if loot is None:
            return not_found("loot not found")
        if loot["status"] != "open":
            return conflict("loot already assigned")

        rows = conn.execute(
            "SELECT recipient_character_id, COUNT(*) AS votes "
            "FROM play_loot_votes WHERE campaign_id = ? AND loot_id = ? "
            "GROUP BY recipient_character_id ORDER BY votes DESC",
            (id, loot_id),
        ).fetchall()

        if not rows:
            return conflict("no votes")

        max_votes = rows[0]["votes"]
        winners = [row["recipient_character_id"] for row in rows if row["votes"] == max_votes]
        if len(winners) > 1:
            return conflict("tie")

        winner_character_id = winners[0]

        _add_play_inventory_item(conn, id, winner_character_id, loot["item_id"], loot["quantity"])

        conn.execute(
            "UPDATE play_loot SET status = ?, recipient_character_id = ? "
            "WHERE campaign_id = ? AND loot_id = ?",
            ("assigned", winner_character_id, id, loot_id),
        )

    return JsonResponse(
        {
            "loot_id": loot_id,
            "recipient_character_id": winner_character_id,
            "item_id": loot["item_id"],
            "quantity": loot["quantity"],
            "votes": max_votes,
            "status": "assigned",
        },
        status=200,
    )


@csrf_exempt
def get_loot(request, id, loot_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        loot = conn.execute(
            "SELECT item_id, quantity, status, recipient_character_id FROM play_loot "
            "WHERE campaign_id = ? AND loot_id = ?",
            (id, loot_id),
        ).fetchone()
        if loot is None:
            return not_found("loot not found")

        rows = conn.execute(
            "SELECT recipient_character_id, COUNT(*) AS count FROM play_loot_votes "
            "WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id "
            "ORDER BY recipient_character_id",
            (id, loot_id),
        ).fetchall()
        votes = {row["recipient_character_id"]: row["count"] for row in rows}

    return JsonResponse(
        {
            "loot_id": loot_id,
            "item_id": loot["item_id"],
            "quantity": loot["quantity"],
            "status": loot["status"],
            "recipient_character_id": loot["recipient_character_id"],
            "votes": votes,
        }
    )
