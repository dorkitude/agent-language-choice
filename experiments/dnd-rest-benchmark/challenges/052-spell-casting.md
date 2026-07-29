# Maintenance Stage 52: Spell Casting

Preserve all earlier behavior. Add, record, and read a character's spell casts.

`POST /v1/play/campaigns/{id}/characters/{character_id}/casts` accepts
`{"spell_id":"magic-missile","target":"training-dummy"}`.
Only the character owner may call it. Return 201 if the character is a
spellcasting class, knows the spell, has it currently prepared, and has at
least one remaining spell slot of the spell's level. At level 1 a wizard has
one first-level slot and can therefore cast a level 1 spell once. Return
`{"character_id":"play-char-w","spell_id":"magic-missile","target":"training-dummy","slot_level":1,"slots_remaining":0,"sequence":1}`.

Return 403 if the caller is not the character owner. Return 400 if the spell is
not currently prepared or if the character is not a spellcaster. Return 409 if
the character has no remaining spell slots of the required level.

`GET /v1/play/campaigns/{id}/characters/{character_id}/casts` is allowed for any
campaign member and returns the character's cast history as
`{"casts":[...]}`. The list contains the cast events in order and is
represented as `[]` when empty, never omitted or `null`.
