#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="$PWD/.deps:${PYTHONPATH:-}"
python3 -c 'from dndsite.db import init_storage; init_storage()'
exec python3 manage.py runserver 127.0.0.1:"$PORT" --noreload
