#!/usr/bin/env bash
set -euo pipefail

# The evaluator starts a fresh server for each suite.  Do not inherit records
# from a prior run, while keeping SQLite-backed state for this server process.
rm -f "$(dirname "$0")/game.db"

exec bundle exec ruby app.rb -o 127.0.0.1 -p "$PORT"
