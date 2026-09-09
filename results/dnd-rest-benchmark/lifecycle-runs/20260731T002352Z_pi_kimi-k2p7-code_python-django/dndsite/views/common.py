"""Shared helpers for the D&D REST API views.

These helpers encapsulate the most common authorization and ownership checks
so that each view stays focused on request parsing and endpoint-specific
logic. Error messages and status codes are preserved exactly to maintain
backward-compatible behavior.
"""

import json

from ..http import forbidden, not_found, unauthorized
from ..db import db_conn


def _get_actor(request):
    """Resolve the actor from the Authorization Bearer token.

    A well-formed ``Bearer session-<username>`` token is treated as a valid
    actor. If the username is known in the ``users`` table, its stored role is
    used; otherwise the actor is assumed to be a player. Missing or malformed
    tokens return ``None`` so the caller can respond with ``401``.
    """
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        return None
    token = header[7:]
    if not token.startswith("session-"):
        return None
    username = token[8:]
    with db_conn() as conn:
        row = conn.execute(
            "SELECT username, role FROM users WHERE username = ?", (username,)
        ).fetchone()
    if row is None:
        return {"username": username, "role": "player"}
    return {"username": row["username"], "role": row["role"]}


def require_actor(request, required_role=None, forbidden_message="forbidden"):
    """Authenticate the request and optionally enforce a role.

    Returns ``(actor, error_response)``. The error response is ``None`` on
    success; otherwise it is a JSON response with the same status and messages
    used by the original views.
    """
    actor = _get_actor(request)
    if actor is None:
        return None, unauthorized("invalid credentials")
    if required_role is not None and actor["role"] != required_role:
        return None, forbidden(forbidden_message)
    return actor, None


def require_play_campaign_owner(request, campaign_id):
    """Return ``(actor, campaign, error_response)`` for a campaign owner.

    The actor must be authenticated and own the campaign. No role check is
    performed so that views such as ``nudge_play_turn`` that only verify
    ownership keep their original behavior. The returned campaign row includes
    the turn state fields needed by those owner-only views.
    """
    actor, err = require_actor(request)
    if err is not None:
        return None, None, err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, name, owner, status, max_players, current_actor, turn_number, "
            "nudge_count, story, dm_notes, current_scene_id, current_location_id, phase, "
            "saved_actor, last_action_actor, safe_turn_current_turn FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return None, None, not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return None, None, forbidden()

    return actor, campaign, None


def require_play_campaign_dm_owner(request, campaign_id):
    """Return ``(actor, campaign, error_response)`` for a DM-owned campaign.

    The actor must be authenticated, have role ``dm``, and own the campaign.
    The returned campaign row includes the full play-campaign state for
    consistency with the other ownership helpers.
    """
    actor, err = require_actor(request, "dm")
    if err is not None:
        return None, None, err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, name, owner, status, max_players, current_actor, turn_number, "
            "nudge_count, story, dm_notes, current_scene_id, current_location_id, phase, "
            "saved_actor, last_action_actor, safe_turn_current_turn FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return None, None, not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return None, None, forbidden()

    return actor, campaign, None


def require_play_campaign_member_or_owner(request, campaign_id):
    """Return ``(actor, campaign, error_response)`` for a visible campaign.

    The actor must be authenticated and either own the campaign or be a member.
    The returned campaign row includes the fields most member/owner views need
    (turn state, story, dm_notes, and current location) so callers can avoid
    re-querying the same row.
    """
    actor, err = require_actor(request)
    if err is not None:
        return None, None, err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, name, owner, status, max_players, current_actor, turn_number, "
            "nudge_count, story, dm_notes, current_scene_id, current_location_id, phase, "
            "saved_actor, last_action_actor, safe_turn_current_turn FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return None, None, not_found("campaign not found")

        is_member = (
            conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, actor["username"]),
            ).fetchone()
            is not None
        )

        if actor["username"] != campaign["owner"] and not is_member:
            return None, None, forbidden()

    return actor, campaign, None


def can_narrate(campaign_id, username, conn=None):
    """Return True if the user may narrate for the campaign.

    The campaign owner always has narration authority. An active delegate
    whose delegation record includes the ``narrate`` power also qualifies.

    When ``conn`` is provided, the check is performed using that connection
    so callers already holding the database lock can avoid reentrancy.
    """
    if conn is None:
        with db_conn() as inner_conn:
            return can_narrate(campaign_id, username, inner_conn)

    campaign = conn.execute(
        "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if campaign is None:
        return False
    if campaign["owner"] == username:
        return True

    row = conn.execute(
        "SELECT powers_json, active FROM play_campaign_delegations "
        "WHERE campaign_id = ? AND username = ?",
        (campaign_id, username),
    ).fetchone()
    if row is None or not row["active"]:
        return False

    powers = json.loads(row["powers_json"])
    return "narrate" in powers
