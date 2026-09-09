"""Campaign-scoped search record views with pagination."""

import sqlite3

from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import (
    require_play_campaign_dm_owner,
    require_play_campaign_member_or_owner,
)
from ..http import bad_request, parse_json, require_method
from ..db import db_conn


@csrf_exempt
def search_records(request, id):
    if request.method == "POST":
        return create_search_record(request, id)
    if request.method == "GET":
        return list_search_records(request, id)
    return HttpResponseBadRequest()


@csrf_exempt
def create_search_record(request, id):
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
        record_id = body["record_id"]
        text = body["text"]
        if not isinstance(record_id, str) or not record_id:
            raise ValueError
        if not isinstance(text, str) or not text:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_search_records WHERE campaign_id = ? AND record_id = ?",
            (id, record_id),
        ).fetchone()
        if existing is not None:
            return bad_request("invalid request")

        duplicate_text = conn.execute(
            "SELECT 1 FROM play_search_records WHERE campaign_id = ? AND LOWER(text) = LOWER(?)",
            (id, text),
        ).fetchone()
        if duplicate_text is not None:
            return bad_request("invalid request")

        try:
            conn.execute(
                "INSERT INTO play_search_records (campaign_id, record_id, text) "
                "VALUES (?, ?, ?)",
                (id, record_id, text),
            )
        except sqlite3.IntegrityError:
            return bad_request("invalid request")

    return JsonResponse(
        {"record_id": record_id, "text": text},
        status=201,
    )


@csrf_exempt
def list_search_records(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    q = request.GET.get("q")
    limit = request.GET.get("limit", "2")
    cursor = request.GET.get("cursor", "0")

    try:
        limit_value = int(limit)
        if not 1 <= limit_value <= 3:
            raise ValueError
        cursor_value = int(cursor)
        if cursor_value < 0:
            raise ValueError
    except (TypeError, ValueError):
        return bad_request("invalid request")

    if q is not None and not isinstance(q, str):
        return bad_request("invalid request")

    params = [id]
    where_clause = "WHERE campaign_id = ?"
    if q:
        where_clause += " AND LOWER(text) LIKE LOWER(?)"
        params.append(f"%{q}%")

    with db_conn() as conn:
        rows = conn.execute(
            f"SELECT record_id, text FROM play_search_records {where_clause} ORDER BY id ASC",
            params,
        ).fetchall()

    total = len(rows)
    page = rows[cursor_value : cursor_value + limit_value]
    next_cursor = cursor_value + limit_value if cursor_value + limit_value < total else None

    records = [
        {"record_id": row["record_id"], "text": row["text"]}
        for row in page
    ]

    return JsonResponse({"records": records, "next_cursor": next_cursor})
