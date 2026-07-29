# 064 Quest Dependencies

This cumulative suite inherits `063-secrets-and-clues`.

Preserve all earlier behavior. Add deterministic campaign quest records whose
activation is gated by completed prerequisite quests.

`POST /v1/play/campaigns/{id}/quests` accepts:

`{"quest_id":"quest-scout","title":"Scout the cave","depends_on":[]}`

or the same shape with `depends_on` containing existing quest IDs.

Only the campaign DM may create quests. Players receive 403 for creation.
`quest_id` and `title` are required nonempty strings. `depends_on` must be a
JSON array of unique quest IDs. Dependencies cannot include the quest's own ID
and every dependency must already exist in the same campaign. Invalid
dependency lists return 400. Quest IDs are unique per campaign; duplicates
return 409.

A valid quest create returns 201 exactly:

`{"quest_id":"quest-scout","title":"Scout the cave","depends_on":[],"state":"locked"}`

`PUT /v1/play/campaigns/{id}/quests/{quest_id}/state` accepts:

`{"state":"active"}`

or:

`{"state":"completed"}`

Only the campaign DM may change quest state. Players receive 403 for state
changes. Unknown quests return 404. `state` must be exactly `active` or
`completed`; invalid state values return 400.

Allowed transitions are:

- `locked` to `active`, only when every quest in `depends_on` has state
  `completed`.
- `active` to `completed`.

All other transitions return 409. A successful state change returns 200 with
the full quest record:

`{"quest_id":"quest-scout","title":"Scout the cave","depends_on":[],"state":"active"}`

`GET /v1/play/campaigns/{id}/quests` is available to authenticated campaign
members and returns:

`{"quests":[...]}`

Quests are returned in creation order. Each quest uses the exact creation
response shape with its current `state`.
