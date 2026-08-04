# D&D 5e REST API — Codebase Guide

A D&D 5e REST API backend implemented as Next.js 16 App Router route handlers
(no pages/UI beyond a placeholder). TypeScript, strict mode, Node's built-in
`node:sqlite` for storage.

## Running the server

```bash
PORT=3000 ./run.sh
```

`run.sh` clears any stale `.next/dev/lock` left by a force-killed previous
run, deletes any existing `game.db*` so every run starts from a clean
database, then starts `next dev` bound to `127.0.0.1` on `$PORT` (required
env var — there is no default). The server only listens on loopback.

Verify it's up:

```bash
curl http://127.0.0.1:$PORT/health
# => {"ok":true}
```

Type-check without starting anything:

```bash
npx tsc --noEmit
```

## Entry point and module layout

There is no custom server entry point — Next.js's App Router derives routes
from the `app/` directory. Every file matching `app/**/route.ts` exports
HTTP-method-named async functions (`GET`, `POST`, ...) that receive a
`Request` and, for dynamic segments, `{ params }` (a `Promise` — always
`await` it, per the Next 15+/16 async-params convention).

```
app/health/route.ts              GET  /health
app/page.tsx                     placeholder root page (not part of the API)
app/v1/db.ts                     SQLite connection, schema, reset
app/v1/http.ts                   shared parseJsonBody()/requireNonEmptyString() helpers
app/v1/shared/initiative.ts      shared rankInitiative() scoring/sort helper (combat only)

app/v1/auth/{store,session,login,register}.ts
                                  registration, login, and Bearer-session auth used by
                                  every session-gated route (campaigns/, play/)

app/v1/campaigns/{store,http,route}.ts
                                  older "campaign management" domain: characters, events,
                                  quests, factions, npcs, inventory, equipment, crafting,
                                  sessions, plus read-only audit/export/analytics views
app/v1/campaigns/[id]/{characters,events,state}/route.ts
app/v1/campaigns/[id]/{quests,factions,npcs,inventory,relationships}/route.ts
app/v1/campaigns/[id]/quests/[quest_id]/progress/route.ts
app/v1/campaigns/[id]/quests/summary/route.ts
app/v1/campaigns/[id]/characters/[character_id]/equipment/route.ts
app/v1/campaigns/[id]/inventory/summary/route.ts
app/v1/campaigns/[id]/downtime/crafting/route.ts
app/v1/campaigns/[id]/downtime/crafting/[project_id]/advance/route.ts
app/v1/campaigns/[id]/sessions/route.ts
app/v1/campaigns/[id]/sessions/next/route.ts
app/v1/campaigns/[id]/sessions/[session_id]/attendance/route.ts
app/v1/campaigns/[id]/audit/route.ts
app/v1/campaigns/[id]/export/route.ts
app/v1/campaigns/[id]/analytics/{summary,risk-report}/route.ts

app/v1/play/{store,http}.ts
                                  live turn-based play session domain, layered on top of
                                  auth (session-gated) but independent of the campaigns/
                                  domain above — a "play campaign" is a separate entity
                                  from a "campaign", identified by its own id space
app/v1/play/campaigns/route.ts                          create a play campaign (dm only)
app/v1/play/campaigns/[id]/members/route.ts              players join with a character
app/v1/play/campaigns/[id]/start/route.ts                dm starts the session
app/v1/play/campaigns/[id]/document/route.ts             shared story/dm_notes doc (GET/PUT)
app/v1/play/campaigns/[id]/narrations/route.ts           dm posts narration events
app/v1/play/campaigns/[id]/gm/status/route.ts            dm-only full status view
app/v1/play/campaigns/[id]/my-turn/route.ts              player's own turn-context view
app/v1/play/campaigns/[id]/turn/route.ts                 turn queue/phase for any member
app/v1/play/campaigns/[id]/turn/nudge/route.ts            dm nudges an overdue player
app/v1/play/campaigns/[id]/actions/route.ts               active player submits an action
app/v1/play/campaigns/[id]/resolutions/route.ts           dm resolves the pending action

app/v1/characters/{rules,ability-modifier,derived-stats,proficiency}.ts
app/v1/checks/ability/route.ts
app/v1/combat/{store,sessions/route}.ts, sessions/[id]/{advance,conditions}/route.ts
app/v1/compendium/{store,items,monsters}/... + [slug]/route.ts
app/v1/dice/stats/route.ts
app/v1/dm/{encounter-builder,loot-parcel,session-recap}/route.ts
app/v1/encounters/{xp,adjusted-xp/route}.ts
app/v1/initiative/order/route.ts
app/v1/phb/{equipment-load,rests/long,spell-slots}/route.ts
app/v1/storage/{reset,status}/route.ts
```

Each domain that persists data has a `store.ts` next to its route handlers.
`store.ts` files are the only code allowed to talk to `db.ts` / run SQL for
that domain — route handlers call store functions, they don't issue queries
themselves. Pure rule/logic modules (`characters/rules.ts`, `encounters/xp.ts`)
have no persistence and are safe to unit test in isolation.

### Shared helpers

- **`app/v1/http.ts`**
  - `parseJsonBody(request)` — the "parse JSON, or return
    `400 { error: "invalid JSON body" }`" contract every mutating endpoint
    follows:
    ```ts
    const parsed = await parseJsonBody(request);
    if (!parsed.ok) return parsed.response;
    const body = parsed.body;
    ```
  - `requireNonEmptyString(value, fieldName)` — the
    `400 { error: "<fieldName> must be a non-empty string" }` shape repeated
    by hand across nearly every route with string fields:
    ```ts
    const name = requireNonEmptyString(body?.name, "name");
    if (name instanceof Response) return name;
    ```
- **`app/v1/auth/session.ts`** — `requireSession(request)` validates the
  `Authorization: Bearer session-<username>` header (a synthetic token, not a
  real session store) and looks up the user. Every route in `campaigns/` and
  `play/` that requires a caller identity starts with this check.
- **`app/v1/play/http.ts`** — helpers specific to the play domain, layered on
  `requireSession`:
  - `requirePlayCampaign(campaignId)` — the "does this play campaign exist"
    404 check every play route needs first.
  - `requireCampaignOwner(campaign, username, errorMessage)` — the "must be
    the owning dm" 403 gate shared by `document` (PUT), `narrations`,
    `start`, and `turn/nudge`. Callers still supply their own error message
    text; only the comparison and response shape are shared.
  - `listRecentPlayEventSummaries(campaignId, limit?)` — the trimmed
    `{sequence, kind, actor, text}` event view shared by `gm/status` and
    `my-turn` (both cap at `RECENT_EVENTS_LIMIT`, currently 10).
- **`app/v1/shared/initiative.ts`** — `rankInitiative(combatants)` computes
  `score = roll + dex` and sorts descending by score, then dex, then name.
  Used by `POST /v1/combat/sessions` and `POST /v1/initiative/order` only —
  unrelated to play-domain turn order (see below).
- **`app/v1/encounters/xp.ts`** — `sumPartyThresholds(party)` and
  `difficultyFor(adjustedXp, thresholds)`, shared by `dm/encounter-builder`
  and `encounters/adjusted-xp`. `sumPartyThresholds` returns `undefined` if
  any party member's level has no entry in `LEVEL_THRESHOLDS` (currently only
  level 3 is defined — extend that table, not the calling routes, to support
  more levels).

**Important distinction:** play-domain turn order (whose turn it is to act in
`app/v1/play/**`) is unrelated to combat initiative (`shared/initiative.ts`).
Play turns cycle player → dm → next player in **party join order**; combat
initiative is `roll + dex` ranking. Don't reach for `rankInitiative` when
touching `play/` turn logic, and don't reuse `play/`'s turn-queue logic for
combat.

## Persistence design

`app/v1/db.ts` owns the single `DatabaseSync` connection (from `node:sqlite`,
lazily opened on first `getDb()` call) against `game.db` in the project
root. Schema, grouped by domain:

- `users(username PK, password_hash, role)` — the only table with real
  columns.
- `combat_sessions(id PK, data)`, `monsters(slug PK, data)`,
  `items(slug PK, data)` — standalone domains, no campaign scoping.
- `campaigns(id PK, data)` plus composite/rowid-keyed child tables scoped by
  `campaign_id`: `campaign_characters`, `campaign_events`,
  `campaign_quests`, `campaign_factions`, `campaign_npcs`,
  `campaign_inventory`, `campaign_equipment`, `campaign_crafting_projects`,
  `campaign_sessions`. This is the "campaign management" domain
  (`app/v1/campaigns/**`).
- `play_campaigns(id PK, data)`, `play_members(campaign_id, character_id,
  data)`, `play_events(campaign_id, sequence, data)`,
  `play_scenes(campaign_id, id, data)`, `play_locations(campaign_id, id,
  data)`, `play_location_connections(campaign_id, from_id, to_id, data)`,
  `play_encounters(campaign_id, id, data)` — the separate "play" domain
  (`app/v1/play/**`). A play campaign is its own entity with its own id
  space; it does not reference or share rows with `campaigns`.

For every blob table, `data` is `JSON.stringify()` of the domain object;
store functions `JSON.parse()` it back on read. IDs/slugs for
client-identified entities are always supplied by the client in the request
body — this API never generates its own IDs for those — so store `create*`
functions just `INSERT` and rely on the primary key to reject duplicates
(routes pre-check with a `has*` lookup to return a clean 409/400 instead of a
raw SQLite constraint error). The `campaign_inventory` and
`campaign_equipment` tables are the exception: they use an autoincrement
`entry_id` because inventory/equipment entries have no natural client-supplied
id. `play_events.sequence` is server-computed per campaign via
`getNextPlayEventSequence` (max + 1), for the same reason.

`SCHEMA_VERSION` (currently `1`) is a plain constant surfaced by
`GET /v1/storage/status` and `POST /v1/storage/reset`. It does not drive any
migration logic — bump it only as a signal to API consumers that the shape
changed; `resetStorage()` always drops and recreates every table from
scratch rather than migrating in place.

- `GET /v1/storage/status` → `{ driver: "sqlite", schema_version, initialized }`
  (`initialized` reflects whether `createSchema` has run in this process).
- `POST /v1/storage/reset` → drops and recreates every table *except*
  `users`, returns `{ ok: true, schema_version }`. Used by the evaluator
  between test runs to get a clean slate without restarting the server;
  `users` survives reset so a session token obtained before a reset call
  stays valid afterward.

## Request routing

Standard Next.js App Router conventions:

- A folder under `app/` becomes a URL segment; `route.ts` inside it defines
  the handlers for that exact path.
- `[id]` / `[slug]` / `[quest_id]` / `[project_id]` / `[session_id]` folders
  are dynamic segments; handlers receive
  `{ params }: { params: Promise<{ id: string }> }` (always `await params`).
- There is no central router file or middleware — each `route.ts` is fully
  self-contained for request validation, auth, and response shaping.

## API domain groupings

| Domain | Base path | Notes |
|---|---|---|
| Health | `GET /health` | liveness only |
| Auth | `POST /v1/auth/register`, `POST /v1/auth/login` | scrypt password hashing (`auth/store.ts`); login returns a synthetic `session-<username>` token consumed by `requireSession` |
| Campaigns (management) | `POST /v1/campaigns`, `.../characters`, `.../events`, `GET .../state` | `state` aggregates campaign + character list + event count |
| Quests | `.../quests`, `.../quests/summary`, `.../quests/:quest_id/progress` | quest lifecycle + progress updates, campaign-scoped |
| Factions & NPCs | `.../factions`, `.../npcs`, `.../relationships` | world-building entities, campaign-scoped |
| Inventory & equipment | `.../inventory`, `.../inventory/summary`, `.../characters/:character_id/equipment` | party inventory ledger + per-character equipment assignment |
| Downtime | `.../downtime/crafting`, `.../downtime/crafting/:project_id/advance` | crafting project lifecycle |
| Sessions (scheduling) | `.../sessions`, `.../sessions/next`, `.../sessions/:session_id/attendance` | real-world session scheduling + attendance, distinct from `play/` live sessions |
| Campaign reporting | `GET .../audit`, `GET .../export`, `GET/POST .../analytics/{summary,risk-report}` | read-only aggregates over the campaign-management tables above |
| Play (live sessions) | `POST /v1/play/campaigns`, `.../members`, `.../start`, `.../document`, `.../narrations`, `.../gm/status`, `.../my-turn`, `.../turn`, `.../turn/nudge`, `.../actions`, `.../resolutions` | session-gated, turn-based play loop: dm creates → players join → dm starts → action/resolution cycle. See `app/v1/play/http.ts` for the shared auth/ownership helpers |
| Characters | `POST /v1/characters/{ability-modifier,derived-stats,proficiency}` | pure rule calculations from `characters/rules.ts`, no persistence |
| Checks | `POST /v1/checks/ability` | roll+modifier vs DC, no persistence |
| Combat | `POST /v1/combat/sessions`, `.../:id/advance`, `.../:id/conditions` | session state (round, turn index, ordered combatants + conditions) persisted as JSON in `combat_sessions`; unrelated to `play/` turn order |
| Compendium | `POST/GET /v1/compendium/items[/:slug]`, `.../monsters[/:slug]` | static reference data, client-supplied slugs |
| Dice | `POST /v1/dice/stats` | parses `NdM[+/-K]` expressions, returns min/max/average |
| DM tools | `POST /v1/dm/{encounter-builder,loot-parcel,session-recap}` | encounter-builder pulls monster CR from compendium + XP tables |
| Encounters | `POST /v1/encounters/adjusted-xp` | same XP/difficulty math as encounter-builder, factored through `encounters/xp.ts` |
| Initiative | `POST /v1/initiative/order` | stateless version of the combat sessions' seeding logic |
| PHB rules | `POST /v1/phb/{equipment-load,rests/long,spell-slots}` | `spell-slots` only supports wizard/level 5 by design (see comment in that route) |
| Storage | `GET /v1/storage/status`, `POST /v1/storage/reset` | see Persistence design above |

## Conventions for extending / testing safely

- **Adding a route**: create `app/v1/<domain>/<path>/route.ts` exporting the
  HTTP method function(s) you need. If the domain already has a `store.ts`,
  add persistence functions there rather than querying `db.ts` directly from
  the route. Use `parseJsonBody`/`requireNonEmptyString` from `app/v1/http.ts`
  for the standard 400 contracts; for session-gated routes use
  `requireSession` from `app/v1/auth/session.ts`; for play-domain routes
  reuse `requirePlayCampaign`/`requireCampaignOwner`/
  `listRecentPlayEventSummaries` from `app/v1/play/http.ts` rather than
  re-deriving the same checks by hand.
- **Validation style**: handlers validate fields manually (no schema
  library) and return `Response.json({ error: "<message>" }, { status })`
  on the first failing check, most specific error first. Keep new endpoints
  consistent with this pattern (plain `Response.json`, lowercase field names
  matching the wire format, 400 for validation, 404 for missing resource,
  409 for "already exists"/"not your turn" conflicts — note `combat/sessions`
  currently returns 400, not 409, for a duplicate session id; that's existing
  behavior, not a template to copy without thinking).
- **IDs/slugs**: client-supplied for entities the client names (campaigns,
  characters, quests, etc.), never generated server-side. The two exceptions
  are autoincrement `entry_id` on `campaign_inventory`/`campaign_equipment`
  and the server-computed `play_events.sequence` — both because those rows
  have no natural client-supplied id. Don't add auto-generated IDs to an
  existing client-identified entity type without updating every caller that
  currently supplies its own.
- **Store functions**: keep the `has*` / `get*` / `list*` / `create*` /
  `update*` naming and JSON-blob-per-row pattern for new blob-backed tables
  so `resetStorage()` keeps working uniformly (it just drops/recreates every
  table it knows about in `db.ts` — remember to add new tables to both the
  `CREATE TABLE` block and the `DROP TABLE` block). `users` is the one table
  deliberately left out of the `DROP TABLE` block — don't add it without
  confirming session tokens are meant to stop working across a reset.
- **Testing**: there's no unit test suite checked in; the evaluator is an
  external black-box HTTP contract suite (`dndeval run --suite <name>
  --base-url http://127.0.0.1:$PORT`, cumulative — each stage's suite retests
  everything from prior stages). Before committing a change, at minimum run
  `npx tsc --noEmit`, and if you can run the server locally, call
  `POST /v1/storage/reset` (or restart via `run.sh`, which wipes `game.db`)
  before manual testing to start from a clean DB. Do not change any existing
  endpoint's URL, method, request/response shape, status code, or validation
  rule without confirming it's actually wrong — this API is covered by a
  fixed external contract test suite that will fail on any observable
  behavior change.
- **Shared logic**: if you notice the same validation/auth/calculation logic
  appearing in two or more routes, prefer extracting it next to the data it
  operates on (as done for `rankInitiative` in `shared/initiative.ts`,
  `sumPartyThresholds`/`difficultyFor` in `encounters/xp.ts`, and the
  session/ownership/event-summary helpers in `play/http.ts`) rather than
  copy-pasting a third time.
