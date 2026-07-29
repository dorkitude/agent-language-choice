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
