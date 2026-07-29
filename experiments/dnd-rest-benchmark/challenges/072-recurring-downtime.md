# 072 Recurring Downtime

Preserve all earlier behavior. Add recurring downtime activities that campaign
members can allocate to owned characters and progress repeatedly.

## Downtime Activity Object

An activity response is exactly:

`{"activity_id":"activity-training","name":"Weapon training","cycles_required":2}`

`activity_id` and `name` must be nonempty strings. `cycles_required` must be an
integer from 1 through 10. Activity IDs must be unique within one campaign.

## Downtime Allocation Object

An allocation response is exactly:

`{"character_id":"play-char-w","activity_id":"activity-training","cycles_completed":0,"completions":0}`

`cycles_completed` tracks progress toward the next completion. `completions`
tracks how many times the recurring activity has completed for that character.

## Endpoints

`POST /v1/play/campaigns/{id}/downtime/activities`

Only the campaign DM may create downtime activities. Players receive 403.
Unknown campaigns return 404. Invalid payloads return 400. Duplicate activity
IDs return 409.

The request body is:

`{"activity_id":"activity-training","name":"Weapon training","cycles_required":2}`

A successful create returns 201 and the exact activity object.

`POST /v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations`

Only the player who owns `character_id` may allocate downtime. The DM receives
403. Non-owners receive 403. Unknown characters or activities return 404.
Duplicate allocations for the same character and activity return 409.

The body is:

`{"activity_id":"activity-training"}`

A successful allocation returns 201 and the exact allocation object with
`cycles_completed:0` and `completions:0`.

`POST /v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}/progress`

Only the player who owns `character_id` may progress downtime. The DM receives
403. Non-owners receive 403. Unknown characters, activities, or allocations
return 404.

Each successful progress call increments `cycles_completed`. When
`cycles_completed` reaches the activity's `cycles_required`, the server resets
`cycles_completed` to 0 and increments `completions`. The allocation can then be
progressed again for another recurring completion.

The response is exactly the updated allocation object.

`GET /v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}`

Authenticated campaign members may read an allocation. Unknown characters,
activities, or allocations return 404. The response is exactly the allocation
object.
