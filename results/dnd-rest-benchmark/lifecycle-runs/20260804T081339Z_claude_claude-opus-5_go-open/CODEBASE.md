# CODEBASE.md

`dndrest` is a single-binary HTTP JSON API for Dungeons & Dragons table math and
campaign bookkeeping. It is written in Go (1.26, per `go.mod`) as one `main`
package split into one file per API grouping, with SQLite for all durable state.

This document describes the implementation as it stands, not a target design.

## Running and verifying

```bash
./run.sh                 # builds ./dndrest and runs it in the foreground
PORT=9000 ./run.sh       # PORT selects the port; default 8080
```

`run.sh` `cd`s to its own directory, exports `PORT` with a default of `8080`,
runs `go build -o ./dndrest .`, and `exec`s the binary. The server binds
`127.0.0.1:$PORT` only — it never listens on a public interface — and logs
`listening on 127.0.0.1:<port>` once bound.

Verify a running server:

```bash
curl -s localhost:8080/health                        # {"ok":true}
curl -s localhost:8080/v1/storage/status             # driver, schema_version, initialized
curl -s -X POST localhost:8080/v1/dice/stats \
  -H 'content-type: application/json' -d '{"expression":"2d6+3"}'
```

Run the unit tests with `go test ./...`; they need neither a database nor a
port. The authoritative check is the external `dndeval` suite, which is
cumulative — each stage's suite includes every earlier stage's tests:

```bash
dndeval run --suite dm-tools --base-url http://127.0.0.1:8080
```

There is no network access at runtime and no outbound call anywhere in the code.

## Entry point and module map

`main.go` is the entry point and the only place routes are declared. `main`
reads `PORT`, opens storage, resets the schema, then serves. Everything else is
a domain file:

| File | Responsibility |
| --- | --- |
| `main.go` | Entry point, `PORT` handling, the complete route table (`newRouter`), `/health` |
| `httpx.go` | Shared HTTP plumbing: JSON writing, the error envelope, method guards, required-field helpers, storage-error responses |
| `storage.go` | SQLite handle, schema DDL, reset, and the `/v1/storage/*` endpoints |
| `dice.go` | Dice-expression parsing and `/v1/dice/stats` |
| `checks.go` | `/v1/checks/ability` |
| `encounters.go` | CR/XP tables, difficulty thresholds, the `flexString` decoder, and `/v1/encounters/adjusted-xp` |
| `initiative.go` | The `combatant` types, initiative sorting, and `/v1/initiative/order` |
| `characters.go` | Ability/level rules (`abilityModifier`, `proficiencyBonus`, `validScore`, `validLevel`) and `/v1/characters/*` |
| `combat.go` | Persisted combat sessions: load/insert/save plus `/v1/combat/*` |
| `auth.go` | PBKDF2 password hashing, the user table, `/v1/auth/*` |
| `compendium.go` | Monster and item records, `/v1/compendium/*` |
| `campaigns.go` | Campaigns, rosters, event log, `/v1/campaigns/*` |
| `quests.go` | Campaign quests and milestone progress, `/v1/campaigns/{id}/quests*` |
| `npcs.go` | Campaign factions, NPCs and the relationship summary, `/v1/campaigns/{id}/{factions,npcs,relationships}` |
| `inventory.go` | Campaign inventory, per-character equipment assignment and the inventory summary, `/v1/campaigns/{id}/inventory*` and `/v1/campaigns/{id}/characters/{character_id}/equipment` |
| `crafting.go` | Downtime crafting projects and their advance/completion rule, `/v1/campaigns/{id}/downtime/crafting*` |
| `sessions.go` | Scheduled play sessions, agendas, attendance and the next-session lookup, `/v1/campaigns/{id}/sessions*` |
| `audit.go` | Read-only campaign rollups, `/v1/campaigns/{id}/{audit,export}` |
| `analytics.go` | Deterministic campaign analytics, `/v1/campaigns/{id}/analytics/{summary,risk-report}` |
| `play.go` | Bearer-token authentication helpers and the protected play surface, `/v1/play/*` |
| `phb.go` | Player's Handbook tables, `/v1/phb/*` |
| `dm.go` | DM tools that read stored state, `/v1/dm/*` |
| `rules_test.go` | Unit tests for the pure helpers |

Dependency direction is one-way: domain files use `httpx.go` and `storage.go`,
never the reverse. Cross-domain sharing is deliberate and narrow — `dm.go`
reuses the XP math in `encounters.go`, `combat.go` reuses the ordering in
`initiative.go`, `phb.go` reuses the range predicates in `characters.go`, and
`dm.go`, `quests.go`, `npcs.go`, `inventory.go`, `crafting.go`,
`sessions.go` and `audit.go` reuse
`requireCampaign`, `nextPosition` and `rowExists` from `campaigns.go`.
`analytics.go` reuses `countCampaignRows` from `audit.go` and the `questActive`
status constant from `quests.go`.
`crafting.go` also writes the `campaign_inventory` ledger owned by
`inventory.go` when a project completes.

## State and persistence

All durable state lives in one SQLite database file, `game.db`, created next to
the binary. The driver is `modernc.org/sqlite`, a pure-Go implementation, so no
CGO toolchain is required.

- `db` (`storage.go`) is a single `*sql.DB` shared by every handler, capped at
  **one** open connection (`SetMaxOpenConns(1)`). Writers therefore serialize
  rather than race for SQLite's write lock, which keeps behavior deterministic
  under the evaluator's concurrent requests.
- The connection string sets `busy_timeout(5000)` so a contended write waits
  instead of failing, and `foreign_keys(1)` so the schema's `ON DELETE CASCADE`
  declarations actually fire.
- `storeMu` (`storage.go`) is a process-level mutex guarding any
  read-modify-write that spans more than one statement: session creation,
  condition ticking, slug/id existence-then-insert, and `position` assignment.
  The single connection alone does not make those sequences atomic.
- **`main` calls `resetStorage()` on every boot.** A leftover `game.db` would
  make previously registered usernames and session ids collide, so each process
  starts from a clean schema. Nothing survives a restart by design.
- `schemaVersion` is 1 and is stamped into the `schema_meta` table;
  `GET /v1/storage/status` reports it along with `initialized`.

Tables: `schema_meta`, `users`, `combat_sessions`, `combat_combatants`,
`combat_conditions`, `monsters`, `items`, `campaigns`, `campaign_characters`,
`campaign_events`, `campaign_quests`, `campaign_quest_milestones`,
`campaign_factions`, `campaign_npcs`, `campaign_inventory`,
`campaign_equipment`, `campaign_crafting`, `campaign_sessions`,
`campaign_session_agenda`, `campaign_session_attendance`. `initSchema`
is idempotent (every statement is
`IF NOT EXISTS` or an upsert), so it serves as both first-run creation and
post-reset recreation.

Two storage conventions matter when reading the code:

- **Ordered child rows.** `combat_combatants`, `combat_conditions`,
  `campaign_characters` and `campaign_events` each carry an integer `position`
  assigned at insert time, and every read orders by it. This is what makes
  responses stable instead of dependent on SQLite's row order.
- **The NULL condition marker.** A row in `combat_conditions` whose `condition`
  is `NULL` means "this combatant has held a condition at some point." It keeps
  the target's key present so an emptied list still renders as `[]` rather than
  vanishing from the response.

## Request routing

Routing uses the standard library's `http.ServeMux` with Go 1.22+ wildcard
patterns (`/v1/campaigns/{id}/state`); path variables are read with
`r.PathValue`. There is no third-party router and no middleware chain.

Patterns are registered **without** a method prefix. Each handler validates its
own method so a wrong method yields `405` with an `Allow` header and a JSON
error body, rather than `ServeMux`'s bare response. Two helpers cover this:

- Handlers that take a body call `decodeBody`, which enforces `POST` **and**
  decodes in one step. They must not also call `requireMethod`.
- Handlers with no body (`GET` reads, `POST /advance`,
  `POST /v1/storage/reset`) call `requireMethod` directly.

Every non-2xx response is `{"error": "<message>"}` written by `writeError`;
success bodies are per-endpoint structs written by `writeJSON`. Handlers return
immediately after writing — the helpers return a `bool`, and the idiom is
`if !helper(...) { return }`.

Validation order inside a handler is load-bearing and asserted by the evaluator:
for nested resources the parent is resolved **before** the payload is judged, so
an unknown session or campaign id is a `404` even when the body is also invalid.

## API groupings

| Group | Endpoints | Nature |
| --- | --- | --- |
| Health | `GET /health` (any method accepted) | Liveness |
| Dice | `POST /v1/dice/stats` | Stateless |
| Checks | `POST /v1/checks/ability` | Stateless |
| Encounters | `POST /v1/encounters/adjusted-xp` | Stateless |
| Initiative | `POST /v1/initiative/order` | Stateless |
| Characters | `POST /v1/characters/{ability-modifier,proficiency,derived-stats}` | Stateless |
| PHB | `POST /v1/phb/{spell-slots,rests/long,equipment-load}` | Stateless |
| Combat | `POST /v1/combat/sessions`, `POST /v1/combat/sessions/{id}/conditions`, `POST /v1/combat/sessions/{id}/advance` | Stateful |
| Auth | `POST /v1/auth/register`, `POST /v1/auth/login` | Stateful |
| Compendium | `POST`/`GET /v1/compendium/monsters[/{slug}]`, `POST`/`GET /v1/compendium/items[/{slug}]` | Stateful |
| Campaigns | `POST /v1/campaigns`, `POST /v1/campaigns/{id}/characters`, `POST /v1/campaigns/{id}/events`, `GET /v1/campaigns/{id}/state` | Stateful |
| Quests | `POST /v1/campaigns/{id}/quests`, `POST /v1/campaigns/{id}/quests/{quest_id}/progress`, `GET /v1/campaigns/{id}/quests/summary` | Stateful |
| NPCs & factions | `POST /v1/campaigns/{id}/factions`, `POST /v1/campaigns/{id}/npcs`, `GET /v1/campaigns/{id}/relationships` | Stateful |
| Inventory & equipment | `POST /v1/campaigns/{id}/inventory`, `POST /v1/campaigns/{id}/characters/{character_id}/equipment`, `GET /v1/campaigns/{id}/inventory/summary` | Stateful |
| DM tools | `POST /v1/dm/{encounter-builder,loot-parcel,session-recap}` | Reads stored state |
| Storage | `GET /v1/storage/status`, `POST /v1/storage/reset` | Introspection / fixture reset |

Notes on the less obvious ones:

- **Auth.** Passwords are PBKDF2-HMAC-SHA256, 210,000 iterations, 32-byte key,
  16-byte random per-user salt; all hashing is behind
  `hashPassword`/`verifyPassword`. Login of an unknown username still runs a
  hash so it costs the same as a wrong password. The issued token is
  `"session-" + username` — derived, not stored, and not yet required by any
  endpoint.
- **Combat.** A session's initiative order is frozen at creation. Only the turn
  pointer and the condition table change afterwards. `advance` moves one step,
  wrapping to index 0 and incrementing `round`, then decrements the newly active
  combatant's own conditions.
- **DM tools.** Purely derived: `encounter-builder` resolves monster slugs to
  CRs and reuses `encounters.go`'s math, `session-recap` folds the campaign
  event log, and `loot-parcel` is a fixed per-tier table that accepts `seed` and
  deliberately ignores it. `loot-parcel` echoes `campaign_id` without verifying
  it; `encounter-builder` and `session-recap` do read campaign/monster state.
- **Quests.** Status is one of `active`, `completed`, `blocked` (default
  `active`); anything else is a `400`. `milestones_total`/`milestones_done` are
  always derived from the `campaign_quest_milestones` rows, never stored. A
  progress call names milestones by string, so blank and duplicate names are
  dropped at create time and an unknown or already-done name is a no-op —
  replaying the same call cannot change the counts. Status transitions: an
  explicit `status` in the progress body wins; otherwise an `active` quest whose
  milestones are all done flips to `completed`. A `blocked` quest never
  auto-completes. The literal `/quests/summary` pattern outranks
  `/quests/{quest_id}/progress` in `ServeMux`, so no ordering care is needed.
- **NPCs and factions.** A faction's `stance` is free text defaulting to
  `neutral`: the spec names `friendly` but fixes no closed set, so an
  unrecognized stance is stored rather than rejected. An NPC's `faction_id` is
  optional and renders as `""` when absent, but a non-empty value must name a
  faction of the same campaign or the write is a `404` — `campaign_npcs.faction_id`
  is therefore a plain column, not a foreign key. The relationship summary is
  derived on read; `friendly_npcs` counts NPCs whose `disposition` is strictly
  positive, so friendliness is a property of the individual, not of their
  faction's stance.
- **Inventory and equipment.** Two append-only ledgers that never merge:
  `campaign_inventory` records what the campaign acquired, `campaign_equipment`
  records what was handed to a roster member. An assignment does not consume or
  delete the party row, so `party_items` and `assigned_items` are plain row
  counts of their own tables — three potions in one row are one party item.
  `healing_potions_available` is the only quantity-aware number: stocked minus
  assigned `healing-potion` units, so it can go negative if more is handed out
  than stocked. `owner` is free text defaulting to `party`, `quantity` must be a
  positive integer, and `item_slug` is *not* checked against the compendium —
  but an equipment assignment must name a character on this campaign's roster or
  it is a `404`. As with quests, the literal `/inventory/summary` pattern
  outranks `/inventory` in `ServeMux`.
- **Session scheduling.** `starts_at` is validated as RFC3339 (a zoneless
  `2006-01-02T15:04:05` is also accepted and read as UTC) but echoed back
  **verbatim**, so a caller's offset survives the round trip. Ordering uses the
  separate `starts_at_key` column — the same instant normalized to UTC — so
  `GET /sessions/next` is independent of timestamp spelling *and* of the wall
  clock: "next" means earliest on the calendar, past or future, with insert
  `position` breaking ties. An empty calendar is a `404`. Attendance
  **replaces** the whole record for a session rather than merging, so a
  correction reports exactly what it was given; a name appearing in both lists
  counts as present only, and character ids are not checked against the roster
  (unlike equipment assignment). Agenda entries are de-blanked like quest
  milestones, and `agenda_count` is a row count of `campaign_session_agenda`.

- **Audit and export.** `audit.go` owns no table of its own: both endpoints are
  pure `COUNT` rollups over tables other modules write, taken under `storeMu` so
  a read never straddles a write. They therefore inherit the "count rows, not
  units" rule — `inventory_items` counts `campaign_inventory` stacks, matching
  `party_items`, not potion units. `GET /audit` counts events, quests, NPCs and
  sessions; `GET /export` counts characters, quests, NPCs, inventory stacks and
  sessions alongside the campaign `name` and the storage `schemaVersion`
  constant. The export is a JSON summary, never a file download, and is
  deterministic: identical bytes for identical state. Both are `404` for an
  unknown campaign — `/export` gets that for free from its `name` lookup, so it
  resolves the campaign itself instead of calling `requireCampaign`.

- **Analytics.** `analytics.go` is the second table-less module and follows the
  same rules as `audit.go`: pure reads under `storeMu`, and counting semantics
  borrowed from the module that owns each table rather than reinvented — an
  "open" quest is `status = questActive`, a "friendly" NPC has
  `disposition > 0` (matching the relationship summary), and `inventory_items`
  counts stacks. Both endpoints derive from one `readCampaignMetrics` read, so
  the summary and the risk report can never disagree about the same campaign.
  `readiness_score` weights the four maintenance signals — DM, characters, a
  scheduled session, an active quest — as `25 + 15` each, so a fully populated
  campaign scores `85` and a bare one `25`; it deliberately ignores the
  magnitude of each pile, since a second NPC does not make a campaign readier.
  `risk_level` is `low`/`medium`/`high` at 0 / 1–2 / 3+ unsatisfied signals.
  `include_zeroes` defaults to `true` and only suppresses the `missing` list —
  it never changes `risk_level`, so hiding the detail cannot hide the finding.
  The risk report's body is entirely optional (an absent body reads as `{}`),
  but a malformed one is still `400`; both endpoints are `404` for an unknown
  campaign, which they get from the `dm` lookup that opens the metrics read.

- **Authenticated play.** `play.go` is the only protected area of the API;
  everything else is open and must stay open. A request carries
  `Authorization: Bearer session-<username>` — the exact token `/v1/auth/login`
  mints, which is derived from the username rather than stored, so it needs no
  session table. The token *names* its actor: a well-formed one authenticates
  even when the username was never registered, because the play surface has no
  sign-up step. A `getUser` hit supplies the stored role; otherwise
  `roleForUsername` derives it (`dm` and `dm-*` are DMs, everyone else plays).
  The two failure modes are kept strictly apart and must not be merged:
  `401 {"error":"authentication required"}` for a missing header, a non-bearer
  scheme, or a token without a `session-<username>` shape; `403
  {"error":"forbidden"}` for a known actor whose role does not permit the
  action — an unregistered name is a known actor, not an anonymous one. Handlers check credentials *before* decoding the body, so an
  anonymous caller never learns which payloads would have been valid — a new
  protected endpoint should call `requireActor` then `requireRole` first.
  `play_campaigns` is deliberately a separate table from the open `campaigns`
  one: it carries an `owner` (the creating `dm`) and a lifecycle `status` that
  starts at `playCampaignStatusLobby`, and ids never collide across the two.

- **Party membership.** `POST /v1/play/campaigns/{id}/members` seats the *actor*
  — a player joins as themselves and cannot enroll anyone else, so the body only
  names the character (`character_id`, `name`, `class`). Only the `player` role
  may join; a DM gets 403. `play_campaign_members` enforces one seat per
  `(campaign, username)` and a unique `character_id` per campaign, and its
  `position` records join order so later stages can render the party in the
  sequence players actually joined. Every "the party cannot take this request"
  case is a 409 with its own message: the player already holds a seat, the
  character id is taken, the party has reached `max_players` (a `max_players` of
  0 means no limit), or the campaign has left the lobby. A campaign that does
  not exist is 404, not 409.

- **Starting play.** `POST /v1/play/campaigns/{id}/start` moves a campaign from
  the lobby to `playCampaignStatusActive` exactly once, and only the `dm` who
  created it may do so — a player, or a DM who owns a different table, gets 403.
  Both "not in the lobby" cases are 409: already active, or a party still short
  of `playCampaignMinParty` (2). Success writes the play clock onto
  `play_campaigns` — `current_actor` is the member with the lowest `position`
  (the first to join) and `turn_number` becomes 1 — and echoes
  `{id, status, current_actor, turn_number}`. The `UPDATE` repeats the status
  guard in its `WHERE`, so two concurrent starts cannot both claim the first
  turn; the loser sees zero affected rows and reports the same 409.

- **GM narration and the event log.** `POST /v1/play/campaigns/{id}/narrations`
  takes `{"text":"..."}` and appends one row to `play_campaign_events`, which is
  the campaign's append-only story log: `sequence` starts at 1 per campaign
  (`nextPlayEventSequence`) and is never renumbered or rewritten. The 201 body is
  `playEventResponse` — `{sequence, kind, actor, text}` — with `kind` fixed to
  `"narration"` and `actor` the narrating username, which for the owning DM is
  `dm`. Only the owner narrates: a player, or a DM who owns a different table,
  gets 403, and an unknown campaign is 404. Permission is settled *before* the
  body is decoded, so a forbidden actor never learns whether their payload was
  well-formed. Later event kinds should reuse `playEventResponse` and this table
  rather than starting a parallel log.

- **Reading the play clock.** `GET /v1/play/campaigns/{id}/turn` returns
  `playTurnResponse` — `{campaign_id, current_actor, phase, turn_number, queue}`.
  `playTurnPhase` names who the clock waits on: an active campaign is `"dm"` when
  the owner holds the turn and `"player"` otherwise, while a campaign that has
  not started has no turn holder and falls back to its lifecycle `status`, so a
  lobby campaign reports `{"", "lobby", 0, []}`. `playTurnQueue` is the round an
  active campaign walks — every seated player in join order, each followed by the
  owning DM, so a two-player table joined A then B reads
  `["player-a", "dm", "player-b", "dm"]`. A lobby campaign has no round yet and
  reports an empty list (never `null`), since the party can still change. This is the
  first play route open to *both* seats: the owning DM and any member of the
  party may read it, and every other authenticated identity — including a DM who
  owns a different table — gets 403. Missing or malformed credentials are 401 and
  an unknown campaign is 404, in that order, so authorization is only ever
  decided about a campaign that exists.

- **A player's own turn context.** `GET /v1/play/campaigns/{id}/my-turn` returns
  `playMyTurnResponse` — `{campaign_id, is_my_turn, current_actor, character,
  recent_events}` — for one seated player. It is the mirror image of `/turn`: the
  DM has no view here at all (403, since only `"player"` actors hold a seat), and
  a player sees only *their own* `character` (`{id, name}`, the seat they joined
  with), never another player's. An authenticated player without a seat in this
  campaign is 403, an unknown campaign is 404, and missing credentials are 401.
  `is_my_turn` is true only when the campaign is `active` *and* `current_actor` is
  the caller, so a lobby campaign is nobody's turn. `recent_events` is the tail of
  the shared narration log — at most `playRecentEventLimit` (10) entries, still in
  told order (`recentPlayEvents` queries newest-first and flips), always a list
  and never `null`. Nothing DM-private is exposed: the log rows every seat can
  already read are the only campaign documents this route touches.

- **Taking a turn.** `POST /v1/play/campaigns/{id}/actions` (`{type, text}`) is
  the active player's half of the round and
  `POST /v1/play/campaigns/{id}/resolutions` (`{text}`) is the owning DM's
  answer. Both append to the same log — kinds `action` and `resolution` — and
  both move `current_actor`: an action hands the clock to the DM (`next_actor`
  is `"dm"`), a resolution hands it to the next seat in join order and
  increments `turn_number`, so the response carries `{..., next_actor,
  turn_number}`. Turn *n* belongs to the player at position `(n-1) % party
  size`, which is why resolving turn 1 at a table joined A then B advances to B
  and the round wraps back to A after the last seat. Wrong-seat refusals are
  409, not 403, on both routes: a waiting player, and a DM whose clock is on a
  player, would each succeed at another moment, and a player never resolves at
  any moment (409 by the same reading). Only an actor with no seat at this table
  is 403; an unstarted campaign has no turn to take or resolve (409).

## Extending the codebase safely

1. **Add a file per new grouping**, and register its routes in `newRouter` in
   `main.go` under a comment naming that file. Do not scatter route
   registration.
2. **Reuse the `httpx.go` helpers** rather than hand-rolling a guard:
   `requireMethod`, `decodeBody`, `requireField`, `requirePathValue`,
   `writeJSON`, `writeError`, `writeStorageFailure`, `writeStorageError`.
3. **Model optional JSON fields as pointers** (`*int`, `*string`). That is the
   only way to distinguish "absent" from "zero", which several endpoints depend
   on. `flexString` (`encounters.go`) additionally accepts a JSON number where a
   string is expected, and rejects `null`.
4. **Keep responses deterministic.** Never iterate a Go map to produce ordered
   output — iterate a slice, as `saveSessionState` does. Sorts need a total
   order: `sortInitiative` falls back to name so equal scores cannot swap. There
   is no `math/rand`, clock, or UUID in any response body, and it should stay
   that way.
5. **Hold `storeMu` for the whole read-modify-write**, taking it before the
   first query and releasing it after the last write. Helpers that assume the
   caller already holds it (`requireCampaign`, `nextPosition`) say so in their
   doc comment.
6. **Preserve wire strings exactly.** Error messages and status codes are
   asserted by the evaluator. In particular the two generic 500 messages differ
   by endpoint family — compendium, campaign and DM endpoints say
   `"storage failure"`; auth and combat say `"storage error"` — and
   `POST /v1/storage/reset` has its own `"storage reset failed"`. Do not unify
   them.
7. **Add ordered child rows with a `position` column** and read them back with
   `ORDER BY position`. Extending the schema means adding the table to
   `schemaDDL` and the matching `DROP TABLE` to `resetStorage`'s list, children
   before parents. `schemaVersion` stays **1**: it is a wire value the
   evaluator's storage-status test asserts, not an internal migration counter —
   this program never migrates, it drops and recreates.
8. **Interpolate table names only from literals in the same file** — never from
   request data. `slugExists`, `nextPosition` and `rowExists` do this and say so;
   all values are bound parameters.

### Testing

- `rules_test.go` unit-tests the pure helpers — ability/proficiency math, dice
  parsing, CR lookup, XP adjustment and difficulty banding, party thresholds,
  initiative sorting, recap thread extraction, tag decoding, password
  verification. It opens no database and binds no port, so `go test ./...` is
  fast and side-effect free. New pure helpers belong here.
- Handler behavior is covered end to end by `dndeval`. Because its suites are
  cumulative, run the **latest** suite after any change, not just the one for
  the area you touched. Start a fresh server per suite: state does not survive a
  restart, and reusing one process across suites causes false conflicts on
  already-registered usernames and ids.
- `POST /v1/storage/reset` exists for fixtures — it drops and recreates the
  schema in place, so a test can reset without restarting the process.
- `gofmt` and `go vet ./...` are both clean; keep them that way.
