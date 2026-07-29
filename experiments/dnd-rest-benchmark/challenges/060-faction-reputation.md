# 060 Faction Reputation

This cumulative suite inherits `059-npc-agendas`.

Preserve all earlier behavior. Add campaign faction creation and bounded
character reputation history.

`POST /v1/play/campaigns/{id}/factions` accepts:

`{"faction_id":"faction-harpers","name":"Harpers"}`.

Only the campaign DM may create factions. `faction_id` and `name` are required
nonempty strings. Duplicate `faction_id` values within the same campaign return
409. A valid request creates the faction and returns 201 exactly:

`{"faction_id":"faction-harpers","name":"Harpers"}`.

`POST /v1/play/campaigns/{id}/factions/{faction_id}/reputation` accepts:

`{"character_id":"play-char-w","delta":15,"reason":"rescued-prisoners"}`.

Only the campaign DM may change reputation. Unknown factions return 404.
`character_id` must identify a campaign member character. `delta` must be a
nonzero integer in `[-25,25]`. `reason` is a required nonempty string. The
stored total reputation for each faction/character pair is bounded to
`[-100,100]`. Each accepted change stores an immutable history record and
returns 201 exactly:

`{"faction_id":"faction-harpers","character_id":"play-char-w","reputation":15,"delta":15,"reason":"rescued-prisoners"}`.

`GET /v1/play/campaigns/{id}/factions/{faction_id}/reputation` is available to
authenticated campaign members. Unknown factions return 404. The response shape
is:

`{"faction_id":"faction-harpers","entries":[...]}`

The DM sees all history entries in insertion order. Each entry is exactly:

`{"faction_id","character_id","reputation","delta","reason"}`

Players see only entries for their own campaign character. Players cannot
create factions or change reputation and receive 403 for those mutating
requests.
