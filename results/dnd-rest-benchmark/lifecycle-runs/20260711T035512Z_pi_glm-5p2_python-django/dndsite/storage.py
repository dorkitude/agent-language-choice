"""SQLite-backed durable storage for the D&D REST API.

This module owns the single SQLite connection used by the whole process and
exposes a tiny data-access API for the durable game-state (combat sessions and
auth users). Schema is initialized on import (i.e. on server startup) so the
database file ``game.db`` exists before the first request is served.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading

# Resolve ``game.db`` in the project directory (the parent of this package).
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_PROJECT_DIR, "game.db")

SCHEMA_VERSION = 1

_LOCK = threading.Lock()
_CONN: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


_SCHEMA_SQL = """
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
    id              TEXT PRIMARY KEY,
    round           INTEGER NOT NULL,
    turn_index      INTEGER NOT NULL,
    order_json      TEXT NOT NULL,
    conditions_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS monsters (
    slug        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    cr          TEXT NOT NULL,
    armor_class INTEGER NOT NULL,
    hit_points  INTEGER NOT NULL,
    tags_json   TEXT NOT NULL
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
    campaign_id TEXT NOT NULL,
    id          TEXT NOT NULL,
    name        TEXT NOT NULL,
    level       INTEGER NOT NULL,
    "class"     TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS campaign_events (
    campaign_id TEXT NOT NULL,
    id          TEXT NOT NULL,
    kind        TEXT NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
"""


def init_schema(reset: bool = False) -> None:
    """Create the database file and tables.

    With ``reset=True`` all benchmark-created durable data is dropped first and
    the schema is recreated from scratch.
    """
    global _CONN
    with _LOCK:
        if _CONN is None:
            _CONN = _connect()
        cur = _CONN.cursor()
        if reset:
            cur.executescript(
                "DROP TABLE IF EXISTS campaign_events;"
                "DROP TABLE IF EXISTS campaign_characters;"
                "DROP TABLE IF EXISTS campaigns;"
                "DROP TABLE IF EXISTS users;"
                "DROP TABLE IF EXISTS combat_sessions;"
                "DROP TABLE IF EXISTS monsters;"
                "DROP TABLE IF EXISTS items;"
                "DROP TABLE IF EXISTS meta;"
            )
        cur.executescript(_SCHEMA_SQL)
        cur.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        _CONN.commit()


def is_initialized() -> bool:
    """Return True when the schema has been created in the database file."""
    with _LOCK:
        if _CONN is None:
            return False
        cur = _CONN.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
        )
        if cur.fetchone() is None:
            return False
        cur.execute("SELECT value FROM meta WHERE key='schema_version'")
        row = cur.fetchone()
        if row is None:
            return False
        try:
            return int(row["value"]) == SCHEMA_VERSION
        except (TypeError, ValueError):
            return False


def reset() -> None:
    """Drop and recreate all benchmark-created durable data."""
    init_schema(reset=True)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_user(username: str) -> dict | None:
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute(
            "SELECT username, role, password_hash FROM users WHERE username=?",
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


def insert_user(username: str, role: str, password_hash: str) -> None:
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute(
            "INSERT INTO users(username, role, password_hash) VALUES (?, ?, ?)",
            (username, role, password_hash),
        )
        _CONN.commit()


# ---------------------------------------------------------------------------
# Combat sessions
# ---------------------------------------------------------------------------

def upsert_session(session: dict) -> None:
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute(
            """
            INSERT INTO combat_sessions(id, round, turn_index, order_json, conditions_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                round           = excluded.round,
                turn_index      = excluded.turn_index,
                order_json      = excluded.order_json,
                conditions_json = excluded.conditions_json
            """,
            (
                session["id"],
                session["round"],
                session["turn_index"],
                json.dumps(session["order"]),
                json.dumps(session["conditions"]),
            ),
        )
        _CONN.commit()


def get_session(sid: str) -> dict | None:
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute(
            "SELECT id, round, turn_index, order_json, conditions_json "
            "FROM combat_sessions WHERE id=?",
            (sid,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "round": row["round"],
            "turn_index": row["turn_index"],
            "order": json.loads(row["order_json"]),
            "conditions": json.loads(row["conditions_json"]),
        }


def delete_session(sid: str) -> None:
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute("DELETE FROM combat_sessions WHERE id=?", (sid,))
        _CONN.commit()


# ---------------------------------------------------------------------------
# Compendium: monsters and items
# ---------------------------------------------------------------------------

def insert_monster(monster: dict) -> None:
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute(
            "INSERT INTO monsters(slug, name, cr, armor_class, hit_points, tags_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                monster["slug"],
                monster["name"],
                monster["cr"],
                monster["armor_class"],
                monster["hit_points"],
                json.dumps(monster["tags"]),
            ),
        )
        _CONN.commit()


def get_monster(slug: str) -> dict | None:
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute(
            "SELECT slug, name, cr, armor_class, hit_points, tags_json "
            "FROM monsters WHERE slug=?",
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
            "tags": json.loads(row["tags_json"]),
        }


def insert_item(item: dict) -> None:
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute(
            "INSERT INTO items(slug, name, type, rarity, cost_gp) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                item["slug"],
                item["name"],
                item["type"],
                item["rarity"],
                item["cost_gp"],
            ),
        )
        _CONN.commit()


def get_item(slug: str) -> dict | None:
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute(
            "SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug=?",
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


# ---------------------------------------------------------------------------
# Campaign state: campaigns, characters, and session log events
# ---------------------------------------------------------------------------

def insert_campaign(campaign: dict) -> None:
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute(
            "INSERT INTO campaigns(id, name, dm) VALUES (?, ?, ?)",
            (campaign["id"], campaign["name"], campaign["dm"]),
        )
        _CONN.commit()


def get_campaign(cid: str) -> dict | None:
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute(
            "SELECT id, name, dm FROM campaigns WHERE id=?",
            (cid,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "dm": row["dm"],
        }


def get_character(campaign_id: str, char_id: str) -> dict | None:
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute(
            'SELECT id, name, level, "class" FROM campaign_characters '
            "WHERE campaign_id=? AND id=?",
            (campaign_id, char_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "level": row["level"],
            "class": row["class"],
        }


def insert_character(campaign_id: str, character: dict) -> None:
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute(
            'INSERT INTO campaign_characters(campaign_id, id, name, level, "class") '
            "VALUES (?, ?, ?, ?, ?)",
            (
                campaign_id,
                character["id"],
                character["name"],
                character["level"],
                character["class"],
            ),
        )
        _CONN.commit()


def list_characters(campaign_id: str) -> list[dict]:
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute(
            'SELECT id, name, level, "class" FROM campaign_characters '
            "WHERE campaign_id=? ORDER BY rowid",
            (campaign_id,),
        )
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "level": row["level"],
                "class": row["class"],
            }
            for row in cur.fetchall()
        ]


def get_event(campaign_id: str, evt_id: str) -> dict | None:
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute(
            "SELECT id, kind, summary FROM campaign_events "
            "WHERE campaign_id=? AND id=?",
            (campaign_id, evt_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "kind": row["kind"],
            "summary": row["summary"],
        }


def insert_event(campaign_id: str, event: dict) -> None:
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute(
            "INSERT INTO campaign_events(campaign_id, id, kind, summary) "
            "VALUES (?, ?, ?, ?)",
            (
                campaign_id,
                event["id"],
                event["kind"],
                event["summary"],
            ),
        )
        _CONN.commit()


def count_events(campaign_id: str) -> int:
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute(
            "SELECT COUNT(*) AS n FROM campaign_events WHERE campaign_id=?",
            (campaign_id,),
        )
        row = cur.fetchone()
        return row["n"] if row is not None else 0


def list_events(campaign_id: str) -> list[dict]:
    """Return the campaign's logged events ordered by insertion sequence."""
    with _LOCK:
        cur = _CONN.cursor()
        cur.execute(
            "SELECT id, kind, summary FROM campaign_events "
            "WHERE campaign_id=? ORDER BY rowid",
            (campaign_id,),
        )
        return [
            {"id": row["id"], "kind": row["kind"], "summary": row["summary"]}
            for row in cur.fetchall()
        ]


# Initialize the schema as soon as the module is imported (server startup).
init_schema()
