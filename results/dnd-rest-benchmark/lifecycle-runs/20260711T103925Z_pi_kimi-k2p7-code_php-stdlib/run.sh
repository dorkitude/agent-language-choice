#!/usr/bin/env bash
set -euo pipefail
rm -f .combat-state.json .users.json game.db
exec php -S 127.0.0.1:"$PORT" index.php
