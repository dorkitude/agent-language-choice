```text
You are participating in a staged programming-language benchmark.

        Target: rust-stdlib
        Language: rust
        Framework/runtime: stdlib
        Lifecycle stage: 089-readiness-health
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
        Use Rust 1.97.0 and the standard library only. Do not add Cargo dependencies or HTTP crates. Implement HTTP handling with std::net::TcpListener/TcpStream and serde-free JSON string handling.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

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



        Finish when ./run.sh is ready.
```
