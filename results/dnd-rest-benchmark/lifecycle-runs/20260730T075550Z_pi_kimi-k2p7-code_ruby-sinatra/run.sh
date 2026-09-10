#!/usr/bin/env bash
set -euo pipefail
rm -f game.db
export PORT="${PORT:-4567}"
bundle exec ruby app.rb -o 127.0.0.1 -p "$PORT"
