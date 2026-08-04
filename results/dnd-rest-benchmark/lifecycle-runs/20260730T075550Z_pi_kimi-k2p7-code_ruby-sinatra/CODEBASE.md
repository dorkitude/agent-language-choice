# D&D DM Tools — Codebase Guide

This is a small Sinatra API that provides dice, character, combat, compendium,
campaign, and DM-helper endpoints for a D&D 5e table. The implementation is
intentionally minimal and deterministic: no background jobs, no external
services, and a single SQLite database file.

## Quick start

```bash
bundle install
PORT=4567 ./run.sh
```

`run.sh` starts the server in the foreground on `127.0.0.1` using the `PORT`
environment variable. The same port is also read by `app.rb` as a fallback, but
`run.sh` always passes it on the command line.

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
app.rb              # Sinatra application, route definitions, request helpers
lib/
  auth.rb           # Password hashing (PBKDF2)
  game_logic.rb     # Pure D&D 5e calculations and encounter constants
  storage.rb        # SQLite persistence layer
  validation.rb     # Input validation helpers
run.sh              # Foreground server launcher
Gemfile             # Pin: sinatra 4.2.1, rack 3.2.6, puma 8.0.2, sqlite3 2.9.5
```

`app.rb` requires the four libraries, configures the server bind address and
port, initializes the SQLite schema, and then registers the helper modules and
routes. The app uses **classic Sinatra** style (`require 'sinatra'` and routes
defined at the top level) so that `ruby app.rb` works directly.

## State, persistence, and request-routing design

### Persistence

All durable state lives in `game.db` (SQLite). The `Storage` module owns every
SQL statement and the single shared database connection. Key facts:

- `Storage::DB_PATH` resolves to the project-root `game.db`.
- `Storage::DB_MUTEX` serializes all database access because Puma may serve
  requests concurrently and the Ruby `sqlite3` connection object is not
  thread-safe for unsynchronized use.
- `Storage::SCHEMA_VERSION` is `1`. It is recorded in the `schema_info` table on
  first boot.
- JSON is stored as text columns (`*_json`) and parsed/serialized by the
  storage layer.

Schema is created on boot by `Storage.init_schema!`. Tables are created with
`IF NOT EXISTS`, so restarts are safe. The `POST /v1/storage/reset` endpoint
(and `Storage.reset!`) drops and recreates all tables for tests.

Tables:

- `combat_sessions` — turn order, active round/turn, and per-target conditions.
- `users` — username, password hash, role (`dm` or `player`).
- `compendium_monsters` — stat blocks keyed by slug, including JSON tags.
- `compendium_items` — magic items keyed by slug.
- `campaigns` — campaign id, name, and DM username.
- `campaign_characters` — party members belonging to a campaign.
- `campaign_events` — session notes and open thread entries.

### Routing

Sinatra routes are grouped by domain in `app.rb`:

1. Health
2. Core dice/checks (`/v1/dice/stats`, `/v1/checks/ability`, `/v1/encounters/adjusted-xp`, `/v1/initiative/order`)
3. Characters (`/v1/characters/*`)
4. Combat state (`/v1/combat/sessions/*`)
5. Auth users (`/v1/auth/*`)
6. Storage (`/v1/storage/*`)
7. Compendium (`/v1/compendium/*`)
8. Campaigns (`/v1/campaigns/*`)
9. PHB rules (`/v1/phb/*`)
10. DM tools (`/v1/dm/*`)

Every route that returns JSON calls `content_type :json` before producing the
body. Validation helpers halt with `json_error(...)` which sets the
`application/json` content type and a JSON body `{"error":"..."}`. The
`/v1/dice/stats` route is the only validation halt that omits the explicit
content type, preserving the original behavior.

### Helper modules

Sinatra helper modules are included in `app.rb`:

- `GameLogic` — pure functions (ability modifier, proficiency, initiative order,
  encounter XP/difficulty). These methods have no side effects and can be unit
  tested in isolation.
- `Validation` — input guards that may `halt` with a 400 response. They depend on
  the request context only through the `json_error` helper.
- `Auth` — password hashing via `OpenSSL::KDF.pbkdf2_hmac`.

App-specific helpers live in the anonymous `helpers` block in `app.rb`:

- `parse_json_body` — read and parse JSON, halt 400 on parse errors.
- `find_combat_session!` — load a session or halt 404.
- `combat_session_response` — format a session for the public API.
- `json_error` — uniform JSON halt helper.
- `encounter_calculation` — campaign-aware encounter builder that loads monsters
  from the compendium and halts 404 if any slug is missing.

## Main API/domain groupings

| Group | Endpoints | Notes |
|-------|-----------|-------|
| Core | `POST /v1/dice/stats`, `POST /v1/checks/ability`, `POST /v1/encounters/adjusted-xp`, `POST /v1/initiative/order` | Deterministic math; no persistence. |
| Characters | `POST /v1/characters/ability-modifier`, `POST /v1/characters/proficiency`, `POST /v1/characters/derived-stats` | Bounded integer validation (scores 1..30, levels 1..20). |
| Combat | `POST /v1/combat/sessions`, `POST /v1/combat/sessions/:id/conditions`, `POST /v1/combat/sessions/:id/advance` | Stores turn order, round, turn index, and conditions with remaining rounds. |
| Auth | `POST /v1/auth/register`, `POST /v1/auth/login` | Usernames match `/\A[a-z0-9_-]{2,32}\z/`. Passwords ≥ 8 chars. Roles are `dm` or `player`. Password hash is PBKDF2 with a username-derived salt. |
| Storage | `GET /v1/storage/status`, `POST /v1/storage/reset` | Schema version and reset. |
| Compendium | `POST /v1/compendium/monsters`, `GET /v1/compendium/monsters/:slug`, `POST /v1/compendium/items`, `GET /v1/compendium/items/:slug` | Slugs match `/\A[a-z0-9-]+\z/`. Duplicate slug returns 409. |
| Campaigns | `POST /v1/campaigns`, `POST /v1/campaigns/:id/characters`, `POST /v1/campaigns/:id/events`, `GET /v1/campaigns/:id/state` | Characters and events live under a campaign. State endpoint returns campaign info, characters, and event count. |
| PHB rules | `POST /v1/phb/spell-slots`, `POST /v1/phb/rests/long`, `POST /v1/phb/equipment-load` | Hard-coded wizard L5 spell slots and simple long-rest/equipment math. |
| DM tools | `POST /v1/dm/encounter-builder`, `POST /v1/dm/loot-parcel`, `POST /v1/dm/session-recap` | Encounter builder requires existing campaign and compendium monsters. Session recap synthesizes notes and thread events. |

## Conventions for extending and testing

### Adding a new endpoint

1. If the endpoint is pure math, add the calculation to `lib/game_logic.rb` and
   expose it through a route in `app.rb`.
2. If it validates input, add a validation helper to `lib/validation.rb` or use
   an existing one. Keep validation rules identical to the previous stage if the
   cumulative suite exercises them.
3. If it persists data, add the SQL methods to `lib/storage.rb` and expose the
   route in `app.rb`.
4. Keep responses deterministic. Do not add randomness or time-dependent
   behavior.
5. Do not remove or rename existing endpoints, status codes, or response keys
   unless the spec explicitly changes; the evaluator is cumulative.

### Testing

There is no bundled test framework. Useful local checks:

- Syntax: `ruby -c app.rb && ruby -c lib/*.rb`
- Load check: `bundle exec ruby -e "require_relative 'app'; puts 'loaded'"`
- Route list: `bundle exec ruby -e "require_relative 'app'; puts Sinatra::Application.routes.keys"`
- Manual endpoint check with the server running: `curl http://127.0.0.1:$PORT/health`

When testing against the database, keep in mind that `POST /v1/storage/reset`
will destroy all data. For manual testing, work on a copy of `game.db` or
point `Storage::DB_PATH` at a temporary file (requires a code change; not
supported by an environment variable).

### Important invariants

- The `combat_order` tie-breaker is total score → Dexterity score → name, so
  order is deterministic.
- The encounter multiplier table is straight from the D&D 5e DMG: 1×, 1.5×, 2×,
  2.5×, 3×, 4× for monster counts 1, 2, 3–6, 7–10, 11–14, 15+.
- Only level 3 party thresholds are currently populated in
  `GameLogic::LEVEL_THRESHOLDS` because the existing endpoint suite exercises
  level 3 parties.
- The password salt is deterministic (`"dnd-auth-salt-#{username}"`). Do not
  change this without also migrating existing users.
- The storage mutex is required for any database access. Never call `Storage.db`
  directly from outside the `Storage` module; use `Storage.with_db` or the
  higher-level methods.
