#!/usr/bin/env bash
set -euo pipefail
php -r "require __DIR__ . '/storage.php'; initializeDatabase();"
php -S 127.0.0.1:"$PORT" index.php
