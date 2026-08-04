```text
You are participating in a staged programming-language benchmark.

        Target: go-stdlib
        Language: go
        Framework/runtime: stdlib
        Lifecycle stage: 088-service-metrics
        Shot kind: maintenance

        You are a fresh maintenance agent inheriting this existing codebase. Add the requested feature stage while preserving all existing API behavior.

        Use the exact latest runtime/framework versions already pinned in this
        workspace. Do not downgrade packages or replace the requested framework.

        Relevant version pins:
        - @types/node: 26.1.1
- @types/react: 19.2.17
- @types/react-dom: 19.2.3
- @vitejs/plugin-react: 6.0.3
- composer: 2.10.2
- django: 6.0.7
- flask: 3.1.3
- go: 1.26.5
- next: 16.2.10
- node: 26.4.0
- openjdk: 26.0.1
- php: 8.5.8
- puma: 8.0.2
- python: 3.14.6
- rack: 3.2.6
- rackup: 2.3.1
- rails: 8.1.3
- react: 19.2.7
- react-dom: 19.2.7
- ruby: 4.0.5
- rust: 1.97.0
- sinatra: 4.2.1
- slim: 4.15.2
- slim-psr7: 1.8.0
- symfony-http-foundation: 8.1.1
- symfony-routing: 8.1.0
- typescript: 7.0.2
- vite: 8.1.3

        Target guidance:
        Use Go 1.26.5, net/http, and encoding/json. Do not add third-party packages.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

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



        Finish when ./run.sh is ready.
```
