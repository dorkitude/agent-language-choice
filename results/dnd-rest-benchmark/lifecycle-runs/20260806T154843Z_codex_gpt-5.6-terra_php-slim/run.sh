#!/usr/bin/env bash
set -euo pipefail
exec php -S 127.0.0.1:"$PORT" index.php
