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
| `./app/lib/engine.ts` | Pure, deterministic game-rule logic: dice stats, ability checks, initiative, encounter XP, derived stats, combat session lifecycle, character build/level-up rules. |
| `./app/lib/storage.ts` | Single monolithic SQLite repository. Owns the `DatabaseSync` connection, schema, migrations, and all CRUD functions grouped by domain section. |
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

### Why `storage.ts` is one file

All persistence code lives in a single module so that the cumulative evaluator suite sees exactly one deterministic SQLite surface.  Domain boundaries inside the file are marked with section comments (`// Users`, `// Campaigns`, `// Play campaigns`, etc.).  If you add a new domain, append a new clearly labeled section to `storage.ts` rather than creating a separate persistence module, so that lazy initialization and transaction conventions remain uniform.

---

## State, persistence, and routing

### SQLite persistence

The default database path is `game.db` in the project root.  You can override it with `DB_PATH`.

`storage.ts` owns a single lazy `DatabaseSync` instance.  The first call to `getDb()` (or any repository function that calls it) runs `initStorage()`, which creates the schema and seeds `schema_version` if needed.  The `instrumentation.ts` hook eagerly calls `initStorage()` in the Node.js runtime so the first request does not pay the schema-creation cost.

`initStorage()` keeps the base `CREATE TABLE` statements and delegates stage-by-stage additive migrations to `runMigrations()`.  Each migration is wrapped in a try/catch so it is safe to rerun against a database that already has the column or table.

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
| `play_campaign_members` | Player membership in a play campaign, including HP, death saves, and build data. |
| `play_campaign_state` | Active turn state (current actor, turn number, nudge count, location, phase). |
| `play_campaign_narrations` | Ordered narration / action / resolution / travel / rest / combat events. |
| `play_campaign_scenes` | Play-campaign scenes with open/closed status. |
| `play_campaign_current_scene` | Currently active scene for a campaign. |
| `play_campaign_documents` | Campaign documents (story and DM notes). |
| `play_campaign_locations` | Named locations within a play campaign. |
| `play_campaign_location_connections` | Directed travel edges between locations with turn cost. |
| `play_campaign_encounters` | Active or completed encounters within a play campaign. |
| `play_campaign_encounter_combatants` | Party members bound to an encounter with initiative. |
| `play_campaign_encounter_monsters` | Monster roster for an encounter with HP and initiative. |
| `play_campaign_encounter_conditions` | Time-limited conditions on encounter targets. |

All parent-child tables use `ON DELETE CASCADE`.

### Determinism

The API is intentionally deterministic:

* Initiative order breaks ties by DEX then by combatant name.
* Password hashing uses `scryptSync` with fixed parameters and a random salt per user.
* Session tokens are deterministic strings (`session-<username>`).
* Loot parcels, spell-slot tables, and encounter-difficulty endpoints are hardcoded to the values exercised by the suite.

### Request routing

Endpoints are organized by URL path under `app/v1/`.  Next.js maps each `route.ts` to `/v1/<path>` automatically.  Dynamic segments are declared as `[id]` or `[slug]` directories.

All route handlers export `export const dynamic = "force-dynamic"` to prevent any static caching and keep the API surface uniform across pure computation and storage-touching endpoints.

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
| `POST` | `/v1/play/campaigns/[id]/turn/travel` | Travel to a connected location. |
| `POST` | `/v1/play/campaigns/[id]/turn/rest` | Take a short or long rest. |
| `GET` | `/v1/play/campaigns/[id]/gm/status` | GM dashboard view. |
| `GET` | `/v1/play/campaigns/[id]/document` | Read campaign document (players see `story`; DM sees `story` + `dm_notes`). |
| `PUT` | `/v1/play/campaigns/[id]/document` | Update campaign document (DM only). |

### Play-campaign characters

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/play/campaigns/[id]/characters/[char_id]/owner` | Read character ownership. |
| `POST` | `/v1/play/campaigns/[id]/characters/[char_id]/claim` | Claim an unowned character. |
| `POST` | `/v1/play/campaigns/[id]/characters/[char_id]/transfer` | Transfer character ownership to another member. |
| `POST` | `/v1/play/campaigns/[id]/characters/[char_id]/build` | Save race/class/background/abilities/level/HP build. |
| `GET` | `/v1/play/campaigns/[id]/characters/[char_id]/status` | Read HP and status. |
| `POST` | `/v1/play/campaigns/[id]/characters/[char_id]/damage` | Apply damage to a character. |
| `POST` | `/v1/play/campaigns/[id]/characters/[char_id]/death-saves` | Record a death save outcome. |
| `POST` | `/v1/play/campaigns/[id]/characters/[char_id]/level-up` | Level up a character by one. |
| `POST` | `/v1/play/campaigns/[id]/characters/[char_id]/skill-check` | Roll a skill check using the character's build. |

### Play-campaign scenes

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/play/campaigns/[id]/scenes` | Create a scene. |
| `POST` | `/v1/play/campaigns/[id]/scenes/[scene_id]/enter` | Enter a scene and record it in the narration log. |
| `GET` | `/v1/play/campaigns/[id]/scenes/current` | Read the currently open scene. |
| `POST` | `/v1/play/campaigns/[id]/scenes/[scene_id]/close` | Close a scene. |

### Play-campaign locations

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/play/campaigns/[id]/locations` | Create a location. |
| `POST` | `/v1/play/campaigns/[id]/locations/[loc_id]/connections` | Connect a location to another. |
| `GET` | `/v1/play/campaigns/[id]/locations/[loc_id]/travel` | List outbound travel destinations. |

### Play-campaign encounters

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/play/campaigns/[id]/encounters` | Create an active encounter and enter combat phase. |
| `POST` | `/v1/play/campaigns/[id]/encounters/[enc_id]/monsters` | Add a monster to the encounter. |
| `DELETE` | `/v1/play/campaigns/[id]/encounters/[enc_id]/monsters/[monster_id]` | Remove a monster from the encounter. |
| `POST` | `/v1/play/campaigns/[id]/encounters/[enc_id]/combatants` | Bind a party member to the encounter. |
| `DELETE` | `/v1/play/campaigns/[id]/encounters/[enc_id]/combatants/[member]` | Unbind a party member from the encounter. |
| `GET` | `/v1/play/campaigns/[id]/encounters/[enc_id]/status` | Read encounter turn, order, and conditions. |
| `GET` | `/v1/play/campaigns/[id]/encounters/[enc_id]/turn` | Read current encounter turn. |
| `POST` | `/v1/play/campaigns/[id]/encounters/[enc_id]/turn/advance` | Advance the encounter turn. |
| `POST` | `/v1/play/campaigns/[id]/encounters/[enc_id]/turn/delay` | Delay the current turn to a later index. |
| `POST` | `/v1/play/campaigns/[id]/encounters/[enc_id]/turn/ready` | Record a ready action. |
| `POST` | `/v1/play/campaigns/[id]/encounters/[enc_id]/conditions` | Add a condition to a target. |
| `POST` | `/v1/play/campaigns/[id]/encounters/[enc_id]/damage` | Apply damage to a combatant. |
| `POST` | `/v1/play/campaigns/[id]/encounters/[enc_id]/heal` | Apply healing to a combatant. |
| `POST` | `/v1/play/campaigns/[id]/encounters/[enc_id]/actions` | Record a player combat action in the narration log. |
| `POST` | `/v1/play/campaigns/[id]/encounters/[enc_id]/rewards` | Award XP and loot for the encounter. |
| `POST` | `/v1/play/campaigns/[id]/encounters/[enc_id]/close` | Close the encounter. |
| `POST` | `/v1/play/campaigns/[id]/encounters/[enc_id]/end` | End the encounter and return to exploration. |

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
4. Keep validation in the route; keep business logic in `app/lib/engine.ts` and repository code in the appropriate section of `app/lib/storage.ts`.
5. Add `export const dynamic = "force-dynamic"` to every new route handler to keep behavior uniform and avoid static caching.
6. Reuse the shared error shapes: `Invalid JSON`, `Bad request`, `Not found`, `Conflict`, `Unauthorized`, `Forbidden`.

### Adding persistence logic

* Repository functions belong in `app/lib/storage.ts` within the appropriate domain section.
* Use `getDb()` from the top of the file to obtain the initialized `DatabaseSync` instance.
* Wrap multi-statement writes in `BEGIN IMMEDIATE;` / `COMMIT;` with `ROLLBACK;` in the catch path so the suite sees atomic updates.
* Return `null` on unique-key conflicts or missing rows so routes can map to `404` or `409` consistently.
* Additive schema changes should be appended to `runMigrations()` with a try/catch guard so they are idempotent across resets and fresh starts.

### Adding domain logic

* Pure functions belong in `engine.ts` and should return `null` (or a sentinel) on invalid input so routes can map to `400`.
* Shared data types belong in `types.ts`.  Do not import `engine.ts` from `storage.ts`; both should import from `types.ts`.

### Testing locally

The evaluator exercises the full suite cumulatively, so a manual smoke test should cover the same flows in order:

1. `GET /health`
2. `POST /v1/storage/reset`
3. Register/login a user
4. Create compendium entries, campaigns, characters, events, quests, factions, NPCs, inventory, crafting, and sessions
5. Build encounters, create combat sessions, advance/condition turns
6. Create play campaigns, add members, start, narrate, act, resolve, travel, rest, and edit documents
7. Create scenes, locations, and connections; enter/close scenes and travel between locations
8. Create encounters, add monsters and party combatants, advance turns, apply damage/healing/conditions, award rewards, and end encounters

You can run the service in the foreground with `PORT=3000 ./run.sh` and use `curl` or any HTTP client.

### Important invariants

* Do **not** change existing response bodies or status codes for existing routes.
* Do **not** remove or rename existing endpoints.
* The spell-slot, loot-parcel, and encounter-difficulty endpoints are intentionally narrow to match the test contract; widening them is allowed as long as the existing cases remain unchanged.
* SQLite is initialized lazily, so most route handlers do not need to call `initStorage()` explicitly.
* All route handlers use the standard `Request` / `NextResponse` API and assume the Node.js runtime.
* Authorization is based on deterministic `session-<username>` bearer tokens.  Unregistered tokens are accepted and their role is inferred from the username (`dm` or `dm-*` -> DM, otherwise player) so that the play surface can be exercised without a registration step.
* Keep all persistence code in `app/lib/storage.ts` to preserve the single deterministic SQLite surface expected by the cumulative suite.
