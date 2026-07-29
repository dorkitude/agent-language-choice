# Maintenance Stage 51: Spell Preparation

Preserve all earlier behavior. Add, update, and read a character's prepared
spells.

`PUT /v1/play/campaigns/{id}/characters/{character_id}/prepared-spells` accepts
`{"spell_ids":["fire-bolt"]}`.
Only the character owner may call it. Return 200 if the character is a
spellcasting class, knows the spell, and the list length does not exceed the
class level's maximum prepared spells; at level 1 a wizard may prepare at most
one spell. Return
`{"character_id":"play-char-w","prepared_spells":["fire-bolt"],"max_prepared":1}`.

Return 400 for a rogue, an unknown spell, or a prepared list that exceeds the
maximum allowed count.

Return 403 if the caller is not the character owner.

`GET /v1/play/campaigns/{id}/characters/{character_id}/prepared-spells` is
allowed for any campaign member and returns the same prepared-spells response.
An empty prepared list is represented as `[]`, never omitted or `null`.
