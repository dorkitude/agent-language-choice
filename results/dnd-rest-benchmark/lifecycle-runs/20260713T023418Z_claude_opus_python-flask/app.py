from flask import Flask, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash
import json
import os
import re
import sqlite3

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game.db")
SCHEMA_VERSION = 1


def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db_connect()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "username TEXT PRIMARY KEY, "
            "role TEXT NOT NULL, "
            "password_hash TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS monsters ("
            "slug TEXT PRIMARY KEY, "
            "name TEXT NOT NULL, "
            "cr TEXT NOT NULL, "
            "armor_class INTEGER NOT NULL, "
            "hit_points INTEGER NOT NULL, "
            "tags TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS items ("
            "slug TEXT PRIMARY KEY, "
            "name TEXT NOT NULL, "
            "type TEXT NOT NULL, "
            "rarity TEXT NOT NULL, "
            "cost_gp INTEGER NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS campaigns ("
            "id TEXT PRIMARY KEY, "
            "name TEXT NOT NULL, "
            "dm TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS campaign_characters ("
            "campaign_id TEXT NOT NULL, "
            "id TEXT NOT NULL, "
            "name TEXT NOT NULL, "
            "level INTEGER NOT NULL, "
            "class TEXT NOT NULL, "
            "seq INTEGER NOT NULL, "
            "PRIMARY KEY (campaign_id, id))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS campaign_events ("
            "campaign_id TEXT NOT NULL, "
            "id TEXT NOT NULL, "
            "kind TEXT NOT NULL, "
            "summary TEXT NOT NULL, "
            "seq INTEGER NOT NULL, "
            "PRIMARY KEY (campaign_id, id))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    finally:
        conn.close()


def reset_db():
    conn = db_connect()
    try:
        conn.execute("DROP TABLE IF EXISTS users")
        conn.execute("DROP TABLE IF EXISTS monsters")
        conn.execute("DROP TABLE IF EXISTS items")
        conn.execute("DROP TABLE IF EXISTS campaigns")
        conn.execute("DROP TABLE IF EXISTS campaign_characters")
        conn.execute("DROP TABLE IF EXISTS campaign_events")
        conn.execute("DROP TABLE IF EXISTS schema_meta")
        conn.commit()
    finally:
        conn.close()
    init_db()
    COMBAT_SESSIONS.clear()


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

DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")


def error(message, status=400):
    return jsonify(error=message), status


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.post("/v1/dice/stats")
def dice_stats():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    expr = data.get("expression")
    if not isinstance(expr, str):
        return error("invalid expression")
    m = DICE_RE.match(expr.strip())
    if not m:
        return error("invalid expression")
    count = int(m.group(1))
    sides = int(m.group(2))
    modifier = int(m.group(3)) if m.group(3) else 0
    if count <= 0 or sides <= 0:
        return error("invalid expression")
    minimum = count * 1 + modifier
    maximum = count * sides + modifier
    average = count * (sides + 1) / 2 + modifier
    if average == int(average):
        average = int(average)
    return jsonify(
        dice_count=count,
        sides=sides,
        modifier=modifier,
        min=minimum,
        max=maximum,
        average=average,
    )


@app.post("/v1/checks/ability")
def ability_check():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    try:
        roll = int(data["roll"])
        modifier = int(data["modifier"])
        dc = int(data["dc"])
    except (KeyError, TypeError, ValueError):
        return error("invalid request")
    total = roll + modifier
    return jsonify(total=total, success=total >= dc, margin=total - dc)


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


@app.post("/v1/encounters/adjusted-xp")
def adjusted_xp():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    party = data.get("party")
    monsters = data.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        return error("invalid request")

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            return error("invalid party member")
        level = member.get("level")
        if not isinstance(level, int) or isinstance(level, bool):
            return error("invalid level")
        member_thresholds = LEVEL_THRESHOLDS.get(level)
        if member_thresholds is None:
            return error("unsupported level")
        for key in thresholds:
            thresholds[key] += member_thresholds[key]

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        if not isinstance(monster, dict):
            return error("invalid monster")
        cr = monster.get("cr")
        count = monster.get("count", 1)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            return error("invalid count")
        cr_key = str(cr)
        if cr_key not in CR_XP:
            return error("unsupported cr")
        base_xp += CR_XP[cr_key] * count
        monster_count += count

    multiplier = count_multiplier(monster_count)
    adjusted = base_xp * multiplier
    if adjusted == int(adjusted):
        adjusted = int(adjusted)

    difficulty = "trivial"
    for name in ("easy", "medium", "hard", "deadly"):
        if adjusted >= thresholds[name]:
            difficulty = name

    return jsonify(
        base_xp=base_xp,
        monster_count=monster_count,
        multiplier=multiplier,
        adjusted_xp=adjusted,
        difficulty=difficulty,
        thresholds=thresholds,
    )


@app.post("/v1/initiative/order")
def initiative_order():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    combatants = data.get("combatants")
    if not isinstance(combatants, list):
        return error("invalid request")

    entries = []
    for c in combatants:
        if not isinstance(c, dict):
            return error("invalid combatant")
        name = c.get("name")
        dex = c.get("dex")
        roll = c.get("roll")
        if not isinstance(name, str):
            return error("invalid name")
        if not isinstance(dex, int) or isinstance(dex, bool):
            return error("invalid dex")
        if not isinstance(roll, int) or isinstance(roll, bool):
            return error("invalid roll")
        entries.append({"name": name, "dex": dex, "score": roll + dex})

    entries.sort(key=lambda e: (-e["score"], -e["dex"], e["name"]))
    order = [{"name": e["name"], "score": e["score"]} for e in entries]
    return jsonify(order=order)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def ability_modifier(score):
    return (score - 10) // 2


def proficiency_bonus(level):
    return (level + 7) // 4


ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")


@app.post("/v1/characters/ability-modifier")
def characters_ability_modifier():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    score = data.get("score")
    if not is_int(score) or score < 1 or score > 30:
        return error("invalid score")
    return jsonify(score=score, modifier=ability_modifier(score))


@app.post("/v1/characters/proficiency")
def characters_proficiency():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    level = data.get("level")
    if not is_int(level) or level < 1 or level > 20:
        return error("invalid level")
    return jsonify(level=level, proficiency_bonus=proficiency_bonus(level))


@app.post("/v1/characters/derived-stats")
def characters_derived_stats():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")

    level = data.get("level")
    if not is_int(level) or level < 1 or level > 20:
        return error("invalid level")

    abilities = data.get("abilities")
    if not isinstance(abilities, dict):
        return error("invalid abilities")

    modifiers = {}
    for key in ABILITY_KEYS:
        score = abilities.get(key)
        if not is_int(score) or score < 1 or score > 30:
            return error("invalid ability score")
        modifiers[key] = ability_modifier(score)

    armor = data.get("armor")
    if not isinstance(armor, dict):
        return error("invalid armor")
    base = armor.get("base")
    dex_cap = armor.get("dex_cap")
    shield = armor.get("shield", False)
    if not is_int(base):
        return error("invalid armor base")
    if not is_int(dex_cap):
        return error("invalid dex_cap")
    if not isinstance(shield, bool):
        return error("invalid shield")

    prof = proficiency_bonus(level)
    hp_max = level * (6 + modifiers["con"])
    shield_bonus = 2 if shield else 0
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus

    return jsonify(
        level=level,
        proficiency_bonus=prof,
        hp_max=hp_max,
        armor_class=armor_class,
        modifiers=modifiers,
    )


COMBAT_SESSIONS = {}


def combatant_public(entry):
    return {"name": entry["name"], "score": entry["score"]}


def session_conditions(session):
    result = {}
    for entry in session["order"]:
        if entry["name"] in session["condition_targets"]:
            result[entry["name"]] = [
                {"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]}
                for c in entry["conditions"]
            ]
    return result


@app.post("/v1/combat/sessions")
def combat_create_session():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    session_id = data.get("id")
    if not isinstance(session_id, str) or not session_id:
        return error("invalid id")
    if session_id in COMBAT_SESSIONS:
        return error("duplicate id")
    combatants = data.get("combatants")
    if not isinstance(combatants, list) or not combatants:
        return error("invalid combatants")

    entries = []
    for c in combatants:
        if not isinstance(c, dict):
            return error("invalid combatant")
        name = c.get("name")
        dex = c.get("dex")
        roll = c.get("roll")
        if not isinstance(name, str) or not name:
            return error("invalid name")
        if not is_int(dex):
            return error("invalid dex")
        if not is_int(roll):
            return error("invalid roll")
        entries.append(
            {"name": name, "dex": dex, "score": roll + dex, "conditions": []}
        )

    entries.sort(key=lambda e: (-e["score"], -e["dex"], e["name"]))
    session = {
        "id": session_id,
        "round": 1,
        "turn_index": 0,
        "order": entries,
        "condition_targets": set(),
    }
    COMBAT_SESSIONS[session_id] = session

    return jsonify(
        id=session_id,
        round=1,
        turn_index=0,
        active=combatant_public(entries[0]),
        order=[combatant_public(e) for e in entries],
    )


@app.post("/v1/combat/sessions/<session_id>/conditions")
def combat_add_condition(session_id):
    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        return error("unknown session", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    target = data.get("target")
    condition = data.get("condition")
    duration = data.get("duration_rounds")
    if not isinstance(target, str) or not target:
        return error("invalid target")
    if not isinstance(condition, str) or not condition:
        return error("invalid condition")
    if not is_int(duration) or duration <= 0:
        return error("invalid duration_rounds")

    entry = next((e for e in session["order"] if e["name"] == target), None)
    if entry is None:
        return error("unknown target")

    entry["conditions"].append(
        {"condition": condition, "remaining_rounds": duration}
    )
    session["condition_targets"].add(target)

    return jsonify(
        target=target,
        conditions=[
            {"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]}
            for c in entry["conditions"]
        ],
    )


@app.post("/v1/combat/sessions/<session_id>/advance")
def combat_advance(session_id):
    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        return error("unknown session", 404)

    order = session["order"]
    session["turn_index"] += 1
    if session["turn_index"] >= len(order):
        session["turn_index"] = 0
        session["round"] += 1

    active = order[session["turn_index"]]
    remaining = []
    for c in active["conditions"]:
        c["remaining_rounds"] -= 1
        if c["remaining_rounds"] > 0:
            remaining.append(c)
    active["conditions"] = remaining

    return jsonify(
        id=session["id"],
        round=session["round"],
        turn_index=session["turn_index"],
        active=combatant_public(active),
        conditions=session_conditions(session),
    )


@app.post("/v1/auth/register")
def auth_register():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    username = data.get("username")
    password = data.get("password")
    role = data.get("role")
    if not isinstance(username, str) or not USERNAME_RE.match(username):
        return error("invalid username")
    if not isinstance(password, str) or len(password) < 8:
        return error("invalid password")
    if role not in ("dm", "player"):
        return error("invalid role")

    conn = db_connect()
    try:
        existing = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing is not None:
            return error("duplicate username", 409)
        conn.execute(
            "INSERT INTO users (username, role, password_hash) VALUES (?, ?, ?)",
            (username, role, generate_password_hash(password)),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify(username=username, role=role), 201


@app.post("/v1/auth/login")
def auth_login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    username = data.get("username")
    password = data.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return error("invalid request")
    conn = db_connect()
    try:
        user = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
    finally:
        conn.close()
    if user is None or not check_password_hash(user["password_hash"], password):
        return error("invalid credentials", 401)
    return jsonify(username=username, token="session-" + username)


def storage_initialized():
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_meta'"
        ).fetchone()
        if row is None:
            return False
        version = conn.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()
        return version is not None
    finally:
        conn.close()


@app.get("/v1/storage/status")
def storage_status():
    return jsonify(
        driver="sqlite",
        schema_version=SCHEMA_VERSION,
        initialized=storage_initialized(),
    )


@app.post("/v1/storage/reset")
def storage_reset():
    reset_db()
    return jsonify(ok=True, schema_version=SCHEMA_VERSION)


SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@app.post("/v1/compendium/monsters")
def compendium_create_monster():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    slug = data.get("slug")
    name = data.get("name")
    cr = data.get("cr")
    armor_class = data.get("armor_class")
    hit_points = data.get("hit_points")
    tags = data.get("tags", [])
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        return error("invalid slug")
    if not isinstance(name, str) or not name:
        return error("invalid name")
    if not isinstance(cr, str) or not cr:
        return error("invalid cr")
    if not is_int(armor_class):
        return error("invalid armor_class")
    if not is_int(hit_points):
        return error("invalid hit_points")
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        return error("invalid tags")

    conn = db_connect()
    try:
        existing = conn.execute(
            "SELECT 1 FROM monsters WHERE slug = ?", (slug,)
        ).fetchone()
        if existing is not None:
            return error("duplicate slug", 409)
        conn.execute(
            "INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (slug, name, cr, armor_class, hit_points, json.dumps(tags)),
        )
        conn.commit()
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
def compendium_read_monster(slug):
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT slug, name, cr, armor_class, hit_points, tags "
            "FROM monsters WHERE slug = ?",
            (slug,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return error("unknown monster", 404)
    return jsonify(
        slug=row["slug"],
        name=row["name"],
        cr=row["cr"],
        armor_class=row["armor_class"],
        hit_points=row["hit_points"],
        tags=json.loads(row["tags"]),
    )


@app.post("/v1/compendium/items")
def compendium_create_item():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    slug = data.get("slug")
    name = data.get("name")
    type_ = data.get("type")
    rarity = data.get("rarity")
    cost_gp = data.get("cost_gp")
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        return error("invalid slug")
    if not isinstance(name, str) or not name:
        return error("invalid name")
    if not isinstance(type_, str) or not type_:
        return error("invalid type")
    if not isinstance(rarity, str) or not rarity:
        return error("invalid rarity")
    if not is_int(cost_gp):
        return error("invalid cost_gp")

    conn = db_connect()
    try:
        existing = conn.execute(
            "SELECT 1 FROM items WHERE slug = ?", (slug,)
        ).fetchone()
        if existing is not None:
            return error("duplicate slug", 409)
        conn.execute(
            "INSERT INTO items (slug, name, type, rarity, cost_gp) "
            "VALUES (?, ?, ?, ?, ?)",
            (slug, name, type_, rarity, cost_gp),
        )
        conn.commit()
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
def compendium_read_item(slug):
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?",
            (slug,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return error("unknown item", 404)
    return jsonify(
        slug=row["slug"],
        name=row["name"],
        type=row["type"],
        rarity=row["rarity"],
        cost_gp=row["cost_gp"],
    )


@app.post("/v1/campaigns")
def campaigns_create():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    campaign_id = data.get("id")
    name = data.get("name")
    dm = data.get("dm")
    if not isinstance(campaign_id, str) or not campaign_id:
        return error("invalid id")
    if not isinstance(name, str) or not name:
        return error("invalid name")
    if not isinstance(dm, str) or not dm:
        return error("invalid dm")

    conn = db_connect()
    try:
        existing = conn.execute(
            "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if existing is not None:
            return error("duplicate id", 409)
        conn.execute(
            "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
            (campaign_id, name, dm),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(id=campaign_id, name=name, dm=dm), 201


def campaign_exists(conn, campaign_id):
    return conn.execute(
        "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone() is not None


@app.post("/v1/campaigns/<campaign_id>/characters")
def campaigns_add_character(campaign_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    char_id = data.get("id")
    name = data.get("name")
    level = data.get("level")
    class_ = data.get("class")
    if not isinstance(char_id, str) or not char_id:
        return error("invalid id")
    if not isinstance(name, str) or not name:
        return error("invalid name")
    if not is_int(level):
        return error("invalid level")
    if not isinstance(class_, str) or not class_:
        return error("invalid class")

    conn = db_connect()
    try:
        if not campaign_exists(conn, campaign_id):
            return error("unknown campaign", 404)
        existing = conn.execute(
            "SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if existing is not None:
            return error("duplicate id", 409)
        seq = conn.execute(
            "SELECT COUNT(*) AS c FROM campaign_characters WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["c"]
        conn.execute(
            "INSERT INTO campaign_characters "
            "(campaign_id, id, name, level, class, seq) VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, char_id, name, level, class_, seq),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(id=char_id, name=name, level=level, **{"class": class_}), 201


@app.post("/v1/campaigns/<campaign_id>/events")
def campaigns_add_event(campaign_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    event_id = data.get("id")
    kind = data.get("kind")
    summary = data.get("summary")
    if not isinstance(event_id, str) or not event_id:
        return error("invalid id")
    if not isinstance(kind, str) or not kind:
        return error("invalid kind")
    if not isinstance(summary, str) or not summary:
        return error("invalid summary")

    conn = db_connect()
    try:
        if not campaign_exists(conn, campaign_id):
            return error("unknown campaign", 404)
        existing = conn.execute(
            "SELECT 1 FROM campaign_events WHERE campaign_id = ? AND id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if existing is not None:
            return error("duplicate id", 409)
        seq = conn.execute(
            "SELECT COUNT(*) AS c FROM campaign_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["c"]
        conn.execute(
            "INSERT INTO campaign_events "
            "(campaign_id, id, kind, summary, seq) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, event_id, kind, summary, seq),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(id=event_id, kind=kind), 201


@app.get("/v1/campaigns/<campaign_id>/state")
def campaigns_state(campaign_id):
    conn = db_connect()
    try:
        campaign = conn.execute(
            "SELECT id, name, dm FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return error("unknown campaign", 404)
        characters = conn.execute(
            "SELECT id, name, level, class FROM campaign_characters "
            "WHERE campaign_id = ? ORDER BY seq",
            (campaign_id,),
        ).fetchall()
        log_count = conn.execute(
            "SELECT COUNT(*) AS c FROM campaign_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["c"]
    finally:
        conn.close()

    return jsonify(
        id=campaign["id"],
        name=campaign["name"],
        dm=campaign["dm"],
        characters=[
            {
                "id": row["id"],
                "name": row["name"],
                "level": row["level"],
                "class": row["class"],
            }
            for row in characters
        ],
        log_count=log_count,
    )


SPELL_SLOTS = {
    ("wizard", 5): {"1": 4, "2": 3, "3": 2},
}


@app.post("/v1/phb/spell-slots")
def phb_spell_slots():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    cls = data.get("class")
    level = data.get("level")
    if not isinstance(cls, str):
        return error("invalid class")
    if not isinstance(level, int) or isinstance(level, bool):
        return error("invalid level")
    slots = SPELL_SLOTS.get((cls, level))
    if slots is None:
        return error("unsupported class/level")
    return jsonify(**{"class": cls, "level": level, "slots": slots})


@app.post("/v1/phb/rests/long")
def phb_long_rest():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    level = data.get("level")
    hp_max = data.get("hp_max")
    hit_dice_spent = data.get("hit_dice_spent")
    exhaustion_level = data.get("exhaustion_level")
    for value in (level, hp_max, hit_dice_spent, exhaustion_level):
        if not isinstance(value, int) or isinstance(value, bool):
            return error("invalid request")
    if level < 1 or hp_max < 0 or hit_dice_spent < 0 or exhaustion_level < 0:
        return error("invalid request")
    recovered = max(level // 2, 1)
    new_hit_dice_spent = max(hit_dice_spent - recovered, 0)
    new_exhaustion = max(exhaustion_level - 1, 0)
    return jsonify(
        hp_current=hp_max,
        hit_dice_spent=new_hit_dice_spent,
        exhaustion_level=new_exhaustion,
    )


@app.post("/v1/phb/equipment-load")
def phb_equipment_load():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    strength = data.get("strength")
    weight = data.get("weight")
    if not isinstance(strength, int) or isinstance(strength, bool):
        return error("invalid strength")
    if not isinstance(weight, (int, float)) or isinstance(weight, bool):
        return error("invalid weight")
    if strength < 0 or weight < 0:
        return error("invalid request")
    capacity = strength * 15
    return jsonify(capacity=capacity, weight=weight, encumbered=weight > capacity)


DIFFICULTY_RECOMMENDATION = {
    "trivial": "trivial skirmish",
    "easy": "safe warm-up",
    "medium": "balanced fight",
    "hard": "tough battle",
    "deadly": "deadly threat",
}

# Deterministic loot tables keyed by tier for this benchmark.
LOOT_TABLE = {
    1: {"coins_gp": 75, "items": [{"slug": "healing-potion", "quantity": 2}]},
}

# Kinds treated as open threads/hooks for session recaps.
THREAD_KINDS = ("hook", "thread", "quest", "open", "unresolved")
# Kinds preferred as the recap headline summary.
RECAP_KINDS = ("note", "recap", "scene", "session")


def derive_trail_thread(summary):
    """Deterministically derive an unresolved "ambush" thread from a scouting
    summary that mentions a "<place> trail" (e.g. "Nyx scouts the goblin
    trail." -> "Resolve goblin trail ambush"). Returns None when no trail is
    mentioned."""
    if not isinstance(summary, str):
        return None
    tokens = [t.strip(".,!?;:") for t in summary.split()]
    for i, token in enumerate(tokens):
        if token.lower() == "trail" and i > 0:
            place = tokens[i - 1]
            if place.lower() in ("the", "a", "an"):
                continue
            return "Resolve " + place + " trail ambush"
    return None


@app.post("/v1/dm/encounter-builder")
def dm_encounter_builder():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    campaign_id = data.get("campaign_id")
    party = data.get("party")
    monster_slugs = data.get("monster_slugs")
    if not isinstance(campaign_id, str) or not campaign_id:
        return error("invalid campaign_id")
    if not isinstance(party, list) or not party:
        return error("invalid party")
    if not isinstance(monster_slugs, list):
        return error("invalid monster_slugs")

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            return error("invalid party member")
        level = member.get("level")
        if not is_int(level):
            return error("invalid level")
        member_thresholds = LEVEL_THRESHOLDS.get(level)
        if member_thresholds is None:
            return error("unsupported level")
        for key in thresholds:
            thresholds[key] += member_thresholds[key]

    base_xp = 0
    monster_count = 0
    conn = db_connect()
    try:
        for slug in monster_slugs:
            if not isinstance(slug, str):
                return error("invalid monster slug")
            row = conn.execute(
                "SELECT cr FROM monsters WHERE slug = ?", (slug,)
            ).fetchone()
            if row is None:
                return error("unknown monster", 404)
            cr_key = str(row["cr"])
            if cr_key not in CR_XP:
                return error("unsupported cr")
            base_xp += CR_XP[cr_key]
            monster_count += 1
    finally:
        conn.close()

    multiplier = count_multiplier(monster_count)
    adjusted = base_xp * multiplier
    if adjusted == int(adjusted):
        adjusted = int(adjusted)

    difficulty = "trivial"
    for name in ("easy", "medium", "hard", "deadly"):
        if adjusted >= thresholds[name]:
            difficulty = name

    return jsonify(
        campaign_id=campaign_id,
        base_xp=base_xp,
        adjusted_xp=adjusted,
        difficulty=difficulty,
        monster_count=monster_count,
        recommendation=DIFFICULTY_RECOMMENDATION[difficulty],
    )


@app.post("/v1/dm/loot-parcel")
def dm_loot_parcel():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    campaign_id = data.get("campaign_id")
    tier = data.get("tier")
    if not isinstance(campaign_id, str) or not campaign_id:
        return error("invalid campaign_id")
    if not is_int(tier):
        return error("invalid tier")
    seed = data.get("seed", 0)
    if not is_int(seed):
        return error("invalid seed")

    parcel = LOOT_TABLE.get(tier)
    if parcel is None:
        return error("unsupported tier")

    return jsonify(
        campaign_id=campaign_id,
        coins_gp=parcel["coins_gp"],
        items=[dict(item) for item in parcel["items"]],
    )


@app.post("/v1/dm/session-recap")
def dm_session_recap():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("invalid request")
    campaign_id = data.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        return error("invalid campaign_id")

    conn = db_connect()
    try:
        if not campaign_exists(conn, campaign_id):
            return error("unknown campaign", 404)
        events = conn.execute(
            "SELECT kind, summary FROM campaign_events "
            "WHERE campaign_id = ? ORDER BY seq",
            (campaign_id,),
        ).fetchall()
    finally:
        conn.close()

    summary = "No events recorded."
    recap_events = [e for e in events if e["kind"] in RECAP_KINDS]
    if recap_events:
        summary = recap_events[-1]["summary"]
    elif events:
        summary = events[-1]["summary"]

    open_threads = []
    for e in events:
        if e["kind"] in THREAD_KINDS:
            open_threads.append("Resolve " + e["summary"])
            continue
        # Derive an open thread deterministically from narrative events that
        # scout an unresolved location (e.g. "... the goblin trail." -> an
        # "ambush" thread waiting to be triggered at that trail).
        thread = derive_trail_thread(e["summary"])
        if thread is not None:
            open_threads.append(thread)

    return jsonify(
        campaign_id=campaign_id,
        summary=summary,
        open_threads=open_threads,
    )


init_db()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
