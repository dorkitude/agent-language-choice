"""DM-only campaign schema migrations."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_play_campaign_dm_owner
from ..http import bad_request, not_found, parse_json, require_method
from ..db import db_conn, _apply_play_campaign_migration, _get_play_campaign_migration


def _validate_migration_body(body):
    """Return story or None if the body is not a valid version-1 snapshot."""
    if not isinstance(body, dict):
        return None
    try:
        schema_version = body["schema_version"]
        story = body["story"]
    except (KeyError, TypeError):
        return None
    if not isinstance(schema_version, int) or schema_version != 1:
        return None
    if not isinstance(story, str) or not story:
        return None
    return story


@csrf_exempt
def create_migration(request, id):
    """POST /v1/play/campaigns/{id}/migrations"""
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")

    story = _validate_migration_body(body)
    if story is None:
        return bad_request("invalid request")

    with db_conn() as conn:
        existing = _get_play_campaign_migration(conn, id)
        if existing is not None:
            if existing["story"] != story:
                return bad_request("invalid request")
            status_code = 200
        else:
            _apply_play_campaign_migration(conn, id, story, campaign["name"])
            status_code = 201

        migrated = _get_play_campaign_migration(conn, id)

    return JsonResponse(
        {
            "schema_version": migrated["schema_version"],
            "story": migrated["story"],
            "campaign_name": migrated["campaign_name"],
        },
        status=status_code,
    )


@csrf_exempt
def get_migration_state(request, id):
    """GET /v1/play/campaigns/{id}/migration-state"""
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        migrated = _get_play_campaign_migration(conn, id)

    if migrated is None:
        return not_found("migration state not found")

    return JsonResponse(
        {
            "schema_version": migrated["schema_version"],
            "story": migrated["story"],
            "campaign_name": migrated["campaign_name"],
        }
    )
