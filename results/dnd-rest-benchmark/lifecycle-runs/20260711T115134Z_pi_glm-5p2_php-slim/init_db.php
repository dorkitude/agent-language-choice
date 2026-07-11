<?php

/**
 * Pre-create the SQLite database and schema so game.db exists on server
 * startup. The application re-ensures the schema idempotently on first
 * request and manages a PID marker for fresh state per server-process start.
 *
 * Kept in lockstep with Database::createSchema() in index.php.
 */
$pdo = new PDO('sqlite:' . __DIR__ . '/game.db');
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
$pdo->exec('CREATE TABLE IF NOT EXISTS schema_meta ('
    . ' key TEXT PRIMARY KEY,'
    . ' value TEXT NOT NULL'
    . ')');
$pdo->exec('CREATE TABLE IF NOT EXISTS combat_sessions ('
    . ' id TEXT PRIMARY KEY,'
    . ' data TEXT NOT NULL'
    . ')');
$pdo->exec('CREATE TABLE IF NOT EXISTS users ('
    . ' username TEXT PRIMARY KEY,'
    . ' password_hash TEXT NOT NULL,'
    . ' role TEXT NOT NULL'
    . ')');
$pdo->exec('CREATE TABLE IF NOT EXISTS monsters ('
    . ' slug TEXT PRIMARY KEY,'
    . ' name TEXT NOT NULL,'
    . ' cr TEXT NOT NULL,'
    . ' armor_class INTEGER NOT NULL,'
    . ' hit_points INTEGER NOT NULL,'
    . ' tags TEXT NOT NULL DEFAULT "[]"'
    . ')');
$pdo->exec('CREATE TABLE IF NOT EXISTS items ('
    . ' slug TEXT PRIMARY KEY,'
    . ' name TEXT NOT NULL,'
    . ' type TEXT NOT NULL,'
    . ' rarity TEXT NOT NULL,'
    . ' cost_gp INTEGER NOT NULL'
    . ')');
$pdo->exec('CREATE TABLE IF NOT EXISTS campaigns ('
    . ' id TEXT PRIMARY KEY,'
    . ' name TEXT NOT NULL,'
    . ' dm TEXT NOT NULL'
    . ')');
$pdo->exec('CREATE TABLE IF NOT EXISTS campaign_characters ('
    . ' campaign_id TEXT NOT NULL,'
    . ' id TEXT NOT NULL,'
    . ' name TEXT NOT NULL,'
    . ' level INTEGER NOT NULL,'
    . ' class TEXT NOT NULL,'
    . ' PRIMARY KEY (campaign_id, id)'
    . ')');
$pdo->exec('CREATE TABLE IF NOT EXISTS campaign_events ('
    . ' campaign_id TEXT NOT NULL,'
    . ' id TEXT NOT NULL,'
    . ' kind TEXT NOT NULL,'
    . ' summary TEXT NOT NULL,'
    . ' PRIMARY KEY (campaign_id, id)'
    . ')');
$pdo->exec("INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', '1')");
