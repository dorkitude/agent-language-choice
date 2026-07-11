import json
import os
import sqlite3
import threading

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "game.db")

SCHEMA_VERSION = 1

_lock = threading.Lock()
_initialized = False


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _create_tables(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL
        )
        """
    )
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
            data TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS monsters (
            slug TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            slug TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS campaigns (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS campaign_characters (
            campaign_id TEXT NOT NULL,
            char_id TEXT NOT NULL,
            data TEXT NOT NULL,
            PRIMARY KEY (campaign_id, char_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS campaign_events (
            campaign_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            data TEXT NOT NULL,
            PRIMARY KEY (campaign_id, event_id)
        )
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (id, version) VALUES (1, ?)",
        (SCHEMA_VERSION,),
    )


def init_schema():
    global _initialized
    with _lock:
        conn = get_connection()
        try:
            _create_tables(conn)
            conn.commit()
        finally:
            conn.close()
        _initialized = True


def reset_schema():
    global _initialized
    with _lock:
        conn = get_connection()
        try:
            conn.execute("DROP TABLE IF EXISTS users")
            conn.execute("DROP TABLE IF EXISTS combat_sessions")
            conn.execute("DROP TABLE IF EXISTS monsters")
            conn.execute("DROP TABLE IF EXISTS items")
            conn.execute("DROP TABLE IF EXISTS campaigns")
            conn.execute("DROP TABLE IF EXISTS campaign_characters")
            conn.execute("DROP TABLE IF EXISTS campaign_events")
            conn.execute("DROP TABLE IF EXISTS schema_meta")
            _create_tables(conn)
            conn.commit()
        finally:
            conn.close()
        _initialized = True


def is_initialized():
    return _initialized


# --- users ---


def get_user(username):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT username, password_hash, role FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            return None
        return {
            "username": row["username"],
            "password_hash": row["password_hash"],
            "role": row["role"],
        }
    finally:
        conn.close()


def create_user(username, password_hash, role):
    with _lock:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, password_hash, role),
            )
            conn.commit()
        finally:
            conn.close()


# --- combat sessions ---


def get_combat_session(session_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT data FROM combat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["data"])
    finally:
        conn.close()


def save_combat_session(session):
    with _lock:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO combat_sessions (id, data) VALUES (?, ?)",
                (session["id"], json.dumps(session)),
            )
            conn.commit()
        finally:
            conn.close()


def combat_session_exists(session_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM combat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# --- compendium: monsters ---


def get_monster(slug):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT data FROM monsters WHERE slug = ?", (slug,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["data"])
    finally:
        conn.close()


def create_monster(monster):
    with _lock:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO monsters (slug, data) VALUES (?, ?)",
                (monster["slug"], json.dumps(monster)),
            )
            conn.commit()
        finally:
            conn.close()


def monster_exists(slug):
    conn = get_connection()
    try:
        row = conn.execute("SELECT 1 FROM monsters WHERE slug = ?", (slug,)).fetchone()
        return row is not None
    finally:
        conn.close()


# --- compendium: items ---


def get_item(slug):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT data FROM items WHERE slug = ?", (slug,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["data"])
    finally:
        conn.close()


def create_item(item):
    with _lock:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO items (slug, data) VALUES (?, ?)",
                (item["slug"], json.dumps(item)),
            )
            conn.commit()
        finally:
            conn.close()


def item_exists(slug):
    conn = get_connection()
    try:
        row = conn.execute("SELECT 1 FROM items WHERE slug = ?", (slug,)).fetchone()
        return row is not None
    finally:
        conn.close()


# --- campaigns ---


def get_campaign(campaign_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT data FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["data"])
    finally:
        conn.close()


def create_campaign(campaign):
    with _lock:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO campaigns (id, data) VALUES (?, ?)",
                (campaign["id"], json.dumps(campaign)),
            )
            conn.commit()
        finally:
            conn.close()


def campaign_exists(campaign_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def add_campaign_character(campaign_id, character):
    with _lock:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO campaign_characters (campaign_id, char_id, data) VALUES (?, ?, ?)",
                (campaign_id, character["id"], json.dumps(character)),
            )
            conn.commit()
        finally:
            conn.close()


def campaign_character_exists(campaign_id, char_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND char_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def list_campaign_characters(campaign_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT data FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
        return [json.loads(row["data"]) for row in rows]
    finally:
        conn.close()


def add_campaign_event(campaign_id, event):
    with _lock:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO campaign_events (campaign_id, event_id, data) VALUES (?, ?, ?)",
                (campaign_id, event["id"], json.dumps(event)),
            )
            conn.commit()
        finally:
            conn.close()


def campaign_event_exists(campaign_id, event_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM campaign_events WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def count_campaign_events(campaign_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM campaign_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        return row["c"]
    finally:
        conn.close()


def list_campaign_events(campaign_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT data FROM campaign_events WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
        return [json.loads(row["data"]) for row in rows]
    finally:
        conn.close()
