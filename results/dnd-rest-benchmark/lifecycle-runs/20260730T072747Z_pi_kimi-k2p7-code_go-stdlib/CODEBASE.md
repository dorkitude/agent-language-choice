# D&D REST Service — Codebase Guide

A small Go 1.26.5 HTTP service that exposes deterministic D&D utility endpoints
for dice, character stats, combat initiative, encounters, compendium entries,
campaigns, play-by-post turn management, and DM helpers. It uses only the Go
standard library (`net/http`, `encoding/json`) and the `sqlite3` command-line
tool for persistence.

## Start and verify the server

The project is started with the included shell wrapper:

```bash
./run.sh
```

`run.sh` removes the previous SQLite file, builds the binary (`go build -o dndrest .`),
and then runs it in the foreground. The server listens on `127.0.0.1` and uses
the `PORT` environment variable, defaulting to `8080`:

```bash
PORT=8080 ./run.sh
```

A quick health check:

```bash
curl http://127.0.0.1:8080/health
```

Expected response:

```json
{"ok": true}
```

For a deterministic test run, first reset storage:

```bash
curl -X POST http://127.0.0.1:8080/v1/storage/reset
```

## Entry point and major files

| File | Responsibility |
|------|--------------|
| `main.go` | Entry point: initializes the database, registers all routes, and starts `http.ListenAndServe`. |
| `run.sh` | Build and run script required by the harness. |
| `go.mod` | Module declaration (`dndrest`) with Go version `1.26.5`. |
| `db.go` | SQLite schema (`schemaSQL`), `dbExec`/`dbQuery` helpers, `dbMu` lock, `writeJSON`/`writeError`, `queryExists`/`queryRows`, `tableHasColumn`, and the storage/health handlers. |
| `auth.go` | User registration, login, SHA-256 password hashing, `loadUserByUsername`, and the session bearer helpers. |
| `dice.go` | Dice expression parsing and statistics (`POST /v1/dice/stats`). |
| `checks.go` | Ability check resolution (`POST /v1/checks/ability`). |
| `initiative.go` | Initiative ordering with deterministic tie-breakers (`POST /v1/initiative/order`). |
| `encounters.go` | Encounter XP math, thresholds, and the standalone adjusted-XP endpoint (`POST /v1/encounters/adjusted-xp`). |
| `characters.go` | Ability modifiers, proficiency bonus, and derived stats (`POST /v1/characters/*`). |
| `combat.go` | Combat session creation, condition tracking, and turn advancement (`POST /v1/combat/sessions/*`). |
| `compendium.go` | Monster and item CRUD (`POST \| GET /v1/compendium/*`). |
| `campaigns.go` | Core campaigns, characters, events, aggregate state, audit, and export (`POST \| GET /v1/campaigns/*`). |
| `play.go` | Authenticated play campaign surface: shared types, authorization helpers, campaign creation/join/start, turn queue, narrations, actions, resolutions, nudges, documents, and GM/player status (`/v1/play/campaigns/*`). |
| `play_turns.go` | Exploration turn actions: travel and rest turns (`POST /v1/play/campaigns/{id}/turn/travel`, `POST /v1/play/campaigns/{id}/turn/rest`). |
| `play_scenes.go` | Scene management: create, enter, close, and read the current scene (`/v1/play/campaigns/{id}/scenes/*`). |
| `play_locations.go` | Deterministic location graph: create locations and connections, list valid travel destinations (`/v1/play/campaigns/{id}/locations/*`). |
| `play_encounters.go` | Campaign-bound encounter creation (`POST /v1/play/campaigns/{id}/encounters`). |
| `play_characters.go` | Bound character health, ownership, death saves, build, level-up, and skill checks (`/v1/play/campaigns/{id}/characters/{char_id}/*`). |
| `monsters.go` | Encounter monster roster, combatant binding, initiative, damage/healing, delay/ready, and combat actions (`/v1/play/campaigns/{id}/encounters/{enc_id}/*`). |
| `encounter_conditions.go` | Encounter condition tracking (`POST /v1/play/campaigns/{id}/encounters/{enc_id}/conditions`, `GET /v1/play/campaigns/{id}/encounters/{enc_id}/status`). |
| `encounter_rewards.go` | Encounter rewards, close, and end-of-combat transition (`/v1/play/campaigns/{id}/encounters/{enc_id}/rewards`, `.../close`, `.../end`). |
| `analytics.go` | Campaign analytics summary and maintenance risk report (`GET /v1/campaigns/{id}/analytics/*`). |
| `quests.go` | Campaign quest tracking with milestones (`/v1/campaigns/{id}/quests/*`). |
| `npcs_factions.go` | Factions and NPCs with relationship summaries (`/v1/campaigns/{id}/factions/*`, `/v1/campaigns/{id}/npcs/*`). |
| `inventory.go` | Party inventory and per-character equipment (`/v1/campaigns/{id}/inventory/*`, `/v1/campaigns/{id}/characters/{id}/equipment`). |
| `crafting.go` | Downtime crafting projects (`/v1/campaigns/{id}/downtime/crafting/*`). |
| `sessions.go` | Campaign session scheduling and attendance (`/v1/campaigns/{id}/sessions/*`). |
| `phb.go` | Spell slots, long rest, and equipment load rules (`POST /v1/phb/*`). |
| `dm.go` | DM tools that combine campaign/compendium data: encounter builder, loot parcel, and session recap (`POST /v1/dm/*`). |

## State, persistence, and routing design

### Persistence

- All durable state lives in a single SQLite file, `game.db`, in the working
  directory.
- The application uses the `sqlite3` command-line tool via `os/exec`. It does
  **not** use a Go SQLite driver or connection pool.
- Because every query spawns a new process, all database reads and writes are
  serialized through the `dbMu sync.Mutex` declared in `db.go`.
- `dbExec` runs statements that return no rows (DDL, DML, DELETE).
- `dbQuery` runs `sqlite3 -json` and returns the JSON-encoded result set; an
  empty result is normalized to `[]`.
- `sq` quotes string literals for SQL. Callers must acquire `dbMu` before
  issuing queries and use `sq` for any string values.
- `queryExists` and `queryRows` are small helpers in `db.go` that remove the
  repetitive JSON-unmarshal boilerplate from `SELECT 1` and general queries.
- `initDB` creates the schema from the shared `schemaSQL` constant and runs
  migrations for older databases.
- `POST /v1/storage/reset` drops and recreates all game tables using the same
  `schemaSQL` script. The `users` table is intentionally preserved so that
  authenticated tests can reuse accounts across resets.

### Routing

- Routes are registered with the standard library `http.ServeMux` pattern syntax
  (e.g., `GET /health`, `POST /v1/combat/sessions/{id}/advance`).
- `r.PathValue("id")` extracts path parameters.
- The server always listens on `127.0.0.1` and uses `net.JoinHostPort` to handle
  the `PORT` env var safely.

### JSON responses

- `writeJSON` sets `Content-Type: application/json` and encodes the body.
- `writeError` is the single helper used for all error envelopes and produces
  `{"error": "..."}`. The exact message strings are preserved from the
  original implementation because the cumulative evaluator suite checks them.

## Shared helpers and data boundaries

### User identity

- `bearerUsername` extracts the username from a `Bearer session-<username>`
  header.
- `loadUserByUsername` loads a full `User` row while the caller holds `dbMu`.
- `requireDM` / `requirePlayer` / `requireCampaignOwner` /
  `requireCampaignOwnerOrMember` enforce the play-surface authorization rules.
  They return the authenticated username on success and write a 401 or 403
  response on failure.

### Play campaigns

- `play.go` owns the shared request/response structs and the core play campaign
  queries (`queryPlayCampaign`, `queryPlayCampaignMembers`, `queryPlayCampaignMember`,
  `nextNarrationSequence`).
- Domain-specific play files (`play_turns.go`, `play_scenes.go`, `play_locations.go`,
  `play_encounters.go`, `play_characters.go`) import these shared types and helpers
  and register no additional package-level state.
- `queryPlayCampaignMembers` loads party members ordered by `join_order`.
- `nextNarrationSequence` returns the next monotonic sequence number for a
  campaign's narration log.

### Encounter math

- `computeEncounterMath` in `encounters.go` is the single source of truth for
  encounter difficulty. The standalone endpoint uses the float result directly;
  the DM encounter builder casts it to an integer.

### Core campaigns

- `queryCampaignExists` in `campaigns.go` is the shared existence check for
  the `campaigns` table and is used by most campaign-scoped handlers.

## Main API/domain groupings

1. **Health & Storage** (`GET /health`, `GET /v1/storage/status`,
   `POST /v1/storage/reset`) — liveness and schema reset.
2. **Dice & Checks** (`POST /v1/dice/stats`, `POST /v1/checks/ability`) — dice
   statistics and d20 checks against a DC.
3. **Initiative** (`POST /v1/initiative/order`) — sort combatants by score,
   then dex, then name.
4. **Encounters** (`POST /v1/encounters/adjusted-xp`) — difficulty math for a
   party of level-3 characters.
5. **Characters** (`POST /v1/characters/ability-modifier`,
   `POST /v1/characters/proficiency`, `POST /v1/characters/derived-stats`) —
   5e ability modifiers, proficiency bonus, and simplified derived stats.
6. **Auth** (`POST /v1/auth/register`, `POST /v1/auth/login`) — username/password
   storage with SHA-256 + random salt; returns deterministic tokens of the form
   `session-<username>`.
7. **Combat** (`POST /v1/combat/sessions`,
   `POST /v1/combat/sessions/{id}/conditions`,
   `POST /v1/combat/sessions/{id}/advance`) — persistent initiative-based turn
   tracker with condition durations.
8. **Compendium** (`POST \| GET /v1/compendium/monsters`,
   `POST \| GET /v1/compendium/items`) — reusable monsters and items stored in
   SQLite; monster tags are stored as JSON.
9. **Campaigns** (`POST /v1/campaigns`, `POST /v1/campaigns/{id}/characters`,
   `POST /v1/campaigns/{id}/events`, `GET /v1/campaigns/{id}/state`,
   `GET /v1/campaigns/{id}/audit`, `GET /v1/campaigns/{id}/export`) — campaign
   headers, characters, and an event log.
10. **Play Campaign Surface** (`POST /v1/play/campaigns`,
    `POST /v1/play/campaigns/{id}/members`,
    `POST /v1/play/campaigns/{id}/start`,
    `POST /v1/play/campaigns/{id}/narrations`,
    `POST /v1/play/campaigns/{id}/actions`,
    `POST /v1/play/campaigns/{id}/resolutions`,
    `GET /v1/play/campaigns/{id}/turn`,
    `POST /v1/play/campaigns/{id}/turn/nudge`,
    `GET /v1/play/campaigns/{id}/my-turn`,
    `GET /v1/play/campaigns/{id}/gm/status`,
    `GET /v1/play/campaigns/{id}/document`,
    `PUT /v1/play/campaigns/{id}/document`,
    `POST /v1/play/campaigns/{id}/encounters`,
    `POST /v1/play/campaigns/{id}/turn/travel`,
    `POST /v1/play/campaigns/{id}/turn/rest`,
    `/v1/play/campaigns/{id}/scenes/*`,
    `/v1/play/campaigns/{id}/locations/*`,
    `/v1/play/campaigns/{id}/characters/{char_id}/*`,
    `/v1/play/campaigns/{id}/encounters/{enc_id}/*`) — authenticated, role-based
    turn-by-turn play with deterministic turn order, DM-private documents,
    scenes, locations, encounters, and character progression.
11. **Campaign Analytics** (`GET /v1/campaigns/{id}/analytics/summary`,
    `POST /v1/campaigns/{id}/analytics/risk-report`) — deterministic dashboard
    and maintenance risk report.
12. **Quest Tracker** (`POST /v1/campaigns/{id}/quests`,
    `POST /v1/campaigns/{id}/quests/{quest_id}/progress`,
    `GET /v1/campaigns/{id}/quests/summary`).
13. **NPCs and Factions** (`POST /v1/campaigns/{id}/factions`,
    `POST /v1/campaigns/{id}/npcs`, `GET /v1/campaigns/{id}/relationships`).
14. **Inventory and Equipment** (`POST /v1/campaigns/{id}/inventory`,
    `POST /v1/campaigns/{id}/characters/{character_id}/equipment`,
    `GET /v1/campaigns/{id}/inventory/summary`).
15. **Downtime Crafting** (`POST /v1/campaigns/{id}/downtime/crafting`,
    `POST /v1/campaigns/{id}/downtime/crafting/{project_id}/advance`).
16. **Session Scheduling** (`POST /v1/campaigns/{id}/sessions`,
    `POST /v1/campaigns/{id}/sessions/{session_id}/attendance`,
    `GET /v1/campaigns/{id}/sessions/next`).
17. **PHB Rules** (`POST /v1/phb/spell-slots`, `POST /v1/phb/rests/long`,
    `POST /v1/phb/equipment-load`) — fixed rules helpers.
18. **DM Tools** (`POST /v1/dm/encounter-builder`, `POST /v1/dm/loot-parcel`,
    `POST /v1/dm/session-recap`) — tools that combine campaign, compendium,
    and event data.

## Conventions for safely extending and testing

### Adding a new endpoint

1. Choose the file that matches the domain (or create a new file in `package main`).
   Keep play-surface files focused: campaign creation and shared state live in
   `play.go`, while travel, scenes, locations, encounters, and character
   progression live in their own files.
2. Add the request/response structs with explicit `json` tags; keep the field
   names and tags stable because the test suite depends on them.
3. Implement the handler using `json.NewDecoder(r.Body).Decode(&req)` and
   `writeJSON` / `writeError`. Reuse `writeError` with the exact error strings
   used elsewhere if they are semantically identical.
4. Register the route in `main.go` with the correct method and pattern.
5. If the endpoint touches the database, wrap the logic in `dbMu.Lock()` /
   `defer dbMu.Unlock()` and use `sq` for any string parameters. Prefer
   `queryExists` and `queryRows` to remove repetitive JSON-unmarshal code.

### Database changes

- The schema is a single source of truth in `db.go`'s `schemaSQL` constant.
- `storageResetHandler` uses `gameTablesDropSQL + schemaSQL` and preserves the
  `users` table. If you add a new game table, include it in both `schemaSQL`
  and `gameTablesDropSQL`.
- If a column is added after the codebase has already shipped, add a migration
  function like `migrateCampaignNarrationsTypeColumn` and call it from `initDB`.
  Consider using `tableHasColumn` to avoid re-implementing the PRAGMA check.
- The schema version in `schema_version` is currently hard-coded to `1`. Update it
  only if you make a breaking schema change that the test suite requires.

### Testing

- The evaluator is a black-box HTTP test suite; it does not import the package.
- Build the project before committing: `go build -o dndrest .`.
- Run the full harness with `./run.sh` and exercise the endpoints with `curl` or
  the evaluator. Do not leave the server running in the background when the
  task is complete; the harness expects `./run.sh` to start the server itself.
- A `storageResetHandler` call is typically the first step of a deterministic
  test run, so new endpoints should tolerate an empty database after reset.

### Code style

- All files share `package main`. No third-party dependencies are permitted.
- Keep the implementation deterministic: do not introduce random behavior in
  endpoint logic, and do not use wall-clock time for responses.
- Use small, domain-focused files; shared helpers like `writeJSON`,
  `writeError`, `sq`, `dbExec`, `dbQuery`, `queryExists`, `queryRows`,
  `loadUserByUsername`, and the play campaign query helpers live in their
  natural homes (`db.go`, `auth.go`, and `play.go`).
- Prefer reusable helpers for repeated queries (e.g., `queryPlayCampaign`,
  `queryPlayCampaignMembers`, `queryCampaignExists`, `queryExists`) but
  preserve the exact authorization order and error messages that the evaluator
  expects.
- Comments should explain non-obvious invariants (e.g., the initiative
  tie-breaker order, the exact meaning of an error message, or why `dbMu` is
  required). Avoid restating the code line-by-line.
