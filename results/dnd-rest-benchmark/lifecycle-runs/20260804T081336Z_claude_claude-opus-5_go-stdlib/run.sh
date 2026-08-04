#!/usr/bin/env bash
# Build and run the server in the foreground on 127.0.0.1:$PORT (default 8080).
# The working directory is the project root so game.db is created beside the
# sources, which is where the server expects to reload it from.
set -euo pipefail

cd "$(dirname "$0")"

export PORT="${PORT:-8080}"

go build -o ./server .
exec ./server
