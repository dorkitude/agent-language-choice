# dndrest — codebase guide

A single-binary HTTP API for running D&D 5e tabletop sessions: dice/rules
math, character derivation, combat session tracking, a monster/item
compendium, campaign logs (quests, factions, npcs, inventory, crafting,
sessions, analytics, audit export), a live turn-based "play" surface, and a
few DM-facing helpers. Go, standard library `net/http`, SQLite persistence
via the pure-Go `modernc.org/sqlite` driver (no CGO required).

## Start and verify

```bash
./run.sh
```

`run.sh` runs `go run .` in the foreground. The server reads `PORT` from the
environment (default `8080`) and always binds `127.0.0.1`. It opens/creates
`game.db` (SQLite, pure-Go driver) in the current directory on startup,
wiping any pre-existing `game.db`/`-shm`/`-wal` files first (`removeDBFiles`
in `storage.go`) so every run starts from clean, deterministic state.

Verify it's up:

```bash
curl -s http://127.0.0.1:8080/health
# {"ok":true}
```

Build/vet without running:

```bash
go build ./...
go vet ./...
```

There is no test suite in this repository; correctness is checked by an
external evaluator (see `dndeval-*-report.json` files) that drives the HTTP
API end-to-end. When changing behavior, exercise the relevant endpoints with
`curl` against a locally running server (see examples above) before
considering a change done.

## Entry point and module map

`main.go` only wires things together: it builds the `http.ServeMux` route
table (`newRouter`) and starts the listener (`main`). Everything else lives
in small, single-domain files, all in `package main`:

| File | Responsibility |
| --- | --- |
| `main.go` | Route table, server startup |
| `httputil.go` | Shared handler plumbing: `writeJSON`/`writeError` response helpers, `requireMethod`/`decodeJSONBody` request-parsing helpers, `extractSessionID` path-parsing helper |
| `storage.go` | SQLite schema, connection lifecycle, load/save functions for every domain |
| `storage_routes.go` | `/v1/storage/status` and `/v1/storage/reset` handlers |
| `health.go` | `/health` |
| `dice.go` | `/v1/dice/stats` |
| `checks.go` | `/v1/checks/ability` |
| `encounters.go` | `/v1/encounters/adjusted-xp`, CR→XP table, party XP thresholds, encounter-multiplier and difficulty logic shared with `dmtools.go` |
| `initiative.go` | `/v1/initiative/order` |
| `characters.go` | `/v1/characters/*` (ability modifier, proficiency bonus, derived stats) |
| `combat.go` | `/v1/combat/sessions*` — in-memory combat session state, initiative ordering, conditions |
| `auth.go` | `/v1/auth/register`, `/v1/auth/login` — bcrypt-hashed passwords |
| `compendium.go` | `/v1/compendium/monsters*`, `/v1/compendium/items*` |
| `campaigns.go` | `/v1/campaigns*` — campaigns, characters, event log, state summary, and the router that dispatches every `/v1/campaigns/{id}/...` sub-resource below |
| `quests.go` | campaign quests and milestone progress (`/v1/campaigns/{id}/quests*`) |
| `npcs_factions.go` | campaign factions and NPCs (`/v1/campaigns/{id}/factions`, `/npcs`, `/relationships`) |
| `inventory.go` | campaign inventory and character equipment (`/v1/campaigns/{id}/inventory*`, `/characters/{id}/equipment`) |
| `crafting.go` | crafting projects (`/v1/campaigns/{id}/downtime/crafting*`) |
| `sessions.go` | scheduled sessions and attendance (`/v1/campaigns/{id}/sessions*`) |
| `analytics.go` | campaign analytics summary and risk report (`/v1/campaigns/{id}/analytics*`) |
| `audit_export.go` | campaign audit log and export (`/v1/campaigns/{id}/audit`, `/export`) |
| `play.go` | `/v1/play/campaigns*` — the live turn-based play surface: lobby, membership, turn order, narration/action/resolution events, nudges, and the durable story/dm-notes document |
| `phb.go` | `/v1/phb/*` — spell slots, long rest, equipment load |
| `dmtools.go` | `/v1/dm/*` — encounter builder, loot parcel, session recap |

Each domain file follows the same shape: request/response structs next to
the handler that uses them, a package-level `sync.Mutex`-guarded map holding
that domain's in-memory state, and plain functions (not methods on a
server struct) registered directly with the mux (or dispatched to by another
domain's router function, for `/v1/campaigns/{id}/...` sub-resources and
`/v1/play/campaigns/{id}/...` sub-resources).

## State, persistence, and request routing

**State model.** Each domain (users, combat sessions, monsters, items,
campaigns, play campaigns/members/narrations) keeps its authoritative-for-reads
state in a package-level Go map guarded by its own `sync.Mutex` (e.g.
`usersMu`/`users` in `auth.go`, `campaignsMu`/`campaigns` in `campaigns.go`,
`playCampaignsMu`/`playCampaigns` in `play.go`). On every write, the handler
holds that domain's mutex for the full read-modify-write-persist sequence:
mutate the map, then call the matching `save*ToDB` function in `storage.go`
before releasing the lock. This keeps the in-memory map and the SQLite copy
from diverging, but it also means storage writes happen synchronously inside
the request path — a slow disk will show up as request latency.

**Persistence.** `storage.go` owns the actual SQLite access:
- `initStorage` (called once from `main`) opens `game.db`, creates the
  schema if needed (`createSchema`), and loads every table into its
  domain's in-memory map (`loadUsersFromDB`, `loadCombatSessionsFromDB`,
  `loadCampaignsFromDB`, `loadPlayCampaignsFromDB`, etc.).
- `createSchema` also runs a short list of idempotent `ALTER TABLE ...
  ADD COLUMN` statements (ignoring "duplicate column" errors) for columns
  added to `play_campaigns`/`play_members`/`play_narrations` after those
  tables' initial `CREATE TABLE` statements. Since `removeDBFiles` wipes
  `game.db` on every startup, these never actually run against an older
  on-disk database — they run against the schema created moments earlier in
  the same process — so this is really "finish building the current schema
  in two steps" rather than backward-compatible migration; the
  duplicate-column tolerance just keeps the list idempotent.
- `resetStorage` (used by `POST /v1/storage/reset`) takes every domain
  mutex, drops and recreates all tables, and clears the in-memory maps —
  this is the only place all domain locks are held together, so it doubles
  as a way to reason about lock ordering if you ever need to add a
  multi-domain operation.
- Combat sessions are stored as a single JSON blob per row
  (`persistedCombatSession`) rather than normalized columns, since their
  shape (ordered combatants with per-combatant condition lists) doesn't map
  cleanly to a fixed set of SQL columns the way monsters/items/campaigns do.

**Routing.** The server uses the standard library `http.ServeMux` with exact
paths for single-resource endpoints (e.g. `/v1/dice/stats`) and prefix
patterns (trailing slash, e.g. `/v1/campaigns/`) for endpoints that take a
path parameter. Because this Go version's `ServeMux` only does prefix
matching (not `{id}`-style templates), each prefix route is backed by a
small router function — `combatSessionsRouter`, `campaignsRouter`,
`monstersRouter`, `itemsRouter`, `playRouter` — that inspects the remaining
path suffix and dispatches to the concrete handler. `campaignsRouter` is the
biggest of these: it peels the campaign id off the front of the path and
then further dispatches by suffix (`/quests`, `/factions`, `/npcs`,
`/inventory`, `/crafting`, `/sessions`, `/analytics`, `/audit`, `/export`,
`/characters/{id}/equipment`, etc.) to handlers defined in the corresponding
domain file. `extractSessionID` (in `httputil.go`) is the shared helper for
pulling an id/slug out between a fixed prefix and suffix.

**Shared handler helpers (`httputil.go`).** Nearly every handler in the
codebase starts with the same two checks, so they're factored out:
- `requireMethod(w, r, method)` — writes a 405 and returns `false` if
  `r.Method` doesn't match; handlers `return` immediately when it's `false`.
- `decodeJSONBody(w, r, &req)` — decodes the JSON body into `req`, writing a
  400 with the standard `"invalid JSON body"` message and returning `false`
  on failure. Only used where a body is always required; a handler with an
  optional body (see `campaignRiskReportHandler` in `analytics.go`) decodes
  inline instead.

## API/domain groupings

- **Core rules math** (`dice.go`, `checks.go`, `encounters.go`,
  `initiative.go`) — stateless calculators: dice statistics, ability checks,
  encounter XP/difficulty, initiative ordering.
- **Character derivation** (`characters.go`) — ability modifiers,
  proficiency bonus by level, and derived stats (HP, AC) from ability scores
  and armor. Stateless; no persistence.
- **Combat sessions** (`combat.go`) — the one top-level endpoint group with
  live, mutable server-side state: create a session (sorts combatants into
  initiative order), add timed conditions to a combatant, and advance turns
  (which also ticks down and expires conditions on the combatant whose turn
  is starting).
- **Auth** (`auth.go`) — minimal username/password registration and login
  with bcrypt hashing. The "token" returned by login is a deterministic
  `"session-" + username` string, not a real session/JWT — treat any auth
  hardening as a separate, deliberate change, not a refactor. `play.go`'s
  `authenticatedActor` parses this same `"Bearer session-<username>"` header
  to authorize the play surface.
- **Compendium** (`compendium.go`) — CRUD-lite (create + get, no
  update/delete) for monsters and items, keyed by a validated slug.
- **Campaigns** (`campaigns.go`) — campaigns own a list of characters and a
  list of log events; `/state` returns a read-only summary. Also hosts
  `campaignsRouter`, the entry point for every `/v1/campaigns/{id}/...`
  sub-resource implemented in the files below.
- **Quests** (`quests.go`) — per-campaign quests with milestone lists and a
  `done` set; progress updates mark milestones done and flip status once all
  are complete.
- **Factions and NPCs** (`npcs_factions.go`) — per-campaign factions, NPCs
  attached to a faction, and a relationship summary rollup.
- **Inventory and equipment** (`inventory.go`) — party-level inventory
  (item + owner + quantity) and per-character equipped items, plus a
  summary endpoint.
- **Crafting** (`crafting.go`) — crafting projects tied to a character and
  item (`/v1/campaigns/{id}/downtime/crafting*`), advanced a fixed number of
  days at a time toward completion.
- **Sessions** (`sessions.go`) — scheduled play sessions with an agenda and
  present/absent attendance, recorded once per session.
- **Analytics** (`analytics.go`) — a campaign analytics summary (readiness
  score, open quests, friendly NPCs, etc.) and a risk report that flags
  missing setup (no DM, no characters, ...); the risk report's request body
  is optional (defaults `include_zeroes` to `false`).
- **Audit export** (`audit_export.go`) — a read-only audit log and a full
  campaign export, both derived from the same in-memory campaign state.
- **Play (turn-based live session)** (`play.go`) — the stateful "run the
  table" surface layered on top of a campaign: a dm creates a play campaign
  and players join it (lobby phase); starting it seats the first joiner as
  current actor. Turn order alternates strictly between whichever player is
  current actor and the owning dm: a player action always hands the turn to
  the dm (`c.CurrentActor = c.Owner`), and a dm resolution always hands it to
  the *next* player after whoever's action is being resolved, in join order
  (`createResolutionHandler`). Only the owning dm may narrate, resolve,
  nudge, or edit the durable story/dm_notes document; only a player who is a
  campaign member may submit an action, and only when it's their turn.
  `getDocumentHandler` exposes `dm_notes` to the owner only, never to
  players. `authenticatedActor`/`requireActor` are shared with the rest of
  this file's handlers for authorization.
- **PHB helpers** (`phb.go`) — spell slots (wizard-only, level 5 only, by
  design of the current data table), long rest recovery math, equipment
  carry-capacity math.
- **DM tools** (`dmtools.go`) — encounter builder (reuses the CR/XP/
  difficulty logic from `encounters.go` via `difficultyForXP`), loot parcel
  generation, and a canned session recap.

## Conventions for extending and testing safely

- **New endpoint in an existing domain:** add the handler function to that
  domain's file, register it in `newRouter` in `main.go` (or, for a
  campaign/play sub-resource, wire it into `campaignsRouter`/`playRouter`'s
  suffix dispatch instead). Follow the existing shape — `requireMethod`
  first, `decodeJSONBody` into a `*Type` (pointer fields for
  optional/required-but-zero-valued JSON fields, so `nil` vs `0` can be
  distinguished for validation), then explicit validation with `writeError`
  returns, then the domain mutation under the domain's mutex, then
  `writeJSON`.
- **New domain:** add a new file with its own state map + mutex (don't
  reuse another domain's mutex), corresponding `load*FromDB`/`save*ToDB`
  functions in `storage.go`, a `CREATE TABLE IF NOT EXISTS` entry in
  `createSchema`, and a `DROP TABLE IF EXISTS` entry (plus map reset) in
  `resetStorage`.
- **Locking:** always hold the domain mutex across both the in-memory
  mutation and its `save*ToDB` call — don't split them, or a concurrent
  reader could observe a map update that hasn't been persisted yet (or
  vice versa after a crash). When a handler needs two domain locks (e.g.
  `play.go` handlers touching both `playCampaignsMu` and `playMembersMu`),
  acquire `playCampaignsMu` first, consistent with `resetStorage`'s lock
  order, to avoid introducing a deadlock-prone inverse order elsewhere.
- **Path-parameterized routes:** register the prefix (trailing slash) on
  the mux and add matching logic to that domain's router function using
  `extractSessionID`; don't hand-roll new prefix/suffix string slicing.
- **Error responses:** always go through `writeError`, which produces
  `{"error": "..."}`. Keep messages user-facing and specific (see existing
  handlers for tone/format) since the evaluator suite asserts on message
  content in places. Use `requireMethod` and `decodeJSONBody` (in
  `httputil.go`) instead of re-inlining the method-check/decode
  boilerplate — every handler in the codebase uses these two helpers except
  where a body is genuinely optional.
- **Testing a change:** there's no in-repo test suite. Start the server
  (`./run.sh` or `PORT=<n> go run .` for a scratch instance), exercise the
  changed and any behaviorally-adjacent endpoints with `curl`, and diff the
  JSON response shape/status codes against what existed before your change.
  Delete any scratch `game.db` you create before finishing.
