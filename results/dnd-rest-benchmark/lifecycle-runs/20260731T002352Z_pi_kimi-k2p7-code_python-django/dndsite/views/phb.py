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
# PHB rules
# ---------------------------------------------------------------------------


@csrf_exempt
def spell_slots(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        character_class = body["class"]
        level = body["level"]
        if not isinstance(character_class, str) or not isinstance(level, int):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if character_class != "wizard" or level != 5:
        return bad_request("unsupported class or level")

    return JsonResponse(
        {
            "class": character_class,
            "level": level,
            "slots": {"1": 4, "2": 3, "3": 2},
        }
    )


@csrf_exempt
def long_rest(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        level = int(body["level"])
        hp_current = int(body["hp_current"])
        hp_max = int(body["hp_max"])
        hit_dice_spent = int(body["hit_dice_spent"])
        exhaustion_level = int(body["exhaustion_level"])
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if level < 1 or hp_max < 1 or hp_current < 0 or hit_dice_spent < 0 or exhaustion_level < 0:
        return bad_request("invalid request")

    restored = max(1, level // 2)
    new_hit_dice_spent = max(0, hit_dice_spent - restored)
    new_exhaustion = max(0, exhaustion_level - 1)

    return JsonResponse(
        {
            "hp_current": hp_max,
            "hit_dice_spent": new_hit_dice_spent,
            "exhaustion_level": new_exhaustion,
        }
    )


@csrf_exempt
def equipment_load(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        strength = int(body["strength"])
        weight = int(body["weight"])
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if strength < 1 or weight < 0:
        return bad_request("invalid request")

    capacity = strength * 15
    return JsonResponse(
        {"capacity": capacity, "weight": weight, "encumbered": weight > capacity}
    )



