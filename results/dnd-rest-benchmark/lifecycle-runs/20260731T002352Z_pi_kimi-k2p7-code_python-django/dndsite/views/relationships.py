"""Relationship graph views for live-play campaigns."""

import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import (
    require_play_campaign_dm_owner,
    require_play_campaign_member_or_owner,
)

from ..http import bad_request, conflict, not_found, parse_json, require_method

from ..db import db_conn


def _entity_exists(conn, campaign_id, entity_id):
    """Return True if entity_id is a member character or NPC in the campaign."""
    member = conn.execute(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
        (campaign_id, entity_id),
    ).fetchone()
    if member is not None:
        return True
    npc = conn.execute(
        "SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
        (campaign_id, entity_id),
    ).fetchone()
    return npc is not None


@csrf_exempt
def relationships_list(request, id):
    bad = require_method(request, "GET", "POST")
    if bad:
        return bad

    if request.method == "POST":
        return _create_relationship(request, id)
    return _list_relationships(request, id)


def _create_relationship(request, id):
    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        source_id = body["source_id"]
        target_id = body["target_id"]
        kind = body["kind"]
        score = body["score"]
        if not isinstance(source_id, str) or not isinstance(target_id, str) or not isinstance(kind, str):
            raise ValueError
        if not kind:
            raise ValueError
        if isinstance(score, bool) or not isinstance(score, int):
            raise ValueError
        if score < -100 or score > 100:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if source_id == target_id:
        return bad_request("invalid request")

    with db_conn() as conn:
        if not _entity_exists(conn, id, source_id):
            return not_found("entity not found")
        if not _entity_exists(conn, id, target_id):
            return not_found("entity not found")

        try:
            conn.execute(
                "INSERT INTO play_relationships (campaign_id, source_id, target_id, kind, score) "
                "VALUES (?, ?, ?, ?, ?)",
                (id, source_id, target_id, kind, score),
            )
        except sqlite3.IntegrityError:
            return conflict("relationship already exists")

    return JsonResponse(
        {
            "source_id": source_id,
            "target_id": target_id,
            "kind": kind,
            "score": score,
        },
        status=201,
    )


def _list_relationships(request, id):
    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT source_id, target_id, kind, score FROM play_relationships "
            "WHERE campaign_id = ? ORDER BY id",
            (id,),
        ).fetchall()

    edges = [
        {
            "source_id": row["source_id"],
            "target_id": row["target_id"],
            "kind": row["kind"],
            "score": row["score"],
        }
        for row in rows
    ]

    return JsonResponse({"edges": edges})


@csrf_exempt
def relationship_update(request, id, source_id, target_id, kind):
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
        score = body["score"]
        if isinstance(score, bool) or not isinstance(score, int):
            raise ValueError
        if score < -100 or score > 100:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM play_relationships "
            "WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
            (id, source_id, target_id, kind),
        ).fetchone()
        if row is None:
            return not_found("relationship not found")

        conn.execute(
            "UPDATE play_relationships SET score = ? "
            "WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
            (score, id, source_id, target_id, kind),
        )

    return JsonResponse(
        {
            "source_id": source_id,
            "target_id": target_id,
            "kind": kind,
            "score": score,
        }
    )
