#!/usr/bin/env bash
set -euo pipefail
exec npx vite --host 127.0.0.1 --port "$PORT"
