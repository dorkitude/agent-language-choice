# 094 Safety Boundaries

This cumulative suite inherits `093-moderation-workflow`.

Preserve all earlier behavior. Add campaign-scoped safety boundaries and
accepted safety events. All endpoints use `Authorization: Bearer
session-<username>`. Unauthenticated requests return 401. Unknown campaigns
return 404. Non-member users return 403. The campaign DM is considered a
campaign member for reads and safety checks.

## Replace Safety Boundaries

`PUT /v1/play/campaigns/{id}/safety-boundaries`

The request body is:

`{"blocked_tags":["gore","spiders"]}`

Only the campaign DM may replace boundaries. Players receive 403.
`blocked_tags` is required and must be a nonempty array of unique nonempty
strings. Missing, empty, non-string, blank/empty string, or duplicate tags
return 400.

Replacement is atomic: invalid requests must not mutate the previous boundary
state. Success returns 200 with the exact full current state, with tags sorted
lexicographically:

`{"blocked_tags":["gore","spiders"]}`

## Read Safety Boundaries

`GET /v1/play/campaigns/{id}/safety-boundaries`

Authenticated campaign members, including the DM, may read the exact current
boundary state:

`{"blocked_tags":["gore","spiders"]}`

The response must match the last successful replacement and keep
lexicographic order.

## Submit Safety Check

`POST /v1/play/campaigns/{id}/safety-checks`

The request body is:

`{"event_id":"safe-1","kind":"narration","text":"The party enters a quiet hall.","tags":["calm","exploration"]}`

Any authenticated campaign member, including the DM, may submit a safety
check. `event_id` and `text` must be nonempty strings. `kind` must be exactly
`narration` or `chat`. `tags` is required and must be a nonempty array of
unique nonempty strings. Missing or invalid fields return 400.

If `event_id` was already accepted in this campaign, return 409 and do not
append or mutate events. If any submitted tag is present in the current
`blocked_tags`, return 409 and do not append or mutate events.

Accepted checks append one event and return 201 with exactly:

`{"event_id":"safe-1","kind":"narration","text":"The party enters a quiet hall.","tags":["calm","exploration"],"sequence":1}`

`sequence` is the accepted safety event append order, starting at 1. The
response keeps the submitted tag order.

## Read Safety Events

`GET /v1/play/campaigns/{id}/safety-events`

Authenticated campaign members, including the DM, may read accepted safety
events. Events are returned in stable append order:

`{"events":[{"event_id":"safe-1","kind":"narration","text":"The party enters a quiet hall.","tags":["calm","exploration"],"sequence":1}]}`

Rejected blocked-tag checks, duplicate event IDs, and invalid requests must
not appear in this list.
