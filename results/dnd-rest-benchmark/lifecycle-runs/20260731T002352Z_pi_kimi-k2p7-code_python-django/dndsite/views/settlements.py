"""Settlement views for play campaigns."""

import json
import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import (
    require_actor,
    require_play_campaign_member_or_owner,
)
from ..http import bad_request, conflict, forbidden, not_found, parse_json, require_method
from ..db import db_conn


VALID_AVAILABILITY = {"open", "limited", "closed"}


def _normalize_services(services):
    """Validate and normalize a list of service strings.

    Returns the normalized list or raises ValueError on invalid input.
    """
    if not isinstance(services, list) or not services:
        raise ValueError
    seen = set()
    normalized = []
    for service in services:
        if not isinstance(service, str):
            raise ValueError
        trimmed = service.strip()
        if not trimmed:
            raise ValueError
        if trimmed in seen:
            raise ValueError
        seen.add(trimmed)
        normalized.append(trimmed)
    return normalized


def _settlement_record(row, discovered_by):
    """Build a settlement response dict from a row and discoverer list."""
    return {
        "settlement_id": row["settlement_id"],
        "name": row["name"],
        "services": json.loads(row["services_json"]),
        "availability": row["availability"],
        "discovered_by": discovered_by,
    }


def _dm_settlement_response(conn, row):
    """Return the full settlement response for the DM."""
    rows = conn.execute(
        "SELECT character_id FROM play_settlement_discoveries "
        "WHERE campaign_id = ? AND settlement_id = ? ORDER BY id ASC",
        (row["campaign_id"], row["settlement_id"]),
    ).fetchall()
    discovered_by = [r["character_id"] for r in rows]
    return _settlement_record(row, discovered_by)


def _player_settlement_response(conn, row, character_id):
    """Return the player-filtered settlement response."""
    discovered = conn.execute(
        "SELECT 1 FROM play_settlement_discoveries "
        "WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?",
        (row["campaign_id"], row["settlement_id"], character_id),
    ).fetchone() is not None
    discovered_by = [character_id] if discovered else []
    return _settlement_record(row, discovered_by)


@csrf_exempt
def settlements(request, id):
    """GET /v1/play/campaigns/{id}/settlements or POST to create one."""
    bad = require_method(request, "GET", "POST")
    if bad:
        return bad
    if request.method == "POST":
        return _create_settlement(request, id)
    return _list_settlements(request, id)


def _create_settlement(request, id):
    actor, err = require_actor(request, "dm")
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")

    try:
        settlement_id = body["settlement_id"]
        name = body["name"]
        services = body["services"]
        availability = body["availability"]
        if not isinstance(settlement_id, str) or not settlement_id:
            raise ValueError
        if not isinstance(name, str) or not name:
            raise ValueError
        if not isinstance(availability, str) or availability not in VALID_AVAILABILITY:
            raise ValueError
        normalized_services = _normalize_services(services)
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")
        if actor["username"] != campaign["owner"]:
            return forbidden()

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
            "FROM play_settlements WHERE campaign_id = ?",
            (id,),
        ).fetchone()["next_sequence"]

        try:
            conn.execute(
                "INSERT INTO play_settlements (campaign_id, settlement_id, name, services_json, availability, sequence) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (id, settlement_id, name, json.dumps(normalized_services), availability, next_sequence),
            )
        except sqlite3.IntegrityError:
            return conflict("settlement already exists")

        row = conn.execute(
            "SELECT campaign_id, settlement_id, name, services_json, availability FROM play_settlements "
            "WHERE campaign_id = ? AND settlement_id = ?",
            (id, settlement_id),
        ).fetchone()
        response = _dm_settlement_response(conn, row)

    return JsonResponse(response, status=201)


@csrf_exempt
def update_settlement(request, id, settlement_id):
    """PUT /v1/play/campaigns/{id}/settlements/{settlement_id}"""
    bad = require_method(request, "PUT")
    if bad:
        return bad

    actor, err = require_actor(request, "dm")
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")

    try:
        name = body["name"]
        services = body["services"]
        availability = body["availability"]
        if not isinstance(name, str) or not name:
            raise ValueError
        if not isinstance(availability, str) or availability not in VALID_AVAILABILITY:
            raise ValueError
        normalized_services = _normalize_services(services)
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")
        if actor["username"] != campaign["owner"]:
            return forbidden()

        row = conn.execute(
            "SELECT campaign_id, settlement_id, name, services_json, availability FROM play_settlements "
            "WHERE campaign_id = ? AND settlement_id = ?",
            (id, settlement_id),
        ).fetchone()
        if row is None:
            return not_found("settlement not found")

        conn.execute(
            "UPDATE play_settlements SET name = ?, services_json = ?, availability = ? "
            "WHERE campaign_id = ? AND settlement_id = ?",
            (name, json.dumps(normalized_services), availability, id, settlement_id),
        )

        row = conn.execute(
            "SELECT campaign_id, settlement_id, name, services_json, availability FROM play_settlements "
            "WHERE campaign_id = ? AND settlement_id = ?",
            (id, settlement_id),
        ).fetchone()
        response = _dm_settlement_response(conn, row)

    return JsonResponse(response)


@csrf_exempt
def discover_settlement(request, id, settlement_id):
    """POST /v1/play/campaigns/{id}/settlements/{settlement_id}/discover"""
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "player")
    if err is not None:
        return err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] == campaign["owner"]:
            return forbidden()

        member = conn.execute(
            "SELECT character_id FROM play_campaign_members "
            "WHERE campaign_id = ? AND username = ?",
            (id, actor["username"]),
        ).fetchone()
        if member is None:
            return forbidden()
        character_id = member["character_id"]

        row = conn.execute(
            "SELECT campaign_id, settlement_id, name, services_json, availability FROM play_settlements "
            "WHERE campaign_id = ? AND settlement_id = ?",
            (id, settlement_id),
        ).fetchone()
        if row is None:
            return not_found("settlement not found")

        existing = conn.execute(
            "SELECT 1 FROM play_settlement_discoveries "
            "WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?",
            (id, settlement_id, character_id),
        ).fetchone()

        if existing is None:
            conn.execute(
                "INSERT INTO play_settlement_discoveries (campaign_id, settlement_id, character_id) "
                "VALUES (?, ?, ?)",
                (id, settlement_id, character_id),
            )
            status = 201
        else:
            status = 200

        response = _player_settlement_response(conn, row, character_id)

    return JsonResponse(response, status=status)


def _list_settlements(request, id):
    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    is_owner = actor["username"] == campaign["owner"]

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT campaign_id, settlement_id, name, services_json, availability FROM play_settlements "
            "WHERE campaign_id = ? ORDER BY sequence ASC",
            (id,),
        ).fetchall()

        if is_owner:
            settlements = [_dm_settlement_response(conn, row) for row in rows]
        else:
            member = conn.execute(
                "SELECT character_id FROM play_campaign_members "
                "WHERE campaign_id = ? AND username = ?",
                (id, actor["username"]),
            ).fetchone()
            character_id = member["character_id"]
            settlements = []
            for row in rows:
                discovered = conn.execute(
                    "SELECT 1 FROM play_settlement_discoveries "
                    "WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?",
                    (id, row["settlement_id"], character_id),
                ).fetchone() is not None
                if discovered:
                    settlements.append(_player_settlement_response(conn, row, character_id))

    return JsonResponse({"settlements": settlements})
