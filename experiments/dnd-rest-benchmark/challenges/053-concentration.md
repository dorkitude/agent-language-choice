# Maintenance Stage 53: Concentration

Preserve all earlier behavior. Add, read, replace, advance, and clear a
character's current concentration state.

`PUT /v1/play/campaigns/{id}/characters/{character_id}/concentration` accepts
`{"spell_id":"magic-missile","target":"training-dummy","duration_turns":2}`.
Only the character owner may call it. Return 200 if the character is a
spellcasting class, knows the spell, has it currently prepared, and the duration
is positive. The response is
`{"character_id":"play-char-w","concentration":{"spell_id":"magic-missile","target":"training-dummy","remaining_turns":2}}`.

A second valid `PUT` replaces any existing concentration for that character
instead of appending or rejecting it. The response shape is the same with the new
spell, target, and remaining turn count.

`GET /v1/play/campaigns/{id}/characters/{character_id}/concentration` is allowed
for any campaign member and returns
`{"character_id":"play-char-w","concentration":{...}}` when concentration is
active. When no concentration is active, return
`{"character_id":"play-char-w","concentration":null}`.

`POST /v1/play/campaigns/{id}/characters/{character_id}/concentration/advance-turn`
is allowed for any campaign member. It decrements the active concentration's
`remaining_turns` by one and clears concentration when the count reaches zero.
Return the same shape as the read endpoint after applying the turn advance.

`DELETE /v1/play/campaigns/{id}/characters/{character_id}/concentration` is
allowed only for the character owner. It clears concentration and returns
`{"character_id":"play-char-w","concentration":null}`. Return 403 if the caller
is not the character owner. Return 400 if the spell is unknown, not currently
prepared, the character is not a spellcaster, or `duration_turns` is less than
one.
