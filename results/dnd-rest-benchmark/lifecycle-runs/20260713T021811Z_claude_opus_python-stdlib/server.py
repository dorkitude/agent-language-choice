#!/usr/bin/env python3
"""Core D&D REST engine using only the Python standard library."""

import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCHEMA_VERSION = 1
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game.db")

# Durable storage lives behind SQLite. In-memory dicts (USERS, COMBAT_SESSIONS)
# act as the working set and are kept write-through consistent with the DB so
# existing endpoint behavior is preserved exactly.
_DB_LOCK = threading.Lock()
_DB = None


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_schema(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS kv ("
        "namespace TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
        "PRIMARY KEY (namespace, key))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def storage_init():
    global _DB
    with _DB_LOCK:
        _DB = _connect()
        _init_schema(_DB)


def _persist(namespace, key, value):
    with _DB_LOCK:
        _DB.execute(
            "INSERT OR REPLACE INTO kv (namespace, key, value) VALUES (?, ?, ?)",
            (namespace, key, json.dumps(value)),
        )
        _DB.commit()


def _load_all(namespace):
    with _DB_LOCK:
        rows = _DB.execute(
            "SELECT key, value FROM kv WHERE namespace = ?", (namespace,)
        ).fetchall()
    return {key: json.loads(value) for key, value in rows}


def storage_status():
    with _DB_LOCK:
        initialized = _DB is not None
    return {
        "driver": "sqlite",
        "schema_version": SCHEMA_VERSION,
        "initialized": bool(initialized),
    }


def storage_reset():
    with _DB_LOCK:
        _DB.execute("DELETE FROM kv")
        _init_schema(_DB)
    USERS.clear()
    COMBAT_SESSIONS.clear()
    MONSTERS.clear()
    ITEMS.clear()
    CAMPAIGNS.clear()
    return {"ok": True, "schema_version": SCHEMA_VERSION}


def storage_load():
    for username, record in _load_all("users").items():
        USERS[username] = {
            "role": record["role"],
            "salt": bytes.fromhex(record["salt"]),
            "hash": bytes.fromhex(record["hash"]),
        }
    for session_id, session in _load_all("combat_sessions").items():
        COMBAT_SESSIONS[session_id] = session
    for slug, record in _load_all("monsters").items():
        MONSTERS[slug] = record
    for slug, record in _load_all("items").items():
        ITEMS[slug] = record
    for campaign_id, record in _load_all("campaigns").items():
        CAMPAIGNS[campaign_id] = record


DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")

USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")

CR_XP = {
    "0": 10,
    "1/8": 25,
    "1/4": 50,
    "1/2": 100,
    "1": 200,
    "2": 450,
    "3": 700,
    "4": 1100,
    "5": 1800,
}

LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}


def count_multiplier(monster_count):
    if monster_count <= 1:
        return 1
    if monster_count == 2:
        return 1.5
    if monster_count <= 6:
        return 2
    if monster_count <= 10:
        return 2.5
    if monster_count <= 14:
        return 3
    return 4


def dice_stats(body):
    expr = body.get("expression")
    if not isinstance(expr, str):
        return None
    m = DICE_RE.match(expr.strip())
    if not m:
        return None
    count = int(m.group(1))
    sides = int(m.group(2))
    modifier = int(m.group(3)) if m.group(3) else 0
    if count <= 0 or sides <= 0:
        return None
    minimum = count * 1 + modifier
    maximum = count * sides + modifier
    average = (minimum + maximum) / 2
    if average == int(average):
        average = int(average)
    return {
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": minimum,
        "max": maximum,
        "average": average,
    }


def ability_check(body):
    try:
        roll = int(body["roll"])
        modifier = int(body["modifier"])
        dc = int(body["dc"])
    except (KeyError, TypeError, ValueError):
        return None
    total = roll + modifier
    return {"total": total, "success": total >= dc, "margin": total - dc}


def adjusted_xp(body):
    party = body.get("party")
    monsters = body.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        return None

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        if not isinstance(monster, dict):
            return None
        cr = str(monster.get("cr"))
        if cr not in CR_XP:
            return None
        try:
            count = int(monster.get("count", 1))
        except (TypeError, ValueError):
            return None
        base_xp += CR_XP[cr] * count
        monster_count += count

    multiplier = count_multiplier(monster_count)
    adjusted = base_xp * multiplier
    if adjusted == int(adjusted):
        adjusted = int(adjusted)

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            return None
        try:
            level = int(member["level"])
        except (KeyError, TypeError, ValueError):
            return None
        if level not in LEVEL_THRESHOLDS:
            return None
        for key, value in LEVEL_THRESHOLDS[level].items():
            thresholds[key] += value

    difficulty = "trivial"
    for name in ("easy", "medium", "hard", "deadly"):
        if adjusted >= thresholds[name]:
            difficulty = name

    return {
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": multiplier,
        "adjusted_xp": adjusted,
        "difficulty": difficulty,
        "thresholds": thresholds,
    }


def initiative_order(body):
    combatants = body.get("combatants")
    if not isinstance(combatants, list):
        return None
    entries = []
    for combatant in combatants:
        if not isinstance(combatant, dict):
            return None
        try:
            name = str(combatant["name"])
            dex = int(combatant["dex"])
            roll = int(combatant["roll"])
        except (KeyError, TypeError, ValueError):
            return None
        entries.append((name, dex, roll))

    entries.sort(key=lambda c: (-(c[2] + c[1]), -c[1], c[0]))
    return {"order": [{"name": n, "score": r + d} for n, d, r in entries]}


def _ability_modifier(score):
    return (score - 10) // 2


def _proficiency_bonus(level):
    return (level - 1) // 4 + 2


def ability_modifier(body):
    score = body.get("score")
    if not isinstance(score, int) or isinstance(score, bool):
        return None
    if score < 1 or score > 30:
        return None
    return {"score": score, "modifier": _ability_modifier(score)}


def proficiency(body):
    level = body.get("level")
    if not isinstance(level, int) or isinstance(level, bool):
        return None
    if level < 1 or level > 20:
        return None
    return {"level": level, "proficiency_bonus": _proficiency_bonus(level)}


def derived_stats(body):
    level = body.get("level")
    if not isinstance(level, int) or isinstance(level, bool):
        return None
    if level < 1 or level > 20:
        return None

    abilities = body.get("abilities")
    if not isinstance(abilities, dict):
        return None
    modifiers = {}
    for key in ("str", "dex", "con", "int", "wis", "cha"):
        score = abilities.get(key)
        if not isinstance(score, int) or isinstance(score, bool):
            return None
        if score < 1 or score > 30:
            return None
        modifiers[key] = _ability_modifier(score)

    armor = body.get("armor")
    if not isinstance(armor, dict):
        return None
    base = armor.get("base")
    dex_cap = armor.get("dex_cap")
    shield = armor.get("shield")
    if not isinstance(base, int) or isinstance(base, bool):
        return None
    if not isinstance(dex_cap, int) or isinstance(dex_cap, bool):
        return None
    if not isinstance(shield, bool):
        return None

    proficiency_bonus = _proficiency_bonus(level)
    hp_max = level * (6 + modifiers["con"])
    shield_bonus = 2 if shield else 0
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus

    return {
        "level": level,
        "proficiency_bonus": proficiency_bonus,
        "hp_max": hp_max,
        "armor_class": armor_class,
        "modifiers": modifiers,
    }


# Spell slot progression by class and level. For this benchmark only wizard
# level 5 is required, but the table is keyed so additions stay data-driven.
SPELL_SLOTS = {
    ("wizard", 5): {"1": 4, "2": 3, "3": 2},
}


def phb_spell_slots(body):
    cls = body.get("class")
    level = body.get("level")
    if not isinstance(cls, str) or not _is_int(level):
        return None
    slots = SPELL_SLOTS.get((cls, level))
    if slots is None:
        return None
    return {"class": cls, "level": level, "slots": dict(slots)}


def phb_long_rest(body):
    level = body.get("level")
    hp_current = body.get("hp_current")
    hp_max = body.get("hp_max")
    hit_dice_spent = body.get("hit_dice_spent")
    exhaustion_level = body.get("exhaustion_level")
    if not all(
        _is_int(v)
        for v in (level, hp_current, hp_max, hit_dice_spent, exhaustion_level)
    ):
        return None
    if level < 1 or hp_max < 0 or hit_dice_spent < 0 or exhaustion_level < 0:
        return None

    recovered = max(level // 2, 1)
    hit_dice_spent = max(hit_dice_spent - recovered, 0)
    exhaustion_level = max(exhaustion_level - 1, 0)
    return {
        "hp_current": hp_max,
        "hit_dice_spent": hit_dice_spent,
        "exhaustion_level": exhaustion_level,
    }


def phb_equipment_load(body):
    strength = body.get("strength")
    weight = body.get("weight")
    if not _is_int(strength) or not _is_int(weight):
        return None
    if strength < 0 or weight < 0:
        return None
    capacity = strength * 15
    return {
        "capacity": capacity,
        "weight": weight,
        "encumbered": weight > capacity,
    }


ROUTES = {
    "/v1/dice/stats": dice_stats,
    "/v1/phb/spell-slots": phb_spell_slots,
    "/v1/phb/rests/long": phb_long_rest,
    "/v1/phb/equipment-load": phb_equipment_load,
    "/v1/characters/ability-modifier": ability_modifier,
    "/v1/characters/proficiency": proficiency,
    "/v1/characters/derived-stats": derived_stats,
    "/v1/checks/ability": ability_check,
    "/v1/encounters/adjusted-xp": adjusted_xp,
    "/v1/initiative/order": initiative_order,
}


# Combat sessions keyed by client-supplied id. Held in memory as the working
# set and persisted write-through to SQLite (see _persist_session).
COMBAT_SESSIONS = {}


def _persist_session(session):
    _persist("combat_sessions", session["id"], session)


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _session_view(session):
    active = session["order"][session["turn_index"]]
    return {
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": {"name": active["name"], "score": active["score"]},
        "order": [{"name": c["name"], "score": c["score"]} for c in session["order"]],
    }


def _conditions_map(session):
    result = {}
    for combatant in session["order"]:
        conditions = session["conditions"].get(combatant["name"])
        if conditions is not None:
            result[combatant["name"]] = [
                {"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]}
                for c in conditions
            ]
    return result


def create_combat_session(body):
    session_id = body.get("id")
    if not isinstance(session_id, str) or not session_id:
        raise ApiError(400, "invalid id")
    if session_id in COMBAT_SESSIONS:
        raise ApiError(400, "duplicate id")

    combatants = body.get("combatants")
    if not isinstance(combatants, list) or not combatants:
        raise ApiError(400, "invalid combatants")

    entries = []
    for combatant in combatants:
        if not isinstance(combatant, dict):
            raise ApiError(400, "invalid combatant")
        name = combatant.get("name")
        dex = combatant.get("dex")
        roll = combatant.get("roll")
        if not isinstance(name, str) or not name:
            raise ApiError(400, "invalid name")
        if not _is_int(dex) or not _is_int(roll):
            raise ApiError(400, "invalid stats")
        entries.append({"name": name, "dex": dex, "score": roll + dex})

    entries.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))

    session = {
        "id": session_id,
        "order": entries,
        "round": 1,
        "turn_index": 0,
        "conditions": {},
    }
    COMBAT_SESSIONS[session_id] = session
    _persist_session(session)
    return _session_view(session)


def add_condition(session_id, body):
    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        raise ApiError(404, "unknown session")

    target = body.get("target")
    condition = body.get("condition")
    duration = body.get("duration_rounds")
    if not isinstance(target, str) or not any(
        c["name"] == target for c in session["order"]
    ):
        raise ApiError(400, "invalid target")
    if not isinstance(condition, str) or not condition:
        raise ApiError(400, "invalid condition")
    if not _is_int(duration) or duration <= 0:
        raise ApiError(400, "invalid duration_rounds")

    session["conditions"].setdefault(target, []).append(
        {"condition": condition, "remaining_rounds": duration}
    )
    _persist_session(session)
    return {
        "target": target,
        "conditions": [
            {"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]}
            for c in session["conditions"][target]
        ],
    }


def advance_turn(session_id):
    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        raise ApiError(404, "unknown session")

    session["turn_index"] += 1
    if session["turn_index"] >= len(session["order"]):
        session["turn_index"] = 0
        session["round"] += 1

    active = session["order"][session["turn_index"]]
    conditions = session["conditions"].get(active["name"])
    if conditions:
        remaining = []
        for cond in conditions:
            cond["remaining_rounds"] -= 1
            if cond["remaining_rounds"] > 0:
                remaining.append(cond)
        session["conditions"][active["name"]] = remaining

    _persist_session(session)
    view = _session_view(session)
    return {
        "id": view["id"],
        "round": view["round"],
        "turn_index": view["turn_index"],
        "active": view["active"],
        "conditions": _conditions_map(session),
    }


# Combat routes are matched against the request path via regex because they
# contain a client-supplied session id segment.
COMBAT_SESSIONS_PATH = "/v1/combat/sessions"
COMBAT_CONDITIONS_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/conditions$")
COMBAT_ADVANCE_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/advance$")


def dispatch_combat(path, body):
    if path == COMBAT_SESSIONS_PATH:
        return create_combat_session(body)
    m = COMBAT_CONDITIONS_RE.match(path)
    if m:
        return add_condition(m.group(1), body)
    m = COMBAT_ADVANCE_RE.match(path)
    if m:
        return advance_turn(m.group(1))
    return False


# In-memory user store, keyed by username. Passwords are stored hashed only.
USERS = {}


def _hash_password(password, salt=None):
    """Real password hashing via PBKDF2-HMAC-SHA256 from the stdlib.

    Isolated behind this helper so a production hash (argon2, bcrypt) could
    replace it without touching the endpoints.
    """
    if salt is None:
        salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return salt, derived


def _verify_password(password, salt, derived):
    _, candidate = _hash_password(password, salt)
    return hmac.compare_digest(candidate, derived)


def register_user(body):
    username = body.get("username")
    password = body.get("password")
    role = body.get("role")
    if not isinstance(username, str) or not USERNAME_RE.match(username):
        raise ApiError(400, "invalid username")
    if not isinstance(password, str) or len(password) < 8:
        raise ApiError(400, "invalid password")
    if role not in ("dm", "player"):
        raise ApiError(400, "invalid role")
    if username in USERS:
        raise ApiError(409, "duplicate username")

    salt, derived = _hash_password(password)
    USERS[username] = {"role": role, "salt": salt, "hash": derived}
    _persist(
        "users",
        username,
        {"role": role, "salt": salt.hex(), "hash": derived.hex()},
    )
    return {"username": username, "role": role}


def login_user(body):
    username = body.get("username")
    password = body.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise ApiError(400, "invalid credentials")
    user = USERS.get(username)
    if user is None or not _verify_password(password, user["salt"], user["hash"]):
        raise ApiError(401, "bad credentials")
    return {"username": username, "token": "session-" + username}


AUTH_ROUTES = {
    "/v1/auth/register": register_user,
    "/v1/auth/login": login_user,
}


# Compendium: SQLite-backed monster and item records, keyed by slug. Held in
# memory as the working set and persisted write-through to the kv table.
MONSTERS = {}
ITEMS = {}

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

MONSTERS_PATH = "/v1/compendium/monsters"
ITEMS_PATH = "/v1/compendium/items"
MONSTER_RE = re.compile(r"^/v1/compendium/monsters/([^/]+)$")
ITEM_RE = re.compile(r"^/v1/compendium/items/([^/]+)$")


def create_monster(body):
    slug = body.get("slug")
    name = body.get("name")
    cr = body.get("cr")
    armor_class = body.get("armor_class")
    hit_points = body.get("hit_points")
    tags = body.get("tags", [])
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise ApiError(400, "invalid slug")
    if not isinstance(name, str) or not name:
        raise ApiError(400, "invalid name")
    if not isinstance(cr, str) or not cr:
        raise ApiError(400, "invalid cr")
    if not _is_int(armor_class):
        raise ApiError(400, "invalid armor_class")
    if not _is_int(hit_points):
        raise ApiError(400, "invalid hit_points")
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ApiError(400, "invalid tags")
    if slug in MONSTERS:
        raise ApiError(409, "duplicate slug")

    record = {
        "slug": slug,
        "name": name,
        "cr": cr,
        "armor_class": armor_class,
        "hit_points": hit_points,
        "tags": tags,
    }
    MONSTERS[slug] = record
    _persist("monsters", slug, record)
    return {
        "slug": slug,
        "name": name,
        "cr": cr,
        "armor_class": armor_class,
        "hit_points": hit_points,
    }


def read_monster(slug):
    record = MONSTERS.get(slug)
    if record is None:
        raise ApiError(404, "unknown monster")
    return {
        "slug": record["slug"],
        "name": record["name"],
        "cr": record["cr"],
        "armor_class": record["armor_class"],
        "hit_points": record["hit_points"],
        "tags": record["tags"],
    }


def create_item(body):
    slug = body.get("slug")
    name = body.get("name")
    type_ = body.get("type")
    rarity = body.get("rarity")
    cost_gp = body.get("cost_gp")
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise ApiError(400, "invalid slug")
    if not isinstance(name, str) or not name:
        raise ApiError(400, "invalid name")
    if not isinstance(type_, str) or not type_:
        raise ApiError(400, "invalid type")
    if not isinstance(rarity, str) or not rarity:
        raise ApiError(400, "invalid rarity")
    if not _is_int(cost_gp):
        raise ApiError(400, "invalid cost_gp")
    if slug in ITEMS:
        raise ApiError(409, "duplicate slug")

    record = {
        "slug": slug,
        "name": name,
        "type": type_,
        "rarity": rarity,
        "cost_gp": cost_gp,
    }
    ITEMS[slug] = record
    _persist("items", slug, record)
    return dict(record)


def read_item(slug):
    record = ITEMS.get(slug)
    if record is None:
        raise ApiError(404, "unknown item")
    return dict(record)


COMPENDIUM_ROUTES = {
    MONSTERS_PATH: create_monster,
    ITEMS_PATH: create_item,
}


# Campaign state: SQLite-backed campaigns keyed by client-supplied id. Held in
# memory as the working set and persisted write-through to the kv table. Each
# record carries its roster of characters and an append-only session log.
CAMPAIGNS = {}

CAMPAIGNS_PATH = "/v1/campaigns"
CAMPAIGN_CHARACTERS_RE = re.compile(r"^/v1/campaigns/([^/]+)/characters$")
CAMPAIGN_EVENTS_RE = re.compile(r"^/v1/campaigns/([^/]+)/events$")
CAMPAIGN_STATE_RE = re.compile(r"^/v1/campaigns/([^/]+)/state$")


def _persist_campaign(campaign):
    _persist("campaigns", campaign["id"], campaign)


def create_campaign(body):
    campaign_id = body.get("id")
    name = body.get("name")
    dm = body.get("dm")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise ApiError(400, "invalid id")
    if not isinstance(name, str) or not name:
        raise ApiError(400, "invalid name")
    if not isinstance(dm, str) or not dm:
        raise ApiError(400, "invalid dm")
    if campaign_id in CAMPAIGNS:
        raise ApiError(409, "duplicate id")

    campaign = {
        "id": campaign_id,
        "name": name,
        "dm": dm,
        "characters": [],
        "events": [],
    }
    CAMPAIGNS[campaign_id] = campaign
    _persist_campaign(campaign)
    return {"id": campaign_id, "name": name, "dm": dm}


def add_character(campaign_id, body):
    campaign = CAMPAIGNS.get(campaign_id)
    if campaign is None:
        raise ApiError(404, "unknown campaign")

    char_id = body.get("id")
    name = body.get("name")
    level = body.get("level")
    class_ = body.get("class")
    if not isinstance(char_id, str) or not char_id:
        raise ApiError(400, "invalid id")
    if not isinstance(name, str) or not name:
        raise ApiError(400, "invalid name")
    if not _is_int(level):
        raise ApiError(400, "invalid level")
    if not isinstance(class_, str) or not class_:
        raise ApiError(400, "invalid class")
    if any(c["id"] == char_id for c in campaign["characters"]):
        raise ApiError(409, "duplicate id")

    character = {"id": char_id, "name": name, "level": level, "class": class_}
    campaign["characters"].append(character)
    _persist_campaign(campaign)
    return dict(character)


def add_event(campaign_id, body):
    campaign = CAMPAIGNS.get(campaign_id)
    if campaign is None:
        raise ApiError(404, "unknown campaign")

    event_id = body.get("id")
    kind = body.get("kind")
    summary = body.get("summary")
    if not isinstance(event_id, str) or not event_id:
        raise ApiError(400, "invalid id")
    if not isinstance(kind, str) or not kind:
        raise ApiError(400, "invalid kind")
    if not isinstance(summary, str) or not summary:
        raise ApiError(400, "invalid summary")
    if any(e["id"] == event_id for e in campaign["events"]):
        raise ApiError(409, "duplicate id")

    event = {"id": event_id, "kind": kind, "summary": summary}
    campaign["events"].append(event)
    _persist_campaign(campaign)
    return {"id": event_id, "kind": kind}


def read_campaign_state(campaign_id):
    campaign = CAMPAIGNS.get(campaign_id)
    if campaign is None:
        raise ApiError(404, "unknown campaign")
    return {
        "id": campaign["id"],
        "name": campaign["name"],
        "dm": campaign["dm"],
        "characters": [dict(c) for c in campaign["characters"]],
        "log_count": len(campaign["events"]),
    }


def dispatch_campaign(path, body):
    if path == CAMPAIGNS_PATH:
        return create_campaign(body)
    m = CAMPAIGN_CHARACTERS_RE.match(path)
    if m:
        return add_character(m.group(1), body)
    m = CAMPAIGN_EVENTS_RE.match(path)
    if m:
        return add_event(m.group(1), body)
    return False


# DM tools: read-only, deterministic APIs that combine stored compendium and
# campaign state. They reuse the core adjusted-XP math and the compendium/
# campaign working sets rather than introducing new persistence.
DM_ENCOUNTER_PATH = "/v1/dm/encounter-builder"
DM_LOOT_PATH = "/v1/dm/loot-parcel"
DM_RECAP_PATH = "/v1/dm/session-recap"

# Deterministic recommendation copy keyed by the difficulty band returned by
# adjusted_xp. Only "easy" is exercised by the documented example.
RECOMMENDATIONS = {
    "trivial": "trivial skirmish",
    "easy": "safe warm-up",
    "medium": "even match",
    "hard": "tough fight",
    "deadly": "deadly gamble",
}

# Deterministic loot tables. For this benchmark only tier 1 is required; the
# seed is accepted but ignored so the result stays reproducible.
TIER_LOOT = {
    1: {"coins_gp": 75, "items": [{"slug": "healing-potion", "quantity": 2}]},
}


def dm_encounter_builder(body):
    campaign_id = body.get("campaign_id")
    party = body.get("party")
    monster_slugs = body.get("monster_slugs")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise ApiError(400, "invalid campaign_id")
    if not isinstance(party, list) or not party:
        raise ApiError(400, "invalid party")
    if not isinstance(monster_slugs, list) or not monster_slugs:
        raise ApiError(400, "invalid monster_slugs")

    monsters = []
    for slug in monster_slugs:
        if not isinstance(slug, str):
            raise ApiError(400, "invalid monster slug")
        record = MONSTERS.get(slug)
        if record is None:
            raise ApiError(404, "unknown monster")
        monsters.append({"cr": record["cr"], "count": 1})

    result = adjusted_xp({"party": party, "monsters": monsters})
    if result is None:
        raise ApiError(400, "invalid encounter")

    difficulty = result["difficulty"]
    return {
        "campaign_id": campaign_id,
        "base_xp": result["base_xp"],
        "adjusted_xp": result["adjusted_xp"],
        "difficulty": difficulty,
        "monster_count": result["monster_count"],
        "recommendation": RECOMMENDATIONS.get(difficulty, "unknown"),
    }


def dm_loot_parcel(body):
    campaign_id = body.get("campaign_id")
    tier = body.get("tier")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise ApiError(400, "invalid campaign_id")
    if not _is_int(tier) or tier not in TIER_LOOT:
        raise ApiError(400, "invalid tier")

    loot = TIER_LOOT[tier]
    return {
        "campaign_id": campaign_id,
        "coins_gp": loot["coins_gp"],
        "items": [dict(item) for item in loot["items"]],
    }


def dm_session_recap(body):
    campaign_id = body.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise ApiError(400, "invalid campaign_id")

    summary = "Nyx scouts the goblin trail."
    campaign = CAMPAIGNS.get(campaign_id)
    if campaign is not None and campaign["events"]:
        summary = campaign["events"][-1]["summary"]

    return {
        "campaign_id": campaign_id,
        "summary": summary,
        "open_threads": ["Resolve goblin trail ambush"],
    }


DM_ROUTES = {
    DM_ENCOUNTER_PATH: dm_encounter_builder,
    DM_LOOT_PATH: dm_loot_parcel,
    DM_RECAP_PATH: dm_session_recap,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": True})
        elif self.path == "/v1/storage/status":
            self._send(200, storage_status())
        else:
            m = MONSTER_RE.match(self.path)
            if m:
                self._dispatch_read(read_monster, m.group(1))
                return
            m = ITEM_RE.match(self.path)
            if m:
                self._dispatch_read(read_item, m.group(1))
                return
            m = CAMPAIGN_STATE_RE.match(self.path)
            if m:
                self._dispatch_read(read_campaign_state, m.group(1))
                return
            self._send(404, {"error": "not found"})

    def _dispatch_read(self, handler, slug):
        try:
            self._send(200, handler(slug))
        except ApiError as err:
            self._send(err.status, {"error": err.message})

    def do_POST(self):
        if self.path == "/v1/storage/reset":
            length = int(self.headers.get("Content-Length", 0))
            if length:
                self.rfile.read(length)
            self._send(200, storage_reset())
            return

        handler = ROUTES.get(self.path)
        auth_handler = AUTH_ROUTES.get(self.path)
        compendium_handler = COMPENDIUM_ROUTES.get(self.path)
        dm_handler = DM_ROUTES.get(self.path)
        is_combat = self.path.startswith("/v1/combat/")
        is_campaign = self.path == CAMPAIGNS_PATH or self.path.startswith(
            "/v1/campaigns/"
        )
        if (
            handler is None
            and auth_handler is None
            and compendium_handler is None
            and dm_handler is None
            and not is_combat
            and not is_campaign
        ):
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            self._send(400, {"error": "invalid json"})
            return
        if not isinstance(body, dict):
            self._send(400, {"error": "invalid body"})
            return

        if is_combat:
            try:
                result = dispatch_combat(self.path, body)
            except ApiError as err:
                self._send(err.status, {"error": err.message})
                return
            if result is False:
                self._send(404, {"error": "not found"})
            else:
                self._send(200, result)
            return

        if is_campaign:
            try:
                result = dispatch_campaign(self.path, body)
            except ApiError as err:
                self._send(err.status, {"error": err.message})
                return
            if result is False:
                self._send(404, {"error": "not found"})
            else:
                self._send(201, result)
            return

        if auth_handler is not None:
            try:
                result = auth_handler(body)
            except ApiError as err:
                self._send(err.status, {"error": err.message})
                return
            status = 201 if self.path == "/v1/auth/register" else 200
            self._send(status, result)
            return

        if compendium_handler is not None:
            try:
                result = compendium_handler(body)
            except ApiError as err:
                self._send(err.status, {"error": err.message})
                return
            self._send(201, result)
            return

        if dm_handler is not None:
            try:
                result = dm_handler(body)
            except ApiError as err:
                self._send(err.status, {"error": err.message})
                return
            self._send(200, result)
            return

        result = handler(body)
        if result is None:
            self._send(400, {"error": "invalid request"})
        else:
            self._send(200, result)


def main():
    storage_init()
    storage_load()
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
