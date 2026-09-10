# DM Tools — Codebase Guide

This is a small PHP/Symfony-Components HTTP API for D&D-style DM helpers. It is
deliberately self-contained: a single SQLite database, a handful of domain
classes, and Symfony `HttpFoundation` + `Routing` for HTTP handling.

## Quick start

Install dependencies (already vendored in this workspace):

```bash
composer install
```

Start the server in the foreground on the port defined by the `PORT`
environment variable:

```bash
PORT=8080 ./run.sh
```

`run.sh` first calls `reset.php` to clear legacy JSON files and truncate the
SQLite data tables, then launches PHP's built-in server bound to
`127.0.0.1:$PORT` using `index.php` as the router script.

Verify the server is up:

```bash
curl http://127.0.0.1:8080/health
# Expected: {"ok":true}
```

Reset persisted state:

```bash
curl -X POST http://127.0.0.1:8080/v1/storage/reset
# Expected: {"ok":true,"schema_version":1}
```

## Project layout

```
.
├── index.php              # Entry point: bootstrap storage, build routes, dispatch requests
├── reset.php              # Pre-startup database reset (used by run.sh)
├── run.sh                 # Foreground server startup
├── composer.json          # Pins Symfony HttpFoundation 8.1.1 and Symfony Routing 8.1.0
├── src/
│   ├── Storage/
│   │   └── GameStorage.php       # All SQLite schema, queries and reset logic
│   ├── Domain/
│   │   ├── Dice.php              # Dice expression parsing and statistics
│   │   ├── Initiative.php        # Deterministic initiative sorting
│   │   ├── Encounter.php         # Encounter difficulty / adjusted XP
│   │   ├── CharacterRules.php    # Ability modifiers, proficiency, derived stats
│   │   ├── RestRules.php         # Spell slots, long rest, equipment load
│   │   ├── SpellRules.php        # Class-based spell validation
│   │   └── CampaignAnalytics.php # Campaign readiness/risk scoring
│   ├── Http/
│   │   ├── HttpException.php     # Domain exception carrying HTTP status code
│   │   ├── HttpHelper.php        # JSON body parsing and error responses
│   │   ├── AuthHelper.php        # Bearer-token authentication and role checks
│   │   └── Controllers.php       # One method per HTTP route
│   ├── Routing/
│   │   └── Router.php            # RouteCollection definition
│   └── Util/
│       └── Numbers.php           # Whole-number float normalisation
└── game.db                # Runtime SQLite database (created on first boot)
```

## Entry point and routing

`index.php` performs the following steps on every request:

1. Loads `vendor/autoload.php`.
2. Creates `App\Storage\GameStorage`, which ensures the SQLite schema exists.
3. Creates `App\Http\Controllers`; `App\Routing\Router` builds the
   `RouteCollection` from that instance.
4. Builds a `Request` from globals once, then derives a `RequestContext` from
   it and creates a `UrlMatcher`.
5. Matches the incoming `Request` against the route collection.
6. Calls the matched controller callable with `($request, $parameters)`.
7. Catches `App\Http\HttpException` → JSON error response with the carried
   status code (400/401/403/409), then `ResourceNotFoundException` → 404 and
   `MethodNotAllowedException` → 405.
8. Sends the resulting `JsonResponse`.

All route definitions are in `src/Routing/Router.php`. Controller methods are
ordinary public methods on `Controllers`; they are registered as
`[$controllers, 'methodName']` callables. This keeps the dispatch code in
`index.php` tiny and makes the routing table easy to scan. `Router` uses small
private `get`/`post`/`put` helpers to reduce the visual noise of the Symfony
`Route` constructor arguments.

Authentication/authorization is handled through `AuthHelper` so controllers do
not repeat the same bearer-token and role checks. `HttpException` lets a
controller fail fast with the same status codes and messages the original
implementation returned manually; `index.php` translates the exception into a
uniform JSON response.

## State and persistence

All persistent state lives in a single SQLite database (`game.db`). The schema is
created idempotently by `GameStorage::initialize()` on every request if the
tables do not exist. Foreign keys are enabled.

Tables:

- `schema_version` — single-row schema marker (currently version 1).
- `users` — username, password hash (bcrypt), role (`dm` or `player`).
- `combat_sessions` / `combat_conditions` — round, turn index, initiative order
  and conditions tied to a combat target.
- `compendium_monsters` / `compendium_items` — monster and item entries keyed
  by slug.
- `campaigns` / `campaign_characters` / `campaign_events` — campaign data,
  characters, and log entries.
- `quests` / `quest_milestones` — quest tracking with milestone completion.
- `campaign_factions` / `campaign_npcs` — faction and NPC relationship tracking.
- `campaign_inventory` — party and character item ownership.
- `downtime_crafting` — crafting project progress.
- `campaign_sessions` / `session_attendance` — session scheduling and RSVP.
- `play_campaigns` / `play_campaign_members` / `play_campaign_narrations` /
  `play_campaign_documents` — collaborative play-campaign turn queue,
  narration log, and shared document.
- `play_campaign_scenes` / `play_campaign_locations` /
  `play_campaign_location_connections` / `play_campaign_encounters` —
  scene graph, travel edges, and active encounters.
- `play_campaign_character_spells` — known spells per character.

`GameStorage::reset()` truncates all data tables, re-seeds the schema version,
and deletes legacy `.combat-state.json` / `.users.json` files. `reset.php`
performs this before the server starts, and `run.sh` no longer duplicates the
truncate list. The `POST /v1/storage/reset` endpoint also calls
`GameStorage::reset()` at runtime.

`GameStorage::initialize()` also performs lightweight column migrations via
`addColumnIfMissing()` so older copies of `game.db` gain new columns (e.g.
`play_campaigns.current_actor`, `campaign_inventory.source`) automatically.

## Domain groupings

The API surface is grouped by URL prefix:

| Prefix | Domain | Examples |
|--------|--------|----------|
| `/health` | Liveness | `GET /health` |
| `/v1/storage/...` | Persistence status/reset | `GET /v1/storage/status`, `POST /v1/storage/reset` |
| `/v1/dice/...` | Dice math | `POST /v1/dice/stats` |
| `/v1/checks/...` | Checks | `POST /v1/checks/ability` |
| `/v1/encounters/...` | Encounter math | `POST /v1/encounters/adjusted-xp` |
| `/v1/initiative/...` | Initiative | `POST /v1/initiative/order` |
| `/v1/characters/...` | Character rules | `POST /v1/characters/ability-modifier`, `POST /v1/characters/proficiency`, `POST /v1/characters/derived-stats` |
| `/v1/combat/...` | Combat tracker | `POST /v1/combat/sessions`, `POST /v1/combat/sessions/{id}/conditions`, `POST /v1/combat/sessions/{id}/advance` |
| `/v1/auth/...` | Authentication | `POST /v1/auth/register`, `POST /v1/auth/login` |
| `/v1/compendium/...` | Monster/item compendium | `POST /v1/compendium/monsters`, `GET /v1/compendium/monsters/{slug}` |
| `/v1/campaigns/...` | Campaign management | `POST /v1/campaigns`, `POST /v1/campaigns/{id}/characters`, `POST /v1/campaigns/{id}/events`, `GET /v1/campaigns/{id}/state`, plus quests, factions, NPCs, inventory, crafting, sessions, audit, export and analytics |
| `/v1/phb/...` | Player's Handbook helpers | `POST /v1/phb/spell-slots`, `POST /v1/phb/rests/long`, `POST /v1/phb/equipment-load` |
| `/v1/dm/...` | DM utilities | `POST /v1/dm/encounter-builder`, `POST /v1/dm/loot-parcel`, `POST /v1/dm/session-recap` |
| `/v1/play/campaigns/...` | Collaborative play campaigns | creation, join, start, narration, turn queue, action/resolution, shared document, scene graph, travel turns, rest turns, encounter creation, character ownership/claims, level progression, skill checks and spellbook state |

Validation rules, response shapes, and status codes are intentionally preserved
from the previous stage. The controllers do HTTP-specific validation; pure
arithmetic and sorting live in `src/Domain/` so they are reused across endpoints
(e.g. initiative sorting and encounter difficulty). Campaign readiness and risk
scoring lives in `src/Domain/CampaignAnalytics.php`; bearer-token handling lives
in `src/Http/AuthHelper.php`.

## Conventions for extending and testing

- **Add routes in `src/Routing/Router.php`**, then implement the corresponding
  public method in `src/Http/Controllers.php`. The method signature is
  `methodName(Request $request, array $parameters): JsonResponse`.
- **Keep domain logic pure.** If a calculation is used by more than one endpoint,
  place it in `src/Domain/`. Pure functions are easy to unit-test with
  `php -r` or small PHPUnit scripts without booting the database.
- **Keep cross-cutting HTTP concerns out of controllers.** Authentication logic
  lives in `AuthHelper`; analytics scoring lives in `CampaignAnalytics`.
- **Storage changes go through `GameStorage`.** Do not embed raw SQL outside
  this class. If you need a new table, add it to `GameStorage::initialize()`;
  reset truncation is centralised in `GameStorage::reset()`, so `reset.php` and
  the runtime reset endpoint stay in sync automatically.
- **Test without starting the server.** You can construct `Request` objects with
  `Request::create()`, wire up `Controllers` + `Router`, and call
  `UrlMatcher::matchRequest()` directly. See the existing ad-hoc tests in the
  development history for the pattern.
- **Do not change the response bodies or status codes** for existing endpoints
  unless the stage explicitly requires it. The cumulative evaluator suite checks
  every prior endpoint.
- **Use `composer dump-autoload`** after adding new classes or namespaces so
  the PSR-4 autoloader picks them up.
- **Keep auth/role checks in `AuthHelper`.** `requireDm`, `requirePlayer`,
  `requirePlayCampaignOwner`, and `requirePlayCampaignMemberOrOwner` centralise
  the common access patterns. Prefer them over inline `authenticate` + null/role
  checks in new controllers; throw `HttpException` for endpoint-specific errors
  when a generic helper does not fit.
