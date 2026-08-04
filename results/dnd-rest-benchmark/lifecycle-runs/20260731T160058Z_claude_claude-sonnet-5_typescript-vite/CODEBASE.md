# CODEBASE.md

A D&D-flavored REST API implemented as a Vite dev-server middleware plugin.
There is no separate HTTP server process — Vite's own dev server (`connect`
under the hood) is the server, and the API is one more piece of middleware
registered on it.

## Start and verify

```bash
PORT=8080 ./run.sh
```

`run.sh` runs `vite --host 127.0.0.1 --port "$PORT"` in the foreground. Vite
picks up `vite.config.ts`, which registers the API plugin.

Verify the server is up:

```bash
curl http://127.0.0.1:8080/health
# {"ok":true}

curl http://127.0.0.1:8080/v1/storage/status
# {"driver":"sqlite","schema_version":1,"initialized":true}
```

The benchmark's evaluator CLI (`dndeval run --base-url http://127.0.0.1:8080
--suite <name>`) exercises the full contract; `dndeval list` shows available
suites. Suites are cumulative — a later checkpoint's suite re-runs every
endpoint from earlier checkpoints plus its own, so the highest-numbered suite
you have a spec for is the one that matters most. Suites assume they run
against either a fresh server or one whose `/v1/storage/reset` endpoint has
just been called — most suites share fixture IDs (e.g. campaign id `camp-1`,
combat session id `sess-1`, usernames `dm`/`player-a`/`player-b`), so running
two suites back-to-back on the same live server without a reset in between
will produce spurious `409 already exists` conflicts.

## Entry point and major modules

- **`vite.config.ts`** — the actual entry point. It's a normal Vite config
  whose only customization is registering `dndApiPlugin()`.
- **`src/api-plugin.ts`** — the Vite plugin. `configureServer` initializes
  storage once at boot (`initStorage()`) and installs one Connect middleware
  function that does routing: match `(method, path)` against a route table,
  read/parse a JSON body if the route needs one, call the matching domain
  handler, and write the handler's `{status, body}` result back as JSON. It
  contains no domain logic — only HTTP mechanics (path/method matching, body
  parsing, response serialization, `Authorization` header pass-through) and a
  handful of small route tables, one per routing shape (see below).
- **`src/db.ts`** — opens the SQLite database (`node:sqlite`'s `DatabaseSync`,
  no external driver) at `<project root>/game.db`, creates the schema on first
  use (`createSchema`), migrates older on-disk schemas forward in place
  (`migrateSchema`, additive `ALTER TABLE ... ADD COLUMN`s only), and exposes
  `resetStorage()` (drop + recreate all tables) plus
  `isInitialized()`/`SCHEMA_VERSION` for the storage-status endpoint.
- **`src/types.ts`** — the two shared shapes every handler uses: `JsonValue`
  (a loosely-typed JSON object, `Record<string, unknown>`) and `ApiResult`
  (`{status, body}`).
- **`src/validation.ts`** — `isValidIntInRange`, the one validator reused
  across multiple domains (levels, scores, counts are all bounded integers).
- **`src/domain/*.ts`** — one file per domain area (see below). Each file
  owns its request validation, business rules, and any persistence calls for
  that domain. `api-plugin.ts` imports handler functions from these files; it
  never touches SQLite or in-memory state directly.
- **`src/domain/play/`** — the authenticated live-play surface, split across
  five files by concern (`campaign-turns.ts`, `scenes.ts`, `locations.ts`,
  `combat.ts`, `characters.ts`) plus a `shared.ts` of common lookups/helpers
  and an `index.ts` barrel that re-exports every handler. `api-plugin.ts`
  imports from `./domain/play/index.ts` and never reaches into the
  individual files directly — see below.
- **`src/main.ts`** — unused by the server; a leftover placeholder script.

## State, persistence, and request routing

**Persistence model:** SQLite (`game.db`) is the single source of truth for
all durable state: users, combat sessions/conditions, monsters, items,
campaigns and their characters/events/quests/factions/NPCs/inventory/crafting
projects/sessions, and the play-mode tables (`play_campaigns`,
`play_campaign_members`, `play_campaign_events`). Two domains — `auth`
(users) and `combat` (sessions/conditions) — additionally keep an in-memory
`Map` cache for fast repeated lookups (e.g. every combat turn advance). Every
mutation to a cached domain writes through to SQLite immediately
(`persistUser`, `persistCombatSession`, `persistCombatConditions`), and
`initStorage()` rehydrates both caches from SQLite at boot
(`loadUsersFromDb`, `loadCombatSessionsFromDb`). Every other domain
(compendium, campaigns, quests, npcs, inventory, crafting, sessions, audit,
analytics, play) has no hot in-memory path and just queries SQLite directly
on every request — there's no cache to keep in sync.

`/v1/storage/reset` drops and recreates all tables *and* clears both
in-memory caches, so it fully resets server state, not just the database
file.

**Request routing:** `api-plugin.ts`'s middleware matches on `(method, path)`
in this order:
1. Three fixed routes are handled first: `GET /health`, `GET
   /v1/storage/status`, `POST /v1/storage/reset`.
2. `POST`: exact-path routes requiring an `Authorization` header
   (`AUTHED_JSON_ROUTES`, currently just `/v1/play/campaigns`), then
   exact-path unauthenticated routes (`JSON_ROUTES` — every stateless
   computation endpoint plus every simple "create a top-level resource"
   endpoint), then authed routes with one `:param`
   (`AUTHED_JSON_PARAM_ROUTES`, the rest of `/v1/play/*`), then
   unauthenticated routes with one `:param` (`JSON_PARAM_ROUTES`), then
   routes with two `:param`s (`JSON_TWO_PARAM_ROUTES`), then the
   no-body special case `POST /v1/combat/sessions/:id/advance`.
3. `PUT`: authed routes with one `:param` (`AUTHED_JSON_PUT_PARAM_ROUTES`,
   currently just `/v1/play/campaigns/:id/document`).
4. `GET`: authed routes with one `:param` (`AUTHED_GET_PARAM_ROUTES`, the
   read side of `/v1/play/*`), then unauthenticated routes with one
   `:param` (`GET_PARAM_ROUTES`, e.g. fetch monster/item/campaign state).
5. Anything unmatched falls through to `next()` (Vite's normal static/HTML
   handling).

For every route table, the captured path segment(s) are URL-decoded before
being passed to the handler. "Authed" routes additionally forward
`req.headers.authorization` as the handler's first argument, ahead of any
path params and the body.

If a route expecting a body receives an unparsable JSON payload, the
middleware responds `400 {"error":"invalid JSON body"}` before the handler
ever runs.

## API/domain groupings

| Domain module | Endpoints | Notes |
|---|---|---|
| `domain/dice.ts` | `POST /v1/dice/stats`, `/v1/checks/ability` | Pure math, no state. |
| `domain/encounters.ts` | `POST /v1/encounters/adjusted-xp` | DMG-style adjusted-XP/difficulty math; reused by `campaigns.encounterBuilder`. |
| `domain/character.ts` | `POST /v1/characters/ability-modifier`, `/proficiency`, `/derived-stats` | Pure math, no state. |
| `domain/combat.ts` | `POST /v1/initiative/order`, `/v1/combat/sessions`, `/v1/combat/sessions/:id/conditions`, `/v1/combat/sessions/:id/advance` | Owns the `combatSessions` in-memory map + its SQLite mirror. |
| `domain/auth.ts` | `POST /v1/auth/register`, `/login` | Owns the `users` in-memory map + its SQLite mirror; scrypt password hashing with timing-safe comparison. `getUserRole` is also called by `domain/play/shared.ts` to resolve a bearer token's role. |
| `domain/phb.ts` | `POST /v1/phb/spell-slots`, `/rests/long`, `/equipment-load` | Pure rules math, no state. |
| `domain/compendium.ts` | `POST`/`GET /v1/compendium/monsters[/:slug]`, `/items[/:slug]` | Reads/writes SQLite directly, no cache. |
| `domain/campaigns.ts` | `POST /v1/campaigns`, `POST`/`GET /v1/campaigns/:id/characters`, `/events`, `/state`, plus DM tools `POST /v1/dm/encounter-builder`, `/loot-parcel`, `/session-recap` | Reads/writes SQLite directly; `encounterBuilder` delegates its XP math to `encounters.adjustedXp`. |
| `domain/quests.ts` | `POST /v1/campaigns/:id/quests`, `/quests/:quest_id/progress`, `GET /quests/summary` | Per-campaign quest tracking. |
| `domain/npcs.ts` | `POST /v1/campaigns/:id/factions`, `/npcs`, `GET /relationships` | Faction/NPC roster and relationship scoring. |
| `domain/inventory.ts` | `POST /v1/campaigns/:id/inventory`, `/characters/:character_id/equipment`, `GET /inventory/summary` | Character inventory and equipment assignment. |
| `domain/crafting.ts` | `POST /v1/campaigns/:id/downtime/crafting`, `/downtime/crafting/:project_id/advance` | Downtime crafting-project progress. |
| `domain/sessions.ts` | `POST /v1/campaigns/:id/sessions`, `/sessions/:session_id/attendance`, `GET /sessions/next` | Session scheduling and attendance. |
| `domain/audit.ts` | `GET /v1/campaigns/:id/audit`, `/export` | Read-only campaign audit trail / export. |
| `domain/analytics.ts` | `GET /v1/campaigns/:id/analytics/summary`, `POST /analytics/risk-report` | Aggregate reporting over campaign state. |
| `domain/play/` | `POST /v1/play/campaigns`, `/:id/members`, `/:id/start`, `/:id/narrations`, `/:id/actions`, `/:id/resolutions`, `/:id/turn/nudge`, `/:id/scenes`, `/:id/locations`, `/:id/locations/:from_id/connections`, `/:id/turn/travel`, `/:id/turn/rest`, `/:id/encounters`, `/:id/encounters/:enc_id/monsters`, `/:id/encounters/:enc_id/combatants`, `/:id/encounters/:enc_id/actions`, `/:id/encounters/:enc_id/damage`, `/:id/encounters/:enc_id/heal`, `/:id/encounters/:enc_id/conditions`, `/:id/encounters/:enc_id/turn/delay`, `/:id/encounters/:enc_id/turn/ready`, `/:id/encounters/:enc_id/rewards`, `/:id/characters/:char_id/damage`, `/death-saves`, `/claim`, `/transfer`, `/build`, `/level-up`, `/skill-check`; `PUT /:id/document`; `GET /:id/turn`, `/:id/my-turn`, `/:id/gm/status`, `/:id/document`, `/:id/scenes/current`, `/:id/locations/:loc_id/travel`, `/:id/encounters/:enc_id/turn`, `/:id/encounters/:enc_id/status`, `/:id/characters/:char_id/status`, `/:id/characters/:char_id/owner`; `POST /:id/scenes/:scene_id/enter`, `/close`, `/:id/encounters/:enc_id/turn/advance`, `/close`, `/end`; `DELETE /:id/encounters/:enc_id/monsters/:monster_id`, `/:id/encounters/:enc_id/combatants/:member` | The authenticated live-play surface — see below. |
| `domain/storage.ts` | `GET /v1/storage/status`, `POST /v1/storage/reset` | Orchestrates `db.ts` plus the auth/combat cache lifecycle. |

### The play-mode surface (`domain/play/`)

`domain/play/` is the only domain that requires authentication, and the only
one split across multiple files — it's by far the largest surface (roughly
sixty handlers). Every exported handler takes the raw `Authorization` header
as its first argument and calls the private `authenticate()` helper (in
`shared.ts`), which expects `Bearer session-<username>` and resolves a role
via `auth.getUserRole` (falling back to `dm` for the literal username `dm`,
`player` otherwise — this fallback exists so play-mode can be exercised
without a prior `/v1/auth/register` call). The five handler files split the
surface by concern:

- **`campaign-turns.ts`** — campaign create/join/start, whose-turn-is-it
  queries (`getPlayCampaignTurn`, `getPlayerTurnContext`, `getGmStatus`),
  nudging, player actions, DM resolutions, and the campaign document
  (public `story` + owner-only `dm_notes`).
- **`scenes.ts`** — scene create/enter/close and reading the current scene.
- **`locations.ts`** — the location graph (create location, create
  connection, list travel options) and the two turn-consuming exploration
  actions, travel and rest.
- **`combat.ts`** — encounter create/close/end, initiative order and
  turn advance/delay/ready, conditions, party-combatant binding, monster
  add/remove/damage/heal, combat actions, and encounter rewards.
- **`characters.ts`** — character HP/damage, death saves, ownership
  (claim/transfer — distinct from campaign membership, see the file's
  header comment), building a character from race/class/background/
  abilities, leveling up, and skill checks.

All five import their row lookups and cross-cutting helpers from
**`shared.ts`** rather than re-deriving them:

- `findCampaign(db, id)` / `findScene(...)` / `findLocation(...)` /
  `findEncounter(...)` — load a row or return the domain's canonical 404
  `ApiResult`.
- `requireParticipant(db, campaign, actor, message)` — returns `null` if the
  actor is the campaign owner or a roster member, otherwise a 403
  `ApiResult`. Several endpoints (turn state, turn context, action
  submission, campaign document) are visible to "owner or member" and use
  this instead of re-checking membership inline.
- `nextSequence` / `insertEvent` / `recentEvents` — the append-only
  `play_campaign_events` log (narrations, player actions, DM resolutions,
  combat actions) is written and read through these three functions
  everywhere, so the sequence-numbering invariant (monotonic per campaign,
  starting at 1) lives in one place.
- `requireNonEmptyString(value, field)` — the repeated "must be a non-empty
  string or 400" body-field check.
- `buildInitiativeOrder` / `combatantKey` / `parseConditions` /
  `encounterHasTarget` / `activeCombatantBody` / `findMonsterTarget` — the
  combat-turn math shared by every `combat.ts` handler that touches
  initiative order or per-combatant conditions.

Each handler still owns its own authorization *decision* (who may call it,
and under what campaign/turn state) inline — only the mechanical lookups are
shared. Turn progression is purely event-driven: a player action, travel, or
rest always hands the turn to the DM (`campaign.owner`), and a DM resolution
advances `current_actor` to the next campaign member after whoever's action
it's resolving (falling back to the first member if there's no prior
action). The "nudge" and "overdue" concepts (`turn/nudge`, `overdue` in `GET
.../turn`) are counted in nudges, not wall-clock time — see the
`TURN_DEADLINE_NUDGES` comment in `shared.ts`.

## Conventions for safely extending and testing

- **Add a new stateless or unauthenticated endpoint:** write a `(body:
  JsonValue) => ApiResult` function in the relevant `domain/*.ts` (or a new
  domain file if it doesn't fit an existing one), then register its path in
  `JSON_ROUTES` in `api-plugin.ts`. For one or two path parameters, use the
  `(param: string, body: JsonValue) => ApiResult` / two-param shape and
  register it in `JSON_PARAM_ROUTES` / `JSON_TWO_PARAM_ROUTES` (or
  `GET_PARAM_ROUTES` for a GET with no body). No other wiring needed.
- **Add a new authenticated (play-mode) endpoint:** follow the pattern in
  `domain/play/` — first argument is `authHeader: string | undefined`, call
  `authenticate()`/`isActor()` first thing, reuse `findCampaign`/
  `requireParticipant`/`nextSequence`/`insertEvent` (all from `shared.ts`)
  where they fit rather than re-querying inline. Add the handler to whichever
  of the five files matches its concern (or `shared.ts` for a lookup reused
  by more than one of them), then export it — `index.ts`'s `export *`
  barrels pick it up automatically, so `api-plugin.ts`'s `from
  './domain/play/index.ts'` import doesn't need touching. Finally register
  the path in `AUTHED_JSON_ROUTES` (exact path), `AUTHED_JSON_PARAM_ROUTES`
  (`POST` with one param), `AUTHED_JSON_PUT_PARAM_ROUTES` (`PUT` with one
  param), or `AUTHED_GET_PARAM_ROUTES` (`GET` with one param) in
  `api-plugin.ts`.
- **Validation style:** every handler validates its own input inline and
  returns `{status: 400, body: {error: "..."}}` on the first invalid field —
  don't introduce a schema library or centralize validation; the existing
  handlers are the pattern to follow. Reuse `isValidIntInRange` from
  `src/validation.ts` for bounded-integer fields, and `requireNonEmptyString`
  from `domain/play/shared.ts` for non-empty-string body fields in that
  domain.
- **Adding persisted state:** add a table in `db.ts`'s `createSchema` (and to
  the matching `DROP TABLE` list in `resetStorage`), then read/write it via
  `getDb()` in your domain module. Only add an in-memory cache (following the
  `auth.ts`/`combat.ts` pattern — a module-level `Map`, a `persist*` write-through
  helper, a `load*FromDb` rehydration function called from
  `storage.initStorage()`, and a `clear*` function called from
  `storage.resetStorageHandler()`) if the endpoint is hot enough to need it;
  otherwise query SQLite directly like `compendium.ts`/`campaigns.ts` do.
  Adding a column to an existing table needs a matching `ALTER TABLE`
  guarded by a `PRAGMA table_info` check in `db.ts`'s `migrateSchema`, so a
  `game.db` created by an older checkpoint still opens cleanly.
- **`node:sqlite` row casts:** `StatementSync#all()`/`#get()` return
  `Record<string, SQLOutputValue>`. TypeScript's `strict` mode allows casting
  that directly to a plain object type literal (`as { foo: string }` or `as {
  foo: string }[]`) and to a single named `type` alias, but an array cast
  through a named `interface` (e.g. `as SomeInterface[]`) fails with TS2352
  ("neither type sufficiently overlaps"). Use `type`, not `interface`, for
  any row shape you intend to cast as an array; the existing domain files
  additionally use `as unknown as X[]` in a few older spots — either style is
  fine, but prefer the plain `type` alias for new code since it needs no
  `unknown` detour.
- **Testing:** there is no unit test suite in this repo; correctness is
  verified against the `dndeval` benchmark CLI. Start the server, then run
  `dndeval run --base-url http://127.0.0.1:<port> --suite <suite>` (see
  `dndeval list` for suite names). Restart the server (or call `POST
  /v1/storage/reset`) between suite runs sharing fixture IDs to avoid
  `409`/`404` conflicts unrelated to your change. Run the highest-numbered
  suite you have a spec for — it's cumulative and is the one to check after
  any change.
- **Behavioral compatibility:** endpoints, status codes, response shapes, and
  validation rules are a cross-checkpoint contract. Don't change them without
  updating the benchmark suites that assert on them.
