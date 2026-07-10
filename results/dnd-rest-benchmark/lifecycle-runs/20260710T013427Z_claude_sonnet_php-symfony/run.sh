#!/usr/bin/env bash
set -euo pipefail
rm -rf "$(dirname "$0")/var"
php -S 127.0.0.1:"$PORT" index.php
