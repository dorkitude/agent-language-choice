"""DM-only immutable campaign export snapshots."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_play_campaign_dm_owner
from ..http import bad_request, not_found, parse_json, require_method
from ..db import (
    db_conn,
    _create_play_campaign_export,
    _get_play_campaign_export,
    _list_play_campaign_exports,
)


@csrf_exempt
def create_export(request, id):
    """POST /v1/play/campaigns/{id}/exports"""
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    # The request body is expected to be empty; tolerate optional valid JSON.
    if request.body:
        body = parse_json(request)
        if body is None:
            return bad_request("invalid request")

    with db_conn() as conn:
        version = _create_play_campaign_export(
            conn,
            campaign_id=id,
            story=campaign["story"],
            status=campaign["status"],
        )

    return JsonResponse(
        {"version": version, "story": campaign["story"], "status": campaign["status"]},
        status=201,
    )


@csrf_exempt
def list_exports(request, id):
    """GET /v1/play/campaigns/{id}/exports"""
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        exports = _list_play_campaign_exports(conn, id)

    return JsonResponse({"exports": exports})


@csrf_exempt
def exports(request, id):
    """Dispatch POST/GET for /v1/play/campaigns/{id}/exports."""
    if request.method == "POST":
        return create_export(request, id)
    if request.method == "GET":
        return list_exports(request, id)
    return bad_request("invalid request")


@csrf_exempt
def get_export(request, id, version):
    """GET /v1/play/campaigns/{id}/exports/{version}"""
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    try:
        version = int(version)
    except (ValueError, TypeError):
        return not_found("export not found")

    with db_conn() as conn:
        export = _get_play_campaign_export(conn, id, version)

    if export is None:
        return not_found("export not found")

    return JsonResponse(
        {"version": export["version"], "story": export["story"], "status": export["status"]}
    )
