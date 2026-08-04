"""Shared route helpers: validation, responses, auth, and existence checks.

These utilities are used by every route module. They are intentionally
small and deterministic so that the HTTP contract is easy to preserve.
"""

import re

from flask import jsonify, request

import storage


# --- Validation helpers ---

USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def _body():
    """Return the parsed JSON body, or an empty dict on failure."""
    return request.get_json(silent=True) or {}


def _require_strings(*values):
    """Return True when every value is a non-empty string."""
    return all(isinstance(value, str) and value != "" for value in values)


# --- Response helpers ---

# These helpers keep the error messages centralized. The exact strings are part
# of the cumulative API contract, so they are intentionally not configurable.


def _bad_request():
    return jsonify(error="invalid input"), 400


def _unauthorized():
    return jsonify(error="unauthorized"), 401


def _forbidden():
    return jsonify(error="forbidden"), 403


def _not_found():
    return jsonify(error="not found"), 404


def _conflict(message):
    return jsonify(error=message), 409


# --- Auth helpers ---


def _current_user():
    """Return the authenticated user dict, or None for invalid credentials.

    A valid user dict has a 'username' and 'role'. A missing or malformed
    Authorization header returns None. Unknown usernames fall back to a
    default role so that the protected play surface stays usable after a
    storage reset: 'dm' is treated as a DM, and every other well-formed
    session username is treated as a player.
    """
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:]
    if not token.startswith("session-"):
        return None
    username = token[8:]
    if not USERNAME_RE.fullmatch(username):
        return None
    user = storage.get_user(username)
    if user is not None:
        return {"username": username, "role": user["role"]}
    if username == "dm":
        return {"username": username, "role": "dm"}
    return {"username": username, "role": "player"}


def _require_role(required_role):
    """Return (user, error_response) for a protected endpoint.

    Returns (None, None) when the actor has the required role.
    Returns (None, 401 response) for missing/invalid credentials,
    and (None, 403 response) for a valid actor without permission.
    """
    user = _current_user()
    if user is None:
        return None, _unauthorized()
    if user["role"] != required_role:
        return None, _forbidden()
    return user, None


# --- Campaign / resource existence helpers ---


def _load_campaign(camp_id):
    """Return (campaign, error_response) for a campaign lookup."""
    campaign = storage.get_campaign(camp_id)
    if campaign is None:
        return None, _not_found()
    return campaign, None


def _ensure_campaign(camp_id):
    """Return a 404 response if the campaign does not exist, otherwise None."""
    if storage.get_campaign(camp_id) is None:
        return _not_found()
    return None


def _load_play_campaign(camp_id):
    """Return (play_campaign, error_response) for a play campaign lookup."""
    campaign = storage.get_play_campaign(camp_id)
    if campaign is None:
        return None, _not_found()
    return campaign, None


def _ensure_play_campaign(camp_id):
    """Return a 404 response if the play campaign does not exist, otherwise None."""
    if storage.get_play_campaign(camp_id) is None:
        return _not_found()
    return None


def _require_owner(campaign, user):
    """Return a 403 response if the user is not the campaign owner."""
    if campaign["owner"] != user["username"]:
        return _forbidden()
    return None


def _require_owner_or_member(campaign, camp_id, user):
    """Return a 403 response if the user is neither owner nor a member."""
    if campaign["owner"] != user["username"] and not storage.is_play_campaign_member(camp_id, user["username"]):
        return _forbidden()
    return None


def _require_dm_campaign(camp_id):
    """Return ((campaign, user), error_response) for a DM owner.

    This combines the three checks repeated by every DM-only play-campaign
    endpoint: require DM role, load the campaign, and require ownership.
    On success, error_response is None; on failure, (campaign, user) is
    (None, None).
    """
    user, error = _require_role("dm")
    if error:
        return (None, None), error
    campaign, err = _load_play_campaign(camp_id)
    if err:
        return (None, None), err
    err = _require_owner(campaign, user)
    if err:
        return (None, None), err
    return (campaign, user), None


def _require_play_campaign_access(camp_id):
    """Return ((campaign, user), error_response) for an owner or member.

    This combines the three checks repeated by most play-campaign endpoints:
    require a valid session, load the campaign, and require owner or member.
    On success, error_response is None; on failure, (campaign, user) is
    (None, None).
    """
    user = _current_user()
    if user is None:
        return (None, None), _unauthorized()
    campaign, err = _load_play_campaign(camp_id)
    if err:
        return (None, None), err
    err = _require_owner_or_member(campaign, camp_id, user)
    if err:
        return (None, None), err
    return (campaign, user), None


# --- Initiative parsing helper ---


def _parse_initiative_combatants(raw_combatants, require_unique_names=False):
    """Build scored combatants from a raw request list.

    Returns (combatants, error_response). Each returned combatant has the
    fields required by domain.initiative_order: 'name', 'score', and 'dex'.
    When require_unique_names is True, names must be non-empty strings and
    must be unique within the list.
    """
    if not isinstance(raw_combatants, list):
        return None, _bad_request()

    combatants = []
    seen_names = set()
    for combatant in raw_combatants:
        if not isinstance(combatant, dict):
            return None, _bad_request()
        try:
            name = combatant["name"]
            dex = int(combatant["dex"])
            roll = int(combatant["roll"])
        except (KeyError, TypeError, ValueError):
            return None, _bad_request()

        if require_unique_names:
            if not isinstance(name, str) or name == "" or name in seen_names:
                return None, _bad_request()
            seen_names.add(name)

        combatants.append({"name": name, "score": roll + dex, "dex": dex})
    return combatants, None
