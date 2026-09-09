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

from .common import require_actor, require_play_campaign_member_or_owner

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
# Scene state
# ---------------------------------------------------------------------------


@csrf_exempt
def create_scene(request, id):
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
        scene_id = body["id"]
        name = body["name"]
        if not isinstance(scene_id, str) or not isinstance(name, str):
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
                "INSERT INTO scenes (campaign_id, scene_id, name, status) VALUES (?, ?, ?, ?)",
                (id, scene_id, name, "open"),
            )
        except sqlite3.IntegrityError:
            return conflict("scene already exists")

    return JsonResponse({"id": scene_id, "name": name, "status": "open"}, status=201)


@csrf_exempt
def enter_scene(request, id, scene_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

        scene = conn.execute(
            "SELECT scene_id, name, status FROM scenes WHERE campaign_id = ? AND scene_id = ?",
            (id, scene_id),
        ).fetchone()
        if scene is None:
            return not_found("scene not found")

        if scene["status"] == "closed":
            return conflict("scene is closed")

        conn.execute(
            "UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?",
            (scene_id, id),
        )

    return JsonResponse({"current_scene_id": scene_id, "name": scene["name"]})


@csrf_exempt
def close_scene(request, id, scene_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

        scene = conn.execute(
            "SELECT scene_id FROM scenes WHERE campaign_id = ? AND scene_id = ?",
            (id, scene_id),
        ).fetchone()
        if scene is None:
            return not_found("scene not found")

        conn.execute(
            "UPDATE scenes SET status = ? WHERE campaign_id = ? AND scene_id = ?",
            ("closed", id, scene_id),
        )
        conn.execute(
            "UPDATE play_campaigns SET current_scene_id = NULL WHERE id = ? AND current_scene_id = ?",
            (id, scene_id),
        )

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM narrations WHERE campaign_id = ?",
            (id,),
        ).fetchone()["next_sequence"]
        conn.execute(
            "INSERT INTO narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
            (id, next_sequence, "scene_closed", campaign["owner"], ""),
        )

    return JsonResponse({"id": scene_id, "status": "closed"})


@csrf_exempt
def get_current_scene(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    if campaign["current_scene_id"] is None:
        return not_found("scene not found")

    with db_conn() as conn:
        scene = conn.execute(
            "SELECT scene_id, name, status FROM scenes WHERE campaign_id = ? AND scene_id = ?",
            (id, campaign["current_scene_id"]),
        ).fetchone()
        if scene is None or scene["status"] != "open":
            return not_found("scene not found")

    return JsonResponse(
        {"id": scene["scene_id"], "name": scene["name"], "status": scene["status"]}
    )



