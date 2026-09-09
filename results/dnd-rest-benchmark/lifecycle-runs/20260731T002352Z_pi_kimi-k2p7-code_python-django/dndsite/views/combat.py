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
# Combat
# ---------------------------------------------------------------------------


@csrf_exempt
def create_combat_session(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        session_id = body["id"]
        combatants = body["combatants"]
        if not isinstance(session_id, str) or not isinstance(combatants, list) or not combatants:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    try:
        parsed = [parse_combatant(c) for c in combatants]
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid combatant")

    order = build_initiative_order(parsed)
    conditions = {c["name"]: [] for c in parsed}

    try:
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO combat_sessions (id, round, turn_index, order_json, conditions_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, 1, 0, json.dumps(order), json.dumps(conditions)),
            )
    except sqlite3.IntegrityError:
        return bad_request("session already exists")

    return JsonResponse(
        {
            "id": session_id,
            "round": 1,
            "turn_index": 0,
            "active": order[0],
            "order": order,
        }
    )


@csrf_exempt
def add_condition(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        target = str(body["target"])
        condition = str(body["condition"])
        duration = int(body["duration_rounds"])
        if duration <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        row = conn.execute(
            "SELECT conditions_json FROM combat_sessions WHERE id = ?", (id,)
        ).fetchone()
        if row is None:
            return not_found("session not found")

        conditions = json.loads(row["conditions_json"])
        if target not in conditions:
            return bad_request("invalid target")

        conditions[target].append({"condition": condition, "remaining_rounds": duration})
        conn.execute(
            "UPDATE combat_sessions SET conditions_json = ? WHERE id = ?",
            (json.dumps(conditions), id),
        )

    return JsonResponse({"target": target, "conditions": conditions[target]})


@csrf_exempt
def advance_turn(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    with db_conn() as conn:
        row = conn.execute(
            "SELECT round, turn_index, order_json, conditions_json FROM combat_sessions WHERE id = ?",
            (id,),
        ).fetchone()
        if row is None:
            return not_found("session not found")

        round_num = row["round"]
        turn_index = row["turn_index"]
        order = json.loads(row["order_json"])
        conditions = json.loads(row["conditions_json"])

        turn_index += 1
        if turn_index >= len(order):
            turn_index = 0
            round_num += 1

        active = order[turn_index]
        # Conditions on the active combatant decrement at the start of its turn.
        active_conditions = conditions[active["name"]]
        new_conditions = []
        for cond in active_conditions:
            cond["remaining_rounds"] -= 1
            if cond["remaining_rounds"] > 0:
                new_conditions.append(cond)
        conditions[active["name"]] = new_conditions

        conn.execute(
            "UPDATE combat_sessions SET round = ?, turn_index = ?, conditions_json = ? WHERE id = ?",
            (round_num, turn_index, json.dumps(conditions), id),
        )

    return JsonResponse(
        {
            "id": id,
            "round": round_num,
            "turn_index": turn_index,
            "active": active,
            "conditions": {name: list(conds) for name, conds in conditions.items()},
        }
    )



