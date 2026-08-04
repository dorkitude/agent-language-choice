#!/usr/bin/env bash
set -euo pipefail
exec ./node_modules/.bin/next dev -H 127.0.0.1 -p "$PORT"
