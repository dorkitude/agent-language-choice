<?php

declare(strict_types=1);

/**
 * SQLite persistence layer.
 *
 * Every request starts with initDatabase(), which makes the schema idempotent.
 * The single SQLite file lives at <project-root>/game.db.
 */

function dbPath(): string
{
    return ROOT_DIR . '/game.db';
}

function db(): PDO
{
    static $pdo = null;
    if ($pdo === null) {
        $pdo = new PDO('sqlite:' . dbPath());
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $pdo->setAttribute(PDO::ATTR_STRINGIFY_FETCHES, false);
    }
    return $pdo;
}

function initDatabase(): void
{
    $pdo = db();
    $pdo->exec('
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS combat_sessions (
            id TEXT PRIMARY KEY,
            round INTEGER NOT NULL,
            turn_index INTEGER NOT NULL,
            order_json TEXT NOT NULL,
            conditions_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS monsters (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            cr TEXT NOT NULL,
            armor_class INTEGER NOT NULL,
            hit_points INTEGER NOT NULL,
            tags_json TEXT NOT NULL
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
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            name TEXT NOT NULL,
            level INTEGER NOT NULL,
            class TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
        );
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            summary TEXT
        );
        CREATE TABLE IF NOT EXISTS quests (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            milestones_json TEXT NOT NULL,
            completed_milestones_json TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
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
            faction_id TEXT,
            disposition INTEGER NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
        );
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            owner TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
        );
        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
            FOREIGN KEY (character_id) REFERENCES characters(id)
        );
        CREATE TABLE IF NOT EXISTS crafting_projects (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            days_required INTEGER NOT NULL,
            days_completed INTEGER NOT NULL,
            status TEXT NOT NULL,
            cost_gp INTEGER NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            agenda_json TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
        );
        CREATE TABLE IF NOT EXISTS session_attendance (
            session_id TEXT PRIMARY KEY,
            present_json TEXT NOT NULL,
            absent_json TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );
        CREATE TABLE IF NOT EXISTS play_campaigns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            owner TEXT NOT NULL,
            status TEXT NOT NULL,
            max_players INTEGER NOT NULL
        );
    ');
    $stmt = $pdo->prepare('INSERT OR REPLACE INTO schema_version (version) VALUES (?)');
    $stmt->execute([1]);
}

function resetDatabase(): void
{
    $pdo = db();
    $pdo->exec('
        DROP TABLE IF EXISTS users;
        DROP TABLE IF EXISTS combat_sessions;
        DROP TABLE IF EXISTS monsters;
        DROP TABLE IF EXISTS items;
        DROP TABLE IF EXISTS campaigns;
        DROP TABLE IF EXISTS characters;
        DROP TABLE IF EXISTS events;
        DROP TABLE IF EXISTS quests;
        DROP TABLE IF EXISTS factions;
        DROP TABLE IF EXISTS npcs;
        DROP TABLE IF EXISTS inventory;
        DROP TABLE IF EXISTS equipment;
        DROP TABLE IF EXISTS crafting_projects;
        DROP TABLE IF EXISTS sessions;
        DROP TABLE IF EXISTS session_attendance;
        DROP TABLE IF EXISTS play_campaigns;
        DROP TABLE IF EXISTS schema_version;
    ');
    initDatabase();
}

function isInitialized(): bool
{
    try {
        $pdo = db();
        $tables = $pdo->query("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('schema_version', 'users', 'combat_sessions', 'monsters', 'items', 'campaigns', 'characters', 'events', 'quests', 'factions', 'npcs', 'inventory', 'equipment', 'crafting_projects', 'sessions', 'session_attendance', 'play_campaigns')")->fetchAll(PDO::FETCH_COLUMN);
        return count($tables) === 17;
    } catch (PDOException $e) {
        return false;
    }
}
