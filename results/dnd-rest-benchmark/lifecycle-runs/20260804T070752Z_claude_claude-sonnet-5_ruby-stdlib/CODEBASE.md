# D&D REST Engine (Ruby stdlib)

A dependency-free HTTP JSON API for D&D 5e session tooling: dice/ability
math, initiative-tracked combat, an auth/user store, a monster+item
compendium, campaign/DM tooling, and a turn-based "campaign play" surface
(join a campaign, take turns, narrate, resolve actions). Built entirely on
the Ruby standard library — no Sinatra, Rails, Rack, or gems.

## Start and verify

```sh
./run.sh                # starts the server in the foreground on 127.0.0.1:$PORT (default 8080)
PORT=8099 ./run.sh       # or override the port
```

Requires the `sqlite3` CLI binary on `PATH` (used as the storage engine;
see "State, persistence, and request routing" below).

Verify it's up:

```sh
curl -s http://127.0.0.1:8080/health
# => {"ok":true}
```

Run the full behavioral test suite (requires the `dndeval` evaluator binary;
not part of this repo):

```sh
dndeval run --suite campaign-document --base-url http://127.0.0.1:8080
```

`campaign-document` is the cumulative suite as of this checkpoint — it
exercises every route below. Later checkpoints add suites with higher route
counts that still include all of these cases.

## Entry point and module map

```
server.rb                    # entry point: reset db file, init schema, start TCPServer, accept loop
lib/errors.rb                # HttpError (status + message)
lib/database.rb              # Database: sqlite3-CLI wrapper, schema DDL and migrations
lib/game_rules.rb            # GameRules: pure SRD math (XP/CR, difficulty, modifiers)
lib/http_server.rb           # HttpServer: request parsing, routing tables, response writing
lib/handlers/core.rb         # Handlers::Core: dice, ability checks, XP, initiative order, /health
lib/handlers/characters.rb   # Handlers::Characters: ability modifier, proficiency, derived stats
lib/handlers/combat.rb       # Handlers::Combat: combat sessions, conditions, turn advancement
lib/handlers/auth.rb         # Handlers::Auth: register/login/authenticate (PBKDF2 password hashing)
lib/handlers/storage.rb      # Handlers::Storage: storage status/reset
lib/handlers/compendium.rb   # Handlers::Compendium: monsters, items
lib/handlers/campaigns.rb    # Handlers::Campaigns: campaigns, characters, events, state
lib/handlers/phb.rb          # Handlers::Phb: spell slots, long rest, equipment load
lib/handlers/dm_tools.rb     # Handlers::DmTools: encounter builder, loot parcel, session recap
lib/handlers/quests.rb       # Handlers::Quests: quests, milestone progress, per-campaign summary
lib/handlers/npcs.rb         # Handlers::Npcs: factions, NPCs, relationship counts
lib/handlers/inventory.rb    # Handlers::Inventory: party inventory, per-character equipment
lib/handlers/downtime.rb     # Handlers::Downtime: crafting projects (advance days, complete -> inventory)
lib/handlers/sessions.rb     # Handlers::Sessions: session scheduling, attendance, next-session lookup
lib/handlers/audit.rb        # Handlers::Audit: per-campaign entity counts (audit/export)
lib/handlers/analytics.rb    # Handlers::Analytics: readiness score, risk report
lib/handlers/play.rb         # Handlers::Play: authenticated campaign-play (turns, narration, document)
```

`server.rb` only wires things together; it has no request-handling logic of
its own. Every handler module exposes `module_function` methods that take
the parsed JSON body (plus path parameters for parameterized routes) and
return `[http_status, response_hash]`. `Handlers::Play` methods additionally
take the authenticated `actor` as their first argument (see "Request
routing" below).

## State, persistence, and request routing

**Persistence.** All state lives in `game.db`, a SQLite file at the project
root. There is no bundled `sqlite3` gem (stdlib-only constraint), so
`Database` (`lib/database.rb`) shells out to the `sqlite3` CLI via `Open3`
for every query: DDL/writes go through `Database.exec`, reads go through
`Database.query`, which parses `.mode json` output into an array of row
hashes. `Database.escape`/`Database.int` build ad hoc SQL string/integer
literals for interpolation — there are no prepared statements, so every
call site is responsible for escaping. `Database.init_schema` is
idempotent (`CREATE TABLE IF NOT EXISTS`) and also runs a handful of
`migrate_*` steps that `ALTER TABLE ... ADD COLUMN` for columns added after
a table's original checkpoint, since `IF NOT EXISTS` doesn't alter an
already-existing table. `Database.reset_schema` (used by
`POST /v1/storage/reset`) drops and recreates every table except `users`
and `play_documents`.

Combat session state (turn order, round, per-combatant status conditions)
is stored as JSON-encoded columns (`order_json`, `conditions_json`) and
rehydrated into plain hashes by `Handlers::Combat.load_session` /
`save_session` on each request — there is no in-memory session cache. The
same JSON-column pattern is used for quest milestones
(`campaign_quests.milestones_json`/`completed_json`), session agendas and
attendance (`campaign_sessions.agenda_json`/`present_json`/`absent_json`),
and combatant conditions.

**Request routing.** `HttpServer` (`lib/http_server.rb`) implements a
minimal single-threaded HTTP/1.1 server directly on `TCPServer`/`TCPSocket`:
`read_request` parses the request line, headers, and a
`Content-Length`-delimited body; `write_response` always emits
`Connection: close` (no keep-alive, one request per connection).

Routing is layered in `HttpServer.handle_connection`:
1. `ROUTES` — an exact `[method, path] => handler` hash for unauthenticated
   routes with no path parameters.
2. `PARAMETERIZED_ROUTES` — an ordered list of `[method, regex, handler]`
   for unauthenticated routes like `/v1/campaigns/:id/state`, checked after
   `ROUTES` misses. Each regex capture group becomes a positional handler
   argument, in order.
3. `PROTECTED_ROUTES` / `PROTECTED_PARAMETERIZED_ROUTES` — the same
   exact/regex split, but only checked once both unauthenticated tables
   miss. Every route under `/v1/play/...` lives here. Before a protected
   handler runs, `Handlers::Auth.authenticate(headers)` resolves the
   `Authorization: Bearer session-<username>` header into an `actor`
   (`{username:, role:}`) hash and passes it as the handler's first
   argument, ahead of any path-parameter captures.

`HttpServer.handle_connection` ties it together: parse request → parse JSON
body (must be a JSON object, or absent) → resolve (unauthenticated, then
protected) → call handler → write response. `HttpError` raised anywhere in
a handler (including `Auth.authenticate`) is caught centrally and turned
into `{"error": message}` with the error's status code; any other
`StandardError` becomes a 400 with the exception message (handlers rely on
this instead of rescuing validation errors themselves).

## API/domain groupings

- **Core mechanics** (`Handlers::Core`) — `POST /v1/dice/stats`,
  `POST /v1/checks/ability`, `POST /v1/encounters/adjusted-xp`,
  `POST /v1/initiative/order`, plus `GET /health`.
- **Characters** (`Handlers::Characters`) — `POST /v1/characters/ability-modifier`,
  `POST /v1/characters/proficiency`, `POST /v1/characters/derived-stats`.
- **Combat** (`Handlers::Combat`) — `POST /v1/combat/sessions`,
  `POST /v1/combat/sessions/:id/conditions`,
  `POST /v1/combat/sessions/:id/advance`.
- **Auth** (`Handlers::Auth`) — `POST /v1/auth/register`, `POST /v1/auth/login`.
  (`authenticate` is not routed directly; it's the gate in front of every
  `/v1/play/...` route.)
- **Storage** (`Handlers::Storage`) — `GET /v1/storage/status`,
  `POST /v1/storage/reset`.
- **Compendium** (`Handlers::Compendium`) — `POST /v1/compendium/monsters`,
  `GET /v1/compendium/monsters/:slug`, `POST /v1/compendium/items`,
  `GET /v1/compendium/items/:slug`.
- **Campaigns** (`Handlers::Campaigns`) — `POST /v1/campaigns`,
  `POST /v1/campaigns/:id/characters`, `POST /v1/campaigns/:id/events`,
  `GET /v1/campaigns/:id/state`. `find_campaign` is reused by nearly every
  other campaign-scoped module below (each raises 404 up front if the
  campaign doesn't exist).
- **PHB rules** (`Handlers::Phb`) — `POST /v1/phb/spell-slots`,
  `POST /v1/phb/rests/long`, `POST /v1/phb/equipment-load`.
- **DM tools** (`Handlers::DmTools`) — `POST /v1/dm/encounter-builder`,
  `POST /v1/dm/loot-parcel`, `POST /v1/dm/session-recap`. These compose
  `Handlers::Campaigns.find_campaign`, the compendium tables, and
  `GameRules` encounter math; every DM tool requires an existing
  `campaign_id`.
- **Quests** (`Handlers::Quests`) — `POST /v1/campaigns/:id/quests`,
  `POST /v1/campaigns/:id/quests/:quest_id/progress`,
  `GET /v1/campaigns/:id/quests/summary`.
- **NPCs & factions** (`Handlers::Npcs`) — `POST /v1/campaigns/:id/factions`,
  `POST /v1/campaigns/:id/npcs`, `GET /v1/campaigns/:id/relationships`.
- **Inventory** (`Handlers::Inventory`) — `POST /v1/campaigns/:id/inventory`,
  `GET /v1/campaigns/:id/inventory/summary`,
  `POST /v1/campaigns/:id/characters/:character_id/equipment`.
- **Downtime** (`Handlers::Downtime`) — `POST /v1/campaigns/:id/downtime/crafting`,
  `POST /v1/campaigns/:id/downtime/crafting/:project_id/advance`. Completing
  a project (`days_completed` reaches `days_required`) adds one unit of the
  crafted item to the campaign's `party`-owned inventory via
  `Handlers::Inventory`'s tables.
- **Sessions** (`Handlers::Sessions`) — `POST /v1/campaigns/:id/sessions`,
  `POST /v1/campaigns/:id/sessions/:session_id/attendance`,
  `GET /v1/campaigns/:id/sessions/next`.
- **Audit & export** (`Handlers::Audit`) — `GET /v1/campaigns/:id/audit`,
  `GET /v1/campaigns/:id/export`. Pure read-side entity counts; no
  additional state of its own.
- **Analytics** (`Handlers::Analytics`) — `GET /v1/campaigns/:id/analytics/summary`,
  `POST /v1/campaigns/:id/analytics/risk-report`. Derives a deterministic
  `readiness_score` and `risk_level` from counts already tracked by quests,
  npcs/factions, sessions, and inventory — no analytics-specific tables.
- **Campaign play** (`Handlers::Play`, all under `/v1/play/...`, all
  authenticated) — `POST /v1/play/campaigns` (dm only),
  `POST /v1/play/campaigns/:id/members` (player joins, player only),
  `POST /v1/play/campaigns/:id/start` (owning dm only, needs 2+ members),
  `POST /v1/play/campaigns/:id/narrations` (owning dm only),
  `POST /v1/play/campaigns/:id/actions` (the current-turn party member only),
  `POST /v1/play/campaigns/:id/resolutions` (owning dm only, on the dm's turn),
  `GET /v1/play/campaigns/:id/turn` (owner or party member),
  `POST /v1/play/campaigns/:id/turn/nudge` (owning dm only),
  `GET /v1/play/campaigns/:id/my-turn` (party member only),
  `GET /v1/play/campaigns/:id/gm/status` (owning dm only),
  `PUT`/`GET /v1/play/campaigns/:id/document` (owner sees `story` +
  `dm_notes`; a party member sees `story` only). Turn order alternates
  party-member action → dm resolution; `next_party_member` advances to
  whoever joined after the last player to act, wrapping to the first
  member. `narrations`, `actions`, and `resolutions` all append to the same
  per-campaign `play_events` log via `Handlers::Play.record_event`, which
  assigns each event the next 1-based `sequence` number for that campaign.

Shared game math (CR→XP table, encounter multiplier, difficulty bands,
ability modifier, proficiency bonus) lives in `GameRules`
(`lib/game_rules.rb`) rather than being duplicated per handler —
`Handlers::Core.adjusted_xp` and `Handlers::DmTools.encounter_builder` both
call `GameRules.party_thresholds` and `GameRules.difficulty_for` for their
identical difficulty-banding logic.

## Conventions for extending and testing

- **Adding an unauthenticated route with no path parameter:** add a handler
  method to the appropriate `Handlers::*` module (or a new module under
  `lib/handlers/`), then register `[METHOD, path] => Module.method(:name)`
  in `HttpServer::ROUTES`.
- **Adding an unauthenticated route with a path parameter:** the handler's
  first argument(s) are the captured path segments in order, last is the
  body; append `[METHOD, regex, Module.method(:name)]` to
  `HttpServer::PARAMETERIZED_ROUTES`.
- **Adding an authenticated route:** same shape, but register in
  `HttpServer::PROTECTED_ROUTES` / `PROTECTED_PARAMETERIZED_ROUTES`
  instead; the handler's first argument is always the authenticated
  `actor` (`{username:, role:}` from `Handlers::Auth.authenticate`),
  followed by any path captures, then the body. Do the role/ownership check
  (e.g. "only the owning dm") inside the handler — `authenticate` only
  proves the bearer token names a well-formed username, not that it's
  authorized for this action. `Handlers::Play` centralizes the recurring
  "is this actor the owning dm" check as `owner?(campaign, actor)` (boolean,
  for routes that vary response shape by role) and `require_owner!(campaign,
  actor, message)` (raises 403, for routes that are dm-owner-only) — reuse
  these instead of re-deriving `campaign['owner'] == actor[:username]`.
- **Validation:** handlers validate their own input inline and raise
  `HttpError.new(status, message)` on failure — do not rescue validation
  errors locally, the central `rescue HttpError` in
  `HttpServer.handle_connection` formats the response.
- **Persistence:** always go through `Database.exec`/`Database.query`, and
  always pass user-controlled values through `Database.escape`/`Database.int`
  when building SQL — there are no prepared statements. If a table gains a
  column after its original checkpoint, add an idempotent `migrate_*` step
  (see `Database.migrate_play_campaigns` for the pattern) rather than
  editing the original `CREATE TABLE`, so existing `game.db` files upgrade
  in place.
- **Determinism:** handlers must stay deterministic (no randomness in
  responses) except where the domain explicitly calls for it (e.g.
  `SecureRandom` for password salts in `Handlers::Auth`, which never affects
  response *shape*, only stored data).
- **Testing:** there is no unit test harness in this repo; correctness is
  verified behaviorally with the external `dndeval` tool against a running
  server (see "Start and verify" above). Point it at a fresh `game.db` (or
  call `POST /v1/storage/reset` first) to avoid cross-run state bleed. Note
  `reset_schema` does not drop `users` or `play_documents`, so registered
  accounts and campaign documents survive a storage reset.
