"""Django views for the D&D REST API.

Each view is a thin layer over the ``domain`` and ``db`` modules. Common
request parsing and response helpers live in ``dndsite.http``. Validation
failures return 400, missing resources 404, and conflicts 409. Error message
strings are preserved from the original implementation to maintain exact
response bodies.
"""

import json
import sqlite3

from django.contrib.auth.hashers import check_password, make_password
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from ..http import bad_request, conflict, forbidden, not_found, parse_json, require_method, unauthorized

from ..constants import (
    DICE_RE,
    HIT_DICE,
    SCHEMA_VERSION,
    SKILL_ABILITIES,
    USERNAME_RE,
    VALID_BACKGROUNDS,
    VALID_CLASSES,
    VALID_RACES,
)
from ..db import (
    _add_inventory_item,
    _assign_equipment,
    _get_inventory_summary,
    db_conn,
    is_initialized,
    reset_storage,
)
from ..domain import (
    ability_modifier as compute_ability_modifier,
    avg_hit_die,
    build_initiative_order,
    compute_encounter_xp,
    encounter_recommendation,
    parse_combatant,
    proficiency_bonus,
    skill_check_modifier,
)

# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


@csrf_exempt
def create_campaign(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        campaign_id = body["id"]
        name = body["name"]
        dm = body["dm"]
        if not all(isinstance(v, str) for v in (campaign_id, name, dm)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    try:
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
                (campaign_id, name, dm),
            )
    except sqlite3.IntegrityError:
        return conflict("campaign already exists")

    return JsonResponse({"id": campaign_id, "name": name, "dm": dm}, status=201)


@csrf_exempt
def add_character(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        character_id = body["id"]
        name = body["name"]
        level = body["level"]
        character_class = body["class"]
        if not all(isinstance(v, str) for v in (character_id, name, character_class)):
            raise ValueError
        if not isinstance(level, int) or level < 1 or level > 20:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        try:
            conn.execute(
                "INSERT INTO campaign_characters (id, campaign_id, name, level, class_name) "
                "VALUES (?, ?, ?, ?, ?)",
                (character_id, id, name, level, character_class),
            )
        except sqlite3.IntegrityError:
            return conflict("character already exists")

    return JsonResponse(
        {"id": character_id, "name": name, "level": level, "class": character_class},
        status=201,
    )


@csrf_exempt
def add_event(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        event_id = body["id"]
        kind = body["kind"]
        summary = body["summary"]
        if not all(isinstance(v, str) for v in (event_id, kind, summary)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        try:
            conn.execute(
                "INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)",
                (event_id, id, kind, summary),
            )
        except sqlite3.IntegrityError:
            return conflict("event already exists")

    return JsonResponse({"id": event_id, "kind": kind}, status=201)


@csrf_exempt
def get_campaign_state(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, name, dm FROM campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        characters = conn.execute(
            "SELECT id, name, level, class_name FROM campaign_characters "
            "WHERE campaign_id = ? ORDER BY id",
            (id,),
        ).fetchall()

        log_count = conn.execute(
            "SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?", (id,)
        ).fetchone()["count"]

    return JsonResponse(
        {
            "id": campaign["id"],
            "name": campaign["name"],
            "dm": campaign["dm"],
            "characters": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "level": row["level"],
                    "class": row["class_name"],
                }
                for row in characters
            ],
            "log_count": log_count,
        }
    )


@csrf_exempt
def create_quest(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        quest_id = body["id"]
        title = body["title"]
        status = body["status"]
        milestones = body["milestones"]
        if not all(isinstance(v, str) for v in (quest_id, title, status)):
            raise ValueError
        if status not in ("active", "completed", "blocked"):
            raise ValueError
        if not isinstance(milestones, list) or not all(isinstance(m, str) for m in milestones):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if status == "completed":
            completed_milestones = list(milestones)
        else:
            completed_milestones = []

        try:
            conn.execute(
                "INSERT INTO quests (id, campaign_id, title, status, milestones_json, completed_milestones_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (quest_id, id, title, status, json.dumps(milestones), json.dumps(completed_milestones)),
            )
        except sqlite3.IntegrityError:
            return conflict("quest already exists")

    return JsonResponse(
        {
            "id": quest_id,
            "title": title,
            "status": status,
            "milestones_total": len(milestones),
            "milestones_done": len(completed_milestones),
        },
        status=201,
    )


@csrf_exempt
def update_quest_progress(request, id, quest_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        completed = body["completed"]
        if not isinstance(completed, list) or not all(isinstance(m, str) for m in completed):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        row = conn.execute(
            "SELECT status, milestones_json, completed_milestones_json FROM quests "
            "WHERE id = ? AND campaign_id = ?",
            (quest_id, id),
        ).fetchone()
        if row is None:
            return not_found("quest not found")

        milestones = json.loads(row["milestones_json"])
        completed_milestones = set(json.loads(row["completed_milestones_json"]))

        for milestone in completed:
            if milestone not in milestones:
                return bad_request("invalid request")
            completed_milestones.add(milestone)

        completed_milestones = list(completed_milestones)
        if len(milestones) > 0 and len(completed_milestones) == len(milestones):
            status = "completed"
        elif len(completed_milestones) > 0:
            status = "active"
        else:
            status = row["status"]

        conn.execute(
            "UPDATE quests SET status = ?, completed_milestones_json = ? WHERE id = ?",
            (status, json.dumps(completed_milestones), quest_id),
        )

    return JsonResponse(
        {
            "id": quest_id,
            "status": status,
            "milestones_total": len(milestones),
            "milestones_done": len(completed_milestones),
        }
    )


@csrf_exempt
def quest_summary(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        rows = conn.execute(
            "SELECT status FROM quests WHERE campaign_id = ?", (id,)
        ).fetchall()

    counts = {"active": 0, "completed": 0, "blocked": 0}
    for row in rows:
        if row["status"] in counts:
            counts[row["status"]] += 1

    return JsonResponse(
        {
            "campaign_id": id,
            "active": counts["active"],
            "completed": counts["completed"],
            "blocked": counts["blocked"],
        }
    )


@csrf_exempt
def create_faction(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        faction_id = body["id"]
        name = body["name"]
        stance = body["stance"]
        if not all(isinstance(v, str) for v in (faction_id, name, stance)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        try:
            conn.execute(
                "INSERT INTO factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)",
                (faction_id, id, name, stance),
            )
        except sqlite3.IntegrityError:
            return conflict("faction already exists")

    return JsonResponse({"id": faction_id, "name": name, "stance": stance}, status=201)


@csrf_exempt
def create_npc(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        npc_id = body["id"]
        name = body["name"]
        faction_id = body["faction_id"]
        disposition = body["disposition"]
        if not all(isinstance(v, str) for v in (npc_id, name, faction_id)):
            raise ValueError
        if not isinstance(disposition, int):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        faction = conn.execute(
            "SELECT id FROM factions WHERE id = ? AND campaign_id = ?",
            (faction_id, id),
        ).fetchone()
        if faction is None:
            return bad_request("invalid request")

        try:
            conn.execute(
                "INSERT INTO npcs (id, campaign_id, name, faction_id, disposition) "
                "VALUES (?, ?, ?, ?, ?)",
                (npc_id, id, name, faction_id, disposition),
            )
        except sqlite3.IntegrityError:
            return conflict("npc already exists")

    return JsonResponse(
        {"id": npc_id, "name": name, "faction_id": faction_id, "disposition": disposition},
        status=201,
    )


@csrf_exempt
def relationship_summary(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        faction_count = conn.execute(
            "SELECT COUNT(*) AS count FROM factions WHERE campaign_id = ?", (id,)
        ).fetchone()["count"]

        npc_count = conn.execute(
            "SELECT COUNT(*) AS count FROM npcs WHERE campaign_id = ?", (id,)
        ).fetchone()["count"]

        friendly_npc_count = conn.execute(
            "SELECT COUNT(*) AS count FROM npcs WHERE campaign_id = ? AND disposition >= 1",
            (id,),
        ).fetchone()["count"]

    return JsonResponse(
        {
            "campaign_id": id,
            "factions": faction_count,
            "npcs": npc_count,
            "friendly_npcs": friendly_npc_count,
        }
    )


@csrf_exempt
def add_inventory_item(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        item_slug = body["item_slug"]
        quantity = body["quantity"]
        owner = body["owner"]
        if (
            not isinstance(item_slug, str)
            or not isinstance(owner, str)
            or not isinstance(quantity, int)
            or quantity <= 0
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")
        new_quantity = _add_inventory_item(conn, id, item_slug, quantity, owner)

    return JsonResponse(
        {"item_slug": item_slug, "quantity": new_quantity, "owner": owner}, status=201
    )


@csrf_exempt
def assign_equipment(request, id, character_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        item_slug = body["item_slug"]
        quantity = body["quantity"]
        if not isinstance(item_slug, str) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        character = conn.execute(
            "SELECT id FROM campaign_characters WHERE id = ? AND campaign_id = ?",
            (character_id, id),
        ).fetchone()
        if character is None:
            return not_found("character not found")

        try:
            _assign_equipment(conn, id, character_id, item_slug, quantity)
        except ValueError as exc:
            return bad_request(str(exc))

    return JsonResponse(
        {"character_id": character_id, "item_slug": item_slug, "quantity": quantity}
    )


@csrf_exempt
def inventory_summary(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")
        summary = _get_inventory_summary(conn, id)

    return JsonResponse({"campaign_id": id, **summary})



# ---------------------------------------------------------------------------
# Downtime crafting
# ---------------------------------------------------------------------------


@csrf_exempt
def create_crafting_project(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        project_id = body["id"]
        character_id = body["character_id"]
        item_slug = body["item_slug"]
        days_required = body["days_required"]
        cost_gp = body["cost_gp"]
        if not all(isinstance(v, str) for v in (project_id, character_id, item_slug)):
            raise ValueError
        if not isinstance(days_required, int) or days_required <= 0:
            raise ValueError
        if not isinstance(cost_gp, int) or cost_gp < 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        character = conn.execute(
            "SELECT id FROM campaign_characters WHERE id = ? AND campaign_id = ?",
            (character_id, id),
        ).fetchone()
        if character is None:
            return not_found("character not found")

        try:
            conn.execute(
                "INSERT INTO crafting_projects (id, campaign_id, character_id, item_slug, days_required, days_completed, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, id, character_id, item_slug, days_required, 0, "active"),
            )
        except sqlite3.IntegrityError:
            return conflict("project already exists")

    return JsonResponse(
        {
            "id": project_id,
            "character_id": character_id,
            "item_slug": item_slug,
            "days_required": days_required,
            "days_completed": 0,
            "status": "active",
        },
        status=201,
    )


@csrf_exempt
def advance_crafting_project(request, id, project_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        days = body["days"]
        if not isinstance(days, int) or days <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        row = conn.execute(
            "SELECT id, item_slug, days_required, days_completed, status FROM crafting_projects "
            "WHERE id = ? AND campaign_id = ?",
            (project_id, id),
        ).fetchone()
        if row is None:
            return not_found("project not found")

        if row["status"] == "complete":
            return bad_request("invalid request")

        days_completed = min(row["days_completed"] + days, row["days_required"])
        status = "complete" if days_completed >= row["days_required"] else "active"

        conn.execute(
            "UPDATE crafting_projects SET days_completed = ?, status = ? WHERE id = ?",
            (days_completed, status, project_id),
        )

        if status == "complete":
            _add_inventory_item(conn, id, row["item_slug"], 1, "party")

    return JsonResponse(
        {
            "id": project_id,
            "days_completed": days_completed,
            "status": status,
        }
    )



# ---------------------------------------------------------------------------
# Session scheduling
# ---------------------------------------------------------------------------


@csrf_exempt
def schedule_session(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        session_id = body["id"]
        starts_at = body["starts_at"]
        duration_minutes = body["duration_minutes"]
        agenda = body["agenda"]
        if not all(isinstance(v, str) for v in (session_id, starts_at)):
            raise ValueError
        if not isinstance(duration_minutes, int):
            raise ValueError
        if not isinstance(agenda, list) or not all(isinstance(a, str) for a in agenda):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        try:
            conn.execute(
                "INSERT INTO sessions (id, campaign_id, starts_at, duration_minutes, agenda_json, attendance_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, id, starts_at, duration_minutes, json.dumps(agenda), json.dumps({})),
            )
        except sqlite3.IntegrityError:
            return conflict("session already exists")

    return JsonResponse(
        {
            "id": session_id,
            "starts_at": starts_at,
            "duration_minutes": duration_minutes,
            "agenda_count": len(agenda),
        },
        status=201,
    )


@csrf_exempt
def record_attendance(request, id, session_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        present = body["present"]
        absent = body["absent"]
        if not isinstance(present, list) or not isinstance(absent, list):
            raise ValueError
        if not all(isinstance(c, str) for c in present + absent):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        row = conn.execute(
            "SELECT id FROM sessions WHERE id = ? AND campaign_id = ?",
            (session_id, id),
        ).fetchone()
        if row is None:
            return not_found("session not found")

        conn.execute(
            "UPDATE sessions SET attendance_json = ? WHERE id = ?",
            (json.dumps({"present": present, "absent": absent}), session_id),
        )

    return JsonResponse(
        {
            "session_id": session_id,
            "present_count": len(present),
            "absent_count": len(absent),
        }
    )


@csrf_exempt
def next_session(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        row = conn.execute(
            "SELECT id, starts_at, agenda_json FROM sessions "
            "WHERE campaign_id = ? ORDER BY starts_at ASC, id ASC LIMIT 1",
            (id,),
        ).fetchone()
        if row is None:
            return not_found("session not found")

    return JsonResponse(
        {
            "id": row["id"],
            "starts_at": row["starts_at"],
            "agenda_count": len(json.loads(row["agenda_json"])),
        }
    )


@csrf_exempt
def campaign_audit(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        events = conn.execute(
            "SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?", (id,)
        ).fetchone()["count"]
        quests = conn.execute(
            "SELECT COUNT(*) AS count FROM quests WHERE campaign_id = ?", (id,)
        ).fetchone()["count"]
        npcs = conn.execute(
            "SELECT COUNT(*) AS count FROM npcs WHERE campaign_id = ?", (id,)
        ).fetchone()["count"]
        sessions = conn.execute(
            "SELECT COUNT(*) AS count FROM sessions WHERE campaign_id = ?", (id,)
        ).fetchone()["count"]

    return JsonResponse(
        {
            "campaign_id": id,
            "events": events,
            "quests": quests,
            "npcs": npcs,
            "sessions": sessions,
        }
    )


@csrf_exempt
def campaign_export(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, name FROM campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        characters = conn.execute(
            "SELECT COUNT(*) AS count FROM campaign_characters WHERE campaign_id = ?", (id,)
        ).fetchone()["count"]
        quests = conn.execute(
            "SELECT COUNT(*) AS count FROM quests WHERE campaign_id = ?", (id,)
        ).fetchone()["count"]
        npcs = conn.execute(
            "SELECT COUNT(*) AS count FROM npcs WHERE campaign_id = ?", (id,)
        ).fetchone()["count"]
        inventory_items = conn.execute(
            "SELECT COUNT(DISTINCT item_slug) AS count FROM inventory WHERE campaign_id = ?", (id,)
        ).fetchone()["count"]
        sessions = conn.execute(
            "SELECT COUNT(*) AS count FROM sessions WHERE campaign_id = ?", (id,)
        ).fetchone()["count"]

    return JsonResponse(
        {
            "campaign_id": campaign["id"],
            "name": campaign["name"],
            "characters": characters,
            "quests": quests,
            "npcs": npcs,
            "inventory_items": inventory_items,
            "sessions": sessions,
            "schema_version": SCHEMA_VERSION,
        }
    )



# ---------------------------------------------------------------------------
# Campaign analytics
# ---------------------------------------------------------------------------


@csrf_exempt
def campaign_analytics_summary(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        open_quests = conn.execute(
            "SELECT COUNT(*) AS count FROM quests WHERE campaign_id = ? AND status = ?",
            (id, "active"),
        ).fetchone()["count"]

        friendly_npcs = conn.execute(
            "SELECT COUNT(*) AS count FROM npcs WHERE campaign_id = ? AND disposition >= 1",
            (id,),
        ).fetchone()["count"]

        scheduled_sessions = conn.execute(
            "SELECT COUNT(*) AS count FROM sessions WHERE campaign_id = ?",
            (id,),
        ).fetchone()["count"]

        inventory_items = conn.execute(
            "SELECT COUNT(DISTINCT item_slug) AS count FROM inventory WHERE campaign_id = ?",
            (id,),
        ).fetchone()["count"]

    readiness_score = max(0, 100 - (5 * open_quests) - (5 * scheduled_sessions) - (5 * inventory_items))

    return JsonResponse(
        {
            "campaign_id": id,
            "readiness_score": readiness_score,
            "open_quests": open_quests,
            "friendly_npcs": friendly_npcs,
            "scheduled_sessions": scheduled_sessions,
            "inventory_items": inventory_items,
        }
    )


@csrf_exempt
def campaign_risk_report(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    if not isinstance(body, dict):
        return bad_request("invalid request")
    include_zeroes = body.get("include_zeroes")
    if include_zeroes is not None and not isinstance(include_zeroes, bool):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT dm FROM campaigns WHERE id = ?", (id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        has_dm = bool(campaign["dm"])

        character_count = conn.execute(
            "SELECT COUNT(*) AS count FROM campaign_characters WHERE campaign_id = ?",
            (id,),
        ).fetchone()["count"]
        has_characters = character_count > 0

        session_count = conn.execute(
            "SELECT COUNT(*) AS count FROM sessions WHERE campaign_id = ?",
            (id,),
        ).fetchone()["count"]
        has_next_session = session_count > 0

        active_quest_count = conn.execute(
            "SELECT COUNT(*) AS count FROM quests WHERE campaign_id = ? AND status = ?",
            (id, "active"),
        ).fetchone()["count"]
        has_active_quest = active_quest_count > 0

    signals = {
        "has_dm": has_dm,
        "has_characters": has_characters,
        "has_next_session": has_next_session,
        "has_active_quest": has_active_quest,
    }

    missing = [name for name in signals if not signals[name]]
    missing_count = len(missing)

    if missing_count == 0:
        risk_level = "low"
    elif missing_count == 1:
        risk_level = "medium"
    elif missing_count == 2:
        risk_level = "high"
    else:
        risk_level = "critical"

    return JsonResponse(
        {
            "campaign_id": id,
            "risk_level": risk_level,
            "missing": missing,
            "signals": signals,
        }
    )



