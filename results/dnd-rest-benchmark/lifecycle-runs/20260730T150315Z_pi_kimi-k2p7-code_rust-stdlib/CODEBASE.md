# dndrest — Codebase Guide

A small, deterministic HTTP service for D&D 5e helper calculations, combat
tracking, campaign management, and play-by-post turn handling. It uses Rust
1.97.0 and the standard library only: no external crates, no serde, no HTTP
framework. HTTP is implemented directly on `std::net::TcpListener` /
`TcpStream`, and JSON is built and parsed with string manipulation.

## Quick start

```bash
PORT=8080 ./run.sh
```

`run.sh` removes the local database (`game.db`), builds the server with
`cargo run`, and starts it in the foreground. The server binds to `127.0.0.1`
on the port given by the `PORT` environment variable (default `8080`). The
database path can be overridden with `DB_PATH`.

Verify the server is listening:

```bash
curl http://127.0.0.1:8080/health
# => {"ok":true}
```

Reset the database and in-memory caches (registered user accounts are
preserved so the authenticated play surface remains usable):

```bash
curl -X POST http://127.0.0.1:8080/v1/storage/reset
# => {"ok":true,"schema_version":1}
```

## Entry point and module layout

- `Cargo.toml` — package metadata. No external dependencies.
- `run.sh` — builds and runs the server with `cargo run`.
- `src/main.rs` — entry point, module declarations, global state, and the
  central request dispatcher. Routing is split into `dispatch_get`,
  `dispatch_post`, and `dispatch_put` helpers.
- `src/domain.rs` — core domain types (`Combatant`, `CombatSession`, `User`,
  `Condition`) and the global in-memory caches (`SESSIONS`, `USERS`).
- `src/http.rs` — minimal HTTP/1.1 request parsing and response writing.
- `src/json.rs` — hand-rolled JSON parsing helpers used by every handler.
- `src/store.rs` — SQLite persistence via the `sqlite3` CLI tool, plus all
  existence and lookup helpers used by the domain modules.
- `src/auth.rs` — registration, login, and bearer-token verification.
- `src/combat.rs` — combat sessions, initiative, conditions, and turn
  advancement.
- `src/campaigns.rs` — campaigns, player characters, events, scheduled
  sessions, attendance, audit, and export.
- `src/compendium.rs` — monsters and items stored in SQLite.
- `src/dice.rs` — dice statistics and ability checks.
- `src/encounters.rs` — encounter difficulty / XP calculations.
- `src/phb.rs` — Player's Handbook rules: modifiers, proficiency, spell slots,
  rests, and equipment load.
- `src/dm_tools.rs` — DM-facing helpers: encounter builder, loot parcel, and
  session recap.
- `src/quests.rs` — quest creation, progress tracking, and summaries.
- `src/npcs_factions.rs` — factions and NPCs with relationship summaries.
- `src/inventory.rs` — campaign inventory and character equipment assignments.
- `src/downtime.rs` — downtime crafting projects.
- `src/analytics.rs` — campaign readiness score and risk reports.
- `src/play.rs` — authenticated play-by-post campaigns: membership, turn
  queue, narrations, actions, resolutions, nudges, and the role-filtered
  campaign document.

## State, persistence, and routing

### In-memory state

Two global `LazyLock<Mutex<HashMap<...>>>` caches live in `src/domain.rs`:

- `SESSIONS` — `HashMap<String, CombatSession>` for active combat encounters.
- `USERS` — `HashMap<String, User>` for registered accounts.

These caches are locked at the start of every request in `dispatch_request` and
held until the response is written. This serializes requests and keeps the
in-memory view consistent with the database between `save_storage` calls.

### Persistence

Persistence is implemented in `src/store.rs` by invoking the `sqlite3` command
line tool. The schema is created by `init_db()` on startup if it does not exist.

Mutable state is saved with a simple “delete all, then re-insert all” strategy:
`save_storage` deletes every row from `users`, `combat_sessions`, `combatants`,
and `conditions`, then re-inserts the current contents of `SESSIONS` and
`USERS`. This is intentionally simple and deterministic. The database is loaded
once at startup by `load_storage`.

Other tables (`campaigns`, `characters`, `events`, `monsters`, `items`,
`monster_tags`, `quests`, `quest_milestones`, `factions`, `npcs`,
`campaign_inventory`, `character_equipment`, `crafting_projects`,
`campaign_sessions`, `session_agenda`, `session_attendance`, `play_campaigns`,
`play_campaign_members`, `play_narrations`, `play_campaign_documents`) are
written directly by their respective handlers and do not go through the
in-memory caches. The storage reset endpoint preserves the `users` cache so
that authenticated play sessions remain identifiable across resets.

### Request routing

`src/main.rs` reads the request line, extracts the body, acquires both global
locks, and dispatches to the appropriate handler. The dispatcher uses a
method-based split (`dispatch_get`, `dispatch_post`, `dispatch_put`) plus
helper parsers for dynamic path segments:

- `combat::parse_combat_path` for `/v1/combat/sessions/{id}/...`
- `campaigns::parse_campaign_path` for `/v1/campaigns/{id}/...`
- `campaigns::parse_campaign_session_path` for session attendance paths.
- `quests::parse_campaign_quest_path` and `parse_quest_progress_path`.
- `inventory::parse_campaign_inventory_path`, `parse_inventory_summary_path`,
  and `parse_character_equipment_path`.
- `downtime::parse_crafting_path` and `parse_crafting_advance_path`.
- `play::parse_play_campaign_path` for `/v1/play/campaigns/{id}/...`.
- `strip_prefix` for `/v1/compendium/monsters/{slug}` and items.

Authorization is enforced by `require_auth` in `src/main.rs`, which checks the
`Authorization: Bearer session-{username}` header and verifies the registered
role (`dm`, `player`, or any role). After a handler that mutates `SESSIONS` or
`USERS` succeeds, the dispatcher calls `save_storage` to persist the change.

### JSON parsing

`src/json.rs` provides a small, serde-free parser. It scans for `"key"`, finds
the following `:`, and extracts the next primitive value or bracketed/array
block. It supports nested objects and arrays by tracking `{ }` / `[ ]` depth,
but does not handle escaped quotes inside string values. All inputs are
expected to be simple JSON objects produced by the test harness.

## API / domain groupings

| Area | Endpoints | Module |
|------|-----------|--------|
| Health & storage | `GET /health`, `GET /v1/storage/status`, `POST /v1/storage/reset` | `src/main.rs`, `src/store.rs` |
| Auth | `POST /v1/auth/register`, `POST /v1/auth/login` | `src/auth.rs` |
| Dice | `POST /v1/dice/stats`, `POST /v1/checks/ability` | `src/dice.rs` |
| Initiative | `POST /v1/initiative/order` | `src/combat.rs` |
| Characters / PHB | `POST /v1/characters/{ability-modifier,proficiency,derived-stats}`, `POST /v1/phb/{spell-slots,rests/long,equipment-load}` | `src/phb.rs` |
| Encounters | `POST /v1/encounters/adjusted-xp` | `src/encounters.rs` |
| Combat | `POST /v1/combat/sessions`, `POST /v1/combat/sessions/{id}/conditions`, `POST /v1/combat/sessions/{id}/advance` | `src/combat.rs` |
| Compendium | `POST /v1/compendium/{monsters,items}`, `GET /v1/compendium/{monsters,items}/{slug}` | `src/compendium.rs` |
| Campaigns | `POST /v1/campaigns`, `POST /v1/campaigns/{id}/characters`, `POST /v1/campaigns/{id}/events`, `POST /v1/campaigns/{id}/sessions`, `POST /v1/campaigns/{id}/sessions/{session_id}/attendance`, `GET /v1/campaigns/{id}/state`, `GET /v1/campaigns/{id}/sessions/next`, `GET /v1/campaigns/{id}/audit`, `GET /v1/campaigns/{id}/export` | `src/campaigns.rs` |
| Quests | `POST /v1/campaigns/{id}/quests`, `POST /v1/campaigns/{id}/quests/{quest_id}/progress`, `GET /v1/campaigns/{id}/quests/summary` | `src/quests.rs` |
| NPCs & factions | `POST /v1/campaigns/{id}/factions`, `POST /v1/campaigns/{id}/npcs`, `GET /v1/campaigns/{id}/relationships` | `src/npcs_factions.rs` |
| Inventory | `POST /v1/campaigns/{id}/inventory`, `POST /v1/campaigns/{id}/characters/{character_id}/equipment`, `GET /v1/campaigns/{id}/inventory/summary` | `src/inventory.rs` |
| Downtime | `POST /v1/campaigns/{id}/downtime/crafting`, `POST /v1/campaigns/{id}/downtime/crafting/{project_id}/advance` | `src/downtime.rs` |
| Analytics | `GET /v1/campaigns/{id}/analytics/summary`, `POST /v1/campaigns/{id}/analytics/risk-report` | `src/analytics.rs` |
| DM tools | `POST /v1/dm/{encounter-builder,loot-parcel,session-recap}` | `src/dm_tools.rs` |
| Play campaigns | `POST /v1/play/campaigns`, `POST /v1/play/campaigns/{id}/members`, `POST /v1/play/campaigns/{id}/start`, `POST /v1/play/campaigns/{id}/narrations`, `POST /v1/play/campaigns/{id}/actions`, `POST /v1/play/campaigns/{id}/resolutions`, `POST /v1/play/campaigns/{id}/turn/nudge`, `GET /v1/play/campaigns/{id}/turn`, `GET /v1/play/campaigns/{id}/gm/status`, `GET /v1/play/campaigns/{id}/my-turn`, `GET /v1/play/campaigns/{id}/document`, `PUT /v1/play/campaigns/{id}/document` | `src/play.rs` |

## Extending and testing the codebase

### Adding a new endpoint

1. Choose the relevant module (or create a new one in `src/` and declare it in
   `src/main.rs`).
2. Implement a pure function that takes the request body string (and optionally
   the locked `sessions` / `users` maps or path parameters) and returns
   `Option<String>` or a module error enum.
3. Add the route to the appropriate dispatcher in `src/main.rs`. If the route
   mutates the in-memory caches, call `save_storage` after the handler succeeds.
   If the route requires authorization, use `require_auth` with the appropriate
   `AuthRequirement`.
4. Keep JSON field order and response shape exactly as expected by the test
   suite; the string-building helpers in `src/json.rs` are used for this.

### String safety

Any user-supplied string embedded in a SQL statement must pass through
`store::sql_escape`. JSON output must pass through `json::escape_json`. Do not
change these functions unless the test suite explicitly requires different
escaping rules.

### Testing locally

Build and run with a temporary database to avoid mutating `game.db`:

```bash
PORT=18080 DB_PATH=./test.db ./run.sh &
curl -X POST http://127.0.0.1:18080/v1/storage/reset
# ... exercise endpoints ...
kill %1
rm -f ./test.db
```

`cargo build` and `cargo run` are the supported workflows. The project has no
external dependencies, so builds are fast and deterministic. There is no test
suite inside the crate; the evaluator is an external HTTP client that exercises
the running server.

### Determinism

Keep behavior deterministic: use explicit sorting (e.g., combatant ordering and
condition target ordering), fixed lookup tables, and no randomness. The test
suite compares exact response bodies and relies on consistent ordering.
