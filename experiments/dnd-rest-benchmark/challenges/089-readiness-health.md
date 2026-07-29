# 089 Readiness/Health

This cumulative suite inherits `088-service-metrics`.

Preserve all earlier behavior. Add public liveness and readiness endpoints plus
a DM-controlled global maintenance switch.

## Liveness

`GET /healthz`

This endpoint is public. It always returns HTTP 200 with exact JSON:

`{"status":"ok"}`

Maintenance mode must not affect liveness.

## Readiness

`GET /readyz`

This endpoint is public. When the service is not in maintenance mode it returns
HTTP 200 with exact JSON:

`{"status":"ready","schema_version":2}`

When the service is in maintenance mode it returns HTTP 503 with exact JSON:

`{"status":"maintenance","schema_version":2}`

## Service Mode

`POST /v1/play/campaigns/{id}/service-mode`

The request body is exact JSON:

`{"maintenance":true}`

or:

`{"maintenance":false}`

Only an authenticated DM may change service mode. Player requests return HTTP
403. Unknown campaigns return HTTP 404. Unauthenticated requests return HTTP
401.

Successful requests return HTTP 200 with exact JSON containing the current
global mode:

`{"maintenance":true}`

or:

`{"maintenance":false}`

The mode is process-global reference service state for the current test-run
server, not campaign-local state. After a DM enables maintenance through any
campaign, public `GET /readyz` must report maintenance until a DM disables it.
