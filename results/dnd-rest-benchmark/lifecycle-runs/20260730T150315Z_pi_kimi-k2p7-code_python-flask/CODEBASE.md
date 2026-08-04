# D&D DM Tools API — Codebase Guide

This is a small Flask REST API for D&D 5e DM utilities. It is intentionally
stateless in memory between requests; all durable state lives in a local SQLite
database.

This document describes the implementation **after** the 050 refactoring
checkpoint. The refactor split the previously monolithic `routes.py` into a
`routes/` package organized by domain area, while keeping the same public
URLs, request/response contracts, and persistence behavior.

## Quick start

```bash
PORT=8000 ./run.sh
```

Verify the server is up:

```bash
curl http://127.0.0.1:8000/health
```

Check the storage layer:

```bash
curl http://127.0.0.1:8000/v1/storage/status
```

`run.sh` bootstraps the vendored dependencies in `./.deps` if they are missing
and starts the Flask development server in the foreground on `127.0.0.1` using
the `PORT` environment variable.

## Runtime and framework versions

- Python 3.14.6
- Flask 3.1.3

Pinned in `requirements.txt` and `VERSION-PINS.json`.

## Entry point and module layout

| File | Responsibility |
| ---- | -------------- |
| `app.py` | Creates the Flask application, registers the `routes` blueprint, and runs the server. Calls `storage.reset_db()` on startup so every server process begins with a clean, initialized database. |
| `routes/` | Flask Blueprint and route handlers, split by domain. `routes/__init__.py` defines the shared `api` Blueprint; `routes/_common.py` holds shared validation/response/auth helpers; the other modules register the actual endpoints. |
| `routes/_common.py` | Helpers used by every route module: JSON body parsing, response tuples, auth/header parsing, campaign existence checks, and initiative parsing. |
| `routes/core.py` | Health, storage, dice/checks/encounters, combat sessions, character helpers, auth, compendium, and PHB utilities. |
| `routes/campaigns.py` | Campaign planning surface: characters, events, quests, factions, NPCs, inventory/equipment, downtime crafting, session scheduling, audit/export, and analytics. |
| `routes/play.py` | Play-campaign surface: lobby, membership, turn queue, narration, scenes, location graph, travel/rest, encounter building, and encounter combat. |
| `routes/dm.py` | High-level DM tools that combine domain math with stored data. |
| `domain.py` | Pure, side-effect-free D&D 5e math and static tables (XP, modifiers, dice, rests, initiative, valid races/classes/backgrounds/skills, etc.). |
| `services.py` | Higher-level workflows that combine domain logic with storage (e.g., encounter builder, analytics, risk reports). |
| `storage.py` | SQLite persistence layer. All SQL lives here; routes never touch the database directly. Includes idempotent schema migrations for columns added across checkpoints. |
| `run.sh` | Bootstrap and server start script. |
| `requirements.txt` | Flask dependency pin. |
| `VERSION-PINS.json` | Shared version metadata for the benchmark harness. |
| `game.db` | SQLite database file created automatically next to `app.py`. |

## State, persistence, and routing

### Persistence

- Storage is provided by SQLite in `game.db`.
- The schema version is `1` and is hard-coded in `storage.py`.
- `storage.init_db()` creates tables and back-fills any columns added since the
  initial schema; `storage.reset_db()` drops and recreates all tables (used by
  `POST /v1/storage/reset` and by `app.py` on startup).
- All tables use string primary keys for domain entities (campaigns, combat
  sessions, users, compendium entries, play campaigns). Junction tables enforce
  composite keys.
- Foreign keys are declared in the DDL but are not enabled at runtime; the
  application enforces referential integrity through the storage layer.

### Request routing

Routes live in a single Flask Blueprint (`api`) that is registered in `app.py`.
The Blueprint is populated by importing the `routes/` submodules, so the URL map
is the union of all registered endpoints. The route layer does three things:

1. Parse and validate the JSON body.
2. Call the appropriate domain function, service, or storage function.
3. Return the same JSON body and status code as the previous checkpoint.

Routes do not contain SQL or business math beyond input validation. Repeated
patterns—such as "campaign must exist" or "only the owner may access"—are
factored into helpers in `routes/_common.py` so each endpoint reads as a short
list of contract checks.

### Determinism

- No randomness is used in responses.
- Initiative order, combat turn order, and condition decay are deterministic.
- Passwords are hashed with PBKDF2; the token returned on login is deterministic
  (`session-{username}`).

## Main API groups

### Core utilities

- `GET /health` — liveness check.
- `POST /v1/dice/stats` — statistics for expressions like `2d6+3`.
- `POST /v1/checks/ability` — d20 ability check result.
- `POST /v1/encounters/adjusted-xp` — encounter difficulty for level-3 parties.
- `POST /v1/initiative/order` — deterministic initiative ordering.

### Storage

- `GET /v1/storage/status` — driver/version/initialization status.
- `POST /v1/storage/reset` — drop and recreate the schema.

### Combat sessions

- `POST /v1/combat/sessions` — create a session and store combatants.
- `POST /v1/combat/sessions/<id>/conditions` — attach a condition to a combatant.
- `POST /v1/combat/sessions/<id>/advance` — advance the turn and decay conditions.

### Characters

- `POST /v1/characters/ability-modifier`
- `POST /v1/characters/proficiency`
- `POST /v1/characters/derived-stats`

### Auth

- `POST /v1/auth/register` — create a user with role `dm` or `player`.
- `POST /v1/auth/login` — validate credentials and return a deterministic token.

### Compendium

- `POST /v1/compendium/monsters` and `GET /v1/compendium/monsters/<slug>`
- `POST /v1/compendium/items` and `GET /v1/compendium/items/<slug>`

### Campaigns

- `POST /v1/campaigns`
- `POST /v1/campaigns/<id>/characters`
- `POST /v1/campaigns/<id>/events`
- `GET /v1/campaigns/<id>/state`
- `POST /v1/campaigns/<id>/quests`
- `POST /v1/campaigns/<id>/quests/<quest_id>/progress`
- `GET /v1/campaigns/<id>/quests/summary`
- `POST /v1/campaigns/<id>/factions`
- `POST /v1/campaigns/<id>/npcs`
- `GET /v1/campaigns/<id>/relationships`
- `POST /v1/campaigns/<id>/inventory`
- `POST /v1/campaigns/<id>/characters/<character_id>/equipment`
- `GET /v1/campaigns/<id>/inventory/summary`
- `POST /v1/campaigns/<id>/downtime/crafting`
- `POST /v1/campaigns/<id>/downtime/crafting/<project_id>/advance`
- `POST /v1/campaigns/<id>/sessions`
- `POST /v1/campaigns/<id>/sessions/<session_id>/attendance`
- `GET /v1/campaigns/<id>/sessions/next`
- `GET /v1/campaigns/<id>/audit`
- `GET /v1/campaigns/<id>/export`
- `GET /v1/campaigns/<id>/analytics/summary`
- `POST /v1/campaigns/<id>/analytics/risk-report`

### Player's Handbook helpers

- `POST /v1/phb/spell-slots`
- `POST /v1/phb/rests/long`
- `POST /v1/phb/equipment-load`

### Play campaigns (lobby and turn queue)

These endpoints require a `Authorization: Bearer session-{username}` header and
enforce owner/member roles:

- `POST /v1/play/campaigns` — create a new lobby (DM only).
- `POST /v1/play/campaigns/<id>/members` — join as a player (player only).
- `POST /v1/play/campaigns/<id>/start` — start the campaign (DM only).
- `POST /v1/play/campaigns/<id>/narrations` — append a narration (DM only).
- `GET /v1/play/campaigns/<id>/turn` — read the current turn and queue.
- `POST /v1/play/campaigns/<id>/turn/nudge` — send a turn reminder (DM only).
- `GET /v1/play/campaigns/<id>/document` — read the campaign document (players
  see only the public story; the DM sees the private notes too).
- `PUT /v1/play/campaigns/<id>/document` — update the story and DM notes (DM only).
- `GET /v1/play/campaigns/<id>/my-turn` — player-only view of the current turn.
- `GET /v1/play/campaigns/<id>/gm/status` — DM-only campaign context.
- `POST /v1/play/campaigns/<id>/actions` — submit a player action (only the
  current acting player).
- `POST /v1/play/campaigns/<id>/resolutions` — submit a DM resolution and
  advance the queue.

### Scenes and location graph

- `POST /v1/play/campaigns/<id>/scenes` — create a scene (DM only).
- `POST /v1/play/campaigns/<id>/scenes/<scene_id>/enter` — set the current scene
  and log a scene narration (DM only).
- `POST /v1/play/campaigns/<id>/scenes/<scene_id>/close` — close a scene (DM only).
- `GET /v1/play/campaigns/<id>/scenes/current` — read the current open scene.
- `POST /v1/play/campaigns/<id>/locations` — create a location (DM only).
- `POST /v1/play/campaigns/<id>/locations/<from_id>/connections` — create a
  one-way travel edge (DM only).
- `GET /v1/play/campaigns/<id>/locations/<loc_id>/travel` — list outbound destinations.
- `POST /v1/play/campaigns/<id>/turn/travel` — consume a player turn to travel.
- `POST /v1/play/campaigns/<id>/turn/rest` — consume a player turn to take a
  short or long rest; a long rest restores the actor's `hp_current` to `hp_max`.

### Play-campaign characters

- `POST /v1/play/campaigns/<id>/characters/<char_id>/damage`
- `POST /v1/play/campaigns/<id>/characters/<char_id>/death-saves`
- `GET /v1/play/campaigns/<id>/characters/<char_id>/status`
- `GET /v1/play/campaigns/<id>/characters/<char_id>/owner`
- `POST /v1/play/campaigns/<id>/characters/<char_id>/claim`
- `POST /v1/play/campaigns/<id>/characters/<char_id>/transfer`
- `POST /v1/play/campaigns/<id>/characters/<char_id>/build`
- `POST /v1/play/campaigns/<id>/characters/<char_id>/level-up`
- `POST /v1/play/campaigns/<id>/characters/<char_id>/skill-check`

### Encounters and encounter combat

- `POST /v1/play/campaigns/<id>/encounters` — create an active encounter (DM only).
- `POST /v1/play/campaigns/<id>/encounters/<enc_id>/monsters` — add a monster (DM only).
- `DELETE /v1/play/campaigns/<id>/encounters/<enc_id>/monsters/<monster_id>` — remove a monster (DM only).
- `POST /v1/play/campaigns/<id>/encounters/<enc_id>/combatants` — bind a party member (DM only).
- `DELETE /v1/play/campaigns/<id>/encounters/<enc_id>/combatants/<member>` — unbind a party member (DM only).
- `GET /v1/play/campaigns/<id>/encounters/<enc_id>/turn` — read the current turn.
- `POST /v1/play/campaigns/<id>/encounters/<enc_id>/turn/advance` — advance the encounter turn.
- `POST /v1/play/campaigns/<id>/encounters/<enc_id>/turn/delay` — delay the current turn.
- `POST /v1/play/campaigns/<id>/encounters/<enc_id>/turn/ready` — record a ready action.
- `POST /v1/play/campaigns/<id>/encounters/<enc_id>/actions` — submit a combat action.
- `POST /v1/play/campaigns/<id>/encounters/<enc_id>/damage` — apply damage (DM only).
- `POST /v1/play/campaigns/<id>/encounters/<enc_id>/heal` — apply healing (DM only).
- `POST /v1/play/campaigns/<id>/encounters/<enc_id>/conditions` — add a condition (DM only).
- `GET /v1/play/campaigns/<id>/encounters/<enc_id>/status` — full encounter state.
- `POST /v1/play/campaigns/<id>/encounters/<enc_id>/rewards` — award XP and loot (DM only).
- `POST /v1/play/campaigns/<id>/encounters/<enc_id>/close` — close an encounter (DM only).
- `POST /v1/play/campaigns/<id>/encounters/<enc_id>/end` — end an encounter and return to exploration (DM only).

### DM tools

- `POST /v1/dm/encounter-builder` — builds an encounter from stored monsters.
- `POST /v1/dm/loot-parcel` — fixed tier-1 loot parcel.
- `POST /v1/dm/session-recap` — fixed recap for an existing campaign.

## Conventions for extending and testing

### Adding a new endpoint

1. Put the route in the appropriate `routes/` module inside the `api` Blueprint.
   If the endpoint does not fit any existing module, add a new module and
   import it from `routes/__init__.py`.
2. Keep validation in the route; keep math in `domain.py` and persistence in
   `storage.py`.
3. If the operation needs both storage and domain logic, consider adding a
   function to `services.py`.
4. Return JSON error objects with an `error` key and the same HTTP status codes
   as the existing routes (usually `400`, `401`, `403`, `404`, or `409`).
5. Reuse the helpers in `routes/_common.py` for common response tuples and for
   repeated campaign / play-campaign existence and access checks.

### Adding persistence

1. Add DDL to `storage.py` inside `_CREATE_TABLES`.
2. If a column is added to an existing table, use `_add_column_if_missing` in
   `init_db()` to keep the migration idempotent.
3. Add a public storage function that returns a plain dict, `True`, `None`, or
   `False` — never a raw `sqlite3.Row` or connection.
4. Bump `SCHEMA_VERSION` only when the schema changes in a way that requires
   migration logic or a public contract change.

### Testing

- Use the Flask test client to avoid starting a real server:

```python
from app import app
client = app.test_client()
client.post("/v1/dice/stats", json={"expression": "2d6+3"})
```

- For tests that mutate data, temporarily point `storage.DB_PATH` to a temp file
  before importing `app` to avoid corrupting the production `game.db`.
- Avoid calling `storage.reset_db()` against the real `game.db` from tests.
- You can also smoke-test with `curl` against a running `./run.sh` process.

### Things to preserve

This is a cumulative checkpoint. Do not change HTTP endpoints, response bodies,
status codes, persistence semantics, or validation rules unless the stage
explicitly requires it. The current code is organized to make those behaviors
easy to preserve while refactoring internals.
