#!/usr/bin/env bash
set -euo pipefail
npx tsc && node dist/server.js
