# 085 Schema Migration

This cumulative suite inherits `084-import-validation`.

Preserve all earlier behavior. Add DM-only campaign schema migrations that
accept only legacy schema version 1 snapshots and deterministically migrate
them to schema version 2.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Only the campaign DM may
create migrations or read migrated state; other authenticated users receive
403.

## Migrate Snapshot

`POST /v1/play/campaigns/{id}/migrations`

The request body must contain `schema_version` and `story`. The only valid input
schema version is `1`. `story` must be nonempty.

Invalid migrations return 400 and must not change migrated state. A valid
migration preserves `story`, sets `schema_version` to `2`, sets
`campaign_name` to the campaign's name, and returns 201 with exact JSON:

`{"schema_version":2,"story":"Legacy story","campaign_name":"Legacy Game"}`

Repeating the same valid version 1 source snapshot is idempotent: it returns 200
with the same migrated state and does not create a new state.

## Read Migrated State

`GET /v1/play/campaigns/{id}/migration-state`

Only the campaign DM may read the current migrated state. Before the first
successful migration, this endpoint returns 404. After a successful migration,
it returns exact JSON:

`{"schema_version":2,"story":"Legacy story","campaign_name":"Legacy Game"}`
