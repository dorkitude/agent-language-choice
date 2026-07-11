"""Durable SQLite-backed storage for the D&D API.

A single SQLite database file (``game.db``) in the project directory holds the
durable game-world data. The schema is initialized on server startup and can be
reset via the storage endpoints.
"""

import json
import os
import sqlite3
import threading

SCHEMA_VERSION = 1

# game.db lives in the project directory (one level above this package).
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "game.db"
)

_lock = threading.Lock()
_initialized = False


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _create_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS monsters (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            cr TEXT NOT NULL,
            armor_class INTEGER NOT NULL,
            hit_points INTEGER NOT NULL,
            tags TEXT NOT NULL
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
            seq INTEGER
        );
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            summary TEXT NOT NULL,
            seq INTEGER
        );
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def init_storage():
    """Create the database file and schema if they do not already exist."""
    global _initialized
    with _lock:
        with _connect() as conn:
            _create_schema(conn)
        _initialized = True


def reset_storage():
    """Drop benchmark-created durable data and recreate the schema."""
    global _initialized
    with _lock:
        with _connect() as conn:
            conn.executescript(
                "DROP TABLE IF EXISTS users; "
                "DROP TABLE IF EXISTS monsters; "
                "DROP TABLE IF EXISTS items; "
                "DROP TABLE IF EXISTS campaigns; "
                "DROP TABLE IF EXISTS characters; "
                "DROP TABLE IF EXISTS events; "
                "DROP TABLE IF EXISTS meta;"
            )
            conn.commit()
            _create_schema(conn)
        _initialized = True


def is_initialized():
    return _initialized


def get_user(username):
    with _lock:
        with _connect() as conn:
            row = conn.execute(
                "SELECT username, role, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()
    return dict(row) if row is not None else None


def create_user(username, role, password_hash):
    """Insert a user. Returns False if the username already exists."""
    with _lock:
        with _connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO users (username, role, password_hash) "
                    "VALUES (?, ?, ?)",
                    (username, role, password_hash),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return False
    return True


def create_monster(slug, name, cr, armor_class, hit_points, tags):
    """Insert a monster. Returns False if the slug already exists."""
    with _lock:
        with _connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO monsters (slug, name, cr, armor_class, "
                    "hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)",
                    (slug, name, cr, armor_class, hit_points, json.dumps(tags)),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return False
    return True


def get_monster(slug):
    with _lock:
        with _connect() as conn:
            row = conn.execute(
                "SELECT slug, name, cr, armor_class, hit_points, tags "
                "FROM monsters WHERE slug = ?",
                (slug,),
            ).fetchone()
    if row is None:
        return None
    monster = dict(row)
    monster["tags"] = json.loads(monster["tags"])
    return monster


def create_campaign(campaign_id, name, dm):
    """Insert a campaign. Returns False if the id already exists."""
    with _lock:
        with _connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
                    (campaign_id, name, dm),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return False
    return True


def get_campaign(campaign_id):
    with _lock:
        with _connect() as conn:
            row = conn.execute(
                "SELECT id, name, dm FROM campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
    return dict(row) if row is not None else None


def create_character(character_id, campaign_id, name, level, class_):
    """Insert a character.

    Returns "ok", "duplicate" if the character id exists, or "no_campaign" if
    the campaign does not exist.
    """
    with _lock:
        with _connect() as conn:
            campaign = conn.execute(
                "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "no_campaign"
            seq = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM characters"
            ).fetchone()[0]
            try:
                conn.execute(
                    "INSERT INTO characters (id, campaign_id, name, level, "
                    "class, seq) VALUES (?, ?, ?, ?, ?, ?)",
                    (character_id, campaign_id, name, level, class_, seq),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return "duplicate"
    return "ok"


def create_event(event_id, campaign_id, kind, summary):
    """Insert a session-log event.

    Returns "ok", "duplicate" if the event id exists, or "no_campaign" if the
    campaign does not exist.
    """
    with _lock:
        with _connect() as conn:
            campaign = conn.execute(
                "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "no_campaign"
            seq = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM events"
            ).fetchone()[0]
            try:
                conn.execute(
                    "INSERT INTO events (id, campaign_id, kind, summary, seq) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (event_id, campaign_id, kind, summary, seq),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return "duplicate"
    return "ok"


def get_campaign_state(campaign_id):
    """Return the full campaign state, or None if the campaign is unknown."""
    with _lock:
        with _connect() as conn:
            campaign = conn.execute(
                "SELECT id, name, dm FROM campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
            if campaign is None:
                return None
            characters = conn.execute(
                "SELECT id, name, level, class FROM characters "
                "WHERE campaign_id = ? ORDER BY seq",
                (campaign_id,),
            ).fetchall()
            log_count = conn.execute(
                "SELECT COUNT(*) FROM events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
    state = dict(campaign)
    state["characters"] = [dict(c) for c in characters]
    state["log_count"] = log_count
    return state


def get_events(campaign_id):
    """Return the campaign's logged events ordered by insertion sequence."""
    with _lock:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT id, kind, summary FROM events "
                "WHERE campaign_id = ? ORDER BY seq",
                (campaign_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def create_item(slug, name, type_, rarity, cost_gp):
    """Insert an item. Returns False if the slug already exists."""
    with _lock:
        with _connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO items (slug, name, type, rarity, cost_gp) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (slug, name, type_, rarity, cost_gp),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return False
    return True


def get_item(slug):
    with _lock:
        with _connect() as conn:
            row = conn.execute(
                "SELECT slug, name, type, rarity, cost_gp "
                "FROM items WHERE slug = ?",
                (slug,),
            ).fetchone()
    return dict(row) if row is not None else None
