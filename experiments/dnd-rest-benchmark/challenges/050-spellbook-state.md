# Maintenance Stage 50: Spellbook State

Preserve all earlier behavior. Add, list, and validate known spells against a
character's class.

`POST /v1/play/campaigns/{id}/characters/{char_id}/spells` accepts
`{"spell_id":"fire-bolt","name":"Fire Bolt","level":0}`.
Only the owner may call it. Return 201 if the spell is valid for the character's
class; wizards may know any wizard spell, rogues may not learn spells. Return 400
for an invalid class/spell combination.

`GET /v1/play/campaigns/{id}/characters/{char_id}/spells` returns the spellbook
for any campaign member: `{"spells":[{"spell_id":"fire-bolt","name":"Fire Bolt","level":0}]}`.

A character may know at most one copy of a spell; duplicates return 409.
