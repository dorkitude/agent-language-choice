#!/usr/bin/env bash
set -euo pipefail
GOCACHE="${GOCACHE:-/tmp/dndrest-gocache}" exec go run .
