"""SQLite persistence layer."""

import os
import sqlite3
import threading
from contextlib import contextmanager

# SQLite file lives next to the project root.
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "game.db"
)

_db_lock = threading.Lock()
_INITIALIZED = False

# Table definitions in dependency order. Foreign keys always point to tables
# defined earlier, so reverse order is safe for DROP statements.
_TABLES = [
    (
        "users",
        """
        username TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL
        """,
    ),
    (
        "combat_sessions",
        """
        id TEXT PRIMARY KEY,
        round INTEGER NOT NULL,
        turn_index INTEGER NOT NULL,
        order_json TEXT NOT NULL,
        conditions_json TEXT NOT NULL
        """,
    ),
    (
        "monsters",
        """
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        cr TEXT NOT NULL,
        armor_class INTEGER NOT NULL,
        hit_points INTEGER NOT NULL,
        tags_json TEXT NOT NULL
        """,
    ),
    (
        "items",
        """
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        rarity TEXT NOT NULL,
        cost_gp INTEGER NOT NULL
        """,
    ),
    (
        "campaigns",
        """
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        dm TEXT NOT NULL
        """,
    ),
    (
        "factions",
        """
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        name TEXT NOT NULL,
        stance TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "npcs",
        """
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        name TEXT NOT NULL,
        faction_id TEXT NOT NULL,
        disposition INTEGER NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY (faction_id) REFERENCES factions(id) ON DELETE CASCADE
        """,
    ),
    (
        "campaign_characters",
        """
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        name TEXT NOT NULL,
        level INTEGER NOT NULL,
        class_name TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "inventory",
        """
        campaign_id TEXT NOT NULL,
        item_slug TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        owner TEXT NOT NULL,
        PRIMARY KEY (campaign_id, item_slug, owner),
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "campaign_events",
        """
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        summary TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "sessions",
        """
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        starts_at TEXT NOT NULL,
        duration_minutes INTEGER NOT NULL,
        agenda_json TEXT NOT NULL,
        attendance_json TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "quests",
        """
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        title TEXT NOT NULL,
        status TEXT NOT NULL,
        milestones_json TEXT NOT NULL,
        completed_milestones_json TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "crafting_projects",
        """
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        item_slug TEXT NOT NULL,
        days_required INTEGER NOT NULL,
        days_completed INTEGER NOT NULL,
        status TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_campaigns",
        """
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        owner TEXT NOT NULL,
        status TEXT NOT NULL,
        max_players INTEGER NOT NULL,
        current_actor TEXT,
        turn_number INTEGER DEFAULT 0,
        nudge_count INTEGER DEFAULT 0,
        story TEXT DEFAULT '',
        dm_notes TEXT DEFAULT '',
        current_scene_id TEXT,
        current_location_id TEXT
        """,
    ),
    (
        "scenes",
        """
        campaign_id TEXT NOT NULL,
        scene_id TEXT NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL,
        PRIMARY KEY (campaign_id, scene_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_campaign_members",
        """
        campaign_id TEXT NOT NULL,
        username TEXT NOT NULL,
        character_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        class_name TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        hp_current INTEGER NOT NULL DEFAULT 20,
        hp_max INTEGER NOT NULL DEFAULT 20,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        UNIQUE (campaign_id, username)
        """,
    ),
    (
        "narrations",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        kind TEXT NOT NULL,
        type TEXT,
        actor TEXT NOT NULL,
        text TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        UNIQUE (campaign_id, sequence)
        """,
    ),
    (
        "locations",
        """
        campaign_id TEXT NOT NULL,
        location_id TEXT NOT NULL,
        name TEXT NOT NULL,
        PRIMARY KEY (campaign_id, location_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "location_connections",
        """
        campaign_id TEXT NOT NULL,
        from_id TEXT NOT NULL,
        to_id TEXT NOT NULL,
        travel_turns INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, from_id, to_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
]


@contextmanager
def db_conn():
    """Thread-safe SQLite connection with row factory and auto commit/rollback."""
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _init_schema():
    """Create tables if they do not already exist."""
    create_stmts = [
        f"CREATE TABLE IF NOT EXISTS {name} ({cols});" for name, cols in _TABLES
    ]
    with db_conn() as conn:
        conn.executescript("\n".join(create_stmts))


def reset_db():
    """Drop and recreate all tables. Used for a fresh startup."""
    global _INITIALIZED
    drop_stmts = [f"DROP TABLE IF EXISTS {name};" for name, _ in reversed(_TABLES)]
    create_stmts = [f"CREATE TABLE {name} ({cols});" for name, cols in _TABLES]
    with db_conn() as conn:
        conn.executescript("\n".join(drop_stmts + create_stmts))
    _INITIALIZED = True


def reset_storage():
    """Drop and recreate all tables except users.

    The storage reset endpoint preserves registered users so that the
    authenticated ``dm`` used by earlier tests survives the reset and
    can still own campaigns under ``/v1/play``.
    """
    global _INITIALIZED
    non_user_tables = [(name, cols) for name, cols in _TABLES if name != "users"]
    drop_stmts = [f"DROP TABLE IF EXISTS {name};" for name, _ in reversed(non_user_tables)]
    create_stmts = [f"CREATE TABLE {name} ({cols});" for name, cols in non_user_tables]
    with db_conn() as conn:
        conn.executescript("\n".join(drop_stmts + create_stmts))
    _INITIALIZED = True


def is_initialized():
    """Return whether the database schema has been set up."""
    return _INITIALIZED


def _add_inventory_item(conn, campaign_id, item_slug, quantity, owner):
    """Insert or increment an inventory stack for the given owner."""
    row = conn.execute(
        "SELECT quantity FROM inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
        (campaign_id, item_slug, owner),
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?)",
            (campaign_id, item_slug, quantity, owner),
        )
        return quantity
    new_quantity = row["quantity"] + quantity
    conn.execute(
        "UPDATE inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
        (new_quantity, campaign_id, item_slug, owner),
    )
    return new_quantity


def _assign_equipment(conn, campaign_id, character_id, item_slug, quantity):
    """Move quantity of an item from the party pool to a character."""
    party_row = conn.execute(
        "SELECT quantity FROM inventory WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'",
        (campaign_id, item_slug),
    ).fetchone()
    if party_row is None or party_row["quantity"] < quantity:
        raise ValueError("insufficient quantity")

    remaining = party_row["quantity"] - quantity
    if remaining == 0:
        conn.execute(
            "DELETE FROM inventory WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'",
            (campaign_id, item_slug),
        )
    else:
        conn.execute(
            "UPDATE inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'",
            (remaining, campaign_id, item_slug),
        )

    char_row = conn.execute(
        "SELECT quantity FROM inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
        (campaign_id, item_slug, character_id),
    ).fetchone()
    if char_row is None:
        conn.execute(
            "INSERT INTO inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?)",
            (campaign_id, item_slug, quantity, character_id),
        )
    else:
        conn.execute(
            "UPDATE inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
            (char_row["quantity"] + quantity, campaign_id, item_slug, character_id),
        )


def _get_inventory_summary(conn, campaign_id):
    """Return party/assigned counts and available healing potions."""
    party_items = conn.execute(
        "SELECT COUNT(DISTINCT item_slug) AS count FROM inventory WHERE campaign_id = ? AND owner = 'party'",
        (campaign_id,),
    ).fetchone()["count"] or 0

    assigned_items = conn.execute(
        "SELECT COUNT(DISTINCT item_slug) AS count FROM inventory WHERE campaign_id = ? AND owner != 'party'",
        (campaign_id,),
    ).fetchone()["count"] or 0

    healing_potions = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS total FROM inventory WHERE campaign_id = ? AND owner = 'party' AND item_slug = ?",
        (campaign_id, "healing-potion"),
    ).fetchone()["total"]

    return {
        "party_items": party_items,
        "assigned_items": assigned_items,
        "healing_potions_available": healing_potions,
    }


def init_db():
    """Reset and recreate the database schema on startup.

    Each benchmark run starts from a clean SQLite database so that
    cumulative tests see a deterministic empty state. The tables are
    dropped and recreated in dependency order.
    """
    global _INITIALIZED
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    reset_db()
