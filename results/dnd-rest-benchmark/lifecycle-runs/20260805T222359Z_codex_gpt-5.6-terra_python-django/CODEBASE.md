# D&D REST API codebase

This is a minimal Django 6.0.7 JSON API for the benchmark's D&D campaign-play
domain. It intentionally has no Django models, migrations, templates, or
middleware: explicit view functions project the HTTP contract while a small
SQLite repository owns durable state.

## Run and verify

Install the pinned dependency into the local dependency directory if it is not
already present:

```sh
python3 -m pip install --target .deps -r requirements.txt
```

Start the foreground server with a port supplied by the caller:

```sh
PORT=8000 ./run.sh
```

`run.sh` sets `PYTHONPATH` for `.deps` and runs Django on `127.0.0.1:$PORT`
with reload disabled.  In a second shell, verify the process with:

```sh
curl -sS http://127.0.0.1:8000/health
```

The expected response is `{"ok": true}`.  For a non-server check, use:

```sh
PYTHONPATH="$PWD/.deps${PYTHONPATH:+:$PYTHONPATH}" python3.14 manage.py check
```

## Entry points and layout

- `run.sh` is the production-style launcher; `manage.py` is Django's command
  entry point.
- `dndsite/settings.py` contains the intentionally minimal Django settings and
  names `dndsite.urls` as the root URL configuration.
- `dndsite/urls.py` owns request parsing, validation, domain calculations,
  response shaping, and the complete `urlpatterns` table. Shared helpers near
  its top implement JSON-object parsing and the standard authenticated/DM
  request gate; views retain endpoint-specific authorization outcomes.
- `dndsite/storage.py` is the persistence boundary.  It owns the SQLite schema
  and short-lived connections, but returns plain dictionaries to the views.
- `game.db` is created beside the source when the URL module initializes
  storage.  It is runtime state, not a migration-managed Django database.

## State and routing

Importing the URL module calls `storage.initialize()`, ensuring the current
schema exists before the first request. Every storage operation opens a fresh
SQLite connection; `with connection()` commits successful writes when the scope
exits. `game.db` holds users, combat-session JSON, compendium records,
campaign-management data, and play-campaign state. The reset endpoint clears
all domain tables in an explicit child-before-parent order while retaining the
schema metadata.

Routes are direct `django.urls.path` entries with no trailing slash. Views use
`json_body()` or `put_json_body()` for method-specific JSON-object validation
and return `JsonResponse` objects directly. Validation helpers intentionally
raise `ValueError`; each view maps those errors to the contract's existing 400
response. `authenticated_actor()` and `dm_actor()` only cover the common
method/session checks, so not-found, conflict, and exceptional authorization
branches stay explicit with their exact established messages and status codes.

## API groupings

- `/health` provides the service probe.
- `/v1/auth/*` manages registration and login.
- `/v1/dice`, `/v1/checks`, `/v1/characters`, `/v1/encounters`, and
  `/v1/initiative` provide stateless rules calculations.
- `/v1/combat/*` stores initiative sessions and conditions.
- `/v1/storage/*` exposes SQLite status and reset controls.
- `/v1/compendium/*` stores and retrieves monsters and items.
- `/v1/campaigns/*` stores campaigns, characters, inventory/equipment,
  downtime, events, quests, factions/NPCs, sessions, reporting, and exports.
  Analytics and risk reporting share one deterministic readiness-signal
  projection while keeping their distinct response shapes.
- `/v1/play/campaigns/*` supports the separate turn-based campaign-play flow:
  campaign creation, player membership, start/turn status, GM narration and
  resolution, player actions, timeout nudges, and the campaign document.
  Its idempotent-event log is campaign-scoped and stores immutable keyed
  effects in sequence order, allowing exact replay without a second effect.
- `/v1/dm/*` builds encounters, deterministic loot, and session recaps from
  campaign and compendium state.
- `/v1/phb/*` provides the supported spell-slot, long-rest, and equipment-load
  rules helpers.

## Safe extension and testing conventions

Preserve the public contract: add no implicit route slash, do not change
validation messages/status codes, request methods, or observable collection
ordering. Put new persisted data and SQL in `storage.py`; keep input validation
and HTTP response projection in `urls.py`. Store JSON through `encode_json()`
so its compact on-disk representation stays consistent. Add routes explicitly
to `urlpatterns`, then exercise both success and validation/error paths with
Django's request tools or HTTP requests. Before handoff, run the Django check,
compile the touched modules, check `run.sh` with `bash -n`, and run the relevant
cumulative evaluator when it is available. Do not start a development server
as part of these checks unless the task explicitly requires it.
