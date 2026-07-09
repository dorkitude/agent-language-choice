#!/usr/bin/env bash
set -euo pipefail
export NEXT_TELEMETRY_DISABLED=1
PORT="${PORT:-8000}"

# TypeScript 7.0.2 (native rewrite) no longer ships lib/typescript.js, which
# Next 16.2.10's verify-typescript-setup detector requires. Without it, Next
# falsely reports TypeScript as missing: it runs a no-op `npm install` and, in
# CI environments, exits with a "missing dependency" error before serving.
# Recreate a minimal shim so detection passes. Type-checking is disabled in
# next.config.js (typescript.ignoreBuildErrors) since TS 7.0's API differs.
mkdir -p node_modules/typescript/lib
printf 'module.exports = require("./version.cjs");\n' > node_modules/typescript/lib/typescript.js

exec next dev -H 127.0.0.1 -p "$PORT"
