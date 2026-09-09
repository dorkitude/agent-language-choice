#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import re
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import parse_qs, urlsplit


XP_BY_CR = {"0": 10, "1/8": 25, "1/4": 50, "1/2": 100,
            "1": 200, "2": 450, "3": 700, "4": 1100, "5": 1800}
THRESHOLDS = {"easy": 75, "medium": 150, "hard": 225, "deadly": 400}
DICE = re.compile(r"^([0-9]+)d([0-9]+)([+-][0-9]+)?$")
DATABASE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game.db")
DATABASE_LOCK = Lock()
SERVICE_MODE_LOCK = Lock()
SERVICE_MAINTENANCE = False
USERNAME = re.compile(r"^[a-z0-9_-]{2,32}$")
CHARACTER_RACES = frozenset((
    "dragonborn", "dwarf", "elf", "gnome", "half-elf", "half-orc",
    "halfling", "human", "tiefling",
))
CHARACTER_CLASSES = frozenset((
    "barbarian", "bard", "cleric", "druid", "fighter", "monk", "paladin",
    "ranger", "rogue", "sorcerer", "warlock", "wizard",
))
CHARACTER_BACKGROUNDS = frozenset((
    "acolyte", "charlatan", "criminal", "entertainer", "folk-hero",
    "guild-artisan", "hermit", "noble", "outlander", "sage", "sailor",
    "soldier", "urchin",
))
ABILITY_NAMES = ("str", "dex", "con", "int", "wis", "cha")
SKILL_NAMES = frozenset((
    "acrobatics", "animal-handling", "arcana", "athletics", "deception",
    "history", "insight", "intimidation", "investigation", "medicine",
    "nature", "perception", "performance", "persuasion", "religion",
    "sleight-of-hand", "stealth", "survival",
))
WIZARD_SPELL_IDS = frozenset(("fire-bolt", "magic-missile"))
PLAY_INVENTORY_ITEM_IDS = frozenset((
    "healing-potion", "torch", "leather-armor", "ring-of-protection",
    "amulet-of-health",
))
PLAY_CONSUMABLE_ITEM_IDS = frozenset(("healing-potion",))
PLAY_EQUIPMENT_SLOTS = frozenset(("armor", "accessory"))
PLAY_EQUIPMENT_ITEM_SLOTS = {
    "leather-armor": "armor",
    "ring-of-protection": "accessory",
    "amulet-of-health": "accessory",
}
PLAY_ATTUNABLE_ITEM_IDS = frozenset(("ring-of-protection", "amulet-of-health"))
LEVEL_ONE_HIT_DICE = {
    "barbarian": 12, "bard": 8, "cleric": 8, "druid": 8, "fighter": 10,
    "monk": 8, "paladin": 10, "ranger": 10, "rogue": 8, "sorcerer": 6,
    "warlock": 8, "wizard": 6,
}
# Kept in one place so the startup schema is easy to compare with reset_storage.
SCHEMA_STATEMENTS = (
    "CREATE TABLE IF NOT EXISTS storage_metadata (schema_version INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, role TEXT NOT NULL, salt BLOB NOT NULL, digest BLOB NOT NULL)",
    "CREATE TABLE IF NOT EXISTS combat_sessions (id TEXT PRIMARY KEY, state TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS compendium_monsters (slug TEXT PRIMARY KEY, name TEXT NOT NULL, cr TEXT NOT NULL, armor_class INTEGER NOT NULL, hit_points INTEGER NOT NULL, tags TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS compendium_items (slug TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, rarity TEXT NOT NULL, cost_gp INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, dm TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS play_campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL, status TEXT NOT NULL, max_players INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS play_campaign_spectators (spectator_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS play_campaign_session_zero (campaign_id TEXT PRIMARY KEY, rules TEXT NOT NULL, tone TEXT NOT NULL, consent TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS play_campaign_content (campaign_id TEXT NOT NULL, content_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, tags TEXT NOT NULL, PRIMARY KEY (campaign_id, content_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_search_records (campaign_id TEXT NOT NULL, record_id TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, record_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_rate_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, actor TEXT NOT NULL, PRIMARY KEY (campaign_id, event_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_metrics (campaign_id TEXT PRIMARY KEY, accepted_rate_events INTEGER NOT NULL, rejected_rate_events INTEGER NOT NULL, projection_events INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS play_campaign_notes (campaign_id TEXT NOT NULL, note_id TEXT NOT NULL, text TEXT NOT NULL, visibility TEXT NOT NULL, owner TEXT NOT NULL, PRIMARY KEY (campaign_id, note_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_whispers (campaign_id TEXT NOT NULL, whisper_id TEXT NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, whisper_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_members (campaign_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL, name TEXT NOT NULL, class TEXT NOT NULL, PRIMARY KEY (campaign_id, username), UNIQUE (campaign_id, character_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_invitations (campaign_id TEXT NOT NULL, invitation_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, invitation_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_delegations (campaign_id TEXT NOT NULL, username TEXT NOT NULL, powers TEXT NOT NULL, active INTEGER NOT NULL, PRIMARY KEY (campaign_id, username))",
    "CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, username TEXT NOT NULL, action TEXT NOT NULL, powers TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence))",
    "CREATE TABLE IF NOT EXISTS play_campaign_audit_events (campaign_id TEXT NOT NULL, timestamp INTEGER NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL, role TEXT NOT NULL, correlation_id TEXT NOT NULL, PRIMARY KEY (campaign_id, timestamp), UNIQUE (campaign_id, correlation_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_projection_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, value TEXT NOT NULL, idempotency_key TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id), UNIQUE (campaign_id, idempotency_key))",
    "CREATE TABLE IF NOT EXISTS play_campaign_feed_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_state (campaign_id TEXT PRIMARY KEY, current_turn INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (campaign_id TEXT NOT NULL, submission_id TEXT NOT NULL, action TEXT NOT NULL, accepted_turn INTEGER NOT NULL, next_turn INTEGER NOT NULL, PRIMARY KEY (campaign_id, submission_id), UNIQUE (campaign_id, accepted_turn))",
    "CREATE TABLE IF NOT EXISTS play_campaign_character_owners (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, owner TEXT, PRIMARY KEY (campaign_id, character_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_character_progression (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, class TEXT NOT NULL, con_modifier INTEGER NOT NULL, level INTEGER NOT NULL, hp_max INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_character_abilities (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, str INTEGER NOT NULL, dex INTEGER NOT NULL, con INTEGER NOT NULL, int INTEGER NOT NULL, wis INTEGER NOT NULL, cha INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_character_spells (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, spell_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_character_prepared_spells (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, spell_id), UNIQUE (campaign_id, character_id, sequence))",
    "CREATE TABLE IF NOT EXISTS play_campaign_character_casts (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, sequence INTEGER NOT NULL, spell_id TEXT NOT NULL, target TEXT NOT NULL, slot_level INTEGER NOT NULL, slots_remaining INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, sequence))",
    "CREATE TABLE IF NOT EXISTS play_campaign_character_concentrations (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, target TEXT NOT NULL, remaining_turns INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_character_inventory_items (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, item_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_recipes (campaign_id TEXT NOT NULL, recipe_id TEXT NOT NULL, name TEXT NOT NULL, ingredients TEXT NOT NULL, output_item TEXT NOT NULL, output_quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, recipe_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (campaign_id TEXT NOT NULL, activity_id TEXT NOT NULL, name TEXT NOT NULL, cycles_required INTEGER NOT NULL, PRIMARY KEY (campaign_id, activity_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_downtime_allocations (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, activity_id TEXT NOT NULL, cycles_completed INTEGER NOT NULL, completions INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, activity_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_character_equipment (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, slot TEXT NOT NULL, item_id TEXT NOT NULL, attuned INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, character_id, slot))",
    "CREATE TABLE IF NOT EXISTS play_campaign_character_currency (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, gold INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_currency_transfers (campaign_id TEXT NOT NULL, transfer_id INTEGER NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, gold INTEGER NOT NULL, PRIMARY KEY (campaign_id, transfer_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, amount INTEGER NOT NULL, from_gold INTEGER NOT NULL, to_gold INTEGER NOT NULL, PRIMARY KEY (campaign_id, sequence))",
    "CREATE TABLE IF NOT EXISTS play_campaign_loot (campaign_id TEXT NOT NULL, loot_id TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL, status TEXT NOT NULL, recipient_character_id TEXT, votes INTEGER NOT NULL, PRIMARY KEY (campaign_id, loot_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (campaign_id TEXT NOT NULL, loot_id TEXT NOT NULL, voter TEXT NOT NULL, recipient_character_id TEXT NOT NULL, PRIMARY KEY (campaign_id, loot_id, voter))",
    "CREATE TABLE IF NOT EXISTS play_campaign_npcs (campaign_id TEXT NOT NULL, npc_id TEXT NOT NULL, name TEXT NOT NULL, agenda TEXT NOT NULL, public_status TEXT NOT NULL, PRIMARY KEY (campaign_id, npc_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (campaign_id TEXT NOT NULL, npc_id TEXT NOT NULL, dialogue_id TEXT NOT NULL, sequence INTEGER NOT NULL, speaker TEXT NOT NULL, text TEXT NOT NULL, visibility TEXT NOT NULL, PRIMARY KEY (campaign_id, npc_id, dialogue_id), UNIQUE (campaign_id, npc_id, sequence))",
    "CREATE TABLE IF NOT EXISTS play_campaign_relationships (campaign_id TEXT NOT NULL, source_id TEXT NOT NULL, target_id TEXT NOT NULL, kind TEXT NOT NULL, score INTEGER NOT NULL, PRIMARY KEY (campaign_id, source_id, target_id, kind))",
    "CREATE TABLE IF NOT EXISTS play_campaign_clues (campaign_id TEXT NOT NULL, clue_id TEXT NOT NULL, text TEXT NOT NULL, audience TEXT NOT NULL, character_id TEXT, PRIMARY KEY (campaign_id, clue_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_quests (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, title TEXT NOT NULL, depends_on TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY (campaign_id, quest_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_quest_rewards (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, xp INTEGER NOT NULL, items TEXT NOT NULL, awarded INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, quest_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_character_quest_rewards (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, quest_id TEXT NOT NULL, xp INTEGER NOT NULL, items TEXT NOT NULL, PRIMARY KEY (campaign_id, character_id, quest_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_world_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, turn_number INTEGER NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL, resolution_turn_number INTEGER, resolution_text TEXT, PRIMARY KEY (campaign_id, event_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_calendars (campaign_id TEXT PRIMARY KEY, day INTEGER NOT NULL, season TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS play_campaign_factions (campaign_id TEXT NOT NULL, faction_id TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY (campaign_id, faction_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_faction_reputations (campaign_id TEXT NOT NULL, faction_id TEXT NOT NULL, character_id TEXT NOT NULL, reputation INTEGER NOT NULL, PRIMARY KEY (campaign_id, faction_id, character_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_faction_reputation_history (campaign_id TEXT NOT NULL, faction_id TEXT NOT NULL, sequence INTEGER NOT NULL, character_id TEXT NOT NULL, reputation INTEGER NOT NULL, delta INTEGER NOT NULL, reason TEXT NOT NULL, PRIMARY KEY (campaign_id, faction_id, sequence))",
    "CREATE TABLE IF NOT EXISTS play_campaign_health (campaign_id TEXT NOT NULL, username TEXT NOT NULL, hp_current INTEGER NOT NULL, hp_max INTEGER NOT NULL, PRIMARY KEY (campaign_id, username))",
    "CREATE TABLE IF NOT EXISTS play_campaign_death_saves (campaign_id TEXT NOT NULL, username TEXT NOT NULL, successes INTEGER NOT NULL, failures INTEGER NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, username))",
    "CREATE TABLE IF NOT EXISTS play_campaign_narrations (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, actor TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence))",
    "CREATE TABLE IF NOT EXISTS play_campaign_actions (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, actor TEXT NOT NULL, type TEXT NOT NULL, target TEXT, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence))",
    "CREATE TABLE IF NOT EXISTS play_campaign_nudges (campaign_id TEXT NOT NULL, nudge_count INTEGER NOT NULL, actor TEXT NOT NULL, target TEXT NOT NULL, message TEXT NOT NULL, PRIMARY KEY (campaign_id, nudge_count))",
    "CREATE TABLE IF NOT EXISTS play_campaign_documents (campaign_id TEXT PRIMARY KEY, story TEXT NOT NULL, dm_notes TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS play_campaign_replay_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_rng_seeds (campaign_id TEXT PRIMARY KEY, seed TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, roll_id TEXT NOT NULL, sides INTEGER NOT NULL, result INTEGER NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, roll_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, report_id TEXT NOT NULL, target_id TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL, reporter TEXT NOT NULL, action TEXT, note TEXT, resolver TEXT, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, report_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries (campaign_id TEXT PRIMARY KEY, blocked_tags TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS play_campaign_safety_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, tags TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_fixture_seeds (campaign_id TEXT PRIMARY KEY, fixture_id TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS play_campaign_backups (campaign_id TEXT NOT NULL, backup_id TEXT NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, backup_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_exports (campaign_id TEXT NOT NULL, version INTEGER NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, version))",
    "CREATE TABLE IF NOT EXISTS play_campaign_import_state (campaign_id TEXT PRIMARY KEY, version INTEGER NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS play_campaign_migration_state (campaign_id TEXT PRIMARY KEY, source_schema_version INTEGER NOT NULL, source_story TEXT NOT NULL, schema_version INTEGER NOT NULL, story TEXT NOT NULL, campaign_name TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS play_campaign_scenes (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_scene_state (campaign_id TEXT PRIMARY KEY, current_scene_id TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS play_campaign_locations (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY (campaign_id, id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_settlements (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, name TEXT NOT NULL, services TEXT NOT NULL, availability TEXT NOT NULL, PRIMARY KEY (campaign_id, settlement_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_settlement_discoveries (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, character_id TEXT NOT NULL, PRIMARY KEY (campaign_id, settlement_id, character_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_shops (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, shop_id TEXT NOT NULL, name TEXT NOT NULL, stock TEXT NOT NULL, buy_price INTEGER NOT NULL, sell_price INTEGER NOT NULL, PRIMARY KEY (campaign_id, settlement_id, shop_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_location_connections (campaign_id TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL, travel_turns INTEGER NOT NULL, PRIMARY KEY (campaign_id, from_id, to_id))",
    "CREATE TABLE IF NOT EXISTS play_campaign_location_state (campaign_id TEXT PRIMARY KEY, current_location_id TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS play_campaign_encounters (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, status TEXT NOT NULL, combatants TEXT NOT NULL, round INTEGER NOT NULL DEFAULT 1, turn_index INTEGER NOT NULL DEFAULT 0, conditions TEXT NOT NULL DEFAULT '{}')",
    "CREATE TABLE IF NOT EXISTS play_campaign_encounter_rewards (encounter_id TEXT PRIMARY KEY, xp INTEGER NOT NULL, loot TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS campaign_characters (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL, class TEXT NOT NULL, PRIMARY KEY (campaign_id, id))",
    "CREATE TABLE IF NOT EXISTS campaign_events (campaign_id TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL, summary TEXT NOT NULL, PRIMARY KEY (campaign_id, id))",
    "CREATE TABLE IF NOT EXISTS campaign_quests (campaign_id TEXT NOT NULL, id TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, milestones TEXT NOT NULL, completed TEXT NOT NULL, PRIMARY KEY (campaign_id, id))",
    "CREATE TABLE IF NOT EXISTS campaign_factions (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, stance TEXT NOT NULL, PRIMARY KEY (campaign_id, id))",
    "CREATE TABLE IF NOT EXISTS campaign_npcs (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, faction_id TEXT NOT NULL, disposition INTEGER NOT NULL, PRIMARY KEY (campaign_id, id))",
    "CREATE TABLE IF NOT EXISTS campaign_inventory (campaign_id TEXT NOT NULL, item_slug TEXT NOT NULL, quantity INTEGER NOT NULL, owner TEXT NOT NULL, PRIMARY KEY (campaign_id, item_slug, owner))",
    "CREATE TABLE IF NOT EXISTS campaign_equipment (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, item_slug))",
    "CREATE TABLE IF NOT EXISTS campaign_crafting_projects (campaign_id TEXT NOT NULL, id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, days_required INTEGER NOT NULL, days_completed INTEGER NOT NULL, cost_gp INTEGER NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, id))",
    "CREATE TABLE IF NOT EXISTS campaign_sessions (campaign_id TEXT NOT NULL, id TEXT NOT NULL, starts_at TEXT NOT NULL, duration_minutes INTEGER NOT NULL, agenda TEXT NOT NULL, PRIMARY KEY (campaign_id, id))",
    "CREATE TABLE IF NOT EXISTS campaign_session_attendance (campaign_id TEXT NOT NULL, session_id TEXT NOT NULL, character_id TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, session_id, character_id))",
)
# Reset order is explicit because SQLite has no dependency-aware schema reset.
# Keep child tables before the records they reference so this remains safe if
# foreign-key enforcement is enabled in a future connection configuration.
RESET_TABLES = (
    "play_campaign_migration_state", "play_campaign_import_state", "play_campaign_exports", "play_campaign_backups", "play_campaign_safety_events", "play_campaign_safety_boundaries", "play_campaign_fixture_seeds", "play_campaign_moderation_reports", "play_campaign_rng_rolls", "play_campaign_rng_seeds", "play_campaign_replay_events",
    "play_campaign_faction_reputation_history", "play_campaign_faction_reputations", "play_campaign_factions", "play_campaign_character_quest_rewards", "play_campaign_quest_rewards", "play_campaign_quests", "play_campaign_world_events", "play_campaign_calendars", "play_campaign_clues", "play_campaign_relationships", "play_campaign_npc_dialogue", "play_campaign_npcs", "play_campaign_loot_votes", "play_campaign_loot", "play_campaign_transactional_transfers", "play_campaign_currency_transfers", "play_campaign_character_currency", "play_campaign_character_equipment", "play_campaign_character_inventory_items", "play_campaign_downtime_allocations", "play_campaign_downtime_activities", "play_campaign_recipes", "play_campaign_character_concentrations", "play_campaign_character_casts", "play_campaign_character_prepared_spells", "play_campaign_character_spells", "play_campaign_character_abilities", "play_campaign_character_progression",
    "play_campaign_character_owners", "play_campaign_death_saves",
    "play_campaign_encounter_rewards", "play_campaign_encounters",
    "play_campaign_location_state", "play_campaign_location_connections",
    "play_campaign_locations", "play_campaign_shops", "play_campaign_settlement_discoveries",
    "play_campaign_settlements", "play_campaign_scene_state", "play_campaign_scenes",
    "play_campaign_documents", "play_campaign_nudges", "play_campaign_actions",
    "play_campaign_narrations", "play_campaign_health", "play_campaign_safe_turns", "play_campaign_safe_turn_state", "play_campaign_idempotent_events", "play_campaign_projection_events", "play_campaign_feed_events", "play_campaign_audit_events", "play_campaign_delegation_audit", "play_campaign_delegations", "play_campaign_invitations", "play_campaign_members",
    "play_campaign_whispers", "play_campaign_notes", "play_campaign_spectators", "play_campaign_metrics", "play_campaign_rate_events", "play_campaign_search_records", "play_campaign_content", "play_campaign_session_zero",
    "play_campaigns", "campaign_session_attendance", "campaign_sessions",
    "campaign_crafting_projects", "campaign_equipment", "campaign_inventory",
    "campaign_npcs", "campaign_factions", "campaign_quests", "campaign_events",
    "campaign_characters", "campaigns", "combat_sessions", "users",
    "compendium_monsters", "compendium_items", "storage_metadata",
)


class BadRequest(Exception):
    pass


class DuplicateUser(Exception):
    pass


class DuplicateSlug(Exception):
    pass


class DuplicateRecord(Exception):
    pass


class SeedAlreadyConfigured(Exception):
    pass


class OutOfTurn(Exception):
    pass


class NoSpellSlots(Exception):
    pass


class InsufficientInventory(Exception):
    pass


class InsufficientGold(Exception):
    pass


class SimulatedFailure(Exception):
    pass


class InsufficientStock(Exception):
    pass


class AttunementLimitReached(Exception):
    pass


class RateLimitReached(Exception):
    pass


def database():
    return sqlite3.connect(DATABASE_PATH)


def initialize_storage():
    """Create the version-one durable store if it has not been created yet."""
    with DATABASE_LOCK, database() as connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        encounter_columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(play_campaign_encounters)"
        )}
        if "round" not in encounter_columns:
            connection.execute(
                "ALTER TABLE play_campaign_encounters ADD COLUMN round INTEGER NOT NULL DEFAULT 1"
            )
        if "turn_index" not in encounter_columns:
            connection.execute(
                "ALTER TABLE play_campaign_encounters ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0"
            )
        if "conditions" not in encounter_columns:
            connection.execute(
                "ALTER TABLE play_campaign_encounters ADD COLUMN conditions TEXT NOT NULL DEFAULT '{}'"
            )
        action_columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(play_campaign_actions)"
        )}
        if "target" not in action_columns:
            connection.execute("ALTER TABLE play_campaign_actions ADD COLUMN target TEXT")
        narration_columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(play_campaign_narrations)"
        )}
        if "actor" not in narration_columns:
            connection.execute(
                "ALTER TABLE play_campaign_narrations "
                "ADD COLUMN actor TEXT NOT NULL DEFAULT 'dm'"
            )
        cast_columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(play_campaign_character_casts)"
        )}
        if "slots_remaining" not in cast_columns:
            connection.execute(
                "ALTER TABLE play_campaign_character_casts "
                "ADD COLUMN slots_remaining INTEGER NOT NULL DEFAULT 0"
            )
        connection.execute(
            "INSERT OR IGNORE INTO play_campaign_death_saves "
            "(campaign_id, username, successes, failures, status) "
            "SELECT campaign_id, username, 0, 0, 'conscious' FROM play_campaign_health"
        )
        # Members created before character ownership was introduced owned the
        # character they joined with.  Preserve that established relationship.
        connection.execute(
            "INSERT OR IGNORE INTO play_campaign_character_owners "
            "(campaign_id, character_id, owner) "
            "SELECT campaign_id, character_id, username FROM play_campaign_members"
        )
        # Currency was added after campaign membership.  Existing members get
        # the same deterministic starting balance as newly joined members.
        connection.execute(
            "INSERT OR IGNORE INTO play_campaign_character_currency "
            "(campaign_id, character_id, gold) "
            "SELECT campaign_id, character_id, 10 FROM play_campaign_members"
        )
        # Campaigns created before service metrics was introduced retain their
        # already accepted event totals; rejected events had no earlier record.
        connection.execute(
            "INSERT OR IGNORE INTO play_campaign_metrics "
            "(campaign_id, accepted_rate_events, rejected_rate_events, projection_events) "
            "SELECT c.id, "
            "(SELECT COUNT(*) FROM play_campaign_rate_events r WHERE r.campaign_id = c.id), "
            "0, "
            "(SELECT COUNT(*) FROM play_campaign_projection_events p WHERE p.campaign_id = c.id) "
            "FROM play_campaigns c"
        )
        connection.execute("DELETE FROM storage_metadata")
        connection.execute("INSERT INTO storage_metadata (schema_version) VALUES (1)")


def storage_initialized():
    try:
        with database() as connection:
            row = connection.execute(
                "SELECT schema_version FROM storage_metadata LIMIT 1"
            ).fetchone()
        return row == (1,)
    except sqlite3.Error:
        return False


def reset_storage():
    with DATABASE_LOCK, database() as connection:
        for table in RESET_TABLES:
            connection.execute(f"DROP TABLE IF EXISTS {table}")
    initialize_storage()


def integer(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise BadRequest()
    return value


def campaign_text(value):
    if not isinstance(value, str) or not value:
        raise BadRequest()
    return value


def create_campaign(data):
    if not isinstance(data, dict):
        raise BadRequest()
    campaign = {key: campaign_text(data.get(key)) for key in ("id", "name", "dm")}
    try:
        with DATABASE_LOCK, database() as connection:
            connection.execute(
                "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
                (campaign["id"], campaign["name"], campaign["dm"]),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return campaign


def add_campaign_character(campaign_id, data):
    if not isinstance(data, dict):
        raise BadRequest()
    character = {key: campaign_text(data.get(key)) for key in ("id", "name", "class")}
    character["level"] = integer(data.get("level"))
    if character["level"] < 1:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        exists = connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if exists is None:
            return None
        try:
            connection.execute(
                "INSERT INTO campaign_characters (campaign_id, id, name, level, class) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, character["id"], character["name"], character["level"], character["class"]),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    return character


def add_campaign_event(campaign_id, data):
    if not isinstance(data, dict):
        raise BadRequest()
    event = {key: campaign_text(data.get(key)) for key in ("id", "kind", "summary")}
    with DATABASE_LOCK, database() as connection:
        exists = connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if exists is None:
            return None
        try:
            connection.execute(
                "INSERT INTO campaign_events (campaign_id, id, kind, summary) VALUES (?, ?, ?, ?)",
                (campaign_id, event["id"], event["kind"], event["summary"]),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    return {"id": event["id"], "kind": event["kind"]}


def campaign_state(campaign_id):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT id, name, dm FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        characters = connection.execute(
            "SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
        log_count = connection.execute(
            "SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
    return {
        "id": campaign[0], "name": campaign[1], "dm": campaign[2],
        "characters": [{"id": row[0], "name": row[1], "level": row[2], "class": row[3]}
                       for row in characters],
        "log_count": log_count,
    }


def campaign_audit(campaign_id):
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
            "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        events, quests, npcs, sessions = (
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()[0]
            for table in ("campaign_events", "campaign_quests", "campaign_npcs", "campaign_sessions")
        )
    return {"campaign_id": campaign_id, "events": events, "quests": quests,
            "npcs": npcs, "sessions": sessions}


def campaign_export(campaign_id):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT name FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        characters, quests, npcs, inventory_items, sessions = (
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()[0]
            for table in ("campaign_characters", "campaign_quests", "campaign_npcs",
                          "campaign_inventory", "campaign_sessions")
        )
    return {"campaign_id": campaign_id, "name": campaign[0],
            "characters": characters, "quests": quests, "npcs": npcs,
            "inventory_items": inventory_items, "sessions": sessions,
            "schema_version": 1}


def campaign_analytics_summary(campaign_id):
    """Return the stable readiness aggregates for one campaign."""
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
            "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        open_quests = connection.execute(
            "SELECT COUNT(*) FROM campaign_quests "
            "WHERE campaign_id = ? AND status != 'completed'", (campaign_id,)
        ).fetchone()[0]
        friendly_npcs = connection.execute(
            "SELECT COUNT(*) FROM campaign_npcs "
            "WHERE campaign_id = ? AND disposition > 0", (campaign_id,)
        ).fetchone()[0]
        scheduled_sessions = connection.execute(
            "SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        inventory_items = connection.execute(
            "SELECT COUNT(*) FROM campaign_inventory "
            "WHERE campaign_id = ? AND owner = 'party' AND quantity > 0", (campaign_id,)
        ).fetchone()[0]
    readiness_score = min(
        100,
        open_quests * 20 + friendly_npcs * 15
        + scheduled_sessions * 25 + inventory_items * 25,
    )
    return {"campaign_id": campaign_id, "readiness_score": readiness_score,
            "open_quests": open_quests, "friendly_npcs": friendly_npcs,
            "scheduled_sessions": scheduled_sessions,
            "inventory_items": inventory_items}


def campaign_risk_report(campaign_id, data):
    if not isinstance(data, dict) or not isinstance(data.get("include_zeroes"), bool):
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT dm FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        has_characters = connection.execute(
            "SELECT 1 FROM campaign_characters WHERE campaign_id = ? LIMIT 1", (campaign_id,)
        ).fetchone() is not None
        has_next_session = connection.execute(
            "SELECT 1 FROM campaign_sessions WHERE campaign_id = ? LIMIT 1", (campaign_id,)
        ).fetchone() is not None
        has_active_quest = connection.execute(
            "SELECT 1 FROM campaign_quests WHERE campaign_id = ? AND status = 'active' LIMIT 1",
            (campaign_id,),
        ).fetchone() is not None
    signals = {"has_dm": bool(campaign[0]), "has_characters": has_characters,
               "has_next_session": has_next_session, "has_active_quest": has_active_quest}
    missing = [name[4:] for name, present in signals.items() if not present]
    risk_level = "low" if not missing else "medium" if len(missing) <= 2 else "high"
    return {"campaign_id": campaign_id, "risk_level": risk_level,
            "missing": missing, "signals": signals}


def session_agenda(value):
    if (not isinstance(value, list)
            or any(not isinstance(item, str) or not item for item in value)):
        raise BadRequest()
    return value


def session_start_time(value):
    value = campaign_text(value)
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise BadRequest()
    return value


def schedule_campaign_session(campaign_id, data):
    if not isinstance(data, dict):
        raise BadRequest()
    session = {"id": campaign_text(data.get("id")),
               "starts_at": session_start_time(data.get("starts_at"))}
    session["duration_minutes"] = integer(data.get("duration_minutes"))
    session["agenda"] = session_agenda(data.get("agenda"))
    if session["duration_minutes"] <= 0:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        if connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone() is None:
            return None
        try:
            connection.execute(
                "INSERT INTO campaign_sessions (campaign_id, id, starts_at, duration_minutes, agenda) "
                "VALUES (?, ?, ?, ?, ?)",
                (campaign_id, session["id"], session["starts_at"], session["duration_minutes"],
                 json.dumps(session["agenda"], separators=(",", ":"))),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    return {"id": session["id"], "starts_at": session["starts_at"],
            "duration_minutes": session["duration_minutes"],
            "agenda_count": len(session["agenda"])}


def attendance_ids(value):
    if (not isinstance(value, list)
            or any(not isinstance(item, str) or not item for item in value)
            or len(set(value)) != len(value)):
        raise BadRequest()
    return value


def record_session_attendance(campaign_id, session_id, data):
    if not isinstance(data, dict):
        raise BadRequest()
    present, absent = attendance_ids(data.get("present")), attendance_ids(data.get("absent"))
    if set(present) & set(absent):
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        if connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone() is None:
            return None
        if connection.execute(
            "SELECT 1 FROM campaign_sessions WHERE campaign_id = ? AND id = ?",
            (campaign_id, session_id),
        ).fetchone() is None:
            return None
        character_ids = {row[0] for row in connection.execute(
            "SELECT id FROM campaign_characters WHERE campaign_id = ?", (campaign_id,)
        )}
        if any(character_id not in character_ids for character_id in present + absent):
            raise BadRequest()
        connection.execute(
            "DELETE FROM campaign_session_attendance WHERE campaign_id = ? AND session_id = ?",
            (campaign_id, session_id),
        )
        connection.executemany(
            "INSERT INTO campaign_session_attendance (campaign_id, session_id, character_id, status) "
            "VALUES (?, ?, ?, ?)",
            [(campaign_id, session_id, character_id, "present") for character_id in present]
            + [(campaign_id, session_id, character_id, "absent") for character_id in absent],
        )
    return {"session_id": session_id, "present_count": len(present), "absent_count": len(absent)}


def next_campaign_session(campaign_id):
    with DATABASE_LOCK, database() as connection:
        if connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone() is None:
            return None
        session = connection.execute(
            "SELECT id, starts_at, agenda FROM campaign_sessions WHERE campaign_id = ? "
            "ORDER BY starts_at, rowid LIMIT 1",
            (campaign_id,),
        ).fetchone()
    if session is None:
        return None
    return {"id": session[0], "starts_at": session[1], "agenda_count": len(json.loads(session[2]))}


def quest_milestones(value):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise BadRequest()
    if len(set(value)) != len(value):
        raise BadRequest()
    return value


def create_campaign_quest(campaign_id, data):
    if not isinstance(data, dict):
        raise BadRequest()
    quest = {key: campaign_text(data.get(key)) for key in ("id", "title", "status")}
    if quest["status"] not in ("active", "completed", "blocked"):
        raise BadRequest()
    milestones = quest_milestones(data.get("milestones"))
    with DATABASE_LOCK, database() as connection:
        exists = connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if exists is None:
            return None
        try:
            connection.execute(
                "INSERT INTO campaign_quests (campaign_id, id, title, status, milestones, completed) VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, quest["id"], quest["title"], quest["status"],
                 json.dumps(milestones, separators=(",", ":")), "[]"),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    return {"id": quest["id"], "title": quest["title"], "status": quest["status"],
            "milestones_total": len(milestones), "milestones_done": 0}


def update_quest_progress(campaign_id, quest_id, data):
    if not isinstance(data, dict):
        raise BadRequest()
    completed = quest_milestones(data.get("completed"))
    with DATABASE_LOCK, database() as connection:
        row = connection.execute(
            "SELECT status, milestones, completed FROM campaign_quests WHERE campaign_id = ? AND id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if row is None:
            return None
        milestones, prior_completed = json.loads(row[1]), json.loads(row[2])
        if any(item not in milestones for item in completed):
            raise BadRequest()
        done = prior_completed + [item for item in completed if item not in prior_completed]
        status = "completed" if row[0] == "active" and milestones and len(done) == len(milestones) else row[0]
        connection.execute(
            "UPDATE campaign_quests SET status = ?, completed = ? WHERE campaign_id = ? AND id = ?",
            (status, json.dumps(done, separators=(",", ":")), campaign_id, quest_id),
        )
    return {"id": quest_id, "status": status,
            "milestones_total": len(milestones), "milestones_done": len(done)}


def quest_summary(campaign_id):
    with DATABASE_LOCK, database() as connection:
        if connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone() is None:
            return None
        counts = dict(connection.execute(
            "SELECT status, COUNT(*) FROM campaign_quests WHERE campaign_id = ? GROUP BY status",
            (campaign_id,),
        ).fetchall())
    return {"campaign_id": campaign_id, "active": counts.get("active", 0),
            "completed": counts.get("completed", 0), "blocked": counts.get("blocked", 0)}


def create_campaign_faction(campaign_id, data):
    if not isinstance(data, dict):
        raise BadRequest()
    faction = {key: campaign_text(data.get(key)) for key in ("id", "name", "stance")}
    if faction["stance"] not in ("friendly", "neutral", "hostile"):
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        if connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone() is None:
            return None
        try:
            connection.execute(
                "INSERT INTO campaign_factions (campaign_id, id, name, stance) VALUES (?, ?, ?, ?)",
                (campaign_id, faction["id"], faction["name"], faction["stance"]),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    return faction


def create_campaign_npc(campaign_id, data):
    if not isinstance(data, dict):
        raise BadRequest()
    npc = {key: campaign_text(data.get(key)) for key in ("id", "name", "faction_id")}
    npc["disposition"] = integer(data.get("disposition"))
    with DATABASE_LOCK, database() as connection:
        if connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone() is None:
            return None
        if connection.execute(
            "SELECT 1 FROM campaign_factions WHERE campaign_id = ? AND id = ?",
            (campaign_id, npc["faction_id"]),
        ).fetchone() is None:
            raise BadRequest()
        try:
            connection.execute(
                "INSERT INTO campaign_npcs (campaign_id, id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, npc["id"], npc["name"], npc["faction_id"], npc["disposition"]),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    return npc


def relationship_summary(campaign_id):
    with DATABASE_LOCK, database() as connection:
        if connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone() is None:
            return None
        factions = connection.execute(
            "SELECT COUNT(*) FROM campaign_factions WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        npcs, friendly_npcs = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(disposition > 0), 0) FROM campaign_npcs WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    return {"campaign_id": campaign_id, "factions": factions, "npcs": npcs,
            "friendly_npcs": friendly_npcs}


def add_inventory_item(campaign_id, data):
    if not isinstance(data, dict):
        raise BadRequest()
    item_slug = compendium_slug(data.get("item_slug"))
    quantity = integer(data.get("quantity"))
    owner = data.get("owner")
    if quantity <= 0 or owner != "party":
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        if connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone() is None:
            return None
        try:
            connection.execute(
                "INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?)",
                (campaign_id, item_slug, quantity, owner),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    return {"item_slug": item_slug, "quantity": quantity, "owner": owner}


def assign_equipment(campaign_id, character_id, data):
    if not isinstance(data, dict):
        raise BadRequest()
    item_slug = compendium_slug(data.get("item_slug"))
    quantity = integer(data.get("quantity"))
    if quantity <= 0:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        if connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone() is None:
            return None
        if connection.execute(
            "SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?",
            (campaign_id, character_id),
        ).fetchone() is None:
            return None
        inventory = connection.execute(
            "SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'",
            (campaign_id, item_slug),
        ).fetchone()
        if inventory is None or inventory[0] < quantity:
            raise BadRequest()
        connection.execute(
            "UPDATE campaign_inventory SET quantity = quantity - ? WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'",
            (quantity, campaign_id, item_slug),
        )
        connection.execute(
            "INSERT INTO campaign_equipment (campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, character_id, item_slug) DO UPDATE SET quantity = quantity + excluded.quantity",
            (campaign_id, character_id, item_slug, quantity),
        )
    return {"character_id": character_id, "item_slug": item_slug, "quantity": quantity}


def inventory_summary(campaign_id):
    with DATABASE_LOCK, database() as connection:
        if connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone() is None:
            return None
        party_items = connection.execute(
            "SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party'", (campaign_id,)
        ).fetchone()[0]
        assigned_items = connection.execute(
            "SELECT COUNT(*) FROM campaign_equipment WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        healing_potions_available = connection.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM campaign_inventory "
            "WHERE campaign_id = ? AND owner = 'party' AND item_slug = 'healing-potion'",
            (campaign_id,),
        ).fetchone()[0]
    return {"campaign_id": campaign_id, "party_items": party_items,
            "assigned_items": assigned_items,
            "healing_potions_available": healing_potions_available}


def create_crafting_project(campaign_id, data):
    if not isinstance(data, dict):
        raise BadRequest()
    project = {key: campaign_text(data.get(key))
               for key in ("id", "character_id")}
    project["item_slug"] = compendium_slug(data.get("item_slug"))
    project["days_required"] = integer(data.get("days_required"))
    cost_gp = integer(data.get("cost_gp"))
    if project["days_required"] <= 0 or cost_gp < 0:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        if connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone() is None:
            return None
        if connection.execute(
            "SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?",
            (campaign_id, project["character_id"]),
        ).fetchone() is None:
            raise BadRequest()
        try:
            connection.execute(
                "INSERT INTO campaign_crafting_projects "
                "(campaign_id, id, character_id, item_slug, days_required, days_completed, cost_gp, status) "
                "VALUES (?, ?, ?, ?, ?, 0, ?, 'active')",
                (campaign_id, project["id"], project["character_id"], project["item_slug"],
                 project["days_required"], cost_gp),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    return {"id": project["id"], "character_id": project["character_id"],
            "item_slug": project["item_slug"], "days_required": project["days_required"],
            "days_completed": 0, "status": "active"}


def advance_crafting_project(campaign_id, project_id, data):
    if not isinstance(data, dict):
        raise BadRequest()
    days = integer(data.get("days"))
    if days <= 0:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        project = connection.execute(
            "SELECT item_slug, days_required, days_completed, status "
            "FROM campaign_crafting_projects WHERE campaign_id = ? AND id = ?",
            (campaign_id, project_id),
        ).fetchone()
        if project is None:
            return None
        if project[3] != "active":
            raise BadRequest()
        days_completed = min(project[1], project[2] + days)
        status = "complete" if days_completed == project[1] else "active"
        connection.execute(
            "UPDATE campaign_crafting_projects SET days_completed = ?, status = ? "
            "WHERE campaign_id = ? AND id = ?",
            (days_completed, status, campaign_id, project_id),
        )
        if status == "complete":
            connection.execute(
                "INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, 1, 'party') "
                "ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + 1",
                (campaign_id, project[0]),
            )
    return {"id": project_id, "days_completed": days_completed, "status": status}


def compendium_text(value):
    if not isinstance(value, str) or not value:
        raise BadRequest()
    return value


def compendium_slug(value):
    value = compendium_text(value)
    if "/" in value:
        raise BadRequest()
    return value


def create_monster(data):
    if not isinstance(data, dict):
        raise BadRequest()
    slug = compendium_slug(data.get("slug"))
    name, cr = compendium_text(data.get("name")), compendium_text(data.get("cr"))
    armor_class, hit_points = integer(data.get("armor_class")), integer(data.get("hit_points"))
    tags = data.get("tags")
    if armor_class < 0 or hit_points < 0 or not isinstance(tags, list) or any(
            not isinstance(tag, str) or not tag for tag in tags):
        raise BadRequest()
    try:
        with DATABASE_LOCK, database() as connection:
            connection.execute(
                "INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)",
                (slug, name, cr, armor_class, hit_points, json.dumps(tags, separators=(",", ":"))),
            )
    except sqlite3.IntegrityError:
        raise DuplicateSlug()
    return {"slug": slug, "name": name, "cr": cr,
            "armor_class": armor_class, "hit_points": hit_points}


def get_monster(slug):
    with DATABASE_LOCK, database() as connection:
        row = connection.execute(
            "SELECT slug, name, cr, armor_class, hit_points, tags FROM compendium_monsters WHERE slug = ?",
            (slug,),
        ).fetchone()
    if row is None:
        return None
    return {"slug": row[0], "name": row[1], "cr": row[2], "armor_class": row[3],
            "hit_points": row[4], "tags": json.loads(row[5])}


def create_item(data):
    if not isinstance(data, dict):
        raise BadRequest()
    slug = compendium_slug(data.get("slug"))
    name, item_type, rarity = (compendium_text(data.get("name")),
                               compendium_text(data.get("type")),
                               compendium_text(data.get("rarity")))
    cost_gp = integer(data.get("cost_gp"))
    if cost_gp < 0:
        raise BadRequest()
    try:
        with DATABASE_LOCK, database() as connection:
            connection.execute(
                "INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
                (slug, name, item_type, rarity, cost_gp),
            )
    except sqlite3.IntegrityError:
        raise DuplicateSlug()
    return {"slug": slug, "name": name, "type": item_type,
            "rarity": rarity, "cost_gp": cost_gp}


def get_item(slug):
    with DATABASE_LOCK, database() as connection:
        row = connection.execute(
            "SELECT slug, name, type, rarity, cost_gp FROM compendium_items WHERE slug = ?",
            (slug,),
        ).fetchone()
    if row is None:
        return None
    return {"slug": row[0], "name": row[1], "type": row[2],
            "rarity": row[3], "cost_gp": row[4]}


def password_hash(password, salt=None):
    """Return a salted stdlib scrypt hash; passwords are never retained."""
    if salt is None:
        salt = os.urandom(16)
    return salt, hashlib.scrypt(password.encode("utf-8"), salt=salt,
                                 n=2**14, r=8, p=1)


def auth_registration(data):
    if not isinstance(data, dict):
        raise BadRequest()
    username, password, role = data.get("username"), data.get("password"), data.get("role")
    if (not isinstance(username, str) or not USERNAME.fullmatch(username)
            or not isinstance(password, str) or len(password) < 8
            or role not in ("dm", "player")):
        raise BadRequest()
    salt, digest = password_hash(password)
    try:
        with DATABASE_LOCK, database() as connection:
            connection.execute(
                "INSERT INTO users (username, role, salt, digest) VALUES (?, ?, ?, ?)",
                (username, role, salt, digest),
            )
    except sqlite3.IntegrityError:
        raise DuplicateUser()
    return {"username": username, "role": role}


def auth_login(data):
    if not isinstance(data, dict):
        raise BadRequest()
    username, password = data.get("username"), data.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        user = connection.execute(
            "SELECT salt, digest FROM users WHERE username = ?", (username,)
        ).fetchone()
    if user is not None:
        _, digest = password_hash(password, user[0])
        valid = hmac.compare_digest(digest, user[1])
    else:
        valid = False
    if not valid:
        return None
    return {"username": username, "token": f"session-{username}"}


def authenticated_user(authorization):
    """Return the current user for a valid deterministic session token."""
    if not isinstance(authorization, str) or not authorization.startswith("Bearer session-"):
        return None
    username = authorization.removeprefix("Bearer session-")
    if not USERNAME.fullmatch(username):
        return None
    with DATABASE_LOCK, database() as connection:
        row = connection.execute(
            "SELECT username, role FROM users WHERE username = ?", (username,)
        ).fetchone()
    if row is not None:
        return {"username": row[0], "role": row[1]}
    # Play credentials intentionally remain valid after storage reset.  A
    # well-formed deterministic identity is a DM only for the reserved DM
    # username; every other identity is a player and will be membership-checked
    # by the play route.
    return {"username": username, "role": "dm" if username == "dm" else "player"}


def create_play_campaign(owner, data):
    if not isinstance(data, dict):
        raise BadRequest()
    campaign = {key: campaign_text(data.get(key)) for key in ("id", "name")}
    campaign["max_players"] = integer(data.get("max_players"))
    if campaign["max_players"] < 1:
        raise BadRequest()
    try:
        with DATABASE_LOCK, database() as connection:
            connection.execute(
                "INSERT INTO play_campaigns (id, name, owner, status, max_players) "
                "VALUES (?, ?, ?, 'lobby', ?)",
                (campaign["id"], campaign["name"], owner, campaign["max_players"]),
            )
            connection.execute(
                "INSERT INTO play_campaign_metrics "
                "(campaign_id, accepted_rate_events, rejected_rate_events, projection_events) "
                "VALUES (?, 0, 0, 0)",
                (campaign["id"],),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return {"id": campaign["id"], "name": campaign["name"], "owner": owner,
            "status": "lobby", "max_players": campaign["max_players"]}


def create_play_campaign_spectator(campaign_id, owner, data):
    """Issue a globally unique, deterministic bearer ticket for one campaign."""
    if not isinstance(data, dict):
        raise BadRequest()
    spectator_id = data.get("spectator_id")
    if not isinstance(spectator_id, str) or not spectator_id:
        raise BadRequest()
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] != owner:
                raise PermissionError()
            connection.execute(
                "INSERT INTO play_campaign_spectators (spectator_id, campaign_id) VALUES (?, ?)",
                (spectator_id, campaign_id),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return {"spectator_id": spectator_id, "token": f"spectator-{spectator_id}"}


def spectator_ticket(authorization):
    """Return a spectator ID only for the dedicated spectator bearer format."""
    if not isinstance(authorization, str) or not authorization.startswith("Bearer spectator-"):
        return None
    spectator_id = authorization.removeprefix("Bearer spectator-")
    return spectator_id if spectator_id else None


def get_play_campaign_spectator_view(campaign_id, spectator_id):
    """Return the deliberately minimal, read-only spectator projection."""
    with DATABASE_LOCK, database() as connection:
        ticket = connection.execute(
            "SELECT campaign_id FROM play_campaign_spectators WHERE spectator_id = ?",
            (spectator_id,),
        ).fetchone()
        if ticket is None:
            raise LookupError()
        campaign = connection.execute(
            "SELECT name, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if ticket[0] != campaign_id:
            raise PermissionError()
        party_size = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        document = connection.execute(
            "SELECT story FROM play_campaign_documents WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
    return {"campaign_id": campaign_id, "name": campaign[0], "status": campaign[1],
            "party_size": party_size, "story": "" if document is None else document[0]}


def session_zero_settings(data):
    """Validate the complete, order-preserving session-zero settings object."""
    if not isinstance(data, dict) or set(data) != {"rules", "tone", "consent"}:
        raise BadRequest()
    settings = {key: campaign_text(data.get(key)) for key in ("rules", "tone")}
    consent = data.get("consent")
    if (not isinstance(consent, list) or not consent
            or any(not isinstance(item, str) or not item for item in consent)
            or len(set(consent)) != len(consent)):
        raise BadRequest()
    settings["consent"] = consent
    return settings


def update_play_campaign_session_zero(campaign_id, owner, data):
    settings = session_zero_settings(data)
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        if campaign[1] != "lobby":
            raise DuplicateRecord()
        connection.execute(
            "INSERT INTO play_campaign_session_zero (campaign_id, rules, tone, consent) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET "
            "rules = excluded.rules, tone = excluded.tone, consent = excluded.consent",
            (campaign_id, settings["rules"], settings["tone"],
             json.dumps(settings["consent"], separators=(",", ":"))),
        )
    return settings


def get_play_campaign_session_zero(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != username and connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        settings = connection.execute(
            "SELECT rules, tone, consent FROM play_campaign_session_zero WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    if settings is None:
        return None
    return {"rules": settings[0], "tone": settings[1], "consent": json.loads(settings[2])}


def content_tags(value, required):
    """Validate order-preserving content tags for create or replacement."""
    if (not isinstance(value, list) or (required and not value)
            or any(not isinstance(tag, str) or not tag for tag in value)
            or len(set(value)) != len(value)):
        raise BadRequest()
    return value


def content_fields(data):
    if not isinstance(data, dict) or set(data) != {"content_id", "kind", "text", "tags"}:
        raise BadRequest()
    return {
        "content_id": campaign_text(data["content_id"]),
        "kind": campaign_text(data["kind"]),
        "text": campaign_text(data["text"]),
        "tags": content_tags(data["tags"], required=True),
    }


def content_response(row):
    return {"content_id": row[0], "kind": row[1], "text": row[2],
            "tags": json.loads(row[3])}


def create_play_campaign_content(campaign_id, owner, data):
    content = content_fields(data)
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] != owner:
                raise PermissionError()
            connection.execute(
                "INSERT INTO play_campaign_content "
                "(campaign_id, content_id, kind, text, tags) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, content["content_id"], content["kind"], content["text"],
                 json.dumps(content["tags"], separators=(",", ":"))),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return content


def update_play_campaign_content_tags(campaign_id, content_id, owner, data):
    if not isinstance(data, dict) or set(data) != {"tags"}:
        raise BadRequest()
    tags = content_tags(data["tags"], required=False)
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        cursor = connection.execute(
            "UPDATE play_campaign_content SET tags = ? "
            "WHERE campaign_id = ? AND content_id = ?",
            (json.dumps(tags, separators=(",", ":")), campaign_id, content_id),
        )
        if cursor.rowcount == 0:
            return None
        row = connection.execute(
            "SELECT content_id, kind, text, tags FROM play_campaign_content "
            "WHERE campaign_id = ? AND content_id = ?", (campaign_id, content_id)
        ).fetchone()
    return content_response(row)


def list_play_campaign_content(campaign_id, username, exclude_tag=None):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        is_owner = campaign[0] == username
        if not is_owner and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        rows = connection.execute(
            "SELECT content_id, kind, text, tags FROM play_campaign_content "
            "WHERE campaign_id = ? ORDER BY rowid", (campaign_id,)
        ).fetchall()
    content = [content_response(row) for row in rows]
    if exclude_tag is not None and not is_owner:
        content = [record for record in content if exclude_tag not in record["tags"]]
    return {"content": content}


def search_record_fields(data):
    if not isinstance(data, dict) or set(data) != {"record_id", "text"}:
        raise BadRequest()
    return {"record_id": campaign_text(data["record_id"]),
            "text": campaign_text(data["text"])}


def create_play_campaign_search_record(campaign_id, owner, data):
    """Create a DM-owned search record with SQLite row order as its sequence."""
    record = search_record_fields(data)
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] != owner:
                raise PermissionError()
            # Search entries identify a distinct piece of searchable text.
            # Validate both uniqueness conditions before mutation so an invalid
            # request has no observable effect on pagination.
            if connection.execute(
                "SELECT 1 FROM play_campaign_search_records "
                "WHERE campaign_id = ? AND (record_id = ? OR text = ?)",
                (campaign_id, record["record_id"], record["text"]),
            ).fetchone() is not None:
                raise BadRequest()
            connection.execute(
                "INSERT INTO play_campaign_search_records (campaign_id, record_id, text) "
                "VALUES (?, ?, ?)",
                (campaign_id, record["record_id"], record["text"]),
            )
    except sqlite3.IntegrityError:
        # A concurrent insert can only make this request invalid as well.
        raise BadRequest()
    return record


def list_play_campaign_search_records(campaign_id, username, query, limit, cursor):
    """List member-visible records in creation order after filtering."""
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, username) is None:
            return None
        rows = connection.execute(
            "SELECT record_id, text FROM play_campaign_search_records "
            "WHERE campaign_id = ? ORDER BY rowid", (campaign_id,)
        ).fetchall()
    filtered = [row for row in rows if query.casefold() in row[1].casefold()]
    page = filtered[cursor:cursor + limit]
    records = [{"record_id": row[0], "text": row[1]} for row in page]
    return {"records": records,
            "next_cursor": cursor + len(records)
            if cursor + len(records) < len(filtered) else None}


def search_records_query(query):
    """Validate a singular query string and pagination offsets."""
    if set(query) - {"q", "limit", "cursor"}:
        raise BadRequest()

    def one(name, default):
        values = query.get(name)
        if values is None:
            return default
        if len(values) != 1:
            raise BadRequest()
        return values[0]

    text = one("q", "")
    limit_value = one("limit", "2")
    cursor_value = one("cursor", "0")
    if not isinstance(text, str) or not limit_value.isascii() or not limit_value.isdecimal() \
            or not cursor_value.isascii() or not cursor_value.isdecimal():
        raise BadRequest()
    limit, cursor = int(limit_value), int(cursor_value)
    if not 1 <= limit <= 3:
        raise BadRequest()
    return text, limit, cursor


def play_campaign_actor(connection, campaign_id, username):
    """Return whether an actor is the campaign DM or a current member."""
    campaign = connection.execute(
        "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if campaign is None:
        return None
    is_dm = campaign[0] == username
    is_member = connection.execute(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        (campaign_id, username),
    ).fetchone() is not None
    if not is_dm and not is_member:
        raise PermissionError()
    return is_dm


def feed_event_fields(data):
    """Validate the immutable public event-feed append shape."""
    if not isinstance(data, dict) or set(data) != {"event_id", "text"}:
        raise BadRequest()
    event_id, text = data["event_id"], data["text"]
    if (not isinstance(event_id, str) or not event_id or
            not isinstance(text, str) or not text):
        raise BadRequest()
    return event_id, text


def append_play_campaign_feed_event(campaign_id, actor, data):
    """Atomically append one member-authored feed event."""
    event_id, text = feed_event_fields(data)
    try:
        with DATABASE_LOCK, database() as connection:
            if play_campaign_actor(connection, campaign_id, actor) is None:
                return None
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM play_campaign_feed_events WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_feed_events "
                "(campaign_id, sequence, event_id, text) VALUES (?, ?, ?, ?)",
                (campaign_id, sequence, event_id, text),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return {"event_id": event_id, "text": text, "sequence": sequence}


def event_feed_pagination(query):
    """Parse the deliberately bounded, offset-based feed page parameters."""
    if set(query) - {"cursor", "limit"}:
        raise BadRequest()

    def value(name, default):
        values = query.get(name)
        if values is None:
            return default
        if len(values) != 1:
            raise BadRequest()
        return values[0]

    cursor_value, limit_value = value("cursor", "0"), value("limit", "2")
    if (not cursor_value.isascii() or not cursor_value.isdecimal() or
            not limit_value.isascii() or not limit_value.isdecimal()):
        raise BadRequest()
    cursor, limit = int(cursor_value), int(limit_value)
    if not 1 <= limit <= 3:
        raise BadRequest()
    return cursor, limit


def get_play_campaign_event_feed(campaign_id, actor, cursor, limit):
    """Read a page without altering the append-only campaign feed."""
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, actor) is None:
            return None
        rows = connection.execute(
            "SELECT event_id, text, sequence FROM play_campaign_feed_events "
            "WHERE campaign_id = ? ORDER BY sequence LIMIT ? OFFSET ?",
            (campaign_id, limit, cursor),
        ).fetchall()
    events = [{"event_id": row[0], "text": row[1], "sequence": row[2]}
              for row in rows]
    return {"events": events, "next_cursor": cursor + len(events)}


def get_play_campaign_onboarding(campaign_id, username):
    """Return fixed onboarding guidance for an authorized campaign actor."""
    with DATABASE_LOCK, database() as connection:
        is_dm = play_campaign_actor(connection, campaign_id, username)
    if is_dm is None:
        return None
    if is_dm:
        return {"role": "dm", "next_steps": [
            "configure-safety", "invite-players", "start-campaign",
        ], "can_mutate": True}
    return {"role": "player", "next_steps": [
        "review-party", "take-turn", "submit-action",
    ], "can_mutate": True}


def canonical_fixture_state():
    """Return the fixed fixture payload in its public field order."""
    return {
        "fixture_id": "canonical-v1",
        "status": "seeded",
        "characters": [
            {"character_id": "fixture-hero", "name": "Ari", "class": "fighter"},
            {"character_id": "fixture-mage", "name": "Bea", "class": "wizard"},
        ],
        "story": "The lantern is lit.",
        "event_ids": ["fixture-event-1", "fixture-event-2"],
    }


def validate_fixture_seed(data):
    if (not isinstance(data, dict) or set(data) != {"fixture_id"}
            or data["fixture_id"] != "canonical-v1"):
        raise BadRequest()


def seed_play_campaign_fixture(campaign_id, username, data):
    """Persist the one canonical fixture once, under the database lock."""
    with DATABASE_LOCK, database() as connection:
        is_dm = play_campaign_actor(connection, campaign_id, username)
        if is_dm is None:
            return None, False
        if not is_dm:
            raise PermissionError()
        validate_fixture_seed(data)
        existing = connection.execute(
            "SELECT fixture_id FROM play_campaign_fixture_seeds WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO play_campaign_fixture_seeds (campaign_id, fixture_id) VALUES (?, ?)",
                (campaign_id, "canonical-v1"),
            )
            return canonical_fixture_state(), True
    return canonical_fixture_state(), False


def get_play_campaign_fixture_state(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, username) is None:
            return None
        seeded = connection.execute(
            "SELECT 1 FROM play_campaign_fixture_seeds WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    if seeded is None:
        return None
    return canonical_fixture_state()


def safety_tags(value):
    """Validate a nonempty, order-preserving list of distinct tag strings."""
    if (not isinstance(value, list) or not value
            or any(not isinstance(tag, str) or not tag.strip() for tag in value)
            or len(set(value)) != len(value)):
        raise BadRequest()
    return value


def safety_check_fields(data):
    if not isinstance(data, dict) or set(data) != {"event_id", "kind", "text", "tags"}:
        raise BadRequest()
    event_id = data["event_id"]
    text = data["text"]
    if (not isinstance(event_id, str) or not event_id.strip()
            or not isinstance(text, str) or not text.strip()
            or data["kind"] not in ("narration", "chat")):
        raise BadRequest()
    return {"event_id": event_id, "kind": data["kind"], "text": text,
            "tags": safety_tags(data["tags"])}


def replace_play_campaign_safety_boundaries(campaign_id, username, data):
    """Atomically replace the DM-managed campaign tag blocklist."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != username:
            raise PermissionError()
        if not isinstance(data, dict) or set(data) != {"blocked_tags"}:
            raise BadRequest()
        blocked_tags = sorted(safety_tags(data["blocked_tags"]))
        connection.execute(
            "INSERT INTO play_campaign_safety_boundaries (campaign_id, blocked_tags) "
            "VALUES (?, ?) ON CONFLICT(campaign_id) DO UPDATE SET "
            "blocked_tags = excluded.blocked_tags",
            (campaign_id, json.dumps(blocked_tags, separators=(",", ":"))),
        )
    return {"blocked_tags": blocked_tags}


def get_play_campaign_safety_boundaries(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, username) is None:
            return None
        row = connection.execute(
            "SELECT blocked_tags FROM play_campaign_safety_boundaries WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    return {"blocked_tags": [] if row is None else json.loads(row[0])}


def create_play_campaign_safety_check(campaign_id, username, data):
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, username) is None:
            return None
        event = safety_check_fields(data)
        boundaries = connection.execute(
            "SELECT blocked_tags FROM play_campaign_safety_boundaries WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        blocked_tags = set() if boundaries is None else set(json.loads(boundaries[0]))
        if blocked_tags.intersection(event["tags"]):
            raise DuplicateRecord()
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_safety_events "
            "WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        try:
            connection.execute(
                "INSERT INTO play_campaign_safety_events "
                "(campaign_id, sequence, event_id, kind, text, tags) VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, sequence, event["event_id"], event["kind"], event["text"],
                 json.dumps(event["tags"], separators=(",", ":"))),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    return {**event, "sequence": sequence}


def list_play_campaign_safety_events(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, username) is None:
            return None
        rows = connection.execute(
            "SELECT event_id, kind, text, tags, sequence FROM play_campaign_safety_events "
            "WHERE campaign_id = ? ORDER BY sequence", (campaign_id,)
        ).fetchall()
    return {"events": [
        {"event_id": row[0], "kind": row[1], "text": row[2],
         "tags": json.loads(row[3]), "sequence": row[4]}
        for row in rows
    ]}


def rate_event_fields(data):
    if not isinstance(data, dict) or set(data) != {"event_id"}:
        raise BadRequest()
    return campaign_text(data["event_id"])


def create_play_campaign_rate_event(campaign_id, username, data):
    """Accept one of a member's two ordered rate events for this campaign."""
    event_id = rate_event_fields(data)
    rate_limited = False
    try:
        with DATABASE_LOCK, database() as connection:
            if play_campaign_actor(connection, campaign_id, username) is None:
                return None
            # Test uniqueness before the allowance so malformed/reused event
            # identifiers never consume an allowance or hide their validation error.
            if connection.execute(
                "SELECT 1 FROM play_campaign_rate_events "
                "WHERE campaign_id = ? AND event_id = ?", (campaign_id, event_id)
            ).fetchone() is not None:
                raise BadRequest()
            accepted = connection.execute(
                "SELECT COUNT(*) FROM play_campaign_rate_events "
                "WHERE campaign_id = ? AND actor = ?", (campaign_id, username)
            ).fetchone()[0]
            if accepted >= 2:
                connection.execute(
                    "UPDATE play_campaign_metrics "
                    "SET rejected_rate_events = rejected_rate_events + 1 WHERE campaign_id = ?",
                    (campaign_id,),
                )
                rate_limited = True
            else:
                connection.execute(
                    "INSERT INTO play_campaign_rate_events (campaign_id, event_id, actor) "
                    "VALUES (?, ?, ?)", (campaign_id, event_id, username)
                )
                connection.execute(
                    "UPDATE play_campaign_metrics "
                    "SET accepted_rate_events = accepted_rate_events + 1 WHERE campaign_id = ?",
                    (campaign_id,),
                )
    except sqlite3.IntegrityError:
        raise BadRequest()
    if rate_limited:
        raise RateLimitReached()
    return {"event_id": event_id, "actor": username, "remaining": 1 - accepted}


def list_play_campaign_rate_events(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, username) is None:
            return None
        rows = connection.execute(
            "SELECT event_id, actor FROM play_campaign_rate_events "
            "WHERE campaign_id = ? ORDER BY rowid", (campaign_id,)
        ).fetchall()
        accepted = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_rate_events "
            "WHERE campaign_id = ? AND actor = ?", (campaign_id, username)
        ).fetchone()[0]
    return {"events": [{"event_id": row[0], "actor": row[1]} for row in rows],
            "remaining": max(0, 2 - accepted)}


def get_play_campaign_metrics(campaign_id, actor):
    """Return only aggregate service counters to the campaign owner."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != actor:
            raise PermissionError()
        metrics = connection.execute(
            "SELECT accepted_rate_events, rejected_rate_events, projection_events "
            "FROM play_campaign_metrics WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
    return {"accepted_rate_events": metrics[0], "rejected_rate_events": metrics[1],
            "projection_events": metrics[2], "uptime_ticks": 1}


def note_fields(data, updating=False):
    keys = {"text", "visibility"} if updating else {"note_id", "text", "visibility"}
    if not isinstance(data, dict) or set(data) != keys:
        raise BadRequest()
    note = {}
    if not updating:
        note["note_id"] = campaign_text(data["note_id"])
    note["text"] = campaign_text(data["text"])
    if data["visibility"] not in ("private", "party"):
        raise BadRequest()
    note["visibility"] = data["visibility"]
    return note


def note_response(row):
    return {"note_id": row[0], "text": row[1], "visibility": row[2], "owner": row[3]}


def create_play_campaign_note(campaign_id, username, data):
    note = note_fields(data)
    try:
        with DATABASE_LOCK, database() as connection:
            if play_campaign_actor(connection, campaign_id, username) is None:
                return None
            connection.execute(
                "INSERT INTO play_campaign_notes (campaign_id, note_id, text, visibility, owner) "
                "VALUES (?, ?, ?, ?, ?)",
                (campaign_id, note["note_id"], note["text"], note["visibility"], username),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return {**note, "owner": username}


def list_play_campaign_notes(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        is_dm = play_campaign_actor(connection, campaign_id, username)
        if is_dm is None:
            return None
        rows = connection.execute(
            "SELECT note_id, text, visibility, owner FROM play_campaign_notes "
            "WHERE campaign_id = ? ORDER BY rowid", (campaign_id,)
        ).fetchall()
    notes = [note_response(row) for row in rows]
    if not is_dm:
        notes = [note for note in notes if note["visibility"] == "party" or note["owner"] == username]
    return {"notes": notes}


def get_play_campaign_note(campaign_id, note_id, username):
    with DATABASE_LOCK, database() as connection:
        is_dm = play_campaign_actor(connection, campaign_id, username)
        if is_dm is None:
            return None
        row = connection.execute(
            "SELECT note_id, text, visibility, owner FROM play_campaign_notes "
            "WHERE campaign_id = ? AND note_id = ?", (campaign_id, note_id)
        ).fetchone()
    if row is None:
        return None
    note = note_response(row)
    if not is_dm and note["visibility"] == "private" and note["owner"] != username:
        raise PermissionError()
    return note


def update_play_campaign_note(campaign_id, note_id, username, data):
    fields = note_fields(data, updating=True)
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, username) is None:
            return None
        row = connection.execute(
            "SELECT owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?",
            (campaign_id, note_id),
        ).fetchone()
        if row is None:
            return None
        if row[0] != username:
            raise PermissionError()
        connection.execute(
            "UPDATE play_campaign_notes SET text = ?, visibility = ? "
            "WHERE campaign_id = ? AND note_id = ?",
            (fields["text"], fields["visibility"], campaign_id, note_id),
        )
    return {"note_id": note_id, **fields, "owner": username}


def whisper_fields(data):
    if not isinstance(data, dict) or set(data) != {"whisper_id", "to_character_id", "text"}:
        raise BadRequest()
    return {key: campaign_text(data[key]) for key in ("whisper_id", "to_character_id", "text")}


def whisper_response(row):
    return {"whisper_id": row[0], "from_character_id": row[1],
            "to_character_id": row[2], "text": row[3]}


def create_play_campaign_whisper(campaign_id, username, data):
    whisper = whisper_fields(data)
    try:
        with DATABASE_LOCK, database() as connection:
            is_dm = play_campaign_actor(connection, campaign_id, username)
            if is_dm is None:
                return None
            if is_dm:
                raise PermissionError()
            sender = connection.execute(
                "SELECT character_id FROM play_campaign_character_owners "
                "WHERE campaign_id = ? AND owner = ? ORDER BY rowid LIMIT 1",
                (campaign_id, username),
            ).fetchone()
            recipient = connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, whisper["to_character_id"]),
            ).fetchone()
            if sender is None or recipient is None:
                raise BadRequest()
            connection.execute(
                "INSERT INTO play_campaign_whispers "
                "(campaign_id, whisper_id, from_character_id, to_character_id, text) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, whisper["whisper_id"], sender[0], whisper["to_character_id"], whisper["text"]),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return {"whisper_id": whisper["whisper_id"], "from_character_id": sender[0],
            "to_character_id": whisper["to_character_id"], "text": whisper["text"]}


def list_play_campaign_whispers(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        is_dm = play_campaign_actor(connection, campaign_id, username)
        if is_dm is None:
            return None
        rows = connection.execute(
            "SELECT whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers "
            "WHERE campaign_id = ? ORDER BY rowid", (campaign_id,)
        ).fetchall()
        owned = {row[0] for row in connection.execute(
            "SELECT character_id FROM play_campaign_character_owners WHERE campaign_id = ? AND owner = ?",
            (campaign_id, username),
        ).fetchall()}
    whispers = [whisper_response(row) for row in rows]
    if not is_dm:
        whispers = [whisper for whisper in whispers if whisper["from_character_id"] in owned
                    or whisper["to_character_id"] in owned]
    return {"whispers": whispers}


def get_play_character_sheet(campaign_id, character_id, username):
    with DATABASE_LOCK, database() as connection:
        is_dm = play_campaign_actor(connection, campaign_id, username)
        if is_dm is None:
            return None
        character = connection.execute(
            "SELECT members.name, members.class, owners.owner "
            "FROM play_campaign_members AS members JOIN play_campaign_character_owners AS owners "
            "ON owners.campaign_id = members.campaign_id AND owners.character_id = members.character_id "
            "WHERE members.campaign_id = ? AND members.character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
    if character is None:
        return None
    if not is_dm and character[2] != username:
        raise PermissionError()
    return {"character_id": character_id, "owner": character[2], "name": character[0],
            "class": character[1], "level": 1, "proficiency_bonus": 2,
            "hp_max": 10, "armor_class": 10}


def add_play_campaign_member(campaign_id, username, data):
    if not isinstance(data, dict):
        raise BadRequest()
    member = {key: campaign_text(data.get(key))
              for key in ("character_id", "name", "class")}
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT status, max_players FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != "lobby":
            raise DuplicateRecord()
        party_size = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        if party_size >= campaign[1]:
            raise DuplicateRecord()
        try:
            connection.execute(
                "INSERT INTO play_campaign_members "
                "(campaign_id, username, character_id, name, class) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, username, member["character_id"], member["name"], member["class"]),
            )
            connection.execute(
                "INSERT INTO play_campaign_character_owners "
                "(campaign_id, character_id, owner) VALUES (?, ?, ?)",
                (campaign_id, member["character_id"], username),
            )
            connection.execute(
                "INSERT INTO play_campaign_character_currency "
                "(campaign_id, character_id, gold) VALUES (?, ?, 10)",
                (campaign_id, member["character_id"]),
            )
            connection.execute(
                "INSERT INTO play_campaign_health (campaign_id, username, hp_current, hp_max) "
                "VALUES (?, ?, 20, 20)",
                (campaign_id, username),
            )
            connection.execute(
                "INSERT INTO play_campaign_death_saves "
                "(campaign_id, username, successes, failures, status) VALUES (?, ?, 0, 0, 'conscious')",
                (campaign_id, username),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    return {"username": username, **member}


def invitation_fields(data):
    if not isinstance(data, dict) or set(data) != {
            "invitation_id", "username", "character_id"}:
        raise BadRequest()
    return {key: campaign_text(data[key])
            for key in ("invitation_id", "username", "character_id")}


def invitation_response(row):
    return {"invitation_id": row[0], "username": row[1],
            "character_id": row[2], "status": row[3]}


def create_play_campaign_invitation(campaign_id, owner, data):
    invitation = invitation_fields(data)
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] != owner:
                raise PermissionError()
            target = connection.execute(
                "SELECT role FROM users WHERE username = ?", (invitation["username"],)
            ).fetchone()
            if target is None or target[0] != "player":
                raise BadRequest()
            if connection.execute(
                    "SELECT 1 FROM play_campaign_invitations "
                    "WHERE campaign_id = ? AND username = ? AND status = 'pending'",
                    (campaign_id, invitation["username"]),
            ).fetchone() is not None:
                raise DuplicateRecord()
            connection.execute(
                "INSERT INTO play_campaign_invitations "
                "(campaign_id, invitation_id, username, character_id, status) "
                "VALUES (?, ?, ?, ?, 'pending')",
                (campaign_id, invitation["invitation_id"], invitation["username"],
                 invitation["character_id"]),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return {**invitation, "status": "pending"}


def accept_play_campaign_invitation(campaign_id, invitation_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        row = connection.execute(
            "SELECT invitation_id, username, character_id, status "
            "FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?",
            (campaign_id, invitation_id),
        ).fetchone()
        if row is None:
            return None
        invitation = invitation_response(row)
        if invitation["username"] != username:
            raise PermissionError()
        if invitation["status"] != "pending":
            raise DuplicateRecord()
        if campaign[0] != "lobby":
            raise DuplicateRecord()
        party_size = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        max_players = connection.execute(
            "SELECT max_players FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()[0]
        if party_size >= max_players:
            raise DuplicateRecord()
        try:
            # Invitations deliberately carry only an identity and character ID.
            # These stable placeholders satisfy legacy member metadata while the
            # invited character's identity remains the supplied character ID.
            connection.execute(
                "INSERT INTO play_campaign_members "
                "(campaign_id, username, character_id, name, class) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, username, invitation["character_id"],
                 invitation["character_id"], "unknown"),
            )
            connection.execute(
                "INSERT INTO play_campaign_character_owners "
                "(campaign_id, character_id, owner) VALUES (?, ?, ?)",
                (campaign_id, invitation["character_id"], username),
            )
            connection.execute(
                "INSERT INTO play_campaign_character_currency "
                "(campaign_id, character_id, gold) VALUES (?, ?, 10)",
                (campaign_id, invitation["character_id"]),
            )
            connection.execute(
                "INSERT INTO play_campaign_health (campaign_id, username, hp_current, hp_max) "
                "VALUES (?, ?, 20, 20)", (campaign_id, username),
            )
            connection.execute(
                "INSERT INTO play_campaign_death_saves "
                "(campaign_id, username, successes, failures, status) "
                "VALUES (?, ?, 0, 0, 'conscious')", (campaign_id, username),
            )
            connection.execute(
                "UPDATE play_campaign_invitations SET status = 'accepted' "
                "WHERE campaign_id = ? AND invitation_id = ?",
                (campaign_id, invitation_id),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    invitation["status"] = "accepted"
    return invitation


def list_play_campaign_invitations(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        rows = connection.execute(
            "SELECT invitation_id, username, character_id, status "
            "FROM play_campaign_invitations WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
    invitations = [invitation_response(row) for row in rows]
    if campaign[0] != username:
        invitations = [record for record in invitations if record["username"] == username]
    return {"invitations": invitations}


def play_character_owner(campaign_id, character_id, username):
    """Return a member-visible character ownership assignment."""
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
    if owner is None:
        return None
    return {"character_id": character_id, "owner": owner[0]}


def play_character_currency(campaign_id, character_id, username):
    """Return a campaign member-visible character gold balance."""
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        balance = connection.execute(
            "SELECT gold FROM play_campaign_character_currency "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
    if balance is None:
        return None
    return {"character_id": character_id, "gold": balance[0]}


def transfer_play_character_currency(campaign_id, character_id, username, data):
    """Atomically move positive gold between two different campaign characters."""
    if not isinstance(data, dict):
        raise BadRequest()
    to_character_id = campaign_text(data.get("to_character_id"))
    gold = integer(data.get("gold"))
    if gold < 1 or to_character_id == character_id:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        source_owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if source_owner is None:
            return None
        if source_owner[0] != username:
            raise PermissionError()
        destination = connection.execute(
            "SELECT 1 FROM play_campaign_character_currency "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, to_character_id)
        ).fetchone()
        if destination is None:
            raise BadRequest()
        source = connection.execute(
            "SELECT gold FROM play_campaign_character_currency "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if source is None:
            return None
        if source[0] < gold:
            raise InsufficientGold()
        transfer_id = connection.execute(
            "SELECT COALESCE(MAX(transfer_id), 0) + 1 "
            "FROM play_campaign_currency_transfers WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        from_gold = source[0] - gold
        connection.execute(
            "UPDATE play_campaign_character_currency SET gold = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (from_gold, campaign_id, character_id),
        )
        connection.execute(
            "UPDATE play_campaign_character_currency SET gold = gold + ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (gold, campaign_id, to_character_id),
        )
        to_gold = connection.execute(
            "SELECT gold FROM play_campaign_character_currency "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, to_character_id)
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_currency_transfers "
            "(campaign_id, transfer_id, from_character_id, to_character_id, gold) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, transfer_id, character_id, to_character_id, gold),
        )
    return {"from_character_id": character_id, "to_character_id": to_character_id,
            "gold": gold, "from_gold": from_gold, "to_gold": to_gold,
            "transfer_id": transfer_id}


def transactional_transfer_fields(data):
    if not isinstance(data, dict) or set(data) != {
            "from_character_id", "to_character_id", "amount", "simulate_failure"}:
        raise BadRequest()
    from_character_id = campaign_text(data["from_character_id"])
    to_character_id = campaign_text(data["to_character_id"])
    amount = integer(data["amount"])
    if not isinstance(data["simulate_failure"], bool):
        raise BadRequest()
    if from_character_id == to_character_id or amount < 1:
        raise BadRequest()
    return from_character_id, to_character_id, amount, data["simulate_failure"]


def create_transactional_transfer(campaign_id, username, data):
    """Commit both balance changes and its ledger row as one SQLite transaction."""
    from_character_id, to_character_id, amount, simulate_failure = transactional_transfer_fields(data)
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        source_owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, from_character_id)
        ).fetchone()
        source = connection.execute(
            "SELECT gold FROM play_campaign_character_currency "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, from_character_id)
        ).fetchone()
        destination = connection.execute(
            "SELECT gold FROM play_campaign_character_currency "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, to_character_id)
        ).fetchone()
        if source_owner is None or source is None or destination is None:
            raise BadRequest()
        if source_owner[0] != username:
            raise PermissionError()
        if source[0] < amount:
            raise InsufficientGold()

        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 "
            "FROM play_campaign_transactional_transfers WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        from_gold = source[0] - amount
        to_gold = destination[0] + amount
        if simulate_failure:
            # The prospective values are prepared, but no compound mutation commits.
            raise SimulatedFailure()
        connection.execute(
            "UPDATE play_campaign_character_currency SET gold = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (from_gold, campaign_id, from_character_id),
        )
        connection.execute(
            "UPDATE play_campaign_character_currency SET gold = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (to_gold, campaign_id, to_character_id),
        )
        connection.execute(
            "INSERT INTO play_campaign_transactional_transfers "
            "(campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold),
        )
    return {"from_character_id": from_character_id, "to_character_id": to_character_id,
            "amount": amount, "from_gold": from_gold, "to_gold": to_gold,
            "sequence": sequence}


def list_transactional_transfers(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, username) is None:
            return None
        rows = connection.execute(
            "SELECT from_character_id, to_character_id, amount, from_gold, to_gold, sequence "
            "FROM play_campaign_transactional_transfers WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()
    return {"transfers": [
        {"from_character_id": row[0], "to_character_id": row[1], "amount": row[2],
         "from_gold": row[3], "to_gold": row[4], "sequence": row[5]}
        for row in rows
    ]}


def claim_play_character(campaign_id, character_id, username):
    """Assign an unowned campaign character to its requesting member."""
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if owner is None:
            return None
        if owner[0] is not None and owner[0] != username:
            raise DuplicateRecord()
        connection.execute(
            "UPDATE play_campaign_character_owners SET owner = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (username, campaign_id, character_id),
        )
    return {"character_id": character_id, "owner": username}


def transfer_play_character(campaign_id, character_id, username, data):
    """Transfer a character only from its current owner to another member."""
    if not isinstance(data, dict):
        raise BadRequest()
    new_owner = campaign_text(data.get("new_owner"))
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if owner is None:
            return None
        if owner[0] != username:
            raise PermissionError()
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, new_owner),
        ).fetchone() is None:
            raise BadRequest()
        connection.execute(
            "UPDATE play_campaign_character_owners SET owner = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (new_owner, campaign_id, character_id),
        )
    return {"character_id": character_id, "owner": new_owner}


def build_play_character(campaign_id, character_id, username, data):
    """Validate a member-owned level-one character build and its defaults."""
    if not isinstance(data, dict):
        raise BadRequest()
    race, character_class, background = (
        data.get("race"), data.get("class"), data.get("background")
    )
    if (race not in CHARACTER_RACES or character_class not in CHARACTER_CLASSES
            or background not in CHARACTER_BACKGROUNDS):
        raise BadRequest()
    abilities = data.get("abilities")
    if not isinstance(abilities, dict):
        raise BadRequest()
    modifiers = {name: ability_modifier(abilities.get(name)) for name in ABILITY_NAMES}
    hp_max = LEVEL_ONE_HIT_DICE[character_class] + modifiers["con"]
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if owner is None:
            return None
        if owner[0] != username:
            raise PermissionError()
        connection.execute(
            "INSERT INTO play_campaign_character_progression "
            "(campaign_id, character_id, class, con_modifier, level, hp_max) "
            "VALUES (?, ?, ?, ?, 1, ?) ON CONFLICT(campaign_id, character_id) DO NOTHING",
            (campaign_id, character_id, character_class, modifiers["con"], hp_max),
        )
        connection.execute(
            "INSERT INTO play_campaign_character_abilities "
            "(campaign_id, character_id, str, dex, con, int, wis, cha) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, character_id) DO NOTHING",
            (campaign_id, character_id, *(abilities[name] for name in ABILITY_NAMES)),
        )
    return {
        "character_id": character_id,
        "race": race,
        "class": character_class,
        "background": background,
        "level": 1,
        "hp_max": hp_max,
        "proficiency_bonus": proficiency_bonus(1),
    }


def level_up_play_character(campaign_id, character_id, username, data):
    """Advance an owned, built character by exactly one deterministic level."""
    if not isinstance(data, dict):
        raise BadRequest()
    requested_level = integer(data.get("level"))
    with DATABASE_LOCK, database() as connection:
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if owner is None:
            raise BadRequest()
        if owner[0] != username:
            raise PermissionError()
        character = connection.execute(
            "SELECT class, con_modifier, level, hp_max "
            "FROM play_campaign_character_progression "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if character is None or requested_level != character[2] + 1 or requested_level > 20:
            raise BadRequest()
        character_class, con_modifier, _, hp_max = character
        hit_die = LEVEL_ONE_HIT_DICE[character_class]
        # Level gains are deterministic: use the rounded-up average of the
        # class hit die, then add Constitution as described by the class rule.
        hp_max += hit_die // 2 + 1 + con_modifier
        connection.execute(
            "UPDATE play_campaign_character_progression "
            "SET level = ?, hp_max = ? WHERE campaign_id = ? AND character_id = ?",
            (requested_level, hp_max, campaign_id, character_id),
        )
        member = connection.execute(
            "SELECT username FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if member is not None:
            connection.execute(
                "UPDATE play_campaign_health SET hp_max = ? "
                "WHERE campaign_id = ? AND username = ?",
                (hp_max, campaign_id, member[0]),
            )
    return {"character_id": character_id, "level": requested_level,
            "hp_max": hp_max, "hit_dice": "1d{}".format(hit_die),
            "proficiency_bonus": proficiency_bonus(requested_level)}


def skill_check_play_character(campaign_id, character_id, username, data):
    """Resolve an owned character's skill check from its built abilities."""
    if not isinstance(data, dict):
        raise BadRequest()
    skill, ability = data.get("skill"), data.get("ability")
    proficient, roll = data.get("proficient"), integer(data.get("roll"))
    if skill not in SKILL_NAMES or ability not in ABILITY_NAMES or not isinstance(proficient, bool):
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if owner is None:
            return None
        if owner[0] != username:
            raise PermissionError()
        character = connection.execute(
            "SELECT progression.level, abilities.%s " % ability
            + "FROM play_campaign_character_progression AS progression "
            + "JOIN play_campaign_character_abilities AS abilities "
            + "ON abilities.campaign_id = progression.campaign_id "
            + "AND abilities.character_id = progression.character_id "
            + "WHERE progression.campaign_id = ? AND progression.character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
    if character is None:
        raise BadRequest()
    modifier = ability_modifier(character[1])
    if proficient:
        modifier += proficiency_bonus(character[0])
    return {"character_id": character_id, "skill": skill, "ability": ability,
            "modifier": modifier, "total": roll + modifier}


def add_play_character_spell(campaign_id, character_id, username, data):
    """Add one class-valid spell to an owned character's spellbook."""
    if not isinstance(data, dict):
        raise BadRequest()
    spell = {key: campaign_text(data.get(key)) for key in ("spell_id", "name")}
    spell["level"] = integer(data.get("level"))
    if spell["level"] < 0:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if owner is None:
            return None
        if owner[0] != username:
            raise PermissionError()
        character = connection.execute(
            "SELECT class FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if character is None:
            return None
        if character[0] != "wizard" or spell["spell_id"] not in WIZARD_SPELL_IDS:
            raise BadRequest()
        try:
            connection.execute(
                "INSERT INTO play_campaign_character_spells "
                "(campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, character_id, spell["spell_id"], spell["name"], spell["level"]),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    return spell


def play_character_spells(campaign_id, character_id, username):
    """Return a campaign member's stable, insertion-ordered spellbook."""
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
        ).fetchone() is None:
            return None
        spells = connection.execute(
            "SELECT spell_id, name, level FROM play_campaign_character_spells "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY rowid",
            (campaign_id, character_id),
        ).fetchall()
    return {"spells": [{"spell_id": row[0], "name": row[1], "level": row[2]}
                       for row in spells]}


def prepared_spell_limit(character_class, level):
    """Return the deterministic prepared-spell limit for a class level."""
    return level if character_class == "wizard" else 0


def prepared_spells_response(connection, campaign_id, character_id):
    """Read a character's prepared spell state from an open connection."""
    character = connection.execute(
        "SELECT members.class, COALESCE(progression.level, 1) "
        "FROM play_campaign_members AS members "
        "LEFT JOIN play_campaign_character_progression AS progression "
        "ON progression.campaign_id = members.campaign_id "
        "AND progression.character_id = members.character_id "
        "WHERE members.campaign_id = ? AND members.character_id = ?",
        (campaign_id, character_id),
    ).fetchone()
    if character is None:
        raise BadRequest()
    prepared_spells = connection.execute(
        "SELECT spell_id FROM play_campaign_character_prepared_spells "
        "WHERE campaign_id = ? AND character_id = ? ORDER BY sequence",
        (campaign_id, character_id),
    ).fetchall()
    return {"character_id": character_id,
            "prepared_spells": [row[0] for row in prepared_spells],
            "max_prepared": prepared_spell_limit(character[0], character[1])}


def update_play_character_prepared_spells(campaign_id, character_id, username, data):
    """Replace an owned spellcaster's ordered set of prepared known spells."""
    if not isinstance(data, dict) or not isinstance(data.get("spell_ids"), list):
        raise BadRequest()
    spell_ids = data["spell_ids"]
    if any(not isinstance(spell_id, str) or not spell_id for spell_id in spell_ids):
        raise BadRequest()
    if len(set(spell_ids)) != len(spell_ids):
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if owner is None:
            return None
        if owner[0] != username:
            raise PermissionError()
        character = connection.execute(
            "SELECT members.class, COALESCE(progression.level, 1) "
            "FROM play_campaign_members AS members "
            "LEFT JOIN play_campaign_character_progression AS progression "
            "ON progression.campaign_id = members.campaign_id "
            "AND progression.character_id = members.character_id "
            "WHERE members.campaign_id = ? AND members.character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            raise BadRequest()
        max_prepared = prepared_spell_limit(character[0], character[1])
        if max_prepared == 0 or len(spell_ids) > max_prepared:
            raise BadRequest()
        known_spells = {
            row[0] for row in connection.execute(
                "SELECT spell_id FROM play_campaign_character_spells "
                "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
            )
        }
        if any(spell_id not in known_spells for spell_id in spell_ids):
            raise BadRequest()
        connection.execute(
            "DELETE FROM play_campaign_character_prepared_spells "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        )
        connection.executemany(
            "INSERT INTO play_campaign_character_prepared_spells "
            "(campaign_id, character_id, spell_id, sequence) VALUES (?, ?, ?, ?)",
            [(campaign_id, character_id, spell_id, sequence)
             for sequence, spell_id in enumerate(spell_ids)],
        )
        return prepared_spells_response(connection, campaign_id, character_id)


def play_character_prepared_spells(campaign_id, character_id, username):
    """Return prepared spells to any member of the character's campaign."""
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
        ).fetchone() is None:
            return None
        return prepared_spells_response(connection, campaign_id, character_id)


def spell_slots_for_level(character_class, character_level, slot_level):
    """Return the deterministic number of slots at one spell level."""
    if character_class == "wizard" and character_level == 1 and slot_level == 1:
        return 1
    return 0


def cast_play_character_spell(campaign_id, character_id, username, data):
    """Consume a prepared spell slot and append one durable cast event."""
    if not isinstance(data, dict):
        raise BadRequest()
    spell_id = campaign_text(data.get("spell_id"))
    target = campaign_text(data.get("target"))
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if owner is None:
            return None
        if owner[0] != username:
            raise PermissionError()
        character = connection.execute(
            "SELECT members.class, COALESCE(progression.level, 1), spells.level "
            "FROM play_campaign_members AS members "
            "LEFT JOIN play_campaign_character_progression AS progression "
            "ON progression.campaign_id = members.campaign_id "
            "AND progression.character_id = members.character_id "
            "LEFT JOIN play_campaign_character_spells AS spells "
            "ON spells.campaign_id = members.campaign_id "
            "AND spells.character_id = members.character_id AND spells.spell_id = ? "
            "WHERE members.campaign_id = ? AND members.character_id = ?",
            (spell_id, campaign_id, character_id),
        ).fetchone()
        if character is None or character[0] != "wizard" or character[2] is None:
            raise BadRequest()
        if connection.execute(
                "SELECT 1 FROM play_campaign_character_prepared_spells "
                "WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
                (campaign_id, character_id, spell_id),
        ).fetchone() is None:
            raise BadRequest()
        slot_level = character[2]
        slot_count = spell_slots_for_level(character[0], character[1], slot_level)
        casts_used = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_character_casts "
            "WHERE campaign_id = ? AND character_id = ? AND slot_level = ?",
            (campaign_id, character_id, slot_level),
        ).fetchone()[0]
        if casts_used >= slot_count:
            raise NoSpellSlots()
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_character_casts "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()[0]
        slots_remaining = slot_count - casts_used - 1
        connection.execute(
            "INSERT INTO play_campaign_character_casts "
            "(campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, character_id, sequence, spell_id, target, slot_level,
             slots_remaining),
        )
    return {"character_id": character_id, "spell_id": spell_id, "target": target,
            "slot_level": slot_level, "slots_remaining": slots_remaining,
            "sequence": sequence}


def play_character_casts(campaign_id, character_id, username):
    """Return a campaign member's cast history in cast order."""
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
        ).fetchone() is None:
            return None
        casts = connection.execute(
            "SELECT spell_id, target, slot_level, slots_remaining, sequence "
            "FROM play_campaign_character_casts WHERE campaign_id = ? AND character_id = ? "
            "ORDER BY sequence", (campaign_id, character_id),
        ).fetchall()
    return {"casts": [{"character_id": character_id, "spell_id": row[0],
                       "target": row[1], "slot_level": row[2],
                       "slots_remaining": row[3], "sequence": row[4]}
                      for row in casts]}


def concentration_response(connection, campaign_id, character_id):
    """Read one character's optional current concentration state."""
    concentration = connection.execute(
        "SELECT spell_id, target, remaining_turns "
        "FROM play_campaign_character_concentrations "
        "WHERE campaign_id = ? AND character_id = ?",
        (campaign_id, character_id),
    ).fetchone()
    return {"character_id": character_id,
            "concentration": (None if concentration is None else {
                "spell_id": concentration[0], "target": concentration[1],
                "remaining_turns": concentration[2]})}


def set_play_character_concentration(campaign_id, character_id, username, data):
    """Replace an owned spellcaster's current concentration state."""
    if not isinstance(data, dict):
        raise BadRequest()
    spell_id = campaign_text(data.get("spell_id"))
    target = campaign_text(data.get("target"))
    duration_turns = integer(data.get("duration_turns"))
    if duration_turns < 1:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if owner is None:
            return None
        if owner[0] != username:
            raise PermissionError()
        character = connection.execute(
            "SELECT class FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        known = connection.execute(
            "SELECT 1 FROM play_campaign_character_spells "
            "WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
            (campaign_id, character_id, spell_id),
        ).fetchone()
        prepared = connection.execute(
            "SELECT 1 FROM play_campaign_character_prepared_spells "
            "WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
            (campaign_id, character_id, spell_id),
        ).fetchone()
        if character is None or character[0] != "wizard" or known is None or prepared is None:
            raise BadRequest()
        connection.execute(
            "INSERT INTO play_campaign_character_concentrations "
            "(campaign_id, character_id, spell_id, target, remaining_turns) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, character_id) DO UPDATE SET "
            "spell_id = excluded.spell_id, target = excluded.target, "
            "remaining_turns = excluded.remaining_turns",
            (campaign_id, character_id, spell_id, target, duration_turns),
        )
        return concentration_response(connection, campaign_id, character_id)


def play_character_concentration(campaign_id, character_id, username):
    """Return concentration state to any member of the character's campaign."""
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
        ).fetchone() is None:
            return None
        return concentration_response(connection, campaign_id, character_id)


def advance_play_character_concentration(campaign_id, character_id, username):
    """Advance active concentration by one turn for any campaign member."""
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
        ).fetchone() is None:
            return None
        concentration = connection.execute(
            "SELECT remaining_turns FROM play_campaign_character_concentrations "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if concentration is not None:
            if concentration[0] <= 1:
                connection.execute(
                    "DELETE FROM play_campaign_character_concentrations "
                    "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
                )
            else:
                connection.execute(
                    "UPDATE play_campaign_character_concentrations "
                    "SET remaining_turns = remaining_turns - 1 "
                    "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
                )
        return concentration_response(connection, campaign_id, character_id)


def clear_play_character_concentration(campaign_id, character_id, username):
    """Clear concentration when requested by the owning character's player."""
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if owner is None:
            return None
        if owner[0] != username:
            raise PermissionError()
        connection.execute(
            "DELETE FROM play_campaign_character_concentrations "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        )
        return concentration_response(connection, campaign_id, character_id)


def add_play_character_inventory_item(campaign_id, character_id, username, data):
    """Add a positive quantity of a catalog item to an owned character."""
    if not isinstance(data, dict):
        raise BadRequest()
    item_id = data.get("item_id")
    quantity = integer(data.get("quantity"))
    if item_id not in PLAY_INVENTORY_ITEM_IDS or quantity < 1:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if owner is None:
            return None
        if owner[0] != username:
            raise PermissionError()
        connection.execute(
            "INSERT INTO play_campaign_character_inventory_items "
            "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET "
            "quantity = quantity + excluded.quantity",
            (campaign_id, character_id, item_id, quantity),
        )
        total_quantity = connection.execute(
            "SELECT quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()[0]
    return {"character_id": character_id, "item_id": item_id,
            "quantity": quantity, "total_quantity": total_quantity}


def play_character_inventory_items(campaign_id, character_id, username):
    """Return a member-visible character inventory in catalog order."""
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        if connection.execute(
                "SELECT 1 FROM play_campaign_character_owners "
                "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone() is None:
            return None
        rows = connection.execute(
            "SELECT item_id, quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND quantity > 0 ORDER BY item_id",
            (campaign_id, character_id),
        ).fetchall()
    return {"character_id": character_id,
            "items": [{"item_id": row[0], "quantity": row[1]} for row in rows]}


def recipe_fields(data):
    """Validate and normalize the public representation of one recipe."""
    if not isinstance(data, dict):
        raise BadRequest()
    recipe_id = campaign_text(data.get("recipe_id"))
    name = campaign_text(data.get("name"))
    ingredients = data.get("ingredients")
    output_item = data.get("output_item")
    output_quantity = integer(data.get("output_quantity"))
    if (not isinstance(ingredients, dict) or not ingredients
            or output_item not in PLAY_INVENTORY_ITEM_IDS or output_quantity < 1):
        raise BadRequest()
    normalized_ingredients = {}
    for item_id, quantity in ingredients.items():
        quantity = integer(quantity)
        if item_id not in PLAY_INVENTORY_ITEM_IDS or quantity < 1:
            raise BadRequest()
        normalized_ingredients[item_id] = quantity
    return {"recipe_id": recipe_id, "name": name,
            "ingredients": normalized_ingredients, "output_item": output_item,
            "output_quantity": output_quantity}


def recipe_response(row):
    return {"recipe_id": row[0], "name": row[1], "ingredients": json.loads(row[2]),
            "output_item": row[3], "output_quantity": row[4]}


def create_play_campaign_recipe(campaign_id, owner, data):
    recipe = recipe_fields(data)
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] != owner:
                raise PermissionError()
            connection.execute(
                "INSERT INTO play_campaign_recipes "
                "(campaign_id, recipe_id, name, ingredients, output_item, output_quantity) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, recipe["recipe_id"], recipe["name"],
                 json.dumps(recipe["ingredients"], separators=(",", ":")),
                 recipe["output_item"], recipe["output_quantity"]),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return recipe


def list_play_campaign_recipes(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != username and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        rows = connection.execute(
            "SELECT recipe_id, name, ingredients, output_item, output_quantity "
            "FROM play_campaign_recipes WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
    return {"recipes": [recipe_response(row) for row in rows]}


def craft_play_campaign_recipe(campaign_id, recipe_id, username, data):
    if not isinstance(data, dict):
        raise BadRequest()
    character_id = campaign_text(data.get("character_id"))
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        recipe = connection.execute(
            "SELECT recipe_id, name, ingredients, output_item, output_quantity "
            "FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?",
            (campaign_id, recipe_id),
        ).fetchone()
        if recipe is None:
            return None
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if owner is None:
            return None
        if owner[0] != username:
            raise PermissionError()
        ingredients = json.loads(recipe[2])
        held = dict(connection.execute(
            "SELECT item_id, quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchall())
        if any(held.get(item_id, 0) < quantity
               for item_id, quantity in ingredients.items()):
            raise InsufficientInventory()
        for item_id, quantity in ingredients.items():
            remaining = held[item_id] - quantity
            if remaining == 0:
                connection.execute(
                    "DELETE FROM play_campaign_character_inventory_items "
                    "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (campaign_id, character_id, item_id),
                )
            else:
                connection.execute(
                    "UPDATE play_campaign_character_inventory_items SET quantity = ? "
                    "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (remaining, campaign_id, character_id, item_id),
                )
        connection.execute(
            "INSERT INTO play_campaign_character_inventory_items "
            "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET "
            "quantity = quantity + excluded.quantity",
            (campaign_id, character_id, recipe[3], recipe[4]),
        )
    return {"character_id": character_id, "recipe_id": recipe[0],
            "output_item": recipe[3], "output_quantity": recipe[4]}


def downtime_activity_fields(data):
    if not isinstance(data, dict):
        raise BadRequest()
    activity = {key: campaign_text(data.get(key)) for key in ("activity_id", "name")}
    activity["cycles_required"] = integer(data.get("cycles_required"))
    if not 1 <= activity["cycles_required"] <= 10:
        raise BadRequest()
    return activity


def downtime_activity_response(row):
    return {"activity_id": row[0], "name": row[1], "cycles_required": row[2]}


def downtime_allocation_response(character_id, activity_id, row):
    return {"character_id": character_id, "activity_id": activity_id,
            "cycles_completed": row[0], "completions": row[1]}


def create_play_campaign_downtime_activity(campaign_id, owner, data):
    activity = downtime_activity_fields(data)
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] != owner:
                raise PermissionError()
            connection.execute(
                "INSERT INTO play_campaign_downtime_activities "
                "(campaign_id, activity_id, name, cycles_required) VALUES (?, ?, ?, ?)",
                (campaign_id, activity["activity_id"], activity["name"],
                 activity["cycles_required"]),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return activity


def create_play_character_downtime_allocation(campaign_id, character_id, username, data):
    if not isinstance(data, dict):
        raise BadRequest()
    activity_id = campaign_text(data.get("activity_id"))
    try:
        with DATABASE_LOCK, database() as connection:
            if connection.execute(
                    "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone() is None:
                return None
            if connection.execute(
                    "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                    (campaign_id, character_id),
            ).fetchone() is None:
                return None
            if connection.execute(
                    "SELECT 1 FROM play_campaign_downtime_activities "
                    "WHERE campaign_id = ? AND activity_id = ?", (campaign_id, activity_id),
            ).fetchone() is None:
                return None
            owner = connection.execute(
                "SELECT owner FROM play_campaign_character_owners "
                "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id),
            ).fetchone()
            if owner is None:
                return None
            if owner[0] != username:
                raise PermissionError()
            connection.execute(
                "INSERT INTO play_campaign_downtime_allocations "
                "(campaign_id, character_id, activity_id, cycles_completed, completions) "
                "VALUES (?, ?, ?, 0, 0)", (campaign_id, character_id, activity_id),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return {"character_id": character_id, "activity_id": activity_id,
            "cycles_completed": 0, "completions": 0}


def progress_play_character_downtime_allocation(campaign_id, character_id, activity_id, username):
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
        ).fetchone() is None:
            return None
        activity = connection.execute(
            "SELECT cycles_required FROM play_campaign_downtime_activities "
            "WHERE campaign_id = ? AND activity_id = ?", (campaign_id, activity_id),
        ).fetchone()
        if activity is None:
            return None
        allocation = connection.execute(
            "SELECT cycles_completed, completions FROM play_campaign_downtime_allocations "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (campaign_id, character_id, activity_id),
        ).fetchone()
        if allocation is None:
            return None
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id),
        ).fetchone()
        if owner is None:
            return None
        if owner[0] != username:
            raise PermissionError()
        cycles_completed, completions = allocation[0] + 1, allocation[1]
        if cycles_completed == activity[0]:
            cycles_completed, completions = 0, completions + 1
        connection.execute(
            "UPDATE play_campaign_downtime_allocations "
            "SET cycles_completed = ?, completions = ? "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (cycles_completed, completions, campaign_id, character_id, activity_id),
        )
    return {"character_id": character_id, "activity_id": activity_id,
            "cycles_completed": cycles_completed, "completions": completions}


def get_play_character_downtime_allocation(campaign_id, character_id, activity_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != username and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
        ).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_downtime_activities "
                "WHERE campaign_id = ? AND activity_id = ?", (campaign_id, activity_id),
        ).fetchone() is None:
            return None
        allocation = connection.execute(
            "SELECT cycles_completed, completions FROM play_campaign_downtime_allocations "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (campaign_id, character_id, activity_id),
        ).fetchone()
    if allocation is None:
        return None
    return downtime_allocation_response(character_id, activity_id, allocation)


def create_play_campaign_loot(campaign_id, owner, data):
    """Open one immutable campaign loot record for its owning DM."""
    if not isinstance(data, dict):
        raise BadRequest()
    loot_id = campaign_text(data.get("loot_id"))
    item_id = data.get("item_id")
    quantity = integer(data.get("quantity"))
    if item_id not in PLAY_INVENTORY_ITEM_IDS or quantity < 1:
        raise BadRequest()
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] != owner:
                raise PermissionError()
            connection.execute(
                "INSERT INTO play_campaign_loot "
                "(campaign_id, loot_id, item_id, quantity, status, recipient_character_id, votes) "
                "VALUES (?, ?, ?, ?, 'open', NULL, 0)",
                (campaign_id, loot_id, item_id, quantity),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return {"loot_id": loot_id, "item_id": item_id, "quantity": quantity,
            "status": "open"}


def vote_on_play_campaign_loot(campaign_id, loot_id, voter, data):
    """Store a player's single, immutable vote for open campaign loot."""
    if not isinstance(data, dict):
        raise BadRequest()
    recipient_character_id = campaign_text(data.get("recipient_character_id"))
    try:
        with DATABASE_LOCK, database() as connection:
            if connection.execute(
                    "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone() is None:
                return None
            if connection.execute(
                    "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                    (campaign_id, voter),
            ).fetchone() is None:
                raise PermissionError()
            loot = connection.execute(
                "SELECT status FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?",
                (campaign_id, loot_id),
            ).fetchone()
            if loot is None:
                return None
            if loot[0] != "open":
                raise DuplicateRecord()
            if connection.execute(
                    "SELECT 1 FROM play_campaign_members "
                    "WHERE campaign_id = ? AND character_id = ?",
                    (campaign_id, recipient_character_id),
            ).fetchone() is None:
                raise BadRequest()
            connection.execute(
                "INSERT INTO play_campaign_loot_votes "
                "(campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)",
                (campaign_id, loot_id, voter, recipient_character_id),
            )
            votes_for_recipient = connection.execute(
                "SELECT COUNT(*) FROM play_campaign_loot_votes "
                "WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?",
                (campaign_id, loot_id, recipient_character_id),
            ).fetchone()[0]
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return {"loot_id": loot_id, "voter": voter,
            "recipient_character_id": recipient_character_id,
            "votes_for_recipient": votes_for_recipient}


def assign_play_campaign_loot(campaign_id, loot_id, owner):
    """Assign an unambiguously voted loot item exactly once."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        loot = connection.execute(
            "SELECT item_id, quantity, status FROM play_campaign_loot "
            "WHERE campaign_id = ? AND loot_id = ?", (campaign_id, loot_id),
        ).fetchone()
        if loot is None:
            return None
        if loot[2] != "open":
            raise DuplicateRecord()
        leaders = connection.execute(
            "SELECT recipient_character_id, COUNT(*) AS vote_count "
            "FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? "
            "GROUP BY recipient_character_id ORDER BY vote_count DESC, recipient_character_id",
            (campaign_id, loot_id),
        ).fetchall()
        if not leaders or (len(leaders) > 1 and leaders[0][1] == leaders[1][1]):
            raise DuplicateRecord()
        recipient_character_id, votes = leaders[0]
        connection.execute(
            "INSERT INTO play_campaign_character_inventory_items "
            "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET "
            "quantity = quantity + excluded.quantity",
            (campaign_id, recipient_character_id, loot[0], loot[1]),
        )
        connection.execute(
            "UPDATE play_campaign_loot SET status = 'assigned', "
            "recipient_character_id = ?, votes = ? WHERE campaign_id = ? AND loot_id = ?",
            (recipient_character_id, votes, campaign_id, loot_id),
        )
    return {"loot_id": loot_id, "recipient_character_id": recipient_character_id,
            "item_id": loot[0], "quantity": loot[1], "votes": votes,
            "status": "assigned"}


def get_play_campaign_loot(campaign_id, loot_id, username):
    """Return loot to the owning DM or a member of its campaign."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != username and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        loot = connection.execute(
            "SELECT item_id, quantity, status, recipient_character_id "
            "FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?",
            (campaign_id, loot_id),
        ).fetchone()
        vote_rows = connection.execute(
            "SELECT recipient_character_id, COUNT(*) FROM play_campaign_loot_votes "
            "WHERE campaign_id = ? AND loot_id = ? "
            "GROUP BY recipient_character_id ORDER BY recipient_character_id",
            (campaign_id, loot_id),
        ).fetchall()
    if loot is None:
        return None
    return {"loot_id": loot_id, "item_id": loot[0], "quantity": loot[1],
            "status": loot[2], "recipient_character_id": loot[3],
            "votes": {row[0]: row[1] for row in vote_rows}}


def create_play_campaign_npc(campaign_id, owner, data):
    """Create a DM-managed NPC whose agenda is private to its campaign DM."""
    if not isinstance(data, dict):
        raise BadRequest()
    npc = {key: campaign_text(data.get(key))
           for key in ("npc_id", "name", "agenda", "public_status")}
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] != owner:
                raise PermissionError()
            connection.execute(
                "INSERT INTO play_campaign_npcs "
                "(campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, npc["npc_id"], npc["name"], npc["agenda"],
                 npc["public_status"]),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return npc


def update_play_campaign_npc_agenda(campaign_id, npc_id, owner, data):
    """Update the private agenda and player-visible status of an NPC."""
    if not isinstance(data, dict):
        raise BadRequest()
    agenda = campaign_text(data.get("agenda"))
    public_status = campaign_text(data.get("public_status"))
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        npc = connection.execute(
            "SELECT name FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
        if npc is None:
            return None
        connection.execute(
            "UPDATE play_campaign_npcs SET agenda = ?, public_status = ? "
            "WHERE campaign_id = ? AND npc_id = ?",
            (agenda, public_status, campaign_id, npc_id),
        )
    return {"npc_id": npc_id, "name": npc[0], "agenda": agenda,
            "public_status": public_status}


def get_play_campaign_npc(campaign_id, npc_id, username):
    """Return a full NPC to its DM or a public projection to a member."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        is_dm = campaign[0] == username
        if not is_dm and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        npc = connection.execute(
            "SELECT name, agenda, public_status FROM play_campaign_npcs "
            "WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
    if npc is None:
        return None
    if is_dm:
        return {"npc_id": npc_id, "name": npc[0], "agenda": npc[1],
                "public_status": npc[2]}
    return {"npc_id": npc_id, "name": npc[0], "public_status": npc[2]}


def create_play_campaign_npc_dialogue(campaign_id, npc_id, owner, data):
    """Append a DM-authored, attributed entry to an NPC's dialogue history."""
    if not isinstance(data, dict):
        raise BadRequest()
    entry = {key: campaign_text(data.get(key))
             for key in ("dialogue_id", "speaker", "text", "visibility")}
    if entry["visibility"] not in ("public", "private"):
        raise BadRequest()
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] != owner:
                raise PermissionError()
            if connection.execute(
                    "SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
                    (campaign_id, npc_id),
            ).fetchone() is None:
                return None
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_npc_dialogue "
                "WHERE campaign_id = ? AND npc_id = ?", (campaign_id, npc_id),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_npc_dialogue "
                "(campaign_id, npc_id, dialogue_id, sequence, speaker, text, visibility) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (campaign_id, npc_id, entry["dialogue_id"], sequence, entry["speaker"],
                 entry["text"], entry["visibility"]),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return entry


def get_play_campaign_npc_dialogue(campaign_id, npc_id, username):
    """Return all NPC dialogue to the DM and public entries to members."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        is_dm = campaign[0] == username
        if not is_dm and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        if connection.execute(
                "SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
                (campaign_id, npc_id),
        ).fetchone() is None:
            return None
        query = (
            "SELECT dialogue_id, speaker, text, visibility FROM play_campaign_npc_dialogue "
            "WHERE campaign_id = ? AND npc_id = ?"
        )
        params = [campaign_id, npc_id]
        if not is_dm:
            query += " AND visibility = ?"
            params.append("public")
        rows = connection.execute(query + " ORDER BY sequence", params).fetchall()
    return {"npc_id": npc_id, "entries": [
        {"dialogue_id": row[0], "speaker": row[1], "text": row[2],
         "visibility": row[3]} for row in rows
    ]}


def relationship_score(value):
    score = integer(value)
    if not -100 <= score <= 100:
        raise BadRequest()
    return score


def play_campaign_entity_exists(connection, campaign_id, entity_id):
    return connection.execute(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? "
        "UNION ALL "
        "SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ? LIMIT 1",
        (campaign_id, entity_id, campaign_id, entity_id),
    ).fetchone() is not None


def create_play_campaign_relationship(campaign_id, owner, data):
    if not isinstance(data, dict):
        raise BadRequest()
    edge = {key: campaign_text(data.get(key))
            for key in ("source_id", "target_id", "kind")}
    edge["score"] = relationship_score(data.get("score"))
    if edge["source_id"] == edge["target_id"]:
        raise BadRequest()
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] != owner:
                raise PermissionError()
            if not play_campaign_entity_exists(connection, campaign_id, edge["source_id"]):
                return None
            if not play_campaign_entity_exists(connection, campaign_id, edge["target_id"]):
                return None
            connection.execute(
                "INSERT INTO play_campaign_relationships "
                "(campaign_id, source_id, target_id, kind, score) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, edge["source_id"], edge["target_id"], edge["kind"], edge["score"]),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return edge


def update_play_campaign_relationship(campaign_id, source_id, target_id, kind, owner, data):
    if not isinstance(data, dict):
        raise BadRequest()
    score = relationship_score(data.get("score"))
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        edge = connection.execute(
            "SELECT 1 FROM play_campaign_relationships "
            "WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
            (campaign_id, source_id, target_id, kind),
        ).fetchone()
        if edge is None:
            return None
        connection.execute(
            "UPDATE play_campaign_relationships SET score = ? "
            "WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
            (score, campaign_id, source_id, target_id, kind),
        )
    return {"source_id": source_id, "target_id": target_id, "kind": kind, "score": score}


def get_play_campaign_relationships(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != username and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        rows = connection.execute(
            "SELECT source_id, target_id, kind, score FROM play_campaign_relationships "
            "WHERE campaign_id = ? ORDER BY rowid", (campaign_id,)
        ).fetchall()
    return {"edges": [
        {"source_id": row[0], "target_id": row[1], "kind": row[2], "score": row[3]}
        for row in rows
    ]}


def create_play_campaign_clue(campaign_id, owner, data):
    """Persist a DM-authored clue with its intended visibility."""
    if not isinstance(data, dict):
        raise BadRequest()
    clue = {key: campaign_text(data.get(key)) for key in ("clue_id", "text")}
    audience = data.get("audience")
    if audience not in ("character", "party", "hidden"):
        raise BadRequest()
    if audience == "character":
        character_id = campaign_text(data.get("character_id"))
    elif "character_id" in data:
        raise BadRequest()
    else:
        character_id = None
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] != owner:
                raise PermissionError()
            if character_id is not None and connection.execute(
                    "SELECT 1 FROM play_campaign_members "
                    "WHERE campaign_id = ? AND character_id = ?",
                    (campaign_id, character_id),
            ).fetchone() is None:
                raise BadRequest()
            connection.execute(
                "INSERT INTO play_campaign_clues "
                "(campaign_id, clue_id, text, audience, character_id) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, clue["clue_id"], clue["text"], audience, character_id),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    response = {"clue_id": clue["clue_id"], "text": clue["text"], "audience": audience}
    if character_id is not None:
        response["character_id"] = character_id
    return response


def get_play_campaign_clues(campaign_id, username):
    """Return all clues to the DM and only relevant revealed clues to a member."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        is_dm = campaign[0] == username
        member = None if is_dm else connection.execute(
            "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if not is_dm and member is None:
            raise PermissionError()
        query = (
            "SELECT clue_id, text, audience, character_id FROM play_campaign_clues "
            "WHERE campaign_id = ?"
        )
        params = [campaign_id]
        if not is_dm:
            query += " AND (audience = ? OR (audience = ? AND character_id = ?))"
            params.extend(["party", "character", member[0]])
        rows = connection.execute(query + " ORDER BY rowid", params).fetchall()
    clues = []
    for row in rows:
        clue = {"clue_id": row[0], "text": row[1], "audience": row[2]}
        if row[2] == "character":
            clue["character_id"] = row[3]
        clues.append(clue)
    return {"clues": clues}


def quest_dependencies(value, quest_id):
    if not isinstance(value, list):
        raise BadRequest()
    if any(not isinstance(dependency, str) or not dependency for dependency in value):
        raise BadRequest()
    if quest_id in value or len(set(value)) != len(value):
        raise BadRequest()
    return value


def play_campaign_quest_response(row):
    response = {"quest_id": row[0], "title": row[1],
                "depends_on": json.loads(row[2]), "state": row[3]}
    if len(row) > 4 and row[4] is not None:
        response["rewards"] = {"xp": row[4], "items": json.loads(row[5])}
    return response


def create_play_campaign_quest(campaign_id, owner, data):
    if not isinstance(data, dict):
        raise BadRequest()
    quest_id = campaign_text(data.get("quest_id"))
    title = campaign_text(data.get("title"))
    depends_on = quest_dependencies(data.get("depends_on"), quest_id)
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] != owner:
                raise PermissionError()
            existing = {
                row[0] for row in connection.execute(
                    "SELECT quest_id FROM play_campaign_quests "
                    "WHERE campaign_id = ? AND quest_id IN ({})".format(
                        ",".join("?" for _ in depends_on)
                    ),
                    [campaign_id, *depends_on],
                )
            } if depends_on else set()
            if existing != set(depends_on):
                raise BadRequest()
            connection.execute(
                "INSERT INTO play_campaign_quests "
                "(campaign_id, quest_id, title, depends_on, state) VALUES (?, ?, ?, ?, 'locked')",
                (campaign_id, quest_id, title, json.dumps(depends_on, separators=(",", ":"))),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return {"quest_id": quest_id, "title": title, "depends_on": depends_on,
            "state": "locked"}


def update_play_campaign_quest_state(campaign_id, quest_id, owner, data):
    if not isinstance(data, dict) or data.get("state") not in ("active", "completed"):
        raise BadRequest()
    target_state = data["state"]
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        quest = connection.execute(
            "SELECT q.quest_id, q.title, q.depends_on, q.state, r.xp, r.items "
            "FROM play_campaign_quests AS q "
            "LEFT JOIN play_campaign_quest_rewards AS r "
            "ON r.campaign_id = q.campaign_id AND r.quest_id = q.quest_id "
            "WHERE q.campaign_id = ? AND q.quest_id = ?", (campaign_id, quest_id),
        ).fetchone()
        if quest is None:
            return None
        depends_on = json.loads(quest[2])
        valid_transition = (quest[3] == "locked" and target_state == "active") or (
            quest[3] == "active" and target_state == "completed"
        )
        if not valid_transition:
            raise DuplicateRecord()
        if quest[3] == "locked":
            completed = {
                row[0] for row in connection.execute(
                    "SELECT quest_id FROM play_campaign_quests "
                    "WHERE campaign_id = ? AND state = 'completed' AND quest_id IN ({})".format(
                        ",".join("?" for _ in depends_on)
                    ),
                    [campaign_id, *depends_on],
                )
            } if depends_on else set()
            if completed != set(depends_on):
                raise DuplicateRecord()
        connection.execute(
            "UPDATE play_campaign_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?",
            (target_state, campaign_id, quest_id),
        )
    return play_campaign_quest_response(quest[:3] + (target_state,) + quest[4:])


def get_play_campaign_quests(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != username and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        rows = connection.execute(
            "SELECT q.quest_id, q.title, q.depends_on, q.state, r.xp, r.items "
            "FROM play_campaign_quests AS q "
            "LEFT JOIN play_campaign_quest_rewards AS r "
            "ON r.campaign_id = q.campaign_id AND r.quest_id = q.quest_id "
            "WHERE q.campaign_id = ? ORDER BY q.rowid", (campaign_id,)
        ).fetchall()
    return {"quests": [play_campaign_quest_response(row) for row in rows]}


def quest_rewards(value):
    if not isinstance(value, dict) or set(value) != {"xp", "items"}:
        raise BadRequest()
    xp = integer(value.get("xp"))
    items = value.get("items")
    if xp < 0 or not isinstance(items, dict):
        raise BadRequest()
    for item_id, quantity in items.items():
        if item_id not in PLAY_INVENTORY_ITEM_IDS or integer(quantity) < 1:
            raise BadRequest()
    return xp, items


def configure_play_campaign_quest_rewards(campaign_id, quest_id, owner, data):
    xp, items = quest_rewards(data)
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        quest = connection.execute(
            "SELECT title, depends_on, state FROM play_campaign_quests "
            "WHERE campaign_id = ? AND quest_id = ?", (campaign_id, quest_id),
        ).fetchone()
        if quest is None:
            return None
        if quest[2] not in ("locked", "active"):
            raise DuplicateRecord()
        connection.execute(
            "INSERT INTO play_campaign_quest_rewards "
            "(campaign_id, quest_id, xp, items) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, quest_id) DO UPDATE SET "
            "xp = excluded.xp, items = excluded.items",
            (campaign_id, quest_id, xp, json.dumps(items, separators=(",", ":"))),
        )
    return {"quest_id": quest_id, "title": quest[0],
            "depends_on": json.loads(quest[1]), "state": quest[2],
            "rewards": {"xp": xp, "items": items}}


def award_play_campaign_quest_rewards(campaign_id, quest_id, owner):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        quest = connection.execute(
            "SELECT state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if quest is None:
            return None
        reward = connection.execute(
            "SELECT xp, items, awarded FROM play_campaign_quest_rewards "
            "WHERE campaign_id = ? AND quest_id = ?", (campaign_id, quest_id),
        ).fetchone()
        if quest[0] != "completed" or reward is None or reward[2]:
            raise DuplicateRecord()
        xp, items = reward[0], json.loads(reward[1])
        members = connection.execute(
            "SELECT character_id FROM play_campaign_members WHERE campaign_id = ?", (campaign_id,)
        ).fetchall()
        for (character_id,) in members:
            connection.execute(
                "INSERT INTO play_campaign_character_quest_rewards "
                "(campaign_id, character_id, quest_id, xp, items) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, character_id, quest_id, xp, reward[1]),
            )
            for item_id, quantity in items.items():
                connection.execute(
                    "INSERT INTO play_campaign_character_inventory_items "
                    "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET "
                    "quantity = quantity + excluded.quantity",
                    (campaign_id, character_id, item_id, quantity),
                )
        connection.execute(
            "UPDATE play_campaign_quest_rewards SET awarded = 1 "
            "WHERE campaign_id = ? AND quest_id = ?", (campaign_id, quest_id),
        )
    return {"quest_id": quest_id, "awarded": True, "xp": xp, "items": items}


def play_character_quest_rewards(campaign_id, character_id, username):
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
        ).fetchone() is None:
            return None
        rows = connection.execute(
            "SELECT xp, items FROM play_campaign_character_quest_rewards "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY rowid",
            (campaign_id, character_id),
        ).fetchall()
    xp, items = 0, {}
    for grant_xp, grant_items in rows:
        xp += grant_xp
        for item_id, quantity in json.loads(grant_items).items():
            items[item_id] = items.get(item_id, 0) + quantity
    return {"character_id": character_id, "xp": xp, "items": items}


def world_event_response(row):
    """Render one world event, including its immutable resolution if present."""
    response = {"event_id": row[0], "turn_number": row[1], "title": row[2],
                "text": row[3], "status": row[4]}
    if row[4] == "resolved":
        response["resolution"] = {"turn_number": row[5], "text": row[6]}
    return response


def schedule_play_campaign_world_event(campaign_id, owner, data):
    if not isinstance(data, dict):
        raise BadRequest()
    event_id = campaign_text(data.get("event_id"))
    title = campaign_text(data.get("title"))
    text = campaign_text(data.get("text"))
    turn_number = integer(data.get("turn_number"))
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] != owner:
                raise PermissionError()
            current_turn = connection.execute(
                "SELECT COUNT(*) FROM play_campaign_actions "
                "WHERE campaign_id = ? AND type = 'resolution'", (campaign_id,)
            ).fetchone()[0] + 1
            if turn_number < current_turn:
                raise BadRequest()
            connection.execute(
                "INSERT INTO play_campaign_world_events "
                "(campaign_id, event_id, turn_number, title, text, status) "
                "VALUES (?, ?, ?, ?, ?, 'scheduled')",
                (campaign_id, event_id, turn_number, title, text),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return {"event_id": event_id, "turn_number": turn_number, "title": title,
            "text": text, "status": "scheduled"}


def resolve_play_campaign_world_event(campaign_id, event_id, owner, data):
    if not isinstance(data, dict):
        raise BadRequest()
    resolution_text = campaign_text(data.get("text"))
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        event = connection.execute(
            "SELECT event_id, turn_number, title, text, status, "
            "resolution_turn_number, resolution_text "
            "FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if event is None:
            return None
        current_turn = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_actions "
            "WHERE campaign_id = ? AND type = 'resolution'", (campaign_id,)
        ).fetchone()[0] + 1
        if current_turn != event[1] or event[4] != "scheduled":
            raise DuplicateRecord()
        connection.execute(
            "UPDATE play_campaign_world_events SET status = 'resolved', "
            "resolution_turn_number = ?, resolution_text = ? "
            "WHERE campaign_id = ? AND event_id = ?",
            (current_turn, resolution_text, campaign_id, event_id),
        )
    return {"event_id": event[0], "turn_number": event[1], "title": event[2],
            "text": event[3], "status": "resolved",
            "resolution": {"turn_number": current_turn, "text": resolution_text}}


def get_play_campaign_world_events(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != username and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        rows = connection.execute(
            "SELECT event_id, turn_number, title, text, status, "
            "resolution_turn_number, resolution_text FROM play_campaign_world_events "
            "WHERE campaign_id = ? ORDER BY turn_number, rowid", (campaign_id,)
        ).fetchall()
    return {"events": [world_event_response(row) for row in rows]}


CALENDAR_SEASON_OFFSETS = {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}
CALENDAR_WEATHER = ("clear", "rain", "wind", "snow")


def calendar_response(day, season):
    return {"day": day, "season": season,
            "weather": CALENDAR_WEATHER[(day + CALENDAR_SEASON_OFFSETS[season]) % 4]}


def initialize_play_campaign_calendar(campaign_id, owner, data):
    if not isinstance(data, dict):
        raise BadRequest()
    day = integer(data.get("day"))
    season = data.get("season")
    if day < 1 or season not in CALENDAR_SEASON_OFFSETS:
        raise BadRequest()
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] != owner:
                raise PermissionError()
            connection.execute(
                "INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (?, ?, ?)",
                (campaign_id, day, season),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return calendar_response(day, season)


def get_play_campaign_calendar(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != username and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        calendar = connection.execute(
            "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    return None if calendar is None else calendar_response(calendar[0], calendar[1])


def advance_play_campaign_calendar(campaign_id, owner, data):
    if not isinstance(data, dict):
        raise BadRequest()
    days = integer(data.get("days"))
    if not 1 <= days <= 30:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        calendar = connection.execute(
            "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if calendar is None:
            return None
        day, season = calendar[0] + days, calendar[1]
        connection.execute(
            "UPDATE play_campaign_calendars SET day = ? WHERE campaign_id = ?",
            (day, campaign_id),
        )
    return calendar_response(day, season)


def create_play_campaign_faction(campaign_id, owner, data):
    """Create a DM-managed faction within a play campaign."""
    if not isinstance(data, dict):
        raise BadRequest()
    faction = {key: campaign_text(data.get(key)) for key in ("faction_id", "name")}
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] != owner:
                raise PermissionError()
            connection.execute(
                "INSERT INTO play_campaign_factions (campaign_id, faction_id, name) "
                "VALUES (?, ?, ?)", (campaign_id, faction["faction_id"], faction["name"])
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return faction


def change_play_campaign_faction_reputation(campaign_id, faction_id, owner, data):
    """Apply a bounded reputation change and retain its immutable history."""
    if not isinstance(data, dict):
        raise BadRequest()
    character_id = campaign_text(data.get("character_id"))
    delta = integer(data.get("delta"))
    reason = campaign_text(data.get("reason"))
    if delta == 0 or delta < -25 or delta > 25:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        if connection.execute(
                "SELECT 1 FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?",
                (campaign_id, faction_id),
        ).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
        ).fetchone() is None:
            raise BadRequest()
        current = connection.execute(
            "SELECT reputation FROM play_campaign_faction_reputations "
            "WHERE campaign_id = ? AND faction_id = ? AND character_id = ?",
            (campaign_id, faction_id, character_id),
        ).fetchone()
        reputation = max(-100, min(100, (current[0] if current else 0) + delta))
        connection.execute(
            "INSERT INTO play_campaign_faction_reputations "
            "(campaign_id, faction_id, character_id, reputation) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, faction_id, character_id) DO UPDATE SET "
            "reputation = excluded.reputation",
            (campaign_id, faction_id, character_id, reputation),
        )
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_faction_reputation_history "
            "WHERE campaign_id = ? AND faction_id = ?", (campaign_id, faction_id),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_faction_reputation_history "
            "(campaign_id, faction_id, sequence, character_id, reputation, delta, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, faction_id, sequence, character_id, reputation, delta, reason),
        )
    return {"faction_id": faction_id, "character_id": character_id,
            "reputation": reputation, "delta": delta, "reason": reason}


def get_play_campaign_faction_reputation(campaign_id, faction_id, username):
    """Return faction reputation history, filtered to a player's character."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        is_dm = campaign[0] == username
        member = None if is_dm else connection.execute(
            "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if not is_dm and member is None:
            raise PermissionError()
        if connection.execute(
                "SELECT 1 FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?",
                (campaign_id, faction_id),
        ).fetchone() is None:
            return None
        if is_dm:
            rows = connection.execute(
                "SELECT character_id, reputation, delta, reason "
                "FROM play_campaign_faction_reputation_history "
                "WHERE campaign_id = ? AND faction_id = ? ORDER BY sequence",
                (campaign_id, faction_id),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT character_id, reputation, delta, reason "
                "FROM play_campaign_faction_reputation_history "
                "WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY sequence",
                (campaign_id, faction_id, member[0]),
            ).fetchall()
    return {"faction_id": faction_id, "entries": [
        {"faction_id": faction_id, "character_id": row[0], "reputation": row[1],
         "delta": row[2], "reason": row[3]} for row in rows
    ]}


def remove_play_character_inventory_item(campaign_id, character_id, item_id, username, data):
    """Remove a positive quantity of a catalog item from an owned character."""
    if not isinstance(data, dict):
        raise BadRequest()
    quantity = integer(data.get("quantity"))
    if item_id not in PLAY_INVENTORY_ITEM_IDS or quantity < 1:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if owner is None:
            return None
        if owner[0] != username:
            raise PermissionError()
        stack = connection.execute(
            "SELECT quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()
        held_quantity = 0 if stack is None else stack[0]
        if quantity > held_quantity:
            raise InsufficientInventory()
        total_quantity = held_quantity - quantity
        if total_quantity == 0:
            connection.execute(
                "DELETE FROM play_campaign_character_inventory_items "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, character_id, item_id),
            )
        else:
            connection.execute(
                "UPDATE play_campaign_character_inventory_items SET quantity = ? "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (total_quantity, campaign_id, character_id, item_id),
            )
    return {"character_id": character_id, "item_id": item_id,
            "quantity": quantity, "total_quantity": total_quantity}


def consume_play_character_inventory_item(campaign_id, character_id, item_id, username):
    """Consume one held unit of a supported consumable inventory item."""
    if item_id not in PLAY_INVENTORY_ITEM_IDS or item_id not in PLAY_CONSUMABLE_ITEM_IDS:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if owner is None:
            return None
        if owner[0] != username:
            raise PermissionError()
        stack = connection.execute(
            "SELECT quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()
        held_quantity = 0 if stack is None else stack[0]
        if held_quantity < 1:
            raise InsufficientInventory()
        total_quantity = held_quantity - 1
        if total_quantity == 0:
            connection.execute(
                "DELETE FROM play_campaign_character_inventory_items "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, character_id, item_id),
            )
        else:
            connection.execute(
                "UPDATE play_campaign_character_inventory_items SET quantity = ? "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (total_quantity, campaign_id, character_id, item_id),
            )
    return {"character_id": character_id, "item_id": item_id,
            "quantity_consumed": 1, "total_quantity": total_quantity,
            "effect": {"type": "healing", "hp_restored": 5}}


def equipment_response(connection, campaign_id, character_id, slot):
    equipment = connection.execute(
        "SELECT item_id, attuned FROM play_campaign_character_equipment "
        "WHERE campaign_id = ? AND character_id = ? AND slot = ?",
        (campaign_id, character_id, slot),
    ).fetchone()
    return {"character_id": character_id, "slot": slot,
            "item_id": "" if equipment is None else equipment[0],
            "attuned": False if equipment is None else bool(equipment[1])}


def equip_play_character_item(campaign_id, character_id, slot, username, data):
    if not isinstance(data, dict):
        raise BadRequest()
    item_id = data.get("item_id")
    if slot not in PLAY_EQUIPMENT_SLOTS or item_id not in PLAY_EQUIPMENT_ITEM_SLOTS:
        raise BadRequest()
    if PLAY_EQUIPMENT_ITEM_SLOTS[item_id] != slot:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if owner is None:
            return None
        if owner[0] != username:
            raise PermissionError()
        held = connection.execute(
            "SELECT quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()
        if held is None or held[0] < 1:
            raise BadRequest()
        connection.execute(
            "INSERT INTO play_campaign_character_equipment "
            "(campaign_id, character_id, slot, item_id, attuned) VALUES (?, ?, ?, ?, 0) "
            "ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET "
            "item_id = excluded.item_id, attuned = 0",
            (campaign_id, character_id, slot, item_id),
        )
        return equipment_response(connection, campaign_id, character_id, slot)


def get_play_character_equipment(campaign_id, character_id, slot, username):
    if slot not in PLAY_EQUIPMENT_SLOTS:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        if connection.execute(
                "SELECT 1 FROM play_campaign_character_owners "
                "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone() is None:
            return None
        return equipment_response(connection, campaign_id, character_id, slot)


def attune_play_character_equipment(campaign_id, character_id, slot, username):
    if slot not in PLAY_EQUIPMENT_SLOTS:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        if connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return None
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id)
        ).fetchone()
        if owner is None:
            return None
        if owner[0] != username:
            raise PermissionError()
        equipment = connection.execute(
            "SELECT item_id, attuned FROM play_campaign_character_equipment "
            "WHERE campaign_id = ? AND character_id = ? AND slot = ?",
            (campaign_id, character_id, slot),
        ).fetchone()
        if (slot != "accessory" or equipment is None
                or equipment[0] not in PLAY_ATTUNABLE_ITEM_IDS):
            raise BadRequest()
        attunement_count = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_character_equipment "
            "WHERE campaign_id = ? AND character_id = ? AND attuned = 1",
            (campaign_id, character_id),
        ).fetchone()[0]
        if attunement_count >= 1:
            raise AttunementLimitReached()
        connection.execute(
            "UPDATE play_campaign_character_equipment SET attuned = 1 "
            "WHERE campaign_id = ? AND character_id = ? AND slot = ?",
            (campaign_id, character_id, slot),
        )
        return {"character_id": character_id, "slot": slot,
                "item_id": equipment[0], "attuned": True,
                "attunement_count": 1, "max_attunements": 1}


def damage_play_character(campaign_id, character_id, owner, data):
    """Apply owner-directed damage to a campaign character outside an encounter."""
    if not isinstance(data, dict):
        raise BadRequest()
    amount = integer(data.get("amount"))
    if amount < 1:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        member = connection.execute(
            "SELECT username FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if member is None:
            return None
        health = connection.execute(
            "SELECT hp_current FROM play_campaign_health WHERE campaign_id = ? AND username = ?",
            (campaign_id, member[0]),
        ).fetchone()
        hp_before = health[0]
        hp_current = max(0, hp_before - amount)
        connection.execute(
            "UPDATE play_campaign_health SET hp_current = ? WHERE campaign_id = ? AND username = ?",
            (hp_current, campaign_id, member[0]),
        )
        if hp_current == 0:
            connection.execute(
                "UPDATE play_campaign_death_saves SET status = 'unconscious' "
                "WHERE campaign_id = ? AND username = ? AND status NOT IN ('dead', 'stable')",
                (campaign_id, member[0]),
            )
    return {"target": character_id, "character_id": character_id, "hp_before": hp_before,
            "hp_after": hp_current, "damage": amount, "hp_current": hp_current}


def play_character_death_save(campaign_id, character_id, username, data):
    if not isinstance(data, dict) or data.get("outcome") not in ("success", "failure"):
        raise BadRequest()
    outcome = data["outcome"]
    with DATABASE_LOCK, database() as connection:
        member = connection.execute(
            "SELECT username FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if member is None:
            return None
        if member[0] != username:
            raise PermissionError()
        save = connection.execute(
            "SELECT successes, failures, status FROM play_campaign_death_saves "
            "WHERE campaign_id = ? AND username = ?", (campaign_id, username)
        ).fetchone()
        if save is None or save[2] != "unconscious":
            raise DuplicateRecord()
        successes, failures = save[0], save[1]
        if outcome == "success":
            successes += 1
        else:
            failures += 1
        status = "stable" if successes >= 3 else "dead" if failures >= 3 else "unconscious"
        connection.execute(
            "UPDATE play_campaign_death_saves SET successes = ?, failures = ?, status = ? "
            "WHERE campaign_id = ? AND username = ?",
            (successes, failures, status, campaign_id, username),
        )
    return {"character_id": character_id, "successes": successes,
            "failures": failures, "status": status}


def play_character_status(campaign_id, character_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != username and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        character = connection.execute(
            "SELECT members.username, health.hp_current, health.hp_max, saves.status "
            "FROM play_campaign_members AS members "
            "JOIN play_campaign_health AS health "
            "ON health.campaign_id = members.campaign_id AND health.username = members.username "
            "JOIN play_campaign_death_saves AS saves "
            "ON saves.campaign_id = members.campaign_id AND saves.username = members.username "
            "WHERE members.campaign_id = ? AND members.character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
    if character is None:
        return None
    return {"character_id": character_id, "hp_current": character[1],
            "hp_max": character[2], "status": character[3]}


def create_play_campaign_encounter(campaign_id, owner, data):
    """Start one combat encounter without consuming exploration turns."""
    if not isinstance(data, dict):
        raise BadRequest()
    encounter = {key: campaign_text(data.get(key)) for key in ("id", "name")}
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        if campaign[1] != "active":
            raise DuplicateRecord()
        try:
            connection.execute(
                "INSERT INTO play_campaign_encounters "
                "(id, campaign_id, name, status, combatants) VALUES (?, ?, ?, 'active', '[]')",
                (encounter["id"], campaign_id, encounter["name"]),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
        connection.execute(
            "UPDATE play_campaigns SET status = 'combat' WHERE id = ?", (campaign_id,)
        )
    return {"id": encounter["id"], "name": encounter["name"],
            "status": "active", "combatants": []}


def award_play_campaign_encounter_rewards(campaign_id, encounter_id, owner, data):
    """Persist the owner's single deterministic reward allocation for an encounter."""
    if not isinstance(data, dict):
        raise BadRequest()
    xp = integer(data.get("xp"))
    loot = data.get("loot")
    if xp < 0 or not isinstance(loot, list):
        raise BadRequest()
    normalized_loot = []
    for item in loot:
        if not isinstance(item, dict):
            raise BadRequest()
        slug = campaign_text(item.get("slug"))
        quantity = integer(item.get("quantity"))
        if quantity < 1:
            raise BadRequest()
        normalized_loot.append({"slug": slug, "quantity": quantity})
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        if connection.execute(
            "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone() is None:
            return None
        try:
            connection.execute(
                "INSERT INTO play_campaign_encounter_rewards (encounter_id, xp, loot) VALUES (?, ?, ?)",
                (encounter_id, xp, json.dumps(normalized_loot, separators=(",", ":"))),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    return {"encounter_id": encounter_id, "xp": xp, "loot": normalized_loot}


def close_play_campaign_encounter(campaign_id, encounter_id, owner):
    """Close an encounter and report the XP allocation made so far."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        encounter = connection.execute(
            "SELECT status FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return None
        reward = connection.execute(
            "SELECT xp FROM play_campaign_encounter_rewards WHERE encounter_id = ?",
            (encounter_id,),
        ).fetchone()
        connection.execute(
            "UPDATE play_campaign_encounters SET status = 'closed' WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        )
    return {"id": encounter_id, "status": "closed", "xp_awarded": 0 if reward is None else reward[0]}


def end_play_campaign_encounter(campaign_id, encounter_id, owner):
    """Return a combat campaign to the exploration turn it paused on."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        if campaign[1] != "combat":
            raise DuplicateRecord()
        encounter = connection.execute(
            "SELECT status FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return None
        if encounter[0] == "active":
            connection.execute(
                "UPDATE play_campaign_encounters SET status = 'closed' "
                "WHERE id = ? AND campaign_id = ?",
                (encounter_id, campaign_id),
            )
        connection.execute(
            "UPDATE play_campaigns SET status = 'active' WHERE id = ?", (campaign_id,)
        )
    return {"campaign_id": campaign_id, "status": "active", "phase": "exploration",
            "current_actor": owner}


def add_play_campaign_monster(campaign_id, encounter_id, owner, data):
    """Add one owner-controlled monster to an active encounter roster."""
    if not isinstance(data, dict):
        raise BadRequest()
    monster = {key: campaign_text(data.get(key)) for key in ("monster_id", "name")}
    monster["hp_max"] = integer(data.get("hp_max"))
    monster["initiative"] = integer(data.get("initiative"))
    if monster["hp_max"] < 1:
        raise BadRequest()
    monster["hp_current"] = monster["hp_max"]
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        encounter = connection.execute(
            "SELECT combatants FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return None
        combatants = json.loads(encounter[0])
        if any(combatant.get("monster_id") == monster["monster_id"]
               for combatant in combatants):
            raise DuplicateRecord()
        combatants.append(monster)
        connection.execute(
            "UPDATE play_campaign_encounters SET combatants = ? WHERE id = ?",
            (json.dumps(combatants, separators=(",", ":")), encounter_id),
        )
    return monster


def add_play_campaign_combatant(campaign_id, encounter_id, owner, data):
    """Bind a party member to an active encounter's combatant roster."""
    if not isinstance(data, dict):
        raise BadRequest()
    member = campaign_text(data.get("member"))
    initiative = integer(data.get("initiative"))
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        encounter = connection.execute(
            "SELECT combatants FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return None
        character = connection.execute(
            "SELECT character_id, name FROM play_campaign_members "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, member),
        ).fetchone()
        if character is None:
            raise BadRequest()
        combatants = json.loads(encounter[0])
        if any(combatant.get("member") == member for combatant in combatants):
            raise DuplicateRecord()
        combatant = {"member": member, "character_id": character[0],
                     "name": character[1], "initiative": initiative}
        combatants.append(combatant)
        connection.execute(
            "UPDATE play_campaign_encounters SET combatants = ? WHERE id = ?",
            (json.dumps(combatants, separators=(",", ":")), encounter_id),
        )
    return combatant


def adjust_play_campaign_combatant_hp(campaign_id, encounter_id, owner, data, healing):
    """Apply an owner-directed, bounded HP change to an encounter combatant."""
    if not isinstance(data, dict):
        raise BadRequest()
    target = campaign_text(data.get("target"))
    amount = integer(data.get("amount"))
    if amount < 1:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        encounter = connection.execute(
            "SELECT combatants FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return None
        combatants = json.loads(encounter[0])
        target_combatant = next(
            (combatant for combatant in combatants
             if combatant.get("monster_id") == target),
            None,
        )
        if target_combatant is not None:
            hp_before = target_combatant["hp_current"]
            hp_max = target_combatant["hp_max"]
            hp_after = min(hp_max, hp_before + amount) if healing else max(0, hp_before - amount)
            target_combatant["hp_current"] = hp_after
            connection.execute(
                "UPDATE play_campaign_encounters SET combatants = ? WHERE id = ? AND campaign_id = ?",
                (json.dumps(combatants, separators=(",", ":")), encounter_id, campaign_id),
            )
        elif any(combatant.get("member") == target for combatant in combatants):
            health = connection.execute(
                "SELECT hp_current, hp_max FROM play_campaign_health "
                "WHERE campaign_id = ? AND username = ?", (campaign_id, target)
            ).fetchone()
            if health is None:
                return None
            hp_before, hp_max = health
            hp_after = min(hp_max, hp_before + amount) if healing else max(0, hp_before - amount)
            connection.execute(
                "UPDATE play_campaign_health SET hp_current = ? "
                "WHERE campaign_id = ? AND username = ?", (hp_after, campaign_id, target)
            )
        else:
            return None
    return {"target": target, "hp_before": hp_before, "hp_after": hp_after,
            "healing" if healing else "damage": amount}


def remove_play_campaign_combatant(campaign_id, encounter_id, member, owner):
    """Unbind one party member from an encounter combatant roster."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        encounter = connection.execute(
            "SELECT combatants FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return None
        combatants = json.loads(encounter[0])
        retained = [combatant for combatant in combatants
                    if combatant.get("member") != member]
        if len(retained) == len(combatants):
            return None
        connection.execute(
            "UPDATE play_campaign_encounters SET combatants = ? WHERE id = ?",
            (json.dumps(retained, separators=(",", ":")), encounter_id),
        )
    return {"removed": member}


def remove_play_campaign_monster(campaign_id, encounter_id, monster_id, owner):
    """Remove one owner-controlled monster from an encounter roster."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        encounter = connection.execute(
            "SELECT combatants FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return None
        combatants = json.loads(encounter[0])
        retained = [combatant for combatant in combatants
                    if combatant.get("monster_id") != monster_id]
        if len(retained) == len(combatants):
            return None
        connection.execute(
            "UPDATE play_campaign_encounters SET combatants = ? WHERE id = ?",
            (json.dumps(retained, separators=(",", ":")), encounter_id),
        )
    return {"removed": monster_id}


def ordered_play_campaign_combatants(combatants):
    """Return the stable encounter order used for every combat turn."""
    return sorted(combatants, key=lambda combatant: (
        -combatant["initiative"], combatant["name"]
    ))


def play_campaign_combat_turn_summary(round_number, turn_index, combatants):
    ordered = ordered_play_campaign_combatants(combatants)
    if not ordered:
        return None
    active = ordered[turn_index % len(ordered)]
    return {
        "round": round_number,
        "turn_index": turn_index % len(ordered),
        "active": {
            "name": active["name"],
            "kind": "player" if "member" in active else "monster",
            "initiative": active["initiative"],
        },
    }


def play_campaign_combatant_target(combatant):
    """Return the externally-addressable condition target for a combatant."""
    return combatant.get("member") or combatant.get("monster_id")


def play_campaign_encounter_status(round_number, turn_index, combatants, conditions):
    """Return the complete, deterministic encounter state."""
    ordered = ordered_play_campaign_combatants(combatants)
    summary = play_campaign_combat_turn_summary(round_number, turn_index, ordered)
    if summary is None:
        return None
    summary["order"] = [
        {"name": combatant["name"],
         "kind": "player" if "member" in combatant else "monster",
         "initiative": combatant["initiative"]}
        for combatant in ordered
    ]
    summary["conditions"] = conditions
    return summary


def get_play_campaign_encounter_turn(campaign_id, encounter_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != username and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        encounter = connection.execute(
            "SELECT round, turn_index, combatants FROM play_campaign_encounters "
            "WHERE id = ? AND campaign_id = ?", (encounter_id, campaign_id),
        ).fetchone()
    if encounter is None:
        return None
    return play_campaign_combat_turn_summary(
        encounter[0], encounter[1], json.loads(encounter[2])
    )


def get_play_campaign_encounter_status(campaign_id, encounter_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != username and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        encounter = connection.execute(
            "SELECT round, turn_index, combatants, conditions "
            "FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
    if encounter is None:
        return None
    return play_campaign_encounter_status(
        encounter[0], encounter[1], json.loads(encounter[2]), json.loads(encounter[3])
    )


def add_play_campaign_encounter_condition(campaign_id, encounter_id, owner, data):
    """Apply a timed condition to a combatant, as the campaign owner."""
    if not isinstance(data, dict):
        raise BadRequest()
    target = campaign_text(data.get("target"))
    condition = campaign_text(data.get("condition"))
    duration = integer(data.get("duration_rounds"))
    if duration < 1:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        encounter = connection.execute(
            "SELECT combatants, conditions FROM play_campaign_encounters "
            "WHERE id = ? AND campaign_id = ?", (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return None
        combatants = json.loads(encounter[0])
        if target not in {play_campaign_combatant_target(item) for item in combatants}:
            raise BadRequest()
        conditions = json.loads(encounter[1])
        target_conditions = conditions.setdefault(target, [])
        target_conditions.append({"condition": condition, "remaining_rounds": duration})
        connection.execute(
            "UPDATE play_campaign_encounters SET conditions = ? WHERE id = ? AND campaign_id = ?",
            (json.dumps(conditions, separators=(",", ":")), encounter_id, campaign_id),
        )
    return {"target": target, "conditions": target_conditions}


def advance_play_campaign_encounter_turn(campaign_id, encounter_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        is_owner = campaign[0] == username
        if not is_owner and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        encounter = connection.execute(
            "SELECT round, turn_index, combatants, conditions FROM play_campaign_encounters "
            "WHERE id = ? AND campaign_id = ?", (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return None
        combatants = ordered_play_campaign_combatants(json.loads(encounter[2]))
        if not combatants:
            return None
        turn_index = encounter[1] % len(combatants)
        if not is_owner and combatants[turn_index].get("member") != username:
            raise OutOfTurn()
        turn_index += 1
        round_number = encounter[0]
        if turn_index == len(combatants):
            turn_index = 0
            round_number += 1
        conditions = json.loads(encounter[3])
        active_target = play_campaign_combatant_target(combatants[turn_index])
        if active_target in conditions:
            remaining = [
                {"condition": item["condition"],
                 "remaining_rounds": item["remaining_rounds"] - 1}
                for item in conditions[active_target]
                if item["remaining_rounds"] > 1
            ]
            if remaining:
                conditions[active_target] = remaining
            else:
                del conditions[active_target]
        connection.execute(
            "UPDATE play_campaign_encounters SET round = ?, turn_index = ?, conditions = ? "
            "WHERE id = ? AND campaign_id = ?",
            (round_number, turn_index, json.dumps(conditions, separators=(",", ":")),
             encounter_id, campaign_id),
        )
    return play_campaign_combat_turn_summary(round_number, turn_index, combatants)


def delay_play_campaign_encounter_turn(campaign_id, encounter_id, username, data):
    """Move the current combatant to a later initiative-order position."""
    if not isinstance(data, dict):
        raise BadRequest()
    new_index = integer(data.get("new_index"))
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        is_owner = campaign[0] == username
        if not is_owner and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        encounter = connection.execute(
            "SELECT round, turn_index, combatants FROM play_campaign_encounters "
            "WHERE id = ? AND campaign_id = ?", (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return None
        combatants = ordered_play_campaign_combatants(json.loads(encounter[2]))
        if not combatants:
            return None
        turn_index = encounter[1] % len(combatants)
        if not is_owner and combatants[turn_index].get("member") != username:
            raise OutOfTurn()
        if not turn_index < new_index < len(combatants):
            raise BadRequest()
        delayed = combatants.pop(turn_index)
        combatants.insert(new_index, delayed)
        # Initiative is the durable ordering source.  Reassign it deterministically
        # so subsequent status and advance requests see this exact ordering.
        for position, combatant in enumerate(combatants):
            combatant["initiative"] = 10000 - position
        connection.execute(
            "UPDATE play_campaign_encounters SET combatants = ?, turn_index = ? "
            "WHERE id = ? AND campaign_id = ?",
            (json.dumps(combatants, separators=(",", ":")), new_index,
             encounter_id, campaign_id),
        )
    return {"round": encounter[0], "turn_index": new_index,
            "order": [{"name": combatant["name"], "initiative": combatant["initiative"]}
                      for combatant in combatants]}


def ready_play_campaign_encounter_turn(campaign_id, encounter_id, username, data):
    """Record a current player combatant's ready trigger without changing order."""
    if not isinstance(data, dict):
        raise BadRequest()
    trigger = campaign_text(data.get("trigger"))
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        encounter = connection.execute(
            "SELECT turn_index, combatants FROM play_campaign_encounters "
            "WHERE id = ? AND campaign_id = ?", (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return None
        combatants = ordered_play_campaign_combatants(json.loads(encounter[1]))
        if not combatants:
            return None
        if combatants[encounter[0] % len(combatants)].get("member") != username:
            raise OutOfTurn()
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM ("
            "SELECT sequence FROM play_campaign_narrations WHERE campaign_id = ? "
            "UNION ALL "
            "SELECT sequence FROM play_campaign_actions WHERE campaign_id = ?"
            ")",
            (campaign_id, campaign_id),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_actions "
            "(campaign_id, sequence, actor, type, target, text) VALUES (?, ?, ?, 'ready', NULL, ?)",
            (campaign_id, sequence, username, trigger),
        )
    return {"actor": username, "trigger": trigger}


def submit_play_campaign_combat_action(campaign_id, encounter_id, actor, data):
    """Record an action for the current player combatant without advancing turns."""
    if not isinstance(data, dict):
        raise BadRequest()
    action_type = campaign_text(data.get("type"))
    target = campaign_text(data.get("target"))
    text = campaign_text(data.get("text"))
    if action_type not in ("attack", "help", "dodge", "ready"):
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, actor),
        ).fetchone() is None:
            raise PermissionError()
        encounter = connection.execute(
            "SELECT turn_index, combatants FROM play_campaign_encounters "
            "WHERE id = ? AND campaign_id = ? AND status = 'active'",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return None
        combatants = ordered_play_campaign_combatants(json.loads(encounter[1]))
        if not combatants:
            return None
        active = combatants[encounter[0] % len(combatants)]
        if active.get("member") != actor:
            raise OutOfTurn()
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM ("
            "SELECT sequence FROM play_campaign_narrations WHERE campaign_id = ? "
            "UNION ALL "
            "SELECT sequence FROM play_campaign_actions WHERE campaign_id = ?"
            ")",
            (campaign_id, campaign_id),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_actions "
            "(campaign_id, sequence, actor, type, target, text) VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, sequence, actor, action_type, target, text),
        )
    return {"sequence": sequence, "kind": "combat_action", "actor": actor,
            "type": action_type, "target": target, "text": text}


def update_play_campaign_document(campaign_id, owner, data):
    if not isinstance(data, dict):
        raise BadRequest()
    document = {key: campaign_text(data.get(key)) for key in ("story", "dm_notes")}
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        connection.execute(
            "INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, ?) "
            "ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story, dm_notes = excluded.dm_notes",
            (campaign_id, document["story"], document["dm_notes"]),
        )
    return document


def get_play_campaign_document(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        is_owner = campaign[0] == username
        if not is_owner and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        document = connection.execute(
            "SELECT story, dm_notes FROM play_campaign_documents WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
    if document is None:
        return None
    if is_owner:
        return {"story": document[0], "dm_notes": document[1]}
    return {"story": document[0]}


def append_play_campaign_replay_event(campaign_id, username, data):
    """Append one validated replay event in durable successful-append order."""
    if not isinstance(data, dict) or set(data) != {"event_id", "kind", "text"}:
        raise BadRequest()
    event_id = campaign_text(data["event_id"])
    kind = data["kind"]
    text = campaign_text(data["text"])
    if kind != "append":
        raise BadRequest()
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] != username and connection.execute(
                    "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                    (campaign_id, username),
            ).fetchone() is None:
                raise PermissionError()
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM play_campaign_replay_events WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_replay_events "
                "(campaign_id, sequence, event_id, kind, text) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, sequence, event_id, kind, text),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return {"event_id": event_id, "kind": kind, "text": text, "sequence": sequence}


def get_play_campaign_replay(campaign_id, username):
    """Rebuild public replay state solely from the ordered append stream."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != username and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        rows = connection.execute(
            "SELECT event_id, text FROM play_campaign_replay_events "
            "WHERE campaign_id = ? ORDER BY sequence", (campaign_id,)
        ).fetchall()
    event_ids = [row[0] for row in rows]
    story = "".join(row[1] for row in rows)
    return {"story": story, "event_ids": event_ids,
            "digest": ",".join(event_ids) + "|" + story}


def configure_play_campaign_rng_seed(campaign_id, username, data):
    """Set the campaign's one immutable deterministic RNG seed."""
    if not isinstance(data, dict) or set(data) != {"seed"}:
        raise BadRequest()
    seed = campaign_text(data["seed"])
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] != username:
                raise PermissionError()
            connection.execute(
                "INSERT INTO play_campaign_rng_seeds (campaign_id, seed) VALUES (?, ?)",
                (campaign_id, seed),
            )
    except sqlite3.IntegrityError:
        raise SeedAlreadyConfigured()
    return {"seed": seed, "rolls": []}


def rng_result(seed, sequence, roll_id, sides):
    """Calculate the specified portable unsigned-32-bit ledger result."""
    acc = 0
    material = f"{seed}|{sequence}|{roll_id}|{sides}".encode("utf-8")
    for byte in material:
        acc = (acc * 31 + byte) % (1 << 32)
    return (acc % sides) + 1


def append_play_campaign_rng_roll(campaign_id, username, data):
    """Append one member-authorized immutable, deterministic RNG record."""
    if not isinstance(data, dict) or set(data) != {"roll_id", "sides"}:
        raise BadRequest()
    roll_id = campaign_text(data["roll_id"])
    sides = integer(data["sides"])
    if not 2 <= sides <= 100:
        raise BadRequest()
    try:
        with DATABASE_LOCK, database() as connection:
            if play_campaign_actor(connection, campaign_id, username) is None:
                return None
            seed_row = connection.execute(
                "SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()
            if seed_row is None:
                raise SeedAlreadyConfigured()
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_rng_rolls "
                "WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()[0]
            result = rng_result(seed_row[0], sequence, roll_id, sides)
            connection.execute(
                "INSERT INTO play_campaign_rng_rolls "
                "(campaign_id, sequence, roll_id, sides, result) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, sequence, roll_id, sides, result),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    return {"roll_id": roll_id, "sides": sides, "result": result, "sequence": sequence}


def get_play_campaign_rng_ledger(campaign_id, username):
    """Read a member-visible ordered ledger; no independent outcome route exists."""
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, username) is None:
            return None
        seed_row = connection.execute(
            "SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
        if seed_row is None:
            return {"seed": None, "rolls": []}
        rows = connection.execute(
            "SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls "
            "WHERE campaign_id = ? ORDER BY sequence", (campaign_id,)
        ).fetchall()
    return {"seed": seed_row[0], "rolls": [
        {"roll_id": row[0], "sides": row[1], "result": row[2], "sequence": row[3]}
        for row in rows
    ]}


def moderation_report_fields(data):
    if not isinstance(data, dict) or set(data) != {"report_id", "target_id", "reason"}:
        raise BadRequest()
    return {key: campaign_text(data[key]) for key in ("report_id", "target_id", "reason")}


def moderation_resolution_fields(data):
    if not isinstance(data, dict) or set(data) != {"action", "note"}:
        raise BadRequest()
    action = data["action"]
    if action not in ("allow", "remove"):
        raise BadRequest()
    return {"action": action, "note": campaign_text(data["note"])}


def moderation_report_response(row):
    report = {"report_id": row[0], "target_id": row[1], "reason": row[2],
              "status": row[3], "reporter": row[4], "sequence": row[5]}
    if row[3] == "resolved":
        report.update({"action": row[6], "note": row[7], "resolver": row[8]})
    return report


def create_play_campaign_moderation_report(campaign_id, username, data):
    """Append one member-submitted immutable moderation report."""
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, username) is None:
            return None
        report = moderation_report_fields(data)
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_moderation_reports "
            "WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        try:
            connection.execute(
                "INSERT INTO play_campaign_moderation_reports "
                "(campaign_id, sequence, report_id, target_id, reason, status, reporter) "
                "VALUES (?, ?, ?, ?, ?, 'open', ?)",
                (campaign_id, sequence, report["report_id"], report["target_id"],
                 report["reason"], username),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    return {**report, "status": "open", "reporter": username, "sequence": sequence}


def list_play_campaign_moderation_reports(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, username) is None:
            return None
        rows = connection.execute(
            "SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver "
            "FROM play_campaign_moderation_reports WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()
    return {"reports": [moderation_report_response(row) for row in rows]}


def resolve_play_campaign_moderation_report(campaign_id, report_id, username, data):
    """Perform the report's sole allowed state transition, by the campaign DM."""
    with DATABASE_LOCK, database() as connection:
        is_dm = play_campaign_actor(connection, campaign_id, username)
        if is_dm is None:
            return None
        if not is_dm:
            raise PermissionError()
        row = connection.execute(
            "SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver "
            "FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?",
            (campaign_id, report_id),
        ).fetchone()
        if row is None:
            return None
        if row[3] != "open":
            raise DuplicateRecord()
        resolution = moderation_resolution_fields(data)
        connection.execute(
            "UPDATE play_campaign_moderation_reports SET status = 'resolved', action = ?, "
            "note = ?, resolver = ? WHERE campaign_id = ? AND report_id = ?",
            (resolution["action"], resolution["note"], username, campaign_id, report_id),
        )
    return {"report_id": row[0], "target_id": row[1], "reason": row[2],
            "status": "resolved", "reporter": row[4], "sequence": row[5],
            "action": resolution["action"], "note": resolution["note"], "resolver": username}


def create_play_campaign_backup(campaign_id, owner):
    """Capture the DM-visible campaign state in an immutable named snapshot."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        document = connection.execute(
            "SELECT story FROM play_campaign_documents WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
        if document is None:
            return None
        sequence = connection.execute(
            "SELECT COALESCE(MAX(CAST(SUBSTR(backup_id, 8) AS INTEGER)), 0) + 1 "
            "FROM play_campaign_backups WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        snapshot = {"backup_id": f"backup-{sequence}", "story": document[0],
                    "status": campaign[1]}
        connection.execute(
            "INSERT INTO play_campaign_backups (campaign_id, backup_id, story, status) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, snapshot["backup_id"], snapshot["story"], snapshot["status"]),
        )
    return snapshot


def list_play_campaign_backups(campaign_id, owner):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        rows = connection.execute(
            "SELECT backup_id, story, status FROM play_campaign_backups "
            "WHERE campaign_id = ? "
            "ORDER BY CAST(SUBSTR(backup_id, 8) AS INTEGER)", (campaign_id,)
        ).fetchall()
    return {"backups": [{"backup_id": row[0], "story": row[1], "status": row[2]}
                        for row in rows]}


def restore_play_campaign_backup(campaign_id, backup_id, owner):
    """Apply one existing backup without changing the saved snapshot."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        row = connection.execute(
            "SELECT backup_id, story, status FROM play_campaign_backups "
            "WHERE campaign_id = ? AND backup_id = ?", (campaign_id, backup_id),
        ).fetchone()
        if row is None:
            return None
        snapshot = {"backup_id": row[0], "story": row[1], "status": row[2]}
        connection.execute(
            "UPDATE play_campaigns SET status = ? WHERE id = ?",
            (snapshot["status"], campaign_id),
        )
        connection.execute(
            "INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, '') "
            "ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story",
            (campaign_id, snapshot["story"]),
        )
    return snapshot


def create_play_campaign_export(campaign_id, owner):
    """Persist a numbered public-story snapshot for the campaign DM."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        document = connection.execute(
            "SELECT story FROM play_campaign_documents WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
        if document is None:
            return None
        version = connection.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM play_campaign_exports "
            "WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        snapshot = {"version": version, "story": document[0], "status": campaign[1]}
        connection.execute(
            "INSERT INTO play_campaign_exports (campaign_id, version, story, status) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, snapshot["version"], snapshot["story"], snapshot["status"]),
        )
    return snapshot


def list_play_campaign_exports(campaign_id, owner):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        rows = connection.execute(
            "SELECT version, story, status FROM play_campaign_exports "
            "WHERE campaign_id = ? ORDER BY version", (campaign_id,)
        ).fetchall()
    return {"exports": [{"version": row[0], "story": row[1], "status": row[2]} for row in rows]}


def get_play_campaign_export(campaign_id, version, owner):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        row = connection.execute(
            "SELECT version, story, status FROM play_campaign_exports "
            "WHERE campaign_id = ? AND version = ?", (campaign_id, version),
        ).fetchone()
    if row is None:
        return None
    return {"version": row[0], "story": row[1], "status": row[2]}


def import_play_campaign_snapshot(campaign_id, owner, data):
    """Apply a compatible snapshot and retain the imported state together."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        if (not isinstance(data, dict) or set(data) != {"version", "story", "status"}
                or isinstance(data["version"], bool) or data["version"] != 1
                or not isinstance(data["version"], int)
                or not isinstance(data["story"], str) or not data["story"]
                or not isinstance(data["status"], str)
                or data["status"] not in ("lobby", "started")):
            raise BadRequest()
        snapshot = {"version": 1, "story": data["story"], "status": data["status"]}
        connection.execute(
            "UPDATE play_campaigns SET status = ? WHERE id = ?",
            (snapshot["status"], campaign_id),
        )
        connection.execute(
            "INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) "
            "VALUES (?, ?, '') ON CONFLICT(campaign_id) DO UPDATE SET "
            "story = excluded.story",
            (campaign_id, snapshot["story"]),
        )
        connection.execute(
            "INSERT INTO play_campaign_import_state (campaign_id, version, story, status) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET "
            "version = excluded.version, story = excluded.story, status = excluded.status",
            (campaign_id, snapshot["version"], snapshot["story"], snapshot["status"]),
        )
    return snapshot


def get_play_campaign_import_state(campaign_id, owner):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        row = connection.execute(
            "SELECT version, story, status FROM play_campaign_import_state WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    if row is None:
        return None
    return {"version": row[0], "story": row[1], "status": row[2]}


def migrate_play_campaign_snapshot(campaign_id, owner, data):
    """Convert a version-one snapshot into the campaign's version-two state."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT name, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None, False
        if campaign[1] != owner:
            raise PermissionError()
        if (not isinstance(data, dict) or "schema_version" not in data or "story" not in data
                or isinstance(data["schema_version"], bool)
                or not isinstance(data["schema_version"], int)
                or data["schema_version"] != 1
                or not isinstance(data["story"], str) or not data["story"]):
            raise BadRequest()
        source_story = data["story"]
        row = connection.execute(
            "SELECT source_schema_version, source_story, schema_version, story, campaign_name "
            "FROM play_campaign_migration_state WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
        if row is not None and row[0] == 1 and row[1] == source_story:
            return {"schema_version": row[2], "story": row[3], "campaign_name": row[4]}, False
        state = {"schema_version": 2, "story": source_story, "campaign_name": campaign[0]}
        connection.execute(
            "INSERT INTO play_campaign_migration_state "
            "(campaign_id, source_schema_version, source_story, schema_version, story, campaign_name) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET "
            "source_schema_version = excluded.source_schema_version, source_story = excluded.source_story, "
            "schema_version = excluded.schema_version, story = excluded.story, "
            "campaign_name = excluded.campaign_name",
            (campaign_id, 1, source_story, state["schema_version"], state["story"],
             state["campaign_name"]),
        )
    return state, True


def play_campaign_dm_exists(campaign_id, owner):
    """Check DM access before a mutation request body is decoded."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
    if campaign is None:
        return False
    if campaign[0] != owner:
        raise PermissionError()
    return True


def set_service_maintenance(enabled):
    """Set the process-local service mode used by the public readiness probe."""
    global SERVICE_MAINTENANCE
    if type(enabled) is not bool:
        raise BadRequest()
    with SERVICE_MODE_LOCK:
        SERVICE_MAINTENANCE = enabled
        return {"maintenance": SERVICE_MAINTENANCE}


def service_maintenance_enabled():
    """Read the process-local maintenance switch safely for threaded requests."""
    with SERVICE_MODE_LOCK:
        return SERVICE_MAINTENANCE


def get_play_campaign_migration_state(campaign_id, owner):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        row = connection.execute(
            "SELECT schema_version, story, campaign_name "
            "FROM play_campaign_migration_state WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
    if row is None:
        return None
    return {"schema_version": row[0], "story": row[1], "campaign_name": row[2]}


def create_play_campaign_scene(campaign_id, owner, data):
    if not isinstance(data, dict):
        raise BadRequest()
    scene = {key: campaign_text(data.get(key)) for key in ("id", "name")}
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        try:
            connection.execute(
                "INSERT INTO play_campaign_scenes (campaign_id, id, name, status) "
                "VALUES (?, ?, ?, 'open')",
                (campaign_id, scene["id"], scene["name"]),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    return {"id": scene["id"], "name": scene["name"], "status": "open"}


def enter_play_campaign_scene(campaign_id, scene_id, owner):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        scene = connection.execute(
            "SELECT name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?",
            (campaign_id, scene_id),
        ).fetchone()
        if scene is None:
            return None
        if scene[1] != "open":
            raise DuplicateRecord()
        connection.execute(
            "INSERT INTO play_campaign_scene_state (campaign_id, current_scene_id) VALUES (?, ?) "
            "ON CONFLICT(campaign_id) DO UPDATE SET current_scene_id = excluded.current_scene_id",
            (campaign_id, scene_id),
        )
    return {"current_scene_id": scene_id, "name": scene[0]}


def close_play_campaign_scene(campaign_id, scene_id, owner):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        scene = connection.execute(
            "SELECT 1 FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?",
            (campaign_id, scene_id),
        ).fetchone()
        if scene is None:
            return None
        connection.execute(
            "UPDATE play_campaign_scenes SET status = 'closed' WHERE campaign_id = ? AND id = ?",
            (campaign_id, scene_id),
        )
        connection.execute(
            "DELETE FROM play_campaign_scene_state WHERE campaign_id = ? AND current_scene_id = ?",
            (campaign_id, scene_id),
        )
    return {"id": scene_id, "status": "closed"}


def current_play_campaign_scene(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != username and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        scene = connection.execute(
            "SELECT scenes.id, scenes.name, scenes.status "
            "FROM play_campaign_scene_state AS state "
            "JOIN play_campaign_scenes AS scenes "
            "ON scenes.campaign_id = state.campaign_id AND scenes.id = state.current_scene_id "
            "WHERE state.campaign_id = ? AND scenes.status = 'open'",
            (campaign_id,),
        ).fetchone()
    if scene is None:
        return None
    return {"id": scene[0], "name": scene[1], "status": scene[2]}


def create_play_campaign_location(campaign_id, owner, data):
    if not isinstance(data, dict):
        raise BadRequest()
    location = {key: campaign_text(data.get(key)) for key in ("id", "name")}
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        try:
            connection.execute(
                "INSERT INTO play_campaign_locations (campaign_id, id, name) VALUES (?, ?, ?)",
                (campaign_id, location["id"], location["name"]),
            )
            # A campaign begins exploring from its first declared location.
            connection.execute(
                "INSERT INTO play_campaign_location_state (campaign_id, current_location_id) "
                "VALUES (?, ?) ON CONFLICT(campaign_id) DO NOTHING",
                (campaign_id, location["id"]),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    return location


def settlement_services(value):
    if not isinstance(value, list) or not value:
        raise BadRequest()
    services = []
    for service in value:
        if not isinstance(service, str):
            raise BadRequest()
        service = service.strip()
        if not service:
            raise BadRequest()
        services.append(service)
    if len(set(services)) != len(services):
        raise BadRequest()
    return services


def settlement_fields(data, include_id):
    if not isinstance(data, dict):
        raise BadRequest()
    fields = {"name": campaign_text(data.get("name")),
              "services": settlement_services(data.get("services")),
              "availability": campaign_text(data.get("availability"))}
    if fields["availability"] not in ("open", "limited", "closed"):
        raise BadRequest()
    if include_id:
        fields["settlement_id"] = campaign_text(data.get("settlement_id"))
    return fields


def settlement_response(settlement, discoveries, character_id=None):
    return {"settlement_id": settlement[0], "name": settlement[1],
            "services": json.loads(settlement[2]), "availability": settlement[3],
            "discovered_by": discoveries if character_id is None else [character_id]}


def create_play_campaign_settlement(campaign_id, owner, data):
    settlement = settlement_fields(data, True)
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        try:
            connection.execute(
                "INSERT INTO play_campaign_settlements "
                "(campaign_id, settlement_id, name, services, availability) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, settlement["settlement_id"], settlement["name"],
                 json.dumps(settlement["services"], separators=(",", ":")),
                 settlement["availability"]),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    return {**settlement, "discovered_by": []}


def update_play_campaign_settlement(campaign_id, settlement_id, owner, data):
    settlement = settlement_fields(data, False)
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        existing = connection.execute(
            "SELECT settlement_id FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?",
            (campaign_id, settlement_id),
        ).fetchone()
        if existing is None:
            return None
        connection.execute(
            "UPDATE play_campaign_settlements SET name = ?, services = ?, availability = ? "
            "WHERE campaign_id = ? AND settlement_id = ?",
            (settlement["name"], json.dumps(settlement["services"], separators=(",", ":")),
             settlement["availability"], campaign_id, settlement_id),
        )
        discoveries = [row[0] for row in connection.execute(
            "SELECT character_id FROM play_campaign_settlement_discoveries "
            "WHERE campaign_id = ? AND settlement_id = ? ORDER BY rowid", (campaign_id, settlement_id)
        )]
    return {"settlement_id": settlement_id, **settlement, "discovered_by": discoveries}


def discover_play_campaign_settlement(campaign_id, settlement_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] == username:
            raise PermissionError()
        member = connection.execute(
            "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if member is None:
            raise PermissionError()
        settlement = connection.execute(
            "SELECT settlement_id, name, services, availability FROM play_campaign_settlements "
            "WHERE campaign_id = ? AND settlement_id = ?", (campaign_id, settlement_id)
        ).fetchone()
        if settlement is None:
            return None
        try:
            connection.execute(
                "INSERT INTO play_campaign_settlement_discoveries "
                "(campaign_id, settlement_id, character_id) VALUES (?, ?, ?)",
                (campaign_id, settlement_id, member[0]),
            )
            created = True
        except sqlite3.IntegrityError:
            created = False
    return settlement_response(settlement, [], member[0]), created


def list_play_campaign_settlements(campaign_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] == username:
            settlements = connection.execute(
                "SELECT settlement_id, name, services, availability FROM play_campaign_settlements "
                "WHERE campaign_id = ? ORDER BY rowid", (campaign_id,)
            ).fetchall()
            return {"settlements": [settlement_response(settlement, [row[0] for row in connection.execute(
                "SELECT character_id FROM play_campaign_settlement_discoveries "
                "WHERE campaign_id = ? AND settlement_id = ? ORDER BY rowid",
                (campaign_id, settlement[0]))]) for settlement in settlements]}
        member = connection.execute(
            "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if member is None:
            raise PermissionError()
        settlements = connection.execute(
            "SELECT s.settlement_id, s.name, s.services, s.availability "
            "FROM play_campaign_settlements AS s JOIN play_campaign_settlement_discoveries AS d "
            "ON d.campaign_id = s.campaign_id AND d.settlement_id = s.settlement_id "
            "WHERE s.campaign_id = ? AND d.character_id = ? ORDER BY s.rowid",
            (campaign_id, member[0]),
        ).fetchall()
    return {"settlements": [settlement_response(settlement, [], member[0]) for settlement in settlements]}


def shop_fields(data):
    if not isinstance(data, dict):
        raise BadRequest()
    shop_id = campaign_text(data.get("shop_id"))
    name = campaign_text(data.get("name"))
    stock = data.get("stock")
    buy_price = integer(data.get("buy_price"))
    sell_price = integer(data.get("sell_price"))
    if not isinstance(stock, dict) or not stock or buy_price < 1 or sell_price < 0:
        raise BadRequest()
    normalized_stock = {}
    for item_id, quantity in stock.items():
        if item_id not in PLAY_INVENTORY_ITEM_IDS or integer(quantity) < 1:
            raise BadRequest()
        normalized_stock[item_id] = quantity
    return {"shop_id": shop_id, "name": name, "stock": normalized_stock,
            "buy_price": buy_price, "sell_price": sell_price}


def shop_response(shop):
    return {"shop_id": shop[0], "name": shop[1], "stock": json.loads(shop[2]),
            "buy_price": shop[3], "sell_price": shop[4]}


def create_play_campaign_shop(campaign_id, settlement_id, owner, data):
    shop = shop_fields(data)
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute("SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        if connection.execute(
                "SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?",
                (campaign_id, settlement_id)).fetchone() is None:
            return None
        try:
            connection.execute(
                "INSERT INTO play_campaign_shops "
                "(campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (campaign_id, settlement_id, shop["shop_id"], shop["name"],
                 json.dumps(shop["stock"], separators=(",", ":")), shop["buy_price"], shop["sell_price"]),
            )
        except sqlite3.IntegrityError:
            raise DuplicateRecord()
    return shop


def get_play_campaign_shop(campaign_id, settlement_id, shop_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute("SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if campaign is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?",
                (campaign_id, settlement_id)).fetchone() is None:
            return None
        shop = connection.execute(
            "SELECT shop_id, name, stock, buy_price, sell_price FROM play_campaign_shops "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (campaign_id, settlement_id, shop_id)).fetchone()
        if shop is None:
            return None
        if campaign[0] != username:
            member = connection.execute(
                "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username)).fetchone()
            if member is None:
                raise PermissionError()
            if connection.execute(
                    "SELECT 1 FROM play_campaign_settlement_discoveries "
                    "WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?",
                    (campaign_id, settlement_id, member[0])).fetchone() is None:
                return None
    return shop_response(shop)


def trade_play_campaign_shop(campaign_id, settlement_id, shop_id, username, data, buying):
    if not isinstance(data, dict):
        raise BadRequest()
    character_id = campaign_text(data.get("character_id"))
    item_id = data.get("item_id")
    quantity = integer(data.get("quantity"))
    if item_id not in PLAY_INVENTORY_ITEM_IDS or quantity < 1:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        if connection.execute("SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)).fetchone() is None:
            return None
        if connection.execute(
                "SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?",
                (campaign_id, settlement_id)).fetchone() is None:
            return None
        shop = connection.execute(
            "SELECT stock, buy_price, sell_price FROM play_campaign_shops "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (campaign_id, settlement_id, shop_id)).fetchone()
        if shop is None:
            return None
        owner = connection.execute(
            "SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id)).fetchone()
        if owner is None:
            return None
        if owner[0] != username:
            raise PermissionError()
        stock, buy_price, sell_price = json.loads(shop[0]), shop[1], shop[2]
        held = connection.execute(
            "SELECT quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id)).fetchone()
        gold = connection.execute(
            "SELECT gold FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id)).fetchone()
        if gold is None:
            return None
        if buying:
            if stock.get(item_id, 0) < quantity:
                raise InsufficientStock()
            cost = buy_price * quantity
            if gold[0] < cost:
                raise InsufficientGold()
            stock[item_id] -= quantity
            new_gold = gold[0] - cost
            connection.execute(
                "INSERT INTO play_campaign_character_inventory_items "
                "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity",
                (campaign_id, character_id, item_id, quantity))
        else:
            if held is None or held[0] < quantity:
                raise InsufficientInventory()
            stock[item_id] = stock.get(item_id, 0) + quantity
            new_gold = gold[0] + sell_price * quantity
            if held[0] == quantity:
                connection.execute("DELETE FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?", (campaign_id, character_id, item_id))
            else:
                connection.execute("UPDATE play_campaign_character_inventory_items SET quantity = quantity - ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?", (quantity, campaign_id, character_id, item_id))
        connection.execute("UPDATE play_campaign_character_currency SET gold = ? WHERE campaign_id = ? AND character_id = ?", (new_gold, campaign_id, character_id))
        connection.execute("UPDATE play_campaign_shops SET stock = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?", (json.dumps(stock, separators=(",", ":")), campaign_id, settlement_id, shop_id))
    return {"character_id": character_id, "item_id": item_id, "quantity": quantity,
            "gold": new_gold, "stock": stock[item_id]}


def create_play_campaign_location_connection(campaign_id, from_id, owner, data):
    if not isinstance(data, dict):
        raise BadRequest()
    to_id = campaign_text(data.get("to_id"))
    travel_turns = integer(data.get("travel_turns"))
    if travel_turns < 1:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        endpoints = connection.execute(
            "SELECT id FROM play_campaign_locations WHERE campaign_id = ? AND id IN (?, ?)",
            (campaign_id, from_id, to_id),
        ).fetchall()
        if {row[0] for row in endpoints} != {from_id, to_id}:
            raise BadRequest()
        try:
            connection.execute(
                "INSERT INTO play_campaign_location_connections "
                "(campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)",
                (campaign_id, from_id, to_id, travel_turns),
            )
        except sqlite3.IntegrityError:
            raise BadRequest()
    return {"from_id": from_id, "to_id": to_id, "travel_turns": travel_turns}


def play_campaign_location_travel(campaign_id, location_id, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != username and connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
        ).fetchone() is None:
            raise PermissionError()
        if connection.execute(
                "SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?",
                (campaign_id, location_id),
        ).fetchone() is None:
            return None
        destinations = connection.execute(
            "SELECT locations.id, locations.name, connections.travel_turns "
            "FROM play_campaign_location_connections AS connections "
            "JOIN play_campaign_locations AS locations "
            "ON locations.campaign_id = connections.campaign_id AND locations.id = connections.to_id "
            "WHERE connections.campaign_id = ? AND connections.from_id = ? "
            "ORDER BY connections.rowid",
            (campaign_id, location_id),
        ).fetchall()
    return {"destinations": [{"id": row[0], "name": row[1], "travel_turns": row[2]}
                             for row in destinations]}


def travel_play_campaign_turn(campaign_id, actor, data):
    """Use the active player's exploration turn to traverse one outbound edge."""
    if not isinstance(data, dict):
        raise BadRequest()
    destination_id = campaign_text(data.get("destination_id"))
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        players = connection.execute(
            "SELECT username FROM play_campaign_members WHERE campaign_id = ? "
            "ORDER BY rowid", (campaign_id,)
        ).fetchall()
        resolutions = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_actions "
            "WHERE campaign_id = ? AND type = 'resolution'", (campaign_id,)
        ).fetchone()[0]
        pending_action = connection.execute(
            "SELECT type FROM play_campaign_actions WHERE campaign_id = ? "
            "ORDER BY sequence DESC LIMIT 1", (campaign_id,)
        ).fetchone()
        active_player = players[resolutions % len(players)][0] if players else None
        if (campaign[0] != "active" or actor != active_player
                or (pending_action is not None and pending_action[0] != "resolution")):
            raise DuplicateRecord()
        location = connection.execute(
            "SELECT current_location_id FROM play_campaign_location_state WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if location is None:
            raise DuplicateRecord()
        edge = connection.execute(
            "SELECT travel_turns FROM play_campaign_location_connections "
            "WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
            (campaign_id, location[0], destination_id),
        ).fetchone()
        if edge is None:
            raise DuplicateRecord()
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 + ("
            "SELECT COUNT(*) FROM play_campaign_locations WHERE campaign_id = ?"
            ") FROM ("
            "SELECT sequence FROM play_campaign_narrations WHERE campaign_id = ? "
            "UNION ALL "
            "SELECT sequence FROM play_campaign_actions WHERE campaign_id = ?"
            ")",
            (campaign_id, campaign_id, campaign_id),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_actions (campaign_id, sequence, actor, type, text) "
            "VALUES (?, ?, ?, 'travel', ?)",
            (campaign_id, sequence, actor, destination_id),
        )
        connection.execute(
            "UPDATE play_campaign_location_state SET current_location_id = ? WHERE campaign_id = ?",
            (destination_id, campaign_id),
        )
    return {"sequence": sequence, "kind": "travel", "actor": actor,
            "destination_id": destination_id, "travel_turns": edge[0], "next_actor": "dm"}


def rest_play_campaign_turn(campaign_id, actor, data):
    """Use the active player's exploration turn to take a short or long rest."""
    if not isinstance(data, dict) or data.get("type") not in ("short", "long"):
        raise BadRequest()
    rest_type = data["type"]
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        players = connection.execute(
            "SELECT username FROM play_campaign_members WHERE campaign_id = ? "
            "ORDER BY rowid", (campaign_id,)
        ).fetchall()
        resolutions = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_actions "
            "WHERE campaign_id = ? AND type = 'resolution'", (campaign_id,)
        ).fetchone()[0]
        pending_action = connection.execute(
            "SELECT type FROM play_campaign_actions WHERE campaign_id = ? "
            "ORDER BY sequence DESC LIMIT 1", (campaign_id,)
        ).fetchone()
        active_player = players[resolutions % len(players)][0] if players else None
        if (campaign[0] != "active" or actor != active_player
                or (pending_action is not None and pending_action[0] != "resolution")):
            raise DuplicateRecord()
        health = connection.execute(
            "SELECT hp_current, hp_max FROM play_campaign_health "
            "WHERE campaign_id = ? AND username = ?", (campaign_id, actor)
        ).fetchone()
        if health is None:
            raise DuplicateRecord()
        hp_current, hp_max = health
        if rest_type == "long":
            hp_current = hp_max
            connection.execute(
                "UPDATE play_campaign_health SET hp_current = ? "
                "WHERE campaign_id = ? AND username = ?", (hp_current, campaign_id, actor)
            )
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM ("
            "SELECT sequence FROM play_campaign_narrations WHERE campaign_id = ? "
            "UNION ALL "
            "SELECT sequence FROM play_campaign_actions WHERE campaign_id = ?"
            ")",
            (campaign_id, campaign_id),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_actions (campaign_id, sequence, actor, type, text) "
            "VALUES (?, ?, ?, 'rest', ?)",
            (campaign_id, sequence, actor, rest_type),
        )
    return {"sequence": sequence, "kind": "rest", "actor": actor,
            "type": rest_type, "hp_current": hp_current, "hp_max": hp_max,
            "next_actor": "dm"}


def start_play_campaign(campaign_id, owner):
    """Atomically move an owner's ready lobby into its first player turn."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        party_size = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        if campaign[1] != "lobby" or party_size < 2:
            raise DuplicateRecord()
        current_actor = connection.execute(
            "SELECT username FROM play_campaign_members WHERE campaign_id = ? "
            "ORDER BY rowid LIMIT 1", (campaign_id,)
        ).fetchone()[0]
        connection.execute(
            "UPDATE play_campaigns SET status = 'active' WHERE id = ?", (campaign_id,)
        )
    return {"id": campaign_id, "status": "active", "current_actor": current_actor,
            "turn_number": 1}


def play_campaign_turn(campaign_id, username):
    """Return the active turn and its deterministic exploration queue."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        member = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if username != campaign[0] and member is None:
            raise PermissionError()
        if campaign[1] != "active":
            return None
        members = connection.execute(
            "SELECT username FROM play_campaign_members WHERE campaign_id = ? "
            "ORDER BY rowid", (campaign_id,)
        ).fetchall()
        resolutions = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_actions "
            "WHERE campaign_id = ? AND type = 'resolution'", (campaign_id,)
        ).fetchone()[0]
        last_action = connection.execute(
            "SELECT type FROM play_campaign_actions WHERE campaign_id = ? "
            "ORDER BY sequence DESC LIMIT 1", (campaign_id,)
        ).fetchone()
        aftermath = connection.execute(
            "SELECT 1 FROM play_campaign_encounters "
            "WHERE campaign_id = ? AND status = 'closed'", (campaign_id,)
        ).fetchone() is not None
    current_actor = (campaign[0] if aftermath or (last_action is not None and last_action[0] != "resolution")
                     else members[resolutions % len(members)][0])
    queue = [actor for member in members for actor in (member[0], "dm")]
    return {"campaign_id": campaign_id, "current_actor": current_actor,
            "phase": "exploration" if aftermath else (
                "dm" if current_actor == campaign[0] else "player"
            ),
            "turn_number": resolutions + 1, "queue": queue, "overdue": False,
            "logical_deadline": resolutions + 2}


def nudge_play_campaign_turn(campaign_id, owner, data):
    """Persist an owner nudge for the current deterministic turn target."""
    if not isinstance(data, dict):
        raise BadRequest()
    message = campaign_text(data.get("message"))
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None or campaign[1] != "active":
            return None
        if campaign[0] != owner:
            raise PermissionError()
        members = connection.execute(
            "SELECT username FROM play_campaign_members WHERE campaign_id = ? "
            "ORDER BY rowid", (campaign_id,)
        ).fetchall()
        resolutions = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_actions "
            "WHERE campaign_id = ? AND type = 'resolution'", (campaign_id,)
        ).fetchone()[0]
        last_action = connection.execute(
            "SELECT type FROM play_campaign_actions WHERE campaign_id = ? "
            "ORDER BY sequence DESC LIMIT 1", (campaign_id,)
        ).fetchone()
        target = (owner if last_action is not None and last_action[0] != "resolution"
                  else members[resolutions % len(members)][0])
        nudge_count = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_nudges WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0] + 1
        connection.execute(
            "INSERT INTO play_campaign_nudges "
            "(campaign_id, nudge_count, actor, target, message) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, nudge_count, owner, target, message),
        )
    return {"actor": owner, "target": target, "message": message,
            "nudge_count": nudge_count}


def play_campaign_my_turn(campaign_id, username):
    """Return a player's own safe context for the active exploration turn."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None or campaign[1] != "active":
            return None
        character = connection.execute(
            "SELECT character_id, name FROM play_campaign_members "
            "WHERE campaign_id = ? AND username = ?", (campaign_id, username)
        ).fetchone()
        if character is None:
            raise PermissionError()
        current_actor = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_actions "
            "WHERE campaign_id = ? AND type = 'resolution'", (campaign_id,)
        ).fetchone()[0]
        members = connection.execute(
            "SELECT username FROM play_campaign_members WHERE campaign_id = ? "
            "ORDER BY rowid", (campaign_id,)
        ).fetchall()
        last_action = connection.execute(
            "SELECT type FROM play_campaign_actions WHERE campaign_id = ? "
            "ORDER BY sequence DESC LIMIT 1", (campaign_id,)
        ).fetchone()
        # Fetch newest events first for an efficient bounded read, then restore
        # their public chronological order.  Narration rows have no private
        # document fields, so this projection is safe for players.
        events = connection.execute(
            "SELECT sequence, actor, text FROM play_campaign_narrations "
            "WHERE campaign_id = ? ORDER BY sequence DESC LIMIT 5", (campaign_id,)
        ).fetchall()
    recent_events = [
        {"sequence": row[0], "kind": "narration", "actor": row[1], "text": row[2]}
        for row in reversed(events)
    ]
    current_actor = campaign[0] if last_action is not None and last_action[0] != "resolution" else members[current_actor % len(members)][0]
    return {"is_my_turn": username == current_actor, "current_actor": current_actor,
            "character": {"id": character[0], "name": character[1]},
            "recent_events": recent_events}


def play_campaign_gm_status(campaign_id, owner):
    """Return the owner's complete, deterministic view of an active campaign."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None or campaign[1] != "active":
            return None
        if campaign[0] != owner:
            raise PermissionError()
        members = connection.execute(
            "SELECT username, character_id, name, class FROM play_campaign_members "
            "WHERE campaign_id = ? ORDER BY rowid", (campaign_id,)
        ).fetchall()
        events = connection.execute(
            "SELECT sequence, actor, text FROM play_campaign_narrations "
            "WHERE campaign_id = ? ORDER BY sequence DESC LIMIT 5", (campaign_id,)
        ).fetchall()
    with DATABASE_LOCK, database() as connection:
        resolutions = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_actions "
            "WHERE campaign_id = ? AND type = 'resolution'", (campaign_id,)
        ).fetchone()[0]
        last_action = connection.execute(
            "SELECT type FROM play_campaign_actions WHERE campaign_id = ? "
            "ORDER BY sequence DESC LIMIT 1", (campaign_id,)
        ).fetchone()
    current_actor = owner if last_action is not None and last_action[0] != "resolution" else members[resolutions % len(members)][0]
    recent_events = [
        {"sequence": row[0], "kind": "narration", "actor": row[1], "text": row[2]}
        for row in reversed(events)
    ]
    return {"needs_attention": current_actor == owner, "current_actor": current_actor,
            "party": [{"username": row[0], "character_id": row[1], "name": row[2], "class": row[3]}
                      for row in members],
            "recent_events": recent_events}


def append_play_campaign_narration(campaign_id, actor, data):
    """Append an owner- or delegated-narrator-owned campaign event."""
    if not isinstance(data, dict):
        raise BadRequest()
    text = campaign_text(data.get("text"))
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        delegated = connection.execute(
            "SELECT 1 FROM play_campaign_delegations "
            "WHERE campaign_id = ? AND username = ? AND active = 1 AND powers = ?",
            (campaign_id, actor, json.dumps(["narrate"])),
        ).fetchone() is not None
        if campaign[0] != actor and not delegated:
            raise PermissionError()
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM ("
            "SELECT sequence FROM play_campaign_narrations WHERE campaign_id = ? "
            "UNION ALL "
            "SELECT sequence FROM play_campaign_actions WHERE campaign_id = ?"
            ")",
            (campaign_id, campaign_id),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_narrations (campaign_id, sequence, actor, text) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, sequence, actor, text),
        )
    return {"sequence": sequence, "kind": "narration", "actor": actor, "text": text}


def create_play_campaign_message(campaign_id, username, data):
    """Append a member-visible chat event without exposing it to spectators."""
    if not isinstance(data, dict) or set(data) != {"text"}:
        raise BadRequest()
    text = campaign_text(data["text"])
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, username) is None:
            return None
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM ("
            "SELECT sequence FROM play_campaign_narrations WHERE campaign_id = ? "
            "UNION ALL "
            "SELECT sequence FROM play_campaign_actions WHERE campaign_id = ?"
            ")",
            (campaign_id, campaign_id),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_narrations (campaign_id, sequence, actor, text) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, sequence, username, text),
        )
    return {"kind": "chat", "actor": username, "text": text}


def delegation_fields(data):
    if not isinstance(data, dict) or set(data) != {"username", "powers"}:
        raise BadRequest()
    username = data["username"]
    powers = data["powers"]
    if (not isinstance(username, str) or not USERNAME.fullmatch(username)
            or not isinstance(powers, list) or not powers
            or len(powers) != len(set(powers)) or any(power != "narrate" for power in powers)):
        raise BadRequest()
    return username, powers


def delegation_response(username, powers, active):
    return {"username": username, "powers": powers, "active": bool(active)}


def grant_play_campaign_delegation(campaign_id, owner, data):
    username, powers = delegation_fields(data)
    powers_json = json.dumps(powers, separators=(",", ":"))
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        if connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone() is None:
            raise BadRequest()
        current = connection.execute(
            "SELECT active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if current is not None and current[0]:
            raise DuplicateRecord()
        connection.execute(
            "INSERT INTO play_campaign_delegations (campaign_id, username, powers, active) "
            "VALUES (?, ?, ?, 1) ON CONFLICT(campaign_id, username) DO UPDATE SET "
            "powers = excluded.powers, active = 1",
            (campaign_id, username, powers_json),
        )
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_delegation_audit "
            "WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_delegation_audit "
            "(campaign_id, sequence, username, action, powers) VALUES (?, ?, ?, 'granted', ?)",
            (campaign_id, sequence, username, powers_json),
        )
    return delegation_response(username, powers, True)


def revoke_play_campaign_delegation(campaign_id, owner, username):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        delegation = connection.execute(
            "SELECT powers, active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if delegation is None or not delegation[1]:
            raise BadRequest()
        powers = json.loads(delegation[0])
        connection.execute(
            "UPDATE play_campaign_delegations SET active = 0 WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        )
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_delegation_audit "
            "WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_delegation_audit "
            "(campaign_id, sequence, username, action, powers) VALUES (?, ?, ?, 'revoked', ?)",
            (campaign_id, sequence, username, delegation[0]),
        )
    return delegation_response(username, powers, False)


def play_campaign_delegation_audit(campaign_id, owner):
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        rows = connection.execute(
            "SELECT username, action, powers FROM play_campaign_delegation_audit "
            "WHERE campaign_id = ? ORDER BY sequence", (campaign_id,)
        ).fetchall()
    return {"entries": [{"username": row[0], "action": row[1], "powers": json.loads(row[2])}
                        for row in rows]}


def audit_event_fields(data):
    if not isinstance(data, dict) or set(data) != {"kind", "correlation_id"}:
        raise BadRequest()
    kind = data["kind"]
    correlation_id = data["correlation_id"]
    if (not isinstance(kind, str) or not kind
            or not isinstance(correlation_id, str) or not correlation_id):
        raise BadRequest()
    return kind, correlation_id


def create_play_campaign_audit_event(campaign_id, actor, data):
    """Append a campaign member's immutable, correlated audit event."""
    kind, correlation_id = audit_event_fields(data)
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        is_owner = campaign[0] == actor
        if not is_owner and connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone() is None:
            raise PermissionError()
        if connection.execute(
            "SELECT 1 FROM play_campaign_audit_events "
            "WHERE campaign_id = ? AND correlation_id = ?",
            (campaign_id, correlation_id),
        ).fetchone() is not None:
            raise DuplicateRecord()
        timestamp = connection.execute(
            "SELECT COALESCE(MAX(timestamp), 0) + 1 FROM play_campaign_audit_events "
            "WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        role = "DM" if is_owner else "player"
        connection.execute(
            "INSERT INTO play_campaign_audit_events "
            "(campaign_id, timestamp, kind, actor, role, correlation_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, timestamp, kind, actor, role, correlation_id),
        )
    return {"kind": kind, "actor": actor, "role": role,
            "timestamp": timestamp, "correlation_id": correlation_id}


def list_play_campaign_audit_events(campaign_id, actor):
    """Return the immutable audit trail to its campaign owner only."""
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != actor:
            raise PermissionError()
        rows = connection.execute(
            "SELECT kind, actor, role, timestamp, correlation_id "
            "FROM play_campaign_audit_events WHERE campaign_id = ? ORDER BY timestamp",
            (campaign_id,),
        ).fetchall()
    return {"entries": [
        {"kind": row[0], "actor": row[1], "role": row[2],
         "timestamp": row[3], "correlation_id": row[4]}
        for row in rows
    ]}


def projection_event_fields(data):
    """Validate a complete projection event without allowing ambiguous fields."""
    if not isinstance(data, dict):
        raise BadRequest()
    event_id = data.get("event_id")
    kind = data.get("kind")
    if not isinstance(event_id, str) or not event_id:
        raise BadRequest()
    if kind == "set-story":
        if set(data) != {"event_id", "kind", "value"}:
            raise BadRequest()
        value = data["value"]
        if not isinstance(value, str) or not value:
            raise BadRequest()
        return event_id, kind, value
    if kind == "increment-danger":
        if set(data) != {"event_id", "kind"}:
            raise BadRequest()
        return event_id, kind, None
    raise BadRequest()


def projection_from_events(events):
    """Derive the entire public projection solely from sequence-ordered events."""
    projection = {"story": "", "danger": 0, "applied_event_ids": []}
    for _, event_id, kind, value in events:
        projection["applied_event_ids"].append(event_id)
        if kind == "set-story":
            projection["story"] = value
        else:
            projection["danger"] += 1
    return projection


def append_play_campaign_projection_event(campaign_id, actor, data):
    event_id, kind, value = projection_event_fields(data)
    try:
        with DATABASE_LOCK, database() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            if campaign[0] == actor or connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, actor),
            ).fetchone() is None:
                raise PermissionError()
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM play_campaign_projection_events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_projection_events "
                "(campaign_id, sequence, event_id, kind, value) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, sequence, event_id, kind, value),
            )
            connection.execute(
                "UPDATE play_campaign_metrics "
                "SET projection_events = projection_events + 1 WHERE campaign_id = ?",
                (campaign_id,),
            )
    except sqlite3.IntegrityError:
        raise DuplicateRecord()
    response = {"sequence": sequence, "event_id": event_id, "kind": kind}
    if kind == "set-story":
        response["value"] = value
    return response


def get_play_campaign_projection(campaign_id, actor):
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, actor) is None:
            return None
        events = connection.execute(
            "SELECT sequence, event_id, kind, value "
            "FROM play_campaign_projection_events WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()
    return projection_from_events(events)


def idempotent_event_fields(data):
    """Validate the deliberately small, immutable idempotent event shape."""
    if not isinstance(data, dict) or set(data) != {"event_id", "value"}:
        raise BadRequest()
    event_id, value = data["event_id"], data["value"]
    if (not isinstance(event_id, str) or not event_id or
            not isinstance(value, str) or not value):
        raise BadRequest()
    return event_id, value


def create_play_campaign_idempotent_event(campaign_id, actor, key, data):
    """Create one event per campaign/key, replaying its original public result."""
    if not isinstance(key, str) or not key.strip():
        raise BadRequest()
    event_id, value = idempotent_event_fields(data)
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, actor) is None:
            return None
        existing = connection.execute(
            "SELECT event_id, value, sequence, idempotency_key "
            "FROM play_campaign_idempotent_events "
            "WHERE campaign_id = ? AND idempotency_key = ?",
            (campaign_id, key),
        ).fetchone()
        if existing is not None:
            if existing[0] != event_id or existing[1] != value:
                raise DuplicateRecord()
            return {"event_id": existing[0], "value": existing[1],
                    "sequence": existing[2], "idempotency_key": existing[3]}, False
        duplicate_id = connection.execute(
            "SELECT 1 FROM play_campaign_idempotent_events "
            "WHERE campaign_id = ? AND event_id = ?", (campaign_id, event_id)
        ).fetchone()
        if duplicate_id is not None:
            raise DuplicateRecord()
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 "
            "FROM play_campaign_idempotent_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_idempotent_events "
            "(campaign_id, sequence, event_id, value, idempotency_key) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, event_id, value, key),
        )
    return {"event_id": event_id, "value": value, "sequence": sequence,
            "idempotency_key": key}, True


def list_play_campaign_idempotent_events(campaign_id, actor):
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, actor) is None:
            return None
        rows = connection.execute(
            "SELECT event_id, value, sequence, idempotency_key "
            "FROM play_campaign_idempotent_events WHERE campaign_id = ? "
            "ORDER BY sequence", (campaign_id,)
        ).fetchall()
    return {"events": [
        {"event_id": row[0], "value": row[1], "sequence": row[2],
         "idempotency_key": row[3]} for row in rows
    ]}


def safe_turn_fields(data):
    if not isinstance(data, dict) or set(data) != {
            "submission_id", "expected_turn", "action"}:
        raise BadRequest()
    submission_id, action = data["submission_id"], data["action"]
    expected_turn = integer(data["expected_turn"])
    if (not isinstance(submission_id, str) or not submission_id or
            not isinstance(action, str) or not action or expected_turn < 1):
        raise BadRequest()
    return submission_id, expected_turn, action


def submit_play_campaign_safe_turn(campaign_id, actor, data):
    """Atomically accept an action only for the campaign's current safe turn."""
    submission_id, expected_turn, action = safe_turn_fields(data)
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, actor) is None:
            return None
        connection.execute(
            "INSERT OR IGNORE INTO play_campaign_safe_turn_state "
            "(campaign_id, current_turn) VALUES (?, 1)", (campaign_id,)
        )
        current_turn = connection.execute(
            "SELECT current_turn FROM play_campaign_safe_turn_state WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        if connection.execute(
                "SELECT 1 FROM play_campaign_safe_turns "
                "WHERE campaign_id = ? AND submission_id = ?",
                (campaign_id, submission_id),
        ).fetchone() is not None:
            return "duplicate", None
        if expected_turn != current_turn:
            return "stale", {"current_turn": current_turn}
        next_turn = current_turn + 1
        connection.execute(
            "INSERT INTO play_campaign_safe_turns "
            "(campaign_id, submission_id, action, accepted_turn, next_turn) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, submission_id, action, current_turn, next_turn),
        )
        connection.execute(
            "UPDATE play_campaign_safe_turn_state SET current_turn = ? "
            "WHERE campaign_id = ?", (next_turn, campaign_id)
        )
    return "accepted", {"submission_id": submission_id, "action": action,
                        "accepted_turn": current_turn, "next_turn": next_turn}


def get_play_campaign_safe_turns(campaign_id, actor):
    with DATABASE_LOCK, database() as connection:
        if play_campaign_actor(connection, campaign_id, actor) is None:
            return None
        state = connection.execute(
            "SELECT current_turn FROM play_campaign_safe_turn_state WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        current_turn = 1 if state is None else state[0]
        rows = connection.execute(
            "SELECT submission_id, action, accepted_turn, next_turn "
            "FROM play_campaign_safe_turns WHERE campaign_id = ? "
            "ORDER BY accepted_turn", (campaign_id,)
        ).fetchall()
    return {"current_turn": current_turn, "accepted": [
        {"submission_id": row[0], "action": row[1],
         "accepted_turn": row[2], "next_turn": row[3]} for row in rows
    ]}


def submit_play_campaign_action(campaign_id, actor, data):
    """Record the active player's action and hand the turn to the DM."""
    if not isinstance(data, dict):
        raise BadRequest()
    action_type, text = campaign_text(data.get("type")), campaign_text(data.get("text"))
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        member = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if actor != campaign[0] and member is None:
            raise PermissionError()
        players = connection.execute(
            "SELECT username FROM play_campaign_members WHERE campaign_id = ? "
            "ORDER BY rowid", (campaign_id,)
        ).fetchall()
        resolutions = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_actions "
            "WHERE campaign_id = ? AND type = 'resolution'", (campaign_id,)
        ).fetchone()[0]
        pending_action = connection.execute(
            "SELECT type FROM play_campaign_actions WHERE campaign_id = ? "
            "ORDER BY sequence DESC LIMIT 1", (campaign_id,)
        ).fetchone()
        active_player = players[resolutions % len(players)][0] if players else None
        if (campaign[1] != "active" or active_player is None
                or actor != active_player
                or (pending_action is not None and pending_action[0] != "resolution")):
            raise DuplicateRecord()
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM ("
            "SELECT sequence FROM play_campaign_narrations WHERE campaign_id = ? "
            "UNION ALL "
            "SELECT sequence FROM play_campaign_actions WHERE campaign_id = ?"
            ")",
            (campaign_id, campaign_id),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_actions (campaign_id, sequence, actor, type, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, actor, action_type, text),
        )
    return {"sequence": sequence, "kind": "action", "actor": actor,
            "type": action_type, "text": text, "next_actor": "dm"}


def submit_play_campaign_resolution(campaign_id, owner, data):
    """Resolve the pending player action and advance to the next player."""
    if not isinstance(data, dict):
        raise BadRequest()
    text = campaign_text(data.get("text"))
    with DATABASE_LOCK, database() as connection:
        campaign = connection.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return None
        if campaign[0] != owner:
            raise PermissionError()
        players = connection.execute(
            "SELECT username FROM play_campaign_members WHERE campaign_id = ? "
            "ORDER BY rowid", (campaign_id,)
        ).fetchall()
        last_action = connection.execute(
            "SELECT type FROM play_campaign_actions WHERE campaign_id = ? "
            "ORDER BY sequence DESC LIMIT 1", (campaign_id,)
        ).fetchone()
        if campaign[1] != "active" or not players or last_action is None or last_action[0] == "resolution":
            raise DuplicateRecord()
        resolutions = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_actions "
            "WHERE campaign_id = ? AND type = 'resolution'", (campaign_id,)
        ).fetchone()[0]
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM ("
            "SELECT sequence FROM play_campaign_narrations WHERE campaign_id = ? "
            "UNION ALL "
            "SELECT sequence FROM play_campaign_actions WHERE campaign_id = ?"
            ")",
            (campaign_id, campaign_id),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_actions (campaign_id, sequence, actor, type, text) "
            "VALUES (?, ?, ?, 'resolution', ?)",
            (campaign_id, sequence, owner, text),
        )
    # Combat actions are recorded in the common event log, but do not consume
    # the paused exploration player's place in its queue.
    next_player = resolutions if last_action[0] in ("attack", "help", "dodge", "ready") else resolutions + 1
    turn_number = resolutions + 2
    return {"sequence": sequence, "kind": "resolution", "actor": owner,
            "text": text, "next_actor": players[next_player % len(players)][0],
            "turn_number": turn_number}


def ability_modifier(score):
    score = integer(score)
    if not 1 <= score <= 30:
        raise BadRequest()
    return (score - 10) // 2


def proficiency_bonus(level):
    level = integer(level)
    if not 1 <= level <= 20:
        raise BadRequest()
    return 2 + (level - 1) // 4


def multiplier(count):
    if count == 1:
        return 1
    if count == 2:
        return 1.5
    if count <= 6:
        return 2
    if count <= 10:
        return 2.5
    if count <= 14:
        return 3
    return 4


def dice_stats(data):
    expression = data.get("expression") if isinstance(data, dict) else None
    match = DICE.fullmatch(expression) if isinstance(expression, str) else None
    if not match:
        raise BadRequest()
    count, sides = int(match[1]), int(match[2])
    modifier = int(match[3] or 0)
    if count <= 0 or sides <= 0:
        raise BadRequest()
    minimum, maximum = count + modifier, count * sides + modifier
    average_sum = minimum + maximum
    average = average_sum // 2 if average_sum % 2 == 0 else average_sum / 2
    return {"dice_count": count, "sides": sides, "modifier": modifier,
            "min": minimum, "max": maximum, "average": average}


def ability_check(data):
    if not isinstance(data, dict):
        raise BadRequest()
    total = integer(data.get("roll")) + integer(data.get("modifier"))
    dc = integer(data.get("dc"))
    return {"total": total, "success": total >= dc, "margin": total - dc}


def adjusted_xp(data):
    if not isinstance(data, dict) or not isinstance(data.get("party"), list) or not isinstance(data.get("monsters"), list):
        raise BadRequest()
    thresholds = {key: 0 for key in THRESHOLDS}
    for member in data["party"]:
        if not isinstance(member, dict) or member.get("level") != 3:
            raise BadRequest()
        for key, value in THRESHOLDS.items():
            thresholds[key] += value
    base_xp = monster_count = 0
    for monster in data["monsters"]:
        if not isinstance(monster, dict) or monster.get("cr") not in XP_BY_CR:
            raise BadRequest()
        count = integer(monster.get("count"))
        if count <= 0:
            raise BadRequest()
        base_xp += XP_BY_CR[monster["cr"]] * count
        monster_count += count
    if monster_count == 0:
        raise BadRequest()
    factor = multiplier(monster_count)
    adjusted = base_xp * factor
    if isinstance(adjusted, float) and adjusted.is_integer():
        adjusted = int(adjusted)
    difficulty = "trivial"
    for label in ("easy", "medium", "hard", "deadly"):
        if adjusted >= thresholds[label]:
            difficulty = label
    return {"base_xp": base_xp, "monster_count": monster_count, "multiplier": factor,
            "adjusted_xp": adjusted, "difficulty": difficulty, "thresholds": thresholds}


def campaign_exists(campaign_id):
    with DATABASE_LOCK, database() as connection:
        return connection.execute(
            "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is not None


def dm_campaign_id(data):
    if not isinstance(data, dict):
        raise BadRequest()
    return campaign_text(data.get("campaign_id"))


def encounter_recommendation(difficulty):
    return {
        "trivial": "safe warm-up",
        "easy": "safe warm-up",
        "medium": "balanced challenge",
        "hard": "dangerous fight",
        "deadly": "deadly encounter",
    }[difficulty]


def dm_encounter_builder(data):
    campaign_id = dm_campaign_id(data)
    if not campaign_exists(campaign_id):
        return None
    slugs = data.get("monster_slugs")
    if not isinstance(slugs, list) or not slugs:
        raise BadRequest()
    monsters = []
    for slug in slugs:
        slug = compendium_slug(slug)
        monster = get_monster(slug)
        if monster is None or monster["cr"] not in XP_BY_CR:
            raise BadRequest()
        monsters.append({"cr": monster["cr"], "count": 1})
    result = adjusted_xp({"party": data.get("party"), "monsters": monsters})
    return {
        "campaign_id": campaign_id,
        "base_xp": result["base_xp"],
        "adjusted_xp": result["adjusted_xp"],
        "difficulty": result["difficulty"],
        "monster_count": result["monster_count"],
        "recommendation": encounter_recommendation(result["difficulty"]),
    }


def dm_loot_parcel(data):
    campaign_id = dm_campaign_id(data)
    if not campaign_exists(campaign_id):
        return None
    if integer(data.get("tier")) != 1:
        raise BadRequest()
    integer(data.get("seed"))
    if get_item("healing-potion") is None:
        raise BadRequest()
    return {"campaign_id": campaign_id, "coins_gp": 75,
            "items": [{"slug": "healing-potion", "quantity": 2}]}


def dm_session_recap(data):
    campaign_id = dm_campaign_id(data)
    if not campaign_exists(campaign_id):
        return None
    with DATABASE_LOCK, database() as connection:
        event = connection.execute(
            "SELECT summary FROM campaign_events WHERE campaign_id = ? ORDER BY rowid DESC LIMIT 1",
            (campaign_id,),
        ).fetchone()
    if event is None:
        raise BadRequest()
    return {"campaign_id": campaign_id, "summary": event[0],
            "open_threads": ["Resolve goblin trail ambush"]}


def initiative_order(data):
    combatants = data.get("combatants") if isinstance(data, dict) else None
    if not isinstance(combatants, list):
        raise BadRequest()
    order = []
    for combatant in combatants:
        if not isinstance(combatant, dict) or not isinstance(combatant.get("name"), str):
            raise BadRequest()
        dex, roll = integer(combatant.get("dex")), integer(combatant.get("roll"))
        order.append((combatant["name"], dex, roll + dex))
    order.sort(key=lambda entry: (-entry[2], -entry[1], entry[0]))
    return {"order": [{"name": name, "score": score} for name, _, score in order]}


def session_summary(session):
    active = session["order"][session["turn_index"]]
    return {
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": {"name": active["name"], "score": active["score"]},
    }


def create_combat_session(data):
    if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not data["id"]:
        raise BadRequest()
    combatants = data.get("combatants")
    if not isinstance(combatants, list) or not combatants:
        raise BadRequest()
    order, names = [], set()
    for combatant in combatants:
        if not isinstance(combatant, dict) or not isinstance(combatant.get("name"), str) or not combatant["name"]:
            raise BadRequest()
        name = combatant["name"]
        if name in names:
            raise BadRequest()
        names.add(name)
        dex, roll = integer(combatant.get("dex")), integer(combatant.get("roll"))
        order.append({"name": name, "dex": dex, "score": roll + dex})
    order.sort(key=lambda entry: (-entry["score"], -entry["dex"], entry["name"]))
    session = {"id": data["id"], "round": 1, "turn_index": 0,
               "order": order, "conditions": {}}
    try:
        with DATABASE_LOCK, database() as connection:
            connection.execute(
                "INSERT INTO combat_sessions (id, state) VALUES (?, ?)",
                (data["id"], json.dumps(session, separators=(",", ":"))),
            )
    except sqlite3.IntegrityError:
        raise BadRequest()
    response = session_summary(session)
    response["order"] = [{"name": entry["name"], "score": entry["score"]} for entry in order]
    return response


def add_condition(session_id, data):
    if not isinstance(data, dict) or not isinstance(data.get("target"), str) or not isinstance(data.get("condition"), str):
        raise BadRequest()
    duration = integer(data.get("duration_rounds"))
    if duration <= 0:
        raise BadRequest()
    with DATABASE_LOCK, database() as connection:
        row = connection.execute(
            "SELECT state FROM combat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        session = json.loads(row[0])
        if data["target"] not in {entry["name"] for entry in session["order"]}:
            raise BadRequest()
        conditions = session["conditions"].setdefault(data["target"], [])
        conditions.append({"condition": data["condition"], "remaining_rounds": duration})
        connection.execute(
            "UPDATE combat_sessions SET state = ? WHERE id = ?",
            (json.dumps(session, separators=(",", ":")), session_id),
        )
        return {"target": data["target"], "conditions": conditions}


def advance_combat(session_id):
    with DATABASE_LOCK, database() as connection:
        row = connection.execute(
            "SELECT state FROM combat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        session = json.loads(row[0])
        session["turn_index"] += 1
        if session["turn_index"] == len(session["order"]):
            session["turn_index"] = 0
            session["round"] += 1
        active_name = session["order"][session["turn_index"]]["name"]
        if active_name in session["conditions"]:
            remaining = []
            for condition in session["conditions"][active_name]:
                condition["remaining_rounds"] -= 1
                if condition["remaining_rounds"] > 0:
                    remaining.append(condition)
            if remaining:
                session["conditions"][active_name] = remaining
            else:
                # Keep an empty collection so expiry differs from never set.
                session["conditions"][active_name] = []
        connection.execute(
            "UPDATE combat_sessions SET state = ? WHERE id = ?",
            (json.dumps(session, separators=(",", ":")), session_id),
        )
        response = session_summary(session)
        response["conditions"] = session["conditions"]
        return response


def character_ability_modifier(data):
    if not isinstance(data, dict):
        raise BadRequest()
    score = integer(data.get("score"))
    return {"score": score, "modifier": ability_modifier(score)}


def character_proficiency(data):
    if not isinstance(data, dict):
        raise BadRequest()
    level = integer(data.get("level"))
    return {"level": level, "proficiency_bonus": proficiency_bonus(level)}


def derived_stats(data):
    if not isinstance(data, dict):
        raise BadRequest()
    level = integer(data.get("level"))
    abilities, armor = data.get("abilities"), data.get("armor")
    if not isinstance(abilities, dict) or not isinstance(armor, dict):
        raise BadRequest()
    modifiers = {name: ability_modifier(abilities.get(name))
                 for name in ("str", "dex", "con", "int", "wis", "cha")}
    base, dex_cap = integer(armor.get("base")), integer(armor.get("dex_cap"))
    shield = armor.get("shield")
    if not isinstance(shield, bool):
        raise BadRequest()
    return {
        "level": level,
        "proficiency_bonus": proficiency_bonus(level),
        "hp_max": level * (6 + modifiers["con"]),
        "armor_class": base + min(modifiers["dex"], dex_cap) + (2 if shield else 0),
        "modifiers": modifiers,
    }


def spell_slots(data):
    if not isinstance(data, dict) or data.get("class") != "wizard":
        raise BadRequest()
    level = integer(data.get("level"))
    if level != 5:
        raise BadRequest()
    return {"class": "wizard", "level": level,
            "slots": {"1": 4, "2": 3, "3": 2}}


def long_rest(data):
    if not isinstance(data, dict):
        raise BadRequest()
    level = integer(data.get("level"))
    hp_current = integer(data.get("hp_current"))
    hp_max = integer(data.get("hp_max"))
    hit_dice_spent = integer(data.get("hit_dice_spent"))
    exhaustion_level = integer(data.get("exhaustion_level"))
    if (level < 1 or hp_current < 0 or hp_max < 0 or hp_current > hp_max
            or hit_dice_spent < 0 or exhaustion_level < 0):
        raise BadRequest()
    restored_hit_dice = max(level // 2, 1)
    return {"hp_current": hp_max,
            "hit_dice_spent": max(0, hit_dice_spent - restored_hit_dice),
            "exhaustion_level": max(0, exhaustion_level - 1)}


def equipment_load(data):
    if not isinstance(data, dict):
        raise BadRequest()
    strength = integer(data.get("strength"))
    weight = integer(data.get("weight"))
    if strength < 0 or weight < 0:
        raise BadRequest()
    capacity = strength * 15
    return {"capacity": capacity, "weight": weight,
            "encumbered": weight > capacity}


# These calculations all have the same POST success contract: status 200.
CALCULATION_POST_ROUTES = {
    "/v1/dice/stats": dice_stats,
    "/v1/checks/ability": ability_check,
    "/v1/encounters/adjusted-xp": adjusted_xp,
    "/v1/initiative/order": initiative_order,
    "/v1/characters/ability-modifier": character_ability_modifier,
    "/v1/characters/proficiency": character_proficiency,
    "/v1/characters/derived-stats": derived_stats,
    "/v1/phb/spell-slots": spell_slots,
    "/v1/phb/rests/long": long_rest,
    "/v1/phb/equipment-load": equipment_load,
}

API_SCHEMA = {
    "version": "2026-07-29",
    "endpoints": [
        {"method": "GET", "path": "/v1/play/campaigns/{id}/rng-ledger", "auth": "member"},
        {"method": "GET", "path": "/v1/schema", "auth": "public"},
        {"method": "POST", "path": "/v1/play/campaigns", "auth": "dm"},
        {"method": "POST", "path": "/v1/play/campaigns/{id}/fixture-seeds", "auth": "dm"},
        {"method": "POST", "path": "/v1/play/campaigns/{id}/members", "auth": "member"},
        {"method": "POST", "path": "/v1/play/campaigns/{id}/moderation/reports", "auth": "member"},
        {"method": "POST", "path": "/v1/play/campaigns/{id}/rng-rolls", "auth": "member"},
        {"method": "PUT", "path": "/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution", "auth": "dm"},
        {"method": "PUT", "path": "/v1/play/campaigns/{id}/rng-seed", "auth": "dm"},
        {"method": "PUT", "path": "/v1/play/campaigns/{id}/safety-boundaries", "auth": "dm"},
    ],
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def respond(self, status, body):
        encoded = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def read_json_body(self):
        """Decode a request body using the established Content-Length contract."""
        length = int(self.headers.get("Content-Length", ""))
        return json.loads(self.rfile.read(length))

    def respond_or_not_found(self, response, success_status=200):
        """Map domain lookups that use None for absence to the public 404 body."""
        if response is None:
            self.respond(404, {"error": "not found"})
        else:
            self.respond(success_status, response)

    def do_GET(self):
        if self.path == "/healthz":
            self.respond(200, {"status": "ok"})
        elif self.path == "/v1/schema":
            self.respond(200, API_SCHEMA)
        elif self.path == "/readyz":
            if service_maintenance_enabled():
                self.respond(503, {"status": "maintenance", "schema_version": 2})
            else:
                self.respond(200, {"status": "ready", "schema_version": 2})
        elif self.path == "/health":
            self.respond(200, {"ok": True})
        elif self.path == "/v1/storage/status":
            self.respond(200, {"driver": "sqlite", "schema_version": 1,
                               "initialized": storage_initialized()})
        else:
            parsed_path = urlsplit(self.path)
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/event-feed", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    cursor, limit = event_feed_pagination(
                        parse_qs(parsed_path.query, keep_blank_values=True)
                    )
                    response = get_play_campaign_event_feed(
                        match[1], actor["username"], cursor, limit
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                except BadRequest:
                    self.respond(400, {"error": "invalid request"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/spectator-view", parsed_path.path
            )
            if match:
                authorization = self.headers.get("Authorization")
                spectator_id = spectator_ticket(authorization)
                if spectator_id is None:
                    if authenticated_user(authorization) is not None:
                        self.respond(403, {"error": "forbidden"})
                    else:
                        self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_spectator_view(match[1], spectator_id)
                except LookupError:
                    self.respond(401, {"error": "unauthorized"})
                    return
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/onboarding", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_onboarding(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/fixture-state", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_fixture_state(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/replay(?:/check)?", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_replay(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/rng-ledger", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_rng_ledger(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/moderation/reports", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = list_play_campaign_moderation_reports(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/safety-boundaries", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_safety_boundaries(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/safety-events", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = list_play_campaign_safety_events(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/metrics", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_metrics(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/rate-events", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = list_play_campaign_rate_events(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/backups", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = list_play_campaign_backups(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/exports/(\d+)", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_export(
                        match[1], int(match[2]), actor["username"]
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/exports", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = list_play_campaign_exports(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/import-state", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_import_state(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/migration-state", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_migration_state(
                        match[1], actor["username"]
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/transactional-transfers", parsed_path.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = list_transactional_transfers(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/safe-turns", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_safe_turns(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/invitations", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = list_play_campaign_invitations(match[1], actor["username"])
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/delegations/audit", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = play_campaign_delegation_audit(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/audit-events", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = list_play_campaign_audit_events(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/idempotent-events", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = list_play_campaign_idempotent_events(
                        match[1], actor["username"]
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/projection(?:/rebuild)?", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_projection(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/notes", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = list_play_campaign_notes(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/notes/([^/]+)", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_note(match[1], match[2], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/whispers", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = list_play_campaign_whispers(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/sheet", parsed_path.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_character_sheet(match[1], match[2], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/content", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                query = parse_qs(parsed_path.query, keep_blank_values=True)
                exclude_tags = query.get("exclude_tag")
                if exclude_tags is not None:
                    if len(exclude_tags) != 1 or not exclude_tags[0]:
                        self.respond(400, {"error": "invalid request"})
                        return
                    exclude_tag = exclude_tags[0]
                else:
                    exclude_tag = None
                try:
                    response = list_play_campaign_content(
                        match[1], actor["username"], exclude_tag
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/search-records", parsed_path.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    query, limit, cursor = search_records_query(
                        parse_qs(parsed_path.query, keep_blank_values=True)
                    )
                    response = list_play_campaign_search_records(
                        match[1], actor["username"], query, limit, cursor
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                except BadRequest:
                    self.respond(400, {"error": "invalid request"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/session-zero", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_session_zero(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations/([^/]+)",
                self.path,
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_character_downtime_allocation(
                        match[1], match[2], match[3], actor["username"]
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/compendium/monsters/([^/]+)", self.path)
            if match:
                self.respond_or_not_found(get_monster(match[1]))
                return
            match = re.fullmatch(r"/v1/compendium/items/([^/]+)", self.path)
            if match:
                self.respond_or_not_found(get_item(match[1]))
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/state", self.path)
            if match:
                self.respond_or_not_found(campaign_state(match[1]))
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/analytics/summary", self.path)
            if match:
                self.respond_or_not_found(campaign_analytics_summary(match[1]))
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/audit", self.path)
            if match:
                self.respond_or_not_found(campaign_audit(match[1]))
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/export", self.path)
            if match:
                self.respond_or_not_found(campaign_export(match[1]))
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/quests/summary", self.path)
            if match:
                self.respond_or_not_found(quest_summary(match[1]))
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/relationships", self.path)
            if match:
                self.respond_or_not_found(relationship_summary(match[1]))
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/inventory/summary", self.path)
            if match:
                self.respond_or_not_found(inventory_summary(match[1]))
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/sessions/next", self.path)
            if match:
                self.respond_or_not_found(next_campaign_session(match[1]))
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/recipes", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = list_play_campaign_recipes(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/my-turn", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "player":
                    self.respond(403, {"error": "forbidden"})
                    return
                try:
                    response = play_campaign_my_turn(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/settlements", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = list_play_campaign_settlements(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_shop(match[1], match[2], match[3], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/loot/([^/]+)", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_loot(match[1], match[2], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/factions/([^/]+)/reputation", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_faction_reputation(
                        match[1], match[2], actor["username"]
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/npcs/([^/]+)/dialogue", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_npc_dialogue(
                        match[1], match[2], actor["username"]
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/relationships", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_relationships(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/clues", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_clues(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/rewards", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = play_character_quest_rewards(
                        match[1], match[2], actor["username"]
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/quests", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_quests(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/calendar", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_calendar(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/world-events", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_world_events(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/npcs/([^/]+)", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_npc(match[1], match[2], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/owner", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = play_character_owner(match[1], match[2], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/currency", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = play_character_currency(match[1], match[2], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = play_character_inventory_items(
                        match[1], match[2], actor["username"]
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)",
                self.path,
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_character_equipment(
                        match[1], match[2], match[3], actor["username"]
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                except BadRequest:
                    self.respond(400, {"error": "invalid request"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/spells", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = play_character_spells(match[1], match[2], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/casts", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = play_character_casts(match[1], match[2], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/prepared-spells", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = play_character_prepared_spells(
                        match[1], match[2], actor["username"]
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = play_character_concentration(
                        match[1], match[2], actor["username"]
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/status", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = play_character_status(match[1], match[2], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/locations/([^/]+)/travel", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = play_campaign_location_travel(match[1], match[2], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/scenes/current", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = current_play_campaign_scene(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/document", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_document(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/gm/status", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                try:
                    response = play_campaign_gm_status(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_encounter_turn(
                        match[1], match[2], actor["username"]
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/encounters/([^/]+)/status", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = get_play_campaign_encounter_status(
                        match[1], match[2], actor["username"]
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/turn", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = play_campaign_turn(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            self.respond(404, {"error": "not found"})

    def do_POST(self):
        try:
            if self.path == "/v1/storage/reset":
                reset_storage()
                self.respond(200, {"ok": True, "schema_version": 1})
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/feed-events", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = append_play_campaign_feed_event(
                        match[1], actor["username"], self.read_json_body()
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/spectators", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = create_play_campaign_spectator(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/fixture-seeds", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response, created = seed_play_campaign_fixture(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201 if created else 200)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/service-mode", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                try:
                    exists = play_campaign_dm_exists(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                if not exists:
                    self.respond(404, {"error": "not found"})
                    return
                data = self.read_json_body()
                if not isinstance(data, dict) or set(data) != {"maintenance"}:
                    raise BadRequest()
                self.respond(200, set_service_maintenance(data["maintenance"]))
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/rate-events", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = create_play_campaign_rate_event(
                        match[1], actor["username"], self.read_json_body()
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                except RateLimitReached:
                    self.respond(429, {"limit": 2, "remaining": 0})
                    return
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/replay-events", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = append_play_campaign_replay_event(
                        match[1], actor["username"], self.read_json_body()
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/rng-rolls", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = append_play_campaign_rng_roll(
                        match[1], actor["username"], self.read_json_body()
                    )
                except SeedAlreadyConfigured:
                    self.respond(409, {"error": "rng seed not configured"})
                    return
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/moderation/reports", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = create_play_campaign_moderation_report(
                        match[1], actor["username"], self.read_json_body()
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/safety-checks", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = create_play_campaign_safety_check(
                        match[1], actor["username"], self.read_json_body()
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/backups/([^/]+)/restore", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = restore_play_campaign_backup(
                        match[1], match[2], actor["username"]
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/backups", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = create_play_campaign_backup(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/exports", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = create_play_campaign_export(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/imports", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = import_play_campaign_snapshot(
                        match[1], actor["username"], self.read_json_body()
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/migrations", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    exists = play_campaign_dm_exists(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                if not exists:
                    self.respond(404, {"error": "not found"})
                    return
                response, created = migrate_play_campaign_snapshot(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201 if created else 200)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/transactional-transfers", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = create_transactional_transfer(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/safe-turns", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                result = submit_play_campaign_safe_turn(
                    match[1], actor["username"], self.read_json_body()
                )
                if result is None:
                    self.respond(404, {"error": "not found"})
                    return
                outcome, response = result
                if outcome == "duplicate":
                    self.respond(409, {"error": "record already exists"})
                elif outcome == "stale":
                    self.respond(409, response)
                else:
                    self.respond(201, response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/invitations/([^/]+)/accept", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = accept_play_campaign_invitation(
                    match[1], match[2], actor["username"]
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/invitations", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = create_play_campaign_invitation(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/notes", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = create_play_campaign_note(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/messages", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = create_play_campaign_message(
                        match[1], actor["username"], self.read_json_body()
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/whispers", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = create_play_campaign_whisper(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/content", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = create_play_campaign_content(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/search-records", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    exists = play_campaign_dm_exists(match[1], actor["username"])
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                if not exists:
                    self.respond(404, {"error": "not found"})
                    return
                response = create_play_campaign_search_record(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/combat/sessions/([^/]+)/advance", self.path)
            if match:
                response = advance_combat(match[1])
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/downtime/activities", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = create_play_campaign_downtime_activity(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations/([^/]+)/progress",
                self.path,
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "player":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = progress_play_character_downtime_allocation(
                    match[1], match[2], match[3], actor["username"]
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations",
                self.path,
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "player":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = create_play_character_downtime_allocation(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/recipes", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = create_play_campaign_recipe(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/recipes/([^/]+)/craft", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "player":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = craft_play_campaign_recipe(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/quests/([^/]+)/rewards/award", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = award_play_campaign_quest_rewards(
                    match[1], match[2], actor["username"]
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/world-events/([^/]+)/resolve", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = resolve_play_campaign_world_event(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/calendar/advance", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = advance_play_campaign_calendar(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/calendar", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = initialize_play_campaign_calendar(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/world-events", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = schedule_play_campaign_world_event(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/settlements/([^/]+)/discover", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "player":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = discover_play_campaign_settlement(match[1], match[2], actor["username"])
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    settlement, created = response
                    self.respond(201 if created else 200, settlement)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)/(buy|sell)", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "player":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = trade_play_campaign_shop(
                    match[1], match[2], match[3], actor["username"], self.read_json_body(), match[4] == "buy"
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = create_play_campaign_shop(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/settlements", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = create_play_campaign_settlement(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            if self.path == "/v1/play/campaigns":
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                data = self.read_json_body()
                self.respond(201, create_play_campaign(actor["username"], data))
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/factions", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = create_play_campaign_faction(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/factions/([^/]+)/reputation", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = change_play_campaign_faction_reputation(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/npcs", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = create_play_campaign_npc(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/npcs/([^/]+)/dialogue", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = create_play_campaign_npc_dialogue(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/relationships", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = create_play_campaign_relationship(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/clues", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = create_play_campaign_clue(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/quests", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = create_play_campaign_quest(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/loot", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = create_play_campaign_loot(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/loot/([^/]+)/votes", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "player":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = vote_on_play_campaign_loot(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/loot/([^/]+)/assign", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = assign_play_campaign_loot(match[1], match[2], actor["username"])
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/claim", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = claim_play_character(match[1], match[2], actor["username"])
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/build", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = build_play_character(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/level-up", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                self.respond(200, level_up_play_character(
                    match[1], match[2], actor["username"], self.read_json_body()
                ))
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/skill-check", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = skill_check_play_character(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/spells", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = add_play_character_spell(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/currency/transfers", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = transfer_play_character_currency(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = add_play_character_inventory_item(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items/([^/]+)/consume",
                self.path,
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = consume_play_character_inventory_item(
                    match[1], match[2], match[3], actor["username"]
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)/attune",
                self.path,
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = attune_play_character_equipment(
                    match[1], match[2], match[3], actor["username"]
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/casts", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = cast_play_character_spell(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration/advance-turn",
                self.path,
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = advance_play_character_concentration(
                    match[1], match[2], actor["username"]
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/transfer", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = transfer_play_character(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/damage", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = damage_play_character(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/death-saves", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = play_character_death_save(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/encounters/([^/]+)/rewards", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = award_play_campaign_encounter_rewards(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/encounters/([^/]+)/close", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = close_play_campaign_encounter(
                    match[1], match[2], actor["username"]
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/encounters/([^/]+)/end", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = end_play_campaign_encounter(
                    match[1], match[2], actor["username"]
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/encounters/([^/]+)/(damage|heal)", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                data = self.read_json_body()
                response = adjust_play_campaign_combatant_hp(
                    match[1], match[2], actor["username"], data, match[3] == "heal"
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/encounters/([^/]+)/conditions", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = add_play_campaign_encounter_condition(
                        match[1], match[2], actor["username"], self.read_json_body()
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/encounters/([^/]+)/actions", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                data = self.read_json_body()
                response = submit_play_campaign_combat_action(
                    match[1], match[2], actor["username"], data
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/advance", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = advance_play_campaign_encounter_turn(
                        match[1], match[2], actor["username"]
                    )
                except OutOfTurn:
                    self.respond(409, {"error": "not current combatant"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/delay", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = delay_play_campaign_encounter_turn(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/ready", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = ready_play_campaign_encounter_turn(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/encounters/([^/]+)/combatants", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                data = self.read_json_body()
                response = add_play_campaign_combatant(
                    match[1], match[2], actor["username"], data
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/encounters/([^/]+)/monsters", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                data = self.read_json_body()
                response = add_play_campaign_monster(
                    match[1], match[2], actor["username"], data
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/encounters", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                data = self.read_json_body()
                response = create_play_campaign_encounter(match[1], actor["username"], data)
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/locations", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                data = self.read_json_body()
                response = create_play_campaign_location(match[1], actor["username"], data)
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/locations/([^/]+)/connections", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                data = self.read_json_body()
                response = create_play_campaign_location_connection(
                    match[1], match[2], actor["username"], data
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/scenes", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                data = self.read_json_body()
                response = create_play_campaign_scene(match[1], actor["username"], data)
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/scenes/([^/]+)/enter", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = enter_play_campaign_scene(match[1], match[2], actor["username"])
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/scenes/([^/]+)/close", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = close_play_campaign_scene(match[1], match[2], actor["username"])
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/members", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "player":
                    self.respond(403, {"error": "forbidden"})
                    return
                data = self.read_json_body()
                response = add_play_campaign_member(match[1], actor["username"], data)
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/start", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = start_play_campaign(match[1], actor["username"])
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/turn/travel", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                data = self.read_json_body()
                response = travel_play_campaign_turn(match[1], actor["username"], data)
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/turn/rest", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                data = self.read_json_body()
                response = rest_play_campaign_turn(match[1], actor["username"], data)
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/turn/nudge", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                data = self.read_json_body()
                try:
                    response = nudge_play_campaign_turn(match[1], actor["username"], data)
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/actions", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                data = self.read_json_body()
                response = submit_play_campaign_action(match[1], actor["username"], data)
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/resolutions", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(409, {"error": "not current actor"})
                    return
                data = self.read_json_body()
                response = submit_play_campaign_resolution(match[1], actor["username"], data)
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/narrations", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                data = self.read_json_body()
                response = append_play_campaign_narration(match[1], actor["username"], data)
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/audit-events", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = create_play_campaign_audit_event(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/projection-events", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = append_play_campaign_projection_event(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/idempotent-events", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response, created = create_play_campaign_idempotent_event(
                    match[1], actor["username"], self.headers.get("Idempotency-Key"),
                    self.read_json_body(),
                )
                self.respond_or_not_found(response, 201 if created else 200)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/delegations", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = grant_play_campaign_delegation(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response, 201)
                return
            data = self.read_json_body()
            if self.path == "/v1/auth/register":
                self.respond(201, auth_registration(data))
                return
            if self.path == "/v1/auth/login":
                response = auth_login(data)
                if response is None:
                    self.respond(401, {"error": "bad credentials"})
                else:
                    self.respond(200, response)
                return
            if self.path == "/v1/compendium/monsters":
                self.respond(201, create_monster(data))
                return
            if self.path == "/v1/compendium/items":
                self.respond(201, create_item(data))
                return
            if self.path == "/v1/campaigns":
                self.respond(201, create_campaign(data))
                return
            if self.path == "/v1/dm/encounter-builder":
                response = dm_encounter_builder(data)
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    self.respond(200, response)
                return
            if self.path == "/v1/dm/loot-parcel":
                response = dm_loot_parcel(data)
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    self.respond(200, response)
                return
            if self.path == "/v1/dm/session-recap":
                response = dm_session_recap(data)
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    self.respond(200, response)
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/analytics/risk-report", self.path)
            if match:
                response = campaign_risk_report(match[1], data)
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    self.respond(200, response)
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/characters", self.path)
            if match:
                response = add_campaign_character(match[1], data)
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    self.respond(201, response)
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/sessions", self.path)
            if match:
                response = schedule_campaign_session(match[1], data)
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    self.respond(201, response)
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/sessions/([^/]+)/attendance", self.path)
            if match:
                response = record_session_attendance(match[1], match[2], data)
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    self.respond(200, response)
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/inventory", self.path)
            if match:
                response = add_inventory_item(match[1], data)
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    self.respond(201, response)
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/downtime/crafting", self.path)
            if match:
                response = create_crafting_project(match[1], data)
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    self.respond(201, response)
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/downtime/crafting/([^/]+)/advance", self.path)
            if match:
                response = advance_crafting_project(match[1], match[2], data)
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    self.respond(200, response)
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/characters/([^/]+)/equipment", self.path)
            if match:
                response = assign_equipment(match[1], match[2], data)
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    self.respond(200, response)
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/events", self.path)
            if match:
                response = add_campaign_event(match[1], data)
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    self.respond(201, response)
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/quests", self.path)
            if match:
                response = create_campaign_quest(match[1], data)
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    self.respond(201, response)
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/factions", self.path)
            if match:
                response = create_campaign_faction(match[1], data)
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    self.respond(201, response)
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/npcs", self.path)
            if match:
                response = create_campaign_npc(match[1], data)
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    self.respond(201, response)
                return
            match = re.fullmatch(r"/v1/campaigns/([^/]+)/quests/([^/]+)/progress", self.path)
            if match:
                response = update_quest_progress(match[1], match[2], data)
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    self.respond(200, response)
                return
            if self.path == "/v1/combat/sessions":
                self.respond(200, create_combat_session(data))
                return
            match = re.fullmatch(r"/v1/combat/sessions/([^/]+)/conditions", self.path)
            if match:
                response = add_condition(match[1], data)
                if response is None:
                    self.respond(404, {"error": "not found"})
                else:
                    self.respond(200, response)
                return
            handler = CALCULATION_POST_ROUTES.get(self.path)
            if handler is None:
                self.respond(404, {"error": "not found"})
                return
            self.respond(200, handler(data))
        except DuplicateUser:
            self.respond(409, {"error": "username already exists"})
        except DuplicateSlug:
            self.respond(409, {"error": "slug already exists"})
        except DuplicateRecord:
            self.respond(409, {"error": "record already exists"})
        except NoSpellSlots:
            self.respond(409, {"error": "no spell slots remaining"})
        except InsufficientInventory:
            self.respond(409, {"error": "insufficient item quantity"})
        except AttunementLimitReached:
            self.respond(409, {"error": "attunement limit reached"})
        except InsufficientGold:
            self.respond(409, {"error": "insufficient gold"})
        except SimulatedFailure:
            self.respond(500, {"error": "simulated failure"})
        except InsufficientStock:
            self.respond(409, {"error": "insufficient stock"})
        except OutOfTurn:
            self.respond(409, {"error": "not current combatant"})
        except PermissionError:
            self.respond(403, {"error": "forbidden"})
        except (BadRequest, ValueError, TypeError, json.JSONDecodeError):
            self.respond(400, {"error": "invalid request"})

    def do_PUT(self):
        try:
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/safety-boundaries", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = replace_play_campaign_safety_boundaries(
                        match[1], actor["username"], self.read_json_body()
                    )
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/moderation/reports/([^/]+)/resolution", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = resolve_play_campaign_moderation_report(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/rng-seed", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                try:
                    response = configure_play_campaign_rng_seed(
                        match[1], actor["username"], self.read_json_body()
                    )
                except SeedAlreadyConfigured:
                    self.respond(409, {"error": "rng seed already configured"})
                    return
                except PermissionError:
                    self.respond(403, {"error": "forbidden"})
                    return
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/notes/([^/]+)", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = update_play_campaign_note(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/content/([^/]+)/tags", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = update_play_campaign_content_tags(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/session-zero", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = update_play_campaign_session_zero(
                    match[1], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/settlements/([^/]+)", self.path)
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = update_play_campaign_settlement(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/quests/([^/]+)/rewards", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = configure_play_campaign_quest_rewards(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/quests/([^/]+)/state", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = update_play_campaign_quest_state(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/relationships/([^/]+)/([^/]+)/([^/]+)",
                self.path,
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = update_play_campaign_relationship(
                    match[1], match[2], match[3], match[4], actor["username"],
                    self.read_json_body(),
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/npcs/([^/]+)/agenda", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = update_play_campaign_npc_agenda(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)",
                self.path,
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = equip_play_character_item(
                    match[1], match[2], match[3], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = set_play_character_concentration(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/prepared-spells", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = update_play_character_prepared_spells(
                    match[1], match[2], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(r"/v1/play/campaigns/([^/]+)/document", self.path)
            if not match:
                self.respond(404, {"error": "not found"})
                return
            actor = authenticated_user(self.headers.get("Authorization"))
            if actor is None:
                self.respond(401, {"error": "unauthorized"})
                return
            if actor["role"] != "dm":
                self.respond(403, {"error": "forbidden"})
                return
            data = self.read_json_body()
            response = update_play_campaign_document(match[1], actor["username"], data)
            self.respond_or_not_found(response)
        except PermissionError:
            self.respond(403, {"error": "forbidden"})
        except DuplicateRecord:
            self.respond(409, {"error": "record already exists"})
        except AttunementLimitReached:
            self.respond(409, {"error": "attunement limit reached"})
        except (BadRequest, ValueError, TypeError, json.JSONDecodeError):
            self.respond(400, {"error": "invalid request"})

    def do_DELETE(self):
        try:
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/delegations/([^/]+)", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = revoke_play_campaign_delegation(
                    match[1], actor["username"], match[2]
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items/([^/]+)",
                self.path,
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = remove_play_character_inventory_item(
                    match[1], match[2], match[3], actor["username"], self.read_json_body()
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration", self.path
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                response = clear_play_character_concentration(
                    match[1], match[2], actor["username"]
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/encounters/([^/]+)/combatants/([^/]+)",
                self.path,
            )
            if match:
                actor = authenticated_user(self.headers.get("Authorization"))
                if actor is None:
                    self.respond(401, {"error": "unauthorized"})
                    return
                if actor["role"] != "dm":
                    self.respond(403, {"error": "forbidden"})
                    return
                response = remove_play_campaign_combatant(
                    match[1], match[2], match[3], actor["username"]
                )
                self.respond_or_not_found(response)
                return
            match = re.fullmatch(
                r"/v1/play/campaigns/([^/]+)/encounters/([^/]+)/monsters/([^/]+)",
                self.path,
            )
            if not match:
                self.respond(404, {"error": "not found"})
                return
            actor = authenticated_user(self.headers.get("Authorization"))
            if actor is None:
                self.respond(401, {"error": "unauthorized"})
                return
            if actor["role"] != "dm":
                self.respond(403, {"error": "forbidden"})
                return
            response = remove_play_campaign_monster(
                match[1], match[2], match[3], actor["username"]
            )
            self.respond_or_not_found(response)
        except PermissionError:
            self.respond(403, {"error": "forbidden"})
        except InsufficientInventory:
            self.respond(409, {"error": "insufficient item quantity"})
        except InsufficientGold:
            self.respond(409, {"error": "insufficient gold"})
        except (BadRequest, ValueError, TypeError, json.JSONDecodeError):
            self.respond(400, {"error": "invalid request"})


if __name__ == "__main__":
    port = int(os.environ["PORT"])
    initialize_storage()
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
