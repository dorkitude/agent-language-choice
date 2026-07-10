#!/usr/bin/env bash
set -euo pipefail
PORT="${PORT:-8000}"
rm -f .combat_sessions*.json
php -S 127.0.0.1:"$PORT" index.php
