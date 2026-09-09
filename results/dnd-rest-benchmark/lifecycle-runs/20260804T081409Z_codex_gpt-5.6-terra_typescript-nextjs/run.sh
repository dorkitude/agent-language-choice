#!/usr/bin/env bash
set -euo pipefail
./node_modules/.bin/next build
exec ./node_modules/.bin/next start -H 127.0.0.1 -p "$PORT"
