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
- `dndsite/urls.py` — URL routes. Endpoints are imported from the
  `dndsite.views` package.
- `dndsite/apps.py` — `DndsiteConfig.ready()` initializes the SQLite schema by
  calling `db.init_db()`.
- `dndsite/db.py` — Persistence layer: SQLite connection context manager,
  schema definitions, `init_db()`, `reset_db()`, `reset_storage()`, and a few
  inventory helper queries.
- `dndsite/domain.py` — Stateless game logic: ability modifiers, proficiency,
  encounter XP, initiative ordering, and combatant parsing.
- `dndsite/constants.py` — Shared constants: schema version, regexes, CR/XP map,
  level-based XP thresholds, and valid character choices.
- `dndsite/http.py` — Common HTTP utilities: JSON body parsing, method guards,
  and standardized JSON error responses.
- `dndsite/views/` — Django views split into domain modules.
  - `__init__.py` re-exports all view functions so `dndsite.urls` can import
    them from a single package.
  - `common.py` — shared authorization helpers (`_get_actor`, `require_actor`,
    `require_play_campaign_owner`, `require_play_campaign_dm_owner`,
    `require_play_campaign_member_or_owner`).
  - `core.py` — health, storage, auth, dice, checks, and initiative.
  - `characters.py` — character ability/proficiency/derived-stat endpoints.
  - `combat.py` — basic combat sessions.
  - `compendium.py` — monsters and items.
  - `campaigns.py` — classic campaigns, factions, NPCs, inventory, crafting,
    sessions, audit, export, and analytics.
  - `phb.py` — PHB rules (spell slots, rests, encumbrance).
  - `dm_tools.py` — DM encounter builder, loot parcel, and session recap.
  - `play_campaigns.py` — live-play campaign creation, joining, turns,
    actions, resolutions, and documents.
  - `scenes.py` — scene state for live play.
  - `locations.py` — location graph, travel, and rest turns.
  - `encounters.py` — encounter creation, monsters, combatant binding, turn
    order, damage/healing, conditions, and rewards.
  - `characters_live.py` — live-play character ownership, builds, level-up,
    death saves, and skill checks.

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
- `scenes` — live-play scenes and their open/closed status.
- `play_campaign_members` — party members in a live-play campaign.
- `narrations` — ordered narration/action/resolution entries for live play.
- `locations` — locations within a live-play campaign.
- `location_connections` — directed travel edges between locations.
- `encounters` — active encounters with combatants, conditions, and turn order.
- `readied_actions` — player readied actions during encounters.
- `encounter_rewards` — XP and loot awarded after an encounter.

JSON columns store structured data (initiative order, condition lists, tags,
agenda, attendance, milestones, abilities, and narration metadata). The schema
version is reported by `/v1/storage/status` and is resettable via
`POST /v1/storage/reset`. The reset endpoint preserves registered users so that
an authenticated DM survives storage reset and can still own campaigns under
`/v1/play`.

### Request routing

Django's URL resolver maps each path to a view function re-exported by
`dndsite.views`. All mutating endpoints are decorated with `@csrf_exempt`
because the API is token-based and does not use Django's session/CSRF
machinery. Wrong HTTP methods return `400 Bad Request` with an empty body
(matching the original behavior).

Authorization uses a `Bearer session-<username>` token. The `_get_actor` helper
in `dndsite.views.common` validates the token shape and resolves the username
to a stored role if known; unknown usernames are treated as players. Missing or
malformed tokens produce a `401` response. Shared helpers such as
`require_play_campaign_owner` and `require_play_campaign_member_or_owner`
centralize the most common campaign ownership and membership checks so that
individual views stay focused on endpoint-specific validation. Both helpers now
return the full campaign row, so owner/member views such as `get_play_turn`,
`get_gm_status`, `nudge_play_turn`, `campaign_document`, and
`get_current_scene` can read turn state, scene/location ids, and document fields
directly without re-querying the same row.

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
    - `POST /v1/play/campaigns/<id>/turn/nudge` (owner only)
    - `GET /v1/play/campaigns/<id>/my-turn` (player only)
    - `GET /v1/play/campaigns/<id>/gm/status` (owner only)
    - `POST /v1/play/campaigns/<id>/actions` (current player only)
    - `POST /v1/play/campaigns/<id>/resolutions` (DM only)
    - `POST /v1/play/campaigns/<id>/encounters` (DM only)
    - `GET /v1/play/campaigns/<id>/document`
    - `PUT /v1/play/campaigns/<id>/document` (DM only)

12. **Scenes**
    - `POST /v1/play/campaigns/<id>/scenes`
    - `GET /v1/play/campaigns/<id>/scenes/current`
    - `POST /v1/play/campaigns/<id>/scenes/<scene_id>/enter`
    - `POST /v1/play/campaigns/<id>/scenes/<scene_id>/close`

13. **Location graph**
    - `POST /v1/play/campaigns/<id>/locations`
    - `POST /v1/play/campaigns/<id>/locations/<from_id>/connections`
    - `GET /v1/play/campaigns/<id>/locations/<loc_id>/travel`
    - `POST /v1/play/campaigns/<id>/turn/travel`
    - `POST /v1/play/campaigns/<id>/turn/rest`

14. **Encounters**
    - `POST /v1/play/campaigns/<id>/encounters`
    - `POST /v1/play/campaigns/<id>/encounters/<enc_id>/monsters`
    - `DELETE /v1/play/campaigns/<id>/encounters/<enc_id>/monsters/<monster_id>`
    - `POST /v1/play/campaigns/<id>/encounters/<enc_id>/combatants`
    - `DELETE /v1/play/campaigns/<id>/encounters/<enc_id>/combatants/<member>`
    - `GET /v1/play/campaigns/<id>/encounters/<enc_id>/turn`
    - `POST /v1/play/campaigns/<id>/encounters/<enc_id>/turn/advance`
    - `POST /v1/play/campaigns/<id>/encounters/<enc_id>/turn/delay`
    - `POST /v1/play/campaigns/<id>/encounters/<enc_id>/turn/ready`
    - `POST /v1/play/campaigns/<id>/encounters/<enc_id>/actions`
    - `POST /v1/play/campaigns/<id>/encounters/<enc_id>/damage`
    - `POST /v1/play/campaigns/<id>/encounters/<enc_id>/heal`
    - `POST /v1/play/campaigns/<id>/encounters/<enc_id>/conditions`
    - `GET /v1/play/campaigns/<id>/encounters/<enc_id>/status`
    - `POST /v1/play/campaigns/<id>/encounters/<enc_id>/rewards`
    - `POST /v1/play/campaigns/<id>/encounters/<enc_id>/end`
    - `POST /v1/play/campaigns/<id>/encounters/<enc_id>/close`

15. **Live characters**
    - `POST /v1/play/campaigns/<id>/characters/<char_id>/damage`
    - `POST /v1/play/campaigns/<id>/characters/<char_id>/death-saves`
    - `GET /v1/play/campaigns/<id>/characters/<char_id>/status`
    - `GET /v1/play/campaigns/<id>/characters/<char_id>/owner`
    - `POST /v1/play/campaigns/<id>/characters/<char_id>/claim`
    - `POST /v1/play/campaigns/<id>/characters/<char_id>/transfer`
    - `POST /v1/play/campaigns/<id>/characters/<char_id>/build`
    - `POST /v1/play/campaigns/<id>/characters/<char_id>/level-up`
    - `POST /v1/play/campaigns/<id>/characters/<char_id>/skill-check`

## Conventions for extending and testing

- **Keep views thin.** Put pure logic in `domain.py` and persistence in `db.py`.
  Use `dndsite.http` for shared request parsing and response builders and
  `dndsite.views.common` for common authorization checks so views stay focused
  on endpoint-specific validation and orchestration. Avoid copying boilerplate
  imports across view modules; import only what each module actually uses.
- **Preserve response bodies.** The cumulative test suite checks status codes
  and exact response bodies; error messages returned by `bad_request`,
  `unauthorized`, `conflict`, `not_found`, and `forbidden` are part of the
  contract.
- **Use `db_conn()` for all DB access.** It handles commit/rollback and
  serializes access. Avoid opening SQLite connections outside the context
  manager.
- **Validate then compute.** Most views parse JSON once, validate required
  fields, and only then touch the database or domain functions.
- **Determinism matters.** Do not introduce randomness; initiative order,
  encounter math, and session tokens are all deterministic.
- **Prefer shared helpers.** When adding new live-play endpoints, use the
  helpers in `dndsite.views.common` for authentication, DM ownership, and
  member-or-owner visibility so the same error semantics are reused across
  the codebase.
- **Testing.** The project has no formal test suite yet. Use Django's test
  client in a standalone script or add `tests.py` modules under the `dndsite`
  app. Run tests with `.venv/bin/python manage.py test`.
