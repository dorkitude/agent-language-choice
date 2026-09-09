"""Live-play campaign quest dependency views."""

import json
import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import (
    require_play_campaign_dm_owner,
    require_play_campaign_member_or_owner,
)
from .inventory import VALID_ITEM_IDS
from ..http import bad_request, conflict, not_found, parse_json, require_method
from ..db import (
    _configure_quest_rewards,
    _grant_quest_rewards_to_member,
    _is_quest_awarded,
    _record_quest_award,
    db_conn,
)


VALID_STATES = {"active", "completed"}


def _quest_record(row):
    record = {
        "quest_id": row["quest_id"],
        "title": row["title"],
        "depends_on": json.loads(row["depends_on_json"]),
        "state": row["state"],
    }
    try:
        rewards_json = row["rewards_json"]
    except (KeyError, IndexError):
        rewards_json = None
    if rewards_json and rewards_json != '{}':
        try:
            record["rewards"] = json.loads(rewards_json)
        except (json.JSONDecodeError, TypeError):
            pass
    return record


@csrf_exempt
def play_quests(request, id):
    bad = require_method(request, "GET", "POST")
    if bad:
        return bad
    if request.method == "POST":
        return _create_play_quest(request, id)
    return _list_play_quests(request, id)


def _create_play_quest(request, id):
    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")

    try:
        quest_id = body["quest_id"]
        title = body["title"]
        depends_on = body["depends_on"]
        if not isinstance(quest_id, str) or not quest_id:
            raise ValueError
        if not isinstance(title, str) or not title:
            raise ValueError
        if not isinstance(depends_on, list):
            raise ValueError
        if any(not isinstance(d, str) or not d for d in depends_on):
            raise ValueError
        if len(depends_on) != len(set(depends_on)):
            raise ValueError
        if quest_id in depends_on:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        if depends_on:
            placeholders = ",".join("?" * len(depends_on))
            rows = conn.execute(
                f"SELECT quest_id FROM play_quests "
                f"WHERE campaign_id = ? AND quest_id IN ({placeholders})",
                (id, *depends_on),
            ).fetchall()
            found = {row["quest_id"] for row in rows}
            if found != set(depends_on):
                return bad_request("invalid request")

        try:
            conn.execute(
                "INSERT INTO play_quests (campaign_id, quest_id, title, depends_on_json, state) "
                "VALUES (?, ?, ?, ?, ?)",
                (id, quest_id, title, json.dumps(depends_on), "locked"),
            )
        except sqlite3.IntegrityError:
            return conflict("quest already exists")

    return JsonResponse(
        {
            "quest_id": quest_id,
            "title": title,
            "depends_on": depends_on,
            "state": "locked",
        },
        status=201,
    )


@csrf_exempt
def update_play_quest_state(request, id, quest_id):
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
        new_state = body["state"]
        if new_state not in VALID_STATES:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, title, depends_on_json, state, rewards_json FROM play_quests "
            "WHERE campaign_id = ? AND quest_id = ?",
            (id, quest_id),
        ).fetchone()
        if row is None:
            return not_found("quest not found")

        current_state = row["state"]
        depends_on = json.loads(row["depends_on_json"])
        allowed = False

        if current_state == "locked" and new_state == "active":
            if depends_on:
                placeholders = ",".join("?" * len(depends_on))
                dep_rows = conn.execute(
                    f"SELECT quest_id, state FROM play_quests "
                    f"WHERE campaign_id = ? AND quest_id IN ({placeholders})",
                    (id, *depends_on),
                ).fetchall()
                dep_states = {r["quest_id"]: r["state"] for r in dep_rows}
                if len(dep_states) != len(depends_on):
                    return conflict("invalid transition")
                if all(dep_states[d] == "completed" for d in depends_on):
                    allowed = True
            else:
                allowed = True
        elif current_state == "active" and new_state == "completed":
            allowed = True

        if not allowed:
            return conflict("invalid transition")

        conn.execute(
            "UPDATE play_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?",
            (new_state, id, quest_id),
        )

        record = {
            "quest_id": quest_id,
            "title": row["title"],
            "depends_on": depends_on,
            "state": new_state,
        }
        rewards_json = row["rewards_json"]
        if rewards_json and rewards_json != '{}':
            try:
                record["rewards"] = json.loads(rewards_json)
            except (json.JSONDecodeError, TypeError):
                pass

        return JsonResponse(record)


def _list_play_quests(request, id):
    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT quest_id, title, depends_on_json, state, rewards_json FROM play_quests "
            "WHERE campaign_id = ? ORDER BY id",
            (id,),
        ).fetchall()

    return JsonResponse({"quests": [_quest_record(row) for row in rows]})


@csrf_exempt
def configure_quest_rewards(request, id, quest_id):
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
        xp = body["xp"]
        items = body["items"]
        if not isinstance(xp, int) or isinstance(xp, bool) or xp < 0:
            raise ValueError
        if not isinstance(items, dict):
            raise ValueError
        if any(not isinstance(k, str) or k not in VALID_ITEM_IDS for k in items.keys()):
            raise ValueError
        if any(not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in items.values()):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    rewards = {"xp": xp, "items": items}

    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, title, depends_on_json, state, rewards_json FROM play_quests "
            "WHERE campaign_id = ? AND quest_id = ?",
            (id, quest_id),
        ).fetchone()
        if row is None:
            return not_found("quest not found")

        if row["state"] == "completed":
            return conflict("quest already completed")

        _configure_quest_rewards(conn, id, quest_id, rewards)

    return JsonResponse(
        {
            "quest_id": quest_id,
            "title": row["title"],
            "depends_on": json.loads(row["depends_on_json"]),
            "state": row["state"],
            "rewards": rewards,
        }
    )


@csrf_exempt
def award_quest_rewards(request, id, quest_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, title, depends_on_json, state, rewards_json FROM play_quests "
            "WHERE campaign_id = ? AND quest_id = ?",
            (id, quest_id),
        ).fetchone()
        if row is None:
            return not_found("quest not found")

        if row["state"] != "completed":
            return conflict("quest not completed")

        rewards_json = row["rewards_json"]
        if not rewards_json or rewards_json == '{}':
            return conflict("rewards not configured")

        try:
            rewards = json.loads(rewards_json)
        except (json.JSONDecodeError, TypeError):
            return conflict("rewards not configured")

        xp = rewards.get("xp", 0)
        items = rewards.get("items", {})

        if _is_quest_awarded(conn, id, quest_id):
            return conflict("rewards already awarded")

        members = conn.execute(
            "SELECT character_id FROM play_campaign_members WHERE campaign_id = ?",
            (id,),
        ).fetchall()

        for member in members:
            _grant_quest_rewards_to_member(conn, id, member["character_id"], xp, items)

        _record_quest_award(conn, id, quest_id)

    return JsonResponse(
        {
            "quest_id": quest_id,
            "awarded": True,
            "xp": xp,
            "items": items,
        },
        status=201,
    )


@csrf_exempt
def get_character_quest_rewards(request, id, character_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        member = conn.execute(
            "SELECT character_id, quest_rewards_xp, quest_rewards_items_json "
            "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (id, character_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

    return JsonResponse(
        {
            "character_id": member["character_id"],
            "xp": member["quest_rewards_xp"],
            "items": json.loads(member["quest_rewards_items_json"]),
        }
    )
