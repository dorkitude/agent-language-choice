# 083 Versioned Export

This cumulative suite inherits `082-transaction-recovery`.

Preserve all earlier behavior. Add DM-only campaign exports that snapshot the
campaign's current public story and status into immutable, sequential versions.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Authenticated players,
including campaign members, cannot create or read exports and receive 403.

## Create Export

`POST /v1/play/campaigns/{id}/exports`

Only the campaign DM may create an export. The request body is empty. Each
successful call creates a new immutable snapshot whose version is one greater
than the campaign's previous export count. The snapshot captures exactly the
campaign document's current `story` and the campaign's current `status`.

For a campaign whose story is `The party reaches the glass gate.` and status is
`active`, the first export returns 201 with exact JSON:

`{"version":1,"story":"The party reaches the glass gate.","status":"active"}`

## List Exports

`GET /v1/play/campaigns/{id}/exports`

Only the campaign DM may list exports. The response is exact JSON with exports
ordered by ascending version:

`{"exports":[{"version":1,"story":"The party reaches the glass gate.","status":"active"},{"version":2,"story":"The glass gate opens to a blue stair.","status":"active"}]}`

## Read Export

`GET /v1/play/campaigns/{id}/exports/{version}`

Only the campaign DM may read a specific export. Existing versions return the
exact immutable snapshot. Unknown versions return 404.
