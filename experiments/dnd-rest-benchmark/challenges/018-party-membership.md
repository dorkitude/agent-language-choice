# Maintenance Stage 18: Party Membership

Preserve all earlier behavior. An authenticated player joins a lobby campaign
with `POST /v1/play/campaigns/{id}/members` and
`{"character_id":"play-char-a","name":"Aria","class":"rogue"}`.
Return 201 with the actor username plus those character fields. A player owns
at most one membership per campaign; character IDs are unique; a full party or
duplicate returns 409. Only players may join.
