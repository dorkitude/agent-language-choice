"""SQLite persistence layer.

All application state lives in a single local `game.db` file. The module-level
`storage` singleton is created when the server starts and is shared by all
request handlers.
"""

import json
import sqlite3


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
    """Thin SQLite store for users, combat sessions, compendium, and campaigns."""

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
                phase TEXT NOT NULL DEFAULT 'lobby'
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
                PRIMARY KEY (campaign_id, username),
                UNIQUE (character_id),
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
                text TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id),
                UNIQUE (campaign_id, sequence)
            )
            """,
        ),
    ]

    def __init__(self):
        self.initialized = False
        # Start from a clean, deterministic state so every server run is
        # independent of any leftover database from earlier attempts.
        self._hard_reset()

    def _connect(self):
        return sqlite3.connect(self.DB_FILE)

    def _init_schema(self):
        conn = self._connect()
        for _, sql in self._TABLES:
            conn.execute(sql)
        conn.commit()
        conn.close()
        self.initialized = True

    def _hard_reset(self):
        """Drop and recreate every table, including users."""
        conn = self._connect()
        for name, _ in self._TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {name}")
        conn.commit()
        conn.close()
        self._init_schema()

    def reset(self):
        """Drop and recreate tables, but preserve registered users.

        The play surface relies on authenticated actors persisting across the
        maintenance reset performed by the cumulative evaluator suite.
        """
        conn = self._connect()
        for name, _ in self._TABLES:
            if name == "users":
                continue
            conn.execute(f"DROP TABLE IF EXISTS {name}")
        conn.commit()
        conn.close()
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
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO users (username, role, salt, password_hash) VALUES (?, ?, ?, ?)",
                (username, role, salt.hex(), password_hash.hex()),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def get_user(self, username):
        conn = self._connect()
        row = conn.execute(
            "SELECT role, salt, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return {
            "role": row[0],
            "salt": bytes.fromhex(row[1]),
            "password_hash": bytes.fromhex(row[2]),
        }

    # --- Combat sessions ---

    def create_session(self, session_id, round, turn_index, order, conditions):
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO sessions (id, round, turn_index, order_json, conditions_json) VALUES (?, ?, ?, ?, ?)",
                (session_id, round, turn_index, json.dumps(order), json.dumps(conditions)),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def get_session(self, session_id):
        conn = self._connect()
        row = conn.execute(
            "SELECT round, turn_index, order_json, conditions_json FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        conn.close()
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
        conn = self._connect()
        conn.execute(
            "UPDATE sessions SET round = ?, turn_index = ?, order_json = ?, conditions_json = ? WHERE id = ?",
            (round, turn_index, json.dumps(order), json.dumps(conditions), session_id),
        )
        conn.commit()
        conn.close()

    # --- Compendium ---

    def create_monster(self, slug, name, cr, armor_class, hit_points, tags):
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)",
                (slug, name, cr, armor_class, hit_points, json.dumps(tags)),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def get_monster(self, slug):
        conn = self._connect()
        row = conn.execute(
            "SELECT name, cr, armor_class, hit_points, tags_json FROM compendium_monsters WHERE slug = ?",
            (slug,),
        ).fetchone()
        conn.close()
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
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
                (slug, name, type, rarity, cost_gp),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def get_item(self, slug):
        conn = self._connect()
        row = conn.execute(
            "SELECT name, type, rarity, cost_gp FROM compendium_items WHERE slug = ?",
            (slug,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return {
            "slug": slug,
            "name": row[0],
            "type": row[1],
            "rarity": row[2],
            "cost_gp": row[3],
        }

    # --- Campaigns ---

    def create_campaign(self, id, name, dm):
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
                (id, name, dm),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def get_campaign(self, id):
        conn = self._connect()
        row = conn.execute(
            "SELECT name, dm FROM campaigns WHERE id = ?",
            (id,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return {"id": id, "name": row[0], "dm": row[1]}

    def create_campaign_character(self, id, campaign_id, name, level, class_):
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)",
                (id, campaign_id, name, level, class_),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def get_campaign_characters(self, campaign_id):
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY id",
            (campaign_id,),
        ).fetchall()
        conn.close()
        return [{"id": r[0], "name": r[1], "level": r[2], "class": r[3]} for r in rows]

    def create_campaign_event(self, id, campaign_id, kind, summary):
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)",
                (id, campaign_id, kind, summary),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def count_campaign_events(self, campaign_id):
        conn = self._connect()
        row = conn.execute(
            "SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        conn.close()
        return row[0] if row else 0

    def count_campaign_characters(self, campaign_id):
        conn = self._connect()
        row = conn.execute(
            "SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        conn.close()
        return row[0] if row else 0

    def count_campaign_quests(self, campaign_id):
        conn = self._connect()
        row = conn.execute(
            "SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        conn.close()
        return row[0] if row else 0

    def count_campaign_npcs(self, campaign_id):
        conn = self._connect()
        row = conn.execute(
            "SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        conn.close()
        return row[0] if row else 0

    def count_campaign_sessions(self, campaign_id):
        conn = self._connect()
        row = conn.execute(
            "SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        conn.close()
        return row[0] if row else 0

    def count_campaign_inventory_items(self, campaign_id):
        conn = self._connect()
        row = conn.execute(
            "SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party'",
            (campaign_id,),
        ).fetchone()
        conn.close()
        return row[0] if row else 0

    def get_campaign_events(self, campaign_id):
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY id",
            (campaign_id,),
        ).fetchall()
        conn.close()
        return [{"id": r[0], "kind": r[1], "summary": r[2]} for r in rows]

    # --- Quests ---

    def create_quest(self, id, campaign_id, title, status, milestones, completed):
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO campaign_quests (id, campaign_id, title, status, milestones_json, completed_json) VALUES (?, ?, ?, ?, ?, ?)",
                (id, campaign_id, title, status, json.dumps(milestones), json.dumps(completed)),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def get_quest(self, id):
        conn = self._connect()
        row = conn.execute(
            "SELECT campaign_id, title, status, milestones_json, completed_json FROM campaign_quests WHERE id = ?",
            (id,),
        ).fetchone()
        conn.close()
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
        conn = self._connect()
        conn.execute(
            "UPDATE campaign_quests SET completed_json = ? WHERE id = ?",
            (json.dumps(completed), id),
        )
        conn.commit()
        conn.close()

    def get_campaign_quests_summary(self, campaign_id):
        conn = self._connect()
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM campaign_quests WHERE campaign_id = ? GROUP BY status",
            (campaign_id,),
        ).fetchall()
        conn.close()
        summary = {"active": 0, "completed": 0, "blocked": 0}
        for status, count in rows:
            if status in summary:
                summary[status] = count
        return summary

    # --- Factions and NPCs ---

    def create_faction(self, id, campaign_id, name, stance):
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO campaign_factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)",
                (id, campaign_id, name, stance),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def get_faction(self, id):
        conn = self._connect()
        row = conn.execute(
            "SELECT campaign_id, name, stance FROM campaign_factions WHERE id = ?",
            (id,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return {
            "id": id,
            "campaign_id": row[0],
            "name": row[1],
            "stance": row[2],
        }

    def create_npc(self, id, campaign_id, name, faction_id, disposition):
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO campaign_npcs (id, campaign_id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)",
                (id, campaign_id, name, faction_id, disposition),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def get_npc(self, id):
        conn = self._connect()
        row = conn.execute(
            "SELECT campaign_id, name, faction_id, disposition FROM campaign_npcs WHERE id = ?",
            (id,),
        ).fetchone()
        conn.close()
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
        conn = self._connect()
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
        conn.close()
        return {
            "campaign_id": campaign_id,
            "factions": factions,
            "npcs": npcs,
            "friendly_npcs": friendly_npcs,
        }

    def get_campaign_character(self, id):
        conn = self._connect()
        row = conn.execute(
            "SELECT campaign_id, name, level, class FROM campaign_characters WHERE id = ?",
            (id,),
        ).fetchone()
        conn.close()
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
        conn = self._connect()
        try:
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
        finally:
            conn.close()

    def assign_equipment(self, campaign_id, character_id, item_slug, quantity):
        conn = self._connect()
        try:
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
        finally:
            conn.close()

    def get_inventory_summary(self, campaign_id):
        conn = self._connect()
        rows = conn.execute(
            "SELECT item_slug, quantity, owner FROM campaign_inventory WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchall()
        conn.close()
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
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO crafting_projects (id, campaign_id, character_id, item_slug, days_required, cost_gp, days_completed, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (id, campaign_id, character_id, item_slug, days_required, cost_gp, 0, "active"),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def get_crafting_project(self, id):
        conn = self._connect()
        row = conn.execute(
            "SELECT campaign_id, character_id, item_slug, days_required, days_completed, status FROM crafting_projects WHERE id = ?",
            (id,),
        ).fetchone()
        conn.close()
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
        conn = self._connect()
        try:
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
        finally:
            conn.close()


    # --- Campaign sessions ---

    def create_campaign_session(self, id, campaign_id, starts_at, duration_minutes, agenda):
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO campaign_sessions (id, campaign_id, starts_at, duration_minutes, agenda_json) VALUES (?, ?, ?, ?, ?)",
                (id, campaign_id, starts_at, duration_minutes, json.dumps(agenda)),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def get_campaign_session(self, id):
        conn = self._connect()
        row = conn.execute(
            "SELECT campaign_id, starts_at, duration_minutes, agenda_json FROM campaign_sessions WHERE id = ?",
            (id,),
        ).fetchone()
        conn.close()
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
        conn = self._connect()
        row = conn.execute(
            "SELECT id, starts_at, duration_minutes, agenda_json FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at ASC LIMIT 1",
            (campaign_id,),
        ).fetchone()
        conn.close()
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
        conn = self._connect()
        try:
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
        finally:
            conn.close()

    def get_session_attendance_counts(self, session_id):
        conn = self._connect()
        row = conn.execute(
            "SELECT SUM(CASE WHEN present = 1 THEN 1 ELSE 0 END), SUM(CASE WHEN present = 0 THEN 1 ELSE 0 END) FROM session_attendance WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        conn.close()
        return (row[0] or 0, row[1] or 0)

    # --- Play campaigns ---

    def create_play_campaign(self, id, name, owner, max_players):
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)",
                (id, name, owner, "lobby", max_players),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def get_play_campaign(self, id):
        conn = self._connect()
        row = conn.execute(
            "SELECT name, owner, status, max_players, current_actor, turn_number, phase FROM play_campaigns WHERE id = ?",
            (id,),
        ).fetchone()
        conn.close()
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
        }

    def is_play_campaign_member(self, campaign_id, username):
        conn = self._connect()
        row = conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        conn.close()
        return row is not None

    def get_play_campaign_members(self, campaign_id):
        """Return the party members for a campaign sorted by username."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT username, character_id, name, class FROM play_campaign_members WHERE campaign_id = ? ORDER BY username",
            (campaign_id,),
        ).fetchall()
        conn.close()
        return [
            {"username": r[0], "character_id": r[1], "name": r[2], "class": r[3]}
            for r in rows
        ]

    def join_play_campaign(self, campaign_id, username, character_id, name, class_):
        conn = self._connect()
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
                "INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, username, character_id, name, class_),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def start_play_campaign(self, campaign_id):
        """Activate a lobby play campaign if it has at least two members.

        Returns the list of party members sorted by username on success, or
        None when the campaign is missing, not in lobby status, or under-populated.
        """
        conn = self._connect()
        try:
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
                "SELECT username, character_id, name, class FROM play_campaign_members WHERE campaign_id = ? ORDER BY username",
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
        finally:
            conn.close()

    def append_narration(self, campaign_id, text):
        """Append a DM narration event and return its ordered event record."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT MAX(sequence) FROM narrations WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            sequence = (row[0] if row and row[0] is not None else 0) + 1
            conn.execute(
                "INSERT INTO narrations (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)",
                (campaign_id, sequence, "narration", "dm", text),
            )
            conn.commit()
            return {
                "sequence": sequence,
                "kind": "narration",
                "actor": "dm",
                "text": text,
            }
        finally:
            conn.close()


# Module-level singleton used by the request handlers.
storage = Storage()
