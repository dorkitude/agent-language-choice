#!/usr/bin/env bash
set -euo pipefail
export PORT="${PORT:-8000}"
export PYTHONPATH="$PWD/.deps:${PYTHONPATH:-}"
python3 manage.py runserver 127.0.0.1:"$PORT" --noreload
