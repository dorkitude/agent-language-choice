```text
You are participating in a staged programming-language benchmark.

        Target: javascript-node
        Language: javascript
        Framework/runtime: node-stdlib
        Lifecycle stage: 068-calendar-and-weather
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
        Use Node 26.4.0 built-in HTTP APIs and plain JavaScript modules. Do not use TypeScript, frameworks, or third-party packages.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 068 Calendar and Weather

Preserve all earlier behavior. Add a campaign calendar that the DM initializes
once, advances in bounded day increments, and exposes to authenticated campaign
members with deterministic weather.

`POST /v1/play/campaigns/{id}/calendar` accepts:

`{"day":1,"season":"spring"}`

Only the campaign DM may initialize the calendar. Players receive 403. `day`
must be an integer greater than or equal to 1. `season` must be one of
`spring`, `summer`, `autumn`, or `winter`. Invalid payloads return 400.
Initializing an already initialized calendar for the same campaign returns 409.
Unknown campaigns return 404.

The response is exactly:

`{"day":1,"season":"spring","weather":"rain"}`

Weather is derived from the current `day` and `season` by this simple function:
assign season offsets `spring=0`, `summer=1`, `autumn=2`, `winter=3`; compute
`(day + season_offset) % 4`; map `0=clear`, `1=rain`, `2=wind`, `3=snow`.

`GET /v1/play/campaigns/{id}/calendar` is available to authenticated campaign
members, including the DM and joined players. It returns exactly:

`{"day":1,"season":"spring","weather":"rain"}`

If the calendar has not been initialized, GET returns 404.

`POST /v1/play/campaigns/{id}/calendar/advance` accepts:

`{"days":5}`

Only the campaign DM may advance the calendar. Players receive 403. `days` must
be an integer from 1 through 30. Advancing a noninitialized calendar returns
404. A successful advance increments the current day by `days` and returns the
new exact calendar object with deterministic weather.



        Finish when ./run.sh is ready.
```
