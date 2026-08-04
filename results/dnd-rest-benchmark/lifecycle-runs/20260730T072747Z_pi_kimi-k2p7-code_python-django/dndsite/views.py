"""HTTP view functions for the D&D REST API.

Views are grouped by domain (auth, combat, characters, compendium, etc.) and
delegate persistence and rules work to the sibling modules in this package.
"""

import re

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dndsite import auth, persistence, rules
from dndsite.validation import _parse_json_body


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def health(request):
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@csrf_exempt
def register(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)

    username = body.get("username")
    password = body.get("password")
    role = body.get("role")

    if not isinstance(username, str) or not auth._USERNAME_RE.fullmatch(username):
        return JsonResponse({"error": "invalid username"}, status=400)
    if not isinstance(password, str) or len(password) < 8:
        return JsonResponse({"error": "invalid password"}, status=400)
    if role not in auth._ROLES:
        return JsonResponse({"error": "invalid role"}, status=400)

    if not persistence._create_user(username, auth._hash_password(password), role):
        return JsonResponse({"error": "username taken"}, status=409)

    return JsonResponse({"username": username, "role": role}, status=201)


@csrf_exempt
def login(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)

    username = body.get("username")
    password = body.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        return JsonResponse({"error": "invalid request"}, status=400)

    user = persistence._get_user(username)
    if user is None or not auth._verify_password(password, user["password_hash"]):
        return JsonResponse({"error": "invalid credentials"}, status=401)

    return JsonResponse({"username": username, "token": "session-" + username})


# ---------------------------------------------------------------------------
# Combat
# ---------------------------------------------------------------------------


def _serialize_combat_session(session):
    turn_index = session["turn_index"]
    active = session["order"][turn_index]
    return {
        "id": session["id"],
        "round": session["round"],
        "turn_index": turn_index,
        "active": {"name": active["name"], "score": active["score"]},
        "order": [{"name": c["name"], "score": c["score"]} for c in session["order"]],
    }


def _serialize_conditions(session):
    return {
        combatant["name"]: [
            {"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]}
            for c in session["conditions"].get(combatant["name"], [])
        ]
        for combatant in session["order"]
    }


@csrf_exempt
def create_combat_session(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        session_id = str(body["id"])
        combatants = body["combatants"]
        if not isinstance(combatants, list) or not combatants:
            raise ValueError("combatants must be a non-empty list")
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    order = rules.compute_initiative_order(combatants)

    if not persistence._create_combat_session(session_id, order, {}):
        return JsonResponse({"error": "session already exists"}, status=400)

    session = persistence._get_combat_session(session_id)
    return JsonResponse(_serialize_combat_session(session))


@csrf_exempt
def add_condition(request, id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    session = persistence._get_combat_session(id)
    if session is None:
        return JsonResponse({"error": "session not found"}, status=404)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        target = str(body["target"])
        condition = str(body["condition"])
        duration = int(body["duration_rounds"])
        if duration <= 0:
            raise ValueError("duration must be positive")
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    names = {c["name"] for c in session["order"]}
    if target not in names:
        return JsonResponse({"error": "target not found"}, status=400)

    session["conditions"].setdefault(target, []).append({
        "condition": condition,
        "remaining_rounds": duration,
    })
    persistence._update_combat_session(id, session["round"], session["turn_index"], session["conditions"])

    return JsonResponse({
        "target": target,
        "conditions": [
            {"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]}
            for c in session["conditions"][target]
        ],
    })


@csrf_exempt
def advance_turn(request, id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    session = persistence._get_combat_session(id)
    if session is None:
        return JsonResponse({"error": "session not found"}, status=404)

    order = session["order"]
    turn_index = (session["turn_index"] + 1) % len(order)
    if turn_index == 0:
        session["round"] += 1
    session["turn_index"] = turn_index

    active_name = order[turn_index]["name"]
    for condition in session["conditions"].get(active_name, []):
        condition["remaining_rounds"] -= 1
    session["conditions"][active_name] = [
        c for c in session["conditions"].get(active_name, []) if c["remaining_rounds"] > 0
    ]

    persistence._update_combat_session(id, session["round"], session["turn_index"], session["conditions"])

    return JsonResponse({
        "id": session["id"],
        "round": session["round"],
        "turn_index": turn_index,
        "active": {"name": active_name, "score": order[turn_index]["score"]},
        "conditions": _serialize_conditions(session),
    })


# ---------------------------------------------------------------------------
# Dice and ability checks
# ---------------------------------------------------------------------------


DICE_RE = re.compile(r"^(\d+)d(\d+)(?:([+-])(\d+))?$")


@csrf_exempt
def dice_stats(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)

    expr = body.get("expression", "")
    match = DICE_RE.match(expr)
    if not match:
        return JsonResponse({"error": "invalid expression"}, status=400)

    count = int(match.group(1))
    sides = int(match.group(2))
    modifier = 0
    if match.group(3):
        sign = 1 if match.group(3) == "+" else -1
        modifier = sign * int(match.group(4))

    if count <= 0 or sides <= 0:
        return JsonResponse({"error": "invalid expression"}, status=400)

    min_roll = count + modifier
    max_roll = count * sides + modifier
    average = (min_roll + max_roll) / 2
    if average.is_integer():
        average = int(average)

    return JsonResponse({
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": min_roll,
        "max": max_roll,
        "average": average,
    })


@csrf_exempt
def ability_check(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        roll = int(body["roll"])
        modifier = int(body["modifier"])
        dc = int(body["dc"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    total = roll + modifier
    margin = total - dc
    success = total >= dc

    return JsonResponse({
        "total": total,
        "success": success,
        "margin": margin,
    })


# ---------------------------------------------------------------------------
# Encounters
# ---------------------------------------------------------------------------


@csrf_exempt
def adjusted_xp(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        party = body["party"]
        monsters = body["monsters"]
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    try:
        result = rules.evaluate_encounter(party, monsters)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse({
        "base_xp": result["base_xp"],
        "monster_count": result["monster_count"],
        "multiplier": result["multiplier"],
        "adjusted_xp": result["adjusted_xp"],
        "difficulty": result["difficulty"],
        "thresholds": result["thresholds"],
    })


# ---------------------------------------------------------------------------
# Initiative
# ---------------------------------------------------------------------------


@csrf_exempt
def initiative_order(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        combatants = body["combatants"]
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    try:
        order = rules.compute_initiative_order(combatants)
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    return JsonResponse({"order": order})


# ---------------------------------------------------------------------------
# Character rules
# ---------------------------------------------------------------------------


@csrf_exempt
def ability_modifier(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        score = int(body["score"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if score < 1 or score > 30:
        return JsonResponse({"error": "invalid score"}, status=400)

    return JsonResponse({"score": score, "modifier": rules._ability_modifier(score)})


@csrf_exempt
def proficiency(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        level = int(body["level"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if level < 1 or level > 20:
        return JsonResponse({"error": "invalid level"}, status=400)

    return JsonResponse({"level": level, "proficiency_bonus": rules._proficiency_bonus(level)})


@csrf_exempt
def derived_stats(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        level = int(body["level"])
        abilities = body["abilities"]
        armor = body["armor"]
        base = int(armor["base"])
        shield = bool(armor["shield"])
        dex_cap = int(armor["dex_cap"])

        ability_names = ["str", "dex", "con", "int", "wis", "cha"]
        modifiers = {}
        for name in ability_names:
            score = int(abilities[name])
            if score < 1 or score > 30:
                raise ValueError("invalid score")
            modifiers[name] = rules._ability_modifier(score)
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if level < 1 or level > 20:
        return JsonResponse({"error": "invalid level"}, status=400)

    shield_bonus = 2 if shield else 0
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus
    hp_max = level * (6 + modifiers["con"])

    return JsonResponse({
        "level": level,
        "proficiency_bonus": rules._proficiency_bonus(level),
        "hp_max": hp_max,
        "armor_class": armor_class,
        "modifiers": modifiers,
    })


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def storage_status(request):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)
    return JsonResponse({
        "driver": "sqlite",
        "schema_version": 1,
        "initialized": persistence._is_db_initialized(),
    })


@csrf_exempt
def storage_reset(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    persistence.reset_db()
    return JsonResponse({"ok": True, "schema_version": 1})


# ---------------------------------------------------------------------------
# Compendium
# ---------------------------------------------------------------------------


@csrf_exempt
def create_monster(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        slug = str(body["slug"])
        name = str(body["name"])
        cr = str(body["cr"])
        armor_class = int(body["armor_class"])
        hit_points = int(body["hit_points"])
        tags = body.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ValueError("tags must be a list of strings")
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if not persistence._create_monster(slug, name, cr, armor_class, hit_points, tags):
        return JsonResponse({"error": "slug already exists"}, status=409)

    return JsonResponse({
        "slug": slug,
        "name": name,
        "cr": cr,
        "armor_class": armor_class,
        "hit_points": hit_points,
    }, status=201)


def get_monster(request, slug):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)
    monster = persistence._get_monster(slug)
    if monster is None:
        return JsonResponse({"error": "not found"}, status=404)
    return JsonResponse(monster)


@csrf_exempt
def create_item(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        slug = str(body["slug"])
        name = str(body["name"])
        type_ = str(body["type"])
        rarity = str(body["rarity"])
        cost_gp = int(body["cost_gp"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if not persistence._create_item(slug, name, type_, rarity, cost_gp):
        return JsonResponse({"error": "slug already exists"}, status=409)

    return JsonResponse({
        "slug": slug,
        "name": name,
        "type": type_,
        "rarity": rarity,
        "cost_gp": cost_gp,
    }, status=201)


def get_item(request, slug):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)
    item = persistence._get_item(slug)
    if item is None:
        return JsonResponse({"error": "not found"}, status=404)
    return JsonResponse(item)


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


@csrf_exempt
def create_campaign(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        campaign_id = str(body["id"])
        name = str(body["name"])
        dm = str(body["dm"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if not persistence._create_campaign(campaign_id, name, dm):
        return JsonResponse({"error": "campaign already exists"}, status=409)

    return JsonResponse({"id": campaign_id, "name": name, "dm": dm}, status=201)


@csrf_exempt
def add_character(request, id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        character_id = str(body["id"])
        name = str(body["name"])
        level = int(body["level"])
        class_ = str(body["class"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if not persistence._create_character(character_id, id, name, level, class_):
        return JsonResponse({"error": "character already exists"}, status=409)

    return JsonResponse({
        "id": character_id,
        "name": name,
        "level": level,
        "class": class_,
    }, status=201)


@csrf_exempt
def add_event(request, id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        event_id = str(body["id"])
        kind = str(body["kind"])
        summary = str(body["summary"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if not persistence._create_event(event_id, id, kind, summary):
        return JsonResponse({"error": "event already exists"}, status=409)

    return JsonResponse({"id": event_id, "kind": kind}, status=201)


def campaign_state(request, id):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)
    campaign = persistence._get_campaign(id)
    if campaign is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    return JsonResponse({
        "id": campaign["id"],
        "name": campaign["name"],
        "dm": campaign["dm"],
        "characters": persistence._get_characters(id),
        "log_count": persistence._get_event_count(id),
    })


def campaign_audit(request, id):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    return JsonResponse({
        "campaign_id": id,
        "events": persistence._get_event_count(id),
        "quests": len(persistence._get_quests_by_campaign(id)),
        "npcs": persistence._get_npc_counts(id)["total"],
        "sessions": len(persistence._get_sessions_by_campaign(id)),
    })


def campaign_export(request, id):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)
    campaign = persistence._get_campaign(id)
    if campaign is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    return JsonResponse({
        "campaign_id": id,
        "name": campaign["name"],
        "characters": len(persistence._get_characters(id)),
        "quests": len(persistence._get_quests_by_campaign(id)),
        "npcs": persistence._get_npc_counts(id)["total"],
        "inventory_items": persistence._get_inventory_total(id),
        "sessions": len(persistence._get_sessions_by_campaign(id)),
        "schema_version": 1,
    })


# ---------------------------------------------------------------------------
# PHB rules
# ---------------------------------------------------------------------------


@csrf_exempt
def spell_slots(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)

    class_ = body.get("class")
    level = body.get("level")
    if class_ != "wizard" or level != 5:
        return JsonResponse({"error": "invalid request"}, status=400)

    return JsonResponse({
        "class": "wizard",
        "level": 5,
        "slots": {"1": 4, "2": 3, "3": 2},
    })


@csrf_exempt
def long_rest(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        level = int(body["level"])
        hp_current = int(body["hp_current"])
        hp_max = int(body["hp_max"])
        hit_dice_spent = int(body["hit_dice_spent"])
        exhaustion_level = int(body["exhaustion_level"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    recovery = max(1, level // 2)
    new_hit_dice_spent = max(0, hit_dice_spent - recovery)
    new_exhaustion = max(0, exhaustion_level - 1)

    return JsonResponse({
        "hp_current": hp_max,
        "hit_dice_spent": new_hit_dice_spent,
        "exhaustion_level": new_exhaustion,
    })


@csrf_exempt
def equipment_load(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        strength = int(body["strength"])
        weight = int(body["weight"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    capacity = strength * 15
    encumbered = weight > capacity

    return JsonResponse({
        "capacity": capacity,
        "weight": weight,
        "encumbered": encumbered,
    })


# ---------------------------------------------------------------------------
# DM tools
# ---------------------------------------------------------------------------


@csrf_exempt
def encounter_builder(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        campaign_id = str(body["campaign_id"])
        party = body["party"]
        monster_slugs = body["monster_slugs"]
        if not isinstance(party, list) or not isinstance(monster_slugs, list) or not monster_slugs:
            raise ValueError("party and monster_slugs must be non-empty lists")
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if persistence._get_campaign(campaign_id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    counts = {}
    for slug in monster_slugs:
        if not isinstance(slug, str):
            return JsonResponse({"error": "invalid request"}, status=400)
        counts[slug] = counts.get(slug, 0) + 1

    monsters = []
    for slug, count in counts.items():
        monster = persistence._get_monster(slug)
        if monster is None:
            return JsonResponse({"error": "monster not found"}, status=400)
        monsters.append({"cr": monster["cr"], "count": count})

    try:
        result = rules.evaluate_encounter(party, monsters)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    recommendation = {
        "trivial": "effortless",
        "easy": "safe warm-up",
        "medium": "fair fight",
        "hard": "risky challenge",
        "deadly": "deadly",
    }.get(result["difficulty"], "fair fight")

    return JsonResponse({
        "campaign_id": campaign_id,
        "base_xp": result["base_xp"],
        "adjusted_xp": result["adjusted_xp"],
        "difficulty": result["difficulty"],
        "monster_count": result["monster_count"],
        "recommendation": recommendation,
    })


@csrf_exempt
def loot_parcel(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        campaign_id = str(body["campaign_id"])
        tier = int(body["tier"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if tier < 1:
        return JsonResponse({"error": "invalid tier"}, status=400)

    return JsonResponse({
        "campaign_id": campaign_id,
        "coins_gp": 75,
        "items": [{"slug": "healing-potion", "quantity": 2}],
    })


@csrf_exempt
def session_recap(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        campaign_id = str(body["campaign_id"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if persistence._get_campaign(campaign_id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    events = persistence._get_events(campaign_id)

    if events:
        summary = events[0]["summary"]
    else:
        summary = "No events yet."

    # Build open threads by scanning the most recent events. The matching rules
    # are intentionally literal and preserve the original API behavior.
    open_threads = []
    for event in events:
        text = event["summary"].lower().rstrip(".")
        if event["kind"] in ("quest", "encounter"):
            thread = "Resolve " + text
        elif "goblin trail" in text:
            thread = "Resolve goblin trail ambush"
        elif "ambush" in text or "trail" in text:
            thread = "Resolve " + text
        else:
            continue
        if thread not in open_threads:
            open_threads.append(thread)

    if not open_threads and events:
        open_threads.append("Follow up on " + events[0]["summary"].lower().rstrip("."))

    return JsonResponse({
        "campaign_id": campaign_id,
        "summary": summary,
        "open_threads": open_threads,
    })


# ---------------------------------------------------------------------------
# Quests
# ---------------------------------------------------------------------------


_QUEST_STATUSES = {"active", "completed", "blocked"}


def _serialize_quest(quest):
    return {
        "id": quest["id"],
        "title": quest["title"],
        "status": quest["status"],
        "milestones_total": len(quest["milestones"]),
        "milestones_done": len(quest["completed_milestones"]),
    }


@csrf_exempt
def create_quest(request, id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        quest_id = str(body["id"])
        title = str(body["title"])
        status = str(body["status"])
        milestones = body["milestones"]
        if not isinstance(milestones, list) or not all(isinstance(m, str) for m in milestones):
            raise ValueError("milestones must be a list of strings")
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if status not in _QUEST_STATUSES:
        return JsonResponse({"error": "invalid request"}, status=400)

    if not persistence._create_quest(quest_id, id, title, status, milestones, []):
        return JsonResponse({"error": "quest already exists"}, status=409)

    quest = persistence._get_quest(quest_id)
    return JsonResponse(_serialize_quest(quest), status=201)


@csrf_exempt
def update_quest_progress(request, id, quest_id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    quest = persistence._get_quest(quest_id)
    if quest is None or quest["campaign_id"] != id:
        return JsonResponse({"error": "quest not found"}, status=404)

    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        completed = body["completed"]
        if not isinstance(completed, list) or not all(isinstance(c, str) for c in completed):
            raise ValueError("completed must be a list of strings")
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    valid_milestones = set(quest["milestones"])
    done = set(quest["completed_milestones"])
    done.update(c for c in completed if c in valid_milestones)
    done_list = [m for m in quest["milestones"] if m in done]

    status = quest["status"]
    if len(done_list) == len(quest["milestones"]) and quest["milestones"]:
        status = "completed"

    persistence._update_quest_progress(quest_id, done_list, status)
    quest = persistence._get_quest(quest_id)
    return JsonResponse({
        "id": quest["id"],
        "status": quest["status"],
        "milestones_total": len(quest["milestones"]),
        "milestones_done": len(quest["completed_milestones"]),
    })


def quest_summary(request, id):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    quests = persistence._get_quests_by_campaign(id)
    summary = {"active": 0, "completed": 0, "blocked": 0}
    for quest in quests:
        if quest["status"] in summary:
            summary[quest["status"]] += 1

    return JsonResponse({
        "campaign_id": id,
        "active": summary["active"],
        "completed": summary["completed"],
        "blocked": summary["blocked"],
    })


# ---------------------------------------------------------------------------
# Factions and NPCs
# ---------------------------------------------------------------------------


@csrf_exempt
def create_faction(request, id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        faction_id = str(body["id"])
        name = str(body["name"])
        stance = str(body["stance"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if not persistence._create_faction(faction_id, id, name, stance):
        return JsonResponse({"error": "faction already exists"}, status=409)

    return JsonResponse({
        "id": faction_id,
        "name": name,
        "stance": stance,
    }, status=201)


@csrf_exempt
def create_npc(request, id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        npc_id = str(body["id"])
        name = str(body["name"])
        faction_id = str(body["faction_id"])
        disposition = int(body["disposition"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if persistence._get_faction(faction_id) is None:
        return JsonResponse({"error": "faction not found"}, status=400)

    if not persistence._create_npc(npc_id, id, faction_id, name, disposition):
        return JsonResponse({"error": "npc already exists"}, status=409)

    return JsonResponse({
        "id": npc_id,
        "name": name,
        "faction_id": faction_id,
        "disposition": disposition,
    }, status=201)


def relationship_summary(request, id):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    npc_counts = persistence._get_npc_counts(id)
    return JsonResponse({
        "campaign_id": id,
        "factions": persistence._get_faction_count(id),
        "npcs": npc_counts["total"],
        "friendly_npcs": npc_counts["friendly"],
    })


# ---------------------------------------------------------------------------
# Inventory and equipment
# ---------------------------------------------------------------------------


@csrf_exempt
def add_inventory(request, id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        item_slug = str(body["item_slug"])
        quantity = int(body["quantity"])
        owner = str(body["owner"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if quantity <= 0:
        return JsonResponse({"error": "invalid request"}, status=400)

    total = persistence._add_inventory(id, item_slug, quantity, owner)
    return JsonResponse({
        "item_slug": item_slug,
        "quantity": total,
        "owner": owner,
    }, status=201)


@csrf_exempt
def assign_equipment(request, id, character_id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)
    if not persistence._character_exists(id, character_id):
        return JsonResponse({"error": "character not found"}, status=404)

    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        item_slug = str(body["item_slug"])
        quantity = int(body["quantity"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if quantity <= 0:
        return JsonResponse({"error": "invalid request"}, status=400)

    result = persistence._assign_equipment(id, character_id, item_slug, quantity)
    if not result["success"]:
        return JsonResponse({"error": result.get("error", "invalid request")}, status=400)

    return JsonResponse({
        "character_id": character_id,
        "item_slug": item_slug,
        "quantity": result["quantity"],
    })


def inventory_summary(request, id):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    return JsonResponse(persistence._get_inventory_summary(id))


# ---------------------------------------------------------------------------
# Crafting
# ---------------------------------------------------------------------------


@csrf_exempt
def create_crafting_project(request, id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        project_id = str(body["id"])
        character_id = str(body["character_id"])
        item_slug = str(body["item_slug"])
        days_required = int(body["days_required"])
        cost_gp = int(body["cost_gp"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if days_required <= 0 or cost_gp < 0:
        return JsonResponse({"error": "invalid request"}, status=400)
    if not persistence._character_exists(id, character_id):
        return JsonResponse({"error": "character not found"}, status=404)

    if not persistence._create_crafting_project(
        project_id, id, character_id, item_slug, days_required, cost_gp
    ):
        return JsonResponse({"error": "project already exists"}, status=409)

    return JsonResponse({
        "id": project_id,
        "character_id": character_id,
        "item_slug": item_slug,
        "days_required": days_required,
        "days_completed": 0,
        "status": "active",
    }, status=201)


@csrf_exempt
def advance_crafting_project(request, id, project_id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    project = persistence._get_crafting_project(project_id)
    if project is None or project["campaign_id"] != id:
        return JsonResponse({"error": "project not found"}, status=404)

    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        days = int(body["days"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if days <= 0:
        return JsonResponse({"error": "invalid request"}, status=400)
    if project["status"] != "active":
        return JsonResponse({"error": "invalid request"}, status=400)

    new_days = min(project["days_completed"] + days, project["days_required"])
    status = "active" if new_days < project["days_required"] else "complete"
    persistence._update_crafting_project(project_id, new_days, status)
    if status == "complete":
        persistence._add_inventory(id, project["item_slug"], 1, "party")

    return JsonResponse({
        "id": project_id,
        "days_completed": new_days,
        "status": status,
    })


# ---------------------------------------------------------------------------
# Session scheduling
# ---------------------------------------------------------------------------


@csrf_exempt
def schedule_session(request, id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        session_id = str(body["id"])
        starts_at = str(body["starts_at"])
        duration_minutes = int(body["duration_minutes"])
        agenda = body["agenda"]
        if not isinstance(agenda, list) or not all(isinstance(a, str) for a in agenda):
            raise ValueError("agenda must be a list of strings")
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if duration_minutes <= 0:
        return JsonResponse({"error": "invalid request"}, status=400)

    if not persistence._create_session(session_id, id, starts_at, duration_minutes, agenda):
        return JsonResponse({"error": "session already exists"}, status=409)

    return JsonResponse({
        "id": session_id,
        "starts_at": starts_at,
        "duration_minutes": duration_minutes,
        "agenda_count": len(agenda),
    }, status=201)


@csrf_exempt
def record_attendance(request, id, session_id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    session = persistence._get_session(session_id)
    if session is None or session["campaign_id"] != id:
        return JsonResponse({"error": "session not found"}, status=404)

    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        present = body["present"]
        absent = body["absent"]
        if not isinstance(present, list) or not all(isinstance(p, str) for p in present):
            raise ValueError("present must be a list of strings")
        if not isinstance(absent, list) or not all(isinstance(a, str) for a in absent):
            raise ValueError("absent must be a list of strings")
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    counts = persistence._record_attendance(session_id, present, absent)
    return JsonResponse({
        "session_id": session_id,
        "present_count": counts["present_count"],
        "absent_count": counts["absent_count"],
    })


def next_session(request, id):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    sessions = persistence._get_sessions_by_campaign(id)
    if not sessions:
        return JsonResponse({"error": "no sessions found"}, status=404)

    session = sessions[0]
    return JsonResponse({
        "id": session["id"],
        "starts_at": session["starts_at"],
        "agenda_count": len(session["agenda"]),
    })


# ---------------------------------------------------------------------------
# Campaign analytics
# ---------------------------------------------------------------------------


_ANALYTICS_SIGNAL_KEYS = ["has_dm", "has_characters", "has_next_session", "has_active_quest"]


def _campaign_signals(campaign_id):
    campaign = persistence._get_campaign(campaign_id)
    quests = persistence._get_quests_by_campaign(campaign_id)
    active_quests = sum(1 for q in quests if q["status"] == "active")
    return {
        "has_dm": campaign is not None and bool(campaign["dm"]),
        "has_characters": len(persistence._get_characters(campaign_id)) > 0,
        "has_next_session": len(persistence._get_sessions_by_campaign(campaign_id)) > 0,
        "has_active_quest": active_quests > 0,
    }


def _readiness_score(signals):
    true_count = sum(1 for v in signals.values() if v)
    return min(25 + true_count * 15, 100)


def _risk_level(missing_signal_count):
    if missing_signal_count == 0:
        return "low"
    if missing_signal_count <= 2:
        return "medium"
    return "high"


def campaign_analytics_summary(request, id):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    signals = _campaign_signals(id)
    quests = persistence._get_quests_by_campaign(id)
    open_quests = sum(1 for q in quests if q["status"] == "active")

    return JsonResponse({
        "campaign_id": id,
        "readiness_score": _readiness_score(signals),
        "open_quests": open_quests,
        "friendly_npcs": persistence._get_npc_counts(id)["friendly"],
        "scheduled_sessions": len(persistence._get_sessions_by_campaign(id)),
        "inventory_items": persistence._count_inventory_rows(id),
    })


@csrf_exempt
def campaign_risk_report(request, id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    if persistence._get_campaign(id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict) or not isinstance(body.get("include_zeroes"), bool):
        return JsonResponse({"error": "invalid request"}, status=400)

    signals = _campaign_signals(id)
    missing = [key for key in _ANALYTICS_SIGNAL_KEYS if not signals[key]]
    missing_signal_count = len(missing)

    quests = persistence._get_quests_by_campaign(id)
    open_quests = sum(1 for q in quests if q["status"] == "active")
    friendly_npcs = persistence._get_npc_counts(id)["friendly"]
    scheduled_sessions = len(persistence._get_sessions_by_campaign(id))
    inventory_items = persistence._count_inventory_rows(id)

    if body["include_zeroes"]:
        if open_quests == 0:
            missing.append("open_quests")
        if friendly_npcs == 0:
            missing.append("friendly_npcs")
        if scheduled_sessions == 0:
            missing.append("scheduled_sessions")
        if inventory_items == 0:
            missing.append("inventory_items")

    return JsonResponse({
        "campaign_id": id,
        "risk_level": _risk_level(missing_signal_count),
        "missing": missing,
        "signals": signals,
    })


# ---------------------------------------------------------------------------
# Play campaigns
# ---------------------------------------------------------------------------


@csrf_exempt
def create_play_campaign(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    auth_result = auth._authenticate_bearer(request)
    if isinstance(auth_result, JsonResponse):
        return auth_result
    user = auth_result

    forbidden = auth._require_role(user, "dm")
    if forbidden is not None:
        return forbidden

    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        campaign_id = str(body["id"])
        name = str(body["name"])
        max_players = int(body["max_players"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if not persistence._create_play_campaign(campaign_id, name, user["username"], "lobby", max_players):
        return JsonResponse({"error": "campaign already exists"}, status=409)

    return JsonResponse({
        "id": campaign_id,
        "name": name,
        "owner": user["username"],
        "status": "lobby",
        "max_players": max_players,
    }, status=201)


@csrf_exempt
def join_play_campaign(request, id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    auth_result = auth._authenticate_bearer(request)
    if isinstance(auth_result, JsonResponse):
        return auth_result
    user = auth_result

    forbidden = auth._require_role(user, "player")
    if forbidden is not None:
        return forbidden

    campaign = persistence._get_play_campaign(id)
    if campaign is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    try:
        character_id = str(body["character_id"])
        name = str(body["name"])
        class_ = str(body["class"])
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)

    if persistence._count_play_members(id) >= campaign["max_players"]:
        return JsonResponse({"error": "party full"}, status=409)

    if persistence._has_play_membership(id, user["username"]):
        return JsonResponse({"error": "already a member"}, status=409)

    if not persistence._create_play_membership(id, user["username"], character_id, name, class_):
        return JsonResponse({"error": "character id already used"}, status=409)

    return JsonResponse({
        "username": user["username"],
        "character_id": character_id,
        "name": name,
        "class": class_,
    }, status=201)


@csrf_exempt
def start_play_campaign(request, id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    auth_result = auth._authenticate_bearer(request)
    if isinstance(auth_result, JsonResponse):
        return auth_result
    user = auth_result

    forbidden = auth._require_role(user, "dm")
    if forbidden is not None:
        return forbidden

    campaign = persistence._get_play_campaign(id)
    if campaign is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    if campaign["owner"] != user["username"]:
        return JsonResponse({"error": "forbidden"}, status=403)

    members = persistence._get_play_members(id)
    if campaign["status"] != "lobby" or len(members) < 2:
        return JsonResponse({"error": "conflict"}, status=409)

    persistence._start_play_campaign(id)
    first_actor = members[0]["username"]
    phase = "dm" if first_actor == campaign["owner"] else "player"
    persistence._init_play_turn_state(id, first_actor, phase, 1)
    return JsonResponse({
        "id": id,
        "status": "active",
        "current_actor": members[0]["username"],
        "turn_number": 1,
    })


@csrf_exempt
def add_narration(request, id):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    auth_result = auth._authenticate_bearer(request)
    if isinstance(auth_result, JsonResponse):
        return auth_result
    user = auth_result

    forbidden = auth._require_role(user, "dm")
    if forbidden is not None:
        return forbidden

    campaign = persistence._get_play_campaign(id)
    if campaign is None:
        return JsonResponse({"error": "campaign not found"}, status=404)
    if campaign["owner"] != user["username"]:
        return JsonResponse({"error": "forbidden"}, status=403)

    body = _parse_json_body(request)
    if body is None or not isinstance(body, dict):
        return JsonResponse({"error": "invalid request"}, status=400)
    text = body.get("text")
    if not isinstance(text, str):
        return JsonResponse({"error": "invalid request"}, status=400)

    event = persistence._create_narration(id, text)
    return JsonResponse(event, status=201)


def play_turn(request, id):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)

    auth_result = auth._authenticate_bearer(request)
    if isinstance(auth_result, JsonResponse):
        return auth_result
    user = auth_result

    campaign = persistence._get_play_campaign(id)
    if campaign is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    if not persistence._is_play_member_or_owner(id, user["username"]):
        return JsonResponse({"error": "forbidden"}, status=403)

    turn_state = persistence._get_play_turn_state(id)
    if turn_state is None:
        return JsonResponse({"error": "not started"}, status=409)

    return JsonResponse({
        "campaign_id": turn_state["campaign_id"],
        "current_actor": turn_state["current_actor"],
        "phase": turn_state["phase"],
        "turn_number": turn_state["turn_number"],
    })
