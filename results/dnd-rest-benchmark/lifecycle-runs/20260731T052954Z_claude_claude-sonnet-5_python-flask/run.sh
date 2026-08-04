#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="$PWD/.deps:${PYTHONPATH:-}"
python3 app.py
