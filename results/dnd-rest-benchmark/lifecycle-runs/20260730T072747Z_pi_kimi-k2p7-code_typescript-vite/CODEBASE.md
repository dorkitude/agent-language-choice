# D&D REST API — Codebase Guide

This is a small, single-purpose Vite 8 / TypeScript API server for a staged D&D benchmark. It exposes a deterministic REST API backed by a local SQLite file and implements the API as a Vite dev-server middleware plugin.

## Starting and verifying the server

```bash
PORT=8080 ./run.sh
```

`run.sh` installs dependencies if needed and then launches Vite in the foreground, bound to `127.0.0.1` on the port given by the `PORT` environment variable. Quick health checks:

```bash
curl http://127.0.0.1:$PORT/health
# → {"ok":true}

curl http://127.0.0.1:$PORT/v1/storage/status
# → {"driver":"sqlite","schema_version":1,"initialized":true}
```

Stop the server with `Ctrl-C` in the terminal where it is running.

**Important:** The database is reset to a clean schema every time the server starts (`resetSchema()` is called from the Vite plugin's `configureServer` hook). This makes each run deterministic, but it also means data does not persist across restarts. Use `POST /v1/storage/reset` to reset the schema between test runs while the server is already running.

## Entry point and major modules

| File / directory | Responsibility |
| ---------------- | -------------- |
| `./run.sh` | Shell entry point. Ensures `npm install` has run and starts Vite. |
| `vite.config.ts` | Minimal Vite configuration. Imports the D&D API plugin and registers it. |
| `src/lib/plugin.ts` | Vite plugin that installs the API middleware and resets the database on server start. |
| `src/lib/router.ts` | Central request router. Matches HTTP method and URL, then delegates to domain handlers in the exact historical order. |
| `src/lib/http.ts` | Low-level HTTP helpers: `readBody`, `sendJson`, and `sendError` for the standard `{ error: ... }` envelope. |
| `src/lib/validation.ts` | Reusable type guards: `isNonEmptyString`, `isLevel`, `isAbilityScore`, `isValidRole`, etc. |
| `src/lib/auth.ts` | `scrypt`-based password hashing/verification and `Bearer session-<username>` token parsing. |
| `src/lib/rules.ts` | Pure, deterministic D&D rule calculations (ability modifiers, proficiency, dice, initiative, encounter XP). |
| `src/lib/constants.ts` | Deterministic reference tables (`XP_TABLE`, `LEVEL3_THRESHOLDS`, `DIFFICULTY_RECOMMENDATION`) plus `DB_PATH` / `SCHEMA_VERSION`. |
| `src/lib/types.ts` | Domain TypeScript interfaces. |
| `src/lib/db.ts` | Compatibility barrel that re-exports `src/lib/db/index.ts`. |
| `src/lib/db/connection.ts` | Shared SQLite connection and schema lifecycle (`initializeSchema`, `resetSchema`). |
| `src/lib/db/*.ts` | Domain-specific persistence modules: `users`, `campaigns`, `play`, `combat`, `compendium`, `quests`, `factions`, `npcs`, `inventory`, `sessions`, `crafting`. |
| `src/lib/handlers/*.ts` | One handler file per domain. |
| `src/main.ts` | Client-side entry point (currently just a log statement). The API is served by Vite middleware, not by this file. |

## State, persistence, and request-routing design

### State and persistence

- The SQLite database is opened once by `src/lib/db/connection.ts` when the module is first imported (`DatabaseSync(path.resolve('game.db'))`).
- The schema is reset when the Vite server starts via `resetSchema()` in `configureServer`.
- `resetSchema()` (used by `POST /v1/storage/reset`) drops and recreates all tables.
- All durable state lives in SQLite; handlers do not keep in-memory state between requests. This makes the server deterministic and easy to restart.
- Persistence is split by domain under `src/lib/db/`. Each module imports the shared `db` connection from `./connection.js` and owns a slice of the schema.

### Request routing

1. The Vite plugin (`src/lib/plugin.ts`) adds a Connect-style middleware to the dev server.
2. The middleware calls `route(req, res, next)`.
3. `router.ts` parses the URL, checks the HTTP method, and dispatches to a handler.
4. If a handler matches, it writes a JSON response and returns `true`; otherwise the router falls through to `next()` so Vite can serve static assets or the client entry point.
5. Unhandled exceptions in the middleware are caught and returned as `500 {"error":"internal server error"}` if headers have not been sent yet.

### POST body parsing

POST requests are read once from the stream and parsed as JSON. Malformed JSON returns `400 {"error":"invalid json"}` before any handler runs. Empty bodies are treated as `undefined`. GET and POST are the only methods with handlers; PUT is accepted for JSON body parsing consistency but falls through if no handler matches. All other methods fall through to Vite.

## Main API / domain groupings

The endpoint order below mirrors the dispatch order in `src/lib/router.ts`, which matters for precedence and edge-case behavior.

### Health & Storage

| Method | Endpoint | Notes |
| ------ | -------- | ----- |
| GET | `/health` | Liveness probe. |
| GET | `/v1/storage/status` | Reports SQLite driver/version/initialized status. |
| POST | `/v1/storage/reset` | Drops and recreates the schema; returns `schema_version`. |

### Classic Campaigns

| Method | Endpoint | Notes |
| ------ | -------- | ----- |
| GET | `/v1/campaigns/:id/state` | Campaign header plus character list and event count. |
| GET | `/v1/campaigns/:id/audit` | Aggregate counts (events, quests, NPCs, sessions). |
| GET | `/v1/campaigns/:id/export` | Aggregate export including inventory and schema version. |
| POST | `/v1/campaigns` | Create a campaign (`id`, `name`, `dm`). |
| POST | `/v1/campaigns/:id/characters` | Add a character to a campaign. |
| POST | `/v1/campaigns/:id/events` | Log an event (`id`, `kind`, `summary`). |

### Session Scheduling

| Method | Endpoint | Notes |
| ------ | -------- | ----- |
| GET | `/v1/campaigns/:id/sessions/next` | Returns the earliest scheduled session. |
| POST | `/v1/campaigns/:id/sessions` | Schedule a session (`id`, `starts_at`, `duration_minutes`, `agenda`). |
| POST | `/v1/campaigns/:id/sessions/:session_id/attendance` | Record present/absent character IDs. |

### Factions & NPCs

| Method | Endpoint | Notes |
| ------ | -------- | ----- |
| GET | `/v1/campaigns/:id/relationships` | Count factions, NPCs, and friendly NPCs. |
| POST | `/v1/campaigns/:id/factions` | Create a faction. |
| POST | `/v1/campaigns/:id/npcs` | Create an NPC linked to a faction. |

### Quests

| Method | Endpoint | Notes |
| ------ | -------- | ----- |
| GET | `/v1/campaigns/:id/quests/summary` | Count quests by status. |
| POST | `/v1/campaigns/:id/quests` | Create a quest. |
| POST | `/v1/campaigns/:id/quests/:quest_id/progress` | Mark milestones completed. |

### Inventory & Equipment

| Method | Endpoint | Notes |
| ------ | -------- | ----- |
| GET | `/v1/campaigns/:id/inventory/summary` | Party/assigned item counts and healing-potion stock. |
| POST | `/v1/campaigns/:id/inventory` | Add items to a campaign owner. |
| POST | `/v1/campaigns/:id/characters/:character_id/equipment` | Assign party inventory to a character. |

### Downtime Crafting

| Method | Endpoint | Notes |
| ------ | -------- | ----- |
| POST | `/v1/campaigns/:id/downtime/crafting` | Start a crafting project. |
| POST | `/v1/campaigns/:id/downtime/crafting/:project_id/advance` | Advance a project by days; deposits the finished item when complete. |

### Auth

| Method | Endpoint | Notes |
| ------ | -------- | ----- |
| POST | `/v1/auth/register` | Username/password registration. |
| POST | `/v1/auth/login` | Returns `session-<username>` token on success. |

### Dice & Rules

| Method | Endpoint | Notes |
| ------ | -------- | ----- |
| POST | `/v1/dice/stats` | Min/max/average for a `XdY+Z` expression. |
| POST | `/v1/checks/ability` | Ability check with `total`, `success`, `margin`. |
| POST | `/v1/initiative/order` | Sort combatants by initiative score. |
| POST | `/v1/characters/ability-modifier` | D&D 5e ability modifier for a score. |
| POST | `/v1/characters/proficiency` | Proficiency bonus for a level. |
| POST | `/v1/characters/derived-stats` | HP/AC/modifiers from level, abilities, and armor. |
| POST | `/v1/encounters/adjusted-xp` | Encounter difficulty using the XP multiplier table. |

### Combat

| Method | Endpoint | Notes |
| ------ | -------- | ----- |
| POST | `/v1/combat/sessions` | Create an initiative-sorted combat session. |
| POST | `/v1/combat/sessions/:id/conditions` | Add a condition to a combatant. |
| POST | `/v1/combat/sessions/:id/advance` | Advance turn; conditions decrement on the active combatant's turn start and expire at `remaining_rounds <= 0`. |

### Compendium

| Method | Endpoint | Notes |
| ------ | -------- | ----- |
| GET | `/v1/compendium/monsters/:slug` | Fetch a monster. |
| GET | `/v1/compendium/items/:slug` | Fetch an item. |
| POST | `/v1/compendium/monsters` | Create a monster. |
| POST | `/v1/compendium/items` | Create an item. |

### DM Tools

| Method | Endpoint | Notes |
| ------ | -------- | ----- |
| POST | `/v1/dm/encounter-builder` | Campaign-specific encounter builder. |
| POST | `/v1/dm/loot-parcel` | Fixed tier-1 loot parcel. |
| POST | `/v1/dm/session-recap` | Recap from the latest event. |

### PHB

| Method | Endpoint | Notes |
| ------ | -------- | ----- |
| POST | `/v1/phb/spell-slots` | Wizard 5 spell slots. |
| POST | `/v1/phb/rests/long` | Long-rest HP/hit-dice/exhaustion recovery. |
| POST | `/v1/phb/equipment-load` | Carrying capacity and encumbrance. |

### Analytics

| Method | Endpoint | Notes |
| ------ | -------- | ----- |
| GET | `/v1/campaigns/:id/analytics/summary` | Readiness score and open quest counts. |
| POST | `/v1/campaigns/:id/analytics/risk-report` | Risk level with optional zero-count inclusion. |

### Play-Mode Campaigns (turn-based lobby/active surface)

These endpoints use `Authorization: Bearer session-<username>` tokens. The auth layer treats a well-formed `session-<username>` token as a valid actor and infers the role from the username (`dm` → DM, otherwise player) so that ownership and membership checks work without requiring every test token to be pre-registered.

| Method | Endpoint | Notes |
| ------ | -------- | ----- |
| GET | `/v1/play/campaigns/:id/my-turn` | Player view of current turn and recent events. |
| GET | `/v1/play/campaigns/:id/gm/status` | GM dashboard with party and recent events. |
| GET | `/v1/play/campaigns/:id/turn` | Shared turn/phase/queue view. |
| GET | `/v1/play/campaigns/:id/document` | Players see only `story`; the GM also sees `dm_notes`. |
| POST | `/v1/play/campaigns` | Create a play-mode lobby (DM only). |
| POST | `/v1/play/campaigns/:id/members` | Join a lobby as a player. |
| POST | `/v1/play/campaigns/:id/start` | Start the campaign (DM/owner only, requires ≥2 members). |
| POST | `/v1/play/campaigns/:id/narrations` | GM narration. |
| POST | `/v1/play/campaigns/:id/actions` | Player action (advances actor to `dm`). |
| POST | `/v1/play/campaigns/:id/resolutions` | GM resolution (advances turn to the next player). |
| POST | `/v1/play/campaigns/:id/turn/nudge` | GM nudge of the current actor. |
| POST | `/v1/play/campaigns/:id/document` | Update the campaign document (GM only). |
| POST | `/v1/play/campaigns/:id/scenes` | Create a scene (GM only). |
| POST | `/v1/play/campaigns/:id/scenes/:scene_id/enter` | Set the current scene (GM only). |
| POST | `/v1/play/campaigns/:id/scenes/:scene_id/close` | Close a scene (GM only). |
| GET | `/v1/play/campaigns/:id/scenes/current` | Read the open current scene (any member). |

## Conventions for extending and testing

- **Keep handlers stateless.** All persistence must go through `src/lib/db/` modules. Do not introduce in-memory caches or module-level mutable state that affects responses.
- **Preserve route precedence.** If you add a new endpoint, insert it in `src/lib/router.ts` in the correct historical order and return early when matched to avoid shadowing existing routes.
- **Use existing validators.** Add new type guards to `src/lib/validation.ts` and reuse them in handlers.
- **Use `sendError` for failures.** This keeps the `{ error: message }` envelope consistent across every endpoint.
- **Keep rules pure.** Numerical calculations belong in `src/lib/rules.ts` so they can be unit-tested without a database or HTTP server.
- **Add persistence to the matching domain module.** If you need a new table, put the connection/schema changes in `src/lib/db/connection.ts` and the CRUD functions in the closest domain module (or create a new one).
- **NodeNext imports.** Because `tsconfig.json` uses `"moduleResolution": "NodeNext"`, all relative imports must include the `.js` extension (e.g., `import { x } from './rules.js'`). Vite transpiles the TypeScript files at dev time, so the `.js` extension is correct for both TypeScript and runtime ESM resolution.
- **Type-check before running.** Run `npx tsc --noEmit` to catch type or import-extension errors.
- **Testing.** The cumulative evaluator suite exercises all endpoints. You can also run quick ad-hoc checks with `curl` after starting the server via `./run.sh`. The schema can be reset with `POST /v1/storage/reset` between test runs.
