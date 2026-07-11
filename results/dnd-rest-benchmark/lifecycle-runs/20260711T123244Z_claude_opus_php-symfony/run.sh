#!/usr/bin/env bash
set -euo pipefail
# Durable game-world and game-state data lives in a SQLite database. Each
# server run starts from a fresh database so state only lasts the server's
# lifetime, matching prior stages' clear-on-startup behavior.
export DND_DB_FILE="${DND_DB_FILE:-$PWD/game.db}"
rm -f "$DND_DB_FILE" "$DND_DB_FILE-wal" "$DND_DB_FILE-shm"
# Initialize the schema on startup (CLI SAPI init mode exits after preparing
# the database), then serve requests in the foreground.
php index.php
php -S 127.0.0.1:"$PORT" index.php
