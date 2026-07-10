#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec ./node_modules/.bin/next dev -H 127.0.0.1 -p "$PORT"
