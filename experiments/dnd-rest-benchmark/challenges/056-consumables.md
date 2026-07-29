# 056 Consumables

This cumulative suite inherits `055-equipment-and-attunement`.

Preserve all earlier behavior, including the 054 inventory stack and 055
equipment/attunement contracts. Add owner-controlled consumption for declared
consumable inventory items.

`POST /v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}/consume`
has no request body. Only the character owner may consume a held item.

Only `healing-potion` is consumable. Valid catalog items that are not
consumable, including `torch`, `leather-armor`, `ring-of-protection`, and
`amulet-of-health`, return 400. Unknown item IDs also return 400.

If the character has no held stack for `healing-potion`, or the held stack has
quantity zero, the request returns 409.

A valid healing potion consumption decrements exactly one stack unit and returns
200:

`{"character_id":"play-char-w","item_id":"healing-potion","quantity_consumed":1,"total_quantity":0,"effect":{"type":"healing","hp_restored":5}}`.

When consumption reduces a stack to zero, subsequent
`GET /v1/play/campaigns/{id}/characters/{character_id}/inventory/items` must no
longer list that item.
