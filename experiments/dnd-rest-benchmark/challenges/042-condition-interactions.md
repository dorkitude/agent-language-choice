# Maintenance Stage 42: Condition Interactions

Preserve all earlier behavior. Apply and expire named conditions on encounter
combatants.

`POST /v1/play/campaigns/{id}/encounters/{enc_id}/conditions` accepts
`{"target":"goblin-1","condition":"blinded","duration_rounds":2}`. Only the
owner may call it. Return 201 with the target's current conditions:
`{"target":"goblin-1","conditions":[{"condition":"blinded","remaining_rounds":2}]}`.

`GET /v1/play/campaigns/{id}/encounters/{enc_id}/status` returns the full
encounter state including `round`, `turn_index`, `active`, `order`, and a
`conditions` map for any campaign member.

Conditions decrement their `remaining_rounds` at the start of the target's
turn; a condition with 0 remaining is removed.
