# Codebase guide

## Run and verify

The application targets Python 3.14.6 and Flask 3.1.3 (pinned in
`requirements.txt`). Install dependencies if needed, then start the foreground
server with:

```sh
PORT=8000 ./run.sh
```

`run.sh` binds Flask to `127.0.0.1` through `app.py`. It deliberately removes
the local `game.db` before startup so a command-line run begins with empty
state. In another shell, check the service with:

```sh
curl http://127.0.0.1:8000/health
```

which returns `{"ok":true}`. For a no-server syntax check, run
`python3 -m py_compile app.py`; this compiles the module but does not execute its
import-time database initialization.

## Entry point, routing, and state

`app.py` is the complete Flask application: configuration, SQLite schema and
access helpers, domain helpers, and route registrations. The module calls
`initialize_database()` during import, then its `__main__` block starts Flask on
`127.0.0.1:$PORT`. `run.sh` supplies the matching foreground launcher.

`game.db`, located next to `app.py`, is the durable store for a running process.
`run.sh` intentionally removes that file before starting, whereas importing
`app.py` preserves and additively migrates an existing database. The storage
routes make this distinction visible: `/v1/storage/status` reports schema state
and `/v1/storage/reset` clears then recreates it.

`database_connection()` creates a connection per operation, enables foreign
keys, and relies on SQLite context managers for transaction commit/rollback.
`table_columns()` keeps additive schema checks in one place; the migration SQL
remains explicit so the on-disk compatibility contract is easy to audit.
Combat sessions are stored as compact JSON. Authentication, compendium data,
traditional campaigns, scheduling, inventory, quests, and play-campaign state
are normalized SQLite tables. Ordered collections must retain their explicit
`ORDER BY` clauses, and play-turn mutations use `BEGIN IMMEDIATE` to preserve
their read-modify-write invariant.

## API/domain layout

Routes appear in `app.py` in these groups:

- service and storage (`/health`, `/v1/storage/*`); authentication
  (`/v1/auth/*`);
- authenticated play campaigns: documents, membership, turns, narration,
  actions, resolutions, locations/scenes, character progression, and
  encounter combat;
- traditional campaign management: characters, events, inventory/equipment,
  crafting, factions/NPCs, quests, sessions, analytics, audit, and export;
- compendium monsters and items; deterministic dice, ability, initiative, and
  encounter utilities; DM encounter/loot/recap tools;
- combat-session state plus character and PHB calculation endpoints.

Shared helpers perform only mechanical tasks, such as required-field parsing,
row serialization, and calculation. Each route retains its own validation,
error text, status code, and authorization decision because those are public
contract.

## Safe extension and testing

Treat every route path, JSON field/order, error string, status code, validation
rule, and persistence behavior as observable API. In particular, keep strict
`type(value) is int` checks: accepting booleans as integers changes validation.
Use parameterized SQL, preserve collection ordering, and keep results
deterministic—no random values or clock-derived output.

Keep routing and public response shaping in the route handlers. Extract only
mechanical helpers that cannot choose validation, authorization, error, or
response policy; those choices are contractual. Verify a change with
`python3 -m py_compile app.py`, then run the relevant evaluator suite when it is
available and inspect the diff. Use `PORT=<port> ./run.sh` only for intentional
manual HTTP verification; it resets the local database before launching.
