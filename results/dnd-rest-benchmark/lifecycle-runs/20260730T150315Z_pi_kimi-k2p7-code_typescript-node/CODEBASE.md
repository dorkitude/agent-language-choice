# DM Tools — Codebase Guide

This project is a small, deterministic HTTP API for D&D-style DM helpers. It is
built with **TypeScript 7.0.2** and **Node.js 26.4.0** built-in APIs only:
`node:http` for the server and `node:sqlite` for persistence. No web frameworks
or external runtime dependencies are used.

## Starting and verifying the server

Run the server from the project root:

```bash
PORT=3000 ./run.sh
```

`run.sh` compiles the TypeScript sources to `dist/` with `tsc` and then runs
`node dist/server.js` in the foreground. The server listens on `127.0.0.1`
using the port from the `PORT` environment variable (default `3000`).

Quick health check:

```bash
curl http://127.0.0.1:3000/health
```

Expected response:

```json
{ "ok": true }
```

Reset the SQLite database during testing:

```bash
curl -X POST http://127.0.0.1:3000/v1/storage/reset
```

## Entry point and major modules

| File / directory | Responsibility |
| --- | --- |
| `run.sh` | Compiles and starts the server in the foreground. |
| `src/server.ts` | Entry point. Creates the `node:http` server, reads JSON bodies, dispatches to the router, and listens on `127.0.0.1`. |
| `src/router.ts` | Central route table. Matches method and path, extracts path parameters, and delegates to handlers. |
| `src/routes/*.ts` | One route module per API domain. Each exports small, synchronous handler functions that write JSON responses. |
| `src/db.ts` | SQLite connection singleton, schema definition, schema version, and `resetDatabase()`. |
| `src/repository.ts` | All SQL reads and writes. Encapsulates the `DatabaseSync` API and JSON serialization for complex columns. |
| `src/rules.ts` | Pure game logic: ability modifiers, proficiency, encounter thresholds, dice expression parsing, initiative sorting, etc. |
| `src/validators.ts` | Reusable type guards for request bodies and query parameters. |
| `src/http-utils.ts` | Tiny helpers for sending JSON responses and reading/parsing request bodies. |
| `src/types.ts` | Shared TypeScript domain types. |
| `src/play-auth.ts` | Authentication and authorization helpers for play-campaign endpoints. |

## State, persistence, and request routing design

### Persistence

- A single SQLite file, `./game.db`, is opened on startup.
- `initializeDatabase()` deletes any existing file before opening a new one so
  every server start is a clean, deterministic slate for testing.
- Schema is created lazily with `CREATE TABLE IF NOT EXISTS`.
- Complex columns (`order_json`, `conditions_json`, `tags_json`, `milestones_json`,
  `agenda_json`) are stored as JSON strings.
- `POST /v1/storage/reset` drops all tables and recreates the schema, which is
  useful for deterministic test isolation.
- All database access goes through `src/repository.ts`; route handlers do not
  write SQL directly.

### Routing

1. `server.ts` receives the request.
2. `handleGet()` is tried first. If it matches, the response is sent and the
   request is done.
3. If the method is not `POST` or `PUT`, the server returns `405 Method Not
   Allowed`.
4. For `POST` and `PUT` requests, the body is read and parsed as JSON. Empty
   bodies are treated as `{}`; malformed JSON returns `400 { "error": "invalid json" }`.
5. `handlePost()` or `handlePut()` is tried against the route table. If it
   matches, the response is sent.
6. If no route matches, `404 Not Found` is returned.

Unhandled exceptions produce `500 Internal Server Error` and are logged to stderr.

### Route table conventions

- Routes are registered in `src/router.ts` as `{ method, pattern, handler }`.
- Patterns are slash-separated segments. A segment starting with `:` is a path
  parameter (e.g., `/v1/campaigns/:id/characters` exposes `params.id`).
- Route order matters: more specific patterns should appear before more general
  ones. The current table is grouped by domain and is unambiguous by segment count.

### Authentication for play campaigns

Play-campaign endpoints use a simple deterministic session scheme:

- Registration and login create users with a `role` of `dm` or `player`.
- `POST /v1/auth/login` returns a token of the form `session-${username}`.
- Play endpoints require `Authorization: Bearer session-<username>`.
- `src/play-auth.ts` parses the header, validates the registered user, and
  enforces `dm`/`player` role checks. Unknown but well-formed tokens are treated
  as players.

## Main API / domain groupings

| Domain | Routes |
| --- | --- |
| Health / Storage | `GET /health`, `GET /v1/storage/status`, `POST /v1/storage/reset` |
| Characters | `POST /v1/characters/ability-modifier`, `POST /v1/characters/proficiency`, `POST /v1/characters/derived-stats` |
| Dice & Checks | `POST /v1/dice/stats`, `POST /v1/checks/ability` |
| Encounters & Initiative | `POST /v1/encounters/adjusted-xp`, `POST /v1/initiative/order` |
| Combat | `POST /v1/combat/sessions`, `POST /v1/combat/sessions/:id/conditions`, `POST /v1/combat/sessions/:id/advance` |
| Auth | `POST /v1/auth/register`, `POST /v1/auth/login` |
| Compendium | `GET /v1/compendium/monsters/:slug`, `POST /v1/compendium/monsters`, `GET /v1/compendium/items/:slug`, `POST /v1/compendium/items` |
| Campaigns (planning) | `GET /v1/campaigns/:id/state`, `POST /v1/campaigns`, `POST /v1/campaigns/:id/characters`, `POST /v1/campaigns/:id/events`, `GET /v1/campaigns/:id/audit`, `GET /v1/campaigns/:id/export` |
| Quests | `GET /v1/campaigns/:id/quests/summary`, `POST /v1/campaigns/:id/quests`, `POST /v1/campaigns/:id/quests/:quest_id/progress` |
| Factions & NPCs | `GET /v1/campaigns/:id/relationships`, `POST /v1/campaigns/:id/factions`, `POST /v1/campaigns/:id/npcs` |
| Inventory & Equipment | `GET /v1/campaigns/:id/inventory/summary`, `POST /v1/campaigns/:id/inventory`, `POST /v1/campaigns/:id/characters/:character_id/equipment` |
| Crafting | `POST /v1/campaigns/:id/downtime/crafting`, `POST /v1/campaigns/:id/downtime/crafting/:project_id/advance` |
| Session scheduling | `GET /v1/campaigns/:id/sessions/next`, `POST /v1/campaigns/:id/sessions`, `POST /v1/campaigns/:id/sessions/:session_id/attendance` |
| Analytics | `GET /v1/campaigns/:id/analytics/summary`, `POST /v1/campaigns/:id/analytics/risk-report` |
| PHB Rules | `POST /v1/phb/spell-slots`, `POST /v1/phb/rests/long`, `POST /v1/phb/equipment-load` |
| DM Tools | `POST /v1/dm/encounter-builder`, `POST /v1/dm/loot-parcel`, `POST /v1/dm/session-recap` |
| Play Campaigns | `GET /v1/play/campaigns/:id/turn`, `GET /v1/play/campaigns/:id/my-turn`, `GET /v1/play/campaigns/:id/gm/status`, `POST /v1/play/campaigns`, `POST /v1/play/campaigns/:id/members`, `POST /v1/play/campaigns/:id/start`, `POST /v1/play/campaigns/:id/narrations`, `POST /v1/play/campaigns/:id/turn/nudge`, `POST /v1/play/campaigns/:id/actions`, `POST /v1/play/campaigns/:id/resolutions` |
| Campaign Documents | `GET /v1/play/campaigns/:id/document`, `PUT /v1/play/campaigns/:id/document` |

All endpoints preserve the exact request bodies, status codes, error messages,
and response shapes from the prior cumulative suite. They use only validation and
deterministic calculations; there is no external randomness or third-party API
usage.

## Play campaign turn flow

The play-campaign module (`src/routes/play-campaigns.ts`) implements a
round-robin turn queue for active sessions:

1. The DM creates a campaign (`POST /v1/play/campaigns`) and players join
   (`POST /v1/play/campaigns/:id/members`).
2. The DM starts the campaign (`POST /v1/play/campaigns/:id/start`). The first
   member becomes the active actor and the phase is `player`.
3. The active player submits an action (`POST /v1/play/campaigns/:id/actions`),
   which advances the active actor to the DM and the phase to `dm`.
4. The DM resolves the action (`POST /v1/play/campaigns/:id/resolutions`),
   advancing the queue to the next player and incrementing the turn number.
5. The turn queue is deterministic: each member is followed by the DM, so the
   round-robin alternates between players and the DM.

The campaign document endpoints (`src/routes/campaign-documents.ts`) are owned
by the DM. Players can read the public `story` only; the DM can read and update
both `story` and private `dm_notes`.

## Conventions for safely extending and testing the codebase

### Adding an endpoint

1. Add or reuse domain types in `src/types.ts`.
2. If the endpoint persists data, add repository functions in
   `src/repository.ts` and, if needed, update `src/db.ts` `createSchema()` and
   `resetDatabase()`.
3. Add reusable validation/type guards to `src/validators.ts` or pure logic to
   `src/rules.ts`.
4. Implement the handler in the appropriate `src/routes/*.ts` module (or add a
   new module) and export it as `handle<Name>`.
5. Register the route in `src/router.ts` with the correct `method` and
   `pattern`.
6. Run `npx tsc` to check types and `PORT=... ./run.sh` to test the new route.

### Determinism

- Initiative, combat order, encounter math, and crafting completion are
  deterministic. Do not add randomness unless the contract explicitly requires it.
- Password hashing uses `scryptSync` with fixed parameters for the lifetime of a
  registered user. Session tokens are derived deterministically from the
  username (`session-${username}`).
- The server removes the old SQLite file on startup, so every fresh run starts
  from the same blank state.

### Testing

- The simplest test harness is `./run.sh` plus `curl` commands.
- For isolated tests, import `src/rules.ts` or `src/validators.ts` directly in a
  Node script (the project is an ES module). Avoid writing SQL in tests; use the
  repository functions or the HTTP API instead.
- Reset the database between test cases with `POST /v1/storage/reset` to avoid
  state leakage from earlier tests.

### TypeScript / module notes

- The project uses `module: "NodeNext"` and `moduleResolution: "NodeNext"`.
- Relative imports must use the emitted file extension (`.js`), e.g.
  `import { ... } from './rules.js'`. TypeScript resolves these to the `.ts`
  source files.
- Keep `tsconfig.json` `include` limited to `src/**/*.ts` so the build stays
  focused and deterministic.
