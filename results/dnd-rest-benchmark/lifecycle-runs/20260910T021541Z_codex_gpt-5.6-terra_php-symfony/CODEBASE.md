# D&D REST API

## Run and verify

Install the pinned dependencies with `composer install`. Start the foreground server with `PORT=8000 ./run.sh`; it binds only to `127.0.0.1` and initializes SQLite before serving requests. Verify it with `curl -i http://127.0.0.1:8000/health`, which returns the JSON health response. Do not start a second server against the same database while testing writes.

## Layout and request flow

- `run.sh` initializes storage and runs PHP's built-in server in the foreground.
- `index.php` is the HTTP entry point. It contains small validation/rule helpers, `applicationRoutes()` (the complete Symfony Routing route table), route matching, the explicit handler dispatch, and the API error mapping.
- `storage.php` owns the SQLite connection, schema initialization, and reset operation. `TABLE_DEFINITIONS` is the authoritative create-schema inventory, while `RESET_TABLES` records the established reset sequence.
- `game.db` is runtime state, created beside these files; it is not source code.
- `composer.json` pins Symfony HttpFoundation and Routing; Composer's autoloader is loaded by `index.php`.

Every request is converted to a Symfony `Request`, matched by `UrlMatcher`, and dispatched by the matched route name. Handlers return `JsonResponse` instances. Unknown paths and unsupported methods are handled by the matcher (404 and 405); validation and domain exceptions are mapped at the bottom of `index.php` to the established JSON errors.

## State and persistence

`storage.php` uses one PDO SQLite connection per PHP process with exceptions enabled and a five-second SQLite busy timeout. The schema holds users, combat-session JSON blobs, compendium monsters/items, and campaign records with their characters/events. `run.sh` and the storage reset endpoint initialize the same schema version. `TABLE_DEFINITIONS` describes a new database; `addMissingColumns()` applies the ordered additive migrations for existing play-campaign, member, and encounter tables. Do not convert those migrations into a destructive rebuild: existing `game.db` files must remain usable.

Combat sessions and users use load-modify-save helpers in `index.php`. Loading begins a transaction; successful saves replace the corresponding table contents and commit. All early exits after a load must call the matching `closeCombatSessions()` or `closeUsers()` helper so the transaction rolls back. This is intentional and preserves their current persistence semantics. Combat condition maps are explicitly cast to an object before JSON encoding so an empty map remains `{}`.

## API groupings

- Health and storage: `/health`, `/v1/storage/*`.
- Core rules: dice statistics, ability checks, encounter XP, initiative, and character derived-stat helpers.
- Combat: persistent session creation, conditions, and turn advancement under `/v1/combat/*`.
- Authentication: registration and login under `/v1/auth/*`.
- Content and campaigns: compendium monsters/items and campaign, character, event, faction, NPC, relationship, quest, inventory/equipment, encounter roster, and state endpoints.
- PHB helpers: spell slots, long rests, and equipment load under `/v1/phb/*`.
- DM tools: deterministic encounter building, loot parcels, and recaps under `/v1/dm/*`.

## Safe extension and testing

Add a route to `applicationRoutes()` and keep its route name aligned with the dispatch branch in `index.php`. Reuse the existing strict JSON and scalar validators rather than coercing client values. Preserve response field order, status codes, validation boundaries, and deterministic ordering: these are observable API behavior. Use prepared statements for new persistence and make ordering explicit when query order is part of a response. When changing storage, update `TABLE_DEFINITIONS`, `RESET_TABLES`, and the appropriate ordered `addMissingColumns()` inventory together; preserve existing additive migrations for deployed databases. For manual regression checks, start with `/health`, then reset storage before a stateful scenario; exercise both a successful request and an invalid request for each changed endpoint. Run `php -l index.php` and `php -l storage.php` before handing off.
