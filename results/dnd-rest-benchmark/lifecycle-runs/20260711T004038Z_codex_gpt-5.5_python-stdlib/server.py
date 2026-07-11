#!/usr/bin/env python3
import json
import hashlib
import hmac
import os
import re
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse


DICE_RE = re.compile(r"^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$")

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


class BadRequest(ValueError):
    pass


class NotFound(ValueError):
    pass


class Unauthorized(ValueError):
    pass


class Conflict(ValueError):
    pass


COMBAT_LOCK = threading.Lock()
USERS_LOCK = threading.Lock()
COMPENDIUM_LOCK = threading.Lock()
CAMPAIGN_LOCK = threading.Lock()
USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
PASSWORD_ITERATIONS = 200_000
SCHEMA_VERSION = 1
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game.db")


def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_storage():
    with db_connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                password_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS combat_sessions (
                id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS compendium_monsters (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cr TEXT NOT NULL,
                armor_class INTEGER NOT NULL,
                hit_points INTEGER NOT NULL,
                tags_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS compendium_items (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                rarity TEXT NOT NULL,
                cost_gp INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                dm TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS campaign_characters (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                level INTEGER NOT NULL,
                class TEXT NOT NULL,
                FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS campaign_events (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            INSERT INTO metadata(key, value)
            VALUES('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (str(SCHEMA_VERSION),),
        )


def reset_storage():
    with USERS_LOCK, COMBAT_LOCK, COMPENDIUM_LOCK, CAMPAIGN_LOCK:
        with db_connect() as conn:
            conn.execute("DROP TABLE IF EXISTS campaign_events")
            conn.execute("DROP TABLE IF EXISTS campaign_characters")
            conn.execute("DROP TABLE IF EXISTS campaigns")
            conn.execute("DROP TABLE IF EXISTS compendium_items")
            conn.execute("DROP TABLE IF EXISTS compendium_monsters")
            conn.execute("DROP TABLE IF EXISTS combat_sessions")
            conn.execute("DROP TABLE IF EXISTS users")
            conn.execute("DROP TABLE IF EXISTS metadata")
        initialize_storage()
    return {"ok": True, "schema_version": SCHEMA_VERSION}


def storage_initialized():
    try:
        with db_connect() as conn:
            row = conn.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            return row is not None and row["value"] == str(SCHEMA_VERSION)
    except sqlite3.Error:
        return False


def storage_status():
    return {
        "driver": "sqlite",
        "schema_version": SCHEMA_VERSION,
        "initialized": storage_initialized(),
    }


def encode_session(session):
    payload = dict(session)
    payload["condition_targets"] = sorted(session["condition_targets"])
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def decode_session(raw):
    session = json.loads(raw)
    session["condition_targets"] = set(session.get("condition_targets", []))
    return session


def save_combat_session(conn, session):
    conn.execute(
        """
        INSERT INTO combat_sessions(id, payload_json)
        VALUES(?, ?)
        ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json
        """,
        (session["id"], encode_session(session)),
    )


def require_int(value, name):
    if type(value) is not int:
        raise BadRequest(f"{name} must be an integer")
    return value


def require_int_range(value, name, minimum, maximum):
    value = require_int(value, name)
    if value < minimum or value > maximum:
        raise BadRequest(f"{name} must be between {minimum} and {maximum}")
    return value


def require_string(value, name):
    if type(value) is not str or value == "":
        raise BadRequest(f"{name} must be a non-empty string")
    return value


def require_slug(value):
    if type(value) is not str or not SLUG_RE.fullmatch(value):
        raise BadRequest("slug is invalid")
    return value


def clean_number(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return {
        "salt": salt.hex(),
        "hash": digest.hex(),
        "iterations": PASSWORD_ITERATIONS,
    }


def verify_password(password, stored):
    salt = bytes.fromhex(stored["salt"])
    expected = bytes.fromhex(stored["hash"])
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, stored["iterations"]
    )
    return hmac.compare_digest(actual, expected)


def require_auth_body(body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")
    username = body.get("username")
    password = body.get("password")
    if type(username) is not str or not USERNAME_RE.fullmatch(username):
        raise BadRequest("username is invalid")
    if type(password) is not str or len(password) < 8:
        raise BadRequest("password is invalid")
    return username, password


def require_login_body(body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")
    username = body.get("username")
    password = body.get("password")
    if type(username) is not str or not USERNAME_RE.fullmatch(username):
        raise BadRequest("username is invalid")
    if type(password) is not str:
        raise BadRequest("password is invalid")
    return username, password


def register_user(body):
    username, password = require_auth_body(body)
    role = body.get("role")
    if role not in ("dm", "player"):
        raise BadRequest("role is invalid")

    with USERS_LOCK:
        with db_connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM users WHERE username = ?", (username,)
            ).fetchone()
            if existing is not None:
                raise Conflict("username already exists")
            conn.execute(
                "INSERT INTO users(username, role, password_json) VALUES(?, ?, ?)",
                (
                    username,
                    role,
                    json.dumps(hash_password(password), separators=(",", ":")),
                ),
            )

    return {"username": username, "role": role}


def login_user(body):
    username, password = require_login_body(body)
    with USERS_LOCK:
        with db_connect() as conn:
            user = conn.execute(
                "SELECT password_json FROM users WHERE username = ?", (username,)
            ).fetchone()
        if user is None or not verify_password(password, json.loads(user["password_json"])):
            raise Unauthorized("bad credentials")

    return {"username": username, "token": f"session-{username}"}


def dice_stats(body):
    expression = body.get("expression") if isinstance(body, dict) else None
    if type(expression) is not str:
        raise BadRequest("expression must be a string")

    match = DICE_RE.fullmatch(expression)
    if not match:
        raise BadRequest("invalid dice expression")

    count = int(match.group(1))
    sides = int(match.group(2))
    if count <= 0 or sides <= 0:
        raise BadRequest("dice count and sides must be positive")

    modifier = int(match.group(4) or "0")
    if match.group(3) == "-":
        modifier = -modifier

    average = count * (sides + 1) / 2 + modifier
    return {
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": count + modifier,
        "max": count * sides + modifier,
        "average": clean_number(average),
    }


def ability_check(body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")
    roll = require_int(body.get("roll"), "roll")
    modifier = require_int(body.get("modifier"), "modifier")
    dc = require_int(body.get("dc"), "dc")
    total = roll + modifier
    return {"total": total, "success": total >= dc, "margin": total - dc}


def ability_modifier_for_score(score):
    return (score - 10) // 2


def proficiency_bonus_for_level(level):
    return 2 + (level - 1) // 4


def ability_modifier(body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")
    score = require_int_range(body.get("score"), "score", 1, 30)
    return {"score": score, "modifier": ability_modifier_for_score(score)}


def proficiency(body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")
    level = require_int_range(body.get("level"), "level", 1, 20)
    return {"level": level, "proficiency_bonus": proficiency_bonus_for_level(level)}


def derived_stats(body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")

    level = require_int_range(body.get("level"), "level", 1, 20)
    abilities = body.get("abilities")
    armor = body.get("armor")
    if not isinstance(abilities, dict):
        raise BadRequest("abilities must be an object")
    if not isinstance(armor, dict):
        raise BadRequest("armor must be an object")

    modifiers = {}
    for ability in ("str", "dex", "con", "int", "wis", "cha"):
        score = require_int_range(abilities.get(ability), ability, 1, 30)
        modifiers[ability] = ability_modifier_for_score(score)

    armor_base = require_int(armor.get("base"), "armor base")
    dex_cap = require_int(armor.get("dex_cap"), "armor dex_cap")
    shield = armor.get("shield")
    if type(shield) is not bool:
        raise BadRequest("armor shield must be a boolean")

    proficiency_bonus = proficiency_bonus_for_level(level)
    hp_max = level * (6 + modifiers["con"])
    armor_class = armor_base + min(modifiers["dex"], dex_cap) + (2 if shield else 0)

    return {
        "level": level,
        "proficiency_bonus": proficiency_bonus,
        "hp_max": hp_max,
        "armor_class": armor_class,
        "modifiers": modifiers,
    }


def spell_slots(body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")
    class_name = body.get("class")
    level = require_int(body.get("level"), "level")
    if class_name != "wizard" or level != 5:
        raise BadRequest("unsupported class level")
    return {"class": class_name, "level": level, "slots": {"1": 4, "2": 3, "3": 2}}


def long_rest(body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")
    level = require_int(body.get("level"), "level")
    hp_max = require_int(body.get("hp_max"), "hp_max")
    require_int(body.get("hp_current"), "hp_current")
    hit_dice_spent = require_int(body.get("hit_dice_spent"), "hit_dice_spent")
    exhaustion_level = require_int(body.get("exhaustion_level"), "exhaustion_level")
    if level <= 0:
        raise BadRequest("level must be positive")
    if hp_max < 0 or hit_dice_spent < 0 or exhaustion_level < 0:
        raise BadRequest("values must be non-negative")

    recovered_hit_dice = max(1, level // 2)
    return {
        "hp_current": hp_max,
        "hit_dice_spent": max(0, hit_dice_spent - recovered_hit_dice),
        "exhaustion_level": max(0, exhaustion_level - 1),
    }


def equipment_load(body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")
    strength = require_int(body.get("strength"), "strength")
    weight = require_int(body.get("weight"), "weight")
    if strength < 0 or weight < 0:
        raise BadRequest("strength and weight must be non-negative")
    capacity = strength * 15
    return {"capacity": capacity, "weight": weight, "encumbered": weight > capacity}


def encounter_multiplier(monster_count):
    if monster_count <= 0:
        raise BadRequest("monster count must be positive")
    if monster_count == 1:
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


def adjusted_xp(body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")

    party = body.get("party")
    monsters = body.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        raise BadRequest("party and monsters must be arrays")

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            raise BadRequest("party members must be objects")
        level = require_int(member.get("level"), "level")
        if level not in LEVEL_THRESHOLDS:
            raise BadRequest("unsupported party level")
        for key, value in LEVEL_THRESHOLDS[level].items():
            thresholds[key] += value

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        if not isinstance(monster, dict):
            raise BadRequest("monsters must be objects")
        cr = monster.get("cr")
        count = require_int(monster.get("count"), "monster count")
        if cr not in CR_XP:
            raise BadRequest("unsupported challenge rating")
        if count <= 0:
            raise BadRequest("monster count must be positive")
        base_xp += CR_XP[cr] * count
        monster_count += count

    multiplier = encounter_multiplier(monster_count)
    adjusted = clean_number(base_xp * multiplier)

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
    ranked = rank_combatants(body)
    return {"order": [{"name": item["name"], "score": item["score"]} for item in ranked]}


def rank_combatants(body, require_nonempty=False, require_unique_names=False):
    if not isinstance(body, dict) or not isinstance(body.get("combatants"), list):
        raise BadRequest("combatants must be an array")
    if require_nonempty and not body["combatants"]:
        raise BadRequest("combatants must not be empty")

    ranked = []
    names = set()
    for combatant in body["combatants"]:
        if not isinstance(combatant, dict):
            raise BadRequest("combatants must be objects")
        name = combatant.get("name")
        if type(name) is not str:
            raise BadRequest("name must be a string")
        if require_unique_names and name in names:
            raise BadRequest("combatant names must be unique")
        names.add(name)
        dex = require_int(combatant.get("dex"), "dex")
        roll = require_int(combatant.get("roll"), "roll")
        ranked.append({"name": name, "dex": dex, "score": roll + dex})

    ranked.sort(key=lambda item: (-item["score"], -item["dex"], item["name"]))
    return ranked


def public_order(session):
    return [{"name": item["name"], "score": item["score"]} for item in session["order"]]


def public_active(session):
    active = session["order"][session["turn_index"]]
    return {"name": active["name"], "score": active["score"]}


def public_conditions(session):
    payload = {}
    for name, conditions in session["conditions"].items():
        if conditions or name in session["condition_targets"]:
            payload[name] = [
                {"condition": item["condition"], "remaining_rounds": item["remaining_rounds"]}
                for item in conditions
            ]
    return payload


def session_payload(session):
    return {
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": public_active(session),
        "order": public_order(session),
    }


def create_combat_session(body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")
    session_id = body.get("id")
    if type(session_id) is not str:
        raise BadRequest("id must be a string")

    order = rank_combatants(body, require_nonempty=True, require_unique_names=True)
    session = {
        "id": session_id,
        "round": 1,
        "turn_index": 0,
        "order": order,
        "conditions": {item["name"]: [] for item in order},
        "condition_targets": set(),
    }

    with COMBAT_LOCK:
        with db_connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM combat_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if existing is not None:
                raise BadRequest("session id must be unique")
            save_combat_session(conn, session)
            return session_payload(session)


def get_combat_session(session_id, conn=None):
    if conn is None:
        with db_connect() as inner_conn:
            return get_combat_session(session_id, inner_conn)
    row = conn.execute(
        "SELECT payload_json FROM combat_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise NotFound("session not found")
    return decode_session(row["payload_json"])


def add_condition(session_id, body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")
    target = body.get("target")
    condition = body.get("condition")
    duration = require_int(body.get("duration_rounds"), "duration_rounds")
    if type(target) is not str:
        raise BadRequest("target must be a string")
    if type(condition) is not str:
        raise BadRequest("condition must be a string")
    if duration <= 0:
        raise BadRequest("duration_rounds must be positive")

    with COMBAT_LOCK:
        with db_connect() as conn:
            session = get_combat_session(session_id, conn)
            if target not in session["conditions"]:
                raise BadRequest("target must name a combatant")
            session["condition_targets"].add(target)
            session["conditions"][target].append(
                {"condition": condition, "remaining_rounds": duration}
            )
            save_combat_session(conn, session)
            return {
                "target": target,
                "conditions": [
                    {"condition": item["condition"], "remaining_rounds": item["remaining_rounds"]}
                    for item in session["conditions"][target]
                ],
            }


def advance_combat(session_id):
    with COMBAT_LOCK:
        with db_connect() as conn:
            session = get_combat_session(session_id, conn)
            session["turn_index"] += 1
            if session["turn_index"] >= len(session["order"]):
                session["turn_index"] = 0
                session["round"] += 1

            active_name = session["order"][session["turn_index"]]["name"]
            remaining = []
            for item in session["conditions"][active_name]:
                next_rounds = item["remaining_rounds"] - 1
                if next_rounds > 0:
                    remaining.append(
                        {"condition": item["condition"], "remaining_rounds": next_rounds}
                    )
            session["conditions"][active_name] = remaining
            save_combat_session(conn, session)

            return {
                "id": session["id"],
                "round": session["round"],
                "turn_index": session["turn_index"],
                "active": public_active(session),
                "conditions": public_conditions(session),
            }


def public_monster(row, include_tags):
    payload = {
        "slug": row["slug"],
        "name": row["name"],
        "cr": row["cr"],
        "armor_class": row["armor_class"],
        "hit_points": row["hit_points"],
    }
    if include_tags:
        payload["tags"] = json.loads(row["tags_json"])
    return payload


def validate_monster_body(body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")
    tags = body.get("tags")
    if not isinstance(tags, list):
        raise BadRequest("tags must be an array")
    clean_tags = []
    for tag in tags:
        clean_tags.append(require_string(tag, "tag"))
    return {
        "slug": require_slug(body.get("slug")),
        "name": require_string(body.get("name"), "name"),
        "cr": require_string(body.get("cr"), "cr"),
        "armor_class": require_int(body.get("armor_class"), "armor_class"),
        "hit_points": require_int(body.get("hit_points"), "hit_points"),
        "tags": clean_tags,
    }


def create_monster(body):
    monster = validate_monster_body(body)
    with COMPENDIUM_LOCK:
        with db_connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM compendium_monsters WHERE slug = ?", (monster["slug"],)
            ).fetchone()
            if existing is not None:
                raise Conflict("monster slug already exists")
            conn.execute(
                """
                INSERT INTO compendium_monsters(
                    slug, name, cr, armor_class, hit_points, tags_json
                )
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    monster["slug"],
                    monster["name"],
                    monster["cr"],
                    monster["armor_class"],
                    monster["hit_points"],
                    json.dumps(monster["tags"], separators=(",", ":")),
                ),
            )
    return {
        "slug": monster["slug"],
        "name": monster["name"],
        "cr": monster["cr"],
        "armor_class": monster["armor_class"],
        "hit_points": monster["hit_points"],
    }


def read_monster(slug):
    require_slug(slug)
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT slug, name, cr, armor_class, hit_points, tags_json
            FROM compendium_monsters
            WHERE slug = ?
            """,
            (slug,),
        ).fetchone()
    if row is None:
        raise NotFound("monster not found")
    return public_monster(row, include_tags=True)


def validate_item_body(body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")
    return {
        "slug": require_slug(body.get("slug")),
        "name": require_string(body.get("name"), "name"),
        "type": require_string(body.get("type"), "type"),
        "rarity": require_string(body.get("rarity"), "rarity"),
        "cost_gp": require_int(body.get("cost_gp"), "cost_gp"),
    }


def create_item(body):
    item = validate_item_body(body)
    with COMPENDIUM_LOCK:
        with db_connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM compendium_items WHERE slug = ?", (item["slug"],)
            ).fetchone()
            if existing is not None:
                raise Conflict("item slug already exists")
            conn.execute(
                """
                INSERT INTO compendium_items(slug, name, type, rarity, cost_gp)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    item["slug"],
                    item["name"],
                    item["type"],
                    item["rarity"],
                    item["cost_gp"],
                ),
            )
    return item


def read_item(slug):
    require_slug(slug)
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT slug, name, type, rarity, cost_gp
            FROM compendium_items
            WHERE slug = ?
            """,
            (slug,),
        ).fetchone()
    if row is None:
        raise NotFound("item not found")
    return {
        "slug": row["slug"],
        "name": row["name"],
        "type": row["type"],
        "rarity": row["rarity"],
        "cost_gp": row["cost_gp"],
    }


def campaign_exists(conn, campaign_id):
    return (
        conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        is not None
    )


def create_campaign(body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")
    campaign = {
        "id": require_string(body.get("id"), "id"),
        "name": require_string(body.get("name"), "name"),
        "dm": require_string(body.get("dm"), "dm"),
    }

    with CAMPAIGN_LOCK:
        with db_connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM campaigns WHERE id = ?", (campaign["id"],)
            ).fetchone()
            if existing is not None:
                raise Conflict("campaign id already exists")
            conn.execute(
                "INSERT INTO campaigns(id, name, dm) VALUES(?, ?, ?)",
                (campaign["id"], campaign["name"], campaign["dm"]),
            )
    return campaign


def add_campaign_character(campaign_id, body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")
    character = {
        "id": require_string(body.get("id"), "id"),
        "name": require_string(body.get("name"), "name"),
        "level": require_int(body.get("level"), "level"),
        "class": require_string(body.get("class"), "class"),
    }

    with CAMPAIGN_LOCK:
        with db_connect() as conn:
            if not campaign_exists(conn, campaign_id):
                raise NotFound("campaign not found")
            existing = conn.execute(
                "SELECT 1 FROM campaign_characters WHERE id = ?", (character["id"],)
            ).fetchone()
            if existing is not None:
                raise Conflict("character id already exists")
            conn.execute(
                """
                INSERT INTO campaign_characters(id, campaign_id, name, level, class)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    character["id"],
                    campaign_id,
                    character["name"],
                    character["level"],
                    character["class"],
                ),
            )
    return character


def add_campaign_event(campaign_id, body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")
    event = {
        "id": require_string(body.get("id"), "id"),
        "kind": require_string(body.get("kind"), "kind"),
        "summary": require_string(body.get("summary"), "summary"),
    }

    with CAMPAIGN_LOCK:
        with db_connect() as conn:
            if not campaign_exists(conn, campaign_id):
                raise NotFound("campaign not found")
            existing = conn.execute(
                "SELECT 1 FROM campaign_events WHERE id = ?", (event["id"],)
            ).fetchone()
            if existing is not None:
                raise Conflict("event id already exists")
            conn.execute(
                """
                INSERT INTO campaign_events(id, campaign_id, kind, summary)
                VALUES(?, ?, ?, ?)
                """,
                (event["id"], campaign_id, event["kind"], event["summary"]),
            )
    return {"id": event["id"], "kind": event["kind"]}


def read_campaign_state(campaign_id):
    with db_connect() as conn:
        campaign = conn.execute(
            "SELECT id, name, dm FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            raise NotFound("campaign not found")
        characters = conn.execute(
            """
            SELECT id, name, level, class
            FROM campaign_characters
            WHERE campaign_id = ?
            ORDER BY rowid
            """,
            (campaign_id,),
        ).fetchall()
        log_count = conn.execute(
            "SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["count"]

    return {
        "id": campaign["id"],
        "name": campaign["name"],
        "dm": campaign["dm"],
        "characters": [
            {
                "id": row["id"],
                "name": row["name"],
                "level": row["level"],
                "class": row["class"],
            }
            for row in characters
        ],
        "log_count": log_count,
    }


def require_campaign_id(body):
    if not isinstance(body, dict):
        raise BadRequest("body must be an object")
    return require_string(body.get("campaign_id"), "campaign_id")


def require_existing_campaign(conn, campaign_id):
    if not campaign_exists(conn, campaign_id):
        raise NotFound("campaign not found")


def dm_encounter_builder(body):
    campaign_id = require_campaign_id(body)
    party = body.get("party")
    monster_slugs = body.get("monster_slugs")
    if not isinstance(party, list) or not isinstance(monster_slugs, list):
        raise BadRequest("party and monster_slugs must be arrays")
    if not monster_slugs:
        raise BadRequest("monster_slugs must not be empty")

    with db_connect() as conn:
        require_existing_campaign(conn, campaign_id)
        cr_counts = {}
        for slug in monster_slugs:
            require_slug(slug)
            row = conn.execute(
                "SELECT cr FROM compendium_monsters WHERE slug = ?", (slug,)
            ).fetchone()
            if row is None:
                raise NotFound("monster not found")
            cr = row["cr"]
            cr_counts[cr] = cr_counts.get(cr, 0) + 1

    result = adjusted_xp(
        {
            "party": party,
            "monsters": [
                {"cr": cr, "count": count}
                for cr, count in sorted(cr_counts.items())
            ],
        }
    )
    recommendation = {
        "trivial": "safe warm-up",
        "easy": "safe warm-up",
        "medium": "balanced challenge",
        "hard": "dangerous fight",
        "deadly": "deadly threat",
    }[result["difficulty"]]
    return {
        "campaign_id": campaign_id,
        "base_xp": result["base_xp"],
        "adjusted_xp": result["adjusted_xp"],
        "difficulty": result["difficulty"],
        "monster_count": result["monster_count"],
        "recommendation": recommendation,
    }


def dm_loot_parcel(body):
    campaign_id = require_campaign_id(body)
    tier = require_int(body.get("tier"), "tier")
    require_int(body.get("seed"), "seed")
    if tier != 1:
        raise BadRequest("unsupported loot tier")

    with db_connect() as conn:
        require_existing_campaign(conn, campaign_id)
        item = conn.execute(
            "SELECT 1 FROM compendium_items WHERE slug = ?", ("healing-potion",)
        ).fetchone()
        if item is None:
            raise NotFound("item not found")

    return {
        "campaign_id": campaign_id,
        "coins_gp": 75,
        "items": [{"slug": "healing-potion", "quantity": 2}],
    }


def dm_session_recap(body):
    campaign_id = require_campaign_id(body)
    with db_connect() as conn:
        require_existing_campaign(conn, campaign_id)
        events = conn.execute(
            """
            SELECT summary
            FROM campaign_events
            WHERE campaign_id = ?
            ORDER BY rowid
            """,
            (campaign_id,),
        ).fetchall()

    summary = events[-1]["summary"] if events else ""
    open_threads = []
    if "goblin trail" in summary.lower():
        open_threads.append("Resolve goblin trail ambush")
    return {
        "campaign_id": campaign_id,
        "summary": summary,
        "open_threads": open_threads,
    }


class Handler(BaseHTTPRequestHandler):
    routes = {
        "/v1/dice/stats": dice_stats,
        "/v1/checks/ability": ability_check,
        "/v1/characters/ability-modifier": ability_modifier,
        "/v1/characters/proficiency": proficiency,
        "/v1/characters/derived-stats": derived_stats,
        "/v1/phb/spell-slots": spell_slots,
        "/v1/phb/rests/long": long_rest,
        "/v1/phb/equipment-load": equipment_load,
        "/v1/encounters/adjusted-xp": adjusted_xp,
        "/v1/initiative/order": initiative_order,
        "/v1/combat/sessions": create_combat_session,
        "/v1/auth/register": register_user,
        "/v1/auth/login": login_user,
        "/v1/compendium/monsters": create_monster,
        "/v1/compendium/items": create_item,
        "/v1/campaigns": create_campaign,
        "/v1/dm/encounter-builder": dm_encounter_builder,
        "/v1/dm/loot-parcel": dm_loot_parcel,
        "/v1/dm/session-recap": dm_session_recap,
    }

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/health":
                self.send_json(200, {"ok": True})
            elif path == "/v1/storage/status":
                self.send_json(200, storage_status())
            else:
                self.handle_resource_get(path)
        except BadRequest as exc:
            self.send_json(400, {"error": str(exc)})
        except NotFound as exc:
            self.send_json(404, {"error": str(exc)})

    def handle_resource_get(self, path):
        campaign_match = re.fullmatch(r"/v1/campaigns/([^/]+)/state", path)
        if campaign_match:
            self.send_json(200, read_campaign_state(unquote(campaign_match.group(1))))
            return

        monster_match = re.fullmatch(r"/v1/compendium/monsters/([^/]+)", path)
        if monster_match:
            self.send_json(200, read_monster(unquote(monster_match.group(1))))
            return

        item_match = re.fullmatch(r"/v1/compendium/items/([^/]+)", path)
        if item_match:
            self.send_json(200, read_item(unquote(item_match.group(1))))
            return

        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/v1/storage/reset":
            self.send_json(200, reset_storage())
            return

        route = self.routes.get(path)
        if route is None:
            self.handle_dynamic_post(path)
            return

        try:
            body = self.read_json()
            payload = route(body)
        except BadRequest as exc:
            self.send_json(400, {"error": str(exc)})
            return
        except NotFound as exc:
            self.send_json(404, {"error": str(exc)})
            return
        except Unauthorized as exc:
            self.send_json(401, {"error": str(exc)})
            return
        except Conflict as exc:
            self.send_json(409, {"error": str(exc)})
            return
        created_routes = {
            "/v1/auth/register",
            "/v1/compendium/monsters",
            "/v1/compendium/items",
            "/v1/campaigns",
        }
        status = 201 if path in created_routes else 200
        self.send_json(status, payload)

    def handle_dynamic_post(self, path):
        campaign_match = re.fullmatch(
            r"/v1/campaigns/([^/]+)/(characters|events)", path
        )
        if campaign_match:
            campaign_id = unquote(campaign_match.group(1))
            action = campaign_match.group(2)
            try:
                if action == "characters":
                    payload = add_campaign_character(campaign_id, self.read_json())
                else:
                    payload = add_campaign_event(campaign_id, self.read_json())
            except BadRequest as exc:
                self.send_json(400, {"error": str(exc)})
                return
            except NotFound as exc:
                self.send_json(404, {"error": str(exc)})
                return
            except Conflict as exc:
                self.send_json(409, {"error": str(exc)})
                return
            self.send_json(201, payload)
            return

        match = re.fullmatch(r"/v1/combat/sessions/([^/]+)/(conditions|advance)", path)
        if not match:
            self.send_json(404, {"error": "not found"})
            return

        session_id = unquote(match.group(1))
        action = match.group(2)
        try:
            if action == "conditions":
                payload = add_condition(session_id, self.read_json())
            else:
                payload = advance_combat(session_id)
        except BadRequest as exc:
            self.send_json(400, {"error": str(exc)})
            return
        except NotFound as exc:
            self.send_json(404, {"error": str(exc)})
            return
        self.send_json(200, payload)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise BadRequest("invalid content length") from exc

        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8") if raw else "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BadRequest("invalid json") from exc

    def send_json(self, status, payload):
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        return


def main():
    initialize_storage()
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
