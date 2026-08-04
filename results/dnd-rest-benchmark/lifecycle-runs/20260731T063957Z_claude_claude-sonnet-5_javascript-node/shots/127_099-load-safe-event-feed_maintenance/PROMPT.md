```text
You are participating in a staged programming-language benchmark.

        Target: javascript-node
        Language: javascript
        Framework/runtime: node-stdlib
        Lifecycle stage: 099-load-safe-event-feed
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

        # 099 Load-Safe Event Feed

This cumulative suite inherits `098-spectator-view`.

Add an authenticated campaign-member append-only event feed with cursor
pagination that remains stable when new events are appended between reads. Do
not add ticket 100 behavior.

## Append Feed Events

`POST /v1/play/campaigns/{id}/feed-events`

Authentication: authenticated campaign members only, including the DM owner and
joined players.

Request body:

```json
{"event_id":"feed-1","text":"A"}
```

`event_id` and `text` must be nonempty strings. `event_id` must be unique
within the campaign feed.

Success status: `201 Created`

Exact success response:

```json
{"event_id":"feed-1","text":"A","sequence":1}
```

`sequence` is one-based accepted append order. Duplicate `event_id` returns
`409`. Invalid request bodies return `400`. Missing authentication returns
`401`. Authenticated nonmembers return `403`.

## Read Event Feed

`GET /v1/play/campaigns/{id}/event-feed?cursor=N&limit=N`

Authentication: authenticated campaign members only.

Both query parameters are optional. Defaults are `cursor=0` and `limit=2`.
`cursor` is the zero-based count of events already consumed and must be an
integer `>= 0`. `limit` must be an integer from `1` through `3`. Invalid
pagination parameters return `400`.

Exact success response:

```json
{"events":[...],"next_cursor":2}
```

`events` are accepted events in append order, each shaped exactly as
`{"event_id":"feed-1","text":"A","sequence":1}`. `next_cursor` is `cursor`
plus the returned event count. If `cursor` is greater than or equal to the
current feed length, return:

```json
{"events":[],"next_cursor":N}
```

Reads must never mutate the feed.

The evaluator verifies this load-safe interleaving:

1. Append `feed-1`/`A`, `feed-2`/`B`, and `feed-3`/`C`.
2. Read `cursor=0&limit=2` and receive `[feed-1, feed-2]`,
   `next_cursor=2`.
3. Append `feed-4`/`D`.
4. Read `cursor=2&limit=2` and receive `[feed-3, feed-4]`,
   `next_cursor=4`.
5. Read `cursor=4` and receive an empty page with `next_cursor=4`.



        Finish when ./run.sh is ready.
```
