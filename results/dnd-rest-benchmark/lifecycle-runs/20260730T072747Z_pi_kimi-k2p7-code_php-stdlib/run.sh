#!/usr/bin/env bash
set -euo pipefail
php -r "require 'index.php'; initDb();"
php -S 127.0.0.1:"$PORT" index.php
