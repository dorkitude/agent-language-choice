"""Django views for the D&D REST API.

Each view is a thin layer over the ``domain`` and ``db`` modules. Common
request parsing and response helpers live in ``dndsite.http``. Validation
failures return 400, missing resources 404, and conflicts 409. Error message
strings are preserved from the original implementation to maintain exact
response bodies.
"""

import json
import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import (
    can_narrate,
    require_actor,
    require_play_campaign_dm_owner,
    require_play_campaign_member_or_owner,
    require_play_campaign_owner,
)

from ..http import bad_request, conflict, forbidden, not_found, parse_json, require_method

from ..db import (
    _create_play_campaign_backup,
    _get_play_campaign_backup,
    _list_play_campaign_backups,
    db_conn,
)

# ---------------------------------------------------------------------------
# Play campaigns
# ---------------------------------------------------------------------------


@csrf_exempt
def create_play_campaign(request):
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
        campaign_id = body["id"]
        name = body["name"]
        max_players = body["max_players"]
        if not all(isinstance(v, str) for v in (campaign_id, name)):
            raise ValueError
        if not isinstance(max_players, int) or max_players < 1:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    try:
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO play_campaigns (id, name, owner, status, max_players, phase) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, name, actor["username"], "lobby", max_players, "exploration"),
            )
    except sqlite3.IntegrityError:
        return conflict("campaign already exists")

    return JsonResponse(
        {
            "id": campaign_id,
            "name": name,
            "owner": actor["username"],
            "status": "lobby",
            "max_players": max_players,
        },
        status=201,
    )


@csrf_exempt
def join_play_campaign(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "player", "only players may join")
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        character_id = body["character_id"]
        name = body["name"]
        character_class = body["class"]
        if not all(isinstance(v, str) for v in (character_id, name, character_class)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, status, max_players FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if campaign["status"] != "lobby":
            return conflict("campaign not open")

        existing = conn.execute(
            "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (id, actor["username"]),
        ).fetchone()
        if existing is not None:
            return conflict("already a member")

        duplicate_char = conn.execute(
            "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (id, character_id),
        ).fetchone()
        if duplicate_char is not None:
            return conflict("character already exists")

        member_count = conn.execute(
            "SELECT COUNT(*) AS count FROM play_campaign_members WHERE campaign_id = ?",
            (id,),
        ).fetchone()["count"]
        if member_count >= campaign["max_players"]:
            return conflict("party is full")

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM play_campaign_members WHERE campaign_id = ?",
            (id,),
        ).fetchone()["next_sequence"]

        try:
            conn.execute(
                "INSERT INTO play_campaign_members (campaign_id, username, owner, character_id, name, class_name, sequence, hp_current, hp_max, status, death_save_successes, death_save_failures, gold) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (id, actor["username"], actor["username"], character_id, name, character_class, next_sequence, 20, 20, "conscious", 0, 0, 10),
            )
        except sqlite3.IntegrityError:
            return conflict("already a member")

    return JsonResponse(
        {
            "username": actor["username"],
            "character_id": character_id,
            "name": name,
            "class": character_class,
        },
        status=201,
    )


@csrf_exempt
def start_play_campaign(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "dm")
    if err is not None:
        return err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner, status FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

        if campaign["status"] != "lobby":
            return conflict("campaign already started")

        member_count = conn.execute(
            "SELECT COUNT(*) AS count FROM play_campaign_members WHERE campaign_id = ?",
            (id,),
        ).fetchone()["count"]
        if member_count < 2:
            return conflict("not enough party members")

        first_member = conn.execute(
            "SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY sequence ASC LIMIT 1",
            (id,),
        ).fetchone()

        conn.execute(
            "UPDATE play_campaigns SET status = ?, current_actor = ?, turn_number = ?, phase = ?, saved_actor = ?, last_action_actor = ? WHERE id = ?",
            ("active", first_member["username"], 1, "player", None, first_member["username"], id),
        )

    return JsonResponse(
        {
            "id": id,
            "status": "active",
            "current_actor": first_member["username"],
            "turn_number": 1,
        }
    )


@csrf_exempt
def add_narration(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        text = body["text"]
        if not isinstance(text, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if not can_narrate(id, actor["username"], conn):
            return forbidden()

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM narrations WHERE campaign_id = ?",
            (id,),
        ).fetchone()["next_sequence"]

        narrator_actor = "dm" if actor["username"] == campaign["owner"] else actor["username"]

        conn.execute(
            "INSERT INTO narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
            (id, next_sequence, "narration", narrator_actor, text),
        )

    return JsonResponse(
        {
            "sequence": next_sequence,
            "kind": "narration",
            "actor": narrator_actor,
            "text": text,
        },
        status=201,
    )


@csrf_exempt
def get_play_turn(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        members = conn.execute(
            "SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY sequence ASC",
            (id,),
        ).fetchall()

    # The turn queue is deterministic: each player is followed by the DM,
    # so a full round cycles through the party in order and returns to the DM.
    queue = []
    for member in members:
        queue.extend([member["username"], campaign["owner"]])

    return JsonResponse(
        {
            "campaign_id": campaign["id"],
            "current_actor": campaign["current_actor"],
            "phase": campaign["phase"],
            "turn_number": campaign["turn_number"],
            "queue": queue,
            "overdue": False,
            "logical_deadline": campaign["turn_number"] + 1,
        }
    )


@csrf_exempt
def nudge_play_turn(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        message = body["message"]
        if not isinstance(message, str) or not message:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    actor, campaign, err = require_play_campaign_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        nudge_count = (campaign["nudge_count"] or 0) + 1
        conn.execute(
            "UPDATE play_campaigns SET nudge_count = ? WHERE id = ?",
            (nudge_count, id),
        )

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM narrations WHERE campaign_id = ?",
            (id,),
        ).fetchone()["next_sequence"]

        conn.execute(
            "INSERT INTO narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
            (id, next_sequence, "nudge", actor["username"], message),
        )

    return JsonResponse(
        {
            "actor": actor["username"],
            "target": campaign["current_actor"],
            "message": message,
            "nudge_count": nudge_count,
        },
        status=201,
    )


@csrf_exempt
def get_my_turn(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, err = require_actor(request, "player", "only players may view their turn")
    if err is not None:
        return err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, current_actor FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        member = conn.execute(
            "SELECT character_id, name FROM play_campaign_members "
            "WHERE campaign_id = ? AND username = ?",
            (id, actor["username"]),
        ).fetchone()
        if member is None:
            return forbidden()

        rows = conn.execute(
            "SELECT sequence, kind, actor, text FROM narrations "
            "WHERE campaign_id = ? AND kind = ? ORDER BY sequence DESC",
            (id, "narration"),
        ).fetchall()

    events = [
        {"sequence": row["sequence"], "kind": row["kind"], "actor": row["actor"], "text": row["text"]}
        for row in rows
    ]

    return JsonResponse(
        {
            "is_my_turn": campaign["current_actor"] == actor["username"],
            "current_actor": campaign["current_actor"],
            "character": {"id": member["character_id"], "name": member["name"]},
            "recent_events": events,
        }
    )


@csrf_exempt
def get_gm_status(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        members = conn.execute(
            "SELECT username, character_id, name, class_name FROM play_campaign_members "
            "WHERE campaign_id = ? ORDER BY sequence ASC",
            (id,),
        ).fetchall()

        rows = conn.execute(
            "SELECT sequence, kind, actor, text FROM narrations "
            "WHERE campaign_id = ? AND kind = ? ORDER BY sequence DESC",
            (id, "narration"),
        ).fetchall()

    party = [
        {
            "username": row["username"],
            "character_id": row["character_id"],
            "name": row["name"],
            "class": row["class_name"],
        }
        for row in members
    ]

    recent_events = [
        {"sequence": row["sequence"], "kind": row["kind"], "actor": row["actor"], "text": row["text"]}
        for row in rows
    ]

    return JsonResponse(
        {
            "needs_attention": campaign["current_actor"] == campaign["owner"],
            "current_actor": campaign["current_actor"],
            "party": party,
            "recent_events": recent_events,
        }
    )


@csrf_exempt
def submit_action(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        action_type = body["type"]
        text = body["text"]
        if not isinstance(action_type, str) or not isinstance(text, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner, status, current_actor, turn_number FROM play_campaigns WHERE id = ?",
            (id,),
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["role"] == "dm":
            return conflict("not your turn")

        member = conn.execute(
            "SELECT username FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (id, actor["username"]),
        ).fetchone()
        if member is None:
            return forbidden()

        if actor["username"] != campaign["current_actor"]:
            return conflict("not your turn")

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM narrations WHERE campaign_id = ?",
            (id,),
        ).fetchone()["next_sequence"]

        conn.execute(
            "INSERT INTO narrations (campaign_id, sequence, kind, type, actor, text) VALUES (?, ?, ?, ?, ?, ?)",
            (id, next_sequence, "action", action_type, actor["username"], text),
        )

        conn.execute(
            "UPDATE play_campaigns SET current_actor = ?, last_action_actor = ? WHERE id = ?",
            (campaign["owner"], actor["username"], id),
        )

    return JsonResponse(
        {
            "sequence": next_sequence,
            "kind": "action",
            "actor": actor["username"],
            "type": action_type,
            "text": text,
            "next_actor": "dm",
        },
        status=201,
    )


@csrf_exempt
def submit_resolution(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        text = body["text"]
        if not isinstance(text, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        if campaign["current_actor"] != actor["username"]:
            return conflict("not your turn")

        if actor["role"] != "dm" or actor["username"] != campaign["owner"]:
            return forbidden()

        members = conn.execute(
            "SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY sequence ASC",
            (id,),
        ).fetchall()

        if not members:
            return conflict("not your turn")

        usernames = [member["username"] for member in members]
        last_actor = campaign["last_action_actor"]
        if last_actor in usernames:
            next_index = (usernames.index(last_actor) + 1) % len(usernames)
        else:
            next_index = 0
        next_actor = usernames[next_index]
        next_turn_number = campaign["turn_number"] + 1

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM narrations WHERE campaign_id = ?",
            (id,),
        ).fetchone()["next_sequence"]

        conn.execute(
            "INSERT INTO narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
            (id, next_sequence, "resolution", campaign["owner"], text),
        )

        conn.execute(
            "UPDATE play_campaigns SET current_actor = ?, turn_number = ? WHERE id = ?",
            (next_actor, next_turn_number, id),
        )

    return JsonResponse(
        {
            "sequence": next_sequence,
            "kind": "resolution",
            "actor": campaign["owner"],
            "text": text,
            "next_actor": next_actor,
            "turn_number": next_turn_number,
        },
        status=201,
    )


@csrf_exempt
def campaign_onboarding(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    if actor["username"] == campaign["owner"]:
        return JsonResponse(
            {
                "role": "dm",
                "next_steps": ["configure-safety", "invite-players", "start-campaign"],
                "can_mutate": True,
            }
        )

    return JsonResponse(
        {
            "role": "player",
            "next_steps": ["review-party", "take-turn", "submit-action"],
            "can_mutate": True,
        }
    )


@csrf_exempt
def campaign_document(request, id):
    bad = require_method(request, "GET", "PUT")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        is_owner = actor["username"] == campaign["owner"]

        if request.method == "GET":
            if is_owner:
                return JsonResponse(
                    {"story": campaign["story"], "dm_notes": campaign["dm_notes"]}
                )
            return JsonResponse({"story": campaign["story"]})

        # PUT
        if not is_owner:
            return forbidden()

        body = parse_json(request)
        if body is None:
            return bad_request("invalid request")
        try:
            story = body["story"]
            dm_notes = body["dm_notes"]
            if not isinstance(story, str) or not isinstance(dm_notes, str):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return bad_request("invalid request")

        conn.execute(
            "UPDATE play_campaigns SET story = ?, dm_notes = ? WHERE id = ?",
            (story, dm_notes, id),
        )

    return JsonResponse({"story": story, "dm_notes": dm_notes})


@csrf_exempt
def session_zero(request, id):
    bad = require_method(request, "GET", "PUT")
    if bad:
        return bad

    if request.method == "PUT":
        actor, campaign, err = require_play_campaign_dm_owner(request, id)
        if err is not None:
            return err

        body = parse_json(request)
        if body is None:
            return bad_request("invalid request")
        try:
            rules = body["rules"]
            tone = body["tone"]
            consent = body["consent"]
            if not isinstance(rules, str) or not rules:
                raise ValueError
            if not isinstance(tone, str) or not tone:
                raise ValueError
            if not isinstance(consent, list) or not consent:
                raise ValueError
            seen = set()
            for item in consent:
                if not isinstance(item, str) or not item:
                    raise ValueError
                if item in seen:
                    raise ValueError
                seen.add(item)
        except (KeyError, TypeError, ValueError):
            return bad_request("invalid request")

        if campaign["status"] != "lobby":
            return conflict("campaign already started")

        with db_conn() as conn:
            conn.execute(
                "INSERT INTO play_campaign_session_zero (campaign_id, rules, tone, consent_json) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(campaign_id) DO UPDATE SET "
                "rules = excluded.rules, tone = excluded.tone, consent_json = excluded.consent_json",
                (id, rules, tone, json.dumps(consent)),
            )

        return JsonResponse({"rules": rules, "tone": tone, "consent": consent})

    # GET
    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        row = conn.execute(
            "SELECT rules, tone, consent_json FROM play_campaign_session_zero WHERE campaign_id = ?",
            (id,),
        ).fetchone()
        if row is None:
            return not_found("session zero settings not found")

    return JsonResponse(
        {"rules": row["rules"], "tone": row["tone"], "consent": json.loads(row["consent_json"])}
    )


@csrf_exempt
def backups(request, id):
    bad = require_method(request, "GET", "POST")
    if bad:
        return bad
    if request.method == "POST":
        return create_backup(request, id)
    return list_backups(request, id)


@csrf_exempt
def create_backup(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        backup_id = _create_play_campaign_backup(conn, id, campaign["story"], campaign["status"])
        backup = _get_play_campaign_backup(conn, id, backup_id)

    return JsonResponse(
        {
            "backup_id": backup["backup_id"],
            "story": backup["story"],
            "status": backup["status"],
        },
        status=201,
    )


@csrf_exempt
def list_backups(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        backups = _list_play_campaign_backups(conn, id)

    return JsonResponse({"backups": backups})


@csrf_exempt
def restore_backup(request, id, backup_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        backup = _get_play_campaign_backup(conn, id, backup_id)
        if backup is None:
            return not_found("backup not found")

        conn.execute(
            "UPDATE play_campaigns SET story = ?, status = ? WHERE id = ?",
            (backup["story"], backup["status"], id),
        )

    return JsonResponse(
        {
            "backup_id": backup["backup_id"],
            "story": backup["story"],
            "status": backup["status"],
        }
    )


@csrf_exempt
def audit_events(request, id):
    bad = require_method(request, "POST", "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    if request.method == "POST":
        body = parse_json(request)
        if body is None:
            return bad_request("invalid request")
        try:
            kind = body["kind"]
            correlation_id = body["correlation_id"]
            if not isinstance(kind, str) or not kind:
                raise ValueError
            if not isinstance(correlation_id, str) or not correlation_id:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return bad_request("invalid request")

        role = "DM" if actor["username"] == campaign["owner"] else "player"

        with db_conn() as conn:
            next_timestamp = conn.execute(
                "SELECT COALESCE(MAX(timestamp), 0) + 1 AS next_timestamp FROM play_audit_events WHERE campaign_id = ?",
                (id,),
            ).fetchone()["next_timestamp"]

            try:
                conn.execute(
                    "INSERT INTO play_audit_events (campaign_id, timestamp, kind, actor, role, correlation_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (id, next_timestamp, kind, actor["username"], role, correlation_id),
                )
            except sqlite3.IntegrityError:
                return conflict("correlation_id already exists")

        return JsonResponse(
            {
                "kind": kind,
                "actor": actor["username"],
                "role": role,
                "timestamp": next_timestamp,
                "correlation_id": correlation_id,
            },
            status=201,
        )

    # GET
    if actor["username"] != campaign["owner"]:
        return forbidden()

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT kind, actor, role, timestamp, correlation_id FROM play_audit_events "
            "WHERE campaign_id = ? ORDER BY timestamp ASC",
            (id,),
        ).fetchall()

    entries = [
        {
            "kind": row["kind"],
            "actor": row["actor"],
            "role": row["role"],
            "timestamp": row["timestamp"],
            "correlation_id": row["correlation_id"],
        }
        for row in rows
    ]

    return JsonResponse({"entries": entries})



