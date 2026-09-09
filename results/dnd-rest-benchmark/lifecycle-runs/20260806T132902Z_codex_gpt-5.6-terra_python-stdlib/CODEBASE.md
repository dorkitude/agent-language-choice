# Codebase guide

## Running and verifying

This is a Python 3 standard-library HTTP service. From the project root, start
it in the foreground with a port supplied by the environment:

```sh
PORT=8000 ./run.sh
```

The service listens only on `127.0.0.1`. In another terminal, verify the live
server with:

```sh
curl -i http://127.0.0.1:8000/health
```

The expected response is HTTP 200 and `{"ok":true}`. A no-server syntax check
is `python3 -m py_compile server.py`. The `dndeval-*-report.json` files and
`shots/` directory are historical benchmark artifacts; they are not runtime
inputs.

## Entry point and code boundaries

- `run.sh` is the operational entry point and runs `python3 server.py`.
- `server.py` is intentionally the complete application. Its top section holds
  constants and schema/reset metadata; module-level functions implement
  validation, SQLite operations, and deterministic rules; `Handler` is the
  HTTP boundary.
- `game.db` is created beside `server.py` and is the only durable runtime
  state. It survives server restarts.

When run directly, `server.py` reads `PORT`, initializes SQLite, and starts a
`ThreadingHTTPServer` bound to loopback. `Handler` owns JSON framing,
authentication checks, route dispatch, and public status/error mapping. Domain
functions return response data or `None` for a missing resource; they do not
select HTTP status codes.

## State and persistence

All mutable data lives in SQLite: credentials, the compendium, conventional
campaigns and their planning records, authenticated play campaigns, and combat
sessions. Combat session state and selected encounter fields are compact JSON;
other campaign data is normalized across tables.

`SCHEMA_STATEMENTS` defines the current schema. Startup also applies the small
compatibility migrations needed by databases from prior stages. `RESET_TABLES`
is the intentionally ordered counterpart used by `/v1/storage/reset`; reset
removes every known table and recreates schema version 1. `DATABASE_LOCK`
protects every database operation because `ThreadingHTTPServer` handles
requests concurrently. Keep related reads and writes in the same locked
connection scope when their atomicity matters.

## Routing and domain groups

`Handler.do_GET`, `do_POST`, `do_PUT`, and `do_DELETE` perform explicit route
matching. `CALCULATION_POST_ROUTES` contains only pure POST calculations whose
successful response is always HTTP 200. Resource endpoints stay explicit so
their authorization, validation order, success status, and not-found behavior
remain visible.

- `/health` and `/v1/storage/*`: service liveness and SQLite status/reset.
- `/v1/auth/*`: user registration and login. Passwords use salted
  `hashlib.scrypt`; the established token behavior is part of the API.
- `/v1/compendium/*`: persistent monsters and items.
- `/v1/campaigns/*`: conventional campaign records, characters, events,
  quests, factions/NPCs, inventory/equipment, crafting, sessions/attendance,
  audit/export, analytics, and risk reporting.
- `/v1/play/campaigns/*`: authenticated DM/player campaign lifecycle,
  ownership and character building/progression, turn queue, narration,
  documents, scenes, locations/travel/rest, health/death saves, encounters,
  combat actions, conditions, delayed/ready turns, and rewards.
  This also includes DM-owned campaign calendars with member-visible,
  deterministic weather.
- `/v1/combat/*`: standalone persisted initiative sessions and conditions.
- `/v1/dm/*`: deterministic encounter, loot, and recap helpers using durable
  campaign and compendium data.
- `/v1/dice`, `/v1/checks`, `/v1/encounters`, `/v1/initiative`,
  `/v1/characters`, and `/v1/phb`: pure deterministic rules calculations,
  including skill and proficiency-related character calculations.

`BadRequest`, duplicate-record exceptions, `OutOfTurn`, and `PermissionError`
form the domain-to-HTTP boundary. In particular,
`Handler.respond_or_not_found` maps domain `None` to the public 404 payload.
These error bodies and status choices are observable API behavior.

## Safe extension and testing conventions

Preserve paths, JSON keys, response bodies, status codes, validation rules,
authorization order, persistence semantics, and deterministic ordering unless
a feature explicitly changes them. In particular, call `read_json_body` only
after the route's current authorization checks: malformed unauthorized requests
must retain their established response. Add validation/domain work as named
module-level functions; keep HTTP status selection in `Handler`. Only add a
route to `CALCULATION_POST_ROUTES` when it is pure and has the shared 200
success contract.

Use parameterized SQL and acquire `DATABASE_LOCK` for each database operation.
When changing schema, update both `SCHEMA_STATEMENTS` and `RESET_TABLES`, retain
needed startup migration behavior, and preserve table reset order. Preserve
initiative tie-breaking and SQLite `rowid` ordering where existing responses
depend on them. Test valid and invalid requests against isolated storage (or
after `/v1/storage/reset`), run `python3 -m py_compile server.py`, and rerun the
cumulative evaluator when it is available.
