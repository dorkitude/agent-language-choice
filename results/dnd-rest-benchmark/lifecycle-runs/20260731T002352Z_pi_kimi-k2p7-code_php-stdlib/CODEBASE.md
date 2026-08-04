# D&D DM Tools API — Codebase Guide

A dependency-free PHP stdlib implementation of a small D&D helper API. It runs on the PHP built-in server with `index.php` as the request router.

## How to start and verify the server

```bash
PORT=8080 ./run.sh
```

`run.sh` starts the PHP built-in server in the foreground:

```bash
php -S 127.0.0.1:"$PORT" index.php
```

Verify with:

```bash
curl http://127.0.0.1:$PORT/health
# {"ok":true}
```

The server must be started with `index.php` as the router so every request flows through the single entry point.

## Entry point and major modules

Everything is in `index.php`. The file is organized into sections:

1. **Configuration & constants** — `DB_FILE`, `SCHEMA_VERSION`.
2. **HTTP helpers** — `jsonResponse`, `readJson`, `badRequest`.
3. **Validation helpers** — `validSlug`, `validUsername`, `validNonEmptyString`, etc.
4. **Game rule helpers** — `abilityModifier`, `proficiencyBonus`, `calculateEncounter`, `recommendationForDifficulty`.
5. **Initiative ordering** — `orderByInitiative`, shared by `/v1/initiative/order` and combat session creation.
6. **Database layer** — `getDb`, `initializeSchema`, `initDb`, `resetDb`.
7. **Storage helpers** — CRUD functions for users, combat sessions, monsters, items, campaigns, characters, and events.
8. **Response builders** — `combatSessionResponse`, `storageStatus`.
9. **Route handlers** — one `handle...` function per endpoint.
10. **Startup & dispatch** — `initDb()` then a regex-based route table.

`run.sh` is the only other operational file.

## State, persistence, and request-routing design

### Persistence

- SQLite via PDO, file-backed at `./game.db`.
- Connection is a singleton (`static $pdo` in `getDb()`).
- WAL mode and a 5-second busy timeout are enabled.
- Schema is created on first startup by `initDb()`.
- `POST /v1/storage/reset` drops and recreates all tables and cleans up legacy JSON files.

### Routing

- The request method and path are read from `$_SERVER`.
- A `$routes` table lists `[method, regex, handler]` tuples.
- Captured regex groups are passed as arguments to the handler.
- The first matching route wins; if none match, the dispatcher returns `404 {"error":"not found"}`.

### Determinism

- Initiative tie-breaking is deterministic: score desc, dex desc, name asc.
- Password hashing uses `password_hash()` with `PASSWORD_DEFAULT`.
- Login tokens are deterministic strings (`session-<username>`).

## Main API / domain groupings

| Group | Endpoints |
|-------|-----------|
| Core | `GET /health`, `POST /v1/dice/stats`, `POST /v1/checks/ability`, `POST /v1/encounters/adjusted-xp`, `POST /v1/initiative/order` |
| Characters | `POST /v1/characters/ability-modifier`, `POST /v1/characters/proficiency`, `POST /v1/characters/derived-stats` |
| Combat | `POST /v1/combat/sessions`, `POST /v1/combat/sessions/{id}/conditions`, `POST /v1/combat/sessions/{id}/advance` |
| Auth | `POST /v1/auth/register`, `POST /v1/auth/login` |
| Storage | `GET /v1/storage/status`, `POST /v1/storage/reset` |
| Compendium | `POST /v1/compendium/monsters`, `GET /v1/compendium/monsters/{slug}`, `POST /v1/compendium/items`, `GET /v1/compendium/items/{slug}` |
| Campaigns | `POST /v1/campaigns`, `POST /v1/campaigns/{id}/characters`, `POST /v1/campaigns/{id}/events`, `GET /v1/campaigns/{id}/state` |
| PHB Rules | `POST /v1/phb/spell-slots`, `POST /v1/phb/rests/long`, `POST /v1/phb/equipment-load` |
| DM Tools | `POST /v1/dm/encounter-builder`, `POST /v1/dm/loot-parcel`, `POST /v1/dm/session-recap` |

## Conventions for extending and testing

- **Keep it single-file.** Add new route handlers as top-level `handleXxx()` functions, add a row to the `$routes` table, and keep the handler return type `never` (it must end with `jsonResponse` or `badRequest`).
- **Preserve response shapes.** The cumulative test suite checks exact response bodies, status codes, and validation error messages. Copy the exact status code and field set from an existing handler when adding a new endpoint.
- **Use the validation helpers.** Reuse `validSlug`, `validNonEmptyString`, `validAbilityScore`, `validLevel`, `validPositiveInt`, `validNonNegativeInt`, etc., so validation semantics stay consistent.
- **Database changes.** If you add a table, add it in `initializeSchema()` and drop it in `resetDb()` in the same relative order as the existing tables.
- **Testing.** Start the server with `./run.sh` on an unused port, hit the endpoints with `curl`, and reset storage with `POST /v1/storage/reset` between test scenarios.
- **No Composer.** The project uses only the PHP standard library; do not add package dependencies.
