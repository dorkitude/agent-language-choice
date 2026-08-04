# D&D REST API — Codebase Guide

A minimal, single-purpose Rails 8 API that implements a small subset of D&D 5e
utilities for a staged benchmark. The server is intentionally lightweight: no
Active Record models, no view layer, no background jobs, and only the
`action_controller` and `railtie` parts of Rails are loaded.

## Starting and verifying the server

The server is started from the project root with the provided wrapper:

```bash
PORT=4567 ./run.sh
```

`run.sh` runs `bundle exec puma -t 1:1 -b "tcp://127.0.0.1:${PORT}"` in the foreground, so
Puma listens on the requested host and port with a single worker thread and logs to stdout. To verify it:

```bash
curl http://127.0.0.1:4567/health
```

Expected response:

```json
{ "ok": true }
```

A smoke test that exercises the main endpoints is:

```bash
BASE=http://127.0.0.1:4567
curl -X POST "$BASE/v1/storage/reset"
curl -X POST "$BASE/v1/auth/register" -H 'Content-Type: application/json' \
  -d '{"username":"dm","password":"password123","role":"dm"}'
curl -X POST "$BASE/v1/dice/stats" -H 'Content-Type: application/json' \
  -d '{"expression":"2d6+3"}'
```

## Entry point and major files

| File / Directory | Purpose |
| ---------------- | ------- |
| `run.sh` | Foreground server wrapper. Uses `PORT`, binds to `127.0.0.1`, and runs Puma with one thread for deterministic request handling. |
| `config.ru` | Rack entry point. Loads `app.rb` and mounts `Rails.application`. |
| `app.rb` | Defines the Rails application (`Dnd::Application`), loads the shared
  storage module, and initializes the database. |
| `config/routes.rb` | All HTTP routes grouped by domain. One explicit route per
  endpoint, no resource macros. |
| `app/controllers/` | One controller per domain. All inherit from
  `ApplicationController`, which parses JSON bodies and provides shared 400/401
  helpers. |
| `app/controllers/concerns/dnd_rules.rb` | Shared domain rules and validation
  helpers: initiative math, encounter difficulty, identifier validation,
  ability modifiers, proficiency bonuses, and `find_campaign`. |
| `app/models/game_storage.rb` | Shared SQLite3 persistence module. Bypasses
  Active Record and uses raw SQL plus a global mutex for write safety. |
| `Gemfile` / `Gemfile.lock` | Pinned dependency set: Rails 8.1.3, Puma 8.0.2,
  Rack 3.2.6, Rackup 2.3.1, SQLite3, BCrypt. |

## State, persistence, and request routing

### Persistence

State lives in a single SQLite3 database file named `game.db` in the project
root. The schema is created by `GameStorage.init` on startup, so the server is
self-initializing. Tables include:

- `users` — DM/player accounts with BCrypt password digests.
- `combat_sessions` — active combat order and conditions as JSON columns.
- `monsters` and `items` — compendium entries.
- `campaigns`, `campaign_characters`, `campaign_events` — campaign state.
- `quests`, `factions`, `npcs` — campaign narrative state.
- `inventory` — campaign inventory entries and assigned equipment.
- `crafting_projects` — downtime crafting progress.
- `sessions`, `session_attendance` — scheduled sessions and attendance.
- `play_campaigns`, `play_campaign_members`, `play_campaign_events` —
  authenticated turn-based play surface.
- `play_campaign_documents` — public story and private DM notes.
- `play_campaign_scenes` — scenes that can be opened, entered, and closed.
- `play_campaign_locations`, `play_campaign_location_connections` — location
  graph and travel edges.
- `play_campaign_encounters` — combat encounters with combatants, conditions,
  turn order, and rewards.
- `play_campaign_spells` — per-character spellbook entries validated against the
  character's class.
- `schema_version` — schema marker used by the storage status endpoint.

The connection is opened lazily by `GameStorage.db`. All writes and any
read-modify-write sequence are wrapped in `GameStorage.with_lock` because the
Puma server runs multi-threaded and the SQLite3 build in this workspace is not
configured for concurrent writers.

`GameStorage.init` calls `create_schema` (the single source of truth for a
fresh database) and then a compact set of migrations grouped by table:
`migrate_play_campaigns`, `migrate_play_events`, `migrate_play_members`,
`migrate_play_documents`, `migrate_play_scenes`, `migrate_play_locations`, and
`migrate_play_encounters`. Each migration is idempotent: it adds missing
columns or creates missing tables only when they are absent. The `reset`
endpoint drops every managed table and recreates them from `create_schema`, so
tests always start from a deterministic, empty state.

### Request routing

Routes are explicit in `config/routes.rb`. No namespaces, no generated helpers.
Each route maps a verb + path to a single controller action. For example:

```ruby
post '/v1/combat/sessions/:id/advance', to: 'combat_sessions#advance'
```

Path parameters are available through `params[:id]`, and the parsed JSON body is
available through the `@body` instance variable populated by
`ApplicationController#parse_json_body`.

### Controllers

`ApplicationController` is the API base. It:

1. Runs `before_action :parse_json_body` for every action.
2. Returns `400 { error: 'invalid json' }` if the body is malformed.
3. Provides `bad_request(message)` for 400 responses.
4. Provides `require_authentication` and `require_dm` for the play surface.

`DndRules` is included in `ApplicationController` so every concrete controller
has access to shared validation (`valid_id?`, `valid_non_empty_string?`) and
D&D 5e math (`initiative_order`, `build_party_thresholds`, `modifier_for`,
`proficiency_bonus`, etc.). It also provides `find_campaign(id)` for 404-aware
campaign lookups.

Concrete controllers keep validation and domain logic together. They return the
exact JSON shapes the cumulative evaluator expects. Prefer `valid_id?` and
`valid_non_empty_string?` over inline regex so the identifier rules stay in
one place, and use `find_campaign` after validating the id to avoid changing 400
vs 404 semantics.

## Main API / domain groupings

Endpoints are grouped by controller under the `/v1/` prefix:

- **Health** — `GET /health` liveness probe.
- **Auth** — `POST /v1/auth/register`, `POST /v1/auth/login`.
- **Dice** — `POST /v1/dice/stats` parses expressions like `2d6+3`.
- **Checks** — `POST /v1/checks/ability` evaluates d20 + modifier vs. DC.
- **Encounters** — `POST /v1/encounters/adjusted-xp` computes difficulty.
- **Initiative** — `POST /v1/initiative/order` sorts combatants by score.
- **Characters** — ability modifier, proficiency bonus, and derived stats.
- **Combat Sessions** — create, add condition, and advance a stored combat round.
- **Storage** — `GET /v1/storage/status`, `POST /v1/storage/reset`.
- **Compendium** — create/read monsters and items.
- **Campaigns** — create campaigns, add characters/events, read aggregate state.
- **Quests / NPCs / Factions / Inventory / Downtime / Sessions** — campaign
  management sub-resources.
- **PHB** — spell slots, long rest, and equipment load rules.
- **DM Tools** — encounter builder, loot parcel, and session recap.
- **Play Campaigns** — authenticated `/v1/play` surface. Only authenticated `dm`
  users may create, start, narrate, nudge, and resolve turns; players join,
  submit actions, and read their own turn context. The document endpoints let
  the DM write a public story and private DM notes; players read only the story.
- **Scenes / Locations / Encounters** — the play surface also manages scenes,
  a travel graph of locations, and turn-based combat encounters with monsters,
  party combatants, conditions, damage, healing, and rewards.
- **Character Ownership / Build / Level / Skills / Spells** — players can claim,
  transfer, build (race/class/background/abilities), level up, roll skill
  checks, and maintain a class-validated spellbook for their own characters.

## Play campaign turn flow

The turn queue is deterministic and derived from the insertion order of party
members (`ORDER BY ROWID`). After the DM starts a campaign, the queue alternates
`player -> dm -> next player`. The current actor is stored in
`play_campaigns.current_actor`, and events are appended to
`play_campaign_events` with monotonically increasing `sequence` values.

- `POST /v1/play/campaigns/:id/actions` — a player submits an action; the event
  is stored with `kind = 'action'` and `next_actor = 'dm'`; the current actor
  moves to the DM.
- `POST /v1/play/campaigns/:id/resolutions` — the DM resolves the latest action;
  the event is stored with `kind = 'resolution'` and `next_actor` set to the
  next player in the queue; the current actor and turn number advance.
- `GET /v1/play/campaigns/:id/turn` and `GET /v1/play/campaigns/:id/my-turn` —
  read the current actor and recent events. Players see only public fields; the
  DM sees the full party and GM context.

Combat encounters transition the campaign into `phase = 'combat'` and save the
previous actor in `saved_actor`. When the encounter ends, the campaign returns
to `phase = 'exploration'` and restores the saved actor. The play surface uses
the same deterministic initiative order for encounter combatants: descending
initiative, with insertion order as the tie-breaker; an explicit `order_json`
overrides the default sort once delay/ready actions are used.

## Conventions for extending and testing

### Adding an endpoint

1. Add a route in `config/routes.rb`. Keep the explicit style and group it near
   related routes.
2. Add the action in the appropriate controller, or create a new controller in
   `app/controllers/` inheriting from `ApplicationController`.
3. Read request data from `@body` (JSON) and `params` (path/query).
4. Validate inputs using `valid_id?` and `valid_non_empty_string?` where
   applicable. Return `bad_request(...)` with a 400 for invalid payloads.
5. For database-backed endpoints, wrap writes in `GameStorage.with_lock`. Use
   `find_campaign` for 404-aware campaign lookups after validating the id.
6. If the new endpoint needs shared D&D math, add the helper to
   `DndRules` rather than duplicating it in a controller.
7. If you add a spellbook endpoint, add the route to `config/routes.rb` and the
   actions to `PlayCampaignsController`. Wizard spells are valid for wizards,
   rogues may not learn spells, and duplicate spells per character return 409.

### Modifying the schema

If you add a table, update `GameStorage.create_schema` and bump
`GameStorage::SCHEMA_VERSION`. The reset endpoint returns the schema version so
tests can confirm the right shape is present. For idempotent column additions,
add the column to the appropriate `migrate_play_*` method in `GameStorage` and
use `ensure_columns` so the migration stays safe on both fresh and existing
databases. The benchmark suite expects existing endpoint responses to remain
unchanged.

### Testing

There is no bundled test framework. The cumulative evaluator drives the running
server as a black box, so the recommended workflow is:

1. Start the server with `./run.sh`.
2. Reset storage with `POST /v1/storage/reset` to get a deterministic state.
3. Use `curl` or the evaluator scripts to hit endpoints and assert response
   bodies and status codes.

When refactoring, preserve the exact response JSON, status codes, and validation
order, because the cumulative suite checks them byte-for-byte in many places.
