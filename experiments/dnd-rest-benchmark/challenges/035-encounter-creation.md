# Maintenance Stage 35: Encounter Creation

Preserve all earlier behavior. The owner starts a campaign-bound encounter
from the current party state.

`POST /v1/play/campaigns/{id}/encounters` accepts `{"id":"enc-road","name":"Road Ambush"}`.
Only the owner may call it. Return 201 with
`{"id":"enc-road","name":"Road Ambush","status":"active","combatants":[]}`.
Duplicate IDs or a campaign already in combat return 409.

The encounter is independent from the exploration turn queue until the
campaign returns to exploration.
