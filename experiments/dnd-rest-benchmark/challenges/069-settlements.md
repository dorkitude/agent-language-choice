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
