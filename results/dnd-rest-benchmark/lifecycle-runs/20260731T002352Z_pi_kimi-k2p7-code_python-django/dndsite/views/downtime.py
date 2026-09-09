"""Django views for recurring downtime activities and allocations."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import (
    require_actor,
    require_play_campaign_member_or_owner,
)
from ..http import (
    bad_request,
    conflict,
    forbidden,
    not_found,
    parse_json,
    require_method,
)
from ..db import db_conn


def _nonempty_string(value):
    return isinstance(value, str) and value != ""


def _valid_cycles(value):
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 1 <= value <= 10
    )


@csrf_exempt
def create_downtime_activity(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "dm")
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        activity_id = body["activity_id"]
        name = body["name"]
        cycles_required = body["cycles_required"]
        if not (
            _nonempty_string(activity_id)
            and _nonempty_string(name)
            and _valid_cycles(cycles_required)
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

        existing = conn.execute(
            "SELECT 1 FROM downtime_activities WHERE campaign_id = ? AND activity_id = ?",
            (id, activity_id),
        ).fetchone()
        if existing is not None:
            return conflict("activity already exists")

        conn.execute(
            "INSERT INTO downtime_activities (campaign_id, activity_id, name, cycles_required) "
            "VALUES (?, ?, ?, ?)",
            (id, activity_id, name, cycles_required),
        )

    return JsonResponse(
        {
            "activity_id": activity_id,
            "name": name,
            "cycles_required": cycles_required,
        },
        status=201,
    )


@csrf_exempt
def create_downtime_allocation(request, id, character_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "player", "only players may allocate")
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        activity_id = body["activity_id"]
        if not _nonempty_string(activity_id):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        member = conn.execute(
            "SELECT username, character_id FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, character_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        if actor["username"] != member["username"]:
            return forbidden()

        activity = conn.execute(
            "SELECT activity_id FROM downtime_activities "
            "WHERE campaign_id = ? AND activity_id = ?",
            (id, activity_id),
        ).fetchone()
        if activity is None:
            return not_found("activity not found")

        existing = conn.execute(
            "SELECT 1 FROM downtime_allocations "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (id, character_id, activity_id),
        ).fetchone()
        if existing is not None:
            return conflict("allocation already exists")

        conn.execute(
            "INSERT INTO downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) "
            "VALUES (?, ?, ?, 0, 0)",
            (id, character_id, activity_id),
        )

    return JsonResponse(
        {
            "character_id": character_id,
            "activity_id": activity_id,
            "cycles_completed": 0,
            "completions": 0,
        },
        status=201,
    )


@csrf_exempt
def progress_downtime_allocation(request, id, character_id, activity_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "player", "only players may progress")
    if err is not None:
        return err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        member = conn.execute(
            "SELECT username, character_id FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, character_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        if actor["username"] != member["username"]:
            return forbidden()

        activity = conn.execute(
            "SELECT activity_id, cycles_required FROM downtime_activities "
            "WHERE campaign_id = ? AND activity_id = ?",
            (id, activity_id),
        ).fetchone()
        if activity is None:
            return not_found("activity not found")

        alloc = conn.execute(
            "SELECT cycles_completed, completions FROM downtime_allocations "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (id, character_id, activity_id),
        ).fetchone()
        if alloc is None:
            return not_found("allocation not found")

        cycles_completed = alloc["cycles_completed"] + 1
        completions = alloc["completions"]
        if cycles_completed >= activity["cycles_required"]:
            cycles_completed = 0
            completions += 1

        conn.execute(
            "UPDATE downtime_allocations SET cycles_completed = ?, completions = ? "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (cycles_completed, completions, id, character_id, activity_id),
        )

    return JsonResponse(
        {
            "character_id": character_id,
            "activity_id": activity_id,
            "cycles_completed": cycles_completed,
            "completions": completions,
        }
    )


@csrf_exempt
def get_downtime_allocation(request, id, character_id, activity_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        member = conn.execute(
            "SELECT 1 FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, character_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        activity = conn.execute(
            "SELECT 1 FROM downtime_activities "
            "WHERE campaign_id = ? AND activity_id = ?",
            (id, activity_id),
        ).fetchone()
        if activity is None:
            return not_found("activity not found")

        alloc = conn.execute(
            "SELECT cycles_completed, completions FROM downtime_allocations "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (id, character_id, activity_id),
        ).fetchone()
        if alloc is None:
            return not_found("allocation not found")

    return JsonResponse(
        {
            "character_id": character_id,
            "activity_id": activity_id,
            "cycles_completed": alloc["cycles_completed"],
            "completions": alloc["completions"],
        }
    )
