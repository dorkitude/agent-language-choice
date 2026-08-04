#!/usr/bin/env bash
set -euo pipefail
rm -rf dist
./node_modules/.bin/tsc
node dist/server.js
