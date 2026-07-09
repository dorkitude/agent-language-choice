#!/usr/bin/env bash
set -euo pipefail
exec npx --no-install vite --host 127.0.0.1 --port "$PORT" --strictPort
