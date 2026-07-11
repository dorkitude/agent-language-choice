#!/usr/bin/env bash
set -euo pipefail
rm -f "$(dirname "$0")/game.db"
rm -f "$(dirname "$0")/game.db-wal"
rm -f "$(dirname "$0")/game.db-shm"
rm -f "$(dirname "$0")/combat_sessions.json"
rm -f "$(dirname "$0")/users.json"
php -S 127.0.0.1:"$PORT" index.php
