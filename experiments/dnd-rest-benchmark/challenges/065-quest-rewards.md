# 065 Quest Rewards

This cumulative suite inherits `064-quest-dependencies`.

Preserve all earlier behavior. Add configured quest rewards that can be awarded
exactly once after quest completion.

`PUT /v1/play/campaigns/{id}/quests/{quest_id}/rewards` accepts:

`{"xp":100,"items":{"healing-potion":1}}`

Only the campaign DM may configure quest rewards. Players receive 403. Unknown
quests return 404. The quest must exist and have state `locked` or `active`;
completed quests reject configuration with 409. `xp` must be a nonnegative
integer. `items` must be a JSON object whose keys are valid catalog item IDs and
whose values are positive integer quantities. Invalid reward bodies return 400.

A valid configure request returns 200 with the full quest record including
rewards:

`{"quest_id":"quest-reward","title":"Recover the cache","depends_on":[],"state":"active","rewards":{"xp":100,"items":{"healing-potion":1}}}`

`POST /v1/play/campaigns/{id}/quests/{quest_id}/rewards/award` has no request
body.

Only the campaign DM may award quest rewards. Players receive 403. Unknown
quests return 404. The quest state must be `completed` and rewards must already
be configured; otherwise the request returns 409. A successful award grants the
configured XP and items once to every campaign member and returns 201 exactly:

`{"quest_id":"quest-reward","awarded":true,"xp":100,"items":{"healing-potion":1}}`

A repeat award returns 409 and makes no changes.

`GET /v1/play/campaigns/{id}/characters/{character_id}/rewards` is available to
authenticated campaign members. Unknown characters return 404. A valid request
returns cumulative quest reward grants for that character:

`{"character_id":"play-char-w","xp":100,"items":{"healing-potion":1}}`
