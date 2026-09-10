#!/usr/bin/env bash
set -euo pipefail
php reset.php
php -S 127.0.0.1:"$PORT" index.php
