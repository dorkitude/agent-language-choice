# 077 GM Delegation

This cumulative suite inherits `076-campaign-invitations`.

Preserve all earlier behavior. Add campaign-scoped GM delegation so the
campaign owner can grant and revoke limited co-GM authority for an existing
campaign member. The only delegated power in this ticket is `narrate`.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404.

A delegation record is exactly:

`{"username":"player-b","powers":["narrate"],"active":true}`

An inactive revoked delegation record is exactly:

`{"username":"player-b","powers":["narrate"],"active":false}`

`username` must be a campaign member. `powers` must be a nonempty array of
unique valid values. For this ticket, the only valid value is `narrate`.

## Grant Delegation

`POST /v1/play/campaigns/{id}/delegations`

Only the campaign owner may grant delegation. The deterministic request body is:

`{"username":"player-b","powers":["narrate"]}`

Success returns 201 and the exact active delegation record. Invalid payloads,
unknown/non-member targets, empty powers, duplicate powers, and powers other
than `narrate` return 400. A duplicate active delegate for the same username
returns 409. Non-owner campaign members receive 403.

An active delegate with `narrate` may use the existing
`POST /v1/play/campaigns/{id}/narrations` endpoint. Nondelegated players still
receive 403 from that endpoint.

## Revoke Delegation

`DELETE /v1/play/campaigns/{id}/delegations/{username}`

Only the campaign owner may revoke delegation. Success returns 200 and the exact
inactive delegation record. After revocation, the target user can no longer
narrate and receives 403 from `POST /v1/play/campaigns/{id}/narrations`.

## Audit

`GET /v1/play/campaigns/{id}/delegations/audit`

Only the campaign owner may read delegation audit. Non-owner campaign members
receive 403.

Returns immutable entries in grant/revoke order:

`{"entries":[{"username":"player-b","action":"granted","powers":["narrate"]},{"username":"player-b","action":"revoked","powers":["narrate"]}]}`
