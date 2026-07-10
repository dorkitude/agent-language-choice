#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
rm -f "$DIR/combat_state.json"
php -S 127.0.0.1:"$PORT" "$DIR/index.php"
