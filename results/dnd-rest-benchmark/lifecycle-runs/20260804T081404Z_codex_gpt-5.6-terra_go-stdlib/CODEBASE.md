# D&D REST API

## Start and verify

Use the pinned Go 1.26 toolchain and run the supported launcher from the
repository root:

```sh
PORT=8080 ./run.sh
```

`run.sh` runs `go run .` in the foreground. The server initializes its local
database and listens only on `127.0.0.1:$PORT`; if `PORT` is unset, it uses
`8080`. A running instance can be checked with:

```sh
curl -i http://127.0.0.1:8080/health
go test ./...
```

There are currently no Go test files, so `go test ./...` is also the package
compile check. Do not start a long-running server as part of automated
verification.

## Implementation map

The application is intentionally a single `main` package with no third-party
Go dependencies:

- `main.go` contains the entry point, domain models, routing, HTTP handlers,
  persistence adapter, validation, and JSON response helpers.
- `main` initializes storage before binding the HTTP server.
- `newRouter` builds the standard-library mux; its `apiRoute` inventory is the
  complete public routing map. Method-qualified patterns are the source of
  truth for accepted endpoints and method handling.
- `run.sh` is the foreground launcher.
- `go.mod` declares module `dndrest` and Go 1.26.

Within `main.go`, handlers are arranged by domain: rules and character
calculations; combat; authentication; playable campaigns and turn flow;
storage administration; compendium content; campaign management; and DM
utilities. Shared helpers near the end implement strict request decoding and
JSON responses.

## State, persistence, and routing

`game.db` is created in the current working directory. The storage adapter
uses the system `/usr/bin/sqlite3` executable and stores JSON documents for
the domain records, alongside indexed identifiers and a few relational
constraints. `schemaDefinition` is shared by startup and reset so both paths
create the same tables. The `GET /v1/storage/status` and
`POST /v1/storage/reset` endpoints expose the established storage lifecycle.

Users and combat sessions are loaded into mutex-protected in-memory maps at
startup and persisted after writes. Other resources are read from SQLite per
request. `storageState` serializes database access. When a reset needs all
state locks, it takes them in this order: user state, combat state, then
storage state. Preserve that order in code that holds more than one of them.

The router exposes these main API groupings:

- `/health` and `/v1/storage/*` for liveness and storage administration.
- `/v1/dice`, `/v1/checks`, `/v1/characters`, `/v1/encounters`,
  `/v1/initiative`, and `/v1/phb` for deterministic rules helpers.
- `/v1/combat/sessions` and `/v1/auth` for combat state and account access.
- `/v1/compendium/*` for monsters and items.
- `/v1/campaigns/*` for campaigns, characters, events, inventory, equipment,
  factions, NPCs, quests, downtime, scheduling, audit/export, and analytics.
- `/v1/play/campaigns/*` for owner/player membership, campaign documents,
  narration, turn state, actions, resolutions, and nudges.
- `/v1/dm/*` for encounter, loot, and recap tools.

## Safe extension and testing conventions

The API is a compatibility contract. Preserve each route's method and path,
status code, response field ordering/shape, validation rule and message, and
persistence behavior. Add any future route to `newRouter` using a
method-qualified pattern rather than introducing manual method dispatch.

Decode bodies with `decodeJSON`: its shared 1 MiB limit rejects oversized
bodies, unknown fields, and trailing JSON values. Write JSON with
`respondJSON` or `badRequest` so the existing content type and error shape
remain consistent. Keep route changes in the `apiRoute` inventory so routing
and endpoint documentation remain reviewable in one place.
Keep validation and ordering deterministic. For persistence changes, test
successful and invalid requests plus restart and reset behavior in an isolated
working directory, because `game.db` is intentionally durable across process
starts. Run `gofmt -w main.go` and `go test ./...` before handing off changes.
