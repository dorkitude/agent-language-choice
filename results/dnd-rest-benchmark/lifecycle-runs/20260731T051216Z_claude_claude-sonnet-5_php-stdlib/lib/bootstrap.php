<?php
declare(strict_types=1);

// ---------------------------------------------------------------------------
// Bootstrap: request line + persistent SQLite handle for this process.
// ---------------------------------------------------------------------------

header('Content-Type: application/json');

$method = $_SERVER['REQUEST_METHOD'];
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);

const SCHEMA_VERSION = 1;
const TURN_TIMEOUT_WINDOW = 1;
// __DIR__ here is lib/, not the app root, because this file is require()'d
// from index.php rather than being the entry point itself -- so the db path
// must be anchored one level up to land next to index.php/run.sh, matching
// where the original single-file layout put it.
$dbFile = dirname(__DIR__) . '/game.db';
