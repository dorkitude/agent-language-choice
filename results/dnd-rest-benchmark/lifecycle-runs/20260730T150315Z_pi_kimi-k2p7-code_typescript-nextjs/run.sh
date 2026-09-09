#!/usr/bin/env bash
set -euo pipefail

DB_FILE="${DB_PATH:-game.db}"
PORT="${PORT:?PORT must be set}"

# Next.js dev mode keeps a per-directory lock file so only one dev server can
# run in a given workspace.  Read any existing lock before clearing state, then
# terminate the stale server it references.
NEXT_DEV_LOCK=".next/dev/lock"
if [ -f "$NEXT_DEV_LOCK" ]; then
  OLD_PID=$(node -e "try { const fs=require('fs'); const l=JSON.parse(fs.readFileSync('$NEXT_DEV_LOCK','utf8')); process.stdout.write(String(l.pid||'')); } catch(e){ process.stdout.write(''); }" 2>/dev/null || true)
  if [ -n "${OLD_PID:-}" ]; then
    if ps -p "$OLD_PID" -o comm= 2>/dev/null | grep -qE "next-server|node"; then
      kill "$OLD_PID" 2>/dev/null || true
      sleep 1
    fi
  fi
fi

# Remove the SQLite database (and any WAL files) so each server start is
# deterministic and cannot inherit a stale write-ahead log from a previous
# evaluator attempt.
rm -f "$DB_FILE"
rm -f "$DB_FILE-wal"
rm -f "$DB_FILE-shm"

# Remove the Next.js build cache so stale compiled routes from previous
# evaluator attempts cannot shadow the current source tree.
rm -rf .next

# Make sure no stale server is still holding the target port or the database
# file, otherwise the new server can fail to bind or serve requests against
# stale state.
kill_holders() {
  if command -v lsof >/dev/null 2>&1; then
    # Processes listening on the target port.
    lsof -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true
    # Processes that still have the (now unlinked) database file open.
    lsof -t "$DB_FILE" 2>/dev/null || true
  fi
}

for PID in $(kill_holders | sort -u); do
  if ps -p "$PID" -o comm= 2>/dev/null | grep -qE "next-server|node"; then
    kill "$PID" 2>/dev/null || true
  fi
done

# Give killed processes a moment to release the port.
sleep 1

# If the port is still occupied, force-kill the holder.
if command -v lsof >/dev/null 2>&1; then
  for PID in $(lsof -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true); do
    kill -9 "$PID" 2>/dev/null || true
  done
fi

exec ./node_modules/.bin/next dev -H 127.0.0.1 -p "$PORT"
