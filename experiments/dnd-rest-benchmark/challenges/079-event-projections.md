# 079 Event Projections

This cumulative suite inherits `078-actor-audit-trail`.

Preserve all earlier behavior. Add a campaign-scoped projection event log and a
deterministic projection rebuilt only from ordered projection events.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Non-member users return 403.

## Append Projection Event

`POST /v1/play/campaigns/{id}/projection-events`

Authenticated campaign player members may append projection events. The
campaign DM may read projections but may not append projection events.

Request bodies are one of:

`{"event_id":"event-1","kind":"set-story","value":"The road is clear."}`

`{"event_id":"event-2","kind":"increment-danger"}`

`event_id` must be a nonempty string and unique per campaign. Duplicate
`event_id` values return 409.

`kind` must be exactly `set-story` or `increment-danger`. Other values return
400.

For `set-story`, `value` is required and must be a nonempty string. For
`increment-danger`, `value` must be omitted. Invalid payloads return 400.

Success stores an immutable event with the next integer `sequence`, rebuilds
the projection from ordered events, and returns 201 with the stored event:

`{"sequence":1,"event_id":"event-1","kind":"set-story","value":"The road is clear."}`

`increment-danger` responses omit `value`:

`{"sequence":2,"event_id":"event-2","kind":"increment-danger"}`

## Read Projection

`GET /v1/play/campaigns/{id}/projection`

Campaign DM and members may read the projection.

The response is exact:

`{"story":"The road is clear.","danger":1,"applied_event_ids":["event-1","event-2"]}`

`story` is the latest `set-story` value by event sequence. `danger` starts at
0 and increments by 1 for each `increment-danger` event. `applied_event_ids`
lists all applied event IDs in sequence order.

## Rebuild Projection

`GET /v1/play/campaigns/{id}/projection/rebuild`

Campaign DM and members may request an explicit rebuild. The response must be
the same exact projection JSON as `GET /projection`, rebuilt solely from the
ordered event log.
