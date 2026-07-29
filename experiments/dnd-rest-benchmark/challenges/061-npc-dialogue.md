# 061 NPC Dialogue

This cumulative suite inherits `060-faction-reputation`.

Preserve all earlier behavior. Add attributed dialogue history for campaign
NPCs, with private entries visible only to the DM.

`POST /v1/play/campaigns/{id}/npcs/{npc_id}/dialogue` accepts:

`{"dialogue_id":"dialogue-welcome","speaker":"Sildar","text":"Welcome to Phandalin.","visibility":"public"}`.

Only the campaign DM may append NPC dialogue. Unknown NPCs return 404.
`dialogue_id`, `speaker`, and `text` are required nonempty strings.
`visibility` must be exactly `public` or `private`. Duplicate `dialogue_id`
values within the same NPC return 409. A valid request creates the dialogue
entry and returns 201 exactly:

`{"dialogue_id":"dialogue-welcome","speaker":"Sildar","text":"Welcome to Phandalin.","visibility":"public"}`.

`GET /v1/play/campaigns/{id}/npcs/{npc_id}/dialogue` is available to
authenticated campaign members. Unknown NPCs return 404. The response shape is:

`{"npc_id":"npc-guide","entries":[...]}`

The DM sees all dialogue entries in insertion order, including public and
private entries. Players receive the same response shape, but `entries` contains
only entries whose `visibility` is `public`. Private text must never appear in
player dialogue history responses.

Players cannot append dialogue and receive 403 for that mutating request.
