"""Campaign-scoped safety boundaries and accepted safety events."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from ..db import (
    _append_safety_event,
    _get_safety_boundaries,
    _get_safety_event_by_id,
    _list_safety_events,
    _set_safety_boundaries,
    db_conn,
)
from ..http import bad_request, conflict, parse_json, require_method
from .common import (
    require_play_campaign_dm_owner,
    require_play_campaign_member_or_owner,
)


def _validate_tag_list(value, required=True):
    """Validate a list of tags for safety boundaries/events.

    Returns the normalized list on success, or raises ValueError on failure.
    """
    if not isinstance(value, list):
        raise ValueError("tags must be an array")
    if required and not value:
        raise ValueError("tags must be nonempty")
    seen = set()
    for tag in value:
        if not isinstance(tag, str) or not tag.strip():
            raise ValueError("tags must be nonempty strings")
        if tag in seen:
            raise ValueError("tags must be unique")
        seen.add(tag)
    return value


def _boundary_response(tags):
    """Build a sorted safety-boundary response dict."""
    return JsonResponse({"blocked_tags": sorted(tags)})


@csrf_exempt
def safety_boundaries(request, id):
    """GET/PUT /v1/play/campaigns/{id}/safety-boundaries"""
    if request.method == "PUT":
        return _replace_safety_boundaries(request, id)
    if request.method == "GET":
        return _get_safety_boundaries_view(request, id)
    return require_method(request, "GET", "PUT")


def _replace_safety_boundaries(request, id):
    """PUT /v1/play/campaigns/{id}/safety-boundaries"""
    err = require_method(request, "PUT")
    if err is not None:
        return err

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")

    try:
        tags = body["blocked_tags"]
        tags = _validate_tag_list(tags, required=True)
    except (KeyError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        _set_safety_boundaries(conn, id, tags)
        stored_tags = _get_safety_boundaries(conn, id)

    return _boundary_response(stored_tags)


def _get_safety_boundaries_view(request, id):
    """GET /v1/play/campaigns/{id}/safety-boundaries"""
    err = require_method(request, "GET")
    if err is not None:
        return err

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        stored_tags = _get_safety_boundaries(conn, id)
        if stored_tags is None:
            stored_tags = []

    return _boundary_response(stored_tags)


@csrf_exempt
def submit_safety_check(request, id):
    """POST /v1/play/campaigns/{id}/safety-checks"""
    err = require_method(request, "POST")
    if err is not None:
        return err

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")

    try:
        event_id = body["event_id"]
        kind = body["kind"]
        text = body["text"]
        tags = body["tags"]
        if not isinstance(event_id, str) or not event_id:
            raise ValueError
        if not isinstance(text, str) or not text:
            raise ValueError
        if kind not in ("narration", "chat"):
            raise ValueError
        tags = _validate_tag_list(tags, required=True)
    except (KeyError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        existing = _get_safety_event_by_id(conn, id, event_id)
        if existing is not None:
            return conflict("event_id already exists")

        blocked_tags = _get_safety_boundaries(conn, id) or []
        blocked_set = set(blocked_tags)
        for tag in tags:
            if tag in blocked_set:
                return conflict("blocked tag")

        sequence = _append_safety_event(conn, id, event_id, kind, text, tags)

    return JsonResponse(
        {
            "event_id": event_id,
            "kind": kind,
            "text": text,
            "tags": tags,
            "sequence": sequence,
        },
        status=201,
    )


@csrf_exempt
def get_safety_events(request, id):
    """GET /v1/play/campaigns/{id}/safety-events"""
    err = require_method(request, "GET")
    if err is not None:
        return err

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        events = _list_safety_events(conn, id)

    return JsonResponse({"events": events})
