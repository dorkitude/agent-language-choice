# D&D REST API codebase

This is a deterministic JSON API for D&D campaign management and turn-based
campaign play, built with Ruby 4.0.5, Sinatra 4.2.1, Rack 3.2.6, and Puma
8.0.2. Exact dependency pins are in `Gemfile` and `Gemfile.lock`; route
contracts are the primary unit of public behavior.

## Start and verify

Install the pinned gems with `bundle install`, then start the foreground server:

```sh
PORT=4567 ./run.sh
```

`run.sh` deletes the prior local `game.db`, then starts Sinatra in the
foreground on `127.0.0.1` using the required `PORT` environment variable.
In another terminal, verify readiness with:

```sh
curl -i http://127.0.0.1:4567/health
```

The successful response is JSON `{"ok":true}`. Use `bundle exec ruby -c app.rb`
for a fast syntax check. Integration tests should start a fresh server,
exercise HTTP contracts rather than helpers directly, and reset storage between
stateful scenarios.

## Entry point and modules

- `run.sh` is the operational entry point used by the benchmark and executes
  `app.rb` in the foreground.
- `app.rb` contains `GameStorage`, the narrow SQLite command wrapper and
  schema owner, and `DndApi`, the Sinatra application. Its helpers hold
  validation, response shaping, authentication, and deterministic state
  reconstruction; its routes define the HTTP contract. In particular,
  `encounter_turn_state!` is the shared read path for routes that need the
  persisted encounter round/index state. It calls `DndApi.run!` only when
  executed directly, so it can also be required by tests.
- `Gemfile` pins Sinatra 4.2.1, Rack 3.2.6, Rackup 2.3.1, and Puma 8.0.2.
- `game.db` is the runtime SQLite database, created beside `app.rb`; it is not
  a source file and is initialized on application boot.

## State, persistence, and routing

`GameStorage` invokes the system `sqlite3` executable through one internal
runner and serializes values into SQL literals with its local `quote` helper.
Schema creation is idempotent and records schema version 1. The storage reset
endpoint drops and recreates all tables, so tests can rely on it for a clean
state.

`DndApi` binds only to loopback, sets every response to JSON, and protects
database reads and writes with `DATABASE_MUTEX`. The mutex is an important
process-local invariant: operations that check then insert, or load then save a
combat session, must remain inside the same synchronized block. Combat session
state is stored as a JSON payload; users, compendium data, campaign records,
and campaign-play state use relational tables. Play-party queries deliberately
order by SQLite `rowid`, because join order defines turn rotation. Encounter
turn indices are normalized against the current order on reads; routes that
advance or delay a turn then persist the resulting state.

Routes parse JSON with `json_body`, send established JSON error bodies through
`halt_json`, and use validation/response helpers to keep equivalent contracts
consistent. The global `error` and `not_found` handlers deliberately return the
existing generic JSON responses.

## API/domain groupings

- Infrastructure: `/health` and `/v1/storage/*`.
- Identity: `/v1/auth/*` registration and password-verified login.
- Campaign play: `/v1/play/campaigns*` provides DM-owned lobbies, membership,
  character ownership, creation choices, level progression, skill checks,
  health/death saves, starting, documents, turn queries and nudges, narration,
  player actions, and GM resolutions.
- Compendium and campaign records: `/v1/compendium/*` and `/v1/campaigns/*`.
  Campaign records cover characters, events, scheduling and attendance,
  inventory/equipment/crafting, factions/NPCs, quests, audit/export, and
  analytics.
- Rules calculations: dice, checks, character stats, encounters, initiative,
  and `/v1/phb/*` rules helpers.
- DM tools: `/v1/dm/*` encounter, loot, and recap helpers backed by campaign
  state where required.
- Combat lifecycle: `/v1/combat/sessions*`, including initiative ordering,
  condition duration, turns, and persisted session state.

## Safe extension and testing conventions

Preserve route paths, success bodies, status codes, validation order, error
messages, and query ordering: benchmark clients treat those as public API
behavior. Add validation through existing helpers only when it produces the
exact intended contract, and keep database mutations synchronized. Use
parameter values only through `GameStorage.quote` when constructing SQL.

When adding persisted behavior, extend both `initialize_schema!` and `reset!`,
and make boot initialization safe for existing databases. Keep outputs
deterministic—do not add time, random values, or unordered query results unless
the API explicitly requires them. Reuse response and state-reconstruction
helpers where the same data shape is emitted by multiple routes, but do not
move authorization or validation unless their ordering and error body stay
identical. Test both successful requests and invalid input through HTTP.
