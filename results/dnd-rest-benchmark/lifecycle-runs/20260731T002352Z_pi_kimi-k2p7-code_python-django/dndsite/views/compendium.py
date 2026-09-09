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
# Compendium
# ---------------------------------------------------------------------------


@csrf_exempt
def create_monster(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        slug = body["slug"]
        name = body["name"]
        cr = body["cr"]
        armor_class = body["armor_class"]
        hit_points = body["hit_points"]
        tags = body["tags"]
        if not isinstance(slug, str) or not isinstance(name, str):
            raise ValueError
        if not isinstance(cr, str) and not isinstance(cr, int):
            raise ValueError
        if not isinstance(armor_class, int) or not isinstance(hit_points, int):
            raise ValueError
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    try:
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (slug, name, str(cr), armor_class, hit_points, json.dumps(tags)),
            )
    except sqlite3.IntegrityError:
        return conflict("monster already exists")

    return JsonResponse(
        {
            "slug": slug,
            "name": name,
            "cr": str(cr),
            "armor_class": armor_class,
            "hit_points": hit_points,
        },
        status=201,
    )


@csrf_exempt
def get_monster(request, slug):
    bad = require_method(request, "GET")
    if bad:
        return bad

    with db_conn() as conn:
        row = conn.execute(
            "SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters WHERE slug = ?",
            (slug,),
        ).fetchone()
    if row is None:
        return not_found("monster not found")

    return JsonResponse(
        {
            "slug": row["slug"],
            "name": row["name"],
            "cr": row["cr"],
            "armor_class": row["armor_class"],
            "hit_points": row["hit_points"],
            "tags": json.loads(row["tags_json"]),
        }
    )


@csrf_exempt
def create_item(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        slug = body["slug"]
        name = body["name"]
        item_type = body["type"]
        rarity = body["rarity"]
        cost_gp = body["cost_gp"]
        if not isinstance(slug, str) or not isinstance(name, str):
            raise ValueError
        if not isinstance(item_type, str) or not isinstance(rarity, str):
            raise ValueError
        if not isinstance(cost_gp, int):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    try:
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
                (slug, name, item_type, rarity, cost_gp),
            )
    except sqlite3.IntegrityError:
        return conflict("item already exists")

    return JsonResponse(
        {
            "slug": slug,
            "name": name,
            "type": item_type,
            "rarity": rarity,
            "cost_gp": cost_gp,
        },
        status=201,
    )


@csrf_exempt
def get_item(request, slug):
    bad = require_method(request, "GET")
    if bad:
        return bad

    with db_conn() as conn:
        row = conn.execute(
            "SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?", (slug,)
        ).fetchone()
    if row is None:
        return not_found("item not found")

    return JsonResponse(
        {
            "slug": row["slug"],
            "name": row["name"],
            "type": row["type"],
            "rarity": row["rarity"],
            "cost_gp": row["cost_gp"],
        }
    )



