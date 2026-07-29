# 066 World Events

This cumulative suite inherits `065-quest-rewards`.

Preserve all earlier behavior. Add deterministic campaign-level world events
that the DM can schedule for a campaign turn and resolve exactly once when that
turn is reached.

`POST /v1/play/campaigns/{id}/world-events` accepts:

`{"event_id":"world-storm","turn_number":4,"title":"Storm Front","text":"Black clouds gather over the cave road."}`

Only the campaign DM may schedule world events. Players receive 403. The
`event_id`, `title`, and `text` fields must be nonempty strings. `turn_number`
must be an integer greater than or equal to the campaign's current
`turn_number`. Invalid bodies return 400. Duplicate event IDs in the same
campaign return 409.

A valid schedule request returns 201 exactly:

`{"event_id":"world-storm","turn_number":4,"title":"Storm Front","text":"Black clouds gather over the cave road.","status":"scheduled"}`

`POST /v1/play/campaigns/{id}/world-events/{event_id}/resolve` accepts:

`{"text":"Rain floods the trail and slows any retreat."}`

Only the campaign DM may resolve world events. Players receive 403. Unknown
events return 404. The resolution `text` must be nonempty. If the campaign's
current turn number does not exactly match the event `turn_number`, resolution
returns 409. If the event is already resolved, resolution returns 409 and does
not change the stored resolution.

A successful resolution records an immutable resolution and returns 201 exactly:

`{"event_id":"world-storm","turn_number":4,"title":"Storm Front","text":"Black clouds gather over the cave road.","status":"resolved","resolution":{"turn_number":4,"text":"Rain floods the trail and slows any retreat."}}`

`GET /v1/play/campaigns/{id}/world-events` is available to authenticated
campaign members. It returns the campaign's world events ordered by
`turn_number` ascending, then creation order for events scheduled on the same
turn:

`{"events":[{"event_id":"world-storm","turn_number":4,"title":"Storm Front","text":"Black clouds gather over the cave road.","status":"resolved","resolution":{"turn_number":4,"text":"Rain floods the trail and slows any retreat."}}]}`
