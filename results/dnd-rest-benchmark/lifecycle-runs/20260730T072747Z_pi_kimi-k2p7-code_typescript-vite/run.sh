#!/usr/bin/env bash
set -euo pipefail

if [ ! -f "node_modules/.bin/vite" ]; then
  npm install
fi

exec ./node_modules/.bin/vite --host 127.0.0.1 --port "$PORT"
