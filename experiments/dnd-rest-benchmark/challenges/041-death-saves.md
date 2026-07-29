# Maintenance Stage 41: Death Saves

Preserve all earlier behavior. Track stable success/failure counters and
unconscious/dead state transitions for a character at 0 HP.

The owner may reduce a character to 0 HP with
`POST /v1/play/campaigns/{id}/characters/{char_id}/damage {"amount":20}`;
when a character's `hp_current` reaches 0, its status becomes `unconscious`.

`POST /v1/play/campaigns/{id}/characters/{char_id}/death-saves` accepts
`{"outcome":"success"}` or `{"outcome":"failure"}`. Only the character's owner
may call it. Return 201 with the updated counters:
`{"character_id":"play-char-a","successes":1,"failures":0,"status":"unconscious"}`.

Three successes make the character `stable` (no further rolls accepted). Three
failures make the character `dead`. Non-owners or rolls on a conscious
character return 403/409.

`GET /v1/play/campaigns/{id}/characters/{char_id}/status` returns
`{"character_id":"play-char-a","hp_current":0,"hp_max":20,"status":"unconscious"}`
for any campaign member.
