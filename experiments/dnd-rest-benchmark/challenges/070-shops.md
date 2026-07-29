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
