# 081 Concurrent Turn Safety

This cumulative suite inherits `080-idempotency-keys`.

Preserve all earlier behavior. Add a campaign-scoped safe turn submission
endpoint that rejects stale turn submissions without changing queue state.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Non-member users return 403.

## Submit Safe Turn

`POST /v1/play/campaigns/{id}/safe-turns`

Authenticated campaign members, including the campaign owner, may submit safe
turn actions.

The deterministic request body is:

`{"submission_id":"submit-1","expected_turn":1,"action":"move"}`

`submission_id` and `action` must be nonempty strings. `expected_turn` must be
a positive integer. Invalid payloads return 400.

Per campaign safe-turn state starts at `current_turn` 1.

If `expected_turn` equals the campaign safe-turn `current_turn`, accept the
submission, advance exactly once, and return 201 with exact JSON:

`{"submission_id":"submit-1","action":"move","accepted_turn":1,"next_turn":2}`

Duplicate `submission_id` values are rejected with 409 and no state change.

If `expected_turn` differs from the current turn, reject the stale submission
with 409 and exact JSON:

`{"current_turn":2}`

Stale submissions must not advance the turn and must not appear in accepted
turn history.

## Read Safe Turns

`GET /v1/play/campaigns/{id}/safe-turns`

Campaign DM and members may read safe-turn state. The response is exact and
ordered by acceptance:

`{"current_turn":2,"accepted":[{"submission_id":"submit-1","action":"move","accepted_turn":1,"next_turn":2}]}`
