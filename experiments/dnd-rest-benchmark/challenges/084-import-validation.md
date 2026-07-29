# 084 Import Validation

This cumulative suite inherits `083-versioned-export`.

Preserve all earlier behavior. Add DM-only campaign imports that accept only
compatible version 1 snapshots and apply the imported story and status
atomically.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Only the campaign DM may
create imports or read imported state; other authenticated users receive 403.

## Import Snapshot

`POST /v1/play/campaigns/{id}/imports`

The request body must be exact compatible snapshot data with `version`,
`story`, and `status`. The only valid version is `1`. `story` must be nonempty.
`status` must be either `lobby` or `started`.

Invalid imports return 400 and must not change campaign or imported state.
Valid imports apply `story` and `status` atomically and return 200 with exact
JSON:

`{"version":1,"story":"Imported","status":"lobby"}`

## Read Imported State

`GET /v1/play/campaigns/{id}/import-state`

Only the campaign DM may read the current imported state. Before the first
successful import, this endpoint returns 404. After a successful import, it
returns exact JSON:

`{"version":1,"story":"Imported","status":"lobby"}`
