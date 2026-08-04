# D&D REST API codebase

## Start and verify

Start the pinned Ruby/Rails application with a port:

```sh
PORT=3000 ./run.sh
```

`run.sh` replaces its shell with Puma through `rackup`, binds to `127.0.0.1`,
and keeps the server in the foreground. From another shell, verify it with:

```sh
curl --fail http://127.0.0.1:3000/health
```

The response is `{"ok":true}`. For a static check that does not run a server:

```sh
bundle exec ruby -c app.rb
```

Run the cumulative benchmark evaluator when it is available in the surrounding
environment. Do not start a long-running server merely for static verification.

## Entry points and major modules

This is an intentionally minimal Rails API, concentrated in a few root files:

- `run.sh` is the benchmark server command.
- `config.ru` requires `app.rb` and exposes `Rails.application` to Rack.
- `app.rb` defines the Rails application, all controllers/routes, shared domain
  helpers, and SQLite storage. It loads only the Rails controller stack; Active
  Record and Rails migrations are deliberately not used.
- `Gemfile` and `Gemfile.lock` pin the Rails, Rack, and Puma runtime.

Within `app.rb`, `ApplicationController` contains shared request parsing,
integer coercion, and the intentionally non-trimming non-empty-string check
used by controllers. `GameStorage` owns persistence. `EncounterMath`,
`CombatSessionState`, `AuthCredentials`, `PlayAuthentication`, and
`PlayCampaignEvents` keep shared non-routing rules focused and reusable.

## Routing and persistence

`DndApi.routes` at the end of `app.rb` is the authoritative route list.
Controllers inherit from `ApplicationController`, which turns malformed JSON
or invalid request parameters into the existing common error response. Keep
route declaration order explicit when adding overlapping paths.

`GameStorage` uses one SQLite connection and a process-local mutex. Its
`game.db` file sits beside `app.rb` and persists users, combat sessions,
compendium records, campaign records, and campaign-play documents/events across
server restarts. Schema setup runs during boot. All database work belongs inside
`GameStorage.synchronize` so the shared connection is safe for Puma threads.
`POST /v1/storage/reset` is intentionally the only API operation that clears
persisted state.

## API/domain groupings

- Core rules: health, dice statistics, ability checks, initiative ordering,
  character calculations, and adjusted encounter XP.
- Combat and auth: persistent combat sessions, conditions, turn advancement,
  and SQLite-backed registration/login.
- Campaign play (`/v1/play`): bearer actor resolution; DM/player lobby
  membership; deterministic player/GM turns; nudges, actions, resolutions, and
  narrations; role-specific context; and the campaign document. Campaign-play
  event sequence allocation and the shared latest-five-event projection live in
  `PlayCampaignEvents`. Character endpoints cover hit points, death saves,
  ownership, build choices, level progression, and deterministic skill checks.
- Compendium and campaign management (`/v1/compendium`, `/v1/campaigns`):
  monsters/items; campaign characters/events/state; inventory/equipment;
  crafting; quests; factions/NPCs; scheduled sessions/attendance; audit/export;
  and deterministic analytics.
- PHB utilities: spell slots, long-rest recovery, and equipment load.
- DM tools: encounter building, deterministic tier-one loot, and the latest
  campaign-event recap. `EncounterMath` is shared with core encounters so XP
  behavior stays in lockstep.

## Safe extension and testing conventions

The benchmark is cumulative: preserve existing routes, status codes, response
shapes, validation, persistence semantics, and ordering. Keep controller-only
request handling in its controller; extract only genuinely shared logic into a
small focused module. Use parameterized SQL and keep database work under the
storage mutex. Add schema changes to `GameStorage.initialize_schema!` and make
sure `reset!` drops every new table.

Prefer deterministic values and ordering. Initiative order and many campaign
collections intentionally use explicit sort keys or insertion order. Keep
campaign-play event allocation and its last-five projection within the same
storage lock. Exercise new behavior through HTTP after resetting storage, then
run the cumulative suite to catch cross-domain regressions. Reuse the base
controller's `present_string?` validation as-is: it intentionally accepts
whitespace-only strings, so tightening it would be a contract change.
