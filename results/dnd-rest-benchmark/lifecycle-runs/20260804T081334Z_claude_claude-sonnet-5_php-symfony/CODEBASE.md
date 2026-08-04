# CODEBASE.md

A D&D-flavored REST API implemented in PHP 8.5 using Symfony's
`http-foundation` (request/response objects) and `routing` (URL matching)
components, backed by SQLite. No framework kernel/DI container is used —
this is a small, hand-wired application.

## Starting and verifying the server

```bash
composer install        # only needed once, or after editing composer.json
PORT=8080 ./run.sh       # starts the server in the foreground on 127.0.0.1:$PORT
```

`run.sh` deletes any existing `game.db*` files before starting, so every run
begins from a fresh, empty database (see "State and persistence" below).

Verify it's up:

```bash
curl http://127.0.0.1:8080/health
# {"ok":true}
```

## Entry point and major modules

**`index.php`** is the only script the web server executes. It:
1. loads the Composer autoloader,
2. ensures the SQLite schema exists (`App\Storage\Database::initSchema`),
3. builds a `Request` from PHP superglobals and hands it to `App\Http\Kernel`,
4. sends the resulting `JsonResponse`.

Everything else lives under `src/`, organized by domain (PSR-4 autoloaded
under the `App\` namespace):

| Namespace | Responsibility |
|---|---|
| `App\Http` | Route table (`RouteFactory`) and request dispatch (`Kernel`) |
| `App\Support` | Cross-cutting helpers: JSON error/body helpers (`Json`), input-shape checks (`Validators`) |
| `App\Storage` | SQLite connection + schema (`Database`), generic JSON-document read-modify-write helper (`KvStore`), `/v1/storage/*` handlers |
| `App\Health` | `/health` |
| `App\Dice` | Stateless dice/probability math: `/v1/dice/stats`, `/v1/checks/ability`, `/v1/encounters/adjusted-xp`, `/v1/initiative/order` |
| `App\Characters` | Ability-score/proficiency/derived-stat math: `/v1/characters/*` |
| `App\Combat` | Initiative-order combat sessions: `/v1/combat/sessions/*` |
| `App\Auth` | Registration/login (`AuthController`) and Bearer-token resolution for protected routes (`SessionAuth`): `/v1/auth/*` |
| `App\Compendium` | Monster/item reference data: `/v1/compendium/*` |
| `App\Campaign` | Campaign roster/quest/faction/NPC records: `/v1/campaigns/*` (relational) |
| `App\Inventory` | Campaign inventory items and character equipment: `/v1/campaigns/{id}/inventory*`, `.../equipment` |
| `App\Downtime` | Downtime crafting projects: `/v1/campaigns/{id}/downtime/crafting/*` |
| `App\Session` | Session scheduling and attendance: `/v1/campaigns/{id}/sessions/*` |
| `App\Audit` | Campaign audit log and full-state export: `/v1/campaigns/{id}/audit`, `.../export` |
| `App\Analytics` | Campaign analytics summary and DM risk report: `/v1/campaigns/{id}/analytics/*` |
| `App\Play` | Authenticated live-play surface (lobby, turn order, narration, resolution, shared story document): `/v1/play/campaigns/*` (kv_store) |
| `App\PhbRules` | Standalone rule calculators: `/v1/phb/*` |
| `App\DmTools` | DM prep tools that read campaign/compendium data: `/v1/dm/*` |
| `App\Encounters` | `EncounterMath`: DMG encounter-difficulty tables shared by `App\Dice` (adjusted-xp) and `App\DmTools` (encounter-builder) |

Each domain namespace has one `*Controller` class holding its HTTP handlers
(one public method per endpoint, named after the action) plus, where useful,
a small `*Math`/table class for pure calculation logic the controller
delegates to.

`App\Campaign` and `App\Play` both model "a campaign" but are deliberately
separate and use different storage: `App\Campaign` is the relational roster
record (name/DM/characters/quests/factions/NPCs, looked up individually),
while `App\Play` is the ephemeral live-play session for that campaign
(lobby → active, turn order, narration/action/resolution event log, shared
story document), gated behind `SessionAuth` and stored as one JSON document
per campaign in `kv_store`. They intentionally do not share an id space or
cross-reference each other's records.

## State, persistence, and request routing

**Persistence** is SQLite (`game.db` in the project root, WAL mode). Two
shapes of state coexist in the same database:

- **Relational tables** for records that are looked up individually or
  listed: `monsters`, `items`, `campaigns`, `campaign_characters`,
  `campaign_events`, `campaign_quests`, `campaign_factions`,
  `campaign_npcs`, `campaign_inventory`, `campaign_equipment`,
  `campaign_crafting`, `campaign_sessions`, plus `schema_meta` for the
  `/v1/storage/status` endpoint. Controllers talk to these directly via
  `PDO` (`App\Storage\Database::connection()`).
- **A generic `kv_store` table** (`key TEXT PRIMARY KEY, value TEXT`) for
  state that's always read and written as one JSON document and never
  queried by anything but its key: combat sessions (key `combat_sessions`,
  one JSON blob holding all sessions keyed by id), user accounts (key
  `users`, one JSON blob keyed by username), and live-play campaigns (key
  `play_campaigns`, one JSON blob holding all `App\Play` campaigns keyed
  by id). `App\Storage\KvStore::withState(key, default, fn)` wraps the
  read → mutate → write cycle in a SQLite `BEGIN IMMEDIATE` transaction so
  concurrent requests against the same key serialize instead of racing;
  `$fn` receives the decoded array by reference and its return value
  (typically a `JsonResponse`) is passed back to the caller.

`App\Storage\Database::initSchema()` creates every table (idempotently, via
`CREATE TABLE IF NOT EXISTS`) and seeds the `combat_sessions`/`users`
`kv_store` rows on every request. `resetSchema()` (used by
`POST /v1/storage/reset`) truncates every relational table and every
`kv_store` document except `users` (accounts are identity state, not
campaign content — combat sessions and play campaigns are wiped like
everything else), then re-seeds.

**Routing** uses `symfony/routing`: `App\Http\RouteFactory::build()` returns
a `RouteCollection` where each `Route` carries three custom defaults —
`_controller` (a `[$controllerInstance, 'method']` callable), `_needsBody`
(whether the JSON request body should be parsed and passed as the
callable's first argument), and `_needsAuth` (whether the `Request` itself
should be passed as the callable's first argument, ahead of the body, for
`App\Auth\SessionAuth::authenticate()` to resolve inside the handler — used
by every `App\Play` route). `App\Http\Kernel::handle()` matches the request
with `UrlMatcher`, parses the body when required (returning
`{"error":"invalid json"}` with 400 if it isn't valid JSON), and invokes the
controller with the request (if `_needsAuth`), then the body (if
`_needsBody`), then any path parameters (e.g. `{id}`, `{slug}`,
`{campaignId}`) in match order. A request that matches no route, or matches
a path with the wrong HTTP method, is treated identically:
`{"error":"not found"}` with 404 — the API never surfaces a distinct 405.

## API/domain groupings

- **Dice & checks** (`App\Dice`) — dice expression stats, ability checks,
  adjusted-XP difficulty, initiative ordering. Stateless.
- **Characters** (`App\Characters`) — ability modifiers, proficiency bonus,
  derived stats (HP/AC). Stateless.
- **Combat** (`App\Combat`) — create a combat session from a list of
  combatants, apply conditions to a combatant, advance to the next turn
  (round increments and condition durations tick down on wraparound).
  Persisted in `kv_store`.
- **Auth** (`App\Auth`) — register (bcrypt-hashed password via
  `password_hash`/`password_verify`) and login (returns a `session-<username>`
  token). Persisted in `kv_store`.
- **Compendium** (`App\Compendium`) — create/fetch monsters and items by
  slug. Persisted in relational tables.
- **Campaign** (`App\Campaign`) — create a campaign, add characters/events/
  quests/factions/NPCs to it, fetch aggregate state (roster + event count),
  quest and faction/NPC-relationship summaries. Persisted in relational
  tables.
- **Inventory** (`App\Inventory`) — add campaign inventory items, assign
  equipment to a character, summarize inventory. Persisted in relational
  tables.
- **Downtime** (`App\Downtime`) — create and advance downtime crafting
  projects. Persisted in relational tables.
- **Session** (`App\Session`) — schedule sessions, record attendance, fetch
  the next upcoming session. Persisted in relational tables.
- **Audit** (`App\Audit`) — chronological campaign audit log and a full
  campaign-state export. Read-only over relational tables.
- **Analytics** (`App\Analytics`) — campaign analytics summary and a DM
  risk report. Read-only over relational tables.
- **Play** (`App\Play`) — the authenticated live-play surface: create/join
  a campaign lobby, start it, add DM narration, submit and resolve a
  player's turn, nudge the current actor, check whose turn it is, and
  read/write a shared story document (players see `story` only; the owner
  also sees `dm_notes`). Every handler authenticates via
  `App\Auth\SessionAuth` first (401 if the Bearer token is missing/
  malformed) and then applies its own ownership/membership/role check (403).
  Persisted in `kv_store`, independent of the `App\Campaign` relational
  records — see the note above.
- **PHB rules** (`App\PhbRules`) — spell slots (wizard only), long rest
  recovery, equipment carry capacity. Stateless.
- **DM tools** (`App\DmTools`) — encounter builder (difficulty for a
  campaign's party against a set of compendium monsters), loot parcels by
  tier, session recap (most recent event summary + canned open threads).
  Reads campaign/compendium tables; stateless otherwise.
- **Storage** (`App\Storage`) — schema status and full reset, for test
  isolation.

## Conventions for extending and testing safely

- **Preserve the handler shape.** Every controller method returns a
  `Symfony\Component\HttpFoundation\JsonResponse`; validation failures
  return `App\Support\Json::error($message, $status = 400)`. Follow the
  existing pattern of validating all fields up front and returning the
  first applicable error before touching the database.
- **Adding an endpoint:** write the handler method on the appropriate
  controller (or a new one, for a new domain), then register it in
  `App\Http\RouteFactory::build()` with the right HTTP method, path,
  and `_needsBody` flag. Path parameters become extra positional
  arguments to the handler, in the order Symfony's matcher returns them
  (single-parameter routes are unambiguous; keep new routes to at most
  one or two parameters to avoid relying on match order).
  Wrong-method/unmatched-path requests fall through to the shared
  `{"error":"not found"}` 404 automatically — no per-route handling needed.
- **Shared calculation tables** (challenge-rating XP, level thresholds,
  encounter multipliers) live in `App\Encounters\EncounterMath` because two
  independent endpoints need them; keep genuinely single-endpoint tables
  (spell slots, loot parcels, session-recap hooks) private to their
  controller instead of over-extracting.
- **New document-shaped state** (state that's always read/written as a
  whole and keyed by one id) should go through `App\Storage\KvStore`
  rather than a bespoke table, for the same transactional safety combat
  sessions, users, and play campaigns get.
- **Factor out repeated per-handler boilerplate as private static helpers**
  on the controller, not as free functions or a shared base class — see
  `CampaignController::rowExists()` (existence checks before insert) and
  `PlayController`'s `requireActor()`/`withCampaigns()`/`isOwner()`/
  `isMember()`/`isParticipant()`/`findMember()` (auth, KV read-modify-write,
  and ownership/membership checks). Keep each helper name specific enough
  that a caller doesn't need to read its body to know what it checks.
- **Testing:** there's no automated test suite in this repo; behavior is
  verified externally via the cumulative `dm-tools` benchmark evaluator
  (see `evaluations/` and `shots/` for prior runs and their expected
  request/response fixtures). When changing a handler, manually exercise it
  with `curl` against a locally running `./run.sh` instance and confirm the
  response body, status code, and any persisted state are unchanged unless
  the change was explicitly requested. `POST /v1/storage/reset` gives a
  clean slate between manual test runs without restarting the server.
