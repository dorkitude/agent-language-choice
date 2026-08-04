#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
php -r '
    $db = new PDO("sqlite:" . getcwd() . "/game.db", null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
    require "storage.php";
    initializeSchema($db);
'
exec php -S 127.0.0.1:"$PORT" index.php
