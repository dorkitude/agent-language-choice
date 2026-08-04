import hashlib
import json
import os
import re
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


DICE_RE = re.compile(r"^(\d+)d(\d+)(?:(\+|\-)(\d+))?$")
USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")

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

THRESHOLDS_BY_LEVEL = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

DIFFICULTIES = ["trivial", "easy", "medium", "hard", "deadly"]

DB_PATH = os.environ.get("DB_PATH", "game.db")
SCHEMA_VERSION = 1

COMBAT_CONDITIONS_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/conditions$")
COMBAT_ADVANCE_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/advance$")


class NotFoundError(Exception):
    pass


class AuthError(Exception):
    pass


class ConflictError(Exception):
    pass


def get_db():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS combat_sessions (
                id TEXT PRIMARY KEY,
                round INTEGER NOT NULL,
                turn_index INTEGER NOT NULL,
                order_json TEXT NOT NULL,
                conditions_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            )
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        conn.commit()
    finally:
        conn.close()


def is_initialized():
    if not os.path.exists(DB_PATH):
        return False
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name IN ('users', 'combat_sessions', 'schema_version')
            """
        ).fetchall()
        return len(rows) == 3
    finally:
        conn.close()


def json_response(handler, status, body):
    data = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def read_json_body(handler):
    length = int(handler.headers.get("Content-Length", 0))
    if length <= 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def _hash_password(password):
    salt = secrets.token_bytes(16)
    hashed = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32
    )
    return f"{salt.hex()}:{hashed.hex()}"


def _verify_password(password, stored):
    salt_hex, hash_hex = stored.split(":")
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(hash_hex)
    actual = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32
    )
    return secrets.compare_digest(actual, expected)


def _require_valid_username(value):
    if not isinstance(value, str) or not USERNAME_RE.match(value):
        raise ValueError("invalid username")
    return value


def _require_valid_password(value):
    if not isinstance(value, str) or len(value) < 8:
        raise ValueError("password must be at least 8 characters")
    return value


def _require_valid_role(value):
    if value not in ("dm", "player"):
        raise ValueError("role must be dm or player")
    return value


def register_user(body):
    username = _require_valid_username(body.get("username"))
    password = _require_valid_password(body.get("password"))
    role = _require_valid_role(body.get("role"))
    conn = get_db()
    try:
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, _hash_password(password), role),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ConflictError("username already exists")
    finally:
        conn.close()
    return {"username": username, "role": role}


def login_user(body):
    username = body.get("username")
    password = body.get("password")
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
    finally:
        conn.close()
    if row is None or not isinstance(password, str) or not _verify_password(
        password, row[0]
    ):
        raise AuthError("invalid credentials")
    return {"username": username, "token": f"session-{username}"}


def dice_stats(body):
    expression = body.get("expression", "")
    match = DICE_RE.match(expression)
    if not match:
        raise ValueError("invalid expression")
    count = int(match.group(1))
    sides = int(match.group(2))
    if count <= 0 or sides <= 0:
        raise ValueError("count and sides must be positive")
    modifier = 0
    sign = match.group(3)
    if sign:
        mod = int(match.group(4))
        modifier = mod if sign == "+" else -mod
    min_total = count + modifier
    max_total = count * sides + modifier
    average_raw = (min_total + max_total) / 2
    average = int(average_raw) if average_raw.is_integer() else average_raw
    return {
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": min_total,
        "max": max_total,
        "average": average,
    }


def ability_check(body):
    roll = int(body["roll"])
    modifier = int(body["modifier"])
    dc = int(body["dc"])
    total = roll + modifier
    return {"total": total, "success": total >= dc, "margin": total - dc}


def monster_multiplier(count):
    if count == 1:
        return 1
    if count == 2:
        return 1.5
    if count <= 6:
        return 2
    if count <= 10:
        return 2.5
    if count <= 14:
        return 3
    return 4


def encounter_adjusted_xp(body):
    party = body["party"]
    monsters = body["monsters"]

    base_xp = 0
    monster_count = 0
    for m in monsters:
        cr = m["cr"]
        count = int(m["count"])
        if cr not in XP_BY_CR:
            raise ValueError(f"unsupported CR: {cr}")
        if count <= 0:
            raise ValueError("monster count must be positive")
        base_xp += XP_BY_CR[cr] * count
        monster_count += count

    multiplier = monster_multiplier(monster_count)
    adjusted_xp = int(base_xp * multiplier)

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = int(member["level"])
        level_thresholds = THRESHOLDS_BY_LEVEL.get(level)
        if level_thresholds is None:
            raise ValueError(f"unsupported level: {level}")
        for key in thresholds:
            thresholds[key] += level_thresholds[key]

    difficulty = "trivial"
    for candidate in ["easy", "medium", "hard", "deadly"]:
        if adjusted_xp >= thresholds[candidate]:
            difficulty = candidate

    return {
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": multiplier,
        "adjusted_xp": adjusted_xp,
        "difficulty": difficulty,
        "thresholds": thresholds,
    }


def initiative_order(body):
    combatants = body["combatants"]
    scored = []
    for c in combatants:
        score = int(c["roll"]) + int(c["dex"])
        scored.append((c["name"], int(c["dex"]), score))
    scored.sort(key=lambda item: (-item[2], -item[1], item[0]))
    return {"order": [{"name": name, "score": score} for name, _, score in scored]}


ABILITIES = ["str", "dex", "con", "int", "wis", "cha"]


def modifier_for_score(score):
    return (score - 10) // 2


def proficiency_bonus_for_level(level):
    if level <= 4:
        return 2
    if level <= 8:
        return 3
    if level <= 12:
        return 4
    if level <= 16:
        return 5
    return 6


def require_int(value, name, minimum=None, maximum=None):
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return value


def require_str(value, name):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def require_positive_int(value, name):
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def ability_modifier(body):
    score = require_int(body.get("score"), "score", 1, 30)
    return {"score": score, "modifier": modifier_for_score(score)}


def proficiency_bonus(body):
    level = require_int(body.get("level"), "level", 1, 20)
    return {"level": level, "proficiency_bonus": proficiency_bonus_for_level(level)}


def derived_stats(body):
    level = require_int(body.get("level"), "level", 1, 20)

    abilities = body.get("abilities", {})
    modifiers = {}
    for ab in ABILITIES:
        score = require_int(abilities.get(ab), ab, 1, 30)
        modifiers[ab] = modifier_for_score(score)

    armor = body.get("armor", {})
    base = require_int(armor.get("base"), "armor.base", 0)
    dex_cap = require_int(armor.get("dex_cap"), "armor.dex_cap", 0)
    shield = bool(armor.get("shield", False))
    shield_bonus = 2 if shield else 0
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus

    proficiency = proficiency_bonus_for_level(level)
    hp_max = level * (6 + modifiers["con"])

    return {
        "level": level,
        "proficiency_bonus": proficiency,
        "hp_max": hp_max,
        "armor_class": armor_class,
        "modifiers": modifiers,
    }


def _load_session(conn, session_id):
    row = conn.execute(
        "SELECT round, turn_index, order_json, conditions_json FROM combat_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("session not found")
    return {
        "id": session_id,
        "round": row[0],
        "turn_index": row[1],
        "order": json.loads(row[2]),
        "conditions": json.loads(row[3]),
    }


def _save_session(conn, session):
    order_json = json.dumps(session["order"])
    conditions_json = json.dumps(session["conditions"])
    conn.execute(
        "INSERT OR REPLACE INTO combat_sessions (id, round, turn_index, order_json, conditions_json) VALUES (?, ?, ?, ?, ?)",
        (session["id"], session["round"], session["turn_index"], order_json, conditions_json),
    )


def create_combat_session(body):
    session_id = require_str(body.get("id"), "id")
    combatants = body.get("combatants")
    if not isinstance(combatants, list) or not combatants:
        raise ValueError("combatants must be a non-empty list")

    scored = []
    for c in combatants:
        name = require_str(c.get("name"), "combatant name")
        dex = require_int(c.get("dex"), "dex")
        roll = require_int(c.get("roll"), "roll")
        scored.append((name, dex, roll + dex))

    scored.sort(key=lambda item: (-item[2], -item[1], item[0]))
    order = [{"name": name, "score": score} for name, _, score in scored]

    session = {
        "id": session_id,
        "round": 1,
        "turn_index": 0,
        "order": order,
        "conditions": {name: [] for name, _, _ in scored},
    }

    conn = get_db()
    try:
        try:
            _save_session(conn, session)
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("session id already exists")
    finally:
        conn.close()

    return {
        "id": session_id,
        "round": 1,
        "turn_index": 0,
        "active": order[0],
        "order": order,
    }


def add_condition(session_id, body):
    conn = get_db()
    try:
        session = _load_session(conn, session_id)
        target = require_str(body.get("target"), "target")
        if target not in session["conditions"]:
            raise ValueError("target not found in combatants")
        condition = require_str(body.get("condition"), "condition")
        duration = require_positive_int(body.get("duration_rounds"), "duration_rounds")
        session["conditions"][target].append(
            {"condition": condition, "remaining_rounds": duration}
        )
        _save_session(conn, session)
        conn.commit()
    finally:
        conn.close()
    return {"target": target, "conditions": session["conditions"][target]}


def advance_turn(session_id):
    conn = get_db()
    try:
        session = _load_session(conn, session_id)
        order = session["order"]
        turn_index = session["turn_index"] + 1
        round_num = session["round"]
        if turn_index >= len(order):
            turn_index = 0
            round_num += 1
        session["turn_index"] = turn_index
        session["round"] = round_num
        active = order[turn_index]
        active_name = active["name"]

        updated = []
        for cond in session["conditions"].get(active_name, []):
            remaining = cond["remaining_rounds"] - 1
            if remaining > 0:
                updated.append({"condition": cond["condition"], "remaining_rounds": remaining})
        session["conditions"][active_name] = updated

        conditions_out = {name: conds for name, conds in session["conditions"].items() if conds}
        if active_name not in conditions_out:
            conditions_out[active_name] = []
        _save_session(conn, session)
        conn.commit()
    finally:
        conn.close()
    return {
        "id": session_id,
        "round": round_num,
        "turn_index": turn_index,
        "active": active,
        "conditions": conditions_out,
    }


def storage_status():
    return {
        "driver": "sqlite",
        "schema_version": SCHEMA_VERSION,
        "initialized": is_initialized(),
    }


def storage_reset():
    conn = get_db()
    try:
        conn.execute("DROP TABLE IF EXISTS users")
        conn.execute("DROP TABLE IF EXISTS combat_sessions")
        conn.execute("DROP TABLE IF EXISTS schema_version")
        conn.commit()
    finally:
        conn.close()
    init_db()
    return {"ok": True, "schema_version": SCHEMA_VERSION}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            json_response(self, 200, {"ok": True})
        elif self.path == "/v1/storage/status":
            json_response(self, 200, storage_status())
        else:
            json_response(self, 404, {"error": "not found"})

    def do_POST(self):
        try:
            path = self.path.split("?")[0]
            body = read_json_body(self)
            if path == "/v1/dice/stats":
                result = dice_stats(body)
            elif path == "/v1/checks/ability":
                result = ability_check(body)
            elif path == "/v1/encounters/adjusted-xp":
                result = encounter_adjusted_xp(body)
            elif path == "/v1/initiative/order":
                result = initiative_order(body)
            elif path == "/v1/characters/ability-modifier":
                result = ability_modifier(body)
            elif path == "/v1/characters/proficiency":
                result = proficiency_bonus(body)
            elif path == "/v1/characters/derived-stats":
                result = derived_stats(body)
            elif path == "/v1/combat/sessions":
                result = create_combat_session(body)
            elif (match := COMBAT_CONDITIONS_RE.match(path)):
                result = add_condition(match.group(1), body)
            elif (match := COMBAT_ADVANCE_RE.match(path)):
                result = advance_turn(match.group(1))
            elif path == "/v1/auth/register":
                result = register_user(body)
                json_response(self, 201, result)
                return
            elif path == "/v1/auth/login":
                result = login_user(body)
            elif path == "/v1/storage/reset":
                result = storage_reset()
            else:
                json_response(self, 404, {"error": "not found"})
                return
            json_response(self, 200, result)
        except NotFoundError as exc:
            json_response(self, 404, {"error": str(exc)})
        except ConflictError as exc:
            json_response(self, 409, {"error": str(exc)})
        except AuthError as exc:
            json_response(self, 401, {"error": str(exc)})
        except Exception as exc:
            json_response(self, 400, {"error": str(exc)})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8080))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Serving on 127.0.0.1:{port}")
    server.serve_forever()
