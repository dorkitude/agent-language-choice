# 055 Equipment and Attunement

Preserve all earlier behavior, including the 054 inventory item stack contract.
Extend the inventory catalog with `leather-armor`, `ring-of-protection`, and
`amulet-of-health`; `POST /v1/play/campaigns/{id}/characters/{character_id}/inventory/items`
may add those item IDs using the same owner and quantity rules as 054.

`PUT /v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}`
accepts `{"item_id":"leather-armor"}`. Only the character owner may equip
items. Valid slots are `armor` and `accessory`. The item must be held in the
character inventory and must match its legal slot:

- `leather-armor`: `armor`
- `ring-of-protection`: `accessory`
- `amulet-of-health`: `accessory`

Invalid slots, unknown item IDs, unheld items, and slot mismatches return 400.

Valid equipment requests return 200:

`{"character_id":"play-char-w","slot":"armor","item_id":"leather-armor","attuned":false}`.

`GET /v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}` is
allowed to any campaign member. It returns the equipped item for that slot using
the same equipment response shape. Reading a valid empty slot returns
`{"character_id":"...","slot":"armor","item_id":"","attuned":false}`.

`POST /v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}/attune`
has no request body. Only the character owner may attune. The slot must contain
an equipped attunable accessory: `ring-of-protection` or `amulet-of-health`.
Only one item may be attuned per character. A second attunement returns 409.

Valid attunement requests return 200:

`{"character_id":"play-char-w","slot":"accessory","item_id":"ring-of-protection","attuned":true,"attunement_count":1,"max_attunements":1}`.
