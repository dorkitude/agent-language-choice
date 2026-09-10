# Codebase guide

## Run and verify

Dependencies are pinned in `composer.lock`; install them with `composer install`
if `vendor/` is absent. Start the foreground server with:

```sh
PORT=8080 ./run.sh
```

`run.sh` invokes PHP's built-in server at `127.0.0.1:$PORT`, using `index.php`
as the router. Verify a running server with:

```sh
curl -i http://127.0.0.1:8080/health
```

The response is JSON containing `{"ok":true}`. For a non-mutating local check,
run `php -l index.php`. Do not start a server merely to perform a static check.

## Layout and request flow

The application deliberately has a small footprint:

- `index.php` is the entry point. It loads Composer, defines HTTP, validation,
  persistence, and domain helpers; initializes SQLite; registers Slim routes;
  then runs the application.
- `run.sh` is the foreground launcher required by the service contract.
- `composer.json` and `composer.lock` define the pinned Slim 4.15.2 and
  slim/psr7 1.8.0 dependencies. `vendor/` is Composer-managed.
- `game.db` is generated persistent state and must not be committed.

Route closures decode a JSON body with `jsonBody`, validate it before changing
state, use prepared SQLite statements, and finish with `jsonResponse` or the
shared `badRequest` response. Helpers above the route registrations are grouped
by responsibility: basic HTTP/rules, storage, authenticated play campaigns,
and campaign-management projections/calculations. Route declarations begin
after application and storage bootstrap, in the same API-group order used
below; this keeps request wiring separate from reusable domain operations even
within the intentionally single-file deployment.

## State and persistence

`database()` owns one process-local PDO connection to `game.db`.
`initializeStorage()` creates all tables at startup and records schema version
1. `storageTableNames()` records the schema's parent-before-child creation
order; reset reverses that exact list to drop dependent tables first.
`/v1/storage/reset` then recreates every application table, so it intentionally
clears all persisted data.

There are two independent campaign surfaces. The authenticated `/v1/play`
surface stores lobby/active campaigns, member order, documents, and sequenced
play events. `rowid` join order is deliberate: it determines party and turn
order. Play event creation is centralized in `appendPlayCampaignEvent()` so
sequence allocation and insertion share one transaction.

The `/v1/campaigns` management surface separately stores campaign metadata,
characters, sessions and attendance, events/quests, factions/NPCs, inventory
and equipment, and crafting projects. Combat sessions and users are stored as
JSON-backed collections; their whole-collection rewrites use
`withinTransaction()`. Scoped campaign updates also use that helper when a
mutation spans more than one table.

## API groupings

- Operations: `/health` and `/v1/storage/*`.
- Authenticated table play: `/v1/play/campaigns/*` for membership, lifecycle,
  documents, turn context, nudges, narrations, resolutions, and actions.
- Campaign management: `/v1/campaigns/*` for characters, sessions,
  attendance, events, quests, factions/NPCs, inventory/equipment, crafting,
  analytics, and summaries.
- Accounts and reference data: `/v1/auth/*` and `/v1/compendium/*`.
- Rules and encounter utilities: `/v1/characters/*`, `/v1/dice/stats`,
  `/v1/checks/ability`, `/v1/initiative/order`, `/v1/encounters/adjusted-xp`,
  `/v1/phb/*`, and `/v1/dm/*`.
- Combat lifecycle: `/v1/combat/sessions/*`, including initiative order,
  conditions, and turn advancement.

## Extending and testing safely

This is a contract-driven API. Preserve route paths and methods, response
status codes and JSON field ordering, validation boundaries, persistence
semantics, and observable collection ordering. In particular, retain the
initiative tie-break sequence (score, Dexterity, then name), `rowid` party
ordering, and transactional play-event sequencing.

Put deterministic logic used by multiple routes in a small named helper. Keep
new tables in `initializeStorage()` and add their names in parent-before-child
order to `storageTableNames()` so reset remains safe. Use prepared statements
for all new SQL and make ordering explicit whenever a response can expose it.
Test with `php -l index.php`, then run the applicable evaluator or exercise the
changed endpoint against a manually started server. Reset storage before
stateful tests that require a known database.
