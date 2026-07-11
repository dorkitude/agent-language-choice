#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/.deps:${PYTHONPATH:-}"
if ! python3 -c 'import flask' >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install --target "$PWD/.deps" -r requirements.txt
  else
    python3 -m pip install --target "$PWD/.deps" -r requirements.txt
  fi
fi
exec python3 app.py
