#!/usr/bin/env bash
set -euo pipefail
uv run --python 3.14.6 --with-requirements requirements.txt python app.py
