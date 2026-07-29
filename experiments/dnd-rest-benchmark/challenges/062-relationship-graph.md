# 062 Relationship Graph

This cumulative suite inherits `061-npc-dialogue`.

Preserve all earlier behavior. Add a directed relationship graph among campaign
entities. Campaign entities are exactly campaign member character IDs and NPC
IDs.

`POST /v1/play/campaigns/{id}/relationships` accepts:

`{"source_id":"npc-guide","target_id":"play-char-w","kind":"trust","score":25}`.

Only the campaign DM may create relationship edges. Players receive 403 for
creation. Both `source_id` and `target_id` must name existing campaign entities,
the IDs must differ, `kind` must be a nonempty string, and `score` must be an
integer from -100 through 100. Unknown campaign entities return 404. Invalid
self-edges, empty kinds, missing fields, and out-of-range or non-integer scores
return 400. Creating a duplicate directed `(source_id, target_id, kind)` edge
returns 409.

A valid create returns 201 exactly:

`{"source_id":"npc-guide","target_id":"play-char-w","kind":"trust","score":25}`.

`PUT /v1/play/campaigns/{id}/relationships/{source_id}/{target_id}/{kind}`
accepts:

`{"score":60}`.

Only the campaign DM may update relationship edges. Players receive 403 for
updates. The addressed relationship edge must already exist, otherwise the
request returns 404. The score must be an integer from -100 through 100. A valid
update returns 200 with the full updated edge exactly:

`{"source_id":"npc-guide","target_id":"play-char-w","kind":"trust","score":60}`.

`GET /v1/play/campaigns/{id}/relationships` is available to authenticated
campaign members and returns all edges in insertion order:

`{"edges":[...]}`

Each edge in the response is the exact full edge shape:

`{"source_id":"npc-guide","target_id":"play-char-w","kind":"trust","score":60}`.
