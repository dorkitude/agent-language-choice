# 073 Session-Zero Settings

Preserve all earlier behavior. Add pre-start campaign session-zero settings for
rules version, tone, and consent boundaries.

## Session-Zero Settings Object

A settings response is exactly:

`{"rules":"2024","tone":"heroic","consent":["no-spiders","fade-to-black"]}`

`rules` and `tone` must be nonempty strings. `consent` must be a nonempty array
of unique nonempty strings. Consent order is preserved exactly as submitted.

## Endpoints

`PUT /v1/play/campaigns/{id}/session-zero`

Only the campaign DM may set session-zero settings. Players receive 403.
Unauthenticated requests receive 401. Unknown campaigns return 404. Invalid
payloads return 400. Settings can only be changed while campaign status is
`lobby`; after the campaign starts, updates return 409.

The deterministic request body is:

`{"rules":"2024","tone":"heroic","consent":["no-spiders","fade-to-black"]}`

A successful update returns 200 and the exact settings object.

`GET /v1/play/campaigns/{id}/session-zero`

Authenticated campaign members, including the DM and joined players, may read
stored settings. Unknown campaigns return 404. Missing settings return 404.
The response is exactly the stored settings object.
