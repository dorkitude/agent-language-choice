"""Content tag views for live-play campaigns."""

import json
import sqlite3

from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_play_campaign_dm_owner, require_play_campaign_member_or_owner
from ..http import bad_request, conflict, not_found, parse_json, require_method
from ..db import db_conn


@csrf_exempt
def content(request, id):
    if request.method == "POST":
        return create_content(request, id)
    if request.method == "GET":
        return list_content(request, id)
    return HttpResponseBadRequest()


@csrf_exempt
def create_content(request, id):
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
        content_id = body["content_id"]
        kind = body["kind"]
        text = body["text"]
        tags = body["tags"]
        if not all(isinstance(v, str) and v for v in (content_id, kind, text)):
            raise ValueError
        if not isinstance(tags, list) or not tags:
            raise ValueError
        seen = set()
        for tag in tags:
            if not isinstance(tag, str) or not tag:
                raise ValueError
            if tag in seen:
                raise ValueError
            seen.add(tag)
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    try:
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO play_content (campaign_id, content_id, kind, text, tags_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (id, content_id, kind, text, json.dumps(tags)),
            )
    except sqlite3.IntegrityError:
        return conflict("content already exists")

    return JsonResponse(
        {"content_id": content_id, "kind": kind, "text": text, "tags": tags},
        status=201,
    )


@csrf_exempt
def update_content_tags(request, id, content_id):
    bad = require_method(request, "PUT")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        tags = body["tags"]
        if not isinstance(tags, list):
            raise ValueError
        seen = set()
        for tag in tags:
            if not isinstance(tag, str) or not tag:
                raise ValueError
            if tag in seen:
                raise ValueError
            seen.add(tag)
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        row = conn.execute(
            "SELECT kind, text, tags_json FROM play_content "
            "WHERE campaign_id = ? AND content_id = ?",
            (id, content_id),
        ).fetchone()
        if row is None:
            return not_found("content not found")

        conn.execute(
            "UPDATE play_content SET tags_json = ? WHERE campaign_id = ? AND content_id = ?",
            (json.dumps(tags), id, content_id),
        )

    return JsonResponse(
        {"content_id": content_id, "kind": row["kind"], "text": row["text"], "tags": tags}
    )


@csrf_exempt
def list_content(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    exclude_tag = request.GET.get("exclude_tag")
    if exclude_tag == "":
        return bad_request("invalid request")

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT content_id, kind, text, tags_json FROM play_content "
            "WHERE campaign_id = ? ORDER BY id ASC",
            (id,),
        ).fetchall()

    items = []
    for row in rows:
        tags = json.loads(row["tags_json"])
        if (
            actor["username"] != campaign["owner"]
            and exclude_tag is not None
            and exclude_tag in tags
        ):
            continue
        items.append(
            {
                "content_id": row["content_id"],
                "kind": row["kind"],
                "text": row["text"],
                "tags": tags,
            }
        )

    return JsonResponse({"content": items})
