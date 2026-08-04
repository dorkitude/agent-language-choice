# dm-tools codebase

A small D&D-5e-flavored REST API built on Node's built-in `node:http` server
and `node:sqlite` — no frameworks, no third-party dependencies.

## Start and verify

```bash
./run.sh                 # starts the server in the foreground on $PORT (127.0.0.1)
```

`run.sh` just runs `node server.js`; `PORT` must be set in the environment.

Verify it's up:

```bash
curl -s http://127.0.0.1:$PORT/health                  # {"ok":true}
curl -s http://127.0.0.1:$PORT/v1/storage/status        # {"driver":"sqlite","schema_version":1,"initialized":true}
```

No build step and no test runner are wired up; verification is done by
exercising the HTTP API directly (see "Testing" below).

## Entry point and major modules

- **`server.js`** — the entry point. Builds the router, registers every
  route group, wraps request dispatch in a try/catch that returns
  `500 {"error":"internal error"}` on unexpected throws, and calls
  `server.listen(PORT, '127.0.0.1')`.
- **`lib/router.js`** — a minimal method+path router. Routes are registered
  with `router.get(pattern, handler)` / `router.post(pattern, handler)` /
  `router.put(pattern, handler)` / `router.delete(pattern, handler)` and
  matched in registration order (first match wins, matching the original
  if-chain's semantics). `pattern` is normally a `"/foo/:id/bar"` string
  (`:name` segments become `[^/]+` capture groups whose decoded values are
  passed to the handler as a `params` object). A route can instead pass a
  raw `RegExp` plus an explicit `paramNames` array — used by sub-action
  routes that must match only a fixed set of literal actions (e.g. the
  combat session's `conditions`/`advance`) and fall through to 404 for
  anything else.
- **`lib/http.js`** — `sendJson(res, status, body)`, `readBody(req)`, and
  `parseJsonBody(req, res)`. `parseJsonBody` reads and `JSON.parse`s the
  body; on malformed JSON it writes the `400 {"error":"invalid JSON"}`
  response itself and returns `{ ok: false }` so route handlers can just
  `if (!body.ok) return;` instead of repeating a try/catch.
- **`lib/db.js`** — owns the single `node:sqlite` `DatabaseSync` connection
  (file `game.db` next to this file), the table DDL, `initSchema()` /
  `resetSchema()`, and `SCHEMA_VERSION`. `dbState.initialized` is a mutable
  flag read by `GET /v1/storage/status`.
- **`lib/stores.js`** — one small `{ has, get, set, ... }` wrapper per table
  (`users`, `combatSessions`, `monsters`, `items`, `campaigns`,
  `campaignCharacters`, `campaignEvents`, `campaignQuests`,
  `campaignFactions`, `campaignNpcs`, `campaignInventory`,
  `campaignEquipment`, `campaignCraftingProjects`, `campaignSessions`,
  `playCampaigns`, `playCampaignMembers`, `playCampaignEvents`,
  `playCampaignScenes`, `playCampaignLocations`,
  `playCampaignLocationConnections`, `playCampaignEncounters`). Each record
  is stored as a JSON blob in a `data` column and (de)serialized on the way
  in/out. Three access patterns cover almost every table, and each is
  implemented once as a set of module-private helpers
  (`keyedStore`/`hasById`/`getById`/`setById` for a single id;
  `hasScoped`/`getScoped`/`setScoped`/`listScoped` for `(campaign_id, id)`;
  `ledgerStore` for append-only rows) — individual stores just say which
  table/id column they use. `users` (real columns, not a blob),
  `playCampaignEvents` (caller-assigned sequence numbers instead of
  `rowid` ordering), and `playCampaignLocationConnections` (composite
  `(from_id, to_id)` key, no single `id`) don't fit those shapes and stay
  hand-written.
- **`lib/auth.js`** — `USERNAME_RE`, scrypt-based
  `hashPassword`/`verifyPassword` (`timingSafeEqual` for the comparison),
  and `bearerUsername(req)`, which extracts the username from an
  `Authorization: Bearer session-<username>` header without checking it
  against the `users` store.
- **`lib/dice.js`** — `parseDiceExpression`, parsing `"NdM+K"` notation.
- **`lib/rules.js`** — shared 5e constants/math: `CR_XP`, `LEVEL_THRESHOLDS`
  (only party level 3 is supported), `DIFFICULTY_RECOMMENDATIONS`,
  `countMultiplier` (DMG encounter multiplier by monster count),
  `proficiencyBonus`, and `difficultyForXp`.
- **`lib/combat.js`** — `computeOrder` (initiative sort), `activeSummary`,
  `conditionsSummary` for combat-session bookkeeping.
- **`routes/*.js`** — one file per domain grouping (see below). Each file
  exports a single `registerXRoutes(router)` function called from
  `server.js`.

## State, persistence, and request routing

- All state lives in SQLite (`game.db`), opened synchronously via
  `node:sqlite`'s `DatabaseSync` at process start. There is no in-memory
  cache layer — every request reads/writes the database directly.
- Schema is created with `CREATE TABLE IF NOT EXISTS` on startup
  (`initSchema()` in `lib/db.js`), so restarting the process is safe and
  idempotent. `POST /v1/storage/reset` drops and recreates every table
  (used by tests to get a clean slate).
- Every HTTP request is parsed once in `server.js` (`new URL(req.url, ...)`),
  then handed to `router.dispatch(req, res, url.pathname)`, which finds the
  first registered route whose method and path pattern match and awaits its
  handler. If nothing matches, `server.js` sends `404 {"error":"not found"}`.
  Any handler that throws (including inside `router.dispatch`) is caught by
  `server.js` and turned into `500 {"error":"internal error"}`.
- Route handlers themselves have no shared framework-level validation layer;
  each does its own `typeof`/`Number.isInteger`/regex checks inline before
  touching storage, and returns `400` with a short `{ "error": "..." }`
  message on the first failing check. This is intentional duplication kept
  from the original implementation — see "Extending the codebase" below for
  why it isn't collapsed further.
- **Two independent campaign concepts coexist on purpose**:
  `routes/campaigns.js` (`/v1/campaigns/...`, backed by the `campaigns`
  table) is the older, unauthenticated worldbuilding record — characters,
  events, quests, NPCs, inventory, crafting, sessions, audit/analytics all
  hang off it via `campaignId`. `routes/play.js` (`/v1/play/campaigns/...`,
  backed by the `play_campaigns` table) is a separate, bearer-token-gated
  live turn-taking layer with its own lobby/membership/turn-order state.
  They share no rows; a `play` campaign id and a worldbuilding campaign id
  are unrelated namespaces even if a caller reuses the same string.

## API/domain groupings

Each corresponds to one `routes/*.js` file:

| File | Routes |
| --- | --- |
| `routes/storage.js` | `GET /health`, `GET /v1/storage/status`, `POST /v1/storage/reset` |
| `routes/dice.js` | `POST /v1/dice/stats`, `POST /v1/checks/ability` |
| `routes/encounters.js` | `POST /v1/encounters/adjusted-xp`, `POST /v1/initiative/order` |
| `routes/characters.js` | `POST /v1/characters/ability-modifier`, `POST /v1/characters/proficiency`, `POST /v1/characters/derived-stats` |
| `routes/combat.js` | `POST /v1/combat/sessions`, `POST /v1/combat/sessions/:id/conditions`, `POST /v1/combat/sessions/:id/advance` |
| `routes/auth.js` | `POST /v1/auth/register`, `POST /v1/auth/login` |
| `routes/compendium.js` | `POST /v1/compendium/monsters`, `GET /v1/compendium/monsters/:slug`, `POST /v1/compendium/items`, `GET /v1/compendium/items/:slug` |
| `routes/campaigns.js` | `POST /v1/campaigns`, `POST /v1/campaigns/:id/characters`, `POST /v1/campaigns/:id/events`, `GET /v1/campaigns/:id/state` |
| `routes/phb.js` | `POST /v1/phb/spell-slots`, `POST /v1/phb/rests/long`, `POST /v1/phb/equipment-load` |
| `routes/dm.js` | `POST /v1/dm/encounter-builder`, `POST /v1/dm/loot-parcel`, `POST /v1/dm/session-recap` |
| `routes/quests.js` | `POST /v1/campaigns/:id/quests`, `POST /v1/campaigns/:id/quests/:questId/progress`, `GET /v1/campaigns/:id/quests/summary` |
| `routes/npcs.js` | `POST /v1/campaigns/:id/factions`, `POST /v1/campaigns/:id/npcs`, `GET /v1/campaigns/:id/relationships` |
| `routes/inventory.js` | `POST /v1/campaigns/:id/inventory`, `POST /v1/campaigns/:id/equipment` (sub-action route), `GET /v1/campaigns/:id/inventory/summary` |
| `routes/crafting.js` | `POST /v1/campaigns/:id/downtime/crafting`, `POST /v1/campaigns/:id/downtime/crafting/:projectId/...` (sub-action route) |
| `routes/sessions.js` | `POST /v1/campaigns/:id/sessions`, `POST /v1/campaigns/:id/sessions/...` (sub-action route), `GET /v1/campaigns/:id/sessions/next` |
| `routes/audit.js` | `GET /v1/campaigns/:id/audit`, `GET /v1/campaigns/:id/export` |
| `routes/analytics.js` | `GET /v1/campaigns/:id/analytics/summary`, `POST /v1/campaigns/:id/analytics/risk-report` |
| `routes/play.js` | Lobby & turn order: `POST /v1/play/campaigns`, `POST .../members`, `POST .../start`, `POST .../narrations`, `GET .../turn`, `POST .../turn/nudge`, `GET .../my-turn`, `POST .../actions`, `POST .../resolutions`, `PUT`/`GET .../document`, `GET .../gm/status`. Scenes: `POST .../scenes`, `POST .../scenes/:scene_id/enter`\|`close`, `GET .../scenes/current`. Locations & travel: `POST .../locations`, `POST .../locations/:from_id/connections`, `GET .../locations/:loc_id/travel`, `POST .../turn/travel`, `POST .../turn/rest`. Encounters (combat): `POST .../encounters`, `POST`/`DELETE .../encounters/:encId/monsters(/:monsterId)`, `POST`/`DELETE .../encounters/:encId/combatants(/:member)`, `GET .../encounters/:encId/turn`, `POST .../encounters/:encId/turn/advance`\|`delay`\|`ready`, `POST .../encounters/:encId/conditions`, `GET .../encounters/:encId/status`, `POST .../encounters/:encId/damage`\|`heal`\|`actions`\|`rewards`\|`close`\|`end`. Characters: `POST .../characters/:char_id/damage`\|`death-saves`, `GET .../characters/:char_id/status`\|`owner`, `POST .../characters/:char_id/claim`\|`transfer`\|`build`\|`level-up`\|`skill-check` |

### `routes/play.js` in detail

This is the live-session turn-taking layer (see "Two independent campaign
concepts" above). It's the largest route file by far, covering lobby
management, exploration (scenes/locations/travel/rest), encounter combat,
and per-character sheet/ownership state — all scoped under one play
campaign. Every route starts by calling the file-local
`authenticate(req, res)`, which reads the bearer token and derives a role —
`dm` if the username is literally `"dm"`, `player` otherwise — with no
lookup against the `users` table. Shared helpers used across handlers:

- `requireCampaign(res, id)` — loads the play campaign or sends `404` and
  returns `null`, so handlers can `if (!campaign) return;`.
- `isMember(members, username)` — true if `username` has joined as a party
  member.
- `appendEvent(campaignId, fields)` — assigns the next per-campaign
  sequence number and appends to `playCampaignEvents`; used by the
  narration, action, resolution, travel, and rest routes so none of them
  track sequence numbers by hand.
- `initiativeOrder(encounter)` — derives a deterministic turn order for an
  encounter's combatants (highest initiative first, ties broken by name),
  reusing any explicit `turn_order` a prior delay/ready action pinned so
  that ordering survives across advances.

**Lobby & exploration turn order** is a DM/player ping-pong: submitting an
action hands `current_actor` to the DM (`campaign.owner`), and resolving it
hands it to the next member after whoever last acted (`resolutions` route).
Travel (`turn/travel`) and rest (`turn/rest`) follow the same pattern —
each is only valid for the player currently holding the turn, and each
hands `current_actor` back to the owner afterward. The `document` route
exposes different fields depending on caller: the owner sees `story` and
`dm_notes`, everyone else sees only `story`.

**Scenes** (`scenes*`) are DM-owned checkpoints (`status: 'open'|'closed'`)
that the campaign's `current_scene_id` points at; only one can be open and
current at a time. **Locations** form a directed graph
(`playCampaignLocationConnections`, one row per `(from_id, to_id)` edge
with a `travel_turns` cost); the first location created for a campaign
becomes its `current_location_id` automatically. `turn/travel` only
succeeds along an existing edge from the campaign's current location.

**Encounters** (`encounters*`) are the combat sub-layer: monsters and
member combatants are added to an encounter, initiative is rolled, and
`turn/advance`/`turn/delay`/`turn/ready` step through `initiativeOrder`
while `conditions`, `damage`, `heal`, `actions`, and `rewards` mutate
combatant/member state along the way. Monster combatants carry their own
`hp_current`/`hp_max`; player combatants defer to their
`playCampaignMembers` record, which stays the single source of truth for a
character's hp both in and out of combat. `encounters/:encId/end` restores
`current_actor` to whichever exploration actor held the turn before combat
began (it was never touched while combat was active).

**Characters** (`characters/:char_id/*`) covers per-member sheet state that
isn't specific to a single encounter: standalone damage/death-saving-throw
tracking, ownership (`owner`/`claim`/`transfer` — who controls a given
party member's actions), and character build (`build`/`level-up`/
`skill-check`, layered on the race/background/class tables and
`proficiencyBonus` near the top of this file).

## Conventions for safely extending and testing

- **Adding a route**: pick (or create) the matching `routes/*.js` file, add
  a `router.get`/`router.post`/`router.put` call inside its
  `registerXRoutes`, and (for a new file) call the new register function
  from `server.js`. Keep the `parseJsonBody` → validate → `sendJson` shape
  used everywhere else.
- **Validation duplication is deliberate here**: two nearly-identical party
  threshold loops exist in `routes/encounters.js`
  (`/v1/encounters/adjusted-xp`) and `routes/dm.js`
  (`/v1/dm/encounter-builder`) with a subtle difference — the former does
  `LEVEL_THRESHOLDS[member.level]` (throws → `500` on a non-object party
  member, caught by `server.js`), the latter does
  `LEVEL_THRESHOLDS[member && member.level]` (never throws, always `400` on
  a bad member). This was already true of the original single-file
  implementation. Do not merge these two loops into one shared helper
  without confirming the evaluator suite doesn't depend on that difference.
- **State access**: never query `lib/db.js`'s `db` directly from a route —
  go through the relevant wrapper in `lib/stores.js` so serialization stays
  in one place. Add a new wrapper (and table in `lib/db.js`) for new
  persisted entities. If the new table is keyed by a single id, or by
  `(campaign_id, id)`, or is an append-only ledger, reuse the matching
  helper (`keyedStore` / `hasScoped`+`getScoped`+`setScoped`+`listScoped` /
  `ledgerStore`) instead of hand-writing the SQL again — that's the
  pattern the existing stores follow.
- **Per-file local helpers**: several route files factor out small,
  file-local helpers for repeated lookups/formatting (e.g.
  `routes/play.js`'s `requireCampaign`/`isMember`/`appendEvent`,
  `routes/quests.js`'s `toSummary`). These are intentionally *not*
  centralized in `lib/` — they encode response shapes or invariants
  specific to one route group, and promoting them to a shared module would
  couple unrelated domains for no behavioral benefit. Prefer adding a
  similarly-scoped local helper over reaching for a shared one when the
  logic is specific to a single route file.
- **Testing**: there's no test framework wired in; the evaluator (external
  to this repo) drives the HTTP API directly. To sanity check changes
  locally, start the server (`PORT=8080 ./run.sh`) and hit it with `curl`,
  e.g.:
  ```bash
  curl -s http://127.0.0.1:8080/health
  curl -s -X POST http://127.0.0.1:8080/v1/dice/stats \
    -H 'Content-Type: application/json' -d '{"expression":"2d6+3"}'
  ```
  Use `POST /v1/storage/reset` between manual test runs to clear state
  without restarting the process.
- **Behavior is the contract**: refactor checkpoints in this codebase are
  refactor-only — endpoint paths, status codes, response bodies, and
  validation rules must stay byte-for-byte compatible with the prior
  implementation. Structural changes (new modules, renamed internals,
  extracted helpers) are fine; observable behavior changes are not.
