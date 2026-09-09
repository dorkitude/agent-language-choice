# Codebase Guide

## Start and verify

Install the versions locked in `package-lock.json`, then supply a port when
starting the app:

```sh
npm install
PORT=3000 ./run.sh
```

`run.sh` uses `exec` to run the Next.js 16 development server in the foreground
at `127.0.0.1:$PORT`. It deliberately does not provide a fallback port, so the
caller always controls the listener. Once it is running, verify it with:

```sh
curl http://127.0.0.1:3000/health
```

The health response is `{"ok":true}`. For a static check that does not start a
server, run `./node_modules/.bin/tsc --noEmit`.

## Entry point and module boundaries

Next.js discovers route handlers from `app/**/route.ts`; `app/health/route.ts`
is the health endpoint and `app/v1/**` is the versioned JSON API. The filesystem
is the routing table—there is no separate application router. Handlers using
SQLite or Node crypto opt into `runtime = "nodejs"`. `app/page.tsx` is an
unrelated default page rather than an API entry point.

Handlers are intentionally thin: they parse a request, enforce the route's
contract, call a domain operation, and shape the exact response. Shared code is
organized as follows:

- `app/lib/http.ts` contains JSON parsing, JSON error responses, and narrow
  primitive validators. Its validators preserve existing distinctions such as
  accepting whitespace-only nonempty strings.
- `app/lib/storage.ts` owns the SQLite connection, idempotent schema setup,
  schema metadata, and the destructive reset operation.
- `app/lib/users.ts` owns password hashing and persisted user lookups.
- `app/lib/campaigns.ts` owns the conventional campaign aggregate: characters,
  event log, quests/milestones, factions/NPCs, inventory/equipment, crafting,
  scheduling, attendance, audit counts, and analytics inputs.
- `app/lib/play-campaigns.ts` owns the authenticated play aggregate: lobby
  membership and ownership, character build/progression/health, exploration
  turns, scenes and locations, documents, event streams, and encounters.
- `app/lib/combat.ts` and `app/lib/compendium.ts` provide persisted combat and
  compendium operations. `app/lib/characters.ts` and
  `app/lib/encounter-math.ts` contain deterministic rule calculations.

## State, persistence, and request flow

`storage.ts` opens `game.db` in the working directory and retains its
`DatabaseSync` instance on `globalThis`, preventing a Next development reload
from opening another connection. Schema initialization is idempotent and records
`SCHEMA_VERSION` in `storage_metadata`. State persists across server restarts;
`POST /v1/storage/reset` intentionally drops and recreates every application
table, including users.

SQLite stores users; conventional campaign resources; compendium records;
standalone combat sessions and conditions; and the play-campaign resources for
members, documents, scenes, locations, character state, events, and encounters.
SQL and persistence transformations stay in the relevant `lib` module, while
routes retain endpoint-specific validation, authorization, status codes, and
response shapes.

Most play-campaign routes identify a user from the login token supplied in the
`Authorization` header and use the persisted role/ownership data to authorize
the operation. This is an API contract detail, not a general middleware layer;
keep authorization checks local unless every affected endpoint is deliberately
migrated together.

## API groupings

- `/health` provides the process health response.
- `/v1/auth` registers users and returns the deterministic login token.
- `/v1/storage` reports SQLite status or resets all application state.
- `/v1/campaigns` manages campaigns, characters, events, quests, relationships,
  inventory/equipment, downtime crafting, sessions/attendance, exports, audit,
  and analytics.
- `/v1/combat` manages persisted combat sessions and conditions;
  `/v1/initiative` calculates a deterministic order without persistence.
- `/v1/compendium` stores and retrieves monsters and items.
- `/v1/characters`, `/v1/checks`, `/v1/dice`, `/v1/encounters`, and `/v1/phb`
  expose deterministic rules calculations.
- `/v1/dm` provides campaign-aware encounter, loot, and recap tools.
- `/v1/play/campaigns` manages the authenticated tabletop flow: campaign setup,
  members and character ownership; builds, skills, levels, health, and death
  saves; exploration turns, rests, travel, scenes, and locations; narrative
  events and documents; plus encounter rosters, conditions, turns, combat
  actions, damage/healing, rewards, closure, and end-of-encounter transitions.

## Safe extension and testing conventions

The API contract is cumulative. Preserve every route's validation boundary,
error text, status code, JSON field spelling/order, and persistence behavior.
Avoid broad route abstractions that can accidentally normalize endpoint-specific
behavior. Put truly shared, behavior-neutral primitives in `lib/http.ts`; put
new persisted operations in the appropriate domain module rather than embedding
SQL in a handler.

Schema changes must be idempotent in `storage.ts` and must be reflected in
`resetStorage`. Preserve `ORDER BY rowid` where it exists: insertion order is a
domain invariant for event streams, member rotation, and queues. Keep rule
calculations deterministic and validate unknown JSON with `jsonBody`, `isRecord`,
and the existing narrow validators before accessing properties. Before handoff,
run the TypeScript check above; reset storage before stateful endpoint tests so
results do not depend on a previous `game.db`.
