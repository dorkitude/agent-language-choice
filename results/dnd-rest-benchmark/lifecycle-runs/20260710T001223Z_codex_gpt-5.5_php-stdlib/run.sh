#!/usr/bin/env bash
set -euo pipefail
export DND_COMBAT_STATE_FILE="${TMPDIR:-/tmp}/dnd-rest-combat-${PORT}.json"
rm -f "$DND_COMBAT_STATE_FILE"
php -S 127.0.0.1:"$PORT" index.php
