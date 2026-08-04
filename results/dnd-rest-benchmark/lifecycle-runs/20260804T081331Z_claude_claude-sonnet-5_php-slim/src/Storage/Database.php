<?php

declare(strict_types=1);

namespace App\Storage;

use PDO;

/**
 * SQLite connection + schema management. All domain tables store their
 * payload as a single JSON `data` column keyed by a natural id/slug; this
 * keeps the schema stable while route handlers evolve the JSON shape.
 */
final class Database
{
    public const SCHEMA_VERSION = 1;

    private static ?PDO $pdo = null;
    private static ?string $cachedFile = null;

    /** Returns a cached PDO connection for $file, initializing the schema on first connect. */
    public static function connect(string $file): PDO
    {
        if (self::$pdo !== null && self::$cachedFile === $file) {
            return self::$pdo;
        }

        $pdo = new PDO('sqlite:' . $file);
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

        self::$pdo = $pdo;
        self::$cachedFile = $file;

        self::initSchema($pdo);

        return $pdo;
    }

    /**
     * CREATE TABLE bodies keyed by table name. Single source of truth for both
     * initSchema (create) and resetSchema (drop), so the two can't drift apart.
     */
    private const TABLES = [
        'meta' => '(key TEXT PRIMARY KEY, value TEXT NOT NULL)',
        'combat_sessions' => '(id TEXT PRIMARY KEY, data TEXT NOT NULL)',
        'users' => '(username TEXT PRIMARY KEY, data TEXT NOT NULL)',
        'monsters' => '(slug TEXT PRIMARY KEY, data TEXT NOT NULL)',
        'items' => '(slug TEXT PRIMARY KEY, data TEXT NOT NULL)',
        'campaigns' => '(id TEXT PRIMARY KEY, data TEXT NOT NULL)',
        'campaign_characters' => '(id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, data TEXT NOT NULL)',
        'campaign_events' => '(id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, data TEXT NOT NULL)',
        'campaign_quests' => '(id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, data TEXT NOT NULL)',
        'campaign_factions' => '(id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, data TEXT NOT NULL)',
        'campaign_npcs' => '(id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, data TEXT NOT NULL)',
        'campaign_inventory' => '(id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, data TEXT NOT NULL)',
        'campaign_equipment' => '(id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, data TEXT NOT NULL)',
        'campaign_crafting' => '(id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, data TEXT NOT NULL)',
        'campaign_sessions' => '(id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, data TEXT NOT NULL)',
        'play_campaigns' => '(id TEXT PRIMARY KEY, data TEXT NOT NULL)',
        'play_campaign_members' => '(id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL, data TEXT NOT NULL)',
        'play_campaign_events' => '(id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, data TEXT NOT NULL)',
    ];

    public static function initSchema(PDO $pdo): void
    {
        foreach (self::TABLES as $name => $columns) {
            $pdo->exec("CREATE TABLE IF NOT EXISTS $name $columns");
        }

        $stmt = $pdo->prepare('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)');
        $stmt->execute(['schema_version', (string) self::SCHEMA_VERSION]);
        $stmt->execute(['initialized', '1']);
    }

    /** Drops and recreates every table. Used by POST /v1/storage/reset. */
    public static function resetSchema(PDO $pdo): void
    {
        foreach (array_keys(self::TABLES) as $name) {
            $pdo->exec("DROP TABLE IF EXISTS $name");
        }
        self::initSchema($pdo);
    }
}
