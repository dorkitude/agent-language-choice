#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="$PWD/.deps:${PYTHONPATH:-}"
exec python3 app.py
