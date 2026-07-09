#!/usr/bin/env bash
set -euo pipefail
exec bundle exec puma -b "tcp://127.0.0.1:${PORT}" config.ru
