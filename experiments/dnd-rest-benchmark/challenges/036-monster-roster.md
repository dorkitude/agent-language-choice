# Maintenance Stage 36: Monster Roster

Preserve all earlier behavior. The owner adds and removes deterministic monster
combatants within an encounter.

## Add monster

`POST /v1/play/campaigns/{id}/encounters/{enc_id}/monsters` accepts
`{"monster_id":"goblin-1","name":"Goblin","hp_max":7,"initiative":15}`.
Only the owner may call it. Return 201 with the monster fields plus
`{"hp_current":7}`. Duplicate IDs return 409.

## Remove monster

`DELETE /v1/play/campaigns/{id}/encounters/{enc_id}/monsters/{monster_id}`
removes the monster. Only the owner may call it. Return 200 with
`{"removed":"goblin-1}`.
