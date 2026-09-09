"""Campaign-scoped deterministic fixture seeding views."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from ..db import _get_fixture_seed, _seed_fixture, db_conn
from ..http import bad_request, not_found, parse_json, require_method
from .common import require_play_campaign_dm_owner, require_play_campaign_member_or_owner


CANONICAL_FIXTURE_ID = "canonical-v1"


def _build_fixture_response(fixture_id):
    """Return the deterministic fixture state for the seeded fixture."""
    return {
        "fixture_id": fixture_id,
        "status": "seeded",
        "characters": [
            {"character_id": "fixture-hero", "name": "Ari", "class": "fighter"},
            {"character_id": "fixture-mage", "name": "Bea", "class": "wizard"},
        ],
        "story": "The lantern is lit.",
        "event_ids": ["fixture-event-1", "fixture-event-2"],
    }


@csrf_exempt
def fixture_seeds(request, id):
    """POST /v1/play/campaigns/{id}/fixture-seeds"""
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
        fixture_id = body["fixture_id"]
        if not isinstance(fixture_id, str) or fixture_id != CANONICAL_FIXTURE_ID:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        existing = _get_fixture_seed(conn, id)
        if existing is not None:
            return JsonResponse(_build_fixture_response(existing["fixture_id"]), status=200)
        _seed_fixture(conn, id, fixture_id)

    return JsonResponse(_build_fixture_response(fixture_id), status=201)


@csrf_exempt
def fixture_state(request, id):
    """GET /v1/play/campaigns/{id}/fixture-state"""
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        existing = _get_fixture_seed(conn, id)
        if existing is None:
            return not_found("fixture state not found")

    return JsonResponse(_build_fixture_response(existing["fixture_id"]))
