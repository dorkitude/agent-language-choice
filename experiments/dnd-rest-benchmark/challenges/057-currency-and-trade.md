# 057 Currency and Trade

This cumulative suite inherits `056-consumables`.

Preserve all earlier behavior. Add deterministic per-character gold balances
and atomic character-to-character transfers within a campaign.

Each campaign character begins with exactly 10 gold when the character joins a
campaign.

`GET /v1/play/campaigns/{id}/characters/{character_id}/currency` is available
to authenticated campaign members. Unknown campaign characters return 404. A
valid response returns 200:

`{"character_id":"play-char-w","gold":10}`.

`POST /v1/play/campaigns/{id}/characters/{character_id}/currency/transfers`
accepts:

`{"to_character_id":"play-char-b","gold":3}`.

Only the source character owner may transfer gold. Non-owners return 403.

The destination must be a different character in the same campaign. Unknown
destinations, same-character destinations, and non-positive gold amounts return
400.

If the source character has insufficient gold, return 409 and leave both source
and destination balances unchanged.

A valid transfer debits and credits atomically, assigns a deterministic
campaign-local transfer id starting at 1, and returns 201:

`{"from_character_id":"play-char-w","to_character_id":"play-char-b","gold":3,"from_gold":7,"to_gold":13,"transfer_id":1}`.
