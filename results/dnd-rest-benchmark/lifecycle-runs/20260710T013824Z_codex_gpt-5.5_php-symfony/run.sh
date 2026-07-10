#!/usr/bin/env bash
set -euo pipefail
php -r '$port = getenv("PORT") ?: "default"; $path = sys_get_temp_dir() . "/dnd-combat-sessions-" . preg_replace("/[^A-Za-z0-9_.-]/", "_", $port) . ".json"; if (is_file($path)) { unlink($path); }'
exec php -S 127.0.0.1:"$PORT" index.php
