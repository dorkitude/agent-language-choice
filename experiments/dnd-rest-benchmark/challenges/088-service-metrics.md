# 088 Service Metrics

This cumulative suite inherits `087-rate-limits`.

Preserve all earlier behavior. Add campaign-scoped service metrics that expose
only safe aggregate counters and no campaign story, character, event, or actor
content.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Only the campaign owner may
read metrics; campaign players and other authenticated users receive 403.

## Read Metrics

`GET /v1/play/campaigns/{id}/metrics`

The response is exact JSON:

`{"accepted_rate_events":0,"rejected_rate_events":0,"projection_events":0,"uptime_ticks":1}`

For a fresh campaign, all event counters start at zero and `uptime_ticks` is
always `1`.

`accepted_rate_events` increments exactly once for each accepted ticket 087 rate
event.

`rejected_rate_events` increments exactly once for each ticket 087 rate event
rejected with HTTP 429.

`projection_events` increments exactly once for each accepted ticket 079
projection event append.

Rejected, invalid, duplicate, idempotent replay, and unrelated requests must not
change these counters.
