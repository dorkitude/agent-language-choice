#!/usr/bin/env bash
set -euo pipefail
rm -f .combat_sessions.json
php -S 127.0.0.1:"$PORT" index.php
