# D&D DM Tools — Codebase Guide

This is a single-process HTTP service for D&D 5e helper calculations,
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
| `api.py` | HTTP request/response helpers, route tables, the `Handler` class, and endpoint handlers. |
| `storage.py` | SQLite persistence layer. Defines the `Storage` class and the module-level `storage` singleton. |
| `domain.py` | Pure, deterministic game-rule and authentication computations. |
| `constants.py` | Literal game tables, valid choice sets, and compiled route patterns. |
| `run.sh` | Launcher script required by the evaluation harness. |

## State, persistence, and routing

### Persistence

All durable state is stored in a single SQLite file named `game.db` in the
current working directory. The `storage` singleton in `storage.py` initializes
the schema on import, so the database is created as soon as the server starts.

Tables (declared in `Storage._TABLES` in dependency order):

- `users` — registered accounts with PBKDF2-HMAC-SHA256 password hashes and salts.
- `sessions` — combat initiative order, round/turn index, and active conditions.
- `compendium_monsters` and `compendium_items` — reusable reference entries.
- `campaigns`, `campaign_characters`, `campaign_events` — classic campaign state and log.
- `campaign_quests`, `campaign_factions`, `campaign_npcs` — quest and relationship tracking.
- `campaign_inventory`, `crafting_projects` — shared inventory and downtime crafting.
- `campaign_sessions`, `session_attendance` — session scheduling and attendance.
- `play_campaigns`, `play_campaign_members` — live-play campaign lobby, party, and character build state.
- `narrations` — chronological narration, action, travel, rest, scene, and resolution events.
- `campaign_documents` — durable story text and DM-only notes.
- `scenes` — named scenes within a play campaign, each `open` or `closed`.
- `campaign_locations`, `location_connections` — location graph for travel turns.
- `encounters` — active/closed combat encounters with combatants, conditions, and rewards.

`POST /v1/storage/reset` drops and recreates all tables except `users`, keeping
registered actors available across the maintenance reset performed by the
cumulative evaluator suite. `GET /v1/storage/status` reports the driver, schema
version, and initialization flag.

### Request routing

`api.py` keeps four ordered lists of route tuples `(compiled_pattern, handler)`:
`GET_ROUTES`, `POST_ROUTES`, `PUT_ROUTES`, and `DELETE_ROUTES`. The first match
wins, preserving the dispatch order of the original implementation, which
matters where a more specific regex could otherwise shadow a shorter exact path.

`Handler` delegates each HTTP method to `_dispatch`, which iterates the
appropriate route table, passes the `re.Match` object (and parsed JSON body for
mutating methods) to the matched handler, and falls back to
`{"error": "not found"}` with HTTP 404.

Dynamic segments (e.g., `/v1/compendium/monsters/{slug}`) are captured by the
regex and passed to the handler as a `re.Match` object.

### Response contract

All JSON responses are sent via `send_json`, which sets `Content-Type` and
`Content-Length`. Error payloads are intentionally coarse-grained (e.g.
`{"error": "invalid request"}`) and match the original behavior.

### Authentication and access control

- `_authenticate` validates the `Authorization: Bearer session-<username>`
  header and returns the actor along with an error code (401 for missing/
  malformed tokens, 403 for unknown users or role mismatches).
- `_require_auth` sends the appropriate JSON response and returns `None` on
  failure.
- `_load_play_campaign` fetches a live campaign and enforces access: with
  `require_owner=True` the actor must own the campaign; otherwise the actor must
  be either the owner or a party member.
- `_load_encounter` fetches an encounter within a campaign and sends the standard
  404 response when it is missing.
- `_require_encounter_owner` combines owner-only campaign access with encounter
  existence for DM-only encounter mutations.

The legacy `authenticate`, `authenticate_player`, and `authenticate_actor`
functions remain as thin wrappers for compatibility.

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
  The derived-stats endpoint uses a simplified HP formula; class-based progression
  lives in `domain.max_hp_for_level` and is used by the play-campaign build path.

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

### Classic campaigns (`/v1/campaigns/*`)

- Create a campaign, add characters, append events, and read the aggregate
  campaign state (`characters` + `log_count`).
- Manage quests, factions, NPCs, inventory, equipment, crafting, and sessions.
- Audit, export, and analytics endpoints report aggregate counts.

### PHB rules (`/v1/phb/*`)

- Wizard level 5 spell slots.
- Long rest restoration (HP, hit dice, exhaustion).
- Carrying capacity and encumbrance.

### DM tools (`/v1/dm/*`)

- Encounter builder that looks up monsters and returns adjusted XP + difficulty
  recommendation.
- Hardcoded tier-1 loot parcel and deterministic session recap helpers.

### Play campaigns (`/v1/play/campaigns/*`)

- DM-owned live campaigns with a `lobby` -> `active` lifecycle.
- Players join with a character; the DM starts the campaign once at least two
  players have joined.
- Deterministic player/DM round-robin turn queue.
- DM narrations, player actions, travel/rest turns, and DM resolutions advance
  the event log and turn queue.
- Turn nudges track how many times the DM has prompted the current actor.
- `GET /v1/play/campaigns/{id}/document` returns the public story for players and
  both story and `dm_notes` for the DM. `PUT /v1/play/campaigns/{id}/document`
  updates it (DM only).

### Scenes, locations, and encounters (`/v1/play/campaigns/{id}/...`)

- Scenes: DM creates, enters, and closes named scenes. `GET .../scenes/current`
  returns the current open scene for all authorized actors.
- Locations: DM creates locations and directed connections with travel-turn
  costs. Authorized actors can list reachable destinations from a location.
- Encounters: DM creates encounters, adds/removes monster combatants, and
  binds/unbinds party members. Party members act on their initiative turn.
- Damage/healing applies to encounter combatants and updates monster state or
  the bound party member's persistent HP.
- Conditions apply to a combatant by `monster_id` or member username and expire
  at the start of that combatant's next active turn.
- Delay and ready actions allow a player to reposition in initiative or declare
  a triggered action.
- Rewards (XP and loot) are recorded once per encounter; closing and ending an
  encounter transitions back to exploration.

### Play-campaign characters (`/v1/play/campaigns/{id}/characters/{cid}/...`)

- Ownership can be claimed by a party member and transferred to another party
  member.
- The owner builds the character with race, class, background, and ability scores,
  producing level-1 HP, hit dice, and proficiency bonus.
- Level-up advances by exactly one level at a time using `domain.max_hp_for_level`.
- Skill checks combine an ability score, proficiency bonus, and a declared
  proficiency.
- Damage, death saves, and status endpoints track durable HP and death-save
  state.

## Conventions for extending and testing

### Adding a new endpoint

1. Define the route pattern in `constants.py` if it has dynamic segments, or use
   a literal `re.compile(r"^/v1/...$")` in `api.py`.
2. Add a handler function in `api.py` near the relevant domain group. Handlers
   receive `(handler, match)` for GET and `(handler, match, body)` for POST/PUT/
   DELETE.
3. Append the tuple to the correct ordered route table. If the route could
   shadow or be shadowed by an existing regex, place it in the same relative
   position as the original implementation.
4. Reuse `_load_play_campaign`, `_load_encounter`, and `_require_encounter_owner`
   for access control when the existing semantics match; otherwise keep the
   explicit checks to preserve exact status-code ordering.

### Pure logic

Game-rule calculations belong in `domain.py`. They should not import `storage`
or perform I/O. Use the constants from `constants.py` rather than hardcoding
numbers inline.

### Persistence

- Add a new table by extending `Storage._TABLES` in order (order matters for
  `CREATE` and `DROP` during reset), then add accessor methods. Use the
  `_connection()` context manager to ensure every connection is closed. Keep the
  same return conventions (`True` / `False` for insert conflicts, `None` for
  missing rows, dict/list for reads).
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
