#!/usr/bin/env bash
set -euo pipefail
rm -f game.db
INIT_DB=1 php index.php
exec php -S 127.0.0.1:"$PORT" index.php
