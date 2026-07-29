# 054 Inventory Stacks

Preserve all earlier behavior. Add per-character inventory item stacks.

`POST /v1/play/campaigns/{id}/characters/{character_id}/inventory/items`
accepts `{"item_id":"healing-potion","quantity":2}`. Only the character owner
may add items. Valid item IDs are `healing-potion` and `torch`. Quantity must be
positive. Invalid item IDs or quantities return 400.

Valid requests increment that character's item stack and return 201:

`{"character_id":"play-char-w","item_id":"healing-potion","quantity":2,"total_quantity":2}`.

`GET /v1/play/campaigns/{id}/characters/{character_id}/inventory/items` is
allowed to any campaign member and returns 200:

`{"character_id":"play-char-w","items":[{"item_id":"healing-potion","quantity":2}]}`.

Items must be returned in lexicographic `item_id` order. Characters with no
held items return `{"character_id":"...","items":[]}`.

`DELETE /v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}`
accepts `{"quantity":1}`. Only the character owner may remove items. Quantity
must be positive and no larger than the held stack. Invalid quantities or
unknown catalog items return 400. Removing more than the held quantity returns
409.

Valid removal requests decrement the stack and return 200 using the same item
response shape with the remaining `total_quantity`.
