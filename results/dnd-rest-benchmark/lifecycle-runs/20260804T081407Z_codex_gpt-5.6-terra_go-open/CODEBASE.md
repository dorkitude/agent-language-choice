# Codebase guide

## Run and verify

Run the server from the project root:

```sh
PORT=8080 ./run.sh
```

`run.sh` runs `go run .` in the foreground. `main.go` reads `PORT`, defaults it
to `8080` when empty, and binds only to `127.0.0.1:$PORT`. Check a running
instance with:

```sh
curl http://127.0.0.1:8080/health
```

Run the in-process test suite without starting the server:

```sh
GOCACHE="$PWD/.gocache" go test ./...
```

## Layout and request flow

- `main.go` is the application entry point and contains SQLite setup and
  migrations, persistence helpers, domain handlers, validation, and JSON
  response helpers.
- `routes.go` contains the complete method-qualified route table. `newRouter`
  is the boundary between transport routing and domain handlers.
- `main_test.go` exercises persistence and representative API behavior through
  handlers.
- `run.sh` provides the foreground server command and keeps its Go build cache
  inside the workspace.
- `go.mod` pins Go 1.26 and the pure-Go SQLite driver; `go.sum` records its
  transitive dependency checksums.

Startup initializes `game.db`, restores durable users and combat sessions to
their in-memory maps, builds the router, and serves it. Each handler decodes a
single strict JSON document (`decodeJSON` rejects unknown fields and trailing
values), validates it, performs its domain operation, and writes JSON using
`writeJSON`.

## State and persistence

SQLite, via the pure-Go `modernc.org/sqlite` driver, is the source of truth for
users, combat sessions, compendium records, and both campaign models. Schema
setup is idempotent, performs additive compatibility migrations, and records
the current schema version. `storage` protects database-handle replacement;
`users` and `sessions` protect the restored authentication and combat working
maps. Combat-session changes are persisted as a transaction that rewrites the
session's related rows. The storage reset endpoint clears durable tables in
foreign-key-safe order and resets both caches.

The application stores `game.db` in the working directory. This is runtime
data, not a source artifact to edit by hand.

## API groupings

- **Service/storage:** health and storage status/reset.
- **Rules utilities:** dice, ability checks, encounter XP, initiative,
  character calculations, and selected PHB rules.
- **Combat and authentication:** initiative-backed combat sessions and local
  user registration/login.
- **Campaign play:** creation, membership, start state, narrations/actions/
  resolutions, turn context, GM status, and the role-filtered campaign
  document.
- **Compendium:** durable monster and item records.
- **Campaign management:** characters, inventory/equipment, crafting, events,
  factions/NPCs, quests, scheduled sessions, state/audit/export, and analytics.
- **DM tools:** campaign-aware encounter building, deterministic tier-one loot,
  and latest-event session recaps.

The exact paths, HTTP methods, JSON field order/content, status codes,
validation behavior, and persistence semantics are compatibility contracts.
`routes.go` is the quickest inventory of those paths.

## Safe extension and testing conventions

Keep route registration method-qualified and add any route to `newRouter`.
Use the existing JSON helpers and validation style so malformed input continues
to receive the established error responses. Preserve deterministic ordering:
database reads specify ordering where output depends on it, combat ordering
uses score, dexterity, then name, and turn membership uses its recorded join
sequence. Add schema changes through idempotent migrations and keep storage
reset order compatible with SQLite foreign keys.

For any behavior change, add focused handler tests with `httptest` and use a
temporary SQLite database as `main_test.go` does. Run `gofmt` on Go files and
`GOCACHE="$PWD/.gocache" go test ./...` before handoff. Avoid starting the
server as part of unit verification.
