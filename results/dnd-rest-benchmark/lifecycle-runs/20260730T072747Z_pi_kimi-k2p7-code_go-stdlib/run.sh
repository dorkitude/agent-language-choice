#!/usr/bin/env bash
set -euo pipefail
rm -f game.db
go build -o dndrest .
exec ./dndrest
