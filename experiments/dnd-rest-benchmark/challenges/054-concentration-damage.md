# Maintenance Stage 54: Concentration Damage Checks

Preserve all earlier behavior. Add deterministic concentration checks when a
character takes damage.

`POST /v1/play/campaigns/{id}/characters/{character_id}/concentration/damage`
accepts `{"damage":22,"roll":11}`. Only the character owner may call it. Return
403 if the caller is not the character owner.

Return 400 when the character has no active concentration, when `damage` is less
than one, or when the request body is invalid.

For valid requests, compute the concentration save DC as
`max(10, ceil(damage / 2))`. If `roll >= dc`, retain the current concentration
and return 200:

`{"character_id":"play-char-w","dc":11,"roll":11,"maintained":true,"concentration":{"spell_id":"magic-missile","target":"training-dummy","remaining_turns":3}}`

If `roll < dc`, clear concentration and return 200:

`{"character_id":"play-char-w","dc":13,"roll":12,"maintained":false,"concentration":null}`
