"""Campaign calendar and deterministic weather views."""

import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import (
    require_play_campaign_dm_owner,
    require_play_campaign_member_or_owner,
)
from ..http import bad_request, conflict, not_found, parse_json, require_method
from ..db import db_conn
from ..domain import SEASON_OFFSETS, weather_for


_VALID_SEASONS = set(SEASON_OFFSETS.keys())


def _calendar_record(day, season):
    return {
        "day": day,
        "season": season,
        "weather": weather_for(day, season),
    }


@csrf_exempt
def calendar(request, id):
    """Dispatch GET/POST for the campaign calendar endpoint."""
    bad = require_method(request, "GET", "POST")
    if bad:
        return bad
    if request.method == "POST":
        return create_calendar(request, id)
    return get_calendar(request, id)


@csrf_exempt
def create_calendar(request, id):
    """Initialize the campaign calendar. Only the campaign DM may do this."""
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
        day = body["day"]
        season = body["season"]
        if not isinstance(day, int) or isinstance(day, bool) or day < 1:
            raise ValueError
        if season not in _VALID_SEASONS:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        existing = conn.execute(
            "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?",
            (id,),
        ).fetchone()
        if existing is not None:
            return conflict("calendar already initialized")

        try:
            conn.execute(
                "INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (?, ?, ?)",
                (id, day, season),
            )
        except sqlite3.IntegrityError:
            return conflict("calendar already initialized")

    return JsonResponse(_calendar_record(day, season), status=201)


@csrf_exempt
def get_calendar(request, id):
    """Return the campaign calendar for authenticated members or the DM."""
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        row = conn.execute(
            "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?",
            (id,),
        ).fetchone()

    if row is None:
        return not_found("calendar not found")

    return JsonResponse(_calendar_record(row["day"], row["season"]))


@csrf_exempt
def advance_calendar(request, id):
    """Advance the campaign calendar by a bounded number of days. DM only."""
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
        days = body["days"]
        if not isinstance(days, int) or isinstance(days, bool) or days < 1 or days > 30:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        row = conn.execute(
            "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?",
            (id,),
        ).fetchone()
        if row is None:
            return not_found("calendar not found")

        new_day = row["day"] + days
        conn.execute(
            "UPDATE play_campaign_calendars SET day = ? WHERE campaign_id = ?",
            (new_day, id),
        )

    return JsonResponse(_calendar_record(new_day, row["season"]))
