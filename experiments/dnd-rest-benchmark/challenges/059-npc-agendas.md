# 059 NPC Agendas

This cumulative suite inherits `058-loot-distribution`.

Preserve all earlier behavior. Add DM-managed campaign NPC records with a
private agenda and player-visible public status.

`POST /v1/play/campaigns/{id}/npcs` accepts:

`{"npc_id":"npc-guide","name":"Sildar","agenda":"find-gundren","public_status":"searching"}`.

Only the campaign DM may create NPCs. `npc_id`, `name`, `agenda`, and
`public_status` are required nonempty strings. Duplicate `npc_id` values within
the same campaign return 409. A valid request creates the NPC and returns 201
with all fields:

`{"npc_id":"npc-guide","name":"Sildar","agenda":"find-gundren","public_status":"searching"}`.

`PUT /v1/play/campaigns/{id}/npcs/{npc_id}/agenda` accepts:

`{"agenda":"reach-cragmaw","public_status":"traveling"}`.

Only the campaign DM may update an NPC agenda. `agenda` and `public_status` are
required nonempty strings. Unknown NPCs return 404. A valid update returns 200
with the full DM shape:

`{"npc_id":"npc-guide","name":"Sildar","agenda":"reach-cragmaw","public_status":"traveling"}`.

`GET /v1/play/campaigns/{id}/npcs/{npc_id}` is available to authenticated
campaign members. Unknown NPCs return 404. DM responses include `agenda`.
Player responses include only:

`{"npc_id":"npc-guide","name":"Sildar","public_status":"traveling"}`.

Player responses must never include `agenda`. Players cannot create or update
NPCs and receive 403 for those mutating requests.
