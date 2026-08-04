"""SQLite persistence layer for the D&D DM Tools API.

All database access lives in this module. The public functions return plain
dicts or None so that the route layer stays free of SQL.

The module is organized by domain area: users, combat sessions, compendium,
campaigns, quests, factions/NPCs, inventory/equipment, crafting, sessions,
play campaigns, scenes, locations, and encounters.
"""

import hashlib
import json
import os
import secrets
import sqlite3

import domain

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game.db")
SCHEMA_VERSION = 1

# DDL for the full application schema. Foreign keys are declared but not
# enforced by default; ON DELETE CASCADE is included for future use.
_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    salt BLOB NOT NULL,
    password_hash BLOB NOT NULL,
    role TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS combat_sessions (
    id TEXT PRIMARY KEY,
    round INTEGER NOT NULL,
    turn_index INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS combatants (
    session_id TEXT NOT NULL,
    name TEXT NOT NULL,
    score INTEGER NOT NULL,
    dex INTEGER NOT NULL,
    PRIMARY KEY (session_id, name)
);
CREATE TABLE IF NOT EXISTS conditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    target TEXT NOT NULL,
    condition TEXT NOT NULL,
    remaining_rounds INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS monsters (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    cr TEXT NOT NULL,
    armor_class INTEGER NOT NULL,
    hit_points INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS monster_tags (
    monster_slug TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (monster_slug, tag),
    FOREIGN KEY (monster_slug) REFERENCES monsters(slug) ON DELETE CASCADE
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
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    level INTEGER NOT NULL,
    class TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS events (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS quests (
    campaign_id TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (campaign_id, quest_id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS quest_milestones (
    campaign_id TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    milestone TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (campaign_id, quest_id, milestone),
    FOREIGN KEY (campaign_id, quest_id) REFERENCES quests(campaign_id, quest_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS factions (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    stance TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS npcs (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    faction_id TEXT NOT NULL,
    disposition INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id, faction_id) REFERENCES factions(campaign_id, id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS campaign_inventory (
    campaign_id TEXT NOT NULL,
    item_slug TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    owner TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'inventory',
    PRIMARY KEY (campaign_id, item_slug, owner),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS character_equipment (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    item_slug TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, character_id, item_slug),
    FOREIGN KEY (campaign_id, character_id) REFERENCES campaign_characters(campaign_id, id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS crafting_projects (
    campaign_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    item_slug TEXT NOT NULL,
    days_required INTEGER NOT NULL,
    cost_gp INTEGER NOT NULL,
    days_completed INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    PRIMARY KEY (campaign_id, project_id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id, character_id) REFERENCES campaign_characters(campaign_id, id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS sessions (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    agenda TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner TEXT NOT NULL,
    status TEXT NOT NULL,
    max_players INTEGER NOT NULL,
    current_actor TEXT,
    current_scene_id TEXT,
    current_location_id TEXT,
    turn_number INTEGER NOT NULL DEFAULT 0,
    nudge_count INTEGER NOT NULL DEFAULT 0,
    story TEXT NOT NULL DEFAULT '',
    dm_notes TEXT NOT NULL DEFAULT '',
    phase TEXT NOT NULL DEFAULT 'exploration',
    pre_combat_actor TEXT
);
CREATE TABLE IF NOT EXISTS play_campaign_members (
    campaign_id TEXT NOT NULL,
    player TEXT NOT NULL,
    character_id TEXT NOT NULL,
    name TEXT NOT NULL,
    class TEXT NOT NULL,
    join_sequence INTEGER NOT NULL DEFAULT 0,
    hp_current INTEGER NOT NULL DEFAULT 20,
    hp_max INTEGER NOT NULL DEFAULT 20,
    death_save_successes INTEGER NOT NULL DEFAULT 0,
    death_save_failures INTEGER NOT NULL DEFAULT 0,
    owner TEXT,
    race TEXT,
    background TEXT,
    level INTEGER NOT NULL DEFAULT 1,
    con_score INTEGER,
    abilities TEXT,
    gold INTEGER NOT NULL DEFAULT 10,
    PRIMARY KEY (campaign_id, player),
    UNIQUE (campaign_id, character_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_narrations (
    campaign_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    kind TEXT NOT NULL,
    actor TEXT NOT NULL,
    type TEXT,
    target TEXT,
    text TEXT NOT NULL,
    PRIMARY KEY (campaign_id, sequence),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS scenes (
    campaign_id TEXT NOT NULL,
    scene_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    PRIMARY KEY (campaign_id, scene_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS session_attendance (
    campaign_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    present INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (campaign_id, session_id, character_id),
    FOREIGN KEY (campaign_id, session_id) REFERENCES sessions(campaign_id, id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id, character_id) REFERENCES campaign_characters(campaign_id, id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_locations (
    campaign_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (campaign_id, location_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_location_connections (
    campaign_id TEXT NOT NULL,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    travel_turns INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, from_id, to_id),
    FOREIGN KEY (campaign_id, from_id) REFERENCES play_locations(campaign_id, location_id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id, to_id) REFERENCES play_locations(campaign_id, location_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_encounters (
    campaign_id TEXT NOT NULL,
    encounter_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    round INTEGER NOT NULL DEFAULT 1,
    turn_index INTEGER NOT NULL DEFAULT 0,
    combatant_order TEXT,
    xp_awarded INTEGER NOT NULL DEFAULT 0,
    loot TEXT,
    PRIMARY KEY (campaign_id, encounter_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_encounter_monsters (
    campaign_id TEXT NOT NULL,
    encounter_id TEXT NOT NULL,
    monster_id TEXT NOT NULL,
    name TEXT NOT NULL,
    hp_max INTEGER NOT NULL,
    hp_current INTEGER NOT NULL,
    initiative INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, encounter_id, monster_id),
    FOREIGN KEY (campaign_id, encounter_id) REFERENCES play_encounters(campaign_id, encounter_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_encounter_combatants (
    campaign_id TEXT NOT NULL,
    encounter_id TEXT NOT NULL,
    member TEXT NOT NULL,
    character_id TEXT NOT NULL,
    name TEXT NOT NULL,
    initiative INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, encounter_id, member),
    FOREIGN KEY (campaign_id, encounter_id) REFERENCES play_encounters(campaign_id, encounter_id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id, member) REFERENCES play_campaign_members(campaign_id, player) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_encounter_conditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    encounter_id TEXT NOT NULL,
    target TEXT NOT NULL,
    condition TEXT NOT NULL,
    remaining_rounds INTEGER NOT NULL,
    FOREIGN KEY (campaign_id, encounter_id) REFERENCES play_encounters(campaign_id, encounter_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS character_spells (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    spell_id TEXT NOT NULL,
    name TEXT NOT NULL,
    level INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, character_id, spell_id),
    FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS character_prepared_spells (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    spell_id TEXT NOT NULL,
    PRIMARY KEY (campaign_id, character_id, spell_id),
    FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS character_spell_casts (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    spell_id TEXT NOT NULL,
    target TEXT NOT NULL,
    slot_level INTEGER NOT NULL,
    slots_remaining INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, character_id, sequence),
    FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS character_concentration (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    spell_id TEXT NOT NULL,
    target TEXT NOT NULL,
    remaining_turns INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, character_id),
    FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS character_inventory (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, character_id, item_id),
    FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS character_equipped_items (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    slot TEXT NOT NULL,
    item_id TEXT NOT NULL,
    attuned INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (campaign_id, character_id, slot),
    FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS currency_transfers (
    campaign_id TEXT NOT NULL,
    transfer_id INTEGER NOT NULL,
    from_character_id TEXT NOT NULL,
    to_character_id TEXT NOT NULL,
    gold INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, transfer_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_loot (
    campaign_id TEXT NOT NULL,
    loot_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    recipient_character_id TEXT,
    PRIMARY KEY (campaign_id, loot_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_loot_votes (
    campaign_id TEXT NOT NULL,
    loot_id TEXT NOT NULL,
    voter TEXT NOT NULL,
    recipient_character_id TEXT NOT NULL,
    PRIMARY KEY (campaign_id, loot_id, voter),
    FOREIGN KEY (campaign_id, loot_id) REFERENCES play_loot(campaign_id, loot_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_npcs (
    campaign_id TEXT NOT NULL,
    npc_id TEXT NOT NULL,
    name TEXT NOT NULL,
    agenda TEXT NOT NULL,
    public_status TEXT NOT NULL,
    PRIMARY KEY (campaign_id, npc_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS npc_dialogue (
    campaign_id TEXT NOT NULL,
    npc_id TEXT NOT NULL,
    dialogue_id TEXT NOT NULL,
    speaker TEXT NOT NULL,
    text TEXT NOT NULL,
    visibility TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, npc_id, dialogue_id),
    FOREIGN KEY (campaign_id, npc_id) REFERENCES play_npcs(campaign_id, npc_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_factions (
    campaign_id TEXT NOT NULL,
    faction_id TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (campaign_id, faction_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reputation_history (
    campaign_id TEXT NOT NULL,
    faction_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    delta INTEGER NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY (campaign_id, faction_id, sequence),
    FOREIGN KEY (campaign_id, faction_id) REFERENCES play_factions(campaign_id, faction_id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_relationships (
    campaign_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    score INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, source_id, target_id, kind),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_clues (
    campaign_id TEXT NOT NULL,
    clue_id TEXT NOT NULL,
    text TEXT NOT NULL,
    audience TEXT NOT NULL,
    character_id TEXT,
    sequence INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, clue_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_quests (
    campaign_id TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    title TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'locked',
    sequence INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, quest_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_quest_dependencies (
    campaign_id TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    depends_on TEXT NOT NULL,
    PRIMARY KEY (campaign_id, quest_id, depends_on),
    FOREIGN KEY (campaign_id, quest_id) REFERENCES play_quests(campaign_id, quest_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_quest_rewards (
    campaign_id TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    xp INTEGER NOT NULL,
    items TEXT NOT NULL,
    awarded INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (campaign_id, quest_id),
    FOREIGN KEY (campaign_id, quest_id) REFERENCES play_quests(campaign_id, quest_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_quest_reward_grants (
    campaign_id TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    xp INTEGER NOT NULL,
    items TEXT NOT NULL,
    PRIMARY KEY (campaign_id, quest_id, character_id),
    FOREIGN KEY (campaign_id, quest_id) REFERENCES play_quests(campaign_id, quest_id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS play_world_events (
    campaign_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled',
    resolution_text TEXT,
    resolution_turn_number INTEGER,
    sequence INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, event_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
);
"""

_DROP_TABLES = """
DROP TABLE IF EXISTS play_world_events;
DROP TABLE IF EXISTS play_quest_reward_grants;
DROP TABLE IF EXISTS play_quest_rewards;
DROP TABLE IF EXISTS play_quest_dependencies;
DROP TABLE IF EXISTS play_quests;
DROP TABLE IF EXISTS play_clues;
DROP TABLE IF EXISTS play_relationships;
DROP TABLE IF EXISTS reputation_history;
DROP TABLE IF EXISTS play_factions;
DROP TABLE IF EXISTS npc_dialogue;
DROP TABLE IF EXISTS play_npcs;
DROP TABLE IF EXISTS play_loot_votes;
DROP TABLE IF EXISTS play_loot;
DROP TABLE IF EXISTS currency_transfers;
DROP TABLE IF EXISTS character_concentration;
DROP TABLE IF EXISTS character_equipped_items;
DROP TABLE IF EXISTS character_inventory;
DROP TABLE IF EXISTS character_spell_casts;
DROP TABLE IF EXISTS character_prepared_spells;
DROP TABLE IF EXISTS character_spells;
DROP TABLE IF EXISTS monster_tags;
DROP TABLE IF EXISTS monsters;
DROP TABLE IF EXISTS items;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS session_attendance;
DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS play_campaign_members;
DROP TABLE IF EXISTS play_narrations;
DROP TABLE IF EXISTS scenes;
DROP TABLE IF EXISTS play_location_connections;
DROP TABLE IF EXISTS play_locations;
DROP TABLE IF EXISTS play_encounter_conditions;
DROP TABLE IF EXISTS play_encounter_combatants;
DROP TABLE IF EXISTS play_encounter_monsters;
DROP TABLE IF EXISTS play_encounters;
DROP TABLE IF EXISTS play_campaigns;
DROP TABLE IF EXISTS crafting_projects;
DROP TABLE IF EXISTS campaign_characters;
DROP TABLE IF EXISTS campaigns;
DROP TABLE IF EXISTS conditions;
DROP TABLE IF EXISTS combatants;
DROP TABLE IF EXISTS combat_sessions;
DROP TABLE IF EXISTS quest_milestones;
DROP TABLE IF EXISTS quests;
DROP TABLE IF EXISTS npcs;
DROP TABLE IF EXISTS character_equipment;
DROP TABLE IF EXISTS campaign_inventory;
DROP TABLE IF EXISTS factions;
DROP TABLE IF EXISTS users;
"""

_EXPECTED_TABLES = {
    "users",
    "combat_sessions",
    "combatants",
    "conditions",
    "monsters",
    "monster_tags",
    "items",
    "campaigns",
    "campaign_characters",
    "events",
    "factions",
    "npcs",
    "quests",
    "quest_milestones",
    "campaign_inventory",
    "character_equipment",
    "crafting_projects",
    "sessions",
    "session_attendance",
    "play_campaigns",
    "play_campaign_members",
    "play_narrations",
    "scenes",
    "play_locations",
    "play_location_connections",
    "play_encounters",
    "play_encounter_monsters",
    "play_encounter_combatants",
    "play_encounter_conditions",
    "character_spells",
    "character_prepared_spells",
    "character_spell_casts",
    "character_concentration",
    "character_inventory",
    "character_equipped_items",
    "currency_transfers",
    "play_loot",
    "play_loot_votes",
    "play_npcs",
    "npc_dialogue",
    "play_factions",
    "reputation_history",
    "play_relationships",
    "play_clues",
    "play_quests",
    "play_quest_dependencies",
    "play_quest_rewards",
    "play_quest_reward_grants",
    "play_world_events",
}


def _get_db():
    """Open a SQLite connection with row factories enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _add_column_if_missing(conn, table, column, definition):
    """Add a column to a table if it is not already part of the schema."""
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        conn.commit()


def init_db():
    """Create the schema if it does not already exist."""
    with _get_db() as conn:
        conn.executescript(_CREATE_TABLES)
        # Back-fill columns that were added to the schema after the initial
        # release. Each migration is idempotent so reset_db stays cheap.
        _add_column_if_missing(conn, "campaign_inventory", "source", "TEXT NOT NULL DEFAULT 'inventory'")
        _add_column_if_missing(conn, "play_campaigns", "current_actor", "TEXT")
        _add_column_if_missing(conn, "play_campaigns", "turn_number", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "play_campaign_members", "join_sequence", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "play_campaign_members", "hp_current", "INTEGER NOT NULL DEFAULT 20")
        _add_column_if_missing(conn, "play_campaign_members", "hp_max", "INTEGER NOT NULL DEFAULT 20")
        _add_column_if_missing(conn, "play_narrations", "type", "TEXT")
        _add_column_if_missing(conn, "play_narrations", "target", "TEXT")
        _add_column_if_missing(conn, "play_campaigns", "nudge_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "play_campaigns", "story", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "play_campaigns", "dm_notes", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "play_campaigns", "current_scene_id", "TEXT")
        _add_column_if_missing(conn, "play_campaigns", "current_location_id", "TEXT")
        _add_column_if_missing(conn, "play_encounters", "round", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing(conn, "play_encounters", "turn_index", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "play_encounters", "combatant_order", "TEXT")
        _add_column_if_missing(conn, "play_encounters", "xp_awarded", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "play_encounters", "loot", "TEXT")
        _add_column_if_missing(conn, "play_campaign_members", "death_save_successes", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "play_campaign_members", "death_save_failures", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "play_campaigns", "phase", "TEXT NOT NULL DEFAULT 'exploration'")
        _add_column_if_missing(conn, "play_campaigns", "pre_combat_actor", "TEXT")
        _add_column_if_missing(conn, "play_campaign_members", "owner", "TEXT")
        _add_column_if_missing(conn, "play_campaign_members", "race", "TEXT")
        _add_column_if_missing(conn, "play_campaign_members", "background", "TEXT")
        _add_column_if_missing(conn, "play_campaign_members", "level", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing(conn, "play_campaign_members", "con_score", "INTEGER")
        _add_column_if_missing(conn, "play_campaign_members", "abilities", "TEXT")
        _add_column_if_missing(conn, "play_campaign_members", "gold", "INTEGER NOT NULL DEFAULT 10")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS character_equipped_items (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                slot TEXT NOT NULL,
                item_id TEXT NOT NULL,
                attuned INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (campaign_id, character_id, slot),
                FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
            )
            """
        )


def reset_db():
    """Drop and recreate all tables, clearing all data."""
    with _get_db() as conn:
        conn.executescript(_DROP_TABLES + _CREATE_TABLES)


def is_initialized():
    """Return True when every expected application table exists."""
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ({})".format(
                ",".join("?" * len(_EXPECTED_TABLES))
            ),
            tuple(_EXPECTED_TABLES),
        ).fetchall()
        return {r["name"] for r in rows} == _EXPECTED_TABLES


# --- Password hashing helpers ---


def _hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)


def verify_password(password, salt, stored_hash):
    """Return True when password matches the stored PBKDF2 hash."""
    return _hash_password(password, salt) == stored_hash


# --- Users ---


def create_user(username, password, role):
    """Create a user; return True on success, None if the username exists."""
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone() is not None:
            return None
        salt = secrets.token_bytes(16)
        password_hash = _hash_password(password, salt)
        conn.execute(
            "INSERT INTO users (username, salt, password_hash, role) VALUES (?, ?, ?, ?)",
            (username, salt, password_hash, role),
        )
        conn.commit()
    return True


def get_user(username):
    """Return user credentials or None if the user does not exist."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT salt, password_hash, role FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            return None
        return {
            "salt": row["salt"],
            "password_hash": row["password_hash"],
            "role": row["role"],
        }


# --- Initiative helpers ---


def _sort_combatants(rows):
    """Build a sorted list of combatants from sqlite3 rows."""
    combatants = [{"name": r["name"], "score": r["score"], "dex": r["dex"]} for r in rows]
    return domain.initiative_order(combatants)


def _next_narration_sequence(conn, campaign_id):
    """Return the next sequence number for a play campaign's narration table."""
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM play_narrations WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    return row["next_seq"]


# --- Combat sessions ---


def _session_combatants(conn, session_id):
    """Return all combatants in a session, sorted by initiative."""
    rows = conn.execute(
        "SELECT name, score, dex FROM combatants WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    return _sort_combatants(rows)


def _session_conditions(conn, session_id):
    """Return grouped conditions for a session, ordered by insertion id."""
    rows = conn.execute(
        "SELECT target, condition, remaining_rounds FROM conditions "
        "WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    conditions = {}
    for r in rows:
        conditions.setdefault(r["target"], []).append(
            {"condition": r["condition"], "remaining_rounds": r["remaining_rounds"]}
        )
    return conditions


def create_combat_session(session_id, combatants):
    """Create a combat session with its initial combatants.

    Returns the saved session on success, None if the id already exists.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM combat_sessions WHERE id = ?", (session_id,)).fetchone() is not None:
            return None
        conn.execute(
            "INSERT INTO combat_sessions (id, round, turn_index) VALUES (?, ?, ?)",
            (session_id, 1, 0),
        )
        for c in combatants:
            conn.execute(
                "INSERT INTO combatants (session_id, name, score, dex) VALUES (?, ?, ?, ?)",
                (session_id, c["name"], c["score"], c["dex"]),
            )
        conn.commit()
    return get_combat_session(session_id)


def get_combat_session(session_id):
    """Return a session with its active combatant and order, or None."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT id, round, turn_index FROM combat_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        combatants = _session_combatants(conn, session_id)
        if not combatants:
            return None
        active = combatants[row["turn_index"]]
        return {
            "id": row["id"],
            "round": row["round"],
            "turn_index": row["turn_index"],
            "active": {"name": active["name"], "score": active["score"]},
            "order": [{"name": c["name"], "score": c["score"]} for c in combatants],
        }


def add_condition(session_id, target, condition_text, duration):
    """Add a condition to a combatant.

    Returns the target's updated condition list, None if the session is
    missing, or False if the target is not a combatant in the session.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM combat_sessions WHERE id = ?", (session_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM combatants WHERE session_id = ? AND name = ?",
            (session_id, target),
        ).fetchone() is None:
            return False
        conn.execute(
            "INSERT INTO conditions (session_id, target, condition, remaining_rounds) VALUES (?, ?, ?, ?)",
            (session_id, target, condition_text, duration),
        )
        conn.commit()
        rows = conn.execute(
            "SELECT condition, remaining_rounds FROM conditions WHERE session_id = ? AND target = ? ORDER BY id",
            (session_id, target),
        ).fetchall()
        return [{"condition": r["condition"], "remaining_rounds": r["remaining_rounds"]} for r in rows]


def advance_turn(session_id):
    """Move to the next combat turn and decay conditions for the new actor.

    Returns the updated session state with conditions, None if the session
    is missing, or False if it has no combatants.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT round, turn_index FROM combat_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        combatants = _session_combatants(conn, session_id)
        if not combatants:
            return False
        round_num = row["round"]
        turn_index = row["turn_index"] + 1
        if turn_index >= len(combatants):
            turn_index = 0
            round_num += 1
        active = combatants[turn_index]

        # Decay and remove expired conditions at the start of the active turn.
        conn.execute(
            "UPDATE conditions SET remaining_rounds = remaining_rounds - 1 "
            "WHERE session_id = ? AND target = ?",
            (session_id, active["name"]),
        )
        conn.execute(
            "DELETE FROM conditions WHERE session_id = ? AND target = ? AND remaining_rounds <= 0",
            (session_id, active["name"]),
        )
        conn.execute(
            "UPDATE combat_sessions SET round = ?, turn_index = ? WHERE id = ?",
            (round_num, turn_index, session_id),
        )
        conn.commit()

        # Rebuild the condition snapshot so every combatant has a key.
        conditions = {c["name"]: [] for c in combatants}
        rows = conn.execute(
            "SELECT target, condition, remaining_rounds FROM conditions "
            "WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        for r in rows:
            conditions.setdefault(r["target"], []).append(
                {"condition": r["condition"], "remaining_rounds": r["remaining_rounds"]}
            )

        return {
            "id": session_id,
            "round": round_num,
            "turn_index": turn_index,
            "active": {"name": active["name"], "score": active["score"]},
            "conditions": conditions,
        }


# --- Compendium ---


def create_monster(slug, name, cr, armor_class, hit_points, tags):
    """Create a monster entry; return it on success, None on duplicate slug."""
    seen = set()
    unique_tags = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            unique_tags.append(tag)
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM monsters WHERE slug = ?", (slug,)).fetchone() is not None:
            return None
        conn.execute(
            "INSERT INTO monsters (slug, name, cr, armor_class, hit_points) VALUES (?, ?, ?, ?, ?)",
            (slug, name, cr, armor_class, hit_points),
        )
        for tag in unique_tags:
            conn.execute(
                "INSERT INTO monster_tags (monster_slug, tag) VALUES (?, ?)",
                (slug, tag),
            )
        conn.commit()
    # The create response matches the original contract and omits tags.
    return {"slug": slug, "name": name, "cr": cr, "armor_class": armor_class, "hit_points": hit_points}


def get_monster(slug):
    """Return a monster entry with its tags, or None if missing."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT slug, name, cr, armor_class, hit_points FROM monsters WHERE slug = ?",
            (slug,),
        ).fetchone()
        if row is None:
            return None
        tag_rows = conn.execute(
            "SELECT tag FROM monster_tags WHERE monster_slug = ? ORDER BY rowid",
            (slug,),
        ).fetchall()
        tags = [r["tag"] for r in tag_rows]
        return {
            "slug": row["slug"],
            "name": row["name"],
            "cr": row["cr"],
            "armor_class": row["armor_class"],
            "hit_points": row["hit_points"],
            "tags": tags,
        }


def create_item(slug, name, item_type, rarity, cost_gp):
    """Create an item entry; return it on success, None on duplicate slug."""
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM items WHERE slug = ?", (slug,)).fetchone() is not None:
            return None
        conn.execute(
            "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
            (slug, name, item_type, rarity, cost_gp),
        )
        conn.commit()
    return {"slug": slug, "name": name, "type": item_type, "rarity": rarity, "cost_gp": cost_gp}


def get_item(slug):
    """Return an item entry, or None if missing."""
    with _get_db() as conn:
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


# --- Campaigns ---


def create_campaign(camp_id, name, dm):
    """Create a campaign; return it on success, None on duplicate id."""
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (camp_id,)).fetchone() is not None:
            return None
        conn.execute(
            "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
            (camp_id, name, dm),
        )
        conn.commit()
    return {"id": camp_id, "name": name, "dm": dm}


def get_campaign(camp_id):
    """Return a campaign summary, or None if missing."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT id, name, dm FROM campaigns WHERE id = ?",
            (camp_id,),
        ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "name": row["name"], "dm": row["dm"]}


def get_character_count(camp_id):
    """Return the number of characters in a campaign."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM campaign_characters WHERE campaign_id = ?",
            (camp_id,),
        ).fetchone()
        return row["cnt"]


def get_campaign_characters(camp_id):
    """Return all characters registered to a campaign."""
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid",
            (camp_id,),
        ).fetchall()
        return [{"id": r["id"], "name": r["name"], "level": r["level"], "class": r["class"]} for r in rows]


def create_campaign_character(camp_id, char_id, name, level, class_name):
    """Add a character to a campaign.

    Returns the character on success, None if the campaign is missing,
    or False if the character id already exists in the campaign.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?",
            (camp_id, char_id),
        ).fetchone() is not None:
            return False
        conn.execute(
            "INSERT INTO campaign_characters (campaign_id, id, name, level, class) VALUES (?, ?, ?, ?, ?)",
            (camp_id, char_id, name, level, class_name),
        )
        conn.commit()
    return {"id": char_id, "name": name, "level": level, "class": class_name}


def get_event_count(camp_id):
    """Return the number of events logged for a campaign."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM events WHERE campaign_id = ?",
            (camp_id,),
        ).fetchone()
        return row["cnt"]


def create_event(camp_id, evt_id, kind, summary):
    """Append an event to a campaign.

    Returns the event id and kind on success, None if the campaign is
    missing, or False if the event id already exists in the campaign.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM events WHERE campaign_id = ? AND id = ?",
            (camp_id, evt_id),
        ).fetchone() is not None:
            return False
        conn.execute(
            "INSERT INTO events (campaign_id, id, kind, summary) VALUES (?, ?, ?, ?)",
            (camp_id, evt_id, kind, summary),
        )
        conn.commit()
    return {"id": evt_id, "kind": kind}


# --- Quests ---


def _quest_milestone_counts(conn, camp_id, quest_id):
    """Return (total, done) milestone counts for a quest."""
    total = conn.execute(
        "SELECT COUNT(*) AS cnt FROM quest_milestones WHERE campaign_id = ? AND quest_id = ?",
        (camp_id, quest_id),
    ).fetchone()["cnt"]
    done = conn.execute(
        "SELECT COUNT(*) AS cnt FROM quest_milestones "
        "WHERE campaign_id = ? AND quest_id = ? AND done = 1",
        (camp_id, quest_id),
    ).fetchone()["cnt"]
    return total, done


def _get_quest(camp_id, quest_id):
    """Return a quest with milestone counts, or None if missing."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT quest_id, title, status FROM quests WHERE campaign_id = ? AND quest_id = ?",
            (camp_id, quest_id),
        ).fetchone()
        if row is None:
            return None
        total, done = _quest_milestone_counts(conn, camp_id, quest_id)
    return {
        "id": row["quest_id"],
        "title": row["title"],
        "status": row["status"],
        "milestones_total": total,
        "milestones_done": done,
    }


def create_quest(camp_id, quest_id, title, status, milestones):
    """Create a quest with its milestones.

    Returns the saved quest on success, None if the campaign is missing,
    or False if the quest id already exists in the campaign.
    """
    seen = set()
    unique_milestones = []
    for milestone in milestones:
        if milestone not in seen:
            seen.add(milestone)
            unique_milestones.append(milestone)

    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM quests WHERE campaign_id = ? AND quest_id = ?",
            (camp_id, quest_id),
        ).fetchone() is not None:
            return False
        conn.execute(
            "INSERT INTO quests (campaign_id, quest_id, title, status) VALUES (?, ?, ?, ?)",
            (camp_id, quest_id, title, status),
        )
        for milestone in unique_milestones:
            conn.execute(
                "INSERT INTO quest_milestones (campaign_id, quest_id, milestone, done) VALUES (?, ?, ?, ?)",
                (camp_id, quest_id, milestone, 0),
            )
        conn.commit()
    return _get_quest(camp_id, quest_id)


def update_quest_progress(camp_id, quest_id, completed):
    """Mark the listed milestones as done for a quest.

    Returns the quest progress summary on success, None if the quest is
    missing, or False if the milestone list is invalid.
    """
    if not isinstance(completed, list):
        return False

    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM quests WHERE campaign_id = ? AND quest_id = ?",
            (camp_id, quest_id),
        ).fetchone() is None:
            return None

        if completed:
            placeholders = ",".join("?" * len(completed))
            conn.execute(
                "UPDATE quest_milestones SET done = 1 "
                "WHERE campaign_id = ? AND quest_id = ? AND milestone IN ({})".format(placeholders),
                (camp_id, quest_id) + tuple(completed),
            )
        conn.commit()

    quest = _get_quest(camp_id, quest_id)
    return {
        "id": quest["id"],
        "status": quest["status"],
        "milestones_total": quest["milestones_total"],
        "milestones_done": quest["milestones_done"],
    }


def get_quest_count(camp_id):
    """Return the number of quests in a campaign."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM quests WHERE campaign_id = ?",
            (camp_id,),
        ).fetchone()
        return row["cnt"]


def get_quest_summary(camp_id):
    """Return quest counts grouped by status for a campaign."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT "
            "SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active, "
            "SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed, "
            "SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) AS blocked "
            "FROM quests WHERE campaign_id = ?",
            (camp_id,),
        ).fetchone()
    return {
        "campaign_id": camp_id,
        "active": row["active"] or 0,
        "completed": row["completed"] or 0,
        "blocked": row["blocked"] or 0,
    }


# --- Factions and NPCs ---


def create_faction(camp_id, faction_id, name, stance):
    """Create a faction within a campaign.

    Returns the faction on success, None if the campaign is missing,
    or False if the faction id already exists in the campaign.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM factions WHERE campaign_id = ? AND id = ?",
            (camp_id, faction_id),
        ).fetchone() is not None:
            return False
        conn.execute(
            "INSERT INTO factions (campaign_id, id, name, stance) VALUES (?, ?, ?, ?)",
            (camp_id, faction_id, name, stance),
        )
        conn.commit()
    return {"id": faction_id, "name": name, "stance": stance}


def create_npc(camp_id, npc_id, name, faction_id, disposition):
    """Create an NPC within a campaign.

    Returns the NPC on success, None if the campaign is missing,
    or False if the NPC id already exists in the campaign.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM npcs WHERE campaign_id = ? AND id = ?",
            (camp_id, npc_id),
        ).fetchone() is not None:
            return False
        conn.execute(
            "INSERT INTO npcs (campaign_id, id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)",
            (camp_id, npc_id, name, faction_id, disposition),
        )
        conn.commit()
    return {"id": npc_id, "name": name, "faction_id": faction_id, "disposition": disposition}


def get_npc_count(camp_id):
    """Return the number of NPCs in a campaign."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM npcs WHERE campaign_id = ?",
            (camp_id,),
        ).fetchone()
        return row["cnt"]


def get_relationship_summary(camp_id):
    """Return relationship counts for a campaign."""
    with _get_db() as conn:
        factions = conn.execute(
            "SELECT COUNT(*) AS cnt FROM factions WHERE campaign_id = ?",
            (camp_id,),
        ).fetchone()["cnt"]
        npcs = conn.execute(
            "SELECT COUNT(*) AS cnt FROM npcs WHERE campaign_id = ?",
            (camp_id,),
        ).fetchone()["cnt"]
        friendly_npcs = conn.execute(
            "SELECT COUNT(*) AS cnt FROM npcs WHERE campaign_id = ? AND disposition > 0",
            (camp_id,),
        ).fetchone()["cnt"]
    return {
        "campaign_id": camp_id,
        "factions": factions,
        "npcs": npcs,
        "friendly_npcs": friendly_npcs,
    }


# --- Inventory and equipment ---


def create_inventory_item(camp_id, item_slug, quantity, owner):
    """Add or update an inventory item for a campaign.

    Returns the item on success, None if the campaign is missing.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        conn.execute(
            "INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner, source) "
            "VALUES (?, ?, ?, ?, 'inventory') "
            "ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = excluded.quantity, source = 'inventory'",
            (camp_id, item_slug, quantity, owner),
        )
        conn.commit()
    return {"item_slug": item_slug, "quantity": quantity, "owner": owner}


def assign_equipment(camp_id, character_id, item_slug, quantity):
    """Assign equipment to a character in a campaign.

    Returns the assignment on success, None if the campaign is missing,
    or False if the character is not part of the campaign.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?",
            (camp_id, character_id),
        ).fetchone() is None:
            return False
        conn.execute(
            "INSERT INTO character_equipment (campaign_id, character_id, item_slug, quantity) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, character_id, item_slug) DO UPDATE SET quantity = excluded.quantity",
            (camp_id, character_id, item_slug, quantity),
        )
        conn.commit()
    return {"character_id": character_id, "item_slug": item_slug, "quantity": quantity}


def get_inventory_item_count(camp_id):
    """Return the number of inventory item rows in a campaign."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM campaign_inventory WHERE campaign_id = ? AND source = 'inventory'",
            (camp_id,),
        ).fetchone()
        return row["cnt"]


def get_inventory_summary(camp_id):
    """Return inventory summary counts for a campaign."""
    with _get_db() as conn:
        party_items = conn.execute(
            "SELECT COUNT(*) AS cnt FROM campaign_inventory WHERE campaign_id = ? AND source = 'inventory'",
            (camp_id,),
        ).fetchone()["cnt"]
        assigned_items = conn.execute(
            "SELECT COUNT(*) AS cnt FROM character_equipment WHERE campaign_id = ?",
            (camp_id,),
        ).fetchone()["cnt"]
        party_potions = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS cnt FROM campaign_inventory "
            "WHERE campaign_id = ? AND item_slug = ?",
            (camp_id, "healing-potion"),
        ).fetchone()["cnt"]
        assigned_potions = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS cnt FROM character_equipment "
            "WHERE campaign_id = ? AND item_slug = ?",
            (camp_id, "healing-potion"),
        ).fetchone()["cnt"]
    return {
        "campaign_id": camp_id,
        "party_items": party_items,
        "assigned_items": assigned_items,
        "healing_potions_available": max(0, party_potions - assigned_potions),
    }


# --- Downtime crafting ---


def create_crafting_project(camp_id, project_id, character_id, item_slug, days_required, cost_gp):
    """Create a downtime crafting project for a character in a campaign.

    Returns the project on success, None if the campaign is missing,
    "character_not_found" if the character is not in the campaign,
    or "duplicate" if the project id already exists in the campaign.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?",
            (camp_id, character_id),
        ).fetchone() is None:
            return "character_not_found"
        if conn.execute(
            "SELECT 1 FROM crafting_projects WHERE campaign_id = ? AND project_id = ?",
            (camp_id, project_id),
        ).fetchone() is not None:
            return "duplicate"
        conn.execute(
            "INSERT INTO crafting_projects "
            "(campaign_id, project_id, character_id, item_slug, days_required, cost_gp, days_completed, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (camp_id, project_id, character_id, item_slug, days_required, cost_gp, 0, "active"),
        )
        conn.commit()
    return {
        "id": project_id,
        "character_id": character_id,
        "item_slug": item_slug,
        "days_required": days_required,
        "days_completed": 0,
        "status": "active",
    }


def advance_crafting_project(camp_id, project_id, days):
    """Advance a crafting project by the given number of days.

    When the project reaches its required days, it is marked complete and
    the crafted item is added to the campaign inventory owned by the
    crafting character.

    Returns the project summary on success, None if the project is missing,
    or False if the request is invalid or the project is already complete.
    """
    if days <= 0:
        return False

    with _get_db() as conn:
        row = conn.execute(
            "SELECT character_id, item_slug, days_required, days_completed, status "
            "FROM crafting_projects WHERE campaign_id = ? AND project_id = ?",
            (camp_id, project_id),
        ).fetchone()
        if row is None:
            return None
        if row["status"] != "active":
            return False

        new_completed = min(row["days_completed"] + days, row["days_required"])
        status = "complete" if new_completed >= row["days_required"] else "active"
        conn.execute(
            "UPDATE crafting_projects SET days_completed = ?, status = ? "
            "WHERE campaign_id = ? AND project_id = ?",
            (new_completed, status, camp_id, project_id),
        )

        if status == "complete":
            conn.execute(
                "INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner, source) "
                "VALUES (?, ?, ?, ?, 'crafting') "
                "ON CONFLICT(campaign_id, item_slug, owner) "
                "DO UPDATE SET quantity = quantity + excluded.quantity",
                (camp_id, row["item_slug"], 1, row["character_id"]),
            )
        conn.commit()

    return {"id": project_id, "days_completed": new_completed, "status": status}


# --- Session scheduling ---


def create_session(camp_id, session_id, starts_at, duration_minutes, agenda):
    """Create a scheduled session for a campaign.

    Returns the saved session on success, None if the campaign is missing,
    or False if the session id already exists in the campaign.
    """

    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM sessions WHERE campaign_id = ? AND id = ?",
            (camp_id, session_id),
        ).fetchone() is not None:
            return False
        conn.execute(
            "INSERT INTO sessions (campaign_id, id, starts_at, duration_minutes, agenda) VALUES (?, ?, ?, ?, ?)",
            (camp_id, session_id, starts_at, duration_minutes, json.dumps(agenda)),
        )
        conn.commit()
    return {
        "id": session_id,
        "starts_at": starts_at,
        "duration_minutes": duration_minutes,
        "agenda_count": len(agenda),
    }


def record_attendance(camp_id, session_id, present, absent):
    """Record attendance for a session.

    Returns the attendance summary on success, None if the session is
    missing, or False if any character is invalid.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM sessions WHERE campaign_id = ? AND id = ?",
            (camp_id, session_id),
        ).fetchone() is None:
            return None

        all_char_ids = set(present) | set(absent)
        if all_char_ids:
            placeholders = ",".join("?" * len(all_char_ids))
            rows = conn.execute(
                "SELECT id FROM campaign_characters WHERE campaign_id = ? AND id IN ({})".format(placeholders),
                (camp_id,) + tuple(all_char_ids),
            ).fetchall()
            valid_ids = {r["id"] for r in rows}
            if valid_ids != all_char_ids:
                return False

        conn.execute(
            "DELETE FROM session_attendance WHERE campaign_id = ? AND session_id = ?",
            (camp_id, session_id),
        )
        for char_id in present:
            conn.execute(
                "INSERT INTO session_attendance (campaign_id, session_id, character_id, present) VALUES (?, ?, ?, ?)",
                (camp_id, session_id, char_id, 1),
            )
        for char_id in absent:
            conn.execute(
                "INSERT INTO session_attendance (campaign_id, session_id, character_id, present) VALUES (?, ?, ?, ?)",
                (camp_id, session_id, char_id, 0),
            )
        conn.commit()
    return {
        "session_id": session_id,
        "present_count": len(present),
        "absent_count": len(absent),
    }


def get_session_count(camp_id):
    """Return the number of scheduled sessions in a campaign."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM sessions WHERE campaign_id = ?",
            (camp_id,),
        ).fetchone()
        return row["cnt"]


def get_play_campaign(camp_id):
    """Return a play campaign or None if missing."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT id, name, owner, status, max_players, current_actor, turn_number, nudge_count "
            "FROM play_campaigns WHERE id = ?",
            (camp_id,),
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
        }


def create_play_campaign(camp_id, name, owner, max_players):
    """Create a play campaign; return it on success, None on duplicate id."""
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is not None:
            return None
        conn.execute(
            "INSERT INTO play_campaigns (id, name, owner, status, max_players, current_actor, turn_number, nudge_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (camp_id, name, owner, "lobby", max_players, None, 0, 0),
        )
        conn.commit()
    return {"id": camp_id, "name": name, "owner": owner, "status": "lobby", "max_players": max_players}


def get_play_campaign_members(camp_id):
    """Return all members of a play campaign, ordered by player username."""
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT player, character_id, name, class FROM play_campaign_members "
            "WHERE campaign_id = ? ORDER BY player",
            (camp_id,),
        ).fetchall()
        return [
            {"player": r["player"], "character_id": r["character_id"], "name": r["name"], "class": r["class"]}
            for r in rows
        ]


def is_play_campaign_member(camp_id, username):
    """Return True when the user is a member of the play campaign."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND player = ?",
            (camp_id, username),
        ).fetchone()
        return row is not None


def get_play_campaign_queue(camp_id):
    """Return the deterministic turn queue for a play campaign.

    The queue interleaves joined players and the DM in join order:
    [player1, dm, player2, dm, ...]. Returns an empty list when the
    campaign has no members. Returns None if the campaign is missing.
    """
    campaign = get_play_campaign(camp_id)
    if campaign is None:
        return None
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT player FROM play_campaign_members "
            "WHERE campaign_id = ? ORDER BY join_sequence, player",
            (camp_id,),
        ).fetchall()
    queue = []
    for row in rows:
        queue.append(row["player"])
        queue.append(campaign["owner"])
    return queue


def start_play_campaign(camp_id):
    """Start a play campaign.

    Returns the campaign start state on success, None if the campaign is
    missing, "already_active" if it is not in lobby status, or
    "under_populated" if it has fewer than two members.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT status FROM play_campaigns WHERE id = ?",
            (camp_id,),
        ).fetchone()
        if row is None:
            return None
        if row["status"] != "lobby":
            return "already_active"
        count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM play_campaign_members WHERE campaign_id = ?",
            (camp_id,),
        ).fetchone()["cnt"]
        if count < 2:
            return "under_populated"
        first_player = conn.execute(
            "SELECT player FROM play_campaign_members WHERE campaign_id = ? ORDER BY join_sequence, player LIMIT 1",
            (camp_id,),
        ).fetchone()["player"]
        conn.execute(
            "UPDATE play_campaigns SET status = ?, current_actor = ?, turn_number = ? WHERE id = ?",
            ("active", first_player, 1, camp_id),
        )
        conn.commit()
    return {"id": camp_id, "status": "active", "current_actor": first_player, "turn_number": 1}


def join_play_campaign(camp_id, player, character_id, name, class_name, hp_max=None, hp_current=None):
    """Join a play campaign as a player.

    Returns the membership on success, None if the campaign is missing,
    "full" if the party is already full, "already_member" if the player
    already joined the campaign, or "duplicate_character" if the character
    id is already used in the campaign.
    """
    if hp_max is None:
        hp_max = 20
    if hp_current is None:
        hp_current = 20
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        cap = conn.execute(
            "SELECT max_players FROM play_campaigns WHERE id = ?",
            (camp_id,),
        ).fetchone()["max_players"]
        count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM play_campaign_members WHERE campaign_id = ?",
            (camp_id,),
        ).fetchone()["cnt"]
        if count >= cap:
            return "full"
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND player = ?",
            (camp_id, player),
        ).fetchone() is not None:
            return "already_member"
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, character_id),
        ).fetchone() is not None:
            return "duplicate_character"
        next_seq = conn.execute(
            "SELECT COALESCE(MAX(join_sequence), 0) + 1 FROM play_campaign_members WHERE campaign_id = ?",
            (camp_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO play_campaign_members (campaign_id, player, character_id, name, class, join_sequence, hp_current, hp_max, owner) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (camp_id, player, character_id, name, class_name, next_seq, hp_current, hp_max, player),
        )
        conn.commit()
    return {"player": player, "character_id": character_id, "name": name, "class": class_name}


def _character_status(hp_current, successes, failures):
    """Return the playable character status derived from HP and death saves."""
    if hp_current > 0:
        return "conscious"
    if successes >= 3:
        return "stable"
    if failures >= 3:
        return "dead"
    return "unconscious"


def get_play_campaign_character(camp_id, character_id):
    """Return a play campaign member by character_id, or None if missing."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT player, character_id, name, class, level, hp_current, hp_max, "
            "death_save_successes, death_save_failures "
            "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, character_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "player": row["player"],
            "character_id": row["character_id"],
            "name": row["name"],
            "class": row["class"],
            "level": row["level"],
            "hp_current": row["hp_current"],
            "hp_max": row["hp_max"],
            "status": _character_status(row["hp_current"], row["death_save_successes"], row["death_save_failures"]),
            "successes": row["death_save_successes"],
            "failures": row["death_save_failures"],
        }


def get_character_status(camp_id, character_id):
    """Return the public status of a play campaign character, or None if missing."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT hp_current, hp_max, death_save_successes, death_save_failures "
            "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, character_id),
        ).fetchone()
        if row is None:
            return None
    return {
        "character_id": character_id,
        "hp_current": row["hp_current"],
        "hp_max": row["hp_max"],
        "status": _character_status(row["hp_current"], row["death_save_successes"], row["death_save_failures"]),
        "successes": row["death_save_successes"],
        "failures": row["death_save_failures"],
    }


def damage_character(camp_id, character_id, amount):
    """Apply damage to a play campaign character.

    HP floors at 0. When a character's HP reaches 0, its status becomes
    unconscious and its death save counters are reset.

    Returns the updated character summary on success, or None if the
    character is missing.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT hp_current, hp_max, death_save_successes, death_save_failures "
            "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, character_id),
        ).fetchone()
        if row is None:
            return None
        hp_after = max(0, row["hp_current"] - amount)
        if hp_after == 0:
            successes = 0
            failures = 0
        else:
            successes = row["death_save_successes"]
            failures = row["death_save_failures"]
        status = _character_status(hp_after, successes, failures)
        conn.execute(
            "UPDATE play_campaign_members SET hp_current = ?, death_save_successes = ?, "
            "death_save_failures = ? WHERE campaign_id = ? AND character_id = ?",
            (hp_after, successes, failures, camp_id, character_id),
        )
        conn.commit()
    return {
        "character_id": character_id,
        "hp_current": hp_after,
        "hp_max": row["hp_max"],
        "status": status,
        "successes": successes,
        "failures": failures,
    }


def record_death_save(camp_id, character_id, outcome):
    """Record a death saving throw for a character at 0 HP.

    Returns the updated counters and status on success, None if the
    character is missing, "conscious" if the character is above 0 HP, or
    "terminal" if the character is already stable or dead.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT hp_current, hp_max, death_save_successes, death_save_failures "
            "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, character_id),
        ).fetchone()
        if row is None:
            return None
        hp_current = row["hp_current"]
        successes = row["death_save_successes"]
        failures = row["death_save_failures"]
        if hp_current > 0:
            return "conscious"
        if successes >= 3 or failures >= 3:
            return "terminal"
        if outcome == "success":
            successes += 1
        else:
            failures += 1
        status = _character_status(hp_current, successes, failures)
        conn.execute(
            "UPDATE play_campaign_members SET death_save_successes = ?, death_save_failures = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (successes, failures, camp_id, character_id),
        )
        conn.commit()
    return {
        "character_id": character_id,
        "hp_current": hp_current,
        "hp_max": row["hp_max"],
        "status": status,
        "successes": successes,
        "failures": failures,
    }


def get_character_owner(camp_id, char_id):
    """Return the owner of a play campaign character, or None if missing.

    The owner is the explicit owner column when set; otherwise the
    character is considered unowned and the owner value is None.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone()
        if row is None:
            return None
        return {"character_id": char_id, "owner": row["owner"]}


def get_character_abilities(camp_id, char_id):
    """Return a character's level and ability scores, or None if missing.

    Ability scores are stored as JSON. The result dict has 'level' and
    'abilities' keys.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT level, abilities FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone()
        if row is None:
            return None
        abilities = {}
        if row["abilities"]:
            try:
                abilities = json.loads(row["abilities"])
            except json.JSONDecodeError:
                pass
        return {"level": row["level"], "abilities": abilities}


def claim_character(camp_id, char_id, player):
    """Claim an unowned play campaign character for a player.

    Returns the player on success, None if the character is missing, or
    "already_owned" if the character is owned by another player. Claiming
    a character already owned by the requesting player is idempotent.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone()
        if row is None:
            return None
        owner = row["owner"]
        if owner is not None and owner != player:
            return "already_owned"
        conn.execute(
            "UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?",
            (player, camp_id, char_id),
        )
        conn.commit()
    return player


def transfer_character(camp_id, char_id, current_owner, new_owner):
    """Transfer ownership of a play campaign character to another member.

    Returns the new owner on success, None if the character is missing,
    "not_owner" if the requester is not the current owner, or
    "invalid_new_owner" if the proposed owner is not a campaign member.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND player = ?",
            (camp_id, new_owner),
        ).fetchone() is None:
            return "invalid_new_owner"
        row = conn.execute(
            "SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone()
        if row is None:
            return None
        owner = row["owner"]
        if owner is None or owner != current_owner:
            return "not_owner"
        conn.execute(
            "UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?",
            (new_owner, camp_id, char_id),
        )
        conn.commit()
    return new_owner


def get_character_currency(camp_id, char_id):
    """Return a character's gold balance, or None if the character is missing."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone()
        if row is None:
            return None
        return {"character_id": char_id, "gold": row["gold"]}


def transfer_gold(camp_id, from_char_id, to_char_id, gold):
    """Atomically transfer gold between two campaign characters.

    Returns a transfer summary on success, None if either character is
    missing, or "insufficient" if the source character does not have enough
    gold. The transfer id is deterministic and campaign-local, starting at 1.
    """
    with _get_db() as conn:
        from_row = conn.execute(
            "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, from_char_id),
        ).fetchone()
        to_row = conn.execute(
            "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, to_char_id),
        ).fetchone()
        if from_row is None or to_row is None:
            return None

        from_gold = from_row["gold"]
        to_gold = to_row["gold"]
        if from_gold < gold:
            return "insufficient"

        next_id = conn.execute(
            "SELECT COALESCE(MAX(transfer_id), 0) + 1 FROM currency_transfers WHERE campaign_id = ?",
            (camp_id,),
        ).fetchone()[0]

        conn.execute(
            "UPDATE play_campaign_members SET gold = gold - ? WHERE campaign_id = ? AND character_id = ?",
            (gold, camp_id, from_char_id),
        )
        conn.execute(
            "UPDATE play_campaign_members SET gold = gold + ? WHERE campaign_id = ? AND character_id = ?",
            (gold, camp_id, to_char_id),
        )
        conn.execute(
            "INSERT INTO currency_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold) "
            "VALUES (?, ?, ?, ?, ?)",
            (camp_id, next_id, from_char_id, to_char_id, gold),
        )
        conn.commit()

    return {
        "from_character_id": from_char_id,
        "to_character_id": to_char_id,
        "gold": gold,
        "from_gold": from_gold - gold,
        "to_gold": to_gold + gold,
        "transfer_id": next_id,
    }


def build_character(camp_id, char_id, race, class_name, background, level, hp_max, con_score=None, abilities=None):
    """Persist a character creation build and return its public summary.

    Returns None if the character does not exist. The character's current
    HP is set to the new maximum so the build leaves the character ready
    to play. The Constitution score is stored so later level-ups can apply
    the class hit die deterministically. The full ability score map is
    stored so skill checks can resolve modifiers.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone() is None:
            return None
        conn.execute(
            "UPDATE play_campaign_members SET race = ?, class = ?, background = ?, level = ?, "
            "hp_max = ?, hp_current = ?, con_score = ?, abilities = ? WHERE campaign_id = ? AND character_id = ?",
            (race, class_name, background, level, hp_max, hp_max, con_score, json.dumps(abilities) if abilities else None, camp_id, char_id),
        )
        conn.commit()
    return {
        "character_id": char_id,
        "race": race,
        "class": class_name,
        "background": background,
        "level": level,
        "hp_max": hp_max,
    }


def level_up_character(camp_id, char_id, new_level):
    """Advance a play campaign character by exactly one level.

    Returns the updated character summary on success, None if the
    character is missing, or "invalid_level" if the requested level is not
    exactly one higher than the current level. The HP increase is the
    class hit die average (rounded up) plus the Constitution modifier,
    with a minimum gain of 1 hit point per level.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT level, class, hp_max, con_score FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone()
        if row is None:
            return None
        current_level = row["level"]
        if new_level != current_level + 1:
            return "invalid_level"

        class_name = row["class"]
        hit_die_max = domain.CLASS_HIT_DIE_MAX.get(class_name)
        if hit_die_max is None:
            return None

        con_score = row["con_score"] if row["con_score"] is not None else 10
        con_modifier = domain.ability_modifier(con_score)
        hit_die_avg = hit_die_max // 2 + 1
        hp_gain = max(1, hit_die_avg + con_modifier)
        new_hp_max = row["hp_max"] + hp_gain

        conn.execute(
            "UPDATE play_campaign_members SET level = ?, hp_max = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (new_level, new_hp_max, camp_id, char_id),
        )
        conn.commit()

    return {
        "character_id": char_id,
        "level": new_level,
        "hp_max": new_hp_max,
        "hit_dice": f"1d{hit_die_max}",
        "proficiency_bonus": domain.proficiency_bonus(new_level),
    }


# --- Character spellbooks ---


def add_character_spell(camp_id, char_id, spell_id, name, level):
    """Add a spell to a character's spellbook.

    Returns the spell on success, None if the character does not exist,
    or "duplicate" if the character already knows the spell.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM character_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
            (camp_id, char_id, spell_id),
        ).fetchone() is not None:
            return "duplicate"
        conn.execute(
            "INSERT INTO character_spells (campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)",
            (camp_id, char_id, spell_id, name, level),
        )
        conn.commit()
    return {"spell_id": spell_id, "name": name, "level": level}


def get_character_spells(camp_id, char_id):
    """Return all spells known by a character, ordered by level then spell_id."""
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT spell_id, name, level FROM character_spells "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY level, spell_id",
            (camp_id, char_id),
        ).fetchall()
    return [{"spell_id": r["spell_id"], "name": r["name"], "level": r["level"]} for r in rows]


def get_prepared_spells(camp_id, char_id):
    """Return the prepared spell ids for a character in insertion order.

    Returns None if the character does not exist.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone() is None:
            return None
        rows = conn.execute(
            "SELECT spell_id FROM character_prepared_spells "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY rowid",
            (camp_id, char_id),
        ).fetchall()
    return [r["spell_id"] for r in rows]


def set_prepared_spells(camp_id, char_id, spell_ids):
    """Replace a character's prepared spell list.

    Returns the saved list on success. The caller is responsible for ensuring
    the character exists, the class is a prepared spellcaster, and every spell
    is known by the character.
    """
    with _get_db() as conn:
        conn.execute(
            "DELETE FROM character_prepared_spells WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        )
        for spell_id in spell_ids:
            conn.execute(
                "INSERT INTO character_prepared_spells (campaign_id, character_id, spell_id) VALUES (?, ?, ?)",
                (camp_id, char_id, spell_id),
            )
        conn.commit()
        rows = conn.execute(
            "SELECT spell_id FROM character_prepared_spells "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY rowid",
            (camp_id, char_id),
        ).fetchall()
    return [r["spell_id"] for r in rows]


def get_character_spell(camp_id, char_id, spell_id):
    """Return a single spell known by a character, or None if missing."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT spell_id, name, level FROM character_spells "
            "WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
            (camp_id, char_id, spell_id),
        ).fetchone()
        if row is None:
            return None
        return {"spell_id": row["spell_id"], "name": row["name"], "level": row["level"]}


def get_remaining_spell_slots(camp_id, char_id):
    """Return remaining spell slots for a character by slot level.

    Returns None if the character is missing or is not a supported
    spellcaster.  The result is a dict mapping slot level (int) to the
    number of slots still available after recorded casts.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT class, level FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone()
        if row is None:
            return None
        slots_info = domain.compute_spell_slots(row["class"], row["level"])
        if slots_info is None:
            return None
        total_slots = {int(k): v for k, v in slots_info["slots"].items()}
        cast_rows = conn.execute(
            "SELECT slot_level, COUNT(*) AS cnt FROM character_spell_casts "
            "WHERE campaign_id = ? AND character_id = ? GROUP BY slot_level",
            (camp_id, char_id),
        ).fetchall()
    used = {r["slot_level"]: r["cnt"] for r in cast_rows}
    return {level: max(0, total - used.get(level, 0)) for level, total in total_slots.items()}


def record_spell_cast(camp_id, char_id, spell_id, target, slot_level, slots_remaining):
    """Record a spell cast for a character.

    Returns the cast record on success, or None if the character is missing.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone() is None:
            return None
        sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM character_spell_casts "
            "WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO character_spell_casts (campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (camp_id, char_id, sequence, spell_id, target, slot_level, slots_remaining),
        )
        conn.commit()
    return {
        "character_id": char_id,
        "spell_id": spell_id,
        "target": target,
        "slot_level": slot_level,
        "slots_remaining": slots_remaining,
        "sequence": sequence,
    }


def get_spell_casts(camp_id, char_id):
    """Return all spell casts for a character in sequence order.

    Returns None if the character is missing, or a list of cast records.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone() is None:
            return None
        rows = conn.execute(
            "SELECT sequence, spell_id, target, slot_level, slots_remaining FROM character_spell_casts "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY sequence",
            (camp_id, char_id),
        ).fetchall()
    return [
        {
            "character_id": char_id,
            "spell_id": r["spell_id"],
            "target": r["target"],
            "slot_level": r["slot_level"],
            "slots_remaining": r["slots_remaining"],
            "sequence": r["sequence"],
        }
        for r in rows
    ]


# --- Character concentration ---


def set_character_concentration(camp_id, char_id, spell_id, target, remaining_turns):
    """Set or replace a character's active concentration.

    Returns the concentration dict on success, or None if the character
    does not exist.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone() is None:
            return None
        conn.execute(
            "INSERT INTO character_concentration (campaign_id, character_id, spell_id, target, remaining_turns) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, character_id) DO UPDATE SET "
            "spell_id = excluded.spell_id, target = excluded.target, remaining_turns = excluded.remaining_turns",
            (camp_id, char_id, spell_id, target, remaining_turns),
        )
        conn.commit()
    return {"spell_id": spell_id, "target": target, "remaining_turns": remaining_turns}


def get_character_concentration(camp_id, char_id):
    """Return a character's active concentration value, or None when inactive.

    Returns None if the character does not exist.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone() is None:
            return None
        row = conn.execute(
            "SELECT spell_id, target, remaining_turns FROM character_concentration "
            "WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone()
    if row is None:
        return None
    return {"spell_id": row["spell_id"], "target": row["target"], "remaining_turns": row["remaining_turns"]}


def advance_character_concentration(camp_id, char_id):
    """Decrement a character's active concentration by one turn.

    Clears concentration when the count reaches zero. Returns the new
    concentration dict, None if there is no active concentration, or
    None if the character does not exist.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone() is None:
            return None
        row = conn.execute(
            "SELECT spell_id, target, remaining_turns FROM character_concentration "
            "WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone()
        if row is None:
            return None
        remaining = row["remaining_turns"] - 1
        if remaining <= 0:
            conn.execute(
                "DELETE FROM character_concentration WHERE campaign_id = ? AND character_id = ?",
                (camp_id, char_id),
            )
            concentration = None
        else:
            conn.execute(
                "UPDATE character_concentration SET remaining_turns = ? "
                "WHERE campaign_id = ? AND character_id = ?",
                (remaining, camp_id, char_id),
            )
            concentration = {"spell_id": row["spell_id"], "target": row["target"], "remaining_turns": remaining}
        conn.commit()
    return concentration


def clear_character_concentration(camp_id, char_id):
    """Clear a character's concentration.

    Returns True on success, or None if the character does not exist.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone() is None:
            return None
        conn.execute(
            "DELETE FROM character_concentration WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        )
        conn.commit()
    return True


# --- Character inventory stacks ---

VALID_INVENTORY_ITEMS = frozenset({"healing-potion", "torch", "leather-armor", "ring-of-protection", "amulet-of-health"})
CONSUMABLE_ITEMS = frozenset({"healing-potion"})
HEALING_POTION_HP_RESTORE = 5


def add_character_inventory_item(camp_id, char_id, item_id, quantity):
    """Add quantity to a character's inventory item stack.

    Returns the item stack summary on success, "invalid_item" if the item is
    not in the catalog, "invalid_quantity" if the quantity is not a positive
    integer, or None if the character does not exist.
    """
    if item_id not in VALID_INVENTORY_ITEMS:
        return "invalid_item"
    if not isinstance(quantity, int) or quantity <= 0:
        return "invalid_quantity"
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone() is None:
            return None
        row = conn.execute(
            "SELECT quantity FROM character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (camp_id, char_id, item_id),
        ).fetchone()
        total = (row["quantity"] if row else 0) + quantity
        conn.execute(
            "INSERT INTO character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = excluded.quantity",
            (camp_id, char_id, item_id, total),
        )
        conn.commit()
    return {"character_id": char_id, "item_id": item_id, "quantity": quantity, "total_quantity": total}


def get_character_inventory_items(camp_id, char_id):
    """Return all inventory items held by a character, ordered by item_id.

    Returns None if the character does not exist.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone() is None:
            return None
        rows = conn.execute(
            "SELECT item_id, quantity FROM character_inventory "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY item_id",
            (camp_id, char_id),
        ).fetchall()
    return {"character_id": char_id, "items": [{"item_id": r["item_id"], "quantity": r["quantity"]} for r in rows]}


def remove_character_inventory_item(camp_id, char_id, item_id, quantity):
    """Remove quantity from a character's inventory item stack.

    Returns the item stack summary on success, "invalid_item" if the item is
    not in the catalog, "invalid_quantity" if the quantity is not a positive
    integer, "insufficient" if the quantity exceeds the held stack, or None if
    the character does not exist.
    """
    if item_id not in VALID_INVENTORY_ITEMS:
        return "invalid_item"
    if not isinstance(quantity, int) or quantity <= 0:
        return "invalid_quantity"
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone() is None:
            return None
        row = conn.execute(
            "SELECT quantity FROM character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (camp_id, char_id, item_id),
        ).fetchone()
        held = row["quantity"] if row else 0
        if quantity > held:
            return "insufficient"
        total = held - quantity
        if total == 0:
            conn.execute(
                "DELETE FROM character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (camp_id, char_id, item_id),
            )
        else:
            conn.execute(
                "UPDATE character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (total, camp_id, char_id, item_id),
            )
        conn.commit()
    return {"character_id": char_id, "item_id": item_id, "quantity": quantity, "total_quantity": total}


def consume_character_inventory_item(camp_id, char_id, item_id):
    """Consume one unit of a declared consumable inventory item.

    Returns the consumption summary on success, "invalid_item" if the item is
    not in the catalog, "not_consumable" if the item is not a declared
    consumable, "empty" if the character has no held stack or the stack has
    quantity zero, or None if the character does not exist.
    """
    if item_id not in VALID_INVENTORY_ITEMS:
        return "invalid_item"
    if item_id not in CONSUMABLE_ITEMS:
        return "not_consumable"
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone() is None:
            return None
        row = conn.execute(
            "SELECT quantity FROM character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (camp_id, char_id, item_id),
        ).fetchone()
        held = row["quantity"] if row else 0
        if held <= 0:
            return "empty"
        total = held - 1
        if total == 0:
            conn.execute(
                "DELETE FROM character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (camp_id, char_id, item_id),
            )
        else:
            conn.execute(
                "UPDATE character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (total, camp_id, char_id, item_id),
            )
        if item_id == "healing-potion":
            hp_row = conn.execute(
                "SELECT hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (camp_id, char_id),
            ).fetchone()
            hp_current = min(hp_row["hp_max"], hp_row["hp_current"] + HEALING_POTION_HP_RESTORE)
            conn.execute(
                "UPDATE play_campaign_members SET hp_current = ? WHERE campaign_id = ? AND character_id = ?",
                (hp_current, camp_id, char_id),
            )
        conn.commit()
    return {
        "character_id": char_id,
        "item_id": item_id,
        "quantity_consumed": 1,
        "total_quantity": total,
        "effect": {"type": "healing", "hp_restored": HEALING_POTION_HP_RESTORE},
    }


def has_character_inventory_item(camp_id, char_id, item_id):
    """Return True when the character holds at least one of the item."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT quantity FROM character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (camp_id, char_id, item_id),
        ).fetchone()
        return row is not None and row["quantity"] > 0


# --- Character equipment slots and attunement ---

ATTUNABLE_ITEMS = frozenset({"ring-of-protection", "amulet-of-health"})


def get_character_equipped_item(camp_id, char_id, slot):
    """Return the equipped item for a slot, or None if the character is missing.

    When the slot is empty, returns {"character_id": ..., "slot": ...,
    "item_id": "", "attuned": False}.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone() is None:
            return None
        row = conn.execute(
            "SELECT item_id, attuned FROM character_equipped_items "
            "WHERE campaign_id = ? AND character_id = ? AND slot = ?",
            (camp_id, char_id, slot),
        ).fetchone()
        if row is None:
            return {"character_id": char_id, "slot": slot, "item_id": "", "attuned": False}
        return {"character_id": char_id, "slot": slot, "item_id": row["item_id"], "attuned": bool(row["attuned"])}


def set_character_equipped_item(camp_id, char_id, slot, item_id):
    """Equip an item in a character's slot.

    Returns the equipped item dict on success, or None if the character
    does not exist.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone() is None:
            return None
        conn.execute(
            "INSERT INTO character_equipped_items (campaign_id, character_id, slot, item_id, attuned) "
            "VALUES (?, ?, ?, ?, 0) "
            "ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET item_id = excluded.item_id, attuned = 0",
            (camp_id, char_id, slot, item_id),
        )
        conn.commit()
    return {"character_id": char_id, "slot": slot, "item_id": item_id, "attuned": False}


def attune_character_equipped_item(camp_id, char_id, slot):
    """Attune to the item equipped in a slot.

    Returns the attuned item dict on success, "not_attunable" if the slot
    is empty or does not hold an attunable item, "already_attuned" if the
    character already has an attuned item (including in the requested slot),
    or None if the character does not exist.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchone() is None:
            return None
        row = conn.execute(
            "SELECT item_id, attuned FROM character_equipped_items "
            "WHERE campaign_id = ? AND character_id = ? AND slot = ?",
            (camp_id, char_id, slot),
        ).fetchone()
        if row is None or row["item_id"] not in ATTUNABLE_ITEMS:
            return "not_attunable"
        item_id = row["item_id"]
        if row["attuned"]:
            return "already_attuned"
        attuned_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM character_equipped_items "
            "WHERE campaign_id = ? AND character_id = ? AND attuned = 1",
            (camp_id, char_id),
        ).fetchone()["cnt"]
        if attuned_count > 0:
            return "already_attuned"
        conn.execute(
            "UPDATE character_equipped_items SET attuned = 1 "
            "WHERE campaign_id = ? AND character_id = ? AND slot = ?",
            (camp_id, char_id, slot),
        )
        conn.commit()
    return {
        "character_id": char_id,
        "slot": slot,
        "item_id": item_id,
        "attuned": True,
        "attunement_count": 1,
        "max_attunements": 1,
    }


def create_narration(campaign_id, text):
    """Append a narration event to a play campaign.

    Returns the event dict on success, or None if the campaign is missing.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)).fetchone() is None:
            return None
        sequence = _next_narration_sequence(conn, campaign_id)
        conn.execute(
            "INSERT INTO play_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, "narration", "dm", text),
        )
        conn.commit()
    return {"sequence": sequence, "kind": "narration", "actor": "dm", "text": text}


def get_play_campaign_member(camp_id, player):
    """Return a player's own character in a play campaign, or None.

    The result has the character_id and name (no class or player) so that
    a player reads only their own character context.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT character_id, name FROM play_campaign_members "
            "WHERE campaign_id = ? AND player = ?",
            (camp_id, player),
        ).fetchone()
        if row is None:
            return None
        return {"character_id": row["character_id"], "name": row["name"]}


def get_play_campaign_events(camp_id):
    """Return all play events for a campaign, ordered by sequence.

    Events include the full DM-facing fields; callers are responsible for
    filtering out private data when exposing the result to players.
    """
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT sequence, kind, actor, type, target, text FROM play_narrations "
            "WHERE campaign_id = ? ORDER BY sequence",
            (camp_id,),
        ).fetchall()
    events = []
    for r in rows:
        event = {"sequence": r["sequence"], "kind": r["kind"], "actor": r["actor"], "text": r["text"]}
        if r["type"] is not None:
            event["type"] = r["type"]
        if r["target"] is not None:
            event["target"] = r["target"]
        events.append(event)
    return events


def create_action(campaign_id, actor, action_type, text):
    """Append a player action event to a play campaign and pass the turn to the DM.

    Returns the action event on success, or None if the campaign is missing.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT owner, turn_number FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        next_seq = _next_narration_sequence(conn, campaign_id)
        conn.execute(
            "INSERT INTO play_narrations (campaign_id, sequence, kind, actor, type, text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, next_seq, "action", actor, action_type, text),
        )
        conn.execute(
            "UPDATE play_campaigns SET current_actor = ? WHERE id = ?",
            (row["owner"], campaign_id),
        )
        conn.commit()
    return {
        "sequence": next_seq,
        "kind": "action",
        "actor": actor,
        "type": action_type,
        "text": text,
        "next_actor": "dm",
    }


def create_resolution(campaign_id, text):
    """Append a GM resolution event to a play campaign and advance the turn.

    Returns the resolution event with next_actor and turn_number on success,
    or None if the campaign is missing or has no turn queue.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT owner, turn_number, current_actor FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        queue = get_play_campaign_queue(campaign_id)
        if not queue:
            return None
        next_seq = _next_narration_sequence(conn, campaign_id)
        players = [actor for actor in queue if actor != row["owner"]]
        # The player whose turn just ended is the most recent exploration
        # action or travel turn (rest and combat narrations do not advance the
        # exploration queue). Advance the queue to the next player after them.
        # The turn counter is advanced at resolution time because a resolution
        # starts the next player's turn, while intermediate player actions (and
        # travel turns) do not bump the counter.
        last_player_row = conn.execute(
            "SELECT actor FROM play_narrations WHERE campaign_id = ? AND actor != ? "
            "AND kind IN ('action', 'travel') ORDER BY sequence DESC LIMIT 1",
            (campaign_id, row["owner"]),
        ).fetchone()
        if last_player_row is None:
            next_actor = players[(row["turn_number"] - 1) % len(players)]
        else:
            last_player = last_player_row["actor"]
            try:
                idx = players.index(last_player)
            except ValueError:
                idx = (row["turn_number"] - 1) % len(players)
            next_actor = players[(idx + 1) % len(players)]
        new_turn_number = row["turn_number"] + 1
        conn.execute(
            "INSERT INTO play_narrations (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, next_seq, "resolution", row["owner"], text),
        )
        conn.execute(
            "UPDATE play_campaigns SET current_actor = ?, turn_number = ? WHERE id = ?",
            (next_actor, new_turn_number, campaign_id),
        )
        conn.commit()
    return {
        "sequence": next_seq,
        "kind": "resolution",
        "actor": row["owner"],
        "text": text,
        "next_actor": next_actor,
        "turn_number": new_turn_number,
    }



def increment_nudge_count(camp_id, message):
    """Increment the nudge counter for a play campaign and log the nudge event.

    Returns the new count on success, or None if the campaign is missing.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT nudge_count FROM play_campaigns WHERE id = ?",
            (camp_id,),
        ).fetchone()
        if row is None:
            return None
        new_count = row["nudge_count"] + 1
        conn.execute(
            "UPDATE play_campaigns SET nudge_count = ? WHERE id = ?",
            (new_count, camp_id),
        )
        sequence = _next_narration_sequence(conn, camp_id)
        conn.execute(
            "INSERT INTO play_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
            (camp_id, sequence, "nudge", "dm", message),
        )
        conn.commit()
    return new_count


def get_play_campaign_document(camp_id):
    """Return the durable campaign document, or None if the campaign is missing."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT story, dm_notes FROM play_campaigns WHERE id = ?",
            (camp_id,),
        ).fetchone()
        if row is None:
            return None
        return {"story": row["story"], "dm_notes": row["dm_notes"]}


def update_play_campaign_document(camp_id, story, dm_notes):
    """Update the durable campaign document.

    Returns the document on success, or None if the campaign is missing.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        conn.execute(
            "UPDATE play_campaigns SET story = ?, dm_notes = ? WHERE id = ?",
            (story, dm_notes, camp_id),
        )
        conn.commit()
    return {"story": story, "dm_notes": dm_notes}


def get_next_session(camp_id):
    """Return the next scheduled session for a campaign, or None if missing.

    The session with the earliest starts_at is returned, including those in
    the past, to keep the API deterministic for tests.
    """

    with _get_db() as conn:
        row = conn.execute(
            "SELECT id, starts_at, agenda FROM sessions WHERE campaign_id = ? ORDER BY starts_at ASC LIMIT 1",
            (camp_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            agenda = json.loads(row["agenda"])
        except Exception:
            agenda = []
    return {
        "id": row["id"],
        "starts_at": row["starts_at"],
        "agenda_count": len(agenda),
    }


# --- Scenes ---


def create_scene(camp_id, scene_id, name):
    """Create a scene in a play campaign.

    Returns the scene on success, None if the campaign is missing,
    or False if the scene id already exists in the campaign.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM scenes WHERE campaign_id = ? AND scene_id = ?",
            (camp_id, scene_id),
        ).fetchone() is not None:
            return False
        conn.execute(
            "INSERT INTO scenes (campaign_id, scene_id, name, status) VALUES (?, ?, ?, ?)",
            (camp_id, scene_id, name, "open"),
        )
        conn.commit()
    return {"id": scene_id, "name": name, "status": "open"}


def get_scene(camp_id, scene_id):
    """Return a scene or None if missing."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT scene_id, name, status FROM scenes WHERE campaign_id = ? AND scene_id = ?",
            (camp_id, scene_id),
        ).fetchone()
        if row is None:
            return None
        return {"id": row["scene_id"], "name": row["name"], "status": row["status"]}


def enter_scene(camp_id, scene_id):
    """Set a play campaign's current scene.

    Returns the current scene summary on success, None if the campaign
    is missing, "scene_not_found" if the scene does not exist, or
    "closed" if the scene is not open.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        row = conn.execute(
            "SELECT name, status FROM scenes WHERE campaign_id = ? AND scene_id = ?",
            (camp_id, scene_id),
        ).fetchone()
        if row is None:
            return "scene_not_found"
        if row["status"] != "open":
            return "closed"
        conn.execute(
            "UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?",
            (scene_id, camp_id),
        )
        sequence = _next_narration_sequence(conn, camp_id)
        conn.execute(
            "INSERT INTO play_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
            (camp_id, sequence, "scene", "dm", scene_id),
        )
        conn.commit()
    return {"current_scene_id": scene_id, "name": row["name"]}


def close_scene(camp_id, scene_id):
    """Mark a scene as closed.

    Returns the scene on success, None if the campaign is missing,
    or "scene_not_found" if the scene does not exist.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        row = conn.execute(
            "SELECT scene_id, status FROM scenes WHERE campaign_id = ? AND scene_id = ?",
            (camp_id, scene_id),
        ).fetchone()
        if row is None:
            return "scene_not_found"
        conn.execute(
            "UPDATE scenes SET status = 'closed' WHERE campaign_id = ? AND scene_id = ?",
            (camp_id, scene_id),
        )
        conn.commit()
    return {"id": scene_id, "status": "closed"}


def get_current_scene(camp_id):
    """Return the open current scene for a play campaign, or None.

    Returns None if the campaign is missing, no current scene is set,
    or the current scene is not open.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT p.current_scene_id, s.name, s.status "
            "FROM play_campaigns p LEFT JOIN scenes s "
            "ON p.id = s.campaign_id AND p.current_scene_id = s.scene_id "
            "WHERE p.id = ?",
            (camp_id,),
        ).fetchone()
        if row is None or row["current_scene_id"] is None or row["status"] != "open":
            return None
        return {
            "id": row["current_scene_id"],
            "name": row["name"],
            "status": row["status"],
        }


# --- Location graph ---


def create_location(camp_id, location_id, name):
    """Create a location in a play campaign.

    Returns the location on success, None if the campaign is missing,
    or False if the location id already exists in the campaign.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM play_locations WHERE campaign_id = ? AND location_id = ?",
            (camp_id, location_id),
        ).fetchone() is not None:
            return False
        conn.execute(
            "INSERT INTO play_locations (campaign_id, location_id, name) VALUES (?, ?, ?)",
            (camp_id, location_id, name),
        )
        conn.execute(
            "UPDATE play_campaigns SET current_location_id = ? WHERE id = ? AND current_location_id IS NULL",
            (location_id, camp_id),
        )
        conn.commit()
    return {"id": location_id, "name": name}


def get_location(camp_id, location_id):
    """Return a location in a play campaign, or None if missing."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT location_id, name FROM play_locations WHERE campaign_id = ? AND location_id = ?",
            (camp_id, location_id),
        ).fetchone()
        if row is None:
            return None
        return {"id": row["location_id"], "name": row["name"]}


def create_connection(camp_id, from_id, to_id, travel_turns):
    """Create a one-way travel connection between two locations.

    Returns the connection on success, None if the campaign is missing,
    "missing" if either location does not exist, or "duplicate" if a
    connection from from_id to to_id already exists.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if (
            conn.execute(
                "SELECT 1 FROM play_locations WHERE campaign_id = ? AND location_id = ?",
                (camp_id, from_id),
            ).fetchone()
            is None
            or conn.execute(
                "SELECT 1 FROM play_locations WHERE campaign_id = ? AND location_id = ?",
                (camp_id, to_id),
            ).fetchone()
            is None
        ):
            return "missing"
        if conn.execute(
            "SELECT 1 FROM play_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
            (camp_id, from_id, to_id),
        ).fetchone() is not None:
            return "duplicate"
        conn.execute(
            "INSERT INTO play_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)",
            (camp_id, from_id, to_id, travel_turns),
        )
        conn.commit()
    return {"from_id": from_id, "to_id": to_id, "travel_turns": travel_turns}


def get_travel_destinations(camp_id, location_id):
    """Return outbound destinations for a location.

    Returns a list of destination dicts, None if the campaign or location
    is missing, or an empty list when there are no outbound connections.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM play_locations WHERE campaign_id = ? AND location_id = ?",
            (camp_id, location_id),
        ).fetchone() is None:
            return None
        rows = conn.execute(
            "SELECT c.to_id, l.name, c.travel_turns "
            "FROM play_location_connections c "
            "JOIN play_locations l ON c.campaign_id = l.campaign_id AND c.to_id = l.location_id "
            "WHERE c.campaign_id = ? AND c.from_id = ? "
            "ORDER BY c.travel_turns, c.to_id",
            (camp_id, location_id),
        ).fetchall()
    return [{"id": r["to_id"], "name": r["name"], "travel_turns": r["travel_turns"]} for r in rows]


def create_travel(camp_id, actor, destination_id):
    """Consume a player's exploration turn to travel along a location edge.

    Returns the travel event on success, None if the campaign is missing,
    "not_your_turn" if the caller is not the current actor, or
    "invalid_destination" if the destination is not a valid outbound
    connection from the party's current location.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT owner, current_actor, current_location_id FROM play_campaigns WHERE id = ?",
            (camp_id,),
        ).fetchone()
        if row is None:
            return None
        if row["current_actor"] != actor:
            return "not_your_turn"
        if row["current_location_id"] is None:
            return "invalid_destination"
        edge = conn.execute(
            "SELECT travel_turns FROM play_location_connections "
            "WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
            (camp_id, row["current_location_id"], destination_id),
        ).fetchone()
        if edge is None:
            return "invalid_destination"
        travel_turns = edge["travel_turns"]
        sequence = _next_narration_sequence(conn, camp_id)
        conn.execute(
            "INSERT INTO play_narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
            (camp_id, sequence, "travel", actor, destination_id),
        )
        conn.execute(
            "UPDATE play_campaigns SET current_actor = ? WHERE id = ?",
            (row["owner"], camp_id),
        )
        conn.commit()
    return {
        "sequence": sequence,
        "kind": "travel",
        "actor": actor,
        "destination_id": destination_id,
        "travel_turns": travel_turns,
        "next_actor": row["owner"],
    }


def create_encounter(camp_id, encounter_id, name):
    """Create a campaign-bound encounter.

    Returns the encounter on success, None if the campaign is missing,
    "duplicate" if the encounter id already exists in the campaign, or
    "in_combat" if the campaign already has an active encounter.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, encounter_id),
        ).fetchone() is not None:
            return "duplicate"
        if conn.execute(
            "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND status = ?",
            (camp_id, "active"),
        ).fetchone() is not None:
            return "in_combat"
        conn.execute(
            "INSERT INTO play_encounters (campaign_id, encounter_id, name, status, round, turn_index) VALUES (?, ?, ?, ?, ?, ?)",
            (camp_id, encounter_id, name, "active", 1, 0),
        )
        camp_row = conn.execute(
            "SELECT phase, current_actor FROM play_campaigns WHERE id = ?",
            (camp_id,),
        ).fetchone()
        if camp_row["phase"] != "combat":
            conn.execute(
                "UPDATE play_campaigns SET phase = ?, pre_combat_actor = ? WHERE id = ?",
                ("combat", camp_row["current_actor"], camp_id),
            )
        conn.commit()
    return {"id": encounter_id, "name": name, "status": "active", "combatants": []}


def _get_encounter_order(conn, camp_id, enc_id):
    """Return the stored encounter order list, or None if not set."""
    row = conn.execute(
        "SELECT combatant_order FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
        (camp_id, enc_id),
    ).fetchone()
    if not row or not row["combatant_order"]:
        return None
    try:
        order = json.loads(row["combatant_order"])
    except json.JSONDecodeError:
        return None
    if not order:
        return None
    return order


def _set_encounter_order(conn, camp_id, enc_id, order):
    """Persist the encounter order list as JSON."""
    conn.execute(
        "UPDATE play_encounters SET combatant_order = ? WHERE campaign_id = ? AND encounter_id = ?",
        (json.dumps(order), camp_id, enc_id),
    )


def _encounter_order_initiative_map(conn, camp_id, enc_id, order):
    """Return a dict mapping (kind, id) to initiative for the order entries."""
    initiatives = {}
    monster_ids = [o["id"] for o in order if o["kind"] == "monster"]
    if monster_ids:
        placeholders = ",".join("?" * len(monster_ids))
        rows = conn.execute(
            "SELECT monster_id, initiative FROM play_encounter_monsters "
            "WHERE campaign_id = ? AND encounter_id = ? AND monster_id IN ({})".format(placeholders),
            (camp_id, enc_id) + tuple(monster_ids),
        ).fetchall()
        initiatives.update({("monster", r["monster_id"]): r["initiative"] for r in rows})
    player_ids = [o["id"] for o in order if o["kind"] == "player"]
    if player_ids:
        placeholders = ",".join("?" * len(player_ids))
        rows = conn.execute(
            "SELECT member, initiative FROM play_encounter_combatants "
            "WHERE campaign_id = ? AND encounter_id = ? AND member IN ({})".format(placeholders),
            (camp_id, enc_id) + tuple(player_ids),
        ).fetchall()
        initiatives.update({("player", r["member"]): r["initiative"] for r in rows})
    return initiatives


def _insert_into_encounter_order(conn, camp_id, enc_id, kind, combatant_id, initiative):
    """Insert a combatant into the stored encounter order by initiative."""
    order = _get_encounter_order(conn, camp_id, enc_id)
    if order is None:
        return
    initiatives = _encounter_order_initiative_map(conn, camp_id, enc_id, order)
    entry = {"kind": kind, "id": combatant_id}
    insert_at = len(order)
    for i, o in enumerate(order):
        init = initiatives.get((o["kind"], o["id"]))
        if init is not None and initiative > init:
            insert_at = i
            break
    order.insert(insert_at, entry)
    _set_encounter_order(conn, camp_id, enc_id, order)


def _remove_from_encounter_order(conn, camp_id, enc_id, kind, combatant_id):
    """Remove a combatant from the stored encounter order if present."""
    order = _get_encounter_order(conn, camp_id, enc_id)
    if order is None:
        return
    order = [o for o in order if o["kind"] != kind or o["id"] != combatant_id]
    _set_encounter_order(conn, camp_id, enc_id, order)


def _encounter_combatants(conn, camp_id, enc_id):
    """Return all combatants in an encounter sorted by initiative or stored order.

    Each combatant has a unique id (monster_id for monsters, member username
    for players), a display name, kind ("monster" or "player"), initiative,
    and for player combatants the controlling member username.
    """
    rows = conn.execute(
        "SELECT monster_id, name, initiative FROM play_encounter_monsters "
        "WHERE campaign_id = ? AND encounter_id = ?",
        (camp_id, enc_id),
    ).fetchall()
    combatants = [
        {"id": r["monster_id"], "name": r["name"], "kind": "monster", "initiative": r["initiative"]} for r in rows
    ]
    rows = conn.execute(
        "SELECT member, name, initiative FROM play_encounter_combatants "
        "WHERE campaign_id = ? AND encounter_id = ?",
        (camp_id, enc_id),
    ).fetchall()
    for r in rows:
        combatants.append(
            {
                "id": r["member"],
                "name": r["name"],
                "kind": "player",
                "initiative": r["initiative"],
                "member": r["member"],
            }
        )
    order = _get_encounter_order(conn, camp_id, enc_id)
    if order:
        order_key = {(o["kind"], o["id"]): i for i, o in enumerate(order)}
        combatants.sort(
            key=lambda c: (
                order_key.get((c["kind"], c["id"]), len(order)),
                -c["initiative"],
                c["name"],
            )
        )
    else:
        # Deterministic initiative order: highest initiative first, then name.
        combatants.sort(key=lambda c: (-c["initiative"], c["name"]))
    return combatants


def get_encounter_turn(camp_id, enc_id):
    """Return the current turn state for an encounter.

    Returns None if the encounter is missing, or False if it has no
    combatants. The active dict includes the controlling member for
    player combatants so callers can enforce turn authority.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone() is None:
            return None
        combatants = _encounter_combatants(conn, camp_id, enc_id)
        if not combatants:
            return False
        row = conn.execute(
            "SELECT round, turn_index FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone()
        turn_index = row["turn_index"] % len(combatants)
        active = combatants[turn_index]
        return {
            "round": row["round"],
            "turn_index": turn_index,
            "active": active,
        }


def advance_encounter_turn(camp_id, enc_id):
    """Advance an encounter to the next combatant in initiative order.

    Conditions on the newly active combatant decrement at the start of its
    turn, and expired conditions are removed. Returns the new turn state,
    None if the encounter is missing, or False if it has no combatants.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone() is None:
            return None
        combatants = _encounter_combatants(conn, camp_id, enc_id)
        if not combatants:
            return False
        row = conn.execute(
            "SELECT round, turn_index FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone()
        turn_index = row["turn_index"] % len(combatants)
        next_index = turn_index + 1
        round_num = row["round"]
        if next_index >= len(combatants):
            next_index = 0
            round_num += 1
        active = combatants[next_index]

        # Decay and remove expired conditions at the start of the active turn.
        conn.execute(
            "UPDATE play_encounter_conditions SET remaining_rounds = remaining_rounds - 1 "
            "WHERE campaign_id = ? AND encounter_id = ? AND target = ?",
            (camp_id, enc_id, active["id"]),
        )
        conn.execute(
            "DELETE FROM play_encounter_conditions "
            "WHERE campaign_id = ? AND encounter_id = ? AND target = ? AND remaining_rounds <= 0",
            (camp_id, enc_id, active["id"]),
        )
        conn.execute(
            "UPDATE play_encounters SET round = ?, turn_index = ? WHERE campaign_id = ? AND encounter_id = ?",
            (round_num, next_index, camp_id, enc_id),
        )
        conn.commit()
        return {
            "round": round_num,
            "turn_index": next_index,
            "active": active,
        }


def delay_encounter_turn(camp_id, enc_id, new_index):
    """Move the current combatant to a later position in the initiative order.

    Returns the new order on success, None if the encounter is missing,
    "invalid_index" if the target index is illegal, or False if the encounter
    has no combatants.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone() is None:
            return None
        combatants = _encounter_combatants(conn, camp_id, enc_id)
        if not combatants:
            return False
        row = conn.execute(
            "SELECT round, turn_index, combatant_order FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone()
        turn_index = row["turn_index"] % len(combatants)

        order = _get_encounter_order(conn, camp_id, enc_id)
        if order is None:
            order = [{"kind": c["kind"], "id": c["id"]} for c in combatants]

        if not isinstance(new_index, int) or new_index <= turn_index or new_index >= len(order):
            return "invalid_index"

        current = order.pop(turn_index)
        order.insert(new_index, current)

        _set_encounter_order(conn, camp_id, enc_id, order)
        conn.execute(
            "UPDATE play_encounters SET turn_index = ? WHERE campaign_id = ? AND encounter_id = ?",
            (new_index, camp_id, enc_id),
        )
        conn.commit()

        new_combatants = _encounter_combatants(conn, camp_id, enc_id)
        return {
            "round": row["round"],
            "turn_index": turn_index,
            "order": new_combatants,
        }


def add_encounter_condition(camp_id, enc_id, target, condition_text, duration):
    """Add a condition to an encounter combatant.

    Returns the target's updated condition list, None if the encounter is
    missing, or False if the target is not a combatant in the encounter.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone() is None:
            return None

        combatants = _encounter_combatants(conn, camp_id, enc_id)
        target_combatant = None
        for c in combatants:
            if c["id"] == target or c["name"] == target:
                target_combatant = c
                break
        if target_combatant is None:
            return False

        canonical_target = target_combatant["id"]
        conn.execute(
            "INSERT INTO play_encounter_conditions (campaign_id, encounter_id, target, condition, remaining_rounds) "
            "VALUES (?, ?, ?, ?, ?)",
            (camp_id, enc_id, canonical_target, condition_text, duration),
        )
        conn.commit()
        rows = conn.execute(
            "SELECT condition, remaining_rounds FROM play_encounter_conditions "
            "WHERE campaign_id = ? AND encounter_id = ? AND target = ? ORDER BY id",
            (camp_id, enc_id, canonical_target),
        ).fetchall()
        return [{"condition": r["condition"], "remaining_rounds": r["remaining_rounds"]} for r in rows]


def get_encounter_status(camp_id, enc_id):
    """Return the full encounter state including a conditions map.

    Returns None if the encounter is missing, or False if it has no
    combatants. Every combatant has a key in the conditions map, even
    when it has no active conditions.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone() is None:
            return None
        combatants = _encounter_combatants(conn, camp_id, enc_id)
        if not combatants:
            return False
        row = conn.execute(
            "SELECT round, turn_index FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone()
        turn_index = row["turn_index"] % len(combatants)
        active = combatants[turn_index]

        conditions = {c["id"]: [] for c in combatants}
        rows = conn.execute(
            "SELECT target, condition, remaining_rounds FROM play_encounter_conditions "
            "WHERE campaign_id = ? AND encounter_id = ? ORDER BY id",
            (camp_id, enc_id),
        ).fetchall()
        for r in rows:
            conditions.setdefault(r["target"], []).append(
                {"condition": r["condition"], "remaining_rounds": r["remaining_rounds"]}
            )

        return {
            "round": row["round"],
            "turn_index": turn_index,
            "active": active,
            "order": combatants,
            "conditions": conditions,
        }


def add_encounter_monster(camp_id, enc_id, monster_id, name, hp_max, initiative):
    """Add a monster to a play campaign encounter.

    Returns the monster on success, None if the encounter is missing,
    or "duplicate" if the monster_id already exists in the encounter.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM play_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?",
            (camp_id, enc_id, monster_id),
        ).fetchone() is not None:
            return "duplicate"
        conn.execute(
            "INSERT INTO play_encounter_monsters (campaign_id, encounter_id, monster_id, name, hp_max, hp_current, initiative) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (camp_id, enc_id, monster_id, name, hp_max, hp_max, initiative),
        )
        _insert_into_encounter_order(conn, camp_id, enc_id, "monster", monster_id, initiative)
        conn.commit()
    return {"monster_id": monster_id, "name": name, "hp_max": hp_max, "initiative": initiative, "hp_current": hp_max}


def remove_encounter_monster(camp_id, enc_id, monster_id):
    """Remove a monster from a play campaign encounter.

    Returns the removed monster_id on success, None if the encounter is
    missing, or False if the monster_id is not in the encounter.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM play_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?",
            (camp_id, enc_id, monster_id),
        ).fetchone() is None:
            return False
        conn.execute(
            "DELETE FROM play_encounter_monsters WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?",
            (camp_id, enc_id, monster_id),
        )
        _remove_from_encounter_order(conn, camp_id, enc_id, "monster", monster_id)
        conn.commit()
    return monster_id


def bind_encounter_member(camp_id, enc_id, member, initiative):
    """Bind a party member to an active encounter as a combatant.

    Returns the combatant on success, None if the campaign or encounter is
    missing, "missing_member" if the player is not in the party, or
    "duplicate" if the member is already bound to the encounter.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone() is None:
            return None
        member_row = conn.execute(
            "SELECT character_id, name FROM play_campaign_members WHERE campaign_id = ? AND player = ?",
            (camp_id, member),
        ).fetchone()
        if member_row is None:
            return "missing_member"
        if conn.execute(
            "SELECT 1 FROM play_encounter_combatants WHERE campaign_id = ? AND encounter_id = ? AND member = ?",
            (camp_id, enc_id, member),
        ).fetchone() is not None:
            return "duplicate"
        conn.execute(
            "INSERT INTO play_encounter_combatants (campaign_id, encounter_id, member, character_id, name, initiative) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (camp_id, enc_id, member, member_row["character_id"], member_row["name"], initiative),
        )
        _insert_into_encounter_order(conn, camp_id, enc_id, "player", member, initiative)
        conn.commit()
    return {"member": member, "character_id": member_row["character_id"], "name": member_row["name"], "initiative": initiative}


def unbind_encounter_member(camp_id, enc_id, member):
    """Remove a party member from an encounter's combatant roster.

    Returns the removed member username on success, None if the encounter
    is missing, or False if the member is not bound to the encounter.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM play_encounter_combatants WHERE campaign_id = ? AND encounter_id = ? AND member = ?",
            (camp_id, enc_id, member),
        ).fetchone() is None:
            return False
        conn.execute(
            "DELETE FROM play_encounter_combatants WHERE campaign_id = ? AND encounter_id = ? AND member = ?",
            (camp_id, enc_id, member),
        )
        _remove_from_encounter_order(conn, camp_id, enc_id, "player", member)
        conn.commit()
    return member


def _apply_encounter_hp_change(camp_id, enc_id, target, delta, is_damage):
    """Apply damage or healing to an encounter combatant by name.

    Returns a dict with hp_before, hp_after, hp_max, kind, and target_name
    on success, None if the encounter is missing, or "not_found" if the
    target is not a combatant in the encounter.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone() is None:
            return None

        # Prefer monsters by combatant name, then by monster_id, then players by name.
        row = conn.execute(
            "SELECT monster_id, name, hp_current, hp_max FROM play_encounter_monsters "
            "WHERE campaign_id = ? AND encounter_id = ? AND name = ? "
            "ORDER BY rowid LIMIT 1",
            (camp_id, enc_id, target),
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT monster_id, name, hp_current, hp_max FROM play_encounter_monsters "
                "WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ? "
                "ORDER BY rowid LIMIT 1",
                (camp_id, enc_id, target),
            ).fetchone()
        if row:
            hp_before = row["hp_current"]
            if is_damage:
                hp_after = max(0, hp_before - delta)
            else:
                hp_after = min(row["hp_max"], hp_before + delta)
            conn.execute(
                "UPDATE play_encounter_monsters SET hp_current = ? "
                "WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?",
                (hp_after, camp_id, enc_id, row["monster_id"]),
            )
            conn.commit()
            return {
                "hp_before": hp_before,
                "hp_after": hp_after,
                "hp_max": row["hp_max"],
                "kind": "monster",
                "target_name": row["name"],
            }

        row = conn.execute(
            "SELECT member, name FROM play_encounter_combatants "
            "WHERE campaign_id = ? AND encounter_id = ? AND name = ? "
            "ORDER BY rowid LIMIT 1",
            (camp_id, enc_id, target),
        ).fetchone()
        if row:
            member_row = conn.execute(
                "SELECT hp_current, hp_max FROM play_campaign_members "
                "WHERE campaign_id = ? AND player = ?",
                (camp_id, row["member"]),
            ).fetchone()
            if member_row is None:
                return "not_found"
            hp_before = member_row["hp_current"]
            if is_damage:
                hp_after = max(0, hp_before - delta)
            else:
                hp_after = min(member_row["hp_max"], hp_before + delta)
            # Healing from 0 HP to positive HP restores consciousness and
            # clears death save counters.
            if not is_damage and hp_before == 0 and hp_after > 0:
                conn.execute(
                    "UPDATE play_campaign_members SET hp_current = ?, "
                    "death_save_successes = 0, death_save_failures = 0 "
                    "WHERE campaign_id = ? AND player = ?",
                    (hp_after, camp_id, row["member"]),
                )
            else:
                conn.execute(
                    "UPDATE play_campaign_members SET hp_current = ? "
                    "WHERE campaign_id = ? AND player = ?",
                    (hp_after, camp_id, row["member"]),
                )
            conn.commit()
            return {
                "hp_before": hp_before,
                "hp_after": hp_after,
                "hp_max": member_row["hp_max"],
                "kind": "player",
                "target_name": row["name"],
            }

        return "not_found"


def apply_encounter_damage(camp_id, enc_id, target, amount):
    """Apply damage to an encounter combatant. HP floors at 0.

    Returns the same dict as _apply_encounter_hp_change.
    """
    return _apply_encounter_hp_change(camp_id, enc_id, target, amount, is_damage=True)


def apply_encounter_healing(camp_id, enc_id, target, amount):
    """Apply healing to an encounter combatant. HP caps at hp_max.

    Returns the same dict as _apply_encounter_hp_change.
    """
    return _apply_encounter_hp_change(camp_id, enc_id, target, amount, is_damage=False)


def create_rest(camp_id, actor, rest_type):
    """Consume a player's exploration turn to rest.

    Returns the rest event on success, None if the campaign is missing,
    "not_your_turn" if the caller is not the current actor, or
    "invalid_type" if the rest type is not "short" or "long".
    """
    if rest_type not in ("short", "long"):
        return "invalid_type"
    with _get_db() as conn:
        row = conn.execute(
            "SELECT owner, current_actor, turn_number FROM play_campaigns WHERE id = ?",
            (camp_id,),
        ).fetchone()
        if row is None:
            return None
        if row["current_actor"] != actor:
            return "not_your_turn"
        member_row = conn.execute(
            "SELECT hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? AND player = ?",
            (camp_id, actor),
        ).fetchone()
        if member_row is None:
            return "not_your_turn"
        hp_current = member_row["hp_current"]
        hp_max = member_row["hp_max"]
        if rest_type == "long":
            hp_current = hp_max
            conn.execute(
                "UPDATE play_campaign_members SET hp_current = ? WHERE campaign_id = ? AND player = ?",
                (hp_current, camp_id, actor),
            )
        sequence = _next_narration_sequence(conn, camp_id)
        conn.execute(
            "INSERT INTO play_narrations (campaign_id, sequence, kind, actor, type, text) VALUES (?, ?, ?, ?, ?, ?)",
            (camp_id, sequence, "rest", actor, rest_type, rest_type),
        )
        conn.execute(
            "UPDATE play_campaigns SET current_actor = ? WHERE id = ?",
            (row["owner"], camp_id),
        )
        conn.commit()
    return {
        "sequence": sequence,
        "kind": "rest",
        "actor": actor,
        "type": rest_type,
        "hp_current": hp_current,
        "hp_max": hp_max,
        "next_actor": row["owner"],
    }


def create_combat_action(camp_id, enc_id, actor, action_type, target, text):
    """Record a typed combat action for the current encounter combatant.

    The action is appended to the campaign log but does not advance the
    encounter turn. Returns the action event on success, or None if the
    encounter is missing.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone() is None:
            return None
        sequence = _next_narration_sequence(conn, camp_id)
        conn.execute(
            "INSERT INTO play_narrations (campaign_id, sequence, kind, actor, type, target, text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (camp_id, sequence, "combat_action", actor, action_type, target, text),
        )
        conn.commit()
    return {
        "sequence": sequence,
        "kind": "combat_action",
        "actor": actor,
        "type": action_type,
        "target": target,
        "text": text,
    }


def create_ready_action(camp_id, enc_id, actor, trigger):
    """Record a ready action for the current encounter combatant.

    The ready action is appended to the campaign log but does not advance
    the encounter turn. Returns the ready record on success, or None if the
    encounter is missing.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone() is None:
            return None
        sequence = _next_narration_sequence(conn, camp_id)
        conn.execute(
            "INSERT INTO play_narrations (campaign_id, sequence, kind, actor, type, text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (camp_id, sequence, "ready", actor, "ready", trigger),
        )
        conn.commit()
    return {
        "actor": actor,
        "trigger": trigger,
    }


# --- Encounter rewards and close ---


def award_encounter_rewards(camp_id, enc_id, xp, loot):
    """Record deterministic XP and loot for an encounter.

    Returns the reward record on success, None if the encounter is missing,
    or "already_awarded" if the encounter already has rewards.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT status, xp_awarded, loot FROM play_encounters "
            "WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone()
        if row is None:
            return None
        if row["xp_awarded"] > 0 or row["loot"] is not None:
            return "already_awarded"
        conn.execute(
            "UPDATE play_encounters SET xp_awarded = ?, loot = ? "
            "WHERE campaign_id = ? AND encounter_id = ?",
            (xp, json.dumps(loot), camp_id, enc_id),
        )
        conn.commit()
    return {"id": enc_id, "xp": xp, "loot": loot}


def close_encounter(camp_id, enc_id):
    """Mark an encounter as closed and return its final state.

    Returns the closed encounter summary on success, None if the encounter
    is missing.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone() is None:
            return None
        conn.execute(
            "UPDATE play_encounters SET status = 'closed' WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT encounter_id, status, xp_awarded FROM play_encounters "
            "WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone()
    return {
        "id": row["encounter_id"],
        "status": row["status"],
        "xp_awarded": row["xp_awarded"],
    }


def end_encounter(camp_id, enc_id):
    """Close an active encounter and return the campaign to exploration.

    Returns the campaign summary on success, None if the encounter is missing,
    or "not_in_combat" if the campaign is not currently in combat.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        camp_row = conn.execute(
            "SELECT status, current_actor, phase, pre_combat_actor FROM play_campaigns WHERE id = ?",
            (camp_id,),
        ).fetchone()
        if camp_row["phase"] != "combat":
            return "not_in_combat"
        enc_row = conn.execute(
            "SELECT status FROM play_encounters WHERE campaign_id = ? AND encounter_id = ?",
            (camp_id, enc_id),
        ).fetchone()
        if enc_row is None:
            return None
        if enc_row["status"] == "active":
            conn.execute(
                "UPDATE play_encounters SET status = 'closed' WHERE campaign_id = ? AND encounter_id = ?",
                (camp_id, enc_id),
            )
        restored_actor = camp_row["pre_combat_actor"] if camp_row["pre_combat_actor"] is not None else camp_row["current_actor"]
        conn.execute(
            "UPDATE play_campaigns SET phase = ?, current_actor = ? WHERE id = ?",
            ("exploration", restored_actor, camp_id),
        )
        conn.commit()
    return {
        "campaign_id": camp_id,
        "status": camp_row["status"],
        "phase": "exploration",
        "current_actor": restored_actor,
    }


# --- Loot distribution ---


def create_loot(camp_id, loot_id, item_id, quantity):
    """Create a campaign-scoped loot record.

    Returns the loot record on success, None if the campaign is missing,
    or "duplicate" if the loot id already exists in the campaign.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM play_loot WHERE campaign_id = ? AND loot_id = ?",
            (camp_id, loot_id),
        ).fetchone() is not None:
            return "duplicate"
        conn.execute(
            "INSERT INTO play_loot (campaign_id, loot_id, item_id, quantity, status) VALUES (?, ?, ?, ?, ?)",
            (camp_id, loot_id, item_id, quantity, "open"),
        )
        conn.commit()
    return {"loot_id": loot_id, "item_id": item_id, "quantity": quantity, "status": "open"}


def add_loot_vote(camp_id, loot_id, voter, recipient_character_id):
    """Cast a single immutable vote for a loot recipient.

    Returns the vote summary on success, None if the loot is missing,
    "not_open" if the loot is no longer open, "invalid_recipient" if the
    recipient is not a campaign character, or "already_voted" if the voter
    has already voted on this loot record.
    """
    with _get_db() as conn:
        loot_row = conn.execute(
            "SELECT status FROM play_loot WHERE campaign_id = ? AND loot_id = ?",
            (camp_id, loot_id),
        ).fetchone()
        if loot_row is None:
            return None
        if loot_row["status"] != "open":
            return "not_open"
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, recipient_character_id),
        ).fetchone() is None:
            return "invalid_recipient"
        if conn.execute(
            "SELECT 1 FROM play_loot_votes WHERE campaign_id = ? AND loot_id = ? AND voter = ?",
            (camp_id, loot_id, voter),
        ).fetchone() is not None:
            return "already_voted"
        conn.execute(
            "INSERT INTO play_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)",
            (camp_id, loot_id, voter, recipient_character_id),
        )
        conn.commit()
        count_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM play_loot_votes "
            "WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?",
            (camp_id, loot_id, recipient_character_id),
        ).fetchone()
    return {
        "loot_id": loot_id,
        "voter": voter,
        "recipient_character_id": recipient_character_id,
        "votes_for_recipient": count_row["cnt"],
    }


def assign_loot(camp_id, loot_id):
    """Assign loot to the single highest-voted recipient.

    Atomically adds the loot quantity to the recipient's inventory, closes
    the loot, and returns the assignment summary. Returns None if the loot is
    missing, "not_open" if it is already assigned, "no_votes" if it has no
    votes, or "tied" if the highest vote count is shared by multiple
    recipients.
    """
    with _get_db() as conn:
        loot_row = conn.execute(
            "SELECT item_id, quantity, status FROM play_loot WHERE campaign_id = ? AND loot_id = ?",
            (camp_id, loot_id),
        ).fetchone()
        if loot_row is None:
            return None
        if loot_row["status"] != "open":
            return "not_open"

        rows = conn.execute(
            "SELECT recipient_character_id, COUNT(*) AS cnt FROM play_loot_votes "
            "WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id "
            "ORDER BY cnt DESC, recipient_character_id",
            (camp_id, loot_id),
        ).fetchall()
        if not rows:
            return "no_votes"
        max_count = rows[0]["cnt"]
        top_recipients = [r["recipient_character_id"] for r in rows if r["cnt"] == max_count]
        if len(top_recipients) > 1:
            return "tied"
        winner = top_recipients[0]

        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, winner),
        ).fetchone() is None:
            return "invalid_recipient"

        held_row = conn.execute(
            "SELECT quantity FROM character_inventory "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (camp_id, winner, loot_row["item_id"]),
        ).fetchone()
        total = (held_row["quantity"] if held_row else 0) + loot_row["quantity"]
        conn.execute(
            "INSERT INTO character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = excluded.quantity",
            (camp_id, winner, loot_row["item_id"], total),
        )
        conn.execute(
            "UPDATE play_loot SET status = ?, recipient_character_id = ? WHERE campaign_id = ? AND loot_id = ?",
            ("assigned", winner, camp_id, loot_id),
        )
        conn.commit()
    return {
        "loot_id": loot_id,
        "recipient_character_id": winner,
        "item_id": loot_row["item_id"],
        "quantity": loot_row["quantity"],
        "votes": max_count,
        "status": "assigned",
    }


def get_loot(camp_id, loot_id):
    """Return a loot record with its votes, or None if missing."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT loot_id, item_id, quantity, status, recipient_character_id FROM play_loot "
            "WHERE campaign_id = ? AND loot_id = ?",
            (camp_id, loot_id),
        ).fetchone()
        if row is None:
            return None
        vote_rows = conn.execute(
            "SELECT recipient_character_id, COUNT(*) AS cnt FROM play_loot_votes "
            "WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id",
            (camp_id, loot_id),
        ).fetchall()
    return {
        "loot_id": row["loot_id"],
        "item_id": row["item_id"],
        "quantity": row["quantity"],
        "status": row["status"],
        "recipient_character_id": row["recipient_character_id"],
        "votes": {r["recipient_character_id"]: r["cnt"] for r in vote_rows},
    }


# --- Play campaign NPC agendas ---


def create_play_npc(camp_id, npc_id, name, agenda, public_status):
    """Create a DM-managed NPC in a play campaign.

    Returns the NPC on success, None if the campaign is missing,
    or "duplicate" if the npc_id already exists in the campaign.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM play_npcs WHERE campaign_id = ? AND npc_id = ?",
            (camp_id, npc_id),
        ).fetchone() is not None:
            return "duplicate"
        conn.execute(
            "INSERT INTO play_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)",
            (camp_id, npc_id, name, agenda, public_status),
        )
        conn.commit()
    return {"npc_id": npc_id, "name": name, "agenda": agenda, "public_status": public_status}


def update_play_npc_agenda(camp_id, npc_id, agenda, public_status):
    """Update an NPC's private agenda and public status.

    Returns the full NPC on success, or None if the NPC does not exist.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT name FROM play_npcs WHERE campaign_id = ? AND npc_id = ?",
            (camp_id, npc_id),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE play_npcs SET agenda = ?, public_status = ? WHERE campaign_id = ? AND npc_id = ?",
            (agenda, public_status, camp_id, npc_id),
        )
        conn.commit()
    return {"npc_id": npc_id, "name": row["name"], "agenda": agenda, "public_status": public_status}


def get_play_npc(camp_id, npc_id):
    """Return a play campaign NPC, or None if missing."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT npc_id, name, agenda, public_status FROM play_npcs WHERE campaign_id = ? AND npc_id = ?",
            (camp_id, npc_id),
        ).fetchone()
        if row is None:
            return None
    return {
        "npc_id": row["npc_id"],
        "name": row["name"],
        "agenda": row["agenda"],
        "public_status": row["public_status"],
    }


# --- NPC dialogue ---


def create_npc_dialogue(camp_id, npc_id, dialogue_id, speaker, text, visibility):
    """Create a dialogue entry for a play campaign NPC.

    Returns the entry on success, None if the NPC is missing,
    or "duplicate" if the dialogue_id already exists for this NPC.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_npcs WHERE campaign_id = ? AND npc_id = ?",
            (camp_id, npc_id),
        ).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM npc_dialogue WHERE campaign_id = ? AND npc_id = ? AND dialogue_id = ?",
            (camp_id, npc_id, dialogue_id),
        ).fetchone() is not None:
            return "duplicate"
        sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM npc_dialogue WHERE campaign_id = ? AND npc_id = ?",
            (camp_id, npc_id),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO npc_dialogue (campaign_id, npc_id, dialogue_id, speaker, text, visibility, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (camp_id, npc_id, dialogue_id, speaker, text, visibility, sequence),
        )
        conn.commit()
    return {
        "dialogue_id": dialogue_id,
        "speaker": speaker,
        "text": text,
        "visibility": visibility,
    }


def get_npc_dialogue_history(camp_id, npc_id, include_private=False):
    """Return dialogue history for a play campaign NPC.

    Returns the NPC dialogue dict on success, or None if the NPC is missing.
    When include_private is False, only public entries are returned.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_npcs WHERE campaign_id = ? AND npc_id = ?",
            (camp_id, npc_id),
        ).fetchone() is None:
            return None
        sql = (
            "SELECT dialogue_id, speaker, text, visibility FROM npc_dialogue "
            "WHERE campaign_id = ? AND npc_id = ?"
        )
        params = [camp_id, npc_id]
        if not include_private:
            sql += " AND visibility = ?"
            params.append("public")
        sql += " ORDER BY sequence"
        rows = conn.execute(sql, params).fetchall()
    entries = [
        {
            "dialogue_id": r["dialogue_id"],
            "speaker": r["speaker"],
            "text": r["text"],
            "visibility": r["visibility"],
        }
        for r in rows
    ]
    return {"npc_id": npc_id, "entries": entries}


# --- Play campaign factions and reputation ---


def create_play_faction(camp_id, faction_id, name):
    """Create a faction in a play campaign.

    Returns the faction on success, None if the campaign is missing,
    or "duplicate" if the faction id already exists in the campaign.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM play_factions WHERE campaign_id = ? AND faction_id = ?",
            (camp_id, faction_id),
        ).fetchone() is not None:
            return "duplicate"
        conn.execute(
            "INSERT INTO play_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)",
            (camp_id, faction_id, name),
        )
        conn.commit()
    return {"faction_id": faction_id, "name": name}


def get_play_faction(camp_id, faction_id):
    """Return a play campaign faction, or None if missing."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT faction_id, name FROM play_factions WHERE campaign_id = ? AND faction_id = ?",
            (camp_id, faction_id),
        ).fetchone()
        if row is None:
            return None
    return {"faction_id": row["faction_id"], "name": row["name"]}


def create_reputation_change(camp_id, faction_id, character_id, delta, reason):
    """Record a bounded reputation change for a faction/character pair.

    Returns the new reputation entry on success, None if the faction is
    missing, or "invalid_character" if the character is not a member.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_factions WHERE campaign_id = ? AND faction_id = ?",
            (camp_id, faction_id),
        ).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, character_id),
        ).fetchone() is None:
            return "invalid_character"

        rows = conn.execute(
            "SELECT delta FROM reputation_history "
            "WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY sequence",
            (camp_id, faction_id, character_id),
        ).fetchall()
        total = 0
        for r in rows:
            total = max(-100, min(100, total + r["delta"]))
        new_total = max(-100, min(100, total + delta))

        sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM reputation_history "
            "WHERE campaign_id = ? AND faction_id = ?",
            (camp_id, faction_id),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO reputation_history (campaign_id, faction_id, character_id, sequence, delta, reason) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (camp_id, faction_id, character_id, sequence, delta, reason),
        )
        conn.commit()
    return {
        "faction_id": faction_id,
        "character_id": character_id,
        "reputation": new_total,
        "delta": delta,
        "reason": reason,
    }


def get_reputation_history(camp_id, faction_id, character_id=None):
    """Return the reputation history for a play faction.

    Returns the full entry list on success, or None if the faction is missing.
    When character_id is provided, only entries for that character are returned.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_factions WHERE campaign_id = ? AND faction_id = ?",
            (camp_id, faction_id),
        ).fetchone() is None:
            return None
        rows = conn.execute(
            "SELECT character_id, delta, reason FROM reputation_history "
            "WHERE campaign_id = ? AND faction_id = ? ORDER BY sequence",
            (camp_id, faction_id),
        ).fetchall()

    totals = {}
    entries = []
    for r in rows:
        char = r["character_id"]
        totals[char] = max(-100, min(100, totals.get(char, 0) + r["delta"]))
        entries.append(
            {
                "faction_id": faction_id,
                "character_id": char,
                "reputation": totals[char],
                "delta": r["delta"],
                "reason": r["reason"],
            }
        )

    if character_id is not None:
        entries = [e for e in entries if e["character_id"] == character_id]

    return {"faction_id": faction_id, "entries": entries}


# --- Play campaign relationship graph ---


def _is_play_campaign_entity(conn, camp_id, entity_id):
    """Return True when the entity ID names a character or NPC in the campaign."""
    if conn.execute(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
        (camp_id, entity_id),
    ).fetchone() is not None:
        return True
    if conn.execute(
        "SELECT 1 FROM play_npcs WHERE campaign_id = ? AND npc_id = ?",
        (camp_id, entity_id),
    ).fetchone() is not None:
        return True
    return False


def create_relationship(camp_id, source_id, target_id, kind, score):
    """Create a directed relationship edge in a play campaign.

    Returns the edge on success, None if the campaign is missing,
    "missing_entity" if either source or target does not exist in the
    campaign, or "duplicate" if the (source_id, target_id, kind) edge
    already exists.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if not _is_play_campaign_entity(conn, camp_id, source_id):
            return "missing_entity"
        if not _is_play_campaign_entity(conn, camp_id, target_id):
            return "missing_entity"
        if conn.execute(
            "SELECT 1 FROM play_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
            (camp_id, source_id, target_id, kind),
        ).fetchone() is not None:
            return "duplicate"
        sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_relationships WHERE campaign_id = ?",
            (camp_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO play_relationships (campaign_id, source_id, target_id, kind, score, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (camp_id, source_id, target_id, kind, score, sequence),
        )
        conn.commit()
    return {"source_id": source_id, "target_id": target_id, "kind": kind, "score": score}


def update_relationship(camp_id, source_id, target_id, kind, score):
    """Update the score of an existing relationship edge.

    Returns the full updated edge on success, or None if the edge does not
    exist.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM play_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
            (camp_id, source_id, target_id, kind),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE play_relationships SET score = ? WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
            (score, camp_id, source_id, target_id, kind),
        )
        conn.commit()
    return {"source_id": source_id, "target_id": target_id, "kind": kind, "score": score}


def get_relationships(camp_id):
    """Return all relationship edges for a play campaign in insertion order.

    Returns a list of edges, or None if the campaign is missing.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        rows = conn.execute(
            "SELECT source_id, target_id, kind, score FROM play_relationships "
            "WHERE campaign_id = ? ORDER BY sequence",
            (camp_id,),
        ).fetchall()
    return [
        {"source_id": r["source_id"], "target_id": r["target_id"], "kind": r["kind"], "score": r["score"]}
        for r in rows
    ]


# --- Campaign clues ---


def _next_clue_sequence(conn, camp_id):
    """Return the next sequence number for a campaign's clue table."""
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM play_clues WHERE campaign_id = ?",
        (camp_id,),
    ).fetchone()
    return row["next_seq"]


def create_clue(camp_id, clue_id, text, audience, character_id):
    """Create a campaign clue.

    Returns the clue dict on success, None if the campaign is missing,
    "duplicate" if the clue_id already exists in the campaign, or
    "invalid_character" if the targeted character is not a member.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM play_clues WHERE campaign_id = ? AND clue_id = ?",
            (camp_id, clue_id),
        ).fetchone() is not None:
            return "duplicate"
        if audience == "character" and conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (camp_id, character_id),
        ).fetchone() is None:
            return "invalid_character"
        sequence = _next_clue_sequence(conn, camp_id)
        conn.execute(
            "INSERT INTO play_clues (campaign_id, clue_id, text, audience, character_id, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (camp_id, clue_id, text, audience, character_id, sequence),
        )
        conn.commit()
    result = {"clue_id": clue_id, "text": text, "audience": audience}
    if audience == "character":
        result["character_id"] = character_id
    return result


def get_clues(camp_id, character_id=None):
    """Return clues visible to a viewer.

    When character_id is None, all clues are returned in insertion order.
    When character_id is provided, only party clues and clues targeted at
    that character are returned; hidden clues are excluded.
    Returns None if the campaign is missing.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if character_id is None:
            rows = conn.execute(
                "SELECT clue_id, text, audience, character_id FROM play_clues "
                "WHERE campaign_id = ? ORDER BY sequence",
                (camp_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT clue_id, text, audience, character_id FROM play_clues "
                "WHERE campaign_id = ? AND (audience = 'party' OR (audience = 'character' AND character_id = ?)) "
                "ORDER BY sequence",
                (camp_id, character_id),
            ).fetchall()
    clues = []
    for r in rows:
        clue = {"clue_id": r["clue_id"], "text": r["text"], "audience": r["audience"]}
        if r["audience"] == "character":
            clue["character_id"] = r["character_id"]
        clues.append(clue)
    return clues


# --- Campaign quests (play surface) ---


def _next_quest_sequence(conn, camp_id):
    """Return the next sequence number for a campaign's quest table."""
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM play_quests WHERE campaign_id = ?",
        (camp_id,),
    ).fetchone()
    return row["next_seq"]


def _get_play_quest_with_deps(conn, camp_id, quest_id):
    """Return a play quest dict including its dependency list and rewards, or None."""
    row = conn.execute(
        "SELECT quest_id, title, state FROM play_quests "
        "WHERE campaign_id = ? AND quest_id = ?",
        (camp_id, quest_id),
    ).fetchone()
    if row is None:
        return None
    dep_rows = conn.execute(
        "SELECT depends_on FROM play_quest_dependencies "
        "WHERE campaign_id = ? AND quest_id = ? ORDER BY rowid",
        (camp_id, quest_id),
    ).fetchall()
    reward_row = conn.execute(
        "SELECT xp, items FROM play_quest_rewards "
        "WHERE campaign_id = ? AND quest_id = ?",
        (camp_id, quest_id),
    ).fetchone()
    result = {
        "quest_id": row["quest_id"],
        "title": row["title"],
        "depends_on": [d["depends_on"] for d in dep_rows],
        "state": row["state"],
    }
    if reward_row is not None:
        result["rewards"] = {"xp": reward_row["xp"], "items": json.loads(reward_row["items"])}
    return result


def get_play_quest(camp_id, quest_id):
    """Return a play quest by ID, or None if it does not exist."""
    with _get_db() as conn:
        return _get_play_quest_with_deps(conn, camp_id, quest_id)


def get_play_quests(camp_id):
    """Return all play quests for a campaign in creation order, or None if the campaign is missing."""
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        rows = conn.execute(
            "SELECT quest_id FROM play_quests WHERE campaign_id = ? ORDER BY sequence",
            (camp_id,),
        ).fetchall()
    return [_get_play_quest_with_deps(_get_db(), camp_id, r["quest_id"]) for r in rows]


def create_play_quest(camp_id, quest_id, title, depends_on):
    """Create a play quest with its dependency list.

    Returns the quest dict on success, None if the campaign is missing, or
    "duplicate" if the quest_id already exists in the campaign.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM play_quests WHERE campaign_id = ? AND quest_id = ?",
            (camp_id, quest_id),
        ).fetchone() is not None:
            return "duplicate"
        sequence = _next_quest_sequence(conn, camp_id)
        conn.execute(
            "INSERT INTO play_quests (campaign_id, quest_id, title, state, sequence) "
            "VALUES (?, ?, ?, ?, ?)",
            (camp_id, quest_id, title, "locked", sequence),
        )
        for dep in depends_on:
            conn.execute(
                "INSERT INTO play_quest_dependencies (campaign_id, quest_id, depends_on) "
                "VALUES (?, ?, ?)",
                (camp_id, quest_id, dep),
            )
        conn.commit()
    return get_play_quest(camp_id, quest_id)


def set_play_quest_state(camp_id, quest_id, state):
    """Set a play quest's state and return the updated quest dict.

    Returns None if the quest does not exist.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_quests WHERE campaign_id = ? AND quest_id = ?",
            (camp_id, quest_id),
        ).fetchone() is None:
            return None
        conn.execute(
            "UPDATE play_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?",
            (state, camp_id, quest_id),
        )
        conn.commit()
    return get_play_quest(camp_id, quest_id)


def configure_play_quest_rewards(camp_id, quest_id, xp, items):
    """Configure or replace the rewards for a play quest.

    Returns the updated quest dict on success, or None if the quest does not
    exist.
    """
    with _get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM play_quests WHERE campaign_id = ? AND quest_id = ?",
            (camp_id, quest_id),
        ).fetchone() is None:
            return None
        conn.execute(
            "INSERT INTO play_quest_rewards (campaign_id, quest_id, xp, items, awarded) "
            "VALUES (?, ?, ?, ?, 0) "
            "ON CONFLICT (campaign_id, quest_id) DO UPDATE SET "
            "xp = excluded.xp, items = excluded.items",
            (camp_id, quest_id, xp, json.dumps(items)),
        )
        conn.commit()
    return get_play_quest(camp_id, quest_id)


def award_play_quest_rewards(camp_id, quest_id):
    """Award configured quest rewards to every campaign member once.

    Returns a dict on success, None if the quest is missing, or a string error
    code ("not_configured", "not_completed", "already_awarded") if the award
    cannot proceed.
    """
    with _get_db() as conn:
        quest = _get_play_quest_with_deps(conn, camp_id, quest_id)
        if quest is None:
            return None
        reward_row = conn.execute(
            "SELECT xp, items, awarded FROM play_quest_rewards "
            "WHERE campaign_id = ? AND quest_id = ?",
            (camp_id, quest_id),
        ).fetchone()
        if reward_row is None:
            return "not_configured"
        if quest["state"] != "completed":
            return "not_completed"
        if reward_row["awarded"]:
            return "already_awarded"
        xp = reward_row["xp"]
        items = json.loads(reward_row["items"])
        members = conn.execute(
            "SELECT character_id FROM play_campaign_members WHERE campaign_id = ?",
            (camp_id,),
        ).fetchall()
        items_json = reward_row["items"]
        for member in members:
            conn.execute(
                "INSERT INTO play_quest_reward_grants "
                "(campaign_id, quest_id, character_id, xp, items) "
                "VALUES (?, ?, ?, ?, ?)",
                (camp_id, quest_id, member["character_id"], xp, items_json),
            )
        conn.execute(
            "UPDATE play_quest_rewards SET awarded = 1 "
            "WHERE campaign_id = ? AND quest_id = ?",
            (camp_id, quest_id),
        )
        conn.commit()
    return {"quest_id": quest_id, "awarded": True, "xp": xp, "items": items}


def get_character_quest_rewards(camp_id, char_id):
    """Return cumulative quest reward grants for a campaign character.

    Returns {"character_id": char_id, "xp": total, "items": {...}}.
    """
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT xp, items FROM play_quest_reward_grants "
            "WHERE campaign_id = ? AND character_id = ?",
            (camp_id, char_id),
        ).fetchall()
    total_xp = 0
    total_items = {}
    for row in rows:
        total_xp += row["xp"]
        for item_id, qty in json.loads(row["items"]).items():
            total_items[item_id] = total_items.get(item_id, 0) + qty
    return {"character_id": char_id, "xp": total_xp, "items": total_items}


# --- World events ---


def _next_world_event_sequence(conn, camp_id):
    """Return the next sequence number for a campaign's world events."""
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM play_world_events WHERE campaign_id = ?",
        (camp_id,),
    ).fetchone()
    return row["next_seq"]


def _world_event_row(row):
    """Build a world event dict from a storage row."""
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


def create_world_event(camp_id, event_id, turn_number, title, text):
    """Schedule a deterministic world event for a campaign turn.

    Returns the event dict on success, None if the campaign is missing,
    "duplicate" if the event_id already exists in the campaign, or
    "invalid_turn" if the requested turn is before the campaign's current
    turn number.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        if conn.execute(
            "SELECT 1 FROM play_world_events WHERE campaign_id = ? AND event_id = ?",
            (camp_id, event_id),
        ).fetchone() is not None:
            return "duplicate"
        camp_row = conn.execute(
            "SELECT turn_number FROM play_campaigns WHERE id = ?",
            (camp_id,),
        ).fetchone()
        if turn_number < camp_row["turn_number"]:
            return "invalid_turn"
        sequence = _next_world_event_sequence(conn, camp_id)
        conn.execute(
            "INSERT INTO play_world_events "
            "(campaign_id, event_id, turn_number, title, text, status, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (camp_id, event_id, turn_number, title, text, "scheduled", sequence),
        )
        conn.commit()
    return {
        "event_id": event_id,
        "turn_number": turn_number,
        "title": title,
        "text": text,
        "status": "scheduled",
    }


def resolve_world_event(camp_id, event_id, text):
    """Resolve a scheduled world event at its turn.

    Returns the resolved event dict on success, None if the event is missing,
    "already_resolved" if it has already been resolved, or "wrong_turn" if
    the campaign's current turn number does not match the event's turn.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT turn_number, title, text, status FROM play_world_events "
            "WHERE campaign_id = ? AND event_id = ?",
            (camp_id, event_id),
        ).fetchone()
        if row is None:
            return None
        if row["status"] == "resolved":
            return "already_resolved"
        camp_row = conn.execute(
            "SELECT turn_number FROM play_campaigns WHERE id = ?",
            (camp_id,),
        ).fetchone()
        if camp_row["turn_number"] != row["turn_number"]:
            return "wrong_turn"
        conn.execute(
            "UPDATE play_world_events SET status = ?, resolution_text = ?, resolution_turn_number = ? "
            "WHERE campaign_id = ? AND event_id = ?",
            ("resolved", text, camp_row["turn_number"], camp_id, event_id),
        )
        conn.commit()
    return {
        "event_id": event_id,
        "turn_number": row["turn_number"],
        "title": row["title"],
        "text": row["text"],
        "status": "resolved",
        "resolution": {
            "turn_number": camp_row["turn_number"],
            "text": text,
        },
    }


def get_world_events(camp_id):
    """Return all world events for a campaign, ordered by turn then creation.

    Returns None if the campaign is missing.
    """
    with _get_db() as conn:
        if conn.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (camp_id,)).fetchone() is None:
            return None
        rows = conn.execute(
            "SELECT event_id, turn_number, title, text, status, resolution_text, resolution_turn_number, sequence "
            "FROM play_world_events WHERE campaign_id = ? ORDER BY turn_number, sequence",
            (camp_id,),
        ).fetchall()
    return [_world_event_row(r) for r in rows]

