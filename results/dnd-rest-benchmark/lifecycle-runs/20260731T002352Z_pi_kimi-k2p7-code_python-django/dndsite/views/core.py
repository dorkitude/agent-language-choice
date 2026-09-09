"""Django views for the D&D REST API.

Each view is a thin layer over the ``domain`` and ``db`` modules. Common
request parsing and response helpers live in ``dndsite.http``. Validation
failures return 400, missing resources 404, and conflicts 409. Error message
strings are preserved from the original implementation to maintain exact
response bodies.
"""

import sqlite3

from django.contrib.auth.hashers import check_password, make_password
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from ..http import (
    bad_request,
    conflict,
    parse_json,
    require_method,
    unauthorized,
)
from ..constants import DICE_RE, SCHEMA_VERSION, USERNAME_RE
from ..db import db_conn, is_initialized, reset_storage
from ..domain import (
    ability_modifier as compute_ability_modifier,
    build_initiative_order,
    compute_encounter_xp,
    parse_combatant,
    proficiency_bonus,
)

# ---------------------------------------------------------------------------
# API schema
# ---------------------------------------------------------------------------

API_SCHEMA = {
    "version": "2026-07-29",
    "endpoints": [
        {"method": "GET", "path": "/v1/play/campaigns/{id}/rng-ledger", "auth": "member"},
        {"method": "GET", "path": "/v1/schema", "auth": "public"},
        {"method": "POST", "path": "/v1/play/campaigns", "auth": "dm"},
        {"method": "POST", "path": "/v1/play/campaigns/{id}/fixture-seeds", "auth": "dm"},
        {"method": "POST", "path": "/v1/play/campaigns/{id}/members", "auth": "member"},
        {"method": "POST", "path": "/v1/play/campaigns/{id}/moderation/reports", "auth": "member"},
        {"method": "POST", "path": "/v1/play/campaigns/{id}/rng-rolls", "auth": "member"},
        {"method": "PUT", "path": "/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution", "auth": "dm"},
        {"method": "PUT", "path": "/v1/play/campaigns/{id}/rng-seed", "auth": "dm"},
        {"method": "PUT", "path": "/v1/play/campaigns/{id}/safety-boundaries", "auth": "dm"},
    ],
}


@csrf_exempt
def schema(request):
    bad = require_method(request, "GET")
    if bad:
        return bad
    return JsonResponse(API_SCHEMA)


# ---------------------------------------------------------------------------
# Health & storage
# ---------------------------------------------------------------------------


def health(request):
    return JsonResponse({"ok": True})


@csrf_exempt
def storage_status(request):
    bad = require_method(request, "GET")
    if bad:
        return bad
    return JsonResponse(
        {
            "driver": "sqlite",
            "schema_version": SCHEMA_VERSION,
            "initialized": is_initialized(),
        }
    )


@csrf_exempt
def storage_reset(request):
    bad = require_method(request, "POST")
    if bad:
        return bad
    reset_storage()
    return JsonResponse({"ok": True, "schema_version": SCHEMA_VERSION})



# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@csrf_exempt
def register(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        username = body["username"]
        password = body["password"]
        role = body["role"]
        if not all(isinstance(v, str) for v in (username, password, role)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if not USERNAME_RE.match(username):
        return bad_request("invalid username")
    if len(password) < 8:
        return bad_request("password too short")
    if role not in ("dm", "player"):
        return bad_request("invalid role")

    try:
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, make_password(password), role),
            )
    except sqlite3.IntegrityError:
        return conflict("username already exists")

    return JsonResponse({"username": username, "role": role}, status=201)


@csrf_exempt
def login(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        username = body["username"]
        password = body["password"]
        if not isinstance(username, str) or not isinstance(password, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()

    if row is None or not check_password(password, row["password_hash"]):
        return unauthorized("invalid credentials")

    return JsonResponse({"username": username, "token": f"session-{username}"})



# ---------------------------------------------------------------------------
# Core mechanics
# ---------------------------------------------------------------------------


@csrf_exempt
def dice_stats(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        expr = body["expression"]
    except (KeyError, TypeError):
        return bad_request("invalid request")

    match = DICE_RE.match(str(expr))
    if not match:
        return bad_request("invalid expression")

    count = int(match.group("count"))
    sides = int(match.group("sides"))
    mod = match.group("mod")

    if count <= 0 or sides <= 0:
        return bad_request("count and sides must be positive")

    modifier = 0 if mod is None else int(mod)

    average = count * (sides + 1) / 2 + modifier
    average = int(average) if average == int(average) else average

    return JsonResponse(
        {
            "dice_count": count,
            "sides": sides,
            "modifier": modifier,
            "min": count + modifier,
            "max": count * sides + modifier,
            "average": average,
        }
    )


@csrf_exempt
def ability_check(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        roll = int(body["roll"])
        modifier = int(body["modifier"])
        dc = int(body["dc"])
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    total = roll + modifier
    return JsonResponse({"total": total, "success": total >= dc, "margin": total - dc})


@csrf_exempt
def adjusted_xp(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        party = body["party"]
        monsters = body["monsters"]
    except (KeyError, TypeError):
        return bad_request("invalid request")

    try:
        result = compute_encounter_xp(party, monsters)
    except ValueError as exc:
        return bad_request(str(exc))

    return JsonResponse(
        {
            "base_xp": result["base_xp"],
            "monster_count": result["monster_count"],
            "multiplier": result["multiplier"],
            "adjusted_xp": result["adjusted_xp"],
            "difficulty": result["difficulty"],
            "thresholds": result["thresholds"],
        }
    )


@csrf_exempt
def initiative_order(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        combatants = body["combatants"]
    except (KeyError, TypeError):
        return bad_request("invalid request")

    try:
        parsed = [parse_combatant(c) for c in combatants]
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid combatant")

    return JsonResponse({"order": build_initiative_order(parsed)})



# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------


@csrf_exempt
def ability_modifier(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        score = body["score"]
        if not isinstance(score, int) or score < 1 or score > 30:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    return JsonResponse({"score": score, "modifier": compute_ability_modifier(score)})


@csrf_exempt
def proficiency(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        level = body["level"]
        if not isinstance(level, int) or level < 1 or level > 20:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    return JsonResponse({"level": level, "proficiency_bonus": proficiency_bonus(level)})


@csrf_exempt
def derived_stats(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        level = body["level"]
        abilities = body["abilities"]
        armor = body["armor"]

        if not isinstance(level, int) or level < 1 or level > 20:
            raise ValueError

        ability_names = ["str", "dex", "con", "int", "wis", "cha"]
        modifiers = {}
        for name in ability_names:
            score = abilities[name]
            if not isinstance(score, int) or score < 1 or score > 30:
                raise ValueError
            modifiers[name] = compute_ability_modifier(score)

        base = armor["base"]
        dex_cap = armor["dex_cap"]
        shield = armor["shield"]
        if not isinstance(base, int) or not isinstance(dex_cap, int) or not isinstance(shield, bool):
            raise ValueError

        shield_bonus = 2 if shield else 0
        armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus
        hp_max = level * (6 + modifiers["con"])
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    return JsonResponse(
        {
            "level": level,
            "proficiency_bonus": proficiency_bonus(level),
            "hp_max": hp_max,
            "armor_class": armor_class,
            "modifiers": modifiers,
        }
    )



