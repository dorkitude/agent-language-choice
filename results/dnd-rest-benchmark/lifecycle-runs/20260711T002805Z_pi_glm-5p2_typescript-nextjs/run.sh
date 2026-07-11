#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Ensure dependencies are present (no-op if already installed).
if [ ! -x ./node_modules/.bin/next ]; then
  npm install --no-audit --no-fund
fi

PORT="${PORT:-3000}"
exec ./node_modules/.bin/next dev -H 127.0.0.1 -p "$PORT"
