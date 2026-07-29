# 082 Transaction Recovery

This cumulative suite inherits `081-concurrent-turn-safety`.

Preserve all earlier behavior. Add a campaign-scoped transactional currency
transfer endpoint where failed compound mutations leave no partial debit,
credit, or transfer record.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Non-member users return 403.

## Create Transactional Transfer

`POST /v1/play/campaigns/{id}/transactional-transfers`

Only the player who owns `from_character_id` may create the transfer. The
destination must be a different character in the same campaign. The amount
must be a positive integer and the source character must have sufficient gold.
Invalid character IDs, self-transfers, malformed payloads, and non-positive
amounts return 400. Insufficient balance returns 409.

The deterministic request body is:

`{"from_character_id":"play-char-w","to_character_id":"play-char-b","amount":2,"simulate_failure":false}`

If `simulate_failure` is true, the server must validate and prepare the
operation, then return 500 with exact JSON:

`{"error":"simulated failure"}`

The simulated failure must not change either character balance and must not
append a transfer record.

On success, debit and credit are committed together, append one ordered
success record, and return 201 with exact JSON:

`{"from_character_id":"play-char-w","to_character_id":"play-char-b","amount":2,"from_gold":7,"to_gold":12,"sequence":1}`

## Read Transactional Transfers

`GET /v1/play/campaigns/{id}/transactional-transfers`

Campaign DM and members may read successful transactional transfers. Failed
simulated operations must never appear. The response is exact and ordered by
successful transfer sequence:

`{"transfers":[{"from_character_id":"play-char-w","to_character_id":"play-char-b","amount":2,"from_gold":7,"to_gold":12,"sequence":1}]}`
