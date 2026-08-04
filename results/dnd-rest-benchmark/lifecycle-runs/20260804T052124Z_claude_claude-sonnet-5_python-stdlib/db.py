"""SQLite persistence layer.

Owns the schema, connection handling, and all CRUD access. Every function
below opens a connection via the `db_conn()` context manager, which closes
it on the way out (SQLite + ThreadingHTTPServer: cheap enough per-request,
and avoids holding connections across threads). Table-creation/reset are
additionally guarded by DB_LOCK so concurrent requests never race on the
schema itself; individual row read/write statements rely on SQLite's own
locking (functions that need both wrap `with DB_LOCK, db_conn() as conn:`).

Rows are handed back as plain dicts (never sqlite3.Row) so callers never
depend on this module's storage engine.
"""
import contextlib
import json
import os
import sqlite3
import threading

SCHEMA_VERSION = 1
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game.db")

DB_LOCK = threading.Lock()
DB_INITIALIZED = False


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextlib.contextmanager
def db_conn():
    """Open a connection for the duration of a `with` block, always closing it.

    Every read/write function in this module uses this instead of managing
    get_conn()/close() by hand; it's the single place that owns "open short-
    lived connection, guarantee close" for all of them.
    """
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


def _count_by_campaign(table, campaign_id):
    """`SELECT COUNT(*) ... WHERE campaign_id = ?` shared by the simple
    per-campaign counters (events, quests, factions, npcs, sessions,
    equipment assignments). `table` is always a literal from this module,
    never request-derived, so building the SQL string is safe.
    """
    with db_conn() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        return row["c"]


def init_db():
    global DB_INITIALIZED
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta ("
            "id INTEGER PRIMARY KEY CHECK (id = 1),"
            "schema_version INTEGER NOT NULL"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "username TEXT PRIMARY KEY,"
            "role TEXT NOT NULL,"
            "salt TEXT NOT NULL,"
            "hash TEXT NOT NULL"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS combat_sessions ("
            "id TEXT PRIMARY KEY,"
            "round INTEGER NOT NULL,"
            "turn_index INTEGER NOT NULL,"
            "order_json TEXT NOT NULL"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS monsters ("
            "slug TEXT PRIMARY KEY,"
            "name TEXT NOT NULL,"
            "cr TEXT NOT NULL,"
            "armor_class INTEGER NOT NULL,"
            "hit_points INTEGER NOT NULL,"
            "tags_json TEXT NOT NULL"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS items ("
            "slug TEXT PRIMARY KEY,"
            "name TEXT NOT NULL,"
            "type TEXT NOT NULL,"
            "rarity TEXT NOT NULL,"
            "cost_gp INTEGER NOT NULL"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS campaigns ("
            "id TEXT PRIMARY KEY,"
            "name TEXT NOT NULL,"
            "dm TEXT NOT NULL"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS campaign_characters ("
            "campaign_id TEXT NOT NULL,"
            "id TEXT NOT NULL,"
            "name TEXT NOT NULL,"
            "level INTEGER NOT NULL,"
            "class TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, id),"
            "FOREIGN KEY (campaign_id) REFERENCES campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS campaign_events ("
            "campaign_id TEXT NOT NULL,"
            "id TEXT NOT NULL,"
            "kind TEXT NOT NULL,"
            "summary TEXT,"
            "PRIMARY KEY (campaign_id, id),"
            "FOREIGN KEY (campaign_id) REFERENCES campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS quests ("
            "campaign_id TEXT NOT NULL,"
            "id TEXT NOT NULL,"
            "title TEXT NOT NULL,"
            "status TEXT NOT NULL,"
            "milestones_json TEXT NOT NULL,"
            "completed_json TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, id),"
            "FOREIGN KEY (campaign_id) REFERENCES campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS factions ("
            "campaign_id TEXT NOT NULL,"
            "id TEXT NOT NULL,"
            "name TEXT NOT NULL,"
            "stance TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, id),"
            "FOREIGN KEY (campaign_id) REFERENCES campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS npcs ("
            "campaign_id TEXT NOT NULL,"
            "id TEXT NOT NULL,"
            "name TEXT NOT NULL,"
            "faction_id TEXT,"
            "disposition INTEGER NOT NULL,"
            "PRIMARY KEY (campaign_id, id),"
            "FOREIGN KEY (campaign_id) REFERENCES campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS inventory_items ("
            "campaign_id TEXT NOT NULL,"
            "item_slug TEXT NOT NULL,"
            "quantity INTEGER NOT NULL,"
            "owner TEXT NOT NULL,"
            "FOREIGN KEY (campaign_id) REFERENCES campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS equipment_assignments ("
            "campaign_id TEXT NOT NULL,"
            "character_id TEXT NOT NULL,"
            "item_slug TEXT NOT NULL,"
            "quantity INTEGER NOT NULL,"
            "FOREIGN KEY (campaign_id) REFERENCES campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS crafting_projects ("
            "campaign_id TEXT NOT NULL,"
            "id TEXT NOT NULL,"
            "character_id TEXT NOT NULL,"
            "item_slug TEXT NOT NULL,"
            "days_required INTEGER NOT NULL,"
            "days_completed INTEGER NOT NULL,"
            "cost_gp INTEGER NOT NULL,"
            "status TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, id),"
            "FOREIGN KEY (campaign_id) REFERENCES campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "campaign_id TEXT NOT NULL,"
            "id TEXT NOT NULL,"
            "starts_at TEXT NOT NULL,"
            "duration_minutes INTEGER NOT NULL,"
            "agenda_json TEXT NOT NULL,"
            "present_json TEXT NOT NULL,"
            "absent_json TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, id),"
            "FOREIGN KEY (campaign_id) REFERENCES campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaigns ("
            "id TEXT PRIMARY KEY,"
            "name TEXT NOT NULL,"
            "owner TEXT NOT NULL,"
            "status TEXT NOT NULL,"
            "max_players INTEGER NOT NULL,"
            "current_actor TEXT,"
            "turn_number INTEGER,"
            "nudge_count INTEGER NOT NULL DEFAULT 0,"
            "story TEXT NOT NULL DEFAULT '',"
            "dm_notes TEXT NOT NULL DEFAULT ''"
            ")"
        )
        for column, coltype in (
            ("current_actor", "TEXT"),
            ("turn_number", "INTEGER"),
            ("nudge_count", "INTEGER NOT NULL DEFAULT 0"),
            ("story", "TEXT NOT NULL DEFAULT ''"),
            ("dm_notes", "TEXT NOT NULL DEFAULT ''"),
            ("current_scene_id", "TEXT"),
            ("current_location_id", "TEXT"),
            ("pre_combat_actor", "TEXT"),
            ("turn_phase", "TEXT"),
        ):
            try:
                conn.execute(
                    "ALTER TABLE play_campaigns ADD COLUMN %s %s" % (column, coltype)
                )
            except sqlite3.OperationalError:
                pass
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_session_zero ("
            "campaign_id TEXT PRIMARY KEY,"
            "rules TEXT NOT NULL,"
            "tone TEXT NOT NULL,"
            "consent_json TEXT NOT NULL,"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_scenes ("
            "campaign_id TEXT NOT NULL,"
            "id TEXT NOT NULL,"
            "name TEXT NOT NULL,"
            "status TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_content ("
            "campaign_id TEXT NOT NULL,"
            "content_id TEXT NOT NULL,"
            "kind TEXT NOT NULL,"
            "text TEXT NOT NULL,"
            "tags_json TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, content_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_members ("
            "campaign_id TEXT NOT NULL,"
            "username TEXT NOT NULL,"
            "character_id TEXT NOT NULL,"
            "name TEXT NOT NULL,"
            "class TEXT NOT NULL,"
            "hp_max INTEGER NOT NULL DEFAULT 20,"
            "hp_current INTEGER NOT NULL DEFAULT 20,"
            "PRIMARY KEY (campaign_id, username),"
            "UNIQUE (campaign_id, character_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        for column, coltype in (
            ("hp_max", "INTEGER NOT NULL DEFAULT 20"),
            ("hp_current", "INTEGER NOT NULL DEFAULT 20"),
            ("status", "TEXT NOT NULL DEFAULT 'alive'"),
            ("death_save_successes", "INTEGER NOT NULL DEFAULT 0"),
            ("death_save_failures", "INTEGER NOT NULL DEFAULT 0"),
            ("owner", "TEXT"),
            ("race", "TEXT"),
            ("background", "TEXT"),
            ("level", "INTEGER NOT NULL DEFAULT 1"),
            ("con_modifier", "INTEGER NOT NULL DEFAULT 0"),
            ("str_modifier", "INTEGER NOT NULL DEFAULT 0"),
            ("dex_modifier", "INTEGER NOT NULL DEFAULT 0"),
            ("int_modifier", "INTEGER NOT NULL DEFAULT 0"),
            ("wis_modifier", "INTEGER NOT NULL DEFAULT 0"),
            ("cha_modifier", "INTEGER NOT NULL DEFAULT 0"),
            ("gold", "INTEGER NOT NULL DEFAULT 10"),
        ):
            try:
                conn.execute(
                    "ALTER TABLE play_campaign_members ADD COLUMN %s %s" % (column, coltype)
                )
            except sqlite3.OperationalError:
                pass
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_narrations ("
            "campaign_id TEXT NOT NULL,"
            "sequence INTEGER NOT NULL,"
            "kind TEXT NOT NULL,"
            "actor TEXT NOT NULL,"
            "type TEXT,"
            "text TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, sequence),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        for column, coltype in (
            ("target", "TEXT"),
        ):
            try:
                conn.execute(
                    "ALTER TABLE play_campaign_narrations ADD COLUMN %s %s" % (column, coltype)
                )
            except sqlite3.OperationalError:
                pass
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_locations ("
            "campaign_id TEXT NOT NULL,"
            "id TEXT NOT NULL,"
            "name TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_location_connections ("
            "campaign_id TEXT NOT NULL,"
            "from_id TEXT NOT NULL,"
            "to_id TEXT NOT NULL,"
            "travel_turns INTEGER NOT NULL,"
            "PRIMARY KEY (campaign_id, from_id, to_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_encounters ("
            "campaign_id TEXT NOT NULL,"
            "id TEXT NOT NULL,"
            "name TEXT NOT NULL,"
            "status TEXT NOT NULL,"
            "combatants_json TEXT NOT NULL,"
            "round INTEGER NOT NULL DEFAULT 1,"
            "turn_index INTEGER NOT NULL DEFAULT 0,"
            "conditions_json TEXT NOT NULL DEFAULT '{}',"
            "PRIMARY KEY (campaign_id, id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        for column, coltype in (
            ("round", "INTEGER NOT NULL DEFAULT 1"),
            ("turn_index", "INTEGER NOT NULL DEFAULT 0"),
            ("conditions_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("rewards_json", "TEXT"),
            ("xp_awarded", "INTEGER NOT NULL DEFAULT 0"),
        ):
            try:
                conn.execute(
                    "ALTER TABLE play_encounters ADD COLUMN %s %s" % (column, coltype)
                )
            except sqlite3.OperationalError:
                pass
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_character_spells ("
            "campaign_id TEXT NOT NULL,"
            "character_id TEXT NOT NULL,"
            "spell_id TEXT NOT NULL,"
            "name TEXT NOT NULL,"
            "level INTEGER NOT NULL,"
            "PRIMARY KEY (campaign_id, character_id, spell_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_character_prepared_spells ("
            "campaign_id TEXT NOT NULL,"
            "character_id TEXT NOT NULL,"
            "spell_id TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, character_id, spell_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_character_casts ("
            "campaign_id TEXT NOT NULL,"
            "character_id TEXT NOT NULL,"
            "spell_id TEXT NOT NULL,"
            "target TEXT NOT NULL,"
            "slot_level INTEGER NOT NULL,"
            "sequence INTEGER NOT NULL,"
            "slots_remaining INTEGER NOT NULL,"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_character_concentration ("
            "campaign_id TEXT NOT NULL,"
            "character_id TEXT NOT NULL,"
            "spell_id TEXT NOT NULL,"
            "target TEXT NOT NULL,"
            "remaining_turns INTEGER NOT NULL,"
            "PRIMARY KEY (campaign_id, character_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_character_inventory_items ("
            "campaign_id TEXT NOT NULL,"
            "character_id TEXT NOT NULL,"
            "item_id TEXT NOT NULL,"
            "quantity INTEGER NOT NULL,"
            "PRIMARY KEY (campaign_id, character_id, item_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_character_equipment ("
            "campaign_id TEXT NOT NULL,"
            "character_id TEXT NOT NULL,"
            "slot TEXT NOT NULL,"
            "item_id TEXT NOT NULL,"
            "attuned INTEGER NOT NULL DEFAULT 0,"
            "PRIMARY KEY (campaign_id, character_id, slot),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_currency_transfers ("
            "campaign_id TEXT NOT NULL,"
            "transfer_id INTEGER NOT NULL,"
            "from_character_id TEXT NOT NULL,"
            "to_character_id TEXT NOT NULL,"
            "gold INTEGER NOT NULL,"
            "PRIMARY KEY (campaign_id, transfer_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers ("
            "campaign_id TEXT NOT NULL,"
            "sequence INTEGER NOT NULL,"
            "from_character_id TEXT NOT NULL,"
            "to_character_id TEXT NOT NULL,"
            "amount INTEGER NOT NULL,"
            "from_gold INTEGER NOT NULL,"
            "to_gold INTEGER NOT NULL,"
            "PRIMARY KEY (campaign_id, sequence),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_exports ("
            "campaign_id TEXT NOT NULL,"
            "version INTEGER NOT NULL,"
            "story TEXT NOT NULL,"
            "status TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, version),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_backups ("
            "campaign_id TEXT NOT NULL,"
            "backup_id TEXT NOT NULL,"
            "sequence INTEGER NOT NULL,"
            "story TEXT NOT NULL,"
            "status TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, backup_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_imports ("
            "campaign_id TEXT PRIMARY KEY,"
            "version INTEGER NOT NULL,"
            "story TEXT NOT NULL,"
            "status TEXT NOT NULL,"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_migrations ("
            "campaign_id TEXT PRIMARY KEY,"
            "source_story TEXT NOT NULL,"
            "schema_version INTEGER NOT NULL,"
            "story TEXT NOT NULL,"
            "campaign_name TEXT NOT NULL,"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_search_records ("
            "campaign_id TEXT NOT NULL,"
            "record_id TEXT NOT NULL,"
            "text TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, record_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_loot ("
            "campaign_id TEXT NOT NULL,"
            "loot_id TEXT NOT NULL,"
            "item_id TEXT NOT NULL,"
            "quantity INTEGER NOT NULL,"
            "status TEXT NOT NULL,"
            "recipient_character_id TEXT,"
            "PRIMARY KEY (campaign_id, loot_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_loot_votes ("
            "campaign_id TEXT NOT NULL,"
            "loot_id TEXT NOT NULL,"
            "voter TEXT NOT NULL,"
            "recipient_character_id TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, loot_id, voter),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_npcs ("
            "campaign_id TEXT NOT NULL,"
            "npc_id TEXT NOT NULL,"
            "name TEXT NOT NULL,"
            "agenda TEXT NOT NULL,"
            "public_status TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, npc_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue ("
            "campaign_id TEXT NOT NULL,"
            "npc_id TEXT NOT NULL,"
            "dialogue_id TEXT NOT NULL,"
            "speaker TEXT NOT NULL,"
            "text TEXT NOT NULL,"
            "visibility TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, npc_id, dialogue_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_factions ("
            "campaign_id TEXT NOT NULL,"
            "faction_id TEXT NOT NULL,"
            "name TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, faction_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_reputation_history ("
            "campaign_id TEXT NOT NULL,"
            "faction_id TEXT NOT NULL,"
            "character_id TEXT NOT NULL,"
            "reputation INTEGER NOT NULL,"
            "delta INTEGER NOT NULL,"
            "reason TEXT NOT NULL"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_relationships ("
            "campaign_id TEXT NOT NULL,"
            "source_id TEXT NOT NULL,"
            "target_id TEXT NOT NULL,"
            "kind TEXT NOT NULL,"
            "score INTEGER NOT NULL,"
            "PRIMARY KEY (campaign_id, source_id, target_id, kind),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_clues ("
            "campaign_id TEXT NOT NULL,"
            "clue_id TEXT NOT NULL,"
            "text TEXT NOT NULL,"
            "audience TEXT NOT NULL,"
            "character_id TEXT,"
            "PRIMARY KEY (campaign_id, clue_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_quests ("
            "campaign_id TEXT NOT NULL,"
            "quest_id TEXT NOT NULL,"
            "title TEXT NOT NULL,"
            "depends_on_json TEXT NOT NULL,"
            "state TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, quest_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_quest_rewards ("
            "campaign_id TEXT NOT NULL,"
            "quest_id TEXT NOT NULL,"
            "xp INTEGER NOT NULL,"
            "items_json TEXT NOT NULL,"
            "awarded INTEGER NOT NULL DEFAULT 0,"
            "PRIMARY KEY (campaign_id, quest_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_character_quest_rewards ("
            "campaign_id TEXT NOT NULL,"
            "character_id TEXT NOT NULL,"
            "xp INTEGER NOT NULL,"
            "items_json TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, character_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_world_events ("
            "campaign_id TEXT NOT NULL,"
            "event_id TEXT NOT NULL,"
            "turn_number INTEGER NOT NULL,"
            "title TEXT NOT NULL,"
            "text TEXT NOT NULL,"
            "status TEXT NOT NULL,"
            "resolution_turn_number INTEGER,"
            "resolution_text TEXT,"
            "PRIMARY KEY (campaign_id, event_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_calendars ("
            "campaign_id TEXT PRIMARY KEY,"
            "day INTEGER NOT NULL,"
            "season TEXT NOT NULL,"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_settlements ("
            "campaign_id TEXT NOT NULL,"
            "settlement_id TEXT NOT NULL,"
            "name TEXT NOT NULL,"
            "services_json TEXT NOT NULL,"
            "availability TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, settlement_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_settlement_discoveries ("
            "campaign_id TEXT NOT NULL,"
            "settlement_id TEXT NOT NULL,"
            "character_id TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, settlement_id, character_id),"
            "FOREIGN KEY (campaign_id, settlement_id) "
            "REFERENCES play_campaign_settlements(campaign_id, settlement_id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_shops ("
            "campaign_id TEXT NOT NULL,"
            "settlement_id TEXT NOT NULL,"
            "shop_id TEXT NOT NULL,"
            "name TEXT NOT NULL,"
            "stock_json TEXT NOT NULL,"
            "buy_price INTEGER NOT NULL,"
            "sell_price INTEGER NOT NULL,"
            "PRIMARY KEY (campaign_id, settlement_id, shop_id),"
            "FOREIGN KEY (campaign_id, settlement_id) "
            "REFERENCES play_campaign_settlements(campaign_id, settlement_id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_recipes ("
            "campaign_id TEXT NOT NULL,"
            "recipe_id TEXT NOT NULL,"
            "name TEXT NOT NULL,"
            "ingredients_json TEXT NOT NULL,"
            "output_item TEXT NOT NULL,"
            "output_quantity INTEGER NOT NULL,"
            "PRIMARY KEY (campaign_id, recipe_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities ("
            "campaign_id TEXT NOT NULL,"
            "activity_id TEXT NOT NULL,"
            "name TEXT NOT NULL,"
            "cycles_required INTEGER NOT NULL,"
            "PRIMARY KEY (campaign_id, activity_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_downtime_allocations ("
            "campaign_id TEXT NOT NULL,"
            "character_id TEXT NOT NULL,"
            "activity_id TEXT NOT NULL,"
            "cycles_completed INTEGER NOT NULL,"
            "completions INTEGER NOT NULL,"
            "PRIMARY KEY (campaign_id, character_id, activity_id),"
            "FOREIGN KEY (campaign_id, activity_id) "
            "REFERENCES play_campaign_downtime_activities(campaign_id, activity_id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_notes ("
            "campaign_id TEXT NOT NULL,"
            "note_id TEXT NOT NULL,"
            "text TEXT NOT NULL,"
            "visibility TEXT NOT NULL,"
            "owner TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, note_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_whispers ("
            "campaign_id TEXT NOT NULL,"
            "whisper_id TEXT NOT NULL,"
            "from_character_id TEXT NOT NULL,"
            "to_character_id TEXT NOT NULL,"
            "text TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, whisper_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_invitations ("
            "campaign_id TEXT NOT NULL,"
            "invitation_id TEXT NOT NULL,"
            "username TEXT NOT NULL,"
            "character_id TEXT NOT NULL,"
            "status TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, invitation_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_delegations ("
            "campaign_id TEXT NOT NULL,"
            "username TEXT NOT NULL,"
            "powers_json TEXT NOT NULL,"
            "active INTEGER NOT NULL,"
            "PRIMARY KEY (campaign_id, username),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit ("
            "campaign_id TEXT NOT NULL,"
            "username TEXT NOT NULL,"
            "action TEXT NOT NULL,"
            "powers_json TEXT NOT NULL,"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_audit_events ("
            "campaign_id TEXT NOT NULL,"
            "kind TEXT NOT NULL,"
            "actor TEXT NOT NULL,"
            "role TEXT NOT NULL,"
            "timestamp INTEGER NOT NULL,"
            "correlation_id TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, correlation_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_projection_events ("
            "campaign_id TEXT NOT NULL,"
            "sequence INTEGER NOT NULL,"
            "event_id TEXT NOT NULL,"
            "kind TEXT NOT NULL,"
            "value TEXT,"
            "PRIMARY KEY (campaign_id, event_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events ("
            "campaign_id TEXT NOT NULL,"
            "sequence INTEGER NOT NULL,"
            "event_id TEXT NOT NULL,"
            "value TEXT NOT NULL,"
            "idempotency_key TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, event_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_state ("
            "campaign_id TEXT PRIMARY KEY,"
            "current_turn INTEGER NOT NULL,"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_safe_turns ("
            "campaign_id TEXT NOT NULL,"
            "sequence INTEGER NOT NULL,"
            "submission_id TEXT NOT NULL,"
            "action TEXT NOT NULL,"
            "accepted_turn INTEGER NOT NULL,"
            "next_turn INTEGER NOT NULL,"
            "PRIMARY KEY (campaign_id, submission_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_rate_events ("
            "campaign_id TEXT NOT NULL,"
            "event_id TEXT NOT NULL,"
            "actor TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, event_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_rate_rejections ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "campaign_id TEXT NOT NULL,"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_replay_events ("
            "campaign_id TEXT NOT NULL,"
            "sequence INTEGER NOT NULL,"
            "event_id TEXT NOT NULL,"
            "kind TEXT NOT NULL,"
            "text TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, event_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_rng_seeds ("
            "campaign_id TEXT PRIMARY KEY,"
            "seed TEXT NOT NULL,"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls ("
            "campaign_id TEXT NOT NULL,"
            "sequence INTEGER NOT NULL,"
            "roll_id TEXT NOT NULL,"
            "sides INTEGER NOT NULL,"
            "result INTEGER NOT NULL,"
            "PRIMARY KEY (campaign_id, roll_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports ("
            "campaign_id TEXT NOT NULL,"
            "sequence INTEGER NOT NULL,"
            "report_id TEXT NOT NULL,"
            "target_id TEXT NOT NULL,"
            "reason TEXT NOT NULL,"
            "status TEXT NOT NULL,"
            "reporter TEXT NOT NULL,"
            "action TEXT,"
            "note TEXT,"
            "resolver TEXT,"
            "PRIMARY KEY (campaign_id, report_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries ("
            "campaign_id TEXT PRIMARY KEY,"
            "blocked_tags TEXT NOT NULL,"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_safety_events ("
            "campaign_id TEXT NOT NULL,"
            "sequence INTEGER NOT NULL,"
            "event_id TEXT NOT NULL,"
            "kind TEXT NOT NULL,"
            "text TEXT NOT NULL,"
            "tags TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, event_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_fixture_seeds ("
            "campaign_id TEXT PRIMARY KEY,"
            "fixture_id TEXT NOT NULL,"
            "state TEXT NOT NULL,"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_spectators ("
            "spectator_id TEXT PRIMARY KEY,"
            "campaign_id TEXT NOT NULL,"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS play_campaign_feed_events ("
            "campaign_id TEXT NOT NULL,"
            "sequence INTEGER NOT NULL,"
            "event_id TEXT NOT NULL,"
            "text TEXT NOT NULL,"
            "PRIMARY KEY (campaign_id, event_id),"
            "FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id)"
            ")"
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_meta (id, schema_version) VALUES (1, ?)",
            (SCHEMA_VERSION,),
        )
        conn.commit()
        DB_INITIALIZED = True


def reset_db():
    """Drop and recreate every table, restoring a fresh schema_meta row."""
    global DB_INITIALIZED
    with DB_LOCK, db_conn() as conn:
        conn.execute("DROP TABLE IF EXISTS combat_sessions")
        conn.execute("DROP TABLE IF EXISTS monsters")
        conn.execute("DROP TABLE IF EXISTS items")
        conn.execute("DROP TABLE IF EXISTS campaign_characters")
        conn.execute("DROP TABLE IF EXISTS campaign_events")
        conn.execute("DROP TABLE IF EXISTS quests")
        conn.execute("DROP TABLE IF EXISTS npcs")
        conn.execute("DROP TABLE IF EXISTS factions")
        conn.execute("DROP TABLE IF EXISTS inventory_items")
        conn.execute("DROP TABLE IF EXISTS equipment_assignments")
        conn.execute("DROP TABLE IF EXISTS crafting_projects")
        conn.execute("DROP TABLE IF EXISTS sessions")
        conn.execute("DROP TABLE IF EXISTS campaigns")
        conn.execute("DROP TABLE IF EXISTS play_campaign_narrations")
        conn.execute("DROP TABLE IF EXISTS play_campaign_members")
        conn.execute("DROP TABLE IF EXISTS play_encounters")
        conn.execute("DROP TABLE IF EXISTS play_location_connections")
        conn.execute("DROP TABLE IF EXISTS play_locations")
        conn.execute("DROP TABLE IF EXISTS play_scenes")
        conn.execute("DROP TABLE IF EXISTS play_campaign_character_spells")
        conn.execute("DROP TABLE IF EXISTS play_campaign_character_prepared_spells")
        conn.execute("DROP TABLE IF EXISTS play_campaign_character_casts")
        conn.execute("DROP TABLE IF EXISTS play_campaign_character_concentration")
        conn.execute("DROP TABLE IF EXISTS play_campaign_character_inventory_items")
        conn.execute("DROP TABLE IF EXISTS play_campaign_character_equipment")
        conn.execute("DROP TABLE IF EXISTS play_campaign_currency_transfers")
        conn.execute("DROP TABLE IF EXISTS play_campaign_loot")
        conn.execute("DROP TABLE IF EXISTS play_campaign_loot_votes")
        conn.execute("DROP TABLE IF EXISTS play_campaign_npcs")
        conn.execute("DROP TABLE IF EXISTS play_campaign_factions")
        conn.execute("DROP TABLE IF EXISTS play_campaign_reputation_history")
        conn.execute("DROP TABLE IF EXISTS play_campaign_relationships")
        conn.execute("DROP TABLE IF EXISTS play_campaign_clues")
        conn.execute("DROP TABLE IF EXISTS play_campaign_quests")
        conn.execute("DROP TABLE IF EXISTS play_campaign_quest_rewards")
        conn.execute("DROP TABLE IF EXISTS play_campaign_character_quest_rewards")
        conn.execute("DROP TABLE IF EXISTS play_campaign_world_events")
        conn.execute("DROP TABLE IF EXISTS play_campaign_calendars")
        conn.execute("DROP TABLE IF EXISTS play_campaign_downtime_allocations")
        conn.execute("DROP TABLE IF EXISTS play_campaign_downtime_activities")
        conn.execute("DROP TABLE IF EXISTS play_campaign_recipes")
        conn.execute("DROP TABLE IF EXISTS play_campaign_notes")
        conn.execute("DROP TABLE IF EXISTS play_campaign_search_records")
        conn.execute("DROP TABLE IF EXISTS play_campaign_whispers")
        conn.execute("DROP TABLE IF EXISTS play_campaign_invitations")
        conn.execute("DROP TABLE IF EXISTS play_campaign_audit_events")
        conn.execute("DROP TABLE IF EXISTS play_campaign_delegation_audit")
        conn.execute("DROP TABLE IF EXISTS play_campaign_delegations")
        conn.execute("DROP TABLE IF EXISTS play_campaign_rate_events")
        conn.execute("DROP TABLE IF EXISTS play_campaign_rate_rejections")
        conn.execute("DROP TABLE IF EXISTS play_campaign_replay_events")
        conn.execute("DROP TABLE IF EXISTS play_campaign_rng_seeds")
        conn.execute("DROP TABLE IF EXISTS play_campaign_rng_rolls")
        conn.execute("DROP TABLE IF EXISTS play_campaign_shops")
        conn.execute("DROP TABLE IF EXISTS play_campaign_settlement_discoveries")
        conn.execute("DROP TABLE IF EXISTS play_campaign_settlements")
        conn.execute("DROP TABLE IF EXISTS play_campaign_moderation_reports")
        conn.execute("DROP TABLE IF EXISTS play_campaign_safety_boundaries")
        conn.execute("DROP TABLE IF EXISTS play_campaign_safety_events")
        conn.execute("DROP TABLE IF EXISTS play_campaign_spectators")
        conn.execute("DROP TABLE IF EXISTS play_campaign_feed_events")
        conn.execute("DROP TABLE IF EXISTS play_campaigns")
        conn.execute("DROP TABLE IF EXISTS schema_meta")
        conn.commit()
        DB_INITIALIZED = False
    init_db()


def is_initialized():
    return DB_INITIALIZED


# -- users --------------------------------------------------------------

def get_user(username):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT username, role, salt, hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            return None
        return {"role": row["role"], "salt": row["salt"], "hash": row["hash"]}


def create_user(username, role, salt, digest_hex):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO users (username, role, salt, hash) VALUES (?, ?, ?, ?)",
            (username, role, salt, digest_hex),
        )
        conn.commit()


# -- combat sessions ------------------------------------------------------

def get_combat_session(session_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, round, turn_index, order_json FROM combat_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "round": row["round"],
            "turn_index": row["turn_index"],
            "order": json.loads(row["order_json"]),
        }


def combat_session_exists(session_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM combat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return row is not None


def save_combat_session(session):
    """Insert or fully overwrite a combat session (order/round/turn_index)."""
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO combat_sessions (id, round, turn_index, order_json) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET round = excluded.round, "
            "turn_index = excluded.turn_index, order_json = excluded.order_json",
            (
                session["id"],
                session["round"],
                session["turn_index"],
                json.dumps(session["order"]),
            ),
        )
        conn.commit()


# -- compendium: monsters / items -----------------------------------------

def get_monster(slug):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters WHERE slug = ?",
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


def create_monster(monster):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                monster["slug"],
                monster["name"],
                monster["cr"],
                monster["armor_class"],
                monster["hit_points"],
                json.dumps(monster["tags"]),
            ),
        )
        conn.commit()


def get_item(slug):
    with db_conn() as conn:
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
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
            (item["slug"], item["name"], item["type"], item["rarity"], item["cost_gp"]),
        )
        conn.commit()


# -- campaigns --------------------------------------------------------------

def get_campaign(campaign_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, name, dm FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "name": row["name"], "dm": row["dm"]}


def create_campaign(campaign):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
            (campaign["id"], campaign["name"], campaign["dm"]),
        )
        conn.commit()


def get_play_campaign(campaign_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, name, owner, status, max_players, current_actor, turn_number, "
            "nudge_count, story, dm_notes, current_scene_id, current_location_id, "
            "pre_combat_actor, turn_phase "
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
            "pre_combat_actor": row["pre_combat_actor"],
            "turn_phase": row["turn_phase"],
        }


def update_play_campaign_document(campaign_id, story, dm_notes):
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "UPDATE play_campaigns SET story = ?, dm_notes = ? WHERE id = ?",
            (story, dm_notes, campaign_id),
        )
        conn.commit()


def get_play_session_zero(campaign_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT rules, tone, consent_json FROM play_session_zero WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "rules": row["rules"],
            "tone": row["tone"],
            "consent": json.loads(row["consent_json"]),
        }


def set_play_session_zero(campaign_id, rules, tone, consent):
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "INSERT INTO play_session_zero (campaign_id, rules, tone, consent_json) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id) DO UPDATE SET "
            "rules = excluded.rules, tone = excluded.tone, "
            "consent_json = excluded.consent_json",
            (campaign_id, rules, tone, json.dumps(consent)),
        )
        conn.commit()


def _content_row_to_dict(row):
    return {
        "content_id": row["content_id"],
        "kind": row["kind"],
        "text": row["text"],
        "tags": json.loads(row["tags_json"]),
    }


def get_play_campaign_content(campaign_id, content_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT content_id, kind, text, tags_json FROM play_campaign_content "
            "WHERE campaign_id = ? AND content_id = ?",
            (campaign_id, content_id),
        ).fetchone()
        if row is None:
            return None
        return _content_row_to_dict(row)


def get_play_campaign_content_list(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT content_id, kind, text, tags_json FROM play_campaign_content "
            "WHERE campaign_id = ? ORDER BY rowid ASC",
            (campaign_id,),
        ).fetchall()
        return [_content_row_to_dict(row) for row in rows]


def create_play_campaign_content(campaign_id, content_id, kind, text, tags):
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?",
            (campaign_id, content_id),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_content "
            "(campaign_id, content_id, kind, text, tags_json) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, content_id, kind, text, json.dumps(tags)),
        )
        conn.commit()
        return True


def update_play_campaign_content_tags(campaign_id, content_id, tags):
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?",
            (campaign_id, content_id),
        ).fetchone()
        if existing is None:
            return None
        conn.execute(
            "UPDATE play_campaign_content SET tags_json = ? "
            "WHERE campaign_id = ? AND content_id = ?",
            (json.dumps(tags), campaign_id, content_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT content_id, kind, text, tags_json FROM play_campaign_content "
            "WHERE campaign_id = ? AND content_id = ?",
            (campaign_id, content_id),
        ).fetchone()
        return _content_row_to_dict(row)


def increment_play_campaign_nudge_count(campaign_id):
    """Atomically bump nudge_count and return the new value."""
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "UPDATE play_campaigns SET nudge_count = nudge_count + 1 WHERE id = ?",
            (campaign_id,),
        )
        row = conn.execute(
            "SELECT nudge_count FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        conn.commit()
        return row["nudge_count"]


def create_play_campaign(campaign):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO play_campaigns (id, name, owner, status, max_players) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                campaign["id"],
                campaign["name"],
                campaign["owner"],
                campaign["status"],
                campaign["max_players"],
            ),
        )
        conn.commit()


def get_play_campaign_member(campaign_id, username):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT campaign_id, username, character_id, name, class "
            "FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if row is None:
            return None
        return {
            "campaign_id": row["campaign_id"],
            "username": row["username"],
            "character_id": row["character_id"],
            "name": row["name"],
            "class": row["class"],
        }


def get_play_campaign_member_count(campaign_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM play_campaign_members WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        return row["n"]


def get_play_campaign_member_by_character(campaign_id, character_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT campaign_id, username, character_id, name, class "
            "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "campaign_id": row["campaign_id"],
            "username": row["username"],
            "character_id": row["character_id"],
            "name": row["name"],
            "class": row["class"],
        }


def get_first_play_campaign_member(campaign_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT username FROM play_campaign_members "
            "WHERE campaign_id = ? ORDER BY rowid ASC LIMIT 1",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        return row["username"]


def get_play_campaign_members_in_join_order(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT username FROM play_campaign_members "
            "WHERE campaign_id = ? ORDER BY rowid ASC",
            (campaign_id,),
        ).fetchall()
        return [row["username"] for row in rows]


def get_play_campaign_members(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT campaign_id, username, character_id, name, class "
            "FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid ASC",
            (campaign_id,),
        ).fetchall()
        return [
            {
                "campaign_id": row["campaign_id"],
                "username": row["username"],
                "character_id": row["character_id"],
                "name": row["name"],
                "class": row["class"],
            }
            for row in rows
        ]


def start_play_campaign(campaign_id, current_actor):
    with db_conn() as conn:
        cur = conn.execute(
            "UPDATE play_campaigns SET status = 'active', current_actor = ?, "
            "turn_number = 1 WHERE id = ? AND status = 'lobby'",
            (current_actor, campaign_id),
        )
        conn.commit()
        return cur.rowcount > 0


def create_play_campaign_member(campaign_id, member):
    with db_conn() as conn:
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
        conn.commit()


def get_play_campaign_character_owner(campaign_id, character_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT character_id, owner FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if row is None:
            return None
        return {"character_id": row["character_id"], "owner": row["owner"]}


def build_play_campaign_character(
    campaign_id, character_id, race, klass, background, level, hp_max, con_modifier=0,
    str_modifier=0, dex_modifier=0, int_modifier=0, wis_modifier=0, cha_modifier=0,
):
    with db_conn() as conn:
        conn.execute(
            "UPDATE play_campaign_members SET race = ?, class = ?, background = ?, "
            "level = ?, hp_max = ?, hp_current = ?, con_modifier = ?, "
            "str_modifier = ?, dex_modifier = ?, int_modifier = ?, wis_modifier = ?, "
            "cha_modifier = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (
                race, klass, background, level, hp_max, hp_max, con_modifier,
                str_modifier, dex_modifier, int_modifier, wis_modifier, cha_modifier,
                campaign_id, character_id,
            ),
        )
        conn.commit()


def get_play_campaign_character_for_level_up(campaign_id, character_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT owner, class, level, hp_max, hp_current, con_modifier "
            "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "owner": row["owner"],
            "class": row["class"],
            "level": row["level"],
            "hp_max": row["hp_max"],
            "hp_current": row["hp_current"],
            "con_modifier": row["con_modifier"],
        }


def get_play_campaign_character_for_skill_check(campaign_id, character_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT owner, level, str_modifier, dex_modifier, con_modifier, "
            "int_modifier, wis_modifier, cha_modifier "
            "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "owner": row["owner"],
            "level": row["level"],
            "str": row["str_modifier"],
            "dex": row["dex_modifier"],
            "con": row["con_modifier"],
            "int": row["int_modifier"],
            "wis": row["wis_modifier"],
            "cha": row["cha_modifier"],
        }


def create_play_campaign_character_spell(campaign_id, character_id, spell_id, name, level):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO play_campaign_character_spells "
            "(campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, character_id, spell_id, name, level),
        )
        conn.commit()


def list_play_campaign_character_spells(campaign_id, character_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT spell_id, name, level FROM play_campaign_character_spells "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY rowid ASC",
            (campaign_id, character_id),
        ).fetchall()
        return [
            {"spell_id": row["spell_id"], "name": row["name"], "level": row["level"]}
            for row in rows
        ]


def get_play_campaign_character_for_prepared_spells(campaign_id, character_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT owner, class, level FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if row is None:
            return None
        return {"owner": row["owner"], "class": row["class"], "level": row["level"]}


def set_play_campaign_character_prepared_spells(campaign_id, character_id, spell_ids):
    with db_conn() as conn:
        conn.execute(
            "DELETE FROM play_campaign_character_prepared_spells "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        )
        conn.executemany(
            "INSERT INTO play_campaign_character_prepared_spells "
            "(campaign_id, character_id, spell_id) VALUES (?, ?, ?)",
            [(campaign_id, character_id, spell_id) for spell_id in spell_ids],
        )
        conn.commit()


def list_play_campaign_character_prepared_spells(campaign_id, character_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT spell_id FROM play_campaign_character_prepared_spells "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY rowid ASC",
            (campaign_id, character_id),
        ).fetchall()
        return [row["spell_id"] for row in rows]


def get_play_campaign_character_for_cast(campaign_id, character_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT owner, class, level FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if row is None:
            return None
        return {"owner": row["owner"], "class": row["class"], "level": row["level"]}


def attempt_play_campaign_character_cast(campaign_id, character_id, spell_id, target, slot_level, max_slots):
    """Atomically check remaining slots and record the cast if any remain.

    Returns (sequence, slots_remaining) on success, or None if the character
    has no remaining slots of `slot_level`.
    """
    with DB_LOCK, db_conn() as conn:
        total_row = conn.execute(
            "SELECT COUNT(*) AS n FROM play_campaign_character_casts "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        sequence = total_row["n"] + 1

        used_row = conn.execute(
            "SELECT COUNT(*) AS n FROM play_campaign_character_casts "
            "WHERE campaign_id = ? AND character_id = ? AND slot_level = ?",
            (campaign_id, character_id, slot_level),
        ).fetchone()
        slots_remaining = max_slots - used_row["n"] - 1
        if slots_remaining < 0:
            return None

        conn.execute(
            "INSERT INTO play_campaign_character_casts "
            "(campaign_id, character_id, spell_id, target, slot_level, sequence, slots_remaining) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, character_id, spell_id, target, slot_level, sequence, slots_remaining),
        )
        conn.commit()
        return sequence, slots_remaining


def list_play_campaign_character_casts(campaign_id, character_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT character_id, spell_id, target, slot_level, sequence, slots_remaining "
            "FROM play_campaign_character_casts "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY sequence ASC",
            (campaign_id, character_id),
        ).fetchall()
        return [
            {
                "character_id": row["character_id"],
                "spell_id": row["spell_id"],
                "target": row["target"],
                "slot_level": row["slot_level"],
                "slots_remaining": row["slots_remaining"],
                "sequence": row["sequence"],
            }
            for row in rows
        ]


def get_play_campaign_character_for_concentration(campaign_id, character_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT owner, class, level FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if row is None:
            return None
        return {"owner": row["owner"], "class": row["class"], "level": row["level"]}


def set_play_campaign_character_concentration(campaign_id, character_id, spell_id, target, remaining_turns):
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "DELETE FROM play_campaign_character_concentration "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        )
        conn.execute(
            "INSERT INTO play_campaign_character_concentration "
            "(campaign_id, character_id, spell_id, target, remaining_turns) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, character_id, spell_id, target, remaining_turns),
        )
        conn.commit()


def get_play_campaign_character_concentration(campaign_id, character_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT spell_id, target, remaining_turns "
            "FROM play_campaign_character_concentration "
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


def clear_play_campaign_character_concentration(campaign_id, character_id):
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "DELETE FROM play_campaign_character_concentration "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        )
        conn.commit()


def advance_play_campaign_character_concentration(campaign_id, character_id):
    """Decrement remaining_turns by one; clear if it reaches zero.

    Returns the concentration dict (possibly None if cleared or absent).
    """
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT spell_id, target, remaining_turns "
            "FROM play_campaign_character_concentration "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if row is None:
            return None

        remaining = row["remaining_turns"] - 1
        if remaining <= 0:
            conn.execute(
                "DELETE FROM play_campaign_character_concentration "
                "WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            )
            conn.commit()
            return None

        conn.execute(
            "UPDATE play_campaign_character_concentration SET remaining_turns = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (remaining, campaign_id, character_id),
        )
        conn.commit()
        return {"spell_id": row["spell_id"], "target": row["target"], "remaining_turns": remaining}


def level_up_play_campaign_character(campaign_id, character_id, level, hp_max, hp_current):
    with db_conn() as conn:
        conn.execute(
            "UPDATE play_campaign_members SET level = ?, hp_max = ?, hp_current = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (level, hp_max, hp_current, campaign_id, character_id),
        )
        conn.commit()


def claim_play_campaign_character(campaign_id, character_id, username):
    """Claim an unowned character, or confirm the requester's existing claim.

    Guarded by DB_LOCK so two concurrent claims of the same unowned
    character can't both observe "unowned" and both succeed.
    """
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT owner FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if row is None:
            return {"error": "not_found"}
        if row["owner"] is not None and row["owner"] != username:
            return {"error": "conflict", "owner": row["owner"]}

        conn.execute(
            "UPDATE play_campaign_members SET owner = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (username, campaign_id, character_id),
        )
        conn.commit()
        return {"owner": username}


def transfer_play_campaign_character(campaign_id, character_id, new_owner):
    with db_conn() as conn:
        conn.execute(
            "UPDATE play_campaign_members SET owner = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (new_owner, campaign_id, character_id),
        )
        conn.commit()


def create_play_campaign_narration(campaign_id, actor, text):
    """Append a narration event, assigning the next sequence for this campaign.

    Guarded by DB_LOCK so concurrent narrations never race on the sequence.
    """
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS m FROM play_campaign_narrations "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = row["m"] + 1
        conn.execute(
            "INSERT INTO play_campaign_narrations "
            "(campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, 'narration', ?, ?)",
            (campaign_id, sequence, actor, text),
        )
        conn.commit()
        return sequence


def get_recent_play_campaign_narrations(campaign_id, limit=10):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT sequence, kind, actor, type, text FROM play_campaign_narrations "
            "WHERE campaign_id = ? ORDER BY sequence DESC LIMIT ?",
            (campaign_id, limit),
        ).fetchall()
        events = []
        for row in rows:
            event = {
                "sequence": row["sequence"],
                "kind": row["kind"],
                "actor": row["actor"],
                "text": row["text"],
            }
            if row["kind"] == "action":
                event["type"] = row["type"]
            events.append(event)
        events.reverse()
        return events


def create_play_campaign_message(campaign_id, actor, text):
    """Append a chat event, assigning the next sequence for this campaign."""
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS m FROM play_campaign_narrations "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = row["m"] + 1
        conn.execute(
            "INSERT INTO play_campaign_narrations "
            "(campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, 'chat', ?, ?)",
            (campaign_id, sequence, actor, text),
        )
        conn.commit()
        return sequence


def create_play_campaign_spectator(campaign_id, spectator_id):
    """Create a globally-unique spectator ticket. Returns False on duplicate."""
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_spectators WHERE spectator_id = ?",
            (spectator_id,),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_spectators (spectator_id, campaign_id) VALUES (?, ?)",
            (spectator_id, campaign_id),
        )
        conn.commit()
        return True


def get_play_campaign_spectator(spectator_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT spectator_id, campaign_id FROM play_campaign_spectators "
            "WHERE spectator_id = ?",
            (spectator_id,),
        ).fetchone()
        if row is None:
            return None
        return {"spectator_id": row["spectator_id"], "campaign_id": row["campaign_id"]}


def create_play_campaign_action(campaign_id, actor, action_type, text):
    """Append an action event, assigning the next sequence for this campaign.

    Guarded by DB_LOCK so concurrent events never race on the sequence.
    """
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS m FROM play_campaign_narrations "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = row["m"] + 1
        conn.execute(
            "INSERT INTO play_campaign_narrations "
            "(campaign_id, sequence, kind, actor, type, text) "
            "VALUES (?, ?, 'action', ?, ?, ?)",
            (campaign_id, sequence, actor, action_type, text),
        )
        conn.execute(
            "UPDATE play_campaigns SET current_actor = owner WHERE id = ?",
            (campaign_id,),
        )
        conn.commit()
        return sequence


def create_play_campaign_encounter_action(campaign_id, actor, action_type, target, text):
    """Append a combat action event, assigning the next sequence for this
    campaign. Does not advance the encounter turn. Guarded by DB_LOCK so
    concurrent events never race on the sequence.
    """
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS m FROM play_campaign_narrations "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = row["m"] + 1
        conn.execute(
            "INSERT INTO play_campaign_narrations "
            "(campaign_id, sequence, kind, actor, type, target, text) "
            "VALUES (?, ?, 'combat_action', ?, ?, ?, ?)",
            (campaign_id, sequence, actor, action_type, target, text),
        )
        conn.commit()
        return sequence


def create_play_campaign_travel(campaign_id, actor, destination_id, next_actor):
    """Append a travel event, moving the party to destination_id and handing
    the turn to next_actor. Guarded by DB_LOCK against sequence races.
    """
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS m FROM play_campaign_narrations "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = row["m"] + 1
        conn.execute(
            "INSERT INTO play_campaign_narrations "
            "(campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, 'travel', ?, ?)",
            (campaign_id, sequence, actor, destination_id),
        )
        conn.execute(
            "UPDATE play_campaigns SET current_actor = ?, current_location_id = ? "
            "WHERE id = ?",
            (next_actor, destination_id, campaign_id),
        )
        conn.commit()
        return sequence


def create_play_campaign_rest(campaign_id, actor, rest_type, next_actor):
    """Append a rest event, restoring HP on a long rest and handing the
    turn to next_actor. Guarded by DB_LOCK against sequence races.
    """
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS m FROM play_campaign_narrations "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = row["m"] + 1
        conn.execute(
            "INSERT INTO play_campaign_narrations "
            "(campaign_id, sequence, kind, actor, type, text) "
            "VALUES (?, ?, 'rest', ?, ?, '')",
            (campaign_id, sequence, actor, rest_type),
        )
        if rest_type == "long":
            conn.execute(
                "UPDATE play_campaign_members SET hp_current = hp_max "
                "WHERE campaign_id = ? AND username = ?",
                (campaign_id, actor),
            )
        conn.execute(
            "UPDATE play_campaigns SET current_actor = ? WHERE id = ?",
            (next_actor, campaign_id),
        )
        conn.commit()
        member_row = conn.execute(
            "SELECT hp_current, hp_max FROM play_campaign_members "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, actor),
        ).fetchone()
        return sequence, member_row["hp_current"], member_row["hp_max"]


def get_last_play_campaign_action_actor(campaign_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT actor FROM play_campaign_narrations "
            "WHERE campaign_id = ? AND kind IN ('action', 'travel', 'rest') "
            "ORDER BY sequence DESC LIMIT 1",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        return row["actor"]


def create_play_campaign_resolution(campaign_id, text, next_actor):
    """Append a resolution event and advance the turn to next_actor.

    Guarded by DB_LOCK so concurrent events never race on the sequence.
    """
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS m FROM play_campaign_narrations "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = row["m"] + 1
        conn.execute(
            "INSERT INTO play_campaign_narrations "
            "(campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, 'resolution', 'dm', ?)",
            (campaign_id, sequence, text),
        )
        conn.execute(
            "UPDATE play_campaigns SET current_actor = ?, "
            "turn_number = turn_number + 1 WHERE id = ?",
            (next_actor, campaign_id),
        )
        conn.commit()
        turn_row = conn.execute(
            "SELECT turn_number FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        return sequence, turn_row["turn_number"]


def get_play_scene(campaign_id, scene_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT campaign_id, id, name, status FROM play_scenes "
            "WHERE campaign_id = ? AND id = ?",
            (campaign_id, scene_id),
        ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "name": row["name"], "status": row["status"]}


def create_play_scene(campaign_id, scene):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO play_scenes (campaign_id, id, name, status) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, scene["id"], scene["name"], scene["status"]),
        )
        conn.commit()


def get_play_encounter(campaign_id, encounter_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, name, status, combatants_json, round, turn_index, conditions_json, "
            "rewards_json, xp_awarded "
            "FROM play_encounters WHERE campaign_id = ? AND id = ?",
            (campaign_id, encounter_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
            "combatants": json.loads(row["combatants_json"]),
            "round": row["round"],
            "turn_index": row["turn_index"],
            "conditions": json.loads(row["conditions_json"]),
            "rewards": json.loads(row["rewards_json"]) if row["rewards_json"] else None,
            "xp_awarded": row["xp_awarded"],
        }


def get_active_play_encounter(campaign_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, name, status, combatants_json, round, turn_index, conditions_json, "
            "rewards_json, xp_awarded "
            "FROM play_encounters WHERE campaign_id = ? AND status = 'active'",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
            "combatants": json.loads(row["combatants_json"]),
            "round": row["round"],
            "turn_index": row["turn_index"],
            "conditions": json.loads(row["conditions_json"]),
            "rewards": json.loads(row["rewards_json"]) if row["rewards_json"] else None,
            "xp_awarded": row["xp_awarded"],
        }


def update_play_encounter_combatants(campaign_id, encounter_id, combatants):
    with db_conn() as conn:
        conn.execute(
            "UPDATE play_encounters SET combatants_json = ? "
            "WHERE campaign_id = ? AND id = ?",
            (json.dumps(combatants), campaign_id, encounter_id),
        )
        conn.commit()


def get_play_campaign_member_hp(campaign_id, username):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT hp_current, hp_max FROM play_campaign_members "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if row is None:
            return None
        return row["hp_current"], row["hp_max"]


def set_play_campaign_member_hp(campaign_id, username, hp_current):
    with db_conn() as conn:
        conn.execute(
            "UPDATE play_campaign_members SET hp_current = ? "
            "WHERE campaign_id = ? AND username = ?",
            (hp_current, campaign_id, username),
        )
        conn.commit()


def get_play_campaign_character_status(campaign_id, character_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT hp_current, hp_max, status FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "hp_current": row["hp_current"],
            "hp_max": row["hp_max"],
            "status": row["status"],
        }


def apply_play_campaign_character_damage(campaign_id, character_id, amount):
    """Reduce a character's HP, transitioning alive -> unconscious at 0 HP.

    Reaching 0 HP resets death save counters so a fresh round of saves
    starts clean the next time the character goes down.
    """
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT hp_current, hp_max, status FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if row is None:
            return None
        hp_before = row["hp_current"]
        hp_after = max(0, hp_before - amount)
        status = row["status"]
        if hp_after == 0 and status == "alive":
            status = "unconscious"
            conn.execute(
                "UPDATE play_campaign_members SET hp_current = ?, status = ?, "
                "death_save_successes = 0, death_save_failures = 0 "
                "WHERE campaign_id = ? AND character_id = ?",
                (hp_after, status, campaign_id, character_id),
            )
        else:
            conn.execute(
                "UPDATE play_campaign_members SET hp_current = ? "
                "WHERE campaign_id = ? AND character_id = ?",
                (hp_after, campaign_id, character_id),
            )
        conn.commit()
        return {
            "hp_before": hp_before,
            "hp_after": hp_after,
            "hp_max": row["hp_max"],
            "status": status,
        }


def record_play_campaign_death_save(campaign_id, character_id, outcome):
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT status, death_save_successes, death_save_failures "
            "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if row is None:
            return None
        if row["status"] != "unconscious":
            return {"error": "not_unconscious", "status": row["status"]}

        successes = row["death_save_successes"]
        failures = row["death_save_failures"]
        if outcome == "success":
            successes += 1
        else:
            failures += 1

        status = "unconscious"
        if successes >= 3:
            status = "stable"
        elif failures >= 3:
            status = "dead"

        conn.execute(
            "UPDATE play_campaign_members SET death_save_successes = ?, "
            "death_save_failures = ?, status = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (successes, failures, status, campaign_id, character_id),
        )
        conn.commit()
        return {"successes": successes, "failures": failures, "status": status}


def update_play_encounter_turn(campaign_id, encounter_id, round_number, turn_index):
    with db_conn() as conn:
        conn.execute(
            "UPDATE play_encounters SET round = ?, turn_index = ? "
            "WHERE campaign_id = ? AND id = ?",
            (round_number, turn_index, campaign_id, encounter_id),
        )
        conn.commit()


def update_play_encounter_turn_and_conditions(
    campaign_id, encounter_id, round_number, turn_index, conditions
):
    with db_conn() as conn:
        conn.execute(
            "UPDATE play_encounters SET round = ?, turn_index = ?, conditions_json = ? "
            "WHERE campaign_id = ? AND id = ?",
            (round_number, turn_index, json.dumps(conditions), campaign_id, encounter_id),
        )
        conn.commit()


def update_play_encounter_conditions(campaign_id, encounter_id, conditions):
    with db_conn() as conn:
        conn.execute(
            "UPDATE play_encounters SET conditions_json = ? "
            "WHERE campaign_id = ? AND id = ?",
            (json.dumps(conditions), campaign_id, encounter_id),
        )
        conn.commit()


def award_play_encounter_rewards(campaign_id, encounter_id, rewards):
    with db_conn() as conn:
        conn.execute(
            "UPDATE play_encounters SET rewards_json = ?, xp_awarded = ? "
            "WHERE campaign_id = ? AND id = ?",
            (json.dumps(rewards), rewards["xp"], campaign_id, encounter_id),
        )
        conn.commit()


def close_play_encounter(campaign_id, encounter_id):
    with db_conn() as conn:
        conn.execute(
            "UPDATE play_encounters SET status = 'closed' "
            "WHERE campaign_id = ? AND id = ?",
            (campaign_id, encounter_id),
        )
        conn.commit()


def create_play_encounter(campaign_id, encounter):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO play_encounters "
            "(campaign_id, id, name, status, combatants_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                campaign_id,
                encounter["id"],
                encounter["name"],
                encounter["status"],
                json.dumps(encounter["combatants"]),
            ),
        )
        conn.execute(
            "UPDATE play_campaigns SET pre_combat_actor = current_actor WHERE id = ?",
            (campaign_id,),
        )
        conn.commit()


def end_play_encounter(campaign_id, encounter_id):
    """Close the encounter if still active and hand control back to the DM,
    who narrates the aftermath before exploration continues.
    """
    with db_conn() as conn:
        conn.execute(
            "UPDATE play_encounters SET status = 'closed' "
            "WHERE campaign_id = ? AND id = ? AND status = 'active'",
            (campaign_id, encounter_id),
        )
        row = conn.execute(
            "SELECT owner FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        restored_actor = row["owner"] if row is not None else None
        if restored_actor is not None:
            conn.execute(
                "UPDATE play_campaigns SET current_actor = ?, pre_combat_actor = NULL, "
                "turn_phase = 'exploration' WHERE id = ?",
                (restored_actor, campaign_id),
            )
        conn.commit()
        return restored_actor


def close_play_scene(campaign_id, scene_id):
    """Mark a scene closed and append a scene_close event to the shared
    campaign event sequence.
    """
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "UPDATE play_scenes SET status = 'closed' "
            "WHERE campaign_id = ? AND id = ?",
            (campaign_id, scene_id),
        )
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS m FROM play_campaign_narrations "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = row["m"] + 1
        conn.execute(
            "INSERT INTO play_campaign_narrations "
            "(campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, 'scene_close', 'dm', ?)",
            (campaign_id, sequence, scene_id),
        )
        conn.commit()


def set_play_campaign_current_scene(campaign_id, scene_id):
    """Set the campaign's current scene and append a scene_enter event to
    the shared campaign event sequence.
    """
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?",
            (scene_id, campaign_id),
        )
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS m FROM play_campaign_narrations "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = row["m"] + 1
        conn.execute(
            "INSERT INTO play_campaign_narrations "
            "(campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, 'scene_enter', 'dm', ?)",
            (campaign_id, sequence, scene_id),
        )
        conn.commit()


def get_play_location(campaign_id, location_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT campaign_id, id, name FROM play_locations "
            "WHERE campaign_id = ? AND id = ?",
            (campaign_id, location_id),
        ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "name": row["name"]}


def create_play_location(campaign_id, location):
    """Insert a location; the first location created becomes the party's
    starting current location.
    """
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "INSERT INTO play_locations (campaign_id, id, name) VALUES (?, ?, ?)",
            (campaign_id, location["id"], location["name"]),
        )
        conn.execute(
            "UPDATE play_campaigns SET current_location_id = ? "
            "WHERE id = ? AND current_location_id IS NULL",
            (location["id"], campaign_id),
        )
        conn.commit()


def get_play_location_connection(campaign_id, from_id, to_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT from_id, to_id, travel_turns FROM play_location_connections "
            "WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
            (campaign_id, from_id, to_id),
        ).fetchone()
        if row is None:
            return None
        return {"from_id": row["from_id"], "to_id": row["to_id"], "travel_turns": row["travel_turns"]}


def create_play_location_connection(campaign_id, connection):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO play_location_connections (campaign_id, from_id, to_id, travel_turns) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, connection["from_id"], connection["to_id"], connection["travel_turns"]),
        )
        conn.commit()


def get_play_location_destinations(campaign_id, from_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT c.to_id AS to_id, l.name AS name, c.travel_turns AS travel_turns "
            "FROM play_location_connections c "
            "JOIN play_locations l ON l.campaign_id = c.campaign_id AND l.id = c.to_id "
            "WHERE c.campaign_id = ? AND c.from_id = ? "
            "ORDER BY c.to_id",
            (campaign_id, from_id),
        ).fetchall()
        return [
            {"id": row["to_id"], "name": row["name"], "travel_turns": row["travel_turns"]}
            for row in rows
        ]


def get_campaign_character(campaign_id, char_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, name, level, class FROM campaign_characters "
            "WHERE campaign_id = ? AND id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "level": row["level"],
            "class": row["class"],
        }


def create_campaign_character(campaign_id, character):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO campaign_characters (campaign_id, id, name, level, class) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                campaign_id,
                character["id"],
                character["name"],
                character["level"],
                character["class"],
            ),
        )
        conn.commit()


def list_campaign_characters(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, level, class FROM campaign_characters "
            "WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
        return [
            {"id": r["id"], "name": r["name"], "level": r["level"], "class": r["class"]}
            for r in rows
        ]


def get_campaign_event(campaign_id, event_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id FROM campaign_events WHERE campaign_id = ? AND id = ?",
            (campaign_id, event_id),
        ).fetchone()
        return row is not None


def create_campaign_event(campaign_id, event):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO campaign_events (campaign_id, id, kind, summary) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, event["id"], event["kind"], event.get("summary")),
        )
        conn.commit()


def count_campaign_events(campaign_id):
    return _count_by_campaign("campaign_events", campaign_id)


def latest_campaign_event(campaign_id):
    """Most recently inserted event for a campaign, or None if it has none."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, kind, summary FROM campaign_events "
            "WHERE campaign_id = ? ORDER BY rowid DESC LIMIT 1",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "kind": row["kind"], "summary": row["summary"]}


# -- campaign quests ----------------------------------------------------------

def _quest_from_row(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "milestones": json.loads(row["milestones_json"]),
        "completed": json.loads(row["completed_json"]),
    }


def get_quest(campaign_id, quest_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, title, status, milestones_json, completed_json "
            "FROM quests WHERE campaign_id = ? AND id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if row is None:
            return None
        return _quest_from_row(row)


def create_quest(campaign_id, quest):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO quests (campaign_id, id, title, status, milestones_json, completed_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                campaign_id,
                quest["id"],
                quest["title"],
                quest["status"],
                json.dumps(quest["milestones"]),
                json.dumps(quest["completed"]),
            ),
        )
        conn.commit()


def save_quest_progress(campaign_id, quest_id, completed, status):
    with db_conn() as conn:
        conn.execute(
            "UPDATE quests SET completed_json = ?, status = ? "
            "WHERE campaign_id = ? AND id = ?",
            (json.dumps(completed), status, campaign_id, quest_id),
        )
        conn.commit()


def count_campaign_quests(campaign_id):
    return _count_by_campaign("quests", campaign_id)


def count_campaign_quests_by_status(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS c FROM quests WHERE campaign_id = ? GROUP BY status",
            (campaign_id,),
        ).fetchall()
        return {row["status"]: row["c"] for row in rows}


# -- campaign factions --------------------------------------------------

def get_faction(campaign_id, faction_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, name, stance FROM factions WHERE campaign_id = ? AND id = ?",
            (campaign_id, faction_id),
        ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "name": row["name"], "stance": row["stance"]}


def create_faction(campaign_id, faction):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO factions (campaign_id, id, name, stance) VALUES (?, ?, ?, ?)",
            (campaign_id, faction["id"], faction["name"], faction["stance"]),
        )
        conn.commit()


def count_campaign_factions(campaign_id):
    return _count_by_campaign("factions", campaign_id)


# -- campaign npcs --------------------------------------------------------

def get_npc(campaign_id, npc_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, name, faction_id, disposition FROM npcs "
            "WHERE campaign_id = ? AND id = ?",
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


def create_npc(campaign_id, npc):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO npcs (campaign_id, id, name, faction_id, disposition) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                campaign_id,
                npc["id"],
                npc["name"],
                npc["faction_id"],
                npc["disposition"],
            ),
        )
        conn.commit()


def count_campaign_npcs(campaign_id):
    return _count_by_campaign("npcs", campaign_id)


def count_campaign_friendly_npcs(campaign_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM npcs WHERE campaign_id = ? AND disposition > 0",
            (campaign_id,),
        ).fetchone()
        return row["c"]


# -- campaign inventory / equipment ----------------------------------------

def create_inventory_item(campaign_id, item_slug, quantity, owner):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO inventory_items (campaign_id, item_slug, quantity, owner) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, item_slug, quantity, owner),
        )
        conn.commit()


def count_campaign_inventory_items(campaign_id, owner):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM inventory_items WHERE campaign_id = ? AND owner = ?",
            (campaign_id, owner),
        ).fetchone()
        return row["c"]


def count_campaign_inventory_items_total(campaign_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(DISTINCT item_slug) AS c FROM inventory_items WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        return row["c"]


def sum_campaign_inventory_quantity(campaign_id, item_slug, owner):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS q FROM inventory_items "
            "WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
            (campaign_id, item_slug, owner),
        ).fetchone()
        return row["q"]


def create_equipment_assignment(campaign_id, character_id, item_slug, quantity):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO equipment_assignments (campaign_id, character_id, item_slug, quantity) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, character_id, item_slug, quantity),
        )
        conn.commit()


def count_campaign_equipment_assignments(campaign_id):
    return _count_by_campaign("equipment_assignments", campaign_id)


def sum_campaign_equipment_quantity(campaign_id, item_slug):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS q FROM equipment_assignments "
            "WHERE campaign_id = ? AND item_slug = ?",
            (campaign_id, item_slug),
        ).fetchone()
        return row["q"]


# -- downtime crafting ------------------------------------------------------

def _crafting_project_from_row(row):
    return {
        "id": row["id"],
        "character_id": row["character_id"],
        "item_slug": row["item_slug"],
        "days_required": row["days_required"],
        "days_completed": row["days_completed"],
        "cost_gp": row["cost_gp"],
        "status": row["status"],
    }


def get_crafting_project(campaign_id, project_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, character_id, item_slug, days_required, days_completed, cost_gp, status "
            "FROM crafting_projects WHERE campaign_id = ? AND id = ?",
            (campaign_id, project_id),
        ).fetchone()
        if row is None:
            return None
        return _crafting_project_from_row(row)


def create_crafting_project(campaign_id, project):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO crafting_projects "
            "(campaign_id, id, character_id, item_slug, days_required, days_completed, cost_gp, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
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
        conn.commit()


def save_crafting_progress(campaign_id, project_id, days_completed, status):
    with db_conn() as conn:
        conn.execute(
            "UPDATE crafting_projects SET days_completed = ?, status = ? "
            "WHERE campaign_id = ? AND id = ?",
            (days_completed, status, campaign_id, project_id),
        )
        conn.commit()


# -- campaign sessions --------------------------------------------------

def _session_from_row(row):
    return {
        "id": row["id"],
        "starts_at": row["starts_at"],
        "duration_minutes": row["duration_minutes"],
        "agenda": json.loads(row["agenda_json"]),
        "present": json.loads(row["present_json"]),
        "absent": json.loads(row["absent_json"]),
    }


def get_session(campaign_id, session_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, starts_at, duration_minutes, agenda_json, present_json, absent_json "
            "FROM sessions WHERE campaign_id = ? AND id = ?",
            (campaign_id, session_id),
        ).fetchone()
        if row is None:
            return None
        return _session_from_row(row)


def create_session(campaign_id, session):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO sessions "
            "(campaign_id, id, starts_at, duration_minutes, agenda_json, present_json, absent_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                campaign_id,
                session["id"],
                session["starts_at"],
                session["duration_minutes"],
                json.dumps(session["agenda"]),
                json.dumps(session["present"]),
                json.dumps(session["absent"]),
            ),
        )
        conn.commit()


def save_session_attendance(campaign_id, session_id, present, absent):
    with db_conn() as conn:
        conn.execute(
            "UPDATE sessions SET present_json = ?, absent_json = ? "
            "WHERE campaign_id = ? AND id = ?",
            (json.dumps(present), json.dumps(absent), campaign_id, session_id),
        )
        conn.commit()


def count_campaign_sessions(campaign_id):
    return _count_by_campaign("sessions", campaign_id)


def get_next_session(campaign_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, starts_at, duration_minutes, agenda_json, present_json, absent_json "
            "FROM sessions WHERE campaign_id = ? ORDER BY starts_at ASC, id ASC LIMIT 1",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        return _session_from_row(row)


# -- play campaign character inventory stacks -------------------------------


def add_play_campaign_character_inventory_item(campaign_id, character_id, item_id, quantity):
    """Increment a character's item stack, creating it if needed. Returns the new total."""
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()
        if row is None:
            total = quantity
            conn.execute(
                "INSERT INTO play_campaign_character_inventory_items "
                "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)",
                (campaign_id, character_id, item_id, total),
            )
        else:
            total = row["quantity"] + quantity
            conn.execute(
                "UPDATE play_campaign_character_inventory_items SET quantity = ? "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (total, campaign_id, character_id, item_id),
            )
        conn.commit()
        return total


def list_play_campaign_character_inventory_items(campaign_id, character_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT item_id, quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND quantity > 0 ORDER BY item_id ASC",
            (campaign_id, character_id),
        ).fetchall()
        return [{"item_id": row["item_id"], "quantity": row["quantity"]} for row in rows]


def remove_play_campaign_character_inventory_item(campaign_id, character_id, item_id, quantity):
    """Decrement a character's item stack.

    Returns the new total, or None if the held quantity (zero if no stack
    exists) is smaller than the requested removal.
    """
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()
        held = row["quantity"] if row is not None else 0
        if quantity > held:
            return None
        total = held - quantity
        conn.execute(
            "UPDATE play_campaign_character_inventory_items SET quantity = ? "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (total, campaign_id, character_id, item_id),
        )
        conn.commit()
        return total


# -- play campaign character equipment / attunement --------------------------


def get_play_campaign_character_inventory_item_quantity(campaign_id, character_id, item_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()
        return row["quantity"] if row is not None else 0


def get_play_campaign_character_equipment_slot(campaign_id, character_id, slot):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT item_id, attuned FROM play_campaign_character_equipment "
            "WHERE campaign_id = ? AND character_id = ? AND slot = ?",
            (campaign_id, character_id, slot),
        ).fetchone()
        if row is None:
            return None
        return {"item_id": row["item_id"], "attuned": bool(row["attuned"])}


def set_play_campaign_character_equipment_slot(campaign_id, character_id, slot, item_id):
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "INSERT INTO play_campaign_character_equipment "
            "(campaign_id, character_id, slot, item_id, attuned) VALUES (?, ?, ?, ?, 0) "
            "ON CONFLICT (campaign_id, character_id, slot) "
            "DO UPDATE SET item_id = excluded.item_id, attuned = 0",
            (campaign_id, character_id, slot, item_id),
        )
        conn.commit()


def count_play_campaign_character_attunements(campaign_id, character_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM play_campaign_character_equipment "
            "WHERE campaign_id = ? AND character_id = ? AND attuned = 1",
            (campaign_id, character_id),
        ).fetchone()
        return row["c"]


def attune_play_campaign_character_equipment_slot(campaign_id, character_id, slot):
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "UPDATE play_campaign_character_equipment SET attuned = 1 "
            "WHERE campaign_id = ? AND character_id = ? AND slot = ?",
            (campaign_id, character_id, slot),
        )
        conn.commit()


# -- play campaign character currency -----------------------------------


def get_play_campaign_character_gold(campaign_id, character_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        return row["gold"] if row is not None else None


def create_play_campaign_transactional_transfer(
    campaign_id, from_character_id, to_character_id, amount, simulate_failure
):
    """Atomically debit/credit and append a success record, or leave state
    untouched if the source has insufficient gold or `simulate_failure` is
    True. Returns (sequence, from_gold, to_gold) on success, "insufficient"
    on insufficient balance, or "simulated_failure" when simulated.
    """
    with DB_LOCK, db_conn() as conn:
        from_row = conn.execute(
            "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, from_character_id),
        ).fetchone()
        to_row = conn.execute(
            "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, to_character_id),
        ).fetchone()
        if from_row is None or to_row is None or from_row["gold"] < amount:
            return "insufficient"

        if simulate_failure:
            return "simulated_failure"

        from_gold = from_row["gold"] - amount
        to_gold = to_row["gold"] + amount
        conn.execute(
            "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?",
            (from_gold, campaign_id, from_character_id),
        )
        conn.execute(
            "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?",
            (to_gold, campaign_id, to_character_id),
        )
        sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq "
            "FROM play_campaign_transactional_transfers WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["next_seq"]
        conn.execute(
            "INSERT INTO play_campaign_transactional_transfers "
            "(campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold),
        )
        conn.commit()
        return (sequence, from_gold, to_gold)


def get_play_campaign_transactional_transfers(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT sequence, from_character_id, to_character_id, amount, from_gold, to_gold "
            "FROM play_campaign_transactional_transfers WHERE campaign_id = ? "
            "ORDER BY sequence ASC",
            (campaign_id,),
        ).fetchall()
        return [
            {
                "from_character_id": row["from_character_id"],
                "to_character_id": row["to_character_id"],
                "amount": row["amount"],
                "from_gold": row["from_gold"],
                "to_gold": row["to_gold"],
                "sequence": row["sequence"],
            }
            for row in rows
        ]


def create_play_campaign_export(campaign_id):
    with DB_LOCK, db_conn() as conn:
        campaign = conn.execute(
            "SELECT story, status FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS next_version "
            "FROM play_campaign_exports WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["next_version"]
        story = campaign["story"] or ""
        status = campaign["status"]
        conn.execute(
            "INSERT INTO play_campaign_exports (campaign_id, version, story, status) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, version, story, status),
        )
        conn.commit()
        return {"version": version, "story": story, "status": status}


def get_play_campaign_exports(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT version, story, status FROM play_campaign_exports "
            "WHERE campaign_id = ? ORDER BY version ASC",
            (campaign_id,),
        ).fetchall()
        return [
            {"version": row["version"], "story": row["story"], "status": row["status"]}
            for row in rows
        ]


def get_play_campaign_export(campaign_id, version):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT version, story, status FROM play_campaign_exports "
            "WHERE campaign_id = ? AND version = ?",
            (campaign_id, version),
        ).fetchone()
        if row is None:
            return None
        return {"version": row["version"], "story": row["story"], "status": row["status"]}


def create_play_campaign_backup(campaign_id):
    with DB_LOCK, db_conn() as conn:
        campaign = conn.execute(
            "SELECT story, status FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
            "FROM play_campaign_backups WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["next_sequence"]
        backup_id = f"backup-{sequence}"
        story = campaign["story"] or ""
        status = campaign["status"]
        conn.execute(
            "INSERT INTO play_campaign_backups "
            "(campaign_id, backup_id, sequence, story, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, backup_id, sequence, story, status),
        )
        conn.commit()
        return {"backup_id": backup_id, "story": story, "status": status}


def get_play_campaign_backups(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT backup_id, story, status FROM play_campaign_backups "
            "WHERE campaign_id = ? ORDER BY sequence ASC",
            (campaign_id,),
        ).fetchall()
        return [
            {"backup_id": row["backup_id"], "story": row["story"], "status": row["status"]}
            for row in rows
        ]


def get_play_campaign_backup(campaign_id, backup_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT backup_id, story, status FROM play_campaign_backups "
            "WHERE campaign_id = ? AND backup_id = ?",
            (campaign_id, backup_id),
        ).fetchone()
        if row is None:
            return None
        return {"backup_id": row["backup_id"], "story": row["story"], "status": row["status"]}


def restore_play_campaign_backup(campaign_id, backup_id):
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT backup_id, story, status FROM play_campaign_backups "
            "WHERE campaign_id = ? AND backup_id = ?",
            (campaign_id, backup_id),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE play_campaigns SET story = ?, status = ? WHERE id = ?",
            (row["story"], row["status"], campaign_id),
        )
        conn.commit()
        return {"backup_id": row["backup_id"], "story": row["story"], "status": row["status"]}


def import_play_campaign_snapshot(campaign_id, version, story, status):
    """Apply an imported snapshot to `campaign_id`'s story/status atomically.

    Also records the imported snapshot so it can be read back verbatim via
    `get_play_campaign_import_state`.
    """
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "UPDATE play_campaigns SET story = ?, status = ? WHERE id = ?",
            (story, status, campaign_id),
        )
        conn.execute(
            "INSERT INTO play_campaign_imports (campaign_id, version, story, status) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id) DO UPDATE SET "
            "version = excluded.version, story = excluded.story, status = excluded.status",
            (campaign_id, version, story, status),
        )
        conn.commit()
        return {"version": version, "story": story, "status": status}


def get_play_campaign_import_state(campaign_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT version, story, status FROM play_campaign_imports WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        return {"version": row["version"], "story": row["story"], "status": row["status"]}


def migrate_play_campaign_snapshot(campaign_id, source_story, campaign_name):
    """Deterministically migrate a legacy schema v1 story snapshot to v2.

    Repeating the same source snapshot is idempotent: it returns the
    existing migrated state unchanged (created=False) instead of writing a
    new one. A different source snapshot overwrites the migrated state.
    """
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT source_story, schema_version, story, campaign_name "
            "FROM play_campaign_migrations WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if existing is not None and existing["source_story"] == source_story:
            return (
                {
                    "schema_version": existing["schema_version"],
                    "story": existing["story"],
                    "campaign_name": existing["campaign_name"],
                },
                False,
            )

        conn.execute(
            "INSERT INTO play_campaign_migrations "
            "(campaign_id, source_story, schema_version, story, campaign_name) "
            "VALUES (?, ?, 2, ?, ?) "
            "ON CONFLICT(campaign_id) DO UPDATE SET "
            "source_story = excluded.source_story, schema_version = excluded.schema_version, "
            "story = excluded.story, campaign_name = excluded.campaign_name",
            (campaign_id, source_story, source_story, campaign_name),
        )
        conn.commit()
        return ({"schema_version": 2, "story": source_story, "campaign_name": campaign_name}, True)


def get_play_campaign_migration_state(campaign_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT schema_version, story, campaign_name FROM play_campaign_migrations "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "schema_version": row["schema_version"],
            "story": row["story"],
            "campaign_name": row["campaign_name"],
        }


def transfer_play_campaign_character_gold(campaign_id, from_character_id, to_character_id, gold):
    """Atomically debit `from_character_id` and credit `to_character_id`.

    Returns (transfer_id, from_gold, to_gold) on success, or None if the
    source character doesn't have enough gold (leaving both balances
    unchanged).
    """
    with DB_LOCK, db_conn() as conn:
        from_row = conn.execute(
            "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, from_character_id),
        ).fetchone()
        to_row = conn.execute(
            "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, to_character_id),
        ).fetchone()
        if from_row is None or to_row is None or from_row["gold"] < gold:
            return None

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
        conn.commit()
        transfer_id = conn.execute(
            "SELECT COALESCE(MAX(transfer_id), 0) + 1 AS next_id "
            "FROM play_campaign_currency_transfers WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["next_id"]
        conn.execute(
            "INSERT INTO play_campaign_currency_transfers "
            "(campaign_id, transfer_id, from_character_id, to_character_id, gold) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, transfer_id, from_character_id, to_character_id, gold),
        )
        conn.commit()
        return (transfer_id, from_gold, to_gold)


# -- play campaign loot ---------------------------------------------------


def get_play_campaign_loot(campaign_id, loot_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT loot_id, item_id, quantity, status, recipient_character_id "
            "FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?",
            (campaign_id, loot_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "loot_id": row["loot_id"],
            "item_id": row["item_id"],
            "quantity": row["quantity"],
            "status": row["status"],
            "recipient_character_id": row["recipient_character_id"],
        }


def create_play_campaign_loot(campaign_id, loot_id, item_id, quantity):
    """Insert an open loot record. Returns False if loot_id already exists in the campaign."""
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?",
            (campaign_id, loot_id),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_loot "
            "(campaign_id, loot_id, item_id, quantity, status, recipient_character_id) "
            "VALUES (?, ?, ?, ?, 'open', NULL)",
            (campaign_id, loot_id, item_id, quantity),
        )
        conn.commit()
        return True


def get_play_campaign_loot_votes_tally(campaign_id, loot_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT recipient_character_id, COUNT(*) AS c FROM play_campaign_loot_votes "
            "WHERE campaign_id = ? AND loot_id = ? "
            "GROUP BY recipient_character_id",
            (campaign_id, loot_id),
        ).fetchall()
        return {row["recipient_character_id"]: row["c"] for row in rows}


def cast_play_campaign_loot_vote(campaign_id, loot_id, voter, recipient_character_id):
    """Insert an immutable vote. Returns the new vote count for the recipient,
    or None if `voter` has already cast a vote for this loot record."""
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_loot_votes "
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
        conn.commit()
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM play_campaign_loot_votes "
            "WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?",
            (campaign_id, loot_id, recipient_character_id),
        ).fetchone()
        return row["c"]


def assign_play_campaign_loot(campaign_id, loot_id):
    """Atomically pick the unambiguous top-voted recipient, close the loot as
    assigned, and credit the recipient's inventory.

    Returns a ready-to-send success dict, or {"error": ...} with one of
    "not_found", "not_open", "no_votes", "tie" on failure.
    """
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT item_id, quantity, status FROM play_campaign_loot "
            "WHERE campaign_id = ? AND loot_id = ?",
            (campaign_id, loot_id),
        ).fetchone()
        if row is None:
            return {"error": "not_found"}
        if row["status"] != "open":
            return {"error": "not_open"}

        vote_rows = conn.execute(
            "SELECT recipient_character_id, COUNT(*) AS c FROM play_campaign_loot_votes "
            "WHERE campaign_id = ? AND loot_id = ? "
            "GROUP BY recipient_character_id ORDER BY c DESC",
            (campaign_id, loot_id),
        ).fetchall()
        if not vote_rows:
            return {"error": "no_votes"}

        top_count = vote_rows[0]["c"]
        leaders = [r["recipient_character_id"] for r in vote_rows if r["c"] == top_count]
        if len(leaders) != 1:
            return {"error": "tie"}
        recipient_character_id = leaders[0]

        item_id = row["item_id"]
        quantity = row["quantity"]

        conn.execute(
            "UPDATE play_campaign_loot SET status = 'assigned', recipient_character_id = ? "
            "WHERE campaign_id = ? AND loot_id = ?",
            (recipient_character_id, campaign_id, loot_id),
        )
        inv_row = conn.execute(
            "SELECT quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, recipient_character_id, item_id),
        ).fetchone()
        if inv_row is None:
            conn.execute(
                "INSERT INTO play_campaign_character_inventory_items "
                "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)",
                (campaign_id, recipient_character_id, item_id, quantity),
            )
        else:
            conn.execute(
                "UPDATE play_campaign_character_inventory_items SET quantity = ? "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (inv_row["quantity"] + quantity, campaign_id, recipient_character_id, item_id),
            )
        conn.commit()

        return {
            "loot_id": loot_id,
            "recipient_character_id": recipient_character_id,
            "item_id": item_id,
            "quantity": quantity,
            "votes": top_count,
            "status": "assigned",
        }


# -- play campaign npcs ----------------------------------------------------


def get_play_campaign_npc(campaign_id, npc_id):
    with db_conn() as conn:
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


def create_play_campaign_npc(campaign_id, npc_id, name, agenda, public_status):
    """Insert a new campaign NPC. Returns False if npc_id already exists in the campaign."""
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_npcs "
            "(campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, npc_id, name, agenda, public_status),
        )
        conn.commit()
        return True


def update_play_campaign_npc_agenda(campaign_id, npc_id, agenda, public_status):
    """Update an existing NPC's agenda and public status. Returns the updated
    record, or None if the NPC does not exist."""
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT name FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
        if existing is None:
            return None
        conn.execute(
            "UPDATE play_campaign_npcs SET agenda = ?, public_status = ? "
            "WHERE campaign_id = ? AND npc_id = ?",
            (agenda, public_status, campaign_id, npc_id),
        )
        conn.commit()
        return {
            "npc_id": npc_id,
            "name": existing["name"],
            "agenda": agenda,
            "public_status": public_status,
        }


# -- play campaign npc dialogue --------------------------------------------


def create_play_campaign_npc_dialogue(campaign_id, npc_id, dialogue_id, speaker, text, visibility):
    """Append an NPC dialogue entry. Returns False if dialogue_id already exists
    for this NPC."""
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_npc_dialogue "
            "WHERE campaign_id = ? AND npc_id = ? AND dialogue_id = ?",
            (campaign_id, npc_id, dialogue_id),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_npc_dialogue "
            "(campaign_id, npc_id, dialogue_id, speaker, text, visibility) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, npc_id, dialogue_id, speaker, text, visibility),
        )
        conn.commit()
        return True


def get_play_campaign_npc_dialogue_history(campaign_id, npc_id, public_only=False):
    with db_conn() as conn:
        if public_only:
            rows = conn.execute(
                "SELECT dialogue_id, speaker, text, visibility "
                "FROM play_campaign_npc_dialogue "
                "WHERE campaign_id = ? AND npc_id = ? AND visibility = 'public' "
                "ORDER BY rowid ASC",
                (campaign_id, npc_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT dialogue_id, speaker, text, visibility "
                "FROM play_campaign_npc_dialogue "
                "WHERE campaign_id = ? AND npc_id = ? ORDER BY rowid ASC",
                (campaign_id, npc_id),
            ).fetchall()
        return [
            {
                "dialogue_id": r["dialogue_id"],
                "speaker": r["speaker"],
                "text": r["text"],
                "visibility": r["visibility"],
            }
            for r in rows
        ]


# -- play campaign relationships ------------------------------------------


def play_campaign_entity_exists(campaign_id, entity_id):
    """True if entity_id names a campaign member character or NPC."""
    with db_conn() as conn:
        member = conn.execute(
            "SELECT 1 FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, entity_id),
        ).fetchone()
        if member is not None:
            return True
        npc = conn.execute(
            "SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, entity_id),
        ).fetchone()
        return npc is not None


def get_play_campaign_relationship(campaign_id, source_id, target_id, kind):
    with db_conn() as conn:
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


def create_play_campaign_relationship(campaign_id, source_id, target_id, kind, score):
    """Insert a new relationship edge. Returns False if the directed
    (source_id, target_id, kind) edge already exists."""
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_relationships "
            "WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
            (campaign_id, source_id, target_id, kind),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_relationships "
            "(campaign_id, source_id, target_id, kind, score) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, source_id, target_id, kind, score),
        )
        conn.commit()
        return True


def update_play_campaign_relationship_score(campaign_id, source_id, target_id, kind, score):
    """Update an existing edge's score. Returns the updated edge, or None if
    the edge does not exist."""
    with DB_LOCK, db_conn() as conn:
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
        conn.commit()
        return {
            "source_id": source_id,
            "target_id": target_id,
            "kind": kind,
            "score": score,
        }


def get_play_campaign_relationships(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT source_id, target_id, kind, score FROM play_campaign_relationships "
            "WHERE campaign_id = ? ORDER BY rowid ASC",
            (campaign_id,),
        ).fetchall()
        return [
            {
                "source_id": r["source_id"],
                "target_id": r["target_id"],
                "kind": r["kind"],
                "score": r["score"],
            }
            for r in rows
        ]


# -- campaign clues --------------------------------------------------------

def get_play_campaign_clue(campaign_id, clue_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT clue_id, text, audience, character_id FROM play_campaign_clues "
            "WHERE campaign_id = ? AND clue_id = ?",
            (campaign_id, clue_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "clue_id": row["clue_id"],
            "text": row["text"],
            "audience": row["audience"],
            "character_id": row["character_id"],
        }


def create_play_campaign_clue(campaign_id, clue_id, text, audience, character_id):
    """Insert a new clue. Returns False if clue_id already exists in the campaign."""
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_clues WHERE campaign_id = ? AND clue_id = ?",
            (campaign_id, clue_id),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_clues "
            "(campaign_id, clue_id, text, audience, character_id) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, clue_id, text, audience, character_id),
        )
        conn.commit()
        return True


def get_play_campaign_clues(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT clue_id, text, audience, character_id FROM play_campaign_clues "
            "WHERE campaign_id = ? ORDER BY rowid ASC",
            (campaign_id,),
        ).fetchall()
        return [
            {
                "clue_id": r["clue_id"],
                "text": r["text"],
                "audience": r["audience"],
                "character_id": r["character_id"],
            }
            for r in rows
        ]


# -- campaign quests -------------------------------------------------------

def get_play_campaign_quest(campaign_id, quest_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT quest_id, title, depends_on_json, state FROM play_campaign_quests "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "quest_id": row["quest_id"],
            "title": row["title"],
            "depends_on": json.loads(row["depends_on_json"]),
            "state": row["state"],
        }


def create_play_campaign_quest(campaign_id, quest_id, title, depends_on):
    """Insert a new quest. Returns False if quest_id already exists in the campaign."""
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_quests "
            "(campaign_id, quest_id, title, depends_on_json, state) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, quest_id, title, json.dumps(depends_on), "locked"),
        )
        conn.commit()
        return True


def get_play_campaign_quests(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT quest_id, title, depends_on_json, state FROM play_campaign_quests "
            "WHERE campaign_id = ? ORDER BY rowid ASC",
            (campaign_id,),
        ).fetchall()
        return [
            {
                "quest_id": r["quest_id"],
                "title": r["title"],
                "depends_on": json.loads(r["depends_on_json"]),
                "state": r["state"],
            }
            for r in rows
        ]


def set_play_campaign_quest_state(campaign_id, quest_id, state):
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "UPDATE play_campaign_quests SET state = ? "
            "WHERE campaign_id = ? AND quest_id = ?",
            (state, campaign_id, quest_id),
        )
        conn.commit()


# -- campaign quest rewards -------------------------------------------------

def get_play_campaign_quest_rewards(campaign_id, quest_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT xp, items_json, awarded FROM play_campaign_quest_rewards "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "xp": row["xp"],
            "items": json.loads(row["items_json"]),
            "awarded": bool(row["awarded"]),
        }


def set_play_campaign_quest_rewards(campaign_id, quest_id, xp, items):
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "INSERT INTO play_campaign_quest_rewards "
            "(campaign_id, quest_id, xp, items_json, awarded) VALUES (?, ?, ?, ?, 0) "
            "ON CONFLICT (campaign_id, quest_id) DO UPDATE SET "
            "xp = excluded.xp, items_json = excluded.items_json, awarded = 0",
            (campaign_id, quest_id, xp, json.dumps(items)),
        )
        conn.commit()


def award_play_campaign_quest_rewards(campaign_id, quest_id, character_ids):
    """Grant configured rewards to every character in `character_ids`, once.

    Returns the rewards dict on success, or None if rewards aren't
    configured or have already been awarded (in which case nothing changes).
    """
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT xp, items_json, awarded FROM play_campaign_quest_rewards "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if row is None or row["awarded"]:
            return None

        xp = row["xp"]
        items = json.loads(row["items_json"])

        conn.execute(
            "UPDATE play_campaign_quest_rewards SET awarded = 1 "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        )

        for character_id in character_ids:
            existing = conn.execute(
                "SELECT xp, items_json FROM play_campaign_character_quest_rewards "
                "WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if existing is None:
                total_xp = xp
                total_items = dict(items)
            else:
                total_xp = existing["xp"] + xp
                total_items = json.loads(existing["items_json"])
                for item_id, qty in items.items():
                    total_items[item_id] = total_items.get(item_id, 0) + qty
            conn.execute(
                "INSERT INTO play_campaign_character_quest_rewards "
                "(campaign_id, character_id, xp, items_json) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (campaign_id, character_id) DO UPDATE SET "
                "xp = excluded.xp, items_json = excluded.items_json",
                (campaign_id, character_id, total_xp, json.dumps(total_items)),
            )

            for item_id, qty in items.items():
                inv_row = conn.execute(
                    "SELECT quantity FROM play_campaign_character_inventory_items "
                    "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (campaign_id, character_id, item_id),
                ).fetchone()
                if inv_row is None:
                    conn.execute(
                        "INSERT INTO play_campaign_character_inventory_items "
                        "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)",
                        (campaign_id, character_id, item_id, qty),
                    )
                else:
                    conn.execute(
                        "UPDATE play_campaign_character_inventory_items SET quantity = ? "
                        "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                        (inv_row["quantity"] + qty, campaign_id, character_id, item_id),
                    )

        conn.commit()
        return {"xp": xp, "items": items}


def get_play_campaign_character_quest_rewards(campaign_id, character_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT xp, items_json FROM play_campaign_character_quest_rewards "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if row is None:
            return {"xp": 0, "items": {}}
        return {"xp": row["xp"], "items": json.loads(row["items_json"])}


# -- campaign world events ---------------------------------------------------

def _world_event_row_to_dict(row):
    resolution = None
    if row["status"] == "resolved":
        resolution = {
            "turn_number": row["resolution_turn_number"],
            "text": row["resolution_text"],
        }
    return {
        "event_id": row["event_id"],
        "turn_number": row["turn_number"],
        "title": row["title"],
        "text": row["text"],
        "status": row["status"],
        "resolution": resolution,
    }


def create_play_campaign_world_event(campaign_id, event_id, turn_number, title, text):
    """Insert a scheduled world event. Returns False if event_id already exists."""
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_world_events "
            "WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_world_events "
            "(campaign_id, event_id, turn_number, title, text, status) "
            "VALUES (?, ?, ?, ?, ?, 'scheduled')",
            (campaign_id, event_id, turn_number, title, text),
        )
        conn.commit()
        return True


def get_play_campaign_world_event(campaign_id, event_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT event_id, turn_number, title, text, status, "
            "resolution_turn_number, resolution_text "
            "FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if row is None:
            return None
        return _world_event_row_to_dict(row)


def get_play_campaign_world_events(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT event_id, turn_number, title, text, status, "
            "resolution_turn_number, resolution_text "
            "FROM play_campaign_world_events WHERE campaign_id = ? "
            "ORDER BY turn_number ASC, rowid ASC",
            (campaign_id,),
        ).fetchall()
        return [_world_event_row_to_dict(row) for row in rows]


def resolve_play_campaign_world_event(campaign_id, event_id, resolution_text):
    """Resolve a scheduled world event. Returns False if already resolved."""
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT turn_number, status FROM play_campaign_world_events "
            "WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if row is None:
            return None
        if row["status"] == "resolved":
            return False
        conn.execute(
            "UPDATE play_campaign_world_events SET status = 'resolved', "
            "resolution_turn_number = ?, resolution_text = ? "
            "WHERE campaign_id = ? AND event_id = ?",
            (row["turn_number"], resolution_text, campaign_id, event_id),
        )
        conn.commit()
        return True


def create_play_campaign_calendar(campaign_id, day, season):
    """Insert the campaign's calendar. Returns False if already initialized."""
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_calendars WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_calendars (campaign_id, day, season) "
            "VALUES (?, ?, ?)",
            (campaign_id, day, season),
        )
        conn.commit()
        return True


def get_play_campaign_calendar(campaign_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        return {"day": row["day"], "season": row["season"]}


def advance_play_campaign_calendar(campaign_id, days):
    """Advance the campaign's day by `days`. Returns None if not initialized."""
    with DB_LOCK, db_conn() as conn:
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
        conn.commit()
        return {"day": new_day, "season": row["season"]}


# -- campaign factions / reputation ---------------------------------------

def get_play_campaign_faction(campaign_id, faction_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT faction_id, name FROM play_campaign_factions "
            "WHERE campaign_id = ? AND faction_id = ?",
            (campaign_id, faction_id),
        ).fetchone()
        if row is None:
            return None
        return {"faction_id": row["faction_id"], "name": row["name"]}


def create_play_campaign_faction(campaign_id, faction_id, name):
    """Insert a new campaign faction. Returns False if faction_id already exists."""
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?",
            (campaign_id, faction_id),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_factions (campaign_id, faction_id, name) "
            "VALUES (?, ?, ?)",
            (campaign_id, faction_id, name),
        )
        conn.commit()
        return True


def get_play_campaign_faction_reputation_total(campaign_id, faction_id, character_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT reputation FROM play_campaign_reputation_history "
            "WHERE campaign_id = ? AND faction_id = ? AND character_id = ? "
            "ORDER BY rowid DESC LIMIT 1",
            (campaign_id, faction_id, character_id),
        ).fetchone()
        if row is None:
            return 0
        return row["reputation"]


def add_play_campaign_reputation_entry(campaign_id, faction_id, character_id, delta, reason):
    """Apply a bounded reputation delta and store an immutable history entry.

    Returns the created entry.
    """
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT reputation FROM play_campaign_reputation_history "
            "WHERE campaign_id = ? AND faction_id = ? AND character_id = ? "
            "ORDER BY rowid DESC LIMIT 1",
            (campaign_id, faction_id, character_id),
        ).fetchone()
        current = row["reputation"] if row is not None else 0
        new_total = max(-100, min(100, current + delta))
        conn.execute(
            "INSERT INTO play_campaign_reputation_history "
            "(campaign_id, faction_id, character_id, reputation, delta, reason) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, faction_id, character_id, new_total, delta, reason),
        )
        conn.commit()
        return {
            "faction_id": faction_id,
            "character_id": character_id,
            "reputation": new_total,
            "delta": delta,
            "reason": reason,
        }


def get_play_campaign_faction_reputation_history(campaign_id, faction_id, character_id=None):
    with db_conn() as conn:
        if character_id is None:
            rows = conn.execute(
                "SELECT faction_id, character_id, reputation, delta, reason "
                "FROM play_campaign_reputation_history "
                "WHERE campaign_id = ? AND faction_id = ? ORDER BY rowid ASC",
                (campaign_id, faction_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT faction_id, character_id, reputation, delta, reason "
                "FROM play_campaign_reputation_history "
                "WHERE campaign_id = ? AND faction_id = ? AND character_id = ? "
                "ORDER BY rowid ASC",
                (campaign_id, faction_id, character_id),
            ).fetchall()
        return [
            {
                "faction_id": r["faction_id"],
                "character_id": r["character_id"],
                "reputation": r["reputation"],
                "delta": r["delta"],
                "reason": r["reason"],
            }
            for r in rows
        ]


def _settlement_row_to_dict(row, discovered_by):
    return {
        "settlement_id": row["settlement_id"],
        "name": row["name"],
        "services": json.loads(row["services_json"]),
        "availability": row["availability"],
        "discovered_by": discovered_by,
    }


def _get_settlement_discovered_by(conn, campaign_id, settlement_id):
    rows = conn.execute(
        "SELECT character_id FROM play_campaign_settlement_discoveries "
        "WHERE campaign_id = ? AND settlement_id = ? ORDER BY rowid ASC",
        (campaign_id, settlement_id),
    ).fetchall()
    return [r["character_id"] for r in rows]


def get_play_campaign_settlement(campaign_id, settlement_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT settlement_id, name, services_json, availability "
            "FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?",
            (campaign_id, settlement_id),
        ).fetchone()
        if row is None:
            return None
        discovered_by = _get_settlement_discovered_by(conn, campaign_id, settlement_id)
        return _settlement_row_to_dict(row, discovered_by)


def create_play_campaign_settlement(campaign_id, settlement_id, name, services, availability):
    with db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_settlements "
            "WHERE campaign_id = ? AND settlement_id = ?",
            (campaign_id, settlement_id),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_settlements "
            "(campaign_id, settlement_id, name, services_json, availability) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, settlement_id, name, json.dumps(services), availability),
        )
        conn.commit()
        return True


def update_play_campaign_settlement(campaign_id, settlement_id, name, services, availability):
    with db_conn() as conn:
        conn.execute(
            "UPDATE play_campaign_settlements SET name = ?, services_json = ?, "
            "availability = ? WHERE campaign_id = ? AND settlement_id = ?",
            (name, json.dumps(services), availability, campaign_id, settlement_id),
        )
        conn.commit()


def get_play_campaign_settlements(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT settlement_id, name, services_json, availability "
            "FROM play_campaign_settlements WHERE campaign_id = ? ORDER BY rowid ASC",
            (campaign_id,),
        ).fetchall()
        settlements = []
        for row in rows:
            discovered_by = _get_settlement_discovered_by(conn, campaign_id, row["settlement_id"])
            settlements.append(_settlement_row_to_dict(row, discovered_by))
        return settlements


def discover_play_campaign_settlement(campaign_id, settlement_id, character_id):
    """Record a discovery. Returns True if newly discovered, False if already known."""
    with db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_settlement_discoveries "
            "WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?",
            (campaign_id, settlement_id, character_id),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_settlement_discoveries "
            "(campaign_id, settlement_id, character_id) VALUES (?, ?, ?)",
            (campaign_id, settlement_id, character_id),
        )
        conn.commit()
        return True


# -- play campaign settlement shops ------------------------------------------


def _shop_row_to_dict(row):
    return {
        "shop_id": row["shop_id"],
        "name": row["name"],
        "stock": json.loads(row["stock_json"]),
        "buy_price": row["buy_price"],
        "sell_price": row["sell_price"],
    }


def get_play_campaign_shop(campaign_id, settlement_id, shop_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT shop_id, name, stock_json, buy_price, sell_price "
            "FROM play_campaign_shops "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (campaign_id, settlement_id, shop_id),
        ).fetchone()
        if row is None:
            return None
        return _shop_row_to_dict(row)


def create_play_campaign_shop(
    campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price
):
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_shops "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (campaign_id, settlement_id, shop_id),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_shops "
            "(campaign_id, settlement_id, shop_id, name, stock_json, buy_price, sell_price) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, settlement_id, shop_id, name, json.dumps(stock), buy_price, sell_price),
        )
        conn.commit()
        return True


def buy_play_campaign_shop_item(
    campaign_id, settlement_id, shop_id, character_id, item_id, quantity
):
    """Atomically buy `quantity` of `item_id` from a shop for `character_id`.

    Returns (gold, new_stock) on success, or None if stock or gold is
    insufficient (leaving all state unchanged).
    """
    with DB_LOCK, db_conn() as conn:
        shop_row = conn.execute(
            "SELECT stock_json, buy_price FROM play_campaign_shops "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (campaign_id, settlement_id, shop_id),
        ).fetchone()
        if shop_row is None:
            return None
        stock = json.loads(shop_row["stock_json"])
        held = stock.get(item_id, 0)
        if held < quantity:
            return None

        cost = shop_row["buy_price"] * quantity
        member_row = conn.execute(
            "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if member_row is None or member_row["gold"] < cost:
            return None

        new_gold = member_row["gold"] - cost
        new_stock_qty = held - quantity
        stock[item_id] = new_stock_qty
        conn.execute(
            "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?",
            (new_gold, campaign_id, character_id),
        )
        conn.execute(
            "UPDATE play_campaign_shops SET stock_json = ? "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (json.dumps(stock), campaign_id, settlement_id, shop_id),
        )
        item_row = conn.execute(
            "SELECT quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()
        if item_row is None:
            conn.execute(
                "INSERT INTO play_campaign_character_inventory_items "
                "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)",
                (campaign_id, character_id, item_id, quantity),
            )
        else:
            conn.execute(
                "UPDATE play_campaign_character_inventory_items SET quantity = ? "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (item_row["quantity"] + quantity, campaign_id, character_id, item_id),
            )
        conn.commit()
        return new_gold, new_stock_qty


def sell_play_campaign_shop_item(
    campaign_id, settlement_id, shop_id, character_id, item_id, quantity
):
    """Atomically sell `quantity` of `item_id` from `character_id` to a shop.

    Returns (gold, new_stock) on success, or None if the character does not
    hold enough of the item (leaving all state unchanged).
    """
    with DB_LOCK, db_conn() as conn:
        shop_row = conn.execute(
            "SELECT stock_json, sell_price FROM play_campaign_shops "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (campaign_id, settlement_id, shop_id),
        ).fetchone()
        if shop_row is None:
            return None

        item_row = conn.execute(
            "SELECT quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()
        held = item_row["quantity"] if item_row is not None else 0
        if held < quantity:
            return None

        proceeds = shop_row["sell_price"] * quantity
        member_row = conn.execute(
            "SELECT gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        new_gold = member_row["gold"] + proceeds

        stock = json.loads(shop_row["stock_json"])
        new_stock_qty = stock.get(item_id, 0) + quantity
        stock[item_id] = new_stock_qty

        conn.execute(
            "UPDATE play_campaign_character_inventory_items SET quantity = ? "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (held - quantity, campaign_id, character_id, item_id),
        )
        conn.execute(
            "UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?",
            (new_gold, campaign_id, character_id),
        )
        conn.execute(
            "UPDATE play_campaign_shops SET stock_json = ? "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (json.dumps(stock), campaign_id, settlement_id, shop_id),
        )
        conn.commit()
        return new_gold, new_stock_qty


# -- play campaign recipes ---------------------------------------------------


def _recipe_row_to_dict(row):
    return {
        "recipe_id": row["recipe_id"],
        "name": row["name"],
        "ingredients": json.loads(row["ingredients_json"]),
        "output_item": row["output_item"],
        "output_quantity": row["output_quantity"],
    }


def get_play_campaign_recipe(campaign_id, recipe_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT recipe_id, name, ingredients_json, output_item, output_quantity "
            "FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?",
            (campaign_id, recipe_id),
        ).fetchone()
        if row is None:
            return None
        return _recipe_row_to_dict(row)


def get_play_campaign_recipes(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT recipe_id, name, ingredients_json, output_item, output_quantity "
            "FROM play_campaign_recipes WHERE campaign_id = ? ORDER BY rowid ASC",
            (campaign_id,),
        ).fetchall()
        return [_recipe_row_to_dict(row) for row in rows]


def create_play_campaign_recipe(
    campaign_id, recipe_id, name, ingredients, output_item, output_quantity
):
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?",
            (campaign_id, recipe_id),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_recipes "
            "(campaign_id, recipe_id, name, ingredients_json, output_item, output_quantity) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, recipe_id, name, json.dumps(ingredients), output_item, output_quantity),
        )
        conn.commit()
        return True


def craft_play_campaign_recipe(campaign_id, character_id, recipe_id):
    """Atomically consume a recipe's ingredients and add its output.

    Returns True on success, or None if the recipe is unknown or the
    character lacks sufficient ingredients (leaving all state unchanged).
    """
    with DB_LOCK, db_conn() as conn:
        recipe_row = conn.execute(
            "SELECT ingredients_json, output_item, output_quantity "
            "FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?",
            (campaign_id, recipe_id),
        ).fetchone()
        if recipe_row is None:
            return None

        ingredients = json.loads(recipe_row["ingredients_json"])
        for item_id, required_qty in ingredients.items():
            item_row = conn.execute(
                "SELECT quantity FROM play_campaign_character_inventory_items "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, character_id, item_id),
            ).fetchone()
            held = item_row["quantity"] if item_row is not None else 0
            if held < required_qty:
                return None

        for item_id, required_qty in ingredients.items():
            item_row = conn.execute(
                "SELECT quantity FROM play_campaign_character_inventory_items "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, character_id, item_id),
            ).fetchone()
            conn.execute(
                "UPDATE play_campaign_character_inventory_items SET quantity = ? "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (item_row["quantity"] - required_qty, campaign_id, character_id, item_id),
            )

        output_item = recipe_row["output_item"]
        output_quantity = recipe_row["output_quantity"]
        output_row = conn.execute(
            "SELECT quantity FROM play_campaign_character_inventory_items "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, output_item),
        ).fetchone()
        if output_row is None:
            conn.execute(
                "INSERT INTO play_campaign_character_inventory_items "
                "(campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)",
                (campaign_id, character_id, output_item, output_quantity),
            )
        else:
            conn.execute(
                "UPDATE play_campaign_character_inventory_items SET quantity = ? "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (output_row["quantity"] + output_quantity, campaign_id, character_id, output_item),
            )

        conn.commit()
        return True


def _downtime_activity_row_to_dict(row):
    return {
        "activity_id": row["activity_id"],
        "name": row["name"],
        "cycles_required": row["cycles_required"],
    }


def get_play_campaign_downtime_activity(campaign_id, activity_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT activity_id, name, cycles_required "
            "FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?",
            (campaign_id, activity_id),
        ).fetchone()
        if row is None:
            return None
        return _downtime_activity_row_to_dict(row)


def create_play_campaign_downtime_activity(campaign_id, activity_id, name, cycles_required):
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_downtime_activities "
            "WHERE campaign_id = ? AND activity_id = ?",
            (campaign_id, activity_id),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_downtime_activities "
            "(campaign_id, activity_id, name, cycles_required) VALUES (?, ?, ?, ?)",
            (campaign_id, activity_id, name, cycles_required),
        )
        conn.commit()
        return True


def _downtime_allocation_row_to_dict(row):
    return {
        "character_id": row["character_id"],
        "activity_id": row["activity_id"],
        "cycles_completed": row["cycles_completed"],
        "completions": row["completions"],
    }


def get_play_campaign_downtime_allocation(campaign_id, character_id, activity_id):
    with db_conn() as conn:
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
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_downtime_allocations "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (campaign_id, character_id, activity_id),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_downtime_allocations "
            "(campaign_id, character_id, activity_id, cycles_completed, completions) "
            "VALUES (?, ?, ?, 0, 0)",
            (campaign_id, character_id, activity_id),
        )
        conn.commit()
        return True


def progress_play_campaign_downtime_allocation(campaign_id, character_id, activity_id):
    """Advance an allocation by one cycle, rolling over into a completion.

    Returns the updated allocation dict, or None if the allocation is unknown.
    """
    with DB_LOCK, db_conn() as conn:
        activity_row = conn.execute(
            "SELECT cycles_required FROM play_campaign_downtime_activities "
            "WHERE campaign_id = ? AND activity_id = ?",
            (campaign_id, activity_id),
        ).fetchone()
        if activity_row is None:
            return None

        row = conn.execute(
            "SELECT cycles_completed, completions FROM play_campaign_downtime_allocations "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (campaign_id, character_id, activity_id),
        ).fetchone()
        if row is None:
            return None

        cycles_completed = row["cycles_completed"] + 1
        completions = row["completions"]
        if cycles_completed >= activity_row["cycles_required"]:
            cycles_completed = 0
            completions += 1

        conn.execute(
            "UPDATE play_campaign_downtime_allocations SET cycles_completed = ?, completions = ? "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (cycles_completed, completions, campaign_id, character_id, activity_id),
        )
        conn.commit()
        return {
            "character_id": character_id,
            "activity_id": activity_id,
            "cycles_completed": cycles_completed,
            "completions": completions,
        }


# -- play: notes ----------------------------------------------------------

def _note_row_to_dict(row):
    return {
        "note_id": row["note_id"],
        "text": row["text"],
        "visibility": row["visibility"],
        "owner": row["owner"],
    }


def create_play_campaign_note(campaign_id, note_id, text, visibility, owner):
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?",
            (campaign_id, note_id),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_notes "
            "(campaign_id, note_id, text, visibility, owner) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, note_id, text, visibility, owner),
        )
        conn.commit()
        return True


def get_play_campaign_note(campaign_id, note_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT note_id, text, visibility, owner FROM play_campaign_notes "
            "WHERE campaign_id = ? AND note_id = ?",
            (campaign_id, note_id),
        ).fetchone()
        if row is None:
            return None
        return _note_row_to_dict(row)


def get_play_campaign_notes(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT note_id, text, visibility, owner FROM play_campaign_notes "
            "WHERE campaign_id = ? ORDER BY rowid ASC",
            (campaign_id,),
        ).fetchall()
        return [_note_row_to_dict(row) for row in rows]


def create_play_campaign_search_record(campaign_id, record_id, text):
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_search_records "
            "WHERE campaign_id = ? AND record_id = ?",
            (campaign_id, record_id),
        ).fetchone()
        if existing is not None:
            return False
        existing_text = conn.execute(
            "SELECT 1 FROM play_campaign_search_records "
            "WHERE campaign_id = ? AND text = ?",
            (campaign_id, text),
        ).fetchone()
        if existing_text is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_search_records "
            "(campaign_id, record_id, text) VALUES (?, ?, ?)",
            (campaign_id, record_id, text),
        )
        conn.commit()
        return True


def get_play_campaign_search_records(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT record_id, text FROM play_campaign_search_records "
            "WHERE campaign_id = ? ORDER BY rowid ASC",
            (campaign_id,),
        ).fetchall()
        return [{"record_id": row[0], "text": row[1]} for row in rows]


def update_play_campaign_note(campaign_id, note_id, text, visibility):
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?",
            (campaign_id, note_id),
        ).fetchone()
        if existing is None:
            return None
        conn.execute(
            "UPDATE play_campaign_notes SET text = ?, visibility = ? "
            "WHERE campaign_id = ? AND note_id = ?",
            (text, visibility, campaign_id, note_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT note_id, text, visibility, owner FROM play_campaign_notes "
            "WHERE campaign_id = ? AND note_id = ?",
            (campaign_id, note_id),
        ).fetchone()
        return _note_row_to_dict(row)


# -- play: invitations -------------------------------------------------------

def _invitation_row_to_dict(row):
    return {
        "invitation_id": row["invitation_id"],
        "username": row["username"],
        "character_id": row["character_id"],
        "status": row["status"],
    }


def create_play_campaign_invitation(campaign_id, invitation_id, username, character_id):
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "INSERT INTO play_campaign_invitations "
            "(campaign_id, invitation_id, username, character_id, status) "
            "VALUES (?, ?, ?, ?, 'pending')",
            (campaign_id, invitation_id, username, character_id),
        )
        conn.commit()


def get_play_campaign_invitation(campaign_id, invitation_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT invitation_id, username, character_id, status "
            "FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?",
            (campaign_id, invitation_id),
        ).fetchone()
        if row is None:
            return None
        return _invitation_row_to_dict(row)


def get_play_campaign_pending_invitation_for_user(campaign_id, username):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT invitation_id, username, character_id, status "
            "FROM play_campaign_invitations "
            "WHERE campaign_id = ? AND username = ? AND status = 'pending'",
            (campaign_id, username),
        ).fetchone()
        if row is None:
            return None
        return _invitation_row_to_dict(row)


def get_play_campaign_invitations(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT invitation_id, username, character_id, status "
            "FROM play_campaign_invitations WHERE campaign_id = ? ORDER BY rowid ASC",
            (campaign_id,),
        ).fetchall()
        return [_invitation_row_to_dict(row) for row in rows]


def update_play_campaign_invitation_status(campaign_id, invitation_id, status):
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "UPDATE play_campaign_invitations SET status = ? "
            "WHERE campaign_id = ? AND invitation_id = ?",
            (status, campaign_id, invitation_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT invitation_id, username, character_id, status "
            "FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?",
            (campaign_id, invitation_id),
        ).fetchone()
        return _invitation_row_to_dict(row)


# -- play: delegations --------------------------------------------------------

def _delegation_row_to_dict(row):
    return {
        "username": row["username"],
        "powers": json.loads(row["powers_json"]),
        "active": bool(row["active"]),
    }


def get_play_campaign_delegation(campaign_id, username):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT username, powers_json, active FROM play_campaign_delegations "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if row is None:
            return None
        return _delegation_row_to_dict(row)


def upsert_play_campaign_delegation(campaign_id, username, powers):
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "INSERT INTO play_campaign_delegations "
            "(campaign_id, username, powers_json, active) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(campaign_id, username) DO UPDATE SET "
            "powers_json = excluded.powers_json, active = 1",
            (campaign_id, username, json.dumps(powers)),
        )
        conn.commit()
        row = conn.execute(
            "SELECT username, powers_json, active FROM play_campaign_delegations "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        return _delegation_row_to_dict(row)


def revoke_play_campaign_delegation(campaign_id, username):
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "UPDATE play_campaign_delegations SET active = 0 "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        )
        conn.commit()
        row = conn.execute(
            "SELECT username, powers_json, active FROM play_campaign_delegations "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if row is None:
            return None
        return _delegation_row_to_dict(row)


def add_play_campaign_delegation_audit_entry(campaign_id, username, action, powers):
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "INSERT INTO play_campaign_delegation_audit "
            "(campaign_id, username, action, powers_json) VALUES (?, ?, ?, ?)",
            (campaign_id, username, action, json.dumps(powers)),
        )
        conn.commit()


def get_play_campaign_delegation_audit(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT username, action, powers_json FROM play_campaign_delegation_audit "
            "WHERE campaign_id = ? ORDER BY rowid ASC",
            (campaign_id,),
        ).fetchall()
        return [
            {
                "username": row["username"],
                "action": row["action"],
                "powers": json.loads(row["powers_json"]),
            }
            for row in rows
        ]


def add_play_campaign_audit_event(campaign_id, kind, actor, role, correlation_id):
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_audit_events "
            "WHERE campaign_id = ? AND correlation_id = ?",
            (campaign_id, correlation_id),
        ).fetchone()
        if existing is not None:
            return None

        count_row = conn.execute(
            "SELECT COUNT(*) AS c FROM play_campaign_audit_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        timestamp = count_row["c"] + 1

        conn.execute(
            "INSERT INTO play_campaign_audit_events "
            "(campaign_id, kind, actor, role, timestamp, correlation_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, kind, actor, role, timestamp, correlation_id),
        )
        conn.commit()
        return {
            "kind": kind,
            "actor": actor,
            "role": role,
            "timestamp": timestamp,
            "correlation_id": correlation_id,
        }


def get_play_campaign_audit_events(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT kind, actor, role, timestamp, correlation_id "
            "FROM play_campaign_audit_events WHERE campaign_id = ? "
            "ORDER BY timestamp ASC",
            (campaign_id,),
        ).fetchall()
        return [
            {
                "kind": row["kind"],
                "actor": row["actor"],
                "role": row["role"],
                "timestamp": row["timestamp"],
                "correlation_id": row["correlation_id"],
            }
            for row in rows
        ]


# -- play: projections -------------------------------------------------------

def add_play_campaign_projection_event(campaign_id, event_id, kind, value):
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_projection_events "
            "WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if existing is not None:
            return None

        count_row = conn.execute(
            "SELECT COUNT(*) AS c FROM play_campaign_projection_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = count_row["c"] + 1

        conn.execute(
            "INSERT INTO play_campaign_projection_events "
            "(campaign_id, sequence, event_id, kind, value) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, event_id, kind, value),
        )
        conn.commit()
        return {"sequence": sequence, "event_id": event_id, "kind": kind, "value": value}


def get_play_campaign_projection_events(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT sequence, event_id, kind, value FROM play_campaign_projection_events "
            "WHERE campaign_id = ? ORDER BY sequence ASC",
            (campaign_id,),
        ).fetchall()
        return [
            {
                "sequence": row["sequence"],
                "event_id": row["event_id"],
                "kind": row["kind"],
                "value": row["value"],
            }
            for row in rows
        ]


def compute_play_campaign_projection(campaign_id):
    story = ""
    danger = 0
    applied_event_ids = []
    for event in get_play_campaign_projection_events(campaign_id):
        applied_event_ids.append(event["event_id"])
        if event["kind"] == "set-story":
            story = event["value"]
        elif event["kind"] == "increment-danger":
            danger += 1
    return {"story": story, "danger": danger, "applied_event_ids": applied_event_ids}


# -- play: idempotent events -------------------------------------------------

def add_play_campaign_idempotent_event(campaign_id, idempotency_key, event_id, value):
    with DB_LOCK, db_conn() as conn:
        key_row = conn.execute(
            "SELECT sequence, event_id, value, idempotency_key "
            "FROM play_campaign_idempotent_events "
            "WHERE campaign_id = ? AND idempotency_key = ?",
            (campaign_id, idempotency_key),
        ).fetchone()
        if key_row is not None:
            if key_row["event_id"] == event_id and key_row["value"] == value:
                return "duplicate", {
                    "event_id": key_row["event_id"],
                    "value": key_row["value"],
                    "sequence": key_row["sequence"],
                    "idempotency_key": key_row["idempotency_key"],
                }
            return "conflict", None

        event_row = conn.execute(
            "SELECT 1 FROM play_campaign_idempotent_events "
            "WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if event_row is not None:
            return "conflict", None

        count_row = conn.execute(
            "SELECT COUNT(*) AS c FROM play_campaign_idempotent_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = count_row["c"] + 1

        conn.execute(
            "INSERT INTO play_campaign_idempotent_events "
            "(campaign_id, sequence, event_id, value, idempotency_key) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, event_id, value, idempotency_key),
        )
        conn.commit()
        return "created", {
            "event_id": event_id,
            "value": value,
            "sequence": sequence,
            "idempotency_key": idempotency_key,
        }


def get_play_campaign_idempotent_events(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT sequence, event_id, value, idempotency_key "
            "FROM play_campaign_idempotent_events "
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


# -- play: safe turns --------------------------------------------------------

def submit_play_campaign_safe_turn(campaign_id, submission_id, expected_turn, action):
    with DB_LOCK, db_conn() as conn:
        state_row = conn.execute(
            "SELECT current_turn FROM play_campaign_safe_turn_state WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if state_row is None:
            current_turn = 1
            conn.execute(
                "INSERT INTO play_campaign_safe_turn_state (campaign_id, current_turn) VALUES (?, ?)",
                (campaign_id, current_turn),
            )
        else:
            current_turn = state_row["current_turn"]

        existing = conn.execute(
            "SELECT 1 FROM play_campaign_safe_turns WHERE campaign_id = ? AND submission_id = ?",
            (campaign_id, submission_id),
        ).fetchone()
        if existing is not None:
            conn.commit()
            return "duplicate", None

        if expected_turn != current_turn:
            conn.commit()
            return "stale", {"current_turn": current_turn}

        count_row = conn.execute(
            "SELECT COUNT(*) AS c FROM play_campaign_safe_turns WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = count_row["c"] + 1

        accepted_turn = current_turn
        next_turn = current_turn + 1

        conn.execute(
            "INSERT INTO play_campaign_safe_turns "
            "(campaign_id, sequence, submission_id, action, accepted_turn, next_turn) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, sequence, submission_id, action, accepted_turn, next_turn),
        )
        conn.execute(
            "UPDATE play_campaign_safe_turn_state SET current_turn = ? WHERE campaign_id = ?",
            (next_turn, campaign_id),
        )
        conn.commit()
        return "accepted", {
            "submission_id": submission_id,
            "action": action,
            "accepted_turn": accepted_turn,
            "next_turn": next_turn,
        }


def get_play_campaign_safe_turns(campaign_id):
    with db_conn() as conn:
        state_row = conn.execute(
            "SELECT current_turn FROM play_campaign_safe_turn_state WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        current_turn = state_row["current_turn"] if state_row is not None else 1

        rows = conn.execute(
            "SELECT submission_id, action, accepted_turn, next_turn "
            "FROM play_campaign_safe_turns WHERE campaign_id = ? ORDER BY sequence ASC",
            (campaign_id,),
        ).fetchall()
        accepted = [
            {
                "submission_id": row["submission_id"],
                "action": row["action"],
                "accepted_turn": row["accepted_turn"],
                "next_turn": row["next_turn"],
            }
            for row in rows
        ]
        return {"current_turn": current_turn, "accepted": accepted}


# -- play: whispers ---------------------------------------------------------

def _whisper_row_to_dict(row):
    return {
        "whisper_id": row["whisper_id"],
        "from_character_id": row["from_character_id"],
        "to_character_id": row["to_character_id"],
        "text": row["text"],
    }


def create_play_campaign_whisper(campaign_id, whisper_id, from_character_id, to_character_id, text):
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_whispers WHERE campaign_id = ? AND whisper_id = ?",
            (campaign_id, whisper_id),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            "INSERT INTO play_campaign_whispers "
            "(campaign_id, whisper_id, from_character_id, to_character_id, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, whisper_id, from_character_id, to_character_id, text),
        )
        conn.commit()
        return True


def get_play_campaign_whispers(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT whisper_id, from_character_id, to_character_id, text "
            "FROM play_campaign_whispers WHERE campaign_id = ? ORDER BY rowid ASC",
            (campaign_id,),
        ).fetchall()
        return [_whisper_row_to_dict(row) for row in rows]


# -- play: character sheet -------------------------------------------------

def get_play_campaign_character_sheet(campaign_id, character_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT character_id, owner, name, class, level, hp_max, dex_modifier "
            "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "character_id": row["character_id"],
            "owner": row["owner"],
            "name": row["name"],
            "class": row["class"],
            "level": row["level"],
            "hp_max": row["hp_max"],
            "dex_modifier": row["dex_modifier"],
        }


# -- play: rate events -------------------------------------------------

def create_play_campaign_rate_event(campaign_id, event_id, actor, limit):
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_rate_events WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if existing is not None:
            return {"status": "duplicate"}
        count = conn.execute(
            "SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?",
            (campaign_id, actor),
        ).fetchone()[0]
        if count >= limit:
            conn.execute(
                "INSERT INTO play_campaign_rate_rejections (campaign_id) VALUES (?)",
                (campaign_id,),
            )
            conn.commit()
            return {"status": "limited", "remaining": 0}
        conn.execute(
            "INSERT INTO play_campaign_rate_events (campaign_id, event_id, actor) VALUES (?, ?, ?)",
            (campaign_id, event_id, actor),
        )
        conn.commit()
        return {"status": "ok", "remaining": limit - count - 1}


def get_play_campaign_rate_events(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT event_id, actor FROM play_campaign_rate_events "
            "WHERE campaign_id = ? ORDER BY rowid ASC",
            (campaign_id,),
        ).fetchall()
        return [{"event_id": row["event_id"], "actor": row["actor"]} for row in rows]


def get_play_campaign_rate_event_remaining(campaign_id, actor, limit):
    with db_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?",
            (campaign_id, actor),
        ).fetchone()[0]
        return max(0, limit - count)


# -- play: metrics -------------------------------------------------------

def get_play_campaign_metrics(campaign_id):
    with db_conn() as conn:
        accepted_rate_events = conn.execute(
            "SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        rejected_rate_events = conn.execute(
            "SELECT COUNT(*) FROM play_campaign_rate_rejections WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        projection_events = conn.execute(
            "SELECT COUNT(*) FROM play_campaign_projection_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0]
        return {
            "accepted_rate_events": accepted_rate_events,
            "rejected_rate_events": rejected_rate_events,
            "projection_events": projection_events,
            "uptime_ticks": 1,
        }


# -- play: deterministic replay -------------------------------------------

def create_play_campaign_replay_event(campaign_id, event_id, kind, text):
    """Append a replay event, assigning the next sequence for this campaign.

    Returns None if `event_id` already exists in this campaign's replay
    stream (caller should treat this as a 409 conflict without mutation).
    """
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_replay_events "
            "WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if existing is not None:
            return None
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS m FROM play_campaign_replay_events "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = row["m"] + 1
        conn.execute(
            "INSERT INTO play_campaign_replay_events "
            "(campaign_id, sequence, event_id, kind, text) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, event_id, kind, text),
        )
        conn.commit()
        return sequence


def get_play_campaign_replay_state(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT event_id, text FROM play_campaign_replay_events "
            "WHERE campaign_id = ? ORDER BY sequence ASC",
            (campaign_id,),
        ).fetchall()
        event_ids = [row["event_id"] for row in rows]
        story = "".join(row["text"] for row in rows)
        digest = ",".join(event_ids) + "|" + story
        return {"story": story, "event_ids": event_ids, "digest": digest}


# -- play: load-safe event feed -------------------------------------------

def create_play_campaign_feed_event(campaign_id, event_id, text):
    """Append a feed event, assigning the next sequence for this campaign.

    Returns None if `event_id` already exists in this campaign's feed
    (caller should treat this as a 409 conflict without mutation).
    """
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_feed_events "
            "WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if existing is not None:
            return None
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS m FROM play_campaign_feed_events "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = row["m"] + 1
        conn.execute(
            "INSERT INTO play_campaign_feed_events "
            "(campaign_id, sequence, event_id, text) VALUES (?, ?, ?, ?)",
            (campaign_id, sequence, event_id, text),
        )
        conn.commit()
        return sequence


def get_play_campaign_feed_events(campaign_id, cursor, limit):
    """Return up to `limit` feed events starting at zero-based `cursor`.

    Read-only: never mutates the feed, so concurrent appends between reads
    can't shift already-returned events.
    """
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT event_id, text, sequence FROM play_campaign_feed_events "
            "WHERE campaign_id = ? ORDER BY sequence ASC LIMIT ? OFFSET ?",
            (campaign_id, limit, cursor),
        ).fetchall()
        events = [
            {"event_id": row["event_id"], "text": row["text"], "sequence": row["sequence"]}
            for row in rows
        ]
        return events


# -- play: rng ledger -----------------------------------------------------

def create_play_campaign_rng_seed(campaign_id, seed):
    """Configure the campaign's RNG seed.

    Returns None if a seed is already configured (caller should treat this
    as a 409 conflict without mutation).
    """
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_rng_seeds WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if existing is not None:
            return None
        conn.execute(
            "INSERT INTO play_campaign_rng_seeds (campaign_id, seed) VALUES (?, ?)",
            (campaign_id, seed),
        )
        conn.commit()
        return seed


def get_play_campaign_rng_seed(campaign_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        return row["seed"] if row is not None else None


def create_play_campaign_rng_roll(campaign_id, roll_id, sides):
    """Append an RNG roll, assigning the next sequence for this campaign.

    Returns None if no seed is configured. Returns "duplicate" if `roll_id`
    already exists in this campaign's ledger (caller should treat this as a
    409 conflict without mutation).
    """
    with DB_LOCK, db_conn() as conn:
        seed_row = conn.execute(
            "SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if seed_row is None:
            return None
        seed = seed_row["seed"]
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_rng_rolls WHERE campaign_id = ? AND roll_id = ?",
            (campaign_id, roll_id),
        ).fetchone()
        if existing is not None:
            return "duplicate"
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS m FROM play_campaign_rng_rolls "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = row["m"] + 1
        message = f"{seed}|{sequence}|{roll_id}|{sides}"
        acc = 0
        for b in message.encode("utf-8"):
            acc = (acc * 31 + b) % (2 ** 32)
        result = (acc % sides) + 1
        conn.execute(
            "INSERT INTO play_campaign_rng_rolls "
            "(campaign_id, sequence, roll_id, sides, result) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, roll_id, sides, result),
        )
        conn.commit()
        return {
            "roll_id": roll_id,
            "sides": sides,
            "result": result,
            "sequence": sequence,
        }


def get_play_campaign_rng_ledger(campaign_id):
    with db_conn() as conn:
        seed_row = conn.execute(
            "SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        seed = seed_row["seed"] if seed_row is not None else None
        rows = conn.execute(
            "SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls "
            "WHERE campaign_id = ? ORDER BY sequence ASC",
            (campaign_id,),
        ).fetchall()
        rolls = [
            {
                "roll_id": row["roll_id"],
                "sides": row["sides"],
                "result": row["result"],
                "sequence": row["sequence"],
            }
            for row in rows
        ]
        return {"seed": seed, "rolls": rolls}


# -- play: moderation reports ---------------------------------------------

def _moderation_report_row_to_dict(row):
    result = {
        "report_id": row["report_id"],
        "target_id": row["target_id"],
        "reason": row["reason"],
        "status": row["status"],
        "reporter": row["reporter"],
        "sequence": row["sequence"],
    }
    if row["status"] == "resolved":
        result["action"] = row["action"]
        result["note"] = row["note"]
        result["resolver"] = row["resolver"]
    return result


def create_play_campaign_moderation_report(campaign_id, report_id, target_id, reason, reporter):
    """Append an open moderation report, assigning the next sequence.

    Returns "duplicate" if `report_id` already exists in this campaign.
    """
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_moderation_reports "
            "WHERE campaign_id = ? AND report_id = ?",
            (campaign_id, report_id),
        ).fetchone()
        if existing is not None:
            return "duplicate"
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS m FROM play_campaign_moderation_reports "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = row["m"] + 1
        conn.execute(
            "INSERT INTO play_campaign_moderation_reports "
            "(campaign_id, sequence, report_id, target_id, reason, status, reporter) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, sequence, report_id, target_id, reason, "open", reporter),
        )
        conn.commit()
        return {
            "report_id": report_id,
            "target_id": target_id,
            "reason": reason,
            "status": "open",
            "reporter": reporter,
            "sequence": sequence,
        }


def get_play_campaign_moderation_reports(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT report_id, target_id, reason, status, reporter, sequence, "
            "action, note, resolver FROM play_campaign_moderation_reports "
            "WHERE campaign_id = ? ORDER BY sequence ASC",
            (campaign_id,),
        ).fetchall()
        return [_moderation_report_row_to_dict(row) for row in rows]


def resolve_play_campaign_moderation_report(campaign_id, report_id, action, note, resolver):
    """Transition an open report to resolved.

    Returns None if the report does not exist. Returns "resolved" if the
    report is already resolved (caller should treat this as a 409 conflict
    without mutation).
    """
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT report_id, target_id, reason, status, reporter, sequence, "
            "action, note, resolver FROM play_campaign_moderation_reports "
            "WHERE campaign_id = ? AND report_id = ?",
            (campaign_id, report_id),
        ).fetchone()
        if row is None:
            return None
        if row["status"] == "resolved":
            return "resolved"
        conn.execute(
            "UPDATE play_campaign_moderation_reports "
            "SET status = ?, action = ?, note = ?, resolver = ? "
            "WHERE campaign_id = ? AND report_id = ?",
            ("resolved", action, note, resolver, campaign_id, report_id),
        )
        conn.commit()
        return {
            "report_id": row["report_id"],
            "target_id": row["target_id"],
            "reason": row["reason"],
            "status": "resolved",
            "reporter": row["reporter"],
            "sequence": row["sequence"],
            "action": action,
            "note": note,
            "resolver": resolver,
        }


# -- play: safety boundaries -----------------------------------------------

def replace_play_campaign_safety_boundaries(campaign_id, blocked_tags):
    """Atomically replace the campaign's blocked_tags list.

    `blocked_tags` must already be validated by the caller. Returns the
    sorted list as stored.
    """
    sorted_tags = sorted(blocked_tags)
    with DB_LOCK, db_conn() as conn:
        conn.execute(
            "INSERT INTO play_campaign_safety_boundaries (campaign_id, blocked_tags) "
            "VALUES (?, ?) "
            "ON CONFLICT(campaign_id) DO UPDATE SET blocked_tags = excluded.blocked_tags",
            (campaign_id, json.dumps(sorted_tags)),
        )
        conn.commit()
        return sorted_tags


def get_play_campaign_safety_boundaries(campaign_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT blocked_tags FROM play_campaign_safety_boundaries "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return []
        return json.loads(row["blocked_tags"])


def create_play_campaign_safety_check(campaign_id, event_id, kind, text, tags):
    """Append an accepted safety event, assigning the next sequence.

    Returns "duplicate" if `event_id` was already accepted in this campaign.
    Returns "blocked" if any submitted tag is in the current blocked_tags.
    """
    with DB_LOCK, db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM play_campaign_safety_events "
            "WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if existing is not None:
            return "duplicate"

        boundary_row = conn.execute(
            "SELECT blocked_tags FROM play_campaign_safety_boundaries "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        blocked_tags = json.loads(boundary_row["blocked_tags"]) if boundary_row else []
        if any(tag in blocked_tags for tag in tags):
            return "blocked"

        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS m FROM play_campaign_safety_events "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        sequence = row["m"] + 1
        conn.execute(
            "INSERT INTO play_campaign_safety_events "
            "(campaign_id, sequence, event_id, kind, text, tags) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, sequence, event_id, kind, text, json.dumps(tags)),
        )
        conn.commit()
        return {
            "event_id": event_id,
            "kind": kind,
            "text": text,
            "tags": tags,
            "sequence": sequence,
        }


def get_play_campaign_safety_events(campaign_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT event_id, kind, text, tags, sequence "
            "FROM play_campaign_safety_events "
            "WHERE campaign_id = ? ORDER BY sequence ASC",
            (campaign_id,),
        ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "kind": row["kind"],
                "text": row["text"],
                "tags": json.loads(row["tags"]),
                "sequence": row["sequence"],
            }
            for row in rows
        ]


CANONICAL_FIXTURE_STATE = {
    "fixture_id": "canonical-v1",
    "status": "seeded",
    "characters": [
        {"character_id": "fixture-hero", "name": "Ari", "class": "fighter"},
        {"character_id": "fixture-mage", "name": "Bea", "class": "wizard"},
    ],
    "story": "The lantern is lit.",
    "event_ids": ["fixture-event-1", "fixture-event-2"],
}


def seed_play_campaign_fixture(campaign_id, fixture_id):
    """Atomically create the canonical fixture state if not already seeded.

    Idempotent: repeating the same fixture_id returns the existing state
    without duplicating anything.
    """
    with DB_LOCK, db_conn() as conn:
        row = conn.execute(
            "SELECT state FROM play_campaign_fixture_seeds WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if row is not None:
            return json.loads(row["state"])

        state = dict(CANONICAL_FIXTURE_STATE)
        conn.execute(
            "INSERT INTO play_campaign_fixture_seeds (campaign_id, fixture_id, state) "
            "VALUES (?, ?, ?)",
            (campaign_id, fixture_id, json.dumps(state)),
        )
        conn.commit()
        return state


def get_play_campaign_fixture_state(campaign_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT state FROM play_campaign_fixture_seeds WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["state"])
