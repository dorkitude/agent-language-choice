```text
You are participating in a staged programming-language benchmark.

        Target: go-open
        Language: go
        Framework/runtime: open-modules
        Lifecycle stage: 070-shops
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

        # 070 Shops

Preserve all earlier behavior. Add settlement shops with deterministic stock,
prices, and player buy/sell operations backed by campaign inventory and
currency.

## Shop Object

A shop response is exactly:

`{"shop_id":"shop-lionshield","name":"Lionshield Coster","stock":{"healing-potion":3},"buy_price":2,"sell_price":1}`

`shop_id` and `name` must be nonempty strings. `stock` must be a nonempty JSON
object whose keys are valid campaign inventory item catalog IDs and whose
values are positive integer quantities. `buy_price` must be a positive integer.
`sell_price` must be a nonnegative integer. Shop IDs must be unique within one
settlement.

## Endpoints

`POST /v1/play/campaigns/{id}/settlements/{settlement_id}/shops`

Only the campaign DM may create shops. Players receive 403. Unknown campaigns
or settlements return 404. Invalid payloads return 400. Duplicate shop IDs in
the same settlement return 409.

The request body is:

`{"shop_id":"shop-lionshield","name":"Lionshield Coster","stock":{"healing-potion":3},"buy_price":2,"sell_price":1}`

A successful create returns 201 and the exact shop object.

`GET /v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}`

Authenticated campaign members may get a shop. The DM may always read shops.
Players may read a shop only after that player's character has discovered the
containing settlement. Undiscovered shops return 404 to players. Unknown
settlements or shops return 404. A successful response returns the exact shop
object.

`POST /v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/buy`

Only the player who owns `character_id` may buy. The DM receives 403.
Non-owners receive 403. Unknown shops, settlements, or characters return 404.
The body is:

`{"character_id":"play-char-w","item_id":"healing-potion","quantity":1}`

`item_id` must be a valid inventory item and `quantity` must be positive. The
shop must have enough stock, and the character must have at least
`buy_price * quantity` gold. Insufficient stock or funds return 409 and must
not partially mutate state.

A successful buy decrements shop stock, subtracts gold, adds the purchased
items to the character inventory, and returns exactly:

`{"character_id":"play-char-w","item_id":"healing-potion","quantity":1,"gold":8,"stock":2}`

`POST /v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/sell`

Only the player who owns `character_id` may sell. The DM receives 403.
Non-owners receive 403. Unknown shops, settlements, or characters return 404.
The body matches buy:

`{"character_id":"play-char-w","item_id":"healing-potion","quantity":1}`

`item_id` must be a valid inventory item and `quantity` must be positive. The
character must have enough inventory. Insufficient inventory returns 409 and
must not partially mutate state.

A successful sell removes items from character inventory, adds
`sell_price * quantity` gold, increments shop stock, and returns exactly:

`{"character_id":"play-char-w","item_id":"healing-potion","quantity":1,"gold":9,"stock":3}`



        Finish when ./run.sh is ready.
```
