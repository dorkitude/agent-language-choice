#!/usr/bin/env bash
set -euo pipefail
exec ruby -S rackup -s puma -o 127.0.0.1 -p "$PORT"
