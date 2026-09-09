"""DM-only campaign import snapshots."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_play_campaign_dm_owner
from ..http import bad_request, not_found, parse_json, require_method
from ..db import db_conn, _apply_play_campaign_import, _get_play_campaign_import


def _validate_import_body(body):
    """Return (version, story, status) or None if body is invalid."""
    if not isinstance(body, dict):
        return None
    try:
        version = body["version"]
        story = body["story"]
        status = body["status"]
    except (KeyError, TypeError):
        return None
    if not isinstance(version, int) or version != 1:
        return None
    if not isinstance(story, str) or not story:
        return None
    if status not in ("lobby", "started"):
        return None
    return version, story, status


@csrf_exempt
def create_import(request, id):
    """POST /v1/play/campaigns/{id}/imports"""
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")

    validated = _validate_import_body(body)
    if validated is None:
        return bad_request("invalid request")

    version, story, status = validated

    with db_conn() as conn:
        _apply_play_campaign_import(conn, id, version, story, status)

    return JsonResponse({"version": version, "story": story, "status": status})


@csrf_exempt
def get_import_state(request, id):
    """GET /v1/play/campaigns/{id}/import-state"""
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        imported = _get_play_campaign_import(conn, id)

    if imported is None:
        return not_found("import state not found")

    return JsonResponse(
        {
            "version": imported["version"],
            "story": imported["story"],
            "status": imported["status"],
        }
    )
