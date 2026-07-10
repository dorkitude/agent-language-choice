#!/usr/bin/env bash
set -euo pipefail
: "${PORT:?PORT environment variable is required}"
# Use the locally installed Vite; fall back to npx if not present.
if [ -x "./node_modules/.bin/vite" ]; then
  exec ./node_modules/.bin/vite --host 127.0.0.1 --port "$PORT"
else
  exec npx vite --host 127.0.0.1 --port "$PORT"
fi
