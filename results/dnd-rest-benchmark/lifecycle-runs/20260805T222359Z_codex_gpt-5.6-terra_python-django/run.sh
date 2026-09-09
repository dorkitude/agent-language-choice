#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="$PWD/.deps:${PYTHONPATH:-}"
python3.14 manage.py runserver 127.0.0.1:"$PORT" --noreload
