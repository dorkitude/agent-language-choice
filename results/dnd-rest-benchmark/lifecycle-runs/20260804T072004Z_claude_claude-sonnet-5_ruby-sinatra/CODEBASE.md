# CODEBASE.md

A D&D-flavored REST API built with Sinatra (classic style), Rack, and Puma,
backed by SQLite. This document describes the implementation as it exists
after the checkpoint-50 refactor — no aspirational or planned design.

## Starting and verifying the server

```bash
bundle install         # first run only
./run.sh                # starts Puma in the foreground on 127.0.0.1:$PORT
```

`run.sh` runs `bundle exec ruby app.rb -o 127.0.0.1 -p "$PORT"`. `PORT` must
be set in the environment; there is no default.

Verify it's up:

```bash
curl http://127.0.0.1:$PORT/health
# => {"ok":true}
```

Every response (success or error) is `Content-Type: application/json`,
enforced by a global `before` filter in `app.rb`.

## Entry point and module layout

`app.rb` is the process entry point. It is a **classic-style** Sinatra app —
`require 'sinatra'` extends the top-level (`main`) object with Sinatra's DSL
(`get`, `post`, `before`, `halt`, `params`, `status`, ...), and every file
loaded via `require_relative` from `app.rb` shares that same top-level
context. This is what lets `routes/*.rb` call plain `get`/`post` and the
helpers in `lib/*.rb` without any explicit `include` — they're all just
methods on `Object`, visible everywhere in the process.

```
app.rb                     entry point: require order, schema init, before filter
lib/
  database.rb               DB connection (per-thread) + schema DDL (CREATE/DROP TABLE)
  request_helpers.rb         json_body, numericish, integerish, valid_username?, valid_slug?
  security.rb                 PBKDF2 password hashing/verification
  dnd_rules.rb                 CR/XP tables, level thresholds, spell slots, loot tiers,
                               and the pure math built on them (count_multiplier,
                               ability_modifier, proficiency_bonus, party_xp_thresholds,
                               difficulty_for_xp)
  combat_session.rb           initiative ordering (order_combatants) + combat session
                               load/save/active-combatant/conditions-payload helpers
  campaigns.rb                 campaign_exists? (shared by routes/campaigns.rb, routes/dm.rb,
                               routes/audit.rb, routes/analytics.rb)
  analytics.rb                 deterministic readiness/risk aggregation shared by
                               routes/analytics.rb (campaign_analytics_counts,
                               campaign_analytics_signals)
  play_auth.rb                 authenticate_play_request! — bearer-token auth for
                               the /v1/play surface
  play_campaigns.rb            shared lookups for /v1/play routes: find_play_campaign!,
                               find_play_encounter!, require_play_owner!,
                               require_play_participant!, membership checks,
                               event-log append/read helpers, and the
                               encounter initiative/condition/HP-delta math
routes/
  core.rb                     GET /health, dice stats, ability checks, adjusted XP, initiative order
  characters.rb                ability modifier, proficiency bonus, derived stats
  combat.rb                    combat session create/apply-condition/advance-turn
  auth.rb                      register/login
  compendium.rb                 monsters and items (create + fetch by slug)
  campaigns.rb                  campaigns, nested characters, nested events, state summary
  phb.rb                        spell slots, long rest recovery, equipment load/encumbrance
  dm.rb                         encounter builder, loot parcel, session recap
  storage.rb                    storage status, full reset
  quests.rb                     quest creation, milestone progress, quest summary
  npcs.rb                       factions, NPCs, faction/NPC relationship summary
  inventory.rb                  party inventory, character equipment, inventory summary
  downtime.rb                   downtime crafting projects and day-by-day advance
  sessions.rb                   scheduled sessions, attendance, next-session lookup
  audit.rb                      per-campaign audit counts and export summary
  analytics.rb                  readiness summary and maintenance risk report
  play/                         the /v1/play campaign-play surface, split by sub-domain
                               (large enough to outgrow a single file — see below)
    campaigns.rb                 create campaign, join as a member, start play
    turns.rb                     narrations, actions, resolutions, turn/gm-status/
                               my-turn reads, nudge, short/long rest
    document.rb                  campaign document (story + DM-only notes)
    scenes.rb                    scene create/enter/close, current-scene lookup
    locations.rb                 location graph, connections, travel
    encounters.rb                encounter/combat: roster, initiative turns,
                               damage/heal, conditions, rewards
    characters.rb                 per-character play state: damage, death saves,
                               ownership/claim/transfer, build, level-up, skill checks
```

Because everything shares one top-level context, **route files are loaded
after every `lib/` file** in `app.rb` — order matters only in that the
helpers must be defined before the routes that call them are *invoked* (not
before they're *defined*, since Ruby method lookups happen at call time).
The current require order in `app.rb` is deliberately grouped:
`lib/*` first, then `routes/*`.

## State, persistence, and request routing

- **Storage:** a single SQLite file, `game.db`, at the project root
  (`lib/database.rb::DB_PATH`). WAL journal mode is enabled per connection.
- **Connection lifetime:** one `SQLite3::Database` per Ruby thread, memoized
  on `Thread.current[:db]` (see `lib/database.rb::db`). Puma may dispatch
  requests on different threads, so connections are never shared across
  threads.
- **Schema:** `init_schema!` runs once at boot (`app.rb`) and is idempotent
  (`CREATE TABLE IF NOT EXISTS`). Every table's full column set is defined
  directly in `init_schema!` — there is no separate migration path, because
  `lib/database.rb` deletes `game.db` (and its WAL/SHM files) at process
  boot, before `init_schema!` ever runs, so every server start is a fresh
  schema. `POST /v1/storage/reset` calls `reset_schema!`, which drops and
  recreates every table — a full wipe used by test setup/teardown, not a
  migration.
- **Tables:** `schema_meta`, `users`, `combat_sessions`, `monsters`, `items`,
  `campaigns`, `campaign_characters`, `campaign_events`, `campaign_quests`,
  `campaign_factions`, `campaign_npcs`, `campaign_inventory`,
  `campaign_equipment`, `campaign_crafting_projects`, `campaign_sessions`,
  `campaign_session_attendance`, `play_campaigns`, `play_campaign_members`,
  `play_campaign_events`, `play_scenes`, `play_locations`,
  `play_location_connections`, `play_character_owners`, `play_encounters`.
  Combat session state (initiative order, active conditions) is stored as
  JSON blobs (`order_json`, `conditions_json`) rather than normalized — see
  `lib/combat_session.rb` for the (de)serialization boundary. Encounter
  rosters and conditions follow the same pattern on `play_encounters`
  (`combatants_json`, `conditions_json`, `turn_order_json`) — see
  `lib/play_campaigns.rb` for that (de)serialization boundary.
- **Routing:** plain Sinatra route blocks, one file per domain under
  `routes/`. There is no router abstraction beyond Sinatra's own — each
  route function does its own body parsing (`json_body`), field validation
  (`halt 400/404/409` inline), and response serialization (`.to_json`).
- **Auth:** `/v1/auth/login` returns a placeholder bearer token
  (`"session-<username>"`) backed by no session store — any well-formed
  token naming a real user is accepted (see `lib/play_auth.rb`). The
  original `/v1/campaigns/*` surface does not check it at all (unchanged
  from earlier checkpoints). The newer `/v1/play/*` surface (`routes/play/*.rb`)
  *does* enforce it: every route calls `authenticate_play_request!` first,
  then applies its own role/ownership/membership check.

## API/domain groupings

| Domain | Routes | File |
|---|---|---|
| Core/math | `/health`, `/v1/dice/stats`, `/v1/checks/ability`, `/v1/encounters/adjusted-xp`, `/v1/initiative/order` | `routes/core.rb` |
| Characters | `/v1/characters/ability-modifier`, `/v1/characters/proficiency`, `/v1/characters/derived-stats` | `routes/characters.rb` |
| Combat | `/v1/combat/sessions`, `/v1/combat/sessions/:id/conditions`, `/v1/combat/sessions/:id/advance` | `routes/combat.rb` |
| Auth | `/v1/auth/register`, `/v1/auth/login` | `routes/auth.rb` |
| Compendium | `/v1/compendium/monsters[/:slug]`, `/v1/compendium/items[/:slug]` | `routes/compendium.rb` |
| Campaigns | `/v1/campaigns`, `/v1/campaigns/:id/characters`, `/v1/campaigns/:id/events`, `/v1/campaigns/:id/state` | `routes/campaigns.rb` |
| PHB rules | `/v1/phb/spell-slots`, `/v1/phb/rests/long`, `/v1/phb/equipment-load` | `routes/phb.rb` |
| DM tools | `/v1/dm/encounter-builder`, `/v1/dm/loot-parcel`, `/v1/dm/session-recap` | `routes/dm.rb` |
| Storage | `/v1/storage/status`, `/v1/storage/reset` | `routes/storage.rb` |
| Quests | `/v1/campaigns/:id/quests`, `/v1/campaigns/:id/quests/:qid/progress`, `/v1/campaigns/:id/quests/summary` | `routes/quests.rb` |
| NPCs/Factions | `/v1/campaigns/:id/factions`, `/v1/campaigns/:id/npcs`, `/v1/campaigns/:id/relationships` | `routes/npcs.rb` |
| Inventory | `/v1/campaigns/:id/inventory`, `/v1/campaigns/:id/characters/:cid/equipment`, `/v1/campaigns/:id/inventory/summary` | `routes/inventory.rb` |
| Downtime | `/v1/campaigns/:id/downtime/crafting`, `/v1/campaigns/:id/downtime/crafting/:pid/advance` | `routes/downtime.rb` |
| Sessions | `/v1/campaigns/:id/sessions`, `/v1/campaigns/:id/sessions/:sid/attendance`, `/v1/campaigns/:id/sessions/next` | `routes/sessions.rb` |
| Audit | `/v1/campaigns/:id/audit`, `/v1/campaigns/:id/export` | `routes/audit.rb` |
| Analytics | `/v1/campaigns/:id/analytics/summary`, `/v1/campaigns/:id/analytics/risk-report` | `routes/analytics.rb` |
| Play: campaigns | `POST /v1/play/campaigns`, `.../:id/members`, `.../:id/start` | `routes/play/campaigns.rb` |
| Play: turns | `.../narrations`, `.../actions`, `.../resolutions`, `.../turn`, `.../turn/nudge`, `.../gm/status`, `.../my-turn`, `.../turn/rest` | `routes/play/turns.rb` |
| Play: document | `GET/PUT .../:id/document` | `routes/play/document.rb` |
| Play: scenes | `.../scenes`, `.../scenes/:scene_id/{enter,close}`, `.../scenes/current` | `routes/play/scenes.rb` |
| Play: locations | `.../locations`, `.../locations/:from_id/connections`, `.../locations/:loc_id/travel`, `.../turn/travel` | `routes/play/locations.rb` |
| Play: encounters | `.../encounters[/:enc_id/{monsters,combatants,damage,heal,end,turn,turn/advance,turn/delay,turn/ready,conditions,status,actions,rewards,close}]` | `routes/play/encounters.rb` |
| Play: characters | `.../characters/:char_id/{damage,death-saves,status,owner,claim,transfer,build,level-up,skill-check}` | `routes/play/characters.rb` |

This grouping matches the evaluator's own suite names (`core`,
`characters`, `combat-state`, `auth-users`, `compendium`, `campaign-state`,
`phb-rules`, `dm-tools`, `sqlite-storage`, `quest-tracker`,
`npcs-factions`, `inventory-equipment`, `downtime-crafting`,
`session-scheduling`, `audit-export`, `analytics-reporting`, and the
`campaign-*`/`gm-*`/`player-*`/`role-authorization`/`turn-*`/`scene-*`/
`location-*`/`encounter-*`/`combat-*`/`character-*` play suites) closely
enough that a failing test suite usually maps to one or two route files.

## Campaign-play turn model (`routes/play/turns.rb`, `routes/play/encounters.rb`)

A `play_campaigns` row is a lobby until the DM starts it (`POST
.../start`, requires 2+ members), at which point `current_actor`,
`turn_number`, and `turn_index` are initialized. Turn order then alternates
strictly between "the active player" and "the DM":

1. The active player calls `POST .../actions` — this appends an `action`
   event and hands `current_actor` to the DM (`campaign['owner']`).
2. The DM calls `POST .../resolutions` — this appends a `resolution` event,
   advances `turn_index` to the next member (wrapping via `% members.length`),
   increments `turn_number`, and hands `current_actor` to that member.

`GET .../turn` derives a display `queue` by interleaving every member with
`'dm'` (`[p1, dm, p2, dm, ...]`) — this is presentation only, it does not
drive whose turn it actually is; `current_actor`/`turn_index` on the row is
the source of truth. `logical_deadline` is `turn_number +
TURN_TIMEOUT_LOGICAL_TICKS`, a pure function of the stored turn number —
never wall-clock time — so the API stays deterministic across runs.
`overdue` is always `false`; there is no timeout enforcement, only the
DM-facing `POST .../turn/nudge` counter.

Encounters layer a second, independent turn loop on top of this: starting an
encounter (`POST .../encounters`) flips the campaign into `phase: 'combat'`
and snapshots the exploration turn (`pre_combat_actor`/`turn_index`/
`turn_number`) so `POST .../encounters/:id/end` can resume exploration
exactly where it left off. Within an encounter, `turn_index`/`round` on
`play_encounters` track initiative order (`encounter_combat_order` in
`lib/play_campaigns.rb`, with an optional `turn_order_json` override written
by `.../turn/delay`) — this is independent of the party's `current_actor`.

`lib/play_campaigns.rb` centralizes the lookups every route needs:
`find_play_campaign!` and `find_play_encounter!` (404 if missing),
`require_play_owner!` (403 unless the caller is the campaign's DM),
`require_play_participant!` (403 unless the caller is the owner or a joined
member — returns whether the caller is the owner, since a few routes shape
their response differently for the DM), `insert_play_event`/
`recent_play_events` for the shared `play_campaign_events` log, and the
encounter-only helpers (`encounter_combat_order`, `apply_encounter_hp_delta!`,
`tick_encounter_conditions!`, `encounter_conditions_map`). Routes with a
*different* authorization shape (active-player-only, character-owner-only)
do that check inline rather than forcing it through a shared helper — see
each route in `routes/play/*.rb` for its exact rule and error message.

## Conventions for extending and testing

- **Adding an endpoint:** add the route block to the matching domain file
  under `routes/` (or the matching sub-domain file under `routes/play/` for
  the play surface). If it needs a new shared calculation or table, add a
  named helper to the matching `lib/` file (or a new one) rather than
  inlining logic in the route block — route blocks should stay limited to
  parsing input, calling helpers, and shaping the response. If a lookup
  pattern (e.g. "fetch X by id, 404 if missing") starts repeating across
  three or more routes, promote it to a `find_*!`/`require_*!` helper in
  the relevant `lib/` file rather than copy-pasting it again.
- **Validation style:** every route validates its own input at the top with
  `halt 400, { error: '...' }.to_json unless <check>` — one halt per field,
  in the order fields appear in the request body. Keep new routes
  consistent with this style rather than introducing a validation
  framework.
- **Error shape:** all errors are `{ "error": "<message>" }` with an
  appropriate status (400 invalid input, 401 missing/malformed
  credentials, 403 forbidden/not-a-member, 404 unknown resource, 409
  conflict/duplicate/wrong-turn). Preserve these codes and messages
  exactly — the evaluator suite asserts on them.
- **Determinism:** encounter math (`lib/dnd_rules.rb`), initiative ordering
  (`lib/combat_session.rb::order_combatants` and
  `lib/play_campaigns.rb::encounter_combat_order`), campaign analytics
  (`lib/analytics.rb`), and the play-turn deadline math
  (`routes/play/turns.rb::TURN_TIMEOUT_LOGICAL_TICKS`) must stay pure and
  deterministic — no randomness, no wall-clock reads.
  `POST /v1/dm/loot-parcel` accepts a `seed` field but the current loot
  table is fixed regardless of its value; if loot generation ever becomes
  seed-driven, keep it a pure function of the seed.
- **Testing:** there is no in-repo test suite; correctness is checked by an
  external evaluator that drives the HTTP API (see the `dndeval-*-report.json`
  files at the project root for the last run's suite-by-suite results). To
  test manually, start the server (`./run.sh`) and `curl` the endpoints
  above, or call `POST /v1/storage/reset` between manual test runs to get a
  clean database.
- **Schema changes:** bump `SCHEMA_VERSION` in `lib/database.rb` and extend
  `init_schema!`/`reset_schema!` together. Because the database file is
  always recreated fresh at boot, a new column just needs to be added to
  the relevant `CREATE TABLE` statement — there is no `ALTER TABLE`
  migration path to keep in sync.
