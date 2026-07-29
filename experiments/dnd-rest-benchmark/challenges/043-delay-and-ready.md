# Maintenance Stage 43: Delay and Ready

Preserve all earlier behavior. The current combatant may delay or ready an
action without duplicating turns.

`POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/delay` moves the current
combatant to a later position in the initiative order. Only the current
combatant or owner may call it. Return 200 with the new order. Reordering to an
illegal index returns 400.

`POST /v1/play/campaigns/{id}/encounters/{enc_id}/turn/ready` accepts
`{"trigger":"when the goblin moves"}`. Only the current combatant may call it.
Return 201 with the ready record: `{"actor":"player-a","trigger":"when the goblin moves"}`.
A ready action does not change the turn order.
