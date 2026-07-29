# 090 Backup and Restore

This cumulative suite inherits `089-readiness-health`.

Preserve all earlier behavior. Add owner-only campaign backups that snapshot
the current public campaign story and status, and restore exactly one existing
snapshot without mutating the snapshot itself.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Authenticated players,
including campaign members, cannot create, list, or restore backups and receive
403.

## Create Backup

`POST /v1/play/campaigns/{id}/backups`

Only the campaign DM may create a backup. The request body is empty. Each
successful call creates a new immutable snapshot whose `backup_id` is
sequential in the form `backup-1`, `backup-2`, and so on. The snapshot captures
exactly the campaign document's current public `story` and the campaign's
current `status`.

For a campaign whose story is `Story A: the party secures the old keep.` and
status is `active`, the first backup returns 201 with exact JSON:

`{"backup_id":"backup-1","story":"Story A: the party secures the old keep.","status":"active"}`

## List Backups

`GET /v1/play/campaigns/{id}/backups`

Only the campaign DM may list backups. The response is exact JSON with backups
ordered by creation sequence:

`{"backups":[{"backup_id":"backup-1","story":"Story A: the party secures the old keep.","status":"active"}]}`

Backups are immutable. Mutating the campaign document or restoring a backup
must not change any existing listed snapshot.

## Restore Backup

`POST /v1/play/campaigns/{id}/backups/{backup_id}/restore`

Only the campaign DM may restore a backup. Existing backups apply exactly the
snapshot's `story` and `status` to the campaign and return HTTP 200 with the
restored snapshot as exact JSON:

`{"backup_id":"backup-1","story":"Story A: the party secures the old keep.","status":"active"}`

Unknown backup IDs return 404. Restoring a backup must not duplicate event
identities or create a new backup snapshot.
