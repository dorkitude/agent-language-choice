# Maintenance Stage 40: Damage and Healing

Preserve all earlier behavior. The owner applies deterministic damage and
healing to encounter combatants.

## Damage

`POST /v1/play/campaigns/{id}/encounters/{enc_id}/damage` accepts
`{"target":"goblin-1","amount":5}`. Only the owner may call it. Return 200 with
`{"target":"goblin-1","hp_before":7,"hp_after":2,"damage":5}`. HP floors at 0.

## Healing

`POST /v1/play/campaigns/{id}/encounters/{enc_id}/heal` accepts
`{"target":"goblin-1","amount":3}`. Only the owner may call it. Return 200 with
`{"target":"goblin-1","hp_before":2,"hp_after":5,"healing":3}`. HP caps at
`hp_max`.
