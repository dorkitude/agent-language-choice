#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
export PATH="$DIR/node_modules/.bin:$PATH"
PORT="${PORT:-3000}"
exec vite --host 127.0.0.1 --port "$PORT"
