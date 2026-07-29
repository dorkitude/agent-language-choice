# 096 API Schema Endpoint

This cumulative suite inherits `095-fixture-seeding`.

Preserve all earlier behavior. Add a public API schema endpoint with no dynamic
state, no authorization requirement, and no map-order dependence.

## Read API Schema

`GET /v1/schema`

This endpoint is public. It must return 200 without an `Authorization` header.

Return exactly:

`{"version":"2026-07-29","endpoints":[...]}`

`endpoints` must be sorted lexicographically by `method`, then `path`. Each item
must have exactly:

`{"method":"GET|POST|PUT","path":"...","auth":"public|member|dm"}`

For this ticket, the exact full endpoint list is:

`[{"method":"GET","path":"/v1/play/campaigns/{id}/rng-ledger","auth":"member"},{"method":"GET","path":"/v1/schema","auth":"public"},{"method":"POST","path":"/v1/play/campaigns","auth":"dm"},{"method":"POST","path":"/v1/play/campaigns/{id}/fixture-seeds","auth":"dm"},{"method":"POST","path":"/v1/play/campaigns/{id}/members","auth":"member"},{"method":"POST","path":"/v1/play/campaigns/{id}/moderation/reports","auth":"member"},{"method":"POST","path":"/v1/play/campaigns/{id}/rng-rolls","auth":"member"},{"method":"PUT","path":"/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution","auth":"dm"},{"method":"PUT","path":"/v1/play/campaigns/{id}/rng-seed","auth":"dm"},{"method":"PUT","path":"/v1/play/campaigns/{id}/safety-boundaries","auth":"dm"}]`

Reading the schema must not create, modify, or delete any campaign or fixture
state. Repeated reads must return the same exact JSON shape and values.
