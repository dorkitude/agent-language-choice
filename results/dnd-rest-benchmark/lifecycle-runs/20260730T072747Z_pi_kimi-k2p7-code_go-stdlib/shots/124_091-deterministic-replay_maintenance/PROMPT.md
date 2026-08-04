```text
You are participating in a staged programming-language benchmark.

        Target: go-stdlib
        Language: go
        Framework/runtime: stdlib
        Lifecycle stage: 091-deterministic-replay
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

        # 091 Deterministic Replay

This cumulative suite inherits `090-backup-restore`.

Preserve all earlier behavior. Add a deterministic replay stream for campaign
members. Replay events are campaign-scoped, authenticated, ordered by
successful append order, and rebuild a public replay state without randomness.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Non-member users return
403. The campaign DM and campaign members may append replay events and read
replay state.

## Append Replay Event

`POST /v1/play/campaigns/{id}/replay-events`

The deterministic request body is:

`{"event_id":"replay-1","kind":"append","text":"A"}`

`event_id` and `text` must be nonempty strings. `event_id` must be unique
within the campaign replay stream. `kind` must be exactly `append`; other
kinds return 400. Duplicate `event_id` values return 409 and must not mutate
replay state.

Successful appends return 201 with exact JSON containing creation sequence:

`{"event_id":"replay-1","kind":"append","text":"A","sequence":1}`

## Read Replay

`GET /v1/play/campaigns/{id}/replay`

Authenticated campaign members read exact deterministic replay state. The
`story` is the ordered concatenation of all append event `text` values.
`event_ids` is the ordered list of successful replay event IDs. `digest` is a
simple deterministic hash substitute defined as:

`strings.Join(event_ids, ",") + "|" + story`

After appending `replay-1` with text `A` and `replay-2` with text `B`, the
exact response is:

`{"story":"AB","event_ids":["replay-1","replay-2"],"digest":"replay-1,replay-2|AB"}`

## Check Replay

`GET /v1/play/campaigns/{id}/replay/check`

Returns the same exact deterministic state as `GET /replay`. This endpoint is
an explicit replay verification path and must not mutate state.



        Finish when ./run.sh is ready.
```
