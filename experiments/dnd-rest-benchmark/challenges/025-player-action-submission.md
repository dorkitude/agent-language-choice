# Maintenance Stage 25: Player Action Submission

Only the active player can call `POST /v1/play/campaigns/{id}/actions` with
`{"type":"search","text":"I examine the trail."}`. Append an action event
and return 201 with `sequence`, `kind:"action"`, `actor`, `type`, `text`, and
`next_actor:"dm"`. A waiting player or the DM receives 409.
