# 063 Secrets and Clues

This cumulative suite inherits `062-relationship-graph`.

Preserve all earlier behavior. Add campaign clues that the DM may reveal to one
character, the party, or nobody.

`POST /v1/play/campaigns/{id}/clues` accepts:

`{"clue_id":"clue-letter","text":"The Black Spider seeks Wave Echo Cave.","audience":"character","character_id":"play-char-w"}`.

Only the campaign DM may create clues. Players receive 403 for creation.
`clue_id` and `text` are required nonempty strings. `audience` must be exactly
`character`, `party`, or `hidden`.

For `character` audience, `character_id` is required and must name a campaign
member character. Unknown characters return 400. For `party` and `hidden`
audience, `character_id` must be omitted. Unknown or invalid audiences and
invalid audience/character combinations return 400. Clue IDs are unique per
campaign; duplicates return 409.

A valid character clue create returns 201 exactly:

`{"clue_id":"clue-letter","text":"The Black Spider seeks Wave Echo Cave.","audience":"character","character_id":"play-char-w"}`

A valid party or hidden clue create returns 201 exactly:

`{"clue_id":"clue-party","text":"The cave entrance lies east of Phandalin.","audience":"party"}`

`GET /v1/play/campaigns/{id}/clues` is available to authenticated campaign
members and returns:

`{"clues":[...]}`

The DM receives all clues in insertion order. A player receives party clues and
character clues targeted to their own character only. Hidden clues and clues
targeted to another player's character never appear in player responses. Each
returned clue uses the exact creation response shape: character clues include
`character_id`; party and hidden clues omit `character_id`.
