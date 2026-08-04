# D&D Helper API — Codebase Guide

This is a small, deterministic HTTP API for D&D 5e style helpers.
It runs on OpenJDK with only the Java standard library and uses an external `sqlite3` binary for persistence.

## Quick start

```bash
PORT=8080 ./run.sh
```

`run.sh` compiles the Java sources under `dnd/` and runs `dnd.Main` in the foreground.
The server listens on `127.0.0.1` and honors the `PORT` environment variable (default `8080`).

Verify it is up:

```bash
curl http://127.0.0.1:8080/health
# -> {"ok":true}
```

Stop the server with `Ctrl-C`.

## Entry point and major files

```
dnd/
  Main.java                 # entry point: opens the HTTP socket and wires the router
  handlers/
    RequestRouter.java      # all HTTP handler methods and route registration
  server/
    HttpSupport.java        # read request bodies, send JSON responses
  game/
    Rules.java              # dice, XP, encounter difficulty, ability modifiers, etc.
  json/
    JsonParser.java         # minimal recursive-descent JSON parser
    JsonUtils.java          # JSON serialization and int coercion
  model/
    Combatant.java          # initiative combatant
    CombatSession.java      # persisted encounter
    Condition.java          # status condition on a combatant
    User.java               # registered user with salt/hash
  storage/
    Storage.java            # SQLite-backed persistence layer
```

`run.sh` compiles everything with `javac -d .` and then runs `java dnd.Main`.

## State, persistence, and routing design

### Persistence

All durable state lives in `game.db`, a SQLite database.
`Storage` shells out to the `sqlite3` binary for each query and wraps every public method with a single `synchronized` lock, because each query is an independent process.
The schema is created lazily by `Storage.init()` and recreated by `Storage.reset()`.

Tables:
- `users` — registered accounts with PBKDF2 hash and salt.
- `combat_sessions`, `combatants`, `conditions` — initiative and condition tracking.
- `monsters`, `monster_tags` — monster compendium.
- `items` — item compendium.
- `campaigns`, `campaign_characters`, `campaign_events`, `quests`, `quest_milestones` — campaign state, session log, and quest tracker.
- `factions`, `npcs` — campaign factions and NPCs with relationship disposition.
- `sessions`, `session_attendance` — scheduled campaign sessions and per-character attendance.
- `play_campaigns` — protected play-surface campaigns owned by a `dm` user.

### Routing

`Main` creates an `HttpServer` from `com.sun.net.httpserver`, builds a `RequestRouter`, and calls `router.register(server)` to attach all contexts.
The router uses `HttpExchange::getRequestMethod()` and `getRequestURI().getPath()` to dispatch.

Handlers are grouped by domain:

- **Core / dice:** `/health`, `/v1/dice/stats`, `/v1/checks/ability`, `/v1/encounters/adjusted-xp`, `/v1/initiative/order`
- **Character rules:** `/v1/characters/ability-modifier`, `/v1/characters/proficiency`, `/v1/characters/derived-stats`
- **Combat:** `/v1/combat/sessions` (create), `/v1/combat/sessions/{id}/conditions`, `/v1/combat/sessions/{id}/advance`
- **Auth:** `/v1/auth/register`, `/v1/auth/login`
- **Storage:** `/v1/storage/status`, `/v1/storage/reset`
- **Compendium:** `/v1/compendium/monsters` (POST), `/v1/compendium/monsters/{slug}` (GET), `/v1/compendium/items` (POST), `/v1/compendium/items/{slug}` (GET)
- **Campaigns:** `/v1/campaigns` (POST), `/v1/campaigns/{id}/state` (GET), `/v1/campaigns/{id}/characters` (POST), `/v1/campaigns/{id}/events` (POST), `/v1/campaigns/{id}/factions` (POST), `/v1/campaigns/{id}/npcs` (POST), `/v1/campaigns/{id}/relationships` (GET), `/v1/campaigns/{id}/downtime/crafting` (POST), `/v1/campaigns/{id}/downtime/crafting/{project_id}/advance` (POST), `/v1/campaigns/{id}/sessions` (POST), `/v1/campaigns/{id}/sessions/next` (GET), `/v1/campaigns/{id}/sessions/{session_id}/attendance` (POST)
- **PHB rules:** `/v1/phb/spell-slots`, `/v1/phb/rests/long`, `/v1/phb/equipment-load`
- **DM tools:** `/v1/dm/encounter-builder`, `/v1/dm/loot-parcel`, `/v1/dm/session-recap`

Most handlers validate the request body, throw `RuntimeException` on bad input, and translate any exception into a `400` response. Missing resources return `404`. Conflicts return `409`.

### JSON handling

Requests and responses are JSON. The built-in `JsonParser` and `JsonUtils` are intentionally minimal and preserve the exact output format expected by the test suite:

- Field order is determined by `LinkedHashMap` insertion order.
- Numbers without a fractional part are serialized as integers.
- Only standard escape sequences are supported.

If you change serialization, ensure the test suite output format stays identical.

## Main API / domain groupings

### Initiative and combat

- `POST /v1/initiative/order` — sorts combatants by `roll + dex`, breaking ties by dex then name.
- `POST /v1/combat/sessions` — creates a persisted combat session with a sorted order and returns the first active combatant.
- `POST /v1/combat/sessions/{id}/conditions` — adds a timed condition to a combatant in the session.
- `POST /v1/combat/sessions/{id}/advance` — advances the turn tracker, increments the round on wrap, and decrements/removes conditions on the newly active combatant.

### Encounter math

- `POST /v1/encounters/adjusted-xp` — calculates base XP, multiplier, adjusted XP, and difficulty thresholds for a party.
- `POST /v1/dm/encounter-builder` — looks up monster slugs from the compendium and delegates to the same encounter math.

### Compendium and campaigns

- Monsters and items are created by slug and read back by slug.
- Campaigns own characters and a chronological event log.
- `POST /v1/dm/session-recap` reads the latest campaign event and derives an open-thread hook from its summary.
- `POST /v1/campaigns/{id}/factions` creates a campaign faction.
- `POST /v1/campaigns/{id}/npcs` creates a campaign NPC linked to a faction.
- `GET /v1/campaigns/{id}/relationships` returns faction and NPC counts, including `friendly_npcs` (NPCs with `disposition > 0`).
- `POST /v1/campaigns/{id}/downtime/crafting` creates a downtime crafting project for a character (returns `days_completed: 0` and `status: active`).
- `POST /v1/campaigns/{id}/downtime/crafting/{project_id}/advance` advances a project by `days`; when `days_completed` reaches `days_required` the project becomes `complete` and the crafted item is added to the campaign inventory with owner `party`.
- `POST /v1/campaigns/{id}/sessions` schedules a session with an agenda and returns the session id, start time, duration, and `agenda_count`.
- `GET /v1/campaigns/{id}/sessions/next` returns the earliest scheduled session (`id`, `starts_at`, `agenda_count`).
- `POST /v1/campaigns/{id}/sessions/{session_id}/attendance` records present and absent characters and returns the counts.
- `GET /v1/campaigns/{id}/analytics/summary` returns a deterministic readiness score plus counts for open quests, friendly NPCs, scheduled sessions, and inventory items.
- `POST /v1/campaigns/{id}/analytics/risk-report` (body `{"include_zeroes": true}`) returns the campaign risk level, missing readiness signals, and booleans for `has_dm`, `has_characters`, `has_next_session`, and `has_active_quest`.

### Play campaigns

- `POST /v1/play/campaigns` creates a play campaign. Requires an `Authorization: Bearer session-<username>` header; only `dm` users may create. Returns the created campaign with `owner`, `status: "lobby"`, and `max_players`.

### Auth

- `POST /v1/auth/register` — validates username, password length, and role (`dm` or `player`), then stores a PBKDF2 hash.
- `POST /v1/auth/login` — verifies the password and returns a deterministic `session-{username}` token.

## Conventions for extending and testing

1. **Keep handlers stateless.** `RequestRouter` holds a single `Storage` reference; handlers read the request, call storage, and write a response. No mutable state should live in the router.
2. **Use `LinkedHashMap` for deterministic JSON output.** The test suite compares exact JSON strings in many places.
3. **Preserve the JSON number format.** `JsonUtils.toJson` emits integers for whole numbers and doubles otherwise.
4. **Validate with `RuntimeException`.** Handlers catch generic exceptions and map them to `400`. Use explicit validation messages for debugging, but never leak them in the HTTP body.
5. **Use the storage lock for concurrency.** `Storage` serializes all database access. Do not add secondary caches that bypass the lock.
6. **Test via run.sh.** Always compile and start the server through `./run.sh` before running evaluators. The `sqlite3` binary must be available on `PATH`.
7. **When adding an endpoint:** register the context in `RequestRouter.register()`, add a handler method, and document the expected JSON shape in this file.
8. **Refactor with care.** The cumulative test suite checks every prior behavior; keep response bodies, status codes, and persistence semantics identical.
