# dnd-rest-benchmark — python-django target

A minimal Django project that implements the D&D REST engine benchmark API
as plain function-based views wired through a single URL routing table.
There is no Django ORM, no models, no admin, and no template layer — Django
is used purely as an HTTP routing/request layer over a hand-written SQLite
persistence module.

## Start and verify

```bash
./run.sh
```

`run.sh` installs nothing itself — dependencies are expected to already be
vendored into `.deps/` (via `pip install --target .deps -r requirements.txt`,
which the benchmark harness runs as a setup step). It then runs:

```bash
python3 manage.py runserver 127.0.0.1:"$PORT" --noreload
```

`PORT` must be set in the environment. `--noreload` is required: the
autoreloader forks a second process, which breaks the benchmark harness's
process management and would double-execute `db.init_schema()`.

Verify the server is up:

```bash
curl -s http://127.0.0.1:$PORT/health
# {"ok": true}
```

Run the evaluator suites against a running instance with the `dndeval`
binary (built from `experiments/dnd-rest-benchmark/evaluator/`):

```bash
dndeval run --suite 030-campaign-document --base-url http://127.0.0.1:$PORT
```

Suites are cumulative — each stage's suite exercises every endpoint from
earlier stages plus its own. `dndeval list` shows all available suites; use
the highest-numbered/most-recent one to verify a change hasn't regressed
prior behavior.

## Entry point and major modules

```
manage.py            Django management entry point (DJANGO_SETTINGS_MODULE=dndsite.settings)
dndsite/
  settings.py          Minimal settings: no INSTALLED_APPS, no MIDDLEWARE, ROOT_URLCONF=dndsite.urls
  urls.py              Pure routing table: path() -> view function. Calls db.init_schema() at import time.
  db.py                SQLite persistence: connection handling, schema DDL, one function pair (get_*/create_*) per entity
  rules.py             Pure D&D 5e math shared by multiple views (XP tables, ability modifiers, encounter difficulty)
  views/
    _util.py           Shared request helpers (see below) — not a Django view module itself
    core.py            /health
    dice.py            /v1/dice/stats, /v1/checks/ability
    encounters.py       /v1/encounters/adjusted-xp, /v1/initiative/order
    characters.py       /v1/characters/*
    combat.py           /v1/combat/sessions*
    auth.py             /v1/auth/register, /v1/auth/login
    compendium.py       /v1/compendium/monsters*, /v1/compendium/items*
    storage.py          /v1/storage/status, /v1/storage/reset
    campaigns.py        /v1/campaigns* (planning-time campaign record: characters, events, quests, inventory)
    phb.py               /v1/phb/*
    dm_tools.py          /v1/dm/*
    npcs.py              /v1/campaigns/<id>/factions, /v1/campaigns/<id>/npcs, /v1/campaigns/<id>/relationships
    downtime.py          /v1/campaigns/<id>/downtime/crafting*
    sessions.py          /v1/campaigns/<id>/sessions*
    audit.py             /v1/campaigns/<id>/audit, /v1/campaigns/<id>/export
    analytics.py         /v1/campaigns/<id>/analytics/*
    play.py              /v1/play/campaigns* (real-time play surface: lobby, turns, narration, the shared document)
```

Each `views/<domain>.py` module owns one group of routes end-to-end
(request parsing, validation, response shaping) and calls into `db` for
persistence and `rules` for shared calculations. `urls.py` only imports
these modules and builds `urlpatterns` — it contains no business logic.

`views/_util.py` holds helpers shared across view modules to avoid
duplicating the same boilerplate in every handler:

- `json_body(request)` — parse the request body as JSON.
- `error_response(message, status)` — build the `{"error": message}` envelope.
- `require_method(request, *allowed)` — return a 405 response, or `None` if
  the method is allowed.
- `require_campaign(campaign_id)` / `require_play_campaign(campaign_id)` —
  fetch a campaign record or return a 404 response. Returns
  `(record, error_response)`; exactly one of the two is `None`.
- `authenticate(request)` / `authenticate_play(request)` — resolve the
  `Authorization: Bearer session-<username>` header to a user record (see
  Auth below). `require_play_auth(request)` wraps `authenticate_play` and
  returns `(user, error_response)` the same way the `require_*` helpers do.
- `is_play_participant(campaign, username)` — true if `username` is the play
  campaign's owner or one of its party members.

## State, persistence, and request routing

- **Persistence**: a single SQLite file at `<project root>/game.db`,
  accessed through `dndsite/db.py`. There is no Django ORM/migrations —
  `db.py` owns raw `CREATE TABLE IF NOT EXISTS` DDL and hand-written SQL.
- **Connection model**: one short-lived `sqlite3` connection per operation
  (opened, used, closed). `db._read_connection()` wraps read-only queries;
  `db._write_connection()` wraps writes, serializing them behind a
  process-wide `threading.Lock` and committing on success (an exception
  raised inside the `with` block skips the commit, and the connection is
  always closed in `finally`). This matches sqlite3's threading model,
  where connections must not be shared/written across threads at once.
- **Schema reset**: `db.reset_schema()` drops and recreates every table in
  `db.TABLES` — used by `POST /v1/storage/reset`, primarily for test
  isolation between evaluator suite runs.
- **Routing**: Django's `path()` list in `urls.py` maps URL patterns
  directly to view functions; there are no `include()`s, no class-based
  views, no DRF. All views are decorated `@csrf_exempt` (there is no
  session/CSRF middleware configured) and check `request.method` themselves,
  returning `405` for anything unexpected (`campaigns.py`/`play.py` do this
  via `_util.require_method`; other modules inline the check).
- **Request/response shape**: every view reads a JSON body (via
  `views/_util.json_body`), validates each field's type/shape explicitly,
  and returns `JsonResponse`. There is no serializer framework — validation
  is inline `isinstance` checks that return a `{"error": "..."}` body with a
  400 on failure. `rules.numeric()` collapses whole-number floats back to
  `int` before they hit JSON, so `5.0` renders as `5`.

## Domain groupings

- **Core**: health check.
- **Dice/Checks**: dice expression stats, ability checks.
- **Encounters/Initiative**: adjusted-XP difficulty calculation, initiative
  ordering (stateless — no persistence).
- **Characters**: ability modifiers, proficiency bonus, derived stats
  (HP/AC) — all pure computation, no persistence.
- **Combat**: stateful combat sessions (create, add condition, advance
  turn/round) — persisted in `combat_sessions`.
- **Auth**: user registration/login with `django.contrib.auth.hashers`
  password hashing — persisted in `users`. There is no real session/token
  system: login returns a deterministic `session-<username>` token, and
  every authenticated request re-derives the user from that same string via
  `_util.authenticate`/`authenticate_play` — there's no server-side session
  store to expire or invalidate.
- **Compendium**: monster and item reference data (create + fetch by slug).
- **Storage**: schema status/reset introspection endpoints.
- **Campaigns**: the planning-time campaign record — characters, the event
  log, quests, inventory/equipment, downtime crafting, session scheduling,
  audit/export, and analytics all key off the same `campaign_id`. These
  endpoints have no auth — anyone can read or mutate a campaign by ID.
- **NPCs/Factions**: campaign factions, NPCs, and NPC-to-party relationships.
- **PHB rules**: spell slots, long rest recovery, equipment load/encumbrance
  — pure computation against small seeded lookup tables.
- **DM tools**: encounter builder (combines `rules` + compendium lookups),
  loot parcels, session recap — the highest-level campaign-record endpoints,
  composing the other domains.
- **Play**: the real-time play surface (`play.py`, `play_campaigns` +
  related tables) — distinct from the planning-time `Campaigns` group above,
  and requires `Authorization: Bearer session-<username>` on every request.
  A play campaign starts in `lobby`, moves to `active` once the DM starts it
  (`POST .../start`), and thereafter alternates `current_actor` between the
  DM and party members: a player posts an action (turn passes to the DM),
  the DM posts a resolution (turn passes to the next party member in join
  order), and the DM can post narration or nudge the current actor at any
  time. `GET .../document` / `PUT .../document` holds the shared
  story text plus DM-only notes (filtered out of the response for
  non-owners).

## Conventions for safely extending and testing

- **Adding an endpoint**: add the view to the relevant `views/<domain>.py`
  (or a new module if it's a new domain), then add one `path()` entry in
  `urls.py`. Do not put routing logic inside view modules or business logic
  inside `urls.py`.
- **View boilerplate**: `campaigns.py` and `play.py` factor their
  method/existence/auth checks through `_util.require_method`,
  `_util.require_campaign`/`require_play_campaign`, and
  `_util.require_play_auth` — start new views in those two modules the same
  way rather than inlining `if request.method != "POST": return
  JsonResponse(...)` again. Use `_util.error_response(message, status)`
  instead of constructing `JsonResponse({"error": ...})` inline. For play
  endpoints, authenticate with `require_play_auth(request)` right after the
  method check (before the campaign lookup, unless the view needs a role
  check gated on the campaign's existence — check a sibling view in
  `play.py` for the exact order expected by that endpoint's tests). Other
  domain modules (`npcs.py`, `downtime.py`, `sessions.py`, `audit.py`,
  `analytics.py`, etc.) still inline the equivalent checks; feel free to
  migrate a module to the shared helpers when you're already touching it,
  but that migration hasn't been done wholesale.
- **Validation style**: parse the JSON body in a
  `try/except (json.JSONDecodeError, KeyError, TypeError)` returning 400,
  then explicit `isinstance` checks per field (rejecting `bool` where an
  `int`/`float` is expected, since `bool` is a subclass of `int` in
  Python). Keep error responses as `{"error": "<message>"}` with the
  appropriate status code (400 validation, 401 auth, 403 forbidden, 404 not
  found, 405 method, 409 conflict).
- **Shared math**: if a calculation is needed by more than one view (e.g.
  encounter difficulty, ability modifiers), put it in `rules.py` rather
  than duplicating it — `encounters.py` and `dm_tools.py` both depend on
  `rules.party_xp_thresholds`/`encounter_multiplier`/`encounter_difficulty`
  for this reason.
- **Persistence changes**: add a table to `db._create_tables` and
  `db.TABLES` (so it participates in `reset_schema`), then a matching
  `get_*`/`create_*` (and `save_*`/`update_*` if mutable) pair using
  `_read_connection`/`_write_connection`. Keep row -> dict mapping
  explicit; don't return `sqlite3.Row` objects from `db.py`. When adding a
  column to an existing table (rather than a new table), use
  `db._ensure_column(conn, table, existing_columns, column, ddl)` instead of
  a bare `ALTER TABLE` — it keeps a running server's already-created table
  migratable in place. `db._next_event_sequence(conn, campaign_id)` is the
  shared helper for assigning the next `play_campaign_events.sequence`; use
  it from inside a `_write_connection` block rather than re-deriving
  `MAX(sequence)` per event-creation function.
- **Testing**: there is no unit test suite in this repo — correctness is
  verified by running the `dndeval` evaluator (see "Start and verify")
  against a live server. Suites are cumulative, so always run at least the
  current stage's suite, and ideally a later/full suite from `dndeval list`
  when persistence or shared `rules`/`db`/`_util` code changes, since
  earlier suites exercise the same tables and helpers. Call
  `POST /v1/storage/reset` (or delete `game.db` and restart) between full
  suite runs to avoid stale-data collisions (e.g. "already exists" 409s)
  from a previous run's leftover rows.
- **Determinism**: no view uses real randomness, wall-clock time, or
  non-deterministic ordering (`initiative_order`/combat sort ties break on
  `-score, -dex, name`; play turn order is a deterministic rotation over
  join order). Keep new endpoints deterministic — the benchmark evaluator
  expects exact response bodies.
