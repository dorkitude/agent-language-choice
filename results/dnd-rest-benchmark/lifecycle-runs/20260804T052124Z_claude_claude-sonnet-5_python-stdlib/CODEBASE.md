# CODEBASE.md

A D&D 5e session-management and live-play REST API, implemented with the
Python 3.14 standard library only (`http.server`, `json`, `sqlite3` — no
third-party dependencies).

## Start and verify

```bash
./run.sh                 # foreground, listens on 127.0.0.1:$PORT (default 8080)
PORT=9000 ./run.sh        # pick a different port
```

`run.sh` just runs `python3 server.py`; the port comes from the `PORT`
environment variable and the server always binds to `127.0.0.1`. On startup
`main()` deletes any existing `game.db` and calls `db.init_db()`, so every
process start begins from a clean, empty database.

Verify it's up:

```bash
curl -s http://127.0.0.1:8080/health              # {"ok": true}
curl -s http://127.0.0.1:8080/v1/storage/status    # sqlite driver + schema version
```

There is no test runner bundled in this directory; behavior is verified via
the external `dndeval` evaluator binary, which drives this server over HTTP
against named test suites and writes a JSON report:

```bash
PORT=18080 python3 server.py &
dndeval run --suite 049-skills-and-proficiencies --base-url http://127.0.0.1:18080 --json-out /tmp/report.json
# then stop the background server
```

`049-skills-and-proficiencies` is the latest cumulative suite (136 tests)
covering the bulk of endpoint behavior added across all prior stages — it's
the fastest way to confirm a change hasn't regressed anything. Each stage's
suite is cumulative over the previous one, so running the highest-numbered
suite available in `dndeval list` is always the most thorough regression
check. The `dndeval-*-report.json` files already in this directory are prior
evaluator output, useful as a reference for expected request/response shapes
per domain area, but are not regenerated automatically by editing the code.

## Entry point and modules

- **`server.py`** — process entry point (`main()`) and the entire HTTP
  layer: route table (`do_GET`/`do_PUT`/`do_POST`), request parsing,
  per-endpoint handlers on `Handler`, and response shaping. Handlers
  validate input, delegate to `db.py` / `rules.py`, and call
  `self._send_json(status, payload)`. This file stays free of SQL and rule-
  table literals. A handful of shared helpers on `Handler` remove repeated
  boilerplate across the ~90 endpoint handlers:
  - `_get_campaign_or_404(campaign_id)` / `_get_play_campaign_or_404(campaign_id)`
    — look up a campaign, writing the standard 404 response if missing.
    Used by every campaign-scoped and play-campaign-scoped handler.
  - `_get_actor_or_401()` — wraps `_authenticate()`, writing the standard
    401 response if the bearer token is missing/malformed.
  - `_compute_adjusted_xp` / `_compute_party_thresholds` / `_difficulty_for`
    — shared XP/difficulty math used by both `/v1/encounters/adjusted-xp`
    and `/v1/dm/encounter-builder` (see API groupings below for why their
    monster-XP loops stay separate).
  The idiom at every call site is `x = self._get_..._or_...(); if x is
  None: return` — the helper has already sent the error response.
- **`db.py`** — the only module that touches SQLite. Owns the schema
  (`init_db`), full reset (`reset_db`), and one function per row-level
  read/write operation (e.g. `get_campaign`, `create_monster`,
  `save_combat_session`). Every function opens its connection via the
  `db_conn()` context manager (a thin wrapper around `get_conn()` that
  guarantees `close()` on exit) — no pooling, no long-lived cursors, no
  connection reused across requests. Functions that also need to guard a
  multi-statement invariant (e.g. assigning the next narration `sequence`,
  or incrementing `nudge_count`) wrap `with DB_LOCK, db_conn() as conn:`
  instead. Rows are always returned as plain dicts, never `sqlite3.Row`, so
  callers don't leak the storage engine's types. `_count_by_campaign(table,
  campaign_id)` is a small private helper factoring out the identical
  `SELECT COUNT(*) ... WHERE campaign_id = ?` shape shared by the simplest
  per-campaign counters (events, quests, factions, npcs, sessions,
  equipment assignments); counters with an extra filter (status, owner,
  disposition) keep their own query rather than being forced through it.
- **`rules.py`** — pure, stateless D&D rule data and calculations: XP/CR
  tables, encounter-difficulty thresholds, dice-expression parsing,
  ability-score math, proficiency bonus, the DMG encounter multiplier table,
  and password hashing (PBKDF2-HMAC-SHA256 via `hashlib`/`secrets`/`hmac`).
  Nothing in this file does I/O.
- **`game.db`** — SQLite database file, created next to `server.py` on
  every process start (and deleted/recreated first, so state never survives
  a restart). Not meant to be committed with real data; `/v1/storage/reset`
  drops and recreates all tables for a clean slate (tests rely on this).

## State, persistence, and routing design

**Persistence.** All durable state — users, combat sessions, compendium
monsters/items, campaigns and everything scoped under a campaign (characters,
events, quests, factions, npcs, inventory, equipment assignments, crafting
projects, sessions), the separate live-play campaigns and their members/
narration log, and a single-row `schema_meta` table holding `SCHEMA_VERSION`
— lives in SQLite at `game.db`. There is no in-memory cache or fallback
store; every request reads/writes the database directly. `db.DB_LOCK` (a
`threading.Lock`) guards schema-level operations (`init_db`/`reset_db`) and
the handful of read-modify-write sequences that must not race across
threads (e.g. assigning the next narration sequence number, incrementing
`nudge_count`); ordinary single-statement row CRUD relies on SQLite's own
connection-level locking, which is sufficient because each call opens and
closes its own connection via `db_conn()`.

**Server concurrency.** `ThreadingHTTPServer` handles each connection on its
own thread. `Handler.protocol_version = "HTTP/1.1"` enables keep-alive;
`log_message` is silenced so request logging doesn't interleave on stdout.

**Routing.** `do_GET`/`do_PUT`/`do_POST`/`do_DELETE` are flat dispatch
functions. Fixed paths are matched by equality; paths with an embedded
resource ID (e.g. `/v1/combat/sessions/{id}/advance`,
`/v1/campaigns/{id}/events`, `/v1/play/campaigns/{id}/document`) are matched
against module-level compiled regexes defined at the top of `server.py`
(`COMBAT_ADVANCE_RE`, `CAMPAIGN_EVENTS_RE`, `PLAY_CAMPAIGN_DOCUMENT_RE`,
etc.) and the captured group(s) are passed to the handler. `do_DELETE`
currently only serves the two live-play "remove from encounter" routes
(`DELETE .../encounters/{id}/monsters/{monster_id}` unbinds a monster,
`DELETE .../encounters/{id}/combatants/{member_username}` unbinds a party
member); every other mutation across the whole API is modeled as a `POST`
so it can carry a JSON body and a uniform response shape. There is no
separate router object or URL-pattern library — this flat structure was kept
deliberately, since the route count is small and a framework would add a
dependency this codebase intentionally avoids.

**Request/response shape.** Every response is JSON via `_send_json`, driven
uniformly (`Content-Type`, `Content-Length`, status code). `PUT`/`POST`
bodies are parsed once per request via `_read_json`; malformed JSON yields a
single, uniform `400 {"error": "invalid json"}` before any route-specific
handler runs. Missing/invalid fields are handler-specific 400s (e.g.
`{"error": "invalid score"}`); not-found resources are 404s (uniformly
`{"error": "campaign not found"}` for campaign lookups, via the
`_get_campaign_or_404`/`_get_play_campaign_or_404` helpers); duplicate
unique keys are 409s; unauthenticated/unauthorized requests to the
`/v1/play/...` endpoints are 401 (via `_get_actor_or_401`) or 403.
`rules.is_plain_int` exists because D&D-domain integers (level, HP, AC,
scores) must reject `bool` — `True`/`False` are `int` subclasses in Python
and would otherwise silently pass `isinstance` checks.

## API / domain groupings

- **Storage** — `GET /v1/storage/status`, `POST /v1/storage/reset`
- **Dice & checks** — `POST /v1/dice/stats`, `POST /v1/checks/ability`
- **Encounters** — `POST /v1/encounters/adjusted-xp`,
  `POST /v1/initiative/order`
- **Characters** — `POST /v1/characters/ability-modifier`,
  `POST /v1/characters/proficiency`, `POST /v1/characters/derived-stats`
- **PHB rules** — `POST /v1/phb/spell-slots`, `POST /v1/phb/rests/long`,
  `POST /v1/phb/equipment-load`
- **Combat sessions** — `POST /v1/combat/sessions`,
  `POST /v1/combat/sessions/{id}/conditions`,
  `POST /v1/combat/sessions/{id}/advance`
- **Auth** — `POST /v1/auth/register`, `POST /v1/auth/login` (issues an
  opaque `session-{username}` bearer token; `Handler._authenticate` parses
  it back out of the `Authorization` header for the `/v1/play/...` routes)
- **Compendium** — `POST`/`GET /v1/compendium/monsters[/{slug}]`,
  `POST`/`GET /v1/compendium/items[/{slug}]`
- **Campaigns** — `POST /v1/campaigns`,
  `POST`/`GET /v1/campaigns/{id}/characters`,
  `POST /v1/campaigns/{id}/events`, `GET /v1/campaigns/{id}/state`,
  `GET /v1/campaigns/{id}/audit`, `GET /v1/campaigns/{id}/export`
- **Campaign quests** — `POST /v1/campaigns/{id}/quests`,
  `POST /v1/campaigns/{id}/quests/{quest_id}/progress`,
  `GET /v1/campaigns/{id}/quests/summary`
- **Campaign npcs / factions** — `POST /v1/campaigns/{id}/factions`,
  `POST /v1/campaigns/{id}/npcs`, `GET /v1/campaigns/{id}/relationships`
- **Campaign inventory / equipment** — `POST /v1/campaigns/{id}/inventory`,
  `POST /v1/campaigns/{id}/characters/{char_id}/equipment`,
  `GET /v1/campaigns/{id}/inventory/summary`
- **Downtime crafting** — `POST /v1/campaigns/{id}/downtime/crafting`,
  `POST /v1/campaigns/{id}/downtime/crafting/{project_id}/advance`
- **Campaign sessions (scheduling)** — `POST /v1/campaigns/{id}/sessions`,
  `GET /v1/campaigns/{id}/sessions/next`,
  `POST /v1/campaigns/{id}/sessions/{session_id}/attendance`
- **Campaign analytics** — `GET /v1/campaigns/{id}/analytics/summary`,
  `POST /v1/campaigns/{id}/analytics/risk-report`
- **DM tools** — `POST /v1/dm/encounter-builder`,
  `POST /v1/dm/loot-parcel`, `POST /v1/dm/session-recap`
- **Live play — campaign lifecycle (auth-gated,
  `Authorization: Bearer session-{username}`)** —
  `POST /v1/play/campaigns` (dm creates), `POST
  /v1/play/campaigns/{id}/members` (player joins), `POST
  /v1/play/campaigns/{id}/start`, `POST
  /v1/play/campaigns/{id}/narrations`, `POST
  /v1/play/campaigns/{id}/actions`, `POST
  /v1/play/campaigns/{id}/resolutions`, `GET
  /v1/play/campaigns/{id}/turn`, `POST
  /v1/play/campaigns/{id}/turn/nudge`, `POST
  /v1/play/campaigns/{id}/turn/travel` (exploration-mode travel),
  `POST /v1/play/campaigns/{id}/turn/rest` (short/long rest), `GET
  /v1/play/campaigns/{id}/my-turn`, `GET
  /v1/play/campaigns/{id}/gm/status`, `GET`/`PUT
  /v1/play/campaigns/{id}/document` (shared "story" text plus DM-only
  "dm_notes")
- **Live play — scenes & locations** — `POST
  /v1/play/campaigns/{id}/scenes` (create), `GET
  /v1/play/campaigns/{id}/scenes/current`, `POST
  /v1/play/campaigns/{id}/scenes/{scene_id}/enter`, `POST
  /v1/play/campaigns/{id}/scenes/{scene_id}/close`, `POST
  /v1/play/campaigns/{id}/locations` (create the location graph's nodes),
  `POST /v1/play/campaigns/{id}/locations/{location_id}/connections` (add an
  edge), `GET /v1/play/campaigns/{id}/locations/{location_id}/travel`
  (lists destinations reachable from that location)
- **Live play — encounters & combat** — `POST
  /v1/play/campaigns/{id}/encounters` (create), `POST`/`DELETE
  /v1/play/campaigns/{id}/encounters/{id}/monsters[/{monster_id}]`, `POST`/
  `DELETE /v1/play/campaigns/{id}/encounters/{id}/combatants[/{member}]`
  (bind/unbind a party member as a combatant), `GET
  /v1/play/campaigns/{id}/encounters/{id}/turn`, `POST
  /v1/play/campaigns/{id}/encounters/{id}/turn/advance`, `POST
  /v1/play/campaigns/{id}/encounters/{id}/turn/delay`, `POST
  /v1/play/campaigns/{id}/encounters/{id}/turn/ready`, `POST
  /v1/play/campaigns/{id}/encounters/{id}/actions` (a combatant's declared
  action for the current turn), `POST
  /v1/play/campaigns/{id}/encounters/{id}/damage`, `POST
  /v1/play/campaigns/{id}/encounters/{id}/heal`, `POST
  /v1/play/campaigns/{id}/encounters/{id}/conditions`, `GET
  /v1/play/campaigns/{id}/encounters/{id}/status`, `POST
  /v1/play/campaigns/{id}/encounters/{id}/rewards` (XP/loot award, rejects
  duplicates), `POST /v1/play/campaigns/{id}/encounters/{id}/close`, `POST
  /v1/play/campaigns/{id}/encounters/{id}/end`
- **Live play — characters (ownership, build, and progression)** — `GET
  /v1/play/campaigns/{id}/characters/{char_id}/owner`, `POST
  /v1/play/campaigns/{id}/characters/{char_id}/claim`, `POST
  /v1/play/campaigns/{id}/characters/{char_id}/transfer` (owner-only), `POST
  /v1/play/campaigns/{id}/characters/{char_id}/build` (race/class/ability
  score choices), `POST
  /v1/play/campaigns/{id}/characters/{char_id}/level-up` (owner-only), `POST
  /v1/play/campaigns/{id}/characters/{char_id}/skill-check` (rolls against a
  named skill using the character's built proficiencies), `POST
  /v1/play/campaigns/{id}/characters/{char_id}/damage`, `POST
  /v1/play/campaigns/{id}/characters/{char_id}/death-saves`, `GET
  /v1/play/campaigns/{id}/characters/{char_id}/status`

`/v1/encounters/adjusted-xp` and `/v1/dm/encounter-builder` share XP/
difficulty math via the `Handler._compute_party_thresholds` and
`Handler._difficulty_for` helpers (the latter also used for the shared
`multiplier`/`adjusted_xp` rounding pattern); the two endpoints differ in
where monster CRs come from (raw request payload vs. compendium lookup by
slug), so their monster-XP loops are intentionally kept separate rather than
forced into one shared helper.

## Conventions for extending and testing

- **New endpoint:** add a route match in `do_GET`/`do_PUT`/`do_POST`
  (equality for fixed paths, a compiled regex constant near the top of
  `server.py` for path parameters), then a `_handle_*` method on `Handler`.
  If it's campaign-scoped, start with `if self._get_campaign_or_404(
  campaign_id) is None: return` (or the `campaign = ...; if campaign is
  None: return` form if you need the campaign dict); if it's a
  `/v1/play/...` endpoint, start with `actor = self._get_actor_or_401(); if
  actor is None: return`. Validate every remaining field explicitly and
  return the same `{"error": "..."}` shape used elsewhere; prefer the
  narrowest correct status code (400 invalid input, 404 missing resource,
  409 duplicate key, 403 forbidden for role/ownership failures).
- **New persisted entity:** add its `CREATE TABLE IF NOT EXISTS` to
  `db.init_db`, add its `DROP TABLE IF EXISTS` to `db.reset_db` (schema
  reset must stay exhaustive), and add plain `get_*`/`create_*`/`list_*`
  functions using `with db_conn() as conn:` (add `DB_LOCK` only if the
  function does a read-then-write sequence that must not race). Return
  dicts — never leak `sqlite3.Row` or raw JSON-encoded columns past `db.py`.
  If you're adding another simple `COUNT(*) ... WHERE campaign_id = ?`
  counter, use `_count_by_campaign(table, campaign_id)` instead of writing
  the query by hand.
- **New rule table/calculation:** put constants and pure functions in
  `rules.py`; keep them free of request/response concerns so they stay unit
  -testable in isolation (`python3 -c "import rules; ..."`).
- **Determinism:** handlers must not depend on wall-clock time, randomness,
  or environment beyond `PORT`. `/v1/dm/loot-parcel` accepts and validates a
  `seed` field for forward compatibility, but current loot tiers are fixed
  presets and the seed is intentionally unused today.
- **Testing a change:** start `./run.sh` (or `PORT=<n> python3 server.py &`
  for a background instance to test against), call `POST
  /v1/storage/reset` to get a clean database if you're reusing a running
  process, then drive the affected endpoint(s) with `curl` or a short
  `urllib.request` script and compare against the behavior documented
  above. Before committing a change, run the latest cumulative evaluator
  suite (check `dndeval list` for the current highest-numbered suite):
  `dndeval run --suite 049-skills-and-proficiencies --base-url
  http://127.0.0.1:<port> --json-out <path>` and confirm `passed_count ==
  total_count == 136`; stop the background server afterward.
