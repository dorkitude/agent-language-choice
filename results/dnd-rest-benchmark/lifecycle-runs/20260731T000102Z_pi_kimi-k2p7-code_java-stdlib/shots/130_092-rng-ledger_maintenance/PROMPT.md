```text
You are participating in a staged programming-language benchmark.

        Target: java-stdlib
        Language: java
        Framework/runtime: stdlib
        Lifecycle stage: 092-rng-ledger
        Shot kind: maintenance

        You are a fresh maintenance agent inheriting this existing codebase. Add the requested feature stage while preserving all existing API behavior.

        Use the exact latest runtime/framework versions already pinned in this
        workspace. Do not downgrade packages or replace the requested framework.

        Relevant version pins:
        - @types/node: 26.1.1
- @types/react: 19.2.17
- @types/react-dom: 19.2.3
- @vitejs/plugin-react: 6.0.3
- composer: 2.10.2
- django: 6.0.7
- flask: 3.1.3
- go: 1.26.5
- next: 16.2.10
- node: 26.4.0
- openjdk: 26.0.1
- php: 8.5.8
- puma: 8.0.2
- python: 3.14.6
- rack: 3.2.6
- rackup: 2.3.1
- rails: 8.1.3
- react: 19.2.7
- react-dom: 19.2.7
- ruby: 4.0.5
- rust: 1.97.0
- sinatra: 4.2.1
- slim: 4.15.2
- slim-psr7: 1.8.0
- symfony-http-foundation: 8.1.1
- symfony-routing: 8.1.0
- typescript: 7.0.2
- vite: 8.1.3

        Target guidance:
        Use OpenJDK 26.0.1 and only the Java standard library, such as com.sun.net.httpserver.HttpServer.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 092 Deterministic RNG Ledger

This cumulative suite inherits `091-deterministic-replay`.

Preserve all earlier behavior. Add a campaign-scoped deterministic RNG seed
and immutable roll ledger for authenticated campaign members. The feature
must not expose any untracked outcome endpoint.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Non-member users return
403. The campaign DM is also a campaign member for read and roll purposes.

## Stable Roll Algorithm

Implementations must not use `math/rand`, wall-clock time, process-global RNG
state, UUID randomness, database autoincrement values, or provider output.

For a successful roll, first assign the append-order `sequence`, starting at
1 for the campaign RNG ledger. Build this exact byte string:

`seed + "|" + decimal(sequence) + "|" + roll_id + "|" + decimal(sides)`

Then compute an unsigned 32-bit accumulator:

1. Start with `acc = 0`.
2. For each UTF-8 byte `b` in the byte string, set
   `acc = (acc * 31 + b) mod 2^32`.
3. The exact result is `(acc mod sides) + 1`.

For seed `ember-seed`, the first three accepted rolls below must be exactly
3, 1, and 46.

## Configure RNG Seed

`PUT /v1/play/campaigns/{id}/rng-seed`

The request body is:

`{"seed":"ember-seed"}`

Only the campaign DM may configure the seed. `seed` must be a nonempty string.
Missing or empty seed returns 400. Replacing an already configured seed returns
409 and must not mutate the ledger.

Success returns 200 with stable ledger state:

`{"seed":"ember-seed","rolls":[]}`

## Append RNG Roll

`POST /v1/play/campaigns/{id}/rng-rolls`

The request body is:

`{"roll_id":"initiative","sides":20}`

Authenticated campaign members, including the DM, may append rolls. A roll
requires a configured seed; if no seed exists, return 409. `roll_id` must be a
nonempty string and unique within the campaign RNG ledger. Duplicate
`roll_id` values return 409 and must not append. `sides` must be an integer
from 2 through 100 inclusive; otherwise return 400.

Successful appends return 201 with the immutable ledger record:

`{"roll_id":"initiative","sides":20,"result":3,"sequence":1}`

Using seed `ember-seed`, these accepted requests must produce this exact
ordered ledger:

1. `{"roll_id":"initiative","sides":20}` -> result 3, sequence 1
2. `{"roll_id":"secret-door","sides":6}` -> result 1, sequence 2
3. `{"roll_id":"morale","sides":100}` -> result 46, sequence 3

## Read RNG Ledger

`GET /v1/play/campaigns/{id}/rng-ledger`

Authenticated campaign members read the exact seed plus ordered immutable roll
records. The response after the three accepted rolls above is:

`{"seed":"ember-seed","rolls":[{"roll_id":"initiative","sides":20,"result":3,"sequence":1},{"roll_id":"secret-door","sides":6,"result":1,"sequence":2},{"roll_id":"morale","sides":100,"result":46,"sequence":3}]}`



        Finish when ./run.sh is ready.
```
