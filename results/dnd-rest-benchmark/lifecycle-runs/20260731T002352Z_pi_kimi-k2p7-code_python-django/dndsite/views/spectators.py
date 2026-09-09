"""Read-only spectator access for play campaigns."""

import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_play_campaign_dm_owner
from ..db import db_conn
from ..http import bad_request, conflict, forbidden, not_found, parse_json, require_method, unauthorized


def _get_spectator_id(request):
    """Return the spectator id from a ``Bearer spectator-<id>`` token, or None."""
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        return None
    token = header[7:]
    if not token.startswith("spectator-"):
        return None
    return token[10:]


def _is_session_token(request):
    """Return True if the Authorization header carries a session token."""
    header = request.headers.get("Authorization")
    return bool(header and header.startswith("Bearer session-"))


@csrf_exempt
def create_spectator(request, id):
    """Issue a deterministic spectator token for a campaign."""
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
        spectator_id = body["spectator_id"]
        if not isinstance(spectator_id, str) or not spectator_id:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO play_campaign_spectators (spectator_id, campaign_id) VALUES (?, ?)",
                (spectator_id, id),
            )
        except sqlite3.IntegrityError:
            return conflict("spectator already exists")

    return JsonResponse(
        {"spectator_id": spectator_id, "token": f"spectator-{spectator_id}"},
        status=201,
    )


@csrf_exempt
def spectator_view(request, id):
    """Return a public, read-only projection of a campaign for spectators."""
    bad = require_method(request, "GET")
    if bad:
        return bad

    spectator_id = _get_spectator_id(request)
    if spectator_id is None:
        if _is_session_token(request):
            return forbidden()
        return unauthorized("invalid credentials")

    with db_conn() as conn:
        row = conn.execute(
            "SELECT campaign_id FROM play_campaign_spectators WHERE spectator_id = ?",
            (spectator_id,),
        ).fetchone()
        if row is None:
            return unauthorized("invalid credentials")

        campaign = conn.execute(
            "SELECT id, name, status, story FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if row["campaign_id"] != id:
            return forbidden()

        party_size = conn.execute(
            "SELECT COUNT(*) AS count FROM play_campaign_members WHERE campaign_id = ?",
            (id,),
        ).fetchone()["count"]

    return JsonResponse(
        {
            "campaign_id": campaign["id"],
            "name": campaign["name"],
            "status": campaign["status"],
            "party_size": party_size,
            "story": campaign["story"] or "",
        }
    )
