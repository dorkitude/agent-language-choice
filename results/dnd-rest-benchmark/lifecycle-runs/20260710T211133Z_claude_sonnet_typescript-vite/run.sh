#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
./node_modules/.bin/vite --host 127.0.0.1 --port "$PORT"
