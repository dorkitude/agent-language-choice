#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
bin="$(mktemp -t dndrest.XXXXXX)"
go build -o "$bin" .
trap 'rm -f "$bin"' EXIT
exec "$bin"
