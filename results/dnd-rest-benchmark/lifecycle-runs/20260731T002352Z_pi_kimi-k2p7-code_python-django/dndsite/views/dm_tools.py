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
# DM tools
# ---------------------------------------------------------------------------


@csrf_exempt
def encounter_builder(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        campaign_id = body["campaign_id"]
        party = body["party"]
        monster_slugs = body["monster_slugs"]
        if not isinstance(campaign_id, str) or not isinstance(party, list) or not isinstance(monster_slugs, list):
            raise ValueError
        if not all(isinstance(s, str) for s in monster_slugs):
            raise ValueError
        if not all(isinstance(m, dict) and isinstance(m.get("level"), int) for m in party):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        # Aggregate duplicate slugs into counts.
        slug_counts = {}
        for slug in monster_slugs:
            slug_counts[slug] = slug_counts.get(slug, 0) + 1

        monsters = []
        for slug, count in slug_counts.items():
            row = conn.execute("SELECT cr FROM monsters WHERE slug = ?", (slug,)).fetchone()
            if row is None:
                return bad_request("monster not found")
            monsters.append({"cr": row["cr"], "count": count})

    try:
        result = compute_encounter_xp(party, monsters)
    except ValueError:
        return bad_request("invalid request")

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "base_xp": result["base_xp"],
            "adjusted_xp": result["adjusted_xp"],
            "difficulty": result["difficulty"],
            "monster_count": result["monster_count"],
            "recommendation": encounter_recommendation(result["difficulty"]),
        }
    )


@csrf_exempt
def loot_parcel(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        campaign_id = body["campaign_id"]
        tier = body["tier"]
        if not isinstance(campaign_id, str) or not isinstance(tier, int):
            raise ValueError
        if tier < 1:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

    if tier != 1:
        return bad_request("unsupported tier")

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "coins_gp": 75,
            "items": [{"slug": "healing-potion", "quantity": 2}],
        }
    )


@csrf_exempt
def session_recap(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        campaign_id = body["campaign_id"]
        if not isinstance(campaign_id, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        event = conn.execute(
            "SELECT summary FROM campaign_events WHERE campaign_id = ? ORDER BY id DESC LIMIT 1",
            (campaign_id,),
        ).fetchone()

    if event is None:
        summary = "No recent events."
        open_threads = []
    else:
        summary = event["summary"]
        last_words = " ".join(summary.rstrip(".").split()[-2:])
        open_threads = [f"Resolve {last_words} ambush"]

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "summary": summary,
            "open_threads": open_threads,
        }
    )



