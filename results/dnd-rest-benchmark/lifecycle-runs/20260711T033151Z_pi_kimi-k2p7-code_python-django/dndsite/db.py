import json
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "game.db")
SCHEMA_VERSION = 1


class DuplicateUserError(Exception):
    pass


class DuplicateSlugError(Exception):
    pass


class SessionExistsError(Exception):
    pass


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _create_schema(conn):
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
        CREATE TABLE IF NOT EXISTS monsters (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            cr TEXT NOT NULL,
            armor_class INTEGER NOT NULL,
            hit_points INTEGER NOT NULL,
            tags_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS campaigns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            dm TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS characters (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            name TEXT NOT NULL,
            level INTEGER NOT NULL,
            class_name TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns (id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            summary TEXT,
            FOREIGN KEY (campaign_id) REFERENCES campaigns (id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (id, version) VALUES (1, ?)",
        (SCHEMA_VERSION,),
    )


def init_storage():
    conn = _connect()
    try:
        _create_schema(conn)
        conn.commit()
    finally:
        conn.close()


def reset_storage():
    conn = _connect()
    try:
        # Drop child tables before parents to satisfy foreign keys.
        conn.execute("DROP TABLE IF EXISTS characters")
        conn.execute("DROP TABLE IF EXISTS events")
        conn.execute("DROP TABLE IF EXISTS campaigns")
        conn.execute("DROP TABLE IF EXISTS users")
        conn.execute("DROP TABLE IF EXISTS combat_sessions")
        conn.execute("DROP TABLE IF EXISTS monsters")
        conn.execute("DROP TABLE IF EXISTS items")
        conn.execute("DROP TABLE IF EXISTS schema_version")
        _create_schema(conn)
        conn.commit()
    finally:
        conn.close()


def storage_status():
    initialized = False
    if os.path.exists(DB_PATH):
        conn = _connect()
        try:
            cursor = conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name IN (
                    'users', 'combat_sessions', 'monsters', 'items',
                    'campaigns', 'characters', 'events', 'schema_version'
                )
                """
            )
            tables = {row[0] for row in cursor.fetchall()}
            initialized = {
                "users",
                "combat_sessions",
                "monsters",
                "items",
                "campaigns",
                "characters",
                "events",
                "schema_version",
            } <= tables
        except sqlite3.Error:
            initialized = False
        finally:
            conn.close()
    return {"driver": "sqlite", "schema_version": SCHEMA_VERSION, "initialized": initialized}


# User storage


def get_user(username):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT password_hash, role FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row is None:
            return None
        return {"password_hash": row[0], "role": row[1]}
    finally:
        conn.close()


def create_user(username, password_hash, role):
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, password_hash, role),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise DuplicateUserError from exc
    finally:
        conn.close()


# Combat session storage


def create_session(session_id, order, conditions):
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO combat_sessions (id, round, turn_index, order_json, conditions_json)
            VALUES (?, 1, 0, ?, ?)
            """,
            (session_id, json.dumps(order), json.dumps(conditions)),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise SessionExistsError from exc
    finally:
        conn.close()


def get_session(session_id):
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT round, turn_index, order_json, conditions_json
            FROM combat_sessions WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": session_id,
            "round": row[0],
            "turn_index": row[1],
            "order": json.loads(row[2]),
            "conditions": json.loads(row[3]),
        }
    finally:
        conn.close()


def update_session(session_id, round_, turn_index, conditions):
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE combat_sessions
            SET round = ?, turn_index = ?, conditions_json = ?
            WHERE id = ?
            """,
            (round_, turn_index, json.dumps(conditions), session_id),
        )
        conn.commit()
    finally:
        conn.close()


# Compendium storage


def create_monster(slug, name, cr, armor_class, hit_points, tags):
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (slug, name, cr, armor_class, hit_points, json.dumps(tags)),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise DuplicateSlugError from exc
    finally:
        conn.close()


def get_monster(slug):
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT name, cr, armor_class, hit_points, tags_json
            FROM monsters WHERE slug = ?
            """,
            (slug,),
        ).fetchone()
        if row is None:
            return None
        return {
            "slug": slug,
            "name": row[0],
            "cr": row[1],
            "armor_class": row[2],
            "hit_points": row[3],
            "tags": json.loads(row[4]),
        }
    finally:
        conn.close()


def create_item(slug, name, item_type, rarity, cost_gp):
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO items (slug, name, type, rarity, cost_gp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (slug, name, item_type, rarity, cost_gp),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise DuplicateSlugError from exc
    finally:
        conn.close()


def get_item(slug):
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT name, type, rarity, cost_gp
            FROM items WHERE slug = ?
            """,
            (slug,),
        ).fetchone()
        if row is None:
            return None
        return {
            "slug": slug,
            "name": row[0],
            "type": row[1],
            "rarity": row[2],
            "cost_gp": row[3],
        }
    finally:
        conn.close()


# Campaign state storage


def create_campaign(campaign_id, name, dm):
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
            (campaign_id, name, dm),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise SessionExistsError from exc
    finally:
        conn.close()


def get_campaign(campaign_id):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT name, dm FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if row is None:
            return None
        return {"id": campaign_id, "name": row[0], "dm": row[1]}
    finally:
        conn.close()


def create_character(character_id, campaign_id, name, level, class_name):
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO characters (id, campaign_id, name, level, class_name)
            VALUES (?, ?, ?, ?, ?)
            """,
            (character_id, campaign_id, name, level, class_name),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise SessionExistsError from exc
    finally:
        conn.close()


def list_characters(campaign_id):
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT id, name, level, class_name
            FROM characters WHERE campaign_id = ?
            ORDER BY id
            """,
            (campaign_id,),
        ).fetchall()
        return [
            {"id": row[0], "name": row[1], "level": row[2], "class": row[3]}
            for row in rows
        ]
    finally:
        conn.close()


def create_event(event_id, campaign_id, kind, summary):
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO events (id, campaign_id, kind, summary)
            VALUES (?, ?, ?, ?)
            """,
            (event_id, campaign_id, kind, summary),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise SessionExistsError from exc
    finally:
        conn.close()


def count_events(campaign_id):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM events WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
        return row[0]
    finally:
        conn.close()


def list_events(campaign_id):
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT id, kind, summary
            FROM events WHERE campaign_id = ?
            ORDER BY id
            """,
            (campaign_id,),
        ).fetchall()
        return [
            {"id": row[0], "kind": row[1], "summary": row[2]}
            for row in rows
        ]
    finally:
        conn.close()
