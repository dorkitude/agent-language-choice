# CODEBASE.md

A D&D 5e-flavored REST API built with Slim 4 (PHP 8.5, `slim/slim` 4.15.2,
`slim/psr7` 1.8.0). It covers dice math, character/encounter rules, combat
session state, auth, a DM-authoring campaign/compendium data layer, and a
separate actor-gated "play" surface that runs a two-player, DM-vs-player
turn rotation — all backed by a single SQLite file.

## Start and verify

```bash
composer install          # first time only, installs vendor/
PORT=8080 ./run.sh         # starts the server in the foreground on 127.0.0.1:$PORT
```

`run.sh` runs PHP's built-in development server (`php -S 127.0.0.1:$PORT index.php`).
The database file defaults to `game.db` next to `index.php`; override it with
the `GAME_DB_FILE` environment variable (used by the test suite to isolate
runs).

Verify the server is up:

```bash
curl http://127.0.0.1:8080/health
# {"ok":true}
```

Exercise a stateful path end-to-end:

```bash
curl -X POST http://127.0.0.1:8080/v1/campaigns \
  -d '{"id":"c1","name":"Test","dm":"kyle"}'
curl http://127.0.0.1:8080/v1/campaigns/c1/state
```

## Entry point and modules

- **`index.php`** — composition root. Boots the Slim `App`, resolves the
  SQLite file path (`GAME_DB_FILE` env var or `game.db`), calls each
  `App\Routes\*Routes::register()` group to attach routes, eagerly connects
  to the database (so schema creation happens before the first request), and
  calls `$app->run()`.
- **`src/Http/Json.php`** — `Json::response()` writes a JSON body with the
  right `Content-Type` and status; `Json::parseBody()` decodes the request
  body, collapsing anything that isn't a JSON object/array to `[]` so route
  handlers can treat missing and malformed input the same way.
- **`src/Http/Auth.php`** — `Auth::actor()` reads the `Authorization: Bearer
  session-<username>` header used by the `/v1/play/*` surface and resolves it
  to `['username' => ..., 'role' => ...]`. The `dm` username is always the DM
  role; every other username is a player. There's no registration or
  password check on this path — it's a lightweight actor identity, distinct
  from `/v1/auth/*` (`AuthRoutes` + `UserRepository`), which does real
  username/password accounts.
- **`src/Rules/`** — pure, side-effect-free D&D 5e math, safe to call
  directly in tests:
  - `Validation.php` — shared field validators (`isIntInRange`, `isSlug`).
  - `Encounters.php` — CR→XP table, per-level XP thresholds, the DMG
    monster-count multiplier, and difficulty banding.
  - `Characters.php` — ability modifier and proficiency bonus formulas.
- **`src/Storage/`** — SQLite access. Every table stores a natural key
  (id/slug/username) plus a `data` column holding the JSON-encoded record;
  this keeps the schema stable while the JSON payload shape evolves.
  - `Database.php` — connection factory (`Database::connect($file)`, memoized
    per-process) and schema management (`initSchema`, `resetSchema`). Table
    definitions live once in the `TABLES` map so create and drop can't drift
    apart.
  - `CombatSessionRepository.php`, `UserRepository.php`,
    `CompendiumRepository.php`, `CampaignRepository.php`,
    `PlayCampaignRepository.php` — one repository per domain area, each a
    thin wrapper around prepared statements against its table(s).
    `CampaignRepository` backs the DM-authoring surface (`/v1/campaigns/*`,
    `/v1/dm/*`, `/v1/campaigns/*/downtime/*`); `PlayCampaignRepository` backs
    the separate actor-gated play surface (`/v1/play/*`) — they model similar
    concepts (campaigns, members/characters, events) but intentionally don't
    share a table or class, since the two surfaces have different auth and
    lifecycle rules.
- **`src/Routes/`** — one class per API grouping; each has a static
  `register(App $app, ?string $dbFile)` that attaches its routes as closures.
  Stateless groups (`CoreRoutes`, `EncounterRoutes`, `CharacterRoutes`,
  `PhbRoutes`) don't need `$dbFile`. Stateful groups (`CombatRoutes`,
  `AuthRoutes`, `StorageRoutes`, `CompendiumRoutes`, `CampaignRoutes`,
  `DmRoutes`, `DowntimeRoutes`, `PlayRoutes`) open a repository per request
  via `Database::connect($dbFile)`. `CampaignRoutes` and `PlayRoutes` each
  factor their repeated "look up the campaign or return 404" (and, for
  `PlayRoutes`, "resolve the actor or return 401") checks into private
  static helpers (`requireCampaign`, `requireActor`, `isOwningDm`) rather
  than duplicating the check inline in every closure — the response bodies
  and status codes are unchanged from inlining them. `PlayRoutes` additionally
  has a `context()` helper that chains `requireActor` + `requireCampaign` into
  one call for the ~40 handlers that need both in that order before any
  route-specific authorization check; the two handlers that must check an
  actor's role *before* looking up the campaign (`POST .../members`,
  `GET .../my-turn`) intentionally don't use it, since folding them in would
  change which error (401/403 vs. 404) wins when both conditions are true.

Autoloading is PSR-4 (`App\` → `src/`) via `composer.json`; run
`composer dump-autoload` after adding new classes under `src/`.

## State, persistence, and request routing

- Storage is SQLite (`game.db` by default), accessed through PDO with
  exceptions enabled. `Database::connect()` memoizes a single PDO instance
  per PHP process/file path and creates all tables (`IF NOT EXISTS`) on first
  connect.
- Every table is a key-value store: a natural primary key plus a `data` TEXT
  column holding `json_encode()`d state. Repositories decode on read and
  encode on write; there's no ORM or migration system, only
  `Database::initSchema()` (idempotent) and `Database::resetSchema()` (drop +
  recreate, used by `POST /v1/storage/reset`).
- Routing is plain Slim: each `*Routes::register()` call adds closures to the
  `$app` instance passed in from `index.php`. There's no middleware stack,
  auth guard, or dependency-injection container — closures pull what they
  need (a repository, a rules class) directly.
- The PHP built-in server (`php -S`) used by `run.sh` handles one request per
  process invocation, so `Database`'s static memoization only matters within
  a single request's lifetime, not across requests.

## API/domain groupings

| Group | Routes file | Endpoints |
|---|---|---|
| Core | `CoreRoutes` | `GET /health`, `POST /v1/dice/stats`, `POST /v1/checks/ability` |
| Encounters | `EncounterRoutes` | `POST /v1/encounters/adjusted-xp`, `POST /v1/initiative/order` |
| Characters | `CharacterRoutes` | `POST /v1/characters/ability-modifier`, `/proficiency`, `/derived-stats` |
| PHB rules | `PhbRoutes` | `POST /v1/phb/spell-slots`, `/rests/long`, `/equipment-load` |
| Combat | `CombatRoutes` | `POST /v1/combat/sessions`, `/{id}/conditions`, `/{id}/advance` |
| Auth | `AuthRoutes` | `POST /v1/auth/register`, `/v1/auth/login` |
| Storage admin | `StorageRoutes` | `GET /v1/storage/status`, `POST /v1/storage/reset` |
| Compendium | `CompendiumRoutes` | `POST`/`GET /v1/compendium/monsters[/{slug}]`, `/items[/{slug}]` |
| Campaigns | `CampaignRoutes` | `POST /v1/campaigns`, `/{id}/characters`, `/{id}/events`, `/{id}/quests`, `/{id}/factions`, `/{id}/npcs`, `/{id}/inventory`, `/{id}/sessions`, `GET /{id}/state`, `/{id}/audit`, `/{id}/export`, `/{id}/analytics/summary`, `/analytics/risk-report`, ... |
| DM tools | `DmRoutes` | `POST /v1/dm/encounter-builder`, `/loot-parcel`, `/session-recap` |
| Downtime | `DowntimeRoutes` | `POST /v1/campaigns/{id}/downtime/crafting`, `/{project_id}/advance` |
| Play (actor-gated) | `PlayRoutes` | `POST /v1/play/campaigns`, `/{id}/members`, `/{id}/start`, `/{id}/narrations`, `/{id}/actions`, `/{id}/resolutions`, `/{id}/turn/nudge`; `GET /{id}/turn`, `/{id}/my-turn`, `/{id}/gm/status`; `GET`/`PUT /{id}/document` |

## Conventions for extending and testing

- Keep route closures thin: validate input, delegate math to `App\Rules\*`
  and persistence to `App\Storage\*`, then return via `Json::response()`.
  Don't inline SQL or D&D formulas into a route closure — add a repository
  method or rules method instead.
- Validation errors always return `400` with `{"error": "<message>"}`;
  not-found returns `404` the same way; conflicts (duplicate id/slug/username)
  return `409` (except combat session creation, which used `400` before this
  refactor and still does, to preserve existing behavior). Match this shape
  for any new endpoint.
- Rules classes (`src/Rules/`) must stay pure (no PDO, no I/O) so they can be
  called directly from a test without spinning up the HTTP server.
- After adding a class under `src/`, run `composer dump-autoload`.
- To test manually end-to-end, run `GAME_DB_FILE=/tmp/test.db PORT=8080 ./run.sh`
  in one terminal and `curl` the endpoints above in another; `GAME_DB_FILE`
  keeps test runs isolated from the default `game.db`.
- The play surface's turn rotation is intentionally simple and fixed at two
  members: `POST /start` seats the first joiner; each player `POST
  /actions` hands the turn to the DM; each DM `POST /resolutions` hands it
  to whichever of the two joiners didn't just act. `PlayRoutes` doesn't
  generalize beyond two players — if that changes, `resolutions`' next-actor
  selection (`membersInJoinOrder` plus `turn_number`) is the place to revisit.
- This directory's `dndeval` benchmark binary (built from
  `experiments/dnd-rest-benchmark/evaluator` in the parent research repo) is
  the authoritative regression check: `dndeval run --suite
  030-campaign-document --base-url http://127.0.0.1:8080` should stay green
  after any change here.
