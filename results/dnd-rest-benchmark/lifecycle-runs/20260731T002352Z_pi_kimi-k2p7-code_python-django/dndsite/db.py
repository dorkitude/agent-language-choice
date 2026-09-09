"""SQLite persistence layer."""

import json
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
        current_location_id TEXT,
        phase TEXT DEFAULT 'exploration',
        saved_actor TEXT,
        last_action_actor TEXT,
        safe_turn_current_turn INTEGER NOT NULL DEFAULT 1
        """,
    ),
    (
        "play_fixture_seeds",
        """
        campaign_id TEXT PRIMARY KEY,
        fixture_id TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_campaign_backups",
        """
        campaign_id TEXT NOT NULL,
        backup_id TEXT NOT NULL,
        story TEXT NOT NULL,
        status TEXT NOT NULL,
        PRIMARY KEY (campaign_id, backup_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "safe_turn_submissions",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        submission_id TEXT NOT NULL,
        action TEXT,
        accepted_turn INTEGER,
        next_turn INTEGER,
        accepted INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        UNIQUE (campaign_id, submission_id)
        """,
    ),
    (
        "projection_events",
        """
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        value TEXT,
        PRIMARY KEY (campaign_id, sequence),
        UNIQUE (campaign_id, event_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "idempotent_events",
        """
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        value TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence),
        UNIQUE (campaign_id, event_id),
        UNIQUE (campaign_id, idempotency_key),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "replay_events",
        """
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence),
        UNIQUE (campaign_id, event_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_campaign_feed_events",
        """
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence),
        UNIQUE (campaign_id, event_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_campaign_invitations",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        invitation_id TEXT NOT NULL,
        username TEXT NOT NULL,
        character_id TEXT NOT NULL,
        status TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        UNIQUE (campaign_id, invitation_id)
        """,
    ),
    (
        "play_campaign_session_zero",
        """
        campaign_id TEXT PRIMARY KEY,
        rules TEXT NOT NULL,
        tone TEXT NOT NULL,
        consent_json TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_content",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        content_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        text TEXT NOT NULL,
        tags_json TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        UNIQUE (campaign_id, content_id)
        """,
    ),
    (
        "play_settlements",
        """
        campaign_id TEXT NOT NULL,
        settlement_id TEXT NOT NULL,
        name TEXT NOT NULL,
        services_json TEXT NOT NULL,
        availability TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, settlement_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_shops",
        """
        campaign_id TEXT NOT NULL,
        settlement_id TEXT NOT NULL,
        shop_id TEXT NOT NULL,
        name TEXT NOT NULL,
        stock_json TEXT NOT NULL,
        buy_price INTEGER NOT NULL,
        sell_price INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, settlement_id, shop_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_settlements(campaign_id, settlement_id) ON DELETE CASCADE
        """,
    ),
    (
        "play_recipes",
        """
        campaign_id TEXT NOT NULL,
        recipe_id TEXT NOT NULL,
        name TEXT NOT NULL,
        ingredients_json TEXT NOT NULL,
        output_item TEXT NOT NULL,
        output_quantity INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, recipe_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_factions",
        """
        campaign_id TEXT NOT NULL,
        faction_id TEXT NOT NULL,
        name TEXT NOT NULL,
        PRIMARY KEY (campaign_id, faction_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_campaign_npcs",
        """
        campaign_id TEXT NOT NULL,
        npc_id TEXT NOT NULL,
        name TEXT NOT NULL,
        agenda TEXT NOT NULL,
        public_status TEXT NOT NULL,
        PRIMARY KEY (campaign_id, npc_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_npc_dialogue",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        npc_id TEXT NOT NULL,
        dialogue_id TEXT NOT NULL,
        speaker TEXT NOT NULL,
        text TEXT NOT NULL,
        visibility TEXT NOT NULL,
        FOREIGN KEY (campaign_id, npc_id) REFERENCES play_campaign_npcs(campaign_id, npc_id) ON DELETE CASCADE,
        UNIQUE (campaign_id, npc_id, dialogue_id)
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
        owner TEXT,
        character_id TEXT NOT NULL,
        name TEXT NOT NULL,
        class_name TEXT NOT NULL,
        level INTEGER NOT NULL DEFAULT 1,
        abilities_json TEXT NOT NULL DEFAULT '{}',
        sequence INTEGER NOT NULL,
        hp_current INTEGER NOT NULL DEFAULT 20,
        hp_max INTEGER NOT NULL DEFAULT 20,
        status TEXT DEFAULT 'conscious',
        death_save_successes INTEGER DEFAULT 0,
        death_save_failures INTEGER DEFAULT 0,
        concentration_json TEXT DEFAULT NULL,
        gold INTEGER NOT NULL DEFAULT 10,
        quest_rewards_xp INTEGER NOT NULL DEFAULT 0,
        quest_rewards_items_json TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        PRIMARY KEY (campaign_id, character_id),
        UNIQUE (campaign_id, username)
        """,
    ),
    (
        "play_rate_events",
        """
        campaign_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        actor TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, event_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "service_metrics",
        """
        campaign_id TEXT PRIMARY KEY,
        rejected_rate_events INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_campaign_delegations",
        """
        campaign_id TEXT NOT NULL,
        username TEXT NOT NULL,
        powers_json TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (campaign_id, username),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_campaign_delegation_audit",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        username TEXT NOT NULL,
        action TEXT NOT NULL,
        powers_json TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_audit_events",
        """
        campaign_id TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        kind TEXT NOT NULL,
        actor TEXT NOT NULL,
        role TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        PRIMARY KEY (campaign_id, timestamp),
        UNIQUE (campaign_id, correlation_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "downtime_activities",
        """
        campaign_id TEXT NOT NULL,
        activity_id TEXT NOT NULL,
        name TEXT NOT NULL,
        cycles_required INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, activity_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "downtime_allocations",
        """
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        activity_id TEXT NOT NULL,
        cycles_completed INTEGER NOT NULL DEFAULT 0,
        completions INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (campaign_id, character_id, activity_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE,
        FOREIGN KEY (campaign_id, activity_id) REFERENCES downtime_activities(campaign_id, activity_id) ON DELETE CASCADE
        """,
    ),
    (
        "play_settlement_discoveries",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        settlement_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_settlements(campaign_id, settlement_id) ON DELETE CASCADE,
        FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE,
        UNIQUE (campaign_id, settlement_id, character_id)
        """,
    ),
    (
        "play_clues",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        clue_id TEXT NOT NULL,
        text TEXT NOT NULL,
        audience TEXT NOT NULL,
        character_id TEXT,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE,
        UNIQUE (campaign_id, clue_id)
        """,
    ),
    (
        "play_notes",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        note_id TEXT NOT NULL,
        text TEXT NOT NULL,
        visibility TEXT NOT NULL,
        owner TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        UNIQUE (campaign_id, note_id)
        """,
    ),
    (
        "play_whispers",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        whisper_id TEXT NOT NULL,
        from_character_id TEXT NOT NULL,
        to_character_id TEXT NOT NULL,
        text TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        UNIQUE (campaign_id, whisper_id)
        """,
    ),
    (
        "play_messages",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        message_id TEXT NOT NULL,
        text TEXT NOT NULL,
        author TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'message',
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        UNIQUE (campaign_id, message_id)
        """,
    ),
    (
        "play_search_records",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        record_id TEXT NOT NULL,
        text TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        UNIQUE (campaign_id, record_id),
        UNIQUE (campaign_id, text)
        """,
    ),
    (
        "play_relationships",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        score INTEGER NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        UNIQUE (campaign_id, source_id, target_id, kind)
        """,
    ),
    (
        "play_quests",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        quest_id TEXT NOT NULL,
        title TEXT NOT NULL,
        depends_on_json TEXT NOT NULL,
        state TEXT NOT NULL,
        rewards_json TEXT DEFAULT '{}',
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        UNIQUE (campaign_id, quest_id)
        """,
    ),
    (
        "play_quest_awards",
        """
        campaign_id TEXT NOT NULL,
        quest_id TEXT NOT NULL,
        PRIMARY KEY (campaign_id, quest_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY (campaign_id, quest_id) REFERENCES play_quests(campaign_id, quest_id) ON DELETE CASCADE
        """,
    ),
    (
        "play_world_events",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        turn_number INTEGER NOT NULL,
        title TEXT NOT NULL,
        text TEXT NOT NULL,
        status TEXT NOT NULL,
        resolution_text TEXT,
        resolution_turn_number INTEGER,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        UNIQUE (campaign_id, event_id)
        """,
    ),
    (
        "play_campaign_calendars",
        """
        campaign_id TEXT PRIMARY KEY,
        day INTEGER NOT NULL,
        season TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_reputation_history",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        faction_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        delta INTEGER NOT NULL,
        reason TEXT NOT NULL,
        reputation INTEGER NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY (campaign_id, faction_id) REFERENCES play_factions(campaign_id, faction_id) ON DELETE CASCADE,
        FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
        """,
    ),
    (
        "play_currency_transfers",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        transfer_id INTEGER NOT NULL,
        from_character_id TEXT NOT NULL,
        to_character_id TEXT NOT NULL,
        gold INTEGER NOT NULL,
        from_gold INTEGER NOT NULL,
        to_gold INTEGER NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        UNIQUE (campaign_id, transfer_id)
        """,
    ),
    (
        "play_transactional_transfers",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        from_character_id TEXT NOT NULL,
        to_character_id TEXT NOT NULL,
        amount INTEGER NOT NULL,
        from_gold INTEGER NOT NULL,
        to_gold INTEGER NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        UNIQUE (campaign_id, sequence)
        """,
    ),
    (
        "play_loot",
        """
        campaign_id TEXT NOT NULL,
        loot_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        status TEXT NOT NULL,
        recipient_character_id TEXT,
        PRIMARY KEY (campaign_id, loot_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_loot_votes",
        """
        campaign_id TEXT NOT NULL,
        loot_id TEXT NOT NULL,
        voter TEXT NOT NULL,
        recipient_character_id TEXT NOT NULL,
        PRIMARY KEY (campaign_id, loot_id, voter),
        FOREIGN KEY (campaign_id, loot_id) REFERENCES play_loot(campaign_id, loot_id) ON DELETE CASCADE
        """,
    ),
    (
        "play_character_inventory",
        """
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id, item_id),
        FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
        """,
    ),
    (
        "play_character_equipment",
        """
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        slot TEXT NOT NULL,
        item_id TEXT NOT NULL,
        attuned INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (campaign_id, character_id, slot),
        FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE
        """,
    ),
    (
        "spells",
        """
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        spell_id TEXT NOT NULL,
        name TEXT NOT NULL,
        level INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id, spell_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "prepared_spells",
        """
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        spell_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id, spell_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
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
        target TEXT,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        UNIQUE (campaign_id, sequence)
        """,
    ),
    (
        "play_campaign_exports",
        """
        campaign_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        story TEXT NOT NULL,
        status TEXT NOT NULL,
        PRIMARY KEY (campaign_id, version),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_campaign_imports",
        """
        campaign_id TEXT PRIMARY KEY,
        version INTEGER NOT NULL,
        story TEXT NOT NULL,
        status TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_campaign_migrations",
        """
        campaign_id TEXT PRIMARY KEY,
        schema_version INTEGER NOT NULL,
        story TEXT NOT NULL,
        campaign_name TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
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
    (
        "encounters",
        """
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL,
        combatants_json TEXT NOT NULL,
        conditions_json TEXT NOT NULL DEFAULT '{}',
        order_json TEXT NOT NULL DEFAULT '[]',
        round INTEGER NOT NULL DEFAULT 1,
        turn_index INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "readied_actions",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        encounter_id TEXT NOT NULL,
        actor TEXT NOT NULL,
        trigger TEXT NOT NULL,
        FOREIGN KEY (encounter_id) REFERENCES encounters(id) ON DELETE CASCADE
        """,
    ),
    (
        "encounter_rewards",
        """
        encounter_id TEXT PRIMARY KEY,
        xp INTEGER NOT NULL,
        loot_json TEXT NOT NULL,
        FOREIGN KEY (encounter_id) REFERENCES encounters(id) ON DELETE CASCADE
        """,
    ),
    (
        "spell_casts",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        spell_id TEXT NOT NULL,
        target TEXT NOT NULL,
        slot_level INTEGER NOT NULL,
        slots_remaining INTEGER NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id) ON DELETE CASCADE,
        UNIQUE (campaign_id, character_id, sequence)
        """,
    ),
    (
        "play_campaign_rng_seeds",
        """
        campaign_id TEXT PRIMARY KEY,
        seed TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_campaign_rng_rolls",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        roll_id TEXT NOT NULL,
        sides INTEGER NOT NULL,
        result INTEGER NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        UNIQUE (campaign_id, sequence),
        UNIQUE (campaign_id, roll_id)
        """,
    ),
    (
        "moderation_reports",
        """
        campaign_id TEXT NOT NULL,
        report_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        reporter TEXT NOT NULL,
        status TEXT NOT NULL,
        action TEXT,
        note TEXT,
        resolver TEXT,
        sequence INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, report_id),
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_campaign_safety_boundaries",
        """
        campaign_id TEXT PRIMARY KEY,
        blocked_tags_json TEXT NOT NULL DEFAULT '[]',
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE
        """,
    ),
    (
        "play_campaign_safety_events",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        text TEXT NOT NULL,
        tags_json TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE,
        UNIQUE (campaign_id, sequence),
        UNIQUE (campaign_id, event_id)
        """,
    ),
    (
        "play_campaign_spectators",
        """
        spectator_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
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


def _add_play_inventory_item(conn, campaign_id, character_id, item_id, quantity):
    """Increment or create a play campaign character inventory stack.

    Returns the new total quantity for the stack.
    """
    row = conn.execute(
        "SELECT quantity FROM play_character_inventory "
        "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
        (campaign_id, character_id, item_id),
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO play_character_inventory (campaign_id, character_id, item_id, quantity) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, character_id, item_id, quantity),
        )
        return quantity
    new_quantity = row["quantity"] + quantity
    conn.execute(
        "UPDATE play_character_inventory SET quantity = ? "
        "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
        (new_quantity, campaign_id, character_id, item_id),
    )
    return new_quantity


def _remove_play_inventory_item(conn, campaign_id, character_id, item_id, quantity):
    """Decrement a play campaign character inventory stack.

    Returns the remaining total quantity. Raises ``ValueError`` if the
    requested quantity exceeds the held stack.
    """
    row = conn.execute(
        "SELECT quantity FROM play_character_inventory "
        "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
        (campaign_id, character_id, item_id),
    ).fetchone()
    if row is None or row["quantity"] < quantity:
        raise ValueError("insufficient quantity")
    remaining = row["quantity"] - quantity
    if remaining == 0:
        conn.execute(
            "DELETE FROM play_character_inventory "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        )
    else:
        conn.execute(
            "UPDATE play_character_inventory SET quantity = ? "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (remaining, campaign_id, character_id, item_id),
        )
    return remaining


def _get_play_inventory(conn, campaign_id, character_id):
    """Return the character's inventory items in lexicographic ``item_id`` order."""
    rows = conn.execute(
        "SELECT item_id, quantity FROM play_character_inventory "
        "WHERE campaign_id = ? AND character_id = ? "
        "ORDER BY item_id",
        (campaign_id, character_id),
    ).fetchall()
    return [{"item_id": row["item_id"], "quantity": row["quantity"]} for row in rows]


def _get_play_equipment(conn, campaign_id, character_id, slot):
    """Return the equipped item for a character slot, if any."""
    return conn.execute(
        "SELECT item_id, attuned FROM play_character_equipment "
        "WHERE campaign_id = ? AND character_id = ? AND slot = ?",
        (campaign_id, character_id, slot),
    ).fetchone()


def _set_play_equipment(conn, campaign_id, character_id, slot, item_id, attuned=0):
    """Equip or replace an item in a character equipment slot."""
    conn.execute(
        "INSERT INTO play_character_equipment (campaign_id, character_id, slot, item_id, attuned) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET "
        "item_id = excluded.item_id, attuned = excluded.attuned",
        (campaign_id, character_id, slot, item_id, 1 if attuned else 0),
    )


def _count_play_attunements(conn, campaign_id, character_id):
    """Return the number of attuned items a character currently has."""
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM play_character_equipment "
        "WHERE campaign_id = ? AND character_id = ? AND attuned = 1",
        (campaign_id, character_id),
    ).fetchone()
    return row["count"]


def _get_character_gold(conn, campaign_id, character_id):
    """Return the character's gold balance, or ``None`` if not found."""
    row = conn.execute(
        "SELECT gold FROM play_campaign_members "
        "WHERE campaign_id = ? AND character_id = ?",
        (campaign_id, character_id),
    ).fetchone()
    if row is None:
        return None
    return row["gold"]


def _set_character_gold(conn, campaign_id, character_id, gold):
    """Set the character's gold balance."""
    conn.execute(
        "UPDATE play_campaign_members SET gold = ? "
        "WHERE campaign_id = ? AND character_id = ?",
        (gold, campaign_id, character_id),
    )


def _next_transfer_id(conn, campaign_id):
    """Return the next campaign-local transfer id (starting at 1)."""
    row = conn.execute(
        "SELECT COALESCE(MAX(transfer_id), 0) + 1 AS next_id "
        "FROM play_currency_transfers WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    return row["next_id"]


def _record_transfer(conn, campaign_id, transfer_id, from_character_id, to_character_id, gold, from_gold, to_gold):
    """Record a completed currency transfer in the campaign ledger."""
    conn.execute(
        "INSERT INTO play_currency_transfers "
        "(campaign_id, transfer_id, from_character_id, to_character_id, gold, from_gold, to_gold) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (campaign_id, transfer_id, from_character_id, to_character_id, gold, from_gold, to_gold),
    )


def _next_transactional_transfer_sequence(conn, campaign_id):
    """Return the next campaign-local transactional transfer sequence (starting at 1)."""
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
        "FROM play_transactional_transfers WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    return row["next_sequence"]


def _record_transactional_transfer(conn, campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold):
    """Record a committed transactional currency transfer in the campaign ledger."""
    conn.execute(
        "INSERT INTO play_transactional_transfers "
        "(campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold),
    )


def _set_play_attunement(conn, campaign_id, character_id, slot, attuned):
    """Set the attuned flag for a character's equipped slot."""
    conn.execute(
        "UPDATE play_character_equipment SET attuned = ? "
        "WHERE campaign_id = ? AND character_id = ? AND slot = ?",
        (1 if attuned else 0, campaign_id, character_id, slot),
    )


def _configure_quest_rewards(conn, campaign_id, quest_id, rewards):
    """Store configured rewards for a play quest."""
    conn.execute(
        "UPDATE play_quests SET rewards_json = ? WHERE campaign_id = ? AND quest_id = ?",
        (json.dumps(rewards), campaign_id, quest_id),
    )


def _is_quest_awarded(conn, campaign_id, quest_id):
    """Return True if the quest rewards have already been awarded."""
    row = conn.execute(
        "SELECT 1 FROM play_quest_awards WHERE campaign_id = ? AND quest_id = ?",
        (campaign_id, quest_id),
    ).fetchone()
    return row is not None


def _record_quest_award(conn, campaign_id, quest_id):
    """Record that a quest's rewards have been awarded."""
    conn.execute(
        "INSERT INTO play_quest_awards (campaign_id, quest_id) VALUES (?, ?)",
        (campaign_id, quest_id),
    )


def _grant_quest_rewards_to_member(conn, campaign_id, character_id, xp, items):
    """Grant quest XP and items to a single campaign member.

    Updates the member's cumulative quest reward totals and adds the items to
    their inventory.
    """
    member = conn.execute(
        "SELECT quest_rewards_xp, quest_rewards_items_json FROM play_campaign_members "
        "WHERE campaign_id = ? AND character_id = ?",
        (campaign_id, character_id),
    ).fetchone()
    if member is None:
        raise ValueError("character not found")

    new_xp = member["quest_rewards_xp"] + xp
    current_items = json.loads(member["quest_rewards_items_json"])
    merged_items = dict(current_items)
    for item_id, quantity in items.items():
        merged_items[item_id] = merged_items.get(item_id, 0) + quantity

    conn.execute(
        "UPDATE play_campaign_members SET quest_rewards_xp = ?, quest_rewards_items_json = ? "
        "WHERE campaign_id = ? AND character_id = ?",
        (new_xp, json.dumps(merged_items), campaign_id, character_id),
    )

    for item_id, quantity in items.items():
        _add_play_inventory_item(conn, campaign_id, character_id, item_id, quantity)

    return new_xp, merged_items


def _get_play_shop(conn, campaign_id, settlement_id, shop_id):
    """Return a shop row or ``None`` if it does not exist."""
    return conn.execute(
        "SELECT shop_id, name, stock_json, buy_price, sell_price FROM play_shops "
        "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
        (campaign_id, settlement_id, shop_id),
    ).fetchone()


def _next_projection_sequence(conn, campaign_id):
    """Return the next projection event sequence for a campaign."""
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM projection_events WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    return row["next_sequence"]


def _append_projection_event(conn, campaign_id, event_id, kind, value):
    """Insert a projection event and return its assigned sequence.

    Raises ``sqlite3.IntegrityError`` for duplicate ``event_id`` values.
    """
    sequence = _next_projection_sequence(conn, campaign_id)
    conn.execute(
        "INSERT INTO projection_events (campaign_id, sequence, event_id, kind, value) VALUES (?, ?, ?, ?, ?)",
        (campaign_id, sequence, event_id, kind, value),
    )
    return sequence


def _get_fixture_seed(conn, campaign_id):
    """Return the seeded fixture row for a campaign, or ``None``."""
    return conn.execute(
        "SELECT fixture_id FROM play_fixture_seeds WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()


def _seed_fixture(conn, campaign_id, fixture_id):
    """Idempotently seed a fixture for a campaign.

    Returns ``True`` if this call created the seed, ``False`` if it already
    existed. Raises ``sqlite3.IntegrityError`` if the campaign does not exist.
    """
    existing = _get_fixture_seed(conn, campaign_id)
    if existing is not None:
        return False
    conn.execute(
        "INSERT INTO play_fixture_seeds (campaign_id, fixture_id) VALUES (?, ?)",
        (campaign_id, fixture_id),
    )
    return True


def _create_play_campaign_backup(conn, campaign_id, story, status):
    """Create a new immutable backup snapshot for a campaign.

    The assigned ``backup_id`` is sequential in the form ``backup-1``,
    ``backup-2``, and so on. The snapshot captures the provided ``story`` and
    ``status`` without modifying the campaign itself.
    """
    row = conn.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(backup_id, 8) AS INTEGER)), 0) + 1 AS next_id "
        "FROM play_campaign_backups WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    backup_id = f"backup-{row['next_id']}"
    conn.execute(
        "INSERT INTO play_campaign_backups (campaign_id, backup_id, story, status) VALUES (?, ?, ?, ?)",
        (campaign_id, backup_id, story, status),
    )
    return backup_id


def _get_play_campaign_backup(conn, campaign_id, backup_id):
    """Return a single backup row, or ``None`` if it does not exist."""
    return conn.execute(
        "SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = ? AND backup_id = ?",
        (campaign_id, backup_id),
    ).fetchone()


def _list_play_campaign_backups(conn, campaign_id):
    """Return all backups for a campaign ordered by creation sequence."""
    rows = conn.execute(
        "SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = ? "
        "ORDER BY CAST(SUBSTR(backup_id, 8) AS INTEGER) ASC",
        (campaign_id,),
    ).fetchall()
    return [{"backup_id": row["backup_id"], "story": row["story"], "status": row["status"]} for row in rows]


def _create_play_campaign_export(conn, campaign_id, story, status):
    """Create a new immutable export version for a campaign.

    The assigned version is one greater than the campaign's previous export
    count. The snapshot captures the provided ``story`` and ``status``.
    """
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM play_campaign_exports WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    version = row["next_version"]
    conn.execute(
        "INSERT INTO play_campaign_exports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)",
        (campaign_id, version, story, status),
    )
    return version


def _get_play_campaign_export(conn, campaign_id, version):
    """Return a single export row, or ``None`` if it does not exist."""
    return conn.execute(
        "SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? AND version = ?",
        (campaign_id, version),
    ).fetchone()


def _list_play_campaign_exports(conn, campaign_id):
    """Return all exports for a campaign ordered by ascending version."""
    rows = conn.execute(
        "SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? ORDER BY version ASC",
        (campaign_id,),
    ).fetchall()
    return [{"version": row["version"], "story": row["story"], "status": row["status"]} for row in rows]


def _apply_play_campaign_import(conn, campaign_id, version, story, status):
    """Atomically record an import snapshot and update the campaign state."""
    conn.execute(
        "INSERT INTO play_campaign_imports (campaign_id, version, story, status) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(campaign_id) DO UPDATE SET "
        "version = excluded.version, story = excluded.story, status = excluded.status",
        (campaign_id, version, story, status),
    )
    conn.execute(
        "UPDATE play_campaigns SET story = ?, status = ? WHERE id = ?",
        (story, status, campaign_id),
    )


def _get_play_campaign_import(conn, campaign_id):
    """Return the current import snapshot for a campaign, or None."""
    return conn.execute(
        "SELECT version, story, status FROM play_campaign_imports WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()


def _apply_play_campaign_migration(conn, campaign_id, story, campaign_name):
    """Record a migrated version-2 snapshot for a campaign.

    The migration is idempotent when the same story is supplied. The stored
    campaign_name is frozen at migration time.
    """
    conn.execute(
        "INSERT INTO play_campaign_migrations (campaign_id, schema_version, story, campaign_name) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(campaign_id) DO UPDATE SET "
        "schema_version = excluded.schema_version, story = excluded.story, campaign_name = excluded.campaign_name",
        (campaign_id, 2, story, campaign_name),
    )


def _get_play_campaign_migration(conn, campaign_id):
    """Return the current migrated snapshot for a campaign, or None."""
    return conn.execute(
        "SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()


def _next_idempotent_sequence(conn, campaign_id):
    """Return the next idempotent event sequence for a campaign."""
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM idempotent_events WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    return row["next_sequence"]


def _get_idempotent_event_by_key(conn, campaign_id, idempotency_key):
    """Return the stored event for an idempotency key, or None."""
    return conn.execute(
        "SELECT event_id, value, sequence FROM idempotent_events "
        "WHERE campaign_id = ? AND idempotency_key = ?",
        (campaign_id, idempotency_key),
    ).fetchone()


def _get_idempotent_event_by_event_id(conn, campaign_id, event_id):
    """Return the stored event for an event_id, or None."""
    return conn.execute(
        "SELECT event_id, value, sequence, idempotency_key FROM idempotent_events "
        "WHERE campaign_id = ? AND event_id = ?",
        (campaign_id, event_id),
    ).fetchone()


def _append_idempotent_event(conn, campaign_id, event_id, value, idempotency_key):
    """Insert an idempotent event and return its assigned sequence."""
    sequence = _next_idempotent_sequence(conn, campaign_id)
    conn.execute(
        "INSERT INTO idempotent_events (campaign_id, sequence, event_id, value, idempotency_key) "
        "VALUES (?, ?, ?, ?, ?)",
        (campaign_id, sequence, event_id, value, idempotency_key),
    )
    return sequence


def _list_idempotent_events(conn, campaign_id):
    """Return all idempotent events for a campaign ordered by sequence."""
    rows = conn.execute(
        "SELECT event_id, value, sequence, idempotency_key FROM idempotent_events "
        "WHERE campaign_id = ? ORDER BY sequence ASC",
        (campaign_id,),
    ).fetchall()
    return [
        {
            "event_id": row["event_id"],
            "value": row["value"],
            "sequence": row["sequence"],
            "idempotency_key": row["idempotency_key"],
        }
        for row in rows
    ]


def _record_rate_event_rejection(conn, campaign_id):
    """Increment the campaign's rejected rate-event counter."""
    conn.execute(
        "INSERT INTO service_metrics (campaign_id, rejected_rate_events) "
        "VALUES (?, 1) "
        "ON CONFLICT(campaign_id) DO UPDATE SET "
        "rejected_rate_events = rejected_rate_events + 1",
        (campaign_id,),
    )


def _count_rejected_rate_events(conn, campaign_id):
    """Return the number of rejected rate events recorded for a campaign."""
    row = conn.execute(
        "SELECT rejected_rate_events FROM service_metrics WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    return row["rejected_rate_events"] if row else 0


def _rebuild_projection(conn, campaign_id):
    """Rebuild the campaign projection solely from ordered projection events."""
    rows = conn.execute(
        "SELECT event_id, kind, value FROM projection_events WHERE campaign_id = ? ORDER BY sequence ASC",
        (campaign_id,),
    ).fetchall()

    story = ""
    danger = 0
    applied_event_ids = []
    for row in rows:
        if row["kind"] == "set-story":
            story = row["value"]
        elif row["kind"] == "increment-danger":
            danger += 1
        applied_event_ids.append(row["event_id"])

    return {
        "story": story,
        "danger": danger,
        "applied_event_ids": applied_event_ids,
    }


def _next_replay_sequence(conn, campaign_id):
    """Return the next replay event sequence for a campaign."""
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM replay_events WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    return row["next_sequence"]


def _append_replay_event(conn, campaign_id, event_id, kind, text):
    """Insert a replay event and return its assigned sequence.

    Raises ``sqlite3.IntegrityError`` for duplicate ``event_id`` values.
    """
    sequence = _next_replay_sequence(conn, campaign_id)
    conn.execute(
        "INSERT INTO replay_events (campaign_id, sequence, event_id, kind, text) VALUES (?, ?, ?, ?, ?)",
        (campaign_id, sequence, event_id, kind, text),
    )
    return sequence


def _get_replay_state(conn, campaign_id):
    """Return deterministic replay state for a campaign.

    The ``story`` is the ordered concatenation of all append event ``text``
    values. ``event_ids`` is the ordered list of successful replay event IDs.
    ``digest`` is ``",".join(event_ids) + "|" + story``.
    """
    rows = conn.execute(
        "SELECT event_id, text FROM replay_events WHERE campaign_id = ? ORDER BY sequence ASC",
        (campaign_id,),
    ).fetchall()

    event_ids = []
    story = ""
    for row in rows:
        event_ids.append(row["event_id"])
        story += row["text"]

    digest = ",".join(event_ids) + "|" + story
    return {
        "story": story,
        "event_ids": event_ids,
        "digest": digest,
    }


def _next_feed_event_sequence(conn, campaign_id):
    """Return the next feed event sequence for a campaign (starts at 1)."""
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM play_campaign_feed_events WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    return row["next_sequence"]


def _get_feed_event_by_event_id(conn, campaign_id, event_id):
    """Return a feed event by its caller-supplied event_id, or None."""
    return conn.execute(
        "SELECT sequence, event_id, text FROM play_campaign_feed_events "
        "WHERE campaign_id = ? AND event_id = ?",
        (campaign_id, event_id),
    ).fetchone()


def _append_feed_event(conn, campaign_id, event_id, text):
    """Append a feed event and return its assigned sequence.

    Raises ``sqlite3.IntegrityError`` for duplicate ``event_id`` values.
    """
    sequence = _next_feed_event_sequence(conn, campaign_id)
    conn.execute(
        "INSERT INTO play_campaign_feed_events (campaign_id, sequence, event_id, text) "
        "VALUES (?, ?, ?, ?)",
        (campaign_id, sequence, event_id, text),
    )
    return sequence


def _list_feed_events(conn, campaign_id, cursor, limit):
    """Return a page of feed events ordered by accepted append sequence."""
    rows = conn.execute(
        "SELECT sequence, event_id, text FROM play_campaign_feed_events "
        "WHERE campaign_id = ? ORDER BY sequence ASC LIMIT ? OFFSET ?",
        (campaign_id, limit, cursor),
    ).fetchall()
    return [
        {"event_id": row["event_id"], "text": row["text"], "sequence": row["sequence"]}
        for row in rows
    ]


def _get_campaign_rng_seed(conn, campaign_id):
    """Return the configured RNG seed for a campaign, or ``None``."""
    row = conn.execute(
        "SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    return row["seed"] if row else None


def _set_campaign_rng_seed(conn, campaign_id, seed):
    """Store the RNG seed for a campaign."""
    conn.execute(
        "INSERT INTO play_campaign_rng_seeds (campaign_id, seed) VALUES (?, ?)",
        (campaign_id, seed),
    )


def _next_rng_roll_sequence(conn, campaign_id):
    """Return the next sequence number for a campaign RNG roll."""
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
        "FROM play_campaign_rng_rolls WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    return row["next_sequence"]


def _append_rng_roll(conn, campaign_id, sequence, roll_id, sides, result):
    """Append an immutable RNG roll record to a campaign ledger."""
    conn.execute(
        "INSERT INTO play_campaign_rng_rolls (campaign_id, sequence, roll_id, sides, result) "
        "VALUES (?, ?, ?, ?, ?)",
        (campaign_id, sequence, roll_id, sides, result),
    )


def _list_rng_rolls(conn, campaign_id):
    """Return ordered RNG roll records for a campaign."""
    rows = conn.execute(
        "SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls "
        "WHERE campaign_id = ? ORDER BY sequence ASC",
        (campaign_id,),
    ).fetchall()
    return [
        {
            "roll_id": row["roll_id"],
            "sides": row["sides"],
            "result": row["result"],
            "sequence": row["sequence"],
        }
        for row in rows
    ]


def _next_moderation_report_sequence(conn, campaign_id):
    """Return the next moderation report sequence for a campaign."""
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM moderation_reports WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    return row["next_sequence"]


def _create_moderation_report(conn, campaign_id, report_id, target_id, reason, reporter):
    """Insert an open moderation report and return its assigned sequence."""
    sequence = _next_moderation_report_sequence(conn, campaign_id)
    conn.execute(
        "INSERT INTO moderation_reports (campaign_id, report_id, target_id, reason, reporter, status, sequence) "
        "VALUES (?, ?, ?, ?, ?, 'open', ?)",
        (campaign_id, report_id, target_id, reason, reporter, sequence),
    )
    return sequence


def _get_moderation_report(conn, campaign_id, report_id):
    """Return a moderation report row, or None if it does not exist."""
    return conn.execute(
        "SELECT campaign_id, report_id, target_id, reason, reporter, status, action, note, resolver, sequence "
        "FROM moderation_reports WHERE campaign_id = ? AND report_id = ?",
        (campaign_id, report_id),
    ).fetchone()


def _list_moderation_reports(conn, campaign_id):
    """Return all moderation reports for a campaign in append order."""
    rows = conn.execute(
        "SELECT report_id, target_id, reason, reporter, status, action, note, resolver, sequence "
        "FROM moderation_reports WHERE campaign_id = ? ORDER BY sequence ASC",
        (campaign_id,),
    ).fetchall()
    return [
        {
            "report_id": row["report_id"],
            "target_id": row["target_id"],
            "reason": row["reason"],
            "reporter": row["reporter"],
            "status": row["status"],
            "action": row["action"],
            "note": row["note"],
            "resolver": row["resolver"],
            "sequence": row["sequence"],
        }
        for row in rows
    ]


def _resolve_moderation_report(conn, campaign_id, report_id, action, note, resolver):
    """Resolve an open moderation report."""
    conn.execute(
        "UPDATE moderation_reports SET status = 'resolved', action = ?, note = ?, resolver = ? "
        "WHERE campaign_id = ? AND report_id = ?",
        (action, note, resolver, campaign_id, report_id),
    )


def _get_safety_boundaries(conn, campaign_id):
    """Return the sorted blocked tags list for a campaign, or None if unset."""
    row = conn.execute(
        "SELECT blocked_tags_json FROM play_campaign_safety_boundaries WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    if row is None:
        return None
    return sorted(json.loads(row["blocked_tags_json"]))


def _set_safety_boundaries(conn, campaign_id, tags):
    """Atomically replace the campaign's safety boundary tags."""
    conn.execute(
        "INSERT INTO play_campaign_safety_boundaries (campaign_id, blocked_tags_json) "
        "VALUES (?, ?) "
        "ON CONFLICT(campaign_id) DO UPDATE SET blocked_tags_json = excluded.blocked_tags_json",
        (campaign_id, json.dumps(tags)),
    )


def _get_safety_event_by_id(conn, campaign_id, event_id):
    """Return a safety event by its caller-supplied event_id, or None."""
    return conn.execute(
        "SELECT sequence, event_id, kind, text, tags_json FROM play_campaign_safety_events "
        "WHERE campaign_id = ? AND event_id = ?",
        (campaign_id, event_id),
    ).fetchone()


def _next_safety_event_sequence(conn, campaign_id):
    """Return the next safety event sequence for a campaign (starts at 1)."""
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM play_campaign_safety_events WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    return row["next_sequence"]


def _append_safety_event(conn, campaign_id, event_id, kind, text, tags):
    """Append an accepted safety check event and return its sequence."""
    sequence = _next_safety_event_sequence(conn, campaign_id)
    conn.execute(
        "INSERT INTO play_campaign_safety_events (campaign_id, sequence, event_id, kind, text, tags_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (campaign_id, sequence, event_id, kind, text, json.dumps(tags)),
    )
    return sequence


def _list_safety_events(conn, campaign_id):
    """Return all accepted safety events for a campaign in append order."""
    rows = conn.execute(
        "SELECT sequence, event_id, kind, text, tags_json FROM play_campaign_safety_events "
        "WHERE campaign_id = ? ORDER BY sequence ASC",
        (campaign_id,),
    ).fetchall()
    return [
        {
            "sequence": row["sequence"],
            "event_id": row["event_id"],
            "kind": row["kind"],
            "text": row["text"],
            "tags": json.loads(row["tags_json"]),
        }
        for row in rows
    ]


def init_db():
    """Reset and recreate the database schema on startup.

    Each benchmark run starts from a clean SQLite database so that
    cumulative tests see a deterministic empty state. The tables are
    dropped and recreated in dependency order.
    """
    global _INITIALIZED
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    reset_db()
