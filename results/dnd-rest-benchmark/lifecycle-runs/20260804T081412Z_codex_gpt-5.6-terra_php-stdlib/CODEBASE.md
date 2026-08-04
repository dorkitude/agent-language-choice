# Codebase guide

## Run and verify

This is a dependency-free PHP 8.5.8 application. From the repository root,
start it with the port supplied by the environment:

```sh
PORT=8080 ./run.sh
```

`run.sh` initializes the SQLite schema, then `exec`s PHP's built-in server in
the foreground on `127.0.0.1:$PORT`. It must remain the supported launcher.
With the server running in another terminal, verify the service with:

```sh
curl -i http://127.0.0.1:8080/health
```

The successful body is `{"ok":true}`. Before handoff, lint without starting a
server:

```sh
php -l index.php && php -l storage.php
```

## Implementation map

- `run.sh` is the operational entry point. It initializes storage and starts
  the foreground HTTP server.
- `index.php` is the HTTP front controller. Its helpers cover JSON responses,
  request validation, authentication, persistence reads/writes, and a
  deliberately ordered route dispatch.
- `storage.php` owns the versioned, idempotent SQLite schema. Its migration
  helpers inspect existing columns before applying additive or rebuild
  compatibility migrations.
- `game.db` is runtime state, created beside the source on first use. It is
  not source code and should not be hand-edited.

No Composer packages or framework layers are used.

## Request flow and state

Every request reaches `index.php`, configures the shared connection through
`database()` with foreign keys and a five-second SQLite busy timeout, and
ensures the schema exists. `respond()` serializes JSON and exits, so each
request has exactly one response. GET routes are matched before request bodies
are parsed; the remaining dispatcher accepts POST routes, with the one
explicit PUT campaign-document route handled earlier. Route order and response
field ordering are observable API behavior.

The database contains two intentionally separate campaign aggregates:

- `campaigns` and its children support campaign-management, sessions,
  inventory, quests, NPCs/factions, crafting, analytics, and DM tools.
- `play_campaigns` and its members, state, events, and document support the
  authenticated turn-based campaign-play API.

Users and combat sessions use small snapshot helpers; combat session state is
stored as JSON to preserve a complete turn state atomically. Other domain data
is relational. Multi-statement writes use transactions and retain their
endpoint-specific error mapping. `POST /v1/storage/reset` clears application
data while retaining the initialized schema and schema-version metadata.

## API groupings

- Rules utilities: health, dice statistics, ability checks, character ability,
  proficiency, derived statistics, and PHB spell-slot, rest, and carrying-load
  calculations.
- Combat: deterministic initiative ordering plus persisted combat sessions,
  turn advancement, and conditions.
- Authentication: registration/login backed by SQLite password hashes; the
  campaign-play API uses bearer session tokens.
- Storage and compendium: storage status/reset and monster/item creation and
  lookup.
- Campaign management: campaigns, characters, events, sessions/attendance,
  crafting, party inventory/equipment, factions/NPCs, quests, state,
  summaries, analytics, export, and DM encounter/loot/recap tools.
- Campaign play: lobby creation and membership, character build, level-up,
  death-save, damage, healing, and owner-only skill-check flows; turn context;
  encounters/conditions; GM status, narration, nudges, and resolutions; player
  actions; and owner-managed story/DM-note documents.

## Safe extension and testing conventions

Preserve route paths, precedence, validation order/messages, JSON field names
and ordering, status codes, and reset/persistence semantics. Add helpers only
when they keep those invariants explicit; `requireCampaign()` is deliberately
limited to the legacy campaign aggregate, while campaign-play checks remain
separate. Keep calculations and ordering deterministic—initiative ties sort by
score, Dexterity, then name, and campaign-play member order is SQLite `rowid`
join order.

When changing persistence, update `initializeSchema()` rather than placing DDL
in an endpoint or another launcher. Preserve foreign-key behavior and wrap
related writes in transactions. Test both success and invalid-input cases from
a clean state via `POST /v1/storage/reset`, then run the PHP lint commands
above. Do not launch a background server during maintenance; `run.sh` is the
foreground command used by the benchmark.
