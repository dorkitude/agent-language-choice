# CODEBASE.md

A JSON HTTP API for running D&D 5e sessions: dice/rules math, character
stats, combat tracking, a small compendium, campaign management (quests,
NPCs/factions, inventory, downtime crafting, session scheduling, audit/
analytics), and a turn-based "play" surface for actually running a game
session live. Built on Node's built-in `http` and `node:sqlite` modules
only — no web framework, no ORM.

## Starting and verifying the server

```bash
./run.sh
```

This compiles TypeScript (`tsc`) to `dist/` and runs `dist/server.js` in the
foreground. The server listens on `127.0.0.1:$PORT` (defaults to `3000`) and
logs `listening on 127.0.0.1:<port>` once ready.

Verify it's up:

```bash
curl http://127.0.0.1:3000/health
# {"ok":true}
```

The SQLite database file is created at `<project root>/game.db` on first
start (`src/db.ts` resolves this path relative to its own compiled location,
so it works the same from `src/` or `dist/`).

## Entry point and module layout

```
src/server.ts           entry point: opens the DB, starts the HTTP server
src/router.ts           route table: (method, path pattern) -> handler
src/db.ts               SQLite schema, open/reset, and forward-compatible column migration
src/http.ts             sendJson / request body reading and JSON parsing
src/validation.ts       isPlainObject / isValidInt / SLUG_RE request-validation helpers
src/domain/rules.ts     shared D&D math: CR->XP, encounter difficulty, ability/proficiency formulas, initiative ordering
src/routes/*.ts         one module per API domain (handlers only, no routing)
```

`server.ts` does nothing but wire these together: `openDatabase()` then
`createServer` delegating every request to `router.dispatch`. Route
matching, body parsing, and 404 handling all live in `router.ts` so
`server.ts` stays a thin bootstrap.

## Request routing

`router.ts` holds a flat, ordered array of route definitions:

```ts
{ method, pattern: RegExp, parseBody: boolean, handler }
```

`dispatch()` walks the table, matches the first entry whose method and
pattern match the request, optionally parses the body as JSON, and invokes
the handler with `{ res, params, body, authHeader }` (`params` are the regex
capture groups, e.g. a combat session id or campaign id from the URL path;
`authHeader` is the raw `Authorization` header, used only by the `/v1/play/*`
routes).

Only routes whose handler actually reads a body have `parseBody: true`.
Three POST routes — `/v1/combat/sessions/:id/advance`,
`/v1/play/campaigns/:id/start`, and `/v1/storage/reset` — intentionally do
**not** parse the body; sending a malformed body to those endpoints is not
an error. Keep this distinction when adding routes: only set
`parseBody: true` if the handler uses `body`.

Unmatched requests get `404 {"error":"not found"}`. A body that fails JSON
parsing (on a `parseBody: true` route) is caught in `server.ts` and turned
into `400 {"error":"invalid request body"}`.

## State and persistence

All persistent state lives in one SQLite database (`node:sqlite`,
synchronous API), opened once at startup (`db.ts`). There is no connection
pooling or migration framework — `initSchema()` runs `CREATE TABLE IF NOT
EXISTS` for every table on every start, followed by `migrateSchema()`, which
`ALTER TABLE ... ADD COLUMN`s any column introduced after a table's initial
release (needed because `IF NOT EXISTS` is a no-op against an
already-existing on-disk table from an earlier stage's schema).
`POST /v1/storage/reset` drops and recreates all tables for test isolation.

Tables:

- `users` — username, role, scrypt password hash
- `combat_sessions` — id, round, turn_index, and the full combatant list
  (with conditions) serialized as a JSON string in `combat_order`. This is
  intentionally denormalized: sessions are always read and rewritten as a
  whole per request, so a JSON blob avoids a join for no benefit.
- `monsters`, `items` — compendium entries keyed by slug
- `campaigns`, `campaign_characters`, `campaign_events` — campaigns and
  their nested rows, keyed by `(campaign_id, id)`
- `campaign_quests`, `campaign_factions`, `campaign_npcs`,
  `campaign_inventory`, `campaign_equipment`, `campaign_crafting`,
  `campaign_sessions` — one table per campaign sub-domain (quests,
  NPCs/factions, inventory/equipment, downtime crafting, session
  scheduling), each scoped by `campaign_id`
- `play_campaigns` — the live, turn-based play session for a campaign:
  owner (the DM), lobby/active status, current actor, turn number, logical
  turn deadline/nudge count, and the shared story document
  (`doc_story`/`doc_dm_notes`)
- `play_campaign_members` — players who joined a play campaign, one row per
  `(campaign_id, username)`, with their character id/name/class
- `play_campaign_events` — the append-only narration/action/resolution log
  for a play campaign, ordered by `sequence`

Each `routes/*.ts` module owns the prepared statements for its own
table(s) directly — there is no repository/DAO abstraction layer. Domain
modules that need another module's data (e.g. `routes/dm.ts` resolving a
monster by slug, or checking a campaign exists) import that module's
exported lookup functions (`getMonster`, `hasCampaign`,
`hasCampaignCharacter`, `addInventoryItem`) rather than querying the tables
themselves.

Route handlers and DB access are synchronous internally; the only `async`
boundary is reading the HTTP request body.

## API domain groupings

- **Core** (`routes/core.ts`) — `GET /health`, `POST /v1/dice/stats`,
  `POST /v1/checks/ability`. Stateless.
- **Encounters** (`routes/encounters.ts`) — `POST /v1/encounters/adjusted-xp`,
  `POST /v1/initiative/order`. Stateless XP/difficulty and turn-order math.
- **Characters** (`routes/characters.ts`) — ability modifier, proficiency
  bonus, derived stats (HP/AC). Stateless.
- **Combat** (`routes/combat.ts`) — `POST /v1/combat/sessions` and nested
  `/conditions`, `/advance`. Persistent (`combat_sessions`).
- **Auth** (`routes/auth.ts`) — register/login, scrypt password hashing.
  Persistent (`users`). Issues placeholder `session-<username>` tokens with
  no real session store or expiry — consumed by the `/v1/play/*` routes.
- **Compendium** (`routes/compendium.ts`) — monster and item CRUD-by-slug
  (create + get only). Persistent (`monsters`, `items`).
- **Campaigns** (`routes/campaigns.ts`) — campaign create, nested
  characters/events, and aggregate state. Persistent (`campaigns`,
  `campaign_characters`, `campaign_events`).
- **Quests** (`routes/quests.ts`) — create quest, record milestone progress,
  status summary. Persistent (`campaign_quests`).
- **NPCs & factions** (`routes/npcs.ts`) — create faction/NPC, relationship
  summary derived from disposition. Persistent (`campaign_factions`,
  `campaign_npcs`).
- **Inventory** (`routes/inventory.ts`) — add inventory item, assign
  equipment to a character, inventory summary. Persistent
  (`campaign_inventory`, `campaign_equipment`).
- **Downtime** (`routes/downtime.ts`) — create/advance a crafting project;
  on completion, deposits the finished item into inventory via
  `routes/inventory.ts`'s `addInventoryItem`. Persistent
  (`campaign_crafting`).
- **Sessions** (`routes/sessions.ts`) — schedule a session, record
  attendance, find the next upcoming session (earliest `starts_at`, which
  sorts correctly as ISO 8601 text). Persistent (`campaign_sessions`).
- **Audit** (`routes/audit.ts`) — deterministic per-campaign audit log and
  full export. Read-only aggregation, no new state.
- **Analytics** (`routes/analytics.ts`) — readiness summary and maintenance
  risk report, both deterministic aggregations over existing campaign
  tables. Read-only, no new state.
- **PHB** (`routes/phb.ts`) — spell slots, long rest, equipment load.
  Stateless; spell slots only support wizard level 5.
- **DM tools** (`routes/dm.ts`) — encounter builder (compendium + rules),
  loot parcel, session recap. All require an existing campaign; loot and
  recap responses are fixed/deterministic, not generated.
- **Play** (`routes/play.ts`) — the live turn-based session surface:
  create/join/start a play campaign, add DM narration, submit a player
  action, add a DM resolution, fetch turn state (`/turn`, `/my-turn`,
  `/gm/status`), nudge an overdue turn, and read/write the shared story
  document. Persistent (`play_campaigns`, `play_campaign_members`,
  `play_campaign_events`). Every handler requires
  `Authorization: Bearer session-<username>`, resolved via
  `resolveActor()`/`requireActor()` into an `{ username, role }` actor:
  401 for a missing/malformed/unknown-format token, 403 for a valid actor
  lacking permission for the specific action. Turn order interleaves each
  player (join order) with a DM turn after each one; turn timeouts are
  purely logical (turn-count based, via `turn_deadline`/`turn_nudge_count`),
  never wall-clock. Internally, `play.ts` is organized into labeled
  sections (campaign lifecycle, narration/turns/actions, story document,
  scenes, locations/travel, rest, GM status, combat, HP/status/death saves,
  rewards, character ownership, character build/progression) and shares
  three access-check helpers used across many handlers:
  `requireCampaignOwner` (403 unless actor owns the campaign),
  `requireCampaignOwnerOrMember` (403 unless actor owns or has joined it),
  and `requireCurrentPlayerTurn` (409/403 for the DM-can't-act /
  must-be-a-joined-player / must-be-your-turn checks shared by the travel
  and rest handlers).
- **Storage** (`routes/storage.ts`) — `GET /v1/storage/status`,
  `POST /v1/storage/reset` (drops and recreates all tables).

Shared rules math (CR→XP table, level thresholds, the multiplier curve,
ability modifier, proficiency bonus, and `computeEncounterDifficulty`) lives
in `src/domain/rules.ts` and is used by both `routes/encounters.ts` and
`routes/dm.ts`, which arrive at a base XP/monster count differently but
share the same difficulty calculation. `rules.ts` also exports
`compareInitiative` (score desc, then dex desc, then name asc — the same
deterministic tiebreak used by `routes/combat.ts` and
`routes/encounters.ts` when ordering initiative).

## Extending and testing the codebase

- Add a new endpoint by writing its handler in the relevant `routes/*.ts`
  module (or a new module for a new domain) and registering one entry in
  the `routes` array in `router.ts`. Follow the existing handler signature:
  validate the body defensively with `isPlainObject`/`isValidInt`, send a
  `400` on any shape mismatch, and keep handlers synchronous unless they
  need to await something beyond body parsing (none currently do).
- Only add new tables/columns in `src/db.ts`'s `initSchema()`. New tables
  need a matching `DROP TABLE` in `resetDatabase()` so `/v1/storage/reset`
  stays exhaustive. New columns on an *existing* table also need a backfill
  branch in `migrateSchema()`, or a fresh checkout with a pre-existing
  `game.db` will be missing them (see `play_campaigns`' `turn_deadline`,
  `turn_nudge_count`, `doc_story`, `doc_dm_notes` for the pattern).
- Slugs (monsters, items) must match `SLUG_RE` (`src/validation.ts`,
  `/^[a-z0-9]+(?:-[a-z0-9]+)*$/`); usernames must match
  `/^[a-z0-9_-]{2,32}$/` (auth) or the looser `/^[a-z0-9_-]+$/`
  (play-session token parsing). Reuse `SLUG_RE` rather than redefining it
  if a new endpoint needs slug-shaped input (`play.ts` keeps its own copy,
  `PLAY_CAMPAIGN_ID_RE`, since it also matches campaign/scene/location/
  encounter ids, not just compendium slugs).
- For new `/v1/play/*` handlers, resolve the caller with `requireActor(res,
  authHeader)` (returns `undefined` after writing the `401` response) rather
  than re-deriving the auth check inline, and append events via
  `insertPlayCampaignEvent()` rather than hand-rolling the sequence-number
  lookup and insert.
- There is no test framework wired into this project. To verify a change
  manually: run `./run.sh` with `PORT` set, then exercise endpoints with
  `curl`, starting with `POST /v1/storage/reset` to get a clean database
  and `GET /health` to confirm the server is up.
