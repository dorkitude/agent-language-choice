# Maintenance Stage 38: Combat Turn Authority

Preserve all earlier behavior. Only the current combatant or the owner may
advance a combat turn.

`GET /v1/play/campaigns/{id}/encounters/{enc_id}/turn` returns the current
combatant for any campaign member:
`{"round":1,"turn_index":0,"active":{"name":"Goblin","kind":"monster","initiative":15}}`.

`POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/advance` advances to the
next combatant in deterministic initiative order. Only the owner or the current
combatant may call it. Return 200 with the new active combatant. Acting out of
turn returns 409.
