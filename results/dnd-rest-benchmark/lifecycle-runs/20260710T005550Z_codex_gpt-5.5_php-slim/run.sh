#!/usr/bin/env bash
set -euo pipefail

if [ ! -d vendor ]; then
  COMPOSER_CACHE_DIR="${COMPOSER_CACHE_DIR:-$(pwd)/.composer-cache}" composer install --no-interaction --no-progress
fi

export COMBAT_STATE_TOKEN="$$"
exec php -S 127.0.0.1:"$PORT" index.php
