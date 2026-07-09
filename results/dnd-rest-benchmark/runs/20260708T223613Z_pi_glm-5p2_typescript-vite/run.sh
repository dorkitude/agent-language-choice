#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-3000}"
exec ./node_modules/.bin/vite --host 127.0.0.1 --port "$PORT"
