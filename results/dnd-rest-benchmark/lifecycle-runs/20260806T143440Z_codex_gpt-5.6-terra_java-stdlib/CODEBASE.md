# Codebase Guide

## Run and verify

This is a Java 26 standard-library HTTP service. From the project root, start
it in the foreground with:

```sh
PORT=8080 ./run.sh
```

`run.sh` compiles `Main.java` and then runs `Main` in the foreground. The
server binds only to `127.0.0.1` and reads its port from `PORT` (defaulting to
`8080` when it is not set). With the server running, a minimal verification
is:

```sh
curl -i http://127.0.0.1:8080/health
```

The expected response is HTTP 200 with `{"ok":true}`. To compile without
starting a server, run `javac Main.java`.

## Implementation layout

The project deliberately has a small surface:

- `run.sh` is the foreground launcher.
- `Main.java` is the entry point and contains the HTTP server, centralized
  router, domain operations, validation, JSON parsing/encoding helpers, and
  SQLite adapter. Its sections are routing, domain actions, persistence, then
  JSON and validation utilities; nested records/classes are the domain model.
- `game.db` is created beside the source at runtime and is the durable state;
  it is not a source artifact.

`Main.main` initializes storage, creates `com.sun.net.httpserver.HttpServer`,
binds it to the loopback address, and sends every request to `handle`.
`handle` keeps routing centralized: fixed and parameterized non-POST routes
are checked first, then POST-only resource routes and fixed calculation
endpoints. It maps domain exceptions to the established JSON status responses.
Route order, exact methods, and the single-read handling of request bodies are
compatibility-sensitive; do not reorder or broaden these checks without
endpoint-level tests.

## State and persistence

The live state is held in insertion-ordered `LinkedHashMap` caches for users,
combat sessions, monsters, items, campaign-management campaigns, and
turn-based play campaigns. Campaign-management campaigns own ordered maps of
characters, events, quests, factions, NPCs, inventory, crafting projects, and
scheduled sessions; combat sessions own initiative order and per-target
conditions. Ordering is observable in several response bodies, so it is
intentional. A shared cache-clear helper is used by both reload and reset so
each replaces the complete in-memory snapshot.

All state-changing domain methods are `synchronized`. After a successful
mutation they call `saveStorage`, which replaces a complete transactional
SQLite snapshot. `CLEAR_STORAGE_TABLES` defines the child-before-owner deletion
order shared by snapshots and resets. On startup, `initializeStorage` creates
schema version 1 if needed and `loadStorage` reconstructs the caches. The
storage adapter invokes the platform `sqlite3` executable; no Java database
dependency is used. Combat session state is JSON encoded and Base64 stored,
while the other domains use normal tables. The storage reset endpoint clears
both the database tables and the live caches.

## API/domain groupings

- Service and storage: `GET /health`, `GET /v1/storage/status`, and
  `POST /v1/storage/reset`.
- Core rules: dice statistics, ability checks, adjusted encounter XP, and
  initiative ordering under `/v1/dice`, `/v1/checks`, `/v1/encounters`, and
  `/v1/initiative`.
- Character and PHB helpers: ability modifiers, proficiency, derived stats,
  spell slots, long rests, and equipment load under `/v1/characters` and
  `/v1/phb`.
- Combat: session creation plus condition and turn-advance actions under
  `/v1/combat/sessions`.
- Authentication: registration and login under `/v1/auth`; passwords are
  PBKDF2 hashes with random salts, while the returned session token remains
  deterministic by contract.
- Compendium: creation and lookup of monsters and items under
  `/v1/compendium`.
- Campaign management and DM tools: campaign creation, characters, events,
  quests, factions, NPCs, inventory/equipment, crafting, scheduling, reports,
  state, audit, and export under `/v1/campaigns`; encounter building, loot
  parcels, and session recaps under `/v1/dm`.
- Live play campaigns: authenticated ownership, membership, start,
  narration/actions/resolutions, travel and rest turns, turn context and
  nudges, and campaign documents under `/v1/play/campaigns`.

## Safe extension and testing conventions

Treat HTTP status codes, JSON field names/order, validation boundaries,
deterministic tie-breakers, and persistence/restart behavior as public
contracts. Add a route in the matching router section and keep all accepted
methods explicit. Reuse the existing validation helpers (`string`, `integer`,
`array`, `requiredText`, and range helpers) so malformed JSON and wrong types
continue to become the standard 400 response.

For a new persistent field, update schema initialization, snapshot writing,
and loading together; preserve ordering with `LinkedHashMap` and explicit
`position` columns where collections are serialized. Keep record IDs global
within their campaign record kind, matching the existing duplicate checks.
Exercise both the normal request and a restart/readback path. Before handing
off a change, compile with `javac Main.java`; use the existing evaluator suites
when available, starting the service only as part of that external test
workflow.
