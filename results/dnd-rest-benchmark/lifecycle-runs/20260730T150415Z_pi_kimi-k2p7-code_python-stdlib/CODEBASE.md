# D&D DM Tools — Codebase Guide

This is a small, single-process HTTP service for D&D 5e helper calculations,
combat tracking, campaign management, and user authentication. It is built with
Python 3.14.6 and the standard library only (`http.server`, `sqlite3`, `json`,
etc.).

## How to start and verify the server

```bash
# Run in the foreground on the port specified by PORT (default 8080).
./run.sh

# In another terminal, verify the health endpoint:
curl http://127.0.0.1:8080/health
# -> {"ok": true}
```

`run.sh` executes `uv run --python 3.14.6 python server.py`. The server listens
on `127.0.0.1` and binds to the `PORT` environment variable.

## Entry point and major modules

| File | Responsibility |
|------|------------------|
| `server.py` | Entry point. Imports `Handler` from `api` and starts `http.server.HTTPServer`. |
| `api.py` | HTTP request/response helpers and ordered route tables (`GET_ROUTES`, `POST_ROUTES`). Contains the `Handler` class. |
| `storage.py` | SQLite persistence layer. Defines the `Storage` class and the module-level `storage` singleton. |
| `domain.py` | Pure, deterministic game-rule and authentication computations. |
| `constants.py` | Literal game tables and compiled regex patterns. |
| `run.sh` | Launcher script required by the evaluation harness. |

## State, persistence, and routing

### Persistence

All durable state is stored in a single SQLite file named `game.db` in the
current working directory. The `storage` singleton in `storage.py` initializes
the schema on import, so the database is created as soon as the server starts.

Tables:

- `users` — registered accounts with PBKDF2-HMAC-SHA256 password hashes and salts.
- `sessions` — combat initiative order, round/turn index, and active conditions.
- `compendium_monsters` and `compendium_items` — reusable reference entries.
- `campaigns`, `campaign_characters`, `campaign_events` — campaign state and log.

`POST /v1/storage/reset` drops and recreates all tables. `GET /v1/storage/status`
reports the driver, schema version, and initialization flag.

### Request routing

`api.py` keeps two ordered lists of route tuples: `(compiled_pattern, handler)`.
`Handler.do_GET` and `Handler.do_POST` iterate the corresponding list and invoke
the first handler whose pattern matches the request path. This preserves the
dispatch order of the original implementation, which matters where a more
specific regex could otherwise shadow a shorter exact path.

Dynamic segments (e.g., `/v1/compendium/monsters/{slug}`) are captured by the
regex and passed to the handler as a `re.Match` object.

### Response contract

All JSON responses are sent via `send_json`, which sets `Content-Type` and
`Content-Length`. Error payloads are intentionally coarse-grained (e.g.
`{"error": "invalid request"}`) and match the original behavior.

## Main API / domain groupings

### Core helpers (`/v1/dice/*`, `/v1/checks/*`, `/v1/encounters/*`, `/v1/initiative/*`)

- Dice expression parsing (`2d6+3`, `1d20-1`) and min/max/average stats.
- Ability checks with margin calculation.
- Encounter adjusted XP and difficulty using the DMG multiplier table.
- Deterministic initiative ordering: score descending, then dexterity descending,
  then name ascending.

### Character helpers (`/v1/characters/*`)

- Ability score modifier (floors negative halves).
- Proficiency bonus by level.
- Derived stats: modifiers, AC (base + capped DEX + shield), and max HP.

### Combat (`/v1/combat/sessions/*`)

- Create a session from a list of combatants; the system sorts them and stores
  the order.
- Add conditions to a combatant with a remaining-rounds duration.
- Advance the turn; when the turn wraps, the round increments and the active
  combatant's conditions have their remaining duration decremented.

### Auth (`/v1/auth/*`)

- Register with username validation, password length, and role (`dm` / `player`).
- Login with PBKDF2-HMAC-SHA256 verification and a deterministic session token.

### Compendium (`/v1/compendium/*`)

- Create and read monsters and items by slug.

### Campaigns (`/v1/campaigns/*`)

- Create a campaign, add characters, append events, and read the aggregate
  campaign state (`characters` + `log_count`).

### PHB rules (`/v1/phb/*`)

- Wizard level 5 spell slots.
- Long rest restoration (HP, hit dice, exhaustion).
- Carrying capacity and encumbrance.

### DM tools (`/v1/dm/*`)

- Encounter builder that looks up monsters and returns adjusted XP + difficulty
  recommendation.
- Hardcoded tier-1 loot parcel and deterministic session recap helpers.

## Conventions for extending and testing

### Adding a new endpoint

1. Define the route pattern in `constants.py` if it has dynamic segments, or use
   a literal `re.compile(r"^/v1/...$")` in `api.py`.
2. Add a handler function in `api.py` near the relevant domain group. Handlers
   receive `(handler, match)` for GET and `(handler, match, body)` for POST.
3. Append the tuple to the correct ordered route table. If the route could
   shadow or be shadowed by an existing regex, place it in the same relative
   position as the original implementation.

### Pure logic

Game-rule calculations belong in `domain.py`. They should not import `storage`
or perform I/O. Use the constants from `constants.py` rather than hardcoding
numbers inline.

### Persistence

- Add a new table by extending `Storage._TABLES` in order, then add accessor
  methods. Keep the same return conventions (`True` / `False` for insert
  conflicts, `None` for missing rows, dict/list for reads).
- Update `Storage.reset` only if the new table must be dropped during a reset.

### Testing

The service is designed to be tested by starting it on an ephemeral port and
hitting the HTTP endpoints. The database is local, so reset it between test cases
with `POST /v1/storage/reset` to keep tests deterministic. The default
`log_message` implementation is suppressed so request logs do not clutter stdout.

### Do not change

This is a refactoring checkpoint. Preserve the exact endpoint set, status
codes, response bodies, validation rules, and persistence semantics. The
`storage` singleton, the ordered route tables, and the error-message strings are
all part of the observable behavior that downstream tests rely on.
