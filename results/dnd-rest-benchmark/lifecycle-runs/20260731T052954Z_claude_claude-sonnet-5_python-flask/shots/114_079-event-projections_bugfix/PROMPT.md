```text
You are participating in a staged programming-language benchmark.

        Target: python-flask
        Language: python
        Framework/runtime: flask
        Lifecycle stage: 079-event-projections
        Shot kind: bugfix

        You are a fresh bug-fix agent inheriting this existing codebase after a deterministic evaluator failure.

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
        Use Python 3.14.6 and Flask 3.1.3. Implement the REST API as Flask routes.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

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



The previous evaluator attempt did not pass. Before editing, inspect
`evaluations/079-03.json` and the raw logs it references. Fix the
implementation so the same evaluator suite passes without removing
previously implemented behavior.


        Finish when ./run.sh is ready.
```
