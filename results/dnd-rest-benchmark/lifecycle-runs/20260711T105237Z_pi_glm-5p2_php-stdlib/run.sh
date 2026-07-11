#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Durable game-world and game-state data lives in SQLite (game.db). Wipe it on
# startup so state lives only for this server process lifetime (matching
# prior-stage semantics), then pre-initialize the schema. index.php also
# lazily ensures the schema on every request.
rm -f game.db .combat_sessions.json .users.json
php db.php
php -S 127.0.0.1:"$PORT" index.php
