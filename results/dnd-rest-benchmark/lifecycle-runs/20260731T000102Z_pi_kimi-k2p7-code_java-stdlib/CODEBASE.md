# D&D Helper API — Codebase Guide

A small, deterministic HTTP API for D&D 5e style helpers. It runs on OpenJDK
with only the Java standard library and shells out to a local `sqlite3` binary
for persistence.

## Quick start

```bash
PORT=8080 ./run.sh
```

`run.sh` compiles the Java sources under `dnd/` and runs `dnd.Main` in the
foreground. The server listens on `127.0.0.1` and honors the `PORT` environment
variable (default `8080`).

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
    RequestRouter.java      # registers top-level HTTP contexts; sub-routes are parsed in domain handlers
    BaseHandler.java        # shared response helpers, exact error JSON constants, Bearer auth
    CoreHandler.java        # health, dice stats, checks, encounter math, initiative, character rules
    CombatHandler.java      # persisted combat sessions
    AuthHandler.java        # user registration and login (PBKDF2 hashing)
    StorageHandler.java     # storage status and reset
    CompendiumHandler.java  # monster and item compendium entries
    CampaignHandler.java    # campaign state, quests, factions, NPCs, inventory, equipment,
                            # crafting, sessions, analytics, and export
    PhbHandler.java         # Player's Handbook helpers: spell slots, rests, equipment load
    DmToolHandler.java      # DM helpers: encounter builder, loot parcel, session recap
    PlayCampaignHandler.java # play-surface campaigns: membership, turn queue, narration,
                             # actions/resolutions, nudges, documents, locations/travel/scenes,
                             # encounters, rewards, character ownership/build/level/skill checks
  server/
    HttpSupport.java        # read request bodies, send JSON responses
  game/
    Rules.java              # dice, XP, encounter difficulty, ability modifiers,
                            # valid race/class/background/skill lists, open-thread derivation
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

All durable state lives in `game.db`, a SQLite database. `Storage` shells out
to the `sqlite3` binary for each query and wraps every public method with a
single `synchronized` lock, because each query is an independent process.
The schema is created lazily by `Storage.init()` and recreated by
`Storage.reset()`.

`Main` calls `storage.reset()` on startup so every benchmark run begins from a
deterministic, empty database. Do not rely on data surviving a server restart.
A JVM shutdown hook stops the `HttpServer` on SIGTERM/SIGINT so the process
exits cleanly when the harness or user terminates it.

Common persistence helpers live in `Storage` as private methods:

- `executeInsert(...)` runs a write transaction and maps `UNIQUE` constraint
  failures to `false` so callers can return `409`.
- `queryCount(...)` simplifies `SELECT COUNT(*) AS c` reads.
- `quote(...)` escapes single quotes for SQLite string literals.
- `addColumnIfMissing(...)` runs `ALTER TABLE ... ADD COLUMN` and ignores
  SQLite "duplicate column name" errors so the schema can evolve safely.

Tables:

- `users` — registered accounts with PBKDF2 hash and salt.
- `combat_sessions`, `combatants`, `conditions` — initiative and condition tracking.
- `monsters`, `monster_tags` — monster compendium.
- `items` — item compendium.
- `campaigns`, `campaign_characters`, `campaign_events`, `quests`,
  `quest_milestones` — campaign state, session log, and quest tracker.
- `factions`, `npcs` — campaign factions and NPCs with relationship disposition.
- `sessions`, `session_attendance` — scheduled campaign sessions and per-character attendance.
- `play_campaigns` — protected play-surface campaigns owned by a `dm` user.
- `play_campaign_members` — player memberships in a play campaign, one row per
  `(campaign_id, username)` and unique `character_id` per campaign.
- `play_campaign_narrations` — append-only campaign log: narration, action,
  resolution, nudge, scene, travel, rest, and combat_action events.
- `play_campaign_scenes` — scene definitions and open/closed status.
- `play_campaign_locations`, `play_campaign_location_connections` — location
  graph and travel-turn cost edges.
- `play_campaign_encounters`, `play_campaign_encounter_monsters`,
  `play_campaign_encounter_combatants`, `play_campaign_encounter_conditions`,
  `play_campaign_encounter_readies`, `play_campaign_encounter_loot` — campaign
  encounters, turn order, HP, conditions, ready actions, and rewards.

### Routing

`Main` creates an `HttpServer` from `com.sun.net.httpserver`, builds a
`RequestRouter`, and calls `router.register(server)` to attach contexts.
`RequestRouter` registers only top-level paths; each domain handler parses
the remainder of the path to route sub-requests. Shared concerns
(authentication, exact error bodies, method checks) live in `BaseHandler`.

Shared handler infrastructure lives in `BaseHandler`:

- `requireMethod`, `badRequest`, `notFound`, `unauthorized`, `forbidden`
- exact JSON error-body constants
- `authenticate` — validates `Authorization: Bearer session-<username>` and
  supports deterministic fixture tokens (`session-dm`, `session-player-a`,
  `session-player-b`, `session-stranger`) even after a storage reset.

Most handlers validate the request body, throw `RuntimeException` on bad input,
and translate any exception into a `400` response. Missing resources return
`404`. Conflicts return `409`.

## Main API / domain groupings

### Core

- `GET /health` — returns `{"ok":true}`.
- `GET /v1/schema` — public, stateless API schema. Returns
  `{"version":"2026-07-29","endpoints":[...]}` with endpoints sorted by
  `method` then `path`. No `Authorization` header is required and no state is
  mutated.
- `POST /v1/dice/stats` — parses an expression like `3d6+2` and returns dice
  count, sides, modifier, min, max, and average.
- `POST /v1/checks/ability` — returns total, success/margin against a DC.
- `POST /v1/encounters/adjusted-xp` — calculates base XP, multiplier,
  adjusted XP, difficulty, and party thresholds.
- `POST /v1/initiative/order` — sorts combatants by `roll + dex`, breaking ties
  by dex then name.
- `POST /v1/characters/ability-modifier` — returns the ability modifier for a score.
- `POST /v1/characters/proficiency` — returns the proficiency bonus for a level.
- `POST /v1/characters/derived-stats` — returns level, proficiency bonus,
  `hp_max`, `armor_class`, and ability modifiers for a class/abilities/armor build.

### Combat sessions

- `POST /v1/combat/sessions` — creates a persisted combat session with a sorted
  order and returns the first active combatant.
- `POST /v1/combat/sessions/{id}/conditions` — adds a timed condition to a
  combatant in the session.
- `POST /v1/combat/sessions/{id}/advance` — advances the turn tracker,
  increments the round on wrap, and decrements/removes conditions on the newly
  active combatant.

### Auth

- `POST /v1/auth/register` — validates username, password length, and role
  (`dm` or `player`), then stores a PBKDF2 hash.
- `POST /v1/auth/login` — verifies the password and returns a deterministic
  `session-{username}` token.

### Storage admin

- `GET /v1/storage/status` — returns driver, schema version, and init flag.
- `POST /v1/storage/reset` — drops and recreates all tables.

### Compendium

- `POST /v1/compendium/monsters` — creates a monster by slug with tags.
- `GET /v1/compendium/monsters/{slug}` — reads the monster.
- `POST /v1/compendium/items` — creates an item by slug.
- `GET /v1/compendium/items/{slug}` — reads the item.

### Campaigns

- `POST /v1/campaigns` — creates a campaign.
- `GET /v1/campaigns/{id}/state` — reads campaign summary with characters and
  log count.
- `POST /v1/campaigns/{id}/characters` — creates a campaign character.
- `POST /v1/campaigns/{id}/events` — logs a campaign event.
- `POST /v1/campaigns/{id}/quests` — creates a quest with milestones.
- `POST /v1/campaigns/{id}/quests/{quest_id}/progress` — marks milestones complete.
- `GET /v1/campaigns/{id}/quests/summary` — returns active/completed/blocked counts.
- `POST /v1/campaigns/{id}/factions` — creates a faction.
- `POST /v1/campaigns/{id}/npcs` — creates an NPC linked to a faction.
- `GET /v1/campaigns/{id}/relationships` — returns faction/NPC counts,
  including `friendly_npcs` (disposition > 0).
- `POST /v1/campaigns/{id}/downtime/crafting` — creates a crafting project.
- `POST /v1/campaigns/{id}/downtime/crafting/{project_id}/advance` — advances
  the project and completes it when `days_completed` reaches `days_required`,
  adding the crafted item to the party inventory.
- `POST /v1/campaigns/{id}/sessions` — schedules a session with an agenda.
- `GET /v1/campaigns/{id}/sessions/next` — returns the earliest scheduled session.
- `POST /v1/campaigns/{id}/sessions/{session_id}/attendance` — records present
  and absent characters and returns counts.
- `GET /v1/campaigns/{id}/analytics/summary` — returns readiness score plus
  counts for open quests, friendly NPCs, scheduled sessions, and inventory items.
- `POST /v1/campaigns/{id}/analytics/risk-report` — returns risk level, missing
  readiness signals, and booleans for `has_dm`, `has_characters`,
  `has_next_session`, and `has_active_quest`.
- `POST /v1/campaigns/{id}/inventory` — adds an item to the campaign inventory.
- `GET /v1/campaigns/{id}/inventory/summary` — returns party/assigned item counts.
- `POST /v1/campaigns/{id}/characters/{character_id}/equipment` — assigns an item
  from party inventory to a character.
- `GET /v1/campaigns/{id}/export` — returns campaign export metadata.
- `GET /v1/campaigns/{id}/audit` — returns audit counts.

### PHB rules

- `POST /v1/phb/spell-slots` — returns level-5 wizard spell slots.
- `POST /v1/phb/rests/long` — applies a long rest: restores HP, reduces hit-dice
  spent, and reduces exhaustion.
- `POST /v1/phb/equipment-load` — returns capacity and encumbered flag.

### DM tools

- `POST /v1/dm/encounter-builder` — looks up monster slugs from the compendium
  and delegates to the same encounter math as `/v1/encounters/adjusted-xp`.
- `POST /v1/dm/loot-parcel` — returns deterministic coins and items.
- `POST /v1/dm/session-recap` — reads the latest campaign event and derives an
  open-thread hook from its summary.

### Play campaigns

All play-campaign endpoints live under `/v1/play/campaigns` and are dispatched
by `PlayCampaignHandler`. Most mutation endpoints require a Bearer token whose
username has the right role and membership/ownership relationship.

- `POST /v1/play/campaigns` — creates a play campaign (DM only).
- `POST /v1/play/campaigns/{id}/members` — player joins a lobby campaign.
- `POST /v1/play/campaigns/{id}/start` — owner starts the campaign when at least
  two members are present.
- `GET /v1/play/campaigns/{id}/turn` — reads current actor, phase, turn number,
  queue, and deterministic timeout metadata.
- `POST /v1/play/campaigns/{id}/turn/nudge` — owner sends a reminder to the
  current actor.
- `POST /v1/play/campaigns/{id}/turn/travel` — active player travels to a
  connected location.
- `POST /v1/play/campaigns/{id}/turn/rest` — active player takes a short or
  long rest.
- `GET /v1/play/campaigns/{id}/my-turn` — player-only turn context.
- `GET /v1/play/campaigns/{id}/gm/status` — owner-only GM turn context.
- `POST /v1/play/campaigns/{id}/narrations` — owner appends a narration event.
- `POST /v1/play/campaigns/{id}/actions` — active player submits an action.
- `POST /v1/play/campaigns/{id}/resolutions` — owner resolves the DM turn.
- `GET /v1/play/campaigns/{id}/document` — role-filtered read of the campaign
  document (players see only `story`).
- `PUT /v1/play/campaigns/{id}/document` — owner updates `story` and `dm_notes`.

### Play campaign locations and scenes

- `POST /v1/play/campaigns/{id}/locations` — owner creates a location.
- `POST /v1/play/campaigns/{id}/locations/{from_id}/connections` — owner creates
  a directed travel connection.
- `GET /v1/play/campaigns/{id}/locations/{loc_id}/travel` — reads outbound
  connections for a location.
- `POST /v1/play/campaigns/{id}/scenes` — owner creates a scene.
- `POST /v1/play/campaigns/{id}/scenes/{scene_id}/enter` — owner sets the current
  scene and appends a `scene` event.
- `POST /v1/play/campaigns/{id}/scenes/{scene_id}/close` — owner closes a scene.
- `GET /v1/play/campaigns/{id}/scenes/current` — reads the current open scene.

### Play campaign encounters

- `POST /v1/play/campaigns/{id}/encounters` — owner creates an encounter.
- `POST /v1/play/campaigns/{id}/encounters/{enc_id}/monsters` — owner adds a
  monster combatant.
- `DELETE /v1/play/campaigns/{id}/encounters/{enc_id}/monsters/{monster_id}` —
  owner removes a monster.
- `POST /v1/play/campaigns/{id}/encounters/{enc_id}/combatants` — owner binds a
  party member to the encounter.
- `DELETE /v1/play/campaigns/{id}/encounters/{enc_id}/combatants/{member}` —
  owner removes a bound member.
- `GET /v1/play/campaigns/{id}/encounters/{enc_id}/turn` — reads the active
  encounter combatant.
- `POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/advance` — advances the
  encounter turn tracker.
- `POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/delay` — active combatant
  or owner moves the current combatant to a later index.
- `POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/ready` — active player
  declares a ready action.
- `POST /v1/play/campaigns/{id}/encounters/{enc_id}/actions` — active player
  submits a combat action.
- `POST /v1/play/campaigns/{id}/encounters/{enc_id}/damage` — owner applies
  damage to a monster or bound party combatant.
- `POST /v1/play/campaigns/{id}/encounters/{enc_id}/heal` — owner applies healing.
- `POST /v1/play/campaigns/{id}/encounters/{enc_id}/conditions` — owner applies a
  condition to a valid encounter target.
- `GET /v1/play/campaigns/{id}/encounters/{enc_id}/status` — reads the encounter
  round, turn index, active combatant, order, and conditions.
- `POST /v1/play/campaigns/{id}/encounters/{enc_id}/rewards` — owner awards XP
  and loot once per encounter.
- `POST /v1/play/campaigns/{id}/encounters/{enc_id}/close` — owner closes the
  encounter.
- `POST /v1/play/campaigns/{id}/encounters/{enc_id}/end` — owner ends the
  encounter and returns the campaign to the exploration phase with the DM as the
  current actor.

### Play campaign characters

- `GET /v1/play/campaigns/{id}/characters/{char_id}/owner` — reads the owner of
  a character.
- `POST /v1/play/campaigns/{id}/characters/{char_id}/claim` — player claims an
  unowned character.
- `POST /v1/play/campaigns/{id}/characters/{char_id}/transfer` — owner transfers
  a character to another player member.
- `POST /v1/play/campaigns/{id}/characters/{char_id}/damage` — owner applies
  damage to a character.
- `POST /v1/play/campaigns/{id}/characters/{char_id}/death-saves` — owner makes a
  death saving throw while unconscious.
- `GET /v1/play/campaigns/{id}/characters/{char_id}/status` — reads character
  HP and status.
- `POST /v1/play/campaigns/{id}/characters/{char_id}/build` — owner validates
  race, class, background, and ability scores and sets level-1 defaults.
- `POST /v1/play/campaigns/{id}/characters/{char_id}/level-up` — owner advances
  the character one level and updates `hp_max`.
- `POST /v1/play/campaigns/{id}/characters/{char_id}/skill-check` — owner makes
  a skill check using the character's ability scores and proficiency.
- `POST /v1/play/campaigns/{id}/characters/{char_id}/spells` — owner adds a
  known spell (`{"spell_id":"fire-bolt","name":"Fire Bolt","level":0}`).
  Wizards may know any spell; rogues and other non-casters may not. Duplicate
  spells return 409; invalid class/spell combinations return 400.
- `GET /v1/play/campaigns/{id}/characters/{char_id}/spells` — any campaign
  member reads the character's spellbook as
  `{"spells":[{"spell_id":"fire-bolt","name":"Fire Bolt","level":0}]}`.
- `PUT /v1/play/campaigns/{id}/characters/{char_id}/prepared-spells` — owner
  sets the character's prepared spells (`{"spell_ids":["fire-bolt"]}`).
  Only wizards may prepare spells, each prepared spell must be known, and the
  count cannot exceed the character's level. Returns 400 for rogues, unknown
  spells, or lists over the limit; returns 403 for non-owners.
- `GET /v1/play/campaigns/{id}/characters/{char_id}/prepared-spells` — any
  campaign member reads prepared spells as
  `{"character_id":"...","prepared_spells":["fire-bolt"],"max_prepared":1}`.
- `POST /v1/play/campaigns/{id}/characters/{char_id}/casts` — owner records
  a spell cast (`{"spell_id":"magic-missile","target":"training-dummy"}`).
  Requires a spellcasting class, a known and prepared spell, and an available
  spell slot of the spell's level. Returns 201 with the cast event, 400 for
  non-spellcasters or unprepared spells, 403 for non-owners, and 409 when no
  slots remain.
- `GET /v1/play/campaigns/{id}/characters/{char_id}/casts` — any campaign
  member reads the character's cast history as `{"casts":[...]}`. Returns
  `[]` when no casts have been recorded.
- `GET /v1/play/campaigns/{id}/characters/{char_id}/inventory/items` — any
  campaign member reads held item stacks.
- `POST /v1/play/campaigns/{id}/characters/{char_id}/inventory/items` — owner
  adds a declared inventory item stack (`{"item_id":"healing-potion","quantity":1}`).
- `DELETE /v1/play/campaigns/{id}/characters/{char_id}/inventory/items/{item_id}` —
  owner removes a held stack quantity.
- `POST /v1/play/campaigns/{id}/characters/{char_id}/inventory/items/{item_id}/consume` —
  owner consumes one unit of a held consumable. Only `healing-potion` is
  consumable; other valid catalog items and unknown IDs return 400, and a
  missing or zero-quantity stack returns 409. Returns 200 with
  `{"character_id":"...","item_id":"...","quantity_consumed":1,"total_quantity":0,"effect":{"type":"healing","hp_restored":5}}`.
- `PUT /v1/play/campaigns/{id}/characters/{char_id}/equipment/{slot}` — owner
  equips a held item into a slot (`armor` or `accessory`).
- `GET /v1/play/campaigns/{id}/characters/{char_id}/equipment/{slot}` — any
  campaign member reads the item equipped in a slot.
- `POST /v1/play/campaigns/{id}/characters/{char_id}/equipment/{slot}/attune` —
  owner attunes an equipped accessory.
- `GET /v1/play/campaigns/{id}/characters/{char_id}/currency` — any campaign
  member reads the character's gold balance (`{"character_id":"...","gold":10}`).
- `POST /v1/play/campaigns/{id}/characters/{char_id}/currency/transfers` —
  the source character owner transfers a positive amount of gold to another
  character in the same campaign. Non-owners receive 403; invalid destinations,
  same-character transfers, and non-positive amounts receive 400; insufficient
  funds receive 409. A valid transfer returns 201 with
  `{"from_character_id":"...","to_character_id":"...","gold":3,"from_gold":7,"to_gold":13,"transfer_id":1}`.

### Play campaign content tags

- `POST /v1/play/campaigns/{id}/content` — DM only. Creates a content record
  (`{"content_id":"content-spider","kind":"scene","text":"A giant spider descends.","tags":["arachnophobia","combat"]}`).
  `content_id`, `kind`, and `text` must be nonempty strings, and `tags` must be a
  nonempty array of unique nonempty strings. Returns 201 with the exact content
  object; players receive 403, unauthenticated requests 401, unknown campaigns
  404, invalid payloads 400, and duplicate `content_id` values 409.
- `PUT /v1/play/campaigns/{id}/content/{content_id}/tags` — DM only. Replaces
  the content record's tags (`{"tags":[...]}`). The replacement list may be empty;
  present tags must be unique nonempty strings. Returns 200 with the updated
  content object; players receive 403, unauthenticated requests 401, unknown
  campaigns or content IDs 404, and invalid payloads 400.
- `GET /v1/play/campaigns/{id}/content` — any authenticated campaign member.
  Returns `{"content":[...]}` in creation order. The optional `exclude_tag=TAG`
  query parameter omits matching tagged records from player responses; the DM
  always receives all records. Empty `exclude_tag` values return 400 and unknown
  campaigns return 404.

### Play campaign loot distribution

- `POST /v1/play/campaigns/{id}/loot` — DM only. Creates an open loot record
  (`{"loot_id":"loot-1","item_id":"healing-potion","quantity":1}`). Duplicate
  `loot_id` values within the campaign return 409; unknown items or non-positive
  quantities return 400.
- `POST /v1/play/campaigns/{id}/loot/{loot_id}/votes` — campaign players only.
  Casts one immutable vote per loot record per player identity
  (`{"recipient_character_id":"play-char-b"}`). Invalid recipients return 400;
  duplicate or changed votes return 409. Returns the running total for the
  chosen recipient.
- `POST /v1/play/campaigns/{id}/loot/{loot_id}/assign` — DM only, no body.
  Assigns the loot to the single unambiguous highest vote recipient, adds the
  quantity to that character's inventory, and closes the loot. Tied or voteless
  loot returns 409; duplicate assignment attempts return 409 and do not add
  inventory again.
- `GET /v1/play/campaigns/{id}/loot/{loot_id}` — any authenticated campaign
  member. Unknown loot returns 404.

### Play campaign NPC agendas

- `POST /v1/play/campaigns/{id}/npcs` — DM only. Creates a campaign NPC with
  `npc_id`, `name`, `agenda`, and `public_status` (all required, nonempty
  strings). Duplicate `npc_id` values within the campaign return 409.
  Returns 201 with the full DM shape including `agenda`.
- `PUT /v1/play/campaigns/{id}/npcs/{npc_id}/agenda` — DM only. Updates the
  NPC's `agenda` and `public_status` (both required, nonempty strings).
  Unknown NPCs return 404. Returns 200 with the full DM shape.
- `GET /v1/play/campaigns/{id}/npcs/{npc_id}` — any authenticated campaign
  member. Unknown NPCs return 404. DM responses include `agenda`; player
  responses include only `npc_id`, `name`, and `public_status`.

### Play campaign calendar and weather

- `POST /v1/play/campaigns/{id}/calendar` — DM only. Initializes the campaign
  calendar with `{"day":1,"season":"spring"}`. `day` must be an integer >= 1
  and `season` must be one of `spring`, `summer`, `autumn`, or `winter`.
  Initializing an already initialized calendar returns 409. Returns the
  calendar object `{"day":1,"season":"spring","weather":"rain"}` using the
  deterministic weather function `(day + season_offset) % 4`.
- `GET /v1/play/campaigns/{id}/calendar` — any authenticated campaign member,
  including the DM. Returns the current calendar object, or 404 if it has not
  been initialized.
- `POST /v1/play/campaigns/{id}/calendar/advance` — DM only. Advances the
  calendar by `{"days":5}`, where `days` must be an integer from 1 through 30.
  Returns the updated calendar object with deterministic weather, or 404 if
  the calendar has not been initialized.

### Play campaign settlements

- `POST /v1/play/campaigns/{id}/settlements` — DM only. Creates a settlement
  with `settlement_id`, `name`, `services`, and `availability`. `services` is a
  nonempty array of unique, nonempty strings trimmed for storage and responses.
  `availability` must be `open`, `limited`, or `closed`. Duplicate
  `settlement_id` values within the campaign return 409. Returns 201 with the
  settlement object including an empty `discovered_by` list.
- `PUT /v1/play/campaigns/{id}/settlements/{settlement_id}` — DM only. Replaces
  `name`, `services`, and `availability`. Unknown settlements return 404.
  Returns 200 with the settlement object, preserving existing `discovered_by`
  order.
- `POST /v1/play/campaigns/{id}/settlements/{settlement_id}/discover` — joined
  campaign players only; the DM receives 403. The first discovery by a player's
  character appends that character ID to `discovered_by` and returns 201. Repeated
  discovery is idempotent and returns 200. The response is player-filtered:
  `discovered_by` contains only the discovering character's ID.
- `GET /v1/play/campaigns/{id}/settlements` — any authenticated campaign member.
  The DM sees every settlement in creation order with the full `discovered_by`
  list. Players see only settlements discovered by their own character, in
  creation order, with `discovered_by` limited to their own character ID.

### Play campaign recipes

- `POST /v1/play/campaigns/{id}/recipes` — DM only. Creates a crafting recipe
  with `recipe_id`, `name`, `ingredients`, `output_item`, and `output_quantity`.
  `ingredients` must be a nonempty object whose keys are valid campaign item
  catalog IDs and whose values are positive integers. `output_item` must be a
  valid catalog ID and `output_quantity` a positive integer. Duplicate
  `recipe_id` values within the campaign return 409. Players and strangers
  receive 403; unknown campaigns return 404; invalid payloads return 400.
  Returns 201 with the exact recipe object.
- `GET /v1/play/campaigns/{id}/recipes` — any authenticated campaign member.
  Returns the list of recipes in creation order as `{"recipes":[...]}`.
- `POST /v1/play/campaigns/{id}/recipes/{recipe_id}/craft` — owner of the
  `character_id` only. The DM receives 403; non-owners receive 403; unknown
  recipes or characters return 404. The character must hold at least every
  required ingredient quantity; otherwise 409 with no state mutation. On success
  the ingredients are consumed atomically and `output_quantity` of `output_item`
  is added to the character inventory. Returns 200 with
  `{"character_id":"...","recipe_id":"...","output_item":"...","output_quantity":...}`.

### Play campaign safe turns

- `POST /v1/play/campaigns/{id}/safe-turns` — campaign members and owner submit
  `{"submission_id":"...","expected_turn":N,"action":"..."}`. Accepted
  submissions advance `current_turn` exactly once and return 201 with
  `{"submission_id":"...","action":"...","accepted_turn":N,"next_turn":N+1}`.
  Duplicate `submission_id` values return 409; stale `expected_turn` values
  return 409 with `{"current_turn":...}` and never advance state.
- `GET /v1/play/campaigns/{id}/safe-turns` — campaign members and owner read
  `{"current_turn":...,"accepted":[...]}` ordered by acceptance.

### Play campaign import validation

- `POST /v1/play/campaigns/{id}/imports` — DM only. Accepts a version-1
  snapshot `{"version":1,"story":"...","status":"lobby|started"}` and
  atomically updates the campaign `story` and `status`. Returns 200 with the
  imported snapshot; invalid payloads return 400 without mutating state. Players,
  strangers, and unauthenticated requests receive 403/401; unknown campaigns
  return 404.
- `GET /v1/play/campaigns/{id}/import-state` — DM only. Returns the last
  successfully imported snapshot as `{"version":1,"story":"...","status":"..."}`,
  or 404 before the first successful import.

### Play campaign rate events

- `POST /v1/play/campaigns/{id}/rate-events` — DM or members. Creates a rate
  event (`{"event_id":"..."}`). Each identity may create up to two accepted
  events per campaign. Returns 201 with
  `{"event_id":"...","actor":"...","remaining":N}`. Returns 429 with
  `{"limit":2,"remaining":0}` when the actor is over limit. Duplicate
  `event_id` values within the campaign and invalid payloads return 400.
- `GET /v1/play/campaigns/{id}/rate-events` — DM or members. Returns accepted
  events in creation order plus the caller's remaining allowance as
  `{"events":[...],"remaining":N}`.

### Play campaign service metrics

- `GET /v1/play/campaigns/{id}/metrics` — DM only. Returns aggregate campaign
  counters as `{"accepted_rate_events":0,"rejected_rate_events":0,"projection_events":0,"uptime_ticks":1}`.

### Play campaign backups

- `POST /v1/play/campaigns/{id}/backups` — DM only. Creates an immutable snapshot
  of the campaign's current public `story` and `status` with a sequential
  `backup_id` (`backup-1`, `backup-2`, ...). Returns 201 with the snapshot
  (`{"backup_id":"...","story":"...","status":"..."}`).
- `GET /v1/play/campaigns/{id}/backups` — DM only. Lists snapshots in creation
  order as `{"backups":[{"backup_id":"...","story":"...","status":"..."}]}`.
- `POST /v1/play/campaigns/{id}/backups/{backup_id}/restore` — DM only. Applies
  the snapshot's `story` and `status` to the campaign without mutating the
  snapshot or creating a new one. Returns 200 with the restored snapshot;
  unknown backup IDs return 404.
  Accepted 087 rate events increment `accepted_rate_events`; 429 rate-limit
  rejections increment `rejected_rate_events`; accepted 079 projection event
  appends increment `projection_events`. Other requests do not affect counters.
  Players and unauthenticated users receive 403/401; unknown campaigns return
  404.

### Play campaign deterministic replay

- `POST /v1/play/campaigns/{id}/replay-events` — DM or members. Appends a
  deterministic replay event (`{"event_id":"replay-1","kind":"append","text":"A"}`).
  `event_id` and `text` must be nonempty strings, `kind` must be exactly
  `append`, and `event_id` must be unique within the campaign replay stream.
  Returns 201 with `{"event_id":"...","kind":"append","text":"...","sequence":N}`.
  Duplicate `event_id` values return 409; invalid payloads return 400.
- `GET /v1/play/campaigns/{id}/replay` — DM or members. Returns the
  deterministic replay state as
  `{"story":"...","event_ids":[...],"digest":"..."}`. The `story` is the
  ordered concatenation of all append event `text` values, `event_ids` is the
  ordered list of successful replay event IDs, and `digest` is
  `join(event_ids, ",") + "|" + story`.
- `GET /v1/play/campaigns/{id}/replay/check` — DM or members. Returns the same
  exact deterministic replay state as `GET /replay` without mutating state.

### Play campaign moderation workflow

- `POST /v1/play/campaigns/{id}/moderation/reports` — any authenticated campaign
  member (including the DM). Submits `{"report_id":"...","target_id":"...","reason":"..."}`.
  Returns 201 with the immutable open report record including `reporter`,
  `status:"open"`, and an append-order `sequence`. Missing/empty fields return
  400; duplicate `report_id` values within the campaign return 409.
- `GET /v1/play/campaigns/{id}/moderation/reports` — any authenticated campaign
  member (including the DM). Returns reports in stable append order as
  `{"reports":[...]}`. Unauthenticated users receive 401, unknown campaigns 404,
  and non-members 403.
- `PUT /v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution` — DM
  only. Accepts `{"action":"allow"|"remove","note":"..."}`. Resolves an open
  report to `status:"resolved"` and returns the updated record with `action`,
  `note`, and `resolver`. Invalid/missing action or empty note returns 400;
  unknown reports return 404; already-resolved reports and player callers return
  409 and 403 respectively.

### Play campaign fixture seeding

- `POST /v1/play/campaigns/{id}/fixture-seeds` — DM only. Seeds the canonical
  fixture with `{"fixture_id":"canonical-v1"}`. The first valid seed returns
  201 with `{"fixture_id":"canonical-v1","status":"seeded","characters":[{"character_id":"fixture-hero","name":"Ari","class":"fighter"},{"character_id":"fixture-mage","name":"Bea","class":"wizard"}],"story":"The lantern is lit.","event_ids":["fixture-event-1","fixture-event-2"]}`. Repeating the same valid seed is idempotent and returns 200 with the same state. Missing, non-string, empty, or any other `fixture_id` returns 400 without mutating state. Players, unauthenticated users, unknown campaigns, and non-owners receive 403/401/404.
- `GET /v1/play/campaigns/{id}/fixture-state` — any authenticated campaign
  member, including the DM. Returns the canonical fixture state, or 404 if no
  fixture has been seeded. Unauthenticated users, unknown campaigns, and
  non-members receive 401/404/403.

## JSON handling

Requests and responses are JSON. The built-in `JsonParser` and `JsonUtils` are
intentionally minimal and preserve the exact output format expected by the
test suite:

- Field order is determined by `LinkedHashMap` insertion order.
- Numbers without a fractional part are serialized as integers.
- Only standard escape sequences are supported.

If you change serialization, ensure the test suite output format stays identical.

## Conventions for extending and testing

1. **Keep handlers stateless.** Handler classes extend `BaseHandler` and hold only
   a `Storage` reference; methods read the request, call storage, and write a
   response. No mutable state should live in handlers.
2. **Use `LinkedHashMap` for deterministic JSON output.** The test suite compares
   exact JSON strings in many places, so shared error response bodies are kept as
   exact string constants in `BaseHandler`.
3. **Preserve the JSON number format.** `JsonUtils.toJson` emits integers for
   whole numbers and doubles otherwise.
4. **Validate with `RuntimeException`.** Handlers catch generic exceptions and
   map them to `400`. Use explicit validation messages for debugging, but never
   leak them in the HTTP body.
5. **Use the storage lock for concurrency.** `Storage` serializes all database
   access. Do not add secondary caches that bypass the lock.
6. **Test via `run.sh`.** Always compile and start the server through
   `./run.sh` before running evaluators. The `sqlite3` binary must be available
   on `PATH`.
7. **When adding an endpoint:** add a handler method in the appropriate domain
   handler, register the top-level path in `RequestRouter.register()` if needed,
   add the sub-path dispatch in the domain handler, and document the expected JSON
   shape in this file.
8. **Refactor with care.** The cumulative test suite checks every prior behavior;
   keep response bodies, status codes, and persistence semantics identical.
   Prefer extracting private helpers and removing duplication over changing logic.
