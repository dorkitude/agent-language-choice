#!/usr/bin/env bash
set -euo pipefail
exec npx next dev -H 127.0.0.1 -p "$PORT"
