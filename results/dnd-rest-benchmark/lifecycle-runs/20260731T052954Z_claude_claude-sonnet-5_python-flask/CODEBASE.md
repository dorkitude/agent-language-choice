# CODEBASE.md

A D&D 5e rules-engine REST API, implemented as a Flask app backed by SQLite.

## Starting and verifying the server

```bash
./run.sh
```

This installs nothing at runtime — dependencies are pre-vendored under
`.deps/` (Flask 3.1.3 and its transitive deps) and `run.sh` just puts that
directory on `PYTHONPATH` and runs `python3 app.py` in the foreground. The
server listens on `127.0.0.1`, on the port given by the `PORT` environment
variable (required — the process fails fast if it's unset).

To verify it's up:

```bash
curl http://127.0.0.1:$PORT/health          # {"ok": true}
curl http://127.0.0.1:$PORT/v1/storage/status
```

`game.db` (a SQLite file next to `app.py`) is created and schema-initialized
automatically on process start; deleting it resets all state on next boot.

## Entry point and module layout

```
app.py                  # builds the Flask app, registers blueprints, runs the dev server
dndapp/
  db.py                 # SQLite connection, schema DDL, init/reset/status helpers
  rules.py               # D&D rules tables + pure calculations (no I/O, no Flask)
  validation.py          # shared request-payload validators and regexes
  combat.py              # combat-session persistence (load/save) and initiative ordering
  routes/
    __init__.py          # register_blueprints(app) — the only place that lists all blueprints
    core.py               # dice stats, ability checks, encounter XP, initiative order, /health
    characters.py         # ability modifier, proficiency bonus, derived stats
    combat.py             # combat session create / add-condition / advance-turn
    auth.py               # user register / login (password hashing via werkzeug)
    compendium.py         # monster and item compendium entries
    campaigns.py          # campaigns, their characters, events, and aggregate state
    phb.py                # spell slots, long rest, equipment load
    dm.py                 # encounter builder, loot parcels, session recap
    quests.py              # quest creation, milestone progress, summaries
    npcs_factions.py       # factions, NPCs, and their relationship state
    inventory.py           # campaign inventory and character equipment
    downtime.py            # multi-day crafting projects
    sessions.py            # session scheduling and attendance
    analytics.py           # cross-domain readiness/risk summaries (read-only)
    audit.py               # deterministic audit log and export summaries
    play.py                # session-token-gated live play: lobby, turns, GM tools
    storage.py             # storage status / destructive reset
```

`app.py` has no route definitions of its own — every HTTP endpoint lives in
`dndapp/routes/*.py` as a Flask `Blueprint`, registered once in
`dndapp/routes/__init__.py`. Each blueprint module owns one API domain and
imports only from `dndapp.db`, `dndapp.rules`, `dndapp.validation`, and
`dndapp.combat` as needed — there are no cross-imports between route modules.

`play.py` is the one module with its own auth layer: every handler is gated
by an `Authorization: Bearer session-<username>` header (checked against the
`users` table — there's no real session store), via the `require_auth`
decorator. The decorator resolves `(username, role)` and passes them as the
first two positional arguments to the view, so handlers stay free of
repeated try/except boilerplate. `play.py` also exposes `next_sequence` (the
next `play_events.sequence` for a campaign) and `serialize_events` (DB rows
to oldest-first JSON dicts) as local helpers shared across its own handlers
only — they are not imported elsewhere.

## State, persistence, and request routing

- **Persistence**: a single SQLite file (`game.db`). `dndapp/db.get_db()`
  opens a fresh connection per call; there is no connection pool or
  request-scoped connection — each route handler opens, uses, and closes its
  own connection inside a `try/finally`.
- **Schema**: defined once in `dndapp/db.py` (`init_schema`) and created
  idempotently (`CREATE TABLE IF NOT EXISTS`) on process start via
  `init_db()`. `reset_db()` drops and recreates all tables — this is what
  backs `POST /v1/storage/reset`.
- **Combat sessions** are the one place state is stored as JSON blobs
  (`order_json`, `conditions_json`) rather than normalized rows: a session is
  always read and rewritten as a whole unit, so JSON keeps `load_session` /
  `save_session` (in `dndapp/combat.py`) trivial and avoids a needless
  extra table.
- **Routing**: standard Flask blueprint registration. There is no global
  middleware or auth guard beyond what Flask provides — every handler
  validates its own input and is independently callable. `play.py` is the
  exception: its handlers additionally require a bearer session token (see
  above).

## API/domain groupings

Each blueprint corresponds to one functional area, and to one of the
benchmark's evaluator suites (`core`, `characters`, `combat-state`,
`auth-users`, `sqlite-storage`, `compendium`, `campaign-state`, `phb-rules`,
`dm-tools`, `quest-tracker`, `npcs-factions`, `inventory-equipment`,
`downtime-crafting`, `session-scheduling`, `analytics-reporting`,
`audit-export`, and the `030-*` campaign-play suites):

- **core** — dice math, ability checks, encounter-XP math, initiative order
- **characters** — ability modifiers, proficiency bonus, derived combat stats
- **combat** — stateful combat sessions (create, apply conditions, advance turn)
- **auth** — user registration/login (password hashing, not real sessions —
  the login token is a deterministic placeholder string, not a real token)
- **compendium** — monster and item reference data
- **campaigns** — campaigns, their characters, events, and read-only state
- **phb** — spell slots, long rest recovery, encumbrance
- **dm** — encounter builder, loot parcels, session recap (compose the above)
- **quests** — quest creation, milestone progress, completion summaries
- **npcs_factions** — factions, NPCs, and their disposition/relationship state
- **inventory** — campaign-owned items and per-character equipment
- **downtime** — multi-day crafting projects that yield inventory
- **sessions** — session scheduling and attendance tracking
- **analytics** — deterministic cross-domain readiness/risk summaries,
  read-only, aggregated from quests/npcs/sessions/inventory/characters/campaigns
- **audit** — deterministic audit log and export summaries of campaign state
- **play** — the live-play surface: lobby creation/joining, starting a
  campaign, DM narrations, player actions, DM resolutions, turn-queue state,
  nudges, the shared story document (plus DM-only notes), and GM status —
  all gated by the `Authorization: Bearer session-<username>` header
- **storage** — introspection (`/v1/storage/status`) and reset
  (`/v1/storage/reset`) for test fixtures

## Conventions for extending and testing

- **Adding an endpoint**: pick the blueprint matching its domain (or add a
  new `dndapp/routes/<name>.py` + `Blueprint` + register it in
  `dndapp/routes/__init__.py` for a new domain). Follow the existing
  handler shape: read `request.get_json(silent=True) or {}`, validate every
  field explicitly (see `dndapp/validation.py` for reusable predicates),
  return `jsonify(error="...")` with an appropriate 4xx on any validation
  failure, and use `dndapp.db.get_db()` inside a `try/finally` for any DB
  access. When adding a bearer-token-gated endpoint to `play.py`, decorate
  the view with `@require_auth` and accept `(username, role, ...)` as its
  first parameters rather than re-deriving auth per-handler.
- **Validation style**: booleans are explicitly excluded from int checks
  (`isinstance(x, int) and not isinstance(x, bool)`) because Python's `bool`
  is an `int` subclass — reuse `valid_int` / `valid_int_in_range` rather than
  re-deriving this.
- **Shared rules math**: encounter-difficulty logic (party XP thresholds,
  monster multiplier, difficulty classification) lives in `dndapp/rules.py`
  and is shared by both `/v1/encounters/adjusted-xp` and
  `/v1/dm/encounter-builder` — extend it there rather than duplicating the
  thresholds/classification logic in a route.
- **Testing**: there's no in-repo test suite; correctness is verified by the
  external `dndeval` evaluator binary against a running server, e.g.:
  ```bash
  PORT=8080 ./run.sh &
  dndeval run --suite dm-tools --base-url http://127.0.0.1:8080
  ```
  Suites are cumulative (each includes all earlier suites' tests). Use
  `POST /v1/storage/reset` between independent test runs against the same
  running server to avoid state leaking across suites (duplicate combat
  session IDs, usernames, etc.).
- **Determinism**: nothing in this codebase depends on wall-clock time,
  randomness, or environment beyond `PORT` — behavior is fully determined by
  request payloads and prior stored state.
