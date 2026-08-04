# D&D DM Tools — Codebase Guide

A small, deterministic HTTP service for D&D 5e helper calculations and campaign management. It uses only Node.js 26 built-ins (`node:http`, `node:sqlite`, `node:crypto`) and plain JavaScript ES modules.

## Starting and verifying the server

```bash
PORT=3000 ./run.sh
```

`run.sh` runs `node server.js` in the foreground. The server binds to `127.0.0.1` and reads the port from the `PORT` environment variable, defaulting to `3000`.

Verify it is up:

```bash
curl http://127.0.0.1:$PORT/health
# {"ok":true}
```

## Entry point and major files

- **`server.js`** — Entry point. Creates the HTTP server, wires the route table via `lib/router.js`, resets the SQLite database with `db.resetDb()`, and starts listening. The route table is grouped by domain, with parameterized routes registered before more general parents that could shadow them.
- **`lib/router.js`** — Minimal HTTP router. Routes are registered with `.get()`, `.post()`, `.put()`, and `.delete()` and matched by HTTP method and regex. Captured path segments are spread as positional arguments to the handler. Bodies are read only for `POST` and `PUT`.
- **`lib/db.js`** — Persistence layer. Owns the SQLite `DatabaseSync` connection, the schema, and all CRUD operations. Schema creation is centralized in `ensureSchema()` and used by both initialization and reset. The `TABLE_NAMES` array is kept in dependency order so the reset path can drop child tables before parents. JSON columns are deserialized with the shared `parseJson()` helper. Recent internal helpers (`addCombatant`, `removeCombatant`) remove duplication between monster and party-member roster operations.
- **`lib/handlers.js`** — HTTP request handlers, organized by domain (health, storage, auth, dice, checks, characters, PHB rules, combat, compendium, campaigns, DM helpers, and play campaigns). Handlers are kept thin: they validate input, call `lib/db.js` or `lib/domain.js`, and format responses. Private helpers inside the module reduce duplication and keep the play-surface semantics consistent:
  - `loadPlayCampaign` — authenticate and load a play campaign.
  - `authorizePlayParticipant` — enforce owner-or-member access for play-surface reads.
  - `loadPlayEncounter` — load a campaign and its encounter, with optional active/order constraints.
  - `requireEncounterOwnerOrActiveMember` / `requireActiveEncounterMember` — encounter turn authorization.
  - `resolveEncounterTarget` / `encounterHealthResponse` — shared damage/heal target resolution and response formatting.
  - `resolveNextTurn` / `publicNarration` — play-campaign turn advancement and narration formatting.
- **`lib/domain.js`** — Pure business logic and validation: dice parsing, encounter XP, initiative ordering, ability modifiers, proficiency bonus, character creation choices, skill lists, auth hashing, and shared validation helpers (`isNonEmptyString`, `isPositiveInteger`, `isValidSlug`, etc.). Shared constants such as `ABILITY_NAMES` and `SKILL_NAMES` live here.
- **`lib/http.js`** — Shared HTTP utilities: body reading, JSON responses, and common error helpers (`badRequest`, `unauthorized`, `forbidden`, `notFound`, `methodNotAllowed`, `conflict`).
- **`run.sh`** — Foreground startup script.
- **`package.json`** — Sets `"type": "module"` and a `start` script. No runtime dependencies.

## State, persistence, and request routing

### Persistence

- SQLite database file: `game.db` in the project root.
- Schema version is fixed at `1` and exposed via `/v1/storage/status`.
- Tables: `users`, `combat_sessions`, `monsters`, `items`, `campaigns`, `characters`, `events`, `factions`, `npcs`, `quests`, `campaign_inventory`, `character_equipment`, `crafting_projects`, `campaign_sessions`, `session_attendance`, `play_campaigns`, `play_members`, `play_character_owners`, `play_narrations`, `play_scenes`, `play_locations`, `play_location_connections`, `play_encounters`, `play_encounter_rewards`.
- JSON arrays/objects (initiative order, combat conditions, monster tags, quest milestones, session agendas, play-campaign queues, encounter combatants, encounter conditions, pre-combat state) are serialized to `TEXT` columns with `JSON.stringify` and deserialized with the shared `parseJson()` helper in `lib/db.js`.
- `/v1/storage/reset` drops all tables and recreates them. This is the only destructive endpoint and is intended for tests. The drop order follows the dependency order in `lib/db.js` so foreign-key constraints are satisfied. The server also calls `db.resetDb()` on startup for a deterministic baseline.

### Request routing

`server.js` builds a `Router` from `lib/router.js`. Routes are evaluated in registration order, and the first matching method/pattern wins. The route table is grouped by domain in `server.js`, but the order within each domain is preserved from previous stages so that parameterized routes (e.g., `/v1/combat/sessions/:id/conditions`) are still registered before their more general parents (`/v1/combat/sessions`).

The router preserves the following behavior, which the cumulative evaluator suite depends on:

- `GET`, `DELETE`, or any method other than `POST`/`PUT` without a matching route returns `405 Method Not Allowed` and does not read the body.
- `POST` or `PUT` without a matching route reads the body, then returns `404 Not Found`.
- `POST` or `PUT` with a matching route reads the body and runs the handler.

`POST`/`PUT` handlers receive the raw body on `req.body` as a string. Handlers parse it with `lib/http.js::parseJson` via `lib/handlers.js::requireBody`. Invalid JSON returns `400 invalid json`.

### Module and data-flow boundaries

```
 server.js   ──▶  lib/router.js  ──▶  lib/handlers.js
                                     │
                                     ▼
              ┌─────────────────────┴─────────────┐
              ▼                                   ▼
       lib/db.js                            lib/domain.js
    (SQLite + schema)                      (pure logic)
              │
              ▼
       lib/http.js
  (responses + body reading)
```

- `server.js` only routes and starts the server.
- `lib/router.js` only matches methods/patterns and reads bodies for POST/PUT.
- `lib/handlers.js` only validates HTTP input, calls the DB/domain layer, and serializes responses. Shared helpers handle repeated authorization, turn checks, and response formatting.
- `lib/db.js` only talks to SQLite and maps rows to/from JS objects.
- `lib/domain.js` has no side effects and no knowledge of HTTP or SQLite.
- `lib/http.js` only provides HTTP utilities and does not depend on the other modules.

## Main API / domain groupings

| Group | Endpoints | Purpose |
|-------|-----------|---------|
| **Health** | `GET /health` | Liveness check. |
| **Storage** | `GET /v1/storage/status`, `POST /v1/storage/reset` | SQLite status and reset. |
| **Auth** | `POST /v1/auth/register`, `POST /v1/auth/login` | User accounts with `scrypt` password hashing. |
| **Core / Dice** | `POST /v1/dice/stats`, `POST /v1/checks/ability`, `POST /v1/encounters/adjusted-xp`, `POST /v1/initiative/order` | Dice stats, ability checks, encounter XP, initiative. |
| **Characters** | `POST /v1/characters/ability-modifier`, `POST /v1/characters/proficiency`, `POST /v1/characters/derived-stats` | Character modifiers and derived stats. |
| **PHB Rules** | `POST /v1/phb/spell-slots`, `POST /v1/phb/rests/long`, `POST /v1/phb/equipment-load` | Spell slots, long rest, carrying capacity. |
| **Combat (standalone)** | `POST /v1/combat/sessions`, `POST /v1/combat/sessions/:id/conditions`, `POST /v1/combat/sessions/:id/advance` | Create session, add conditions, advance turns. |
| **Compendium** | `POST /v1/compendium/monsters`, `GET /v1/compendium/monsters/:slug`, `POST /v1/compendium/items`, `GET /v1/compendium/items/:slug` | Monster and item reference entries. |
| **Campaigns (core)** | `POST /v1/campaigns`, `GET /v1/campaigns/:id/state`, `GET /v1/campaigns/:id/relationships`, `GET /v1/campaigns/:id/audit`, `GET /v1/campaigns/:id/export`, `GET /v1/campaigns/:id/analytics/summary`, `POST /v1/campaigns/:id/analytics/risk-report` | Campaign CRUD and aggregate reports. |
| **Campaigns (entities)** | `POST /v1/campaigns/:id/characters`, `POST /v1/campaigns/:id/characters/:id/equipment`, `POST /v1/campaigns/:id/events`, `POST /v1/campaigns/:id/factions`, `POST /v1/campaigns/:id/npcs` | Characters, events, factions, NPCs. |
| **Quests** | `POST /v1/campaigns/:id/quests`, `POST /v1/campaigns/:id/quests/:id/progress`, `GET /v1/campaigns/:id/quests/summary` | Quest tracking and milestone progress. |
| **Inventory** | `POST /v1/campaigns/:id/inventory`, `GET /v1/campaigns/:id/inventory/summary` | Party inventory and assignment summary. |
| **Downtime Crafting** | `POST /v1/campaigns/:id/downtime/crafting`, `POST /v1/campaigns/:id/downtime/crafting/:id/advance` | Crafting project creation and advancement. |
| **Session Scheduling** | `POST /v1/campaigns/:id/sessions`, `GET /v1/campaigns/:id/sessions/next`, `POST /v1/campaigns/:id/sessions/:id/attendance` | Session scheduling and attendance. |
| **DM Helpers** | `POST /v1/dm/encounter-builder`, `POST /v1/dm/loot-parcel`, `POST /v1/dm/session-recap` | DM-facing convenience tools. |
| **Play Campaigns (lobby)** | `POST /v1/play/campaigns`, `POST /v1/play/campaigns/:id/members`, `POST /v1/play/campaigns/:id/start` | Play-surface campaign lobby and start. |
| **Play Campaigns (turns / document)** | `GET /v1/play/campaigns/:id/turn`, `GET /v1/play/campaigns/:id/my-turn`, `GET /v1/play/campaigns/:id/gm/status`, `POST /v1/play/campaigns/:id/turn/nudge`, `POST /v1/play/campaigns/:id/turn/travel`, `POST /v1/play/campaigns/:id/turn/rest`, `POST /v1/play/campaigns/:id/actions`, `POST /v1/play/campaigns/:id/resolutions`, `POST /v1/play/campaigns/:id/narrations`, `GET /v1/play/campaigns/:id/document`, `PUT /v1/play/campaigns/:id/document` | Turn queue, travel/rest turns, nudges, player actions, GM resolutions, shared document. |
| **Play Campaigns (scenes)** | `POST /v1/play/campaigns/:id/scenes`, `GET /v1/play/campaigns/:id/scenes/current`, `POST /v1/play/campaigns/:id/scenes/:id/enter`, `POST /v1/play/campaigns/:id/scenes/:id/close` | Scene creation and lifecycle. |
| **Play Campaigns (locations)** | `POST /v1/play/campaigns/:id/locations`, `POST /v1/play/campaigns/:id/locations/:id/connections`, `GET /v1/play/campaigns/:id/locations/:id/travel` | Location graph and travel edges. |
| **Play Campaigns (encounters)** | `POST /v1/play/campaigns/:id/encounters`, `POST /v1/play/campaigns/:id/encounters/:id/monsters`, `DELETE /v1/play/campaigns/:id/encounters/:id/monsters/:monster_id`, `POST /v1/play/campaigns/:id/encounters/:id/combatants`, `DELETE /v1/play/campaigns/:id/encounters/:id/combatants/:member`, `GET /v1/play/campaigns/:id/encounters/:id/status`, `GET /v1/play/campaigns/:id/encounters/:id/turn`, `POST /v1/play/campaigns/:id/encounters/:id/turn/advance`, `POST /v1/play/campaigns/:id/encounters/:id/turn/delay`, `POST /v1/play/campaigns/:id/encounters/:id/turn/ready`, `POST /v1/play/campaigns/:id/encounters/:id/actions`, `POST /v1/play/campaigns/:id/encounters/:id/conditions`, `POST /v1/play/campaigns/:id/encounters/:id/damage`, `POST /v1/play/campaigns/:id/encounters/:id/heal`, `POST /v1/play/campaigns/:id/encounters/:id/rewards`, `POST /v1/play/campaigns/:id/encounters/:id/close`, `POST /v1/play/campaigns/:id/encounters/:id/end` | Active encounter creation, deterministic monster roster management, party member binding, turn authority, delay/ready actions, owner-only damage/healing, conditions, rewards, and returning to exploration. |
| **Play Campaigns (character ownership)** | `GET /v1/play/campaigns/:id/characters/:id/owner`, `POST /v1/play/campaigns/:id/characters/:id/claim`, `POST /v1/play/campaigns/:id/characters/:id/transfer` | Character ownership tracking and transfer. |
| **Play Campaigns (character choices / health / skills)** | `POST /v1/play/campaigns/:id/characters/:id/build`, `POST /v1/play/campaigns/:id/characters/:id/level-up`, `POST /v1/play/campaigns/:id/characters/:id/skill-check`, `POST /v1/play/campaigns/:id/characters/:id/damage`, `POST /v1/play/campaigns/:id/characters/:id/death-saves`, `GET /v1/play/campaigns/:id/characters/:id/status` | Owner-only character building, leveling, skill checks, damage, death saves, and status reads. |

## Preservation contract

This is a cumulative benchmark codebase. The evaluator suite checks exact status codes, response bodies, validation rules, and persistence semantics for every stage. When changing the codebase:

- Preserve existing HTTP endpoints, response JSON keys, value shapes, status codes, validation rules, error messages, and persistence semantics. New endpoints may be added by maintenance stages, but existing behavior must remain unchanged.
- Do not change response JSON keys, value shapes, or status codes for existing endpoints.
- Do not change validation rules or error messages for existing endpoints.
- Do not change persistence semantics (including `db.resetDb()` behavior and SQLite schema) for existing data models.
- Keep the implementation deterministic. The only source of randomness is `crypto.randomBytes` for password salts.

Internal structure may change as long as every observable behavior remains identical.

## Conventions for safely extending and testing the codebase

- **Keep handlers thin**: handlers validate input, call `lib/db.js` or `lib/domain.js`, and format responses. Business rules belong in `lib/domain.js`.
- **Add routes in order**: new routes go into the `createRouter()` chain in `server.js` in the order they should be checked. Place parameterized routes before general ones that could shadow them. Group related routes by domain.
- **Use the shared validation helpers**: prefer `domain.isNonEmptyString`, `domain.isPositiveInteger`, `domain.isNonNegativeInteger`, `domain.isValidSlug`, `domain.isStringArray`, `domain.ABILITY_NAMES`, `domain.SKILL_NAMES`, etc., for consistent error messages and shapes.
- **Reuse play-surface helpers**: use `loadPlayCampaign`, `authorizePlayParticipant`, `loadPlayEncounter`, `requireEncounterOwnerOrActiveMember`, `requireActiveEncounterMember`, `resolveEncounterTarget`, `encounterHealthResponse`, `resolveNextTurn`, and `publicNarration` when adding play-surface features so authorization, turn checks, and response shapes stay consistent.
- **Preserve response shapes and status codes**: existing endpoints have fixed response bodies required by the cumulative test suite. Any changes must keep status codes and JSON keys identical.
- **Centralize schema changes**: when adding or changing tables, update `lib/db.js` only. Keep `TABLE_NAMES` in dependency order so `resetDb()` remains safe. Use the `parseJson()` helper when deserializing JSON columns.
- **JSON bodies**: all handlers use `requireBody` from `lib/handlers.js`, which wraps `lib/http.js::parseJson`. Invalid JSON returns `400 invalid json`.
- **Errors**: `badRequest` → `400 { error }`, `unauthorized` → `401 { error }`, `forbidden` → `403 { error }`, `notFound` → `404 { error: 'not found' }`, `methodNotAllowed` → `405 { error: 'method not allowed' }`, `conflict` → `409 { error }`. Uncaught errors log to stderr and return `500 { error: 'internal server error' }`.
- **No external dependencies**: do not add npm packages or TypeScript. The project uses only Node.js stdlib modules and plain `.js` ES modules (`"type": "module"` in `package.json`).
- **Determinism**: avoid randomness in business logic. The only randomness is `crypto.randomBytes` when generating password salts.
- **Testing**: run `node --check server.js` and `node --check lib/*.js` after edits to catch syntax errors before starting the server. Start the server and exercise a representative endpoint from each domain to confirm cumulative behavior is preserved.

## Testing locally

Start the server, reset storage, then exercise endpoints:

```bash
PORT=3000 ./run.sh &
SERVER=$!
curl -X POST http://127.0.0.1:3000/v1/storage/reset
curl -X POST http://127.0.0.1:3000/v1/dice/stats -H 'Content-Type: application/json' -d '{"expression":"2d6+3"}'
kill $SERVER
```
