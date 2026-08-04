#!/usr/bin/env bash
set -euo pipefail

# Remove the SQLite database so each server start is deterministic.
rm -f "${DB_PATH:-game.db}"

# Next.js dev mode keeps a per-directory lock file so only one dev server can
# run in a given workspace.  Stale servers from previous evaluator attempts can
# block the new server from binding, so clear any leftover lock/process before
# starting.
NEXT_DEV_LOCK=".next/dev/lock"
if [ -f "$NEXT_DEV_LOCK" ]; then
  OLD_PID=$(node -e "try { const fs=require('fs'); const l=JSON.parse(fs.readFileSync('$NEXT_DEV_LOCK','utf8')); process.stdout.write(String(l.pid||'')); } catch(e){ process.stdout.write(''); }" 2>/dev/null || true)
  if [ -n "${OLD_PID:-}" ]; then
    if ps -p "$OLD_PID" -o comm= 2>/dev/null | grep -q "next-server"; then
      kill "$OLD_PID" 2>/dev/null || true
      sleep 1
    fi
  fi
  rm -f "$NEXT_DEV_LOCK"
fi

# As a fallback, stop any next-server process still holding this directory open.
if command -v lsof >/dev/null 2>&1; then
  for PID in $(lsof -t +D "$(pwd)" 2>/dev/null || true); do
    if ps -p "$PID" -o comm= 2>/dev/null | grep -q "next-server"; then
      kill "$PID" 2>/dev/null || true
    fi
  done
fi

exec ./node_modules/.bin/next dev -H 127.0.0.1 -p "$PORT"
