#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$PWD/node_modules/.bin:$PATH"
exec next dev -H 127.0.0.1 -p "$PORT"
