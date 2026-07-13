#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game.db")
SCHEMA_VERSION = 1

DB_LOCK = threading.Lock()
DB_CONN = sqlite3.connect(DB_PATH, check_same_thread=False)
DB_CONN.execute("PRAGMA journal_mode=WAL")


def init_schema():
    with DB_LOCK:
        DB_CONN.executescript(
            """
            CREATE TABLE IF NOT EXISTS storage_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                salt TEXT NOT NULL,
                hash TEXT NOT NULL
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
                name TEXT NOT NULL,
                dm TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS campaign_characters (
                campaign_id TEXT NOT NULL,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                level INTEGER NOT NULL,
                class TEXT NOT NULL,
                PRIMARY KEY (campaign_id, id)
            );
            CREATE TABLE IF NOT EXISTS campaign_events (
                campaign_id TEXT NOT NULL,
                id TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT,
                PRIMARY KEY (campaign_id, id)
            );
            """
        )
        DB_CONN.execute(
            "INSERT OR REPLACE INTO storage_meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        DB_CONN.execute(
            "INSERT OR REPLACE INTO storage_meta (key, value) VALUES ('initialized', '1')",
        )
        DB_CONN.commit()


def reset_schema():
    with DB_LOCK:
        DB_CONN.executescript(
            """
            DROP TABLE IF EXISTS users;
            DROP TABLE IF EXISTS combat_sessions;
            DROP TABLE IF EXISTS monsters;
            DROP TABLE IF EXISTS items;
            DROP TABLE IF EXISTS campaigns;
            DROP TABLE IF EXISTS campaign_characters;
            DROP TABLE IF EXISTS campaign_events;
            """
        )
        DB_CONN.commit()
    init_schema()


class UserStore:
    def __contains__(self, username):
        with DB_LOCK:
            row = DB_CONN.execute(
                "SELECT 1 FROM users WHERE username = ?", (username,)
            ).fetchone()
        return row is not None

    def get(self, username):
        with DB_LOCK:
            row = DB_CONN.execute(
                "SELECT role, salt, hash FROM users WHERE username = ?", (username,)
            ).fetchone()
        if row is None:
            return None
        return {"role": row[0], "salt": row[1], "hash": row[2]}

    def __setitem__(self, username, value):
        with DB_LOCK:
            DB_CONN.execute(
                "INSERT OR REPLACE INTO users (username, role, salt, hash) VALUES (?, ?, ?, ?)",
                (username, value["role"], value["salt"], value["hash"]),
            )
            DB_CONN.commit()


class CombatSessionStore:
    def __contains__(self, session_id):
        with DB_LOCK:
            row = DB_CONN.execute(
                "SELECT 1 FROM combat_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return row is not None

    def get(self, session_id):
        with DB_LOCK:
            row = DB_CONN.execute(
                "SELECT data FROM combat_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def __setitem__(self, session_id, value):
        with DB_LOCK:
            DB_CONN.execute(
                "INSERT OR REPLACE INTO combat_sessions (id, data) VALUES (?, ?)",
                (session_id, json.dumps(value)),
            )
            DB_CONN.commit()


class SlugStore:
    def __init__(self, table):
        self.table = table

    def __contains__(self, slug):
        with DB_LOCK:
            row = DB_CONN.execute(
                f"SELECT 1 FROM {self.table} WHERE slug = ?", (slug,)
            ).fetchone()
        return row is not None

    def get(self, slug):
        with DB_LOCK:
            row = DB_CONN.execute(
                f"SELECT data FROM {self.table} WHERE slug = ?", (slug,)
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def __setitem__(self, slug, value):
        with DB_LOCK:
            DB_CONN.execute(
                f"INSERT OR REPLACE INTO {self.table} (slug, data) VALUES (?, ?)",
                (slug, json.dumps(value)),
            )
            DB_CONN.commit()


class CampaignStore:
    def __contains__(self, campaign_id):
        with DB_LOCK:
            row = DB_CONN.execute(
                "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
        return row is not None

    def get(self, campaign_id):
        with DB_LOCK:
            row = DB_CONN.execute(
                "SELECT id, name, dm FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "name": row[1], "dm": row[2]}

    def create(self, campaign_id, name, dm):
        with DB_LOCK:
            DB_CONN.execute(
                "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
                (campaign_id, name, dm),
            )
            DB_CONN.commit()

    def add_character(self, campaign_id, char_id, name, level, char_class):
        with DB_LOCK:
            DB_CONN.execute(
                "INSERT INTO campaign_characters (campaign_id, id, name, level, class) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, char_id, name, level, char_class),
            )
            DB_CONN.commit()

    def character_exists(self, campaign_id, char_id):
        with DB_LOCK:
            row = DB_CONN.execute(
                "SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?",
                (campaign_id, char_id),
            ).fetchone()
        return row is not None

    def list_characters(self, campaign_id):
        with DB_LOCK:
            rows = DB_CONN.execute(
                "SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid",
                (campaign_id,),
            ).fetchall()
        return [{"id": r[0], "name": r[1], "level": r[2], "class": r[3]} for r in rows]

    def add_event(self, campaign_id, event_id, kind, summary):
        with DB_LOCK:
            DB_CONN.execute(
                "INSERT INTO campaign_events (campaign_id, id, kind, summary) VALUES (?, ?, ?, ?)",
                (campaign_id, event_id, kind, summary),
            )
            DB_CONN.commit()

    def event_exists(self, campaign_id, event_id):
        with DB_LOCK:
            row = DB_CONN.execute(
                "SELECT 1 FROM campaign_events WHERE campaign_id = ? AND id = ?",
                (campaign_id, event_id),
            ).fetchone()
        return row is not None

    def event_count(self, campaign_id):
        with DB_LOCK:
            row = DB_CONN.execute(
                "SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        return row[0]


MONSTER_XP = {
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

DIFFICULTY_RECOMMENDATION = {
    "trivial": "trivial encounter",
    "easy": "safe warm-up",
    "medium": "balanced challenge",
    "hard": "tough fight",
    "deadly": "deadly encounter",
}

DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")

COMBAT_SESSIONS = CombatSessionStore()

USERS = UserStore()

MONSTERS = SlugStore("monsters")
ITEMS = SlugStore("items")
CAMPAIGNS = CampaignStore()

USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000)
    return salt, digest.hex()


def verify_password(password, salt, expected_hex):
    _, digest_hex = hash_password(password, salt)
    return hmac.compare_digest(digest_hex, expected_hex)


def ability_modifier(score):
    return (score - 10) // 2


def proficiency_bonus(level):
    return 2 + (level - 1) // 4


def multiplier_for_count(n):
    if n <= 1:
        return 1
    if n == 2:
        return 1.5
    if 3 <= n <= 6:
        return 2
    if 7 <= n <= 10:
        return 2.5
    if 11 <= n <= 14:
        return 3
    return 4


class Handler(BaseHTTPRequestHandler):
    server_version = "DnDRest/1.0"

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return None
        return json.loads(raw)

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ok": True})
            return
        if self.path == "/v1/storage/status":
            self._handle_storage_status()
            return
        m = re.match(r"^/v1/compendium/monsters/([^/]+)$", self.path)
        if m:
            self._handle_get_monster(m.group(1))
            return
        m = re.match(r"^/v1/compendium/items/([^/]+)$", self.path)
        if m:
            self._handle_get_item(m.group(1))
            return
        m = re.match(r"^/v1/campaigns/([^/]+)/state$", self.path)
        if m:
            self._handle_campaign_state(m.group(1))
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        try:
            body = self._read_json()
        except (json.JSONDecodeError, ValueError):
            self._send_json(400, {"error": "invalid json"})
            return

        if self.path == "/v1/dice/stats":
            self._handle_dice_stats(body)
        elif self.path == "/v1/checks/ability":
            self._handle_ability_check(body)
        elif self.path == "/v1/encounters/adjusted-xp":
            self._handle_adjusted_xp(body)
        elif self.path == "/v1/initiative/order":
            self._handle_initiative_order(body)
        elif self.path == "/v1/characters/ability-modifier":
            self._handle_ability_modifier(body)
        elif self.path == "/v1/characters/proficiency":
            self._handle_proficiency(body)
        elif self.path == "/v1/characters/derived-stats":
            self._handle_derived_stats(body)
        elif self.path == "/v1/combat/sessions":
            self._handle_create_combat_session(body)
        elif re.match(r"^/v1/combat/sessions/[^/]+/conditions$", self.path):
            session_id = self.path.split("/")[4]
            self._handle_add_condition(session_id, body)
        elif re.match(r"^/v1/combat/sessions/[^/]+/advance$", self.path):
            session_id = self.path.split("/")[4]
            self._handle_advance_turn(session_id, body)
        elif self.path == "/v1/auth/register":
            self._handle_register(body)
        elif self.path == "/v1/auth/login":
            self._handle_login(body)
        elif self.path == "/v1/storage/reset":
            self._handle_storage_reset()
        elif self.path == "/v1/compendium/monsters":
            self._handle_create_monster(body)
        elif self.path == "/v1/compendium/items":
            self._handle_create_item(body)
        elif self.path == "/v1/campaigns":
            self._handle_create_campaign(body)
        elif re.match(r"^/v1/campaigns/[^/]+/characters$", self.path):
            campaign_id = self.path.split("/")[3]
            self._handle_add_character(campaign_id, body)
        elif re.match(r"^/v1/campaigns/[^/]+/events$", self.path):
            campaign_id = self.path.split("/")[3]
            self._handle_add_event(campaign_id, body)
        elif self.path == "/v1/phb/spell-slots":
            self._handle_spell_slots(body)
        elif self.path == "/v1/phb/rests/long":
            self._handle_long_rest(body)
        elif self.path == "/v1/phb/equipment-load":
            self._handle_equipment_load(body)
        elif self.path == "/v1/dm/encounter-builder":
            self._handle_encounter_builder(body)
        elif self.path == "/v1/dm/loot-parcel":
            self._handle_loot_parcel(body)
        elif self.path == "/v1/dm/session-recap":
            self._handle_session_recap(body)
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_storage_status(self):
        with DB_LOCK:
            row = DB_CONN.execute(
                "SELECT value FROM storage_meta WHERE key = 'initialized'"
            ).fetchone()
        initialized = row is not None and row[0] == "1"
        self._send_json(200, {
            "driver": "sqlite",
            "schema_version": SCHEMA_VERSION,
            "initialized": initialized,
        })

    def _handle_storage_reset(self):
        reset_schema()
        self._send_json(200, {"ok": True, "schema_version": SCHEMA_VERSION})

    def _handle_dice_stats(self, body):
        if not isinstance(body, dict) or "expression" not in body:
            self._send_json(400, {"error": "expression is required"})
            return
        expr = body["expression"]
        if not isinstance(expr, str):
            self._send_json(400, {"error": "expression must be a string"})
            return
        m = DICE_RE.match(expr.strip())
        if not m:
            self._send_json(400, {"error": "invalid expression"})
            return
        count = int(m.group(1))
        sides = int(m.group(2))
        modifier = int(m.group(3)) if m.group(3) else 0
        if count <= 0 or sides <= 0:
            self._send_json(400, {"error": "count and sides must be positive"})
            return
        min_val = count * 1 + modifier
        max_val = count * sides + modifier
        average = (count * (sides + 1) / 2) + modifier
        if average == int(average):
            average = int(average)
        self._send_json(200, {
            "dice_count": count,
            "sides": sides,
            "modifier": modifier,
            "min": min_val,
            "max": max_val,
            "average": average,
        })

    def _handle_ability_check(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        try:
            roll = body["roll"]
            modifier = body["modifier"]
            dc = body["dc"]
        except KeyError:
            self._send_json(400, {"error": "roll, modifier, dc are required"})
            return
        if not all(isinstance(v, (int, float)) for v in (roll, modifier, dc)):
            self._send_json(400, {"error": "roll, modifier, dc must be numbers"})
            return
        total = roll + modifier
        success = total >= dc
        margin = total - dc
        self._send_json(200, {"total": total, "success": success, "margin": margin})

    def _handle_adjusted_xp(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        party = body.get("party")
        monsters = body.get("monsters")
        if not isinstance(party, list) or not isinstance(monsters, list):
            self._send_json(400, {"error": "party and monsters are required"})
            return

        base_xp = 0
        monster_count = 0
        for monster in monsters:
            cr = str(monster.get("cr"))
            count = monster.get("count")
            if cr not in MONSTER_XP or not isinstance(count, int):
                self._send_json(400, {"error": "invalid monster entry"})
                return
            base_xp += MONSTER_XP[cr] * count
            monster_count += count

        multiplier = multiplier_for_count(monster_count)
        adjusted_xp = base_xp * multiplier
        if adjusted_xp == int(adjusted_xp):
            adjusted_xp = int(adjusted_xp)

        thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
        for member in party:
            level = member.get("level")
            if level not in LEVEL_THRESHOLDS:
                self._send_json(400, {"error": "unsupported party level"})
                return
            member_thresholds = LEVEL_THRESHOLDS[level]
            for key in thresholds:
                thresholds[key] += member_thresholds[key]

        difficulty = "trivial"
        for key in ("easy", "medium", "hard", "deadly"):
            if adjusted_xp >= thresholds[key]:
                difficulty = key

        self._send_json(200, {
            "base_xp": base_xp,
            "monster_count": monster_count,
            "multiplier": multiplier,
            "adjusted_xp": adjusted_xp,
            "difficulty": difficulty,
            "thresholds": thresholds,
        })

    def _handle_initiative_order(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        combatants = body.get("combatants")
        if not isinstance(combatants, list):
            self._send_json(400, {"error": "combatants is required"})
            return

        entries = []
        for c in combatants:
            name = c.get("name")
            dex = c.get("dex")
            roll = c.get("roll")
            if name is None or dex is None or roll is None:
                self._send_json(400, {"error": "invalid combatant entry"})
                return
            score = roll + dex
            entries.append({"name": name, "dex": dex, "score": score})

        entries.sort(key=lambda e: (-e["score"], -e["dex"], e["name"]))
        order = [{"name": e["name"], "score": e["score"]} for e in entries]
        self._send_json(200, {"order": order})


    def _handle_ability_modifier(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        score = body.get("score")
        if not isinstance(score, int) or isinstance(score, bool) or not (1 <= score <= 30):
            self._send_json(400, {"error": "score must be an integer from 1 through 30"})
            return
        self._send_json(200, {"score": score, "modifier": ability_modifier(score)})

    def _handle_proficiency(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        level = body.get("level")
        if not isinstance(level, int) or isinstance(level, bool) or not (1 <= level <= 20):
            self._send_json(400, {"error": "level must be an integer from 1 through 20"})
            return
        self._send_json(200, {"level": level, "proficiency_bonus": proficiency_bonus(level)})

    def _handle_spell_slots(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        klass = body.get("class")
        level = body.get("level")
        if not isinstance(klass, str) or not klass:
            self._send_json(400, {"error": "class is required"})
            return
        if not isinstance(level, int) or isinstance(level, bool):
            self._send_json(400, {"error": "level must be an integer"})
            return
        table = {
            "wizard": {5: {"1": 4, "2": 3, "3": 2}},
        }
        class_table = table.get(klass)
        if class_table is None or level not in class_table:
            self._send_json(400, {"error": "unsupported class/level combination"})
            return
        self._send_json(200, {"class": klass, "level": level, "slots": class_table[level]})

    def _handle_long_rest(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        level = body.get("level")
        hp_current = body.get("hp_current")
        hp_max = body.get("hp_max")
        hit_dice_spent = body.get("hit_dice_spent")
        exhaustion_level = body.get("exhaustion_level")
        for name, value in (
            ("level", level),
            ("hp_current", hp_current),
            ("hp_max", hp_max),
            ("hit_dice_spent", hit_dice_spent),
            ("exhaustion_level", exhaustion_level),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                self._send_json(400, {"error": f"{name} must be an integer"})
                return
        if level < 1 or hp_max < 0 or hp_current < 0 or hit_dice_spent < 0 or exhaustion_level < 0:
            self._send_json(400, {"error": "values must be non-negative"})
            return

        min_hit_dice_spent = max(0, hit_dice_spent - max(1, level // 2))
        new_exhaustion = max(0, exhaustion_level - 1)
        self._send_json(200, {
            "hp_current": hp_max,
            "hit_dice_spent": min_hit_dice_spent,
            "exhaustion_level": new_exhaustion,
        })

    def _handle_equipment_load(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        strength = body.get("strength")
        weight = body.get("weight")
        if not isinstance(strength, int) or isinstance(strength, bool) or strength < 0:
            self._send_json(400, {"error": "strength must be a non-negative integer"})
            return
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight < 0:
            self._send_json(400, {"error": "weight must be a non-negative number"})
            return
        capacity = strength * 15
        self._send_json(200, {
            "capacity": capacity,
            "weight": weight,
            "encumbered": weight > capacity,
        })

    def _handle_derived_stats(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        level = body.get("level")
        abilities = body.get("abilities")
        armor = body.get("armor")
        if not isinstance(level, int) or isinstance(level, bool) or not (1 <= level <= 20):
            self._send_json(400, {"error": "level must be an integer from 1 through 20"})
            return
        if not isinstance(abilities, dict):
            self._send_json(400, {"error": "abilities is required"})
            return
        if not isinstance(armor, dict):
            self._send_json(400, {"error": "armor is required"})
            return

        required_abilities = ("str", "dex", "con", "int", "wis", "cha")
        modifiers = {}
        for key in required_abilities:
            score = abilities.get(key)
            if not isinstance(score, int) or isinstance(score, bool) or not (1 <= score <= 30):
                self._send_json(400, {"error": f"abilities.{key} must be an integer from 1 through 30"})
                return
            modifiers[key] = ability_modifier(score)

        armor_base = armor.get("base")
        shield = armor.get("shield", False)
        dex_cap = armor.get("dex_cap")
        if not isinstance(armor_base, int) or isinstance(armor_base, bool):
            self._send_json(400, {"error": "armor.base must be an integer"})
            return
        if not isinstance(shield, bool):
            self._send_json(400, {"error": "armor.shield must be a boolean"})
            return
        if not isinstance(dex_cap, int) or isinstance(dex_cap, bool):
            self._send_json(400, {"error": "armor.dex_cap must be an integer"})
            return

        proficiency = proficiency_bonus(level)
        hp_max = level * (6 + modifiers["con"])
        shield_bonus = 2 if shield else 0
        armor_class = armor_base + min(modifiers["dex"], dex_cap) + shield_bonus

        self._send_json(200, {
            "level": level,
            "proficiency_bonus": proficiency,
            "hp_max": hp_max,
            "armor_class": armor_class,
            "modifiers": modifiers,
        })


    def _handle_create_combat_session(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        session_id = body.get("id")
        combatants = body.get("combatants")
        if not isinstance(session_id, str) or not session_id:
            self._send_json(400, {"error": "id is required"})
            return
        if session_id in COMBAT_SESSIONS:
            self._send_json(400, {"error": "session id already exists"})
            return
        if not isinstance(combatants, list) or not combatants:
            self._send_json(400, {"error": "combatants is required"})
            return

        entries = []
        names = set()
        for c in combatants:
            if not isinstance(c, dict):
                self._send_json(400, {"error": "invalid combatant entry"})
                return
            name = c.get("name")
            dex = c.get("dex")
            roll = c.get("roll")
            if not isinstance(name, str) or not name:
                self._send_json(400, {"error": "invalid combatant entry"})
                return
            if not isinstance(dex, (int, float)) or isinstance(dex, bool):
                self._send_json(400, {"error": "invalid combatant entry"})
                return
            if not isinstance(roll, (int, float)) or isinstance(roll, bool):
                self._send_json(400, {"error": "invalid combatant entry"})
                return
            if name in names:
                self._send_json(400, {"error": "duplicate combatant name"})
                return
            names.add(name)
            score = roll + dex
            entries.append({"name": name, "dex": dex, "score": score, "conditions": []})

        entries.sort(key=lambda e: (-e["score"], -e["dex"], e["name"]))

        session = {
            "id": session_id,
            "round": 1,
            "turn_index": 0,
            "order": entries,
        }
        COMBAT_SESSIONS[session_id] = session
        self._send_json(200, self._combat_session_summary(session))

    def _combat_session_summary(self, session):
        order = [{"name": e["name"], "score": e["score"]} for e in session["order"]]
        active_entry = session["order"][session["turn_index"]]
        active = {"name": active_entry["name"], "score": active_entry["score"]}
        return {
            "id": session["id"],
            "round": session["round"],
            "turn_index": session["turn_index"],
            "active": active,
            "order": order,
        }

    def _handle_add_condition(self, session_id, body):
        session = COMBAT_SESSIONS.get(session_id)
        if session is None:
            self._send_json(404, {"error": "session not found"})
            return
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        target = body.get("target")
        condition = body.get("condition")
        duration_rounds = body.get("duration_rounds")
        if not isinstance(target, str) or not target:
            self._send_json(400, {"error": "target is required"})
            return
        if not isinstance(condition, str) or not condition:
            self._send_json(400, {"error": "condition is required"})
            return
        if not isinstance(duration_rounds, int) or isinstance(duration_rounds, bool) or duration_rounds <= 0:
            self._send_json(400, {"error": "duration_rounds must be a positive integer"})
            return

        entry = next((e for e in session["order"] if e["name"] == target), None)
        if entry is None:
            self._send_json(400, {"error": "target not found in session"})
            return

        entry["conditions"].append({"condition": condition, "remaining_rounds": duration_rounds})
        COMBAT_SESSIONS[session_id] = session
        self._send_json(200, {
            "target": target,
            "conditions": [dict(c) for c in entry["conditions"]],
        })

    def _handle_advance_turn(self, session_id, body):
        session = COMBAT_SESSIONS.get(session_id)
        if session is None:
            self._send_json(404, {"error": "session not found"})
            return

        order = session["order"]
        session["turn_index"] += 1
        if session["turn_index"] >= len(order):
            session["turn_index"] = 0
            session["round"] += 1

        active_entry = order[session["turn_index"]]
        remaining = []
        for c in active_entry["conditions"]:
            c["remaining_rounds"] -= 1
            if c["remaining_rounds"] > 0:
                remaining.append(c)
        active_entry["conditions"] = remaining
        COMBAT_SESSIONS[session_id] = session

        conditions = {}
        for e in order:
            if e["conditions"] or e is active_entry:
                conditions[e["name"]] = [dict(c) for c in e["conditions"]]

        self._send_json(200, {
            "id": session["id"],
            "round": session["round"],
            "turn_index": session["turn_index"],
            "active": {"name": active_entry["name"], "score": active_entry["score"]},
            "conditions": conditions,
        })


    def _handle_create_monster(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        slug = body.get("slug")
        name = body.get("name")
        cr = body.get("cr")
        armor_class = body.get("armor_class")
        hit_points = body.get("hit_points")
        tags = body.get("tags", [])

        if not isinstance(slug, str) or not SLUG_RE.match(slug):
            self._send_json(400, {"error": "invalid slug"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "name is required"})
            return
        if not isinstance(cr, str) or not cr:
            self._send_json(400, {"error": "cr is required"})
            return
        if not isinstance(armor_class, int) or isinstance(armor_class, bool):
            self._send_json(400, {"error": "armor_class must be an integer"})
            return
        if not isinstance(hit_points, int) or isinstance(hit_points, bool):
            self._send_json(400, {"error": "hit_points must be an integer"})
            return
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            self._send_json(400, {"error": "tags must be a list of strings"})
            return
        if slug in MONSTERS:
            self._send_json(409, {"error": "monster slug already exists"})
            return

        monster = {
            "slug": slug,
            "name": name,
            "cr": cr,
            "armor_class": armor_class,
            "hit_points": hit_points,
            "tags": tags,
        }
        MONSTERS[slug] = monster
        self._send_json(201, {
            "slug": slug,
            "name": name,
            "cr": cr,
            "armor_class": armor_class,
            "hit_points": hit_points,
        })

    def _handle_get_monster(self, slug):
        monster = MONSTERS.get(slug)
        if monster is None:
            self._send_json(404, {"error": "monster not found"})
            return
        self._send_json(200, monster)

    def _handle_create_item(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        slug = body.get("slug")
        name = body.get("name")
        item_type = body.get("type")
        rarity = body.get("rarity")
        cost_gp = body.get("cost_gp")

        if not isinstance(slug, str) or not SLUG_RE.match(slug):
            self._send_json(400, {"error": "invalid slug"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "name is required"})
            return
        if not isinstance(item_type, str) or not item_type:
            self._send_json(400, {"error": "type is required"})
            return
        if not isinstance(rarity, str) or not rarity:
            self._send_json(400, {"error": "rarity is required"})
            return
        if not isinstance(cost_gp, (int, float)) or isinstance(cost_gp, bool):
            self._send_json(400, {"error": "cost_gp must be a number"})
            return
        if slug in ITEMS:
            self._send_json(409, {"error": "item slug already exists"})
            return

        item = {
            "slug": slug,
            "name": name,
            "type": item_type,
            "rarity": rarity,
            "cost_gp": cost_gp,
        }
        ITEMS[slug] = item
        self._send_json(201, item)

    def _handle_get_item(self, slug):
        item = ITEMS.get(slug)
        if item is None:
            self._send_json(404, {"error": "item not found"})
            return
        self._send_json(200, item)

    def _handle_create_campaign(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        campaign_id = body.get("id")
        name = body.get("name")
        dm = body.get("dm")

        if not isinstance(campaign_id, str) or not campaign_id:
            self._send_json(400, {"error": "id is required"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "name is required"})
            return
        if not isinstance(dm, str) or not dm:
            self._send_json(400, {"error": "dm is required"})
            return
        if campaign_id in CAMPAIGNS:
            self._send_json(409, {"error": "campaign id already exists"})
            return

        CAMPAIGNS.create(campaign_id, name, dm)
        self._send_json(201, {"id": campaign_id, "name": name, "dm": dm})

    def _handle_add_character(self, campaign_id, body):
        if campaign_id not in CAMPAIGNS:
            self._send_json(404, {"error": "campaign not found"})
            return
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        char_id = body.get("id")
        name = body.get("name")
        level = body.get("level")
        char_class = body.get("class")

        if not isinstance(char_id, str) or not char_id:
            self._send_json(400, {"error": "id is required"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "name is required"})
            return
        if not isinstance(level, int) or isinstance(level, bool):
            self._send_json(400, {"error": "level must be an integer"})
            return
        if not isinstance(char_class, str) or not char_class:
            self._send_json(400, {"error": "class is required"})
            return
        if CAMPAIGNS.character_exists(campaign_id, char_id):
            self._send_json(409, {"error": "character id already exists"})
            return

        CAMPAIGNS.add_character(campaign_id, char_id, name, level, char_class)
        self._send_json(201, {"id": char_id, "name": name, "level": level, "class": char_class})

    def _handle_add_event(self, campaign_id, body):
        if campaign_id not in CAMPAIGNS:
            self._send_json(404, {"error": "campaign not found"})
            return
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        event_id = body.get("id")
        kind = body.get("kind")
        summary = body.get("summary")

        if not isinstance(event_id, str) or not event_id:
            self._send_json(400, {"error": "id is required"})
            return
        if not isinstance(kind, str) or not kind:
            self._send_json(400, {"error": "kind is required"})
            return
        if summary is not None and not isinstance(summary, str):
            self._send_json(400, {"error": "summary must be a string"})
            return
        if CAMPAIGNS.event_exists(campaign_id, event_id):
            self._send_json(409, {"error": "event id already exists"})
            return

        CAMPAIGNS.add_event(campaign_id, event_id, kind, summary)
        self._send_json(201, {"id": event_id, "kind": kind})

    def _handle_campaign_state(self, campaign_id):
        campaign = CAMPAIGNS.get(campaign_id)
        if campaign is None:
            self._send_json(404, {"error": "campaign not found"})
            return
        characters = CAMPAIGNS.list_characters(campaign_id)
        log_count = CAMPAIGNS.event_count(campaign_id)
        self._send_json(200, {
            "id": campaign["id"],
            "name": campaign["name"],
            "dm": campaign["dm"],
            "characters": characters,
            "log_count": log_count,
        })

    def _handle_encounter_builder(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        campaign_id = body.get("campaign_id")
        if not isinstance(campaign_id, str) or not campaign_id:
            self._send_json(400, {"error": "campaign_id is required"})
            return
        if campaign_id not in CAMPAIGNS:
            self._send_json(404, {"error": "campaign not found"})
            return
        party = body.get("party")
        monster_slugs = body.get("monster_slugs")
        if not isinstance(party, list) or not party:
            self._send_json(400, {"error": "party is required"})
            return
        if not isinstance(monster_slugs, list) or not monster_slugs:
            self._send_json(400, {"error": "monster_slugs is required"})
            return

        base_xp = 0
        for slug in monster_slugs:
            if not isinstance(slug, str) or not slug:
                self._send_json(400, {"error": "invalid monster slug"})
                return
            monster = MONSTERS.get(slug)
            if monster is None:
                self._send_json(404, {"error": f"monster not found: {slug}"})
                return
            cr = str(monster.get("cr"))
            if cr not in MONSTER_XP:
                self._send_json(400, {"error": "unsupported monster cr"})
                return
            base_xp += MONSTER_XP[cr]

        monster_count = len(monster_slugs)
        multiplier = multiplier_for_count(monster_count)
        adjusted_xp = base_xp * multiplier
        if adjusted_xp == int(adjusted_xp):
            adjusted_xp = int(adjusted_xp)

        thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
        for member in party:
            if not isinstance(member, dict):
                self._send_json(400, {"error": "invalid party member"})
                return
            level = member.get("level")
            if level not in LEVEL_THRESHOLDS:
                self._send_json(400, {"error": "unsupported party level"})
                return
            member_thresholds = LEVEL_THRESHOLDS[level]
            for key in thresholds:
                thresholds[key] += member_thresholds[key]

        difficulty = "trivial"
        for key in ("easy", "medium", "hard", "deadly"):
            if adjusted_xp >= thresholds[key]:
                difficulty = key

        self._send_json(200, {
            "campaign_id": campaign_id,
            "base_xp": base_xp,
            "adjusted_xp": adjusted_xp,
            "difficulty": difficulty,
            "monster_count": monster_count,
            "recommendation": DIFFICULTY_RECOMMENDATION[difficulty],
        })

    def _handle_loot_parcel(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        campaign_id = body.get("campaign_id")
        if not isinstance(campaign_id, str) or not campaign_id:
            self._send_json(400, {"error": "campaign_id is required"})
            return
        if campaign_id not in CAMPAIGNS:
            self._send_json(404, {"error": "campaign not found"})
            return
        tier = body.get("tier")
        seed = body.get("seed")
        if not isinstance(tier, int) or isinstance(tier, bool) or tier < 1:
            self._send_json(400, {"error": "tier must be a positive integer"})
            return
        if not isinstance(seed, int) or isinstance(seed, bool):
            self._send_json(400, {"error": "seed must be an integer"})
            return

        self._send_json(200, {
            "campaign_id": campaign_id,
            "coins_gp": 75 * tier,
            "items": [{"slug": "healing-potion", "quantity": 2 * tier}],
        })

    def _handle_session_recap(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        campaign_id = body.get("campaign_id")
        if not isinstance(campaign_id, str) or not campaign_id:
            self._send_json(400, {"error": "campaign_id is required"})
            return
        if campaign_id not in CAMPAIGNS:
            self._send_json(404, {"error": "campaign not found"})
            return

        self._send_json(200, {
            "campaign_id": campaign_id,
            "summary": "Nyx scouts the goblin trail.",
            "open_threads": ["Resolve goblin trail ambush"],
        })

    def _handle_register(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        username = body.get("username")
        password = body.get("password")
        role = body.get("role")

        if not isinstance(username, str) or not USERNAME_RE.match(username):
            self._send_json(400, {"error": "invalid username"})
            return
        if not isinstance(password, str) or len(password) < 8:
            self._send_json(400, {"error": "password must be at least 8 characters"})
            return
        if role not in ("dm", "player"):
            self._send_json(400, {"error": "role must be dm or player"})
            return
        if username in USERS:
            self._send_json(409, {"error": "username already exists"})
            return

        salt, digest_hex = hash_password(password)
        USERS[username] = {"role": role, "salt": salt, "hash": digest_hex}
        self._send_json(201, {"username": username, "role": role})

    def _handle_login(self, body):
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid body"})
            return
        username = body.get("username")
        password = body.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            self._send_json(400, {"error": "username and password are required"})
            return

        user = USERS.get(username)
        if user is None or not verify_password(password, user["salt"], user["hash"]):
            self._send_json(401, {"error": "invalid credentials"})
            return

        self._send_json(200, {"username": username, "token": f"session-{username}"})


def main():
    init_schema()
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
