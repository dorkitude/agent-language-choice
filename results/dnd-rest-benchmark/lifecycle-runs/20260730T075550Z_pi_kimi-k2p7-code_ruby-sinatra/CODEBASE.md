# D&D DM Tools — Codebase Guide

A small, deterministic Sinatra API for D&D 5e DM helpers: dice, character math,
combat state, compendium, campaign management, play-by-post campaigns, and
encounter mechanics. There are no background jobs, no external services, and a
single SQLite database file.

## Runtime versions

The Gemfile pins the runtime/framework versions used by this workspace:

- Ruby 4.0.5
- Sinatra 4.2.1
- Rack 3.2.6
- Rackup 2.3.1
- Puma 8.0.2
- sqlite3 2.9.5

## Quick start

```bash
bundle install
PORT=4567 ./run.sh
```

`run.sh` starts the server in the foreground on `127.0.0.1`, using the `PORT`
environment variable. It also removes and recreates `game.db` on every launch so
each run begins with a fresh schema.

Verify the server is up:

```bash
curl http://127.0.0.1:$PORT/health
```

Expected response:

```json
{ "ok": true }
```

Stop the server with `Ctrl-C`.

## Entry point and file layout

```
app.rb                    # Sinatra setup, shared helpers, route requires
lib/
  auth.rb                 # Bearer-token authentication and password hashing
  game_logic.rb           # Pure D&D 5e calculations and encounter constants
  storage.rb              # SQLite persistence layer
  validation.rb           # Input validation helpers
  routes/                 # Domain route files (loaded in precedence order)
    core.rb               # Health, dice, checks, initiative, encounter XP
    characters.rb         # Ability modifier, proficiency, derived stats
    combat_sessions.rb    # Combat session state and conditions
    auth.rb               # User registration and login
    storage.rb            # Storage status and reset
    compendium.rb         # Monster and item compendium
    campaigns.rb          # Campaigns, quests, factions/NPCs, inventory
    phb.rb                # PHB rule helpers (spell slots, rests, load)
    dm_tools.rb           # DM encounter builder, loot, session recap
    downtime.rb           # Crafting projects
    sessions.rb           # Session scheduling, attendance, audit, analytics
    play_lobby.rb         # Play campaign creation, membership, start
    play_turns.rb         # Narrations, actions, resolutions, turn views
    play_document.rb      # Campaign story / dm_notes document
    play_exports.rb       # Versioned DM-only campaign exports
    play_scenes.rb        # Scene state
    play_locations.rb     # Location graph
    play_travel_rest.rb   # Travel and rest turns
    play_encounters.rb    # Encounters, roster, combat turns, actions, rewards
    play_characters.rb    # Character damage, death saves, build, level-up
    play_moderation.rb    # Campaign moderation reports and DM resolution
    play_safety_boundaries.rb # Safety boundaries and accepted safety events
    play_fixture_seeding.rb   # Campaign-scoped deterministic fixture seeding
run.sh                    # Foreground server launcher
Gemfile                   # Version pins
```

`app.rb` requires the four helper modules, configures the server bind address
and port, initializes the SQLite schema, registers the helper modules, defines
shared request helpers, and then loads the route files.

The app uses **classic Sinatra** style (`require 'sinatra'` and routes defined at
the top level), so `bundle exec ruby app.rb` works directly.

## State, persistence, and request-routing design

### Persistence

All durable state lives in `game.db` (SQLite). The `Storage` module owns every
SQL statement and the single shared database connection.

- `Storage::DB_PATH` resolves to the project-root `game.db`.
- `Storage::DB_MUTEX` serializes all database access because Puma may serve
  requests concurrently and the Ruby `sqlite3` connection object is not
  thread-safe for unsynchronized use.
- `Storage::SCHEMA_VERSION` is `1`. It is recorded in the `schema_info` table on
  first boot.
- JSON is stored as text columns (`*_json`) and parsed/serialized by the
  storage layer. `Storage.json_column(row, column, default)` centralizes the
  parse step; `Storage.ensure_column!(db, table, column, definition)` runs the
  incremental schema migrations so older databases can be reopened safely.

Schema is created on boot by `Storage.init_schema!`. Tables are created with
`IF NOT EXISTS`, so restarts are safe. The `POST /v1/storage/reset` endpoint
(and `Storage.reset!`) drops and recreates all tables for tests.

Key tables:

- `combat_sessions` — turn order, active round/turn, and per-target conditions.
- `users` — username, password hash, role (`dm` or `player`).
- `compendium_monsters` / `compendium_items` — stat blocks and magic items.
- `campaigns`, `campaign_characters`, `campaign_events` — base campaigns.
- `campaign_quests` — quest headers, milestones, completed milestones.
- `campaign_factions` / `campaign_npcs` — factions and their NPCs.
- `campaign_inventory` — party and per-character item quantities.
- `campaign_crafting_projects` — downtime crafting state.
- `campaign_sessions` / `campaign_session_attendance` — scheduled sessions and
  attendance.
- `play_campaigns`, `play_campaign_members`, `play_campaign_narrations` —
  owned live-play campaigns, party membership, and ordered narration/action/
  resolution events. `play_campaigns` stores the durable campaign document
  (`story`, `dm_notes`), turn queue, turn number, scene/location state, and
  pre-combat exploration state.
- `play_campaign_scenes` / `play_campaign_locations` /
  `play_campaign_location_connections` — scene and location graph.
- `play_campaign_exports` — immutable, versioned snapshots of a play
  campaign's public `story` and `status`, writable and readable only by the DM.
- `play_campaign_encounters` / `play_campaign_encounter_monsters` — active
  encounters, monster roster, bound party combatants, conditions, readies,
  rewards, and cached initiative order.
- `play_campaign_moderation_reports` — campaign-scoped moderation reports with
  a single open→resolved transition.
- `play_campaign_safety_boundaries` / `play_campaign_safety_events` — campaign
  blocked tags and accepted safety checks.
- `play_campaign_fixtures` — deterministic canonical fixture state seeded by the
  DM and readable by campaign members.

### Routing

Routes are grouped by domain in `lib/routes/`. Each file contains only Sinatra
route definitions and delegates persistence and math to `Storage` and
`GameLogic`. Files are loaded from `app.rb` in precedence order, so route
matching order matches the original monolithic layout.

Every successful JSON route calls `content_type :json` before producing the
body. Error halts use `json_error(status, message)`, which sets the
`application/json` content type and a JSON body `{"error":"..."}`. The
`POST /v1/dice/stats` route intentionally omits the explicit content type on
its validation halt, preserving original behavior.

### Helper modules

- `GameLogic` — pure functions (ability modifier, proficiency, initiative order,
  encounter XP/difficulty). No side effects; easy to test in isolation.
- `Validation` — input guards that may `halt` with a 400 response. They depend on
  the request context through the `json_error` helper.
- `Auth` — bearer-token extraction, password hashing, and role enforcement.
  Uses PBKDF2-HMAC-SHA256 with a username-derived salt.

Shared application helpers live in the anonymous `helpers` block in `app.rb`:

- `parse_json_body` — read and parse JSON; halt 400 on parse errors.
- `find_combat_session!` — load a combat session or halt 404.
- `combat_session_response(session, extra = {})` — format a session for the
  public API.
- `json_error(status, message)` — uniform JSON halt helper.
- `require_campaign_exists!(campaign_id)` — validate id and halt 404.
- `load_play_campaign!(campaign_id)` — load a play campaign or halt 404.
- `require_play_campaign_access!` / `require_play_campaign_owner!` —
  membership/ownership guards.
- `load_play_encounter!(campaign_id, enc_id, username, require_owner: false)` —
  shared campaign/encounter loading and access/ownership enforcement used by the
  encounter route group.
- `current_actor_for(campaign, turn_number = nil)` — deterministic actor whose
  turn it is from the turn queue.
- `phase_for(actor)` — map actor name to `dm` or `player`.
- `advance_play_campaign_turn!` / `advance_to_dm_phase_and_turn!` /
  `advance_to_dm_phase!` — turn-queue advancement helpers.
- `encounter_order` / `encounter_order_for` / `refresh_encounter_order!` / `recompute_encounter_order!` —
  deterministic initiative order for campaign encounters; `recompute_encounter_order!`
  reloads the roster before refreshing so route files do not duplicate that logic.
- `encounter_active(combatant)` — public shape for an active combatant.
- `condition_key_for(combatant)` — condition-storage key for a combatant.
- `valid_encounter_target?` — roster membership check for condition targets.
- `apply_condition_decay_for_active!` — decrement and purge expired conditions
  at the start of a turn.
- `campaign_readiness_signals` — compute readiness flags and active quest count.
- `play_turn_deadline` / `play_logical_deadline` — deterministic deadlines from
  turn number.
- `encounter_calculation(party, monster_slugs)` — campaign-aware encounter
  builder that loads compendium monsters and halts 404 if any slug is missing.

## Main API/domain groupings

| Group | Endpoints | Notes |
|-------|-----------|-------|
| Core | `GET /health`, `POST /v1/dice/stats`, `POST /v1/checks/ability`, `POST /v1/encounters/adjusted-xp`, `POST /v1/initiative/order` | Deterministic math; no persistence. |
| Characters | `POST /v1/characters/ability-modifier`, `POST /v1/characters/proficiency`, `POST /v1/characters/derived-stats` | Bounded integer validation (scores 1..30, levels 1..20). |
| Combat sessions | `POST /v1/combat/sessions`, `POST /v1/combat/sessions/:id/conditions`, `POST /v1/combat/sessions/:id/advance` | Stores turn order, round, turn index, and conditions with remaining rounds. |
| Auth | `POST /v1/auth/register`, `POST /v1/auth/login` | Usernames match `/\A[a-z0-9_-]{2,32}\z/`. Passwords ≥ 8 chars. Roles are `dm` or `player`. |
| Storage | `GET /v1/storage/status`, `POST /v1/storage/reset` | Schema version and destructive reset. |
| Compendium | `POST /v1/compendium/monsters`, `GET /v1/compendium/monsters/:slug`, `POST /v1/compendium/items`, `GET /v1/compendium/items/:slug` | Slugs match `/\A[a-z0-9-]+\z/`. Duplicate slug returns 409. |
| Campaigns | `POST /v1/campaigns`, `POST /v1/campaigns/:id/characters`, `POST /v1/campaigns/:id/events`, `GET /v1/campaigns/:id/state` | Characters and events live under a campaign; state returns campaign info. |
| Quests | `POST /v1/campaigns/:id/quests`, `GET /v1/campaigns/:id/quests/summary`, `POST /v1/campaigns/:id/quests/:quest_id/progress` | Status is `active`, `completed`, or `blocked`. |
| Factions/NPCs | `POST /v1/campaigns/:id/factions`, `POST /v1/campaigns/:id/npcs`, `GET /v1/campaigns/:id/relationships` | NPCs reference a faction; relationships summarize counts. |
| Inventory | `POST /v1/campaigns/:id/inventory`, `POST /v1/campaigns/:id/characters/:character_id/equipment`, `GET /v1/campaigns/:id/inventory/summary` | Items start in the `party` owner and are assigned to characters. |
| PHB rules | `POST /v1/phb/spell-slots`, `POST /v1/phb/rests/long`, `POST /v1/phb/equipment-load` | Hard-coded wizard L5 spell slots and simple rest/load math. |
| DM tools | `POST /v1/dm/encounter-builder`, `POST /v1/dm/loot-parcel`, `POST /v1/dm/session-recap` | Encounter builder requires existing campaign and compendium monsters. |
| Downtime | `POST /v1/campaigns/:id/downtime/crafting`, `POST /v1/campaigns/:id/downtime/crafting/:project_id/advance` | Crafting projects advance by days; completion adds one item to party inventory. |
| Sessions | `POST /v1/campaigns/:id/sessions`, `POST /v1/campaigns/:id/sessions/:session_id/attendance`, `GET /v1/campaigns/:id/sessions/next` | `starts_at` must be ISO-8601; `next` returns the earliest scheduled session. |
| Audit/Export/Analytics | `GET /v1/campaigns/:id/audit`, `GET /v1/campaigns/:id/export`, `GET /v1/campaigns/:id/analytics/summary`, `POST /v1/campaigns/:id/analytics/risk-report` | Aggregate campaign metadata and readiness/risk scoring. |
| Play lobby | `POST /v1/play/campaigns`, `POST /v1/play/campaigns/:id/members`, `POST /v1/play/campaigns/:id/start` | DM creates lobby; players join; start requires ≥ 2 members and builds a `player, dm, player, dm, ...` turn queue. |
| Play turns | `POST /v1/play/campaigns/:id/narrations`, `POST /v1/play/campaigns/:id/actions`, `POST /v1/play/campaigns/:id/resolutions`, `POST /v1/play/campaigns/:id/turn/nudge`, `GET /v1/play/campaigns/:id/turn`, `GET /v1/play/campaigns/:id/my-turn`, `GET /v1/play/campaigns/:id/gm/status` | DM narrates; players submit actions; DM resolves. Actions and resolutions advance the turn queue. |
| Play document | `GET /v1/play/campaigns/:id/document`, `PUT /v1/play/campaigns/:id/document` | Owner-write durable `story` and `dm_notes`; owners read both, members read only `story`. |
| Play exports | `POST /v1/play/campaigns/:id/exports`, `GET /v1/play/campaigns/:id/exports`, `GET /v1/play/campaigns/:id/exports/:version` | DM-only immutable snapshots of the campaign's current public `story` and `status`, sequenced by version. |
| Play scenes | `POST /v1/play/campaigns/:id/scenes`, `POST /v1/play/campaigns/:id/scenes/:scene_id/enter`, `POST /v1/play/campaigns/:id/scenes/:scene_id/close`, `GET /v1/play/campaigns/:id/scenes/current` | DM-managed scene stack. |
| Play locations | `POST /v1/play/campaigns/:id/locations`, `POST /v1/play/campaigns/:id/locations/:from_id/connections`, `GET /v1/play/campaigns/:id/locations/:loc_id/travel` | DM builds a deterministic location graph; any member reads valid outbound destinations. |
| Play travel/rest | `POST /v1/play/campaigns/:id/turn/travel`, `POST /v1/play/campaigns/:id/turn/rest` | Active player consumes a travel or rest turn; travel advances along a valid edge, long rest restores HP. |
| Play encounters | `POST /v1/play/campaigns/:id/encounters`, `POST/DELETE /v1/play/campaigns/:id/encounters/:enc_id/monsters/:monster_id`, `POST/DELETE /v1/play/campaigns/:id/encounters/:enc_id/combatants/:member`, `GET /v1/play/campaigns/:id/encounters/:enc_id/turn`, `POST .../turn/advance`, `POST .../turn/delay`, `POST .../turn/ready`, `POST .../actions`, `POST .../damage`, `POST .../heal`, `POST .../conditions`, `GET .../status`, `POST .../rewards`, `POST .../close`, `POST .../end` | DM creates/manages encounter roster; party members bind as combatants; turn authority, delay/ready, combat actions, HP changes, conditions, rewards, and transition back to exploration. |
| Play characters | `POST /v1/play/campaigns/:id/characters/:char_id/damage`, `POST .../death-saves`, `GET .../status`, `GET .../owner`, `POST .../claim`, `POST .../transfer`, `POST .../build`, `POST .../level-up`, `POST .../skill-check`, `POST/GET .../spells`, `PUT/GET .../prepared-spells` | Character ownership, build choices, level progression, HP/damage/death saves, skill checks, known spells, and prepared spells. |
| Play moderation | `POST /v1/play/campaigns/:id/moderation/reports`, `GET /v1/play/campaigns/:id/moderation/reports`, `PUT /v1/play/campaigns/:id/moderation/reports/:report_id/resolution` | Members (including the DM) submit/read reports; only the DM resolves an open report once. |
| Play safety boundaries | `PUT /v1/play/campaigns/:id/safety-boundaries`, `GET /v1/play/campaigns/:id/safety-boundaries`, `POST /v1/play/campaigns/:id/safety-checks`, `GET /v1/play/campaigns/:id/safety-events` | DM-only boundary replacement; members submit safety checks; blocked/duplicate checks return 409. |
| Play fixture seeding | `POST /v1/play/campaigns/:id/fixture-seeds`, `GET /v1/play/campaigns/:id/fixture-state` | DM-only seeding of `canonical-v1`; first seed returns 201, repeats return 200; members read seeded state or 404. |

## Conventions for extending and testing

### Adding a new endpoint

1. Put the route in the most specific `lib/routes/*.rb` file (or create a new
   domain file and require it from `app.rb` in the right precedence order).
2. If the endpoint is pure math, add the calculation to `lib/game_logic.rb`.
3. If it validates input, add a validation helper to `lib/validation.rb` or
   reuse an existing one. Keep validation rules identical to prior stages
   because the evaluator suite is cumulative.
4. If it persists data, add the SQL methods to `lib/storage.rb`. Reuse
   `Storage.json_column` for JSON columns and `Storage.with_db` for all access.
5. Keep responses deterministic. Do not add randomness or time-dependent
   behavior.
6. Do not remove or rename existing endpoints, status codes, or response keys
   unless the stage spec explicitly changes.
7. For play-campaign routes that need both id validation and authentication,
   call `validate_campaign_id!(campaign_id)` before the auth helper so that an
   empty id still produces a 400 response before a 401/403.

### Testing

There is no bundled test framework. Useful local checks:

- Syntax: `ruby -c app.rb && ruby -c lib/*.rb && ruby -c lib/routes/*.rb`
- Load check: `bundle exec ruby -e "require_relative 'app'; puts 'loaded'"`
- Route list: `bundle exec ruby -e "require_relative 'app'; puts Sinatra::Application.routes.keys"`
- Manual endpoint check with the server running: `curl http://127.0.0.1:$PORT/health`

When testing against the database, keep in mind that `POST /v1/storage/reset`
will destroy all data. `run.sh` already starts with a fresh `game.db`, so a
single server run is isolated.

### Important invariants

- The `combat_order` tie-breaker is total score → Dexterity score → name, so
  order is deterministic.
- The encounter multiplier table follows the D&D 5e DMG: 1×, 1.5×, 2×, 2.5×,
  3×, 4× for monster counts 1, 2, 3–6, 7–10, 11–14, 15+.
- Only level 3 party thresholds are currently populated in
  `GameLogic::LEVEL_THRESHOLDS` because the existing endpoint suite exercises
  level 3 parties.
- The password salt is deterministic (`"dnd-auth-salt-#{username}"`). Do not
  change this without also migrating existing users.
- The storage mutex is required for any database access. Never call `Storage.db`
  directly from outside the `Storage` module; use `Storage.with_db` or the
  higher-level methods.
- Play-campaign narration/action/resolution/travel/rest/scene/combat events
  share a single per-campaign sequence counter; `Storage.insert_narration` is
  the single path for appending.
- Initiative order for campaign encounters is cached in `order_json`. Roster
  changes recompute and overwrite the cached order via
  `refresh_encounter_order!`.
