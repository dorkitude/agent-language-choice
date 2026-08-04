# D&D REST API — Codebase Foundation

A small, synchronous Django REST API for D&D 5e-style tooling. The server is intentionally minimal: it uses Django only for routing, request handling, and JSON responses, while state lives in a local SQLite file.

## Start and verify the server

```bash
# inside the project root
PORT=8000 ./run.sh
```

`run.sh` starts the Django development server in the foreground on `127.0.0.1:$PORT` with auto-reload disabled.

Quick verification:

```bash
curl http://127.0.0.1:$PORT/health
# -> {"ok": true}
```

## Entry point and major files

- `manage.py` — standard Django management entry point.
- `run.sh` — convenience launcher that calls `manage.py runserver` in the foreground.
- `dndsite/settings.py` — bare Django settings: `ROOT_URLCONF`, `ALLOWED_HOSTS`, `SECRET_KEY`, `DEBUG`. No Django database settings are used; SQLite is accessed directly.
- `dndsite/urls.py` — route table mapping URL paths to view functions.
- `dndsite/views.py` — all HTTP handlers, grouped by domain.
- `dndsite/persistence.py` — SQLite connection, schema creation, and data access functions.
- `dndsite/rules.py` — shared D&D calculations (XP, encounter difficulty, initiative, modifiers, proficiency).
- `dndsite/auth.py` — username validation and password hashing/verification.
- `dndsite/validation.py` — JSON body parsing helper.
- `game.db` — runtime SQLite database created next to the project root.

## State, persistence, and routing

### Persistence

The application uses a single SQLite file at `./game.db`. `persistence.py` creates the schema when it is imported and provides a connection helper (`_get_conn`) that enables `sqlite3.Row` and foreign-key enforcement.

There are no Django ORM models. Data access is raw SQL wrapped in short helper functions. Every call opens and closes its own connection, so the implementation is deterministic and does not hold long-lived state in memory.

The `storage_reset` endpoint drops and recreates all tables, returning the schema to version 1.

### Routing

`dndsite/urls.py` is the single URLconf. All endpoints are defined there. Routes are organized into the following groups:

- `health` — service liveness.
- `v1/auth/*` — user registration and login.
- `v1/dice/*`, `v1/checks/*` — dice expression stats and ability checks.
- `v1/initiative/*`, `v1/characters/*` — initiative ordering and character math.
- `v1/combat/*` — combat sessions, conditions, and turn advancement.
- `v1/storage/*` — storage status and reset.
- `v1/compendium/*` — monster and item CRUD.
- `v1/campaigns/*` — campaign, character, event, and state management.
- `v1/phb/*` — PHB rules stubs (spell slots, long rest, encumbrance).
- `v1/dm/*` — DM encounter builder, loot parcel, and session recap.

### State

All mutable state is in SQLite. No in-memory caches or global mutable variables are used except for the deterministic rules tables in `rules.py`.

## API/domain groupings

- **Core / Health**: `GET /health`.
- **Auth**: `POST /v1/auth/register`, `POST /v1/auth/login`.
- **Dice & Checks**: `POST /v1/dice/stats`, `POST /v1/checks/ability`.
- **Initiative**: `POST /v1/initiative/order`.
- **Characters**: `POST /v1/characters/ability-modifier`, `POST /v1/characters/proficiency`, `POST /v1/characters/derived-stats`.
- **Combat**: `POST /v1/combat/sessions`, `POST /v1/combat/sessions/<id>/conditions`, `POST /v1/combat/sessions/<id>/advance`.
- **Encounters**: `POST /v1/encounters/adjusted-xp`.
- **Storage**: `GET /v1/storage/status`, `POST /v1/storage/reset`.
- **Compendium**: `POST /v1/compendium/monsters`, `GET /v1/compendium/monsters/<slug>`, `POST /v1/compendium/items`, `GET /v1/compendium/items/<slug>`.
- **Campaigns**: `POST /v1/campaigns`, `POST /v1/campaigns/<id>/characters`, `POST /v1/campaigns/<id>/events`, `GET /v1/campaigns/<id>/state`.
- **PHB Rules**: `POST /v1/phb/spell-slots`, `POST /v1/phb/rests/long`, `POST /v1/phb/equipment-load`.
- **DM Tools**: `POST /v1/dm/encounter-builder`, `POST /v1/dm/loot-parcel`, `POST /v1/dm/session-recap`.

## Conventions for extending and testing

- **Preserve the response contract**: status codes, JSON key order, and error messages are part of the API surface. Changing them may break the cumulative evaluator suite.
- **Keep mutation endpoints CSRF-exempt**: all endpoints that accept `POST` are decorated with `@csrf_exempt` so the API can be exercised with plain JSON clients.
- **Use the persistence helper**: new database-backed endpoints should reuse `_get_conn()` and follow the existing pattern of opening/closing a connection per call.
- **Add domain math to `rules.py`**: if you add new D&D calculations, put shared logic in `rules.py` and keep view functions focused on HTTP concerns.
- **Validate via `validation.py`**: use `_parse_json_body` for JSON requests and coerce fields carefully; many endpoints expect specific types and return `400 invalid request` for bad input.
- **Test against the evaluator suite**: run `./run.sh` in one terminal and the provided `dndeval-*` checks against `http://127.0.0.1:$PORT`.
- **Do not change the database path or schema**: `game.db` is the expected SQLite file; `schema_version` is pinned to 1.

## Notes

- The rules implementation is intentionally narrow: only specific party levels (3), CRs, and a wizard level-5 spell-slot table are supported.
- Passwords are hashed with PBKDF2-HMAC-SHA256 (100,000 iterations).
- The server runs in the foreground; terminate it with `Ctrl-C`.
