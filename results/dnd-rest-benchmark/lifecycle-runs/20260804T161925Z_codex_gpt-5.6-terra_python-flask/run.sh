#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="$PWD/.deps:${PYTHONPATH:-}"
rm -f game.db
python3 app.py
