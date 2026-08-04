#!/usr/bin/env bash
set -euo pipefail
tsc && node dist/server.js
