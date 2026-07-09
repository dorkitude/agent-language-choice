#!/bin/sh
set -e

if [ ! -f solution.js ] || [ solution.ts -nt solution.js ]; then
    tsc solution.ts --module commonjs --target ES2018 --outDir .
fi

exec node solution.js
