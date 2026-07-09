#!/usr/bin/env bash
set -euo pipefail
./node_modules/.bin/vite --host 127.0.0.1 --port "${PORT:?PORT must be set}"
