"""Small helpers shared across view modules. Not a URL-routable module itself."""

import json

from django.http import JsonResponse

from dndsite import db

BEARER_PREFIX = "Bearer "
SESSION_PREFIX = "session-"


def json_body(request):
    """Parse the request body as JSON. Raises json.JSONDecodeError/TypeError on malformed input."""
    return json.loads(request.body.decode("utf-8"))


def error_response(message, status):
    """Build the ``{"error": message}`` JSON envelope used by every failure response."""
    return JsonResponse({"error": message}, status=status)


def require_method(request, *allowed_methods):
    """Return a 405 response if the request method isn't allowed, else None."""
    if request.method not in allowed_methods:
        return error_response("method not allowed", 405)
    return None


def require_campaign(campaign_id):
    """Fetch a legacy (non-play) campaign, or a 404 response if it doesn't exist.

    Returns ``(campaign, error_response)``; exactly one of the two is None.
    """
    campaign = db.get_campaign(campaign_id)
    if campaign is None:
        return None, error_response("campaign not found", 404)
    return campaign, None


def require_play_campaign(campaign_id):
    """Fetch a play campaign, or a 404 response if it doesn't exist.

    Returns ``(campaign, error_response)``; exactly one of the two is None.
    """
    campaign = db.get_play_campaign(campaign_id)
    if campaign is None:
        return None, error_response("campaign not found", 404)
    return campaign, None


def require_play_auth(request):
    """Authenticate a play-surface request, translating auth failure into a response.

    Returns ``(user, error_response)``; exactly one of the two is None.
    """
    user, error_status = authenticate_play(request)
    if error_status is not None:
        message = "unauthorized" if error_status == 401 else "forbidden"
        return None, error_response(message, error_status)
    return user, None


def is_play_participant(campaign, username):
    """True if ``username`` is the campaign's DM or one of its party members."""
    if username == campaign["owner"]:
        return True
    return db.get_play_campaign_member(campaign["id"], username) is not None


def authenticate(request):
    """Resolve the ``Authorization: Bearer session-<username>`` header to a user record, or None."""
    username = _session_username(request)
    if username is None:
        return None
    return db.get_user(username)


def _session_username(request):
    """Extract the username from a well-formed ``Bearer session-<username>`` header, or None."""
    header = request.headers.get("Authorization", "")
    if not header.startswith(BEARER_PREFIX):
        return None
    token = header[len(BEARER_PREFIX):]
    if not token.startswith(SESSION_PREFIX):
        return None
    username = token[len(SESSION_PREFIX):]
    if not username:
        return None
    return username


def authenticate_play(request):
    """Resolve a play-surface actor.

    Returns ``(user, error_status)``. A missing/malformed token yields
    ``(None, 401)``. A well-formed token for an unregistered username yields
    ``(None, 403)`` — the play surface treats "not a known campaign member"
    as forbidden rather than unauthenticated. A valid token yields
    ``(user, None)``.
    """
    username = _session_username(request)
    if username is None:
        return None, 401
    user = db.get_user(username)
    if user is None:
        return None, 403
    return user, None
