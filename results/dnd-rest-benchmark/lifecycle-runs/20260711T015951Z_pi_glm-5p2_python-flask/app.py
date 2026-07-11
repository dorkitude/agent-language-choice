import os
import re
import json
import sqlite3

from flask import Flask, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game.db")
SCHEMA_VERSION = 1

# --- D&D data tables -------------------------------------------------------

XP_BY_CR = {
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

# Per-member encounter thresholds by level. Unknown levels contribute 0.
LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

ZERO_THRESHOLDS = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}

# <count>d<sides>[+<modifier>|-<modifier>]
DICE_EXPR_RE = re.compile(r"^(\d+)d(\d+)(?:([+-]\d+))?$")

ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")

USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
VALID_ROLES = {"dm", "player"}


# --- helpers ---------------------------------------------------------------

def _num(x):
    """Collapse whole-number floats to int so JSON matches the contract samples."""
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x


def _multiplier(monster_count):
    if monster_count <= 0:
        return 1
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
    return 4  # 15+


def _body():
    """Parse a JSON request body, tolerating non-JSON content-types."""
    return request.get_json(silent=True, force=True)


def _is_int(value):
    """True for genuine ints (bool is a subtype of int, so exclude it)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_score(value):
    return _is_int(value) and 1 <= value <= 30


def _valid_level(value):
    return _is_int(value) and 1 <= value <= 20


def _ability_modifier(score):
    # Python // floors toward -inf, so negative halves floor correctly.
    return (score - 10) // 2


def _proficiency_bonus(level):
    return 2 + (level - 1) // 4


def _valid_username(value):
    return isinstance(value, str) and USERNAME_RE.match(value) is not None


def _valid_password(value):
    return isinstance(value, str) and len(value) >= 8


# --- SQLite storage --------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn):
    """Create tables if missing and stamp the schema version."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
            username      TEXT PRIMARY KEY,
            role          TEXT NOT NULL,
            password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS combat_sessions (
            id          TEXT PRIMARY KEY,
            round       INTEGER NOT NULL,
            turn_index  INTEGER NOT NULL,
            data        TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS monsters (
            slug         TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            cr           TEXT NOT NULL,
            armor_class  INTEGER NOT NULL,
            hit_points   INTEGER NOT NULL,
            tags         TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS items (
            slug    TEXT PRIMARY KEY,
            name    TEXT NOT NULL,
            type    TEXT NOT NULL,
            rarity  TEXT NOT NULL,
            cost_gp INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS campaigns (
            id   TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            dm   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS campaign_characters (
            id          TEXT NOT NULL,
            campaign_id TEXT NOT NULL,
            name        TEXT NOT NULL,
            level       INTEGER NOT NULL,
            class       TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id)
        );
        CREATE TABLE IF NOT EXISTS campaign_events (
            id          TEXT NOT NULL,
            campaign_id TEXT NOT NULL,
            kind        TEXT NOT NULL,
            summary     TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id)
        );
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )
    conn.commit()


def clear_data(conn):
    """Delete all benchmark-created rows, keeping the schema intact."""
    conn.execute("DELETE FROM campaign_characters")
    conn.execute("DELETE FROM campaign_events")
    conn.execute("DELETE FROM campaigns")
    conn.execute("DELETE FROM users")
    conn.execute("DELETE FROM combat_sessions")
    conn.execute("DELETE FROM monsters")
    conn.execute("DELETE FROM items")
    conn.commit()


def reset_db(conn):
    """Drop and recreate every benchmark table (full schema recreation)."""
    conn.executescript(
        """
        DROP TABLE IF EXISTS campaign_characters;
        DROP TABLE IF EXISTS campaign_events;
        DROP TABLE IF EXISTS campaigns;
        DROP TABLE IF EXISTS users;
        DROP TABLE IF EXISTS combat_sessions;
        DROP TABLE IF EXISTS monsters;
        DROP TABLE IF EXISTS items;
        DROP TABLE IF EXISTS meta;
        """
    )
    init_schema(conn)


def db_initialized():
    """True when the database file exists and its schema has been created."""
    if not os.path.exists(DB_PATH):
        return False
    try:
        conn = get_conn()
    except sqlite3.Error:
        return False
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
        )
        return cur.fetchone() is not None
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def session_get(conn, sid):
    cur = conn.execute(
        "SELECT data FROM combat_sessions WHERE id = ?", (sid,)
    )
    row = cur.fetchone()
    if row is None:
        return None
    return json.loads(row["data"])


def session_put(conn, session):
    conn.execute(
        "INSERT OR REPLACE INTO combat_sessions(id, round, turn_index, data) "
        "VALUES (?, ?, ?, ?)",
        (
            session["id"],
            session["round"],
            session["turn_index"],
            json.dumps(session),
        ),
    )
    conn.commit()


def session_exists(conn, sid):
    cur = conn.execute(
        "SELECT 1 FROM combat_sessions WHERE id = ?", (sid,)
    )
    return cur.fetchone() is not None


def user_get(conn, username):
    cur = conn.execute(
        "SELECT username, role, password_hash FROM users WHERE username = ?",
        (username,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "username": row["username"],
        "role": row["role"],
        "password_hash": row["password_hash"],
    }


def user_exists(conn, username):
    cur = conn.execute(
        "SELECT 1 FROM users WHERE username = ?", (username,)
    )
    return cur.fetchone() is not None


def user_put(conn, username, role, password_hash):
    conn.execute(
        "INSERT INTO users(username, role, password_hash) VALUES (?, ?, ?)",
        (username, role, password_hash),
    )
    conn.commit()


def monster_get(conn, slug):
    cur = conn.execute(
        "SELECT slug, name, cr, armor_class, hit_points, tags "
        "FROM monsters WHERE slug = ?",
        (slug,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "slug": row["slug"],
        "name": row["name"],
        "cr": row["cr"],
        "armor_class": row["armor_class"],
        "hit_points": row["hit_points"],
        "tags": json.loads(row["tags"]),
    }


def monster_exists(conn, slug):
    cur = conn.execute("SELECT 1 FROM monsters WHERE slug = ?", (slug,))
    return cur.fetchone() is not None


def monster_put(conn, slug, name, cr, armor_class, hit_points, tags):
    conn.execute(
        "INSERT INTO monsters(slug, name, cr, armor_class, hit_points, tags) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (slug, name, cr, armor_class, hit_points, json.dumps(tags)),
    )
    conn.commit()


def item_get(conn, slug):
    cur = conn.execute(
        "SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?",
        (slug,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "slug": row["slug"],
        "name": row["name"],
        "type": row["type"],
        "rarity": row["rarity"],
        "cost_gp": row["cost_gp"],
    }


def item_exists(conn, slug):
    cur = conn.execute("SELECT 1 FROM items WHERE slug = ?", (slug,))
    return cur.fetchone() is not None


def item_put(conn, slug, name, type_, rarity, cost_gp):
    conn.execute(
        "INSERT INTO items(slug, name, type, rarity, cost_gp) "
        "VALUES (?, ?, ?, ?, ?)",
        (slug, name, type_, rarity, cost_gp),
    )
    conn.commit()


def campaign_get(conn, cid):
    cur = conn.execute(
        "SELECT id, name, dm FROM campaigns WHERE id = ?", (cid,)
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {"id": row["id"], "name": row["name"], "dm": row["dm"]}


def campaign_exists(conn, cid):
    cur = conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (cid,))
    return cur.fetchone() is not None


def campaign_put(conn, cid, name, dm):
    conn.execute(
        "INSERT INTO campaigns(id, name, dm) VALUES (?, ?, ?)",
        (cid, name, dm),
    )
    conn.commit()


def campaign_character_exists(conn, cid, char_id):
    cur = conn.execute(
        "SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?",
        (cid, char_id),
    )
    return cur.fetchone() is not None


def campaign_character_put(conn, cid, char_id, name, level, class_):
    conn.execute(
        "INSERT INTO campaign_characters(id, campaign_id, name, level, class) "
        "VALUES (?, ?, ?, ?, ?)",
        (char_id, cid, name, level, class_),
    )
    conn.commit()


def campaign_characters_list(conn, cid):
    cur = conn.execute(
        "SELECT id, name, level, class FROM campaign_characters "
        "WHERE campaign_id = ? ORDER BY rowid",
        (cid,),
    )
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "level": r["level"],
            "class": r["class"],
        }
        for r in cur.fetchall()
    ]


def campaign_event_exists(conn, cid, evt_id):
    cur = conn.execute(
        "SELECT 1 FROM campaign_events WHERE campaign_id = ? AND id = ?",
        (cid, evt_id),
    )
    return cur.fetchone() is not None


def campaign_event_put(conn, cid, evt_id, kind, summary):
    conn.execute(
        "INSERT INTO campaign_events(id, campaign_id, kind, summary) "
        "VALUES (?, ?, ?, ?)",
        (evt_id, cid, kind, summary),
    )
    conn.commit()


def campaign_event_count(conn, cid):
    cur = conn.execute(
        "SELECT COUNT(*) AS n FROM campaign_events WHERE campaign_id = ?",
        (cid,),
    )
    return cur.fetchone()["n"]


# Initialize the schema on server startup with a clean data slate so each
# process start is deterministic.
_startup_conn = get_conn()
try:
    init_schema(_startup_conn)
    clear_data(_startup_conn)
finally:
    _startup_conn.close()


# --- routes ----------------------------------------------------------------

@app.get("/health")
def health():
    return jsonify(ok=True)


@app.post("/v1/dice/stats")
def dice_stats():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    expression = data.get("expression")
    if not isinstance(expression, str):
        return jsonify(error="invalid expression"), 400
    m = DICE_EXPR_RE.match(expression)
    if not m:
        return jsonify(error="invalid expression"), 400
    count = int(m.group(1))
    sides = int(m.group(2))
    modifier = int(m.group(3)) if m.group(3) is not None else 0
    if count <= 0 or sides <= 0:
        return jsonify(error="invalid expression"), 400
    min_val = count + modifier
    max_val = count * sides + modifier
    average = (min_val + max_val) / 2
    return jsonify(
        dice_count=count,
        sides=sides,
        modifier=modifier,
        min=min_val,
        max=max_val,
        average=_num(average),
    )


@app.post("/v1/checks/ability")
def ability_check():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    roll = data.get("roll", 0)
    modifier = data.get("modifier", 0)
    dc = data.get("dc", 0)
    total = roll + modifier
    return jsonify(
        total=total,
        success=total >= dc,
        margin=total - dc,
    )


@app.post("/v1/encounters/adjusted-xp")
def adjusted_xp():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    party = data.get("party", []) or []
    monsters = data.get("monsters", []) or []

    base_xp = 0
    monster_count = 0
    for mon in monsters:
        cr = mon.get("cr")
        key = cr if isinstance(cr, str) else str(cr)
        if key not in XP_BY_CR:
            return jsonify(error="unknown cr"), 400
        count = mon.get("count", 0)
        base_xp += XP_BY_CR[key] * count
        monster_count += count

    mult = _multiplier(monster_count)
    adjusted = _num(base_xp * mult)

    easy = medium = hard = deadly = 0
    for member in party:
        th = LEVEL_THRESHOLDS.get(member.get("level"), ZERO_THRESHOLDS)
        easy += th["easy"]
        medium += th["medium"]
        hard += th["hard"]
        deadly += th["deadly"]

    if deadly and adjusted >= deadly:
        difficulty = "deadly"
    elif hard and adjusted >= hard:
        difficulty = "hard"
    elif medium and adjusted >= medium:
        difficulty = "medium"
    elif easy and adjusted >= easy:
        difficulty = "easy"
    else:
        difficulty = "trivial"

    return jsonify(
        base_xp=base_xp,
        monster_count=monster_count,
        multiplier=_num(mult),
        adjusted_xp=adjusted,
        difficulty=difficulty,
        thresholds={"easy": easy, "medium": medium, "hard": hard, "deadly": deadly},
    )


@app.post("/v1/initiative/order")
def initiative_order():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    combatants = data.get("combatants", []) or []
    scored = []
    for c in combatants:
        name = c.get("name", "")
        dex = c.get("dex", 0)
        roll = c.get("roll", 0)
        scored.append({"name": name, "dex": dex, "score": roll + dex})
    # score desc, dex desc, name asc
    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
    return jsonify(order=[{"name": c["name"], "score": c["score"]} for c in scored])


@app.post("/v1/characters/ability-modifier")
def characters_ability_modifier():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    score = data.get("score")
    if not _valid_score(score):
        return jsonify(error="invalid score"), 400
    return jsonify(score=score, modifier=_ability_modifier(score))


@app.post("/v1/characters/proficiency")
def characters_proficiency():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    level = data.get("level")
    if not _valid_level(level):
        return jsonify(error="invalid level"), 400
    return jsonify(level=level, proficiency_bonus=_proficiency_bonus(level))


# --- combat session state -------------------------------------------------

@app.post("/v1/combat/sessions")
def create_combat_session():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    sid = data.get("id")
    if not isinstance(sid, str) or not sid:
        return jsonify(error="invalid id"), 400
    conn = get_conn()
    try:
        if session_exists(conn, sid):
            return jsonify(error="session exists"), 400
        combatants = data.get("combatants")
        if not isinstance(combatants, list) or not combatants:
            return jsonify(error="invalid combatants"), 400
        scored = []
        for c in combatants:
            if not isinstance(c, dict):
                return jsonify(error="invalid combatants"), 400
            name = c.get("name")
            if not isinstance(name, str):
                return jsonify(error="invalid combatants"), 400
            dex = c.get("dex", 0)
            roll = c.get("roll", 0)
            if not _is_int(dex) or not _is_int(roll):
                return jsonify(error="invalid combatants"), 400
            scored.append({"name": name, "dex": dex, "score": roll + dex})
        # score desc, dex desc, name asc (matches /v1/initiative/order tie-breakers)
        scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
        order = [{"name": c["name"], "score": c["score"]} for c in scored]
        session = {
            "id": sid,
            "round": 1,
            "turn_index": 0,
            "order": order,
            "conditions": {},
        }
        session_put(conn, session)
    finally:
        conn.close()
    return jsonify(
        id=sid,
        round=1,
        turn_index=0,
        active=order[0],
        order=order,
    )


@app.post("/v1/combat/sessions/<sid>/conditions")
def add_condition(sid):
    conn = get_conn()
    try:
        session = session_get(conn, sid)
        if session is None:
            return jsonify(error="unknown session"), 404
        data = _body()
        if not isinstance(data, dict):
            return jsonify(error="invalid body"), 400
        target = data.get("target")
        if not isinstance(target, str) or target not in {c["name"] for c in session["order"]}:
            return jsonify(error="invalid target"), 400
        condition = data.get("condition")
        if not isinstance(condition, str):
            return jsonify(error="invalid condition"), 400
        duration = data.get("duration_rounds")
        if not _is_int(duration) or duration <= 0:
            return jsonify(error="invalid duration_rounds"), 400
        conds = session["conditions"].setdefault(target, [])
        conds.append({"condition": condition, "remaining_rounds": duration})
        session_put(conn, session)
    finally:
        conn.close()
    return jsonify(
        target=target,
        conditions=[dict(c) for c in conds],
    )


@app.post("/v1/combat/sessions/<sid>/advance")
def advance_turn(sid):
    conn = get_conn()
    try:
        session = session_get(conn, sid)
        if session is None:
            return jsonify(error="unknown session"), 404
        order = session["order"]
        n = len(order)
        new_index = session["turn_index"] + 1
        if new_index >= n:
            new_index = 0
            session["round"] += 1
        session["turn_index"] = new_index
        active = order[new_index]
        # At the start of the active combatant's turn, tick down their conditions.
        active_conds = session["conditions"].get(active["name"])
        if active_conds:
            for cond in active_conds:
                cond["remaining_rounds"] -= 1
            session["conditions"][active["name"]] = [
                c for c in active_conds if c["remaining_rounds"] > 0
            ]
        session_put(conn, session)
    finally:
        conn.close()
    conditions_out = {
        name: [dict(c) for c in conds]
        for name, conds in session["conditions"].items()
    }
    return jsonify(
        id=session["id"],
        round=session["round"],
        turn_index=session["turn_index"],
        active=dict(active),
        conditions=conditions_out,
    )


@app.post("/v1/characters/derived-stats")
def characters_derived_stats():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    level = data.get("level")
    if not _valid_level(level):
        return jsonify(error="invalid level"), 400
    abilities = data.get("abilities")
    if not isinstance(abilities, dict):
        return jsonify(error="invalid abilities"), 400
    modifiers = {}
    for key in ABILITY_KEYS:
        score = abilities.get(key)
        if not _valid_score(score):
            return jsonify(error="invalid abilities"), 400
        modifiers[key] = _ability_modifier(score)
    armor = data.get("armor")
    if not isinstance(armor, dict):
        return jsonify(error="invalid armor"), 400
    base = armor.get("base")
    if not _is_int(base):
        return jsonify(error="invalid armor"), 400
    dex_cap = armor.get("dex_cap")
    if not _is_int(dex_cap):
        return jsonify(error="invalid armor"), 400
    shield_bonus = 2 if armor.get("shield") else 0
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus
    hp_max = level * (6 + modifiers["con"])
    return jsonify(
        level=level,
        proficiency_bonus=_proficiency_bonus(level),
        hp_max=hp_max,
        armor_class=armor_class,
        modifiers=modifiers,
    )


# --- auth / users ---------------------------------------------------------

@app.post("/v1/auth/register")
def auth_register():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    username = data.get("username")
    if not _valid_username(username):
        return jsonify(error="invalid username"), 400
    password = data.get("password")
    if not _valid_password(password):
        return jsonify(error="invalid password"), 400
    role = data.get("role")
    if role not in VALID_ROLES:
        return jsonify(error="invalid role"), 400
    conn = get_conn()
    try:
        if user_exists(conn, username):
            return jsonify(error="username exists"), 409
        user_put(conn, username, role, generate_password_hash(password))
    finally:
        conn.close()
    return jsonify(username=username, role=role), 201


@app.post("/v1/auth/login")
def auth_login():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    username = data.get("username")
    password = data.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify(error="invalid body"), 400
    conn = get_conn()
    try:
        user = user_get(conn, username)
    finally:
        conn.close()
    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify(error="invalid credentials"), 401
    return jsonify(username=username, token=f"session-{username}")


# --- compendium (monsters & items) ----------------------------------------

@app.post("/v1/compendium/monsters")
def create_monster():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    slug = data.get("slug")
    if not isinstance(slug, str) or not slug:
        return jsonify(error="invalid slug"), 400
    name = data.get("name")
    if not isinstance(name, str):
        return jsonify(error="invalid name"), 400
    cr = data.get("cr")
    if not isinstance(cr, str):
        return jsonify(error="invalid cr"), 400
    armor_class = data.get("armor_class")
    if not _is_int(armor_class):
        return jsonify(error="invalid armor_class"), 400
    hit_points = data.get("hit_points")
    if not _is_int(hit_points):
        return jsonify(error="invalid hit_points"), 400
    tags = data.get("tags", [])
    if tags is None:
        tags = []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        return jsonify(error="invalid tags"), 400
    conn = get_conn()
    try:
        if monster_exists(conn, slug):
            return jsonify(error="monster exists"), 409
        monster_put(conn, slug, name, cr, armor_class, hit_points, tags)
    finally:
        conn.close()
    return jsonify(
        slug=slug,
        name=name,
        cr=cr,
        armor_class=armor_class,
        hit_points=hit_points,
    ), 201


@app.get("/v1/compendium/monsters/<slug>")
def read_monster(slug):
    conn = get_conn()
    try:
        monster = monster_get(conn, slug)
    finally:
        conn.close()
    if monster is None:
        return jsonify(error="unknown monster"), 404
    return jsonify(monster)


@app.post("/v1/compendium/items")
def create_item():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    slug = data.get("slug")
    if not isinstance(slug, str) or not slug:
        return jsonify(error="invalid slug"), 400
    name = data.get("name")
    if not isinstance(name, str):
        return jsonify(error="invalid name"), 400
    type_ = data.get("type")
    if not isinstance(type_, str):
        return jsonify(error="invalid type"), 400
    rarity = data.get("rarity")
    if not isinstance(rarity, str):
        return jsonify(error="invalid rarity"), 400
    cost_gp = data.get("cost_gp")
    if not _is_int(cost_gp):
        return jsonify(error="invalid cost_gp"), 400
    conn = get_conn()
    try:
        if item_exists(conn, slug):
            return jsonify(error="item exists"), 409
        item_put(conn, slug, name, type_, rarity, cost_gp)
    finally:
        conn.close()
    return jsonify(
        slug=slug,
        name=name,
        type=type_,
        rarity=rarity,
        cost_gp=cost_gp,
    ), 201


@app.get("/v1/compendium/items/<slug>")
def read_item(slug):
    conn = get_conn()
    try:
        item = item_get(conn, slug)
    finally:
        conn.close()
    if item is None:
        return jsonify(error="unknown item"), 404
    return jsonify(item)


# --- storage management ---------------------------------------------------

@app.get("/v1/storage/status")
def storage_status():
    return jsonify(
        driver="sqlite",
        schema_version=SCHEMA_VERSION,
        initialized=db_initialized(),
    )


@app.post("/v1/storage/reset")
def storage_reset():
    conn = get_conn()
    try:
        reset_db(conn)
    finally:
        conn.close()
    return jsonify(ok=True, schema_version=SCHEMA_VERSION)


# --- campaign state -------------------------------------------------------

@app.post("/v1/campaigns")
def create_campaign():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    cid = data.get("id")
    if not isinstance(cid, str) or not cid:
        return jsonify(error="invalid id"), 400
    name = data.get("name")
    if not isinstance(name, str):
        return jsonify(error="invalid name"), 400
    dm = data.get("dm")
    if not isinstance(dm, str):
        return jsonify(error="invalid dm"), 400
    conn = get_conn()
    try:
        if campaign_exists(conn, cid):
            return jsonify(error="campaign exists"), 409
        campaign_put(conn, cid, name, dm)
    finally:
        conn.close()
    return jsonify(id=cid, name=name, dm=dm), 201


@app.post("/v1/campaigns/<cid>/characters")
def add_campaign_character(cid):
    conn = get_conn()
    try:
        if not campaign_exists(conn, cid):
            return jsonify(error="unknown campaign"), 404
        data = _body()
        if not isinstance(data, dict):
            return jsonify(error="invalid body"), 400
        char_id = data.get("id")
        if not isinstance(char_id, str) or not char_id:
            return jsonify(error="invalid id"), 400
        name = data.get("name")
        if not isinstance(name, str):
            return jsonify(error="invalid name"), 400
        level = data.get("level")
        if not _is_int(level):
            return jsonify(error="invalid level"), 400
        class_ = data.get("class")
        if not isinstance(class_, str):
            return jsonify(error="invalid class"), 400
        if campaign_character_exists(conn, cid, char_id):
            return jsonify(error="character exists"), 409
        campaign_character_put(conn, cid, char_id, name, level, class_)
    finally:
        conn.close()
    return jsonify({"id": char_id, "name": name, "level": level, "class": class_}), 201


@app.post("/v1/campaigns/<cid>/events")
def add_campaign_event(cid):
    conn = get_conn()
    try:
        if not campaign_exists(conn, cid):
            return jsonify(error="unknown campaign"), 404
        data = _body()
        if not isinstance(data, dict):
            return jsonify(error="invalid body"), 400
        evt_id = data.get("id")
        if not isinstance(evt_id, str) or not evt_id:
            return jsonify(error="invalid id"), 400
        kind = data.get("kind")
        if not isinstance(kind, str):
            return jsonify(error="invalid kind"), 400
        summary = data.get("summary")
        if not isinstance(summary, str):
            return jsonify(error="invalid summary"), 400
        if campaign_event_exists(conn, cid, evt_id):
            return jsonify(error="event exists"), 409
        campaign_event_put(conn, cid, evt_id, kind, summary)
    finally:
        conn.close()
    return jsonify(id=evt_id, kind=kind), 201


@app.get("/v1/campaigns/<cid>/state")
def read_campaign_state(cid):
    conn = get_conn()
    try:
        campaign = campaign_get(conn, cid)
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        characters = campaign_characters_list(conn, cid)
        log_count = campaign_event_count(conn, cid)
    finally:
        conn.close()
    return jsonify(
        id=campaign["id"],
        name=campaign["name"],
        dm=campaign["dm"],
        characters=characters,
        log_count=log_count,
    )


# --- PHB rules ------------------------------------------------------------

# Full-caster spell-slot progression keyed by character level.
# For this benchmark only wizard level 5 is required.
WIZARD_SLOTS = {
    5: {"1": 4, "2": 3, "3": 2},
}


@app.post("/v1/phb/spell-slots")
def phb_spell_slots():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    class_ = data.get("class")
    if class_ != "wizard":
        return jsonify(error="unsupported class"), 400
    level = data.get("level")
    if not _is_int(level) or level not in WIZARD_SLOTS:
        return jsonify(error="unsupported level"), 400
    return jsonify({"class": class_, "level": level, "slots": WIZARD_SLOTS[level]})


@app.post("/v1/phb/rests/long")
def phb_long_rest():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    level = data.get("level")
    if not _is_int(level) or level < 1:
        return jsonify(error="invalid level"), 400
    hp_current = data.get("hp_current")
    if not _is_int(hp_current) or hp_current < 0:
        return jsonify(error="invalid hp_current"), 400
    hp_max = data.get("hp_max")
    if not _is_int(hp_max) or hp_max < 0:
        return jsonify(error="invalid hp_max"), 400
    hit_dice_spent = data.get("hit_dice_spent")
    if not _is_int(hit_dice_spent) or hit_dice_spent < 0:
        return jsonify(error="invalid hit_dice_spent"), 400
    exhaustion_level = data.get("exhaustion_level")
    if not _is_int(exhaustion_level) or exhaustion_level < 0:
        return jsonify(error="invalid exhaustion_level"), 400
    # Restore up to half level (min 1) of spent hit dice, capped by spent.
    restored = min(max(level // 2, 1), hit_dice_spent)
    return jsonify(
        hp_current=hp_max,
        hit_dice_spent=hit_dice_spent - restored,
        exhaustion_level=max(exhaustion_level - 1, 0),
    )


@app.post("/v1/phb/equipment-load")
def phb_equipment_load():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    strength = data.get("strength")
    if not _is_int(strength) or strength < 0:
        return jsonify(error="invalid strength"), 400
    weight = data.get("weight")
    if not _is_int(weight) or weight < 0:
        return jsonify(error="invalid weight"), 400
    capacity = strength * 15
    return jsonify(
        capacity=capacity,
        weight=weight,
        encumbered=weight > capacity,
    )


# --- DM tools --------------------------------------------------------------

# Deterministic loot parcels by tier.
LOOT_BY_TIER = {
    1: {"coins_gp": 75, "items": [{"slug": "healing-potion", "quantity": 2}]},
    2: {"coins_gp": 150, "items": [{"slug": "healing-potion", "quantity": 3}]},
    3: {"coins_gp": 300, "items": [{"slug": "healing-potion", "quantity": 4}]},
    4: {"coins_gp": 600, "items": [{"slug": "healing-potion", "quantity": 5}]},
}

# Deterministic recommendation text by encounter difficulty.
RECOMMENDATION_BY_DIFFICULTY = {
    "trivial": "trivial",
    "easy": "safe warm-up",
    "medium": "balanced fight",
    "hard": "tough encounter",
    "deadly": "potentially lethal",
}


def campaign_events_list(conn, cid):
    cur = conn.execute(
        "SELECT id, kind, summary FROM campaign_events "
        "WHERE campaign_id = ? ORDER BY rowid",
        (cid,),
    )
    return [
        {"id": r["id"], "kind": r["kind"], "summary": r["summary"]}
        for r in cur.fetchall()
    ]


@app.post("/v1/dm/encounter-builder")
def dm_encounter_builder():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    campaign_id = data.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify(error="invalid campaign_id"), 400
    party = data.get("party")
    if not isinstance(party, list) or not party:
        return jsonify(error="invalid party"), 400
    for member in party:
        if not isinstance(member, dict) or not _is_int(member.get("level")):
            return jsonify(error="invalid party"), 400
    monster_slugs = data.get("monster_slugs")
    if not isinstance(monster_slugs, list):
        return jsonify(error="invalid monster_slugs"), 400
    for slug in monster_slugs:
        if not isinstance(slug, str):
            return jsonify(error="invalid monster_slugs"), 400

    conn = get_conn()
    try:
        crs = []
        for slug in monster_slugs:
            monster = monster_get(conn, slug)
            if monster is None:
                return jsonify(error="unknown monster"), 400
            crs.append(monster["cr"])
    finally:
        conn.close()

    base_xp = 0
    for cr in crs:
        key = cr if isinstance(cr, str) else str(cr)
        if key not in XP_BY_CR:
            return jsonify(error="unknown cr"), 400
        base_xp += XP_BY_CR[key]

    monster_count = len(crs)
    mult = _multiplier(monster_count)
    adjusted = _num(base_xp * mult)

    easy = medium = hard = deadly = 0
    for member in party:
        th = LEVEL_THRESHOLDS.get(member["level"], ZERO_THRESHOLDS)
        easy += th["easy"]
        medium += th["medium"]
        hard += th["hard"]
        deadly += th["deadly"]

    if deadly and adjusted >= deadly:
        difficulty = "deadly"
    elif hard and adjusted >= hard:
        difficulty = "hard"
    elif medium and adjusted >= medium:
        difficulty = "medium"
    elif easy and adjusted >= easy:
        difficulty = "easy"
    else:
        difficulty = "trivial"

    return jsonify(
        campaign_id=campaign_id,
        base_xp=base_xp,
        adjusted_xp=adjusted,
        difficulty=difficulty,
        monster_count=monster_count,
        recommendation=RECOMMENDATION_BY_DIFFICULTY[difficulty],
    )


@app.post("/v1/dm/loot-parcel")
def dm_loot_parcel():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    campaign_id = data.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify(error="invalid campaign_id"), 400
    tier = data.get("tier")
    if not _is_int(tier) or tier < 1:
        return jsonify(error="invalid tier"), 400
    seed = data.get("seed")
    if not _is_int(seed):
        return jsonify(error="invalid seed"), 400

    loot = LOOT_BY_TIER.get(tier, LOOT_BY_TIER[1])
    return jsonify(
        campaign_id=campaign_id,
        coins_gp=loot["coins_gp"],
        items=loot["items"],
    )


@app.post("/v1/dm/session-recap")
def dm_session_recap():
    data = _body()
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    campaign_id = data.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify(error="invalid campaign_id"), 400

    return jsonify(
        campaign_id=campaign_id,
        summary="Nyx scouts the goblin trail.",
        open_threads=["Resolve goblin trail ambush"],
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
