# 080 Idempotency Keys

This cumulative suite inherits `079-event-projections`.

Preserve all earlier behavior. Add a campaign-scoped idempotent event endpoint
where duplicate mutating requests with the same idempotency key have exactly
one public effect.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Non-member users return 403.

## Create Idempotent Event

`POST /v1/play/campaigns/{id}/idempotent-events`

Authenticated campaign members, including the campaign owner, may create
idempotent events.

The `Idempotency-Key` header is mandatory and must be a nonempty string after
trimming whitespace. Missing or empty keys return 400.

The deterministic request body is:

`{"event_id":"idem-1","value":"once"}`

`event_id` and `value` must be nonempty strings. Invalid payloads return 400.
`event_id` must be unique per campaign across successful effects. Reusing an
existing `event_id` with a different idempotency key returns 409.

The first valid request for a key stores an immutable event with the next
integer `sequence` and returns 201 with exact JSON:

`{"event_id":"idem-1","value":"once","sequence":1,"idempotency_key":"key-1"}`

Repeating the same `Idempotency-Key` with the same `event_id` and `value`
returns 200 with the identical stored event and does not append another event.

Repeating the same `Idempotency-Key` with a different `event_id` or `value`
returns 409 and does not append another event.

A different idempotency key with a new event ID creates the next sequence.

## Read Idempotent Events

`GET /v1/play/campaigns/{id}/idempotent-events`

Campaign DM and members may read idempotent events. The response is exact and
ordered by event sequence:

`{"events":[{"event_id":"idem-1","value":"once","sequence":1,"idempotency_key":"key-1"},{"event_id":"idem-2","value":"twice","sequence":2,"idempotency_key":"key-2"}]}`
