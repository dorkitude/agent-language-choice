#!/usr/bin/env bash
set -euo pipefail
rm -f game.db .combat_state.json .users.json
php -S 127.0.0.1:"$PORT" index.php
