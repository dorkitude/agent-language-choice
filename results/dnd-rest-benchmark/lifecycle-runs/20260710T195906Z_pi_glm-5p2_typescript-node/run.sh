#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Ensure the pinned TypeScript 7.0.2 compiler is available.
if [ ! -x ./node_modules/.bin/tsc ]; then
  npm install --no-audit --no-fund --silent 2>/dev/null || true
fi

if [ -x ./node_modules/.bin/tsc ]; then
  ./node_modules/.bin/tsc
  node dist/server.js
else
  # Fallback: Node 26 runs TypeScript directly via built-in type stripping.
  exec node src/server.ts
fi
