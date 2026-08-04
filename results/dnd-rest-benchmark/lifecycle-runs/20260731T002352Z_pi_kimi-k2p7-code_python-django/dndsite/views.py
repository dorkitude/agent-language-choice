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

from .http import bad_request, conflict, forbidden, not_found, parse_json, require_method, unauthorized

from .constants import DICE_RE, SCHEMA_VERSION, USERNAME_RE
from .db import (
    _add_inventory_item,
    _assign_equipment,
    _get_inventory_summary,
    db_conn,
    is_initialized,
    reset_storage,
)
from .domain import (
    ability_modifier as compute_ability_modifier,
    build_initiative_order,
    compute_encounter_xp,
    encounter_recommendation,
    parse_combatant,
    proficiency_bonus,
)


# ---------------------------------------------------------------------------
# Health & storage
# ---------------------------------------------------------------------------

def health(request):
    return JsonResponse({"ok": True})


@csrf_exempt
def storage_status(request):
    bad = require_method(request, "GET")
    if bad:
        return bad
    return JsonResponse(
        {
            "driver": "sqlite",
            "schema_version": SCHEMA_VERSION,
            "initialized": is_initialized(),
        }
    )


@csrf_exempt
def storage_reset(request):
    bad = require_method(request, "POST")
    if bad:
        return bad
    reset_storage()
    return JsonResponse({"ok": True, "schema_version": SCHEMA_VERSION})


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@csrf_exempt
def register(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        username = body["username"]
        password = body["password"]
        role = body["role"]
        if not all(isinstance(v, str) for v in (username, password, role)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if not USERNAME_RE.match(username):
        return bad_request("invalid username")
    if len(password) < 8:
        return bad_request("password too short")
    if role not in ("dm", "player"):
        return bad_request("invalid role")

    try:
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, make_password(password), role),
            )
    except sqlite3.IntegrityError:
        return conflict("username already exists")

    return JsonResponse({"username": username, "role": role}, status=201)


@csrf_exempt
def login(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        username = body["username"]
        password = body["password"]
        if not isinstance(username, str) or not isinstance(password, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()

    if row is None or not check_password(password, row["password_hash"]):
        return unauthorized("invalid credentials")

    return JsonResponse({"username": username, "token": f"session-{username}"})


def _get_actor(request):
    """Validate the Authorization Bearer token and return the actor.

    A well-formed ``Bearer session-<username>`` token is treated as a valid
    actor. If the username is known in the users table its stored role is
    used; otherwise the actor is assumed to be a player. Missing or
    malformed tokens return ``None`` so the caller can respond with 401.
    """
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        return None
    token = header[7:]
    if not token.startswith("session-"):
        return None
    username = token[8:]
    with db_conn() as conn:
        row = conn.execute(
            "SELECT username, role FROM users WHERE username = ?", (username,)
        ).fetchone()
    if row is None:
        return {"username": username, "role": "player"}
    return {"username": row["username"], "role": row["role"]}


# ---------------------------------------------------------------------------
# Core mechanics
# ---------------------------------------------------------------------------

@csrf_exempt
def dice_stats(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        expr = body["expression"]
    except (KeyError, TypeError):
        return bad_request("invalid request")

    match = DICE_RE.match(str(expr))
    if not match:
        return bad_request("invalid expression")

    count = int(match.group("count"))
    sides = int(match.group("sides"))
    mod = match.group("mod")

    if count <= 0 or sides <= 0:
        return bad_request("count and sides must be positive")

    modifier = 0 if mod is None else int(mod)

    average = count * (sides + 1) / 2 + modifier
    average = int(average) if average == int(average) else average

    return JsonResponse(
        {
            "dice_count": count,
            "sides": sides,
            "modifier": modifier,
            "min": count + modifier,
            "max": count * sides + modifier,
            "average": average,
        }
    )


@csrf_exempt
def ability_check(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        roll = int(body["roll"])
        modifier = int(body["modifier"])
        dc = int(body["dc"])
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    total = roll + modifier
    return JsonResponse({"total": total, "success": total >= dc, "margin": total - dc})


@csrf_exempt
def adjusted_xp(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        party = body["party"]
        monsters = body["monsters"]
    except (KeyError, TypeError):
        return bad_request("invalid request")

    try:
        result = compute_encounter_xp(party, monsters)
    except ValueError as exc:
        return bad_request(str(exc))

    return JsonResponse(
        {
            "base_xp": result["base_xp"],
            "monster_count": result["monster_count"],
            "multiplier": result["multiplier"],
            "adjusted_xp": result["adjusted_xp"],
            "difficulty": result["difficulty"],
            "thresholds": result["thresholds"],
        }
    )


@csrf_exempt
def initiative_order(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        combatants = body["combatants"]
    except (KeyError, TypeError):
        return bad_request("invalid request")

    try:
        parsed = [parse_combatant(c) for c in combatants]
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid combatant")

    return JsonResponse({"order": build_initiative_order(parsed)})


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------

@csrf_exempt
def ability_modifier(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        score = body["score"]
        if not isinstance(score, int) or score < 1 or score > 30:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    return JsonResponse({"score": score, "modifier": compute_ability_modifier(score)})


@csrf_exempt
def proficiency(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        level = body["level"]
        if not isinstance(level, int) or level < 1 or level > 20:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    return JsonResponse({"level": level, "proficiency_bonus": proficiency_bonus(level)})


@csrf_exempt
def derived_stats(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        level = body["level"]
        abilities = body["abilities"]
        armor = body["armor"]

        if not isinstance(level, int) or level < 1 or level > 20:
            raise ValueError

        ability_names = ["str", "dex", "con", "int", "wis", "cha"]
        modifiers = {}
        for name in ability_names:
            score = abilities[name]
            if not isinstance(score, int) or score < 1 or score > 30:
                raise ValueError
            modifiers[name] = compute_ability_modifier(score)

        base = armor["base"]
        dex_cap = armor["dex_cap"]
        shield = armor["shield"]
        if not isinstance(base, int) or not isinstance(dex_cap, int) or not isinstance(shield, bool):
            raise ValueError

        shield_bonus = 2 if shield else 0
        armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus
        hp_max = level * (6 + modifiers["con"])
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    return JsonResponse(
        {
            "level": level,
            "proficiency_bonus": proficiency_bonus(level),
            "hp_max": hp_max,
            "armor_class": armor_class,
            "modifiers": modifiers,
        }
    )


# ---------------------------------------------------------------------------
# Combat
# ---------------------------------------------------------------------------

@csrf_exempt
def create_combat_session(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        session_id = body["id"]
        combatants = body["combatants"]
        if not isinstance(session_id, str) or not isinstance(combatants, list) or not combatants:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    try:
        parsed = [parse_combatant(c) for c in combatants]
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid combatant")

    order = build_initiative_order(parsed)
    conditions = {c["name"]: [] for c in parsed}

    try:
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO combat_sessions (id, round, turn_index, order_json, conditions_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, 1, 0, json.dumps(order), json.dumps(conditions)),
            )
    except sqlite3.IntegrityError:
        return bad_request("session already exists")

    return JsonResponse(
        {
            "id": session_id,
            "round": 1,
            "turn_index": 0,
            "active": order[0],
            "order": order,
        }
    )


@csrf_exempt
def add_condition(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        target = str(body["target"])
        condition = str(body["condition"])
        duration = int(body["duration_rounds"])
        if duration <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        row = conn.execute(
            "SELECT conditions_json FROM combat_sessions WHERE id = ?", (id,)
        ).fetchone()
        if row is None:
            return not_found("session not found")

        conditions = json.loads(row["conditions_json"])
        if target not in conditions:
            return bad_request("invalid target")

        conditions[target].append({"condition": condition, "remaining_rounds": duration})
        conn.execute(
            "UPDATE combat_sessions SET conditions_json = ? WHERE id = ?",
            (json.dumps(conditions), id),
        )

    return JsonResponse({"target": target, "conditions": conditions[target]})


@csrf_exempt
def advance_turn(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    with db_conn() as conn:
        row = conn.execute(
            "SELECT round, turn_index, order_json, conditions_json FROM combat_sessions WHERE id = ?",
            (id,),
        ).fetchone()
        if row is None:
            return not_found("session not found")

        round_num = row["round"]
        turn_index = row["turn_index"]
        order = json.loads(row["order_json"])
        conditions = json.loads(row["conditions_json"])

        turn_index += 1
        if turn_index >= len(order):
            turn_index = 0
            round_num += 1

        active = order[turn_index]
        # Conditions on the active combatant decrement at the start of its turn.
        active_conditions = conditions[active["name"]]
        new_conditions = []
        for cond in active_conditions:
            cond["remaining_rounds"] -= 1
            if cond["remaining_rounds"] > 0:
                new_conditions.append(cond)
        conditions[active["name"]] = new_conditions

        conn.execute(
            "UPDATE combat_sessions SET round = ?, turn_index = ?, conditions_json = ? WHERE id = ?",
            (round_num, turn_index, json.dumps(conditions), id),
        )

    return JsonResponse(
        {
            "id": id,
            "round": round_num,
            "turn_index": turn_index,
            "active": active,
            "conditions": {name: list(conds) for name, conds in conditions.items()},
        }
    )


# ---------------------------------------------------------------------------
# Compendium
# ---------------------------------------------------------------------------

@csrf_exempt
def create_monster(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        slug = body["slug"]
        name = body["name"]
        cr = body["cr"]
        armor_class = body["armor_class"]
        hit_points = body["hit_points"]
        tags = body["tags"]
        if not isinstance(slug, str) or not isinstance(name, str):
            raise ValueError
        if not isinstance(cr, str) and not isinstance(cr, int):
            raise ValueError
        if not isinstance(armor_class, int) or not isinstance(hit_points, int):
            raise ValueError
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    try:
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (slug, name, str(cr), armor_class, hit_points, json.dumps(tags)),
            )
    except sqlite3.IntegrityError:
        return conflict("monster already exists")

    return JsonResponse(
        {
            "slug": slug,
            "name": name,
            "cr": str(cr),
            "armor_class": armor_class,
            "hit_points": hit_points,
        },
        status=201,
    )


@csrf_exempt
def get_monster(request, slug):
    bad = require_method(request, "GET")
    if bad:
        return bad

    with db_conn() as conn:
        row = conn.execute(
            "SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters WHERE slug = ?",
            (slug,),
        ).fetchone()
    if row is None:
        return not_found("monster not found")

    return JsonResponse(
        {
            "slug": row["slug"],
            "name": row["name"],
            "cr": row["cr"],
            "armor_class": row["armor_class"],
            "hit_points": row["hit_points"],
            "tags": json.loads(row["tags_json"]),
        }
    )


@csrf_exempt
def create_item(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        slug = body["slug"]
        name = body["name"]
        item_type = body["type"]
        rarity = body["rarity"]
        cost_gp = body["cost_gp"]
        if not isinstance(slug, str) or not isinstance(name, str):
            raise ValueError
        if not isinstance(item_type, str) or not isinstance(rarity, str):
            raise ValueError
        if not isinstance(cost_gp, int):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    try:
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
                (slug, name, item_type, rarity, cost_gp),
            )
    except sqlite3.IntegrityError:
        return conflict("item already exists")

    return JsonResponse(
        {
            "slug": slug,
            "name": name,
            "type": item_type,
            "rarity": rarity,
            "cost_gp": cost_gp,
        },
        status=201,
    )


@csrf_exempt
def get_item(request, slug):
    bad = require_method(request, "GET")
    if bad:
        return bad

    with db_conn() as conn:
        row = conn.execute(
            "SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?", (slug,)
        ).fetchone()
    if row is None:
        return not_found("item not found")

    return JsonResponse(
        {
            "slug": row["slug"],
            "name": row["name"],
            "type": row["type"],
            "rarity": row["rarity"],
            "cost_gp": row["cost_gp"],
        }
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
# PHB rules
# ---------------------------------------------------------------------------

@csrf_exempt
def spell_slots(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        character_class = body["class"]
        level = body["level"]
        if not isinstance(character_class, str) or not isinstance(level, int):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if character_class != "wizard" or level != 5:
        return bad_request("unsupported class or level")

    return JsonResponse(
        {
            "class": character_class,
            "level": level,
            "slots": {"1": 4, "2": 3, "3": 2},
        }
    )


@csrf_exempt
def long_rest(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        level = int(body["level"])
        hp_current = int(body["hp_current"])
        hp_max = int(body["hp_max"])
        hit_dice_spent = int(body["hit_dice_spent"])
        exhaustion_level = int(body["exhaustion_level"])
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if level < 1 or hp_max < 1 or hp_current < 0 or hit_dice_spent < 0 or exhaustion_level < 0:
        return bad_request("invalid request")

    restored = max(1, level // 2)
    new_hit_dice_spent = max(0, hit_dice_spent - restored)
    new_exhaustion = max(0, exhaustion_level - 1)

    return JsonResponse(
        {
            "hp_current": hp_max,
            "hit_dice_spent": new_hit_dice_spent,
            "exhaustion_level": new_exhaustion,
        }
    )


@csrf_exempt
def equipment_load(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        strength = int(body["strength"])
        weight = int(body["weight"])
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if strength < 1 or weight < 0:
        return bad_request("invalid request")

    capacity = strength * 15
    return JsonResponse(
        {"capacity": capacity, "weight": weight, "encumbered": weight > capacity}
    )


# ---------------------------------------------------------------------------
# DM tools
# ---------------------------------------------------------------------------

@csrf_exempt
def encounter_builder(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        campaign_id = body["campaign_id"]
        party = body["party"]
        monster_slugs = body["monster_slugs"]
        if not isinstance(campaign_id, str) or not isinstance(party, list) or not isinstance(monster_slugs, list):
            raise ValueError
        if not all(isinstance(s, str) for s in monster_slugs):
            raise ValueError
        if not all(isinstance(m, dict) and isinstance(m.get("level"), int) for m in party):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        # Aggregate duplicate slugs into counts.
        slug_counts = {}
        for slug in monster_slugs:
            slug_counts[slug] = slug_counts.get(slug, 0) + 1

        monsters = []
        for slug, count in slug_counts.items():
            row = conn.execute("SELECT cr FROM monsters WHERE slug = ?", (slug,)).fetchone()
            if row is None:
                return bad_request("monster not found")
            monsters.append({"cr": row["cr"], "count": count})

    try:
        result = compute_encounter_xp(party, monsters)
    except ValueError:
        return bad_request("invalid request")

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "base_xp": result["base_xp"],
            "adjusted_xp": result["adjusted_xp"],
            "difficulty": result["difficulty"],
            "monster_count": result["monster_count"],
            "recommendation": encounter_recommendation(result["difficulty"]),
        }
    )


@csrf_exempt
def loot_parcel(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        campaign_id = body["campaign_id"]
        tier = body["tier"]
        if not isinstance(campaign_id, str) or not isinstance(tier, int):
            raise ValueError
        if tier < 1:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

    if tier != 1:
        return bad_request("unsupported tier")

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "coins_gp": 75,
            "items": [{"slug": "healing-potion", "quantity": 2}],
        }
    )


@csrf_exempt
def session_recap(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        campaign_id = body["campaign_id"]
        if not isinstance(campaign_id, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute("SELECT id FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        event = conn.execute(
            "SELECT summary FROM campaign_events WHERE campaign_id = ? ORDER BY id DESC LIMIT 1",
            (campaign_id,),
        ).fetchone()

    if event is None:
        summary = "No recent events."
        open_threads = []
    else:
        summary = event["summary"]
        last_words = " ".join(summary.rstrip(".").split()[-2:])
        open_threads = [f"Resolve {last_words} ambush"]

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "summary": summary,
            "open_threads": open_threads,
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


# ---------------------------------------------------------------------------
# Play campaigns
# ---------------------------------------------------------------------------

@csrf_exempt
def create_play_campaign(request):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")
    if actor["role"] != "dm":
        return forbidden()

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
                "INSERT INTO play_campaigns (id, name, owner, status, max_players) "
                "VALUES (?, ?, ?, ?, ?)",
                (campaign_id, name, actor["username"], "lobby", max_players),
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

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")
    if actor["role"] != "player":
        return forbidden("only players may join")

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
            "SELECT character_id FROM play_campaign_members WHERE character_id = ?",
            (character_id,),
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
                "INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class_name, sequence, hp_current, hp_max) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (id, actor["username"], character_id, name, character_class, next_sequence, 20, 20),
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

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner, status FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["role"] != "dm" or actor["username"] != campaign["owner"]:
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
            "UPDATE play_campaigns SET status = ?, current_actor = ?, turn_number = ? WHERE id = ?",
            ("active", first_member["username"], 1, id),
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

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")
    if actor["role"] != "dm":
        return forbidden()

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
        if actor["username"] != campaign["owner"]:
            return forbidden()

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM narrations WHERE campaign_id = ?",
            (id,),
        ).fetchone()["next_sequence"]

        conn.execute(
            "INSERT INTO narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
            (id, next_sequence, "narration", "dm", text),
        )

    return JsonResponse(
        {
            "sequence": next_sequence,
            "kind": "narration",
            "actor": "dm",
            "text": text,
        },
        status=201,
    )


@csrf_exempt
def get_play_turn(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner, status, current_actor, turn_number FROM play_campaigns WHERE id = ?",
            (id,),
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        is_member = conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (id, actor["username"]),
        ).fetchone() is not None

        if actor["username"] != campaign["owner"] and not is_member:
            return forbidden()

        members = conn.execute(
            "SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY sequence ASC",
            (id,),
        ).fetchall()

    # The turn queue is deterministic: each player is followed by the DM,
    # so a full round cycles through the party in order and returns to the DM.
    queue = []
    for member in members:
        queue.extend([member["username"], campaign["owner"]])

    current_actor = campaign["current_actor"]
    if current_actor is None:
        phase = campaign["status"]
    elif current_actor == campaign["owner"]:
        phase = "dm"
    else:
        phase = "player"

    return JsonResponse(
        {
            "campaign_id": campaign["id"],
            "current_actor": current_actor,
            "phase": phase,
            "turn_number": campaign["turn_number"],
            "queue": queue,
            "overdue": False,
            "logical_deadline": campaign["turn_number"],
        }
    )


@csrf_exempt
def nudge_play_turn(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        message = body["message"]
        if not isinstance(message, str) or not message:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner, current_actor, nudge_count FROM play_campaigns WHERE id = ?",
            (id,),
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

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

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")
    if actor["role"] != "player":
        return forbidden("only players may view their turn")

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

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner, current_actor FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

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

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

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

        next_actor = campaign["owner"]
        next_turn_number = campaign["turn_number"] + 1
        conn.execute(
            "UPDATE play_campaigns SET current_actor = ?, turn_number = ? WHERE id = ?",
            (next_actor, next_turn_number, id),
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

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

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
            "SELECT id, owner, status, current_actor, turn_number FROM play_campaigns WHERE id = ?",
            (id,),
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["role"] != "dm":
            return conflict("not your turn")

        if actor["username"] != campaign["owner"]:
            return forbidden()

        if campaign["current_actor"] != campaign["owner"]:
            return conflict("not your turn")

        members = conn.execute(
            "SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY sequence ASC",
            (id,),
        ).fetchall()

        queue = []
        for member in members:
            queue.extend([member["username"], campaign["owner"]])

        if not queue:
            return conflict("not your turn")

        # turn_number is 1-based; the actor at index turn_number-1 is the one
        # who is currently expected to act. After resolving, advance to the
        # actor at the next index (turn_number), wrapping around the queue.
        current_index = (campaign["turn_number"] - 1) % len(queue)
        if queue[current_index] != campaign["owner"]:
            return conflict("not your turn")

        next_actor = queue[campaign["turn_number"] % len(queue)]
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
            "turn_number": campaign["turn_number"] // 2 + 1,
        },
        status=201,
    )


@csrf_exempt
def campaign_document(request, id):
    bad = require_method(request, "GET", "PUT")
    if bad:
        return bad

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner, story, dm_notes FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        is_owner = actor["username"] == campaign["owner"]
        is_member = (
            conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (id, actor["username"]),
            ).fetchone()
            is not None
        )

        if not is_owner and not is_member:
            return forbidden()

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

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM narrations WHERE campaign_id = ?",
            (id,),
        ).fetchone()["next_sequence"]

        conn.execute(
            "INSERT INTO narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
            (id, next_sequence, "document", actor["username"], story),
        )

    return JsonResponse({"story": story, "dm_notes": dm_notes})


# ---------------------------------------------------------------------------
# Scene state
# ---------------------------------------------------------------------------

@csrf_exempt
def create_scene(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        scene_id = body["id"]
        name = body["name"]
        if not isinstance(scene_id, str) or not isinstance(name, str):
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

        try:
            conn.execute(
                "INSERT INTO scenes (campaign_id, scene_id, name, status) VALUES (?, ?, ?, ?)",
                (id, scene_id, name, "open"),
            )
        except sqlite3.IntegrityError:
            return conflict("scene already exists")

    return JsonResponse({"id": scene_id, "name": name, "status": "open"}, status=201)


@csrf_exempt
def enter_scene(request, id, scene_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

        scene = conn.execute(
            "SELECT scene_id, name, status FROM scenes WHERE campaign_id = ? AND scene_id = ?",
            (id, scene_id),
        ).fetchone()
        if scene is None:
            return not_found("scene not found")

        if scene["status"] == "closed":
            return conflict("scene is closed")

        conn.execute(
            "UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?",
            (scene_id, id),
        )

    return JsonResponse({"current_scene_id": scene_id, "name": scene["name"]})


@csrf_exempt
def close_scene(request, id, scene_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

        scene = conn.execute(
            "SELECT scene_id FROM scenes WHERE campaign_id = ? AND scene_id = ?",
            (id, scene_id),
        ).fetchone()
        if scene is None:
            return not_found("scene not found")

        conn.execute(
            "UPDATE scenes SET status = ? WHERE campaign_id = ? AND scene_id = ?",
            ("closed", id, scene_id),
        )
        conn.execute(
            "UPDATE play_campaigns SET current_scene_id = NULL WHERE id = ? AND current_scene_id = ?",
            (id, scene_id),
        )

    return JsonResponse({"id": scene_id, "status": "closed"})


@csrf_exempt
def get_current_scene(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner, current_scene_id FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        is_member = (
            conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (id, actor["username"]),
            ).fetchone()
            is not None
        )

        if actor["username"] != campaign["owner"] and not is_member:
            return forbidden()

        if campaign["current_scene_id"] is None:
            return not_found("scene not found")

        scene = conn.execute(
            "SELECT scene_id, name, status FROM scenes WHERE campaign_id = ? AND scene_id = ?",
            (id, campaign["current_scene_id"]),
        ).fetchone()
        if scene is None or scene["status"] != "open":
            return not_found("scene not found")

    return JsonResponse(
        {"id": scene["scene_id"], "name": scene["name"], "status": scene["status"]}
    )


# ---------------------------------------------------------------------------
# Location graph
# ---------------------------------------------------------------------------

@csrf_exempt
def create_location(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        location_id = body["id"]
        name = body["name"]
        if not isinstance(location_id, str) or not isinstance(name, str):
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

        try:
            conn.execute(
                "INSERT INTO locations (campaign_id, location_id, name) VALUES (?, ?, ?)",
                (id, location_id, name),
            )
        except sqlite3.IntegrityError:
            return conflict("location already exists")

        conn.execute(
            "UPDATE play_campaigns SET current_location_id = ? WHERE id = ? AND current_location_id IS NULL",
            (location_id, id),
        )

    return JsonResponse({"id": location_id, "name": name}, status=201)


@csrf_exempt
def create_connection(request, id, from_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        to_id = body["to_id"]
        travel_turns = body["travel_turns"]
        if not isinstance(to_id, str) or not isinstance(travel_turns, int):
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

        from_loc = conn.execute(
            "SELECT 1 FROM locations WHERE campaign_id = ? AND location_id = ?",
            (id, from_id),
        ).fetchone()
        if from_loc is None:
            return bad_request("invalid location")

        to_loc = conn.execute(
            "SELECT 1 FROM locations WHERE campaign_id = ? AND location_id = ?",
            (id, to_id),
        ).fetchone()
        if to_loc is None:
            return bad_request("invalid destination")

        existing = conn.execute(
            "SELECT 1 FROM location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
            (id, from_id, to_id),
        ).fetchone()
        if existing is not None:
            return bad_request("connection already exists")

        conn.execute(
            "INSERT INTO location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)",
            (id, from_id, to_id, travel_turns),
        )

    return JsonResponse(
        {"from_id": from_id, "to_id": to_id, "travel_turns": travel_turns}, status=201
    )


@csrf_exempt
def get_valid_travel(request, id, loc_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        is_member = (
            conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (id, actor["username"]),
            ).fetchone()
            is not None
        )

        if actor["username"] != campaign["owner"] and not is_member:
            return forbidden()

        location = conn.execute(
            "SELECT 1 FROM locations WHERE campaign_id = ? AND location_id = ?",
            (id, loc_id),
        ).fetchone()
        if location is None:
            return not_found("location not found")

        rows = conn.execute(
            """
            SELECT l.location_id, l.name, c.travel_turns
            FROM location_connections c
            JOIN locations l ON l.campaign_id = c.campaign_id AND l.location_id = c.to_id
            WHERE c.campaign_id = ? AND c.from_id = ?
            ORDER BY l.location_id ASC
            """,
            (id, loc_id),
        ).fetchall()

    destinations = [
        {"id": row["location_id"], "name": row["name"], "travel_turns": row["travel_turns"]}
        for row in rows
    ]

    return JsonResponse({"destinations": destinations})


@csrf_exempt
def travel_turn(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        destination_id = body["destination_id"]
        if not isinstance(destination_id, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner, status, current_actor, turn_number, current_location_id "
            "FROM play_campaigns WHERE id = ?",
            (id,),
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        is_member = (
            conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (id, actor["username"]),
            ).fetchone()
            is not None
        )

        if actor["username"] != campaign["owner"] and not is_member:
            return forbidden()

        if actor["role"] == "dm" or actor["username"] != campaign["current_actor"]:
            return conflict("not your turn")

        connection = conn.execute(
            "SELECT travel_turns FROM location_connections "
            "WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
            (id, campaign["current_location_id"], destination_id),
        ).fetchone()
        if connection is None:
            return conflict("invalid destination")

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM narrations WHERE campaign_id = ?",
            (id,),
        ).fetchone()["next_sequence"]

        conn.execute(
            "INSERT INTO narrations (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (id, next_sequence, "travel", actor["username"], destination_id),
        )

        next_actor = campaign["owner"]
        next_turn_number = campaign["turn_number"] + 1
        conn.execute(
            "UPDATE play_campaigns SET current_actor = ?, turn_number = ?, current_location_id = ? "
            "WHERE id = ?",
            (next_actor, next_turn_number, destination_id, id),
        )

    return JsonResponse(
        {
            "sequence": next_sequence,
            "kind": "travel",
            "actor": actor["username"],
            "destination_id": destination_id,
            "travel_turns": connection["travel_turns"],
            "next_actor": next_actor,
        },
        status=201,
    )


@csrf_exempt
def rest_turn(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor = _get_actor(request)
    if actor is None:
        return unauthorized("invalid credentials")

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        rest_type = body["type"]
        if not isinstance(rest_type, str) or rest_type not in ("short", "long"):
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

        is_member = (
            conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (id, actor["username"]),
            ).fetchone()
            is not None
        )

        if actor["username"] != campaign["owner"] and not is_member:
            return forbidden()

        if actor["role"] == "dm" or actor["username"] != campaign["current_actor"]:
            return conflict("not your turn")

        member = conn.execute(
            "SELECT character_id, hp_current, hp_max FROM play_campaign_members "
            "WHERE campaign_id = ? AND username = ?",
            (id, actor["username"]),
        ).fetchone()

        hp_current = member["hp_current"]
        hp_max = member["hp_max"]

        if rest_type == "long":
            hp_current = hp_max
            conn.execute(
                "UPDATE play_campaign_members SET hp_current = ? WHERE campaign_id = ? AND username = ?",
                (hp_current, id, actor["username"]),
            )

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM narrations WHERE campaign_id = ?",
            (id,),
        ).fetchone()["next_sequence"]

        conn.execute(
            "INSERT INTO narrations (campaign_id, sequence, kind, type, actor, text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (id, next_sequence, "rest", rest_type, actor["username"], ""),
        )

        next_actor = campaign["owner"]
        next_turn_number = campaign["turn_number"] + 1
        conn.execute(
            "UPDATE play_campaigns SET current_actor = ?, turn_number = ? WHERE id = ?",
            (next_actor, next_turn_number, id),
        )

    return JsonResponse(
        {
            "sequence": next_sequence,
            "kind": "rest",
            "actor": actor["username"],
            "type": rest_type,
            "hp_current": hp_current,
            "hp_max": hp_max,
            "next_actor": next_actor,
        },
        status=201,
    )
