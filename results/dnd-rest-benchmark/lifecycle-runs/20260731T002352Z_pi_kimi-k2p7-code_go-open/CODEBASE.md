# dndrest — Codebase Guide

This is a small Go HTTP service that implements a deterministic subset of D&D 5e helpers (dice statistics, ability checks, encounter math, initiative, character stats, spell slots, rests, encumbrance) plus campaign, compendium, and play-session management backed by SQLite.

This codebase is the result of the `050-codebase-refactor` cumulative checkpoint. All HTTP endpoints, response bodies, status codes, validation rules, and persistence semantics are preserved from the `049-skills-and-proficiencies` cumulative suite. This refactoring pass only changed internal structure: handlers are grouped by domain, common helpers are extracted, duplication is reduced, and invariants are documented.

## Quick start

```bash
# run the server in the foreground on the port given by the PORT env var
PORT=8080 ./run.sh
```

If `PORT` is not set, the server listens on `127.0.0.1:8080` by default. The script builds the binary and then `exec`s it, so the server remains in the foreground.

Verify the server is up:

```bash
curl http://127.0.0.1:8080/health
```

The SQLite database is stored in `./game.db`. The first startup creates the schema automatically and deletes any stale database from a previous run to keep the evaluator deterministic.

Run the unit tests:

```bash
go test ./...
```

## Entry point and routing

- `main.go` is the only entry point. It initializes the database, creates an `http.ServeMux`, registers every handler, and calls `http.ListenAndServe` on `127.0.0.1:$PORT`.
- Routes are grouped by domain and registered in `main.go` in a clear order: core rules, auth, combat, storage, compendium, play campaigns, campaign state, analytics, scheduling, inventory, crafting, quests, NPCs/factions, PHB rules, and DM tools.
- Routing uses Go 1.22+ path-value patterns (e.g. `GET /v1/compendium/monsters/{slug}`). There is no middleware chain; each handler validates and responds directly.

## Major files and modules

| File | Responsibility |
|------|----------------|
| `main.go` | Server entry point and route table. |
| `models.go` | Domain structs and small role/status constants, grouped into logical sections (auth/runtime state, compendium, campaign state, play surface, encounters, character build). |
| `rules.go` | Static lookup tables (CR XP, encounter thresholds, loot table, spell slots) and pure calculation helpers (`abilityModifier`, `proficiencyBonus`, `computeInitiative`, `computeEncounterMetrics`, `recommendationFor`, `lootForTier`, `recapOpenThreads`). |
| `db.go` | SQLite connection setup, schema DDL, idempotent migrations (via a shared `addMissingColumns` helper), and all DB helper functions. |
| `state.go` | Package-level mutable state (`db`, `users`, `combat`, `initMu`/`initialized`). |
| `handlers_core.go` | Shared JSON response helpers, error helpers, SQLite error helpers, common `requireCampaign` loader, and core rule endpoints (`/health`, dice, ability checks, adjusted XP, initiative, ability modifier, proficiency, derived stats). |
| `handlers_auth.go` | Password hashing and the `/v1/auth/*` endpoints. |
| `handlers_combat.go` | In-memory combat sessions (`/v1/combat/sessions/*`). |
| `handlers_storage.go` | Storage status and reset (`/v1/storage/*`). |
| `handlers_compendium.go` | Monster and item CRUD (`/v1/compendium/*`). |
| `handlers_campaign.go` | Campaigns, characters, events, and aggregated campaign state (`/v1/campaigns/*`). |
| `handlers_analytics.go` | Campaign analytics and risk reports (`/v1/campaigns/{id}/analytics/*`). |
| `handlers_sessions.go` | Campaign session scheduling (`/v1/campaigns/{id}/sessions/*`). |
| `handlers_inventory.go` | Party inventory and equipment assignment (`/v1/campaigns/{id}/inventory/*`). |
| `handlers_downtime.go` | Downtime crafting projects (`/v1/campaigns/{id}/downtime/crafting/*`). |
| `handlers_quest.go` | Quest tracking (`/v1/campaigns/{id}/quests/*`). |
| `handlers_npcs_factions.go` | Factions, NPCs, and relationship summary (`/v1/campaigns/{id}/factions/*`, `/v1/campaigns/{id}/npcs/*`, `/v1/campaigns/{id}/relationships`). |
| `handlers_phb.go` | Player's Handbook rules (`/v1/phb/*`). |
| `handlers_dm.go` | DM tools (`/v1/dm/*`). |
| `handlers_play.go` | Authenticated play-surface campaigns (`/v1/play/campaigns/*`), including narrations, turn queue, actions, resolutions, nudges, and campaign documents. |
| `rules_test.go` | Unit tests for the deterministic pure functions in `rules.go`. |

## State, persistence, and request routing

### Persistence

- The database is SQLite, accessed through the pure-Go `modernc.org/sqlite` driver (no CGO).
- Foreign keys are enabled with `PRAGMA foreign_keys = ON`.
- `initDB` opens the database, applies the schema, runs idempotent migrations, and loads the in-memory caches. To keep the evaluator deterministic across repeated runs, any stale `game.db` from a previous process is removed before opening a fresh database.
- Major durable tables:
  - `users` — registered accounts.
  - `combat_sessions`, `combat_order`, `combat_conditions` — combat encounter state.
  - `monsters`, `monster_tags` — compendium monsters.
  - `items` — compendium items.
  - `campaigns`, `characters`, `events` — campaign state and log.
  - `campaign_sessions`, `session_agenda`, `session_attendance` — scheduled play sessions and attendance.
  - `quests`, `quest_milestones` — quest tracking.
  - `factions`, `npcs` — campaign relationships.
  - `inventory`, `equipment` — party inventory and character equipment.
  - `crafting_projects` — downtime crafting.
  - `play_campaigns`, `play_members`, `play_narrations`, `play_scenes`, `play_locations`, `play_connections` — authenticated play surface, scene state, and location graph.
  - `play_encounters`, `play_combatants`, `play_encounter_monsters`, `play_encounter_conditions`, `play_encounter_rewards` — play-surface combat encounters.

### Idempotent migrations

`createSchema` in `db.go` applies the full DDL and then runs idempotent migrations for columns and tables added by later stages (e.g. `play_campaigns.current_actor`, `turn_number`, `nudge_count`, `story`, `dm_notes`, and `play_narrations.type`). The simple column-addition migrations share a single `addMissingColumns` helper that queries `PRAGMA table_info` once per table and runs the original `ALTER TABLE` statements in order when a column is absent. They are safe on both fresh databases and databases from earlier stages.

### In-memory caches

- `users` mirrors the `users` table. Registering writes to SQLite first, then updates the cache. Login checks read the cache under an `RWMutex`.
- `combat` caches active combat sessions from `combat_sessions` plus the full order and conditions tables. It is hydrated on startup and updated whenever a session is created or advanced.
- `storageStatusHandler` and `storageResetHandler` use `initMu` to report and control schema-initialized state.

### Request routing and shared helpers

- Standard library `net/http.ServeMux` with Go 1.22+ path-value patterns.
- Handlers return errors via `badRequest`, `conflict`, `notFound`, `unauthorized`, `forbidden`, and `writeJSON` helpers defined in `handlers_core.go`.
- `isUniqueViolation` and `isForeignKeyViolation` centralize detection of SQLite unique/foreign-key failures so handlers can translate them into 409/404 responses with domain-specific messages.
- `requireCampaign` loads a campaign and writes the standard 404 response if it is missing or the load fails. It is used by any handler that needs to validate a `/v1/campaigns/{id}` path parameter.
- `handlers_play.go` contains `authenticate` (Bearer `session-<username>` validation) and `requirePlayCampaign` (loads the play surface campaign with the standard 400/404 response). Auth failures are written with `authFail` from `handlers_core.go`.

## Main API/domain groupings

1. **Core rules** (`/v1/dice/*`, `/v1/checks/*`, `/v1/encounters/*`, `/v1/initiative/*`, `/v1/characters/*`) — pure, deterministic calculations with no persistence. Dice handlers compute min/max/average rather than rolling.
2. **Auth** (`/v1/auth/*`) — password hashing with bcrypt; returns deterministic `session-<username>` tokens.
3. **Combat** (`/v1/combat/*`) — initiative order, conditions, and turn advancement persisted to SQLite and mirrored in memory.
4. **Storage** (`/v1/storage/*`) — introspects the SQLite driver/schema and can reset the database to a clean schema while preserving users.
5. **Compendium** (`/v1/compendium/*`) — CRUD for monsters and items; tags are stored in a child table.
6. **Campaigns** (`/v1/campaigns/*`) — campaigns, characters, events, audit, export, and aggregated state.
7. **Campaign analytics** (`/v1/campaigns/{id}/analytics/*`) — deterministic readiness score and risk report.
8. **Session scheduling** (`/v1/campaigns/{id}/sessions/*`) — scheduled play sessions and attendance.
9. **Inventory and equipment** (`/v1/campaigns/{id}/inventory/*`) — party inventory and per-character equipment assignment.
10. **Downtime crafting** (`/v1/campaigns/{id}/downtime/crafting/*`) — crafting projects that advance days and produce items on completion.
11. **Quest tracking** (`/v1/campaigns/{id}/quests/*`) — quests with milestones and status aggregation.
12. **NPCs and factions** (`/v1/campaigns/{id}/factions/*`, `/v1/campaigns/{id}/npcs/*`, `/v1/campaigns/{id}/relationships`) — relationship map and friendly-NPC counts.
13. **Player's Handbook rules** (`/v1/phb/*`) — spell slots, long rests, and encumbrance.
14. **DM tools** (`/v1/dm/*`) — encounter builder, loot parcels, and session recap hooks that scan the latest event summary.
15. **Play surface** (`/v1/play/campaigns/*`) — authenticated campaign lifecycle (create, join, start), narrations, turn queue, player actions, GM resolutions, nudges, GM status, owner/player campaign documents with DM-note filtering, and owner-managed location graph.

## Conventions for extending and testing

- All files belong to `package main`. The project is deliberately kept as a single package to avoid exposing internal symbols unnecessarily.
- Keep handlers grouped by domain in the existing `handlers_*.go` files. Add a new file only when a domain is large enough to warrant its own boundary.
- Pure calculation logic belongs in `rules.go`; persistence logic belongs in `db.go`; types and shared constants belong in `models.go`.
- All JSON responses are produced via `writeJSON` so the `Content-Type` header and encoding error logging are consistent.
- Status codes are part of the observable contract: use `http.StatusOK` for successful reads, `http.StatusCreated` for successful creation, and the standard 400/401/403/404/409 helpers for errors.
- Unique-constraint failures are detected with `isUniqueViolation`; foreign-key failures are detected with `isForeignKeyViolation`. Avoid duplicating the raw SQLite error string in individual handlers.
- Map iteration order is non-deterministic. Avoid relying on it for any response field that tests compare exactly. Use explicit `ORDER BY` clauses in SQL and sort slices where needed.
- The service is deterministic by design: dice handlers compute min/max/average; bcrypt uses the default cost; no randomness is used. Do not introduce `math/rand` or non-deterministic sources.
- All database mutations should be performed inside a transaction when they touch more than one table. Existing helpers in `db.go` already follow this pattern; new helpers should too.
- The in-memory caches (`users`, `combat`) are protected by mutexes. Always hold the appropriate lock before reading or writing the cached map.
- Add unit tests for pure helpers in `rules.go` (see `rules_test.go` for examples). Keep tests deterministic and do not require an external network or running server.
- When refactoring, do not change the observable HTTP contract: endpoints, status codes, response field names, error messages, validation order, and persistence semantics must stay identical. Keep changes purely internal (structure, names, comments, and duplication removal).
- To test locally, start the server with `./run.sh` and use `curl` against `http://127.0.0.1:$PORT`. To run the unit-test suite, use `go test ./...`.
