# dndrest — Codebase Overview

A single-binary D&D 5e REST API built only on the Go standard library
(`net/http`, `encoding/json`). No third-party dependencies.

## Running and verifying

```bash
./run.sh
# or directly:
PORT=8080 go run .
```

The server listens on `127.0.0.1:$PORT` (defaults to `8080` if `PORT` is
unset). Verify it's up with:

```bash
curl http://127.0.0.1:8080/health
```

Every mutation is recorded to `game.db` (JSON, see "Persistence" below) in
the current working directory, but each server process starts from a fresh,
empty in-memory schema regardless of what `game.db` already contains — see
"Persistence" for why.

## Entry point

`main.go` wires up the `http.ServeMux`, reads `PORT`, calls `initStorage()`
to reset `game.db` to an empty schema, and starts `http.ListenAndServe`. All
route registrations live in `main()`; each route maps to a handler function
defined in the module for its domain (see below). `withMethod` is a small
wrapper that rejects requests whose HTTP method doesn't match the route,
returning `405`.

## Modules

Each file groups one domain's types and HTTP handlers together:

- **`main.go`** — server bootstrap, route table, shared JSON helpers
  (`writeJSON`, `writeError`), auth (`/v1/auth/register`, `/v1/auth/login`,
  password hashing/verification), combat session HTTP handlers.
- **`storage.go`** — persistence layer (see below) and
  `/v1/storage/status` / `/v1/storage/reset`.
- **`dice.go`** — dice-expression parsing and `/v1/dice/stats`.
- **`characters.go`** — ability modifiers, proficiency bonus, derived stats,
  ability checks (`/v1/checks/ability`, `/v1/characters/*`).
- **`encounters.go`** — challenge-rating XP tables and
  `/v1/encounters/adjusted-xp`.
- **`initiative.go`** — turn-order sorting for `/v1/initiative/order`.
- **`compendium.go`** — in-memory monster/item compendium and its CRUD
  routes (`/v1/compendium/monsters*`, `/v1/compendium/items*`).
- **`campaign.go`** — campaign records (roster, characters, event log) and
  the `/v1/campaigns*` dispatch tree. `handleCampaignsSub` is the router for
  every `/v1/campaigns/{id}/...` sub-resource: it delegates in turn to each
  domain file's own `handleCampaignXxxSub` before falling back to its own
  `characters` / `events` / `state` routes.
- **`quests.go`**, **`npcs_factions.go`**, **`inventory.go`**,
  **`downtime.go`**, **`sessions.go`**, **`audit_export.go`**,
  **`analytics.go`** — additional campaign sub-resources (quests, NPCs and
  factions, inventory and equipment, crafting/downtime, session scheduling,
  audit log and export, analytics) that all attach to the same
  `/v1/campaigns/{id}/...` path space. Each file owns its slice of the
  `campaign` struct (e.g. `Quests`, `Inventory`, `Crafting`, `Sessions`) and
  exposes a `handleCampaignXxxSub(w, r, campaignID, rest) bool` matcher that
  `handleCampaignsSub` calls; it returns `true` once it has handled (or
  rejected) the request, so `handleCampaignsSub` can try the next domain.
- **`phb.go`** — PHB rules lookups: spell slots, long rest, equipment load.
- **`dm_tools.go`** — higher-level DM helpers that compose other domains:
  encounter builder, loot parcels, session recaps (`/v1/dm/*`).
- **`play_campaigns.go`**, **`play_scenes.go`**, **`play_encounters.go`**,
  **`play_characters.go`** — the turn-based "live play" engine used once a
  campaign moves out of freeform note-taking (`/v1/play/campaigns*`). This is
  a separate store (`playStore`) and domain model (`playCampaign`) from
  `campaign.go`'s `campaignStore`; the two are related only in that a play
  campaign's `Members` reference character IDs created via `/v1/campaigns*`
  or `/v1/characters*`. `authenticatePlay` implements this domain's bearer
  token scheme (`Bearer session-<username>`, matching the token minted by
  `handleLogin`); `requirePlayCampaign` is the shared "look up under
  `playMu`, 404 and unlock on miss" helper used by nearly every handler
  across these four files. All four share the same package, `playMu` lock,
  and `playCampaign` struct — the split is purely by sub-domain to keep each
  file a manageable size:
  - **`play_campaigns.go`** — core types (`playMember`, `playEvent`,
    `playCampaign`), lobby creation/join, `handlePlayCampaignsSub` (the
    dispatch tree every play-campaign sub-resource path routes through
    before falling through to the more specific handlers below), the
    exploration turn cycle (turn/nudge/travel/rest, my-turn, gm-status,
    narrations), session start, the action → resolution cycle, member
    listing, and the role-filtered campaign document.
  - **`play_scenes.go`** — scene and location types and handlers: scene
    create/enter/close/current, and location create/connect/travel.
  - **`play_encounters.go`** — encounter, monster, and turn-combatant types
    and handlers: encounter/monster CRUD, combatant bind/unbind, turn
    get/advance/delay/ready, encounter-scoped actions, damage/heal,
    conditions, status, rewards, close, and end. `playEncounterOrder` is the
    single source of truth for deterministic initiative ordering, used by
    every turn-related handler in this file.
  - **`play_characters.go`** — handlers for a party member's character
    inside a play campaign: damage/status/death-saves, owner/claim/transfer,
    build, level-up, and skill checks. Distinct from `characters.go`, which
    covers standalone (non-play) character math and CRUD.

Combat session state (initiative order, conditions, turn advancement) is
split between the `combatSession` type/logic defined alongside
`handleCreateCombatSession` and friends in `main.go`, and its on-disk
representation (`diskSession`/`diskCombatant`) in `storage.go`.

## State, persistence, and routing

**In-memory state** is held in package-level maps/slices guarded by
`sync.Mutex`/`sync.RWMutex` values scoped to each domain (e.g. `userMu` for
users, `combatMu` for combat sessions, `campaignMu` for `campaignStore` and
everything hanging off `campaign.Quests`/`Inventory`/`Crafting`/etc., and
`playMu` for `playStore`). Handlers always take the relevant lock before
reading or mutating shared state.

**Persistence** (`storage.go`) is a JSON-file store, not real SQLite: the Go
standard library has no SQLite driver, and third-party packages are
disallowed by this project's constraints. `game.db` holds a JSON-encoded
`diskState` (schema-versioned) containing users, combat sessions, monsters,
items, and campaigns (with their quests/NPCs/inventory/crafting/sessions).
`/v1/storage/status` reports `"driver": "sqlite"` to match the expected API
contract, but the implementation is a JSON snapshot file written atomically
(write to `dbPath+".tmp"`, then `os.Rename`) after each mutation via
`persistState()`/`snapshotState()`. `snapshotState()` locks each domain's
mutex in turn (never more than one at a time) to build a consistent
snapshot before writing. Crucially, `game.db` is write-only from the
server's point of view: `initStorage()` unconditionally overwrites it with
an empty schema at startup and nothing ever reads it back, because
fixture-driven evaluator suites expect every server start to be able to
recreate fixed IDs from scratch rather than inherit state from a previous
run. Play campaigns (`play_campaigns.go`) are pure in-memory state and are
never written to `game.db` at all, for the same reason (see the comment on
`playStore` usage in `storage.go`'s `snapshotState`).

**Routing** uses a single `http.ServeMux` with explicit path registration
in `main()`. Collection routes (e.g. `/v1/compendium/monsters`) and
item routes (e.g. `/v1/compendium/monsters/`) are registered separately;
handlers for the trailing-slash routes extract the path suffix themselves
(see `findSessionFromPath` in `main.go` for the combat-session pattern).
Method enforcement is applied per-route via `withMethod` except where a
handler needs to dispatch on multiple methods itself (e.g.
`handleMonstersItem`, `handleCombatSessionSub`).

## API/domain groupings

- `/health` — liveness check.
- `/v1/storage/*` — storage status and reset.
- `/v1/dice/*` — dice expression statistics.
- `/v1/checks/*`, `/v1/characters/*` — ability scores, modifiers,
  proficiency, derived stats, ability checks.
- `/v1/encounters/*`, `/v1/initiative/*` — encounter XP and turn order.
- `/v1/combat/sessions*` — combat session lifecycle: create, advance turn,
  add conditions.
- `/v1/auth/*` — user registration and login.
- `/v1/compendium/*` — monster and item CRUD.
- `/v1/campaigns*` — campaign, character, and event management, plus the
  per-campaign sub-resources: quests, NPCs/factions, inventory/equipment,
  downtime crafting, session scheduling, audit/export, and analytics.
- `/v1/phb/*` — PHB rules: spell slots, long rest, equipment load.
- `/v1/dm/*` — composite DM tools: encounter builder, loot parcel, session
  recap.
- `/v1/play/campaigns*` — the live-play turn engine: lobby, join, start,
  turn/action/resolution cycle, narrations, nudges, gm/player turn views,
  and the campaign document.

## Extending and testing safely

- Add new domain logic in a new file (or the most relevant existing one)
  following the existing pattern: package-level types, a mutex if the
  domain holds mutable state, and handler functions named `handleXxx`.
- Register new routes in `main()`'s `mux.HandleFunc` block, using
  `withMethod` unless the handler must dispatch multiple methods itself.
- If a domain's state should be recorded to `game.db` (note: this does not
  mean it survives a server restart — see "Persistence" above), add it to
  `diskState` in `storage.go`, extend `snapshotState()` accordingly, and
  call `persistState()` after mutations (following the pattern used by
  users and combat sessions).
- Always take the domain's mutex before reading/writing its shared state,
  and never call `persistState()`/`snapshotState()` while already holding
  that domain's mutex (see `snapshotState()` in `storage.go`, which takes
  and releases each domain mutex in turn rather than nesting them).
- This is a refactor-only checkpoint: HTTP endpoints, response bodies,
  status codes, persistence semantics, and validation rules from prior
  stages must not change. New work should extend the codebase without
  altering observable behavior of existing routes.
- There is no in-repo test suite; behavior is verified by the external
  `dm-tools` evaluator suite, which drives the running server over HTTP.
  When changing a handler, manually re-verify with `curl` against a
  locally running server (`./run.sh`) before considering the change done.
