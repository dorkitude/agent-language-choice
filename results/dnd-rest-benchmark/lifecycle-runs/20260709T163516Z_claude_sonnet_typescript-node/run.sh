#!/usr/bin/env bash
set -euo pipefail
./node_modules/.bin/tsc && node dist/server.js
