# D&D REST service

## Run and verify

The server targets Rust 1.97.0 and uses the Rust standard library only. Its
durable store is accessed through the locally installed `sqlite3` executable.
Start it in the foreground with a port selected through `PORT`:

```sh
PORT=8080 ./run.sh
```

It listens only on `127.0.0.1`. In another terminal, check readiness with:

```sh
curl -i http://127.0.0.1:8080/health
```

The successful response body is `{"ok":true}`. Run the regression suite without
starting the server using `cargo test`. `run.sh` deliberately blocks after it
executes the compiled server, so it is not a build-only check.

## Files and request flow

- `run.sh` compiles `src/main.rs` with Rust 2024 edition and runs the server in
  the foreground.
- `Cargo.toml` declares the dependency-free crate and test target.
- `src/main.rs` contains the complete application, organized into data types,
  the `Storage` persistence adapter, state encoding, HTTP startup/routing,
  domain handlers, JSON parsing, response writing, and focused unit tests.

`main` binds the listener, opens `game.db`, restores the in-memory users and
combat sessions, then processes one TCP connection at a time. `read_request`
is the HTTP framing boundary: it accepts a bounded header/body and returns an
owned `HttpRequest`. `handle` is the routing boundary. It checks parameterized
resource routes before exact method/path routes, while the focused helper
functions below it implement the individual domain operations. `respond` writes
every JSON HTTP response.

The custom `Json` parser and its `*_field` helpers form the validation boundary.
Response JSON is assembled in fixed field order; preserve that ordering because
it is observable and keeps output deterministic without `serde`.

## State and persistence

`Storage` is the only persistence adapter. It creates the schema and invokes
the platform `sqlite3` executable for relational reads and writes, so the Rust
crate itself remains dependency-free. `game.db` contains:

- compendium tables for monsters, tags, and items;
- campaign tables for characters, events, quests/milestones, factions, NPCs,
  inventory/equipment, crafting projects, and scheduled sessions/attendance;
- play-campaign tables for memberships, runtime turns, documents, events, and
  turn nudges;
- `game_state`, a versioned BLOB for registered users and combat sessions; and
- `schema_meta`, currently schema version 1.

The `DNDSTATE1`/`DNDSTATE2` encoder sorts map keys before saving. Preserve its
format and validation: it is read on the next server start. It contains only
registered users and standalone combat sessions; successful auth and combat
mutations save it immediately. Relational-domain methods write directly through
`Storage`. `/v1/storage/reset` recreates the tables and clears the corresponding
in-memory state.

## API/domain groupings

- Core rules: health, storage status/reset, dice, ability checks, encounter XP,
  and initiative.
- Characters and PHB rules: ability modifiers, proficiency, derived stats,
  spell slots, long rests, and equipment load.
- Authentication and combat: registration/login plus combat sessions, turns,
  and conditions.
- Compendium: monster and item creation with slug lookups.
- Campaign management: campaigns, characters, events, quests, factions, NPCs,
  inventory, equipment, crafting, schedules, analytics, audits, exports, and
  relationship/state summaries.
- Play campaigns: DM-owned lobbies, player membership, campaign documents,
  narrated turns, player actions, GM resolutions, nudges, and player/GM turn
  context.
- DM tools: encounter building, deterministic tier-1 loot parcels, and session
  recaps derived from persisted campaign and compendium data.

## Safe extension and testing conventions

Keep the service stdlib-only: use `TcpListener`/`TcpStream`, the existing JSON
helpers, and no Cargo dependencies or HTTP crates. Treat exact paths, response
field order, error bodies/statuses, validation limits, and persistence formats
as public behavior.

Add a route in `handle`, keep its domain logic in a focused helper, and add the
corresponding persistence operation to `Storage` instead of embedding SQL in a
handler. Unit tests live in the `#[cfg(test)]` module at the end of
`src/main.rs`; add focused assertions there, run `cargo test`, and exercise
persistence-sensitive routes with `curl` against a fresh database. Do not start
`./run.sh` for a build-only verification.
