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
SCHEMA_VERSION = 1
DATABASE_PATH = Path(__file__).with_name("game.db")
# This is intentionally process-local operational state. It is neither
# campaign-local nor persisted across server restarts.
maintenance_mode = False


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
            CREATE TABLE IF NOT EXISTS play_campaign_spectators (
                spectator_id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_session_zero_settings (
                campaign_id TEXT PRIMARY KEY,
                rules TEXT NOT NULL,
                tone TEXT NOT NULL,
                consent_json TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_content (
                campaign_id TEXT NOT NULL,
                content_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                PRIMARY KEY (campaign_id, content_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_search_records (
                campaign_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (campaign_id, record_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_rate_events (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                actor TEXT NOT NULL,
                PRIMARY KEY (campaign_id, event_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_service_metrics (
                campaign_id TEXT PRIMARY KEY,
                rejected_rate_events INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_notes (
                campaign_id TEXT NOT NULL,
                note_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                text TEXT NOT NULL,
                visibility TEXT NOT NULL,
                owner TEXT NOT NULL,
                PRIMARY KEY (campaign_id, note_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_whispers (
                campaign_id TEXT NOT NULL,
                whisper_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                from_character_id TEXT NOT NULL,
                to_character_id TEXT NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (campaign_id, whisper_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
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
            CREATE TABLE IF NOT EXISTS play_campaign_invitations (
                campaign_id TEXT NOT NULL,
                invitation_id TEXT NOT NULL,
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                status TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, invitation_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_delegations (
                campaign_id TEXT NOT NULL,
                username TEXT NOT NULL,
                powers_json TEXT NOT NULL,
                active INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, username),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                powers_json TEXT NOT NULL,
                PRIMARY KEY (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_audit_events (
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
            CREATE TABLE IF NOT EXISTS play_campaign_projection_events (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                value TEXT,
                PRIMARY KEY (campaign_id, event_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_replay_events (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (campaign_id, event_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_rng_seeds (
                campaign_id TEXT PRIMARY KEY,
                seed TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                roll_id TEXT NOT NULL,
                sides INTEGER NOT NULL,
                result INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, roll_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                report_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL,
                reporter TEXT NOT NULL,
                action TEXT,
                note TEXT,
                resolver TEXT,
                PRIMARY KEY (campaign_id, report_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries (
                campaign_id TEXT PRIMARY KEY,
                blocked_tags_json TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_safety_events (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                PRIMARY KEY (campaign_id, event_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_feed_events (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (campaign_id, event_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_fixture_seeds (
                campaign_id TEXT PRIMARY KEY,
                fixture_id TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                value TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                PRIMARY KEY (campaign_id, event_id),
                UNIQUE (campaign_id, sequence),
                UNIQUE (campaign_id, idempotency_key),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (
                campaign_id TEXT PRIMARY KEY,
                current_turn INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_submissions (
                campaign_id TEXT NOT NULL,
                submission_id TEXT NOT NULL,
                action TEXT NOT NULL,
                accepted_turn INTEGER NOT NULL,
                next_turn INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, submission_id),
                UNIQUE (campaign_id, accepted_turn),
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
            CREATE TABLE IF NOT EXISTS play_campaign_concentrations (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                spell_id TEXT NOT NULL,
                target TEXT NOT NULL,
                remaining_turns INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id),
                FOREIGN KEY (campaign_id, character_id)
                    REFERENCES play_campaign_members(campaign_id, character_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_inventory_items (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id, item_id),
                FOREIGN KEY (campaign_id, character_id)
                    REFERENCES play_campaign_members(campaign_id, character_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_equipment (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                slot TEXT NOT NULL,
                item_id TEXT NOT NULL,
                attuned INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (campaign_id, character_id, slot),
                FOREIGN KEY (campaign_id, character_id)
                    REFERENCES play_campaign_members(campaign_id, character_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_currency (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                gold INTEGER NOT NULL DEFAULT 10,
                PRIMARY KEY (campaign_id, character_id),
                FOREIGN KEY (campaign_id, character_id)
                    REFERENCES play_campaign_members(campaign_id, character_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_currency_transfers (
                campaign_id TEXT NOT NULL,
                transfer_id INTEGER NOT NULL,
                from_character_id TEXT NOT NULL,
                to_character_id TEXT NOT NULL,
                gold INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, transfer_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                from_character_id TEXT NOT NULL,
                to_character_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                from_gold INTEGER NOT NULL,
                to_gold INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_loot (
                campaign_id TEXT NOT NULL,
                loot_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                status TEXT NOT NULL,
                recipient_character_id TEXT,
                votes INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (campaign_id, loot_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (
                campaign_id TEXT NOT NULL,
                loot_id TEXT NOT NULL,
                voter TEXT NOT NULL,
                recipient_character_id TEXT NOT NULL,
                PRIMARY KEY (campaign_id, loot_id, voter),
                FOREIGN KEY (campaign_id, loot_id)
                    REFERENCES play_campaign_loot(campaign_id, loot_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_npcs (
                campaign_id TEXT NOT NULL,
                npc_id TEXT NOT NULL,
                name TEXT NOT NULL,
                agenda TEXT NOT NULL,
                public_status TEXT NOT NULL,
                PRIMARY KEY (campaign_id, npc_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (
                campaign_id TEXT NOT NULL,
                npc_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                dialogue_id TEXT NOT NULL,
                speaker TEXT NOT NULL,
                text TEXT NOT NULL,
                visibility TEXT NOT NULL,
                PRIMARY KEY (campaign_id, npc_id, dialogue_id),
                UNIQUE (campaign_id, npc_id, sequence),
                FOREIGN KEY (campaign_id, npc_id)
                    REFERENCES play_campaign_npcs(campaign_id, npc_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_relationships (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                score INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, source_id, target_id, kind),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_clues (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                clue_id TEXT NOT NULL,
                text TEXT NOT NULL,
                audience TEXT NOT NULL,
                character_id TEXT,
                PRIMARY KEY (campaign_id, clue_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                FOREIGN KEY (campaign_id, character_id)
                    REFERENCES play_campaign_members(campaign_id, character_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_quests (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                quest_id TEXT NOT NULL,
                title TEXT NOT NULL,
                state TEXT NOT NULL,
                PRIMARY KEY (campaign_id, quest_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_quest_dependencies (
                campaign_id TEXT NOT NULL,
                quest_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                dependency_quest_id TEXT NOT NULL,
                PRIMARY KEY (campaign_id, quest_id, dependency_quest_id),
                UNIQUE (campaign_id, quest_id, position),
                FOREIGN KEY (campaign_id, quest_id)
                    REFERENCES play_campaign_quests(campaign_id, quest_id),
                FOREIGN KEY (campaign_id, dependency_quest_id)
                    REFERENCES play_campaign_quests(campaign_id, quest_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_quest_rewards (
                campaign_id TEXT NOT NULL,
                quest_id TEXT NOT NULL,
                xp INTEGER NOT NULL,
                items_json TEXT NOT NULL,
                awarded INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (campaign_id, quest_id),
                FOREIGN KEY (campaign_id, quest_id)
                    REFERENCES play_campaign_quests(campaign_id, quest_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_quest_reward_grants (
                campaign_id TEXT NOT NULL,
                quest_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                xp INTEGER NOT NULL,
                items_json TEXT NOT NULL,
                PRIMARY KEY (campaign_id, quest_id, character_id),
                FOREIGN KEY (campaign_id, quest_id)
                    REFERENCES play_campaign_quest_rewards(campaign_id, quest_id),
                FOREIGN KEY (campaign_id, character_id)
                    REFERENCES play_campaign_members(campaign_id, character_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_world_events (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                turn_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'scheduled',
                resolution_turn_number INTEGER,
                resolution_text TEXT,
                PRIMARY KEY (campaign_id, event_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_calendars (
                campaign_id TEXT PRIMARY KEY,
                day INTEGER NOT NULL,
                season TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_settlements (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                settlement_id TEXT NOT NULL,
                name TEXT NOT NULL,
                services_json TEXT NOT NULL,
                availability TEXT NOT NULL,
                PRIMARY KEY (campaign_id, settlement_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_settlement_discoveries (
                campaign_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, settlement_id, character_id),
                UNIQUE (campaign_id, settlement_id, sequence),
                FOREIGN KEY (campaign_id, settlement_id)
                    REFERENCES play_campaign_settlements(campaign_id, settlement_id),
                FOREIGN KEY (campaign_id, character_id)
                    REFERENCES play_campaign_members(campaign_id, character_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_shops (
                campaign_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                shop_id TEXT NOT NULL,
                name TEXT NOT NULL,
                buy_price INTEGER NOT NULL,
                sell_price INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, settlement_id, shop_id),
                FOREIGN KEY (campaign_id, settlement_id)
                    REFERENCES play_campaign_settlements(campaign_id, settlement_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_shop_stock (
                campaign_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                shop_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, settlement_id, shop_id, item_id),
                FOREIGN KEY (campaign_id, settlement_id, shop_id)
                    REFERENCES play_campaign_shops(campaign_id, settlement_id, shop_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_recipes (
                campaign_id TEXT NOT NULL,
                recipe_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                name TEXT NOT NULL,
                ingredients_json TEXT NOT NULL,
                output_item TEXT NOT NULL,
                output_quantity INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, recipe_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (
                campaign_id TEXT NOT NULL,
                activity_id TEXT NOT NULL,
                name TEXT NOT NULL,
                cycles_required INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, activity_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_downtime_allocations (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                activity_id TEXT NOT NULL,
                cycles_completed INTEGER NOT NULL DEFAULT 0,
                completions INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (campaign_id, character_id, activity_id),
                FOREIGN KEY (campaign_id, character_id)
                    REFERENCES play_campaign_members(campaign_id, character_id),
                FOREIGN KEY (campaign_id, activity_id)
                    REFERENCES play_campaign_downtime_activities(campaign_id, activity_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_factions (
                campaign_id TEXT NOT NULL,
                faction_id TEXT NOT NULL,
                name TEXT NOT NULL,
                PRIMARY KEY (campaign_id, faction_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_faction_reputation_history (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                faction_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                reputation INTEGER NOT NULL,
                delta INTEGER NOT NULL,
                reason TEXT NOT NULL,
                PRIMARY KEY (campaign_id, sequence),
                FOREIGN KEY (campaign_id, faction_id)
                    REFERENCES play_campaign_factions(campaign_id, faction_id),
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
            CREATE TABLE IF NOT EXISTS play_campaign_exports (
                campaign_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                story TEXT NOT NULL,
                status TEXT NOT NULL,
                PRIMARY KEY (campaign_id, version),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_backups (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                backup_id TEXT NOT NULL,
                story TEXT NOT NULL,
                status TEXT NOT NULL,
                PRIMARY KEY (campaign_id, backup_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_imports (
                campaign_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                story TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_migrations (
                campaign_id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                story TEXT NOT NULL,
                campaign_name TEXT NOT NULL,
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
        # Currency was added after campaign membership.  Seed every preexisting
        # member once, while new members are seeded by the join route below.
        connection.execute(
            "INSERT OR IGNORE INTO play_campaign_currency (campaign_id, character_id, gold) "
            "SELECT campaign_id, character_id, 10 FROM play_campaign_members"
        )
        # Existing campaigns predate this aggregate-only metric row.  Seeding
        # them makes the later counter update safe without exposing any state.
        connection.execute(
            "INSERT OR IGNORE INTO play_campaign_service_metrics (campaign_id) "
            "SELECT id FROM play_campaigns"
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


@app.get("/healthz")
def liveness():
    return jsonify(status="ok")


@app.get("/readyz")
def readiness():
    if maintenance_mode:
        return jsonify(status="maintenance", schema_version=2), 503
    return jsonify(status="ready", schema_version=2)


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
            DROP TABLE IF EXISTS play_campaign_safe_turn_submissions;
            DROP TABLE IF EXISTS play_campaign_safe_turns;
            DROP TABLE IF EXISTS play_campaign_feed_events;
            DROP TABLE IF EXISTS play_campaign_safety_events;
            DROP TABLE IF EXISTS play_campaign_safety_boundaries;
            DROP TABLE IF EXISTS play_campaign_fixture_seeds;
            DROP TABLE IF EXISTS play_campaign_idempotent_events;
            DROP TABLE IF EXISTS play_campaign_rng_rolls;
            DROP TABLE IF EXISTS play_campaign_rng_seeds;
            DROP TABLE IF EXISTS play_campaign_moderation_reports;
            DROP TABLE IF EXISTS play_campaign_replay_events;
            DROP TABLE IF EXISTS play_campaign_projection_events;
            DROP TABLE IF EXISTS play_campaign_service_metrics;
            DROP TABLE IF EXISTS play_campaign_rate_events;
            DROP TABLE IF EXISTS play_campaign_audit_events;
            DROP TABLE IF EXISTS play_campaign_delegation_audit;
            DROP TABLE IF EXISTS play_campaign_delegations;
            DROP TABLE IF EXISTS play_campaign_invitations;
            DROP TABLE IF EXISTS play_campaign_loot_votes;
            DROP TABLE IF EXISTS play_campaign_loot;
            DROP TABLE IF EXISTS play_campaign_faction_reputation_history;
            DROP TABLE IF EXISTS play_campaign_factions;
            DROP TABLE IF EXISTS play_campaign_quest_reward_grants;
            DROP TABLE IF EXISTS play_campaign_quest_rewards;
            DROP TABLE IF EXISTS play_campaign_world_events;
            DROP TABLE IF EXISTS play_campaign_calendars;
            DROP TABLE IF EXISTS play_campaign_shop_stock;
            DROP TABLE IF EXISTS play_campaign_shops;
            DROP TABLE IF EXISTS play_campaign_downtime_allocations;
            DROP TABLE IF EXISTS play_campaign_downtime_activities;
            DROP TABLE IF EXISTS play_campaign_recipes;
            DROP TABLE IF EXISTS play_campaign_settlement_discoveries;
            DROP TABLE IF EXISTS play_campaign_settlements;
            DROP TABLE IF EXISTS play_campaign_quest_dependencies;
            DROP TABLE IF EXISTS play_campaign_quests;
            DROP TABLE IF EXISTS play_campaign_clues;
            DROP TABLE IF EXISTS play_campaign_relationships;
            DROP TABLE IF EXISTS play_campaign_npc_dialogue;
            DROP TABLE IF EXISTS play_campaign_npcs;
            DROP TABLE IF EXISTS play_campaign_transactional_transfers;
            DROP TABLE IF EXISTS play_campaign_currency_transfers;
            DROP TABLE IF EXISTS play_campaign_currency;
            DROP TABLE IF EXISTS play_campaign_equipment;
            DROP TABLE IF EXISTS play_campaign_inventory_items;
            DROP TABLE IF EXISTS play_campaign_concentrations;
            DROP TABLE IF EXISTS play_campaign_spell_casts;
            DROP TABLE IF EXISTS play_campaign_prepared_spells;
            DROP TABLE IF EXISTS play_campaign_character_spells;
            DROP TABLE IF EXISTS play_campaign_whispers;
            DROP TABLE IF EXISTS play_campaign_notes;
            DROP TABLE IF EXISTS play_campaign_members;
            DROP TABLE IF EXISTS play_campaign_content;
            DROP TABLE IF EXISTS play_campaign_search_records;
            DROP TABLE IF EXISTS play_campaign_session_zero_settings;
            DROP TABLE IF EXISTS play_campaign_migrations;
            DROP TABLE IF EXISTS play_campaign_imports;
            DROP TABLE IF EXISTS play_campaign_backups;
            DROP TABLE IF EXISTS play_campaign_exports;
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
            DROP TABLE IF EXISTS play_campaign_spectators;
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


def authenticated_spectator_id():
    """Return the bearer-ticket ID for the spectator-only projection."""
    authorization = request.headers.get("Authorization")
    prefix = "Bearer spectator-"
    if not isinstance(authorization, str) or not authorization.startswith(prefix):
        return None
    spectator_id = authorization[len(prefix):]
    return spectator_id if spectator_id else None


API_SCHEMA_ENDPOINTS = (
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
)


@app.get("/v1/schema")
def read_api_schema():
    """Return the fixed public contract for the supported play API."""
    return jsonify(version="2026-07-29", endpoints=API_SCHEMA_ENDPOINTS)


@app.get("/v1/play/campaigns/<campaign_id>/onboarding")
def read_play_campaign_onboarding(campaign_id):
    """Return the fixed first-read guidance for an authorized campaign actor."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404

        if actor[1] == "dm" and campaign[0] == actor[0]:
            return jsonify(
                role="dm",
                next_steps=["configure-safety", "invite-players", "start-campaign"],
                can_mutate=True,
            )

        is_player_member = actor[1] == "player" and connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone() is not None
        if not is_player_member:
            return jsonify(error="forbidden"), 403

    return jsonify(
        role="player",
        next_steps=["review-party", "take-turn", "submit-action"],
        can_mutate=True,
    )


@app.post("/v1/play/campaigns/<campaign_id>/service-mode")
def set_service_mode(campaign_id):
    """Set the process-global readiness mode through a known campaign."""
    global maintenance_mode

    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    if actor[1] != "dm":
        return jsonify(error="forbidden"), 403

    data = request.get_json(silent=True)
    if (not isinstance(data, dict) or set(data) != {"maintenance"}
            or type(data["maintenance"]) is not bool):
        return jsonify(error="invalid service mode"), 400

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
    if campaign is None:
        return jsonify(error="unknown campaign"), 404

    maintenance_mode = data["maintenance"]
    return jsonify(maintenance=maintenance_mode)


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
            connection.execute(
                "INSERT INTO play_campaign_service_metrics (campaign_id) VALUES (?)",
                (campaign_id,),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="campaign id already exists"), 409
    return jsonify(
        id=campaign_id, name=name, owner=actor[0], status="lobby", max_players=max_players,
    ), 201


@app.post("/v1/play/campaigns/<campaign_id>/spectators")
def create_play_campaign_spectator(campaign_id):
    """Issue a globally unique, campaign-bound spectator bearer ticket."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    if actor[1] != "dm":
        return jsonify(error="forbidden"), 403

    data = json_with_required_fields(("spectator_id",))
    if data is None or not isinstance(data["spectator_id"], str) or not data["spectator_id"]:
        return jsonify(error="invalid spectator"), 400

    spectator_id = data["spectator_id"]
    try:
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return jsonify(error="unknown campaign"), 404
            if campaign[0] != actor[0]:
                return jsonify(error="forbidden"), 403
            connection.execute(
                "INSERT INTO play_campaign_spectators (spectator_id, campaign_id) VALUES (?, ?)",
                (spectator_id, campaign_id),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="spectator id already exists"), 409

    return jsonify(spectator_id=spectator_id, token=f"spectator-{spectator_id}"), 201


@app.get("/v1/play/campaigns/<campaign_id>/spectator-view")
def read_play_campaign_spectator_view(campaign_id):
    """Return the deliberately narrow, read-only spectator projection."""
    spectator_id = authenticated_spectator_id()
    if spectator_id is None:
        # Session credentials are authenticated elsewhere, but are expressly
        # forbidden from this spectator-only route.
        if authenticated_actor() is not None:
            return jsonify(error="forbidden"), 403
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        ticket = connection.execute(
            "SELECT campaign_id FROM play_campaign_spectators WHERE spectator_id = ?",
            (spectator_id,),
        ).fetchone()
        if ticket is None:
            return jsonify(error="unauthorized"), 401

        campaign = connection.execute(
            "SELECT name, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if ticket[0] != campaign_id:
            return jsonify(error="forbidden"), 403

        party_size = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]
        document = connection.execute(
            "SELECT story FROM play_campaign_documents WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()

    return jsonify(
        campaign_id=campaign_id,
        name=campaign[0],
        status=campaign[1],
        party_size=party_size,
        story="" if document is None else document[0],
    )


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
        connection.execute("BEGIN IMMEDIATE")
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
        # The established exploration flow records a document revision after a
        # DM nudge.  Preserve that public event identity, while ordinary story
        # edits (including backup snapshot preparation) remain document-only.
        has_nudge = connection.execute(
            "SELECT 1 FROM play_campaign_events "
            "WHERE campaign_id = ? AND kind = 'nudge' LIMIT 1",
            (campaign_id,),
        ).fetchone() is not None
        if has_nudge:
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


@app.post("/v1/play/campaigns/<campaign_id>/exports")
def create_play_campaign_export(campaign_id):
    """Create an immutable, DM-only snapshot of the public campaign state."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        # Version allocation and the captured values must be one atomic write.
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403

        document = connection.execute(
            "SELECT story FROM play_campaign_documents WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        story = document[0] if document is not None else ""
        version = connection.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 "
            "FROM play_campaign_exports WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_exports (campaign_id, version, story, status) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, version, story, campaign[1]),
        )

    return jsonify(version=version, story=story, status=campaign[1]), 201


@app.get("/v1/play/campaigns/<campaign_id>/exports")
def list_play_campaign_exports(campaign_id):
    """List a campaign DM's immutable snapshots in version order."""
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
        rows = connection.execute(
            "SELECT version, story, status FROM play_campaign_exports "
            "WHERE campaign_id = ? ORDER BY version",
            (campaign_id,),
        ).fetchall()

    return jsonify(exports=[
        {"version": version, "story": story, "status": status}
        for version, story, status in rows
    ])


@app.get("/v1/play/campaigns/<campaign_id>/exports/<int:version>")
def read_play_campaign_export(campaign_id, version):
    """Return one immutable export snapshot to its campaign DM."""
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
        export = connection.execute(
            "SELECT version, story, status FROM play_campaign_exports "
            "WHERE campaign_id = ? AND version = ?",
            (campaign_id, version),
        ).fetchone()

    if export is None:
        return jsonify(error="unknown export"), 404
    return jsonify(version=export[0], story=export[1], status=export[2])


@app.post("/v1/play/campaigns/<campaign_id>/backups")
def create_play_campaign_backup(campaign_id):
    """Capture an immutable owner-only snapshot of a campaign's public state."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        # Allocate the sequence and read its contents in the same write
        # transaction, so concurrent creates cannot share a backup ID.
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403

        document = connection.execute(
            "SELECT story FROM play_campaign_documents WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        story = document[0] if document is not None else ""
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_backups "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        backup_id = f"backup-{sequence}"
        connection.execute(
            "INSERT INTO play_campaign_backups "
            "(campaign_id, sequence, backup_id, story, status) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, backup_id, story, campaign[1]),
        )

    return jsonify(backup_id=backup_id, story=story, status=campaign[1]), 201


@app.get("/v1/play/campaigns/<campaign_id>/backups")
def list_play_campaign_backups(campaign_id):
    """List immutable campaign snapshots in their creation sequence."""
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
        rows = connection.execute(
            "SELECT backup_id, story, status FROM play_campaign_backups "
            "WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()

    return jsonify(backups=[
        {"backup_id": backup_id, "story": story, "status": status}
        for backup_id, story, status in rows
    ])


@app.post("/v1/play/campaigns/<campaign_id>/backups/<backup_id>/restore")
def restore_play_campaign_backup(campaign_id, backup_id):
    """Apply one immutable snapshot without changing it or emitting events."""
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
        backup = connection.execute(
            "SELECT backup_id, story, status FROM play_campaign_backups "
            "WHERE campaign_id = ? AND backup_id = ?",
            (campaign_id, backup_id),
        ).fetchone()
        if backup is None:
            return jsonify(error="unknown backup"), 404

        connection.execute(
            "INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story",
            (campaign_id, backup[1], ""),
        )
        connection.execute(
            "UPDATE play_campaigns SET status = ? WHERE id = ?",
            (backup[2], campaign_id),
        )

    return jsonify(backup_id=backup[0], story=backup[1], status=backup[2])


@app.post("/v1/play/campaigns/<campaign_id>/imports")
def import_play_campaign_snapshot(campaign_id):
    """Atomically apply a compatible exported campaign snapshot for its DM."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    snapshot = request.get_json(silent=True)
    if (not isinstance(snapshot, dict)
            or set(snapshot) != {"version", "story", "status"}
            or type(snapshot["version"]) is not int
            or snapshot["version"] != 1
            or not valid_nonblank_text(snapshot["story"])
            or snapshot["status"] not in ("lobby", "started")):
        return jsonify(error="invalid import"), 400

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
            "INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story",
            (campaign_id, snapshot["story"], ""),
        )
        connection.execute(
            "UPDATE play_campaigns SET status = ? WHERE id = ?",
            (snapshot["status"], campaign_id),
        )
        connection.execute(
            "INSERT INTO play_campaign_imports (campaign_id, version, story, status) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id) DO UPDATE SET "
            "version = excluded.version, story = excluded.story, status = excluded.status",
            (campaign_id, snapshot["version"], snapshot["story"], snapshot["status"]),
        )

    return jsonify(
        version=snapshot["version"], story=snapshot["story"], status=snapshot["status"],
    )


@app.get("/v1/play/campaigns/<campaign_id>/import-state")
def read_play_campaign_import_state(campaign_id):
    """Return the most recently applied compatible snapshot to its campaign DM."""
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
        imported = connection.execute(
            "SELECT version, story, status FROM play_campaign_imports WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()

    if imported is None:
        return jsonify(error="unknown import"), 404
    return jsonify(version=imported[0], story=imported[1], status=imported[2])


@app.post("/v1/play/campaigns/<campaign_id>/migrations")
def migrate_play_campaign_snapshot(campaign_id):
    """Deterministically upgrade one legacy version-one campaign snapshot."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    snapshot = json_with_required_fields(("schema_version", "story"))
    if (snapshot is None
            or type(snapshot["schema_version"]) is not int
            or snapshot["schema_version"] != 1
            or not valid_nonblank_text(snapshot["story"])):
        return jsonify(error="invalid migration"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner, name FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403

        migrated = connection.execute(
            "SELECT story FROM play_campaign_migrations WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        response = {
            "schema_version": 2,
            "story": snapshot["story"],
            "campaign_name": campaign[1],
        }
        if migrated is not None and migrated[0] == snapshot["story"]:
            return jsonify(response), 200

        connection.execute(
            "INSERT INTO play_campaign_migrations "
            "(campaign_id, schema_version, story, campaign_name) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id) DO UPDATE SET "
            "schema_version = excluded.schema_version, story = excluded.story, "
            "campaign_name = excluded.campaign_name",
            (campaign_id, 2, snapshot["story"], campaign[1]),
        )

    return jsonify(response), 201


@app.get("/v1/play/campaigns/<campaign_id>/migration-state")
def read_play_campaign_migration_state(campaign_id):
    """Return the current migrated schema state to the owning DM only."""
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
        migrated = connection.execute(
            "SELECT schema_version, story, campaign_name "
            "FROM play_campaign_migrations WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()

    if migrated is None:
        return jsonify(error="unknown migration"), 404
    return jsonify(
        schema_version=migrated[0], story=migrated[1], campaign_name=migrated[2]
    )


@app.put("/v1/play/campaigns/<campaign_id>/session-zero")
def update_play_campaign_session_zero(campaign_id):
    """Store the DM's pre-start rules, tone, and consent boundaries."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("rules", "tone", "consent"))
    consent = None if data is None else data["consent"]
    if (data is None
            or not valid_nonblank_text(data["rules"])
            or not valid_nonblank_text(data["tone"])
            or not isinstance(consent, list)
            or not consent
            or any(not valid_nonblank_text(boundary) for boundary in consent)
            or len(set(consent)) != len(consent)):
        return jsonify(error="invalid session-zero settings"), 400

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        if campaign[1] != "lobby":
            return jsonify(error="campaign has already started"), 409
        connection.execute(
            "INSERT INTO play_campaign_session_zero_settings "
            "(campaign_id, rules, tone, consent_json) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id) DO UPDATE SET rules = excluded.rules, "
            "tone = excluded.tone, consent_json = excluded.consent_json",
            (campaign_id, data["rules"], data["tone"], json.dumps(consent)),
        )

    return jsonify(rules=data["rules"], tone=data["tone"], consent=consent)


@app.get("/v1/play/campaigns/<campaign_id>/session-zero")
def read_play_campaign_session_zero(campaign_id):
    """Return stored session-zero settings to the owner or a joined player."""
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
        settings = connection.execute(
            "SELECT rules, tone, consent_json FROM play_campaign_session_zero_settings "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()

    if settings is None:
        return jsonify(error="session-zero settings not found"), 404
    return jsonify(rules=settings[0], tone=settings[1], consent=json.loads(settings[2]))


def content_tags(value, allow_empty):
    """Validate an ordered, duplicate-free list of content tags."""
    if not isinstance(value, list) or (not allow_empty and not value):
        return None
    if (any(not valid_nonblank_text(tag) for tag in value)
            or len(set(value)) != len(value)):
        return None
    return value


def content_response(content):
    return {
        "content_id": content[0],
        "kind": content[1],
        "text": content[2],
        "tags": json.loads(content[3]),
    }


@app.post("/v1/play/campaigns/<campaign_id>/content")
def create_play_campaign_content(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("content_id", "kind", "text", "tags"))
    tags = None if data is None else content_tags(data["tags"], allow_empty=False)
    if (data is None
            or not valid_nonblank_text(data["content_id"])
            or not valid_nonblank_text(data["kind"])
            or not valid_nonblank_text(data["text"])
            or tags is None):
        return jsonify(error="invalid content"), 400

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
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_content "
                "WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_content "
                "(campaign_id, content_id, sequence, kind, text, tags_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, data["content_id"], sequence, data["kind"], data["text"],
                 json.dumps(tags, separators=(",", ":"))),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="content id already exists"), 409

    return jsonify(content_id=data["content_id"], kind=data["kind"], text=data["text"],
                   tags=tags), 201


@app.put("/v1/play/campaigns/<campaign_id>/content/<content_id>/tags")
def update_play_campaign_content_tags(campaign_id, content_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("tags",))
    tags = None if data is None else content_tags(data["tags"], allow_empty=True)
    if data is None or tags is None:
        return jsonify(error="invalid content tags"), 400

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        content = connection.execute(
            "SELECT content_id, kind, text FROM play_campaign_content "
            "WHERE campaign_id = ? AND content_id = ?", (campaign_id, content_id),
        ).fetchone()
        if content is None:
            return jsonify(error="unknown content"), 404
        connection.execute(
            "UPDATE play_campaign_content SET tags_json = ? "
            "WHERE campaign_id = ? AND content_id = ?",
            (json.dumps(tags, separators=(",", ":")), campaign_id, content_id),
        )

    return jsonify(content_id=content[0], kind=content[1], text=content[2], tags=tags)


@app.get("/v1/play/campaigns/<campaign_id>/content")
def read_play_campaign_content(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    exclude_tag = request.args.get("exclude_tag")
    if exclude_tag is not None and not valid_nonblank_text(exclude_tag):
        return jsonify(error="invalid exclude tag"), 400

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
        content = connection.execute(
            "SELECT content_id, kind, text, tags_json FROM play_campaign_content "
            "WHERE campaign_id = ? ORDER BY sequence", (campaign_id,),
        ).fetchall()

    records = [content_response(record) for record in content]
    if not is_owner and exclude_tag is not None:
        records = [record for record in records if exclude_tag not in record["tags"]]
    return jsonify(content=records)


def play_campaign_search_access(connection, campaign_id, actor):
    """Return the campaign when its DM or a member may search its records."""
    campaign = connection.execute(
        "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if campaign is None:
        return None, (jsonify(error="unknown campaign"), 404)
    is_member = connection.execute(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        (campaign_id, actor[0]),
    ).fetchone() is not None
    if campaign[0] != actor[0] and not is_member:
        return None, (jsonify(error="forbidden"), 403)
    return campaign, None


@app.post("/v1/play/campaigns/<campaign_id>/search-records")
def create_play_campaign_search_record(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("record_id", "text"))
    if (data is None
            or not valid_nonblank_text(data["record_id"])
            or not valid_nonblank_text(data["text"])):
        return jsonify(error="invalid search record"), 400

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
            duplicate = connection.execute(
                "SELECT 1 FROM play_campaign_search_records "
                "WHERE campaign_id = ? AND (record_id = ? OR text = ?)",
                (campaign_id, data["record_id"], data["text"]),
            ).fetchone()
            if duplicate is not None:
                return jsonify(error="duplicate search record"), 400
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM play_campaign_search_records WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_search_records "
                "(campaign_id, record_id, sequence, text) VALUES (?, ?, ?, ?)",
                (campaign_id, data["record_id"], sequence, data["text"]),
            )
    except sqlite3.IntegrityError:
        # The pre-insert check above handles ordinary duplicate submissions.
        # Retain the same invalid-request contract if another writer wins a
        # race between that check and this insert.
        return jsonify(error="duplicate search record"), 400

    return jsonify(record_id=data["record_id"], text=data["text"]), 201


def search_pagination_value(name, default, minimum, maximum=None):
    """Parse an ASCII integer query value without accepting partial numbers."""
    value = request.args.get(name)
    if value is None:
        return default
    if not value.isascii() or not value.isdigit():
        return None
    number = int(value)
    if number < minimum or (maximum is not None and number > maximum):
        return None
    return number


@app.get("/v1/play/campaigns/<campaign_id>/search-records")
def read_play_campaign_search_records(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    limit = search_pagination_value("limit", 2, 1, 3)
    cursor = search_pagination_value("cursor", 0, 0)
    if limit is None or cursor is None:
        return jsonify(error="invalid search pagination"), 400
    query = request.args.get("q")

    with database_connection() as connection:
        _, error = play_campaign_search_access(connection, campaign_id, actor)
        if error is not None:
            return error
        rows = connection.execute(
            "SELECT record_id, text FROM play_campaign_search_records "
            "WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()

    records = [{"record_id": row[0], "text": row[1]} for row in rows]
    if query is not None:
        normalized_query = query.casefold()
        records = [record for record in records if normalized_query in record["text"].casefold()]
    page = records[cursor:cursor + limit]
    next_cursor = cursor + len(page)
    if next_cursor >= len(records):
        next_cursor = None
    return jsonify(records=page, next_cursor=next_cursor)


def play_campaign_rate_event_access(connection, campaign_id, actor):
    """Allow a campaign's DM and its members to use rate events."""
    campaign = connection.execute(
        "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if campaign is None:
        return (jsonify(error="unknown campaign"), 404)
    is_dm = actor[1] == "dm" and campaign[0] == actor[0]
    is_member = connection.execute(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        (campaign_id, actor[0]),
    ).fetchone() is not None
    if not is_dm and not is_member:
        return (jsonify(error="forbidden"), 403)
    return None


@app.post("/v1/play/campaigns/<campaign_id>/rate-events")
def create_play_campaign_rate_event(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("event_id",))
    if data is None or not valid_nonblank_text(data["event_id"]):
        return jsonify(error="invalid rate event"), 400

    try:
        with database_connection() as connection:
            # The lock includes both the allowance count and the insertion, so
            # accepted events remain ordered and cannot overrun the limit.
            connection.execute("BEGIN IMMEDIATE")
            error = play_campaign_rate_event_access(connection, campaign_id, actor)
            if error is not None:
                return error
            duplicate = connection.execute(
                "SELECT 1 FROM play_campaign_rate_events "
                "WHERE campaign_id = ? AND event_id = ?",
                (campaign_id, data["event_id"]),
            ).fetchone()
            if duplicate is not None:
                return jsonify(error="event id already exists"), 400
            accepted = connection.execute(
                "SELECT COUNT(*) FROM play_campaign_rate_events "
                "WHERE campaign_id = ? AND actor = ?",
                (campaign_id, actor[0]),
            ).fetchone()[0]
            if accepted >= 2:
                connection.execute(
                    "UPDATE play_campaign_service_metrics "
                    "SET rejected_rate_events = rejected_rate_events + 1 "
                    "WHERE campaign_id = ?",
                    (campaign_id,),
                )
                return jsonify(limit=2, remaining=0), 429
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM play_campaign_rate_events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_rate_events "
                "(campaign_id, sequence, event_id, actor) VALUES (?, ?, ?, ?)",
                (campaign_id, sequence, data["event_id"], actor[0]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="event id already exists"), 400

    return jsonify(event_id=data["event_id"], actor=actor[0], remaining=1 - accepted), 201


@app.get("/v1/play/campaigns/<campaign_id>/rate-events")
def read_play_campaign_rate_events(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        error = play_campaign_rate_event_access(connection, campaign_id, actor)
        if error is not None:
            return error
        events = connection.execute(
            "SELECT event_id, actor FROM play_campaign_rate_events "
            "WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()
        accepted = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_rate_events "
            "WHERE campaign_id = ? AND actor = ?",
            (campaign_id, actor[0]),
        ).fetchone()[0]

    return jsonify(
        events=[{"event_id": event[0], "actor": event[1]} for event in events],
        remaining=max(0, 2 - accepted),
    )


@app.get("/v1/play/campaigns/<campaign_id>/metrics")
def read_play_campaign_service_metrics(campaign_id):
    """Return the campaign owner's safe, aggregate service counters only."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        accepted_rate_events = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        projection_events = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_projection_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        metric = connection.execute(
            "SELECT rejected_rate_events FROM play_campaign_service_metrics "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()

    return jsonify({
        "accepted_rate_events": accepted_rate_events,
        "rejected_rate_events": 0 if metric is None else metric[0],
        "projection_events": projection_events,
        "uptime_ticks": 1,
    })


def play_campaign_privacy_access(connection, campaign_id, actor):
    """Return whether an actor is this campaign's DM or a current member."""
    campaign = connection.execute(
        "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if campaign is None:
        return None, None, (jsonify(error="unknown campaign"), 404)
    is_dm = campaign[0] == actor[0]
    is_member = connection.execute(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        (campaign_id, actor[0]),
    ).fetchone() is not None
    if not is_dm and not is_member:
        return None, None, (jsonify(error="forbidden"), 403)
    return is_dm, is_member, None


def note_response(note):
    return {
        "note_id": note[0],
        "text": note[1],
        "visibility": note[2],
        "owner": note[3],
    }


@app.post("/v1/play/campaigns/<campaign_id>/notes")
def create_play_campaign_note(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    data = json_with_required_fields(("note_id", "text", "visibility"))
    if (data is None or not valid_nonblank_text(data["note_id"])
            or not valid_nonblank_text(data["text"])
            or data["visibility"] not in ("private", "party")):
        return jsonify(error="invalid note"), 400
    try:
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            is_dm, is_member, error = play_campaign_privacy_access(connection, campaign_id, actor)
            if error is not None:
                return error
            # The campaign owner may keep private preparation notes even
            # though DMs are not party members.
            if not is_dm and not is_member:
                return jsonify(error="forbidden"), 403
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_notes "
                "WHERE campaign_id = ?", (campaign_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_notes "
                "(campaign_id, note_id, sequence, text, visibility, owner) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, data["note_id"], sequence, data["text"], data["visibility"], actor[0]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="note id already exists"), 409
    return jsonify(note_id=data["note_id"], text=data["text"], visibility=data["visibility"],
                   owner=actor[0]), 201


@app.post("/v1/play/campaigns/<campaign_id>/messages")
def create_play_campaign_message(campaign_id):
    """Append a campaign chat event for an authenticated campaign actor."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("text",))
    if data is None or not valid_nonblank_text(data["text"]):
        return jsonify(error="invalid message"), 400

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
        if campaign[0] != actor[0] and not is_member:
            return jsonify(error="forbidden"), 403
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events "
            "WHERE campaign_id = ?", (campaign_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, "chat", actor[0], data["text"]),
        )

    return jsonify(
        sequence=sequence,
        kind="chat",
        actor=actor[0],
        text=data["text"],
        current_actor=campaign[1],
    ), 201


@app.get("/v1/play/campaigns/<campaign_id>/notes")
def read_play_campaign_notes(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    with database_connection() as connection:
        is_dm, _, error = play_campaign_privacy_access(connection, campaign_id, actor)
        if error is not None:
            return error
        notes = connection.execute(
            "SELECT note_id, text, visibility, owner FROM play_campaign_notes "
            "WHERE campaign_id = ? ORDER BY sequence", (campaign_id,),
        ).fetchall()
    if not is_dm:
        notes = [note for note in notes if note[2] == "party" or note[3] == actor[0]]
    return jsonify(notes=[note_response(note) for note in notes])


@app.get("/v1/play/campaigns/<campaign_id>/notes/<note_id>")
def read_play_campaign_note(campaign_id, note_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    with database_connection() as connection:
        is_dm, _, error = play_campaign_privacy_access(connection, campaign_id, actor)
        if error is not None:
            return error
        note = connection.execute(
            "SELECT note_id, text, visibility, owner FROM play_campaign_notes "
            "WHERE campaign_id = ? AND note_id = ?", (campaign_id, note_id),
        ).fetchone()
    if note is None:
        return jsonify(error="unknown note"), 404
    if note[2] == "private" and not is_dm and note[3] != actor[0]:
        return jsonify(error="forbidden"), 403
    return jsonify(note_response(note))


@app.put("/v1/play/campaigns/<campaign_id>/notes/<note_id>")
def update_play_campaign_note(campaign_id, note_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    data = json_with_required_fields(("text", "visibility"))
    if (data is None or not valid_nonblank_text(data["text"])
            or data["visibility"] not in ("private", "party")):
        return jsonify(error="invalid note"), 400
    with database_connection() as connection:
        _, _, error = play_campaign_privacy_access(connection, campaign_id, actor)
        if error is not None:
            return error
        note = connection.execute(
            "SELECT note_id, text, visibility, owner FROM play_campaign_notes "
            "WHERE campaign_id = ? AND note_id = ?", (campaign_id, note_id),
        ).fetchone()
        if note is None:
            return jsonify(error="unknown note"), 404
        if note[3] != actor[0]:
            return jsonify(error="forbidden"), 403
        connection.execute(
            "UPDATE play_campaign_notes SET text = ?, visibility = ? "
            "WHERE campaign_id = ? AND note_id = ?",
            (data["text"], data["visibility"], campaign_id, note_id),
        )
    return jsonify(note_id=note_id, text=data["text"], visibility=data["visibility"],
                   owner=actor[0])


def whisper_response(whisper):
    return {
        "whisper_id": whisper[0],
        "from_character_id": whisper[1],
        "to_character_id": whisper[2],
        "text": whisper[3],
    }


@app.post("/v1/play/campaigns/<campaign_id>/whispers")
def create_play_campaign_whisper(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    data = json_with_required_fields(("whisper_id", "to_character_id", "text"))
    if (data is None or not valid_nonblank_text(data["whisper_id"])
            or not valid_nonblank_text(data["to_character_id"])
            or not valid_nonblank_text(data["text"])):
        return jsonify(error="invalid whisper"), 400
    try:
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _, is_member, error = play_campaign_privacy_access(connection, campaign_id, actor)
            if error is not None:
                return error
            sender = connection.execute(
                "SELECT character_id FROM play_campaign_members "
                "WHERE campaign_id = ? AND owner = ?", (campaign_id, actor[0]),
            ).fetchone()
            if actor[1] != "player" or not is_member or sender is None:
                return jsonify(error="forbidden"), 403
            recipient = connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, data["to_character_id"]),
            ).fetchone()
            if recipient is None:
                return jsonify(error="invalid whisper"), 400
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_whispers "
                "WHERE campaign_id = ?", (campaign_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_whispers "
                "(campaign_id, whisper_id, sequence, from_character_id, to_character_id, text) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, data["whisper_id"], sequence, sender[0],
                 data["to_character_id"], data["text"]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="whisper id already exists"), 409
    return jsonify(whisper_id=data["whisper_id"], from_character_id=sender[0],
                   to_character_id=data["to_character_id"], text=data["text"]), 201


@app.get("/v1/play/campaigns/<campaign_id>/whispers")
def read_play_campaign_whispers(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    with database_connection() as connection:
        is_dm, _, error = play_campaign_privacy_access(connection, campaign_id, actor)
        if error is not None:
            return error
        whispers = connection.execute(
            "SELECT whisper_id, from_character_id, to_character_id, text "
            "FROM play_campaign_whispers WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()
        character = connection.execute(
            "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND owner = ?",
            (campaign_id, actor[0]),
        ).fetchone()
    if not is_dm:
        whispers = [] if character is None else [
            whisper for whisper in whispers if character[0] in (whisper[1], whisper[2])
        ]
    return jsonify(whispers=[whisper_response(whisper) for whisper in whispers])


@app.get("/v1/play/campaigns/<campaign_id>/characters/<character_id>/sheet")
def read_play_campaign_character_sheet(campaign_id, character_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    with database_connection() as connection:
        is_dm, _, error = play_campaign_privacy_access(connection, campaign_id, actor)
        if error is not None:
            return error
        character = connection.execute(
            "SELECT owner, name, class FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?", (campaign_id, character_id),
        ).fetchone()
    if character is None:
        return jsonify(error="unknown character"), 404
    if not is_dm and character[0] != actor[0]:
        return jsonify(error="forbidden"), 403
    return jsonify(character_id=character_id, owner=character[0], name=character[1],
                   **{"class": character[2]}, level=1, proficiency_bonus=2, hp_max=10,
                   armor_class=10)


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
            connection.execute(
                "INSERT INTO play_campaign_currency (campaign_id, character_id, gold) "
                "VALUES (?, ?, 10)",
                (campaign_id, character_id),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="party membership already exists"), 409
    return jsonify(username=actor[0], character_id=character_id, name=name,
                   **{"class": character_class}), 201


def invitation_view(invitation):
    return {
        "invitation_id": invitation[0],
        "username": invitation[1],
        "character_id": invitation[2],
        "status": invitation[3],
    }


@app.post("/v1/play/campaigns/<campaign_id>/invitations")
def create_play_campaign_invitation(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("invitation_id", "username", "character_id"))
    if data is None or not all(
            valid_nonblank_text(data[field])
            for field in ("invitation_id", "username", "character_id")):
        return jsonify(error="invalid invitation"), 400

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
            target = connection.execute(
                "SELECT 1 FROM users WHERE username = ? AND role = 'player'",
                (data["username"],),
            ).fetchone()
            if target is None:
                return jsonify(error="invalid invitation"), 400
            existing = connection.execute(
                "SELECT username FROM play_campaign_invitations "
                "WHERE campaign_id = ? AND invitation_id = ?",
                (campaign_id, data["invitation_id"]),
            ).fetchone()
            if existing is not None:
                return jsonify(error="invitation id already exists"), 409
            pending = connection.execute(
                "SELECT 1 FROM play_campaign_invitations "
                "WHERE campaign_id = ? AND username = ? AND status = 'pending'",
                (campaign_id, data["username"]),
            ).fetchone()
            if pending is not None:
                return jsonify(error="pending invitation already exists"), 409
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_invitations "
                "WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_invitations "
                "(campaign_id, invitation_id, username, character_id, status, sequence) "
                "VALUES (?, ?, ?, ?, 'pending', ?)",
                (campaign_id, data["invitation_id"], data["username"],
                 data["character_id"], sequence),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="invitation already exists"), 409

    return jsonify(invitation_id=data["invitation_id"], username=data["username"],
                   character_id=data["character_id"], status="pending"), 201


@app.post("/v1/play/campaigns/<campaign_id>/invitations/<invitation_id>/accept")
def accept_play_campaign_invitation(campaign_id, invitation_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        invitation = connection.execute(
            "SELECT invitation_id, username, character_id, status "
            "FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?",
            (campaign_id, invitation_id),
        ).fetchone()
        if invitation is None:
            return jsonify(error="unknown invitation"), 404
        if actor[0] != invitation[1]:
            return jsonify(error="forbidden"), 403
        if invitation[3] != "pending":
            return jsonify(error="invitation already accepted"), 409
        member = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone()
        if member is not None:
            return jsonify(error="party membership already exists"), 409
        connection.execute(
            "INSERT INTO play_campaign_members "
            "(character_id, campaign_id, username, owner, name, class) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (invitation[2], campaign_id, actor[0], actor[0], invitation[2], "adventurer"),
        )
        connection.execute(
            "INSERT INTO play_campaign_currency (campaign_id, character_id, gold) "
            "VALUES (?, ?, 10)",
            (campaign_id, invitation[2]),
        )
        connection.execute(
            "UPDATE play_campaign_invitations SET status = 'accepted' "
            "WHERE campaign_id = ? AND invitation_id = ?",
            (campaign_id, invitation_id),
        )

    return jsonify(invitation_id=invitation[0], username=invitation[1],
                   character_id=invitation[2], status="accepted")


@app.get("/v1/play/campaigns/<campaign_id>/invitations")
def list_play_campaign_invitations(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] == "dm" and campaign[0] == actor[0]:
            invitations = connection.execute(
                "SELECT invitation_id, username, character_id, status "
                "FROM play_campaign_invitations WHERE campaign_id = ? ORDER BY sequence",
                (campaign_id,),
            ).fetchall()
        else:
            is_member = connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, actor[0]),
            ).fetchone() is not None
            is_target = connection.execute(
                "SELECT 1 FROM play_campaign_invitations "
                "WHERE campaign_id = ? AND username = ?",
                (campaign_id, actor[0]),
            ).fetchone() is not None
            if not is_member and not is_target:
                return jsonify(error="forbidden"), 403
            if is_target:
                invitations = connection.execute(
                    "SELECT invitation_id, username, character_id, status "
                    "FROM play_campaign_invitations WHERE campaign_id = ? AND username = ? "
                    "ORDER BY sequence",
                    (campaign_id, actor[0]),
                ).fetchall()
            else:
                invitations = []

    return jsonify(invitations=[invitation_view(invitation) for invitation in invitations])


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


@app.get("/v1/play/campaigns/<campaign_id>/characters/<character_id>/currency")
def read_play_campaign_character_currency(campaign_id, character_id):
    """Return a campaign member-visible character's gold balance."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        _, error = play_campaign_member_viewer(connection, campaign_id, actor)
        if error is not None:
            return error
        currency = connection.execute(
            "SELECT currency.gold FROM play_campaign_members AS members "
            "JOIN play_campaign_currency AS currency "
            "ON currency.campaign_id = members.campaign_id "
            "AND currency.character_id = members.character_id "
            "WHERE members.campaign_id = ? AND members.character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if currency is None:
            return jsonify(error="unknown character"), 404

    return jsonify(character_id=character_id, gold=currency[0])


@app.post("/v1/play/campaigns/<campaign_id>/characters/<character_id>/currency/transfers")
def transfer_play_campaign_character_currency(campaign_id, character_id):
    """Atomically transfer positive gold from an owned character to a party member."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("to_character_id", "gold"))
    if (data is None
            or not valid_nonblank_text(data["to_character_id"])
            or type(data["gold"]) is not int
            or data["gold"] <= 0
            or data["to_character_id"] == character_id):
        return jsonify(error="invalid currency transfer"), 400

    with database_connection() as connection:
        # The write lock covers balance reads, both updates, and transfer-id
        # allocation, so a failed transfer cannot partially change balances.
        connection.execute("BEGIN IMMEDIATE")
        _, error = play_campaign_member_viewer(connection, campaign_id, actor)
        if error is not None:
            return error
        source = connection.execute(
            "SELECT members.owner, currency.gold FROM play_campaign_members AS members "
            "JOIN play_campaign_currency AS currency "
            "ON currency.campaign_id = members.campaign_id "
            "AND currency.character_id = members.character_id "
            "WHERE members.campaign_id = ? AND members.character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if source is None:
            return jsonify(error="unknown character"), 404
        if source[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        destination = connection.execute(
            "SELECT gold FROM play_campaign_currency "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, data["to_character_id"]),
        ).fetchone()
        if destination is None:
            return jsonify(error="invalid currency transfer"), 400
        if source[1] < data["gold"]:
            return jsonify(error="insufficient gold"), 409

        from_gold = source[1] - data["gold"]
        to_gold = destination[0] + data["gold"]
        transfer_id = connection.execute(
            "SELECT COALESCE(MAX(transfer_id), 0) + 1 "
            "FROM play_campaign_currency_transfers WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        connection.execute(
            "UPDATE play_campaign_currency SET gold = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (from_gold, campaign_id, character_id),
        )
        connection.execute(
            "UPDATE play_campaign_currency SET gold = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (to_gold, campaign_id, data["to_character_id"]),
        )
        connection.execute(
            "INSERT INTO play_campaign_currency_transfers "
            "(campaign_id, transfer_id, from_character_id, to_character_id, gold) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, transfer_id, character_id, data["to_character_id"], data["gold"]),
        )

    return jsonify(
        from_character_id=character_id,
        to_character_id=data["to_character_id"],
        gold=data["gold"],
        from_gold=from_gold,
        to_gold=to_gold,
        transfer_id=transfer_id,
    ), 201


@app.post("/v1/play/campaigns/<campaign_id>/transactional-transfers")
def create_play_campaign_transactional_transfer(campaign_id):
    """Commit a currency movement and its public record as one transaction."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields((
        "from_character_id", "to_character_id", "amount", "simulate_failure",
    ))
    if (data is None
            or not valid_nonblank_text(data["from_character_id"])
            or not valid_nonblank_text(data["to_character_id"])
            or data["from_character_id"] == data["to_character_id"]
            or type(data["amount"]) is not int
            or data["amount"] <= 0
            or type(data["simulate_failure"]) is not bool):
        return jsonify(error="invalid transactional transfer"), 400

    with database_connection() as connection:
        # Keep validation, both balance mutations, and sequence allocation in
        # one write transaction.  In particular, the simulated failure occurs
        # before any mutation, so it has no observable partial effects.
        connection.execute("BEGIN IMMEDIATE")
        _, error = play_campaign_member_viewer(connection, campaign_id, actor)
        if error is not None:
            return error

        source = connection.execute(
            "SELECT members.owner, currency.gold FROM play_campaign_members AS members "
            "JOIN play_campaign_currency AS currency "
            "ON currency.campaign_id = members.campaign_id "
            "AND currency.character_id = members.character_id "
            "WHERE members.campaign_id = ? AND members.character_id = ?",
            (campaign_id, data["from_character_id"]),
        ).fetchone()
        destination = connection.execute(
            "SELECT gold FROM play_campaign_currency "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, data["to_character_id"]),
        ).fetchone()
        if source is None or destination is None:
            return jsonify(error="invalid transactional transfer"), 400
        if source[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        if source[1] < data["amount"]:
            return jsonify(error="insufficient gold"), 409

        from_gold = source[1] - data["amount"]
        to_gold = destination[0] + data["amount"]
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 "
            "FROM play_campaign_transactional_transfers WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]

        if data["simulate_failure"]:
            return jsonify(error="simulated failure"), 500

        connection.execute(
            "UPDATE play_campaign_currency SET gold = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (from_gold, campaign_id, data["from_character_id"]),
        )
        connection.execute(
            "UPDATE play_campaign_currency SET gold = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (to_gold, campaign_id, data["to_character_id"]),
        )
        connection.execute(
            "INSERT INTO play_campaign_transactional_transfers "
            "(campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, sequence, data["from_character_id"], data["to_character_id"],
             data["amount"], from_gold, to_gold),
        )

    return jsonify(
        from_character_id=data["from_character_id"],
        to_character_id=data["to_character_id"],
        amount=data["amount"],
        from_gold=from_gold,
        to_gold=to_gold,
        sequence=sequence,
    ), 201


@app.get("/v1/play/campaigns/<campaign_id>/transactional-transfers")
def read_play_campaign_transactional_transfers(campaign_id):
    """List committed transactional transfers for the DM or a campaign member."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        is_dm = actor[1] == "dm" and campaign[0] == actor[0]
        is_member = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone() is not None
        if not is_dm and not is_member:
            return jsonify(error="forbidden"), 403
        rows = connection.execute(
            "SELECT from_character_id, to_character_id, amount, from_gold, to_gold, sequence "
            "FROM play_campaign_transactional_transfers WHERE campaign_id = ? "
            "ORDER BY sequence",
            (campaign_id,),
        ).fetchall()

    return jsonify(transfers=[
        {
            "from_character_id": row[0], "to_character_id": row[1],
            "amount": row[2], "from_gold": row[3], "to_gold": row[4],
            "sequence": row[5],
        }
        for row in rows
    ])


def play_campaign_loot_access(connection, campaign_id, actor):
    """Check whether an actor is the campaign DM or one of its players."""
    campaign = connection.execute(
        "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if campaign is None:
        return None, (jsonify(error="unknown campaign"), 404)
    is_owner = actor[1] == "dm" and campaign[0] == actor[0]
    is_member = actor[1] == "player" and connection.execute(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        (campaign_id, actor[0]),
    ).fetchone() is not None
    if not is_owner and not is_member:
        return None, (jsonify(error="forbidden"), 403)
    return campaign[0], None


def play_campaign_npc_access(connection, campaign_id, actor):
    """Check whether an actor can view a campaign's NPC records."""
    campaign = connection.execute(
        "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if campaign is None:
        return None, (jsonify(error="unknown campaign"), 404)
    is_owner = actor[1] == "dm" and campaign[0] == actor[0]
    is_member = actor[1] == "player" and connection.execute(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        (campaign_id, actor[0]),
    ).fetchone() is not None
    if not is_owner and not is_member:
        return None, (jsonify(error="forbidden"), 403)
    return campaign[0], None


@app.post("/v1/play/campaigns/<campaign_id>/npcs")
def create_play_campaign_npc(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("npc_id", "name", "agenda", "public_status"))
    if data is None or not all(
            valid_nonblank_text(data[field])
            for field in ("npc_id", "name", "agenda", "public_status")):
        return jsonify(error="invalid npc"), 400

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
                "INSERT INTO play_campaign_npcs "
                "(campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, data["npc_id"], data["name"], data["agenda"],
                 data["public_status"]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="npc id already exists"), 409

    return jsonify(
        npc_id=data["npc_id"], name=data["name"], agenda=data["agenda"],
        public_status=data["public_status"],
    ), 201


@app.put("/v1/play/campaigns/<campaign_id>/npcs/<npc_id>/agenda")
def update_play_campaign_npc_agenda(campaign_id, npc_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("agenda", "public_status"))
    if data is None or not all(valid_nonblank_text(data[field])
                               for field in ("agenda", "public_status")):
        return jsonify(error="invalid npc agenda"), 400

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        npc = connection.execute(
            "SELECT name FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
        if npc is None:
            return jsonify(error="unknown npc"), 404
        connection.execute(
            "UPDATE play_campaign_npcs SET agenda = ?, public_status = ? "
            "WHERE campaign_id = ? AND npc_id = ?",
            (data["agenda"], data["public_status"], campaign_id, npc_id),
        )

    return jsonify(
        npc_id=npc_id, name=npc[0], agenda=data["agenda"],
        public_status=data["public_status"],
    )


@app.get("/v1/play/campaigns/<campaign_id>/npcs/<npc_id>")
def read_play_campaign_npc(campaign_id, npc_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        owner, error = play_campaign_npc_access(connection, campaign_id, actor)
        if error is not None:
            return error
        npc = connection.execute(
            "SELECT npc_id, name, agenda, public_status FROM play_campaign_npcs "
            "WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
    if npc is None:
        return jsonify(error="unknown npc"), 404
    if actor[1] == "dm" and owner == actor[0]:
        return jsonify(npc_id=npc[0], name=npc[1], agenda=npc[2], public_status=npc[3])
    return jsonify(npc_id=npc[0], name=npc[1], public_status=npc[3])


@app.post("/v1/play/campaigns/<campaign_id>/npcs/<npc_id>/dialogue")
def append_play_campaign_npc_dialogue(campaign_id, npc_id):
    """Append a DM-authored, attributed entry to an NPC's dialogue history."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("dialogue_id", "speaker", "text", "visibility"))
    if (data is None
            or not all(valid_nonblank_text(data[field])
                       for field in ("dialogue_id", "speaker", "text"))
            or data["visibility"] not in ("public", "private")):
        return jsonify(error="invalid dialogue"), 400

    try:
        with database_connection() as connection:
            campaign = connection.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return jsonify(error="unknown campaign"), 404
            if actor[1] != "dm" or campaign[0] != actor[0]:
                return jsonify(error="forbidden"), 403
            npc = connection.execute(
                "SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
                (campaign_id, npc_id),
            ).fetchone()
            if npc is None:
                return jsonify(error="unknown npc"), 404
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_npc_dialogue "
                "WHERE campaign_id = ? AND npc_id = ?",
                (campaign_id, npc_id),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_npc_dialogue "
                "(campaign_id, npc_id, sequence, dialogue_id, speaker, text, visibility) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (campaign_id, npc_id, sequence, data["dialogue_id"], data["speaker"],
                 data["text"], data["visibility"]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="dialogue id already exists"), 409

    return jsonify(
        dialogue_id=data["dialogue_id"], speaker=data["speaker"], text=data["text"],
        visibility=data["visibility"],
    ), 201


@app.get("/v1/play/campaigns/<campaign_id>/npcs/<npc_id>/dialogue")
def read_play_campaign_npc_dialogue(campaign_id, npc_id):
    """Read dialogue history, hiding private entries from campaign players."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        owner, error = play_campaign_npc_access(connection, campaign_id, actor)
        if error is not None:
            return error
        npc = connection.execute(
            "SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
        if npc is None:
            return jsonify(error="unknown npc"), 404
        is_owner = actor[1] == "dm" and owner == actor[0]
        query = (
            "SELECT dialogue_id, speaker, text, visibility "
            "FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ?"
        )
        parameters = [campaign_id, npc_id]
        if not is_owner:
            query += " AND visibility = ?"
            parameters.append("public")
        entries = connection.execute(query + " ORDER BY sequence", parameters).fetchall()

    return jsonify(npc_id=npc_id, entries=[
        {"dialogue_id": entry[0], "speaker": entry[1], "text": entry[2],
         "visibility": entry[3]}
        for entry in entries
    ])


def clue_response(clue_id, text, audience, character_id=None):
    clue = {"clue_id": clue_id, "text": text, "audience": audience}
    if audience == "character":
        clue["character_id"] = character_id
    return clue


@app.post("/v1/play/campaigns/<campaign_id>/clues")
def create_play_campaign_clue(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("clue_id", "text", "audience"))
    audience = None if data is None else data["audience"]
    has_character_id = data is not None and "character_id" in data
    if (data is None
            or not valid_nonblank_text(data["clue_id"])
            or not valid_nonblank_text(data["text"])
            or audience not in ("character", "party", "hidden")
            or (audience == "character" and
                (not has_character_id or not valid_nonblank_text(data["character_id"])))
            or (audience != "character" and has_character_id)):
        return jsonify(error="invalid clue"), 400

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
            character_id = data.get("character_id")
            if (audience == "character" and connection.execute(
                    "SELECT 1 FROM play_campaign_members "
                    "WHERE campaign_id = ? AND character_id = ?",
                    (campaign_id, character_id),
            ).fetchone() is None):
                return jsonify(error="unknown character"), 400
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_clues "
                "WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_clues "
                "(campaign_id, sequence, clue_id, text, audience, character_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, sequence, data["clue_id"], data["text"], audience, character_id),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="clue id already exists"), 409

    return jsonify(clue_response(
        data["clue_id"], data["text"], audience, data.get("character_id"),
    )), 201


@app.get("/v1/play/campaigns/<campaign_id>/clues")
def read_play_campaign_clues(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        owner, error = play_campaign_npc_access(connection, campaign_id, actor)
        if error is not None:
            return error
        is_owner = actor[1] == "dm" and owner == actor[0]
        query = (
            "SELECT clue_id, text, audience, character_id FROM play_campaign_clues "
            "WHERE campaign_id = ?"
        )
        parameters = [campaign_id]
        if not is_owner:
            character_id = connection.execute(
                "SELECT character_id FROM play_campaign_members "
                "WHERE campaign_id = ? AND username = ?",
                (campaign_id, actor[0]),
            ).fetchone()[0]
            query += " AND (audience = ? OR (audience = ? AND character_id = ?))"
            parameters.extend(("party", "character", character_id))
        clues = connection.execute(query + " ORDER BY sequence", parameters).fetchall()

    return jsonify(clues=[clue_response(*clue) for clue in clues])


def play_quest_response(quest_id, title, depends_on, state, rewards=None):
    response = {
        "quest_id": quest_id,
        "title": title,
        "depends_on": depends_on,
        "state": state,
    }
    if rewards is not None:
        response["rewards"] = rewards
    return response


def play_quest_dependencies(connection, campaign_id, quest_id):
    return [row[0] for row in connection.execute(
        "SELECT dependency_quest_id FROM play_campaign_quest_dependencies "
        "WHERE campaign_id = ? AND quest_id = ? ORDER BY position",
        (campaign_id, quest_id),
    )]


def play_quest_record(connection, campaign_id, quest_id):
    quest = connection.execute(
        "SELECT quest_id, title, state FROM play_campaign_quests "
        "WHERE campaign_id = ? AND quest_id = ?",
        (campaign_id, quest_id),
    ).fetchone()
    if quest is None:
        return None
    reward = connection.execute(
        "SELECT xp, items_json FROM play_campaign_quest_rewards "
        "WHERE campaign_id = ? AND quest_id = ?",
        (campaign_id, quest_id),
    ).fetchone()
    rewards = None if reward is None else {"xp": reward[0], "items": json.loads(reward[1])}
    return play_quest_response(
        quest[0], quest[1], play_quest_dependencies(connection, campaign_id, quest[0]),
        quest[2], rewards,
    )


def play_campaign_quest_owner(connection, campaign_id, actor):
    """Return an ownership error for a quest mutation, if any."""
    campaign = connection.execute(
        "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if campaign is None:
        return jsonify(error="unknown campaign"), 404
    if actor[1] != "dm" or campaign[0] != actor[0]:
        return jsonify(error="forbidden"), 403
    return None


@app.post("/v1/play/campaigns/<campaign_id>/quests")
def create_play_campaign_quest(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("quest_id", "title", "depends_on"))
    depends_on = None if data is None else data["depends_on"]
    if (data is None
            or not valid_nonblank_text(data["quest_id"])
            or not valid_nonblank_text(data["title"])
            or not isinstance(depends_on, list)
            or any(not valid_nonblank_text(dependency) for dependency in depends_on)
            or len(set(depends_on)) != len(depends_on)
            or data["quest_id"] in depends_on):
        return jsonify(error="invalid quest"), 400

    try:
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            error = play_campaign_quest_owner(connection, campaign_id, actor)
            if error is not None:
                return error
            if connection.execute(
                    "SELECT 1 FROM play_campaign_quests "
                    "WHERE campaign_id = ? AND quest_id = ?",
                    (campaign_id, data["quest_id"]),
            ).fetchone() is not None:
                return jsonify(error="quest id already exists"), 409
            existing_dependencies = {
                row[0] for row in connection.execute(
                    "SELECT quest_id FROM play_campaign_quests "
                    "WHERE campaign_id = ? AND quest_id IN ({})".format(
                        ", ".join("?" for _ in depends_on)
                    ),
                    [campaign_id, *depends_on],
                )
            } if depends_on else set()
            if len(existing_dependencies) != len(depends_on):
                return jsonify(error="invalid quest"), 400
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_quests "
                "WHERE campaign_id = ?", (campaign_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_quests "
                "(campaign_id, sequence, quest_id, title, state) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, sequence, data["quest_id"], data["title"], "locked"),
            )
            connection.executemany(
                "INSERT INTO play_campaign_quest_dependencies "
                "(campaign_id, quest_id, position, dependency_quest_id) VALUES (?, ?, ?, ?)",
                ((campaign_id, data["quest_id"], position, dependency)
                 for position, dependency in enumerate(depends_on)),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="quest id already exists"), 409

    return jsonify(play_quest_response(
        data["quest_id"], data["title"], depends_on, "locked",
    )), 201


@app.put("/v1/play/campaigns/<campaign_id>/quests/<quest_id>/state")
def update_play_campaign_quest_state(campaign_id, quest_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("state",))
    if data is None or data["state"] not in ("active", "completed"):
        return jsonify(error="invalid quest state"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        error = play_campaign_quest_owner(connection, campaign_id, actor)
        if error is not None:
            return error
        quest = connection.execute(
            "SELECT state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if quest is None:
            return jsonify(error="unknown quest"), 404
        if quest[0] == "locked" and data["state"] == "active":
            incomplete_dependency = connection.execute(
                "SELECT 1 FROM play_campaign_quest_dependencies AS dependencies "
                "JOIN play_campaign_quests AS prerequisite "
                "ON prerequisite.campaign_id = dependencies.campaign_id "
                "AND prerequisite.quest_id = dependencies.dependency_quest_id "
                "WHERE dependencies.campaign_id = ? AND dependencies.quest_id = ? "
                "AND prerequisite.state != 'completed' LIMIT 1",
                (campaign_id, quest_id),
            ).fetchone()
            if incomplete_dependency is not None:
                return jsonify(error="invalid quest transition"), 409
        elif not (quest[0] == "active" and data["state"] == "completed"):
            return jsonify(error="invalid quest transition"), 409
        connection.execute(
            "UPDATE play_campaign_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?",
            (data["state"], campaign_id, quest_id),
        )
        record = play_quest_record(connection, campaign_id, quest_id)

    return jsonify(record)


def valid_quest_rewards(data):
    """Validate the complete, finite reward parcel configured by a campaign DM."""
    if not isinstance(data, dict) or set(data) != {"xp", "items"}:
        return False
    return (
        type(data["xp"]) is int
        and data["xp"] >= 0
        and isinstance(data["items"], dict)
        and all(
            item_id in PLAY_INVENTORY_ITEM_IDS
            and type(quantity) is int
            and quantity > 0
            for item_id, quantity in data["items"].items()
        )
    )


@app.put("/v1/play/campaigns/<campaign_id>/quests/<quest_id>/rewards")
def configure_play_campaign_quest_rewards(campaign_id, quest_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = request.get_json(silent=True)
    if not valid_quest_rewards(data):
        return jsonify(error="invalid quest rewards"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        error = play_campaign_quest_owner(connection, campaign_id, actor)
        if error is not None:
            return error
        quest = connection.execute(
            "SELECT state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if quest is None:
            return jsonify(error="unknown quest"), 404
        if quest[0] not in ("locked", "active"):
            return jsonify(error="quest rewards cannot be configured"), 409
        connection.execute(
            "INSERT INTO play_campaign_quest_rewards "
            "(campaign_id, quest_id, xp, items_json) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, quest_id) DO UPDATE SET "
            "xp = excluded.xp, items_json = excluded.items_json "
            "WHERE awarded = 0",
            (campaign_id, quest_id, data["xp"], json.dumps(data["items"], separators=(",", ":"))),
        )
        # A completed quest cannot reach this route; this protects a future
        # state extension from silently replacing an already awarded parcel.
        if connection.execute(
                "SELECT awarded FROM play_campaign_quest_rewards "
                "WHERE campaign_id = ? AND quest_id = ?",
                (campaign_id, quest_id),
        ).fetchone()[0]:
            return jsonify(error="quest rewards already awarded"), 409
        record = play_quest_record(connection, campaign_id, quest_id)

    return jsonify(record)


@app.post("/v1/play/campaigns/<campaign_id>/quests/<quest_id>/rewards/award")
def award_play_campaign_quest_rewards(campaign_id, quest_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        error = play_campaign_quest_owner(connection, campaign_id, actor)
        if error is not None:
            return error
        quest = connection.execute(
            "SELECT state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if quest is None:
            return jsonify(error="unknown quest"), 404
        reward = connection.execute(
            "SELECT xp, items_json, awarded FROM play_campaign_quest_rewards "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if quest[0] != "completed" or reward is None:
            return jsonify(error="quest rewards cannot be awarded"), 409
        if reward[2]:
            return jsonify(error="quest rewards already awarded"), 409
        items = json.loads(reward[1])
        members = connection.execute(
            "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? "
            "ORDER BY character_id",
            (campaign_id,),
        ).fetchall()
        for (character_id,) in members:
            connection.execute(
                "INSERT INTO play_campaign_quest_reward_grants "
                "(campaign_id, quest_id, character_id, xp, items_json) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, quest_id, character_id, reward[0], reward[1]),
            )
            for item_id, quantity in items.items():
                connection.execute(
                    "INSERT INTO play_campaign_inventory_items "
                    "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET "
                    "quantity = quantity + excluded.quantity",
                    (campaign_id, character_id, item_id, quantity),
                )
        connection.execute(
            "UPDATE play_campaign_quest_rewards SET awarded = 1 "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        )

    return jsonify(quest_id=quest_id, awarded=True, xp=reward[0], items=items), 201


@app.get("/v1/play/campaigns/<campaign_id>/characters/<character_id>/rewards")
def read_play_campaign_character_quest_rewards(campaign_id, character_id):
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
        grants = connection.execute(
            "SELECT xp, items_json FROM play_campaign_quest_reward_grants "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY quest_id",
            (campaign_id, character_id),
        ).fetchall()

    items = {}
    for _, items_json in grants:
        for item_id, quantity in json.loads(items_json).items():
            items[item_id] = items.get(item_id, 0) + quantity
    return jsonify(character_id=character_id, xp=sum(grant[0] for grant in grants), items=items)


@app.get("/v1/play/campaigns/<campaign_id>/quests")
def read_play_campaign_quests(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        _, error = play_campaign_npc_access(connection, campaign_id, actor)
        if error is not None:
            return error
        quests = connection.execute(
            "SELECT quest_id, title, state FROM play_campaign_quests "
            "WHERE campaign_id = ? ORDER BY sequence", (campaign_id,),
        ).fetchall()
        dependencies = {}
        for dependency in connection.execute(
                "SELECT quest_id, dependency_quest_id FROM play_campaign_quest_dependencies "
                "WHERE campaign_id = ? ORDER BY quest_id, position", (campaign_id,)):
            dependencies.setdefault(dependency[0], []).append(dependency[1])
        rewards = {
            reward[0]: {"xp": reward[1], "items": json.loads(reward[2])}
            for reward in connection.execute(
                "SELECT quest_id, xp, items_json FROM play_campaign_quest_rewards "
                "WHERE campaign_id = ?", (campaign_id,)
            )
        }

    return jsonify(quests=[
        play_quest_response(
            quest[0], quest[1], dependencies.get(quest[0], []), quest[2],
            rewards.get(quest[0]),
        )
        for quest in quests
    ])


def world_event_response(event_id, turn_number, title, text, status,
                         resolution_turn_number=None, resolution_text=None):
    response = {
        "event_id": event_id,
        "turn_number": turn_number,
        "title": title,
        "text": text,
        "status": status,
    }
    if status == "resolved":
        response["resolution"] = {
            "turn_number": resolution_turn_number,
            "text": resolution_text,
        }
    return response


@app.post("/v1/play/campaigns/<campaign_id>/world-events")
def schedule_play_campaign_world_event(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("event_id", "turn_number", "title", "text"))
    if (data is None
            or not all(valid_nonblank_text(data[field]) for field in ("event_id", "title", "text"))
            or type(data["turn_number"]) is not int):
        return jsonify(error="invalid world event"), 400

    try:
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            campaign = connection.execute(
                "SELECT owner, turn_number FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return jsonify(error="unknown campaign"), 404
            if actor[1] != "dm" or campaign[0] != actor[0]:
                return jsonify(error="forbidden"), 403
            current_turn = campaign[1] or 0
            if data["turn_number"] < current_turn:
                return jsonify(error="invalid world event"), 400
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM play_campaign_world_events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_world_events "
                "(campaign_id, sequence, event_id, turn_number, title, text) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, sequence, data["event_id"], data["turn_number"],
                 data["title"], data["text"]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="world event id already exists"), 409

    return jsonify(world_event_response(
        data["event_id"], data["turn_number"], data["title"], data["text"], "scheduled",
    )), 201


@app.post("/v1/play/campaigns/<campaign_id>/world-events/<event_id>/resolve")
def resolve_play_campaign_world_event(campaign_id, event_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("text",))
    if data is None or not valid_nonblank_text(data["text"]):
        return jsonify(error="invalid world event resolution"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner, turn_number FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        event = connection.execute(
            "SELECT turn_number, title, text, status, resolution_turn_number, resolution_text "
            "FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if event is None:
            return jsonify(error="unknown world event"), 404
        if event[3] == "resolved" or campaign[1] != event[0]:
            return jsonify(error="world event cannot be resolved"), 409
        changed = connection.execute(
            "UPDATE play_campaign_world_events SET status = ?, resolution_turn_number = ?, "
            "resolution_text = ? WHERE campaign_id = ? AND event_id = ? AND status = ?",
            ("resolved", campaign[1], data["text"], campaign_id, event_id, "scheduled"),
        ).rowcount
        if changed != 1:
            return jsonify(error="world event cannot be resolved"), 409

    return jsonify(world_event_response(
        event_id, event[0], event[1], event[2], "resolved", campaign[1], data["text"],
    )), 201


@app.get("/v1/play/campaigns/<campaign_id>/world-events")
def read_play_campaign_world_events(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        _, error = play_campaign_npc_access(connection, campaign_id, actor)
        if error is not None:
            return error
        events = connection.execute(
            "SELECT event_id, turn_number, title, text, status, resolution_turn_number, "
            "resolution_text FROM play_campaign_world_events WHERE campaign_id = ? "
            "ORDER BY turn_number, sequence",
            (campaign_id,),
        ).fetchall()

    return jsonify(events=[world_event_response(*event) for event in events])


CALENDAR_SEASON_OFFSETS = {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}
CALENDAR_WEATHER = ("clear", "rain", "wind", "snow")


def calendar_response(day, season):
    """Build the public calendar representation with deterministic weather."""
    return {
        "day": day,
        "season": season,
        "weather": CALENDAR_WEATHER[(day + CALENDAR_SEASON_OFFSETS[season]) % 4],
    }


@app.post("/v1/play/campaigns/<campaign_id>/calendar")
def initialize_play_campaign_calendar(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("day", "season"))
    if (data is None
            or type(data["day"]) is not int
            or data["day"] < 1
            or data["season"] not in CALENDAR_SEASON_OFFSETS):
        return jsonify(error="invalid calendar"), 400

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
                "INSERT INTO play_campaign_calendars (campaign_id, day, season) "
                "VALUES (?, ?, ?)",
                (campaign_id, data["day"], data["season"]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="calendar already initialized"), 409

    return jsonify(calendar_response(data["day"], data["season"])), 201


@app.get("/v1/play/campaigns/<campaign_id>/calendar")
def read_play_campaign_calendar(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        _, error = play_campaign_loot_access(connection, campaign_id, actor)
        if error is not None:
            return error
        calendar = connection.execute(
            "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if calendar is None:
            return jsonify(error="calendar not initialized"), 404

    return jsonify(calendar_response(*calendar))


@app.post("/v1/play/campaigns/<campaign_id>/calendar/advance")
def advance_play_campaign_calendar(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("days",))
    if (data is None
            or type(data["days"]) is not int
            or not 1 <= data["days"] <= 30):
        return jsonify(error="invalid calendar advance"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        calendar = connection.execute(
            "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if calendar is None:
            return jsonify(error="calendar not initialized"), 404
        day = calendar[0] + data["days"]
        connection.execute(
            "UPDATE play_campaign_calendars SET day = ? WHERE campaign_id = ?",
            (day, campaign_id),
        )

    return jsonify(calendar_response(day, calendar[1]))


SETTLEMENT_AVAILABILITIES = frozenset(("open", "limited", "closed"))


def settlement_payload(required_fields):
    """Validate settlement input and normalize its ordered service names."""
    data = json_with_required_fields(required_fields)
    if data is None:
        return None
    if not all(valid_nonblank_text(data[field]) for field in required_fields
               if field in ("settlement_id", "name")):
        return None
    services = data.get("services")
    if not isinstance(services, list) or not services:
        return None
    normalized_services = []
    for service in services:
        if not isinstance(service, str) or not service.strip():
            return None
        normalized_services.append(service.strip())
    if len(set(normalized_services)) != len(normalized_services):
        return None
    if data.get("availability") not in SETTLEMENT_AVAILABILITIES:
        return None
    return data, normalized_services


def settlement_response(settlement, discovered_by):
    return {
        "settlement_id": settlement[0],
        "name": settlement[1],
        "services": json.loads(settlement[2]),
        "availability": settlement[3],
        "discovered_by": discovered_by,
    }


def settlement_discoverers(connection, campaign_id, settlement_id):
    return [row[0] for row in connection.execute(
        "SELECT character_id FROM play_campaign_settlement_discoveries "
        "WHERE campaign_id = ? AND settlement_id = ? ORDER BY sequence",
        (campaign_id, settlement_id),
    )]


@app.post("/v1/play/campaigns/<campaign_id>/settlements")
def create_play_campaign_settlement(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    payload = settlement_payload(("settlement_id", "name", "services", "availability"))
    if payload is None:
        return jsonify(error="invalid settlement"), 400
    data, services = payload

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
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_settlements "
                "WHERE campaign_id = ?", (campaign_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_settlements "
                "(campaign_id, sequence, settlement_id, name, services_json, availability) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, sequence, data["settlement_id"], data["name"],
                 json.dumps(services, separators=(",", ":")), data["availability"]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="settlement id already exists"), 409

    return jsonify({
        "settlement_id": data["settlement_id"], "name": data["name"],
        "services": services, "availability": data["availability"], "discovered_by": [],
    }), 201


@app.put("/v1/play/campaigns/<campaign_id>/settlements/<settlement_id>")
def update_play_campaign_settlement(campaign_id, settlement_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    payload = settlement_payload(("name", "services", "availability"))
    if payload is None:
        return jsonify(error="invalid settlement"), 400
    data, services = payload

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        settlement = connection.execute(
            "SELECT settlement_id, name, services_json, availability "
            "FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?",
            (campaign_id, settlement_id),
        ).fetchone()
        if settlement is None:
            return jsonify(error="unknown settlement"), 404
        connection.execute(
            "UPDATE play_campaign_settlements SET name = ?, services_json = ?, availability = ? "
            "WHERE campaign_id = ? AND settlement_id = ?",
            (data["name"], json.dumps(services, separators=(",", ":")),
             data["availability"], campaign_id, settlement_id),
        )
        discoverers = settlement_discoverers(connection, campaign_id, settlement_id)

    return jsonify({
        "settlement_id": settlement_id, "name": data["name"], "services": services,
        "availability": data["availability"], "discovered_by": discoverers,
    })


@app.post("/v1/play/campaigns/<campaign_id>/settlements/<settlement_id>/discover")
def discover_play_campaign_settlement(campaign_id, settlement_id):
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
        if actor[1] != "player":
            return jsonify(error="forbidden"), 403
        member = connection.execute(
            "SELECT character_id FROM play_campaign_members "
            "WHERE campaign_id = ? AND username = ?", (campaign_id, actor[0]),
        ).fetchone()
        if member is None:
            return jsonify(error="forbidden"), 403
        settlement = connection.execute(
            "SELECT settlement_id, name, services_json, availability "
            "FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?",
            (campaign_id, settlement_id),
        ).fetchone()
        if settlement is None:
            return jsonify(error="unknown settlement"), 404
        character_id = member[0]
        already_discovered = connection.execute(
            "SELECT 1 FROM play_campaign_settlement_discoveries "
            "WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?",
            (campaign_id, settlement_id, character_id),
        ).fetchone() is not None
        if not already_discovered:
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM play_campaign_settlement_discoveries "
                "WHERE campaign_id = ? AND settlement_id = ?",
                (campaign_id, settlement_id),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_settlement_discoveries "
                "(campaign_id, settlement_id, character_id, sequence) VALUES (?, ?, ?, ?)",
                (campaign_id, settlement_id, character_id, sequence),
            )

    return jsonify(settlement_response(settlement, [character_id])), 200 if already_discovered else 201


@app.get("/v1/play/campaigns/<campaign_id>/settlements")
def read_play_campaign_settlements(campaign_id):
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
        member = None
        if actor[1] == "player":
            member = connection.execute(
                "SELECT character_id FROM play_campaign_members "
                "WHERE campaign_id = ? AND username = ?", (campaign_id, actor[0]),
            ).fetchone()
        if not is_owner and member is None:
            return jsonify(error="forbidden"), 403
        settlements = connection.execute(
            "SELECT settlement_id, name, services_json, availability "
            "FROM play_campaign_settlements WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()
        if is_owner:
            responses = [settlement_response(
                settlement, settlement_discoverers(connection, campaign_id, settlement[0])
            ) for settlement in settlements]
        else:
            character_id = member[0]
            responses = [settlement_response(settlement, [character_id]) for settlement in settlements
                         if connection.execute(
                             "SELECT 1 FROM play_campaign_settlement_discoveries "
                             "WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?",
                             (campaign_id, settlement[0], character_id),
                         ).fetchone() is not None]

    return jsonify(settlements=responses)


def shop_payload():
    """Validate the complete, catalog-backed definition of a settlement shop."""
    data = json_with_required_fields(("shop_id", "name", "stock", "buy_price", "sell_price"))
    if (data is None
            or not valid_nonblank_text(data["shop_id"])
            or not valid_nonblank_text(data["name"])
            or not isinstance(data["stock"], dict)
            or not data["stock"]
            or type(data["buy_price"]) is not int or data["buy_price"] <= 0
            or type(data["sell_price"]) is not int or data["sell_price"] < 0):
        return None
    if any(item_id not in PLAY_INVENTORY_ITEM_IDS
           or type(quantity) is not int or quantity <= 0
           for item_id, quantity in data["stock"].items()):
        return None
    return data


def shop_response(connection, campaign_id, settlement_id, shop):
    """Serialize a shop without exposing database-only campaign metadata."""
    stock = dict(connection.execute(
        "SELECT item_id, quantity FROM play_campaign_shop_stock "
        "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? ORDER BY item_id",
        (campaign_id, settlement_id, shop[0]),
    ).fetchall())
    return {
        "shop_id": shop[0], "name": shop[1], "stock": stock,
        "buy_price": shop[2], "sell_price": shop[3],
    }


@app.post("/v1/play/campaigns/<campaign_id>/settlements/<settlement_id>/shops")
def create_play_campaign_shop(campaign_id, settlement_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    data = shop_payload()
    if data is None:
        return jsonify(error="invalid shop"), 400

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
            settlement = connection.execute(
                "SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?",
                (campaign_id, settlement_id),
            ).fetchone()
            if settlement is None:
                return jsonify(error="unknown settlement"), 404
            connection.execute(
                "INSERT INTO play_campaign_shops "
                "(campaign_id, settlement_id, shop_id, name, buy_price, sell_price) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, settlement_id, data["shop_id"], data["name"],
                 data["buy_price"], data["sell_price"]),
            )
            connection.executemany(
                "INSERT INTO play_campaign_shop_stock "
                "(campaign_id, settlement_id, shop_id, item_id, quantity) VALUES (?, ?, ?, ?, ?)",
                [(campaign_id, settlement_id, data["shop_id"], item_id, quantity)
                 for item_id, quantity in data["stock"].items()],
            )
    except sqlite3.IntegrityError:
        return jsonify(error="shop id already exists"), 409
    return jsonify({
        "shop_id": data["shop_id"], "name": data["name"], "stock": data["stock"],
        "buy_price": data["buy_price"], "sell_price": data["sell_price"],
    }), 201


@app.get("/v1/play/campaigns/<campaign_id>/settlements/<settlement_id>/shops/<shop_id>")
def read_play_campaign_shop(campaign_id, settlement_id, shop_id):
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
        member = None if is_owner else connection.execute(
            "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone()
        if not is_owner and member is None:
            return jsonify(error="forbidden"), 403
        settlement = connection.execute(
            "SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?",
            (campaign_id, settlement_id),
        ).fetchone()
        if settlement is None:
            return jsonify(error="unknown settlement"), 404
        if not is_owner and connection.execute(
                "SELECT 1 FROM play_campaign_settlement_discoveries "
                "WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?",
                (campaign_id, settlement_id, member[0]),
        ).fetchone() is None:
            return jsonify(error="unknown shop"), 404
        shop = connection.execute(
            "SELECT shop_id, name, buy_price, sell_price FROM play_campaign_shops "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (campaign_id, settlement_id, shop_id),
        ).fetchone()
        if shop is None:
            return jsonify(error="unknown shop"), 404
        response = shop_response(connection, campaign_id, settlement_id, shop)
    return jsonify(response)


def trade_with_play_campaign_shop(campaign_id, settlement_id, shop_id, selling):
    """Execute one all-or-nothing player/shop inventory and gold exchange."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    data = json_with_required_fields(("character_id", "item_id", "quantity"))
    if (data is None or not valid_nonblank_text(data["character_id"])
            or data["item_id"] not in PLAY_INVENTORY_ITEM_IDS
            or type(data["quantity"]) is not int or data["quantity"] <= 0):
        return jsonify(error="invalid shop trade"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "player":
            return jsonify(error="forbidden"), 403
        settlement = connection.execute(
            "SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?",
            (campaign_id, settlement_id),
        ).fetchone()
        if settlement is None:
            return jsonify(error="unknown settlement"), 404
        shop = connection.execute(
            "SELECT buy_price, sell_price FROM play_campaign_shops "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (campaign_id, settlement_id, shop_id),
        ).fetchone()
        if shop is None:
            return jsonify(error="unknown shop"), 404
        character = connection.execute(
            "SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, data["character_id"]),
        ).fetchone()
        if character is None:
            return jsonify(error="unknown character"), 404
        if character[0] != actor[0]:
            return jsonify(error="forbidden"), 403

        stock_row = connection.execute(
            "SELECT quantity FROM play_campaign_shop_stock "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? AND item_id = ?",
            (campaign_id, settlement_id, shop_id, data["item_id"]),
        ).fetchone()
        stock = 0 if stock_row is None else stock_row[0]
        quantity = data["quantity"]
        if selling:
            held_row = connection.execute(
                "SELECT quantity FROM play_campaign_inventory_items "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, data["character_id"], data["item_id"]),
            ).fetchone()
            held = 0 if held_row is None else held_row[0]
            if held < quantity:
                return jsonify(error="insufficient held quantity"), 409
            remaining = held - quantity
            if remaining == 0:
                connection.execute(
                    "DELETE FROM play_campaign_inventory_items "
                    "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (campaign_id, data["character_id"], data["item_id"]),
                )
            else:
                connection.execute(
                    "UPDATE play_campaign_inventory_items SET quantity = ? "
                    "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (remaining, campaign_id, data["character_id"], data["item_id"]),
                )
            gold_change = shop[1] * quantity
            connection.execute(
                "UPDATE play_campaign_currency SET gold = gold + ? "
                "WHERE campaign_id = ? AND character_id = ?",
                (gold_change, campaign_id, data["character_id"]),
            )
            if stock_row is None:
                connection.execute(
                    "INSERT INTO play_campaign_shop_stock "
                    "(campaign_id, settlement_id, shop_id, item_id, quantity) VALUES (?, ?, ?, ?, ?)",
                    (campaign_id, settlement_id, shop_id, data["item_id"], quantity),
                )
            else:
                connection.execute(
                    "UPDATE play_campaign_shop_stock SET quantity = ? "
                    "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? AND item_id = ?",
                    (stock + quantity, campaign_id, settlement_id, shop_id, data["item_id"]),
                )
            new_stock = stock + quantity
        else:
            cost = shop[0] * quantity
            gold_row = connection.execute(
                "SELECT gold FROM play_campaign_currency WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, data["character_id"]),
            ).fetchone()
            if stock < quantity:
                return jsonify(error="insufficient stock"), 409
            if gold_row is None or gold_row[0] < cost:
                return jsonify(error="insufficient gold"), 409
            new_stock = stock - quantity
            connection.execute(
                "UPDATE play_campaign_shop_stock SET quantity = ? "
                "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? AND item_id = ?",
                (new_stock, campaign_id, settlement_id, shop_id, data["item_id"]),
            )
            connection.execute(
                "UPDATE play_campaign_currency SET gold = gold - ? "
                "WHERE campaign_id = ? AND character_id = ?",
                (cost, campaign_id, data["character_id"]),
            )
            connection.execute(
                "INSERT INTO play_campaign_inventory_items "
                "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET "
                "quantity = quantity + excluded.quantity",
                (campaign_id, data["character_id"], data["item_id"], quantity),
            )
        gold = connection.execute(
            "SELECT gold FROM play_campaign_currency WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, data["character_id"]),
        ).fetchone()[0]

    return jsonify(character_id=data["character_id"], item_id=data["item_id"],
                   quantity=quantity, gold=gold, stock=new_stock)


@app.post("/v1/play/campaigns/<campaign_id>/settlements/<settlement_id>/shops/<shop_id>/buy")
def buy_from_play_campaign_shop(campaign_id, settlement_id, shop_id):
    return trade_with_play_campaign_shop(campaign_id, settlement_id, shop_id, selling=False)


@app.post("/v1/play/campaigns/<campaign_id>/settlements/<settlement_id>/shops/<shop_id>/sell")
def sell_to_play_campaign_shop(campaign_id, settlement_id, shop_id):
    return trade_with_play_campaign_shop(campaign_id, settlement_id, shop_id, selling=True)


def downtime_activity_response(activity_id, name, cycles_required):
    return {
        "activity_id": activity_id,
        "name": name,
        "cycles_required": cycles_required,
    }


def downtime_allocation_response(character_id, activity_id, cycles_completed, completions):
    return {
        "character_id": character_id,
        "activity_id": activity_id,
        "cycles_completed": cycles_completed,
        "completions": completions,
    }


@app.post("/v1/play/campaigns/<campaign_id>/downtime/activities")
def create_play_campaign_downtime_activity(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    data = json_with_required_fields(("activity_id", "name", "cycles_required"))
    if (data is None
            or not valid_nonblank_text(data["activity_id"])
            or not valid_nonblank_text(data["name"])
            or not valid_int(data["cycles_required"], 1, 10)):
        return jsonify(error="invalid downtime activity"), 400

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
                "INSERT INTO play_campaign_downtime_activities "
                "(campaign_id, activity_id, name, cycles_required) VALUES (?, ?, ?, ?)",
                (campaign_id, data["activity_id"], data["name"], data["cycles_required"]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="activity id already exists"), 409

    return jsonify(downtime_activity_response(
        data["activity_id"], data["name"], data["cycles_required"],
    )), 201


@app.post("/v1/play/campaigns/<campaign_id>/characters/<character_id>/downtime/allocations")
def allocate_play_campaign_downtime(campaign_id, character_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    data = json_with_required_fields(("activity_id",))
    if data is None or not valid_nonblank_text(data["activity_id"]):
        return jsonify(error="invalid downtime allocation"), 400

    try:
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            campaign = connection.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return jsonify(error="unknown campaign"), 404
            if actor[1] != "player":
                return jsonify(error="forbidden"), 403
            character = connection.execute(
                "SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if character is None:
                return jsonify(error="unknown character"), 404
            activity = connection.execute(
                "SELECT 1 FROM play_campaign_downtime_activities "
                "WHERE campaign_id = ? AND activity_id = ?",
                (campaign_id, data["activity_id"]),
            ).fetchone()
            if activity is None:
                return jsonify(error="unknown activity"), 404
            if character[0] != actor[0]:
                return jsonify(error="forbidden"), 403
            connection.execute(
                "INSERT INTO play_campaign_downtime_allocations "
                "(campaign_id, character_id, activity_id) VALUES (?, ?, ?)",
                (campaign_id, character_id, data["activity_id"]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="downtime allocation already exists"), 409

    return jsonify(downtime_allocation_response(
        character_id, data["activity_id"], 0, 0,
    )), 201


@app.post("/v1/play/campaigns/<campaign_id>/characters/<character_id>/downtime/allocations/<activity_id>/progress")
def progress_play_campaign_downtime(campaign_id, character_id, activity_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "player":
            return jsonify(error="forbidden"), 403
        character = connection.execute(
            "SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return jsonify(error="unknown character"), 404
        activity = connection.execute(
            "SELECT cycles_required FROM play_campaign_downtime_activities "
            "WHERE campaign_id = ? AND activity_id = ?",
            (campaign_id, activity_id),
        ).fetchone()
        if activity is None:
            return jsonify(error="unknown activity"), 404
        if character[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        allocation = connection.execute(
            "SELECT cycles_completed, completions FROM play_campaign_downtime_allocations "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (campaign_id, character_id, activity_id),
        ).fetchone()
        if allocation is None:
            return jsonify(error="unknown downtime allocation"), 404

        cycles_completed = allocation[0] + 1
        completions = allocation[1]
        if cycles_completed == activity[0]:
            cycles_completed = 0
            completions += 1
        connection.execute(
            "UPDATE play_campaign_downtime_allocations "
            "SET cycles_completed = ?, completions = ? "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (cycles_completed, completions, campaign_id, character_id, activity_id),
        )

    return jsonify(downtime_allocation_response(
        character_id, activity_id, cycles_completed, completions,
    ))


@app.get("/v1/play/campaigns/<campaign_id>/characters/<character_id>/downtime/allocations/<activity_id>")
def read_play_campaign_downtime_allocation(campaign_id, character_id, activity_id):
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
        character = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return jsonify(error="unknown character"), 404
        activity = connection.execute(
            "SELECT 1 FROM play_campaign_downtime_activities "
            "WHERE campaign_id = ? AND activity_id = ?",
            (campaign_id, activity_id),
        ).fetchone()
        if activity is None:
            return jsonify(error="unknown activity"), 404
        allocation = connection.execute(
            "SELECT cycles_completed, completions FROM play_campaign_downtime_allocations "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (campaign_id, character_id, activity_id),
        ).fetchone()
        if allocation is None:
            return jsonify(error="unknown downtime allocation"), 404

    return jsonify(downtime_allocation_response(
        character_id, activity_id, allocation[0], allocation[1],
    ))


def recipe_payload():
    """Validate a catalog-backed recipe definition."""
    data = json_with_required_fields(
        ("recipe_id", "name", "ingredients", "output_item", "output_quantity")
    )
    if (data is None
            or not valid_nonblank_text(data["recipe_id"])
            or not valid_nonblank_text(data["name"])
            or not isinstance(data["ingredients"], dict)
            or not data["ingredients"]
            or not isinstance(data["output_item"], str)
            or data["output_item"] not in PLAY_INVENTORY_ITEM_IDS
            or type(data["output_quantity"]) is not int
            or data["output_quantity"] <= 0):
        return None
    if any(item_id not in PLAY_INVENTORY_ITEM_IDS
           or type(quantity) is not int or quantity <= 0
           for item_id, quantity in data["ingredients"].items()):
        return None
    return data


def recipe_response(recipe):
    """Serialize one recipe in its public, stable shape."""
    return {
        "recipe_id": recipe[0],
        "name": recipe[1],
        "ingredients": json.loads(recipe[2]),
        "output_item": recipe[3],
        "output_quantity": recipe[4],
    }


@app.post("/v1/play/campaigns/<campaign_id>/recipes")
def create_play_campaign_recipe(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    data = recipe_payload()
    if data is None:
        return jsonify(error="invalid recipe"), 400

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
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_recipes "
                "WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_recipes "
                "(campaign_id, recipe_id, sequence, name, ingredients_json, output_item, output_quantity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (campaign_id, data["recipe_id"], sequence, data["name"],
                 json.dumps(data["ingredients"], separators=(",", ":")),
                 data["output_item"], data["output_quantity"]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="recipe id already exists"), 409

    return jsonify({
        "recipe_id": data["recipe_id"], "name": data["name"],
        "ingredients": data["ingredients"], "output_item": data["output_item"],
        "output_quantity": data["output_quantity"],
    }), 201


@app.get("/v1/play/campaigns/<campaign_id>/recipes")
def read_play_campaign_recipes(campaign_id):
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
        recipes = connection.execute(
            "SELECT recipe_id, name, ingredients_json, output_item, output_quantity "
            "FROM play_campaign_recipes WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()

    return jsonify(recipes=[recipe_response(recipe) for recipe in recipes])


@app.post("/v1/play/campaigns/<campaign_id>/recipes/<recipe_id>/craft")
def craft_play_campaign_recipe(campaign_id, recipe_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    data = json_with_required_fields(("character_id",))
    if data is None or not valid_nonblank_text(data["character_id"]):
        return jsonify(error="invalid craft request"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "player":
            return jsonify(error="forbidden"), 403
        recipe = connection.execute(
            "SELECT recipe_id, name, ingredients_json, output_item, output_quantity "
            "FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?",
            (campaign_id, recipe_id),
        ).fetchone()
        if recipe is None:
            return jsonify(error="unknown recipe"), 404
        character = connection.execute(
            "SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, data["character_id"]),
        ).fetchone()
        if character is None:
            return jsonify(error="unknown character"), 404
        if character[0] != actor[0]:
            return jsonify(error="forbidden"), 403

        ingredients = json.loads(recipe[2])
        for item_id, required_quantity in ingredients.items():
            stack = connection.execute(
                "SELECT quantity FROM play_campaign_inventory_items "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, data["character_id"], item_id),
            ).fetchone()
            if stack is None or stack[0] < required_quantity:
                return jsonify(error="insufficient ingredients"), 409

        for item_id, required_quantity in ingredients.items():
            remaining = connection.execute(
                "SELECT quantity FROM play_campaign_inventory_items "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, data["character_id"], item_id),
            ).fetchone()[0] - required_quantity
            if remaining == 0:
                connection.execute(
                    "DELETE FROM play_campaign_inventory_items "
                    "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (campaign_id, data["character_id"], item_id),
                )
            else:
                connection.execute(
                    "UPDATE play_campaign_inventory_items SET quantity = ? "
                    "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (remaining, campaign_id, data["character_id"], item_id),
                )
        connection.execute(
            "INSERT INTO play_campaign_inventory_items "
            "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET "
            "quantity = quantity + excluded.quantity",
            (campaign_id, data["character_id"], recipe[3], recipe[4]),
        )

    return jsonify(
        character_id=data["character_id"], recipe_id=recipe_id,
        output_item=recipe[3], output_quantity=recipe[4],
    ), 201


def play_campaign_entity_exists(connection, campaign_id, entity_id):
    """Whether an ID belongs to a member character or NPC in this campaign."""
    return connection.execute(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? "
        "UNION ALL "
        "SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ? "
        "LIMIT 1",
        (campaign_id, entity_id, campaign_id, entity_id),
    ).fetchone() is not None


def relationship_response(source_id, target_id, kind, score):
    return {
        "source_id": source_id,
        "target_id": target_id,
        "kind": kind,
        "score": score,
    }


@app.post("/v1/play/campaigns/<campaign_id>/relationships")
def create_play_campaign_relationship(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("source_id", "target_id", "kind", "score"))
    if (data is None
            or not all(valid_nonblank_text(data[field])
                       for field in ("source_id", "target_id", "kind"))
            or data["source_id"] == data["target_id"]
            or not valid_int(data["score"], -100, 100)):
        return jsonify(error="invalid relationship"), 400

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
            if not play_campaign_entity_exists(connection, campaign_id, data["source_id"]):
                return jsonify(error="unknown campaign entity"), 404
            if not play_campaign_entity_exists(connection, campaign_id, data["target_id"]):
                return jsonify(error="unknown campaign entity"), 404
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM play_campaign_relationships WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_relationships "
                "(campaign_id, sequence, source_id, target_id, kind, score) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, sequence, data["source_id"], data["target_id"],
                 data["kind"], data["score"]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="relationship already exists"), 409

    return jsonify(relationship_response(
        data["source_id"], data["target_id"], data["kind"], data["score"],
    )), 201


@app.put("/v1/play/campaigns/<campaign_id>/relationships/<source_id>/<target_id>/<kind>")
def update_play_campaign_relationship(campaign_id, source_id, target_id, kind):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("score",))
    if data is None or not valid_int(data["score"], -100, 100):
        return jsonify(error="invalid relationship"), 400

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        updated = connection.execute(
            "UPDATE play_campaign_relationships SET score = ? "
            "WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
            (data["score"], campaign_id, source_id, target_id, kind),
        ).rowcount
        if updated != 1:
            return jsonify(error="unknown relationship"), 404

    return jsonify(relationship_response(source_id, target_id, kind, data["score"]))


@app.get("/v1/play/campaigns/<campaign_id>/relationships")
def read_play_campaign_relationships(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        _, error = play_campaign_npc_access(connection, campaign_id, actor)
        if error is not None:
            return error
        edges = connection.execute(
            "SELECT source_id, target_id, kind, score "
            "FROM play_campaign_relationships WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()

    return jsonify(edges=[relationship_response(*edge) for edge in edges])


def play_campaign_faction_access(connection, campaign_id, actor):
    """Check faction-history visibility and identify the campaign owner."""
    campaign = connection.execute(
        "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if campaign is None:
        return None, (jsonify(error="unknown campaign"), 404)
    is_owner = actor[1] == "dm" and campaign[0] == actor[0]
    is_member = actor[1] == "player" and connection.execute(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        (campaign_id, actor[0]),
    ).fetchone() is not None
    if not is_owner and not is_member:
        return None, (jsonify(error="forbidden"), 403)
    return campaign[0], None


@app.post("/v1/play/campaigns/<campaign_id>/factions")
def create_play_campaign_faction(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("faction_id", "name"))
    if data is None or not all(valid_nonblank_text(data[field])
                               for field in ("faction_id", "name")):
        return jsonify(error="invalid faction"), 400

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
                "INSERT INTO play_campaign_factions (campaign_id, faction_id, name) "
                "VALUES (?, ?, ?)",
                (campaign_id, data["faction_id"], data["name"]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="faction id already exists"), 409

    return jsonify(faction_id=data["faction_id"], name=data["name"]), 201


@app.post("/v1/play/campaigns/<campaign_id>/factions/<faction_id>/reputation")
def change_play_campaign_faction_reputation(campaign_id, faction_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("character_id", "delta", "reason"))
    if (data is None
            or not valid_nonblank_text(data["character_id"])
            or not valid_int(data["delta"], -25, 25)
            or data["delta"] == 0
            or not valid_nonblank_text(data["reason"])):
        return jsonify(error="invalid reputation change"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        faction = connection.execute(
            "SELECT 1 FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?",
            (campaign_id, faction_id),
        ).fetchone()
        if faction is None:
            return jsonify(error="unknown faction"), 404
        character = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, data["character_id"]),
        ).fetchone()
        if character is None:
            return jsonify(error="unknown character"), 400
        prior = connection.execute(
            "SELECT reputation FROM play_campaign_faction_reputation_history "
            "WHERE campaign_id = ? AND faction_id = ? AND character_id = ? "
            "ORDER BY sequence DESC LIMIT 1",
            (campaign_id, faction_id, data["character_id"]),
        ).fetchone()
        reputation = max(-100, min(100, (prior[0] if prior else 0) + data["delta"]))
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 "
            "FROM play_campaign_faction_reputation_history WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_faction_reputation_history "
            "(campaign_id, sequence, faction_id, character_id, reputation, delta, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, sequence, faction_id, data["character_id"], reputation,
             data["delta"], data["reason"]),
        )

    return jsonify(
        faction_id=faction_id, character_id=data["character_id"], reputation=reputation,
        delta=data["delta"], reason=data["reason"],
    ), 201


@app.get("/v1/play/campaigns/<campaign_id>/factions/<faction_id>/reputation")
def read_play_campaign_faction_reputation(campaign_id, faction_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        owner, error = play_campaign_faction_access(connection, campaign_id, actor)
        if error is not None:
            return error
        faction = connection.execute(
            "SELECT 1 FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?",
            (campaign_id, faction_id),
        ).fetchone()
        if faction is None:
            return jsonify(error="unknown faction"), 404
        query = (
            "SELECT faction_id, character_id, reputation, delta, reason "
            "FROM play_campaign_faction_reputation_history "
            "WHERE campaign_id = ? AND faction_id = ?"
        )
        parameters = [campaign_id, faction_id]
        if not (actor[1] == "dm" and owner == actor[0]):
            query += (
                " AND character_id IN (SELECT character_id FROM play_campaign_members "
                "WHERE campaign_id = ? AND owner = ?)"
            )
            parameters.extend((campaign_id, actor[0]))
        query += " ORDER BY sequence"
        entries = connection.execute(query, parameters).fetchall()

    return jsonify(
        faction_id=faction_id,
        entries=[
            {"faction_id": row[0], "character_id": row[1], "reputation": row[2],
             "delta": row[3], "reason": row[4]}
            for row in entries
        ],
    )


@app.post("/v1/play/campaigns/<campaign_id>/loot")
def create_play_campaign_loot(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("loot_id", "item_id", "quantity"))
    if (data is None
            or not valid_nonblank_text(data["loot_id"])
            or data["item_id"] not in PLAY_INVENTORY_ITEM_IDS
            or type(data["quantity"]) is not int
            or data["quantity"] <= 0):
        return jsonify(error="invalid loot"), 400

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
                "INSERT INTO play_campaign_loot "
                "(campaign_id, loot_id, item_id, quantity, status) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, data["loot_id"], data["item_id"], data["quantity"], "open"),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="loot id already exists"), 409

    return jsonify(
        loot_id=data["loot_id"], item_id=data["item_id"], quantity=data["quantity"], status="open",
    ), 201


@app.post("/v1/play/campaigns/<campaign_id>/loot/<loot_id>/votes")
def vote_on_play_campaign_loot(campaign_id, loot_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("recipient_character_id",))
    if data is None or not valid_nonblank_text(data["recipient_character_id"]):
        return jsonify(error="invalid loot vote"), 400

    try:
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _, error = play_campaign_loot_access(connection, campaign_id, actor)
            if error is not None:
                return error
            if actor[1] != "player":
                return jsonify(error="forbidden"), 403
            loot = connection.execute(
                "SELECT status FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?",
                (campaign_id, loot_id),
            ).fetchone()
            if loot is None:
                return jsonify(error="unknown loot"), 404
            if loot[0] != "open":
                return jsonify(error="loot is already assigned"), 409
            recipient = connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, data["recipient_character_id"]),
            ).fetchone()
            if recipient is None:
                return jsonify(error="invalid loot vote"), 400
            connection.execute(
                "INSERT INTO play_campaign_loot_votes "
                "(campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)",
                (campaign_id, loot_id, actor[0], data["recipient_character_id"]),
            )
            votes_for_recipient = connection.execute(
                "SELECT COUNT(*) FROM play_campaign_loot_votes "
                "WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?",
                (campaign_id, loot_id, data["recipient_character_id"]),
            ).fetchone()[0]
    except sqlite3.IntegrityError:
        return jsonify(error="loot vote already exists"), 409

    return jsonify(
        loot_id=loot_id,
        voter=actor[0],
        recipient_character_id=data["recipient_character_id"],
        votes_for_recipient=votes_for_recipient,
    ), 201


@app.post("/v1/play/campaigns/<campaign_id>/loot/<loot_id>/assign")
def assign_play_campaign_loot(campaign_id, loot_id):
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
        loot = connection.execute(
            "SELECT item_id, quantity, status FROM play_campaign_loot "
            "WHERE campaign_id = ? AND loot_id = ?",
            (campaign_id, loot_id),
        ).fetchone()
        if loot is None:
            return jsonify(error="unknown loot"), 404
        if loot[2] != "open":
            return jsonify(error="loot is already assigned"), 409
        leaders = connection.execute(
            "SELECT recipient_character_id, COUNT(*) AS vote_count "
            "FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? "
            "GROUP BY recipient_character_id ORDER BY vote_count DESC, recipient_character_id",
            (campaign_id, loot_id),
        ).fetchall()
        if not leaders or (len(leaders) > 1 and leaders[0][1] == leaders[1][1]):
            return jsonify(error="loot has no unambiguous recipient"), 409

        recipient_character_id, votes = leaders[0]
        connection.execute(
            "INSERT INTO play_campaign_inventory_items "
            "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET "
            "quantity = quantity + excluded.quantity",
            (campaign_id, recipient_character_id, loot[0], loot[1]),
        )
        connection.execute(
            "UPDATE play_campaign_loot SET status = ?, recipient_character_id = ?, votes = ? "
            "WHERE campaign_id = ? AND loot_id = ?",
            ("assigned", recipient_character_id, votes, campaign_id, loot_id),
        )

    return jsonify(
        loot_id=loot_id,
        recipient_character_id=recipient_character_id,
        item_id=loot[0],
        quantity=loot[1],
        votes=votes,
        status="assigned",
    )


@app.get("/v1/play/campaigns/<campaign_id>/loot/<loot_id>")
def read_play_campaign_loot(campaign_id, loot_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        _, error = play_campaign_loot_access(connection, campaign_id, actor)
        if error is not None:
            return error
        loot = connection.execute(
            "SELECT loot_id, item_id, quantity, status, recipient_character_id "
            "FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?",
            (campaign_id, loot_id),
        ).fetchone()
        if loot is None:
            return jsonify(error="unknown loot"), 404
        vote_rows = connection.execute(
            "SELECT recipient_character_id, COUNT(*) "
            "FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? "
            "GROUP BY recipient_character_id ORDER BY recipient_character_id",
            (campaign_id, loot_id),
        ).fetchall()

    return jsonify(
        loot_id=loot[0],
        item_id=loot[1],
        quantity=loot[2],
        status=loot[3],
        recipient_character_id=loot[4],
        votes={recipient_character_id: vote_count
               for recipient_character_id, vote_count in vote_rows},
    )


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


def spell_slot_capacity(character_class, character_level, spell_level):
    """Return the supported spell-slot count for one spell level.

    The play API currently supports wizard spellbooks.  Its deliberately small
    ruleset gives a first-level wizard one first-level slot.
    """
    if character_class == "wizard" and character_level == 1 and spell_level == 1:
        return 1
    return 0


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


@app.post("/v1/play/campaigns/<campaign_id>/characters/<character_id>/casts")
def cast_play_campaign_character_spell(campaign_id, character_id):
    """Spend a prepared wizard spell slot and append the resulting cast event."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("spell_id", "target"))
    if (data is None
            or not valid_nonblank_text(data["spell_id"])
            or not valid_nonblank_text(data["target"])):
        return jsonify(error="invalid spell cast"), 400

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
        if character[1] != "wizard":
            return jsonify(error="character is not a spellcaster"), 400

        spell = connection.execute(
            "SELECT level FROM play_campaign_character_spells "
            "WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
            (campaign_id, character_id, data["spell_id"]),
        ).fetchone()
        prepared = connection.execute(
            "SELECT 1 FROM play_campaign_prepared_spells "
            "WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
            (campaign_id, character_id, data["spell_id"]),
        ).fetchone()
        if spell is None or prepared is None:
            return jsonify(error="spell is not prepared"), 400

        slot_level = spell[0]
        slots_used = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_spell_casts "
            "WHERE campaign_id = ? AND character_id = ? AND slot_level = ?",
            (campaign_id, character_id, slot_level),
        ).fetchone()[0]
        slots_remaining = spell_slot_capacity(character[1], character[2], slot_level) - slots_used
        if slots_remaining <= 0:
            return jsonify(error="no remaining spell slots"), 409

        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_spell_casts "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_spell_casts "
            "(campaign_id, character_id, sequence, spell_id, target, slot_level) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, character_id, sequence, data["spell_id"], data["target"], slot_level),
        )

    return jsonify(
        character_id=character_id,
        spell_id=data["spell_id"],
        target=data["target"],
        slot_level=slot_level,
        slots_remaining=slots_remaining - 1,
        sequence=sequence,
    ), 201


@app.get("/v1/play/campaigns/<campaign_id>/characters/<character_id>/casts")
def read_play_campaign_character_casts(campaign_id, character_id):
    """Return a campaign-visible character's ordered spell-cast history."""
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
        casts = connection.execute(
            "SELECT spell_id, target, slot_level, sequence "
            "FROM play_campaign_spell_casts WHERE campaign_id = ? AND character_id = ? "
            "ORDER BY sequence",
            (campaign_id, character_id),
        ).fetchall()

    slots_used = {}
    cast_history = []
    for spell_id, target, slot_level, sequence in casts:
        slots_used[slot_level] = slots_used.get(slot_level, 0) + 1
        cast_history.append({
            "character_id": character_id,
            "spell_id": spell_id,
            "target": target,
            "slot_level": slot_level,
            "slots_remaining": max(
                0,
                spell_slot_capacity(character[0], character[1], slot_level)
                - slots_used[slot_level],
            ),
            "sequence": sequence,
        })

    return jsonify(casts=cast_history)


def concentration_response(character_id, concentration):
    """Format the stable concentration projection used by all four routes."""
    if concentration is None:
        return jsonify(character_id=character_id, concentration=None)
    return jsonify(character_id=character_id, concentration={
        "spell_id": concentration[0],
        "target": concentration[1],
        "remaining_turns": concentration[2],
    })


@app.put("/v1/play/campaigns/<campaign_id>/characters/<character_id>/concentration")
def update_play_campaign_character_concentration(campaign_id, character_id):
    """Replace an owned spellcaster's current concentration."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("spell_id", "target", "duration_turns"))
    if (data is None
            or not valid_nonblank_text(data["spell_id"])
            or not valid_nonblank_text(data["target"])
            or type(data["duration_turns"]) is not int
            or data["duration_turns"] < 1):
        return jsonify(error="invalid concentration"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
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
            return jsonify(error="character is not a spellcaster"), 400
        known = connection.execute(
            "SELECT 1 FROM play_campaign_character_spells "
            "WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
            (campaign_id, character_id, data["spell_id"]),
        ).fetchone()
        prepared = connection.execute(
            "SELECT 1 FROM play_campaign_prepared_spells "
            "WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
            (campaign_id, character_id, data["spell_id"]),
        ).fetchone()
        if known is None:
            return jsonify(error="unknown spell"), 400
        if prepared is None:
            return jsonify(error="spell is not prepared"), 400
        connection.execute(
            "INSERT INTO play_campaign_concentrations "
            "(campaign_id, character_id, spell_id, target, remaining_turns) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, character_id) DO UPDATE SET "
            "spell_id = excluded.spell_id, target = excluded.target, "
            "remaining_turns = excluded.remaining_turns",
            (campaign_id, character_id, data["spell_id"], data["target"], data["duration_turns"]),
        )

    return concentration_response(
        character_id, (data["spell_id"], data["target"], data["duration_turns"])
    )


@app.get("/v1/play/campaigns/<campaign_id>/characters/<character_id>/concentration")
def read_play_campaign_character_concentration(campaign_id, character_id):
    """Return a campaign member's current concentration, if any."""
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
        concentration = connection.execute(
            "SELECT spell_id, target, remaining_turns FROM play_campaign_concentrations "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()

    return concentration_response(character_id, concentration)


@app.post("/v1/play/campaigns/<campaign_id>/characters/<character_id>/concentration/advance-turn")
def advance_play_campaign_character_concentration(campaign_id, character_id):
    """Advance a campaign-visible character's concentration by one turn."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _, error = play_campaign_member_viewer(connection, campaign_id, actor)
        if error is not None:
            return error
        character = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return jsonify(error="unknown character"), 404
        concentration = connection.execute(
            "SELECT spell_id, target, remaining_turns FROM play_campaign_concentrations "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if concentration is not None:
            remaining_turns = concentration[2] - 1
            if remaining_turns <= 0:
                connection.execute(
                    "DELETE FROM play_campaign_concentrations "
                    "WHERE campaign_id = ? AND character_id = ?",
                    (campaign_id, character_id),
                )
                concentration = None
            else:
                connection.execute(
                    "UPDATE play_campaign_concentrations SET remaining_turns = ? "
                    "WHERE campaign_id = ? AND character_id = ?",
                    (remaining_turns, campaign_id, character_id),
                )
                concentration = (concentration[0], concentration[1], remaining_turns)

    return concentration_response(character_id, concentration)


@app.delete("/v1/play/campaigns/<campaign_id>/characters/<character_id>/concentration")
def clear_play_campaign_character_concentration(campaign_id, character_id):
    """Clear the character owner's current concentration."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        character = connection.execute(
            "SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
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
        connection.execute(
            "DELETE FROM play_campaign_concentrations "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        )

    return concentration_response(character_id, None)


@app.post("/v1/play/campaigns/<campaign_id>/characters/<character_id>/inventory/items")
def add_play_campaign_character_inventory_item(campaign_id, character_id):
    """Add a catalog item to the owned character's held stack."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("item_id", "quantity"))
    if (data is None
            or data["item_id"] not in PLAY_INVENTORY_ITEM_IDS
            or type(data["quantity"]) is not int
            or data["quantity"] < 1):
        return jsonify(error="invalid inventory item"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        character = connection.execute(
            "SELECT owner FROM play_campaign_members "
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
        connection.execute(
            "INSERT INTO play_campaign_inventory_items "
            "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET "
            "quantity = quantity + excluded.quantity",
            (campaign_id, character_id, data["item_id"], data["quantity"]),
        )
        total_quantity = connection.execute(
            "SELECT quantity FROM play_campaign_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, data["item_id"]),
        ).fetchone()[0]

    return jsonify(
        character_id=character_id,
        item_id=data["item_id"],
        quantity=data["quantity"],
        total_quantity=total_quantity,
    ), 201


@app.get("/v1/play/campaigns/<campaign_id>/characters/<character_id>/inventory/items")
def read_play_campaign_character_inventory_items(campaign_id, character_id):
    """Return a campaign member-visible character's held item stacks."""
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
        items = connection.execute(
            "SELECT item_id, quantity FROM play_campaign_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY item_id",
            (campaign_id, character_id),
        ).fetchall()

    return jsonify(character_id=character_id, items=[
        {"item_id": item_id, "quantity": quantity} for item_id, quantity in items
    ])


@app.post("/v1/play/campaigns/<campaign_id>/characters/<character_id>/inventory/items/<item_id>/consume")
def consume_play_campaign_character_inventory_item(campaign_id, character_id, item_id):
    """Consume one unit of a held consumable item owned by the actor."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    if item_id not in PLAY_CONSUMABLE_ITEM_IDS:
        return jsonify(error="invalid consumable item"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        character = connection.execute(
            "SELECT owner FROM play_campaign_members "
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
        stack = connection.execute(
            "SELECT quantity FROM play_campaign_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()
        held_quantity = 0 if stack is None else stack[0]
        if held_quantity <= 0:
            return jsonify(error="insufficient held quantity"), 409
        total_quantity = held_quantity - 1
        if total_quantity == 0:
            connection.execute(
                "DELETE FROM play_campaign_inventory_items "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, character_id, item_id),
            )
        else:
            connection.execute(
                "UPDATE play_campaign_inventory_items SET quantity = ? "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (total_quantity, campaign_id, character_id, item_id),
            )

    return jsonify(
        character_id=character_id,
        item_id=item_id,
        quantity_consumed=1,
        total_quantity=total_quantity,
        effect={"type": "healing", "hp_restored": 5},
    )


@app.delete("/v1/play/campaigns/<campaign_id>/characters/<character_id>/inventory/items/<item_id>")
def remove_play_campaign_character_inventory_item(campaign_id, character_id, item_id):
    """Remove a positive quantity from an owned character's held item stack."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("quantity",))
    if (data is None
            or item_id not in PLAY_INVENTORY_ITEM_IDS
            or type(data["quantity"]) is not int
            or data["quantity"] < 1):
        return jsonify(error="invalid inventory item"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        character = connection.execute(
            "SELECT owner FROM play_campaign_members "
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
        stack = connection.execute(
            "SELECT quantity FROM play_campaign_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()
        held_quantity = 0 if stack is None else stack[0]
        if data["quantity"] > held_quantity:
            return jsonify(error="insufficient held quantity"), 409
        total_quantity = held_quantity - data["quantity"]
        if total_quantity == 0:
            connection.execute(
                "DELETE FROM play_campaign_inventory_items "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, character_id, item_id),
            )
        else:
            connection.execute(
                "UPDATE play_campaign_inventory_items SET quantity = ? "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (total_quantity, campaign_id, character_id, item_id),
            )

    return jsonify(
        character_id=character_id,
        item_id=item_id,
        quantity=data["quantity"],
        total_quantity=total_quantity,
    )


def equipment_response(character_id, slot, item_id="", attuned=False):
    """Build the stable public representation of one equipment slot."""
    return {
        "character_id": character_id,
        "slot": slot,
        "item_id": item_id,
        "attuned": attuned,
    }


@app.put("/v1/play/campaigns/<campaign_id>/characters/<character_id>/equipment/<slot>")
def equip_play_campaign_character_item(campaign_id, character_id, slot):
    """Equip a held catalog item in its legal character slot."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("item_id",))
    item_id = data["item_id"] if data is not None else None
    if (slot not in PLAY_EQUIPMENT_SLOTS
            or not isinstance(item_id, str)
            or item_id not in PLAY_EQUIPMENT_ITEM_SLOTS
            or PLAY_EQUIPMENT_ITEM_SLOTS[item_id] != slot):
        return jsonify(error="invalid equipment"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        character = connection.execute(
            "SELECT owner FROM play_campaign_members "
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
        held = connection.execute(
            "SELECT 1 FROM play_campaign_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ? AND quantity > 0",
            (campaign_id, character_id, item_id),
        ).fetchone()
        if held is None:
            return jsonify(error="invalid equipment"), 400
        connection.execute(
            "INSERT INTO play_campaign_equipment "
            "(campaign_id, character_id, slot, item_id, attuned) VALUES (?, ?, ?, ?, 0) "
            "ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET "
            "item_id = excluded.item_id, attuned = 0",
            (campaign_id, character_id, slot, item_id),
        )

    return jsonify(equipment_response(character_id, slot, item_id))


@app.get("/v1/play/campaigns/<campaign_id>/characters/<character_id>/equipment/<slot>")
def read_play_campaign_character_equipment(campaign_id, character_id, slot):
    """Read one equipment slot as a campaign member."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    if slot not in PLAY_EQUIPMENT_SLOTS:
        return jsonify(error="invalid equipment"), 400

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
        equipment = connection.execute(
            "SELECT item_id, attuned FROM play_campaign_equipment "
            "WHERE campaign_id = ? AND character_id = ? AND slot = ?",
            (campaign_id, character_id, slot),
        ).fetchone()

    if equipment is None:
        return jsonify(equipment_response(character_id, slot))
    return jsonify(equipment_response(character_id, slot, equipment[0], bool(equipment[1])))


@app.post("/v1/play/campaigns/<campaign_id>/characters/<character_id>/equipment/<slot>/attune")
def attune_play_campaign_character_equipment(campaign_id, character_id, slot):
    """Attune the equipped accessory, subject to the one-item limit."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    if slot not in PLAY_EQUIPMENT_SLOTS:
        return jsonify(error="invalid equipment"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        character = connection.execute(
            "SELECT owner FROM play_campaign_members "
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
        equipment = connection.execute(
            "SELECT item_id FROM play_campaign_equipment "
            "WHERE campaign_id = ? AND character_id = ? AND slot = ?",
            (campaign_id, character_id, slot),
        ).fetchone()
        if (slot != "accessory" or equipment is None
                or equipment[0] not in PLAY_ATTUNABLE_ITEM_IDS):
            return jsonify(error="invalid equipment"), 400
        attunement_count = connection.execute(
            "SELECT COUNT(*) FROM play_campaign_equipment "
            "WHERE campaign_id = ? AND character_id = ? AND attuned = 1",
            (campaign_id, character_id),
        ).fetchone()[0]
        if attunement_count >= 1:
            return jsonify(error="attunement limit reached"), 409
        connection.execute(
            "UPDATE play_campaign_equipment SET attuned = 1 "
            "WHERE campaign_id = ? AND character_id = ? AND slot = ?",
            (campaign_id, character_id, slot),
        )

    return jsonify(
        **equipment_response(character_id, slot, equipment[0], True),
        attunement_count=1,
        max_attunements=1,
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
        # A resolved exploration action hands control to the DM.  If that
        # handoff immediately becomes a monster encounter, retain the DM as
        # the actor once combat has concluded so the resolution is not lost
        # behind the combat interlude.  Encounters entered from an ordinary
        # player turn continue to resume that player unchanged.
        resolved_handoff = connection.execute(
            "SELECT 1 FROM play_campaign_events "
            "WHERE campaign_id = ? AND kind = 'resolution' LIMIT 1",
            (campaign_id,),
        ).fetchone() is not None
        has_monster = connection.execute(
            "SELECT 1 FROM play_campaign_encounter_monsters "
            "WHERE encounter_id = ? LIMIT 1",
            (encounter_id,),
        ).fetchone() is not None
        current_actor = campaign[0] if resolved_handoff and has_monster else campaign[2]
        connection.execute(
            "UPDATE play_campaigns SET phase = 'exploration', current_actor = ? WHERE id = ?",
            (current_actor, campaign_id),
        )

    return jsonify(
        campaign_id=campaign_id,
        status=campaign[1],
        phase="exploration",
        current_actor=current_actor,
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
            "SELECT owner, status, current_actor, turn_number, phase "
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
    # Before any encounter has completed, the established turn endpoint uses
    # actor-relative phases.  A completed encounter records the explicit
    # exploration transition instead.
    with database_connection() as connection:
        has_completed_encounter = connection.execute(
            "SELECT 1 FROM play_campaign_encounters "
            "WHERE campaign_id = ? AND status = 'closed' LIMIT 1",
            (campaign_id,),
        ).fetchone() is not None
    return jsonify(
        campaign_id=campaign_id,
        current_actor=campaign[2],
        # The campaign status is "active" after a start, while the turn
        # phase identifies which side is currently expected to act until an
        # encounter explicitly transitions it back to exploration.
        phase="exploration" if has_completed_encounter else (
            "dm" if campaign[2] == campaign[0] else "player"
        ),
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
        is_owner = actor[1] == "dm" and campaign[0] == actor[0]
        delegation = connection.execute(
            "SELECT powers_json FROM play_campaign_delegations "
            "WHERE campaign_id = ? AND username = ? AND active = 1",
            (campaign_id, actor[0]),
        ).fetchone()
        is_delegate = delegation is not None and "narrate" in json.loads(delegation[0])
        if not is_owner and not is_delegate:
            return jsonify(error="forbidden"), 403

        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, "narration", actor[0], data["text"]),
        )

    return jsonify(sequence=sequence, kind="narration", actor=actor[0], text=data["text"]), 201


def valid_delegation_powers(powers):
    # There is only one valid power in this stage, so this also rejects an
    # empty list, duplicates, non-string values, and unknown powers.
    return isinstance(powers, list) and powers == ["narrate"]


def delegation_response(username, powers, active):
    return jsonify(username=username, powers=powers, active=active)


@app.post("/v1/play/campaigns/<campaign_id>/delegations")
def grant_play_campaign_delegation(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("username", "powers"))
    if (data is None or not valid_nonblank_text(data["username"])
            or not valid_delegation_powers(data["powers"])):
        return jsonify(error="invalid delegation"), 400

    powers = data["powers"]
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
            member = connection.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, data["username"]),
            ).fetchone()
            if member is None:
                return jsonify(error="invalid delegation"), 400
            existing = connection.execute(
                "SELECT active FROM play_campaign_delegations "
                "WHERE campaign_id = ? AND username = ?",
                (campaign_id, data["username"]),
            ).fetchone()
            if existing is not None and existing[0]:
                return jsonify(error="active delegation already exists"), 409
            if existing is None:
                connection.execute(
                    "INSERT INTO play_campaign_delegations "
                    "(campaign_id, username, powers_json, active) VALUES (?, ?, ?, 1)",
                    (campaign_id, data["username"], json.dumps(powers, separators=(",", ":"))),
                )
            else:
                connection.execute(
                    "UPDATE play_campaign_delegations SET powers_json = ?, active = 1 "
                    "WHERE campaign_id = ? AND username = ?",
                    (json.dumps(powers, separators=(",", ":")), campaign_id, data["username"]),
                )
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_delegation_audit "
                "WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_delegation_audit "
                "(campaign_id, sequence, username, action, powers_json) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, sequence, data["username"], "granted",
                 json.dumps(powers, separators=(",", ":"))),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="active delegation already exists"), 409

    return delegation_response(data["username"], powers, True), 201


@app.delete("/v1/play/campaigns/<campaign_id>/delegations/<username>")
def revoke_play_campaign_delegation(campaign_id, username):
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
        delegation = connection.execute(
            "SELECT powers_json, active FROM play_campaign_delegations "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if delegation is None or not delegation[1]:
            return jsonify(error="unknown active delegation"), 404
        powers = json.loads(delegation[0])
        connection.execute(
            "UPDATE play_campaign_delegations SET active = 0 "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        )
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_delegation_audit "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO play_campaign_delegation_audit "
            "(campaign_id, sequence, username, action, powers_json) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, username, "revoked", delegation[0]),
        )

    return delegation_response(username, powers, False)


@app.get("/v1/play/campaigns/<campaign_id>/delegations/audit")
def read_play_campaign_delegation_audit(campaign_id):
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
        entries = connection.execute(
            "SELECT username, action, powers_json FROM play_campaign_delegation_audit "
            "WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()

    return jsonify(entries=[
        {"username": entry[0], "action": entry[1], "powers": json.loads(entry[2])}
        for entry in entries
    ])


@app.post("/v1/play/campaigns/<campaign_id>/audit-events")
def create_play_campaign_audit_event(campaign_id):
    """Append an immutable, actor-attributed campaign audit event."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("kind", "correlation_id"))
    if (data is None or not valid_nonblank_text(data["kind"])
            or not valid_nonblank_text(data["correlation_id"])):
        return jsonify(error="invalid audit event"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404

        is_owner = campaign[0] == actor[0]
        is_member = connection.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor[0]),
        ).fetchone() is not None
        if not is_owner and not is_member:
            return jsonify(error="forbidden"), 403

        duplicate = connection.execute(
            "SELECT 1 FROM play_campaign_audit_events "
            "WHERE campaign_id = ? AND correlation_id = ?",
            (campaign_id, data["correlation_id"]),
        ).fetchone()
        if duplicate is not None:
            return jsonify(error="correlation id already exists"), 409

        timestamp = connection.execute(
            "SELECT COALESCE(MAX(timestamp), 0) + 1 FROM play_campaign_audit_events "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        role = "DM" if is_owner else "player"
        connection.execute(
            "INSERT INTO play_campaign_audit_events "
            "(campaign_id, timestamp, kind, actor, role, correlation_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, timestamp, data["kind"], actor[0], role, data["correlation_id"]),
        )

    return jsonify(
        kind=data["kind"], actor=actor[0], role=role, timestamp=timestamp,
        correlation_id=data["correlation_id"],
    ), 201


@app.get("/v1/play/campaigns/<campaign_id>/audit-events")
def read_play_campaign_audit_events(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        entries = connection.execute(
            "SELECT kind, actor, role, timestamp, correlation_id "
            "FROM play_campaign_audit_events WHERE campaign_id = ? ORDER BY timestamp",
            (campaign_id,),
        ).fetchall()

    return jsonify(entries=[
        {"kind": entry[0], "actor": entry[1], "role": entry[2],
         "timestamp": entry[3], "correlation_id": entry[4]}
        for entry in entries
    ])


def rebuild_play_campaign_projection(connection, campaign_id):
    """Derive the projection exclusively from its immutable ordered event log."""
    events = connection.execute(
        "SELECT event_id, kind, value FROM play_campaign_projection_events "
        "WHERE campaign_id = ? ORDER BY sequence",
        (campaign_id,),
    ).fetchall()
    projection = {"story": "", "danger": 0, "applied_event_ids": []}
    for event_id, kind, value in events:
        projection["applied_event_ids"].append(event_id)
        if kind == "set-story":
            projection["story"] = value
        else:
            projection["danger"] += 1
    return projection


def play_campaign_projection_access(connection, campaign_id, actor):
    """Return the campaign when its owner or a member is allowed to read it."""
    campaign = connection.execute(
        "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if campaign is None:
        return None, (jsonify(error="unknown campaign"), 404)
    is_member = connection.execute(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        (campaign_id, actor[0]),
    ).fetchone() is not None
    if campaign[0] != actor[0] and not is_member:
        return None, (jsonify(error="forbidden"), 403)
    return campaign, None


@app.post("/v1/play/campaigns/<campaign_id>/idempotent-events")
def create_play_campaign_idempotent_event(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    idempotency_key = request.headers.get("Idempotency-Key")
    if not isinstance(idempotency_key, str) or not (idempotency_key := idempotency_key.strip()):
        return jsonify(error="invalid idempotency key"), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="invalid idempotent event"), 400
    event_id = data.get("event_id")
    value = data.get("value")
    if not isinstance(event_id, str) or not event_id or not isinstance(value, str) or not value:
        return jsonify(error="invalid idempotent event"), 400

    try:
        with database_connection() as connection:
            # Serializing writers makes a retry race observe the stored event
            # rather than create a second public effect.
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

            stored = connection.execute(
                "SELECT event_id, value, sequence, idempotency_key "
                "FROM play_campaign_idempotent_events "
                "WHERE campaign_id = ? AND idempotency_key = ?",
                (campaign_id, idempotency_key),
            ).fetchone()
            if stored is not None:
                if stored[0] != event_id or stored[1] != value:
                    return jsonify(error="idempotency key payload conflict"), 409
                return jsonify(
                    event_id=stored[0], value=stored[1], sequence=stored[2],
                    idempotency_key=stored[3],
                ), 200

            existing_event = connection.execute(
                "SELECT 1 FROM play_campaign_idempotent_events "
                "WHERE campaign_id = ? AND event_id = ?",
                (campaign_id, event_id),
            ).fetchone()
            if existing_event is not None:
                return jsonify(error="event id already exists"), 409

            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM play_campaign_idempotent_events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_idempotent_events "
                "(campaign_id, sequence, event_id, value, idempotency_key) "
                "VALUES (?, ?, ?, ?, ?)",
                (campaign_id, sequence, event_id, value, idempotency_key),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="event id already exists"), 409

    return jsonify(
        event_id=event_id, value=value, sequence=sequence,
        idempotency_key=idempotency_key,
    ), 201


@app.get("/v1/play/campaigns/<campaign_id>/idempotent-events")
def read_play_campaign_idempotent_events(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        _, error = play_campaign_projection_access(connection, campaign_id, actor)
        if error is not None:
            return error
        events = connection.execute(
            "SELECT event_id, value, sequence, idempotency_key "
            "FROM play_campaign_idempotent_events WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()
    return jsonify(events=[
        {"event_id": event[0], "value": event[1], "sequence": event[2],
         "idempotency_key": event[3]}
        for event in events
    ])


def play_campaign_safe_turn_access(connection, campaign_id, actor):
    """Return an access error unless the actor owns or belongs to a campaign."""
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
    return None


@app.post("/v1/play/campaigns/<campaign_id>/safe-turns")
def submit_play_campaign_safe_turn(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("submission_id", "expected_turn", "action"))
    if (data is None
            or not valid_nonblank_text(data["submission_id"])
            or not valid_nonblank_text(data["action"])
            or type(data["expected_turn"]) is not int
            or data["expected_turn"] <= 0):
        return jsonify(error="invalid safe turn"), 400

    try:
        with database_connection() as connection:
            # A write transaction makes duplicate and stale checks atomic with
            # the accepted turn increment, even across concurrent requests.
            connection.execute("BEGIN IMMEDIATE")
            error = play_campaign_safe_turn_access(connection, campaign_id, actor)
            if error is not None:
                return error

            duplicate = connection.execute(
                "SELECT 1 FROM play_campaign_safe_turn_submissions "
                "WHERE campaign_id = ? AND submission_id = ?",
                (campaign_id, data["submission_id"]),
            ).fetchone()
            if duplicate is not None:
                return jsonify(error="submission id already exists"), 409

            state = connection.execute(
                "SELECT current_turn FROM play_campaign_safe_turns WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            current_turn = 1 if state is None else state[0]
            if data["expected_turn"] != current_turn:
                return jsonify(current_turn=current_turn), 409

            next_turn = current_turn + 1
            if state is None:
                connection.execute(
                    "INSERT INTO play_campaign_safe_turns (campaign_id, current_turn) "
                    "VALUES (?, ?)",
                    (campaign_id, next_turn),
                )
            else:
                connection.execute(
                    "UPDATE play_campaign_safe_turns SET current_turn = ? WHERE campaign_id = ?",
                    (next_turn, campaign_id),
                )
            connection.execute(
                "INSERT INTO play_campaign_safe_turn_submissions "
                "(campaign_id, submission_id, action, accepted_turn, next_turn) "
                "VALUES (?, ?, ?, ?, ?)",
                (campaign_id, data["submission_id"], data["action"], current_turn, next_turn),
            )
    except sqlite3.IntegrityError:
        # The transaction normally prevents this race; retain the contract if
        # a preexisting database row is encountered through another writer.
        return jsonify(error="submission id already exists"), 409

    return jsonify(
        submission_id=data["submission_id"], action=data["action"],
        accepted_turn=current_turn, next_turn=next_turn,
    ), 201


@app.get("/v1/play/campaigns/<campaign_id>/safe-turns")
def read_play_campaign_safe_turns(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        error = play_campaign_safe_turn_access(connection, campaign_id, actor)
        if error is not None:
            return error
        state = connection.execute(
            "SELECT current_turn FROM play_campaign_safe_turns WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        accepted = connection.execute(
            "SELECT submission_id, action, accepted_turn, next_turn "
            "FROM play_campaign_safe_turn_submissions WHERE campaign_id = ? "
            "ORDER BY accepted_turn",
            (campaign_id,),
        ).fetchall()

    return jsonify(
        current_turn=1 if state is None else state[0],
        accepted=[
            {"submission_id": record[0], "action": record[1],
             "accepted_turn": record[2], "next_turn": record[3]}
            for record in accepted
        ],
    )


@app.post("/v1/play/campaigns/<campaign_id>/projection-events")
def append_play_campaign_projection_event(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="invalid projection event"), 400
    event_id = data.get("event_id")
    kind = data.get("kind")
    if not isinstance(event_id, str) or not event_id or kind not in ("set-story", "increment-danger"):
        return jsonify(error="invalid projection event"), 400
    if kind == "set-story":
        if "value" not in data or not isinstance(data["value"], str) or not data["value"]:
            return jsonify(error="invalid projection event"), 400
        value = data["value"]
    else:
        if "value" in data:
            return jsonify(error="invalid projection event"), 400
        value = None

    try:
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
            # Only player accounts that are members can append; the campaign
            # owner remains a read-only observer of this event stream.
            if actor[1] != "player" or not is_member:
                return jsonify(error="forbidden"), 403
            duplicate = connection.execute(
                "SELECT 1 FROM play_campaign_projection_events "
                "WHERE campaign_id = ? AND event_id = ?",
                (campaign_id, event_id),
            ).fetchone()
            if duplicate is not None:
                return jsonify(error="event id already exists"), 409
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
            rebuild_play_campaign_projection(connection, campaign_id)
    except sqlite3.IntegrityError:
        return jsonify(error="event id already exists"), 409

    event = {"sequence": sequence, "event_id": event_id, "kind": kind}
    if kind == "set-story":
        event["value"] = value
    return jsonify(event), 201


@app.get("/v1/play/campaigns/<campaign_id>/projection")
def read_play_campaign_projection(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    with database_connection() as connection:
        _, error = play_campaign_projection_access(connection, campaign_id, actor)
        if error is not None:
            return error
        projection = rebuild_play_campaign_projection(connection, campaign_id)
    return jsonify(projection)


@app.get("/v1/play/campaigns/<campaign_id>/projection/rebuild")
def rebuild_play_campaign_projection_route(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401
    with database_connection() as connection:
        _, error = play_campaign_projection_access(connection, campaign_id, actor)
        if error is not None:
            return error
        projection = rebuild_play_campaign_projection(connection, campaign_id)
    return jsonify(projection)


def rebuild_play_campaign_replay(connection, campaign_id):
    """Build the public replay state solely from ordered successful appends."""
    events = connection.execute(
        "SELECT event_id, text FROM play_campaign_replay_events "
        "WHERE campaign_id = ? ORDER BY sequence",
        (campaign_id,),
    ).fetchall()
    event_ids = [event[0] for event in events]
    story = "".join(event[1] for event in events)
    return {
        "story": story,
        "event_ids": event_ids,
        "digest": f"{','.join(event_ids)}|{story}",
    }


@app.post("/v1/play/campaigns/<campaign_id>/replay-events")
def append_play_campaign_replay_event(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("event_id", "kind", "text"))
    if (data is None or not isinstance(data["event_id"], str) or not data["event_id"]
            or data["kind"] != "append" or not isinstance(data["text"], str)
            or not data["text"]):
        return jsonify(error="invalid replay event"), 400

    try:
        with database_connection() as connection:
            # Serialize appends so the sequence is the successful append order.
            connection.execute("BEGIN IMMEDIATE")
            _, error = play_campaign_projection_access(connection, campaign_id, actor)
            if error is not None:
                return error
            duplicate = connection.execute(
                "SELECT 1 FROM play_campaign_replay_events "
                "WHERE campaign_id = ? AND event_id = ?",
                (campaign_id, data["event_id"]),
            ).fetchone()
            if duplicate is not None:
                return jsonify(error="event id already exists"), 409
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM play_campaign_replay_events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_replay_events "
                "(campaign_id, sequence, event_id, kind, text) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, sequence, data["event_id"], data["kind"], data["text"]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="event id already exists"), 409

    return jsonify(
        event_id=data["event_id"], kind="append", text=data["text"], sequence=sequence,
    ), 201


@app.get("/v1/play/campaigns/<campaign_id>/replay")
@app.get("/v1/play/campaigns/<campaign_id>/replay/check")
def read_play_campaign_replay(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        _, error = play_campaign_projection_access(connection, campaign_id, actor)
        if error is not None:
            return error
        replay = rebuild_play_campaign_replay(connection, campaign_id)
    return jsonify(replay)


def play_campaign_rng_access(connection, campaign_id, actor):
    """Return the campaign when its owner or a member may use its RNG ledger."""
    campaign = connection.execute(
        "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if campaign is None:
        return None, (jsonify(error="unknown campaign"), 404)
    is_member = connection.execute(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        (campaign_id, actor[0]),
    ).fetchone() is not None
    if campaign[0] != actor[0] and not is_member:
        return None, (jsonify(error="forbidden"), 403)
    return campaign, None


def deterministic_rng_result(seed, sequence, roll_id, sides):
    """Calculate the specified UTF-8, unsigned-32-bit campaign roll."""
    payload = f"{seed}|{sequence}|{roll_id}|{sides}".encode("utf-8")
    accumulator = 0
    for byte in payload:
        accumulator = (accumulator * 31 + byte) & 0xFFFFFFFF
    return (accumulator % sides) + 1


def rng_ledger_response(connection, campaign_id):
    seed_row = connection.execute(
        "SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?", (campaign_id,)
    ).fetchone()
    rolls = connection.execute(
        "SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls "
        "WHERE campaign_id = ? ORDER BY sequence",
        (campaign_id,),
    ).fetchall()
    return {
        "seed": None if seed_row is None else seed_row[0],
        "rolls": [
            {"roll_id": roll[0], "sides": roll[1], "result": roll[2], "sequence": roll[3]}
            for roll in rolls
        ],
    }


@app.put("/v1/play/campaigns/<campaign_id>/rng-seed")
def configure_play_campaign_rng_seed(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("seed",))
    if data is None or not valid_nonblank_text(data["seed"]):
        return jsonify(error="invalid rng seed"), 400

    try:
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            campaign, error = play_campaign_rng_access(connection, campaign_id, actor)
            if error is not None:
                return error
            if actor[1] != "dm" or campaign[0] != actor[0]:
                return jsonify(error="forbidden"), 403
            if connection.execute(
                "SELECT 1 FROM play_campaign_rng_seeds WHERE campaign_id = ?", (campaign_id,)
            ).fetchone() is not None:
                return jsonify(error="rng seed already configured"), 409
            connection.execute(
                "INSERT INTO play_campaign_rng_seeds (campaign_id, seed) VALUES (?, ?)",
                (campaign_id, data["seed"]),
            )
            ledger = rng_ledger_response(connection, campaign_id)
    except sqlite3.IntegrityError:
        return jsonify(error="rng seed already configured"), 409
    return jsonify(ledger)


@app.post("/v1/play/campaigns/<campaign_id>/rng-rolls")
def append_play_campaign_rng_roll(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("roll_id", "sides"))
    if (data is None or not valid_nonblank_text(data["roll_id"])
            or type(data["sides"]) is not int or not 2 <= data["sides"] <= 100):
        return jsonify(error="invalid rng roll"), 400

    try:
        with database_connection() as connection:
            # A write transaction makes sequence exactly the accepted append order.
            connection.execute("BEGIN IMMEDIATE")
            _, error = play_campaign_rng_access(connection, campaign_id, actor)
            if error is not None:
                return error
            seed_row = connection.execute(
                "SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()
            if seed_row is None:
                return jsonify(error="rng seed not configured"), 409
            duplicate = connection.execute(
                "SELECT 1 FROM play_campaign_rng_rolls WHERE campaign_id = ? AND roll_id = ?",
                (campaign_id, data["roll_id"]),
            ).fetchone()
            if duplicate is not None:
                return jsonify(error="roll id already exists"), 409
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_rng_rolls "
                "WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            result = deterministic_rng_result(seed_row[0], sequence, data["roll_id"], data["sides"])
            connection.execute(
                "INSERT INTO play_campaign_rng_rolls "
                "(campaign_id, sequence, roll_id, sides, result) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, sequence, data["roll_id"], data["sides"], result),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="roll id already exists"), 409

    return jsonify(
        roll_id=data["roll_id"], sides=data["sides"], result=result, sequence=sequence,
    ), 201


@app.get("/v1/play/campaigns/<campaign_id>/rng-ledger")
def read_play_campaign_rng_ledger(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        _, error = play_campaign_rng_access(connection, campaign_id, actor)
        if error is not None:
            return error
        ledger = rng_ledger_response(connection, campaign_id)
    return jsonify(ledger)


def play_campaign_moderation_access(connection, campaign_id, actor):
    """Return a campaign when its DM or a player member may moderate-read."""
    campaign = connection.execute(
        "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if campaign is None:
        return None, (jsonify(error="unknown campaign"), 404)
    is_member = connection.execute(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        (campaign_id, actor[0]),
    ).fetchone() is not None
    if campaign[0] != actor[0] and not is_member:
        return None, (jsonify(error="forbidden"), 403)
    return campaign, None


def moderation_report_response(report):
    response = {
        "report_id": report[0],
        "target_id": report[1],
        "reason": report[2],
        "status": report[3],
        "reporter": report[4],
        "sequence": report[5],
    }
    if report[3] == "resolved":
        response.update(action=report[6], note=report[7], resolver=report[8])
    return response


@app.post("/v1/play/campaigns/<campaign_id>/moderation/reports")
def submit_play_campaign_moderation_report(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("report_id", "target_id", "reason"))
    if (data is None or not valid_nonblank_text(data["report_id"])
            or not valid_nonblank_text(data["target_id"])
            or not valid_nonblank_text(data["reason"])):
        return jsonify(error="invalid moderation report"), 400

    try:
        with database_connection() as connection:
            # Serialize report appends so sequence is the accepted append order.
            connection.execute("BEGIN IMMEDIATE")
            _, error = play_campaign_moderation_access(connection, campaign_id, actor)
            if error is not None:
                return error
            duplicate = connection.execute(
                "SELECT 1 FROM play_campaign_moderation_reports "
                "WHERE campaign_id = ? AND report_id = ?",
                (campaign_id, data["report_id"]),
            ).fetchone()
            if duplicate is not None:
                return jsonify(error="report id already exists"), 409
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM play_campaign_moderation_reports WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_moderation_reports "
                "(campaign_id, sequence, report_id, target_id, reason, status, reporter) "
                "VALUES (?, ?, ?, ?, ?, 'open', ?)",
                (campaign_id, sequence, data["report_id"], data["target_id"], data["reason"], actor[0]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="report id already exists"), 409

    return jsonify(
        report_id=data["report_id"], target_id=data["target_id"], reason=data["reason"],
        status="open", reporter=actor[0], sequence=sequence,
    ), 201


@app.get("/v1/play/campaigns/<campaign_id>/moderation/reports")
def read_play_campaign_moderation_reports(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        _, error = play_campaign_moderation_access(connection, campaign_id, actor)
        if error is not None:
            return error
        reports = connection.execute(
            "SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver "
            "FROM play_campaign_moderation_reports WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()
    return jsonify(reports=[moderation_report_response(report) for report in reports])


@app.put("/v1/play/campaigns/<campaign_id>/moderation/reports/<report_id>/resolution")
def resolve_play_campaign_moderation_report(campaign_id, report_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("action", "note"))
    if (data is None or data["action"] not in ("allow", "remove")
            or not valid_nonblank_text(data["note"])):
        return jsonify(error="invalid moderation resolution"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign, error = play_campaign_moderation_access(connection, campaign_id, actor)
        if error is not None:
            return error
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        report = connection.execute(
            "SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver "
            "FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?",
            (campaign_id, report_id),
        ).fetchone()
        if report is None:
            return jsonify(error="unknown report"), 404
        if report[3] != "open":
            return jsonify(error="report already resolved"), 409
        connection.execute(
            "UPDATE play_campaign_moderation_reports "
            "SET status = 'resolved', action = ?, note = ?, resolver = ? "
            "WHERE campaign_id = ? AND report_id = ?",
            (data["action"], data["note"], actor[0], campaign_id, report_id),
        )
        report = report[:3] + ("resolved",) + report[4:6] + (
            data["action"], data["note"], actor[0],
        )
    return jsonify(moderation_report_response(report))


def valid_safety_tags(value):
    """Require a nonempty, duplicate-free list of nonblank string tags."""
    return (
        isinstance(value, list)
        and bool(value)
        and all(valid_nonblank_text(tag) for tag in value)
        and len(set(value)) == len(value)
    )


def play_campaign_safety_access(connection, campaign_id, actor):
    """Return a campaign when its DM or a member may access safety state."""
    return play_campaign_moderation_access(connection, campaign_id, actor)


def safety_boundaries_response(connection, campaign_id):
    row = connection.execute(
        "SELECT blocked_tags_json FROM play_campaign_safety_boundaries WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    return {"blocked_tags": [] if row is None else json.loads(row[0])}


@app.put("/v1/play/campaigns/<campaign_id>/safety-boundaries")
def replace_play_campaign_safety_boundaries(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("blocked_tags",))
    if data is None or not valid_safety_tags(data["blocked_tags"]):
        return jsonify(error="invalid safety boundaries"), 400
    blocked_tags = sorted(data["blocked_tags"])

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign, error = play_campaign_safety_access(connection, campaign_id, actor)
        if error is not None:
            return error
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        connection.execute(
            "INSERT INTO play_campaign_safety_boundaries (campaign_id, blocked_tags_json) "
            "VALUES (?, ?) ON CONFLICT(campaign_id) DO UPDATE SET "
            "blocked_tags_json = excluded.blocked_tags_json",
            (campaign_id, json.dumps(blocked_tags, separators=(",", ":"))),
        )
    return jsonify(blocked_tags=blocked_tags)


@app.get("/v1/play/campaigns/<campaign_id>/safety-boundaries")
def read_play_campaign_safety_boundaries(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        _, error = play_campaign_safety_access(connection, campaign_id, actor)
        if error is not None:
            return error
        boundaries = safety_boundaries_response(connection, campaign_id)
    return jsonify(boundaries)


@app.post("/v1/play/campaigns/<campaign_id>/safety-checks")
def submit_play_campaign_safety_check(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("event_id", "kind", "text", "tags"))
    if (data is None or not valid_nonblank_text(data["event_id"])
            or data["kind"] not in ("narration", "chat")
            or not valid_nonblank_text(data["text"])
            or not valid_safety_tags(data["tags"])):
        return jsonify(error="invalid safety check"), 400

    try:
        with database_connection() as connection:
            # Serialize checks so sequence is precisely accepted append order.
            connection.execute("BEGIN IMMEDIATE")
            _, error = play_campaign_safety_access(connection, campaign_id, actor)
            if error is not None:
                return error
            duplicate = connection.execute(
                "SELECT 1 FROM play_campaign_safety_events "
                "WHERE campaign_id = ? AND event_id = ?",
                (campaign_id, data["event_id"]),
            ).fetchone()
            if duplicate is not None:
                return jsonify(error="event id already exists"), 409
            boundaries = safety_boundaries_response(connection, campaign_id)
            if set(data["tags"]) & set(boundaries["blocked_tags"]):
                return jsonify(error="safety tag is blocked"), 409
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM play_campaign_safety_events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_safety_events "
                "(campaign_id, sequence, event_id, kind, text, tags_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, sequence, data["event_id"], data["kind"], data["text"],
                 json.dumps(data["tags"], separators=(",", ":"))),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="event id already exists"), 409

    return jsonify(
        event_id=data["event_id"], kind=data["kind"], text=data["text"],
        tags=data["tags"], sequence=sequence,
    ), 201


@app.get("/v1/play/campaigns/<campaign_id>/safety-events")
def read_play_campaign_safety_events(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        _, error = play_campaign_safety_access(connection, campaign_id, actor)
        if error is not None:
            return error
        events = connection.execute(
            "SELECT event_id, kind, text, tags_json, sequence "
            "FROM play_campaign_safety_events WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()
    return jsonify(events=[{
        "event_id": event[0], "kind": event[1], "text": event[2],
        "tags": json.loads(event[3]), "sequence": event[4],
    } for event in events])


@app.post("/v1/play/campaigns/<campaign_id>/feed-events")
def append_play_campaign_feed_event(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("event_id", "text"))
    if (data is None or not valid_nonblank_text(data["event_id"])
            or not valid_nonblank_text(data["text"])):
        return jsonify(error="invalid feed event"), 400

    try:
        with database_connection() as connection:
            # Keep sequence allocation in the same write transaction as the insert.
            connection.execute("BEGIN IMMEDIATE")
            _, error = play_campaign_moderation_access(connection, campaign_id, actor)
            if error is not None:
                return error
            duplicate = connection.execute(
                "SELECT 1 FROM play_campaign_feed_events "
                "WHERE campaign_id = ? AND event_id = ?",
                (campaign_id, data["event_id"]),
            ).fetchone()
            if duplicate is not None:
                return jsonify(error="event id already exists"), 409
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM play_campaign_feed_events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO play_campaign_feed_events "
                "(campaign_id, sequence, event_id, text) VALUES (?, ?, ?, ?)",
                (campaign_id, sequence, data["event_id"], data["text"]),
            )
    except sqlite3.IntegrityError:
        return jsonify(error="event id already exists"), 409

    return jsonify(event_id=data["event_id"], text=data["text"], sequence=sequence), 201


@app.get("/v1/play/campaigns/<campaign_id>/event-feed")
def read_play_campaign_event_feed(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    cursor = search_pagination_value("cursor", 0, 0)
    limit = search_pagination_value("limit", 2, 1, 3)
    if cursor is None or limit is None:
        return jsonify(error="invalid feed pagination"), 400

    with database_connection() as connection:
        _, error = play_campaign_moderation_access(connection, campaign_id, actor)
        if error is not None:
            return error
        events = connection.execute(
            "SELECT event_id, text, sequence FROM play_campaign_feed_events "
            "WHERE campaign_id = ? ORDER BY sequence LIMIT ? OFFSET ?",
            (campaign_id, limit, cursor),
        ).fetchall()

    page = [
        {"event_id": event[0], "text": event[1], "sequence": event[2]}
        for event in events
    ]
    return jsonify(events=page, next_cursor=cursor + len(page))


def canonical_fixture_state():
    """Return a fresh copy of the one supported deterministic fixture."""
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


@app.post("/v1/play/campaigns/<campaign_id>/fixture-seeds")
def seed_play_campaign_fixture(campaign_id):
    """Seed the campaign's canonical fixture exactly once."""
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    data = json_with_required_fields(("fixture_id",))
    if data is None or data["fixture_id"] != "canonical-v1":
        return jsonify(error="invalid fixture"), 400

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="unknown campaign"), 404
        if actor[1] != "dm" or campaign[0] != actor[0]:
            return jsonify(error="forbidden"), 403
        inserted = connection.execute(
            "INSERT OR IGNORE INTO play_campaign_fixture_seeds (campaign_id, fixture_id) "
            "VALUES (?, ?)",
            (campaign_id, "canonical-v1"),
        ).rowcount == 1

    return jsonify(canonical_fixture_state()), 201 if inserted else 200


@app.get("/v1/play/campaigns/<campaign_id>/fixture-state")
def read_play_campaign_fixture_state(campaign_id):
    actor = authenticated_actor()
    if actor is None:
        return jsonify(error="unauthorized"), 401

    with database_connection() as connection:
        _, error = play_campaign_safety_access(connection, campaign_id, actor)
        if error is not None:
            return error
        seeded = connection.execute(
            "SELECT 1 FROM play_campaign_fixture_seeds WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if seeded is None:
            return jsonify(error="fixture not seeded"), 404
    return jsonify(canonical_fixture_state())


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
            "WHERE campaign_id = ? AND kind IN (?, ?) "
            "ORDER BY sequence DESC LIMIT 1",
            (campaign_id, "action", "travel"),
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
