#!/usr/bin/env bash
set -euo pipefail
bundle exec ruby app.rb -o 127.0.0.1 -p "$PORT"
