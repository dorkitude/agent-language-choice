#!/usr/bin/env bash
set -euo pipefail
export PATH="$PWD/node_modules/.bin:$PATH"
vite --host 127.0.0.1 --port "$PORT"
