# DM Tools — Codebase Guide

This is a small PHP/Symfony-Components HTTP API for D&D-style DM helpers. It is deliberately self-contained: a single SQLite database, a handful of domain classes, and Symfony `HttpFoundation` + `Routing` for HTTP handling.

## Quick start

Install dependencies (already vendored in this workspace):

```bash
composer install
```

Start the server in the foreground on the port defined by the `PORT` environment variable:

```bash
PORT=8080 ./run.sh
```

`run.sh` removes legacy JSON files, truncates the SQLite data tables, and then launches PHP's built-in server bound to `127.0.0.1:$PORT` using `index.php` as the router script.

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
├── run.sh                 # Foreground server startup + table reset
├── composer.json          # Pins Symfony HttpFoundation 8.1.1 and Symfony Routing 8.1.0
├── src/
│   ├── Storage/
│   │   └── GameStorage.php       # All SQLite schema, queries and reset logic
│   ├── Domain/
│   │   ├── Dice.php              # Dice expression parsing and statistics
│   │   ├── Initiative.php        # Deterministic initiative sorting
│   │   ├── Encounter.php         # Encounter difficulty / adjusted XP
│   │   ├── CharacterRules.php    # Ability modifiers, proficiency, derived stats
│   │   └── RestRules.php         # Spell slots, long rest, equipment load
│   ├── Http/
│   │   ├── HttpHelper.php        # JSON body parsing and error responses
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
3. Creates `App\Http\Controllers` and asks `App\Routing\Router` for the `RouteCollection`.
4. Builds a `RequestContext` from globals and a `UrlMatcher`.
5. Matches the incoming `Request` against the route collection.
6. Calls the matched controller callable with `($request, $parameters)`.
7. Catches `ResourceNotFoundException` → 404 and `MethodNotAllowedException` → 405.
8. Sends the resulting `JsonResponse`.

All route definitions are in `src/Routing/Router.php`. Controller methods are ordinary public methods on `Controllers`; they are registered as `[$controllers, 'methodName']` callables. This keeps the dispatch code in `index.php` tiny and makes the routing table easy to scan.

## State and persistence

All persistent state lives in a single SQLite database (`game.db`). The schema is created idempotently by `GameStorage::initialize()` on every request if the tables do not exist. Foreign keys are enabled.

Tables:

- `schema_version` — single-row schema marker (currently version 1).
- `users` — username, password hash (bcrypt), role (`dm` or `player`).
- `combat_sessions` — round, turn index, JSON-ordered combatants.
- `combat_conditions` — conditions tied to a combat session and target, with remaining rounds.
- `compendium_monsters` — monster entries keyed by slug.
- `compendium_items` — item entries keyed by slug.
- `campaigns` — campaign id, name, DM.
- `campaign_characters` — characters belonging to a campaign.
- `campaign_events` — log entries belonging to a campaign.

`GameStorage::reset()` truncates all data tables, re-seeds the schema version, and deletes legacy `.combat-state.json` / `.users.json` files. `run.sh` calls an equivalent reset before starting the server.

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
| `/v1/campaigns/...` | Campaign management | `POST /v1/campaigns`, `POST /v1/campaigns/{id}/characters`, `POST /v1/campaigns/{id}/events`, `GET /v1/campaigns/{id}/state` |
| `/v1/phb/...` | Player's Handbook helpers | `POST /v1/phb/spell-slots`, `POST /v1/phb/rests/long`, `POST /v1/phb/equipment-load` |
| `/v1/dm/...` | DM utilities | `POST /v1/dm/encounter-builder`, `POST /v1/dm/loot-parcel`, `POST /v1/dm/session-recap` |

Validation rules, response shapes, and status codes are intentionally preserved from the previous stage. The controllers do HTTP-specific validation; pure arithmetic and sorting live in `src/Domain/` so they are reused across endpoints (e.g. initiative sorting and encounter difficulty).

## Conventions for extending and testing

- **Add routes in `src/Routing/Router.php`**, then implement the corresponding public method in `src/Http/Controllers.php`. The method signature is `methodName(Request $request, array $parameters): JsonResponse`.
- **Keep domain logic pure.** If a calculation is used by more than one endpoint, place it in `src/Domain/`. Pure functions are easy to unit-test with `php -r` or small PHPUnit scripts without booting the database.
- **Storage changes go through `GameStorage`.** Do not embed raw SQL outside this class. If you need a new table, add it to `GameStorage::initialize()` and the truncate list in `GameStorage::reset()` (and `run.sh` if pre-startup cleanup matters).
- **Test without starting the server.** You can construct `Request` objects with `Request::create()`, wire up `Controllers` + `Router`, and call `UrlMatcher::matchRequest()` directly. See the existing ad-hoc tests in the development history for the pattern.
- **Do not change the response bodies or status codes** for existing endpoints unless the stage explicitly requires it. The cumulative evaluator suite checks every prior endpoint.
- **Use `composer dump-autoload`** after adding new classes or namespaces so the PSR-4 autoloader picks them up.
