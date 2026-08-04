#!/usr/bin/env bash
set -euo pipefail
exec .venv/bin/python manage.py runserver 127.0.0.1:"${PORT}" --noreload
