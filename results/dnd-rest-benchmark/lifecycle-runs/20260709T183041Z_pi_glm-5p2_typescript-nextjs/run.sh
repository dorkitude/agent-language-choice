#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-3000}"
cd "$(dirname "$0")"

# Use locally installed Next.js binary.
export PATH="$PWD/node_modules/.bin:$PATH"

# Always rebuild so maintenance-stage route changes are picked up, then serve
# in the foreground on 127.0.0.1.
next build

exec next start -H 127.0.0.1 -p "$PORT"
