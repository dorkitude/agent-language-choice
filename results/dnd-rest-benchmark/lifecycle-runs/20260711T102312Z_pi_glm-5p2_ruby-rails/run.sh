#!/usr/bin/env bash
set -euo pipefail

: "${PORT:?PORT environment variable is required}"

# Gems (rails, rack, rackup, puma) are installed into the default GEM_PATH via
# `gem install`, so we run rackup directly without Bundler.
exec rackup -o 127.0.0.1 -p "$PORT" config.ru
