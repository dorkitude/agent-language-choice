#!/usr/bin/env bash
set -euo pipefail
export RAILS_ENV=production
export RACK_ENV=production
bundle exec rackup -o 127.0.0.1 -p "$PORT" -s puma
