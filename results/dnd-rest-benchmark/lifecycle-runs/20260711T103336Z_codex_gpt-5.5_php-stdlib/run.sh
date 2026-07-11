#!/usr/bin/env bash
set -euo pipefail
export COMBAT_STATE_FILE="$PWD/.combat-state-${PORT}.json"
rm -f "$COMBAT_STATE_FILE"
php -S 127.0.0.1:"$PORT" index.php
