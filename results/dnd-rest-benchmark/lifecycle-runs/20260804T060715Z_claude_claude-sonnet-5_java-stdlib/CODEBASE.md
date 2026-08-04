# CODEBASE.md

A D&D 5e tooling REST API implemented as a single-file Java program using only
the JDK standard library (`com.sun.net.httpserver.HttpServer`). No build tool,
no third-party dependencies.

## Start and verify

```bash
./run.sh                 # compiles Main.java and runs it in the foreground
PORT=8080 ./run.sh        # optional; defaults to 8080 if PORT is unset
```

`run.sh` is just:

```bash
javac Main.java
java Main
```

The server binds to `127.0.0.1:$PORT` and prints `Listening on 127.0.0.1:<port>`
once ready. Verify with:

```bash
curl -s http://127.0.0.1:8080/health
# {"ok": true}
```

## Entry point and module layout

Everything lives in `Main.java` (single top-level class `Main`), organized
top-to-bottom into clearly-labeled sections (`// ---------- ... ----------`):

- **`main`** — parses `PORT`, calls `initStorage()`, registers every route via
  `HttpServer.createContext`, and starts the server with the default
  (synchronous, single-threaded) executor.
- **SQLite mirror** — `initStorage`, `resetStorage`, `runSqlite`, and the
  `/v1/storage/status` / `/v1/storage/reset` handlers.
- **Handlers** — dice, ability checks, encounter XP, initiative order.
- **Combat handlers** — combat session lifecycle, conditions, turn order.
- **Character handlers** — ability modifiers, proficiency, derived stats,
  spell slots, long rest, equipment load.
- **Compendium handlers** — monsters and items.
- **Campaign handlers** — campaigns, characters, events, campaign state.
- **Auth handlers** — register/login (PBKDF2 password hashing).
- **Play campaign handlers** — the live, turn-based play loop: lobby, party
  membership, turn order/timeout status, narration/action/resolution events,
  nudges, GM status, and the shared story/DM-notes document.
- **DM tools handlers** — encounter builder, loot parcel, session recap.
- **Helpers** — shared request/response plumbing (see below).
- **`Json`** (nested static class) — minimal hand-rolled JSON parser and
  serializer; no external JSON library is used.

Each domain's handler group declares its own private state and helper
functions immediately above or below its handlers (e.g. `Combatant`,
`CombatSession`, and `COMBAT_SESSIONS` sit right before the combat handlers
that use them), so a module's data model, storage, and request logic stay
adjacent instead of being scattered across the file.

## State, persistence, and request routing

**Request routing** is done entirely through `HttpServer.createContext`, one
context per top-level path registered in `main`. Endpoints that need
per-instance sub-paths (combat sessions, monsters, items, campaigns) register
a single context for the collection path and dispatch internally by matching
`exchange.getRequestURI().getPath()` against a `Pattern` (e.g.
`COMBAT_CONDITIONS_PATH`, `COMBAT_ADVANCE_PATH`).

**State is in-memory and authoritative.** Each domain keeps its data in a
`ConcurrentHashMap` declared next to its handlers:

- `COMBAT_SESSIONS` — active combat encounters
- `USERS` — registered accounts (username, role, salted password hash)
- `MONSTERS`, `ITEMS` — compendium entries
- `CAMPAIGNS` — campaigns, their characters, and their event logs
- `PLAY_CAMPAIGNS` — live play sessions (lobby/party/turn state, the
  narration/action/resolution event log, and the story/DM-notes document);
  separate from `CAMPAIGNS` above and not synced with it. Each `PlayCampaign`
  is locked with its own monitor (`synchronized (campaign)`) rather than
  relying on the map being a `ConcurrentHashMap`, since a request typically
  reads and updates several of its fields atomically (e.g. advancing
  `currentActor` while appending an event).

All reads and writes for a request go through these maps. There is no
database query on the request path.

**`game.db` (SQLite) is a best-effort mirror, not a data store.** It exists so
an operator can inspect the schema with the `sqlite3` CLI. `initStorage()`
(startup) and `resetStorage()` (`POST /v1/storage/reset`) shell out to the
`sqlite3` binary to create/drop-and-recreate tables that mirror the schema
shape; if `sqlite3` isn't available, storage falls back to an empty
placeholder file and continues to work using only the in-memory maps.
`POST /v1/storage/reset` clears `COMBAT_SESSIONS`, `MONSTERS`, `ITEMS`, and
`CAMPAIGNS` directly — it does not depend on the SQLite mirror succeeding,
and it deliberately leaves `USERS` and `PLAY_CAMPAIGNS` untouched (accounts
and in-progress play sessions outlive a storage reset). Don't add code that
reads domain data back out of `game.db`; it isn't kept in sync with in-memory
state.

## API/domain groupings

| Group | Base path(s) |
|---|---|
| Health | `/health` |
| Dice & checks | `/v1/dice/stats`, `/v1/checks/ability` |
| Encounters | `/v1/encounters/adjusted-xp`, `/v1/initiative/order` |
| Combat | `/v1/combat/sessions[/{id}/conditions\|advance]` |
| Characters | `/v1/characters/ability-modifier`, `/v1/characters/proficiency`, `/v1/characters/derived-stats` |
| PHB rules | `/v1/phb/spell-slots`, `/v1/phb/rests/long`, `/v1/phb/equipment-load` |
| Compendium | `/v1/compendium/monsters[/{slug}]`, `/v1/compendium/items[/{slug}]` |
| Campaigns | `/v1/campaigns[/{id}][/characters\|events\|state]` |
| Auth | `/v1/auth/register`, `/v1/auth/login` |
| Play campaigns | `/v1/play/campaigns[/{id}][/members\|start\|narrations\|actions\|resolutions\|turn[/nudge]\|my-turn\|gm/status\|document]` |
| DM tools | `/v1/dm/encounter-builder`, `/v1/dm/loot-parcel`, `/v1/dm/session-recap` |
| Storage admin | `/v1/storage/status`, `/v1/storage/reset` |

Play-campaign endpoints authenticate with `Authorization: Bearer
session-<username>` (see `requireSessionUser`) rather than a real session
store — the token is just the registered username, and the referenced user
must already exist via `/v1/auth/register`. Per-endpoint authorization then
follows one of two shapes, both centralized as helpers: `requireCampaignOwner`
(campaign's DM only — `403 forbidden`) or `requireCampaignMember` (DM or a
joined player — `403 not a campaign member`). A handful of endpoints layer a
further turn-specific check on top (e.g. `actions` requires it to actually be
that player's turn, returning `409 not your turn`).

Every handler responds with `application/json`. Malformed or missing bodies
return `400`, wrong HTTP methods return `405`, unknown IDs/slugs return `404`.

## Shared request/response conventions

- `requireMethod(exchange, "POST")` — for single-method endpoints, checks the
  HTTP method and sends `405 {"error": "method not allowed"}` if it doesn't
  match, returning `false` so the handler can `return` immediately. Endpoints
  that support more than one method (e.g. compendium collection endpoints
  handling both `GET` and `POST`) branch on the method explicitly instead.
- `parseJsonObject(exchange)` — reads the request body, parses it as JSON, and
  requires it to be a JSON object. Sends `400 {"error": "invalid body"}` and
  returns `null` if it isn't; callers check for `null` and return. Malformed
  JSON throws, which is caught by each handler's enclosing `try/catch` and
  reported as `400 {"error": "invalid request"}`.
- `sendJson(exchange, status, payload)` / `readBody(exchange)` — response
  writing and request reading.
- `mapOf(key, value)` / `numeric(double)` — small builders for single-entry
  response maps and for rendering whole-valued doubles as JSON integers.
- Play-campaign handlers additionally use `requireSessionUser` (bearer-token
  lookup), `requireCampaignOwner`, and `requireCampaignMember` (see above) —
  each sends the appropriate error response and returns `null`/`false` so the
  caller can check the result and `return` immediately, matching the
  `requireMethod` pattern.
- Entity lookup-or-404 also follows this pattern via small per-domain
  helpers: `requireCampaign(exchange, campaignId)` (the `CAMPAIGNS` map,
  `404 {"error": "campaign not found"}`), `requirePlayCampaign(exchange,
  campaignId)` (the `PLAY_CAMPAIGNS` map, `404 {"error": "not found"}`), and
  `requireEncounter(exchange, campaign, encounterId)` (a play campaign's
  `encountersById`, `404 {"error": "not found"}`) — each returns `null` on a
  miss so the caller can check and `return` immediately.

## Conventions for extending and testing

- **Adding an endpoint:** register the path in `main`, add a handler in the
  relevant domain section (create a new `// ---------- X handlers ----------`
  section if it's a new domain), and start the handler body with
  `requireMethod` (single method) or an explicit method branch (multiple
  methods). Parse the body with `parseJsonObject` inside a `try { ... } catch
  (Exception e) { sendJson(exchange, 400, mapOf("error", "invalid
  request")); }` block, matching the existing handlers.
- **State:** if the endpoint needs persistent-for-the-process state, add a
  `ConcurrentHashMap` next to the handler, following the existing per-domain
  pattern. Do not add reads/writes against `game.db`; it is not part of the
  request path (see above).
- **Testing:** there is no test suite in this repository; the evaluator suite
  lives outside the project and drives the running server over HTTP. To test
  locally, start the server with `./run.sh` (or `PORT=<port> ./run.sh`) and
  exercise it with `curl`. When changing shared helpers
  (`requireMethod`, `parseJsonObject`, `sendJson`, `Json`), smoke-test at
  least one handler from every domain group above, since all handlers depend
  on them.
- **JSON:** use the nested `Json` class (`Json.parse` / `Json.stringify`) for
  all JSON handling — do not introduce a third-party JSON library, per the
  stdlib-only constraint for this target.
