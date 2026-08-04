package dnd.storage;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import dnd.json.JsonUtils;
import dnd.model.Combatant;
import dnd.model.CombatSession;
import dnd.model.Condition;
import dnd.model.User;

/**
 * SQLite-backed persistence layer.
 * All operations are serialized on a single lock because the backing store
 * is an external sqlite3 process per query. The schema is created lazily by
 * init() and recreated by reset().
 */
public class Storage {
    private final String dbPath;
    private final Object lock = new Object();
    private boolean initialized = false;

    public Storage(String dbPath) {
        this.dbPath = dbPath;
    }

    public void init() {
        synchronized (lock) {
            execSql(
                "CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, role TEXT NOT NULL, salt TEXT NOT NULL, hash TEXT NOT NULL);",
                "CREATE TABLE IF NOT EXISTS combat_sessions (id TEXT PRIMARY KEY, round INTEGER NOT NULL, turn_index INTEGER NOT NULL);",
                "CREATE TABLE IF NOT EXISTS combatants (session_id TEXT NOT NULL, name TEXT NOT NULL, score INTEGER NOT NULL, dex INTEGER NOT NULL, roll INTEGER NOT NULL, sort_order INTEGER NOT NULL, PRIMARY KEY (session_id, name));",
                "CREATE TABLE IF NOT EXISTS conditions (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, target TEXT NOT NULL, condition TEXT NOT NULL, remaining_rounds INTEGER NOT NULL);",
                "CREATE TABLE IF NOT EXISTS monsters (slug TEXT PRIMARY KEY, name TEXT NOT NULL, cr TEXT NOT NULL, armor_class INTEGER NOT NULL, hit_points INTEGER NOT NULL);",
                "CREATE TABLE IF NOT EXISTS monster_tags (monster_slug TEXT NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (monster_slug, tag));",
                "CREATE TABLE IF NOT EXISTS items (slug TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, rarity TEXT NOT NULL, cost_gp INTEGER NOT NULL);",
                "CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, dm TEXT NOT NULL);",
                "CREATE TABLE IF NOT EXISTS campaign_characters (id TEXT NOT NULL, campaign_id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL, class TEXT NOT NULL, PRIMARY KEY (id, campaign_id));",
                "CREATE TABLE IF NOT EXISTS campaign_events (id TEXT NOT NULL, campaign_id TEXT NOT NULL, kind TEXT NOT NULL, summary TEXT, PRIMARY KEY (id, campaign_id));",
                "CREATE TABLE IF NOT EXISTS quests (id TEXT NOT NULL, campaign_id TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (id, campaign_id));",
                "CREATE TABLE IF NOT EXISTS quest_milestones (quest_id TEXT NOT NULL, campaign_id TEXT NOT NULL, milestone TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (quest_id, campaign_id, milestone));",
                "CREATE TABLE IF NOT EXISTS factions (id TEXT NOT NULL, campaign_id TEXT NOT NULL, name TEXT NOT NULL, stance TEXT NOT NULL, PRIMARY KEY (id, campaign_id));",
                "CREATE TABLE IF NOT EXISTS npcs (id TEXT NOT NULL, campaign_id TEXT NOT NULL, name TEXT NOT NULL, faction_id TEXT NOT NULL, disposition INTEGER NOT NULL, PRIMARY KEY (id, campaign_id));",
                "CREATE TABLE IF NOT EXISTS campaign_inventory (campaign_id TEXT NOT NULL, item_slug TEXT NOT NULL, owner TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, item_slug, owner));",
                "CREATE TABLE IF NOT EXISTS character_equipment (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, item_slug));",
                "CREATE TABLE IF NOT EXISTS downtime_crafting_projects (id TEXT NOT NULL, campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, days_required INTEGER NOT NULL, days_completed INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, PRIMARY KEY (id, campaign_id));",
                "CREATE TABLE IF NOT EXISTS sessions (id TEXT NOT NULL, campaign_id TEXT NOT NULL, starts_at TEXT NOT NULL, duration_minutes INTEGER NOT NULL, agenda_count INTEGER NOT NULL, PRIMARY KEY (id, campaign_id));",
                "CREATE TABLE IF NOT EXISTS session_attendance (session_id TEXT NOT NULL, campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, present INTEGER NOT NULL, PRIMARY KEY (session_id, campaign_id, character_id));",
                "CREATE TABLE IF NOT EXISTS play_campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL, status TEXT NOT NULL, max_players INTEGER NOT NULL);"
            );
            initialized = true;
        }
    }

    public void reset() {
        synchronized (lock) {
            execSql(
                "DROP TABLE IF EXISTS items;",
                "DROP TABLE IF EXISTS monster_tags;",
                "DROP TABLE IF EXISTS monsters;",
                "DROP TABLE IF EXISTS conditions;",
                "DROP TABLE IF EXISTS combatants;",
                "DROP TABLE IF EXISTS combat_sessions;",
                "DROP TABLE IF EXISTS users;",
                "DROP TABLE IF EXISTS campaigns;",
                "DROP TABLE IF EXISTS campaign_characters;",
                "DROP TABLE IF EXISTS campaign_events;",
                "DROP TABLE IF EXISTS quest_milestones;",
                "DROP TABLE IF EXISTS quests;",
                "DROP TABLE IF EXISTS npcs;",
                "DROP TABLE IF EXISTS factions;",
                "DROP TABLE IF EXISTS character_equipment;",
                "DROP TABLE IF EXISTS campaign_inventory;",
                "DROP TABLE IF EXISTS downtime_crafting_projects;",
                "DROP TABLE IF EXISTS session_attendance;",
                "DROP TABLE IF EXISTS sessions;",
                "DROP TABLE IF EXISTS play_campaigns;"
            );
            init();
        }
    }

    public Map<String, Object> status() {
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("driver", "sqlite");
        res.put("schema_version", 1);
        res.put("initialized", initialized);
        return res;
    }

    public User getUser(String username) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT username, role, salt, hash FROM users WHERE username = " + quote(username) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            return new User((String) row.get("username"), (String) row.get("role"), (String) row.get("salt"), (String) row.get("hash"));
        }
    }

    public boolean insertUser(User user) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "INSERT INTO users (username, role, salt, hash) VALUES (" + quote(user.username) + ", " + quote(user.role) + ", " + quote(user.salt) + ", " + quote(user.hash) + ");",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                if (e.getMessage() != null && e.getMessage().contains("UNIQUE constraint failed")) {
                    return false;
                }
                throw e;
            }
        }
    }

    public boolean insertCombatSession(CombatSession session) {
        synchronized (lock) {
            try {
                List<String> sqls = new ArrayList<>();
                sqls.add("BEGIN;");
                sqls.add("INSERT INTO combat_sessions (id, round, turn_index) VALUES (" + quote(session.id) + ", " + session.round + ", " + session.turnIndex + ");");
                for (int i = 0; i < session.order.size(); i++) {
                    Combatant c = session.order.get(i);
                    sqls.add("INSERT INTO combatants (session_id, name, score, dex, roll, sort_order) VALUES (" + quote(session.id) + ", " + quote(c.name) + ", " + c.score + ", " + c.dex + ", " + c.roll + ", " + i + ");");
                }
                sqls.add("COMMIT;");
                execSql(sqls.toArray(new String[0]));
                return true;
            } catch (RuntimeException e) {
                if (e.getMessage() != null && e.getMessage().contains("UNIQUE constraint failed")) {
                    return false;
                }
                throw e;
            }
        }
    }

    public CombatSession getCombatSession(String id) {
        synchronized (lock) {
            List<Map<String, Object>> sessionRows = query("SELECT id, round, turn_index FROM combat_sessions WHERE id = " + quote(id) + ";");
            if (sessionRows.isEmpty()) return null;
            Map<String, Object> sessionRow = sessionRows.get(0);

            List<Combatant> combatants = new ArrayList<>();
            List<Map<String, Object>> combatantRows = query("SELECT name, score, dex, roll FROM combatants WHERE session_id = " + quote(id) + " ORDER BY sort_order;");
            for (Map<String, Object> row : combatantRows) {
                combatants.add(new Combatant((String) row.get("name"), JsonUtils.toInt(row.get("score")), JsonUtils.toInt(row.get("dex")), JsonUtils.toInt(row.get("roll"))));
            }

            CombatSession session = new CombatSession((String) sessionRow.get("id"), combatants);
            session.round = JsonUtils.toInt(sessionRow.get("round"));
            session.turnIndex = JsonUtils.toInt(sessionRow.get("turn_index"));

            List<Map<String, Object>> conditionRows = query("SELECT target, condition, remaining_rounds FROM conditions WHERE session_id = " + quote(id) + " ORDER BY id;");
            for (Map<String, Object> row : conditionRows) {
                String target = (String) row.get("target");
                session.conditions.computeIfAbsent(target, k -> new ArrayList<>()).add(new Condition((String) row.get("condition"), JsonUtils.toInt(row.get("remaining_rounds"))));
            }

            return session;
        }
    }

    public void addCondition(String sessionId, String target, String condition, int duration) {
        synchronized (lock) {
            execSql("INSERT INTO conditions (session_id, target, condition, remaining_rounds) VALUES (" + quote(sessionId) + ", " + quote(target) + ", " + quote(condition) + ", " + duration + ");");
        }
    }

    public void advanceCombatSession(CombatSession session, Combatant active) {
        synchronized (lock) {
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("UPDATE combat_sessions SET round = " + session.round + ", turn_index = " + session.turnIndex + " WHERE id = " + quote(session.id) + ";");
            sqls.add("UPDATE conditions SET remaining_rounds = remaining_rounds - 1 WHERE session_id = " + quote(session.id) + " AND target = " + quote(active.name) + ";");
            sqls.add("DELETE FROM conditions WHERE session_id = " + quote(session.id) + " AND target = " + quote(active.name) + " AND remaining_rounds <= 0;");
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));
        }
    }

    public boolean insertMonster(String slug, String name, String cr, int armorClass, int hitPoints, List<String> tags) {
        synchronized (lock) {
            try {
                List<String> sqls = new ArrayList<>();
                sqls.add("BEGIN;");
                sqls.add("INSERT INTO monsters (slug, name, cr, armor_class, hit_points) VALUES (" + quote(slug) + ", " + quote(name) + ", " + quote(cr) + ", " + armorClass + ", " + hitPoints + ");");
                Set<String> seen = new HashSet<>();
                for (String tag : tags) {
                    if (!seen.add(tag)) continue;
                    sqls.add("INSERT INTO monster_tags (monster_slug, tag) VALUES (" + quote(slug) + ", " + quote(tag) + ");");
                }
                sqls.add("COMMIT;");
                execSql(sqls.toArray(new String[0]));
                return true;
            } catch (RuntimeException e) {
                if (e.getMessage() != null && e.getMessage().contains("UNIQUE constraint failed")) {
                    return false;
                }
                throw e;
            }
        }
    }

    public Map<String, Object> getMonster(String slug) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT slug, name, cr, armor_class, hit_points FROM monsters WHERE slug = " + quote(slug) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            List<String> tags = new ArrayList<>();
            List<Map<String, Object>> tagRows = query("SELECT tag FROM monster_tags WHERE monster_slug = " + quote(slug) + " ORDER BY rowid;");
            for (Map<String, Object> tr : tagRows) {
                tags.add((String) tr.get("tag"));
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("slug", row.get("slug"));
            res.put("name", row.get("name"));
            res.put("cr", row.get("cr"));
            res.put("armor_class", JsonUtils.toInt(row.get("armor_class")));
            res.put("hit_points", JsonUtils.toInt(row.get("hit_points")));
            res.put("tags", tags);
            return res;
        }
    }

    public boolean insertItem(String slug, String name, String type, String rarity, int costGp) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (" + quote(slug) + ", " + quote(name) + ", " + quote(type) + ", " + quote(rarity) + ", " + costGp + ");",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                if (e.getMessage() != null && e.getMessage().contains("UNIQUE constraint failed")) {
                    return false;
                }
                throw e;
            }
        }
    }

    public Map<String, Object> getItem(String slug) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = " + quote(slug) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("slug", row.get("slug"));
            res.put("name", row.get("name"));
            res.put("type", row.get("type"));
            res.put("rarity", row.get("rarity"));
            res.put("cost_gp", JsonUtils.toInt(row.get("cost_gp")));
            return res;
        }
    }

    public boolean insertCampaign(String id, String name, String dm) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "INSERT INTO campaigns (id, name, dm) VALUES (" + quote(id) + ", " + quote(name) + ", " + quote(dm) + ");",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                if (e.getMessage() != null && e.getMessage().contains("UNIQUE constraint failed")) {
                    return false;
                }
                throw e;
            }
        }
    }

    public Map<String, Object> getCampaign(String id) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, name, dm FROM campaigns WHERE id = " + quote(id) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", row.get("id"));
            res.put("name", row.get("name"));
            res.put("dm", row.get("dm"));
            return res;
        }
    }

    public boolean insertPlayCampaign(String id, String name, String owner, int maxPlayers) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (" + quote(id) + ", " + quote(name) + ", " + quote(owner) + ", 'lobby', " + maxPlayers + ");",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                if (e.getMessage() != null && e.getMessage().contains("UNIQUE constraint failed")) {
                    return false;
                }
                throw e;
            }
        }
    }

    public Map<String, Object> getPlayCampaign(String id) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, name, owner, status, max_players FROM play_campaigns WHERE id = " + quote(id) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", row.get("id"));
            res.put("name", row.get("name"));
            res.put("owner", row.get("owner"));
            res.put("status", row.get("status"));
            res.put("max_players", JsonUtils.toInt(row.get("max_players")));
            return res;
        }
    }

    public boolean insertCampaignCharacter(String campaignId, String id, String name, int level, String className) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (" + quote(id) + ", " + quote(campaignId) + ", " + quote(name) + ", " + level + ", " + quote(className) + ");",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                if (e.getMessage() != null && e.getMessage().contains("UNIQUE constraint failed")) {
                    return false;
                }
                throw e;
            }
        }
    }

    public List<Map<String, Object>> listCampaignCharacters(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = " + quote(campaignId) + " ORDER BY rowid;");
            List<Map<String, Object>> res = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                Map<String, Object> c = new LinkedHashMap<>();
                c.put("id", row.get("id"));
                c.put("name", row.get("name"));
                c.put("level", JsonUtils.toInt(row.get("level")));
                c.put("class", row.get("class"));
                res.add(c);
            }
            return res;
        }
    }

    public boolean insertCampaignEvent(String campaignId, String id, String kind, String summary) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (" + quote(id) + ", " + quote(campaignId) + ", " + quote(kind) + ", " + (summary == null ? "NULL" : quote(summary)) + ");",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                if (e.getMessage() != null && e.getMessage().contains("UNIQUE constraint failed")) {
                    return false;
                }
                throw e;
            }
        }
    }

    public int countCampaignEvents(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COUNT(*) AS c FROM campaign_events WHERE campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return 0;
            return JsonUtils.toInt(rows.get(0).get("c"));
        }
    }

    public int countCampaignCharacters(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COUNT(*) AS c FROM campaign_characters WHERE campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return 0;
            return JsonUtils.toInt(rows.get(0).get("c"));
        }
    }

    public int countQuests(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COUNT(*) AS c FROM quests WHERE campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return 0;
            return JsonUtils.toInt(rows.get(0).get("c"));
        }
    }

    public int countActiveQuests(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COUNT(*) AS c FROM quests WHERE campaign_id = " + quote(campaignId) + " AND status = 'active';");
            if (rows.isEmpty()) return 0;
            return JsonUtils.toInt(rows.get(0).get("c"));
        }
    }

    public int countSessions(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COUNT(*) AS c FROM sessions WHERE campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return 0;
            return JsonUtils.toInt(rows.get(0).get("c"));
        }
    }

    public int countInventoryItems(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COUNT(*) AS c FROM campaign_inventory WHERE campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return 0;
            return JsonUtils.toInt(rows.get(0).get("c"));
        }
    }

    public Map<String, Object> getLatestCampaignEvent(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, kind, summary FROM campaign_events WHERE campaign_id = " + quote(campaignId) + " ORDER BY rowid DESC LIMIT 1;");
            if (rows.isEmpty()) return null;
            return rows.get(0);
        }
    }

    public boolean insertQuest(String campaignId, String id, String title, String status, List<String> milestones) {
        synchronized (lock) {
            try {
                List<String> sqls = new ArrayList<>();
                sqls.add("BEGIN;");
                sqls.add("INSERT INTO quests (id, campaign_id, title, status) VALUES (" + quote(id) + ", " + quote(campaignId) + ", " + quote(title) + ", " + quote(status) + ");");
                Set<String> seen = new HashSet<>();
                for (String milestone : milestones) {
                    if (!seen.add(milestone)) continue;
                    sqls.add("INSERT INTO quest_milestones (quest_id, campaign_id, milestone, completed) VALUES (" + quote(id) + ", " + quote(campaignId) + ", " + quote(milestone) + ", 0);");
                }
                sqls.add("COMMIT;");
                execSql(sqls.toArray(new String[0]));
                return true;
            } catch (RuntimeException e) {
                if (e.getMessage() != null && e.getMessage().contains("UNIQUE constraint failed")) {
                    return false;
                }
                throw e;
            }
        }
    }

    public Map<String, Object> getQuest(String campaignId, String id) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, title, status FROM quests WHERE id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            List<String> milestones = new ArrayList<>();
            Set<String> completed = new HashSet<>();
            List<Map<String, Object>> milestoneRows = query("SELECT milestone, completed FROM quest_milestones WHERE quest_id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + " ORDER BY rowid;");
            for (Map<String, Object> mr : milestoneRows) {
                String milestone = (String) mr.get("milestone");
                milestones.add(milestone);
                if (JsonUtils.toInt(mr.get("completed")) != 0) {
                    completed.add(milestone);
                }
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", row.get("id"));
            res.put("title", row.get("title"));
            res.put("status", row.get("status"));
            res.put("milestones", milestones);
            res.put("completed", completed);
            return res;
        }
    }

    public boolean updateQuestProgress(String campaignId, String id, List<String> completed) {
        synchronized (lock) {
            try {
                List<String> sqls = new ArrayList<>();
                sqls.add("BEGIN;");
                for (String milestone : completed) {
                    sqls.add("UPDATE quest_milestones SET completed = 1 WHERE quest_id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + " AND milestone = " + quote(milestone) + ";");
                }
                sqls.add("COMMIT;");
                execSql(sqls.toArray(new String[0]));

                List<Map<String, Object>> rows = query("SELECT COUNT(*) AS total FROM quest_milestones WHERE quest_id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + ";");
                int total = JsonUtils.toInt(rows.get(0).get("total"));
                rows = query("SELECT COUNT(*) AS done FROM quest_milestones WHERE quest_id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + " AND completed = 1;");
                int done = JsonUtils.toInt(rows.get(0).get("done"));
                if (total > 0 && total == done) {
                    execSql("UPDATE quests SET status = 'completed' WHERE id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + " AND status != 'completed';");
                }
                return true;
            } catch (RuntimeException e) {
                return false;
            }
        }
    }

    public boolean insertFaction(String campaignId, String id, String name, String stance) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "INSERT INTO factions (id, campaign_id, name, stance) VALUES (" + quote(id) + ", " + quote(campaignId) + ", " + quote(name) + ", " + quote(stance) + ");",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                if (e.getMessage() != null && e.getMessage().contains("UNIQUE constraint failed")) {
                    return false;
                }
                throw e;
            }
        }
    }

    public boolean insertNpc(String campaignId, String id, String name, String factionId, int disposition) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "INSERT INTO npcs (id, campaign_id, name, faction_id, disposition) VALUES (" + quote(id) + ", " + quote(campaignId) + ", " + quote(name) + ", " + quote(factionId) + ", " + disposition + ");",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                if (e.getMessage() != null && e.getMessage().contains("UNIQUE constraint failed")) {
                    return false;
                }
                throw e;
            }
        }
    }

    public int countFactions(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COUNT(*) AS c FROM factions WHERE campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return 0;
            return JsonUtils.toInt(rows.get(0).get("c"));
        }
    }

    public int countNpcs(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COUNT(*) AS c FROM npcs WHERE campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return 0;
            return JsonUtils.toInt(rows.get(0).get("c"));
        }
    }

    public int countFriendlyNpcs(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COUNT(*) AS c FROM npcs WHERE campaign_id = " + quote(campaignId) + " AND disposition > 0;");
            if (rows.isEmpty()) return 0;
            return JsonUtils.toInt(rows.get(0).get("c"));
        }
    }

    public Map<String, Object> getQuestSummary(String campaignId) {
        synchronized (lock) {
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("campaign_id", campaignId);
            res.put("active", 0);
            res.put("completed", 0);
            res.put("blocked", 0);
            List<Map<String, Object>> rows = query("SELECT status, COUNT(*) AS c FROM quests WHERE campaign_id = " + quote(campaignId) + " GROUP BY status;");
            for (Map<String, Object> row : rows) {
                String status = (String) row.get("status");
                int count = JsonUtils.toInt(row.get("c"));
                if ("active".equals(status)) res.put("active", count);
                else if ("completed".equals(status)) res.put("completed", count);
                else if ("blocked".equals(status)) res.put("blocked", count);
            }
            return res;
        }
    }

    public void addInventoryItem(String campaignId, String itemSlug, String owner, int quantity) {
        synchronized (lock) {
            execSql(
                "INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (" + quote(campaignId) + ", " + quote(itemSlug) + ", " + quote(owner) + ", " + quantity + ") ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + excluded.quantity;"
            );
        }
    }

    public boolean assignEquipment(String campaignId, String characterId, String itemSlug, int quantity) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COALESCE(SUM(quantity), 0) AS total FROM campaign_inventory WHERE campaign_id = " + quote(campaignId) + " AND item_slug = " + quote(itemSlug) + " AND owner = 'party';");
            int partyTotal = JsonUtils.toInt(rows.get(0).get("total"));
            rows = query("SELECT COALESCE(SUM(quantity), 0) AS total FROM character_equipment WHERE campaign_id = " + quote(campaignId) + " AND item_slug = " + quote(itemSlug) + ";");
            int assignedTotal = JsonUtils.toInt(rows.get(0).get("total"));
            if (partyTotal - assignedTotal < quantity) return false;

            execSql(
                "INSERT INTO character_equipment (campaign_id, character_id, item_slug, quantity) VALUES (" + quote(campaignId) + ", " + quote(characterId) + ", " + quote(itemSlug) + ", " + quantity + ") ON CONFLICT(campaign_id, character_id, item_slug) DO UPDATE SET quantity = quantity + excluded.quantity;"
            );
            return true;
        }
    }

    public boolean insertCraftingProject(String campaignId, String id, String characterId, String itemSlug, int daysRequired) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "INSERT INTO downtime_crafting_projects (id, campaign_id, character_id, item_slug, days_required, days_completed, status) VALUES (" + quote(id) + ", " + quote(campaignId) + ", " + quote(characterId) + ", " + quote(itemSlug) + ", " + daysRequired + ", 0, 'active');",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                if (e.getMessage() != null && e.getMessage().contains("UNIQUE constraint failed")) {
                    return false;
                }
                throw e;
            }
        }
    }

    public Map<String, Object> getCraftingProject(String campaignId, String id) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, character_id, item_slug, days_required, days_completed, status FROM downtime_crafting_projects WHERE id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", row.get("id"));
            res.put("character_id", row.get("character_id"));
            res.put("item_slug", row.get("item_slug"));
            res.put("days_required", JsonUtils.toInt(row.get("days_required")));
            res.put("days_completed", JsonUtils.toInt(row.get("days_completed")));
            res.put("status", row.get("status"));
            return res;
        }
    }

    public Map<String, Object> advanceCraftingProject(String campaignId, String id, int days) {
        synchronized (lock) {
            Map<String, Object> project = getCraftingProject(campaignId, id);
            if (project == null) return null;
            int daysRequired = JsonUtils.toInt(project.get("days_required"));
            int daysCompleted = JsonUtils.toInt(project.get("days_completed"));
            String status = (String) project.get("status");
            if ("complete".equals(status)) {
                Map<String, Object> res = new LinkedHashMap<>();
                res.put("id", id);
                res.put("days_completed", daysCompleted);
                res.put("status", status);
                return res;
            }
            int newDaysCompleted = Math.min(daysRequired, daysCompleted + days);
            String newStatus = newDaysCompleted >= daysRequired ? "complete" : "active";
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("UPDATE downtime_crafting_projects SET days_completed = " + newDaysCompleted + ", status = '" + newStatus + "' WHERE id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + ";");
            if ("complete".equals(newStatus)) {
                String itemSlug = (String) project.get("item_slug");
                sqls.add("INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (" + quote(campaignId) + ", " + quote(itemSlug) + ", 'party', 1) ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + excluded.quantity;");
            }
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", id);
            res.put("days_completed", newDaysCompleted);
            res.put("status", newStatus);
            return res;
        }
    }

    public Map<String, Object> getInventorySummary(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT COUNT(*) AS c FROM campaign_inventory WHERE campaign_id = " + quote(campaignId) + " AND owner = 'party';");
            int partyItems = JsonUtils.toInt(rows.get(0).get("c"));
            rows = query("SELECT COUNT(*) AS c FROM character_equipment WHERE campaign_id = " + quote(campaignId) + ";");
            int assignedItems = JsonUtils.toInt(rows.get(0).get("c"));
            rows = query("SELECT COALESCE(SUM(quantity), 0) AS q FROM campaign_inventory WHERE campaign_id = " + quote(campaignId) + " AND item_slug = 'healing-potion' AND owner = 'party';");
            int partyHealing = JsonUtils.toInt(rows.get(0).get("q"));
            rows = query("SELECT COALESCE(SUM(quantity), 0) AS q FROM character_equipment WHERE campaign_id = " + quote(campaignId) + " AND item_slug = 'healing-potion';");
            int assignedHealing = JsonUtils.toInt(rows.get(0).get("q"));
            int available = Math.max(0, partyHealing - assignedHealing);

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("campaign_id", campaignId);
            res.put("party_items", partyItems);
            res.put("assigned_items", assignedItems);
            res.put("healing_potions_available", available);
            return res;
        }
    }

    public boolean insertSession(String campaignId, String id, String startsAt, int durationMinutes, List<String> agenda) {
        synchronized (lock) {
            try {
                execSql(
                    "BEGIN;",
                    "INSERT INTO sessions (id, campaign_id, starts_at, duration_minutes, agenda_count) VALUES (" + quote(id) + ", " + quote(campaignId) + ", " + quote(startsAt) + ", " + durationMinutes + ", " + agenda.size() + ");",
                    "COMMIT;"
                );
                return true;
            } catch (RuntimeException e) {
                if (e.getMessage() != null && e.getMessage().contains("UNIQUE constraint failed")) {
                    return false;
                }
                throw e;
            }
        }
    }

    public Map<String, Object> getSession(String id, String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, starts_at, duration_minutes, agenda_count FROM sessions WHERE id = " + quote(id) + " AND campaign_id = " + quote(campaignId) + ";");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", row.get("id"));
            res.put("starts_at", row.get("starts_at"));
            res.put("duration_minutes", JsonUtils.toInt(row.get("duration_minutes")));
            res.put("agenda_count", JsonUtils.toInt(row.get("agenda_count")));
            return res;
        }
    }

    public Map<String, Object> getNextSession(String campaignId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT id, starts_at, duration_minutes, agenda_count FROM sessions WHERE campaign_id = " + quote(campaignId) + " ORDER BY starts_at, id LIMIT 1;");
            if (rows.isEmpty()) return null;
            Map<String, Object> row = rows.get(0);
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("id", row.get("id"));
            res.put("starts_at", row.get("starts_at"));
            res.put("agenda_count", JsonUtils.toInt(row.get("agenda_count")));
            return res;
        }
    }

    public boolean recordAttendance(String campaignId, String sessionId, List<String> present, List<String> absent) {
        synchronized (lock) {
            List<String> sqls = new ArrayList<>();
            sqls.add("BEGIN;");
            sqls.add("DELETE FROM session_attendance WHERE session_id = " + quote(sessionId) + " AND campaign_id = " + quote(campaignId) + ";");
            for (String p : present) {
                sqls.add("INSERT INTO session_attendance (session_id, campaign_id, character_id, present) VALUES (" + quote(sessionId) + ", " + quote(campaignId) + ", " + quote(p) + ", 1);");
            }
            for (String a : absent) {
                sqls.add("INSERT INTO session_attendance (session_id, campaign_id, character_id, present) VALUES (" + quote(sessionId) + ", " + quote(campaignId) + ", " + quote(a) + ", 0);");
            }
            sqls.add("COMMIT;");
            execSql(sqls.toArray(new String[0]));
            return true;
        }
    }

    public Map<String, Object> getAttendanceCounts(String campaignId, String sessionId) {
        synchronized (lock) {
            List<Map<String, Object>> rows = query("SELECT present, COUNT(*) AS c FROM session_attendance WHERE session_id = " + quote(sessionId) + " AND campaign_id = " + quote(campaignId) + " GROUP BY present;");
            int present = 0;
            int absent = 0;
            for (Map<String, Object> row : rows) {
                int p = JsonUtils.toInt(row.get("present"));
                int c = JsonUtils.toInt(row.get("c"));
                if (p == 1) present = c;
                else absent = c;
            }
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("present_count", present);
            res.put("absent_count", absent);
            return res;
        }
    }

    private String quote(String s) {
        return "'" + s.replace("'", "''") + "'";
    }

    private void execSql(String... sqls) {
        try {
            List<String> cmd = new ArrayList<>();
            cmd.add("sqlite3");
            cmd.add(dbPath);
            Collections.addAll(cmd, sqls);
            ProcessBuilder pb = new ProcessBuilder(cmd);
            pb.redirectErrorStream(true);
            Process p = pb.start();
            String output = new String(p.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
            int rc = p.waitFor();
            if (rc != 0) {
                throw new RuntimeException("sqlite3 failed: " + output.trim());
            }
        } catch (IOException | InterruptedException e) {
            throw new RuntimeException(e);
        }
    }

    private List<Map<String, Object>> query(String sql) {
        try {
            List<String> cmd = new ArrayList<>();
            cmd.add("sqlite3");
            cmd.add("-json");
            cmd.add(dbPath);
            cmd.add(sql);
            ProcessBuilder pb = new ProcessBuilder(cmd);
            pb.redirectErrorStream(true);
            Process p = pb.start();
            String output = new String(p.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
            int rc = p.waitFor();
            if (rc != 0) {
                throw new RuntimeException("sqlite3 failed: " + output.trim());
            }
            String trimmed = output.trim();
            if (trimmed.isEmpty()) return new ArrayList<>();
            Object parsed = JsonUtils.parseJson(trimmed);
            if (parsed instanceof List) return (List<Map<String, Object>>) parsed;
            return new ArrayList<>();
        } catch (IOException | InterruptedException e) {
            throw new RuntimeException(e);
        }
    }
}
