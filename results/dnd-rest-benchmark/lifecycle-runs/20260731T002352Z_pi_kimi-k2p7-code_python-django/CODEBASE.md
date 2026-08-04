# D&D REST API — Codebase Guide

This is a minimal Django project that implements a deterministic D&D helper
REST API. All business logic is stateless; persistent data lives in a single
SQLite file (`game.db`) next to the project root.

## Quick start

```bash
# Uses the Python 3.14.6 virtual environment already present in the workspace.
PORT=8000 ./run.sh
```

`run.sh` starts Django's development server in the foreground on
`127.0.0.1:$PORT` with `--noreload` so the process is deterministic and easy to
clean up.

Verify the server is up:

```bash
curl http://127.0.0.1:$PORT/health
# -> {"ok": true}
```

## Entry point and major modules

- `manage.py` — Standard Django management entry point.
- `run.sh` — Foreground server launcher.
- `dndsite/settings.py` — Minimal Django settings: `SECRET_KEY`, `DEBUG`,
  `ROOT_URLCONF`, `ALLOWED_HOSTS`, and `INSTALLED_APPS` pointing to
  `dndsite.apps.DndsiteConfig`. No middleware is configured.
- `dndsite/urls.py` — URL routes. All endpoints are mapped to view functions in
  `dndsite/views.py`.
- `dndsite/apps.py` — `DndsiteConfig.ready()` initializes the SQLite schema by
  calling `db.init_db()`.
- `dndsite/db.py` — Persistence layer: SQLite connection context manager,
  schema definitions, `init_db()`, `reset_db()`, `reset_storage()`, and a few
  inventory helper queries.
- `dndsite/domain.py` — Stateless game logic: ability modifiers, proficiency,
  encounter XP, initiative ordering, and combatant parsing.
- `dndsite/constants.py` — Shared constants: schema version, regexes, CR/XP map,
  and level-based XP thresholds.
- `dndsite/http.py` — Common HTTP utilities: JSON body parsing, method guards,
  and standardized JSON error responses.
- `dndsite/views.py` — Thin HTTP view wrappers. Each view validates the request,
  calls domain/db helpers, and returns a `JsonResponse`.

## State, persistence, and request routing

### State

The application has no in-memory mutable state. All persistent data is stored
in `game.db` via SQLite. The connection context manager (`db.db_conn()`) uses a
module-level lock so concurrent requests serialize access to the database.

On startup, `db.init_db()` drops and recreates every table so each benchmark
run starts from a clean, deterministic state. (The development server is
started with `--noreload`, so this happens once per process.)

### Persistence

Tables in dependency order (foreign keys point to earlier tables):

- `users` — registered accounts (username, hashed password, role).
- `combat_sessions` — initiative order and conditions as JSON.
- `monsters` — compendium monsters with CR, AC, HP, and tag list.
- `items` — compendium items with type, rarity, and cost.
- `campaigns` — top-level campaigns with name and DM.
- `factions` — campaign factions and their stance.
- `npcs` — campaign NPCs tied to a faction with a disposition score.
- `campaign_characters` — characters that belong to a campaign.
- `inventory` — per-campaign item stacks owned by `party` or a character.
- `campaign_events` — free-form campaign log entries.
- `sessions` — scheduled play sessions with agenda and attendance JSON.
- `quests` — quests with milestone lists and completed subset.
- `crafting_projects` — per-character downtime crafting progress.
- `play_campaigns` — live-play campaigns with owner, status, turn tracking,
  and story/dm_notes fields.
- `play_campaign_members` — party members in a live-play campaign.
- `narrations` — ordered narration/action/resolution entries for live play.

JSON columns store structured data (initiative order, condition lists, tags,
agenda, attendance, milestones, and narration metadata). The schema version is
reported by `/v1/storage/status` and is resettable via
`POST /v1/storage/reset`. The reset endpoint preserves registered users so that
an authenticated DM survives storage reset and can still own campaigns under
`/v1/play`.

### Request routing

Django's URL resolver maps each path to a view function in `dndsite.views`.
All mutating endpoints are decorated with `@csrf_exempt` because the API is
token-based and does not use Django's session/CSRF machinery. Wrong HTTP methods
return `400 Bad Request` with an empty body (matching the original behavior).

Authorization uses a `Bearer session-<username>` token. The `_get_actor` helper
validates the token shape and resolves the username to a stored role if known;
unknown usernames are treated as players. Missing or malformed tokens produce a
`401` response.

## Main API/domain groupings

1. **Health & storage**
   - `GET /health`
   - `GET /v1/storage/status`
   - `POST /v1/storage/reset`

2. **Auth**
   - `POST /v1/auth/register` (roles: `dm` or `player`)
   - `POST /v1/auth/login` — returns deterministic token `session-{username}`.

3. **Core mechanics**
   - `POST /v1/dice/stats`
   - `POST /v1/checks/ability`
   - `POST /v1/encounters/adjusted-xp`
   - `POST /v1/initiative/order`

4. **Characters**
   - `POST /v1/characters/ability-modifier`
   - `POST /v1/characters/proficiency`
   - `POST /v1/characters/derived-stats`

5. **Combat**
   - `POST /v1/combat/sessions`
   - `POST /v1/combat/sessions/<id>/conditions`
   - `POST /v1/combat/sessions/<id>/advance`

6. **Compendium**
   - `POST /v1/compendium/monsters`
   - `GET /v1/compendium/monsters/<slug>`
   - `POST /v1/compendium/items`
   - `GET /v1/compendium/items/<slug>`

7. **Campaigns**
   - `POST /v1/campaigns`
   - `POST /v1/campaigns/<id>/characters`
   - `POST /v1/campaigns/<id>/events`
   - `GET /v1/campaigns/<id>/state`
   - `POST /v1/campaigns/<id>/factions`
   - `POST /v1/campaigns/<id>/npcs`
   - `GET /v1/campaigns/<id>/relationships`
   - `POST /v1/campaigns/<id>/quests`
   - `POST /v1/campaigns/<id>/quests/<quest_id>/progress`
   - `GET /v1/campaigns/<id>/quests/summary`
   - `POST /v1/campaigns/<id>/inventory`
   - `GET /v1/campaigns/<id>/inventory/summary`
   - `POST /v1/campaigns/<id>/characters/<character_id>/equipment`
   - `POST /v1/campaigns/<id>/downtime/crafting`
   - `POST /v1/campaigns/<id>/downtime/crafting/<project_id>/advance`
   - `GET /v1/campaigns/<id>/audit`
   - `GET /v1/campaigns/<id>/export`
   - `GET /v1/campaigns/<id>/analytics/summary`
   - `POST /v1/campaigns/<id>/analytics/risk-report`

8. **Session scheduling**
   - `POST /v1/campaigns/<id>/sessions`
   - `GET /v1/campaigns/<id>/sessions/next`
   - `POST /v1/campaigns/<id>/sessions/<session_id>/attendance`

9. **PHB rules**
   - `POST /v1/phb/spell-slots` (only wizard level 5 is supported)
   - `POST /v1/phb/rests/long`
   - `POST /v1/phb/equipment-load`

10. **DM tools**
    - `POST /v1/dm/encounter-builder`
    - `POST /v1/dm/loot-parcel` (only tier 1 is supported)
    - `POST /v1/dm/session-recap`

11. **Play campaigns (live turn-based play)**
    - `POST /v1/play/campaigns` (DM only)
    - `POST /v1/play/campaigns/<id>/members` (player only)
    - `POST /v1/play/campaigns/<id>/start` (DM only)
    - `POST /v1/play/campaigns/<id>/narrations` (DM only)
    - `GET /v1/play/campaigns/<id>/turn`
    - `POST /v1/play/campaigns/<id>/turn/nudge` (DM only)
    - `GET /v1/play/campaigns/<id>/my-turn` (player only)
    - `GET /v1/play/campaigns/<id>/gm/status` (DM only)
    - `POST /v1/play/campaigns/<id>/actions` (current player only)
    - `POST /v1/play/campaigns/<id>/resolutions` (DM only)
    - `GET /v1/play/campaigns/<id>/document`
    - `PUT /v1/play/campaigns/<id>/document` (DM only)

## Conventions for extending and testing

- **Keep views thin.** Put pure logic in `domain.py` and persistence in `db.py`. Use `dndsite.http` for shared request parsing and response builders so views stay focused on endpoint-specific validation and orchestration.
- **Preserve response bodies.** The cumulative test suite checks status codes and exact response bodies; error messages returned by `bad_request`, `unauthorized`, `conflict`, `not_found`, and `forbidden` are part of the contract.
- **Use `db_conn()` for all DB access.** It handles commit/rollback and serializes access. Avoid opening SQLite connections outside the context manager.
- **Validate then compute.** Most views parse JSON once, validate required fields, and only then touch the database or domain functions.
- **Determinism matters.** Do not introduce randomness; initiative order, encounter math, and session tokens are all deterministic.
- **Testing.** The project has no formal test suite yet. Use Django's test client in a standalone script or add `tests.py` modules under the `dndsite` app. Run tests with `.venv/bin/python manage.py test`.
