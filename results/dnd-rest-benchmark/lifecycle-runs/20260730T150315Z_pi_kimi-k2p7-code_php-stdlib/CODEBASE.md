# D&D DM Tools — PHP stdlib codebase

A tiny, dependency-free REST API for D&D 5e-style DM helpers, built on PHP's
built-in server and the SQLite extension. No Composer packages are used.

## Quick start

```bash
PORT=8080 ./run.sh
```

In another terminal:

```bash
curl -s http://127.0.0.1:8080/health
# -> {"ok":true}
```

`run.sh` deletes the SQLite database (and any stale legacy JSON files) before
starting, so every run begins from a clean state.

## Entry point and modules

- **`index.php`** — sets the JSON response header, defines `ROOT_DIR`, and loads
  every module in dependency order. It does not contain request logic; that is
  delegated to `src/Router.php`.
- **`src/Http.php`** — request parsing (`getMethod`, `getPath`, `parseInput`) and
  response helpers (`sendJson`, `sendError`).
- **`src/Database.php`** — SQLite connection (`db()`), schema initialization
  (`initDatabase()`), storage reset (`resetDatabase()`), and the health check for
  the database (`isInitialized()`).
- **`src/Utils.php`** — 5e math tables: ability modifier, proficiency bonus, XP
  by CR, encounter thresholds, and `calculateEncounterDifficulty()`.
- **`src/Combat.php`** — initiative sorting, combat session creation, condition
  application, and turn advancement. All combat state is read/written through
  `loadCombatState()` and `saveCombatState()`.
- **`src/Auth.php`** — user registration and login backed by the `users` table.
- **`src/Compendium.php`** — monster and item CRUD.
- **`src/Campaigns.php`** — campaigns, characters, events, campaign state, and
  session recap generation.
- **`src/PlayerHandbook.php`** — wizard spell slots, long rests, and carrying
  capacity.
- **`src/DmTools.php`** — DM-facing helpers: encounter builder, loot parcels, and
  session recap.
- **`src/Router.php`** — single if/elseif dispatch chain that maps method + path
  to domain functions. It is the only file that wires HTTP to the domain.

## State, persistence, and routing

### Persistence

All mutable state lives in a single SQLite file, `game.db`, in the project root.
`initDatabase()` is called on every request and creates tables idempotently; the
schema version is stored in `schema_version` for observability. The reset endpoint
`/v1/storage/reset` drops and recreates all tables.

Historical note: earlier versions of the codebase used JSON files for combat
state and users. `run.sh` still removes `.combat_state.json` and `.users.json` at
startup to avoid confusion, but the runtime no longer reads them.

### Routing

`src/Router.php` reads the request method/path from `$_SERVER` and the JSON body
from `php://input`. It matches routes in a single chain:

```php
if ($method === 'GET' && $path === '/health') { ... }
elseif ($method === 'POST' && $path === '/v1/dice/stats') { ... }
elseif (...) { ... }
// ...
sendError(404, 'not found');
```

Path parameters (session IDs, campaign IDs, slugs) are captured with `preg_match`.
The first matching branch handles the request and exits via `sendJson` or
`sendError`; if no branch matches, the router falls through to a 404.

### Determinism

The server does not use randomness. Responses are fully determined by the
request body and the current SQLite state, which is required for reproducible
combat initiative and encounter math.

## Main API/domain groupings

| Group | Prefix | Responsibility |
|-------|--------|--------------|
| Core | `/health`, `/v1/dice/stats`, `/v1/checks/ability`, `/v1/encounters/adjusted-xp`, `/v1/initiative/order` | Health, dice statistics, ability checks, initiative, and adjusted XP. |
| Characters | `/v1/characters/...` | Ability modifiers, proficiency, derived stats. |
| Combat | `/v1/combat/sessions` | Session creation, turn order, conditions, advance. |
| Auth | `/v1/auth/...` | Register and login. |
| Storage | `/v1/storage/...` | SQLite status and reset. |
| Compendium | `/v1/compendium/...` | Monsters and items. |
| Campaigns | `/v1/campaigns/...` | Campaigns, characters, events, state. |
| PHB | `/v1/phb/...` | Spell slots, long rest, equipment load. |
| DM Tools | `/v1/dm/...` | Encounter builder, loot parcel, session recap. |

## Conventions for extending and testing

- **Keep HTTP and domain separate.** Add new business logic to the appropriate
  `src/*.php` module, then add a branch in `src/Router.php`. Avoid putting SQL or
  math directly in `index.php` or `Router.php`.
- **Preserve existing error messages.** Many endpoints return specific 400/401/404
  bodies (e.g. `missing fields`, `invalid expression`, `session not found`). When
  adding features or refactoring, keep these exact strings for the cumulative
  test suite.
- **Validate input with the same patterns.** Use `array_key_exists` for required
  fields, `filter_var(..., FILTER_VALIDATE_INT)` for integers, `is_string` for
  string IDs, and `is_bool` for booleans. Always check IDs are non-empty before
  using them.
- **Use the shared response helpers.** Every successful response goes through
  `sendJson(int $code, array $body)`, which encodes with
  `JSON_UNESCAPED_SLASHES` and appends a newline. Errors use `sendError()`.
- **Cast empty associative arrays to objects when needed.** For example, combat
  `conditions` is returned with `(object) $session['conditions']` so that an empty
  set serializes as `{}` rather than `[]`.
- **Test deterministically.** Lint files with `php -l`, then run the server on a
  throwaway port and exercise endpoints with `curl`. Use `/v1/storage/reset` or
  delete `game.db` between full test runs so IDs and unique constraints do not
  leak across tests.
- **Do not add Composer packages.** The benchmark uses only PHP 8.5.8 and the
  built-in extensions (PDO/SQLite). If you need a new library, implement it with
  core PHP functions instead.
