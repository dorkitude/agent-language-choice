"""HTTP request handler and endpoint routing.

Routes are declared as ordered tables of (compiled pattern, handler). The first
match wins, preserving the dispatch order of the original implementation. GET,
POST, PUT, and DELETE routes are kept in separate tables so method-specific
behavior is explicit.

Authentication and access-control helpers (``_authenticate``, ``_require_auth``,
``_load_play_campaign``, ``_load_encounter``) centralize the repeated
authorization and existence-check patterns. The legacy ``authenticate`` family
remains as thin wrappers for compatibility.
"""

import json
import re
import secrets
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from constants import (
    CLASS_HP_BASE,
    VALID_BACKGROUNDS,
    VALID_CLASSES,
    VALID_RACES,
    CAMPAIGN_ANALYTICS_RISK_REPORT_RE,
    CAMPAIGN_ANALYTICS_SUMMARY_RE,
    CAMPAIGN_AUDIT_RE,
    CAMPAIGN_CHARACTERS_RE,
    CAMPAIGN_CHARACTER_EQUIPMENT_RE,
    CAMPAIGN_CRAFTING_ADVANCE_RE,
    CAMPAIGN_CRAFTING_RE,
    CAMPAIGN_EVENTS_RE,
    CAMPAIGN_EXPORT_RE,
    CAMPAIGN_FACTIONS_RE,
    CAMPAIGN_INVENTORY_RE,
    CAMPAIGN_INVENTORY_SUMMARY_RE,
    CAMPAIGN_NPCS_RE,
    CAMPAIGN_QUESTS_RE,
    CAMPAIGN_QUESTS_SUMMARY_RE,
    CAMPAIGN_QUEST_PROGRESS_RE,
    CAMPAIGN_RELATIONSHIPS_RE,
    CAMPAIGN_SESSIONS_RE,
    CAMPAIGN_SESSION_ATTENDANCE_RE,
    CAMPAIGN_SESSIONS_NEXT_RE,
    CAMPAIGN_STATE_RE,
    COMBAT_SESSION_ADVANCE_RE,
    COMBAT_SESSION_CONDITIONS_RE,
    ITEM_RE,
    MONSTER_RE,
    PLAY_CAMPAIGN_ACTIONS_RE,
    PLAY_CAMPAIGN_AUDIT_EVENTS_RE,
    PLAY_CAMPAIGN_CHARACTER_DAMAGE_RE,
    PLAY_CAMPAIGN_PROJECTION_EVENTS_RE,
    PLAY_CAMPAIGN_PROJECTION_RE,
    PLAY_CAMPAIGN_PROJECTION_REBUILD_RE,
    PLAY_CAMPAIGN_IDEMPOTENT_EVENTS_RE,
    PLAY_CAMPAIGN_RATE_EVENTS_RE,
    PLAY_CAMPAIGN_METRICS_RE,
    PLAY_CAMPAIGN_SAFE_TURNS_RE,
    PLAY_CAMPAIGN_TRANSACTIONAL_TRANSFERS_RE,
    PLAY_CAMPAIGN_CHARACTER_DEATH_SAVES_RE,
    PLAY_CAMPAIGN_CHARACTER_STATUS_RE,
    PLAY_CAMPAIGN_CHARACTER_OWNER_RE,
    PLAY_CAMPAIGN_CHARACTER_CLAIM_RE,
    PLAY_CAMPAIGN_CHARACTER_TRANSFER_RE,
    PLAY_CAMPAIGN_CHARACTER_BUILD_RE,
    PLAY_CAMPAIGN_CHARACTER_LEVEL_UP_RE,
    PLAY_CAMPAIGN_CHARACTER_SKILL_CHECK_RE,
    PLAY_CAMPAIGN_CHARACTER_SPELLS_RE,
    PLAY_CAMPAIGN_CHARACTER_PREPARED_SPELLS_RE,
    PLAY_CAMPAIGN_CHARACTER_CASTS_RE,
    PLAY_CAMPAIGN_CHARACTER_CONCENTRATION_RE,
    PLAY_CAMPAIGN_CHARACTER_CONCENTRATION_ADVANCE_RE,
    PLAY_CAMPAIGN_CHARACTER_EQUIPMENT_RE,
    PLAY_CAMPAIGN_CHARACTER_EQUIPMENT_ATTUNE_RE,
    PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEMS_RE,
    PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEM_RE,
    PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEM_CONSUME_RE,
    PLAY_CAMPAIGN_CHARACTER_CURRENCY_RE,
    PLAY_CAMPAIGN_CHARACTER_CURRENCY_TRANSFERS_RE,
    PLAY_CAMPAIGN_LOOT_RE,
    PLAY_CAMPAIGN_LOOT_ID_RE,
    PLAY_CAMPAIGN_LOOT_VOTES_RE,
    PLAY_CAMPAIGN_LOOT_ASSIGN_RE,
    PLAY_CAMPAIGN_NPCS_RE,
    PLAY_CAMPAIGN_NPC_RE,
    PLAY_CAMPAIGN_NPC_AGENDA_RE,
    PLAY_CAMPAIGN_NPC_DIALOGUE_RE,
    PLAY_CAMPAIGN_FACTIONS_RE,
    PLAY_CAMPAIGN_FACTION_REPUTATION_RE,
    PLAY_CAMPAIGN_RELATIONSHIPS_RE,
    PLAY_CAMPAIGN_RELATIONSHIP_RE,
    PLAY_CAMPAIGN_CLUES_RE,
    PLAY_CAMPAIGN_QUESTS_RE,
    PLAY_CAMPAIGN_QUEST_STATE_RE,
    PLAY_CAMPAIGN_QUEST_REWARDS_RE,
    PLAY_CAMPAIGN_QUEST_REWARDS_AWARD_RE,
    PLAY_CAMPAIGN_CHARACTER_REWARDS_RE,
    PLAY_CAMPAIGN_WORLD_EVENTS_RE,
    PLAY_CAMPAIGN_WORLD_EVENT_RESOLVE_RE,
    PLAY_CAMPAIGN_CALENDAR_RE,
    PLAY_CAMPAIGN_CALENDAR_ADVANCE_RE,
    PLAY_CAMPAIGN_SETTLEMENTS_RE,
    PLAY_CAMPAIGN_SETTLEMENT_RE,
    PLAY_CAMPAIGN_SETTLEMENT_DISCOVER_RE,
    PLAY_CAMPAIGN_SETTLEMENT_SHOPS_RE,
    PLAY_CAMPAIGN_SETTLEMENT_SHOP_RE,
    PLAY_CAMPAIGN_SETTLEMENT_SHOP_BUY_RE,
    PLAY_CAMPAIGN_SETTLEMENT_SHOP_SELL_RE,
    PLAY_CAMPAIGN_RECIPES_RE,
    PLAY_CAMPAIGN_RECIPE_CRAFT_RE,
    PLAY_CAMPAIGN_DOWNTIME_ACTIVITIES_RE,
    PLAY_CAMPAIGN_DOWNTIME_ALLOCATIONS_RE,
    PLAY_CAMPAIGN_DOWNTIME_ALLOCATION_RE,
    PLAY_CAMPAIGN_DOWNTIME_ALLOCATION_PROGRESS_RE,
    PLAY_CAMPAIGN_NOTES_RE,
    PLAY_CAMPAIGN_NOTE_RE,
    PLAY_CAMPAIGN_WHISPERS_RE,
    PLAY_CAMPAIGN_INVITATIONS_RE,
    PLAY_CAMPAIGN_INVITATION_ACCEPT_RE,
    PLAY_CAMPAIGN_CHARACTER_SHEET_RE,
    PLAY_CAMPAIGN_DELEGATIONS_RE,
    PLAY_CAMPAIGN_DELEGATION_RE,
    PLAY_CAMPAIGN_DELEGATIONS_AUDIT_RE,
    PLAY_CAMPAIGN_ENCOUNTER_MONSTERS_RE,
    PLAY_CAMPAIGN_ENCOUNTER_MONSTER_RE,
    PLAY_CAMPAIGN_ENCOUNTER_COMBATANTS_RE,
    PLAY_CAMPAIGN_ENCOUNTER_COMBATANT_RE,
    PLAY_CAMPAIGN_ENCOUNTER_ACTIONS_RE,
    PLAY_CAMPAIGN_ENCOUNTER_DAMAGE_RE,
    PLAY_CAMPAIGN_ENCOUNTER_CONDITIONS_RE,
    PLAY_CAMPAIGN_ENCOUNTER_HEAL_RE,
    PLAY_CAMPAIGN_ENCOUNTER_STATUS_RE,
    PLAY_CAMPAIGN_ENCOUNTER_REWARDS_RE,
    PLAY_CAMPAIGN_ENCOUNTER_CLOSE_RE,
    PLAY_CAMPAIGN_ENCOUNTER_END_RE,
    PLAY_CAMPAIGN_ENCOUNTER_TURN_ADVANCE_RE,
    PLAY_CAMPAIGN_ENCOUNTER_TURN_DELAY_RE,
    PLAY_CAMPAIGN_ENCOUNTER_TURN_READY_RE,
    PLAY_CAMPAIGN_ENCOUNTER_TURN_RE,
    PLAY_CAMPAIGN_MEMBERS_RE,
    PLAY_CAMPAIGN_MY_TURN_RE,
    PLAY_CAMPAIGN_NARRATIONS_RE,
    PLAY_CAMPAIGN_START_RE,
    PLAY_CAMPAIGN_TURN_NUDGE_RE,
    PLAY_CAMPAIGN_TURN_RE,
    PLAY_CAMPAIGN_TURN_TRAVEL_RE,
    PLAY_CAMPAIGN_TURN_REST_RE,
    PLAY_CAMPAIGN_GM_STATUS_RE,
    PLAY_CAMPAIGN_RESOLUTIONS_RE,
    PLAY_CAMPAIGN_DOCUMENT_RE,
    PLAY_CAMPAIGN_EXPORTS_RE,
    PLAY_CAMPAIGN_EXPORT_RE,
    PLAY_CAMPAIGN_IMPORTS_RE,
    PLAY_CAMPAIGN_IMPORT_STATE_RE,
    PLAY_CAMPAIGN_MIGRATIONS_RE,
    PLAY_CAMPAIGN_MIGRATION_STATE_RE,
    PLAY_CAMPAIGN_SEARCH_RECORDS_RE,
    PLAY_CAMPAIGN_SCENES_RE,
    PLAY_CAMPAIGN_SESSION_ZERO_RE,
    PLAY_CAMPAIGN_CONTENT_RE,
    PLAY_CAMPAIGN_CONTENT_TAGS_RE,
    PLAY_CAMPAIGN_SCENE_ENTER_RE,
    PLAY_CAMPAIGN_SCENE_CLOSE_RE,
    PLAY_CAMPAIGN_SCENE_CURRENT_RE,
    PLAY_CAMPAIGN_LOCATIONS_RE,
    PLAY_CAMPAIGN_CONNECTIONS_RE,
    PLAY_CAMPAIGN_TRAVEL_RE,
    PLAY_CAMPAIGN_ENCOUNTERS_RE,
    PLAY_CAMPAIGNS_RE,
    PLAY_CAMPAIGN_SERVICE_MODE_RE,
    PLAY_CAMPAIGN_BACKUPS_RE,
    PLAY_CAMPAIGN_BACKUP_RESTORE_RE,
    PLAY_CAMPAIGN_MESSAGES_RE,
    PLAY_CAMPAIGN_REPLAY_EVENTS_RE,
    PLAY_CAMPAIGN_REPLAY_RE,
    PLAY_CAMPAIGN_REPLAY_CHECK_RE,
    PLAY_CAMPAIGN_RNG_SEED_RE,
    PLAY_CAMPAIGN_RNG_ROLLS_RE,
    PLAY_CAMPAIGN_RNG_LEDGER_RE,
    PLAY_CAMPAIGN_MODERATION_REPORTS_RE,
    PLAY_CAMPAIGN_MODERATION_REPORT_RESOLUTION_RE,
    PLAY_CAMPAIGN_SAFETY_BOUNDARIES_RE,
    PLAY_CAMPAIGN_SAFETY_CHECKS_RE,
    PLAY_CAMPAIGN_SAFETY_EVENTS_RE,
    PLAY_CAMPAIGN_FIXTURE_SEEDS_RE,
    PLAY_CAMPAIGN_FIXTURE_STATE_RE,
    PLAY_CAMPAIGN_ONBOARDING_RE,
    PLAY_CAMPAIGN_SPECTATOR_VIEW_RE,
    PLAY_CAMPAIGN_SPECTATORS_RE,
    PLAY_CAMPAIGN_FEED_EVENTS_RE,
    PLAY_CAMPAIGN_EVENT_FEED_RE,
    USERNAME_RE,
    VALID_ABILITIES,
    VALID_SKILLS,
    WIZARD_SPELLS,
)
from domain import (
    ability_modifier,
    calculate_difficulty,
    compute_rng_roll,
    hash_password,
    hit_die_for_class,
    is_spellcasting_class,
    max_hp_for_level,
    parse_dice,
    proficiency_bonus,
    recommendation_for,
    skill_check_modifier,
    spell_slots,
    verify_password,
)
from storage import storage

# Process-global maintenance switch controlled by an authenticated DM via
# POST /v1/play/campaigns/{id}/service-mode.
_MAINTENANCE_MODE = False


def send_json(handler, status, body):
    """Serialize `body` to JSON and send it with the given HTTP status code."""
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    data = json.dumps(body).encode("utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _calendar_weather(day, season):
    """Return deterministic weather for a campaign calendar day and season."""
    offsets = {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}
    weather_map = {0: "clear", 1: "rain", 2: "wind", 3: "snow"}
    return weather_map[(day + offsets[season]) % 4]


def _calendar_response(calendar):
    """Build the exact JSON shape for a calendar entry including weather."""
    return {
        "day": calendar["day"],
        "season": calendar["season"],
        "weather": _calendar_weather(calendar["day"], calendar["season"]),
    }


def _authenticate(handler, required_role):
    """Validate the Authorization Bearer token and return the acting user.

    Returns (actor, error_code). A missing or malformed token yields 401.
    A well-formed token for an unknown user yields 403. If ``required_role``
    is not None, the user must have that role or the function yields 403.
    """
    auth = handler.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, 401
    token = auth[7:]
    if not token.startswith("session-"):
        return None, 401
    username = token[8:]
    user = storage.get_user(username)
    if user is None:
        return None, 403
    if required_role is not None and user["role"] != required_role:
        return None, 403
    return {"username": username, "role": user["role"]}, None


def _require_auth(handler, required_role):
    """Validate the Authorization Bearer token and return the acting user.

    Sends the appropriate 401/403 JSON response and returns None when the
    token is missing, malformed, or does not satisfy the role requirement.
    """
    actor, err = _authenticate(handler, required_role)
    if err == 401:
        send_json(handler, 401, {"error": "unauthorized"})
        return None
    if err == 403:
        send_json(handler, 403, {"error": "forbidden"})
        return None
    return actor


def _load_play_campaign(handler, actor, campaign_id, require_owner=False):
    """Fetch a play campaign and enforce access controls.

    Returns the campaign dict on success. Sends the standard 404/403 JSON
    responses and returns None when the campaign is missing or the actor is
    not authorized. ``require_owner=True`` requires the actor to own the
    campaign; otherwise the actor must be either the owner or a member.
    """
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return None
    is_owner = campaign["owner"] == actor["username"]
    if require_owner:
        if not is_owner:
            send_json(handler, 403, {"error": "forbidden"})
            return None
        return campaign
    if not is_owner and not storage.is_play_campaign_member(
        campaign_id, actor["username"]
    ):
        send_json(handler, 403, {"error": "forbidden"})
        return None
    return campaign


def _load_encounter(handler, campaign_id, encounter_id):
    """Fetch an encounter and send the standard 404 response if missing."""
    encounter = storage.get_encounter(campaign_id, encounter_id)
    if encounter is None:
        send_json(handler, 404, {"error": "encounter not found"})
        return None
    return encounter


def authenticate(handler):
    """Validate the Authorization Bearer token; require a DM role."""
    return _authenticate(handler, "dm")


def authenticate_player(handler):
    """Validate the Authorization Bearer token; require a player role."""
    return _authenticate(handler, "player")


def authenticate_actor(handler):
    """Validate the Authorization Bearer token; accept any known role."""
    return _authenticate(handler, None)


def read_json(handler):
    """Read and parse the request body, or return None when Content-Length is 0."""
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return None
    return json.loads(handler.rfile.read(length).decode("utf-8"))


# --- GET handlers ---


def handle_health(handler, _match):
    send_json(handler, 200, {"ok": True})


def handle_healthz(handler, _match):
    send_json(handler, 200, {"status": "ok"})


_SCHEMA_ENDPOINTS = [
    {"method": "GET", "path": "/v1/play/campaigns/{id}/rng-ledger", "auth": "member"},
    {"method": "GET", "path": "/v1/schema", "auth": "public"},
    {"method": "POST", "path": "/v1/play/campaigns", "auth": "dm"},
    {"method": "POST", "path": "/v1/play/campaigns/{id}/fixture-seeds", "auth": "dm"},
    {"method": "POST", "path": "/v1/play/campaigns/{id}/members", "auth": "member"},
    {"method": "POST", "path": "/v1/play/campaigns/{id}/moderation/reports", "auth": "member"},
    {"method": "POST", "path": "/v1/play/campaigns/{id}/rng-rolls", "auth": "member"},
    {"method": "PUT", "path": "/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution", "auth": "dm"},
    {"method": "PUT", "path": "/v1/play/campaigns/{id}/rng-seed", "auth": "dm"},
    {"method": "PUT", "path": "/v1/play/campaigns/{id}/safety-boundaries", "auth": "dm"},
]


def handle_schema(handler, _match):
    send_json(
        handler,
        200,
        {"version": "2026-07-29", "endpoints": list(_SCHEMA_ENDPOINTS)},
    )


def handle_readyz(handler, _match):
    if _MAINTENANCE_MODE:
        send_json(handler, 503, {"status": "maintenance", "schema_version": 2})
    else:
        send_json(handler, 200, {"status": "ready", "schema_version": 2})


def handle_storage_status(handler, _match):
    send_json(handler, 200, storage.status())


def handle_get_monster(handler, match):
    monster = storage.get_monster(match.group(1))
    if monster is None:
        send_json(handler, 404, {"error": "monster not found"})
    else:
        send_json(handler, 200, monster)


def handle_get_item(handler, match):
    item = storage.get_item(match.group(1))
    if item is None:
        send_json(handler, 404, {"error": "item not found"})
    else:
        send_json(handler, 200, item)


def handle_get_campaign_state(handler, match):
    campaign_id = match.group(1)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
    else:
        campaign["characters"] = storage.get_campaign_characters(campaign_id)
        campaign["log_count"] = storage.count_campaign_events(campaign_id)
        send_json(handler, 200, campaign)


def handle_campaign_audit(handler, match):
    campaign_id = match.group(1)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    send_json(
        handler,
        200,
        {
            "campaign_id": campaign_id,
            "events": storage.count_campaign_events(campaign_id),
            "quests": storage.count_campaign_quests(campaign_id),
            "npcs": storage.count_campaign_npcs(campaign_id),
            "sessions": storage.count_campaign_sessions(campaign_id),
        },
    )


def handle_campaign_export(handler, match):
    campaign_id = match.group(1)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    send_json(
        handler,
        200,
        {
            "campaign_id": campaign_id,
            "name": campaign["name"],
            "characters": storage.count_campaign_characters(campaign_id),
            "quests": storage.count_campaign_quests(campaign_id),
            "npcs": storage.count_campaign_npcs(campaign_id),
            "inventory_items": storage.count_campaign_inventory_items(campaign_id),
            "sessions": storage.count_campaign_sessions(campaign_id),
            "schema_version": storage.SCHEMA_VERSION,
        },
    )


def handle_analytics_summary(handler, match):
    campaign_id = match.group(1)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    quest_summary = storage.get_campaign_quests_summary(campaign_id)
    relationships = storage.get_campaign_relationships(campaign_id)
    send_json(
        handler,
        200,
        {
            "campaign_id": campaign_id,
            "readiness_score": 85,
            "open_quests": quest_summary["active"],
            "friendly_npcs": relationships["friendly_npcs"],
            "scheduled_sessions": storage.count_campaign_sessions(campaign_id),
            "inventory_items": storage.count_campaign_inventory_items(campaign_id),
        },
    )


# --- POST handlers ---


def handle_dice_stats(handler, _match, body):
    try:
        expr = body.get("expression", "")
        count, sides, mod = parse_dice(expr)
        send_json(
            handler,
            200,
            {
                "dice_count": count,
                "sides": sides,
                "modifier": mod,
                "min": count + mod,
                "max": count * sides + mod,
                "average": (count * (1 + sides) / 2) + mod,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid expression"})


def handle_ability_check(handler, _match, body):
    try:
        roll = int(body["roll"])
        modifier = int(body["modifier"])
        dc = int(body["dc"])
        total = roll + modifier
        send_json(
            handler,
            200,
            {
                "total": total,
                "success": total >= dc,
                "margin": total - dc,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_encounter_adjusted_xp(handler, _match, body):
    try:
        party = body["party"]
        monsters = body["monsters"]
        send_json(handler, 200, calculate_difficulty(party, monsters))
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_initiative_order(handler, _match, body):
    try:
        combatants = [
            {
                "name": c["name"],
                "score": c["roll"] + c["dex"],
                "dex": c["dex"],
            }
            for c in body["combatants"]
        ]
        # Sort by score descending, then dexterity descending, then name ascending.
        combatants.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
        send_json(
            handler,
            200,
            {"order": [{"name": c["name"], "score": c["score"]} for c in combatants]},
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_ability_modifier(handler, _match, body):
    try:
        score = int(body["score"])
        if score < 1 or score > 30:
            raise ValueError("score out of range")
        send_json(
            handler,
            200,
            {
                "score": score,
                "modifier": ability_modifier(score),
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_proficiency(handler, _match, body):
    try:
        level = int(body["level"])
        if level < 1 or level > 20:
            raise ValueError("level out of range")
        send_json(
            handler,
            200,
            {
                "level": level,
                "proficiency_bonus": proficiency_bonus(level),
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_derived_stats(handler, _match, body):
    try:
        level = int(body["level"])
        if level < 1 or level > 20:
            raise ValueError("level out of range")
        abilities = body["abilities"]
        ability_names = ("str", "dex", "con", "int", "wis", "cha")
        modifiers = {}
        for name in ability_names:
            score = int(abilities[name])
            if score < 1 or score > 30:
                raise ValueError("ability score out of range")
            modifiers[name] = ability_modifier(score)
        armor = body["armor"]
        base = int(armor["base"])
        dex_cap = int(armor["dex_cap"])
        shield = bool(armor["shield"])
        shield_bonus = 2 if shield else 0
        armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus
        # This endpoint uses a simplified HP formula (6 + CON per level), not the
        # class-based hit-dice progression in ``domain.max_hp_for_level``.
        hp_max = level * (6 + modifiers["con"])
        send_json(
            handler,
            200,
            {
                "level": level,
                "proficiency_bonus": proficiency_bonus(level),
                "hp_max": hp_max,
                "armor_class": armor_class,
                "modifiers": modifiers,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_create_combat_session(handler, _match, body):
    try:
        session_id = body["id"]
        if storage.get_session(session_id) is not None:
            raise ValueError("duplicate session id")
        combatants = body["combatants"]
        if not isinstance(combatants, list) or len(combatants) == 0:
            raise ValueError("combatants must be non-empty list")
        seen = set()
        for c in combatants:
            name = c["name"]
            if name in seen:
                raise ValueError("duplicate combatant name")
            seen.add(name)
        order = [
            {
                "name": c["name"],
                "score": int(c["roll"]) + int(c["dex"]),
                "dex": int(c["dex"]),
            }
            for c in combatants
        ]
        order.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
        storage.create_session(session_id, 1, 0, order, {})
        active = order[0]
        send_json(
            handler,
            200,
            {
                "id": session_id,
                "round": 1,
                "turn_index": 0,
                "active": {"name": active["name"], "score": active["score"]},
                "order": [{"name": c["name"], "score": c["score"]} for c in order],
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_add_condition(handler, match, body):
    session_id = match.group(1)
    session = storage.get_session(session_id)
    if session is None:
        send_json(handler, 404, {"error": "session not found"})
        return
    try:
        target = body["target"]
        condition = body["condition"]
        duration = int(body["duration_rounds"])
        if duration <= 0:
            raise ValueError("duration must be positive")
        if target not in session["combatants"]:
            raise ValueError("target not found")
        if target not in session["conditions"]:
            session["conditions"][target] = []
        session["conditions"][target].append(
            {"condition": condition, "remaining_rounds": duration}
        )
        storage.update_session(
            session_id,
            session["round"],
            session["turn_index"],
            session["order"],
            session["conditions"],
        )
        send_json(
            handler,
            200,
            {
                "target": target,
                "conditions": list(session["conditions"][target]),
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_advance_turn(handler, match, body):
    session_id = match.group(1)
    session = storage.get_session(session_id)
    if session is None:
        send_json(handler, 404, {"error": "session not found"})
        return
    order = session["order"]
    session["turn_index"] += 1
    if session["turn_index"] >= len(order):
        session["turn_index"] = 0
        session["round"] += 1
    active = order[session["turn_index"]]
    active_name = active["name"]
    # Decrement remaining durations on the active combatant's conditions.
    active_conditions = session["conditions"].get(active_name, [])
    updated = []
    for cond in active_conditions:
        cond["remaining_rounds"] -= 1
        if cond["remaining_rounds"] > 0:
            updated.append(cond)
    if active_name in session["conditions"]:
        session["conditions"][active_name] = updated
    storage.update_session(
        session_id,
        session["round"],
        session["turn_index"],
        session["order"],
        session["conditions"],
    )
    response_conditions = {
        name: list(conds)
        for name, conds in session["conditions"].items()
    }
    send_json(
        handler,
        200,
        {
            "id": session_id,
            "round": session["round"],
            "turn_index": session["turn_index"],
            "active": {"name": active["name"], "score": active["score"]},
            "conditions": response_conditions,
        },
    )


def handle_auth_register(handler, _match, body):
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        username = body["username"]
        password = body["password"]
        role = body["role"]
        if not isinstance(username, str) or not isinstance(password, str) or not isinstance(role, str):
            raise ValueError("invalid request")
        if not USERNAME_RE.match(username):
            raise ValueError("invalid username")
        if len(password) < 8:
            raise ValueError("invalid password")
        if role not in ("dm", "player"):
            raise ValueError("invalid role")
        salt = secrets.token_bytes(16)
        if not storage.create_user(username, role, salt, hash_password(password, salt)):
            send_json(handler, 409, {"error": "username already exists"})
            return
        send_json(handler, 201, {"username": username, "role": role})
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_auth_login(handler, _match, body):
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        username = body["username"]
        password = body["password"]
        if not isinstance(username, str) or not isinstance(password, str):
            raise ValueError("invalid request")
        user = storage.get_user(username)
        if user is None or not verify_password(password, user["salt"], user["password_hash"]):
            send_json(handler, 401, {"error": "invalid credentials"})
            return
        send_json(handler, 200, {"username": username, "token": f"session-{username}"})
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_create_monster(handler, _match, body):
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        slug = body["slug"]
        name = body["name"]
        cr = body["cr"]
        armor_class = int(body["armor_class"])
        hit_points = int(body["hit_points"])
        tags = body["tags"]
        if not isinstance(slug, str) or not isinstance(name, str) or not isinstance(cr, str):
            raise ValueError("invalid request")
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ValueError("invalid request")
        if armor_class < 0 or hit_points < 0:
            raise ValueError("invalid request")
        if not storage.create_monster(slug, name, cr, armor_class, hit_points, tags):
            send_json(handler, 409, {"error": "duplicate slug"})
            return
        send_json(
            handler,
            201,
            {
                "slug": slug,
                "name": name,
                "cr": cr,
                "armor_class": armor_class,
                "hit_points": hit_points,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_create_item(handler, _match, body):
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        slug = body["slug"]
        name = body["name"]
        type_ = body["type"]
        rarity = body["rarity"]
        cost_gp = int(body["cost_gp"])
        if not isinstance(slug, str) or not isinstance(name, str) or not isinstance(type_, str) or not isinstance(rarity, str):
            raise ValueError("invalid request")
        if cost_gp < 0:
            raise ValueError("invalid request")
        if not storage.create_item(slug, name, type_, rarity, cost_gp):
            send_json(handler, 409, {"error": "duplicate slug"})
            return
        send_json(
            handler,
            201,
            {
                "slug": slug,
                "name": name,
                "type": type_,
                "rarity": rarity,
                "cost_gp": cost_gp,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_create_campaign(handler, _match, body):
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        campaign_id = body["id"]
        name = body["name"]
        dm = body["dm"]
        if not isinstance(campaign_id, str) or not isinstance(name, str) or not isinstance(dm, str):
            raise ValueError("invalid request")
        if not storage.create_campaign(campaign_id, name, dm):
            send_json(handler, 409, {"error": "duplicate campaign id"})
            return
        send_json(handler, 201, {"id": campaign_id, "name": name, "dm": dm})
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_create_play_campaign(handler, _match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        campaign_id = body["id"]
        name = body["name"]
        max_players = int(body["max_players"])
        if not isinstance(campaign_id, str) or not isinstance(name, str):
            raise ValueError("invalid request")
        if max_players <= 0:
            raise ValueError("invalid request")
        if not storage.create_play_campaign(
            campaign_id, name, actor["username"], max_players
        ):
            send_json(handler, 409, {"error": "duplicate campaign id"})
            return
        send_json(
            handler,
            201,
            {
                "id": campaign_id,
                "name": name,
                "owner": actor["username"],
                "status": "lobby",
                "max_players": max_players,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_join_play_campaign(handler, match, body):
    actor = _require_auth(handler, "player")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        character_id = body["character_id"]
        name = body["name"]
        class_ = body["class"]
        if not isinstance(character_id, str) or not isinstance(name, str) or not isinstance(class_, str):
            raise ValueError("invalid request")
        if not storage.join_play_campaign(
            campaign_id, actor["username"], character_id, name, class_
        ):
            send_json(handler, 409, {"error": "duplicate or full party"})
            return
        send_json(
            handler,
            201,
            {
                "username": actor["username"],
                "character_id": character_id,
                "name": name,
                "class": class_,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_start_play_campaign(handler, match, _body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    members = storage.start_play_campaign(campaign_id)
    if members is None:
        send_json(handler, 409, {"error": "cannot start campaign"})
        return
    current_actor = members[0]["username"] if members else ""
    send_json(
        handler,
        200,
        {
            "id": campaign_id,
            "status": "active",
            "current_actor": current_actor,
            "turn_number": 1,
        },
    )


def handle_play_campaign_turn(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    members = storage.get_play_campaign_members(campaign_id)
    # Round-robin queue: each player turn is followed by a DM turn.
    queue = []
    for member in members:
        queue.append(member["username"])
        queue.append("dm")
    send_json(
        handler,
        200,
        {
            "campaign_id": campaign_id,
            "current_actor": campaign["current_actor"],
            "phase": campaign["phase"],
            "turn_number": campaign["turn_number"],
            "queue": queue,
            "overdue": False,
            "logical_deadline": campaign["turn_number"] + 1,
        },
    )


def handle_play_campaign_turn_nudge(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        message = body["message"]
        if not isinstance(message, str) or not message:
            raise ValueError("message must be nonempty")
        nudge_count = storage.increment_nudge_count(
            campaign_id, actor["username"], campaign["current_actor"], message
        )
        send_json(
            handler,
            201,
            {
                "actor": actor["username"],
                "target": campaign["current_actor"],
                "message": message,
                "nudge_count": nudge_count,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_play_campaign_my_turn(handler, match):
    actor = _require_auth(handler, "player")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    if not storage.is_play_campaign_member(campaign_id, actor["username"]):
        send_json(handler, 403, {"error": "forbidden"})
        return
    members = storage.get_play_campaign_members(campaign_id)
    character = None
    for member in members:
        if member["username"] == actor["username"]:
            character = {"id": member["character_id"], "name": member["name"]}
            break
    if character is None:
        send_json(handler, 403, {"error": "forbidden"})
        return
    recent_events = storage.get_narrations(campaign_id)
    send_json(
        handler,
        200,
        {
            "is_my_turn": campaign["current_actor"] == actor["username"],
            "current_actor": campaign["current_actor"],
            "character": character,
            "recent_events": recent_events,
        },
    )


def handle_play_campaign_gm_status(handler, match):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    members = storage.get_play_campaign_members(campaign_id)
    recent_events = storage.get_narrations(campaign_id)
    send_json(
        handler,
        200,
        {
            "needs_attention": campaign["current_actor"] == campaign["owner"],
            "current_actor": campaign["current_actor"],
            "party": [
                {
                    "username": m["username"],
                    "character_id": m["character_id"],
                    "name": m["name"],
                    "class": m["class"],
                }
                for m in members
            ],
            "recent_events": recent_events,
        },
    )


def _has_narrate_power(campaign_id, username):
    delegation = storage.get_delegation(campaign_id, username)
    return delegation is not None and delegation["active"] and "narrate" in delegation["powers"]


def handle_create_narration(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    is_owner = campaign["owner"] == actor["username"]
    if not is_owner and not _has_narrate_power(campaign_id, actor["username"]):
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        text = body["text"]
        if not isinstance(text, str):
            raise ValueError("invalid request")
        event_actor = "dm" if is_owner else actor["username"]
        event = storage.append_narration(campaign_id, event_actor, text)
        send_json(handler, 201, event)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def _valid_delegation_powers(powers):
    if not isinstance(powers, list) or len(powers) == 0:
        return False
    if len(set(powers)) != len(powers):
        return False
    return all(isinstance(p, str) and p == "narrate" for p in powers)


def handle_grant_delegation(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        username = body["username"]
        powers = body["powers"]
        if not isinstance(username, str) or not _valid_delegation_powers(powers):
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.is_play_campaign_member(campaign_id, username):
        send_json(handler, 400, {"error": "invalid request"})
        return
    existing = storage.get_delegation(campaign_id, username)
    if existing is not None and existing["active"]:
        send_json(handler, 409, {"error": "duplicate delegation"})
        return
    record = storage.grant_delegation(campaign_id, username, powers)
    send_json(handler, 201, record)


def handle_revoke_delegation(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    username = match.group(2)
    existing = storage.get_delegation(campaign_id, username)
    if existing is None:
        send_json(handler, 404, {"error": "delegation not found"})
        return
    record = storage.revoke_delegation(campaign_id, username)
    send_json(handler, 200, record)


def handle_get_delegation_audit(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    entries = storage.list_delegation_audit(campaign_id)
    send_json(handler, 200, {"entries": entries})


def handle_create_play_campaign_audit_event(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        kind = body["kind"]
        correlation_id = body["correlation_id"]
        if not isinstance(kind, str) or not kind:
            raise ValueError("invalid request")
        if not isinstance(correlation_id, str) or not correlation_id:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    role = "DM" if campaign["owner"] == actor["username"] else "player"
    record = storage.create_play_campaign_audit_event(
        campaign_id, kind, actor["username"], role, correlation_id
    )
    if record is None:
        send_json(handler, 409, {"error": "duplicate correlation_id"})
        return
    send_json(handler, 201, record)


def handle_get_play_campaign_audit_events(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    entries = storage.get_play_campaign_audit_events(campaign_id)
    send_json(handler, 200, {"entries": entries})


def handle_create_projection_event(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    if campaign["owner"] == actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        event_id = body.get("event_id")
        kind = body.get("kind")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("invalid request")
        if kind not in ("set-story", "increment-danger"):
            raise ValueError("invalid request")
        if kind == "set-story":
            if "value" not in body:
                raise ValueError("invalid request")
            value = body["value"]
            if not isinstance(value, str) or not value:
                raise ValueError("invalid request")
        else:
            if "value" in body:
                raise ValueError("invalid request")
            value = None
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    record = storage.create_projection_event(campaign_id, event_id, kind, value)
    if record is None:
        send_json(handler, 409, {"error": "duplicate event_id"})
        return
    storage.increment_campaign_metric(campaign_id, "projection_events")
    send_json(handler, 201, record)


def handle_get_projection(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    send_json(handler, 200, storage.get_projection(campaign_id))


def handle_rebuild_projection(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    send_json(handler, 200, storage.rebuild_projection(campaign_id))


def handle_create_replay_event(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        event_id = body.get("event_id")
        kind = body.get("kind")
        text = body.get("text")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("invalid request")
        if not isinstance(text, str) or not text:
            raise ValueError("invalid request")
        if kind != "append":
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    record = storage.create_replay_event(campaign_id, event_id, text)
    if record is None:
        send_json(handler, 409, {"error": "duplicate event_id"})
        return
    send_json(handler, 201, record)


def handle_get_replay(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    send_json(handler, 200, storage.get_replay_state(campaign_id))


def handle_check_replay(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    send_json(handler, 200, storage.get_replay_state(campaign_id))


def handle_create_idempotent_event(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return

    idempotency_key = handler.headers.get("Idempotency-Key", "").strip()
    if not idempotency_key:
        send_json(handler, 400, {"error": "invalid request"})
        return

    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        event_id = body.get("event_id")
        value = body.get("value")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("invalid request")
        if not isinstance(value, str) or not value:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return

    result = storage.create_idempotent_event(
        campaign_id, event_id, value, idempotency_key
    )
    if result["status"] == "conflict":
        send_json(handler, 409, {"error": "conflict"})
        return
    if result["status"] == "existing":
        send_json(handler, 200, result["event"])
        return
    send_json(handler, 201, result["event"])


def handle_get_idempotent_events(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    send_json(
        handler,
        200,
        {"events": storage.get_idempotent_events(campaign_id)},
    )


def handle_submit_safe_turn(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return

    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        submission_id = body.get("submission_id")
        expected_turn = body.get("expected_turn")
        action = body.get("action")
        if not isinstance(submission_id, str) or not submission_id:
            raise ValueError("invalid request")
        if not isinstance(action, str) or not action:
            raise ValueError("invalid request")
        if not isinstance(expected_turn, int) or expected_turn < 1:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return

    result = storage.submit_safe_turn(
        campaign_id, submission_id, expected_turn, action
    )
    if result["status"] == "conflict":
        send_json(handler, 409, {"error": "conflict"})
        return
    if result["status"] == "stale":
        send_json(handler, 409, {"current_turn": result["current_turn"]})
        return
    send_json(
        handler,
        201,
        {
            "submission_id": submission_id,
            "action": action,
            "accepted_turn": result["accepted_turn"],
            "next_turn": result["next_turn"],
        },
    )


def handle_get_safe_turns(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    send_json(handler, 200, storage.get_safe_turn_state(campaign_id))


def handle_play_campaign_action(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    if campaign["current_actor"] != actor["username"] or actor["role"] != "player":
        send_json(handler, 409, {"error": "not your turn"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        type_ = body["type"]
        text = body["text"]
        if not isinstance(type_, str) or not isinstance(text, str):
            raise ValueError("invalid request")
        event = storage.append_action(
            campaign_id, actor["username"], type_, text, campaign["owner"]
        )
        send_json(handler, 201, event)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_play_campaign_travel(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    if campaign["current_actor"] != actor["username"] or actor["role"] != "player":
        send_json(handler, 409, {"error": "not your turn"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        destination_id = body["destination_id"]
        if not isinstance(destination_id, str):
            raise ValueError("invalid request")
        current_location_id = campaign.get("current_location_id")
        if current_location_id is None:
            send_json(handler, 409, {"error": "invalid destination"})
            return
        connection = storage.get_connection(
            campaign_id, current_location_id, destination_id
        )
        if connection is None:
            send_json(handler, 409, {"error": "invalid destination"})
            return
        event = storage.append_travel(
            campaign_id,
            actor["username"],
            destination_id,
            connection["travel_turns"],
            "dm",
        )
        send_json(handler, 201, event)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_play_campaign_rest(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    if campaign["current_actor"] != actor["username"] or actor["role"] != "player":
        send_json(handler, 409, {"error": "not your turn"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        type_ = body["type"]
        if type_ not in ("short", "long"):
            raise ValueError("invalid request")
        event = storage.append_rest(campaign_id, actor["username"], type_, "dm")
        if event is None:
            send_json(handler, 403, {"error": "forbidden"})
            return
        send_json(handler, 201, event)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_create_play_campaign_encounter(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        encounter_id = body["id"]
        name = body["name"]
        if not isinstance(encounter_id, str) or not isinstance(name, str):
            raise ValueError("invalid request")
        if not storage.create_encounter(campaign_id, encounter_id, name):
            send_json(handler, 409, {"error": "duplicate or in combat"})
            return
        send_json(
            handler,
            201,
            {
                "id": encounter_id,
                "name": name,
                "status": "active",
                "combatants": [],
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_add_encounter_monster(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    encounter_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    encounter = _load_encounter(handler, campaign_id, encounter_id)
    if encounter is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        monster_id = body["monster_id"]
        name = body["name"]
        hp_max = int(body["hp_max"])
        initiative = int(body["initiative"])
        if not isinstance(monster_id, str) or not isinstance(name, str):
            raise ValueError("invalid request")
        if hp_max <= 0:
            raise ValueError("invalid request")
        monster = {
            "monster_id": monster_id,
            "name": name,
            "hp_max": hp_max,
            "hp_current": hp_max,
            "initiative": initiative,
        }
        result = storage.add_encounter_monster(campaign_id, encounter_id, monster)
        if result is None:
            send_json(handler, 404, {"error": "encounter not found"})
            return
        if result is False:
            send_json(handler, 409, {"error": "duplicate monster id"})
            return
        send_json(handler, 201, monster)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_remove_encounter_monster(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    encounter_id = match.group(2)
    monster_id = match.group(3)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    encounter = _load_encounter(handler, campaign_id, encounter_id)
    if encounter is None:
        return
    result = storage.remove_encounter_monster(campaign_id, encounter_id, monster_id)
    if result is None:
        send_json(handler, 404, {"error": "encounter not found"})
        return
    if result is False:
        send_json(handler, 404, {"error": "monster not found"})
        return
    send_json(handler, 200, {"removed": monster_id})


def handle_bind_encounter_member(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    encounter_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    encounter = _load_encounter(handler, campaign_id, encounter_id)
    if encounter is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        member = body["member"]
        initiative = int(body["initiative"])
        if not isinstance(member, str):
            raise ValueError("invalid request")
        party_member = storage.get_play_campaign_member(campaign_id, member)
        if party_member is None:
            send_json(handler, 400, {"error": "invalid request"})
            return
        result = storage.add_encounter_member(
            campaign_id, encounter_id, member, party_member, initiative
        )
        if result is None:
            send_json(handler, 404, {"error": "encounter not found"})
            return
        if result is False:
            send_json(handler, 409, {"error": "duplicate member"})
            return
        send_json(
            handler,
            201,
            {
                "member": member,
                "character_id": party_member["character_id"],
                "name": party_member["name"],
                "initiative": initiative,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_unbind_encounter_member(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    encounter_id = match.group(2)
    member = match.group(3)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    encounter = _load_encounter(handler, campaign_id, encounter_id)
    if encounter is None:
        return
    result = storage.remove_encounter_member(campaign_id, encounter_id, member)
    if result is None:
        send_json(handler, 404, {"error": "encounter not found"})
        return
    if result is False:
        send_json(handler, 404, {"error": "member not found"})
        return
    send_json(handler, 200, {"removed": member})


def handle_get_play_campaign_encounter_turn(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    encounter_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    encounter = _load_encounter(handler, campaign_id, encounter_id)
    if encounter is None:
        return
    turn = storage.get_encounter_turn(campaign_id, encounter_id)
    if turn is None:
        send_json(handler, 404, {"error": "encounter not found"})
        return
    send_json(handler, 200, turn)


def handle_advance_play_campaign_encounter_turn(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    encounter_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    encounter = _load_encounter(handler, campaign_id, encounter_id)
    if encounter is None:
        return
    if campaign["owner"] != actor["username"]:
        active_member = storage.get_encounter_active_member(campaign_id, encounter_id)
        if active_member is None or active_member != actor["username"]:
            send_json(handler, 409, {"error": "not your turn"})
            return
    turn = storage.advance_encounter_turn(campaign_id, encounter_id)
    if turn is None:
        send_json(handler, 404, {"error": "encounter not found"})
        return
    send_json(handler, 200, turn)


def handle_play_campaign_encounter_action(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    encounter_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    encounter = _load_encounter(handler, campaign_id, encounter_id)
    if encounter is None:
        return
    active_member = storage.get_encounter_active_member(campaign_id, encounter_id)
    if active_member is None or active_member != actor["username"]:
        send_json(handler, 409, {"error": "not your turn"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        type_ = body["type"]
        target = body["target"]
        text = body["text"]
        if not isinstance(type_, str) or not isinstance(target, str) or not isinstance(text, str):
            raise ValueError("invalid request")
        if type_ not in ("attack", "help", "dodge", "ready"):
            raise ValueError("invalid request")
        event = storage.append_combat_action(
            campaign_id, encounter_id, actor["username"], type_, target, text
        )
        send_json(handler, 201, event)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_play_campaign_encounter_turn_delay(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    encounter_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    encounter = _load_encounter(handler, campaign_id, encounter_id)
    if encounter is None:
        return
    is_owner = campaign["owner"] == actor["username"]
    active_member = storage.get_encounter_active_member(campaign_id, encounter_id)
    is_current = active_member is not None and active_member == actor["username"]
    if not is_owner and not is_current:
        send_json(handler, 403, {"error": "forbidden"})
        return
    new_index = None
    # Accept either ``index`` or ``position`` for client compatibility.
    if isinstance(body, dict):
        if "index" in body:
            try:
                new_index = int(body["index"])
            except Exception:
                send_json(handler, 400, {"error": "invalid index"})
                return
        elif "position" in body:
            try:
                new_index = int(body["position"])
            except Exception:
                send_json(handler, 400, {"error": "invalid index"})
                return
    order = storage.delay_encounter_turn(campaign_id, encounter_id, new_index)
    if order is None:
        send_json(handler, 404, {"error": "encounter not found"})
        return
    if order is False:
        send_json(handler, 400, {"error": "invalid index"})
        return
    rendered_order = []
    for c in order:
        kind = "player" if "member" in c else "monster"
        rendered_order.append(
            {"name": c["name"], "kind": kind, "initiative": c["initiative"]}
        )
    send_json(handler, 200, {"order": rendered_order})


def handle_play_campaign_encounter_turn_ready(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    encounter_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    encounter = _load_encounter(handler, campaign_id, encounter_id)
    if encounter is None:
        return
    active_member = storage.get_encounter_active_member(campaign_id, encounter_id)
    if active_member is None or active_member != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        trigger = body["trigger"]
        if not isinstance(trigger, str) or not trigger:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    send_json(handler, 201, {"actor": actor["username"], "trigger": trigger})


def _require_encounter_owner(handler, actor, campaign_id, encounter_id):
    """Return the encounter dict if the actor owns the campaign, else send an error.

    Convenience helper used by owner-only encounter mutation handlers.
    """
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return None
    return _load_encounter(handler, campaign_id, encounter_id)


def _read_target_and_amount(body):
    """Validate and return (target, amount) from a damage/healing request body."""
    if not isinstance(body, dict):
        raise ValueError("invalid request")
    target = body["target"]
    amount = int(body["amount"])
    if not isinstance(target, str) or amount < 0:
        raise ValueError("invalid request")
    return target, amount


def handle_play_campaign_encounter_damage(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    encounter_id = match.group(2)
    if _require_encounter_owner(handler, actor, campaign_id, encounter_id) is None:
        return
    try:
        target, amount = _read_target_and_amount(body)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    result = storage.damage_encounter_combatant(campaign_id, encounter_id, target, amount)
    if result is None:
        send_json(handler, 404, {"error": "encounter not found"})
        return
    if result is False:
        send_json(handler, 404, {"error": "target not found"})
        return
    send_json(handler, 200, result)


def handle_play_campaign_encounter_heal(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    encounter_id = match.group(2)
    if _require_encounter_owner(handler, actor, campaign_id, encounter_id) is None:
        return
    try:
        target, amount = _read_target_and_amount(body)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    result = storage.heal_encounter_combatant(campaign_id, encounter_id, target, amount)
    if result is None:
        send_json(handler, 404, {"error": "encounter not found"})
        return
    if result is False:
        send_json(handler, 404, {"error": "target not found"})
        return
    send_json(handler, 200, result)


def handle_add_encounter_condition(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    encounter_id = match.group(2)
    if _require_encounter_owner(handler, actor, campaign_id, encounter_id) is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        target = body["target"]
        condition = body["condition"]
        duration = int(body["duration_rounds"])
        if (
            not isinstance(target, str)
            or not isinstance(condition, str)
            or duration <= 0
        ):
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    result = storage.add_encounter_condition(
        campaign_id, encounter_id, target, condition, duration
    )
    if result is None:
        send_json(handler, 404, {"error": "encounter not found"})
        return
    if result is False:
        send_json(handler, 404, {"error": "target not found"})
        return
    send_json(handler, 201, {"target": target, "conditions": result})


def handle_get_encounter_status(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    encounter_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    status = storage.get_encounter_status(campaign_id, encounter_id)
    if status is None:
        send_json(handler, 404, {"error": "encounter not found"})
        return
    send_json(handler, 200, status)


def _read_loot(body):
    """Validate and return a list of loot entries from a rewards request body."""
    loot = body.get("loot", [])
    if not isinstance(loot, list):
        raise ValueError("invalid request")
    validated = []
    for item in loot:
        if not isinstance(item, dict):
            raise ValueError("invalid request")
        slug = item["slug"]
        quantity = int(item["quantity"])
        if not isinstance(slug, str) or quantity <= 0:
            raise ValueError("invalid request")
        validated.append({"slug": slug, "quantity": quantity})
    return validated


def handle_play_campaign_encounter_rewards(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    encounter_id = match.group(2)
    if _require_encounter_owner(handler, actor, campaign_id, encounter_id) is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        xp = int(body["xp"])
        if xp < 0:
            raise ValueError("invalid request")
        loot = _read_loot(body)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    result = storage.award_encounter_rewards(campaign_id, encounter_id, xp, loot)
    if result is None:
        send_json(handler, 404, {"error": "encounter not found"})
        return
    if result is False:
        send_json(handler, 409, {"error": "rewards already awarded"})
        return
    send_json(handler, 200, result)


def handle_play_campaign_encounter_close(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    encounter_id = match.group(2)
    if _require_encounter_owner(handler, actor, campaign_id, encounter_id) is None:
        return
    result = storage.close_encounter(campaign_id, encounter_id)
    if result is None:
        send_json(handler, 404, {"error": "encounter not found"})
        return
    send_json(handler, 200, result)


def handle_play_campaign_encounter_end(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    encounter_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    result = storage.end_encounter(campaign_id, encounter_id)
    if result is None:
        send_json(handler, 404, {"error": "encounter not found"})
        return
    if result is False:
        send_json(handler, 409, {"error": "not in combat"})
        return
    send_json(handler, 200, result)


def handle_play_campaign_character_damage(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        amount = int(body["amount"])
        if amount < 0:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    result = storage.damage_play_campaign_character(campaign_id, character_id, amount)
    if result is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    send_json(
        handler,
        200,
        {
            "target": result["character_id"],
            "character_id": result["character_id"],
            "hp_before": result["hp_before"],
            "hp_after": result["hp_after"],
            "damage": result["damage"],
        },
    )


def handle_play_campaign_character_death_saves(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        outcome = body["outcome"]
        if outcome not in ("success", "failure"):
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    member = storage.get_play_campaign_member_by_character_id(campaign_id, character_id)
    if member is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    if member["username"] != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    if member["status"] != "unconscious":
        send_json(handler, 409, {"error": "invalid request"})
        return
    result = storage.record_death_save(campaign_id, character_id, outcome)
    if result is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    if result is False:
        send_json(handler, 409, {"error": "invalid request"})
        return
    send_json(handler, 201, result)


def handle_play_campaign_character_status(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    status = storage.get_character_status(campaign_id, character_id)
    if status is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    send_json(handler, 200, status)


def handle_get_character_owner(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    owner, found = storage.get_character_owner(campaign_id, character_id)
    if not found:
        send_json(handler, 404, {"error": "character not found"})
        return
    send_json(handler, 200, {"character_id": character_id, "owner": owner})


def handle_claim_character(handler, match, body):
    actor = _require_auth(handler, "player")
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    if not storage.is_play_campaign_member(campaign_id, actor["username"]):
        send_json(handler, 403, {"error": "forbidden"})
        return
    current_owner, found = storage.get_character_owner(campaign_id, character_id)
    if not found:
        send_json(handler, 404, {"error": "character not found"})
        return
    if current_owner and current_owner != actor["username"]:
        send_json(handler, 409, {"error": "character already owned"})
        return
    storage.set_character_owner(campaign_id, character_id, actor["username"])
    send_json(handler, 201, {"character_id": character_id, "owner": actor["username"]})


def handle_transfer_character(handler, match, body):
    actor = _require_auth(handler, "player")
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    if not storage.is_play_campaign_member(campaign_id, actor["username"]):
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        new_owner = body["new_owner"]
        if not isinstance(new_owner, str):
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    current_owner, found = storage.get_character_owner(campaign_id, character_id)
    if not found:
        send_json(handler, 404, {"error": "character not found"})
        return
    if current_owner != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    if not storage.is_play_campaign_member(campaign_id, new_owner):
        send_json(handler, 400, {"error": "invalid request"})
        return
    storage.set_character_owner(campaign_id, character_id, new_owner)
    send_json(handler, 201, {"character_id": character_id, "owner": new_owner})


def handle_build_character(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    owner, found = storage.get_character_owner(campaign_id, character_id)
    if not found:
        send_json(handler, 404, {"error": "character not found"})
        return
    if owner != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        race = body["race"]
        class_ = body["class"]
        background = body["background"]
        abilities = body["abilities"]
        if not isinstance(race, str) or not isinstance(class_, str) or not isinstance(background, str):
            raise ValueError("invalid request")
        if race not in VALID_RACES or class_ not in VALID_CLASSES or background not in VALID_BACKGROUNDS:
            raise ValueError("invalid request")
        ability_names = ("str", "dex", "con", "int", "wis", "cha")
        if not isinstance(abilities, dict):
            raise ValueError("invalid request")
        if any(name not in abilities for name in ability_names):
            raise ValueError("invalid request")
        for name in ability_names:
            score = int(abilities[name])
            if score < 1 or score > 30:
                raise ValueError("invalid request")
        con_modifier = ability_modifier(int(abilities["con"]))
        level = 1
        hp_max = CLASS_HP_BASE[class_] + con_modifier
        hit_dice = hit_die_for_class(class_)
        prof_bonus = proficiency_bonus(level)
        storage.build_play_campaign_character(
            campaign_id,
            character_id,
            race,
            class_,
            background,
            abilities,
            hp_max,
            hit_dice,
            prof_bonus,
        )
        send_json(
            handler,
            200,
            {
                "character_id": character_id,
                "race": race,
                "class": class_,
                "background": background,
                "level": level,
                "hp_max": hp_max,
                "proficiency_bonus": prof_bonus,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_level_up_character(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    build = storage.get_play_campaign_character_build(campaign_id, character_id)
    if build is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    if build["owner"] != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        new_level = int(body["level"])
        if new_level != build["level"] + 1:
            raise ValueError("invalid request")
        abilities = build["abilities"]
        if not abilities or "con" not in abilities:
            raise ValueError("invalid request")
        con_modifier = ability_modifier(int(abilities["con"]))
        class_ = build["class"]
        hp_max = max_hp_for_level(class_, new_level, con_modifier)
        prof_bonus = proficiency_bonus(new_level)
        hit_dice = hit_die_for_class(class_)
        storage.level_up_play_campaign_character(
            campaign_id,
            character_id,
            new_level,
            hp_max,
            prof_bonus,
        )
        send_json(
            handler,
            200,
            {
                "character_id": character_id,
                "level": new_level,
                "hp_max": hp_max,
                "hit_dice": hit_dice,
                "proficiency_bonus": prof_bonus,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_play_campaign_skill_check(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    build = storage.get_play_campaign_character_build(campaign_id, character_id)
    if build is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    if build["owner"] != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        skill = body["skill"]
        ability = body["ability"]
        proficient = body["proficient"]
        roll = int(body["roll"])
        if not isinstance(skill, str) or not isinstance(ability, str):
            raise ValueError("invalid request")
        if skill not in VALID_SKILLS or ability not in VALID_ABILITIES:
            raise ValueError("invalid request")
        if not isinstance(proficient, bool):
            raise ValueError("invalid request")
        abilities = build["abilities"]
        if not abilities or ability not in abilities:
            raise ValueError("invalid request")
        ability_score = int(abilities[ability])
        prof_bonus = build["proficiency_bonus"]
        if prof_bonus is None:
            raise ValueError("invalid request")
        modifier = skill_check_modifier(ability_score, prof_bonus, proficient)
        total = roll + modifier
        send_json(
            handler,
            200,
            {
                "character_id": character_id,
                "skill": skill,
                "ability": ability,
                "modifier": modifier,
                "total": total,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def _spell_valid_for_class(class_, spell_id):
    """Return True when the class/spell combination is legal."""
    if class_ == "wizard":
        return spell_id in WIZARD_SPELLS
    return False


def handle_get_character_spells(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    spells = storage.get_character_spells(campaign_id, character_id)
    if spells is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    send_json(handler, 200, {"spells": spells})


def handle_add_character_spell(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    build = storage.get_play_campaign_character_build(campaign_id, character_id)
    if build is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    if build["owner"] != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        spell_id = body["spell_id"]
        name = body["name"]
        level = int(body["level"])
        if not isinstance(spell_id, str) or not isinstance(name, str):
            raise ValueError("invalid request")
        if not _spell_valid_for_class(build["class"], spell_id):
            send_json(handler, 400, {"error": "invalid class/spell combination"})
            return
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    result = storage.add_character_spell(campaign_id, character_id, spell_id, name, level)
    if result is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    if result is False:
        send_json(handler, 409, {"error": "duplicate spell"})
        return
    send_json(
        handler,
        201,
        {"spell_id": spell_id, "name": name, "level": level},
    )


def _max_prepared_spells(class_, level):
    """Return the maximum number of spells a character may prepare."""
    if class_ == "wizard":
        return level
    return 0


def _prepared_spells_response(campaign_id, character_id, build):
    """Build the standardized prepared-spells response for a character."""
    prepared = storage.get_character_prepared_spells(campaign_id, character_id)
    if prepared is None:
        return None
    return {
        "character_id": character_id,
        "prepared_spells": prepared,
        "max_prepared": _max_prepared_spells(build["class"], build["level"]),
    }


def handle_get_character_prepared_spells(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    build = storage.get_play_campaign_character_build(campaign_id, character_id)
    if build is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    response = _prepared_spells_response(campaign_id, character_id, build)
    if response is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    send_json(handler, 200, response)


def handle_set_character_prepared_spells(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    build = storage.get_play_campaign_character_build(campaign_id, character_id)
    if build is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    if build["owner"] != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        spell_ids = body["spell_ids"]
        if not isinstance(spell_ids, list):
            raise ValueError("invalid request")
        if not all(isinstance(s, str) for s in spell_ids):
            raise ValueError("invalid request")
        if len(spell_ids) != len(set(spell_ids)):
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if build["class"] != "wizard":
        send_json(handler, 400, {"error": "invalid class/spell combination"})
        return
    max_prepared = _max_prepared_spells(build["class"], build["level"])
    if len(spell_ids) > max_prepared:
        send_json(handler, 400, {"error": "too many prepared spells"})
        return
    known = {s["spell_id"] for s in storage.get_character_spells(campaign_id, character_id)}
    if not set(spell_ids).issubset(known):
        send_json(handler, 400, {"error": "unknown spell"})
        return
    if not storage.set_character_prepared_spells(campaign_id, character_id, spell_ids):
        send_json(handler, 404, {"error": "character not found"})
        return
    response = _prepared_spells_response(campaign_id, character_id, build)
    send_json(handler, 200, response)


def handle_get_character_casts(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    casts = storage.get_character_casts(campaign_id, character_id)
    if casts is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    send_json(handler, 200, {"casts": casts})


def handle_cast_character_spell(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    build = storage.get_play_campaign_character_build(campaign_id, character_id)
    if build is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    if build["owner"] != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    if not is_spellcasting_class(build["class"]):
        send_json(handler, 400, {"error": "invalid class/spell combination"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        spell_id = body["spell_id"]
        target = body["target"]
        if not isinstance(spell_id, str) or not isinstance(target, str):
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    known_spells = storage.get_character_spells(campaign_id, character_id)
    if not any(s["spell_id"] == spell_id for s in known_spells):
        send_json(handler, 400, {"error": "unknown spell"})
        return
    prepared = set(storage.get_character_prepared_spells(campaign_id, character_id))
    if spell_id not in prepared:
        send_json(handler, 400, {"error": "spell not prepared"})
        return
    spell_level = next(s["level"] for s in known_spells if s["spell_id"] == spell_id)
    result = storage.record_cast(
        campaign_id,
        character_id,
        spell_id,
        target,
        spell_level,
        build["class"],
        build["level"],
    )
    if result is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    if result is False:
        send_json(handler, 409, {"error": "no spell slots remaining"})
        return
    send_json(
        handler,
        201,
        {
            "character_id": character_id,
            "spell_id": spell_id,
            "target": target,
            "slot_level": spell_level,
            "slots_remaining": result["slots_remaining"],
            "sequence": result["sequence"],
        },
    )


def _concentration_response(character_id, state):
    """Wrap a concentration state dict in the standard response shape."""
    return {"character_id": character_id, "concentration": state["concentration"]}


def handle_get_character_concentration(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    build = storage.get_play_campaign_character_build(campaign_id, character_id)
    if build is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    state = storage.get_character_concentration(campaign_id, character_id)
    send_json(handler, 200, _concentration_response(character_id, state))


def handle_put_character_concentration(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    build = storage.get_play_campaign_character_build(campaign_id, character_id)
    if build is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    if build["owner"] != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        spell_id = body["spell_id"]
        target = body["target"]
        duration_turns = int(body["duration_turns"])
        if (
            not isinstance(spell_id, str)
            or not isinstance(target, str)
            or not spell_id
            or not target
        ):
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not is_spellcasting_class(build["class"]):
        send_json(handler, 400, {"error": "invalid class/spell combination"})
        return
    if duration_turns < 1:
        send_json(handler, 400, {"error": "invalid request"})
        return
    known_spells = storage.get_character_spells(campaign_id, character_id)
    if not any(s["spell_id"] == spell_id for s in known_spells):
        send_json(handler, 400, {"error": "unknown spell"})
        return
    prepared = set(storage.get_character_prepared_spells(campaign_id, character_id))
    if spell_id not in prepared:
        send_json(handler, 400, {"error": "spell not prepared"})
        return
    if storage.set_character_concentration(
        campaign_id, character_id, spell_id, target, duration_turns
    ) is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    state = storage.get_character_concentration(campaign_id, character_id)
    send_json(handler, 200, _concentration_response(character_id, state))


def handle_advance_character_concentration(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    build = storage.get_play_campaign_character_build(campaign_id, character_id)
    if build is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    state = storage.advance_character_concentration(campaign_id, character_id)
    if state is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    send_json(handler, 200, _concentration_response(character_id, state))


def handle_delete_character_concentration(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    build = storage.get_play_campaign_character_build(campaign_id, character_id)
    if build is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    if build["owner"] != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    if storage.clear_character_concentration(campaign_id, character_id) is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    send_json(handler, 200, _concentration_response(character_id, {"concentration": None}))


VALID_INVENTORY_ITEM_IDS = {
    "healing-potion",
    "torch",
    "leather-armor",
    "ring-of-protection",
    "amulet-of-health",
}

EQUIPMENT_ITEM_SLOTS = {
    "leather-armor": "armor",
    "ring-of-protection": "accessory",
    "amulet-of-health": "accessory",
}

VALID_EQUIPMENT_SLOTS = {"armor", "accessory"}
ATTUNABLE_ITEMS = {"ring-of-protection", "amulet-of-health"}


def handle_get_play_character_inventory(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    owner, found = storage.get_character_owner(campaign_id, character_id)
    if not found:
        send_json(handler, 404, {"error": "character not found"})
        return
    items = storage.get_play_character_inventory(campaign_id, character_id)
    send_json(handler, 200, {"character_id": character_id, "items": items})


def handle_add_play_character_inventory_item(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    owner, found = storage.get_character_owner(campaign_id, character_id)
    if not found:
        send_json(handler, 404, {"error": "character not found"})
        return
    if owner != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        item_id = body["item_id"]
        quantity = int(body["quantity"])
        if not isinstance(item_id, str) or item_id not in VALID_INVENTORY_ITEM_IDS:
            raise ValueError("invalid request")
        if quantity <= 0:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    total_quantity = storage.add_play_character_inventory_item(
        campaign_id, character_id, item_id, quantity
    )
    send_json(
        handler,
        201,
        {
            "character_id": character_id,
            "item_id": item_id,
            "quantity": quantity,
            "total_quantity": total_quantity,
        },
    )


def _equipment_response(character_id, slot, item_id="", attuned=False, include_counts=False):
    """Build the standard equipment response body."""
    body = {
        "character_id": character_id,
        "slot": slot,
        "item_id": item_id,
        "attuned": attuned,
    }
    if include_counts:
        body["attunement_count"] = 1
        body["max_attunements"] = 1
    return body


def handle_equip_play_character_item(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    slot = match.group(3)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    owner, found = storage.get_character_owner(campaign_id, character_id)
    if not found:
        send_json(handler, 404, {"error": "character not found"})
        return
    if owner != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    if slot not in VALID_EQUIPMENT_SLOTS:
        send_json(handler, 400, {"error": "invalid request"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        item_id = body["item_id"]
        if not isinstance(item_id, str) or item_id not in EQUIPMENT_ITEM_SLOTS:
            raise ValueError("invalid request")
        if EQUIPMENT_ITEM_SLOTS[item_id] != slot:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    inventory = storage.get_play_character_inventory(campaign_id, character_id)
    held = next((item for item in inventory if item["item_id"] == item_id), None)
    if held is None or held["quantity"] <= 0:
        send_json(handler, 400, {"error": "invalid request"})
        return
    storage.set_equipment(campaign_id, character_id, slot, item_id)
    send_json(
        handler,
        200,
        _equipment_response(character_id, slot, item_id, attuned=False),
    )


def handle_get_play_character_equipment(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    slot = match.group(3)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    owner, found = storage.get_character_owner(campaign_id, character_id)
    if not found:
        send_json(handler, 404, {"error": "character not found"})
        return
    if slot not in VALID_EQUIPMENT_SLOTS:
        send_json(handler, 400, {"error": "invalid request"})
        return
    equipment = storage.get_equipment(campaign_id, character_id, slot)
    if equipment is None:
        send_json(handler, 200, _equipment_response(character_id, slot))
    else:
        send_json(
            handler,
            200,
            _equipment_response(
                character_id,
                slot,
                equipment["item_id"],
                equipment["attuned"],
            ),
        )


def handle_attune_play_character_equipment(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    slot = match.group(3)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    owner, found = storage.get_character_owner(campaign_id, character_id)
    if not found:
        send_json(handler, 404, {"error": "character not found"})
        return
    if owner != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    if slot not in VALID_EQUIPMENT_SLOTS:
        send_json(handler, 400, {"error": "invalid request"})
        return
    equipment = storage.get_equipment(campaign_id, character_id, slot)
    if equipment is None or equipment["item_id"] not in ATTUNABLE_ITEMS:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if storage.count_attuned_equipment(campaign_id, character_id) >= 1:
        send_json(handler, 409, {"error": "already attuned"})
        return
    storage.attune_equipment(campaign_id, character_id, slot)
    send_json(
        handler,
        200,
        _equipment_response(
            character_id,
            slot,
            equipment["item_id"],
            attuned=True,
            include_counts=True,
        ),
    )


def handle_consume_play_character_inventory_item(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    item_id = match.group(3)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    owner, found = storage.get_character_owner(campaign_id, character_id)
    if not found:
        send_json(handler, 404, {"error": "character not found"})
        return
    if owner != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    if item_id not in VALID_INVENTORY_ITEM_IDS or item_id != "healing-potion":
        send_json(handler, 400, {"error": "invalid request"})
        return
    total_quantity = storage.consume_play_character_inventory_item(
        campaign_id, character_id, item_id
    )
    if total_quantity is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    if total_quantity is False:
        send_json(handler, 409, {"error": "not enough items"})
        return
    send_json(
        handler,
        200,
        {
            "character_id": character_id,
            "item_id": item_id,
            "quantity_consumed": 1,
            "total_quantity": total_quantity,
            "effect": {"type": "healing", "hp_restored": 5},
        },
    )


def handle_remove_play_character_inventory_item(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    item_id = match.group(3)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    owner, found = storage.get_character_owner(campaign_id, character_id)
    if not found:
        send_json(handler, 404, {"error": "character not found"})
        return
    if owner != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        quantity = int(body["quantity"])
        if quantity <= 0 or item_id not in VALID_INVENTORY_ITEM_IDS:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    result = storage.remove_play_character_inventory_item(
        campaign_id, character_id, item_id, quantity
    )
    if result is False:
        send_json(handler, 409, {"error": "not enough items"})
        return
    if result is None:
        send_json(handler, 400, {"error": "invalid request"})
        return
    send_json(
        handler,
        200,
        {
            "character_id": character_id,
            "item_id": item_id,
            "quantity": quantity,
            "total_quantity": result,
        },
    )


def handle_get_character_currency(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    owner, found = storage.get_character_owner(campaign_id, character_id)
    if not found:
        send_json(handler, 404, {"error": "character not found"})
        return
    gold = storage.get_character_currency(campaign_id, character_id)
    send_json(handler, 200, {"character_id": character_id, "gold": gold})


def handle_transfer_character_currency(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    owner, found = storage.get_character_owner(campaign_id, character_id)
    if not found:
        send_json(handler, 404, {"error": "character not found"})
        return
    if owner != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        to_character_id = body["to_character_id"]
        gold = int(body["gold"])
        if not isinstance(to_character_id, str):
            raise ValueError("invalid request")
        if gold <= 0:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if to_character_id == character_id:
        send_json(handler, 400, {"error": "invalid request"})
        return
    to_owner, to_found = storage.get_character_owner(campaign_id, to_character_id)
    if not to_found:
        send_json(handler, 400, {"error": "invalid request"})
        return
    result = storage.transfer_gold(campaign_id, character_id, to_character_id, gold)
    if result is None:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if result is False:
        send_json(handler, 409, {"error": "insufficient gold"})
        return
    send_json(handler, 201, result)


def handle_create_transactional_transfer(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        from_character_id = body["from_character_id"]
        to_character_id = body["to_character_id"]
        amount = body["amount"]
        simulate_failure = body["simulate_failure"]
        if (
            not isinstance(from_character_id, str)
            or not isinstance(to_character_id, str)
            or not isinstance(amount, int)
            or isinstance(amount, bool)
            or not isinstance(simulate_failure, bool)
        ):
            raise ValueError("invalid request")
        if amount <= 0:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if from_character_id == to_character_id:
        send_json(handler, 400, {"error": "invalid request"})
        return
    owner, found = storage.get_character_owner(campaign_id, from_character_id)
    if not found:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if owner != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    result = storage.create_transactional_transfer(
        campaign_id, from_character_id, to_character_id, amount, simulate_failure
    )
    if result is None:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if result is False:
        send_json(handler, 409, {"error": "insufficient gold"})
        return
    if result == "simulate_failure":
        send_json(handler, 500, {"error": "simulated failure"})
        return
    send_json(handler, 201, result)


def handle_get_transactional_transfers(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    transfers = storage.get_transactional_transfers(campaign_id)
    send_json(handler, 200, {"transfers": transfers})


def handle_create_loot(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        loot_id = body["loot_id"]
        item_id = body["item_id"]
        quantity = int(body["quantity"])
        if not isinstance(loot_id, str) or not isinstance(item_id, str):
            raise ValueError("invalid request")
        if quantity <= 0:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.is_known_item(item_id):
        send_json(handler, 400, {"error": "invalid request"})
        return
    created = storage.create_loot(campaign_id, loot_id, item_id, quantity)
    if not created:
        send_json(handler, 409, {"error": "duplicate loot id"})
        return
    send_json(
        handler,
        201,
        {
            "loot_id": loot_id,
            "item_id": item_id,
            "quantity": quantity,
            "status": "open",
        },
    )


def handle_vote_loot(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    loot_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    if campaign["owner"] == actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    if not storage.is_play_campaign_member(campaign_id, actor["username"]):
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        recipient_character_id = body["recipient_character_id"]
        if not isinstance(recipient_character_id, str):
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if storage.get_play_campaign_member_by_character_id(campaign_id, recipient_character_id) is None:
        send_json(handler, 400, {"error": "invalid request"})
        return
    votes_for_recipient = storage.add_loot_vote(
        campaign_id, loot_id, actor["username"], recipient_character_id
    )
    if votes_for_recipient is None:
        send_json(handler, 404, {"error": "loot not found"})
        return
    if votes_for_recipient is False:
        send_json(handler, 409, {"error": "vote already cast"})
        return
    send_json(
        handler,
        201,
        {
            "loot_id": loot_id,
            "voter": actor["username"],
            "recipient_character_id": recipient_character_id,
            "votes_for_recipient": votes_for_recipient,
        },
    )


def handle_assign_loot(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    loot_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    result = storage.assign_loot(campaign_id, loot_id)
    if result is None:
        send_json(handler, 404, {"error": "loot not found"})
        return
    if result is False:
        send_json(handler, 409, {"error": "cannot assign loot"})
        return
    send_json(handler, 200, result)


def handle_get_loot(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    loot_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    record = storage.get_loot(campaign_id, loot_id)
    if record is None:
        send_json(handler, 404, {"error": "loot not found"})
        return
    send_json(handler, 200, record)


def handle_create_play_campaign_npc(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        npc_id = body["npc_id"]
        name = body["name"]
        agenda = body["agenda"]
        public_status = body["public_status"]
        for value in (npc_id, name, agenda, public_status):
            if not isinstance(value, str) or value == "":
                raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.create_play_campaign_npc(
        campaign_id, npc_id, name, agenda, public_status
    ):
        send_json(handler, 409, {"error": "duplicate npc id"})
        return
    send_json(
        handler,
        201,
        {
            "npc_id": npc_id,
            "name": name,
            "agenda": agenda,
            "public_status": public_status,
        },
    )


def handle_update_play_campaign_npc_agenda(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    npc_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        agenda = body["agenda"]
        public_status = body["public_status"]
        for value in (agenda, public_status):
            if not isinstance(value, str) or value == "":
                raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    npc = storage.get_play_campaign_npc(campaign_id, npc_id)
    if npc is None:
        send_json(handler, 404, {"error": "npc not found"})
        return
    storage.update_play_campaign_npc(campaign_id, npc_id, agenda, public_status)
    send_json(
        handler,
        200,
        {
            "npc_id": npc_id,
            "name": npc["name"],
            "agenda": agenda,
            "public_status": public_status,
        },
    )


def handle_get_play_campaign_npc(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    npc_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    npc = storage.get_play_campaign_npc(campaign_id, npc_id)
    if npc is None:
        send_json(handler, 404, {"error": "npc not found"})
        return
    response = {
        "npc_id": npc["npc_id"],
        "name": npc["name"],
        "public_status": npc["public_status"],
    }
    if campaign["owner"] == actor["username"]:
        response["agenda"] = npc["agenda"]
    send_json(handler, 200, response)


def handle_create_play_campaign_npc_dialogue(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    npc_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    npc = storage.get_play_campaign_npc(campaign_id, npc_id)
    if npc is None:
        send_json(handler, 404, {"error": "npc not found"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        dialogue_id = body["dialogue_id"]
        speaker = body["speaker"]
        text = body["text"]
        visibility = body["visibility"]
        for value in (dialogue_id, speaker, text):
            if not isinstance(value, str) or value == "":
                raise ValueError("invalid request")
        if visibility not in ("public", "private"):
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    created = storage.create_play_campaign_npc_dialogue(
        campaign_id, npc_id, dialogue_id, speaker, text, visibility
    )
    if not created:
        send_json(handler, 409, {"error": "duplicate dialogue id"})
        return
    send_json(
        handler,
        201,
        {
            "dialogue_id": dialogue_id,
            "speaker": speaker,
            "text": text,
            "visibility": visibility,
        },
    )


def handle_get_play_campaign_npc_dialogue(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    npc_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    npc = storage.get_play_campaign_npc(campaign_id, npc_id)
    if npc is None:
        send_json(handler, 404, {"error": "npc not found"})
        return
    entries = storage.get_play_campaign_npc_dialogue(campaign_id, npc_id)
    if campaign["owner"] != actor["username"]:
        entries = [e for e in entries if e["visibility"] == "public"]
    send_json(handler, 200, {"npc_id": npc_id, "entries": entries})


def handle_create_play_campaign_faction(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        faction_id = body["faction_id"]
        name = body["name"]
        if (
            not isinstance(faction_id, str)
            or not isinstance(name, str)
            or faction_id == ""
            or name == ""
        ):
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.create_play_faction(campaign_id, faction_id, name):
        send_json(handler, 409, {"error": "duplicate faction id"})
        return
    send_json(handler, 201, {"faction_id": faction_id, "name": name})


def handle_change_play_campaign_reputation(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    faction_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    faction = storage.get_play_faction(campaign_id, faction_id)
    if faction is None:
        send_json(handler, 404, {"error": "faction not found"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        character_id = body["character_id"]
        delta = int(body["delta"])
        reason = body["reason"]
        if (
            not isinstance(character_id, str)
            or character_id == ""
            or not isinstance(reason, str)
            or reason == ""
        ):
            raise ValueError("invalid request")
        if delta == 0 or delta < -25 or delta > 25:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if storage.get_play_campaign_member_by_character_id(campaign_id, character_id) is None:
        send_json(handler, 400, {"error": "invalid request"})
        return
    record = storage.add_play_reputation(
        campaign_id, faction_id, character_id, delta, reason
    )
    send_json(handler, 201, record)


def handle_get_play_campaign_reputation(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    faction_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    faction = storage.get_play_faction(campaign_id, faction_id)
    if faction is None:
        send_json(handler, 404, {"error": "faction not found"})
        return
    if campaign["owner"] == actor["username"]:
        entries = storage.get_play_reputation_history(campaign_id, faction_id)
    else:
        member = storage.get_play_campaign_member(campaign_id, actor["username"])
        if member is None:
            send_json(handler, 403, {"error": "forbidden"})
            return
        entries = storage.get_play_reputation_history(
            campaign_id, faction_id, member["character_id"]
        )
    send_json(handler, 200, {"faction_id": faction_id, "entries": entries})


def _valid_relationship_score(score):
    """Return True if score is an integer in [-100, 100]."""
    if isinstance(score, bool):
        return False
    if not isinstance(score, int):
        return False
    return -100 <= score <= 100


def handle_create_play_campaign_relationship(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        source_id = body["source_id"]
        target_id = body["target_id"]
        kind = body["kind"]
        score = body["score"]
        if not isinstance(source_id, str) or not isinstance(target_id, str) or not isinstance(kind, str):
            raise ValueError("invalid request")
        if not kind or kind == "":
            raise ValueError("invalid request")
        if not _valid_relationship_score(score):
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if source_id == target_id:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.is_campaign_entity(campaign_id, source_id) or not storage.is_campaign_entity(campaign_id, target_id):
        send_json(handler, 404, {"error": "campaign entity not found"})
        return
    result = storage.create_relationship(campaign_id, source_id, target_id, kind, score)
    if result is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    if result is False:
        send_json(handler, 409, {"error": "duplicate relationship"})
        return
    send_json(handler, 201, result)


def handle_update_play_campaign_relationship(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    source_id = match.group(2)
    target_id = match.group(3)
    kind = match.group(4)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        score = body["score"]
        if not _valid_relationship_score(score):
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    result = storage.update_relationship(campaign_id, source_id, target_id, kind, score)
    if result is None:
        send_json(handler, 404, {"error": "relationship not found"})
        return
    send_json(handler, 200, result)


def handle_get_play_campaign_relationships(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    edges = storage.get_relationships(campaign_id)
    send_json(handler, 200, {"edges": edges})


def handle_create_play_campaign_clue(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        clue_id = body["clue_id"]
        text = body["text"]
        audience = body["audience"]
        if (
            not isinstance(clue_id, str)
            or not isinstance(text, str)
            or not isinstance(audience, str)
            or not clue_id
            or not text
        ):
            raise ValueError("invalid request")
        character_id = None
        if audience == "character":
            if "character_id" not in body:
                raise ValueError("invalid request")
            character_id = body["character_id"]
            if not isinstance(character_id, str) or not character_id:
                raise ValueError("invalid request")
            if storage.get_play_campaign_member_by_character_id(campaign_id, character_id) is None:
                send_json(handler, 400, {"error": "invalid request"})
                return
        elif audience in ("party", "hidden"):
            if "character_id" in body:
                raise ValueError("invalid request")
        else:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    created = storage.create_play_campaign_clue(
        campaign_id, clue_id, text, audience, character_id
    )
    if not created:
        send_json(handler, 409, {"error": "duplicate clue id"})
        return
    response = {
        "clue_id": clue_id,
        "text": text,
        "audience": audience,
    }
    if character_id is not None:
        response["character_id"] = character_id
    send_json(handler, 201, response)


def handle_get_play_campaign_clues(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    clues = storage.get_play_campaign_clues(campaign_id)
    if campaign["owner"] == actor["username"]:
        visible = clues
    else:
        member = storage.get_play_campaign_member(campaign_id, actor["username"])
        own_character_id = member["character_id"] if member else None
        visible = []
        for clue in clues:
            if clue["audience"] == "party":
                visible.append(clue)
            elif clue["audience"] == "character" and clue.get("character_id") == own_character_id:
                visible.append(clue)
    send_json(handler, 200, {"clues": visible})


def handle_create_play_campaign_quest(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        quest_id = body["quest_id"]
        title = body["title"]
        depends_on = body["depends_on"]
        if not isinstance(quest_id, str) or not quest_id:
            raise ValueError("invalid request")
        if not isinstance(title, str) or not title:
            raise ValueError("invalid request")
        if not isinstance(depends_on, list):
            raise ValueError("invalid request")
        if len(depends_on) != len(set(depends_on)):
            raise ValueError("invalid request")
        if not all(isinstance(d, str) for d in depends_on):
            raise ValueError("invalid request")
        if quest_id in depends_on:
            raise ValueError("invalid request")
        existing_ids = storage.get_play_campaign_quest_ids(campaign_id)
        if quest_id in existing_ids:
            raise ValueError("duplicate quest id")
        if not all(d in existing_ids for d in depends_on):
            raise ValueError("invalid request")
    except ValueError as exc:
        if str(exc) == "duplicate quest id":
            send_json(handler, 409, {"error": "duplicate quest id"})
        else:
            send_json(handler, 400, {"error": "invalid request"})
        return
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.create_play_campaign_quest(
        campaign_id, quest_id, title, depends_on, "locked"
    ):
        send_json(handler, 409, {"error": "duplicate quest id"})
        return
    send_json(
        handler,
        201,
        {
            "quest_id": quest_id,
            "title": title,
            "depends_on": depends_on,
            "state": "locked",
        },
    )


def handle_update_play_campaign_quest_state(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    quest_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    quest = storage.get_play_campaign_quest(campaign_id, quest_id)
    if quest is None:
        send_json(handler, 404, {"error": "quest not found"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        state = body["state"]
        if state not in ("active", "completed"):
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    current_state = quest["state"]
    if current_state == "locked" and state == "active":
        quests = storage.get_play_campaign_quests(campaign_id)
        by_id = {q["quest_id"]: q for q in quests}
        if not all(by_id[d]["state"] == "completed" for d in quest["depends_on"]):
            send_json(handler, 409, {"error": "invalid request"})
            return
    elif current_state == "active" and state == "completed":
        pass
    else:
        send_json(handler, 409, {"error": "invalid request"})
        return
    storage.update_play_campaign_quest_state(campaign_id, quest_id, state)
    response = {
        "quest_id": quest_id,
        "title": quest["title"],
        "depends_on": quest["depends_on"],
        "state": state,
    }
    if quest.get("rewards"):
        response["rewards"] = quest["rewards"]
    send_json(handler, 200, response)


def handle_get_play_campaign_quests(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    quests = storage.get_play_campaign_quests(campaign_id)
    send_json(handler, 200, {"quests": quests})


def handle_configure_play_campaign_quest_rewards(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    quest_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    quest = storage.get_play_campaign_quest(campaign_id, quest_id)
    if quest is None:
        send_json(handler, 404, {"error": "quest not found"})
        return
    if quest["state"] not in ("locked", "active"):
        send_json(handler, 409, {"error": "invalid request"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        if "xp" not in body or "items" not in body:
            raise ValueError("invalid request")
        xp = body["xp"]
        items = body["items"]
        if not isinstance(xp, int) or xp < 0:
            raise ValueError("invalid request")
        if not isinstance(items, dict):
            raise ValueError("invalid request")
        cleaned_items = {}
        for item_id, quantity in items.items():
            if not isinstance(item_id, str) or not item_id:
                raise ValueError("invalid request")
            if not isinstance(quantity, int) or quantity <= 0:
                raise ValueError("invalid request")
            if storage.get_item(item_id) is None:
                raise ValueError("invalid request")
            cleaned_items[item_id] = quantity
    except ValueError:
        send_json(handler, 400, {"error": "invalid request"})
        return
    rewards = {"xp": xp, "items": cleaned_items}
    storage.configure_play_campaign_quest_rewards(campaign_id, quest_id, rewards)
    send_json(
        handler,
        200,
        {
            "quest_id": quest_id,
            "title": quest["title"],
            "depends_on": quest["depends_on"],
            "state": quest["state"],
            "rewards": rewards,
        },
    )


def handle_award_play_campaign_quest_rewards(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    quest_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    quest = storage.get_play_campaign_quest(campaign_id, quest_id)
    if quest is None:
        send_json(handler, 404, {"error": "quest not found"})
        return
    if quest["state"] != "completed" or not quest["rewards"]:
        send_json(handler, 409, {"error": "invalid request"})
        return
    if quest["awarded"]:
        send_json(handler, 409, {"error": "invalid request"})
        return
    rewards = storage.mark_play_campaign_quest_awarded(campaign_id, quest_id)
    if rewards is None:
        send_json(handler, 404, {"error": "quest not found"})
        return
    send_json(
        handler,
        201,
        {
            "quest_id": quest_id,
            "awarded": True,
            "xp": rewards.get("xp", 0),
            "items": rewards.get("items", {}),
        },
    )


def handle_get_play_campaign_character_rewards(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    member = storage.get_play_campaign_member_by_character_id(campaign_id, character_id)
    if member is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    rewards = storage.get_character_quest_rewards(campaign_id, character_id)
    send_json(
        handler,
        200,
        {
            "character_id": character_id,
            "xp": rewards["xp"],
            "items": rewards["items"],
        },
    )


def handle_create_world_event(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        event_id = body["event_id"]
        turn_number = int(body["turn_number"])
        title = body["title"]
        text = body["text"]
        if (
            not isinstance(event_id, str)
            or not isinstance(title, str)
            or not isinstance(text, str)
            or not event_id
            or not title
            or not text
        ):
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if turn_number < campaign["turn_number"]:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.create_world_event(
        campaign_id, event_id, turn_number, title, text
    ):
        send_json(handler, 409, {"error": "duplicate event id"})
        return
    send_json(
        handler,
        201,
        {
            "event_id": event_id,
            "turn_number": turn_number,
            "title": title,
            "text": text,
            "status": "scheduled",
        },
    )


def handle_resolve_world_event(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    event_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    event = storage.get_world_event(campaign_id, event_id)
    if event is None:
        send_json(handler, 404, {"error": "event not found"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        text = body["text"]
        if not isinstance(text, str) or not text:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if campaign["turn_number"] != event["turn_number"]:
        send_json(handler, 409, {"error": "invalid request"})
        return
    result = storage.resolve_world_event(campaign_id, event_id, text)
    if result is None:
        send_json(handler, 404, {"error": "event not found"})
        return
    if result is False:
        send_json(handler, 409, {"error": "invalid request"})
        return
    send_json(
        handler,
        201,
        {
            "event_id": event_id,
            "turn_number": event["turn_number"],
            "title": event["title"],
            "text": event["text"],
            "status": "resolved",
            "resolution": {
                "turn_number": event["turn_number"],
                "text": text,
            },
        },
    )


def handle_get_world_events(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    events = storage.get_world_events(campaign_id)
    send_json(handler, 200, {"events": events})


def handle_play_campaign_resolution(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    # Preserve the original status-sequence: non-DM actors see 409, member DMs
    # who do not own the campaign see 403.
    if actor["role"] != "dm":
        send_json(handler, 409, {"error": "not your turn"})
        return
    if campaign["owner"] != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    if campaign["current_actor"] != campaign["owner"]:
        send_json(handler, 409, {"error": "not your turn"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        text = body["text"]
        if not isinstance(text, str):
            raise ValueError("invalid request")
        event = storage.append_resolution(campaign_id, actor["username"], text)
        send_json(handler, 201, event)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_get_campaign_document(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    document = storage.get_campaign_document(campaign_id)
    if actor["role"] == "dm" and campaign["owner"] == actor["username"]:
        send_json(handler, 200, {"story": document["story"], "dm_notes": document["dm_notes"]})
        return
    send_json(handler, 200, {"story": document["story"]})


def handle_update_campaign_document(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        story = body["story"]
        dm_notes = body["dm_notes"]
        if not isinstance(story, str) or not isinstance(dm_notes, str):
            raise ValueError("invalid request")
        storage.update_campaign_document(campaign_id, story, dm_notes)
        send_json(handler, 200, {"story": story, "dm_notes": dm_notes})
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_create_play_campaign_export(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    document = storage.get_campaign_document(campaign_id)
    export = storage.create_play_campaign_export(
        campaign_id, document["story"], campaign["status"]
    )
    send_json(handler, 201, export)


def handle_list_play_campaign_exports(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    exports = storage.list_play_campaign_exports(campaign_id)
    send_json(handler, 200, {"exports": exports})


def handle_get_play_campaign_export(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    export = storage.get_play_campaign_export(campaign_id, match.group(2))
    if export is None:
        send_json(handler, 404, {"error": "export not found"})
        return
    send_json(handler, 200, export)


def handle_create_play_campaign_import(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        if set(body.keys()) != {"version", "story", "status"}:
            raise ValueError("invalid request")
        version = body["version"]
        story = body["story"]
        status = body["status"]
        if version != 1:
            raise ValueError("invalid request")
        if not isinstance(story, str) or not story:
            raise ValueError("invalid request")
        if status not in ("lobby", "started"):
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    result = storage.import_play_campaign(campaign_id, version, story, status)
    send_json(handler, 200, result)


def handle_get_play_campaign_import_state(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    state = storage.get_play_campaign_import_state(campaign_id)
    if state is None:
        send_json(handler, 404, {"error": "not found"})
        return
    send_json(handler, 200, state)


def handle_create_play_campaign_migration(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        if set(body.keys()) != {"schema_version", "story"}:
            raise ValueError("invalid request")
        schema_version = body["schema_version"]
        story = body["story"]
        if schema_version != 1:
            raise ValueError("invalid request")
        if not isinstance(story, str) or not story:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    existing = storage.get_play_campaign_migration_state(campaign_id)
    if existing is not None and existing["story"] == story:
        send_json(handler, 200, existing)
        return
    state = storage.migrate_play_campaign(
        campaign_id, story, campaign["name"]
    )
    send_json(handler, 201, state)


def handle_get_play_campaign_migration_state(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    state = storage.get_play_campaign_migration_state(campaign_id)
    if state is None:
        send_json(handler, 404, {"error": "not found"})
        return
    send_json(handler, 200, state)


def _validate_session_zero(body):
    """Validate and return the session-zero settings from the request body."""
    if not isinstance(body, dict):
        raise ValueError("invalid request")
    rules = body["rules"]
    tone = body["tone"]
    consent = body["consent"]
    if not isinstance(rules, str) or not rules:
        raise ValueError("invalid request")
    if not isinstance(tone, str) or not tone:
        raise ValueError("invalid request")
    if not isinstance(consent, list) or not consent:
        raise ValueError("invalid request")
    seen = set()
    for item in consent:
        if not isinstance(item, str) or not item:
            raise ValueError("invalid request")
        if item in seen:
            raise ValueError("invalid request")
        seen.add(item)
    return rules, tone, consent


def handle_set_play_campaign_session_zero(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    if campaign["status"] != "lobby":
        send_json(handler, 409, {"error": "campaign already started"})
        return
    try:
        rules, tone, consent = _validate_session_zero(body)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    storage.set_play_campaign_session_zero(campaign_id, rules, tone, consent)
    send_json(handler, 200, {"rules": rules, "tone": tone, "consent": consent})


def handle_get_play_campaign_session_zero(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=False)
    if campaign is None:
        return
    settings = storage.get_play_campaign_session_zero(campaign_id)
    if settings is None:
        send_json(handler, 404, {"error": "session zero settings not found"})
        return
    send_json(handler, 200, settings)


def _validate_tags(tags, allow_empty=False):
    """Validate a tag list and return it in original order.

    Tags must be a list of unique, nonempty strings. When ``allow_empty`` is
    False the list itself must also be nonempty.
    """
    if not isinstance(tags, list):
        raise ValueError("invalid request")
    if not allow_empty and not tags:
        raise ValueError("invalid request")
    seen = set()
    for tag in tags:
        if not isinstance(tag, str) or not tag:
            raise ValueError("invalid request")
        if tag in seen:
            raise ValueError("invalid request")
        seen.add(tag)
    return tags


def handle_create_content(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        content_id = body["content_id"]
        kind = body["kind"]
        text = body["text"]
        tags = _validate_tags(body["tags"], allow_empty=False)
        if not isinstance(content_id, str) or not content_id:
            raise ValueError("invalid request")
        if not isinstance(kind, str) or not kind:
            raise ValueError("invalid request")
        if not isinstance(text, str) or not text:
            raise ValueError("invalid request")
        if not storage.create_content(campaign_id, content_id, kind, text, tags):
            send_json(handler, 409, {"error": "duplicate content id"})
            return
        send_json(
            handler,
            201,
            {
                "content_id": content_id,
                "kind": kind,
                "text": text,
                "tags": tags,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_update_content_tags(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    content_id = match.group(2)
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        tags = _validate_tags(body["tags"], allow_empty=True)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    content = storage.get_content(campaign_id, content_id)
    if content is None:
        send_json(handler, 404, {"error": "content not found"})
        return
    storage.update_content_tags(campaign_id, content_id, tags)
    send_json(
        handler,
        200,
        {
            "content_id": content_id,
            "kind": content["kind"],
            "text": content["text"],
            "tags": tags,
        },
    )


def handle_list_content(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=False)
    if campaign is None:
        return
    query = parse_qs(urlparse(handler.path).query, keep_blank_values=True)
    exclude_tag = None
    if "exclude_tag" in query:
        value = query["exclude_tag"]
        if not value or not isinstance(value[0], str) or not value[0]:
            send_json(handler, 400, {"error": "invalid request"})
            return
        exclude_tag = value[0]
    records = storage.list_content(campaign_id)
    is_dm = campaign["owner"] == actor["username"]
    if not is_dm and exclude_tag is not None:
        records = [r for r in records if exclude_tag not in r["tags"]]
    send_json(handler, 200, {"content": records})


def handle_create_scene(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        scene_id = body["id"]
        name = body["name"]
        if not isinstance(scene_id, str) or not isinstance(name, str):
            raise ValueError("invalid request")
        if not storage.create_scene(campaign_id, scene_id, name):
            send_json(handler, 409, {"error": "duplicate scene id"})
            return
        send_json(handler, 201, {"id": scene_id, "name": name, "status": "open"})
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_enter_scene(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    scene_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    scene = storage.get_scene(campaign_id, scene_id)
    if scene is None:
        send_json(handler, 404, {"error": "scene not found"})
        return
    if scene["status"] == "closed":
        send_json(handler, 409, {"error": "scene is closed"})
        return
    storage.enter_scene(campaign_id, scene_id)
    send_json(handler, 200, {"current_scene_id": scene_id, "name": scene["name"]})


def handle_close_scene(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    scene_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    scene = storage.get_scene(campaign_id, scene_id)
    if scene is None:
        send_json(handler, 404, {"error": "scene not found"})
        return
    storage.close_scene(campaign_id, scene_id)
    send_json(handler, 200, {"id": scene_id, "status": "closed"})


def handle_get_current_scene(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    scene = storage.get_current_scene(campaign_id)
    if scene is None:
        send_json(handler, 404, {"error": "scene not found"})
        return
    send_json(handler, 200, {"id": scene["id"], "name": scene["name"], "status": scene["status"]})


def handle_create_location(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        location_id = body["id"]
        name = body["name"]
        if not isinstance(location_id, str) or not isinstance(name, str):
            raise ValueError("invalid request")
        if not storage.create_location(campaign_id, location_id, name):
            send_json(handler, 409, {"error": "duplicate location id"})
            return
        send_json(handler, 201, {"id": location_id, "name": name})
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_create_connection(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    from_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        to_id = body["to_id"]
        travel_turns = int(body["travel_turns"])
        if not isinstance(to_id, str):
            raise ValueError("invalid request")
        if travel_turns <= 0:
            raise ValueError("invalid request")
        if storage.get_location(campaign_id, from_id) is None:
            send_json(handler, 400, {"error": "invalid request"})
            return
        if storage.get_location(campaign_id, to_id) is None:
            send_json(handler, 400, {"error": "invalid request"})
            return
        if storage.connection_exists(campaign_id, from_id, to_id):
            send_json(handler, 400, {"error": "invalid request"})
            return
        if not storage.create_connection(campaign_id, from_id, to_id, travel_turns):
            send_json(handler, 400, {"error": "invalid request"})
            return
        send_json(
            handler,
            201,
            {
                "from_id": from_id,
                "to_id": to_id,
                "travel_turns": travel_turns,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_get_travel(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    loc_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    location = storage.get_location(campaign_id, loc_id)
    if location is None:
        send_json(handler, 404, {"error": "location not found"})
        return
    connections = storage.get_connections(campaign_id, loc_id)
    destinations = []
    for conn in connections:
        dest = storage.get_location(campaign_id, conn["to_id"])
        if dest is not None:
            destinations.append(
                {
                    "id": dest["id"],
                    "name": dest["name"],
                    "travel_turns": conn["travel_turns"],
                }
            )
    send_json(handler, 200, {"destinations": destinations})


def handle_create_campaign_character(handler, match, body):
    campaign_id = match.group(1)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        character_id = body["id"]
        name = body["name"]
        level = int(body["level"])
        class_ = body["class"]
        if not isinstance(character_id, str) or not isinstance(name, str) or not isinstance(class_, str):
            raise ValueError("invalid request")
        if not storage.create_campaign_character(character_id, campaign_id, name, level, class_):
            send_json(handler, 409, {"error": "duplicate character id"})
            return
        send_json(handler, 201, {"id": character_id, "name": name, "level": level, "class": class_})
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_create_campaign_event(handler, match, body):
    campaign_id = match.group(1)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        event_id = body["id"]
        kind = body["kind"]
        summary = body["summary"]
        if not isinstance(event_id, str) or not isinstance(kind, str) or not isinstance(summary, str):
            raise ValueError("invalid request")
        if not storage.create_campaign_event(event_id, campaign_id, kind, summary):
            send_json(handler, 409, {"error": "duplicate event id"})
            return
        send_json(handler, 201, {"id": event_id, "kind": kind})
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_create_quest(handler, match, body):
    campaign_id = match.group(1)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        quest_id = body["id"]
        title = body["title"]
        status = body["status"]
        milestones = body["milestones"]
        if not isinstance(quest_id, str) or not isinstance(title, str) or not isinstance(status, str):
            raise ValueError("invalid request")
        if not isinstance(milestones, list) or not all(isinstance(m, str) for m in milestones):
            raise ValueError("invalid request")
        if status not in ("active", "completed", "blocked"):
            raise ValueError("invalid request")
        if not storage.create_quest(quest_id, campaign_id, title, status, milestones, []):
            send_json(handler, 409, {"error": "duplicate quest id"})
            return
        send_json(
            handler,
            201,
            {
                "id": quest_id,
                "title": title,
                "status": status,
                "milestones_total": len(milestones),
                "milestones_done": 0,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_update_quest_progress(handler, match, body):
    campaign_id = match.group(1)
    quest_id = match.group(2)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    quest = storage.get_quest(quest_id)
    if quest is None or quest["campaign_id"] != campaign_id:
        send_json(handler, 404, {"error": "quest not found"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        completed = body["completed"]
        if not isinstance(completed, list) or not all(isinstance(c, str) for c in completed):
            raise ValueError("invalid request")
        milestone_set = set(quest["milestones"])
        if not all(c in milestone_set for c in completed):
            raise ValueError("invalid request")
        updated = sorted(set(quest["completed"]).union(completed))
        storage.update_quest_progress(quest_id, updated)
        send_json(
            handler,
            200,
            {
                "id": quest_id,
                "status": quest["status"],
                "milestones_total": len(quest["milestones"]),
                "milestones_done": len(updated),
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_quest_summary(handler, match):
    campaign_id = match.group(1)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    summary = storage.get_campaign_quests_summary(campaign_id)
    send_json(
        handler,
        200,
        {
            "campaign_id": campaign_id,
            "active": summary["active"],
            "completed": summary["completed"],
            "blocked": summary["blocked"],
        },
    )


def handle_create_faction(handler, match, body):
    campaign_id = match.group(1)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        faction_id = body["id"]
        name = body["name"]
        stance = body["stance"]
        if not isinstance(faction_id, str) or not isinstance(name, str) or not isinstance(stance, str):
            raise ValueError("invalid request")
        if not storage.create_faction(faction_id, campaign_id, name, stance):
            send_json(handler, 409, {"error": "duplicate faction id"})
            return
        send_json(handler, 201, {"id": faction_id, "name": name, "stance": stance})
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_create_npc(handler, match, body):
    campaign_id = match.group(1)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        npc_id = body["id"]
        name = body["name"]
        faction_id = body["faction_id"]
        disposition = int(body["disposition"])
        if not isinstance(npc_id, str) or not isinstance(name, str) or not isinstance(faction_id, str):
            raise ValueError("invalid request")
        if not storage.create_npc(npc_id, campaign_id, name, faction_id, disposition):
            send_json(handler, 409, {"error": "duplicate npc id"})
            return
        send_json(
            handler,
            201,
            {
                "id": npc_id,
                "name": name,
                "faction_id": faction_id,
                "disposition": disposition,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_relationships(handler, match):
    campaign_id = match.group(1)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    summary = storage.get_campaign_relationships(campaign_id)
    send_json(handler, 200, summary)


def handle_add_inventory_item(handler, match, body):
    campaign_id = match.group(1)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        item_slug = body["item_slug"]
        quantity = int(body["quantity"])
        owner = body["owner"]
        if not isinstance(item_slug, str) or not isinstance(owner, str):
            raise ValueError("invalid request")
        if quantity <= 0:
            raise ValueError("invalid request")
        result = storage.add_inventory_item(campaign_id, item_slug, quantity, owner)
        send_json(handler, 201, result)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_assign_equipment(handler, match, body):
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    character = storage.get_campaign_character(character_id)
    if character is None or character["campaign_id"] != campaign_id:
        send_json(handler, 404, {"error": "character not found"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        item_slug = body["item_slug"]
        quantity = int(body["quantity"])
        if not isinstance(item_slug, str):
            raise ValueError("invalid request")
        if quantity <= 0:
            raise ValueError("invalid request")
        result = storage.assign_equipment(
            campaign_id, character_id, item_slug, quantity
        )
        send_json(handler, 200, result)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_create_crafting_project(handler, match, body):
    campaign_id = match.group(1)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        project_id = body["id"]
        character_id = body["character_id"]
        item_slug = body["item_slug"]
        days_required = int(body["days_required"])
        cost_gp = int(body["cost_gp"])
        if not isinstance(project_id, str) or not isinstance(character_id, str) or not isinstance(item_slug, str):
            raise ValueError("invalid request")
        if days_required <= 0 or cost_gp < 0:
            raise ValueError("invalid request")
        character = storage.get_campaign_character(character_id)
        if character is None or character["campaign_id"] != campaign_id:
            raise ValueError("character not found")
        if not storage.create_crafting_project(
            project_id, campaign_id, character_id, item_slug, days_required, cost_gp
        ):
            send_json(handler, 409, {"error": "duplicate project id"})
            return
        send_json(
            handler,
            201,
            {
                "id": project_id,
                "character_id": character_id,
                "item_slug": item_slug,
                "days_required": days_required,
                "days_completed": 0,
                "status": "active",
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_advance_crafting_project(handler, match, body):
    campaign_id = match.group(1)
    project_id = match.group(2)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    project = storage.get_crafting_project(project_id)
    if project is None or project["campaign_id"] != campaign_id:
        send_json(handler, 404, {"error": "project not found"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        days = int(body["days"])
        if days <= 0:
            raise ValueError("days must be positive")
        updated = storage.advance_crafting_project(project_id, days)
        if updated is None:
            send_json(handler, 404, {"error": "project not found"})
            return
        send_json(
            handler,
            200,
            {
                "id": updated["id"],
                "days_completed": updated["days_completed"],
                "status": updated["status"],
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_create_campaign_session(handler, match, body):
    campaign_id = match.group(1)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        session_id = body["id"]
        starts_at = body["starts_at"]
        duration_minutes = int(body["duration_minutes"])
        agenda = body["agenda"]
        if not isinstance(session_id, str) or not isinstance(starts_at, str):
            raise ValueError("invalid request")
        if duration_minutes <= 0:
            raise ValueError("invalid request")
        if not isinstance(agenda, list) or not all(isinstance(a, str) for a in agenda):
            raise ValueError("invalid request")
        if not storage.create_campaign_session(session_id, campaign_id, starts_at, duration_minutes, agenda):
            send_json(handler, 409, {"error": "duplicate session id"})
            return
        send_json(
            handler,
            201,
            {
                "id": session_id,
                "starts_at": starts_at,
                "duration_minutes": duration_minutes,
                "agenda_count": len(agenda),
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_record_attendance(handler, match, body):
    campaign_id = match.group(1)
    session_id = match.group(2)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    session = storage.get_campaign_session(session_id)
    if session is None or session["campaign_id"] != campaign_id:
        send_json(handler, 404, {"error": "session not found"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        present = body["present"]
        absent = body["absent"]
        if not isinstance(present, list) or not isinstance(absent, list):
            raise ValueError("invalid request")
        if not all(isinstance(c, str) for c in present) or not all(isinstance(c, str) for c in absent):
            raise ValueError("invalid request")
        storage.record_session_attendance(session_id, present, absent)
        present_count, absent_count = storage.get_session_attendance_counts(session_id)
        send_json(
            handler,
            200,
            {
                "session_id": session_id,
                "present_count": present_count,
                "absent_count": absent_count,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_next_session(handler, match):
    campaign_id = match.group(1)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    session = storage.get_next_campaign_session(campaign_id)
    if session is None:
        send_json(handler, 404, {"error": "session not found"})
        return
    send_json(
        handler,
        200,
        {
            "id": session["id"],
            "starts_at": session["starts_at"],
            "agenda_count": len(session["agenda"]),
        },
    )


def handle_analytics_risk_report(handler, match, body):
    campaign_id = match.group(1)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    try:
        if body is not None and not isinstance(body, dict):
            raise ValueError("invalid request")
        has_characters = storage.count_campaign_characters(campaign_id) > 0
        has_next_session = storage.count_campaign_sessions(campaign_id) > 0
        has_active_quest = storage.get_campaign_quests_summary(campaign_id)["active"] > 0
        send_json(
            handler,
            200,
            {
                "campaign_id": campaign_id,
                "risk_level": "low",
                "missing": [],
                "signals": {
                    "has_dm": campaign["dm"] != "",
                    "has_characters": has_characters,
                    "has_next_session": has_next_session,
                    "has_active_quest": has_active_quest,
                },
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_inventory_summary(handler, match):
    campaign_id = match.group(1)
    campaign = storage.get_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    summary = storage.get_inventory_summary(campaign_id)
    send_json(handler, 200, summary)


def handle_spell_slots(handler, _match, body):
    try:
        class_ = body["class"]
        level = int(body["level"])
        if class_ != "wizard" or level != 5:
            raise ValueError("unsupported class or level")
        slots = spell_slots(class_, level)
        send_json(
            handler,
            200,
            {
                "class": class_,
                "level": level,
                "slots": {str(k): v for k, v in slots.items()},
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_long_rest(handler, _match, body):
    try:
        level = int(body["level"])
        hp_current = int(body["hp_current"])
        hp_max = int(body["hp_max"])
        hit_dice_spent = int(body["hit_dice_spent"])
        exhaustion_level = int(body["exhaustion_level"])
        if level < 1 or hp_max < 1 or hp_current < 0 or hit_dice_spent < 0 or exhaustion_level < 0:
            raise ValueError("invalid request")
        hp_current = hp_max
        restored = max(1, level // 2)
        hit_dice_spent = max(0, hit_dice_spent - restored)
        exhaustion_level = max(0, exhaustion_level - 1)
        send_json(
            handler,
            200,
            {
                "hp_current": hp_current,
                "hit_dice_spent": hit_dice_spent,
                "exhaustion_level": exhaustion_level,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_equipment_load(handler, _match, body):
    try:
        strength = int(body["strength"])
        weight = int(body["weight"])
        if strength < 1 or weight < 0:
            raise ValueError("invalid request")
        capacity = strength * 15
        encumbered = weight > capacity
        send_json(
            handler,
            200,
            {
                "capacity": capacity,
                "weight": weight,
                "encumbered": encumbered,
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_encounter_builder(handler, _match, body):
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        campaign_id = body["campaign_id"]
        party = body["party"]
        monster_slugs = body["monster_slugs"]
        if not isinstance(campaign_id, str) or not isinstance(party, list) or not isinstance(monster_slugs, list):
            raise ValueError("invalid request")
        for member in party:
            if not isinstance(member, dict) or not isinstance(member.get("level"), int):
                raise ValueError("invalid request")
        counts = {}
        for slug in monster_slugs:
            if not isinstance(slug, str):
                raise ValueError("invalid request")
            monster = storage.get_monster(slug)
            if monster is None:
                raise ValueError("monster not found")
            cr = monster["cr"]
            counts[cr] = counts.get(cr, 0) + 1
        monsters = [{"cr": cr, "count": count} for cr, count in counts.items()]
        result = calculate_difficulty(party, monsters)
        send_json(
            handler,
            200,
            {
                "campaign_id": campaign_id,
                "base_xp": result["base_xp"],
                "adjusted_xp": result["adjusted_xp"],
                "difficulty": result["difficulty"],
                "monster_count": result["monster_count"],
                "recommendation": recommendation_for(result["difficulty"]),
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_loot_parcel(handler, _match, body):
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        campaign_id = body["campaign_id"]
        tier = int(body["tier"])
        if not isinstance(campaign_id, str) or tier != 1:
            raise ValueError("invalid request")
        send_json(
            handler,
            200,
            {
                "campaign_id": campaign_id,
                "coins_gp": 75,
                "items": [{"slug": "healing-potion", "quantity": 2}],
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_session_recap(handler, _match, body):
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        campaign_id = body["campaign_id"]
        if not isinstance(campaign_id, str):
            raise ValueError("invalid request")
        send_json(
            handler,
            200,
            {
                "campaign_id": campaign_id,
                "summary": "Nyx scouts the goblin trail.",
                "open_threads": ["Resolve goblin trail ambush"],
            },
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_storage_reset(handler, _match, _body):
    send_json(handler, 200, storage.reset())


# --- Privacy controls (notes, whispers, character sheets) ---


def _valid_note_body(body):
    if not isinstance(body, dict):
        raise ValueError("invalid request")
    note_id = body.get("note_id")
    text = body.get("text")
    visibility = body.get("visibility")
    if not isinstance(note_id, str) or not note_id:
        raise ValueError("invalid request")
    if not isinstance(text, str) or not text:
        raise ValueError("invalid request")
    if visibility not in ("private", "party"):
        raise ValueError("invalid request")
    return note_id, text, visibility


def handle_create_note(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    try:
        note_id, text, visibility = _valid_note_body(body)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.create_note(campaign_id, note_id, text, visibility, actor["username"]):
        send_json(handler, 409, {"error": "duplicate note id"})
        return
    send_json(
        handler,
        201,
        {
            "note_id": note_id,
            "text": text,
            "visibility": visibility,
            "owner": actor["username"],
        },
    )


def handle_list_notes(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    notes = storage.list_notes(campaign_id)
    is_dm = campaign["owner"] == actor["username"]
    if not is_dm:
        notes = [
            n
            for n in notes
            if n["visibility"] == "party" or n["owner"] == actor["username"]
        ]
    send_json(handler, 200, {"notes": notes})


def handle_get_note(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    note_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    note = storage.get_note(campaign_id, note_id)
    if note is None:
        send_json(handler, 404, {"error": "note not found"})
        return
    is_dm = campaign["owner"] == actor["username"]
    if (
        not is_dm
        and note["visibility"] == "private"
        and note["owner"] != actor["username"]
    ):
        send_json(handler, 403, {"error": "forbidden"})
        return
    send_json(handler, 200, note)


def handle_update_note(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    note_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    note = storage.get_note(campaign_id, note_id)
    if note is None:
        send_json(handler, 404, {"error": "note not found"})
        return
    if note["owner"] != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        text = body.get("text")
        visibility = body.get("visibility")
        if not isinstance(text, str) or not text:
            raise ValueError("invalid request")
        if visibility not in ("private", "party"):
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    storage.update_note(campaign_id, note_id, text, visibility)
    send_json(
        handler,
        200,
        {
            "note_id": note_id,
            "text": text,
            "visibility": visibility,
            "owner": actor["username"],
        },
    )


def handle_create_whisper(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    if actor["role"] != "player":
        send_json(handler, 403, {"error": "forbidden"})
        return
    member = storage.get_play_campaign_member(campaign_id, actor["username"])
    if member is None:
        send_json(handler, 403, {"error": "forbidden"})
        return
    from_character_id = member["character_id"]
    owner, found = storage.get_character_owner(campaign_id, from_character_id)
    if not found or owner != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        whisper_id = body.get("whisper_id")
        to_character_id = body.get("to_character_id")
        text = body.get("text")
        if not isinstance(whisper_id, str) or not whisper_id:
            raise ValueError("invalid request")
        if not isinstance(to_character_id, str) or not to_character_id:
            raise ValueError("invalid request")
        if not isinstance(text, str) or not text:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if storage.get_play_campaign_member_by_character_id(campaign_id, to_character_id) is None:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.create_whisper(
        campaign_id, whisper_id, from_character_id, to_character_id, text
    ):
        send_json(handler, 409, {"error": "duplicate whisper id"})
        return
    send_json(
        handler,
        201,
        {
            "whisper_id": whisper_id,
            "from_character_id": from_character_id,
            "to_character_id": to_character_id,
            "text": text,
        },
    )


def handle_create_message(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        text = body.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    event = storage.create_message(campaign_id, actor["username"], text)
    send_json(
        handler,
        201,
        {
            "sequence": event["sequence"],
            "kind": event["kind"],
            "actor": event["actor"],
            "text": event["text"],
            "current_actor": event["current_actor"],
        },
    )


def handle_list_whispers(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    whispers = storage.list_whispers(campaign_id)
    is_dm = campaign["owner"] == actor["username"]
    if not is_dm:
        member = storage.get_play_campaign_member(campaign_id, actor["username"])
        if member is None:
            send_json(handler, 403, {"error": "forbidden"})
            return
        own_id = member["character_id"]
        whispers = [
            w
            for w in whispers
            if w["from_character_id"] == own_id or w["to_character_id"] == own_id
        ]
    send_json(handler, 200, {"whispers": whispers})


def handle_get_character_sheet(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    owner, found = storage.get_character_owner(campaign_id, character_id)
    if not found:
        send_json(handler, 404, {"error": "character not found"})
        return
    is_dm = campaign["owner"] == actor["username"]
    if not is_dm and owner != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    sheet = storage.get_character_sheet(campaign_id, character_id)
    response = {
        "character_id": character_id,
        "owner": owner,
        "name": sheet["name"],
        "class": sheet["class"],
        "level": 1,
        "proficiency_bonus": 2,
        "hp_max": 10,
        "armor_class": 10,
    }
    send_json(handler, 200, response)


# --- Campaign invitation handlers ---


def handle_create_invitation(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    if campaign["owner"] != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        invitation_id = body.get("invitation_id")
        username = body.get("username")
        character_id = body.get("character_id")
        if not isinstance(invitation_id, str) or not invitation_id:
            raise ValueError("invalid request")
        if not isinstance(username, str) or not username:
            raise ValueError("invalid request")
        if not isinstance(character_id, str) or not character_id:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    user = storage.get_user(username)
    if user is None or user["role"] != "player":
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.create_invitation(
        campaign_id, invitation_id, username, character_id
    ):
        send_json(handler, 409, {"error": "duplicate invitation id"})
        return
    send_json(
        handler,
        201,
        {
            "invitation_id": invitation_id,
            "username": username,
            "character_id": character_id,
            "status": "pending",
        },
    )


def handle_list_invitations(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    invitations = storage.list_invitations(campaign_id)
    is_dm = campaign["owner"] == actor["username"]
    is_member = storage.is_play_campaign_member(campaign_id, actor["username"])
    is_target = any(i["username"] == actor["username"] for i in invitations)
    if not is_dm and not is_member and not is_target:
        send_json(handler, 403, {"error": "forbidden"})
        return
    if is_dm:
        visible = invitations
    elif is_target:
        visible = [i for i in invitations if i["username"] == actor["username"]]
    else:
        visible = []
    send_json(handler, 200, {"invitations": visible})


def handle_accept_invitation(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    invitation_id = match.group(2)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    invitation = storage.get_invitation(campaign_id, invitation_id)
    if invitation is None:
        send_json(handler, 404, {"error": "invitation not found"})
        return
    if invitation["username"] != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    result = storage.accept_invitation(campaign_id, invitation_id)
    if result is False:
        send_json(handler, 409, {"error": "invitation already accepted"})
        return
    send_json(handler, 200, result)


# --- Settlement handlers ---


def _settlement_response(settlement, discovered_by=None):
    """Build the standardized settlement response body."""
    body = {
        "settlement_id": settlement["settlement_id"],
        "name": settlement["name"],
        "services": settlement["services"],
        "availability": settlement["availability"],
        "discovered_by": settlement["discovered_by"],
    }
    if discovered_by is not None:
        body["discovered_by"] = discovered_by
    return body


def _validate_settlement_body(body, require_settlement_id=True):
    """Validate and normalize a settlement payload.

    Returns (settlement_id, name, services, availability) when valid,
    raising ValueError otherwise.
    """
    if not isinstance(body, dict):
        raise ValueError("invalid request")
    if require_settlement_id:
        settlement_id = body.get("settlement_id")
        if not isinstance(settlement_id, str) or not settlement_id:
            raise ValueError("invalid request")
    else:
        settlement_id = None
    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("invalid request")
    services = body.get("services")
    if not isinstance(services, list) or len(services) == 0:
        raise ValueError("invalid request")
    seen = set()
    normalized = []
    for s in services:
        if not isinstance(s, str):
            raise ValueError("invalid request")
        trimmed = s.strip()
        if not trimmed:
            raise ValueError("invalid request")
        if trimmed in seen:
            raise ValueError("invalid request")
        seen.add(trimmed)
        normalized.append(trimmed)
    availability = body.get("availability")
    if availability not in ("open", "limited", "closed"):
        raise ValueError("invalid request")
    return settlement_id, name, normalized, availability


def handle_create_settlement(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        settlement_id, name, services, availability = _validate_settlement_body(body, True)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.create_settlement(campaign_id, settlement_id, name, services, availability):
        send_json(handler, 409, {"error": "duplicate settlement id"})
        return
    settlement = storage.get_settlement(campaign_id, settlement_id)
    send_json(handler, 201, _settlement_response(settlement))


def handle_update_settlement(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    settlement_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        _, name, services, availability = _validate_settlement_body(body, False)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.update_settlement(campaign_id, settlement_id, name, services, availability):
        send_json(handler, 404, {"error": "settlement not found"})
        return
    settlement = storage.get_settlement(campaign_id, settlement_id)
    send_json(handler, 200, _settlement_response(settlement))


def handle_discover_settlement(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    settlement_id = match.group(2)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    if actor["role"] == "dm":
        send_json(handler, 403, {"error": "forbidden"})
        return
    if not storage.is_play_campaign_member(campaign_id, actor["username"]):
        send_json(handler, 403, {"error": "forbidden"})
        return
    member = storage.get_play_campaign_member(campaign_id, actor["username"])
    character_id = member["character_id"]
    is_new, settlement = storage.discover_settlement(campaign_id, settlement_id, character_id)
    if settlement is None:
        send_json(handler, 404, {"error": "settlement not found"})
        return
    status = 201 if is_new else 200
    send_json(handler, status, _settlement_response(settlement, [character_id]))


def handle_list_settlements(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    settlements = storage.list_settlements(campaign_id)
    if campaign["owner"] == actor["username"]:
        send_json(handler, 200, {"settlements": [_settlement_response(s) for s in settlements]})
        return
    member = storage.get_play_campaign_member(campaign_id, actor["username"])
    if member is None:
        send_json(handler, 403, {"error": "forbidden"})
        return
    own_id = member["character_id"]
    visible = []
    for s in settlements:
        if own_id in s["discovered_by"]:
            visible.append(_settlement_response(s, [own_id]))
    send_json(handler, 200, {"settlements": visible})


def _shop_response(shop):
    """Build the standardized shop response body."""
    return {
        "shop_id": shop["shop_id"],
        "name": shop["name"],
        "stock": shop["stock"],
        "buy_price": shop["buy_price"],
        "sell_price": shop["sell_price"],
    }


def _validate_shop_body(body):
    """Validate a shop payload.

    Returns (shop_id, name, stock, buy_price, sell_price) when valid,
    raising ValueError otherwise.
    """
    if not isinstance(body, dict):
        raise ValueError("invalid request")
    shop_id = body.get("shop_id")
    if not isinstance(shop_id, str) or not shop_id:
        raise ValueError("invalid request")
    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("invalid request")
    stock = body.get("stock")
    if not isinstance(stock, dict) or len(stock) == 0:
        raise ValueError("invalid request")
    normalized = {}
    for item_id, qty in stock.items():
        if not isinstance(item_id, str) or item_id not in VALID_INVENTORY_ITEM_IDS:
            raise ValueError("invalid request")
        qty = int(qty)
        if qty <= 0:
            raise ValueError("invalid request")
        normalized[item_id] = qty
    buy_price = body.get("buy_price")
    if not isinstance(buy_price, int) or buy_price <= 0:
        raise ValueError("invalid request")
    sell_price = body.get("sell_price")
    if not isinstance(sell_price, int) or sell_price < 0:
        raise ValueError("invalid request")
    return shop_id, name, normalized, buy_price, sell_price


def _get_owned_character_id(handler, campaign_id, actor):
    """Return the actor's character_id for a campaign, or None if not a member."""
    if actor["role"] == "dm":
        return None
    member = storage.get_play_campaign_member(campaign_id, actor["username"])
    if member is None:
        return None
    return member["character_id"]


def _require_character_owner(handler, campaign_id, character_id, actor):
    """Return True if actor owns the character in this campaign."""
    if actor["role"] != "player":
        return False
    member = storage.get_play_campaign_member(campaign_id, actor["username"])
    if member is None:
        return False
    return member["character_id"] == character_id


def handle_create_shop(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    settlement_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    settlement = storage.get_settlement(campaign_id, settlement_id)
    if settlement is None:
        send_json(handler, 404, {"error": "settlement not found"})
        return
    try:
        shop_id, name, stock, buy_price, sell_price = _validate_shop_body(body)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.create_shop(campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price):
        send_json(handler, 409, {"error": "duplicate shop id"})
        return
    shop = storage.get_shop(campaign_id, settlement_id, shop_id)
    send_json(handler, 201, _shop_response(shop))


def handle_get_shop(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    settlement_id = match.group(2)
    shop_id = match.group(3)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    settlement = storage.get_settlement(campaign_id, settlement_id)
    if settlement is None:
        send_json(handler, 404, {"error": "settlement not found"})
        return
    shop = storage.get_shop(campaign_id, settlement_id, shop_id)
    if shop is None:
        send_json(handler, 404, {"error": "shop not found"})
        return
    if campaign["owner"] != actor["username"]:
        character_id = _get_owned_character_id(handler, campaign_id, actor)
        if character_id is None:
            send_json(handler, 403, {"error": "forbidden"})
            return
        if character_id not in settlement["discovered_by"]:
            send_json(handler, 404, {"error": "shop not found"})
            return
    send_json(handler, 200, _shop_response(shop))


def _validate_shop_transaction_body(body):
    """Validate a buy/sell request body."""
    if not isinstance(body, dict):
        raise ValueError("invalid request")
    character_id = body.get("character_id")
    item_id = body.get("item_id")
    quantity = body.get("quantity")
    if not isinstance(character_id, str) or not character_id:
        raise ValueError("invalid request")
    if not isinstance(item_id, str) or item_id not in VALID_INVENTORY_ITEM_IDS:
        raise ValueError("invalid request")
    quantity = int(quantity)
    if quantity <= 0:
        raise ValueError("invalid request")
    return character_id, item_id, quantity


def handle_buy_from_shop(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    settlement_id = match.group(2)
    shop_id = match.group(3)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    if actor["role"] == "dm":
        send_json(handler, 403, {"error": "forbidden"})
        return
    if not storage.is_play_campaign_member(campaign_id, actor["username"]):
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        character_id, item_id, quantity = _validate_shop_transaction_body(body)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not _require_character_owner(handler, campaign_id, character_id, actor):
        send_json(handler, 403, {"error": "forbidden"})
        return
    settlement = storage.get_settlement(campaign_id, settlement_id)
    if settlement is None:
        send_json(handler, 404, {"error": "settlement not found"})
        return
    shop = storage.get_shop(campaign_id, settlement_id, shop_id)
    if shop is None:
        send_json(handler, 404, {"error": "shop not found"})
        return
    if character_id not in settlement["discovered_by"]:
        send_json(handler, 404, {"error": "shop not found"})
        return
    member = storage.get_play_campaign_member_by_character_id(campaign_id, character_id)
    if member is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    result = storage.buy_from_shop(campaign_id, settlement_id, shop_id, character_id, item_id, quantity)
    if result is None:
        send_json(handler, 404, {"error": "shop not found"})
        return
    if result is False:
        send_json(handler, 409, {"error": "insufficient stock or funds"})
        return
    shop_response, gold, stock = result
    send_json(
        handler,
        200,
        {
            "character_id": character_id,
            "item_id": item_id,
            "quantity": quantity,
            "gold": gold,
            "stock": stock,
        },
    )


def handle_sell_to_shop(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    settlement_id = match.group(2)
    shop_id = match.group(3)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    if actor["role"] == "dm":
        send_json(handler, 403, {"error": "forbidden"})
        return
    if not storage.is_play_campaign_member(campaign_id, actor["username"]):
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        character_id, item_id, quantity = _validate_shop_transaction_body(body)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not _require_character_owner(handler, campaign_id, character_id, actor):
        send_json(handler, 403, {"error": "forbidden"})
        return
    settlement = storage.get_settlement(campaign_id, settlement_id)
    if settlement is None:
        send_json(handler, 404, {"error": "settlement not found"})
        return
    shop = storage.get_shop(campaign_id, settlement_id, shop_id)
    if shop is None:
        send_json(handler, 404, {"error": "shop not found"})
        return
    if character_id not in settlement["discovered_by"]:
        send_json(handler, 404, {"error": "shop not found"})
        return
    member = storage.get_play_campaign_member_by_character_id(campaign_id, character_id)
    if member is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    result = storage.sell_to_shop(campaign_id, settlement_id, shop_id, character_id, item_id, quantity)
    if result is None:
        send_json(handler, 404, {"error": "shop not found"})
        return
    if result is False:
        send_json(handler, 409, {"error": "insufficient inventory"})
        return
    shop_response, gold, stock = result
    send_json(
        handler,
        200,
        {
            "character_id": character_id,
            "item_id": item_id,
            "quantity": quantity,
            "gold": gold,
            "stock": stock,
        },
    )


# --- Calendar handlers ---


def handle_get_play_campaign_calendar(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    calendar = storage.get_play_campaign_calendar(campaign_id)
    if calendar is None:
        send_json(handler, 404, {"error": "calendar not found"})
        return
    send_json(handler, 200, _calendar_response(calendar))


def handle_create_play_campaign_calendar(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        day = body["day"]
        season = body["season"]
        if not isinstance(day, int) or not isinstance(season, str):
            raise ValueError("invalid request")
        if day < 1:
            raise ValueError("day out of range")
        if season not in ("spring", "summer", "autumn", "winter"):
            raise ValueError("invalid season")
        if not storage.create_play_campaign_calendar(campaign_id, day, season):
            send_json(handler, 409, {"error": "calendar already exists"})
            return
        send_json(
            handler,
            201,
            _calendar_response({"day": day, "season": season}),
        )
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def handle_advance_play_campaign_calendar(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        days = body["days"]
        if not isinstance(days, int):
            raise ValueError("invalid request")
        if days < 1 or days > 30:
            raise ValueError("days out of range")
        calendar = storage.advance_play_campaign_calendar(campaign_id, days)
        if calendar is None:
            send_json(handler, 404, {"error": "calendar not found"})
            return
        send_json(handler, 200, _calendar_response(calendar))
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})


def _validate_recipe_ingredients(ingredients):
    """Validate recipe ingredients and return a normalized dict or raise."""
    if not isinstance(ingredients, dict) or not ingredients:
        raise ValueError("invalid request")
    normalized = {}
    for item_id, quantity in ingredients.items():
        if not isinstance(item_id, str) or not item_id or item_id not in VALID_INVENTORY_ITEM_IDS:
            raise ValueError("invalid request")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("invalid request")
        normalized[item_id] = quantity
    return normalized


def handle_create_play_campaign_recipe(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        recipe_id = body["recipe_id"]
        name = body["name"]
        ingredients = body["ingredients"]
        output_item = body["output_item"]
        output_quantity = body["output_quantity"]
        if (
            not isinstance(recipe_id, str)
            or not isinstance(name, str)
            or not isinstance(output_item, str)
            or not recipe_id
            or not name
            or not output_item
        ):
            raise ValueError("invalid request")
        normalized_ingredients = _validate_recipe_ingredients(ingredients)
        if isinstance(output_quantity, bool) or not isinstance(output_quantity, int) or output_quantity <= 0:
            raise ValueError("invalid request")
        if output_item not in VALID_INVENTORY_ITEM_IDS:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.create_recipe(
        campaign_id,
        recipe_id,
        name,
        normalized_ingredients,
        output_item,
        output_quantity,
    ):
        send_json(handler, 409, {"error": "duplicate recipe id"})
        return
    send_json(
        handler,
        201,
        {
            "recipe_id": recipe_id,
            "name": name,
            "ingredients": normalized_ingredients,
            "output_item": output_item,
            "output_quantity": output_quantity,
        },
    )


def handle_get_play_campaign_recipes(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    recipes = storage.get_recipes(campaign_id)
    send_json(handler, 200, {"recipes": recipes})


def handle_craft_recipe(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    recipe_id = match.group(2)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    if actor["role"] == "dm":
        send_json(handler, 403, {"error": "forbidden"})
        return
    if not storage.is_play_campaign_member(campaign_id, actor["username"]):
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        character_id = body["character_id"]
        if not isinstance(character_id, str) or not character_id:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    member = storage.get_play_campaign_member(campaign_id, actor["username"])
    if member is None:
        send_json(handler, 403, {"error": "forbidden"})
        return
    target_member = storage.get_play_campaign_member_by_character_id(campaign_id, character_id)
    if target_member is None:
        send_json(handler, 404, {"error": "character not found"})
        return
    if member["character_id"] != character_id:
        send_json(handler, 403, {"error": "forbidden"})
        return
    result = storage.craft_recipe(campaign_id, recipe_id, character_id)
    if result is None:
        send_json(handler, 404, {"error": "recipe not found"})
        return
    if result is False:
        send_json(handler, 409, {"error": "insufficient ingredients"})
        return
    send_json(handler, 201, result)


def handle_create_downtime_activity(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        activity_id = body["activity_id"]
        name = body["name"]
        cycles_required = body["cycles_required"]
        if (
            not isinstance(activity_id, str)
            or not isinstance(name, str)
            or isinstance(cycles_required, bool)
            or not isinstance(cycles_required, int)
            or not activity_id
            or not name
        ):
            raise ValueError("invalid request")
        if cycles_required < 1 or cycles_required > 10:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.create_downtime_activity(
        campaign_id, activity_id, name, cycles_required
    ):
        send_json(handler, 409, {"error": "duplicate activity id"})
        return
    send_json(
        handler,
        201,
        {"activity_id": activity_id, "name": name, "cycles_required": cycles_required},
    )


def handle_create_downtime_allocation(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    if actor["role"] == "dm":
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        activity_id = body["activity_id"]
        if not isinstance(activity_id, str) or not activity_id:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    owner, found = storage.get_character_owner(campaign_id, character_id)
    if not found:
        send_json(handler, 404, {"error": "character not found"})
        return
    if owner != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    if storage.get_downtime_activity(campaign_id, activity_id) is None:
        send_json(handler, 404, {"error": "activity not found"})
        return
    if not storage.create_downtime_allocation(campaign_id, character_id, activity_id):
        send_json(handler, 409, {"error": "duplicate allocation"})
        return
    send_json(
        handler,
        201,
        {
            "character_id": character_id,
            "activity_id": activity_id,
            "cycles_completed": 0,
            "completions": 0,
        },
    )


def handle_progress_downtime_allocation(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    activity_id = match.group(3)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    if actor["role"] == "dm":
        send_json(handler, 403, {"error": "forbidden"})
        return
    owner, found = storage.get_character_owner(campaign_id, character_id)
    if not found:
        send_json(handler, 404, {"error": "character not found"})
        return
    if owner != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    if storage.get_downtime_activity(campaign_id, activity_id) is None:
        send_json(handler, 404, {"error": "activity not found"})
        return
    allocation = storage.progress_downtime_allocation(
        campaign_id, character_id, activity_id
    )
    if allocation is None:
        send_json(handler, 404, {"error": "allocation not found"})
        return
    send_json(handler, 200, allocation)


def handle_get_downtime_allocation(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    character_id = match.group(2)
    activity_id = match.group(3)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    owner, found = storage.get_character_owner(campaign_id, character_id)
    if not found:
        send_json(handler, 404, {"error": "character not found"})
        return
    if storage.get_downtime_activity(campaign_id, activity_id) is None:
        send_json(handler, 404, {"error": "activity not found"})
        return
    allocation = storage.get_downtime_allocation(
        campaign_id, character_id, activity_id
    )
    if allocation is None:
        send_json(handler, 404, {"error": "allocation not found"})
        return
    send_json(handler, 200, allocation)


def _parse_search_query(handler):
    """Parse and validate the search-records query string.

    Returns (q, limit, cursor). Raises ValueError for invalid values.
    """
    query = parse_qs(urlparse(handler.path).query, keep_blank_values=True)
    q = None
    if "q" in query:
        value = query["q"]
        if not value or not isinstance(value[0], str):
            raise ValueError("invalid request")
        q = value[0]
    limit = 2
    if "limit" in query:
        value = query["limit"]
        if not value or not isinstance(value[0], str):
            raise ValueError("invalid request")
        try:
            limit = int(value[0])
        except Exception:
            raise ValueError("invalid request")
        if limit < 1 or limit > 3:
            raise ValueError("invalid request")
    cursor = 0
    if "cursor" in query:
        value = query["cursor"]
        if not value or not isinstance(value[0], str):
            raise ValueError("invalid request")
        try:
            cursor = int(value[0])
        except Exception:
            raise ValueError("invalid request")
        if cursor < 0:
            raise ValueError("invalid request")
    return q, limit, cursor


def handle_create_search_record(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    if campaign["owner"] != actor["username"]:
        send_json(handler, 403, {"error": "forbidden"})
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        record_id = body.get("record_id")
        text = body.get("text")
        if not isinstance(record_id, str) or not record_id:
            raise ValueError("invalid request")
        if not isinstance(text, str) or not text:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.create_search_record(campaign_id, record_id, text):
        send_json(handler, 400, {"error": "duplicate search record"})
        return
    send_json(handler, 201, {"record_id": record_id, "text": text})


def handle_list_search_records(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    try:
        q, limit, cursor = _parse_search_query(handler)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    records, next_cursor = storage.list_search_records(
        campaign_id, q=q, limit=limit, cursor=cursor
    )
    send_json(handler, 200, {"records": records, "next_cursor": next_cursor})


def handle_create_rate_event(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        event_id = body.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    ok, remaining, reason = storage.create_rate_event(
        campaign_id, actor["username"], event_id
    )
    if reason == "limit":
        storage.increment_campaign_metric(campaign_id, "rejected_rate_events")
        send_json(handler, 429, {"limit": storage.RATE_LIMIT, "remaining": remaining})
        return
    if reason == "duplicate":
        send_json(handler, 400, {"error": "duplicate event_id"})
        return
    storage.increment_campaign_metric(campaign_id, "accepted_rate_events")
    send_json(
        handler,
        201,
        {"event_id": event_id, "actor": actor["username"], "remaining": remaining},
    )


def handle_list_rate_events(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    events, remaining = storage.list_rate_events(campaign_id, actor["username"])
    send_json(handler, 200, {"events": events, "remaining": remaining})


def handle_get_campaign_metrics(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    send_json(handler, 200, storage.get_campaign_metrics(campaign_id))


def handle_create_backup(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    backup = storage.create_campaign_backup(campaign_id)
    if backup is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    send_json(handler, 201, backup)


def handle_list_backups(handler, match):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    backups = storage.list_campaign_backups(campaign_id)
    send_json(handler, 200, {"backups": backups})


def handle_restore_backup(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    backup_id = match.group(2)
    result = storage.restore_campaign_backup(campaign_id, backup_id)
    if result is None:
        send_json(handler, 404, {"error": "backup not found"})
        return
    send_json(handler, 200, result)


def handle_service_mode(handler, match, body):
    global _MAINTENANCE_MODE
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    if storage.get_play_campaign(campaign_id) is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    try:
        if not isinstance(body, dict) or not isinstance(body.get("maintenance"), bool):
            raise ValueError("invalid request")
        _MAINTENANCE_MODE = body["maintenance"]
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    send_json(handler, 200, {"maintenance": _MAINTENANCE_MODE})


def handle_set_play_campaign_rng_seed(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    if not isinstance(body, dict):
        send_json(handler, 400, {"error": "invalid request"})
        return
    seed = body.get("seed")
    if not isinstance(seed, str) or seed == "":
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.set_campaign_rng_seed(campaign_id, seed):
        send_json(handler, 409, {"error": "seed already configured"})
        return
    send_json(handler, 200, {"seed": seed, "rolls": []})


def handle_create_play_campaign_rng_roll(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=False)
    if campaign is None:
        return
    seed = storage.get_campaign_rng_seed(campaign_id)
    if seed is None:
        send_json(handler, 409, {"error": "no seed configured"})
        return
    if not isinstance(body, dict):
        send_json(handler, 400, {"error": "invalid request"})
        return
    roll_id = body.get("roll_id")
    if not isinstance(roll_id, str) or roll_id == "":
        send_json(handler, 400, {"error": "invalid request"})
        return
    try:
        sides = int(body["sides"])
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if sides < 2 or sides > 100:
        send_json(handler, 400, {"error": "invalid request"})
        return
    existing_rolls = storage.get_campaign_rng_ledger(campaign_id)["rolls"]
    sequence = len(existing_rolls) + 1
    result = compute_rng_roll(seed, sequence, roll_id, sides)
    record = storage.append_campaign_rng_roll(campaign_id, roll_id, sides, result)
    if record is None:
        send_json(handler, 409, {"error": "duplicate roll_id"})
        return
    send_json(handler, 201, record)


def handle_get_play_campaign_rng_ledger(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=False)
    if campaign is None:
        return
    send_json(handler, 200, storage.get_campaign_rng_ledger(campaign_id))


def handle_create_moderation_report(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=False)
    if campaign is None:
        return
    if not isinstance(body, dict):
        send_json(handler, 400, {"error": "invalid request"})
        return
    report_id = body.get("report_id")
    target_id = body.get("target_id")
    reason = body.get("reason")
    if (
        not isinstance(report_id, str) or report_id == ""
        or not isinstance(target_id, str) or target_id == ""
        or not isinstance(reason, str) or reason == ""
    ):
        send_json(handler, 400, {"error": "invalid request"})
        return
    record = storage.add_moderation_report(
        campaign_id, report_id, target_id, reason, actor["username"]
    )
    if record is None:
        send_json(handler, 409, {"error": "duplicate report_id"})
        return
    send_json(handler, 201, record)


def handle_get_moderation_reports(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=False)
    if campaign is None:
        return
    send_json(handler, 200, {"reports": storage.get_moderation_reports(campaign_id)})


def handle_resolve_moderation_report(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    report_id = match.group(2)
    report = storage.get_moderation_report(campaign_id, report_id)
    if report is None:
        send_json(handler, 404, {"error": "report not found"})
        return
    if report["status"] != "open":
        send_json(handler, 409, {"error": "report already resolved"})
        return
    if not isinstance(body, dict):
        send_json(handler, 400, {"error": "invalid request"})
        return
    action = body.get("action")
    note = body.get("note")
    if action not in ("allow", "remove") or not isinstance(note, str) or note == "":
        send_json(handler, 400, {"error": "invalid request"})
        return
    result = storage.resolve_moderation_report(
        campaign_id, report_id, action, note, actor["username"]
    )
    send_json(handler, 200, result)


def _validate_blocked_tags(body):
    """Validate a blocked_tags replacement body.

    ``blocked_tags`` must be a nonempty array of unique, non-blank strings.
    """
    if not isinstance(body, dict):
        raise ValueError("invalid request")
    tags = body.get("blocked_tags")
    if not isinstance(tags, list) or len(tags) == 0:
        raise ValueError("invalid request")
    seen = set()
    for tag in tags:
        if not isinstance(tag, str) or tag.strip() == "":
            raise ValueError("invalid request")
        if tag in seen:
            raise ValueError("invalid request")
        seen.add(tag)
    return tags


def _validate_safety_check_body(body):
    """Validate a safety-check submission body."""
    if not isinstance(body, dict):
        raise ValueError("invalid request")
    event_id = body.get("event_id")
    kind = body.get("kind")
    text = body.get("text")
    tags = body.get("tags")
    if not isinstance(event_id, str) or event_id == "":
        raise ValueError("invalid request")
    if kind not in ("narration", "chat"):
        raise ValueError("invalid request")
    if not isinstance(text, str) or text == "":
        raise ValueError("invalid request")
    if not isinstance(tags, list) or len(tags) == 0:
        raise ValueError("invalid request")
    seen = set()
    for tag in tags:
        if not isinstance(tag, str) or tag == "":
            raise ValueError("invalid request")
        if tag in seen:
            raise ValueError("invalid request")
        seen.add(tag)
    return event_id, kind, text, tags


def handle_replace_safety_boundaries(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        tags = _validate_blocked_tags(body)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    result = storage.replace_safety_boundaries(campaign_id, tags)
    send_json(handler, 200, result)


def handle_get_safety_boundaries(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=False)
    if campaign is None:
        return
    send_json(handler, 200, storage.get_safety_boundaries(campaign_id))


def handle_submit_safety_check(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=False)
    if campaign is None:
        return
    try:
        event_id, kind, text, tags = _validate_safety_check_body(body)
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    blocked = set(storage.get_safety_boundaries(campaign_id)["blocked_tags"])
    if any(tag in blocked for tag in tags):
        send_json(handler, 409, {"error": "blocked tag"})
        return
    if storage.safety_event_exists(campaign_id, event_id):
        send_json(handler, 409, {"error": "duplicate event_id"})
        return
    record = storage.add_safety_event(campaign_id, event_id, kind, text, tags)
    if record is None:
        send_json(handler, 409, {"error": "duplicate event_id"})
        return
    send_json(handler, 201, record)


def handle_get_safety_events(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=False)
    if campaign is None:
        return
    send_json(handler, 200, {"events": storage.get_safety_events(campaign_id)})


def handle_seed_play_campaign_fixture(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    if not isinstance(body, dict) or body.get("fixture_id") != "canonical-v1":
        send_json(handler, 400, {"error": "invalid request"})
        return
    fixture, created = storage.seed_play_campaign_fixture(campaign_id)
    status = 201 if created else 200
    send_json(handler, status, fixture)


def handle_get_play_campaign_fixture_state(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=False)
    if campaign is None:
        return
    fixture = storage.get_play_campaign_fixture(campaign_id)
    if fixture is None:
        send_json(handler, 404, {"error": "fixture not found"})
        return
    send_json(handler, 200, fixture)


def handle_get_play_campaign_onboarding(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=False)
    if campaign is None:
        return
    if campaign["owner"] == actor["username"]:
        send_json(
            handler,
            200,
            {
                "role": "dm",
                "next_steps": ["configure-safety", "invite-players", "start-campaign"],
                "can_mutate": True,
            },
        )
        return
    send_json(
        handler,
        200,
        {
            "role": "player",
            "next_steps": ["review-party", "take-turn", "submit-action"],
            "can_mutate": True,
        },
    )


def handle_create_spectator(handler, match, body):
    actor = _require_auth(handler, "dm")
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id, require_owner=True)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        spectator_id = body.get("spectator_id")
        if not isinstance(spectator_id, str) or not spectator_id:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    if not storage.create_spectator(campaign_id, spectator_id):
        send_json(handler, 409, {"error": "duplicate spectator id"})
        return
    send_json(
        handler,
        201,
        {"spectator_id": spectator_id, "token": f"spectator-{spectator_id}"},
    )


def handle_get_spectator_view(handler, match):
    auth = handler.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        send_json(handler, 401, {"error": "unauthorized"})
        return
    token = auth[7:]
    if token.startswith("session-"):
        send_json(handler, 403, {"error": "forbidden"})
        return
    if not token.startswith("spectator-"):
        send_json(handler, 401, {"error": "unauthorized"})
        return
    spectator_id = token[len("spectator-"):]
    spectator_campaign_id = storage.get_spectator_campaign(spectator_id)
    if spectator_campaign_id is None:
        send_json(handler, 401, {"error": "unauthorized"})
        return
    campaign_id = match.group(1)
    campaign = storage.get_play_campaign(campaign_id)
    if campaign is None:
        send_json(handler, 404, {"error": "campaign not found"})
        return
    if spectator_campaign_id != campaign_id:
        send_json(handler, 403, {"error": "forbidden"})
        return
    members = storage.get_play_campaign_members(campaign_id)
    document = storage.get_campaign_document(campaign_id)
    send_json(
        handler,
        200,
        {
            "campaign_id": campaign_id,
            "name": campaign["name"],
            "status": campaign["status"],
            "party_size": len(members),
            "story": document["story"],
        },
    )


def _parse_feed_query(handler):
    """Parse and validate cursor/limit query parameters for the event feed.

    Returns (cursor, limit) on success, or None when parameters are invalid.
    """
    query = parse_qs(urlparse(handler.path).query)
    cursor = query.get("cursor", ["0"])[0]
    limit = query.get("limit", ["2"])[0]
    try:
        cursor = int(cursor)
        limit = int(limit)
    except ValueError:
        return None
    if cursor < 0 or limit < 1 or limit > 3:
        return None
    return cursor, limit


def handle_create_feed_event(handler, match, body):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    try:
        if not isinstance(body, dict):
            raise ValueError("invalid request")
        event_id = body.get("event_id")
        text = body.get("text")
        if not isinstance(event_id, str) or not isinstance(text, str) or not event_id or not text:
            raise ValueError("invalid request")
    except Exception:
        send_json(handler, 400, {"error": "invalid request"})
        return
    event = storage.create_feed_event(campaign_id, event_id, text)
    if event is None:
        send_json(handler, 409, {"error": "duplicate event_id"})
        return
    send_json(handler, 201, event)


def handle_get_event_feed(handler, match):
    actor = _require_auth(handler, None)
    if actor is None:
        return
    campaign_id = match.group(1)
    campaign = _load_play_campaign(handler, actor, campaign_id)
    if campaign is None:
        return
    parsed = _parse_feed_query(handler)
    if parsed is None:
        send_json(handler, 400, {"error": "invalid request"})
        return
    cursor, limit = parsed
    events = storage.get_feed_events(campaign_id, cursor, limit)
    send_json(handler, 200, {"events": events, "next_cursor": cursor + len(events)})


# Ordered route tables: first match wins. Keep the original dispatch order.
GET_ROUTES = [
    (re.compile(r"^/health$"), handle_health),
    (re.compile(r"^/healthz$"), handle_healthz),
    (re.compile(r"^/readyz$"), handle_readyz),
    (re.compile(r"^/v1/storage/status$"), handle_storage_status),
    (re.compile(r"^/v1/schema$"), handle_schema),
    (MONSTER_RE, handle_get_monster),
    (ITEM_RE, handle_get_item),
    (CAMPAIGN_QUESTS_SUMMARY_RE, handle_quest_summary),
    (CAMPAIGN_RELATIONSHIPS_RE, handle_relationships),
    (CAMPAIGN_INVENTORY_SUMMARY_RE, handle_inventory_summary),
    (CAMPAIGN_SESSIONS_NEXT_RE, handle_next_session),
    (CAMPAIGN_AUDIT_RE, handle_campaign_audit),
    (CAMPAIGN_EXPORT_RE, handle_campaign_export),
    (CAMPAIGN_ANALYTICS_SUMMARY_RE, handle_analytics_summary),
    (CAMPAIGN_STATE_RE, handle_get_campaign_state),
    (PLAY_CAMPAIGN_TURN_RE, handle_play_campaign_turn),
    (PLAY_CAMPAIGN_MY_TURN_RE, handle_play_campaign_my_turn),
    (PLAY_CAMPAIGN_GM_STATUS_RE, handle_play_campaign_gm_status),
    (PLAY_CAMPAIGN_DOCUMENT_RE, handle_get_campaign_document),
    (PLAY_CAMPAIGN_BACKUPS_RE, handle_list_backups),
    (PLAY_CAMPAIGN_EXPORTS_RE, handle_list_play_campaign_exports),
    (PLAY_CAMPAIGN_EXPORT_RE, handle_get_play_campaign_export),
    (PLAY_CAMPAIGN_IMPORT_STATE_RE, handle_get_play_campaign_import_state),
    (PLAY_CAMPAIGN_MIGRATION_STATE_RE, handle_get_play_campaign_migration_state),
    (PLAY_CAMPAIGN_SEARCH_RECORDS_RE, handle_list_search_records),
    (PLAY_CAMPAIGN_RATE_EVENTS_RE, handle_list_rate_events),
    (PLAY_CAMPAIGN_METRICS_RE, handle_get_campaign_metrics),
    (PLAY_CAMPAIGN_SESSION_ZERO_RE, handle_get_play_campaign_session_zero),
    (PLAY_CAMPAIGN_CONTENT_RE, handle_list_content),
    (PLAY_CAMPAIGN_TRAVEL_RE, handle_get_travel),
    (PLAY_CAMPAIGN_SCENE_CURRENT_RE, handle_get_current_scene),
    (PLAY_CAMPAIGN_ENCOUNTER_TURN_RE, handle_get_play_campaign_encounter_turn),
    (PLAY_CAMPAIGN_ENCOUNTER_STATUS_RE, handle_get_encounter_status),
    (PLAY_CAMPAIGN_CHARACTER_STATUS_RE, handle_play_campaign_character_status),
    (PLAY_CAMPAIGN_CHARACTER_OWNER_RE, handle_get_character_owner),
    (PLAY_CAMPAIGN_CHARACTER_SPELLS_RE, handle_get_character_spells),
    (PLAY_CAMPAIGN_CHARACTER_PREPARED_SPELLS_RE, handle_get_character_prepared_spells),
    (PLAY_CAMPAIGN_CHARACTER_CASTS_RE, handle_get_character_casts),
    (PLAY_CAMPAIGN_CHARACTER_CONCENTRATION_RE, handle_get_character_concentration),
    (PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEMS_RE, handle_get_play_character_inventory),
    (PLAY_CAMPAIGN_CHARACTER_EQUIPMENT_RE, handle_get_play_character_equipment),
    (PLAY_CAMPAIGN_CHARACTER_CURRENCY_RE, handle_get_character_currency),
    (PLAY_CAMPAIGN_TRANSACTIONAL_TRANSFERS_RE, handle_get_transactional_transfers),
    (PLAY_CAMPAIGN_NPC_RE, handle_get_play_campaign_npc),
    (PLAY_CAMPAIGN_NPC_DIALOGUE_RE, handle_get_play_campaign_npc_dialogue),
    (PLAY_CAMPAIGN_LOOT_ID_RE, handle_get_loot),
    (PLAY_CAMPAIGN_FACTION_REPUTATION_RE, handle_get_play_campaign_reputation),
    (PLAY_CAMPAIGN_RELATIONSHIPS_RE, handle_get_play_campaign_relationships),
    (PLAY_CAMPAIGN_CLUES_RE, handle_get_play_campaign_clues),
    (PLAY_CAMPAIGN_QUESTS_RE, handle_get_play_campaign_quests),
    (PLAY_CAMPAIGN_CHARACTER_REWARDS_RE, handle_get_play_campaign_character_rewards),
    (PLAY_CAMPAIGN_WORLD_EVENTS_RE, handle_get_world_events),
    (PLAY_CAMPAIGN_SETTLEMENTS_RE, handle_list_settlements),
    (PLAY_CAMPAIGN_SETTLEMENT_SHOP_RE, handle_get_shop),
    (PLAY_CAMPAIGN_CALENDAR_RE, handle_get_play_campaign_calendar),
    (PLAY_CAMPAIGN_RECIPES_RE, handle_get_play_campaign_recipes),
    (PLAY_CAMPAIGN_DOWNTIME_ALLOCATION_RE, handle_get_downtime_allocation),
    (PLAY_CAMPAIGN_NOTES_RE, handle_list_notes),
    (PLAY_CAMPAIGN_NOTE_RE, handle_get_note),
    (PLAY_CAMPAIGN_WHISPERS_RE, handle_list_whispers),
    (PLAY_CAMPAIGN_INVITATIONS_RE, handle_list_invitations),
    (PLAY_CAMPAIGN_CHARACTER_SHEET_RE, handle_get_character_sheet),
    (PLAY_CAMPAIGN_DELEGATIONS_AUDIT_RE, handle_get_delegation_audit),
    (PLAY_CAMPAIGN_AUDIT_EVENTS_RE, handle_get_play_campaign_audit_events),
    (PLAY_CAMPAIGN_PROJECTION_REBUILD_RE, handle_rebuild_projection),
    (PLAY_CAMPAIGN_PROJECTION_RE, handle_get_projection),
    (PLAY_CAMPAIGN_REPLAY_CHECK_RE, handle_check_replay),
    (PLAY_CAMPAIGN_REPLAY_RE, handle_get_replay),
    (PLAY_CAMPAIGN_IDEMPOTENT_EVENTS_RE, handle_get_idempotent_events),
    (PLAY_CAMPAIGN_SAFE_TURNS_RE, handle_get_safe_turns),
    (PLAY_CAMPAIGN_RNG_LEDGER_RE, handle_get_play_campaign_rng_ledger),
    (PLAY_CAMPAIGN_MODERATION_REPORTS_RE, handle_get_moderation_reports),
    (PLAY_CAMPAIGN_SAFETY_BOUNDARIES_RE, handle_get_safety_boundaries),
    (PLAY_CAMPAIGN_SAFETY_EVENTS_RE, handle_get_safety_events),
    (PLAY_CAMPAIGN_FIXTURE_STATE_RE, handle_get_play_campaign_fixture_state),
    (PLAY_CAMPAIGN_ONBOARDING_RE, handle_get_play_campaign_onboarding),
    (PLAY_CAMPAIGN_SPECTATOR_VIEW_RE, handle_get_spectator_view),
    (PLAY_CAMPAIGN_EVENT_FEED_RE, handle_get_event_feed),
]

POST_ROUTES = [
    (re.compile(r"^/v1/dice/stats$"), handle_dice_stats),
    (re.compile(r"^/v1/checks/ability$"), handle_ability_check),
    (re.compile(r"^/v1/encounters/adjusted-xp$"), handle_encounter_adjusted_xp),
    (re.compile(r"^/v1/initiative/order$"), handle_initiative_order),
    (re.compile(r"^/v1/characters/ability-modifier$"), handle_ability_modifier),
    (re.compile(r"^/v1/characters/proficiency$"), handle_proficiency),
    (re.compile(r"^/v1/characters/derived-stats$"), handle_derived_stats),
    (re.compile(r"^/v1/combat/sessions$"), handle_create_combat_session),
    (COMBAT_SESSION_CONDITIONS_RE, handle_add_condition),
    (COMBAT_SESSION_ADVANCE_RE, handle_advance_turn),
    (re.compile(r"^/v1/auth/register$"), handle_auth_register),
    (re.compile(r"^/v1/auth/login$"), handle_auth_login),
    (re.compile(r"^/v1/compendium/monsters$"), handle_create_monster),
    (re.compile(r"^/v1/compendium/items$"), handle_create_item),
    (re.compile(r"^/v1/campaigns$"), handle_create_campaign),
    (PLAY_CAMPAIGNS_RE, handle_create_play_campaign),
    (PLAY_CAMPAIGN_MEMBERS_RE, handle_join_play_campaign),
    (PLAY_CAMPAIGN_START_RE, handle_start_play_campaign),
    (PLAY_CAMPAIGN_NARRATIONS_RE, handle_create_narration),
    (PLAY_CAMPAIGN_ACTIONS_RE, handle_play_campaign_action),
    (PLAY_CAMPAIGN_TURN_TRAVEL_RE, handle_play_campaign_travel),
    (PLAY_CAMPAIGN_TURN_REST_RE, handle_play_campaign_rest),
    (PLAY_CAMPAIGN_RESOLUTIONS_RE, handle_play_campaign_resolution),
    (PLAY_CAMPAIGN_TURN_NUDGE_RE, handle_play_campaign_turn_nudge),
    (CAMPAIGN_CHARACTERS_RE, handle_create_campaign_character),
    (CAMPAIGN_EVENTS_RE, handle_create_campaign_event),
    (CAMPAIGN_FACTIONS_RE, handle_create_faction),
    (CAMPAIGN_NPCS_RE, handle_create_npc),
    (CAMPAIGN_QUESTS_RE, handle_create_quest),
    (CAMPAIGN_QUEST_PROGRESS_RE, handle_update_quest_progress),
    (CAMPAIGN_INVENTORY_RE, handle_add_inventory_item),
    (CAMPAIGN_CHARACTER_EQUIPMENT_RE, handle_assign_equipment),
    (CAMPAIGN_CRAFTING_RE, handle_create_crafting_project),
    (CAMPAIGN_CRAFTING_ADVANCE_RE, handle_advance_crafting_project),
    (CAMPAIGN_SESSIONS_RE, handle_create_campaign_session),
    (CAMPAIGN_SESSION_ATTENDANCE_RE, handle_record_attendance),
    (CAMPAIGN_ANALYTICS_RISK_REPORT_RE, handle_analytics_risk_report),
    (re.compile(r"^/v1/phb/spell-slots$"), handle_spell_slots),
    (re.compile(r"^/v1/phb/rests/long$"), handle_long_rest),
    (re.compile(r"^/v1/phb/equipment-load$"), handle_equipment_load),
    (re.compile(r"^/v1/dm/encounter-builder$"), handle_encounter_builder),
    (re.compile(r"^/v1/dm/loot-parcel$"), handle_loot_parcel),
    (re.compile(r"^/v1/dm/session-recap$"), handle_session_recap),
    (re.compile(r"^/v1/storage/reset$"), handle_storage_reset),
    (PLAY_CAMPAIGN_CONTENT_RE, handle_create_content),
    (PLAY_CAMPAIGN_SCENES_RE, handle_create_scene),
    (PLAY_CAMPAIGN_SCENE_ENTER_RE, handle_enter_scene),
    (PLAY_CAMPAIGN_SCENE_CLOSE_RE, handle_close_scene),
    (PLAY_CAMPAIGN_LOCATIONS_RE, handle_create_location),
    (PLAY_CAMPAIGN_CONNECTIONS_RE, handle_create_connection),
    (PLAY_CAMPAIGN_ENCOUNTERS_RE, handle_create_play_campaign_encounter),
    (PLAY_CAMPAIGN_ENCOUNTER_MONSTERS_RE, handle_add_encounter_monster),
    (PLAY_CAMPAIGN_ENCOUNTER_COMBATANTS_RE, handle_bind_encounter_member),
    (PLAY_CAMPAIGN_ENCOUNTER_TURN_ADVANCE_RE, handle_advance_play_campaign_encounter_turn),
    (PLAY_CAMPAIGN_ENCOUNTER_TURN_DELAY_RE, handle_play_campaign_encounter_turn_delay),
    (PLAY_CAMPAIGN_ENCOUNTER_TURN_READY_RE, handle_play_campaign_encounter_turn_ready),
    (PLAY_CAMPAIGN_ENCOUNTER_ACTIONS_RE, handle_play_campaign_encounter_action),
    (PLAY_CAMPAIGN_ENCOUNTER_DAMAGE_RE, handle_play_campaign_encounter_damage),
    (PLAY_CAMPAIGN_ENCOUNTER_HEAL_RE, handle_play_campaign_encounter_heal),
    (PLAY_CAMPAIGN_ENCOUNTER_CONDITIONS_RE, handle_add_encounter_condition),
    (PLAY_CAMPAIGN_ENCOUNTER_REWARDS_RE, handle_play_campaign_encounter_rewards),
    (PLAY_CAMPAIGN_ENCOUNTER_CLOSE_RE, handle_play_campaign_encounter_close),
    (PLAY_CAMPAIGN_ENCOUNTER_END_RE, handle_play_campaign_encounter_end),
    (PLAY_CAMPAIGN_CHARACTER_DAMAGE_RE, handle_play_campaign_character_damage),
    (PLAY_CAMPAIGN_CHARACTER_DEATH_SAVES_RE, handle_play_campaign_character_death_saves),
    (PLAY_CAMPAIGN_CHARACTER_CLAIM_RE, handle_claim_character),
    (PLAY_CAMPAIGN_CHARACTER_TRANSFER_RE, handle_transfer_character),
    (PLAY_CAMPAIGN_CHARACTER_BUILD_RE, handle_build_character),
    (PLAY_CAMPAIGN_CHARACTER_LEVEL_UP_RE, handle_level_up_character),
    (PLAY_CAMPAIGN_CHARACTER_SKILL_CHECK_RE, handle_play_campaign_skill_check),
    (PLAY_CAMPAIGN_CHARACTER_SPELLS_RE, handle_add_character_spell),
    (PLAY_CAMPAIGN_CHARACTER_CASTS_RE, handle_cast_character_spell),
    (PLAY_CAMPAIGN_CHARACTER_CONCENTRATION_ADVANCE_RE, handle_advance_character_concentration),
    (PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEMS_RE, handle_add_play_character_inventory_item),
    (PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEM_CONSUME_RE, handle_consume_play_character_inventory_item),
    (PLAY_CAMPAIGN_CHARACTER_EQUIPMENT_ATTUNE_RE, handle_attune_play_character_equipment),
    (PLAY_CAMPAIGN_CHARACTER_CURRENCY_TRANSFERS_RE, handle_transfer_character_currency),
    (PLAY_CAMPAIGN_TRANSACTIONAL_TRANSFERS_RE, handle_create_transactional_transfer),
    (PLAY_CAMPAIGN_LOOT_VOTES_RE, handle_vote_loot),
    (PLAY_CAMPAIGN_LOOT_ASSIGN_RE, handle_assign_loot),
    (PLAY_CAMPAIGN_NPCS_RE, handle_create_play_campaign_npc),
    (PLAY_CAMPAIGN_NPC_DIALOGUE_RE, handle_create_play_campaign_npc_dialogue),
    (PLAY_CAMPAIGN_FACTIONS_RE, handle_create_play_campaign_faction),
    (PLAY_CAMPAIGN_FACTION_REPUTATION_RE, handle_change_play_campaign_reputation),
    (PLAY_CAMPAIGN_RELATIONSHIPS_RE, handle_create_play_campaign_relationship),
    (PLAY_CAMPAIGN_LOOT_RE, handle_create_loot),
    (PLAY_CAMPAIGN_CLUES_RE, handle_create_play_campaign_clue),
    (PLAY_CAMPAIGN_QUESTS_RE, handle_create_play_campaign_quest),
    (PLAY_CAMPAIGN_QUEST_REWARDS_AWARD_RE, handle_award_play_campaign_quest_rewards),
    (PLAY_CAMPAIGN_WORLD_EVENTS_RE, handle_create_world_event),
    (PLAY_CAMPAIGN_WORLD_EVENT_RESOLVE_RE, handle_resolve_world_event),
    (PLAY_CAMPAIGN_SETTLEMENTS_RE, handle_create_settlement),
    (PLAY_CAMPAIGN_SETTLEMENT_SHOPS_RE, handle_create_shop),
    (PLAY_CAMPAIGN_SETTLEMENT_SHOP_BUY_RE, handle_buy_from_shop),
    (PLAY_CAMPAIGN_SETTLEMENT_SHOP_SELL_RE, handle_sell_to_shop),
    (PLAY_CAMPAIGN_SETTLEMENT_DISCOVER_RE, handle_discover_settlement),
    (PLAY_CAMPAIGN_CALENDAR_ADVANCE_RE, handle_advance_play_campaign_calendar),
    (PLAY_CAMPAIGN_CALENDAR_RE, handle_create_play_campaign_calendar),
    (PLAY_CAMPAIGN_RECIPES_RE, handle_create_play_campaign_recipe),
    (PLAY_CAMPAIGN_RECIPE_CRAFT_RE, handle_craft_recipe),
    (PLAY_CAMPAIGN_DOWNTIME_ACTIVITIES_RE, handle_create_downtime_activity),
    (PLAY_CAMPAIGN_DOWNTIME_ALLOCATION_PROGRESS_RE, handle_progress_downtime_allocation),
    (PLAY_CAMPAIGN_DOWNTIME_ALLOCATIONS_RE, handle_create_downtime_allocation),
    (PLAY_CAMPAIGN_NOTES_RE, handle_create_note),
    (PLAY_CAMPAIGN_WHISPERS_RE, handle_create_whisper),
    (PLAY_CAMPAIGN_MESSAGES_RE, handle_create_message),
    (PLAY_CAMPAIGN_INVITATION_ACCEPT_RE, handle_accept_invitation),
    (PLAY_CAMPAIGN_INVITATIONS_RE, handle_create_invitation),
    (PLAY_CAMPAIGN_DELEGATIONS_RE, handle_grant_delegation),
    (PLAY_CAMPAIGN_AUDIT_EVENTS_RE, handle_create_play_campaign_audit_event),
    (PLAY_CAMPAIGN_PROJECTION_EVENTS_RE, handle_create_projection_event),
    (PLAY_CAMPAIGN_IDEMPOTENT_EVENTS_RE, handle_create_idempotent_event),
    (PLAY_CAMPAIGN_REPLAY_EVENTS_RE, handle_create_replay_event),
    (PLAY_CAMPAIGN_SAFE_TURNS_RE, handle_submit_safe_turn),
    (PLAY_CAMPAIGN_EXPORTS_RE, handle_create_play_campaign_export),
    (PLAY_CAMPAIGN_IMPORTS_RE, handle_create_play_campaign_import),
    (PLAY_CAMPAIGN_MIGRATIONS_RE, handle_create_play_campaign_migration),
    (PLAY_CAMPAIGN_SEARCH_RECORDS_RE, handle_create_search_record),
    (PLAY_CAMPAIGN_RATE_EVENTS_RE, handle_create_rate_event),
    (PLAY_CAMPAIGN_BACKUPS_RE, handle_create_backup),
    (PLAY_CAMPAIGN_BACKUP_RESTORE_RE, handle_restore_backup),
    (PLAY_CAMPAIGN_RNG_ROLLS_RE, handle_create_play_campaign_rng_roll),
    (PLAY_CAMPAIGN_SERVICE_MODE_RE, handle_service_mode),
    (PLAY_CAMPAIGN_MODERATION_REPORTS_RE, handle_create_moderation_report),
    (PLAY_CAMPAIGN_SAFETY_CHECKS_RE, handle_submit_safety_check),
    (PLAY_CAMPAIGN_FIXTURE_SEEDS_RE, handle_seed_play_campaign_fixture),
    (PLAY_CAMPAIGN_SPECTATORS_RE, handle_create_spectator),
    (PLAY_CAMPAIGN_FEED_EVENTS_RE, handle_create_feed_event),
]

DELETE_ROUTES = [
    (PLAY_CAMPAIGN_ENCOUNTER_MONSTER_RE, handle_remove_encounter_monster),
    (PLAY_CAMPAIGN_ENCOUNTER_COMBATANT_RE, handle_unbind_encounter_member),
    (PLAY_CAMPAIGN_CHARACTER_CONCENTRATION_RE, handle_delete_character_concentration),
    (PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEM_RE, handle_remove_play_character_inventory_item),
    (PLAY_CAMPAIGN_DELEGATION_RE, handle_revoke_delegation),
]

PUT_ROUTES = [
    (PLAY_CAMPAIGN_DOCUMENT_RE, handle_update_campaign_document),
    (PLAY_CAMPAIGN_SESSION_ZERO_RE, handle_set_play_campaign_session_zero),
    (PLAY_CAMPAIGN_CONTENT_TAGS_RE, handle_update_content_tags),
    (PLAY_CAMPAIGN_CHARACTER_PREPARED_SPELLS_RE, handle_set_character_prepared_spells),
    (PLAY_CAMPAIGN_CHARACTER_CONCENTRATION_RE, handle_put_character_concentration),
    (PLAY_CAMPAIGN_CHARACTER_EQUIPMENT_RE, handle_equip_play_character_item),
    (PLAY_CAMPAIGN_NPC_AGENDA_RE, handle_update_play_campaign_npc_agenda),
    (PLAY_CAMPAIGN_RELATIONSHIP_RE, handle_update_play_campaign_relationship),
    (PLAY_CAMPAIGN_QUEST_STATE_RE, handle_update_play_campaign_quest_state),
    (PLAY_CAMPAIGN_QUEST_REWARDS_RE, handle_configure_play_campaign_quest_rewards),
    (PLAY_CAMPAIGN_SETTLEMENT_RE, handle_update_settlement),
    (PLAY_CAMPAIGN_NOTE_RE, handle_update_note),
    (PLAY_CAMPAIGN_RNG_SEED_RE, handle_set_play_campaign_rng_seed),
    (PLAY_CAMPAIGN_MODERATION_REPORT_RESOLUTION_RE, handle_resolve_moderation_report),
    (PLAY_CAMPAIGN_SAFETY_BOUNDARIES_RE, handle_replace_safety_boundaries),
]


_UNSET = object()


def _dispatch(handler, routes, body=_UNSET):
    """Dispatch a request to the first matching route from an ordered table.

    ``routes`` contains (compiled_pattern, callable) tuples. GET handlers
    receive (handler, match). POST/PUT/DELETE handlers receive
    (handler, match, body), where ``body`` may be ``None`` for empty requests.
    Falls back to a 404 response.
    """
    for pattern, route_handler in routes:
        match = pattern.match(handler.path)
        if match:
            if body is _UNSET:
                return route_handler(handler, match)
            return route_handler(handler, match, body)
    send_json(handler, 404, {"error": "not found"})


class Handler(BaseHTTPRequestHandler):
    """Request handler that dispatches GET, POST, PUT, and DELETE routes."""

    def do_GET(self):
        _dispatch(self, GET_ROUTES)

    def do_POST(self):
        try:
            body = read_json(self)
        except Exception:
            send_json(self, 400, {"error": "invalid json"})
            return
        _dispatch(self, POST_ROUTES, body)

    def do_PUT(self):
        try:
            body = read_json(self)
        except Exception:
            send_json(self, 400, {"error": "invalid json"})
            return
        _dispatch(self, PUT_ROUTES, body)

    def do_DELETE(self):
        try:
            body = read_json(self)
        except Exception:
            send_json(self, 400, {"error": "invalid json"})
            return
        _dispatch(self, DELETE_ROUTES, body)

    def log_message(self, format, *args):
        # Suppress default request logging to keep stdout quiet during tests.
        pass
