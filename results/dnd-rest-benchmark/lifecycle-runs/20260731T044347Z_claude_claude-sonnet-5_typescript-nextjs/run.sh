#!/usr/bin/env bash
set -euo pipefail

# Next.js refuses to start a dev server if a lock file from a prior
# instance is still present. Each invocation of this script must own the
# server exclusively, so reclaim the lock unconditionally: stop whatever
# process (if any) is still holding it, then clear the lock file.
LOCK_FILE=".next/dev/lock"
if [ -f "$LOCK_FILE" ]; then
  lock_pid=$(node -e "try{console.log(JSON.parse(require('fs').readFileSync('$LOCK_FILE','utf8')).pid)}catch(e){}" 2>/dev/null || true)
  if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
    kill -9 "$lock_pid" 2>/dev/null || true
  fi
  rm -f "$LOCK_FILE"
fi

# Each invocation must start from a clean database. Stale sqlite files left
# over from a prior run (or a prior failed attempt) would otherwise leak
# user/campaign state (e.g. "username already exists" on a fresh register).
rm -f game.db game.db-shm game.db-wal

npx --no-install next dev -H 127.0.0.1 -p "$PORT"
