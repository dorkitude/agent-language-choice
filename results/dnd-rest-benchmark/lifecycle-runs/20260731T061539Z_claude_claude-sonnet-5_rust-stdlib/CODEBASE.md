# dndrest — codebase guide

A D&D 5e utility REST API implemented in Rust using **only the standard
library**: no HTTP framework, no JSON crate (e.g. serde), no SQLite driver.
Everything — TCP handling, HTTP parsing, JSON parsing/formatting, and the
on-disk SQLite file — is hand-rolled.

## Starting and verifying the server

```bash
./run.sh                 # compiles src/main.rs with rustc and runs it in the foreground
PORT=9000 ./run.sh        # listen on a different port (default 8080)
```

`run.sh` is intentionally a single `rustc --edition=2024 src/main.rs -o dndrest && ./dndrest`
invocation — no `Cargo.toml` dependencies are declared or needed. `rustc`
resolves the `mod` declarations in `src/main.rs` to the sibling files under
`src/` automatically, so this stays a single build command even though the
implementation is split across modules.

Verify it's up:

```bash
curl -s http://127.0.0.1:8080/health
# {"ok":true}
```

Exercise a representative endpoint from each domain:

```bash
curl -s -X POST http://127.0.0.1:8080/v1/dice/stats -d '{"expression":"2d6+3"}'
curl -s -X POST http://127.0.0.1:8080/v1/auth/register -d '{"username":"kyle","password":"password1","role":"dm"}'
curl -s -X POST http://127.0.0.1:8080/v1/campaigns -d '{"id":"c1","name":"Test","dm":"kyle"}'
curl -s http://127.0.0.1:8080/v1/storage/status
```

Live play (a campaign that has been started via `/v1/play/campaigns`) sits
behind bearer auth — pass the token returned by `/v1/auth/login`
(`session-<username>`) as `Authorization: Bearer session-<username>`:

```bash
curl -s -X POST http://127.0.0.1:8080/v1/auth/register -d '{"username":"dm1","password":"password1","role":"dm"}'
curl -s -X POST http://127.0.0.1:8080/v1/play/campaigns \
  -H "Authorization: Bearer session-dm1" -d '{"id":"c1","name":"Test","max_players":2}'
```

There is no automated test suite in this repository; correctness is
verified by the external `dndeval` evaluator harness (see the
`dndeval-*-report.json` files and `evaluations/` at the project root, which
are evaluator output, not part of the implementation).

## Entry point and module map

`src/main.rs` only wires things together: it calls `storage::init_storage()`,
binds `TcpListener` to `127.0.0.1:$PORT` (default `8080`), and loops over
incoming connections, handing each one to `http::handle`. One connection is
handled synchronously per accepted socket (no threads, no async) — this is a
benchmark-sized service, and simplicity was prioritized over concurrency.

| Module | Responsibility |
|---|---|
| `json.rs` | The `Json` value enum, a hand-written recursive-descent parser (`parse_json`), and formatting helpers (`fmt_num`, `escape_json_string`, `as_int`, `object_get`). No module below parses or serializes JSON any other way. |
| `http.rs` | Reads one request off a `TcpStream` (headers, then exactly `Content-Length` body bytes), the `route()` dispatch table, and the shared `respond`/`bad_request` response writers. |
| `dice.rs` | `/v1/dice/stats`, `/v1/checks/ability`, `/v1/initiative/order` — dice expression parsing and roll math. Stateless. |
| `encounters.rs` | Challenge-rating → XP table, monster-count multiplier, per-level XP thresholds, and difficulty classification. Used directly by `/v1/encounters/adjusted-xp` and reused by `dm_tools`' encounter builder so the two endpoints can't drift. |
| `characters.rs` | Ability modifiers, proficiency bonus, derived stats (HP/AC), spell slots, long rest, and equipment load. Stateless. |
| `combat.rs` | In-memory combat sessions: initiative order, timed conditions, turn advancement. Owns the `sessions()` store. |
| `auth.rs` | User registration/login, including the pure-stdlib SHA-256 implementation and per-user salting, plus `authenticate()` (parses an `Authorization: Bearer session-<username>` header used by both `play` and any other bearer-protected handler). Owns the `users()` store. |
| `compendium.rs` | Monster and item catalogs (create + get-by-slug). Owns the `monsters()`/`items()` stores; `Monster::cr` is exposed to `dm_tools` for XP lookups. |
| `campaigns.rs` | Campaigns, their character roster, and log-event counts. Owns the `campaigns()` store; exposes `campaign_exists`/`campaign_summary`/`character_exists` so every campaign-scoped module below can validate a `campaign_id` without reaching into `campaigns`' internals. |
| `quests.rs` | Campaign quest tracking: create a quest with a milestone checklist, mark milestones complete (auto-completing the quest once all are done), and per-campaign quest-count summaries. Owns its own `quests()` store (keyed by campaign id), validated against `campaigns` the same way the other campaign-scoped modules below are. |
| `npcs.rs` | Campaign factions and NPCs, and a relationship summary (friendly/hostile counts). Owns the `relationships()` store (keyed by campaign id); exposes `npc_count`/`friendly_npc_count` for `analytics`. |
| `inventory.rs` | Per-campaign inventory (item + quantity + owner) and per-character equipment assignment, plus an inventory summary. Owns the `inventory()`/`equipment()`/`healing_potion_bonus()` stores; exposes `inventory_item_count`/`add_healing_potion_bonus` for `crafting` and `analytics`. |
| `crafting.rs` | Downtime crafting projects: start one against an inventory item, advance progress over time, auto-complete and grant the crafted item via `inventory::add_healing_potion_bonus` on completion. Owns the `projects()` store. |
| `sessions.rs` | Campaign session scheduling, attendance recording, and "next session" lookup. Owns the `sessions()` store; exposes `session_count` for `analytics`. |
| `analytics.rs` | Read-only campaign rollups (`/analytics/summary`, `/analytics/risk-report`) computed by calling into `quests`, `npcs`, `inventory`, and `sessions`' count helpers. Holds no state of its own. |
| `audit.rs` | Read-only campaign audit trail and export, built from `campaigns`' event log. Holds no state of its own. |
| `dm_tools.rs` | Encounter builder (reads `campaigns` + `compendium` + `encounters`), loot parcel, and session recap. These validate `campaign_id` against the `campaigns` store but otherwise don't hold their own state. |
| `play.rs` | Live, turn-based campaign play under `/v1/play/...`, protected by `Authorization: Bearer session-<username>` (see `auth::authenticate`): lobby creation/join/start, DM narration, player actions, DM resolutions (which advance the turn), a turn-nudge notice, the shared story/DM-notes document, scenes/locations/travel, encounters/combat, HP/death saves, character ownership, and leveling/skill checks. Owns its own `play_campaigns()` store, entirely separate from `campaigns::campaigns()` — a play campaign and a "plain" campaign with the same id are unrelated records. At ~2,700 lines it is by far the largest module (everything else is under 750); it's kept as one file because every handler shares the same `PlayCampaign` struct and locking discipline, but it's organized top-to-bottom with `// ===== Section =====` banner comments (data model → store → shared macros → lobby → narration/turns → document → scenes → locations/travel → encounters → rewards → combat actions → HP/damage → ownership → creation/leveling → skill checks) — use those banners, not line numbers, to navigate it. |
| `storage.rs` | `/v1/storage/status` and `/v1/storage/reset`, plus the hand-rolled SQLite file writer described below. |

## State, persistence, and request routing

**Live state** lives entirely in process memory, one `Mutex<HashMap<...>>`
behind a `OnceLock` per domain (`combat::sessions()`, `auth::users()`,
`compendium::monsters()`/`items()`, `campaigns::campaigns()`,
`quests::quests()`, `npcs::relationships()`, `inventory::inventory()`/
`equipment()`, `crafting::projects()`, `sessions::sessions()`,
`play::play_campaigns()`). There is no cross-module shared store — each
module owns and locks only its own map, so a request touching multiple
domains (e.g. the encounter builder, or `analytics`' rollups) takes each
module's lock independently and briefly, never nested. State does not
survive a process restart. `storage::reset_storage()` (behind
`/v1/storage/reset`) calls every domain module's `clear()` in turn so a
reset is complete across all of them.

**`game.db`** is a real, spec-compliant SQLite file (valid 100-byte header,
`sqlite_master` schema page, one empty leaf page per table) written by
`storage::write_sqlite_schema()`. It exists to represent the durable schema
the in-memory state is modeled after; it is regenerated (and left empty) on
every `init_storage()` and `/v1/storage/reset` call. No request handler
reads from or writes to this file — it is schema-only, not a live database.
If a future change needs the file to reflect live data, `write_sqlite_schema`
is the place to extend, and `storage.rs`'s `sqlite_record`/`sqlite_varint`/
`write_leaf_table_page` helpers already handle the SQLite on-disk format.

**Routing** is a single `match` in `http::route()` for fixed paths, with a
fallback block that strips known prefixes/suffixes for the routes with a
path segment (`/v1/combat/sessions/{id}/...`, `/v1/campaigns/{id}/...`,
`/v1/play/campaigns/{id}/...`, `/v1/compendium/{monsters,items}/{slug}`).
There is no router abstraction or path-parameter framework — at this
endpoint count a flat match is easier to audit than a table-driven router
would be.

## API/domain groupings

- **Dice & checks** (`dice.rs`): `/v1/dice/stats`, `/v1/checks/ability`, `/v1/initiative/order`
- **Encounters** (`encounters.rs`): `/v1/encounters/adjusted-xp`
- **Characters** (`characters.rs`): `/v1/characters/ability-modifier`, `/v1/characters/proficiency`, `/v1/characters/derived-stats`, `/v1/phb/spell-slots`, `/v1/phb/rests/long`, `/v1/phb/equipment-load`
- **Combat** (`combat.rs`): `/v1/combat/sessions`, `/v1/combat/sessions/{id}/conditions`, `/v1/combat/sessions/{id}/advance`
- **Auth** (`auth.rs`): `/v1/auth/register`, `/v1/auth/login`
- **Compendium** (`compendium.rs`): `/v1/compendium/monsters[/{slug}]`, `/v1/compendium/items[/{slug}]`
- **Campaigns** (`campaigns.rs`): `/v1/campaigns`, `/v1/campaigns/{id}/characters`, `/v1/campaigns/{id}/events`, `/v1/campaigns/{id}/state`
- **Quests** (`quests.rs`): `/v1/campaigns/{id}/quests`, `/v1/campaigns/{id}/quests/{quest_id}/progress`, `/v1/campaigns/{id}/quests/summary`
- **NPCs & factions** (`npcs.rs`): `/v1/campaigns/{id}/factions`, `/v1/campaigns/{id}/npcs`, `/v1/campaigns/{id}/relationships`
- **Inventory & equipment** (`inventory.rs`): `/v1/campaigns/{id}/inventory`, `/v1/campaigns/{id}/characters/{character_id}/equipment`, `/v1/campaigns/{id}/inventory/summary`
- **Downtime crafting** (`crafting.rs`): `/v1/campaigns/{id}/downtime/crafting`, `/v1/campaigns/{id}/downtime/crafting/{project_id}/advance`
- **Session scheduling** (`sessions.rs`): `/v1/campaigns/{id}/sessions`, `/v1/campaigns/{id}/sessions/{session_id}/attendance`, `/v1/campaigns/{id}/sessions/next`
- **Analytics** (`analytics.rs`): `/v1/campaigns/{id}/analytics/summary`, `/v1/campaigns/{id}/analytics/risk-report`
- **Audit** (`audit.rs`): `/v1/campaigns/{id}/audit`, `/v1/campaigns/{id}/export`
- **DM tools** (`dm_tools.rs`): `/v1/dm/encounter-builder`, `/v1/dm/loot-parcel`, `/v1/dm/session-recap`
- **Live play** (`play.rs`), all bearer-authenticated: `/v1/play/campaigns`, `/v1/play/campaigns/{id}/members`, `/v1/play/campaigns/{id}/start`, `/v1/play/campaigns/{id}/narrations`, `/v1/play/campaigns/{id}/actions`, `/v1/play/campaigns/{id}/resolutions`, `/v1/play/campaigns/{id}/turn`, `/v1/play/campaigns/{id}/turn/nudge`, `/v1/play/campaigns/{id}/my-turn`, `/v1/play/campaigns/{id}/gm/status`, `/v1/play/campaigns/{id}/document`
- **Storage** (`storage.rs`): `/v1/storage/status`, `/v1/storage/reset`
- **Health**: `/health` (handled inline in `http::route`)

## Conventions for safely extending and testing

- **Adding an endpoint**: pick (or add) the domain module that owns the
  relevant state, write a `handle_*(stream, ...)` function there following
  the existing pattern (parse JSON with `json::parse_json`, validate every
  field with an explicit `match`/`bad_request` before touching any store,
  then `respond`), and add one arm to `http::route()`. Keep response bodies
  built with plain `format!` + `escape_json_string`/`fmt_num`, matching every
  other handler — there is no serializer to route around.
- **Validation-then-mutation ordering**: every existing handler validates
  and parses *all* fields before acquiring any store lock and before
  mutating anything, so a bad request never leaves partial state behind.
  Preserve this ordering in new handlers.
- **Locking**: never hold two domain locks at once. `dm_tools` and
  `analytics` are the modules that touch more than one store per request;
  note how each lock is acquired inside its own `{ }` block (or a short-lived
  helper call) and dropped before the next is taken.
- **JSON**: don't hand-format JSON outside `json::escape_json_string`/`fmt_num`
  — string fields must be escaped and numbers must use `fmt_num` so whole
  values don't grow a spurious `.0`.
- **Repeated arithmetic/formatting**: factor it out the same way `play.rs`
  does for HP math — `clamp_hp` centralizes the "add/subtract then clamp to
  `[0, max]`" rule used by every damage/heal path (monster, bound member,
  and character-by-id) so the three call sites can't drift out of sync.
- **Repeated per-handler boilerplate**: `play.rs` factors its "authenticate
  or 401" / "look up the campaign or 404" / "parse the JSON body or 400" /
  "require a non-empty string field or 400" steps into `macro_rules!` helpers
  (`authenticated!`, `campaign_or_404!`, `parsed_json!`, `require_str!`) at
  the top of the file, since every handler starts with some subset of them
  and a plain function can't early-return out of its caller. If a module
  outside `play.rs` accumulates the same repeated shape, prefer lifting the
  same kind of macro rather than re-deriving the pattern by hand.
- **Testing**: there's no in-repo test harness; validate changes by running
  `./run.sh` and exercising endpoints with `curl` (see above), and by
  re-running the external `dndeval` evaluator, which is the source of truth
  for observable behavior this codebase must preserve.
- **No new dependencies**: this target is std-only by contract (no Cargo
  dependencies, no HTTP/JSON/SQLite crates). Any new functionality must be
  implemented with `std::net`/`std::io`/`std::sync`/etc., following the
  existing hand-rolled JSON and SQLite code as the pattern to match.
