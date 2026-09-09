"""Campaign-scoped GM delegation views."""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_play_campaign_dm_owner
from ..http import bad_request, conflict, forbidden, not_found, parse_json, require_method
from ..db import db_conn


VALID_POWERS = {"narrate"}


def _validate_powers(powers):
    """Return (True, unique_list) if powers is a nonempty list of unique valid values."""
    if not isinstance(powers, list) or len(powers) == 0:
        return False, None
    seen = set()
    result = []
    for power in powers:
        if not isinstance(power, str) or power not in VALID_POWERS or power in seen:
            return False, None
        seen.add(power)
        result.append(power)
    return True, result


@csrf_exempt
def grant_delegation(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        username = body["username"]
        powers = body["powers"]
        if not isinstance(username, str) or not username:
            raise ValueError
        valid, powers = _validate_powers(powers)
        if not valid:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        member = conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (id, username),
        ).fetchone()
        if member is None:
            return bad_request("invalid request")

        existing = conn.execute(
            "SELECT active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?",
            (id, username),
        ).fetchone()
        if existing is not None and existing["active"]:
            return conflict("delegation already exists")

        powers_json = json.dumps(powers)
        if existing is None:
            conn.execute(
                "INSERT INTO play_campaign_delegations (campaign_id, username, powers_json, active) "
                "VALUES (?, ?, ?, ?)",
                (id, username, powers_json, 1),
            )
        else:
            conn.execute(
                "UPDATE play_campaign_delegations SET powers_json = ?, active = ? "
                "WHERE campaign_id = ? AND username = ?",
                (powers_json, 1, id, username),
            )

        conn.execute(
            "INSERT INTO play_campaign_delegation_audit (campaign_id, username, action, powers_json) "
            "VALUES (?, ?, ?, ?)",
            (id, username, "granted", powers_json),
        )

    return JsonResponse(
        {"username": username, "powers": powers, "active": True},
        status=201,
    )


@csrf_exempt
def revoke_delegation(request, id, username):
    bad = require_method(request, "DELETE")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        existing = conn.execute(
            "SELECT powers_json, active FROM play_campaign_delegations "
            "WHERE campaign_id = ? AND username = ?",
            (id, username),
        ).fetchone()
        if existing is None:
            return not_found("delegation not found")

        powers = json.loads(existing["powers_json"])

        if existing["active"]:
            conn.execute(
                "UPDATE play_campaign_delegations SET active = ? "
                "WHERE campaign_id = ? AND username = ?",
                (0, id, username),
            )
            conn.execute(
                "INSERT INTO play_campaign_delegation_audit (campaign_id, username, action, powers_json) "
                "VALUES (?, ?, ?, ?)",
                (id, username, "revoked", existing["powers_json"]),
            )

    return JsonResponse(
        {"username": username, "powers": powers, "active": False},
        status=200,
    )


@csrf_exempt
def delegation_audit(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT username, action, powers_json FROM play_campaign_delegation_audit "
            "WHERE campaign_id = ? ORDER BY id",
            (id,),
        ).fetchall()

    entries = [
        {
            "username": row["username"],
            "action": row["action"],
            "powers": json.loads(row["powers_json"]),
        }
        for row in rows
    ]

    return JsonResponse({"entries": entries})
