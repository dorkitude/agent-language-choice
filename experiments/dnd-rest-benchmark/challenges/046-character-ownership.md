# Maintenance Stage 46: Character Ownership

Preserve all earlier behavior. Each campaign character is linked to exactly
one player identity.

`GET /v1/play/campaigns/{id}/characters/{char_id}/owner` returns
`{"character_id":"play-char-a","owner":"player-a"}` for any campaign member.

`POST /v1/play/campaigns/{id}/characters/{char_id}/claim` allows the requesting
player to claim an unowned character. Return 201 with the owner. If the
character is already owned by another player, return 409. The owner may
transfer ownership to another member with `POST .../transfer` and
`{"new_owner":"player-b"}`; only the owner may transfer, and the new owner must
be a campaign member.
