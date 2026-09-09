"""Campaign-scoped deterministic RNG ledger views."""

import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import (
    require_play_campaign_dm_owner,
    require_play_campaign_member_or_owner,
)
from ..db import (
    _append_rng_roll,
    _get_campaign_rng_seed,
    _list_rng_rolls,
    _next_rng_roll_sequence,
    _set_campaign_rng_seed,
    db_conn,
)
from ..domain import deterministic_roll
from ..http import bad_request, conflict, parse_json, require_method


@csrf_exempt
def configure_rng_seed(request, id):
    bad = require_method(request, "PUT")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None or not isinstance(body, dict):
        return bad_request("invalid request")
    try:
        seed = body["seed"]
        if not isinstance(seed, str) or not seed:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        existing = _get_campaign_rng_seed(conn, id)
        if existing is not None:
            return conflict("seed already configured")
        _set_campaign_rng_seed(conn, id, seed)
        rolls = _list_rng_rolls(conn, id)

    return JsonResponse({"seed": seed, "rolls": rolls})


@csrf_exempt
def append_rng_roll(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None or not isinstance(body, dict):
        return bad_request("invalid request")
    try:
        roll_id = body["roll_id"]
        sides = body["sides"]
        if not isinstance(roll_id, str) or not roll_id:
            raise ValueError
        if not isinstance(sides, int) or sides < 2 or sides > 100:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        seed = _get_campaign_rng_seed(conn, id)
        if seed is None:
            return conflict("no seed configured")

        existing = conn.execute(
            "SELECT 1 FROM play_campaign_rng_rolls WHERE campaign_id = ? AND roll_id = ?",
            (id, roll_id),
        ).fetchone()
        if existing is not None:
            return conflict("roll_id already exists")

        sequence = _next_rng_roll_sequence(conn, id)
        result = deterministic_roll(seed, sequence, roll_id, sides)
        try:
            _append_rng_roll(conn, id, sequence, roll_id, sides, result)
        except sqlite3.IntegrityError:
            return conflict("roll_id already exists")

    return JsonResponse(
        {
            "roll_id": roll_id,
            "sides": sides,
            "result": result,
            "sequence": sequence,
        },
        status=201,
    )


@csrf_exempt
def get_rng_ledger(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        seed = _get_campaign_rng_seed(conn, id)
        rolls = _list_rng_rolls(conn, id)

    return JsonResponse({"seed": seed, "rolls": rolls})
