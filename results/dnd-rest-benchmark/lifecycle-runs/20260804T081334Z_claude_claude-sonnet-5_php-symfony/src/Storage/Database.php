<?php

namespace App\Storage;

use PDO;

/**
 * Owns the single SQLite connection and the schema for both the relational
 * tables (monsters, items, campaigns, ...) and the generic kv_store table
 * used by App\Storage\KvStore for document-shaped state (combat sessions,
 * users, play campaigns).
 */
final class Database
{
    public const SCHEMA_VERSION = 1;

    private static ?PDO $connection = null;

    private function __construct()
    {
    }

    public static function file(): string
    {
        return dirname(__DIR__, 2) . '/game.db';
    }

    /** Lazily opens (or returns the cached) SQLite connection for the process. */
    public static function connection(): PDO
    {
        if (self::$connection === null) {
            $db = new PDO('sqlite:' . self::file());
            $db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
            $db->exec('PRAGMA journal_mode = WAL');
            $db->exec('PRAGMA busy_timeout = 5000');
            self::$connection = $db;
        }
        return self::$connection;
    }

    /** Creates every table/seed row if missing. Safe to call on every request. */
    public static function initSchema(PDO $db): void
    {
        $db->exec('CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT NOT NULL)');
        $db->exec('CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)');
        $db->exec('CREATE TABLE IF NOT EXISTS monsters (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            cr TEXT NOT NULL,
            armor_class INTEGER NOT NULL,
            hit_points INTEGER NOT NULL,
            tags TEXT NOT NULL
        )');
        $db->exec('CREATE TABLE IF NOT EXISTS items (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            rarity TEXT NOT NULL,
            cost_gp INTEGER NOT NULL
        )');
        $db->exec('CREATE TABLE IF NOT EXISTS campaigns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            dm TEXT NOT NULL
        )');
        $db->exec('CREATE TABLE IF NOT EXISTS campaign_characters (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            name TEXT NOT NULL,
            level INTEGER NOT NULL,
            class TEXT NOT NULL
        )');
        $db->exec('CREATE TABLE IF NOT EXISTS campaign_events (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            summary TEXT NOT NULL
        )');
        $db->exec('CREATE TABLE IF NOT EXISTS campaign_quests (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            milestones TEXT NOT NULL,
            milestones_done TEXT NOT NULL
        )');
        $db->exec('CREATE TABLE IF NOT EXISTS campaign_factions (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            name TEXT NOT NULL,
            stance TEXT NOT NULL
        )');
        $db->exec('CREATE TABLE IF NOT EXISTS campaign_npcs (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            name TEXT NOT NULL,
            faction_id TEXT,
            disposition INTEGER NOT NULL
        )');
        $db->exec('CREATE TABLE IF NOT EXISTS campaign_inventory (
            campaign_id TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            owner TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, item_slug, owner)
        )');
        $db->exec('CREATE TABLE IF NOT EXISTS campaign_equipment (
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, character_id, item_slug)
        )');
        $db->exec('CREATE TABLE IF NOT EXISTS campaign_crafting (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            character_id TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            days_required INTEGER NOT NULL,
            cost_gp INTEGER NOT NULL,
            days_completed INTEGER NOT NULL,
            status TEXT NOT NULL
        )');
        $db->exec('CREATE TABLE IF NOT EXISTS campaign_sessions (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            agenda TEXT NOT NULL,
            present TEXT NOT NULL,
            absent TEXT NOT NULL
        )');

        $stmt = $db->prepare('INSERT OR IGNORE INTO schema_meta (key, value) VALUES (?, ?)');
        $stmt->execute(['schema_version', (string) self::SCHEMA_VERSION]);
        $stmt->execute(['initialized', '1']);

        $stmt = $db->prepare('INSERT OR IGNORE INTO kv_store (key, value) VALUES (?, ?)');
        $stmt->execute(['combat_sessions', json_encode(['sessions' => []])]);
        $stmt->execute(['users', json_encode(['users' => []])]);
    }

    /**
     * Wipes compendium/campaign tables and every kv_store document except
     * the registered-users list, then re-seeds. Used by POST
     * /v1/storage/reset. Accounts survive a reset since they are
     * identity state, not campaign content; combat sessions and play
     * campaigns are wiped along with everything else in kv_store.
     */
    public static function resetSchema(PDO $db): void
    {
        $db->exec("DELETE FROM kv_store WHERE key NOT IN ('users')");
        $db->exec('DELETE FROM schema_meta');
        $db->exec('DELETE FROM monsters');
        $db->exec('DELETE FROM items');
        $db->exec('DELETE FROM campaigns');
        $db->exec('DELETE FROM campaign_characters');
        $db->exec('DELETE FROM campaign_events');
        $db->exec('DELETE FROM campaign_quests');
        $db->exec('DELETE FROM campaign_factions');
        $db->exec('DELETE FROM campaign_npcs');
        $db->exec('DELETE FROM campaign_inventory');
        $db->exec('DELETE FROM campaign_equipment');
        $db->exec('DELETE FROM campaign_crafting');
        $db->exec('DELETE FROM campaign_sessions');
        self::initSchema($db);
    }
}
