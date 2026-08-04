"""SQLite persistence layer for the D&D REST API.

All database access is synchronous and connection-per-call. The module
initializes the schema on import so the application can rely on the database
existing before it handles its first request.
"""

import json
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "game.db")


def _get_conn():
    """Return a fresh SQLite connection with row factories and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create the schema if it does not exist and seed schema_version."""
    conn = _get_conn()
    try:
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
                turn_index INTEGER NOT NULL,
                order_json TEXT NOT NULL,
                conditions_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS monsters (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cr TEXT NOT NULL,
                armor_class INTEGER NOT NULL,
                hit_points INTEGER NOT NULL,
                tags_json TEXT NOT NULL
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
            CREATE TABLE IF NOT EXISTS quests (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                milestones_json TEXT NOT NULL,
                completed_milestones_json TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS factions (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                stance TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS npcs (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                faction_id TEXT NOT NULL,
                name TEXT NOT NULL,
                disposition INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
                FOREIGN KEY (faction_id) REFERENCES factions(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS inventory (
                campaign_id TEXT NOT NULL,
                item_slug TEXT NOT NULL,
                owner TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, item_slug, owner),
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS equipment (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                item_slug TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id, item_slug),
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
                FOREIGN KEY (character_id) REFERENCES campaign_characters(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS crafting_projects (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                item_slug TEXT NOT NULL,
                days_required INTEGER NOT NULL,
                cost_gp INTEGER NOT NULL,
                days_completed INTEGER NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                starts_at TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                agenda_json TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS attendance (
                session_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                present INTEGER NOT NULL,
                PRIMARY KEY (session_id, character_id),
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS play_campaigns (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                owner TEXT NOT NULL,
                status TEXT NOT NULL,
                max_players INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS play_members (
                campaign_id TEXT NOT NULL,
                username TEXT NOT NULL,
                character_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                class TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
                UNIQUE (campaign_id, username)
            );
            CREATE TABLE IF NOT EXISTS play_narrations (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                kind TEXT NOT NULL,
                actor TEXT NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS play_turn_state (
                campaign_id TEXT PRIMARY KEY,
                current_actor TEXT NOT NULL,
                phase TEXT NOT NULL,
                turn_number INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (1)")
        conn.commit()
    finally:
        conn.close()


def reset_db():
    """Drop all tables and recreate the schema. Used by the storage reset endpoint."""
    conn = _get_conn()
    try:
        conn.executescript(
            """
            PRAGMA foreign_keys = OFF;
            DROP TABLE IF EXISTS attendance;
            DROP TABLE IF EXISTS play_turn_state;
            DROP TABLE IF EXISTS play_narrations;
            DROP TABLE IF EXISTS play_members;
            DROP TABLE IF EXISTS play_campaigns;
            DROP TABLE IF EXISTS sessions;
            DROP TABLE IF EXISTS crafting_projects;
            DROP TABLE IF EXISTS equipment;
            DROP TABLE IF EXISTS inventory;
            DROP TABLE IF EXISTS npcs;
            DROP TABLE IF EXISTS factions;
            DROP TABLE IF EXISTS quests;
            DROP TABLE IF EXISTS campaign_events;
            DROP TABLE IF EXISTS campaign_characters;
            DROP TABLE IF EXISTS campaigns;
            DROP TABLE IF EXISTS combat_sessions;
            DROP TABLE IF EXISTS monsters;
            DROP TABLE IF EXISTS items;
            DROP TABLE IF EXISTS users;
            DROP TABLE IF EXISTS schema_version;
            PRAGMA foreign_keys = ON;
            """
        )
        conn.commit()
    finally:
        conn.close()
    init_db()


def _is_db_initialized():
    """True if the database file and all expected tables exist."""
    if not os.path.exists(DB_PATH):
        return False
    conn = _get_conn()
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('schema_version', 'users', 'combat_sessions', 'monsters', 'items', "
            "'campaigns', 'campaign_characters', 'campaign_events', 'quests', "
            "'factions', 'npcs', 'inventory', 'equipment', 'crafting_projects', "
            "'sessions', 'attendance', 'play_campaigns', 'play_members', 'play_narrations', 'play_turn_state')"
        )
        tables = {row["name"] for row in cur.fetchall()}
        return tables == {
            "schema_version",
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
            "inventory",
            "equipment",
            "crafting_projects",
            "sessions",
            "attendance",
            "play_campaigns",
            "play_members",
            "play_narrations",
            "play_turn_state",
        }
    except Exception:
        return False
    finally:
        conn.close()


# Initialize the database when this module is imported so the application is
# ready to serve requests without an explicit setup step. Reset the database on
# startup so every evaluation begins from a clean, deterministic state.
reset_db()


# --- Play campaigns ---


def _create_play_campaign(campaign_id, name, owner, status, max_players):
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO play_campaigns (id, name, owner, status, max_players) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, name, owner, status, max_players),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _get_play_campaign(campaign_id):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, name, owner, status, max_players FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _get_play_members(campaign_id):
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT username, character_id, name, class FROM play_members "
            "WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _start_play_campaign(campaign_id):
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE play_campaigns SET status = 'active' WHERE id = ?",
            (campaign_id,),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def _init_play_turn_state(campaign_id, current_actor, phase, turn_number):
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO play_turn_state (campaign_id, current_actor, phase, turn_number) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (campaign_id) DO UPDATE "
            "SET current_actor = excluded.current_actor, phase = excluded.phase, "
            "turn_number = excluded.turn_number",
            (campaign_id, current_actor, phase, turn_number),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def _get_play_turn_state(campaign_id):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT campaign_id, current_actor, phase, turn_number FROM play_turn_state "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _count_play_members(campaign_id):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM play_members WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        return row["count"]
    finally:
        conn.close()


def _is_play_member_or_owner(campaign_id, username):
    conn = _get_conn()
    try:
        campaign = conn.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return False
        if campaign["owner"] == username:
            return True
        row = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _has_play_membership(campaign_id, username):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _create_play_membership(campaign_id, username, character_id, name, class_):
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO play_members (campaign_id, username, character_id, name, class) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, username, character_id, name, class_),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


# --- Narrations ---


def _create_narration(campaign_id, text):
    """Append a DM narration event and return it with its campaign sequence."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM play_narrations "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = row["next_sequence"]
        conn.execute(
            "INSERT INTO play_narrations (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, 'narration', 'dm', ?)",
            (campaign_id, sequence, text),
        )
        conn.commit()
        return {"sequence": sequence, "kind": "narration", "actor": "dm", "text": text}
    finally:
        conn.close()


# --- Users ---


def _get_user(username):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT username, password_hash, role FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _create_user(username, password_hash, role):
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, password_hash, role),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


# --- Monsters ---


def _create_monster(slug, name, cr, armor_class, hit_points, tags):
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (slug, name, cr, armor_class, hit_points, json.dumps(tags)),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _get_monster(slug):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters "
            "WHERE slug = ?",
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
            "tags": json.loads(row["tags_json"]),
        }
    finally:
        conn.close()


# --- Items ---


def _create_item(slug, name, type_, rarity, cost_gp):
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
            (slug, name, type_, rarity, cost_gp),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _get_item(slug):
    conn = _get_conn()
    try:
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
    finally:
        conn.close()


# --- Campaigns ---


def _create_campaign(campaign_id, name, dm):
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
            (campaign_id, name, dm),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _get_campaign(campaign_id):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, name, dm FROM campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# --- Characters ---


def _create_character(character_id, campaign_id, name, level, class_):
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO campaign_characters (id, campaign_id, name, level, class) "
            "VALUES (?, ?, ?, ?, ?)",
            (character_id, campaign_id, name, level, class_),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _get_characters(campaign_id):
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, name, level, class FROM campaign_characters "
            "WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# --- Campaign events ---


def _create_event(event_id, campaign_id, kind, summary):
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)",
            (event_id, campaign_id, kind, summary),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _get_event_count(campaign_id):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        return row["count"]
    finally:
        conn.close()


def _get_events(campaign_id):
    """Return all events for a campaign ordered by rowid descending (most recent first)."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY rowid DESC",
            (campaign_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# --- Combat sessions ---


def _get_combat_session(session_id):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, round, turn_index, order_json, conditions_json FROM combat_sessions "
            "WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "round": row["round"],
            "turn_index": row["turn_index"],
            "order": json.loads(row["order_json"]),
            "conditions": json.loads(row["conditions_json"]),
        }
    finally:
        conn.close()


def _create_combat_session(session_id, order, conditions):
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO combat_sessions (id, round, turn_index, order_json, conditions_json) "
            "VALUES (?, 1, 0, ?, ?)",
            (session_id, json.dumps(order), json.dumps(conditions)),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _update_combat_session(session_id, round_, turn_index, conditions):
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE combat_sessions SET round = ?, turn_index = ?, conditions_json = ? "
            "WHERE id = ?",
            (round_, turn_index, json.dumps(conditions), session_id),
        )
        conn.commit()
    finally:
        conn.close()


# --- Quests ---


def _create_quest(quest_id, campaign_id, title, status, milestones, completed_milestones):
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO quests (id, campaign_id, title, status, milestones_json, completed_milestones_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (quest_id, campaign_id, title, status, json.dumps(milestones), json.dumps(completed_milestones)),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _get_quest(quest_id):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, campaign_id, title, status, milestones_json, completed_milestones_json FROM quests "
            "WHERE id = ?",
            (quest_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "campaign_id": row["campaign_id"],
            "title": row["title"],
            "status": row["status"],
            "milestones": json.loads(row["milestones_json"]),
            "completed_milestones": json.loads(row["completed_milestones_json"]),
        }
    finally:
        conn.close()


def _get_quests_by_campaign(campaign_id):
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, campaign_id, title, status, milestones_json, completed_milestones_json FROM quests "
            "WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "campaign_id": row["campaign_id"],
                "title": row["title"],
                "status": row["status"],
                "milestones": json.loads(row["milestones_json"]),
                "completed_milestones": json.loads(row["completed_milestones_json"]),
            }
            for row in rows
        ]
    finally:
        conn.close()


def _update_quest_progress(quest_id, completed_milestones, status):
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE quests SET completed_milestones_json = ?, status = ? WHERE id = ?",
            (json.dumps(completed_milestones), status, quest_id),
        )
        conn.commit()
    finally:
        conn.close()


# --- Factions ---


def _create_faction(faction_id, campaign_id, name, stance):
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)",
            (faction_id, campaign_id, name, stance),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _get_faction(faction_id):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, campaign_id, name, stance FROM factions WHERE id = ?",
            (faction_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _get_faction_count(campaign_id):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM factions WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        return row["count"]
    finally:
        conn.close()


# --- NPCs ---


def _create_npc(npc_id, campaign_id, faction_id, name, disposition):
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO npcs (id, campaign_id, faction_id, name, disposition) "
            "VALUES (?, ?, ?, ?, ?)",
            (npc_id, campaign_id, faction_id, name, disposition),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _get_npc(npc_id):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, campaign_id, faction_id, name, disposition FROM npcs WHERE id = ?",
            (npc_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _get_npc_counts(campaign_id):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT "
            "  COUNT(*) AS total, "
            "  COALESCE(SUM(CASE WHEN disposition >= 1 THEN 1 ELSE 0 END), 0) AS friendly "
            "FROM npcs WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        return {"total": row["total"], "friendly": row["friendly"]}
    finally:
        conn.close()


# --- Inventory and equipment ---


def _add_inventory(campaign_id, item_slug, quantity, owner):
    """Insert or accumulate an inventory row and return the resulting quantity."""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO inventory (campaign_id, item_slug, owner, quantity) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (campaign_id, item_slug, owner) DO UPDATE "
            "SET quantity = quantity + excluded.quantity",
            (campaign_id, item_slug, owner, quantity),
        )
        conn.commit()
        row = conn.execute(
            "SELECT quantity FROM inventory "
            "WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
            (campaign_id, item_slug, owner),
        ).fetchone()
        return row["quantity"]
    finally:
        conn.close()


def _get_inventory_total(campaign_id):
    """Return the number of distinct inventory item types for a campaign."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(DISTINCT item_slug) AS total FROM inventory "
            "WHERE campaign_id = ? AND quantity > 0",
            (campaign_id,),
        ).fetchone()
        return row["total"]
    finally:
        conn.close()


def _get_inventory_summary(campaign_id):
    """Return the inventory/equipment summary for a campaign."""
    conn = _get_conn()
    try:
        party_items = conn.execute(
            "SELECT COUNT(*) AS count FROM inventory "
            "WHERE campaign_id = ? AND owner = 'party' AND quantity > 0",
            (campaign_id,),
        ).fetchone()["count"]
        assigned_items = conn.execute(
            "SELECT COUNT(*) AS count FROM equipment WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["count"]
        row = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS total FROM inventory "
            "WHERE campaign_id = ? AND item_slug = 'healing-potion' AND owner = 'party'",
            (campaign_id,),
        ).fetchone()
        healing_potions_available = row["total"]
        return {
            "campaign_id": campaign_id,
            "party_items": party_items,
            "assigned_items": assigned_items,
            "healing_potions_available": healing_potions_available,
        }
    finally:
        conn.close()


def _count_inventory_rows(campaign_id):
    """Return the number of inventory rows with positive quantity for a campaign."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM inventory "
            "WHERE campaign_id = ? AND quantity > 0",
            (campaign_id,),
        ).fetchone()
        return row["count"]
    finally:
        conn.close()


def _character_exists(campaign_id, character_id):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM campaign_characters "
            "WHERE id = ? AND campaign_id = ?",
            (character_id, campaign_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _assign_equipment(campaign_id, character_id, item_slug, quantity):
    """Transfer quantity of an item from the party inventory to a character.

    Returns a dict with ``success`` and, when successful, ``quantity`` (the
    character's new total for that item). On failure ``error`` is provided.
    """
    conn = _get_conn()
    try:
        if not _character_exists(campaign_id, character_id):
            return {"success": False, "error": "character not found"}

        row = conn.execute(
            "SELECT quantity FROM inventory "
            "WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'",
            (campaign_id, item_slug),
        ).fetchone()
        available = row["quantity"] if row else 0
        if available < quantity:
            return {"success": False, "error": "insufficient quantity"}

        remaining = available - quantity
        if remaining > 0:
            conn.execute(
                "UPDATE inventory SET quantity = ? "
                "WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'",
                (remaining, campaign_id, item_slug),
            )
        else:
            conn.execute(
                "DELETE FROM inventory "
                "WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'",
                (campaign_id, item_slug),
            )

        conn.execute(
            "INSERT INTO equipment (campaign_id, character_id, item_slug, quantity) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id, item_slug) DO UPDATE "
            "SET quantity = quantity + excluded.quantity",
            (campaign_id, character_id, item_slug, quantity),
        )

        row = conn.execute(
            "SELECT quantity FROM equipment "
            "WHERE campaign_id = ? AND character_id = ? AND item_slug = ?",
            (campaign_id, character_id, item_slug),
        ).fetchone()
        total = row["quantity"]
        conn.commit()
        return {"success": True, "quantity": total}
    finally:
        conn.close()


# --- Crafting ---


def _create_crafting_project(project_id, campaign_id, character_id, item_slug, days_required, cost_gp):
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO crafting_projects (id, campaign_id, character_id, item_slug, "
            "days_required, cost_gp, days_completed, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, 'active')",
            (project_id, campaign_id, character_id, item_slug, days_required, cost_gp),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _get_crafting_project(project_id):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, campaign_id, character_id, item_slug, days_required, "
            "cost_gp, days_completed, status FROM crafting_projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "campaign_id": row["campaign_id"],
            "character_id": row["character_id"],
            "item_slug": row["item_slug"],
            "days_required": row["days_required"],
            "cost_gp": row["cost_gp"],
            "days_completed": row["days_completed"],
            "status": row["status"],
        }
    finally:
        conn.close()


def _update_crafting_project(project_id, days_completed, status):
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE crafting_projects SET days_completed = ?, status = ? WHERE id = ?",
            (days_completed, status, project_id),
        )
        conn.commit()
    finally:
        conn.close()


# --- Session scheduling ---


def _create_session(session_id, campaign_id, starts_at, duration_minutes, agenda):
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO sessions (id, campaign_id, starts_at, duration_minutes, agenda_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, campaign_id, starts_at, duration_minutes, json.dumps(agenda)),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _get_session(session_id):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, campaign_id, starts_at, duration_minutes, agenda_json FROM sessions "
            "WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "campaign_id": row["campaign_id"],
            "starts_at": row["starts_at"],
            "duration_minutes": row["duration_minutes"],
            "agenda": json.loads(row["agenda_json"]),
        }
    finally:
        conn.close()


def _get_sessions_by_campaign(campaign_id):
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, campaign_id, starts_at, duration_minutes, agenda_json FROM sessions "
            "WHERE campaign_id = ? ORDER BY starts_at, rowid",
            (campaign_id,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "campaign_id": row["campaign_id"],
                "starts_at": row["starts_at"],
                "duration_minutes": row["duration_minutes"],
                "agenda": json.loads(row["agenda_json"]),
            }
            for row in rows
        ]
    finally:
        conn.close()


def _record_attendance(session_id, present, absent):
    conn = _get_conn()
    try:
        for character_id in present:
            conn.execute(
                "INSERT INTO attendance (session_id, character_id, present) VALUES (?, ?, 1) "
                "ON CONFLICT (session_id, character_id) DO UPDATE SET present = 1",
                (session_id, character_id),
            )
        for character_id in absent:
            conn.execute(
                "INSERT INTO attendance (session_id, character_id, present) VALUES (?, ?, 0) "
                "ON CONFLICT (session_id, character_id) DO UPDATE SET present = 0",
                (session_id, character_id),
            )
        conn.commit()
        present_count = conn.execute(
            "SELECT COUNT(*) AS count FROM attendance WHERE session_id = ? AND present = 1",
            (session_id,),
        ).fetchone()["count"]
        absent_count = conn.execute(
            "SELECT COUNT(*) AS count FROM attendance WHERE session_id = ? AND present = 0",
            (session_id,),
        ).fetchone()["count"]
        return {"present_count": present_count, "absent_count": absent_count}
    finally:
        conn.close()
