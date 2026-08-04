"""SQLite connection management and schema lifecycle.

Every request opens and closes its own connection (see get_db); there is no
pooling or long-lived connection, which keeps request handlers simple and
avoids cross-request state leaking through a shared connection.
"""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "game.db")
SCHEMA_VERSION = 1

_TABLE_NAMES = (
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
    "play_members",
    "play_character_owners",
    "play_scenes",
    "play_locations",
    "play_connections",
    "play_encounters",
    "play_encounter_monsters",
    "play_encounter_combatants",
    "play_encounter_conditions",
    "play_encounter_turn_order",
    "play_encounter_rewards",
    "play_character_spells",
    "play_character_prepared_spells",
    "play_character_casts",
    "play_character_concentration",
    "play_character_inventory",
    "play_character_equipment",
    "play_character_attunements",
    "play_character_currency",
    "play_currency_transfers",
    "play_loot",
    "play_loot_votes",
    "play_npcs",
    "play_factions",
    "play_faction_reputation",
    "play_npc_dialogue",
    "play_clues",
    "play_quests",
    "play_session_zero",
    "play_invitations",
    "play_delegations",
    "play_delegation_audit",
    "play_audit_events",
)

_SCHEMA_SQL = """
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
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    level INTEGER NOT NULL,
    class TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS campaign_events (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS quests (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    milestones_json TEXT NOT NULL,
    completed_json TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS factions (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    stance TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS npcs (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    faction_id TEXT,
    disposition INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS campaign_inventory (
    campaign_id TEXT NOT NULL,
    item_slug TEXT NOT NULL,
    owner TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, item_slug, owner),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS character_equipment (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    item_slug TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, character_id, item_slug),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS crafting_projects (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    item_slug TEXT NOT NULL,
    days_required INTEGER NOT NULL,
    days_completed INTEGER NOT NULL,
    cost_gp INTEGER NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS campaign_sessions (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    agenda_json TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS session_attendance (
    campaign_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    present_json TEXT NOT NULL,
    absent_json TEXT NOT NULL,
    PRIMARY KEY (campaign_id, session_id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

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
    current_location_id TEXT,
    in_combat INTEGER NOT NULL DEFAULT 0,
    pre_combat_actor TEXT
);

CREATE TABLE IF NOT EXISTS play_members (
    campaign_id TEXT NOT NULL,
    username TEXT NOT NULL,
    character_id TEXT NOT NULL,
    name TEXT NOT NULL,
    class TEXT NOT NULL,
    hp_current INTEGER NOT NULL DEFAULT 20,
    hp_max INTEGER NOT NULL DEFAULT 20,
    status TEXT NOT NULL DEFAULT 'active',
    death_save_successes INTEGER NOT NULL DEFAULT 0,
    death_save_failures INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (campaign_id, username),
    UNIQUE (campaign_id, character_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_character_owners (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    owner TEXT,
    race TEXT,
    class TEXT,
    background TEXT,
    level INTEGER,
    hp_max INTEGER,
    proficiency_bonus INTEGER,
    con_modifier INTEGER,
    str_modifier INTEGER,
    dex_modifier INTEGER,
    int_modifier INTEGER,
    wis_modifier INTEGER,
    cha_modifier INTEGER,
    PRIMARY KEY (campaign_id, character_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_events (
    campaign_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    kind TEXT NOT NULL,
    actor TEXT NOT NULL,
    type TEXT,
    target TEXT,
    text TEXT NOT NULL,
    PRIMARY KEY (campaign_id, sequence),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_scenes (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_locations (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_connections (
    campaign_id TEXT NOT NULL,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    travel_turns INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, from_id, to_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_encounters (
    campaign_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    round INTEGER NOT NULL DEFAULT 1,
    turn_index INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (campaign_id, id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
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
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_encounter_combatants (
    campaign_id TEXT NOT NULL,
    encounter_id TEXT NOT NULL,
    member TEXT NOT NULL,
    character_id TEXT NOT NULL,
    name TEXT NOT NULL,
    initiative INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, encounter_id, member),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_encounter_conditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    encounter_id TEXT NOT NULL,
    target TEXT NOT NULL,
    condition TEXT NOT NULL,
    remaining_rounds INTEGER NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_encounter_turn_order (
    campaign_id TEXT NOT NULL,
    encounter_id TEXT NOT NULL,
    order_json TEXT NOT NULL,
    PRIMARY KEY (campaign_id, encounter_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_encounter_rewards (
    campaign_id TEXT NOT NULL,
    encounter_id TEXT NOT NULL,
    xp INTEGER NOT NULL,
    loot_json TEXT NOT NULL,
    PRIMARY KEY (campaign_id, encounter_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_character_spells (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    spell_id TEXT NOT NULL,
    name TEXT NOT NULL,
    level INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, character_id, spell_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_character_prepared_spells (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    spell_ids_json TEXT NOT NULL,
    PRIMARY KEY (campaign_id, character_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_character_casts (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    spell_id TEXT NOT NULL,
    target TEXT NOT NULL,
    slot_level INTEGER NOT NULL,
    slots_remaining INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, character_id, sequence),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_character_concentration (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    spell_id TEXT NOT NULL,
    target TEXT NOT NULL,
    remaining_turns INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, character_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_character_inventory (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, character_id, item_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_character_equipment (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    slot TEXT NOT NULL,
    item_id TEXT NOT NULL,
    PRIMARY KEY (campaign_id, character_id, slot),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_character_attunements (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    slot TEXT NOT NULL,
    item_id TEXT NOT NULL,
    PRIMARY KEY (campaign_id, character_id, slot),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_character_currency (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    gold INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, character_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_currency_transfers (
    campaign_id TEXT NOT NULL,
    transfer_id INTEGER NOT NULL,
    from_character_id TEXT NOT NULL,
    to_character_id TEXT NOT NULL,
    gold INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, transfer_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_loot (
    campaign_id TEXT NOT NULL,
    loot_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    status TEXT NOT NULL,
    recipient_character_id TEXT,
    PRIMARY KEY (campaign_id, loot_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_loot_votes (
    campaign_id TEXT NOT NULL,
    loot_id TEXT NOT NULL,
    voter TEXT NOT NULL,
    recipient_character_id TEXT NOT NULL,
    PRIMARY KEY (campaign_id, loot_id, voter),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_npcs (
    campaign_id TEXT NOT NULL,
    npc_id TEXT NOT NULL,
    name TEXT NOT NULL,
    agenda TEXT NOT NULL,
    public_status TEXT NOT NULL,
    PRIMARY KEY (campaign_id, npc_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_factions (
    campaign_id TEXT NOT NULL,
    faction_id TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (campaign_id, faction_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_faction_reputation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    faction_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    delta INTEGER NOT NULL,
    reason TEXT NOT NULL,
    reputation INTEGER NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_npc_dialogue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    npc_id TEXT NOT NULL,
    dialogue_id TEXT NOT NULL,
    speaker TEXT NOT NULL,
    text TEXT NOT NULL,
    visibility TEXT NOT NULL,
    UNIQUE (campaign_id, npc_id, dialogue_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    score INTEGER NOT NULL,
    UNIQUE (campaign_id, source_id, target_id, kind),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_clues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    clue_id TEXT NOT NULL,
    text TEXT NOT NULL,
    audience TEXT NOT NULL,
    character_id TEXT,
    UNIQUE (campaign_id, clue_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_quests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    title TEXT NOT NULL,
    depends_on TEXT NOT NULL,
    state TEXT NOT NULL,
    UNIQUE (campaign_id, quest_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_quest_rewards (
    campaign_id TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    xp INTEGER NOT NULL,
    items_json TEXT NOT NULL,
    awarded INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (campaign_id, quest_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_character_quest_rewards (
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    xp INTEGER NOT NULL,
    items_json TEXT NOT NULL,
    PRIMARY KEY (campaign_id, character_id, quest_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_world_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    resolution_turn_number INTEGER,
    resolution_text TEXT,
    UNIQUE (campaign_id, event_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_calendar (
    campaign_id TEXT PRIMARY KEY,
    day INTEGER NOT NULL,
    season TEXT NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_settlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    settlement_id TEXT NOT NULL,
    name TEXT NOT NULL,
    services_json TEXT NOT NULL,
    availability TEXT NOT NULL,
    UNIQUE (campaign_id, settlement_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_settlement_discoveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    settlement_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    UNIQUE (campaign_id, settlement_id, character_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_shops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    settlement_id TEXT NOT NULL,
    shop_id TEXT NOT NULL,
    name TEXT NOT NULL,
    stock_json TEXT NOT NULL,
    buy_price INTEGER NOT NULL,
    sell_price INTEGER NOT NULL,
    UNIQUE (campaign_id, settlement_id, shop_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    recipe_id TEXT NOT NULL,
    name TEXT NOT NULL,
    ingredients_json TEXT NOT NULL,
    output_item TEXT NOT NULL,
    output_quantity INTEGER NOT NULL,
    UNIQUE (campaign_id, recipe_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_downtime_activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    activity_id TEXT NOT NULL,
    name TEXT NOT NULL,
    cycles_required INTEGER NOT NULL,
    UNIQUE (campaign_id, activity_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_downtime_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    activity_id TEXT NOT NULL,
    cycles_completed INTEGER NOT NULL DEFAULT 0,
    completions INTEGER NOT NULL DEFAULT 0,
    UNIQUE (campaign_id, character_id, activity_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_session_zero (
    campaign_id TEXT PRIMARY KEY,
    rules TEXT NOT NULL,
    tone TEXT NOT NULL,
    consent_json TEXT NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    content_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    UNIQUE (campaign_id, content_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    note_id TEXT NOT NULL,
    text TEXT NOT NULL,
    visibility TEXT NOT NULL,
    owner TEXT NOT NULL,
    UNIQUE (campaign_id, note_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_whispers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    whisper_id TEXT NOT NULL,
    from_character_id TEXT NOT NULL,
    to_character_id TEXT NOT NULL,
    text TEXT NOT NULL,
    UNIQUE (campaign_id, whisper_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_invitations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    invitation_id TEXT NOT NULL,
    username TEXT NOT NULL,
    character_id TEXT NOT NULL,
    status TEXT NOT NULL,
    UNIQUE (campaign_id, invitation_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_delegations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    username TEXT NOT NULL,
    powers TEXT NOT NULL,
    active INTEGER NOT NULL,
    UNIQUE (campaign_id, username),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_delegation_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    powers TEXT NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_audit_events (
    campaign_id TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    kind TEXT NOT NULL,
    actor TEXT NOT NULL,
    role TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    PRIMARY KEY (campaign_id, timestamp),
    UNIQUE (campaign_id, correlation_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);

CREATE TABLE IF NOT EXISTS play_projection_events (
    campaign_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY (campaign_id, sequence),
    UNIQUE (campaign_id, event_id),
    FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
);
"""

_DROP_SQL = """
DROP TABLE IF EXISTS play_projection_events;
DROP TABLE IF EXISTS play_audit_events;
DROP TABLE IF EXISTS play_delegation_audit;
DROP TABLE IF EXISTS play_delegations;
DROP TABLE IF EXISTS play_invitations;
DROP TABLE IF EXISTS play_whispers;
DROP TABLE IF EXISTS play_notes;
DROP TABLE IF EXISTS play_content;
DROP TABLE IF EXISTS play_session_zero;
DROP TABLE IF EXISTS play_downtime_allocations;
DROP TABLE IF EXISTS play_downtime_activities;
DROP TABLE IF EXISTS play_recipes;
DROP TABLE IF EXISTS play_shops;
DROP TABLE IF EXISTS play_settlement_discoveries;
DROP TABLE IF EXISTS play_settlements;
DROP TABLE IF EXISTS play_calendar;
DROP TABLE IF EXISTS play_character_quest_rewards;
DROP TABLE IF EXISTS play_quest_rewards;
DROP TABLE IF EXISTS play_quests;
DROP TABLE IF EXISTS play_clues;
DROP TABLE IF EXISTS play_relationships;
DROP TABLE IF EXISTS play_npc_dialogue;
DROP TABLE IF EXISTS play_faction_reputation;
DROP TABLE IF EXISTS play_factions;
DROP TABLE IF EXISTS play_npcs;
DROP TABLE IF EXISTS play_loot_votes;
DROP TABLE IF EXISTS play_loot;
DROP TABLE IF EXISTS play_currency_transfers;
DROP TABLE IF EXISTS play_character_currency;
DROP TABLE IF EXISTS play_character_attunements;
DROP TABLE IF EXISTS play_character_equipment;
DROP TABLE IF EXISTS play_character_inventory;
DROP TABLE IF EXISTS play_character_concentration;
DROP TABLE IF EXISTS play_character_casts;
DROP TABLE IF EXISTS play_character_prepared_spells;
DROP TABLE IF EXISTS play_character_spells;
DROP TABLE IF EXISTS play_encounter_rewards;
DROP TABLE IF EXISTS play_encounter_turn_order;
DROP TABLE IF EXISTS play_encounter_conditions;
DROP TABLE IF EXISTS play_encounter_combatants;
DROP TABLE IF EXISTS play_encounter_monsters;
DROP TABLE IF EXISTS play_encounters;
DROP TABLE IF EXISTS play_connections;
DROP TABLE IF EXISTS play_locations;
DROP TABLE IF EXISTS play_scenes;
DROP TABLE IF EXISTS play_events;
DROP TABLE IF EXISTS play_character_owners;
DROP TABLE IF EXISTS play_members;
DROP TABLE IF EXISTS play_campaigns;
DROP TABLE IF EXISTS session_attendance;
DROP TABLE IF EXISTS campaign_sessions;
DROP TABLE IF EXISTS crafting_projects;
DROP TABLE IF EXISTS character_equipment;
DROP TABLE IF EXISTS campaign_inventory;
DROP TABLE IF EXISTS npcs;
DROP TABLE IF EXISTS factions;
DROP TABLE IF EXISTS combat_sessions;
DROP TABLE IF EXISTS monsters;
DROP TABLE IF EXISTS items;
DROP TABLE IF EXISTS quests;
DROP TABLE IF EXISTS campaign_events;
DROP TABLE IF EXISTS campaign_characters;
DROP TABLE IF EXISTS campaigns;
"""


def get_db():
    """Open a fresh connection for the caller; caller is responsible for closing it."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_schema(conn):
    conn.executescript(_SCHEMA_SQL)
    conn.commit()


def init_db():
    conn = get_db()
    try:
        init_schema(conn)
    finally:
        conn.close()


def reset_db():
    conn = get_db()
    try:
        conn.executescript(_DROP_SQL)
        conn.commit()
        init_schema(conn)
    finally:
        conn.close()


def db_initialized():
    conn = get_db()
    try:
        placeholders = ",".join("?" for _ in _TABLE_NAMES)
        rows = conn.execute(
            f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({placeholders})",
            _TABLE_NAMES,
        ).fetchall()
        return len(rows) == len(_TABLE_NAMES)
    finally:
        conn.close()
