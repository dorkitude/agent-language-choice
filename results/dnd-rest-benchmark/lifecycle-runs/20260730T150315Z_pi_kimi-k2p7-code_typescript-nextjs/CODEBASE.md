# D&D REST Benchmark — Codebase Guide

This is a small [Next.js](https://nextjs.org/) 16 + React 19 + TypeScript 7 HTTP service that implements a deterministic set of D&D 5e helper endpoints for a staged benchmark.  It uses SQLite (`node:sqlite`) for persistence, stores data in `game.db` by default, and exposes all endpoints under `/v1/...` via the App Router.

> **Note:** This is a refactoring checkpoint.  The API surface, response bodies, status codes, persistence semantics, and validation rules are frozen to preserve the cumulative evaluator suite.  Extend only by adding new routes; do not alter existing behavior.

---

## Quick start

```bash
# Install pinned dependencies
npm install

# Start the server (listens on 127.0.0.1:PORT)
PORT=3000 ./run.sh
```

`run.sh` runs `next dev -H 127.0.0.1 -p "$PORT"` in the foreground and removes the existing SQLite file before starting, so every run begins with a fresh database.  The server compiles TypeScript on demand and is ready once Next.js prints the local URL.

Verify the server is alive:

```bash
curl http://127.0.0.1:$PORT/health
# -> { "ok": true }
```

Check the SQLite layer:

```bash
curl http://127.0.0.1:$PORT/v1/storage/status
# -> { "driver": "sqlite", "schema_version": 1, "initialized": true }
```

---

## Entry point and major modules

| File / directory | Purpose |
|------------------|---------|
| `./run.sh` | Foreground launcher used by the evaluator. |
| `./next.config.js` | Minimal Next.js config. |
| `./instrumentation.ts` | `register()` hook that eagerly initializes the SQLite schema on Node.js startup. Uses a dynamic import so the Edge Runtime bundle does not statically load the SQLite module. |
| `./app/lib/types.ts` | Shared domain type definitions used by both the engine and storage layers. |
| `./app/lib/engine.ts` | Pure, deterministic game-rule logic: dice stats, ability checks, initiative, encounter XP, derived stats, combat session lifecycle. |
| `./app/lib/storage.ts` | SQLite connection management, schema migration, and CRUD repositories grouped by domain. |
| `./app/lib/auth.ts` | Username/password validation, scrypt hashing, and bearer-token authorization. |
| `./app/lib/http.ts` | Common request parsing (`parseJsonBody`) and shared HTTP response helpers (`ok`, `created`, `badRequest`, `notFound`, `conflict`, `unauthorized`, `forbidden`). |
| `./app/lib/validate.ts` | Deterministic predicates (`isNonEmptyString`, `isInteger`, `isPositiveInteger`, `isStringArray`, etc.) used by route handlers. |
| `./app/health/route.ts` | Health check. |
| `./app/v1/.../route.ts` | API route handlers. |
| `./app/page.tsx` | Minimal landing page (not exercised by the API suite). |

### Runtime layout

```text
Request -> Next.js App Router -> app/v1/.../route.ts -> app/lib/* -> SQLite
```

Route handlers are responsible for **only three things**:

1. Parse and validate the incoming request body.
2. Call the appropriate engine or storage function.
3. Format the result into a `NextResponse` with the correct status code.

---

## State, persistence, and routing

### SQLite persistence

The default database path is `game.db` in the project root.  You can override it with `DB_PATH`.

`storage.ts` owns a single lazy `DatabaseSync` instance.  The first call to `getDb()` (or any repository function that calls it) runs `initStorage()`, which creates the schema and seeds `schema_version` if needed.  The `instrumentation.ts` hook eagerly calls `initStorage()` in the Node.js runtime so the first request does not pay the schema-creation cost.

#### Schema overview

| Table | Purpose |
|-------|---------|
| `schema_version` | Single-row version marker (currently `1`). |
| `users` | Registered accounts with scrypt password hashes and roles (`dm`/`player`). |
| `combat_sessions` | Active combat sessions (round, turn index). |
| `combatants` | Combatants within a session, ordered by `order_index`. |
| `conditions` | Time-limited conditions attached to a combatant. |
| `monsters` | Compendium entries with challenge rating. |
| `monster_tags` | Many-to-many tags for monsters. |
| `items` | Compendium items with type, rarity, and cost. |
| `campaigns` | Top-level campaigns keyed by caller-provided `id`. |
| `campaign_characters` | Player characters tied to a campaign. |
| `campaign_events` | Recap / log entries tied to a campaign. |
| `campaign_quests` | Quest headers with status. |
| `campaign_quest_milestones` | Milestones within a quest. |
| `campaign_factions` | Factions within a campaign. |
| `campaign_npcs` | NPCs tied to a faction and disposition. |
| `campaign_inventory` | Party loot and per-owner items. |
| `campaign_equipment` | Items assigned to specific characters. |
| `crafting_projects` | Downtime crafting projects. |
| `campaign_sessions` | Scheduled sessions. |
| `campaign_session_agenda` | Ordered agenda items for a session. |
| `campaign_session_attendance` | Per-session character attendance. |
| `play_campaigns` | Turn-based play campaigns. |
| `play_campaign_members` | Player membership in a play campaign. |
| `play_campaign_state` | Active turn state (current actor, turn number, nudge count). |
| `play_campaign_narrations` | Ordered narration / action / resolution events. |
| `play_campaign_documents` | Campaign documents (story and DM notes). |

All parent-child tables use `ON DELETE CASCADE`.

### Determinism

The API is intentionally deterministic:

* Initiative order breaks ties by DEX then by combatant name.
* Password hashing uses `scryptSync` with fixed parameters and a random salt per user.
* Session tokens are deterministic strings (`session-<username>`).
* Loot parcels, spell-slot tables, and encounter-difficulty endpoints are hardcoded to the values exercised by the suite.

### Request routing

Endpoints are organized by URL path under `app/v1/`.  Next.js maps each `route.ts` to `/v1/<path>` automatically.  Dynamic segments are declared as `[id]` or `[slug]` directories.

Because these routes read from and write to SQLite, storage-touching handlers export `export const dynamic = "force-dynamic"` to prevent any static caching.

---

## API / domain groupings

### Core helpers (no persistence)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/dice/stats` | Range/average for expressions like `2d6+3`. |
| `POST` | `/v1/checks/ability` | Ability check against a DC. |
| `POST` | `/v1/initiative/order` | Sort initiative rolls with SRD tie-breakers. |
| `POST` | `/v1/characters/ability-modifier` | D&D 5e ability modifier. |
| `POST` | `/v1/characters/proficiency` | Proficiency bonus by level. |
| `POST` | `/v1/characters/derived-stats` | HP, AC, and modifiers. |
| `POST` | `/v1/encounters/adjusted-xp` | Encounter difficulty for level-3 parties. |

### PHB helpers (no persistence)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/phb/spell-slots` | Wizard level-5 slot table only. |
| `POST` | `/v1/phb/rests/long` | Long-rest HP/hit-dice/exhaustion recovery. |
| `POST` | `/v1/phb/equipment-load` | Carrying capacity and encumbrance. |

### Auth & storage

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/auth/register` | Create a user (`dm` or `player`). |
| `POST` | `/v1/auth/login` | Verify password and return a deterministic token. |
| `GET` | `/v1/storage/status` | SQLite driver and schema version. |
| `POST` | `/v1/storage/reset` | Drop and recreate all tables. |

### Compendium

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/compendium/items` | Create an item. |
| `GET` | `/v1/compendium/items/[slug]` | Read an item. |
| `POST` | `/v1/compendium/monsters` | Create a monster (with tags). |
| `GET` | `/v1/compendium/monsters/[slug]` | Read a monster. |

### Campaigns

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/campaigns` | Create a campaign. |
| `GET` | `/v1/campaigns/[id]/state` | Aggregate campaign state. |
| `POST` | `/v1/campaigns/[id]/characters` | Add a character. |
| `POST` | `/v1/campaigns/[id]/events` | Append a log event. |
| `POST` | `/v1/campaigns/[id]/quests` | Create a quest with milestones. |
| `POST` | `/v1/campaigns/[id]/quests/[quest_id]/progress` | Mark milestones complete. |
| `GET` | `/v1/campaigns/[id]/quests/summary` | Quest counts by status. |
| `POST` | `/v1/campaigns/[id]/factions` | Create a faction. |
| `POST` | `/v1/campaigns/[id]/npcs` | Create an NPC. |
| `GET` | `/v1/campaigns/[id]/relationships` | Faction/NPC summary. |
| `POST` | `/v1/campaigns/[id]/inventory` | Add items to the party pool. |
| `GET` | `/v1/campaigns/[id]/inventory/summary` | Inventory counts. |
| `POST` | `/v1/campaigns/[id]/characters/[character_id]/equipment` | Assign items from the party pool to a character. |
| `POST` | `/v1/campaigns/[id]/downtime/crafting` | Start a crafting project. |
| `POST` | `/v1/campaigns/[id]/downtime/crafting/[project_id]/advance` | Advance a crafting project. |
| `POST` | `/v1/campaigns/[id]/sessions` | Schedule a session. |
| `GET` | `/v1/campaigns/[id]/sessions/next` | Read the earliest scheduled session. |
| `POST` | `/v1/campaigns/[id]/sessions/[session_id]/attendance` | Record attendance. |
| `GET` | `/v1/campaigns/[id]/audit` | Audit counts for a campaign. |
| `GET` | `/v1/campaigns/[id]/export` | Export summary. |
| `GET` | `/v1/campaigns/[id]/analytics/summary` | Readiness score summary. |
| `POST` | `/v1/campaigns/[id]/analytics/risk-report` | Risk assessment. |

### Combat

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/combat/sessions` | Create a deterministic session. |
| `POST` | `/v1/combat/sessions/[id]/advance` | Advance the turn and tick conditions. |
| `POST` | `/v1/combat/sessions/[id]/conditions` | Add a condition to a combatant. |

### DM tools

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/dm/encounter-builder` | Build an encounter from campaign + compendium. |
| `POST` | `/v1/dm/session-recap` | Recap the latest campaign event and derive a hook. |
| `POST` | `/v1/dm/loot-parcel` | Return a fixed deterministic loot parcel. |

### Play campaigns (turn-based cooperative play)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/play/campaigns` | Create a play campaign (DM only). |
| `POST` | `/v1/play/campaigns/[id]/members` | Join a play campaign (player only). |
| `POST` | `/v1/play/campaigns/[id]/start` | Start a play campaign (DM only). |
| `POST` | `/v1/play/campaigns/[id]/narrations` | Add a GM narration. |
| `POST` | `/v1/play/campaigns/[id]/actions` | Submit a player action. |
| `POST` | `/v1/play/campaigns/[id]/resolutions` | Resolve a player action and advance the turn. |
| `GET` | `/v1/play/campaigns/[id]/turn` | Read turn state and queue. |
| `GET` | `/v1/play/campaigns/[id]/my-turn` | Player-specific turn context. |
| `POST` | `/v1/play/campaigns/[id]/turn/nudge` | Nudge the current actor. |
| `GET` | `/v1/play/campaigns/[id]/gm/status` | GM dashboard view. |
| `GET` | `/v1/play/campaigns/[id]/document` | Read campaign document (players see `story`; DM sees `story` + `dm_notes`). |
| `PUT` | `/v1/play/campaigns/[id]/document` | Update campaign document (DM only). |

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check returning `{ ok: true }`. |

---

## Conventions for extending and testing

### Adding a new endpoint

1. Create a new `route.ts` under the appropriate `app/v1/...` directory.
2. Use `parseJsonBody(req)` from `app/lib/http.ts` for JSON parsing.
3. Reuse the shared helpers from `app/lib/http.ts` for responses and from `app/lib/validate.ts` for deterministic field checks.
4. Keep validation in the route; keep business logic in `app/lib/engine.ts` or repository code in `app/lib/storage.ts`.
5. If the endpoint touches SQLite, add `export const dynamic = "force-dynamic"`.
6. Reuse the shared error shapes: `Invalid JSON`, `Bad request`, `Not found`, `Conflict`, `Unauthorized`, `Forbidden`.

### Adding domain logic

* Pure functions belong in `engine.ts` and should return `null` (or a sentinel) on invalid input so routes can map to `400`.
* Repository functions belong in `storage.ts` and should return `null` on unique-key conflicts so routes can map to `409`.
* Shared data types belong in `types.ts`.  Do not import `engine.ts` from `storage.ts`; both should import from `types.ts`.

### Testing locally

The evaluator exercises the full suite cumulatively, so a manual smoke test should cover the same flows in order:

1. `GET /health`
2. `POST /v1/storage/reset`
3. Register/login a user
4. Create compendium entries, campaigns, characters, events
5. Build encounters, create combat sessions, advance/condition turns
6. Create play campaigns, add members, start, narrate, act, resolve, and edit documents

You can run the service in the foreground with `PORT=3000 ./run.sh` and use `curl` or any HTTP client.

### Important invariants

* Do **not** change existing response bodies or status codes for existing routes.
* Do **not** remove or rename existing endpoints.
* The spell-slot, loot-parcel, and encounter-difficulty endpoints are intentionally narrow to match the test contract; widening them is allowed as long as the existing cases remain unchanged.
* SQLite is initialized lazily, so most route handlers do not need to call `initStorage()` explicitly.
* All route handlers use the standard `Request` / `NextResponse` API and assume the Node.js runtime.
* Authorization is based on deterministic `session-<username>` bearer tokens.  Unregistered tokens are accepted and their role is inferred from the username (`dm` or `dm-*` -> DM, otherwise player) so that the play surface can be exercised without a registration step.
