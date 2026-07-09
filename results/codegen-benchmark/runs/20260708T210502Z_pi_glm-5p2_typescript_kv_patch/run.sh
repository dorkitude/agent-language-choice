#!/bin/sh
# POSIX shell script: compile solution.ts with tsc, then run with node.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Compile TypeScript to JavaScript (emit alongside source).
# No npm packages / tsx required; uses only the Node standard library.
tsc solution.ts \
  --target es2020 \
  --module commonjs \
  --skipLibCheck \
  >/dev/null 2>&1

node solution.js
