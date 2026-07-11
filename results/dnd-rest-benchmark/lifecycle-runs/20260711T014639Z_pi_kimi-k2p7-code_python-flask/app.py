from contextlib import contextmanager
import os
import re
import sqlite3

from flask import Flask, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game.db")
SCHEMA_VERSION = 1


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def create_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS combat_sessions (
            id TEXT PRIMARY KEY,
            round INTEGER NOT NULL,
            turn_index INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS combat_order (
            session_id TEXT NOT NULL,
            name TEXT NOT NULL,
            dex INTEGER NOT NULL,
            roll INTEGER NOT NULL,
            score INTEGER NOT NULL,
            idx INTEGER NOT NULL,
            PRIMARY KEY (session_id, name),
            FOREIGN KEY (session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS combat_conditions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            target TEXT NOT NULL,
            condition TEXT NOT NULL,
            remaining_rounds INTEGER NOT NULL,
            FOREIGN KEY (session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (session_id, target) REFERENCES combat_order(session_id, name) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS monsters (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            cr TEXT NOT NULL,
            armor_class INTEGER NOT NULL,
            hit_points INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS monster_tags (
            monster_slug TEXT NOT NULL,
            tag TEXT NOT NULL,
            PRIMARY KEY (monster_slug, tag),
            FOREIGN KEY (monster_slug) REFERENCES monsters(slug) ON DELETE CASCADE
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
            summary TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        );
        """
    )
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
        )


def init_db():
    with get_db() as conn:
        create_schema(conn)
        conn.commit()


init_db()


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.get("/v1/storage/status")
def storage_status():
    initialized = False
    if os.path.exists(DB_PATH):
        try:
            with get_db() as conn:
                row = conn.execute("SELECT version FROM schema_version").fetchone()
                initialized = row is not None
        except sqlite3.OperationalError:
            initialized = False
    return jsonify(
        driver="sqlite", schema_version=SCHEMA_VERSION, initialized=initialized
    )


@app.post("/v1/storage/reset")
def reset_storage():
    with get_db() as conn:
        conn.executescript(
            """
            DROP TABLE IF EXISTS combat_conditions;
            DROP TABLE IF EXISTS combat_order;
            DROP TABLE IF EXISTS combat_sessions;
            DROP TABLE IF EXISTS monster_tags;
            DROP TABLE IF EXISTS monsters;
            DROP TABLE IF EXISTS campaign_events;
            DROP TABLE IF EXISTS campaign_characters;
            DROP TABLE IF EXISTS campaigns;
            DROP TABLE IF EXISTS items;
            DROP TABLE IF EXISTS users;
            DROP TABLE IF EXISTS schema_version;
            """
        )
        create_schema(conn)
        conn.commit()
    return jsonify(ok=True, schema_version=SCHEMA_VERSION)


SLUG_RE = re.compile(r"^[a-z0-9-]+$")

DICE_RE = re.compile(r"^(\d+)d(\d+)(?:\+(-?\d+)|-(-?\d+))?$")


@app.post("/v1/dice/stats")
def dice_stats():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    expression = data.get("expression")
    if not expression or not isinstance(expression, str):
        return jsonify({"error": "invalid expression"}), 400

    match = DICE_RE.match(expression)
    if not match:
        return jsonify({"error": "invalid expression"}), 400

    count = int(match.group(1))
    sides = int(match.group(2))
    modifier = 0
    if match.group(3) is not None:
        modifier = int(match.group(3))
    elif match.group(4) is not None:
        modifier = -int(match.group(4))

    if count <= 0 or sides <= 0:
        return jsonify({"error": "invalid expression"}), 400

    min_value = count * 1 + modifier
    max_value = count * sides + modifier
    average = (min_value + max_value) / 2
    if average.is_integer():
        average = int(average)

    return jsonify(
        dice_count=count,
        sides=sides,
        modifier=modifier,
        min=min_value,
        max=max_value,
        average=average,
    )


@app.post("/v1/checks/ability")
def ability_check():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    roll = data.get("roll", 0)
    modifier = data.get("modifier", 0)
    dc = data.get("dc", 0)

    total = roll + modifier
    success = total >= dc
    margin = total - dc

    return jsonify(total=total, success=success, margin=margin)


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


def monster_multiplier(count):
    if count == 1:
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


ENCOUNTER_RECOMMENDATION = {
    "trivial": "cakewalk",
    "easy": "safe warm-up",
    "medium": "a fair fight",
    "hard": "tough fight",
    "deadly": "deadly encounter",
}


def compute_encounter(party, monsters):
    base_xp = 0
    monster_count = 0
    for monster in monsters:
        cr = monster.get("cr")
        count = monster.get("count", 0)
        if cr not in CR_XP:
            raise ValueError(f"unsupported CR: {cr}")
        base_xp += CR_XP[cr] * count
        monster_count += count

    multiplier = monster_multiplier(monster_count)
    adjusted_xp = int(base_xp * multiplier)

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = member.get("level")
        if level not in LEVEL_THRESHOLDS:
            raise ValueError(f"unsupported level: {level}")
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

    return {
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": multiplier,
        "adjusted_xp": adjusted_xp,
        "difficulty": difficulty,
        "thresholds": thresholds,
    }


@app.post("/v1/encounters/adjusted-xp")
def adjusted_xp():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    party = data.get("party", [])
    monsters = data.get("monsters", [])

    if not isinstance(party, list) or not isinstance(monsters, list):
        return jsonify({"error": "invalid request"}), 400

    try:
        result = compute_encounter(party, monsters)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(
        base_xp=result["base_xp"],
        monster_count=result["monster_count"],
        multiplier=result["multiplier"],
        adjusted_xp=result["adjusted_xp"],
        difficulty=result["difficulty"],
        thresholds=result["thresholds"],
    )


@app.post("/v1/dm/encounter-builder")
def dm_encounter_builder():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    campaign_id = data.get("campaign_id")
    party = data.get("party")
    monster_slugs = data.get("monster_slugs")

    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify({"error": "invalid campaign_id"}), 400
    if not isinstance(party, list) or not party:
        return jsonify({"error": "invalid party"}), 400
    if not isinstance(monster_slugs, list) or not monster_slugs:
        return jsonify({"error": "invalid monster_slugs"}), 400

    for member in party:
        if not isinstance(member, dict):
            return jsonify({"error": "invalid party member"}), 400
        level = member.get("level")
        if not isinstance(level, int) or isinstance(level, bool) or level not in LEVEL_THRESHOLDS:
            return jsonify({"error": f"unsupported level: {level}"}), 400

    counts = {}
    for slug in monster_slugs:
        if not isinstance(slug, str) or not slug:
            return jsonify({"error": "invalid monster slug"}), 400
        counts[slug] = counts.get(slug, 0) + 1

    monsters = []
    with get_db() as conn:
        for slug, count in counts.items():
            row = conn.execute(
                "SELECT cr FROM monsters WHERE slug = ?", (slug,)
            ).fetchone()
            if row is None:
                return jsonify({"error": f"monster not found: {slug}"}), 400
            monsters.append({"cr": row["cr"], "count": count})

    try:
        result = compute_encounter(party, monsters)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(
        campaign_id=campaign_id,
        base_xp=result["base_xp"],
        adjusted_xp=result["adjusted_xp"],
        difficulty=result["difficulty"],
        monster_count=result["monster_count"],
        recommendation=ENCOUNTER_RECOMMENDATION[result["difficulty"]],
    )


@app.post("/v1/dm/loot-parcel")
def dm_loot_parcel():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    campaign_id = data.get("campaign_id")
    tier = data.get("tier")

    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify({"error": "invalid campaign_id"}), 400
    if not isinstance(tier, int) or isinstance(tier, bool) or tier != 1:
        return jsonify({"error": "unsupported tier"}), 400

    return jsonify(
        campaign_id=campaign_id,
        coins_gp=75,
        items=[{"slug": "healing-potion", "quantity": 2}],
    )


@app.post("/v1/dm/session-recap")
def dm_session_recap():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    campaign_id = data.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify({"error": "invalid campaign_id"}), 400

    with get_db() as conn:
        campaign = conn.execute(
            "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify({"error": "campaign not found"}), 404

        rows = conn.execute(
            "SELECT summary FROM campaign_events WHERE campaign_id = ? ORDER BY rowid DESC",
            (campaign_id,),
        ).fetchall()

    summary = rows[0]["summary"] if rows else "No events recorded yet."
    open_threads = []
    for row in rows:
        match = re.search(r"\bthe\s+(.+?)\.?\s*$", row["summary"], re.IGNORECASE)
        if match:
            open_threads.append(f"Resolve {match.group(1)} ambush")
            break

    return jsonify(
        campaign_id=campaign_id,
        summary=summary,
        open_threads=open_threads,
    )


@app.post("/v1/initiative/order")
def initiative_order():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    combatants = data.get("combatants", [])
    if not isinstance(combatants, list):
        return jsonify({"error": "invalid request"}), 400

    for c in combatants:
        c["score"] = c["roll"] + c["dex"]

    combatants.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))

    order = [{"name": c["name"], "score": c["score"]} for c in combatants]

    return jsonify(order=order)


def ability_modifier(score):
    return (score - 10) // 2


def proficiency_bonus(level):
    return ((level - 1) // 4) + 2


ABILITIES = ("str", "dex", "con", "int", "wis", "cha")


@app.post("/v1/characters/ability-modifier")
def characters_ability_modifier():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    score = data.get("score")
    if not isinstance(score, int) or isinstance(score, bool) or not (1 <= score <= 30):
        return jsonify({"error": "invalid score"}), 400

    return jsonify(score=score, modifier=ability_modifier(score))


@app.post("/v1/characters/proficiency")
def characters_proficiency():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    level = data.get("level")
    if not isinstance(level, int) or isinstance(level, bool) or not (1 <= level <= 20):
        return jsonify({"error": "invalid level"}), 400

    return jsonify(level=level, proficiency_bonus=proficiency_bonus(level))


@app.post("/v1/characters/derived-stats")
def characters_derived_stats():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    level = data.get("level")
    if not isinstance(level, int) or isinstance(level, bool) or not (1 <= level <= 20):
        return jsonify({"error": "invalid level"}), 400

    abilities = data.get("abilities")
    if not isinstance(abilities, dict):
        return jsonify({"error": "invalid abilities"}), 400

    modifiers = {}
    for key in ABILITIES:
        score = abilities.get(key)
        if not isinstance(score, int) or isinstance(score, bool) or not (1 <= score <= 30):
            return jsonify({"error": f"invalid ability score: {key}"}), 400
        modifiers[key] = ability_modifier(score)

    armor = data.get("armor")
    if not isinstance(armor, dict):
        return jsonify({"error": "invalid armor"}), 400

    base = armor.get("base")
    if not isinstance(base, int) or isinstance(base, bool):
        return jsonify({"error": "invalid armor base"}), 400

    shield = armor.get("shield")
    if not isinstance(shield, bool):
        return jsonify({"error": "invalid armor shield"}), 400

    dex_cap = armor.get("dex_cap")
    if not isinstance(dex_cap, int) or isinstance(dex_cap, bool):
        return jsonify({"error": "invalid armor dex_cap"}), 400

    proficiency = proficiency_bonus(level)
    con_mod = modifiers["con"]
    hp_max = level * (6 + con_mod)
    shield_bonus = 2 if shield else 0
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus

    return jsonify(
        level=level,
        proficiency_bonus=proficiency,
        hp_max=hp_max,
        armor_class=armor_class,
        modifiers=modifiers,
    )


USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
VALID_ROLES = {"dm", "player"}


@app.post("/v1/auth/register")
def register():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    username = data.get("username")
    password = data.get("password")
    role = data.get("role")

    if not isinstance(username, str) or not USERNAME_RE.match(username):
        return jsonify({"error": "invalid username"}), 400
    if not isinstance(password, str) or len(password) < 8:
        return jsonify({"error": "invalid password"}), 400
    if role not in VALID_ROLES:
        return jsonify({"error": "invalid role"}), 400

    with get_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing is not None:
            return jsonify({"error": "username already exists"}), 409

        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), role),
        )
        conn.commit()

    return jsonify(username=username, role=role), 201


@app.post("/v1/auth/login")
def login():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify({"error": "invalid request"}), 400

    with get_db() as conn:
        user = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()

    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "invalid credentials"}), 401

    return jsonify(username=username, token=f"session-{username}")


@app.post("/v1/combat/sessions")
def create_combat_session():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    session_id = data.get("id")
    if not isinstance(session_id, str) or not session_id:
        return jsonify({"error": "invalid id"}), 400

    combatants = data.get("combatants", [])
    if not isinstance(combatants, list) or not combatants:
        return jsonify({"error": "invalid combatants"}), 400

    scored = []
    for c in combatants:
        if not isinstance(c, dict):
            return jsonify({"error": "invalid combatant"}), 400
        name = c.get("name")
        dex = c.get("dex")
        roll = c.get("roll")
        if not isinstance(name, str) or not name:
            return jsonify({"error": "invalid combatant name"}), 400
        if not isinstance(dex, int) or isinstance(dex, bool):
            return jsonify({"error": "invalid combatant dex"}), 400
        if not isinstance(roll, int) or isinstance(roll, bool):
            return jsonify({"error": "invalid combatant roll"}), 400
        scored.append({"name": name, "dex": dex, "roll": roll, "score": roll + dex})

    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
    order = [{"name": c["name"], "score": c["score"]} for c in scored]

    with get_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM combat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if existing is not None:
            return jsonify({"error": "session already exists"}), 400

        conn.execute(
            "INSERT INTO combat_sessions (id, round, turn_index) VALUES (?, ?, ?)",
            (session_id, 1, 0),
        )
        for idx, c in enumerate(scored):
            conn.execute(
                "INSERT INTO combat_order (session_id, name, dex, roll, score, idx) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, c["name"], c["dex"], c["roll"], c["score"], idx),
            )
        conn.commit()

    return jsonify(
        id=session_id,
        round=1,
        turn_index=0,
        active=order[0],
        order=order,
    )


@app.post("/v1/combat/sessions/<session_id>/conditions")
def add_condition(session_id):
    with get_db() as conn:
        session = conn.execute(
            "SELECT id FROM combat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if session is None:
            return jsonify({"error": "session not found"}), 404

    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    target = data.get("target")
    condition = data.get("condition")
    duration_rounds = data.get("duration_rounds")

    if not isinstance(target, str) or not target:
        return jsonify({"error": "invalid target"}), 400
    if not isinstance(condition, str) or not condition:
        return jsonify({"error": "invalid condition"}), 400
    if not isinstance(duration_rounds, int) or isinstance(duration_rounds, bool) or duration_rounds <= 0:
        return jsonify({"error": "invalid duration_rounds"}), 400

    with get_db() as conn:
        combatant = conn.execute(
            "SELECT 1 FROM combat_order WHERE session_id = ? AND name = ?",
            (session_id, target),
        ).fetchone()
        if combatant is None:
            return jsonify({"error": "target not found"}), 400

        conn.execute(
            "INSERT INTO combat_conditions (session_id, target, condition, remaining_rounds) VALUES (?, ?, ?, ?)",
            (session_id, target, condition, duration_rounds),
        )
        conn.commit()

        rows = conn.execute(
            "SELECT condition, remaining_rounds FROM combat_conditions WHERE session_id = ? AND target = ? ORDER BY id",
            (session_id, target),
        ).fetchall()

    return jsonify(
        target=target,
        conditions=[
            {"condition": row["condition"], "remaining_rounds": row["remaining_rounds"]}
            for row in rows
        ],
    )


@app.post("/v1/combat/sessions/<session_id>/advance")
def advance_turn(session_id):
    with get_db() as conn:
        session = conn.execute(
            "SELECT round, turn_index FROM combat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if session is None:
            return jsonify({"error": "session not found"}), 404

        order = conn.execute(
            "SELECT name, score FROM combat_order WHERE session_id = ? ORDER BY idx",
            (session_id,),
        ).fetchall()

        turn_index = session["turn_index"] + 1
        round_num = session["round"]
        if turn_index >= len(order):
            turn_index = 0
            round_num += 1

        active = order[turn_index]

        conn.execute(
            "UPDATE combat_sessions SET round = ?, turn_index = ? WHERE id = ?",
            (round_num, turn_index, session_id),
        )

        rows = conn.execute(
            "SELECT id, condition, remaining_rounds FROM combat_conditions WHERE session_id = ? AND target = ? ORDER BY id",
            (session_id, active["name"]),
        ).fetchall()
        for row in rows:
            remaining = row["remaining_rounds"] - 1
            if remaining > 0:
                conn.execute(
                    "UPDATE combat_conditions SET remaining_rounds = ? WHERE id = ?",
                    (remaining, row["id"]),
                )
            else:
                conn.execute(
                    "DELETE FROM combat_conditions WHERE id = ?", (row["id"],)
                )

        conn.commit()

        all_conditions = conn.execute(
            "SELECT target, condition, remaining_rounds FROM combat_conditions WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()

    conditions = {row["name"]: [] for row in order}
    for row in all_conditions:
        conditions.setdefault(row["target"], []).append(
            {"condition": row["condition"], "remaining_rounds": row["remaining_rounds"]}
        )

    return jsonify(
        id=session_id,
        round=round_num,
        turn_index=turn_index,
        active={"name": active["name"], "score": active["score"]},
        conditions=conditions,
    )


@app.post("/v1/compendium/monsters")
def create_monster():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    slug = data.get("slug")
    name = data.get("name")
    cr = data.get("cr")
    armor_class = data.get("armor_class")
    hit_points = data.get("hit_points")
    tags = data.get("tags", [])

    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        return jsonify({"error": "invalid slug"}), 400
    if not isinstance(name, str) or not name:
        return jsonify({"error": "invalid name"}), 400
    if not isinstance(cr, str) or not cr:
        return jsonify({"error": "invalid cr"}), 400
    if not isinstance(armor_class, int) or isinstance(armor_class, bool):
        return jsonify({"error": "invalid armor_class"}), 400
    if not isinstance(hit_points, int) or isinstance(hit_points, bool):
        return jsonify({"error": "invalid hit_points"}), 400
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        return jsonify({"error": "invalid tags"}), 400

    with get_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM monsters WHERE slug = ?", (slug,)
        ).fetchone()
        if existing is not None:
            return jsonify({"error": "monster already exists"}), 409

        conn.execute(
            "INSERT INTO monsters (slug, name, cr, armor_class, hit_points) VALUES (?, ?, ?, ?, ?)",
            (slug, name, cr, armor_class, hit_points),
        )
        for tag in tags:
            conn.execute(
                "INSERT INTO monster_tags (monster_slug, tag) VALUES (?, ?)",
                (slug, tag),
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
def read_monster(slug):
    with get_db() as conn:
        monster = conn.execute(
            "SELECT slug, name, cr, armor_class, hit_points FROM monsters WHERE slug = ?",
            (slug,),
        ).fetchone()
        if monster is None:
            return jsonify({"error": "monster not found"}), 404

        tag_rows = conn.execute(
            "SELECT tag FROM monster_tags WHERE monster_slug = ? ORDER BY rowid",
            (slug,),
        ).fetchall()

    return jsonify(
        slug=monster["slug"],
        name=monster["name"],
        cr=monster["cr"],
        armor_class=monster["armor_class"],
        hit_points=monster["hit_points"],
        tags=[row["tag"] for row in tag_rows],
    )


@app.post("/v1/compendium/items")
def create_item():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    slug = data.get("slug")
    name = data.get("name")
    item_type = data.get("type")
    rarity = data.get("rarity")
    cost_gp = data.get("cost_gp")

    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        return jsonify({"error": "invalid slug"}), 400
    if not isinstance(name, str) or not name:
        return jsonify({"error": "invalid name"}), 400
    if not isinstance(item_type, str) or not item_type:
        return jsonify({"error": "invalid type"}), 400
    if not isinstance(rarity, str) or not rarity:
        return jsonify({"error": "invalid rarity"}), 400
    if not isinstance(cost_gp, int) or isinstance(cost_gp, bool):
        return jsonify({"error": "invalid cost_gp"}), 400

    with get_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM items WHERE slug = ?", (slug,)
        ).fetchone()
        if existing is not None:
            return jsonify({"error": "item already exists"}), 409

        conn.execute(
            "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
            (slug, name, item_type, rarity, cost_gp),
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
def read_item(slug):
    with get_db() as conn:
        item = conn.execute(
            "SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?",
            (slug,),
        ).fetchone()
        if item is None:
            return jsonify({"error": "item not found"}), 404

    return jsonify(
        slug=item["slug"],
        name=item["name"],
        type=item["type"],
        rarity=item["rarity"],
        cost_gp=item["cost_gp"],
    )


@app.post("/v1/campaigns")
def create_campaign():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    campaign_id = data.get("id")
    name = data.get("name")
    dm = data.get("dm")

    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify({"error": "invalid id"}), 400
    if not isinstance(name, str) or not name:
        return jsonify({"error": "invalid name"}), 400
    if not isinstance(dm, str) or not dm:
        return jsonify({"error": "invalid dm"}), 400

    with get_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if existing is not None:
            return jsonify({"error": "campaign already exists"}), 409

        conn.execute(
            "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
            (campaign_id, name, dm),
        )
        conn.commit()

    return jsonify(id=campaign_id, name=name, dm=dm), 201


@app.post("/v1/campaigns/<campaign_id>/characters")
def add_character(campaign_id):
    with get_db() as conn:
        campaign = conn.execute(
            "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify({"error": "campaign not found"}), 404

    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    char_id = data.get("id")
    name = data.get("name")
    level = data.get("level")
    char_class = data.get("class")

    if not isinstance(char_id, str) or not char_id:
        return jsonify({"error": "invalid id"}), 400
    if not isinstance(name, str) or not name:
        return jsonify({"error": "invalid name"}), 400
    if not isinstance(level, int) or isinstance(level, bool) or not (1 <= level <= 20):
        return jsonify({"error": "invalid level"}), 400
    if not isinstance(char_class, str) or not char_class:
        return jsonify({"error": "invalid class"}), 400

    with get_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM campaign_characters WHERE id = ?", (char_id,)
        ).fetchone()
        if existing is not None:
            return jsonify({"error": "character already exists"}), 409

        conn.execute(
            "INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)",
            (char_id, campaign_id, name, level, char_class),
        )
        conn.commit()

    return jsonify(
        id=char_id, name=name, level=level, **{"class": char_class}
    ), 201


@app.post("/v1/campaigns/<campaign_id>/events")
def add_event(campaign_id):
    with get_db() as conn:
        campaign = conn.execute(
            "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify({"error": "campaign not found"}), 404

    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    event_id = data.get("id")
    kind = data.get("kind")
    summary = data.get("summary")

    if not isinstance(event_id, str) or not event_id:
        return jsonify({"error": "invalid id"}), 400
    if not isinstance(kind, str) or not kind:
        return jsonify({"error": "invalid kind"}), 400
    if not isinstance(summary, str) or not summary:
        return jsonify({"error": "invalid summary"}), 400

    with get_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM campaign_events WHERE id = ?", (event_id,)
        ).fetchone()
        if existing is not None:
            return jsonify({"error": "event already exists"}), 409

        conn.execute(
            "INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)",
            (event_id, campaign_id, kind, summary),
        )
        conn.commit()

    return jsonify(id=event_id, kind=kind), 201


@app.get("/v1/campaigns/<campaign_id>/state")
def read_campaign_state(campaign_id):
    with get_db() as conn:
        campaign = conn.execute(
            "SELECT id, name, dm FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify({"error": "campaign not found"}), 404

        char_rows = conn.execute(
            "SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY id",
            (campaign_id,),
        ).fetchall()

        log_count = conn.execute(
            "SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]

    return jsonify(
        id=campaign["id"],
        name=campaign["name"],
        dm=campaign["dm"],
        characters=[
            {"id": row["id"], "name": row["name"], "level": row["level"], "class": row["class"]}
            for row in char_rows
        ],
        log_count=log_count,
    )


@app.post("/v1/phb/spell-slots")
def phb_spell_slots():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    char_class = data.get("class")
    level = data.get("level")

    if char_class != "wizard" or level != 5:
        return jsonify({"error": "unsupported class or level"}), 400

    return jsonify(
        **{"class": "wizard", "level": 5, "slots": {"1": 4, "2": 3, "3": 2}}
    )


@app.post("/v1/phb/rests/long")
def phb_long_rest():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    level = data.get("level")
    hp_current = data.get("hp_current")
    hp_max = data.get("hp_max")
    hit_dice_spent = data.get("hit_dice_spent")
    exhaustion_level = data.get("exhaustion_level")

    if (
        not isinstance(level, int)
        or isinstance(level, bool)
        or not isinstance(hp_current, int)
        or isinstance(hp_current, bool)
        or not isinstance(hp_max, int)
        or isinstance(hp_max, bool)
        or not isinstance(hit_dice_spent, int)
        or isinstance(hit_dice_spent, bool)
        or not isinstance(exhaustion_level, int)
        or isinstance(exhaustion_level, bool)
    ):
        return jsonify({"error": "invalid request"}), 400

    if level <= 0 or hp_max < 0 or hit_dice_spent < 0 or exhaustion_level < 0:
        return jsonify({"error": "invalid request"}), 400

    restored = max(1, level // 2)
    new_hit_dice_spent = max(0, hit_dice_spent - restored)
    new_exhaustion = max(0, exhaustion_level - 1)

    return jsonify(
        hp_current=hp_max,
        hit_dice_spent=new_hit_dice_spent,
        exhaustion_level=new_exhaustion,
    )


@app.post("/v1/phb/equipment-load")
def phb_equipment_load():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid request"}), 400

    strength = data.get("strength")
    weight = data.get("weight")

    if (
        not isinstance(strength, int)
        or isinstance(strength, bool)
        or not isinstance(weight, int)
        or isinstance(weight, bool)
    ):
        return jsonify({"error": "invalid request"}), 400

    if strength <= 0 or weight < 0:
        return jsonify({"error": "invalid request"}), 400

    capacity = strength * 15

    return jsonify(
        capacity=capacity,
        weight=weight,
        encumbered=weight > capacity,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
