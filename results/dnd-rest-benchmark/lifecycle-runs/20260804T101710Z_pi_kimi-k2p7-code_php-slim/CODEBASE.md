# D&D Helper API — Codebase Guide

A small PHP/Slim API that implements deterministic D&D 5e helper tools:
dice statistics, ability checks, encounter difficulty, character rules,
combat turn tracking, user authentication, a compendium, campaign state,
PHB helpers, DM utilities, crafting, session scheduling, analytics,
and a protected turn-based play surface with a shared campaign document.

## Quick start

```bash
# Install dependencies (already present in vendor/ after composer install)
composer install --no-interaction

# Start the server on the port specified by the PORT environment variable
PORT=8080 ./run.sh
```

`./run.sh` is the only entry point required by the evaluator. It:

1. Removes the existing `game.db` so each run starts fresh.
2. Runs `INIT_DB=1 php index.php` to create the SQLite schema and exit.
3. Starts the PHP built-in server in the foreground on `127.0.0.1:$PORT`.

Verify the server is responding:

```bash
curl http://127.0.0.1:$PORT/health
# => {"ok":true}
```

The server must be stopped with `Ctrl-C` (or by sending `SIGTERM` to the
`run.sh` process). The evaluator starts its own server instance, so this
script is not intended to daemonize.

## Entry point and module layout

```
.
├── index.php              # Slim app bootstrap, middleware, route wiring
├── run.sh                 # Foreground server launcher
├── composer.json          # slim/slim 4.15.2, slim/psr7 1.8.0
├── game.db                # SQLite file created at runtime
├── users.json             # Fixture users re-seeded on storage reset
└── src/
    ├── ResponseHelper.php        # Global respondJson() helper
    ├── GameDatabase.php          # All SQLite schema and CRUD operations
    ├── GameEngine.php            # Stateless game-rule calculations
    └── Handlers/
        ├── HasCampaign.php         # Shared requireCampaign() trait for campaign-scoped handlers
        ├── CoreHandler.php           # health, dice, checks, encounters, initiative
        ├── CharacterHandler.php      # ability modifier, proficiency, derived stats
        ├── CombatHandler.php         # combat sessions, conditions, turn advancement
        ├── AuthHandler.php           # register / login
        ├── StorageHandler.php        # storage status / reset
        ├── CompendiumHandler.php     # monsters, items
        ├── CampaignHandler.php       # campaigns, characters, events, quests, factions, npcs, inventory, equipment, audit, export
        ├── CampaignSessionHandler.php# session scheduling and attendance
        ├── PhbHandler.php            # spell slots, long rest, equipment load
        ├── DmHandler.php             # encounter builder, loot, session recap
        ├── DowntimeHandler.php       # crafting projects
        ├── AnalyticsHandler.php      # campaign readiness and risk reports
        └── PlayHandler.php           # turn-based play surface, scenes, locations, encounters, character sheets, and campaign documents
```

`index.php` is intentionally thin. It loads the autoloader and explicit
source files, creates a `GameDatabase`, initializes the schema, and registers
each handler group with the Slim app. The `INIT_DB=1` CLI shortcut is used by
`run.sh` to create the database file before the web server starts.

All PHP source files use `declare(strict_types=1)` for consistent type
discipline. Handlers validate and cast input before calling the typed
`GameDatabase` and `GameEngine` methods.

## State, persistence, and routing design

### Persistence

State is stored in a single SQLite file (`game.db`) accessed through
`GameDatabase`. The schema has the following tables:

- `users` — username (PK), role, password hash
- `combat_sessions` — id (PK), round, turn_index, JSON order, JSON conditions
- `monsters` — slug (PK), name, CR, AC, HP, JSON tags
- `items` — slug (PK), name, type, rarity, cost in gp
- `campaigns` — id (PK), name, DM
- `characters` — id (PK), campaign_id, name, level, class
- `events` — id (PK), campaign_id, kind, summary
- `quests` — id (PK), campaign_id, title, status, JSON milestones, JSON completed
- `factions` — id (PK), campaign_id, name, stance
- `npcs` — id (PK), campaign_id, name, faction_id, disposition
- `inventory` — id (AUTOINCREMENT), campaign_id, item_slug, quantity, owner
- `equipment` — id (AUTOINCREMENT), campaign_id, character_id, item_slug, quantity
- `crafting_projects` — id (PK), campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status
- `campaign_sessions` — id (PK), campaign_id, starts_at, duration_minutes, JSON agenda
- `session_attendance` — session_id, character_id, status (composite PK)
- `play_campaigns` — id (PK), name, owner, status, max_players, current_actor, turn_number, nudge_count, current_scene_id, current_location_id, phase, pre_combat_actor
- `play_members` — campaign_id, username, character_id (PK), name, class, hp_current, hp_max, status, death_save_successes, death_save_failures, owner, race, background, abilities_json, level
- `narrations` — id (AUTOINCREMENT), campaign_id, sequence, kind, actor, type, target, text
- `play_campaign_documents` — campaign_id (PK), story, dm_notes
- `scenes` — campaign_id, scene_id, name, status (PK on campaign_id, scene_id)
- `locations` — campaign_id, location_id, name (PK on campaign_id, location_id)
- `location_connections` — campaign_id, from_id, to_id, travel_turns (PK on campaign_id, from_id, to_id)
- `play_encounters` — id (PK), campaign_id, name, status, combatants_json, round, turn_index, conditions_json, turn_order_json, ready_actions_json
- `encounter_rewards` — encounter_id (PK), xp, loot_json

JSON columns (`order_json`, `conditions_json`, `tags_json`, `milestones_json`,
`completed_json`, `agenda_json`, `combatants_json`, `turn_order_json`,
`ready_actions_json`, `abilities_json`, `loot_json`) are encoded and decoded
inside `GameDatabase` so callers always work with plain arrays. The encoding uses
`JSON_UNESCAPED_UNICODE` for storage; response encoding is handled separately by
`respondJson()`.

`GameDatabase::initializeSchema()` creates tables with `IF NOT EXISTS`, and
`GameDatabase::reset()` drops them in reverse creation order and recreates them.
`reset()` also re-seeds the fixture users from `users.json` so that play-surface
tests can rely on the well-known `dm`, `player-a`, and `player-b` accounts.

### Routing

The Slim app is configured with:

- `AppFactory::create()` (uses `slim/psr7`)
- Body parsing middleware (so JSON request bodies become arrays)
- Routing middleware
- Error middleware with all display flags disabled (`false, false, false`)

Each handler class exposes a `register(App $app): void` method that maps its
routes. Handler classes are instantiated in `index.php` and receive the
dependencies they need (`GameDatabase`, `GameEngine`, or both). Business logic
is kept out of `index.php` and out of the route closures by using class methods
as first-class callables.

Handlers share common authorization and existence checks through small private
helpers:

- `CampaignHandler`, `CampaignSessionHandler`, `DowntimeHandler`, and
  `AnalyticsHandler` share `requireCampaign()` through the `HasCampaign` trait
  so that every campaign-scoped endpoint returns the same 404 shape.
- `PlayHandler` uses `requirePlayCampaign()` for the same purpose, plus
  `authenticate()` / `requireDm()` / `requirePlayer()` for the Bearer-token
  play surface. `formatRecentEvents()` and `formatParty()` normalize narration
  and member lists for the status endpoints.

### Response format

`respondJson()` writes JSON using
`JSON_PRESERVE_ZERO_FRACTION | JSON_UNESCAPED_SLASHES`.
This preserves values like `10.0` and keeps URLs readable. The helper returns
the PSR-7 response after setting the status code and
`Content-Type: application/json` header.

## API / domain groupings

| Group          | Routes                                                                                                                                                                                                                                                                                                                                 |
|----------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Core           | `GET /health`, `POST /v1/dice/stats`, `POST /v1/checks/ability`, `POST /v1/encounters/adjusted-xp`, `POST /v1/initiative/order`                                                                                                                                                                                                          |
| Characters     | `POST /v1/characters/ability-modifier`, `POST /v1/characters/proficiency`, `POST /v1/characters/derived-stats`                                                                                                                                                                                                                       |
| Combat         | `POST /v1/combat/sessions`, `POST /v1/combat/sessions/{id}/conditions`, `POST /v1/combat/sessions/{id}/advance`                                                                                                                                                                                                                      |
| Auth           | `POST /v1/auth/register`, `POST /v1/auth/login`                                                                                                                                                                                                                                                                                        |
| Storage        | `GET /v1/storage/status`, `POST /v1/storage/reset`                                                                                                                                                                                                                                                                                      |
| Compendium     | `POST /v1/compendium/monsters`, `GET /v1/compendium/monsters/{slug}`, `POST /v1/compendium/items`, `GET /v1/compendium/items/{slug}`                                                                                                                                                                                                    |
| Campaigns      | `POST /v1/campaigns`, `POST /v1/campaigns/{id}/characters`, `POST /v1/campaigns/{id}/events`, `GET /v1/campaigns/{id}/state`, `POST /v1/campaigns/{id}/quests`, `POST /v1/campaigns/{id}/quests/{quest_id}/progress`, `GET /v1/campaigns/{id}/quests/summary`, `POST /v1/campaigns/{id}/factions`, `POST /v1/campaigns/{id}/npcs`, `GET /v1/campaigns/{id}/relationships`, `POST /v1/campaigns/{id}/inventory`, `POST /v1/campaigns/{id}/characters/{character_id}/equipment`, `GET /v1/campaigns/{id}/inventory/summary`, `GET /v1/campaigns/{id}/audit`, `GET /v1/campaigns/{id}/export` |
| Campaign Sessions | `POST /v1/campaigns/{id}/sessions`, `POST /v1/campaigns/{id}/sessions/{session_id}/attendance`, `GET /v1/campaigns/{id}/sessions/next`                                                                                                                                                                                                |
| Downtime       | `POST /v1/campaigns/{id}/downtime/crafting`, `POST /v1/campaigns/{id}/downtime/crafting/{project_id}/advance`                                                                                                                                                                                                                          |
| Play           | `POST /v1/play/campaigns`, `POST /v1/play/campaigns/{id}/members`, `POST /v1/play/campaigns/{id}/start`, `POST /v1/play/campaigns/{id}/narrations`, `POST /v1/play/campaigns/{id}/actions`, `POST /v1/play/campaigns/{id}/resolutions`, `GET /v1/play/campaigns/{id}/turn`, `POST /v1/play/campaigns/{id}/turn/nudge`, `GET /v1/play/campaigns/{id}/my-turn`, `GET /v1/play/campaigns/{id}/gm/status`, `PUT /v1/play/campaigns/{id}/document`, `GET /v1/play/campaigns/{id}/document`, `POST /v1/play/campaigns/{id}/scenes`, `POST /v1/play/campaigns/{id}/scenes/{scene_id}/enter`, `POST /v1/play/campaigns/{id}/scenes/{scene_id}/close`, `GET /v1/play/campaigns/{id}/scenes/current`, `POST /v1/play/campaigns/{id}/locations`, `POST /v1/play/campaigns/{id}/locations/{from_id}/connections`, `GET /v1/play/campaigns/{id}/locations/{loc_id}/travel`, `POST /v1/play/campaigns/{id}/turn/travel`, `POST /v1/play/campaigns/{id}/turn/rest`, `POST /v1/play/campaigns/{id}/encounters`, `POST /v1/play/campaigns/{id}/encounters/{enc_id}/monsters`, `DELETE /v1/play/campaigns/{id}/encounters/{enc_id}/monsters/{monster_id}`, `POST /v1/play/campaigns/{id}/encounters/{enc_id}/combatants`, `DELETE /v1/play/campaigns/{id}/encounters/{enc_id}/combatants/{member}`, `GET /v1/play/campaigns/{id}/encounters/{enc_id}/turn`, `POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/advance`, `POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/delay`, `POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/ready`, `POST /v1/play/campaigns/{id}/encounters/{enc_id}/actions`, `POST /v1/play/campaigns/{id}/encounters/{enc_id}/damage`, `POST /v1/play/campaigns/{id}/encounters/{enc_id}/heal`, `POST /v1/play/campaigns/{id}/characters/{char_id}/damage`, `POST /v1/play/campaigns/{id}/characters/{char_id}/death-saves`, `GET /v1/play/campaigns/{id}/characters/{char_id}/status`, `GET /v1/play/campaigns/{id}/characters/{char_id}/owner`, `POST /v1/play/campaigns/{id}/characters/{char_id}/claim`, `POST /v1/play/campaigns/{id}/characters/{char_id}/transfer`, `POST /v1/play/campaigns/{id}/characters/{char_id}/build`, `POST /v1/play/campaigns/{id}/characters/{char_id}/level-up`, `POST /v1/play/campaigns/{id}/characters/{char_id}/skill-check`, `POST /v1/play/campaigns/{id}/encounters/{enc_id}/conditions`, `GET /v1/play/campaigns/{id}/encounters/{enc_id}/status`, `POST /v1/play/campaigns/{id}/encounters/{enc_id}/rewards`, `POST /v1/play/campaigns/{id}/encounters/{enc_id}/close`, `POST /v1/play/campaigns/{id}/encounters/{enc_id}/end` |
| PHB            | `POST /v1/phb/spell-slots`, `POST /v1/phb/rests/long`, `POST /v1/phb/equipment-load`                                                                                                                                                                                                                                                   |
| DM Tools       | `POST /v1/dm/encounter-builder`, `POST /v1/dm/loot-parcel`, `POST /v1/dm/session-recap`                                                                                                                                                                                                                                              |
| Analytics      | `GET /v1/campaigns/{id}/analytics/summary`, `POST /v1/campaigns/{id}/analytics/risk-report`                                                                                                                                                                                                                                            |

Pure game calculations (ability modifier, proficiency, XP difficulty,
initiative ordering, derived stats, max HP) live in `GameEngine`. All database
access for handlers lives in `GameDatabase`. This split makes the rules easy to
test without a database and keeps request handlers focused on validation and
response shaping.

The play surface uses a deterministic Bearer token scheme (`session-<username>`).
Only users with the `dm` role may create, start, narrate, nudge, or edit the
campaign document. The document exposes the full `story` and `dm_notes` to the
owner and only the `story` to members.

## Conventions for extending and testing

- **Keep handlers thin.** Handlers validate input, call `GameDatabase` or
  `GameEngine`, shape the response, and return it. Avoid adding business rules
  directly in handlers; put them in `GameEngine`.

- **Add new routes by adding a handler method and registering it.** If a new
  domain grows large enough, create a new handler class in `src/Handlers/`,
  require it in `index.php`, instantiate it, and call `register($app)`.

- **Re-use `respondJson()` for every JSON response.** Do not change the JSON
  flags unless the evaluator contract is updated, because the test suite may
  assert exact response bodies including float formatting.

- **Re-use existence helpers.** When a route requires a campaign or play
  campaign to exist, use the shared `HasCampaign::requireCampaign()` trait or the
  private `requirePlayCampaign()` helper so that missing resources always return
  the same 404 shape and ordering is preserved.

- **Database changes go through `GameDatabase`.** Add new tables to
  `initializeSchema()`, add CRUD methods, and update `reset()` to drop them in
  reverse order. Do not issue raw SQL in handlers.

- **Preserve the CLI `INIT_DB` behavior.** `index.php` must exit(0) after schema
  creation when `INIT_DB` is set, so `run.sh` can initialize the database
  before launching the server.

- **Centralize small domain helpers.** `PlayHandler::resolveOwner()` normalizes
  the `owner` fallback logic for play-member rows; use it when checking character
  ownership so that null/empty owner values are handled consistently.

- **Test game logic without a server.** `GameEngine` has no I/O dependencies;
  instantiate it directly and call the rule methods. For integration testing,
  start the server via `run.sh`, use the actual API, and then stop the server.

- **Do not change response bodies, status codes, validation rules, or persistence
  semantics.** This is a cumulative checkpoint; any observable change may break
  the evaluator suite.
