"""SQLite persistence layer.

One connection is opened per operation (SQLite handles this cheaply and
avoids cross-request connection-sharing bugs under the dev server's
threaded request handling). Writes are serialized through ``_lock`` since
sqlite3 connections are not safe to write from multiple threads at once.
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "game.db")

SCHEMA_VERSION = 1

TABLES = (
    "users",
    "combat_sessions",
    "monsters",
    "items",
    "campaigns",
    "campaign_characters",
    "campaign_events",
    "quests",
    "factions",
    "npcs",
    "campaign_inventory",
    "character_equipment",
    "crafting_projects",
    "campaign_sessions",
    "session_attendance",
    "play_campaigns",
    "play_campaign_members",
    "play_campaign_events",
    "play_campaign_scenes",
    "play_campaign_locations",
    "play_campaign_connections",
    "play_campaign_encounters",
    "play_campaign_character_spells",
    "play_campaign_character_prepared_spells",
    "play_campaign_character_casts",
    "play_campaign_gold_transfers",
    "play_campaign_loot",
    "play_campaign_loot_votes",
    "play_campaign_npcs",
    "play_campaign_npc_dialogue",
    "play_campaign_factions",
    "play_campaign_faction_reputation",
    "play_campaign_relationships",
    "play_campaign_clues",
    "play_campaign_quests",
    "play_campaign_character_rewards",
    "play_campaign_world_events",
    "play_campaign_calendars",
    "play_campaign_settlements",
    "play_campaign_shops",
    "play_campaign_recipes",
    "play_campaign_downtime_activities",
    "play_campaign_downtime_allocations",
    "play_campaign_session_zero",
    "play_campaign_content",
    "play_campaign_notes",
    "play_campaign_whispers",
    "play_campaign_invitations",
)

_lock = threading.Lock()
_initialized = False


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def _read_connection():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def _write_connection():
    """Serialize writers and commit on successful exit; a raised exception skips the commit."""
    with _lock:
        conn = get_connection()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _ensure_column(conn, table, existing_columns, column, ddl):
    """Add ``column`` to ``table`` via ALTER TABLE if it isn't already present.

    Used to migrate tables created by an older server process in place,
    since ``CREATE TABLE IF NOT EXISTS`` alone won't add columns introduced
    by later stages.
    """
    if column not in existing_columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _create_tables(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            password_hash TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS combat_sessions (
            id TEXT PRIMARY KEY,
            round INTEGER NOT NULL,
            turn_index INTEGER NOT NULL,
            combatants TEXT NOT NULL
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
            tags TEXT NOT NULL
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
        CREATE TABLE IF NOT EXISTS campaign_characters (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            level INTEGER NOT NULL,
            class TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS campaign_events (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            kind TEXT NOT NULL,
            summary TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS quests (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            milestones TEXT NOT NULL,
            completed TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS factions (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            stance TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS npcs (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            faction_id TEXT,
            disposition INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS campaign_inventory (
            campaign_id TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            owner TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, item_slug, owner)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS character_equipment (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, character_id, item_slug)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crafting_projects (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            days_required INTEGER NOT NULL,
            days_completed INTEGER NOT NULL,
            cost_gp INTEGER NOT NULL,
            status TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS campaign_sessions (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            agenda TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS session_attendance (
            campaign_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            present TEXT NOT NULL,
            absent TEXT NOT NULL,
            PRIMARY KEY (campaign_id, session_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaigns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            owner TEXT NOT NULL,
            status TEXT NOT NULL,
            max_players INTEGER NOT NULL,
            current_actor TEXT,
            turn_number INTEGER,
            nudge_count INTEGER NOT NULL DEFAULT 0,
            story TEXT NOT NULL DEFAULT '',
            dm_notes TEXT NOT NULL DEFAULT '',
            current_scene_id TEXT,
            current_location_id TEXT
        )
        """
    )
    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(play_campaigns)")}
    _ensure_column(conn, "play_campaigns", existing_columns, "current_actor", "current_actor TEXT")
    _ensure_column(conn, "play_campaigns", existing_columns, "turn_number", "turn_number INTEGER")
    _ensure_column(
        conn, "play_campaigns", existing_columns, "nudge_count",
        "nudge_count INTEGER NOT NULL DEFAULT 0",
    )
    _ensure_column(conn, "play_campaigns", existing_columns, "story", "story TEXT NOT NULL DEFAULT ''")
    _ensure_column(
        conn, "play_campaigns", existing_columns, "dm_notes", "dm_notes TEXT NOT NULL DEFAULT ''"
    )
    _ensure_column(conn, "play_campaigns", existing_columns, "current_scene_id", "current_scene_id TEXT")
    _ensure_column(
        conn, "play_campaigns", existing_columns, "current_location_id", "current_location_id TEXT"
    )
    _ensure_column(
        conn, "play_campaigns", existing_columns, "combat_phase",
        "combat_phase TEXT NOT NULL DEFAULT 'exploration'",
    )
    _ensure_column(
        conn, "play_campaigns", existing_columns, "pre_combat_actor", "pre_combat_actor TEXT"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_members (
            campaign_id TEXT NOT NULL,
            username TEXT NOT NULL,
            character_id TEXT NOT NULL,
            name TEXT NOT NULL,
            class TEXT NOT NULL,
            hp_current INTEGER NOT NULL DEFAULT 20,
            hp_max INTEGER NOT NULL DEFAULT 20,
            PRIMARY KEY (campaign_id, username)
        )
        """
    )
    existing_member_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(play_campaign_members)")
    }
    m = "play_campaign_members"
    _ensure_column(conn, m, existing_member_columns, "hp_current", "hp_current INTEGER NOT NULL DEFAULT 20")
    _ensure_column(conn, m, existing_member_columns, "hp_max", "hp_max INTEGER NOT NULL DEFAULT 20")
    _ensure_column(conn, m, existing_member_columns, "status", "status TEXT NOT NULL DEFAULT 'alive'")
    _ensure_column(
        conn, m, existing_member_columns, "death_save_successes",
        "death_save_successes INTEGER NOT NULL DEFAULT 0",
    )
    _ensure_column(
        conn, m, existing_member_columns, "death_save_failures",
        "death_save_failures INTEGER NOT NULL DEFAULT 0",
    )
    _ensure_column(conn, m, existing_member_columns, "owner", "owner TEXT")
    _ensure_column(conn, m, existing_member_columns, "race", "race TEXT")
    _ensure_column(conn, m, existing_member_columns, "background", "background TEXT")
    _ensure_column(conn, m, existing_member_columns, "level", "level INTEGER NOT NULL DEFAULT 1")
    _ensure_column(
        conn, m, existing_member_columns, "proficiency_bonus",
        "proficiency_bonus INTEGER NOT NULL DEFAULT 2",
    )
    _ensure_column(
        conn, m, existing_member_columns, "con_modifier", "con_modifier INTEGER NOT NULL DEFAULT 0"
    )
    _ensure_column(
        conn, m, existing_member_columns, "ability_modifiers",
        "ability_modifiers TEXT NOT NULL DEFAULT '{}'",
    )
    _ensure_column(conn, m, existing_member_columns, "gold", "gold INTEGER NOT NULL DEFAULT 10")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_events (
            campaign_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            kind TEXT NOT NULL,
            actor TEXT NOT NULL,
            text TEXT NOT NULL,
            type TEXT,
            PRIMARY KEY (campaign_id, sequence)
        )
        """
    )
    existing_event_columns = {row["name"] for row in conn.execute("PRAGMA table_info(play_campaign_events)")}
    e = "play_campaign_events"
    _ensure_column(conn, e, existing_event_columns, "type", "type TEXT")
    _ensure_column(conn, e, existing_event_columns, "destination_id", "destination_id TEXT")
    _ensure_column(conn, e, existing_event_columns, "travel_turns", "travel_turns INTEGER")
    _ensure_column(conn, e, existing_event_columns, "hp_current", "hp_current INTEGER")
    _ensure_column(conn, e, existing_event_columns, "hp_max", "hp_max INTEGER")
    _ensure_column(conn, e, existing_event_columns, "target", "target TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_scenes (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_locations (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_connections (
            campaign_id TEXT NOT NULL,
            from_id TEXT NOT NULL,
            to_id TEXT NOT NULL,
            travel_turns INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, from_id, to_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_encounters (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            combatants TEXT NOT NULL DEFAULT '[]',
            round INTEGER NOT NULL DEFAULT 1,
            turn_index INTEGER NOT NULL DEFAULT 0,
            conditions TEXT NOT NULL DEFAULT '{}',
            turn_order TEXT NOT NULL DEFAULT '[]',
            rewards TEXT,
            xp_awarded INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (campaign_id, id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_character_spells (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            spell_id TEXT NOT NULL,
            name TEXT NOT NULL,
            level INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, character_id, spell_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_character_prepared_spells (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            spell_ids TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY (campaign_id, character_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_character_casts (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            spell_id TEXT NOT NULL,
            target TEXT NOT NULL,
            slot_level INTEGER NOT NULL,
            slots_remaining INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, character_id, sequence)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_character_concentration (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            spell_id TEXT NOT NULL,
            target TEXT NOT NULL,
            remaining_turns INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, character_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_character_inventory_items (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, character_id, item_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_character_equipment (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            slot TEXT NOT NULL,
            item_id TEXT NOT NULL,
            attuned INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (campaign_id, character_id, slot)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_gold_transfers (
            campaign_id TEXT NOT NULL,
            transfer_id INTEGER NOT NULL,
            from_character_id TEXT NOT NULL,
            to_character_id TEXT NOT NULL,
            gold INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, transfer_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_loot (
            campaign_id TEXT NOT NULL,
            loot_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            status TEXT NOT NULL,
            recipient_character_id TEXT,
            PRIMARY KEY (campaign_id, loot_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (
            campaign_id TEXT NOT NULL,
            loot_id TEXT NOT NULL,
            voter TEXT NOT NULL,
            recipient_character_id TEXT NOT NULL,
            PRIMARY KEY (campaign_id, loot_id, voter)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_npcs (
            campaign_id TEXT NOT NULL,
            npc_id TEXT NOT NULL,
            name TEXT NOT NULL,
            agenda TEXT NOT NULL,
            public_status TEXT NOT NULL,
            PRIMARY KEY (campaign_id, npc_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (
            campaign_id TEXT NOT NULL,
            npc_id TEXT NOT NULL,
            dialogue_id TEXT NOT NULL,
            speaker TEXT NOT NULL,
            text TEXT NOT NULL,
            visibility TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, npc_id, dialogue_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_factions (
            campaign_id TEXT NOT NULL,
            faction_id TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (campaign_id, faction_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_faction_reputation (
            campaign_id TEXT NOT NULL,
            faction_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            reputation INTEGER NOT NULL,
            delta INTEGER NOT NULL,
            reason TEXT NOT NULL,
            sequence INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_relationships (
            campaign_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            score INTEGER NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, source_id, target_id, kind)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_clues (
            campaign_id TEXT NOT NULL,
            clue_id TEXT NOT NULL,
            text TEXT NOT NULL,
            audience TEXT NOT NULL,
            character_id TEXT,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, clue_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_quests (
            campaign_id TEXT NOT NULL,
            quest_id TEXT NOT NULL,
            title TEXT NOT NULL,
            depends_on TEXT NOT NULL,
            state TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            rewards_xp INTEGER,
            rewards_items TEXT,
            awarded INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (campaign_id, quest_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_character_rewards (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            xp INTEGER NOT NULL DEFAULT 0,
            items TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (campaign_id, character_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_world_events (
            campaign_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            turn_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL,
            resolution_turn_number INTEGER,
            resolution_text TEXT,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, event_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_calendars (
            campaign_id TEXT NOT NULL PRIMARY KEY,
            day INTEGER NOT NULL,
            season TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_settlements (
            campaign_id TEXT NOT NULL,
            settlement_id TEXT NOT NULL,
            name TEXT NOT NULL,
            services TEXT NOT NULL,
            availability TEXT NOT NULL,
            discovered_by TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, settlement_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_shops (
            campaign_id TEXT NOT NULL,
            settlement_id TEXT NOT NULL,
            shop_id TEXT NOT NULL,
            name TEXT NOT NULL,
            stock TEXT NOT NULL,
            buy_price INTEGER NOT NULL,
            sell_price INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, settlement_id, shop_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_recipes (
            campaign_id TEXT NOT NULL,
            recipe_id TEXT NOT NULL,
            name TEXT NOT NULL,
            ingredients TEXT NOT NULL,
            output_item TEXT NOT NULL,
            output_quantity INTEGER NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, recipe_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (
            campaign_id TEXT NOT NULL,
            activity_id TEXT NOT NULL,
            name TEXT NOT NULL,
            cycles_required INTEGER NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, activity_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_downtime_allocations (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            activity_id TEXT NOT NULL,
            cycles_completed INTEGER NOT NULL,
            completions INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, character_id, activity_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_session_zero (
            campaign_id TEXT NOT NULL PRIMARY KEY,
            rules TEXT NOT NULL,
            tone TEXT NOT NULL,
            consent TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_content (
            campaign_id TEXT NOT NULL,
            content_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            tags TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, content_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_notes (
            campaign_id TEXT NOT NULL,
            note_id TEXT NOT NULL,
            text TEXT NOT NULL,
            visibility TEXT NOT NULL,
            owner TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, note_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_whispers (
            campaign_id TEXT NOT NULL,
            whisper_id TEXT NOT NULL,
            from_character_id TEXT NOT NULL,
            to_character_id TEXT NOT NULL,
            text TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, whisper_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_campaign_invitations (
            campaign_id TEXT NOT NULL,
            invitation_id TEXT NOT NULL,
            username TEXT NOT NULL,
            character_id TEXT NOT NULL,
            status TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, invitation_id)
        )
        """
    )
    conn.commit()


def init_schema():
    """Start each server process with a blank store.

    A fresh process is a fresh game world: nothing survives a server restart
    (only requests within a single running process share state). Any leftover
    file from a prior process is discarded before the schema is (re)created."""
    global _initialized
    with _lock:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        conn = get_connection()
        try:
            _create_tables(conn)
        finally:
            conn.close()
        _initialized = True


def reset_schema():
    """Recreate all tables except ``users``: registered accounts and play-campaign
    sessions must survive a storage reset, matching the reference server's
    behavior where the reset only clears monsters/items/campaigns."""
    global _initialized
    with _lock:
        conn = get_connection()
        try:
            for table in TABLES:
                if table in (
                    "users",
                    "play_campaigns",
                    "play_campaign_members",
                    "play_campaign_scenes",
                    "play_campaign_locations",
                    "play_campaign_connections",
                    "play_campaign_encounters",
                    "play_campaign_character_spells",
                    "play_campaign_character_prepared_spells",
                    "play_campaign_character_casts",
                ):
                    continue
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            _create_tables(conn)
        finally:
            conn.close()
        _initialized = True


def is_initialized():
    return _initialized


# --- users ---


def get_user(username):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT username, role, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None:
        return None
    return {"username": row["username"], "role": row["role"], "password_hash": row["password_hash"]}


def create_user(username, role, password_hash):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO users (username, role, password_hash) VALUES (?, ?, ?)",
            (username, role, password_hash),
        )


# --- combat sessions ---


def get_session(session_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT id, round, turn_index, combatants FROM combat_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "round": row["round"],
        "turn_index": row["turn_index"],
        "order": json.loads(row["combatants"]),
    }


def create_session(session):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO combat_sessions (id, round, turn_index, combatants) VALUES (?, ?, ?, ?)",
            (session["id"], session["round"], session["turn_index"], json.dumps(session["order"])),
        )


def save_session(session):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE combat_sessions SET round = ?, turn_index = ?, combatants = ? WHERE id = ?",
            (session["round"], session["turn_index"], json.dumps(session["order"]), session["id"]),
        )


# --- monsters ---


def get_monster(slug):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters WHERE slug = ?",
            (slug,),
        ).fetchone()
    if row is None:
        return None
    return {
        "slug": row["slug"],
        "name": row["name"],
        "cr": row["cr"],
        "armor_class": row["armor_class"],
        "hit_points": row["hit_points"],
        "tags": json.loads(row["tags"]),
    }


def create_monster(monster):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)",
            (
                monster["slug"],
                monster["name"],
                monster["cr"],
                monster["armor_class"],
                monster["hit_points"],
                json.dumps(monster["tags"]),
            ),
        )


# --- items ---


def get_item(slug):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?",
            (slug,),
        ).fetchone()
    if row is None:
        return None
    return {
        "slug": row["slug"],
        "name": row["name"],
        "type": row["type"],
        "rarity": row["rarity"],
        "cost_gp": row["cost_gp"],
    }


def create_item(item):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
            (item["slug"], item["name"], item["type"], item["rarity"], item["cost_gp"]),
        )


# --- campaigns ---


def get_campaign(campaign_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT id, name, dm FROM campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "name": row["name"], "dm": row["dm"]}


def create_campaign(campaign):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
            (campaign["id"], campaign["name"], campaign["dm"]),
        )


def get_campaign_character(campaign_id, character_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? AND id = ?",
            (campaign_id, character_id),
        ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "name": row["name"], "level": row["level"], "class": row["class"]}


def list_campaign_characters(campaign_id):
    with _read_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
    return [{"id": r["id"], "name": r["name"], "level": r["level"], "class": r["class"]} for r in rows]


def create_campaign_character(campaign_id, character):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO campaign_characters (campaign_id, id, name, level, class) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, character["id"], character["name"], character["level"], character["class"]),
        )


def get_campaign_event(campaign_id, event_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT id, kind, summary FROM campaign_events WHERE campaign_id = ? AND id = ?",
            (campaign_id, event_id),
        ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "kind": row["kind"], "summary": row["summary"]}


def count_campaign_events(campaign_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM campaign_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    return row["c"]


def create_campaign_event(campaign_id, event):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO campaign_events (campaign_id, id, kind, summary) VALUES (?, ?, ?, ?)",
            (campaign_id, event["id"], event["kind"], event["summary"]),
        )


# --- quests ---


def get_quest(campaign_id, quest_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT id, title, status, milestones, completed FROM quests WHERE campaign_id = ? AND id = ?",
            (campaign_id, quest_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "milestones": json.loads(row["milestones"]),
        "completed": json.loads(row["completed"]),
    }


def list_quests(campaign_id):
    with _read_connection() as conn:
        rows = conn.execute(
            "SELECT id, title, status, milestones, completed FROM quests WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "status": r["status"],
            "milestones": json.loads(r["milestones"]),
            "completed": json.loads(r["completed"]),
        }
        for r in rows
    ]


def create_quest(campaign_id, quest):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO quests (campaign_id, id, title, status, milestones, completed) VALUES (?, ?, ?, ?, ?, ?)",
            (
                campaign_id,
                quest["id"],
                quest["title"],
                quest["status"],
                json.dumps(quest["milestones"]),
                json.dumps(quest["completed"]),
            ),
        )


def save_quest(campaign_id, quest):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE quests SET title = ?, status = ?, milestones = ?, completed = ? WHERE campaign_id = ? AND id = ?",
            (
                quest["title"],
                quest["status"],
                json.dumps(quest["milestones"]),
                json.dumps(quest["completed"]),
                campaign_id,
                quest["id"],
            ),
        )


# --- factions ---


def get_faction(campaign_id, faction_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT id, name, stance FROM factions WHERE campaign_id = ? AND id = ?",
            (campaign_id, faction_id),
        ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "name": row["name"], "stance": row["stance"]}


def count_factions(campaign_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM factions WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    return row["c"]


def create_faction(campaign_id, faction):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO factions (campaign_id, id, name, stance) VALUES (?, ?, ?, ?)",
            (campaign_id, faction["id"], faction["name"], faction["stance"]),
        )


# --- npcs ---


def get_npc(campaign_id, npc_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT id, name, faction_id, disposition FROM npcs WHERE campaign_id = ? AND id = ?",
            (campaign_id, npc_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "faction_id": row["faction_id"],
        "disposition": row["disposition"],
    }


def list_npcs(campaign_id):
    with _read_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, faction_id, disposition FROM npcs WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "faction_id": r["faction_id"],
            "disposition": r["disposition"],
        }
        for r in rows
    ]


def create_npc(campaign_id, npc):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO npcs (campaign_id, id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, npc["id"], npc["name"], npc["faction_id"], npc["disposition"]),
        )


def count_campaign_characters(campaign_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM campaign_characters WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    return row["c"]


def count_quests(campaign_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM quests WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    return row["c"]


def count_npcs(campaign_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM npcs WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    return row["c"]


def count_campaign_sessions(campaign_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM campaign_sessions WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    return row["c"]


def count_all_inventory_entries(campaign_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM campaign_inventory WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    return row["c"]


# --- inventory & equipment ---


def add_inventory_item(campaign_id, item_slug, owner, quantity):
    with _write_connection() as conn:
        row = conn.execute(
            "SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
            (campaign_id, item_slug, owner),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)",
                (campaign_id, item_slug, owner, quantity),
            )
        else:
            conn.execute(
                "UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
                (row["quantity"] + quantity, campaign_id, item_slug, owner),
            )


def count_inventory_entries(campaign_id, owner):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM campaign_inventory WHERE campaign_id = ? AND owner = ?",
            (campaign_id, owner),
        ).fetchone()
    return row["c"]


def get_inventory_quantity(campaign_id, item_slug, owner):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
            (campaign_id, item_slug, owner),
        ).fetchone()
    return row["quantity"] if row is not None else 0


def assign_equipment(campaign_id, character_id, item_slug, quantity):
    with _write_connection() as conn:
        row = conn.execute(
            "SELECT quantity FROM character_equipment WHERE campaign_id = ? AND character_id = ? AND item_slug = ?",
            (campaign_id, character_id, item_slug),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO character_equipment (campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?)",
                (campaign_id, character_id, item_slug, quantity),
            )
        else:
            conn.execute(
                "UPDATE character_equipment SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_slug = ?",
                (row["quantity"] + quantity, campaign_id, character_id, item_slug),
            )


def count_equipment_entries(campaign_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM character_equipment WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    return row["c"]


def get_assigned_quantity(campaign_id, item_slug):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS c FROM character_equipment WHERE campaign_id = ? AND item_slug = ?",
            (campaign_id, item_slug),
        ).fetchone()
    return row["c"]


# --- downtime crafting ---


def get_crafting_project(campaign_id, project_id):
    with _read_connection() as conn:
        row = conn.execute(
            """
            SELECT id, character_id, item_slug, days_required, days_completed, cost_gp, status
            FROM crafting_projects WHERE campaign_id = ? AND id = ?
            """,
            (campaign_id, project_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "character_id": row["character_id"],
        "item_slug": row["item_slug"],
        "days_required": row["days_required"],
        "days_completed": row["days_completed"],
        "cost_gp": row["cost_gp"],
        "status": row["status"],
    }


def create_crafting_project(campaign_id, project):
    with _write_connection() as conn:
        conn.execute(
            """
            INSERT INTO crafting_projects
                (campaign_id, id, character_id, item_slug, days_required, days_completed, cost_gp, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                project["id"],
                project["character_id"],
                project["item_slug"],
                project["days_required"],
                project["days_completed"],
                project["cost_gp"],
                project["status"],
            ),
        )


def save_crafting_project(campaign_id, project):
    with _write_connection() as conn:
        conn.execute(
            """
            UPDATE crafting_projects
            SET days_completed = ?, status = ?
            WHERE campaign_id = ? AND id = ?
            """,
            (project["days_completed"], project["status"], campaign_id, project["id"]),
        )


# --- session scheduling ---


def get_campaign_session(campaign_id, session_id):
    with _read_connection() as conn:
        row = conn.execute(
            """
            SELECT id, starts_at, duration_minutes, agenda
            FROM campaign_sessions WHERE campaign_id = ? AND id = ?
            """,
            (campaign_id, session_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "starts_at": row["starts_at"],
        "duration_minutes": row["duration_minutes"],
        "agenda": json.loads(row["agenda"]),
    }


def create_campaign_session(campaign_id, session):
    with _write_connection() as conn:
        conn.execute(
            """
            INSERT INTO campaign_sessions (campaign_id, id, starts_at, duration_minutes, agenda)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                session["id"],
                session["starts_at"],
                session["duration_minutes"],
                json.dumps(session["agenda"]),
            ),
        )


def get_next_campaign_session(campaign_id):
    with _read_connection() as conn:
        row = conn.execute(
            """
            SELECT id, starts_at, duration_minutes, agenda
            FROM campaign_sessions WHERE campaign_id = ?
            ORDER BY starts_at ASC, rowid ASC LIMIT 1
            """,
            (campaign_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "starts_at": row["starts_at"],
        "duration_minutes": row["duration_minutes"],
        "agenda": json.loads(row["agenda"]),
    }


def get_session_attendance(campaign_id, session_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT present, absent FROM session_attendance WHERE campaign_id = ? AND session_id = ?",
            (campaign_id, session_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "present": json.loads(row["present"]),
        "absent": json.loads(row["absent"]),
    }


def save_session_attendance(campaign_id, session_id, present, absent):
    with _write_connection() as conn:
        conn.execute(
            """
            INSERT INTO session_attendance (campaign_id, session_id, present, absent)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (campaign_id, session_id)
            DO UPDATE SET present = excluded.present, absent = excluded.absent
            """,
            (campaign_id, session_id, json.dumps(present), json.dumps(absent)),
        )


def _next_event_sequence(conn, campaign_id):
    """Return the next 1-based ``sequence`` for a play campaign's event log.

    Must be called from within the caller's ``_write_connection`` block so
    the read-then-insert is covered by the same lock/transaction and two
    concurrent event inserts can't compute the same sequence number.
    """
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_events WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    return row["max_sequence"] + 1


# --- play campaigns ---


def get_play_campaign(campaign_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT id, name, owner, status, max_players, current_actor, turn_number, nudge_count, "
            "story, dm_notes, current_scene_id, current_location_id, combat_phase, pre_combat_actor "
            "FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "owner": row["owner"],
        "status": row["status"],
        "max_players": row["max_players"],
        "current_actor": row["current_actor"],
        "turn_number": row["turn_number"],
        "nudge_count": row["nudge_count"],
        "story": row["story"],
        "dm_notes": row["dm_notes"],
        "current_scene_id": row["current_scene_id"],
        "current_location_id": row["current_location_id"],
        "combat_phase": row["combat_phase"],
        "pre_combat_actor": row["pre_combat_actor"],
    }


def create_play_campaign(campaign):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)",
            (
                campaign["id"],
                campaign["name"],
                campaign["owner"],
                campaign["status"],
                campaign["max_players"],
            ),
        )


def start_play_campaign(campaign_id, current_actor, turn_number):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaigns SET status = 'active', current_actor = ?, turn_number = ? "
            "WHERE id = ?",
            (current_actor, turn_number, campaign_id),
        )


def set_play_campaign_current_actor(campaign_id, current_actor):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaigns SET current_actor = ? WHERE id = ?",
            (current_actor, campaign_id),
        )


def advance_play_campaign_turn(campaign_id, current_actor, turn_number):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaigns SET current_actor = ?, turn_number = ? WHERE id = ?",
            (current_actor, turn_number, campaign_id),
        )


def enter_play_campaign_combat(campaign_id, pre_combat_actor):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaigns SET combat_phase = 'combat', pre_combat_actor = ? WHERE id = ?",
            (pre_combat_actor, campaign_id),
        )


def exit_play_campaign_combat(campaign_id, current_actor):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaigns SET combat_phase = 'exploration', current_actor = ?, "
            "pre_combat_actor = NULL WHERE id = ?",
            (current_actor, campaign_id),
        )


def increment_play_campaign_nudge_count(campaign_id):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaigns SET nudge_count = nudge_count + 1 WHERE id = ?",
            (campaign_id,),
        )
        row = conn.execute(
            "SELECT nudge_count FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
    return row["nudge_count"]


def update_play_campaign_document(campaign_id, story, dm_notes):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaigns SET story = ?, dm_notes = ? WHERE id = ?",
            (story, dm_notes, campaign_id),
        )


def get_play_campaign_session_zero(campaign_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT rules, tone, consent FROM play_campaign_session_zero WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "rules": row["rules"],
        "tone": row["tone"],
        "consent": json.loads(row["consent"]),
    }


def set_play_campaign_session_zero(campaign_id, rules, tone, consent):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO play_campaign_session_zero (campaign_id, rules, tone, consent) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id) DO UPDATE SET rules = excluded.rules, "
            "tone = excluded.tone, consent = excluded.consent",
            (campaign_id, rules, tone, json.dumps(consent)),
        )


def get_play_campaign_members(campaign_id):
    with _read_connection() as conn:
        rows = conn.execute(
            "SELECT campaign_id, username, character_id, name, class, hp_current, hp_max "
            "FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
    return [
        {
            "username": row["username"],
            "character_id": row["character_id"],
            "name": row["name"],
            "class": row["class"],
            "hp_current": row["hp_current"],
            "hp_max": row["hp_max"],
        }
        for row in rows
    ]


def get_play_campaign_member(campaign_id, username):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT username, character_id, name, class, hp_current, hp_max "
            "FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
    if row is None:
        return None
    return {
        "username": row["username"],
        "character_id": row["character_id"],
        "name": row["name"],
        "class": row["class"],
        "hp_current": row["hp_current"],
        "hp_max": row["hp_max"],
    }


def get_play_campaign_member_by_character(campaign_id, character_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT username, character_id, name, class, hp_current, hp_max, status, "
            "death_save_successes, death_save_failures, owner, level, proficiency_bonus, "
            "con_modifier, ability_modifiers, gold FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "username": row["username"],
        "character_id": row["character_id"],
        "name": row["name"],
        "class": row["class"],
        "hp_current": row["hp_current"],
        "hp_max": row["hp_max"],
        "status": row["status"],
        "death_save_successes": row["death_save_successes"],
        "death_save_failures": row["death_save_failures"],
        "owner": row["owner"],
        "level": row["level"],
        "proficiency_bonus": row["proficiency_bonus"],
        "con_modifier": row["con_modifier"],
        "ability_modifiers": json.loads(row["ability_modifiers"]),
        "gold": row["gold"],
    }


def create_play_campaign_member(campaign_id, member):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, owner) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                campaign_id,
                member["username"],
                member["character_id"],
                member["name"],
                member["class"],
                member["username"],
            ),
        )


def set_play_campaign_member_hp(campaign_id, username, hp_current):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_members SET hp_current = ? WHERE campaign_id = ? AND username = ?",
            (hp_current, campaign_id, username),
        )


def set_play_campaign_member_hp_and_status(campaign_id, username, hp_current, status):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_members SET hp_current = ?, status = ? "
            "WHERE campaign_id = ? AND username = ?",
            (hp_current, status, campaign_id, username),
        )


def set_play_campaign_member_death_saves(campaign_id, username, successes, failures, status):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_members SET death_save_successes = ?, death_save_failures = ?, "
            "status = ? WHERE campaign_id = ? AND username = ?",
            (successes, failures, status, campaign_id, username),
        )


def set_play_campaign_member_owner(campaign_id, username, owner):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND username = ?",
            (owner, campaign_id, username),
        )


def set_play_campaign_member_build(
    campaign_id,
    username,
    race,
    char_class,
    background,
    level,
    hp_max,
    proficiency_bonus,
    con_modifier,
    ability_modifiers,
):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_members SET race = ?, class = ?, background = ?, level = ?, "
            "hp_max = ?, hp_current = ?, proficiency_bonus = ?, con_modifier = ?, ability_modifiers = ? "
            "WHERE campaign_id = ? AND username = ?",
            (
                race,
                char_class,
                background,
                level,
                hp_max,
                hp_max,
                proficiency_bonus,
                con_modifier,
                json.dumps(ability_modifiers),
                campaign_id,
                username,
            ),
        )


def set_play_campaign_member_level_up(campaign_id, username, level, hp_max, hp_current, proficiency_bonus):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_members SET level = ?, hp_max = ?, hp_current = ?, "
            "proficiency_bonus = ? WHERE campaign_id = ? AND username = ?",
            (level, hp_max, hp_current, proficiency_bonus, campaign_id, username),
        )


def list_play_campaign_events(campaign_id, limit=10):
    with _read_connection() as conn:
        rows = conn.execute(
            "SELECT sequence, kind, actor, text, type, destination_id, travel_turns, "
            "hp_current, hp_max, target "
            "FROM play_campaign_events "
            "WHERE campaign_id = ? ORDER BY sequence DESC LIMIT ?",
            (campaign_id, limit),
        ).fetchall()
    events = []
    for row in rows:
        event = {
            "sequence": row["sequence"],
            "kind": row["kind"],
            "actor": row["actor"],
        }
        if row["kind"] == "travel":
            event["destination_id"] = row["destination_id"]
            event["travel_turns"] = row["travel_turns"]
        elif row["kind"] == "rest":
            event["type"] = row["type"]
            event["hp_current"] = row["hp_current"]
            event["hp_max"] = row["hp_max"]
        elif row["kind"] == "combat_action":
            event["type"] = row["type"]
            event["target"] = row["target"]
            event["text"] = row["text"]
        else:
            event["text"] = row["text"]
            if row["type"] is not None:
                event["type"] = row["type"]
        events.append(event)
    return events


def create_play_campaign_event(campaign_id, kind, actor, text, event_type=None):
    with _write_connection() as conn:
        sequence = _next_event_sequence(conn, campaign_id)
        conn.execute(
            "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text, type) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, sequence, kind, actor, text, event_type),
        )
    event = {"sequence": sequence, "kind": kind, "actor": actor, "text": text}
    if event_type is not None:
        event["type"] = event_type
    return event


def create_play_campaign_travel_event(campaign_id, actor, destination_id, travel_turns):
    with _write_connection() as conn:
        sequence = _next_event_sequence(conn, campaign_id)
        conn.execute(
            "INSERT INTO play_campaign_events "
            "(campaign_id, sequence, kind, actor, text, destination_id, travel_turns) "
            "VALUES (?, ?, 'travel', ?, '', ?, ?)",
            (campaign_id, sequence, actor, destination_id, travel_turns),
        )
    return {
        "sequence": sequence,
        "kind": "travel",
        "actor": actor,
        "destination_id": destination_id,
        "travel_turns": travel_turns,
    }


def create_play_campaign_rest_event(campaign_id, actor, rest_type, hp_current, hp_max):
    with _write_connection() as conn:
        sequence = _next_event_sequence(conn, campaign_id)
        conn.execute(
            "INSERT INTO play_campaign_events "
            "(campaign_id, sequence, kind, actor, text, type, hp_current, hp_max) "
            "VALUES (?, ?, 'rest', ?, '', ?, ?, ?)",
            (campaign_id, sequence, actor, rest_type, hp_current, hp_max),
        )
    return {
        "sequence": sequence,
        "kind": "rest",
        "actor": actor,
        "type": rest_type,
        "hp_current": hp_current,
        "hp_max": hp_max,
    }


def create_play_campaign_combat_action_event(campaign_id, actor, action_type, target, text):
    with _write_connection() as conn:
        sequence = _next_event_sequence(conn, campaign_id)
        conn.execute(
            "INSERT INTO play_campaign_events "
            "(campaign_id, sequence, kind, actor, text, type, target) "
            "VALUES (?, ?, 'combat_action', ?, ?, ?, ?)",
            (campaign_id, sequence, actor, text, action_type, target),
        )
    return {
        "sequence": sequence,
        "kind": "combat_action",
        "actor": actor,
        "type": action_type,
        "target": target,
        "text": text,
    }


# --- play campaign scenes ---


def get_play_scene(campaign_id, scene_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT id, name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?",
            (campaign_id, scene_id),
        ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "name": row["name"], "status": row["status"]}


def create_play_scene(campaign_id, scene):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO play_campaign_scenes (campaign_id, id, name, status) VALUES (?, ?, ?, ?)",
            (campaign_id, scene["id"], scene["name"], scene["status"]),
        )


def close_play_scene(campaign_id, scene_id):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_scenes SET status = 'closed' WHERE campaign_id = ? AND id = ?",
            (campaign_id, scene_id),
        )


def set_play_campaign_current_scene(campaign_id, scene_id):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?",
            (scene_id, campaign_id),
        )


# --- play campaign locations ---


def get_play_location(campaign_id, location_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT id, name FROM play_campaign_locations WHERE campaign_id = ? AND id = ?",
            (campaign_id, location_id),
        ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "name": row["name"]}


def create_play_location(campaign_id, location):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO play_campaign_locations (campaign_id, id, name) VALUES (?, ?, ?)",
            (campaign_id, location["id"], location["name"]),
        )
        conn.execute(
            "UPDATE play_campaigns SET current_location_id = ? "
            "WHERE id = ? AND current_location_id IS NULL",
            (location["id"], campaign_id),
        )


def set_play_campaign_current_location(campaign_id, location_id):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaigns SET current_location_id = ? WHERE id = ?",
            (location_id, campaign_id),
        )


def get_play_connection(campaign_id, from_id, to_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT from_id, to_id, travel_turns FROM play_campaign_connections "
            "WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
            (campaign_id, from_id, to_id),
        ).fetchone()
    if row is None:
        return None
    return {"from_id": row["from_id"], "to_id": row["to_id"], "travel_turns": row["travel_turns"]}


def create_play_connection(campaign_id, from_id, to_id, travel_turns):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO play_campaign_connections (campaign_id, from_id, to_id, travel_turns) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, from_id, to_id, travel_turns),
        )


def list_play_connections(campaign_id, from_id):
    with _read_connection() as conn:
        rows = conn.execute(
            "SELECT c.to_id AS to_id, l.name AS name, c.travel_turns AS travel_turns "
            "FROM play_campaign_connections c "
            "JOIN play_campaign_locations l ON l.campaign_id = c.campaign_id AND l.id = c.to_id "
            "WHERE c.campaign_id = ? AND c.from_id = ? "
            "ORDER BY c.to_id",
            (campaign_id, from_id),
        ).fetchall()
    return [{"id": row["to_id"], "name": row["name"], "travel_turns": row["travel_turns"]} for row in rows]


def get_play_campaign_encounter(campaign_id, encounter_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT id, name, status, combatants, round, turn_index, conditions, turn_order, "
            "rewards, xp_awarded "
            "FROM play_campaign_encounters WHERE campaign_id = ? AND id = ?",
            (campaign_id, encounter_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "status": row["status"],
        "combatants": json.loads(row["combatants"]),
        "round": row["round"],
        "turn_index": row["turn_index"],
        "conditions": json.loads(row["conditions"]),
        "turn_order": json.loads(row["turn_order"]),
        "rewards": json.loads(row["rewards"]) if row["rewards"] is not None else None,
        "xp_awarded": row["xp_awarded"],
    }


def set_play_campaign_encounter_combatants(campaign_id, encounter_id, combatants):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_encounters SET combatants = ? WHERE campaign_id = ? AND id = ?",
            (json.dumps(combatants), campaign_id, encounter_id),
        )


def set_play_campaign_encounter_turn(campaign_id, encounter_id, round_number, turn_index):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_encounters SET round = ?, turn_index = ? "
            "WHERE campaign_id = ? AND id = ?",
            (round_number, turn_index, campaign_id, encounter_id),
        )


def set_play_campaign_encounter_conditions(campaign_id, encounter_id, conditions):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_encounters SET conditions = ? WHERE campaign_id = ? AND id = ?",
            (json.dumps(conditions), campaign_id, encounter_id),
        )


def set_play_campaign_encounter_turn_order(campaign_id, encounter_id, turn_order, turn_index):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_encounters SET turn_order = ?, turn_index = ? "
            "WHERE campaign_id = ? AND id = ?",
            (json.dumps(turn_order), turn_index, campaign_id, encounter_id),
        )


def get_active_play_campaign_encounter(campaign_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT id, name, status, combatants, round, turn_index, conditions, turn_order "
            "FROM play_campaign_encounters WHERE campaign_id = ? AND status = 'active'",
            (campaign_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "status": row["status"],
        "combatants": json.loads(row["combatants"]),
        "round": row["round"],
        "turn_index": row["turn_index"],
        "conditions": json.loads(row["conditions"]),
        "turn_order": json.loads(row["turn_order"]),
    }


def set_play_campaign_encounter_rewards(campaign_id, encounter_id, rewards):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_encounters SET rewards = ? WHERE campaign_id = ? AND id = ?",
            (json.dumps(rewards), campaign_id, encounter_id),
        )


def set_play_campaign_encounter_status_and_xp(campaign_id, encounter_id, status, xp_awarded):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_encounters SET status = ?, xp_awarded = ? "
            "WHERE campaign_id = ? AND id = ?",
            (status, xp_awarded, campaign_id, encounter_id),
        )


# --- play campaign character spells ---


def list_play_campaign_character_spells(campaign_id, character_id):
    with _read_connection() as conn:
        rows = conn.execute(
            "SELECT spell_id, name, level FROM play_campaign_character_spells "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY rowid",
            (campaign_id, character_id),
        ).fetchall()
    return [{"spell_id": row["spell_id"], "name": row["name"], "level": row["level"]} for row in rows]


def get_play_campaign_character_spell(campaign_id, character_id, spell_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT spell_id, name, level FROM play_campaign_character_spells "
            "WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
            (campaign_id, character_id, spell_id),
        ).fetchone()
    if row is None:
        return None
    return {"spell_id": row["spell_id"], "name": row["name"], "level": row["level"]}


def create_play_campaign_character_spell(campaign_id, character_id, spell):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO play_campaign_character_spells "
            "(campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, character_id, spell["spell_id"], spell["name"], spell["level"]),
        )


def get_play_campaign_character_prepared_spells(campaign_id, character_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT spell_ids FROM play_campaign_character_prepared_spells "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
    if row is None:
        return []
    return json.loads(row["spell_ids"])


def set_play_campaign_character_prepared_spells(campaign_id, character_id, spell_ids):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO play_campaign_character_prepared_spells "
            "(campaign_id, character_id, spell_ids) VALUES (?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id) DO UPDATE SET spell_ids = excluded.spell_ids",
            (campaign_id, character_id, json.dumps(spell_ids)),
        )


def count_play_campaign_character_casts_at_level(campaign_id, character_id, slot_level):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM play_campaign_character_casts "
            "WHERE campaign_id = ? AND character_id = ? AND slot_level = ?",
            (campaign_id, character_id, slot_level),
        ).fetchone()
    return row["n"]


def create_play_campaign_character_cast(campaign_id, character_id, cast):
    with _write_connection() as conn:
        sequence = (
            conn.execute(
                "SELECT COUNT(*) AS n FROM play_campaign_character_casts "
                "WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()["n"]
            + 1
        )
        conn.execute(
            "INSERT INTO play_campaign_character_casts "
            "(campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                campaign_id,
                character_id,
                sequence,
                cast["spell_id"],
                cast["target"],
                cast["slot_level"],
                cast["slots_remaining"],
            ),
        )
    return sequence


def list_play_campaign_character_casts(campaign_id, character_id):
    with _read_connection() as conn:
        rows = conn.execute(
            "SELECT spell_id, target, slot_level, slots_remaining, sequence "
            "FROM play_campaign_character_casts "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY sequence",
            (campaign_id, character_id),
        ).fetchall()
    return [
        {
            "spell_id": row["spell_id"],
            "target": row["target"],
            "slot_level": row["slot_level"],
            "slots_remaining": row["slots_remaining"],
            "sequence": row["sequence"],
        }
        for row in rows
    ]


def get_play_campaign_character_concentration(campaign_id, character_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT spell_id, target, remaining_turns FROM play_campaign_character_concentration "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "spell_id": row["spell_id"],
        "target": row["target"],
        "remaining_turns": row["remaining_turns"],
    }


def set_play_campaign_character_concentration(campaign_id, character_id, concentration):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO play_campaign_character_concentration "
            "(campaign_id, character_id, spell_id, target, remaining_turns) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id) DO UPDATE SET "
            "spell_id = excluded.spell_id, target = excluded.target, remaining_turns = excluded.remaining_turns",
            (
                campaign_id,
                character_id,
                concentration["spell_id"],
                concentration["target"],
                concentration["remaining_turns"],
            ),
        )


def clear_play_campaign_character_concentration(campaign_id, character_id):
    with _write_connection() as conn:
        conn.execute(
            "DELETE FROM play_campaign_character_concentration "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        )


def list_play_campaign_character_inventory_items(campaign_id, character_id):
    with _read_connection() as conn:
        rows = conn.execute(
            "SELECT item_id, quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY item_id",
            (campaign_id, character_id),
        ).fetchall()
    return [{"item_id": row["item_id"], "quantity": row["quantity"]} for row in rows]


def get_play_campaign_character_inventory_item(campaign_id, character_id, item_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT item_id, quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()
    if row is None:
        return None
    return {"item_id": row["item_id"], "quantity": row["quantity"]}


def add_play_campaign_character_inventory_item(campaign_id, character_id, item_id, quantity):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO play_campaign_character_inventory_items "
            "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE SET "
            "quantity = quantity + excluded.quantity",
            (campaign_id, character_id, item_id, quantity),
        )
        row = conn.execute(
            "SELECT quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()
    return row["quantity"]


def remove_play_campaign_character_inventory_item(campaign_id, character_id, item_id, quantity):
    with _write_connection() as conn:
        row = conn.execute(
            "SELECT quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()
        held = row["quantity"] if row is not None else 0
        if quantity > held:
            return None
        remaining = held - quantity
        if remaining == 0:
            conn.execute(
                "DELETE FROM play_campaign_character_inventory_items "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, character_id, item_id),
            )
        else:
            conn.execute(
                "UPDATE play_campaign_character_inventory_items SET quantity = ? "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (remaining, campaign_id, character_id, item_id),
            )
    return remaining


def get_play_campaign_character_equipment(campaign_id, character_id, slot):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT item_id, attuned FROM play_campaign_character_equipment "
            "WHERE campaign_id = ? AND character_id = ? AND slot = ?",
            (campaign_id, character_id, slot),
        ).fetchone()
    if row is None:
        return None
    return {"item_id": row["item_id"], "attuned": bool(row["attuned"])}


def set_play_campaign_character_equipment(campaign_id, character_id, slot, item_id):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO play_campaign_character_equipment "
            "(campaign_id, character_id, slot, item_id, attuned) VALUES (?, ?, ?, ?, 0) "
            "ON CONFLICT (campaign_id, character_id, slot) DO UPDATE SET "
            "item_id = excluded.item_id, attuned = 0",
            (campaign_id, character_id, slot, item_id),
        )


def set_play_campaign_character_equipment_attuned(campaign_id, character_id, slot):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_character_equipment SET attuned = 1 "
            "WHERE campaign_id = ? AND character_id = ? AND slot = ?",
            (campaign_id, character_id, slot),
        )


def count_play_campaign_character_attunements(campaign_id, character_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM play_campaign_character_equipment "
            "WHERE campaign_id = ? AND character_id = ? AND attuned = 1",
            (campaign_id, character_id),
        ).fetchone()
    return row["c"]


def get_play_campaign_character_gold(campaign_id, character_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
    if row is None:
        return None
    return row["gold"]


def transfer_play_campaign_gold(campaign_id, from_character_id, to_character_id, gold):
    """Debit ``from_character_id`` and credit ``to_character_id`` atomically.

    Returns None if the source lacks sufficient gold, otherwise a dict with
    the resulting balances and the assigned campaign-local transfer id.
    """
    with _write_connection() as conn:
        from_row = conn.execute(
            "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, from_character_id),
        ).fetchone()
        if from_row is None or from_row["gold"] < gold:
            return None

        to_row = conn.execute(
            "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, to_character_id),
        ).fetchone()

        from_gold = from_row["gold"] - gold
        to_gold = to_row["gold"] + gold

        conn.execute(
            "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?",
            (from_gold, campaign_id, from_character_id),
        )
        conn.execute(
            "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?",
            (to_gold, campaign_id, to_character_id),
        )

        next_id_row = conn.execute(
            "SELECT COALESCE(MAX(transfer_id), 0) + 1 AS next_id "
            "FROM play_campaign_gold_transfers WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        transfer_id = next_id_row["next_id"]

        conn.execute(
            "INSERT INTO play_campaign_gold_transfers "
            "(campaign_id, transfer_id, from_character_id, to_character_id, gold) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, transfer_id, from_character_id, to_character_id, gold),
        )

    return {
        "from_gold": from_gold,
        "to_gold": to_gold,
        "transfer_id": transfer_id,
    }


def create_play_campaign_loot(campaign_id, loot_id, item_id, quantity):
    """Create an open loot record, or return None if ``loot_id`` is already used."""
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT loot_id FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?",
            (campaign_id, loot_id),
        ).fetchone()
        if existing is not None:
            return None
        conn.execute(
            "INSERT INTO play_campaign_loot "
            "(campaign_id, loot_id, item_id, quantity, status, recipient_character_id) "
            "VALUES (?, ?, ?, ?, 'open', NULL)",
            (campaign_id, loot_id, item_id, quantity),
        )
    return {
        "loot_id": loot_id,
        "item_id": item_id,
        "quantity": quantity,
        "status": "open",
        "recipient_character_id": None,
    }


def get_play_campaign_loot(campaign_id, loot_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT loot_id, item_id, quantity, status, recipient_character_id "
            "FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?",
            (campaign_id, loot_id),
        ).fetchone()
        if row is None:
            return None
        votes_rows = conn.execute(
            "SELECT recipient_character_id, COUNT(*) AS c FROM play_campaign_loot_votes "
            "WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id",
            (campaign_id, loot_id),
        ).fetchall()
    return {
        "loot_id": row["loot_id"],
        "item_id": row["item_id"],
        "quantity": row["quantity"],
        "status": row["status"],
        "recipient_character_id": row["recipient_character_id"],
        "votes": {vr["recipient_character_id"]: vr["c"] for vr in votes_rows},
    }


def create_play_campaign_loot_vote(campaign_id, loot_id, voter, recipient_character_id):
    """Cast an immutable vote, or return None if ``voter`` has already voted on this loot."""
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT voter FROM play_campaign_loot_votes "
            "WHERE campaign_id = ? AND loot_id = ? AND voter = ?",
            (campaign_id, loot_id, voter),
        ).fetchone()
        if existing is not None:
            return None
        conn.execute(
            "INSERT INTO play_campaign_loot_votes "
            "(campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)",
            (campaign_id, loot_id, voter, recipient_character_id),
        )
        votes_row = conn.execute(
            "SELECT COUNT(*) AS c FROM play_campaign_loot_votes "
            "WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?",
            (campaign_id, loot_id, recipient_character_id),
        ).fetchone()
    return {"votes_for_recipient": votes_row["c"]}


def assign_play_campaign_loot(campaign_id, loot_id):
    """Assign loot to its unambiguous top-voted recipient atomically.

    Returns ``(result, error)`` where ``error`` is one of ``"not_found"``,
    ``"not_open"``, or ``"no_winner"`` (voteless or tied), with ``result``
    None in that case.
    """
    with _write_connection() as conn:
        loot = conn.execute(
            "SELECT loot_id, item_id, quantity, status FROM play_campaign_loot "
            "WHERE campaign_id = ? AND loot_id = ?",
            (campaign_id, loot_id),
        ).fetchone()
        if loot is None:
            return None, "not_found"
        if loot["status"] != "open":
            return None, "not_open"

        tally_rows = conn.execute(
            "SELECT recipient_character_id, COUNT(*) AS c FROM play_campaign_loot_votes "
            "WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id",
            (campaign_id, loot_id),
        ).fetchall()
        if not tally_rows:
            return None, "no_winner"

        best = max(row["c"] for row in tally_rows)
        winners = [row["recipient_character_id"] for row in tally_rows if row["c"] == best]
        if len(winners) != 1:
            return None, "no_winner"
        recipient_character_id = winners[0]

        conn.execute(
            "INSERT INTO play_campaign_character_inventory_items "
            "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE SET "
            "quantity = quantity + excluded.quantity",
            (campaign_id, recipient_character_id, loot["item_id"], loot["quantity"]),
        )
        conn.execute(
            "UPDATE play_campaign_loot SET status = 'assigned', recipient_character_id = ? "
            "WHERE campaign_id = ? AND loot_id = ?",
            (recipient_character_id, campaign_id, loot_id),
        )

    return {
        "loot_id": loot["loot_id"],
        "recipient_character_id": recipient_character_id,
        "item_id": loot["item_id"],
        "quantity": loot["quantity"],
        "votes": best,
        "status": "assigned",
    }, None


def create_play_campaign_encounter(campaign_id, encounter):
    with _write_connection() as conn:
        conn.execute(
            "INSERT INTO play_campaign_encounters (campaign_id, id, name, status, combatants) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                campaign_id,
                encounter["id"],
                encounter["name"],
                encounter["status"],
                json.dumps(encounter["combatants"]),
            ),
        )


def create_play_campaign_npc(campaign_id, npc_id, name, agenda, public_status):
    """Create a campaign NPC, or return None if ``npc_id`` is already used."""
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT npc_id FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
        if existing is not None:
            return None
        conn.execute(
            "INSERT INTO play_campaign_npcs (campaign_id, npc_id, name, agenda, public_status) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, npc_id, name, agenda, public_status),
        )
    return {
        "npc_id": npc_id,
        "name": name,
        "agenda": agenda,
        "public_status": public_status,
    }


def get_play_campaign_npc(campaign_id, npc_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT npc_id, name, agenda, public_status FROM play_campaign_npcs "
            "WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "npc_id": row["npc_id"],
        "name": row["name"],
        "agenda": row["agenda"],
        "public_status": row["public_status"],
    }


def update_play_campaign_npc_agenda(campaign_id, npc_id, agenda, public_status):
    """Update an NPC's agenda and public status, or return None if it doesn't exist."""
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT npc_id, name FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
        if existing is None:
            return None
        conn.execute(
            "UPDATE play_campaign_npcs SET agenda = ?, public_status = ? "
            "WHERE campaign_id = ? AND npc_id = ?",
            (agenda, public_status, campaign_id, npc_id),
        )
        name = existing["name"]
    return {
        "npc_id": npc_id,
        "name": name,
        "agenda": agenda,
        "public_status": public_status,
    }


def create_play_campaign_npc_dialogue(campaign_id, npc_id, dialogue_id, speaker, text, visibility):
    """Append a dialogue entry, or return None if ``dialogue_id`` is already used for this NPC."""
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT dialogue_id FROM play_campaign_npc_dialogue "
            "WHERE campaign_id = ? AND npc_id = ? AND dialogue_id = ?",
            (campaign_id, npc_id, dialogue_id),
        ).fetchone()
        if existing is not None:
            return None

        seq_row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_npc_dialogue "
            "WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
        sequence = seq_row["max_seq"] + 1

        conn.execute(
            "INSERT INTO play_campaign_npc_dialogue "
            "(campaign_id, npc_id, dialogue_id, speaker, text, visibility, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, npc_id, dialogue_id, speaker, text, visibility, sequence),
        )
    return {
        "dialogue_id": dialogue_id,
        "speaker": speaker,
        "text": text,
        "visibility": visibility,
    }


def list_play_campaign_npc_dialogue(campaign_id, npc_id):
    """Dialogue entries for an NPC in insertion order."""
    with _read_connection() as conn:
        rows = conn.execute(
            "SELECT dialogue_id, speaker, text, visibility FROM play_campaign_npc_dialogue "
            "WHERE campaign_id = ? AND npc_id = ? ORDER BY sequence ASC",
            (campaign_id, npc_id),
        ).fetchall()
    return [
        {
            "dialogue_id": row["dialogue_id"],
            "speaker": row["speaker"],
            "text": row["text"],
            "visibility": row["visibility"],
        }
        for row in rows
    ]


# --- factions ---


def create_play_campaign_faction(campaign_id, faction_id, name):
    """Create a campaign faction, or return None if ``faction_id`` is already used."""
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT faction_id FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?",
            (campaign_id, faction_id),
        ).fetchone()
        if existing is not None:
            return None
        conn.execute(
            "INSERT INTO play_campaign_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)",
            (campaign_id, faction_id, name),
        )
    return {"faction_id": faction_id, "name": name}


def get_play_campaign_faction(campaign_id, faction_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT faction_id, name FROM play_campaign_factions "
            "WHERE campaign_id = ? AND faction_id = ?",
            (campaign_id, faction_id),
        ).fetchone()
    if row is None:
        return None
    return {"faction_id": row["faction_id"], "name": row["name"]}


def create_play_campaign_faction_reputation_entry(campaign_id, faction_id, character_id, delta, reason):
    """Append an immutable reputation history entry, bounding the running total to [-100, 100]."""
    with _write_connection() as conn:
        row = conn.execute(
            "SELECT reputation FROM play_campaign_faction_reputation "
            "WHERE campaign_id = ? AND faction_id = ? AND character_id = ? "
            "ORDER BY sequence DESC LIMIT 1",
            (campaign_id, faction_id, character_id),
        ).fetchone()
        current = row["reputation"] if row is not None else 0
        new_total = max(-100, min(100, current + delta))

        seq_row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_faction_reputation "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = seq_row["max_seq"] + 1

        conn.execute(
            "INSERT INTO play_campaign_faction_reputation "
            "(campaign_id, faction_id, character_id, reputation, delta, reason, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, faction_id, character_id, new_total, delta, reason, sequence),
        )
    return {
        "faction_id": faction_id,
        "character_id": character_id,
        "reputation": new_total,
        "delta": delta,
        "reason": reason,
    }


def list_play_campaign_faction_reputation(campaign_id, faction_id, character_id=None):
    """History entries in insertion order, optionally filtered to one character."""
    with _read_connection() as conn:
        if character_id is None:
            rows = conn.execute(
                "SELECT faction_id, character_id, reputation, delta, reason "
                "FROM play_campaign_faction_reputation "
                "WHERE campaign_id = ? AND faction_id = ? ORDER BY sequence ASC",
                (campaign_id, faction_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT faction_id, character_id, reputation, delta, reason "
                "FROM play_campaign_faction_reputation "
                "WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY sequence ASC",
                (campaign_id, faction_id, character_id),
            ).fetchall()
    return [
        {
            "faction_id": row["faction_id"],
            "character_id": row["character_id"],
            "reputation": row["reputation"],
            "delta": row["delta"],
            "reason": row["reason"],
        }
        for row in rows
    ]


def create_play_campaign_relationship(campaign_id, source_id, target_id, kind, score):
    """Create a directed relationship edge, or return None if it already exists."""
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_relationships "
            "WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
            (campaign_id, source_id, target_id, kind),
        ).fetchone()
        if existing is not None:
            return None
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_relationships "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["max_seq"] + 1
        conn.execute(
            "INSERT INTO play_campaign_relationships "
            "(campaign_id, source_id, target_id, kind, score, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, source_id, target_id, kind, score, next_sequence),
        )
    return {
        "source_id": source_id,
        "target_id": target_id,
        "kind": kind,
        "score": score,
    }


def get_play_campaign_relationship(campaign_id, source_id, target_id, kind):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT source_id, target_id, kind, score FROM play_campaign_relationships "
            "WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
            (campaign_id, source_id, target_id, kind),
        ).fetchone()
    if row is None:
        return None
    return {
        "source_id": row["source_id"],
        "target_id": row["target_id"],
        "kind": row["kind"],
        "score": row["score"],
    }


def update_play_campaign_relationship(campaign_id, source_id, target_id, kind, score):
    """Update an edge's score, or return None if the edge doesn't exist."""
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_relationships "
            "WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
            (campaign_id, source_id, target_id, kind),
        ).fetchone()
        if existing is None:
            return None
        conn.execute(
            "UPDATE play_campaign_relationships SET score = ? "
            "WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
            (score, campaign_id, source_id, target_id, kind),
        )
    return {
        "source_id": source_id,
        "target_id": target_id,
        "kind": kind,
        "score": score,
    }


def list_play_campaign_relationships(campaign_id):
    """All edges for a campaign in insertion order."""
    with _read_connection() as conn:
        rows = conn.execute(
            "SELECT source_id, target_id, kind, score FROM play_campaign_relationships "
            "WHERE campaign_id = ? ORDER BY sequence ASC",
            (campaign_id,),
        ).fetchall()
    return [
        {
            "source_id": row["source_id"],
            "target_id": row["target_id"],
            "kind": row["kind"],
            "score": row["score"],
        }
        for row in rows
    ]


def _clue_row_to_dict(row):
    clue = {"clue_id": row["clue_id"], "text": row["text"], "audience": row["audience"]}
    if row["character_id"] is not None:
        clue["character_id"] = row["character_id"]
    return clue


def get_play_campaign_clue(campaign_id, clue_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT clue_id, text, audience, character_id FROM play_campaign_clues "
            "WHERE campaign_id = ? AND clue_id = ?",
            (campaign_id, clue_id),
        ).fetchone()
    if row is None:
        return None
    return _clue_row_to_dict(row)


def create_play_campaign_clue(campaign_id, clue_id, text, audience, character_id):
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_clues WHERE campaign_id = ? AND clue_id = ?",
            (campaign_id, clue_id),
        ).fetchone()
        if existing is not None:
            return None
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_clues "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["max_seq"] + 1
        conn.execute(
            "INSERT INTO play_campaign_clues "
            "(campaign_id, clue_id, text, audience, character_id, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, clue_id, text, audience, character_id, next_sequence),
        )
    clue = {"clue_id": clue_id, "text": text, "audience": audience}
    if character_id is not None:
        clue["character_id"] = character_id
    return clue


def list_play_campaign_clues(campaign_id):
    """All clues for a campaign in insertion order."""
    with _read_connection() as conn:
        rows = conn.execute(
            "SELECT clue_id, text, audience, character_id FROM play_campaign_clues "
            "WHERE campaign_id = ? ORDER BY sequence ASC",
            (campaign_id,),
        ).fetchall()
    return [_clue_row_to_dict(row) for row in rows]


QUEST_COLUMNS = "quest_id, title, depends_on, state, rewards_xp, rewards_items, awarded"


def _quest_row_to_dict(row):
    quest = {
        "quest_id": row["quest_id"],
        "title": row["title"],
        "depends_on": json.loads(row["depends_on"]),
        "state": row["state"],
    }
    if row["rewards_xp"] is not None:
        quest["rewards"] = {
            "xp": row["rewards_xp"],
            "items": json.loads(row["rewards_items"]),
        }
    return quest


def _quest_awarded(row):
    return bool(row["awarded"])


def get_play_campaign_quest(campaign_id, quest_id):
    with _read_connection() as conn:
        row = conn.execute(
            f"SELECT {QUEST_COLUMNS} FROM play_campaign_quests "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
    if row is None:
        return None
    quest = _quest_row_to_dict(row)
    quest["_awarded"] = _quest_awarded(row)
    return quest


def create_play_campaign_quest(campaign_id, quest_id, title, depends_on):
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if existing is not None:
            return None
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_quests "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["max_seq"] + 1
        conn.execute(
            "INSERT INTO play_campaign_quests "
            "(campaign_id, quest_id, title, depends_on, state, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, quest_id, title, json.dumps(depends_on), "locked", next_sequence),
        )
    return {"quest_id": quest_id, "title": title, "depends_on": depends_on, "state": "locked"}


def list_play_campaign_quests(campaign_id):
    """All quests for a campaign in creation order."""
    with _read_connection() as conn:
        rows = conn.execute(
            f"SELECT {QUEST_COLUMNS} FROM play_campaign_quests "
            "WHERE campaign_id = ? ORDER BY sequence ASC",
            (campaign_id,),
        ).fetchall()
    return [_quest_row_to_dict(row) for row in rows]


def update_play_campaign_quest_state(campaign_id, quest_id, state):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_quests SET state = ? "
            "WHERE campaign_id = ? AND quest_id = ?",
            (state, campaign_id, quest_id),
        )
        row = conn.execute(
            f"SELECT {QUEST_COLUMNS} FROM play_campaign_quests "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
    if row is None:
        return None
    return _quest_row_to_dict(row)


def set_play_campaign_quest_rewards(campaign_id, quest_id, xp, items):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_quests SET rewards_xp = ?, rewards_items = ? "
            "WHERE campaign_id = ? AND quest_id = ?",
            (xp, json.dumps(items), campaign_id, quest_id),
        )
        row = conn.execute(
            f"SELECT {QUEST_COLUMNS} FROM play_campaign_quests "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
    return _quest_row_to_dict(row)


def mark_play_campaign_quest_rewards_awarded(campaign_id, quest_id):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_quests SET awarded = 1 "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        )


def grant_play_campaign_character_reward(campaign_id, character_id, xp, items):
    with _write_connection() as conn:
        row = conn.execute(
            "SELECT xp, items FROM play_campaign_character_rewards "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if row is None:
            total_xp = xp
            total_items = dict(items)
            conn.execute(
                "INSERT INTO play_campaign_character_rewards "
                "(campaign_id, character_id, xp, items) VALUES (?, ?, ?, ?)",
                (campaign_id, character_id, total_xp, json.dumps(total_items)),
            )
        else:
            total_xp = row["xp"] + xp
            total_items = json.loads(row["items"])
            for item_id, quantity in items.items():
                total_items[item_id] = total_items.get(item_id, 0) + quantity
            conn.execute(
                "UPDATE play_campaign_character_rewards SET xp = ?, items = ? "
                "WHERE campaign_id = ? AND character_id = ?",
                (total_xp, json.dumps(total_items), campaign_id, character_id),
            )


def get_play_campaign_character_rewards(campaign_id, character_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT xp, items FROM play_campaign_character_rewards "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
    if row is None:
        return {"xp": 0, "items": {}}
    return {"xp": row["xp"], "items": json.loads(row["items"])}


WORLD_EVENT_COLUMNS = (
    "event_id, turn_number, title, text, status, resolution_turn_number, resolution_text"
)


def _world_event_row_to_dict(row):
    event = {
        "event_id": row["event_id"],
        "turn_number": row["turn_number"],
        "title": row["title"],
        "text": row["text"],
        "status": row["status"],
    }
    if row["status"] == "resolved":
        event["resolution"] = {
            "turn_number": row["resolution_turn_number"],
            "text": row["resolution_text"],
        }
    return event


def get_play_campaign_world_event(campaign_id, event_id):
    with _read_connection() as conn:
        row = conn.execute(
            f"SELECT {WORLD_EVENT_COLUMNS} FROM play_campaign_world_events "
            "WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
    if row is None:
        return None
    return _world_event_row_to_dict(row)


def create_play_campaign_world_event(campaign_id, event_id, turn_number, title, text):
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if existing is not None:
            return None
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_world_events "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["max_seq"] + 1
        conn.execute(
            "INSERT INTO play_campaign_world_events "
            "(campaign_id, event_id, turn_number, title, text, status, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, event_id, turn_number, title, text, "scheduled", next_sequence),
        )
    return {
        "event_id": event_id,
        "turn_number": turn_number,
        "title": title,
        "text": text,
        "status": "scheduled",
    }


def list_play_campaign_world_events(campaign_id):
    """All world events for a campaign ordered by turn_number, then creation order."""
    with _read_connection() as conn:
        rows = conn.execute(
            f"SELECT {WORLD_EVENT_COLUMNS} FROM play_campaign_world_events "
            "WHERE campaign_id = ? ORDER BY turn_number ASC, sequence ASC",
            (campaign_id,),
        ).fetchall()
    return [_world_event_row_to_dict(row) for row in rows]


def resolve_play_campaign_world_event(campaign_id, event_id, resolution_turn_number, text):
    with _write_connection() as conn:
        row = conn.execute(
            f"SELECT {WORLD_EVENT_COLUMNS} FROM play_campaign_world_events "
            "WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if row is None or row["status"] == "resolved":
            return None
        conn.execute(
            "UPDATE play_campaign_world_events SET status = ?, resolution_turn_number = ?, "
            "resolution_text = ? WHERE campaign_id = ? AND event_id = ?",
            ("resolved", resolution_turn_number, text, campaign_id, event_id),
        )
        row = conn.execute(
            f"SELECT {WORLD_EVENT_COLUMNS} FROM play_campaign_world_events "
            "WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
    return _world_event_row_to_dict(row)


SEASON_OFFSETS = {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}
WEATHER_BY_OFFSET = {0: "clear", 1: "rain", 2: "wind", 3: "snow"}


def _calendar_weather(day, season):
    offset = SEASON_OFFSETS[season]
    return WEATHER_BY_OFFSET[(day + offset) % 4]


def _calendar_row_to_dict(row):
    return {
        "day": row["day"],
        "season": row["season"],
        "weather": _calendar_weather(row["day"], row["season"]),
    }


def get_play_campaign_calendar(campaign_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    if row is None:
        return None
    return _calendar_row_to_dict(row)


def create_play_campaign_calendar(campaign_id, day, season):
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_calendars WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if existing is not None:
            return None
        conn.execute(
            "INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (?, ?, ?)",
            (campaign_id, day, season),
        )
    return {"day": day, "season": season, "weather": _calendar_weather(day, season)}


def advance_play_campaign_calendar(campaign_id, days):
    with _write_connection() as conn:
        row = conn.execute(
            "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        new_day = row["day"] + days
        conn.execute(
            "UPDATE play_campaign_calendars SET day = ? WHERE campaign_id = ?",
            (new_day, campaign_id),
        )
    return {
        "day": new_day,
        "season": row["season"],
        "weather": _calendar_weather(new_day, row["season"]),
    }


SETTLEMENT_COLUMNS = "settlement_id, name, services, availability, discovered_by"


def _settlement_row_to_dict(row):
    return {
        "settlement_id": row["settlement_id"],
        "name": row["name"],
        "services": json.loads(row["services"]),
        "availability": row["availability"],
        "discovered_by": json.loads(row["discovered_by"]),
    }


def get_play_campaign_settlement(campaign_id, settlement_id):
    with _read_connection() as conn:
        row = conn.execute(
            f"SELECT {SETTLEMENT_COLUMNS} FROM play_campaign_settlements "
            "WHERE campaign_id = ? AND settlement_id = ?",
            (campaign_id, settlement_id),
        ).fetchone()
    if row is None:
        return None
    return _settlement_row_to_dict(row)


def create_play_campaign_settlement(campaign_id, settlement_id, name, services, availability):
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?",
            (campaign_id, settlement_id),
        ).fetchone()
        if existing is not None:
            return None
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_settlements "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["max_seq"] + 1
        conn.execute(
            "INSERT INTO play_campaign_settlements "
            "(campaign_id, settlement_id, name, services, availability, discovered_by, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                campaign_id,
                settlement_id,
                name,
                json.dumps(services),
                availability,
                json.dumps([]),
                next_sequence,
            ),
        )
    return {
        "settlement_id": settlement_id,
        "name": name,
        "services": services,
        "availability": availability,
        "discovered_by": [],
    }


def update_play_campaign_settlement(campaign_id, settlement_id, name, services, availability):
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?",
            (campaign_id, settlement_id),
        ).fetchone()
        if existing is None:
            return None
        conn.execute(
            "UPDATE play_campaign_settlements SET name = ?, services = ?, availability = ? "
            "WHERE campaign_id = ? AND settlement_id = ?",
            (name, json.dumps(services), availability, campaign_id, settlement_id),
        )
        row = conn.execute(
            f"SELECT {SETTLEMENT_COLUMNS} FROM play_campaign_settlements "
            "WHERE campaign_id = ? AND settlement_id = ?",
            (campaign_id, settlement_id),
        ).fetchone()
    return _settlement_row_to_dict(row)


def list_play_campaign_settlements(campaign_id):
    """All settlements for a campaign in creation order."""
    with _read_connection() as conn:
        rows = conn.execute(
            f"SELECT {SETTLEMENT_COLUMNS} FROM play_campaign_settlements "
            "WHERE campaign_id = ? ORDER BY sequence ASC",
            (campaign_id,),
        ).fetchall()
    return [_settlement_row_to_dict(row) for row in rows]


def discover_play_campaign_settlement(campaign_id, settlement_id, character_id):
    """Append ``character_id`` to a settlement's discoverers if not already present.

    Returns ``(settlement, created)`` where ``created`` is True only on the
    first discovery by this character.
    """
    with _write_connection() as conn:
        row = conn.execute(
            f"SELECT {SETTLEMENT_COLUMNS} FROM play_campaign_settlements "
            "WHERE campaign_id = ? AND settlement_id = ?",
            (campaign_id, settlement_id),
        ).fetchone()
        if row is None:
            return None, False
        discovered_by = json.loads(row["discovered_by"])
        if character_id in discovered_by:
            return _settlement_row_to_dict(row), False
        discovered_by.append(character_id)
        conn.execute(
            "UPDATE play_campaign_settlements SET discovered_by = ? "
            "WHERE campaign_id = ? AND settlement_id = ?",
            (json.dumps(discovered_by), campaign_id, settlement_id),
        )
        row = conn.execute(
            f"SELECT {SETTLEMENT_COLUMNS} FROM play_campaign_settlements "
            "WHERE campaign_id = ? AND settlement_id = ?",
            (campaign_id, settlement_id),
        ).fetchone()
    return _settlement_row_to_dict(row), True


SHOP_COLUMNS = "shop_id, name, stock, buy_price, sell_price"


def _shop_row_to_dict(row):
    return {
        "shop_id": row["shop_id"],
        "name": row["name"],
        "stock": json.loads(row["stock"]),
        "buy_price": row["buy_price"],
        "sell_price": row["sell_price"],
    }


def get_play_campaign_shop(campaign_id, settlement_id, shop_id):
    with _read_connection() as conn:
        row = conn.execute(
            f"SELECT {SHOP_COLUMNS} FROM play_campaign_shops "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (campaign_id, settlement_id, shop_id),
        ).fetchone()
    if row is None:
        return None
    return _shop_row_to_dict(row)


def create_play_campaign_shop(campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price):
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_shops "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (campaign_id, settlement_id, shop_id),
        ).fetchone()
        if existing is not None:
            return None
        conn.execute(
            "INSERT INTO play_campaign_shops "
            "(campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, settlement_id, shop_id, name, json.dumps(stock), buy_price, sell_price),
        )
    return {
        "shop_id": shop_id,
        "name": name,
        "stock": stock,
        "buy_price": buy_price,
        "sell_price": sell_price,
    }


def buy_play_campaign_shop_item(campaign_id, settlement_id, shop_id, character_id, item_id, quantity):
    """Atomically decrement shop stock and character gold, and credit the item.

    Returns ``(result, error)`` where ``error`` is one of ``"shop_not_found"``,
    ``"character_not_found"``, ``"insufficient_stock"``, or
    ``"insufficient_gold"``, with ``result`` None in that case.
    """
    with _write_connection() as conn:
        shop_row = conn.execute(
            f"SELECT {SHOP_COLUMNS} FROM play_campaign_shops "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (campaign_id, settlement_id, shop_id),
        ).fetchone()
        if shop_row is None:
            return None, "shop_not_found"

        stock = json.loads(shop_row["stock"])
        available = stock.get(item_id, 0)
        if available < quantity:
            return None, "insufficient_stock"

        member_row = conn.execute(
            "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if member_row is None:
            return None, "character_not_found"

        cost = shop_row["buy_price"] * quantity
        if member_row["gold"] < cost:
            return None, "insufficient_gold"

        new_gold = member_row["gold"] - cost
        stock[item_id] = available - quantity

        conn.execute(
            "UPDATE play_campaign_shops SET stock = ? "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (json.dumps(stock), campaign_id, settlement_id, shop_id),
        )
        conn.execute(
            "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?",
            (new_gold, campaign_id, character_id),
        )
        conn.execute(
            "INSERT INTO play_campaign_character_inventory_items "
            "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE SET "
            "quantity = quantity + excluded.quantity",
            (campaign_id, character_id, item_id, quantity),
        )
    return {"gold": new_gold, "stock": stock[item_id]}, None


def sell_play_campaign_shop_item(campaign_id, settlement_id, shop_id, character_id, item_id, quantity):
    """Atomically credit shop stock and character gold, and debit the item.

    Returns ``(result, error)`` where ``error`` is one of ``"shop_not_found"``,
    ``"character_not_found"``, or ``"insufficient_inventory"``, with
    ``result`` None in that case.
    """
    with _write_connection() as conn:
        shop_row = conn.execute(
            f"SELECT {SHOP_COLUMNS} FROM play_campaign_shops "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (campaign_id, settlement_id, shop_id),
        ).fetchone()
        if shop_row is None:
            return None, "shop_not_found"

        item_row = conn.execute(
            "SELECT quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()
        held = item_row["quantity"] if item_row is not None else 0
        if held < quantity:
            return None, "insufficient_inventory"

        member_row = conn.execute(
            "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if member_row is None:
            return None, "character_not_found"

        proceeds = shop_row["sell_price"] * quantity
        new_gold = member_row["gold"] + proceeds
        remaining = held - quantity

        if remaining == 0:
            conn.execute(
                "DELETE FROM play_campaign_character_inventory_items "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, character_id, item_id),
            )
        else:
            conn.execute(
                "UPDATE play_campaign_character_inventory_items SET quantity = ? "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (remaining, campaign_id, character_id, item_id),
            )

        stock = json.loads(shop_row["stock"])
        stock[item_id] = stock.get(item_id, 0) + quantity
        conn.execute(
            "UPDATE play_campaign_shops SET stock = ? "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (json.dumps(stock), campaign_id, settlement_id, shop_id),
        )
        conn.execute(
            "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?",
            (new_gold, campaign_id, character_id),
        )
    return {"gold": new_gold, "stock": stock[item_id]}, None


def _recipe_row_to_dict(row):
    return {
        "recipe_id": row["recipe_id"],
        "name": row["name"],
        "ingredients": json.loads(row["ingredients"]),
        "output_item": row["output_item"],
        "output_quantity": row["output_quantity"],
    }


def get_play_campaign_recipe(campaign_id, recipe_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT recipe_id, name, ingredients, output_item, output_quantity "
            "FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?",
            (campaign_id, recipe_id),
        ).fetchone()
    if row is None:
        return None
    return _recipe_row_to_dict(row)


def list_play_campaign_recipes(campaign_id):
    with _read_connection() as conn:
        rows = conn.execute(
            "SELECT recipe_id, name, ingredients, output_item, output_quantity "
            "FROM play_campaign_recipes WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()
    return [_recipe_row_to_dict(row) for row in rows]


def create_play_campaign_recipe(campaign_id, recipe_id, name, ingredients, output_item, output_quantity):
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?",
            (campaign_id, recipe_id),
        ).fetchone()
        if existing is not None:
            return None
        sequence_row = conn.execute(
            "SELECT COALESCE(MAX(sequence), -1) + 1 AS next_sequence "
            "FROM play_campaign_recipes WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        conn.execute(
            "INSERT INTO play_campaign_recipes "
            "(campaign_id, recipe_id, name, ingredients, output_item, output_quantity, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                campaign_id,
                recipe_id,
                name,
                json.dumps(ingredients),
                output_item,
                output_quantity,
                sequence_row["next_sequence"],
            ),
        )
    return {
        "recipe_id": recipe_id,
        "name": name,
        "ingredients": ingredients,
        "output_item": output_item,
        "output_quantity": output_quantity,
    }


def craft_play_campaign_recipe(campaign_id, character_id, recipe):
    """Atomically consume a recipe's ingredients from a character's inventory and credit the output.

    Returns ``(ok, error)`` where ``error`` is ``"insufficient_ingredients"`` and
    ``ok`` is False in that case.
    """
    ingredients = recipe["ingredients"]
    with _write_connection() as conn:
        held = {}
        for item_id, required_quantity in ingredients.items():
            row = conn.execute(
                "SELECT quantity FROM play_campaign_character_inventory_items "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, character_id, item_id),
            ).fetchone()
            held[item_id] = row["quantity"] if row is not None else 0
            if held[item_id] < required_quantity:
                return False, "insufficient_ingredients"

        for item_id, required_quantity in ingredients.items():
            remaining = held[item_id] - required_quantity
            if remaining == 0:
                conn.execute(
                    "DELETE FROM play_campaign_character_inventory_items "
                    "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (campaign_id, character_id, item_id),
                )
            else:
                conn.execute(
                    "UPDATE play_campaign_character_inventory_items SET quantity = ? "
                    "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (remaining, campaign_id, character_id, item_id),
                )

        conn.execute(
            "INSERT INTO play_campaign_character_inventory_items "
            "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE SET "
            "quantity = quantity + excluded.quantity",
            (campaign_id, character_id, recipe["output_item"], recipe["output_quantity"]),
        )
    return True, None


def _downtime_activity_row_to_dict(row):
    return {
        "activity_id": row["activity_id"],
        "name": row["name"],
        "cycles_required": row["cycles_required"],
    }


def get_play_campaign_downtime_activity(campaign_id, activity_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT activity_id, name, cycles_required FROM play_campaign_downtime_activities "
            "WHERE campaign_id = ? AND activity_id = ?",
            (campaign_id, activity_id),
        ).fetchone()
    if row is None:
        return None
    return _downtime_activity_row_to_dict(row)


def create_play_campaign_downtime_activity(campaign_id, activity_id, name, cycles_required):
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?",
            (campaign_id, activity_id),
        ).fetchone()
        if existing is not None:
            return None
        sequence_row = conn.execute(
            "SELECT COALESCE(MAX(sequence), -1) + 1 AS next_sequence "
            "FROM play_campaign_downtime_activities WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        conn.execute(
            "INSERT INTO play_campaign_downtime_activities "
            "(campaign_id, activity_id, name, cycles_required, sequence) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, activity_id, name, cycles_required, sequence_row["next_sequence"]),
        )
    return {
        "activity_id": activity_id,
        "name": name,
        "cycles_required": cycles_required,
    }


def _downtime_allocation_row_to_dict(row):
    return {
        "character_id": row["character_id"],
        "activity_id": row["activity_id"],
        "cycles_completed": row["cycles_completed"],
        "completions": row["completions"],
    }


def get_play_campaign_downtime_allocation(campaign_id, character_id, activity_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT character_id, activity_id, cycles_completed, completions "
            "FROM play_campaign_downtime_allocations "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (campaign_id, character_id, activity_id),
        ).fetchone()
    if row is None:
        return None
    return _downtime_allocation_row_to_dict(row)


def create_play_campaign_downtime_allocation(campaign_id, character_id, activity_id):
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_downtime_allocations "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (campaign_id, character_id, activity_id),
        ).fetchone()
        if existing is not None:
            return None
        conn.execute(
            "INSERT INTO play_campaign_downtime_allocations "
            "(campaign_id, character_id, activity_id, cycles_completed, completions) "
            "VALUES (?, ?, ?, 0, 0)",
            (campaign_id, character_id, activity_id),
        )
    return {
        "character_id": character_id,
        "activity_id": activity_id,
        "cycles_completed": 0,
        "completions": 0,
    }


def advance_play_campaign_downtime_allocation(campaign_id, character_id, activity_id, cycles_required):
    with _write_connection() as conn:
        row = conn.execute(
            "SELECT cycles_completed, completions FROM play_campaign_downtime_allocations "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (campaign_id, character_id, activity_id),
        ).fetchone()
        if row is None:
            return None
        cycles_completed = row["cycles_completed"] + 1
        completions = row["completions"]
        if cycles_completed >= cycles_required:
            cycles_completed = 0
            completions += 1
        conn.execute(
            "UPDATE play_campaign_downtime_allocations SET cycles_completed = ?, completions = ? "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (cycles_completed, completions, campaign_id, character_id, activity_id),
        )
    return {
        "character_id": character_id,
        "activity_id": activity_id,
        "cycles_completed": cycles_completed,
        "completions": completions,
    }


def _content_row_to_dict(row):
    return {
        "content_id": row["content_id"],
        "kind": row["kind"],
        "text": row["text"],
        "tags": json.loads(row["tags"]),
    }


def get_play_campaign_content_item(campaign_id, content_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT content_id, kind, text, tags FROM play_campaign_content "
            "WHERE campaign_id = ? AND content_id = ?",
            (campaign_id, content_id),
        ).fetchone()
    if row is None:
        return None
    return _content_row_to_dict(row)


def create_play_campaign_content_item(campaign_id, content_id, kind, text, tags):
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?",
            (campaign_id, content_id),
        ).fetchone()
        if existing is not None:
            return None
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_content "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["max_seq"] + 1
        conn.execute(
            "INSERT INTO play_campaign_content "
            "(campaign_id, content_id, kind, text, tags, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, content_id, kind, text, json.dumps(tags), next_sequence),
        )
    return {"content_id": content_id, "kind": kind, "text": text, "tags": list(tags)}


def set_play_campaign_content_tags(campaign_id, content_id, tags):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_content SET tags = ? WHERE campaign_id = ? AND content_id = ?",
            (json.dumps(tags), campaign_id, content_id),
        )


def list_play_campaign_content(campaign_id):
    """All content records for a campaign in creation order."""
    with _read_connection() as conn:
        rows = conn.execute(
            "SELECT content_id, kind, text, tags FROM play_campaign_content "
            "WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()
    return [_content_row_to_dict(row) for row in rows]


def get_play_campaign_member_by_owner(campaign_id, owner):
    """The party member row currently owned/controlled by ``owner``, if any."""
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT username, character_id, name, class, hp_current, hp_max, status, "
            "death_save_successes, death_save_failures, owner, level, proficiency_bonus, "
            "con_modifier, ability_modifiers, gold FROM play_campaign_members "
            "WHERE campaign_id = ? AND owner = ?",
            (campaign_id, owner),
        ).fetchone()
    if row is None:
        return None
    return {
        "username": row["username"],
        "character_id": row["character_id"],
        "name": row["name"],
        "class": row["class"],
        "hp_current": row["hp_current"],
        "hp_max": row["hp_max"],
        "status": row["status"],
        "death_save_successes": row["death_save_successes"],
        "death_save_failures": row["death_save_failures"],
        "owner": row["owner"],
        "level": row["level"],
        "proficiency_bonus": row["proficiency_bonus"],
        "con_modifier": row["con_modifier"],
        "ability_modifiers": json.loads(row["ability_modifiers"]),
        "gold": row["gold"],
    }


def _note_row_to_dict(row):
    return {
        "note_id": row["note_id"],
        "text": row["text"],
        "visibility": row["visibility"],
        "owner": row["owner"],
    }


def get_play_campaign_note(campaign_id, note_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT note_id, text, visibility, owner FROM play_campaign_notes "
            "WHERE campaign_id = ? AND note_id = ?",
            (campaign_id, note_id),
        ).fetchone()
    if row is None:
        return None
    return _note_row_to_dict(row)


def create_play_campaign_note(campaign_id, note_id, text, visibility, owner):
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?",
            (campaign_id, note_id),
        ).fetchone()
        if existing is not None:
            return None
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_notes "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["max_seq"] + 1
        conn.execute(
            "INSERT INTO play_campaign_notes "
            "(campaign_id, note_id, text, visibility, owner, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, note_id, text, visibility, owner, next_sequence),
        )
    return {"note_id": note_id, "text": text, "visibility": visibility, "owner": owner}


def update_play_campaign_note(campaign_id, note_id, text, visibility):
    with _write_connection() as conn:
        conn.execute(
            "UPDATE play_campaign_notes SET text = ?, visibility = ? "
            "WHERE campaign_id = ? AND note_id = ?",
            (text, visibility, campaign_id, note_id),
        )


def list_play_campaign_notes(campaign_id):
    """All notes for a campaign in creation order."""
    with _read_connection() as conn:
        rows = conn.execute(
            "SELECT note_id, text, visibility, owner FROM play_campaign_notes "
            "WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()
    return [_note_row_to_dict(row) for row in rows]


def _whisper_row_to_dict(row):
    return {
        "whisper_id": row["whisper_id"],
        "from_character_id": row["from_character_id"],
        "to_character_id": row["to_character_id"],
        "text": row["text"],
    }


def get_play_campaign_whisper(campaign_id, whisper_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT whisper_id, from_character_id, to_character_id, text "
            "FROM play_campaign_whispers WHERE campaign_id = ? AND whisper_id = ?",
            (campaign_id, whisper_id),
        ).fetchone()
    if row is None:
        return None
    return _whisper_row_to_dict(row)


def create_play_campaign_whisper(campaign_id, whisper_id, from_character_id, to_character_id, text):
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_whispers WHERE campaign_id = ? AND whisper_id = ?",
            (campaign_id, whisper_id),
        ).fetchone()
        if existing is not None:
            return None
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_whispers "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["max_seq"] + 1
        conn.execute(
            "INSERT INTO play_campaign_whispers "
            "(campaign_id, whisper_id, from_character_id, to_character_id, text, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, whisper_id, from_character_id, to_character_id, text, next_sequence),
        )
    return {
        "whisper_id": whisper_id,
        "from_character_id": from_character_id,
        "to_character_id": to_character_id,
        "text": text,
    }


def list_play_campaign_whispers(campaign_id):
    """All whispers for a campaign in creation order."""
    with _read_connection() as conn:
        rows = conn.execute(
            "SELECT whisper_id, from_character_id, to_character_id, text "
            "FROM play_campaign_whispers WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()
    return [_whisper_row_to_dict(row) for row in rows]


def _invitation_row_to_dict(row):
    return {
        "invitation_id": row["invitation_id"],
        "username": row["username"],
        "character_id": row["character_id"],
        "status": row["status"],
    }


def get_play_campaign_invitation(campaign_id, invitation_id):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT invitation_id, username, character_id, status FROM play_campaign_invitations "
            "WHERE campaign_id = ? AND invitation_id = ?",
            (campaign_id, invitation_id),
        ).fetchone()
    if row is None:
        return None
    return _invitation_row_to_dict(row)


def get_play_campaign_pending_invitation_for_user(campaign_id, username):
    with _read_connection() as conn:
        row = conn.execute(
            "SELECT invitation_id, username, character_id, status FROM play_campaign_invitations "
            "WHERE campaign_id = ? AND username = ? AND status = 'pending'",
            (campaign_id, username),
        ).fetchone()
    if row is None:
        return None
    return _invitation_row_to_dict(row)


def create_play_campaign_invitation(campaign_id, invitation_id, username, character_id):
    with _write_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?",
            (campaign_id, invitation_id),
        ).fetchone()
        if existing is not None:
            return None
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_invitations "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["max_seq"] + 1
        conn.execute(
            "INSERT INTO play_campaign_invitations "
            "(campaign_id, invitation_id, username, character_id, status, sequence) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (campaign_id, invitation_id, username, character_id, next_sequence),
        )
    return {
        "invitation_id": invitation_id,
        "username": username,
        "character_id": character_id,
        "status": "pending",
    }


def accept_play_campaign_invitation(campaign_id, invitation_id, member=None):
    """Mark the invitation accepted, optionally adding ``member`` in the same transaction.

    ``member`` is only inserted if the campaign has no existing member row for
    that username, checked inside this same write connection to avoid a
    separate lock acquisition/round trip racing with the update.
    """
    with _write_connection() as conn:
        if member is not None:
            existing = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, member["username"]),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO play_campaign_members "
                    "(campaign_id, username, character_id, name, class, owner) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        campaign_id,
                        member["username"],
                        member["character_id"],
                        member["name"],
                        member["class"],
                        member["username"],
                    ),
                )
        conn.execute(
            "UPDATE play_campaign_invitations SET status = 'accepted' "
            "WHERE campaign_id = ? AND invitation_id = ?",
            (campaign_id, invitation_id),
        )


def list_play_campaign_invitations(campaign_id):
    """All invitations for a campaign in creation order."""
    with _read_connection() as conn:
        rows = conn.execute(
            "SELECT invitation_id, username, character_id, status FROM play_campaign_invitations "
            "WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()
    return [_invitation_row_to_dict(row) for row in rows]
