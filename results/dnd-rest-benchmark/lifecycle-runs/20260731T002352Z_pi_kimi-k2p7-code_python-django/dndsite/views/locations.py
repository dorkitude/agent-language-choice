"""Django views for the D&D REST API.

Each view is a thin layer over the ``domain`` and ``db`` modules. Common
request parsing and response helpers live in ``dndsite.http``. Validation
failures return 400, missing resources 404, and conflicts 409. Error message
strings are preserved from the original implementation to maintain exact
response bodies.
"""

import json
import sqlite3

from django.contrib.auth.hashers import check_password, make_password
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import (
    require_actor,
    require_play_campaign_member_or_owner,
)

from ..http import bad_request, conflict, forbidden, not_found, parse_json, require_method, unauthorized

from ..constants import (
    DICE_RE,
    HIT_DICE,
    SCHEMA_VERSION,
    SKILL_ABILITIES,
    USERNAME_RE,
    VALID_BACKGROUNDS,
    VALID_CLASSES,
    VALID_RACES,
)
from ..db import (
    _add_inventory_item,
    _assign_equipment,
    _get_inventory_summary,
    db_conn,
    is_initialized,
    reset_storage,
)
from ..domain import (
    ability_modifier as compute_ability_modifier,
    avg_hit_die,
    build_initiative_order,
    compute_encounter_xp,
    encounter_recommendation,
    parse_combatant,
    proficiency_bonus,
    skill_check_modifier,
)

# ---------------------------------------------------------------------------
# Location graph
# ---------------------------------------------------------------------------


@csrf_exempt
def create_location(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        location_id = body["id"]
        name = body["name"]
        if not isinstance(location_id, str) or not isinstance(name, str):
            raise ValueError
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

        try:
            conn.execute(
                "INSERT INTO locations (campaign_id, location_id, name) VALUES (?, ?, ?)",
                (id, location_id, name),
            )
        except sqlite3.IntegrityError:
            return conflict("location already exists")

        conn.execute(
            "UPDATE play_campaigns SET current_location_id = ? WHERE id = ? AND current_location_id IS NULL",
            (location_id, id),
        )

    return JsonResponse({"id": location_id, "name": name}, status=201)


@csrf_exempt
def create_connection(request, id, from_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        to_id = body["to_id"]
        travel_turns = body["travel_turns"]
        if not isinstance(to_id, str) or not isinstance(travel_turns, int):
            raise ValueError
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

        from_loc = conn.execute(
            "SELECT 1 FROM locations WHERE campaign_id = ? AND location_id = ?",
            (id, from_id),
        ).fetchone()
        if from_loc is None:
            return bad_request("invalid location")

        to_loc = conn.execute(
            "SELECT 1 FROM locations WHERE campaign_id = ? AND location_id = ?",
            (id, to_id),
        ).fetchone()
        if to_loc is None:
            return bad_request("invalid destination")

        existing = conn.execute(
            "SELECT 1 FROM location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
            (id, from_id, to_id),
        ).fetchone()
        if existing is not None:
            return bad_request("connection already exists")

        conn.execute(
            "INSERT INTO location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)",
            (id, from_id, to_id, travel_turns),
        )

    return JsonResponse(
        {"from_id": from_id, "to_id": to_id, "travel_turns": travel_turns}, status=201
    )


@csrf_exempt
def get_valid_travel(request, id, loc_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        location = conn.execute(
            "SELECT 1 FROM locations WHERE campaign_id = ? AND location_id = ?",
            (id, loc_id),
        ).fetchone()
        if location is None:
            return not_found("location not found")

        rows = conn.execute(
            """
            SELECT l.location_id, l.name, c.travel_turns
            FROM location_connections c
            JOIN locations l ON l.campaign_id = c.campaign_id AND l.location_id = c.to_id
            WHERE c.campaign_id = ? AND c.from_id = ?
            ORDER BY l.location_id ASC
            """,
            (id, loc_id),
        ).fetchall()

    destinations = [
        {"id": row["location_id"], "name": row["name"], "travel_turns": row["travel_turns"]}
        for row in rows
    ]

    return JsonResponse({"destinations": destinations})


@csrf_exempt
def travel_turn(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        destination_id = body["destination_id"]
        if not isinstance(destination_id, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner, status, current_actor, turn_number, current_location_id "
            "FROM play_campaigns WHERE id = ?",
            (id,),
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        is_member = (
            conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (id, actor["username"]),
            ).fetchone()
            is not None
        )

        if actor["username"] != campaign["owner"] and not is_member:
            return forbidden()

        if actor["role"] == "dm" or actor["username"] != campaign["current_actor"]:
            return conflict("not your turn")

        connection = conn.execute(
            "SELECT travel_turns FROM location_connections "
            "WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
            (id, campaign["current_location_id"], destination_id),
        ).fetchone()
        if connection is None:
            return conflict("invalid destination")

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM narrations WHERE campaign_id = ?",
            (id,),
        ).fetchone()["next_sequence"]

        conn.execute(
            "INSERT INTO narrations (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (id, next_sequence, "travel", actor["username"], destination_id),
        )

        conn.execute(
            "UPDATE play_campaigns SET current_actor = ?, last_action_actor = ?, current_location_id = ? "
            "WHERE id = ?",
            (campaign["owner"], actor["username"], destination_id, id),
        )

    next_actor = campaign["owner"]
    return JsonResponse(
        {
            "sequence": next_sequence,
            "kind": "travel",
            "actor": actor["username"],
            "destination_id": destination_id,
            "travel_turns": connection["travel_turns"],
            "next_actor": next_actor,
        },
        status=201,
    )


@csrf_exempt
def rest_turn(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        rest_type = body["type"]
        if not isinstance(rest_type, str) or rest_type not in ("short", "long"):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner, status, current_actor, turn_number FROM play_campaigns WHERE id = ?",
            (id,),
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        is_member = (
            conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (id, actor["username"]),
            ).fetchone()
            is not None
        )

        if actor["username"] != campaign["owner"] and not is_member:
            return forbidden()

        if actor["role"] == "dm" or actor["username"] != campaign["current_actor"]:
            return conflict("not your turn")

        member = conn.execute(
            "SELECT character_id, hp_current, hp_max FROM play_campaign_members "
            "WHERE campaign_id = ? AND username = ?",
            (id, actor["username"]),
        ).fetchone()

        hp_current = member["hp_current"]
        hp_max = member["hp_max"]

        if rest_type == "long":
            hp_current = hp_max
            conn.execute(
                "UPDATE play_campaign_members SET hp_current = ?, status = 'conscious', death_save_successes = 0, death_save_failures = 0 WHERE campaign_id = ? AND username = ?",
                (hp_current, id, actor["username"]),
            )

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM narrations WHERE campaign_id = ?",
            (id,),
        ).fetchone()["next_sequence"]

        conn.execute(
            "INSERT INTO narrations (campaign_id, sequence, kind, type, actor, text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (id, next_sequence, "rest", rest_type, actor["username"], ""),
        )

        conn.execute(
            "UPDATE play_campaigns SET current_actor = ? WHERE id = ?",
            (campaign["owner"], id),
        )

    next_actor = campaign["owner"]
    return JsonResponse(
        {
            "sequence": next_sequence,
            "kind": "rest",
            "actor": actor["username"],
            "type": rest_type,
            "hp_current": hp_current,
            "hp_max": hp_max,
            "next_actor": next_actor,
        },
        status=201,
    )



