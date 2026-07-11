#!/usr/bin/env bash
set -euo pipefail
go build -o dndrest .
exec ./dndrest
