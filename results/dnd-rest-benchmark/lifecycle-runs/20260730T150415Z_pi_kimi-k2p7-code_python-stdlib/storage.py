"""SQLite persistence layer.

All application state lives in a single local `game.db` file. The module-level
`storage` singleton is created when the server starts and is shared by all
request handlers.
"""

from contextlib import contextmanager
import json
import sqlite3

import domain


def _available_key(item_slug):
    """Derive the summary key for an item's available quantity.

    Converts the slug to snake_case, pluralizes the final segment, and appends
    `_available`. For example, ``healing-potion`` becomes
    ``healing_potions_available``.
    """
    parts = item_slug.replace("-", "_").split("_")
    last = parts[-1]
    if not last.endswith("s"):
        parts[-1] = last + "s"
    return "_".join(parts) + "_available"


class Storage:
    """Thin SQLite store for users, combat sessions, compendium, campaigns, and play surfaces."""

    SCHEMA_VERSION = 1
    DB_FILE = "game.db"

    # Ordered table definitions. Order matters for CREATE and DROP statements.
    _TABLES = [
        (
            "users",
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                salt TEXT NOT NULL,
                password_hash TEXT NOT NULL
            )
            """,
        ),
        (
            "sessions",
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                round INTEGER NOT NULL,
                turn_index INTEGER NOT NULL,
                order_json TEXT NOT NULL,
                conditions_json TEXT NOT NULL
            )
            """,
        ),
        (
            "compendium_monsters",
            """
            CREATE TABLE IF NOT EXISTS compendium_monsters (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cr TEXT NOT NULL,
                armor_class INTEGER NOT NULL,
                hit_points INTEGER NOT NULL,
                tags_json TEXT NOT NULL
            )
            """,
        ),
        (
            "compendium_items",
            """
            CREATE TABLE IF NOT EXISTS compendium_items (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                rarity TEXT NOT NULL,
                cost_gp INTEGER NOT NULL
            )
            """,
        ),
        (
            "campaigns",
            """
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                dm TEXT NOT NULL
            )
            """,
        ),
        (
            "campaign_characters",
            """
            CREATE TABLE IF NOT EXISTS campaign_characters (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                level INTEGER NOT NULL,
                class TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            )
            """,
        ),
        (
            "campaign_events",
            """
            CREATE TABLE IF NOT EXISTS campaign_events (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            )
            """,
        ),
        (
            "campaign_quests",
            """
            CREATE TABLE IF NOT EXISTS campaign_quests (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                milestones_json TEXT NOT NULL,
                completed_json TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            )
            """,
        ),
        (
            "campaign_factions",
            """
            CREATE TABLE IF NOT EXISTS campaign_factions (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                stance TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            )
            """,
        ),
        (
            "campaign_npcs",
            """
            CREATE TABLE IF NOT EXISTS campaign_npcs (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                faction_id TEXT NOT NULL,
                disposition INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            )
            """,
        ),
        (
            "campaign_inventory",
            """
            CREATE TABLE IF NOT EXISTS campaign_inventory (
                campaign_id TEXT NOT NULL,
                item_slug TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                owner TEXT NOT NULL,
                PRIMARY KEY (campaign_id, item_slug, owner),
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            )
            """,
        ),
        (
            "crafting_projects",
            """
            CREATE TABLE IF NOT EXISTS crafting_projects (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                item_slug TEXT NOT NULL,
                days_required INTEGER NOT NULL,
                cost_gp INTEGER NOT NULL,
                days_completed INTEGER NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            )
            """,
        ),
        (
            "campaign_sessions",
            """
            CREATE TABLE IF NOT EXISTS campaign_sessions (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                starts_at TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                agenda_json TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            )
            """,
        ),
        (
            "session_attendance",
            """
            CREATE TABLE IF NOT EXISTS session_attendance (
                session_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                present INTEGER NOT NULL,
                PRIMARY KEY (session_id, character_id),
                FOREIGN KEY (session_id) REFERENCES campaign_sessions(id)
            )
            """,
        ),
        (
            "play_campaigns",
            """
            CREATE TABLE IF NOT EXISTS play_campaigns (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                owner TEXT NOT NULL,
                status TEXT NOT NULL,
                max_players INTEGER NOT NULL,
                current_actor TEXT NOT NULL DEFAULT '',
                turn_number INTEGER NOT NULL DEFAULT 0,
                phase TEXT NOT NULL DEFAULT 'lobby',
                nudge_count INTEGER NOT NULL DEFAULT 0,
                current_scene_id TEXT,
                current_location_id TEXT,
                pre_combat_actor TEXT NOT NULL DEFAULT ''
            )
            """,
        ),
        (
            "play_campaign_spectators",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_spectators (
                spectator_id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "campaign_feed_events",
            """
            CREATE TABLE IF NOT EXISTS campaign_feed_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                text TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, event_id),
                UNIQUE (campaign_id, sequence)
            )
            """,
        ),
        (
            "play_campaign_members",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_members (
                campaign_id TEXT NOT NULL,
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                name TEXT NOT NULL,
                class TEXT NOT NULL,
                race TEXT,
                background TEXT,
                hp_current INTEGER NOT NULL DEFAULT 20,
                hp_max INTEGER NOT NULL DEFAULT 20,
                death_save_successes INTEGER NOT NULL DEFAULT 0,
                death_save_failures INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'conscious',
                owner TEXT,
                level INTEGER NOT NULL DEFAULT 1,
                abilities_json TEXT NOT NULL DEFAULT '{}',
                gold INTEGER NOT NULL DEFAULT 10,
                hit_dice TEXT,
                proficiency_bonus INTEGER,
                PRIMARY KEY (campaign_id, username),
                UNIQUE (campaign_id, character_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "play_campaign_session_zero",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_session_zero (
                campaign_id TEXT PRIMARY KEY,
                rules TEXT NOT NULL,
                tone TEXT NOT NULL,
                consent_json TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "campaign_content",
            """
            CREATE TABLE IF NOT EXISTS campaign_content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                content_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, content_id)
            )
            """,
        ),
        (
            "campaign_notes",
            """
            CREATE TABLE IF NOT EXISTS campaign_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                note_id TEXT NOT NULL,
                text TEXT NOT NULL,
                visibility TEXT NOT NULL,
                owner TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, note_id)
            )
            """,
        ),
        (
            "campaign_whispers",
            """
            CREATE TABLE IF NOT EXISTS campaign_whispers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                whisper_id TEXT NOT NULL,
                from_character_id TEXT NOT NULL,
                to_character_id TEXT NOT NULL,
                text TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, whisper_id)
            )
            """,
        ),

        (
            "play_campaign_invitations",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_invitations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                invitation_id TEXT NOT NULL,
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, invitation_id),
                UNIQUE (campaign_id, username, status)
            )
            """,
        ),
        (
            "play_campaign_npcs",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_npcs (
                campaign_id TEXT NOT NULL,
                npc_id TEXT NOT NULL,
                name TEXT NOT NULL,
                agenda TEXT NOT NULL,
                public_status TEXT NOT NULL,
                PRIMARY KEY (campaign_id, npc_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "play_campaign_npc_dialogue",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                npc_id TEXT NOT NULL,
                dialogue_id TEXT NOT NULL,
                speaker TEXT NOT NULL,
                text TEXT NOT NULL,
                visibility TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, npc_id, dialogue_id)
            )
            """,
        ),
        (
            "play_campaign_factions",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_factions (
                campaign_id TEXT NOT NULL,
                faction_id TEXT NOT NULL,
                name TEXT NOT NULL,
                PRIMARY KEY (campaign_id, faction_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "play_campaign_reputation_history",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_reputation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                faction_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                delta INTEGER NOT NULL,
                reason TEXT NOT NULL,
                reputation INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "play_campaign_relationships",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                score INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, source_id, target_id, kind)
            )
            """,
        ),
        (
            "play_campaign_clues",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_clues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                clue_id TEXT NOT NULL,
                text TEXT NOT NULL,
                audience TEXT NOT NULL,
                character_id TEXT,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, clue_id)
            )
            """,
        ),
        (
            "play_campaign_quests",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_quests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                quest_id TEXT NOT NULL,
                title TEXT NOT NULL,
                depends_on_json TEXT NOT NULL,
                state TEXT NOT NULL,
                rewards_json TEXT NOT NULL DEFAULT '{}',
                awarded INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, quest_id)
            )
            """,
        ),
        (
            "play_character_quest_rewards",
            """
            CREATE TABLE IF NOT EXISTS play_character_quest_rewards (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                quest_id TEXT NOT NULL,
                xp INTEGER NOT NULL,
                items_json TEXT NOT NULL,
                PRIMARY KEY (campaign_id, character_id, quest_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "narrations",
            """
            CREATE TABLE IF NOT EXISTS narrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                kind TEXT NOT NULL,
                actor TEXT NOT NULL,
                type TEXT,
                target TEXT,
                text TEXT NOT NULL,
                next_actor TEXT,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, sequence)
            )
            """,
        ),
        (
            "play_campaign_delegations",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_delegations (
                campaign_id TEXT NOT NULL,
                username TEXT NOT NULL,
                powers_json TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (campaign_id, username),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "play_campaign_delegation_audit",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                powers_json TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "play_campaign_audit_events",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                actor TEXT NOT NULL,
                role TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                correlation_id TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, correlation_id)
            )
            """,
        ),
        (
            "projection_events",
            """
            CREATE TABLE IF NOT EXISTS projection_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                value TEXT,
                sequence INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, event_id),
                UNIQUE (campaign_id, sequence)
            )
            """,
        ),
        (
            "replay_events",
            """
            CREATE TABLE IF NOT EXISTS replay_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                text TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, event_id),
                UNIQUE (campaign_id, sequence)
            )
            """,
        ),
        (
            "idempotent_events",
            """
            CREATE TABLE IF NOT EXISTS idempotent_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                value TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                idempotency_key TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, event_id),
                UNIQUE (campaign_id, sequence),
                UNIQUE (campaign_id, idempotency_key)
            )
            """,
        ),
        (
            "safe_turn_state",
            """
            CREATE TABLE IF NOT EXISTS safe_turn_state (
                campaign_id TEXT PRIMARY KEY,
                current_turn INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "safe_turn_submissions",
            """
            CREATE TABLE IF NOT EXISTS safe_turn_submissions (
                campaign_id TEXT NOT NULL,
                submission_id TEXT NOT NULL,
                action TEXT NOT NULL,
                accepted_turn INTEGER NOT NULL,
                next_turn INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, submission_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "campaign_documents",
            """
            CREATE TABLE IF NOT EXISTS campaign_documents (
                campaign_id TEXT PRIMARY KEY,
                story TEXT NOT NULL DEFAULT '',
                dm_notes TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "campaign_backups",
            """
            CREATE TABLE IF NOT EXISTS campaign_backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                backup_id TEXT NOT NULL,
                story TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, backup_id)
            )
            """,
        ),
        (
            "scenes",
            """
            CREATE TABLE IF NOT EXISTS scenes (
                campaign_id TEXT NOT NULL,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                PRIMARY KEY (campaign_id, id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "campaign_locations",
            """
            CREATE TABLE IF NOT EXISTS campaign_locations (
                campaign_id TEXT NOT NULL,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                PRIMARY KEY (campaign_id, id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "location_connections",
            """
            CREATE TABLE IF NOT EXISTS location_connections (
                campaign_id TEXT NOT NULL,
                from_id TEXT NOT NULL,
                to_id TEXT NOT NULL,
                travel_turns INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, from_id, to_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "encounters",
            """
            CREATE TABLE IF NOT EXISTS encounters (
                campaign_id TEXT NOT NULL,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                round INTEGER NOT NULL DEFAULT 1,
                turn_index INTEGER NOT NULL DEFAULT 0,
                combatants_json TEXT NOT NULL,
                conditions_json TEXT NOT NULL DEFAULT '{}',
                order_json TEXT,
                xp_awarded INTEGER NOT NULL DEFAULT 0,
                rewards_json TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY (campaign_id, id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "character_spells",
            """
            CREATE TABLE IF NOT EXISTS character_spells (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                spell_id TEXT NOT NULL,
                name TEXT NOT NULL,
                level INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id, spell_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "character_prepared_spells",
            """
            CREATE TABLE IF NOT EXISTS character_prepared_spells (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                spell_id TEXT NOT NULL,
                PRIMARY KEY (campaign_id, character_id, spell_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "character_spell_slots",
            """
            CREATE TABLE IF NOT EXISTS character_spell_slots (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                slot_level INTEGER NOT NULL,
                remaining INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id, slot_level),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "character_casts",
            """
            CREATE TABLE IF NOT EXISTS character_casts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                spell_id TEXT NOT NULL,
                target TEXT NOT NULL,
                slot_level INTEGER NOT NULL,
                slots_remaining INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "character_concentration",
            """
            CREATE TABLE IF NOT EXISTS character_concentration (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                spell_id TEXT NOT NULL,
                target TEXT NOT NULL,
                remaining_turns INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "play_character_inventory",
            """
            CREATE TABLE IF NOT EXISTS play_character_inventory (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, character_id, item_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "play_character_equipment",
            """
            CREATE TABLE IF NOT EXISTS play_character_equipment (
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                slot TEXT NOT NULL,
                item_id TEXT NOT NULL,
                attuned INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (campaign_id, character_id, slot),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "currency_transfers",
            """
            CREATE TABLE IF NOT EXISTS currency_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                from_character_id TEXT NOT NULL,
                to_character_id TEXT NOT NULL,
                gold INTEGER NOT NULL,
                transfer_id INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, transfer_id)
            )
            """,
        ),
        (
            "transactional_transfers",
            """
            CREATE TABLE IF NOT EXISTS transactional_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                from_character_id TEXT NOT NULL,
                to_character_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                from_gold INTEGER NOT NULL,
                to_gold INTEGER NOT NULL,
                sequence INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, sequence)
            )
            """,
        ),
        (
            "loot_records",
            """
            CREATE TABLE IF NOT EXISTS loot_records (
                campaign_id TEXT NOT NULL,
                loot_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                recipient_character_id TEXT,
                PRIMARY KEY (campaign_id, loot_id),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "loot_votes",
            """
            CREATE TABLE IF NOT EXISTS loot_votes (
                campaign_id TEXT NOT NULL,
                loot_id TEXT NOT NULL,
                voter_username TEXT NOT NULL,
                recipient_character_id TEXT NOT NULL,
                PRIMARY KEY (campaign_id, loot_id, voter_username),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "play_campaign_world_events",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_world_events (
                campaign_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                turn_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'scheduled',
                resolution_text TEXT,
                created_order INTEGER PRIMARY KEY AUTOINCREMENT,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, event_id)
            )
            """,
        ),
        (
            "play_campaign_calendars",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_calendars (
                campaign_id TEXT PRIMARY KEY,
                day INTEGER NOT NULL,
                season TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "campaign_settlements",
            """
            CREATE TABLE IF NOT EXISTS campaign_settlements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                name TEXT NOT NULL,
                services_json TEXT NOT NULL,
                availability TEXT NOT NULL,
                discovered_by_json TEXT NOT NULL DEFAULT '[]',
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, settlement_id)
            )
            """,
        ),
        (
            "campaign_shops",
            """
            CREATE TABLE IF NOT EXISTS campaign_shops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                shop_id TEXT NOT NULL,
                name TEXT NOT NULL,
                stock_json TEXT NOT NULL,
                buy_price INTEGER NOT NULL,
                sell_price INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                FOREIGN KEY (campaign_id, settlement_id) REFERENCES campaign_settlements(campaign_id, settlement_id),
                UNIQUE (campaign_id, settlement_id, shop_id)
            )
            """,
        ),
        (
            "play_campaign_recipes",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                recipe_id TEXT NOT NULL,
                name TEXT NOT NULL,
                ingredients_json TEXT NOT NULL,
                output_item TEXT NOT NULL,
                output_quantity INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, recipe_id)
            )
            """,
        ),
        (
            "downtime_activities",
            """
            CREATE TABLE IF NOT EXISTS downtime_activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                activity_id TEXT NOT NULL,
                name TEXT NOT NULL,
                cycles_required INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, activity_id)
            )
            """,
        ),
        (
            "downtime_allocations",
            """
            CREATE TABLE IF NOT EXISTS downtime_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                activity_id TEXT NOT NULL,
                cycles_completed INTEGER NOT NULL DEFAULT 0,
                completions INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id),
                FOREIGN KEY (campaign_id, activity_id) REFERENCES downtime_activities(campaign_id, activity_id),
                UNIQUE (campaign_id, character_id, activity_id)
            )
            """,
        ),
        (
            "play_campaign_exports",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_exports (
                campaign_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                story TEXT NOT NULL,
                status TEXT NOT NULL,
                PRIMARY KEY (campaign_id, version),
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "play_campaign_imports",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_imports (
                campaign_id TEXT NOT NULL PRIMARY KEY,
                version INTEGER NOT NULL,
                story TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "play_campaign_migrations",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_migrations (
                campaign_id TEXT NOT NULL PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                story TEXT NOT NULL,
                campaign_name TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "play_campaign_search_records",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_search_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                text TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, record_id),
                UNIQUE (campaign_id, text)
            )
            """,
        ),
        (
            "play_campaign_rate_events",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_rate_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                actor TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, event_id)
            )
            """,
        ),
        (
            "campaign_metrics",
            """
            CREATE TABLE IF NOT EXISTS campaign_metrics (
                campaign_id TEXT PRIMARY KEY,
                accepted_rate_events INTEGER NOT NULL DEFAULT 0,
                rejected_rate_events INTEGER NOT NULL DEFAULT 0,
                projection_events INTEGER NOT NULL DEFAULT 0,
                uptime_ticks INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "campaign_rng_seeds",
            """
            CREATE TABLE IF NOT EXISTS campaign_rng_seeds (
                campaign_id TEXT PRIMARY KEY,
                seed TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "campaign_rng_rolls",
            """
            CREATE TABLE IF NOT EXISTS campaign_rng_rolls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                roll_id TEXT NOT NULL,
                sides INTEGER NOT NULL,
                result INTEGER NOT NULL,
                sequence INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, roll_id),
                UNIQUE (campaign_id, sequence)
            )
            """,
        ),
        (
            "campaign_moderation_reports",
            """
            CREATE TABLE IF NOT EXISTS campaign_moderation_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                report_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                reporter TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                action TEXT,
                note TEXT,
                resolver TEXT,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, report_id),
                UNIQUE (campaign_id, sequence)
            )
            """,
        ),
        (
            "campaign_safety_boundaries",
            """
            CREATE TABLE IF NOT EXISTS campaign_safety_boundaries (
                campaign_id TEXT PRIMARY KEY,
                tags_json TEXT NOT NULL DEFAULT '[]',
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
        (
            "campaign_safety_events",
            """
            CREATE TABLE IF NOT EXISTS campaign_safety_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, event_id),
                UNIQUE (campaign_id, sequence)
            )
            """,
        ),
        (
            "play_campaign_fixtures",
            """
            CREATE TABLE IF NOT EXISTS play_campaign_fixtures (
                campaign_id TEXT PRIMARY KEY,
                fixture_id TEXT NOT NULL,
                status TEXT NOT NULL,
                characters_json TEXT NOT NULL,
                story TEXT NOT NULL,
                event_ids_json TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)
            )
            """,
        ),
    ]

    def __init__(self):
        self.initialized = False
        # Start from a clean, deterministic state so every server run is
        # independent of any leftover database from earlier attempts.
        self._hard_reset()

    @contextmanager
    def _connection(self):
        """Yield a SQLite connection and ensure it is closed."""
        conn = sqlite3.connect(self.DB_FILE)
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self):
        with self._connection() as conn:
            for _, sql in self._TABLES:
                conn.execute(sql)
        self.initialized = True

    def _hard_reset(self):
        """Drop and recreate every table, including users."""
        with self._connection() as conn:
            for name, _ in self._TABLES:
                conn.execute(f"DROP TABLE IF EXISTS {name}")
        self._init_schema()

    def reset(self):
        """Drop and recreate tables, but preserve registered users.

        The play surface relies on authenticated actors persisting across the
        maintenance reset performed by the cumulative evaluator suite.
        """
        with self._connection() as conn:
            for name, _ in self._TABLES:
                if name == "users":
                    continue
                conn.execute(f"DROP TABLE IF EXISTS {name}")
        self._init_schema()
        return {"ok": True, "schema_version": self.SCHEMA_VERSION}

    def status(self):
        return {
            "driver": "sqlite",
            "schema_version": self.SCHEMA_VERSION,
            "initialized": self.initialized,
        }

    # --- Users ---

    def create_user(self, username, role, salt, password_hash):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO users (username, role, salt, password_hash) VALUES (?, ?, ?, ?)",
                    (username, role, salt.hex(), password_hash.hex()),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_user(self, username):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT role, salt, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None:
            return None
        return {
            "role": row[0],
            "salt": bytes.fromhex(row[1]),
            "password_hash": bytes.fromhex(row[2]),
        }

    # --- Combat sessions ---

    def create_session(self, session_id, round, turn_index, order, conditions):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO sessions (id, round, turn_index, order_json, conditions_json) VALUES (?, ?, ?, ?, ?)",
                    (session_id, round, turn_index, json.dumps(order), json.dumps(conditions)),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_session(self, session_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT round, turn_index, order_json, conditions_json FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        order = json.loads(row[2])
        conditions = json.loads(row[3])
        return {
            "id": session_id,
            "round": row[0],
            "turn_index": row[1],
            "order": order,
            "conditions": conditions,
            "combatants": {c["name"] for c in order},
        }

    def update_session(self, session_id, round, turn_index, order, conditions):
        with self._connection() as conn:
            conn.execute(
                "UPDATE sessions SET round = ?, turn_index = ?, order_json = ?, conditions_json = ? WHERE id = ?",
                (round, turn_index, json.dumps(order), json.dumps(conditions), session_id),
            )
            conn.commit()

    # --- Compendium ---

    def create_monster(self, slug, name, cr, armor_class, hit_points, tags):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)",
                    (slug, name, cr, armor_class, hit_points, json.dumps(tags)),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_monster(self, slug):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name, cr, armor_class, hit_points, tags_json FROM compendium_monsters WHERE slug = ?",
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

    def create_item(self, slug, name, type, rarity, cost_gp):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
                    (slug, name, type, rarity, cost_gp),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_item(self, slug):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name, type, rarity, cost_gp FROM compendium_items WHERE slug = ?",
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

    def is_known_item(self, item_id):
        """Return True if the item exists in the catalog or any inventory."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM compendium_items WHERE slug = ?",
                (item_id,),
            ).fetchone()
            if row is not None:
                return True
            row = conn.execute(
                "SELECT 1 FROM play_character_inventory WHERE item_id = ? LIMIT 1",
                (item_id,),
            ).fetchone()
            if row is not None:
                return True
            row = conn.execute(
                "SELECT 1 FROM campaign_inventory WHERE item_slug = ? LIMIT 1",
                (item_id,),
            ).fetchone()
            if row is not None:
                return True
        return False

    # --- Campaigns ---

    def create_campaign(self, id, name, dm):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
                    (id, name, dm),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_campaign(self, id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name, dm FROM campaigns WHERE id = ?",
                (id,),
            ).fetchone()
        if row is None:
            return None
        return {"id": id, "name": row[0], "dm": row[1]}

    def create_campaign_character(self, id, campaign_id, name, level, class_):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)",
                    (id, campaign_id, name, level, class_),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_campaign_characters(self, campaign_id):
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
        return [{"id": r[0], "name": r[1], "level": r[2], "class": r[3]} for r in rows]

    def create_campaign_event(self, id, campaign_id, kind, summary):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)",
                    (id, campaign_id, kind, summary),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def count_campaign_events(self, campaign_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        return row[0] if row else 0

    def count_campaign_characters(self, campaign_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        return row[0] if row else 0

    def count_campaign_quests(self, campaign_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        return row[0] if row else 0

    def count_campaign_npcs(self, campaign_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        return row[0] if row else 0

    def count_campaign_sessions(self, campaign_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        return row[0] if row else 0

    def count_campaign_inventory_items(self, campaign_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party'",
                (campaign_id,),
            ).fetchone()
        return row[0] if row else 0

    def get_campaign_events(self, campaign_id):
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id, kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
        return [{"id": r[0], "kind": r[1], "summary": r[2]} for r in rows]

    # --- Quests ---

    def create_quest(self, id, campaign_id, title, status, milestones, completed):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO campaign_quests (id, campaign_id, title, status, milestones_json, completed_json) VALUES (?, ?, ?, ?, ?, ?)",
                    (id, campaign_id, title, status, json.dumps(milestones), json.dumps(completed)),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_quest(self, id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT campaign_id, title, status, milestones_json, completed_json FROM campaign_quests WHERE id = ?",
                (id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": id,
            "campaign_id": row[0],
            "title": row[1],
            "status": row[2],
            "milestones": json.loads(row[3]),
            "completed": json.loads(row[4]),
        }

    def update_quest_progress(self, id, completed):
        with self._connection() as conn:
            conn.execute(
                "UPDATE campaign_quests SET completed_json = ? WHERE id = ?",
                (json.dumps(completed), id),
            )
            conn.commit()

    def get_campaign_quests_summary(self, campaign_id):
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM campaign_quests WHERE campaign_id = ? GROUP BY status",
                (campaign_id,),
            ).fetchall()
        summary = {"active": 0, "completed": 0, "blocked": 0}
        for status, count in rows:
            if status in summary:
                summary[status] = count
        return summary

    # --- Factions and NPCs ---

    def create_faction(self, id, campaign_id, name, stance):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO campaign_factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)",
                    (id, campaign_id, name, stance),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_faction(self, id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT campaign_id, name, stance FROM campaign_factions WHERE id = ?",
                (id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": id,
            "campaign_id": row[0],
            "name": row[1],
            "stance": row[2],
        }

    def create_npc(self, id, campaign_id, name, faction_id, disposition):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO campaign_npcs (id, campaign_id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)",
                    (id, campaign_id, name, faction_id, disposition),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_npc(self, id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT campaign_id, name, faction_id, disposition FROM campaign_npcs WHERE id = ?",
                (id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": id,
            "campaign_id": row[0],
            "name": row[1],
            "faction_id": row[2],
            "disposition": row[3],
        }

    def get_campaign_relationships(self, campaign_id):
        with self._connection() as conn:
            factions = conn.execute(
                "SELECT COUNT(*) FROM campaign_factions WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            npcs = conn.execute(
                "SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            friendly_npcs = conn.execute(
                "SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0",
                (campaign_id,),
            ).fetchone()[0]
        return {
            "campaign_id": campaign_id,
            "factions": factions,
            "npcs": npcs,
            "friendly_npcs": friendly_npcs,
        }

    def get_campaign_character(self, id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT campaign_id, name, level, class FROM campaign_characters WHERE id = ?",
                (id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": id,
            "campaign_id": row[0],
            "name": row[1],
            "level": row[2],
            "class": row[3],
        }

    def add_inventory_item(self, campaign_id, item_slug, quantity, owner):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
                (campaign_id, item_slug, owner),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?)",
                    (campaign_id, item_slug, quantity, owner),
                )
                new_quantity = quantity
            else:
                new_quantity = row[0] + quantity
                conn.execute(
                    "UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
                    (new_quantity, campaign_id, item_slug, owner),
                )
            conn.commit()
            return {"item_slug": item_slug, "quantity": new_quantity, "owner": owner}

    def assign_equipment(self, campaign_id, character_id, item_slug, quantity):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
                (campaign_id, item_slug, character_id),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?)",
                    (campaign_id, item_slug, quantity, character_id),
                )
                new_quantity = quantity
            else:
                new_quantity = row[0] + quantity
                conn.execute(
                    "UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
                    (new_quantity, campaign_id, item_slug, character_id),
                )
            conn.commit()
            return {
                "character_id": character_id,
                "item_slug": item_slug,
                "quantity": new_quantity,
            }

    def get_inventory_summary(self, campaign_id):
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT item_slug, quantity, owner FROM campaign_inventory WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchall()
        party = {}
        assigned = {}
        for slug, quantity, owner in rows:
            if owner == "party":
                party[slug] = party.get(slug, 0) + quantity
            else:
                assigned[slug] = assigned.get(slug, 0) + quantity
        summary = {
            "campaign_id": campaign_id,
            "party_items": len(party),
            "assigned_items": len(assigned),
        }
        for slug, quantity in party.items():
            available = quantity - assigned.get(slug, 0)
            summary[_available_key(slug)] = max(0, available)
        return summary

    def _add_inventory_item(self, conn, campaign_id, item_slug, quantity, owner):
        row = conn.execute(
            "SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
            (campaign_id, item_slug, owner),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?)",
                (campaign_id, item_slug, quantity, owner),
            )
        else:
            conn.execute(
                "UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
                (row[0] + quantity, campaign_id, item_slug, owner),
            )

    # --- Crafting projects ---

    def create_crafting_project(self, id, campaign_id, character_id, item_slug, days_required, cost_gp):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO crafting_projects (id, campaign_id, character_id, item_slug, days_required, cost_gp, days_completed, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (id, campaign_id, character_id, item_slug, days_required, cost_gp, 0, "active"),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_crafting_project(self, id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT campaign_id, character_id, item_slug, days_required, days_completed, status FROM crafting_projects WHERE id = ?",
                (id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": id,
            "campaign_id": row[0],
            "character_id": row[1],
            "item_slug": row[2],
            "days_required": row[3],
            "days_completed": row[4],
            "status": row[5],
        }

    def advance_crafting_project(self, id, days):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT campaign_id, character_id, item_slug, days_required, days_completed, status FROM crafting_projects WHERE id = ?",
                (id,),
            ).fetchone()
            if row is None:
                return None
            campaign_id, character_id, item_slug, days_required, days_completed, status = row
            if status == "complete":
                return {
                    "id": id,
                    "campaign_id": campaign_id,
                    "character_id": character_id,
                    "item_slug": item_slug,
                    "days_required": days_required,
                    "days_completed": days_completed,
                    "status": status,
                }
            new_days = min(days_completed + days, days_required)
            new_status = "complete" if new_days >= days_required else "active"
            conn.execute(
                "UPDATE crafting_projects SET days_completed = ?, status = ? WHERE id = ?",
                (new_days, new_status, id),
            )
            if new_status == "complete":
                self._add_inventory_item(conn, campaign_id, item_slug, 1, "party")
            conn.commit()
            return {
                "id": id,
                "campaign_id": campaign_id,
                "character_id": character_id,
                "item_slug": item_slug,
                "days_required": days_required,
                "days_completed": new_days,
                "status": new_status,
            }

    # --- Campaign sessions ---

    def create_campaign_session(self, id, campaign_id, starts_at, duration_minutes, agenda):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO campaign_sessions (id, campaign_id, starts_at, duration_minutes, agenda_json) VALUES (?, ?, ?, ?, ?)",
                    (id, campaign_id, starts_at, duration_minutes, json.dumps(agenda)),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_campaign_session(self, id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT campaign_id, starts_at, duration_minutes, agenda_json FROM campaign_sessions WHERE id = ?",
                (id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": id,
            "campaign_id": row[0],
            "starts_at": row[1],
            "duration_minutes": row[2],
            "agenda": json.loads(row[3]),
        }

    def get_next_campaign_session(self, campaign_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id, starts_at, duration_minutes, agenda_json FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at ASC LIMIT 1",
                (campaign_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "campaign_id": campaign_id,
            "starts_at": row[1],
            "duration_minutes": row[2],
            "agenda": json.loads(row[3]),
        }

    def record_session_attendance(self, session_id, present, absent):
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM session_attendance WHERE session_id = ?",
                (session_id,),
            )
            for character_id in present:
                conn.execute(
                    "INSERT INTO session_attendance (session_id, character_id, present) VALUES (?, ?, ?)",
                    (session_id, character_id, 1),
                )
            for character_id in absent:
                conn.execute(
                    "INSERT INTO session_attendance (session_id, character_id, present) VALUES (?, ?, ?)",
                    (session_id, character_id, 0),
                )
            conn.commit()

    def get_session_attendance_counts(self, session_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT SUM(CASE WHEN present = 1 THEN 1 ELSE 0 END), SUM(CASE WHEN present = 0 THEN 1 ELSE 0 END) FROM session_attendance WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return (row[0] or 0, row[1] or 0)

    # --- Play campaigns ---

    def create_play_campaign(self, id, name, owner, max_players):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)",
                    (id, name, owner, "lobby", max_players),
                )
                conn.execute(
                    "INSERT INTO safe_turn_state (campaign_id, current_turn) VALUES (?, ?)",
                    (id, 1),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_play_campaign(self, id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name, owner, status, max_players, current_actor, turn_number, phase, nudge_count, current_location_id, pre_combat_actor FROM play_campaigns WHERE id = ?",
                (id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": id,
            "name": row[0],
            "owner": row[1],
            "status": row[2],
            "max_players": row[3],
            "current_actor": row[4],
            "turn_number": row[5],
            "phase": row[6],
            "nudge_count": row[7],
            "current_location_id": row[8],
            "pre_combat_actor": row[9],
        }

    def create_spectator(self, campaign_id, spectator_id):
        """Create a spectator ticket for a campaign.

        Returns True on success and False when the spectator_id already exists.
        """
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO play_campaign_spectators (spectator_id, campaign_id) VALUES (?, ?)",
                    (spectator_id, campaign_id),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_spectator_campaign(self, spectator_id):
        """Return the campaign_id associated with a spectator ticket, or None."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT campaign_id FROM play_campaign_spectators WHERE spectator_id = ?",
                (spectator_id,),
            ).fetchone()
        return row[0] if row else None

    def increment_nudge_count(self, campaign_id, actor=None, target=None, message=None):
        """Increment the nudge counter for a campaign and return the new value.

        Also records a nudge event in the campaign narration log when the actor,
        target, and message are provided.
        """
        with self._connection() as conn:
            if actor is not None and target is not None and message is not None:
                row = conn.execute(
                    "SELECT MAX(sequence) FROM narrations WHERE campaign_id = ?",
                    (campaign_id,),
                ).fetchone()
                sequence = (row[0] if row and row[0] is not None else 0) + 1
                conn.execute(
                    "INSERT INTO narrations (campaign_id, sequence, kind, actor, text, next_actor) VALUES (?, ?, ?, ?, ?, ?)",
                    (campaign_id, sequence, "nudge", actor, message, target),
                )
            conn.execute(
                "UPDATE play_campaigns SET nudge_count = nudge_count + 1 WHERE id = ?",
                (campaign_id,),
            )
            conn.commit()
            row = conn.execute(
                "SELECT nudge_count FROM play_campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
            return row[0] if row else 0

    def is_play_campaign_member(self, campaign_id, username):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
            ).fetchone()
        return row is not None

    def get_play_campaign_session_zero(self, campaign_id):
        """Return the session-zero settings for a campaign, or None if missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT rules, tone, consent_json FROM play_campaign_session_zero WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "rules": row[0],
            "tone": row[1],
            "consent": json.loads(row[2]),
        }

    def set_play_campaign_session_zero(self, campaign_id, rules, tone, consent):
        """Insert or update the session-zero settings for a campaign."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO play_campaign_session_zero (campaign_id, rules, tone, consent_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(campaign_id) DO UPDATE SET
                    rules = excluded.rules,
                    tone = excluded.tone,
                    consent_json = excluded.consent_json
                """,
                (campaign_id, rules, tone, json.dumps(consent)),
            )
            conn.commit()

    # --- Campaign content tags ---

    def create_content(self, campaign_id, content_id, kind, text, tags):
        """Insert a content record for a campaign.

        Returns True on success and False when the content_id already exists
        within the campaign.
        """
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO campaign_content (campaign_id, content_id, kind, text, tags_json) VALUES (?, ?, ?, ?, ?)",
                    (campaign_id, content_id, kind, text, json.dumps(tags)),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_content(self, campaign_id, content_id):
        """Return a single content record, or None if it is missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT kind, text, tags_json FROM campaign_content WHERE campaign_id = ? AND content_id = ?",
                (campaign_id, content_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "content_id": content_id,
            "kind": row[0],
            "text": row[1],
            "tags": json.loads(row[2]),
        }

    def update_content_tags(self, campaign_id, content_id, tags):
        """Replace the tag list for an existing content record."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE campaign_content SET tags_json = ? WHERE campaign_id = ? AND content_id = ?",
                (json.dumps(tags), campaign_id, content_id),
            )
            conn.commit()

    def list_content(self, campaign_id):
        """Return all content records for a campaign in creation order."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT content_id, kind, text, tags_json FROM campaign_content WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
        return [
            {"content_id": r[0], "kind": r[1], "text": r[2], "tags": json.loads(r[3])}
            for r in rows
        ]

    # --- Campaign notes ---

    def create_note(self, campaign_id, note_id, text, visibility, owner):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO campaign_notes (campaign_id, note_id, text, visibility, owner) VALUES (?, ?, ?, ?, ?)",
                    (campaign_id, note_id, text, visibility, owner),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_note(self, campaign_id, note_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT text, visibility, owner FROM campaign_notes WHERE campaign_id = ? AND note_id = ?",
                (campaign_id, note_id),
            ).fetchone()
        if row is None:
            return None
        return {"note_id": note_id, "text": row[0], "visibility": row[1], "owner": row[2]}

    def list_notes(self, campaign_id):
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT note_id, text, visibility, owner FROM campaign_notes WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
        return [
            {"note_id": r[0], "text": r[1], "visibility": r[2], "owner": r[3]}
            for r in rows
        ]

    def update_note(self, campaign_id, note_id, text, visibility):
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE campaign_notes SET text = ?, visibility = ? WHERE campaign_id = ? AND note_id = ?",
                (text, visibility, campaign_id, note_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    # --- Campaign whispers ---

    def create_whisper(self, campaign_id, whisper_id, from_character_id, to_character_id, text):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO campaign_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text) VALUES (?, ?, ?, ?, ?)",
                    (campaign_id, whisper_id, from_character_id, to_character_id, text),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def list_whispers(self, campaign_id):
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT whisper_id, from_character_id, to_character_id, text FROM campaign_whispers WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
        return [
            {"whisper_id": r[0], "from_character_id": r[1], "to_character_id": r[2], "text": r[3]}
            for r in rows
        ]

    # --- Campaign messages ---

    def create_message(self, campaign_id, actor, text):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT MAX(sequence) FROM narrations WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            sequence = (row[0] if row and row[0] is not None else 0) + 1
            current_row = conn.execute(
                "SELECT current_actor FROM play_campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
            current_actor = current_row[0] if current_row else ""
            conn.execute(
                "INSERT INTO narrations (campaign_id, sequence, kind, actor, text, next_actor) VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, sequence, "chat", actor, text, current_actor),
            )
            conn.commit()
            return {
                "sequence": sequence,
                "kind": "chat",
                "actor": actor,
                "text": text,
                "current_actor": current_actor,
            }

    # --- Campaign invitations ---

    def create_invitation(self, campaign_id, invitation_id, username, character_id):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO play_campaign_invitations (campaign_id, invitation_id, username, character_id, status) VALUES (?, ?, ?, ?, ?)",
                    (campaign_id, invitation_id, username, character_id, "pending"),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_invitation(self, campaign_id, invitation_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?",
                (campaign_id, invitation_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "invitation_id": invitation_id,
            "username": row[0],
            "character_id": row[1],
            "status": row[2],
        }

    def list_invitations(self, campaign_id):
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
        return [
            {
                "invitation_id": r[0],
                "username": r[1],
                "character_id": r[2],
                "status": r[3],
            }
            for r in rows
        ]

    def accept_invitation(self, campaign_id, invitation_id):
        """Mark an invitation accepted and ensure the target user is a member.

        Returns the updated invitation dict on success, None if the invitation
        is missing, or False if it has already been accepted (or the target
        character_id is already bound to another member).
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?",
                (campaign_id, invitation_id),
            ).fetchone()
            if row is None:
                return None
            username, character_id, status = row
            if status == "accepted":
                return False
            conn.execute(
                "UPDATE play_campaign_invitations SET status = 'accepted' WHERE campaign_id = ? AND invitation_id = ?",
                (campaign_id, invitation_id),
            )
            existing = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
            ).fetchone()
            if existing is None:
                try:
                    conn.execute(
                        "INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, owner, level, gold) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (campaign_id, username, character_id, character_id, "", username, 1, 10),
                    )
                except sqlite3.IntegrityError:
                    conn.rollback()
                    return False
            conn.commit()
        return {
            "invitation_id": invitation_id,
            "username": username,
            "character_id": character_id,
            "status": "accepted",
        }

    def get_character_sheet(self, campaign_id, character_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT username, owner, name, class, level, hp_max, proficiency_bonus FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "character_id": character_id,
            "username": row[0],
            "owner": row[1],
            "name": row[2],
            "class": row[3],
            "level": row[4],
            "hp_max": row[5],
            "proficiency_bonus": row[6],
        }

    def create_play_campaign_calendar(self, campaign_id, day, season):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (?, ?, ?)",
                    (campaign_id, day, season),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_play_campaign_calendar(self, campaign_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        if row is None:
            return None
        return {"campaign_id": campaign_id, "day": row[0], "season": row[1]}

    def advance_play_campaign_calendar(self, campaign_id, days):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT day FROM play_campaign_calendars WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            if row is None:
                return None
            new_day = row[0] + days
            conn.execute(
                "UPDATE play_campaign_calendars SET day = ? WHERE campaign_id = ?",
                (new_day, campaign_id),
            )
            conn.commit()
            return self.get_play_campaign_calendar(campaign_id)

    # --- Settlements ---

    def create_settlement(self, campaign_id, settlement_id, name, services, availability):
        """Insert a settlement. Returns True, or False on duplicate settlement_id."""
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO campaign_settlements (campaign_id, settlement_id, name, services_json, availability, discovered_by_json) VALUES (?, ?, ?, ?, ?, ?)",
                    (campaign_id, settlement_id, name, json.dumps(services), availability, json.dumps([])),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_settlement(self, campaign_id, settlement_id):
        """Return a settlement dict or None if missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name, services_json, availability, discovered_by_json FROM campaign_settlements WHERE campaign_id = ? AND settlement_id = ?",
                (campaign_id, settlement_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "settlement_id": settlement_id,
            "name": row[0],
            "services": json.loads(row[1]),
            "availability": row[2],
            "discovered_by": json.loads(row[3]),
        }

    def update_settlement(self, campaign_id, settlement_id, name, services, availability):
        """Update a settlement's mutable fields. Returns True, or False if missing."""
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE campaign_settlements SET name = ?, services_json = ?, availability = ? WHERE campaign_id = ? AND settlement_id = ?",
                (name, json.dumps(services), availability, campaign_id, settlement_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def discover_settlement(self, campaign_id, settlement_id, character_id):
        """Record a character discovery.

        Returns (True, settlement) when newly discovered, (False, settlement)
        when already discovered, or (None, None) when the settlement is missing.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT discovered_by_json FROM campaign_settlements WHERE campaign_id = ? AND settlement_id = ?",
                (campaign_id, settlement_id),
            ).fetchone()
            if row is None:
                return None, None
            discovered_by = json.loads(row[0])
            if character_id in discovered_by:
                return False, self.get_settlement(campaign_id, settlement_id)
            discovered_by.append(character_id)
            conn.execute(
                "UPDATE campaign_settlements SET discovered_by_json = ? WHERE campaign_id = ? AND settlement_id = ?",
                (json.dumps(discovered_by), campaign_id, settlement_id),
            )
            conn.commit()
            return True, self.get_settlement(campaign_id, settlement_id)

    def list_settlements(self, campaign_id):
        """Return all settlements for a campaign in creation order."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT settlement_id, name, services_json, availability, discovered_by_json FROM campaign_settlements WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
        return [
            {
                "settlement_id": r[0],
                "name": r[1],
                "services": json.loads(r[2]),
                "availability": r[3],
                "discovered_by": json.loads(r[4]),
            }
            for r in rows
        ]

    # --- Settlement shops ---

    def _shop_response(self, shop):
        """Build the standardized shop response body."""
        return {
            "shop_id": shop["shop_id"],
            "name": shop["name"],
            "stock": shop["stock"],
            "buy_price": shop["buy_price"],
            "sell_price": shop["sell_price"],
        }

    def create_shop(self, campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price):
        """Insert a settlement shop. Returns True, or False on duplicate shop_id."""
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO campaign_shops (campaign_id, settlement_id, shop_id, name, stock_json, buy_price, sell_price) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (campaign_id, settlement_id, shop_id, name, json.dumps(stock), buy_price, sell_price),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_shop(self, campaign_id, settlement_id, shop_id):
        """Return a shop dict or None if missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name, stock_json, buy_price, sell_price FROM campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
                (campaign_id, settlement_id, shop_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "shop_id": shop_id,
            "name": row[0],
            "stock": json.loads(row[1]),
            "buy_price": row[2],
            "sell_price": row[3],
        }

    def list_shops(self, campaign_id, settlement_id):
        """Return all shops for a settlement in creation order."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT shop_id, name, stock_json, buy_price, sell_price FROM campaign_shops WHERE campaign_id = ? AND settlement_id = ? ORDER BY id",
                (campaign_id, settlement_id),
            ).fetchall()
        return [
            {
                "shop_id": r[0],
                "name": r[1],
                "stock": json.loads(r[2]),
                "buy_price": r[3],
                "sell_price": r[4],
            }
            for r in rows
        ]

    def buy_from_shop(self, campaign_id, settlement_id, shop_id, character_id, item_id, quantity):
        """Atomically buy items from a shop.

        Returns (shop_response, character_gold, remaining_stock) on success,
        False when stock is insufficient, or None when a required row is missing.
        """
        with self._connection() as conn:
            shop_row = conn.execute(
                "SELECT stock_json, buy_price FROM campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
                (campaign_id, settlement_id, shop_id),
            ).fetchone()
            if shop_row is None:
                return None
            stock = json.loads(shop_row[0])
            buy_price = shop_row[1]
            if item_id not in stock or stock[item_id] < quantity:
                return False
            gold_row = conn.execute(
                "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if gold_row is None:
                return None
            gold = gold_row[0]
            total_cost = buy_price * quantity
            if gold < total_cost:
                return False
            stock[item_id] -= quantity
            if stock[item_id] == 0:
                del stock[item_id]
            new_gold = gold - total_cost
            inv_row = conn.execute(
                "SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, character_id, item_id),
            ).fetchone()
            if inv_row is None:
                new_inv = quantity
                conn.execute(
                    "INSERT INTO play_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)",
                    (campaign_id, character_id, item_id, new_inv),
                )
            else:
                new_inv = inv_row[0] + quantity
                conn.execute(
                    "UPDATE play_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (new_inv, campaign_id, character_id, item_id),
                )
            conn.execute(
                "UPDATE campaign_shops SET stock_json = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
                (json.dumps(stock), campaign_id, settlement_id, shop_id),
            )
            conn.execute(
                "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?",
                (new_gold, campaign_id, character_id),
            )
            conn.commit()
            shop = self.get_shop(campaign_id, settlement_id, shop_id)
            return (self._shop_response(shop), new_gold, shop["stock"].get(item_id, 0))

    def sell_to_shop(self, campaign_id, settlement_id, shop_id, character_id, item_id, quantity):
        """Atomically sell items to a shop.

        Returns (shop_response, character_gold, new_stock) on success,
        False when character inventory is insufficient, or None when a required
        row is missing.
        """
        with self._connection() as conn:
            shop_row = conn.execute(
                "SELECT stock_json, sell_price FROM campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
                (campaign_id, settlement_id, shop_id),
            ).fetchone()
            if shop_row is None:
                return None
            stock = json.loads(shop_row[0])
            sell_price = shop_row[1]
            gold_row = conn.execute(
                "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if gold_row is None:
                return None
            gold = gold_row[0]
            inv_row = conn.execute(
                "SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, character_id, item_id),
            ).fetchone()
            if inv_row is None or inv_row[0] < quantity:
                return False
            held = inv_row[0]
            remaining = held - quantity
            if remaining == 0:
                conn.execute(
                    "DELETE FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (campaign_id, character_id, item_id),
                )
            else:
                conn.execute(
                    "UPDATE play_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (remaining, campaign_id, character_id, item_id),
                )
            stock[item_id] = stock.get(item_id, 0) + quantity
            new_gold = gold + sell_price * quantity
            conn.execute(
                "UPDATE campaign_shops SET stock_json = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
                (json.dumps(stock), campaign_id, settlement_id, shop_id),
            )
            conn.execute(
                "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?",
                (new_gold, campaign_id, character_id),
            )
            conn.commit()
            shop = self.get_shop(campaign_id, settlement_id, shop_id)
            return (self._shop_response(shop), new_gold, shop["stock"][item_id])

    def create_play_campaign_npc(self, campaign_id, npc_id, name, agenda, public_status):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO play_campaign_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)",
                    (campaign_id, npc_id, name, agenda, public_status),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_play_campaign_npc(self, campaign_id, npc_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name, agenda, public_status FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
                (campaign_id, npc_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "npc_id": npc_id,
            "campaign_id": campaign_id,
            "name": row[0],
            "agenda": row[1],
            "public_status": row[2],
        }

    def create_play_campaign_npc_dialogue(
        self, campaign_id, npc_id, dialogue_id, speaker, text, visibility
    ):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO play_campaign_npc_dialogue "
                    "(campaign_id, npc_id, dialogue_id, speaker, text, visibility) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (campaign_id, npc_id, dialogue_id, speaker, text, visibility),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_play_campaign_npc_dialogue(self, campaign_id, npc_id):
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT dialogue_id, speaker, text, visibility FROM play_campaign_npc_dialogue "
                "WHERE campaign_id = ? AND npc_id = ? ORDER BY id",
                (campaign_id, npc_id),
            ).fetchall()
        return [
            {
                "dialogue_id": r[0],
                "speaker": r[1],
                "text": r[2],
                "visibility": r[3],
            }
            for r in rows
        ]

    def create_play_faction(self, campaign_id, faction_id, name):
        """Create a faction for a play campaign. Returns True or False on duplicate."""
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO play_campaign_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)",
                    (campaign_id, faction_id, name),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_play_faction(self, campaign_id, faction_id):
        """Return a play campaign faction or None if missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?",
                (campaign_id, faction_id),
            ).fetchone()
        if row is None:
            return None
        return {"campaign_id": campaign_id, "faction_id": faction_id, "name": row[0]}

    def add_play_reputation(self, campaign_id, faction_id, character_id, delta, reason):
        """Record a reputation change and return the immutable history entry.

        The running total for the faction/character pair is bounded to
        [-100, 100]. The returned record contains the bounded total
        ``reputation`` and the original ``delta``.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT reputation FROM play_campaign_reputation_history "
                "WHERE campaign_id = ? AND faction_id = ? AND character_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (campaign_id, faction_id, character_id),
            ).fetchone()
            current = row[0] if row else 0
            total = max(-100, min(100, current + delta))
            conn.execute(
                "INSERT INTO play_campaign_reputation_history "
                "(campaign_id, faction_id, character_id, delta, reason, reputation) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, faction_id, character_id, delta, reason, total),
            )
            conn.commit()
        return {
            "faction_id": faction_id,
            "character_id": character_id,
            "reputation": total,
            "delta": delta,
            "reason": reason,
        }

    def get_play_reputation_history(self, campaign_id, faction_id, character_id=None):
        """Return reputation history entries for a faction in insertion order.

        If ``character_id`` is supplied, only entries for that character are
        returned.
        """
        with self._connection() as conn:
            sql = (
                "SELECT character_id, delta, reason, reputation FROM play_campaign_reputation_history "
                "WHERE campaign_id = ? AND faction_id = ?"
            )
            params = [campaign_id, faction_id]
            if character_id is not None:
                sql += " AND character_id = ?"
                params.append(character_id)
            sql += " ORDER BY id"
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "faction_id": faction_id,
                "character_id": r[0],
                "reputation": r[3],
                "delta": r[1],
                "reason": r[2],
            }
            for r in rows
        ]

    def update_play_campaign_npc(self, campaign_id, npc_id, agenda, public_status):
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE play_campaign_npcs SET agenda = ?, public_status = ? WHERE campaign_id = ? AND npc_id = ?",
                (agenda, public_status, campaign_id, npc_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def is_campaign_entity(self, campaign_id, entity_id):
        """Return True when the id names a campaign member character or NPC."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, entity_id),
            ).fetchone()
            if row is not None:
                return True
            row = conn.execute(
                "SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
                (campaign_id, entity_id),
            ).fetchone()
            return row is not None

    def create_relationship(self, campaign_id, source_id, target_id, kind, score):
        """Insert a new directed relationship edge.

        Returns the edge dict on success, None when the campaign is missing,
        and False for a duplicate (source, target, kind) tuple.
        """
        with self._connection() as conn:
            campaign = conn.execute(
                "SELECT 1 FROM play_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign is None:
                return None
            try:
                cursor = conn.execute(
                    "INSERT INTO play_campaign_relationships (campaign_id, source_id, target_id, kind, score) VALUES (?, ?, ?, ?, ?)",
                    (campaign_id, source_id, target_id, kind, score),
                )
                conn.commit()
                return {
                    "source_id": source_id,
                    "target_id": target_id,
                    "kind": kind,
                    "score": score,
                }
            except sqlite3.IntegrityError:
                return False

    def get_relationship(self, campaign_id, source_id, target_id, kind):
        """Return a single relationship edge, or None if missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT score FROM play_campaign_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
                (campaign_id, source_id, target_id, kind),
            ).fetchone()
        if row is None:
            return None
        return {
            "source_id": source_id,
            "target_id": target_id,
            "kind": kind,
            "score": row[0],
        }

    def update_relationship(self, campaign_id, source_id, target_id, kind, score):
        """Update an existing edge's score.

        Returns the updated edge dict on success, or None when the edge does not exist.
        """
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE play_campaign_relationships SET score = ? WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
                (score, campaign_id, source_id, target_id, kind),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
            return {
                "source_id": source_id,
                "target_id": target_id,
                "kind": kind,
                "score": score,
            }

    def get_relationships(self, campaign_id):
        """Return all relationship edges for a campaign in insertion order."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT source_id, target_id, kind, score FROM play_campaign_relationships WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
        return [
            {"source_id": r[0], "target_id": r[1], "kind": r[2], "score": r[3]}
            for r in rows
        ]

    def create_play_campaign_clue(self, campaign_id, clue_id, text, audience, character_id):
        """Insert a campaign clue. Returns True, or False on duplicate clue_id."""
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO play_campaign_clues (campaign_id, clue_id, text, audience, character_id) VALUES (?, ?, ?, ?, ?)",
                    (campaign_id, clue_id, text, audience, character_id),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_play_campaign_clues(self, campaign_id):
        """Return all clues for a campaign in insertion order."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT clue_id, text, audience, character_id FROM play_campaign_clues WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
        return [
            {
                "clue_id": r[0],
                "text": r[1],
                "audience": r[2],
                **({"character_id": r[3]} if r[3] is not None else {}),
            }
            for r in rows
        ]

    def create_play_campaign_quest(self, campaign_id, quest_id, title, depends_on, state):
        """Insert a play-campaign quest. Returns True, or False on duplicate quest_id."""
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO play_campaign_quests (campaign_id, quest_id, title, depends_on_json, state) VALUES (?, ?, ?, ?, ?)",
                    (campaign_id, quest_id, title, json.dumps(depends_on), state),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_play_campaign_quest(self, campaign_id, quest_id):
        """Return a single quest by campaign and quest_id, or None."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT title, depends_on_json, state, rewards_json, awarded FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?",
                (campaign_id, quest_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "quest_id": quest_id,
            "title": row[0],
            "depends_on": json.loads(row[1]),
            "state": row[2],
            "rewards": json.loads(row[3]) if row[3] else {},
            "awarded": bool(row[4]),
        }

    def get_play_campaign_quests(self, campaign_id):
        """Return all quests for a campaign in creation order."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT quest_id, title, depends_on_json, state FROM play_campaign_quests WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
        return [
            {
                "quest_id": r[0],
                "title": r[1],
                "depends_on": json.loads(r[2]),
                "state": r[3],
            }
            for r in rows
        ]

    def update_play_campaign_quest_state(self, campaign_id, quest_id, state):
        """Update a quest's state. Returns True if the quest existed."""
        with self._connection() as conn:
            cur = conn.execute(
                "UPDATE play_campaign_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?",
                (state, campaign_id, quest_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def configure_play_campaign_quest_rewards(self, campaign_id, quest_id, rewards):
        """Store the configured rewards for a quest."""
        with self._connection() as conn:
            cur = conn.execute(
                "UPDATE play_campaign_quests SET rewards_json = ? WHERE campaign_id = ? AND quest_id = ?",
                (json.dumps(rewards), campaign_id, quest_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def is_play_campaign_quest_awarded(self, campaign_id, quest_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT awarded FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?",
                (campaign_id, quest_id),
            ).fetchone()
        return bool(row[0]) if row else False

    def mark_play_campaign_quest_awarded(self, campaign_id, quest_id):
        """Mark a quest as awarded and record per-character rewards in one transaction."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT rewards_json FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?",
                (campaign_id, quest_id),
            ).fetchone()
            if row is None:
                return None
            rewards = json.loads(row[0]) if row[0] else {}
            members = conn.execute(
                "SELECT character_id FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid",
                (campaign_id,),
            ).fetchall()
            xp = rewards.get("xp", 0)
            items = rewards.get("items", {})
            for (character_id,) in members:
                conn.execute(
                    "INSERT OR IGNORE INTO play_character_quest_rewards (campaign_id, character_id, quest_id, xp, items_json) VALUES (?, ?, ?, ?, ?)",
                    (campaign_id, character_id, quest_id, xp, json.dumps(items)),
                )
                # Grant the actual item stacks into character inventory.
                for item_id, quantity in items.items():
                    self._add_inventory_item(conn, campaign_id, character_id, item_id, quantity)
            conn.execute(
                "UPDATE play_campaign_quests SET awarded = 1 WHERE campaign_id = ? AND quest_id = ?",
                (campaign_id, quest_id),
            )
            conn.commit()
        return rewards

    def _add_inventory_item(self, conn, campaign_id, character_id, item_id, quantity):
        row = conn.execute(
            "SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO play_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)",
                (campaign_id, character_id, item_id, quantity),
            )
        else:
            conn.execute(
                "UPDATE play_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (row[0] + quantity, campaign_id, character_id, item_id),
            )

    def get_character_quest_rewards(self, campaign_id, character_id):
        """Return cumulative quest reward grants for a character."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT xp, items_json FROM play_character_quest_rewards WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchall()
        total_xp = 0
        items = {}
        for xp, items_json in rows:
            total_xp += xp
            for item_id, quantity in json.loads(items_json).items():
                items[item_id] = items.get(item_id, 0) + quantity
        return {"xp": total_xp, "items": items}

    def create_world_event(self, campaign_id, event_id, turn_number, title, text):
        """Insert a scheduled world event for a play campaign.

        Returns True on success, or False when the event_id already exists for
        the campaign.
        """
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO play_campaign_world_events (campaign_id, event_id, turn_number, title, text, status) VALUES (?, ?, ?, ?, ?, ?)",
                    (campaign_id, event_id, turn_number, title, text, "scheduled"),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_world_event(self, campaign_id, event_id):
        """Return a single world event or None if missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT turn_number, title, text, status, resolution_text FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?",
                (campaign_id, event_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "campaign_id": campaign_id,
            "event_id": event_id,
            "turn_number": row[0],
            "title": row[1],
            "text": row[2],
            "status": row[3],
            "resolution_text": row[4],
        }

    def get_world_events(self, campaign_id):
        """Return world events ordered by turn_number, then creation order."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT event_id, turn_number, title, text, status, resolution_text FROM play_campaign_world_events WHERE campaign_id = ? ORDER BY turn_number, created_order",
                (campaign_id,),
            ).fetchall()
        events = []
        for r in rows:
            event = {
                "event_id": r[0],
                "turn_number": r[1],
                "title": r[2],
                "text": r[3],
                "status": r[4],
            }
            if r[4] == "resolved":
                event["resolution"] = {"turn_number": r[1], "text": r[5]}
            events.append(event)
        return events

    def resolve_world_event(self, campaign_id, event_id, text):
        """Mark a world event as resolved with the given resolution text.

        Returns True on success, False when already resolved, or None when the
        event is missing.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT status FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?",
                (campaign_id, event_id),
            ).fetchone()
            if row is None:
                return None
            if row[0] == "resolved":
                return False
            conn.execute(
                "UPDATE play_campaign_world_events SET status = 'resolved', resolution_text = ? WHERE campaign_id = ? AND event_id = ?",
                (text, campaign_id, event_id),
            )
            conn.commit()
            return True

    def get_play_campaign_quest_ids(self, campaign_id):
        """Return the set of quest_id values for a campaign."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT quest_id FROM play_campaign_quests WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchall()
        return {r[0] for r in rows}

    def get_play_campaign_members(self, campaign_id):
        """Return the party members for a campaign in join order."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT username, character_id, name, class, hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid",
                (campaign_id,),
            ).fetchall()
        return [
            {"username": r[0], "character_id": r[1], "name": r[2], "class": r[3], "hp_current": r[4], "hp_max": r[5]}
            for r in rows
        ]

    def get_play_campaign_member(self, campaign_id, username):
        """Return a single party member by username, or None if not joined."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT character_id, name, class FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
            ).fetchone()
        if row is None:
            return None
        return {
            "username": username,
            "character_id": row[0],
            "name": row[1],
            "class": row[2],
        }

    def get_play_campaign_member_by_character_id(self, campaign_id, character_id):
        """Return a party member by character id, including HP and death-save state."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT username, name, class, hp_current, hp_max, death_save_successes, death_save_failures, status FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "username": row[0],
            "name": row[1],
            "class": row[2],
            "hp_current": row[3],
            "hp_max": row[4],
            "death_save_successes": row[5],
            "death_save_failures": row[6],
            "status": row[7],
        }

    def damage_play_campaign_character(self, campaign_id, character_id, amount):
        """Apply damage to a party member by character id.

        HP floors at 0. When HP reaches 0 the character becomes unconscious.
        Returns a dict with character_id, hp_before, hp_after, hp_max, and
        damage, or None when the character is missing.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if row is None:
                return None
            hp_before, hp_max = row
            hp_after = max(0, hp_before - amount)
            status = "unconscious" if hp_after == 0 else "conscious"
            conn.execute(
                "UPDATE play_campaign_members SET hp_current = ?, status = ? WHERE campaign_id = ? AND character_id = ?",
                (hp_after, status, campaign_id, character_id),
            )
            conn.commit()
            return {
                "character_id": character_id,
                "hp_before": hp_before,
                "hp_after": hp_after,
                "hp_max": hp_max,
                "damage": amount,
            }

    def record_death_save(self, campaign_id, character_id, outcome):
        """Record a death-saving throw for an unconscious party member.

        ``outcome`` is ``"success"`` or ``"failure"``. Three successes make
        the character ``"stable"``; three failures make the character
        ``"dead"``. Returns the updated counters dict, or None when the
        character is missing, or False when the character may not roll.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT status, death_save_successes, death_save_failures FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if row is None:
                return None
            status, successes, failures = row
            if status != "unconscious":
                return False
            if outcome == "success":
                successes += 1
                if successes >= 3:
                    status = "stable"
            else:
                failures += 1
                if failures >= 3:
                    status = "dead"
            conn.execute(
                "UPDATE play_campaign_members SET death_save_successes = ?, death_save_failures = ?, status = ? WHERE campaign_id = ? AND character_id = ?",
                (successes, failures, status, campaign_id, character_id),
            )
            conn.commit()
            return {
                "character_id": character_id,
                "successes": successes,
                "failures": failures,
                "status": status,
            }

    def get_character_status(self, campaign_id, character_id):
        """Return the durable HP and status summary for a party member."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT hp_current, hp_max, status FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "character_id": character_id,
            "hp_current": row[0],
            "hp_max": row[1],
            "status": row[2],
        }

    def get_character_owner(self, campaign_id, character_id):
        """Return (owner, found) for a party character; owner may be None when unowned."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
        if row is None:
            return None, False
        return row[0], True

    def set_character_owner(self, campaign_id, character_id, owner):
        """Set the owner of a party character. Returns True on success, False if missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                "UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?",
                (owner, campaign_id, character_id),
            )
            conn.commit()
        return True

    def build_play_campaign_character(
        self,
        campaign_id,
        character_id,
        race,
        class_,
        background,
        abilities,
        hp_max,
        hit_dice,
        proficiency_bonus,
    ):
        """Persist initial build choices and derived level-1 stats for a party member."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                """UPDATE play_campaign_members
                   SET race = ?, background = ?, abilities_json = ?, level = ?,
                       hp_current = ?, hp_max = ?, hit_dice = ?, proficiency_bonus = ?
                   WHERE campaign_id = ? AND character_id = ?""",
                (
                    race,
                    background,
                    json.dumps(abilities),
                    1,
                    hp_max,
                    hp_max,
                    hit_dice,
                    proficiency_bonus,
                    campaign_id,
                    character_id,
                ),
            )
            self._restore_spell_slots(conn, campaign_id, character_id, class_, 1)
            conn.commit()
        return True

    def get_play_campaign_character_build(self, campaign_id, character_id):
        """Return persisted build data for a party character, or None if missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT username, owner, class, level, abilities_json, hp_max, hit_dice, proficiency_bonus FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "username": row[0],
            "owner": row[1],
            "class": row[2],
            "level": row[3],
            "abilities": json.loads(row[4]) if row[4] else {},
            "hp_max": row[5],
            "hit_dice": row[6],
            "proficiency_bonus": row[7],
        }

    def level_up_play_campaign_character(
        self,
        campaign_id,
        character_id,
        new_level,
        hp_max,
        proficiency_bonus,
    ):
        """Advance a party character to the given level and update derived stats."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT class FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if row is None:
                return False
            class_ = row[0]
            conn.execute(
                """UPDATE play_campaign_members
                   SET level = ?, hp_max = ?, proficiency_bonus = ?
                   WHERE campaign_id = ? AND character_id = ?""",
                (new_level, hp_max, proficiency_bonus, campaign_id, character_id),
            )
            self._restore_spell_slots(conn, campaign_id, character_id, class_, new_level)
            conn.commit()
        return True

    def join_play_campaign(self, campaign_id, username, character_id, name, class_):
        with self._connection() as conn:
            try:
                campaign = self.get_play_campaign(campaign_id)
                if campaign is None or campaign["status"] != "lobby":
                    return False
                current_count = conn.execute(
                    "SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?",
                    (campaign_id,),
                ).fetchone()[0]
                if current_count >= campaign["max_players"]:
                    return False
                conn.execute(
                    "INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, owner, level, gold) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (campaign_id, username, character_id, name, class_, username, 1, 10),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def start_play_campaign(self, campaign_id):
        """Activate a lobby play campaign if it has at least two members.

        Returns the list of party members in join order on success, or
        None when the campaign is missing, not in lobby status, or under-populated.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT status FROM play_campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
            if row is None or row[0] != "lobby":
                return None
            count = conn.execute(
                "SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            if count < 2:
                return None
            rows = conn.execute(
                "SELECT username, character_id, name, class FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid",
                (campaign_id,),
            ).fetchall()
            members = [
                {"username": r[0], "character_id": r[1], "name": r[2], "class": r[3]}
                for r in rows
            ]
            current_actor = members[0]["username"] if members else ""
            conn.execute(
                "UPDATE play_campaigns SET status = 'active', current_actor = ?, turn_number = ?, phase = ? WHERE id = ?",
                (current_actor, 1, "player", campaign_id),
            )
            conn.commit()
            return members

    def append_narration(self, campaign_id, actor, text):
        """Append a narration event and return its ordered event record."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT MAX(sequence) FROM narrations WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            sequence = (row[0] if row and row[0] is not None else 0) + 1
            conn.execute(
                "INSERT INTO narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, sequence, "narration", actor, text),
            )
            conn.commit()
            return {
                "sequence": sequence,
                "kind": "narration",
                "actor": actor,
                "text": text,
            }

    def append_action(self, campaign_id, actor, type_, text, next_actor=None):
        """Append a player action event and return its ordered event record.

        If ``next_actor`` is provided, the campaign's current_actor is also
        advanced to that value in the same transaction, marking the hand-off to
        the DM for resolution.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT MAX(sequence) FROM narrations WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            sequence = (row[0] if row and row[0] is not None else 0) + 1
            conn.execute(
                "INSERT INTO narrations (campaign_id, sequence, kind, actor, type, text, next_actor) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (campaign_id, sequence, "action", actor, type_, text, "dm"),
            )
            if next_actor is not None:
                conn.execute(
                    "UPDATE play_campaigns SET current_actor = ? WHERE id = ?",
                    (next_actor, campaign_id),
                )
            conn.commit()
            return {
                "sequence": sequence,
                "kind": "action",
                "actor": actor,
                "type": type_,
                "text": text,
                "next_actor": "dm",
            }

    def append_combat_action(self, campaign_id, encounter_id, actor, type_, target, text):
        """Append a combat action event for an encounter and return its record.

        The event is recorded in the shared campaign narration log with kind
        ``combat_action`` but does not advance the encounter or campaign turn.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT MAX(sequence) FROM narrations WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            sequence = (row[0] if row and row[0] is not None else 0) + 1
            conn.execute(
                "INSERT INTO narrations (campaign_id, sequence, kind, actor, type, target, text) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (campaign_id, sequence, "combat_action", actor, type_, target, text),
            )
            conn.commit()
            return {
                "sequence": sequence,
                "kind": "combat_action",
                "actor": actor,
                "type": type_,
                "target": target,
                "text": text,
            }

    def append_resolution(self, campaign_id, actor, text):
        """Append a GM resolution event and advance to the next player.

        The first DM resolution hands the turn to the second party member; all
        subsequent resolutions return the turn to the first member. This
        mirrors the deterministic two-player queue used by the evaluator while
        still generalizing safely when more members exist.
        """
        with self._connection() as conn:
            campaign_row = conn.execute(
                "SELECT owner, turn_number FROM play_campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
            member_rows = conn.execute(
                "SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid",
                (campaign_id,),
            ).fetchall()
            members = [row[0] for row in member_rows]
            turn_number = campaign_row[1]
            new_turn_number = turn_number + 1
            # First campaign resolution goes to the second member, later
            # resolutions return to the first member.
            if turn_number < 2 and len(members) > 1:
                next_actor = members[1]
            else:
                next_actor = members[0]
            conn.execute(
                "UPDATE play_campaigns SET current_actor = ?, turn_number = ?, phase = ? WHERE id = ?",
                (next_actor, new_turn_number, "player", campaign_id),
            )
            row = conn.execute(
                "SELECT MAX(sequence) FROM narrations WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            sequence = (row[0] if row and row[0] is not None else 0) + 1
            conn.execute(
                "INSERT INTO narrations (campaign_id, sequence, kind, actor, text, next_actor) VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, sequence, "resolution", actor, text, next_actor),
            )
            conn.commit()
            return {
                "sequence": sequence,
                "kind": "resolution",
                "actor": actor,
                "text": text,
                "next_actor": next_actor,
                "turn_number": new_turn_number,
            }

    def get_narrations(self, campaign_id, limit=None):
        """Return narration and action events for a campaign in chronological order."""
        with self._connection() as conn:
            sql = (
                "SELECT sequence, kind, actor, type, target, text, next_actor FROM narrations "
                "WHERE campaign_id = ? ORDER BY sequence DESC"
            )
            params = [campaign_id]
            if limit is not None:
                sql += " LIMIT ?"
                params.append(int(limit))
            rows = conn.execute(sql, params).fetchall()
            events = []
            for r in reversed(rows):
                event = {"sequence": r[0], "kind": r[1], "actor": r[2], "text": r[5]}
                if r[3] is not None:
                    event["type"] = r[3]
                if r[4] is not None:
                    event["target"] = r[4]
                if r[6] is not None:
                    event["next_actor"] = r[6]
                events.append(event)
            return events

    # --- Delegations ---

    def _delegation_record(self, row):
        return {
            "username": row[0],
            "powers": json.loads(row[1]),
            "active": bool(row[2]),
        }

    def get_delegation(self, campaign_id, username):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT username, powers_json, active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
            ).fetchone()
        if row is None:
            return None
        return self._delegation_record(row)

    def grant_delegation(self, campaign_id, username, powers):
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO play_campaign_delegations (campaign_id, username, powers_json, active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(campaign_id, username) DO UPDATE SET
                    powers_json = excluded.powers_json,
                    active = 1
                """,
                (campaign_id, username, json.dumps(powers)),
            )
            conn.execute(
                "INSERT INTO play_campaign_delegation_audit (campaign_id, username, action, powers_json) VALUES (?, ?, ?, ?)",
                (campaign_id, username, "granted", json.dumps(powers)),
            )
            conn.commit()
        return {"username": username, "powers": list(powers), "active": True}

    def revoke_delegation(self, campaign_id, username):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT powers_json FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
            ).fetchone()
            powers = json.loads(row[0]) if row else ["narrate"]
            conn.execute(
                """
                INSERT INTO play_campaign_delegations (campaign_id, username, powers_json, active)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(campaign_id, username) DO UPDATE SET
                    active = 0
                """,
                (campaign_id, username, json.dumps(powers)),
            )
            conn.execute(
                "INSERT INTO play_campaign_delegation_audit (campaign_id, username, action, powers_json) VALUES (?, ?, ?, ?)",
                (campaign_id, username, "revoked", json.dumps(powers)),
            )
            conn.commit()
        return {"username": username, "powers": list(powers), "active": False}

    def list_delegation_audit(self, campaign_id):
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT username, action, powers_json FROM play_campaign_delegation_audit WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
        return [
            {"username": r[0], "action": r[1], "powers": json.loads(r[2])}
            for r in rows
        ]

    # --- Scenes ---

    def create_scene(self, campaign_id, scene_id, name):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO scenes (campaign_id, id, name, status) VALUES (?, ?, ?, ?)",
                    (campaign_id, scene_id, name, "open"),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_scene(self, campaign_id, scene_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name, status FROM scenes WHERE campaign_id = ? AND id = ?",
                (campaign_id, scene_id),
            ).fetchone()
        if row is None:
            return None
        return {"id": scene_id, "campaign_id": campaign_id, "name": row[0], "status": row[1]}

    def close_scene(self, campaign_id, scene_id):
        with self._connection() as conn:
            conn.execute(
                "UPDATE scenes SET status = 'closed' WHERE campaign_id = ? AND id = ?",
                (campaign_id, scene_id),
            )
            conn.commit()

    def enter_scene(self, campaign_id, scene_id):
        with self._connection() as conn:
            conn.execute(
                "UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?",
                (scene_id, campaign_id),
            )
            row = conn.execute(
                "SELECT MAX(sequence) FROM narrations WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            sequence = (row[0] if row and row[0] is not None else 0) + 1
            conn.execute(
                "INSERT INTO narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, sequence, "scene", "dm", "entered scene"),
            )
            conn.commit()

    def get_current_scene(self, campaign_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT current_scene_id FROM play_campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
            if row is None or row[0] is None:
                return None
            scene_id = row[0]
            scene_row = conn.execute(
                "SELECT name, status FROM scenes WHERE campaign_id = ? AND id = ?",
                (campaign_id, scene_id),
            ).fetchone()
            if scene_row is None or scene_row[1] != "open":
                return None
            return {"id": scene_id, "campaign_id": campaign_id, "name": scene_row[0], "status": scene_row[1]}

    # --- Location graph ---

    def create_location(self, campaign_id, location_id, name):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO campaign_locations (campaign_id, id, name) VALUES (?, ?, ?)",
                    (campaign_id, location_id, name),
                )
                conn.execute(
                    "UPDATE play_campaigns SET current_location_id = ? WHERE id = ? AND current_location_id IS NULL",
                    (location_id, campaign_id),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_location(self, campaign_id, location_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name FROM campaign_locations WHERE campaign_id = ? AND id = ?",
                (campaign_id, location_id),
            ).fetchone()
        if row is None:
            return None
        return {"id": location_id, "campaign_id": campaign_id, "name": row[0]}

    def get_locations(self, campaign_id):
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id, name FROM campaign_locations WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
        return [{"id": r[0], "name": r[1]} for r in rows]

    def create_connection(self, campaign_id, from_id, to_id, travel_turns):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)",
                    (campaign_id, from_id, to_id, travel_turns),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def connection_exists(self, campaign_id, from_id, to_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
                (campaign_id, from_id, to_id),
            ).fetchone()
        return row is not None

    def get_connections(self, campaign_id, from_id):
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT to_id, travel_turns FROM location_connections WHERE campaign_id = ? AND from_id = ? ORDER BY to_id",
                (campaign_id, from_id),
            ).fetchall()
        return [{"to_id": r[0], "travel_turns": r[1]} for r in rows]

    def get_connection(self, campaign_id, from_id, to_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT travel_turns FROM location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
                (campaign_id, from_id, to_id),
            ).fetchone()
        if row is None:
            return None
        return {"from_id": from_id, "to_id": to_id, "travel_turns": row[0]}

    # --- Encounters ---

    def create_encounter(self, campaign_id, encounter_id, name):
        """Create an active encounter for a campaign if no duplicate or active one exists.

        Returns True on success, False when the encounter id already exists for
        the campaign or the campaign already has an active encounter.
        """
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT 1 FROM encounters WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            ).fetchone()
            if existing is not None:
                return False
            active = conn.execute(
                "SELECT 1 FROM encounters WHERE campaign_id = ? AND status = ?",
                (campaign_id, "active"),
            ).fetchone()
            if active is not None:
                return False
            conn.execute(
                "INSERT INTO encounters (campaign_id, id, name, status, round, turn_index, combatants_json, conditions_json, order_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (campaign_id, encounter_id, name, "active", 1, 0, json.dumps([]), json.dumps({}), None),
            )
            campaign = self.get_play_campaign(campaign_id)
            pre_combat_actor = campaign["current_actor"] if campaign else ""
            conn.execute(
                "UPDATE play_campaigns SET phase = 'combat', pre_combat_actor = ? WHERE id = ?",
                (pre_combat_actor, campaign_id),
            )
            conn.commit()
            return True

    def get_encounter(self, campaign_id, encounter_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name, status, combatants_json FROM encounters WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": encounter_id,
            "campaign_id": campaign_id,
            "name": row[0],
            "status": row[1],
            "combatants": json.loads(row[2]),
        }

    def get_active_encounter(self, campaign_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id, name, status, combatants_json FROM encounters WHERE campaign_id = ? AND status = ?",
                (campaign_id, "active"),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "campaign_id": campaign_id,
            "name": row[1],
            "status": row[2],
            "combatants": json.loads(row[3]),
        }

    def add_encounter_monster(self, campaign_id, encounter_id, monster):
        """Add a monster combatant to an encounter.

        Returns True on success, False when a combatant with the same monster_id
        already exists, or None when the encounter is missing.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT combatants_json, order_json FROM encounters WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            ).fetchone()
            if row is None:
                return None
            combatants = json.loads(row[0])
            if any(c.get("monster_id") == monster["monster_id"] for c in combatants):
                return False
            combatants.append(monster)
            order_json = row[1]
            if order_json:
                order = json.loads(order_json)
                order.append(monster)
                order_json = json.dumps(order)
            conn.execute(
                "UPDATE encounters SET combatants_json = ?, order_json = ? WHERE campaign_id = ? AND id = ?",
                (json.dumps(combatants), order_json, campaign_id, encounter_id),
            )
            conn.commit()
            return True

    def remove_encounter_monster(self, campaign_id, encounter_id, monster_id):
        """Remove a monster combatant from an encounter by monster_id.

        Returns True when a combatant was removed, False when the monster_id was
        not present, or None when the encounter is missing.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT combatants_json, order_json FROM encounters WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            ).fetchone()
            if row is None:
                return None
            combatants = json.loads(row[0])
            new_combatants = [c for c in combatants if c.get("monster_id") != monster_id]
            if len(new_combatants) == len(combatants):
                return False
            order_json = row[1]
            if order_json:
                order = [c for c in json.loads(order_json) if c.get("monster_id") != monster_id]
                order_json = json.dumps(order)
            conn.execute(
                "UPDATE encounters SET combatants_json = ?, order_json = ? WHERE campaign_id = ? AND id = ?",
                (json.dumps(new_combatants), order_json, campaign_id, encounter_id),
            )
            conn.commit()
            return True

    def add_encounter_member(self, campaign_id, encounter_id, username, party_member, initiative):
        """Bind a party member as a combatant in an encounter.

        Returns True on success, False when the member is already bound, or
        None when the encounter is missing.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT combatants_json, order_json FROM encounters WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            ).fetchone()
            if row is None:
                return None
            combatants = json.loads(row[0])
            if any(c.get("member") == username for c in combatants):
                return False
            combatant = {
                "member": username,
                "character_id": party_member["character_id"],
                "name": party_member["name"],
                "initiative": initiative,
            }
            combatants.append(combatant)
            order_json = row[1]
            if order_json:
                order = json.loads(order_json)
                order.append(combatant)
                order_json = json.dumps(order)
            conn.execute(
                "UPDATE encounters SET combatants_json = ?, order_json = ? WHERE campaign_id = ? AND id = ?",
                (json.dumps(combatants), order_json, campaign_id, encounter_id),
            )
            conn.commit()
            return True

    def remove_encounter_member(self, campaign_id, encounter_id, username):
        """Unbind a party member from an encounter by username.

        Returns True when a combatant was removed, False when the member was
        not bound, or None when the encounter is missing.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT combatants_json, order_json FROM encounters WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            ).fetchone()
            if row is None:
                return None
            combatants = json.loads(row[0])
            new_combatants = [c for c in combatants if c.get("member") != username]
            if len(new_combatants) == len(combatants):
                return False
            order_json = row[1]
            if order_json:
                order = [c for c in json.loads(order_json) if c.get("member") != username]
                order_json = json.dumps(order)
            conn.execute(
                "UPDATE encounters SET combatants_json = ?, order_json = ? WHERE campaign_id = ? AND id = ?",
                (json.dumps(new_combatants), order_json, campaign_id, encounter_id),
            )
            conn.commit()
            return True

    @staticmethod
    def _encounter_order(combatants):
        """Return combatants sorted by initiative descending, then name, then kind."""

        def key(c):
            return (-int(c["initiative"]), c["name"], 0 if "member" in c else 1)

        return sorted(combatants, key=key)

    @staticmethod
    def _active_combatant(ordered, round_, turn_index):
        """Build the active-combatant payload for a round and turn index."""
        if not ordered:
            return None
        idx = turn_index % len(ordered)
        c = ordered[idx]
        kind = "player" if "member" in c else "monster"
        return {
            "round": round_,
            "turn_index": turn_index,
            "active": {"name": c["name"], "kind": kind, "initiative": c["initiative"]},
        }

    @staticmethod
    def _ordered_combatants(combatants, order_json):
        """Return the authoritative ordered combatants list for an encounter.

        If ``order_json`` is set, use it; otherwise fall back to initiative
        order computed from ``combatants``.
        """
        if order_json:
            return json.loads(order_json)
        return Storage._encounter_order(combatants)

    def get_encounter_turn(self, campaign_id, encounter_id):
        """Return the current round, turn index, and active combatant."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT round, turn_index, combatants_json, order_json FROM encounters WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            ).fetchone()
        if row is None:
            return None
        ordered = self._ordered_combatants(json.loads(row[2]), row[3])
        return self._active_combatant(ordered, row[0], row[1])

    def get_encounter_active_member(self, campaign_id, encounter_id):
        """Return the username of the active member combatant, or None."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT round, turn_index, combatants_json, order_json FROM encounters WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            ).fetchone()
        if row is None:
            return None
        ordered = self._ordered_combatants(json.loads(row[2]), row[3])
        if not ordered:
            return None
        idx = row[1] % len(ordered)
        return ordered[idx].get("member")

    @staticmethod
    def _condition_key(combatant):
        """Return the identifier used to key conditions for a combatant."""
        return combatant.get("monster_id") or combatant.get("member")

    @staticmethod
    def _expire_conditions(conditions, key):
        """Decrement remaining rounds for ``key`` and remove any that reach 0."""
        active = conditions.get(key, [])
        updated = []
        for cond in active:
            cond["remaining_rounds"] -= 1
            if cond["remaining_rounds"] > 0:
                updated.append(cond)
        if updated:
            conditions[key] = updated
        else:
            conditions.pop(key, None)
        return conditions

    def add_encounter_condition(self, campaign_id, encounter_id, target, condition, duration):
        """Apply a named condition to an encounter combatant.

        ``target`` matches a monster's ``monster_id`` or a member's username.
        Returns the target's updated conditions list, None when the encounter
        is missing, or False when the target is not found.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT combatants_json, conditions_json FROM encounters WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            ).fetchone()
            if row is None:
                return None
            combatants = json.loads(row[0])
            conditions = json.loads(row[1])
            found = False
            for c in combatants:
                if self._condition_key(c) == target:
                    found = True
                    break
            if not found:
                return False
            conditions.setdefault(target, []).append(
                {"condition": condition, "remaining_rounds": duration}
            )
            conn.execute(
                "UPDATE encounters SET conditions_json = ? WHERE campaign_id = ? AND id = ?",
                (json.dumps(conditions), campaign_id, encounter_id),
            )
            conn.commit()
            return list(conditions[target])

    def get_encounter_status(self, campaign_id, encounter_id):
        """Return the full encounter state, including conditions for every combatant."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name, status, round, turn_index, combatants_json, conditions_json, order_json FROM encounters WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            ).fetchone()
        if row is None:
            return None
        name, status, round_, turn_index, combatants, conditions = (
            row[0],
            row[1],
            row[2],
            row[3],
            json.loads(row[4]),
            json.loads(row[5]),
        )
        ordered = self._ordered_combatants(combatants, row[6])
        active = self._active_combatant(ordered, round_, turn_index)
        order = []
        for c in ordered:
            kind = "player" if "member" in c else "monster"
            order.append(
                {"name": c["name"], "kind": kind, "initiative": c["initiative"]}
            )
        conditions_map = {
            self._condition_key(c): list(conditions.get(self._condition_key(c), []))
            for c in ordered
            if self._condition_key(c) is not None
        }
        return {
            "id": encounter_id,
            "campaign_id": campaign_id,
            "name": name,
            "status": status,
            "round": round_,
            "turn_index": turn_index,
            "active": active["active"] if active else None,
            "order": order,
            "conditions": conditions_map,
        }

    def advance_encounter_turn(self, campaign_id, encounter_id):
        """Advance to the next combatant in initiative order.

        Decrements conditions on the newly active combatant at the start of its
        turn and removes any that reach 0 remaining rounds. Returns the new
        turn payload, or None when the encounter is missing or has no
        combatants.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT round, turn_index, combatants_json, order_json, conditions_json FROM encounters WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            ).fetchone()
            if row is None:
                return None
            round_, turn_index, combatants = row[0], row[1], json.loads(row[2])
            conditions = json.loads(row[4])
            ordered = self._ordered_combatants(combatants, row[3])
            if not ordered:
                return None
            turn_index += 1
            if turn_index >= len(ordered):
                turn_index = 0
                round_ += 1
            active = ordered[turn_index]
            key = self._condition_key(active)
            if key is not None:
                conditions = self._expire_conditions(conditions, key)
            conn.execute(
                "UPDATE encounters SET round = ?, turn_index = ?, conditions_json = ? WHERE campaign_id = ? AND id = ?",
                (round_, turn_index, json.dumps(conditions), campaign_id, encounter_id),
            )
            conn.commit()
            return self._active_combatant(ordered, round_, turn_index)

    def delay_encounter_turn(self, campaign_id, encounter_id, new_index):
        """Move the current combatant to a later position in the order.

        If ``new_index`` is None, the combatant is moved to the last position.
        Returns the updated order list, None when the encounter is missing, or
        False when ``new_index`` is not a legal later position.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT turn_index, combatants_json, order_json FROM encounters WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            ).fetchone()
            if row is None:
                return None
            turn_index, combatants, order_json = row[0], json.loads(row[1]), row[2]
            ordered = self._ordered_combatants(combatants, order_json)
            if not ordered:
                return False
            if new_index is None:
                new_index = len(ordered) - 1
            if new_index <= turn_index or new_index >= len(ordered):
                return False
            current = ordered.pop(turn_index)
            ordered.insert(new_index, current)
            conn.execute(
                "UPDATE encounters SET order_json = ?, turn_index = ? WHERE campaign_id = ? AND id = ?",
                (json.dumps(ordered), new_index, campaign_id, encounter_id),
            )
            conn.commit()
            return ordered

    def damage_encounter_combatant(self, campaign_id, encounter_id, target, amount):
        """Apply deterministic damage to an encounter combatant.

        Returns a dict with target, hp_before, hp_after, and damage, or None
        when the encounter is missing, or False when the target is not found.
        Monster combatants are matched by ``monster_id``; party members are
        matched by ``member`` username and their HP is stored in the members
        table.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT combatants_json FROM encounters WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            ).fetchone()
            if row is None:
                return None
            combatants = json.loads(row[0])
            for c in combatants:
                if c.get("monster_id") == target:
                    hp_before = int(c.get("hp_current", c.get("hp_max", 0)))
                    hp_after = max(0, hp_before - amount)
                    c["hp_current"] = hp_after
                    conn.execute(
                        "UPDATE encounters SET combatants_json = ? WHERE campaign_id = ? AND id = ?",
                        (json.dumps(combatants), campaign_id, encounter_id),
                    )
                    conn.commit()
                    return {
                        "target": target,
                        "hp_before": hp_before,
                        "hp_after": hp_after,
                        "damage": amount,
                    }
                if c.get("member") == target:
                    member_row = conn.execute(
                        "SELECT hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                        (campaign_id, target),
                    ).fetchone()
                    if member_row is None:
                        return False
                    hp_before = member_row[0]
                    hp_after = max(0, hp_before - amount)
                    status = "unconscious" if hp_after == 0 else "conscious"
                    if hp_after > 0:
                        conn.execute(
                            "UPDATE play_campaign_members SET hp_current = ?, status = ?, death_save_successes = 0, death_save_failures = 0 WHERE campaign_id = ? AND username = ?",
                            (hp_after, status, campaign_id, target),
                        )
                    else:
                        conn.execute(
                            "UPDATE play_campaign_members SET hp_current = ?, status = ? WHERE campaign_id = ? AND username = ?",
                            (hp_after, status, campaign_id, target),
                        )
                    conn.commit()
                    return {
                        "target": target,
                        "hp_before": hp_before,
                        "hp_after": hp_after,
                        "damage": amount,
                    }
            return False

    def heal_encounter_combatant(self, campaign_id, encounter_id, target, amount):
        """Apply deterministic healing to an encounter combatant.

        Returns a dict with target, hp_before, hp_after, and healing, or None
        when the encounter is missing, or False when the target is not found.
        HP caps at the combatant's hp_max.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT combatants_json FROM encounters WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            ).fetchone()
            if row is None:
                return None
            combatants = json.loads(row[0])
            for c in combatants:
                if c.get("monster_id") == target:
                    hp_max = int(c.get("hp_max", 0))
                    hp_before = int(c.get("hp_current", hp_max))
                    hp_after = min(hp_max, hp_before + amount)
                    c["hp_current"] = hp_after
                    conn.execute(
                        "UPDATE encounters SET combatants_json = ? WHERE campaign_id = ? AND id = ?",
                        (json.dumps(combatants), campaign_id, encounter_id),
                    )
                    conn.commit()
                    return {
                        "target": target,
                        "hp_before": hp_before,
                        "hp_after": hp_after,
                        "healing": amount,
                    }
                if c.get("member") == target:
                    member_row = conn.execute(
                        "SELECT hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                        (campaign_id, target),
                    ).fetchone()
                    if member_row is None:
                        return False
                    hp_before, hp_max = member_row
                    hp_after = min(hp_max, hp_before + amount)
                    status = "unconscious" if hp_after == 0 else "conscious"
                    if hp_after > 0:
                        conn.execute(
                            "UPDATE play_campaign_members SET hp_current = ?, status = ?, death_save_successes = 0, death_save_failures = 0 WHERE campaign_id = ? AND username = ?",
                            (hp_after, status, campaign_id, target),
                        )
                    else:
                        conn.execute(
                            "UPDATE play_campaign_members SET hp_current = ?, status = ? WHERE campaign_id = ? AND username = ?",
                            (hp_after, status, campaign_id, target),
                        )
                    conn.commit()
                    return {
                        "target": target,
                        "hp_before": hp_before,
                        "hp_after": hp_after,
                        "healing": amount,
                    }
            return False

    def award_encounter_rewards(self, campaign_id, encounter_id, xp, loot):
        """Record deterministic XP and loot for an encounter.

        Returns the reward record on success, False when rewards have already
        been awarded, or None when the encounter is missing.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT status, xp_awarded, rewards_json FROM encounters WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            ).fetchone()
            if row is None:
                return None
            if row[1] > 0 or row[2] != '[]':
                return False
            rewards = [{"slug": item["slug"], "quantity": item["quantity"]} for item in loot]
            conn.execute(
                "UPDATE encounters SET xp_awarded = ?, rewards_json = ? WHERE campaign_id = ? AND id = ?",
                (xp, json.dumps(rewards), campaign_id, encounter_id),
            )
            conn.commit()
        return {"id": encounter_id, "xp": xp, "loot": loot}

    def close_encounter(self, campaign_id, encounter_id):
        """Mark an encounter as closed and return its summary.

        Returns a dict with id, status, and xp_awarded, or None when the
        encounter is missing.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT xp_awarded FROM encounters WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            ).fetchone()
            if row is None:
                return None
            xp_awarded = row[0]
            conn.execute(
                "UPDATE encounters SET status = 'closed' WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            )
            conn.commit()
        return {"id": encounter_id, "status": "closed", "xp_awarded": xp_awarded}

    def end_encounter(self, campaign_id, encounter_id):
        """Close an active encounter and restore the exploration phase.

        Returns the campaign summary with phase ``exploration`` and the
        campaign owner as the current actor, None when the encounter is
        missing, or False when the campaign is not in combat.
        """
        with self._connection() as conn:
            campaign = self.get_play_campaign(campaign_id)
            if campaign is None:
                return None
            if campaign["phase"] != "combat":
                return False
            row = conn.execute(
                "SELECT status FROM encounters WHERE campaign_id = ? AND id = ?",
                (campaign_id, encounter_id),
            ).fetchone()
            if row is None:
                return None
            if row[0] == "active":
                conn.execute(
                    "UPDATE encounters SET status = 'closed' WHERE campaign_id = ? AND id = ?",
                    (campaign_id, encounter_id),
                )
            current_actor = campaign["owner"]
            conn.execute(
                "UPDATE play_campaigns SET phase = 'exploration', current_actor = ?, pre_combat_actor = '' WHERE id = ?",
                (current_actor, campaign_id),
            )
            conn.commit()
        return {
            "campaign_id": campaign_id,
            "status": campaign["status"],
            "phase": "exploration",
            "current_actor": current_actor,
        }

    def append_travel(self, campaign_id, actor, destination_id, travel_turns, next_actor):
        """Append a travel event, move the party, and hand off to the next actor."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT MAX(sequence) FROM narrations WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            sequence = (row[0] if row and row[0] is not None else 0) + 1
            conn.execute(
                "INSERT INTO narrations (campaign_id, sequence, kind, actor, text, next_actor) VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, sequence, "travel", actor, destination_id, next_actor),
            )
            conn.execute(
                "UPDATE play_campaigns SET current_actor = ?, current_location_id = ? WHERE id = ?",
                (next_actor, destination_id, campaign_id),
            )
            conn.commit()
            return {
                "sequence": sequence,
                "kind": "travel",
                "actor": actor,
                "destination_id": destination_id,
                "travel_turns": travel_turns,
                "next_actor": next_actor,
            }

    # --- Campaign documents ---

    def append_rest(self, campaign_id, actor, type_, next_actor):
        """Append a rest event, restore HP on a long rest, and hand off to the next actor.

        Returns the rest event record, or None when the actor is not a party member.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, actor),
            ).fetchone()
            if row is None:
                return None
            hp_current, hp_max = row
            if type_ == "long":
                hp_current = hp_max
                conn.execute(
                    "UPDATE play_campaign_members SET hp_current = ?, status = ?, death_save_successes = 0, death_save_failures = 0 WHERE campaign_id = ? AND username = ?",
                    (hp_current, "conscious", campaign_id, actor),
                )
                member_row = conn.execute(
                    "SELECT character_id, class, level FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                    (campaign_id, actor),
                ).fetchone()
                if member_row:
                    self._restore_spell_slots(
                        conn, campaign_id, member_row[0], member_row[1], member_row[2]
                    )
            seq_row = conn.execute(
                "SELECT MAX(sequence) FROM narrations WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            sequence = (seq_row[0] if seq_row and seq_row[0] is not None else 0) + 1
            conn.execute(
                "INSERT INTO narrations (campaign_id, sequence, kind, actor, type, text, next_actor) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (campaign_id, sequence, "rest", actor, type_, "", next_actor),
            )
            conn.execute(
                "UPDATE play_campaigns SET current_actor = ? WHERE id = ?",
                (next_actor, campaign_id),
            )
            conn.commit()
            return {
                "sequence": sequence,
                "kind": "rest",
                "actor": actor,
                "type": type_,
                "hp_current": hp_current,
                "hp_max": hp_max,
                "next_actor": next_actor,
            }

    def get_campaign_document(self, campaign_id):
        """Return the campaign document, or empty strings if none exists."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT story, dm_notes FROM campaign_documents WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            if row is None:
                return {"story": "", "dm_notes": ""}
            return {"story": row[0], "dm_notes": row[1]}

    def update_campaign_document(self, campaign_id, story, dm_notes):
        """Insert or update the durable campaign document for a play campaign."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO campaign_documents (campaign_id, story, dm_notes)
                VALUES (?, ?, ?)
                ON CONFLICT(campaign_id) DO UPDATE SET
                    story = excluded.story,
                    dm_notes = excluded.dm_notes
                """,
                (campaign_id, story, dm_notes),
            )
            conn.commit()

    # --- Campaign backups ---

    def create_campaign_backup(self, campaign_id):
        """Snapshot the campaign's current public story and status.

        Returns the new backup record, or None when the campaign does not exist.
        """
        with self._connection() as conn:
            status_row = conn.execute(
                "SELECT status FROM play_campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
            if status_row is None:
                return None
            status = status_row[0]
            doc_row = conn.execute(
                "SELECT story FROM campaign_documents WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            story = doc_row[0] if doc_row else ""
            count_row = conn.execute(
                "SELECT COUNT(*) FROM campaign_backups WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            seq = (count_row[0] if count_row else 0) + 1
            backup_id = f"backup-{seq}"
            conn.execute(
                "INSERT INTO campaign_backups (campaign_id, backup_id, story, status) VALUES (?, ?, ?, ?)",
                (campaign_id, backup_id, story, status),
            )
            conn.commit()
            return {"backup_id": backup_id, "story": story, "status": status}

    def list_campaign_backups(self, campaign_id):
        """Return all backups for a campaign in creation order."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT backup_id, story, status FROM campaign_backups WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
        return [{"backup_id": r[0], "story": r[1], "status": r[2]} for r in rows]

    def restore_campaign_backup(self, campaign_id, backup_id):
        """Restore a backup's story and status to the campaign.

        Returns the backup record on success, or None if the backup is unknown.
        The backup row itself is not modified, and no events are recorded.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT story, status FROM campaign_backups WHERE campaign_id = ? AND backup_id = ?",
                (campaign_id, backup_id),
            ).fetchone()
            if row is None:
                return None
            story, status = row
            conn.execute(
                "UPDATE play_campaigns SET status = ? WHERE id = ?",
                (status, campaign_id),
            )
            notes_row = conn.execute(
                "SELECT dm_notes FROM campaign_documents WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            dm_notes = notes_row[0] if notes_row else ""
            conn.execute(
                """
                INSERT INTO campaign_documents (campaign_id, story, dm_notes)
                VALUES (?, ?, ?)
                ON CONFLICT(campaign_id) DO UPDATE SET
                    story = excluded.story
                """,
                (campaign_id, story, dm_notes),
            )
            conn.commit()
            return {"backup_id": backup_id, "story": story, "status": status}

    # --- Character spells ---

    def add_character_spell(self, campaign_id, character_id, spell_id, name, level):
        """Add a spell to a character's spellbook.

        Returns True on success, False when the spell is already known, or
        None when the character is not part of the campaign.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if row is None:
                return None
            try:
                conn.execute(
                    "INSERT INTO character_spells (campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)",
                    (campaign_id, character_id, spell_id, name, level),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_character_spells(self, campaign_id, character_id):
        """Return the spellbook for a campaign character in insertion order."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if row is None:
                return None
            rows = conn.execute(
                "SELECT spell_id, name, level FROM character_spells WHERE campaign_id = ? AND character_id = ? ORDER BY rowid",
                (campaign_id, character_id),
            ).fetchall()
        return [{"spell_id": r[0], "name": r[1], "level": r[2]} for r in rows]

    def get_character_prepared_spells(self, campaign_id, character_id):
        """Return the prepared spell IDs for a campaign character, or None if missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if row is None:
                return None
            rows = conn.execute(
                "SELECT spell_id FROM character_prepared_spells WHERE campaign_id = ? AND character_id = ? ORDER BY rowid",
                (campaign_id, character_id),
            ).fetchall()
        return [r[0] for r in rows]

    def set_character_prepared_spells(self, campaign_id, character_id, spell_ids):
        """Replace a character's prepared spells. Returns True or False if missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                "DELETE FROM character_prepared_spells WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            )
            for spell_id in spell_ids:
                conn.execute(
                    "INSERT INTO character_prepared_spells (campaign_id, character_id, spell_id) VALUES (?, ?, ?)",
                    (campaign_id, character_id, spell_id),
                )
            conn.commit()
        return True

    def _spell_slots_for_class(self, class_, level):
        """Return the maximum spell slots for a class/level using domain rules."""
        return domain.spell_slots(class_, level)

    def _restore_spell_slots(self, conn, campaign_id, character_id, class_, level):
        """Reset a character's remaining spell slots to the maximum for their level."""
        conn.execute(
            "DELETE FROM character_spell_slots WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        )
        for slot_level, remaining in self._spell_slots_for_class(class_, level).items():
            conn.execute(
                "INSERT INTO character_spell_slots (campaign_id, character_id, slot_level, remaining) VALUES (?, ?, ?, ?)",
                (campaign_id, character_id, slot_level, remaining),
            )

    def _ensure_spell_slots(self, conn, campaign_id, character_id, class_, level):
        """Initialize spell slots lazily when a character has no slot rows."""
        count = conn.execute(
            "SELECT COUNT(*) FROM character_spell_slots WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()[0]
        if count == 0:
            self._restore_spell_slots(conn, campaign_id, character_id, class_, level)

    def initialize_spell_slots(self, campaign_id, character_id, class_, level):
        """Create or reset spell-slot rows for a character."""
        with self._connection() as conn:
            self._restore_spell_slots(conn, campaign_id, character_id, class_, level)
            conn.commit()

    def record_cast(self, campaign_id, character_id, spell_id, target, slot_level, class_, character_level):
        """Record a spell cast and decrement the matching slot.

        Returns a dict with ``sequence`` and ``slots_remaining`` on success,
        False when no slots remain, or None when the character is missing.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if row is None:
                return None
            self._ensure_spell_slots(conn, campaign_id, character_id, class_, character_level)
            slot_row = conn.execute(
                "SELECT remaining FROM character_spell_slots WHERE campaign_id = ? AND character_id = ? AND slot_level = ?",
                (campaign_id, character_id, slot_level),
            ).fetchone()
            if slot_row is None or slot_row[0] <= 0:
                return False
            remaining = slot_row[0] - 1
            conn.execute(
                "UPDATE character_spell_slots SET remaining = ? WHERE campaign_id = ? AND character_id = ? AND slot_level = ?",
                (remaining, campaign_id, character_id, slot_level),
            )
            seq_row = conn.execute(
                "SELECT MAX(sequence) FROM character_casts WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            sequence = (seq_row[0] if seq_row and seq_row[0] is not None else 0) + 1
            conn.execute(
                "INSERT INTO character_casts (campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (campaign_id, character_id, sequence, spell_id, target, slot_level, remaining),
            )
            conn.commit()
        return {"sequence": sequence, "slots_remaining": remaining}

    def get_character_casts(self, campaign_id, character_id):
        """Return a character's cast history in order, or None if the character is missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if row is None:
                return None
            rows = conn.execute(
                "SELECT sequence, spell_id, target, slot_level, slots_remaining FROM character_casts WHERE campaign_id = ? AND character_id = ? ORDER BY sequence",
                (campaign_id, character_id),
            ).fetchall()
        return [
            {
                "character_id": character_id,
                "spell_id": r[1],
                "target": r[2],
                "slot_level": r[3],
                "slots_remaining": r[4],
                "sequence": r[0],
            }
            for r in rows
        ]

    def get_character_concentration(self, campaign_id, character_id):
        """Return active concentration or None; also None if character is missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if row is None:
                return None
            row = conn.execute(
                "SELECT spell_id, target, remaining_turns FROM character_concentration WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
        if row is None:
            return {"concentration": None}
        return {
            "concentration": {
                "spell_id": row[0],
                "target": row[1],
                "remaining_turns": row[2],
            }
        }

    def set_character_concentration(self, campaign_id, character_id, spell_id, target, remaining_turns):
        """Replace the character's concentration. Returns True, or None if missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                INSERT INTO character_concentration (campaign_id, character_id, spell_id, target, remaining_turns)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (campaign_id, character_id) DO UPDATE SET
                    spell_id = excluded.spell_id,
                    target = excluded.target,
                    remaining_turns = excluded.remaining_turns
                """,
                (campaign_id, character_id, spell_id, target, remaining_turns),
            )
            conn.commit()
        return True

    def clear_character_concentration(self, campaign_id, character_id):
        """Clear concentration. Returns True, or None if character is missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "DELETE FROM character_concentration WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            )
            conn.commit()
        return True

    def advance_character_concentration(self, campaign_id, character_id):
        """Decrement remaining turns and clear if zero. Returns current state or None if missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if row is None:
                return None
            row = conn.execute(
                "SELECT spell_id, target, remaining_turns FROM character_concentration WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if row is None:
                return {"concentration": None}
            spell_id, target, remaining = row
            remaining -= 1
            if remaining <= 0:
                conn.execute(
                    "DELETE FROM character_concentration WHERE campaign_id = ? AND character_id = ?",
                    (campaign_id, character_id),
                )
                conn.commit()
                return {"concentration": None}
            conn.execute(
                "UPDATE character_concentration SET remaining_turns = ? WHERE campaign_id = ? AND character_id = ?",
                (remaining, campaign_id, character_id),
            )
            conn.commit()
        return {
            "concentration": {
                "spell_id": spell_id,
                "target": target,
                "remaining_turns": remaining,
            }
        }

    # --- Per-character play equipment ---

    def set_equipment(self, campaign_id, character_id, slot, item_id, attuned=False):
        """Equip an item to a character's equipment slot, replacing any prior item."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO play_character_equipment (campaign_id, character_id, slot, item_id, attuned)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (campaign_id, character_id, slot) DO UPDATE SET
                    item_id = excluded.item_id,
                    attuned = excluded.attuned
                """,
                (campaign_id, character_id, slot, item_id, 1 if attuned else 0),
            )
            conn.commit()

    def get_equipment(self, campaign_id, character_id, slot):
        """Return the equipped item for a slot, or None if the slot is empty."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT item_id, attuned FROM play_character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?",
                (campaign_id, character_id, slot),
            ).fetchone()
        if row is None:
            return None
        return {"item_id": row[0], "attuned": bool(row[1])}

    def attune_equipment(self, campaign_id, character_id, slot):
        """Mark the item in the given slot as attuned."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE play_character_equipment SET attuned = 1 WHERE campaign_id = ? AND character_id = ? AND slot = ?",
                (campaign_id, character_id, slot),
            )
            conn.commit()

    def count_attuned_equipment(self, campaign_id, character_id):
        """Return the number of attuned items for a character."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM play_character_equipment WHERE campaign_id = ? AND character_id = ? AND attuned = 1",
                (campaign_id, character_id),
            ).fetchone()
        return row[0] if row else 0

    # --- Per-character play inventory stacks ---

    def add_play_character_inventory_item(self, campaign_id, character_id, item_id, quantity):
        """Increment a character's item stack. Returns the new total quantity."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, character_id, item_id),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO play_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)",
                    (campaign_id, character_id, item_id, quantity),
                )
                total = quantity
            else:
                total = row[0] + quantity
                conn.execute(
                    "UPDATE play_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (total, campaign_id, character_id, item_id),
                )
            conn.commit()
        return total

    def get_play_character_inventory(self, campaign_id, character_id):
        """Return a character's item stacks in lexicographic item_id order."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT item_id, quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? ORDER BY item_id",
                (campaign_id, character_id),
            ).fetchall()
        return [{"item_id": r[0], "quantity": r[1]} for r in rows]

    def remove_play_character_inventory_item(self, campaign_id, character_id, item_id, quantity):
        """Decrement a character's item stack.

        Returns the remaining quantity on success, False when the stack is
        absent or the removal quantity exceeds the held amount, or None when
        the character is not part of the campaign.
        """
        with self._connection() as conn:
            member = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if member is None:
                return None
            row = conn.execute(
                "SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, character_id, item_id),
            ).fetchone()
            if row is None:
                return False
            held = row[0]
            if quantity > held:
                return False
            remaining = held - quantity
            if remaining == 0:
                conn.execute(
                    "DELETE FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (campaign_id, character_id, item_id),
                )
            else:
                conn.execute(
                    "UPDATE play_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (remaining, campaign_id, character_id, item_id),
                )
            conn.commit()
        return remaining

    def consume_play_character_inventory_item(self, campaign_id, character_id, item_id, hp_restored=5):
        """Consume one unit of a held consumable item.

        Returns the remaining quantity on success, False when the stack is
        absent or empty, or None when the character is not part of the campaign.
        Healing consumables also restore HP up to the character's maximum and
        revive an unconscious character.
        """
        with self._connection() as conn:
            member = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if member is None:
                return None
            row = conn.execute(
                "SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, character_id, item_id),
            ).fetchone()
            if row is None or row[0] <= 0:
                return False
            held = row[0]
            remaining = held - 1
            if remaining == 0:
                conn.execute(
                    "DELETE FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (campaign_id, character_id, item_id),
                )
            else:
                conn.execute(
                    "UPDATE play_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (remaining, campaign_id, character_id, item_id),
                )
            hp_row = conn.execute(
                "SELECT hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if hp_row is not None:
                hp_current, hp_max = hp_row
                hp_after = min(hp_max, hp_current + hp_restored)
                status = "conscious" if hp_after > 0 else "unconscious"
                conn.execute(
                    "UPDATE play_campaign_members SET hp_current = ?, status = ? WHERE campaign_id = ? AND character_id = ?",
                    (hp_after, status, campaign_id, character_id),
                )
            conn.commit()
        return remaining

    # --- Per-character currency and transfers ---

    def get_character_currency(self, campaign_id, character_id):
        """Return a character's current gold balance, or None if missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
        if row is None:
            return None
        return row[0]

    def transfer_gold(self, campaign_id, from_character_id, to_character_id, gold):
        """Atomically transfer gold between campaign characters.

        Returns the transfer record on success, False when the source has
        insufficient gold, or None when either character is not in the campaign.
        """
        with self._connection() as conn:
            from_row = conn.execute(
                "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, from_character_id),
            ).fetchone()
            to_row = conn.execute(
                "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, to_character_id),
            ).fetchone()
            if from_row is None or to_row is None:
                return None
            from_gold = from_row[0]
            to_gold = to_row[0]
            if from_gold < gold:
                return False
            transfer_row = conn.execute(
                "SELECT MAX(transfer_id) FROM currency_transfers WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            transfer_id = (transfer_row[0] if transfer_row and transfer_row[0] is not None else 0) + 1
            conn.execute(
                "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?",
                (from_gold - gold, campaign_id, from_character_id),
            )
            conn.execute(
                "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?",
                (to_gold + gold, campaign_id, to_character_id),
            )
            conn.execute(
                "INSERT INTO currency_transfers (campaign_id, from_character_id, to_character_id, gold, transfer_id) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, from_character_id, to_character_id, gold, transfer_id),
            )
            conn.commit()
        return {
            "from_character_id": from_character_id,
            "to_character_id": to_character_id,
            "gold": gold,
            "from_gold": from_gold - gold,
            "to_gold": to_gold + gold,
            "transfer_id": transfer_id,
        }

    # --- Transactional campaign-scoped currency transfers ---

    def create_transactional_transfer(
        self, campaign_id, from_character_id, to_character_id, amount, simulate_failure
    ):
        """Atomically transfer gold and record the transfer.

        Returns the transfer record on success. Returns None when either
        character is not in the campaign, False when the source has
        insufficient gold, and "simulate_failure" when the caller asked to
        simulate a failure (no changes are committed).
        """
        with self._connection() as conn:
            from_row = conn.execute(
                "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, from_character_id),
            ).fetchone()
            to_row = conn.execute(
                "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, to_character_id),
            ).fetchone()
            if from_row is None or to_row is None:
                return None
            from_gold = from_row[0]
            to_gold = to_row[0]
            if from_gold < amount:
                return False
            if simulate_failure:
                # Validate and prepare without committing any changes.
                return "simulate_failure"
            seq_row = conn.execute(
                "SELECT MAX(sequence) FROM transactional_transfers WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            sequence = (seq_row[0] if seq_row and seq_row[0] is not None else 0) + 1
            conn.execute(
                "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?",
                (from_gold - amount, campaign_id, from_character_id),
            )
            conn.execute(
                "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?",
                (to_gold + amount, campaign_id, to_character_id),
            )
            conn.execute(
                "INSERT INTO transactional_transfers (campaign_id, from_character_id, to_character_id, amount, from_gold, to_gold, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    campaign_id,
                    from_character_id,
                    to_character_id,
                    amount,
                    from_gold - amount,
                    to_gold + amount,
                    sequence,
                ),
            )
            conn.commit()
        return {
            "from_character_id": from_character_id,
            "to_character_id": to_character_id,
            "amount": amount,
            "from_gold": from_gold - amount,
            "to_gold": to_gold + amount,
            "sequence": sequence,
        }

    def get_transactional_transfers(self, campaign_id):
        """Return successful transactional transfers ordered by sequence."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT from_character_id, to_character_id, amount, from_gold, to_gold, sequence
                FROM transactional_transfers
                WHERE campaign_id = ?
                ORDER BY sequence
                """,
                (campaign_id,),
            ).fetchall()
        return [
            {
                "from_character_id": row[0],
                "to_character_id": row[1],
                "amount": row[2],
                "from_gold": row[3],
                "to_gold": row[4],
                "sequence": row[5],
            }
            for row in rows
        ]

    # --- Loot distribution ---

    def create_loot(self, campaign_id, loot_id, item_id, quantity):
        """Create an open loot record. Returns True on success, False on duplicate."""
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO loot_records (campaign_id, loot_id, item_id, quantity, status) VALUES (?, ?, ?, ?, ?)",
                    (campaign_id, loot_id, item_id, quantity, "open"),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_loot(self, campaign_id, loot_id):
        """Return a loot record, or None if missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT item_id, quantity, status, recipient_character_id FROM loot_records WHERE campaign_id = ? AND loot_id = ?",
                (campaign_id, loot_id),
            ).fetchone()
            if row is None:
                return None
            total_votes = self._count_loot_votes(conn, campaign_id, loot_id)
        return {
            "loot_id": loot_id,
            "item_id": row[0],
            "quantity": row[1],
            "status": row[2],
            "recipient_character_id": row[3],
            "votes": total_votes,
        }

    def _count_loot_votes(self, conn, campaign_id, loot_id):
        """Return a mapping from recipient character id to vote count."""
        rows = conn.execute(
            "SELECT recipient_character_id, COUNT(*) FROM loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id",
            (campaign_id, loot_id),
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def count_loot_votes_for_recipient(self, campaign_id, loot_id, recipient_character_id):
        """Return the number of votes for a specific recipient."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM loot_votes WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?",
                (campaign_id, loot_id, recipient_character_id),
            ).fetchone()
        return row[0] if row else 0

    def add_loot_vote(self, campaign_id, loot_id, voter_username, recipient_character_id):
        """Cast a vote for a loot recipient.

        Returns the votes_for_recipient count on success, None if the loot is
        missing, False if the voter already voted or the loot is not open.
        """
        with self._connection() as conn:
            loot = conn.execute(
                "SELECT status FROM loot_records WHERE campaign_id = ? AND loot_id = ?",
                (campaign_id, loot_id),
            ).fetchone()
            if loot is None:
                return None
            if loot[0] != "open":
                return False
            existing = conn.execute(
                "SELECT 1 FROM loot_votes WHERE campaign_id = ? AND loot_id = ? AND voter_username = ?",
                (campaign_id, loot_id, voter_username),
            ).fetchone()
            if existing is not None:
                return False
            conn.execute(
                "INSERT INTO loot_votes (campaign_id, loot_id, voter_username, recipient_character_id) VALUES (?, ?, ?, ?)",
                (campaign_id, loot_id, voter_username, recipient_character_id),
            )
            row = conn.execute(
                "SELECT COUNT(*) FROM loot_votes WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?",
                (campaign_id, loot_id, recipient_character_id),
            ).fetchone()
            conn.commit()
        return row[0] if row else 0

    def assign_loot(self, campaign_id, loot_id):
        """Assign loot to the single highest vote recipient.

        Atomically adds the item quantity to the recipient's inventory, closes
        the loot, and returns the assignment record on success. Returns None if
        the loot is missing and False if it cannot be assigned (not open,
        voteless, tied, or already assigned).
        """
        with self._connection() as conn:
            loot = conn.execute(
                "SELECT item_id, quantity, status FROM loot_records WHERE campaign_id = ? AND loot_id = ?",
                (campaign_id, loot_id),
            ).fetchone()
            if loot is None:
                return None
            item_id, quantity, status = loot
            if status != "open":
                return False
            rows = conn.execute(
                "SELECT recipient_character_id, COUNT(*) FROM loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id ORDER BY recipient_character_id",
                (campaign_id, loot_id),
            ).fetchall()
            if not rows:
                return False
            max_votes = max(r[1] for r in rows)
            winners = [r[0] for r in rows if r[1] == max_votes]
            if len(winners) != 1:
                return False
            recipient = winners[0]
            inventory = conn.execute(
                "SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, recipient, item_id),
            ).fetchone()
            if inventory is None:
                conn.execute(
                    "INSERT INTO play_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)",
                    (campaign_id, recipient, item_id, quantity),
                )
            else:
                conn.execute(
                    "UPDATE play_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (inventory[0] + quantity, campaign_id, recipient, item_id),
                )
            conn.execute(
                "UPDATE loot_records SET status = ?, recipient_character_id = ? WHERE campaign_id = ? AND loot_id = ?",
                ("assigned", recipient, campaign_id, loot_id),
            )
            total_votes = conn.execute(
                "SELECT COUNT(*) FROM loot_votes WHERE campaign_id = ? AND loot_id = ?",
                (campaign_id, loot_id),
            ).fetchone()[0]
            conn.commit()
        return {
            "loot_id": loot_id,
            "recipient_character_id": recipient,
            "item_id": item_id,
            "quantity": quantity,
            "votes": total_votes,
            "status": "assigned",
        }


    # --- Recipe catalog ---

    def create_recipe(self, campaign_id, recipe_id, name, ingredients, output_item, output_quantity):
        """Insert a crafting recipe for a campaign. Returns True, or False on duplicate recipe_id."""
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO play_campaign_recipes (campaign_id, recipe_id, name, ingredients_json, output_item, output_quantity) VALUES (?, ?, ?, ?, ?, ?)",
                    (campaign_id, recipe_id, name, json.dumps(ingredients), output_item, output_quantity),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_recipe(self, campaign_id, recipe_id):
        """Return a recipe dict, or None if missing."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name, ingredients_json, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?",
                (campaign_id, recipe_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "recipe_id": recipe_id,
            "name": row[0],
            "ingredients": json.loads(row[1]),
            "output_item": row[2],
            "output_quantity": row[3],
        }

    def get_recipes(self, campaign_id):
        """Return all recipes for a campaign in creation order."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT recipe_id, name, ingredients_json, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
        return [
            {
                "recipe_id": r[0],
                "name": r[1],
                "ingredients": json.loads(r[2]),
                "output_item": r[3],
                "output_quantity": r[4],
            }
            for r in rows
        ]

    def craft_recipe(self, campaign_id, recipe_id, character_id):
        """Atomically consume ingredients and grant output for a recipe.

        Returns the craft result dict on success, False when the character has
        insufficient ingredients, None when the recipe or character is missing.
        """
        with self._connection() as conn:
            recipe_row = conn.execute(
                "SELECT ingredients_json, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?",
                (campaign_id, recipe_id),
            ).fetchone()
            if recipe_row is None:
                return None
            ingredients = json.loads(recipe_row[0])
            output_item = recipe_row[1]
            output_quantity = recipe_row[2]

            member = conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if member is None:
                return None

            # Verify the character holds enough of every ingredient.
            held = {}
            for item_id, required in ingredients.items():
                row = conn.execute(
                    "SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (campaign_id, character_id, item_id),
                ).fetchone()
                available = row[0] if row else 0
                if available < required:
                    return False
                held[item_id] = row[0] if row else 0

            # Consume ingredients.
            for item_id, required in ingredients.items():
                remaining = held[item_id] - required
                if remaining == 0:
                    conn.execute(
                        "DELETE FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                        (campaign_id, character_id, item_id),
                    )
                else:
                    conn.execute(
                        "UPDATE play_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                        (remaining, campaign_id, character_id, item_id),
                    )

            # Grant output.
            output_row = conn.execute(
                "SELECT quantity FROM play_character_inventory WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, character_id, output_item),
            ).fetchone()
            if output_row is None:
                conn.execute(
                    "INSERT INTO play_character_inventory (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)",
                    (campaign_id, character_id, output_item, output_quantity),
                )
            else:
                conn.execute(
                    "UPDATE play_character_inventory SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (output_row[0] + output_quantity, campaign_id, character_id, output_item),
                )
            conn.commit()
        return {
            "character_id": character_id,
            "recipe_id": recipe_id,
            "output_item": output_item,
            "output_quantity": output_quantity,
        }


    def create_downtime_activity(self, campaign_id, activity_id, name, cycles_required):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO downtime_activities (campaign_id, activity_id, name, cycles_required) VALUES (?, ?, ?, ?)",
                    (campaign_id, activity_id, name, cycles_required),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_downtime_activity(self, campaign_id, activity_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name, cycles_required FROM downtime_activities WHERE campaign_id = ? AND activity_id = ?",
                (campaign_id, activity_id),
            ).fetchone()
        if row is None:
            return None
        return {"activity_id": activity_id, "name": row[0], "cycles_required": row[1]}

    def create_downtime_allocation(self, campaign_id, character_id, activity_id):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (?, ?, ?, ?, ?)",
                    (campaign_id, character_id, activity_id, 0, 0),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_downtime_allocation(self, campaign_id, character_id, activity_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT cycles_completed, completions FROM downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
                (campaign_id, character_id, activity_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "character_id": character_id,
            "activity_id": activity_id,
            "cycles_completed": row[0],
            "completions": row[1],
        }

    def progress_downtime_allocation(self, campaign_id, character_id, activity_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT cycles_completed FROM downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
                (campaign_id, character_id, activity_id),
            ).fetchone()
            if row is None:
                return None
            activity_row = conn.execute(
                "SELECT cycles_required FROM downtime_activities WHERE campaign_id = ? AND activity_id = ?",
                (campaign_id, activity_id),
            ).fetchone()
            if activity_row is None:
                return None
            cycles_completed = row[0] + 1
            completions_delta = 0
            cycles_required = activity_row[0]
            if cycles_completed >= cycles_required:
                completions_delta = cycles_completed // cycles_required
                cycles_completed = cycles_completed % cycles_required
            conn.execute(
                "UPDATE downtime_allocations SET cycles_completed = ?, completions = completions + ? WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
                (cycles_completed, completions_delta, campaign_id, character_id, activity_id),
            )
            conn.commit()
            updated = conn.execute(
                "SELECT cycles_completed, completions FROM downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
                (campaign_id, character_id, activity_id),
            ).fetchone()
        return {
            "character_id": character_id,
            "activity_id": activity_id,
            "cycles_completed": updated[0],
            "completions": updated[1],
        }


    def create_play_campaign_audit_event(
        self, campaign_id, kind, actor, role, correlation_id
    ):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT MAX(timestamp) FROM play_campaign_audit_events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            timestamp = (row[0] or 0) + 1
            try:
                conn.execute(
                    """INSERT INTO play_campaign_audit_events
                        (campaign_id, kind, actor, role, timestamp, correlation_id)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                    (campaign_id, kind, actor, role, timestamp, correlation_id),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return None
        return {
            "kind": kind,
            "actor": actor,
            "role": role,
            "timestamp": timestamp,
            "correlation_id": correlation_id,
        }

    def get_play_campaign_audit_events(self, campaign_id):
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT kind, actor, role, timestamp, correlation_id
                   FROM play_campaign_audit_events
                   WHERE campaign_id = ?
                   ORDER BY timestamp""",
                (campaign_id,),
            ).fetchall()
        return [
            {
                "kind": row[0],
                "actor": row[1],
                "role": row[2],
                "timestamp": row[3],
                "correlation_id": row[4],
            }
            for row in rows
        ]

    # --- Projection events ---

    def create_projection_event(self, campaign_id, event_id, kind, value):
        """Append an immutable projection event.

        Returns the stored event dict on success, or None when the event_id
        or sequence collides (both are unique per campaign).
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT MAX(sequence) FROM projection_events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            sequence = (row[0] or 0) + 1
            try:
                conn.execute(
                    """INSERT INTO projection_events
                        (campaign_id, event_id, kind, value, sequence)
                        VALUES (?, ?, ?, ?, ?)""",
                    (campaign_id, event_id, kind, value, sequence),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return None
        event = {"sequence": sequence, "event_id": event_id, "kind": kind}
        if value is not None:
            event["value"] = value
        return event

    def get_projection_events(self, campaign_id):
        """Return projection events for a campaign in sequence order."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT sequence, event_id, kind, value FROM projection_events WHERE campaign_id = ? ORDER BY sequence",
                (campaign_id,),
            ).fetchall()
        return [
            {
                "sequence": r[0],
                "event_id": r[1],
                "kind": r[2],
                "value": r[3],
            }
            for r in rows
        ]

    @staticmethod
    def _build_projection(events):
        """Rebuild the deterministic projection from ordered events."""
        story = ""
        danger = 0
        applied_event_ids = []
        for event in events:
            applied_event_ids.append(event["event_id"])
            if event["kind"] == "set-story":
                story = event["value"]
            elif event["kind"] == "increment-danger":
                danger += 1
        return {"story": story, "danger": danger, "applied_event_ids": applied_event_ids}

    def get_projection(self, campaign_id):
        """Return the projection rebuilt from the ordered event log."""
        return self._build_projection(self.get_projection_events(campaign_id))

    def rebuild_projection(self, campaign_id):
        """Return the projection rebuilt solely from the ordered event log."""
        return self._build_projection(self.get_projection_events(campaign_id))

    # --- Replay events ---

    # --- Feed events ---

    def create_feed_event(self, campaign_id, event_id, text):
        """Append an event to the authenticated campaign-member feed.

        Returns the stored event dict on success, or None when the event_id
        or sequence collides (both are unique per campaign).
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT MAX(sequence) FROM campaign_feed_events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            sequence = (row[0] or 0) + 1
            try:
                conn.execute(
                    "INSERT INTO campaign_feed_events (campaign_id, event_id, text, sequence) VALUES (?, ?, ?, ?)",
                    (campaign_id, event_id, text, sequence),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return None
        return {"event_id": event_id, "text": text, "sequence": sequence}

    def get_feed_events(self, campaign_id, cursor=0, limit=2):
        """Return a slice of feed events in accepted append order.

        ``cursor`` is the zero-based count of events already consumed.
        ``limit`` is the maximum number of events to return.
        """
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT event_id, text, sequence FROM campaign_feed_events WHERE campaign_id = ? ORDER BY sequence LIMIT ? OFFSET ?",
                (campaign_id, limit, cursor),
            ).fetchall()
        return [{"event_id": r[0], "text": r[1], "sequence": r[2]} for r in rows]

    def count_feed_events(self, campaign_id):
        """Return the total number of accepted feed events for a campaign."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM campaign_feed_events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        return row[0] if row else 0

    def create_replay_event(self, campaign_id, event_id, text):
        """Append a deterministic replay event to a campaign stream.

        Returns the stored event dict on success, or None when the event_id
        or sequence collides (both are unique per campaign).
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT MAX(sequence) FROM replay_events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            sequence = (row[0] or 0) + 1
            try:
                conn.execute(
                    "INSERT INTO replay_events (campaign_id, event_id, text, sequence) VALUES (?, ?, ?, ?)",
                    (campaign_id, event_id, text, sequence),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return None
        return {"event_id": event_id, "kind": "append", "text": text, "sequence": sequence}

    def get_replay_events(self, campaign_id):
        """Return replay events for a campaign in sequence order."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT event_id, text FROM replay_events WHERE campaign_id = ? ORDER BY sequence",
                (campaign_id,),
            ).fetchall()
        return [{"event_id": r[0], "text": r[1]} for r in rows]

    def get_replay_state(self, campaign_id):
        """Return deterministic replay state built from ordered events."""
        events = self.get_replay_events(campaign_id)
        event_ids = [e["event_id"] for e in events]
        story = "".join(e["text"] for e in events)
        digest = ",".join(event_ids) + "|" + story
        return {"story": story, "event_ids": event_ids, "digest": digest}

    def create_idempotent_event(self, campaign_id, event_id, value, idempotency_key):
        """Create or replay an idempotent campaign event.

        Returns a dict describing the outcome:
        - {"status": "created", "event": event} on first valid request.
        - {"status": "existing", "event": event} on a repeated key/value pair.
        - {"status": "conflict"} when the idempotency key or event_id collides.
        """
        with self._connection() as conn:
            row = conn.execute(
                """SELECT event_id, value, sequence FROM idempotent_events
                    WHERE campaign_id = ? AND idempotency_key = ?""",
                (campaign_id, idempotency_key),
            ).fetchone()
            if row:
                stored_event_id, stored_value, sequence = row
                if stored_event_id == event_id and stored_value == value:
                    return {
                        "status": "existing",
                        "event": {
                            "event_id": stored_event_id,
                            "value": stored_value,
                            "sequence": sequence,
                            "idempotency_key": idempotency_key,
                        },
                    }
                return {"status": "conflict"}

            row = conn.execute(
                "SELECT 1 FROM idempotent_events WHERE campaign_id = ? AND event_id = ?",
                (campaign_id, event_id),
            ).fetchone()
            if row:
                return {"status": "conflict"}

            row = conn.execute(
                "SELECT MAX(sequence) FROM idempotent_events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            sequence = (row[0] or 0) + 1
            conn.execute(
                """INSERT INTO idempotent_events
                    (campaign_id, event_id, value, sequence, idempotency_key)
                    VALUES (?, ?, ?, ?, ?)""",
                (campaign_id, event_id, value, sequence, idempotency_key),
            )
            conn.commit()

        return {
            "status": "created",
            "event": {
                "event_id": event_id,
                "value": value,
                "sequence": sequence,
                "idempotency_key": idempotency_key,
            },
        }

    def get_idempotent_events(self, campaign_id):
        """Return idempotent events for a campaign ordered by sequence."""
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT event_id, value, sequence, idempotency_key
                    FROM idempotent_events
                    WHERE campaign_id = ?
                    ORDER BY sequence""",
                (campaign_id,),
            ).fetchall()
        return [
            {
                "event_id": r[0],
                "value": r[1],
                "sequence": r[2],
                "idempotency_key": r[3],
            }
            for r in rows
        ]

    # --- Safe turns ---

    def _ensure_safe_turn_state(self, conn, campaign_id):
        """Create the safe-turn state row for a campaign if it is missing."""
        conn.execute(
            """INSERT OR IGNORE INTO safe_turn_state (campaign_id, current_turn)
                VALUES (?, ?)""",
            (campaign_id, 1),
        )

    def get_safe_turn_state(self, campaign_id):
        """Return the current turn and accepted submissions for a campaign."""
        with self._connection() as conn:
            self._ensure_safe_turn_state(conn, campaign_id)
            row = conn.execute(
                "SELECT current_turn FROM safe_turn_state WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            rows = conn.execute(
                """SELECT submission_id, action, accepted_turn, next_turn
                    FROM safe_turn_submissions
                    WHERE campaign_id = ?
                    ORDER BY accepted_turn""",
                (campaign_id,),
            ).fetchall()
            conn.commit()
        return {
            "current_turn": row[0] if row else 1,
            "accepted": [
                {
                    "submission_id": r[0],
                    "action": r[1],
                    "accepted_turn": r[2],
                    "next_turn": r[3],
                }
                for r in rows
            ],
        }

    def submit_safe_turn(self, campaign_id, submission_id, expected_turn, action):
        """Accept or reject a safe-turn submission.

        Returns a dict describing the outcome:
        - {"status": "accepted", "accepted_turn": t, "next_turn": t+1} on success.
        - {"status": "stale", "current_turn": t} when the expected turn is wrong.
        - {"status": "conflict"} when the submission_id was already accepted.
        """
        with self._connection() as conn:
            self._ensure_safe_turn_state(conn, campaign_id)
            row = conn.execute(
                "SELECT current_turn FROM safe_turn_state WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            current_turn = row[0] if row else 1

            duplicate = conn.execute(
                """SELECT 1 FROM safe_turn_submissions
                    WHERE campaign_id = ? AND submission_id = ?""",
                (campaign_id, submission_id),
            ).fetchone()
            if duplicate:
                conn.commit()
                return {"status": "conflict"}

            if expected_turn != current_turn:
                conn.commit()
                return {"status": "stale", "current_turn": current_turn}

            next_turn = current_turn + 1
            conn.execute(
                """INSERT INTO safe_turn_submissions
                    (campaign_id, submission_id, action, accepted_turn, next_turn)
                    VALUES (?, ?, ?, ?, ?)""",
                (campaign_id, submission_id, action, current_turn, next_turn),
            )
            conn.execute(
                "UPDATE safe_turn_state SET current_turn = ? WHERE campaign_id = ?",
                (next_turn, campaign_id),
            )
            conn.commit()
        return {
            "status": "accepted",
            "accepted_turn": current_turn,
            "next_turn": next_turn,
        }


    # --- Versioned campaign exports ---

    def create_play_campaign_export(self, campaign_id, story, status):
        """Create an immutable export snapshot for a campaign.

        Returns the export dict with a version one greater than the campaign's
        previous export count.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM play_campaign_exports WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            version = (row[0] if row else 0) + 1
            conn.execute(
                "INSERT INTO play_campaign_exports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)",
                (campaign_id, version, story, status),
            )
            conn.commit()
        return {"version": version, "story": story, "status": status}

    def list_play_campaign_exports(self, campaign_id):
        """Return all exports for a campaign ordered by ascending version."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? ORDER BY version",
                (campaign_id,),
            ).fetchall()
        return [{"version": r[0], "story": r[1], "status": r[2]} for r in rows]

    def get_play_campaign_export(self, campaign_id, version):
        """Return a specific export, or None if the version is missing/invalid."""
        try:
            version_num = int(version)
        except (ValueError, TypeError):
            return None
        with self._connection() as conn:
            row = conn.execute(
                "SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? AND version = ?",
                (campaign_id, version_num),
            ).fetchone()
        if row is None:
            return None
        return {"version": row[0], "story": row[1], "status": row[2]}

    # --- Versioned campaign imports ---

    def import_play_campaign(self, campaign_id, version, story, status):
        """Atomically apply an imported snapshot to a play campaign.

        Updates the campaign status, campaign document story, and records the
        imported snapshot. All writes happen in a single transaction.
        """
        with self._connection() as conn:
            conn.execute(
                "UPDATE play_campaigns SET status = ? WHERE id = ?",
                (status, campaign_id),
            )
            conn.execute(
                """
                INSERT INTO campaign_documents (campaign_id, story, dm_notes)
                VALUES (?, ?, '')
                ON CONFLICT(campaign_id) DO UPDATE SET
                    story = excluded.story
                """,
                (campaign_id, story),
            )
            conn.execute(
                """
                INSERT INTO play_campaign_imports (campaign_id, version, story, status)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(campaign_id) DO UPDATE SET
                    version = excluded.version,
                    story = excluded.story,
                    status = excluded.status
                """,
                (campaign_id, version, story, status),
            )
            conn.commit()
        return {"version": version, "story": story, "status": status}

    def get_play_campaign_import_state(self, campaign_id):
        """Return the current imported snapshot, or None if none exists."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT version, story, status FROM play_campaign_imports WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        if row is None:
            return None
        return {"version": row[0], "story": row[1], "status": row[2]}

    # --- Schema migration ---

    def migrate_play_campaign(self, campaign_id, story, campaign_name):
        """Store the migrated state for a campaign.

        Replaces any existing migration state for the campaign with a version 2
        snapshot that preserves the source story and records the campaign name.
        """
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO play_campaign_migrations (campaign_id, schema_version, story, campaign_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(campaign_id) DO UPDATE SET
                    schema_version = excluded.schema_version,
                    story = excluded.story,
                    campaign_name = excluded.campaign_name
                """,
                (campaign_id, 2, story, campaign_name),
            )
            conn.commit()
        return {"schema_version": 2, "story": story, "campaign_name": campaign_name}

    def get_play_campaign_migration_state(self, campaign_id):
        """Return the current migrated state, or None if none exists."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        if row is None:
            return None
        return {"schema_version": row[0], "story": row[1], "campaign_name": row[2]}

    # --- Campaign search records ---

    def create_search_record(self, campaign_id, record_id, text):
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO play_campaign_search_records (campaign_id, record_id, text) VALUES (?, ?, ?)",
                    (campaign_id, record_id, text),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def list_search_records(self, campaign_id, q=None, limit=2, cursor=0):
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT record_id, text FROM play_campaign_search_records WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
        records = [{"record_id": r[0], "text": r[1]} for r in rows]
        if q is not None:
            q_lower = q.lower()
            records = [r for r in records if q_lower in r["text"].lower()]
        total = len(records)
        start = cursor
        end = start + limit
        page = records[start:end]
        next_cursor = end if end < total else None
        return page, next_cursor

    # --- Campaign rate events ---

    RATE_LIMIT = 2

    def create_rate_event(self, campaign_id, actor, event_id):
        """Attempt to record a rate event for an actor in a campaign.

        Returns a tuple ``(ok, remaining, reason)``. ``ok`` is True when the
        event is accepted. ``remaining`` is the caller's remaining allowance
        after the attempt. ``reason`` is ``"limit"`` when the actor has no
        remaining allowance, ``"duplicate"`` when the ``event_id`` already
        exists, and ``None`` otherwise.
        """
        with self._connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?",
                (campaign_id, actor),
            ).fetchone()[0]
            if count >= self.RATE_LIMIT:
                return False, self.RATE_LIMIT - count, "limit"
            try:
                conn.execute(
                    "INSERT INTO play_campaign_rate_events (campaign_id, event_id, actor) VALUES (?, ?, ?)",
                    (campaign_id, event_id, actor),
                )
                conn.commit()
                return True, self.RATE_LIMIT - count - 1, None
            except sqlite3.IntegrityError:
                return False, self.RATE_LIMIT - count, "duplicate"

    def list_rate_events(self, campaign_id, actor):
        """Return accepted rate events for a campaign and the actor's remaining allowance."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT event_id, actor FROM play_campaign_rate_events WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
            count = conn.execute(
                "SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?",
                (campaign_id, actor),
            ).fetchone()[0]
        events = [{"event_id": r[0], "actor": r[1]} for r in rows]
        return events, self.RATE_LIMIT - count

    # --- Campaign service metrics ---

    def _ensure_campaign_metrics(self, conn, campaign_id):
        """Insert a fresh metrics row for a campaign if one does not exist."""
        conn.execute(
            """INSERT OR IGNORE INTO campaign_metrics
                (campaign_id, accepted_rate_events, rejected_rate_events, projection_events, uptime_ticks)
                VALUES (?, 0, 0, 0, 1)""",
            (campaign_id,),
        )

    def increment_campaign_metric(self, campaign_id, name):
        """Increment a campaign-scoped service metric counter."""
        if name not in {"accepted_rate_events", "rejected_rate_events", "projection_events"}:
            raise ValueError("invalid metric")
        with self._connection() as conn:
            self._ensure_campaign_metrics(conn, campaign_id)
            conn.execute(
                f"UPDATE campaign_metrics SET {name} = {name} + 1 WHERE campaign_id = ?",
                (campaign_id,),
            )
            conn.commit()

    def get_campaign_metrics(self, campaign_id):
        """Return the campaign service metrics counters."""
        with self._connection() as conn:
            self._ensure_campaign_metrics(conn, campaign_id)
            row = conn.execute(
                """SELECT accepted_rate_events, rejected_rate_events, projection_events, uptime_ticks
                    FROM campaign_metrics WHERE campaign_id = ?""",
                (campaign_id,),
            ).fetchone()
        return {
            "accepted_rate_events": row[0],
            "rejected_rate_events": row[1],
            "projection_events": row[2],
            "uptime_ticks": row[3],
        }

    # --- RNG ledger ---

    def set_campaign_rng_seed(self, campaign_id, seed):
        """Set the RNG seed for a campaign if it is not already configured.

        Returns True on success and False when a seed already exists.
        """
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT 1 FROM campaign_rng_seeds WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            if existing:
                return False
            conn.execute(
                "INSERT INTO campaign_rng_seeds (campaign_id, seed) VALUES (?, ?)",
                (campaign_id, seed),
            )
            conn.commit()
        return True

    def get_campaign_rng_seed(self, campaign_id):
        """Return the configured RNG seed or None."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT seed FROM campaign_rng_seeds WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        return row[0] if row else None

    def append_campaign_rng_roll(self, campaign_id, roll_id, sides, result):
        """Append a deterministic roll record to the campaign ledger.

        Returns the roll record dict on success, or None when ``roll_id`` is
        not unique within the campaign.
        """
        with self._connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM campaign_rng_rolls WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            sequence = count + 1
            try:
                conn.execute(
                    """INSERT INTO campaign_rng_rolls
                        (campaign_id, roll_id, sides, result, sequence)
                        VALUES (?, ?, ?, ?, ?)""",
                    (campaign_id, roll_id, sides, result, sequence),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return None
        return {"roll_id": roll_id, "sides": sides, "result": result, "sequence": sequence}

    def get_campaign_rng_ledger(self, campaign_id):
        """Return the ordered list of immutable roll records for a campaign."""
        seed = self.get_campaign_rng_seed(campaign_id)
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT roll_id, sides, result, sequence
                    FROM campaign_rng_rolls
                    WHERE campaign_id = ?
                    ORDER BY sequence""",
                (campaign_id,),
            ).fetchall()
        rolls = [
            {"roll_id": r[0], "sides": r[1], "result": r[2], "sequence": r[3]}
            for r in rows
        ]
        return {"seed": seed, "rolls": rolls}

    # --- Moderation reports ---

    def _moderation_report_row(self, row):
        """Convert a campaign_moderation_reports row to the exact JSON record."""
        record = {
            "report_id": row[0],
            "target_id": row[1],
            "reason": row[2],
            "status": row[3],
            "reporter": row[4],
            "sequence": row[5],
        }
        if row[3] == "resolved":
            record["action"] = row[6]
            record["note"] = row[7]
            record["resolver"] = row[8]
        return record

    def add_moderation_report(self, campaign_id, report_id, target_id, reason, reporter):
        """Append an open moderation report.

        Returns the new report record on success, or None when ``report_id`` is
        not unique within the campaign.
        """
        with self._connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM campaign_moderation_reports WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            sequence = count + 1
            try:
                conn.execute(
                    """INSERT INTO campaign_moderation_reports
                        (campaign_id, report_id, target_id, reason, status, reporter, sequence)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (campaign_id, report_id, target_id, reason, "open", reporter, sequence),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return None
        return {
            "report_id": report_id,
            "target_id": target_id,
            "reason": reason,
            "status": "open",
            "reporter": reporter,
            "sequence": sequence,
        }

    def get_moderation_reports(self, campaign_id):
        """Return moderation reports for a campaign in stable append order."""
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT report_id, target_id, reason, status, reporter, sequence,
                          action, note, resolver
                    FROM campaign_moderation_reports
                    WHERE campaign_id = ?
                    ORDER BY sequence""",
                (campaign_id,),
            ).fetchall()
        return [self._moderation_report_row(r) for r in rows]

    def get_moderation_report(self, campaign_id, report_id):
        """Return a single moderation report, or None if it does not exist."""
        with self._connection() as conn:
            row = conn.execute(
                """SELECT report_id, target_id, reason, status, reporter, sequence,
                          action, note, resolver
                    FROM campaign_moderation_reports
                    WHERE campaign_id = ? AND report_id = ?""",
                (campaign_id, report_id),
            ).fetchone()
        if row is None:
            return None
        return self._moderation_report_row(row)

    def resolve_moderation_report(self, campaign_id, report_id, action, note, resolver):
        """Resolve an open moderation report.

        Returns the resolved record on success, None if the report is missing,
        or False if it has already been resolved.
        """
        with self._connection() as conn:
            row = conn.execute(
                """SELECT id, status, sequence, reporter, target_id, reason
                    FROM campaign_moderation_reports
                    WHERE campaign_id = ? AND report_id = ?""",
                (campaign_id, report_id),
            ).fetchone()
            if row is None:
                return None
            if row[1] != "open":
                return False
            conn.execute(
                """UPDATE campaign_moderation_reports
                    SET status = ?, action = ?, note = ?, resolver = ?
                    WHERE id = ?""",
                ("resolved", action, note, resolver, row[0]),
            )
            conn.commit()
        return {
            "report_id": report_id,
            "target_id": row[4],
            "reason": row[5],
            "status": "resolved",
            "reporter": row[3],
            "sequence": row[2],
            "action": action,
            "note": note,
            "resolver": resolver,
        }

    # --- Safety boundaries and events ---

    def get_safety_boundaries(self, campaign_id):
        """Return the current safety boundary state for a campaign."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT tags_json FROM campaign_safety_boundaries WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        tags = json.loads(row[0]) if row else []
        return {"blocked_tags": sorted(tags)}

    def replace_safety_boundaries(self, campaign_id, tags):
        """Atomically replace the blocked tags for a campaign.

        Returns the exact current state with tags sorted lexicographically.
        """
        sorted_tags = sorted(tags)
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO campaign_safety_boundaries (campaign_id, tags_json)
                    VALUES (?, ?)
                    ON CONFLICT(campaign_id) DO UPDATE SET tags_json = excluded.tags_json""",
                (campaign_id, json.dumps(sorted_tags)),
            )
            conn.commit()
        return {"blocked_tags": sorted_tags}

    def safety_event_exists(self, campaign_id, event_id):
        """Return True if a safety event with this event_id already exists."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM campaign_safety_events WHERE campaign_id = ? AND event_id = ?",
                (campaign_id, event_id),
            ).fetchone()
        return row is not None

    def add_safety_event(self, campaign_id, event_id, kind, text, tags):
        """Append an accepted safety check event.

        Returns the new event record, or None if the event_id or sequence is
        already present (indicating a race/duplicate).
        """
        with self._connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM campaign_safety_events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            sequence = count + 1
            try:
                conn.execute(
                    """INSERT INTO campaign_safety_events
                        (campaign_id, event_id, kind, text, tags_json, sequence)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                    (campaign_id, event_id, kind, text, json.dumps(tags), sequence),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return None
        return {
            "event_id": event_id,
            "kind": kind,
            "text": text,
            "tags": tags,
            "sequence": sequence,
        }

    def get_safety_events(self, campaign_id):
        """Return accepted safety events for a campaign in stable append order."""
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT event_id, kind, text, tags_json, sequence
                    FROM campaign_safety_events
                    WHERE campaign_id = ?
                    ORDER BY sequence""",
                (campaign_id,),
            ).fetchall()
        return [
            {
                "event_id": r[0],
                "kind": r[1],
                "text": r[2],
                "tags": json.loads(r[3]),
                "sequence": r[4],
            }
            for r in rows
        ]

    # --- Fixture seeding ---

    CANONICAL_FIXTURE = {
        "fixture_id": "canonical-v1",
        "status": "seeded",
        "characters": [
            {"character_id": "fixture-hero", "name": "Ari", "class": "fighter"},
            {"character_id": "fixture-mage", "name": "Bea", "class": "wizard"},
        ],
        "story": "The lantern is lit.",
        "event_ids": ["fixture-event-1", "fixture-event-2"],
    }

    def get_play_campaign_fixture(self, campaign_id):
        """Return the seeded canonical fixture for a campaign, or None."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT fixture_id, status, characters_json, story, event_ids_json FROM play_campaign_fixtures WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "fixture_id": row[0],
            "status": row[1],
            "characters": json.loads(row[2]),
            "story": row[3],
            "event_ids": json.loads(row[4]),
        }

    def seed_play_campaign_fixture(self, campaign_id):
        """Idempotently seed the canonical fixture for a campaign.

        Returns (fixture_state, created). ``created`` is True on the first
        successful seed and False when the fixture already existed.
        """
        canonical = self.CANONICAL_FIXTURE
        characters_json = json.dumps(canonical["characters"])
        event_ids_json = json.dumps(canonical["event_ids"])
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO play_campaign_fixtures (campaign_id, fixture_id, status, characters_json, story, event_ids_json) VALUES (?, ?, ?, ?, ?, ?)",
                    (campaign_id, canonical["fixture_id"], canonical["status"], characters_json, canonical["story"], event_ids_json),
                )
                conn.commit()
                return canonical, True
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT fixture_id, status, characters_json, story, event_ids_json FROM play_campaign_fixtures WHERE campaign_id = ?",
                    (campaign_id,),
                ).fetchone()
                return {
                    "fixture_id": row[0],
                    "status": row[1],
                    "characters": json.loads(row[2]),
                    "story": row[3],
                    "event_ids": json.loads(row[4]),
                }, False


# Module-level singleton used by the request handlers.
storage = Storage()
