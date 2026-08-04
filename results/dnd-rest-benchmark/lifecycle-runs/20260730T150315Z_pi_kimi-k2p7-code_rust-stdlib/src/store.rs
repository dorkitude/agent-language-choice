use std::env;
use std::io::Write;
use std::process::{Command, Stdio};

use crate::domain::{CombatSession, User};
use crate::json::{extract_int, extract_objects, extract_string, extract_top_array_content};

/// Path to the SQLite database file. Defaults to `game.db` in the working
/// directory.
pub fn db_path() -> String {
    env::var("DB_PATH").unwrap_or_else(|_| "game.db".to_string())
}

/// Escape a single quote for safe concatenation into SQLite string literals.
///
/// This application builds SQL by string concatenation rather than using
/// parameterized queries, so every user-supplied string must be escaped before
/// being embedded in a SQL statement.
pub fn sql_escape(s: &str) -> String {
    s.replace('\'', "''")
}

/// Execute a SQL script against the SQLite database without capturing output.
///
/// Returns an error if `sqlite3` cannot be spawned or exits with a non-zero
/// status.
pub fn sqlite_exec(sql: &str) -> Result<(), String> {
    let mut child = Command::new("sqlite3")
        .arg(db_path())
        .arg("-bail")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("sqlite3 spawn failed: {}", e))?;

    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(sql.as_bytes())
            .map_err(|e| format!("sqlite3 stdin write: {}", e))?;
    }

    let output = child
        .wait_with_output()
        .map_err(|e| format!("sqlite3 output: {}", e))?;
    if !output.status.success() {
        return Err(format!(
            "sqlite3 error: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    Ok(())
}

/// Execute a SQL query and return the SQLite JSON-mode result as a string.
///
/// The output is produced with `.mode json`, so well-formed results are a JSON
/// array of objects. Empty results are returned as an empty string.
pub fn sqlite_query(sql: &str) -> Result<String, String> {
    let input = format!(".mode json\n{}\n", sql);
    let mut child = Command::new("sqlite3")
        .arg(db_path())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("sqlite3 spawn failed: {}", e))?;

    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(input.as_bytes())
            .map_err(|e| format!("sqlite3 stdin write: {}", e))?;
    }

    let output = child
        .wait_with_output()
        .map_err(|e| format!("sqlite3 output: {}", e))?;
    if !output.status.success() {
        return Err(format!(
            "sqlite3 error: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

/// Create the SQLite schema if it does not already exist.
///
/// Also inserts the schema_meta row marking the database as initialized with
/// version 1.
pub fn init_db() -> Result<(), String> {
    let sql = r#"
        PRAGMA busy_timeout = 5000;
        CREATE TABLE IF NOT EXISTS schema_meta (
            version INTEGER PRIMARY KEY,
            initialized INTEGER NOT NULL
        );
        INSERT OR REPLACE INTO schema_meta (version, initialized) VALUES (1, 1);
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS combat_sessions (
            id TEXT PRIMARY KEY,
            round INTEGER NOT NULL,
            turn_index INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS combatants (
            session_id TEXT NOT NULL,
            name TEXT NOT NULL,
            score INTEGER NOT NULL,
            dex INTEGER NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (session_id, name)
        );
        CREATE TABLE IF NOT EXISTS conditions (
            session_id TEXT NOT NULL,
            target TEXT NOT NULL,
            condition TEXT NOT NULL,
            remaining INTEGER NOT NULL,
            PRIMARY KEY (session_id, target, condition)
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
            tag TEXT NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (monster_slug, position)
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
        CREATE TABLE IF NOT EXISTS characters (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            level INTEGER NOT NULL,
            class TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id)
        );
        CREATE TABLE IF NOT EXISTS events (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            kind TEXT NOT NULL,
            summary TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id)
        );
        CREATE TABLE IF NOT EXISTS quests (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, id)
        );
        CREATE TABLE IF NOT EXISTS quest_milestones (
            campaign_id TEXT NOT NULL,
            quest_id TEXT NOT NULL,
            title TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0,
            position INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, quest_id, position)
        );
        CREATE TABLE IF NOT EXISTS factions (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            stance TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id)
        );
        CREATE TABLE IF NOT EXISTS npcs (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            faction_id TEXT NOT NULL,
            disposition INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, id)
        );
        CREATE TABLE IF NOT EXISTS campaign_inventory (
            campaign_id TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            owner TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, item_slug, owner)
        );
        CREATE TABLE IF NOT EXISTS character_equipment (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, character_id, item_slug)
        );
        CREATE TABLE IF NOT EXISTS crafting_projects (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            days_required INTEGER NOT NULL,
            days_completed INTEGER NOT NULL,
            status TEXT NOT NULL,
            cost_gp INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, id)
        );
        CREATE TABLE IF NOT EXISTS campaign_sessions (
            campaign_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, session_id)
        );
        CREATE TABLE IF NOT EXISTS session_agenda (
            campaign_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            item TEXT NOT NULL,
            PRIMARY KEY (campaign_id, session_id, position)
        );
        CREATE TABLE IF NOT EXISTS session_attendance (
            campaign_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            present INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, session_id, character_id)
        );
        CREATE TABLE IF NOT EXISTS play_campaigns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            owner TEXT NOT NULL,
            status TEXT NOT NULL,
            max_players INTEGER NOT NULL,
            current_actor TEXT NOT NULL DEFAULT '',
            phase TEXT NOT NULL DEFAULT 'lobby',
            turn_number INTEGER NOT NULL DEFAULT 0,
            nudge_count INTEGER NOT NULL DEFAULT 0,
            current_scene_id TEXT NOT NULL DEFAULT '',
            current_location_id TEXT NOT NULL DEFAULT '',
            exploration_actor TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS play_campaign_members (
            campaign_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            character_id TEXT NOT NULL,
            name TEXT NOT NULL,
            class TEXT NOT NULL,
            hp_max INTEGER NOT NULL DEFAULT 20,
            hp_current INTEGER NOT NULL DEFAULT 20,
            status TEXT NOT NULL DEFAULT 'healthy',
            death_saves_successes INTEGER NOT NULL DEFAULT 0,
            death_saves_failures INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (campaign_id, actor),
            UNIQUE (campaign_id, character_id)
        );
        CREATE TABLE IF NOT EXISTS play_narrations (
            campaign_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            kind TEXT NOT NULL DEFAULT 'narration',
            actor TEXT NOT NULL,
            target TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL,
            PRIMARY KEY (campaign_id, sequence)
        );
        CREATE TABLE IF NOT EXISTS play_campaign_documents (
            id TEXT PRIMARY KEY,
            story TEXT NOT NULL DEFAULT '',
            dm_notes TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS play_scenes (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id)
        );
        CREATE TABLE IF NOT EXISTS play_locations (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id)
        );
        CREATE TABLE IF NOT EXISTS play_location_connections (
            campaign_id TEXT NOT NULL,
            from_id TEXT NOT NULL,
            to_id TEXT NOT NULL,
            travel_turns INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, from_id, to_id)
        );
        CREATE TABLE IF NOT EXISTS play_encounters (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            combatants TEXT NOT NULL DEFAULT '[]',
            round INTEGER NOT NULL DEFAULT 1,
            turn_index INTEGER NOT NULL DEFAULT 0,
            xp_awarded INTEGER NOT NULL DEFAULT 0,
            rewards_awarded INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (campaign_id, id)
        );
        CREATE TABLE IF NOT EXISTS play_encounter_monsters (
            campaign_id TEXT NOT NULL,
            encounter_id TEXT NOT NULL,
            monster_id TEXT NOT NULL,
            name TEXT NOT NULL,
            hp_max INTEGER NOT NULL,
            hp_current INTEGER NOT NULL,
            initiative INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, encounter_id, monster_id)
        );
        CREATE TABLE IF NOT EXISTS play_encounter_combatants (
            campaign_id TEXT NOT NULL,
            encounter_id TEXT NOT NULL,
            member TEXT NOT NULL,
            character_id TEXT NOT NULL,
            name TEXT NOT NULL,
            initiative INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, encounter_id, member)
        );
        CREATE TABLE IF NOT EXISTS play_encounter_conditions (
            campaign_id TEXT NOT NULL,
            encounter_id TEXT NOT NULL,
            target TEXT NOT NULL,
            condition TEXT NOT NULL,
            remaining INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, encounter_id, target, condition)
        );
        CREATE TABLE IF NOT EXISTS play_encounter_order (
            campaign_id TEXT NOT NULL,
            encounter_id TEXT NOT NULL,
            identifier TEXT NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, encounter_id, position)
        );
        CREATE TABLE IF NOT EXISTS play_encounter_loot (
            campaign_id TEXT NOT NULL,
            encounter_id TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, encounter_id, position)
        );
    "#;
    sqlite_exec(sql)?;
    migrate_play_campaign_members()?;
    migrate_play_encounters_rewards()?;
    migrate_play_campaigns_exploration_actor()
}

/// Add missing death-save columns to an existing play_campaign_members table.
///
/// Older schemas created before the death-saves stage lack `status`,
/// `death_saves_successes`, and `death_saves_failures`. This migration runs
/// unconditionally on startup and adds any missing columns with safe defaults.
fn migrate_play_campaign_members() -> Result<(), String> {
    let sql = "PRAGMA table_info(play_campaign_members);";
    let output = sqlite_query(sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let mut has_status = false;
    let mut has_successes = false;
    let mut has_failures = false;
    for obj in extract_objects(content) {
        if let Some(name) = extract_string(obj, "name") {
            match name {
                "status" => has_status = true,
                "death_saves_successes" => has_successes = true,
                "death_saves_failures" => has_failures = true,
                _ => {}
            }
        }
    }
    if !has_status {
        sqlite_exec(
            "ALTER TABLE play_campaign_members ADD COLUMN status TEXT NOT NULL DEFAULT 'healthy';",
        )?;
    }
    if !has_successes {
        sqlite_exec(
            "ALTER TABLE play_campaign_members ADD COLUMN death_saves_successes INTEGER NOT NULL DEFAULT 0;",
        )?;
    }
    if !has_failures {
        sqlite_exec(
            "ALTER TABLE play_campaign_members ADD COLUMN death_saves_failures INTEGER NOT NULL DEFAULT 0;",
        )?;
    }
    Ok(())
}

/// Add missing reward columns to an existing play_encounters table.
///
/// Older schemas created before the encounter rewards stage lack
/// `xp_awarded` and `rewards_awarded`. This migration runs
/// unconditionally on startup and adds any missing columns with safe
/// defaults.
fn migrate_play_encounters_rewards() -> Result<(), String> {
    let sql = "PRAGMA table_info(play_encounters);";
    let output = sqlite_query(sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let mut has_xp_awarded = false;
    let mut has_rewards_awarded = false;
    for obj in extract_objects(content) {
        if let Some(name) = extract_string(obj, "name") {
            match name {
                "xp_awarded" => has_xp_awarded = true,
                "rewards_awarded" => has_rewards_awarded = true,
                _ => {}
            }
        }
    }
    if !has_xp_awarded {
        sqlite_exec(
            "ALTER TABLE play_encounters ADD COLUMN xp_awarded INTEGER NOT NULL DEFAULT 0;",
        )?;
    }
    if !has_rewards_awarded {
        sqlite_exec(
            "ALTER TABLE play_encounters ADD COLUMN rewards_awarded INTEGER NOT NULL DEFAULT 0;",
        )?;
    }
    Ok(())
}

/// Add missing exploration-actor column to an existing play_campaigns table.
///
/// Older schemas created before the combat/exploration transition stage lack
/// `exploration_actor`. This migration runs unconditionally on startup and
/// adds the missing column with an empty default.
fn migrate_play_campaigns_exploration_actor() -> Result<(), String> {
    let sql = "PRAGMA table_info(play_campaigns);";
    let output = sqlite_query(sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let mut has_exploration_actor = false;
    for obj in extract_objects(content) {
        if let Some(name) = extract_string(obj, "name") {
            if name == "exploration_actor" {
                has_exploration_actor = true;
            }
        }
    }
    if !has_exploration_actor {
        sqlite_exec(
            "ALTER TABLE play_campaigns ADD COLUMN exploration_actor TEXT NOT NULL DEFAULT '';",
        )?;
    }
    Ok(())
}

/// Drop all application tables and recreate a fresh schema.
///
/// This is a destructive operation used by the storage reset endpoint.
pub fn reset_db() -> Result<(), String> {
    let sql = r#"
        PRAGMA busy_timeout = 5000;
        DROP TABLE IF EXISTS schema_meta;
        DROP TABLE IF EXISTS combat_sessions;
        DROP TABLE IF EXISTS combatants;
        DROP TABLE IF EXISTS conditions;
        DROP TABLE IF EXISTS monsters;
        DROP TABLE IF EXISTS monster_tags;
        DROP TABLE IF EXISTS items;
        DROP TABLE IF EXISTS events;
        DROP TABLE IF EXISTS npcs;
        DROP TABLE IF EXISTS factions;
        DROP TABLE IF EXISTS quest_milestones;
        DROP TABLE IF EXISTS quests;
        DROP TABLE IF EXISTS characters;
        DROP TABLE IF EXISTS campaigns;
        DROP TABLE IF EXISTS character_equipment;
        DROP TABLE IF EXISTS campaign_inventory;
        DROP TABLE IF EXISTS crafting_projects;
        DROP TABLE IF EXISTS session_attendance;
        DROP TABLE IF EXISTS session_agenda;
        DROP TABLE IF EXISTS campaign_sessions;
        DROP TABLE IF EXISTS play_campaigns;
        DROP TABLE IF EXISTS play_campaign_members;
        DROP TABLE IF EXISTS play_narrations;
        DROP TABLE IF EXISTS play_campaign_documents;
        DROP TABLE IF EXISTS play_scenes;
        DROP TABLE IF EXISTS play_locations;
        DROP TABLE IF EXISTS play_location_connections;
        DROP TABLE IF EXISTS play_encounters;
        DROP TABLE IF EXISTS play_encounter_monsters;
        DROP TABLE IF EXISTS play_encounter_combatants;
        DROP TABLE IF EXISTS play_encounter_conditions;
        DROP TABLE IF EXISTS play_encounter_order;
        DROP TABLE IF EXISTS play_encounter_loot;
    "#;
    sqlite_exec(sql)?;
    init_db()
}

/// Return the current schema version and initialization flag.
///
/// If the schema_meta row is missing or the query fails, the database is
/// reported as uninitialized with version 0.
pub fn storage_status() -> Result<(i64, bool), String> {
    let sql = "SELECT version, initialized FROM schema_meta WHERE version = 1;";
    match sqlite_query(sql) {
        Ok(output) => {
            let content = extract_top_array_content(&output).unwrap_or("");
            let objects = extract_objects(content);
            if objects.is_empty() {
                return Ok((0, false));
            }
            let obj = objects[0];
            let version = extract_int(obj, "version").unwrap_or(0);
            let initialized = extract_int(obj, "initialized").unwrap_or(0) != 0;
            Ok((version, initialized))
        }
        Err(_) => Ok((0, false)),
    }
}

/// Load persistent users and combat sessions from SQLite into the in-memory
/// caches.
///
/// This is called once at startup. Existing in-memory contents are cleared and
/// replaced by the persisted state.
pub fn load_storage(
    sessions: &mut std::collections::HashMap<String, CombatSession>,
    users: &mut std::collections::HashMap<String, User>,
) -> Result<(), String> {
    users.clear();
    sessions.clear();

    let users_output = sqlite_query("SELECT username, role, password_hash FROM users;")?;
    let users_content = extract_top_array_content(&users_output).unwrap_or("");
    for obj in extract_objects(users_content) {
        let username = extract_string(obj, "username")
            .ok_or("missing username")?
            .to_string();
        let role = extract_string(obj, "role").ok_or("missing role")?.to_string();
        let password_hash = extract_string(obj, "password_hash")
            .ok_or("missing password_hash")?
            .to_string();
        users.insert(
            username.clone(),
            User {
                username,
                role,
                password_hash,
            },
        );
    }

    let sessions_output = sqlite_query("SELECT id, round, turn_index FROM combat_sessions;")?;
    let sessions_content = extract_top_array_content(&sessions_output).unwrap_or("");
    for obj in extract_objects(sessions_content) {
        let id = extract_string(obj, "id").ok_or("missing id")?.to_string();
        let round = extract_int(obj, "round").ok_or("missing round")?;
        let turn_index = extract_int(obj, "turn_index").ok_or("missing turn_index")? as usize;

        let c_sql = format!(
            "SELECT name, score, dex, position FROM combatants WHERE session_id = '{}' ORDER BY position;",
            sql_escape(&id)
        );
        let c_output = sqlite_query(&c_sql)?;
        let c_content = extract_top_array_content(&c_output).unwrap_or("");
        let mut order = Vec::new();
        for c_obj in extract_objects(c_content) {
            let name = extract_string(c_obj, "name")
                .ok_or("missing combatant name")?
                .to_string();
            let score = extract_int(c_obj, "score").ok_or("missing score")?;
            let dex = extract_int(c_obj, "dex").ok_or("missing dex")?;
            order.push(crate::domain::Combatant { name, score, dex });
        }

        let cond_sql = format!(
            "SELECT target, condition, remaining FROM conditions WHERE session_id = '{}';",
            sql_escape(&id)
        );
        let cond_output = sqlite_query(&cond_sql)?;
        let cond_content = extract_top_array_content(&cond_output).unwrap_or("");
        let mut conditions = std::collections::HashMap::new();
        for cond_obj in extract_objects(cond_content) {
            let target = extract_string(cond_obj, "target")
                .ok_or("missing target")?
                .to_string();
            let name = extract_string(cond_obj, "condition")
                .ok_or("missing condition")?
                .to_string();
            let remaining = extract_int(cond_obj, "remaining").ok_or("missing remaining")?;
            conditions
                .entry(target)
                .or_insert_with(Vec::new)
                .push(crate::domain::Condition { name, remaining });
        }

        sessions.insert(
            id.clone(),
            CombatSession {
                id,
                round,
                turn_index,
                order,
                conditions,
            },
        );
    }

    Ok(())
}

/// Persist the entire in-memory state to SQLite.
///
/// This function is intentionally simple: it deletes all rows from the mutable
/// tables and re-inserts them from the in-memory caches. The busy timeout
/// helps prevent conflicts with rapid sequential requests.
pub fn save_storage(
    sessions: &std::collections::HashMap<String, CombatSession>,
    users: &std::collections::HashMap<String, User>,
) -> Result<(), String> {
    let mut sql = String::from(
        "PRAGMA busy_timeout = 5000;\nDELETE FROM conditions;\nDELETE FROM combatants;\nDELETE FROM combat_sessions;\nDELETE FROM users;\n",
    );

    for user in users.values() {
        sql.push_str(&format!(
            "INSERT INTO users (username, role, password_hash) VALUES ('{}', '{}', '{}');\n",
            sql_escape(&user.username),
            sql_escape(&user.role),
            sql_escape(&user.password_hash)
        ));
    }

    for session in sessions.values() {
        sql.push_str(&format!(
            "INSERT INTO combat_sessions (id, round, turn_index) VALUES ('{}', {}, {});\n",
            sql_escape(&session.id),
            session.round,
            session.turn_index
        ));
        for (position, c) in session.order.iter().enumerate() {
            sql.push_str(&format!(
                "INSERT INTO combatants (session_id, name, score, dex, position) VALUES ('{}', '{}', {}, {}, {});\n",
                sql_escape(&session.id),
                sql_escape(&c.name),
                c.score,
                c.dex,
                position
            ));
        }
        for (target, list) in &session.conditions {
            for c in list {
                sql.push_str(&format!(
                    "INSERT INTO conditions (session_id, target, condition, remaining) VALUES ('{}', '{}', '{}', {});\n",
                    sql_escape(&session.id),
                    sql_escape(target),
                    sql_escape(&c.name),
                    c.remaining
                ));
            }
        }
    }

    sqlite_exec(&sql)
}

/// Check whether a compendium slug already exists in the given table.
pub fn compendium_slug_exists(table: &str, slug: &str) -> Result<bool, String> {
    let sql = format!("SELECT 1 FROM {} WHERE slug = '{}';", table, sql_escape(slug));
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

pub fn campaign_exists(id: &str) -> Result<bool, String> {
    let sql = format!("SELECT 1 FROM campaigns WHERE id = '{}';", sql_escape(id));
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Check whether a character exists within a campaign.
pub fn character_exists(campaign_id: &str, id: &str) -> Result<bool, String> {
    let sql = format!(
        "SELECT 1 FROM characters WHERE campaign_id = '{}' AND id = '{}';",
        sql_escape(campaign_id),
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Check whether a campaign event exists.
pub fn event_exists(campaign_id: &str, id: &str) -> Result<bool, String> {
    let sql = format!(
        "SELECT 1 FROM events WHERE campaign_id = '{}' AND id = '{}';",
        sql_escape(campaign_id),
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Check whether a quest exists within a campaign.
pub fn quest_exists(campaign_id: &str, id: &str) -> Result<bool, String> {
    let sql = format!(
        "SELECT 1 FROM quests WHERE campaign_id = '{}' AND id = '{}';",
        sql_escape(campaign_id),
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Check whether a faction exists within a campaign.
pub fn faction_exists(campaign_id: &str, id: &str) -> Result<bool, String> {
    let sql = format!(
        "SELECT 1 FROM factions WHERE campaign_id = '{}' AND id = '{}';",
        sql_escape(campaign_id),
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Check whether an NPC exists within a campaign.
pub fn npc_exists(campaign_id: &str, id: &str) -> Result<bool, String> {
    let sql = format!(
        "SELECT 1 FROM npcs WHERE campaign_id = '{}' AND id = '{}';",
        sql_escape(campaign_id),
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Check whether a crafting project exists within a campaign.
pub fn project_exists(campaign_id: &str, id: &str) -> Result<bool, String> {
    let sql = format!(
        "SELECT 1 FROM crafting_projects WHERE campaign_id = '{}' AND id = '{}';",
        sql_escape(campaign_id),
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Check whether a play campaign exists by id.
pub fn play_campaign_exists(id: &str) -> Result<bool, String> {
    let sql = format!("SELECT 1 FROM play_campaigns WHERE id = '{}';", sql_escape(id));
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Create a play campaign owned by the authenticated DM.
pub fn play_campaign_create(
    id: &str,
    name: &str,
    owner: &str,
    status: &str,
    max_players: i64,
) -> Result<(), String> {
    let sql = format!(
        "BEGIN;\nINSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES ('{}', '{}', '{}', '{}', {});\nINSERT INTO play_campaign_documents (id, story, dm_notes) VALUES ('{}', '', '');\nCOMMIT;",
        sql_escape(id),
        sql_escape(name),
        sql_escape(owner),
        sql_escape(status),
        max_players,
        sql_escape(id)
    );
    sqlite_exec(&sql)
}

/// Read the durable campaign document.
///
/// If the document row is missing (e.g., the campaign was created before the
/// document table existed), an empty document row is inserted on demand and
/// empty strings are returned.
pub fn play_campaign_document_get(id: &str) -> Result<(String, String), String> {
    let sql = format!(
        "SELECT story, dm_notes FROM play_campaign_documents WHERE id = '{}';",
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        let insert = format!(
            "INSERT OR IGNORE INTO play_campaign_documents (id, story, dm_notes) VALUES ('{}', '', '');",
            sql_escape(id)
        );
        sqlite_exec(&insert)?;
        return Ok((String::new(), String::new()));
    }
    let story = extract_string(objects[0], "story").ok_or("missing story")?;
    let dm_notes = extract_string(objects[0], "dm_notes").ok_or("missing dm_notes")?;
    Ok((story.to_string(), dm_notes.to_string()))
}

/// Update the durable campaign document.
pub fn play_campaign_document_set(
    id: &str,
    story: &str,
    dm_notes: &str,
) -> Result<(), String> {
    let sql = format!(
        "UPDATE play_campaign_documents SET story = '{}', dm_notes = '{}' WHERE id = '{}';",
        sql_escape(story),
        sql_escape(dm_notes),
        sql_escape(id)
    );
    sqlite_exec(&sql)
}

/// Return the maximum number of players for a play campaign, if it exists.
pub fn play_campaign_max_players(id: &str) -> Result<i64, String> {
    let sql = format!(
        "SELECT max_players FROM play_campaigns WHERE id = '{}';",
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err("play campaign not found".to_string());
    }
    extract_int(objects[0], "max_players").ok_or("missing max_players".to_string())
}

/// Count the number of members in a play campaign.
pub fn play_campaign_member_count(id: &str) -> Result<i64, String> {
    let sql = format!(
        "SELECT COUNT(*) AS cnt FROM play_campaign_members WHERE campaign_id = '{}';",
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Ok(0);
    }
    Ok(extract_int(objects[0], "cnt").unwrap_or(0))
}

/// Check whether a player already has a membership in a play campaign.
pub fn play_campaign_member_exists(campaign_id: &str, actor: &str) -> Result<bool, String> {
    let sql = format!(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = '{}' AND actor = '{}';",
        sql_escape(campaign_id),
        sql_escape(actor)
    );
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Check whether a character id is already used in a play campaign.
pub fn play_campaign_character_id_exists(campaign_id: &str, character_id: &str) -> Result<bool, String> {
    let sql = format!(
        "SELECT 1 FROM play_campaign_members WHERE campaign_id = '{}' AND character_id = '{}';",
        sql_escape(campaign_id),
        sql_escape(character_id)
    );
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Add a player membership to a play campaign.
pub fn play_campaign_member_create(
    campaign_id: &str,
    actor: &str,
    character_id: &str,
    name: &str,
    class: &str,
) -> Result<(), String> {
    let sql = format!(
        "INSERT INTO play_campaign_members (campaign_id, actor, character_id, name, class, hp_max, hp_current, status, death_saves_successes, death_saves_failures) VALUES ('{}', '{}', '{}', '{}', '{}', 20, 20, 'healthy', 0, 0);",
        sql_escape(campaign_id),
        sql_escape(actor),
        sql_escape(character_id),
        sql_escape(name),
        sql_escape(class)
    );
    sqlite_exec(&sql)
}

/// Return the current and maximum hit points for a play campaign member.
pub fn play_campaign_member_hp(campaign_id: &str, actor: &str) -> Result<(i64, i64), String> {
    let sql = format!(
        "SELECT hp_current, hp_max FROM play_campaign_members WHERE campaign_id = '{}' AND actor = '{}';",
        sql_escape(campaign_id),
        sql_escape(actor)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err("member not found".to_string());
    }
    let hp_current = extract_int(objects[0], "hp_current").ok_or("missing hp_current")?;
    let hp_max = extract_int(objects[0], "hp_max").ok_or("missing hp_max")?;
    Ok((hp_current, hp_max))
}

/// Return the full durable state for a play campaign member by actor.
///
/// The returned tuple is `(actor, character_id, hp_current, hp_max,
/// death_saves_successes, death_saves_failures, status)`.
pub fn play_campaign_member_full(
    campaign_id: &str,
    actor: &str,
) -> Result<(String, String, i64, i64, i64, i64, String), String> {
    let sql = format!(
        "SELECT actor, character_id, hp_current, hp_max, death_saves_successes, death_saves_failures, status FROM play_campaign_members WHERE campaign_id = '{}' AND actor = '{}';",
        sql_escape(campaign_id),
        sql_escape(actor)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err("member not found".to_string());
    }
    let obj = objects[0];
    let actor = extract_string(obj, "actor").ok_or("missing actor")?.to_string();
    let character_id = extract_string(obj, "character_id").ok_or("missing character_id")?.to_string();
    let hp_current = extract_int(obj, "hp_current").ok_or("missing hp_current")?;
    let hp_max = extract_int(obj, "hp_max").ok_or("missing hp_max")?;
    let successes = extract_int(obj, "death_saves_successes").ok_or("missing death_saves_successes")?;
    let failures = extract_int(obj, "death_saves_failures").ok_or("missing death_saves_failures")?;
    let status = extract_string(obj, "status").ok_or("missing status")?.to_string();
    Ok((actor, character_id, hp_current, hp_max, successes, failures, status))
}

/// Return the full durable state for a play campaign member by character id.
///
/// The returned tuple is `(actor, character_id, hp_current, hp_max,
/// death_saves_successes, death_saves_failures, status)`.
pub fn play_campaign_member_by_character_id(
    campaign_id: &str,
    character_id: &str,
) -> Result<(String, String, i64, i64, i64, i64, String), String> {
    let sql = format!(
        "SELECT actor, character_id, hp_current, hp_max, death_saves_successes, death_saves_failures, status FROM play_campaign_members WHERE campaign_id = '{}' AND character_id = '{}';",
        sql_escape(campaign_id),
        sql_escape(character_id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err("member not found".to_string());
    }
    let obj = objects[0];
    let actor = extract_string(obj, "actor").ok_or("missing actor")?.to_string();
    let character_id = extract_string(obj, "character_id").ok_or("missing character_id")?.to_string();
    let hp_current = extract_int(obj, "hp_current").ok_or("missing hp_current")?;
    let hp_max = extract_int(obj, "hp_max").ok_or("missing hp_max")?;
    let successes = extract_int(obj, "death_saves_successes").ok_or("missing death_saves_successes")?;
    let failures = extract_int(obj, "death_saves_failures").ok_or("missing death_saves_failures")?;
    let status = extract_string(obj, "status").ok_or("missing status")?.to_string();
    Ok((actor, character_id, hp_current, hp_max, successes, failures, status))
}

/// Update a play campaign member's current hit points, applying automatic
/// status transitions: HP above 0 makes the character healthy and clears death
/// saves; dropping from above 0 to 0 makes the character unconscious.
pub fn play_campaign_member_set_hp_current(
    campaign_id: &str,
    actor: &str,
    hp_current: i64,
) -> Result<(), String> {
    let (_, _, _, _, successes, failures, status) = play_campaign_member_full(campaign_id, actor)?;
    let new_status = if hp_current > 0 {
        "healthy"
    } else if status == "healthy" {
        "unconscious"
    } else {
        &status
    };
    let new_successes = if hp_current > 0 { 0 } else { successes };
    let new_failures = if hp_current > 0 { 0 } else { failures };
    let sql = format!(
        "UPDATE play_campaign_members SET hp_current = {}, status = '{}', death_saves_successes = {}, death_saves_failures = {} WHERE campaign_id = '{}' AND actor = '{}';",
        hp_current,
        sql_escape(new_status),
        new_successes,
        new_failures,
        sql_escape(campaign_id),
        sql_escape(actor)
    );
    sqlite_exec(&sql)
}

/// Update a play campaign member's hit points, status, and death-save counters.
pub fn play_campaign_member_set_hp_status_saves(
    campaign_id: &str,
    actor: &str,
    hp_current: i64,
    status: &str,
    successes: i64,
    failures: i64,
) -> Result<(), String> {
    let sql = format!(
        "UPDATE play_campaign_members SET hp_current = {}, status = '{}', death_saves_successes = {}, death_saves_failures = {} WHERE campaign_id = '{}' AND actor = '{}';",
        hp_current,
        sql_escape(status),
        successes,
        failures,
        sql_escape(campaign_id),
        sql_escape(actor)
    );
    sqlite_exec(&sql)
}

/// Update a play campaign member's death-save counters and status.
pub fn play_campaign_member_set_death_saves_status(
    campaign_id: &str,
    actor: &str,
    successes: i64,
    failures: i64,
    status: &str,
) -> Result<(), String> {
    let sql = format!(
        "UPDATE play_campaign_members SET death_saves_successes = {}, death_saves_failures = {}, status = '{}' WHERE campaign_id = '{}' AND actor = '{}';",
        successes,
        failures,
        sql_escape(status),
        sql_escape(campaign_id),
        sql_escape(actor)
    );
    sqlite_exec(&sql)
}

/// Return the owner and status of a play campaign.
pub fn play_campaign_owner_status(id: &str) -> Result<(String, String), String> {
    let sql = format!(
        "SELECT owner, status FROM play_campaigns WHERE id = '{}';",
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err("play campaign not found".to_string());
    }
    let owner = extract_string(objects[0], "owner").ok_or("missing owner")?;
    let status = extract_string(objects[0], "status").ok_or("missing status")?;
    Ok((owner.to_string(), status.to_string()))
}

/// Store the exploration actor to resume when combat ends.
pub fn play_campaign_set_exploration_actor(
    campaign_id: &str,
    actor: &str,
) -> Result<(), String> {
    let sql = format!(
        "UPDATE play_campaigns SET exploration_actor = '{}' WHERE id = '{}';",
        sql_escape(actor),
        sql_escape(campaign_id)
    );
    sqlite_exec(&sql)
}

/// Read the stored exploration actor for a play campaign.
pub fn play_campaign_get_exploration_actor(campaign_id: &str) -> Result<String, String> {
    let sql = format!(
        "SELECT exploration_actor FROM play_campaigns WHERE id = '{}';",
        sql_escape(campaign_id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err("play campaign not found".to_string());
    }
    let actor = extract_string(objects[0], "exploration_actor")
        .ok_or("missing exploration_actor")?;
    Ok(actor.to_string())
}

/// Return all members of a play campaign in insertion order.
pub fn play_campaign_members(
    id: &str,
) -> Result<Vec<(String, String, String, String)>, String> {
    let sql = format!(
        "SELECT actor, character_id, name, class FROM play_campaign_members WHERE campaign_id = '{}' ORDER BY rowid;",
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let mut members = Vec::new();
    for obj in extract_objects(content) {
        let actor = extract_string(obj, "actor").ok_or("missing actor")?;
        let character_id = extract_string(obj, "character_id").ok_or("missing character_id")?;
        let name = extract_string(obj, "name").ok_or("missing name")?;
        let class = extract_string(obj, "class").ok_or("missing class")?;
        members.push((
            actor.to_string(),
            character_id.to_string(),
            name.to_string(),
            class.to_string(),
        ));
    }
    Ok(members)
}

/// Return the next append-only narration sequence for a play campaign.
///
/// Sequences start at 1 for each campaign and never decrease.
pub fn play_narration_next_sequence(campaign_id: &str) -> Result<i64, String> {
    let sql = format!(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS seq FROM play_narrations WHERE campaign_id = '{}';",
        sql_escape(campaign_id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Ok(1);
    }
    Ok(extract_int(objects[0], "seq").unwrap_or(1))
}

/// Append a narration event to a play campaign.
pub fn play_narration_create(
    campaign_id: &str,
    sequence: i64,
    kind: &str,
    actor: &str,
    text: &str,
) -> Result<(), String> {
    let sql = format!(
        "INSERT INTO play_narrations (campaign_id, sequence, kind, actor, text) VALUES ('{}', {}, '{}', '{}', '{}');",
        sql_escape(campaign_id),
        sequence,
        sql_escape(kind),
        sql_escape(actor),
        sql_escape(text)
    );
    sqlite_exec(&sql)
}

/// Append a narration event that includes an explicit target to a play campaign.
///
/// The `target` column is stored but omitted from the standard event list so
/// that existing endpoints continue to return the same four-field shape.
pub fn play_narration_create_with_target(
    campaign_id: &str,
    sequence: i64,
    kind: &str,
    actor: &str,
    target: &str,
    text: &str,
) -> Result<(), String> {
    let sql = format!(
        "INSERT INTO play_narrations (campaign_id, sequence, kind, actor, target, text) VALUES ('{}', {}, '{}', '{}', '{}', '{}');",
        sql_escape(campaign_id),
        sequence,
        sql_escape(kind),
        sql_escape(actor),
        sql_escape(target),
        sql_escape(text)
    );
    sqlite_exec(&sql)
}

/// Start a play campaign, recording its initial turn state.
pub fn play_campaign_start(
    id: &str,
    current_actor: &str,
    phase: &str,
    turn_number: i64,
) -> Result<(), String> {
    let sql = format!(
        "UPDATE play_campaigns SET status = 'active', current_actor = '{}', phase = '{}', turn_number = {} WHERE id = '{}';",
        sql_escape(current_actor),
        sql_escape(phase),
        turn_number,
        sql_escape(id)
    );
    sqlite_exec(&sql)
}

/// Update the current actor, phase, and turn number for a play campaign.
pub fn play_campaign_update_turn(
    id: &str,
    current_actor: &str,
    phase: &str,
    turn_number: i64,
) -> Result<(), String> {
    let sql = format!(
        "UPDATE play_campaigns SET current_actor = '{}', phase = '{}', turn_number = {} WHERE id = '{}';",
        sql_escape(current_actor),
        sql_escape(phase),
        turn_number,
        sql_escape(id)
    );
    sqlite_exec(&sql)
}

/// Return the character id and name for a play campaign member.
pub fn play_campaign_member_character(
    campaign_id: &str,
    actor: &str,
) -> Result<(String, String), String> {
    let sql = format!(
        "SELECT character_id, name FROM play_campaign_members WHERE campaign_id = '{}' AND actor = '{}';",
        sql_escape(campaign_id),
        sql_escape(actor)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err("member not found".to_string());
    }
    let character_id = extract_string(objects[0], "character_id").ok_or("missing character_id")?;
    let name = extract_string(objects[0], "name").ok_or("missing name")?;
    Ok((character_id.to_string(), name.to_string()))
}

/// Return all public events for a play campaign in sequence order.
pub fn play_campaign_narrations(
    campaign_id: &str,
) -> Result<Vec<(i64, String, String, String)>, String> {
    let sql = format!(
        "SELECT sequence, kind, actor, text FROM play_narrations WHERE campaign_id = '{}' ORDER BY sequence ASC;",
        sql_escape(campaign_id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let mut narrations = Vec::new();
    for obj in extract_objects(content) {
        let sequence = extract_int(obj, "sequence").ok_or("missing sequence")?;
        let kind = extract_string(obj, "kind").ok_or("missing kind")?;
        let actor = extract_string(obj, "actor").ok_or("missing actor")?;
        let text = extract_string(obj, "text").ok_or("missing text")?;
        narrations.push((sequence, kind.to_string(), actor.to_string(), text.to_string()));
    }
    Ok(narrations)
}

/// Read the persisted turn state for a play campaign.
pub fn play_campaign_get_turn(id: &str) -> Result<(String, String, i64), String> {
    let sql = format!(
        "SELECT current_actor, phase, turn_number FROM play_campaigns WHERE id = '{}';",
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err("play campaign not found".to_string());
    }
    let current_actor = extract_string(objects[0], "current_actor").ok_or("missing current_actor")?;
    let phase = extract_string(objects[0], "phase").ok_or("missing phase")?;
    let turn_number = extract_int(objects[0], "turn_number").ok_or("missing turn_number")?;
    Ok((current_actor.to_string(), phase.to_string(), turn_number))
}

/// Increment the nudge count for a play campaign and return the new value.
pub fn play_campaign_nudge(id: &str) -> Result<i64, String> {
    let update = format!(
        "UPDATE play_campaigns SET nudge_count = nudge_count + 1 WHERE id = '{}';",
        sql_escape(id)
    );
    sqlite_exec(&update)?;
    let sql = format!(
        "SELECT nudge_count FROM play_campaigns WHERE id = '{}';",
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err("play campaign not found".to_string());
    }
    extract_int(objects[0], "nudge_count").ok_or("missing nudge_count".to_string())
}

/// Check whether a scene exists within a play campaign.
pub fn play_scene_exists(campaign_id: &str, id: &str) -> Result<bool, String> {
    let sql = format!(
        "SELECT 1 FROM play_scenes WHERE campaign_id = '{}' AND id = '{}';",
        sql_escape(campaign_id),
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Create a new open scene for a play campaign.
pub fn play_scene_create(campaign_id: &str, id: &str, name: &str) -> Result<(), String> {
    let sql = format!(
        "INSERT INTO play_scenes (campaign_id, id, name, status) VALUES ('{}', '{}', '{}', 'open');",
        sql_escape(campaign_id),
        sql_escape(id),
        sql_escape(name)
    );
    sqlite_exec(&sql)
}

/// Read a scene's name and status for a play campaign.
pub fn play_scene_get(campaign_id: &str, id: &str) -> Result<(String, String), String> {
    let sql = format!(
        "SELECT name, status FROM play_scenes WHERE campaign_id = '{}' AND id = '{}';",
        sql_escape(campaign_id),
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err("scene not found".to_string());
    }
    let name = extract_string(objects[0], "name").ok_or("missing name")?;
    let status = extract_string(objects[0], "status").ok_or("missing status")?;
    Ok((name.to_string(), status.to_string()))
}

/// Update a scene's status for a play campaign.
pub fn play_scene_set_status(campaign_id: &str, id: &str, status: &str) -> Result<(), String> {
    let sql = format!(
        "UPDATE play_scenes SET status = '{}' WHERE campaign_id = '{}' AND id = '{}';",
        sql_escape(status),
        sql_escape(campaign_id),
        sql_escape(id)
    );
    sqlite_exec(&sql)
}

/// Set the current scene for a play campaign.
pub fn play_campaign_set_current_scene(campaign_id: &str, scene_id: &str) -> Result<(), String> {
    let sql = format!(
        "UPDATE play_campaigns SET current_scene_id = '{}' WHERE id = '{}';",
        sql_escape(scene_id),
        sql_escape(campaign_id)
    );
    sqlite_exec(&sql)
}

/// Read the current scene for a play campaign, if one is set.
pub fn play_campaign_get_current_scene(
    campaign_id: &str,
) -> Result<Option<(String, String, String)>, String> {
    let sql = format!(
        "SELECT current_scene_id FROM play_campaigns WHERE id = '{}';",
        sql_escape(campaign_id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err("play campaign not found".to_string());
    }
    let current_scene_id = extract_string(objects[0], "current_scene_id")
        .ok_or("missing current_scene_id")?;
    if current_scene_id.is_empty() {
        return Ok(None);
    }
    let (name, status) = play_scene_get(campaign_id, &current_scene_id)?;
    Ok(Some((current_scene_id.to_string(), name, status)))
}

/// Check whether a scheduled session exists within a campaign.
pub fn session_exists(campaign_id: &str, id: &str) -> Result<bool, String> {
    let sql = format!(
        "SELECT 1 FROM campaign_sessions WHERE campaign_id = '{}' AND session_id = '{}';",
        sql_escape(campaign_id),
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Create a scheduled campaign session and its agenda items.
pub fn session_create(
    campaign_id: &str,
    id: &str,
    starts_at: &str,
    duration_minutes: i64,
    agenda: &[String],
) -> Result<(), String> {
    let mut sql = String::from("BEGIN;");
    sql.push_str(&format!(
        "INSERT INTO campaign_sessions (campaign_id, session_id, starts_at, duration_minutes) VALUES ('{}', '{}', '{}', {});",
        sql_escape(campaign_id),
        sql_escape(id),
        sql_escape(starts_at),
        duration_minutes
    ));
    for (position, item) in agenda.iter().enumerate() {
        sql.push_str(&format!(
            "INSERT INTO session_agenda (campaign_id, session_id, position, item) VALUES ('{}', '{}', {}, '{}');",
            sql_escape(campaign_id),
            sql_escape(id),
            position,
            sql_escape(item)
        ));
    }
    sql.push_str("COMMIT;");
    sqlite_exec(&sql)
}

/// Return the earliest scheduled session for a campaign, if any.
///
/// ISO 8601 UTC strings with the same timezone are sorted correctly
/// lexicographically, so the query simply orders by `starts_at`.
pub fn session_get_next(campaign_id: &str) -> Result<Option<(String, String, i64, i64)>, String> {
    let sql = format!(
        "SELECT session_id, starts_at, duration_minutes FROM campaign_sessions WHERE campaign_id = '{}' ORDER BY starts_at ASC LIMIT 1;",
        sql_escape(campaign_id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Ok(None);
    }
    let obj = objects[0];
    let session_id = extract_string(obj, "session_id").ok_or("missing session_id")?;
    let starts_at = extract_string(obj, "starts_at").ok_or("missing starts_at")?;
    let duration_minutes = extract_int(obj, "duration_minutes").ok_or("missing duration_minutes")?;

    let count_sql = format!(
        "SELECT COUNT(*) AS agenda_count FROM session_agenda WHERE campaign_id = '{}' AND session_id = '{}';",
        sql_escape(campaign_id),
        sql_escape(session_id)
    );
    let count_output = sqlite_query(&count_sql)?;
    let count_content = extract_top_array_content(&count_output).unwrap_or("");
    let count_objects = extract_objects(count_content);
    let agenda_count = if count_objects.is_empty() {
        0
    } else {
        extract_int(count_objects[0], "agenda_count").unwrap_or(0)
    };

    Ok(Some((session_id.to_string(), starts_at.to_string(), duration_minutes, agenda_count)))
}

/// Store attendance records for a campaign session, replacing any previous records.
pub fn session_set_attendance(
    campaign_id: &str,
    session_id: &str,
    present: &[String],
    absent: &[String],
) -> Result<(), String> {
    let mut sql = String::from("BEGIN;");
    sql.push_str(&format!(
        "DELETE FROM session_attendance WHERE campaign_id = '{}' AND session_id = '{}';",
        sql_escape(campaign_id),
        sql_escape(session_id)
    ));
    for character_id in present {
        sql.push_str(&format!(
            "INSERT INTO session_attendance (campaign_id, session_id, character_id, present) VALUES ('{}', '{}', '{}', 1);",
            sql_escape(campaign_id),
            sql_escape(session_id),
            sql_escape(character_id)
        ));
    }
    for character_id in absent {
        sql.push_str(&format!(
            "INSERT INTO session_attendance (campaign_id, session_id, character_id, present) VALUES ('{}', '{}', '{}', 0);",
            sql_escape(campaign_id),
            sql_escape(session_id),
            sql_escape(character_id)
        ));
    }
    sql.push_str("COMMIT;");
    sqlite_exec(&sql)
}

/// Check whether a location exists within a play campaign.
pub fn play_location_exists(campaign_id: &str, id: &str) -> Result<bool, String> {
    let sql = format!(
        "SELECT 1 FROM play_locations WHERE campaign_id = '{}' AND id = '{}';",
        sql_escape(campaign_id),
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Create a new location for a play campaign.
pub fn play_location_create(campaign_id: &str, id: &str, name: &str) -> Result<(), String> {
    let sql = format!(
        "INSERT INTO play_locations (campaign_id, id, name) VALUES ('{}', '{}', '{}');\nUPDATE play_campaigns SET current_location_id = '{}' WHERE id = '{}' AND current_location_id = '';",
        sql_escape(campaign_id),
        sql_escape(id),
        sql_escape(name),
        sql_escape(id),
        sql_escape(campaign_id)
    );
    sqlite_exec(&sql)
}

/// Check whether a directed connection already exists between two locations.
pub fn play_location_connection_exists(
    campaign_id: &str,
    from_id: &str,
    to_id: &str,
) -> Result<bool, String> {
    let sql = format!(
        "SELECT 1 FROM play_location_connections WHERE campaign_id = '{}' AND from_id = '{}' AND to_id = '{}';",
        sql_escape(campaign_id),
        sql_escape(from_id),
        sql_escape(to_id)
    );
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Create a directed connection between two play campaign locations.
pub fn play_location_connection_create(
    campaign_id: &str,
    from_id: &str,
    to_id: &str,
    travel_turns: i64,
) -> Result<(), String> {
    let sql = format!(
        "INSERT INTO play_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES ('{}', '{}', '{}', {});",
        sql_escape(campaign_id),
        sql_escape(from_id),
        sql_escape(to_id),
        travel_turns
    );
    sqlite_exec(&sql)
}

/// Return all outbound connections from a play campaign location.
///
/// Each tuple contains the destination id, destination name, and travel turns.
/// Results are ordered by destination id for deterministic output.
pub fn play_location_connections(
    campaign_id: &str,
    from_id: &str,
) -> Result<Vec<(String, String, i64)>, String> {
    let sql = format!(
        "SELECT c.to_id, l.name, c.travel_turns FROM play_location_connections c JOIN play_locations l ON l.campaign_id = c.campaign_id AND l.id = c.to_id WHERE c.campaign_id = '{}' AND c.from_id = '{}' ORDER BY c.to_id ASC;",
        sql_escape(campaign_id),
        sql_escape(from_id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let mut connections = Vec::new();
    for obj in extract_objects(content) {
        let to_id = extract_string(obj, "to_id").ok_or("missing to_id")?;
        let name = extract_string(obj, "name").ok_or("missing name")?;
        let travel_turns = extract_int(obj, "travel_turns").ok_or("missing travel_turns")?;
        connections.push((to_id.to_string(), name.to_string(), travel_turns));
    }
    Ok(connections)
}

/// Read the party's current location id for a play campaign, if one is set.
pub fn play_campaign_get_current_location(
    campaign_id: &str,
) -> Result<Option<String>, String> {
    let sql = format!(
        "SELECT current_location_id FROM play_campaigns WHERE id = '{}';",
        sql_escape(campaign_id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err("play campaign not found".to_string());
    }
    let loc = extract_string(objects[0], "current_location_id")
        .ok_or("missing current_location_id")?;
    if loc.is_empty() {
        Ok(None)
    } else {
        Ok(Some(loc.to_string()))
    }
}

/// Set the party's current location id for a play campaign.
pub fn play_campaign_set_current_location(
    campaign_id: &str,
    location_id: &str,
) -> Result<(), String> {
    let sql = format!(
        "UPDATE play_campaigns SET current_location_id = '{}' WHERE id = '{}';",
        sql_escape(location_id),
        sql_escape(campaign_id)
    );
    sqlite_exec(&sql)
}

/// Check whether an encounter id already exists within a play campaign.
pub fn play_encounter_exists(campaign_id: &str, id: &str) -> Result<bool, String> {
    let sql = format!(
        "SELECT 1 FROM play_encounters WHERE campaign_id = '{}' AND id = '{}';",
        sql_escape(campaign_id),
        sql_escape(id)
    );
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Return the status of a play encounter.
pub fn play_encounter_get_status(campaign_id: &str, encounter_id: &str) -> Result<String, String> {
    let sql = format!(
        "SELECT status FROM play_encounters WHERE campaign_id = '{}' AND id = '{}';",
        sql_escape(campaign_id),
        sql_escape(encounter_id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err("encounter not found".to_string());
    }
    let status = extract_string(objects[0], "status").ok_or("missing status")?;
    Ok(status.to_string())
}

/// Check whether a play campaign already has an active encounter.
pub fn play_campaign_active_encounter_exists(campaign_id: &str) -> Result<bool, String> {
    let sql = format!(
        "SELECT 1 FROM play_encounters WHERE campaign_id = '{}' AND status = 'active';",
        sql_escape(campaign_id)
    );
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Create an active encounter bound to a play campaign.
pub fn play_encounter_create(
    campaign_id: &str,
    id: &str,
    name: &str,
) -> Result<(), String> {
    let sql = format!(
        "INSERT INTO play_encounters (campaign_id, id, name, status, combatants) VALUES ('{}', '{}', '{}', 'active', '[]');",
        sql_escape(campaign_id),
        sql_escape(id),
        sql_escape(name)
    );
    sqlite_exec(&sql)
}

/// Check whether a monster id already exists within a play encounter.
pub fn play_encounter_monster_exists(
    campaign_id: &str,
    encounter_id: &str,
    monster_id: &str,
) -> Result<bool, String> {
    let sql = format!(
        "SELECT 1 FROM play_encounter_monsters WHERE campaign_id = '{}' AND encounter_id = '{}' AND monster_id = '{}';",
        sql_escape(campaign_id),
        sql_escape(encounter_id),
        sql_escape(monster_id)
    );
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Add a monster to a play encounter.
pub fn play_encounter_add_monster(
    campaign_id: &str,
    encounter_id: &str,
    monster_id: &str,
    name: &str,
    hp_max: i64,
    hp_current: i64,
    initiative: i64,
) -> Result<(), String> {
    let sql = format!(
        "INSERT INTO play_encounter_monsters (campaign_id, encounter_id, monster_id, name, hp_max, hp_current, initiative) VALUES ('{}', '{}', '{}', '{}', {}, {}, {});",
        sql_escape(campaign_id),
        sql_escape(encounter_id),
        sql_escape(monster_id),
        sql_escape(name),
        hp_max,
        hp_current,
        initiative
    );
    sqlite_exec(&sql)
}

/// Remove a monster from a play encounter.
pub fn play_encounter_remove_monster(
    campaign_id: &str,
    encounter_id: &str,
    monster_id: &str,
) -> Result<(), String> {
    let sql = format!(
        "DELETE FROM play_encounter_monsters WHERE campaign_id = '{}' AND encounter_id = '{}' AND monster_id = '{}';",
        sql_escape(campaign_id),
        sql_escape(encounter_id),
        sql_escape(monster_id)
    );
    sqlite_exec(&sql)
}

/// Return the current and maximum hit points for a play encounter monster.
pub fn play_encounter_monster_hp(
    campaign_id: &str,
    encounter_id: &str,
    monster_id: &str,
) -> Result<(i64, i64), String> {
    let sql = format!(
        "SELECT hp_current, hp_max FROM play_encounter_monsters WHERE campaign_id = '{}' AND encounter_id = '{}' AND monster_id = '{}';",
        sql_escape(campaign_id),
        sql_escape(encounter_id),
        sql_escape(monster_id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err("monster not found".to_string());
    }
    let hp_current = extract_int(objects[0], "hp_current").ok_or("missing hp_current")?;
    let hp_max = extract_int(objects[0], "hp_max").ok_or("missing hp_max")?;
    Ok((hp_current, hp_max))
}

/// Update a play encounter monster's current hit points.
pub fn play_encounter_monster_set_hp_current(
    campaign_id: &str,
    encounter_id: &str,
    monster_id: &str,
    hp_current: i64,
) -> Result<(), String> {
    let sql = format!(
        "UPDATE play_encounter_monsters SET hp_current = {} WHERE campaign_id = '{}' AND encounter_id = '{}' AND monster_id = '{}';",
        hp_current,
        sql_escape(campaign_id),
        sql_escape(encounter_id),
        sql_escape(monster_id)
    );
    sqlite_exec(&sql)
}

/// Check whether a party member is already bound as a combatant in a play encounter.
pub fn play_encounter_combatant_exists(
    campaign_id: &str,
    encounter_id: &str,
    member: &str,
) -> Result<bool, String> {
    let sql = format!(
        "SELECT 1 FROM play_encounter_combatants WHERE campaign_id = '{}' AND encounter_id = '{}' AND member = '{}';",
        sql_escape(campaign_id),
        sql_escape(encounter_id),
        sql_escape(member)
    );
    let output = sqlite_query(&sql)?;
    Ok(!output.trim().is_empty())
}

/// Bind a campaign party member as a combatant in a play encounter.
pub fn play_encounter_combatant_create(
    campaign_id: &str,
    encounter_id: &str,
    member: &str,
    character_id: &str,
    name: &str,
    initiative: i64,
) -> Result<(), String> {
    let sql = format!(
        "INSERT INTO play_encounter_combatants (campaign_id, encounter_id, member, character_id, name, initiative) VALUES ('{}', '{}', '{}', '{}', '{}', {});",
        sql_escape(campaign_id),
        sql_escape(encounter_id),
        sql_escape(member),
        sql_escape(character_id),
        sql_escape(name),
        initiative
    );
    sqlite_exec(&sql)
}

/// Remove a bound party member combatant from a play encounter.
pub fn play_encounter_combatant_remove(
    campaign_id: &str,
    encounter_id: &str,
    member: &str,
) -> Result<(), String> {
    let sql = format!(
        "DELETE FROM play_encounter_combatants WHERE campaign_id = '{}' AND encounter_id = '{}' AND member = '{}';",
        sql_escape(campaign_id),
        sql_escape(encounter_id),
        sql_escape(member)
    );
    sqlite_exec(&sql)
}

/// Return the stored turn state for a play encounter.
pub fn play_encounter_get_turn(
    campaign_id: &str,
    encounter_id: &str,
) -> Result<(i64, i64), String> {
    let sql = format!(
        "SELECT round, turn_index FROM play_encounters WHERE campaign_id = '{}' AND id = '{}';",
        sql_escape(campaign_id),
        sql_escape(encounter_id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err("encounter not found".to_string());
    }
    let round = extract_int(objects[0], "round").unwrap_or(1);
    let turn_index = extract_int(objects[0], "turn_index").unwrap_or(0);
    Ok((round, turn_index))
}

/// Update the stored turn state for a play encounter.
pub fn play_encounter_set_turn(
    campaign_id: &str,
    encounter_id: &str,
    round: i64,
    turn_index: i64,
) -> Result<(), String> {
    let sql = format!(
        "UPDATE play_encounters SET round = {}, turn_index = {} WHERE campaign_id = '{}' AND id = '{}';",
        round,
        turn_index,
        sql_escape(campaign_id),
        sql_escape(encounter_id)
    );
    sqlite_exec(&sql)
}

/// Return the persisted initiative order for a play encounter.
///
/// Identifiers are stored in the `play_encounter_order` table, ordered by
/// `position`. An empty list is returned as an empty Vec, which callers
/// should fall back to initiative sorting.
pub fn play_encounter_get_order(
    campaign_id: &str,
    encounter_id: &str,
) -> Result<Vec<String>, String> {
    let sql = format!(
        "SELECT identifier FROM play_encounter_order WHERE campaign_id = '{}' AND encounter_id = '{}' ORDER BY position ASC;",
        sql_escape(campaign_id),
        sql_escape(encounter_id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let mut order = Vec::new();
    for obj in extract_objects(content) {
        let id = extract_string(obj, "identifier")
            .ok_or("missing identifier")?
            .to_string();
        order.push(id);
    }
    Ok(order)
}

/// Persist a new initiative order for a play encounter.
///
/// `order` is a list of combatant identifiers (monster_id for monsters,
/// member actor for bound players) in the desired turn order. The existing
/// order rows are replaced in a single transaction.
pub fn play_encounter_set_order(
    campaign_id: &str,
    encounter_id: &str,
    order: &[String],
) -> Result<(), String> {
    let mut sql = String::from("BEGIN;");
    sql.push_str(&format!(
        "DELETE FROM play_encounter_order WHERE campaign_id = '{}' AND encounter_id = '{}';",
        sql_escape(campaign_id),
        sql_escape(encounter_id)
    ));
    for (position, id) in order.iter().enumerate() {
        sql.push_str(&format!(
            "INSERT INTO play_encounter_order (campaign_id, encounter_id, identifier, position) VALUES ('{}', '{}', '{}', {});",
            sql_escape(campaign_id),
            sql_escape(encounter_id),
            sql_escape(id),
            position
        ));
    }
    sql.push_str("COMMIT;");
    sqlite_exec(&sql)
}

/// Return all monsters bound to a play encounter, ordered by monster_id.
pub fn play_encounter_list_monsters(
    campaign_id: &str,
    encounter_id: &str,
) -> Result<Vec<(String, String, i64)>, String> {
    let sql = format!(
        "SELECT monster_id, name, initiative FROM play_encounter_monsters WHERE campaign_id = '{}' AND encounter_id = '{}' ORDER BY monster_id ASC;",
        sql_escape(campaign_id),
        sql_escape(encounter_id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let mut monsters = Vec::new();
    for obj in extract_objects(content) {
        let monster_id = extract_string(obj, "monster_id").ok_or("missing monster_id")?.to_string();
        let name = extract_string(obj, "name").ok_or("missing name")?.to_string();
        let initiative = extract_int(obj, "initiative").ok_or("missing initiative")?;
        monsters.push((monster_id, name, initiative));
    }
    Ok(monsters)
}

/// Return all party-member combatants bound to a play encounter, ordered by member.
pub fn play_encounter_list_combatants(
    campaign_id: &str,
    encounter_id: &str,
) -> Result<Vec<(String, String, i64)>, String> {
    let sql = format!(
        "SELECT member, name, initiative FROM play_encounter_combatants WHERE campaign_id = '{}' AND encounter_id = '{}' ORDER BY member ASC;",
        sql_escape(campaign_id),
        sql_escape(encounter_id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let mut members = Vec::new();
    for obj in extract_objects(content) {
        let member = extract_string(obj, "member").ok_or("missing member")?.to_string();
        let name = extract_string(obj, "name").ok_or("missing name")?.to_string();
        let initiative = extract_int(obj, "initiative").ok_or("missing initiative")?;
        members.push((member, name, initiative));
    }
    Ok(members)
}

/// Apply a named condition to an encounter combatant.
///
/// If the same condition already exists on the target, its remaining duration
/// is replaced.
pub fn play_encounter_add_condition(
    campaign_id: &str,
    encounter_id: &str,
    target: &str,
    condition: &str,
    remaining: i64,
) -> Result<(), String> {
    let sql = format!(
        "INSERT OR REPLACE INTO play_encounter_conditions (campaign_id, encounter_id, target, condition, remaining) VALUES ('{}', '{}', '{}', '{}', {});",
        sql_escape(campaign_id),
        sql_escape(encounter_id),
        sql_escape(target),
        sql_escape(condition),
        remaining
    );
    sqlite_exec(&sql)
}

/// Return all active conditions for a single target combatant.
pub fn play_encounter_conditions_for_target(
    campaign_id: &str,
    encounter_id: &str,
    target: &str,
) -> Result<Vec<(String, i64)>, String> {
    let sql = format!(
        "SELECT condition, remaining FROM play_encounter_conditions WHERE campaign_id = '{}' AND encounter_id = '{}' AND target = '{}' ORDER BY condition ASC;",
        sql_escape(campaign_id),
        sql_escape(encounter_id),
        sql_escape(target)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let mut list = Vec::new();
    for obj in extract_objects(content) {
        let name = extract_string(obj, "condition").ok_or("missing condition")?.to_string();
        let remaining = extract_int(obj, "remaining").ok_or("missing remaining")?;
        list.push((name, remaining));
    }
    Ok(list)
}

/// Return all active conditions for an encounter, grouped by target.
pub fn play_encounter_all_conditions(
    campaign_id: &str,
    encounter_id: &str,
) -> Result<Vec<(String, String, i64)>, String> {
    let sql = format!(
        "SELECT target, condition, remaining FROM play_encounter_conditions WHERE campaign_id = '{}' AND encounter_id = '{}' ORDER BY target ASC, condition ASC;",
        sql_escape(campaign_id),
        sql_escape(encounter_id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let mut list = Vec::new();
    for obj in extract_objects(content) {
        let target = extract_string(obj, "target").ok_or("missing target")?.to_string();
        let name = extract_string(obj, "condition").ok_or("missing condition")?.to_string();
        let remaining = extract_int(obj, "remaining").ok_or("missing remaining")?;
        list.push((target, name, remaining));
    }
    Ok(list)
}

/// Decrement active conditions on a target at the start of its turn, removing
/// any condition whose duration reaches zero.
pub fn play_encounter_decrement_conditions(
    campaign_id: &str,
    encounter_id: &str,
    target: &str,
) -> Result<Vec<(String, i64)>, String> {
    let update_sql = format!(
        "UPDATE play_encounter_conditions SET remaining = remaining - 1 WHERE campaign_id = '{}' AND encounter_id = '{}' AND target = '{}' AND remaining > 0;",
        sql_escape(campaign_id),
        sql_escape(encounter_id),
        sql_escape(target)
    );
    sqlite_exec(&update_sql)?;
    let delete_sql = format!(
        "DELETE FROM play_encounter_conditions WHERE campaign_id = '{}' AND encounter_id = '{}' AND target = '{}' AND remaining <= 0;",
        sql_escape(campaign_id),
        sql_escape(encounter_id),
        sql_escape(target)
    );
    sqlite_exec(&delete_sql)?;
    play_encounter_conditions_for_target(campaign_id, encounter_id, target)
}

/// Return the current reward record for a play encounter.
///
/// The returned tuple is `(xp_awarded, rewards_awarded, loot)` where
/// `loot` is a list of `(item_slug, quantity)` ordered by position.
pub fn play_encounter_get_rewards(
    campaign_id: &str,
    encounter_id: &str,
) -> Result<(i64, bool, Vec<(String, i64)>), String> {
    let sql = format!(
        "SELECT xp_awarded, rewards_awarded FROM play_encounters WHERE campaign_id = '{}' AND id = '{}';",
        sql_escape(campaign_id),
        sql_escape(encounter_id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let objects = extract_objects(content);
    if objects.is_empty() {
        return Err("encounter not found".to_string());
    }
    let xp_awarded = extract_int(objects[0], "xp_awarded").unwrap_or(0);
    let rewards_awarded = extract_int(objects[0], "rewards_awarded").unwrap_or(0) != 0;
    let loot = play_encounter_get_loot(campaign_id, encounter_id)?;
    Ok((xp_awarded, rewards_awarded, loot))
}

/// Return all loot entries for a play encounter in position order.
pub fn play_encounter_get_loot(
    campaign_id: &str,
    encounter_id: &str,
) -> Result<Vec<(String, i64)>, String> {
    let sql = format!(
        "SELECT item_slug, quantity FROM play_encounter_loot WHERE campaign_id = '{}' AND encounter_id = '{}' ORDER BY position ASC;",
        sql_escape(campaign_id),
        sql_escape(encounter_id)
    );
    let output = sqlite_query(&sql)?;
    let content = extract_top_array_content(&output).unwrap_or("");
    let mut loot = Vec::new();
    for obj in extract_objects(content) {
        let slug = extract_string(obj, "item_slug").ok_or("missing item_slug")?.to_string();
        let quantity = extract_int(obj, "quantity").ok_or("missing quantity")?;
        loot.push((slug, quantity));
    }
    Ok(loot)
}

/// Store a reward record for a play encounter, replacing any prior loot.
///
/// `loot` is a list of `(item_slug, quantity)` ordered by position.
pub fn play_encounter_set_rewards(
    campaign_id: &str,
    encounter_id: &str,
    xp: i64,
    loot: &[(String, i64)],
) -> Result<(), String> {
    let mut sql = String::from("BEGIN;");
    sql.push_str(&format!(
        "UPDATE play_encounters SET xp_awarded = {}, rewards_awarded = 1 WHERE campaign_id = '{}' AND id = '{}';",
        xp,
        sql_escape(campaign_id),
        sql_escape(encounter_id)
    ));
    sql.push_str(&format!(
        "DELETE FROM play_encounter_loot WHERE campaign_id = '{}' AND encounter_id = '{}';",
        sql_escape(campaign_id),
        sql_escape(encounter_id)
    ));
    for (position, (slug, quantity)) in loot.iter().enumerate() {
        sql.push_str(&format!(
            "INSERT INTO play_encounter_loot (campaign_id, encounter_id, item_slug, quantity, position) VALUES ('{}', '{}', '{}', {}, {});",
            sql_escape(campaign_id),
            sql_escape(encounter_id),
            sql_escape(slug),
            quantity,
            position
        ));
    }
    sql.push_str("COMMIT;");
    sqlite_exec(&sql)
}

/// Mark a play encounter as closed.
pub fn play_encounter_close(
    campaign_id: &str,
    encounter_id: &str,
) -> Result<(), String> {
    let sql = format!(
        "UPDATE play_encounters SET status = 'closed' WHERE campaign_id = '{}' AND id = '{}';",
        sql_escape(campaign_id),
        sql_escape(encounter_id)
    );
    sqlite_exec(&sql)
}


