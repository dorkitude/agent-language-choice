#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Start each server process with a fresh durable store, matching prior stages
# where a new server process began with empty game state.
rm -f game.db game.db-wal game.db-shm

# Initialize the SQLite schema on startup.
php index.php

php -S 127.0.0.1:"$PORT" index.php
