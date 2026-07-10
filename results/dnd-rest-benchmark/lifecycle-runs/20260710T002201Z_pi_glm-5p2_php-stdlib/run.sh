#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
rm -f .combat-sessions.json
php -S 127.0.0.1:"$PORT" index.php
