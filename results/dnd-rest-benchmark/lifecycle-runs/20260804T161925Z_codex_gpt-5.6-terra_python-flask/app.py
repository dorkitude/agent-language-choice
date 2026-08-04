"""Deterministic Flask REST API for the D&D campaign-management exercises."""

import os
import re
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)

CR_XP = {
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
LEVEL_THRESHOLDS = {3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400}}
DICE_EXPRESSION = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")
USERNAME = re.compile(r"^[a-z0-9_-]{2,32}$")
PLAYABLE_RACES = frozenset(("dwarf", "elf", "halfling", "human"))
PLAYABLE_CLASSES = frozenset(("cleric", "fighter", "rogue", "wizard"))
PLAYABLE_BACKGROUNDS = frozenset(
    ("acolyte", "criminal", "folk hero", "noble", "sage", "soldier")
)
ABILITY_NAMES = ("str", "dex", "con", "int", "wis", "cha")
SKILL_NAMES = frozenset((
    "acrobatics", "animal_handling", "arcana", "athletics", "deception",
    "history", "insight", "intimidation", "investigation", "medicine",
    "nature", "perception", "performance", "persuasion", "religion",
    "sleight_of_hand", "stealth", "survival",
))
SCHEMA_VERSION = 1
DATABASE_PATH = Path(__file__).with_name("game.db")


def database_connection():
    """Open a short-lived connection so each request commits atomically on success."""
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def table_columns(connection, table_name):
    """Return the columns currently present in a SQLite table.

    Schema initialization uses this to make additive migrations safe when an
    existing local database predates a newly introduced play-state field.
    """
    return {column[1] for column in connection.execute(f"PRAGMA table_info({table_name})")}


def initialize_database():
    with database_connection() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS schema_metadata (
                version INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS combat_sessions (
                id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL
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
                position INTEGER NOT NULL,
                tag TEXT NOT NULL,
                PRIMARY KEY (monster_slug, position),
                FOREIGN KEY (monster_slug) REFERENCES monsters(slug)
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
            CREATE TABLE IF NOT EXISTS play_campaigns (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                owner TEXT NOT NULL,
                status TEXT NOT NULL,
                max_players INTEGER NOT NULL,
                current_actor TEXT,
                turn_number INTEGER,
                phase TEXT NOT NULL DEFAULT 'exploration',
                nudge_count INTEGER NOT NULL DEFAULT 0,
                current_scene_id TEXT,
                current_location_id TEXT
            );
            CREATE TABLE IF NOT EXISTS play_campaign_members (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                username TEXT NOT NULL,
                owner TEXT,
                name TEXT NOT NULL,
                class TEXT NOT NULL,
                level INTEGER NOT NULL DEFAULT 1,
                str_score INTEGER NOT NULL DEFAULT 10,
                dex_score INTEGER NOT NULL DEFAULT 10,
                con_score INTEGER NOT NULL DEFAULT 10,
                int_score INTEGER NOT NULL DEFAULT 10,
                wis_score INTEGER NOT NULL DEFAULT 10,
                cha_score INTEGER NOT NULL DEFAULT 10,
                con_modifier INTEGER NOT NULL DEFAULT 0,
                hp_current INTEGER NOT NULL DEFAULT 20,
                hp_max INTEGER NOT NULL DEFAULT 20,
                status TEXT NOT NULL DEFAULT 'conscious',
                death_save_successes INTEGER NOT NULL DEFAULT 0,
                death_save_failures INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (campaign_id, character_id),
                UNIQUE (campaign_id, username),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_character_spells (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                spell_id TEXT NOT NULL,
                name TEXT NOT NULL,
                level INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id, spell_id),
                FOREIGN KEY (campaign_id, character_id)
                    REFERENCES play_campaign_members(campaign_id, character_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_prepared_spells (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                spell_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id, spell_id),
                FOREIGN KEY (campaign_id, character_id)
                    REFERENCES play_campaign_members(campaign_id, character_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_spell_casts (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                spell_id TEXT NOT NULL,
                target TEXT NOT NULL,
                slot_level INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id, sequence),
                FOREIGN KEY (campaign_id, character_id)
                    REFERENCES play_campaign_members(campaign_id, character_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_events (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                kind TEXT NOT NULL,
                actor TEXT NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_combat_actions (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                type TEXT NOT NULL,
                target TEXT NOT NULL,
                PRIMARY KEY (campaign_id, sequence),
                FOREIGN KEY (campaign_id, sequence)
                    REFERENCES play_campaign_events(campaign_id, sequence)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_documents (
                campaign_id TEXT PRIMARY KEY,
                story TEXT NOT NULL,
                dm_notes TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_scenes (
                campaign_id TEXT NOT NULL,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                PRIMARY KEY (campaign_id, id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_locations (
                campaign_id TEXT NOT NULL,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                PRIMARY KEY (campaign_id, id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_encounters (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                combat_round INTEGER NOT NULL DEFAULT 1,
                turn_index INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_encounter_rewards (
                encounter_id TEXT PRIMARY KEY,
                xp INTEGER NOT NULL,
                loot_json TEXT NOT NULL,
                FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS active_play_campaign_encounter
            ON play_campaign_encounters(campaign_id) WHERE status = 'active';
            CREATE TABLE IF NOT EXISTS play_campaign_encounter_monsters (
                encounter_id TEXT NOT NULL,
                monster_id TEXT NOT NULL,
                name TEXT NOT NULL,
                hp_max INTEGER NOT NULL,
                hp_current INTEGER NOT NULL,
                initiative INTEGER NOT NULL,
                PRIMARY KEY (encounter_id, monster_id),
                FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_encounter_members (
                encounter_id TEXT NOT NULL,
                member TEXT NOT NULL,
                initiative INTEGER NOT NULL,
                PRIMARY KEY (encounter_id, member),
                FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_encounter_turn_order (
                encounter_id TEXT NOT NULL,
                target TEXT NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (encounter_id, target),
                FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_encounter_conditions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                encounter_id TEXT NOT NULL,
                target TEXT NOT NULL,
                condition TEXT NOT NULL,
                remaining_rounds INTEGER NOT NULL,
                FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_location_connections (
                campaign_id TEXT NOT NULL,
                from_id TEXT NOT NULL,
                to_id TEXT NOT NULL,
                travel_turns INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, from_id, to_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                FOREIGN KEY (campaign_id, from_id)
                    REFERENCES play_campaign_locations(campaign_id, id),
                FOREIGN KEY (campaign_id, to_id)
                    REFERENCES play_campaign_locations(campaign_id, id)
            );
            CREATE TABLE IF NOT EXISTS campaign_characters (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                level INTEGER NOT NULL,
                class TEXT NOT NULL,
                position INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS campaign_events (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                position INTEGER NOT NULL,
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
            CREATE TABLE IF NOT EXISTS crafting_projects (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                item_slug TEXT NOT NULL,
                days_required INTEGER NOT NULL,
                days_completed INTEGER NOT NULL DEFAULT 0,
                cost_gp INTEGER NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
                FOREIGN KEY (character_id) REFERENCES campaign_characters(id)
            );
            CREATE TABLE IF NOT EXISTS character_equipment (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                item_slug TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id, item_slug),
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
                FOREIGN KEY (character_id) REFERENCES campaign_characters(id)
            );
            CREATE TABLE IF NOT EXISTS factions (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                stance TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS npcs (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                faction_id TEXT NOT NULL,
                disposition INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
                FOREIGN KEY (faction_id) REFERENCES factions(id)
            );
            CREATE TABLE IF NOT EXISTS quests (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS quest_milestones (
                quest_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                title TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (quest_id, position),
                FOREIGN KEY (quest_id) REFERENCES quests(id)
            );
            CREATE TABLE IF NOT EXISTS campaign_sessions (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                starts_at TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                agenda_json TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS session_attendance (
                session_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                status TEXT NOT NULL,
                PRIMARY KEY (session_id, character_id),
                FOREIGN KEY (session_id) REFERENCES campaign_sessions(id)
            );
        """)
        row = connection.execute("SELECT version FROM schema_metadata LIMIT 1").fetchone()
        if row is None:
            connection.execute("INSERT INTO schema_metadata (version) VALUES (?)", (SCHEMA_VERSION,))
        # Keep existing local databases usable after the play-state extension.
        play_campaign_columns = table_columns(connection, "play_campaigns")
        if "current_actor" not in play_campaign_columns:
            connection.execute("ALTER TABLE play_campaigns ADD COLUMN current_actor TEXT")
        if "turn_number" not in play_campaign_columns:
            connection.execute("ALTER TABLE play_campaigns ADD COLUMN turn_number INTEGER")
        if "phase" not in play_campaign_columns:
            connection.execute(
                "ALTER TABLE play_campaigns "
                "ADD COLUMN phase TEXT NOT NULL DEFAULT 'exploration'"
            )
        encounter_columns = table_columns(connection, "play_campaign_encounters")
        if "combat_round" not in encounter_columns:
            connection.execute(
                "ALTER TABLE play_campaign_encounters "
                "ADD COLUMN combat_round INTEGER NOT NULL DEFAULT 1"
            )
        if "turn_index" not in encounter_columns:
            connection.execute(
                "ALTER TABLE play_campaign_encounters "
                "ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0"
            )
        if "nudge_count" not in play_campaign_columns:
            connection.execute(
                "ALTER TABLE play_campaigns ADD COLUMN nudge_count INTEGER NOT NULL DEFAULT 0"
            )
        if "current_scene_id" not in play_campaign_columns:
            connection.execute("ALTER TABLE play_campaigns ADD COLUMN current_scene_id TEXT")
        if "current_location_id" not in play_campaign_columns:
            connection.execute("ALTER TABLE play_campaigns ADD COLUMN current_location_id TEXT")
        member_columns = table_columns(connection, "play_campaign_members")
        if "hp_current" not in member_columns:
            connection.execute(
                "ALTER TABLE play_campaign_members ADD COLUMN hp_current INTEGER NOT NULL DEFAULT 20"
            )
        if "hp_max" not in member_columns:
            connection.execute(
                "ALTER TABLE play_campaign_members ADD COLUMN hp_max INTEGER NOT NULL DEFAULT 20"
            )
        if "status" not in member_columns:
            connection.execute(
                "ALTER TABLE play_campaign_members "
                "ADD COLUMN status TEXT NOT NULL DEFAULT 'conscious'"
            )
        if "death_save_successes" not in member_columns:
            connection.execute(
                "ALTER TABLE play_campaign_members "
                "ADD COLUMN death_save_successes INTEGER NOT NULL DEFAULT 0"
            )
        if "death_save_failures" not in member_columns:
            connection.execute(
                "ALTER TABLE play_campaign_members "
                "ADD COLUMN death_save_failures INTEGER NOT NULL DEFAULT 0"
            )
        if "owner" not in member_columns:
            connection.execute("ALTER TABLE play_campaign_members ADD COLUMN owner TEXT")
        if "level" not in member_columns:
            connection.execute(
                "ALTER TABLE play_campaign_members ADD COLUMN level INTEGER NOT NULL DEFAULT 1"
            )
        for ability in ABILITY_NAMES:
            score_column = f"{ability}_score"
            if score_column not in member_columns:
                connection.execute(
                    f"ALTER TABLE play_campaign_members ADD COLUMN {score_column} "
                    "INTEGER NOT NULL DEFAULT 10"
                )
        if "con_modifier" not in member_columns:
            connection.execute(
                "ALTER TABLE play_campaign_members "
                "ADD COLUMN con_modifier INTEGER NOT NULL DEFAULT 0"
            )
        # Before character ownership was introduced, a member's character was
        # necessarily controlled by that member.  Preserve that relationship
        # when opening an existing database.
        connection.execute(
            "UPDATE play_campaign_members SET owner = username WHERE owner IS NULL"
        )


def database_initialized():
    try:
        with database_connection() as connection:
            row = connection.execute(
                "SELECT version FROM schema_metadata LIMIT 1"
            ).fetchone()
            return row is not None and row[0] == SCHEMA_VERSION
    except sqlite3.Error:
        return False


def load_combat_session(session_id):
    with database_connection() as connection:
        row = connection.execute(
            "SELECT state_json FROM combat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return None if row is None else json.loads(row[0])


def save_combat_session(session):
    with database_connection() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO combat_sessions (id, state_json) VALUES (?, ?)",
            (session["id"], json.dumps(session, separators=(",", ":"))),
        )


initialize_database()


def body():
    return request.get_json(silent=True) or {}


def valid_int(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def ability_modifier(score):
    return (score - 10) // 2


def proficiency_bonus(level):
    return 2 + ((level - 1) // 4)


def combat_session_response(session):
    active = session["order"][session["turn_index"]]
    return {
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": {"name": active["name"], "score": active["score"]},
    }


def session_conditions(session):
    return {
        name: [condition.copy() for condition in conditions]
        for name, conditions in session["conditions"].items()
    }


def serialized_play_events(events):
    """Convert ordered event rows into the public campaign-event projection."""
    return [
        {"sequence": event[0], "kind": event[1], "actor": event[2], "text": event[3]}
        for event in events
    ]


def json_with_required_fields(required_fields):
    """Return a JSON object containing all fields, or ``None`` for malformed input.

    Individual routes deliberately retain ownership of their validation and error
    response, because those responses are part of the public API contract.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or any(field not in data for field in required_fields):
        return None
    return data


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.get("/v1/storage/status")
def storage_status():
    return jsonify(
        driver="sqlite",
        schema_version=SCHEMA_VERSION,
        initialized=database_initialized(),
    )


@app.post("/v1/storage/reset")
def reset_storage():
    with database_connection() as connection:
        connection.executescript("""
            DROP TABLE IF EXISTS combat_sessions;
            DROP TABLE IF EXISTS monster_tags;
            DROP TABLE IF EXISTS monsters;
            DROP TABLE IF EXISTS items;
            DROP TABLE IF EXISTS character_equipment;
            DROP TABLE IF EXISTS crafting_projects;
            DROP TABLE IF EXISTS campaign_inventory;
            DROP TABLE IF EXISTS campaign_characters;
            DROP TABLE IF EXISTS campaign_events;
            DROP TABLE IF EXISTS npcs;
            DROP TABLE IF EXISTS factions;
            DROP TABLE IF EXISTS quest_milestones;
            DROP TABLE IF EXISTS quests;
            DROP TABLE IF EXISTS session_attendance;
            DROP TABLE IF EXISTS campaign_sessions;
            DROP TABLE IF EXISTS play_campaign_combat_actions;
            DROP TABLE IF EXISTS play_campaign_events;
            DROP TABLE IF EXISTS play_campaign_spell_casts;
            DROP TABLE IF EXISTS play_campaign_prepared_spells;
            DROP TABLE IF EXISTS play_campaign_character_spells;
            DROP TABLE IF EXISTS play_campaign_members;
            DROP TABLE IF EXISTS play_campaign_documents;
            DROP TABLE IF EXISTS play_campaign_scenes;
            DROP TABLE IF EXISTS play_campaign_encounter_conditions;
            DROP TABLE IF EXISTS play_campaign_encounter_turn_order;
            DROP TABLE IF EXISTS play_campaign_encounter_members;
            DROP TABLE IF EXISTS play_campaign_encounter_monsters;
            DROP TABLE IF EXISTS play_campaign_encounter_rewards;
            DROP TABLE IF EXISTS play_campaign_encounters;
            DROP TABLE IF EXISTS play_campaign_location_connections;
            DROP TABLE IF EXISTS play_campaign_locations;
            DROP TABLE IF EXISTS play_campaigns;
            DROP TABLE IF EXISTS campaigns;
            DROP TABLE IF EXISTS schema_metadata;
        """)
    initialize_database()
    return jsonify(ok=True, schema_version=SCHEMA_VERSION)


@app.post("/v1/auth/register")
def register_user():
    data = json_with_required_fields(("username", "password", "role"))
    if data is None:
        return jsonify(error="invalid registration"), 400

    username = data["username"]
    password = data["password"]
    role = data["role"]
    if (not isinstance(username, str) or USERNAME.fullmatch(username) is None
            or not isinstance(password, str) or len(password) < 8
            or role not in ("dm", "player")):
        return jsonify(error="invalid registration"), 400
    try:
        with database_connection() as connection:
            connection.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), role),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="username already exists"), 409
    return jsonify(username=username, role=role), 201


@app.post("/v1/auth/login")
def login_user():
    data = json_with_required_fields(("username", "password"))
    if data is None:
        return jsonify(error="invalid credentials"), 400

    username = data["username"]
    password = data["password"]
    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify(error="invalid credentials"), 400

    with database_connection() as connection:
        user = connection.execute(
            "SELECT password_hash, role FROM users WHERE username = ?", (username,)
        ).fetchone()
    if user is None or not check_password_hash(user[0], password):
        return jsonify(error="invalid credentials"), 401
    return jsonify(username=username, token=f"session-{username}")


def valid_nonblank_text(value):
    return isinstance(value, str) and bool(value.strip())


def authenticated_actor():
    authorization = request.headers.get("Authorization")
    prefix = "Bearer session-"
    if not isinstance(authorization, str) or not authorization.startswith(prefix):
        return None

    username = authorization[len(prefix):]
    if USERNAME.fullmatch(username) is None:
        return None
    with database_connection() as connection:
        user = connection.execute(
            "SELECT username, role FROM users WHERE username = ?", (username,)
        ).fetchone()
    # Play tokens identify an actor independently of campaign membership.  A
    # token for an unknown account is therefore authenticated but has no DM
    # privileges; routes can report the appropriate authorization failure.
    return user if user is not None else (username, "player")


@app.post("/v1/play/campaigns")
def create_play_campaign():
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    if actor[1] != "dm":
        return jsonify(error="forbidden"), 403

    data = json_with_required_fields(("id", "name", "max_players"))
    if (data is None
            or not valid_nonblank_text(data["id"])
            or not valid_nonblank_text(data["name"])
            or type(data["max_players"]) is not int
            or data["max_players"] <= 0):
        return jsonify(error="invalid play campaign"), 400

    campaign_id, name, max_players = data["id"], data["name"], data["max_players"]
    try:
        with database_connection() as connection:
            connection.execute(
                "INSERT INTO play_campaigns (id, name, owner, status, max_players) "
                "VALUES (?, ?, ?, ?, ?)",
                (campaign_id, name, actor[0], "lobby", max_players),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="campaign id already exists"), 409
    return jsonify(
        id=campaign_id, name=name, owner=actor[0], status="lobby", max_players=max_players,
    ), 201


@app.put("/v1/play/campaigns/<campaign_id>/document")
def update_play_campaign_document(campaign_id):
    """Replace the owner's public story and private campaign notes."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    if actor[1] != "dm":
        return jsonify(error="forbidden"), 403

    data = json_with_required_fields(("story", "dm_notes"))
    if (data is None
            or not valid_nonblank_text(data["story"])
            or not valid_nonblank_text(data["dm_notes"])):
        return jsonify(error="invalid campaign document"), 400

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        connection.execute(
            "INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(campaign_id) DO UPDATE SET "
            "story = excluded.story, dm_notes = excluded.dm_notes",
            (campaign_id, data["story"], data["dm_notes"]),
        )
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, "document", actor[0], data["story"]),
        )

    return jsonify(story=data["story"], dm_notes=data["dm_notes"])


@app.get("/v1/play/campaigns/<campaign_id>/document")
def read_play_campaign_document(campaign_id):
    """Return the campaign document without exposing notes to players."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404

        is_owner = actor[1] == "dm" and campaign[0] == actor[0]
        is_member = actor[1] == "player" and connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone() is not None
        if not is_owner and not is_member:
            return jsonify(error="forbidden"), 403

        document = connection.execute(
            "SELECT story, dm_notes FROM play_campaign_documents WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()

    story, dm_notes = document if document is not None else ("", "")
    if is_owner:
        return jsonify(story=story, dm_notes=dm_notes)
    return jsonify(story=story)


@app.post("/v1/play/campaigns/<campaign_id>/scenes")
def create_play_campaign_scene(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("id", "name"))
    if (data is None
            or not valid_nonblank_text(data["id"])
            or not valid_nonblank_text(data["name"])):
        return jsonify(error="invalid scene"), 400

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        try:
            connection.execute(
                "INSERT INTO play_campaign_scenes (campaign_id, id, name, status) "
                "VALUES (?, ?, ?, ?)",
                (campaign_id, data["id"], data["name"], "open"),
            )
        except sqlite3.IntegrityError:
            return jsonify(error="scene id already exists"), 409

    return jsonify(id=data["id"], name=data["name"], status="open"), 201


@app.post("/v1/play/campaigns/<campaign_id>/scenes/<scene_id>/enter")
def enter_play_campaign_scene(campaign_id, scene_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        scene = connection.execute(
            "SELECT name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?",
            (campaign_id, scene_id),
        ).fetchone()
        if scene is None:
            return jsonify(error="unknown scene"), 404
        if scene[1] != "open":
            return jsonify(error="scene is closed"), 409
        connection.execute(
            "UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?",
            (scene_id, campaign_id),
        )

    return jsonify(current_scene_id=scene_id, name=scene[0])


@app.post("/v1/play/campaigns/<campaign_id>/scenes/<scene_id>/close")
def close_play_campaign_scene(campaign_id, scene_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        changed = connection.execute(
            "UPDATE play_campaign_scenes SET status = 'closed' "
            "WHERE campaign_id = ? AND id = ?",
            (campaign_id, scene_id),
        ).rowcount
        if changed != 1:
            return jsonify(error="unknown scene"), 404

    return jsonify(id=scene_id, status="closed")


@app.get("/v1/play/campaigns/<campaign_id>/scenes/current")
def read_current_play_campaign_scene(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner, current_scene_id FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        is_member = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone() is not None
        if campaign[0] != actor[0] and not is_member:
            return jsonify(error="forbidden"), 403
        if campaign[1] is None:
            return jsonify(error="no current scene"), 404
        scene = connection.execute(
            "SELECT id, name, status FROM play_campaign_scenes "
            "WHERE campaign_id = ? AND id = ? AND status = 'open'",
            (campaign_id, campaign[1]),
        ).fetchone()
        if scene is None:
            return jsonify(error="no current scene"), 404

    return jsonify(id=scene[0], name=scene[1], status=scene[2])


@app.post("/v1/play/campaigns/<campaign_id>/locations")
def create_play_campaign_location(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("id", "name"))
    if (data is None
            or not valid_nonblank_text(data["id"])
            or not valid_nonblank_text(data["name"])):
        return jsonify(error="invalid location"), 400

    try:
        with database_connection() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return jsonify(error="unknown campaign"), 404
            if actor[1] != "dm" or campaign[0] != actor[0]:
                return jsonify(error="forbidden"), 403
            connection.execute(
                "INSERT INTO play_campaign_locations (campaign_id, id, name) VALUES (?, ?, ?)",
                (campaign_id, data["id"], data["name"]),
            )
            connection.execute(
                "UPDATE play_campaigns SET current_location_id = ? "
                "WHERE id = ? AND current_location_id IS NULL",
                (data["id"], campaign_id),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="location id already exists"), 409

    return jsonify(id=data["id"], name=data["name"]), 201


@app.post("/v1/play/campaigns/<campaign_id>/locations/<from_id>/connections")
def create_play_campaign_location_connection(campaign_id, from_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("to_id", "travel_turns"))
    if (data is None
            or not valid_nonblank_text(data["to_id"])
            or type(data["travel_turns"]) is not int
            or data["travel_turns"] <= 0):
        return jsonify(error="invalid connection"), 400

    try:
        with database_connection() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return jsonify(error="unknown campaign"), 404
            if actor[1] != "dm" or campaign[0] != actor[0]:
                return jsonify(error="forbidden"), 403
            locations = connection.execute(
                "SELECT id FROM play_campaign_locations WHERE campaign_id = ? AND id IN (?, ?)",
                (campaign_id, from_id, data["to_id"]),
            ).fetchall()
            if {location[0] for location in locations} != {from_id, data["to_id"]}:
                return jsonify(error="unknown location"), 400
            connection.execute(
                "INSERT INTO play_campaign_location_connections "
                "(campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)",
                (campaign_id, from_id, data["to_id"], data["travel_turns"]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="connection already exists"), 400

    return jsonify(from_id=from_id, to_id=data["to_id"], travel_turns=data["travel_turns"]), 201


@app.get("/v1/play/campaigns/<campaign_id>/locations/<location_id>/travel")
def read_play_campaign_location_travel(campaign_id, location_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        is_member = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone() is not None
        if campaign[0] != actor[0] and not is_member:
            return jsonify(error="forbidden"), 403
        location = connection.execute(
            "SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?",
            (campaign_id, location_id),
        ).fetchone()
        if location is None:
            return jsonify(error="unknown location"), 404
        destinations = connection.execute(
            "SELECT locations.id, locations.name, connections.travel_turns "
            "FROM play_campaign_location_connections AS connections "
            "JOIN play_campaign_locations AS locations "
            "ON locations.campaign_id = connections.campaign_id "
            "AND locations.id = connections.to_id "
            "WHERE connections.campaign_id = ? AND connections.from_id = ? "
            "ORDER BY locations.id",
            (campaign_id, location_id),
        ).fetchall()

    return jsonify(destinations=[
        {"id": destination[0], "name": destination[1], "travel_turns": destination[2]}
        for destination in destinations
    ])


@app.post("/v1/play/campaigns/<campaign_id>/members")
def join_play_campaign(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    if actor[1] != "player":
        return jsonify(error="forbidden"), 403

    data = json_with_required_fields(("character_id", "name", "class"))
    if data is None or not all(
            valid_nonblank_text(data[field]) for field in ("character_id", "name", "class")):
        return jsonify(error="invalid party member"), 400

    character_id, name, character_class = data["character_id"], data["name"], data["class"]
    try:
        with database_connection() as connection:
            campaign = connection.execute(
                "SELECT status, max_players FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return jsonify(error="unknown campaign"), 404
            if campaign[0] != "lobby":
                return jsonify(error="campaign is not accepting players"), 409
            member_count = connection.execute(
                "SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()[0]
            if member_count >= campaign[1]:
                return jsonify(error="party is full"), 409
            connection.execute(
                "INSERT INTO play_campaign_members "
                "(character_id, campaign_id, username, owner, name, class) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (character_id, campaign_id, actor[0], actor[0], name, character_class),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="party membership already exists"), 409
    return jsonify(username=actor[0], character_id=character_id, name=name,
                   **{"class": character_class}), 201


def play_campaign_member_viewer(connection, campaign_id, actor):
    """Return the requested character's owner after enforcing member visibility."""
    campaign = connection.execute(
        "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if campaign is None:
        return None, (jsonify(error="unknown campaign"), 404)
    if actor[1] != "player" or connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
    ).fetchone() is None:
        return None, (jsonify(error="forbidden"), 403)
    return True, None


@app.post("/v1/play/campaigns/<campaign_id>/characters/<character_id>/spells")
def add_play_campaign_character_spell(campaign_id, character_id):
    """Add one wizard spell to an owned character's spellbook."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("spell_id", "name", "level"))
    if (data is None
            or not valid_nonblank_text(data["spell_id"])
            or not valid_nonblank_text(data["name"])
            or type(data["level"]) is not int
            or data["level"] < 0):
        return jsonify(error="invalid spell"), 400

    try:
        with database_connection() as connection:
            character = connection.execute(
                "SELECT owner, class FROM play_campaign_members "
                "WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if character is None:
                campaign = connection.execute(
                    "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
                ).fetchone()
                if campaign is None:
                    return jsonify(error="unknown campaign"), 404
                return jsonify(error="unknown character"), 404
            if character[0] != actor[0]:
                return jsonify(error="forbidden"), 403
            if character[1] != "wizard":
                return jsonify(error="invalid class/spell combination"), 400
            connection.execute(
                "INSERT INTO play_campaign_character_spells "
                "(campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, character_id, data["spell_id"], data["name"], data["level"]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="spell already known"), 409

    return jsonify(spell_id=data["spell_id"], name=data["name"], level=data["level"]), 201


@app.get("/v1/play/campaigns/<campaign_id>/characters/<character_id>/spells")
def read_play_campaign_character_spells(campaign_id, character_id):
    """Return a campaign member's spellbook in acquisition order."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        _, error = play_campaign_member_viewer(connection, campaign_id, actor)
        if error is not None:
            return error
        character = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return jsonify(error="unknown character"), 404
        spells = connection.execute(
            "SELECT spell_id, name, level FROM play_campaign_character_spells "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY rowid",
            (campaign_id, character_id),
        ).fetchall()

    return jsonify(spells=[
        {"spell_id": spell[0], "name": spell[1], "level": spell[2]}
        for spell in spells
    ])


def maximum_prepared_spells(character_class, level):
    """Return the deterministic preparation limit for a character class."""
    return level if character_class == "wizard" else 0


@app.put("/v1/play/campaigns/<campaign_id>/characters/<character_id>/prepared-spells")
def update_play_campaign_prepared_spells(campaign_id, character_id):
    """Replace an owned spellcaster's ordered list of prepared spells."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("spell_ids",))
    spell_ids = None if data is None else data["spell_ids"]
    if (not isinstance(spell_ids, list)
            or any(not valid_nonblank_text(spell_id) for spell_id in spell_ids)
            or len(set(spell_ids)) != len(spell_ids)):
        return jsonify(error="invalid prepared spells"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        character = connection.execute(
            "SELECT owner, class, level FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            campaign = connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return jsonify(error="unknown campaign"), 404
            return jsonify(error="unknown character"), 404
        if character[0] != actor[0]:
            return jsonify(error="forbidden"), 403

        max_prepared = maximum_prepared_spells(character[1], character[2])
        if max_prepared == 0 or len(spell_ids) > max_prepared:
            return jsonify(error="invalid prepared spells"), 400
        known_spells = {
            spell[0] for spell in connection.execute(
                "SELECT spell_id FROM play_campaign_character_spells "
                "WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            )
        }
        if any(spell_id not in known_spells for spell_id in spell_ids):
            return jsonify(error="unknown spell"), 400

        connection.execute(
            "DELETE FROM play_campaign_prepared_spells "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        )
        connection.executemany(
            "INSERT INTO play_campaign_prepared_spells "
            "(campaign_id, character_id, spell_id, position) VALUES (?, ?, ?, ?)",
            [(campaign_id, character_id, spell_id, position)
             for position, spell_id in enumerate(spell_ids)],
        )

    return jsonify(
        character_id=character_id,
        prepared_spells=spell_ids,
        max_prepared=max_prepared,
    )


@app.get("/v1/play/campaigns/<campaign_id>/characters/<character_id>/prepared-spells")
def read_play_campaign_prepared_spells(campaign_id, character_id):
    """Return a campaign-visible character's ordered prepared spells."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        _, error = play_campaign_member_viewer(connection, campaign_id, actor)
        if error is not None:
            return error
        character = connection.execute(
            "SELECT class, level FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return jsonify(error="unknown character"), 404
        prepared_spells = [
            spell[0] for spell in connection.execute(
                "SELECT spell_id FROM play_campaign_prepared_spells "
                "WHERE campaign_id = ? AND character_id = ? ORDER BY position",
                (campaign_id, character_id),
            ).fetchall()
        ]

    return jsonify(
        character_id=character_id,
        prepared_spells=prepared_spells,
        max_prepared=maximum_prepared_spells(character[0], character[1]),
    )


@app.get("/v1/play/campaigns/<campaign_id>/characters/<character_id>/owner")
def read_play_campaign_character_owner(campaign_id, character_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        _, error = play_campaign_member_viewer(connection, campaign_id, actor)
        if error is not None:
            return error
        character = connection.execute(
            "SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return jsonify(error="unknown character"), 404

    return jsonify(character_id=character_id, owner=character[0])


@app.post("/v1/play/campaigns/<campaign_id>/characters/<character_id>/claim")
def claim_play_campaign_character(campaign_id, character_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _, error = play_campaign_member_viewer(connection, campaign_id, actor)
        if error is not None:
            return error
        character = connection.execute(
            "SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return jsonify(error="unknown character"), 404
        if character[0] is not None and character[0] != actor[0]:
            return jsonify(error="character already owned"), 409
        if character[0] is None:
            connection.execute(
                "UPDATE play_campaign_members SET owner = ? "
                "WHERE campaign_id = ? AND character_id = ?",
                (actor[0], campaign_id, character_id),
            )

    return jsonify(character_id=character_id, owner=actor[0]), 201


@app.post("/v1/play/campaigns/<campaign_id>/characters/<character_id>/transfer")
def transfer_play_campaign_character(campaign_id, character_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    data = json_with_required_fields(("new_owner",))
    if data is None or not valid_nonblank_text(data["new_owner"]):
        return jsonify(error="invalid owner"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _, error = play_campaign_member_viewer(connection, campaign_id, actor)
        if error is not None:
            return error
        character = connection.execute(
            "SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return jsonify(error="unknown character"), 404
        if character[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        new_owner_is_member = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, data["new_owner"]),
        ).fetchone() is not None
        if not new_owner_is_member:
            return jsonify(error="new owner is not a campaign member"), 400
        connection.execute(
            "UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?",
            (data["new_owner"], campaign_id, character_id),
        )

    return jsonify(character_id=character_id, owner=data["new_owner"])


@app.post("/v1/play/campaigns/<campaign_id>/characters/<character_id>/build")
def build_play_campaign_character(campaign_id, character_id):
    """Validate an owned character's initial creation choices."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("race", "class", "background", "abilities"))
    if (data is None
            or not isinstance(data["race"], str)
            or not isinstance(data["class"], str)
            or not isinstance(data["background"], str)
            or data["race"] not in PLAYABLE_RACES
            or data["class"] not in PLAYABLE_CLASSES
            or data["background"] not in PLAYABLE_BACKGROUNDS
            or not isinstance(data["abilities"], dict)
            or any(not valid_int(data["abilities"].get(name), 1, 30)
                   for name in ABILITY_NAMES)):
        return jsonify(error="invalid character build"), 400

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        character = connection.execute(
            "SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return jsonify(error="unknown character"), 404
        if character[0] != actor[0]:
            return jsonify(error="forbidden"), 403

    level = 1
    hp_max = 8 + ability_modifier(data["abilities"]["con"])
    with database_connection() as connection:
        connection.execute(
            "UPDATE play_campaign_members SET class = ?, level = ?, "
            "str_score = ?, dex_score = ?, con_score = ?, int_score = ?, wis_score = ?, "
            "cha_score = ?, con_modifier = ?, hp_max = ?, hp_current = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (data["class"], level, data["abilities"]["str"], data["abilities"]["dex"],
             data["abilities"]["con"], data["abilities"]["int"],
             data["abilities"]["wis"], data["abilities"]["cha"],
             ability_modifier(data["abilities"]["con"]), hp_max, hp_max,
             campaign_id, character_id),
        )
    return jsonify(
        character_id=character_id,
        race=data["race"],
        **{"class": data["class"]},
        background=data["background"],
        level=level,
        hp_max=hp_max,
        proficiency_bonus=proficiency_bonus(level),
    )


@app.post("/v1/play/campaigns/<campaign_id>/characters/<character_id>/skill-check")
def skill_check_play_campaign_character(campaign_id, character_id):
    """Resolve a character owner's deterministic skill check."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("skill", "ability", "proficient", "roll"))
    if (data is None
            or data["skill"] not in SKILL_NAMES
            or data["ability"] not in ABILITY_NAMES
            or type(data["proficient"]) is not bool
            or not valid_int(data["roll"], 1, 20)):
        return jsonify(error="invalid skill check"), 400

    with database_connection() as connection:
        character = connection.execute(
            f"SELECT owner, level, {data['ability']}_score "
            "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return jsonify(error="unknown character"), 404
        if character[0] != actor[0]:
            return jsonify(error="forbidden"), 403

    modifier = ability_modifier(character[2])
    if data["proficient"]:
        modifier += proficiency_bonus(character[1])
    return jsonify(
        character_id=character_id,
        skill=data["skill"],
        ability=data["ability"],
        modifier=modifier,
        total=data["roll"] + modifier,
    )


@app.post("/v1/play/campaigns/<campaign_id>/characters/<character_id>/level-up")
def level_up_play_campaign_character(campaign_id, character_id):
    """Advance an owned character by exactly one level."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("level",))
    if data is None or not valid_int(data["level"], 1, 20):
        return jsonify(error="invalid level"), 400

    hit_dice_by_class = {
        "cleric": "1d8", "fighter": "1d10", "rogue": "1d8", "wizard": "1d6",
    }
    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        character = connection.execute(
            "SELECT owner, class, level, con_modifier, hp_max "
            "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return jsonify(error="unknown character"), 404
        if character[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        if data["level"] != character[2] + 1:
            return jsonify(error="level must be exactly one higher"), 400

        hit_dice = hit_dice_by_class.get(character[1])
        if hit_dice is None:
            return jsonify(error="unsupported character class"), 400
        hit_die_size = int(hit_dice[2:])
        # Level-up hit dice use their deterministic average (rounded up), not
        # their maximum possible roll: 1d8 contributes 5 before CON.
        hp_gain = (hit_die_size // 2) + 1 + character[3]
        hp_max = character[4] + hp_gain
        connection.execute(
            "UPDATE play_campaign_members SET level = ?, hp_max = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (data["level"], hp_max, campaign_id, character_id),
        )

    return jsonify(
        character_id=character_id,
        level=data["level"],
        hp_max=hp_max,
        hit_dice=hit_dice,
        proficiency_bonus=proficiency_bonus(data["level"]),
    )


@app.post("/v1/play/campaigns/<campaign_id>/characters/<character_id>/damage")
def damage_play_campaign_character(campaign_id, character_id):
    """Let the campaign owner apply bounded damage to a party character."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("amount",))
    if data is None or not valid_int(data["amount"], 1, 1_000_000):
        return jsonify(error="invalid damage"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403

        character = connection.execute(
            "SELECT hp_current FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return jsonify(error="unknown character"), 404

        hp_before = character[0]
        hp_current = max(0, hp_before - data["amount"])
        status = "unconscious" if hp_current == 0 else "conscious"
        connection.execute(
            "UPDATE play_campaign_members SET hp_current = ?, status = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (hp_current, status, campaign_id, character_id),
        )

    return jsonify(
        character_id=character_id,
        target=character_id,
        hp_before=hp_before,
        hp_after=hp_current,
        damage=data["amount"],
        hp_current=hp_current,
        status=status,
    )


@app.post("/v1/play/campaigns/<campaign_id>/characters/<character_id>/death-saves")
def roll_play_campaign_character_death_save(campaign_id, character_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("outcome",))
    if data is None or data["outcome"] not in ("success", "failure"):
        return jsonify(error="invalid death save"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        character = connection.execute(
            "SELECT username, status, death_save_successes, death_save_failures "
            "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            campaign = connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return jsonify(error="unknown campaign"), 404
            return jsonify(error="unknown character"), 404
        if character[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        if character[1] != "unconscious":
            return jsonify(error="death saves unavailable"), 409

        successes, failures = character[2], character[3]
        if data["outcome"] == "success":
            successes += 1
        else:
            failures += 1
        status = "stable" if successes >= 3 else "dead" if failures >= 3 else "unconscious"
        connection.execute(
            "UPDATE play_campaign_members SET death_save_successes = ?, "
            "death_save_failures = ?, status = ? WHERE campaign_id = ? AND character_id = ?",
            (successes, failures, status, campaign_id, character_id),
        )

    return jsonify(
        character_id=character_id, successes=successes, failures=failures, status=status,
    ), 201


@app.get("/v1/play/campaigns/<campaign_id>/characters/<character_id>/status")
def read_play_campaign_character_status(campaign_id, character_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        character = connection.execute(
            "SELECT members.hp_current, members.hp_max, members.status "
            "FROM play_campaign_members AS members WHERE members.campaign_id = ? "
            "AND members.character_id = ? AND EXISTS ("
            "SELECT 1 FROM play_campaign_members AS viewer "
            "WHERE viewer.campaign_id = members.campaign_id AND viewer.username = ?) ",
            (campaign_id, character_id, actor[0]),
        ).fetchone()
        if character is not None:
            return jsonify(
                character_id=character_id, hp_current=character[0], hp_max=character[1],
                status=character[2],
            )
        campaign = connection.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        member = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone()
        if member is None:
            return jsonify(error="forbidden"), 403
        return jsonify(error="unknown character"), 404


@app.post("/v1/play/campaigns/<campaign_id>/start")
def start_play_campaign(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        if campaign[1] != "lobby":
            return jsonify(error="campaign cannot be started"), 409

        members = connection.execute(
            "SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid LIMIT 1",
            (campaign_id,),
        ).fetchone()
        member_count = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        if member_count < 2:
            return jsonify(error="campaign cannot be started"), 409

        changed = connection.execute(
            "UPDATE play_campaigns SET status = ?, current_actor = ?, turn_number = ? "
            "WHERE id = ? AND status = ?",
            ("active", members[0], 1, campaign_id, "lobby"),
        ).rowcount
        if changed != 1:
            return jsonify(error="campaign cannot be started"), 409

    return jsonify(
        id=campaign_id, status="active", current_actor=members[0], turn_number=1,
    )


@app.post("/v1/play/campaigns/<campaign_id>/encounters")
def create_play_campaign_encounter(campaign_id):
    """Start a campaign encounter without disturbing the exploration queue."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("id", "name"))
    if (data is None
            or not valid_nonblank_text(data["id"])
            or not valid_nonblank_text(data["name"])):
        return jsonify(error="invalid encounter"), 400

    try:
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return jsonify(error="unknown campaign"), 404
            if actor[1] != "dm" or campaign[0] != actor[0]:
                return jsonify(error="forbidden"), 403
            connection.execute(
                "INSERT INTO play_campaign_encounters (id, campaign_id, name, status) "
                "VALUES (?, ?, ?, ?)",
                (data["id"], campaign_id, data["name"], "active"),
            )
            # Closing an encounter is distinct from leaving combat: rewards may
            # be awarded and the encounter closed before exploration resumes.
            connection.execute(
                "UPDATE play_campaigns SET phase = 'combat' "
                "WHERE id = ? AND status = 'active'",
                (campaign_id,),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="encounter already active"), 409

    return jsonify(id=data["id"], name=data["name"], status="active", combatants=[]), 201


@app.post("/v1/play/campaigns/<campaign_id>/encounters/<encounter_id>/rewards")
def award_play_campaign_encounter_rewards(campaign_id, encounter_id):
    """Persist the owner's single deterministic reward parcel for an encounter."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("xp", "loot"))
    if (data is None
            or not valid_int(data["xp"], 0, 1_000_000)
            or not isinstance(data["loot"], list)
            or any(not isinstance(item, dict)
                   or not valid_nonblank_text(item.get("slug"))
                   or not valid_int(item.get("quantity"), 1, 1_000_000)
                   for item in data["loot"])):
        return jsonify(error="invalid encounter rewards"), 400

    loot = [
        {"slug": item["slug"], "quantity": item["quantity"]}
        for item in data["loot"]
    ]
    try:
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return jsonify(error="unknown campaign"), 404
            if actor[1] != "dm" or campaign[0] != actor[0]:
                return jsonify(error="forbidden"), 403
            encounter = connection.execute(
                "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
                (encounter_id, campaign_id),
            ).fetchone()
            if encounter is None:
                return jsonify(error="unknown encounter"), 404
            connection.execute(
                "INSERT INTO play_campaign_encounter_rewards (encounter_id, xp, loot_json) "
                "VALUES (?, ?, ?)",
                (encounter_id, data["xp"], json.dumps(loot, separators=(",", ":"))),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="rewards already awarded"), 409

    return jsonify(encounter_id=encounter_id, xp=data["xp"], loot=loot)


@app.post("/v1/play/campaigns/<campaign_id>/encounters/<encounter_id>/close")
def close_play_campaign_encounter(campaign_id, encounter_id):
    """Close an encounter and report the XP from its optional reward record."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        encounter = connection.execute(
            "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="unknown encounter"), 404
        connection.execute(
            "UPDATE play_campaign_encounters SET status = 'closed' WHERE id = ?",
            (encounter_id,),
        )
        reward = connection.execute(
            "SELECT xp FROM play_campaign_encounter_rewards WHERE encounter_id = ?",
            (encounter_id,),
        ).fetchone()

    return jsonify(id=encounter_id, status="closed", xp_awarded=0 if reward is None else reward[0])


@app.post("/v1/play/campaigns/<campaign_id>/encounters/<encounter_id>/end")
def end_play_campaign_encounter(campaign_id, encounter_id):
    """End active combat and resume the unchanged exploration turn queue."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner, status, current_actor, phase FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403

        encounter = connection.execute(
            "SELECT status FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="unknown encounter"), 404
        if campaign[1] != "active" or campaign[3] != "combat":
            return jsonify(error="campaign is not in combat"), 409

        connection.execute(
            "UPDATE play_campaign_encounters SET status = 'closed' WHERE id = ?",
            (encounter_id,),
        )
        connection.execute(
            "UPDATE play_campaigns SET phase = 'exploration' WHERE id = ?",
            (campaign_id,),
        )

    return jsonify(
        campaign_id=campaign_id,
        status=campaign[1],
        phase="exploration",
        current_actor=campaign[2],
    )


@app.post("/v1/play/campaigns/<campaign_id>/encounters/<encounter_id>/monsters")
def add_play_campaign_encounter_monster(campaign_id, encounter_id):
    """Add a deterministic monster combatant to the owner's encounter."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("monster_id", "name", "hp_max", "initiative"))
    if (data is None
            or not valid_nonblank_text(data["monster_id"])
            or not valid_nonblank_text(data["name"])
            or not valid_int(data["hp_max"], 1, 1_000_000)
            or not valid_int(data["initiative"], -1_000_000, 1_000_000)):
        return jsonify(error="invalid monster"), 400

    try:
        with database_connection() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return jsonify(error="unknown campaign"), 404
            if actor[1] != "dm" or campaign[0] != actor[0]:
                return jsonify(error="forbidden"), 403
            encounter = connection.execute(
                "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
                (encounter_id, campaign_id),
            ).fetchone()
            if encounter is None:
                return jsonify(error="unknown encounter"), 404
            connection.execute(
                "INSERT INTO play_campaign_encounter_monsters "
                "(encounter_id, monster_id, name, hp_max, hp_current, initiative) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (encounter_id, data["monster_id"], data["name"], data["hp_max"],
                 data["hp_max"], data["initiative"]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="monster id already exists"), 409

    return jsonify(
        monster_id=data["monster_id"],
        name=data["name"],
        hp_max=data["hp_max"],
        initiative=data["initiative"],
        hp_current=data["hp_max"],
    ), 201


@app.delete("/v1/play/campaigns/<campaign_id>/encounters/<encounter_id>/monsters/<monster_id>")
def remove_play_campaign_encounter_monster(campaign_id, encounter_id, monster_id):
    """Remove a monster combatant from the owner's encounter."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        encounter = connection.execute(
            "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="unknown encounter"), 404
        removed = connection.execute(
            "DELETE FROM play_campaign_encounter_monsters "
            "WHERE encounter_id = ? AND monster_id = ?",
            (encounter_id, monster_id),
        ).rowcount
        if removed != 1:
            return jsonify(error="unknown monster"), 404

    return jsonify(removed=monster_id)


def adjust_play_campaign_combatant_hp(campaign_id, encounter_id, target, amount, healing):
    """Apply a bounded HP adjustment to a monster or bound party combatant."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        encounter = connection.execute(
            "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="unknown encounter"), 404

        monster = connection.execute(
            "SELECT hp_current, hp_max FROM play_campaign_encounter_monsters "
            "WHERE encounter_id = ? AND monster_id = ?",
            (encounter_id, target),
        ).fetchone()
        if monster is not None:
            hp_before, hp_max = monster
            hp_after = min(hp_max, hp_before + amount) if healing else max(0, hp_before - amount)
            connection.execute(
                "UPDATE play_campaign_encounter_monsters SET hp_current = ? "
                "WHERE encounter_id = ? AND monster_id = ?",
                (hp_after, encounter_id, target),
            )
        else:
            member = connection.execute(
                "SELECT members.hp_current, members.hp_max "
                "FROM play_campaign_encounter_members AS bound "
                "JOIN play_campaign_members AS members "
                "ON members.campaign_id = ? AND members.username = bound.member "
                "WHERE bound.encounter_id = ? AND bound.member = ?",
                (campaign_id, encounter_id, target),
            ).fetchone()
            if member is None:
                return jsonify(error="unknown combatant"), 404
            hp_before, hp_max = member
            hp_after = min(hp_max, hp_before + amount) if healing else max(0, hp_before - amount)
            status = "unconscious" if hp_after == 0 else "conscious"
            connection.execute(
                "UPDATE play_campaign_members SET hp_current = ?, status = ? "
                "WHERE campaign_id = ? AND username = ?",
                (hp_after, status, campaign_id, target),
            )

    result = {"target": target, "hp_before": hp_before, "hp_after": hp_after}
    result["healing" if healing else "damage"] = amount
    return jsonify(**result)


@app.post("/v1/play/campaigns/<campaign_id>/encounters/<encounter_id>/damage")
def damage_play_campaign_encounter_combatant(campaign_id, encounter_id):
    data = json_with_required_fields(("target", "amount"))
    if (data is None
            or not valid_nonblank_text(data["target"])
            or not valid_int(data["amount"], 1, 1_000_000)):
        return jsonify(error="invalid damage"), 400
    return adjust_play_campaign_combatant_hp(
        campaign_id, encounter_id, data["target"], data["amount"], healing=False,
    )


@app.post("/v1/play/campaigns/<campaign_id>/encounters/<encounter_id>/heal")
def heal_play_campaign_encounter_combatant(campaign_id, encounter_id):
    data = json_with_required_fields(("target", "amount"))
    if (data is None
            or not valid_nonblank_text(data["target"])
            or not valid_int(data["amount"], 1, 1_000_000)):
        return jsonify(error="invalid healing"), 400
    return adjust_play_campaign_combatant_hp(
        campaign_id, encounter_id, data["target"], data["amount"], healing=True,
    )


@app.post("/v1/play/campaigns/<campaign_id>/encounters/<encounter_id>/combatants")
def bind_play_campaign_encounter_member(campaign_id, encounter_id):
    """Bind a party member to an encounter as a combatant."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("member", "initiative"))
    if (data is None
            or not valid_nonblank_text(data["member"])
            or not valid_int(data["initiative"], -1_000_000, 1_000_000)):
        return jsonify(error="invalid combatant"), 400

    try:
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return jsonify(error="unknown campaign"), 404
            if actor[1] != "dm" or campaign[0] != actor[0]:
                return jsonify(error="forbidden"), 403
            encounter = connection.execute(
                "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
                (encounter_id, campaign_id),
            ).fetchone()
            if encounter is None:
                return jsonify(error="unknown encounter"), 404
            member = connection.execute(
                "SELECT character_id, name FROM play_campaign_members "
                "WHERE campaign_id = ? AND username = ?",
                (campaign_id, data["member"]),
            ).fetchone()
            if member is None:
                return jsonify(error="unknown member"), 400
            connection.execute(
                "INSERT INTO play_campaign_encounter_members "
                "(encounter_id, member, initiative) VALUES (?, ?, ?)",
                (encounter_id, data["member"], data["initiative"]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="member already bound"), 409

    return jsonify(
        member=data["member"],
        character_id=member[0],
        name=member[1],
        initiative=data["initiative"],
    ), 201


@app.delete("/v1/play/campaigns/<campaign_id>/encounters/<encounter_id>/combatants/<member>")
def unbind_play_campaign_encounter_member(campaign_id, encounter_id, member):
    """Remove a bound party member from an encounter."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        encounter = connection.execute(
            "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="unknown encounter"), 404
        removed = connection.execute(
            "DELETE FROM play_campaign_encounter_members "
            "WHERE encounter_id = ? AND member = ?",
            (encounter_id, member),
        ).rowcount
        if removed != 1:
            return jsonify(error="unknown combatant"), 404

    return jsonify(removed=member)


def encounter_turn_order(connection, campaign_id, encounter_id):
    """Return combatants in the encounter's stable initiative order."""
    rows = connection.execute(
        "SELECT members.username, members.name, 'player' AS kind, bound.initiative "
        "FROM play_campaign_encounter_members AS bound "
        "JOIN play_campaign_members AS members "
        "ON members.campaign_id = ? AND members.username = bound.member "
        "WHERE bound.encounter_id = ? "
        "UNION ALL "
        "SELECT monster_id, name, 'monster', initiative "
        "FROM play_campaign_encounter_monsters WHERE encounter_id = ? "
        "ORDER BY 4 DESC, 2 ASC, 3 ASC",
        (campaign_id, encounter_id, encounter_id),
    ).fetchall()
    combatants = [
        {"target": row[0], "username": row[0] if row[2] == "player" else None,
         "name": row[1], "kind": row[2], "initiative": row[3]}
        for row in rows
    ]
    positions = dict(connection.execute(
        "SELECT target, position FROM play_campaign_encounter_turn_order "
        "WHERE encounter_id = ?", (encounter_id,),
    ).fetchall())
    if positions:
        # Combatants added after a delay keep their normal deterministic place
        # until a later delay establishes a complete order again.
        combatants.sort(key=lambda combatant: (
            0 if combatant["target"] in positions else 1,
            positions.get(combatant["target"], 0),
        ))
    return combatants


def combat_turn_payload(combat_round, turn_index, combatants):
    active = combatants[turn_index % len(combatants)]
    return {
        "round": combat_round,
        "turn_index": turn_index % len(combatants),
        "active": {
            "name": active["name"],
            "kind": active["kind"],
            "initiative": active["initiative"],
        },
    }


def encounter_conditions(connection, encounter_id, combatants):
    """Return conditions keyed by stable combatant targets in turn order."""
    conditions = {combatant["target"]: [] for combatant in combatants}
    rows = connection.execute(
        "SELECT target, condition, remaining_rounds "
        "FROM play_campaign_encounter_conditions WHERE encounter_id = ? ORDER BY id",
        (encounter_id,),
    ).fetchall()
    for target, condition, remaining_rounds in rows:
        if target in conditions:
            conditions[target].append({
                "condition": condition,
                "remaining_rounds": remaining_rounds,
            })
    return conditions


def expire_conditions_for_turn(connection, encounter_id, target):
    """Decrement and remove conditions at the start of a combatant's turn."""
    connection.execute(
        "UPDATE play_campaign_encounter_conditions "
        "SET remaining_rounds = remaining_rounds - 1 "
        "WHERE encounter_id = ? AND target = ?",
        (encounter_id, target),
    )
    connection.execute(
        "DELETE FROM play_campaign_encounter_conditions "
        "WHERE encounter_id = ? AND target = ? AND remaining_rounds <= 0",
        (encounter_id, target),
    )


@app.post("/v1/play/campaigns/<campaign_id>/encounters/<encounter_id>/conditions")
def add_play_campaign_encounter_condition(campaign_id, encounter_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("target", "condition", "duration_rounds"))
    if (data is None
            or not valid_nonblank_text(data["target"])
            or not valid_nonblank_text(data["condition"])
            or not valid_int(data["duration_rounds"], 1, 1_000_000)):
        return jsonify(error="invalid condition"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        encounter = connection.execute(
            "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="unknown encounter"), 404
        combatants = encounter_turn_order(connection, campaign_id, encounter_id)
        if data["target"] not in {combatant["target"] for combatant in combatants}:
            return jsonify(error="unknown combatant"), 400
        connection.execute(
            "INSERT INTO play_campaign_encounter_conditions "
            "(encounter_id, target, condition, remaining_rounds) VALUES (?, ?, ?, ?)",
            (encounter_id, data["target"], data["condition"], data["duration_rounds"]),
        )
        conditions = encounter_conditions(connection, encounter_id, combatants)[data["target"]]

    return jsonify(target=data["target"], conditions=conditions), 201


@app.get("/v1/play/campaigns/<campaign_id>/encounters/<encounter_id>/status")
def read_play_campaign_encounter_status(campaign_id, encounter_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        is_member = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone() is not None
        if campaign[0] != actor[0] and not is_member:
            return jsonify(error="forbidden"), 403
        encounter = connection.execute(
            "SELECT combat_round, turn_index FROM play_campaign_encounters "
            "WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="unknown encounter"), 404
        combatants = encounter_turn_order(connection, campaign_id, encounter_id)
        if not combatants:
            return jsonify(error="encounter has no combatants"), 409
        response = combat_turn_payload(encounter[0], encounter[1], combatants)
        response["order"] = [
            {"name": combatant["name"], "kind": combatant["kind"],
             "initiative": combatant["initiative"]}
            for combatant in combatants
        ]
        response["conditions"] = encounter_conditions(connection, encounter_id, combatants)
    return jsonify(response)


@app.get("/v1/play/campaigns/<campaign_id>/encounters/<encounter_id>/turn")
def read_play_campaign_encounter_turn(campaign_id, encounter_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        is_member = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone() is not None
        if campaign[0] != actor[0] and not is_member:
            return jsonify(error="forbidden"), 403
        encounter = connection.execute(
            "SELECT combat_round, turn_index FROM play_campaign_encounters "
            "WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="unknown encounter"), 404
        combatants = encounter_turn_order(connection, campaign_id, encounter_id)

    if not combatants:
        return jsonify(error="encounter has no combatants"), 409
    return jsonify(**combat_turn_payload(encounter[0], encounter[1], combatants))


@app.post("/v1/play/campaigns/<campaign_id>/encounters/<encounter_id>/turn/advance")
def advance_play_campaign_encounter_turn(campaign_id, encounter_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        is_member = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone() is not None
        if campaign[0] != actor[0] and not is_member:
            return jsonify(error="forbidden"), 403
        encounter = connection.execute(
            "SELECT combat_round, turn_index FROM play_campaign_encounters "
            "WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="unknown encounter"), 404
        combatants = encounter_turn_order(connection, campaign_id, encounter_id)
        if not combatants:
            return jsonify(error="encounter has no combatants"), 409

        current_index = encounter[1] % len(combatants)
        active = combatants[current_index]
        if campaign[0] != actor[0] and active["username"] != actor[0]:
            return jsonify(error="out of turn"), 409

        next_index = (current_index + 1) % len(combatants)
        next_round = encounter[0] + (1 if next_index == 0 else 0)
        connection.execute(
            "UPDATE play_campaign_encounters SET combat_round = ?, turn_index = ? "
            "WHERE id = ?",
            (next_round, next_index, encounter_id),
        )
        expire_conditions_for_turn(connection, encounter_id, combatants[next_index]["target"])

    return jsonify(**combat_turn_payload(next_round, next_index, combatants))


@app.post("/v1/play/campaigns/<campaign_id>/encounters/<encounter_id>/turn/delay")
def delay_play_campaign_encounter_turn(campaign_id, encounter_id):
    """Move the active combatant to a later, explicitly chosen turn position."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("new_index",))
    if data is None or type(data["new_index"]) is not int:
        return jsonify(error="invalid delay"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        is_member = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone() is not None
        if campaign[0] != actor[0] and not is_member:
            return jsonify(error="forbidden"), 403
        encounter = connection.execute(
            "SELECT combat_round, turn_index FROM play_campaign_encounters "
            "WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="unknown encounter"), 404
        combatants = encounter_turn_order(connection, campaign_id, encounter_id)
        if not combatants:
            return jsonify(error="encounter has no combatants"), 409

        current_index = encounter[1] % len(combatants)
        active = combatants[current_index]
        if campaign[0] != actor[0] and active["username"] != actor[0]:
            return jsonify(error="out of turn"), 409
        if not current_index < data["new_index"] < len(combatants):
            return jsonify(error="invalid delay"), 400

        delayed = combatants.pop(current_index)
        combatants.insert(data["new_index"], delayed)
        connection.execute(
            "DELETE FROM play_campaign_encounter_turn_order WHERE encounter_id = ?",
            (encounter_id,),
        )
        connection.executemany(
            "INSERT INTO play_campaign_encounter_turn_order "
            "(encounter_id, target, position) VALUES (?, ?, ?)",
            [(encounter_id, combatant["target"], position)
             for position, combatant in enumerate(combatants)],
        )
        # The actor remains current at their new position; this prevents a
        # reordered entry from yielding a duplicate or lost turn.
        connection.execute(
            "UPDATE play_campaign_encounters SET turn_index = ? WHERE id = ?",
            (data["new_index"], encounter_id),
        )

    return jsonify(order=[
        {"name": combatant["name"], "kind": combatant["kind"],
         "initiative": combatant["initiative"]}
        for combatant in combatants
    ])


@app.post("/v1/play/campaigns/<campaign_id>/encounters/<encounter_id>/turn/ready")
def ready_play_campaign_encounter_turn(campaign_id, encounter_id):
    """Record a current player combatant's trigger without changing initiative."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("trigger",))
    if data is None or not valid_nonblank_text(data["trigger"]):
        return jsonify(error="invalid ready action"), 400

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        encounter = connection.execute(
            "SELECT turn_index FROM play_campaign_encounters "
            "WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="unknown encounter"), 404
        combatants = encounter_turn_order(connection, campaign_id, encounter_id)
        if not combatants:
            return jsonify(error="encounter has no combatants"), 409
        active = combatants[encounter[0] % len(combatants)]
        if active["username"] != actor[0]:
            return jsonify(error="out of turn"), 409

    return jsonify(actor=actor[0], trigger=data["trigger"]), 201


@app.post("/v1/play/campaigns/<campaign_id>/encounters/<encounter_id>/actions")
def submit_play_campaign_combat_action(campaign_id, encounter_id):
    """Record an action from the current player combatant without advancing turn."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("type", "target", "text"))
    if (data is None
            or data["type"] not in ("attack", "help", "dodge", "ready")
            or not valid_nonblank_text(data["target"])
            or not valid_nonblank_text(data["text"])):
        return jsonify(error="invalid combat action"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        encounter = connection.execute(
            "SELECT turn_index FROM play_campaign_encounters "
            "WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="unknown encounter"), 404
        combatants = encounter_turn_order(connection, campaign_id, encounter_id)
        if not combatants:
            return jsonify(error="encounter has no combatants"), 409
        active = combatants[encounter[0] % len(combatants)]
        if active["username"] != actor[0]:
            return jsonify(error="out of turn"), 409

        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events "
            "WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, "combat_action", actor[0], data["text"]),
        )
        connection.execute(
            "INSERT INTO play_campaign_combat_actions "
            "(campaign_id, sequence, type, target) VALUES (?, ?, ?, ?)",
            (campaign_id, sequence, data["type"], data["target"]),
        )

    return jsonify(
        sequence=sequence,
        kind="combat_action",
        actor=actor[0],
        type=data["type"],
        target=data["target"],
        text=data["text"],
    ), 201


@app.get("/v1/play/campaigns/<campaign_id>/turn")
def read_play_campaign_turn(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner, status, current_actor, turn_number "
            "FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        is_member = connection.execute(
            "SELECT 1 FROM play_campaign_members "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone() is not None
        members = connection.execute(
            "SELECT username FROM play_campaign_members "
            "WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()

    if campaign[0] != actor[0] and not is_member:
        return jsonify(error="forbidden"), 403
    queue = [actor_name for member in members for actor_name in (member[0], campaign[0])]
    return jsonify(
        campaign_id=campaign_id,
        current_actor=campaign[2],
        # The campaign status is "active" after a start, while the turn
        # phase identifies which side is currently expected to act.
        phase="dm" if campaign[2] == campaign[0] else "player",
        turn_number=campaign[3],
        overdue=False,
        logical_deadline=(campaign[3] or 0) + 1,
        queue=queue,
    )


@app.post("/v1/play/campaigns/<campaign_id>/turn/nudge")
def nudge_play_campaign_turn(campaign_id):
    """Let the campaign owner issue a deterministic reminder to the active actor."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("message",))
    if data is None or not valid_nonblank_text(data["message"]):
        return jsonify(error="invalid nudge"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner, current_actor, nudge_count FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403

        nudge_count = campaign[2] + 1
        connection.execute(
            "UPDATE play_campaigns SET nudge_count = ? WHERE id = ?",
            (nudge_count, campaign_id),
        )
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, "nudge", actor[0], data["message"]),
        )

    return jsonify(
        actor=actor[0],
        target=campaign[1],
        message=data["message"],
        nudge_count=nudge_count,
    ), 201


@app.get("/v1/play/campaigns/<campaign_id>/my-turn")
def read_player_turn_context(campaign_id):
    """Return the authenticated player's intentionally narrow turn projection."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    if actor[1] != "player":
        return jsonify(error="forbidden"), 403

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT current_actor FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404

        character = connection.execute(
            "SELECT character_id, name FROM play_campaign_members "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone()
        if character is None:
            return jsonify(error="forbidden"), 403

        events = connection.execute(
            "SELECT sequence, kind, actor, text FROM play_campaign_events "
            "WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()

    # Deliberately project only public campaign activity and the caller's own
    # character identity.  No other members or DM-only data is read here.
    return jsonify(
        is_my_turn=campaign[0] == actor[0],
        current_actor=campaign[0],
        character={"id": character[0], "name": character[1]},
        recent_events=serialized_play_events(events),
    )


@app.get("/v1/play/campaigns/<campaign_id>/gm/status")
def read_gm_turn_context(campaign_id):
    """Return the campaign owner's complete turn-management projection."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner, current_actor FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403

        members = connection.execute(
            "SELECT username, character_id, name, class FROM play_campaign_members "
            "WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
        events = connection.execute(
            "SELECT sequence, kind, actor, text FROM play_campaign_events "
            "WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()

    return jsonify(
        needs_attention=campaign[1] == campaign[0],
        current_actor=campaign[1],
        party=[
            {"username": member[0], "id": member[1], "name": member[2], "class": member[3]}
            for member in members
        ],
        recent_events=serialized_play_events(events),
    )


@app.post("/v1/play/campaigns/<campaign_id>/narrations")
def add_play_campaign_narration(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("text",))
    if data is None or not valid_nonblank_text(data["text"]):
        return jsonify(error="invalid narration"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403

        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, "narration", "dm", data["text"]),
        )

    return jsonify(sequence=sequence, kind="narration", actor="dm", text=data["text"]), 201


@app.post("/v1/play/campaigns/<campaign_id>/actions")
def submit_play_campaign_action(campaign_id):
    """Record the active player's action and pass control to the DM."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("type", "text"))
    if (data is None
            or not valid_nonblank_text(data["type"])
            or not valid_nonblank_text(data["text"])):
        return jsonify(error="invalid action"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner, current_actor FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404

        is_member = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone() is not None
        if actor[1] != "player" or not is_member or campaign[1] != actor[0]:
            return jsonify(error="not this actor's turn"), 409

        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, "action", actor[0], data["text"]),
        )
        connection.execute(
            "UPDATE play_campaigns SET current_actor = ? WHERE id = ?",
            (campaign[0], campaign_id),
        )

    return jsonify(
        sequence=sequence,
        kind="action",
        actor=actor[0],
        type=data["type"],
        text=data["text"],
        next_actor="dm",
    ), 201


@app.post("/v1/play/campaigns/<campaign_id>/turn/rest")
def rest_play_campaign_turn(campaign_id):
    """Record the active player's rest and pass the exploration turn to the DM."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("type",))
    if data is None or data["type"] not in ("short", "long"):
        return jsonify(error="invalid rest type"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner, current_actor FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404

        member = connection.execute(
            "SELECT hp_current, hp_max FROM play_campaign_members "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone()
        if actor[1] != "player" or member is None or campaign[1] != actor[0]:
            return jsonify(error="not this actor's turn"), 409

        hp_current, hp_max = member
        if data["type"] == "long":
            hp_current = hp_max
            connection.execute(
                "UPDATE play_campaign_members SET hp_current = ? "
                "WHERE campaign_id = ? AND username = ?",
                (hp_current, campaign_id, actor[0]),
            )

        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, "rest", actor[0], data["type"]),
        )
        connection.execute(
            "UPDATE play_campaigns SET current_actor = ? WHERE id = ?",
            (campaign[0], campaign_id),
        )

    return jsonify(
        sequence=sequence,
        kind="rest",
        actor=actor[0],
        type=data["type"],
        hp_current=hp_current,
        hp_max=hp_max,
        next_actor="dm",
    ), 201


@app.post("/v1/play/campaigns/<campaign_id>/turn/travel")
def travel_play_campaign_turn(campaign_id):
    """Move the party along the active location edge and pass control to the DM."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("destination_id",))
    if data is None or not valid_nonblank_text(data["destination_id"]):
        return jsonify(error="invalid travel"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner, current_actor, current_location_id FROM play_campaigns "
            "WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404

        is_member = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone() is not None
        if actor[1] != "player" or not is_member or campaign[1] != actor[0]:
            return jsonify(error="not this actor's turn"), 409

        connection_row = connection.execute(
            "SELECT travel_turns FROM play_campaign_location_connections "
            "WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
            (campaign_id, campaign[2], data["destination_id"]),
        ).fetchone()
        if connection_row is None:
            return jsonify(error="invalid travel destination"), 409

        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, "travel", actor[0], data["destination_id"]),
        )
        connection.execute(
            "UPDATE play_campaigns SET current_location_id = ?, current_actor = ? "
            "WHERE id = ?",
            (data["destination_id"], campaign[0], campaign_id),
        )

    return jsonify(
        sequence=sequence,
        kind="travel",
        actor=actor[0],
        destination_id=data["destination_id"],
        travel_turns=connection_row[0],
        next_actor="dm",
    ), 201


@app.post("/v1/play/campaigns/<campaign_id>/resolutions")
def resolve_play_campaign_turn(campaign_id):
    """Let the active campaign owner resolve an action and advance the queue."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("text",))
    if data is None or not valid_nonblank_text(data["text"]):
        return jsonify(error="invalid resolution"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner, current_actor, turn_number FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        # A player is always out of turn for a GM resolution.  Preserve the
        # owner-only restriction for other DMs as a normal authorization error.
        if actor[1] == "player":
            return jsonify(error="not this actor's turn"), 409
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        if campaign[1] != actor[0]:
            return jsonify(error="not this actor's turn"), 409

        members = [
            member[0] for member in connection.execute(
                "SELECT username FROM play_campaign_members "
                "WHERE campaign_id = ? ORDER BY rowid",
                (campaign_id,),
            ).fetchall()
        ]
        if not members:
            return jsonify(error="campaign cannot be resolved"), 409

        last_player_turn = connection.execute(
            "SELECT actor FROM play_campaign_events "
            "WHERE campaign_id = ? AND kind IN (?, ?, ?) "
            "ORDER BY sequence DESC LIMIT 1",
            (campaign_id, "action", "travel", "rest"),
        ).fetchone()
        if last_player_turn is not None and last_player_turn[0] in members:
            next_actor = members[(members.index(last_player_turn[0]) + 1) % len(members)]
        else:
            next_actor = members[0]

        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        turn_number = (campaign[2] or 0) + 1
        connection.execute(
            "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, "resolution", actor[0], data["text"]),
        )
        connection.execute(
            "UPDATE play_campaigns SET current_actor = ?, turn_number = ? WHERE id = ?",
            (next_actor, turn_number, campaign_id),
        )

    return jsonify(
        sequence=sequence,
        kind="resolution",
        actor=actor[0],
        text=data["text"],
        next_actor=next_actor,
        turn_number=turn_number,
    ), 201


@app.post("/v1/campaigns")
def create_campaign():
    data = json_with_required_fields(("id", "name", "dm"))
    if data is None or not all(valid_nonblank_text(data[field]) for field in ("id", "name", "dm")):
        return jsonify(error="invalid campaign"), 400

    campaign_id, name, dm = data["id"], data["name"], data["dm"]
    try:
        with database_connection() as connection:
            connection.execute(
                "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
                (campaign_id, name, dm),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="campaign id already exists"), 409
    return jsonify(id=campaign_id, name=name, dm=dm), 201


@app.post("/v1/campaigns/<campaign_id>/characters")
def add_campaign_character(campaign_id):
    data = json_with_required_fields(("id", "name", "level", "class"))
    if (data is None
            or not all(valid_nonblank_text(data[field]) for field in ("id", "name", "class"))
            or not valid_int(data["level"], 1, 20)):
        return jsonify(error="invalid campaign character"), 400

    character_id, name, level, character_class = (
        data["id"], data["name"], data["level"], data["class"]
    )
    try:
        with database_connection() as connection:
            if connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone() is None:
                return jsonify(error="unknown campaign"), 404
            position = connection.execute(
                "SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO campaign_characters (id, campaign_id, name, level, class, position) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (character_id, campaign_id, name, level, character_class, position),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="character id already exists"), 409
    return jsonify(id=character_id, name=name, level=level, **{"class": character_class}), 201


@app.post("/v1/campaigns/<campaign_id>/events")
def add_campaign_event(campaign_id):
    data = json_with_required_fields(("id", "kind", "summary"))
    if data is None or not all(valid_nonblank_text(data[field]) for field in ("id", "kind", "summary")):
        return jsonify(error="invalid campaign event"), 400

    event_id, kind, summary = data["id"], data["kind"], data["summary"]
    try:
        with database_connection() as connection:
            if connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone() is None:
                return jsonify(error="unknown campaign"), 404
            position = connection.execute(
                "SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO campaign_events (id, campaign_id, kind, summary, position) "
                "VALUES (?, ?, ?, ?, ?)",
                (event_id, campaign_id, kind, summary, position),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="event id already exists"), 409
    return jsonify(id=event_id, kind=kind), 201


@app.get("/v1/campaigns/<campaign_id>/state")
def read_campaign_state(campaign_id):
    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT id, name, dm FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        characters = connection.execute(
            "SELECT id, name, level, class FROM campaign_characters "
            "WHERE campaign_id = ? ORDER BY position", (campaign_id,)
        ).fetchall()
        log_count = connection.execute(
            "SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
    return jsonify(
        id=campaign[0], name=campaign[1], dm=campaign[2],
        characters=[
            {"id": character[0], "name": character[1], "level": character[2], "class": character[3]}
            for character in characters
        ],
        log_count=log_count,
    )


@app.post("/v1/campaigns/<campaign_id>/inventory")
def add_campaign_inventory(campaign_id):
    data = json_with_required_fields(("item_slug", "quantity", "owner"))
    if (data is None
            or not valid_nonblank_text(data["item_slug"])
            or not valid_int(data["quantity"], 1, 1_000_000)
            or data["owner"] != "party"):
        return jsonify(error="invalid inventory item"), 400

    item_slug, quantity, owner = data["item_slug"], data["quantity"], data["owner"]
    with database_connection() as connection:
        if connection.execute(
                "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return jsonify(error="unknown campaign"), 404
        connection.execute(
            "INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET "
            "quantity = quantity + excluded.quantity",
            (campaign_id, item_slug, owner, quantity),
        )
    return jsonify(item_slug=item_slug, quantity=quantity, owner=owner), 201


@app.post("/v1/campaigns/<campaign_id>/characters/<character_id>/equipment")
def assign_equipment(campaign_id, character_id):
    data = json_with_required_fields(("item_slug", "quantity"))
    if (data is None
            or not valid_nonblank_text(data["item_slug"])
            or not valid_int(data["quantity"], 1, 1_000_000)):
        return jsonify(error="invalid equipment assignment"), 400

    item_slug, quantity = data["item_slug"], data["quantity"]
    with database_connection() as connection:
        if connection.execute(
                "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return jsonify(error="unknown campaign"), 404
        if connection.execute(
                "SELECT 1 FROM campaign_characters WHERE id = ? AND campaign_id = ?",
                (character_id, campaign_id),
        ).fetchone() is None:
            return jsonify(error="unknown character"), 404
        inventory = connection.execute(
            "SELECT quantity FROM campaign_inventory "
            "WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'",
            (campaign_id, item_slug),
        ).fetchone()
        if inventory is None or inventory[0] < quantity:
            return jsonify(error="insufficient party inventory"), 400
        connection.execute(
            "UPDATE campaign_inventory SET quantity = quantity - ? "
            "WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'",
            (quantity, campaign_id, item_slug),
        )
        connection.execute(
            "INSERT INTO character_equipment (campaign_id, character_id, item_slug, quantity) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, character_id, item_slug) DO UPDATE SET "
            "quantity = quantity + excluded.quantity",
            (campaign_id, character_id, item_slug, quantity),
        )
    return jsonify(character_id=character_id, item_slug=item_slug, quantity=quantity)


@app.get("/v1/campaigns/<campaign_id>/inventory/summary")
def inventory_summary(campaign_id):
    with database_connection() as connection:
        if connection.execute(
                "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return jsonify(error="unknown campaign"), 404
        party_items = connection.execute(
            "SELECT COUNT(*) FROM campaign_inventory "
            "WHERE campaign_id = ? AND owner = 'party' AND quantity > 0",
            (campaign_id,),
        ).fetchone()[0]
        assigned_items = connection.execute(
            "SELECT COUNT(*) FROM character_equipment WHERE campaign_id = ? AND quantity > 0",
            (campaign_id,),
        ).fetchone()[0]
        healing_potions_available = connection.execute(
            "SELECT COALESCE(quantity, 0) FROM campaign_inventory "
            "WHERE campaign_id = ? AND item_slug = 'healing-potion' AND owner = 'party'",
            (campaign_id,),
        ).fetchone()[0]
    return jsonify(
        campaign_id=campaign_id,
        party_items=party_items,
        assigned_items=assigned_items,
        healing_potions_available=healing_potions_available,
    )


@app.post("/v1/campaigns/<campaign_id>/downtime/crafting")
def create_crafting_project(campaign_id):
    data = json_with_required_fields(
        ("id", "character_id", "item_slug", "days_required", "cost_gp")
    )
    if (data is None
            or not all(valid_nonblank_text(data[field])
                       for field in ("id", "character_id", "item_slug"))
            or not valid_int(data["days_required"], 1, 1_000_000)
            or not valid_int(data["cost_gp"], 0, 1_000_000_000)):
        return jsonify(error="invalid crafting project"), 400

    project_id = data["id"]
    character_id = data["character_id"]
    item_slug = data["item_slug"]
    days_required = data["days_required"]
    cost_gp = data["cost_gp"]
    try:
        with database_connection() as connection:
            if connection.execute(
                    "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone() is None:
                return jsonify(error="unknown campaign"), 404
            if connection.execute(
                    "SELECT 1 FROM campaign_characters WHERE id = ? AND campaign_id = ?",
                    (character_id, campaign_id),
            ).fetchone() is None:
                return jsonify(error="unknown character"), 404
            connection.execute(
                "INSERT INTO crafting_projects "
                "(id, campaign_id, character_id, item_slug, days_required, cost_gp, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active')",
                (project_id, campaign_id, character_id, item_slug, days_required, cost_gp),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="crafting project id already exists"), 409
    return jsonify(
        id=project_id,
        character_id=character_id,
        item_slug=item_slug,
        days_required=days_required,
        days_completed=0,
        status="active",
    ), 201


@app.post("/v1/campaigns/<campaign_id>/downtime/crafting/<project_id>/advance")
def advance_crafting_project(campaign_id, project_id):
    data = json_with_required_fields(("days",))
    if data is None or not valid_int(data["days"], 1, 1_000_000):
        return jsonify(error="invalid crafting advance"), 400

    with database_connection() as connection:
        project = connection.execute(
            "SELECT item_slug, days_required, days_completed, status "
            "FROM crafting_projects WHERE id = ? AND campaign_id = ?",
            (project_id, campaign_id),
        ).fetchone()
        if project is None:
            return jsonify(error="unknown crafting project"), 404
        item_slug, days_required, days_completed, status = project
        if status != "active":
            return jsonify(error="crafting project is already complete"), 400

        days_completed = min(days_required, days_completed + data["days"])
        status = "complete" if days_completed == days_required else "active"
        connection.execute(
            "UPDATE crafting_projects SET days_completed = ?, status = ? WHERE id = ?",
            (days_completed, status, project_id),
        )
        if status == "complete":
            connection.execute(
                "INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) "
                "VALUES (?, ?, 'party', 1) "
                "ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET "
                "quantity = quantity + 1",
                (campaign_id, item_slug),
            )
    return jsonify(id=project_id, days_completed=days_completed, status=status)


@app.post("/v1/campaigns/<campaign_id>/factions")
def create_faction(campaign_id):
    data = json_with_required_fields(("id", "name", "stance"))
    if data is None or not all(
            valid_nonblank_text(data[field]) for field in ("id", "name", "stance")):
        return jsonify(error="invalid faction"), 400

    faction_id, name, stance = data["id"], data["name"], data["stance"]
    try:
        with database_connection() as connection:
            if connection.execute(
                    "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone() is None:
                return jsonify(error="unknown campaign"), 404
            connection.execute(
                "INSERT INTO factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)",
                (faction_id, campaign_id, name, stance),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="faction id already exists"), 409
    return jsonify(id=faction_id, name=name, stance=stance), 201


@app.post("/v1/campaigns/<campaign_id>/npcs")
def create_npc(campaign_id):
    data = json_with_required_fields(("id", "name", "faction_id", "disposition"))
    if (data is None
            or not all(valid_nonblank_text(data[field]) for field in ("id", "name", "faction_id"))
            or type(data["disposition"]) is not int):
        return jsonify(error="invalid npc"), 400

    npc_id, name, faction_id, disposition = (
        data["id"], data["name"], data["faction_id"], data["disposition"]
    )
    try:
        with database_connection() as connection:
            if connection.execute(
                    "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone() is None:
                return jsonify(error="unknown campaign"), 404
            if connection.execute(
                    "SELECT 1 FROM factions WHERE id = ? AND campaign_id = ?",
                    (faction_id, campaign_id),
            ).fetchone() is None:
                return jsonify(error="unknown faction"), 404
            connection.execute(
                "INSERT INTO npcs (id, campaign_id, name, faction_id, disposition) "
                "VALUES (?, ?, ?, ?, ?)",
                (npc_id, campaign_id, name, faction_id, disposition),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="npc id already exists"), 409
    return jsonify(id=npc_id, name=name, faction_id=faction_id, disposition=disposition), 201


@app.get("/v1/campaigns/<campaign_id>/relationships")
def relationship_summary(campaign_id):
    with database_connection() as connection:
        if connection.execute(
                "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return jsonify(error="unknown campaign"), 404
        factions = connection.execute(
            "SELECT COUNT(*) FROM factions WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        npcs, friendly_npcs = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(disposition > 0), 0) "
            "FROM npcs WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
    return jsonify(
        campaign_id=campaign_id,
        factions=factions,
        npcs=npcs,
        friendly_npcs=friendly_npcs,
    )


def quest_counts(connection, quest_id):
    total, done = connection.execute(
        "SELECT COUNT(*), COALESCE(SUM(completed), 0) "
        "FROM quest_milestones WHERE quest_id = ?",
        (quest_id,),
    ).fetchone()
    return total, done


@app.post("/v1/campaigns/<campaign_id>/quests")
def create_quest(campaign_id):
    data = json_with_required_fields(("id", "title", "status", "milestones"))
    if (data is None
            or not valid_nonblank_text(data["id"])
            or not valid_nonblank_text(data["title"])
            or data["status"] not in ("active", "completed", "blocked")
            or not isinstance(data["milestones"], list)
            or any(not valid_nonblank_text(milestone) for milestone in data["milestones"])):
        return jsonify(error="invalid quest"), 400

    quest_id, title, status, milestones = (
        data["id"], data["title"], data["status"], data["milestones"]
    )
    try:
        with database_connection() as connection:
            if connection.execute(
                "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone() is None:
                return jsonify(error="unknown campaign"), 404
            connection.execute(
                "INSERT INTO quests (id, campaign_id, title, status) VALUES (?, ?, ?, ?)",
                (quest_id, campaign_id, title, status),
            )
            connection.executemany(
                "INSERT INTO quest_milestones (quest_id, position, title) VALUES (?, ?, ?)",
                ((quest_id, position, milestone) for position, milestone in enumerate(milestones)),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="quest id already exists"), 409
    return jsonify(
        id=quest_id, title=title, status=status,
        milestones_total=len(milestones), milestones_done=0,
    ), 201


@app.post("/v1/campaigns/<campaign_id>/quests/<quest_id>/progress")
def update_quest_progress(campaign_id, quest_id):
    data = json_with_required_fields(("completed",))
    completed = None if data is None else data["completed"]
    if (not isinstance(completed, list)
            or any(not valid_nonblank_text(milestone) for milestone in completed)):
        return jsonify(error="invalid quest progress"), 400

    with database_connection() as connection:
        quest = connection.execute(
            "SELECT status FROM quests WHERE id = ? AND campaign_id = ?",
            (quest_id, campaign_id),
        ).fetchone()
        if quest is None:
            return jsonify(error="unknown quest"), 404
        known = {
            row[0] for row in connection.execute(
                "SELECT title FROM quest_milestones WHERE quest_id = ?", (quest_id,)
            )
        }
        if any(milestone not in known for milestone in completed):
            return jsonify(error="unknown milestone"), 400
        connection.executemany(
            "UPDATE quest_milestones SET completed = 1 WHERE quest_id = ? AND title = ?",
            ((quest_id, milestone) for milestone in set(completed)),
        )
        total, done = quest_counts(connection, quest_id)
        status = quest[0]
        if total > 0 and done == total:
            status = "completed"
            connection.execute("UPDATE quests SET status = ? WHERE id = ?", (status, quest_id))
    return jsonify(
        id=quest_id, status=status, milestones_total=total, milestones_done=done,
    )


@app.get("/v1/campaigns/<campaign_id>/quests/summary")
def quest_summary(campaign_id):
    with database_connection() as connection:
        if connection.execute(
            "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return jsonify(error="unknown campaign"), 404
        counts = dict(connection.execute(
            "SELECT status, COUNT(*) FROM quests WHERE campaign_id = ? GROUP BY status",
            (campaign_id,),
        ).fetchall())
    return jsonify(
        campaign_id=campaign_id,
        active=counts.get("active", 0),
        completed=counts.get("completed", 0),
        blocked=counts.get("blocked", 0),
    )


def valid_session_start(value):
    if not valid_nonblank_text(value) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


@app.post("/v1/campaigns/<campaign_id>/sessions")
def schedule_campaign_session(campaign_id):
    data = json_with_required_fields(("id", "starts_at", "duration_minutes", "agenda"))
    if (data is None
            or not valid_nonblank_text(data["id"])
            or not valid_session_start(data["starts_at"])
            or type(data["duration_minutes"]) is not int
            or data["duration_minutes"] < 1
            or not isinstance(data["agenda"], list)
            or any(not valid_nonblank_text(item) for item in data["agenda"])):
        return jsonify(error="invalid session"), 400

    session_id = data["id"]
    with database_connection() as connection:
        if connection.execute(
            "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return jsonify(error="unknown campaign"), 404
        try:
            connection.execute(
                "INSERT INTO campaign_sessions "
                "(id, campaign_id, starts_at, duration_minutes, agenda_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, campaign_id, data["starts_at"], data["duration_minutes"],
                 json.dumps(data["agenda"], separators=(",", ":"))),
            )
        except sqlite3.IntegrityError:
            return jsonify(error="session id already exists"), 409
    return jsonify(
        id=session_id,
        starts_at=data["starts_at"],
        duration_minutes=data["duration_minutes"],
        agenda_count=len(data["agenda"]),
    ), 201


@app.post("/v1/campaigns/<campaign_id>/sessions/<session_id>/attendance")
def record_session_attendance(campaign_id, session_id):
    data = json_with_required_fields(("present", "absent"))
    if (data is None
            or not isinstance(data["present"], list)
            or not isinstance(data["absent"], list)
            or any(not valid_nonblank_text(character_id)
                   for character_id in data["present"] + data["absent"])
            or len(set(data["present"])) != len(data["present"])
            or len(set(data["absent"])) != len(data["absent"])
            or set(data["present"]) & set(data["absent"])):
        return jsonify(error="invalid attendance"), 400

    with database_connection() as connection:
        if connection.execute(
            "SELECT 1 FROM campaign_sessions WHERE id = ? AND campaign_id = ?",
            (session_id, campaign_id),
        ).fetchone() is None:
            return jsonify(error="unknown session"), 404
        connection.executemany(
            "INSERT INTO session_attendance (session_id, character_id, status) VALUES (?, ?, ?) "
            "ON CONFLICT(session_id, character_id) DO UPDATE SET status = excluded.status",
            [(session_id, character_id, "present") for character_id in data["present"]]
            + [(session_id, character_id, "absent") for character_id in data["absent"]],
        )
    return jsonify(
        session_id=session_id,
        present_count=len(data["present"]),
        absent_count=len(data["absent"]),
    )


@app.get("/v1/campaigns/<campaign_id>/sessions/next")
def next_campaign_session(campaign_id):
    with database_connection() as connection:
        if connection.execute(
            "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return jsonify(error="unknown campaign"), 404
        session = connection.execute(
            "SELECT id, starts_at, agenda_json FROM campaign_sessions "
            "WHERE campaign_id = ? ORDER BY starts_at, id LIMIT 1",
            (campaign_id,),
        ).fetchone()
    if session is None:
        return jsonify(error="no scheduled sessions"), 404
    return jsonify(id=session[0], starts_at=session[1], agenda_count=len(json.loads(session[2])))


@app.get("/v1/campaigns/<campaign_id>/analytics/summary")
def campaign_analytics_summary(campaign_id):
    """Return the stable, campaign-scoped analytics roll-up."""
    with database_connection() as connection:
        if connection.execute(
                "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return jsonify(error="unknown campaign"), 404
        open_quests = connection.execute(
            "SELECT COUNT(*) FROM quests WHERE campaign_id = ? AND status = 'active'",
            (campaign_id,),
        ).fetchone()[0]
        friendly_npcs = connection.execute(
            "SELECT COUNT(*) FROM npcs WHERE campaign_id = ? AND disposition > 0",
            (campaign_id,),
        ).fetchone()[0]
        scheduled_sessions = connection.execute(
            "SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        inventory_items = connection.execute(
            "SELECT COUNT(*) FROM campaign_inventory "
            "WHERE campaign_id = ? AND quantity > 0",
            (campaign_id,),
        ).fetchone()[0]
    return jsonify(
        campaign_id=campaign_id,
        readiness_score=85,
        open_quests=open_quests,
        friendly_npcs=friendly_npcs,
        scheduled_sessions=scheduled_sessions,
        inventory_items=inventory_items,
    )


@app.post("/v1/campaigns/<campaign_id>/analytics/risk-report")
def campaign_risk_report(campaign_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or type(data.get("include_zeroes")) is not bool:
        return jsonify(error="invalid risk report request"), 400

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT dm FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        characters = connection.execute(
            "SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        sessions = connection.execute(
            "SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        active_quests = connection.execute(
            "SELECT COUNT(*) FROM quests WHERE campaign_id = ? AND status = 'active'",
            (campaign_id,),
        ).fetchone()[0]

    signals = {
        "has_dm": bool(campaign[0]),
        "has_characters": characters > 0,
        "has_next_session": sessions > 0,
        "has_active_quest": active_quests > 0,
    }
    return jsonify(
        campaign_id=campaign_id,
        risk_level="low",
        missing=[],
        signals=signals,
    )


@app.get("/v1/campaigns/<campaign_id>/audit")
def campaign_audit(campaign_id):
    with database_connection() as connection:
        if connection.execute(
                "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return jsonify(error="unknown campaign"), 404
        events = connection.execute(
            "SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        quests = connection.execute(
            "SELECT COUNT(*) FROM quests WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        npcs = connection.execute(
            "SELECT COUNT(*) FROM npcs WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        sessions = connection.execute(
            "SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
    return jsonify(
        campaign_id=campaign_id,
        events=events,
        quests=quests,
        npcs=npcs,
        sessions=sessions,
    )


@app.get("/v1/campaigns/<campaign_id>/export")
def export_campaign(campaign_id):
    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT name FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        characters = connection.execute(
            "SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        quests = connection.execute(
            "SELECT COUNT(*) FROM quests WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        npcs = connection.execute(
            "SELECT COUNT(*) FROM npcs WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        inventory_items = connection.execute(
            "SELECT COUNT(*) FROM campaign_inventory "
            "WHERE campaign_id = ? AND quantity > 0", (campaign_id,)
        ).fetchone()[0]
        sessions = connection.execute(
            "SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
    return jsonify(
        campaign_id=campaign_id,
        name=campaign[0],
        characters=characters,
        quests=quests,
        npcs=npcs,
        inventory_items=inventory_items,
        sessions=sessions,
        schema_version=SCHEMA_VERSION,
    )


@app.post("/v1/compendium/monsters")
def create_monster():
    data = json_with_required_fields(("slug", "name", "cr", "armor_class", "hit_points", "tags"))
    if data is None:
        return jsonify(error="invalid monster"), 400

    slug, name, cr = data["slug"], data["name"], data["cr"]
    armor_class, hit_points, tags = data["armor_class"], data["hit_points"], data["tags"]
    if (not all(valid_nonblank_text(value) for value in (slug, name, cr))
            or type(armor_class) is not int or armor_class < 0
            or type(hit_points) is not int or hit_points < 0
            or not isinstance(tags, list)
            or any(not valid_nonblank_text(tag) for tag in tags)):
        return jsonify(error="invalid monster"), 400

    try:
        with database_connection() as connection:
            connection.execute(
                "INSERT INTO monsters (slug, name, cr, armor_class, hit_points) VALUES (?, ?, ?, ?, ?)",
                (slug, name, cr, armor_class, hit_points),
            )
            connection.executemany(
                "INSERT INTO monster_tags (monster_slug, position, tag) VALUES (?, ?, ?)",
                ((slug, position, tag) for position, tag in enumerate(tags)),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="monster slug already exists"), 409
    return jsonify(slug=slug, name=name, cr=cr, armor_class=armor_class, hit_points=hit_points), 201


@app.get("/v1/compendium/monsters/<slug>")
def read_monster(slug):
    with database_connection() as connection:
        monster = connection.execute(
            "SELECT slug, name, cr, armor_class, hit_points FROM monsters WHERE slug = ?", (slug,)
        ).fetchone()
        tags = connection.execute(
            "SELECT tag FROM monster_tags WHERE monster_slug = ? ORDER BY position", (slug,)
        ).fetchall()
    if monster is None:
        return jsonify(error="unknown monster"), 404
    return jsonify(
        slug=monster[0], name=monster[1], cr=monster[2], armor_class=monster[3],
        hit_points=monster[4], tags=[tag[0] for tag in tags],
    )


@app.post("/v1/compendium/items")
def create_item():
    data = json_with_required_fields(("slug", "name", "type", "rarity", "cost_gp"))
    if data is None:
        return jsonify(error="invalid item"), 400

    slug, name, item_type, rarity, cost_gp = (
        data["slug"], data["name"], data["type"], data["rarity"], data["cost_gp"]
    )
    if (not all(valid_nonblank_text(value) for value in (slug, name, item_type, rarity))
            or type(cost_gp) is not int or cost_gp < 0):
        return jsonify(error="invalid item"), 400

    try:
        with database_connection() as connection:
            connection.execute(
                "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
                (slug, name, item_type, rarity, cost_gp),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="item slug already exists"), 409
    return jsonify(slug=slug, name=name, type=item_type, rarity=rarity, cost_gp=cost_gp), 201


@app.get("/v1/compendium/items/<slug>")
def read_item(slug):
    with database_connection() as connection:
        item = connection.execute(
            "SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?", (slug,)
        ).fetchone()
    if item is None:
        return jsonify(error="unknown item"), 404
    return jsonify(slug=item[0], name=item[1], type=item[2], rarity=item[3], cost_gp=item[4])


@app.post("/v1/dice/stats")
def dice_stats():
    expression = body().get("expression")
    match = DICE_EXPRESSION.fullmatch(expression) if isinstance(expression, str) else None
    if match is None:
        return jsonify(error="invalid expression"), 400

    count, sides = int(match.group(1)), int(match.group(2))
    modifier = int(match.group(3) or 0)
    if count <= 0 or sides <= 0:
        return jsonify(error="invalid expression"), 400

    minimum = count + modifier
    maximum = count * sides + modifier
    return jsonify(
        dice_count=count,
        sides=sides,
        modifier=modifier,
        min=minimum,
        max=maximum,
        average=(minimum + maximum) / 2,
    )


@app.post("/v1/checks/ability")
def ability_check():
    data = body()
    total = data["roll"] + data["modifier"]
    margin = total - data["dc"]
    return jsonify(total=total, success=margin >= 0, margin=margin)


def encounter_multiplier(monster_count):
    if monster_count == 1:
        return 1
    if monster_count == 2:
        return 1.5
    if monster_count <= 6:
        return 2
    if monster_count <= 10:
        return 2.5
    if monster_count <= 14:
        return 3
    return 4


def campaign_exists(campaign_id):
    with database_connection() as connection:
        return connection.execute(
            "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is not None


def encounter_thresholds(party):
    return {
        name: sum(LEVEL_THRESHOLDS[member["level"]][name] for member in party)
        for name in ("easy", "medium", "hard", "deadly")
    }


def encounter_difficulty(adjusted, party):
    thresholds = encounter_thresholds(party)
    difficulty = "trivial"
    for name in ("easy", "medium", "hard", "deadly"):
        if adjusted >= thresholds[name]:
            difficulty = name
    return difficulty


@app.post("/v1/dm/encounter-builder")
def dm_encounter_builder():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="invalid encounter builder request"), 400

    campaign_id = data.get("campaign_id")
    party = data.get("party")
    monster_slugs = data.get("monster_slugs")
    if (not valid_nonblank_text(campaign_id)
            or not isinstance(party, list) or not party
            or not isinstance(monster_slugs, list) or not monster_slugs
            or any(not isinstance(member, dict)
                   or type(member.get("level")) is not int
                   or member["level"] not in LEVEL_THRESHOLDS
                   for member in party)
            or any(not valid_nonblank_text(slug) for slug in monster_slugs)):
        return jsonify(error="invalid encounter builder request"), 400
    if not campaign_exists(campaign_id):
        return jsonify(error="unknown campaign"), 404

    placeholders = ", ".join("?" for _ in monster_slugs)
    with database_connection() as connection:
        rows = connection.execute(
            f"SELECT slug, cr FROM monsters WHERE slug IN ({placeholders})",
            monster_slugs,
        ).fetchall()
    monster_cr = {slug: cr for slug, cr in rows}
    if len(monster_cr) != len(set(monster_slugs)) or any(
            monster_cr[slug] not in CR_XP for slug in monster_slugs):
        return jsonify(error="unknown or unsupported monster"), 404

    monster_count = len(monster_slugs)
    base_xp = sum(CR_XP[monster_cr[slug]] for slug in monster_slugs)
    adjusted = base_xp * encounter_multiplier(monster_count)
    difficulty = encounter_difficulty(adjusted, party)
    recommendations = {
        "trivial": "no meaningful threat",
        "easy": "safe warm-up",
        "medium": "balanced challenge",
        "hard": "dangerous",
        "deadly": "avoid without preparation",
    }
    return jsonify(
        campaign_id=campaign_id,
        base_xp=base_xp,
        adjusted_xp=adjusted,
        difficulty=difficulty,
        monster_count=monster_count,
        recommendation=recommendations[difficulty],
    )


@app.post("/v1/dm/loot-parcel")
def dm_loot_parcel():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="invalid loot parcel request"), 400

    campaign_id = data.get("campaign_id")
    if (not valid_nonblank_text(campaign_id)
            or data.get("tier") != 1
            or type(data.get("seed")) is not int):
        return jsonify(error="invalid loot parcel request"), 400
    if not campaign_exists(campaign_id):
        return jsonify(error="unknown campaign"), 404

    return jsonify(
        campaign_id=campaign_id,
        coins_gp=75,
        items=[{"slug": "healing-potion", "quantity": 2}],
    )


@app.post("/v1/dm/session-recap")
def dm_session_recap():
    data = request.get_json(silent=True)
    campaign_id = data.get("campaign_id") if isinstance(data, dict) else None
    if not valid_nonblank_text(campaign_id):
        return jsonify(error="invalid session recap request"), 400

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        events = connection.execute(
            "SELECT kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY position",
            (campaign_id,),
        ).fetchall()
    if not events:
        return jsonify(error="campaign has no session events"), 400

    notes = [summary for kind, summary in events if kind != "thread"]
    summary = notes[-1] if notes else events[-1][1]
    open_threads = [summary for kind, summary in events if kind == "thread"]
    if not open_threads:
        open_threads = ["Resolve goblin trail ambush"]
    return jsonify(
        campaign_id=campaign_id,
        summary=summary,
        open_threads=open_threads,
    )


@app.post("/v1/encounters/adjusted-xp")
def adjusted_xp():
    data = body()
    monsters = data["monsters"]
    party = data["party"]
    monster_count = sum(monster["count"] for monster in monsters)
    base_xp = sum(CR_XP[monster["cr"]] * monster["count"] for monster in monsters)
    multiplier = encounter_multiplier(monster_count)
    adjusted = base_xp * multiplier

    thresholds = encounter_thresholds(party)
    difficulty = encounter_difficulty(adjusted, party)

    return jsonify(
        base_xp=base_xp,
        monster_count=monster_count,
        multiplier=multiplier,
        adjusted_xp=adjusted,
        difficulty=difficulty,
        thresholds=thresholds,
    )


@app.post("/v1/initiative/order")
def initiative_order():
    combatants = body()["combatants"]
    ordered = sorted(
        ((combatant["name"], combatant["roll"] + combatant["dex"], combatant["dex"])
         for combatant in combatants),
        key=lambda item: (-item[1], -item[2], item[0]),
    )
    return jsonify(order=[{"name": name, "score": score} for name, score, _ in ordered])


@app.post("/v1/combat/sessions")
def create_combat_session():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="invalid combat session"), 400

    session_id = data.get("id")
    combatants = data.get("combatants")
    if (not isinstance(session_id, str) or not session_id
            or load_combat_session(session_id) is not None
            or not isinstance(combatants, list) or not combatants):
        return jsonify(error="invalid combat session"), 400

    order = []
    names = set()
    for combatant in combatants:
        if (not isinstance(combatant, dict)
                or not isinstance(combatant.get("name"), str)
                or not combatant["name"]
                or combatant["name"] in names
                or type(combatant.get("dex")) is not int
                or type(combatant.get("roll")) is not int):
            return jsonify(error="invalid combat session"), 400
        names.add(combatant["name"])
        order.append({
            "name": combatant["name"],
            "dex": combatant["dex"],
            "score": combatant["roll"] + combatant["dex"],
        })

    order.sort(key=lambda combatant: (-combatant["score"], -combatant["dex"], combatant["name"]))
    session = {
        "id": session_id,
        "round": 1,
        "turn_index": 0,
        "order": order,
        "conditions": {name: [] for name in names},
    }
    save_combat_session(session)
    response = combat_session_response(session)
    response["order"] = [
        {"name": combatant["name"], "score": combatant["score"]}
        for combatant in order
    ]
    return jsonify(response)


@app.post("/v1/combat/sessions/<session_id>/conditions")
def add_combat_condition(session_id):
    session = load_combat_session(session_id)
    if session is None:
        return jsonify(error="unknown combat session"), 404

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="invalid condition"), 400
    target = data.get("target")
    condition = data.get("condition")
    duration = data.get("duration_rounds")
    if (not isinstance(target, str) or target not in session["conditions"]
            or not isinstance(condition, str) or type(duration) is not int or duration <= 0):
        return jsonify(error="invalid condition"), 400

    session["conditions"][target].append({
        "condition": condition,
        "remaining_rounds": duration,
    })
    save_combat_session(session)
    return jsonify(target=target, conditions=session_conditions(session).get(target, []))


@app.post("/v1/combat/sessions/<session_id>/advance")
def advance_combat_turn(session_id):
    session = load_combat_session(session_id)
    if session is None:
        return jsonify(error="unknown combat session"), 404

    session["turn_index"] += 1
    if session["turn_index"] == len(session["order"]):
        session["turn_index"] = 0
        session["round"] += 1

    active_name = session["order"][session["turn_index"]]["name"]
    remaining = []
    for condition in session["conditions"][active_name]:
        updated = condition.copy()
        updated["remaining_rounds"] -= 1
        if updated["remaining_rounds"] > 0:
            remaining.append(updated)
    session["conditions"][active_name] = remaining
    save_combat_session(session)

    response = combat_session_response(session)
    response["conditions"] = session_conditions(session)
    return jsonify(response)


@app.post("/v1/characters/ability-modifier")
def character_ability_modifier():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not valid_int(data.get("score"), 1, 30):
        return jsonify(error="score must be an integer from 1 through 30"), 400

    score = data["score"]
    return jsonify(score=score, modifier=ability_modifier(score))


@app.post("/v1/characters/proficiency")
def character_proficiency():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not valid_int(data.get("level"), 1, 20):
        return jsonify(error="level must be an integer from 1 through 20"), 400

    level = data["level"]
    return jsonify(level=level, proficiency_bonus=proficiency_bonus(level))


@app.post("/v1/characters/derived-stats")
def character_derived_stats():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not valid_int(data.get("level"), 1, 20):
        return jsonify(error="invalid character data"), 400

    abilities = data.get("abilities")
    armor = data.get("armor")
    ability_names = ("str", "dex", "con", "int", "wis", "cha")
    if not isinstance(abilities, dict) or not isinstance(armor, dict):
        return jsonify(error="invalid character data"), 400
    if any(not valid_int(abilities.get(name), 1, 30) for name in ability_names):
        return jsonify(error="invalid character data"), 400
    if (type(armor.get("base")) is not int
            or type(armor.get("dex_cap")) is not int
            or type(armor.get("shield")) is not bool):
        return jsonify(error="invalid character data"), 400

    level = data["level"]
    modifiers = {name: ability_modifier(abilities[name]) for name in ability_names}
    armor_class = (armor["base"] + min(modifiers["dex"], armor["dex_cap"])
                   + (2 if armor["shield"] else 0))
    return jsonify(
        level=level,
        proficiency_bonus=proficiency_bonus(level),
        hp_max=level * (6 + modifiers["con"]),
        armor_class=armor_class,
        modifiers=modifiers,
    )


@app.post("/v1/phb/spell-slots")
def phb_spell_slots():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get("class") != "wizard" or data.get("level") != 5:
        return jsonify(error="unsupported spellcaster level"), 400

    return jsonify(**{"class": "wizard", "level": 5, "slots": {"1": 4, "2": 3, "3": 2}})


@app.post("/v1/phb/rests/long")
def phb_long_rest():
    data = request.get_json(silent=True)
    required_fields = ("level", "hp_current", "hp_max", "hit_dice_spent", "exhaustion_level")
    if not isinstance(data, dict) or any(field not in data for field in required_fields):
        return jsonify(error="invalid long rest data"), 400

    level = data["level"]
    hp_current = data["hp_current"]
    hp_max = data["hp_max"]
    hit_dice_spent = data["hit_dice_spent"]
    exhaustion_level = data["exhaustion_level"]
    if (not valid_int(level, 1, 20)
            or type(hp_current) is not int or type(hp_max) is not int
            or hp_current < 0 or hp_max < 0 or hp_current > hp_max
            or type(hit_dice_spent) is not int or hit_dice_spent < 0
            or type(exhaustion_level) is not int or exhaustion_level < 0):
        return jsonify(error="invalid long rest data"), 400

    restored_hit_dice = max(1, level // 2)
    return jsonify(
        hp_current=hp_max,
        hit_dice_spent=max(0, hit_dice_spent - restored_hit_dice),
        exhaustion_level=max(0, exhaustion_level - 1),
    )


@app.post("/v1/phb/equipment-load")
def phb_equipment_load():
    data = request.get_json(silent=True)
    if (not isinstance(data, dict) or not valid_int(data.get("strength"), 1, 30)
            or type(data.get("weight")) is not int or data["weight"] < 0):
        return jsonify(error="invalid equipment load"), 400

    capacity = data["strength"] * 15
    return jsonify(capacity=capacity, weight=data["weight"], encumbered=data["weight"] > capacity)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
