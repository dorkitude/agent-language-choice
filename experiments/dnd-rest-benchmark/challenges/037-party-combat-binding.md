# Maintenance Stage 37: Party/Combat Binding

Preserve all earlier behavior. The owner binds campaign party members to and
from an active encounter as combatants.

## Bind member

`POST /v1/play/campaigns/{id}/encounters/{enc_id}/combatants` accepts
`{"member":"player-a","initiative":14}`. Only the owner may call it. Return 201
with `{"member":"player-a","character_id":"play-char-a","name":"Aria","initiative":14}`.
Duplicate members return 409; missing members return 400.

## Unbind member

`DELETE /v1/play/campaigns/{id}/encounters/{enc_id}/combatants/{member}` removes
the member from the encounter. Only the owner may call it. Return 200 with
`{"removed":"player-a}`.
