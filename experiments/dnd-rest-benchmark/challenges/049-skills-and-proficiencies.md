# Maintenance Stage 49: Skills and Proficiencies

Preserve all earlier behavior. Resolve skill-check modifiers using a character's
ability and proficiency.

`POST /v1/play/campaigns/{id}/characters/{char_id}/skill-check` accepts
`{"skill":"stealth","ability":"dex","proficient":true,"roll":15}`.
Only the character's owner may call it. Return 200 with
`{"character_id":"play-char-a","skill":"stealth","ability":"dex","modifier":5,"total":20}`.

Modifier = `ability_modifier + (proficiency_bonus if proficient else 0)`. Total =
`roll + modifier`. Non-owners or unsupported skills/abilities return 403/400.
