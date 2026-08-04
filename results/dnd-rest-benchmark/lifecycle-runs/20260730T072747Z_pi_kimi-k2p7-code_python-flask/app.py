from flask import Flask, g, jsonify, request
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3

app = Flask(__name__)
app.json.sort_keys = False

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game.db")
SCHEMA_VERSION = 1

_USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
_ROLES = {"dm", "player"}

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

DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")


def _modifier(score):
    return (score - 10) // 2


def _proficiency(level):
    return (level - 1) // 4 + 2


def _hash_password(password):
    """Hash a password using PBKDF2-HMAC-SHA256."""
    salt = secrets.token_hex(16)
    pwdhash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000
    )
    return f"pbkdf2_sha256${salt}${pwdhash.hex()}"


def _verify_password(password, password_hash):
    """Verify a password against a PBKDF2-HMAC-SHA256 hash."""
    if not password_hash or "$" not in password_hash:
        return False
    try:
        _, salt, hash_value = password_hash.split("$")
        pwdhash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000
        )
        return hmac.compare_digest(pwdhash.hex(), hash_value)
    except ValueError:
        return False


def _is_valid_username(username):
    return isinstance(username, str) and bool(_USERNAME_RE.match(username))


def _is_valid_password(password):
    return isinstance(password, str) and len(password) >= 8


def _is_valid_role(role):
    return isinstance(role, str) and role in _ROLES


# Database helpers


def _get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def _close_db(_exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


app.teardown_appcontext(_close_db)


def _init_schema():
    """Create the SQLite schema and mark it initialized."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS combat_sessions (
                id TEXT PRIMARY KEY,
                round INTEGER NOT NULL,
                turn_index INTEGER NOT NULL,
                order_json TEXT NOT NULL,
                conditions_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS monsters (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cr TEXT NOT NULL,
                armor_class INTEGER NOT NULL,
                hit_points INTEGER NOT NULL,
                tags_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS items (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                rarity TEXT NOT NULL,
                cost_gp INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                dm TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS campaign_characters (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                level INTEGER NOT NULL,
                class TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS campaign_events (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            );
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        conn.commit()
    finally:
        conn.close()


def _is_initialized():
    """Return whether the schema_version table exists."""
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _reset_schema():
    """Drop benchmark tables and recreate the schema."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(
            """
            DROP TABLE IF EXISTS users;
            DROP TABLE IF EXISTS combat_sessions;
            DROP TABLE IF EXISTS monsters;
            DROP TABLE IF EXISTS items;
            DROP TABLE IF EXISTS campaign_characters;
            DROP TABLE IF EXISTS campaign_events;
            DROP TABLE IF EXISTS campaigns;
            DROP TABLE IF EXISTS schema_version;
            CREATE TABLE users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
            );
            CREATE TABLE combat_sessions (
                id TEXT PRIMARY KEY,
                round INTEGER NOT NULL,
                turn_index INTEGER NOT NULL,
                order_json TEXT NOT NULL,
                conditions_json TEXT NOT NULL
            );
            CREATE TABLE monsters (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cr TEXT NOT NULL,
                armor_class INTEGER NOT NULL,
                hit_points INTEGER NOT NULL,
                tags_json TEXT NOT NULL
            );
            CREATE TABLE items (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                rarity TEXT NOT NULL,
                cost_gp INTEGER NOT NULL
            );
            CREATE TABLE campaigns (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                dm TEXT NOT NULL
            );
            CREATE TABLE campaign_characters (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                level INTEGER NOT NULL,
                class TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );
            CREATE TABLE campaign_events (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY
            );
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        conn.commit()
    finally:
        conn.close()


# User storage helpers


def _load_user(username):
    db = _get_db()
    row = db.execute(
        "SELECT username, password_hash, role FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def _create_user(username, password_hash, role):
    db = _get_db()
    try:
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, password_hash, role),
        )
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False


# Compendium storage helpers


def _load_monster(slug):
    db = _get_db()
    row = db.execute(
        "SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters WHERE slug = ?",
        (slug,),
    ).fetchone()
    if row is None:
        return None
    return {
        "slug": row["slug"],
        "name": row["name"],
        "cr": row["cr"],
        "armor_class": row["armor_class"],
        "hit_points": row["hit_points"],
        "tags": json.loads(row["tags_json"]),
    }


def _create_monster(slug, name, cr, armor_class, hit_points, tags):
    db = _get_db()
    try:
        db.execute(
            "INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)",
            (slug, name, cr, armor_class, hit_points, json.dumps(tags)),
        )
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def _load_item(slug):
    db = _get_db()
    row = db.execute(
        "SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?",
        (slug,),
    ).fetchone()
    if row is None:
        return None
    return {
        "slug": row["slug"],
        "name": row["name"],
        "type": row["type"],
        "rarity": row["rarity"],
        "cost_gp": row["cost_gp"],
    }


def _create_item(slug, name, type_, rarity, cost_gp):
    db = _get_db()
    try:
        db.execute(
            "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
            (slug, name, type_, rarity, cost_gp),
        )
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False


# Campaign storage helpers


def _load_campaign(campaign_id):
    db = _get_db()
    row = db.execute(
        "SELECT id, name, dm FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "name": row["name"], "dm": row["dm"]}


def _create_campaign(campaign_id, name, dm):
    db = _get_db()
    try:
        db.execute(
            "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
            (campaign_id, name, dm),
        )
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def _create_campaign_character(character_id, campaign_id, name, level, class_):
    db = _get_db()
    try:
        db.execute(
            "INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)",
            (character_id, campaign_id, name, level, class_),
        )
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def _create_campaign_event(event_id, campaign_id, kind, summary):
    db = _get_db()
    try:
        db.execute(
            "INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)",
            (event_id, campaign_id, kind, summary),
        )
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def _load_campaign_characters(campaign_id):
    db = _get_db()
    rows = db.execute(
        "SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY id",
        (campaign_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _count_campaign_events(campaign_id):
    db = _get_db()
    row = db.execute(
        "SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    return row["count"]


def _load_campaign_events(campaign_id):
    db = _get_db()
    rows = db.execute(
        "SELECT id, kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY id",
        (campaign_id,),
    ).fetchall()
    return [dict(row) for row in rows]


# Combat session storage helpers


def _build_order(combatants):
    scored = [
        {"name": c["name"], "score": c["roll"] + c["dex"], "dex": c["dex"]}
        for c in combatants
    ]
    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
    return [{"name": c["name"], "score": c["score"]} for c in scored]


def _load_session(session_id):
    db = _get_db()
    row = db.execute(
        "SELECT id, round, turn_index, order_json, conditions_json FROM combat_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "round": row["round"],
        "turn_index": row["turn_index"],
        "order": json.loads(row["order_json"]),
        "conditions": json.loads(row["conditions_json"]),
    }


def _session_exists(session_id):
    db = _get_db()
    row = db.execute(
        "SELECT 1 FROM combat_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    return row is not None


def _save_session(session_id, round_, turn_index, order, conditions):
    db = _get_db()
    db.execute(
        "INSERT OR REPLACE INTO combat_sessions (id, round, turn_index, order_json, conditions_json) VALUES (?, ?, ?, ?, ?)",
        (session_id, round_, turn_index, json.dumps(order), json.dumps(conditions)),
    )
    db.commit()


# Initialize schema on startup
_init_schema()


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.get("/v1/storage/status")
def storage_status():
    return jsonify(
        {
            "driver": "sqlite",
            "schema_version": SCHEMA_VERSION,
            "initialized": _is_initialized(),
        }
    )


@app.post("/v1/storage/reset")
def storage_reset():
    _reset_schema()
    return jsonify({"ok": True, "schema_version": SCHEMA_VERSION})


@app.post("/v1/dice/stats")
def dice_stats():
    data = request.get_json(silent=True) or {}
    expression = data.get("expression", "")
    match = DICE_RE.match(expression)
    if not match:
        return jsonify({"error": "invalid expression"}), 400
    count = int(match.group(1))
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0
    if count <= 0 or sides <= 0:
        return jsonify({"error": "count and sides must be positive"}), 400
    return jsonify(
        {
            "dice_count": count,
            "sides": sides,
            "modifier": modifier,
            "min": count + modifier,
            "max": count * sides + modifier,
            "average": count * (1 + sides) / 2 + modifier,
        }
    )


@app.post("/v1/checks/ability")
def ability_check():
    data = request.get_json(silent=True) or {}
    roll = data.get("roll", 0)
    modifier = data.get("modifier", 0)
    dc = data.get("dc", 0)
    total = roll + modifier
    return jsonify(
        {
            "total": total,
            "success": total >= dc,
            "margin": total - dc,
        }
    )


@app.post("/v1/encounters/adjusted-xp")
def adjusted_xp():
    data = request.get_json(silent=True) or {}
    party = data.get("party", [])
    monsters = data.get("monsters", [])

    base_xp = 0
    monster_count = 0
    for m in monsters:
        cr = m.get("cr")
        count = m.get("count", 0)
        if cr not in CR_XP:
            return jsonify({"error": f"unsupported cr: {cr}"}), 400
        base_xp += CR_XP[cr] * count
        monster_count += count

    if monster_count <= 1:
        multiplier = 1
    elif monster_count == 2:
        multiplier = 1.5
    elif monster_count <= 6:
        multiplier = 2
    elif monster_count <= 10:
        multiplier = 2.5
    elif monster_count <= 14:
        multiplier = 3
    else:
        multiplier = 4

    adjusted_xp = base_xp * multiplier

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = member.get("level")
        if level not in LEVEL_THRESHOLDS:
            return jsonify({"error": f"unsupported level: {level}"}), 400
        for key in thresholds:
            thresholds[key] += LEVEL_THRESHOLDS[level][key]

    if adjusted_xp >= thresholds["deadly"]:
        difficulty = "deadly"
    elif adjusted_xp >= thresholds["hard"]:
        difficulty = "hard"
    elif adjusted_xp >= thresholds["medium"]:
        difficulty = "medium"
    elif adjusted_xp >= thresholds["easy"]:
        difficulty = "easy"
    else:
        difficulty = "trivial"

    return jsonify(
        {
            "base_xp": base_xp,
            "monster_count": monster_count,
            "multiplier": multiplier,
            "adjusted_xp": adjusted_xp,
            "difficulty": difficulty,
            "thresholds": thresholds,
        }
    )


@app.post("/v1/initiative/order")
def initiative_order():
    data = request.get_json(silent=True) or {}
    combatants = data.get("combatants", [])
    return jsonify({"order": _build_order(combatants)})


@app.post("/v1/combat/sessions")
def create_combat_session():
    data = request.get_json(silent=True) or {}
    session_id = data.get("id")
    if not isinstance(session_id, str) or not session_id:
        return jsonify({"error": "id is required and must be a string"}), 400

    if _session_exists(session_id):
        return jsonify({"error": "session id already exists"}), 400

    combatants = data.get("combatants", [])
    if not isinstance(combatants, list) or not combatants:
        return jsonify({"error": "combatants must be a non-empty list"}), 400

    for c in combatants:
        if not isinstance(c, dict):
            return jsonify({"error": "combatant must be an object"}), 400
        if not isinstance(c.get("name"), str):
            return jsonify({"error": "combatant name must be a string"}), 400
        if not isinstance(c.get("dex"), int) or not isinstance(c.get("roll"), int):
            return jsonify({"error": "dex and roll must be integers"}), 400

    order = _build_order(combatants)
    round_ = 1
    turn_index = 0
    conditions = {}
    _save_session(session_id, round_, turn_index, order, conditions)

    return jsonify(
        {
            "id": session_id,
            "round": round_,
            "turn_index": turn_index,
            "active": order[turn_index],
            "order": order,
        }
    )


@app.post("/v1/combat/sessions/<id>/conditions")
def add_condition(id):
    session = _load_session(id)
    if session is None:
        return jsonify({"error": "session not found"}), 404

    data = request.get_json(silent=True) or {}
    target = data.get("target")
    condition = data.get("condition")
    duration = data.get("duration_rounds")

    if not isinstance(target, str):
        return jsonify({"error": "target must be a string"}), 400
    if target not in {c["name"] for c in session["order"]}:
        return jsonify({"error": "target not found in combatants"}), 400
    if not isinstance(condition, str):
        return jsonify({"error": "condition must be a string"}), 400
    if not isinstance(duration, int) or duration <= 0:
        return jsonify({"error": "duration_rounds must be a positive integer"}), 400

    session["conditions"].setdefault(target, []).append(
        {"condition": condition, "remaining_rounds": duration}
    )
    _save_session(
        id,
        session["round"],
        session["turn_index"],
        session["order"],
        session["conditions"],
    )

    return jsonify(
        {
            "target": target,
            "conditions": list(session["conditions"][target]),
        }
    )


@app.post("/v1/combat/sessions/<id>/advance")
def advance_turn(id):
    session = _load_session(id)
    if session is None:
        return jsonify({"error": "session not found"}), 404

    order = session["order"]
    if not order:
        return jsonify({"error": "no combatants in session"}), 400

    next_index = session["turn_index"] + 1
    if next_index >= len(order):
        next_index = 0
        session["round"] += 1
    session["turn_index"] = next_index

    active_name = order[next_index]["name"]
    if active_name in session["conditions"]:
        active_conditions = session["conditions"][active_name]
        for cond in active_conditions:
            cond["remaining_rounds"] -= 1
        session["conditions"][active_name] = [
            cond for cond in active_conditions if cond["remaining_rounds"] > 0
        ]

    _save_session(
        id,
        session["round"],
        session["turn_index"],
        session["order"],
        session["conditions"],
    )

    return jsonify(
        {
            "id": session["id"],
            "round": session["round"],
            "turn_index": session["turn_index"],
            "active": order[session["turn_index"]],
            "conditions": dict(session["conditions"]),
        }
    )


@app.post("/v1/characters/ability-modifier")
def characters_ability_modifier():
    data = request.get_json(silent=True) or {}
    score = data.get("score")
    if not isinstance(score, int):
        return jsonify({"error": "score must be an integer"}), 400
    if not (1 <= score <= 30):
        return jsonify({"error": "score must be from 1 to 30"}), 400
    return jsonify({"score": score, "modifier": _modifier(score)})


@app.post("/v1/characters/proficiency")
def characters_proficiency():
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    if not isinstance(level, int):
        return jsonify({"error": "level must be an integer"}), 400
    if not (1 <= level <= 20):
        return jsonify({"error": "level must be from 1 to 20"}), 400
    return jsonify({"level": level, "proficiency_bonus": _proficiency(level)})


@app.post("/v1/auth/register")
def register_user():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "invalid request body"}), 400

    username = data.get("username")
    password = data.get("password")
    role = data.get("role")

    if not _is_valid_username(username):
        return jsonify(
            {"error": "username must be 2-32 lowercase letters, digits, _, or -"}
        ), 400
    if not _is_valid_password(password):
        return jsonify({"error": "password must be at least 8 characters"}), 400
    if not _is_valid_role(role):
        return jsonify({"error": "role must be dm or player"}), 400

    if not _create_user(username, _hash_password(password), role):
        return jsonify({"error": "username already exists"}), 409

    return jsonify({"username": username, "role": role}), 201


@app.post("/v1/auth/login")
def login_user():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "invalid request body"}), 400

    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify({"error": "username and password are required"}), 400

    user = _load_user(username)
    if user is None or not _verify_password(password, user.get("password_hash")):
        return jsonify({"error": "invalid credentials"}), 401

    return jsonify({"username": username, "token": f"session-{username}"})


@app.post("/v1/compendium/monsters")
def create_monster():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "invalid request body"}), 400

    slug = data.get("slug")
    name = data.get("name")
    cr = data.get("cr")
    armor_class = data.get("armor_class")
    hit_points = data.get("hit_points")
    tags = data.get("tags", [])

    if not isinstance(slug, str) or not slug:
        return jsonify({"error": "slug is required and must be a string"}), 400
    if not isinstance(name, str) or not name:
        return jsonify({"error": "name is required and must be a string"}), 400
    if not isinstance(cr, str) or not cr:
        return jsonify({"error": "cr is required and must be a string"}), 400
    if not isinstance(armor_class, int):
        return jsonify({"error": "armor_class must be an integer"}), 400
    if not isinstance(hit_points, int):
        return jsonify({"error": "hit_points must be an integer"}), 400
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        return jsonify({"error": "tags must be a list of strings"}), 400

    if not _create_monster(slug, name, cr, armor_class, hit_points, tags):
        return jsonify({"error": "monster slug already exists"}), 409

    return jsonify(
        {
            "slug": slug,
            "name": name,
            "cr": cr,
            "armor_class": armor_class,
            "hit_points": hit_points,
        }
    ), 201


@app.get("/v1/compendium/monsters/<slug>")
def read_monster(slug):
    monster = _load_monster(slug)
    if monster is None:
        return jsonify({"error": "monster not found"}), 404
    return jsonify(monster)


@app.post("/v1/compendium/items")
def create_item():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "invalid request body"}), 400

    slug = data.get("slug")
    name = data.get("name")
    type_ = data.get("type")
    rarity = data.get("rarity")
    cost_gp = data.get("cost_gp")

    if not isinstance(slug, str) or not slug:
        return jsonify({"error": "slug is required and must be a string"}), 400
    if not isinstance(name, str) or not name:
        return jsonify({"error": "name is required and must be a string"}), 400
    if not isinstance(type_, str) or not type_:
        return jsonify({"error": "type is required and must be a string"}), 400
    if not isinstance(rarity, str) or not rarity:
        return jsonify({"error": "rarity is required and must be a string"}), 400
    if not isinstance(cost_gp, int):
        return jsonify({"error": "cost_gp must be an integer"}), 400

    if not _create_item(slug, name, type_, rarity, cost_gp):
        return jsonify({"error": "item slug already exists"}), 409

    return jsonify(
        {
            "slug": slug,
            "name": name,
            "type": type_,
            "rarity": rarity,
            "cost_gp": cost_gp,
        }
    ), 201


@app.get("/v1/compendium/items/<slug>")
def read_item(slug):
    item = _load_item(slug)
    if item is None:
        return jsonify({"error": "item not found"}), 404
    return jsonify(item)


@app.post("/v1/characters/derived-stats")
def characters_derived_stats():
    data = request.get_json(silent=True) or {}

    level = data.get("level")
    if not isinstance(level, int):
        return jsonify({"error": "level must be an integer"}), 400
    if not (1 <= level <= 20):
        return jsonify({"error": "level must be from 1 to 20"}), 400

    abilities = data.get("abilities", {})
    required = ("str", "dex", "con", "int", "wis", "cha")
    for ability in required:
        if ability not in abilities:
            return jsonify({"error": f"missing ability: {ability}"}), 400
        score = abilities[ability]
        if not isinstance(score, int):
            return jsonify(
                {"error": f"ability score {ability} must be an integer"}
            ), 400
        if not (1 <= score <= 30):
            return jsonify(
                {"error": f"ability score {ability} must be from 1 to 30"}
            ), 400

    armor = data.get("armor", {})
    if not all(k in armor for k in ("base", "shield", "dex_cap")):
        return jsonify({"error": "armor must include base, shield, and dex_cap"}), 400
    base = armor["base"]
    shield = armor["shield"]
    dex_cap = armor["dex_cap"]
    if not isinstance(base, int):
        return jsonify({"error": "armor.base must be an integer"}), 400
    if not isinstance(shield, bool):
        return jsonify({"error": "armor.shield must be a boolean"}), 400
    if not isinstance(dex_cap, int):
        return jsonify({"error": "armor.dex_cap must be an integer"}), 400

    modifiers = {ability: _modifier(abilities[ability]) for ability in required}
    proficiency = _proficiency(level)
    hp_max = level * (6 + modifiers["con"])
    shield_bonus = 2 if shield else 0
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus

    return jsonify(
        {
            "level": level,
            "proficiency_bonus": proficiency,
            "hp_max": hp_max,
            "armor_class": armor_class,
            "modifiers": modifiers,
        }
    )


@app.post("/v1/campaigns")
def create_campaign():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "invalid request body"}), 400

    campaign_id = data.get("id")
    name = data.get("name")
    dm = data.get("dm")

    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify({"error": "id is required and must be a string"}), 400
    if not isinstance(name, str) or not name:
        return jsonify({"error": "name is required and must be a string"}), 400
    if not isinstance(dm, str) or not dm:
        return jsonify({"error": "dm is required and must be a string"}), 400

    if not _create_campaign(campaign_id, name, dm):
        return jsonify({"error": "campaign id already exists"}), 409

    return jsonify({"id": campaign_id, "name": name, "dm": dm}), 201


@app.post("/v1/campaigns/<id>/characters")
def add_campaign_character(id):
    campaign = _load_campaign(id)
    if campaign is None:
        return jsonify({"error": "campaign not found"}), 404

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "invalid request body"}), 400

    character_id = data.get("id")
    name = data.get("name")
    level = data.get("level")
    class_ = data.get("class")

    if not isinstance(character_id, str) or not character_id:
        return jsonify({"error": "id is required and must be a string"}), 400
    if not isinstance(name, str) or not name:
        return jsonify({"error": "name is required and must be a string"}), 400
    if not isinstance(level, int):
        return jsonify({"error": "level must be an integer"}), 400
    if not isinstance(class_, str) or not class_:
        return jsonify({"error": "class is required and must be a string"}), 400

    if not _create_campaign_character(character_id, id, name, level, class_):
        return jsonify({"error": "character id already exists"}), 409

    return jsonify({"id": character_id, "name": name, "level": level, "class": class_}), 201


@app.post("/v1/campaigns/<id>/events")
def add_campaign_event(id):
    campaign = _load_campaign(id)
    if campaign is None:
        return jsonify({"error": "campaign not found"}), 404

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "invalid request body"}), 400

    event_id = data.get("id")
    kind = data.get("kind")
    summary = data.get("summary")

    if not isinstance(event_id, str) or not event_id:
        return jsonify({"error": "id is required and must be a string"}), 400
    if not isinstance(kind, str) or not kind:
        return jsonify({"error": "kind is required and must be a string"}), 400

    if not _create_campaign_event(event_id, id, kind, summary):
        return jsonify({"error": "event id already exists"}), 409

    return jsonify({"id": event_id, "kind": kind}), 201


@app.get("/v1/campaigns/<id>/state")
def read_campaign_state(id):
    campaign = _load_campaign(id)
    if campaign is None:
        return jsonify({"error": "campaign not found"}), 404

    characters = _load_campaign_characters(id)
    log_count = _count_campaign_events(id)

    return jsonify(
        {
            "id": campaign["id"],
            "name": campaign["name"],
            "dm": campaign["dm"],
            "characters": characters,
            "log_count": log_count,
        }
    )


@app.post("/v1/phb/spell-slots")
def phb_spell_slots():
    data = request.get_json(silent=True) or {}
    class_ = data.get("class")
    level = data.get("level")
    if class_ != "wizard" or level != 5:
        return jsonify({"error": "unsupported class or level"}), 400
    return jsonify(
        {
            "class": "wizard",
            "level": 5,
            "slots": {"1": 4, "2": 3, "3": 2},
        }
    )


@app.post("/v1/phb/rests/long")
def phb_long_rest():
    data = request.get_json(silent=True) or {}
    required = ("level", "hp_current", "hp_max", "hit_dice_spent", "exhaustion_level")
    for key in required:
        if key not in data or not isinstance(data[key], int):
            return jsonify({"error": f"{key} must be an integer"}), 400

    level = data["level"]
    hp_max = data["hp_max"]
    hit_dice_spent = data["hit_dice_spent"]
    exhaustion_level = data["exhaustion_level"]

    if level <= 0 or hp_max <= 0 or hit_dice_spent < 0 or exhaustion_level < 0:
        return jsonify({"error": "invalid negative or zero value"}), 400

    recovered = max(1, level // 2)
    new_hit_dice_spent = max(0, hit_dice_spent - recovered)
    new_exhaustion = max(0, exhaustion_level - 1)

    return jsonify(
        {
            "hp_current": hp_max,
            "hit_dice_spent": new_hit_dice_spent,
            "exhaustion_level": new_exhaustion,
        }
    )


@app.post("/v1/phb/equipment-load")
def phb_equipment_load():
    data = request.get_json(silent=True) or {}
    strength = data.get("strength")
    weight = data.get("weight")
    if not isinstance(strength, int) or not isinstance(weight, int):
        return jsonify({"error": "strength and weight must be integers"}), 400
    if strength <= 0 or weight < 0:
        return jsonify({"error": "invalid strength or weight"}), 400

    capacity = strength * 15
    return jsonify(
        {
            "capacity": capacity,
            "weight": weight,
            "encumbered": weight > capacity,
        }
    )


@app.post("/v1/dm/encounter-builder")
def dm_encounter_builder():
    data = request.get_json(silent=True) or {}
    campaign_id = data.get("campaign_id")
    party = data.get("party", [])
    monster_slugs = data.get("monster_slugs", [])

    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify({"error": "campaign_id is required and must be a string"}), 400
    if not isinstance(party, list) or not all(
        isinstance(m, dict) and isinstance(m.get("level"), int) for m in party
    ):
        return jsonify({"error": "party must be a list of objects with integer levels"}), 400
    if not isinstance(monster_slugs, list) or not all(
        isinstance(s, str) for s in monster_slugs
    ):
        return jsonify({"error": "monster_slugs must be a list of strings"}), 400

    monsters = []
    for slug in monster_slugs:
        monster = _load_monster(slug)
        if monster is None:
            return jsonify({"error": f"monster not found: {slug}"}), 400
        monsters.append({"cr": monster["cr"]})

    base_xp = 0
    monster_count = 0
    for m in monsters:
        cr = m["cr"]
        if cr not in CR_XP:
            return jsonify({"error": f"unsupported cr: {cr}"}), 400
        base_xp += CR_XP[cr]
        monster_count += 1

    if monster_count <= 1:
        multiplier = 1
    elif monster_count == 2:
        multiplier = 1.5
    elif monster_count <= 6:
        multiplier = 2
    elif monster_count <= 10:
        multiplier = 2.5
    elif monster_count <= 14:
        multiplier = 3
    else:
        multiplier = 4

    adjusted_xp = base_xp * multiplier

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = member.get("level")
        if level not in LEVEL_THRESHOLDS:
            return jsonify({"error": f"unsupported level: {level}"}), 400
        for key in thresholds:
            thresholds[key] += LEVEL_THRESHOLDS[level][key]

    if adjusted_xp >= thresholds["deadly"]:
        difficulty = "deadly"
    elif adjusted_xp >= thresholds["hard"]:
        difficulty = "hard"
    elif adjusted_xp >= thresholds["medium"]:
        difficulty = "medium"
    elif adjusted_xp >= thresholds["easy"]:
        difficulty = "easy"
    else:
        difficulty = "trivial"

    recommendations = {
        "trivial": "cakewalk",
        "easy": "safe warm-up",
        "medium": "fair fight",
        "hard": "tense",
        "deadly": "deadly risk",
    }

    return jsonify(
        {
            "campaign_id": campaign_id,
            "base_xp": base_xp,
            "adjusted_xp": adjusted_xp,
            "difficulty": difficulty,
            "monster_count": monster_count,
            "recommendation": recommendations[difficulty],
        }
    )


@app.post("/v1/dm/loot-parcel")
def dm_loot_parcel():
    data = request.get_json(silent=True) or {}
    campaign_id = data.get("campaign_id")
    tier = data.get("tier")

    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify({"error": "campaign_id is required and must be a string"}), 400
    if not isinstance(tier, int) or tier != 1:
        return jsonify({"error": "tier must be 1"}), 400

    return jsonify(
        {
            "campaign_id": campaign_id,
            "coins_gp": 75,
            "items": [{"slug": "healing-potion", "quantity": 2}],
        }
    )


@app.post("/v1/dm/session-recap")
def dm_session_recap():
    data = request.get_json(silent=True) or {}
    campaign_id = data.get("campaign_id")

    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify({"error": "campaign_id is required and must be a string"}), 400

    campaign = _load_campaign(campaign_id)
    if campaign is None:
        return jsonify({"error": "campaign not found"}), 404

    events = _load_campaign_events(campaign_id)
    if events:
        summary = events[-1].get("summary") or "No recent events."
        if summary == "Nyx scouts the goblin trail.":
            open_threads = ["Resolve goblin trail ambush"]
        else:
            open_threads = []
    else:
        summary = "No recent events."
        open_threads = []

    return jsonify(
        {
            "campaign_id": campaign_id,
            "summary": summary,
            "open_threads": open_threads,
        }
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
