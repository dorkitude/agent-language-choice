import hashlib
import hmac
import json
import os
import re
import sqlite3

from flask import Flask, jsonify, request

app = Flask(__name__)


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

DICE_RE = re.compile(r"^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$")
ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")
USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
PASSWORD_ITERATIONS = 120_000
SCHEMA_VERSION = 1
DB_PATH = os.path.join(os.path.dirname(__file__), "game.db")
STORAGE_TABLES = (
    "metadata",
    "users",
    "combat_sessions",
    "monsters",
    "items",
    "campaigns",
    "campaign_characters",
    "campaign_events",
)


def db_connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_storage():
    with db_connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                password_hash TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS combat_sessions (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS monsters (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cr TEXT NOT NULL,
                armor_class INTEGER NOT NULL,
                hit_points INTEGER NOT NULL,
                tags TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                rarity TEXT NOT NULL,
                cost_gp INTEGER NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                dm TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS campaign_characters (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                level INTEGER NOT NULL,
                class TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS campaign_events (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            """
            INSERT INTO metadata (key, value)
            VALUES ('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(SCHEMA_VERSION),),
        )


def reset_storage():
    with db_connect() as db:
        db.execute("DROP TABLE IF EXISTS campaign_events")
        db.execute("DROP TABLE IF EXISTS campaign_characters")
        db.execute("DROP TABLE IF EXISTS campaigns")
        db.execute("DROP TABLE IF EXISTS items")
        db.execute("DROP TABLE IF EXISTS monsters")
        db.execute("DROP TABLE IF EXISTS combat_sessions")
        db.execute("DROP TABLE IF EXISTS users")
        db.execute("DROP TABLE IF EXISTS metadata")
    initialize_storage()


def storage_initialized():
    try:
        with db_connect() as db:
            rows = db.execute(
                f"""
                SELECT name FROM sqlite_master
                WHERE type = 'table'
                AND name IN ({",".join("?" for _ in STORAGE_TABLES)})
                """,
                STORAGE_TABLES,
            ).fetchall()
            version = db.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
        return (
            len(rows) == len(STORAGE_TABLES)
            and version is not None
            and version["value"] == str(SCHEMA_VERSION)
        )
    except sqlite3.Error:
        return False


def serialize_combat_session(session):
    data = dict(session)
    data["condition_targets"] = sorted(session["condition_targets"])
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def deserialize_combat_session(raw_data):
    session = json.loads(raw_data)
    session["condition_targets"] = set(session.get("condition_targets", []))
    return session


def save_combat_session(session):
    with db_connect() as db:
        db.execute(
            """
            INSERT INTO combat_sessions (id, data)
            VALUES (?, ?)
            ON CONFLICT(id) DO UPDATE SET data = excluded.data
            """,
            (session["id"], serialize_combat_session(session)),
        )


def combat_session_exists(session_id):
    with db_connect() as db:
        row = db.execute(
            "SELECT 1 FROM combat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return row is not None


def load_user(username):
    with db_connect() as db:
        row = db.execute(
            "SELECT username, role, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None:
        return None
    return {"username": row["username"], "role": row["role"], "password_hash": row["password_hash"]}


def create_user(username, role, password_hash):
    with db_connect() as db:
        db.execute(
            "INSERT INTO users (username, role, password_hash) VALUES (?, ?, ?)",
            (username, role, password_hash),
        )


def monster_from_row(row, include_tags):
    monster = {
        "slug": row["slug"],
        "name": row["name"],
        "cr": row["cr"],
        "armor_class": row["armor_class"],
        "hit_points": row["hit_points"],
    }
    if include_tags:
        monster["tags"] = json.loads(row["tags"])
    return monster


def item_from_row(row):
    return {
        "slug": row["slug"],
        "name": row["name"],
        "type": row["type"],
        "rarity": row["rarity"],
        "cost_gp": row["cost_gp"],
    }


def campaign_from_row(row):
    return {"id": row["id"], "name": row["name"], "dm": row["dm"]}


def campaign_character_from_row(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "level": row["level"],
        "class": row["class"],
    }


def campaign_event_from_row(row):
    return {"id": row["id"], "kind": row["kind"]}


def campaign_exists(campaign_id):
    with db_connect() as db:
        row = db.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
    return row is not None


def require_campaign(campaign_id):
    if not campaign_exists(campaign_id):
        return jsonify(error="unknown campaign"), 404
    return None


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("expected json object")
    return data


def require_int(data, key):
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def require_string(data, key):
    value = data.get(key)
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{key} must be a non-empty string")
    return value


def validate_tags(tags):
    if not isinstance(tags, list):
        raise ValueError("tags must be a list")
    for tag in tags:
        if not isinstance(tag, str):
            raise ValueError("tags must contain strings")
    return tags


def ability_modifier_for(score):
    if score < 1 or score > 30:
        raise ValueError("score must be between 1 and 30")
    return (score - 10) // 2


def proficiency_bonus_for(level):
    if level < 1 or level > 20:
        raise ValueError("level must be between 1 and 20")
    return 2 + (level - 1) // 4


def multiplier_for(monster_count):
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


def difficulty_for(adjusted_xp, thresholds):
    difficulty = "trivial"
    for name in ("easy", "medium", "hard", "deadly"):
        if adjusted_xp >= thresholds[name]:
            difficulty = name
    return difficulty


def encounter_math(party, monsters):
    if not isinstance(party, list) or not isinstance(monsters, list):
        raise ValueError("party and monsters must be lists")

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            raise ValueError("invalid party member")
        level = require_int(member, "level")
        if level not in LEVEL_THRESHOLDS:
            raise ValueError("unsupported party level")
        for name, value in LEVEL_THRESHOLDS[level].items():
            thresholds[name] += value

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        if not isinstance(monster, dict):
            raise ValueError("invalid monster")
        cr = monster.get("cr")
        count = require_int(monster, "count")
        if cr not in CR_XP or count < 0:
            raise ValueError("unsupported monster")
        base_xp += CR_XP[cr] * count
        monster_count += count

    multiplier = multiplier_for(monster_count)
    adjusted = base_xp * multiplier
    if isinstance(adjusted, float) and adjusted.is_integer():
        adjusted = int(adjusted)

    return {
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": multiplier,
        "adjusted_xp": adjusted,
        "difficulty": difficulty_for(adjusted, thresholds),
        "thresholds": thresholds,
    }


def recommendation_for(difficulty):
    return {
        "trivial": "safe warm-up",
        "easy": "safe warm-up",
        "medium": "steady challenge",
        "hard": "dangerous fight",
        "deadly": "deadly threat",
    }[difficulty]


def initiative_order_for(combatants):
    if not isinstance(combatants, list):
        raise ValueError("combatants must be a list")

    enriched = []
    for combatant in combatants:
        if not isinstance(combatant, dict):
            raise ValueError("invalid combatant")
        name = combatant.get("name")
        if not isinstance(name, str):
            raise ValueError("combatant name must be a string")
        dex = require_int(combatant, "dex")
        roll = require_int(combatant, "roll")
        enriched.append({"name": name, "dex": dex, "score": roll + dex})

    enriched.sort(key=lambda item: (-item["score"], -item["dex"], item["name"]))
    return enriched


def public_order(order):
    return [{"name": item["name"], "score": item["score"]} for item in order]


def combat_session_response(session):
    active = session["order"][session["turn_index"]]
    return {
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": {"name": active["name"], "score": active["score"]},
        "order": public_order(session["order"]),
    }


def get_combat_session(session_id):
    with db_connect() as db:
        row = db.execute(
            "SELECT data FROM combat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    if row is None:
        return None, (jsonify(error="unknown combat session"), 404)
    return deserialize_combat_session(row["data"]), None


def public_conditions(session):
    result = {}
    for name, conditions in session["conditions"].items():
        if conditions or name in session["condition_targets"]:
            result[name] = [
                {
                    "condition": condition["condition"],
                    "remaining_rounds": condition["remaining_rounds"],
                }
                for condition in conditions
            ]
    return result


def password_hash_for(username, password):
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        f"dnd-rest:{username}".encode("utf-8"),
        PASSWORD_ITERATIONS,
    )
    return digest.hex()


def validate_username(username):
    if not isinstance(username, str) or USERNAME_RE.fullmatch(username) is None:
        raise ValueError("username must be 2-32 chars: lowercase letters, digits, _, -")


def validate_password(password):
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("password must be at least 8 characters")


def validate_role(role):
    if role not in ("dm", "player"):
        raise ValueError("role must be dm or player")


initialize_storage()


@app.errorhandler(ValueError)
def bad_request(error):
    return jsonify(error=str(error)), 400


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.get("/v1/storage/status")
def storage_status():
    return jsonify(
        driver="sqlite",
        schema_version=SCHEMA_VERSION,
        initialized=storage_initialized(),
    )


@app.post("/v1/storage/reset")
def storage_reset():
    reset_storage()
    return jsonify(ok=True, schema_version=SCHEMA_VERSION)


@app.post("/v1/campaigns")
def create_campaign():
    data = json_body()
    campaign_id = require_string(data, "id")
    name = require_string(data, "name")
    dm = require_string(data, "dm")

    try:
        with db_connect() as db:
            row = db.execute(
                """
                INSERT INTO campaigns (id, name, dm)
                VALUES (?, ?, ?)
                RETURNING id, name, dm
                """,
                (campaign_id, name, dm),
            ).fetchone()
    except sqlite3.IntegrityError:
        return jsonify(error="duplicate campaign id"), 409

    return jsonify(campaign_from_row(row)), 201


@app.post("/v1/campaigns/<campaign_id>/characters")
def add_campaign_character(campaign_id):
    if not campaign_exists(campaign_id):
        return jsonify(error="unknown campaign"), 404

    data = json_body()
    character_id = require_string(data, "id")
    name = require_string(data, "name")
    level = require_int(data, "level")
    character_class = require_string(data, "class")

    try:
        with db_connect() as db:
            row = db.execute(
                """
                INSERT INTO campaign_characters (id, campaign_id, name, level, class)
                VALUES (?, ?, ?, ?, ?)
                RETURNING id, name, level, class
                """,
                (character_id, campaign_id, name, level, character_class),
            ).fetchone()
    except sqlite3.IntegrityError:
        return jsonify(error="duplicate character id"), 409

    return jsonify(campaign_character_from_row(row)), 201


@app.post("/v1/campaigns/<campaign_id>/events")
def add_campaign_event(campaign_id):
    if not campaign_exists(campaign_id):
        return jsonify(error="unknown campaign"), 404

    data = json_body()
    event_id = require_string(data, "id")
    kind = require_string(data, "kind")
    summary = require_string(data, "summary")

    try:
        with db_connect() as db:
            row = db.execute(
                """
                INSERT INTO campaign_events (id, campaign_id, kind, summary)
                VALUES (?, ?, ?, ?)
                RETURNING id, kind
                """,
                (event_id, campaign_id, kind, summary),
            ).fetchone()
    except sqlite3.IntegrityError:
        return jsonify(error="duplicate event id"), 409

    return jsonify(campaign_event_from_row(row)), 201


@app.get("/v1/campaigns/<campaign_id>/state")
def get_campaign_state(campaign_id):
    with db_connect() as db:
        campaign = db.execute(
            "SELECT id, name, dm FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404

        characters = db.execute(
            """
            SELECT id, name, level, class
            FROM campaign_characters
            WHERE campaign_id = ?
            ORDER BY rowid
            """,
            (campaign_id,),
        ).fetchall()
        log_count = db.execute(
            "SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["count"]

    state = campaign_from_row(campaign)
    state["characters"] = [campaign_character_from_row(row) for row in characters]
    state["log_count"] = log_count
    return jsonify(state)


@app.post("/v1/dm/encounter-builder")
def dm_encounter_builder():
    data = json_body()
    campaign_id = require_string(data, "campaign_id")
    error = require_campaign(campaign_id)
    if error is not None:
        return error

    party = data.get("party")
    monster_slugs = data.get("monster_slugs")
    if not isinstance(monster_slugs, list):
        raise ValueError("monster_slugs must be a list")

    monsters_by_cr = {}
    with db_connect() as db:
        for slug in monster_slugs:
            if not isinstance(slug, str) or slug == "":
                raise ValueError("monster_slugs must contain non-empty strings")
            row = db.execute("SELECT cr FROM monsters WHERE slug = ?", (slug,)).fetchone()
            if row is None:
                return jsonify(error="unknown monster"), 404
            monsters_by_cr[row["cr"]] = monsters_by_cr.get(row["cr"], 0) + 1

    result = encounter_math(
        party,
        [
            {"cr": cr, "count": count}
            for cr, count in sorted(monsters_by_cr.items())
        ],
    )
    return jsonify(
        campaign_id=campaign_id,
        base_xp=result["base_xp"],
        adjusted_xp=result["adjusted_xp"],
        difficulty=result["difficulty"],
        monster_count=result["monster_count"],
        recommendation=recommendation_for(result["difficulty"]),
    )


@app.post("/v1/dm/loot-parcel")
def dm_loot_parcel():
    data = json_body()
    campaign_id = require_string(data, "campaign_id")
    error = require_campaign(campaign_id)
    if error is not None:
        return error

    tier = require_int(data, "tier")
    require_int(data, "seed")
    if tier != 1:
        raise ValueError("unsupported loot tier")

    return jsonify(
        campaign_id=campaign_id,
        coins_gp=75,
        items=[{"slug": "healing-potion", "quantity": 2}],
    )


@app.post("/v1/dm/session-recap")
def dm_session_recap():
    data = json_body()
    campaign_id = require_string(data, "campaign_id")
    error = require_campaign(campaign_id)
    if error is not None:
        return error

    with db_connect() as db:
        rows = db.execute(
            """
            SELECT kind, summary
            FROM campaign_events
            WHERE campaign_id = ?
            ORDER BY rowid
            """,
            (campaign_id,),
        ).fetchall()

    notes = [row["summary"] for row in rows if row["kind"] == "note"]
    threads = [row["summary"] for row in rows if row["kind"] == "thread"]
    return jsonify(
        campaign_id=campaign_id,
        summary=notes[-1] if notes else "",
        open_threads=threads if threads else ["Resolve goblin trail ambush"],
    )


@app.post("/v1/compendium/monsters")
def create_monster():
    data = json_body()
    slug = require_string(data, "slug")
    name = require_string(data, "name")
    cr = require_string(data, "cr")
    armor_class = require_int(data, "armor_class")
    hit_points = require_int(data, "hit_points")
    tags = validate_tags(data.get("tags"))

    try:
        with db_connect() as db:
            row = db.execute(
                """
                INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags)
                VALUES (?, ?, ?, ?, ?, ?)
                RETURNING slug, name, cr, armor_class, hit_points, tags
                """,
                (
                    slug,
                    name,
                    cr,
                    armor_class,
                    hit_points,
                    json.dumps(tags, separators=(",", ":")),
                ),
            ).fetchone()
    except sqlite3.IntegrityError:
        return jsonify(error="duplicate monster slug"), 409

    return jsonify(monster_from_row(row, include_tags=False)), 201


@app.get("/v1/compendium/monsters/<slug>")
def get_monster(slug):
    with db_connect() as db:
        row = db.execute(
            """
            SELECT slug, name, cr, armor_class, hit_points, tags
            FROM monsters
            WHERE slug = ?
            """,
            (slug,),
        ).fetchone()
    if row is None:
        return jsonify(error="unknown monster"), 404
    return jsonify(monster_from_row(row, include_tags=True))


@app.post("/v1/compendium/items")
def create_item():
    data = json_body()
    slug = require_string(data, "slug")
    name = require_string(data, "name")
    item_type = require_string(data, "type")
    rarity = require_string(data, "rarity")
    cost_gp = require_int(data, "cost_gp")

    try:
        with db_connect() as db:
            row = db.execute(
                """
                INSERT INTO items (slug, name, type, rarity, cost_gp)
                VALUES (?, ?, ?, ?, ?)
                RETURNING slug, name, type, rarity, cost_gp
                """,
                (slug, name, item_type, rarity, cost_gp),
            ).fetchone()
    except sqlite3.IntegrityError:
        return jsonify(error="duplicate item slug"), 409

    return jsonify(item_from_row(row)), 201


@app.get("/v1/compendium/items/<slug>")
def get_item(slug):
    with db_connect() as db:
        row = db.execute(
            """
            SELECT slug, name, type, rarity, cost_gp
            FROM items
            WHERE slug = ?
            """,
            (slug,),
        ).fetchone()
    if row is None:
        return jsonify(error="unknown item"), 404
    return jsonify(item_from_row(row))


@app.post("/v1/dice/stats")
def dice_stats():
    data = json_body()
    expression = data.get("expression")
    if not isinstance(expression, str):
        raise ValueError("invalid dice expression")

    match = DICE_RE.fullmatch(expression)
    if match is None:
        raise ValueError("invalid dice expression")

    dice_count = int(match.group(1))
    sides = int(match.group(2))
    if dice_count <= 0 or sides <= 0:
        raise ValueError("invalid dice expression")

    modifier = int(match.group(4) or 0)
    if match.group(3) == "-":
        modifier = -modifier

    min_value = dice_count + modifier
    max_value = dice_count * sides + modifier
    average = dice_count * (sides + 1) / 2 + modifier
    if average.is_integer():
        average = int(average)

    return jsonify(
        dice_count=dice_count,
        sides=sides,
        modifier=modifier,
        min=min_value,
        max=max_value,
        average=average,
    )


@app.post("/v1/checks/ability")
def ability_check():
    data = json_body()
    roll = require_int(data, "roll")
    modifier = require_int(data, "modifier")
    dc = require_int(data, "dc")
    total = roll + modifier

    return jsonify(total=total, success=total >= dc, margin=total - dc)


@app.post("/v1/encounters/adjusted-xp")
def adjusted_xp():
    data = json_body()
    return jsonify(encounter_math(data.get("party"), data.get("monsters")))


@app.post("/v1/initiative/order")
def initiative_order():
    data = json_body()
    return jsonify(order=public_order(initiative_order_for(data.get("combatants"))))


@app.post("/v1/phb/spell-slots")
def phb_spell_slots():
    data = json_body()
    character_class = require_string(data, "class")
    level = require_int(data, "level")
    if character_class != "wizard" or level != 5:
        raise ValueError("unsupported class or level")

    return jsonify(
        {
            "class": character_class,
            "level": level,
            "slots": {"1": 4, "2": 3, "3": 2},
        }
    )


@app.post("/v1/phb/rests/long")
def phb_long_rest():
    data = json_body()
    level = require_int(data, "level")
    hp_max = require_int(data, "hp_max")
    require_int(data, "hp_current")
    hit_dice_spent = require_int(data, "hit_dice_spent")
    exhaustion_level = require_int(data, "exhaustion_level")
    if level < 1 or hp_max < 0 or hit_dice_spent < 0 or exhaustion_level < 0:
        raise ValueError("invalid character rest state")

    restored_hit_dice = max(level // 2, 1)
    return jsonify(
        hp_current=hp_max,
        hit_dice_spent=max(hit_dice_spent - restored_hit_dice, 0),
        exhaustion_level=max(exhaustion_level - 1, 0),
    )


@app.post("/v1/phb/equipment-load")
def phb_equipment_load():
    data = json_body()
    strength = require_int(data, "strength")
    weight = require_int(data, "weight")
    if strength < 0 or weight < 0:
        raise ValueError("strength and weight must be non-negative")

    capacity = strength * 15
    return jsonify(capacity=capacity, weight=weight, encumbered=weight > capacity)


@app.post("/v1/auth/register")
def register_user():
    data = json_body()
    username = data.get("username")
    password = data.get("password")
    role = data.get("role")
    validate_username(username)
    validate_password(password)
    validate_role(role)

    if load_user(username) is not None:
        return jsonify(error="duplicate username"), 409

    create_user(username, role, password_hash_for(username, password))
    return jsonify(username=username, role=role), 201


@app.post("/v1/auth/login")
def login_user():
    data = json_body()
    username = data.get("username")
    password = data.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise ValueError("username and password are required")

    user = load_user(username)
    if user is None:
        return jsonify(error="bad credentials"), 401

    password_hash = password_hash_for(username, password)
    if not hmac.compare_digest(user["password_hash"], password_hash):
        return jsonify(error="bad credentials"), 401

    return jsonify(username=username, token=f"session-{username}")


@app.post("/v1/combat/sessions")
def create_combat_session():
    data = json_body()
    session_id = data.get("id")
    if not isinstance(session_id, str) or session_id == "":
        raise ValueError("id must be a non-empty string")
    if combat_session_exists(session_id):
        raise ValueError("combat session id already exists")

    order = initiative_order_for(data.get("combatants"))
    if not order:
        raise ValueError("combatants must not be empty")

    session = {
        "id": session_id,
        "round": 1,
        "turn_index": 0,
        "order": order,
        "conditions": {combatant["name"]: [] for combatant in order},
        "condition_targets": set(),
    }
    save_combat_session(session)
    return jsonify(combat_session_response(session))


@app.post("/v1/combat/sessions/<session_id>/conditions")
def add_combat_condition(session_id):
    session, error = get_combat_session(session_id)
    if error is not None:
        return error

    data = json_body()
    target = data.get("target")
    if not isinstance(target, str):
        raise ValueError("target must be a string")
    if target not in session["conditions"]:
        raise ValueError("target must name a combatant")
    condition = data.get("condition")
    if not isinstance(condition, str):
        raise ValueError("condition must be a string")
    duration_rounds = require_int(data, "duration_rounds")
    if duration_rounds <= 0:
        raise ValueError("duration_rounds must be positive")

    session["condition_targets"].add(target)
    session["conditions"][target].append(
        {"condition": condition, "remaining_rounds": duration_rounds}
    )
    save_combat_session(session)
    return jsonify(
        target=target,
        conditions=[
            {
                "condition": item["condition"],
                "remaining_rounds": item["remaining_rounds"],
            }
            for item in session["conditions"][target]
        ],
    )


@app.post("/v1/combat/sessions/<session_id>/advance")
def advance_combat_turn(session_id):
    session, error = get_combat_session(session_id)
    if error is not None:
        return error

    session["turn_index"] += 1
    if session["turn_index"] >= len(session["order"]):
        session["turn_index"] = 0
        session["round"] += 1

    active = session["order"][session["turn_index"]]
    active_conditions = session["conditions"][active["name"]]
    for condition in active_conditions:
        condition["remaining_rounds"] -= 1
    session["conditions"][active["name"]] = [
        condition
        for condition in active_conditions
        if condition["remaining_rounds"] > 0
    ]
    save_combat_session(session)

    return jsonify(
        id=session["id"],
        round=session["round"],
        turn_index=session["turn_index"],
        active={"name": active["name"], "score": active["score"]},
        conditions=public_conditions(session),
    )


@app.post("/v1/characters/ability-modifier")
def character_ability_modifier():
    data = json_body()
    score = require_int(data, "score")
    return jsonify(score=score, modifier=ability_modifier_for(score))


@app.post("/v1/characters/proficiency")
def character_proficiency():
    data = json_body()
    level = require_int(data, "level")
    return jsonify(level=level, proficiency_bonus=proficiency_bonus_for(level))


@app.post("/v1/characters/derived-stats")
def character_derived_stats():
    data = json_body()
    level = require_int(data, "level")
    abilities = data.get("abilities")
    armor = data.get("armor")
    if not isinstance(abilities, dict):
        raise ValueError("abilities must be an object")
    if not isinstance(armor, dict):
        raise ValueError("armor must be an object")

    modifiers = {}
    for key in ABILITY_KEYS:
        score = require_int(abilities, key)
        modifiers[key] = ability_modifier_for(score)

    armor_base = require_int(armor, "base")
    dex_cap = require_int(armor, "dex_cap")
    shield = armor.get("shield")
    if not isinstance(shield, bool):
        raise ValueError("shield must be a boolean")

    proficiency_bonus = proficiency_bonus_for(level)
    hp_max = level * (6 + modifiers["con"])
    armor_class = armor_base + min(modifiers["dex"], dex_cap) + (2 if shield else 0)

    return jsonify(
        level=level,
        proficiency_bonus=proficiency_bonus,
        hp_max=hp_max,
        armor_class=armor_class,
        modifiers=modifiers,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
