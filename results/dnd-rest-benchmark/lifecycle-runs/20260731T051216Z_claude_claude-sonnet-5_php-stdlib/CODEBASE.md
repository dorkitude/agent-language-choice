# dm-tools API — Codebase Guide

A plain-PHP REST API for tabletop D&D session support: dice, checks,
initiative, combat tracking, auth, a compendium, campaign bookkeeping (roster,
quests, factions/NPCs, inventory, crafting, scheduling, audit/analytics), DM
helper tools, and an authenticated turn-based "play" surface for running a
campaign live. It runs on PHP's built-in web server with no Composer
dependencies.

## Starting and verifying the server

```bash
PORT=8080 ./run.sh
```

`run.sh` deletes any leftover `combat_sessions.json` / `users.json` (legacy
file-store artifacts from earlier stages) and the SQLite file `game.db`, then
starts `php -S 127.0.0.1:$PORT index.php` in the foreground. Each run starts
from a clean database.

Verify it's up:

```bash
curl -s http://127.0.0.1:$PORT/health
# {"ok":true}
```

Most endpoints require `Content-Type: application/json` and a JSON body —
PHP's built-in server only exposes the raw POST body via `php://input` when
the request isn't parsed as a traditional form upload, so requests that omit
the header but still send JSON text will fail body validation.

### Running the evaluator suite

The benchmark's Go-based evaluator (`dndeval`) drives the server over HTTP and
checks status codes/response bodies. The cumulative suite for this stage is
`049-skills-and-proficiencies` (136 tests, re-testing everything through
checkpoint 49):

```bash
lsof -ti:8099 | xargs -r kill -9          # free the port
rm -f combat_sessions.json users.json game.db   # clean slate — see gotcha below
PORT=8099 php -S 127.0.0.1:8099 index.php &
sleep 1
/path/to/dndeval run --base-url http://127.0.0.1:8099 --suite 049-skills-and-proficiencies
lsof -ti:8099 | xargs -r kill -9          # stop the server afterward
```

**Gotcha**: always delete `combat_sessions.json`, `users.json`, and `game.db`
and start a fresh server process before each run. Re-running the suite
against an already-populated database produces spurious `409`/`500` failures
(e.g. "session already exists") that look like regressions but are just
leftover state from the previous run.

## Entry point and module layout

`index.php` is a thin entry point: it `require`s the files below in
dependency order and nothing else. There is no autoloader and no Composer —
every required file is plain top-level PHP that executes directly in
`index.php`'s global scope, so a function/constant/variable defined by an
earlier `require` is visible to every later one. This is what makes the
split safe: the runtime behavior is identical to the old single-file layout,
just reorganized on disk. Route handlers rely on `send_json()` (and the
`bad_request()` etc. shortcuts built on it) calling `exit`, so a request is
fully handled by the first `if ($method === ... && $path === ...)` block
that matches; nothing after it runs.

| File | Purpose |
|---|---|
| `index.php` | Entry point — requires every module below, in order, then the 404 fallback. |
| `lib/bootstrap.php` | Per-request setup: `$method`/`$path`, `SCHEMA_VERSION`/`TURN_TIMEOUT_WINDOW` constants, `$dbFile`. |
| `lib/db.php` | Storage layer: `init_schema()` (one `CREATE TABLE IF NOT EXISTS` per resource collection) and `get_db()`; opens `$db`. |
| `lib/http.php` | `read_json_body()`, `send_json()`, and the `bad_request()`/`not_found()`/`unauthorized()`/`conflict()` shortcuts; plus field validators `is_valid_int_range()`/`is_valid_slug()`. |
| `lib/rules.php` | SRD rules helpers: ability modifiers, proficiency bonus, `CR_XP`/`LEVEL_THRESHOLDS`/`LOOT_TIERS`/`SPELL_SLOT_TABLES` tables, `encounter_multiplier()`, `compute_party_thresholds()`, `determine_difficulty()`, plus combat/initiative helpers (`parse_and_sort_combatants()`, combat session load/save). |
| `lib/auth.php` | User load/save, password hash/verify, `require_actor()` (resolves a `Bearer session-<username>` token), `forbidden()`. |
| `lib/routes_core.php` | Routes: health, dice & ability checks, encounter XP/initiative, characters (ability/proficiency/derived stats), combat sessions, `/v1/auth/*`, storage admin. |
| `lib/routes_compendium.php` | Routes: compendium monsters and items. |
| `lib/routes_campaigns.php` | Campaign lookup helpers (`require_campaign_exists()`, `load_campaign()`) plus routes: campaign roster/events/quests, NPCs & factions, inventory & equipment. |
| `lib/routes_tools.php` | Routes: PHB rules (spell slots/rests/equipment load), DM tools (encounter builder/loot/session recap), downtime crafting, session scheduling, audit/export, analytics. |
| `lib/play_campaign.php` | Play-surface lookup helpers (`require_play_campaign()`, `recent_narrations()`, `next_narration_sequence()`) plus routes: campaign create/join/start, narrations, actions/resolutions, turn context, nudge, gm status, document. |
| `lib/play_scenes_travel.php` | Routes: scenes (create/enter/close/current), locations & connections, travel turns, rest turns. |
| `lib/play_characters.php` | Play character helpers (`find_play_character()`, `play_character_owner()`) plus routes: damage, death saves, status, ownership (owner/claim/transfer), character build, level-up, skill checks. |
| `lib/play_combat.php` | Encounter turn-order/HP helpers (`build_encounter_turn_order()`, `apply_encounter_hp_change()`, condition decrement) plus routes: encounters, monsters/combatants, damage/heal, turn advance, conditions, combat actions, delay/ready, rewards, close/end. |
| `lib/routes_fallback.php` | Final fallback: any unmatched request gets a JSON 404. |

There is no router/dispatch table by design: each route is a flat
`if ($method === ... && $path === ...)` (or `preg_match` for paths with an ID
segment) check, and route order only matters in that the first match wins.

**Note on `__DIR__`**: only `lib/bootstrap.php` needs to reference the app
root (for `$dbFile`), and since `__DIR__` inside a required file resolves to
that file's own directory (`lib/`), it uses `dirname(__DIR__) . '/game.db'`
rather than `__DIR__ . '/game.db'` to land the database next to `index.php`.
Keep this in mind if any future module needs a root-relative path.

## State, persistence, and request routing

- **Persistence**: a single SQLite database (`game.db`, created next to
  `index.php`) via PDO. Each resource collection is its own table:
  `combat_sessions`, `users`, `monsters`, `items` (top-level, keyed by their
  own id/slug); `campaigns` and its per-campaign children `campaign_characters`,
  `campaign_events`, `campaign_quests`, `campaign_factions`, `campaign_npcs`,
  `campaign_crafting`, `campaign_sessions` (keyed by `(campaign_id, id)`) plus
  `campaign_inventory` and `campaign_equipment` (keyed by
  `(campaign_id, item_slug, owner)` / `(campaign_id, character_id, item_slug)`,
  since those two track a plain quantity rather than a JSON blob); and the
  play surface's `play_campaigns`, `play_campaign_members`,
  `play_campaign_narrations`, `play_character_owners`. `storage_meta` holds
  schema/init bookkeeping. Every JSON-blob table stores its resource in a
  `data` column keyed by the resource's natural ID — this keeps the schema
  stable while letting resource shapes evolve; `init_schema()` in `lib/db.php`
  is the source of truth for the exact column list of each table.
- **Process model**: PHP's built-in server runs each request fresh, so
  nothing is cached across requests in memory; `get_db()`'s `static $db` only
  avoids re-opening the handle within one request's lifetime. `init_schema()`
  runs every request but is idempotent (`CREATE TABLE IF NOT EXISTS`), so
  this has no observable effect beyond a small constant cost — which is also
  what makes `POST /v1/storage/reset` safe to call anytime.
- **Routing**: no path-parameter framework — routes with a variable segment
  (a session ID, slug, or campaign ID) match via `preg_match` with a capture
  group, checked inline in each route block, across whichever `lib/routes_*.php`
  / `lib/play_*.php` file owns that domain.
- **Reset**: `POST /v1/storage/reset` drops and recreates every table,
  giving a clean slate without restarting the process.

## API/domain groupings

| Group | Paths | Notes |
|---|---|---|
| Health | `GET /health` | liveness check |
| Dice & checks | `POST /v1/dice/stats`, `POST /v1/checks/ability` | stateless math |
| Encounters & initiative | `POST /v1/encounters/adjusted-xp`, `POST /v1/initiative/order` | stateless; shares CR/threshold/multiplier logic with the DM encounter builder |
| Characters | `POST /v1/characters/ability-modifier`, `.../proficiency`, `.../derived-stats` | stateless SRD math |
| Combat sessions | `POST /v1/combat/sessions`, `POST .../{id}/conditions`, `POST .../{id}/advance` | persisted turn order + status conditions |
| Auth | `POST /v1/auth/register`, `POST /v1/auth/login` | bcrypt-hashed passwords; login token is `session-{username}` (not a real session/JWT — matches prior-stage behavior) |
| Storage admin | `GET /v1/storage/status`, `POST /v1/storage/reset` | schema/version introspection and full reset |
| Compendium | `POST`/`GET /v1/compendium/monsters[/...]`, `.../items[/...]` | append-only reference data, keyed by slug |
| Campaigns (roster/log) | `POST /v1/campaigns`, `.../characters`, `.../events`, `GET .../state` | roster + append-only event log, `state` aggregates them |
| Quests | `POST /v1/campaigns/{id}/quests`, `.../quests/{id}/progress`, `GET .../quests/summary` | milestone tracking per quest, plus a per-campaign status-count summary |
| NPCs & factions | `POST /v1/campaigns/{id}/factions`, `.../npcs`, `GET .../relationships` | an NPC must reference an existing faction; `relationships` summarizes counts and friendly disposition |
| Inventory & equipment | `POST /v1/campaigns/{id}/inventory`, `.../characters/{id}/equipment`, `GET .../inventory/summary` | party-owned vs. character-assigned quantities, additive on repeat posts |
| PHB rules | `POST /v1/phb/spell-slots`, `.../rests/long`, `.../equipment-load` | stateless SRD lookup tables |
| DM tools | `POST /v1/dm/encounter-builder`, `.../loot-parcel`, `.../session-recap` | `encounter-builder` looks up monsters from the compendium by slug; `session-recap` returns a fixed placeholder response (no persisted session log to summarize yet) |
| Downtime crafting | `POST /v1/campaigns/{id}/downtime/crafting`, `.../crafting/{id}/advance` | completing a project deposits the crafted item into party inventory |
| Session scheduling | `POST /v1/campaigns/{id}/sessions`, `.../sessions/{id}/attendance`, `GET .../sessions/next` | ISO-8601 `starts_at` validated by `is_valid_iso_datetime()` |
| Audit & export | `GET /v1/campaigns/{id}/audit`, `.../export` | read-only aggregate counts across a campaign's child tables |
| Analytics | `GET /v1/campaigns/{id}/analytics/summary`, `POST .../analytics/risk-report` | both build on `load_campaign_analytics()`; risk report adds a `include_zeroes` flag for near-zero signals |
| Play (protected campaign-play surface) | `POST /v1/play/campaigns`, `.../members`, `.../start`, `.../narrations`, `.../actions`, `.../resolutions`, `GET .../turn`, `POST .../turn/nudge`, `GET .../my-turn`, `.../gm/status`, `GET`/`PUT .../document`, scenes/locations/travel/rest, encounters/combat/rewards, character ownership/build/level-up/skill-check | authenticated via `Authorization: Bearer session-<username>` (see `require_actor()`); the dm/owner and players alternate turns through a fixed create → join → start → (action → resolution)* loop |

## Extending and testing the codebase

- **Adding a route**: add a new `if ($method === ... && $path === ...) { ... }`
  block in the `lib/routes_*.php` or `lib/play_*.php` file matching its
  domain (see the table above), following the existing pattern of
  validate-then-`bad_request()`, then `send_json()`. Keep response shapes
  exact — the evaluator suite checks status codes and body fields precisely.
- **Adding a table**: add its `CREATE TABLE IF NOT EXISTS` to `init_schema()`
  in `lib/db.php` and its `DROP TABLE IF EXISTS` to the `/v1/storage/reset`
  handler (in `lib/routes_core.php`) so reset stays exhaustive.
- **Adding a new module**: if a domain grows large enough to warrant its own
  file, `require` it from `index.php` in the appropriate position (helpers
  before the routes that use them) — no registration step is needed beyond
  that `require` line, since everything shares one global scope.
- **Reusing rules logic**: the CR/XP table, level thresholds, encounter
  multiplier, and difficulty banding (`lib/rules.php`) are shared between
  `/v1/encounters/adjusted-xp` and `/v1/dm/encounter-builder` via
  `CR_XP`, `LEVEL_THRESHOLDS`, `encounter_multiplier()`,
  `compute_party_thresholds()`, and `determine_difficulty()` — extend those
  instead of duplicating a lookup table inline.
- **Reusing campaign/play lookups**: a new `/v1/campaigns/{id}/...` route
  should call `require_campaign_exists($db, $campaignId)` (if it only needs
  the 404 check) or `load_campaign($db, $campaignId)` (if it needs the
  campaign's fields), both in `lib/routes_campaigns.php`; a new
  `/v1/play/campaigns/{id}/...` route should call
  `require_play_campaign($db, $campaignId)` from `lib/play_campaign.php`.
  Don't hand-roll the `SELECT ... WHERE id = ?` + `not_found()` boilerplate
  again — every existing route in both families goes through one of these
  helpers.
- **Testing manually**: start the server with a throwaway `PORT` and hit it
  with `curl`, always setting `Content-Type: application/json`:
  ```bash
  PORT=8099 ./run.sh &
  curl -s -X POST http://127.0.0.1:8099/v1/dice/stats \
    -H 'Content-Type: application/json' -d '{"expression":"2d6+3"}'
  ```
  Call `POST /v1/storage/reset` between manual test runs (or just restart the
  server, since `run.sh` wipes `game.db` on each start) to get a clean state.
- **Running the evaluator**: see "Running the evaluator suite" above — always
  clear `combat_sessions.json`/`users.json`/`game.db` and use a fresh server
  process before each run.
- **No framework, no Composer packages**: this is a target constraint, not an
  oversight — keep additions to plain PHP 8.5 stdlib (PDO SQLite, `password_hash`,
  etc.), and keep new files plain `require`-based, no autoloading.
