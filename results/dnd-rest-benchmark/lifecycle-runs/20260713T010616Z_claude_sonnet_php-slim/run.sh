#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
rm -f combat_state.json users_state.json game.db
php -S 127.0.0.1:"$PORT" index.php
