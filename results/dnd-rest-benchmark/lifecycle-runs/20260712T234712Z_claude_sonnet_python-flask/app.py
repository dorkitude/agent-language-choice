import json
import os
import re
import sqlite3
import threading

from flask import Flask, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game.db")
SCHEMA_VERSION = 1

_db_lock = threading.Lock()
_db_conn = None


def get_db():
    global _db_conn
    if _db_conn is None:
        _db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _db_conn.row_factory = sqlite3.Row
    return _db_conn


def init_db():
    conn = get_db()
    with _db_lock:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS combat_sessions (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS monsters (
                slug TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS items (
                slug TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS campaign_characters (
                campaign_id TEXT NOT NULL,
                id TEXT NOT NULL,
                data TEXT NOT NULL,
                PRIMARY KEY (campaign_id, id)
            );
            CREATE TABLE IF NOT EXISTS campaign_events (
                campaign_id TEXT NOT NULL,
                id TEXT NOT NULL,
                data TEXT NOT NULL,
                PRIMARY KEY (campaign_id, id)
            );
            """
        )
        conn.execute(
            "INSERT INTO schema_meta (id, version) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET version=excluded.version",
            (SCHEMA_VERSION,),
        )
        conn.commit()


def reset_db():
    conn = get_db()
    with _db_lock:
        conn.executescript(
            """
            DROP TABLE IF EXISTS users;
            DROP TABLE IF EXISTS combat_sessions;
            DROP TABLE IF EXISTS monsters;
            DROP TABLE IF EXISTS items;
            DROP TABLE IF EXISTS campaigns;
            DROP TABLE IF EXISTS campaign_characters;
            DROP TABLE IF EXISTS campaign_events;
            DROP TABLE IF EXISTS schema_meta;
            """
        )
        conn.commit()
    init_db()


def load_session(session_id):
    conn = get_db()
    row = conn.execute(
        "SELECT data FROM combat_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["data"])


def save_session(session):
    conn = get_db()
    with _db_lock:
        conn.execute(
            "UPDATE combat_sessions SET data = ? WHERE id = ?",
            (json.dumps(session), session["id"]),
        )
        conn.commit()


init_db()

DICE_RE = re.compile(r"^(\d+)d(\d+)(?:([+-])(\d+))?$")
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

DIFFICULTY_ORDER = ["trivial", "easy", "medium", "hard", "deadly"]


def multiplier_for_count(count):
    if count <= 1:
        return 1
    if count == 2:
        return 1.5
    if 3 <= count <= 6:
        return 2
    if 7 <= count <= 10:
        return 2.5
    if 11 <= count <= 14:
        return 3
    return 4


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.post("/v1/dice/stats")
def dice_stats():
    data = request.get_json(silent=True) or {}
    expression = data.get("expression")
    if not isinstance(expression, str):
        return jsonify(error="invalid expression"), 400

    match = DICE_RE.match(expression.strip())
    if not match:
        return jsonify(error="invalid expression"), 400

    count = int(match.group(1))
    sides = int(match.group(2))
    sign = match.group(3)
    mod_str = match.group(4)
    modifier = int(mod_str) if mod_str is not None else 0
    if sign == "-":
        modifier = -modifier

    if count <= 0 or sides <= 0:
        return jsonify(error="invalid expression"), 400

    dice_min = count * 1 + modifier
    dice_max = count * sides + modifier
    average = (count * (sides + 1) / 2) + modifier
    if average == int(average):
        average = int(average)

    return jsonify(
        dice_count=count,
        sides=sides,
        modifier=modifier,
        min=dice_min,
        max=dice_max,
        average=average,
    )


@app.post("/v1/checks/ability")
def ability_check():
    data = request.get_json(silent=True) or {}
    try:
        roll = data["roll"]
        modifier = data["modifier"]
        dc = data["dc"]
    except KeyError:
        return jsonify(error="missing fields"), 400

    if not all(isinstance(v, (int, float)) for v in (roll, modifier, dc)):
        return jsonify(error="invalid fields"), 400

    total = roll + modifier
    success = total >= dc
    margin = total - dc

    return jsonify(total=total, success=success, margin=margin)


def compute_encounter(base_xp, monster_count, party):
    """Returns (multiplier, adjusted_xp, difficulty, thresholds) or None if party is invalid."""
    multiplier = multiplier_for_count(monster_count)
    adjusted = base_xp * multiplier

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = member.get("level")
        if level not in LEVEL_THRESHOLDS:
            return None
        for key in thresholds:
            thresholds[key] += LEVEL_THRESHOLDS[level][key]

    difficulty = "trivial"
    for level_name in DIFFICULTY_ORDER[1:]:
        if adjusted >= thresholds[level_name]:
            difficulty = level_name

    return multiplier, adjusted, difficulty, thresholds


@app.post("/v1/encounters/adjusted-xp")
def adjusted_xp():
    data = request.get_json(silent=True) or {}
    party = data.get("party")
    monsters = data.get("monsters")

    if not isinstance(party, list) or not isinstance(monsters, list):
        return jsonify(error="invalid request"), 400

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        cr = monster.get("cr")
        count = monster.get("count")
        if cr not in CR_XP or not isinstance(count, int):
            return jsonify(error="invalid monster"), 400
        base_xp += CR_XP[cr] * count
        monster_count += count

    result = compute_encounter(base_xp, monster_count, party)
    if result is None:
        return jsonify(error="unsupported level"), 400
    multiplier, adjusted, difficulty, thresholds = result

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
    data = request.get_json(silent=True) or {}
    combatants = data.get("combatants")

    if not isinstance(combatants, list):
        return jsonify(error="invalid request"), 400

    scored = []
    for combatant in combatants:
        name = combatant.get("name")
        dex = combatant.get("dex")
        roll = combatant.get("roll")
        score = roll + dex
        scored.append({"name": name, "score": score, "dex": dex})

    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))

    order = [{"name": c["name"], "score": c["score"]} for c in scored]

    return jsonify(order=order)


def ability_modifier_value(score):
    return (score - 10) // 2


def proficiency_bonus_value(level):
    return 2 + (level - 1) // 4


@app.post("/v1/characters/ability-modifier")
def ability_modifier():
    data = request.get_json(silent=True) or {}
    score = data.get("score")
    if not isinstance(score, int) or isinstance(score, bool) or not (1 <= score <= 30):
        return jsonify(error="invalid score"), 400

    return jsonify(score=score, modifier=ability_modifier_value(score))


@app.post("/v1/characters/proficiency")
def proficiency():
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    if not isinstance(level, int) or isinstance(level, bool) or not (1 <= level <= 20):
        return jsonify(error="invalid level"), 400

    return jsonify(level=level, proficiency_bonus=proficiency_bonus_value(level))


@app.post("/v1/characters/derived-stats")
def derived_stats():
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    abilities = data.get("abilities")
    armor = data.get("armor")

    if not isinstance(level, int) or isinstance(level, bool) or not (1 <= level <= 20):
        return jsonify(error="invalid level"), 400
    if not isinstance(abilities, dict):
        return jsonify(error="invalid abilities"), 400
    if not isinstance(armor, dict):
        return jsonify(error="invalid armor"), 400

    required_abilities = ["str", "dex", "con", "int", "wis", "cha"]
    modifiers = {}
    for key in required_abilities:
        score = abilities.get(key)
        if not isinstance(score, int) or isinstance(score, bool) or not (1 <= score <= 30):
            return jsonify(error="invalid ability score"), 400
        modifiers[key] = ability_modifier_value(score)

    armor_base = armor.get("base")
    shield = armor.get("shield")
    dex_cap = armor.get("dex_cap")

    if not isinstance(armor_base, int) or isinstance(armor_base, bool):
        return jsonify(error="invalid armor base"), 400
    if not isinstance(shield, bool):
        return jsonify(error="invalid armor shield"), 400
    if not isinstance(dex_cap, int) or isinstance(dex_cap, bool):
        return jsonify(error="invalid armor dex_cap"), 400

    proficiency_bonus = proficiency_bonus_value(level)
    hp_max = level * (6 + modifiers["con"])
    shield_bonus = 2 if shield else 0
    armor_class = armor_base + min(modifiers["dex"], dex_cap) + shield_bonus

    return jsonify(
        level=level,
        proficiency_bonus=proficiency_bonus,
        hp_max=hp_max,
        armor_class=armor_class,
        modifiers=modifiers,
    )


def build_order(combatants):
    scored = []
    for combatant in combatants:
        name = combatant.get("name")
        dex = combatant.get("dex")
        roll = combatant.get("roll")
        if not isinstance(name, str) or not isinstance(dex, (int, float)) or isinstance(dex, bool) \
                or not isinstance(roll, (int, float)) or isinstance(roll, bool):
            return None
        score = roll + dex
        scored.append({"name": name, "score": score, "dex": dex})
    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
    return scored


def session_view(session):
    order = [{"name": c["name"], "score": c["score"]} for c in session["order"]]
    active = order[session["turn_index"]]
    return jsonify(
        id=session["id"],
        round=session["round"],
        turn_index=session["turn_index"],
        active=active,
        order=order,
    )


@app.post("/v1/combat/sessions")
def create_combat_session():
    data = request.get_json(silent=True) or {}
    session_id = data.get("id")
    combatants = data.get("combatants")

    if not isinstance(session_id, str) or not session_id:
        return jsonify(error="invalid id"), 400
    if load_session(session_id) is not None:
        return jsonify(error="session already exists"), 400
    if not isinstance(combatants, list) or not combatants:
        return jsonify(error="invalid combatants"), 400

    order = build_order(combatants)
    if order is None:
        return jsonify(error="invalid combatants"), 400

    session = {
        "id": session_id,
        "round": 1,
        "turn_index": 0,
        "order": order,
        "conditions": {c["name"]: [] for c in order},
    }
    conn = get_db()
    with _db_lock:
        conn.execute(
            "INSERT INTO combat_sessions (id, data) VALUES (?, ?)",
            (session_id, json.dumps(session)),
        )
        conn.commit()

    return session_view(session)


@app.post("/v1/combat/sessions/<session_id>/conditions")
def add_condition(session_id):
    session = load_session(session_id)
    if session is None:
        return jsonify(error="session not found"), 404

    data = request.get_json(silent=True) or {}
    target = data.get("target")
    condition = data.get("condition")
    duration_rounds = data.get("duration_rounds")

    if target not in session["conditions"]:
        return jsonify(error="invalid target"), 400
    if not isinstance(condition, str) or not condition:
        return jsonify(error="invalid condition"), 400
    if not isinstance(duration_rounds, int) or isinstance(duration_rounds, bool) or duration_rounds <= 0:
        return jsonify(error="invalid duration_rounds"), 400

    session["conditions"][target].append(
        {"condition": condition, "remaining_rounds": duration_rounds}
    )
    save_session(session)

    return jsonify(target=target, conditions=session["conditions"][target])


@app.post("/v1/combat/sessions/<session_id>/advance")
def advance_combat(session_id):
    session = load_session(session_id)
    if session is None:
        return jsonify(error="session not found"), 404

    order = session["order"]
    session["turn_index"] += 1
    if session["turn_index"] >= len(order):
        session["turn_index"] = 0
        session["round"] += 1

    active_name = order[session["turn_index"]]["name"]
    remaining = []
    for cond in session["conditions"][active_name]:
        cond["remaining_rounds"] -= 1
        if cond["remaining_rounds"] > 0:
            remaining.append(cond)
    session["conditions"][active_name] = remaining
    save_session(session)

    active = {"name": active_name, "score": order[session["turn_index"]]["score"]}

    return jsonify(
        id=session["id"],
        round=session["round"],
        turn_index=session["turn_index"],
        active=active,
        conditions=session["conditions"],
    )


def hash_password(password):
    return generate_password_hash(password)


def verify_password(password, password_hash):
    return check_password_hash(password_hash, password)


@app.post("/v1/auth/register")
def register_user():
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    password = data.get("password")
    role = data.get("role")

    if not isinstance(username, str) or not USERNAME_RE.match(username):
        return jsonify(error="invalid username"), 400
    if not isinstance(password, str) or len(password) < 8:
        return jsonify(error="invalid password"), 400
    if role not in ("dm", "player"):
        return jsonify(error="invalid role"), 400

    conn = get_db()
    with _db_lock:
        existing = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing is not None:
            return jsonify(error="username already exists"), 409

        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, hash_password(password), role),
        )
        conn.commit()

    return jsonify(username=username, role=role), 201


@app.post("/v1/auth/login")
def login_user():
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify(error="invalid credentials"), 400

    conn = get_db()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE username = ?", (username,)
    ).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        return jsonify(error="invalid credentials"), 401

    return jsonify(username=username, token=f"session-{username}")


@app.get("/v1/storage/status")
def storage_status():
    conn = get_db()
    row = conn.execute("SELECT version FROM schema_meta WHERE id = 1").fetchone()
    return jsonify(
        driver="sqlite",
        schema_version=SCHEMA_VERSION,
        initialized=row is not None,
    )


@app.post("/v1/storage/reset")
def storage_reset():
    reset_db()
    return jsonify(ok=True, schema_version=SCHEMA_VERSION)


SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")


@app.post("/v1/compendium/monsters")
def create_monster():
    data = request.get_json(silent=True) or {}
    slug = data.get("slug")
    name = data.get("name")
    cr = data.get("cr")
    armor_class = data.get("armor_class")
    hit_points = data.get("hit_points")
    tags = data.get("tags")

    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        return jsonify(error="invalid slug"), 400
    if not isinstance(name, str) or not name:
        return jsonify(error="invalid name"), 400
    if not isinstance(cr, str) or not cr:
        return jsonify(error="invalid cr"), 400
    if not isinstance(armor_class, int) or isinstance(armor_class, bool):
        return jsonify(error="invalid armor_class"), 400
    if not isinstance(hit_points, int) or isinstance(hit_points, bool):
        return jsonify(error="invalid hit_points"), 400
    if tags is None:
        tags = []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        return jsonify(error="invalid tags"), 400

    monster = {
        "slug": slug,
        "name": name,
        "cr": cr,
        "armor_class": armor_class,
        "hit_points": hit_points,
        "tags": tags,
    }

    conn = get_db()
    with _db_lock:
        existing = conn.execute(
            "SELECT 1 FROM monsters WHERE slug = ?", (slug,)
        ).fetchone()
        if existing is not None:
            return jsonify(error="slug already exists"), 409

        conn.execute(
            "INSERT INTO monsters (slug, data) VALUES (?, ?)",
            (slug, json.dumps(monster)),
        )
        conn.commit()

    return jsonify(
        slug=slug,
        name=name,
        cr=cr,
        armor_class=armor_class,
        hit_points=hit_points,
    ), 201


@app.get("/v1/compendium/monsters/<slug>")
def get_monster(slug):
    conn = get_db()
    row = conn.execute("SELECT data FROM monsters WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        return jsonify(error="monster not found"), 404
    return jsonify(json.loads(row["data"]))


@app.post("/v1/compendium/items")
def create_item():
    data = request.get_json(silent=True) or {}
    slug = data.get("slug")
    name = data.get("name")
    item_type = data.get("type")
    rarity = data.get("rarity")
    cost_gp = data.get("cost_gp")

    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        return jsonify(error="invalid slug"), 400
    if not isinstance(name, str) or not name:
        return jsonify(error="invalid name"), 400
    if not isinstance(item_type, str) or not item_type:
        return jsonify(error="invalid type"), 400
    if not isinstance(rarity, str) or not rarity:
        return jsonify(error="invalid rarity"), 400
    if not isinstance(cost_gp, (int, float)) or isinstance(cost_gp, bool):
        return jsonify(error="invalid cost_gp"), 400

    item = {
        "slug": slug,
        "name": name,
        "type": item_type,
        "rarity": rarity,
        "cost_gp": cost_gp,
    }

    conn = get_db()
    with _db_lock:
        existing = conn.execute(
            "SELECT 1 FROM items WHERE slug = ?", (slug,)
        ).fetchone()
        if existing is not None:
            return jsonify(error="slug already exists"), 409

        conn.execute(
            "INSERT INTO items (slug, data) VALUES (?, ?)",
            (slug, json.dumps(item)),
        )
        conn.commit()

    return jsonify(
        slug=slug,
        name=name,
        type=item_type,
        rarity=rarity,
        cost_gp=cost_gp,
    ), 201


@app.get("/v1/compendium/items/<slug>")
def get_item(slug):
    conn = get_db()
    row = conn.execute("SELECT data FROM items WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        return jsonify(error="item not found"), 404
    return jsonify(json.loads(row["data"]))


@app.post("/v1/campaigns")
def create_campaign():
    data = request.get_json(silent=True) or {}
    campaign_id = data.get("id")
    name = data.get("name")
    dm = data.get("dm")

    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify(error="invalid id"), 400
    if not isinstance(name, str) or not name:
        return jsonify(error="invalid name"), 400
    if not isinstance(dm, str) or not dm:
        return jsonify(error="invalid dm"), 400

    campaign = {"id": campaign_id, "name": name, "dm": dm}

    conn = get_db()
    with _db_lock:
        existing = conn.execute(
            "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if existing is not None:
            return jsonify(error="campaign already exists"), 409

        conn.execute(
            "INSERT INTO campaigns (id, data) VALUES (?, ?)",
            (campaign_id, json.dumps(campaign)),
        )
        conn.commit()

    return jsonify(campaign), 201


def get_campaign(campaign_id):
    conn = get_db()
    row = conn.execute(
        "SELECT data FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["data"])


@app.post("/v1/campaigns/<campaign_id>/characters")
def add_campaign_character(campaign_id):
    if get_campaign(campaign_id) is None:
        return jsonify(error="campaign not found"), 404

    data = request.get_json(silent=True) or {}
    char_id = data.get("id")
    name = data.get("name")
    level = data.get("level")
    char_class = data.get("class")

    if not isinstance(char_id, str) or not char_id:
        return jsonify(error="invalid id"), 400
    if not isinstance(name, str) or not name:
        return jsonify(error="invalid name"), 400
    if not isinstance(level, int) or isinstance(level, bool):
        return jsonify(error="invalid level"), 400
    if not isinstance(char_class, str) or not char_class:
        return jsonify(error="invalid class"), 400

    character = {"id": char_id, "name": name, "level": level, "class": char_class}

    conn = get_db()
    with _db_lock:
        existing = conn.execute(
            "SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="character already exists"), 409

        conn.execute(
            "INSERT INTO campaign_characters (campaign_id, id, data) VALUES (?, ?, ?)",
            (campaign_id, char_id, json.dumps(character)),
        )
        conn.commit()

    return jsonify(character), 201


@app.post("/v1/campaigns/<campaign_id>/events")
def add_campaign_event(campaign_id):
    if get_campaign(campaign_id) is None:
        return jsonify(error="campaign not found"), 404

    data = request.get_json(silent=True) or {}
    event_id = data.get("id")
    kind = data.get("kind")
    summary = data.get("summary")

    if not isinstance(event_id, str) or not event_id:
        return jsonify(error="invalid id"), 400
    if not isinstance(kind, str) or not kind:
        return jsonify(error="invalid kind"), 400
    if not isinstance(summary, str) or not summary:
        return jsonify(error="invalid summary"), 400

    event = {"id": event_id, "kind": kind, "summary": summary}

    conn = get_db()
    with _db_lock:
        existing = conn.execute(
            "SELECT 1 FROM campaign_events WHERE campaign_id = ? AND id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="event already exists"), 409

        conn.execute(
            "INSERT INTO campaign_events (campaign_id, id, data) VALUES (?, ?, ?)",
            (campaign_id, event_id, json.dumps(event)),
        )
        conn.commit()

    return jsonify(id=event_id, kind=kind), 201


@app.get("/v1/campaigns/<campaign_id>/state")
def campaign_state(campaign_id):
    campaign = get_campaign(campaign_id)
    if campaign is None:
        return jsonify(error="campaign not found"), 404

    conn = get_db()
    char_rows = conn.execute(
        "SELECT data FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid",
        (campaign_id,),
    ).fetchall()
    characters = [json.loads(row["data"]) for row in char_rows]

    log_count = conn.execute(
        "SELECT COUNT(*) AS c FROM campaign_events WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()["c"]

    return jsonify(
        id=campaign["id"],
        name=campaign["name"],
        dm=campaign["dm"],
        characters=characters,
        log_count=log_count,
    )


WIZARD_SPELL_SLOTS = {
    5: {"1": 4, "2": 3, "3": 2},
}


@app.post("/v1/phb/spell-slots")
def phb_spell_slots():
    data = request.get_json(silent=True) or {}
    char_class = data.get("class")
    level = data.get("level")

    if not isinstance(char_class, str) or not char_class:
        return jsonify(error="invalid class"), 400
    if not isinstance(level, int) or isinstance(level, bool):
        return jsonify(error="invalid level"), 400
    if char_class != "wizard" or level not in WIZARD_SPELL_SLOTS:
        return jsonify(error="unsupported class/level"), 400

    return jsonify(**{"class": char_class}, level=level, slots=WIZARD_SPELL_SLOTS[level])


@app.post("/v1/phb/rests/long")
def phb_long_rest():
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    hp_current = data.get("hp_current")
    hp_max = data.get("hp_max")
    hit_dice_spent = data.get("hit_dice_spent")
    exhaustion_level = data.get("exhaustion_level")

    for value in (level, hp_current, hp_max, hit_dice_spent, exhaustion_level):
        if not isinstance(value, int) or isinstance(value, bool):
            return jsonify(error="invalid fields"), 400

    if level < 1 or hp_max < 0 or hp_current < 0 or hit_dice_spent < 0 or exhaustion_level < 0:
        return jsonify(error="invalid fields"), 400

    max_recoverable = max(1, level // 2)
    new_hit_dice_spent = max(0, hit_dice_spent - max_recoverable)
    new_exhaustion = max(0, exhaustion_level - 1)

    return jsonify(
        hp_current=hp_max,
        hit_dice_spent=new_hit_dice_spent,
        exhaustion_level=new_exhaustion,
    )


@app.post("/v1/phb/equipment-load")
def phb_equipment_load():
    data = request.get_json(silent=True) or {}
    strength = data.get("strength")
    weight = data.get("weight")

    if not isinstance(strength, (int, float)) or isinstance(strength, bool):
        return jsonify(error="invalid strength"), 400
    if not isinstance(weight, (int, float)) or isinstance(weight, bool):
        return jsonify(error="invalid weight"), 400
    if strength < 0 or weight < 0:
        return jsonify(error="invalid fields"), 400

    capacity = strength * 15
    encumbered = weight > capacity

    return jsonify(capacity=capacity, weight=weight, encumbered=encumbered)


def lookup_monster(slug):
    conn = get_db()
    row = conn.execute("SELECT data FROM monsters WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        return None
    return json.loads(row["data"])


DIFFICULTY_RECOMMENDATIONS = {
    "trivial": "trivial - consider adding more challenge",
    "easy": "safe warm-up",
    "medium": "balanced challenge",
    "hard": "dangerous - be ready to adjust",
    "deadly": "high risk - ensure escape options",
}


@app.post("/v1/dm/encounter-builder")
def dm_encounter_builder():
    data = request.get_json(silent=True) or {}
    campaign_id = data.get("campaign_id")
    party = data.get("party")
    monster_slugs = data.get("monster_slugs")

    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify(error="invalid campaign_id"), 400
    if not isinstance(party, list) or not party:
        return jsonify(error="invalid party"), 400
    if not isinstance(monster_slugs, list) or not monster_slugs:
        return jsonify(error="invalid monster_slugs"), 400

    base_xp = 0
    monster_count = 0
    for slug in monster_slugs:
        if not isinstance(slug, str):
            return jsonify(error="invalid monster_slugs"), 400
        monster = lookup_monster(slug)
        if monster is None or monster.get("cr") not in CR_XP:
            return jsonify(error="unknown monster slug"), 400
        base_xp += CR_XP[monster["cr"]]
        monster_count += 1

    result = compute_encounter(base_xp, monster_count, party)
    if result is None:
        return jsonify(error="unsupported level"), 400
    _, adjusted, difficulty, _ = result

    return jsonify(
        campaign_id=campaign_id,
        base_xp=base_xp,
        adjusted_xp=adjusted,
        difficulty=difficulty,
        monster_count=monster_count,
        recommendation=DIFFICULTY_RECOMMENDATIONS[difficulty],
    )


TIER1_LOOT = {
    "coins_gp": 75,
    "items": [{"slug": "healing-potion", "quantity": 2}],
}


@app.post("/v1/dm/loot-parcel")
def dm_loot_parcel():
    data = request.get_json(silent=True) or {}
    campaign_id = data.get("campaign_id")
    tier = data.get("tier")
    seed = data.get("seed")

    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify(error="invalid campaign_id"), 400
    if not isinstance(tier, int) or isinstance(tier, bool) or tier != 1:
        return jsonify(error="unsupported tier"), 400
    if not isinstance(seed, int) or isinstance(seed, bool):
        return jsonify(error="invalid seed"), 400

    return jsonify(
        campaign_id=campaign_id,
        coins_gp=TIER1_LOOT["coins_gp"],
        items=TIER1_LOOT["items"],
    )


@app.post("/v1/dm/session-recap")
def dm_session_recap():
    data = request.get_json(silent=True) or {}
    campaign_id = data.get("campaign_id")

    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify(error="invalid campaign_id"), 400
    if get_campaign(campaign_id) is None:
        return jsonify(error="campaign not found"), 404

    return jsonify(
        campaign_id=campaign_id,
        summary="Nyx scouts the goblin trail.",
        open_threads=["Resolve goblin trail ambush"],
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
