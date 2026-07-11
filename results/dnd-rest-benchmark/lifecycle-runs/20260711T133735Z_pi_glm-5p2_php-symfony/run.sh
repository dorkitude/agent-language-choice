#!/usr/bin/env bash
set -euo pipefail

# Start each server run with a clean durable database and no stale temp state
# from the previous (file-backed) implementation.
rm -f game.db
rm -f "$(php -r 'echo sys_get_temp_dir();')"/dnd_combat_*.json "$(php -r 'echo sys_get_temp_dir();')"/dnd_users_*.json 2>/dev/null || true

# Initialize the SQLite schema so game.db exists before serving.
php index.php init-schema

# Serve in the foreground on 127.0.0.1:$PORT.
php -S 127.0.0.1:"$PORT" index.php
