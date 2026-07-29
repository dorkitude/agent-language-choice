# 058 Loot Distribution

This cumulative suite inherits `057-currency-and-trade`.

Preserve all earlier behavior. Add campaign-scoped loot records that the DM can
open, players can vote on, and the DM can assign exactly once.

`POST /v1/play/campaigns/{id}/loot` accepts:

`{"loot_id":"loot-1","item_id":"healing-potion","quantity":1}`.

Only the campaign DM may create loot. The `item_id` must be a known inventory
catalog item and `quantity` must be positive. A valid request creates an
immutable open loot record and returns 201:

`{"loot_id":"loot-1","item_id":"healing-potion","quantity":1,"status":"open"}`.

Duplicate `loot_id` values within the same campaign return 409.

`POST /v1/play/campaigns/{id}/loot/{loot_id}/votes` accepts:

`{"recipient_character_id":"play-char-b"}`.

Only authenticated campaign players may vote. The recipient must be a character
in the same campaign. Each player identity may cast one immutable vote per loot
record; duplicate or changed votes return 409. A valid vote returns 201:

`{"loot_id":"loot-1","voter":"player-a","recipient_character_id":"play-char-b","votes_for_recipient":1}`.

`POST /v1/play/campaigns/{id}/loot/{loot_id}/assign` has no body.

Only the campaign DM may assign loot. Assignment requires the loot to be open
and to have a single unambiguous highest vote recipient. Tied or voteless loot
returns 409. A valid assignment atomically adds the loot quantity to the
recipient character inventory, closes the loot, and returns 200:

`{"loot_id":"loot-1","recipient_character_id":"play-char-b","item_id":"healing-potion","quantity":1,"votes":2,"status":"assigned"}`.

Duplicate assignment attempts return 409 and must not add inventory again.

`GET /v1/play/campaigns/{id}/loot/{loot_id}` is available to authenticated
campaign members. Unknown loot returns 404. The response returns the immutable
record, including `loot_id`, `item_id`, `quantity`, `status`,
`recipient_character_id`, and `votes`.
