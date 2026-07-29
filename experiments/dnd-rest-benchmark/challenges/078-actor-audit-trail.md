# 078 Actor Audit Trail

This cumulative suite inherits `077-gm-delegation`.

Preserve all earlier behavior. Add a campaign-scoped actor audit trail for
mutating campaign play events. For this ticket, automatic auditing is required
for the new audit mutation endpoint only; no retroactive auditing of earlier
mutation endpoints is required.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Non-member users return 403.

An audit entry is exactly:

`{"kind":"note","actor":"player-a","role":"player","timestamp":1,"correlation_id":"corr-1"}`

`actor` is the authenticated username. `role` is `DM` for the campaign owner
and `player` for campaign members. `timestamp` is a deterministic per-campaign
sequence starting at 1 and incrementing for every created audit entry.
`correlation_id` must be unique per campaign.

## Create Audit Event

`POST /v1/play/campaigns/{id}/audit-events`

Authenticated campaign members, including the campaign owner, may create audit
events. The deterministic request body is:

`{"kind":"note","correlation_id":"corr-1"}`

`kind` and `correlation_id` must be nonempty strings. Invalid payloads return
400. Duplicate `correlation_id` values in the same campaign return 409.

Success creates an immutable audit record and returns 201 with the exact audit
entry.

## Read Audit Events

`GET /v1/play/campaigns/{id}/audit-events`

Only the campaign owner may read the audit trail. Non-owner campaign members
receive 403.

Returns immutable entries in timestamp order:

`{"entries":[{"kind":"note","actor":"dm","role":"DM","timestamp":1,"correlation_id":"corr-dm"},{"kind":"note","actor":"player-a","role":"player","timestamp":2,"correlation_id":"corr-player"}]}`
