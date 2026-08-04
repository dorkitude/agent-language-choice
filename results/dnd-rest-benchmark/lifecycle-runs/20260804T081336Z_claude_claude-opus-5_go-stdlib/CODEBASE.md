# CODEBASE.md

A deterministic D&D rules-and-campaign REST API written in Go 1.26 using only
the standard library (`net/http`, `encoding/json`, `crypto/*`). There are no
third-party dependencies, and none may be added — `go.mod` declares module
`dndrest` with no `require` block.

## Starting and verifying the server

```bash
./run.sh                 # builds ./server and runs it in the foreground on 127.0.0.1:8080
PORT=9001 ./run.sh       # same, on a different port
```

`run.sh` `cd`s to the project root, so the SQLite file `game.db` is created and
reloaded beside the sources. The server binds `127.0.0.1` only and logs one line
(`listening on 127.0.0.1:<port>`) before serving.

Verify:

```bash
curl -s localhost:8080/health                 # {"ok":true}
curl -s localhost:8080/v1/storage/status      # {"driver":"sqlite","schema_version":1,"initialized":true}
curl -s -XPOST localhost:8080/v1/dice/stats -d '{"expression":"2d6+3"}'
```

`go build ./...` and `go vet ./...` are both clean and are the fastest check
that a change compiles. There is no test binary in the repo; see
[Testing](#testing).

## Entry point and file map

Everything is one package (`package main`) in the root directory. Files are
split by domain, not by layer; within the package any file can call any other,
so the split is about where a reader should look.

| File | Responsibility |
| --- | --- |
| `main.go` | Package doc, the full route table (`routes()`), `/health`, and `main()` (load storage → listen). |
| `httpx.go` | Shared HTTP plumbing: `writeJSON`, `writeError`, `decodeBody`, `requirePost`, `requireGet`. |
| `validate.go` | Shared request-field readers: `asInt`, `crKey`, `requiredString`. |
| `rules.go` | Stateless core rules: dice stats, ability checks, encounter adjusted XP, initiative ordering (`initiativeOrder`). |
| `encounter.go` | Encounter math shared by two endpoints: the `thresholds` type, the CR→XP and level→threshold tables, `countMultiplier`, `sumThresholds`, `classifyDifficulty`. |
| `characters.go` | Ability modifiers, proficiency bonus, derived stats, armor-class computation. |
| `phb.go` | Player's Handbook rules: spell slots, long rest, equipment load. |
| `auth.go` | Password hashing (PBKDF2-HMAC-SHA256), the user store, register/login. |
| `combat.go` | Stateful combat sessions: initiative order, turn cursor, conditions. |
| `compendium.go` | Monster and item entries keyed by slug. |
| `campaign.go` | Campaigns, party rosters, append-only event log. |
| `quests.go` | Campaign quest tracking: milestone checklists, progress updates, per-campaign status summary. |
| `npcs.go` | Campaign cast: factions, NPCs, and the relationship summary. |
| `inventory.go` | Campaign stock, per-character equipment assignment, and the derived inventory summary. |
| `crafting.go` | Downtime crafting projects: create, advance, and delivery of the finished item into campaign stock. |
| `scheduling.go` | Scheduled play sessions: scheduling, attendance records, and the next-session lookup. |
| `audit.go` | Read-only campaign audit counts and the deterministic export summary. |
| `analytics.go` | Read-only campaign analytics: the readiness summary and the maintenance risk report. |
| `dm.go` | DM tools that read stored state: encounter builder, loot parcel, session recap. |
| `play.go` | The protected `/v1/play` surface: bearer-token authentication (`authenticate`, `requireActor`, `requireRole`), DM-owned play campaigns, and their player memberships. |
| `store.go` | Persistence: snapshot/flush, startup load, `/v1/storage/*` endpoints. |
| `sqlite.go` | A minimal SQLite 3 file-format writer and reader (no driver available). |

## State and persistence

### In-memory stores are authoritative

Four package-level stores hold all mutable state. Each is a struct with its own
`sync.Mutex` guarding its maps:

| Store | Type | Contents |
| --- | --- | --- |
| `users` | `*userStore` | username → `*user` (role + password hash) |
| `sessions` | `*combatStore` | session id → `*combatSession` |
| `compendium` | `*compendiumStore` | slug → `*monsterEntry`, slug → `*itemEntry` |
| `campaigns` | `*campaignStore` | id → `*campaign`, plus `order []string` for creation order; each campaign owns its roster, event log, and quest list |

Reads and writes are served entirely from these maps. SQLite is a mirror, never
a read path during request handling.

### Flush-the-world persistence

`flush()` (in `store.go`) re-renders the *entire* world as a brand-new SQLite
file and atomically renames it over `game.db`. Every mutating handler calls it
after committing its change in memory. Whole-file rewrites keep `sqlite.go`
small and leave the file always internally consistent; the data set is small
and bounded, so the cost is acceptable.

At startup `initStorage()` runs `loadFromDatabase()` and then `flush()`, so the
file exists and matches the schema even on a first run.

Three rules matter when touching this area:

1. **Lock ordering.** `flush()` acquires each store's lock in turn. A handler
   must release its own store lock *before* calling `flush()`. The handlers show
   the pattern: mutate under the lock, copy anything needed for the response,
   `Unlock()`, `flush()`, then write the response.
2. **Determinism.** Snapshot helpers iterate map keys via `sortedKeys` so map
   iteration order never reaches the file. Lists whose order is part of the API
   (campaign order, rosters, event logs) carry an explicit `position` column,
   because rowid order is not a contract.
3. **Best-effort durability.** A failed write is logged and swallowed — a
   successful mutation must not turn into a failed request. `db.initialized`
   tracks whether the last flush succeeded and is what `/v1/storage/status`
   reports.

`loadFromDatabase()` skips any row that fails its invariants (unparseable
password hash, empty key, combat session whose `turn_index` does not index its
`order`) instead of aborting, so one bad row cannot make the service
unstartable.

### The SQLite layer

`sqlite.go` implements just enough of the SQLite 3 file format to be read by
real `sqlite3` tooling (`PRAGMA integrity_check` passes): rowid tables with
TEXT/INTEGER/NULL columns, leaf pages plus one level of interior pages, and
payload overflow chains. `localPayloadSize` is the one formula the writer and
reader must agree on. Nested values (initiative order, conditions, tags) are
stored as JSON text because the encoder only handles flat columns.

Schema (version 1, declared in `store.go` as `schema`): `meta`, `users`,
`combat_sessions`, `monsters`, `items`, `campaigns`, `campaign_characters`,
`campaign_events`.

## Request routing

`routes()` in `main.go` builds one `http.ServeMux` and is the single place to
look up which handler serves a path. Two registration styles coexist, and the
difference is observable:

- **Method-qualified** (`"POST /v1/campaigns"`): the mux rejects other methods
  itself.
- **Path-only** (`"/v1/dice/stats"`): the handler calls `requirePost` or
  `requireGet`, which answers `405` with an `Allow` header.

Both forms are load-bearing for existing endpoints — switching one changes its
404/405 behavior — so leave existing patterns alone and register *new* routes in
the method-qualified form. Path parameters use Go 1.22+ wildcards
(`{id}`, `{slug}`) read via `r.PathValue`.

The catch-all `"/"` route returns `{"error":"not found"}` with `404` so
unmatched paths get the same JSON envelope as everything else.

### Conventions every handler follows

- Responses are JSON; errors are always `{"error": "<message>"}` via
  `writeError`.
- Optional-vs-missing is distinguished by decoding into pointer fields
  (`*string`, `*bool`) or `*json.RawMessage`. Numeric fields use
  `*json.RawMessage` + `asInt` so `null`, `"5"`, `true`, and `1.5` are all
  rejected rather than silently coerced.
- A malformed body is `400 "invalid JSON body"`; a missing required field is
  `400 "<field> is required"`.
- Duplicate-key creation is `409`; a missing parent or entity is `404`.
- Helpers ending in a `(value, bool)` pair that take a `http.ResponseWriter`
  (`readLevel`, `armorClassOf`, `requireCampaign`) have already written the
  error response when they return `false` — the caller just returns.
- Validation order is part of the contract. When two fields are both invalid,
  the suite asserts on the message for the *first* one checked, so do not
  reorder existing checks.

## API groupings

| Group | Endpoints | Notes |
| --- | --- | --- |
| Health | `GET /health` | `{"ok":true}`. |
| Core rules | `POST /v1/dice/stats`, `/v1/checks/ability`, `/v1/encounters/adjusted-xp`, `/v1/initiative/order` | Stateless. `adjusted-xp` deliberately accepts only CR 0–5 and level-3 party members. |
| Characters | `POST /v1/characters/ability-modifier`, `/proficiency`, `/derived-stats` | Scores 1–30, levels 1–20. |
| PHB rules | `POST /v1/phb/spell-slots`, `/rests/long`, `/equipment-load` | Full-caster classes only. |
| Auth | `POST /v1/auth/register`, `/login` | `201` on register; login returns a placeholder token. |
| Combat | `POST /v1/combat/sessions`, `GET /v1/combat/sessions/{id}`, `POST .../conditions`, `POST .../advance` | Create returns `200`, not `201`, and is idempotent: re-posting an id resets that encounter to round 1. |
| Compendium | `POST /v1/compendium/monsters`, `GET .../monsters/{slug}`, `POST /items`, `GET /items/{slug}` | Create-and-read only; `201` on create. |
| Campaigns | `POST /v1/campaigns`, `POST /{id}/characters`, `POST /{id}/events`, `GET /{id}/state` | Append-only event log; state reports `log_count`. |
| Quests | `POST /v1/campaigns/{id}/quests`, `POST .../quests/{quest_id}/progress`, `GET .../quests/summary` | Statuses are `active`/`completed`/`blocked`; `201` on create. Progress names milestones by text and is idempotent; an unknown name is a `400`. |
| NPCs & factions | `POST /v1/campaigns/{id}/factions`, `POST .../npcs`, `GET .../relationships` | `201` on create. An NPC's `faction_id` is optional but must name an existing faction; the summary counts factions, NPCs, and NPCs with a positive `disposition`. |
| Inventory | `POST /v1/campaigns/{id}/inventory`, `POST .../characters/{character_id}/equipment`, `GET .../inventory/summary` | Both lists are append-only; availability is derived (`added - assigned`) and may go negative. |
| Downtime crafting | `POST /v1/campaigns/{id}/downtime/crafting`, `POST .../crafting/{project_id}/advance` | `201` on create with `days_completed: 0` and status `active`; advance accumulates days and flips to `complete` once `days_required` is reached. |
| Session scheduling | `POST /v1/campaigns/{id}/sessions`, `POST .../sessions/{session_id}/attendance`, `GET .../sessions/next` | `201` on schedule; `starts_at` must be RFC 3339 and `duration_minutes` positive. Attendance replaces the rosters and returns `200`. `next` is the earliest session by start instant, `404` when none are scheduled. |
| Audit & export | `GET /v1/campaigns/{id}/audit`, `GET .../export` | Read-only aggregations over an existing campaign; `404` when it is unknown. Neither writes state. `export` carries its own `schema_version` (`exportSchemaVersion`), independent of the SQLite `schemaVersion`. |
| Analytics | `GET /v1/campaigns/{id}/analytics/summary`, `POST .../analytics/risk-report` | Read-only aggregations; `404` when the campaign is unknown, and neither writes state. `readiness_score` is the weighted sum of the four readiness signals (dm 25, characters 25, next session 20, active quest 15); `missing` names the false ones and `risk_level` grades how many are absent (0 low, 1–2 medium, 3+ high). `open_quests` counts `active` quests only. The risk report's body is optional — `include_zeroes` is a presentation hint, since `signals` always reports all four. |
| DM tools | `POST /v1/dm/encounter-builder`, `/loot-parcel`, `/session-recap` | Read stored compendium/campaign state; all require an existing `campaign_id`. |
| Play (protected) | `POST /v1/play/campaigns`, `POST /v1/play/campaigns/{id}/members`, `POST /v1/play/campaigns/{id}/start` | The only authenticated group. `Authorization: Bearer session-<username>`; `401` for a missing/unusable credential, `403` for a valid actor without permission. Only a `dm` may create a campaign; `201` with `owner` set to the actor and `status` `lobby`, `409` on a duplicate id. Only a `player` may join one; `201` echoes the actor `username` with the character fields, `404` for an unknown campaign, and `409` when the campaign has left `lobby`, the player already holds a seat, the `character_id` is taken, or the party has reached `max_players`. Only the owning `dm` may start one; `200` with `status` `active`, `current_actor` set to the first member to join, and `turn_number` 1, `403` for a player or a non-owning DM, `404` for an unknown campaign, and `409` when the campaign has already started or the party is smaller than two. |
| Play reads (protected) | `POST /v1/play/campaigns/{id}/narrations`, `GET /v1/play/campaigns/{id}/turn`, `GET /v1/play/campaigns/{id}/my-turn` | Same credential rules as the group above. Only the owning `dm` narrates; `201` with the event's `sequence`, `kind`, `actor`, `text`. `turn` is a membership right — the owner or any seated player reads the cursor, `phase`, and the `queue` (each member in join order, each followed by the owner; empty while in `lobby`) — and anyone else is `403`. `my-turn` is a seated **player's** own view: `is_my_turn`, `current_actor`, `turn_number`, the caller's own `{id,name}` character, and `recent_events` (the last 10 log entries, oldest first). Any DM, including the owner, and any non-member is `403`; an unknown campaign is `404` first. It exposes no character but the caller's own and no DM-private fields at all. `gm/status` is its owner-only mirror: `needs_attention` (true exactly when the cursor rests on the owner), `current_actor`, `status`, `phase`, `turn_number`, the whole `party` in join order (each with `is_current`), and the same `recent_events`. Players, non-members, and any other DM are `403`; an unknown campaign is `404` first. |
| Play actions (protected) | `POST /v1/play/campaigns/{id}/actions` | Only the player the cursor rests on may declare an action. `201` with the event's `sequence`, `kind` `action`, `actor`, the caller's `type` and `text`, and `next_actor` `dm`; accepting it moves the cursor to the owning DM (`turn_number` is unchanged) and appends the event to the shared log, where both `my-turn` and `gm/status` see it. A seated player who is waiting and the DM are `409` — the request is fine, the turn is not theirs; a caller who is neither owner nor member is `403`; an unknown campaign is `404`, checked first. `type` and `text` are both required, validated after the turn check. |
| Storage | `GET /v1/storage/status`, `POST /v1/storage/reset` | Reset clears every store and recreates an empty database. |

### Domain invariants worth knowing

- **Crafted items are minted exactly once.** A crafting project delivers its
  item into campaign stock only on the `active → complete` transition, so
  replaying `advance` on a finished project accumulates days without adding a
  second item.
- **"Next session" is the earliest, not the soonest-upcoming.** The lookup
  orders by start instant and never compares against the wall clock, so the
  answer is stable no matter when it is asked. The parsed `time.Time` is used
  only for ordering; responses echo the caller's original `starts_at` text.
- **Determinism everywhere.** No randomness and no wall-clock reads in any
  response. Ties in initiative break on score desc → dex desc → name asc.
  `/v1/dm/loot-parcel` validates `seed` but intentionally ignores it.
- **Combat sessions** always have a non-empty `Order`, and `TurnIndex` always
  indexes it; handlers report the active combatant without a bounds check.
  Advancing past the end wraps to index 0 and increments `Round`.
- **Conditions** tick down at the start of the affected combatant's own turn.
  Re-applying an existing condition refreshes its duration instead of stacking.
  An expired condition leaves an empty list under its combatant's name, which is
  how callers tell "cleared" from "never present".
- **Two encounter tables on purpose.** `crXPTable` and `levelThresholdTable`
  hold the full CR 0–30 / level 1–20 data used by the DM tools.
  `/v1/encounters/adjusted-xp` reads the restricted `coreCRXP` and
  `coreLevelThreshold` views derived from them, because its narrow domain (and
  its `400`s outside it) is a frozen contract. The numbers live in one place;
  only the accepted key set differs.
- **Passwords** are PBKDF2-HMAC-SHA256, 210k iterations, 32-byte key, random
  16-byte salt, stored as `pbkdf2-sha256$<salt hex>$<key hex>`. All password
  handling is confined to `hashPassword` / `verifyPassword` / `encoded` /
  `parsePasswordHash`. Login compares with `subtle.ConstantTimeCompare` and
  returns one message for both unknown user and wrong password.
- **Quest milestones** are two parallel slices (`Milestones` text, `Done` flags),
  so duplicate milestone text stays individually countable. Ticking the last
  milestone promotes an `active` quest to `completed`; `blocked` and
  already-`completed` quests keep their status, and a quest with no milestones
  is never auto-completed. A progress batch is validated in full before any of
  it is applied.
- **Friendliness is per-NPC, not per-faction.** `friendly_npcs` counts NPCs whose
  own `disposition` is `> 0`; a faction's `stance` describes the group and never
  overrides a member's disposition. Stances are `friendly`/`neutral`/`hostile`,
  with `allied`/`unfriendly` accepted as synonyms and stored lowercased.
- **Auth runs before validation** on `/v1/play`. A handler calls
  `requireRole` first, so a caller without a usable credential gets `401` (or
  `403`) whether or not its body would have parsed. The token is the same
  placeholder login issues (`session-<username>`), resolved against the user
  store — there is no separate session table, so deleting a user revokes it.
- **Play campaigns are a separate store** from `campaign.go`'s campaigns: those
  name their DM in the request body, while a play campaign's `owner` is always
  the authenticated creator. Ids are independent between the two collections.
- **Ownership is checked after the role** on `/v1/play`. A player is `403` from
  `requireRole` before the campaign is looked up; a DM who is not this
  campaign's `owner` is `403` after. Both answer the same envelope, so a caller
  cannot use the status to probe which campaigns exist.
- **Join order is turn order.** Starting a campaign opens its cursor on
  `Members[0]` at `turn_number` 1, and the party slice is kept in join order
  everywhere — including across a restart, via the persisted `position` column.
- **Stored ids are trimmed** by `requiredString` — except the combat session id,
  which is trimmed only for the blank check and stored raw, so lookups keep
  matching what the client sent.

## Extending the codebase

1. Put new domain logic in the file that owns the domain, or add a new
   `<domain>.go` if it is genuinely new. Keep `main.go` limited to routing and
   startup.
2. Register the route in `routes()`, method-qualified, under the matching
   comment group.
3. Reuse the shared helpers rather than re-deriving them: `decodeBody`,
   `writeJSON`/`writeError`, `asInt`, `requiredString`, `crKey`. New numeric
   fields should go through `asInt` so type-rejection stays uniform.
4. If the endpoint mutates state: add the field to the in-memory struct, extend
   `schema` and the matching `snapshot*`/`load*` helper in `store.go` (bumping
   `schemaVersion` if the shape changes), and call `flush()` after releasing the
   store lock.
5. Preserve existing responses exactly — status codes, key names, key order
   within a struct, and error strings are all asserted by the cumulative suite.
   New fields are additive; renames are not.

## Testing

There is no in-repo test suite; the project is verified by an external
cumulative HTTP evaluator. Every checkpoint's suite includes all earlier ones,
so any change must be checked against the whole cumulative set, not just the
endpoints it touched.

Useful local checks, in increasing cost:

```bash
go vet ./...                                  # compiles and catches obvious mistakes
./run.sh                                      # then curl the endpoints you changed
```

Two techniques that catch regressions cheaply:

- **Differential probe.** Keep the previous `./server` binary, run old and new
  on different ports, replay the same list of `curl` requests against both, and
  diff the output. Refactors should be byte-identical, including the resulting
  `game.db`.
- **Restart round-trip.** Create data, kill the server, start it again, and read
  the data back. This is the only way to exercise the `snapshot`/`load` pair,
  including list ordering. `sqlite3 game.db "PRAGMA integrity_check"` confirms
  the file is still a valid database.

When adding a handler by hand, cover at least: missing field, wrong-typed
numeric field, out-of-range value, duplicate id, unknown parent id, and wrong
HTTP method — those are the shapes the evaluator asserts on.
