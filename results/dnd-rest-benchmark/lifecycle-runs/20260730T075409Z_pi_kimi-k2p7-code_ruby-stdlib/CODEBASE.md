# D&D DM Tools API — Codebase Guide

A multi-file Ruby HTTP server for a D&D 5e DM helper API. It uses only the
Ruby standard library plus SQLite, keeps domain logic in named modules under
`lib/`, and implements a tiny TCP/HTTP layer under `lib/http/`.

## Quick start

```bash
PORT=3000 ./run.sh
```

`run.sh` is a one-line wrapper that executes `ruby server.rb`. The server
binds to `127.0.0.1` and reads the port from the `PORT` environment variable
(defaulting to `3000`).

Verify it is listening:

```bash
curl http://127.0.0.1:$PORT/health
# => {"ok":true}
```

The server runs in the foreground; stop it with `Ctrl-C` or by sending
`SIGTERM` to the process.

## Entry point and file layout

- `run.sh` — the launcher required by the harness.
- `server.rb` — the entry point. Requires standard-library gems and all
  domain/HTTP modules in dependency order, then starts `HttpServer`.
- `lib/config.rb` — runtime constants (`HOST`, `PORT`, `DB_PATH`,
  `SCHEMA_VERSION`).
- `lib/persistence.rb` — SQLite schema, connection wrapper, table lists, and
  lifecycle helpers (`reset!`, `soft_reset!`, `initialize_schema!`).
- `lib/pure_rules.rb` — deterministic, side-effect-free game-rule helpers.
- `lib/auth.rb` — PBKDF2 password hashing and user/token storage.
- `lib/combat.rb` — combat sessions, initiative, and turn/condition tracking.
- `lib/compendium.rb` — monster and item reference entries.
- `lib/campaigns.rb` — campaign metadata, characters, and event logs.
- `lib/quests.rb` — campaign quest tracking and progress.
- `lib/factions.rb` — campaign factions, NPCs, and relationship summaries.
- `lib/inventory.rb` — campaign inventory and character equipment
  assignments.
- `lib/crafting.rb` — downtime crafting projects and progress.
- `lib/sessions.rb` — campaign session scheduling and attendance.
- `lib/analytics.rb` — campaign readiness and risk reports.
- `lib/play_campaigns.rb` — protected campaign-play surface: ownership,
  membership, turn queue, narration, actions, resolutions, documents,
  locations, scenes, encounters, character builds, and combat.
- `lib/player_handbook.rb` — PHB rule helpers (spell slots, rests,
  encumbrance).
- `lib/dm_tools.rb` — DM-facing helpers (encounter builder, loot parcel,
  session recap).
- `lib/http/request.rb` — HTTP request parsing.
- `lib/http/response.rb` — HTTP response building.
- `lib/http/router.rb` — method/path dispatch and JSON serialization.
- `lib/http/http_server.rb` — TCP accept loop and keep-alive handling.

## State, persistence, and routing

### Persistence design

- SQLite file: `game.db` in the working directory.
- A single `Mutex` (`Persistence::DB_MUTEX`) serializes all database access.
- `Persistence.db` yields a single shared `SQLite3::Database` connection that
  is opened when the module loads and reused for the lifetime of the process.
  This keeps the implementation simple and deterministic.
- `Persistence::APP_TABLES` lists every application table in dependency
  order. `reset!` and `soft_reset!` derive their drop lists from it, so adding
  a table only requires one list update.
- On startup the server calls `Persistence.reset!`. The schema statements use
  `IF NOT EXISTS`, and `reset!` drops every application table (including
  `users`) before recreating them, so the server begins each run with a clean
  state.
- `Persistence.soft_reset!` drops every application table *except* `users`
  and `schema_meta`, then recreates the schema. It is used by the
  `/v1/storage/reset` endpoint so authentication remains usable after a reset.
- `Persistence.initialize_schema!` can be used to create missing tables without
  dropping existing data.

### Request routing

- Raw socket I/O: `TCPServer` accepts connections; each connection is handled
  in its own thread so the accept loop is never blocked. `Request.parse`
  reads a request line, headers, and optional body.
- `Router.route` is a long `if/elsif` dispatch that matches `method + path`.
  Path parameters are captured with anchored regexes and forced to UTF-8 so
  SQLite binds them as text rather than blobs.
- Connections are kept open until the client closes them, supporting HTTP/1.1
  keep-alive without pipelining issues.
- Domain modules return `[:tag, data]` tuples:
  - `:ok` with a Hash body,
  - `:invalid` for validation failures,
  - `:not_found` for missing resources,
  - `:conflict` for duplicate IDs or business-rule conflicts,
  - `:forbidden` for authorization failures.
- `Router.handle_result` maps those tags to HTTP status codes (`200`, `201`,
  `400`, `403`, `404`, `409`) and serializes the body as JSON.
- Authenticated routes use `Router.with_auth` to centralize bearer-token
  validation and role checks, returning `401` or `403` when appropriate.
- Authentication endpoints (`/v1/auth/*`) are handled specially in the router
  because `Auth` returns booleans rather than tuples. A successful login
  returns a deterministic `session-<username>` token.

## Main API/domain groupings

| Group | Endpoints | Module |
|-------|-----------|--------|
| Core | `GET /health`, `POST /v1/dice/stats`, `POST /v1/checks/ability`, `POST /v1/encounters/adjusted-xp`, `POST /v1/initiative/order` | `PureRules` |
| Characters | `POST /v1/characters/ability-modifier`, `POST /v1/characters/proficiency`, `POST /v1/characters/derived-stats` | `PureRules` |
| Combat | `POST /v1/combat/sessions`, `POST /v1/combat/sessions/:id/conditions`, `POST /v1/combat/sessions/:id/advance` | `Combat` |
| Auth | `POST /v1/auth/register`, `POST /v1/auth/login` | `Auth` |
| Storage | `GET /v1/storage/status`, `POST /v1/storage/reset` | `Persistence` |
| Compendium | `POST /v1/compendium/monsters`, `GET /v1/compendium/monsters/:slug`, `POST /v1/compendium/items`, `GET /v1/compendium/items/:slug` | `Compendium` |
| Campaigns | `POST /v1/campaigns`, `POST /v1/campaigns/:id/characters`, `POST /v1/campaigns/:id/events`, `GET /v1/campaigns/:id/state`, `GET /v1/campaigns/:id/audit`, `GET /v1/campaigns/:id/export` | `Campaigns` |
| Quests | `POST /v1/campaigns/:id/quests`, `POST /v1/campaigns/:id/quests/:quest_id/progress`, `GET /v1/campaigns/:id/quests/summary` | `Quests` |
| Factions | `POST /v1/campaigns/:id/factions`, `POST /v1/campaigns/:id/npcs`, `GET /v1/campaigns/:id/relationships` | `Factions` |
| Inventory | `POST /v1/campaigns/:id/inventory`, `POST /v1/campaigns/:id/characters/:character_id/equipment`, `GET /v1/campaigns/:id/inventory/summary` | `Inventory` |
| Crafting | `POST /v1/campaigns/:id/downtime/crafting`, `POST /v1/campaigns/:id/downtime/crafting/:project_id/advance` | `Crafting` |
| Session scheduling | `POST /v1/campaigns/:id/sessions`, `POST /v1/campaigns/:id/sessions/:session_id/attendance`, `GET /v1/campaigns/:id/sessions/next` | `Sessions` |
| Analytics | `GET /v1/campaigns/:id/analytics/summary`, `POST /v1/campaigns/:id/analytics/risk-report` | `Analytics` |
| Play campaigns | `POST /v1/play/campaigns`, `POST /v1/play/campaigns/:id/members`, `POST /v1/play/campaigns/:id/start`, `POST /v1/play/campaigns/:id/narrations`, `POST /v1/play/campaigns/:id/locations`, `POST /v1/play/campaigns/:id/locations/:loc_id/connections`, `GET /v1/play/campaigns/:id/locations/:loc_id/travel`, `POST /v1/play/campaigns/:id/scenes`, `POST /v1/play/campaigns/:id/scenes/:scene_id/enter`, `POST /v1/play/campaigns/:id/scenes/:scene_id/close`, `GET /v1/play/campaigns/:id/scenes/current`, `GET /v1/play/campaigns/:id/document`, `PUT /v1/play/campaigns/:id/document`, `GET /v1/play/campaigns/:id/turn`, `POST /v1/play/campaigns/:id/turn/nudge`, `POST /v1/play/campaigns/:id/turn/travel`, `POST /v1/play/campaigns/:id/turn/rest`, `GET /v1/play/campaigns/:id/my-turn`, `GET /v1/play/campaigns/:id/gm/status`, `POST /v1/play/campaigns/:id/actions`, `POST /v1/play/campaigns/:id/resolutions`, `POST /v1/play/campaigns/:id/encounters`, `POST /v1/play/campaigns/:id/encounters/:enc_id/monsters`, `DELETE /v1/play/campaigns/:id/encounters/:enc_id/monsters/:monster_id`, `POST /v1/play/campaigns/:id/encounters/:enc_id/combatants`, `DELETE /v1/play/campaigns/:id/encounters/:enc_id/combatants/:member`, `POST /v1/play/campaigns/:id/encounters/:enc_id/conditions`, `GET /v1/play/campaigns/:id/encounters/:enc_id/status`, `POST /v1/play/campaigns/:id/encounters/:enc_id/turn/advance`, `POST /v1/play/campaigns/:id/encounters/:enc_id/turn/delay`, `POST /v1/play/campaigns/:id/encounters/:enc_id/turn/ready`, `GET /v1/play/campaigns/:id/encounters/:enc_id/turn`, `POST /v1/play/campaigns/:id/encounters/:enc_id/actions`, `POST /v1/play/campaigns/:id/encounters/:enc_id/damage`, `POST /v1/play/campaigns/:id/encounters/:enc_id/heal`, `POST /v1/play/campaigns/:id/encounters/:enc_id/rewards`, `POST /v1/play/campaigns/:id/encounters/:enc_id/close`, `POST /v1/play/campaigns/:id/encounters/:enc_id/end`, `POST /v1/play/campaigns/:id/characters/:char_id/damage`, `POST /v1/play/campaigns/:id/characters/:char_id/death-saves`, `GET /v1/play/campaigns/:id/characters/:char_id/status`, `GET /v1/play/campaigns/:id/characters/:char_id/owner`, `POST /v1/play/campaigns/:id/characters/:char_id/claim`, `POST /v1/play/campaigns/:id/characters/:char_id/transfer`, `POST /v1/play/campaigns/:id/characters/:char_id/build`, `POST /v1/play/campaigns/:id/characters/:char_id/level-up`, `POST /v1/play/campaigns/:id/characters/:char_id/skill-check`, `POST /v1/play/campaigns/:id/characters/:char_id/spells`, `GET /v1/play/campaigns/:id/characters/:char_id/spells`, `PUT /v1/play/campaigns/:id/characters/:char_id/prepared-spells`, `GET /v1/play/campaigns/:id/characters/:char_id/prepared-spells`, `POST /v1/play/campaigns/:id/npcs`, `PUT /v1/play/campaigns/:id/npcs/:npc_id/agenda`, `GET /v1/play/campaigns/:id/npcs/:npc_id`, `POST /v1/play/campaigns/:id/npcs/:npc_id/dialogue`, `GET /v1/play/campaigns/:id/npcs/:npc_id/dialogue`, `POST /v1/play/campaigns/:id/factions`, `POST /v1/play/campaigns/:id/factions/:faction_id/reputation`, `GET /v1/play/campaigns/:id/factions/:faction_id/reputation` | `PlayCampaigns` |
| PHB rules | `POST /v1/phb/spell-slots`, `POST /v1/phb/rests/long`, `POST /v1/phb/equipment-load` | `PlayerHandbook` |
| DM tools | `POST /v1/dm/encounter-builder`, `POST /v1/dm/loot-parcel`, `POST /v1/dm/session-recap` | `DmTools` |

## Conventions for extending and testing

### Adding a new endpoint

1. If the endpoint is pure computation, put it in the appropriate domain
   module (e.g., `PureRules`, `PlayerHandbook`, `DmTools`) and have it return
   a Hash on success or `nil` on invalid input.
2. If the endpoint needs persistence, add it to the module that owns the data
   (e.g., `Combat`, `Campaigns`, `Compendium`, `PlayCampaigns`) and return a
   `[:tag, data]` tuple.
3. Wire the endpoint into `Router.route` with an explicit `method`/`path`
   check and call `handle_result` or `json_response` / `error_response` as
   needed.
4. If the endpoint requires authentication, wrap the handler with
   `with_auth(request, %w[role]) { |actor| ... }`.
5. If the endpoint creates a resource, use status `201`; otherwise use `200`.

### Adding a new table

1. Add the `CREATE TABLE` statement to `Persistence::SCHEMA_SQL`.
2. Add the table name to `Persistence::APP_TABLES` in dependency order.
   `reset!` and `soft_reset!` derive their drop lists from this single source.
3. Add a module that owns reads and writes for that table.
4. Keep validation logic private with `private_class_method`.

### Shared helpers inside `PlayCampaigns`

`PlayCampaigns` uses a few private helpers to keep repetition low:

- `record_narration(d, campaign_id, kind, actor_name, text)` allocates the
  next sequence number and inserts a narration row. All narration-producing
  endpoints flow through it so sequence numbers stay monotonic.
- `recent_events(d, campaign_id)` returns the newest narrations.
- `build_encounter_order(...)` constructs or reuses the encounter turn order,
  sorting by initiative with deterministic tie-breaking.
- `public_combatant` / `public_order` strip internal `_` prefixed routing
  keys before sending combatants to the client.

### Testing locally

Because the server is a single entry point, you can run it directly:

```bash
PORT=3000 ruby server.rb
```

Then exercise endpoints with `curl` or any HTTP client. To reset state between
manual test runs, use:

```bash
curl -X POST http://127.0.0.1:$PORT/v1/storage/reset
```

For automated regression testing, run the cumulative `dndeval` suite against
the running server. The cumulative suite exercises every endpoint above and
verifies prior-stage behavior.

You can also load the codebase without starting the server to exercise domain
modules in isolation:

```bash
ruby -Ilib -e "load './server.rb'; puts Router.route(Request.new('GET', '/health', {}, nil)).to_s"
```

### Determinism

- Game-rule helpers are pure functions of their inputs.
- Combat initiative uses deterministic tie-breaking (`score`, then `dex`, then
  name for the legacy combat helper; `initiative`, then `name`, then `kind`,
  then `_target` for encounter order in `PlayCampaigns`).
- `DmTools.loot_parcel` is deterministic for a given tier and seed; it does
  not use `SecureRandom`.
- Password hashing still uses `SecureRandom` for salts, which is correct for
  security and does not affect the deterministic test flows that register and
  then immediately authenticate the same user.

### What to avoid

- Do not introduce Rack, Rails, Sinatra, or external gems. The runtime contract
  is Ruby stdlib + SQLite only.
- Do not change existing response shapes, status codes, validation rules, or
  persistence semantics for endpoints already exercised by the cumulative
  `dndeval` suite.
- Keep domain modules independent of HTTP details; the `Router` is the only
  place that knows about JSON and status codes.
- Avoid circular `require_relative` dependencies between modules; the entry
  point loads them in the correct order.
- Avoid duplicating table names in `reset!` and `soft_reset!`; add them once
  to `APP_TABLES` and let the two reset methods derive their lists.
