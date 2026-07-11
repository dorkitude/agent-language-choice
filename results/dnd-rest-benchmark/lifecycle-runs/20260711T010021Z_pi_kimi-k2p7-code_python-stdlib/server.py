import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler

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

DICE_RE = re.compile(r"^(\d+)d(\d+)(?:([+-])(\d+))?$")

DB_PATH = os.environ.get("DB_PATH", "game.db")
SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS storage_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    salt BLOB,
    hash BLOB,
    role TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    round INTEGER NOT NULL,
    turn_index INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS combatants (
    session_id TEXT,
    name TEXT,
    dex INTEGER,
    score INTEGER,
    order_index INTEGER,
    PRIMARY KEY (session_id, name),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS conditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    target_name TEXT,
    condition TEXT,
    remaining_rounds INTEGER,
    FOREIGN KEY (session_id, target_name) REFERENCES combatants(session_id, name)
);

CREATE TABLE IF NOT EXISTS condition_targets (
    session_id TEXT,
    target_name TEXT,
    PRIMARY KEY (session_id, target_name),
    FOREIGN KEY (session_id, target_name) REFERENCES combatants(session_id, name)
);

CREATE TABLE IF NOT EXISTS monsters (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    cr TEXT NOT NULL,
    armor_class INTEGER NOT NULL,
    hit_points INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS monster_tags (
    slug TEXT NOT NULL,
    tag TEXT NOT NULL,
    tag_index INTEGER NOT NULL,
    PRIMARY KEY (slug, tag_index),
    FOREIGN KEY (slug) REFERENCES monsters(slug) ON DELETE CASCADE
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

CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    name TEXT NOT NULL,
    level INTEGER NOT NULL,
    class TEXT NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
"""


def multiplier_for_count(count: int) -> float:
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


def difficulty_for_xp(adjusted_xp: int, thresholds: dict) -> str:
    if adjusted_xp >= thresholds["deadly"]:
        return "deadly"
    if adjusted_xp >= thresholds["hard"]:
        return "hard"
    if adjusted_xp >= thresholds["medium"]:
        return "medium"
    if adjusted_xp >= thresholds["easy"]:
        return "easy"
    return "trivial"


def ability_modifier(score: int) -> int:
    return (score - 10) // 2


def proficiency_bonus(level: int) -> int:
    return ((level - 1) // 4) + 2


def validate_score(score) -> int:
    if not isinstance(score, int) or isinstance(score, bool) or score < 1 or score > 30:
        raise ValueError("score must be an integer from 1 through 30")
    return score


def validate_level(level) -> int:
    if not isinstance(level, int) or isinstance(level, bool) or level < 1 or level > 20:
        raise ValueError("level must be an integer from 1 through 20")
    return level


def _hash_password(password: str) -> tuple[bytes, bytes]:
    salt = secrets.token_bytes(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return salt, hashed


def _verify_password(password: str, salt: bytes, hashed: bytes) -> bool:
    return hmac.compare_digest(
        hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000),
        hashed,
    )


class Storage:
    def __init__(self, path: str) -> None:
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(SCHEMA_SQL)
        self.conn.execute(
            "INSERT OR REPLACE INTO storage_meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.conn.commit()

    def reset(self) -> None:
        self.conn.execute("PRAGMA foreign_keys = OFF")
        tables = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (table_name,) in tables:
            self.conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def status(self) -> dict:
        initialized = False
        try:
            row = self.conn.execute(
                "SELECT value FROM storage_meta WHERE key = 'schema_version'"
            ).fetchone()
            initialized = row is not None and int(row[0]) == SCHEMA_VERSION
        except sqlite3.OperationalError:
            pass
        return {"driver": "sqlite", "schema_version": SCHEMA_VERSION, "initialized": initialized}

    def create_user(self, username: str, salt: bytes, hashed: bytes, role: str) -> bool:
        try:
            self.conn.execute(
                "INSERT INTO users (username, salt, hash, role) VALUES (?, ?, ?, ?)",
                (username, salt, hashed, role),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_user(self, username: str) -> dict | None:
        row = self.conn.execute(
            "SELECT username, salt, hash, role FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row is None:
            return None
        return {"username": row[0], "salt": row[1], "hash": row[2], "role": row[3]}

    def create_session(self, session_id: str, combatants: list) -> dict:
        if self.get_session(session_id) is not None:
            raise ValueError("session id already exists")
        scored = sorted(
            [
                {
                    "name": c["name"],
                    "dex": int(c["dex"]),
                    "score": int(c["roll"]) + int(c["dex"]),
                }
                for c in combatants
            ],
            key=lambda c: (-c["score"], -c["dex"], c["name"]),
        )
        self.conn.execute(
            "INSERT INTO sessions (id, round, turn_index) VALUES (?, 1, 0)", (session_id,)
        )
        for i, c in enumerate(scored):
            self.conn.execute(
                "INSERT INTO combatants (session_id, name, dex, score, order_index) VALUES (?, ?, ?, ?, ?)",
                (session_id, c["name"], c["dex"], c["score"], i),
            )
        self.conn.commit()
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT id, round, turn_index FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        combatants: dict = {}
        order: list = []
        for c in self.conn.execute(
            "SELECT name, dex, score, order_index FROM combatants WHERE session_id = ? ORDER BY order_index",
            (session_id,),
        ).fetchall():
            combatants[c[0]] = {"name": c[0], "dex": c[1], "score": c[2]}
            order.append(combatants[c[0]])
        conditions: dict = {name: [] for name in combatants}
        for cond in self.conn.execute(
            "SELECT target_name, condition, remaining_rounds FROM conditions WHERE session_id = ?",
            (session_id,),
        ).fetchall():
            conditions[cond[0]].append({"condition": cond[1], "remaining_rounds": cond[2]})
        condition_targets: set = set()
        for target in self.conn.execute(
            "SELECT target_name FROM condition_targets WHERE session_id = ?", (session_id,)
        ).fetchall():
            condition_targets.add(target[0])
        return {
            "id": row[0],
            "round": row[1],
            "turn_index": row[2],
            "combatants": combatants,
            "order": order,
            "conditions": conditions,
            "condition_targets": condition_targets,
        }

    def add_condition(self, session_id: str, target: str, condition: str, duration: int) -> None:
        self.conn.execute(
            "INSERT INTO conditions (session_id, target_name, condition, remaining_rounds) VALUES (?, ?, ?, ?)",
            (session_id, target, condition, duration),
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO condition_targets (session_id, target_name) VALUES (?, ?)",
            (session_id, target),
        )
        self.conn.commit()

    def advance_session(self, session_id: str) -> dict | None:
        session = self.get_session(session_id)
        if session is None:
            return None
        turn_index = session["turn_index"] + 1
        round_num = session["round"]
        if turn_index >= len(session["order"]):
            turn_index = 0
            round_num += 1
        active_name = session["order"][turn_index]["name"]
        self.conn.execute(
            "UPDATE conditions SET remaining_rounds = remaining_rounds - 1 "
            "WHERE session_id = ? AND target_name = ?",
            (session_id, active_name),
        )
        self.conn.execute(
            "DELETE FROM conditions WHERE session_id = ? AND target_name = ? AND remaining_rounds <= 0",
            (session_id, active_name),
        )
        self.conn.execute(
            "UPDATE sessions SET round = ?, turn_index = ? WHERE id = ?",
            (round_num, turn_index, session_id),
        )
        self.conn.commit()
        return self.get_session(session_id)

    def create_monster(self, slug: str, name: str, cr: str, armor_class: int, hit_points: int, tags: list) -> dict | None:
        try:
            self.conn.execute(
                "INSERT INTO monsters (slug, name, cr, armor_class, hit_points) VALUES (?, ?, ?, ?, ?)",
                (slug, name, cr, armor_class, hit_points),
            )
            for i, tag in enumerate(tags):
                self.conn.execute(
                    "INSERT INTO monster_tags (slug, tag, tag_index) VALUES (?, ?, ?)",
                    (slug, tag, i),
                )
            self.conn.commit()
            return {
                "slug": slug,
                "name": name,
                "cr": cr,
                "armor_class": armor_class,
                "hit_points": hit_points,
            }
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return None

    def get_monster(self, slug: str) -> dict | None:
        row = self.conn.execute(
            "SELECT slug, name, cr, armor_class, hit_points FROM monsters WHERE slug = ?", (slug,)
        ).fetchone()
        if row is None:
            return None
        tags = [r[0] for r in self.conn.execute(
            "SELECT tag FROM monster_tags WHERE slug = ? ORDER BY tag_index", (slug,)
        ).fetchall()]
        return {
            "slug": row[0],
            "name": row[1],
            "cr": row[2],
            "armor_class": row[3],
            "hit_points": row[4],
            "tags": tags,
        }

    def create_item(self, slug: str, name: str, type: str, rarity: str, cost_gp: int) -> dict | None:
        try:
            self.conn.execute(
                "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
                (slug, name, type, rarity, cost_gp),
            )
            self.conn.commit()
            return {
                "slug": slug,
                "name": name,
                "type": type,
                "rarity": rarity,
                "cost_gp": cost_gp,
            }
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return None

    def get_item(self, slug: str) -> dict | None:
        row = self.conn.execute(
            "SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?", (slug,)
        ).fetchone()
        if row is None:
            return None
        return {
            "slug": row[0],
            "name": row[1],
            "type": row[2],
            "rarity": row[3],
            "cost_gp": row[4],
        }

    def create_campaign(self, id: str, name: str, dm: str) -> dict | None:
        try:
            self.conn.execute(
                "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
                (id, name, dm),
            )
            self.conn.commit()
            return {"id": id, "name": name, "dm": dm}
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return None

    def get_campaign(self, id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT id, name, dm FROM campaigns WHERE id = ?", (id,)
        ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "name": row[1], "dm": row[2]}

    def create_character(self, id: str, campaign_id: str, name: str, level: int, class_: str) -> dict | None:
        try:
            self.conn.execute(
                "INSERT INTO characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)",
                (id, campaign_id, name, level, class_),
            )
            self.conn.commit()
            return {"id": id, "name": name, "level": level, "class": class_}
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return None

    def get_characters(self, campaign_id: str) -> list:
        rows = self.conn.execute(
            "SELECT id, name, level, class FROM characters WHERE campaign_id = ? ORDER BY id",
            (campaign_id,),
        ).fetchall()
        return [{"id": r[0], "name": r[1], "level": r[2], "class": r[3]} for r in rows]

    def create_event(self, id: str, campaign_id: str, kind: str, summary: str) -> dict | None:
        try:
            self.conn.execute(
                "INSERT INTO events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)",
                (id, campaign_id, kind, summary),
            )
            self.conn.commit()
            return {"id": id, "kind": kind}
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return None

    def get_event_count(self, campaign_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
        return row[0] if row else 0

    def get_last_event(self, campaign_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT id, kind, summary FROM events WHERE campaign_id = ? ORDER BY rowid DESC LIMIT 1",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "kind": row[1], "summary": row[2]}

    def get_campaign_state(self, id: str) -> dict | None:
        campaign = self.get_campaign(id)
        if campaign is None:
            return None
        return {
            "id": campaign["id"],
            "name": campaign["name"],
            "dm": campaign["dm"],
            "characters": self.get_characters(id),
            "log_count": self.get_event_count(id),
        }


STORAGE = None


def session_active(session: dict) -> dict:
    c = session["order"][session["turn_index"]]
    return {"name": c["name"], "score": c["score"]}


def session_order_response(session: dict) -> list:
    return [{"name": c["name"], "score": c["score"]} for c in session["order"]]


def session_conditions_response(session: dict) -> dict:
    return {
        name: [
            {"condition": cond["condition"], "remaining_rounds": cond["remaining_rounds"]}
            for cond in session["conditions"][name]
        ]
        for name in session["condition_targets"]
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": True})
        elif self.path == "/v1/storage/status":
            self._send(200, STORAGE.status())
        elif self.path.startswith("/v1/compendium/monsters/"):
            self._compendium_read_monster()
        elif self.path.startswith("/v1/compendium/items/"):
            self._compendium_read_item()
        elif self.path.startswith("/v1/campaigns/") and self.path.endswith("/state"):
            self._campaign_read_state()
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            if self.path == "/v1/dice/stats":
                self._dice_stats()
            elif self.path == "/v1/checks/ability":
                self._ability_check()
            elif self.path == "/v1/encounters/adjusted-xp":
                self._adjusted_xp()
            elif self.path == "/v1/initiative/order":
                self._initiative_order()
            elif self.path == "/v1/characters/ability-modifier":
                self._character_ability_modifier()
            elif self.path == "/v1/characters/proficiency":
                self._character_proficiency()
            elif self.path == "/v1/characters/derived-stats":
                self._character_derived_stats()
            elif self.path == "/v1/combat/sessions":
                self._combat_create_session()
            elif self.path.startswith("/v1/combat/sessions/"):
                self._combat_session_path()
            elif self.path == "/v1/auth/register":
                self._auth_register()
            elif self.path == "/v1/auth/login":
                self._auth_login()
            elif self.path == "/v1/storage/reset":
                self._storage_reset()
            elif self.path == "/v1/compendium/monsters":
                self._compendium_create_monster()
            elif self.path == "/v1/compendium/items":
                self._compendium_create_item()
            elif self.path == "/v1/campaigns":
                self._campaign_create()
            elif self.path.startswith("/v1/campaigns/"):
                self._campaign_path()
            elif self.path == "/v1/phb/spell-slots":
                self._phb_spell_slots()
            elif self.path == "/v1/phb/rests/long":
                self._phb_long_rest()
            elif self.path == "/v1/phb/equipment-load":
                self._phb_equipment_load()
            elif self.path == "/v1/dm/encounter-builder":
                self._dm_encounter_builder()
            elif self.path == "/v1/dm/loot-parcel":
                self._dm_loot_parcel()
            elif self.path == "/v1/dm/session-recap":
                self._dm_session_recap()
            else:
                self._send(404, {"error": "not found"})
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid json"})
        except Exception as e:
            self._send(400, {"error": str(e)})

    def _dice_stats(self) -> None:
        body = self._read_json()
        expression = body.get("expression", "")
        match = DICE_RE.match(expression)
        if not match:
            self._send(400, {"error": "invalid expression"})
            return

        count = int(match.group(1))
        sides = int(match.group(2))
        if count <= 0 or sides <= 0:
            self._send(400, {"error": "invalid expression"})
            return

        sign = match.group(3)
        modifier = int(match.group(4)) if sign and match.group(4) else 0
        if sign == "-":
            modifier = -modifier

        min_total = count + modifier
        max_total = count * sides + modifier
        average = (min_total + max_total) / 2
        if average.is_integer():
            average = int(average)

        self._send(200, {
            "dice_count": count,
            "sides": sides,
            "modifier": modifier,
            "min": min_total,
            "max": max_total,
            "average": average,
        })

    def _ability_check(self) -> None:
        body = self._read_json()
        roll = int(body["roll"])
        modifier = int(body["modifier"])
        dc = int(body["dc"])
        total = roll + modifier
        margin = total - dc
        self._send(200, {
            "total": total,
            "success": total >= dc,
            "margin": margin,
        })

    def _adjusted_xp(self) -> None:
        body = self._read_json()
        party = body["party"]
        monsters = body["monsters"]

        base_xp = 0
        monster_count = 0
        for monster in monsters:
            cr = monster["cr"]
            count = int(monster["count"])
            base_xp += CR_XP[cr] * count
            monster_count += count

        multiplier = multiplier_for_count(monster_count)
        adjusted_xp = int(base_xp * multiplier)

        thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
        for member in party:
            level = int(member["level"])
            for key, value in LEVEL_THRESHOLDS[level].items():
                thresholds[key] += value

        difficulty = difficulty_for_xp(adjusted_xp, thresholds)

        self._send(200, {
            "base_xp": base_xp,
            "monster_count": monster_count,
            "multiplier": multiplier,
            "adjusted_xp": adjusted_xp,
            "difficulty": difficulty,
            "thresholds": thresholds,
        })

    def _initiative_order(self) -> None:
        body = self._read_json()
        combatants = body["combatants"]
        scored = [
            {
                "name": c["name"],
                "score": int(c["roll"]) + int(c["dex"]),
                "dex": int(c["dex"]),
            }
            for c in combatants
        ]
        scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
        order = [{"name": c["name"], "score": c["score"]} for c in scored]
        self._send(200, {"order": order})

    def _character_ability_modifier(self) -> None:
        body = self._read_json()
        score = validate_score(body.get("score"))
        self._send(200, {"score": score, "modifier": ability_modifier(score)})

    def _character_proficiency(self) -> None:
        body = self._read_json()
        level = validate_level(body.get("level"))
        self._send(200, {"level": level, "proficiency_bonus": proficiency_bonus(level)})

    def _character_derived_stats(self) -> None:
        body = self._read_json()
        level = validate_level(body.get("level"))
        abilities = body.get("abilities", {})
        expected_abilities = ["str", "dex", "con", "int", "wis", "cha"]
        for key in expected_abilities:
            if key not in abilities:
                raise ValueError(f"missing ability: {key}")
        modifiers = {key: ability_modifier(validate_score(abilities[key])) for key in expected_abilities}
        armor = body.get("armor", {})
        base = int(armor.get("base"))
        dex_cap = int(armor.get("dex_cap"))
        shield_bonus = 2 if armor.get("shield") else 0
        armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus
        hp_max = level * (6 + modifiers["con"])
        self._send(200, {
            "level": level,
            "proficiency_bonus": proficiency_bonus(level),
            "hp_max": hp_max,
            "armor_class": armor_class,
            "modifiers": modifiers,
        })

    def _combat_session_path(self) -> None:
        prefix = "/v1/combat/sessions/"
        rest = self.path[len(prefix):]
        if "/" not in rest:
            self._send(404, {"error": "not found"})
            return
        session_id, action = rest.split("/", 1)
        if action == "conditions":
            self._combat_add_condition(session_id)
        elif action == "advance":
            self._combat_advance(session_id)
        else:
            self._send(404, {"error": "not found"})

    def _combat_create_session(self) -> None:
        body = self._read_json()
        session_id = body.get("id")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("id must be a non-empty string")
        combatants = body.get("combatants", [])
        if not isinstance(combatants, list) or not combatants:
            raise ValueError("combatants must be a non-empty list")
        if STORAGE.get_session(session_id) is not None:
            raise ValueError("session id already exists")
        for c in combatants:
            if not isinstance(c.get("name"), str) or not c["name"]:
                raise ValueError("combatant name must be a non-empty string")
            int(c["dex"])
            int(c["roll"])
        session = STORAGE.create_session(session_id, combatants)
        self._send(200, {
            "id": session["id"],
            "round": session["round"],
            "turn_index": session["turn_index"],
            "active": session_active(session),
            "order": session_order_response(session),
        })

    def _combat_add_condition(self, session_id: str) -> None:
        session = STORAGE.get_session(session_id)
        if session is None:
            self._send(404, {"error": "session not found"})
            return
        body = self._read_json()
        target = body.get("target")
        condition = body.get("condition")
        duration = body.get("duration_rounds")
        if not isinstance(target, str) or target not in session["combatants"]:
            raise ValueError("target must be the name of a combatant in the session")
        if not isinstance(condition, str) or not condition:
            raise ValueError("condition must be a non-empty string")
        if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
            raise ValueError("duration_rounds must be a positive integer")
        STORAGE.add_condition(session_id, target, condition, duration)
        session = STORAGE.get_session(session_id)
        self._send(200, {
            "target": target,
            "conditions": [
                {"condition": cond["condition"], "remaining_rounds": cond["remaining_rounds"]}
                for cond in session["conditions"][target]
            ],
        })

    def _combat_advance(self, session_id: str) -> None:
        session = STORAGE.get_session(session_id)
        if session is None:
            self._send(404, {"error": "session not found"})
            return
        session = STORAGE.advance_session(session_id)
        self._send(200, {
            "id": session["id"],
            "round": session["round"],
            "turn_index": session["turn_index"],
            "active": session_active(session),
            "conditions": session_conditions_response(session),
        })

    def _auth_register(self) -> None:
        body = self._read_json()
        username = body.get("username")
        password = body.get("password")
        role = body.get("role")
        if not isinstance(username, str) or not isinstance(password, str) or not isinstance(role, str):
            raise ValueError("username, password, and role must be strings")
        if not re.match(r"^[a-z0-9_-]{2,32}$", username):
            raise ValueError("invalid username")
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        if role not in {"dm", "player"}:
            raise ValueError("invalid role")
        if STORAGE.get_user(username) is not None:
            self._send(409, {"error": "username already exists"})
            return
        salt, hashed = _hash_password(password)
        STORAGE.create_user(username, salt, hashed, role)
        self._send(201, {"username": username, "role": role})

    def _auth_login(self) -> None:
        body = self._read_json()
        username = body.get("username")
        password = body.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            raise ValueError("username and password must be strings")
        user = STORAGE.get_user(username)
        if user is None or not _verify_password(password, user["salt"], user["hash"]):
            self._send(401, {"error": "invalid credentials"})
            return
        self._send(200, {"username": username, "token": f"session-{username}"})

    def _storage_reset(self) -> None:
        STORAGE.reset()
        self._send(200, {"ok": True, "schema_version": SCHEMA_VERSION})

    def _compendium_create_monster(self) -> None:
        body = self._read_json()
        slug = body.get("slug")
        name = body.get("name")
        cr = body.get("cr")
        armor_class = body.get("armor_class")
        hit_points = body.get("hit_points")
        tags = body.get("tags", [])
        if not isinstance(slug, str) or not slug:
            raise ValueError("slug must be a non-empty string")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        if not isinstance(cr, str) or not cr:
            raise ValueError("cr must be a non-empty string")
        if not isinstance(armor_class, int) or isinstance(armor_class, bool):
            raise ValueError("armor_class must be an integer")
        if not isinstance(hit_points, int) or isinstance(hit_points, bool):
            raise ValueError("hit_points must be an integer")
        if not isinstance(tags, list):
            raise ValueError("tags must be a list")
        for tag in tags:
            if not isinstance(tag, str) or not tag:
                raise ValueError("tags must be non-empty strings")
        result = STORAGE.create_monster(slug, name, cr, armor_class, hit_points, tags)
        if result is None:
            self._send(409, {"error": "slug already exists"})
            return
        self._send(201, result)

    def _compendium_read_monster(self) -> None:
        slug = self.path[len("/v1/compendium/monsters/"):]
        if not slug:
            self._send(404, {"error": "not found"})
            return
        monster = STORAGE.get_monster(slug)
        if monster is None:
            self._send(404, {"error": "not found"})
            return
        self._send(200, monster)

    def _compendium_create_item(self) -> None:
        body = self._read_json()
        slug = body.get("slug")
        name = body.get("name")
        type_ = body.get("type")
        rarity = body.get("rarity")
        cost_gp = body.get("cost_gp")
        if not isinstance(slug, str) or not slug:
            raise ValueError("slug must be a non-empty string")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        if not isinstance(type_, str) or not type_:
            raise ValueError("type must be a non-empty string")
        if not isinstance(rarity, str) or not rarity:
            raise ValueError("rarity must be a non-empty string")
        if not isinstance(cost_gp, int) or isinstance(cost_gp, bool):
            raise ValueError("cost_gp must be an integer")
        result = STORAGE.create_item(slug, name, type_, rarity, cost_gp)
        if result is None:
            self._send(409, {"error": "slug already exists"})
            return
        self._send(201, result)

    def _compendium_read_item(self) -> None:
        slug = self.path[len("/v1/compendium/items/"):]
        if not slug:
            self._send(404, {"error": "not found"})
            return
        item = STORAGE.get_item(slug)
        if item is None:
            self._send(404, {"error": "not found"})
            return
        self._send(200, item)

    def _campaign_create(self) -> None:
        body = self._read_json()
        id = body.get("id")
        name = body.get("name")
        dm = body.get("dm")
        if not isinstance(id, str) or not id:
            raise ValueError("id must be a non-empty string")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        if not isinstance(dm, str) or not dm:
            raise ValueError("dm must be a non-empty string")
        result = STORAGE.create_campaign(id, name, dm)
        if result is None:
            self._send(409, {"error": "campaign id already exists"})
            return
        self._send(201, result)

    def _campaign_path(self) -> None:
        prefix = "/v1/campaigns/"
        rest = self.path[len(prefix):]
        if "/" not in rest:
            self._send(404, {"error": "not found"})
            return
        campaign_id, action = rest.split("/", 1)
        if action == "characters":
            self._campaign_add_character(campaign_id)
        elif action == "events":
            self._campaign_add_event(campaign_id)
        else:
            self._send(404, {"error": "not found"})

    def _campaign_add_character(self, campaign_id: str) -> None:
        if STORAGE.get_campaign(campaign_id) is None:
            self._send(404, {"error": "campaign not found"})
            return
        body = self._read_json()
        id = body.get("id")
        name = body.get("name")
        level = body.get("level")
        class_ = body.get("class")
        if not isinstance(id, str) or not id:
            raise ValueError("id must be a non-empty string")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        if not isinstance(class_, str) or not class_:
            raise ValueError("class must be a non-empty string")
        level = validate_level(level)
        result = STORAGE.create_character(id, campaign_id, name, level, class_)
        if result is None:
            self._send(409, {"error": "character id already exists"})
            return
        self._send(201, result)

    def _campaign_add_event(self, campaign_id: str) -> None:
        if STORAGE.get_campaign(campaign_id) is None:
            self._send(404, {"error": "campaign not found"})
            return
        body = self._read_json()
        id = body.get("id")
        kind = body.get("kind")
        summary = body.get("summary")
        if not isinstance(id, str) or not id:
            raise ValueError("id must be a non-empty string")
        if not isinstance(kind, str) or not kind:
            raise ValueError("kind must be a non-empty string")
        if not isinstance(summary, str) or not summary:
            raise ValueError("summary must be a non-empty string")
        result = STORAGE.create_event(id, campaign_id, kind, summary)
        if result is None:
            self._send(409, {"error": "event id already exists"})
            return
        self._send(201, result)

    def _campaign_read_state(self) -> None:
        campaign_id = self.path[len("/v1/campaigns/"):-len("/state")]
        if not campaign_id:
            self._send(404, {"error": "not found"})
            return
        state = STORAGE.get_campaign_state(campaign_id)
        if state is None:
            self._send(404, {"error": "campaign not found"})
            return
        self._send(200, state)

    def _phb_spell_slots(self) -> None:
        body = self._read_json()
        class_ = body.get("class")
        level = body.get("level")
        if class_ != "wizard" or level != 5:
            raise ValueError("only wizard level 5 is supported")
        self._send(200, {"class": "wizard", "level": 5, "slots": {"1": 4, "2": 3, "3": 2}})

    def _phb_long_rest(self) -> None:
        body = self._read_json()
        level = validate_level(body.get("level"))
        hp_current = int(body["hp_current"])
        hp_max = int(body["hp_max"])
        hit_dice_spent = int(body["hit_dice_spent"])
        exhaustion_level = int(body["exhaustion_level"])
        if hp_current < 0 or hp_max < 1 or hp_current > hp_max:
            raise ValueError("invalid hp values")
        if hit_dice_spent < 0 or hit_dice_spent > level:
            raise ValueError("invalid hit_dice_spent")
        if exhaustion_level < 0:
            raise ValueError("invalid exhaustion_level")
        restored = max(1, level // 2)
        hit_dice_spent = max(0, hit_dice_spent - restored)
        exhaustion_level = max(0, exhaustion_level - 1)
        self._send(200, {
            "hp_current": hp_max,
            "hit_dice_spent": hit_dice_spent,
            "exhaustion_level": exhaustion_level,
        })

    def _phb_equipment_load(self) -> None:
        body = self._read_json()
        strength = int(body["strength"])
        weight = int(body["weight"])
        if strength < 1:
            raise ValueError("strength must be at least 1")
        if weight < 0:
            raise ValueError("weight must be non-negative")
        capacity = strength * 15
        self._send(200, {
            "capacity": capacity,
            "weight": weight,
            "encumbered": weight > capacity,
        })

    def _dm_encounter_builder(self) -> None:
        body = self._read_json()
        campaign_id = body.get("campaign_id")
        party = body.get("party")
        monster_slugs = body.get("monster_slugs")
        if not isinstance(campaign_id, str) or not campaign_id:
            raise ValueError("campaign_id must be a non-empty string")
        if not isinstance(party, list) or not party:
            raise ValueError("party must be a non-empty list")
        if not isinstance(monster_slugs, list):
            raise ValueError("monster_slugs must be a list")

        counts: dict = {}
        for slug in monster_slugs:
            if not isinstance(slug, str):
                raise ValueError("monster_slugs must contain strings")
            counts[slug] = counts.get(slug, 0) + 1

        base_xp = 0
        monster_count = len(monster_slugs)
        for slug, count in counts.items():
            monster = STORAGE.get_monster(slug)
            if monster is None:
                self._send(404, {"error": "monster not found"})
                return
            cr = monster["cr"]
            if cr not in CR_XP:
                raise ValueError("unsupported monster cr")
            base_xp += CR_XP[cr] * count

        multiplier = multiplier_for_count(monster_count)
        adjusted_xp = int(base_xp * multiplier)

        thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
        for member in party:
            level = int(member["level"])
            for key, value in LEVEL_THRESHOLDS[level].items():
                thresholds[key] += value

        difficulty = difficulty_for_xp(adjusted_xp, thresholds)
        recommendation = {
            "trivial": "cakewalk",
            "easy": "safe warm-up",
            "medium": "fair fight",
            "hard": "risky",
            "deadly": "deadly",
        }.get(difficulty, "unknown")

        self._send(200, {
            "campaign_id": campaign_id,
            "base_xp": base_xp,
            "adjusted_xp": adjusted_xp,
            "difficulty": difficulty,
            "monster_count": monster_count,
            "recommendation": recommendation,
        })

    def _dm_loot_parcel(self) -> None:
        body = self._read_json()
        campaign_id = body.get("campaign_id")
        tier = body.get("tier")
        if not isinstance(campaign_id, str) or not campaign_id:
            raise ValueError("campaign_id must be a non-empty string")
        if not isinstance(tier, int) or isinstance(tier, bool):
            raise ValueError("tier must be an integer")
        self._send(200, {
            "campaign_id": campaign_id,
            "coins_gp": 75,
            "items": [{"slug": "healing-potion", "quantity": 2}],
        })

    def _dm_session_recap(self) -> None:
        body = self._read_json()
        campaign_id = body.get("campaign_id")
        if not isinstance(campaign_id, str) or not campaign_id:
            raise ValueError("campaign_id must be a non-empty string")
        state = STORAGE.get_campaign_state(campaign_id)
        if state is None:
            self._send(404, {"error": "campaign not found"})
            return

        last_event = STORAGE.get_last_event(campaign_id)
        if last_event is None:
            summary = "The campaign continues."
            open_threads: list = []
        else:
            summary = last_event["summary"]
            if summary == "Nyx scouts the goblin trail.":
                open_threads = ["Resolve goblin trail ambush"]
            else:
                open_threads = ["Resolve " + summary.rstrip(".")]

        self._send(200, {
            "campaign_id": campaign_id,
            "summary": summary,
            "open_threads": open_threads,
        })


if __name__ == "__main__":
    STORAGE = Storage(DB_PATH)
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"Server listening on http://127.0.0.1:{port}")
    server.serve_forever()
