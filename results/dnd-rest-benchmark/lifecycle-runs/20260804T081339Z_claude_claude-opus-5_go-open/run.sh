#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PORT="${PORT:-8080}"
go build -o ./dndrest .
exec ./dndrest
