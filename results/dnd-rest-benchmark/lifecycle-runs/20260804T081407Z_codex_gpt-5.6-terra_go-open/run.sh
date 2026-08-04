#!/usr/bin/env bash
set -euo pipefail
export GOCACHE="${GOCACHE:-$PWD/.gocache}"
mkdir -p "$GOCACHE"
go run .
