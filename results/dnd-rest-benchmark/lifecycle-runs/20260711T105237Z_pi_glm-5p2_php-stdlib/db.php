<?php

declare(strict_types=1);

/**
 * SQLite-backed durable storage for the D&D REST API.
 *
 * Schema version 1. Tables:
 *   schema_meta(key TEXT PK, value TEXT)   — schema_version, initialized flags
 *   combat_sessions(id TEXT PK, data TEXT) — one JSON blob per session
 *   users(username TEXT PK, password_hash TEXT, role TEXT)
 *
 * The PHP built-in server re-executes the router per request, so db() opens a
 * fresh PDO connection per request and idempotently ensures the schema on first
 * use. run.sh pre-initializes the schema before starting the server; index.php
 * also lazily ensures it on every request. Storage helpers (load/save combat
 * sessions and users) are drop-in replacements for the prior JSON-file helpers
 * so the handlers are unchanged.
 */

function db_path(): string
{
    return __DIR__ . '/game.db';
}

function db_init_schema(PDO $pdo): void
{
    $pdo->exec('CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )');
    $pdo->exec("INSERT OR IGNORE INTO schema_meta(key, value) VALUES('schema_version', '1')");
    $pdo->exec("INSERT OR IGNORE INTO schema_meta(key, value) VALUES('initialized', '1')");
    $pdo->exec('CREATE TABLE IF NOT EXISTS combat_sessions (
        id TEXT PRIMARY KEY,
        data TEXT NOT NULL
    )');
    $pdo->exec('CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL
    )');
    // Compendium tables (Stage 5). Tags stored as a JSON array string.
    $pdo->exec('CREATE TABLE IF NOT EXISTS monsters (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        cr TEXT NOT NULL,
        armor_class INTEGER NOT NULL,
        hit_points INTEGER NOT NULL,
        tags TEXT NOT NULL DEFAULT "[]"
    )');
    $pdo->exec('CREATE TABLE IF NOT EXISTS items (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        rarity TEXT NOT NULL,
        cost_gp INTEGER NOT NULL
    )');
    // Campaign state tables (Stage 6). Characters and events are sub-resources
    // keyed by (campaign_id, id); rowid preserves insertion order for the
    // state read.
    $pdo->exec('CREATE TABLE IF NOT EXISTS campaigns (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        dm TEXT NOT NULL
    )');
    $pdo->exec('CREATE TABLE IF NOT EXISTS campaign_characters (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        name TEXT NOT NULL,
        level INTEGER NOT NULL,
        class TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
    )');
    $pdo->exec('CREATE TABLE IF NOT EXISTS campaign_events (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        kind TEXT NOT NULL,
        summary TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
    )');
}

function db(): PDO
{
    static $pdo = null;
    if ($pdo === null) {
        $pdo = new PDO('sqlite:' . db_path());
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
        db_init_schema($pdo);
    }
    return $pdo;
}

/**
 * Drop benchmark-created durable data and recreate the schema.
 */
function db_reset(): void
{
    $pdo = db();
    $pdo->exec('DROP TABLE IF EXISTS combat_sessions');
    $pdo->exec('DROP TABLE IF EXISTS users');
    $pdo->exec('DROP TABLE IF EXISTS monsters');
    $pdo->exec('DROP TABLE IF EXISTS items');
    $pdo->exec('DROP TABLE IF EXISTS campaigns');
    $pdo->exec('DROP TABLE IF EXISTS campaign_characters');
    $pdo->exec('DROP TABLE IF EXISTS campaign_events');
    db_init_schema($pdo);
}

/* ----------------------------------------------- combat session persistence */

function load_combat_sessions(): array
{
    $stmt = db()->query('SELECT id, data FROM combat_sessions');
    $out = [];
    foreach ($stmt as $row) {
        $data = json_decode((string) $row['data'], true);
        if (is_array($data)) {
            $out[$row['id']] = $data;
        }
    }
    return $out;
}

function save_combat_sessions(array $sessions): void
{
    $pdo = db();
    $pdo->beginTransaction();
    try {
        $pdo->exec('DELETE FROM combat_sessions');
        $stmt = $pdo->prepare('INSERT INTO combat_sessions(id, data) VALUES(:id, :data)');
        foreach ($sessions as $id => $sess) {
            $stmt->execute([':id' => (string) $id, ':data' => json_encode($sess)]);
        }
        $pdo->commit();
    } catch (Throwable $e) {
        if ($pdo->inTransaction()) {
            $pdo->rollBack();
        }
        throw $e;
    }
}

/* --------------------------------------------------------- user persistence */

function load_users(): array
{
    $stmt = db()->query('SELECT username, password_hash, role FROM users');
    $out = [];
    foreach ($stmt as $row) {
        $out[$row['username']] = [
            'username' => $row['username'],
            'password_hash' => $row['password_hash'],
            'role' => $row['role'],
        ];
    }
    return $out;
}

function save_users(array $users): void
{
    $pdo = db();
    $pdo->beginTransaction();
    try {
        $pdo->exec('DELETE FROM users');
        $stmt = $pdo->prepare(
            'INSERT INTO users(username, password_hash, role) VALUES(:u, :p, :r)'
        );
        foreach ($users as $username => $u) {
            $stmt->execute([
                ':u' => (string) $username,
                ':p' => (string) $u['password_hash'],
                ':r' => (string) $u['role'],
            ]);
        }
        $pdo->commit();
    } catch (Throwable $e) {
        if ($pdo->inTransaction()) {
            $pdo->rollBack();
        }
        throw $e;
    }
}

// When executed directly (e.g. `php db.php` from run.sh), pre-initialize the
// schema so game.db exists before the server accepts its first request. When
// required by index.php under the built-in server, this block is skipped.
if (PHP_SAPI === 'cli'
    && realpath(__FILE__) === realpath((string) ($_SERVER['SCRIPT_FILENAME'] ?? ''))
) {
    db();
}
