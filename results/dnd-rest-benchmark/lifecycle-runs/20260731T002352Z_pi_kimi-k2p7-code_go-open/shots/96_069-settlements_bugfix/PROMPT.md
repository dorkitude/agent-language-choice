```text
You are participating in a staged programming-language benchmark.

        Target: go-open
        Language: go
        Framework/runtime: open-modules
        Lifecycle stage: 069-settlements
        Shot kind: bugfix

        You are a fresh bug-fix agent inheriting this existing codebase after a deterministic evaluator failure.

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
        Use Go 1.26.5. Third-party Go modules are allowed and should be recorded in go.mod/go.sum. Choose idiomatic libraries where they reduce implementation risk; for real SQLite support, prefer the pure-Go modernc.org/sqlite driver (or another compatible driver) rather than requiring CGO. Runtime network access remains forbidden.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 069 Settlements

Preserve all earlier behavior. Add DM-managed campaign settlements with
validated services, availability, and player discovery.

## Settlement Object

A settlement response is exactly:

`{"settlement_id":"settle-phandalin","name":"Phandalin","services":["inn","smithy","temple"],"availability":"open","discovered_by":[]}`

`settlement_id` and `name` must be nonempty strings. `services` must be a
nonempty JSON array of nonempty strings. Services are normalized by trimming
surrounding whitespace for storage and responses, and the normalized values
must be unique. Preserve service order from the accepted request.

`availability` must be exactly one of `open`, `limited`, or `closed`.

`discovered_by` is an ordered list of player character IDs that have discovered
the settlement. DM responses include all discoverers. Player responses include
only that player's own character ID, and only for settlements the player has
discovered.

## Endpoints

`POST /v1/play/campaigns/{id}/settlements`

Only the campaign DM may create settlements. Players receive 403. Unknown
campaigns return 404. Invalid payloads return 400. Duplicate settlement IDs in
the same campaign return 409.

The request body is:

`{"settlement_id":"settle-phandalin","name":"Phandalin","services":["inn","smithy","temple"],"availability":"open"}`

A successful create returns 201 and the exact settlement object.

`PUT /v1/play/campaigns/{id}/settlements/{settlement_id}`

Only the campaign DM may replace a settlement's `name`, `services`, and
`availability`. Players receive 403. Unknown settlements return 404. The body
uses the same fields as create except `settlement_id` is taken from the path.
Validation rules are identical to create. A successful update returns 200 and
the exact settlement object, preserving existing `discovered_by` order.

`POST /v1/play/campaigns/{id}/settlements/{settlement_id}/discover`

Only joined campaign players may discover settlements. The DM receives 403.
Unknown settlements return 404. The first discovery by a player's character
appends that character ID to `discovered_by` and returns 201 with the exact
player-filtered settlement object. Repeating the same discovery is idempotent:
it must not append a duplicate and returns 200 with the same exact
player-filtered settlement object.

`GET /v1/play/campaigns/{id}/settlements`

Authenticated campaign members may list settlements. The DM sees every
settlement in creation order and each settlement's full `discovered_by` list.
Players see only settlements discovered by their own character, in creation
order, with `discovered_by` limited to their own character ID.



The previous evaluator attempt did not pass. Before editing, inspect
`evaluations/069-01.json` and the raw logs it references. Fix the
implementation so the same evaluator suite passes without removing
previously implemented behavior.


        Finish when ./run.sh is ready.
```
