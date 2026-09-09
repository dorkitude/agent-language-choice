"""SQLite persistence boundary for the REST views.

The API stores only the small amount of state that must survive requests.  This
module deliberately returns ordinary dictionaries so HTTP serialization and
validation remain the responsibility of ``dndsite.urls``.
"""

import json
import sqlite3
from pathlib import Path


SCHEMA_VERSION = 1
DATABASE_PATH = Path(__file__).resolve().parent.parent / "game.db"

# Children must be cleared before their parents.  Keep this explicit order even
# though SQLite foreign-key enforcement is not enabled on these connections.
RESET_TABLES = (
    "users",
    "combat_sessions",
    "compendium_monsters",
    "compendium_items",
    "campaign_characters",
    "campaign_events",
    "campaign_quests",
    "character_equipment",
    "campaign_inventory",
    "crafting_projects",
    "campaign_session_attendance",
    "campaign_sessions",
    "campaign_npcs",
    "campaign_factions",
    "campaigns",
    "play_campaign_turns",
    "play_campaign_nudges",
    "play_campaign_current_scenes",
    "play_campaign_current_locations",
    "play_campaign_scenes",
    "play_campaign_location_connections",
    "play_campaign_locations",
    "play_campaign_documents",
    "play_campaign_backups",
    "play_campaign_exports",
    "play_campaign_import_states",
    "play_campaign_migration_states",
    "play_campaign_search_records",
    "play_campaign_service_metrics",
    "play_campaign_rate_events",
    "play_campaign_character_prepared_spells",
    "play_campaign_character_spells",
    "play_campaign_character_casts",
    "play_campaign_character_concentrations",
    "play_campaign_character_inventory_items",
    "play_campaign_downtime_allocations",
    "play_campaign_downtime_activities",
    "play_campaign_recipes",
    "play_campaign_loot_votes",
    "play_campaign_loot",
    "play_campaign_npc_dialogue",
    "play_campaign_clues",
    "play_campaign_world_events",
    "play_campaign_calendars",
    "play_campaign_shops",
    "play_campaign_settlement_discoveries",
    "play_campaign_settlements",
    "play_campaign_quest_reward_grants",
    "play_campaign_quests",
    "play_campaign_relationships",
    "play_campaign_npcs",
    "play_campaign_reputation_history",
    "play_campaign_factions",
    "play_campaign_character_equipment",
    "play_campaign_transactional_transfers",
    "play_campaign_currency_transfers",
    "play_campaign_character_currency",
    "play_campaign_character_owners",
    "play_campaign_invitations",
    "play_campaign_delegation_audit",
    "play_campaign_delegations",
    "play_campaign_audit_events",
    "play_campaign_projection_events",
    "play_campaign_replay_events",
    "play_campaign_rng_rolls",
    "play_campaign_rng_seeds",
    "play_campaign_moderation_reports",
    "play_campaign_safety_events",
    "play_campaign_safety_boundaries",
    "play_campaign_fixture_states",
    "play_campaign_idempotent_events",
    "play_campaign_safe_turns",
    "play_campaign_safe_turn_state",
    "play_campaign_spectators",
    "play_campaign_feed_events",
    "play_campaign_members",
    "play_campaign_session_zero_settings",
    "play_campaign_whispers",
    "play_campaign_notes",
    "play_campaign_content",
    "play_campaign_narrations",
    "play_campaign_actions",
    "play_campaign_resolutions",
    "play_campaign_travels",
    "play_campaign_rests",
    "play_campaign_event_sequences",
    "play_campaign_combat_actions",
    "play_campaign_encounter_conditions",
    "play_campaign_encounter_turn_order",
    "play_campaign_encounter_ready_actions",
    "play_campaign_encounter_rewards",
    "play_campaign_encounter_combatants",
    "play_campaign_encounter_monsters",
    "play_campaign_encounters",
    "play_campaigns",
)


def connection():
    """Open one short-lived connection; context managers commit successful writes."""
    database = sqlite3.connect(DATABASE_PATH)
    database.row_factory = sqlite3.Row
    return database


def encode_json(value):
    """Use the stable compact representation used for JSON-in-SQLite fields."""
    return json.dumps(value, separators=(",", ":"))


def decode_json(value):
    return json.loads(value)


def next_play_campaign_event_sequence(database, campaign_id, kind):
    """Allocate one campaign-wide event sequence inside an open transaction."""
    sequence = database.execute(
        """
        SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM (
            SELECT sequence FROM play_campaign_narrations WHERE campaign_id = ?
            UNION ALL
            SELECT sequence FROM play_campaign_actions WHERE campaign_id = ?
            UNION ALL
            SELECT sequence FROM play_campaign_resolutions WHERE campaign_id = ?
            UNION ALL
            SELECT sequence FROM play_campaign_travels WHERE campaign_id = ?
            UNION ALL
            SELECT sequence FROM play_campaign_rests WHERE campaign_id = ?
            UNION ALL
            SELECT sequence FROM play_campaign_combat_actions WHERE campaign_id = ?
            UNION ALL
            SELECT sequence FROM play_campaign_event_sequences WHERE campaign_id = ?
        )
        """,
        (
            campaign_id, campaign_id, campaign_id, campaign_id, campaign_id,
            campaign_id, campaign_id,
        ),
    ).fetchone()["sequence"]
    database.execute(
        """
        INSERT INTO play_campaign_event_sequences (campaign_id, sequence, kind)
        VALUES (?, ?, ?)
        """,
        (campaign_id, sequence, kind),
    )
    return sequence


def initialize():
    """Create the version-one schema if it is not already present."""
    with connection() as database:
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS storage_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL,
                role TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS combat_sessions (
                id TEXT PRIMARY KEY,
                state TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS compendium_monsters (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cr TEXT NOT NULL,
                armor_class INTEGER NOT NULL,
                hit_points INTEGER NOT NULL,
                tags TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS compendium_items (
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
                phase TEXT NOT NULL DEFAULT 'exploration'
            );
            CREATE TABLE IF NOT EXISTS play_campaign_spectators (
                spectator_id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_feed_events (
                campaign_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                text TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, event_id),
                UNIQUE (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_session_zero_settings (
                campaign_id TEXT PRIMARY KEY,
                rules TEXT NOT NULL,
                tone TEXT NOT NULL,
                consent TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_invitations (
                creation_order INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                invitation_id TEXT NOT NULL,
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                status TEXT NOT NULL,
                UNIQUE (campaign_id, invitation_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_delegations (
                campaign_id TEXT NOT NULL,
                username TEXT NOT NULL,
                powers TEXT NOT NULL,
                active INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, username),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (
                creation_order INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                powers TEXT NOT NULL,
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
                PRIMARY KEY (campaign_id, sequence),
                UNIQUE (campaign_id, event_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_replay_events (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (campaign_id, sequence),
                UNIQUE (campaign_id, event_id),
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
                PRIMARY KEY (campaign_id, sequence),
                UNIQUE (campaign_id, roll_id),
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
                PRIMARY KEY (campaign_id, sequence),
                UNIQUE (campaign_id, report_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries (
                campaign_id TEXT PRIMARY KEY,
                blocked_tags TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_safety_events (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                tags TEXT NOT NULL,
                PRIMARY KEY (campaign_id, sequence),
                UNIQUE (campaign_id, event_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_fixture_states (
                campaign_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                value TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                PRIMARY KEY (campaign_id, sequence),
                UNIQUE (campaign_id, event_id),
                UNIQUE (campaign_id, idempotency_key),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_state (
                campaign_id TEXT PRIMARY KEY,
                current_turn INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (
                campaign_id TEXT NOT NULL,
                submission_id TEXT NOT NULL,
                action TEXT NOT NULL,
                accepted_turn INTEGER NOT NULL,
                next_turn INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, submission_id),
                UNIQUE (campaign_id, accepted_turn),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_content (
                campaign_id TEXT NOT NULL,
                content_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                tags TEXT NOT NULL,
                PRIMARY KEY (campaign_id, content_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_notes (
                creation_order INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                note_id TEXT NOT NULL,
                text TEXT NOT NULL,
                visibility TEXT NOT NULL,
                owner TEXT NOT NULL,
                UNIQUE (campaign_id, note_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_whispers (
                creation_order INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                whisper_id TEXT NOT NULL,
                from_character_id TEXT NOT NULL,
                to_character_id TEXT NOT NULL,
                text TEXT NOT NULL,
                UNIQUE (campaign_id, whisper_id),
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
            CREATE UNIQUE INDEX IF NOT EXISTS active_play_campaign_encounter
            ON play_campaign_encounters(campaign_id) WHERE status = 'active';
            CREATE TABLE IF NOT EXISTS play_campaign_encounter_monsters (
                encounter_id TEXT NOT NULL,
                monster_id TEXT NOT NULL,
                name TEXT NOT NULL,
                hp_current INTEGER NOT NULL,
                hp_max INTEGER NOT NULL,
                initiative INTEGER NOT NULL,
                PRIMARY KEY (encounter_id, monster_id),
                FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_encounter_combatants (
                encounter_id TEXT NOT NULL,
                member TEXT NOT NULL,
                character_id TEXT NOT NULL,
                name TEXT NOT NULL,
                initiative INTEGER NOT NULL,
                PRIMARY KEY (encounter_id, member),
                FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_encounter_conditions (
                encounter_id TEXT NOT NULL,
                target TEXT NOT NULL,
                condition TEXT NOT NULL,
                remaining_rounds INTEGER NOT NULL,
                PRIMARY KEY (encounter_id, target, condition),
                FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_encounter_turn_order (
                encounter_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                tie_id TEXT NOT NULL,
                PRIMARY KEY (encounter_id, position),
                UNIQUE (encounter_id, tie_id),
                FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_encounter_ready_actions (
                encounter_id TEXT NOT NULL,
                actor TEXT NOT NULL,
                trigger TEXT NOT NULL,
                PRIMARY KEY (encounter_id, actor),
                FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_encounter_rewards (
                encounter_id TEXT PRIMARY KEY,
                xp INTEGER NOT NULL,
                loot TEXT NOT NULL,
                FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_documents (
                campaign_id TEXT PRIMARY KEY,
                story TEXT NOT NULL,
                dm_notes TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_backups (
                creation_order INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                backup_id TEXT NOT NULL,
                story TEXT NOT NULL,
                status TEXT NOT NULL,
                UNIQUE (campaign_id, backup_id),
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
            CREATE TABLE IF NOT EXISTS play_campaign_import_states (
                campaign_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                story TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_migration_states (
                campaign_id TEXT PRIMARY KEY,
                story TEXT NOT NULL,
                campaign_name TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_search_records (
                creation_order INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                text TEXT NOT NULL,
                UNIQUE (campaign_id, record_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_rate_events (
                creation_order INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                actor TEXT NOT NULL,
                UNIQUE (campaign_id, event_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_service_metrics (
                campaign_id TEXT PRIMARY KEY,
                rejected_rate_events INTEGER NOT NULL DEFAULT 0,
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
            CREATE TABLE IF NOT EXISTS play_campaign_current_scenes (
                campaign_id TEXT PRIMARY KEY,
                scene_id TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_locations (
                campaign_id TEXT NOT NULL,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                PRIMARY KEY (campaign_id, id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_current_locations (
                campaign_id TEXT PRIMARY KEY,
                location_id TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_location_connections (
                campaign_id TEXT NOT NULL,
                from_id TEXT NOT NULL,
                to_id TEXT NOT NULL,
                travel_turns INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, from_id, to_id),
                FOREIGN KEY (campaign_id, from_id)
                    REFERENCES play_campaign_locations(campaign_id, id),
                FOREIGN KEY (campaign_id, to_id)
                    REFERENCES play_campaign_locations(campaign_id, id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_members (
                campaign_id TEXT NOT NULL,
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                name TEXT NOT NULL,
                class TEXT NOT NULL,
                hp_current INTEGER NOT NULL DEFAULT 20,
                hp_max INTEGER NOT NULL DEFAULT 20,
                level INTEGER NOT NULL DEFAULT 1,
                con_modifier INTEGER NOT NULL DEFAULT 0,
                character_class TEXT NOT NULL DEFAULT '',
                abilities TEXT NOT NULL DEFAULT '{}',
                death_save_successes INTEGER NOT NULL DEFAULT 0,
                death_save_failures INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'conscious',
                PRIMARY KEY (campaign_id, username),
                UNIQUE (campaign_id, character_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_character_owners (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                owner TEXT,
                PRIMARY KEY (campaign_id, character_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_character_currency (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                gold INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
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
            CREATE TABLE IF NOT EXISTS play_campaign_character_spells (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                spell_id TEXT NOT NULL,
                name TEXT NOT NULL,
                level INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id, spell_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_character_prepared_spells (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                spell_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id, spell_id),
                UNIQUE (campaign_id, character_id, position),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_character_casts (
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
            CREATE TABLE IF NOT EXISTS play_campaign_character_concentrations (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                spell_id TEXT NOT NULL,
                target TEXT NOT NULL,
                remaining_turns INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_character_inventory_items (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id, item_id),
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
                cycles_completed INTEGER NOT NULL,
                completions INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id, activity_id),
                FOREIGN KEY (campaign_id, activity_id)
                    REFERENCES play_campaign_downtime_activities(campaign_id, activity_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_recipes (
                campaign_id TEXT NOT NULL,
                recipe_id TEXT NOT NULL,
                name TEXT NOT NULL,
                ingredients TEXT NOT NULL,
                output_item TEXT NOT NULL,
                output_quantity INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, recipe_id),
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
                dialogue_id TEXT NOT NULL,
                speaker TEXT NOT NULL,
                text TEXT NOT NULL,
                visibility TEXT NOT NULL,
                PRIMARY KEY (campaign_id, npc_id, dialogue_id),
                FOREIGN KEY (campaign_id, npc_id)
                    REFERENCES play_campaign_npcs(campaign_id, npc_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_clues (
                campaign_id TEXT NOT NULL,
                clue_id TEXT NOT NULL,
                text TEXT NOT NULL,
                audience TEXT NOT NULL,
                character_id TEXT,
                PRIMARY KEY (campaign_id, clue_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_world_events (
                creation_order INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                turn_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                resolution_turn_number INTEGER,
                resolution_text TEXT,
                UNIQUE (campaign_id, event_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_calendars (
                campaign_id TEXT PRIMARY KEY,
                day INTEGER NOT NULL,
                season TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_settlements (
                creation_order INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                name TEXT NOT NULL,
                services TEXT NOT NULL,
                availability TEXT NOT NULL,
                UNIQUE (campaign_id, settlement_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_settlement_discoveries (
                discovery_order INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                UNIQUE (campaign_id, settlement_id, character_id),
                FOREIGN KEY (campaign_id, settlement_id)
                    REFERENCES play_campaign_settlements(campaign_id, settlement_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_shops (
                campaign_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                shop_id TEXT NOT NULL,
                name TEXT NOT NULL,
                stock TEXT NOT NULL,
                buy_price INTEGER NOT NULL,
                sell_price INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, settlement_id, shop_id),
                FOREIGN KEY (campaign_id, settlement_id)
                    REFERENCES play_campaign_settlements(campaign_id, settlement_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_quests (
                campaign_id TEXT NOT NULL,
                quest_id TEXT NOT NULL,
                title TEXT NOT NULL,
                depends_on TEXT NOT NULL,
                state TEXT NOT NULL,
                rewards TEXT,
                rewards_awarded INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (campaign_id, quest_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_quest_reward_grants (
                campaign_id TEXT NOT NULL,
                quest_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                xp INTEGER NOT NULL,
                items TEXT NOT NULL,
                PRIMARY KEY (campaign_id, quest_id, character_id),
                FOREIGN KEY (campaign_id, quest_id)
                    REFERENCES play_campaign_quests(campaign_id, quest_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_relationships (
                campaign_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                score INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, source_id, target_id, kind),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_factions (
                campaign_id TEXT NOT NULL,
                faction_id TEXT NOT NULL,
                name TEXT NOT NULL,
                PRIMARY KEY (campaign_id, faction_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_reputation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                faction_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                reputation INTEGER NOT NULL,
                delta INTEGER NOT NULL,
                reason TEXT NOT NULL,
                FOREIGN KEY (campaign_id, faction_id)
                    REFERENCES play_campaign_factions(campaign_id, faction_id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_character_equipment (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                slot TEXT NOT NULL,
                item_id TEXT NOT NULL,
                attuned INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (campaign_id, character_id, slot),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_turns (
                campaign_id TEXT PRIMARY KEY,
                current_actor TEXT NOT NULL,
                turn_number INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_nudges (
                campaign_id TEXT PRIMARY KEY,
                nudge_count INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_narrations (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_actions (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                actor TEXT NOT NULL,
                action_type TEXT NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_resolutions (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                actor TEXT NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_travels (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                actor TEXT NOT NULL,
                destination_id TEXT NOT NULL,
                travel_turns INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_rests (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                actor TEXT NOT NULL,
                rest_type TEXT NOT NULL,
                hp_current INTEGER NOT NULL,
                hp_max INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_event_sequences (
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                kind TEXT NOT NULL,
                PRIMARY KEY (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS play_campaign_combat_actions (
                campaign_id TEXT NOT NULL,
                encounter_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                actor TEXT NOT NULL,
                action_type TEXT NOT NULL,
                target TEXT NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (campaign_id, sequence),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id)
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
            CREATE TABLE IF NOT EXISTS campaign_quests (
                campaign_id TEXT NOT NULL,
                id TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                milestones TEXT NOT NULL,
                completed TEXT NOT NULL,
                PRIMARY KEY (campaign_id, id),
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS campaign_factions (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                stance TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS campaign_npcs (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                faction_id TEXT NOT NULL,
                disposition INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
                FOREIGN KEY (faction_id) REFERENCES campaign_factions(id)
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
                FOREIGN KEY (campaign_id, character_id)
                    REFERENCES campaign_characters(campaign_id, id)
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
                FOREIGN KEY (campaign_id, character_id)
                    REFERENCES campaign_characters(campaign_id, id)
            );
            CREATE TABLE IF NOT EXISTS campaign_sessions (
                campaign_id TEXT NOT NULL,
                id TEXT NOT NULL,
                starts_at TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                agenda TEXT NOT NULL,
                PRIMARY KEY (campaign_id, id),
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS campaign_session_attendance (
                campaign_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                present TEXT NOT NULL,
                absent TEXT NOT NULL,
                PRIMARY KEY (campaign_id, session_id),
                FOREIGN KEY (campaign_id, session_id)
                    REFERENCES campaign_sessions(campaign_id, id)
            );
            """
        )
        play_campaign_columns = {
            row["name"] for row in database.execute("PRAGMA table_info(play_campaigns)")
        }
        if "phase" not in play_campaign_columns:
            database.execute(
                "ALTER TABLE play_campaigns "
                "ADD COLUMN phase TEXT NOT NULL DEFAULT 'exploration'"
            )
        encounter_columns = {
            row["name"] for row in database.execute("PRAGMA table_info(play_campaign_encounters)")
        }
        if "combat_round" not in encounter_columns:
            database.execute(
                "ALTER TABLE play_campaign_encounters "
                "ADD COLUMN combat_round INTEGER NOT NULL DEFAULT 1"
            )
        if "turn_index" not in encounter_columns:
            database.execute(
                "ALTER TABLE play_campaign_encounters "
                "ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0"
            )
        member_columns = {
            row["name"]
            for row in database.execute("PRAGMA table_info(play_campaign_members)")
        }
        if "hp_current" not in member_columns:
            database.execute(
                "ALTER TABLE play_campaign_members "
                "ADD COLUMN hp_current INTEGER NOT NULL DEFAULT 20"
            )
        if "hp_max" not in member_columns:
            database.execute(
                "ALTER TABLE play_campaign_members "
                "ADD COLUMN hp_max INTEGER NOT NULL DEFAULT 20"
            )
        if "level" not in member_columns:
            database.execute(
                "ALTER TABLE play_campaign_members "
                "ADD COLUMN level INTEGER NOT NULL DEFAULT 1"
            )
        if "con_modifier" not in member_columns:
            database.execute(
                "ALTER TABLE play_campaign_members "
                "ADD COLUMN con_modifier INTEGER NOT NULL DEFAULT 0"
            )
        if "character_class" not in member_columns:
            database.execute(
                "ALTER TABLE play_campaign_members "
                "ADD COLUMN character_class TEXT NOT NULL DEFAULT ''"
            )
        if "abilities" not in member_columns:
            database.execute(
                "ALTER TABLE play_campaign_members "
                "ADD COLUMN abilities TEXT NOT NULL DEFAULT '{}'"
            )
        if "death_save_successes" not in member_columns:
            database.execute(
                "ALTER TABLE play_campaign_members "
                "ADD COLUMN death_save_successes INTEGER NOT NULL DEFAULT 0"
            )
        if "death_save_failures" not in member_columns:
            database.execute(
                "ALTER TABLE play_campaign_members "
                "ADD COLUMN death_save_failures INTEGER NOT NULL DEFAULT 0"
            )
        if "status" not in member_columns:
            database.execute(
                "ALTER TABLE play_campaign_members "
                "ADD COLUMN status TEXT NOT NULL DEFAULT 'conscious'"
            )
        quest_columns = {
            row["name"] for row in database.execute("PRAGMA table_info(play_campaign_quests)")
        }
        if "rewards" not in quest_columns:
            database.execute("ALTER TABLE play_campaign_quests ADD COLUMN rewards TEXT")
        if "rewards_awarded" not in quest_columns:
            database.execute(
                "ALTER TABLE play_campaign_quests "
                "ADD COLUMN rewards_awarded INTEGER NOT NULL DEFAULT 0"
            )
        # Before ownership became an explicit concern, the membership username
        # was the only durable character/player link.  Preserve that meaning
        # for all existing campaigns while allowing a future unowned record to
        # be claimed atomically.
        database.execute(
            """
            INSERT OR IGNORE INTO play_campaign_character_owners
                (campaign_id, character_id, owner)
            SELECT campaign_id, character_id, username FROM play_campaign_members
            """
        )
        database.execute(
            "INSERT OR REPLACE INTO storage_metadata (key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )


def is_initialized():
    if not DATABASE_PATH.exists():
        return False
    try:
        with connection() as database:
            row = database.execute(
                "SELECT value FROM storage_metadata WHERE key = ?", ("schema_version",)
            ).fetchone()
    except sqlite3.DatabaseError:
        return False
    return row is not None and row["value"] == str(SCHEMA_VERSION)


def reset():
    initialize()
    with connection() as database:
        for table in RESET_TABLES:
            database.execute(f"DELETE FROM {table}")
        database.execute(
            "INSERT OR REPLACE INTO storage_metadata (key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )


def get_user(username):
    with connection() as database:
        return database.execute(
            "SELECT username, password, role FROM users WHERE username = ?", (username,)
        ).fetchone()


def create_user(username, password, role):
    try:
        with connection() as database:
            database.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                (username, password, role),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def get_combat_session(session_id):
    with connection() as database:
        row = database.execute(
            "SELECT state FROM combat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return None if row is None else decode_json(row["state"])


def create_combat_session(session):
    try:
        with connection() as database:
            database.execute(
                "INSERT INTO combat_sessions (id, state) VALUES (?, ?)",
                (session["id"], encode_json(session)),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def save_combat_session(session):
    with connection() as database:
        database.execute(
            "UPDATE combat_sessions SET state = ? WHERE id = ?",
            (encode_json(session), session["id"]),
        )


def create_monster(monster):
    try:
        with connection() as database:
            database.execute(
                """
                INSERT INTO compendium_monsters
                    (slug, name, cr, armor_class, hit_points, tags)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    monster["slug"],
                    monster["name"],
                    monster["cr"],
                    monster["armor_class"],
                    monster["hit_points"],
                    encode_json(monster["tags"]),
                ),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def get_monster(slug):
    with connection() as database:
        row = database.execute(
            """
            SELECT slug, name, cr, armor_class, hit_points, tags
            FROM compendium_monsters WHERE slug = ?
            """,
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
        "tags": decode_json(row["tags"]),
    }


def create_item(item):
    try:
        with connection() as database:
            database.execute(
                """
                INSERT INTO compendium_items (slug, name, type, rarity, cost_gp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (item["slug"], item["name"], item["type"], item["rarity"], item["cost_gp"]),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def get_item(slug):
    with connection() as database:
        row = database.execute(
            """
            SELECT slug, name, type, rarity, cost_gp
            FROM compendium_items WHERE slug = ?
            """,
            (slug,),
        ).fetchone()
    return None if row is None else dict(row)


def create_campaign(campaign):
    try:
        with connection() as database:
            database.execute(
                "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
                (campaign["id"], campaign["name"], campaign["dm"]),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def create_play_campaign(campaign):
    try:
        with connection() as database:
            database.execute(
                """
                INSERT INTO play_campaigns (id, name, owner, status, max_players)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    campaign["id"],
                    campaign["name"],
                    campaign["owner"],
                    campaign["status"],
                    campaign["max_players"],
                ),
            )
            database.execute(
                "INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) "
                "VALUES (?, '', '')",
                (campaign["id"],),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def create_play_campaign_spectator(campaign_id, owner, spectator_id):
    """Create a globally-addressable spectator ticket for its campaign owner."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign"
        if campaign["owner"] != owner:
            return "not_owner"
        try:
            database.execute(
                "INSERT INTO play_campaign_spectators (spectator_id, campaign_id) VALUES (?, ?)",
                (spectator_id, campaign_id),
            )
        except sqlite3.IntegrityError:
            return "duplicate"
    return "created"


def get_play_campaign_spectator_view(campaign_id, spectator_id):
    """Return the intentionally small, non-mutating spectator projection."""
    with connection() as database:
        campaign = database.execute(
            "SELECT id, name, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        ticket = database.execute(
            "SELECT campaign_id FROM play_campaign_spectators WHERE spectator_id = ?",
            (spectator_id,),
        ).fetchone()
        if ticket is None:
            return "invalid_ticket", None
        if ticket["campaign_id"] != campaign_id:
            return "wrong_campaign", None
        party_size = database.execute(
            "SELECT COUNT(*) AS count FROM play_campaign_members WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["count"]
        document = database.execute(
            "SELECT story FROM play_campaign_documents WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
    return "found", {
        "campaign_id": campaign["id"],
        "name": campaign["name"],
        "status": campaign["status"],
        "party_size": party_size,
        "story": "" if document is None else document["story"],
    }


def append_play_campaign_feed_event(campaign_id, actor, event_id, text):
    """Append one member-authored feed event in a serialized transaction."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if campaign["owner"] != actor and member is None:
            return "not_member", None
        duplicate = database.execute(
            "SELECT 1 FROM play_campaign_feed_events WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if duplicate is not None:
            return "duplicate", None
        sequence = database.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence "
            "FROM play_campaign_feed_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["sequence"]
        database.execute(
            "INSERT INTO play_campaign_feed_events (campaign_id, event_id, text, sequence) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, event_id, text, sequence),
        )
    return "created", {"event_id": event_id, "text": text, "sequence": sequence}


def get_play_campaign_feed_events(campaign_id, actor, cursor, limit):
    """Read a non-mutating, offset-based page of the append-only feed."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if campaign["owner"] != actor and member is None:
            return "not_member", None
        rows = database.execute(
            """
            SELECT event_id, text, sequence FROM play_campaign_feed_events
            WHERE campaign_id = ?
            ORDER BY sequence ASC
            LIMIT ? OFFSET ?
            """,
            (campaign_id, limit, cursor),
        ).fetchall()
    events = [dict(row) for row in rows]
    return "found", {"events": events, "next_cursor": cursor + len(events)}


def play_campaign_exists(campaign_id):
    """Return whether a play campaign exists, without applying role rules."""
    with connection() as database:
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
    return campaign is not None


def check_play_campaign_access(campaign_id, username):
    """Check the normal DM-or-member gate without exposing campaign data."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign"
        if campaign["owner"] == username:
            return "allowed"
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
    return "allowed" if member is not None else "not_member"


def create_play_campaign_audit_event(campaign_id, actor, kind, correlation_id):
    """Append one immutable member-created audit entry atomically."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] == actor:
            role = "DM"
        elif database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone() is not None:
            role = "player"
        else:
            return "not_member", None
        if database.execute(
            "SELECT 1 FROM play_campaign_audit_events WHERE campaign_id = ? AND correlation_id = ?",
            (campaign_id, correlation_id),
        ).fetchone() is not None:
            return "duplicate_correlation_id", None
        timestamp = database.execute(
            "SELECT COALESCE(MAX(timestamp), 0) + 1 AS timestamp "
            "FROM play_campaign_audit_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["timestamp"]
        entry = {
            "kind": kind,
            "actor": actor,
            "role": role,
            "timestamp": timestamp,
            "correlation_id": correlation_id,
        }
        database.execute(
            """
            INSERT INTO play_campaign_audit_events
                (campaign_id, timestamp, kind, actor, role, correlation_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (campaign_id, timestamp, kind, actor, role, correlation_id),
        )
    return "created", entry


def get_play_campaign_audit_events(campaign_id, actor):
    """Read an owner's immutable audit trail in timestamp order."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != actor:
            return "not_owner", None
        rows = database.execute(
            """
            SELECT kind, actor, role, timestamp, correlation_id
            FROM play_campaign_audit_events WHERE campaign_id = ?
            ORDER BY timestamp ASC
            """,
            (campaign_id,),
        ).fetchall()
    return "found", [dict(row) for row in rows]


def _projection_from_events(rows):
    """Build the complete projection solely from its immutable event log."""
    projection = {"story": "", "danger": 0, "applied_event_ids": []}
    for row in rows:
        projection["applied_event_ids"].append(row["event_id"])
        if row["kind"] == "set-story":
            projection["story"] = row["value"]
        else:
            projection["danger"] += 1
    return projection


def create_play_campaign_projection_event(campaign_id, actor, event):
    """Append a player-only immutable projection event in sequence order."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] == actor:
            return "not_member", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if member is None:
            return "not_member", None
        duplicate = database.execute(
            "SELECT 1 FROM play_campaign_projection_events "
            "WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event["event_id"]),
        ).fetchone()
        if duplicate is not None:
            return "duplicate_event_id", None
        sequence = database.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence "
            "FROM play_campaign_projection_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["sequence"]
        stored_event = {"sequence": sequence, **event}
        database.execute(
            """
            INSERT INTO play_campaign_projection_events
                (campaign_id, sequence, event_id, kind, value)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                sequence,
                event["event_id"],
                event["kind"],
                event.get("value"),
            ),
        )
    return "created", stored_event


def get_play_campaign_projection(campaign_id, actor):
    """Authorize a campaign participant and deterministically rebuild its projection."""
    with connection() as database:
        result, _, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        rows = database.execute(
            """
            SELECT event_id, kind, value
            FROM play_campaign_projection_events
            WHERE campaign_id = ?
            ORDER BY sequence ASC
            """,
            (campaign_id,),
        ).fetchall()
    return "found", _projection_from_events(rows)


def create_play_campaign_replay_event(campaign_id, actor, event):
    """Append an immutable replay event for any campaign participant."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        result, _, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        duplicate = database.execute(
            "SELECT 1 FROM play_campaign_replay_events "
            "WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event["event_id"]),
        ).fetchone()
        if duplicate is not None:
            return "duplicate_event_id", None
        sequence = database.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence "
            "FROM play_campaign_replay_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["sequence"]
        stored_event = {"event_id": event["event_id"], "kind": "append",
                        "text": event["text"], "sequence": sequence}
        database.execute(
            """
            INSERT INTO play_campaign_replay_events
                (campaign_id, sequence, event_id, text)
            VALUES (?, ?, ?, ?)
            """,
            (campaign_id, sequence, event["event_id"], event["text"]),
        )
    return "created", stored_event


def get_play_campaign_replay(campaign_id, actor):
    """Rebuild the public replay state in immutable append order."""
    with connection() as database:
        result, _, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        rows = database.execute(
            """
            SELECT event_id, text FROM play_campaign_replay_events
            WHERE campaign_id = ? ORDER BY sequence ASC
            """,
            (campaign_id,),
        ).fetchall()
    event_ids = [row["event_id"] for row in rows]
    story = "".join(row["text"] for row in rows)
    return "found", {
        "story": story,
        "event_ids": event_ids,
        "digest": f"{','.join(event_ids)}|{story}",
    }


def set_play_campaign_rng_seed(campaign_id, actor, seed):
    """Configure the one immutable deterministic RNG seed for a campaign."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != actor:
            return "not_owner", None
        existing = database.execute(
            "SELECT 1 FROM play_campaign_rng_seeds WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
        if existing is not None:
            return "seed_exists", None
        database.execute(
            "INSERT INTO play_campaign_rng_seeds (campaign_id, seed) VALUES (?, ?)",
            (campaign_id, seed),
        )
    return "configured", {"seed": seed, "rolls": []}


def _rng_result(seed, sequence, roll_id, sides):
    """Compute the specified UTF-8, uint32 deterministic die result."""
    accumulator = 0
    source = f"{seed}|{sequence}|{roll_id}|{sides}".encode("utf-8")
    for byte in source:
        accumulator = (accumulator * 31 + byte) & 0xFFFFFFFF
    return accumulator % sides + 1


def append_play_campaign_rng_roll(campaign_id, actor, roll_id, sides):
    """Atomically append one immutable, campaign-sequenced RNG roll."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        result, _, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        seed_row = database.execute(
            "SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
        if seed_row is None:
            return "seed_missing", None
        duplicate = database.execute(
            "SELECT 1 FROM play_campaign_rng_rolls WHERE campaign_id = ? AND roll_id = ?",
            (campaign_id, roll_id),
        ).fetchone()
        if duplicate is not None:
            return "duplicate_roll_id", None
        sequence = database.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence "
            "FROM play_campaign_rng_rolls WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["sequence"]
        roll = {
            "roll_id": roll_id,
            "sides": sides,
            "result": _rng_result(seed_row["seed"], sequence, roll_id, sides),
            "sequence": sequence,
        }
        database.execute(
            """
            INSERT INTO play_campaign_rng_rolls
                (campaign_id, sequence, roll_id, sides, result)
            VALUES (?, ?, ?, ?, ?)
            """,
            (campaign_id, sequence, roll_id, sides, roll["result"]),
        )
    return "created", roll


def get_play_campaign_rng_ledger(campaign_id, actor):
    """Return the seed and all immutable rolls in their append order."""
    with connection() as database:
        result, _, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        seed_row = database.execute(
            "SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
        rows = database.execute(
            """
            SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls
            WHERE campaign_id = ? ORDER BY sequence ASC
            """,
            (campaign_id,),
        ).fetchall()
    return "found", {
        "seed": None if seed_row is None else seed_row["seed"],
        "rolls": [dict(row) for row in rows],
    }


def create_play_campaign_moderation_report(campaign_id, actor, report):
    """Atomically append one immutable open moderation report."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        result, _, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        duplicate = database.execute(
            "SELECT 1 FROM play_campaign_moderation_reports "
            "WHERE campaign_id = ? AND report_id = ?",
            (campaign_id, report["report_id"]),
        ).fetchone()
        if duplicate is not None:
            return "duplicate_report_id", None
        sequence = database.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence "
            "FROM play_campaign_moderation_reports WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["sequence"]
        stored = {
            "report_id": report["report_id"],
            "target_id": report["target_id"],
            "reason": report["reason"],
            "status": "open",
            "reporter": actor,
            "sequence": sequence,
        }
        database.execute(
            """
            INSERT INTO play_campaign_moderation_reports
                (campaign_id, sequence, report_id, target_id, reason, status, reporter)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (campaign_id, sequence, stored["report_id"], stored["target_id"],
             stored["reason"], stored["status"], stored["reporter"]),
        )
    return "created", stored


def get_play_campaign_moderation_reports(campaign_id, actor):
    """Read moderation reports in their stable, per-campaign append order."""
    with connection() as database:
        result, _, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        rows = database.execute(
            """
            SELECT report_id, target_id, reason, status, reporter, sequence,
                   action, note, resolver
            FROM play_campaign_moderation_reports
            WHERE campaign_id = ? ORDER BY sequence ASC
            """,
            (campaign_id,),
        ).fetchall()
    reports = []
    for row in rows:
        report = {
            "report_id": row["report_id"], "target_id": row["target_id"],
            "reason": row["reason"], "status": row["status"],
            "reporter": row["reporter"], "sequence": row["sequence"],
        }
        if row["status"] == "resolved":
            report.update({"action": row["action"], "note": row["note"],
                           "resolver": row["resolver"]})
        reports.append(report)
    return "found", reports


def replace_play_campaign_safety_boundaries(campaign_id, actor, blocked_tags):
    """Atomically replace the owner's campaign-scoped blocked-tag list."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != actor:
            return "not_owner", None
        database.execute(
            """
            INSERT INTO play_campaign_safety_boundaries (campaign_id, blocked_tags)
            VALUES (?, ?)
            ON CONFLICT(campaign_id) DO UPDATE SET blocked_tags = excluded.blocked_tags
            """,
            (campaign_id, encode_json(blocked_tags)),
        )
    return "replaced", {"blocked_tags": blocked_tags}


def get_play_campaign_safety_boundaries(campaign_id, actor):
    """Return a member-visible campaign's current boundaries, defaulting empty."""
    with connection() as database:
        result, _, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        row = database.execute(
            "SELECT blocked_tags FROM play_campaign_safety_boundaries WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    return "found", {"blocked_tags": [] if row is None else decode_json(row["blocked_tags"])}


def submit_play_campaign_safety_check(campaign_id, actor, event):
    """Accept one unblocked safety event in stable per-campaign sequence order."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        result, _, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        if database.execute(
            "SELECT 1 FROM play_campaign_safety_events WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event["event_id"]),
        ).fetchone() is not None:
            return "duplicate_event_id", None
        boundary = database.execute(
            "SELECT blocked_tags FROM play_campaign_safety_boundaries WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        blocked_tags = set() if boundary is None else set(decode_json(boundary["blocked_tags"]))
        if blocked_tags.intersection(event["tags"]):
            return "blocked_tag", None
        sequence = database.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence "
            "FROM play_campaign_safety_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["sequence"]
        accepted = {
            "event_id": event["event_id"], "kind": event["kind"],
            "text": event["text"], "tags": event["tags"], "sequence": sequence,
        }
        database.execute(
            """
            INSERT INTO play_campaign_safety_events
                (campaign_id, sequence, event_id, kind, text, tags)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (campaign_id, sequence, accepted["event_id"], accepted["kind"],
             accepted["text"], encode_json(accepted["tags"])),
        )
    return "created", accepted


def get_play_campaign_safety_events(campaign_id, actor):
    """Return accepted safety checks in their immutable append order."""
    with connection() as database:
        result, _, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        rows = database.execute(
            """
            SELECT event_id, kind, text, tags, sequence
            FROM play_campaign_safety_events WHERE campaign_id = ?
            ORDER BY sequence ASC
            """,
            (campaign_id,),
        ).fetchall()
    return "found", {"events": [{
        "event_id": row["event_id"], "kind": row["kind"], "text": row["text"],
        "tags": decode_json(row["tags"]), "sequence": row["sequence"],
    } for row in rows]}


def resolve_play_campaign_moderation_report(campaign_id, actor, report_id, resolution):
    """Perform the report's sole permitted state transition, open to resolved."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != actor:
            return "not_owner", None
        row = database.execute(
            """
            SELECT report_id, target_id, reason, status, reporter, sequence
            FROM play_campaign_moderation_reports
            WHERE campaign_id = ? AND report_id = ?
            """,
            (campaign_id, report_id),
        ).fetchone()
        if row is None:
            return "unknown_report", None
        if row["status"] != "open":
            return "already_resolved", None
        database.execute(
            """
            UPDATE play_campaign_moderation_reports
            SET status = 'resolved', action = ?, note = ?, resolver = ?
            WHERE campaign_id = ? AND report_id = ? AND status = 'open'
            """,
            (resolution["action"], resolution["note"], actor, campaign_id, report_id),
        )
        resolved = {
            "report_id": row["report_id"], "target_id": row["target_id"],
            "reason": row["reason"], "status": "resolved",
            "reporter": row["reporter"], "sequence": row["sequence"],
            "action": resolution["action"], "note": resolution["note"],
            "resolver": actor,
        }
    return "resolved", resolved


def create_play_campaign_idempotent_event(campaign_id, actor, event):
    """Store one immutable event, replaying an identical keyed request."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        result, _, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None

        keyed_event = database.execute(
            """
            SELECT event_id, value, sequence, idempotency_key
            FROM play_campaign_idempotent_events
            WHERE campaign_id = ? AND idempotency_key = ?
            """,
            (campaign_id, event["idempotency_key"]),
        ).fetchone()
        if keyed_event is not None:
            stored_event = dict(keyed_event)
            if (stored_event["event_id"] != event["event_id"]
                    or stored_event["value"] != event["value"]):
                return "key_conflict", None
            return "replayed", stored_event

        if database.execute(
            """
            SELECT 1 FROM play_campaign_idempotent_events
            WHERE campaign_id = ? AND event_id = ?
            """,
            (campaign_id, event["event_id"]),
        ).fetchone() is not None:
            return "event_id_conflict", None

        sequence = database.execute(
            """
            SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence
            FROM play_campaign_idempotent_events WHERE campaign_id = ?
            """,
            (campaign_id,),
        ).fetchone()["sequence"]
        stored_event = {
            "event_id": event["event_id"],
            "value": event["value"],
            "sequence": sequence,
            "idempotency_key": event["idempotency_key"],
        }
        database.execute(
            """
            INSERT INTO play_campaign_idempotent_events
                (campaign_id, sequence, event_id, value, idempotency_key)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                sequence,
                stored_event["event_id"],
                stored_event["value"],
                stored_event["idempotency_key"],
            ),
        )
    return "created", stored_event


def get_play_campaign_idempotent_events(campaign_id, actor):
    """Read a campaign's idempotent-event log in immutable sequence order."""
    with connection() as database:
        result, _, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        rows = database.execute(
            """
            SELECT event_id, value, sequence, idempotency_key
            FROM play_campaign_idempotent_events
            WHERE campaign_id = ? ORDER BY sequence ASC
            """,
            (campaign_id,),
        ).fetchall()
    return "found", {"events": [dict(row) for row in rows]}


def submit_play_campaign_safe_turn(campaign_id, actor, submission):
    """Accept one expected turn atomically, leaving stale attempts untouched."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if campaign["owner"] != actor and member is None:
            return "not_member", None
        if database.execute(
            "SELECT 1 FROM play_campaign_safe_turns WHERE campaign_id = ? AND submission_id = ?",
            (campaign_id, submission["submission_id"]),
        ).fetchone() is not None:
            return "duplicate_submission_id", None

        state = database.execute(
            "SELECT current_turn FROM play_campaign_safe_turn_state WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        current_turn = 1 if state is None else state["current_turn"]
        if submission["expected_turn"] != current_turn:
            return "stale_turn", {"current_turn": current_turn}

        accepted = {
            "submission_id": submission["submission_id"],
            "action": submission["action"],
            "accepted_turn": current_turn,
            "next_turn": current_turn + 1,
        }
        database.execute(
            """
            INSERT INTO play_campaign_safe_turns
            (campaign_id, submission_id, action, accepted_turn, next_turn)
            VALUES (?, ?, ?, ?, ?)
            """,
            (campaign_id, accepted["submission_id"], accepted["action"],
             accepted["accepted_turn"], accepted["next_turn"]),
        )
        if state is None:
            database.execute(
                "INSERT INTO play_campaign_safe_turn_state (campaign_id, current_turn) VALUES (?, ?)",
                (campaign_id, accepted["next_turn"]),
            )
        else:
            database.execute(
                "UPDATE play_campaign_safe_turn_state SET current_turn = ? WHERE campaign_id = ?",
                (accepted["next_turn"], campaign_id),
            )
    return "created", accepted


def get_play_campaign_safe_turns(campaign_id, actor):
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if campaign["owner"] != actor and member is None:
            return "not_member", None
        state = database.execute(
            "SELECT current_turn FROM play_campaign_safe_turn_state WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        rows = database.execute(
            """
            SELECT submission_id, action, accepted_turn, next_turn
            FROM play_campaign_safe_turns WHERE campaign_id = ?
            ORDER BY accepted_turn
            """,
            (campaign_id,),
        ).fetchall()
    return "found", {
        "current_turn": 1 if state is None else state["current_turn"],
        "accepted": [dict(row) for row in rows],
    }


def set_play_campaign_session_zero_settings(campaign_id, owner, settings):
    """Store session-zero settings only for a lobby campaign's DM."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        if campaign["status"] != "lobby":
            return "not_lobby", None
        database.execute(
            """
            INSERT INTO play_campaign_session_zero_settings (campaign_id, rules, tone, consent)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(campaign_id) DO UPDATE SET
                rules = excluded.rules,
                tone = excluded.tone,
                consent = excluded.consent
            """,
            (campaign_id, settings["rules"], settings["tone"], encode_json(settings["consent"])),
        )
    return "updated", settings


def get_play_campaign_session_zero_settings(campaign_id, username):
    """Read session-zero settings for the campaign DM or a joined player."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != username:
            membership = database.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
            ).fetchone()
            if membership is None:
                return "not_member", None
        row = database.execute(
            """
            SELECT rules, tone, consent FROM play_campaign_session_zero_settings
            WHERE campaign_id = ?
            """,
            (campaign_id,),
        ).fetchone()
    if row is None:
        return "missing_settings", None
    return "found", {"rules": row["rules"], "tone": row["tone"], "consent": decode_json(row["consent"])}


def create_play_campaign_content(campaign_id, owner, content):
    """Create one DM-owned content record in insertion order."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        try:
            database.execute(
                """
                INSERT INTO play_campaign_content (campaign_id, content_id, kind, text, tags)
                VALUES (?, ?, ?, ?, ?)
                """,
                (campaign_id, content["content_id"], content["kind"], content["text"],
                 encode_json(content["tags"])),
            )
        except sqlite3.IntegrityError:
            return "duplicate", None
    return "created", content


def replace_play_campaign_content_tags(campaign_id, owner, content_id, tags):
    """Replace a content record's tags, retaining its other fields."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        content = database.execute(
            """SELECT content_id, kind, text FROM play_campaign_content
               WHERE campaign_id = ? AND content_id = ?""",
            (campaign_id, content_id),
        ).fetchone()
        if content is None:
            return "unknown_content", None
        database.execute(
            """UPDATE play_campaign_content SET tags = ?
               WHERE campaign_id = ? AND content_id = ?""",
            (encode_json(tags), campaign_id, content_id),
        )
    return "updated", {
        "content_id": content["content_id"], "kind": content["kind"],
        "text": content["text"], "tags": tags,
    }


def get_play_campaign_content(campaign_id, actor, exclude_tag=None):
    """Return campaign content to its DM or a joined player."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if actor != campaign["owner"] and member is None:
            return "not_member", None
        rows = database.execute(
            """SELECT content_id, kind, text, tags FROM play_campaign_content
               WHERE campaign_id = ? ORDER BY rowid""",
            (campaign_id,),
        ).fetchall()
    content = [{
        "content_id": row["content_id"], "kind": row["kind"], "text": row["text"],
        "tags": decode_json(row["tags"]),
    } for row in rows]
    if exclude_tag is not None and actor != campaign["owner"]:
        content = [record for record in content if exclude_tag not in record["tags"]]
    return "found", {"content": content}


def _play_campaign_access(database, campaign_id, actor):
    """Return the campaign and actor membership, or a stable access result."""
    campaign = database.execute(
        "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if campaign is None:
        return "unknown_campaign", None, None
    member = database.execute(
        "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
        (campaign_id, actor),
    ).fetchone()
    if actor != campaign["owner"] and member is None:
        return "not_member", None, None
    return "found", campaign, member


def seed_play_campaign_fixture(campaign_id, actor):
    """Create the single deterministic fixture for an owner-controlled campaign."""
    fixture = {
        "fixture_id": "canonical-v1",
        "status": "seeded",
        "characters": [
            {"character_id": "fixture-hero", "name": "Ari", "class": "fighter"},
            {"character_id": "fixture-mage", "name": "Bea", "class": "wizard"},
        ],
        "story": "The lantern is lit.",
        "event_ids": ["fixture-event-1", "fixture-event-2"],
    }
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != actor:
            return "not_owner", None
        row = database.execute(
            "SELECT state FROM play_campaign_fixture_states WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if row is not None:
            return "existing", decode_json(row["state"])
        database.execute(
            "INSERT INTO play_campaign_fixture_states (campaign_id, state) VALUES (?, ?)",
            (campaign_id, encode_json(fixture)),
        )
    return "seeded", fixture


def get_play_campaign_fixture(campaign_id, actor):
    """Read a seeded fixture when the actor belongs to its campaign."""
    with connection() as database:
        result, _, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        row = database.execute(
            "SELECT state FROM play_campaign_fixture_states WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    if row is None:
        return "missing", None
    return "found", decode_json(row["state"])


def create_play_campaign_search_record(campaign_id, actor, record):
    """Store one owner-authored search record in insertion order."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != actor:
                return "not_owner", None
            existing = database.execute(
                """SELECT 1 FROM play_campaign_search_records
                   WHERE campaign_id = ? AND text = ?""",
                (campaign_id, record["text"]),
            ).fetchone()
            if existing is not None:
                return "duplicate", None
            database.execute(
                """INSERT INTO play_campaign_search_records (campaign_id, record_id, text)
                   VALUES (?, ?, ?)""",
                (campaign_id, record["record_id"], record["text"]),
            )
    except sqlite3.IntegrityError:
        return "duplicate", None
    return "created", record


def get_play_campaign_search_records(campaign_id, actor, query, limit, cursor):
    """Read the stable, filtered slice of a campaign's search records."""
    with connection() as database:
        result, _, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        rows = database.execute(
            """SELECT record_id, text FROM play_campaign_search_records
               WHERE campaign_id = ? ORDER BY creation_order""",
            (campaign_id,),
        ).fetchall()
    records = [dict(row) for row in rows]
    if query is not None:
        folded_query = query.casefold()
        records = [record for record in records if folded_query in record["text"].casefold()]
    page = records[cursor:cursor + limit]
    next_cursor = cursor + limit if cursor + limit < len(records) else None
    return "found", {"records": page, "next_cursor": next_cursor}


def create_play_campaign_rate_event(campaign_id, actor, event_id):
    """Accept one member rate event when that member has allowance remaining."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            result, _, _ = _play_campaign_access(database, campaign_id, actor)
            if result != "found":
                return result, None
            if database.execute(
                "SELECT 1 FROM play_campaign_rate_events "
                "WHERE campaign_id = ? AND event_id = ?",
                (campaign_id, event_id),
            ).fetchone() is not None:
                return "duplicate_event_id", None
            accepted = database.execute(
                "SELECT COUNT(*) AS count FROM play_campaign_rate_events "
                "WHERE campaign_id = ? AND actor = ?",
                (campaign_id, actor),
            ).fetchone()["count"]
            if accepted >= 2:
                database.execute(
                    """
                    INSERT INTO play_campaign_service_metrics
                        (campaign_id, rejected_rate_events)
                    VALUES (?, 1)
                    ON CONFLICT(campaign_id) DO UPDATE SET
                        rejected_rate_events = rejected_rate_events + 1
                    """,
                    (campaign_id,),
                )
                return "rate_limited", None
            database.execute(
                "INSERT INTO play_campaign_rate_events (campaign_id, event_id, actor) "
                "VALUES (?, ?, ?)",
                (campaign_id, event_id, actor),
            )
    except sqlite3.IntegrityError:
        return "duplicate_event_id", None
    return "created", {"event_id": event_id, "actor": actor, "remaining": 1 - accepted}


def get_play_campaign_rate_events(campaign_id, actor):
    """Return accepted events in order and the caller's independent balance."""
    with connection() as database:
        result, _, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        rows = database.execute(
            "SELECT event_id, actor FROM play_campaign_rate_events "
            "WHERE campaign_id = ? ORDER BY creation_order",
            (campaign_id,),
        ).fetchall()
        accepted = database.execute(
            "SELECT COUNT(*) AS count FROM play_campaign_rate_events "
            "WHERE campaign_id = ? AND actor = ?",
            (campaign_id, actor),
        ).fetchone()["count"]
    return "found", {"events": [dict(row) for row in rows], "remaining": max(0, 2 - accepted)}


def get_play_campaign_service_metrics(campaign_id, actor):
    """Return only an owner's safe, aggregate service counters."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != actor:
            return "not_owner", None
        accepted_rate_events = database.execute(
            "SELECT COUNT(*) AS count FROM play_campaign_rate_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["count"]
        projection_events = database.execute(
            "SELECT COUNT(*) AS count FROM play_campaign_projection_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["count"]
        metrics = database.execute(
            "SELECT rejected_rate_events FROM play_campaign_service_metrics WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    return "found", {
        "accepted_rate_events": accepted_rate_events,
        "rejected_rate_events": 0 if metrics is None else metrics["rejected_rate_events"],
        "projection_events": projection_events,
        "uptime_ticks": 1,
    }


def create_play_campaign_note(campaign_id, actor, note):
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        result, _, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        try:
            database.execute(
                """INSERT INTO play_campaign_notes (campaign_id, note_id, text, visibility, owner)
                   VALUES (?, ?, ?, ?, ?)""",
                (campaign_id, note["note_id"], note["text"], note["visibility"], actor),
            )
        except sqlite3.IntegrityError:
            return "duplicate", None
    return "created", {**note, "owner": actor}


def get_play_campaign_notes(campaign_id, actor, note_id=None):
    with connection() as database:
        result, campaign, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        query = "SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ?"
        arguments = [campaign_id]
        if note_id is not None:
            query += " AND note_id = ?"
            arguments.append(note_id)
        query += " ORDER BY creation_order"
        rows = database.execute(query, arguments).fetchall()
    if note_id is not None and not rows:
        return "unknown_note", None
    notes = [dict(row) for row in rows]
    if actor != campaign["owner"]:
        notes = [note for note in notes if note["visibility"] == "party" or note["owner"] == actor]
    if note_id is not None:
        return ("found", notes[0]) if notes else ("not_readable", None)
    return "found", {"notes": notes}


def update_play_campaign_note(campaign_id, actor, note_id, changes):
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        result, _, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        row = database.execute(
            "SELECT owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?",
            (campaign_id, note_id),
        ).fetchone()
        if row is None:
            return "unknown_note", None
        if row["owner"] != actor:
            return "not_owner", None
        database.execute(
            """UPDATE play_campaign_notes SET text = ?, visibility = ?
               WHERE campaign_id = ? AND note_id = ?""",
            (changes["text"], changes["visibility"], campaign_id, note_id),
        )
    return "updated", {"note_id": note_id, **changes, "owner": actor}


def create_play_campaign_whisper(campaign_id, actor, whisper):
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        result, _, member = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        if member is None:
            return "no_owned_character", None
        sender = database.execute(
            """SELECT 1 FROM play_campaign_character_owners
               WHERE campaign_id = ? AND character_id = ? AND owner = ?""",
            (campaign_id, member["character_id"], actor),
        ).fetchone()
        if sender is None:
            return "no_owned_character", None
        recipient = database.execute(
            """SELECT 1 FROM play_campaign_members
               WHERE campaign_id = ? AND character_id = ?""",
            (campaign_id, whisper["to_character_id"]),
        ).fetchone()
        if recipient is None:
            return "invalid_recipient", None
        try:
            database.execute(
                """INSERT INTO play_campaign_whispers
                   (campaign_id, whisper_id, from_character_id, to_character_id, text)
                   VALUES (?, ?, ?, ?, ?)""",
                (campaign_id, whisper["whisper_id"], member["character_id"],
                 whisper["to_character_id"], whisper["text"]),
            )
        except sqlite3.IntegrityError:
            return "duplicate", None
    return "created", {"whisper_id": whisper["whisper_id"],
                       "from_character_id": member["character_id"], **whisper}


def get_play_campaign_whispers(campaign_id, actor):
    with connection() as database:
        result, campaign, member = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        rows = database.execute(
            """SELECT whisper_id, from_character_id, to_character_id, text
               FROM play_campaign_whispers WHERE campaign_id = ? ORDER BY creation_order""",
            (campaign_id,),
        ).fetchall()
        owned_character_ids = {
            row["character_id"] for row in database.execute(
                """SELECT character_id FROM play_campaign_character_owners
                   WHERE campaign_id = ? AND owner = ?""",
                (campaign_id, actor),
            ).fetchall()
        }
    whispers = [dict(row) for row in rows]
    if actor != campaign["owner"]:
        whispers = [whisper for whisper in whispers if owned_character_ids.intersection(
            (whisper["from_character_id"], whisper["to_character_id"])
        )]
    return "found", {"whispers": whispers}


def get_play_campaign_character_sheet(campaign_id, actor, character_id):
    with connection() as database:
        result, campaign, _ = _play_campaign_access(database, campaign_id, actor)
        if result != "found":
            return result, None
        character = database.execute(
            """SELECT m.character_id, m.name, m.class, m.level, o.owner
               FROM play_campaign_members AS m
               LEFT JOIN play_campaign_character_owners AS o
                 ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
               WHERE m.campaign_id = ? AND m.character_id = ?""",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        if actor != campaign["owner"] and character["owner"] != actor:
            return "not_readable", None
    # Sheets in this API are deliberately the stage's deterministic basic
    # projection.  They do not expose mutable progression state.
    return "found", {"character_id": character["character_id"], "owner": character["owner"],
                      "name": character["name"], "class": character["class"],
                      "level": 1, "proficiency_bonus": 2,
                      "hp_max": 10, "armor_class": 10}


def create_play_campaign_encounter(campaign_id, owner, encounter):
    """Start one active combat encounter without changing the exploration turn."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != owner:
                return "not_owner", None
            if campaign["status"] != "active":
                return "not_active", None
            database.execute(
                """
                INSERT INTO play_campaign_encounters (id, campaign_id, name, status)
                VALUES (?, ?, ?, 'active')
                """,
                (encounter["id"], campaign_id, encounter["name"]),
            )
            # The existing turn record remains the suspended exploration queue.
            database.execute(
                "UPDATE play_campaigns SET phase = 'combat' WHERE id = ?", (campaign_id,)
            )
    except sqlite3.IntegrityError:
        return "conflict", None
    return "created", {
        "id": encounter["id"],
        "name": encounter["name"],
        "status": "active",
        "combatants": [],
    }


def award_play_campaign_encounter_rewards(campaign_id, owner, encounter_id, reward):
    """Persist the single owner-authorized reward record for an encounter."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != owner:
                return "not_owner", None
            encounter = database.execute(
                "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
                (encounter_id, campaign_id),
            ).fetchone()
            if encounter is None:
                return "unknown_encounter", None
            database.execute(
                """
                INSERT INTO play_campaign_encounter_rewards (encounter_id, xp, loot)
                VALUES (?, ?, ?)
                """,
                (encounter_id, reward["xp"], encode_json(reward["loot"])),
            )
    except sqlite3.IntegrityError:
        return "already_awarded", None
    return "created", {
        "encounter_id": encounter_id,
        "xp": reward["xp"],
        "loot": reward["loot"],
    }


def close_play_campaign_encounter(campaign_id, owner, encounter_id):
    """Close an encounter while leaving combat-to-exploration to ``/end``."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        encounter = database.execute(
            "SELECT status FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return "unknown_encounter", None
        database.execute(
            """
            UPDATE play_campaign_encounters SET status = 'closed'
            WHERE id = ? AND campaign_id = ?
            """,
            (encounter_id, campaign_id),
        )
        reward = database.execute(
            "SELECT xp FROM play_campaign_encounter_rewards WHERE encounter_id = ?",
            (encounter_id,),
        ).fetchone()
    return "closed", {
        "id": encounter_id,
        "status": "closed",
        "xp_awarded": 0 if reward is None else reward["xp"],
    }


def end_play_campaign_encounter(campaign_id, owner, encounter_id):
    """Finish combat and return turn authority to the DM in exploration."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner, status, phase FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        if campaign["phase"] != "combat":
            return "not_in_combat", None

        encounter = database.execute(
            "SELECT status FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return "unknown_encounter", None
        turn = database.execute(
            "SELECT current_actor FROM play_campaign_turns WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if turn is None:
            return "not_active", None

        if encounter["status"] == "active":
            database.execute(
                "UPDATE play_campaign_encounters SET status = 'closed' WHERE id = ?",
                (encounter_id,),
            )
        database.execute(
            "UPDATE play_campaigns SET phase = 'exploration' WHERE id = ?", (campaign_id,)
        )
        # Combat is an interruption of the exploration exchange.  Its explicit
        # end is a DM-owned transition, so the next exploration authority is
        # deterministically the owner rather than the actor suspended when
        # combat was opened.
        database.execute(
            "UPDATE play_campaign_turns SET current_actor = ? WHERE campaign_id = ?",
            (campaign["owner"], campaign_id),
        )
    return "ended", {
        "campaign_id": campaign_id,
        "status": campaign["status"],
        "phase": "exploration",
        "current_actor": campaign["owner"],
    }


def add_play_campaign_encounter_monster(campaign_id, owner, encounter_id, monster):
    """Add a monster to an encounter after confirming campaign ownership."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != owner:
                return "not_owner", None
            encounter = database.execute(
                "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
                (encounter_id, campaign_id),
            ).fetchone()
            if encounter is None:
                return "unknown_encounter", None
            database.execute(
                """
                INSERT INTO play_campaign_encounter_monsters
                    (encounter_id, monster_id, name, hp_current, hp_max, initiative)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    encounter_id,
                    monster["monster_id"],
                    monster["name"],
                    monster["hp_current"],
                    monster["hp_max"],
                    monster["initiative"],
                ),
            )
    except sqlite3.IntegrityError:
        return "duplicate", None
    return "created", monster


def remove_play_campaign_encounter_monster(campaign_id, owner, encounter_id, monster_id):
    """Remove an encounter monster after confirming campaign ownership."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign"
        if campaign["owner"] != owner:
            return "not_owner"
        encounter = database.execute(
            "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return "unknown_encounter"
        deleted = database.execute(
            """
            DELETE FROM play_campaign_encounter_monsters
            WHERE encounter_id = ? AND monster_id = ?
            """,
            (encounter_id, monster_id),
        ).rowcount
    return "removed" if deleted else "unknown_monster"


def add_play_campaign_encounter_combatant(campaign_id, owner, encounter_id, member, initiative):
    """Bind a campaign party member to an encounter as a combatant."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != owner:
                return "not_owner", None
            encounter = database.execute(
                "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
                (encounter_id, campaign_id),
            ).fetchone()
            if encounter is None:
                return "unknown_encounter", None
            party_member = database.execute(
                """
                SELECT character_id, name FROM play_campaign_members
                WHERE campaign_id = ? AND username = ?
                """,
                (campaign_id, member),
            ).fetchone()
            if party_member is None:
                return "unknown_member", None
            combatant = {
                "member": member,
                "character_id": party_member["character_id"],
                "name": party_member["name"],
                "initiative": initiative,
            }
            database.execute(
                """
                INSERT INTO play_campaign_encounter_combatants
                    (encounter_id, member, character_id, name, initiative)
                VALUES (?, ?, ?, ?, ?)
                """,
                (encounter_id, member, combatant["character_id"], combatant["name"], initiative),
            )
    except sqlite3.IntegrityError:
        return "duplicate", None
    return "created", combatant


def remove_play_campaign_encounter_combatant(campaign_id, owner, encounter_id, member):
    """Unbind a party combatant after confirming campaign ownership."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign"
        if campaign["owner"] != owner:
            return "not_owner"
        encounter = database.execute(
            "SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?",
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return "unknown_encounter"
        deleted = database.execute(
            """
            DELETE FROM play_campaign_encounter_combatants
            WHERE encounter_id = ? AND member = ?
            """,
            (encounter_id, member),
        ).rowcount
    return "removed" if deleted else "unknown_member"


def _encounter_turn_order(database, encounter_id):
    """Return the stable combined monster/player initiative order for an encounter."""
    combatants = []
    for row in database.execute(
        """
        SELECT monster_id AS tie_id, name, initiative
        FROM play_campaign_encounter_monsters WHERE encounter_id = ?
        """,
        (encounter_id,),
    ):
        combatants.append({
            "name": row["name"], "kind": "monster", "initiative": row["initiative"],
            "tie_id": row["tie_id"], "member": None,
        })
    for row in database.execute(
        """
        SELECT member AS tie_id, member, name, initiative
        FROM play_campaign_encounter_combatants WHERE encounter_id = ?
        """,
        (encounter_id,),
    ):
        combatants.append({
            "name": row["name"], "kind": "player", "initiative": row["initiative"],
            "tie_id": row["tie_id"], "member": row["member"],
        })
    default_order = sorted(
        combatants,
        key=lambda item: (-item["initiative"], item["name"], item["kind"], item["tie_id"]),
    )
    positions = {
        row["tie_id"]: row["position"]
        for row in database.execute(
            "SELECT position, tie_id FROM play_campaign_encounter_turn_order "
            "WHERE encounter_id = ?",
            (encounter_id,),
        )
    }
    if not positions:
        return default_order
    by_id = {item["tie_id"]: item for item in default_order}
    ordered = [by_id[tie_id] for tie_id, _ in sorted(positions.items(), key=lambda item: item[1]) if tie_id in by_id]
    known_ids = {item["tie_id"] for item in ordered}
    return ordered + [item for item in default_order if item["tie_id"] not in known_ids]


def _encounter_turn_response(encounter, order):
    active = order[encounter["turn_index"] % len(order)]
    return {
        "round": encounter["combat_round"],
        "turn_index": encounter["turn_index"] % len(order),
        "active": {
            "name": active["name"],
            "kind": active["kind"],
            "initiative": active["initiative"],
        },
    }


def _encounter_conditions(database, encounter_id):
    """Return conditions grouped by their encounter-local target identifier."""
    conditions = {}
    for row in database.execute(
        """
        SELECT target, condition, remaining_rounds
        FROM play_campaign_encounter_conditions
        WHERE encounter_id = ?
        ORDER BY target, condition
        """,
        (encounter_id,),
    ):
        conditions.setdefault(row["target"], []).append({
            "condition": row["condition"],
            "remaining_rounds": row["remaining_rounds"],
        })
    return conditions


def apply_play_campaign_encounter_condition(
    campaign_id, owner, encounter_id, target, condition, duration_rounds
):
    """Apply (or refresh) one named condition on an active combatant."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        encounter = database.execute(
            """
            SELECT 1 FROM play_campaign_encounters
            WHERE id = ? AND campaign_id = ? AND status = 'active'
            """,
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return "unknown_encounter", None
        is_monster = database.execute(
            """
            SELECT 1 FROM play_campaign_encounter_monsters
            WHERE encounter_id = ? AND monster_id = ?
            """,
            (encounter_id, target),
        ).fetchone()
        is_member = database.execute(
            """
            SELECT 1 FROM play_campaign_encounter_combatants
            WHERE encounter_id = ? AND member = ?
            """,
            (encounter_id, target),
        ).fetchone()
        if is_monster is None and is_member is None:
            return "unknown_target", None
        database.execute(
            """
            INSERT INTO play_campaign_encounter_conditions
                (encounter_id, target, condition, remaining_rounds)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(encounter_id, target, condition) DO UPDATE SET
                remaining_rounds = excluded.remaining_rounds
            """,
            (encounter_id, target, condition, duration_rounds),
        )
        conditions = _encounter_conditions(database, encounter_id)[target]
    return "created", {"target": target, "conditions": conditions}


def get_play_campaign_encounter_status(campaign_id, username, encounter_id):
    """Read the complete active encounter state for its owner or a member."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if campaign["owner"] != username and member is None:
            return "not_member", None
        encounter = database.execute(
            """
            SELECT combat_round, turn_index FROM play_campaign_encounters
            WHERE id = ? AND campaign_id = ? AND status = 'active'
            """,
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return "unknown_encounter", None
        order = _encounter_turn_order(database, encounter_id)
        conditions = _encounter_conditions(database, encounter_id)
    if not order:
        return "no_combatants", None
    response = _encounter_turn_response(encounter, order)
    response["order"] = [
        {"name": item["name"], "kind": item["kind"], "initiative": item["initiative"]}
        for item in order
    ]
    response["conditions"] = conditions
    return "found", response


def get_play_campaign_encounter_turn(campaign_id, username, encounter_id):
    """Read an active encounter's turn for its owner or any party member."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if campaign["owner"] != username and member is None:
            return "not_member", None
        encounter = database.execute(
            """
            SELECT combat_round, turn_index FROM play_campaign_encounters
            WHERE id = ? AND campaign_id = ? AND status = 'active'
            """,
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return "unknown_encounter", None
        order = _encounter_turn_order(database, encounter_id)
    if not order:
        return "no_combatants", None
    return "found", _encounter_turn_response(encounter, order)


def advance_play_campaign_encounter_turn(campaign_id, username, encounter_id):
    """Advance an encounter only for its owner or the player whose turn is active."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if campaign["owner"] != username and member is None:
            return "not_member", None
        encounter = database.execute(
            """
            SELECT combat_round, turn_index FROM play_campaign_encounters
            WHERE id = ? AND campaign_id = ? AND status = 'active'
            """,
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return "unknown_encounter", None
        order = _encounter_turn_order(database, encounter_id)
        if not order:
            return "no_combatants", None
        current_index = encounter["turn_index"] % len(order)
        active = order[current_index]
        if campaign["owner"] != username and active["member"] != username:
            return "not_your_turn", None
        next_index = (current_index + 1) % len(order)
        next_round = encounter["combat_round"] + (1 if next_index == 0 else 0)
        next_target = order[next_index]["tie_id"]
        database.execute(
            """
            UPDATE play_campaign_encounter_conditions
            SET remaining_rounds = remaining_rounds - 1
            WHERE encounter_id = ? AND target = ?
            """,
            (encounter_id, next_target),
        )
        database.execute(
            """
            DELETE FROM play_campaign_encounter_conditions
            WHERE encounter_id = ? AND target = ? AND remaining_rounds <= 0
            """,
            (encounter_id, next_target),
        )
        database.execute(
            """
            UPDATE play_campaign_encounters
            SET combat_round = ?, turn_index = ? WHERE id = ? AND campaign_id = ?
            """,
            (next_round, next_index, encounter_id, campaign_id),
        )
        encounter = {"combat_round": next_round, "turn_index": next_index}
        response = _encounter_turn_response(encounter, order)
    return "advanced", response


def delay_play_campaign_encounter_turn(campaign_id, username, encounter_id, new_index):
    """Move the active combatant later in the persistent initiative order."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if campaign["owner"] != username and member is None:
            return "not_member", None
        encounter = database.execute(
            """
            SELECT combat_round, turn_index FROM play_campaign_encounters
            WHERE id = ? AND campaign_id = ? AND status = 'active'
            """,
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return "unknown_encounter", None
        order = _encounter_turn_order(database, encounter_id)
        if not order:
            return "no_combatants", None
        current_index = encounter["turn_index"] % len(order)
        active = order[current_index]
        if campaign["owner"] != username and active["member"] != username:
            return "not_your_turn", None
        if new_index <= current_index or new_index >= len(order):
            return "invalid_index", None

        delayed = order.pop(current_index)
        order.insert(new_index, delayed)
        database.execute(
            "DELETE FROM play_campaign_encounter_turn_order WHERE encounter_id = ?",
            (encounter_id,),
        )
        database.executemany(
            "INSERT INTO play_campaign_encounter_turn_order (encounter_id, position, tie_id) VALUES (?, ?, ?)",
            [(encounter_id, index, item["tie_id"]) for index, item in enumerate(order)],
        )
        database.execute(
            "UPDATE play_campaign_encounters SET turn_index = ? WHERE id = ? AND campaign_id = ?",
            (new_index, encounter_id, campaign_id),
        )
        response = [
            {"name": item["name"], "kind": item["kind"], "initiative": item["initiative"]}
            for item in order
        ]
    return "delayed", {"order": response}


def ready_play_campaign_encounter_action(campaign_id, username, encounter_id, trigger):
    """Store one active player's ready trigger without changing initiative."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if member is None:
            return "not_member", None
        encounter = database.execute(
            """
            SELECT turn_index FROM play_campaign_encounters
            WHERE id = ? AND campaign_id = ? AND status = 'active'
            """,
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return "unknown_encounter", None
        order = _encounter_turn_order(database, encounter_id)
        if not order:
            return "no_combatants", None
        if order[encounter["turn_index"] % len(order)]["member"] != username:
            return "not_your_turn", None
        database.execute(
            """
            INSERT INTO play_campaign_encounter_ready_actions (encounter_id, actor, trigger)
            VALUES (?, ?, ?)
            ON CONFLICT(encounter_id, actor) DO UPDATE SET trigger = excluded.trigger
            """,
            (encounter_id, username, trigger),
        )
    return "created", {"actor": username, "trigger": trigger}


def submit_play_campaign_combat_action(campaign_id, encounter_id, actor, action):
    """Record an active player combatant's action without advancing the turn."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None

        member = database.execute(
            """
            SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?
            """,
            (campaign_id, actor),
        ).fetchone()
        if member is None:
            return "not_member", None

        encounter = database.execute(
            """
            SELECT combat_round, turn_index FROM play_campaign_encounters
            WHERE id = ? AND campaign_id = ? AND status = 'active'
            """,
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return "unknown_encounter", None
        order = _encounter_turn_order(database, encounter_id)
        if not order:
            return "no_combatants", None
        active = order[encounter["turn_index"] % len(order)]
        if active["member"] != actor:
            return "not_your_turn", None

        sequence = next_play_campaign_event_sequence(database, campaign_id, "combat_action")
        database.execute(
            """
            INSERT INTO play_campaign_combat_actions
                (campaign_id, encounter_id, sequence, actor, action_type, target, text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id, encounter_id, sequence, actor, action["type"],
                action["target"], action["text"],
            ),
        )
    return "created", {
        "sequence": sequence,
        "kind": "combat_action",
        "actor": actor,
        "type": action["type"],
        "target": action["target"],
        "text": action["text"],
    }


def adjust_play_campaign_encounter_hp(campaign_id, owner, encounter_id, target, amount, healing):
    """Apply an owner-directed, bounded HP adjustment to an encounter target."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        encounter = database.execute(
            """
            SELECT 1 FROM play_campaign_encounters
            WHERE id = ? AND campaign_id = ? AND status = 'active'
            """,
            (encounter_id, campaign_id),
        ).fetchone()
        if encounter is None:
            return "unknown_encounter", None

        monster = database.execute(
            """
            SELECT hp_current, hp_max FROM play_campaign_encounter_monsters
            WHERE encounter_id = ? AND monster_id = ?
            """,
            (encounter_id, target),
        ).fetchone()
        if monster is not None:
            hp_before, hp_max = monster["hp_current"], monster["hp_max"]
            hp_after = min(hp_max, hp_before + amount) if healing else max(0, hp_before - amount)
            database.execute(
                """
                UPDATE play_campaign_encounter_monsters SET hp_current = ?
                WHERE encounter_id = ? AND monster_id = ?
                """,
                (hp_after, encounter_id, target),
            )
        else:
            combatant = database.execute(
                """
                SELECT member FROM play_campaign_encounter_combatants
                WHERE encounter_id = ? AND member = ?
                """,
                (encounter_id, target),
            ).fetchone()
            if combatant is None:
                return "unknown_target", None
            member = database.execute(
                """
                SELECT hp_current, hp_max FROM play_campaign_members
                WHERE campaign_id = ? AND username = ?
                """,
                (campaign_id, target),
            ).fetchone()
            if member is None:
                return "unknown_target", None
            hp_before, hp_max = member["hp_current"], member["hp_max"]
            hp_after = min(hp_max, hp_before + amount) if healing else max(0, hp_before - amount)
            if hp_after == 0:
                database.execute(
                    """
                    UPDATE play_campaign_members SET hp_current = ?, status = 'unconscious'
                    WHERE campaign_id = ? AND username = ?
                    """,
                    (hp_after, campaign_id, target),
                )
            elif healing:
                database.execute(
                    """
                    UPDATE play_campaign_members
                    SET hp_current = ?, death_save_successes = 0,
                        death_save_failures = 0, status = 'conscious'
                    WHERE campaign_id = ? AND username = ?
                    """,
                    (hp_after, campaign_id, target),
                )
            else:
                database.execute(
                    """
                    UPDATE play_campaign_members SET hp_current = ?
                    WHERE campaign_id = ? AND username = ?
                    """,
                    (hp_after, campaign_id, target),
                )
    return "adjusted", {"target": target, "hp_before": hp_before, "hp_after": hp_after}


def damage_play_campaign_character(campaign_id, actor, character_id, amount):
    """Damage a character when requested by its owner or the campaign owner."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        character = database.execute(
            """
            SELECT o.owner, m.hp_current, m.hp_max, m.status
            FROM play_campaign_members AS m
            JOIN play_campaign_character_owners AS o
              ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
            WHERE m.campaign_id = ? AND m.character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        if actor not in (character["owner"], campaign["owner"]):
            return "not_owner", None
        hp_after = max(0, character["hp_current"] - amount)
        status = (
            "unconscious"
            if hp_after == 0 and character["hp_current"] > 0
            else character["status"]
        )
        database.execute(
            """
            UPDATE play_campaign_members SET hp_current = ?, status = ?
            WHERE campaign_id = ? AND character_id = ?
            """,
            (hp_after, status, campaign_id, character_id),
        )
    return "adjusted", {
        # Keep the generic HP-adjustment response shape used by the existing
        # encounter damage endpoint while also exposing the character ID.
        "target": character_id,
        "character_id": character_id,
        "hp_before": character["hp_current"],
        "hp_after": hp_after,
        "status": status,
    }


def record_play_campaign_death_save(campaign_id, owner, character_id, outcome):
    """Persist one death-save roll and its terminal state transition."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        character = database.execute(
            """
            SELECT o.owner, m.death_save_successes, m.death_save_failures, m.status
            FROM play_campaign_members AS m
            JOIN play_campaign_character_owners AS o
              ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
            WHERE m.campaign_id = ? AND m.character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        if character["owner"] != owner:
            return "not_owner", None
        if character["status"] != "unconscious":
            return "not_unconscious", None
        successes = character["death_save_successes"] + (outcome == "success")
        failures = character["death_save_failures"] + (outcome == "failure")
        status = "stable" if successes >= 3 else "dead" if failures >= 3 else "unconscious"
        database.execute(
            """
            UPDATE play_campaign_members
            SET death_save_successes = ?, death_save_failures = ?, status = ?
            WHERE campaign_id = ? AND character_id = ?
            """,
            (successes, failures, status, campaign_id, character_id),
        )
    return "created", {
        "character_id": character_id,
        "successes": successes,
        "failures": failures,
        "status": status,
    }


def get_play_campaign_character_status(campaign_id, actor, character_id):
    """Return a character status to any member of the same play campaign."""
    with connection() as database:
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if member is None:
            return "not_member", None
        character = database.execute(
            """
            SELECT character_id, hp_current, hp_max, status
            FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
    return "found", dict(character)


def get_play_campaign_character_owner(campaign_id, actor, character_id):
    """Return one character's owner to members of the same campaign."""
    with connection() as database:
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if member is None:
            return "not_member", None
        character = database.execute(
            """
            SELECT m.character_id, o.owner
            FROM play_campaign_members AS m
            LEFT JOIN play_campaign_character_owners AS o
              ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
            WHERE m.campaign_id = ? AND m.character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
    return "found", dict(character)


def check_play_campaign_character_owner(campaign_id, actor, character_id):
    """Verify that ``actor`` is the explicit owner of a play character."""
    with connection() as database:
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign"
        character = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character"
        ownership = database.execute(
            """
            SELECT 1 FROM play_campaign_character_owners
            WHERE campaign_id = ? AND character_id = ? AND owner = ?
            """,
            (campaign_id, character_id, actor),
        ).fetchone()
        if ownership is None:
            return "not_owner"
    return "owner"


def save_play_campaign_character_progression(
    campaign_id, character_id, character_class, con_modifier, abilities=None
):
    """Save the build choices needed by subsequent deterministic level-ups."""
    with connection() as database:
        database.execute(
            """
            UPDATE play_campaign_members
            SET character_class = ?, con_modifier = ?, abilities = ?
            WHERE campaign_id = ? AND character_id = ?
            """,
            (
                character_class,
                con_modifier,
                encode_json({} if abilities is None else abilities),
                campaign_id,
                character_id,
            ),
        )


def get_play_campaign_character_skill_data(campaign_id, actor, character_id):
    """Return an owned character's persisted ability scores and level."""
    with connection() as database:
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        character = database.execute(
            """
            SELECT m.level, m.abilities, o.owner
            FROM play_campaign_members AS m
            LEFT JOIN play_campaign_character_owners AS o
              ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
            WHERE m.campaign_id = ? AND m.character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        if character["owner"] != actor:
            return "not_owner", None
    return "found", {"level": character["level"], "abilities": decode_json(character["abilities"])}


def get_play_campaign_character_class(campaign_id, character_id):
    """Return a built class, falling back to the original membership class."""
    with connection() as database:
        character = database.execute(
            """
            SELECT character_class, class FROM play_campaign_members
            WHERE campaign_id = ? AND character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
    if character is None:
        return None
    return character["character_class"] or character["class"]


def add_play_campaign_character_spell(campaign_id, actor, character_id, spell):
    """Add one wizard spell after atomically checking character ownership."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign"
            character = database.execute(
                """
                SELECT m.character_class, m.class, o.owner
                FROM play_campaign_members AS m
                LEFT JOIN play_campaign_character_owners AS o
                  ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
                WHERE m.campaign_id = ? AND m.character_id = ?
                """,
                (campaign_id, character_id),
            ).fetchone()
            if character is None:
                return "unknown_character"
            if character["owner"] != actor:
                return "not_owner"
            if (character["character_class"] or character["class"]) != "wizard":
                return "invalid_class"
            database.execute(
                """
                INSERT INTO play_campaign_character_spells
                    (campaign_id, character_id, spell_id, name, level)
                VALUES (?, ?, ?, ?, ?)
                """,
                (campaign_id, character_id, spell["spell_id"], spell["name"], spell["level"]),
            )
    except sqlite3.IntegrityError:
        return "duplicate"
    return "added"


def get_play_campaign_character_spells(campaign_id, actor, character_id):
    """Return a character spellbook to members of its campaign."""
    with connection() as database:
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if member is None:
            return "not_member", None
        character = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        spells = database.execute(
            """
            SELECT spell_id, name, level
            FROM play_campaign_character_spells
            WHERE campaign_id = ? AND character_id = ?
            ORDER BY spell_id
            """,
            (campaign_id, character_id),
        ).fetchall()
    return "found", [dict(spell) for spell in spells]


def maximum_prepared_spells(character_class, level):
    """Return the deliberately small preparation limit for supported casters."""
    return level if character_class in {"wizard", "cleric"} else 0


def replace_play_campaign_prepared_spells(campaign_id, actor, character_id, spell_ids):
    """Replace an owned caster's prepared spells after validating its spellbook."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        character = database.execute(
            """
            SELECT m.level, m.character_class, m.class, o.owner
            FROM play_campaign_members AS m
            LEFT JOIN play_campaign_character_owners AS o
              ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
            WHERE m.campaign_id = ? AND m.character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        if character["owner"] != actor:
            return "not_owner", None
        character_class = character["character_class"] or character["class"]
        maximum = maximum_prepared_spells(character_class, character["level"])
        if maximum == 0:
            return "invalid_class", None
        if len(spell_ids) > maximum:
            return "too_many", None
        known_spells = {
            row["spell_id"]
            for row in database.execute(
                """
                SELECT spell_id FROM play_campaign_character_spells
                WHERE campaign_id = ? AND character_id = ?
                """,
                (campaign_id, character_id),
            )
        }
        if any(spell_id not in known_spells for spell_id in spell_ids):
            return "unknown_spell", None
        database.execute(
            """
            DELETE FROM play_campaign_character_prepared_spells
            WHERE campaign_id = ? AND character_id = ?
            """,
            (campaign_id, character_id),
        )
        database.executemany(
            """
            INSERT INTO play_campaign_character_prepared_spells
                (campaign_id, character_id, spell_id, position)
            VALUES (?, ?, ?, ?)
            """,
            [
                (campaign_id, character_id, spell_id, position)
                for position, spell_id in enumerate(spell_ids)
            ],
        )
    return "updated", {
        "character_id": character_id,
        "prepared_spells": spell_ids,
        "max_prepared": maximum,
    }


def get_play_campaign_prepared_spells(campaign_id, actor, character_id):
    """Return prepared spells to any member of the character's campaign."""
    with connection() as database:
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if member is None:
            return "not_member", None
        character = database.execute(
            """
            SELECT level, character_class, class FROM play_campaign_members
            WHERE campaign_id = ? AND character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        prepared_spells = [
            row["spell_id"]
            for row in database.execute(
                """
                SELECT spell_id FROM play_campaign_character_prepared_spells
                WHERE campaign_id = ? AND character_id = ?
                ORDER BY position
                """,
                (campaign_id, character_id),
            )
        ]
    character_class = character["character_class"] or character["class"]
    return "found", {
        "character_id": character_id,
        "prepared_spells": prepared_spells,
        "max_prepared": maximum_prepared_spells(character_class, character["level"]),
    }


# The play API currently has two full casters.  Keeping the complete standard
# full-caster progression here makes slot use deterministic at every supported
# character level while retaining the stage-one wizard's single level-one slot.
FULL_CASTER_SLOTS = (
    (), (1,), (2,), (3, 2), (4, 3), (4, 3, 2), (4, 3, 3), (4, 3, 3, 1),
    (4, 3, 3, 2), (4, 3, 3, 3, 1), (4, 3, 3, 3, 2), (4, 3, 3, 3, 2, 1),
    (4, 3, 3, 3, 2, 1), (4, 3, 3, 3, 2, 1, 1), (4, 3, 3, 3, 2, 1, 1),
    (4, 3, 3, 3, 2, 1, 1, 1), (4, 3, 3, 3, 2, 1, 1, 1),
    (4, 3, 3, 3, 2, 1, 1, 1, 1), (4, 3, 3, 3, 3, 1, 1, 1, 1),
    (4, 3, 3, 3, 3, 2, 1, 1, 1), (4, 3, 3, 3, 3, 2, 2, 1, 1),
)


def spell_slots_for(character_class, level, slot_level):
    """Return the capacity for a spell level, or zero when unavailable."""
    if character_class not in {"wizard", "cleric"} or slot_level < 1:
        return 0
    slots = FULL_CASTER_SLOTS[level] if 1 <= level < len(FULL_CASTER_SLOTS) else ()
    return slots[slot_level - 1] if slot_level <= len(slots) else 0


def cast_play_campaign_character_spell(campaign_id, actor, character_id, spell_id, target):
    """Atomically spend a prepared spell slot and append its cast event."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        character = database.execute(
            """
            SELECT m.level, m.character_class, m.class, o.owner
            FROM play_campaign_members AS m
            LEFT JOIN play_campaign_character_owners AS o
              ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
            WHERE m.campaign_id = ? AND m.character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        if character["owner"] != actor:
            return "not_owner", None
        character_class = character["character_class"] or character["class"]
        if character_class not in {"wizard", "cleric"}:
            return "invalid_class", None
        spell = database.execute(
            """
            SELECT s.level
            FROM play_campaign_character_spells AS s
            JOIN play_campaign_character_prepared_spells AS p
              ON p.campaign_id = s.campaign_id
             AND p.character_id = s.character_id
             AND p.spell_id = s.spell_id
            WHERE s.campaign_id = ? AND s.character_id = ? AND s.spell_id = ?
            """,
            (campaign_id, character_id, spell_id),
        ).fetchone()
        if spell is None:
            return "not_prepared", None
        slot_level = spell["level"]
        capacity = spell_slots_for(character_class, character["level"], slot_level)
        used = database.execute(
            """
            SELECT COUNT(*) AS count FROM play_campaign_character_casts
            WHERE campaign_id = ? AND character_id = ? AND slot_level = ?
            """,
            (campaign_id, character_id, slot_level),
        ).fetchone()["count"]
        if capacity <= used:
            return "no_slots", None
        sequence = database.execute(
            """
            SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence
            FROM play_campaign_character_casts
            WHERE campaign_id = ? AND character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()["sequence"]
        event = {
            "character_id": character_id,
            "spell_id": spell_id,
            "target": target,
            "slot_level": slot_level,
            "slots_remaining": capacity - used - 1,
            "sequence": sequence,
        }
        database.execute(
            """
            INSERT INTO play_campaign_character_casts
                (campaign_id, character_id, sequence, spell_id, target,
                 slot_level, slots_remaining)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (campaign_id, character_id, sequence, spell_id, target, slot_level,
             event["slots_remaining"]),
        )
    return "cast", event


def get_play_campaign_character_casts(campaign_id, actor, character_id):
    """Return cast history to any member of the character's campaign."""
    with connection() as database:
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if member is None:
            return "not_member", None
        character = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        casts = database.execute(
            """
            SELECT character_id, spell_id, target, slot_level, slots_remaining, sequence
            FROM play_campaign_character_casts
            WHERE campaign_id = ? AND character_id = ?
            ORDER BY sequence
            """,
            (campaign_id, character_id),
        ).fetchall()
    return "found", [dict(cast) for cast in casts]


def set_play_campaign_character_concentration(
    campaign_id, actor, character_id, spell_id, target, remaining_turns
):
    """Replace an owned caster's active concentration after spell validation."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        character = database.execute(
            """
            SELECT m.character_class, m.class, o.owner
            FROM play_campaign_members AS m
            LEFT JOIN play_campaign_character_owners AS o
              ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
            WHERE m.campaign_id = ? AND m.character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        if character["owner"] != actor:
            return "not_owner", None
        if (character["character_class"] or character["class"]) not in {"wizard", "cleric"}:
            return "invalid_class", None
        known = database.execute(
            """
            SELECT 1 FROM play_campaign_character_spells
            WHERE campaign_id = ? AND character_id = ? AND spell_id = ?
            """,
            (campaign_id, character_id, spell_id),
        ).fetchone()
        if known is None:
            return "unknown_spell", None
        prepared = database.execute(
            """
            SELECT 1 FROM play_campaign_character_prepared_spells
            WHERE campaign_id = ? AND character_id = ? AND spell_id = ?
            """,
            (campaign_id, character_id, spell_id),
        ).fetchone()
        if prepared is None:
            return "not_prepared", None
        concentration = {
            "spell_id": spell_id,
            "target": target,
            "remaining_turns": remaining_turns,
        }
        database.execute(
            """
            INSERT INTO play_campaign_character_concentrations
                (campaign_id, character_id, spell_id, target, remaining_turns)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(campaign_id, character_id) DO UPDATE SET
                spell_id = excluded.spell_id,
                target = excluded.target,
                remaining_turns = excluded.remaining_turns
            """,
            (campaign_id, character_id, spell_id, target, remaining_turns),
        )
    return "updated", {"character_id": character_id, "concentration": concentration}


def get_play_campaign_character_concentration(campaign_id, actor, character_id):
    """Return one character's concentration state to campaign members."""
    with connection() as database:
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if member is None:
            return "not_member", None
        character = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        concentration = database.execute(
            """
            SELECT spell_id, target, remaining_turns
            FROM play_campaign_character_concentrations
            WHERE campaign_id = ? AND character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
    return "found", {
        "character_id": character_id,
        "concentration": dict(concentration) if concentration is not None else None,
    }


def advance_play_campaign_character_concentration(campaign_id, actor, character_id):
    """Advance an active concentration by one member-visible campaign turn."""
    result, state = get_play_campaign_character_concentration(campaign_id, actor, character_id)
    if result != "found" or state["concentration"] is None:
        return result, state
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        concentration = database.execute(
            """
            SELECT remaining_turns FROM play_campaign_character_concentrations
            WHERE campaign_id = ? AND character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if concentration is None:
            return "found", {"character_id": character_id, "concentration": None}
        remaining_turns = concentration["remaining_turns"] - 1
        if remaining_turns <= 0:
            database.execute(
                "DELETE FROM play_campaign_character_concentrations WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            )
            concentration_state = None
        else:
            database.execute(
                """
                UPDATE play_campaign_character_concentrations SET remaining_turns = ?
                WHERE campaign_id = ? AND character_id = ?
                """,
                (remaining_turns, campaign_id, character_id),
            )
            concentration_state = state["concentration"] | {"remaining_turns": remaining_turns}
    return "found", {"character_id": character_id, "concentration": concentration_state}


def clear_play_campaign_character_concentration(campaign_id, actor, character_id):
    """Clear concentration after atomically checking ownership."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        character = database.execute(
            """
            SELECT o.owner FROM play_campaign_members AS m
            LEFT JOIN play_campaign_character_owners AS o
              ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
            WHERE m.campaign_id = ? AND m.character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        if character["owner"] != actor:
            return "not_owner", None
        database.execute(
            "DELETE FROM play_campaign_character_concentrations WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        )
    return "cleared", {"character_id": character_id, "concentration": None}


def create_play_campaign_downtime_activity(campaign_id, owner, activity):
    """Create a recurring activity owned by a campaign's DM."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != owner:
                return "not_owner", None
            database.execute(
                """
                INSERT INTO play_campaign_downtime_activities
                    (campaign_id, activity_id, name, cycles_required)
                VALUES (?, ?, ?, ?)
                """,
                (campaign_id, activity["activity_id"], activity["name"],
                 activity["cycles_required"]),
            )
    except sqlite3.IntegrityError:
        return "duplicate", None
    return "created", activity


def create_play_campaign_downtime_allocation(campaign_id, actor, character_id, activity_id):
    """Allocate an activity to its owning player character."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            character = database.execute(
                """
                SELECT o.owner FROM play_campaign_members AS m
                LEFT JOIN play_campaign_character_owners AS o
                  ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
                WHERE m.campaign_id = ? AND m.character_id = ?
                """,
                (campaign_id, character_id),
            ).fetchone()
            if character is None:
                return "unknown_character", None
            if character["owner"] != actor:
                return "not_owner", None
            activity = database.execute(
                """SELECT 1 FROM play_campaign_downtime_activities
                   WHERE campaign_id = ? AND activity_id = ?""",
                (campaign_id, activity_id),
            ).fetchone()
            if activity is None:
                return "unknown_activity", None
            database.execute(
                """
                INSERT INTO play_campaign_downtime_allocations
                    (campaign_id, character_id, activity_id, cycles_completed, completions)
                VALUES (?, ?, ?, 0, 0)
                """,
                (campaign_id, character_id, activity_id),
            )
    except sqlite3.IntegrityError:
        return "duplicate", None
    return "created", {
        "character_id": character_id, "activity_id": activity_id,
        "cycles_completed": 0, "completions": 0,
    }


def progress_play_campaign_downtime_allocation(campaign_id, actor, character_id, activity_id):
    """Advance an owned allocation one cycle, resetting it after each completion."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        character = database.execute(
            """
            SELECT o.owner FROM play_campaign_members AS m
            LEFT JOIN play_campaign_character_owners AS o
              ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
            WHERE m.campaign_id = ? AND m.character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        if character["owner"] != actor:
            return "not_owner", None
        activity = database.execute(
            """SELECT cycles_required FROM play_campaign_downtime_activities
               WHERE campaign_id = ? AND activity_id = ?""",
            (campaign_id, activity_id),
        ).fetchone()
        if activity is None:
            return "unknown_activity", None
        allocation = database.execute(
            """SELECT cycles_completed, completions FROM play_campaign_downtime_allocations
               WHERE campaign_id = ? AND character_id = ? AND activity_id = ?""",
            (campaign_id, character_id, activity_id),
        ).fetchone()
        if allocation is None:
            return "unknown_allocation", None
        cycles_completed = allocation["cycles_completed"] + 1
        completions = allocation["completions"]
        if cycles_completed == activity["cycles_required"]:
            cycles_completed = 0
            completions += 1
        database.execute(
            """UPDATE play_campaign_downtime_allocations
               SET cycles_completed = ?, completions = ?
               WHERE campaign_id = ? AND character_id = ? AND activity_id = ?""",
            (cycles_completed, completions, campaign_id, character_id, activity_id),
        )
    return "progressed", {
        "character_id": character_id, "activity_id": activity_id,
        "cycles_completed": cycles_completed, "completions": completions,
    }


def get_play_campaign_downtime_allocation(campaign_id, actor, character_id, activity_id):
    """Read an allocation as the DM or any enrolled campaign player."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if actor != campaign["owner"] and member is None:
            return "not_member", None
        character = database.execute(
            """SELECT 1 FROM play_campaign_members
               WHERE campaign_id = ? AND character_id = ?""",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        activity = database.execute(
            """SELECT 1 FROM play_campaign_downtime_activities
               WHERE campaign_id = ? AND activity_id = ?""",
            (campaign_id, activity_id),
        ).fetchone()
        if activity is None:
            return "unknown_activity", None
        allocation = database.execute(
            """SELECT cycles_completed, completions FROM play_campaign_downtime_allocations
               WHERE campaign_id = ? AND character_id = ? AND activity_id = ?""",
            (campaign_id, character_id, activity_id),
        ).fetchone()
        if allocation is None:
            return "unknown_allocation", None
    return "found", {
        "character_id": character_id, "activity_id": activity_id,
        "cycles_completed": allocation["cycles_completed"],
        "completions": allocation["completions"],
    }


def create_play_campaign_recipe(campaign_id, owner, recipe):
    """Create one DM-owned recipe, retaining its insertion order in SQLite."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        try:
            database.execute(
                """
                INSERT INTO play_campaign_recipes
                    (campaign_id, recipe_id, name, ingredients, output_item, output_quantity)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (campaign_id, recipe["recipe_id"], recipe["name"],
                 encode_json(recipe["ingredients"]), recipe["output_item"],
                 recipe["output_quantity"]),
            )
        except sqlite3.IntegrityError:
            return "duplicate", None
    return "created", recipe


def get_play_campaign_recipes(campaign_id, actor):
    """Return recipes to the DM or any player who belongs to the campaign."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if actor != campaign["owner"] and member is None:
            return "not_member", None
        rows = database.execute(
            """
            SELECT recipe_id, name, ingredients, output_item, output_quantity
            FROM play_campaign_recipes WHERE campaign_id = ? ORDER BY rowid
            """,
            (campaign_id,),
        ).fetchall()
    return "found", {"recipes": [{
        "recipe_id": row["recipe_id"], "name": row["name"],
        "ingredients": decode_json(row["ingredients"]),
        "output_item": row["output_item"], "output_quantity": row["output_quantity"],
    } for row in rows]}


def craft_play_campaign_recipe(campaign_id, actor, recipe_id, character_id):
    """Consume every ingredient and add the output as one SQLite transaction."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        recipe = database.execute(
            """
            SELECT ingredients, output_item, output_quantity FROM play_campaign_recipes
            WHERE campaign_id = ? AND recipe_id = ?
            """,
            (campaign_id, recipe_id),
        ).fetchone()
        if recipe is None:
            return "unknown_recipe", None
        character = database.execute(
            """
            SELECT o.owner FROM play_campaign_members AS m
            LEFT JOIN play_campaign_character_owners AS o
              ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
            WHERE m.campaign_id = ? AND m.character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        if character["owner"] != actor:
            return "not_owner", None
        ingredients = decode_json(recipe["ingredients"])
        for item_id, quantity in ingredients.items():
            stack = database.execute(
                """SELECT quantity FROM play_campaign_character_inventory_items
                   WHERE campaign_id = ? AND character_id = ? AND item_id = ?""",
                (campaign_id, character_id, item_id),
            ).fetchone()
            if stack is None or stack["quantity"] < quantity:
                return "insufficient", None
        for item_id, quantity in ingredients.items():
            database.execute(
                """UPDATE play_campaign_character_inventory_items
                   SET quantity = quantity - ?
                   WHERE campaign_id = ? AND character_id = ? AND item_id = ?""",
                (quantity, campaign_id, character_id, item_id),
            )
        database.execute(
            """DELETE FROM play_campaign_character_inventory_items
               WHERE campaign_id = ? AND character_id = ? AND quantity = 0""",
            (campaign_id, character_id),
        )
        database.execute(
            """INSERT INTO play_campaign_character_inventory_items
                   (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)
               ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET
                   quantity = quantity + excluded.quantity""",
            (campaign_id, character_id, recipe["output_item"], recipe["output_quantity"]),
        )
    return "crafted", {
        "character_id": character_id, "recipe_id": recipe_id,
        "output_item": recipe["output_item"], "output_quantity": recipe["output_quantity"],
    }


def add_play_campaign_character_inventory_item(campaign_id, actor, character_id, item_id, quantity):
    """Atomically add to an explicitly owned character's item stack."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        character = database.execute(
            """
            SELECT o.owner FROM play_campaign_members AS m
            LEFT JOIN play_campaign_character_owners AS o
              ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
            WHERE m.campaign_id = ? AND m.character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        if character["owner"] != actor:
            return "not_owner", None
        database.execute(
            """
            INSERT INTO play_campaign_character_inventory_items
                (campaign_id, character_id, item_id, quantity)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET
                quantity = quantity + excluded.quantity
            """,
            (campaign_id, character_id, item_id, quantity),
        )
        total_quantity = database.execute(
            """
            SELECT quantity FROM play_campaign_character_inventory_items
            WHERE campaign_id = ? AND character_id = ? AND item_id = ?
            """,
            (campaign_id, character_id, item_id),
        ).fetchone()["quantity"]
    return "updated", {
        "character_id": character_id,
        "item_id": item_id,
        "quantity": quantity,
        "total_quantity": total_quantity,
    }


def get_play_campaign_character_inventory_items(campaign_id, actor, character_id):
    """Return item stacks to any member of the same play campaign."""
    with connection() as database:
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if member is None:
            return "not_member", None
        character = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        items = database.execute(
            """
            SELECT item_id, quantity FROM play_campaign_character_inventory_items
            WHERE campaign_id = ? AND character_id = ?
            ORDER BY item_id
            """,
            (campaign_id, character_id),
        ).fetchall()
    return "found", {"character_id": character_id, "items": [dict(item) for item in items]}


def create_play_campaign_loot(campaign_id, owner, loot):
    """Create one DM-owned, campaign-scoped loot record."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        try:
            database.execute(
                """
                INSERT INTO play_campaign_loot (campaign_id, loot_id, item_id, quantity, status)
                VALUES (?, ?, ?, ?, 'open')
                """,
                (campaign_id, loot["loot_id"], loot["item_id"], loot["quantity"]),
            )
        except sqlite3.IntegrityError:
            return "duplicate", None
    return "created", {**loot, "status": "open"}


def vote_for_play_campaign_loot(campaign_id, voter, loot_id, recipient_character_id):
    """Persist a player's single immutable vote and return that recipient's total."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, voter),
        ).fetchone()
        if member is None:
            return "not_member", None
        loot = database.execute(
            "SELECT status FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?",
            (campaign_id, loot_id),
        ).fetchone()
        if loot is None:
            return "unknown_loot", None
        if loot["status"] != "open":
            return "not_open", None
        recipient = database.execute(
            """
            SELECT 1 FROM play_campaign_members
            WHERE campaign_id = ? AND character_id = ?
            """,
            (campaign_id, recipient_character_id),
        ).fetchone()
        if recipient is None:
            return "unknown_character", None
        try:
            database.execute(
                """
                INSERT INTO play_campaign_loot_votes
                    (campaign_id, loot_id, voter, recipient_character_id)
                VALUES (?, ?, ?, ?)
                """,
                (campaign_id, loot_id, voter, recipient_character_id),
            )
        except sqlite3.IntegrityError:
            return "duplicate", None
        votes = database.execute(
            """
            SELECT COUNT(*) AS votes FROM play_campaign_loot_votes
            WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?
            """,
            (campaign_id, loot_id, recipient_character_id),
        ).fetchone()["votes"]
    return "created", {
        "loot_id": loot_id,
        "voter": voter,
        "recipient_character_id": recipient_character_id,
        "votes_for_recipient": votes,
    }


def assign_play_campaign_loot(campaign_id, owner, loot_id):
    """Assign the unique vote winner and add its stack exactly once."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        loot = database.execute(
            """
            SELECT item_id, quantity, status FROM play_campaign_loot
            WHERE campaign_id = ? AND loot_id = ?
            """,
            (campaign_id, loot_id),
        ).fetchone()
        if loot is None:
            return "unknown_loot", None
        if loot["status"] != "open":
            return "not_open", None
        leaders = database.execute(
            """
            SELECT recipient_character_id, COUNT(*) AS votes
            FROM play_campaign_loot_votes
            WHERE campaign_id = ? AND loot_id = ?
            GROUP BY recipient_character_id
            ORDER BY votes DESC, recipient_character_id
            """,
            (campaign_id, loot_id),
        ).fetchall()
        if not leaders or (len(leaders) > 1 and leaders[0]["votes"] == leaders[1]["votes"]):
            return "ambiguous", None
        winner, votes = leaders[0]["recipient_character_id"], leaders[0]["votes"]
        database.execute(
            """
            INSERT INTO play_campaign_character_inventory_items
                (campaign_id, character_id, item_id, quantity)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET
                quantity = quantity + excluded.quantity
            """,
            (campaign_id, winner, loot["item_id"], loot["quantity"]),
        )
        database.execute(
            """
            UPDATE play_campaign_loot
            SET status = 'assigned', recipient_character_id = ?, votes = ?
            WHERE campaign_id = ? AND loot_id = ?
            """,
            (winner, votes, campaign_id, loot_id),
        )
    return "assigned", {
        "loot_id": loot_id,
        "recipient_character_id": winner,
        "item_id": loot["item_id"],
        "quantity": loot["quantity"],
        "votes": votes,
        "status": "assigned",
    }


def get_play_campaign_loot(campaign_id, actor, loot_id):
    """Return a loot record to the DM or a player in its campaign."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if actor != campaign["owner"] and member is None:
            return "not_member", None
        loot = database.execute(
            """
            SELECT loot_id, item_id, quantity, status, recipient_character_id, votes
            FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?
            """,
            (campaign_id, loot_id),
        ).fetchone()
        if loot is None:
            return "unknown_loot", None
        vote_rows = database.execute(
            """
            SELECT recipient_character_id, COUNT(*) AS votes
            FROM play_campaign_loot_votes
            WHERE campaign_id = ? AND loot_id = ?
            GROUP BY recipient_character_id
            """,
            (campaign_id, loot_id),
        ).fetchall()
    record = dict(loot)
    # The read representation exposes immutable vote tallies, while the
    # assignment response intentionally reports only the winning vote count.
    record["votes"] = {row["recipient_character_id"]: row["votes"] for row in vote_rows}
    return "found", record


def create_play_campaign_npc(campaign_id, owner, npc):
    """Create one DM-managed NPC with a private agenda."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != owner:
                return "not_owner", None
            database.execute(
                """
                INSERT INTO play_campaign_npcs
                    (campaign_id, npc_id, name, agenda, public_status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    campaign_id,
                    npc["npc_id"],
                    npc["name"],
                    npc["agenda"],
                    npc["public_status"],
                ),
            )
    except sqlite3.IntegrityError:
        return "duplicate", None
    return "created", npc


def update_play_campaign_npc_agenda(campaign_id, owner, npc_id, agenda, public_status):
    """Update the DM-only and public parts of one campaign NPC atomically."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        npc = database.execute(
            "SELECT name FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
        if npc is None:
            return "unknown_npc", None
        database.execute(
            """
            UPDATE play_campaign_npcs SET agenda = ?, public_status = ?
            WHERE campaign_id = ? AND npc_id = ?
            """,
            (agenda, public_status, campaign_id, npc_id),
        )
    return "updated", {
        "npc_id": npc_id,
        "name": npc["name"],
        "agenda": agenda,
        "public_status": public_status,
    }


def get_play_campaign_npc(campaign_id, actor, npc_id):
    """Read an NPC only for its DM or a player who belongs to its campaign."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if actor != campaign["owner"] and member is None:
            return "not_member", None
        npc = database.execute(
            """
            SELECT npc_id, name, agenda, public_status FROM play_campaign_npcs
            WHERE campaign_id = ? AND npc_id = ?
            """,
            (campaign_id, npc_id),
        ).fetchone()
    if npc is None:
        return "unknown_npc", None
    return "found", {**dict(npc), "is_dm": actor == campaign["owner"]}


def create_play_campaign_npc_dialogue(campaign_id, owner, npc_id, dialogue):
    """Append one attributed dialogue line to an NPC's ordered history."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != owner:
                return "not_owner", None
            npc = database.execute(
                "SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
                (campaign_id, npc_id),
            ).fetchone()
            if npc is None:
                return "unknown_npc", None
            database.execute(
                """
                INSERT INTO play_campaign_npc_dialogue
                    (campaign_id, npc_id, dialogue_id, speaker, text, visibility)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign_id, npc_id, dialogue["dialogue_id"], dialogue["speaker"],
                    dialogue["text"], dialogue["visibility"],
                ),
            )
    except sqlite3.IntegrityError:
        return "duplicate", None
    return "created", dialogue


def get_play_campaign_npc_dialogue(campaign_id, actor, npc_id):
    """Return dialogue visible to the campaign DM or one of its players."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if actor != campaign["owner"] and member is None:
            return "not_member", None
        npc = database.execute(
            "SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
        if npc is None:
            return "unknown_npc", None
        query = """
            SELECT dialogue_id, speaker, text, visibility
            FROM play_campaign_npc_dialogue
            WHERE campaign_id = ? AND npc_id = ?
        """
        parameters = [campaign_id, npc_id]
        if actor != campaign["owner"]:
            query += " AND visibility = 'public'"
        query += " ORDER BY rowid"
        entries = [dict(row) for row in database.execute(query, parameters).fetchall()]
    return "found", {"npc_id": npc_id, "entries": entries}


def _play_campaign_entity_exists(database, campaign_id, entity_id):
    """Return whether an id names either a member character or an NPC."""
    return database.execute(
        """
        SELECT 1 FROM play_campaign_members
        WHERE campaign_id = ? AND character_id = ?
        UNION ALL
        SELECT 1 FROM play_campaign_npcs
        WHERE campaign_id = ? AND npc_id = ?
        LIMIT 1
        """,
        (campaign_id, entity_id, campaign_id, entity_id),
    ).fetchone() is not None


def create_play_campaign_relationship(campaign_id, owner, relationship):
    """Create one directed edge after checking both campaign entities."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != owner:
                return "not_owner", None
            if not _play_campaign_entity_exists(database, campaign_id, relationship["source_id"]):
                return "unknown_entity", None
            if not _play_campaign_entity_exists(database, campaign_id, relationship["target_id"]):
                return "unknown_entity", None
            database.execute(
                """
                INSERT INTO play_campaign_relationships
                    (campaign_id, source_id, target_id, kind, score)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    campaign_id, relationship["source_id"], relationship["target_id"],
                    relationship["kind"], relationship["score"],
                ),
            )
    except sqlite3.IntegrityError:
        return "duplicate", None
    return "created", relationship


def update_play_campaign_relationship(campaign_id, owner, source_id, target_id, kind, score):
    """Update the score of an existing directed relationship edge."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        cursor = database.execute(
            """
            UPDATE play_campaign_relationships SET score = ?
            WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?
            """,
            (score, campaign_id, source_id, target_id, kind),
        )
        if cursor.rowcount == 0:
            return "unknown_relationship", None
    return "updated", {
        "source_id": source_id, "target_id": target_id, "kind": kind, "score": score,
    }


def get_play_campaign_relationships(campaign_id, actor):
    """Return insertion-ordered relationship edges to campaign participants."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if actor != campaign["owner"] and member is None:
            return "not_member", None
        edges = database.execute(
            """
            SELECT source_id, target_id, kind, score
            FROM play_campaign_relationships
            WHERE campaign_id = ? ORDER BY rowid
            """,
            (campaign_id,),
        ).fetchall()
    return "found", {"edges": [dict(edge) for edge in edges]}


def create_play_campaign_clue(campaign_id, owner, clue):
    """Create one DM-managed clue after checking its target character."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != owner:
                return "not_owner", None
            if clue["audience"] == "character":
                member = database.execute(
                    "SELECT 1 FROM play_campaign_members "
                    "WHERE campaign_id = ? AND character_id = ?",
                    (campaign_id, clue["character_id"]),
                ).fetchone()
                if member is None:
                    return "unknown_character", None
            database.execute(
                """
                INSERT INTO play_campaign_clues
                    (campaign_id, clue_id, text, audience, character_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    campaign_id, clue["clue_id"], clue["text"], clue["audience"],
                    clue.get("character_id"),
                ),
            )
    except sqlite3.IntegrityError:
        return "duplicate", None
    return "created", clue


def get_play_campaign_clues(campaign_id, actor):
    """Return campaign clues visible to the owner or requesting party member."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT character_id FROM play_campaign_members "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if actor != campaign["owner"] and member is None:
            return "not_member", None

        query = """
            SELECT clue_id, text, audience, character_id
            FROM play_campaign_clues
            WHERE campaign_id = ?
        """
        parameters = [campaign_id]
        if actor != campaign["owner"]:
            query += " AND (audience = 'party' OR (audience = 'character' AND character_id = ?))"
            parameters.append(member["character_id"])
        query += " ORDER BY rowid"
        clues = []
        for row in database.execute(query, parameters):
            clue = {"clue_id": row["clue_id"], "text": row["text"], "audience": row["audience"]}
            if row["audience"] == "character":
                clue["character_id"] = row["character_id"]
            clues.append(clue)
    return "found", {"clues": clues}


def _play_campaign_quest(row):
    quest = {
        "quest_id": row["quest_id"],
        "title": row["title"],
        "depends_on": decode_json(row["depends_on"]),
        "state": row["state"],
    }
    if "rewards" in row.keys() and row["rewards"] is not None:
        quest["rewards"] = decode_json(row["rewards"])
    return quest


def create_play_campaign_quest(campaign_id, owner, quest):
    """Create a dependency-gated quest for the campaign owner."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != owner:
                return "not_owner", None
            if quest["depends_on"]:
                placeholders = ", ".join("?" for _ in quest["depends_on"])
                found = database.execute(
                    f"SELECT quest_id FROM play_campaign_quests WHERE campaign_id = ? "
                    f"AND quest_id IN ({placeholders})",
                    [campaign_id, *quest["depends_on"]],
                ).fetchall()
                if len(found) != len(quest["depends_on"]):
                    return "unknown_dependency", None
            database.execute(
                """
                INSERT INTO play_campaign_quests
                    (campaign_id, quest_id, title, depends_on, state)
                VALUES (?, ?, ?, ?, ?)
                """,
                (campaign_id, quest["quest_id"], quest["title"],
                 encode_json(quest["depends_on"]), "locked"),
            )
    except sqlite3.IntegrityError:
        return "duplicate", None
    return "created", {**quest, "state": "locked"}


def get_play_campaign_quests(campaign_id, actor):
    """Read insertion-ordered quests for the owner or any campaign member."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if actor != campaign["owner"] and member is None:
            return "not_member", None
        rows = database.execute(
            "SELECT quest_id, title, depends_on, state, rewards FROM play_campaign_quests "
            "WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
    return "found", {"quests": [_play_campaign_quest(row) for row in rows]}


def update_play_campaign_quest_state(campaign_id, owner, quest_id, state):
    """Apply the two permitted quest state transitions atomically."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        row = database.execute(
            "SELECT quest_id, title, depends_on, state, rewards FROM play_campaign_quests "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if row is None:
            return "unknown_quest", None
        quest = _play_campaign_quest(row)
        if quest["state"] == "locked" and state == "active":
            dependencies = quest["depends_on"]
            if dependencies:
                placeholders = ", ".join("?" for _ in dependencies)
                completed = database.execute(
                    f"SELECT COUNT(*) AS count FROM play_campaign_quests "
                    f"WHERE campaign_id = ? AND state = 'completed' "
                    f"AND quest_id IN ({placeholders})",
                    [campaign_id, *dependencies],
                ).fetchone()["count"]
                if completed != len(dependencies):
                    return "blocked", None
        elif not (quest["state"] == "active" and state == "completed"):
            return "invalid_transition", None
        database.execute(
            "UPDATE play_campaign_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?",
            (state, campaign_id, quest_id),
        )
        quest["state"] = state
    return "updated", quest


def configure_play_campaign_quest_rewards(campaign_id, owner, quest_id, rewards):
    """Save one unawarded reward package for a locked or active owner quest."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        row = database.execute(
            "SELECT quest_id, title, depends_on, state, rewards FROM play_campaign_quests "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if row is None:
            return "unknown_quest", None
        quest = _play_campaign_quest(row)
        if quest["state"] not in {"locked", "active"}:
            return "invalid_state", None
        database.execute(
            "UPDATE play_campaign_quests SET rewards = ? "
            "WHERE campaign_id = ? AND quest_id = ?",
            (encode_json(rewards), campaign_id, quest_id),
        )
    return "configured", {**quest, "rewards": rewards}


def award_play_campaign_quest_rewards(campaign_id, owner, quest_id):
    """Grant a completed quest package once to every current campaign member."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        quest = database.execute(
            "SELECT state, rewards, rewards_awarded FROM play_campaign_quests "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if quest is None:
            return "unknown_quest", None
        if quest["state"] != "completed" or quest["rewards"] is None:
            return "invalid_state", None
        if quest["rewards_awarded"]:
            return "already_awarded", None
        rewards = decode_json(quest["rewards"])
        members = database.execute(
            "SELECT character_id FROM play_campaign_members WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchall()
        for member in members:
            database.execute(
                "INSERT INTO play_campaign_quest_reward_grants "
                "(campaign_id, quest_id, character_id, xp, items) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, quest_id, member["character_id"], rewards["xp"],
                 encode_json(rewards["items"])),
            )
        database.execute(
            "UPDATE play_campaign_quests SET rewards_awarded = 1 "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        )
    return "awarded", {"quest_id": quest_id, "awarded": True, **rewards}


def get_play_campaign_character_rewards(campaign_id, actor, character_id):
    """Return cumulative awarded quest rewards to a campaign member."""
    with connection() as database:
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if member is None:
            return "not_member", None
        character = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        grants = database.execute(
            "SELECT xp, items FROM play_campaign_quest_reward_grants "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchall()
    items = {}
    for grant in grants:
        for item_id, quantity in decode_json(grant["items"]).items():
            items[item_id] = items.get(item_id, 0) + quantity
    return "found", {
        "character_id": character_id,
        "xp": sum(grant["xp"] for grant in grants),
        "items": items,
    }


def _play_campaign_world_event(row):
    """Format one stored world event without exposing persistence metadata."""
    event = {
        "event_id": row["event_id"],
        "turn_number": row["turn_number"],
        "title": row["title"],
        "text": row["text"],
        "status": "resolved" if row["resolution_text"] is not None else "scheduled",
    }
    if row["resolution_text"] is not None:
        event["resolution"] = {
            "turn_number": row["resolution_turn_number"],
            "text": row["resolution_text"],
        }
    return event


def schedule_play_campaign_world_event(campaign_id, owner, event):
    """Schedule a future (or current-turn) DM event exactly once."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != owner:
                return "not_owner", None
            turn = database.execute(
                "SELECT turn_number FROM play_campaign_turns WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            if turn is None:
                return "not_active", None
            if event["turn_number"] < turn["turn_number"]:
                return "past_turn", None
            database.execute(
                """
                INSERT INTO play_campaign_world_events
                    (campaign_id, event_id, turn_number, title, text)
                VALUES (?, ?, ?, ?, ?)
                """,
                (campaign_id, event["event_id"], event["turn_number"], event["title"], event["text"]),
            )
    except sqlite3.IntegrityError:
        return "duplicate", None
    return "scheduled", {**event, "status": "scheduled"}


def resolve_play_campaign_world_event(campaign_id, owner, event_id, text):
    """Persist a world-event resolution only at its designated campaign turn."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        row = database.execute(
            """
            SELECT event_id, turn_number, title, text, resolution_turn_number, resolution_text
            FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?
            """,
            (campaign_id, event_id),
        ).fetchone()
        if row is None:
            return "unknown_event", None
        if row["resolution_text"] is not None:
            return "already_resolved", None
        turn = database.execute(
            "SELECT turn_number FROM play_campaign_turns WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if turn is None:
            return "not_active", None
        if turn["turn_number"] != row["turn_number"]:
            return "wrong_turn", None
        database.execute(
            """
            UPDATE play_campaign_world_events
            SET resolution_turn_number = ?, resolution_text = ?
            WHERE campaign_id = ? AND event_id = ? AND resolution_text IS NULL
            """,
            (turn["turn_number"], text, campaign_id, event_id),
        )
    event = _play_campaign_world_event(row)
    event["status"] = "resolved"
    event["resolution"] = {"turn_number": row["turn_number"], "text": text}
    return "resolved", event


def get_play_campaign_world_events(campaign_id, actor):
    """List campaign events for the DM and its current party members."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if campaign["owner"] != actor and member is None:
            return "not_member", None
        rows = database.execute(
            """
            SELECT event_id, turn_number, title, text, resolution_turn_number, resolution_text
            FROM play_campaign_world_events
            WHERE campaign_id = ?
            ORDER BY turn_number ASC, creation_order ASC
            """,
            (campaign_id,),
        ).fetchall()
    return "found", {"events": [_play_campaign_world_event(row) for row in rows]}


def initialize_play_campaign_calendar(campaign_id, owner, calendar):
    """Create the one DM-owned calendar for a campaign."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != owner:
                return "not_owner", None
            database.execute(
                "INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (?, ?, ?)",
                (campaign_id, calendar["day"], calendar["season"]),
            )
    except sqlite3.IntegrityError:
        return "already_initialized", None
    return "created", calendar


def get_play_campaign_calendar(campaign_id, actor):
    """Return a calendar to its DM or an enrolled player."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if campaign["owner"] != actor and member is None:
            return "not_member", None
        row = database.execute(
            "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    if row is None:
        return "not_initialized", None
    return "found", dict(row)


def advance_play_campaign_calendar(campaign_id, owner, days):
    """Advance a DM-owned initialized calendar by a validated number of days."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        row = database.execute(
            "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return "not_initialized", None
        day = row["day"] + days
        database.execute(
            "UPDATE play_campaign_calendars SET day = ? WHERE campaign_id = ?",
            (day, campaign_id),
        )
    return "advanced", {"day": day, "season": row["season"]}


def _play_campaign_settlement(database, row, character_id=None):
    """Build the public settlement shape, optionally limited to one player."""
    discoverers = database.execute(
        """
        SELECT character_id FROM play_campaign_settlement_discoveries
        WHERE campaign_id = ? AND settlement_id = ?
        ORDER BY discovery_order ASC
        """,
        (row["campaign_id"], row["settlement_id"]),
    ).fetchall()
    return {
        "settlement_id": row["settlement_id"],
        "name": row["name"],
        "services": decode_json(row["services"]),
        "availability": row["availability"],
        "discovered_by": [entry["character_id"] for entry in discoverers
                          if character_id is None or entry["character_id"] == character_id],
    }


def create_play_campaign_settlement(campaign_id, owner, settlement):
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != owner:
                return "not_owner", None
            database.execute(
                """
                INSERT INTO play_campaign_settlements
                    (campaign_id, settlement_id, name, services, availability)
                VALUES (?, ?, ?, ?, ?)
                """,
                (campaign_id, settlement["settlement_id"], settlement["name"],
                 encode_json(settlement["services"]), settlement["availability"]),
            )
    except sqlite3.IntegrityError:
        return "duplicate", None
    return "created", {**settlement, "discovered_by": []}


def update_play_campaign_settlement(campaign_id, owner, settlement_id, settlement):
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        row = database.execute(
            """
            SELECT campaign_id, settlement_id, name, services, availability
            FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?
            """,
            (campaign_id, settlement_id),
        ).fetchone()
        if row is None:
            return "unknown_settlement", None
        database.execute(
            """
            UPDATE play_campaign_settlements
            SET name = ?, services = ?, availability = ?
            WHERE campaign_id = ? AND settlement_id = ?
            """,
            (settlement["name"], encode_json(settlement["services"]),
             settlement["availability"], campaign_id, settlement_id),
        )
        row = dict(row)
        row.update(settlement)
        row["campaign_id"] = campaign_id
        row["settlement_id"] = settlement_id
        row["services"] = encode_json(settlement["services"])
        return "updated", _play_campaign_settlement(database, row)


def discover_play_campaign_settlement(campaign_id, actor, settlement_id):
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            """
            SELECT character_id FROM play_campaign_members
            WHERE campaign_id = ? AND username = ?
            """,
            (campaign_id, actor),
        ).fetchone()
        if member is None:
            return "not_member", None
        row = database.execute(
            """
            SELECT campaign_id, settlement_id, name, services, availability
            FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?
            """,
            (campaign_id, settlement_id),
        ).fetchone()
        if row is None:
            return "unknown_settlement", None
        exists = database.execute(
            """
            SELECT 1 FROM play_campaign_settlement_discoveries
            WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?
            """,
            (campaign_id, settlement_id, member["character_id"]),
        ).fetchone()
        if exists is None:
            database.execute(
                """
                INSERT INTO play_campaign_settlement_discoveries
                    (campaign_id, settlement_id, character_id)
                VALUES (?, ?, ?)
                """,
                (campaign_id, settlement_id, member["character_id"]),
            )
            result = "discovered"
        else:
            result = "already_discovered"
        return result, _play_campaign_settlement(database, row, member["character_id"])


def get_play_campaign_settlements(campaign_id, actor):
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            """
            SELECT character_id FROM play_campaign_members
            WHERE campaign_id = ? AND username = ?
            """,
            (campaign_id, actor),
        ).fetchone()
        if campaign["owner"] != actor and member is None:
            return "not_member", None
        rows = database.execute(
            """
            SELECT campaign_id, settlement_id, name, services, availability
            FROM play_campaign_settlements WHERE campaign_id = ?
            ORDER BY creation_order ASC
            """,
            (campaign_id,),
        ).fetchall()
        character_id = None if campaign["owner"] == actor else member["character_id"]
        settlements = []
        for row in rows:
            item = _play_campaign_settlement(database, row, character_id)
            if character_id is None or item["discovered_by"]:
                settlements.append(item)
    return "found", {"settlements": settlements}


def _play_campaign_shop(row):
    return {
        "shop_id": row["shop_id"],
        "name": row["name"],
        "stock": decode_json(row["stock"]),
        "buy_price": row["buy_price"],
        "sell_price": row["sell_price"],
    }


def create_play_campaign_shop(campaign_id, owner, settlement_id, shop):
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != owner:
                return "not_owner", None
            settlement = database.execute(
                """
                SELECT 1 FROM play_campaign_settlements
                WHERE campaign_id = ? AND settlement_id = ?
                """,
                (campaign_id, settlement_id),
            ).fetchone()
            if settlement is None:
                return "unknown_settlement", None
            database.execute(
                """
                INSERT INTO play_campaign_shops
                    (campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (campaign_id, settlement_id, shop["shop_id"], shop["name"],
                 encode_json(shop["stock"]), shop["buy_price"], shop["sell_price"]),
            )
    except sqlite3.IntegrityError:
        return "duplicate", None
    return "created", shop


def get_play_campaign_shop(campaign_id, actor, settlement_id, shop_id):
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            """
            SELECT character_id FROM play_campaign_members
            WHERE campaign_id = ? AND username = ?
            """,
            (campaign_id, actor),
        ).fetchone()
        if campaign["owner"] != actor and member is None:
            return "not_member", None
        settlement = database.execute(
            """
            SELECT 1 FROM play_campaign_settlements
            WHERE campaign_id = ? AND settlement_id = ?
            """,
            (campaign_id, settlement_id),
        ).fetchone()
        if settlement is None:
            return "unknown_settlement", None
        shop = database.execute(
            """
            SELECT shop_id, name, stock, buy_price, sell_price
            FROM play_campaign_shops
            WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?
            """,
            (campaign_id, settlement_id, shop_id),
        ).fetchone()
        if shop is None:
            return "unknown_shop", None
        if campaign["owner"] != actor:
            discovered = database.execute(
                """
                SELECT 1 FROM play_campaign_settlement_discoveries
                WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?
                """,
                (campaign_id, settlement_id, member["character_id"]),
            ).fetchone()
            if discovered is None:
                return "undiscovered", None
    return "found", _play_campaign_shop(shop)


def trade_play_campaign_shop(campaign_id, actor, settlement_id, shop_id, character_id,
                             item_id, quantity, operation):
    """Atomically settle a shop trade after verifying the owner's inventory."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        settlement = database.execute(
            """
            SELECT 1 FROM play_campaign_settlements
            WHERE campaign_id = ? AND settlement_id = ?
            """,
            (campaign_id, settlement_id),
        ).fetchone()
        if settlement is None:
            return "unknown_settlement", None
        shop = database.execute(
            """
            SELECT stock, buy_price, sell_price FROM play_campaign_shops
            WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?
            """,
            (campaign_id, settlement_id, shop_id),
        ).fetchone()
        if shop is None:
            return "unknown_shop", None
        character = database.execute(
            """
            SELECT o.owner FROM play_campaign_members AS m
            LEFT JOIN play_campaign_character_owners AS o
              ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
            WHERE m.campaign_id = ? AND m.character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        if character["owner"] != actor:
            return "not_owner", None

        stock = decode_json(shop["stock"])
        if operation == "buy":
            available = stock.get(item_id, 0)
            if available < quantity:
                return "insufficient_stock", None
            database.execute(
                """
                INSERT OR IGNORE INTO play_campaign_character_currency
                    (campaign_id, character_id, gold)
                VALUES (?, ?, 10)
                """,
                (campaign_id, character_id),
            )
            gold = database.execute(
                """
                SELECT gold FROM play_campaign_character_currency
                WHERE campaign_id = ? AND character_id = ?
                """,
                (campaign_id, character_id),
            ).fetchone()["gold"]
            cost = shop["buy_price"] * quantity
            if gold < cost:
                return "insufficient_gold", None
            gold -= cost
            stock[item_id] = available - quantity
            database.execute(
                """
                INSERT INTO play_campaign_character_inventory_items
                    (campaign_id, character_id, item_id, quantity)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET
                    quantity = quantity + excluded.quantity
                """,
                (campaign_id, character_id, item_id, quantity),
            )
        else:
            inventory = database.execute(
                """
                SELECT quantity FROM play_campaign_character_inventory_items
                WHERE campaign_id = ? AND character_id = ? AND item_id = ?
                """,
                (campaign_id, character_id, item_id),
            ).fetchone()
            if inventory is None or inventory["quantity"] < quantity:
                return "insufficient_inventory", None
            database.execute(
                """
                INSERT OR IGNORE INTO play_campaign_character_currency
                    (campaign_id, character_id, gold)
                VALUES (?, ?, 10)
                """,
                (campaign_id, character_id),
            )
            gold = database.execute(
                """
                SELECT gold FROM play_campaign_character_currency
                WHERE campaign_id = ? AND character_id = ?
                """,
                (campaign_id, character_id),
            ).fetchone()["gold"] + shop["sell_price"] * quantity
            stock[item_id] = stock.get(item_id, 0) + quantity

        database.execute(
            """
            UPDATE play_campaign_character_currency SET gold = ?
            WHERE campaign_id = ? AND character_id = ?
            """,
            (gold, campaign_id, character_id),
        )
        database.execute(
            """
            UPDATE play_campaign_shops SET stock = ?
            WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?
            """,
            (encode_json(stock), campaign_id, settlement_id, shop_id),
        )
    return "traded", {
        "character_id": character_id,
        "item_id": item_id,
        "quantity": quantity,
        "gold": gold,
        "stock": stock[item_id],
    }


def create_play_campaign_faction(campaign_id, owner, faction):
    """Create one DM-managed faction in a play campaign."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != owner:
                return "not_owner", None
            database.execute(
                """
                INSERT INTO play_campaign_factions (campaign_id, faction_id, name)
                VALUES (?, ?, ?)
                """,
                (campaign_id, faction["faction_id"], faction["name"]),
            )
    except sqlite3.IntegrityError:
        return "duplicate", None
    return "created", faction


def change_play_campaign_reputation(campaign_id, owner, faction_id, change):
    """Apply a bounded reputation change and preserve its immutable history."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        faction = database.execute(
            """
            SELECT 1 FROM play_campaign_factions
            WHERE campaign_id = ? AND faction_id = ?
            """,
            (campaign_id, faction_id),
        ).fetchone()
        if faction is None:
            return "unknown_faction", None
        member = database.execute(
            """
            SELECT 1 FROM play_campaign_members
            WHERE campaign_id = ? AND character_id = ?
            """,
            (campaign_id, change["character_id"]),
        ).fetchone()
        if member is None:
            return "unknown_character", None
        current = database.execute(
            """
            SELECT reputation FROM play_campaign_reputation_history
            WHERE campaign_id = ? AND faction_id = ? AND character_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (campaign_id, faction_id, change["character_id"]),
        ).fetchone()
        reputation = max(-100, min(100, (current["reputation"] if current else 0) + change["delta"]))
        record = {
            "faction_id": faction_id,
            "character_id": change["character_id"],
            "reputation": reputation,
            "delta": change["delta"],
            "reason": change["reason"],
        }
        database.execute(
            """
            INSERT INTO play_campaign_reputation_history
                (campaign_id, faction_id, character_id, reputation, delta, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (campaign_id, faction_id, record["character_id"], reputation,
             record["delta"], record["reason"]),
        )
    return "created", record


def get_play_campaign_reputation(campaign_id, actor, faction_id):
    """Return faction reputation history visible to a campaign participant."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            """
            SELECT character_id FROM play_campaign_members
            WHERE campaign_id = ? AND username = ?
            """,
            (campaign_id, actor),
        ).fetchone()
        if actor != campaign["owner"] and member is None:
            return "not_member", None
        faction = database.execute(
            """
            SELECT 1 FROM play_campaign_factions
            WHERE campaign_id = ? AND faction_id = ?
            """,
            (campaign_id, faction_id),
        ).fetchone()
        if faction is None:
            return "unknown_faction", None
        query = """
            SELECT faction_id, character_id, reputation, delta, reason
            FROM play_campaign_reputation_history
            WHERE campaign_id = ? AND faction_id = ?
        """
        parameters = [campaign_id, faction_id]
        if actor != campaign["owner"]:
            query += " AND character_id = ?"
            parameters.append(member["character_id"])
        query += " ORDER BY id"
        entries = [dict(row) for row in database.execute(query, parameters).fetchall()]
    return "found", {"faction_id": faction_id, "entries": entries}


def remove_play_campaign_character_inventory_item(campaign_id, actor, character_id, item_id, quantity):
    """Atomically remove from an owned character's item stack."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        character = database.execute(
            """
            SELECT o.owner FROM play_campaign_members AS m
            LEFT JOIN play_campaign_character_owners AS o
              ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
            WHERE m.campaign_id = ? AND m.character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        if character["owner"] != actor:
            return "not_owner", None
        stack = database.execute(
            """
            SELECT quantity FROM play_campaign_character_inventory_items
            WHERE campaign_id = ? AND character_id = ? AND item_id = ?
            """,
            (campaign_id, character_id, item_id),
        ).fetchone()
        if stack is None or quantity > stack["quantity"]:
            return "insufficient", None
        total_quantity = stack["quantity"] - quantity
        if total_quantity == 0:
            database.execute(
                """
                DELETE FROM play_campaign_character_inventory_items
                WHERE campaign_id = ? AND character_id = ? AND item_id = ?
                """,
                (campaign_id, character_id, item_id),
            )
        else:
            database.execute(
                """
                UPDATE play_campaign_character_inventory_items SET quantity = ?
                WHERE campaign_id = ? AND character_id = ? AND item_id = ?
                """,
                (total_quantity, campaign_id, character_id, item_id),
            )
    return "updated", {
        "character_id": character_id,
        "item_id": item_id,
        "quantity": quantity,
        "total_quantity": total_quantity,
    }


def consume_play_campaign_character_inventory_item(campaign_id, actor, character_id, item_id):
    """Atomically consume one item from an owned character inventory stack."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        result, character = _play_equipment_character(database, campaign_id, character_id)
        if result != "found":
            return result, None
        if character["owner"] != actor:
            return "not_owner", None
        stack = database.execute(
            """
            SELECT quantity FROM play_campaign_character_inventory_items
            WHERE campaign_id = ? AND character_id = ? AND item_id = ?
            """,
            (campaign_id, character_id, item_id),
        ).fetchone()
        if stack is None or stack["quantity"] <= 0:
            return "insufficient", None
        total_quantity = stack["quantity"] - 1
        if total_quantity == 0:
            database.execute(
                """
                DELETE FROM play_campaign_character_inventory_items
                WHERE campaign_id = ? AND character_id = ? AND item_id = ?
                """,
                (campaign_id, character_id, item_id),
            )
        else:
            database.execute(
                """
                UPDATE play_campaign_character_inventory_items SET quantity = ?
                WHERE campaign_id = ? AND character_id = ? AND item_id = ?
                """,
                (total_quantity, campaign_id, character_id, item_id),
            )
    return "updated", {
        "character_id": character_id,
        "item_id": item_id,
        "quantity_consumed": 1,
        "total_quantity": total_quantity,
    }


def _play_equipment_character(database, campaign_id, character_id):
    """Resolve a play campaign and character for equipment operations."""
    campaign = database.execute(
        "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if campaign is None:
        return "unknown_campaign", None
    character = database.execute(
        """
        SELECT o.owner FROM play_campaign_members AS m
        LEFT JOIN play_campaign_character_owners AS o
          ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
        WHERE m.campaign_id = ? AND m.character_id = ?
        """,
        (campaign_id, character_id),
    ).fetchone()
    if character is None:
        return "unknown_character", None
    return "found", character


def equip_play_campaign_character_item(campaign_id, actor, character_id, slot, item_id):
    """Equip an owned inventory item in its already-validated legal slot."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        result, character = _play_equipment_character(database, campaign_id, character_id)
        if result != "found":
            return result, None
        if character["owner"] != actor:
            return "not_owner", None
        held = database.execute(
            """
            SELECT 1 FROM play_campaign_character_inventory_items
            WHERE campaign_id = ? AND character_id = ? AND item_id = ? AND quantity > 0
            """,
            (campaign_id, character_id, item_id),
        ).fetchone()
        if held is None:
            return "unheld", None
        database.execute(
            """
            INSERT INTO play_campaign_character_equipment
                (campaign_id, character_id, slot, item_id, attuned)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET
                item_id = excluded.item_id, attuned = 0
            """,
            (campaign_id, character_id, slot, item_id),
        )
    return "equipped", {
        "character_id": character_id,
        "slot": slot,
        "item_id": item_id,
        "attuned": False,
    }


def get_play_campaign_character_equipment(campaign_id, actor, character_id, slot):
    """Read one equipment slot as any member of the campaign."""
    with connection() as database:
        result, _ = _play_equipment_character(database, campaign_id, character_id)
        if result != "found":
            return result, None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if member is None:
            return "not_member", None
        equipment = database.execute(
            """
            SELECT item_id, attuned FROM play_campaign_character_equipment
            WHERE campaign_id = ? AND character_id = ? AND slot = ?
            """,
            (campaign_id, character_id, slot),
        ).fetchone()
    return "found", {
        "character_id": character_id,
        "slot": slot,
        "item_id": "" if equipment is None else equipment["item_id"],
        "attuned": False if equipment is None else bool(equipment["attuned"]),
    }


def attune_play_campaign_character_equipment(campaign_id, actor, character_id, slot, attunable_item_ids):
    """Attune an owned, equipped item when the character has capacity."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        result, character = _play_equipment_character(database, campaign_id, character_id)
        if result != "found":
            return result, None
        if character["owner"] != actor:
            return "not_owner", None
        equipment = database.execute(
            """
            SELECT item_id, attuned FROM play_campaign_character_equipment
            WHERE campaign_id = ? AND character_id = ? AND slot = ?
            """,
            (campaign_id, character_id, slot),
        ).fetchone()
        if equipment is None:
            return "not_equipped", None
        if equipment["item_id"] not in attunable_item_ids:
            return "cannot_attune", None
        if equipment["attuned"]:
            return "attunement_limit", None
        attunement_count = database.execute(
            """
            SELECT COUNT(*) AS count FROM play_campaign_character_equipment
            WHERE campaign_id = ? AND character_id = ? AND attuned = 1
            """,
            (campaign_id, character_id),
        ).fetchone()["count"]
        if attunement_count >= 1:
            return "attunement_limit", None
        database.execute(
            """
            UPDATE play_campaign_character_equipment SET attuned = 1
            WHERE campaign_id = ? AND character_id = ? AND slot = ?
            """,
            (campaign_id, character_id, slot),
        )
    return "attuned", {
        "character_id": character_id,
        "slot": slot,
        "item_id": equipment["item_id"],
        "attuned": True,
        "attunement_count": 1,
        "max_attunements": 1,
    }


def level_up_play_campaign_character(campaign_id, actor, character_id, level, hit_dice):
    """Advance an owned character exactly one level with fixed average HP."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        character = database.execute(
            """
            SELECT m.level, m.con_modifier, m.character_class, m.class, o.owner
            FROM play_campaign_members AS m
            LEFT JOIN play_campaign_character_owners AS o
              ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
            WHERE m.campaign_id = ? AND m.character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        if character["owner"] != actor:
            return "not_owner", None
        if level != character["level"] + 1:
            return "invalid_level", None

        die_sides = int(hit_dice.removeprefix("1d"))
        # The fixed, round-up average makes level progression deterministic.
        hp_max = die_sides + character["con_modifier"] + (
            level - 1
        ) * (die_sides // 2 + 1 + character["con_modifier"])
        database.execute(
            """
            UPDATE play_campaign_members SET level = ?, hp_max = ?
            WHERE campaign_id = ? AND character_id = ?
            """,
            (level, hp_max, campaign_id, character_id),
        )
    return "leveled_up", {
        "character_id": character_id,
        "level": level,
        "hp_max": hp_max,
        "hit_dice": hit_dice,
    }


def claim_play_campaign_character(campaign_id, actor, character_id):
    """Atomically assign an unowned campaign character to a member."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if member is None:
            return "not_member", None
        character = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        ownership = database.execute(
            """
            SELECT owner FROM play_campaign_character_owners
            WHERE campaign_id = ? AND character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if ownership is not None and ownership["owner"] is not None:
            return "already_owned", None
        if ownership is None:
            database.execute(
                """
                INSERT INTO play_campaign_character_owners (campaign_id, character_id, owner)
                VALUES (?, ?, ?)
                """,
                (campaign_id, character_id, actor),
            )
        else:
            database.execute(
                """
                UPDATE play_campaign_character_owners SET owner = ?
                WHERE campaign_id = ? AND character_id = ?
                """,
                (actor, campaign_id, character_id),
            )
    return "claimed", {"character_id": character_id, "owner": actor}


def transfer_play_campaign_character(campaign_id, actor, character_id, new_owner):
    """Transfer character ownership only from its current owner to a member."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        character = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        ownership = database.execute(
            """
            SELECT owner FROM play_campaign_character_owners
            WHERE campaign_id = ? AND character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        if ownership is None or ownership["owner"] != actor:
            return "not_owner", None
        recipient = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, new_owner),
        ).fetchone()
        if recipient is None:
            return "new_owner_not_member", None
        database.execute(
            """
            UPDATE play_campaign_character_owners SET owner = ?
            WHERE campaign_id = ? AND character_id = ?
            """,
            (new_owner, campaign_id, character_id),
        )
    return "transferred", {"character_id": character_id, "owner": new_owner}


def save_play_campaign_document(campaign_id, owner, document):
    """Replace a campaign document when requested by its owner."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        database.execute(
            """
            INSERT INTO play_campaign_documents (campaign_id, story, dm_notes)
            VALUES (?, ?, ?)
            ON CONFLICT(campaign_id) DO UPDATE SET
                story = excluded.story,
                dm_notes = excluded.dm_notes
            """,
            (campaign_id, document["story"], document["dm_notes"]),
        )
    return "saved", document


def get_play_campaign_document(campaign_id, username):
    """Read a document, retaining DM notes only for the campaign owner."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        is_member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if campaign["owner"] != username and is_member is None:
            return "not_member", None
        document = database.execute(
            "SELECT story, dm_notes FROM play_campaign_documents WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    if document is None:
        document = {"story": "", "dm_notes": ""}
    else:
        document = dict(document)
    if campaign["owner"] != username:
        document = {"story": document["story"]}
    return "found", document


def create_play_campaign_backup(campaign_id, owner):
    """Snapshot the owner's current public campaign state in sequence order."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        story = database.execute(
            "SELECT story FROM play_campaign_documents WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()["story"]
        sequence = database.execute(
            "SELECT COUNT(*) + 1 AS sequence FROM play_campaign_backups WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["sequence"]
        backup = {
            "backup_id": f"backup-{sequence}",
            "story": story,
            "status": campaign["status"],
        }
        database.execute(
            """
            INSERT INTO play_campaign_backups (campaign_id, backup_id, story, status)
            VALUES (?, ?, ?, ?)
            """,
            (campaign_id, backup["backup_id"], backup["story"], backup["status"]),
        )
    return "created", backup


def get_play_campaign_backups(campaign_id, owner):
    """Return the owner's immutable snapshots in creation order."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        backups = database.execute(
            """
            SELECT backup_id, story, status FROM play_campaign_backups
            WHERE campaign_id = ? ORDER BY creation_order
            """,
            (campaign_id,),
        ).fetchall()
    return "found", {"backups": [dict(backup) for backup in backups]}


def restore_play_campaign_backup(campaign_id, owner, backup_id):
    """Apply one snapshot while leaving its stored representation untouched."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        backup = database.execute(
            """
            SELECT backup_id, story, status FROM play_campaign_backups
            WHERE campaign_id = ? AND backup_id = ?
            """,
            (campaign_id, backup_id),
        ).fetchone()
        if backup is None:
            return "unknown_backup", None
        backup = dict(backup)
        database.execute(
            "UPDATE play_campaigns SET status = ? WHERE id = ?",
            (backup["status"], campaign_id),
        )
        database.execute(
            "UPDATE play_campaign_documents SET story = ? WHERE campaign_id = ?",
            (backup["story"], campaign_id),
        )
    return "restored", backup


def create_play_campaign_export(campaign_id, owner):
    """Persist the owner's current public document as the next export version."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        document = database.execute(
            "SELECT story FROM play_campaign_documents WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
        version = database.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS version "
            "FROM play_campaign_exports WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["version"]
        exported = {
            "version": version,
            "story": "" if document is None else document["story"],
            "status": campaign["status"],
        }
        database.execute(
            """
            INSERT INTO play_campaign_exports (campaign_id, version, story, status)
            VALUES (?, ?, ?, ?)
            """,
            (campaign_id, version, exported["story"], exported["status"]),
        )
    return "created", exported


def get_play_campaign_exports(campaign_id, owner):
    """Return all immutable exports after verifying campaign ownership."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        rows = database.execute(
            """
            SELECT version, story, status FROM play_campaign_exports
            WHERE campaign_id = ? ORDER BY version ASC
            """,
            (campaign_id,),
        ).fetchall()
    return "found", [dict(row) for row in rows]


def get_play_campaign_export(campaign_id, owner, version):
    """Return one immutable export after verifying campaign ownership."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        exported = database.execute(
            """
            SELECT version, story, status FROM play_campaign_exports
            WHERE campaign_id = ? AND version = ?
            """,
            (campaign_id, version),
        ).fetchone()
    if exported is None:
        return "unknown_export", None
    return "found", dict(exported)


def import_play_campaign_snapshot(campaign_id, owner, snapshot):
    """Atomically apply and retain a validated version-one campaign snapshot."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None

        database.execute(
            "UPDATE play_campaigns SET status = ? WHERE id = ?",
            (snapshot["status"], campaign_id),
        )
        database.execute(
            "UPDATE play_campaign_documents SET story = ? WHERE campaign_id = ?",
            (snapshot["story"], campaign_id),
        )
        database.execute(
            """
            INSERT INTO play_campaign_import_states (campaign_id, version, story, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(campaign_id) DO UPDATE SET
                version = excluded.version,
                story = excluded.story,
                status = excluded.status
            """,
            (campaign_id, snapshot["version"], snapshot["story"], snapshot["status"]),
        )
    return "imported", snapshot


def get_play_campaign_import_state(campaign_id, owner):
    """Return the latest imported snapshot after verifying campaign ownership."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        snapshot = database.execute(
            """
            SELECT version, story, status FROM play_campaign_import_states
            WHERE campaign_id = ?
            """,
            (campaign_id,),
        ).fetchone()
    if snapshot is None:
        return "unknown_import", None
    return "found", dict(snapshot)


def migrate_play_campaign_snapshot(campaign_id, owner, story):
    """Migrate one legacy version-one snapshot into the version-two shape."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner, name FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None

        migrated = {
            "schema_version": 2,
            "story": story,
            "campaign_name": campaign["name"],
        }
        existing = database.execute(
            """
            SELECT story, campaign_name FROM play_campaign_migration_states
            WHERE campaign_id = ?
            """,
            (campaign_id,),
        ).fetchone()
        if existing is not None and dict(existing) == {
            "story": migrated["story"],
            "campaign_name": migrated["campaign_name"],
        }:
            return "unchanged", migrated
        database.execute(
            """
            INSERT INTO play_campaign_migration_states (campaign_id, story, campaign_name)
            VALUES (?, ?, ?)
            ON CONFLICT(campaign_id) DO UPDATE SET
                story = excluded.story,
                campaign_name = excluded.campaign_name
            """,
            (campaign_id, migrated["story"], migrated["campaign_name"]),
        )
    return "migrated", migrated


def get_play_campaign_migration_state(campaign_id, owner):
    """Return the latest migrated state after verifying campaign ownership."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        migrated = database.execute(
            """
            SELECT story, campaign_name FROM play_campaign_migration_states
            WHERE campaign_id = ?
            """,
            (campaign_id,),
        ).fetchone()
    if migrated is None:
        return "unknown_migration", None
    return "found", {"schema_version": 2, **dict(migrated)}


def create_play_campaign_scene(campaign_id, owner, scene):
    """Create a uniquely identified open scene for the campaign owner."""
    try:
        with connection() as database:
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != owner:
                return "not_owner", None
            database.execute(
                """
                INSERT INTO play_campaign_scenes (campaign_id, id, name, status)
                VALUES (?, ?, ?, 'open')
                """,
                (campaign_id, scene["id"], scene["name"]),
            )
    except sqlite3.IntegrityError:
        return "duplicate", None
    return "created", {"id": scene["id"], "name": scene["name"], "status": "open"}


def enter_play_campaign_scene(campaign_id, owner, scene_id):
    """Set an open scene as the campaign's current scene."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        scene = database.execute(
            "SELECT name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?",
            (campaign_id, scene_id),
        ).fetchone()
        if scene is None:
            return "unknown_scene", None
        if scene["status"] != "open":
            return "closed", None
        database.execute(
            """
            INSERT INTO play_campaign_current_scenes (campaign_id, scene_id)
            VALUES (?, ?)
            ON CONFLICT(campaign_id) DO UPDATE SET scene_id = excluded.scene_id
            """,
            (campaign_id, scene_id),
        )
    return "entered", {"current_scene_id": scene_id, "name": scene["name"]}


def close_play_campaign_scene(campaign_id, owner, scene_id):
    """Mark one owner-controlled scene as closed."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        scene = database.execute(
            "SELECT 1 FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?",
            (campaign_id, scene_id),
        ).fetchone()
        if scene is None:
            return "unknown_scene", None
        database.execute(
            "UPDATE play_campaign_scenes SET status = 'closed' WHERE campaign_id = ? AND id = ?",
            (campaign_id, scene_id),
        )
        # A closed scene is a durable campaign transition.  It has no sequence
        # in its HTTP representation, but it still occupies one identity in
        # the shared event stream used by subsequent play events.
        next_play_campaign_event_sequence(database, campaign_id, "scene_closed")
    return "closed", {"id": scene_id, "status": "closed"}


def get_play_campaign_current_scene(campaign_id, username):
    """Read the open current scene for a campaign owner or member."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if campaign["owner"] != username and member is None:
            return "not_member", None
        scene = database.execute(
            """
            SELECT scene.id, scene.name, scene.status
            FROM play_campaign_current_scenes AS current
            JOIN play_campaign_scenes AS scene
              ON scene.campaign_id = current.campaign_id AND scene.id = current.scene_id
            WHERE current.campaign_id = ? AND scene.status = 'open'
            """,
            (campaign_id,),
        ).fetchone()
    if scene is None:
        return "not_set", None
    return "found", dict(scene)


def create_play_campaign_location(campaign_id, owner, location):
    """Create a uniquely identified location for the campaign owner."""
    try:
        with connection() as database:
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            if campaign["owner"] != owner:
                return "not_owner", None
            database.execute(
                """
                INSERT INTO play_campaign_locations (campaign_id, id, name)
                VALUES (?, ?, ?)
                """,
                (campaign_id, location["id"], location["name"]),
            )
            # The first location establishes the party's initial position.
            database.execute(
                """
                INSERT INTO play_campaign_current_locations (campaign_id, location_id)
                VALUES (?, ?)
                ON CONFLICT(campaign_id) DO NOTHING
                """,
                (campaign_id, location["id"]),
            )
    except sqlite3.IntegrityError:
        return "duplicate", None
    return "created", location


def create_play_campaign_location_connection(campaign_id, owner, location_connection):
    """Create one directed connection when both campaign locations exist."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        from_location = database.execute(
            "SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?",
            (campaign_id, location_connection["from_id"]),
        ).fetchone()
        to_location = database.execute(
            "SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?",
            (campaign_id, location_connection["to_id"]),
        ).fetchone()
        if from_location is None or to_location is None:
            return "unknown_location", None
        existing = database.execute(
            """
            SELECT 1 FROM play_campaign_location_connections
            WHERE campaign_id = ? AND from_id = ? AND to_id = ?
            """,
            (
                campaign_id,
                location_connection["from_id"],
                location_connection["to_id"],
            ),
        ).fetchone()
        if existing is not None:
            return "duplicate", None
        database.execute(
            """
            INSERT INTO play_campaign_location_connections
                (campaign_id, from_id, to_id, travel_turns)
            VALUES (?, ?, ?, ?)
            """,
            (
                campaign_id,
                location_connection["from_id"],
                location_connection["to_id"],
                location_connection["travel_turns"],
            ),
        )
    return "created", location_connection


def get_play_campaign_location_travel(campaign_id, username, location_id):
    """Return a member-visible, deterministically ordered outbound travel list."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if campaign["owner"] != username and member is None:
            return "not_member", None
        location = database.execute(
            "SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?",
            (campaign_id, location_id),
        ).fetchone()
        if location is None:
            return "unknown_location", None
        destinations = database.execute(
            """
            SELECT location.id, location.name, connection.travel_turns
            FROM play_campaign_location_connections AS connection
            JOIN play_campaign_locations AS location
              ON location.campaign_id = connection.campaign_id
             AND location.id = connection.to_id
            WHERE connection.campaign_id = ? AND connection.from_id = ?
            ORDER BY location.id ASC
            """,
            (campaign_id, location_id),
        ).fetchall()
    return "found", {"destinations": [dict(destination) for destination in destinations]}


def submit_play_campaign_travel(campaign_id, actor, destination_id):
    """Move the party along an outbound edge and give the turn to the DM."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if member is None:
            return "not_member", None
        turn = database.execute(
            "SELECT current_actor FROM play_campaign_turns WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if turn is None:
            return "not_active", None
        if turn["current_actor"] != actor:
            return "not_your_turn", None
        current_location = database.execute(
            "SELECT location_id FROM play_campaign_current_locations WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if current_location is None:
            return "invalid_destination", None
        travel_connection = database.execute(
            """
            SELECT travel_turns FROM play_campaign_location_connections
            WHERE campaign_id = ? AND from_id = ? AND to_id = ?
            """,
            (campaign_id, current_location["location_id"], destination_id),
        ).fetchone()
        if travel_connection is None:
            return "invalid_destination", None
        sequence = next_play_campaign_event_sequence(database, campaign_id, "travel")
        database.execute(
            """
            INSERT INTO play_campaign_travels
                (campaign_id, sequence, actor, destination_id, travel_turns)
            VALUES (?, ?, ?, ?, ?)
            """,
            (campaign_id, sequence, actor, destination_id, travel_connection["travel_turns"]),
        )
        database.execute(
            "UPDATE play_campaign_current_locations SET location_id = ? WHERE campaign_id = ?",
            (destination_id, campaign_id),
        )
        database.execute(
            "UPDATE play_campaign_turns SET current_actor = ? WHERE campaign_id = ?",
            (campaign["owner"], campaign_id),
        )
    return "created", {
        "sequence": sequence,
        "kind": "travel",
        "actor": actor,
        "destination_id": destination_id,
        "travel_turns": travel_connection["travel_turns"],
        "next_actor": campaign["owner"],
    }


def add_play_campaign_member(campaign_id, member):
    """Atomically add a player to a lobby campaign when capacity permits.

    The table constraints make player and character duplication durable, while
    the immediate transaction prevents two simultaneous requests from both
    observing a final free party slot.
    """
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT status, max_players FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign"
        if campaign["status"] != "lobby":
            return "not_lobby"
        duplicate = database.execute(
            """
            SELECT 1 FROM play_campaign_members
            WHERE campaign_id = ? AND (username = ? OR character_id = ?)
            """,
            (campaign_id, member["username"], member["character_id"]),
        ).fetchone()
        if duplicate is not None:
            return "duplicate"
        count = database.execute(
            "SELECT COUNT(*) AS count FROM play_campaign_members WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["count"]
        if count >= campaign["max_players"]:
            return "full"
        database.execute(
            """
            INSERT INTO play_campaign_members
                (campaign_id, username, character_id, name, class, hp_current, hp_max)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                member["username"],
                member["character_id"],
                member["name"],
                member["class"],
                member.get("hp_current", 20),
                member.get("hp_max", 20),
            ),
        )
        database.execute(
            """
            INSERT INTO play_campaign_character_owners
                (campaign_id, character_id, owner)
            VALUES (?, ?, ?)
            """,
            (campaign_id, member["character_id"], member["username"]),
        )
        database.execute(
            """
            INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold)
            VALUES (?, ?, 10)
            """,
            (campaign_id, member["character_id"]),
        )
    return "created"


def create_play_campaign_invitation(campaign_id, owner, invitation):
    """Create one pending invitation after checking campaign ownership."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        if database.execute(
            "SELECT 1 FROM play_campaign_invitations "
            "WHERE campaign_id = ? AND invitation_id = ?",
            (campaign_id, invitation["invitation_id"]),
        ).fetchone() is not None:
            return "duplicate_id", None
        if database.execute(
            "SELECT 1 FROM play_campaign_invitations "
            "WHERE campaign_id = ? AND username = ? AND status = 'pending'",
            (campaign_id, invitation["username"]),
        ).fetchone() is not None:
            return "duplicate_pending", None
        database.execute(
            """
            INSERT INTO play_campaign_invitations
                (campaign_id, invitation_id, username, character_id, status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (
                campaign_id,
                invitation["invitation_id"],
                invitation["username"],
                invitation["character_id"],
            ),
        )
    return "created", {**invitation, "status": "pending"}


def accept_play_campaign_invitation(campaign_id, username, invitation_id):
    """Accept an invite and add its target as a campaign member atomically."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        if database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return "unknown_campaign", None
        invitation = database.execute(
            """
            SELECT invitation_id, username, character_id, status
            FROM play_campaign_invitations
            WHERE campaign_id = ? AND invitation_id = ?
            """,
            (campaign_id, invitation_id),
        ).fetchone()
        if invitation is None:
            return "unknown_invitation", None
        if invitation["username"] != username:
            return "not_target", None
        if invitation["status"] != "pending":
            return "already_accepted", None
        if database.execute(
            "SELECT 1 FROM play_campaign_members "
            "WHERE campaign_id = ? AND (username = ? OR character_id = ?)",
            (campaign_id, username, invitation["character_id"]),
        ).fetchone() is not None:
            return "membership_exists", None
        database.execute(
            """
            INSERT INTO play_campaign_members
                (campaign_id, username, character_id, name, class)
            VALUES (?, ?, ?, ?, ?)
            """,
            (campaign_id, username, invitation["character_id"], invitation["character_id"], "unknown"),
        )
        database.execute(
            """
            INSERT INTO play_campaign_character_owners
                (campaign_id, character_id, owner)
            VALUES (?, ?, ?)
            """,
            (campaign_id, invitation["character_id"], username),
        )
        database.execute(
            """
            INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold)
            VALUES (?, ?, 10)
            """,
            (campaign_id, invitation["character_id"]),
        )
        database.execute(
            "UPDATE play_campaign_invitations SET status = 'accepted' "
            "WHERE campaign_id = ? AND invitation_id = ?",
            (campaign_id, invitation_id),
        )
    return "accepted", {
        "invitation_id": invitation["invitation_id"],
        "username": invitation["username"],
        "character_id": invitation["character_id"],
        "status": "accepted",
    }


def get_play_campaign_invitations(campaign_id, username):
    """List all invites for a DM, or just the caller's own invites otherwise."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] == username:
            rows = database.execute(
                """
                SELECT invitation_id, username, character_id, status
                FROM play_campaign_invitations WHERE campaign_id = ?
                ORDER BY creation_order
                """,
                (campaign_id,),
            )
        else:
            rows = database.execute(
                """
                SELECT invitation_id, username, character_id, status
                FROM play_campaign_invitations
                WHERE campaign_id = ? AND username = ?
                ORDER BY creation_order
                """,
                (campaign_id, username),
            )
        return "listed", [dict(row) for row in rows]


def grant_play_campaign_delegation(campaign_id, owner, username, powers):
    """Grant a member a durable, narrowly scoped campaign delegation."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        if database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone() is None:
            return "not_member", None
        existing = database.execute(
            "SELECT active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if existing is not None and existing["active"]:
            return "already_active", None
        if existing is None:
            database.execute(
                "INSERT INTO play_campaign_delegations (campaign_id, username, powers, active) VALUES (?, ?, ?, 1)",
                (campaign_id, username, encode_json(powers)),
            )
        else:
            database.execute(
                "UPDATE play_campaign_delegations SET powers = ?, active = 1 WHERE campaign_id = ? AND username = ?",
                (encode_json(powers), campaign_id, username),
            )
        database.execute(
            "INSERT INTO play_campaign_delegation_audit (campaign_id, username, action, powers) VALUES (?, ?, 'granted', ?)",
            (campaign_id, username, encode_json(powers)),
        )
    return "created", {"username": username, "powers": powers, "active": True}


def revoke_play_campaign_delegation(campaign_id, owner, username):
    """Deactivate a delegation while retaining its audit history."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        delegation = database.execute(
            "SELECT powers, active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if delegation is None or not delegation["active"]:
            return "not_active", None
        powers = decode_json(delegation["powers"])
        database.execute(
            "UPDATE play_campaign_delegations SET active = 0 WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        )
        database.execute(
            "INSERT INTO play_campaign_delegation_audit (campaign_id, username, action, powers) VALUES (?, ?, 'revoked', ?)",
            (campaign_id, username, encode_json(powers)),
        )
    return "revoked", {"username": username, "powers": powers, "active": False}


def get_play_campaign_delegation_audit(campaign_id, owner):
    """Read immutable delegation records in their creation order."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        rows = database.execute(
            "SELECT username, action, powers FROM play_campaign_delegation_audit WHERE campaign_id = ? ORDER BY creation_order",
            (campaign_id,),
        ).fetchall()
    return "found", [
        {"username": row["username"], "action": row["action"], "powers": decode_json(row["powers"])}
        for row in rows
    ]


def get_play_campaign_character_currency(campaign_id, actor, character_id):
    """Return a member-visible character gold balance."""
    with connection() as database:
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if member is None:
            return "not_member", None
        character = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return "unknown_character", None
        balance = database.execute(
            """
            SELECT gold FROM play_campaign_character_currency
            WHERE campaign_id = ? AND character_id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
        # Campaigns created before currency was introduced receive the same
        # deterministic starting balance the first time it is observed.
        if balance is None:
            database.execute(
                """
                INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold)
                VALUES (?, ?, 10)
                """,
                (campaign_id, character_id),
            )
            gold = 10
        else:
            gold = balance["gold"]
    return "found", {"character_id": character_id, "gold": gold}


def transfer_play_campaign_character_currency(campaign_id, actor, from_character_id, to_character_id, gold):
    """Atomically move gold between two different campaign characters."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        source = database.execute(
            """
            SELECT o.owner FROM play_campaign_members AS m
            LEFT JOIN play_campaign_character_owners AS o
              ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
            WHERE m.campaign_id = ? AND m.character_id = ?
            """,
            (campaign_id, from_character_id),
        ).fetchone()
        if source is None:
            return "unknown_character", None
        if source["owner"] != actor:
            return "not_owner", None
        destination = database.execute(
            """
            SELECT 1 FROM play_campaign_members
            WHERE campaign_id = ? AND character_id = ?
            """,
            (campaign_id, to_character_id),
        ).fetchone()
        if destination is None:
            return "invalid_destination", None
        for character_id in (from_character_id, to_character_id):
            database.execute(
                """
                INSERT OR IGNORE INTO play_campaign_character_currency
                    (campaign_id, character_id, gold)
                VALUES (?, ?, 10)
                """,
                (campaign_id, character_id),
            )
        from_gold = database.execute(
            """
            SELECT gold FROM play_campaign_character_currency
            WHERE campaign_id = ? AND character_id = ?
            """,
            (campaign_id, from_character_id),
        ).fetchone()["gold"]
        if from_gold < gold:
            return "insufficient", None
        to_gold = database.execute(
            """
            SELECT gold FROM play_campaign_character_currency
            WHERE campaign_id = ? AND character_id = ?
            """,
            (campaign_id, to_character_id),
        ).fetchone()["gold"]
        from_gold -= gold
        to_gold += gold
        transfer_id = database.execute(
            """
            SELECT COALESCE(MAX(transfer_id), 0) + 1 AS transfer_id
            FROM play_campaign_currency_transfers WHERE campaign_id = ?
            """,
            (campaign_id,),
        ).fetchone()["transfer_id"]
        database.execute(
            """
            UPDATE play_campaign_character_currency SET gold = ?
            WHERE campaign_id = ? AND character_id = ?
            """,
            (from_gold, campaign_id, from_character_id),
        )
        database.execute(
            """
            UPDATE play_campaign_character_currency SET gold = ?
            WHERE campaign_id = ? AND character_id = ?
            """,
            (to_gold, campaign_id, to_character_id),
        )
        database.execute(
            """
            INSERT INTO play_campaign_currency_transfers
                (campaign_id, transfer_id, from_character_id, to_character_id, gold)
            VALUES (?, ?, ?, ?, ?)
            """,
            (campaign_id, transfer_id, from_character_id, to_character_id, gold),
        )
    return "transferred", {
        "from_character_id": from_character_id,
        "to_character_id": to_character_id,
        "gold": gold,
        "from_gold": from_gold,
        "to_gold": to_gold,
        "transfer_id": transfer_id,
    }


class _SimulatedTransactionalFailure(Exception):
    """Internal sentinel used to make the test failure take SQLite's rollback path."""


def create_play_campaign_transactional_transfer(
    campaign_id, actor, from_character_id, to_character_id, amount, simulate_failure
):
    """Move currency and append its receipt as one all-or-nothing transaction."""
    try:
        with connection() as database:
            database.execute("BEGIN IMMEDIATE")
            campaign = database.execute(
                "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return "unknown_campaign", None
            member = database.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, actor),
            ).fetchone()
            if campaign["owner"] != actor and member is None:
                return "not_member", None

            source = database.execute(
                """
                SELECT o.owner FROM play_campaign_members AS m
                LEFT JOIN play_campaign_character_owners AS o
                  ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id
                WHERE m.campaign_id = ? AND m.character_id = ?
                """,
                (campaign_id, from_character_id),
            ).fetchone()
            destination = database.execute(
                """
                SELECT 1 FROM play_campaign_members
                WHERE campaign_id = ? AND character_id = ?
                """,
                (campaign_id, to_character_id),
            ).fetchone()
            if source is None or destination is None or from_character_id == to_character_id:
                return "invalid_character", None
            if source["owner"] != actor:
                return "not_owner", None

            # Currency rows are lazily initialized by older campaign data.  They
            # are deliberately created inside this transaction so a simulated
            # failure also leaves legacy campaigns completely unchanged.
            for character_id in (from_character_id, to_character_id):
                database.execute(
                    """
                    INSERT OR IGNORE INTO play_campaign_character_currency
                        (campaign_id, character_id, gold)
                    VALUES (?, ?, 10)
                    """,
                    (campaign_id, character_id),
                )
            from_gold = database.execute(
                "SELECT gold FROM play_campaign_character_currency "
                "WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, from_character_id),
            ).fetchone()["gold"]
            to_gold = database.execute(
                "SELECT gold FROM play_campaign_character_currency "
                "WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, to_character_id),
            ).fetchone()["gold"]
            if from_gold < amount:
                return "insufficient", None

            from_gold -= amount
            to_gold += amount
            sequence = database.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence "
                "FROM play_campaign_transactional_transfers WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()["sequence"]

            if simulate_failure:
                raise _SimulatedTransactionalFailure

            database.execute(
                """UPDATE play_campaign_character_currency SET gold = ?
                   WHERE campaign_id = ? AND character_id = ?""",
                (from_gold, campaign_id, from_character_id),
            )
            database.execute(
                """UPDATE play_campaign_character_currency SET gold = ?
                   WHERE campaign_id = ? AND character_id = ?""",
                (to_gold, campaign_id, to_character_id),
            )
            database.execute(
                """
                INSERT INTO play_campaign_transactional_transfers
                    (campaign_id, sequence, from_character_id, to_character_id,
                     amount, from_gold, to_gold)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (campaign_id, sequence, from_character_id, to_character_id,
                 amount, from_gold, to_gold),
            )
    except _SimulatedTransactionalFailure:
        return "simulated_failure", None
    return "created", {
        "from_character_id": from_character_id,
        "to_character_id": to_character_id,
        "amount": amount,
        "from_gold": from_gold,
        "to_gold": to_gold,
        "sequence": sequence,
    }


def get_play_campaign_transactional_transfers(campaign_id, actor):
    """Read successful transactional transfer receipts in commit order."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if campaign["owner"] != actor and member is None:
            return "not_member", None
        rows = database.execute(
            """
            SELECT from_character_id, to_character_id, amount, from_gold, to_gold, sequence
            FROM play_campaign_transactional_transfers
            WHERE campaign_id = ? ORDER BY sequence ASC
            """,
            (campaign_id,),
        ).fetchall()
    return "found", {"transfers": [dict(row) for row in rows]}


def submit_play_campaign_rest(campaign_id, actor, rest_type):
    """Record an active player's rest and hand the exploration turn to the DM."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        member = database.execute(
            """
            SELECT hp_current, hp_max FROM play_campaign_members
            WHERE campaign_id = ? AND username = ?
            """,
            (campaign_id, actor),
        ).fetchone()
        if member is None:
            return "not_member", None
        turn = database.execute(
            "SELECT current_actor FROM play_campaign_turns WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if turn is None:
            return "not_active", None
        if turn["current_actor"] != actor:
            return "not_your_turn", None

        hp_max = member["hp_max"]
        hp_current = hp_max if rest_type == "long" else member["hp_current"]
        if rest_type == "long":
            database.execute(
                """
                UPDATE play_campaign_members
                SET hp_current = ?, death_save_successes = 0, death_save_failures = 0,
                    status = 'conscious'
                WHERE campaign_id = ? AND username = ?
                """,
                (hp_current, campaign_id, actor),
            )
        sequence = next_play_campaign_event_sequence(database, campaign_id, "rest")
        database.execute(
            """
            INSERT INTO play_campaign_rests
                (campaign_id, sequence, actor, rest_type, hp_current, hp_max)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (campaign_id, sequence, actor, rest_type, hp_current, hp_max),
        )
        database.execute(
            "UPDATE play_campaign_turns SET current_actor = ? WHERE campaign_id = ?",
            (campaign["owner"], campaign_id),
        )
    return "created", {
        "sequence": sequence,
        "kind": "rest",
        "actor": actor,
        "type": rest_type,
        "hp_current": hp_current,
        "hp_max": hp_max,
        "next_actor": campaign["owner"],
    }


def start_play_campaign(campaign_id, owner):
    """Start a sufficiently populated lobby exactly once.

    The immediate transaction makes the lobby check, initial-actor choice, and
    state transition one durable operation.
    """
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None
        if campaign["status"] != "lobby":
            return "not_lobby", None
        members = database.execute(
            """
            SELECT username FROM play_campaign_members
            WHERE campaign_id = ? ORDER BY rowid
            """,
            (campaign_id,),
        ).fetchall()
        if len(members) < 2:
            return "under_populated", None

        current_actor = members[0]["username"]
        database.execute(
            "UPDATE play_campaigns SET status = 'active' WHERE id = ?", (campaign_id,)
        )
        database.execute(
            """
            INSERT INTO play_campaign_turns (campaign_id, current_actor, turn_number)
            VALUES (?, ?, 1)
            """,
            (campaign_id, current_actor),
        )
    return "started", {
        "id": campaign_id,
        "status": "active",
        "current_actor": current_actor,
        "turn_number": 1,
    }


def get_play_campaign_turn(campaign_id, username):
    """Return a turn only when its owner or a party member reads it."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None

        is_member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if campaign["owner"] != username and is_member is None:
            return "not_member", None

        turn = database.execute(
            """
            SELECT current_actor, turn_number FROM play_campaign_turns
            WHERE campaign_id = ?
            """,
            (campaign_id,),
        ).fetchone()
        members = database.execute(
            """
            SELECT username FROM play_campaign_members
            WHERE campaign_id = ? ORDER BY rowid
            """,
            (campaign_id,),
        ).fetchall()
        # The existing active turn contract names the normal exchange
        # ``player``.  Once an encounter has ended, the same queue has
        # explicitly resumed its exploration phase.
        completed_encounter = database.execute(
            "SELECT 1 FROM play_campaign_encounters "
            "WHERE campaign_id = ? AND status = 'closed' LIMIT 1",
            (campaign_id,),
        ).fetchone()
    if turn is None:
        return "not_active", None
    queue = []
    for member in members:
        queue.extend((member["username"], campaign["owner"]))
    return "found", {
        "campaign_id": campaign_id,
        "current_actor": turn["current_actor"],
        "phase": "exploration" if completed_encounter is not None else "player",
        "turn_number": turn["turn_number"],
        "queue": queue,
        # Deadlines are expressed in logical turns so results never depend on
        # request timing or wall-clock time.  A newly-created turn is always
        # pending until a future turn transition can make it stale.
        "logical_deadline": turn["turn_number"] + 1,
        "overdue": False,
    }


def get_play_campaign_onboarding(campaign_id, username):
    """Read a campaign member's fixed role-specific onboarding projection."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] == username:
            return "found", {
                "role": "dm",
                "next_steps": [
                    "configure-safety", "invite-players", "start-campaign",
                ],
                "can_mutate": True,
            }
        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
    if member is None:
        return "not_member", None
    return "found", {
        "role": "player",
        "next_steps": ["review-party", "take-turn", "submit-action"],
        "can_mutate": True,
    }


def nudge_play_campaign_turn(campaign_id, owner, message):
    """Record an owner nudge for the active actor with a durable counter."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None

        turn = database.execute(
            "SELECT current_actor FROM play_campaign_turns WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if turn is None:
            return "not_active", None

        nudge = database.execute(
            "SELECT nudge_count FROM play_campaign_nudges WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        nudge_count = 1 if nudge is None else nudge["nudge_count"] + 1
        if nudge is None:
            database.execute(
                "INSERT INTO play_campaign_nudges (campaign_id, nudge_count) VALUES (?, ?)",
                (campaign_id, nudge_count),
            )
        else:
            database.execute(
                "UPDATE play_campaign_nudges SET nudge_count = ? WHERE campaign_id = ?",
                (nudge_count, campaign_id),
            )
        next_play_campaign_event_sequence(database, campaign_id, "nudge")
    return "created", {
        "actor": owner,
        "target": turn["current_actor"],
        "message": message,
        "nudge_count": nudge_count,
    }


def get_play_campaign_player_turn_context(campaign_id, username):
    """Return the active turn and public context for one player-owned character."""
    with connection() as database:
        campaign = database.execute(
            "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None

        member = database.execute(
            """
            SELECT character_id, name FROM play_campaign_members
            WHERE campaign_id = ? AND username = ?
            """,
            (campaign_id, username),
        ).fetchone()
        if member is None:
            return "not_member", None

        turn = database.execute(
            """
            SELECT current_actor FROM play_campaign_turns WHERE campaign_id = ?
            """,
            (campaign_id,),
        ).fetchone()
        if turn is None:
            return "not_active", None

        # Fetch newest first to bound the response, then restore narrative order.
        events = database.execute(
            """
            SELECT sequence, text FROM play_campaign_narrations
            WHERE campaign_id = ? ORDER BY sequence DESC LIMIT 5
            """,
            (campaign_id,),
        ).fetchall()

    return "found", {
        "is_my_turn": turn["current_actor"] == username,
        "current_actor": turn["current_actor"],
        "character": {"id": member["character_id"], "name": member["name"]},
        "recent_events": [
            {"sequence": event["sequence"], "kind": "narration", "actor": "dm", "text": event["text"]}
            for event in reversed(events)
        ],
    }


def get_play_campaign_gm_status(campaign_id, owner):
    """Return the owner-only operational view of an active play campaign."""
    with connection() as database:
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None

        turn = database.execute(
            "SELECT current_actor FROM play_campaign_turns WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if turn is None:
            return "not_active", None

        members = database.execute(
            """
            SELECT username, character_id, name, class
            FROM play_campaign_members
            WHERE campaign_id = ? ORDER BY rowid
            """,
            (campaign_id,),
        ).fetchall()
        # Fetch newest first to bound the response, then restore narrative order.
        events = database.execute(
            """
            SELECT sequence, text FROM play_campaign_narrations
            WHERE campaign_id = ? ORDER BY sequence DESC LIMIT 5
            """,
            (campaign_id,),
        ).fetchall()

    return "found", {
        "needs_attention": turn["current_actor"] == owner,
        "current_actor": turn["current_actor"],
        "party": [dict(member) for member in members],
        "recent_events": [
            {"sequence": event["sequence"], "kind": "narration", "actor": "dm", "text": event["text"]}
            for event in reversed(events)
        ],
    }


def append_play_campaign_narration(campaign_id, owner, text):
    """Append narration for the owner or an active narrate delegate."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            delegation = database.execute(
                "SELECT powers FROM play_campaign_delegations "
                "WHERE campaign_id = ? AND username = ? AND active = 1",
                (campaign_id, owner),
            ).fetchone()
            if delegation is None or "narrate" not in decode_json(delegation["powers"]):
                return "not_owner", None
        sequence = next_play_campaign_event_sequence(database, campaign_id, "narration")
        database.execute(
            "INSERT INTO play_campaign_narrations (campaign_id, sequence, text) "
            "VALUES (?, ?, ?)",
            (campaign_id, sequence, text),
        )
    return "created", {
        "sequence": sequence,
        "kind": "narration",
        "actor": owner,
        "text": text,
    }


def submit_play_campaign_action(campaign_id, actor, action_type, text):
    """Append the active player's action and hand the turn to the DM.

    The transaction keeps the turn check, shared event sequence, append, and
    state transition together, so an action cannot be accepted twice.
    """
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None

        member = database.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        if member is None and campaign["owner"] != actor:
            return "not_member", None

        turn = database.execute(
            "SELECT current_actor FROM play_campaign_turns WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if turn is None:
            return "not_active", None
        if turn["current_actor"] != actor:
            return "not_your_turn", None

        sequence = next_play_campaign_event_sequence(database, campaign_id, "action")
        database.execute(
            """
            INSERT INTO play_campaign_actions
                (campaign_id, sequence, actor, action_type, text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (campaign_id, sequence, actor, action_type, text),
        )
        database.execute(
            "UPDATE play_campaign_turns SET current_actor = ? WHERE campaign_id = ?",
            (campaign["owner"], campaign_id),
        )
    return "created", {
        "sequence": sequence,
        "kind": "action",
        "actor": actor,
        "type": action_type,
        "text": text,
        "next_actor": campaign["owner"],
    }


def append_play_campaign_resolution(campaign_id, owner, text):
    """Resolve the owner's active turn and advance the player queue atomically."""
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        campaign = database.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return "unknown_campaign", None
        if campaign["owner"] != owner:
            return "not_owner", None

        turn = database.execute(
            "SELECT current_actor, turn_number FROM play_campaign_turns WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if turn is None:
            return "not_active", None
        if turn["current_actor"] != owner:
            return "not_your_turn", None

        members = database.execute(
            """
            SELECT username FROM play_campaign_members
            WHERE campaign_id = ? ORDER BY rowid
            """,
            (campaign_id,),
        ).fetchall()
        if not members:
            return "not_active", None

        # A rest returns control to the DM without consuming a numbered turn.
        # Combat, narration, and document events may follow it, but do not
        # change the exploration turn.  Therefore look through those events
        # to the most recent turn-affecting exploration event.
        previous_turn_event = database.execute(
            """
            SELECT kind FROM play_campaign_event_sequences
            WHERE campaign_id = ?
              AND kind IN ('action', 'travel', 'rest', 'resolution')
            ORDER BY sequence DESC LIMIT 1
            """,
            (campaign_id,),
        ).fetchone()
        sequence = next_play_campaign_event_sequence(database, campaign_id, "resolution")
        next_actor = (
            members[0]["username"]
            if previous_turn_event is not None and previous_turn_event["kind"] == "rest"
            else members[turn["turn_number"] % len(members)]["username"]
        )
        next_turn_number = turn["turn_number"] + 1
        database.execute(
            """
            INSERT INTO play_campaign_resolutions (campaign_id, sequence, actor, text)
            VALUES (?, ?, ?, ?)
            """,
            (campaign_id, sequence, owner, text),
        )
        database.execute(
            """
            UPDATE play_campaign_turns
            SET current_actor = ?, turn_number = ?
            WHERE campaign_id = ?
            """,
            (next_actor, next_turn_number, campaign_id),
        )
    return "created", {
        "sequence": sequence,
        "kind": "resolution",
        "actor": owner,
        "text": text,
        "next_actor": next_actor,
        "turn_number": next_turn_number,
    }


def get_campaign(campaign_id):
    with connection() as database:
        row = database.execute(
            "SELECT id, name, dm FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
    return None if row is None else dict(row)


def create_campaign_character(campaign_id, character):
    try:
        with connection() as database:
            database.execute(
                """
                INSERT INTO campaign_characters (campaign_id, id, name, level, class)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    campaign_id,
                    character["id"],
                    character["name"],
                    character["level"],
                    character["class"],
                ),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def get_campaign_characters(campaign_id):
    with connection() as database:
        rows = database.execute(
            """
            SELECT id, name, level, class FROM campaign_characters
            WHERE campaign_id = ? ORDER BY rowid
            """,
            (campaign_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_campaign_character(campaign_id, character_id):
    with connection() as database:
        row = database.execute(
            """
            SELECT id, name, level, class FROM campaign_characters
            WHERE campaign_id = ? AND id = ?
            """,
            (campaign_id, character_id),
        ).fetchone()
    return None if row is None else dict(row)


def add_campaign_inventory(campaign_id, item_slug, quantity, owner):
    with connection() as database:
        database.execute(
            """
            INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE
            SET quantity = quantity + excluded.quantity
            """,
            (campaign_id, item_slug, owner, quantity),
        )


def assign_campaign_equipment(campaign_id, character_id, item_slug, quantity):
    """Move party stock to a character, returning false when stock is insufficient."""
    with connection() as database:
        inventory = database.execute(
            """
            SELECT quantity FROM campaign_inventory
            WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'
            """,
            (campaign_id, item_slug),
        ).fetchone()
        if inventory is None or inventory["quantity"] < quantity:
            return False
        database.execute(
            """
            UPDATE campaign_inventory SET quantity = quantity - ?
            WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'
            """,
            (quantity, campaign_id, item_slug),
        )
        database.execute(
            """
            INSERT INTO character_equipment
                (campaign_id, character_id, item_slug, quantity)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(campaign_id, character_id, item_slug) DO UPDATE
            SET quantity = quantity + excluded.quantity
            """,
            (campaign_id, character_id, item_slug, quantity),
        )
    return True


def campaign_inventory_summary(campaign_id):
    with connection() as database:
        party_items = database.execute(
            """
            SELECT COUNT(*) AS count FROM campaign_inventory
            WHERE campaign_id = ? AND owner = 'party' AND quantity > 0
            """,
            (campaign_id,),
        ).fetchone()["count"]
        assigned_items = database.execute(
            """
            SELECT COUNT(*) AS count FROM character_equipment
            WHERE campaign_id = ? AND quantity > 0
            """,
            (campaign_id,),
        ).fetchone()["count"]
        healing_potions = database.execute(
            """
            SELECT COALESCE(quantity, 0) AS quantity FROM campaign_inventory
            WHERE campaign_id = ? AND item_slug = 'healing-potion' AND owner = 'party'
            """,
            (campaign_id,),
        ).fetchone()["quantity"]
    return {
        "party_items": party_items,
        "assigned_items": assigned_items,
        "healing_potions_available": healing_potions,
    }


def create_crafting_project(campaign_id, project):
    try:
        with connection() as database:
            database.execute(
                """
                INSERT INTO crafting_projects
                    (campaign_id, id, character_id, item_slug, days_required,
                     days_completed, cost_gp, status)
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
    except sqlite3.IntegrityError:
        return False
    return True


def advance_crafting_project(campaign_id, project_id, days):
    """Advance a project and deposit its result once when it completes."""
    with connection() as database:
        row = database.execute(
            """
            SELECT id, item_slug, days_required, days_completed, status
            FROM crafting_projects WHERE campaign_id = ? AND id = ?
            """,
            (campaign_id, project_id),
        ).fetchone()
        if row is None:
            return None

        project = dict(row)
        if project["status"] == "active":
            completed = min(project["days_required"], project["days_completed"] + days)
            status = "complete" if completed == project["days_required"] else "active"
            database.execute(
                """
                UPDATE crafting_projects SET days_completed = ?, status = ?
                WHERE campaign_id = ? AND id = ?
                """,
                (completed, status, campaign_id, project_id),
            )
            if status == "complete":
                database.execute(
                    """
                    INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity)
                    VALUES (?, ?, 'party', 1)
                    ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE
                    SET quantity = quantity + 1
                    """,
                    (campaign_id, project["item_slug"]),
                )
            project["days_completed"] = completed
            project["status"] = status
        return project


def create_campaign_event(campaign_id, event):
    try:
        with connection() as database:
            database.execute(
                """
                INSERT INTO campaign_events (campaign_id, id, kind, summary)
                VALUES (?, ?, ?, ?)
                """,
                (campaign_id, event["id"], event["kind"], event["summary"]),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def campaign_event_count(campaign_id):
    with connection() as database:
        return database.execute(
            "SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["count"]


def get_campaign_events(campaign_id):
    """Return campaign events in the order they were recorded."""
    with connection() as database:
        rows = database.execute(
            """
            SELECT id, kind, summary FROM campaign_events
            WHERE campaign_id = ? ORDER BY rowid
            """,
            (campaign_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def create_campaign_quest(campaign_id, quest):
    try:
        with connection() as database:
            database.execute(
                """
                INSERT INTO campaign_quests
                    (campaign_id, id, title, status, milestones, completed)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign_id,
                    quest["id"],
                    quest["title"],
                    quest["status"],
                    encode_json(quest["milestones"]),
                    encode_json([]),
                ),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def get_campaign_quest(campaign_id, quest_id):
    with connection() as database:
        row = database.execute(
            """
            SELECT id, title, status, milestones, completed FROM campaign_quests
            WHERE campaign_id = ? AND id = ?
            """,
            (campaign_id, quest_id),
        ).fetchone()
    if row is None:
        return None
    quest = dict(row)
    quest["milestones"] = decode_json(quest["milestones"])
    quest["completed"] = decode_json(quest["completed"])
    return quest


def save_campaign_quest(campaign_id, quest):
    with connection() as database:
        database.execute(
            """
            UPDATE campaign_quests SET status = ?, completed = ?
            WHERE campaign_id = ? AND id = ?
            """,
            (quest["status"], encode_json(quest["completed"]), campaign_id, quest["id"]),
        )


def campaign_quest_summary(campaign_id):
    with connection() as database:
        rows = database.execute(
            """
            SELECT status, COUNT(*) AS count FROM campaign_quests
            WHERE campaign_id = ? GROUP BY status
            """,
            (campaign_id,),
        ).fetchall()
    counts = {"active": 0, "completed": 0, "blocked": 0}
    counts.update({row["status"]: row["count"] for row in rows})
    return counts


def create_campaign_faction(campaign_id, faction):
    try:
        with connection() as database:
            database.execute(
                """
                INSERT INTO campaign_factions (id, campaign_id, name, stance)
                VALUES (?, ?, ?, ?)
                """,
                (faction["id"], campaign_id, faction["name"], faction["stance"]),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def get_campaign_faction(campaign_id, faction_id):
    with connection() as database:
        row = database.execute(
            """
            SELECT id, name, stance FROM campaign_factions
            WHERE campaign_id = ? AND id = ?
            """,
            (campaign_id, faction_id),
        ).fetchone()
    return None if row is None else dict(row)


def create_campaign_npc(campaign_id, npc):
    try:
        with connection() as database:
            database.execute(
                """
                INSERT INTO campaign_npcs
                    (id, campaign_id, name, faction_id, disposition)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    npc["id"],
                    campaign_id,
                    npc["name"],
                    npc["faction_id"],
                    npc["disposition"],
                ),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def campaign_relationship_summary(campaign_id):
    with connection() as database:
        factions = database.execute(
            "SELECT COUNT(*) AS count FROM campaign_factions WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["count"]
        counts = database.execute(
            """
            SELECT COUNT(*) AS npcs,
                   COALESCE(SUM(disposition > 0), 0) AS friendly_npcs
            FROM campaign_npcs WHERE campaign_id = ?
            """,
            (campaign_id,),
        ).fetchone()
    return {"factions": factions, "npcs": counts["npcs"], "friendly_npcs": counts["friendly_npcs"]}


def create_campaign_session(campaign_id, session):
    try:
        with connection() as database:
            database.execute(
                """
                INSERT INTO campaign_sessions
                    (campaign_id, id, starts_at, duration_minutes, agenda)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    campaign_id,
                    session["id"],
                    session["starts_at"],
                    session["duration_minutes"],
                    encode_json(session["agenda"]),
                ),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def get_campaign_session(campaign_id, session_id):
    with connection() as database:
        row = database.execute(
            """
            SELECT id, starts_at, duration_minutes, agenda FROM campaign_sessions
            WHERE campaign_id = ? AND id = ?
            """,
            (campaign_id, session_id),
        ).fetchone()
    if row is None:
        return None
    session = dict(row)
    session["agenda"] = decode_json(session["agenda"])
    return session


def save_campaign_session_attendance(campaign_id, session_id, present, absent):
    with connection() as database:
        database.execute(
            """
            INSERT INTO campaign_session_attendance
                (campaign_id, session_id, present, absent)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(campaign_id, session_id) DO UPDATE SET
                present = excluded.present, absent = excluded.absent
            """,
            (campaign_id, session_id, encode_json(present), encode_json(absent)),
        )


def get_next_campaign_session(campaign_id):
    with connection() as database:
        row = database.execute(
            """
            SELECT id, starts_at, agenda FROM campaign_sessions
            WHERE campaign_id = ?
            ORDER BY starts_at, rowid LIMIT 1
            """,
            (campaign_id,),
        ).fetchone()
    if row is None:
        return None
    session = dict(row)
    session["agenda"] = decode_json(session["agenda"])
    return session


def campaign_audit_summary(campaign_id):
    """Return stable resource counts for a campaign's audit view."""
    with connection() as database:
        counts = database.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?) AS events,
                (SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ?) AS quests,
                (SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?) AS npcs,
                (SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?) AS sessions
            """,
            (campaign_id, campaign_id, campaign_id, campaign_id),
        ).fetchone()
    return dict(counts)


def campaign_export_summary(campaign_id):
    """Return stable counts for the compact campaign export."""
    with connection() as database:
        counts = database.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?) AS characters,
                (SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ?) AS quests,
                (SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?) AS npcs,
                (SELECT COUNT(*) FROM campaign_inventory
                 WHERE campaign_id = ? AND quantity > 0) AS inventory_items,
                (SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?) AS sessions
            """,
            (campaign_id, campaign_id, campaign_id, campaign_id, campaign_id),
        ).fetchone()
    return dict(counts)


def campaign_analytics_summary(campaign_id):
    """Return the stable counts used by campaign analytics reports."""
    with connection() as database:
        counts = database.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM campaign_quests
                 WHERE campaign_id = ? AND status != 'completed') AS open_quests,
                (SELECT COUNT(*) FROM campaign_npcs
                 WHERE campaign_id = ? AND disposition > 0) AS friendly_npcs,
                (SELECT COUNT(*) FROM campaign_sessions
                 WHERE campaign_id = ?) AS scheduled_sessions,
                (SELECT COUNT(*) FROM campaign_inventory
                 WHERE campaign_id = ? AND quantity > 0) AS inventory_items,
                (SELECT COUNT(*) FROM campaign_characters
                 WHERE campaign_id = ?) AS characters,
                (SELECT COUNT(*) FROM campaign_quests
                 WHERE campaign_id = ? AND status = 'active') AS active_quests
            """,
            (campaign_id, campaign_id, campaign_id, campaign_id, campaign_id, campaign_id),
        ).fetchone()
    return dict(counts)
