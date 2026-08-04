#!/usr/bin/env bash
set -euo pipefail
exec bundle exec puma -t 1:1 -b "tcp://127.0.0.1:${PORT}"
