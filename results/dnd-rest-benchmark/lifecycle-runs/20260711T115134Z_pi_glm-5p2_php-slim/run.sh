#!/usr/bin/env bash
set -euo pipefail

# Initialize the SQLite database and schema so game.db exists on server startup.
php init_db.php

# Start the HTTP server in the foreground on 127.0.0.1:$PORT.
php -S 127.0.0.1:"$PORT" index.php
