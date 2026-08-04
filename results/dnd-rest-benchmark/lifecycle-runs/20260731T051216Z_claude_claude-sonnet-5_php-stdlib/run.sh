#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
rm -f combat_sessions.json users.json game.db
php -S 127.0.0.1:"$PORT" index.php
