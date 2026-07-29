# 067 Rumors

This cumulative suite inherits `066-world-events`.

Preserve all earlier behavior. Add deterministic campaign rumors that the DM
can publish, that players can discover exactly once through their campaign
character identity, and that readers see through role-filtered public REST
responses.

`POST /v1/play/campaigns/{id}/rumors` accepts:

`{"rumor_id":"rumor-cave","text":"A dragon was seen near the cave."}`

Only the campaign DM may publish rumors. Players receive 403. The `rumor_id`
and `text` fields must be nonempty strings. Invalid bodies return 400.
Duplicate rumor IDs in the same campaign return 409. Duplicate normalized text
also returns 409, where normalized text is `trim` then `lowercase`.

A valid publish request returns 201 exactly:

`{"rumor_id":"rumor-cave","text":"A dragon was seen near the cave.","discovered_by":[]}`

`POST /v1/play/campaigns/{id}/rumors/{rumor_id}/discover` accepts an empty JSON
body or no body.

Only authenticated campaign player members may discover rumors. The DM cannot
discover and receives 403. Unknown rumors return 404. Discovery records the
actor's campaign character ID once. A repeated discovery by the same character
returns 409 and does not duplicate the character ID.

A successful discovery returns 201 exactly:

`{"rumor_id":"rumor-cave","text":"A dragon was seen near the cave.","discovered_by":["play-char-a"]}`

`GET /v1/play/campaigns/{id}/rumors` is available to authenticated campaign
members. It returns rumors in creation order:

`{"rumors":[{"rumor_id":"rumor-cave","text":"A dragon was seen near the cave.","discovered_by":["play-char-a","play-char-b"]}]}`

DM responses include all discoverer character IDs in discovery order. Player
responses include only that player's own character ID when that character has
discovered the rumor; undiscovered rumors and rumors discovered only by other
characters have an empty `discovered_by` array.
