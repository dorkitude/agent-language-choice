#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
rm -f game.db game.db-wal game.db-shm
php -S 127.0.0.1:"$PORT" index.php
