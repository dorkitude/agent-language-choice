# 093 Moderation Workflow

This cumulative suite inherits `092-rng-ledger`.

Preserve all earlier behavior. Add campaign-scoped moderation reports for
authenticated campaign members and a single DM-only resolution transition.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Non-member users return
403. The campaign DM is also a campaign member for report creation and reads.

## Submit Moderation Report

`POST /v1/play/campaigns/{id}/moderation/reports`

The request body is:

`{"report_id":"report-1","target_id":"event-1","reason":"spam"}`

Any authenticated campaign member, including the DM, may submit a report.
`report_id`, `target_id`, and `reason` must be nonempty strings. Missing or
empty strings return 400. `report_id` must be unique within the campaign;
duplicates return 409 and must not append or mutate any report.

Success returns 201 with the exact immutable open report record:

`{"report_id":"report-1","target_id":"event-1","reason":"spam","status":"open","reporter":"<username>","sequence":1}`

`sequence` is the accepted report append order, starting at 1.

## Read Moderation Reports

`GET /v1/play/campaigns/{id}/moderation/reports`

Authenticated campaign members, including the DM, may read moderation reports.
Reports must be returned in stable append order:

`{"reports":[{"report_id":"report-1","target_id":"event-1","reason":"spam","status":"open","reporter":"player-a","sequence":1}]}`

## Resolve Moderation Report

`PUT /v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution`

The request body is:

`{"action":"allow","note":"Reviewed and allowed."}`

Only the campaign DM may resolve reports. Players receive 403. Unknown reports
return 404. `action` must be exactly `allow` or `remove`, and `note` must be a
nonempty string. Missing/invalid action or empty note returns 400.

Resolving an open report returns 200 with the exact resolved record:

`{"report_id":"report-1","target_id":"event-1","reason":"spam","status":"resolved","reporter":"player-a","sequence":1,"action":"remove","note":"Removed duplicate spam event.","resolver":"dm"}`

Resolving the same report again returns 409 and must not mutate the record.
The report record is immutable except for this one transition from `open` to
`resolved`; append order and sequence values remain stable.
